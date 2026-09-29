"""Franchise filings: notice, amendment and taking effect (PRD 3.4)."""

from flask import Blueprint, request

import calc
import cascade
import db
import derive
import enums
import response
import serializers
import validation as v
from errors import ApiError
from middleware import guard, require_manufacturer_owner

bp = Blueprint("filings", __name__)

READ_ROLES = ["BoardAdmin", "HearingClerk", "LicensingAnalyst", "Dealer", "Manufacturer"]

NOTICE_MINIMUM_DAYS = {"TERMINATION": 60, "RELOCATION": 60, "ADDITIONAL_POINT": 30}
MOVED_ON_PROTEST_STATES = ("HEARD", "SUSTAINED", "DENIED", "APPEALED", "FINAL")
AMENDMENT_WITHDRAWABLE_STATES = ("FILED", "SCHEDULED")
AMENDMENT_LIMIT = 2
PROTEST_WINDOW_DAYS = 30


def _find(record_id):
    record = db.get("franchise_filing", record_id)
    if record is None:
        raise ApiError("ERR_FILING_NOT_FOUND", "No such franchise filing")
    return record


def _owned(caller, record_id):
    record = db.get("franchise_filing", record_id)
    if record is not None:
        require_manufacturer_owner(caller, record["manufacturer_id"])
    return _find(record_id)


def _require_registered(manufacturer):
    if manufacturer is None or manufacturer["state_registration_status"] != "REGISTERED":
        raise ApiError("ERR_MANUFACTURER_REGISTRATION_LAPSED", "The franchisor's registration has lapsed")


def _check_notice_period(filing, proposed_effective_on, reference_date):
    minimum = NOTICE_MINIMUM_DAYS[filing["filing_type"]]
    if (proposed_effective_on - reference_date).days < minimum:
        raise ApiError(
            "ERR_NOTICE_PERIOD_TOO_SHORT",
            "A %s requires at least %d days of notice" % (filing["filing_type"], minimum),
        )


def _stamp_notice(filing, reference_date, proposed_effective_on):
    filing["proposed_effective_on"] = proposed_effective_on
    filing["notice_served_on"] = reference_date
    filing["notice_days_provided"] = (proposed_effective_on - reference_date).days
    filing["protest_window_ends_on"] = reference_date + calc._timedelta(PROTEST_WINDOW_DAYS)


