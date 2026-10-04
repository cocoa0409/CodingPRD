"""Walk-in clinics, visits, rabies certificates and state reporting (PRD §3.7)."""

from datetime import timedelta

import db
import domain
import validate
from errors import ApiError
from services import core


def _same_day(left, right):
    return (left.year, left.month, left.day) == (right.year, right.month, right.day)


def create_clinic(body, store_id):
    store = core.require_store(store_id)
    body = validate.shape(body, required=["clinic_date", "open_time", "close_time"],
                          optional=[])
    clinic_date = db.parse_dt(body["clinic_date"])
    open_time = db.parse_dt(body["open_time"])
    close_time = db.parse_dt(body["close_time"])
    if close_time <= open_time:
        raise ApiError("ERR_CLINIC_WINDOW_INVALID")
    validate.check_backdating(store)
    for other in core.store_clinics(store_id):
        if not _same_day(other["clinic_date"], clinic_date):
            continue
        if open_time < other["close_time"] and other["open_time"] < close_time:
            raise ApiError("ERR_CLINIC_OVERLAP")
    row = db.new_row()
    row.update({
        "store_id": store_id, "clinic_date": clinic_date, "open_time": open_time,
        "close_time": close_time,
        # staffing is decided at creation time from the store's posture
        "coverage_required": store["hospital_posture"] in ("RESTRICTED", "FROZEN"),
        "coverage_provider": None, "clinic_status": "SCHEDULED",
    })
    db.add("clinics", row)
    return row


def create_visit(body, store_id):
    store = core.require_store(store_id)
    body = validate.shape(body, required=["clinic_id", "pet_id", "vaccine_type"],
                          optional=["prior_rabies_vaccination_date"])
    clinic = core.require_clinic(body["clinic_id"])
    if clinic["store_id"] != store_id:
        raise ApiError("ERR_VISIT_CLINIC_MISMATCH")
    pet = core.require_pet(body["pet_id"])
    if clinic["clinic_status"] != "OPEN":
        raise ApiError("ERR_CLINIC_NOT_OPEN")
    prior = db.parse_dt(body.get("prior_rabies_vaccination_date"))
    validate.check_backdating(store, clinic, pet)
    row = db.new_row()
    row.update({
        "clinic_id": clinic["id"], "pet_id": pet["id"], "store_id": store_id,
        "walk_in_at": db.now(), "vaccine_type": body["vaccine_type"],
        "prior_rabies_vaccination_date": prior,
        "prior_effective_days": None, "prior_is_booster": False,
        "new_effective_days": None, "certificate_serial": None,
        "certificate_issued_at": None, "certificate_expires_at": None,
        "state_report_status": "PENDING", "state_report_due_at": None,
        "status": "REGISTERED",
    })
    db.add("visits", row)
    return row


def _prior_effective_days(pet_id, prior_date):
    """§3.7: the day count carried by the pet's latest certificate issued at or
    before the supplied prior vaccination date (searched globally over the pet)."""
    candidates = [c for c in db.rows("certificates")
                  if c["pet_id"] == pet_id and c["issued_at"] <= prior_date]
    if not candidates:
        return None
    latest = max(candidates, key=lambda c: (c["issued_at"], c["id"]))
    return latest["effective_days"]


