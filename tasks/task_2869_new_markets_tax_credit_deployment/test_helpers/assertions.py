"""Entity assertions and domain invariant checkers.

Timestamps are compared through `assert_instant` rather than by string
equality: the PRD fixes the wire format at "ISO 8601 in UTC with exactly three
fractional digits", but a comparison against a literal written in a shorter
form should still succeed, so both sides are normalised first.
"""
from datetime import datetime, timezone
from typing import Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    QUALIFYING_QLICI_STATUSES,
)
from .types import (
    AwardLifecycleStatus,
    CbaStatus,
    CdeCertificationStatus,
    CertificationClassification,
    CompliancePosture,
    DistressTier,
    InvestmentFundStatus,
    MeasurementBasis,
    QalicbEligibilityStatus,
    QeiComplianceStatus,
    QeiDeploymentStatus,
    QliciStatus,
    RecaptureTriggerType,
    ReinvestmentObligationStatus,
    ServiceAreaScope,
    SubstantiallyAllMethod,
    UnwindStatus,
)

PCT_TOLERANCE = 0.005


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating a trailing `Z`."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def canonical_instant(value: str) -> str:
    """Render an instant in the PRD's wire format: UTC, three fractional digits."""
    moment = parse_instant(value)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def assert_instant(actual: Optional[str], expected: str, label: str = "instant") -> None:
    """Assert two ISO 8601 instants denote the same moment."""
    assert actual is not None, f"{label} must be present, got None"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Expected {label} {canonical_instant(expected)}, got {canonical_instant(actual)}"
    )


def assert_instant_format(value: str, label: str = "timestamp") -> None:
    """Assert an instant is ISO 8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {type(value)}"
    assert is_iso8601_timestamp(value), f"{label} must be ISO 8601, got {value!r}"
    assert value.endswith("Z"), f"{label} must be expressed in UTC with a Z suffix: {value!r}"
    assert "." in value, f"{label} must carry fractional digits: {value!r}"
    fraction = value.split(".")[-1].rstrip("Z")
    assert len(fraction) == 3, (
        f"{label} must carry exactly three fractional digits, got {value!r}"
    )


def assert_pct(actual, expected: float, label: str = "percentage") -> None:
    """Assert a percentage matches to two decimal places."""
    assert isinstance(actual, (int, float)), f"{label} must be numeric, got {actual!r}"
    assert abs(float(actual) - expected) < PCT_TOLERANCE, (
        f"Expected {label} {expected:.2f}, got {actual}"
    )


def assert_cents(actual, expected: int, label: str = "amount") -> None:
    """Assert a money field is an integer number of cents with the exact value."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"Expected {label} {expected}, got {actual}"


def assert_two_decimal_places(value) -> None:
    """Assert a percentage is rounded to at most two decimal places."""
    assert isinstance(value, (int, float)), f"expected a number, got {value!r}"
    assert abs(round(float(value), 2) - float(value)) < 1e-9, (
        f"Expected a value rounded to two decimal places, got {value}"
    )


# ---------------------------------------------------------------------------
# Common-field shape
# ---------------------------------------------------------------------------


def assert_common_fields(data: dict, label: str = "resource") -> None:
    """Assert the four common properties of a primary resource."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID with no type prefix, got {data.get('id')!r}"
    )
    assert_instant_format(data.get("created_at", ""), f"{label}.created_at")
    assert_instant_format(data.get("updated_at", ""), f"{label}.updated_at")
    assert isinstance(data.get("version"), int) and not isinstance(
        data.get("version"), bool
    ), f"{label}.version must be an integer, got {data.get('version')!r}"
    assert data["version"] >= 1, f"{label}.version must start at 1, got {data['version']}"


def assert_append_only_fields(data: dict, label: str = "observation") -> None:
    """Assert an append-only observation carries only `id` and `created_at`."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert_instant_format(data.get("created_at", ""), f"{label}.created_at")
    assert "updated_at" not in data, (
        f"{label} is append-only: updated_at must be absent entirely"
    )
    assert "version" not in data, (
        f"{label} is append-only: version must be absent entirely"
    )


