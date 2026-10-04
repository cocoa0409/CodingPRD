"""Evaluation hardware loans, the ring fence, and proof-of-concept milestones."""

import calc
import constants as K
from auth import roles
from error import (
    CatalogError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PARTNER_NOT_FOUND,
    ERR_QUALIFICATION_NOT_MET,
    ERR_RESERVED_FOR_EVALUATION,
)
from envelope import created, ok, page
from rules import (
    blueprint_or_404,
    check_product_version,
    resolve,
    resource_or_404,
)
from services import derive_available, serialize
from store import DB
from util import by_created, paginate, parse_utc, require, require_enum

GROUP = "loans"


def _caller_partner(caller):
    partner = resolve("partners", caller.user_id)
    if partner is None:
        raise CatalogError(ERR_PARTNER_NOT_FOUND, "X-User-ID does not name a partner account.")
    return partner


def _create(caller):
    from flask import request
    body = request.raw_payload or {}
    partner = _caller_partner(caller)
    product = resolve("products", require(body, "product_sku_id"))
    if product is None:
        raise CatalogError(ERR_INVALID_REQUEST, "'product_sku_id' does not resolve.")
    blueprint = blueprint_or_404(require(body, "blueprint_id"))
    units = require(body, "loan_units", "int", positive=True)
    loan = DB.mint({
        "product_sku_id": product["id"],
        "partner_id": partner["id"],
        "blueprint_id": blueprint["id"],
        "loan_units": units,
        "loan_state": "REQUESTED",
        "required_return_at": None,
        "late_fee_units": 0,
        "expected_product_version": None,
        "supply_node_id": None,
    })
    DB.loans[loan["id"]] = loan
    return created(serialize(loan))


def _list(caller):
    from flask import request
    rows = by_created(list(DB.loans.values()))
    for field in ("partner_id", "product_sku_id", "blueprint_id"):
        value = request.args.get(field)
        if value:
            rows = [row for row in rows if row.get(field) == value]
    window, meta = paginate([serialize(row) for row in rows], request.args)
    return page(window, meta)


def _read(caller, loan_id):
    return ok(serialize(resource_or_404("loans", loan_id, "evaluation loan")))


def _approve(caller, loan_id):
    from flask import request
    body = request.raw_payload if isinstance(request.raw_payload, dict) else {}
    loan = resource_or_404("loans", loan_id, "evaluation loan")
    if loan.get("loan_state") != "REQUESTED":
        raise CatalogError(ERR_INVALID_STATE, "Only a REQUESTED loan may be approved.")
    partner = DB.partners.get(loan.get("partner_id"))
    product = DB.products.get(loan.get("product_sku_id"))
    blueprint = DB.blueprints.get(loan.get("blueprint_id"))
    if partner is None:
        raise CatalogError(ERR_PARTNER_NOT_FOUND)
    if partner.get("qualification_status") != "QUALIFIED":
        raise CatalogError(ERR_QUALIFICATION_NOT_MET)
    if product is None or blueprint is None:
        raise CatalogError(ERR_INVALID_REQUEST, "The loan's product or blueprint no longer exists.")

    units = int(loan.get("loan_units", 0))
    if units > int(product.get("reserved_evaluation_units", 0) or 0):
        raise CatalogError(ERR_RESERVED_FOR_EVALUATION)
    check_product_version(product, body.get("expected_product_version"))

    loan["loan_state"] = "APPROVED"
    loan["expected_product_version"] = body.get("expected_product_version")
    loan["required_return_at"] = _plus_days(int(blueprint.get("evaluation_deadline_days", 0)))
    DB.touch(loan)

    product["reserved_evaluation_units"] = int(product.get("reserved_evaluation_units", 0)) + units
    derive_available(product)
    DB.bump(product)
    return ok(serialize(loan))


def _plus_days(days):
    from datetime import timedelta
    from util import format_utc
    return format_utc(DB.clock + timedelta(days=days))


def _start(caller, loan_id):
    loan = resource_or_404("loans", loan_id, "evaluation loan")
    if loan.get("loan_state") != "APPROVED":
        raise CatalogError(ERR_INVALID_STATE, "Only an APPROVED loan may be started.")
    loan["loan_state"] = "ACTIVE"
    loan["started_at"] = DB.now_text()
    DB.touch(loan)
    milestone = DB.mint({
        "loan_id": loan["id"],
        "milestone_type": "KICKOFF",
        "milestone_result": None,
        "recorded_at": None,
        "milestone_triggered_at": None,
        "milestone_state": "OPEN",
    })
    DB.milestones[milestone["id"]] = milestone
    return ok(serialize(loan))


