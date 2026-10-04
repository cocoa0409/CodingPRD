"""Cut specification endpoints: create (ChainCustomer-owned), validate,
request-revision with the spec_stale cascade."""

from decimal import Decimal

import domain
from db import store
from errors import ApiError
from flask import Blueprint, g, request
from middleware import ANY_ROLES, require_roles
from response import list_response, sort_default, success_object
from util import body_json, opt_bool, req_enum, req_int, req_number, req_str
from constants import COATING_TYPES, CUT_FAMILIES, PANEL_SCORE_MIN

bp = Blueprint("specs", __name__)


@bp.route("/potato-ops/cut-specifications", methods=["POST"])
@require_roles("ChainCustomer")
def create_spec():
    body = body_json()
    # Priority 3: entity-backed ownership (evaluated when customer_id present).
    raw_customer = body.get("customer_id")
    if isinstance(raw_customer, str) and raw_customer != g.user_id:
        raise ApiError(
            "ERR_OWNERSHIP_MISMATCH",
            "ChainCustomer may author a specification only with customer_id equal to X-User-ID",
            403,
        )
    # Priority 4: shape.
    customer_id = req_str(body, "customer_id")
    spec_code = req_str(body, "spec_code")
    cut_family = req_enum(body, "cut_family", CUT_FAMILIES)
    cut_size = req_number(body, "cut_size_mm")
    if cut_size <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'cut_size_mm': must be > 0", 400)
    coating = req_enum(body, "coating_type", COATING_TYPES)
    target_color = req_number(body, "target_color_units")
    if target_color < 0 or target_color > 4:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'target_color_units': must be on the 0..4 scale",
            400,
        )
    max_cook = req_int(body, "max_cook_time_sec")
    if max_cook <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'max_cook_time_sec': must be > 0", 400)
    sensory = opt_bool(body, "sensory_panel_required", True)
    # Priority 5: existence.
    domain.get_chain_or_404(customer_id)
    s = domain.new_entity()
    s.update({
        "customer_id": customer_id,
        "spec_code": spec_code,
        "cut_family": cut_family,
        "cut_size_mm": cut_size,
        "coating_type": coating,
        "target_color_units": target_color,
        "max_cook_time_sec": max_cook,
        "sensory_panel_required": sensory,
        "panel_score": None,
        "ever_locked": False,
        "status": "SUBMITTED",
    })
    store.specs[s["id"]] = s
    return success_object(domain.spec_view(s), 201)


@bp.route("/potato-ops/cut-specifications", methods=["GET"])
@require_roles(*ANY_ROLES)
def list_specs():
    items = list(store.specs.values())
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    if customer_id is not None:
        items = [s for s in items if s["customer_id"] == customer_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_response(sort_default(items), domain.spec_view)


@bp.route("/potato-ops/cut-specifications/<sid>", methods=["GET"])
@require_roles(*ANY_ROLES)
def get_spec(sid):
    return success_object(domain.spec_view(domain.get_spec_or_404(sid)), 200)


@bp.route("/potato-ops/cut-specifications/<sid>/validate", methods=["POST"])
@require_roles("QualityAssuranceLead")
def validate_spec(sid):
    body = body_json()
    score = req_number(body, "panel_score")
    spec = domain.get_spec_or_404(sid)
    if spec["status"] not in ("SUBMITTED", "REVISION_REQUESTED"):
        raise ApiError(
            "ERR_SPEC_NOT_AWAITING_VALIDATION",
            "validate requires the spec in SUBMITTED or REVISION_REQUESTED",
            409,
        )
    if spec["sensory_panel_required"]:
        if score < Decimal(PANEL_SCORE_MIN):
            raise ApiError(
                "ERR_PANEL_SCORE_BELOW_STANDARD",
                "Sensory panel score below 7.0 on a spec requiring a panel",
                422,
            )
    elif score < 0:
        raise ApiError(
            "ERR_PANEL_SCORE_BELOW_STANDARD",
            "Panel score must be >= 0",
            422,
        )
    spec["panel_score"] = score
    if spec["status"] == "SUBMITTED":
        spec["status"] = "VALIDATED"
    else:  # REVISION_REQUESTED
        spec["status"] = "LOCKED" if spec["ever_locked"] else "VALIDATED"
    domain.touch(spec)
    return success_object(domain.spec_view(spec), 200)


@bp.route("/potato-ops/cut-specifications/<sid>/request-revision", methods=["POST"])
@require_roles("ChainCustomer")
def request_revision(sid):
    # Priority 3: ownership needs the spec; missing spec falls through to 404.
    spec = store.specs.get(sid)
    if spec is not None and spec["customer_id"] != g.user_id:
        raise ApiError(
            "ERR_OWNERSHIP_MISMATCH",
            "ChainCustomer may request a revision only on its own specifications",
            403,
        )
    if spec is None:
        raise ApiError("ERR_SPEC_NOT_FOUND", "Cut specification not found", 404)
    if spec["status"] not in ("VALIDATED", "LOCKED"):
        raise ApiError(
            "ERR_SPEC_NOT_REVISIONABLE",
            "request-revision requires the spec in VALIDATED or LOCKED",
            409,
        )
    pre_revision_version = spec["version"]
    was_locked = spec["status"] == "LOCKED"
    spec["status"] = "REVISION_REQUESTED"
    domain.touch(spec)
    if was_locked:
        domain.spec_revision_cascade(spec, pre_revision_version)
    return success_object(domain.spec_view(spec), 200)
