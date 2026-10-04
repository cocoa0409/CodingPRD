"""Supply agreement endpoints: create, list, get, activate (first activation
or re-acknowledgment of a stale spec pin).

Activation precedence (PRD 2.10): existence (5) -> activatable + spec state
(6) -> weekly-pool capacity (10) -> credit gate (11).
"""

import domain
from db import store
from errors import ApiError
from flask import Blueprint, request
from middleware import ANY_ROLES, require_roles
from response import list_response, sort_default, success_object
from util import body_json, req_dt, req_int, req_str

bp = Blueprint("agreements", __name__)


@bp.route("/potato-ops/supply-agreements", methods=["POST"])
@require_roles("AccountManager")
def create_agreement():
    body = body_json()
    customer_id = req_str(body, "customer_id")
    spec_id = req_str(body, "spec_id")
    weekly = req_int(body, "weekly_contracted_cases")
    if weekly < 1:
        raise ApiError(
            "ERR_INVALID_REQUEST", "Field 'weekly_contracted_cases': must be >= 1", 400
        )
    price = req_int(body, "price_per_case_cents")
    if price <= 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", "Field 'price_per_case_cents': must be > 0", 400
        )
    term_start = req_dt(body, "term_start")
    term_end = req_dt(body, "term_end")
    if not term_end > term_start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'term_end': must be strictly after term_start",
            400,
        )
    # Existence in declared input order: customer_id, then spec_id.
    domain.get_chain_or_404(customer_id)
    domain.get_spec_or_404(spec_id)
    a = domain.new_entity()
    a.update({
        "customer_id": customer_id,
        "spec_id": spec_id,
        "weekly_contracted_cases": weekly,
        "price_per_case_cents": price,
        "term_start": term_start,
        "term_end": term_end,
        "pinned_spec_version": None,
        "spec_stale": False,
        "under_sla_review": False,
        "current_week_allocation_cases": 0,
        "status": "DRAFT",
    })
    store.agreements[a["id"]] = a
    return success_object(domain.agreement_view(a), 201)


@bp.route("/potato-ops/supply-agreements", methods=["GET"])
@require_roles(*ANY_ROLES)
def list_agreements():
    items = list(store.agreements.values())
    customer_id = request.args.get("customer_id")
    spec_id = request.args.get("spec_id")
    status = request.args.get("status")
    if customer_id is not None:
        items = [a for a in items if a["customer_id"] == customer_id]
    if spec_id is not None:
        items = [a for a in items if a["spec_id"] == spec_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response(sort_default(items), domain.agreement_view)


@bp.route("/potato-ops/supply-agreements/<aid>", methods=["GET"])
@require_roles(*ANY_ROLES)
def get_agreement(aid):
    return success_object(domain.agreement_view(domain.get_agreement_or_404(aid)), 200)


@bp.route("/potato-ops/supply-agreements/<aid>/activate", methods=["POST"])
@require_roles("AccountManager")
def activate_agreement(aid):
    ag = domain.get_agreement_or_404(aid)
    if not (ag["status"] == "DRAFT" or (ag["status"] == "ACTIVE" and ag["spec_stale"])):
        raise ApiError(
            "ERR_AGREEMENT_NOT_ACTIVABLE",
            "activate requires the agreement DRAFT, or ACTIVE with spec_stale true",
            409,
        )
    spec = store.specs[ag["spec_id"]]
    chain = store.chains[ag["customer_id"]]
    if ag["status"] == "DRAFT":
        if spec["status"] not in ("VALIDATED", "LOCKED"):
            raise ApiError(
                "ERR_SPEC_NOT_VALIDATED",
                "agreement activation requires the spec VALIDATED or LOCKED",
                409,
            )
        if domain.pool_remaining() < ag["weekly_contracted_cases"]:
            raise ApiError(
                "ERR_WEEK_CAPACITY_EXCEEDED",
                "Agreement activation would push reserved weekly cases past the "
                "100000-case plant pool",
                422,
            )
        if chain["credit_status"] != "GOOD_STANDING":
            raise ApiError(
                "ERR_CREDIT_HOLD_ACTIVE",
                "Agreement activation requires the chain in GOOD_STANDING",
                409,
            )
        ag["status"] = "ACTIVE"
        ag["spec_stale"] = False
        ag["current_week_allocation_cases"] = ag["weekly_contracted_cases"]
        if spec["status"] == "VALIDATED":
            spec["status"] = "LOCKED"
            spec["ever_locked"] = True
            domain.touch(spec)
        # Pin AFTER the lock increment: the revision cascade flags agreements whose
        # pinned_spec_version equals the spec's pre-revision (LOCKED) version, so the
        # pin must capture the version of the LOCKED spec this agreement runs against.
        ag["pinned_spec_version"] = spec["version"]
        domain.touch(ag)
    else:
        # Re-acknowledgment of a stale spec pin on an ACTIVE agreement.
        if spec["status"] != "LOCKED":
            raise ApiError(
                "ERR_SPEC_NOT_LOCKED",
                "agreement re-ack requires the spec LOCKED",
                409,
            )
        ag["pinned_spec_version"] = spec["version"]
        ag["spec_stale"] = False
        domain.touch(ag)
    return success_object(domain.agreement_view(ag), 200)
