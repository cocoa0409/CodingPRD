"""Entity assertions and domain invariant checkers.

Every helper here asserts only what the PRD states about the record: the UUID
identity, the ISO 8601 timestamps, the declared enum domains and the arithmetic
invariants that must hold after any operation.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AccuracyStatus,
    ActivationStage,
    AgreementStatus,
    BreachState,
    BrokerType,
    CallReportLine,
    CapitalCategory,
    ComplianceStatus,
    ConcentrationMetric,
    ConcentrationPosture,
    DepositBrokerProng,
    DeterminedClass,
    DiligenceStatus,
    ExceptionBasis,
    ExceptionStatus,
    FeeStructure,
    FilingStatus,
    FilingType,
    FundingChannelClaim,
    FundingStatus,
    LimitStatus,
    PlanStatus,
    ProductType,
    ProgramState,
    RateCapOutcome,
    RateCapRegime,
    TenorBucket,
    TestOutcome,
    TitlingConvention,
)

_MEMBERS = lambda enum_cls: [m.value for m in enum_cls]  # noqa: E731


# ─── Common record shape ──────────────────────────────

def assert_common_fields(data: dict, entity: str = "record") -> None:
    """id + created_at + updated_at + version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict, entity: str = "record") -> None:
    """An append-only ledger row carries only id and created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, (
        f"{entity} is append-only and must not carry updated_at"
    )
    assert "version" not in data, f"{entity} is append-only and must not carry version"


def assert_calendar_date(value, field: str) -> None:
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{field} must be a year-month-day calendar date, got {value!r}"
    )


def assert_non_negative_cents(data: dict, *fields: str) -> None:
    for field in fields:
        value = data.get(field)
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be an integer number of cents, got {value!r}"
        )
        assert value >= 0, f"{field} must not be negative, got {value}"


def assert_bps_in_range(data: dict, *fields: str) -> None:
    for field in fields:
        value = data.get(field)
        if value is None:
            continue
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be an integer number of basis points, got {value!r}"
        )
        assert 0 <= value <= 10000, f"{field} must lie in 0..10000 bps, got {value}"


# ─── Per-entity assertions ────────────────────────────

def assert_institution(data: dict) -> None:
    assert_common_fields(data, "Institution")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["cert_id"], str) and data["cert_id"]
    assert data["capital_category"] in _MEMBERS(CapitalCategory)
    assert data["rate_cap_regime"] in _MEMBERS(RateCapRegime)
    assert data["concentration_posture"] in _MEMBERS(ConcentrationPosture)
    assert_non_negative_cents(
        data,
        "core_deposits_cents",
        "brokered_deposits_cents",
        "listing_service_deposits_cents",
        "reciprocal_deposits_cents",
        "total_deposits_cents",
        "total_liabilities_cents",
        "tier1_capital_cents",
        "liquidity_buffer_cents",
    )
    assert isinstance(data["wholesale_funding_ratio_bps"], int)
    assert isinstance(data["single_broker_max_ratio_bps"], int)
    assert isinstance(data["breached_metric_count"], int)
    assert data["breached_metric_count"] >= 0
    assert_institution_invariants(data)


def assert_institution_invariants(data: dict) -> None:
    """total_deposits_cents is core plus the three wholesale buckets (PRD §2.11).

    rate_cap_regime is EXEMPT exactly for a WELL_CAPITALIZED bank (PRD §3.1).
    """
    expected_total = (
        data["core_deposits_cents"]
        + data["brokered_deposits_cents"]
        + data["listing_service_deposits_cents"]
        + data["reciprocal_deposits_cents"]
    )
    assert data["total_deposits_cents"] == expected_total, (
        "total_deposits_cents must equal core_deposits_cents plus the three "
        f"wholesale buckets: expected {expected_total}, got {data['total_deposits_cents']}"
    )
    expected_regime = (
        "EXEMPT" if data["capital_category"] == "WELL_CAPITALIZED" else "CAPPED"
    )
    assert data["rate_cap_regime"] == expected_regime, (
        f"rate_cap_regime must be {expected_regime} for capital_category "
        f"{data['capital_category']}, got {data['rate_cap_regime']}"
    )


def assert_national_rate_cap(data: dict) -> None:
    assert_append_only_fields(data, "NationalRateCap")
    assert data["tenor_bucket"] in _MEMBERS(TenorBucket)
    assert isinstance(data["published_national_rate_bps"], int)
    assert data["published_national_rate_bps"] >= 0
    assert_calendar_date(data["effective_date"], "effective_date")
    assert data["cap_bps"] == data["published_national_rate_bps"] + 75, (
        "cap_bps must be the published rate plus 75 basis points"
    )
    assert data["non_maturity_cap_bps"] == data["published_national_rate_bps"] + 50, (
        "non_maturity_cap_bps must be the published rate plus 50 basis points"
    )
    assert isinstance(data["published_by_user_id"], str) and data["published_by_user_id"]


def assert_broker(data: dict) -> None:
    assert_common_fields(data, "Broker")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["broker_type"] in _MEMBERS(BrokerType)
    assert isinstance(data["has_placement_discretion"], bool)
    assert data["fee_structure"] in _MEMBERS(FeeStructure)
    assert_non_negative_cents(data, "fee_flat_cents")
    assert isinstance(data["fee_bps"], int) and data["fee_bps"] >= 0
    assert data["diligence_status"] in _MEMBERS(DiligenceStatus)
    assert isinstance(data["approved_agreement_count"], int)
    assert data["approved_agreement_count"] >= 0


def assert_broker_agreement(data: dict) -> None:
    assert_common_fields(data, "BrokerAgreement")
    assert is_valid_uuid(data.get("broker_id", "")), "broker_id must be a UUID string"
    assert isinstance(data["agreement_ref"], str) and data["agreement_ref"]
    assert data["status"] in _MEMBERS(AgreementStatus)
    assert data["fee_structure"] in _MEMBERS(FeeStructure)
    assert isinstance(data["fee_bps"], int) and data["fee_bps"] >= 0
    assert_non_negative_cents(data, "fee_flat_cents", "accrued_fee_cents")
    assert isinstance(data["termination_notice_days"], int)
    assert data["termination_notice_days"] >= 0
    assert_calendar_date(data["effective_date"], "effective_date")
    for field in (
        "aml_program_score",
        "financial_condition_score",
        "insurance_coverage_score",
        "recordkeeping_score",
        "diligence_score",
    ):
        assert isinstance(data[field], int) and 0 <= data[field] <= 100, (
            f"{field} must be an integer within 0 to 100 inclusive, got {data[field]!r}"
        )
    assert isinstance(data["rfi_round_count"], int) and data["rfi_round_count"] >= 0
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]


def assert_primary_purpose_exception(data: dict) -> None:
    assert_common_fields(data, "PrimaryPurposeException")
    assert is_valid_uuid(data.get("broker_id", ""))
    assert is_valid_uuid(data.get("institution_id", ""))
    assert data["exception_basis"] in _MEMBERS(ExceptionBasis)
    assert data["filing_type"] in _MEMBERS(FilingType)
    assert data["test_outcome"] in _MEMBERS(TestOutcome)
    assert data["status"] in _MEMBERS(ExceptionStatus)
    assert isinstance(data["designated_business_line"], str)
    assert_non_negative_cents(
        data, "total_customer_assets_cents", "deposits_placed_at_ifs_cents"
    )
    assert isinstance(data["enabling_transaction_count"], int)
    assert isinstance(data["total_transaction_count"], int)
    assert isinstance(data["business_line_deposit_ratio_bps"], int)
    assert isinstance(data["enabling_transaction_ratio_bps"], int)
    assert isinstance(data["info_request_round_count"], int)
    assert isinstance(data["reliant_program_count"], int)
    assert data["reliant_program_count"] >= 0
    if data.get("reporting_due_date") is not None:
        assert_calendar_date(data["reporting_due_date"], "reporting_due_date")
    expected_type = (
        "APPLICATION" if data["exception_basis"] == "OTHER_APPLICATION" else "NOTICE"
    )
    assert data["filing_type"] == expected_type, (
        f"filing_type must be {expected_type} for basis {data['exception_basis']}"
    )


def assert_deposit_program(data: dict) -> None:
    assert_common_fields(data, "DepositProgram")
    assert is_valid_uuid(data.get("institution_id", ""))
    assert data["funding_channel_claim"] in _MEMBERS(FundingChannelClaim)
    assert data["product_type"] in _MEMBERS(ProductType)
    assert data["tenor_bucket"] in _MEMBERS(TenorBucket)
    assert data["titling_convention"] in _MEMBERS(TitlingConvention)
    assert data["state"] in _MEMBERS(ProgramState)
    assert isinstance(data["tenor_days"], int) and data["tenor_days"] >= 0
    assert isinstance(data["offered_rate_bps"], int) and data["offered_rate_bps"] >= 0
    assert isinstance(data["early_withdrawal_penalty_days"], int)
    assert isinstance(data["principal_erosion_allowed"], bool)
    assert isinstance(data["pass_through_insurance"], bool)
    assert isinstance(data["rollover_enabled"], bool)
    assert_non_negative_cents(
        data, "reciprocal_arrangement_cents", "outstanding_principal_cents"
    )
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]
    assert_tenor_bucket_matches(data["product_type"], data["tenor_days"],
                                data["tenor_bucket"])


def assert_tenor_bucket_matches(product_type: str, tenor_days: int,
                                tenor_bucket: str) -> None:
    """The bucket assignment rule of PRD §3.4, with inclusive upper edges."""
    if product_type in ("MONEY_MARKET", "SAVINGS", "NOW"):
        expected = "NON_MATURITY"
    elif tenor_days <= 30:
        expected = "DAYS_1_30"
    elif tenor_days <= 90:
        expected = "DAYS_31_90"
    elif tenor_days <= 180:
        expected = "DAYS_91_180"
    elif tenor_days <= 365:
        expected = "DAYS_181_365"
    else:
        expected = "DAYS_366_PLUS"
    assert tenor_bucket == expected, (
        f"tenor_bucket for {product_type} at {tenor_days} days must be {expected}, "
        f"got {tenor_bucket}"
    )


def assert_deposit_classification(data: dict) -> None:
    assert_append_only_fields(data, "DepositClassification")
    assert is_valid_uuid(data.get("program_id", ""))
    assert data["determined_class"] in _MEMBERS(DeterminedClass)
    assert data["deposit_broker_prong"] in _MEMBERS(DepositBrokerProng)
    assert data["call_report_line"] in _MEMBERS(CallReportLine)
    assert isinstance(data["rationale_code"], str)
    assert isinstance(data["determined_by_user_id"], str) and data["determined_by_user_id"]
    assert is_iso8601_timestamp(data.get("effective_at", "")), (
        f"effective_at must be ISO 8601 UTC, got {data.get('effective_at')!r}"
    )
    assert isinstance(data["program_version_at_determination"], int)
    assert_call_report_line_mapping(data["determined_class"], data["call_report_line"])


def assert_call_report_line_mapping(determined_class: str, call_report_line: str) -> None:
    """Each determined class maps one-to-one onto a call report line (PRD §3.4)."""
    mapping = {
        "BROKERED": "RC_E_M1_BROKERED",
        "LISTING_SERVICE_NON_BROKERED": "RC_E_M2_LISTING",
        "CORE": "RC_E_CORE",
        "RECIPROCAL_EXCLUDED": "RC_O_M_RECIPROCAL",
    }
    assert call_report_line == mapping[determined_class], (
        f"call_report_line for {determined_class} must be {mapping[determined_class]}, "
        f"got {call_report_line}"
    )


def assert_deposit_placement(data: dict) -> None:
    assert_common_fields(data, "DepositPlacement")
    assert is_valid_uuid(data.get("program_id", ""))
    assert data["funding_status"] in _MEMBERS(FundingStatus)
    assert data["compliance_status"] in _MEMBERS(ComplianceStatus)
    assert data["tenor_bucket"] in _MEMBERS(TenorBucket)
    assert isinstance(data["principal_cents"], int) and data["principal_cents"] > 0, (
        "principal_cents must be strictly greater than zero"
    )
    assert isinstance(data["rate_bps"], int) and data["rate_bps"] >= 0
    assert isinstance(data["tenor_days"], int) and data["tenor_days"] >= 0
    assert_calendar_date(data["issue_date"], "issue_date")
    assert_calendar_date(data["maturity_date"], "maturity_date")
    assert_non_negative_cents(
        data,
        "accrued_interest_cents",
        "early_withdrawal_penalty_cents",
        "fee_accrual_cents",
    )
    # net_settlement_cents is principal plus interest less the penalty; where the
    # programme allows principal erosion it may legitimately fall below principal.
    assert isinstance(data["net_settlement_cents"], int)
    if data.get("settlement_date") is not None:
        assert_calendar_date(data["settlement_date"], "settlement_date")
    if data.get("classified_as") is not None:
        assert data["classified_as"] in _MEMBERS(DeterminedClass)
    if data.get("prepared_by_user_id") is not None:
        # A tranche booked by an officer carries that officer's identifier; a
        # successor created by the sweep has no booking officer of its own.
        assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]


def assert_rate_cap_check(data: dict) -> None:
    assert_append_only_fields(data, "RateCapCheck")
    assert is_valid_uuid(data.get("placement_id", ""))
    assert_calendar_date(data["check_date"], "check_date")
    assert data["applied_tenor_bucket"] in _MEMBERS(TenorBucket)
    assert data["outcome"] in _MEMBERS(RateCapOutcome)
    assert isinstance(data["breach_bps"], int) and data["breach_bps"] >= 0, (
        "breach_bps is floored at zero so it is never negative"
    )
    assert isinstance(data["offered_rate_bps"], int)
    assert isinstance(data["checked_by_user_id"], str) and data["checked_by_user_id"]
    cap = data.get("effective_cap_bps")
    if cap is None:
        assert data["breach_bps"] == 0, (
            "breach_bps is 0 whenever effective_cap_bps is null"
        )
        assert data["outcome"] == "EXEMPT_NO_CAP"
    else:
        expected_breach = max(0, data["offered_rate_bps"] - cap)
        assert data["breach_bps"] == expected_breach, (
            f"breach_bps must be {expected_breach}, got {data['breach_bps']}"
        )
        assert data["outcome"] == ("BREACH" if expected_breach > 0 else "PASS")


def assert_concentration_limit(data: dict) -> None:
    assert_common_fields(data, "ConcentrationLimit")
    assert is_valid_uuid(data.get("institution_id", ""))
    assert data["metric"] in _MEMBERS(ConcentrationMetric)
    assert data["status"] in _MEMBERS(LimitStatus)
    assert data["breach_state"] in _MEMBERS(BreachState)
    assert_bps_in_range(data, "warning_threshold_bps", "breach_threshold_bps")
    assert data["warning_threshold_bps"] < data["breach_threshold_bps"], (
        "warning_threshold_bps must be strictly below breach_threshold_bps"
    )
    assert isinstance(data["current_value_bps"], int)


def assert_contingency_plan(data: dict) -> None:
    assert_common_fields(data, "LiquidityContingencyPlan")
    assert is_valid_uuid(data.get("institution_id", ""))
    assert isinstance(data["plan_version_label"], str) and data["plan_version_label"]
    assert_calendar_date(data["effective_from"], "effective_from")
    assert_calendar_date(data["effective_to"], "effective_to")
    assert data["effective_from"] < data["effective_to"], (
        "effective_from must be strictly before effective_to"
    )
    assert data["status"] in _MEMBERS(PlanStatus)
    assert data["activation_stage"] in _MEMBERS(ActivationStage)
    assert_bps_in_range(
        data, "stage_1_trigger_bps", "stage_2_trigger_bps", "stage_3_trigger_bps"
    )
    assert data["stage_1_trigger_bps"] < data["stage_2_trigger_bps"] < data["stage_3_trigger_bps"], (
        "the three escalation triggers must be strictly increasing"
    )
    for field in ("stage_1_action_code", "stage_2_action_code", "stage_3_action_code"):
        assert isinstance(data[field], str) and data[field]
    assert_non_negative_cents(data, "required_buffer_cents", "buffer_shortfall_cents")
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]
    if data["status"] != "ACTIVATED":
        assert data["activation_stage"] == "NONE", (
            "activation_stage is NONE for any plan whose status is not ACTIVATED"
        )


def assert_call_report_filing(data: dict) -> None:
    assert_common_fields(data, "CallReportFiling")
    assert is_valid_uuid(data.get("institution_id", ""))
    period = data["report_period"]
    assert isinstance(period, str) and len(period) == 6 and period[4] == "Q", (
        f"report_period must be four digits then Q then a quarter number, got {period!r}"
    )
    assert period[:4].isdigit() and period[5] in "1234"
    assert data["status"] in _MEMBERS(FilingStatus)
    assert data["accuracy_status"] in _MEMBERS(AccuracyStatus)
    assert_non_negative_cents(
        data,
        "rc_e_brokered_reported_cents",
        "rc_o_listing_reported_cents",
        "rc_e_core_reported_cents",
        "computed_brokered_cents",
        "computed_listing_cents",
        "computed_core_cents",
        "variance_cents",
    )
    assert isinstance(data["variance_bps"], int) and data["variance_bps"] >= 0
    assert isinstance(data["amendment_round"], int) and data["amendment_round"] >= 0


# ─── Cross-record invariants ──────────────────────────

def assert_wholesale_buckets_match_active_placements(institution: dict,
                                                     placements: list) -> None:
    """Each wholesale bucket equals the sum of principal_cents over the bank's
    ACTIVE placements of the matching class (PRD §2.11)."""
    expected = {"BROKERED": 0, "LISTING_SERVICE_NON_BROKERED": 0, "RECIPROCAL_EXCLUDED": 0}
    for placement in placements:
        if placement.get("funding_status") != "ACTIVE":
            continue
        bucket = placement.get("classified_as")
        if bucket in expected:
            expected[bucket] += placement["principal_cents"]
    assert institution["brokered_deposits_cents"] == expected["BROKERED"], (
        f"brokered_deposits_cents must equal {expected['BROKERED']}, "
        f"got {institution['brokered_deposits_cents']}"
    )
    assert institution["listing_service_deposits_cents"] == expected[
        "LISTING_SERVICE_NON_BROKERED"
    ], (
        "listing_service_deposits_cents must equal "
        f"{expected['LISTING_SERVICE_NON_BROKERED']}, "
        f"got {institution['listing_service_deposits_cents']}"
    )
    assert institution["reciprocal_deposits_cents"] == expected["RECIPROCAL_EXCLUDED"], (
        f"reciprocal_deposits_cents must equal {expected['RECIPROCAL_EXCLUDED']}, "
        f"got {institution['reciprocal_deposits_cents']}"
    )


def assert_net_settlement_arithmetic(placement: dict) -> None:
    """net_settlement_cents is principal plus accrued interest less penalty
    (PRD §3.5)."""
    expected = (
        placement["principal_cents"]
        + placement["accrued_interest_cents"]
        - placement["early_withdrawal_penalty_cents"]
    )
    assert placement["net_settlement_cents"] == expected, (
        f"net_settlement_cents must be {expected}, got {placement['net_settlement_cents']}"
    )
