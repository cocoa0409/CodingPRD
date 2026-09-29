"""The calculation engine.

Every formula here is transcribed from PRD 3 and the scaffold's calculations
table. All money is integer cents and all rates integer basis points; the
rounding direction of every step is pinned by the specification and is never
left to implementation convenience.
"""

import db
import util

# Pinned constants.
MARKET_APR_BPS = 799
CANCEL_RESERVE_BPS = 275
RESIDUAL_PASS_THROUGH_BPS = 6000
MAX_TOTAL_UPLIFT_BPS = 5000
MIN_OBJECTIVE_UNITS = 1
MAX_REPORT_LAG_DAYS = 10
MAX_PROTEST_ROUNDS = 2
SETTLEMENT_BUFFER_SECONDS = 86400

# Program incentive types that mint a UNIT_INCENTIVE claim rather than a bonus.
UNIT_INCENTIVE_PROGRAM_TYPES = ("CUSTOMER_CASH", "FINANCE_SUBVENTION", "LEASE_SUPPORT")
CLAIM_TYPE_UNIT_INCENTIVE = "UNIT_INCENTIVE"

COMMITTED_PAYMENT_STATES = ("UNPAID", "SCHEDULED", "PAID")


# --------------------------------------------------------------------------
# Collection helpers
# --------------------------------------------------------------------------

def program_rules(program_id):
    """A program's eligibility footprint rows in created_at ASC order."""
    return db.ordered(
        [r for r in db.eligibility_rules.values() if r["program_id"] == program_id]
    )


def program_edges(program_id):
    return db.ordered(
        [
            e
            for e in db.stackability_constraints.values()
            if e["program_a_id"] == program_id or e["program_b_id"] == program_id
        ]
    )


def find_edge(program_a_id, program_b_id):
    """The single undirected stackability edge joining an unordered pair."""
    pair = {program_a_id, program_b_id}
    for edge in db.ordered(list(db.stackability_constraints.values())):
        if {edge["program_a_id"], edge["program_b_id"]} == pair:
            return edge
    return None


def program_claims(program_id):
    return db.ordered([c for c in db.claims.values() if c["program_id"] == program_id])


def delivery_claims(delivery_id):
    return db.ordered([c for c in db.claims.values() if c["delivery_id"] == delivery_id])


def claim_chargebacks(claim_id):
    return db.ordered([c for c in db.chargebacks.values() if c["claim_id"] == claim_id])


def program_accruals(program_id):
    return db.ordered(
        [a for a in db.budget_accruals.values() if a["program_id"] == program_id]
    )


def program_repricings(program_id):
    return db.ordered(
        [r for r in db.repricing_events.values() if r["program_id"] == program_id]
    )


def program_objectives(program_id):
    return db.ordered([o for o in db.objectives.values() if o["program_id"] == program_id])


def objective_protests(objective_id):
    return sorted(
        [p for p in db.protests.values() if p["objective_id"] == objective_id],
        key=lambda p: (p["round_index"], p["_seq"]),
    )


def find_objective(program_id, dealer_id):
    matches = db.ordered(
        [
            o
            for o in db.objectives.values()
            if o["program_id"] == program_id and o["dealer_id"] == dealer_id
        ]
    )
    return matches[0] if matches else None


# --------------------------------------------------------------------------
# The admission predicate (PRD 3.1)
# --------------------------------------------------------------------------

def rule_admits(rule, delivery):
    if rule["model_code"] != delivery["model_code"]:
        return False
    if rule["trim_code"] is not None and rule["trim_code"] != delivery["trim_code"]:
        return False
    if rule["region_code"] != delivery["customer_region_code"]:
        return False
    if not (rule["build_date_from"] <= delivery["build_date"] <= rule["build_date_to"]):
        return False
    if delivery["msrp_cents"] < rule["min_msrp_cents"]:
        return False
    if rule["max_msrp_cents"] is not None and delivery["msrp_cents"] > rule["max_msrp_cents"]:
        return False
    if delivery["deal_type"] not in rule["allowed_deal_types"]:
        return False
    return True


def program_admits(program, delivery):
    for rule in program_rules(program["id"]):
        if rule_admits(rule, delivery):
            return True
    return False


