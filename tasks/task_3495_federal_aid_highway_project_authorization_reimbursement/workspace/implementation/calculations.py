"""Calculation rules (scaffold §1.3 / PRD §2.6, §3).

All money is integer cents; all shares are Decimal, rounded half-up to four
decimal places; share-times-cents products are rounded half-up to whole cents.
"""
from decimal import ROUND_HALF_UP, Decimal

# --- Named constants (scaffold `constants:` block — single definition point) ---
STIP_DURATION_YEARS = 4
STIP_COMMENT_PERIOD_DAYS = 30
MIN_PUBLIC_COMMENTS = 1
EIS_COMMENT_PERIOD_DAYS = 45
MIN_ADVERTISEMENT_DAYS = 21
AUDIT_FINDINGS_RESPONSE_DAYS = 30
INTERSTATE_SYSTEM_BUMP = Decimal("0.10")
INTERSTATE_SHARE_CAP = Decimal("0.90")
SAFETY_FULL_SHARE = Decimal("1.00")
SAFETY_FULL_SHARE_ACTIVITIES = (
    "SIGNAGE_LIGHTING",
    "GUARDRAIL_INSTALL",
    "PEDESTRIAN_CROSSING",
)
FEDERAL_LAND_SLIDING_THRESHOLD = Decimal("0.05")
FEDERAL_LAND_SHARE_CAP = Decimal("0.95")
OVERRUN_PARTICIPATION_CAP_PCT = Decimal("0.20")
ACTIVITY_CODES = (
    "ROAD_RESURFACING",
    "BRIDGE_REPLACEMENT",
    "SIGNAGE_LIGHTING",
    "GUARDRAIL_INSTALL",
    "PEDESTRIAN_CROSSING",
    "TRANSIT_EXPANSION",
)
FUNDING_PROGRAM_CODES = ("NHPP", "STBG", "HSIP", "CMAQ", "TAP")
BASE_SHARE = {
    "NHPP": Decimal("0.80"),
    "STBG": Decimal("0.80"),
    "HSIP": Decimal("0.90"),
    "CMAQ": Decimal("0.80"),
    "TAP": Decimal("0.80"),
}

# Project statuses counted by the STIP fiscal-constraint check and by
# total_programmed_federal_cents.
COUNTED_PROJECT_STATUSES = (
    "NOMINATED",
    "ELIGIBLE",
    "AUTHORIZED",
    "BIDDING",
    "BIDS_OPENED",
    "UNDER_CONSTRUCTION",
    "COMPLETE",
)


def dec(value):
    """Decimal from a JSON number without binary-float artifacts."""
    return Decimal(str(value))


def round_half_up_int(x):
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_share_4(x):
    return x.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


# --- federal_share_determination ---
def statutory_base_share(program):
    """statutory_base variant: program base share only; no bump, no safety
    override, no land adjustment."""
    return BASE_SHARE[program["code"]]


def adjusted_full_share(program, project, stip):
    """adjusted_full variant. Evaluation order pinned: interstate bump first,
    safety override second (discards the land adjustment entirely), land
    sliding scale third only when the override does not fire."""
    base = BASE_SHARE[program["code"]]
    if project["is_interstate_system"]:
        base = min(INTERSTATE_SHARE_CAP, base + INTERSTATE_SYSTEM_BUMP)
    if (
        program["code"] == "HSIP"
        and project["activity_code"] in SAFETY_FULL_SHARE_ACTIVITIES
    ):
        share = SAFETY_FULL_SHARE
    else:
        land = dec(stip["state_federal_land_pct"])
        if land > FEDERAL_LAND_SLIDING_THRESHOLD:
            base = min(
                FEDERAL_LAND_SHARE_CAP,
                base + (FEDERAL_LAND_SHARE_CAP - base) * land,
            )
        share = base
    return round_share_4(share)


def provisional_estimate_cents(total_cost_cents, share):
    return round_half_up_int(Decimal(total_cost_cents) * share)


# --- fiscal_constraint_check / apportionment_availability (forward-looking) ---
def fiscal_constraint_ok(stip, projects, apportionments):
    counted = [
        p
        for p in projects
        if p["stip_id"] == stip["id"] and p["status"] in COUNTED_PROJECT_STATUSES
    ]
    program_ids = {p["funding_program_id"] for p in counted}
    for pid in program_ids:
        programmed = sum(
            p["provisional_federal_estimate_cents"]
            for p in counted
            if p["funding_program_id"] == pid
        )
        capacity = sum(
            a["apportioned_cents"] - a["obligated_cents"]
            for a in apportionments
            if a["funding_program_id"] == pid
            and a["state_code"] == stip["state_code"]
            and stip["start_federal_fiscal_year"]
            <= a["federal_fiscal_year"]
            <= stip["end_federal_fiscal_year"]
        )
        if programmed > capacity:
            return False
    return True


def total_programmed_federal_cents(stip_id, projects):
    return sum(
        p["provisional_federal_estimate_cents"]
        for p in projects
        if p["stip_id"] == stip_id and p["status"] in COUNTED_PROJECT_STATUSES
    )


# --- voucher_reimbursement ---
def voucher_reimbursement(
    line_items, ineligible_indexes, share, obligated_cents, reimbursed_cents
):
    """Per-line round_half_up to whole cents first, then sum; clamped to the
    authorization's remaining obligation. Sum-then-round is forbidden."""
    struck = set(ineligible_indexes or [])
    approved = [li for i, li in enumerate(line_items) if i not in struck]
    eligible_total = sum(li["eligible_amount_cents"] for li in approved)
    per_line_sum = sum(
        round_half_up_int(Decimal(li["eligible_amount_cents"]) * share)
        for li in approved
    )
    remaining = obligated_cents - reimbursed_cents
    return eligible_total, min(per_line_sum, remaining)


# --- change_order_federal_participation ---
def change_order_participation(
    delta_cost_cents, share, initial_obligated_cents, cumulative_participation_cents
):
    """Pinned step order: eligible amount, cap, remaining room, clamp."""
    eligible = round_half_up_int(Decimal(delta_cost_cents) * share)
    cap = round_half_up_int(
        Decimal(initial_obligated_cents) * OVERRUN_PARTICIPATION_CAP_PCT
    )
    room = cap - cumulative_participation_cents
    return max(0, min(eligible, room))


# --- lowest_responsive_bid_selection ---
def select_winning_bid(project_bids):
    """Winner among responsive SUBMITTED bids: lowest amount, tie-break by
    submission_seq (payload array index) only. None when the pool is empty."""
    candidates = [
        b
        for b in project_bids
        if b["is_responsive"] and b["status"] == "SUBMITTED"
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda b: (b["bid_amount_cents"], b["submission_seq"]))


# --- authorization_ledger_reconciliation ---
def ledger_reconciliation(auth, approved_eligible_total, ineligible_amount_cents):
    share = auth["_share_dec"]
    product = (Decimal(approved_eligible_total) - Decimal(ineligible_amount_cents)) * share
    final_eligible = max(0, round_half_up_int(product))
    repayment_due = max(0, auth["reimbursed_cents"] - final_eligible)
    return final_eligible, repayment_due