def _release_ring_fence(loan):
    product = DB.products.get(loan.get("product_sku_id"))
    if product is None:
        return
    product["reserved_evaluation_units"] = max(
        0, int(product.get("reserved_evaluation_units", 0) or 0) - int(loan.get("loan_units", 0))
    )
    derive_available(product)
    DB.touch(product)


def _return(caller, loan_id):
    loan = resource_or_404("loans", loan_id, "evaluation loan")
    if loan.get("loan_state") not in ("ACTIVE", "OVERDUE"):
        raise CatalogError(ERR_INVALID_STATE, "Only an ACTIVE or OVERDUE loan may be returned.")
    loan["loan_state"] = "RETURNED"
    DB.touch(loan)
    _release_ring_fence(loan)
    return ok(serialize(loan))


def _reclaim(caller, loan_id):
    loan = resource_or_404("loans", loan_id, "evaluation loan")
    state = loan.get("loan_state")
    if state not in ("REQUESTED", "APPROVED", "OVERDUE"):
        raise CatalogError(ERR_INVALID_STATE, "The loan cannot be reclaimed from %s." % state)
    loan["loan_state"] = "RECLAIMED"
    DB.touch(loan)
    if state != "REQUESTED":
        _release_ring_fence(loan)
    return ok(serialize(loan))


def _record_milestone(caller, loan_id):
    from flask import request
    body = request.raw_payload or {}
    loan = resource_or_404("loans", loan_id, "evaluation loan")
    milestone_type = require_enum(require(body, "milestone_type"), K.MILESTONE_TYPES, "milestone_type")
    result = require_enum(require(body, "milestone_result"), K.MILESTONE_RESULTS, "milestone_result")
    milestone = DB.mint({
        "loan_id": loan["id"],
        "milestone_type": milestone_type,
        "milestone_result": result,
        "recorded_at": DB.now_text(),
        "milestone_triggered_at": None,
        "milestone_state": "RECORDED",
    })
    DB.milestones[milestone["id"]] = milestone

    if result == "PASSED" and loan.get("loan_state") == "ACTIVE":
        loan["loan_state"] = "RETURNED"
        DB.touch(loan)
        _release_ring_fence(loan)
        milestone["milestone_triggered_at"] = DB.now_text()
        milestone["milestone_state"] = "RECORDED"
        DB.touch(milestone)
        # Any KICKOFF milestone still OPEN on this loan is closed with it.
        for other in DB.milestones.values():
            if other.get("loan_id") != loan["id"] or other["id"] == milestone["id"]:
                continue
            if other.get("milestone_state") == "OPEN":
                other["milestone_state"] = "RECORDED"
                other["milestone_triggered_at"] = DB.now_text()
                DB.touch(other)
    return created(serialize(milestone))


def _list_milestones(caller):
    from flask import request
    rows = by_created(list(DB.milestones.values()))
    loan_id = request.args.get("loan_id")
    if loan_id:
        rows = [row for row in rows if row.get("loan_id") == loan_id]
    window, meta = paginate([serialize(row) for row in rows], request.args)
    return page(window, meta)


def _read_milestone(caller, milestone_id):
    return ok(serialize(resource_or_404("milestones", milestone_id, "proof-of-concept milestone")))


ROUTES = [
    ("POST", "/accelerators/evaluation-loans", _create, ("PartnerOps",)),
    ("GET", "/accelerators/evaluation-loans", _list, ("PartnerOps",)),
    ("GET", "/accelerators/evaluation-loans/<loan_id>", _read, ("PartnerOps",)),
    ("POST", "/accelerators/evaluation-loans/<loan_id>/approve", _approve, ("PartnerProgramManager",)),
    ("POST", "/accelerators/evaluation-loans/<loan_id>/start", _start, ("PartnerProgramManager",)),
    ("POST", "/accelerators/evaluation-loans/<loan_id>/return", _return, ("PartnerProgramManager",)),
    ("POST", "/accelerators/evaluation-loans/<loan_id>/reclaim", _reclaim, ("PartnerProgramManager",)),
    ("POST", "/accelerators/evaluation-loans/<loan_id>/milestones", _record_milestone, ("PartnerProgramManager",)),
    ("GET", "/accelerators/milestones", _list_milestones, ("PartnerProgramManager",)),
    ("GET", "/accelerators/milestones/<milestone_id>", _read_milestone, ("PartnerProgramManager",)),
]


def register(app):
    for method, path, handler, allowed in ROUTES:
        endpoint = "%s_%s" % (GROUP, path.replace("/", "_").replace("<", "").replace(">", ""))
        app.add_url_rule(path, endpoint + method, roles(*allowed)(handler), methods=[method])