def issue_certificate(body, store_id, visit_id):
    store = core.require_store(store_id)
    visit = core.require_visit(visit_id)
    if visit["store_id"] != store_id:
        raise ApiError("ERR_VISIT_NOT_FOUND")
    clinic = core.require_clinic(visit["clinic_id"])
    if clinic["store_id"] != store_id:
        raise ApiError("ERR_VISIT_CLINIC_MISMATCH")
    body = validate.shape(body, required=["expected_visit_version"], optional=[])
    validate.check_backdating(store, visit, clinic)
    if clinic["clinic_status"] != "OPEN":
        raise ApiError("ERR_CLINIC_NOT_OPEN")
    if visit["vaccine_type"] != "RABIES":
        raise ApiError("ERR_VISIT_NOT_RABIES")
    if not (clinic["open_time"] <= visit["walk_in_at"] <= clinic["close_time"]):
        raise ApiError("ERR_VISIT_OUTSIDE_WINDOW")
    validate.require_expected(body, visit["version"], "expected_visit_version")

    # priority 18: the weekday rule is the tighter of the two, so a weekend
    # issuance reports the weekday error even when the clock is also outside
    # the window.
    if db.now().weekday() in (5, 6):
        raise ApiError("ERR_VISIT_WEEKEND_BLOCKED")
    if not (clinic["open_time"] <= db.now() <= clinic["close_time"]):
        raise ApiError("ERR_VISIT_OUTSIDE_WINDOW")
    # priority 19
    prior_date = visit["prior_rabies_vaccination_date"]
    if prior_date is not None:
        if not prior_date < clinic["clinic_date"]:
            raise ApiError("ERR_PRIOR_VACCINATION_NOT_PRIOR")

    state_default_days = domain.STATE_DEFAULT_DAYS[store["state_code"]]
    if prior_date is None:
        prior_days = None
        prior_is_booster = False
        new_effective_days = state_default_days
    else:
        prior_days = _prior_effective_days(visit["pet_id"], prior_date)
        prior_is_booster = prior_days == domain.BOOSTER_CAP_DAYS
        new_effective_days = (min(state_default_days, domain.BOOSTER_CAP_DAYS)
                              if prior_is_booster else state_default_days)

    issued_at = db.now()
    expires_at = issued_at + timedelta(days=new_effective_days)
    year = issued_at.year
    existing = [c for c in db.rows("certificates")
                if c["serial"].startswith("%s-%d-" % (store["state_code"], year))]
    serial = "%s-%d-%06d" % (store["state_code"], year, len(existing) + 1)
    if any(c["serial"] == serial for c in db.rows("certificates")):
        raise ApiError("ERR_CERTIFICATE_SERIAL_DUPLICATE")

    cert = db.new_row(versioned=False)
    cert.update({
        "visit_id": visit["id"], "pet_id": visit["pet_id"], "store_id": store_id,
        "serial": serial, "issued_at": issued_at, "expires_at": expires_at,
        "effective_days": new_effective_days, "is_booster": prior_is_booster,
        "is_effective": db.now() <= expires_at,
    })
    db.add("certificates", cert)

    pet = core.require_pet(visit["pet_id"])
    # provisional stamping at issuance: the just-written certificate alone
    pet["rabies_vaccination_expires_at"] = expires_at
    db.touch(pet)

    visit["prior_effective_days"] = prior_days
    visit["prior_is_booster"] = prior_is_booster
    visit["new_effective_days"] = new_effective_days
    visit["certificate_serial"] = serial
    visit["certificate_issued_at"] = issued_at
    visit["certificate_expires_at"] = expires_at
    visit["status"] = "CERTIFICATE_ISSUED"
    db.touch(visit)

    if domain.REPORTING_STATES.get(store["state_code"]) \
            and visit["vaccine_type"] in domain.REPORTABLE_VACCINE_TYPES:
        visit["status"] = "REPORT_REQUIRED"
        visit["state_report_status"] = "PENDING"
        visit["state_report_due_at"] = db.month_end_after(issued_at)
        db.touch(visit)
        core.schedule("REPORT_OVERDUE", {"visit_id": visit["id"]})
    return visit


def submit_state_report(body, store_id, visit_id):
    store = core.require_store(store_id)
    visit = core.require_visit(visit_id)
    if visit["store_id"] != store_id:
        raise ApiError("ERR_VISIT_NOT_FOUND")
    body = validate.shape(body, required=["expected_visit_version"], optional=[])
    validate.check_backdating(store, visit)
    if visit["status"] != "REPORT_REQUIRED":
        raise ApiError("ERR_VISIT_NOT_REPORTABLE")
    if visit["state_report_status"] == "SUBMITTED":
        raise ApiError("ERR_VISIT_ALREADY_REPORTED")
    validate.require_expected(body, visit["version"], "expected_visit_version")
    visit["state_report_status"] = "SUBMITTED"
    visit["status"] = "REPORTED"
    visit["state_report_submitted_at"] = db.now()
    db.touch(visit)
    return visit


