"""RoyaltyStatement — the two accrual variants, the true-up fork and the
pinned four-figure finalisation (PRD §3.9)."""

from flask import Blueprint, request

from db import db, new_row, now_iso, ordered, public, today, touch
from errors import ApiError
from middleware import EP, LM, LR, roles
from response import list_response, object_response
from services import calc, derive
from services.validate import Body

bp = Blueprint("statements", __name__)

SUPERSEDABLE = ("DRAFT", "UNDER_TRUEUP")
CLOSED_OUT_PERIOD = ("ISSUED", "SETTLED", "SUPERSEDED")
PROVISIONAL_STATUSES = ("PENDING", "CONFIRMED", "CHECKED_IN", "NO_SHOW")
FINAL_TICKET_STATUSES = ("CONFIRMED", "CHECKED_IN", "NO_SHOW", "REFUND_DUE",
                         "REFUNDED")


def _population(statement_row):
    """The orders of the run whose slot's start date falls inside the accrual
    period, replayed in ascending created_at order. CANCELLED never counts."""
    run_row = db.runs.get(statement_row["run_id"])
    if run_row is None:
        return []
    start = statement_row["_period_start"]
    end = statement_row["_period_end"]
    rows = []
    for order_row in ordered(list(db.orders.values())):
        if order_row["run_id"] != run_row["id"]:
            continue
        if order_row["status"] == "CANCELLED":
            continue
        slot_row = db.slots.get(order_row["slot_id"])
        if slot_row is None:
            continue
        # what matters is when the guest was due to walk in
        walk_in = slot_row["_start"].date()
        if start <= walk_in <= end:
            rows.append(order_row)
    return rows


def _rates(statement_row):
    agreement_row = derive.agreement(statement_row["license_agreement_id"])
    return agreement_row


def _provisional(statement_row):
    """Money the operator expects: unpaid pending orders at face value."""
    orders = [o for o in _population(statement_row)
              if o["status"] in PROVISIONAL_STATUSES]
    ticket_base = sum(o["net_amount_cents"] for o in orders)
    merch_base = sum(o["merch_amount_cents"] for o in orders)
    agreement_row = _rates(statement_row)
    royalty = calc.royalty_cents(ticket_base, merch_base,
                                 agreement_row["royalty_rate_bps"],
                                 agreement_row["merch_royalty_rate_bps"])
    return ticket_base, merch_base, royalty


def _final(statement_row):
    """Money the operator actually holds; merchandise is handed over at the
    door, so only CHECKED_IN orders carry it."""
    orders = _population(statement_row)
    ticket_base = sum(o["net_collected_cents"] for o in orders
                      if o["status"] in FINAL_TICKET_STATUSES)
    merch_base = sum(o["merch_amount_cents"] for o in orders
                     if o["status"] == "CHECKED_IN")
    agreement_row = _rates(statement_row)
    royalty = calc.royalty_cents(ticket_base, merch_base,
                                 agreement_row["royalty_rate_bps"],
                                 agreement_row["merch_royalty_rate_bps"])
    return ticket_base, merch_base, royalty


@bp.post("/royalty-statements")
@roles(LM)
def open_statement():
    body = Body(require_body=True)
    run_id = body.reference("run_id")
    period_start, start_raw = body.date_field("period_start_date")
    period_end, end_raw = body.date_field("period_end_date")
    expected_version = body.integer("expected_run_version", minimum=0)

    # rung 5 — body foreign key
    run_row = derive.run(run_id)
    # rung 7 — optimistic concurrency on the parent run
    if run_row["version"] != expected_version:
        raise ApiError("ERR_RUN_VERSION_CONFLICT")

    agreement_row = derive.agreement(run_row["license_agreement_id"])
    # rung 11 — interval and calendar bounds
    if period_end <= period_start:
        raise ApiError("ERR_INVALID_WINDOW")
    if (period_start < agreement_row["_term_start"]
            or period_end > agreement_row["_term_end"]):
        raise ApiError("ERR_PERIOD_OUTSIDE_TERM")

    # rung 17 — a period whose numbers have left the building is closed
    family = [s for s in derive.statements_of_run(run_row)
              if s["period_start_date"] == start_raw
              and s["period_end_date"] == end_raw]
    for peer in family:
        if peer["status"] in CLOSED_OUT_PERIOD:
            raise ApiError("ERR_STATEMENT_PERIOD_ISSUED")

    row = new_row()
    row.update({
        "run_id": run_row["id"],
        "license_agreement_id": agreement_row["id"],
        "period_start_date": start_raw,
        "period_end_date": end_raw,
        "ticket_base_cents": 0,
        "merch_base_cents": 0,
        "provisional_royalty_cents": 0,
        "provisional_royalty_cents_prev": 0,
        "truedown_cents": 0,
        "final_royalty_cents": 0,
        "mg_prorated_cents": 0,
        "minimum_guarantee_shortfall_cents": 0,
        "amount_due_cents": 0,
        "superseded_by_statement_id": None,
        "issued_at": None,
        "settled_at": None,
        "status": "DRAFT",
        "_period_start": period_start,
        "_period_end": period_end,
    })
    db.statements[row["id"]] = row

    # the older open row is retired, keeping its truedown as the audit trail
    for peer in family:
        if peer["status"] in SUPERSEDABLE:
            peer["status"] = "SUPERSEDED"
            peer["superseded_by_statement_id"] = row["id"]
            touch(peer)

    ticket_base, merch_base, royalty = _provisional(row)
    row["ticket_base_cents"] = ticket_base
    row["merch_base_cents"] = merch_base
    row["provisional_royalty_cents"] = royalty

    run_row["royalty_statement_count"] += 1
    touch(run_row)
    return object_response(public(row), 201)