@bp.post("/franchise-filings")
def create_filing():
    caller = guard(["Manufacturer"])
    peeked = v.peek_body()
    if isinstance(peeked.get("manufacturer_id"), str):
        require_manufacturer_owner(caller, peeked["manufacturer_id"])

    body = v.read_body()
    manufacturer_id = v.req_string(body, "manufacturer_id", 1, 100)
    filing_type = v.req_enum(body, "filing_type", enums.FILING_TYPES)
    proposed_effective_on = v.req_date(body, "proposed_effective_on")
    affected_dealer_id = v.opt_string(body, "affected_dealer_id", 1, 100)
    site_x_km = v.opt_decimal(body, "site_x_km", -500, 500, 2)
    site_y_km = v.opt_decimal(body, "site_y_km", -500, 500, 2)
    termination_cause_code = v.opt_string(body, "termination_cause_code", 1, 200)

    manufacturer = db.get("manufacturer", manufacturer_id)
    if manufacturer is None:
        raise ApiError("ERR_MANUFACTURER_NOT_FOUND", "No such franchisor")
    dealer = None
    if affected_dealer_id is not None:
        dealer = db.get("dealer", affected_dealer_id)
        if dealer is None:
            raise ApiError("ERR_DEALER_NOT_FOUND", "No such dealership")
        if dealer["line_make"] != manufacturer["line_make"]:
            raise ApiError("ERR_LINE_MAKE_MISMATCH", "The dealership does not carry the franchisor's line make")

    if filing_type in ("TERMINATION", "RELOCATION") and affected_dealer_id is None:
        raise ApiError("ERR_FILING_FIELDS_INCONSISTENT", "A %s must name affected_dealer_id" % filing_type)
    if filing_type in ("RELOCATION", "ADDITIONAL_POINT") and (site_x_km is None or site_y_km is None):
        raise ApiError("ERR_FILING_FIELDS_INCONSISTENT", "A %s must carry site_x_km and site_y_km" % filing_type)
    if filing_type == "ADDITIONAL_POINT" and affected_dealer_id is not None:
        raise ApiError("ERR_FILING_FIELDS_INCONSISTENT", "An ADDITIONAL_POINT must omit affected_dealer_id")
    if filing_type == "TERMINATION" and termination_cause_code is None:
        raise ApiError("ERR_FILING_FIELDS_INCONSISTENT", "A TERMINATION must cite termination_cause_code")
    if filing_type != "TERMINATION" and termination_cause_code is not None:
        raise ApiError(
            "ERR_FILING_FIELDS_INCONSISTENT",
            "termination_cause_code is present only for a TERMINATION",
        )

    record = db.insert("franchise_filing", {
        "manufacturer_id": manufacturer_id,
        "affected_dealer_id": affected_dealer_id,
        "filing_type": filing_type,
        "line_make": manufacturer["line_make"],
        "status": "DRAFT",
        "proposed_effective_on": proposed_effective_on,
        "site_x_km": site_x_km,
        "site_y_km": site_y_km,
        "termination_cause_code": termination_cause_code,
        "notice_served_on": None,
        "notice_days_provided": None,
        "protest_window_ends_on": None,
        "amendment_count": 0,
        "active_protest_count": 0,
    })
    derive.recompute_all()
    return response.object_response(serializers.franchise_filing(record), 201)


@bp.post("/franchise-filings/<record_id>/serve-notice")
def serve_notice(record_id):
    caller = guard(["Manufacturer"])
    filing = _owned(caller, record_id)
    v.read_body()
    if filing["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_FILING_STATE", "Only a DRAFT filing may be served")
    manufacturer = db.get("manufacturer", filing["manufacturer_id"])
    _require_registered(manufacturer)

    reference_date = db.today()
    _check_notice_period(filing, filing["proposed_effective_on"], reference_date)

    _stamp_notice(filing, reference_date, filing["proposed_effective_on"])
    filing["status"] = "NOTICE_SERVED"
    db.touch(filing)

    if filing["filing_type"] == "TERMINATION":
        dealer = db.get("dealer", filing["affected_dealer_id"])
        if dealer is not None and dealer["franchise_status"] == "FRANCHISED":
            dealer["franchise_status"] = "TERMINATION_PENDING"
            db.touch(dealer)

    derive.recompute_all()
    return response.object_response(serializers.franchise_filing(filing), 200)


@bp.post("/franchise-filings/<record_id>/amend")
def amend_filing(record_id):
    caller = guard(["Manufacturer"])
    filing = _owned(caller, record_id)
    body = v.read_body()
    proposed_effective_on = v.req_date(body, "proposed_effective_on")
    site_x_km = v.opt_decimal(body, "site_x_km", -500, 500, 2)
    site_y_km = v.opt_decimal(body, "site_y_km", -500, 500, 2)

    if filing["status"] not in ("NOTICE_SERVED", "PROTEST_PENDING"):
        raise ApiError("ERR_INVALID_FILING_STATE", "A filing in %s may not be amended" % filing["status"])
    was_protest_pending = filing["status"] == "PROTEST_PENDING"
    if was_protest_pending:
        for protest in derive.protests_for_filing(filing["id"]):
            if protest["status"] in MOVED_ON_PROTEST_STATES:
                raise ApiError("ERR_INVALID_FILING_STATE", "The protest record has moved beyond amendment")

    manufacturer = db.get("manufacturer", filing["manufacturer_id"])
    _require_registered(manufacturer)

    reference_date = db.today()
    _check_notice_period(filing, proposed_effective_on, reference_date)

    if filing["amendment_count"] >= AMENDMENT_LIMIT:
        raise ApiError("ERR_AMENDMENT_LIMIT_REACHED", "The amendment loop is bounded at two amendments")

    filing["amendment_count"] += 1
    _stamp_notice(filing, reference_date, proposed_effective_on)
    if site_x_km is not None:
        filing["site_x_km"] = site_x_km
    if site_y_km is not None:
        filing["site_y_km"] = site_y_km
    filing["status"] = "NOTICE_SERVED"
    db.touch(filing)

    if was_protest_pending:
        for protest in derive.protests_for_filing(filing["id"]):
            if protest["status"] in AMENDMENT_WITHDRAWABLE_STATES:
                protest["status"] = "WITHDRAWN"
                db.touch(protest)
                cascade.release_docket(protest)

    derive.recompute_all()
    return response.object_response(serializers.franchise_filing(filing), 200)


