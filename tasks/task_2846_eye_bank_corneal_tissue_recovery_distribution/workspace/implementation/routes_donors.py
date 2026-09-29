"""Donor referral, screening, consent, deferral, reinstatement and release."""

from flask import Blueprint, request

import auth
import calc
import cascade
import envelope
import serialize
import store
import validate
from errors import ApiError

bp = Blueprint("donors", __name__)

REFERRAL_SOURCES = ("HOSPITAL", "HOSPICE", "MEDICAL_EXAMINER", "FUNERAL_HOME")
DEATH_TIME_BASES = ("ASYSTOLE", "PRONOUNCED")
CAUSE_CATEGORIES = (
    "CARDIAC",
    "TRAUMA",
    "MALIGNANCY",
    "NEUROLOGIC",
    "INFECTIOUS",
    "OTHER",
)
DONOR_STATUSES = (
    "REFERRED",
    "SCREENING",
    "CONSENT_OBTAINED",
    "APPROVED_FOR_RECOVERY",
    "RECOVERED",
    "DEFERRED",
    "RULED_OUT",
)
CONSENT_TYPES = ("NONE", "FIRST_PERSON", "NEXT_OF_KIN")
CONSENT_SCOPES = (
    "NONE",
    "TRANSPLANT_ONLY",
    "TRANSPLANT_AND_RESEARCH",
    "RESEARCH_ONLY",
    "TRAINING_ONLY",
)
QUESTION_CODES = (
    "IV_DRUG_USE",
    "HIV_RISK",
    "HEP_B_C_HISTORY",
    "SEPSIS",
    "UNEXPLAINED_NEURO",
    "CJD_FAMILY",
    "TATTOO_12M",
    "INCARCERATION_12M",
)
RESPONSES = ("YES", "NO", "UNKNOWN")
HISTORIAN_RELATIONSHIPS = (
    "SPOUSE",
    "CHILD",
    "PARENT",
    "SIBLING",
    "MEDICAL_RECORD",
    "OTHER",
)


@bp.post("/eye-bank/donors")
def create_donor():
    auth.authenticate(("EyeBankCoordinator",))
    body = auth.body_dict()

    donor_code = validate.req_str(body, "donor_code", 1, 32)
    referral_source = validate.req_enum(body, "referral_source", REFERRAL_SOURCES)
    death_at = validate.req_dt(body, "death_at")
    death_time_basis = validate.req_enum(body, "death_time_basis", DEATH_TIME_BASES)
    body_cooled_at = validate.opt_dt(body, "body_cooled_at")
    age_years = validate.req_int(body, "age_years", 0, 110)
    cause = validate.req_enum(body, "cause_of_death_category", CAUSE_CATEGORIES)
    if body_cooled_at is not None and body_cooled_at < death_at:
        raise ApiError("ERR_INVALID_REQUEST", "body_cooled_at must not precede death_at.")

    if death_at > store.now():
        raise ApiError("ERR_DEATH_TIME_IN_FUTURE", "death_at is later than the current instant.")

    for existing in store.DB["donors"].values():
        if existing["donor_code"] == donor_code:
            raise ApiError("ERR_DUPLICATE_DONOR_CODE", "donor_code is already in use.")

    row = store.base_row()
    row.update(
        {
            "donor_code": donor_code,
            "referral_source": referral_source,
            "death_at": death_at,
            "death_time_basis": death_time_basis,
            "body_cooled_at": body_cooled_at,
            "age_years": age_years,
            "cause_of_death_category": cause,
            "status": "REFERRED",
            "consent_type": "NONE",
            "consent_scope": "NONE",
            "authorizing_party_name": None,
            "consent_obtained_at": None,
            "recovery_window_minutes": 0,
            "recovery_deadline_at": None,
            "screening_risk_score": 0,
            "screening_risk_variant": "INTERVIEW_ONLY",
            "serology_status": "PENDING",
            "deferral_reason": None,
            "lookback_flag": False,
            "tissues_recovered_count": 0,
        }
    )
    calc.apply_recovery_window(row)
    store.DB["donors"][row["id"]] = row
    return envelope.ok(serialize.donor(row), 201)


@bp.get("/eye-bank/donors/<donor_id>")
def get_donor(donor_id):
    auth.authenticate(
        (
            "EyeBankCoordinator",
            "LabTechnician",
            "MedicalDirector",
            "RecoveryTechnician",
            "EvaluationTechnician",
        )
    )
    donor = validate.lookup("donors", donor_id)
    return envelope.ok(serialize.donor(donor))


@bp.get("/eye-bank/donors")
def list_donors():
    auth.authenticate(("EyeBankCoordinator", "LabTechnician", "MedicalDirector"))
    rows = list(store.DB["donors"].values())
    status = request.args.get("status")
    if status is not None:
        validate.filter_enum("status", status, DONOR_STATUSES)
        rows = [r for r in rows if r["status"] == status]
    flag = request.args.get("lookback_flag")
    if flag is not None:
        wanted = validate.filter_bool("lookback_flag", flag)
        rows = [r for r in rows if r["lookback_flag"] is wanted]
    rows = store.sort_desc(rows, lambda r: r["created_at"])
    return envelope.paginated(rows, serialize.donor)