def first_admitting_rule(program_id, delivery):
    for rule in program_rules(program_id):
        if rule_admits(rule, delivery):
            return rule
    return None


def window_contains(program, instant):
    """Half-open [effective_from, effective_to)."""
    return program["effective_from"] <= instant < program["effective_to"]


# --------------------------------------------------------------------------
# claim_payable_amount (PRD 3.7)
# --------------------------------------------------------------------------

def retroactive_repricing_covers(program_id, sale_date):
    for event in program_repricings(program_id):
        if event["mode"] != "RETROACTIVE_TO_MONTH_START":
            continue
        if event["month_start"] <= sale_date < event["effective_at"]:
            return True
    return False


def incentive_leg_cents(program, delivery):
    incentive_type = program["incentive_type"]
    if incentive_type == "CUSTOMER_CASH":
        return 0
    if incentive_type == "FINANCE_SUBVENTION":
        headroom = MARKET_APR_BPS - delivery["contract_apr_bps"]
        if headroom < 0:
            headroom = 0
        effective_bps = min(program["apr_buydown_bps"], headroom)
        return util.round_half_up_div(
            delivery["msrp_cents"] * effective_bps * delivery["term_months"], 120000
        )
    if incentive_type == "LEASE_SUPPORT":
        return util.round_half_up_div(
            delivery["msrp_cents"] * program["residual_support_bps"], 10000
        )
    return 0


def claim_payable(claim, force_repriced=False):
    """Return (approved_amount_cents, rate_basis) for one claim."""
    program = db.programs[claim["program_id"]]
    delivery = db.deliveries.get(claim["delivery_id"])

    if force_repriced or (
        delivery is not None
        and retroactive_repricing_covers(program["id"], delivery["sale_date"])
    ):
        rate_cents = program["per_unit_amount_cents"]
        rate_basis = "REPRICED_CURRENT"
    else:
        rate_cents = claim["snapshot_per_unit_cents"]
        rate_basis = "AS_SOLD_SNAPSHOT"

    if claim["claim_type"] == "STAIR_STEP_BONUS":
        objective = find_objective(claim["program_id"], claim["dealer_id"])
        if objective is None:
            return 0, rate_basis
        return objective["payout_cents"] - objective["paid_payout_cents"], rate_basis

    return rate_cents + incentive_leg_cents(program, delivery), rate_basis


def gross_payable(delivery, program):
    """Gross payable amount of a hypothetical claim for (delivery, program).

    Used by the stacking waterfall, where no claim row exists yet: the rate a
    fresh claim would freeze is the program's current per_unit_amount_cents.
    """
    if program["incentive_type"] == "DEALER_STAIR_STEP":
        objective = find_objective(program["id"], delivery["dealer_id"])
        if objective is None:
            return 0
        return objective["payout_cents"] - objective["paid_payout_cents"]
    return program["per_unit_amount_cents"] + incentive_leg_cents(program, delivery)


def claim_running_contribution(claim):
    """What an already-accepted claim contributes to the waterfall total."""
    if claim["validation_status"] == "SUBMITTED":
        amount, _ = claim_payable(claim)
        return amount
    return claim["approved_amount_cents"]


# --------------------------------------------------------------------------
# delivery_stack_allocation (PRD 3.6)
# --------------------------------------------------------------------------

def candidate_programs(delivery):
    """ACTIVE programs whose half-open window contains sale_date and whose
    footprint admits the delivery, ranked by priority_rank ASC then created_at ASC."""
    candidates = [
        p
        for p in db.programs.values()
        if p["status"] == "ACTIVE"
        and window_contains(p, delivery["sale_date"])
        and program_admits(p, delivery)
    ]
    return sorted(candidates, key=lambda p: (p["priority_rank"], p["created_at"], p["_seq"]))


def accepted_program_ids(delivery):
    """Programs behind this delivery's live claims (PRD 3.6 accepted set)."""
    ids = []
    for claim in delivery_claims(delivery["id"]):
        if claim["validation_status"] == "REJECTED":
            continue
        if claim["payment_status"] == "CHARGED_BACK":
            continue
        if claim["program_id"] not in ids:
            ids.append(claim["program_id"])
    return ids


