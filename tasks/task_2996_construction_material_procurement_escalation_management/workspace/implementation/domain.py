"""Cross-entity helpers: lookups, cascades and the reference-resolution ladder."""

from decimal import Decimal

import calc
from errors import ApiError
from store import ordered, store
from util import month_key

INDEX_CODES = (
    "PPI_STEEL_MILL",
    "PPI_COPPER_WIRE",
    "PPI_LUMBER",
    "PPI_CEMENT",
    "PPI_SWITCHGEAR",
)
PACKAGE_STATUSES = ("IDENTIFIED", "SOURCING", "BOUGHT_OUT", "SOURCING_STALLED", "CLOSED")
QUOTE_STATUSES = ("OPEN", "EXPIRED", "SUPERSEDED", "CONVERTED")
AGREEMENT_STATUSES = ("DRAFT", "PROPOSED", "COUNTERED", "EXECUTED", "LAPSED")
COMMITMENT_STATUSES = ("PENDING", "COMMITTED", "CLOSED", "CANCELLED", "VOIDED")
POSTURES = (
    "SCHEDULED",
    "RELEASED_FOR_FAB",
    "FABRICATING",
    "STORED_OFFSITE",
    "STORAGE_NONCOMPLIANT",
    "DELIVERED",
)
ARRANGEMENT_STATUSES = ("DRAFT", "ACTIVE", "SUSPENDED", "RELEASED")
DOC_TYPES = ("BAILMENT_AGREEMENT", "INSURANCE_CERTIFICATE", "LIEN_WAIVER", "INVENTORY_TAG_PHOTO")
DRIVERS = ("VALUE_ENGINEERING", "DISRUPTION_CONTINGENCY", "AVAILABILITY")
SUBSTITUTION_STATUSES = (
    "SUBMITTED",
    "APPROVED",
    "APPROVED_AS_NOTED",
    "REJECTED",
    "REVISION_REQUESTED",
    "RESCINDED",
)
CHANGE_ORDER_STATUSES = ("PREPARED", "SUBMITTED", "OWNER_APPROVED", "OWNER_REJECTED")
EVENT_TYPES = ("TARIFF_IMPOSED", "PLANT_SHUTDOWN", "PORT_CONGESTION", "FORCE_MAJEURE")
SUPPLIER_STATUSES = ("ACTIVE", "SUSPENDED")
EXPOSURE_BANDS = ("LOW", "ELEVATED", "HIGH")
RFF_BANDS = ("ON_TRACK", "AT_RISK", "CRITICAL")


# ---------------------------------------------------------------------------
# id resolution (PRD 2.8)
# ---------------------------------------------------------------------------
def get_project(row_id):
    row = store.projects.get(row_id)
    if row is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND")
    return row


def get_package(row_id):
    row = store.packages.get(row_id)
    if row is None:
        raise ApiError("ERR_PACKAGE_NOT_FOUND")
    return row


def get_supplier(row_id):
    row = store.suppliers.get(row_id)
    if row is None:
        raise ApiError("ERR_SUPPLIER_NOT_FOUND")
    return row


def get_quote(row_id):
    row = store.quotes.get(row_id)
    if row is None:
        raise ApiError("ERR_QUOTE_NOT_FOUND")
    return row


def get_agreement(row_id):
    row = store.agreements.get(row_id)
    if row is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND")
    return row


def get_commitment(row_id):
    row = store.commitments.get(row_id)
    if row is None:
        raise ApiError("ERR_COMMITMENT_NOT_FOUND")
    return row


def get_arrangement(row_id):
    row = store.arrangements.get(row_id)
    if row is None:
        raise ApiError("ERR_RECORD_NOT_FOUND")
    return row


def get_document(row_id):
    row = store.documents.get(row_id)
    if row is None:
        raise ApiError("ERR_RECORD_NOT_FOUND")
    return row


def get_substitution(row_id):
    row = store.substitutions.get(row_id)
    if row is None:
        raise ApiError("ERR_RECORD_NOT_FOUND")
    return row


def get_change_order(row_id):
    row = store.change_orders.get(row_id)
    if row is None:
        raise ApiError("ERR_RECORD_NOT_FOUND")
    return row


