"""Organization profile, verification and the self-reported collections."""

from flask import Blueprint, request

import auth
import calc
import clock
import listing
import response
import store
import svc
import webutil
from errors import (
    ApiError,
    ERR_EIN_ALREADY_REGISTERED,
    ERR_INVALID_REQUEST,
    ERR_ORG_NOT_IN_GOOD_STANDING,
    ERR_PROFILE_INCOMPLETE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_VERIFICATION_STEP_INVALID,
)

bp = Blueprint("organizations", __name__)

ORG_TYPES = ("501C3", "501C4", "501C6", "501C7", "527", "OTHER")
DISCLOSURE_LEVELS = ("PUBLIC", "RESTRICTED", "WITHHELD")
VERIFICATION_LADDER = ("SELF_REPORTED", "DOCUMENT_VERIFIED", "INDEPENDENTLY_AUDITED")
DEMOGRAPHIC_CATEGORIES = (
    "RACE_ETHNICITY", "GENDER_IDENTITY", "AGE_BAND", "LGBTQIA", "DISABILITY", "VETERAN",
)

ORG_FIELDS = (
    "legal_name", "ein", "org_type", "state_code", "display_name", "ntee_code",
    "mission_statement", "dissolution_date",
)
PATCH_FIELDS = (
    "expected_organization_version", "display_name", "ntee_code", "mission_statement",
    "legal_name", "state_code", "demographic_records",
)


@bp.route("/nonprofits/organizations", methods=["POST"])
def create_organization():
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_PLATFORM_ADMIN,))
    data = webutil.body()
    webutil.reject_unknown(data, ORG_FIELDS)

    legal_name = webutil.as_string(data, "legal_name")
    ein = webutil.as_string(data, "ein")
    org_type = webutil.as_enum(data, "org_type", ORG_TYPES)
    state_code = webutil.as_string(data, "state_code")
    display_name = webutil.as_string(data, "display_name", required=False)
    ntee_code = webutil.as_string(data, "ntee_code", required=False)
    mission_statement = webutil.as_string(data, "mission_statement", required=False)
    dissolution_date = webutil.as_datetime(data, "dissolution_date", required=False)

    for existing in store.rows("organizations"):
        if existing.get("ein") == ein:
            raise ApiError(
                ERR_EIN_ALREADY_REGISTERED,
                "EIN '%s' is already registered to another organization." % ein,
            )

    org = store.new_row(
        legal_name=legal_name,
        display_name=display_name,
        former_legal_names=[],
        ein=ein,
        org_type=org_type,
        state_code=state_code,
        ntee_code=ntee_code,
        ntee_code_verified=False,
        mission_statement=mission_statement,
        profile_status="DRAFT",
        verification_level="SELF_REPORTED",
        verification_evidence_count=0,
        transparency_seal_level="NONE",
        seal_expires_on=None,
        provisional_completeness_score=0,
        verified_completeness_score=0,
        profile_completeness_score=0,
        disclosure_pct=0.0,
        total_revenue_cents=0,
        latest_filing_tax_year=None,
        distinct_funder_count=0,
        active_license_count=0,
        open_correction_count=0,
        last_profile_editor_user_id=acting.user_id,
        successor_organization_id=None,
        dissolution_date=dissolution_date,
    )
    store.insert("organizations", org)
    svc.recompute_org(org)
    return response.ok(svc.ser_organization(org), status=201)


@bp.route("/nonprofits/organizations", methods=["GET"])
def list_organizations():
    acting = auth.actor()
    auth.require_role(acting, (
        auth.ROLE_PLATFORM_ADMIN, auth.ROLE_PLATFORM_VERIFIER,
        auth.ROLE_ORGANIZATION_USER, auth.ROLE_DATA_CONSUMER,
    ))
    spec = (
        ("ein", "ein", "str"),
        ("state_code", "state_code", "str"),
        ("profile_status", "profile_status", "str"),
        ("verification_level", "verification_level", "str"),
        ("successor_organization_id", "successor_organization_id", "str"),
    )
    return listing.list_endpoint(store.rows("organizations"), svc.ser_organization, spec)


@bp.route("/nonprofits/organizations/<org_id>", methods=["GET"])
def get_organization(org_id):
    acting = auth.actor()
    auth.require_role(acting, (
        auth.ROLE_PLATFORM_ADMIN, auth.ROLE_PLATFORM_VERIFIER,
        auth.ROLE_ORGANIZATION_USER, auth.ROLE_DATA_CONSUMER,
    ))
    org = svc.get_organization(org_id)
    return response.ok(svc.ser_organization(org))


