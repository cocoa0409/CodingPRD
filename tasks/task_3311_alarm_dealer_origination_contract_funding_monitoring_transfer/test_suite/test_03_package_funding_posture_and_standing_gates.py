"""Package approval, whole-package funding posture and dealer standing gates."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    set_logical_clock,
    setup_package_with_contract,
    submit_and_approve_package,
    fund_package,
    declare_package_contract,
    package_version,
    register_customer,
    provision_monitoring_account,
    make_dealer_headers,
    validate_success,
    validate_error,
    create_dealer_payload,
    ApiErrorId,
    TEST_USERS,
)

_CHANNEL = TEST_USERS["channel_manager_headers"]
_ANALYST = TEST_USERS["funding_analyst_headers"]
_DEALER = TEST_USERS["dealer_headers"]


# ─── Corner: rbac / dealer_role_cannot_approve_package_returns_403 ───

def test_dealer_role_cannot_approve_package(api):
    """PRD §2.1: "A request that names a declared role the endpoint does not admit is rejected with `ERR_UNAUTHORIZED` and HTTP 403."

    Design: Corner/rbac/dealer_role_cannot_approve_package_returns_403
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    dealer, package, contract = setup_package_with_contract(
        dealer_code="D10", legal_name="Delta Alarms Inc", holdback_rate=0.10,
        quality_tier="TIER_1", package_reference="PKG-P10",
        equipment_config_code="PREMIUM", contract_term_months=60)
    get_success_data(api_client.submit_package(
        package["id"], make_dealer_headers(dealer["id"])))

    res = api_client.approve_package(
        package["id"],
        {"expected_dealer_package_version": package_version(package["id"])},
        make_dealer_headers(dealer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


# ─── Difficulty: priority_pair_validation_conflict / state_precedes_business_fiscal_on_package_fund ───

def _draft_package_with_credit_failing_child():
    """A DRAFT package holding one child whose credit score is below the floor."""
    set_logical_clock("2026-09-01T00:00:00Z")
    dealer, package, contract = setup_package_with_contract(
        dealer_code="D1", legal_name="Northstar Security LLC", holdback_rate=0.10,
        quality_tier="TIER_1", package_reference="PKG-P8",
        equipment_config_code="PREMIUM", credit_score=600,
        contract_term_months=60, provision=False)
    assert package["package_status"] == "DRAFT"
    return dealer, package, contract


def test_package_fund_from_draft_reports_package_not_approved(api):
    """PRD §2.10: "Three state errors are specialised because they carry their own identifiers: funding a package from a state other than `APPROVED` reports `ERR_PACKAGE_NOT_APPROVED`"

    Design: Difficulty/priority_pair_validation_conflict/state_precedes_business_fiscal_on_package_fund
    """
    dealer, package, contract = _draft_package_with_credit_failing_child()

    res = api_client.fund_package(
        package["id"],
        {"expected_dealer_package_version": package_version(package["id"])},
        _ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_PACKAGE_NOT_APPROVED, expected_status=409)


def test_package_fund_reports_state_error_not_the_credit_floor_error(api):
    """PRD §2.10: "Requests are validated in a fixed order, and the first check that fails determines the single `error_id` returned."
    PRD §2.10: "State checks follow, failing with `ERR_INVALID_STATE` when the target is not in a state from which the requested transition is declared."
    PRD §2.10: "the fiscal quality gates come eighth (`ERR_CREDIT_SCORE_BELOW_FLOOR`, `ERR_TERM_BELOW_FLOOR`, `ERR_EQUIPMENT_CONFIG_NOT_PERMITTED`, `ERR_MONITORING_NOT_PROVISIONED`, `ERR_DEALER_STANDING_SUSPENDED`, `ERR_DEALER_CHARGEBACK_RATE_EXCEEDED`, `ERR_HOLDBACK_RATE_EXCEEDS_CEILING`, `ERR_CHARGEBACK_WINDOW_CLOSED`, `ERR_DISCLOSURE_AMOUNT_MISMATCH`)."

    Design: Difficulty/priority_pair_validation_conflict/state_precedes_business_fiscal_on_package_fund
    """
    dealer, package, contract = _draft_package_with_credit_failing_child()

    res = api_client.fund_package(
        package["id"],
        {"expected_dealer_package_version": package_version(package["id"])},
        _ANALYST,
    )
    body = res.json()
    assert body["data"]["error_id"] == "ERR_PACKAGE_NOT_APPROVED"
    assert body["data"]["error_id"] != "ERR_CREDIT_SCORE_BELOW_FLOOR"
    assert res.status_code == 409


# ─── Difficulty: transitive_cascade / credit_gate_failure_contagion_freezes_sibling_children ───

def _package_with_bad_and_good_children():
    """Package P7 with a credit-failing child and a fully eligible sibling."""
    set_logical_clock("2026-09-01T00:00:00Z")
    dealer = validate_success(api_client.create_dealer(
        create_dealer_payload(dealer_code="D1", legal_name="Northstar Security LLC",
                              holdback_rate=0.10, quality_tier="TIER_1"),
        _CHANNEL), 201)
    package = validate_success(api_client.create_package(
        {"package_reference": "PKG-P7", "dealer_id": dealer["id"]}, _ANALYST), 201)

    bad_customer = register_customer(full_name="Paige BadCredit",
                                     email="paige.badcredit@example.com")
    good_customer = register_customer(full_name="Quinn GoodCredit",
                                      email="quinn.goodcredit@example.com")

    bad = declare_package_contract(
        package["id"], bad_customer["id"], equipment_config_code="PREMIUM",
        credit_score=600, contract_term_months=60, monthly_monitoring_cents=4999,
        installation_scheduled_at="2026-09-02T00:00:00Z",
        installation_engineer_id="ENG-1")
    good = declare_package_contract(
        package["id"], good_customer["id"], equipment_config_code="PREMIUM",
        credit_score=700, contract_term_months=60, monthly_monitoring_cents=4999,
        installation_scheduled_at="2026-09-02T00:00:00Z",
        installation_engineer_id="ENG-2")
    provision_monitoring_account(good["id"])

    package = submit_and_approve_package(dealer, package["id"])
    return dealer, package, bad, good


def test_credit_floor_failure_freezes_the_offending_child_and_refuses_funding(api):
    """PRD §3.3: "In the whole-declined case — a declined child froze on `ERR_CREDIT_SCORE_BELOW_FLOOR` — the posture is `DECLINED`, and a funding attempt then freezes every remaining `PENDING_VALIDATION` child: the credit offender carries `ERR_CREDIT_SCORE_BELOW_FLOOR`, and each other child is frozen with `ERR_PACKAGE_DECLINED` because the whole-package posture declined it. A fund attempt in a `DECLINED` posture is refused outright with `ERR_NO_FUNDABLE_CONTRACT`."

    Design: Difficulty/transitive_cascade/credit_gate_failure_contagion_freezes_sibling_children
    """
    dealer, package, bad, good = _package_with_bad_and_good_children()

    res = api_client.fund_package(
        package["id"],
        {"expected_dealer_package_version": package_version(package["id"])},
        _ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_NO_FUNDABLE_CONTRACT, expected_status=422)

    frozen_bad = validate_success(api_client.get_contract(bad["id"], _ANALYST), 200)
    assert frozen_bad["validation_failure_code"] == "ERR_CREDIT_SCORE_BELOW_FLOOR"


def test_credit_floor_failure_freezes_the_sibling_child_that_passed_every_gate(api):
    """PRD §3.3: "each other child is frozen with `ERR_PACKAGE_DECLINED` because the whole-package posture declined it"
    PRD §3.4: "When a child is frozen by a package fund or decline, the parent package's `declined_count` advances by one and the package's `version` advances as well."

    Design: Difficulty/transitive_cascade/credit_gate_failure_contagion_freezes_sibling_children
    """
    dealer, package, bad, good = _package_with_bad_and_good_children()

    api_client.fund_package(
        package["id"],
        {"expected_dealer_package_version": package_version(package["id"])},
        _ANALYST,
    )

    frozen_good = validate_success(api_client.get_contract(good["id"], _ANALYST), 200)
    assert frozen_good["contract_status"] == "CANCELLED"
    assert frozen_good["validation_failure_code"] == "ERR_PACKAGE_DECLINED"

    refreshed = validate_success(api_client.get_package(package["id"], _ANALYST), 200)
    assert refreshed["declined_count"] == 2


# ─── Difficulty: cross_entity_state_dependency / package_funding_requires_dealer_standing_not_suspended ───

def _suspended_dealer_with_submitted_package():
    """A SUSPENDED dealer holding a package under review."""
    set_logical_clock("2026-09-01T00:00:00Z")
    dealer, package, contract = setup_package_with_contract(
        dealer_code="D1", legal_name="Northstar Security LLC", holdback_rate=0.10,
        quality_tier="TIER_3", package_reference="PKG-P12",
        equipment_config_code="PREMIUM", contract_term_months=60)
    get_success_data(api_client.submit_package(
        package["id"], make_dealer_headers(dealer["id"])))
    suspended = validate_success(api_client.suspend_dealer(dealer["id"], _ANALYST), 200)
    assert suspended["standing"] == "SUSPENDED"
    return suspended, package, contract


def test_package_approval_refused_when_dealer_standing_is_suspended(api):
    """PRD §3.3: "Two business preconditions must also hold: the package reference must be unique within the dealer — the same natural key rule that guards creation — and the dealer's standing must not be `SUSPENDED`, refused with `ERR_DEALER_STANDING_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/package_funding_requires_dealer_standing_not_suspended
    """
    dealer, package, contract = _suspended_dealer_with_submitted_package()

    res = api_client.approve_package(
        package["id"],
        {"expected_dealer_package_version": package_version(package["id"])},
        _ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_DEALER_STANDING_SUSPENDED, expected_status=422)


def test_suspended_dealer_approval_leaves_dealer_suspended_and_package_under_review(api):
    """PRD §2.9: "A `SUSPENDED` dealer may not have a package approved — the approval is refused with `ERR_DEALER_STANDING_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/package_funding_requires_dealer_standing_not_suspended
    """
    dealer, package, contract = _suspended_dealer_with_submitted_package()

    api_client.approve_package(
        package["id"],
        {"expected_dealer_package_version": package_version(package["id"])},
        _ANALYST,
    )
    still = validate_success(api_client.get_dealer(dealer["id"], _ANALYST), 200)
    assert still["standing"] == "SUSPENDED"
    pkg = validate_success(api_client.get_package(package["id"], _ANALYST), 200)
    assert pkg["package_status"] == "UNDER_REVIEW"