def get_disruption(row_id):
    row = store.disruptions.get(row_id)
    if row is None:
        raise ApiError("ERR_RECORD_NOT_FOUND")
    return row


# ---------------------------------------------------------------------------
# navigation
# ---------------------------------------------------------------------------
def project_of_package(pkg):
    return store.projects[pkg["project_id"]]


def package_of_commitment(commitment):
    return store.packages[commitment["material_package_id"]]


def project_of_commitment(commitment):
    return project_of_package(package_of_commitment(commitment))


def supplier_of_commitment(commitment):
    return store.suppliers[store.quotes[commitment["quote_id"]]["supplier_id"]]


def commitment_of_arrangement(arrangement):
    return store.commitments[arrangement["purchase_commitment_id"]]


def arrangements_of_commitment(commitment_id):
    return ordered(
        [
            a
            for a in store.arrangements.values()
            if a["purchase_commitment_id"] == commitment_id
        ]
    )


def live_commitment_on_package(package_id, exclude_id=None):
    for row in ordered(list(store.commitments.values())):
        if row["material_package_id"] != package_id:
            continue
        if exclude_id is not None and row["id"] == exclude_id:
            continue
        if row["commitment_status"] in ("PENDING", "COMMITTED"):
            return row
    return None


def bump_project_version(project):
    store.touch(project)


def release_package_from_bought_out(pkg):
    """Package leaves BOUGHT_OUT for SOURCING or SOURCING_STALLED per open quotes."""
    if pkg["status"] != "BOUGHT_OUT":
        return
    if calc.package_open_quote_count(pkg["id"]) >= 1:
        pkg["status"] = "SOURCING"
    else:
        pkg["status"] = "SOURCING_STALLED"
    store.touch(pkg)


# ---------------------------------------------------------------------------
# storage arrangement compound status (PRD 3.7)
# ---------------------------------------------------------------------------
def refresh_arrangement_status(arrangement):
    """Recompute the compound status after a document write. Returns True on change."""
    if arrangement["status"] == "RELEASED":
        return False
    _count, doc_status = calc.documentation_completeness(arrangement)
    before = arrangement["status"]
    if doc_status == "COMPLETE":
        arrangement["status"] = "ACTIVE"
    elif before == "ACTIVE":
        arrangement["status"] = "SUSPENDED"
    if arrangement["status"] != before:
        store.touch(arrangement)
        return True
    return False


def active_documented_arrangement(commitment_id):
    """An arrangement that is ACTIVE, documentation-COMPLETE and already occupied."""
    for arrangement in arrangements_of_commitment(commitment_id):
        if arrangement["status"] != "ACTIVE":
            continue
        if store.clock < arrangement["stored_from"]:
            continue
        _count, doc_status = calc.documentation_completeness(arrangement)
        if doc_status == "COMPLETE":
            return arrangement
    return None


# ---------------------------------------------------------------------------
# escalation recognition (PRD 3.6)
# ---------------------------------------------------------------------------
def recognise_escalation(commitment, variant):
    """Compute (amount, period) for a posture transition. Raises when no reading."""
    agreement_id = commitment["escalation_agreement_id"]
    if agreement_id is None:
        return Decimal("0.00"), None
    agreement = store.agreements[agreement_id]
    period = month_key(store.clock)
    if variant == "PROVISIONAL":
        reading = calc.reading_lookback(agreement["index_code"], period)
    else:
        reading = calc.reading_exact(agreement["index_code"], period)
    if reading is None:
        raise ApiError("ERR_INDEX_READING_MISSING")
    if agreement["baseline_index_value"] is None:
        return Decimal("0.00"), reading["period"]
    amount = calc.escalation_amount(
        commitment["committed_base_cost"], agreement, reading["value"]
    )
    return amount, reading["period"]


# ---------------------------------------------------------------------------
# list filtering
# ---------------------------------------------------------------------------
def string_filter(args, key):
    value = args.get(key)
    if value is None or value == "":
        return None
    return value


def bool_filter(args, key):
    value = args.get(key)
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return "__none__"


def matches(row, field, expected):
    if expected is None:
        return True
    return row.get(field) == expected