@bp.get("/royalty-statements/<statement_id>")
@roles(LM, LR, EP)
def read_statement(statement_id):
    return object_response(public(derive.statement(statement_id)))


@bp.get("/royalty-statements")
@roles(LM, LR, EP)
def list_statements():
    rows = list(db.statements.values())
    for field in ("run_id", "license_agreement_id",
                  "superseded_by_statement_id", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return list_response(rows)


@bp.post("/royalty-statements/<statement_id>/recompute-provisional")
@roles(LM)
def recompute_provisional(statement_id):
    statement_row = derive.statement(statement_id)
    body = Body()
    body.string("note", required=False, default=None, min_len=1, max_len=500)

    # rung 8 — own state. PRD §3.9 declares the recompute only from DRAFT
    # ("Re-run the provisional accrual on a draft statement"; the two
    # destinations are DRAFT → DRAFT and DRAFT → UNDER_TRUEUP), in contrast
    # with finalisation, which names UNDER_TRUEUP as a source explicitly.
    if statement_row["status"] != "DRAFT":
        raise ApiError("ERR_STATEMENT_INVALID_STATE")

    previous = statement_row["provisional_royalty_cents"]
    ticket_base, merch_base, royalty = _provisional(statement_row)
    statement_row["provisional_royalty_cents_prev"] = previous
    statement_row["ticket_base_cents"] = ticket_base
    statement_row["merch_base_cents"] = merch_base
    statement_row["provisional_royalty_cents"] = royalty

    # one trigger, two destinations, chosen by comparing the two figures
    if royalty >= previous:
        statement_row["truedown_cents"] = 0
        statement_row["status"] = "DRAFT"
    else:
        statement_row["truedown_cents"] = previous - royalty
        statement_row["status"] = "UNDER_TRUEUP"
    touch(statement_row)
    return object_response(public(statement_row))


@bp.post("/royalty-statements/<statement_id>/finalize")
@roles(LM)
def finalize_statement(statement_id):
    statement_row = derive.statement(statement_id)
    body = Body()
    body.string("note", required=False, default=None, min_len=1, max_len=500)

    # rung 8 — own state
    if statement_row["status"] not in SUPERSEDABLE:
        raise ApiError("ERR_STATEMENT_INVALID_STATE")
    # rung 12 — the period must be genuinely over
    if today() <= statement_row["_period_end"]:
        raise ApiError("ERR_PERIOD_NOT_ENDED")

    agreement_row = derive.agreement(statement_row["license_agreement_id"])
    ticket_base, merch_base, royalty = _final(statement_row)
    statement_row["ticket_base_cents"] = ticket_base
    statement_row["merch_base_cents"] = merch_base

    # the four figures are written in a pinned order
    statement_row["final_royalty_cents"] = royalty
    term_days = ((agreement_row["_term_end"] - agreement_row["_term_start"]).days
                 + 1)
    period_days = ((statement_row["_period_end"]
                    - statement_row["_period_start"]).days + 1)
    prorated = calc.mg_prorated_cents(agreement_row["minimum_guarantee_cents"],
                                      period_days, term_days)
    statement_row["mg_prorated_cents"] = prorated
    statement_row["minimum_guarantee_shortfall_cents"] = max(
        0, prorated - statement_row["final_royalty_cents"])
    statement_row["amount_due_cents"] = (
        statement_row["final_royalty_cents"]
        + statement_row["minimum_guarantee_shortfall_cents"])

    # a statement issued out of true-up keeps its truedown_cents
    statement_row["status"] = "ISSUED"
    statement_row["issued_at"] = now_iso()
    touch(statement_row)
    return object_response(public(statement_row))


@bp.post("/royalty-statements/<statement_id>/settle")
@roles(LM)
def settle_statement(statement_id):
    statement_row = derive.statement(statement_id)
    body = Body()
    body.string("note", required=False, default=None, min_len=1, max_len=500)

    # rung 8 — own state; SETTLED is terminal
    if statement_row["status"] != "ISSUED":
        raise ApiError("ERR_STATEMENT_INVALID_STATE")

    statement_row["status"] = "SETTLED"
    statement_row["settled_at"] = now_iso()
    touch(statement_row)
    return object_response(public(statement_row))
