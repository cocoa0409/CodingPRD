"""Derived totals, cascades and every calculation rule from PRD section 3."""
from decimal import Decimal

from store import (
    ATTRITION_HOLD_THRESHOLD_BPS,
    CLAWBACK_WINDOW_DAYS,
    MAX_HIERARCHY_DEPTH,
    MAX_OVERRIDE_LEVELS,
    MINIMUM_SHARE_PCT,
    TIER_1_CEILING_CENTS,
    TIER_2_CEILING_CENTS,
    VESTING_BUYOUT_MULTIPLE,
    VESTING_CLIFF_MONTHS,
    VESTING_STEP_MONTHS,
    VESTING_STEP_PCT,
    db,
    index_to_month,
    month_first_day,
    month_index,
    month_of_date,
    new_id,
    next_month_first_day,
    ordered,
    parse_date,
    round_half_up,
    stamp_new,
    touch,
)

HALF = Decimal("0.5")


# --- collection helpers -----------------------------------------------------
def lines_of_batch(batch_id):
    return ordered([r for r in db.lines.values() if r["residual_batch_id"] == batch_id])


def allocations_of_statement(statement_id):
    return ordered([r for r in db.allocations.values() if r["statement_id"] == statement_id])


def adjustments_of_statement(statement_id):
    return ordered([r for r in db.adjustments.values() if r["statement_id"] == statement_id])


def statements_of_agent(agent_id):
    return ordered([r for r in db.statements.values() if r["agent_id"] == agent_id])


def merchants_of_agent(agent_id):
    return ordered([r for r in db.merchants.values() if r["owning_agent_id"] == agent_id])


def advances_of_agent(agent_id):
    return ordered([r for r in db.advances.values() if r["agent_id"] == agent_id])


def children_of_agent(agent_id):
    return ordered([r for r in db.agents.values() if r["parent_agent_id"] == agent_id])


def batches_of_program(program_id):
    return ordered([r for r in db.batches.values() if r["processor_program_id"] == program_id])


# --- ProcessorProgram derived ----------------------------------------------
def posted_batch_count(program_id):
    return len([b for b in db.batches.values()
                if b["processor_program_id"] == program_id and b["state"] == "POSTED"])


