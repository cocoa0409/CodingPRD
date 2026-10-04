"""Catalog domain: items, attributes, cross-references, curation reviews,
suppliers / availability reports, and stock rows."""

from common import (invalid_request, optional_str, require, require_bool,
                    require_int, require_str, round_half_up_int)
from calculations import supplier_selector
from db import created_key
from errors import ApiError, not_found


def get_item(store, item_id):
    record = store.catalog_items.get(item_id)
    if record is None:
        raise not_found("ERR_ITEM_NOT_FOUND", "No catalog item exists for id '%s'." % item_id)
    return record


def get_supplier(store, supplier_id):
    record = store.suppliers.get(supplier_id)
    if record is None:
        raise not_found("ERR_SUPPLIER_NOT_FOUND" if False else "ERR_ITEM_NOT_FOUND",
                        "No supplier exists for id '%s'." % supplier_id)
    return record


# ------------------------------------------------------------------- items

def create_item(store, body):
    sku = require_str(body, "sku")
    if any(i.get("sku") == sku for i in store.catalog_items.values()):
        raise invalid_request("Field 'sku' must be unique across the catalog.")

    description = require_str(body, "description")
    material_spec = require_str(body, "material_spec")
    long_tail = require_bool(body, "long_tail")
    unit_price_cents = require_int(body, "unit_price_cents", 1)

    unit_weight_kg = require(body, "unit_weight_kg")
    if isinstance(unit_weight_kg, bool) or not isinstance(unit_weight_kg, (int, float)):
        raise invalid_request("Field 'unit_weight_kg' must be a number.")
    if float(unit_weight_kg) <= 0:
        raise invalid_request("Field 'unit_weight_kg' must be strictly positive.")

    curation_bundle_size = require_int(body, "curation_bundle_size", 0)
    dimension = require(body, "curated_dimension_json")
    if not isinstance(dimension, dict):
        raise invalid_request("Field 'curated_dimension_json' must be an object.")
    if "drawing_revision" not in dimension:
        raise invalid_request("Field 'curated_dimension_json' must carry 'drawing_revision'.")

    record = {
        "sku": sku,
        "description": description,
        "material_spec": material_spec,
        "long_tail": long_tail,
        "catalog_status": "ACTIVE",
        "unit_price_cents": unit_price_cents,
        "unit_weight_kg": unit_weight_kg,
        "curated_dimension_json": dict(dimension),
        "curation_bundle_size": curation_bundle_size,
        "curation_review_state": "UNREVIEWED",
        "curation_last_reviewed_by": None,
    }
    store.stamp(record)
    store.catalog_items[record["id"]] = record
    return record


def item_availability(store, item, dc_id=None):
    """live_availability_at_dc for one DC, or the aggregate across all DCs."""
    from calculations import aggregate_order_availability, live_availability_at_dc
    if dc_id:
        return live_availability_at_dc(item["id"], dc_id, store)
    return aggregate_order_availability(item["id"], store)


def item_matches(store, item, args):
    q = args.get("q")
    if q:
        needle = q.strip().lower()
        haystack = " ".join(str(item.get(f, "") or "") for f in
                            ("sku", "description", "material_spec"))
        if needle not in haystack.lower():
            return False
    material_spec = args.get("material_spec")
    if material_spec and item.get("material_spec") != material_spec:
        return False
    catalog_status = args.get("catalog_status")
    if catalog_status and item.get("catalog_status") != catalog_status:
        return False
    long_tail = args.get("long_tail")
    if long_tail is not None:
        if item.get("long_tail") is not (long_tail.strip().lower() in ("true", "1", "yes")):
            return False
    region = args.get("region")
    if region:
        dc_ids = [d["id"] for d in store.distribution_centers.values() if d.get("region") == region]
        if not any(_has_row(store, item["id"], dcid) for dcid in dc_ids):
            return False
    dc_id = args.get("dc_id")
    if dc_id and not _has_row(store, item["id"], dc_id):
        return False
    supplier_id = args.get("supplier_id")
    if supplier_id:
        rows = [r for r in store.supplier_availability_reports.values()
                if r.get("supplier_id") == supplier_id and r.get("item_id") == item["id"]]
        if not rows:
            return False
    return True


def _has_row(store, item_id, dc_id):
    return any(r.get("item_id") == item_id and r.get("dc_id") == dc_id
               for r in store.stock_rows.values())


# -------------------------------------------------------------- attributes

def create_attribute(store, item, body):
    attribute_name = require_str(body, "attribute_name")
    attribute_value = require_str(body, "attribute_value")
    unit_of_measure = require_str(body, "unit_of_measure")
    for row in store.item_attributes.values():
        if row.get("item_id") != item["id"]:
            continue
        if row.get("attribute_name") == attribute_name:
            raise invalid_request("Attribute name '%s' already exists on this item." % attribute_name)
        if row.get("attribute_value") == attribute_value:
            raise invalid_request("Attribute value '%s' already exists on this item." % attribute_value)
    record = {
        "item_id": item["id"],
        "attribute_name": attribute_name,
        "attribute_value": attribute_value,
        "unit_of_measure": unit_of_measure,
    }
    store.stamp(record, common=False)
    store.item_attributes[record["id"]] = record
    return record


def item_attributes(store, item_id):
    rows = [r for r in store.item_attributes.values() if r.get("item_id") == item_id]
    return sorted(rows, key=created_key)


# --------------------------------------------------------- cross-reference

def create_cross_reference(store, item, body):
    record = {
        "item_id": item["id"],
        "referenced_manufacturer": require_str(body, "referenced_manufacturer"),
        "referenced_part_number": require_str(body, "referenced_part_number"),
        "compatibility_note": require_str(body, "compatibility_note"),
    }
    store.stamp(record, common=False)
    store.item_cross_references[record["id"]] = record
    return record


