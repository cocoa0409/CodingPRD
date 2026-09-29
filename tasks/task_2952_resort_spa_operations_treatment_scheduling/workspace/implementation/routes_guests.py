"""Guest registration, health intake and clinical screening (PRD §3.4)."""

from flask import Blueprint

import auth
import calc
import domain
import envelope
import errors
import store
import validation as v
from errors import ApiError
from store import db, touch

bp = Blueprint("guests", __name__)

LOYALTY_TIERS = ("NONE", "SILVER", "GOLD", "PLATINUM")
INTAKE_STATUSES = ("DRAFT", "SUBMITTED", "SCREENED_CLEAR", "SCREENED_FLAGGED",
                   "OVERRIDDEN", "SUPERSEDED")


# --------------------------------------------------------------------------
# guests
# --------------------------------------------------------------------------

@bp.route("/guests", methods=["POST"])
def create_guest():
    auth.authenticate(auth.SPA_COORDINATOR, auth.SPA_DIRECTOR)
    body = v.json_body()
    full_name = v.field_str(body, "full_name", max_len=200)
    room_number = v.field_str(body, "resort_room_number", max_len=32)
    loyalty_tier = v.field_enum(body, "loyalty_tier", LOYALTY_TIERS, required=False,
                                default="NONE")
    folio_limit = v.field_int(body, "folio_limit_cents", minimum=0)

    entity = {}
    store.stamp_common(entity)
    entity.update({
        "full_name": full_name,
        "resort_room_number": room_number,
        "loyalty_tier": loyalty_tier,
        "folio_limit_cents": folio_limit,
        "folio_balance_cents": 0,
        "late_cancel_count": 0,
        "no_show_strikes": 0,
        "booking_privilege": "OPEN",
        "authoritative_intake_form_id": None,
        "screened_condition_codes": [],
    })
    db.guests[entity["id"]] = entity
    return envelope.created(entity)


@bp.route("/guests/<guest_id>", methods=["GET"])
def read_guest(guest_id):
    caller = auth.authenticate(auth.SPA_COORDINATOR, auth.SPA_DIRECTOR,
                               auth.COMPLIANCE_OFFICER, auth.GUEST)
    guest = domain.find_guest(guest_id)
    auth.require_guest_owner(caller, guest["id"])
    return envelope.ok(guest)


# --------------------------------------------------------------------------
# intake forms
# --------------------------------------------------------------------------

@bp.route("/guests/<guest_id>/intake-forms", methods=["POST"])
def create_intake_form(guest_id):
    caller = auth.authenticate(auth.GUEST, auth.SPA_COORDINATOR)
    body = v.json_body()
    expected_version = v.field_int(body, "expected_guest_version", minimum=0)
    condition_codes = v.field_str_array(body, "condition_codes", required=False,
                                        default=[])
    medications = v.field_str_array(body, "medications", required=False, default=[])
    guest = domain.find_guest(guest_id)
    auth.require_guest_owner(caller, guest["id"])

    if expected_version != guest["version"]:
        raise ApiError(errors.ERR_STALE_GUEST_VERSION,
                       "The guest version has moved on; expected %s but found %s."
                       % (expected_version, guest["version"]))

    entity = {}
    store.stamp_common(entity)
    entity.update({
        "guest_id": guest["id"],
        "condition_codes": list(condition_codes or []),
        "medications": list(medications or []),
        "status": "DRAFT",
        "flagged_condition_codes": [],
        "consent_version": None,
        "consent_signed_at": None,
        "screened_by_user_id": None,
        "screened_at": None,
        "overridden_by_user_id": None,
        "override_reason": None,
        "amendment_round": 0,
    })
    db.intake_forms[entity["id"]] = entity
    touch(guest)
    return envelope.created(entity)


