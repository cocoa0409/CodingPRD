from flask import Blueprint, request
import db
import errors
import helpers
import serializers as ser
import services
from response import success_obj, success_list

bp = Blueprint("screening", __name__, url_prefix="/screening")

ROLES = {"ProgramAdmin", "Provider", "LabTechnician", "FulfillmentAgent", "Navigator"}
ALL_ROLES = ROLES


def _allowed(allowed):
    def wrapper():
        uid = request.headers.get("X-User-ID")
        role = request.headers.get("X-User-Role")
        if uid is None or uid == "" or role is None or role == "":
            raise errors.missing_context()
        if role not in allowed:
            raise errors.forbidden()
        return uid, role
    return wrapper


def _get_or_404(store, key):
    ent = db.STORE[store].get(key)
    if ent is None:
        raise errors.not_found()
    return ent


def _touch_program(program):
    db.touch(program)


def _recompute_and_touch_program(program_id):
    program = db.STORE["programs"].get(program_id)
    if program is None:
        return
    services.recompute_program_counters(program_id)
    db.touch(program)


# =========================================================================
# Logical clock
# =========================================================================
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _allowed({"ProgramAdmin"})()
    body = helpers.get_body()
    raw = helpers.req_str(body, "to_iso8601")
    try:
        dt = db.parse_iso(raw)
    except Exception:
        raise errors.validation("to_iso8601 must be a valid ISO 8601 timestamp")
    db.set_clock(dt)
    services.evaluate_time_transitions()
    return success_obj({"current_utc": db.iso_ms(db.now())})


# =========================================================================
# Programs
# =========================================================================
@bp.route("/programs", methods=["POST"])
def create_program():
    _allowed({"ProgramAdmin"})()
    body = helpers.get_body()
    program_code = helpers.req_str(body, "program_code")
    program_name = helpers.req_str(body, "program_name")
    outreach_mode = helpers.req_enum(body, "outreach_mode", {"PUSH", "SELF_SERVE"})
    measure_year = helpers.req_int(body, "measure_year")
    is_active = helpers.opt_bool(body, "is_active", True)
    ent = db.new_entity()
    ent.update({
        "program_code": program_code,
        "program_name": program_name,
        "outreach_mode": outreach_mode,
        "is_active": is_active,
        "population_size": 0,
        "attributed_count": 0,
        "adherent_count": 0,
        "measure_year": measure_year,
    })
    db.STORE["programs"][ent["id"]] = ent
    return success_obj(ser.program_view(ent), 201)


@bp.route("/programs", methods=["GET"])
def list_programs():
    _allowed(ALL_ROLES)()
    limit, offset = helpers.get_limit_offset()
    items = sorted(db.STORE["programs"].values(), key=lambda e: e["created_at"])
    total = len(items)
    window = items[offset:offset + limit]
    return success_list([ser.program_view(p) for p in window], limit, offset, total)


@bp.route("/programs/<programId>", methods=["GET"])
def get_program(programId):
    _allowed(ALL_ROLES)()
    p = _get_or_404("programs", programId)
    return success_obj(ser.program_view(p))


@bp.route("/programs/<programId>/cohorts", methods=["GET"])
def list_program_cohorts(programId):
    _allowed({"ProgramAdmin"})()
    _get_or_404("programs", programId)
    limit, offset = helpers.get_limit_offset()
    status_f = request.args.get("status")
    items = [c for c in db.STORE["cohorts"].values() if c["program_id"] == programId]
    if status_f is not None:
        items = [c for c in items if c["status"] == status_f]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    window = items[offset:offset + limit]
    return success_list([ser.cohort_view(c) for c in window], limit, offset, total)


@bp.route("/programs/<programId>/cohorts", methods=["POST"])
def create_cohort(programId):
    _allowed({"ProgramAdmin"})()
    program = _get_or_404("programs", programId)
    body = helpers.get_body()
    patient_id = helpers.req_str(body, "patient_id")
    patient = db.STORE["patients"].get(patient_id)
    if patient is None:
        raise errors.not_found("patient not found")
    today = db.date_of(db.now())
    ent = db.new_entity()
    ent.update({
        "program_id": programId,
        "patient_id": patient_id,
        "enrolled_at": today,
        "attributed": True,
        "adherence_window_start": today,
        "adherence_window_end": db.add_days(today, db.ADHERENCE_WINDOW_DAYS - 1),
        "status": "ELIGIBLE",
    })
    db.STORE["cohorts"][ent["id"]] = ent
    _recompute_and_touch_program(programId)
    return success_obj(ser.cohort_view(ent), 201)


@bp.route("/programs/<programId>/cohorts/<cohortId>", methods=["GET"])
def get_program_cohort(programId, cohortId):
    _allowed({"ProgramAdmin"})()
    _get_or_404("programs", programId)
    cohort = _get_or_404("cohorts", cohortId)
    if cohort["program_id"] != programId:
        raise errors.not_found()
    return success_obj(ser.cohort_view(cohort))


