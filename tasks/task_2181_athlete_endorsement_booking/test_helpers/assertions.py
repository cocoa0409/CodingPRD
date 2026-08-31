"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

ACCRUAL_ENTRY_TYPES = ("TRAVEL_ACCRUAL", "REVERSAL", "PENALTY", "BONUS")


def _assert_common_fields(data: dict, label: str):
    """id / created_at / updated_at / version carried by every resource except
    the append-only ledger entry."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1"
    )


def assert_athlete(data: dict):
    _assert_common_fields(data, "Athlete")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["sport"], str)
    assert data["market_tier"] in ("GLOBAL", "NATIONAL", "REGIONAL")
    assert isinstance(data["base_appearance_rate_cents"], int)
    assert data["base_appearance_rate_cents"] >= 1
    assert 0 < float(data["commission_pct"]) <= 0.50
    assert data["status"] in ("ACTIVE", "SUSPENDED", "RETIRED")
    assert isinstance(data["active_exclusivity_count"], int)
    assert data["active_exclusivity_count"] >= 0
    assert isinstance(data["exposure_risk_snapshot_score"], int)
    assert 0 <= data["exposure_risk_snapshot_score"] <= 100
    assert isinstance(data["no_show_count"], int) and data["no_show_count"] >= 0


def assert_brand(data: dict):
    _assert_common_fields(data, "Brand")
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in (
        "BEVERAGE", "FOOTWEAR", "FINANCIAL", "AUTOMOTIVE", "GAMING", "NUTRITION",
    )
    assert isinstance(data["legal_entity_name"], str)
    assert 0 <= data["compliance_rating"] <= 100
    assert isinstance(data["sanctioned"], bool)


def assert_opportunity(data: dict):
    _assert_common_fields(data, "Opportunity")
    assert is_valid_uuid(data["brand_id"])
    assert is_valid_uuid(data["athlete_id"])
    assert data["status"] in (
        "INTAKE", "SCREENED", "REJECTED_FIT", "CONTRACTED", "CLOSED_LOST",
    )
    assert data["territory"] in ("DOMESTIC", "NORTH_AMERICA", "GLOBAL")
    assert data["usage_rights_tier"] in ("SOCIAL_ONLY", "BROADCAST", "PERPETUAL")
    assert 0 <= data["exclusivity_months"] <= 36
    for count_field in ("planned_posts", "planned_appearances", "planned_shoots"):
        assert isinstance(data[count_field], int) and data[count_field] >= 0
    if data["brand_fit_score"] is not None:
        assert 0 <= data["brand_fit_score"] <= 100, "brand_fit_score is clamped to 0..100"


def assert_term_sheet(data: dict):
    _assert_common_fields(data, "TermSheet")
    assert is_valid_uuid(data["opportunity_id"])
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "COUNTERED", "ACCEPTED", "WITHDRAWN", "EXPIRED",
    )
    assert data["fee_cents"] >= 1
    assert 1 <= data["usage_term_months"] <= 60
    assert data["usage_rights_tier"] in ("SOCIAL_ONLY", "BROADCAST", "PERPETUAL")
    assert data["morals_clause_tier"] in ("TIER_A", "TIER_B", "TIER_C")
    assert data["territory"] in ("DOMESTIC", "NORTH_AMERICA", "GLOBAL")
    assert 0 <= data["exclusivity_months"] <= 36
    assert data["appearance_days"] >= 0
    assert data["round_number"] >= 1
    assert 0 <= data["counter_count"] <= 3
    if data["offer_expires_at"] is not None:
        assert is_iso8601_timestamp(data["offer_expires_at"])


def assert_engagement(data: dict):
    _assert_common_fields(data, "Engagement")
    for fk in ("term_sheet_id", "opportunity_id", "athlete_id", "brand_id"):
        assert is_valid_uuid(data[fk]), f"Engagement.{fk} must be a UUID"
    assert data["contract_status"] in (
        "PENDING_COUNTERSIGN", "ACTIVE", "COMPLETED", "TERMINATED",
    )
    assert data["settlement_status"] in ("UNBILLED", "BILLABLE", "INVOICED", "SETTLED")
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["accrued_fee_cents"], int)
    assert isinstance(data["gross_settled_cents"], int)
    assert isinstance(data["required_deliverable_count"], int)
    assert isinstance(data["approved_deliverable_count"], int)
    assert data["approved_deliverable_count"] >= 0
    assert data["morals_clause_tier"] in ("TIER_A", "TIER_B", "TIER_C")


def assert_exclusivity_grant(data: dict):
    _assert_common_fields(data, "ExclusivityGrant")
    assert is_valid_uuid(data["athlete_id"])
    assert is_valid_uuid(data["engagement_id"])
    assert data["status"] in ("PENDING", "ACTIVE", "RELEASED")
    assert data["start_date"] <= data["end_date"]


def assert_appearance_booking(data: dict):
    _assert_common_fields(data, "AppearanceBooking")
    assert is_valid_uuid(data["engagement_id"])
    assert data["status"] in ("HOLD", "CONFIRMED", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert 0 <= data["travel_buffer_hours"] <= 72
    assert isinstance(data["travel_cost_cents"], int)
    assert isinstance(data["travel_days"], int) and data["travel_days"] >= 0
    assert data["outcome"] in (None, "COMPLETED", "NO_SHOW")
    assert data["start_at"] < data["end_at"], "end_at must be strictly after start_at"


def assert_production_slot(data: dict):
    _assert_common_fields(data, "ProductionSlot")
    assert data["capacity"] >= 1
    assert data["window_start_at"] < data["window_end_at"]
    assert isinstance(data["reserved_count"], int) and data["reserved_count"] >= 0


def assert_deliverable(data: dict):
    _assert_common_fields(data, "Deliverable")
    assert is_valid_uuid(data["engagement_id"])
    assert data["type"] in ("SOCIAL_POST", "APPEARANCE", "SHOOT")
    assert data["status"] in (
        "PENDING", "SUBMITTED", "REVISION_REQUESTED", "APPROVED", "VOIDED",
    )
    assert data["weight"] == {"SOCIAL_POST": 1, "APPEARANCE": 4, "SHOOT": 2}[data["type"]], (
        "weight is derived from type: SOCIAL_POST 1, APPEARANCE 4, SHOOT 2"
    )
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert isinstance(data["disclosure_required"], bool)


def assert_disclosure_record(data: dict):
    _assert_common_fields(data, "DisclosureRecord")
    assert is_valid_uuid(data["deliverable_id"])
    assert data["platform"] in ("INSTAGRAM", "X", "TIKTOK", "YOUTUBE", "BROADCAST")
    assert data["status"] in ("PENDING_REVIEW", "COMPLIANT", "NON_COMPLIANT")
    assert isinstance(data["remediation_count"], int) and data["remediation_count"] >= 0
    assert isinstance(data["disclosure_tag"], str)


def assert_payout_statement(data: dict):
    _assert_common_fields(data, "PayoutStatement")
    assert is_valid_uuid(data["engagement_id"])
    assert data["status"] in ("DRAFT", "DISBURSED", "VOIDED")
    assert isinstance(data["line_count"], int) and data["line_count"] >= 0
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["agency_commission_cents"], int)
    assert isinstance(data["penalty_cents"], int) and data["penalty_cents"] >= 0
    assert data["athlete_net_cents"] == (
        data["gross_amount_cents"] - data["agency_commission_cents"] - data["penalty_cents"]
    ), "athlete_net_cents is gross less commission less penalty"


def assert_renewal_option(data: dict):
    _assert_common_fields(data, "RenewalOption")
    assert is_valid_uuid(data["engagement_id"])
    assert data["status"] in ("OPEN", "EXERCISED", "DECLINED", "LAPSED")
    assert data["bonus_tier"] in ("TIER_1", "TIER_2", "TIER_3", "NONE")
    assert isinstance(data["bonus_cents"], int)
    assert data["total_engagement_value_cents"] == (
        data["base_value_cents"] + data["bonus_cents"]
    ), "total_engagement_value_cents is base_value_cents plus bonus_cents"


def assert_ledger_entry(data: dict):
    """A ledger entry is immutable: it carries only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), "LedgerEntry.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "LedgerEntry.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, "A ledger entry has no updated_at"
    assert "version" not in data, "A ledger entry has no version"
    assert data["entry_type"] in (
        "TRAVEL_ACCRUAL", "REVERSAL", "PENALTY", "BONUS", "DISBURSEMENT",
    )
    assert isinstance(data["amount_cents"], int)
    assert is_valid_uuid(data["engagement_id"])


