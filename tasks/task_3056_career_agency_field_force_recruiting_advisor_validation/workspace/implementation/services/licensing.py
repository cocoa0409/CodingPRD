"""Insurance licences, securities registrations and carrier appointments
(PRD §2.8 interval conventions, §3.4 ordering hazard, §3.5 sequencing)."""

from db import db, ts, parse_dt
from errors import (
    err,
    ERR_LICENSE_NOT_FOUND,
    ERR_REGISTRATION_NOT_FOUND,
    ERR_APPOINTMENT_NOT_FOUND,
    ERR_ADVISOR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_ALREADY_TERMINAL,
    ERR_LICENSE_NOT_ACTIVE,
    ERR_REGISTRATION_NOT_ACTIVE,
    ERR_PREREQUISITE_REGISTRATION_NOT_ACTIVE,
    ERR_LICENSE_INTERVAL_OVERLAP,
    ERR_REGISTRATION_INTERVAL_OVERLAP,
    ERR_DUPLICATE_NATURAL_KEY,
)
from services import derived


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------
def get_license(license_id):
    row = db.licenses.get(license_id)
    if row is None:
        raise err(ERR_LICENSE_NOT_FOUND, "no product licence with id %s" % license_id)
    return row


def get_registration(registration_id):
    row = db.registrations.get(registration_id)
    if row is None:
        raise err(ERR_REGISTRATION_NOT_FOUND,
                  "no securities registration with id %s" % registration_id)
    return row


def get_appointment(appointment_id):
    row = db.appointments.get(appointment_id)
    if row is None:
        raise err(ERR_APPOINTMENT_NOT_FOUND,
                  "no carrier appointment with id %s" % appointment_id)
    return row


def _advisor(advisor_id):
    row = db.advisors.get(advisor_id)
    if row is None:
        raise err(ERR_ADVISOR_NOT_FOUND, "no advisor with id %s" % advisor_id)
    return row


# ---------------------------------------------------------------------------
# ProductLicense
# ---------------------------------------------------------------------------
def _license_overlaps(advisor_id, product_line, start, end, exclude_id=None):
    """Half-open [effective_date, expires_at); a shared boundary instant is NOT
    an overlap (PRD §2.8)."""
    for row in db.licenses.values():
        if row["id"] == exclude_id:
            continue
        if row["advisor_id"] != advisor_id or row["product_line"] != product_line:
            continue
        if start < row["expires_at"] and row["effective_date"] < end:
            return True
    return False


def create_license(data):
    advisor_id = data.get("advisor_id")
    if advisor_id is None:
        raise err(ERR_ADVISOR_NOT_FOUND, "advisor_id is required")
    advisor = _advisor(advisor_id)
    from middleware import require_fields
    require_fields(data, ["product_line", "license_number", "effective_date", "expires_at"])
    product_line = data.get("product_line")
    license_number = data.get("license_number")
    effective_date = parse_dt(data.get("effective_date"))
    expires_at = parse_dt(data.get("expires_at"))
    appointment_required = data.get("appointment_required")
    if appointment_required is None:
        appointment_required = True

    if _license_overlaps(advisor_id, product_line, effective_date, expires_at):
        raise err(ERR_LICENSE_INTERVAL_OVERLAP,
                  "the licence interval overlaps an existing licence")
    for row in db.licenses.values():
        if row["product_line"] == product_line and row["license_number"] == license_number:
            raise err(ERR_DUPLICATE_NATURAL_KEY,
                      "license_number %s is already in use for this product line"
                      % license_number)

    row = {
        "advisor_id": advisor_id,
        "product_line": product_line,
        "license_number": license_number,
        "effective_date": effective_date,
        "expires_at": expires_at,
        "appointment_required": bool(appointment_required),
        "status": "PENDING",
    }
    db.stamp_create(row)
    db.insert(db.licenses, row)
    derived.refresh_license_dimension(advisor_id)
    return row


