"""Clock (unprefixed), FundingOpportunity, Institute, Institution, Applicant."""
from flask import Blueprint

from constants import ACTIVITY_CODES, CAREER_STAGES, ROLE_PROGRAM_OFFICER
from db import STORE, clock_now, new_entity, set_clock, touch
from errors import fail
from serializers import (
    applicant_json,
    foa_json,
    institute_json,
    institution_json,
)
from services import fund_application, get, run_payline_walk
from util import (
    auth_context,
    get_body,
    ok_object,
    opt_dt,
    parse_iso,
    render_dt,
    req_dt,
    req_enum,
    req_int,
    req_num,
    req_str,
    require_role,
)

bp = Blueprint("core", __name__)


# ---------------------------------------------------------------------------
# Logical clock (mounted OUTSIDE /grants — PRD §2.4)
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    user_id, role = auth_context()
    require_role(role, (ROLE_PROGRAM_OFFICER,))
    body = get_body()
    raw = body.get("to_iso8601")
    dt = parse_iso(raw) if isinstance(raw, str) else None
    if dt is None:
        fail("ERR_INVALID_CLOCK_VALUE", "to_iso8601 must be a valid ISO8601 UTC timestamp")
    if dt < clock_now():
        fail(
            "ERR_INVALID_CLOCK_VALUE",
            "to_iso8601 must not be earlier than the current logical time",
        )
    current = set_clock(dt)
    return ok_object({"current_utc": render_dt(current)})


# ---------------------------------------------------------------------------
# FundingOpportunity
# ---------------------------------------------------------------------------
@bp.route("/grants/funding-opportunities", methods=["POST"])
def create_foa():
    user_id, role = auth_context()
    require_role(role, (ROLE_PROGRAM_OFFICER,))
    body = get_body()
    pa_number = req_str(body, "pa_number")
    title = req_str(body, "title")
    activity_code = req_enum(body, "activity_code", ACTIVITY_CODES)
    page_limit = req_int(body, "research_strategy_page_limit", minimum=1)
    min_direct = req_int(body, "min_direct_cents_per_year", minimum=0)
    max_direct = req_int(body, "max_direct_cents_per_year", minimum=0)
    if max_direct < min_direct:
        fail("ERR_VALIDATION", "max_direct_cents_per_year must be >= min_direct_cents_per_year")
    max_years = req_int(body, "max_years", minimum=1, maximum=5)
    open_date = req_dt(body, "open_date")
    receipt_deadline = req_dt(body, "receipt_deadline")
    for existing in STORE["funding_opportunities"].values():
        if existing["pa_number"] == pa_number:
            fail("ERR_DUPLICATE_PA_NUMBER", "a funding opportunity with this pa_number already exists")
    foa = new_entity()
    foa.update(
        {
            "pa_number": pa_number,
            "title": title,
            "activity_code": activity_code,
            "research_strategy_page_limit": page_limit,
            "min_direct_cents_per_year": min_direct,
            "max_direct_cents_per_year": max_direct,
            "max_years": max_years,
            "open_date": open_date,
            "receipt_deadline": receipt_deadline,
            "status": "OPEN",
        }
    )
    STORE["funding_opportunities"][foa["id"]] = foa
    return ok_object(foa_json(foa), 201)


@bp.route("/grants/funding-opportunities/<foa_id>", methods=["GET"])
def get_foa(foa_id):
    auth_context()
    foa = get("funding_opportunities", foa_id)
    if foa is None:
        fail("ERR_FOA_NOT_FOUND", "funding opportunity not found")
    return ok_object(foa_json(foa))


@bp.route("/grants/funding-opportunities/<foa_id>/close", methods=["POST"])
def close_foa(foa_id):
    user_id, role = auth_context()
    require_role(role, (ROLE_PROGRAM_OFFICER,))
    foa = get("funding_opportunities", foa_id)
    if foa is None:
        fail("ERR_FOA_NOT_FOUND", "funding opportunity not found")
    if foa["status"] != "OPEN":
        fail("ERR_FOA_NOT_OPEN", "funding opportunity is not OPEN")
    foa["status"] = "CLOSED"
    touch(foa)
    return ok_object(foa_json(foa))