def assert_version_is(data: dict, expected: int, label: str = "resource") -> None:
    assert data.get("version") == expected, (
        f"Expected {label}.version {expected}, got {data.get('version')}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_cde(data: dict) -> None:
    assert_common_fields(data, "cde")
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 120
    assert isinstance(data["certification_number"], str)
    assert 1 <= len(data["certification_number"]) <= 40
    assert data["service_area_scope"] in [s.value for s in ServiceAreaScope]
    assert data["certification_status"] in [s.value for s in CdeCertificationStatus]
    assert isinstance(data["award_count"], int) and data["award_count"] >= 0
    if data["certification_status"] == CdeCertificationStatus.CERTIFIED.value:
        assert data["decertified_at"] is None, "a certified entity has no decertified_at"
        assert data["decertification_reason"] is None


def assert_allocation_award(data: dict) -> None:
    assert_common_fields(data, "allocation_award")
    assert is_valid_uuid(data["cde_id"])
    assert isinstance(data["award_year"], int)
    assert isinstance(data["allocation_amount_cents"], int)
    assert isinstance(data["service_area_state_codes"], list)
    assert 1 <= len(data["service_area_state_codes"]) <= 10
    for code in data["service_area_state_codes"]:
        assert isinstance(code, str) and len(code) == 2 and code.isupper()
    assert data["substantially_all_method"] in [m.value for m in SubstantiallyAllMethod]
    assert data["lifecycle_status"] in [s.value for s in AwardLifecycleStatus]
    assert data["compliance_posture"] in [p.value for p in CompliancePosture]
    for counter in (
        "issued_qei_count",
        "at_risk_qei_count",
        "recaptured_qei_count",
        "cba_breach_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"allocation_award.{counter} must be a non-negative integer"
        )
    assert isinstance(data["remaining_authority_cents"], int)
    assert data["remaining_authority_cents"] >= 0, (
        "remaining allocation authority can never go negative"
    )
    assert_two_decimal_places(data["severe_distress_share_pct"])


def assert_census_tract(data: dict) -> None:
    assert_append_only_fields(data, "census_tract")
    assert isinstance(data["tract_code"], str) and len(data["tract_code"]) == 11
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["is_low_income_community"], bool)
    assert isinstance(data["qualifies_by_contiguity"], bool)
    assert isinstance(data["eligible_for_qlici"], bool)
    assert data["severe_criteria_met_count"] in (0, 1, 2, 3)
    assert 0.0 <= float(data["distress_score"]) <= 100.0, (
        "distress_score is capped at 100.00"
    )
    assert_two_decimal_places(data["distress_score"])
    assert data["distress_tier"] in [t.value for t in DistressTier]


def assert_qalicb(data: dict) -> None:
    assert_common_fields(data, "qalicb")
    assert is_valid_uuid(data["census_tract_id"])
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["naics_code"], str)
    assert isinstance(data["sponsor_user_id"], str) and data["sponsor_user_id"]
    assert data["eligibility_status"] in [s.value for s in QalicbEligibilityStatus]
    assert isinstance(data["consecutive_failed_test_count"], int)
    assert isinstance(data["funding_qlici_count"], int)


def assert_eligibility_test(data: dict) -> None:
    assert_append_only_fields(data, "eligibility_test")
    assert data["result"] in ("PASS", "FAIL")
    assert isinstance(data["failed_prongs"], list)
    assert isinstance(data["location_prong_passed"], bool)
    assert isinstance(data["performed_by_user_id"], str) and data["performed_by_user_id"]
    assert_instant_format(data["performed_at"], "eligibility_test.performed_at")
    if data["result"] == "PASS":
        assert data["failed_prongs"] == [], "a passing test lists no failed prongs"


def assert_investment_fund(data: dict) -> None:
    assert_common_fields(data, "investment_fund")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["equity_contribution_cents"], int)
    assert isinstance(data["leverage_loan_principal_cents"], int)
    assert isinstance(data["leverage_loan_rate_bps"], int)
    assert isinstance(data["investor_user_id"], str) and data["investor_user_id"]
    assert data["status"] in [s.value for s in InvestmentFundStatus]
    for field in (
        "equity_received_cents",
        "leverage_received_cents",
        "leverage_loan_outstanding_cents",
        "capital_available_cents",
        "deployed_to_qei_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"investment_fund.{field} must be a non-negative integer of cents"
        )


