"""Donor risk scoring, deferral bookkeeping and the lookback recall cascade
(PRD 3.1 - 3.3)."""

from decimal import Decimal

import domain_dispense
import domain_pool
from store import db, find, insert, set_field
from util import add_days, days_between, fmt_date, parse_date, round_half_up

MEDICATION_WEIGHT = 8
TRAVEL_WEIGHT = 25
TOBACCO_WEIGHT = 40
POSTPARTUM_FREE_MONTHS = 12
POSTPARTUM_PER_MONTH = 3
POSTPARTUM_CAP = 30
SEROLOGY_PENDING_PENALTY = 20
TEMP_DEFERRAL_WEIGHT = 15
DECAY_HALF_LIFE_DAYS = 180
SCORE_CAP = 100
RISK_ACCEPT_MAX = 60
RISK_DEFER_MAX = 85
AUTO_DEFERRAL_DAYS = 90
SEROLOGY_VALIDITY_DAYS = 180
PHYSICIAN_APPROVAL_VALIDITY_DAYS = 365
REACTIVE_LOOKBACK_DAYS = 365

RECALLABLE_DONATION_STATES = ("ELIGIBLE", "ALLOCATED", "PASTEURIZED")
RECALLABLE_LOT_STATES = ("HOLD", "RELEASED", "EXHAUSTED")


# --- lookups ---------------------------------------------------------------
def questionnaires_of(donor_id):
    return [q for q in db.rows("questionnaires") if q["donor_id"] == donor_id]


def newest_questionnaire(donor_id):
    rows = questionnaires_of(donor_id)
    if not rows:
        return None
    rows.sort(key=lambda q: (q["created_at"], q["submitted_at"], q["_seq"]),
              reverse=True)
    return rows[0]


def serology_of(donor_id):
    return [s for s in db.rows("serology") if s["donor_id"] == donor_id]


def approvals_of(donor_id):
    return [a for a in db.rows("approvals") if a["donor_id"] == donor_id]


def deferrals_of(donor_id):
    return [d for d in db.rows("deferrals") if d["donor_id"] == donor_id]


def donations_of(donor_id):
    return [d for d in db.rows("donations") if d["donor_id"] == donor_id]


def has_valid_serology(donor_id):
    today = db.clock_date()
    for panel in serology_of(donor_id):
        if panel["panel_status"] != "NON_REACTIVE":
            continue
        expires = parse_date(panel["expires_on"])
        if expires is not None and expires >= today:
            return True
    return False


def has_active_approval(donor_id):
    today = db.clock_date()
    for approval in approvals_of(donor_id):
        if approval["status"] != "ACTIVE":
            continue
        valid_until = parse_date(approval["valid_until"])
        if valid_until is not None and valid_until >= today:
            return True
    return False


def counted_temp_deferrals(donor_id):
    return [
        d for d in deferrals_of(donor_id)
        if d["deferral_type"] == "TEMPORARY" and d["status"] in ("ACTIVE", "EXPIRED")
    ]


# --- risk scoring ----------------------------------------------------------
def base_points(questionnaire):
    if questionnaire is None:
        return 0
    units = questionnaire["alcohol_units_per_week"]
    if units == 0:
        alcohol = 0
    elif units <= 3:
        alcohol = 5
    elif units <= 7:
        alcohol = 15
    else:
        alcohol = 45
    over = questionnaire["months_postpartum"] - POSTPARTUM_FREE_MONTHS
    if over < 0:
        over = 0
    postpartum = over * POSTPARTUM_PER_MONTH
    if postpartum > POSTPARTUM_CAP:
        postpartum = POSTPARTUM_CAP
    return (
        questionnaire["medication_flag_count"] * MEDICATION_WEIGHT
        + (TRAVEL_WEIGHT if questionnaire["travel_risk_flag"] else 0)
        + (TOBACCO_WEIGHT if questionnaire["tobacco_use"] else 0)
        + alcohol
        + postpartum
    )


