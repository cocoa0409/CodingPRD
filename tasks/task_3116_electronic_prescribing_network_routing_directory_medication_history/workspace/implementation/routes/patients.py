"""Patient, PatientConsent, MedicationHistoryRecord and MedicationHistoryBatch routes."""

from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import serializers
from clock import ok, parse_dt
from errors import ApiError, ERR_HISTORY_SOURCE_UNCERTIFIED, ERR_HISTORY_BATCH_IN_PROGRESS, ERR_INVALID_REQUEST
from request_context import (
    _is_history_record_route,
    actor,
    allowed,
    body,
    created_order,
    enum_value,
    int_value,
    need_consent,
    need_participant,
    need_patient,
    page_args,
    paginate,
    same_resource,
    string_value,
)
from services import history, routing

bp = Blueprint("patients", __name__)

CONSENT_SCOPES = ("MEDICATION_HISTORY", "BENEFIT_CHECK", "BOTH")
PATIENT_LISTER_ROLES = ["PatientService", "Prescriber", "NetworkOperator"]
HISTORY_SOURCE_TYPES = ("PHARMACY_FILL", "PAYER_CLAIM")
TRIGGER_REASONS = ("PRESCRIBER_QUERY", "CONSENT_GRANT", "SCHEDULED_REFRESH")


@bp.post("/network/patients")
def register_patient():
    role, _ = actor()
    allowed(role, ["PatientService", "Prescriber"])
    payload = body(
        required=("full_name", "date_of_birth", "home_state"),
        optional=("covered_plan_payer_id", "discard_on_revoke"),
    )
    full_name = string_value(payload["full_name"], "full_name")
    date_of_birth = parse_dt(payload["date_of_birth"], "date_of_birth")
    home_state = string_value(payload["home_state"], "home_state")
    covered_plan_payer_id = payload.get("covered_plan_payer_id")
    if covered_plan_payer_id is not None:
        payer = db.get("participants", covered_plan_payer_id)
        if payer is None:
            raise ApiError("ERR_PARTICIPANT_NOT_FOUND")
    discard_on_revoke = payload.get("discard_on_revoke", False)
    if not isinstance(discard_on_revoke, bool):
        raise ApiError(ERR_INVALID_REQUEST, "'discard_on_revoke' must be a boolean.")

    row = db.new_resource()
    row.update({
        "full_name": full_name,
        "date_of_birth": clock.now_iso(date_of_birth),
        "home_state": home_state,
        "covered_plan_payer_id": covered_plan_payer_id,
        "discard_on_revoke": discard_on_revoke,
        "consent_status": "NONE",
        "consent_version": 0,
        "history_record_count": 0,
    })
    db.add("patients", row)
    return ok(serializers.patient(row), status=201)


