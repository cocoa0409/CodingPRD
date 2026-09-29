"""In-memory data store.  Every collection starts empty on every boot; nothing
is ever seeded, preloaded or read from disk."""

from common import clock_now, fmt_instant, new_id
from errors import ApiError

brands = {}
owners = {}
existing_units = {}
applications = {}
claims = {}
agreements = {}
pips = {}
pip_items = {}
inspections = {}
transfer_requests = {}

_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_row(kind):
    """Mint the four server-managed properties every resource family carries."""
    stamp = fmt_instant(clock_now())
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_kind": kind,
        "_seq": next_seq(),
    }


def touch(row):
    """A mutation: refresh updated_at from the logical clock, advance version."""
    if row is None:
        return None
    row["updated_at"] = fmt_instant(clock_now())
    row["version"] = row["version"] + 1
    return row


def ordered(collection, predicate=None):
    rows = [r for r in collection.values() if predicate is None or predicate(r)]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


# ---------------------------------------------------------------------------
# Path / foreign-key resolution.  Each family answers with its own 404.
# ---------------------------------------------------------------------------


def _fetch(collection, identifier, error_id):
    if not isinstance(identifier, str):
        raise ApiError(error_id)
    row = collection.get(identifier)
    if row is None:
        raise ApiError(error_id)
    return row


def get_brand(identifier):
    return _fetch(brands, identifier, "ERR_BRAND_NOT_FOUND")


def get_owner(identifier):
    return _fetch(owners, identifier, "ERR_OWNER_NOT_FOUND")


def get_unit(identifier):
    return _fetch(existing_units, identifier, "ERR_EXISTING_UNIT_NOT_FOUND")


def get_application(identifier):
    return _fetch(applications, identifier, "ERR_APPLICATION_NOT_FOUND")


def get_claim(identifier):
    return _fetch(claims, identifier, "ERR_CLAIM_NOT_FOUND")


def get_agreement(identifier):
    return _fetch(agreements, identifier, "ERR_AGREEMENT_NOT_FOUND")


def get_pip(identifier):
    return _fetch(pips, identifier, "ERR_PIP_NOT_FOUND")


def get_pip_item(identifier):
    return _fetch(pip_items, identifier, "ERR_PIP_ITEM_NOT_FOUND")


def get_inspection(identifier):
    return _fetch(inspections, identifier, "ERR_INSPECTION_NOT_FOUND")


def get_transfer_request(identifier):
    return _fetch(transfer_requests, identifier, "ERR_TRANSFER_REQUEST_NOT_FOUND")


# ---------------------------------------------------------------------------
# Graph walks used by ownership checks and by derived figures
# ---------------------------------------------------------------------------


def application_of_agreement(agreement):
    return applications.get(agreement["application_id"])


def owner_id_of_agreement(agreement):
    application = application_of_agreement(agreement)
    return application["owner_id"] if application else None


def pip_of_agreement(agreement):
    rows = ordered(pips, lambda p: p["agreement_id"] == agreement["id"])
    return rows[0] if rows else None


def items_of_pip(pip):
    return ordered(pip_items, lambda i: i["pip_id"] == pip["id"])


def agreement_of_pip(pip):
    return agreements.get(pip["agreement_id"])


def pip_of_item(item):
    return pips.get(item["pip_id"])