@bp.route("/programs/<programId>/cohorts/<cohortId>/outreach", methods=["POST"])
def outreach(programId, cohortId):
    _allowed({"ProgramAdmin"})()
    program = _get_or_404("programs", programId)
    cohort = _get_or_404("cohorts", cohortId)
    if cohort["program_id"] != programId:
        raise errors.not_found()
    body = helpers.get_body()
    channel = helpers.req_enum(body, "channel", {"MAIL", "SMS", "PHONE"})
    template_code = helpers.req_str(body, "template_code")
    if cohort["status"] != "ELIGIBLE":
        raise errors.biz("ERR_COHORT_INVALID_STATE", 409, "Cohort not in ELIGIBLE status")
    if not program["is_active"]:
        raise errors.biz("ERR_PROGRAM_INACTIVE", 422, "Program is not active")
    if program["outreach_mode"] != "PUSH":
        raise errors.biz("ERR_PROGRAM_MODE_VIOLATION", 422, "Outreach allowed only for PUSH programs")
    ev = {
        "id": db.new_id(),
        "cohort_id": cohortId,
        "channel": channel,
        "sent_at": db.now(),
        "template_code": template_code,
        "created_at": db.now(),
    }
    db.STORE["outreach_events"][ev["id"]] = ev
    cohort["status"] = "OUTREACH_SENT"
    db.touch(cohort)
    _recompute_and_touch_program(programId)
    return success_obj(ser.outreach_event_view(ev), 201)


@bp.route("/programs/<programId>/cohorts/<cohortId>/exclude", methods=["POST"])
def exclude_cohort(programId, cohortId):
    _allowed({"ProgramAdmin"})()
    _get_or_404("programs", programId)
    cohort = _get_or_404("cohorts", cohortId)
    if cohort["program_id"] != programId:
        raise errors.not_found()
    helpers.get_body()
    if cohort["status"] not in ("ELIGIBLE", "OUTREACH_SENT"):
        raise errors.biz("ERR_COHORT_INVALID_STATE", 409, "Cohort not in ELIGIBLE or OUTREACH_SENT status")
    cohort["attributed"] = False
    cohort["status"] = "EXCLUDED"
    db.touch(cohort)
    _recompute_and_touch_program(programId)
    return success_obj(ser.cohort_view(cohort))


@bp.route("/programs/<programId>/cohorts/<cohortId>/outreach-events", methods=["GET"])
def list_cohort_outreach_events(programId, cohortId):
    _allowed({"ProgramAdmin"})()
    _get_or_404("programs", programId)
    cohort = _get_or_404("cohorts", cohortId)
    if cohort["program_id"] != programId:
        raise errors.not_found()
    limit, offset = helpers.get_limit_offset()
    items = [e for e in db.STORE["outreach_events"].values() if e["cohort_id"] == cohortId]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    window = items[offset:offset + limit]
    return success_list([ser.outreach_event_view(e) for e in window], limit, offset, total)


@bp.route("/programs/<programId>/quality-measure-report", methods=["POST"])
def create_report(programId):
    _allowed({"ProgramAdmin"})()
    program = _get_or_404("programs", programId)
    helpers.get_body()
    services.recompute_program_counters(programId)
    numerator = program["adherent_count"]
    denominator = program["attributed_count"]
    ent = db.new_entity()
    ent.update({
        "program_id": programId,
        "measure_year": program["measure_year"],
        "numerator": numerator,
        "denominator": denominator,
        "adherence_rate": services.adherence_rate(numerator, denominator),
        "snapshot_at": db.now(),
    })
    db.STORE["reports"][ent["id"]] = ent
    return success_obj(ser.report_view(ent), 201)


@bp.route("/programs/<programId>/quality-measure-reports", methods=["GET"])
def list_program_reports(programId):
    _allowed({"ProgramAdmin"})()
    _get_or_404("programs", programId)
    limit, offset = helpers.get_limit_offset()
    items = [r for r in db.STORE["reports"].values() if r["program_id"] == programId]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    window = items[offset:offset + limit]
    return success_list([ser.report_view(r) for r in window], limit, offset, total)


# =========================================================================
# Cohorts (flat)
# =========================================================================
@bp.route("/cohorts", methods=["GET"])
def list_cohorts():
    _allowed({"ProgramAdmin"})()
    limit, offset = helpers.get_limit_offset()
    program_id = request.args.get("program_id")
    patient_id = request.args.get("patient_id")
    items = list(db.STORE["cohorts"].values())
    if program_id is not None:
        items = [c for c in items if c["program_id"] == program_id]
    if patient_id is not None:
        items = [c for c in items if c["patient_id"] == patient_id]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    window = items[offset:offset + limit]
    return success_list([ser.cohort_view(c) for c in window], limit, offset, total)


@bp.route("/cohorts/<cohortId>", methods=["GET"])
def get_cohort(cohortId):
    _allowed({"ProgramAdmin"})()
    cohort = _get_or_404("cohorts", cohortId)
    return success_obj(ser.cohort_view(cohort))


# =========================================================================
# Outreach events (flat)
# =========================================================================
@bp.route("/outreach-events", methods=["GET"])
def list_outreach_events():
    _allowed({"ProgramAdmin"})()
    limit, offset = helpers.get_limit_offset()
    cohort_id = request.args.get("cohort_id")
    items = list(db.STORE["outreach_events"].values())
    if cohort_id is not None:
        items = [e for e in items if e["cohort_id"] == cohort_id]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    window = items[offset:offset + limit]
    return success_list([ser.outreach_event_view(e) for e in window], limit, offset, total)


