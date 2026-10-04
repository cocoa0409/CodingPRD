"""Composite setup helpers.

The review/billing/care chains in this API are long: reaching an ACCEPTED
application takes ~7 calls (hospital -> program -> source -> application ->
open-review -> vote x2 -> decide). These fixtures encapsulate the chains so
tests can focus on assertions. All fixtures build their preconditions from
scratch via the public API and use get_success_data() so setup failures
surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_allocation_payload,
    create_application_payload,
    create_fund_payload,
    create_hospital_payload,
    create_insurance_policy_payload,
    create_outreach_clinic_payload,
    create_program_payload,
    create_referral_source_payload,
    create_screening_payload,
    create_staged_procedure_payload,
    decide_payload,
    vote_payload,
)
from .test_users import (
    make_admin_headers,
    make_care_headers,
    make_intake_headers,
    make_outreach_headers,
    make_philanthropy_headers,
    make_reviewer_headers,
)


def _fail(context, resp):
    raise AssertionError(
        f"Setup failed at {context}: HTTP {resp.status_code} {resp.text[:400]}"
    )


def _data(resp, context):
    d = get_success_data(resp)
    if d is None or (isinstance(d, dict) and not d and resp.request.method == "POST"):
        _fail(context, resp)
    return d


# ---------------------------------------------------------------------------
# Tier 0: clock + single-entity creation
# ---------------------------------------------------------------------------

def set_clock(current_utc=TEST_DEFAULTS["CLOCK_START"]):
    """Advance the logical clock."""
    resp = api_client.set_clock(current_utc, make_admin_headers("admin-1"))
    return _data(resp, "set_clock")


def create_hospital(**overrides):
    """Create a hospital; returns the hospital dict."""
    payload = create_hospital_payload(**overrides)
    resp = api_client.create_hospital(payload, make_admin_headers("admin-1"))
    return _data(resp, "create_hospital")


def create_program(hospital_id, **overrides):
    """Create a program under a hospital."""
    resp = api_client.create_program(
        hospital_id, create_program_payload(**overrides), make_admin_headers("admin-1"),
    )
    return _data(resp, "create_program")


def create_referral_source(**overrides):
    """Register a referral source."""
    resp = api_client.create_referral_source(
        create_referral_source_payload(**overrides), make_admin_headers("admin-1"),
    )
    return _data(resp, "create_referral_source")


def create_application(referral_source_id, program_id, **overrides):
    """Submit an application as the IntakeCoordinator."""
    resp = api_client.create_application(
        create_application_payload(referral_source_id, program_id, **overrides),
        make_intake_headers("ic-1"),
    )
    return _data(resp, "create_application")


def create_fund(**overrides):
    """Create a philanthropic fund."""
    resp = api_client.create_fund(
        create_fund_payload(**overrides), make_philanthropy_headers("po-1"),
    )
    return _data(resp, "create_fund")


def create_allocation(fund_id, hospital_id, **overrides):
    """Pledge an allocation; returns the PLEDGED allocation."""
    resp = api_client.create_allocation(
        fund_id, create_allocation_payload(hospital_id, **overrides),
        make_philanthropy_headers("po-1"),
    )
    return _data(resp, "create_allocation")


def create_outreach_clinic(hospital_id, **overrides):
    """Propose an outreach clinic."""
    resp = api_client.create_outreach_clinic(
        hospital_id, create_outreach_clinic_payload(**overrides),
        make_outreach_headers("op-1"),
    )
    return _data(resp, "create_outreach_clinic")


def create_screening(clinic_id, **overrides):
    """Book a screening at a clinic."""
    resp = api_client.create_screening(
        clinic_id, create_screening_payload(**overrides), make_outreach_headers("op-1"),
    )
    return _data(resp, "create_screening")


# ---------------------------------------------------------------------------
# Tier 1: hospital + program + referral source baseline
# ---------------------------------------------------------------------------

def setup_hospital_with_program(hospital_overrides=None, program_overrides=None,
                                source_overrides=None):
    """Hospital + one program + one US referral source.
    Returns (hospital, program, referral_source)."""
    hospital = create_hospital(**(hospital_overrides or {}))
    program = create_program(hospital["id"], **(program_overrides or {}))
    source = create_referral_source(**(source_overrides or {}))
    return hospital, program, source


def setup_standard_intake(**overrides):
    """The standard intake topology used by most tests: hospital H1 at
    (45.0, -122.0) with capacity 5, an ORTHOPEDIC program with age window
    0..215 (non-staged), and a US community-physician referral source.
    Returns (hospital, program, referral_source)."""
    return setup_hospital_with_program(
        hospital_overrides=overrides.get("hospital_overrides"),
        program_overrides=overrides.get("program_overrides"),
        source_overrides=overrides.get("source_overrides"),
    )


# ---------------------------------------------------------------------------
# Tier 2: application lifecycle — open review and vote accumulation
# ---------------------------------------------------------------------------

def setup_submitted_application(patient_full_name="Kid One",
                                patient_date_of_birth="2020-01-01T00:00:00Z",
                                home_latitude=45.0, home_longitude=-121.0,
                                condition_category="ORTHOPEDIC",
                                program_overrides=None, hospital_overrides=None,
                                source_overrides=None, **extra):
    """Standard intake + one SUBMITTED application.
    Returns (hospital, program, source, application)."""
    hospital, program, source = setup_hospital_with_program(
        hospital_overrides=hospital_overrides,
        program_overrides=program_overrides,
        source_overrides=source_overrides,
    )
    application = create_application(
        source["id"], program["id"],
        patient_full_name=patient_full_name,
        patient_date_of_birth=patient_date_of_birth,
        condition_category=condition_category,
        home_latitude=home_latitude, home_longitude=home_longitude,
        **extra,
    )
    return hospital, program, source, application


def open_review(application_id, reviewer="rcm-1"):
    resp = api_client.open_review(application_id, make_reviewer_headers(reviewer))
    return _data(resp, "open_review")


def cast_vote(application_id, vote="ACCEPT", vote_weight=1, reviewer="rcm-1"):
    resp = api_client.cast_vote(
        application_id, vote_payload(vote=vote, vote_weight=vote_weight),
        make_reviewer_headers(reviewer),
    )
    return _data(resp, "cast_vote")


def setup_application_with_accept_quorum(**kwargs):
    """Application opened in PENDING_REVIEW with accept weight 3 on the round
    (vote 2 by rcm-1, vote 1 by rcm-2). Returns (hospital, program, source,
    application)."""
    hospital, program, source, application = setup_submitted_application(**kwargs)
    open_review(application["id"])
    cast_vote(application["id"], vote="ACCEPT", vote_weight=2, reviewer="rcm-1")
    cast_vote(application["id"], vote="ACCEPT", vote_weight=1, reviewer="rcm-2")
    return hospital, program, source, application


def get_application(application_id, reviewer="rcm-1"):
    resp = api_client.get_application(application_id, make_reviewer_headers(reviewer))
    return _data(resp, "get_application")


def decide(application_id, decision="ACCEPT", decision_reason="ok",
           expected_application_version=None, reviewer="rcm-3"):
    """Decide an application. When expected_application_version is None the
    current version is read fresh from the API."""
    if expected_application_version is None:
        current = get_application(application_id)
        expected_application_version = current["version"]
    resp = api_client.decide_application(
        application_id,
        decide_payload(
            decision=decision, decision_reason=decision_reason,
            expected_application_version=expected_application_version,
        ),
        make_reviewer_headers(reviewer),
    )
    return _data(resp, "decide")


# ---------------------------------------------------------------------------
# Tier 3: acceptance cascades — billing account / care plan
# ---------------------------------------------------------------------------

def setup_accepted_application(with_insurance=False, **kwargs):
    """Full acceptance chain: intake -> open-review -> accept quorum -> decide.
    When with_insurance=True a VERIFIED coverage policy is attached before
    acceptance so the auto-created billing account links it.
    Returns (hospital, program, source, application, billing_account)."""
    hospital, program, source, application = setup_application_with_accept_quorum(**kwargs)
    if with_insurance:
        resp = api_client.create_insurance_policy(
            application["id"], create_insurance_policy_payload(),
            make_intake_headers("ic-1"),
        )
        _data(resp, "create_insurance_policy")
    decide(application["id"], decision="ACCEPT", decision_reason="ok")
    resp = api_client.get_application_billing_account(
        application["id"], make_care_headers("cc-1"),
    )
    accounts = _data(resp, "get_application_billing_account")
    if isinstance(accounts, dict):
        accounts = accounts.get("data") or accounts.get("items") or []
    assert len(accounts) == 1, "Setup failed: expected exactly one billing account"
    return hospital, program, source, application, accounts[0]


def get_care_plan_for_application(application_id):
    resp = api_client.get_application_care_plan(
        application_id, make_care_headers("cc-1"),
    )
    plans = _data(resp, "get_application_care_plan")
    if isinstance(plans, dict):
        plans = plans.get("data") or plans.get("items") or []
    assert len(plans) == 1, "Setup failed: expected exactly one care plan"
    return plans[0]


def setup_accepted_staged_application(**kwargs):
    """Acceptance into a staged (BURN) program: auto-creates a CarePlan.
    Returns (hospital, program, source, application, billing_account, care_plan)."""
    kwargs.setdefault("condition_category", "BURN")
    kwargs["program_overrides"] = dict(
        {"category": "BURN", "staged_care_required": True},
        **(kwargs.get("program_overrides") or {}),
    )
    hospital, program, source, application, account = setup_accepted_application(**kwargs)
    care_plan = get_care_plan_for_application(application["id"])
    return hospital, program, source, application, account, care_plan


def add_stage(care_plan_id, **overrides):
    resp = api_client.create_staged_procedure(
        care_plan_id, create_staged_procedure_payload(**overrides),
        make_care_headers("cc-1"),
    )
    return _data(resp, "add_stage")


def get_care_plan(care_plan_id):
    resp = api_client.get_care_plan(care_plan_id, make_care_headers("cc-1"))
    return _data(resp, "get_care_plan")


def schedule_stage(stage_id):
    resp = api_client.schedule_stage(stage_id, make_care_headers("cc-1"))
    return _data(resp, "schedule_stage")


def get_stage(stage_id):
    resp = api_client.get_staged_procedure(stage_id, make_care_headers("cc-1"))
    return _data(resp, "get_stage")


def setup_care_plan_with_scheduled_stage(stage_overrides=None, **kwargs):
    """Staged (BURN) acceptance + one stage created and SCHEDULED; the plan is
    ACTIVE_TREATMENT. Returns (hospital, program, source, application,
    billing_account, care_plan, stage)."""
    hospital, program, source, application, account, plan = (
        setup_accepted_staged_application(**kwargs)
    )
    stage = add_stage(plan["id"], **(stage_overrides or {}))
    schedule_stage(stage["id"])
    plan = get_care_plan(plan["id"])
    return hospital, program, source, application, account, plan, stage


# ---------------------------------------------------------------------------
# Tier 4: funds / allocations
# ---------------------------------------------------------------------------

def get_fund(fund_id):
    resp = api_client.get_fund(fund_id, make_philanthropy_headers("po-1"))
    return _data(resp, "get_fund")


def commit_allocation(allocation_id, expected_fund_version=None):
    if expected_fund_version is None:
        alloc = api_client.get_allocation(allocation_id, make_philanthropy_headers("po-1"))
        alloc_data = _data(alloc, "get_allocation")
        expected_fund_version = get_fund(alloc_data["fund_id"])["version"]
    resp = api_client.commit_allocation(
        allocation_id, expected_fund_version, make_philanthropy_headers("po-1"),
    )
    return _data(resp, "commit_allocation")


def setup_fund_with_pledge(total_committed_cents=100000, amount_cents=5000,
                           hospital_id=None, hospital_overrides=None, **alloc_overrides):
    """Hospital + fund + one PLEDGED allocation against the hospital.
    Returns (hospital, fund, allocation)."""
    hospital = (
        create_hospital(**(hospital_overrides or {})) if hospital_id is None
        else {"id": hospital_id}
    )
    fund = create_fund(total_committed_cents=total_committed_cents)
    allocation = create_allocation(fund["id"], hospital["id"], amount_cents=amount_cents,
                                   **alloc_overrides)
    return hospital, fund, allocation


# ---------------------------------------------------------------------------
# Tier 5: outreach clinics and screenings
# ---------------------------------------------------------------------------

def get_clinic(clinic_id):
    resp = api_client.get_outreach_clinic(clinic_id, make_outreach_headers("op-1"))
    return _data(resp, "get_clinic")


def get_screening(screening_id):
    resp = api_client.get_screening(screening_id, make_outreach_headers("op-1"))
    return _data(resp, "get_screening")


def setup_confirmed_clinic(hospital_id=None, clinic_overrides=None, **hospital_overrides):
    """Hospital + one PROPOSED clinic that is then CONFIRMED.
    Returns (hospital, clinic)."""
    hospital = create_hospital(**hospital_overrides) if hospital_id is None else {"id": hospital_id}
    clinic = create_outreach_clinic(hospital["id"], **(clinic_overrides or {}))
    resp = api_client.confirm_clinic(clinic["id"], make_outreach_headers("op-1"))
    _data(resp, "confirm_clinic")
    return hospital, get_clinic(clinic["id"])
