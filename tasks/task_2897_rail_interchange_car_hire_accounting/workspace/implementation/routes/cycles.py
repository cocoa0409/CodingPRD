"""Settlement cycles, their statement and the dispute negotiation
(PRD section 3.8)."""
import re

from flask import Blueprint

import db
import middleware
import response
import shapes
from errors import fail
from middleware import endpoint
from services import exposure, ledger, pricing, serialize, settlement

bp = Blueprint("cycles", __name__)

PERIOD_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@bp.post("/car-hire/settlement-cycles")
@endpoint(roles=[db.ROLE_ACCOUNTANT])
def open_cycle():
    body = shapes.body()
    payer_road_id = shapes.s_id(body, "payer_road_id")
    payee_road_id = shapes.s_id(body, "payee_road_id")
    period_month = shapes.s_str(body, "period_month")
    if not PERIOD_MONTH_RE.match(period_month):
        fail("ERR_INVALID_REQUEST", "period_month must be formatted YYYY-MM.")
    if payer_road_id == payee_road_id:
        fail("ERR_INVALID_REQUEST", "payee_road_id must differ from payer_road_id.")

    db.lookup("railroad", payer_road_id)
    db.lookup("railroad", payee_road_id)
    middleware.require_party(payer_road_id, payee_road_id)
    middleware.require_active(middleware.acting(), payer_road_id, payee_road_id)

    for other in db.cycles.values():
        if (
            other["payer_road_id"] == payer_road_id
            and other["payee_road_id"] == payee_road_id
            and other["period_month"] == period_month
        ):
            fail("ERR_DUPLICATE_RESOURCE", "That payer, payee and period already has a cycle.")

    start, end = settlement.period_bounds(period_month)
    row = db.base_row()
    row.update(
        {
            "payer_road_id": payer_road_id,
            "payee_road_id": payee_road_id,
            "period_month": period_month,
            "period_start_at": start,
            "period_end_at": end,
            "status": "OPEN",
            "variant_applied": None,
            "movement_line_count": 0,
            "gross_hire_cents": 0,
            "reclaim_credit_cents": 0,
            "penalty_cents": 0,
            "repair_charge_cents": 0,
            "dispute_adjustment_cents": 0,
            "pre_fee_net_cents": 0,
            "clearinghouse_fee_cents": 0,
            "net_settlement_cents": 0,
            "as_reported_net_cents": 0,
            "reconciled_net_cents": 0,
            "computed_at": None,
            "exchanged_at": None,
            "dispute_deadline_at": None,
            "settled_at": None,
            "reopen_deadline_at": None,
            "reopened_at": None,
            "archived_at": None,
            "reopen_count": 0,
            "reopen_reason": None,
        }
    )
    db.cycles[row["id"]] = row
    return response.ok(serialize.cycle(row), 201)