def assert_exposure_summary(data: dict, athlete_id: str = None):
    assert data["variant"] in ("ROSTER_SNAPSHOT", "PIPELINE_PROJECTED")
    for field in ("category_load", "morals_exposure", "noncompliance_hits", "score"):
        assert isinstance(data[field], int), f"exposure summary {field} must be an integer"
    assert 0 <= data["score"] <= 100, "the exposure score has a ceiling of 100"
    if athlete_id is not None:
        assert data["athlete_id"] == athlete_id


def accrual_sum(ledger_rows) -> int:
    """Running sum of the accrual-bearing ledger entries; disbursements excluded."""
    return sum(
        row["amount_cents"] for row in ledger_rows
        if row["entry_type"] in ACCRUAL_ENTRY_TYPES
    )


def assert_accrued_fee_matches_ledger(engagement: dict, ledger_rows):
    """Engagement.accrued_fee_cents is the running sum of its accrual entries."""
    expected = accrual_sum(ledger_rows)
    assert engagement["accrued_fee_cents"] == expected, (
        f"accrued_fee_cents {engagement['accrued_fee_cents']} must equal the ledger "
        f"sum {expected} over TRAVEL_ACCRUAL, REVERSAL, PENALTY and BONUS entries"
    )


def assert_ledger_ordered_by_created_at(ledger_rows):
    stamps = [row["created_at"] for row in ledger_rows]
    assert stamps == sorted(stamps), "ledger entries are returned oldest first"


def parse_instant(value: str):
    """Parse a UTC ISO 8601 instant, with or without fractional seconds."""
    from datetime import datetime, timezone

    assert isinstance(value, str) and value, "expected an ISO 8601 UTC instant"
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def assert_same_instant(actual: str, expected: str, label: str = "instant"):
    """Two UTC instants are equal regardless of how many fractional digits the
    serializer prints."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )
