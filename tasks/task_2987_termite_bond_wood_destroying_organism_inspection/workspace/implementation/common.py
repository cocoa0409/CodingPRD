"""Shared lookups and the reusable rungs of the rejection ladder (PRD 2.6)."""

from errors import ApiError, not_found
from clock import clock
from store import db

# --- stage 4 / stage 8: existence -----------------------------------------

_TABLES = {
    "Property": "properties",
    "Inspector": "inspectors",
    "Inspection": "inspections",
    "TreatmentPlan": "plans",
    "Bond": "bonds",
    "BondRenewal": "renewals",
    "WdoReport": "reports",
    "BaitStation": "stations",
    "DamageClaim": "claims",
}


def resolve(kind, ident):
    """Path or body reference resolution; a miss raises the entity's 404."""
    table = getattr(db, _TABLES[kind])
    row = table.get(ident) if isinstance(ident, str) else None
    if row is None:
        raise not_found(kind, ident)
    return row


def get_property(ident):
    return resolve("Property", ident)


def get_inspector(ident):
    return resolve("Inspector", ident)


def get_inspection(ident):
    return resolve("Inspection", ident)


def get_plan(ident):
    return resolve("TreatmentPlan", ident)


def get_bond(ident):
    return resolve("Bond", ident)


def get_renewal(ident):
    return resolve("BondRenewal", ident)


def get_report(ident):
    return resolve("WdoReport", ident)


def get_station(ident):
    return resolve("BaitStation", ident)


def get_claim(ident):
    return resolve("DamageClaim", ident)


# --- stages 11 and 12: licence discipline ---------------------------------

def require_license_active(inspector):
    if inspector["status"] != "ACTIVE":
        raise ApiError("ERR_LICENSE_NOT_ACTIVE", 409,
                       "licence %s is %s" % (inspector["license_number"], inspector["status"]))


def require_license_unexpired(inspector):
    if inspector["license_expires_on"] < clock.today():
        raise ApiError("ERR_LICENSE_EXPIRED", 409,
                       "licence %s expired on %s" % (inspector["license_number"],
                                                     inspector["license_expires_on"]))


def require_category(inspector, category):
    if category not in inspector["license_categories"]:
        raise ApiError("ERR_CATEGORY_NOT_LICENSED", 422,
                       "licence does not carry the %s endorsement" % category)


# --- stage 20: referential state of consumed rows -------------------------

def require_graphed(inspection):
    if inspection["status"] != "GRAPHED":
        raise ApiError("ERR_INSPECTION_NOT_GRAPHED", 409,
                       "inspection %s is %s, not GRAPHED" % (inspection["id"],
                                                             inspection["status"]))


def require_purpose(inspection, purpose):
    if inspection["purpose"] != purpose:
        raise ApiError("ERR_INSPECTION_PURPOSE_MISMATCH", 422,
                       "inspection purpose %s is not %s" % (inspection["purpose"], purpose))


def require_same_property(property_id, inspection):
    if inspection["property_id"] != property_id:
        raise ApiError("ERR_PROPERTY_MISMATCH", 422,
                       "inspection %s belongs to another property" % inspection["id"])


# --- filtering ------------------------------------------------------------

def apply_filters(rows, spec):
    """spec maps a row field to the requested exact-match value (None = no filter)."""
    out = rows
    for field, wanted in spec.items():
        if wanted is None:
            continue
        out = [r for r in out if _matches(r.get(field), wanted)]
    return out


def _matches(actual, wanted):
    if isinstance(wanted, bool):
        return actual is wanted
    return actual == wanted
