"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BrandApplicationStatus,
    BrandConflictClaimStatus,
    BrandRegistrationStatus,
    Disposition,
    DistributionVariant,
    EstrayCaseStatus,
    FeeRemittanceStatus,
    FeeStatus,
    InspectorStatus,
    IntakeStatus,
    LotStatus,
    MatchStatus,
    OwnerStanding,
    ScheduleStatus,
    TheftInvestigationStatus,
    TheftOutcome,
)


def _members(enum_cls) -> list:
    return [member.value for member in enum_cls]


def assert_common_record_fields(data: dict) -> None:
    """Every record the board persists carries an opaque UUID `id`, ISO 8601
    `created_at` and `updated_at`, and an integer `version` starting at 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_owner(data: dict) -> None:
    assert_common_record_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["mailing_state"], str) and len(data["mailing_state"]) == 2
    assert data["mailing_state"].isupper(), "mailing_state is two uppercase letters"
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["standing"] in _members(OwnerStanding)
    assert isinstance(data["posted_arrears_cents"], int)
    assert isinstance(data["projected_arrears_cents"], int)
    assert data["posted_arrears_cents"] >= 0
    assert data["projected_arrears_cents"] >= 0


def assert_territory(data: dict) -> None:
    assert_common_record_fields(data)
    assert isinstance(data["territory_code"], str) and data["territory_code"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["travel_surcharge_cents"], int)
    assert data["travel_surcharge_cents"] >= 0
    assert isinstance(data["impound_capacity_head"], int)
    assert data["impound_capacity_head"] >= 1
    assert isinstance(data["impound_current_head"], int)
    assert data["impound_current_head"] >= 0
    assert data["intake_status"] in _members(IntakeStatus)


def assert_inspector(data: dict) -> None:
    assert_common_record_fields(data)
    assert isinstance(data["badge_number"], str) and data["badge_number"]
    assert is_valid_uuid(data.get("home_territory_id", ""))
    assert is_iso8601_timestamp(data.get("certification_expires_on", ""))
    assert isinstance(data["max_daily_assignments"], int)
    assert data["max_daily_assignments"] >= 1
    assert data["status"] in _members(InspectorStatus)
    assert isinstance(data["active_assignment_count"], int)
    assert data["active_assignment_count"] >= 0


def assert_brand_application(data: dict) -> None:
    assert_common_record_fields(data)
    assert is_valid_uuid(data.get("owner_id", ""))
    assert data["application_type"] in ["NEW", "TRANSFER", "RENEWAL"]
    assert isinstance(data["brand_symbol"], str) and data["brand_symbol"]
    assert data["position_code"] in [
        "LEFT_RIB", "RIGHT_RIB", "LEFT_HIP", "RIGHT_HIP",
        "LEFT_SHOULDER", "RIGHT_SHOULDER",
    ]
    assert data["species_class"] in ["CATTLE", "HORSE", "SHEEP"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["documented_prior_use_years"], int)
    assert data["documented_prior_use_years"] >= 0
    assert isinstance(data["prior_use_affidavit_on_file"], bool)
    assert is_iso8601_timestamp(data.get("original_filed_at", ""))
    assert is_iso8601_timestamp(data.get("effective_priority_at", ""))
    assert isinstance(data["correction_rounds"], int)
    assert data["status"] in _members(BrandApplicationStatus)
    assert isinstance(data["assessed_filing_fee_cents"], int)
    assert data["assessed_filing_fee_cents"] >= 0


def assert_brand_registration(data: dict) -> None:
    assert_common_record_fields(data)
    assert is_valid_uuid(data.get("owner_id", ""))
    assert is_valid_uuid(data.get("source_application_id", ""))
    assert isinstance(data["brand_symbol"], str) and data["brand_symbol"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert is_iso8601_timestamp(data.get("recorded_at", ""))
    assert is_iso8601_timestamp(data.get("expires_on", ""))
    assert is_iso8601_timestamp(data.get("effective_priority_at", ""))
    assert isinstance(data["priority_rank"], int) and data["priority_rank"] >= 1
    assert data["status"] in _members(BrandRegistrationStatus)
    assert isinstance(data["encumbrance_count"], int)
    assert data["encumbrance_count"] >= 0


def assert_brand_conflict_claim(data: dict) -> None:
    assert_common_record_fields(data)
    assert is_valid_uuid(data.get("claimant_owner_id", ""))
    assert is_valid_uuid(data.get("respondent_registration_id", ""))
    assert data["grounds"] in ["PRIOR_USE", "DECEPTIVE_SIMILARITY", "RECORDING_ERROR"]
    assert data["status"] in _members(BrandConflictClaimStatus)


def assert_inspection_order(data: dict) -> None:
    assert_common_record_fields(data)
    assert is_valid_uuid(data.get("owner_id", ""))
    assert is_valid_uuid(data.get("territory_id", ""))
    assert data["inspection_purpose"] in ["SALE", "MOVEMENT", "SLAUGHTER"]
    assert is_iso8601_timestamp(data.get("requested_window_start_at", ""))
    assert is_iso8601_timestamp(data.get("requested_window_end_at", ""))
    assert data["schedule_status"] in _members(ScheduleStatus)
    assert data["fee_status"] in _members(FeeStatus)
    assert isinstance(data["assessed_fee_cents"], int)
    assert data["assessed_fee_cents"] >= 0
    assert isinstance(data["hold_flag"], bool)
    assert isinstance(data["head_count_presented"], int)
    assert data["head_count_presented"] >= 0


def assert_animal_lot(data: dict) -> None:
    assert_common_record_fields(data)
    assert is_valid_uuid(data.get("inspection_order_id", ""))
    assert data["species_class"] in ["CATTLE", "HORSE", "SHEEP"]
    assert isinstance(data["head_count"], int) and data["head_count"] >= 1
    assert data["lot_status"] in _members(LotStatus)
    assert data["match_status"] in _members(MatchStatus)
    assert data["disposition"] in _members(Disposition)


def assert_bill_of_sale(data: dict) -> None:
    """An ownership instrument is immutable once written: it carries only `id`
    and `created_at`, with no `updated_at` and no `version` (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "a bill of sale has no updated_at field"
    assert "version" not in data, "a bill of sale has no version field"
    assert is_valid_uuid(data.get("seller_owner_id", ""))
    assert is_valid_uuid(data.get("buyer_owner_id", ""))
    assert isinstance(data["document_number"], str) and data["document_number"]
    assert isinstance(data["head_count"], int) and data["head_count"] >= 1
    assert data["species_class"] in ["CATTLE", "HORSE", "SHEEP"]


def assert_estray_case(data: dict) -> None:
    assert_common_record_fields(data)
    assert is_valid_uuid(data.get("animal_lot_id", ""))
    assert is_valid_uuid(data.get("territory_id", ""))
    assert isinstance(data["head_count"], int) and data["head_count"] >= 1
    assert is_iso8601_timestamp(data.get("impounded_at", ""))
    assert is_iso8601_timestamp(data.get("statutory_release_on", ""))
    assert data["status"] in _members(EstrayCaseStatus)
    assert data["distribution_variant"] in _members(DistributionVariant)
    for bucket in (
        "care_cost_cents",
        "handling_fee_cents",
        "claimant_residual_cents",
        "board_forfeiture_cents",
    ):
        assert isinstance(data[bucket], int), f"{bucket} must be integer cents"
        assert data[bucket] >= 0, f"{bucket} must never be negative, got {data[bucket]}"
    assert isinstance(data["claim_denied_count"], int)


def assert_theft_investigation(data: dict) -> None:
    assert_common_record_fields(data)
    assert is_valid_uuid(data.get("animal_lot_id", ""))
    assert is_valid_uuid(data.get("brand_registration_id", ""))
    assert is_iso8601_timestamp(data.get("opened_at", ""))
    assert data["status"] in _members(TheftInvestigationStatus)
    assert data["outcome"] in _members(TheftOutcome)
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0


def assert_fee_remittance(data: dict) -> None:
    assert_common_record_fields(data)
    assert is_valid_uuid(data.get("owner_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["covered_order_ids"], list)
    assert data["status"] in _members(FeeRemittanceStatus)
    assert isinstance(data["applied_cents"], int) and data["applied_cents"] >= 0
    assert isinstance(data["shortfall_cents"], int) and data["shortfall_cents"] >= 0


# ─── Domain invariants ────────────────────────────────────────────────────────

def assert_estray_distribution_conserved(case: dict) -> None:
    """PRD §3.8: the gross amount equals the care cost plus the handling fee plus
    whichever of the claimant residual or the board forfeiture is in play."""
    variant = case["distribution_variant"]
    if variant == "NONE":
        return
    gross = (
        case["gross_proceeds_cents"]
        if variant == "FINAL"
        else case["estimated_gross_cents"]
    )
    assert gross is not None, "a written distribution must have a gross amount"
    tail = case["care_cost_cents"] + case["handling_fee_cents"]
    residual = case["claimant_residual_cents"] + case["board_forfeiture_cents"]
    # The conserved identity only holds when the care bucket did not swallow the
    # gross; when it did, the residual is floored at zero by the sixth step.
    if gross - case["care_cost_cents"] > 0:
        assert tail + residual == gross, (
            f"distribution must conserve the gross: {tail} + {residual} != {gross}"
        )


def assert_arrears_consistent(owner: dict) -> None:
    """PRD §3.9: the posted figure counts only `DELINQUENT` orders while the
    projected figure counts `ASSESSED` and `DELINQUENT` alike, so posted can
    never exceed projected, and only the posted figure gates work."""
    assert owner["posted_arrears_cents"] <= owner["projected_arrears_cents"], (
        "posted arrears may never exceed projected arrears: "
        f"{owner['posted_arrears_cents']} > {owner['projected_arrears_cents']}"
    )
    expected = "SUSPENDED" if owner["posted_arrears_cents"] >= 25000 else "GOOD"
    assert owner["standing"] == expected, (
        f"standing must read {expected} at posted arrears "
        f"{owner['posted_arrears_cents']}, got {owner['standing']}"
    )


def assert_no_version_field(data: dict) -> None:
    """Records the PRD declares leaner carry no `version` token."""
    assert "version" not in data, "this record type carries no version field"


def _parse_instant(value: str):
    """Parse an ISO 8601 UTC instant into a timezone-aware datetime."""
    from datetime import datetime, timezone

    assert isinstance(value, str) and value, (
        f"expected an ISO 8601 UTC instant, got {value!r}"
    )
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected: str, field: str = "instant") -> None:
    """Compare two ISO 8601 UTC instants for equality of the moment they name."""
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"{field}: expected the instant {expected}, got {actual}"
    )


def assert_three_fraction_digit_timestamp(value: str, field: str = "timestamp") -> None:
    """PRD §2.4 pins created_at and updated_at to three fractional digits."""
    import re

    assert isinstance(value, str) and re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", value
    ), f"{field} must be ISO 8601 UTC with three fractional digits, got {value!r}"
