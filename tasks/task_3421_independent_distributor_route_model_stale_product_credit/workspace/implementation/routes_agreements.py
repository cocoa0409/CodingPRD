"""Route agreement routes: create/list/get + lifecycle actions."""
from flask import Blueprint, request

import auth
import clock
import domain
import store
import validators as V
from constants import (
    ROLE_COMPANY_ADMIN, ROLE_ROUTE_OPS, ROLE_CREDIT_ANALYST, ROLE_DISTRIBUTOR,
    SUSPEND_REASONS, REINSTATE_RESOLUTIONS, EXIT_MODES, AGREEMENT_LIVE_STATUSES,
)
from errors import (
    ERR_NOT_FOUND, ERR_TERRITORY_NOT_FOUND, ERR_DISTRIBUTOR_NOT_FOUND,
    ERR_BAKERY_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_TERRITORY_NOT_LISTED, ERR_AGREEMENT_OVERLAP, ERR_FINANCING_NOT_DISBURSED,
    ERR_REINSTATE_FORBIDDEN, raise_err,
)
from response import ok_object, ok_list, pagination_params, body

bp = Blueprint("agreements", __name__)

ALL = (ROLE_COMPANY_ADMIN, ROLE_ROUTE_OPS, ROLE_CREDIT_ANALYST, ROLE_DISTRIBUTOR)
OPS = (ROLE_ROUTE_OPS,)
REINSTATERS = (ROLE_ROUTE_OPS, ROLE_COMPANY_ADMIN)


def load_agreement(rid, user_id, role):
    agreement = store.get("agreements", rid)
    if agreement is None:
        raise_err(ERR_NOT_FOUND, "Agreement not found")
    auth.check_resource_owner(user_id, role, agreement["distributor_id"])
    return agreement


@bp.route("/agreements", methods=["POST"])
def create_agreement():
    user_id, role = auth.caller()
    auth.require_role(role, OPS)
    data = body()
    # Stage 5: body FK existence, declared input order.
    territory = distributor = bakery = None
    if data.get("territory_id") is not None:
        territory = store.get("territories", data["territory_id"])
        if territory is None:
            raise_err(ERR_TERRITORY_NOT_FOUND, "territory_id does not exist")
    if data.get("distributor_id") is not None:
        distributor = store.get("distributors", data["distributor_id"])
        if distributor is None:
            raise_err(ERR_DISTRIBUTOR_NOT_FOUND, "distributor_id does not exist")
    if data.get("bakery_id") is not None:
        bakery = store.get("bakeries", data["bakery_id"])
        if bakery is None:
            raise_err(ERR_BAKERY_NOT_FOUND, "bakery_id does not exist")
    # Stage 6: request shape.
    territory_id = V.get_str(data, "territory_id")
    distributor_id = V.get_str(data, "distributor_id")
    bakery_id = V.get_str(data, "bakery_id")
    purchase_price = V.get_int(data, "purchase_price_cents", minimum=1)
    financed = V.get_int(data, "financed_amount_cents", minimum=0)
    if financed > purchase_price:
        raise_err(ERR_INVALID_REQUEST,
                  "financed_amount_cents may not exceed purchase_price_cents")
    discount = V.get_number(data, "discount_pct")
    if not (0 < discount < 1):
        raise_err(ERR_INVALID_REQUEST, "discount_pct must be strictly between 0 and 1")
    start_str, start = V.get_date(data, "start_date")
    end_str, end = V.get_date(data, "end_date")
    if end <= start:
        raise_err(ERR_INVALID_REQUEST, "end_date must be strictly after start_date")
    # Stage 7: state preconditions.
    if territory["status"] != "LISTED":
        raise_err(ERR_TERRITORY_NOT_LISTED, "Territory is not LISTED")
    # Stage 11: half-open interval non-overlap per distributor.
    for existing in domain.agreements_of(distributor_id):
        if existing["status"] not in AGREEMENT_LIVE_STATUSES:
            continue
        if existing["_start"] < end and start < existing["_end"]:
            raise_err(ERR_AGREEMENT_OVERLAP,
                      "Agreement interval overlaps an existing non-terminal agreement")
    agreement = store.insert("agreements", {
        "territory_id": territory_id,
        "distributor_id": distributor_id,
        "bakery_id": bakery_id,
        "purchase_price_cents": purchase_price,
        "financed_amount_cents": financed,
        "discount_pct": discount,
        "start_date": start_str,
        "end_date": end_str,
        "status": "DRAFT",
        "suspension_reason": None,
        "strike_count": 0,
        "activated_on": None,
        "exited_on": None,
        "_start": start,
        "_end": end,
        "_activated_date": None,
    })
    territory["status"] = "UNDER_AGREEMENT"
    store.touch(territory)
    return ok_object(agreement, 201)


