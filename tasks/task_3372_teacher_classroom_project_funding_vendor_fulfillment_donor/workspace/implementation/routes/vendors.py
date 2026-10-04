"""Vendor registry, suspension, and catalog item management."""
from flask import request

import store
from envelope import ok, page_payload
from errors import bad_request, forbidden, invalid_state, not_found
from security import actor, require_roles
from serializers import catalog_item_json, vendor_json
from validators import (
    CATEGORIES,
    SHIPPING_ZONES,
    as_enum,
    as_int,
    as_str,
    as_subject_list,
    json_body,
    optional_bool,
    optional_int,
    pagination_args,
    require_present,
)

READ_ROLES = ("PlatformAdmin", "Reviewer", "Teacher", "Vendor")
LIST_ROLES = ("PlatformAdmin", "Reviewer", "Teacher", "Vendor", "Donor")


def _get_vendor(vendor_id):
    vendor = store.vendors.get(vendor_id)
    if vendor is None:
        raise not_found("Vendor not found")
    return vendor


def register(app):
    @app.route("/giving/vendors", methods=["POST"])
    def create_vendor():
        data = json_body()
        name = as_str(require_present(data, "name"), "name")
        ship_from_state = as_str(require_present(data, "ship_from_state"), "ship_from_state")
        contact_email = as_str(require_present(data, "contact_email"), "contact_email")
        _, role = actor()
        require_roles(role, ("PlatformAdmin",))
        rec = store.base_record()
        rec.update({
            "name": name,
            "ship_from_state": ship_from_state,
            "contact_email": contact_email,
            "status": "ACTIVE",
        })
        store.vendors[rec["id"]] = rec
        return ok(vendor_json(rec), 201)

    @app.route("/giving/vendors/<vendor_id>", methods=["GET"])
    def get_vendor(vendor_id):
        _, role = actor()
        require_roles(role, READ_ROLES)
        return ok(vendor_json(_get_vendor(vendor_id)), 200)

    @app.route("/giving/vendors/<vendor_id>/suspend", methods=["POST"])
    def suspend_vendor(vendor_id):
        _, role = actor()
        require_roles(role, ("PlatformAdmin",))
        vendor = _get_vendor(vendor_id)
        if vendor["status"] != "SUSPENDED":
            vendor["status"] = "SUSPENDED"
            store.touch(vendor)
        return ok(vendor_json(vendor), 200)

    @app.route("/giving/vendors/<vendor_id>/catalog-items", methods=["POST"])
    def create_catalog_item(vendor_id):
        data = json_body()
        sku = as_str(require_present(data, "sku"), "sku")
        name = as_str(require_present(data, "name"), "name")
        category = as_enum(require_present(data, "category"), "category", CATEGORIES)
        unit_price_cents = as_int(require_present(data, "unit_price_cents"), "unit_price_cents")
        if unit_price_cents < 1:
            raise bad_request("unit_price_cents must be at least 1")
        weight_oz = as_int(require_present(data, "weight_oz"), "weight_oz")
        if weight_oz < 1:
            raise bad_request("weight_oz must be at least 1")
        shipping_zone = as_enum(require_present(data, "shipping_zone"), "shipping_zone", SHIPPING_ZONES)
        subject_tags = []
        if "subject_tags" in data and data["subject_tags"] is not None:
            subject_tags = as_subject_list(data["subject_tags"], "subject_tags")
        fragile = optional_bool(data, "fragile")
        max_quantity = optional_int(data, "max_quantity_per_project", minimum=1)
        user_id, role = actor()
        require_roles(role, ("PlatformAdmin", "Vendor"))
        vendor = _get_vendor(vendor_id)
        if role == "Vendor" and user_id != vendor_id:
            raise forbidden("A vendor may only manage its own catalog")
        if vendor["status"] != "ACTIVE":
            raise invalid_state("A suspended vendor cannot add catalog items")
        if any(
            ci["vendor_id"] == vendor_id and ci["sku"] == sku
            for ci in store.catalog_items.values()
        ):
            raise bad_request("sku must be unique within the vendor")
        rec = store.base_record()
        rec.update({
            "vendor_id": vendor_id,
            "sku": sku,
            "name": name,
            "category": category,
            "subject_tags": subject_tags,
            "unit_price_cents": unit_price_cents,
            "weight_oz": weight_oz,
            "shipping_zone": shipping_zone,
            "fragile": fragile if fragile is not None else False,
            "max_quantity_per_project": max_quantity,
            "status": "ACTIVE",
        })
        store.catalog_items[rec["id"]] = rec
        return ok(catalog_item_json(rec), 201)

    @app.route("/giving/vendors/<vendor_id>/catalog-items", methods=["GET"])
    def list_catalog_items(vendor_id):
        _, role = actor()
        require_roles(role, LIST_ROLES)
        _get_vendor(vendor_id)
        category = request.args.get("category")
        status = request.args.get("status")
        rows = [ci for ci in store.catalog_items.values() if ci["vendor_id"] == vendor_id]
        if category is not None:
            rows = [ci for ci in rows if ci["category"] == category]
        if status is not None:
            rows = [ci for ci in rows if ci["status"] == status]
        rows.sort(key=lambda ci: (ci["created_at"], ci["_seq"]))
        limit, offset = pagination_args()
        page, meta = page_payload([catalog_item_json(ci) for ci in rows], limit, offset)
        return ok(page, 200, pagination=meta)

    @app.route("/giving/vendors/<vendor_id>/catalog-items/<item_id>", methods=["PATCH"])
    def patch_catalog_item(vendor_id, item_id):
        data = json_body()
        unit_price_cents = None
        if "unit_price_cents" in data and data["unit_price_cents"] is not None:
            unit_price_cents = as_int(data["unit_price_cents"], "unit_price_cents")
            if unit_price_cents < 1:
                raise bad_request("unit_price_cents must be at least 1")
        new_status = None
        if "status" in data and data["status"] is not None:
            new_status = as_enum(data["status"], "status", ("ACTIVE", "DISCONTINUED"))
        user_id, role = actor()
        require_roles(role, ("PlatformAdmin", "Vendor"))
        _get_vendor(vendor_id)
        item = store.catalog_items.get(item_id)
        if item is None or item["vendor_id"] != vendor_id:
            raise not_found("Catalog item not found")
        if role == "Vendor" and user_id != vendor_id:
            raise forbidden("A vendor may only edit its own catalog items")
        changed = False
        if new_status is not None and new_status != item["status"]:
            # Status moves only one way: ACTIVE -> DISCONTINUED.
            if item["status"] == "DISCONTINUED":
                raise invalid_state("A DISCONTINUED item cannot return to ACTIVE")
            item["status"] = new_status
            changed = True
        if unit_price_cents is not None and unit_price_cents != item["unit_price_cents"]:
            item["unit_price_cents"] = unit_price_cents
            changed = True
        if changed:
            store.touch(item)
        return ok(catalog_item_json(item), 200)