@bp.route("/outreach-events/<eventId>", methods=["GET"])
def get_outreach_event(eventId):
    _allowed({"ProgramAdmin"})()
    ev = _get_or_404("outreach_events", eventId)
    return success_obj(ser.outreach_event_view(ev))


# =========================================================================
# Reminders (flat)
# =========================================================================
@bp.route("/reminders", methods=["GET"])
def list_reminders():
    _allowed({"ProgramAdmin", "FulfillmentAgent"})()
    limit, offset = helpers.get_limit_offset()
    order_id = request.args.get("order_id")
    status_f = request.args.get("status")
    items = list(db.STORE["reminders"].values())
    if order_id is not None:
        items = [r for r in items if r["order_id"] == order_id]
    if status_f is not None:
        items = [r for r in items if r["status"] == status_f]
    items.sort(key=lambda e: (e["created_at"], e["sequence_no"]))
    total = len(items)
    window = items[offset:offset + limit]
    return success_list([ser.reminder_view(r) for r in window], limit, offset, total)


@bp.route("/reminders/<reminderId>", methods=["GET"])
def get_reminder(reminderId):
    _allowed({"ProgramAdmin", "FulfillmentAgent"})()
    rem = _get_or_404("reminders", reminderId)
    return success_obj(ser.reminder_view(rem))


# =========================================================================
# Quality measure reports (flat)
# =========================================================================
@bp.route("/quality-measure-reports", methods=["GET"])
def list_reports():
    _allowed({"ProgramAdmin"})()
    limit, offset = helpers.get_limit_offset()
    program_id = request.args.get("program_id")
    items = list(db.STORE["reports"].values())
    if program_id is not None:
        items = [r for r in items if r["program_id"] == program_id]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    window = items[offset:offset + limit]
    return success_list([ser.report_view(r) for r in window], limit, offset, total)


@bp.route("/quality-measure-reports/<reportId>", methods=["GET"])
def get_report(reportId):
    _allowed({"ProgramAdmin"})()
    rep = _get_or_404("reports", reportId)
    return success_obj(ser.report_view(rep))


# =========================================================================
# Patients
# =========================================================================
@bp.route("/patients", methods=["POST"])
def create_patient():
    _allowed({"ProgramAdmin", "Provider"})()
    body = helpers.get_body()
    external_ref = helpers.req_str(body, "external_ref")
    date_of_birth = helpers.opt_date_str(body, "date_of_birth")
    if date_of_birth is None:
        raise errors.validation("Missing required field: date_of_birth")
    risk_category = helpers.req_enum(body, "risk_category", {"AVERAGE", "ELEVATED", "HIGH"})
    contraindication_flags = helpers.opt_str_list(body, "contraindication_flags", [])
    recent_symptoms = helpers.opt_bool(body, "recent_symptoms", False)
    comorbidity = helpers.opt_bool(body, "comorbidity", False)
    family_history = helpers.opt_bool(body, "family_history", False)
    for p in db.STORE["patients"].values():
        if p["external_ref"] == external_ref:
            raise errors.biz("ERR_DUPLICATE_PATIENT", 409, "A patient with the same external_ref already exists")
    ent = db.new_entity()
    ent.update({
        "external_ref": external_ref,
        "date_of_birth": date_of_birth,
        "risk_category": risk_category,
        "contraindication_flags": contraindication_flags,
        "recent_symptoms": recent_symptoms,
        "comorbidity": comorbidity,
        "family_history": family_history,
        "status": "ACTIVE",
    })
    db.STORE["patients"][ent["id"]] = ent
    return success_obj(ser.patient_view(ent), 201)


@bp.route("/patients", methods=["GET"])
def list_patients():
    _allowed({"ProgramAdmin", "Provider"})()
    limit, offset = helpers.get_limit_offset()
    external_ref = request.args.get("external_ref")
    items = list(db.STORE["patients"].values())
    if external_ref is not None:
        items = [p for p in items if p["external_ref"] == external_ref]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    window = items[offset:offset + limit]
    return success_list([ser.patient_view(p) for p in window], limit, offset, total)


@bp.route("/patients/<patientId>", methods=["GET"])
def get_patient(patientId):
    _allowed({"ProgramAdmin", "Provider"})()
    p = _get_or_404("patients", patientId)
    return success_obj(ser.patient_view(p))


@bp.route("/patients/<patientId>/opt-out", methods=["POST"])
def opt_out_patient(patientId):
    _allowed({"ProgramAdmin"})()
    patient = _get_or_404("patients", patientId)
    helpers.get_body()
    patient["status"] = "OPTED_OUT"
    db.touch(patient)
    affected_programs = set()
    for cohort in db.STORE["cohorts"].values():
        if cohort["patient_id"] == patientId and cohort["status"] in ("ELIGIBLE", "OUTREACH_SENT"):
            cohort["attributed"] = False
            cohort["status"] = "EXCLUDED"
            db.touch(cohort)
            affected_programs.add(cohort["program_id"])
    for pid in affected_programs:
        _recompute_and_touch_program(pid)
    return success_obj(ser.patient_view(patient))


