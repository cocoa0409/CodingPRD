"""PRD 3.2 / 3.3 -- adopting employers, census data and plan design elections."""

from flask import Blueprint

import authz
import clockcal
import envelope
import recompute
import store
import validate
from errors import fail
from routes_setup import (
    MATCH_FORMULA_CODES,
    VESTING_RANK,
    VESTING_SCHEDULES,
    need,
)

bp = Blueprint("employer", __name__)

ELECTION_CREATE_STATUSES = ("APPLIED", "ELECTIONS_SUBMITTED", "RETURNED_FOR_REVISION")
DEFICIENCY_CODES = (
    "MISSING_SIGNATORY",
    "TIER_MISMATCH",
    "ELIGIBILITY_TOO_RESTRICTIVE",
    "VESTING_TOO_RESTRICTIVE",
)
TIER_FIELDS = (
    "match_tier_1_pct",
    "match_tier_1_limit_pct",
    "match_tier_2_pct",
    "match_tier_2_limit_pct",
)


def _census_consistent(participant, hce, nhce, benefiting_hce, benefiting_nhce):
    """The four-part census arithmetic, checked as a unit (PRD 3.2)."""
    if benefiting_hce > hce:
        return False
    if benefiting_nhce > nhce:
        return False
    if nhce < 1:
        return False
    if hce + nhce != participant:
        return False
    return True


# ==========================================================================
# AdoptingEmployer
# ==========================================================================


@bp.post("/pep/adopting-employers")
def create_employer():
    authz.identify()
    authz.authorize("PooledPlanProvider")
    b = validate.body()

    plan = validate.resolve_fk(
        b, "plan_document_id", "plans", "ERR_PLAN_DOCUMENT_NOT_FOUND"
    )
    authz.own_if(plan=plan)

    validate.require_fk_shape(b, "plan_document_id")
    legal_name = validate.req_str(b, "legal_name", 1, 200)
    ein = validate.req_digits(b, "ein", 9)
    window_close = validate.req_date(b, "election_window_close_date")
    participant = validate.req_int(b, "participant_count", 0)
    hce = validate.req_int(b, "hce_count", 0)
    nhce = validate.req_int(b, "nhce_count", 0)
    benefiting_hce = validate.req_int(b, "benefiting_hce_count", 0)
    benefiting_nhce = validate.req_int(b, "benefiting_nhce_count", 0)
    hce_avg = validate.req_num(b, "hce_avg_deferral_pct", 0, 25, 2)
    nhce_avg = validate.req_num(b, "nhce_avg_deferral_pct", 0, 25, 2)

    if plan["status"] != "ACTIVE":
        fail("ERR_PLAN_NOT_ACTIVE")

    for row in store.employers_of_plan(plan):
        if row["ein"] == ein:
            fail("ERR_DUPLICATE_EMPLOYER_EIN")

    if not _census_consistent(participant, hce, nhce, benefiting_hce, benefiting_nhce):
        fail("ERR_CENSUS_INCONSISTENT")

    record = {
        "plan_document_id": plan["id"],
        "legal_name": legal_name,
        "ein": ein,
        "election_window_close_date": clockcal.fmt_date(window_close),
        "adoption_status": "APPLIED",
        "effective_adoption_date": None,
        "participant_count": participant,
        "hce_count": hce,
        "nhce_count": nhce,
        "benefiting_hce_count": benefiting_hce,
        "benefiting_nhce_count": benefiting_nhce,
        "hce_avg_deferral_pct": hce_avg,
        "nhce_avg_deferral_pct": nhce_avg,
        "is_small_plan": True,
        "employer_audit_required": False,
        "contribution_hold": False,
        "open_correction_count": 0,
        "account_balance_cents": 0,
        "contribution_receivable_cents": 0,
        "revenue_sharing_credit_cents": 0,
        "exited_at": None,
    }
    recompute.employer_census_flags(record)
    store.insert("employers", record)

    plan["cumulative_enrolled_participant_count"] += participant
    recompute.recompute_plan(plan, authz.touch())
    return envelope.ok_created(envelope.VIEWS["employers"](record))


