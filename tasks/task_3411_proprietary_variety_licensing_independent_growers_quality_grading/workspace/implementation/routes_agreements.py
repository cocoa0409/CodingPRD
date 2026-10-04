"""GrowerAgreement endpoints: apply, get, list, decide."""
from flask import Blueprint, request

import constants
import store
from errors import (
    err,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_AGREEMENT_WINDOW_OVERLAP,
    ERR_EXCLUSIVE_MARKETING_REQUIRED,
    ERR_GROWER_NOT_ACTIVE,
    ERR_GROWER_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_VARIETY_NOT_FOUND,
    ERR_VARIETY_NOT_RELEASED,
    ERR_VARIETY_RECALLED,
)
from helpers import (
    as_bool,
    as_dt,
    as_pos_int,
    as_str,
    as_str_list,
    body,
    check_owner,
    dump,
    opt_field,
    paginate,
    req_field,
    require_roles,
    success,
)

bp = Blueprint("agreements", __name__)

ANY_ROLE = constants.ROLES


def get_agreement_or_404(agreement_id):
    a = store.db["agreements"].get(agreement_id)
    if a is None:
        raise err(ERR_AGREEMENT_NOT_FOUND, "No agreement with the given id")
    return a


@bp.route("/licensing/agreements", methods=["POST"])
@require_roles("GrowerPrincipal")
def create_agreement():
    b = body()
    # Tier 3 ownership: the GrowerPrincipal may apply only for its own grower_id
    raw_grower_id = b.get("grower_id")
    if raw_grower_id is not None:
        check_owner(raw_grower_id)
    grower_id = as_str(req_field(b, "grower_id"), "grower_id")
    variety_id = as_str(req_field(b, "variety_id"), "variety_id")
    region_code = as_str(req_field(b, "region_code"), "region_code")
    max_planting_units = as_pos_int(req_field(b, "max_planting_units"), "max_planting_units")
    cultural_practice_codes = as_str_list(
        req_field(b, "cultural_practice_codes"),
        "cultural_practice_codes",
        allowed=constants.CULTURAL_PRACTICE_CODES,
        non_empty=True,
    )
    exclusive_marketing = as_bool(req_field(b, "exclusive_marketing"), "exclusive_marketing")
    effective_from = as_dt(req_field(b, "effective_from"), "effective_from")
    effective_to = as_dt(req_field(b, "effective_to"), "effective_to")
    if effective_to <= effective_from:
        raise err(ERR_INVALID_REQUEST, "effective_to must be after effective_from")
    # Tier 4 existence, left-to-right: grower, then variety
    grower = store.db["growers"].get(grower_id)
    if grower is None:
        raise err(ERR_GROWER_NOT_FOUND, "No grower with the given id")
    variety = store.db["varieties"].get(variety_id)
    if variety is None:
        raise err(ERR_VARIETY_NOT_FOUND, "No variety with the given id")
    # Tier 7 state: grower must be ACTIVE
    if grower["status"] != "ACTIVE":
        raise err(ERR_GROWER_NOT_ACTIVE, "Grower is not ACTIVE")
    # Tier 9 referential: variety must not be RECALLED
    if variety["status"] == "RECALLED":
        raise err(ERR_VARIETY_RECALLED, "Variety is RECALLED")
    # Tier 10 temporal: closed-interval overlap on same (grower_id, variety_id)
    # among non-terminal agreements; sharing a boundary day counts as overlap
    for a in store.db["agreements"].values():
        if (
            a["grower_id"] == grower_id
            and a["variety_id"] == variety_id
            and a["status"] in ("PENDING_REVIEW", "ACTIVE", "SUSPENDED")
            and a["effective_from"] <= effective_to
            and effective_from <= a["effective_to"]
        ):
            raise err(ERR_AGREEMENT_WINDOW_OVERLAP, "Agreement window overlaps an existing agreement")
    # Tier 11: exclusive marketing is not negotiable
    if exclusive_marketing is not True:
        raise err(ERR_EXCLUSIVE_MARKETING_REQUIRED, "exclusive_marketing must be true")
    rec = store.init_record({
        "grower_id": grower_id,
        "variety_id": variety_id,
        "region_code": region_code,
        "max_planting_units": max_planting_units,
        "units_planted": 0,
        "cultural_practice_codes": cultural_practice_codes,
        "exclusive_marketing": exclusive_marketing,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "PENDING_REVIEW",
        "decided_at": None,
        "reject_reason": None,
    })
    store.db["agreements"][rec["id"]] = rec
    return success(dump(rec), code=201)


@bp.route("/licensing/agreements/<agreementId>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_agreement(agreementId):
    return success(dump(get_agreement_or_404(agreementId)))


@bp.route("/licensing/agreements", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_agreements():
    items = list(store.db["agreements"].values())
    for f in ("grower_id", "variety_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [a for a in items if a.get(f) == val]
    page, pagination = paginate(items)
    return success(page, pagination=pagination)


@bp.route("/licensing/agreements/<agreementId>/decide", methods=["POST"])
@require_roles("ComplianceOfficer")
def decide_agreement(agreementId):
    a = get_agreement_or_404(agreementId)
    b = body()
    decision = b.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise err(ERR_INVALID_REQUEST, "decision must be APPROVE or REJECT")
    reason = opt_field(b, "reason", None)
    if a["status"] != "PENDING_REVIEW":
        raise err(ERR_INVALID_STATE, "Agreement is not PENDING_REVIEW")
    if decision == "APPROVE":
        grower = store.db["growers"].get(a["grower_id"])
        if grower is None or grower["status"] != "ACTIVE":
            raise err(ERR_GROWER_NOT_ACTIVE, "Grower is not ACTIVE")
        variety = store.db["varieties"].get(a["variety_id"])
        if variety is not None and variety["status"] == "RECALLED":
            raise err(ERR_VARIETY_RECALLED, "Variety is RECALLED")
        if variety is None or variety["status"] != "RELEASED":
            raise err(ERR_VARIETY_NOT_RELEASED, "Variety is not RELEASED")
        a["status"] = "ACTIVE"
    else:
        a["status"] = "REJECTED"
        a["reject_reason"] = reason
    a["decided_at"] = store.clock_now()
    store.touch(a)
    return success(dump(a))
