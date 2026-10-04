"""Composite setup helpers.

Every fixture builds its preconditions from scratch through declared endpoints:
the server is restarted before each test, so no entity survives between tests.
All setup calls use the lenient `get_success_data()` validator so a setup
problem surfaces as a clear "Setup failed" rather than a confusing assertion.
"""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID, get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_START,
    FULL_MARK_SCORE_INPUTS,
    FUTURE_LICENSE_EXPIRES_ON,
    FUTURE_LOCK_EXPIRES_AT,
    STANDARD_LOAN_AMOUNT_CENTS,
    STANDARD_PLAN_BORROWER_PAID_CENTS,
    STANDARD_PLAN_LENDER_PAID_CENTS,
    STANDARD_VOLUME_EXPECTATION_CENTS,
    ltv_band_label,
)
from .factories import (
    broker_payload,
    compensation_plan_payload,
    exclusivity_policy_payload,
    financial_review_payload,
    license_payload,
    loan_submission_payload,
    next_nmls_id,
    pricing_quote_payload,
    product_eligibility_payload,
    rate_sheet_payload,
)
from .test_users import (
    NAMED_QC_ANALYST_ID,
    NAMED_UNDERWRITER_ID,
    TEST_USERS,
    make_broker_headers,
    make_channel_manager_headers,
    make_compliance_officer_headers,
    make_platform_admin_headers,
    make_qc_analyst_headers,
    make_underwriter_headers,
)

CM = TEST_USERS["channel_manager_headers"]
UW = make_underwriter_headers()
QC = make_qc_analyst_headers()
CO = make_compliance_officer_headers()
PA = make_platform_admin_headers()
ANY = TEST_USERS["any_headers"]


def _data(response, what: str) -> dict:
    assert response.status_code < 300, (
        f"Setup failed: {what} returned {response.status_code}: {response.text[:400]}"
    )
    return get_success_data(response)


def set_clock(to_iso8601: str = CLOCK_START) -> dict:
    return _data(api_client.set_current_utc(to_iso8601, PA), f"set clock to {to_iso8601}")


def reset_clock() -> dict:
    return set_clock(CLOCK_START)


def broker_version(broker_id: str) -> int:
    return _data(api_client.get_broker(broker_id, ANY), "get broker")["version"]


def get_broker(broker_id: str) -> dict:
    return _data(api_client.get_broker(broker_id, ANY), "get broker")


# ---------------------------------------------------------------------------
# Tier 1 — entity creation and state progression
# ---------------------------------------------------------------------------

def create_submitted_broker(legal_name: str = "Test Wholesale Brokerage LLC",
                            nmls_id: str = None, home_state: str = "TX",
                            volume_expectation_cents: int = STANDARD_VOLUME_EXPECTATION_CENTS) -> dict:
    """A brand-new broker in SUBMITTED, with the full derived baseline."""
    payload = broker_payload(
        legal_name=legal_name,
        nmls_id=nmls_id or next_nmls_id(),
        home_state=home_state,
        volume_expectation_cents=volume_expectation_cents,
    )
    return _data(api_client.create_broker(payload, CM), "create broker")


def record_license(broker_id: str, state_code: str = "TX",
                   license_number: str = None,
                   license_type: str = "MORTGAGE_BROKER",
                   expires_on: str = FUTURE_LICENSE_EXPIRES_ON) -> dict:
    payload = license_payload(
        state_code=state_code,
        license_number=license_number or f"{state_code}-MB-{broker_id[:8]}",
        license_type=license_type,
        expires_on=expires_on,
    )
    return _data(api_client.create_license(broker_id, payload, CM), "record license")


def record_financial_review(broker_id: str, **overrides) -> dict:
    payload = financial_review_payload(**overrides)
    return _data(api_client.create_financial_review(broker_id, payload, CM), "record financial review")


def pass_financial_review(review_id: str) -> dict:
    return _data(
        api_client.decide_financial_review(review_id, {"outcome": "PASSED"}, CM),
        "pass financial review",
    )


def record_and_pass_financial_review(broker_id: str, **overrides) -> dict:
    """Records a review and immediately decides it PASSED. Returns the review."""
    review = record_financial_review(broker_id, **overrides)
    return pass_financial_review(review["id"])