# ---------------------------------------------------------------------------
# Institute
# ---------------------------------------------------------------------------
@bp.route("/grants/institutes", methods=["POST"])
def create_institute():
    user_id, role = auth_context()
    require_role(role, (ROLE_PROGRAM_OFFICER,))
    body = get_body()
    name = req_str(body, "name")
    appropriation = req_int(body, "appropriation_cents", minimum=0)
    reserve = req_int(body, "reserve_cents", minimum=0)
    rate = req_num(body, "indirect_cost_rate", minimum=0, maximum=1)
    cap_pct = req_num(body, "select_pay_cap_pct", minimum=0, maximum=1)
    extension = req_num(body, "select_pay_extension_percentile", minimum=0)
    inst = new_entity()
    inst.update(
        {
            "name": name,
            "appropriation_cents": appropriation,
            "reserve_cents": reserve,
            "indirect_cost_rate": rate,
            "select_pay_cap_pct": cap_pct,
            "select_pay_extension_percentile": extension,
            "committed_cents": 0,
            "disbursed_cents": 0,
            "select_pay_spent_cents": 0,
            "current_payline_percentile": None,
        }
    )
    STORE["institutes"][inst["id"]] = inst
    return ok_object(institute_json(inst), 201)


@bp.route("/grants/institutes/<institute_id>", methods=["GET"])
def get_institute(institute_id):
    auth_context()
    inst = get("institutes", institute_id)
    if inst is None:
        fail("ERR_INSTITUTE_NOT_FOUND", "institute not found")
    return ok_object(institute_json(inst))


@bp.route("/grants/institutes/<institute_id>/payline-decisions", methods=["POST"])
def publish_payline(institute_id):
    user_id, role = auth_context()
    require_role(role, (ROLE_PROGRAM_OFFICER,))
    inst = get("institutes", institute_id)
    if inst is None:
        fail("ERR_INSTITUTE_NOT_FOUND", "institute not found")
    body = get_body()
    base_payline = req_num(body, "base_payline_percentile")
    expected_version = req_int(body, "expected_institute_version")
    if expected_version != inst["version"]:
        fail(
            "ERR_STALE_INSTITUTE_VERSION",
            "expected_institute_version does not match the institute's current version",
        )
    funded = run_payline_walk(inst, base_payline)
    for app in funded:
        fund_application(app)
    inst["current_payline_percentile"] = base_payline
    touch(inst)
    return ok_object(institute_json(inst))


# ---------------------------------------------------------------------------
# Institution
# ---------------------------------------------------------------------------
@bp.route("/grants/institutions", methods=["POST"])
def create_institution():
    user_id, role = auth_context()
    require_role(role, (ROLE_PROGRAM_OFFICER,))
    body = get_body()
    name = req_str(body, "name")
    hs_expiry = opt_dt(body, "human_subjects_certification_expiry")
    aw_expiry = opt_dt(body, "animal_welfare_assurance_expiry")
    inst = new_entity()
    inst.update(
        {
            "name": name,
            "human_subjects_certification_expiry": hs_expiry,
            "animal_welfare_assurance_expiry": aw_expiry,
        }
    )
    STORE["institutions"][inst["id"]] = inst
    return ok_object(institution_json(inst), 201)


@bp.route("/grants/institutions/<institution_id>", methods=["GET"])
def get_institution(institution_id):
    auth_context()
    inst = get("institutions", institution_id)
    if inst is None:
        fail("ERR_INSTITUTION_NOT_FOUND", "institution not found")
    return ok_object(institution_json(inst))


# ---------------------------------------------------------------------------
# Applicant
# ---------------------------------------------------------------------------
@bp.route("/grants/applicants", methods=["POST"])
def create_applicant():
    user_id, role = auth_context()
    require_role(role, (ROLE_PROGRAM_OFFICER,))
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    career_stage = req_enum(body, "career_stage", CAREER_STAGES)
    applicant = new_entity()
    applicant.update(
        {"full_name": full_name, "email": email, "career_stage": career_stage}
    )
    STORE["applicants"][applicant["id"]] = applicant
    return ok_object(applicant_json(applicant), 201)


@bp.route("/grants/applicants/<applicant_id>", methods=["GET"])
def get_applicant(applicant_id):
    auth_context()
    applicant = get("applicants", applicant_id)
    if applicant is None:
        fail("ERR_APPLICANT_NOT_FOUND", "applicant not found")
    return ok_object(applicant_json(applicant))