@bp.route("/nonprofits/organizations/<org_id>", methods=["PATCH"])
def patch_organization(org_id):
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_ORGANIZATION_USER, auth.ROLE_PLATFORM_ADMIN))
    org = svc.get_organization(org_id)
    auth.require_owner(acting, org_id, "profile")

    data = webutil.body()
    webutil.reject_unknown(data, PATCH_FIELDS)

    for field in ("display_name", "ntee_code", "mission_statement", "legal_name", "state_code"):
        if field in data:
            value = data[field]
            if value is None:
                org[field] = None
            elif not isinstance(value, str):
                raise ApiError(ERR_INVALID_REQUEST, "Field '%s' must be a string." % field)
            else:
                org[field] = value

    if "demographic_records" in data and data["demographic_records"] is not None:
        records = webutil.as_list(data, "demographic_records")
        for existing in store.where("demographic_records", organization_id=org_id):
            store.DB["demographic_records"].pop(existing["id"], None)
            store.ORDER["demographic_records"].remove(existing["id"])
        for element in records:
            if not isinstance(element, dict):
                raise ApiError(ERR_INVALID_REQUEST, "Each demographic record must be an object.")
            category = webutil.as_enum(element, "category", DEMOGRAPHIC_CATEGORIES)
            value_code = webutil.as_string(element, "value_code")
            disclosure_level = webutil.as_enum(
                element, "disclosure_level", DISCLOSURE_LEVELS, required=False, default="RESTRICTED"
            )
            fiscal_year = webutil.as_int(element, "fiscal_year")
            row = store.new_row(
                organization_id=org_id,
                category=category,
                value_code=value_code,
                disclosure_level=disclosure_level,
                is_verified=False,
                fiscal_year=fiscal_year,
            )
            store.insert("demographic_records", row)

    org["last_profile_editor_user_id"] = acting.user_id
    svc.recompute_scores(org)
    svc.recompute_disclosure(org)
    svc.apply_seal_floor_cascade(org)
    store.touch(org)
    return response.ok(svc.ser_organization(org))


@bp.route("/nonprofits/organizations/<org_id>/verify", methods=["POST"])
def verify_organization(org_id):
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_PLATFORM_VERIFIER,))
    org = svc.get_organization(org_id)

    data = webutil.body()
    webutil.reject_unknown(data, ("target_level", "evidence_count"))
    target_level = webutil.as_enum(data, "target_level", VERIFICATION_LADDER)
    evidence_count = webutil.as_int(data, "evidence_count", minimum=1)

    status = org.get("profile_status")
    if status in ("MERGED", "DISSOLVED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "An organization in %s status cannot be verified." % status,
        )

    if status == "SUSPENDED":
        if (org.get("open_correction_count") or 0) >= 3:
            raise ApiError(
                ERR_ORG_NOT_IN_GOOD_STANDING,
                "The organization cannot return to ACTIVE while it has three or more "
                "open correction requests.",
            )
        org["profile_status"] = "ACTIVE"
        store.touch(org)
        return response.ok(svc.ser_organization(org))

    # Gate 1 — segregation of duties (PRD 2.6 / 3.3).
    if acting.user_id == org.get("last_profile_editor_user_id"):
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "The verifying user must differ from the organization's last profile editor.",
        )

    # Gate 2 — the step rule.
    ladder = list(VERIFICATION_LADDER)
    current = org.get("verification_level")
    index = ladder.index(current) if current in ladder else -1
    expected = ladder[index + 1] if 0 <= index < len(ladder) - 1 else None
    if expected is None or target_level != expected:
        raise ApiError(
            ERR_VERIFICATION_STEP_INVALID,
            "target_level must be exactly the next level above %s." % current,
        )

    # Gate 3 — the completeness floor, only while the profile is still DRAFT.
    if status == "DRAFT" and (org.get("profile_completeness_score") or 0) < 50:
        raise ApiError(
            ERR_PROFILE_INCOMPLETE,
            "profile_completeness_score must be at least 50 before the first verification.",
        )

    org["verification_level"] = target_level
    org["verification_evidence_count"] = (org.get("verification_evidence_count") or 0) + evidence_count
    for program in store.where("programs", organization_id=org_id):
        program["is_verified"] = True
        store.touch(program)
    for leader in store.where("leadership_members", organization_id=org_id):
        leader["is_verified"] = True
        store.touch(leader)
    for record in store.where("demographic_records", organization_id=org_id):
        record["is_verified"] = True
        store.touch(record)
    org["ntee_code_verified"] = True
    if status == "DRAFT":
        org["profile_status"] = "ACTIVE"
    svc.recompute_scores(org)
    store.touch(org)
    return response.ok(svc.ser_organization(org))


# --- programs ------------------------------------------------------------

@bp.route("/nonprofits/organizations/<org_id>/programs", methods=["POST"])
def create_program(org_id):
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_ORGANIZATION_USER, auth.ROLE_PLATFORM_ADMIN))
    org = svc.get_organization(org_id)
    auth.require_owner(acting, org_id, "programs")

    data = webutil.body()
    webutil.reject_unknown(
        data, ("program_name", "fiscal_year", "subject_code", "population_served", "disclosure_level")
    )
    program_name = webutil.as_string(data, "program_name")
    fiscal_year = webutil.as_int(data, "fiscal_year")
    subject_code = webutil.as_string(data, "subject_code", required=False)
    population_served = webutil.as_string(data, "population_served", required=False)
    disclosure_level = webutil.as_enum(
        data, "disclosure_level", DISCLOSURE_LEVELS, required=False, default="RESTRICTED"
    )

    program = store.new_row(
        organization_id=org_id,
        program_name=program_name,
        subject_code=subject_code,
        population_served=population_served,
        disclosure_level=disclosure_level,
        is_verified=False,
        status="ACTIVE",
        fiscal_year=fiscal_year,
    )
    store.insert("programs", program)
    svc.recompute_scores(org)
    svc.recompute_disclosure(org)
    svc.apply_seal_floor_cascade(org)
    return response.ok(svc.ser_program(program), status=201)


