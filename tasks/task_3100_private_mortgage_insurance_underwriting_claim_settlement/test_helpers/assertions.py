"""Entity assertions and domain invariant checkers."""
import pytest
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_instant_equals(actual: str, expected: str, label: str = "instant"):
    """PRD 2.4: "Both instants are ISO 8601 values in UTC written with exactly
    three fractional digits, for example `2025-05-24T10:30:00.123Z`."

    Several PRD sentences carry a derived instant as a bare `00:00:00Z` literal —
    the delinquency report's fifth-calendar-day effective instant, the
    cancellation effective instant, the underwriting stamp — because their source
    is a calendar rule rather than an input. Since PRD 2.4's serialization rule
    governs every instant this API returns, a comparison against such a literal
    compares instants, not spellings: this helper normalizes the fractional part
    before comparing, then leaves the format check to
    `is_iso8601_timestamp`/`assert_timestamp_format`.
    """
    assert is_iso8601_timestamp(actual), f"{label} must be ISO 8601: {actual!r}"
    normalized_actual = _strip_fractional(actual)
    normalized_expected = _strip_fractional(expected)
    assert normalized_actual == normalized_expected, (
        f"{label} is {actual!r}, expected the instant {expected!r}"
    )


def _strip_fractional(value: str) -> str:
    if isinstance(value, str) and "." in value and value.endswith("Z"):
        head, _, frac = value[:-1].rpartition(".")
        if frac.isdigit():
            return head + "Z"
    return value


def _assert_audit_fields(data: dict, entity_name: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity_name}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity_name}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity_name}.version must be a positive integer"


def assert_master_policy(data: dict):
    _assert_audit_fields(data, "MasterPolicy")
    assert data["coverage_percent_default"] in [12, 25, 30]
    assert data["status"] == "ACTIVE"
    assert isinstance(data["two_year_effective_flag"], bool)


def assert_rate_card(data: dict):
    _assert_audit_fields(data, "RateCard")
    assert data["credit_grade"] in ["A", "B", "C", "D"]
    assert data["ltv_band"] in ["831_TO_85", "851_TO_90", "901_TO_95"]
    assert data["premium_plan"] in ["BPM", "SPM", "LPM"]
    assert isinstance(data["rate_bps"], int) and data["rate_bps"] >= 0


def assert_treaty(data: dict):
    _assert_audit_fields(data, "ReinsuranceTreaty")
    assert data["status"] in ["ACTIVE", "EXPIRED", "CANCELLED"]
    assert data["exhaustion_per_claim_cents"] >= data["retention_per_claim_cents"]