@bp.route("/patients/<patientId>/risk-score", methods=["GET"])
def risk_score(patientId):
    _allowed({"ProgramAdmin", "Provider"})()
    p = _get_or_404("patients", patientId)
    score = (5 if p["recent_symptoms"] else 0) + (3 if p["comorbidity"] else 0) + (2 if p["family_history"] else 0)
    recommended = "CLINIC" if score >= 6 else "HOME_KIT_OK"
    return success_obj({"score": score, "recommended_channel": recommended})


# =========================================================================
# Providers
# =========================================================================
@bp.route("/providers", methods=["POST"])
def create_provider():
    _allowed({"ProgramAdmin"})()
    body = helpers.get_body()
    npi = helpers.req_str(body, "npi")
    display_name = helpers.req_str(body, "display_name")
    channel = helpers.req_enum(body, "channel", {"ORDERING", "TELEHEALTH"})
    is_active = helpers.opt_bool(body, "is_active", True)
    ent = db.new_entity()
    ent.update({
        "npi": npi,
        "display_name": display_name,
        "channel": channel,
        "is_active": is_active,
    })
    db.STORE["providers"][ent["id"]] = ent
    return success_obj(ser.provider_view(ent), 201)


@bp.route("/providers/<providerId>", methods=["GET"])
def get_provider(providerId):
    _allowed(ALL_ROLES)()
    p = _get_or_404("providers", providerId)
    return success_obj(ser.provider_view(p))


# =========================================================================
# Orders
# =========================================================================
@bp.route("/orders", methods=["POST"])
def create_order():
    _allowed({"ProgramAdmin", "Provider"})()
    body = helpers.get_body()
    patient_id = helpers.req_str(body, "patient_id")
    provider_id = helpers.req_str(body, "provider_id")
    program_id = helpers.opt_str(body, "program_id")
    cohort_id = helpers.opt_str(body, "cohort_id")
    patient = db.STORE["patients"].get(patient_id)
    if patient is None:
        raise errors.not_found("patient not found")
    provider = db.STORE["providers"].get(provider_id)
    if provider is None:
        raise errors.not_found("provider not found")
    if not provider["is_active"]:
        raise errors.biz("ERR_PROVIDER_INACTIVE", 422, "Provider is not active")
    cohort = None
    if program_id is not None:
        program = db.STORE["programs"].get(program_id)
        if program is None:
            raise errors.not_found("program not found")
    if cohort_id is not None:
        cohort = db.STORE["cohorts"].get(cohort_id)
        if cohort is None:
            raise errors.not_found("cohort not found")
    if (program_id is None) != (cohort_id is None):
        raise errors.biz("ERR_COHORT_PROGRAM_MISMATCH", 422,
                         "program_id and cohort_id must be supplied together")
    if cohort is not None and cohort["program_id"] != program_id:
        raise errors.biz("ERR_COHORT_PROGRAM_MISMATCH", 422,
                         "cohort does not belong to the named program")
    ent = db.new_entity()
    ent.update({
        "patient_id": patient_id,
        "provider_id": provider_id,
        "program_id": program_id,
        "cohort_id": cohort_id,
        "order_channel": provider["channel"],
        "status": "PENDING_ELIGIBILITY",
        "eligible_at": None,
        "shipped_at": None,
        "returned_at": None,
        "abandonment_due_at": None,
        "recollection_round": 0,
        "active_kit_id": None,
        "quality_outcome": "UNRESOLVED",
    })
    db.STORE["orders"][ent["id"]] = ent
    return success_obj(ser.order_view(ent), 201)


@bp.route("/orders", methods=["GET"])
def list_orders():
    _allowed(ALL_ROLES)()
    limit, offset = helpers.get_limit_offset()
    items = list(db.STORE["orders"].values())
    for f in ("patient_id", "status", "provider_id", "program_id", "cohort_id"):
        v = request.args.get(f)
        if v is not None:
            items = [o for o in items if o.get(f) == v]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    window = items[offset:offset + limit]
    return success_list([ser.order_view(o) for o in window], limit, offset, total)


@bp.route("/orders/<orderId>", methods=["GET"])
def get_order(orderId):
    _allowed(ALL_ROLES)()
    o = _get_or_404("orders", orderId)
    return success_obj(ser.order_view(o))


def _age_on(dob_str, ref_date):
    dob = db.parse_date(dob_str)
    age = ref_date.year - dob.year
    if (ref_date.month, ref_date.day) < (dob.month, dob.day):
        age -= 1
    return age