def request_product_eligibility(broker_id: str, **overrides) -> dict:
    payload = product_eligibility_payload(**overrides)
    return _data(
        api_client.create_product_eligibility(broker_id, payload, CM),
        "request product eligibility",
    )


def approve_product_eligibility(eligibility_id: str, expected_broker_version: int) -> dict:
    return _data(
        api_client.decide_product_eligibility(
            eligibility_id,
            {"outcome": "APPROVED", "expected_broker_version": expected_broker_version},
            CM,
        ),
        "approve product eligibility",
    )


def request_and_approve_eligibility(broker_id: str, **overrides) -> dict:
    payload = product_eligibility_payload(**overrides)
    eligibility = _data(
        api_client.create_product_eligibility(broker_id, payload, CM),
        "request product eligibility",
    )
    return approve_product_eligibility(eligibility["id"], broker_version(broker_id))


def create_compensation_plan(broker_id: str, plan_code: str = "PLAN_A",
                             default_election: str = "LENDER_PAID",
                             lender_paid_amount_cents: int = STANDARD_PLAN_LENDER_PAID_CENTS,
                             borrower_paid_amount_cents: int = STANDARD_PLAN_BORROWER_PAID_CENTS,
                             is_active: bool = True) -> dict:
    payload = compensation_plan_payload(
        broker_id,
        plan_code=plan_code,
        default_election=default_election,
        lender_paid_amount_cents=lender_paid_amount_cents,
        borrower_paid_amount_cents=borrower_paid_amount_cents,
        is_active=is_active,
    )
    return _data(api_client.create_compensation_plan(payload, CM), "create compensation plan")


def approve_broker(broker_id: str) -> dict:
    return _data(api_client.approve_broker(broker_id, CM), "approve broker")


def create_and_approve_broker(state_code: str = "TX",
                             license_expires_on: str = FUTURE_LICENSE_EXPIRES_ON,
                             review_overrides: dict = None,
                             **broker_overrides) -> dict:
    """Broker -> licence -> PASSED review -> approved. Returns the broker."""
    broker = create_submitted_broker(**broker_overrides)
    broker_id = broker["id"]
    record_license(broker_id, state_code=state_code, expires_on=license_expires_on)
    record_and_pass_financial_review(broker_id, **(review_overrides or {}))
    return approve_broker(broker_id)


def publish_rate_sheet(broker_id: str, product_code: str = "CONVENTIONAL",
                       base_rate_pct: float = 6.125, adjustment_table: list = None) -> dict:
    payload = rate_sheet_payload(
        product_code=product_code,
        base_rate_pct=base_rate_pct,
        adjustment_table=adjustment_table if adjustment_table is not None else rate_sheet_payload()["adjustment_table"],
    )
    return _data(api_client.publish_rate_sheet(broker_id, payload, CM), "publish rate sheet")


def price_quote(broker_id: str, sheet: dict, **overrides) -> dict:
    payload = pricing_quote_payload(**overrides)
    payload["expected_rate_sheet_version"] = overrides.get(
        "expected_rate_sheet_version", sheet["version"]
    )
    return _data(
        api_client.create_pricing_quote(sheet["id"], payload, make_broker_headers(broker_id)),
        "price quote",
    )


def submit_loan(broker_id: str, quote: dict, **overrides) -> dict:
    payload = loan_submission_payload(broker_id, quote["id"], **overrides)
    return _data(
        api_client.create_loan_submission(payload, make_broker_headers(broker_id)),
        "submit loan",
    )


def underwrite_loan(loan_id: str, expected_broker_version: int,
                    underwriter_id: str = NAMED_UNDERWRITER_ID) -> dict:
    return _data(
        api_client.underwrite_loan(
            loan_id, {"expected_broker_version": expected_broker_version},
            make_underwriter_headers(underwriter_id),
        ),
        "underwrite loan",
    )


