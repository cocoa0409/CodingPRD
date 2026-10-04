"""Collection lookups, existence resolution and default list ordering.

Existence is validated strictly left to right (PRD §2.7): the first
identifier in a path that does not resolve terminates the request with
ERR_RESOURCE_NOT_FOUND and HTTP 404.
"""

from clock import parse_iso
from errors import fail
from store import store

COLLECTION_NAMES = (
    "manufacturers",
    "drugs",
    "pharmacies",
    "licenses",
    "prices",
    "patients",
    "prescribers",
    "prescriptions",
    "requests",
    "orders",
    "shipments",
    "claims",
    "comparisons",
    "substantiations",
)

# Singular labels used for the existence error message.
LABELS = {
    "manufacturers": "manufacturer",
    "drugs": "drug",
    "pharmacies": "pharmacy",
    "licenses": "pharmacy license",
    "prices": "manufacturer drug price",
    "patients": "patient",
    "prescribers": "prescriber",
    "prescriptions": "prescription",
    "requests": "prescription request",
    "orders": "order",
    "shipments": "shipment",
    "claims": "claim",
    "comparisons": "price comparison",
    "substantiations": "price substantiation",
}


def collection(name):
    return getattr(store, name)


def all_of(name):
    return list(collection(name).values())


def get(name, ident):
    return collection(name).get(ident)


def find(name, ident):
    """Resolve an identifier or refuse with ERR_RESOURCE_NOT_FOUND."""
    record = collection(name).get(ident)
    if record is None:
        fail("ERR_RESOURCE_NOT_FOUND", "No %s with id %s." % (LABELS[name], ident))
    return record


def exists(name, ident):
    return ident is not None and ident in collection(name)


def ordered_by_created(records):
    """Unless a specific ordering is stated, lists sort by created_at asc."""
    return sorted(
        records,
        key=lambda rec: (rec.get("created_at") or "", rec.get("id") or ""),
    )


def ordered_by_seq(records, seq_field):
    return sorted(
        records,
        key=lambda rec: (
            rec.get(seq_field, 0),
            rec.get("created_at") or "",
            rec.get("id") or "",
        ),
    )


def of_parent(name, field, parent_id):
    return [rec for rec in collection(name).values() if rec.get(field) == parent_id]


def license_pair(pharmacy_id, state_code):
    return [
        rec
        for rec in collection("licenses").values()
        if rec.get("pharmacy_id") == pharmacy_id and rec.get("state_code") == state_code
    ]


def active_license_for(pharmacy_id, state_code):
    for rec in collection("licenses").values():
        if (
            rec.get("pharmacy_id") == pharmacy_id
            and rec.get("state_code") == state_code
            and rec.get("status") == "ACTIVE"
        ):
            return rec
    return None


def price_rows_for_drug(drug_id):
    return [
        rec for rec in collection("prices").values() if rec.get("drug_id") == drug_id
    ]


def orders_for_drug(drug_id):
    out = []
    for order in collection("orders").values():
        prescription = get("prescriptions", order.get("prescription_id"))
        if prescription is not None and prescription.get("drug_id") == drug_id:
            out.append(order)
    return out


def orders_of_prescription(prescription_id):
    return of_parent("orders", "prescription_id", prescription_id)


def claims_of_prescription(prescription_id):
    return of_parent("claims", "prescription_id", prescription_id)


def shipments_of_order(order_id):
    return of_parent("shipments", "order_id", order_id)


def comparisons_of_order(order_id):
    return of_parent("comparisons", "order_id", order_id)


def substantiations_of_order(order_id):
    return of_parent("substantiations", "order_id", order_id)


def requests_of_prescription(prescription_id):
    return of_parent("requests", "prescription_id", prescription_id)


def created_instant(record):
    return parse_iso(record.get("created_at"))


def resolve_license_of_pharmacy(pharmacy_id, license_id):
    """Left-to-right resolution: pharmacy first, then licence (PRD §2.7)."""
    pharmacy = find("pharmacies", pharmacy_id)
    license_record = find("licenses", license_id)
    if license_record.get("pharmacy_id") != pharmacy.get("id"):
        fail(
            "ERR_RESOURCE_NOT_FOUND",
            "License %s does not belong to pharmacy %s." % (license_id, pharmacy_id),
        )
    return pharmacy, license_record


def resolve_comparison_of_order(order_id, comparison_id):
    order = find("orders", order_id)
    comparison = find("comparisons", comparison_id)
    if comparison.get("order_id") != order.get("id"):
        fail(
            "ERR_RESOURCE_NOT_FOUND",
            "Comparison %s does not belong to order %s." % (comparison_id, order_id),
        )
    return order, comparison