@bp.post("/franchise-filings/<record_id>/finalize")
def finalize_filing(record_id):
    guard(["BoardAdmin"])
    filing = _find(record_id)
    v.read_body()

    # PRD 3.4: a filing in DRAFT, EFFECTIVE or BARRED is refused here. A filing
    # still sitting in PROTEST_PENDING clears this gate on purpose and is turned
    # away later by the active-protest check (PRD 2.10).
    if filing["status"] in ("DRAFT", "EFFECTIVE", "BARRED"):
        raise ApiError("ERR_INVALID_FILING_STATE", "A filing in %s may not be finalised" % filing["status"])

    reference_date = db.today()
    window_ends_on = filing.get("protest_window_ends_on")
    if window_ends_on is not None and not (reference_date > window_ends_on):
        raise ApiError("ERR_PROTEST_WINDOW_OPEN", "The protest window has not closed yet")
    if reference_date < filing["proposed_effective_on"]:
        raise ApiError("ERR_EFFECTIVE_DATE_NOT_REACHED", "The proposed effective date has not arrived")
    if filing["active_protest_count"] != 0:
        raise ApiError("ERR_ACTIVE_PROTEST_BLOCKS_FINALIZE", "An active protest blocks finalisation")
    for protest in derive.protests_for_filing(filing["id"]):
        if protest["status"] == "APPEALED":
            raise ApiError("ERR_APPEAL_PENDING", "A pending court appeal freezes the filing")

    filing["status"] = "EFFECTIVE"
    db.touch(filing)

    if filing["filing_type"] == "TERMINATION":
        cascade.finalize_termination(filing)
    elif filing["filing_type"] == "RELOCATION":
        dealer = db.get("dealer", filing["affected_dealer_id"])
        if dealer is not None:
            dealer["site_x_km"] = filing["site_x_km"]
            dealer["site_y_km"] = filing["site_y_km"]
            db.touch(dealer)

    derive.recompute_all()
    return response.object_response(serializers.franchise_filing(filing), 200)


@bp.get("/franchise-filings/<record_id>")
def read_filing(record_id):
    guard(READ_ROLES)
    return response.object_response(serializers.franchise_filing(_find(record_id)), 200)


@bp.get("/franchise-filings")
def list_filings():
    guard(READ_ROLES)
    manufacturer_id = v.query_string("manufacturer_id")
    affected_dealer_id = v.query_string("affected_dealer_id")
    filing_type = v.query_enum("filing_type", enums.FILING_TYPES)
    status = v.query_enum("status", enums.FILING_STATUSES)
    limit, offset = response.read_pagination(request.args)
    rows = [
        row for row in db.ordered("franchise_filing")
        if (manufacturer_id is None or row["manufacturer_id"] == manufacturer_id)
        and (affected_dealer_id is None or row["affected_dealer_id"] == affected_dealer_id)
        and (filing_type is None or row["filing_type"] == filing_type)
        and (status is None or row["status"] == status)
    ]
    window, total = response.page(rows, limit, offset)
    return response.array_response(
        [serializers.franchise_filing(row) for row in window], limit, offset, len(rows)
    )