def item_cross_references(store, item_id):
    rows = [r for r in store.item_cross_references.values() if r.get("item_id") == item_id]
    return sorted(rows, key=created_key)


# --------------------------------------------------------- curation review

def create_curation_review(store, curator_id, item_ids):
    if not isinstance(item_ids, list) or not item_ids:
        raise invalid_request("Field 'item_ids' must be a non-empty array.")
    items = [get_item(store, item_id) for item_id in item_ids]

    # Preconditions are checked for every item before any approval is committed.
    for item in items:
        if not item_attributes(store, item["id"]):
            raise ApiError(
                "ERR_CURATION_ATTRIBUTES_MISSING",
                "Item '%s' carries no standardized attribute rows." % item["sku"], 409)
        revision = (item.get("curated_dimension_json") or {}).get("drawing_revision")
        if revision is None:
            raise invalid_request(
                "Item '%s' has no drawing_revision in its dimensional payload." % item["sku"])

    review = {
        "curator_id": curator_id,
        "review_status": "OPEN",
        "bundle_level_revision": 0,
        "approved_count": 0,
        "revision_round_baseline": 0,
    }
    store.stamp(review)
    store.curation_reviews[review["id"]] = review

    for item in items:
        member = {
            "review_id": review["id"],
            "item_id": item["id"],
            "item_level_revision": 0,
            "item_attribute_counter": len(item_attributes(store, item["id"])),
        }
        store.stamp(member, common=False)
        store.curation_review_items[member["id"]] = member
        item["curation_review_state"] = "APPROVED"
        item["curation_last_reviewed_by"] = curator_id
        store.touch(item)

    review["approved_count"] = len(items)
    return review


def revoke_curation_review(store, review):
    if review.get("review_status") == "REVOKED":
        raise ApiError("ERR_INVALID_STATE",
                       "Curation review '%s' is already REVOKED." % review["id"], 409)
    review["review_status"] = "REVOKED"
    store.touch(review)
    for member in store.curation_review_items.values():
        if member.get("review_id") != review["id"]:
            continue
        item = store.catalog_items.get(member.get("item_id"))
        if item is not None:
            item["curation_review_state"] = "UNREVIEWED"
            store.touch(item)
    return review


# ---------------------------------------------------------------- suppliers

def create_supplier(store, body):
    from svc_dc import get_dc
    supplier_name = require_str(body, "supplier_name")
    home_dc_id = require_str(body, "home_dc_id")
    get_dc(store, home_dc_id)
    record = {
        "supplier_name": supplier_name,
        "home_dc_id": home_dc_id,
        "primary_attribute_name": require_str(body, "primary_attribute_name"),
        "primary_attribute_value": require_str(body, "primary_attribute_value"),
        "long_tail_authorized": require_bool(body, "long_tail_authorized"),
        "min_stock_commitment_units": require_int(body, "min_stock_commitment_units", 0),
        "commitment_breach_count": 0,
        "performance_rating_units": 100,
    }
    store.stamp(record)
    store.suppliers[record["id"]] = record
    return record


def supplier_matches(supplier, args):
    long_tail_authorized = args.get("long_tail_authorized")
    if long_tail_authorized is not None:
        wanted = long_tail_authorized.strip().lower() in ("true", "1", "yes")
        if supplier.get("long_tail_authorized") is not wanted:
            return False
    for field in ("home_dc_id", "primary_attribute_name", "primary_attribute_value"):
        value = args.get(field)
        if value and supplier.get(field) != value:
            return False
    return True


def file_availability_report(store, supplier, body):
    item_id = require_str(body, "item_id")
    get_item(store, item_id)
    reported_units = require_int(body, "reported_available_units", 0)

    winner = supplier_selector(reported_units, store)
    if winner is None:
        raise ApiError("ERR_SUPPLIER_CANDIDATE_EMPTY",
                       "No supplier survives the availability selector for this report.", 409)

    record = {
        "supplier_id": supplier["id"],
        "item_id": item_id,
        "reported_available_units": reported_units,
    }
    store.stamp(record, common=False)
    store.supplier_availability_reports[record["id"]] = record

    if reported_units < (supplier.get("min_stock_commitment_units", 0) or 0):
        supplier["commitment_breach_count"] = supplier.get("commitment_breach_count", 0) + 1
        supplier["performance_rating_units"] = 100 - 10 * supplier["commitment_breach_count"]
        store.touch(supplier)
    return winner


# --------------------------------------------------------------- stock rows

def create_stock(store, body):
    from svc_dc import get_dc
    item_id = require_str(body, "item_id")
    get_item(store, item_id)
    dc_id = require_str(body, "dc_id")
    get_dc(store, dc_id)
    record = {
        "item_id": item_id,
        "dc_id": dc_id,
        "account_id": require_str(body, "account_id"),
        "on_hand_units": require_int(body, "on_hand_units", 0),
        "reserved_units": 0,
        "daily_demand_units": require_int(body, "daily_demand_units", 0),
        "inbound_daily_units": require_int(body, "inbound_daily_units", 0),
        "positioning_flag": None,
    }
    store.stamp(record)
    record["available_units"] = record["on_hand_units"]
    store.stock_rows[record["id"]] = record
    return record


def get_stock(store, stock_id):
    record = store.stock_rows.get(stock_id)
    if record is None:
        raise not_found("ERR_INVALID_REQUEST", "No stock row exists for id '%s'." % stock_id)
    return record


def stock_matches(row, args):
    for field in ("item_id", "dc_id", "account_id"):
        value = args.get(field)
        if value and row.get(field) != value:
            return False
    return True


def available_units(row):
    return row.get("on_hand_units", 0) - row.get("reserved_units", 0)