"""Entity assertions and domain invariant checkers for the franchise API."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    COLLECTIONS_WATCH_SHARE,
    REBATE_TIER_1_FLOOR,
    REBATE_TIER_2_FLOOR,
)


# --------------------------------------------------------------------------
# Shared system-field helpers
# --------------------------------------------------------------------------


def assert_common_fields(data: dict) -> None:
    """Every mutable resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_append_only_fields(data: dict) -> None:
    """Append-only records carry only id and created_at as system fields."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"


def assert_iso_date(value: str, field_name: str) -> None:
    assert isinstance(value, str) and len(value) == 10, (
        f"{field_name} must be a YYYY-MM-DD date, got {value!r}"
    )
    assert value[4] == "-" and value[7] == "-", (
        f"{field_name} must be a YYYY-MM-DD date, got {value!r}"
    )


def assert_period_month(value: str, field_name: str = "period_month") -> None:
    assert isinstance(value, str) and len(value) == 7 and value[4] == "-", (
        f"{field_name} must be a YYYY-MM month, got {value!r}"
    )


def assert_decimal_places(value: float, places: int, field_name: str) -> None:
    """A numeric field must not carry more decimal places than the PRD declares."""
    assert value is not None, f"{field_name} must not be null"
    text = f"{float(value):.10f}".rstrip("0")
    fraction = text.split(".")[1] if "." in text else ""
    assert len(fraction) <= places, (
        f"{field_name} must carry at most {places} decimal places, got {value!r}"
    )


# --------------------------------------------------------------------------
# Entity assertions
# --------------------------------------------------------------------------


def assert_franchisee(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["royalty_rate_bps"], int)
    assert 0 <= data["royalty_rate_bps"] <= 1200, (
        f"royalty_rate_bps must be between 0 and 1200, got {data['royalty_rate_bps']}"
    )
    assert data["status"] in ("ACTIVE", "PROBATION"), f"unexpected status {data['status']!r}"
    assert isinstance(data["national_account_eligible"], bool)
    for counter in (
        "inspection_fail_streak",
        "collections_watch_club_count",
        "disputed_royalty_count",
        "corporate_allocation_cents",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"{counter} must be a non-negative integer, got {data[counter]!r}"
        )
    assert isinstance(data["compliance_score"], int)
    assert 0 <= data["compliance_score"] <= 100, (
        f"compliance_score is clamped to 0..100, got {data['compliance_score']}"
    )


def assert_territory(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["franchisee_id"])
    assert_decimal_places(data["center_lat"], 4, "center_lat")
    assert_decimal_places(data["center_lng"], 4, "center_lng")
    assert_decimal_places(data["protected_radius_km"], 1, "protected_radius_km")
    assert 0.5 <= data["protected_radius_km"] <= 50.0, (
        f"protected_radius_km must be within 0.5..50.0, got {data['protected_radius_km']}"
    )
    assert data["state_code"] in ("CA", "TX", "NY")
    assert data["status"] in ("RESERVED", "ACTIVE")
    assert isinstance(data["relocation_count"], int) and data["relocation_count"] >= 0
    if data.get("encroachment_km") is not None:
        assert_decimal_places(data["encroachment_km"], 3, "encroachment_km")


def assert_club(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["territory_id"])
    assert is_valid_uuid(data["franchisee_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert data["state_code"] in ("CA", "TX", "NY")
    assert isinstance(data["lat"], (int, float))
    assert isinstance(data["lng"], (int, float))
    assert_iso_date(data["opened_on"], "opened_on")
    assert isinstance(data["guest_fee_cents"], int)
    assert 0 <= data["guest_fee_cents"] <= 5000, (
        f"guest_fee_cents must be within 0..5000, got {data['guest_fee_cents']}"
    )
    assert data["status"] in ("PRE_OPENING", "OPEN", "SUSPENDED")
    assert data["equipment_compliance_state"] in ("COMPLIANT", "WATCH", "NON_COMPLIANT")
    assert data["last_inspection_score"] is None or isinstance(
        data["last_inspection_score"], int
    )
    for counter in ("active_agreement_count", "delinquent_member_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert isinstance(data["collections_watch"], bool)
    assert isinstance(data["settlement_ledger_cents"], int)


def assert_relocation_request(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["club_id"])
    assert isinstance(data["requested_lat"], (int, float))
    assert isinstance(data["requested_lng"], (int, float))
    assert_decimal_places(data["requested_radius_km"], 1, "requested_radius_km")
    assert isinstance(data["justification"], str) and data["justification"]
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "CHANGES_REQUESTED",
        "APPROVED",
        "REJECTED",
        "WITHDRAWN",
    )
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_plan_template(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["code"], str)
    assert 2 <= len(data["code"]) <= 24, f"code must be 2..24 characters, got {data['code']!r}"
    assert data["monthly_dues_cents"] >= 100, (
        f"monthly_dues_cents must be at least 100, got {data['monthly_dues_cents']}"
    )
    assert data["initiation_fee_cents"] >= 0
    assert 1 <= data["term_months"] <= 36
    assert 0 <= data["cancellation_notice_days"] <= 60
    assert data["floor_price_cents"] >= 0
    assert data["status"] in ("DRAFT", "PUBLISHED")


def assert_promotion(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["franchisee_id"])
    assert is_valid_uuid(data["plan_template_id"])
    assert isinstance(data["code"], str) and data["code"]
    assert_decimal_places(data["discount_pct"], 3, "discount_pct")
    assert 0.0 <= data["discount_pct"] <= 0.500
    assert_iso_date(data["starts_on"], "starts_on")
    assert_iso_date(data["ends_on"], "ends_on")
    assert data["starts_on"] <= data["ends_on"], "starts_on must not follow ends_on"
    assert data["status"] in (
        "PENDING_REVIEW",
        "APPROVED",
        "REJECTED",
        "WITHDRAWN_BY_BRAND",
    )


def assert_member(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["home_state_code"] in ("CA", "TX", "NY")
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["agreement_count"], int) and data["agreement_count"] >= 0


def assert_corporate_account(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert_decimal_places(data["corporate_credit_pct"], 3, "corporate_credit_pct")
    assert 0.0 <= data["corporate_credit_pct"] <= 0.100
    assert data["allocation_method"] in ("USAGE_SHARE", "EQUAL_SPLIT")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    for counter in (
        "pool_balance_cents",
        "allocated_cents",
        "lifetime_funded_cents",
        "enrolled_agreement_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert_corporate_pool_conserved(data)


def assert_corporate_pool_conserved(data: dict) -> None:
    """pool_balance_cents + allocated_cents must always equal lifetime_funded_cents."""
    assert (
        data["pool_balance_cents"] + data["allocated_cents"]
        == data["lifetime_funded_cents"]
    ), (
        "pool_balance_cents + allocated_cents must equal lifetime_funded_cents, got "
        f"{data['pool_balance_cents']} + {data['allocated_cents']} != "
        f"{data['lifetime_funded_cents']}"
    )


def assert_agreement(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["home_club_id"])
    assert is_valid_uuid(data["plan_template_id"])
    assert isinstance(data["multi_club_access"], bool)
    assert data["state_code"] in ("CA", "TX", "NY")
    assert_iso_date(data["signed_on"], "signed_on")
    assert_iso_date(data["term_end_on"], "term_end_on")
    for money in (
        "monthly_dues_base_cents",
        "initiation_fee_cents",
        "promo_discount_cents",
        "corporate_credit_cents",
        "multi_club_credit_cents",
        "effective_monthly_dues_cents",
        "outstanding_balance_cents",
        "dues_paid_cents",
    ):
        assert isinstance(data[money], int), f"{money} must be an integer number of cents"
    assert isinstance(data["cancellation_notice_days"], int)
    assert data["agreement_status"] in (
        "PENDING",
        "ACTIVE",
        "FROZEN",
        "CANCELLATION_PENDING",
        "CANCELLED",
    )
    assert data["dues_status"] in (
        "CURRENT",
        "PAST_DUE",
        "DELINQUENT",
        "IN_COLLECTIONS",
        "WRITTEN_OFF",
    )
    assert isinstance(data["delinquency_days"], int) and data["delinquency_days"] >= 0
    assert isinstance(data["transfer_count"], int) and data["transfer_count"] >= 0


def assert_transfer_request(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["from_club_id"])
    assert is_valid_uuid(data["to_club_id"])
    assert data["from_club_id"] != data["to_club_id"], (
        "a transfer request must name two different clubs"
    )
    assert isinstance(data["reason"], str) and data["reason"]
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "COMPLETED")


def assert_guest_usage_event(data: dict) -> None:
    assert_append_only_fields(data)
    assert "version" not in data, "an append-only visit batch carries no version field"
    assert "updated_at" not in data, "an append-only visit batch carries no updated_at field"
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["host_club_id"])
    assert is_valid_uuid(data["home_club_id_at_visit"])
    assert_period_month(data["period_month"])
    assert isinstance(data["visit_count"], int) and data["visit_count"] >= 1
    assert isinstance(data["guest_fee_cents_at_visit"], int)
    assert (
        data["usage_fee_cents"] == data["visit_count"] * data["guest_fee_cents_at_visit"]
    ), (
        "usage_fee_cents must equal visit_count multiplied by guest_fee_cents_at_visit, got "
        f"{data['usage_fee_cents']}"
    )


def assert_usage_settlement(data: dict) -> None:
    assert_common_fields(data)
    assert_period_month(data["period_month"])
    assert is_valid_uuid(data["home_club_id"])
    assert is_valid_uuid(data["host_club_id"])
    assert data["home_club_id"] != data["host_club_id"], (
        "a settlement must name two different clubs"
    )
    for counter in ("event_count", "visit_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0
    for money in (
        "gross_fee_cents",
        "admin_hold_cents",
        "net_before_rebate_cents",
        "volume_rebate_cents",
        "net_payable_cents",
    ):
        assert isinstance(data[money], int), f"{money} must be an integer number of cents"
    assert data["status"] in ("OPEN", "POSTED", "REVERSED")
    assert_settlement_waterfall(data)


def assert_settlement_waterfall(data: dict) -> None:
    """The waterfall identities the PRD states for every settlement."""
    assert (
        data["net_before_rebate_cents"]
        == data["gross_fee_cents"] - data["admin_hold_cents"]
    ), "net_before_rebate_cents must equal gross_fee_cents minus admin_hold_cents"
    assert (
        data["net_payable_cents"]
        == data["net_before_rebate_cents"] - data["volume_rebate_cents"]
    ), "net_payable_cents must equal net_before_rebate_cents minus volume_rebate_cents"
    net_before = data["net_before_rebate_cents"]
    if net_before < REBATE_TIER_1_FLOOR:
        expected_pct = 0.00
    elif net_before < REBATE_TIER_2_FLOOR:
        expected_pct = 0.03
    else:
        expected_pct = 0.06
    assert abs(data["rebate_pct"] - expected_pct) < 1e-9, (
        f"net_before_rebate_cents {net_before} selects rebate_pct {expected_pct}, got "
        f"{data['rebate_pct']}"
    )


def assert_billing_event(data: dict) -> None:
    assert_append_only_fields(data)
    assert "version" not in data, "an append-only ledger entry carries no version field"
    assert "updated_at" not in data, "an append-only ledger entry carries no updated_at field"
    assert is_valid_uuid(data["agreement_id"])
    assert data["event_type"] in (
        "DUES_POSTED",
        "PAYMENT_RECEIVED",
        "PAYMENT_FAILED",
        "WRITE_OFF",
        "TRANSFER_FEE_POSTED",
        "COLLECTION_PLACED",
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert_iso_date(data["occurred_on"], "occurred_on")
    assert data["source"] in ("BILLING_PARTNER", "SYSTEM")
    assert isinstance(data["resulting_outstanding_balance_cents"], int)
    if data["event_type"] == "DUES_POSTED":
        assert data["due_on"] is not None, "a DUES_POSTED entry must carry due_on"
    elif data["event_type"] not in ("TRANSFER_FEE_POSTED",):
        assert data["due_on"] is None, (
            f"{data['event_type']} must leave due_on null, got {data['due_on']!r}"
        )
    if data["event_type"] in ("PAYMENT_FAILED", "COLLECTION_PLACED"):
        assert data["amount_cents"] == 0, (
            f"{data['event_type']} must carry amount_cents 0, got {data['amount_cents']}"
        )


def assert_royalty_report(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["franchisee_id"])
    assert_period_month(data["period_month"])
    assert isinstance(data["reported_member_count"], int)
    assert data["reported_member_count"] >= 0
    assert isinstance(data["verified_member_count"], int)
    for money in (
        "reported_dues_basis_cents",
        "verified_dues_basis_cents",
        "reported_royalty_cents",
        "royalty_due_cents",
    ):
        assert isinstance(data[money], int)
    assert_decimal_places(data["variance_pct"], 2, "variance_pct")
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "DISPUTED", "ADJUSTED")


def assert_inspection(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["club_id"])
    assert_iso_date(data["inspection_date"], "inspection_date")
    assert data["status"] in (
        "SCHEDULED",
        "REMEDIATION_REQUIRED",
        "REMEDIATION_WAIVED",
        "CLOSED",
    )
    if data.get("variant_applied") is not None:
        assert data["variant_applied"] in ("STANDARD_CYCLE", "ACCELERATED_CYCLE")
    if data.get("score") is not None:
        assert isinstance(data["score"], int) and 0 <= data["score"] <= 100
    if data.get("refresh_pts") is not None:
        assert isinstance(data["refresh_pts"], int) and 0 <= data["refresh_pts"] <= 100


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------


def assert_collections_watch_consistent(club: dict) -> None:
    """collections_watch is on exactly when the delinquent share strictly exceeds the
    brand threshold, with a non-zero denominator."""
    denominator = club["active_agreement_count"]
    numerator = club["delinquent_member_count"]
    expected = denominator > 0 and (numerator / denominator) > COLLECTIONS_WATCH_SHARE
    assert club["collections_watch"] is expected, (
        f"collections_watch should be {expected} for {numerator}/{denominator}, got "
        f"{club['collections_watch']}"
    )


def assert_settlement_ledger_conserved(clubs: list) -> None:
    """The sum of settlement_ledger_cents across every club must be zero."""
    total = sum(club["settlement_ledger_cents"] for club in clubs)
    assert total == 0, (
        f"settlement_ledger_cents must net to zero across all clubs, got {total}"
    )


def assert_agreement_pricing_components(agreement: dict) -> None:
    """Each declared credit is subtracted from the pinned base to give effective dues."""
    expected = (
        agreement["monthly_dues_base_cents"]
        - agreement["promo_discount_cents"]
        - agreement["corporate_credit_cents"]
        - agreement["multi_club_credit_cents"]
    )
    assert agreement["effective_monthly_dues_cents"] == expected, (
        "effective_monthly_dues_cents must be the base less each rounded credit, expected "
        f"{expected}, got {agreement['effective_monthly_dues_cents']}"
    )


def assert_version_bumped_by(before: dict, after: dict, expected_delta: int = 1) -> None:
    assert after["version"] == before["version"] + expected_delta, (
        f"version should advance by {expected_delta} from {before['version']}, got "
        f"{after['version']}"
    )