@bp.get("/pep/adopting-employers/<emp_id>")
def read_employer(emp_id):
    authz.identify()
    authz.authorize("RegulatorOps", "PooledPlanProvider", "AdoptingEmployer")
    employer = need("employers", emp_id, "ERR_ADOPTING_EMPLOYER_NOT_FOUND")
    authz.own(plan=store.plan_of_employer(employer), employer=employer)
    return envelope.ok_object(envelope.VIEWS["employers"](employer))


@bp.patch("/pep/adopting-employers/<emp_id>/census")
def restate_census(emp_id):
    authz.identify()
    authz.authorize("AdoptingEmployer", "PooledPlanProvider")
    employer = need("employers", emp_id, "ERR_ADOPTING_EMPLOYER_NOT_FOUND")
    plan = store.plan_of_employer(employer)
    authz.own(plan=plan, employer=employer)

    b = validate.body()
    participant = validate.req_int(b, "participant_count", 0)
    hce = validate.req_int(b, "hce_count", 0)
    nhce = validate.req_int(b, "nhce_count", 0)
    benefiting_hce = validate.req_int(b, "benefiting_hce_count", 0)
    benefiting_nhce = validate.req_int(b, "benefiting_nhce_count", 0)
    hce_avg = validate.opt_num(b, "hce_avg_deferral_pct", 0, 25, 2, None)
    nhce_avg = validate.opt_num(b, "nhce_avg_deferral_pct", 0, 25, 2, None)

    if employer["adoption_status"] != "ACTIVE":
        fail("ERR_EMPLOYER_INVALID_STATE")

    if not _census_consistent(participant, hce, nhce, benefiting_hce, benefiting_nhce):
        fail("ERR_CENSUS_INCONSISTENT")

    delta = participant - employer["participant_count"]
    employer["participant_count"] = participant
    employer["hce_count"] = hce
    employer["nhce_count"] = nhce
    employer["benefiting_hce_count"] = benefiting_hce
    employer["benefiting_nhce_count"] = benefiting_nhce
    if hce_avg is not None:
        employer["hce_avg_deferral_pct"] = hce_avg
    if nhce_avg is not None:
        employer["nhce_avg_deferral_pct"] = nhce_avg
    recompute.employer_census_flags(employer)

    touch = authz.touch()
    touch.bump(employer)
    plan["cumulative_enrolled_participant_count"] += delta
    recompute.recompute_plan(plan, touch)
    return envelope.ok_object(envelope.VIEWS["employers"](employer))


def _employer_sub_list(emp_id, roles, rows_fn, collection):
    authz.identify()
    authz.authorize(*roles)
    employer = need("employers", emp_id, "ERR_ADOPTING_EMPLOYER_NOT_FOUND")
    authz.own(plan=store.plan_of_employer(employer), employer=employer)
    return envelope.paginate(rows_fn(employer), envelope.VIEWS[collection])


@bp.get("/pep/adopting-employers/<emp_id>/design-elections")
def list_employer_elections(emp_id):
    return _employer_sub_list(
        emp_id,
        ("RegulatorOps", "PooledPlanProvider", "AdoptingEmployer"),
        store.elections_of_employer,
        "elections",
    )


@bp.get("/pep/adopting-employers/<emp_id>/payroll-batches")
def list_employer_batches(emp_id):
    return _employer_sub_list(
        emp_id,
        ("RegulatorOps", "PooledPlanProvider", "AdoptingEmployer", "ServiceProvider"),
        store.batches_of_employer,
        "batches",
    )


@bp.get("/pep/adopting-employers/<emp_id>/compliance-tests")
def list_employer_tests(emp_id):
    return _employer_sub_list(
        emp_id,
        ("RegulatorOps", "PooledPlanProvider", "AdoptingEmployer"),
        lambda e: store.where("tests", adopting_employer_id=e["id"]),
        "tests",
    )


@bp.get("/pep/adopting-employers/<emp_id>/exit-transfers")
def list_employer_exits(emp_id):
    return _employer_sub_list(
        emp_id,
        ("RegulatorOps", "PooledPlanProvider", "AdoptingEmployer"),
        store.exits_of_employer,
        "exits",
    )


