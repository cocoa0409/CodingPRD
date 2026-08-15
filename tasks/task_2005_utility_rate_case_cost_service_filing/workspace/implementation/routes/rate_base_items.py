"""RateBaseItem endpoints (PRD 3.3): submit-audit-revise cycle."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_CASE_STATE,
    ERR_INVALID_ITEM_STATE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_arg
from services.core import new_record, public, touch
from validate import (
    get_body,
    no_unknown_fields,
    opt_str,
    req_enum,
    req_int,
    req_str,
    require_fk,
    require_path_resource,
)

bp = Blueprint("rate_base_items", __name__)

_AMOUNT_FIELDS = (
    "plant_in_service_cents",
    "accumulated_depreciation_cents",
    "working_capital_cents",
    "accumulated_deferred_taxes_cents",
)

_AUDIT_CASE_STATES = ("FILED", "ACCEPTED", "DISCOVERY", "HEARING", "SETTLEMENT")
_REVISE_CASE_STATES = ("FILED", "ACCEPTED", "DISCOVERY", "HEARING", "SETTLEMENT", "DEFICIENT")


def _net(item):
    return (
        item["plant_in_service_cents"]
        - item["accumulated_depreciation_cents"]
        + item["working_capital_cents"]
        - item["accumulated_deferred_taxes_cents"]
    )


@bp.post("/rate-base-items")
def create_item():
    body = get_body()
    no_unknown_fields(body, {"rate_case_id", "label", *_AMOUNT_FIELDS})
    rate_case_id = req_str(body, "rate_case_id")
    label = req_str(body, "label")
    amounts = {f: req_int(body, f, non_negative=True) for f in _AMOUNT_FIELDS}
    authorized(["UtilityFiler"])
    case = require_fk("rate_cases", rate_case_id, "rate_case_id")
    if case["status"] not in ("DRAFT", "DEFICIENT"):
        raise_error(ERR_INVALID_CASE_STATE, "items may be added only while the case is DRAFT or DEFICIENT")
    fields = {"rate_case_id": rate_case_id, "label": label, **amounts}
    fields["net_rate_base_cents"] = _net(fields)
    fields["status"] = "DRAFT"
    rec = new_record("rate_base_items", fields)
    return success_object(public(rec), status=201)


@bp.get("/rate-base-items")
def list_items():
    filters = {
        "rate_case_id": query_arg("rate_case_id"),
        "status": query_arg("status"),
    }
    return list_response("rate_base_items", filters)


@bp.get("/rate-base-items/<item_id>")
def get_item(item_id):
    return get_one("rate_base_items", item_id)


@bp.post("/rate-base-items/<item_id>/submit")
def submit_item(item_id):
    body = get_body()
    no_unknown_fields(body, set())
    authorized(["UtilityFiler"])
    item = require_path_resource("rate_base_items", item_id)
    if item["status"] != "DRAFT":
        raise_error(ERR_INVALID_ITEM_STATE, "submit requires DRAFT")
    case = db["rate_cases"].get(item["rate_case_id"])
    if case is None or case["status"] not in ("DRAFT", "DEFICIENT"):
        raise_error(ERR_INVALID_CASE_STATE, "case must be DRAFT or DEFICIENT")
    item["status"] = "SUBMITTED"
    touch(item)
    return success_object(public(item))


@bp.post("/rate-base-items/<item_id>/audit")
def audit_item(item_id):
    body = get_body()
    no_unknown_fields(body, {"outcome", "exception_notes"})
    outcome = req_enum(body, "outcome", ("AUDIT_PASS", "AUDIT_EXCEPTION"))
    opt_str(body, "exception_notes")
    authorized(["CommissionStaff"])
    item = require_path_resource("rate_base_items", item_id)
    if item["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_ITEM_STATE, "audit requires SUBMITTED")
    case = db["rate_cases"].get(item["rate_case_id"])
    if case is None or case["status"] not in _AUDIT_CASE_STATES:
        raise_error(ERR_INVALID_CASE_STATE,
                    "case must be FILED, ACCEPTED, DISCOVERY, HEARING, or SETTLEMENT")
    item["status"] = "AUDITED" if outcome == "AUDIT_PASS" else "EXCEPTION"
    touch(item)
    return success_object(public(item))


@bp.post("/rate-base-items/<item_id>/revise")
def revise_item(item_id):
    body = get_body()
    no_unknown_fields(body, set(_AMOUNT_FIELDS))
    amounts = {f: req_int(body, f, non_negative=True) for f in _AMOUNT_FIELDS}
    authorized(["UtilityFiler"])
    item = require_path_resource("rate_base_items", item_id)
    if item["status"] != "EXCEPTION":
        raise_error(ERR_INVALID_ITEM_STATE, "revise requires EXCEPTION")
    case = db["rate_cases"].get(item["rate_case_id"])
    if case is None or case["status"] not in _REVISE_CASE_STATES:
        raise_error(ERR_INVALID_CASE_STATE,
                    "case must be FILED, ACCEPTED, DISCOVERY, HEARING, SETTLEMENT, or DEFICIENT")
    for f, v in amounts.items():
        item[f] = v
    item["net_rate_base_cents"] = _net(item)
    item["status"] = "SUBMITTED"
    touch(item)
    return success_object(public(item))
