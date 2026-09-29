"""Closure orders, trespass incidents, range improvement projects and the logical
clock (PRD 3.10, 3.11, 3.12 and 2.5)."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import constants as K
import derive
import envelope
from errors import ApiError
import find
import services
import store
from validate import bad, date_range, field, json_body, parse_body

bp = Blueprint("ops", __name__)

ONE = Decimal("1")

CLOSURE_FIELDS = [
    field("allotment_id", "str"),
    field("order_type", "enum", values=K.ORDER_TYPE),
    field("effective_start_date", "date"),
    field("effective_end_date", "date"),
    field("justification", "str", min_len=10, max_len=500),
    field("reduction_pct", "num", min=0, max=1, required=False, nullable=True,
          default=None),
]

LIFT_FIELDS = [
    field("justification", "str", min_len=10, max_len=500, required=False,
          nullable=True, default=None),
]


def order_state(message):
    raise ApiError("ERR_CLOSURE_ORDER_STATE_INVALID", message)


def day(text):
    return store.parse_instant(text + "T00:00:00Z").date()


@bp.post("/closure-orders")
def issue_closure_order():
    body = parse_body(json_body(), CLOSURE_FIELDS)
    pct = body["reduction_pct"]
    if body["order_type"] == "DROUGHT_REDUCTION":
        if pct is None:
            bad("reduction_pct is required on a drought reduction")
        if pct <= 0 or pct > K.MAX_STOCKING_ADJUSTMENT_PCT:
            bad("reduction_pct must be greater than 0.0 and at most 0.9")
    else:
        if pct is not None and pct != ONE:
            bad("a total closure must omit reduction_pct or send exactly 1.0")
        pct = ONE
    date_range(body["effective_start_date"], body["effective_end_date"], False,
               "effective_start_date must be on or before effective_end_date")
    actor = auth.authenticate(["AuthorizedOfficer"])
    allotment = find.need("allotments", body["allotment_id"])
    for other in store.rows("closure_orders"):
        if other["allotment_id"] != allotment["id"]:
            continue
        if other["order_status"] != "ACTIVE":
            continue
        limit = store.add_days(day(other["effective_end_date"]),
                               K.CLOSURE_BUFFER_DAYS)
        if body["effective_start_date"] <= limit:
            raise ApiError("ERR_CLOSURE_ORDER_OVERLAP",
                           "an active order on this allotment ends less than "
                           "eight days before the requested start")
    record = store.insert("closure_orders", {
        "allotment_id": allotment["id"],
        "order_type": body["order_type"],
        "reduction_pct": calc.pct4(pct),
        "effective_start_date": body["effective_start_date"].isoformat(),
        "effective_end_date": body["effective_end_date"].isoformat(),
        "justification": body["justification"],
        "issuing_officer_id": actor.user_id,
        "order_status": "ACTIVE",
    })
    services.run_reallocation(allotment)
    return envelope.created(derive.closure_order_json(record))


@bp.get("/closure-orders")
def list_closure_orders():
    envelope.page_params()
    auth.any_operational()
    records = find.apply_filters(
        envelope.sort_default(store.rows("closure_orders")), [
            ("allotment_id", "allotment_id", "str"),
            ("order_status", "order_status", "str"),
            ("order_type", "order_type", "str"),
        ])
    return envelope.paginate(records, derive.closure_order_json)


@bp.get("/allotments/<allotment_id>/closure-orders")
def list_orders_of_allotment(allotment_id):
    envelope.page_params()
    auth.any_operational()
    allotment = find.need("allotments", allotment_id)
    records = [row for row in envelope.sort_default(store.rows("closure_orders"))
               if row["allotment_id"] == allotment["id"]]
    records = find.apply_filters(records, [
        ("order_status", "order_status", "str"),
        ("order_type", "order_type", "str"),
    ])
    return envelope.paginate(records, derive.closure_order_json)


@bp.get("/closure-orders/<order_id>")
def get_closure_order(order_id):
    auth.any_operational()
    record = find.need("closure_orders", order_id)
    return envelope.ok(derive.closure_order_json(record))


@bp.post("/closure-orders/<order_id>/lift")
def lift_closure_order(order_id):
    body = parse_body(json_body(), LIFT_FIELDS)
    auth.authenticate(["AuthorizedOfficer"])
    record = find.need("closure_orders", order_id)
    if record["order_status"] != "ACTIVE":
        order_state("only an ACTIVE closure order may be lifted")
    record["order_status"] = "LIFTED"
    if body["justification"] is not None:
        record["justification"] = body["justification"]
    store.touch(record)
    allotment = store.get("allotments", record["allotment_id"])
    if allotment is not None:
        services.run_reallocation(allotment)
    return envelope.ok(derive.closure_order_json(record))


# ------------------------------------------------------------------- trespass


TRESPASS_FIELDS = [
    field("allotment_id", "str"),
    field("permittee_id", "str", required=False, nullable=True, default=None),
    field("detected_at", "instant"),
    field("head_count", "int", min=1),
    field("livestock_kind", "enum", values=K.LIVESTOCK_KIND),
    field("unauthorized_days", "int", min=1),
    field("willfulness", "enum", values=K.WILLFULNESS),
]


def trespass_state(message):
    raise ApiError("ERR_TRESPASS_STATE_INVALID", message)


def prior_billed_count(permittee_id, detected_at):
    """PRD 3.11: snapshotted at detection and never recomputed."""
    if not permittee_id:
        return 0
    moment = store.parse_instant(detected_at)
    total = 0
    for other in store.rows("trespass_incidents"):
        if other["permittee_id"] != permittee_id:
            continue
        if other["incident_status"] not in ("BILLED", "RESOLVED"):
            continue
        earlier = store.parse_instant(other["detected_at"])
        if earlier is not None and moment is not None and earlier < moment:
            total += 1
    return total


@bp.post("/trespass-incidents")
def create_trespass():
    body = parse_body(json_body(), TRESPASS_FIELDS)
    auth.authenticate(["RangeSpecialist"])
    allotment = find.need("allotments", body["allotment_id"])
    permittee = find.need_optional("permittees", body["permittee_id"])
    detected_at = store.canonical_instant(body["detected_at"])
    permittee_id = permittee["id"] if permittee else None
    record = store.insert("trespass_incidents", {
        "allotment_id": allotment["id"],
        "permittee_id": permittee_id,
        "detected_at": detected_at,
        "head_count": body["head_count"],
        "livestock_kind": body["livestock_kind"],
        "unauthorized_days": body["unauthorized_days"],
        "willfulness": body["willfulness"],
        "unauthorized_aums": calc.forage_aums(body["head_count"],
                                              body["livestock_kind"],
                                              body["unauthorized_days"]),
        "billed_aums": calc.aums2(0),
        "prior_billed_incident_count": prior_billed_count(permittee_id, detected_at),
        "incident_status": "DETECTED",
    })
    return envelope.created(derive.trespass_json(record))


@bp.get("/trespass-incidents")
def list_trespass():
    envelope.page_params()
    actor = auth.any_operational()
    records = envelope.sort_default(store.rows("trespass_incidents"))
    records = auth.scope_permittee_rows(actor, records,
                                       lambda row: row["permittee_id"])
    records = find.apply_filters(records, [
        ("allotment_id", "allotment_id", "str"),
        ("permittee_id", "permittee_id", "str"),
        ("willfulness", "willfulness", "str"),
        ("incident_status", "incident_status", "str"),
    ])
    return envelope.paginate(records, derive.trespass_json)


@bp.get("/trespass-incidents/<incident_id>")
def get_trespass(incident_id):
    actor = auth.any_operational()
    record = find.need("trespass_incidents", incident_id)
    auth.require_own(actor, record["permittee_id"])
    return envelope.ok(derive.trespass_json(record))


@bp.post("/trespass-incidents/<incident_id>/bill")
def bill_trespass(incident_id):
    auth.authenticate(["AuthorizedOfficer"])
    record = find.need("trespass_incidents", incident_id)
    if record["incident_status"] != "DETECTED":
        trespass_state("only a DETECTED incident may be billed")
    if not record["permittee_id"]:
        trespass_state("an incident whose owner is undetermined cannot be billed")
    unauthorized = calc.forage_aums(record["head_count"], record["livestock_kind"],
                                    record["unauthorized_days"])
    money = calc.trespass_money(unauthorized, record["willfulness"],
                                record["prior_billed_incident_count"])
    record["unauthorized_aums"] = unauthorized
    record["billed_aums"] = money["billed_aums"]
    record["incident_status"] = "BILLED"
    store.touch(record)
    services.create_bill(record["permittee_id"], "UNAUTHORIZED_USE", money,
                         trespass_incident_id=record["id"])
    services.refresh_account_status(record["permittee_id"])
    return envelope.ok(derive.trespass_json(record))


# ------------------------------------------------------- range improvement projects


PROJECT_FIELDS = [
    field("allotment_id", "str"),
    field("project_type", "enum", values=K.PROJECT_TYPE),
    field("total_cost_cents", "int", min=1),
    field("agency_share_pct", "num", min=0, max=1),
    field("permittee_share_pct", "num", min=0, max=1),
    field("maintenance_responsibility", "enum",
          values=K.MAINTENANCE_RESPONSIBILITY),
]


def project_state(message):
    raise ApiError("ERR_PROJECT_STATE_INVALID", message)


def cost_share_money(share_cents):
    return {
        "billed_aums": calc.aums2(0),
        "fee_rate_cents_per_aum": 0,
        "base_amount_cents": share_cents,
        "admin_fee_cents": 0,
        "penalty_amount_cents": 0,
        "total_amount_cents": share_cents,
    }


@bp.post("/range-improvement-projects")
def propose_project():
    body = parse_body(json_body(), PROJECT_FIELDS)
    if body["agency_share_pct"] + body["permittee_share_pct"] != ONE:
        bad("agency_share_pct and permittee_share_pct must add up to exactly 1.0")
    auth.authenticate(["RangeSpecialist"])
    allotment = find.need("allotments", body["allotment_id"])
    record = store.insert("projects", {
        "allotment_id": allotment["id"],
        "project_type": body["project_type"],
        "total_cost_cents": body["total_cost_cents"],
        "agency_share_pct": calc.pct4(body["agency_share_pct"]),
        "permittee_share_pct": calc.pct4(body["permittee_share_pct"]),
        "permittee_share_cents": 0,
        "allocated_share_cents": 0,
        "maintenance_responsibility": body["maintenance_responsibility"],
        "project_status": "PROPOSED",
    })
    return envelope.created(derive.project_json(record))


@bp.get("/range-improvement-projects")
def list_projects():
    envelope.page_params()
    auth.any_operational()
    records = find.apply_filters(
        envelope.sort_default(store.rows("projects")), [
            ("allotment_id", "allotment_id", "str"),
            ("project_type", "project_type", "str"),
            ("maintenance_responsibility", "maintenance_responsibility", "str"),
            ("project_status", "project_status", "str"),
        ])
    return envelope.paginate(records, derive.project_json)


@bp.get("/range-improvement-projects/<project_id>")
def get_project(project_id):
    auth.any_operational()
    record = find.need("projects", project_id)
    return envelope.ok(derive.project_json(record))


@bp.post("/range-improvement-projects/<project_id>/approve")
def approve_project(project_id):
    auth.authenticate(["AuthorizedOfficer"])
    record = find.need("projects", project_id)
    if record["project_status"] != "PROPOSED":
        project_state("only a PROPOSED project may be approved")
    allotment = store.get("allotments", record["allotment_id"])
    if allotment is not None and allotment["allotment_status"] == "CLOSED":
        raise ApiError("ERR_ALLOTMENT_CLOSED",
                       "no improvement may be contracted on a closed allotment")
    record["permittee_share_cents"] = calc.cents(
        calc.dec(record["total_cost_cents"]) * calc.dec(record["permittee_share_pct"]))
    record["project_status"] = "APPROVED"
    store.touch(record)
    return envelope.ok(derive.project_json(record))


@bp.post("/range-improvement-projects/<project_id>/allocate-cost-share")
def allocate_cost_share(project_id):
    auth.authenticate(["AuthorizedOfficer"])
    record = find.need("projects", project_id)
    if record["total_cost_cents"] < 1 or record["project_status"] != "APPROVED":
        project_state("only an APPROVED project with a positive cost may be "
                      "allocated")
    eligible = [permit for permit in store.rows("permits")
                if permit["allotment_id"] == record["allotment_id"]
                and permit["permit_status"] == "ISSUED"]
    weights = [(permit["id"], permit["permitted_aums"], permit["created_at"],
                permit["_seq"]) for permit in eligible]
    shares = calc.prorata_shares(record["permittee_share_cents"], weights)
    touched = []
    for permit in eligible:
        share = shares.get(permit["id"], 0)
        if share <= 0:
            continue
        services.create_bill(permit["permittee_id"], "PROJECT_COST_SHARE",
                             cost_share_money(share), project_id=record["id"])
        if permit["permittee_id"] not in touched:
            touched.append(permit["permittee_id"])
    record["allocated_share_cents"] = (record["permittee_share_cents"]
                                       if shares else 0)
    record["project_status"] = "COST_ALLOCATED"
    store.touch(record)
    for permittee_id in touched:
        services.refresh_account_status(permittee_id)
    return envelope.ok(derive.project_json(record))


# ---------------------------------------------------------------- logical clock


CLOCK_FIELDS = [field("current_utc", "instant")]


@bp.post("/_clock/set_current_utc")
def set_clock():
    body = parse_body(json_body(), CLOCK_FIELDS)
    auth.authenticate(["SystemAdmin"])
    moment = store.parse_instant(body["current_utc"])
    if moment <= store.clock_now():
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC",
                       "the logical clock only ever moves forward")
    store.clock_set(moment)
    today = moment.date().isoformat()
    sweep_delinquency(today)
    sweep_closure_expiry(today)
    sweep_permit_expiry(today)
    return envelope.ok({})


def sweep_delinquency(today):
    """PRD 3.6: an unpaid bill whose due date has passed becomes DELINQUENT."""
    touched = []
    for bill in store.rows("bills"):
        if bill["bill_status"] != "ISSUED":
            continue
        if not (bill["due_date"] < today):
            continue
        if bill["total_amount_cents"] <= bill["amount_paid_cents"]:
            continue
        bill["bill_status"] = "DELINQUENT"
        store.touch(bill)
        if bill["permittee_id"] and bill["permittee_id"] not in touched:
            touched.append(bill["permittee_id"])
    for permittee_id in touched:
        services.refresh_account_status(permittee_id)


def sweep_closure_expiry(today):
    """PRD 3.10: an order whose end date is strictly past expires and re-cascades."""
    allotment_ids = []
    for order in store.rows("closure_orders"):
        if order["order_status"] != "ACTIVE":
            continue
        if not (order["effective_end_date"] < today):
            continue
        order["order_status"] = "EXPIRED"
        store.touch(order)
        if order["allotment_id"] not in allotment_ids:
            allotment_ids.append(order["allotment_id"])
    for allotment_id in allotment_ids:
        allotment = store.get("allotments", allotment_id)
        if allotment is not None:
            services.run_reallocation(allotment)


def sweep_permit_expiry(today):
    """PRD 3.3: an ISSUED permit whose term has run out expires."""
    for permit in store.rows("permits"):
        if permit["permit_status"] != "ISSUED":
            continue
        if permit["term_end_date"] < today:
            permit["permit_status"] = "EXPIRED"
            store.touch(permit)