@bp.route("/orders/<orderId>/eligibility/confirm", methods=["POST"])
def confirm_eligibility(orderId):
    _allowed({"ProgramAdmin"})()
    order = _get_or_404("orders", orderId)
    helpers.get_body()
    if order["status"] != "PENDING_ELIGIBILITY":
        raise errors.biz("ERR_ORDER_INVALID_STATE", 409, "Order not in PENDING_ELIGIBILITY")
    patient = db.STORE["patients"].get(order["patient_id"])
    if patient is None or patient["status"] != "ACTIVE":
        raise errors.biz("ERR_PATIENT_NOT_ACTIVE", 422, "Patient is not ACTIVE")
    age = _age_on(patient["date_of_birth"], db.date_of(order["created_at"]))
    if age < db.MIN_AGE or age > db.MAX_AGE:
        raise errors.biz("ERR_AGE_OUT_OF_RANGE", 422, "Patient age outside [45, 75]")
    if patient["risk_category"] == "HIGH":
        raise errors.biz("ERR_RISK_CATEGORY_EXCLUDED", 422, "risk_category HIGH requires a different test")
    if len(patient["contraindication_flags"]) > 0:
        raise errors.biz("ERR_CONTRAINDICATION_PRESENT", 422, "contraindication_flags non-empty")
    order["status"] = "ELIGIBLE"
    order["eligible_at"] = db.now()
    db.touch(order)
    return success_obj(ser.order_view(order))


@bp.route("/orders/<orderId>/eligibility/reject", methods=["POST"])
def reject_eligibility(orderId):
    _allowed({"ProgramAdmin"})()
    order = _get_or_404("orders", orderId)
    helpers.get_body()
    if order["status"] != "PENDING_ELIGIBILITY":
        raise errors.biz("ERR_ORDER_INVALID_STATE", 409, "Order not in PENDING_ELIGIBILITY")
    order["status"] = "REJECTED_INELIGIBLE"
    db.touch(order)
    return success_obj(ser.order_view(order))


@bp.route("/orders/<orderId>/cancel", methods=["POST"])
def cancel_order(orderId):
    _allowed({"ProgramAdmin", "Provider"})()
    order = _get_or_404("orders", orderId)
    helpers.get_body()
    if order["status"] not in ("PENDING_ELIGIBILITY", "ELIGIBLE"):
        raise errors.biz("ERR_ORDER_NOT_CANCELLABLE", 409,
                         "Cancel attempted from a state other than PENDING_ELIGIBILITY or ELIGIBLE")
    order["status"] = "CANCELLED"
    db.touch(order)
    return success_obj(ser.order_view(order))


@bp.route("/orders/<orderId>/kit", methods=["POST"])
def create_kit(orderId):
    _allowed({"FulfillmentAgent"})()
    order = _get_or_404("orders", orderId)
    body = helpers.get_body()
    expected = helpers.req_int(body, "expected_order_version")
    # PRD §2.7/§2.9: the state precondition runs before the OCC version check.
    if order["status"] not in ("ELIGIBLE", "RECOLLECTION_REQUESTED"):
        raise errors.biz("ERR_ORDER_INVALID_STATE", 409, "Order not in ELIGIBLE or RECOLLECTION_REQUESTED")
    if expected != order["version"]:
        raise errors.biz("ERR_STALE_VERSION", 412, "expected_order_version does not match current order version")
    if order["status"] == "ELIGIBLE":
        for other in db.STORE["orders"].values():
            if other["id"] != order["id"] and other["patient_id"] == order["patient_id"] \
                    and other["status"] in services.IN_FLIGHT_ORDER_STATUSES:
                raise errors.biz("ERR_ACTIVE_ORDER_EXISTS", 409,
                                 "Another in-flight order exists for the same patient")
    kit = db.new_entity()
    kit.update({
        "order_id": order["id"],
        "kit_serial": "KIT-" + db.new_id()[:8].upper(),
        "shipped_at": None,
        "returned_at": None,
        "stabilization_expires_at": None,
        "status": "ORDERED",
    })
    db.STORE["kits"][kit["id"]] = kit
    order["active_kit_id"] = kit["id"]
    order["abandonment_due_at"] = None
    order["status"] = "KIT_ORDERED"
    db.touch(order)
    if order.get("cohort_id"):
        cohort = db.STORE["cohorts"].get(order["cohort_id"])
        if cohort is not None and cohort["status"] in ("ELIGIBLE", "OUTREACH_SENT"):
            cohort["status"] = "ORDERED"
            db.touch(cohort)
            _recompute_and_touch_program(cohort["program_id"])
    return success_obj(ser.kit_view(kit), 201)


@bp.route("/orders/<orderId>/kits", methods=["GET"])
def list_order_kits(orderId):
    _allowed({"ProgramAdmin", "Provider", "LabTechnician", "FulfillmentAgent"})()
    _get_or_404("orders", orderId)
    limit, offset = helpers.get_limit_offset()
    items = [k for k in db.STORE["kits"].values() if k["order_id"] == orderId]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    window = items[offset:offset + limit]
    return success_list([ser.kit_view(k) for k in window], limit, offset, total)


@bp.route("/orders/<orderId>/reminders", methods=["GET"])
def list_order_reminders(orderId):
    _allowed({"ProgramAdmin", "FulfillmentAgent"})()
    _get_or_404("orders", orderId)
    limit, offset = helpers.get_limit_offset()
    items = [r for r in db.STORE["reminders"].values() if r["order_id"] == orderId]
    items.sort(key=lambda e: (e["created_at"], e["sequence_no"]))
    total = len(items)
    window = items[offset:offset + limit]
    return success_list([ser.reminder_view(r) for r in window], limit, offset, total)


