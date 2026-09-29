"""Body / query shape validation (PRD 2.10 item 4 -> ERR_INVALID_REQUEST)."""

import re

from flask import request

from errors import ApiError
from store import db, parse_date, parse_instant

MONTH_DAY_RE = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")


def bad():
    raise ApiError("ERR_INVALID_REQUEST")


def body():
    """Return the JSON body as a dict.  A non-object body is a shape violation."""
    if not request.data:
        payload = None
    else:
        payload = request.get_json(silent=True)
        if payload is None:
            bad()
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad()
    return payload


def present(payload, name):
    return name in payload and payload[name] is not None


def take_string(payload, name, required=True, min_len=None, max_len=None, default=None):
    if not present(payload, name):
        if required:
            bad()
        return default
    value = payload[name]
    if not isinstance(value, str):
        bad()
    if min_len is not None and len(value) < min_len:
        bad()
    if max_len is not None and len(value) > max_len:
        bad()
    return value


def take_int(payload, name, required=True, minimum=None, maximum=None, default=None):
    if not present(payload, name):
        if required:
            bad()
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad()
    if minimum is not None and value < minimum:
        bad()
    if maximum is not None and value > maximum:
        bad()
    return value


def take_enum(payload, name, values, required=True, default=None):
    if not present(payload, name):
        if required:
            bad()
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in values:
        bad()
    return value


def take_date(payload, name, required=True, default=None):
    """Returns the raw YYYY-MM-DD string once it parses as a real calendar date."""
    if not present(payload, name):
        if required:
            bad()
        return default
    value = payload[name]
    if not isinstance(value, str) or parse_date(value) is None:
        bad()
    return value


def take_month_day(payload, name, required=True, default=None):
    if not present(payload, name):
        if required:
            bad()
        return default
    value = payload[name]
    if not isinstance(value, str) or not MONTH_DAY_RE.match(value):
        bad()
    return value


def take_instant(payload, name, required=True, default=None):
    if not present(payload, name):
        if required:
            bad()
        return default
    value = payload[name]
    moment = parse_instant(value) if isinstance(value, str) else None
    if moment is None:
        bad()
    return moment


def take_id(payload, name, required=True, default=None):
    if not present(payload, name):
        if required:
            bad()
        return default
    value = payload[name]
    if not isinstance(value, str) or value.strip() == "":
        bad()
    return value


# ---------------------------------------------------------------------------
# query-string filters
# ---------------------------------------------------------------------------
def query_enum(name, values):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in values:
        bad()
    return raw


def query_id(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw.strip() == "":
        bad()
    return raw


# ---------------------------------------------------------------------------
# existence lookups (priorities 6 and 7)
# ---------------------------------------------------------------------------
def lookup(table, key, error_id):
    row = table.get(key)
    if row is None:
        raise ApiError(error_id)
    return row


def find_tier(tier_id):
    return lookup(db.membership_tiers, tier_id, "ERR_TIER_NOT_FOUND")


def find_resort(resort_id):
    return lookup(db.resorts, resort_id, "ERR_RESORT_NOT_FOUND")


def find_band(band_id):
    return lookup(db.season_bands, band_id, "ERR_SEASON_BAND_NOT_FOUND")


def find_member(member_id):
    return lookup(db.members, member_id, "ERR_MEMBER_NOT_FOUND")


def find_deposit(deposit_id):
    return lookup(db.deposits, deposit_id, "ERR_DEPOSIT_NOT_FOUND")


def find_request(request_id):
    return lookup(db.exchange_requests, request_id, "ERR_EXCHANGE_REQUEST_NOT_FOUND")


def find_confirmation(confirmation_id):
    return lookup(db.confirmations, confirmation_id, "ERR_CONFIRMATION_NOT_FOUND")


def find_offer(offer_id):
    return lookup(db.getaway_offers, offer_id, "ERR_GETAWAY_OFFER_NOT_FOUND")


def find_dispute(dispute_id):
    return lookup(db.disputes, dispute_id, "ERR_DISPUTE_NOT_FOUND")


def find_run(run_id):
    return lookup(db.matching_runs, run_id, "ERR_MATCHING_RUN_NOT_FOUND")


def find_review(review_id):
    return lookup(db.resort_quality_reviews, review_id, "ERR_QUALITY_REVIEW_NOT_FOUND")


def find_entry(entry_id):
    return lookup(db.ledger_entries, entry_id, "ERR_LEDGER_ENTRY_NOT_FOUND")
