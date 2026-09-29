"""The provider dossier, its licence decisions and its risk read (PRD §3.2, §3.8)."""

from flask import Blueprint, request

import calc
import clock
import constants as K
import derive
import envelope
import helpers
import serialize
import store
import validate
from auth import authenticate, require_provider_owner
from errors import ApiError
from validate import F

bp = Blueprint("providers", __name__)

PROVIDER_READERS = (
    "AgencyAdmin",
    "Applicant",
    "LicensingSupervisor",
    "LicensingInspector",
    "ComplaintIntakeSpecialist",
    "ComplaintInvestigator",
    "PublicPortalReader",
)

PROVIDER_INPUT = [
    F("legal_name", "string", required=True, min_len=1, max_len=200, not_blank=True),
    F("county_code", "string", required=True, pattern=K.COUNTY_PATTERN),
    F("site_address", "string", required=True, min_len=1, max_len=300, not_blank=True),
    F("program_type", "enum", required=True, values=K.PROGRAM_TYPES),
    F("requested_capacity", "int", required=True, min_val=1),
]


@bp.post("/licensing/providers")
def create_provider():
    authenticate(
        ("Applicant", "AgencyAdmin"), require_user_id=False, resolve_identity=False
    )
    vals = validate.body(PROVIDER_INPUT)
    ceiling = K.PROGRAM_CAPACITY_CEILING[vals["program_type"]]
    if vals["requested_capacity"] > ceiling:
        raise ApiError(
            "ERR_CAPACITY_CEILING_EXCEEDED",
            "Requested capacity exceeds the statutory ceiling for this programme class.",
        )
    record = {
        "legal_name": vals["legal_name"],
        "county_code": vals["county_code"],
        "site_address": vals["site_address"],
        "program_type": vals["program_type"],
        "requested_capacity": vals["requested_capacity"],
        "capacity_ceiling": ceiling,
        "licensed_capacity": 0,
        "suspended_capacity": 0,
        "application_status": "DRAFT",
        "license_status": "NONE",
        "license_number": None,
        "licensed_at": None,
        "provisional_started_at": None,
        "open_violation_points": 0,
        "resolved_violation_points": 0,
        "lifetime_violation_points": 0,
        "critical_open_count": 0,
        "critical_violation_count_24mo": 0,
        "substantiated_complaint_count_24mo": 0,
        "inconclusive_complaint_count_24mo": 0,
        "risk_score": calc.rhu(0, 2),
        "risk_tier": "LOW",
        "current_ladder_step": 0,
        "probation_cycle_count": 0,
        "decision_reason": None,
    }
    store.create(store.providers, record)
    return envelope.created(serialize.provider(record))


@bp.get("/licensing/providers")
def list_providers():
    authenticate(
        (
            "AgencyAdmin",
            "LicensingSupervisor",
            "ComplaintIntakeSpecialist",
            "PublicPortalReader",
        )
    )
    limit, offset = envelope.pagination(request.args)
    program_type = validate.query_enum("program_type", K.PROGRAM_TYPES)
    license_status = validate.query_enum("license_status", K.LICENSE_STATUSES)
    application_status = validate.query_enum("application_status", K.APPLICATION_STATUSES)
    risk_tier = validate.query_enum("risk_tier", K.RISK_TIERS)
    county = validate.query_str("county_code")
    rows = store.ordered(store.providers)
    if county is not None:
        rows = [r for r in rows if r["county_code"] == county]
    if program_type is not None:
        rows = [r for r in rows if r["program_type"] == program_type]
    if license_status is not None:
        rows = [r for r in rows if r["license_status"] == license_status]
    if application_status is not None:
        rows = [r for r in rows if r["application_status"] == application_status]
    if risk_tier is not None:
        rows = [r for r in rows if r["risk_tier"] == risk_tier]
    return helpers.listing(rows, serialize.provider, limit, offset)


@bp.get("/licensing/providers/<provider_id>")
def read_provider(provider_id):
    authenticate(PROVIDER_READERS)
    record = helpers.need("provider", provider_id)
    return envelope.ok(serialize.provider(record))