@bp.route("/orders/<orderId>/reminders/dispatch", methods=["POST"])
def dispatch_reminders(orderId):
    _allowed({"ProgramAdmin"})()
    order = _get_or_404("orders", orderId)
    helpers.get_body()
    if order["status"] != "KIT_SHIPPED":
        raise errors.biz("ERR_ORDER_INVALID_STATE", 409, "Order not in KIT_SHIPPED")
    today = db.date_of(db.now())
    due = [r for r in db.STORE["reminders"].values()
           if r["order_id"] == orderId and r["status"] == "SCHEDULED" and r["scheduled_for"] <= today]
    due.sort(key=lambda r: (r["scheduled_for"], r["sequence_no"]))
    for r in due:
        r["status"] = "SENT"
        r["sent_at"] = db.now()
    return success_obj([ser.reminder_view(r) for r in due])


@bp.route("/orders/<orderId>/sla", methods=["GET"])
def order_sla(orderId):
    _allowed({"ProgramAdmin", "Provider", "FulfillmentAgent"})()
    order = _get_or_404("orders", orderId)
    if order["shipped_at"] is None:
        provisional = 0
        return_logistics = 0
    else:
        ship_date = db.date_of(order["shipped_at"])
        if order["returned_at"] is not None:
            ret_date = db.date_of(order["returned_at"])
            provisional = (ret_date - ship_date).days
            return_logistics = provisional
        else:
            provisional = (db.date_of(db.now()) - ship_date).days
            return_logistics = db.KIT_ABANDON_DAYS
    return success_obj({"provisional_days": provisional, "return_logistics_days": return_logistics})


@bp.route("/orders/<orderId>/results", methods=["GET"])
def list_order_results(orderId):
    _allowed({"ProgramAdmin", "Provider", "LabTechnician", "Navigator"})()
    _get_or_404("orders", orderId)
    limit, offset = helpers.get_limit_offset()
    items = [r for r in db.STORE["results"].values() if r["order_id"] == orderId]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    window = items[offset:offset + limit]
    return success_list([ser.result_view(r) for r in window], limit, offset, total)


@bp.route("/orders/<orderId>/specimens", methods=["POST"])
def accession_specimen(orderId):
    _allowed({"LabTechnician"})()
    order = _get_or_404("orders", orderId)
    helpers.get_body()
    if order["status"] != "KIT_RETURNED":
        raise errors.biz("ERR_ORDER_INVALID_STATE", 409, "Order not in KIT_RETURNED")
    kit = db.STORE["kits"].get(order["active_kit_id"]) if order["active_kit_id"] else None
    if kit is None:
        raise errors.biz("ERR_ORDER_INVALID_STATE", 409, "No active kit for the order")
    sp = db.new_entity()
    sp.update({
        "kit_id": kit["id"],
        "order_id": order["id"],
        "accessioned_at": db.now(),
        "adequacy": "PENDING",
        "adequacy_checked_at": None,
        "processing_started_at": None,
        "status": "ACCESSIONED",
    })
    db.STORE["specimens"][sp["id"]] = sp
    order["status"] = "IN_LAB"
    db.touch(order)
    # PRD §4: accession creates a new LabSpecimen resource → 201.
    return success_obj(ser.specimen_view(sp), 201)


# =========================================================================
# Kits
# =========================================================================
@bp.route("/kits", methods=["GET"])
def list_kits():
    _allowed({"ProgramAdmin", "Provider", "LabTechnician", "FulfillmentAgent"})()
    limit, offset = helpers.get_limit_offset()
    order_id = request.args.get("order_id")
    status_f = request.args.get("status")
    items = list(db.STORE["kits"].values())
    if order_id is not None:
        items = [k for k in items if k["order_id"] == order_id]
    if status_f is not None:
        items = [k for k in items if k["status"] == status_f]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    window = items[offset:offset + limit]
    return success_list([ser.kit_view(k) for k in window], limit, offset, total)


@bp.route("/kits/<kitId>", methods=["GET"])
def get_kit(kitId):
    _allowed({"ProgramAdmin", "Provider", "LabTechnician", "FulfillmentAgent"})()
    kit = _get_or_404("kits", kitId)
    return success_obj(ser.kit_view(kit))


@bp.route("/kits/<kitId>/ship", methods=["POST"])
def ship_kit(kitId):
    _allowed({"FulfillmentAgent"})()
    kit = _get_or_404("kits", kitId)
    helpers.get_body()
    if kit["status"] != "ORDERED":
        raise errors.biz("ERR_KIT_INVALID_STATE", 409, "Kit not in ORDERED status")
    order = db.STORE["orders"].get(kit["order_id"])
    if order is None or order["status"] != "KIT_ORDERED":
        raise errors.biz("ERR_ORDER_INVALID_STATE", 409, "Order not in KIT_ORDERED")
    now = db.now()
    kit["status"] = "SHIPPED"
    kit["shipped_at"] = now
    db.touch(kit)
    ship_date = db.date_of(now)
    order["status"] = "KIT_SHIPPED"
    order["shipped_at"] = now
    order["abandonment_due_at"] = db.add_days(ship_date, db.KIT_ABANDON_DAYS)
    db.touch(order)
    for seq, off in db.REMINDER_OFFSETS.items():
        rem = {
            "id": db.new_id(),
            "order_id": order["id"],
            "sequence_no": seq,
            "channel": "MAIL",
            "scheduled_for": db.add_days(ship_date, off),
            "sent_at": None,
            "status": "SCHEDULED",
            "created_at": now,
        }
        db.STORE["reminders"][rem["id"]] = rem
    return success_obj(ser.kit_view(kit))


