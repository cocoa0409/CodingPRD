"""Cross-aggregate side effects: cascades, repricing, shared lookups."""
from common import DB, by_seq, touch, clock_date
import calc


def project_utilities(project_id):
    return by_seq([u for u in DB.utilities.values() if u["adu_project_id"] == project_id])


def project_submittals(project_id):
    return by_seq([s for s in DB.submittals.values() if s["adu_project_id"] == project_id])


def project_phases(project_id):
    return by_seq([p for p in DB.phases.values() if p["adu_project_id"] == project_id])


def project_appointments(project_id):
    return by_seq([a for a in DB.appointments.values() if a["adu_project_id"] == project_id])


def phase_appointments(phase_id):
    return by_seq(
        [a for a in DB.appointments.values() if a["construction_phase_id"] == phase_id]
    )


def submittal_corrections(submittal_id):
    return by_seq(
        [c for c in DB.corrections.values() if c["permit_submittal_id"] == submittal_id]
    )


def project_scenarios(project_id):
    return by_seq([s for s in DB.scenarios.values() if s["adu_project_id"] == project_id])


def project_change_orders(project_id):
    return by_seq([c for c in DB.change_orders.values() if c["adu_project_id"] == project_id])


def latest_submittal(project_id):
    rows = project_submittals(project_id)
    return rows[-1] if rows else None


def committed_scenario(project_id):
    for s in project_scenarios(project_id):
        if s["status"] == "COMMITTED":
            return s
    return None


# ---------------------------------------------------------------------------
# Plan-check correction cascade (four links)
# ---------------------------------------------------------------------------
def block_scheduled_phases(project):
    """Link 3 and link 4: SCHEDULED phases -> BLOCKED, their open appointments -> CANCELLED."""
    for phase in project_phases(project["id"]):
        if phase["status"] != "SCHEDULED":
            continue
        phase["status"] = "BLOCKED"
        phase["window_start_date"] = None
        phase["window_end_date"] = None
        touch(phase)
        for appt in phase_appointments(phase["id"]):
            if appt["status"] in ("SCHEDULED", "PARTIAL"):
                appt["status"] = "CANCELLED"
                touch(appt)


# ---------------------------------------------------------------------------
# Financing repricing (change-order funding chain, link 3)
# ---------------------------------------------------------------------------
def reprice_committed_scenario(project):
    """Recompute required_funds/funding_gap on the project's single COMMITTED scenario
    and move the funding axis accordingly."""
    scenario = committed_scenario(project["id"])
    if scenario is None:
        return
    prop = DB.properties.get(project["property_id"])
    result = calc.financing_capacity(scenario, project, prop)
    scenario["required_funds_cents"] = result["required_funds_cents"]
    scenario["funding_gap_cents"] = result["funding_gap_cents"]
    touch(scenario)

    if project["financing_state"] == "COMMITTED" and result["funding_gap_cents"] > 0:
        project["financing_state"] = "SHORTFALL"
    elif project["financing_state"] == "SHORTFALL" and result["funding_gap_cents"] == 0:
        project["financing_state"] = "COMMITTED"


# ---------------------------------------------------------------------------
# Metering reversal (first approved change order with a non-zero cost delta)
# ---------------------------------------------------------------------------
def revert_separate_utility_decisions(project):
    for uc in project_utilities(project["id"]):
        if uc["status"] == "SEPARATE_APPROVED":
            uc["status"] = "PENDING_DECISION"
            uc["decision"] = None
            uc["separation_score"] = 0
            uc["separation_cost_cents"] = 0
            touch(uc)
