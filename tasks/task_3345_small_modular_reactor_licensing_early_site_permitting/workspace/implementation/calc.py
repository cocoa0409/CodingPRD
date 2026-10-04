"""Domain calculations: EPZ, FOAK allocation, escalation, withdrawal penalty, etc."""
import math
from decimal import Decimal, ROUND_HALF_UP

from store import DB, floor_int, round2, touch

QUALIFIED_DEFECTS_THRESHOLD = 3

# withdrawal tiers: (min_days, max_days, rate)
WITHDRAWAL_TIERS = [
    (0, 30, Decimal("0.0")),
    (30, 180, Decimal("0.1")),
    (180, None, Decimal("0.25")),
]


# ---------------------------------------------------------------------------
# EPZ radius
# ---------------------------------------------------------------------------
def compute_epz(source_term_fraction, site_boundary_miles):
    """Returns (deterministic, dose_based, selected) each rounded half-up to 2dp."""
    stf = float(source_term_fraction)
    sbm = float(site_boundary_miles)
    det = 10.0 * stf
    dose_term = 2.0 * math.sqrt(sbm)
    margin_term = 5.0 * (1.0 - stf)
    dose = max(0.5, dose_term + margin_term)
    sel = max(0.5, min(10.0, max(det, dose)))
    return round2(det), round2(dose), round2(sel)


# ---------------------------------------------------------------------------
# Vendor qualification variant
# ---------------------------------------------------------------------------
def derive_qualified_variant(status, defects_found):
    if status == "FULLY_QUALIFIED":
        return "FULLY_QUALIFIED"
    if status == "CONDITIONALLY_QUALIFIED" and defects_found < QUALIFIED_DEFECTS_THRESHOLD:
        return "CONDITIONALLY_QUALIFIED"
    return "UNQUALIFIED"


def recompute_vendor_flags(vendor_id):
    """Recompute vendor.qualified and has_active_qualification from latest active qualification."""
    vendor = DB["vendor"].get(vendor_id)
    if not vendor:
        return
    quals = [q for q in DB["vendor_qualification"].values() if q["vendor_id"] == vendor_id]
    active = [q for q in quals if q["status"] in ("AUDIT_SCHEDULED", "CONDITIONALLY_QUALIFIED", "FULLY_QUALIFIED")]
    has_active = len(active) > 0
    qualified = False
    if active:
        # latest by cycle_number
        latest = max(active, key=lambda q: q.get("cycle_number", 0))
        qualified = latest.get("qualified_variant") == "FULLY_QUALIFIED"
    changed = False
    if vendor.get("qualified") != qualified:
        vendor["qualified"] = qualified
        changed = True
    if vendor.get("has_active_qualification") != has_active:
        vendor["has_active_qualification"] = has_active
        changed = True
    if changed:
        touch(vendor)


# ---------------------------------------------------------------------------
# SAR open_rais
# ---------------------------------------------------------------------------
def recompute_open_rais(dca_id, section_code):
    """Recompute SAR.open_rais for any SAR of this DCA with matching section_code."""
    open_statuses = ("OPEN", "RESPONSE_SUBMITTED", "REOPENED")
    count = sum(
        1
        for r in DB["rai"].values()
        if r["dca_id"] == dca_id and r["sar_section_code"] == section_code and r["status"] in open_statuses
    )
    for sar in DB["sar"].values():
        if sar["dca_id"] == dca_id and sar["section_code"] == section_code:
            if sar.get("open_rais") != count:
                sar["open_rais"] = count
                touch(sar)


# ---------------------------------------------------------------------------
# TestProgram completed_tests
# ---------------------------------------------------------------------------
def recompute_completed_tests(program_id):
    program = DB["test_program"].get(program_id)
    if not program:
        return 0
    count = sum(1 for r in DB["test_result"].values() if r["program_id"] == program_id and r["outcome"] == "PASS")
    if program.get("completed_tests") != count:
        program["completed_tests"] = count
    return count


# ---------------------------------------------------------------------------
# DCA subscription computed fields
# ---------------------------------------------------------------------------
def recompute_dca_subscription_fields(dca_id):
    dca = DB["dca"].get(dca_id)
    if not dca:
        return
    subscribed = sum(
        s["committed_mw"]
        for s in DB["subscription"].values()
        if s["dca_id"] == dca_id and s["status"] in ("EXECUTED", "LOCKED")
    )
    dca["subscribed_mw"] = subscribed
    dca["available_mw"] = dca["plant_net_capacity_mw"] - subscribed


# ---------------------------------------------------------------------------
# Workforce pipeline graduates
# ---------------------------------------------------------------------------
def recompute_pipeline_graduates(pipeline_id):
    pipeline = DB["workforce_pipeline"].get(pipeline_id)
    if not pipeline:
        return 0
    count = sum(
        1
        for lic in DB["operator_license"].values()
        if lic["pipeline_id"] == pipeline_id and lic["license_status"] in ("LICENSED", "ACTIVE")
    )
    if pipeline.get("graduates") != count:
        pipeline["graduates"] = count
    return count