def assert_qei(data: dict) -> None:
    assert_common_fields(data, "qei")
    assert is_valid_uuid(data["allocation_award_id"])
    assert is_valid_uuid(data["investment_fund_id"])
    assert isinstance(data["qei_amount_cents"], int)
    assert isinstance(data["reserve_bps"], int)
    assert isinstance(data["permitted_fees_cents"], int)
    assert isinstance(data["net_deployable_cents"], int)
    assert isinstance(data["uninvested_cash_cents"], int)
    assert data["uninvested_cash_cents"] >= 0, "uninvested cash can never go negative"
    assert_instant_format(data["issued_at"], "qei.issued_at")
    assert_instant_format(data["deployment_deadline_at"], "qei.deployment_deadline_at")
    assert data["deployment_status"] in [s.value for s in QeiDeploymentStatus]
    assert data["compliance_status"] in [s.value for s in QeiComplianceStatus]
    assert 0 <= data["compliance_years_completed"] <= 7
    assert_two_decimal_places(data["substantially_all_pct_direct"])
    assert_two_decimal_places(data["substantially_all_pct_aggregate"])
    assert data["recapture_trigger_type"] in [t.value for t in RecaptureTriggerType]
    assert isinstance(data["recapture_exposure_cents"], int)
    assert isinstance(data["accrued_unpaid_fee_cents"], int)
    assert data["net_deployable_cents"] == (
        data["qei_amount_cents"] - data["permitted_fees_cents"]
    ), "net_deployable_cents is the gross amount less the permitted fees"


def assert_qlici(data: dict) -> None:
    assert_common_fields(data, "qlici")
    assert is_valid_uuid(data["qei_id"])
    assert is_valid_uuid(data["qalicb_id"])
    assert data["loan_class"] in ("A", "B")
    assert isinstance(data["principal_cents"], int)
    assert_instant_format(data["deployed_at"], "qlici.deployed_at")
    assert data["status"] in [s.value for s in QliciStatus]
    assert isinstance(data["outstanding_principal_cents"], int)
    assert isinstance(data["total_repaid_cents"], int)
    assert isinstance(data["allocated_fee_cents"], int)
    assert isinstance(data["created_by_cure"], bool)
    assert (
        data["outstanding_principal_cents"] + data["total_repaid_cents"]
        == data["principal_cents"]
    ), "outstanding principal plus total repaid always equals the original principal"


def assert_reinvestment_obligation(data: dict) -> None:
    assert_common_fields(data, "reinvestment_obligation")
    assert is_valid_uuid(data["qei_id"])
    assert is_valid_uuid(data["source_qlici_id"])
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["reinvested_cents"], int)
    assert_instant_format(data["arose_at"], "reinvestment_obligation.arose_at")
    assert_instant_format(data["reinvest_by_at"], "reinvestment_obligation.reinvest_by_at")
    assert data["status"] in [s.value for s in ReinvestmentObligationStatus]
    assert data["reinvested_cents"] <= data["amount_cents"], (
        "reinvested capital can never exceed the obligation"
    )


def assert_annual_compliance_test(data: dict) -> None:
    assert_append_only_fields(data, "annual_compliance_test")
    assert 1 <= data["compliance_year"] <= 7
    assert_instant_format(data["window_start_at"], "annual_test.window_start_at")
    assert_instant_format(data["window_end_at"], "annual_test.window_end_at")
    assert data["window_days"] == 365, "the measurement window is always 365 days long"
    assert_two_decimal_places(data["measured_pct_direct"])
    assert_two_decimal_places(data["measured_pct_aggregate"])
    assert data["governing_method"] in [m.value for m in SubstantiallyAllMethod]
    assert data["result"] in ("PASS", "FAIL")
    assert isinstance(data["recapture_triggered"], bool)
    assert isinstance(data["breached_obligation_count"], int)
    assert isinstance(data["recertification_swept_qalicb_count"], int)
    assert isinstance(data["performed_by_user_id"], str) and data["performed_by_user_id"]


def assert_community_benefits_agreement(data: dict) -> None:
    assert_common_fields(data, "community_benefits_agreement")
    assert is_valid_uuid(data["qalicb_id"])
    assert is_valid_uuid(data["allocation_award_id"])
    assert isinstance(data["target_fte_count"], int) and data["target_fte_count"] >= 1
    assert isinstance(data["wage_floor_cents_per_hour"], int)
    assert data["measurement_basis"] in [m.value for m in MeasurementBasis]
    assert_instant_format(
        data["agreement_start_at"], "community_benefits_agreement.agreement_start_at"
    )
    assert data["status"] in [s.value for s in CbaStatus]
    assert isinstance(data["consecutive_cure_required_count"], int)
    assert_two_decimal_places(data["latest_compliance_pct"])
    assert_two_decimal_places(data["latest_local_hire_pct"])