def stack_allocation(delivery):
    """Run the stacking waterfall over one delivery."""
    accepted = accepted_program_ids(delivery)
    running_total = 0
    for claim in delivery_claims(delivery["id"]):
        if claim["validation_status"] == "REJECTED":
            continue
        if claim["payment_status"] == "CHARGED_BACK":
            continue
        running_total += claim_running_contribution(claim)

    eligible, blocked, capped_out = [], [], []

    for candidate in candidate_programs(delivery):
        candidate_id = candidate["id"]
        if candidate_id in accepted:
            continue

        forbidden = False
        for partner_id in accepted:
            edge = find_edge(candidate_id, partner_id)
            if edge is not None and edge["mode"] == "FORBIDDEN":
                forbidden = True
                break
        if forbidden:
            blocked.append(candidate_id)
            continue

        pair_caps = []
        for partner_id in accepted:
            edge = find_edge(candidate_id, partner_id)
            if (
                edge is not None
                and edge["mode"] == "CAPPED_TOTAL"
                and edge["cap_amount_cents"] is not None
            ):
                pair_caps.append(edge["cap_amount_cents"])

        partner_caps = [
            db.programs[partner_id]["stack_cap_cents"]
            for partner_id in accepted
            if db.programs[partner_id]["stack_cap_cents"] > 0
        ]

        ceilings = []
        if pair_caps:
            ceilings.append(min(pair_caps))
        if candidate["stack_cap_cents"] > 0:
            ceilings.append(candidate["stack_cap_cents"])
        if partner_caps:
            ceilings.append(min(partner_caps))

        gross = gross_payable(delivery, candidate)
        if ceilings and running_total + gross > min(ceilings):
            capped_out.append(candidate_id)
            continue

        eligible.append(candidate_id)
        accepted.append(candidate_id)
        running_total += gross

    return {
        "delivery_id": delivery["id"],
        "eligible_program_ids": eligible,
        "blocked_program_ids": blocked,
        "capped_out_program_ids": capped_out,
        "stacked_total_cents": running_total,
    }


# --------------------------------------------------------------------------
# objective_units_proposal (PRD 3.3)
# --------------------------------------------------------------------------

def objective_units_from_basis(basis_units, market_opportunity_bps, stretch_bps):
    uplift_bps = min(MAX_TOTAL_UPLIFT_BPS, market_opportunity_bps + stretch_bps)
    rounded = util.round_half_up_div(basis_units * (10000 + uplift_bps), 10000)
    return max(MIN_OBJECTIVE_UNITS, rounded)


# --------------------------------------------------------------------------
# objective_achieved_units and dealer_stair_step_payout (PRD 3.5, 3.7)
# --------------------------------------------------------------------------

def objective_achieved_units(objective):
    program = db.programs[objective["program_id"]]
    count = 0
    for delivery in db.deliveries.values():
        if delivery["dealer_id"] != objective["dealer_id"]:
            continue
        if delivery["status"] != "VALIDATED":
            continue
        if not window_contains(program, delivery["sale_date"]):
            continue
        if not program_admits(program, delivery):
            continue
        count += 1
    return count


def stair_step_payout(objective, program):
    """Return (attainment_bps, tier_attained, payout_cents)."""
    achieved = objective["achieved_units"]
    objective_units = objective["objective_units"] or MIN_OBJECTIVE_UNITS
    attainment_bps = util.floor_div(achieved * 10000, objective_units)

    tiers = sorted(program.get("tier_schedule") or [], key=lambda t: t["tier_index"])
    reached = [t["tier_index"] for t in tiers if t["threshold_bps"] <= attainment_bps]
    tier_attained = max(reached) if reached else 0

    if tier_attained == 0:
        return attainment_bps, 0, 0

    def threshold_units(tier):
        return util.ceil_div(objective_units * tier["threshold_bps"], 10000)

    if program.get("tier_bonus_mode") == "FULL_VOLUME":
        top = next(t for t in tiers if t["tier_index"] == tier_attained)
        return attainment_bps, tier_attained, achieved * top["per_unit_bonus_cents"]

    payout_cents = 0
    for index, tier in enumerate(tiers):
        if tier["tier_index"] > tier_attained:
            break
        lower = threshold_units(tier)
        if index + 1 < len(tiers):
            band_hi = threshold_units(tiers[index + 1]) - 1
            upper = min(achieved, band_hi)
        else:
            upper = achieved
        band_units = upper - lower + 1
        payout_cents += band_units * tier["per_unit_bonus_cents"]
    return attainment_bps, tier_attained, payout_cents