@bp.route("/kits/<kitId>/return", methods=["POST"])
def return_kit(kitId):
    _allowed({"FulfillmentAgent"})()
    kit = _get_or_404("kits", kitId)
    helpers.get_body()
    if kit["status"] != "SHIPPED":
        raise errors.biz("ERR_KIT_INVALID_STATE", 409, "Kit not in SHIPPED status")
    order = db.STORE["orders"].get(kit["order_id"])
    if order is None or order["status"] != "KIT_SHIPPED":
        raise errors.biz("ERR_ORDER_INVALID_STATE", 409, "Order not in KIT_SHIPPED")
    now = db.now()
    kit["status"] = "RETURNED"
    kit["returned_at"] = now
    kit["stabilization_expires_at"] = db.add_hours(now, db.STABILIZATION_HOURS)
    db.touch(kit)
    order["status"] = "KIT_RETURNED"
    order["returned_at"] = now
    db.touch(order)
    for rem in db.STORE["reminders"].values():
        if rem["order_id"] == order["id"] and rem["status"] == "SCHEDULED":
            rem["status"] = "SKIPPED"
    return success_obj(ser.kit_view(kit))


@bp.route("/kits/<kitId>/specimens", methods=["GET"])
def list_kit_specimens(kitId):
    _allowed({"ProgramAdmin", "LabTechnician"})()
    _get_or_404("kits", kitId)
    limit, offset = helpers.get_limit_offset()
    items = [s for s in db.STORE["specimens"].values() if s["kit_id"] == kitId]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    window = items[offset:offset + limit]
    return success_list([ser.specimen_view(s) for s in window], limit, offset, total)


# =========================================================================
# Specimens
# =========================================================================
@bp.route("/specimens", methods=["GET"])
def list_specimens():
    _allowed({"ProgramAdmin", "LabTechnician"})()
    limit, offset = helpers.get_limit_offset()
    kit_id = request.args.get("kit_id")
    status_f = request.args.get("status")
    items = list(db.STORE["specimens"].values())
    if kit_id is not None:
        items = [s for s in items if s["kit_id"] == kit_id]
    if status_f is not None:
        items = [s for s in items if s["status"] == status_f]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    window = items[offset:offset + limit]
    return success_list([ser.specimen_view(s) for s in window], limit, offset, total)


@bp.route("/specimens/<specimenId>", methods=["GET"])
def get_specimen(specimenId):
    _allowed({"ProgramAdmin", "LabTechnician"})()
    sp = _get_or_404("specimens", specimenId)
    return success_obj(ser.specimen_view(sp))


@bp.route("/specimens/<specimenId>/process", methods=["POST"])
def process_specimen(specimenId):
    _allowed({"LabTechnician"})()
    sp = _get_or_404("specimens", specimenId)
    helpers.get_body()
    if sp["status"] != "ACCESSIONED":
        raise errors.biz("ERR_SPECIMEN_INVALID_STATE", 409, "Specimen not in ACCESSIONED status")
    kit = db.STORE["kits"].get(sp["kit_id"])
    if kit is not None and kit["stabilization_expires_at"] is not None:
        if db.now() >= kit["stabilization_expires_at"]:
            raise errors.biz("ERR_STABILIZATION_EXPIRED", 422,
                             "Processing start at or after stabilization expiry")
    sp["status"] = "PROCESSING"
    sp["processing_started_at"] = db.now()
    db.touch(sp)
    if kit is not None:
        kit["status"] = "IN_PROCESSING"
        db.touch(kit)
    return success_obj(ser.specimen_view(sp))


@bp.route("/specimens/<specimenId>/adequacy", methods=["POST"])
def specimen_adequacy(specimenId):
    _allowed({"LabTechnician"})()
    sp = _get_or_404("specimens", specimenId)
    body = helpers.get_body()
    adequacy = helpers.req_enum(body, "adequacy", {"ADEQUATE", "INADEQUATE"})
    if sp["status"] not in ("ACCESSIONED", "PROCESSING"):
        raise errors.biz("ERR_SPECIMEN_INVALID_STATE", 409,
                         "Specimen not in ACCESSIONED or PROCESSING status")
    order = db.STORE["orders"].get(sp["order_id"])
    if adequacy == "ADEQUATE":
        sp["adequacy"] = "ADEQUATE"
        sp["adequacy_checked_at"] = db.now()
        db.touch(sp)
        return success_obj(ser.specimen_view(sp))
    # INADEQUATE
    if order is not None and order["recollection_round"] >= db.MAX_RECOLLECTIONS:
        raise errors.biz("ERR_RECOLLECTION_LIMIT_REACHED", 422,
                         "Recollection limit reached")
    sp["adequacy"] = "INADEQUATE"
    sp["adequacy_checked_at"] = db.now()
    sp["status"] = "INADEQUATE"
    db.touch(sp)
    kit = db.STORE["kits"].get(sp["kit_id"])
    if kit is not None:
        kit["status"] = "CONSUMED"
        db.touch(kit)
    if order is not None:
        order["active_kit_id"] = None
        order["recollection_round"] += 1
        order["status"] = "RECOLLECTION_REQUESTED"
        db.touch(order)
    return success_obj(ser.specimen_view(sp))