# ---------------------------------------------------------------------------
# FOAK cost allocation (LOCK-time waterfall)
# ---------------------------------------------------------------------------
def foak_allocate(csa, dca, locked_subs):
    """Distributes csa.participant_share_usd across locked_subs in created_at ASC order.

    Mutates each subscription: sets cost_share_total_usd and withdrawal_reserve_usd.
    """
    pool = int(csa["participant_share_usd"])
    capacity = int(dca["plant_net_capacity_mw"])
    subs = sorted(locked_subs, key=lambda s: (s["created_at"], s["id"]))
    base_shares = []
    for s in subs:
        share = (pool * s["committed_mw"]) // capacity
        base_shares.append(share)
    remainder = pool - sum(base_shares)
    for i, s in enumerate(subs):
        extra = 0
        if remainder > 0:
            extra = 1
            remainder -= 1
        total = base_shares[i] + extra
        s["cost_share_total_usd"] = total
        s["withdrawal_reserve_usd"] = total
    return subs


def recompute_csa_allocated(dca_id):
    csa = next((c for c in DB["cost_share_agreement"].values() if c["dca_id"] == dca_id), None)
    if not csa:
        return None
    total = sum(
        (s.get("cost_share_total_usd", 0) or 0) + (s.get("allocated_overrun_usd", 0) or 0)
        for s in DB["subscription"].values()
        if s["dca_id"] == dca_id
    )
    csa["allocated_to_participants_usd"] = total
    return csa


# ---------------------------------------------------------------------------
# Withdrawal penalty (tiered by days since execution)
# ---------------------------------------------------------------------------
def withdrawal_penalty(reserve_usd, executed_at_dt, clock_dt):
    if executed_at_dt is None or clock_dt is None:
        days = 0
    else:
        delta = clock_dt - executed_at_dt
        days = delta.days
        if delta.total_seconds() < 0:
            days = 0
    penalty = 0
    for (min_d, max_d, rate) in WITHDRAWAL_TIERS:
        if days >= min_d and (max_d is None or days < max_d):
            penalty = int((Decimal(int(reserve_usd)) * rate).to_integral_value(rounding=ROUND_HALF_UP))
            # floor instead of half_up
            penalty = int((Decimal(int(reserve_usd)) * rate).to_integral_value(rounding="ROUND_FLOOR"))
    return penalty


# ---------------------------------------------------------------------------
# Escalation reallocation
# ---------------------------------------------------------------------------
def escalate_reallocate(csa, dca, overrun_usd):
    """Returns dict with summary. Mutates subscriptions and dca.funding_gap_usd."""
    subs = [
        s for s in DB["subscription"].values()
        if s["dca_id"] == dca["id"] and s["status"] in ("EXECUTED", "LOCKED")
    ]
    subs.sort(key=lambda s: (s["created_at"], s["id"]))
    total_committed = sum(s["committed_mw"] for s in subs)
    if total_committed <= 0:
        # no one can absorb; all goes to funding gap
        dca["funding_gap_usd"] = int(dca.get("funding_gap_usd", 0)) + overrun_usd
        return {"allocated": 0, "funding_gap_added": overrun_usd, "off_ramped": []}

    off_ramped = []
    total_allocated = 0
    total_gap = 0
    for s in subs:
        pro_rata = (overrun_usd * s["committed_mw"]) // total_committed
        capacity = int(s.get("withdrawal_reserve_usd", 0))
        allocated = min(pro_rata, capacity)
        if allocated > 0:
            s["allocated_overrun_usd"] = int(s.get("allocated_overrun_usd", 0)) + allocated
            if s["status"] == "EXECUTED":
                s["withdrawal_reserve_usd"] = int(s.get("withdrawal_reserve_usd", 0)) - allocated
            else:
                # LOCKED: reserve is also decremented (capacity consumed)
                s["withdrawal_reserve_usd"] = int(s.get("withdrawal_reserve_usd", 0)) - allocated
            total_allocated += allocated
        if pro_rata > capacity:
            gap = pro_rata - capacity
            dca["funding_gap_usd"] = int(dca.get("funding_gap_usd", 0)) + gap
            total_gap += gap
            if s["status"] == "EXECUTED" and capacity == 0:
                s["status"] = "WITHDRAWN"
                s["offload_penalty_usd"] = 0
                touch(s)
                off_ramped.append(s["id"])
        # touch each participant that changed
        if allocated > 0 or pro_rata > capacity:
            touch(s)

    remainder = overrun_usd - total_allocated - total_gap
    # distribute remainder one dollar at a time in created_at order to participants with capacity
    while remainder > 0:
        progressed = False
        for s in subs:
            if remainder <= 0:
                break
            if s["status"] not in ("EXECUTED", "LOCKED"):
                continue
            capacity = int(s.get("withdrawal_reserve_usd", 0))
            if capacity > 0:
                s["allocated_overrun_usd"] = int(s.get("allocated_overrun_usd", 0)) + 1
                s["withdrawal_reserve_usd"] = capacity - 1
                total_allocated += 1
                remainder -= 1
                touch(s)
                progressed = True
        if not progressed:
            # nobody has capacity; push remainder into funding gap
            dca["funding_gap_usd"] = int(dca.get("funding_gap_usd", 0)) + remainder
            total_gap += remainder
            remainder = 0

    return {"allocated": total_allocated, "funding_gap_added": total_gap, "off_ramped": off_ramped}