def assert_servicer(data: dict):
    _assert_audit_fields(data, "Servicer")
    assert data["tier"] in ["TIER_1", "TIER_2", "TIER_3"]
    assert data["loss_mitigation_capability"] in ["PARTICIPATION", "PARTICIPATION_COMPLETE"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_lender(data: dict):
    _assert_audit_fields(data, "Lender")
    assert isinstance(data["delegated_underwriting"], bool)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_coverage_application(data: dict):
    _assert_audit_fields(data, "CoverageApplication")
    assert data["status"] in ["SUBMITTED", "IN_UNDERWRITING", "INFO_REQUESTED",
                              "APPROVED", "DECLINED", "WITHDRAWN"]
    assert data["underwriting_path"] in ["DELEGATED", "NON_DELEGATED"]


def assert_loan(data: dict):
    _assert_audit_fields(data, "Loan")
    assert data["coverage_status"] in ["ACTIVE", "PENDING_CANCELLATION", "CANCELLED"]
    assert data["amortization_status"] in ["IN_AMORTIZATION", "AT_78", "AT_80"]
    assert data["termination_reason"] in ["NONE", "BORROWER_REQUEST", "LTV_MILESTONE",
                                          "SERVICER_LOSS_MITIGATION_FAILURE"]
    assert data["rescission_relief_status"] in ["NONE", "PROVISIONAL", "GUARANTEED"]
    assert isinstance(data["claim_blocked"], bool)


def assert_delinquency_report(data: dict):
    _assert_audit_fields(data, "DelinquencyReport")
    assert data["delinquency_class"] in ["A", "B"]
    assert is_iso8601_timestamp(data["effective_utc"])
    assert isinstance(data["participation_standard_met"], bool)


def assert_cancellation_notice(data: dict):
    _assert_audit_fields(data, "CancellationNotice")
    assert data["request_kind"] in ["BORROWER_REQUEST", "SERVICER_LOSS_MITIGATION_FAILURE"]
    assert data["requested_by_role"] in ["BORROWER", "SERVICER"]
    assert data["status"] in ["SUBMITTED", "APPLIED", "REJECTED"]
    assert isinstance(data["refund_cents"], int) and data["refund_cents"] >= 0


def assert_external_report(data: dict):
    _assert_audit_fields(data, "ExternalReport")
    assert data["occupancy_reported"] in ["OWNER_OCCUPIED", "SECOND_HOME", "INVESTMENT"]
    assert isinstance(data["validated_ltv"], float)
    assert isinstance(data["occupancy_materially_differs"], bool)


def assert_dispute(data: dict):
    _assert_audit_fields(data, "CurtailmentDispute")
    assert data["grounds"] in ["ORIGINATION_OMISSION", "OCCUPANCY_MISREPRESENTATION",
                               "VALUATION_ERROR", "LOSS_MITIGATION_EXCUSE"]
    assert data["status"] in ["OPEN", "UNDER_REVIEW", "RESOLVED"]


def assert_claim(data: dict):
    _assert_audit_fields(data, "Claim")
    assert data["event_kind"] in ["FORECLOSURE", "SHORT_SALE", "DEED_IN_LIEU"]
    assert data["status"] in ["FILED", "UNDER_REVIEW", "APPROVED", "DENIED",
                              "SETTLED", "RESCINDED"]
    assert isinstance(data["trace_number"], str) and len(data["trace_number"]) > 0


def assert_settlement_option(data: dict):
    _assert_audit_fields(data, "ClaimSettlementOption")
    assert data["option_kind"] in ["CASH", "THIRD_PARTY_SALE", "DEED_IN_LIEU", "DIL"]
    assert isinstance(data["computed_amount_cents"], int)


def assert_snapshot(data: dict):
    _assert_audit_fields(data, "PortfolioSnapshot")
    assert data["status"] in ["COMPUTED", "SUPERSEDED"]
    assert isinstance(data["segment_statuses"], list)
    assert isinstance(data["aggregate_ceded_cents"], int)


def assert_cession(data: dict):
    _assert_audit_fields(data, "ReinsuranceCession")
    assert data["status"] in ["ACCEPTED", "REJECTED"]
    if data["status"] == "REJECTED":
        assert data["rejected_reason"] in ["NO_TREATY", "TREATY_NOT_IN_FORCE_AT_EVENT",
                                           "AGGREGATE_CAP_EXHAUSTED"]
    assert isinstance(data["ceded_amount_cents"], int)


# --- Domain invariant checkers ------------------------------------------------

def assert_claim_arithmetic(data: dict):
    """The claim arithmetic chain, re-derived from the frozen inputs."""
    if data.get("permitted_interest_cents") is None:
        return
    assert data["permitted_interest_cents"] == \
        min(data["accrued_interest_cents"],
            int(data["unpaid_principal_cents"] * 0.15))
    assert data["permitted_advances_cents"] == \
        min(data["allowable_advances_cents"],
            int(data["unpaid_principal_cents"] * 1.10))
    assert data["net_unpaid_balance_cents"] == (
        data["unpaid_principal_cents"]
        + data["permitted_interest_cents"]
        + data["permitted_advances_cents"])
    assert data["recoverable_amount_cents"] == max(
        0,
        data["net_unpaid_balance_cents"]
        - max(0, data["gross_proceeds_cents"] - data["expenses_of_sale_cents"]))
    assert data["covered_claim_amount_cents"] == \
        min(data["recoverable_amount_cents"], data["coverage_ceiling_cents"])


def assert_premium_schedule(loan: dict):
    """The premium schedule ledger invariant: the twelve periods sum to the
    annual premium."""
    total = 11 * loan["monthly_period_cents"] + loan["final_period_cents"]
    assert total == loan["annual_premium_cents"], (
        f"premium schedule total {total} != annual premium "
        f"{loan['annual_premium_cents']}")


def assert_loan_exposure_contribution(contribution_cents: int,
                                      coverage_base_upb_cents: int,
                                      exposure_contribution_rate: float,
                                      aggregate_ceded_cents: int = 0):
    expected = aggregate_ceded_cents + round(
        coverage_base_upb_cents * exposure_contribution_rate)
    assert contribution_cents == expected, (
        f"expected contribution {expected}, got {contribution_cents}")