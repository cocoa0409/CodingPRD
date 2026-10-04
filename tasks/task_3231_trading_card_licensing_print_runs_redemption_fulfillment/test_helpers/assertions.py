"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ArtworkApprovalStatus,
    CardSetStatus,
    CollectorComplaintStatus,
    CollectorNotificationStatus,
    DistributionAllocationStatus,
    LicenseStatus,
    PackConfigurationStatus,
    PrintRunDecisionStatus,
    PrintRunStatus,
    ProductLineStatus,
    QualityClaimStatus,
    RedemptionStatus,
    SigningSessionStatus,
)


def _assert_common(data: dict):
    """All twelve resources carry id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 for a freshly created resource"


def assert_license(data: dict):
    _assert_common(data)
    assert isinstance(data["grantor_name"], str) and data["grantor_name"]
    assert data["exclusivity_scope"] in ["EXCLUSIVE", "NON_EXCLUSIVE"]
    assert is_iso8601_timestamp(data["term_starts_on"])
    assert is_iso8601_timestamp(data["term_ends_on"])
    assert isinstance(data["approval_window_days"], int)
    assert isinstance(data["rights_version"], int) and data["rights_version"] >= 0
    assert data["status"] in [s.value for s in LicenseStatus]
    assert isinstance(data["set_count"], int) and data["set_count"] >= 0
    assert isinstance(data["approved_set_count"], int) and data["approved_set_count"] >= 0


def assert_product_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["license_id"])
    assert isinstance(data["line_name"], str) and data["line_name"]
    assert data["line_kind"] in ["BASE", "INSERT", "PREMIUM"]
    for f in ("packs_per_box", "cards_per_pack", "boxes_per_case", "cases_printed"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative integer"
    assert is_iso8601_timestamp(data["run_planned_on"])
    assert isinstance(data["sets_per_case"], int)
    assert isinstance(data["allocated_cards"], int) and data["allocated_cards"] >= 0
    assert data["status"] in [s.value for s in ProductLineStatus]


def assert_card_set(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["product_line_id"])
    assert isinstance(data["set_name"], str) and data["set_name"]
    assert data["set_tier"] in ["BASE", "INSERT", "PREMIUM"]
    assert isinstance(data["rights_pinned_version"], int)
    assert isinstance(data["print_run_quantity"], int) and data["print_run_quantity"] >= 0
    assert isinstance(data["announced"], bool)
    assert isinstance(data["serial_numbered"], bool)
    assert data["print_run_status"] in [s.value for s in PrintRunStatus]
    assert isinstance(data["autograph_planned_count"], int)
    assert isinstance(data["autograph_secured_count"], int)
    assert isinstance(data["autograph_redemptions_outstanding"], int)
    assert isinstance(data["quality_claim_count"], int) and data["quality_claim_count"] >= 0
    assert isinstance(data["settled_complaint_count"], int)
    assert data["status"] in [s.value for s in CardSetStatus]


def assert_pack_configuration(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["card_set_id"])
    assert isinstance(data["config_serial"], int)
    assert isinstance(data["odd_value"], int)
    for f in ("base_packs", "insert_packs", "premium_packs", "total_cards"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert data["status"] in [s.value for s in PackConfigurationStatus]


def assert_signing_session(data: dict):
    _assert_common(data)
    assert isinstance(data["signer_name"], str) and data["signer_name"]
    assert data["signer_kind"] in ["PLAYER_ASSOCIATION", "INDEPENDENT"]
    assert is_valid_uuid(data["license_id"])
    assert is_iso8601_timestamp(data["scheduled_on"])
    assert is_iso8601_timestamp(data["ship_date"])
    assert isinstance(data["total_allocated_count"], int)
    assert isinstance(data["allocation_lines"], list)
    for line in data["allocation_lines"]:
        assert is_valid_uuid(line["card_set_id"])
        assert "player_id" in line
        assert isinstance(line["quantity_delivered"], int)
    assert data["status"] in [s.value for s in SigningSessionStatus]


def assert_artwork_approval(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["card_set_id"])
    assert isinstance(data["artwork_code"], str) and data["artwork_code"]
    assert is_valid_uuid(data["approver_id"])
    assert is_iso8601_timestamp(data["submitted_on"])
    assert data["status"] in [s.value for s in ArtworkApprovalStatus]


def assert_print_run_decision(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["card_set_id"])
    assert data["authority"] in ["SALES_HISTORY", "MARKET_DEMAND", "BRAND_DIRECTIVE"]
    assert isinstance(data["proposed_against_line_version"], int)
    assert isinstance(data["demand_multiplier"], (int, float))
    assert isinstance(data["declared_quantity"], int)
    assert isinstance(data["announced"], bool)
    assert isinstance(data["final_quantity"], int) and data["final_quantity"] >= 0
    assert is_iso8601_timestamp(data["proposed_on"])
    assert data["status"] in [s.value for s in PrintRunDecisionStatus]


def assert_redemption(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["card_set_id"])
    assert isinstance(data["redemption_code"], str) and data["redemption_code"]
    assert isinstance(data["signer_name"], str) and data["signer_name"]
    assert isinstance(data["estimated_value_cents"], int)
    assert is_iso8601_timestamp(data["opened_on"])
    assert data["deadline_days"] in (365, 730)
    assert data["status"] in [s.value for s in RedemptionStatus]
    assert isinstance(data["collector_notification_count"], int)


def assert_collector_notification(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["redemption_id"])
    assert isinstance(data["notice_code"], str) and data["notice_code"]
    assert isinstance(data["notice_text"], str) and data["notice_text"]
    assert is_iso8601_timestamp(data["opened_on"])
    assert data["status"] in [s.value for s in CollectorNotificationStatus]


def assert_distribution_allocation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["product_line_id"])
    assert data["channel"] in ["HOBBY", "MASS", "DIRECT"]
    assert isinstance(data["quantity_allocated"], int)
    assert isinstance(data["shipped_quantity"], int)
    assert isinstance(data["effective_price_cents"], int)
    assert data["status"] in [s.value for s in DistributionAllocationStatus]


def assert_quality_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["card_set_id"])
    assert data["claim_type"] in ["MISPRINT", "DAMAGE", "MISSING_HIT"]
    assert data["severity"] in ["MINOR", "MAJOR", "CRITICAL"]
    assert isinstance(data["affected_quantity"], int)
    assert is_iso8601_timestamp(data["filed_on"])
    assert data["status"] in [s.value for s in QualityClaimStatus]
    assert data["claim_weight"] in (1, 2, 3)


def assert_collector_complaint(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["card_set_id"])
    assert isinstance(data["complaint_label"], str) and data["complaint_label"]
    assert data["breach_reason"] in ["UNDISCLOSED_PRINT_RUN", "NO_REPLACEMENT_POLICY"]
    assert isinstance(data["claim_quantity"], int)
    assert data["status"] in [s.value for s in CollectorComplaintStatus]


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_license_invariants(data: dict):
    """Counters stay within their natural bounds and the rights pin never lags."""
    assert data["set_count"] >= 0
    assert data["approved_set_count"] >= 0
    assert data["approved_set_count"] <= data["set_count"], (
        "approved_set_count can never exceed set_count"
    )
    assert data["rights_version"] >= 0


def assert_card_set_invariants(data: dict):
    assert data["print_run_quantity"] >= 0
    assert data["autograph_secured_count"] >= 0
    assert data["autograph_redemptions_outstanding"] >= 0
    assert data["quality_claim_count"] >= 0
    if data["print_run_status"] == PrintRunStatus.UNDECIDED.value:
        assert data["print_run_quantity"] == 0 or data["status"] != CardSetStatus.APPROVED
    if data["print_run_status"] in (
        PrintRunStatus.DISCLOSED.value,
        PrintRunStatus.UNDISCLOSED.value,
    ):
        assert data["print_run_quantity"] > 0


def assert_endorsement_pair(line: dict, card_set: dict):
    """An allocation line points at a set that is approved for autograph stock."""
    assert line["card_set_id"] == card_set["id"]
    assert card_set["status"] == CardSetStatus.APPROVED.value