@bp.route("/agreements", methods=["GET"])
def list_agreements():
    auth.caller()
    agreements = store.all_of("agreements")
    for param in ("territory_id", "distributor_id", "bakery_id", "status"):
        value = request.args.get(param)
        if value is not None:
            agreements = [a for a in agreements if a[param] == value]
    page = pagination_params()
    total = len(agreements)
    window = agreements[page["offset"]:page["offset"] + page["limit"]]
    return ok_list(window, total, page)


@bp.route("/agreements/<rid>", methods=["GET"])
def get_agreement(rid):
    user_id, role = auth.caller()
    auth.require_role(role, ALL)
    return ok_object(load_agreement(rid, user_id, role))


@bp.route("/agreements/<rid>/activate", methods=["POST"])
def activate(rid):
    user_id, role = auth.caller()
    auth.require_role(role, OPS)
    agreement = store.get("agreements", rid)
    if agreement is None:
        raise_err(ERR_NOT_FOUND, "Agreement not found")
    if agreement["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT agreement can be activated")
    if agreement["financed_amount_cents"] > 0:
        plans = domain.plans_of_agreement(rid)
        if not any(p["status"] == "ACTIVE" for p in plans):
            raise_err(ERR_FINANCING_NOT_DISBURSED,
                      "Financed activation requires an ACTIVE financing plan")
    agreement["status"] = "ACTIVE"
    agreement["activated_on"] = clock.iso()
    agreement["_activated_date"] = clock.today()
    store.touch(agreement)
    distributor = store.get("distributors", agreement["distributor_id"])
    distributor["status"] = "ACTIVE"
    store.touch(distributor)
    return ok_object(agreement)


@bp.route("/agreements/<rid>/suspend", methods=["POST"])
def suspend(rid):
    user_id, role = auth.caller()
    auth.require_role(role, OPS)
    agreement = store.get("agreements", rid)
    if agreement is None:
        raise_err(ERR_NOT_FOUND, "Agreement not found")
    data = body()
    reason = V.get_enum(data, "reason", SUSPEND_REASONS)
    if agreement["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE agreement can be suspended")
    domain.suspend_agreement(agreement, reason)
    return ok_object(agreement)


@bp.route("/agreements/<rid>/reinstate", methods=["POST"])
def reinstate(rid):
    user_id, role = auth.caller()
    auth.require_role(role, REINSTATERS)
    agreement = store.get("agreements", rid)
    if agreement is None:
        raise_err(ERR_NOT_FOUND, "Agreement not found")
    # Stage 3 companion rule: classification-dispute resolution is CompanyAdmin-only.
    if (agreement["status"] == "SUSPENDED_CLASSIFICATION"
            and role == ROLE_ROUTE_OPS):
        raise_err(ERR_REINSTATE_FORBIDDEN,
                  "Only CompanyAdmin may resolve a classification suspension")
    data = body()
    resolution = V.get_enum(data, "resolution", REINSTATE_RESOLUTIONS, required=False)
    if agreement["status"] == "SUSPENDED_SERVICE":
        agreement["status"] = "ACTIVE"
        agreement["suspension_reason"] = None
        store.touch(agreement)
        return ok_object(agreement)
    if agreement["status"] != "SUSPENDED_CLASSIFICATION":
        raise_err(ERR_INVALID_STATE,
                  "Only a suspended agreement can be reinstated")
    if resolution is None:
        raise_err(ERR_INVALID_REQUEST,
                  "resolution is required from SUSPENDED_CLASSIFICATION")
    distributor = store.get("distributors", agreement["distributor_id"])
    if resolution == "CONFIRMED_IC":
        agreement["status"] = "ACTIVE"
        agreement["suspension_reason"] = None
        store.touch(agreement)
        distributor["classification_status"] = "INDEPENDENT_CONTRACTOR"
        store.touch(distributor)
        return ok_object(agreement)
    # RECLASSIFIED: straight to EXITING as a for-cause exit.
    distributor["classification_status"] = "RECLASSIFIED_EMPLOYEE"
    store.touch(distributor)
    domain.begin_exit(agreement, "FOR_CAUSE")
    return ok_object(agreement)


@bp.route("/agreements/<rid>/exit", methods=["POST"])
def exit_agreement(rid):
    user_id, role = auth.caller()
    auth.require_role(role, OPS)
    agreement = store.get("agreements", rid)
    if agreement is None:
        raise_err(ERR_NOT_FOUND, "Agreement not found")
    data = body()
    mode = V.get_enum(data, "mode", EXIT_MODES)
    if agreement["status"] not in ("ACTIVE", "SUSPENDED_SERVICE"):
        raise_err(ERR_INVALID_STATE,
                  "Exit may begin only from ACTIVE or SUSPENDED_SERVICE")
    domain.begin_exit(agreement, mode)
    return ok_object(agreement)
