"""Entity assertions and the money invariants the PRD declares."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant


def assert_instant_equals(actual, expected, label="instant"):
    """Compare two ISO 8601 UTC instants ignoring fractional-second width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Expected {label} {expected}, got {actual}"
    )


def assert_common_fields(data: dict, label: str = "resource"):
    """Every resource kind carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 instant: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 instant: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_league(data: dict):
    assert_common_fields(data, "League")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    for field in (
        "season_start_at",
        "season_end_at",
        "roster_lock_at",
        "transfer_window_open_at",
        "transfer_window_close_at",
    ):
        assert is_iso8601_timestamp(data[field]), f"League.{field} must be an instant"
    for field in (
        "minimum_salary_cents",
        "min_roster_size",
        "max_roster_size",
        "offer_response_window_hours",
        "max_negotiation_rounds",
        "player_association_levy_bp",
        "association_min_prize_split_bp",
        "association_max_streaming_hours_per_week",
        "minor_max_weekly_minutes",
        "adult_max_weekly_minutes",
        "education_reserved_minutes",
        "minor_age_threshold_years",
        "free_agency_cooldown_days",
    ):
        assert isinstance(data[field], int), f"League.{field} must be an integer"
    assert isinstance(data["tryout_required_before_offer"], bool)
    assert isinstance(data["roster_lock_active"], bool)


def assert_organization(data: dict):
    assert_common_fields(data, "Organization")
    assert is_valid_uuid(data["league_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["tax_jurisdiction_code"], str)
    for field in (
        "annual_salary_budget_cents",
        "org_prize_share_bp",
        "committed_salary_cents",
        "uncommitted_salary_cents",
        "active_roster_count",
        "prize_payable_cents",
        "wellness_flag_count",
    ):
        assert isinstance(data[field], int), f"Organization.{field} must be an integer"
    assert_salary_ledger_balances(data)


def assert_salary_ledger_balances(data: dict):
    """annual_salary_budget_cents == committed_salary_cents + uncommitted_salary_cents."""
    assert (
        data["annual_salary_budget_cents"]
        == data["committed_salary_cents"] + data["uncommitted_salary_cents"]
    ), (
        "Salary ledger does not balance: budget "
        f"{data['annual_salary_budget_cents']} != committed "
        f"{data['committed_salary_cents']} + uncommitted "
        f"{data['uncommitted_salary_cents']}"
    )


def assert_prize_ledger_balances(data: dict):
    """gross == association_levy + org_share + allocated + unallocated."""
    total = (
        data["association_levy_cents"]
        + data["org_share_cents"]
        + data["allocated_cents"]
        + data["unallocated_cents"]
    )
    assert data["gross_prize_cents"] == total, (
        "Prize ledger does not balance: gross "
        f"{data['gross_prize_cents']} != levy {data['association_levy_cents']} + "
        f"org {data['org_share_cents']} + allocated {data['allocated_cents']} + "
        f"unallocated {data['unallocated_cents']}"
    )


def assert_player(data: dict):
    assert_common_fields(data, "Player")
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 120
    assert isinstance(data["birth_date"], str) and len(data["birth_date"]) == 10
    assert isinstance(data["region_code"], str) and data["region_code"].isupper()
    assert isinstance(data["association_member"], bool)
    assert data["player_status"] in (
        "PROSPECT",
        "TRYOUT_INVITED",
        "TRYOUT_COMPLETED",
        "SIGNED",
        "FREE_AGENT",
    )
    assert isinstance(data["age_years"], int)
    assert isinstance(data["is_minor"], bool)
    assert data["guardian_consent_status"] in ("NOT_REQUIRED", "REQUIRED", "GRANTED")
    assert data["education_enrollment_status"] in (
        "NOT_ENROLLED",
        "ENROLLED_PART_TIME",
        "ENROLLED_FULL_TIME",
    )


def assert_contract_offer(data: dict):
    assert_common_fields(data, "ContractOffer")
    assert is_valid_uuid(data["organization_id"])
    assert is_valid_uuid(data["player_id"])
    assert data["offer_status"] in (
        "SENT",
        "COUNTERED",
        "ACCEPTED",
        "DECLINED",
        "EXPIRED",
        "SUPERSEDED",
    )
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    for field in (
        "base_salary_cents",
        "term_months",
        "prize_split_player_pct_bp",
        "streaming_hours_per_week",
        "signing_bonus_cents",
        "buyout_multiplier_bp",
    ):
        assert isinstance(data[field], int), f"ContractOffer.{field} must be an integer"
    assert is_iso8601_timestamp(data["sent_at"])
    assert is_iso8601_timestamp(data["expires_at"])


def assert_player_contract(data: dict):
    assert_common_fields(data, "PlayerContract")
    assert is_valid_uuid(data["offer_id"])
    assert is_valid_uuid(data["player_id"])
    assert is_valid_uuid(data["organization_id"])
    assert data["contract_status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert data["obligation_status"] in ("COMPLIANT", "WARNED", "BREACH")
    for field in (
        "base_salary_cents",
        "term_months",
        "signing_bonus_cents",
        "prize_split_player_pct_bp",
        "streaming_hours_per_week",
        "buyout_multiplier_bp",
        "provisional_cap_charge_cents",
        "final_cap_charge_cents",
        "season_practice_minutes",
        "burnout_score",
    ):
        assert isinstance(data[field], int), f"PlayerContract.{field} must be an integer"
    assert is_iso8601_timestamp(data["effective_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert 0 <= data["burnout_score"] <= 100


def assert_team_house(data: dict):
    assert_common_fields(data, "TeamHouse")
    assert is_valid_uuid(data["organization_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["timezone"], str)
    assert isinstance(data["turnaround_buffer_minutes"], int)
    assert 0 <= data["turnaround_buffer_minutes"] <= 720
    assert isinstance(data["concurrent_seat_capacity"], int)
    assert data["concurrent_seat_capacity"] >= 1


def assert_practice_block(data: dict):
    assert_common_fields(data, "PracticeBlock")
    assert is_valid_uuid(data["organization_id"])
    assert is_valid_uuid(data["team_house_id"])
    assert data["block_type"] in ("SCRIM", "REVIEW", "INDIVIDUAL", "TRYOUT")
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0
    assert isinstance(data["participant_player_ids"], list)
    assert data["block_status"] in ("SCHEDULED", "HELD", "CANCELLED")
    if data.get("cancel_reason") is not None:
        assert data["cancel_reason"] in (
            "COACH_CANCELLED",
            "WELLNESS_HOLD",
            "CONTRACT_SUSPENDED",
        )


def assert_sponsorship_deal(data: dict):
    assert_common_fields(data, "SponsorshipDeal")
    assert is_valid_uuid(data["organization_id"])
    assert isinstance(data["sponsor_name"], str)
    assert data["exclusivity_category"] in (
        "ENERGY_DRINK",
        "PERIPHERALS",
        "APPAREL",
        "BETTING",
        "CRYPTO",
    )
    assert isinstance(data["total_fee_cents"], int)
    assert isinstance(data["deliverable_count_required"], int)
    assert data["deal_status"] in ("DRAFT", "ACTIVE", "FULFILLED")
    assert isinstance(data["assigned_count"], int)
    assert isinstance(data["approved_count"], int)
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])


def assert_deliverable_assignment(data: dict):
    assert_common_fields(data, "DeliverableAssignment")
    assert is_valid_uuid(data["sponsorship_deal_id"])
    assert is_valid_uuid(data["contract_id"])
    assert data["deliverable_type"] in (
        "SOCIAL_POST",
        "STREAM_SEGMENT",
        "APPEARANCE",
        "VOD_FEATURE",
    )
    assert is_iso8601_timestamp(data["due_at"])
    assert isinstance(data["fee_share_cents"], int)
    assert data["assignment_status"] in (
        "ASSIGNED",
        "SUBMITTED",
        "APPROVED",
        "REJECTED",
        "VOIDED",
    )
    assert isinstance(data["rejection_count"], int)


def assert_prize_distribution(data: dict):
    assert_common_fields(data, "PrizeDistribution")
    assert is_valid_uuid(data["organization_id"])
    assert is_valid_uuid(data["league_id"])
    assert isinstance(data["tournament_name"], str)
    assert isinstance(data["placement"], int)
    assert data["distribution_status"] in ("DRAFT", "CALCULATED", "APPROVED", "VOIDED")
    for field in (
        "gross_prize_cents",
        "association_levy_cents",
        "org_share_cents",
        "allocated_cents",
        "unallocated_cents",
        "withholding_total_cents",
        "escrow_total_cents",
    ):
        assert isinstance(data[field], int), f"PrizeDistribution.{field} must be an integer"
    assert is_iso8601_timestamp(data["tournament_end_at"])
    assert_prize_ledger_balances(data)


def assert_prize_allocation(data: dict):
    assert_common_fields(data, "PrizeAllocation")
    assert is_valid_uuid(data["prize_distribution_id"])
    assert is_valid_uuid(data["contract_id"])
    for field in (
        "weight_bp",
        "gross_share_cents",
        "withholding_rate_bp",
        "withholding_cents",
        "escrow_holdback_cents",
        "net_cents",
    ):
        assert isinstance(data[field], int), f"PrizeAllocation.{field} must be an integer"
    assert data["allocation_status"] in ("CALCULATED", "APPROVED", "VOIDED")


def assert_roster_move(data: dict):
    assert_common_fields(data, "RosterMove")
    assert is_valid_uuid(data["organization_id"])
    assert is_valid_uuid(data["player_id"])
    assert data["move_type"] in ("SIGN", "RELEASE", "TRANSFER_OUT")
    assert data["move_status"] in ("PENDING", "APPROVED", "REJECTED", "EXECUTED", "REVERSED")
    for field in (
        "gross_transfer_fee_cents",
        "buyout_credit_cents",
        "commission_tier_bp",
        "agent_commission_cents",
        "net_to_org_cents",
        "released_cap_cents",
    ):
        assert isinstance(data[field], int), f"RosterMove.{field} must be an integer"


def assert_success_envelope_meta(body: dict):
    """The envelope every success response shares."""
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(meta["api_request_timestamp"])
    assert body["response_type"] in ("object", "array")


def assert_error_envelope(body: dict, expected_error_id: str):
    """The error envelope: response_type 'error' and a data payload of two fields."""
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(meta["api_request_timestamp"])
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == expected_error_id
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
