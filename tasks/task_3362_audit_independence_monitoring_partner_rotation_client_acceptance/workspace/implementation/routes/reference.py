"""Reference data: clients, affiliates and professionals."""

from flask import Blueprint

from core import constants as C
from core.auth import require_role
from core.db import all_rows, new_row, store
from core.errors import (
    ERR_AFFILIATE_NOT_FOUND,
    ERR_CLIENT_NOT_FOUND,
    ERR_PROFESSIONAL_NOT_FOUND,
    ERR_REFERENCED_ENTITY_NOT_FOUND,
    ApiError,
)
from core.response import send
from core.serialize import serialize, serialize_many
from core import validate as V
from routes.common import body, fetch, filter_rows, list_response

bp = Blueprint("reference", __name__)

CLIENT_FIELDS = ("legal_name", "industry_code", "jurisdiction_country",
                 "is_public_interest_entity", "parent_client_id", "naf_annual_cap_cents")
AFFILIATE_FIELDS = ("firm_name", "country_code", "network_tier", "independence_framework")
PROFESSIONAL_FIELDS = ("full_name", "grade", "home_affiliate_id",
                       "rotation_role_class", "max_workload_points")


def refresh_client(client):
    from services.independence import commit_client, recompute_client
    from services.naf import recompute_naf_pool
    recompute_naf_pool(client)
    recompute_client(client)
    commit_client(client)
    return client


@bp.route("/clients", methods=["POST"])
def create_client():
    payload = body(CLIENT_FIELDS)
    legal_name = V.string(payload, "legal_name", required=True)
    industry_code = V.enum(payload, "industry_code", C.INDUSTRY_CODES, required=True)
    jurisdiction = V.string(payload, "jurisdiction_country", required=True)
    is_pie = V.boolean(payload, "is_public_interest_entity", False)
    parent_client_id = V.string(payload, "parent_client_id", default=None, nullable=True)
    cap = V.number(payload, "naf_annual_cap_cents", default=0, minimum=0)
    require_role([C.ROLE_PLATFORM_ADMIN])
    row = new_row("clients", {
        "legal_name": legal_name,
        "industry_code": industry_code,
        "jurisdiction_country": jurisdiction,
        "is_public_interest_entity": is_pie,
        "parent_client_id": parent_client_id,
        "status": "PROSPECT",
        "naf_annual_cap_cents": int(cap),
        "naf_approved_fee_cents": 0,
        "aggregate_independence_status": "CLEAR",
        "open_finding_count": 0,
    })
    return send(serialize("client", row), 201)


@bp.route("/clients", methods=["GET"])
def list_clients():
    require_role(C.READ_ALL_ROLES)
    rows = filter_rows(all_rows("clients"), {
        "industry_code": "industry_code",
        "status": "status",
        "parent_client_id": "parent_client_id",
    })
    for row in rows:
        refresh_client(row)
    return list_response(rows, lambda row: serialize("client", row))


@bp.route("/clients/<client_id>", methods=["GET"])
def get_client(client_id):
    require_role(C.READ_ALL_ROLES)
    row = fetch("clients", client_id, ERR_CLIENT_NOT_FOUND)
    refresh_client(row)
    return send(serialize("client", row))


@bp.route("/affiliates", methods=["POST"])
def create_affiliate():
    payload = body(AFFILIATE_FIELDS)
    firm_name = V.string(payload, "firm_name", required=True)
    country_code = V.string(payload, "country_code", required=True)
    network_tier = V.enum(payload, "network_tier", C.NETWORK_TIERS, required=True)
    framework = V.enum(payload, "independence_framework", C.INDEPENDENCE_FRAMEWORKS, required=True)
    require_role([C.ROLE_PLATFORM_ADMIN])
    row = new_row("affiliates", {
        "firm_name": firm_name,
        "country_code": country_code,
        "network_tier": network_tier,
        "independence_framework": framework,
        "status": "ACTIVE",
        "open_breach_count": 0,
    })
    return send(serialize("affiliate", row), 201)


@bp.route("/affiliates", methods=["GET"])
def list_affiliates():
    require_role(C.READ_ALL_ROLES)
    rows = filter_rows(all_rows("affiliates"), {
        "network_tier": "network_tier",
        "status": "status",
        "country_code": "country_code",
    })
    return list_response(rows, lambda row: serialize("affiliate", row))


@bp.route("/affiliates/<affiliate_id>", methods=["GET"])
def get_affiliate(affiliate_id):
    require_role(C.READ_ALL_ROLES)
    row = fetch("affiliates", affiliate_id, ERR_AFFILIATE_NOT_FOUND)
    return send(serialize("affiliate", row))


@bp.route("/professionals", methods=["POST"])
def create_professional():
    payload = body(PROFESSIONAL_FIELDS)
    full_name = V.string(payload, "full_name", required=True)
    grade = V.enum(payload, "grade", C.GRADES, required=True)
    home_affiliate_id = V.string(payload, "home_affiliate_id", required=True)
    rotation_role_class = V.enum(payload, "rotation_role_class", C.ROTATION_ROLE_CLASSES, required=True)
    max_points = V.integer(payload, "max_workload_points",
                           default=C.MAX_WORKLOAD_POINTS_DEFAULT, minimum=0)
    require_role([C.ROLE_PLATFORM_ADMIN])
    if store.affiliates.get(home_affiliate_id) is None:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND,
                       "home_affiliate_id does not resolve to an existing affiliate.")
    row = new_row("professionals", {
        "full_name": full_name,
        "grade": grade,
        "home_affiliate_id": home_affiliate_id,
        "rotation_role_class": rotation_role_class,
        "availability": "AVAILABLE",
        "max_workload_points": int(max_points),
        "active_workload_points": 0,
        "rotation_exposure_months": 0,
    })
    return send(serialize("professional", row), 201)


@bp.route("/professionals", methods=["GET"])
def list_professionals():
    require_role(C.READ_ALL_ROLES)
    rows = filter_rows(all_rows("professionals"), {
        "home_affiliate_id": "home_affiliate_id",
        "grade": "grade",
        "rotation_role_class": "rotation_role_class",
        "availability": "availability",
    })
    return list_response(rows, lambda row: serialize("professional", row))


@bp.route("/professionals/<professional_id>", methods=["GET"])
def get_professional(professional_id):
    require_role(C.READ_ALL_ROLES)
    row = fetch("professionals", professional_id, ERR_PROFESSIONAL_NOT_FOUND)
    return send(serialize("professional", row))
