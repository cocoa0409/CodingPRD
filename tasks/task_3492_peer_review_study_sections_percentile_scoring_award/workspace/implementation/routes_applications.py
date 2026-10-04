"""Application routes: draft/submit/withdraw/referral/select-pay + sublists."""
from flask import Blueprint, request

from constants import (
    LIVE_ASSIGNMENT_STATUSES,
    ROLE_APPLICANT,
    ROLE_GRANTS_OFFICER,
    ROLE_REFERRAL_OFFICER,
    TERMINAL_APPLICATION_STATUSES,
    WITHDRAWABLE_APPLICATION_STATUSES,
)
from db import STORE, clock_now, new_entity, touch
from errors import fail
from serializers import application_json, council_review_json, jit_json
from services import (
    dec,
    fund_application,
    get,
    live_assignment_count,
    projected_cost,
    rhu,
    section_assigned_count,
)
from util import (
    auth_context,
    get_body,
    ok_list,
    ok_object,
    opt_bool,
    opt_list,
    opt_str,
    parse_pagination,
    req_int,
    req_list,
    req_str,
    require_owner,
    require_role,
    sort_and_page,
)

bp = Blueprint("applications", __name__)


def _get_application_or_404(application_id):
    app = get("applications", application_id)
    if app is None:
        fail("ERR_APPLICATION_NOT_FOUND", "application not found")
    return app


# ---------------------------------------------------------------------------
# Create / read
# ---------------------------------------------------------------------------
@bp.route("/grants/applications", methods=["POST"])
def create_application():
    user_id, role = auth_context()
    require_role(role, (ROLE_APPLICANT,))
    body = get_body()
    foa_id = req_str(body, "foa_id")
    institution_id = req_str(body, "institution_id")
    title = req_str(body, "title")
    page_count = req_int(body, "research_strategy_page_count", minimum=1)
    direct = req_list(body, "direct_cents_per_year", elem=int)
    years = req_int(body, "requested_years", minimum=1, maximum=5)
    human = opt_bool(body, "human_subjects_involved", default=False)
    animals = opt_bool(body, "vertebrate_animals_involved", default=False)
    req_section = opt_str(body, "requested_study_section_id")
    req_institute = opt_str(body, "requested_institute_id")
    excluded = opt_list(body, "excluded_reviewer_ids", elem=str, default=[])
    # body foreign keys (pipeline stage 4)
    foa = get("funding_opportunities", foa_id)
    if foa is None:
        fail("ERR_FOA_NOT_FOUND", "funding opportunity not found")
    institution = get("institutions", institution_id)
    if institution is None:
        fail("ERR_INSTITUTION_NOT_FOUND", "institution not found")
    if req_section is not None and get("study_sections", req_section) is None:
        fail("ERR_STUDY_SECTION_NOT_FOUND", "requested study section not found")
    if req_institute is not None and get("institutes", req_institute) is None:
        fail("ERR_INSTITUTE_NOT_FOUND", "requested institute not found")
    # budget structure (stage 11, creation-time leg)
    if len(direct) != years:
        fail(
            "ERR_INVALID_BUDGET_STRUCTURE",
            "direct_cents_per_year length must equal requested_years",
        )
    # uniqueness (stage 12): one non-terminal application per (applicant, foa)
    for other in STORE["applications"].values():
        if (
            other["applicant_id"] == user_id
            and other["foa_id"] == foa_id
            and other["status"] not in TERMINAL_APPLICATION_STATUSES
        ):
            fail(
                "ERR_DUPLICATE_APPLICATION",
                "applicant already has a non-terminal application against this FOA",
            )
    app = new_entity()
    app.update(
        {
            "foa_id": foa_id,
            "applicant_id": user_id,
            "institution_id": institution_id,
            "title": title,
            "research_strategy_page_count": page_count,
            "direct_cents_per_year": list(direct),
            "requested_years": years,
            "human_subjects_involved": human,
            "vertebrate_animals_involved": animals,
            "requested_study_section_id": req_section,
            "requested_institute_id": req_institute,
            "excluded_reviewer_ids": list(excluded),
            "study_section_id": None,
            "institute_id": None,
            "impact_score": None,
            "approach_mean": None,
            "significance_mean": None,
            "innovation_mean": None,
            "percentile_raw": None,
            "percentile_normalized": None,
            "status": "DRAFT",
        }
    )
    STORE["applications"][app["id"]] = app
    return ok_object(application_json(app), 201)


@bp.route("/grants/applications", methods=["GET"])
def list_applications():
    auth_context()
    limit, offset = parse_pagination(request.args)
    filters = (
        "foa_id",
        "applicant_id",
        "institution_id",
        "requested_study_section_id",
        "requested_institute_id",
        "study_section_id",
        "institute_id",
        "status",
    )
    items = list(STORE["applications"].values())
    args = request.args
    for f in filters:
        if args.get(f) is not None:
            items = [a for a in items if a.get(f) == args.get(f)]
    page, total = sort_and_page(items, limit, offset)
    return ok_list([application_json(a) for a in page], total, limit, offset)