@bp.route("/specimens/<specimenId>/result", methods=["POST"])
def result_specimen(specimenId):
    _allowed({"LabTechnician"})()
    sp = _get_or_404("specimens", specimenId)
    body = helpers.get_body()
    outcome = helpers.req_enum(body, "outcome", {"NEGATIVE", "POSITIVE"})
    if sp["status"] != "PROCESSING":
        raise errors.biz("ERR_SPECIMEN_INVALID_STATE", 409, "Specimen not in PROCESSING status")
    if sp["adequacy"] != "ADEQUATE":
        raise errors.biz("ERR_SPECIMEN_NOT_ADEQUATE", 422, "Specimen adequacy is not ADEQUATE")
    order = db.STORE["orders"].get(sp["order_id"])
    now = db.now()
    sp["status"] = "RESULTED"
    db.touch(sp)
    kit = db.STORE["kits"].get(sp["kit_id"])
    if kit is not None:
        kit["status"] = "CONSUMED"
        db.touch(kit)
    result = {
        "id": db.new_id(),
        "order_id": sp["order_id"],
        "specimen_id": sp["id"],
        "resulted_at": now,
        "outcome": outcome,
        "delivered_to_provider_at": now,
        "navigation_due_at": None,
        "navigation_status": "NOT_REQUIRED",
        "navigation_completed_at": None,
        "created_at": now,
    }
    if outcome == "POSITIVE":
        result["navigation_status"] = "PENDING"
        result["navigation_due_at"] = db.add_days(db.date_of(now), db.NAVIGATION_WINDOW_DAYS)
    db.STORE["results"][result["id"]] = result
    if order is not None:
        order["active_kit_id"] = None
        order["status"] = "RESULTED"
        db.touch(order)
        services.update_order_quality_outcome(order)
        if order.get("cohort_id"):
            cohort = db.STORE["cohorts"].get(order["cohort_id"])
            if cohort is not None and cohort["status"] == "ORDERED":
                cohort["status"] = "SCREENED"
                db.touch(cohort)
                _recompute_and_touch_program(cohort["program_id"])
    return success_obj(ser.result_view(result), 201)


# =========================================================================
# Results / navigation
# =========================================================================
@bp.route("/results", methods=["GET"])
def list_results():
    _allowed({"ProgramAdmin", "Provider", "LabTechnician", "Navigator"})()
    limit, offset = helpers.get_limit_offset()
    order_id = request.args.get("order_id")
    specimen_id = request.args.get("specimen_id")
    items = list(db.STORE["results"].values())
    if order_id is not None:
        items = [r for r in items if r["order_id"] == order_id]
    if specimen_id is not None:
        items = [r for r in items if r["specimen_id"] == specimen_id]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    window = items[offset:offset + limit]
    return success_list([ser.result_view(r) for r in window], limit, offset, total)


@bp.route("/results/<resultId>", methods=["GET"])
def get_result(resultId):
    _allowed({"ProgramAdmin", "Provider", "LabTechnician", "Navigator"})()
    r = _get_or_404("results", resultId)
    return success_obj(ser.result_view(r))


@bp.route("/results/<resultId>/navigation/schedule", methods=["POST"])
def schedule_navigation(resultId):
    _allowed({"Navigator"})()
    r = _get_or_404("results", resultId)
    helpers.get_body()
    if r["outcome"] != "POSITIVE":
        raise errors.biz("ERR_NAVIGATION_NOT_REQUIRED", 422, "Navigation not required for this result")
    if r["navigation_status"] != "PENDING":
        raise errors.biz("ERR_NAVIGATION_INVALID_STATE", 409, "Navigation not in PENDING status")
    r["navigation_status"] = "SCHEDULED"
    return success_obj(ser.result_view(r))


@bp.route("/results/<resultId>/navigation/complete", methods=["POST"])
def complete_navigation(resultId):
    _allowed({"Navigator"})()
    r = _get_or_404("results", resultId)
    helpers.get_body()
    if r["outcome"] != "POSITIVE":
        raise errors.biz("ERR_NAVIGATION_NOT_REQUIRED", 422, "Navigation not required for this result")
    if r["navigation_status"] != "SCHEDULED":
        raise errors.biz("ERR_NAVIGATION_INVALID_STATE", 409, "Navigation not in SCHEDULED status")
    r["navigation_status"] = "COMPLETED"
    r["navigation_completed_at"] = db.now()
    order = db.STORE["orders"].get(r["order_id"])
    if order is not None:
        services.update_order_quality_outcome(order, bump_version=True)
    return success_obj(ser.result_view(r))