def record_decision(loan_id: str, decision_type: str = "CONDITIONAL",
                    conditions: list = None, decision_notes: str = "decision",
                    underwriter_id: str = NAMED_UNDERWRITER_ID) -> dict:
    payload = {
        "loan_submission_id": loan_id,
        "decision_type": decision_type,
        "decision_notes": decision_notes,
    }
    if decision_type == "CONDITIONAL":
        payload["conditions"] = conditions if conditions is not None else ["standard conditions"]
    elif conditions is not None:
        payload["conditions"] = conditions
    return _data(
        api_client.create_underwriting_decision(payload, make_underwriter_headers(underwriter_id)),
        f"record {decision_type} decision",
    )


# ---------------------------------------------------------------------------
# Tier 2 — the full scenario the majority of pricing / loan tests need
# ---------------------------------------------------------------------------

def setup_full_scenario(state_code: str = "TX",
                        license_expires_on: str = FUTURE_LICENSE_EXPIRES_ON,
                        review_overrides: dict = None,
                        product_code: str = "CONVENTIONAL",
                        base_rate_pct: float = 6.125,
                        adjustment_table: list = None,
                        eligibility_overrides: dict = None,
                        plan_code: str = "PLAN_A",
                        plan_default: str = "LENDER_PAID",
                        quote_overrides: dict = None,
                        loan_overrides: dict = None,
                        with_borrower_plan: bool = False,
                        legal_name: str = "Test Wholesale Brokerage LLC",
                        volume_expectation_cents: int = STANDARD_VOLUME_EXPECTATION_CENTS) -> dict:
    """Approved broker + licence + eligibility + plan(s) + sheet + quote + SUBMITTED loan.

    Returns a dict with every captured entity and the broker version at each step.
    """
    broker = create_submitted_broker(
        legal_name=legal_name,
        home_state=state_code,
        volume_expectation_cents=volume_expectation_cents,
    )
    b = broker["id"]
    license_ = record_license(b, state_code=state_code, expires_on=license_expires_on)
    review = record_and_pass_financial_review(b, **(review_overrides or {}))
    eligibility = request_and_approve_eligibility(b, **(eligibility_overrides or {}))
    plan = create_compensation_plan(b, plan_code=plan_code, default_election=plan_default)
    plan_borrower = None
    if with_borrower_plan:
        plan_borrower = create_compensation_plan(
            b, plan_code="PLAN_B", default_election="BORROWER_PAID",
        )
    broker = approve_broker(b)
    sheet = publish_rate_sheet(
        b, product_code=product_code, base_rate_pct=base_rate_pct,
        adjustment_table=adjustment_table,
    )
    quote = price_quote(b, sheet, **(quote_overrides or {}))
    sheet = _data(api_client.get_rate_sheet(sheet["id"], ANY), "re-read sheet")
    loan = submit_loan(
        b, quote,
        property_state=state_code,
        compensation_election=plan_default,
        comp_plan_id=plan["id"],
        **(loan_overrides or {}),
    )
    return {
        "broker": get_broker(b),
        "broker_id": b,
        "license": license_,
        "review": review,
        "eligibility": eligibility,
        "plan": plan,
        "plan_borrower": plan_borrower,
        "sheet": sheet,
        "quote": quote,
        "loan": loan,
        "loan_id": loan["id"],
    }


def setup_loan_in_state(target_state: str, **scenario_kwargs) -> dict:
    """Build the full scenario and walk the loan forward to `target_state`."""
    scenario = setup_full_scenario(**scenario_kwargs)
    loan_id = scenario["loan_id"]
    b = scenario["broker_id"]

    if target_state == "SUBMITTED":
        return scenario

    underwrite_loan(loan_id, broker_version(b))
    if target_state == "UNDERWRITING":
        return scenario

    if target_state in ("CONDITIONAL_APPROVAL", "CLEAR_TO_CLOSE", "FUNDED", "REPURCHASED"):
        record_decision(loan_id, "CONDITIONAL")
        if target_state == "CONDITIONAL_APPROVAL":
            return scenario

    if target_state in ("CLEAR_TO_CLOSE", "FUNDED", "REPURCHASED"):
        _data(api_client.clear_to_close_loan(loan_id, make_underwriter_headers()), "clear to close")
        if target_state == "CLEAR_TO_CLOSE":
            return scenario

    if target_state in ("FUNDED", "REPURCHASED"):
        _data(api_client.fund_loan(loan_id, make_underwriter_headers()), "fund loan")
        if target_state == "FUNDED":
            return scenario

    raise ValueError(f"unsupported target_state {target_state!r}")


