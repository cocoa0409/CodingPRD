"""Existence resolution and the shared gates of the rejection order."""
import db
from errors import ApiError
from services.derive import CHARGE_ACCEPTING

_NOT_FOUND = {
    "properties": "ERR_PROPERTY_NOT_FOUND",
    "outlets": "ERR_OUTLET_NOT_FOUND",
    "periods": "ERR_PERIOD_NOT_FOUND",
    "business_dates": "ERR_BUSINESS_DATE_NOT_FOUND",
    "folios": "ERR_FOLIO_NOT_FOUND",
    "postings": "ERR_POSTING_NOT_FOUND",
    "tickets": "ERR_TICKET_NOT_FOUND",
    "batches": "ERR_BATCH_NOT_FOUND",
    "ledger_accounts": "ERR_LEDGER_ACCOUNT_NOT_FOUND",
    "allowances": "ERR_ALLOWANCE_NOT_FOUND",
    "documents": "ERR_DOCUMENT_NOT_FOUND",
    "card_auths": "ERR_AUTHORIZATION_NOT_FOUND",
    "reports": "ERR_REPORT_NOT_FOUND",
}


def fetch(collection, row_id):
    row = getattr(db.store, collection).get(row_id) if row_id else None
    if row is None:
        raise ApiError(_NOT_FOUND[collection], "%s does not exist." % row_id)
    return row


def get_property(row_id):
    return fetch("properties", row_id)


def get_outlet(row_id):
    return fetch("outlets", row_id)


def get_period(row_id):
    return fetch("periods", row_id)


def get_date(row_id):
    return fetch("business_dates", row_id)


def get_folio(row_id):
    return fetch("folios", row_id)


def get_posting(row_id):
    return fetch("postings", row_id)


def get_ticket(row_id):
    return fetch("tickets", row_id)


def get_batch(row_id):
    return fetch("batches", row_id)


def get_ledger(row_id):
    return fetch("ledger_accounts", row_id)


def get_allowance(row_id):
    return fetch("allowances", row_id)


def get_document(row_id):
    return fetch("documents", row_id)


def get_auth(row_id):
    return fetch("card_auths", row_id)


def get_report(row_id):
    return fetch("reports", row_id)


def property_of_folio(folio):
    return db.store.properties.get(folio["property_id"])


def require_not_archived(date_row):
    """An archived day refuses every write, outranking every other complaint."""
    if date_row["status"] == "ARCHIVED":
        raise ApiError(
            "ERR_BUSINESS_DATE_ARCHIVED",
            "The business date is archived and immutable.",
        )


def require_charges_open(date_row):
    """The charge-seal gate: only OPEN, ROOM_POSTING and REOPENED take charges."""
    if date_row["status"] not in CHARGE_ACCEPTING:
        raise ApiError(
            "ERR_CHARGES_ALREADY_SEALED",
            "The business date no longer accepts charges.",
        )


REVERSAL_ACCEPTING = (
    "OPEN", "ROOM_POSTING", "CHARGES_SEALED", "SETTLEMENT_REVIEW",
    "BALANCED", "REOPENED",
)


def require_reversal_window(date_row):
    """The reversal carve-out: only a CLOSED day refuses a correction."""
    if date_row["status"] not in REVERSAL_ACCEPTING:
        raise ApiError(
            "ERR_CHARGES_ALREADY_SEALED",
            "A closed business date no longer accepts corrections.",
        )


def documents_of_folio(folio_id, doc_type):
    return [d for d in db.all_of("documents")
            if d["folio_id"] == folio_id and d["doc_type"] == doc_type]


def has_active_document(folio_id, doc_type, on_date):
    """An ACTIVE paperwork row whose closed interval covers the given day."""
    for doc in documents_of_folio(folio_id, doc_type):
        if doc["status"] != "ACTIVE":
            continue
        if doc["valid_from_date"] <= on_date <= doc["valid_to_date"]:
            return doc
    return None


def has_active_allowance_document(allowance_id):
    for doc in db.all_of("documents"):
        if doc["allowance_id"] != allowance_id:
            continue
        if doc["doc_type"] == "ALLOWANCE_APPROVAL" and doc["status"] == "ACTIVE":
            return doc
    return None
