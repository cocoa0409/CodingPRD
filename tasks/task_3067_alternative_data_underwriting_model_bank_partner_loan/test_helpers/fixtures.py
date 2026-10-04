"""Composite setup helpers.

The server restarts with an empty database before every test, so every helper
builds its full precondition chain from scratch using only PRD-declared
endpoints. Setup calls use the lenient get_success_data() so failures surface
as clear "Setup failed" messages rather than confusing assertion errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_applicant_payload,
    create_application_payload,
    create_attestation_payload,
    create_credit_box_payload,
    create_fairness_review_payload,
    create_model_version_payload,
    create_partner_payload,
    create_securitization_pool_payload,
)
from .test_users import TEST_USERS

RO_CREATE = TEST_USERS["risk_officer_creator_headers"]
RO_VALIDATE = TEST_USERS["risk_officer_validator_headers"]
RO_ATTEST = TEST_USERS["risk_officer_attester_headers"]
PA = TEST_USERS["partner_admin_headers"]
PA_TWO = TEST_USERS["partner_admin_two_headers"]
PAD = TEST_USERS["platform_admin_headers"]
VO_ONE = TEST_USERS["verification_officer_headers"]
VO_TWO = TEST_USERS["verification_officer_two_headers"]
SA = TEST_USERS["servicing_agent_headers"]
CA = TEST_USERS["collections_agent_headers"]
AU = TEST_USERS["auditor_headers"]

_counter = {"n": 0}


def _seq() -> int:
    _counter["n"] += 1
    return _counter["n"]


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def create_active_model(variables=None, model_code=None, score_floor=0, score_ceiling=1000):
    """Create a model and walk it DRAFT -> VALIDATED -> ACTIVE through the
    full governance chain: a different officer validates than created, a
    DISPARATE_IMPACT review is opened and decided PASSED, then activation."""
    code = model_code or f"ADU-{_seq():04d}"
    payload = create_model_version_payload(
        model_code=code,
        score_floor=score_floor,
        score_ceiling=score_ceiling,
    )
    if variables is not None:
        payload["variables"] = variables
    resp = api_client.create_model_version(payload, RO_CREATE)
    assert resp.status_code == 201, f"Setup failed: create model: {resp.text}"
    model = get_success_data(resp)

    resp = api_client.validate_model_version(model["id"], RO_VALIDATE)
    assert resp.status_code == 200, f"Setup failed: validate model: {resp.text}"

    review_payload = create_fairness_review_payload(model["id"])
    resp = api_client.create_fairness_review(review_payload, RO_CREATE)
    assert resp.status_code == 201, f"Setup failed: create fairness review: {resp.text}"
    review = get_success_data(resp)

    resp = api_client.decide_fairness_review(review["id"], {"outcome": "PASSED"}, RO_CREATE)
    assert resp.status_code == 200, f"Setup failed: decide fairness review: {resp.text}"

    resp = api_client.activate_model_version(model["id"], RO_CREATE)
    assert resp.status_code == 200, f"Setup failed: activate model: {resp.text}"
    return get_success_data(resp)


def create_partner(activated=True, activator=PA, **overrides):
    """Create a partner (ONBOARDING); optionally activate it.

    `activator` is the headers used for activation — its X-User-ID becomes the
    recorded activator for the charge-off segregation-of-duties check.
    """
    payload = create_partner_payload(**overrides)
    resp = api_client.create_partner(payload, PA)
    assert resp.status_code == 201, f"Setup failed: create partner: {resp.text}"
    partner = get_success_data(resp)
    if activated:
        resp = api_client.activate_partner(partner["id"], activator)
        assert resp.status_code == 200, f"Setup failed: activate partner: {resp.text}"
        partner = get_success_data(resp)
    return partner


def attach_active_credit_box(partner_id, **box_overrides):
    """Create a DRAFT credit box under the partner and activate it, reading
    the partner's current version first for the expected_partner_version OCC
    field. Returns the activated CreditBox."""
    box_payload = create_credit_box_payload(**box_overrides)
    resp = api_client.create_credit_box(partner_id, box_payload, PA)
    assert resp.status_code == 201, f"Setup failed: create credit box: {resp.text}"
    box = get_success_data(resp)

    partner = get_success_data(api_client.get_partner(partner_id, PA))
    resp = api_client.activate_credit_box(
        partner_id, box["id"], {"expected_partner_version": partner["version"]}, PA
    )
    assert resp.status_code == 200, f"Setup failed: activate credit box: {resp.text}"
    return get_success_data(resp)


def create_applicant(**overrides):
    payload = create_applicant_payload(**overrides)
    resp = api_client.create_applicant(payload, PAD)
    assert resp.status_code == 201, f"Setup failed: create applicant: {resp.text}"
    return get_success_data(resp)


def submit_application(applicant_id, **overrides):
    payload = create_application_payload(applicant_id, **overrides)
    resp = api_client.create_application(payload, PAD)
    assert resp.status_code == 201, f"Setup failed: create application: {resp.text}"
    return get_success_data(resp)


def get_verifications(application_id):
    resp = api_client.list_verifications(application_id, VO_ONE)
    assert resp.status_code == 200, f"Setup failed: list verifications: {resp.text}"
    data, _meta = validate_paginated(resp)
    return data


# ---------------------------------------------------------------------------
# Tier 3: verification lifecycle shortcuts
# ---------------------------------------------------------------------------

def pass_all_instant_checks(application_id, officer=VO_ONE):
    """Run the instant check on both PENDING verifications of a
    VERIFICATION_PENDING application. Returns the refreshed application dict
    (UNDERWRITTEN when both pass)."""
    verifications = get_verifications(application_id)
    for v in verifications:
        resp = api_client.instant_check_verification(application_id, v["id"], officer)
        assert resp.status_code == 200, f"Setup failed: instant check: {resp.text}"
    return get_success_data(api_client.get_application(application_id, PAD))


def fail_income_instant_check(application_id, officer=VO_ONE):
    """Run instant checks on both verifications of an application whose
    applicant fails the INCOME instant check (e.g. nsf_count == 3). Returns
    (application dict in DOCS_REQUIRED, income verification dict)."""
    verifications = get_verifications(application_id)
    income = next(v for v in verifications if v["kind"] == "INCOME")
    identity = next(v for v in verifications if v["kind"] == "IDENTITY")
    resp = api_client.instant_check_verification(application_id, identity["id"], officer)
    assert resp.status_code == 200, f"Setup failed: identity instant check: {resp.text}"
    resp = api_client.instant_check_verification(application_id, income["id"], officer)
    assert resp.status_code == 200, f"Setup failed: income instant check: {resp.text}"
    income = get_success_data(resp)
    app = get_success_data(api_client.get_application(application_id, PAD))
    return app, income


def manual_pass_verification(application_id, verification_id, officer=VO_TWO):
    """Render a manual PASS decision on a failed verification with an officer
    other than the instant checker. Returns the refreshed application dict."""
    resp = api_client.manual_decide_verification(
        application_id, verification_id, {"outcome": "PASS"}, officer
    )
    assert resp.status_code == 200, f"Setup failed: manual PASS decision: {resp.text}"
    return get_success_data(api_client.get_application(application_id, PAD))


def allocate(application_id):
    resp = api_client.allocate_application(application_id, PAD)
    assert resp.status_code == 200, f"Setup failed: allocate application: {resp.text}"
    return get_success_data(resp)


def find_loan_for_application(application_id):
    resp = api_client.list_loans(SA, params={"application_id": application_id})
    assert resp.status_code == 200, f"Setup failed: list loans: {resp.text}"
    data, _meta = validate_paginated(resp)
    assert len(data) >= 1, "Setup failed: no loan found for application"
    return data[0]


# ---------------------------------------------------------------------------
# Tier 2/4: full underwriting scenarios
# ---------------------------------------------------------------------------

def setup_underwritten_application(applicant_overrides=None, requested_amount_cents=5000000,
                                   model_variables=None, manual_review=False):
    """Active model + applicant + application walked to UNDERWRITTEN.

    With manual_review=True the applicant is forced through the manual
    document-review path (income instant check fails, then MANUAL_PASSED),
    engaging the reduced affordability ratio. Returns the application dict.
    """
    create_active_model(variables=model_variables)
    overrides = dict(applicant_overrides or {})
    if manual_review:
        overrides.setdefault("bank_account_nsf_count_90d", 3)
    applicant = create_applicant(**overrides)
    app = submit_application(applicant["id"], requested_amount_cents=requested_amount_cents)
    assert app["status"] == "VERIFICATION_PENDING", (
        f"Setup failed: expected VERIFICATION_PENDING, got {app['status']} "
        f"(risk_score {app.get('risk_score')} may be below the floor-reject threshold)"
    )
    if manual_review:
        _app, income = fail_income_instant_check(app["id"])
        app = manual_pass_verification(app["id"], income["id"], officer=VO_TWO)
    else:
        app = pass_all_instant_checks(app["id"])
    assert app["status"] == "UNDERWRITTEN", (
        f"Setup failed: expected UNDERWRITTEN, got {app['status']}"
    )
    return app


def setup_funded_loan(box_overrides=None, applicant_overrides=None, requested_amount_cents=5000000,
                      partner_overrides=None, partner_activator=PA):
    """Full chain: ACTIVE model -> ACTIVE bank partner with ACTIVE credit box
    -> clean applicant -> UNDERWRITTEN application -> allocated loan.

    Returns a bundle dict with keys: application, applicant, loan, partner,
    box, decision.
    """
    create_active_model()
    partner = create_partner(activator=partner_activator, **(partner_overrides or {}))
    box = attach_active_credit_box(partner["id"], **(box_overrides or {}))
    applicant = create_applicant(**(applicant_overrides or {}))
    app = submit_application(applicant["id"], requested_amount_cents=requested_amount_cents)
    app = pass_all_instant_checks(app["id"])
    assert app["status"] == "UNDERWRITTEN", (
        f"Setup failed: expected UNDERWRITTEN, got {app['status']}"
    )
    decision = allocate(app["id"])
    assert decision["channel"] == "PARTNER_RETAINED", (
        f"Setup failed: expected PARTNER_RETAINED allocation, got {decision['channel']} "
        f"with reason_codes {decision.get('reason_codes')}"
    )
    loan = find_loan_for_application(app["id"])
    return {
        "application": app,
        "applicant": applicant,
        "loan": loan,
        "partner": partner,
        "box": box,
        "decision": decision,
    }


def setup_securitized_loan(pool_overrides=None, applicant_overrides=None,
                           requested_amount_cents=5000000, trust_activator=PA_TWO):
    """Full chain landing the loan in a securitization pool: ACTIVE model ->
    ACTIVE trust partner (no banks/buyers exist) -> OPEN pool -> clean
    applicant -> UNDERWRITTEN application -> SECURITIZATION allocation.

    `trust_activator` defaults to a second PartnerAdmin operator so a later
    CollectionsAgent charge-off does not collide with the recorded activator.
    Returns a bundle dict with keys: application, applicant, loan, trust,
    pool, decision.
    """
    create_active_model()
    trust = create_partner(
        partner_type="SECURITIZATION_TRUST", legal_name="Test Trust", home_state="DE",
        activator=trust_activator,
    )
    pool_payload = create_securitization_pool_payload(trust["id"], **(pool_overrides or {}))
    resp = api_client.create_securitization_pool(pool_payload, PA)
    assert resp.status_code == 201, f"Setup failed: create pool: {resp.text}"
    pool = get_success_data(resp)

    applicant = create_applicant(**(applicant_overrides or {}))
    app = submit_application(applicant["id"], requested_amount_cents=requested_amount_cents)
    app = pass_all_instant_checks(app["id"])
    assert app["status"] == "UNDERWRITTEN", (
        f"Setup failed: expected UNDERWRITTEN, got {app['status']}"
    )
    decision = allocate(app["id"])
    assert decision["channel"] == "SECURITIZATION", (
        f"Setup failed: expected SECURITIZATION allocation, got {decision['channel']} "
        f"with reason_codes {decision.get('reason_codes')}"
    )
    loan = find_loan_for_application(app["id"])
    return {
        "application": app,
        "applicant": applicant,
        "loan": loan,
        "trust": trust,
        "pool": pool,
        "decision": decision,
    }


def advance_loan_periods(loan_id, periods):
    """Advance a loan through `periods` unpaid 30-day servicing periods.

    The default logical clock starts on 2026-09-01, so a freshly funded loan
    enters CURRENT immediately at funding (PRD 3.10 first-of-month rule). The
    first advance on a CURRENT loan lands it at 30 days delinquent, so the
    clock is moved forward first and `periods` advances then reach the
    intended `periods * 30` days of delinquency.

    Returns the final loan dict."""
    if periods >= 1:
        resp = api_client.set_clock({"to_iso8601": "2026-09-02T00:00:00Z"}, PAD)
        assert resp.status_code == 200, f"Setup failed: set clock: {resp.text}"
    loan = None
    for _ in range(periods):
        resp = api_client.advance_servicing(loan_id, SA)
        assert resp.status_code == 200, f"Setup failed: advance servicing: {resp.text}"
        loan = get_success_data(resp)
    if loan is None:
        loan = get_success_data(api_client.get_loan(loan_id, SA))
    return loan