def activate_license(lic):
    if lic["status"] == "REVOKED":
        raise err(ERR_ALREADY_TERMINAL, "the licence is revoked")
    if lic["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "the licence is not PENDING")
    if db.now() >= lic["expires_at"]:
        raise err(ERR_LICENSE_NOT_ACTIVE,
                  "the licence expiry has been reached")
    lic["status"] = "ACTIVE"
    db.touch(lic)
    derived.refresh_license_dimension(lic["advisor_id"])
    _cascade_requested_appointments(lic)
    return lic


def _cascade_requested_appointments(lic):
    """Every REQUESTED appointment of this advisor requiring this licence is
    re-evaluated against the appointment sequencing gate (PRD §3.5)."""
    for appt in list(db.appointments.values()):
        if appt["requires_license_id"] != lic["id"]:
            continue
        if appt["appointment_status"] != "REQUESTED":
            continue
        if _appointment_gate_open(appt, lic):
            _approve(appt, lic, demote_on_stale=False)


def renew_license(lic, new_expires_at):
    if lic["status"] == "REVOKED":
        raise err(ERR_ALREADY_TERMINAL, "the licence is revoked")
    if lic["status"] != "LAPSED":
        raise err(ERR_INVALID_STATE, "only a lapsed licence may be renewed")
    expires_at = parse_dt(new_expires_at)
    if not expires_at > db.now():
        raise err(ERR_INVALID_REQUEST,
                  "the new expires_at must be strictly after the logical clock")
    lic["expires_at"] = expires_at
    lic["status"] = "ACTIVE"
    db.touch(lic)
    derived.refresh_license_dimension(lic["advisor_id"])
    return lic


# ---------------------------------------------------------------------------
# SecuritiesRegistration
# ---------------------------------------------------------------------------
def _registration_overlaps(advisor_id, registration_type, start, end, exclude_id=None):
    """Closed [effective_date, expires_at]; a shared boundary instant IS an
    overlap (PRD §2.8)."""
    for row in db.registrations.values():
        if row["id"] == exclude_id:
            continue
        if row["advisor_id"] != advisor_id or row["registration_type"] != registration_type:
            continue
        if start <= row["expires_at"] and row["effective_date"] <= end:
            return True
    return False


def create_registration(data):
    advisor_id = data.get("advisor_id")
    if advisor_id is None:
        raise err(ERR_ADVISOR_NOT_FOUND, "advisor_id is required")
    _advisor(advisor_id)
    registration_type = data.get("registration_type")
    crd_number = data.get("crd_number")
    effective_date = parse_dt(data.get("effective_date"))
    expires_at = parse_dt(data.get("expires_at"))
    prerequisite_registration_id = data.get("prerequisite_registration_id")
    if prerequisite_registration_id is not None:
        if prerequisite_registration_id not in db.registrations:
            raise err(ERR_REGISTRATION_NOT_FOUND,
                      "no securities registration with id %s"
                      % prerequisite_registration_id)
    from middleware import require_fields
    require_fields(data, ["registration_type", "crd_number", "effective_date", "expires_at"])

    if _registration_overlaps(advisor_id, registration_type, effective_date, expires_at):
        raise err(ERR_REGISTRATION_INTERVAL_OVERLAP,
                  "the registration interval shares an instant with an existing registration")
    for row in db.registrations.values():
        if row["registration_type"] == registration_type and row["crd_number"] == crd_number:
            raise err(ERR_DUPLICATE_NATURAL_KEY,
                      "crd_number %s is already in use for this registration type"
                      % crd_number)

    row = {
        "advisor_id": advisor_id,
        "registration_type": registration_type,
        "crd_number": crd_number,
        "effective_date": effective_date,
        "expires_at": expires_at,
        "prerequisite_registration_id": prerequisite_registration_id,
        "status": "PENDING",
    }
    db.stamp_create(row)
    db.insert(db.registrations, row)
    derived.refresh_registration_dimension(advisor_id)
    return row


def activate_registration(reg, _seen=None):
    """Gate (PRD §3.5): a registration with a prerequisite may reach ACTIVE only
    when that prerequisite is itself ACTIVE; without one, only when the clock is
    strictly before its own expires_at."""
    if reg["status"] == "TERMINATED":
        raise err(ERR_ALREADY_TERMINAL, "the registration is terminated")
    if reg["status"] == "ACTIVE":
        # An already-ACTIVE registration satisfies any re-evaluation.
        return reg
    if reg["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "the registration is not PENDING")
    prerequisite_id = reg["prerequisite_registration_id"]
    if prerequisite_id is not None:
        prerequisite = db.registrations.get(prerequisite_id)
        if prerequisite is None or prerequisite["status"] != "ACTIVE":
            raise err(ERR_PREREQUISITE_REGISTRATION_NOT_ACTIVE,
                      "the prerequisite registration is not ACTIVE")
    else:
        if db.now() >= reg["expires_at"]:
            raise err(ERR_REGISTRATION_NOT_ACTIVE,
                      "the registration expiry has been reached")
    reg["status"] = "ACTIVE"
    db.touch(reg)
    derived.refresh_registration_dimension(reg["advisor_id"])
    _cascade_dependents(reg, _seen or set())
    return reg


def _cascade_dependents(reg, seen):
    if reg["id"] in seen:
        return
    seen.add(reg["id"])
    for dependent in list(db.registrations.values()):
        if dependent["prerequisite_registration_id"] != reg["id"]:
            continue
        if dependent["status"] != "PENDING":
            continue
        if reg["status"] != "ACTIVE":
            continue
        activate_registration(dependent, seen)


def dependents(reg):
    return [r for r in db.registrations.values()
            if r["prerequisite_registration_id"] == reg["id"]]


# ---------------------------------------------------------------------------
# CarrierAppointment
# ---------------------------------------------------------------------------
def create_appointment(data):
    advisor_id = data.get("advisor_id")
    if advisor_id is None:
        raise err(ERR_ADVISOR_NOT_FOUND, "advisor_id is required")
    advisor = _advisor(advisor_id)
    requires_license_id = data.get("requires_license_id")
    if requires_license_id is None:
        raise err(ERR_LICENSE_NOT_FOUND, "requires_license_id is required")
    lic = db.licenses.get(requires_license_id)
    if lic is None or lic["advisor_id"] != advisor_id:
        raise err(ERR_LICENSE_NOT_FOUND,
                  "no product licence with id %s belongs to advisor %s"
                  % (requires_license_id, advisor_id))
    from middleware import require_fields
    require_fields(data, ["carrier_name", "state_code", "requested_date"])

    row = {
        "advisor_id": advisor_id,
        "requires_license_id": requires_license_id,
        "carrier_name": data.get("carrier_name"),
        "state_code": data.get("state_code"),
        "requested_date": parse_dt(data.get("requested_date")),
        "appointment_date": None,
        "appointment_status": "REQUESTED",
    }
    db.stamp_create(row)
    db.insert(db.appointments, row)
    derived.refresh_appointment_dimension(advisor_id)
    return row


def _appointment_gate_open(appt, lic):
    return lic["status"] == "ACTIVE" and db.now() < lic["expires_at"]


def approve_appointment(appt):
    if appt["appointment_status"] == "TERMINATED":
        raise err(ERR_ALREADY_TERMINAL, "the appointment is terminated")
    if appt["appointment_status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "the appointment is not REQUESTED")
    lic = db.licenses.get(appt["requires_license_id"])
    if lic is None:
        raise err(ERR_LICENSE_NOT_FOUND, "the required licence no longer exists")
    if not _appointment_gate_open(appt, lic):
        # The licence gate is evaluated first; a licence whose expiry the clock
        # has reached also demotes an ACTIVE_TRAINING advisor to AT_RISK unless
        # licensing_locked suppresses it (PRD §3.4).
        stale = db.now() >= lic["expires_at"]
        if stale:
            _demote_for_stale_licence(appt["advisor_id"])
        raise err(ERR_LICENSE_NOT_ACTIVE,
                  "the required licence is not ACTIVE at approval time")
    _approve(appt, lic, demote_on_stale=False)
    return appt


def _approve(appt, lic, demote_on_stale):
    if db.now() >= lic["expires_at"]:
        if demote_on_stale:
            _demote_for_stale_licence(appt["advisor_id"])
        return
    appt["appointment_status"] = "APPROVED"
    appt["appointment_date"] = ts(db.now())
    db.touch(appt)
    derived.refresh_appointment_dimension(appt["advisor_id"])


def _demote_for_stale_licence(advisor_id):
    advisor = db.advisors.get(advisor_id)
    if advisor is None:
        return
    if advisor.get("licensing_locked"):
        return
    if advisor["contract_status"] != "ACTIVE_TRAINING":
        return
    advisor["contract_status"] = "AT_RISK"
    advisor["validation_posture"] = "AT_RISK"
    db.touch(advisor)
    for contract in db.contracts.values():
        if contract["advisor_id"] == advisor_id and contract["contract_status"] == "ACTIVE_TRAINING":
            contract["contract_status"] = "AT_RISK"
            db.touch(contract)


def reject_appointment(appt):
    if appt["appointment_status"] == "TERMINATED":
        raise err(ERR_ALREADY_TERMINAL, "the appointment is terminated")
    if appt["appointment_status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "the appointment is not REQUESTED")
    appt["appointment_status"] = "REJECTED"
    db.touch(appt)
    derived.refresh_appointment_dimension(appt["advisor_id"])
    return appt