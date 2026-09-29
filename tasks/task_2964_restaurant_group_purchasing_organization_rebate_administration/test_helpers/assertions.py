"""Shape assertions, arithmetic helpers and the PRD's conservation invariants."""
from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant
from .types import (
    AccrualBasis,
    AccrualBlockReason,
    AccrualStatus,
    AuditStatus,
    ClaimStatus,
    ComplianceResult,
    DealStatus,
    DisputeStatus,
    DistributorStatus,
    ItemStatus,
    LetterScope,
    LetterStatus,
    MatchStatus,
    MemberEnrollmentStatus,
    NormalizationStatus,
    RateCardStatus,
    RateType,
    ReconciliationPosture,
    ReversalReason,
)


def _members(enum_cls):
    return [m.value for m in enum_cls]


# ----------------------------------------------------------- arithmetic ----

def round_half_up(numerator: int, denominator: int) -> int:
    """The PRD's round-half-up: ties always go away from zero."""
    return int(
        (Decimal(numerator) / Decimal(denominator)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def floor_div(numerator: int, denominator: int) -> int:
    """The PRD's floor: truncate towards negative infinity."""
    return numerator // denominator


# ------------------------------------------------------- common fields ----

def assert_common_mutable_fields(data: dict):
    """A mutable record carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )
    assert_three_fractional_digits(data["created_at"])
    assert_three_fractional_digits(data["updated_at"])


def assert_immutable_row_fields(data: dict):
    """The one exception: a row that carries only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert_three_fractional_digits(data["created_at"])
    assert "updated_at" not in data, "an immutable row carries no updated_at"
    assert "version" not in data, "an immutable row carries no version"


def assert_three_fractional_digits(value: str):
    """Instants are ISO 8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str), f"expected a string instant, got {value!r}"
    assert value.endswith("Z"), f"instant must end in Z, got {value!r}"
    assert len(value) == 24 and value[19] == ".", (
        f"instant must carry exactly three fractional digits, got {value!r}"
    )
    assert value[20:23].isdigit(), f"fractional part must be digits, got {value!r}"


def assert_calendar_date(value: str):
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"expected a YYYY-MM-DD calendar date, got {value!r}"
    )


def assert_instants_equal(actual, expected):
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"expected instant {expected!r}, got {actual!r}"
    )


# --------------------------------------------------------------- lists ----

def assert_created_at_desc(rows):
    """Every list endpoint orders by created_at DESCENDING (newest first)."""
    stamps = [canonical_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps, reverse=True), (
        f"rows must be ordered created_at DESC, got {stamps}"
    )


def validate_unpaginated(response, expected_status: int = 200):
    """Read a list response body without asserting pagination meta."""
    assert response.status_code == expected_status, (
        f"expected {expected_status}, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert "data" in body and isinstance(body["data"], list), "data must be a list"
    return body["data"]


def assert_error_meta_is_minimal(response):
    """An error envelope's meta carries only the two request fields."""
    meta = response.json()["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must carry only the two request fields, got {sorted(meta.keys())}"
    )


def assert_request_meta(response):
    meta = response.json()["meta"]
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    assert_three_fractional_digits(meta["api_request_timestamp"])


# ------------------------------------------------------ entity shapes ----

def assert_program_tier(data: dict):
    assert_common_mutable_fields(data)
    assert data["tier_code"] in ("CORE", "PLUS", "ELITE"), data["tier_code"]
    assert data["member_share_bps"] + data["gpo_retention_bps"] == 10000
    for field in (
        "member_share_bps",
        "gpo_retention_bps",
        "admin_fee_bps_low",
        "admin_fee_bps_high",
        "compliance_min_ratio_bps",
        "markup_cap_bps",
    ):
        assert isinstance(data[field], int) and 0 <= data[field] <= 10000, field
    assert data["dispute_window_days"] >= 1
    assert data["reversal_posture_limit"] >= 1


def assert_distributor(data: dict):
    assert_common_mutable_fields(data)
    assert data["status"] in _members(DistributorStatus), data["status"]
    assert 1 <= len(data["name"]) <= 200
    assert 3 <= len(data["dba_code"]) <= 20
    assert isinstance(data["contracted_markup_bps"], int)
    assert 0 <= data["contracted_markup_bps"] <= 10000
    assert isinstance(data["active_letter_count"], int) and data["active_letter_count"] >= 0
    assert isinstance(data["overbilled_recovered_cents"], int)


def assert_member(data: dict):
    assert_common_mutable_fields(data)
    assert data["enrollment_status"] in _members(MemberEnrollmentStatus)
    assert data["reconciliation_posture"] in _members(ReconciliationPosture)
    assert isinstance(data["payout_hold"], bool)
    assert 1 <= len(data["legal_name"]) <= 200
    assert data["committed_annual_spend_cents"] >= 1
    for cents_field in (
        "accrued_member_share_cents",
        "attributed_gpo_retention_cents",
        "attributed_admin_fee_cents",
        "ytd_net_snapshot_cents",
        "recovery_credit_cents",
    ):
        assert isinstance(data[cents_field], int), f"{cents_field} must be integer cents"
    assert data["active_letter_count"] >= 0
    assert data["dispute_reversal_count"] >= 0


def assert_authorization_letter(data: dict):
    assert_common_mutable_fields(data)
    assert data["status"] in _members(LetterStatus), data["status"]
    assert data["scope"] in _members(LetterScope), data["scope"]
    assert_three_fractional_digits(data["effective_from"])
    assert_three_fractional_digits(data["effective_to"])
    assert 1 <= len(data["signatory_name"]) <= 120


def assert_deal(data: dict):
    assert_common_mutable_fields(data)
    assert data["status"] in _members(DealStatus), data["status"]
    assert 1 <= len(data["manufacturer_name"]) <= 200
    assert 3 <= len(data["deal_code"]) <= 30
    assert_calendar_date(data["effective_from"])
    assert_calendar_date(data["effective_to"])
    assert data["required_purchase_window_days"] >= 1
    assert data["contracted_item_count"] >= 0


def assert_contracted_item(data: dict):
    assert_common_mutable_fields(data)
    assert data["status"] in _members(ItemStatus), data["status"]
    assert 1 <= len(data["manufacturer_sku"]) <= 40
    assert 1 <= len(data["normalized_item_key"]) <= 60
    assert data["pack_size"] >= 1
    assert data["baseline_unit_cost_cents"] >= 1
    assert data["contract_unit_cost_cents"] >= 1
    assert data["approved_rate_card_count"] >= 0


def assert_rate_card(data: dict):
    assert_common_mutable_fields(data)
    assert data["status"] in _members(RateCardStatus), data["status"]
    assert data["rate_type"] in _members(RateType), data["rate_type"]
    assert_calendar_date(data["effective_from"])
    assert_calendar_date(data["effective_to"])


def assert_purchase_batch(data: dict):
    assert_common_mutable_fields(data)
    assert data["normalization_status"] in _members(NormalizationStatus)
    assert data["audit_status"] in _members(AuditStatus)
    assert_calendar_date(data["period_start"])
    assert_calendar_date(data["period_end"])
    assert 3 <= len(data["source_reference"]) <= 40
    assert isinstance(data["payout_hold"], bool)
    for field in ("line_count", "total_cases_ingested", "matched_cases", "unmatched_cases"):
        assert isinstance(data[field], int) and data[field] >= 0, field
    assert isinstance(data["overbilled_cents"], int)
    assert_case_conservation(data)


def assert_purchase_line(data: dict):
    assert_common_mutable_fields(data)
    assert data["match_status"] in _members(MatchStatus), data["match_status"]
    assert data["accrual_block_reason"] in _members(AccrualBlockReason)
    assert_calendar_date(data["invoice_date"])
    assert data["cases_shipped"] >= 1
    assert data["invoice_unit_cost_cents"] >= 1
    assert data["distributor_base_cost_cents"] >= 1
    assert data["invoice_extended_cents"] == (
        data["cases_shipped"] * data["invoice_unit_cost_cents"]
    ), "invoice_extended_cents is cases_shipped multiplied by invoice_unit_cost_cents"


def assert_accrual(data: dict):
    assert_common_mutable_fields(data)
    assert data["status"] in _members(AccrualStatus), data["status"]
    assert data["basis"] in _members(AccrualBasis), data["basis"]
    assert data["reversal_reason"] in _members(ReversalReason), data["reversal_reason"]
    for cents_field in (
        "gross_rebate_cents",
        "admin_fee_cents",
        "net_distributable_cents",
        "member_share_cents",
        "gpo_retention_cents",
        "final_adjustment_cents",
    ):
        assert isinstance(data[cents_field], int), f"{cents_field} must be integer cents"
    assert data["accrued_cases"] >= 1


def assert_claim(data: dict):
    assert_common_mutable_fields(data)
    assert data["status"] in _members(ClaimStatus), data["status"]
    assert data["claimed_units"] >= 0
    assert data["claimed_amount_cents"] >= 0
    assert isinstance(data["accrued_amount_cents"], int)


def assert_dispute(data: dict):
    assert_common_mutable_fields(data)
    assert data["status"] in _members(DisputeStatus), data["status"]
    assert data["disputed_amount_cents"] >= 1
    assert data["evidence_round_count"] >= 0


def assert_compliance_review(data: dict):
    """ComplianceReview is the sole immutable entity: id and created_at only."""
    assert_immutable_row_fields(data)
    assert data["result"] in _members(ComplianceResult), data["result"]
    assert isinstance(data["triggered_deal_loss"], bool)
    assert data["window_days"] >= 1
    for cents_field in (
        "committed_spend_prorated_cents",
        "contracted_spend_cents",
        "deal_wide_contracted_spend_cents",
    ):
        assert isinstance(data[cents_field], int), f"{cents_field} must be integer cents"
    assert isinstance(data["purchase_ratio_bps"], int)


# --------------------------------------------------------- invariants ----

def assert_split(
    accrual: dict,
    gross_rebate_cents: int,
    admin_fee_bps_applied: int,
    admin_fee_cents: int,
    net_distributable_cents: int,
    member_share_cents: int,
    gpo_retention_cents: int,
):
    """Assert the pinned five-step waterfall on one accrual, to the cent."""
    assert accrual["gross_rebate_cents"] == gross_rebate_cents
    assert accrual["admin_fee_bps_applied"] == admin_fee_bps_applied
    assert accrual["admin_fee_cents"] == admin_fee_cents
    assert accrual["net_distributable_cents"] == net_distributable_cents
    assert accrual["member_share_cents"] == member_share_cents
    assert accrual["gpo_retention_cents"] == gpo_retention_cents
    assert (
        accrual["net_distributable_cents"]
        == accrual["gross_rebate_cents"] - accrual["admin_fee_cents"]
    ), "step 3: net is gross minus the admin fee"
    assert (
        accrual["gpo_retention_cents"]
        == accrual["net_distributable_cents"] - accrual["member_share_cents"]
    ), "step 5: retention is the residual of net minus the member share"


def assert_member_ledger(
    member: dict,
    accrued_member_share_cents: int,
    attributed_gpo_retention_cents: int,
    attributed_admin_fee_cents: int,
):
    assert member["accrued_member_share_cents"] == accrued_member_share_cents
    assert member["attributed_gpo_retention_cents"] == attributed_gpo_retention_cents
    assert member["attributed_admin_fee_cents"] == attributed_admin_fee_cents


def assert_money_triple(member: dict, expected_gross_total: int):
    """The three member counters must sum to the gross of its live accruals."""
    total = (
        member["accrued_member_share_cents"]
        + member["attributed_gpo_retention_cents"]
        + member["attributed_admin_fee_cents"]
    )
    assert total == expected_gross_total, (
        f"member money triple sums to {total}, expected {expected_gross_total}"
    )


def assert_case_conservation(batch: dict):
    """total_cases_ingested must always equal matched plus unmatched cases."""
    assert batch["total_cases_ingested"] == batch["matched_cases"] + batch["unmatched_cases"], (
        f"case conservation broken: {batch['total_cases_ingested']} != "
        f"{batch['matched_cases']} + {batch['unmatched_cases']}"
    )