# ==========================================================================
# PlanDesignElection
# ==========================================================================


@bp.post("/pep/plan-design-elections")
def create_election():
    authz.identify()
    authz.authorize("AdoptingEmployer")
    b = validate.body()

    employer = validate.resolve_fk(
        b, "adopting_employer_id", "employers", "ERR_ADOPTING_EMPLOYER_NOT_FOUND"
    )
    authz.own_if(
        plan=store.plan_of_employer(employer) if employer else None, employer=employer
    )

    validate.require_fk_shape(b, "adopting_employer_id")
    min_age = validate.req_int(b, "eligibility_min_age", 18, 21)
    months = validate.req_int(b, "eligibility_service_months", 0, 12)
    vesting = validate.req_enum(b, "vesting_schedule", VESTING_SCHEDULES)
    match_code = validate.req_enum(b, "match_formula_code", MATCH_FORMULA_CODES)
    expected = validate.req_int(b, "expected_adopting_employer_version")
    tier_1_pct = validate.opt_num(b, "match_tier_1_pct", 0, 100, 2, None)
    tier_1_limit = validate.opt_num(b, "match_tier_1_limit_pct", 0, 15, 2, None)
    tier_2_pct = validate.opt_num(b, "match_tier_2_pct", 0, 100, 2, None)
    tier_2_limit = validate.opt_num(b, "match_tier_2_limit_pct", 0, 15, 2, None)

    if expected != employer["version"]:
        fail("ERR_STALE_EMPLOYER_VERSION")

    if employer["adoption_status"] not in ELECTION_CREATE_STATUSES:
        fail("ERR_EMPLOYER_INVALID_STATE")

    supplied = [
        v for v in (tier_1_pct, tier_1_limit, tier_2_pct, tier_2_limit)
        if v is not None
    ]
    if match_code == "DISCRETIONARY_TIERED":
        if len(supplied) != 4:
            fail("ERR_TIER_FIELDS_MISMATCH")
    elif supplied:
        fail("ERR_TIER_FIELDS_MISMATCH")

    if match_code == "DISCRETIONARY_TIERED" and tier_2_limit < tier_1_limit:
        fail("ERR_TIER_LIMITS_OUT_OF_ORDER")

    touch = authz.touch()
    existing = store.elections_of_employer(employer)
    sequence = len(existing) + 1

    for prior in existing:
        if prior["status"] in ("DRAFT", "SUBMITTED", "RETURNED"):
            prior["status"] = "SUPERSEDED"
            touch.bump(prior)

    if employer["adoption_status"] in ("ELECTIONS_SUBMITTED", "RETURNED_FOR_REVISION"):
        employer["adoption_status"] = "APPLIED"
    touch.bump(employer)

    track = (
        "SAFE_HARBOR_EXEMPT"
        if match_code in ("SAFE_HARBOR_BASIC", "SAFE_HARBOR_ENHANCED")
        else "ADP_ACP_TESTED"
    )
    record = store.insert(
        "elections",
        {
            "adopting_employer_id": employer["id"],
            "election_sequence": sequence,
            "eligibility_min_age": min_age,
            "eligibility_service_months": months,
            "vesting_schedule": vesting,
            "match_formula_code": match_code,
            "match_tier_1_pct": tier_1_pct,
            "match_tier_1_limit_pct": tier_1_limit,
            "match_tier_2_pct": tier_2_pct,
            "match_tier_2_limit_pct": tier_2_limit,
            "nondiscrimination_track": track,
            "status": "DRAFT",
            "signatory_name": None,
            "return_reason": None,
            "deficiency_code": None,
            "approved_at": None,
        },
    )
    return envelope.ok_created(envelope.VIEWS["elections"](record))


