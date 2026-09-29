"""In-memory data store.  Nothing is seeded: every row is created through the
declared API surface, and a fresh process starts completely empty."""

import itertools
import threading
import uuid

from envelope import clock_now

_lock = threading.RLock()
_seq = itertools.count(1)

# Collections, keyed by id.
program_tiers = {}
device_categories = {}
security_criteria = {}
manufacturers = {}
products = {}
assessments = {}
criterion_responses = {}
test_labs = {}
test_engagements = {}
label_grants = {}
registry_entries = {}
retailers = {}
display_authorizations = {}
enforcement_cases = {}
recognition_surveys = {}

ALL_COLLECTIONS = (
    program_tiers,
    device_categories,
    security_criteria,
    manufacturers,
    products,
    assessments,
    criterion_responses,
    test_labs,
    test_engagements,
    label_grants,
    registry_entries,
    retailers,
    display_authorizations,
    enforcement_cases,
    recognition_surveys,
)


def lock():
    return _lock


def new_id():
    return str(uuid.uuid4())


def base_row(with_common=True):
    """Common resource properties (PRD 2.5)."""
    now = clock_now()
    row = {"id": new_id(), "created_at": now, "_seq": next(_seq)}
    if with_common:
        row["updated_at"] = now
        row["version"] = 1
    return row


def touch(row):
    """Recomputation of a derived field counts as a mutation (PRD 2.5)."""
    row["updated_at"] = clock_now()
    row["version"] = row.get("version", 1) + 1
    return row


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])


def sort_created_id(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["id"]))


def find_unique(collection, field, value):
    for row in collection.values():
        if row.get(field) == value:
            return row
    return None


# ---- typed lookups --------------------------------------------------------
def responses_of(assessment_id):
    return by_seq([r for r in criterion_responses.values() if r["assessment_id"] == assessment_id])


def engagements_of_assessment(assessment_id):
    return by_seq([e for e in test_engagements.values() if e["assessment_id"] == assessment_id])


def engagements_of_lab(lab_id):
    return by_seq([e for e in test_engagements.values() if e["test_lab_id"] == lab_id])


def assessments_of_product(product_id):
    return by_seq([a for a in assessments.values() if a["product_id"] == product_id])


def grants_of_product(product_id):
    return by_seq([g for g in label_grants.values() if g["product_id"] == product_id])


def registry_entry_of_grant(grant_id):
    for entry in registry_entries.values():
        if entry["label_grant_id"] == grant_id:
            return entry
    return None


def authorizations_of_grant(grant_id):
    return by_seq([a for a in display_authorizations.values() if a["label_grant_id"] == grant_id])


def authorizations_of_retailer(retailer_id):
    return by_seq([a for a in display_authorizations.values() if a["retailer_id"] == retailer_id])


def cases_of_manufacturer(manufacturer_id):
    return by_seq(
        [c for c in enforcement_cases.values() if c["subject_manufacturer_id"] == manufacturer_id]
    )


def products_of_manufacturer(manufacturer_id):
    return by_seq([p for p in products.values() if p["manufacturer_id"] == manufacturer_id])


def grant_by_code(code):
    for grant in label_grants.values():
        if grant["scannable_code"] == code:
            return grant
    return None


def criterion_by_code(code):
    return find_unique(security_criteria, "criterion_code", code)


# ---- chained context lookups ---------------------------------------------
def category_of_product(product):
    return device_categories.get(product["device_category_id"])


def tier_of_product(product):
    category = category_of_product(product)
    if category is None:
        return None
    return program_tiers.get(category["program_tier_id"])


def product_of_assessment(assessment):
    return products.get(assessment["product_id"])


def tier_of_assessment(assessment):
    product = product_of_assessment(assessment)
    if product is None:
        return None
    return tier_of_product(product)


def product_of_grant(grant):
    return products.get(grant["product_id"])


def manufacturer_of_grant(grant):
    product = product_of_grant(grant)
    if product is None:
        return None
    return manufacturers.get(product["manufacturer_id"])
