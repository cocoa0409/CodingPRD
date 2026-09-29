"""Service line products: the filed warranty terms."""

from flask import Blueprint

import config
import serializers
from errors import ApiError
from response import object_response, paginate
from routes.partners import READ_ROLES, lookup_partner
from store import create_record, ordered, store
from validation import Field, current_user_id, filter_enum, filter_value, parse_body, require_path_uuid, require_role

bp = Blueprint("products", __name__)

CREATE_SPEC = {
    "partner_id": Field("uuid", required=True),
    "name": Field("string", required=True, min_len=1, max_len=120),
    "line_type": Field("enum", required=True, enum=config.LINE_TYPES),
    "ownership_boundary": Field("enum", required=True, enum=config.OWNERSHIP_BOUNDARIES),
    "required_owned_segment": Field("enum", required=True, enum=config.OWNED_SEGMENTS),
    "monthly_price_cents": Field("integer", required=True, minimum=100, maximum=20000),
    "waiting_period_days": Field("integer", required=True, minimum=0, maximum=90),
    "per_occurrence_cap_cents": Field("integer", required=True, minimum=10000, maximum=2000000),
    "annual_cap_cents": Field("integer", required=True, minimum=10000, maximum=5000000),
    "permit_covered": Field("boolean"),
    "restoration_covered_scope": Field("enum", enum=config.RESTORATION_SCOPES),
    "cap_reset_basis": Field("enum", enum=config.CAP_RESET_BASES),
}


def lookup_product(product_id):
    product = store.products.get(product_id)
    if product is None:
        raise ApiError("ERR_PRODUCT_NOT_FOUND", "No service line product with id %s" % product_id)
    return product


@bp.post("/service-line-products")
def create_product():
    current_user_id()
    require_role(config.ROLE_PLATFORM_ADMIN)
    body = parse_body(CREATE_SPEC)
    partner = lookup_partner(body["partner_id"])
    # A partner cannot be activated until one of its products is AVAILABLE
    # (3.1), so the first filing necessarily happens while it is still
    # ONBOARDING; only a suspended or terminated partner may not be filed
    # against.
    if partner["status"] not in ("ONBOARDING", "ACTIVE"):
        raise ApiError("ERR_PARTNER_NOT_ACTIVE", "The sponsoring partner is not ACTIVE")
    record = create_record(
        store.products,
        {
            "partner_id": partner["id"],
            "name": body["name"],
            "line_type": body["line_type"],
            "ownership_boundary": body["ownership_boundary"],
            "required_owned_segment": body["required_owned_segment"],
            "monthly_price_cents": body["monthly_price_cents"],
            "waiting_period_days": body["waiting_period_days"],
            "per_occurrence_cap_cents": body["per_occurrence_cap_cents"],
            "annual_cap_cents": body["annual_cap_cents"],
            "permit_covered": False if body["permit_covered"] is None else body["permit_covered"],
            "restoration_covered_scope": "NONE"
            if body["restoration_covered_scope"] is None
            else body["restoration_covered_scope"],
            "cap_reset_basis": "ENROLLMENT_ANNIVERSARY" if body["cap_reset_basis"] is None else body["cap_reset_basis"],
            "status": "AVAILABLE",
        },
    )
    return object_response(serializers.product(record), 201)


@bp.get("/service-line-products")
def list_products():
    current_user_id()
    require_role(*READ_ROLES)
    partner_id = filter_value("partner_id")
    line_type = filter_enum("line_type", config.LINE_TYPES)
    status = filter_enum("status", config.PRODUCT_STATUSES)

    def matches(product):
        if partner_id is not None and product["partner_id"] != partner_id:
            return False
        if line_type is not None and product["line_type"] != line_type:
            return False
        if status is not None and product["status"] != status:
            return False
        return True

    return paginate(ordered(store.products, matches), serializers.product)


@bp.get("/service-line-products/<product_id>")
def get_product(product_id):
    current_user_id()
    require_role(*READ_ROLES)
    require_path_uuid(product_id)
    return object_response(serializers.product(lookup_product(product_id)))
