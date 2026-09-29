"""Intake, grading, appeals and disposition of trade-ins (PRD 3.2 to 3.4)."""

from flask import Blueprint

import access
import constants as C
import serialize
import services
import store
import validators as V
from envelope import list_response, object_response, paginate
from errors import ApiError

bp = Blueprint("tradein", __name__)


@bp.post("/trade-ins")
def submit_trade_in():
    user_id, role = V.guard("Customer", "IntakeAgent")
    payload = V.body()
    customer_id = V.id_field(payload, "customer_id")
    channel = V.enum_field(payload, "channel", C.INTAKE_CHANNELS)
    product_category = V.enum_field(payload, "product_category", C.PRODUCT_CATEGORIES)
    declared_grade = V.enum_field(payload, "declared_grade", C.CONDITION_GRADES)
    msrp_minor = V.int_field(payload, "msrp_minor", minimum=1)
    item_mass_grams = V.int_field(payload, "item_mass_grams", minimum=1)
    store_location_id = V.id_field(payload, "store_location_id", required=False)
    if channel == "IN_STORE" and store_location_id is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'store_location_id' is required when channel is IN_STORE.",
        )
    if channel == "MAIL_IN" and store_location_id is not None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'store_location_id' must be null when channel is MAIL_IN.",
        )

    customer = store.require("customers", customer_id)
    location = None
    if store_location_id is not None:
        location = store.require("store_locations", store_location_id)

    access.require_owner(role, user_id, customer["id"])

    if customer["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED")
    if location is not None and location["status"] != "ACTIVE":
        raise ApiError("ERR_STORE_LOCATION_CLOSED")

    draft = {
        "msrp_minor": msrp_minor,
        "channel": channel,
        "product_category": product_category,
        "declared_grade": declared_grade,
    }
    appraised = services.quote_provisional(draft)

    window_days = (
        C.MAIL_IN_INTAKE_WINDOW_DAYS if channel == "MAIL_IN" else C.IN_STORE_INTAKE_WINDOW_DAYS
    )
    row = store.create(
        "trade_ins",
        {
            "customer_id": customer["id"],
            "store_location_id": None if location is None else location["id"],
            "channel": channel,
            "product_category": product_category,
            "declared_grade": declared_grade,
            "msrp_minor": msrp_minor,
            "item_mass_grams": item_mass_grams,
            "status": "SUBMITTED",
            "authenticity_result": "PENDING",
            "assessed_grade": None,
            "graded_by_user_id": None,
            "appeal_count": 0,
            "appraised_credit_minor": appraised,
            "receive_deadline_at": store.now() + store.days(window_days),
            "received_at": None,
            "accepted_at": None,
            "reject_reason": None,
        },
    )
    return object_response(serialize.out(row), 201)


@bp.get("/trade-ins/<trade_in_id>")
def get_trade_in(trade_in_id):
    user_id, role = V.guard("ProgramAdmin", "IntakeAgent", "Authenticator", "Customer")
    trade_in = store.require("trade_ins", trade_in_id)
    access.require_owner(role, user_id, trade_in["customer_id"])
    return object_response(serialize.out(trade_in))


@bp.get("/trade-ins")
def list_trade_ins():
    user_id, role = V.guard("ProgramAdmin", "IntakeAgent", "Authenticator", "Customer")
    limit, offset = V.pagination()
    status = V.enum_query("status", C.TRADE_IN_STATUSES)
    channel = V.enum_query("channel", C.INTAKE_CHANNELS)
    customer_id = V.id_query("customer_id")
    store_location_id = V.id_query("store_location_id")
    if customer_id is not None:
        store.require("customers", customer_id)
    if store_location_id is not None:
        store.require("store_locations", store_location_id)
    customer_id = access.scope_customer_filter(role, user_id, customer_id)

    rows = store.rows("trade_ins")
    if customer_id is not None:
        rows = [t for t in rows if t["customer_id"] == customer_id]
    if store_location_id is not None:
        rows = [t for t in rows if t.get("store_location_id") == store_location_id]
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    if channel is not None:
        rows = [t for t in rows if t["channel"] == channel]
    page, total = paginate(store.ordered(rows), limit, offset)
    return list_response(serialize.out_list(page), limit, offset, total)


@bp.post("/trade-ins/<trade_in_id>/receive")
def receive_trade_in(trade_in_id):
    V.guard("IntakeAgent")
    trade_in = store.require("trade_ins", trade_in_id)
    if trade_in["status"] != "SUBMITTED":
        raise ApiError("ERR_TRADE_IN_NOT_RECEIVABLE")
    if trade_in.get("store_location_id") is not None:
        location = store.get("store_locations", trade_in["store_location_id"])
        if location is not None and location["status"] != "ACTIVE":
            raise ApiError("ERR_STORE_LOCATION_CLOSED")
    if store.now() > trade_in["receive_deadline_at"]:
        raise ApiError("ERR_INTAKE_WINDOW_EXPIRED")
    trade_in["status"] = "RECEIVED"
    trade_in["received_at"] = store.now()
    store.touch(trade_in)
    return object_response(serialize.out(trade_in))


