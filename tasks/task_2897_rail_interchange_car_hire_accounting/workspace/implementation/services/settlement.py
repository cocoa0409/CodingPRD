"""Settlement cycle membership, the eight step statement, and recomputation
cascades (PRD sections 2.9 and 3.8)."""
from datetime import datetime, timezone

import db
from services import ledger, money


def period_bounds(period_month):
    year = int(period_month[0:4])
    month = int(period_month[5:7])
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def member_movements(cycle):
    """Closed, hire liable segments handled by the payer and owned by the payee
    whose end_at falls in the half-open period."""
    start = cycle["period_start_at"]
    end = cycle["period_end_at"]
    rows = [
        m
        for m in db.movements.values()
        if m["status"] == "CLOSED"
        and m["handling_road_id"] == cycle["payer_road_id"]
        and m["owner_road_id"] == cycle["payee_road_id"]
        and m["hire_liable"]
        and m["end_at"] is not None
        and start <= m["end_at"] < end
    ]
    rows.sort(key=lambda m: (m["end_at"], m["_seq"]))
    return rows


def member_bills(cycle):
    start = cycle["period_start_at"]
    end = cycle["period_end_at"]
    rows = [
        b
        for b in db.bills.values()
        if b["status"] in ("ACCEPTED", "SETTLED")
        and b["billing_road_id"] == cycle["payee_road_id"]
        and b["responsible_road_id"] == cycle["payer_road_id"]
        and b["accepted_at"] is not None
        and start <= b["accepted_at"] < end
    ]
    rows.sort(key=db.order_key)
    return rows


def has_accepted_dispute(cycle):
    return any(
        d["settlement_cycle_id"] == cycle["id"] and d["status"] == "ACCEPTED"
        for d in db.disputes.values()
    )


def default_variant(cycle):
    return "RECONCILED" if has_accepted_dispute(cycle) else "AS_REPORTED"


def build_statement(cycle, variant):
    segments = member_movements(cycle)
    bills = member_bills(cycle)

    gross = sum(int(m["gross_hire_cents"] or 0) for m in segments)
    reclaim = sum(int(m["reclaim_credit_cents"] or 0) for m in segments)
    penalty = sum(int(m["reverse_route_penalty_cents"] or 0) for m in segments)
    repair = sum(int(b["total_cents"] or 0) for b in bills)

    if variant == "RECONCILED":
        dispute_adjustment = sum(
            int(m["adjusted_net_hire_cents"] or 0) - int(m["net_hire_cents"] or 0)
            for m in segments
        )
        segment_total = sum(int(m["adjusted_net_hire_cents"] or 0) for m in segments)
    else:
        dispute_adjustment = 0
        segment_total = sum(int(m["net_hire_cents"] or 0) for m in segments)

    pre_fee_net = segment_total + repair
    fee = money.clearinghouse_fee_cents(pre_fee_net)
    net_settlement = pre_fee_net - fee

    return {
        "variant_applied": variant,
        "movement_line_count": len(segments),
        "gross_hire_cents": gross,
        "reclaim_credit_cents": reclaim,
        "penalty_cents": penalty,
        "repair_charge_cents": repair,
        "dispute_adjustment_cents": dispute_adjustment,
        "pre_fee_net_cents": pre_fee_net,
        "clearinghouse_fee_cents": fee,
        "net_settlement_cents": net_settlement,
        "included_movement_ids": [m["id"] for m in segments],
        "included_repair_bill_ids": [b["id"] for b in bills],
        "_segments": segments,
        "_bills": bills,
    }


def _write_totals(cycle, statement):
    for key in (
        "variant_applied",
        "movement_line_count",
        "gross_hire_cents",
        "reclaim_credit_cents",
        "penalty_cents",
        "repair_charge_cents",
        "dispute_adjustment_cents",
        "pre_fee_net_cents",
        "clearinghouse_fee_cents",
        "net_settlement_cents",
    ):
        cycle[key] = statement[key]
    if statement["variant_applied"] == "RECONCILED":
        cycle["reconciled_net_cents"] = statement["net_settlement_cents"]
    else:
        cycle["as_reported_net_cents"] = statement["net_settlement_cents"]


def stamp_members(cycle, statement):
    """Stamp unstamped qualifying members and mint their opening entries."""
    for m in statement["_segments"]:
        if m["settlement_cycle_id"] is None:
            m["settlement_cycle_id"] = cycle["id"]
            db.touch(m)
            ledger.mint(
                "HIRE_CHARGE",
                int(m["net_hire_cents"] or 0),
                cycle["payer_road_id"],
                cycle["payee_road_id"],
                "POST /car-hire/settlement-cycles/{id}/compute minted a hire charge for movement %s"
                % m["id"],
                settlement_cycle_id=cycle["id"],
                movement_id=m["id"],
            )
    for b in statement["_bills"]:
        if b["settlement_cycle_id"] is None:
            b["settlement_cycle_id"] = cycle["id"]
            db.touch(b)
            ledger.mint(
                "REPAIR_CHARGE",
                int(b["total_cents"] or 0),
                cycle["payer_road_id"],
                cycle["payee_road_id"],
                "POST /car-hire/settlement-cycles/{id}/compute minted a repair charge for bill %s"
                % b["id"],
                settlement_cycle_id=cycle["id"],
                repair_bill_id=b["id"],
            )


def compute(cycle, variant):
    """The payee's explicit compute: stamps members, mints, writes totals."""
    statement = build_statement(cycle, variant)
    stamp_members(cycle, statement)
    statement = build_statement(cycle, variant)
    _write_totals(cycle, statement)
    cycle["status"] = "COMPUTED"
    cycle["computed_at"] = db.now()
    db.touch(cycle)
    return statement


def recompute(cycle, variant=None):
    """A server initiated recomputation triggered by a cascade.

    A cycle already SETTLED is first taken back to REOPENED, without a client
    request naming it (PRD section 2.9).
    """
    if cycle["status"] == "SETTLED":
        cycle["status"] = "REOPENED"
        cycle["reopened_at"] = db.now()
        cycle["reopen_count"] = int(cycle["reopen_count"] or 0) + 1
        db.touch(cycle)
        # The automatic cascade takes the same SETTLED -> REOPENED edge as the
        # client request, so it reverses the settlement payment the same way.
        payments = ledger.entries_for_cycle(cycle["id"], "SETTLEMENT_PAYMENT")
        if payments:
            ledger.mint(
                "CORRECTION_ADJUSTMENT",
                -int(payments[-1]["amount_cents"]),
                cycle["payer_road_id"],
                cycle["payee_road_id"],
                "automatic reopen reversed the settlement payment of cycle %s" % cycle["id"],
                settlement_cycle_id=cycle["id"],
            )
    if variant is None:
        variant = cycle["variant_applied"] or default_variant(cycle)
    statement = build_statement(cycle, variant)
    _write_totals(cycle, statement)
    db.touch(cycle)
    return statement


def recompute_for_movement(movement, variant=None):
    if not movement.get("settlement_cycle_id"):
        return None
    cycle = db.cycles.get(movement["settlement_cycle_id"])
    if cycle is None or cycle["status"] == "ARCHIVED":
        return None
    return recompute(cycle, variant)
