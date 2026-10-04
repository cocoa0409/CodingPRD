"""Catalogue configuration surface: engineers, customers, products, centers.

POST /engineers, POST /customers, POST /products and POST /service-centers are
header-exempt (PRD §2.1); business validations still apply when a caller does
present a role the operation admits.
"""

from flask import request

from db import DB, iso
from middleware import guard, optional_guard
from response import (as_enum, as_int, as_list, as_str, body, created_obj,
                      ensure_known, invalid_value, ok_list, ok_obj, page,
                      pagination, sorted_by_created)
from services import calc, core
from errors import ApiError, Err

REGIONS = ("MIDWEST", "SOUTH", "WEST", "EAST")
ENGINEER_STATUSES = ("ACTIVE", "SUSPENDED", "OFFBOARDED")
CUSTOMER_TIERS = ("STANDARD", "PREMIUM", "STUDIO")
CUSTOMER_STATUSES = ("PENDING", "ACTIVE", "CLOSED")
CENTER_STATUSES = ("OPEN", "SUSPENDED")


def register(app):
    # ---- engineers -------------------------------------------------------
    @app.route("/engineers", methods=["POST"])
    def create_engineer():
        optional_guard(["PlatformAdmin", "SalesEngineerOps"])
        data = body()
        ensure_known(data, ["full_name", "email", "region", "max_book_size"],
                     optional=("max_book_size",))
        email = as_str(data, "email", required=True)
        if core.lookup("engineers", email=email) is not None:
            raise ApiError(Err.INVALID_FIELD_VALUE,
                           "email must be unique across Engineer.")
        row = core.new_row(
            "engineers",
            full_name=as_str(data, "full_name", required=True),
            email=email,
            region=as_enum(data, "region", REGIONS),
            status="ACTIVE",
            max_book_size=as_int(data, "max_book_size", default=120),
            active_book_size=0,
            certified_family_count=0,
            seniority_tier="TIER_1",
            commission_cap_bps=5000,
            lifetime_commission_cents=0,
        )
        core.recompute_seniority(row["id"])
        return created_obj(core.public(row))

    @app.route("/engineers", methods=["GET"])
    def list_engineers():
        guard(["PlatformAdmin", "SalesEngineerOps", "Anonymous"])
        return page(core.all_rows("engineers"), filters=(
            ("region", "region", None),
            ("status", "status", None),
        ))

    @app.route("/engineers/<ident>", methods=["GET"])
    def get_engineer(ident):
        guard(["PlatformAdmin", "SalesEngineerOps", "Anonymous"])
        return ok_obj(core.public(core.fetch("engineers", ident, Err.ENGINEER_NOT_FOUND)))

    # ---- customers -------------------------------------------------------
    @app.route("/customers", methods=["POST"])
    def create_customer():
        optional_guard(["Anonymous", "SalesEngineerOps"])
        data = body()
        ensure_known(data, ["full_name", "email", "home_state", "account_tier"],
                     optional=("account_tier",))
        email = as_str(data, "email", required=True)
        if core.lookup("customers", email=email) is not None:
            raise ApiError(Err.INVALID_FIELD_VALUE,
                           "email must be unique across Customer.")
        row = core.new_row(
            "customers",
            full_name=as_str(data, "full_name", required=True),
            email=email,
            home_state=as_str(data, "home_state", required=True),
            account_tier=as_enum(data, "account_tier", CUSTOMER_TIERS,
                                 default="STANDARD", required=False),
            status="PENDING",
            assigned_engineer_id=None,
            purchased_instrument_count=0,
            lifetime_gear_credit_cents=0,
            tech_support_entitlement="NONE",
        )
        return created_obj(core.public(row))

    @app.route("/customers", methods=["GET"])
    def list_customers():
        guard(["PlatformAdmin", "SalesEngineerOps", "SupportAgent"])
        return page(core.all_rows("customers"), filters=(
            ("status", "status", None),
        ))

    @app.route("/customers/<ident>", methods=["GET"])
    def get_customer(ident):
        guard(["PlatformAdmin", "SalesEngineerOps", "SupportAgent", "Anonymous"])
        return ok_obj(core.public(core.fetch("customers", ident, Err.CUSTOMER_NOT_FOUND)))

    # ---- products --------------------------------------------------------
    @app.route("/products", methods=["POST"])
    def create_product():
        optional_guard(["PlatformAdmin"])
        data = body()
        ensure_known(data, ["product_code", "display_name", "product_family",
                            "unit_price_cents", "required_family",
                            "requires_certification", "in_catalog"],
                     optional=("required_family", "requires_certification",
                               "in_catalog"))
        code = as_str(data, "product_code", required=True)
        if core.lookup("products", product_code=code) is not None:
            raise ApiError(Err.INVALID_FIELD_VALUE,
                           "product_code must be unique across Product.")
        price = as_int(data, "unit_price_cents", required=True)
        if price < 0:
            raise invalid_value("unit_price_cents must be >= 0.")
        required_family = None
        if data.get("required_family") is not None:
            required_family = as_enum(data, "required_family", calc.PRODUCT_FAMILIES)
        row = core.new_row(
            "products",
            product_code=code,
            display_name=as_str(data, "display_name", required=True),
            product_family=as_enum(data, "product_family", calc.PRODUCT_FAMILIES),
            unit_price_cents=price,
            required_family=required_family,
            requires_certification=bool(data.get("requires_certification") or False),
            in_catalog=True if data.get("in_catalog") is None
            else bool(data.get("in_catalog")),
        )
        return created_obj(core.public(row))

    @app.route("/products", methods=["GET"])
    def list_products():
        guard(["PlatformAdmin", "SalesEngineerOps", "Engineer", "Anonymous"])
        rows = core.all_rows("products")
        family = request.args.get("product_family")
        if family is not None:
            rows = [r for r in rows if r.get("product_family") == family]
        in_catalog = request.args.get("in_catalog")
        if in_catalog is not None:
            wanted = in_catalog.strip().lower() in ("true", "1", "yes")
            rows = [r for r in rows if bool(r.get("in_catalog")) is wanted]
        limit, offset = pagination()
        rows = sorted_by_created(rows)
        return ok_list(rows, limit, offset, len(rows))

    # ---- service centers -------------------------------------------------
    @app.route("/service-centers", methods=["POST"])
    def create_service_center():
        optional_guard(["PlatformAdmin"])
        data = body()
        ensure_known(data, ["name", "region", "capacity_slots", "accepted_families"])
        families = [as_enum({"value": item}, "value", calc.PRODUCT_FAMILIES)
                    for item in as_list(data, "accepted_families", required=True)]
        row = core.new_row(
            "service_centers",
            name=as_str(data, "name", required=True),
            region=as_enum(data, "region", REGIONS),
            capacity_slots=as_int(data, "capacity_slots", required=True),
            open_ticket_count=0,
            accepted_families=families,
            status="OPEN",
        )
        return created_obj(core.public(row))

    @app.route("/service-centers", methods=["GET"])
    def list_service_centers():
        guard(["PlatformAdmin", "SupportAgent", "SalesEngineerOps"])
        return page(core.all_rows("service_centers"), filters=(
            ("region", "region", None),
            ("status", "status", None),
        ))

    @app.route("/service-centers/<ident>/suspend", methods=["POST"])
    def suspend_service_center(ident):
        guard(["PlatformAdmin"])
        center = core.fetch("service_centers", ident, Err.REFERENCED_RESOURCE_NOT_FOUND)
        center["status"] = "SUSPENDED"
        core.touch(center)
        return ok_obj(core.public(center))

    @app.route("/service-centers/<ident>/reopen", methods=["POST"])
    def reopen_service_center(ident):
        guard(["PlatformAdmin"])
        center = core.fetch("service_centers", ident, Err.REFERENCED_RESOURCE_NOT_FOUND)
        center["status"] = "OPEN"
        core.touch(center)
        return ok_obj(core.public(center))