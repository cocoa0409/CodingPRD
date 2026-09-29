"""Products, spec-change notices and assessment creation (PRD 3.2, 3.3)."""

from flask import Blueprint

import cascades
import lookups
import serialize
import store
import validation as v
from auth import (
    CONFORMITY_REVIEWER,
    MANUFACTURER,
    PROGRAM_ADMINISTRATOR,
    TEST_LAB_OPERATOR,
    caller,
    own,
)
from envelope import created, ok
from validation import ensure
from store import base_row, touch

bp = Blueprint("products", __name__)

CONFORMANCE_CURRENCIES = ("CURRENT", "STALE")
ELIGIBILITY_STATUSES = ("ELIGIBLE", "EXCLUDED")
PRODUCT_READERS = (
    PROGRAM_ADMINISTRATOR,
    CONFORMITY_REVIEWER,
    MANUFACTURER,
    TEST_LAB_OPERATOR,
)


@bp.post("/labeling/products")
def create_product():
    caller(MANUFACTURER)
    body = v.raw_body()

    # Body foreign keys resolve left to right, ahead of the shape rung.
    lookups.resolve_fk(body, "manufacturer_id", lookups.need_manufacturer)
    lookups.resolve_fk(body, "device_category_id", lookups.need_category)

    manufacturer_id = v.field_str(body, "manufacturer_id")
    device_category_id = v.field_str(body, "device_category_id")
    model_name = v.field_str(body, "model_name", max_len=200)
    sku = v.field_str(body, "sku", max_len=100)
    firmware_version = v.field_str(body, "firmware_version", max_len=100)
    declared_support_period_end = v.field_instant(body, "declared_support_period_end")
    update_policy_disclosed = v.field_bool(body, "update_policy_disclosed")
    retail_units_shipped = v.field_int(body, "retail_units_shipped", minimum=0)

    manufacturer = lookups.need_manufacturer(manufacturer_id)
    category = lookups.need_category(device_category_id)
    lookups.unique_or_reject(store.products, "sku", sku)

    row = base_row()
    row.update(
        {
            "manufacturer_id": manufacturer["id"],
            "device_category_id": category["id"],
            "model_name": model_name,
            "sku": sku,
            "firmware_version": firmware_version,
            "declared_support_period_end": declared_support_period_end,
            "update_policy_disclosed": update_policy_disclosed,
            "retail_units_shipped": retail_units_shipped,
            "spec_revision": 1,
            "conformance_currency": "CURRENT",
            # eligibility mirrors the referenced device category.
            "eligibility_status": category["eligibility_status"],
            "last_change_summary": None,
        }
    )
    store.products[row["id"]] = row
    return created(serialize.product(row))


@bp.get("/labeling/products/<identifier>")
def read_product(identifier):
    caller(*PRODUCT_READERS)
    return ok(serialize.product(lookups.need_product(identifier)))


@bp.get("/labeling/products")
def list_products():
    caller(*PRODUCT_READERS)
    manufacturer_id = v.query_str("manufacturer_id")
    device_category_id = v.query_str("device_category_id")
    conformance_currency = v.query_enum("conformance_currency", CONFORMANCE_CURRENCIES)
    eligibility_status = v.query_enum("eligibility_status", ELIGIBILITY_STATUSES)

    rows = list(store.products.values())
    if manufacturer_id is not None:
        rows = [row for row in rows if row["manufacturer_id"] == manufacturer_id]
    if device_category_id is not None:
        rows = [row for row in rows if row["device_category_id"] == device_category_id]
    if conformance_currency is not None:
        rows = [row for row in rows if row["conformance_currency"] == conformance_currency]
    if eligibility_status is not None:
        rows = [row for row in rows if row["eligibility_status"] == eligibility_status]
    return lookups.listing(store.sort_created_id(rows), serialize.product)


def _owned_product(identifier, actor):
    """Ownership (rung 3) needs the row; an unresolvable id falls through to
    the existence rung's not-found code (rung 5)."""
    product = store.products.get(identifier)
    if product is not None:
        own(product["manufacturer_id"] == actor.user_id)
    return lookups.need_product(identifier)


@bp.post("/labeling/products/<identifier>/spec-changes")
def create_spec_change(identifier):
    actor = caller(MANUFACTURER)
    product = _owned_product(identifier, actor)
    body = v.raw_body()

    expected_product_version = v.field_int(body, "expected_product_version")
    change_summary = v.field_str(body, "change_summary", max_len=2000)
    firmware_version = v.field_str(body, "firmware_version", required=False, max_len=100)
    declared_support_period_end = v.field_instant(
        body, "declared_support_period_end", required=False
    )
    update_policy_disclosed = v.field_bool(body, "update_policy_disclosed", required=False)

    ensure(
        expected_product_version == product["version"],
        "ERR_STALE_PRODUCT_VERSION",
        "The product has been modified since it was last read.",
    )

    product["spec_revision"] = product["spec_revision"] + 1
    if firmware_version is not None:
        product["firmware_version"] = firmware_version
    if declared_support_period_end is not None:
        product["declared_support_period_end"] = declared_support_period_end
    if update_policy_disclosed is not None:
        product["update_policy_disclosed"] = update_policy_disclosed
    product["last_change_summary"] = change_summary
    product["conformance_currency"] = "STALE"
    touch(product)

    # Three-link cascade: grants -> displays -> retailer tiers.
    cascades.suspend_product_grants(product, "PRODUCT_SPEC_CHANGED", True)

    return created(serialize.product(product))


@bp.post("/labeling/products/<identifier>/assessments")
def create_assessment(identifier):
    actor = caller(MANUFACTURER)
    product = _owned_product(identifier, actor)
    body = v.raw_body()

    expected_product_version = v.field_int(body, "expected_product_version")
    ensure(
        expected_product_version == product["version"],
        "ERR_STALE_PRODUCT_VERSION",
        "The product has been modified since it was last read.",
    )
    ensure(
        product["eligibility_status"] == "ELIGIBLE",
        "ERR_DEVICE_CLASS_EXCLUDED",
        "The product's device category is outside the program scope.",
    )

    tier = store.tier_of_product(product)
    row = base_row()
    row.update(
        {
            "product_id": product["id"],
            "route": tier["required_route"],
            "assessed_spec_revision": product["spec_revision"],
            "status": "DRAFT",
            "deficiency_round": 0,
            "provisional_area_scores": None,
            "provisional_overall_score": None,
            "verified_area_scores": None,
            "verified_overall_score": None,
            "decided_overall_score": None,
            "decided_min_area_score": None,
            "gate_applied": False,
            "grade": None,
            "submitted_at": None,
            "decided_at": None,
            "decided_by_user_id": None,
            "last_deficiency_by_user_id": None,
            "reviewer_note": None,
            "superseded_by_assessment_id": None,
        }
    )
    store.assessments[row["id"]] = row

    # Opening a new assessment supersedes any earlier one still in flight.
    cascades.supersede_open_assessments(product, row["id"])
    touch(product)

    return created(serialize.assessment(row))