@bp.post("/licensing/providers/<provider_id>/submit-application")
def submit_application(provider_id):
    user_id, role = authenticate(("Applicant",))
    validate.body([])
    provider = helpers.need("provider", provider_id)
    require_provider_owner(role, user_id, provider_id)
    if provider["application_status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE", "The application is no longer in DRAFT."
        )
    people = store.staff_of(provider_id)
    if not any(s["member_type"] == "DIRECTOR" for s in people):
        raise ApiError("ERR_CLEARANCE_INCOMPLETE", "The provider has no DIRECTOR on file.")
    rooms = store.rosters_of(provider_id)
    if not rooms:
        raise ApiError(
            "ERR_CAPACITY_SLOT_IMBALANCE", "The provider has declared no age-group roster."
        )
    if sum(r["requested_group_size"] for r in rooms) != provider["requested_capacity"]:
        raise ApiError(
            "ERR_CAPACITY_SLOT_IMBALANCE",
            "Requested group sizes must sum to the requested capacity exactly.",
        )
    if provider["requested_capacity"] > provider["capacity_ceiling"]:
        raise ApiError(
            "ERR_CAPACITY_CEILING_EXCEEDED",
            "Requested capacity exceeds the statutory ceiling for this programme class.",
        )
    if derive.approved_size_sum(provider_id) > derive.roster_capacity_limit(provider):
        raise ApiError(
            "ERR_ROSTER_CAPACITY_MISMATCH",
            "Approved group sizes exceed the provider's authorised capacity.",
        )
    provider["application_status"] = "SUBMITTED"
    store.touch(provider)
    return envelope.ok(serialize.provider(provider))


@bp.post("/licensing/providers/<provider_id>/clear-checks")
def clear_checks(provider_id):
    authenticate(("LicensingSupervisor",))
    validate.body([])
    provider = helpers.need("provider", provider_id)
    if provider["application_status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE", "The application is not in SUBMITTED."
        )
    if not derive.provider_clearance_complete(provider):
        raise ApiError(
            "ERR_CLEARANCE_INCOMPLETE", "Not every attached person is cleared."
        )
    provider["application_status"] = "CHECKS_CLEARED"
    store.touch(provider)
    return envelope.ok(serialize.provider(provider))


@bp.post("/licensing/providers/<provider_id>/license-decision")
def license_decision(provider_id):
    authenticate(("LicensingSupervisor",))
    vals = validate.body(
        [
            F("decision", "enum", required=True, values=K.LICENSE_DECISIONS),
            F("decision_reason", "string"),
        ]
    )
    provider = helpers.need("provider", provider_id)
    if vals["decision"] == "ISSUE":
        if provider["application_status"] != "INITIAL_INSPECTION_PASSED":
            raise ApiError(
                "ERR_INVALID_APPLICATION_STATE",
                "A licence may only be issued after the initial inspection has passed.",
            )
        if not derive.provider_clearance_complete(provider):
            raise ApiError(
                "ERR_CLEARANCE_INCOMPLETE", "Not every attached person is cleared."
            )
        if provider["critical_open_count"] != 0:
            raise ApiError(
                "ERR_UNRESOLVED_CRITICAL_VIOLATION",
                "An open critical violation blocks issuance.",
            )
        sequence = 1 + len(
            [
                p
                for p in store.ordered(store.providers)
                if p["county_code"] == provider["county_code"]
                and p.get("licensed_at") is not None
            ]
        )
        now = clock.now()
        provider["application_status"] = "LICENSED"
        provider["license_status"] = "PROVISIONAL"
        provider["licensed_at"] = now
        provider["provisional_started_at"] = now
        for room in store.rosters_of(provider_id):
            room["approved_group_size"] = room["requested_group_size"]
            derive.recompute_roster_flags(room)
            store.touch(room)
        provider["licensed_capacity"] = derive.approved_size_sum(provider_id)
        provider["suspended_capacity"] = 0
        provider["license_number"] = calc.license_number(
            provider["county_code"], sequence
        )
    else:
        if provider["application_status"] not in ("SUBMITTED", "CHECKS_CLEARED"):
            raise ApiError(
                "ERR_INVALID_APPLICATION_STATE",
                "A denial requires the application to be SUBMITTED or CHECKS_CLEARED.",
            )
        provider["application_status"] = "DENIED"
        provider["decision_reason"] = vals.get("decision_reason")
        for inspection in store.provider_inspections(provider_id):
            if inspection["status"] in ("SCHEDULED", "IN_PROGRESS", "PENDING_REVIEW"):
                derive.void_inspection(inspection, "Licence application denied.")
    store.touch(provider)
    return envelope.ok(serialize.provider(provider))