def assert_job_report(data: dict) -> None:
    assert_append_only_fields(data, "job_report")
    assert_instant_format(data["period_start_at"], "job_report.period_start_at")
    assert_instant_format(data["period_end_at"], "job_report.period_end_at")
    assert isinstance(data["headcount"], int)
    assert isinstance(data["qualifying_headcount"], int)
    assert data["qualifying_headcount"] <= data["headcount"]
    assert isinstance(data["local_hires"], int)
    assert isinstance(data["avg_hourly_wage_cents"], int)
    assert isinstance(data["wage_floor_met"], bool)
    assert isinstance(data["filed_by_user_id"], str) and data["filed_by_user_id"]
    assert_instant_format(data["filed_at"], "job_report.filed_at")


def assert_unwind_transaction(data: dict) -> None:
    assert_common_fields(data, "unwind_transaction")
    assert is_valid_uuid(data["qei_id"])
    assert isinstance(data["put_holder_user_id"], str) and data["put_holder_user_id"]
    assert isinstance(data["call_holder_user_id"], str) and data["call_holder_user_id"]
    assert isinstance(data["fund_residual_value_cents"], int)
    assert isinstance(data["put_price_cents"], int)
    assert isinstance(data["call_price_cents"], int)
    assert data["put_price_cents"] >= 100_000
    assert data["call_price_cents"] >= 100_000, (
        "the call price is floored at 100000 cents"
    )
    assert_instant_format(
        data["option_window_open_at"], "unwind_transaction.option_window_open_at"
    )
    assert_instant_format(
        data["option_window_close_at"], "unwind_transaction.option_window_close_at"
    )
    assert data["status"] in [s.value for s in UnwindStatus]
    assert isinstance(data["settlement_amount_cents"], int)


def assert_agency_report(data: dict) -> None:
    assert is_valid_uuid(data["allocation_award_id"])
    assert isinstance(data["report_year"], int)
    for counter in (
        "issued_qei_count",
        "qualifying_qalicb_count",
        "at_risk_qei_count",
        "recaptured_qei_count",
        "cba_breach_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert isinstance(data["deployed_principal_cents"], int)
    assert_two_decimal_places(data["severe_distress_share_pct"])
    assert isinstance(data["severe_distress_shortfall"], bool)


def assert_annual_certification(data: dict) -> None:
    assert is_valid_uuid(data["community_benefits_agreement_id"])
    assert isinstance(data["certification_year"], int)
    assert data["measurement_basis"] in [m.value for m in MeasurementBasis]
    assert_two_decimal_places(data["compliance_pct"])
    assert_two_decimal_places(data["local_hire_pct"])
    assert isinstance(data["report_count"], int)
    assert isinstance(data["excluded_wage_failing_report_count"], int)
    assert data["classification"] in [c.value for c in CertificationClassification]
    assert data["resulting_status"] in [s.value for s in CbaStatus]


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def assert_allocation_authority_conserved(award: dict, qeis: Iterable[dict]) -> None:
    """The award's allocation amount is split between drawn and remaining authority.

    Voided investments release their draw entirely, so they are excluded.
    """
    drawn = sum(
        q["qei_amount_cents"]
        for q in qeis
        if q["deployment_status"] != QeiDeploymentStatus.VOIDED.value
    )
    assert (
        drawn + award["remaining_authority_cents"] == award["allocation_amount_cents"]
    ), (
        "gross issued amounts plus remaining authority must equal the allocation "
        f"amount: {drawn} + {award['remaining_authority_cents']} != "
        f"{award['allocation_amount_cents']}"
    )


def assert_investment_capital_conserved(qei: dict, qlicis: Iterable[dict]) -> None:
    """Uninvested cash plus outstanding principal equals the net deployable amount."""
    outstanding = sum(q["outstanding_principal_cents"] for q in qlicis)
    assert qei["uninvested_cash_cents"] + outstanding == qei["net_deployable_cents"], (
        "uninvested cash plus outstanding sub-allocation principal must equal the "
        f"net deployable amount: {qei['uninvested_cash_cents']} + {outstanding} != "
        f"{qei['net_deployable_cents']}"
    )


def compute_direct_pct(qei: dict, qlicis: Iterable[dict]) -> float:
    """Reproduce the direct-tracing substantially-all measurement."""
    numerator = sum(
        q["outstanding_principal_cents"]
        for q in qlicis
        if q["status"] in QUALIFYING_QLICI_STATUSES
    )
    denominator = qei["qei_amount_cents"] - qei["permitted_fees_cents"]
    if denominator == 0:
        return 0.0
    return round(100.0 * numerator / denominator + 1e-9, 2)


def assert_no_negative_money(data: dict, fields: List[str]) -> None:
    for field in fields:
        assert data[field] >= 0, f"{field} must never go negative, got {data[field]}"