@bp.route("/guests/<guest_id>/intake-forms", methods=["GET"])
def list_intake_forms(guest_id):
    caller = auth.authenticate(auth.SPA_COORDINATOR, auth.COMPLIANCE_OFFICER,
                               auth.SPA_DIRECTOR, auth.GUEST)
    limit, offset = v.pagination()
    status = v.query_enum("status", INTAKE_STATUSES)
    guest = domain.find_guest(guest_id)
    auth.require_guest_owner(caller, guest["id"])

    rows = domain.intake_forms_of(guest["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = list(reversed(rows))
    return envelope.listing(v.paginate(rows, limit, offset), len(rows), limit, offset)


@bp.route("/intake-forms/<form_id>", methods=["GET"])
def read_intake_form(form_id):
    caller = auth.authenticate(auth.SPA_COORDINATOR, auth.COMPLIANCE_OFFICER,
                               auth.SPA_DIRECTOR, auth.GUEST)
    form = domain.find_intake_form(form_id)
    auth.require_guest_owner(caller, form["guest_id"])
    return envelope.ok(form)


@bp.route("/intake-forms/<form_id>/consent", methods=["POST"])
def sign_consent(form_id):
    caller = auth.authenticate(auth.GUEST, auth.SPA_COORDINATOR)
    body = v.json_body()
    consent_version = v.field_str(body, "consent_version", max_len=64)
    form = domain.find_intake_form(form_id)
    auth.require_guest_owner(caller, form["guest_id"])

    if form["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError(errors.ERR_INVALID_INTAKE_STATE,
                       "Consent may only be recorded on a DRAFT or SUBMITTED form.")

    form["consent_version"] = consent_version
    form["consent_signed_at"] = db.clock
    touch(form)
    return envelope.ok(form)


@bp.route("/intake-forms/<form_id>/submit", methods=["POST"])
def submit_intake_form(form_id):
    caller = auth.authenticate(auth.GUEST, auth.SPA_COORDINATOR)
    v.json_body()
    form = domain.find_intake_form(form_id)
    auth.require_guest_owner(caller, form["guest_id"])

    if form["status"] != "DRAFT":
        raise ApiError(errors.ERR_INVALID_INTAKE_STATE,
                       "Only a DRAFT intake form may be submitted.")

    form["status"] = "SUBMITTED"
    touch(form)
    return envelope.ok(form)


@bp.route("/intake-forms/<form_id>/screen", methods=["POST"])
def screen_intake_form(form_id):
    caller = auth.authenticate(auth.COMPLIANCE_OFFICER)
    v.json_body()
    form = domain.find_intake_form(form_id)

    if form["status"] != "SUBMITTED":
        raise ApiError(errors.ERR_INVALID_INTAKE_STATE,
                       "Only a SUBMITTED intake form may be screened.")

    flagged = []
    for code in form["condition_codes"]:
        if code in calc.HIGH_RISK_CONDITION_CODES and code not in flagged:
            flagged.append(code)

    form["flagged_condition_codes"] = flagged
    form["status"] = "SCREENED_FLAGGED" if flagged else "SCREENED_CLEAR"
    form["screened_by_user_id"] = caller.user_id
    form["screened_at"] = db.clock
    touch(form)

    guest = db.guests.get(form["guest_id"])
    previous_id = guest.get("authoritative_intake_form_id")
    if previous_id and previous_id != form["id"]:
        previous = db.intake_forms.get(previous_id)
        if previous is not None:
            previous["status"] = "SUPERSEDED"
            touch(previous)

    guest["authoritative_intake_form_id"] = form["id"]
    guest["screened_condition_codes"] = list(form["condition_codes"])
    touch(guest)

    appointments = domain.appointments_of_guest(guest["id"])
    if flagged:
        domain.run_block_cascade(appointments)
    else:
        domain.run_reclear_cascade(appointments)
    return envelope.ok(form)


@bp.route("/intake-forms/<form_id>/override", methods=["POST"])
def override_intake_form(form_id):
    caller = auth.authenticate(auth.SPA_DIRECTOR)
    body = v.json_body()
    override_reason = v.field_str(body, "override_reason", max_len=1000)
    form = domain.find_intake_form(form_id)

    if form["status"] != "SCREENED_FLAGGED":
        raise ApiError(errors.ERR_INVALID_INTAKE_STATE,
                       "Only a SCREENED_FLAGGED form may be overridden.")
    if caller.user_id == form.get("screened_by_user_id"):
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES,
                       "The screening officer may not override the same form.")

    form["status"] = "OVERRIDDEN"
    form["overridden_by_user_id"] = caller.user_id
    form["override_reason"] = override_reason
    touch(form)

    domain.run_reclear_cascade(domain.appointments_of_guest(form["guest_id"]))
    return envelope.ok(form)


@bp.route("/intake-forms/<form_id>/amend", methods=["POST"])
def amend_intake_form(form_id):
    caller = auth.authenticate(auth.GUEST, auth.SPA_COORDINATOR)
    body = v.json_body()
    condition_codes = v.field_str_array(body, "condition_codes", required=False,
                                        default=[])
    medications = v.field_str_array(body, "medications", required=False, default=[])
    form = domain.find_intake_form(form_id)
    auth.require_guest_owner(caller, form["guest_id"])

    if form["status"] != "SCREENED_FLAGGED":
        raise ApiError(errors.ERR_INVALID_INTAKE_STATE,
                       "Only a SCREENED_FLAGGED form may be amended.")
    if form["amendment_round"] >= calc.MAX_AMENDMENT_ROUNDS:
        raise ApiError(errors.ERR_AMENDMENT_LIMIT,
                       "The intake amendment budget of %d rounds is exhausted."
                       % calc.MAX_AMENDMENT_ROUNDS)

    form["condition_codes"] = list(condition_codes or [])
    form["medications"] = list(medications or [])
    form["flagged_condition_codes"] = []
    form["screened_by_user_id"] = None
    form["screened_at"] = None
    form["status"] = "DRAFT"
    form["amendment_round"] += 1
    touch(form)

    guest = db.guests.get(form["guest_id"])
    domain.recompute_authoritative(guest)
    touch(guest)
    return envelope.ok(form)