@bp.route("/grants/applications/<application_id>", methods=["GET"])
def get_application(application_id):
    auth_context()
    return ok_object(application_json(_get_application_or_404(application_id)))


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------
@bp.route("/grants/applications/<application_id>/submit", methods=["POST"])
def submit_application(application_id):
    user_id, role = auth_context()
    require_role(role, (ROLE_APPLICANT,))
    app = _get_application_or_404(application_id)
    require_owner(app["applicant_id"], user_id)
    if app["status"] != "DRAFT":
        fail("ERR_APPLICATION_NOT_SUBMITTABLE", "submit requires DRAFT status")
    foa = get("funding_opportunities", app["foa_id"])
    if foa["status"] != "OPEN":
        fail("ERR_FOA_NOT_OPEN", "funding opportunity is not OPEN")
    # institutional certifications (pipeline stage 8)
    institution = get("institutions", app["institution_id"])
    if app["human_subjects_involved"]:
        expiry = institution["human_subjects_certification_expiry"]
        if expiry is None:
            fail("ERR_CERTIFICATION_MISSING", "human-subjects certification is absent")
        if expiry < foa["receipt_deadline"]:
            fail(
                "ERR_CERTIFICATION_EXPIRED",
                "human-subjects certification expires before the receipt deadline",
            )
    if app["vertebrate_animals_involved"]:
        expiry = institution["animal_welfare_assurance_expiry"]
        if expiry is None:
            fail("ERR_CERTIFICATION_MISSING", "animal-welfare assurance is absent")
        if expiry < foa["receipt_deadline"]:
            fail(
                "ERR_CERTIFICATION_EXPIRED",
                "animal-welfare assurance expires before the receipt deadline",
            )
    # page limit (stage 10)
    if app["research_strategy_page_count"] > foa["research_strategy_page_limit"]:
        fail("ERR_PAGE_LIMIT_EXCEEDED", "research strategy exceeds the FOA page limit")
    # budget structure + caps (stage 11)
    if (
        app["requested_years"] > foa["max_years"]
        or len(app["direct_cents_per_year"]) != app["requested_years"]
        or any(d < foa["min_direct_cents_per_year"] for d in app["direct_cents_per_year"])
    ):
        fail("ERR_INVALID_BUDGET_STRUCTURE", "budget violates the FOA structure bounds")
    if any(d > foa["max_direct_cents_per_year"] for d in app["direct_cents_per_year"]):
        fail("ERR_BUDGET_CAP_EXCEEDED", "a per-year direct cost exceeds the FOA cap")
    # receipt deadline (stage 16)
    if clock_now() > foa["receipt_deadline"]:
        fail("ERR_RECEIPT_DEADLINE_PASSED", "the logical clock is past the receipt deadline")
    app["status"] = "SUBMITTED"
    touch(app)
    return ok_object(application_json(app))


# ---------------------------------------------------------------------------
# Withdraw
# ---------------------------------------------------------------------------
@bp.route("/grants/applications/<application_id>/withdraw", methods=["POST"])
def withdraw_application(application_id):
    user_id, role = auth_context()
    require_role(role, (ROLE_APPLICANT,))
    app = _get_application_or_404(application_id)
    require_owner(app["applicant_id"], user_id)
    if app["status"] not in WITHDRAWABLE_APPLICATION_STATUSES:
        fail(
            "ERR_APPLICATION_NOT_WITHDRAWABLE",
            "withdraw requires DRAFT, SUBMITTED, REFERRED, or UNDER_REVIEW",
        )
    if app["status"] == "UNDER_REVIEW":
        for assignment in STORE["assignments"].values():
            if (
                assignment["application_id"] == app["id"]
                and assignment["status"] in LIVE_ASSIGNMENT_STATUSES
            ):
                assignment["status"] = "CANCELLED"
                touch(assignment)
    app["status"] = "WITHDRAWN"
    touch(app)
    return ok_object(application_json(app))