@bp.post("/trade-ins/<trade_in_id>/authenticate")
def authenticate_trade_in(trade_in_id):
    user_id, _role = V.guard("Authenticator")
    payload = V.body()
    authenticity_result = V.enum_field(payload, "authenticity_result", C.AUTHENTICITY_VERDICTS)
    assessed_grade = V.enum_field(
        payload, "assessed_grade", C.CONDITION_GRADES, required=False
    )
    trade_in = store.require("trade_ins", trade_in_id)
    if trade_in["status"] not in ("RECEIVED", "APPEALED"):
        raise ApiError("ERR_TRADE_IN_NOT_AUTHENTICATABLE")
    if trade_in["status"] == "APPEALED" and trade_in.get("graded_by_user_id") == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if assessed_grade is not None:
        services.grade_policy_or_error(trade_in["product_category"], assessed_grade)
        trade_in["assessed_grade"] = assessed_grade
    trade_in["authenticity_result"] = authenticity_result
    trade_in["graded_by_user_id"] = user_id
    trade_in["status"] = "AUTHENTICATED"
    store.touch(trade_in)
    return object_response(serialize.out(trade_in))


@bp.post("/trade-ins/<trade_in_id>/appeal")
def appeal_trade_in(trade_in_id):
    user_id, role = V.guard("Customer", "ProgramAdmin")
    payload = V.body()
    V.str_field(payload, "appeal_reason", allow_blank=True)
    trade_in = store.require("trade_ins", trade_in_id)
    access.require_owner(role, user_id, trade_in["customer_id"])
    if trade_in["status"] != "AUTHENTICATED":
        raise ApiError("ERR_TRADE_IN_NOT_APPEALABLE")
    if trade_in["appeal_count"] >= C.APPEAL_LIMIT:
        raise ApiError("ERR_APPEAL_LIMIT_EXCEEDED")
    trade_in["status"] = "APPEALED"
    trade_in["appeal_count"] += 1
    store.touch(trade_in)
    return object_response(serialize.out(trade_in))


@bp.post("/trade-ins/<trade_in_id>/disposition")
def disposition_trade_in(trade_in_id):
    V.guard("Authenticator", "ProgramAdmin")
    payload = V.body()
    decision = V.enum_field(payload, "decision", C.DISPOSITION_DECISIONS)
    reject_reason = V.str_field(payload, "reject_reason", required=False, allow_blank=True)
    ownership_treatment = V.enum_field(
        payload,
        "ownership_treatment",
        C.OWNERSHIP_TREATMENTS,
        required=False,
        default="OWNED_INVENTORY",
    )
    trade_in = store.require("trade_ins", trade_in_id)
    if trade_in["status"] != "AUTHENTICATED":
        raise ApiError("ERR_TRADE_IN_NOT_DISPOSITIONABLE")

    if decision == "REJECT":
        trade_in["status"] = "REJECTED"
        trade_in["reject_reason"] = reject_reason
        trade_in["appraised_credit_minor"] = 0
        store.touch(trade_in)
        return object_response(serialize.out(trade_in))

    if trade_in["authenticity_result"] == "COUNTERFEIT":
        raise ApiError("ERR_COUNTERFEIT_NOT_ACCEPTABLE")

    grade_policy = services.grade_policy_or_error(
        trade_in["product_category"], trade_in.get("assessed_grade")
    )
    credit_policy = services.credit_policy_or_error()
    customer = store.get("customers", trade_in["customer_id"])

    # First link: the trade-in itself, repriced at the assessed grade.
    final_credit = services.issuance_final(trade_in, customer, grade_policy, credit_policy)
    accepted_at = store.now()
    trade_in["status"] = "ACCEPTED"
    trade_in["accepted_at"] = accepted_at
    trade_in["appraised_credit_minor"] = final_credit
    store.touch(trade_in)

    # Second link: the brand-currency grant, pinned to the live policy row.
    grant = store.create(
        "credit_grants",
        {
            "customer_id": trade_in["customer_id"],
            "trade_in_id": trade_in["id"],
            "credit_policy_id": credit_policy["id"],
            "credit_policy_version": credit_policy["version"],
            "issued_amount_minor": final_credit,
            "remaining_minor": final_credit,
            "issued_at": accepted_at,
            "expires_at": accepted_at + store.days(credit_policy["expiry_days"]),
            "status": "ISSUED",
        },
    )

    # Third link: the grant's opening ledger entry.
    services.append_entry(grant, "ISSUE", final_credit, final_credit)

    # Parallel branch: the resale unit, salvaged at birth on a SALVAGE grade.
    assessed_grade = trade_in["assessed_grade"]
    salvage = assessed_grade == "SALVAGE"
    store.create(
        "resale_units",
        {
            "trade_in_id": trade_in["id"],
            "replacement_for_unit_id": None,
            "listed_channel_id": None,
            "product_category": trade_in["product_category"],
            "condition_grade": assessed_grade,
            "reference_msrp_minor": trade_in["msrp_minor"],
            "mass_grams": trade_in["item_mass_grams"],
            "ownership_treatment": ownership_treatment,
            "lifecycle_state": "SALVAGED" if salvage else "INTAKE",
            "accounting_state": (
                "EXPENSED" if salvage and ownership_treatment == "OWNED_INVENTORY" else "UNCAPITALIZED"
            ),
            "capitalized_cost_minor": 0,
            "list_price_minor": None,
            "current_price_minor": None,
            "markdown_step_count": 0,
            "listed_at": None,
        },
    )

    # Fourth link: the participant's derived quantities, touched exactly once.
    services.recompute_customer(customer, balance=True, diverted=True)
    return object_response(serialize.out(trade_in))