def setup_suspended_review_loan(**scenario_kwargs) -> dict:
    """Loan at SUSPENDED_REVIEW via an underwriter SUSPENDED decision."""
    scenario = setup_full_scenario(**scenario_kwargs)
    loan_id = scenario["loan_id"]
    underwrite_loan(loan_id, broker_version(scenario["broker_id"]))
    record_decision(loan_id, "SUSPENDED", decision_notes="missing income documentation")
    scenario["loan"] = _data(api_client.get_loan_submission(loan_id, ANY), "re-read loan")
    return scenario


def setup_funded_loan(**scenario_kwargs) -> dict:
    return setup_loan_in_state("FUNDED", **scenario_kwargs)


def setup_clear_to_close_loan(**scenario_kwargs) -> dict:
    return setup_loan_in_state("CLEAR_TO_CLOSE", **scenario_kwargs)


def setup_conditional_approval_loan(**scenario_kwargs) -> dict:
    return setup_loan_in_state("CONDITIONAL_APPROVAL", **scenario_kwargs)


# ---------------------------------------------------------------------------
# Tier 3 — quality-control fixtures
# ---------------------------------------------------------------------------

def open_qc_review(loan_id: str, defect_type: str = "NON_DEFECT",
                   severity: str = "MINOR", remediation_status: str = "NONE",
                   reviewer_id: str = NAMED_QC_ANALYST_ID) -> dict:
    payload = {
        "loan_submission_id": loan_id,
        "defect_type": defect_type,
        "severity": severity,
        "remediation_status": remediation_status,
    }
    return _data(
        api_client.create_quality_control_review(payload, make_qc_analyst_headers(reviewer_id)),
        "open quality control review",
    )


def resolve_qc_review(review_id: str, resolution_type: str = "REMEDIATED",
                      resolution_note: str = "corrected documentation supplied by broker",
                      reviewer_id: str = NAMED_QC_ANALYST_ID) -> dict:
    payload = {"resolution_type": resolution_type, "resolution_note": resolution_note}
    return _data(
        api_client.resolve_quality_control_review(
            review_id, payload, make_qc_analyst_headers(reviewer_id)
        ),
        "resolve quality control review",
    )


def setup_funded_loan_with_review(defect_type: str = "NON_DEFECT", severity: str = "MINOR",
                                  remediation_status: str = "NONE",
                                  **scenario_kwargs) -> dict:
    """A funded loan plus one QC review of the requested shape."""
    scenario = setup_funded_loan(**scenario_kwargs)
    review = open_qc_review(scenario["loan_id"], defect_type, severity, remediation_status)
    scenario["qc"] = review
    scenario["qc_id"] = review["id"]
    scenario["broker"] = get_broker(scenario["broker_id"])
    return scenario


def setup_funded_loan_with_critical_defect(defect_type: str = "LICENSE_DEFECT",
                                           **scenario_kwargs) -> dict:
    """A funded loan plus a CRITICAL defect that requires repurchase."""
    return setup_funded_loan_with_review(
        defect_type=defect_type, severity="CRITICAL", remediation_status="NONE",
        **scenario_kwargs
    )


# ---------------------------------------------------------------------------
# Tier 4 — accumulation / threshold targeting
# ---------------------------------------------------------------------------

def setup_broker_with_open_defect(loan_id: str, broker_id: str,
                                  defect_type: str = "UNDISCLOSED_LIABILITY",
                                  severity: str = "MAJOR") -> dict:
    """Adds one already-REMEDIATED defect so the broker sits downstream of a finding."""
    review = open_qc_review(loan_id, defect_type, severity, remediation_status="REMEDIATED")
    return review


# ---------------------------------------------------------------------------
# Tier 5 — finalization / terminal state
# ---------------------------------------------------------------------------