def screening_score(donor, base=None):
    """SCREENING_WORST_CASE: undecayed, with the pending-serology penalty."""
    if base is None:
        base = base_points(newest_questionnaire(donor["id"]))
    penalty = 0 if has_valid_serology(donor["id"]) else SEROLOGY_PENDING_PENALTY
    history = TEMP_DEFERRAL_WEIGHT * len(counted_temp_deferrals(donor["id"]))
    total = base + penalty + history
    return SCORE_CAP if total > SCORE_CAP else total


def surveillance_score(donor, base=None):
    """SURVEILLANCE_DECAYED: no serology term, deferrals halved every 180 days."""
    if base is None:
        base = base_points(newest_questionnaire(donor["id"]))
    today = db.clock_date()
    decayed = 0.0
    for event in counted_temp_deferrals(donor["id"]):
        effective_from = parse_date(event["effective_from"])
        if effective_from is None:
            continue
        age = days_between(effective_from, today)
        decayed += TEMP_DEFERRAL_WEIGHT * (0.5 ** (float(age) / DECAY_HALF_LIFE_DAYS))
    total = int(round_half_up(Decimal(repr(base + decayed)), 0))
    return SCORE_CAP if total > SCORE_CAP else total


def refresh_scores(donor):
    base = base_points(newest_questionnaire(donor["id"]))
    set_field(donor, "screening_risk_score", screening_score(donor, base))
    set_field(donor, "surveillance_risk_score", surveillance_score(donor, base))


def refresh_surveillance(donor):
    set_field(donor, "surveillance_risk_score", surveillance_score(donor))


# --- donor derived ledgers -------------------------------------------------
def refresh_temporary_deferral_count(donor):
    count = len([
        d for d in deferrals_of(donor["id"]) if d["deferral_type"] == "TEMPORARY"
    ])
    set_field(donor, "temporary_deferral_count", count)


def refresh_active_deferral_until(donor):
    """End date of the MOST RECENTLY CREATED active temporary deferral."""
    candidates = [
        d for d in deferrals_of(donor["id"])
        if d["deferral_type"] == "TEMPORARY" and d["status"] == "ACTIVE"
    ]
    if not candidates:
        set_field(donor, "active_deferral_until_date", None)
        return
    candidates.sort(key=lambda d: (d["created_at"], d["_seq"]), reverse=True)
    newest = candidates[0]
    effective_from = parse_date(newest["effective_from"])
    if effective_from is None:
        set_field(donor, "active_deferral_until_date", None)
        return
    set_field(donor, "active_deferral_until_date",
              fmt_date(add_days(effective_from, newest["deferral_days"])))


def refresh_lifetime_volume(donor):
    total = sum(
        d["volume_ml"] for d in donations_of(donor["id"])
        if d["status"] in ("ELIGIBLE", "ALLOCATED", "PASTEURIZED")
    )
    set_field(donor, "lifetime_accepted_volume_ml", total)


# --- deferral events -------------------------------------------------------
def create_deferral(donor, reason_code, deferral_type, effective_from,
                    deferral_days, lookback_days, recall_scope, recorded_by):
    return insert("deferrals", {
        "donor_id": donor["id"],
        "reason_code": reason_code,
        "deferral_type": deferral_type,
        "effective_from": fmt_date(effective_from),
        "deferral_days": deferral_days,
        "lookback_days": lookback_days,
        "recall_scope": recall_scope,
        "status": "ACTIVE",
        "recalled_donation_count": 0,
        "quarantined_pool_count": 0,
        "recalled_lot_count": 0,
        "recalled_dispense_count": 0,
        "reversed_subsidy_cents": 0,
        "recorded_by_user_id": recorded_by,
    })


def apply_deferral(donor, event):
    """Donor consequences of a deferral event, then its recall cascade."""
    if event["deferral_type"] == "PERMANENT":
        set_field(donor, "status", "PERMANENTLY_DEFERRED")
    else:
        set_field(donor, "status", "TEMPORARILY_DEFERRED")
    refresh_temporary_deferral_count(donor)
    refresh_active_deferral_until(donor)
    refresh_surveillance(donor)
    if event["reason_code"] == "PHYSICIAN_WITHDRAWAL":
        for approval in approvals_of(donor["id"]):
            if approval["status"] == "ACTIVE":
                set_field(approval, "status", "WITHDRAWN")
    run_recall(donor, event)