# --------------------------------------------------------------------------
# back_dated_sale_detection (PRD 3.5)
# --------------------------------------------------------------------------

def back_dated_detection(sale_date, reported_at):
    """Return (reporting_lag_days, back_dated_flag)."""
    from datetime import timedelta

    delta = util.to_dt(reported_at) - util.to_dt(sale_date)
    lag_days = delta // timedelta(seconds=86400)
    flagged = (lag_days > MAX_REPORT_LAG_DAYS) or (sale_date > reported_at)
    return lag_days, flagged


# --------------------------------------------------------------------------
# monthly_budget_accrual (PRD 3.9)
# --------------------------------------------------------------------------

def accrual_lines(program, period_month):
    """Return (unit_basis, accrued_cents) for one program and period_month.

    One line per eligibility footprint row in created_at ASC order; a delivery
    is attributed to the first admitting row only. Half-up rounding is applied
    per line and only the rounded line amounts are summed.
    """
    rules = program_rules(program["id"])
    window_start, window_end = util.month_window(period_month)

    in_window = []
    for delivery in db.deliveries.values():
        if delivery["status"] != "VALIDATED":
            continue
        sale_date = delivery["sale_date"]
        if sale_date < window_start or sale_date >= window_end:
            continue
        in_window.append(delivery)

    counts = {rule["id"]: 0 for rule in rules}
    for delivery in in_window:
        first = first_admitting_rule(program["id"], delivery)
        if first is not None:
            counts[first["id"]] += 1

    per_unit = program["per_unit_amount_cents"]
    method = program["accrual_method"]
    unit_basis = 0
    accrued_cents = 0
    for rule in rules:
        units = counts[rule["id"]]
        unit_basis += units
        if method == "TAKE_RATE_BASED":
            factor = program["projected_take_rate_bps"]
        else:
            factor = 10000 - CANCEL_RESERVE_BPS
        accrued_cents += util.round_half_up_div(units * per_unit * factor, 10000)
    return unit_basis, accrued_cents


def accrued_budget_cents(program_id):
    """Sum of accrued_cents minus sum of reversal_cents over the whole ledger."""
    total = 0
    for row in program_accruals(program_id):
        total += row["accrued_cents"] - row["reversal_cents"]
    return total


# --------------------------------------------------------------------------
# per_unit_incentive_spend (PRD 3.7)
# --------------------------------------------------------------------------

def committed_claim_set(program_id):
    """VALIDATED claims in a committed payment state (PRD 3.7 / 3.9)."""
    return [
        claim
        for claim in program_claims(program_id)
        if claim["validation_status"] == "VALIDATED"
        and claim["payment_status"] in COMMITTED_PAYMENT_STATES
    ]


def per_unit_spend(program_id):
    """Return (claimed_units, per_unit_spend_cents)."""
    claims = committed_claim_set(program_id)
    claimed_units = sum(1 for c in claims if c["claim_type"] == CLAIM_TYPE_UNIT_INCENTIVE)
    spend = sum(c["approved_amount_cents"] for c in claims)
    if claimed_units == 0:
        return 0, 0
    return claimed_units, util.floor_div(spend, claimed_units)


# --------------------------------------------------------------------------
# residual_value_impact (PRD 3.9) - five pinned steps, every division floors
# --------------------------------------------------------------------------

def residual_impact_bps(program):
    if program["incentive_type"] != "LEASE_SUPPORT":
        return 0
    claims = committed_claim_set(program["id"])
    gross_support = sum(c["approved_amount_cents"] for c in claims)
    supported_units = len(claims)
    if supported_units == 0:
        return 0
    msrp_total = 0
    for claim in claims:
        delivery = db.deliveries.get(claim["delivery_id"])
        if delivery is not None:
            msrp_total += delivery["msrp_cents"]
    average_cap_cost = util.floor_div(msrp_total, supported_units)
    denominator = average_cap_cost * supported_units
    if denominator == 0:
        return 0
    support_ratio_bps = util.floor_div(gross_support * 10000, denominator)
    return util.floor_div(support_ratio_bps * RESIDUAL_PASS_THROUGH_BPS, 10000)