@bp.get("/network/patients")
def list_patients():
    role, _ = actor()
    allowed(role, PATIENT_LISTER_ROLES)
    limit, offset = page_args()
    rows = db.all_rows("patients")
    for field in ("home_state", "consent_status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    rows = created_order(rows)
    window, meta = paginate(rows, limit, offset)
    return ok([serializers.patient(p) for p in window], **meta)


@bp.get("/network/patients/<pid>")
def get_patient(pid):
    role, _ = actor()
    allowed(role, PATIENT_LISTER_ROLES)
    patient = need_patient(pid)
    return ok(serializers.patient(patient))


@bp.post("/network/patients/<pid>/consents")
def grant_consent(pid):
    role, _ = actor()
    allowed(role, ["PatientService"])
    payload = body(required=("scope", "duration_days"), optional=())
    patient = need_patient(pid)
    scope = enum_value(payload["scope"], "scope", CONSENT_SCOPES)
    duration_days = int_value(payload["duration_days"], "duration_days", minimum=0)

    granted_at = clock.get_clock()
    expires_at = granted_at + timedelta(days=duration_days)
    now = clock.get_clock()
    status = "ACTIVE" if expires_at > now else "EXPIRED"
    # §3.8: "Only one `ACTIVE` window may exist at a time for a given patient and
    # scope, so a grant whose window intersects an existing `ACTIVE` window for the
    # same patient and scope is refused". The window is compared against the *current*
    # logical clock, so a grant already past its expiry intersects nothing and is
    # simply recorded as EXPIRED.
    if status == "ACTIVE" and history.overlapping_active_consent(
            patient["id"], scope, granted_at, expires_at) is not None:
        raise ApiError("ERR_CONSENT_INTERVAL_OVERLAP")

    row = db.new_resource()
    row.update({
        "patient_id": patient["id"],
        "scope": scope,
        "duration_days": duration_days,
        "status": status,
        "granted_at": clock.now_iso(granted_at),
        "expires_at": clock.now_iso(expires_at),
        "revoked_at": None,
    })
    db.add("consents", row)

    patient["consent_status"] = "GRANTED" if status == "ACTIVE" else "EXPIRED"
    patient["consent_version"] += 1
    db.touch(patient)
    history.recompute_monitored_prescriptions(patient["id"])
    return ok(serializers.consent(row), status=201)


@bp.post("/network/patients/<pid>/consents/revoke")
def revoke_consents(pid):
    role, _ = actor()
    allowed(role, ["PatientService"])
    body(required=(), optional=())
    patient = need_patient(pid)
    revoked = history.revoke_all(patient)
    if revoked:
        return ok(serializers.consent(revoked[0]))
    return ok({})


@bp.get("/network/patients/<pid>/consents")
def list_consents(pid):
    role, _ = actor()
    allowed(role, ["PatientService", "NetworkOperator"])
    patient = need_patient(pid)
    rows = created_order([c for c in db.all_rows("consents") if c["patient_id"] == patient["id"]])
    return ok([serializers.consent(c) for c in rows])


@bp.get("/network/consents/<cid>")
def get_consent(cid):
    role, _ = actor()
    allowed(role, ["PatientService", "NetworkOperator", "Prescriber"])
    consent = need_consent(cid)
    return ok(serializers.consent(consent))


# --------------------------------------------------------------------------
# Medication history records
# --------------------------------------------------------------------------

@bp.post("/network/patients/<pid>/history-records")
def submit_history_record(pid):
    role, user_id = actor()
    allowed(role, ["Pharmacy", "HubOperator"])
    payload = body(
        required=("source_type", "source_participant_id", "drug_ndc",
                  "fill_date", "days_supply", "quantity"),
        optional=(),
    )
    patient = need_patient(pid)
    source_type = enum_value(payload["source_type"], "source_type", HISTORY_SOURCE_TYPES)
    source = need_participant(payload["source_participant_id"], "source_participant_id")
    # §3.8: "A reporting organization that is not `CERTIFIED` has its submission
    # refused with `ERR_HISTORY_SOURCE_UNCERTIFIED`" — the reporting organization is
    # the one named as `source_participant_id`. A `Pharmacy` identity is entity-backed
    # (§2.1) so it answers for the source it names; a `HubOperator` identity is opaque
    # and may report on any source's behalf, which is how an uncertified source's
    # submission reaches the certification check at all.
    if (role == "Pharmacy" and user_id != source["id"]):
        raise ApiError("ERR_FORBIDDEN_ROLE")
    if source["certification_status"] != "CERTIFIED":
        raise ApiError(ERR_HISTORY_SOURCE_UNCERTIFIED)
    drug_ndc = string_value(payload["drug_ndc"], "drug_ndc")
    fill_date = parse_dt(payload["fill_date"], "fill_date")
    days_supply = int_value(payload["days_supply"], "days_supply", minimum=0)
    quantity = int_value(payload["quantity"], "quantity", minimum=0)

    row = db.new_resource()
    row.update({
        "patient_id": patient["id"],
        "source_type": source_type,
        "source_participant_id": source["id"],
        "drug_ndc": drug_ndc,
        "fill_date": fill_date,
        "days_supply": days_supply,
        "quantity": quantity,
        "dedupe_key": history.dedupe_key(patient["id"], drug_ndc, fill_date, days_supply),
        "is_superseded": False,
        "aggregation_batch_id": None,
        "retracted_at": None,
    })
    db.add("history_records", row)
    history.recompute_history_record_count(patient)
    return ok(serializers.history_record(row), status=201)


@bp.get("/network/history-records")
def list_history_records():
    role, _ = actor()
    allowed(role, ["NetworkOperator", "HubOperator", "Prescriber", "PatientService"])
    limit, offset = page_args()
    rows = db.all_rows("history_records")
    for field in ("patient_id", "source_participant_id", "source_type", "aggregation_batch_id"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    rows = created_order(rows)
    window, meta = paginate(rows, limit, offset)
    return ok([serializers.history_record(r) for r in window], **meta)


@bp.get("/network/history-records/<rid>")
def get_history_record(rid):
    role, _ = actor()
    allowed(role, ["NetworkOperator", "HubOperator", "Prescriber", "PatientService"])
    row = db.get("history_records", rid)
    if row is None:
        raise ApiError("ERR_PATIENT_NOT_FOUND", "The referenced medication history record does not exist.")
    return ok(serializers.history_record(row))


@bp.get("/network/patients/<pid>/history-records")
def patient_history_records(pid):
    role, _ = actor()
    allowed(role, ["Prescriber", "PatientService", "NetworkOperator"])
    limit, offset = page_args()
    patient = need_patient(pid)
    rows = [r for r in db.all_rows("history_records") if r["patient_id"] == patient["id"]]
    source_type = request.args.get("source_type")
    if source_type is not None:
        rows = [r for r in rows if r["source_type"] == source_type]
    rows = created_order(rows)
    window, meta = paginate(rows, limit, offset)
    return ok([serializers.history_record(r) for r in window], **meta)


# --------------------------------------------------------------------------
# Aggregation batches
# --------------------------------------------------------------------------

@bp.post("/network/medication-history/batches")
def open_batch():
    role, _ = actor()
    allowed(role, ["Prescriber", "HubOperator"])
    payload = body(required=("patient_id", "trigger_reason"), optional=())
    patient = need_patient(payload["patient_id"])
    trigger_reason = enum_value(payload["trigger_reason"], "trigger_reason", TRIGGER_REASONS)
    for existing in db.all_rows("batches"):
        if existing["patient_id"] == patient["id"] and existing["status"] == "AGGREGATING":
            raise ApiError(ERR_HISTORY_BATCH_IN_PROGRESS)

    row = db.new_resource()
    row.update({
        "patient_id": patient["id"],
        "trigger_reason": trigger_reason,
        "status": "PENDING",
        "subscription_generation": 0,
        "consent_version_snapshot": None,
        "source_record_count": 0,
        "record_count": 0,
        "superseded_count": 0,
        "batch_cost_cents": 0,
    })
    db.add("batches", row)
    return ok(serializers.batch(row), status=201)


@bp.get("/network/patients/<pid>/history-batches")
def patient_batches(pid):
    role, _ = actor()
    allowed(role, ["Prescriber", "NetworkOperator"])
    patient = need_patient(pid)
    rows = created_order([b for b in db.all_rows("batches") if b["patient_id"] == patient["id"]])
    return ok([serializers.batch(b) for b in rows])


@bp.get("/network/medication-history/batches/<bid>")
def get_batch(bid):
    role, _ = actor()
    allowed(role, ["Prescriber", "HubOperator", "NetworkOperator"])
    batch = db.get("batches", bid)
    if batch is None:
        raise ApiError("ERR_PATIENT_NOT_FOUND", "The referenced aggregation batch does not exist.")
    return ok(serializers.batch(batch))


@bp.get("/network/medication-history/batches/<bid>/history-records")
def batch_records(bid):
    role, _ = actor()
    allowed(role, ["NetworkOperator", "HubOperator", "Prescriber"])
    batch = db.get("batches", bid)
    if batch is None:
        raise ApiError("ERR_PATIENT_NOT_FOUND", "The referenced aggregation batch does not exist.")
    rows = created_order([r for r in db.all_rows("history_records")
                          if r.get("aggregation_batch_id") == batch["id"]])
    return ok([serializers.history_record(r) for r in rows])


@bp.post("/network/medication-history/batches/<bid>/aggregate")
def aggregate_batch(bid):
    role, _ = actor()
    allowed(role, ["HubOperator", "NetworkOperator"])
    body(required=(), optional=())
    batch = db.get("batches", bid)
    if batch is None:
        raise ApiError("ERR_PATIENT_NOT_FOUND", "The referenced aggregation batch does not exist.")
    # §3.8: a batch already settled as FAILED accepts no further work; the consent gate
    # itself is owned by the advance so that a PENDING batch blocked for want of consent
    # reports ERR_CONSENT_REQUIRED rather than a state error.
    if batch["status"] not in ("PENDING", "COMPLETE"):
        raise ApiError("ERR_INVALID_STATE")
    history.advance_batch(batch)
    return ok(serializers.batch(batch))


# --------------------------------------------------------------------------
# Patient-scoped collections
# --------------------------------------------------------------------------

@bp.get("/network/patients/<pid>/prescriptions")
def patient_prescriptions(pid):
    role, _ = actor()
    allowed(role, ["Prescriber", "Pharmacy", "NetworkOperator"])
    limit, offset = page_args()
    patient = need_patient(pid)
    rows = [p for p in db.all_rows("prescriptions") if p["patient_id"] == patient["id"]]
    rows = created_order(rows)
    window, meta = paginate(rows, limit, offset)
    return ok([serializers.prescription(p) for p in window], **meta)


@bp.get("/network/patients/<pid>/benefit-checks")
def patient_benefit_checks(pid):
    role, _ = actor()
    allowed(role, ["Prescriber", "Pharmacy", "NetworkOperator"])
    limit, offset = page_args()
    patient = need_patient(pid)
    rows = [b for b in db.all_rows("benefit_checks") if b["patient_id"] == patient["id"]]
    rows = created_order(rows)
    window, meta = paginate(rows, limit, offset)
    return ok([serializers.benefit_check(b) for b in window], **meta)