# --- the five-hop lookback recall -----------------------------------------
def run_recall(donor, event):
    scope = event["recall_scope"]
    if scope == "NONE":
        return
    effective_from = parse_date(event["effective_from"])
    if effective_from is None:
        return
    window_start = add_days(effective_from, -event["lookback_days"])

    # hop 1 - the donor's own containers inside the closed lookback interval
    recalled = []
    for donation in donations_of(donor["id"]):
        if donation["status"] not in RECALLABLE_DONATION_STATES:
            continue
        expressed = parse_date(donation["expressed_on"])
        if expressed is None or expressed < window_start or expressed > effective_from:
            continue
        set_field(donation, "status", "RECALLED")
        recalled.append(donation)
    event["recalled_donation_count"] = len(recalled)
    for donation in recalled:
        owner = find("donors", donation["donor_id"])
        if owner is not None:
            refresh_lifetime_volume(owner)
    if scope == "DONATIONS_ONLY":
        return

    # hop 2 - the components drawn from those containers
    recalled_ids = set(d["id"] for d in recalled)
    implicated_pool_ids = set()
    scrapped_pools = 0
    for component in db.rows("components"):
        if component["donation_id"] not in recalled_ids:
            continue
        if component["status"] == "ALLOCATED":
            set_field(component, "status", "VOIDED")
            donation = find("donations", component["donation_id"])
            if donation is not None:
                domain_pool.recompute_donation_remaining(donation)
            implicated_pool_ids.add(component["pool_id"])
            pool = find("pools", component["pool_id"])
            if pool is not None:
                if pool["status"] in ("DRAFT", "BALANCED", "COMMITTED"):
                    set_field(pool, "status", "SCRAPPED")
                    scrapped_pools += 1
                domain_pool.recompute_aggregates(pool)
        elif component["status"] == "CONSUMED_PASTEURIZED":
            implicated_pool_ids.add(component["pool_id"])
    event["quarantined_pool_count"] = scrapped_pools

    # hop 3 - the bottled inventory made from those pools
    implicated_run_ids = set(
        run["id"] for run in db.rows("runs") if run["pool_id"] in implicated_pool_ids
    )
    recalled_lots = []
    for lot in db.rows("lots"):
        if lot["run_id"] not in implicated_run_ids:
            continue
        if lot["release_status"] not in RECALLABLE_LOT_STATES:
            continue
        set_field(lot, "release_status", "RECALLED")
        recalled_lots.append(lot)
    event["recalled_lot_count"] = len(recalled_lots)

    # hop 4 - the fills drawn from those lots
    recalled_lot_ids = set(l["id"] for l in recalled_lots)
    reversed_subsidy = 0
    touched_prescriptions = []
    recalled_dispenses = 0
    for dispense in db.rows("dispenses"):
        if dispense["lot_id"] not in recalled_lot_ids:
            continue
        if dispense["status"] != "DISPENSED":
            continue
        set_field(dispense, "status", "RECALLED")
        recalled_dispenses += 1
        prescription = find("prescriptions", dispense["prescription_id"])
        if prescription is None:
            continue
        program = domain_dispense.program_of(prescription)
        if program is not None and dispense["subsidy_cents"]:
            set_field(program, "consumed_cents",
                      program["consumed_cents"] - dispense["subsidy_cents"])
            if program["consumed_cents"] < 0:
                set_field(program, "consumed_cents", 0)
            domain_dispense.refresh_program_status(program)
        reversed_subsidy += dispense["subsidy_cents"]
        # the volume is deliberately NOT credited back to the lot
        touched_prescriptions.append((prescription, dispense["volume_ml"]))
    event["recalled_dispense_count"] = recalled_dispenses
    event["reversed_subsidy_cents"] = reversed_subsidy

    # hop 5 - the orders those fills had satisfied return to the waitlist
    for prescription, volume_ml in touched_prescriptions:
        domain_dispense.reopen_prescription(prescription, volume_ml)