# --- Agent derived ----------------------------------------------------------
def vesting_pct_at_clock(agent):
    anchor = parse_date(agent["vesting_start_date"])
    if anchor is None:
        return 0
    today = db.today()
    months = 12 * (today.year - anchor.year) + (today.month - anchor.month)
    if today.day < anchor.day:
        months -= 1
    if months < VESTING_CLIFF_MONTHS:
        return 0
    return min(100, VESTING_STEP_PCT * (months // VESTING_STEP_MONTHS))


def vested_pct(agent):
    frozen = agent.get("vested_pct_at_departure")
    if agent["status"] == "DEPARTED" and frozen is not None:
        return frozen
    return vesting_pct_at_clock(agent)


def portfolio_counts(agent_id):
    rows = merchants_of_agent(agent_id)
    total = len([r for r in rows if r["status"] in ("PENDING", "ACTIVE", "ATTRITED")])
    active = len([r for r in rows if r["status"] == "ACTIVE"])
    attrited = len([r for r in rows if r["status"] == "ATTRITED"])
    return total, active, attrited


def portfolio_attrition_bps(agent_id):
    rows = merchants_of_agent(agent_id)
    denominator = len([r for r in rows if r["status"] in ("ACTIVE", "ATTRITED")])
    if denominator == 0:
        return 0
    numerator = len([r for r in rows if r["status"] == "ATTRITED"])
    return round_half_up(Decimal(10000 * numerator) / Decimal(denominator))


def residual_hold(agent_id):
    return portfolio_attrition_bps(agent_id) >= ATTRITION_HOLD_THRESHOLD_BPS


def lifetime_clawback_cents(agent_id):
    statement_ids = set(r["id"] for r in db.statements.values() if r["agent_id"] == agent_id)
    total = 0
    for adj in db.adjustments.values():
        if adj["statement_id"] not in statement_ids or adj["state"] != "APPLIED":
            continue
        if adj["kind"] == "BONUS_CLAWBACK":
            total += abs(adj["amount_cents"])
        elif adj["kind"] == "CLAWBACK_REVERSAL":
            total -= abs(adj["amount_cents"])
    return total


def clawed_back_bonus_cents(merchant_id):
    total = 0
    for adj in db.adjustments.values():
        if adj.get("source_merchant_id") != merchant_id or adj["state"] != "APPLIED":
            continue
        if adj["kind"] == "BONUS_CLAWBACK":
            total += abs(adj["amount_cents"])
        elif adj["kind"] == "CLAWBACK_REVERSAL":
            total -= abs(adj["amount_cents"])
    return total


def trailing_residual_cents(agent_id):
    rows = statements_of_agent(agent_id)
    rows.sort(key=lambda r: r["period_month"], reverse=True)
    return sum(r["gross_after_trueup_cents"] for r in rows[:3])


def advance_outstanding_cents(agent_id):
    return sum(r["outstanding_cents"] for r in db.advances.values()
               if r["agent_id"] == agent_id and r["state"] == "ACTIVE")


# --- hierarchy --------------------------------------------------------------
def descendant_ids(agent_id):
    found = set()
    frontier = [agent_id]
    while frontier:
        current = frontier.pop()
        for child in children_of_agent(current):
            if child["id"] not in found:
                found.add(child["id"])
                frontier.append(child["id"])
    return found


def subtree_relative_depth(agent_id):
    """Deepest number of edges below the given agent."""
    deepest = 0
    for child in children_of_agent(agent_id):
        deepest = max(deepest, 1 + subtree_relative_depth(child["id"]))
    return deepest


def recompute_hierarchy_depth(agent):
    parent_id = agent.get("parent_agent_id")
    if parent_id and parent_id in db.agents:
        agent["hierarchy_depth"] = db.agents[parent_id]["hierarchy_depth"] + 1
    else:
        agent["hierarchy_depth"] = 0
    for child in children_of_agent(agent["id"]):
        recompute_hierarchy_depth(child)


# --- AgentStatement ---------------------------------------------------------
def find_statement(agent_id, period_month):
    for row in ordered(list(db.statements.values())):
        if row["agent_id"] == agent_id and row["period_month"] == period_month:
            return row
    return None


def upsert_statement(agent_id, period_month):
    """Returns (statement, created). Statements are never created by a client."""
    existing = find_statement(agent_id, period_month)
    if existing is not None:
        return existing, False
    row = {
        "id": new_id(),
        "agent_id": agent_id,
        "period_month": period_month,
        "lifecycle_state": "DRAFT",
        "settlement_state": "UNSETTLED",
        "direct_residual_cents": 0,
        "override_residual_cents": 0,
        "minimum_true_up_cents": 0,
        "gross_after_trueup_cents": 0,
        "advance_recoupment_cents": 0,
        "adjustment_cents": 0,
        "opening_deficit_cents": 0,
        "net_payable_cents": 0,
        "carry_forward_deficit_cents": 0,
        "issued_at": None,
        "paid_on": None,
        "hold_reason": None,
        "_recoupments": {},
    }
    stamp_new(row)
    db.statements[row["id"]] = row
    return row, True


def opening_deficit_cents(statement):
    previous_month = index_to_month(month_index(statement["period_month"]) - 1)
    previous = find_statement(statement["agent_id"], previous_month)
    if previous is None:
        return 0
    if previous["lifecycle_state"] not in ("ISSUED", "FINALIZED"):
        return 0
    return previous["carry_forward_deficit_cents"]


def recompute_statement(statement):
    """The pinned nine-step evaluation of PRD 3.7."""
    allocations = allocations_of_statement(statement["id"])
    statement["direct_residual_cents"] = sum(
        r["gross_allocation_cents"] for r in allocations
        if r["allocation_type"] == "DIRECT_SPLIT")
    statement["override_residual_cents"] = sum(
        r["gross_allocation_cents"] for r in allocations
        if r["allocation_type"] == "OVERRIDE")
    if statement["lifecycle_state"] == "DRAFT":
        statement["minimum_true_up_cents"] = 0
        statement["advance_recoupment_cents"] = 0
    statement["gross_after_trueup_cents"] = (
        statement["direct_residual_cents"]
        + statement["override_residual_cents"]
        + statement["minimum_true_up_cents"]
    )
    statement["adjustment_cents"] = sum(
        r["amount_cents"] for r in adjustments_of_statement(statement["id"])
        if r["state"] == "APPLIED")
    statement["opening_deficit_cents"] = opening_deficit_cents(statement)
    pre_floor = (
        statement["gross_after_trueup_cents"]
        - statement["advance_recoupment_cents"]
        + statement["adjustment_cents"]
        - statement["opening_deficit_cents"]
    )
    if pre_floor >= 0:
        statement["net_payable_cents"] = pre_floor
        statement["carry_forward_deficit_cents"] = 0
    else:
        statement["net_payable_cents"] = 0
        statement["carry_forward_deficit_cents"] = abs(pre_floor)
    return statement


def posted_line_for(merchant_id, period_month):
    for line in ordered(list(db.lines.values())):
        if line["merchant_id"] != merchant_id:
            continue
        batch = db.batches.get(line["residual_batch_id"])
        if batch is None:
            continue
        if batch["period_month"] == period_month and batch["state"] == "POSTED":
            return line
    return None


def minimum_fee_reconciliation(statement):
    """PRD 3.7: per-merchant rounded shares of the monthly-minimum shortfall."""
    agent = db.agents.get(statement["agent_id"])
    if agent is None:
        return 0
    total = 0
    for allocation in allocations_of_statement(statement["id"]):
        if allocation["allocation_type"] != "DIRECT_SPLIT":
            continue
        merchant = db.merchants.get(allocation["merchant_id"])
        if merchant is None or merchant["status"] != "ACTIVE":
            continue
        program = db.programs.get(merchant["processor_program_id"])
        if program is None or program["minimum_billing_mode"] == "NO_MINIMUM":
            continue
        line = posted_line_for(merchant["id"], statement["period_month"])
        if line is None:
            continue
        billable = merchant["per_transaction_fee_cents"] * line["transaction_count"]
        shortfall = merchant["monthly_minimum_cents"] - billable
        if shortfall <= 0:
            continue
        total += round_half_up(Decimal(shortfall) * agent["split_pct"] * MINIMUM_SHARE_PCT)
    return total


def advance_recoupment_schedule(statement, gross):
    """PRD 3.6: the recoupment waterfall consuming one aggregate 50% cap."""
    cap = round_half_up(Decimal(gross) * HALF)
    if cap < 0:
        cap = 0
    remaining = cap
    period_index = month_index(statement["period_month"])
    eligible = []
    for advance in db.advances.values():
        if advance["agent_id"] != statement["agent_id"] or advance["state"] != "ACTIVE":
            continue
        if month_index(advance["first_recoupment_month"]) > period_index:
            continue
        if month_index(advance["last_recoupment_month"]) < period_index:
            continue
        eligible.append(advance)
    eligible.sort(key=lambda r: (r["funded_on"], r["created_at"], r["_seq"]))
    takes = {}
    total = 0
    for advance in eligible:
        if remaining <= 0:
            break
        if advance["recoupment_mode"] == "PERCENT_OF_RESIDUAL":
            if gross < TIER_1_CEILING_CENTS:
                tier_cap = Decimal("0.25")
            elif gross < TIER_2_CEILING_CENTS:
                tier_cap = Decimal("0.40")
            else:
                tier_cap = Decimal("0.50")
            own = advance.get("recoupment_pct")
            effective = tier_cap if own is None else min(own, tier_cap)
            wanted = round_half_up(Decimal(gross) * effective)
        else:
            months = advance.get("amortization_months") or 1
            if advance["months_recouped"] + 1 >= months:
                wanted = advance["outstanding_cents"]
            else:
                wanted = round_half_up(Decimal(advance["principal_cents"]) / Decimal(months))
        taken = min(wanted, advance["outstanding_cents"], remaining)
        if taken <= 0:
            continue
        advance["outstanding_cents"] -= taken
        advance["cumulative_recouped_cents"] += taken
        advance["months_recouped"] += 1
        if advance["outstanding_cents"] == 0:
            advance["state"] = "RECOUPED"
        touch(advance)
        takes[advance["id"]] = taken
        remaining -= taken
        total += taken
    statement["_recoupments"] = takes
    return total


def reverse_advance_recoupments(statement):
    """Exact compensation of everything the issue booked against the advances."""
    for advance_id, taken in list(statement.get("_recoupments", {}).items()):
        advance = db.advances.get(advance_id)
        if advance is None:
            continue
        advance["outstanding_cents"] += taken
        advance["cumulative_recouped_cents"] -= taken
        if advance["months_recouped"] > 0:
            advance["months_recouped"] -= 1
        if advance["state"] == "RECOUPED" and advance["outstanding_cents"] > 0:
            advance["state"] = "ACTIVE"
        touch(advance)
    statement["_recoupments"] = {}


def system_adjustment(statement, kind, amount_cents, source_merchant_id=None):
    row = {
        "id": new_id(),
        "statement_id": statement["id"],
        "source_merchant_id": source_merchant_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "reason": "System-generated %s" % kind,
        "state": "APPLIED",
        "created_by_user_id": "system",
        "approved_by_user_id": None,
        "info_request_note": None,
    }
    stamp_new(row)
    db.adjustments[row["id"]] = row
    return row


# --- normalization (PRD 3.4) ------------------------------------------------
def normalize_batch(batch):
    program = db.programs.get(batch["processor_program_id"])
    mode = program["normalization_mode"]
    lines = lines_of_batch(batch["id"])
    for line in lines:
        volume_term = round_half_up(
            Decimal(line["sales_volume_cents"]) * Decimal(program["buy_rate_bps"]) / Decimal(10000)
        )
        cost = volume_term + program["buy_rate_per_item_cents"] * line["transaction_count"]
        line["processor_cost_cents"] = cost
        net = line["gross_income_cents"] - line["interchange_cents"] - line["assessments_cents"]
        if mode == "NET_REVENUE_SPLIT":
            net -= cost
        line["normalized_net_revenue_cents"] = net
        line["normalization_mode_applied"] = mode
        touch(line)
    batch["line_count"] = len(lines)
    batch["gross_volume_cents"] = sum(r["sales_volume_cents"] for r in lines)
    batch["total_normalized_net_revenue_cents"] = sum(
        r["normalized_net_revenue_cents"] for r in lines)
    batch["state"] = "NORMALIZED"
    touch(batch)
    return batch


def recall_batch(batch):
    for line in lines_of_batch(batch["id"]):
        line["processor_cost_cents"] = 0
        line["normalized_net_revenue_cents"] = 0
        line["normalization_mode_applied"] = None
        touch(line)
    batch["total_normalized_net_revenue_cents"] = 0
    batch["recall_count"] += 1
    batch["state"] = "RECEIVED"
    touch(batch)
    return batch


# --- posting cascade (PRD 3.5) ---------------------------------------------
def equipment_cost_cents(merchant, period_month):
    lease = merchant["equipment_lease_monthly_cents"]
    first_day = month_first_day(period_month)
    next_first_day = next_month_first_day(period_month)
    days_in_period = (next_first_day - first_day).days
    if merchant["status"] == "ATTRITED" and merchant.get("attrition_date"):
        attrition = parse_date(merchant["attrition_date"])
        if attrition is not None:
            if attrition < first_day:
                return 0
            if attrition < next_first_day:
                active_days = min((attrition - first_day).days + 1, days_in_period)
                return round_half_up(
                    Decimal(lease) * Decimal(active_days) / Decimal(days_in_period))
    return lease


def build_profitability(batch, line):
    period_month = batch["period_month"]
    merchant = db.merchants.get(line["merchant_id"])
    events = [r for r in db.chargebacks.values()
              if r["merchant_id"] == line["merchant_id"] and r["period_month"] == period_month]
    chargeback_all = sum(r["amount_cents"] for r in events)
    chargeback_agent = sum(r["amount_cents"] for r in events if r["liability"] == "AGENT_CHARGED")
    equipment = equipment_cost_cents(merchant, period_month) if merchant else 0
    net = line["normalized_net_revenue_cents"]
    row = {
        "id": new_id(),
        "merchant_id": line["merchant_id"],
        "residual_batch_id": batch["id"],
        "period_month": period_month,
        "normalized_net_revenue_cents": net,
        "chargeback_cost_cents": chargeback_all,
        "agent_chargeable_chargeback_cents": chargeback_agent,
        "equipment_cost_cents": equipment,
        "profit_cents": net - chargeback_all - equipment,
        "agent_basis_cents": net - chargeback_agent - equipment,
        "allocated_total_cents": 0,
        "iso_retained_cents": 0,
    }
    stamp_new(row)
    db.profitability[row["id"]] = row
    return row


def _write_allocation(agent, profitability, batch, pct, allocation_type, tier_level, touched):
    basis = profitability["agent_basis_cents"]
    raw = round_half_up(Decimal(basis) * pct)
    if agent["status"] == "DEPARTED":
        frozen = agent.get("vested_pct_at_departure") or 0
        paid = round_half_up(Decimal(basis) * pct * Decimal(frozen) / Decimal(100))
    else:
        paid = raw
    withheld = raw - paid
    if paid == 0 and withheld == 0:
        return 0
    statement, created = upsert_statement(agent["id"], batch["period_month"])
    if statement["id"] not in touched:
        touched[statement["id"]] = created
    row = {
        "id": new_id(),
        "agent_id": agent["id"],
        "merchant_id": profitability["merchant_id"],
        "statement_id": statement["id"],
        "period_month": batch["period_month"],
        "allocation_type": allocation_type,
        "tier_level": tier_level,
        "applied_pct": pct,
        "basis_cents": basis,
        "gross_allocation_cents": paid,
        "vesting_withheld_cents": withheld,
        "_batch_id": batch["id"],
        "_profitability_id": profitability["id"],
    }
    stamp_new(row)
    db.allocations[row["id"]] = row
    return paid


def split_profitability(profitability, batch, touched):
    """The differential override waterfall of PRD 3.5, cascade link 2."""
    merchant = db.merchants.get(profitability["merchant_id"])
    allocated = 0
    direct_agent = db.agents.get(merchant["owning_agent_id"]) if merchant else None
    if direct_agent is not None:
        cumulative = direct_agent["split_pct"]
        allocated += _write_allocation(
            direct_agent, profitability, batch, direct_agent["split_pct"],
            "DIRECT_SPLIT", 0, touched)
        node = direct_agent
        visits = 0
        while visits < MAX_OVERRIDE_LEVELS:
            parent_id = node.get("parent_agent_id")
            if not parent_id:
                break
            parent = db.agents.get(parent_id)
            if parent is None:
                break
            visits += 1
            differential = parent["override_pct"] - cumulative
            if differential > 0:
                allocated += _write_allocation(
                    parent, profitability, batch, differential, "OVERRIDE", visits, touched)
            if parent["override_pct"] > cumulative:
                cumulative = parent["override_pct"]
            node = parent
    profitability["allocated_total_cents"] = allocated
    profitability["iso_retained_cents"] = profitability["agent_basis_cents"] - allocated
    return profitability


def post_batch(batch):
    touched = {}
    retained = 0
    for line in lines_of_batch(batch["id"]):
        profitability = build_profitability(batch, line)
        split_profitability(profitability, batch, touched)
        retained += profitability["iso_retained_cents"]
    for statement_id in list(touched.keys()):
        statement = db.statements[statement_id]
        recompute_statement(statement)
        if not touched[statement_id]:
            touch(statement)
    batch["iso_retained_cents"] = retained
    batch["posted_at"] = db.now_iso()
    batch["state"] = "POSTED"
    touch(batch)
    return batch


def reverse_batch(batch):
    allocations = [r for r in db.allocations.values() if r.get("_batch_id") == batch["id"]]
    statement_ids = []
    for row in ordered(allocations):
        if row["statement_id"] not in statement_ids:
            statement_ids.append(row["statement_id"])
    for row in allocations:
        db.allocations.pop(row["id"], None)
    for row in [r for r in db.profitability.values() if r["residual_batch_id"] == batch["id"]]:
        db.profitability.pop(row["id"], None)
    for statement_id in statement_ids:
        statement = db.statements.get(statement_id)
        if statement is None:
            continue
        recompute_statement(statement)
        touch(statement)
    batch["iso_retained_cents"] = 0
    batch["posted_at"] = None
    batch["state"] = "REVERSED"
    touch(batch)
    return batch


# --- merchant bonus clawback and departure buyout ---------------------------
def bonus_clawback_cents(merchant, attrition_date):
    boarded = parse_date(merchant["boarded_on"])
    active_days = (attrition_date - boarded).days
    if active_days >= CLAWBACK_WINDOW_DAYS:
        return 0
    remaining = CLAWBACK_WINDOW_DAYS - active_days
    return round_half_up(
        Decimal(merchant["upfront_bonus_cents"]) * Decimal(remaining)
        / Decimal(CLAWBACK_WINDOW_DAYS))


def departure_vested_buyout(agent, frozen_pct):
    rows = [r for r in statements_of_agent(agent["id"])
            if r["lifecycle_state"] in ("ISSUED", "FINALIZED")]
    rows.sort(key=lambda r: r["period_month"], reverse=True)
    window = rows[:3]
    if not window:
        return 0
    average = round_half_up(
        Decimal(sum(r["gross_after_trueup_cents"] for r in window)) / Decimal(len(window)))
    return round_half_up(
        Decimal(average) * Decimal(VESTING_BUYOUT_MULTIPLE) * Decimal(frozen_pct) / Decimal(100))


def apply_hold_cascade(agent_id, already_touched=None):
    """PRD 3.3: the attrition risk hold moves every unsettled draft/issued statement to HELD.

    A statement the same write already touched (or created) advances its version
    only once for that write, so its id is passed in through already_touched.
    """
    already_touched = already_touched or set()
    for statement in statements_of_agent(agent_id):
        if statement["lifecycle_state"] not in ("DRAFT", "ISSUED"):
            continue
        if statement["settlement_state"] != "UNSETTLED":
            continue
        statement["settlement_state"] = "HELD"
        statement["hold_reason"] = "PORTFOLIO_ATTRITION_THRESHOLD"
        if statement["id"] not in already_touched:
            touch(statement)