# ---------------------------------------------------------------------------
# Referral (OCC on application version)
# ---------------------------------------------------------------------------
@bp.route("/grants/applications/<application_id>/referral", methods=["POST"])
def refer_application(application_id):
    user_id, role = auth_context()
    require_role(role, (ROLE_REFERRAL_OFFICER,))
    app = _get_application_or_404(application_id)
    body = get_body()
    section_id = req_str(body, "study_section_id")
    institute_id = req_str(body, "institute_id")
    expected_version = req_int(body, "expected_application_version")
    override = opt_bool(body, "override_assignment_request", default=False)
    if app["status"] not in ("SUBMITTED", "REFERRED"):
        fail(
            "ERR_APPLICATION_NOT_REFERRABLE",
            "referral requires SUBMITTED or REFERRED status",
        )
    if expected_version != app["version"]:
        fail(
            "ERR_STALE_APPLICATION_VERSION",
            "expected_application_version does not match the application's current version",
        )
    section = get("study_sections", section_id)
    if section is None:
        fail("ERR_STUDY_SECTION_NOT_FOUND", "study section not found")
    if section["status"] != "RECRUITING":
        fail("ERR_SECTION_NOT_RECRUITING", "study section is not RECRUITING")
    if section_assigned_count(section["id"]) >= section["application_quota"]:
        fail("ERR_SECTION_QUOTA_EXCEEDED", "study section quota would be exceeded")
    institute = get("institutes", institute_id)
    if institute is None:
        fail("ERR_INSTITUTE_NOT_FOUND", "institute not found")
    if app["status"] == "REFERRED" and live_assignment_count(app["id"]) > 0:
        fail(
            "ERR_LIVE_ASSIGNMENTS_EXIST",
            "re-referral requires live_assignment_count == 0",
        )
    # assignment-request honor rule (stage 14)
    req_section_id = app["requested_study_section_id"]
    if req_section_id is not None and req_section_id != section_id and not override:
        requested = get("study_sections", req_section_id)
        if (
            requested is not None
            and requested["status"] == "RECRUITING"
            and section_assigned_count(req_section_id) < requested["application_quota"]
        ):
            fail(
                "ERR_ASSIGNMENT_REQUEST_IGNORED",
                "referral overrides a satisfiable requested study section",
            )
    req_institute_id = app["requested_institute_id"]
    if req_institute_id is not None and req_institute_id != institute_id and not override:
        if get("institutes", req_institute_id) is not None:
            fail(
                "ERR_ASSIGNMENT_REQUEST_IGNORED",
                "referral overrides a satisfiable requested institute",
            )
    app["study_section_id"] = section_id
    app["institute_id"] = institute_id
    app["status"] = "REFERRED"
    touch(app)
    return ok_object(application_json(app))


# ---------------------------------------------------------------------------
# Select pay
# ---------------------------------------------------------------------------
@bp.route("/grants/applications/<application_id>/select-pay", methods=["POST"])
def select_pay(application_id):
    user_id, role = auth_context()
    require_role(role, (ROLE_GRANTS_OFFICER,))
    app = _get_application_or_404(application_id)
    if app["status"] != "COUNCIL_REVIEWED":
        fail("ERR_APPLICATION_NOT_FUNDABLE", "select-pay requires COUNCIL_REVIEWED")
    institute = get("institutes", app["institute_id"])
    if institute is None or institute["current_payline_percentile"] is None:
        fail("ERR_NO_PAYLINE_PUBLISHED", "institute has no published payline")
    band_limit = dec(institute["current_payline_percentile"]) + dec(
        institute["select_pay_extension_percentile"]
    )
    if dec(app["percentile_raw"]) > band_limit:
        fail(
            "ERR_SELECT_PAY_BAND_EXCEEDED",
            "raw percentile is beyond the select-pay band",
        )
    foa = get("funding_opportunities", app["foa_id"])
    cost = projected_cost(app, foa, institute)
    if (
        institute["committed_cents"] + institute["disbursed_cents"] + cost
        > institute["appropriation_cents"] - institute["reserve_cents"]
    ):
        fail(
            "ERR_INSUFFICIENT_COMMITMENT_AUTHORITY",
            "select pay exceeds the institute's commitment authority",
        )
    cap = int(rhu(dec(institute["appropriation_cents"]) * dec(institute["select_pay_cap_pct"]), 0))
    if institute["select_pay_spent_cents"] + cost > cap:
        fail("ERR_SELECT_PAY_CAP_EXCEEDED", "select pay exceeds the select-pay cap")
    fund_application(app)
    institute["select_pay_spent_cents"] += cost
    touch(institute)
    return ok_object(application_json(app))


# ---------------------------------------------------------------------------
# Application-scoped lists
# ---------------------------------------------------------------------------
@bp.route("/grants/applications/<application_id>/council-reviews", methods=["GET"])
def list_application_council_reviews(application_id):
    auth_context()
    app = _get_application_or_404(application_id)
    limit, offset = parse_pagination(request.args)
    items = [
        r for r in STORE["council_reviews"].values() if r["application_id"] == app["id"]
    ]
    page, total = sort_and_page(items, limit, offset)
    return ok_list([council_review_json(r) for r in page], total, limit, offset)


@bp.route("/grants/applications/<application_id>/jit-requests", methods=["GET"])
def list_application_jit_requests(application_id):
    auth_context()
    app = _get_application_or_404(application_id)
    limit, offset = parse_pagination(request.args)
    items = [
        j for j in STORE["jit_requests"].values() if j["application_id"] == app["id"]
    ]
    page, total = sort_and_page(items, limit, offset)
    return ok_list([jit_json(j) for j in page], total, limit, offset)
