"""Non-renewal notices, the logical clock and managed-risk letters
(PRD §2.4, §3.9)."""

from flask import Blueprint

import calc
import db
import reqs
from clock import add_days, days_between_exclusive_inclusive, fmt_dt, parse_dt
from errors import err
from middleware import authorize
from response import array, ok, paginate
from serialize import render, render_list
from services import core

bp = Blueprint("notices", __name__)

GROUNDS = ("CONCENTRATION_REVIEW", "MITIGATION_FAILURE", "APPRAISAL_LAPSE", "NONPAYMENT")
NOTICE_READERS = ("Underwriter", "ClaimsAdjuster", "PlatformAdmin", "ComplianceReporter",
                  "AgencyProducer", "RiskConsultant")
MANAGED_READERS = ("Underwriter", "RiskConsultant", "ComplianceReporter", "PlatformAdmin",
                   "AgencyProducer", "ClaimsAdjuster")


def common_fields():
    now = fmt_dt(db.now())
    return {"id": db.new_id(), "created_at": now, "updated_at": now, "version": 1}


# --------------------------------------------------------------------------
# the logical clock
# --------------------------------------------------------------------------
@bp.route("/hnw/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authorize(("PlatformAdmin",))
    data = reqs.body()
    instant = parse_dt(reqs.require(data, "current_utc"))
    if instant is None:
        raise err("ERR_INVALID_REQUEST", "current_utc must be an ISO 8601 instant.")
    db.CLOCK.set(instant)
    core.on_clock_change()
    return ok({"current_utc": fmt_dt(db.now())})


# --------------------------------------------------------------------------
# non-renewal notices
# --------------------------------------------------------------------------
@bp.route("/hnw/enrollments/<enrollment_id>/non-renewal-notices", methods=["POST"])
def create_notice(enrollment_id):
    authorize(("Underwriter",))
    enrollment = core.get(db.ENROLLMENTS, enrollment_id, "Enrollment")
    prop = core.get(db.PROPERTIES, enrollment["property_id"], "Property")
    data = reqs.body()
    effective_on = parse_dt(reqs.require(data, "effective_on"))
    if effective_on is None:
        raise err("ERR_INVALID_REQUEST", "effective_on must be an ISO 8601 instant.")
    zone = db.ZONES.get(enrollment["risk_zone_id"])
    zone_band = zone["concentration_band"] if zone else "NORMAL"
    if zone_band not in ("CRITICAL", "ELEVATED"):
        zone_band = "CAPITALIZED"
    ground = reqs.enum(data, "ground", GROUNDS)
    record = common_fields()
    # The window is measured at birth, exclusive of the filing date and
    # inclusive of the effective date (PRD §3.9).
    record.update({
        "enrollment_id": enrollment["id"],
        "property_id": prop["id"],
        "risk_zone_id": enrollment["risk_zone_id"],
        "ground": ground,
        "issued_on": None,
        "notice_period_days": days_between_exclusive_inclusive(db.now(), effective_on),
        "effective_on": effective_on,
        "window_anchor": fmt_dt(db.now()),
        "required_notice_days": _required_notice_days(zone_band),
        "delay_exempt": (ground == "CONCENTRATION_REVIEW" and zone_band == "CRITICAL"),
        "seal_at": None,
        "status": "PENDING",
    })
    db.NON_RENEWAL_NOTICES[record["id"]] = record
    return ok(render(record), status=201)


def _required_notice_days(zone_band):
    """Read the regulator's required period for the band (PRD §3.9)."""
    return {"CRITICAL": 90, "ELEVATED": 60, "CAPITALIZED": 45}[zone_band]


def _notice_filters(rows):
    status = reqs.query("status")
    ground = reqs.query("ground")
    if status:
        rows = [n for n in rows if n["status"] == status]
    if ground:
        rows = [n for n in rows if n["ground"] == ground]
    return rows


@bp.route("/hnw/enrollments/<enrollment_id>/non-renewal-notices", methods=["GET"])
def list_enrollment_notices(enrollment_id):
    authorize(("Underwriter", "ClaimsAdjuster", "PlatformAdmin", "ComplianceReporter"))
    core.get(db.ENROLLMENTS, enrollment_id, "Enrollment")
    limit, offset = reqs.pagination()
    rows = _notice_filters([n for n in db.NON_RENEWAL_NOTICES.values()
                            if n["enrollment_id"] == enrollment_id])
    rows = reqs.sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return array(render_list(page), meta)


@bp.route("/hnw/properties/<property_id>/non-renewal-notices", methods=["GET"])
def list_property_notices(property_id):
    authorize(("Underwriter", "ComplianceReporter", "PlatformAdmin"))
    core.get(db.PROPERTIES, property_id, "Property")
    limit, offset = reqs.pagination()
    rows = _notice_filters([n for n in db.NON_RENEWAL_NOTICES.values()
                            if n["property_id"] == property_id])
    rows = reqs.sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return array(render_list(page), meta)


@bp.route("/hnw/risk-zones/<zone_id>/non-renewal-notices", methods=["GET"])
def list_zone_notices(zone_id):
    authorize(("Underwriter", "ComplianceReporter", "PlatformAdmin"))
    core.get(db.ZONES, zone_id, "RiskZone")
    limit, offset = reqs.pagination()
    rows = _notice_filters([n for n in db.NON_RENEWAL_NOTICES.values()
                            if n["risk_zone_id"] == zone_id])
    rows = reqs.sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return array(render_list(page), meta)


@bp.route("/hnw/non-renewal-notices/<notice_id>/issue", methods=["POST"])
def issue_notice(notice_id):
    authorize(("Underwriter",))
    notice = core.get(db.NON_RENEWAL_NOTICES, notice_id, "NonRenewalNotice")
    if notice["status"] not in ("PENDING", "ISSUED"):
        raise err("ERR_INVALID_STATE",
                  "Only a PENDING or ISSUED notice may be issued.")
    enrollment = core.get(db.ENROLLMENTS, notice["enrollment_id"], "Enrollment")
    prop = core.get(db.PROPERTIES, notice["property_id"], "Property")
    zone = db.ZONES.get(notice["risk_zone_id"])
    band = zone["concentration_band"] if zone else "NORMAL"
    if band not in ("CRITICAL", "ELEVATED"):
        band = "CAPITALIZED"
    now = db.now()
    # The filing date is pinned when the window was opened and is not re-stamped.
    filing_at = parse_dt(notice.get("window_anchor")) or parse_dt(notice["issued_on"]) or now
    required = _required_notice_days(band)
    delay_exempt = (notice["ground"] == "CONCENTRATION_REVIEW" and band == "CRITICAL")
    notice["required_notice_days"] = required
    notice["delay_exempt"] = delay_exempt
    notice["seal_at"] = fmt_dt(add_days(filing_at, required))
    notice["notice_period_days"] = days_between_exclusive_inclusive(
        filing_at, notice["effective_on"])
    period = notice["notice_period_days"]

    # Priority 10: the 60-day minimum policy age, measured from the bind to the
    # notice's own filing date.  A defective period outranks the ground test.
    if enrollment["bound_at"] is None:
        raise err("ERR_NOTICE_PERIOD_INSUFFICIENT",
                  "The parent enrollment is not bound.")
    if period <= 0:
        raise err("ERR_NOTICE_PERIOD_INSUFFICIENT",
                  "The notice period must be strictly positive.")
    if not delay_exempt and period <= required:
        raise err("ERR_NOTICE_PERIOD_INSUFFICIENT",
                  "The notice period is not strictly longer than the required period.")
    age_days = days_between_exclusive_inclusive(enrollment["bound_at"], filing_at)
    if age_days < calc.MIN_POLICY_AGE_DAYS:
        raise err("ERR_NOTICE_PERIOD_INSUFFICIENT",
                  "The policy was bound fewer than 60 days before the file date.")
    # Priority 15: the ground must be actionable against the property's state.
    if notice["ground"] == "MITIGATION_FAILURE" and prop["mitigation_band"] != "FAILED":
        raise err("ERR_GROUND_NOT_ACTIONABLE",
                  "A MITIGATION_FAILURE ground requires mitigation_band FAILED.")
    if notice["ground"] == "APPRAISAL_LAPSE" and core.approved_appraisals_in_currency(prop["id"]):
        raise err("ERR_GROUND_NOT_ACTIONABLE",
                  "An APPRAISAL_LAPSE ground requires that no approved appraisal remain current.")
    if notice["ground"] == "CONCENTRATION_REVIEW" and band != "CRITICAL":
        raise err("ERR_GROUND_NOT_ACTIONABLE",
                  "A CONCENTRATION_REVIEW ground requires the zone band to be CRITICAL.")

    if enrollment["status"] != "ATTACHED":
        raise err("ERR_INVALID_STATE", "The parent enrollment is not ATTACHED.")


    notice["issued_on"] = fmt_dt(now)
    notice["status"] = "ISSUED"
    core.touch(notice)
    if notice["ground"] == "CONCENTRATION_REVIEW":
        if not prop["non_renewal_ground_activated"]:
            prop["non_renewal_ground_activated"] = True
            core.touch(prop)
    return ok(render(notice))


@bp.route("/hnw/non-renewal-notices/<notice_id>/rescind", methods=["POST"])
def rescind_notice(notice_id):
    authorize(("Underwriter",))
    notice = core.get(db.NON_RENEWAL_NOTICES, notice_id, "NonRenewalNotice")
    if notice["status"] not in ("PENDING", "ISSUED"):
        raise err("ERR_INVALID_STATE",
                  "Only a PENDING or ISSUED notice may be rescinded.")
    if notice["effective_on"] is not None and db.now() > notice["effective_on"]:
        raise err("ERR_INVALID_STATE",
                  "The notice's effective date has already passed.")
    notice["status"] = "RESCINDED"
    core.touch(notice)
    prop = db.PROPERTIES.get(notice["property_id"])
    if prop is not None:
        active = core.has_activated_ground(prop["id"])
        if prop["non_renewal_ground_activated"] != active:
            prop["non_renewal_ground_activated"] = active
            core.touch(prop)
    return ok(render(notice))


# --------------------------------------------------------------------------
# managed-risk letters
# --------------------------------------------------------------------------
@bp.route("/hnw/properties/<property_id>/managed-risk-events", methods=["GET"])
def list_property_events(property_id):
    authorize(MANAGED_READERS)
    core.get(db.PROPERTIES, property_id, "Property")
    limit, offset = reqs.pagination()
    rows = [e for e in db.MANAGED_RISK_EVENTS.values() if e["property_id"] == property_id]
    event_type = reqs.query("event_type")
    if event_type:
        rows = [e for e in rows if e["event_type"] == event_type]
    rows = reqs.sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return array(render_list(page), meta)


@bp.route("/hnw/managed-risk-events", methods=["GET"])
def list_events():
    authorize(("Underwriter", "ComplianceReporter", "PlatformAdmin"))
    limit, offset = reqs.pagination()
    rows = list(db.MANAGED_RISK_EVENTS.values())
    property_id = reqs.query("property_id")
    event_type = reqs.query("event_type")
    if property_id:
        rows = [e for e in rows if e["property_id"] == property_id]
    if event_type:
        rows = [e for e in rows if e["event_type"] == event_type]
    rows = reqs.sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return array(render_list(page), meta)