@bp.post("/eye-bank/donors/<donor_id>/screening-records")
def create_screening_record(donor_id):
    actor = auth.authenticate(("EyeBankCoordinator",))
    donor = validate.lookup("donors", donor_id)
    body = auth.body_dict()

    question_code = validate.req_enum(body, "question_code", QUESTION_CODES)
    response = validate.req_enum(body, "response", RESPONSES)
    relationship = validate.req_enum(body, "historian_relationship", HISTORIAN_RELATIONSHIPS)

    for existing in store.DB["screening_records"].values():
        if existing["donor_id"] == donor_id and existing["question_code"] == question_code:
            raise ApiError(
                "ERR_DUPLICATE_SCREENING_ANSWER",
                "This question has already been answered for the donor.",
            )

    row = store.base_row(with_version=False)
    row.update(
        {
            "donor_id": donor_id,
            "question_code": question_code,
            "response": response,
            "historian_relationship": relationship,
            "recorded_by_user_id": actor.user_id,
            "weight_applied": 0,
        }
    )
    store.DB["screening_records"][row["id"]] = row

    if donor["status"] == "REFERRED":
        donor["status"] = "SCREENING"
    calc.recompute_screening_risk(donor)
    store.touch(donor)

    return envelope.ok(serialize.screening_record(row), 201)


@bp.get("/eye-bank/donors/<donor_id>/screening-records")
def list_screening_records(donor_id):
    auth.authenticate(("EyeBankCoordinator", "LabTechnician", "MedicalDirector"))
    validate.lookup("donors", donor_id)
    rows = calc.donor_screening_records(donor_id)
    return envelope.nested_list(rows, serialize.screening_record)


@bp.post("/eye-bank/donors/<donor_id>/consent")
def record_consent(donor_id):
    auth.authenticate(("EyeBankCoordinator",))
    donor = validate.lookup("donors", donor_id)
    body = auth.body_dict()

    consent_type = validate.req_enum(body, "consent_type", CONSENT_TYPES)
    consent_scope = validate.req_enum(body, "consent_scope", CONSENT_SCOPES)
    authorizing_party_name = validate.opt_str(body, "authorizing_party_name", 1, 120)
    if consent_scope == "NONE":
        raise ApiError("ERR_INVALID_REQUEST", "consent_scope NONE may not be submitted.")

    if donor["status"] != "SCREENING":
        raise ApiError("ERR_DONOR_STATE_INVALID", "Consent requires a donor in SCREENING.")

    donor["consent_type"] = consent_type
    donor["consent_scope"] = consent_scope
    donor["authorizing_party_name"] = authorizing_party_name
    donor["consent_obtained_at"] = store.now()
    donor["status"] = "CONSENT_OBTAINED"
    store.touch(donor)
    return envelope.ok(serialize.donor(donor))


@bp.post("/eye-bank/donors/<donor_id>/defer")
def defer_donor(donor_id):
    auth.authenticate(("EyeBankCoordinator", "MedicalDirector"))
    donor = validate.lookup("donors", donor_id)
    body = auth.body_dict()
    deferral_reason = validate.req_str(body, "deferral_reason", 1, 500)

    if donor["status"] not in ("SCREENING", "CONSENT_OBTAINED", "APPROVED_FOR_RECOVERY"):
        raise ApiError("ERR_DONOR_STATE_INVALID", "This donor status cannot be deferred.")

    donor["deferral_reason"] = deferral_reason
    donor["status"] = "DEFERRED"
    store.touch(donor)

    live = [
        r
        for r in store.DB["recoveries"].values()
        if r["donor_id"] == donor_id and r["status"] in ("DISPATCHED", "ON_SITE")
    ]
    for recovery in store.by_created(live):
        recovery["status"] = "ABORTED"
        recovery["abort_reason"] = "DONOR_DEFERRED"
        calc.refresh_occupation(recovery)
        store.touch(recovery)
        technician = store.DB["technicians"].get(recovery["technician_id"])
        if technician is not None:
            technician["open_dispatch_count"] = max(0, technician["open_dispatch_count"] - 1)
            store.touch(technician)

    return envelope.ok(serialize.donor(donor))


@bp.post("/eye-bank/donors/<donor_id>/reinstate")
def reinstate_donor(donor_id):
    auth.authenticate(("MedicalDirector",))
    donor = validate.lookup("donors", donor_id)

    if donor["status"] != "DEFERRED":
        raise ApiError("ERR_DONOR_STATE_INVALID", "Only a DEFERRED donor may be reinstated.")
    if donor["serology_status"] == "REACTIVE":
        raise ApiError("ERR_SEROLOGY_REACTIVE", "A reactive donor may not be reinstated.")

    donor["deferral_reason"] = None
    donor["status"] = "SCREENING"
    store.touch(donor)
    return envelope.ok(serialize.donor(donor))


@bp.post("/eye-bank/donors/<donor_id>/approve-recovery")
def approve_recovery(donor_id):
    auth.authenticate(("MedicalDirector",))
    donor = validate.lookup("donors", donor_id)

    if donor["status"] != "CONSENT_OBTAINED":
        raise ApiError("ERR_DONOR_STATE_INVALID", "Approval requires CONSENT_OBTAINED.")
    if donor["serology_status"] == "REACTIVE":
        raise ApiError("ERR_SEROLOGY_REACTIVE", "A reactive donor may not be approved.")
    if store.now() >= donor["recovery_deadline_at"]:
        raise ApiError(
            "ERR_PRESERVATION_WINDOW_EXCEEDED",
            "The donor's recovery window has already closed.",
        )

    donor["status"] = "APPROVED_FOR_RECOVERY"
    store.touch(donor)
    return envelope.ok(serialize.donor(donor))
