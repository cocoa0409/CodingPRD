"""Excise returns and off-site event permits."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import derive
import envelope
import helpers
import store
import validation
from errors import ApiError
from validation import ALL_ROLES, authenticate

bp = Blueprint("excise", __name__)

TAPROOM_BASES = ("METERED_POUR", "WHOLE_KEG_REMOVAL")
REPORT_STATES = ("DRAFT", "FILED", "SUPERSEDED")
PERMIT_TYPES = ("FESTIVAL", "OFF_SITE_TASTING", "FARMERS_MARKET")
PERMIT_STATES = ("DRAFT", "SUBMITTED", "INFO_REQUESTED", "APPROVED", "DENIED")
DECISIONS = ("APPROVED", "DENIED", "INFO_REQUESTED")


# ---------------------------------------------------------------------------
# taxable barrel computation
# ---------------------------------------------------------------------------

def _taproom_bbl(basis, period_start, period_end):
    if basis == "METERED_POUR":
        total_oz = Decimal("0")
        for pour in derive.rows("pours"):
            poured_at = pour.get("poured_at_utc")
            if poured_at is None:
                continue
            if period_start <= poured_at < period_end:
                total_oz += Decimal(pour.get("volume_oz") or 0)
        return calc.bbl(total_oz / calc.OZ_PER_BBL)
    total = Decimal("0")
    for keg in derive.rows("kegs"):
        tapped_at = keg.get("tapped_at_utc")
        if tapped_at is None or keg.get("deployment_channel") != "TAPROOM":
            continue
        if period_start <= tapped_at < period_end:
            total += Decimal(keg.get("size_bbl") or 0)
    return calc.bbl(total)


def _distribution_bbl(period_start, period_end):
    total = Decimal("0")
    for order in derive.rows("orders"):
        if order.get("state") != "SHIPPED":
            continue
        shipped_at = order.get("shipped_at_utc")
        if shipped_at is None:
            continue
        if period_start <= shipped_at < period_end:
            total += Decimal(order.get("allocated_bbl") or 0)
    return calc.bbl(total)


def _ytd_before(period_start, exclude_ids):
    brewery = store.DB["brewery"]
    total = Decimal("0")
    if brewery is not None:
        total += Decimal(brewery.get("carry_in_taproom_bbl") or 0)
        total += Decimal(brewery.get("carry_in_distribution_bbl") or 0)
    for report in derive.rows("reports"):
        if report["id"] in exclude_ids or report.get("state") != "FILED":
            continue
        if report["period_end_utc"] <= period_start:
            total += Decimal(report.get("total_taxable_bbl") or 0)
    return calc.bbl(total)


def _recompute(report):
    period_start = report["period_start_utc"]
    period_end = report["period_end_utc"]
    taproom = _taproom_bbl(report["taproom_basis"], period_start, period_end)
    distribution = _distribution_bbl(period_start, period_end)
    ytd_before = _ytd_before(period_start, {report["id"]})
    taxes = calc.excise_tax(taproom, distribution, ytd_before)
    report["taproom_bbl"] = taproom
    report["distribution_bbl"] = distribution
    report["total_taxable_bbl"] = taxes["total_bbl"]
    report["ytd_bbl_before_period"] = ytd_before
    report["federal_tax_cents"] = taxes["federal_tax_cents"]
    report["state_tax_cents"] = taxes["state_tax_cents"]
    report["total_tax_due_cents"] = taxes["total_tax_due_cents"]


# ---------------------------------------------------------------------------
# excise reports
# ---------------------------------------------------------------------------

@bp.get("/excise-reports")
def list_reports():
    authenticate(ALL_ROLES)
    amends_report_id = validation.query_string("amends_report_id")
    state = validation.query_enum("state", REPORT_STATES)
    taproom_basis = validation.query_enum("taproom_basis", TAPROOM_BASES)

    def predicate(row):
        return (helpers.matches(row, "amends_report_id", amends_report_id)
                and helpers.matches(row, "state", state)
                and helpers.matches(row, "taproom_basis", taproom_basis))

    rows, limit, offset, total = helpers.listing("reports", derive.serialize_report, predicate)
    return envelope.list_response(rows, limit, offset, total)


@bp.get("/excise-reports/<report_id>")
def read_report(report_id):
    authenticate(ALL_ROLES)
    return envelope.object_response(derive.serialize_report(helpers.find("reports", report_id)))


@bp.post("/excise-reports")
def create_report():
    user_id, _role = authenticate(["BreweryAdmin"])
    payload = validation.body()
    period_start = validation.field_datetime(payload, "period_start_utc")
    period_end = validation.field_datetime(payload, "period_end_utc")
    validation.require_interval("period_start_utc", period_start,
                                "period_end_utc", period_end)
    taproom_basis = validation.field_enum(payload, "taproom_basis", TAPROOM_BASES)
    amends_report_id = validation.field_id(payload, "amends_report_id", required=False)
    if amends_report_id is not None:
        helpers.find("reports", amends_report_id)

    row = store.new_row({
        "period_start_utc": period_start,
        "period_end_utc": period_end,
        "taproom_basis": taproom_basis,
        "amends_report_id": amends_report_id,
        "taproom_bbl": calc.bbl(0),
        "distribution_bbl": calc.bbl(0),
        "total_taxable_bbl": calc.bbl(0),
        "ytd_bbl_before_period": calc.bbl(0),
        "federal_tax_cents": 0,
        "state_tax_cents": 0,
        "total_tax_due_cents": 0,
        "state": "DRAFT",
        "prepared_by_user_id": user_id,
        "filed_by_user_id": None,
        "filed_at_utc": None,
    })
    _recompute(row)
    helpers.insert("reports", row)
    return envelope.object_response(derive.serialize_report(row), 201)


@bp.post("/excise-reports/<report_id>/file")
def file_report(report_id):
    user_id, _role = authenticate(["ComplianceOfficer"])
    validation.body()
    report = helpers.find("reports", report_id)
    if report.get("state") != "DRAFT":
        raise ApiError("ERR_REPORT_TRANSITION_INVALID")
    if helpers.now() < report["period_end_utc"]:
        raise ApiError("ERR_PERIOD_NOT_CLOSED")
    if user_id == report.get("prepared_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    target = None
    if report.get("amends_report_id") is not None:
        target = store.DB["reports"].get(report["amends_report_id"])
        if target is None or target.get("state") != "FILED":
            raise ApiError("ERR_AMENDMENT_TARGET_NOT_FILED")
    else:
        for other in derive.rows("reports"):
            if other["id"] == report["id"] or other.get("state") != "FILED":
                continue
            if (other["period_start_utc"] == report["period_start_utc"]
                    and other["period_end_utc"] == report["period_end_utc"]):
                raise ApiError("ERR_PERIOD_ALREADY_FILED")

    seen = set()
    _recompute(report)
    report["state"] = "FILED"
    report["filed_by_user_id"] = user_id
    report["filed_at_utc"] = helpers.now()
    cascades.touch_once(report, seen)
    if target is not None:
        target["state"] = "SUPERSEDED"
        cascades.touch_once(target, seen)
    return envelope.object_response(derive.serialize_report(report))


# ---------------------------------------------------------------------------
# event permits
# ---------------------------------------------------------------------------

@bp.get("/event-permits")
def list_permits():
    authenticate(ALL_ROLES)
    featured_beer_id = validation.query_string("featured_beer_id")
    venue_state_code = validation.query_string("venue_state_code")
    state = validation.query_enum("state", PERMIT_STATES)
    permit_type = validation.query_enum("permit_type", PERMIT_TYPES)

    def predicate(row):
        return (helpers.matches(row, "featured_beer_id", featured_beer_id)
                and helpers.matches(row, "venue_state_code", venue_state_code)
                and helpers.matches(row, "state", state)
                and helpers.matches(row, "permit_type", permit_type))

    rows, limit, offset, total = helpers.listing("permits", derive.serialize_permit, predicate)
    return envelope.list_response(rows, limit, offset, total)


@bp.get("/event-permits/<permit_id>")
def read_permit(permit_id):
    authenticate(ALL_ROLES)
    return envelope.object_response(derive.serialize_permit(helpers.find("permits", permit_id)))


@bp.post("/event-permits")
def create_permit():
    authenticate(["ComplianceOfficer"])
    payload = validation.body()
    featured_beer_id = validation.field_id(payload, "featured_beer_id")
    event_name = validation.field_string(payload, "event_name", 1, 120)
    permit_type = validation.field_enum(payload, "permit_type", PERMIT_TYPES)
    venue_state_code = validation.field_state_code(payload, "venue_state_code")
    event_start = validation.field_datetime(payload, "event_start_utc")
    event_end = validation.field_datetime(payload, "event_end_utc")
    validation.require_interval("event_start_utc", event_start, "event_end_utc", event_end)
    requested_bbl = validation.field_number(payload, "requested_bbl", 2, exclusive_minimum=0)

    helpers.find("beers", featured_beer_id)
    licensed = any(licence.get("state_code") == venue_state_code
                   for licence in derive.rows("licenses"))
    if not licensed:
        raise ApiError("ERR_TERRITORY_NOT_LICENSED")

    row = store.new_row({
        "featured_beer_id": featured_beer_id,
        "event_name": event_name,
        "permit_type": permit_type,
        "venue_state_code": venue_state_code,
        "event_start_utc": event_start,
        "event_end_utc": event_end,
        "requested_bbl": calc.bbl2(requested_bbl),
        "state": "DRAFT",
        "info_request_note": None,
        "submission_count": 0,
        "decided_at_utc": None,
        "denial_reason": None,
    })
    helpers.insert("permits", row)
    return envelope.object_response(derive.serialize_permit(row), 201)


@bp.post("/event-permits/<permit_id>/submit")
def submit_permit(permit_id):
    authenticate(["ComplianceOfficer"])
    validation.body()
    permit = helpers.find("permits", permit_id)
    if permit.get("state") not in ("DRAFT", "INFO_REQUESTED"):
        raise ApiError("ERR_PERMIT_TRANSITION_INVALID")
    helpers.require_notice_active()
    beer = helpers.find("beers", permit["featured_beer_id"])
    helpers.beer_formula_guard(beer)

    booked = Decimal("0")
    for other in derive.rows("permits"):
        if other["id"] == permit["id"]:
            continue
        if other.get("venue_state_code") != permit["venue_state_code"]:
            continue
        if other.get("state") not in ("SUBMITTED", "APPROVED"):
            continue
        booked += Decimal(other.get("requested_bbl") or 0)
    projected = calc.bbl2(booked + Decimal(permit["requested_bbl"]))
    if projected > calc.EVENT_ANNUAL_BBL_CAP_PER_STATE:
        raise ApiError("ERR_EVENT_BARREL_CAP_EXCEEDED")

    permit["state"] = "SUBMITTED"
    permit["submission_count"] = (permit.get("submission_count") or 0) + 1
    permit["info_request_note"] = None
    store.touch(permit)
    return envelope.object_response(derive.serialize_permit(permit))


@bp.post("/event-permits/<permit_id>/decision")
def decide_permit(permit_id):
    authenticate(["StateRegulator"])
    payload = validation.body()
    decision = validation.field_enum(payload, "decision", DECISIONS)
    note = validation.field_string(payload, "note", 1, None, required=False)
    permit = helpers.find("permits", permit_id)
    if permit.get("state") != "SUBMITTED":
        raise ApiError("ERR_PERMIT_TRANSITION_INVALID")

    if decision == "APPROVED":
        overlapping = 0
        for other in derive.rows("permits"):
            if other["id"] == permit["id"] or other.get("state") != "APPROVED":
                continue
            if other.get("venue_state_code") != permit["venue_state_code"]:
                continue
            if (other["event_start_utc"] <= permit["event_end_utc"]
                    and permit["event_start_utc"] <= other["event_end_utc"]):
                overlapping += 1
        if overlapping >= calc.MAX_CONCURRENT_OFFSITE_PERMITS_PER_STATE:
            raise ApiError("ERR_OFFSITE_EVENT_CAPACITY_EXCEEDED")
        permit["state"] = "APPROVED"
        permit["decided_at_utc"] = helpers.now()
    elif decision == "DENIED":
        permit["state"] = "DENIED"
        permit["denial_reason"] = note
        permit["decided_at_utc"] = helpers.now()
    else:
        permit["state"] = "INFO_REQUESTED"
        permit["info_request_note"] = note
    store.touch(permit)
    return envelope.object_response(derive.serialize_permit(permit))