@bp.get("/car-hire/settlement-cycles")
@endpoint(roles=db.ALL_ROLES)
def list_cycles():
    response.page_params()
    status = shapes.q_enum("status", db.CYCLE_STATUS)
    payer = shapes.q_str("payer_road_id")
    payee = shapes.q_str("payee_road_id")
    period_month = shapes.q_str("period_month")
    rows = list(db.cycles.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if payer is not None:
        rows = [r for r in rows if r["payer_road_id"] == payer]
    if payee is not None:
        rows = [r for r in rows if r["payee_road_id"] == payee]
    if period_month is not None:
        rows = [r for r in rows if r["period_month"] == period_month]
    rows.sort(key=lambda r: (r["period_month"], r["created_at"], r["_seq"]))
    return response.paginate(rows, serialize.cycle)


@bp.get("/car-hire/settlement-cycles/<settlement_cycle_id>")
@endpoint(roles=db.ALL_ROLES, path_params=[("settlement_cycle_id", "cycle")])
def read_cycle(cycle):
    middleware.party_cycle(cycle)
    return response.ok(serialize.cycle(cycle))


@bp.get("/car-hire/settlement-cycles/<settlement_cycle_id>/statement")
@endpoint(
    roles=[db.ROLE_ADMIN, db.ROLE_ACCOUNTANT], path_params=[("settlement_cycle_id", "cycle")]
)
def read_statement(cycle):
    variant = shapes.q_str("variant") or "AS_REPORTED"
    shapes.check_enum("variant", variant, db.STATEMENT_VARIANT)
    middleware.party_cycle(cycle)
    statement = settlement.build_statement(cycle, variant)
    return response.ok(
        {
            "settlement_cycle_id": cycle["id"],
            "variant_applied": statement["variant_applied"],
            "payer_road_id": cycle["payer_road_id"],
            "payee_road_id": cycle["payee_road_id"],
            "period_month": cycle["period_month"],
            "movement_line_count": statement["movement_line_count"],
            "gross_hire_cents": statement["gross_hire_cents"],
            "reclaim_credit_cents": statement["reclaim_credit_cents"],
            "penalty_cents": statement["penalty_cents"],
            "repair_charge_cents": statement["repair_charge_cents"],
            "dispute_adjustment_cents": statement["dispute_adjustment_cents"],
            "pre_fee_net_cents": statement["pre_fee_net_cents"],
            "clearinghouse_fee_cents": statement["clearinghouse_fee_cents"],
            "net_settlement_cents": statement["net_settlement_cents"],
            "included_movement_ids": statement["included_movement_ids"],
            "included_repair_bill_ids": statement["included_repair_bill_ids"],
        }
    )


@bp.post("/car-hire/settlement-cycles/<settlement_cycle_id>/compute")
@endpoint(roles=[db.ROLE_ACCOUNTANT], path_params=[("settlement_cycle_id", "cycle")])
def compute_cycle(cycle):
    body = shapes.body()
    variant = shapes.s_str(body, "variant", required=False)
    shapes.check_enum("variant", variant, db.STATEMENT_VARIANT)
    # the computation belongs to the payee road
    middleware.require_party(cycle["payee_road_id"])
    if cycle["status"] not in ("OPEN", "REOPENED"):
        fail("ERR_INVALID_STATE_TRANSITION")
    middleware.require_active(
        middleware.acting(), cycle["payer_road_id"], cycle["payee_road_id"]
    )
    if db.now() < cycle["period_end_at"]:
        fail("ERR_PERIOD_NOT_ENDED")

    payer = db.railroads[cycle["payer_road_id"]]
    if exposure.snapshot_cents(payer) > int(payer["per_diem_credit_limit_cents"]):
        fail("ERR_PER_DIEM_CREDIT_LIMIT_EXCEEDED")

    if variant is None:
        variant = settlement.default_variant(cycle)
    settlement.compute(cycle, variant)
    return response.ok(serialize.cycle(cycle))


@bp.post("/car-hire/settlement-cycles/<settlement_cycle_id>/exchange")
@endpoint(roles=[db.ROLE_ACCOUNTANT], path_params=[("settlement_cycle_id", "cycle")])
def exchange_cycle(cycle):
    middleware.require_party(cycle["payee_road_id"])
    if cycle["status"] != "COMPUTED":
        fail("ERR_INVALID_STATE_TRANSITION")
    middleware.require_active(
        middleware.acting(), cycle["payer_road_id"], cycle["payee_road_id"]
    )
    cycle["status"] = "EXCHANGED"
    cycle["exchanged_at"] = db.now()
    cycle["dispute_deadline_at"] = db.now() + db.days(db.DISPUTE_WINDOW_DAYS)
    db.touch(cycle)
    return response.ok(serialize.cycle(cycle))


@bp.post("/car-hire/settlement-cycles/<settlement_cycle_id>/settle")
@endpoint(roles=[db.ROLE_ACCOUNTANT], path_params=[("settlement_cycle_id", "cycle")])
def settle_cycle(cycle):
    middleware.require_party(cycle["payer_road_id"])
    if cycle["status"] != "EXCHANGED":
        fail("ERR_INVALID_STATE_TRANSITION")
    middleware.require_active(
        middleware.acting(), cycle["payer_road_id"], cycle["payee_road_id"]
    )
    for d in db.disputes.values():
        if d["settlement_cycle_id"] == cycle["id"] and d["status"] in ("OPEN", "COUNTERED"):
            fail("ERR_OPEN_DISPUTES_BLOCK_SETTLEMENT")

    cycle["status"] = "SETTLED"
    cycle["settled_at"] = db.now()
    cycle["reopen_deadline_at"] = db.now() + db.days(db.REOPEN_WINDOW_DAYS)
    db.touch(cycle)
    ledger.mint(
        "SETTLEMENT_PAYMENT",
        -int(cycle["net_settlement_cents"] or 0),
        cycle["payer_road_id"],
        cycle["payee_road_id"],
        "POST /car-hire/settlement-cycles/{id}/settle remitted cycle %s" % cycle["id"],
        settlement_cycle_id=cycle["id"],
    )
    return response.ok(serialize.cycle(cycle))


@bp.post("/car-hire/settlement-cycles/<settlement_cycle_id>/reopen")
@endpoint(roles=[db.ROLE_ADMIN], path_params=[("settlement_cycle_id", "cycle")])
def reopen_cycle(cycle):
    body = shapes.body()
    reopen_reason = shapes.s_str(body, "reopen_reason")
    # --- step 11 precedes step 14: ARCHIVED is not a legal from-state for the
    # SETTLED -> REOPENED edge, so the generic transition gate speaks first. ---
    if cycle["status"] != "SETTLED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if cycle["reopen_deadline_at"] is not None and db.now() > cycle["reopen_deadline_at"]:
        fail("ERR_REOPEN_WINDOW_EXPIRED")

    cycle["status"] = "REOPENED"
    cycle["reopened_at"] = db.now()
    cycle["reopen_count"] = int(cycle["reopen_count"] or 0) + 1
    cycle["reopen_reason"] = reopen_reason
    db.touch(cycle)
    payments = ledger.entries_for_cycle(cycle["id"], "SETTLEMENT_PAYMENT")
    if payments:
        ledger.mint(
            "CORRECTION_ADJUSTMENT",
            -int(payments[-1]["amount_cents"]),
            cycle["payer_road_id"],
            cycle["payee_road_id"],
            "POST /car-hire/settlement-cycles/{id}/reopen reversed the settlement payment",
            settlement_cycle_id=cycle["id"],
        )
    return response.ok(serialize.cycle(cycle))


@bp.post("/car-hire/settlement-cycles/<settlement_cycle_id>/archive")
@endpoint(roles=[db.ROLE_ADMIN], path_params=[("settlement_cycle_id", "cycle")])
def archive_cycle(cycle):
    if cycle["status"] != "SETTLED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if cycle["reopen_deadline_at"] is None or db.now() <= cycle["reopen_deadline_at"]:
        fail("ERR_REOPEN_WINDOW_STILL_OPEN")
    cycle["status"] = "ARCHIVED"
    cycle["archived_at"] = db.now()
    db.touch(cycle)
    return response.ok(serialize.cycle(cycle))


# --------------------------------------------------------------------------
# disputes
# --------------------------------------------------------------------------


def _turn_holder(dispute):
    """OPEN means the respondent moves next; COUNTERED means the filer does."""
    if dispute["status"] == "OPEN":
        return dispute["respondent_road_id"]
    return dispute["filed_by_road_id"]


def _require_turn(dispute, road_id):
    if middleware.is_admin():
        return
    if middleware.acting() != road_id:
        fail("ERR_DISPUTE_TURN_VIOLATION")


@bp.post("/car-hire/disputes")
@endpoint(roles=[db.ROLE_ACCOUNTANT])
def file_dispute():
    body = shapes.body()
    settlement_cycle_id = shapes.s_id(body, "settlement_cycle_id")
    dispute_reason = shapes.s_str(body, "dispute_reason")
    disputed_amount_cents = shapes.s_int(body, "disputed_amount_cents")
    expected_cycle_version = shapes.s_int(body, "expected_cycle_version")
    movement_id = shapes.s_id(body, "movement_id", required=False)
    repair_bill_id = shapes.s_id(body, "repair_bill_id", required=False)
    filing_note = shapes.s_str(body, "filing_note", required=False)
    shapes.check_enum("dispute_reason", dispute_reason, db.DISPUTE_REASON)

    cycle = db.lookup("cycle", settlement_cycle_id)
    movement = db.lookup("movement", movement_id) if movement_id is not None else None
    bill = db.lookup("bill", repair_bill_id) if repair_bill_id is not None else None

    # only the payer files
    middleware.require_party(cycle["payer_road_id"])
    if expected_cycle_version != cycle["version"]:
        fail("ERR_STALE_VERSION")
    if cycle["status"] != "EXCHANGED":
        fail("ERR_CYCLE_NOT_EXCHANGED")
    middleware.require_active(
        middleware.acting(), cycle["payer_road_id"], cycle["payee_road_id"]
    )
    if movement is not None and movement["settlement_cycle_id"] != cycle["id"]:
        fail("ERR_DISPUTE_SUBJECT_NOT_IN_CYCLE")
    if bill is not None and bill["settlement_cycle_id"] != cycle["id"]:
        fail("ERR_DISPUTE_SUBJECT_NOT_IN_CYCLE")
    if (movement is None) == (bill is None):
        fail("ERR_DISPUTE_SUBJECT_AMBIGUOUS")
    if cycle["dispute_deadline_at"] is not None and db.now() > cycle["dispute_deadline_at"]:
        fail("ERR_DISPUTE_WINDOW_EXPIRED")
    for other in db.disputes.values():
        if other["settlement_cycle_id"] != cycle["id"] or other["status"] not in (
            "OPEN",
            "COUNTERED",
        ):
            continue
        if movement is not None and other["movement_id"] == movement["id"]:
            fail("ERR_DUPLICATE_RESOURCE", "That line is already under dispute.")
        if bill is not None and other["repair_bill_id"] == bill["id"]:
            fail("ERR_DUPLICATE_RESOURCE", "That line is already under dispute.")

    if movement is not None:
        subject_net = int(movement["net_hire_cents"] or 0)
    else:
        subject_net = int(bill["total_cents"] or 0)
    if disputed_amount_cents <= 0 or disputed_amount_cents > subject_net:
        fail("ERR_DISPUTED_AMOUNT_EXCEEDS_SUBJECT")

    row = db.base_row()
    row.update(
        {
            "settlement_cycle_id": cycle["id"],
            "movement_id": movement["id"] if movement is not None else None,
            "repair_bill_id": bill["id"] if bill is not None else None,
            "filed_by_road_id": cycle["payer_road_id"],
            "respondent_road_id": cycle["payee_road_id"],
            "dispute_reason": dispute_reason,
            "subject_net_at_filing_cents": subject_net,
            "disputed_amount_cents": disputed_amount_cents,
            "counter_amount_cents": None,
            "resolution_amount_cents": None,
            "round_number": 0,
            "status": "OPEN",
            "filing_note": filing_note,
            "counter_note": None,
            "withdraw_reason": None,
            "last_action_at": None,
            "resolved_at": None,
        }
    )
    db.disputes[row["id"]] = row
    db.touch(cycle)
    return response.ok(serialize.dispute(row), 201)


@bp.get("/car-hire/disputes")
@endpoint(roles=db.ALL_ROLES)
def list_disputes():
    response.page_params()
    status = shapes.q_enum("status", db.DISPUTE_STATUS)
    reason = shapes.q_enum("dispute_reason", db.DISPUTE_REASON)
    cycle_id = shapes.q_str("settlement_cycle_id")
    movement_id = shapes.q_str("movement_id")
    repair_bill_id = shapes.q_str("repair_bill_id")
    filed_by = shapes.q_str("filed_by_road_id")
    respondent = shapes.q_str("respondent_road_id")
    rows = list(db.disputes.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if reason is not None:
        rows = [r for r in rows if r["dispute_reason"] == reason]
    if cycle_id is not None:
        rows = [r for r in rows if r["settlement_cycle_id"] == cycle_id]
    if movement_id is not None:
        rows = [r for r in rows if r["movement_id"] == movement_id]
    if repair_bill_id is not None:
        rows = [r for r in rows if r["repair_bill_id"] == repair_bill_id]
    if filed_by is not None:
        rows = [r for r in rows if r["filed_by_road_id"] == filed_by]
    if respondent is not None:
        rows = [r for r in rows if r["respondent_road_id"] == respondent]
    rows.sort(key=db.order_key)
    return response.paginate(rows, serialize.dispute)


@bp.get("/car-hire/disputes/<dispute_id>")
@endpoint(roles=db.ALL_ROLES, path_params=[("dispute_id", "dispute")])
def read_dispute(dispute):
    middleware.party_dispute(dispute)
    return response.ok(serialize.dispute(dispute))


@bp.post("/car-hire/disputes/<dispute_id>/counter")
@endpoint(roles=[db.ROLE_ACCOUNTANT], path_params=[("dispute_id", "dispute")])
def counter_dispute(dispute):
    body = shapes.body()
    counter_amount_cents = shapes.s_int(body, "counter_amount_cents")
    counter_note = shapes.s_str(body, "counter_note", required=False)

    cycle = db.cycles[dispute["settlement_cycle_id"]]
    middleware.party_dispute(dispute)
    if dispute["status"] not in ("OPEN", "COUNTERED"):
        fail("ERR_INVALID_STATE_TRANSITION")
    middleware.require_active(
        middleware.acting(), dispute["filed_by_road_id"], dispute["respondent_road_id"]
    )
    if int(dispute["round_number"] or 0) >= db.MAX_DISPUTE_ROUNDS:
        fail("ERR_DISPUTE_ROUNDS_EXHAUSTED")
    _require_turn(dispute, _turn_holder(dispute))

    disputed = int(dispute["disputed_amount_cents"])
    if dispute["status"] == "OPEN":
        low = 0
    else:
        low = int(dispute["counter_amount_cents"] or 0)
    if counter_amount_cents < low or counter_amount_cents > disputed:
        fail("ERR_COUNTER_AMOUNT_OUT_OF_RANGE")

    dispute["status"] = "COUNTERED" if dispute["status"] == "OPEN" else "OPEN"
    dispute["counter_amount_cents"] = counter_amount_cents
    dispute["counter_note"] = counter_note
    dispute["round_number"] = int(dispute["round_number"] or 0) + 1
    dispute["last_action_at"] = db.now()
    db.touch(dispute)
    return response.ok(serialize.dispute(dispute))


@bp.post("/car-hire/disputes/<dispute_id>/accept")
@endpoint(roles=[db.ROLE_ACCOUNTANT], path_params=[("dispute_id", "dispute")])
def accept_dispute(dispute):
    cycle = db.cycles[dispute["settlement_cycle_id"]]
    middleware.party_dispute(dispute)
    if dispute["status"] not in ("OPEN", "COUNTERED"):
        fail("ERR_INVALID_STATE_TRANSITION")
    middleware.require_active(
        middleware.acting(), dispute["filed_by_road_id"], dispute["respondent_road_id"]
    )
    _require_turn(dispute, _turn_holder(dispute))

    if dispute["counter_amount_cents"] is not None:
        resolution = int(dispute["counter_amount_cents"])
    else:
        resolution = int(dispute["disputed_amount_cents"])
    dispute["status"] = "ACCEPTED"
    dispute["resolution_amount_cents"] = resolution
    dispute["last_action_at"] = db.now()
    dispute["resolved_at"] = db.now()
    db.touch(dispute)

    if dispute["movement_id"]:
        movement = db.movements[dispute["movement_id"]]
        pricing.recompute_net(movement)
        db.touch(movement)
    ledger.mint(
        "DISPUTE_ADJUSTMENT",
        -resolution,
        cycle["payer_road_id"],
        cycle["payee_road_id"],
        "POST /car-hire/disputes/{id}/accept resolved dispute %s" % dispute["id"],
        settlement_cycle_id=cycle["id"],
        movement_id=dispute["movement_id"],
        repair_bill_id=dispute["repair_bill_id"],
        dispute_id=dispute["id"],
    )
    settlement.recompute(cycle, "RECONCILED")
    return response.ok(serialize.dispute(dispute))


@bp.post("/car-hire/disputes/<dispute_id>/withdraw")
@endpoint(roles=[db.ROLE_ACCOUNTANT], path_params=[("dispute_id", "dispute")])
def withdraw_dispute(dispute):
    body = shapes.body()
    withdraw_reason = shapes.s_str(body, "withdraw_reason")

    middleware.party_dispute(dispute)
    if dispute["status"] not in ("OPEN", "COUNTERED"):
        fail("ERR_INVALID_STATE_TRANSITION")
    middleware.require_active(
        middleware.acting(), dispute["filed_by_road_id"], dispute["respondent_road_id"]
    )
    # withdrawal belongs to the filer from either live state
    _require_turn(dispute, dispute["filed_by_road_id"])

    dispute["status"] = "WITHDRAWN"
    dispute["withdraw_reason"] = withdraw_reason
    dispute["resolution_amount_cents"] = 0
    dispute["last_action_at"] = db.now()
    dispute["resolved_at"] = db.now()
    db.touch(dispute)
    return response.ok(serialize.dispute(dispute))