def setup_repurchased_loan(defect_type: str = "LICENSE_DEFECT", **scenario_kwargs) -> dict:
    """A loan funded then repurchased through a CRITICAL defect review."""
    scenario = setup_funded_loan_with_critical_defect(defect_type=defect_type, **scenario_kwargs)
    loan_id = scenario["loan_id"]
    _data(
        api_client.repurchase_quality_control_review(
            scenario["qc_id"], make_qc_analyst_headers()
        ),
        "repurchase loan",
    )
    scenario["loan"] = _data(api_client.get_loan_submission(loan_id, ANY), "re-read loan")
    scenario["broker"] = get_broker(scenario["broker_id"])
    return scenario


# ---------------------------------------------------------------------------
# Exclusive-window and multi-broker helpers
# ---------------------------------------------------------------------------

def setup_broker_with_policy(competitor_identifier: str = "COMP-ALPHA",
                             effective_from: str = "2026-09-01T00:00:00Z",
                             effective_to: str = "2026-12-01T00:00:00Z",
                             restriction_scope: str = "LOAN_SUBMISSION",
                             status: str = "ACTIVE",
                             **scenario_kwargs) -> dict:
    scenario = setup_full_scenario(**scenario_kwargs)
    payload = exclusivity_policy_payload(
        scenario["broker_id"],
        competitor_identifier=competitor_identifier,
        effective_from=effective_from,
        effective_to=effective_to,
        restriction_scope=restriction_scope,
        status=status,
    )
    policy = _data(api_client.create_exclusivity_policy(payload, CM), "create exclusivity policy")
    scenario["policy"] = policy
    scenario["policy_id"] = policy["id"]
    return scenario


def setup_second_broker(home_state: str = "NV") -> dict:
    """A second, unrelated brokerage — used for ownership and isolation checks."""
    return create_submitted_broker(
        legal_name="Second Wholesale Brokerage LLC",
        home_state=home_state,
        volume_expectation_cents=50_000_000,
    )


def setup_underwriting_escalation(**scenario_kwargs) -> dict:
    """Loan in UNDERWRITING with one OPEN underwriting-stage escalation."""
    scenario = setup_loan_in_state("UNDERWRITING", **scenario_kwargs)
    set_clock("2026-09-20T00:00:00Z")
    escalations = _data(
        api_client.list_loan_escalations(scenario["loan_id"], ANY), "list escalations"
    )
    scenario["escalations"] = escalations
    scenario["escalation_id"] = escalations[0]["id"]
    scenario["loan"] = _data(api_client.get_loan_submission(scenario["loan_id"], ANY), "re-read loan")
    return scenario


def resolve_escalation(escalation_id: str,
                       resolution_note: str = "underwriting staffing shortage resolved") -> dict:
    return _data(
        api_client.resolve_escalation(escalation_id, {"resolution_note": resolution_note}, CM),
        "resolve escalation",
    )


__all__ = [
    "ANY", "CM", "CO", "PA", "QC", "UW",
    "NON_EXISTENT_UUID",
    "set_clock", "reset_clock", "broker_version", "get_broker",
    "create_submitted_broker", "record_license", "record_financial_review",
    "pass_financial_review", "record_and_pass_financial_review",
    "request_product_eligibility", "approve_product_eligibility",
    "request_and_approve_eligibility", "create_compensation_plan",
    "approve_broker", "create_and_approve_broker", "publish_rate_sheet",
    "price_quote", "submit_loan", "underwrite_loan", "record_decision",
    "setup_full_scenario", "setup_loan_in_state", "setup_suspended_review_loan",
    "setup_funded_loan", "setup_clear_to_close_loan", "setup_conditional_approval_loan",
    "open_qc_review", "resolve_qc_review", "setup_funded_loan_with_review",
    "setup_funded_loan_with_critical_defect", "setup_broker_with_open_defect",
    "setup_repurchased_loan", "setup_broker_with_policy", "setup_second_broker",
    "setup_underwriting_escalation", "resolve_escalation",
    "make_broker_headers", "make_underwriter_headers", "make_qc_analyst_headers",
    "make_channel_manager_headers", "make_compliance_officer_headers",
    "make_platform_admin_headers",
    "NAMED_UNDERWRITER_ID", "NAMED_QC_ANALYST_ID",
    "ltv_band_label",
]