@bp.route("/nonprofits/organizations/<org_id>/programs", methods=["GET"])
def list_programs(org_id):
    acting = auth.actor()
    auth.require_role(acting, (
        auth.ROLE_PLATFORM_ADMIN, auth.ROLE_PLATFORM_VERIFIER,
        auth.ROLE_ORGANIZATION_USER, auth.ROLE_DATA_CONSUMER,
    ))
    svc.get_organization(org_id)
    rows = store.where("programs", organization_id=org_id)
    return listing.list_endpoint(rows, svc.ser_program, (("status", "status", "str"),))


# --- leadership ----------------------------------------------------------

def _intervals_overlap(start_a, end_a, start_b, end_b):
    """Closed intervals; a null end means the term is open-ended."""
    if start_a is None or start_b is None:
        return False
    if end_a is not None and start_b > end_a:
        return False
    if end_b is not None and start_a > end_b:
        return False
    return True


@bp.route("/nonprofits/organizations/<org_id>/leadership-members", methods=["POST"])
def create_leadership_member(org_id):
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_ORGANIZATION_USER, auth.ROLE_PLATFORM_ADMIN))
    org = svc.get_organization(org_id)
    auth.require_owner(acting, org_id, "leadership roster")

    data = webutil.body()
    webutil.reject_unknown(data, (
        "full_name", "office_title", "service_start", "is_officer", "is_independent",
        "disclosure_level", "compensation_cents", "service_end",
    ))
    full_name = webutil.as_string(data, "full_name")
    office_title = webutil.as_string(data, "office_title")
    service_start_raw = webutil.as_datetime(data, "service_start")
    service_end_raw = webutil.as_datetime(data, "service_end", required=False)
    is_officer = webutil.as_bool(data, "is_officer", default=True)
    is_independent = webutil.as_bool(data, "is_independent", default=False)
    disclosure_level = webutil.as_enum(
        data, "disclosure_level", DISCLOSURE_LEVELS, required=False, default="RESTRICTED"
    )
    compensation_cents = webutil.as_int(data, "compensation_cents", required=False, default=0)

    service_start = clock.parse_dt(service_start_raw)
    service_end = clock.parse_dt(service_end_raw)
    for existing in store.where("leadership_members", organization_id=org_id, office_title=office_title):
        if existing.get("status") != "ACTIVE":
            continue
        if _intervals_overlap(
            service_start, service_end,
            clock.parse_dt(existing.get("service_start")),
            clock.parse_dt(existing.get("service_end")),
        ):
            raise ApiError(
                "ERR_LEADERSHIP_TERM_OVERLAP",
                "The service interval overlaps an ACTIVE %s row." % office_title,
            )

    member = store.new_row(
        organization_id=org_id,
        full_name=full_name,
        office_title=office_title,
        is_officer=is_officer,
        is_independent=is_independent,
        is_verified=False,
        disclosure_level=disclosure_level,
        compensation_cents=compensation_cents,
        service_start=service_start_raw,
        service_end=service_end_raw,
        status="ACTIVE",
    )
    store.insert("leadership_members", member)
    svc.recompute_scores(org)
    svc.recompute_disclosure(org)
    svc.apply_seal_floor_cascade(org)
    return response.ok(svc.ser_leader(member), status=201)


@bp.route("/nonprofits/organizations/<org_id>/leadership-members", methods=["GET"])
def list_leadership_members(org_id):
    acting = auth.actor()
    auth.require_role(acting, (
        auth.ROLE_PLATFORM_ADMIN, auth.ROLE_PLATFORM_VERIFIER,
        auth.ROLE_ORGANIZATION_USER, auth.ROLE_DATA_CONSUMER,
    ))
    svc.get_organization(org_id)
    rows = store.where("leadership_members", organization_id=org_id)
    spec = (("status", "status", "str"), ("office_title", "office_title", "str"))
    return listing.list_endpoint(rows, svc.ser_leader, spec)


# --- demographic records -------------------------------------------------

@bp.route("/nonprofits/organizations/<org_id>/demographic-records", methods=["GET"])
def list_demographic_records(org_id):
    acting = auth.actor()
    auth.require_role(acting, (
        auth.ROLE_PLATFORM_ADMIN, auth.ROLE_PLATFORM_VERIFIER,
        auth.ROLE_ORGANIZATION_USER, auth.ROLE_DATA_CONSUMER,
    ))
    svc.get_organization(org_id)
    rows = store.where("demographic_records", organization_id=org_id)
    spec = (("category", "category", "str"), ("disclosure_level", "disclosure_level", "str"))
    return listing.list_endpoint(rows, svc.ser_demographic, spec)