@bp.post("/pep/plan-design-elections/<election_id>/submit")
def submit_election(election_id):
    authz.identify()
    authz.authorize("AdoptingEmployer")
    election = need("elections", election_id, "ERR_DESIGN_ELECTION_NOT_FOUND")
    employer = store.employer_of_election(election)
    authz.own(plan=store.plan_of_employer(employer), employer=employer)

    b = validate.body()
    if "signatory_name" in b and b["signatory_name"] is not None:
        if not isinstance(b["signatory_name"], str):
            fail("ERR_VALIDATION", "`signatory_name` must be a string.")

    if election["status"] not in ("DRAFT", "RETURNED"):
        fail("ERR_ELECTION_INVALID_STATE")

    close = clockcal.parse_date(employer["election_window_close_date"])
    if clockcal.today() > close:
        fail("ERR_ELECTION_WINDOW_CLOSED")

    if election["match_formula_code"] == "DISCRETIONARY_TIERED":
        if any(election[f] is None for f in TIER_FIELDS):
            fail("ERR_TIER_FIELDS_MISMATCH")

    signatory = b.get("signatory_name")
    if not isinstance(signatory, str) or signatory.strip() == "":
        fail("ERR_SIGNATORY_REQUIRED")

    touch = authz.touch()
    election["status"] = "SUBMITTED"
    election["signatory_name"] = signatory
    election["return_reason"] = None
    election["deficiency_code"] = None
    touch.bump(election)
    employer["adoption_status"] = "ELECTIONS_SUBMITTED"
    touch.bump(employer)
    return envelope.ok_object(envelope.VIEWS["elections"](election))


@bp.post("/pep/plan-design-elections/<election_id>/return")
def return_election(election_id):
    authz.identify()
    authz.authorize("PooledPlanProvider")
    election = need("elections", election_id, "ERR_DESIGN_ELECTION_NOT_FOUND")
    employer = store.employer_of_election(election)
    authz.own(plan=store.plan_of_employer(employer), employer=employer)

    b = validate.body()
    reason = validate.req_str(b, "return_reason", 1, None)
    code = validate.req_enum(b, "deficiency_code", DEFICIENCY_CODES)

    if election["status"] != "SUBMITTED":
        fail("ERR_ELECTION_INVALID_STATE")

    touch = authz.touch()
    election["status"] = "RETURNED"
    election["return_reason"] = reason
    election["deficiency_code"] = code
    touch.bump(election)
    employer["adoption_status"] = "RETURNED_FOR_REVISION"
    touch.bump(employer)
    return envelope.ok_object(envelope.VIEWS["elections"](election))


@bp.post("/pep/plan-design-elections/<election_id>/approve")
def approve_election(election_id):
    authz.identify()
    authz.authorize("PooledPlanProvider")
    election = need("elections", election_id, "ERR_DESIGN_ELECTION_NOT_FOUND")
    employer = store.employer_of_election(election)
    plan = store.plan_of_employer(employer)
    authz.own(plan=plan, employer=employer)

    if plan["status"] != "ACTIVE":
        fail("ERR_PLAN_NOT_ACTIVE")
    if election["status"] != "SUBMITTED":
        fail("ERR_ELECTION_INVALID_STATE")
    if (
        election["eligibility_min_age"] > plan["base_eligibility_min_age"]
        or election["eligibility_service_months"]
        > plan["base_eligibility_service_months"]
    ):
        fail("ERR_ELIGIBILITY_MORE_RESTRICTIVE")
    if (
        VESTING_RANK[election["vesting_schedule"]]
        > VESTING_RANK[plan["base_vesting_schedule"]]
    ):
        fail("ERR_VESTING_MORE_RESTRICTIVE")

    touch = authz.touch()
    election["status"] = "APPROVED"
    election["approved_at"] = clockcal.stamp()
    touch.bump(election)
    employer["adoption_status"] = "ACTIVE"
    employer["effective_adoption_date"] = clockcal.fmt_date(clockcal.today())
    touch.bump(employer)
    recompute.recompute_plan(plan, touch)
    return envelope.ok_object(envelope.VIEWS["elections"](election))


@bp.get("/pep/plan-design-elections/<election_id>")
def read_election(election_id):
    authz.identify()
    authz.authorize("RegulatorOps", "PooledPlanProvider", "AdoptingEmployer")
    election = need("elections", election_id, "ERR_DESIGN_ELECTION_NOT_FOUND")
    employer = store.employer_of_election(election)
    authz.own(plan=store.plan_of_employer(employer), employer=employer)
    return envelope.ok_object(envelope.VIEWS["elections"](election))
