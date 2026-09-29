"""Safekeeping and nonuse extension filings (PRD 3.9)."""

from flask import Blueprint

import calc
import domain
from authz import (BROKER, PLATFORM_ADMIN, REGULATOR, SELLER, authenticate,
                   filing_or_404, license_or_404, require_seller)
from envelope import apply_filters, created, ok, ok_list, pagination_args, paginate
from errors import ApiError
from store import (add_months, bump, db, make_record, now, public, public_list,
                   sorted_by_created, whole_day_diff)
from validation import F, json_body, validate

bp = Blueprint("safekeeping", __name__)

FILING_TYPES = ("INITIAL", "EXTENSION")
FILING_TERMINAL = ("GRANTED", "DENIED")
DECISIONS = ("GRANT", "DENY")


@bp.route("/safekeeping-filings", methods=["POST"])
def create_filing():
    user_id, role = authenticate((BROKER, SELLER))
    data = validate(json_body(), [
        F("license_id", "string"),
        F("filing_type", "enum", values=FILING_TYPES),
        F("requested_months", "integer", minimum=1, maximum=24),
        F("expected_license_version", "integer"),
    ])
    lic = license_or_404(data["license_id"])
    require_seller(user_id, role, lic["owner_seller_id"])
    if lic["version"] != data["expected_license_version"]:
        raise ApiError("ERR_STALE_LICENSE_VERSION",
                       "The license has moved since it was last observed.")
    if lic["status"] == "IN_ESCROW":
        raise ApiError("ERR_INVALID_LICENSE_STATE",
                       "A license in escrow may not be petitioned for safekeeping.")
    if lic["status"] == "TRANSFERRED":
        raise ApiError("ERR_ALREADY_TERMINAL", "The license is already in a terminal state.")
    if data["filing_type"] == "EXTENSION" and lic["safekeeping_expires_at"] is None:
        raise ApiError("ERR_INVALID_LICENSE_STATE",
                       "There is no safekeeping window on this license to extend.")
    if lic["safekeeping_filing_pending"]:
        raise ApiError("ERR_SAFEKEEPING_FILING_PENDING",
                       "A safekeeping filing on this license is already awaiting decision.")
    if (data["filing_type"] == "EXTENSION"
            and lic["safekeeping_extensions_count"] >= calc.MAX_EXTENSIONS):
        raise ApiError("ERR_SAFEKEEPING_EXTENSION_LIMIT",
                       "The safekeeping extension limit has been reached.")
    if data["filing_type"] == "INITIAL":
        elapsed = whole_day_diff(now().date(), lic["last_active_date"])
        if elapsed < calc.NONUSE_GRACE_DAYS:
            raise ApiError("ERR_NONUSE_PERIOD_NOT_REACHED",
                           "The statutory nonuse period has not been reached.")
        extension_index = 0
        granted_months = min(data["requested_months"], calc.SAFEKEEPING_INITIAL_MAX_MONTHS)
        effective_from = now()
    else:
        extension_index = lic["safekeeping_extensions_count"] + 1
        granted_months = min(data["requested_months"], calc.EXTENSION_MAX_MONTHS)
        effective_from = lic["safekeeping_expires_at"]
    filing = make_record({
        "license_id": lic["id"],
        "filing_type": data["filing_type"],
        "requested_months": data["requested_months"],
        "extension_index": extension_index,
        "granted_months": granted_months,
        "effective_from": effective_from,
        "expires_at": add_months(effective_from, granted_months),
        "fee_cents": calc.safekeeping_fee(extension_index),
        "status": "PENDING",
        "decided_at": None,
    })
    db.filings[filing["id"]] = filing
    lic["safekeeping_filing_pending"] = True
    bump(lic)
    return created(public(filing))


@bp.route("/safekeeping-filings/<filing_id>", methods=["GET"])
def get_filing(filing_id):
    authenticate((PLATFORM_ADMIN, BROKER, SELLER, REGULATOR))
    return ok(public(filing_or_404(filing_id)))


@bp.route("/safekeeping-filings", methods=["GET"])
def list_filings():
    authenticate((PLATFORM_ADMIN, BROKER, SELLER, REGULATOR))
    limit, offset = pagination_args()
    rows = apply_filters(db.filings.values(), {
        "license_id": "license_id",
        "filing_type": "filing_type",
        "status": "status",
    })
    rows = sorted_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.route("/safekeeping-filings/<filing_id>/decide", methods=["POST"])
def decide_filing(filing_id):
    authenticate((REGULATOR,))
    data = validate(json_body(), [F("decision", "enum", values=DECISIONS)])
    filing = filing_or_404(filing_id)
    if filing["status"] != "PENDING" and filing["status"] not in FILING_TERMINAL:
        raise ApiError("ERR_INVALID_LICENSE_STATE", "The filing is not awaiting decision.")
    if filing["status"] in FILING_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", "The filing is already in a terminal state.")
    lic = license_or_404(filing["license_id"])
    if data["decision"] == "GRANT":
        if filing["filing_type"] == "INITIAL" and lic["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_LICENSE_STATE",
                           "An initial safekeeping grant requires an ACTIVE license.")
        if filing["filing_type"] == "EXTENSION":
            if lic["status"] != "SAFEKEEPING":
                raise ApiError("ERR_INVALID_LICENSE_STATE",
                               "An extension grant requires a license in SAFEKEEPING.")
            if lic["safekeeping_extensions_count"] >= calc.MAX_EXTENSIONS:
                raise ApiError("ERR_SAFEKEEPING_EXTENSION_LIMIT",
                               "The safekeeping extension limit has been reached.")
        filing["status"] = "GRANTED"
        filing["decided_at"] = now()
        bump(filing)
        lic["safekeeping_expires_at"] = filing["expires_at"]
        lic["safekeeping_extensions_count"] = filing["extension_index"]
        lic["status"] = "SAFEKEEPING"
        lic["safekeeping_filing_pending"] = False
        bump(lic)
        domain.recompute_county_of(lic)
        return ok(public(filing))
    filing["status"] = "DENIED"
    filing["decided_at"] = now()
    bump(filing)
    lic["safekeeping_filing_pending"] = False
    bump(lic)
    return ok(public(filing))