def open_walk_ins(body, store_id, clinic_id):
    store = core.require_store(store_id)
    clinic = core.require_clinic(clinic_id)
    if clinic["store_id"] != store_id:
        raise ApiError("ERR_CLINIC_NOT_FOUND")
    body = validate.shape(body, required=["expected_clinic_version"], optional=[])
    validate.check_backdating(store, clinic)
    if clinic["clinic_status"] != "SCHEDULED":
        raise ApiError("ERR_CLINIC_NOT_OPEN")
    if store["hospital_posture"] != "OPEN":
        raise ApiError("ERR_CLINIC_STORE_NOT_OPEN")
    validate.require_expected(body, clinic["version"], "expected_clinic_version")
    # priority 7: coverage and same-day opening share one error id
    if clinic["coverage_required"] and not (clinic["coverage_provider"] or "").strip():
        raise ApiError("ERR_CLINIC_COVERAGE_REQUIRED")
    if not _same_day(clinic["clinic_date"], db.now()):
        raise ApiError("ERR_CLINIC_COVERAGE_REQUIRED")
    clinic["clinic_status"] = "OPEN"
    db.touch(clinic)
    return clinic


def close_walk_ins(body, store_id, clinic_id):
    store = core.require_store(store_id)
    clinic = core.require_clinic(clinic_id)
    if clinic["store_id"] != store_id:
        raise ApiError("ERR_CLINIC_NOT_FOUND")
    body = validate.shape(body, required=["expected_clinic_version"], optional=[])
    validate.check_backdating(store, clinic)
    if clinic["clinic_status"] != "OPEN":
        raise ApiError("ERR_CLINIC_NOT_OPEN")
    open_visits = [v for v in db.rows("visits")
                   if v["clinic_id"] == clinic["id"]
                   and v["status"] in ("REGISTERED", "CERTIFICATE_ISSUED", "REPORT_REQUIRED")]
    if open_visits:
        raise ApiError("ERR_CLINIC_HAS_OPEN_VISITS")
    validate.require_expected(body, clinic["version"], "expected_clinic_version")
    clinic["clinic_status"] = "CLOSED"
    db.touch(clinic)
    return clinic


def set_coverage_provider(body, store_id, clinic_id):
    """The staffing decision made at creation is honoured by naming the relief vet."""
    store = core.require_store(store_id)
    clinic = core.require_clinic(clinic_id)
    if clinic["store_id"] != store_id:
        raise ApiError("ERR_CLINIC_NOT_FOUND")
    body = validate.shape(body, required=["coverage_provider"],
                          optional=["expected_clinic_version"])
    validate.check_backdating(store, clinic)
    if clinic["clinic_status"] not in ("SCHEDULED",):
        raise ApiError("ERR_CLINIC_NOT_OPEN")
    if "expected_clinic_version" in body and body["expected_clinic_version"] is not None \
            and int(body["expected_clinic_version"]) != clinic["version"]:
        raise ApiError("ERR_STALE_VERSION")
    clinic["coverage_provider"] = body["coverage_provider"]
    db.touch(clinic)
    return clinic


def state_report(clinic_id, store_id):
    clinic = core.require_clinic(clinic_id)
    if clinic["store_id"] != store_id:
        raise ApiError("ERR_CLINIC_NOT_FOUND")
    visits = [v for v in db.rows("visits") if v["clinic_id"] == clinic["id"]]
    reportable = [v for v in visits
                  if v["state_report_status"] in ("PENDING", "SUBMITTED", "OVERDUE")]
    submitted = [v for v in reportable if v["state_report_status"] == "SUBMITTED"]
    pending = [v for v in reportable if v["state_report_status"] == "PENDING"]
    overdue = [v for v in reportable if v["state_report_status"] == "OVERDUE"]
    outstanding = [v for v in reportable if v["state_report_status"] != "SUBMITTED"
                   and v["state_report_due_at"] is not None]
    earliest = min((v["state_report_due_at"] for v in outstanding), default=None)
    next_due = None
    if earliest is not None:
        for v in outstanding:
            if v["state_report_due_at"] == earliest:
                next_due = v["id"]
                break
    return {
        "submitted_count": len(submitted),
        "pending_count": len(pending),
        "overdue_count": len(overdue),
        "due_at_earliest": db.iso(earliest),
        "next_due_visit_id": next_due,
    }