@bp.post("/licensing/providers/<provider_id>/promote-to-full")
def promote_to_full(provider_id):
    authenticate(("LicensingSupervisor",))
    validate.body([])
    provider = helpers.need("provider", provider_id)
    if provider["license_status"] != "PROVISIONAL":
        raise ApiError("ERR_INVALID_LICENSE_STATE", "The licence is not PROVISIONAL.")
    started = clock.at(provider["provisional_started_at"])
    passing = None
    for inspection in store.provider_inspections(provider_id):
        if inspection["inspection_type"] != "ANNUAL" or inspection["status"] != "FINALIZED":
            continue
        if inspection["outcome"] not in ("PASS", "CONDITIONAL_PASS"):
            continue
        if started is not None and clock.at(inspection["finalized_at"]) < started:
            continue
        passing = inspection
        break
    if passing is None:
        raise ApiError(
            "ERR_INVALID_LICENSE_STATE",
            "No passing ANNUAL inspection has been finalized in the provisional period.",
        )
    if provider["critical_open_count"] != 0:
        raise ApiError(
            "ERR_UNRESOLVED_CRITICAL_VIOLATION",
            "An open critical violation blocks promotion.",
        )
    if started is not None and clock.now_dt() < clock.add_months(
        started, K.PROVISIONAL_PERIOD_MONTHS
    ):
        raise ApiError(
            "ERR_PROVISIONAL_PERIOD_NOT_ELAPSED",
            "The six-month provisional period has not elapsed.",
        )
    if provider["open_violation_points"] != 0:
        raise ApiError(
            "ERR_OUTSTANDING_VIOLATION_POINTS",
            "Outstanding violation points block promotion.",
        )
    provider["license_status"] = "FULL"
    store.touch(provider)
    return envelope.ok(serialize.provider(provider))


@bp.post("/licensing/providers/<provider_id>/restore-full")
def restore_full(provider_id):
    authenticate(("LicensingSupervisor",))
    validate.body([])
    provider = helpers.need("provider", provider_id)
    if provider["license_status"] != "PROBATION":
        raise ApiError("ERR_INVALID_LICENSE_STATE", "The licence is not on PROBATION.")
    for plan in store.by_provider(store.caps, provider_id):
        if plan["status"] not in ("COMPLETED", "SUPERSEDED"):
            raise ApiError(
                "ERR_INVALID_CAP_STATE",
                "Every corrective action plan must be COMPLETED or SUPERSEDED.",
            )
    if provider["critical_open_count"] != 0:
        raise ApiError(
            "ERR_UNRESOLVED_CRITICAL_VIOLATION",
            "An open critical violation blocks restoration.",
        )
    if provider["open_violation_points"] >= K.WARNING_THRESHOLD:
        raise ApiError(
            "ERR_OUTSTANDING_VIOLATION_POINTS",
            "The point balance is not below the warning threshold.",
        )
    provider["license_status"] = "FULL"
    provider["current_ladder_step"] = 0
    store.touch(provider)
    return envelope.ok(serialize.provider(provider))


@bp.get("/licensing/providers/<provider_id>/risk-assessment")
def risk_assessment(provider_id):
    authenticate(("AgencyAdmin", "LicensingSupervisor", "ComplaintIntakeSpecialist"))
    variant = validate.query_enum("variant", K.RISK_VARIANTS) or "ENFORCEMENT_REVIEW"
    provider = helpers.need("provider", provider_id)
    snapshot = dict(provider)
    derive.recompute_provider_points(snapshot)
    derive.recompute_provider_complaint_counts(snapshot)
    score = calc.risk_score(snapshot, variant)
    return envelope.ok(
        {
            "variant": variant,
            "risk_score": calc.as_number(score),
            "risk_tier": calc.risk_tier(score),
            "open_violation_points": snapshot["open_violation_points"],
            "substantiated_complaint_count_24mo": snapshot[
                "substantiated_complaint_count_24mo"
            ],
            "inconclusive_complaint_count_24mo": snapshot[
                "inconclusive_complaint_count_24mo"
            ],
            "critical_violation_count_24mo": snapshot["critical_violation_count_24mo"],
        }
    )
