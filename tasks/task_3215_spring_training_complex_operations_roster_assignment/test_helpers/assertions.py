"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict):
    """Every entity carries a server-minted UUID id plus timestamps."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"


def assert_complex(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["host_city"], str) and data["host_city"]
    assert data["season_split_track"] in ("SHARED", "DEDICATED")
    assert data["field_maintenance_status"] in ("OPEN", "HALF_FIELD", "CLOSED")
    assert data["facility_posture"] in ("NORMAL", "FIELD_RESTRICTED", "CLOSED")
    assert isinstance(data["facility_capacity_units"], int)
    assert isinstance(data["posted_occupancy_units"], int)
    assert isinstance(data["maintenance_block_units"], int)
    assert isinstance(data["posture_sweep_index"], int)


def assert_player(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["idp_number"], str) and data["idp_number"]
    assert data["position_code"] in ("P", "C", "INF", "OF", "DH")
    assert data["acquisition_channel"] in (
        "DRAFT_PICK", "NRI_ASSIGNMENT", "FREE_AGENT",
        "INTERNATIONAL_SIGNING", "TRADE",
    )
    assert data["clearance_status"] in (
        "PENDING", "MEDICALS_COMPLETE", "CAMP_CLEARED", "TURNED_AWAY",
    )


def assert_roster_record(data: dict):
    assert_common_fields(data)
    assert data["roster_decision_status"] in (
        "DECISION_PENDING", "DECISION_FINALIZED", "DECISION_VOIDED",
    )
    assert data["option_eligibility"] in ("OPTION_AVAILABLE", "NO_OPTION_REMAINING")
    assert isinstance(data["option_decisions_used"], int)
    assert isinstance(data["waivers_required"], bool)
    assert isinstance(data["decision_sequence"], int)


def assert_host_community_record(data: dict):
    assert_common_fields(data)
    assert data["ticketing_status"] in ("NOT_OPEN", "ON_SALE", "SOLD_OUT", "SUSPENDED")
    assert isinstance(data["tickets_sold"], int)
    assert isinstance(data["community_ledger_cents"], int)
    assert isinstance(data["ledger_gap_cents"], int)


def assert_ledger_identity(data: dict):
    """The ledger projection's conserved identity: gap = ledger - recognition."""
    assert data["community_ledger_cents"] == (
        data["ticketing_revenue_cents"] + data["sponsorship_revenue_cents"]
    ), "community_ledger_cents must equal ticketing_revenue_cents + sponsorship_revenue_cents"
    assert data["ledger_gap_cents"] == (
        data["community_ledger_cents"] - data["recognition_funded_cents"]
    ), "ledger_gap_cents must equal community_ledger_cents - recognition_funded_cents"


def assert_sponsorship(data: dict):
    assert_common_fields(data)
    assert data["sponsor_tier"] in ("LOCAL", "REGIONAL", "NATIONAL")
    assert data["reconciliation_status"] in (
        "UNSETTLED", "SETTLED", "RECOGNIZED", "SETTLEMENT_VOIDED",
    )
    assert data["received_amount_cents"] >= 0
    assert isinstance(data["fulfillment_completed"], bool)


def assert_workout_group(data: dict):
    assert_common_fields(data)
    assert data["roster_bucket"] in ("MAJOR", "MINOR")
    assert data["facility_kind"] in ("FIELD", "CLUBHOUSE", "TRAINING_ROOM")
    assert data["group_status"] in ("FORMING", "PUBLISHED", "DISBANDED")
    assert isinstance(data["assigned_units"], int)
    assert isinstance(data["capacity_units"], int)


def assert_group_assignment(data: dict):
    assert_common_fields(data)
    assert data["roster_bucket"] in ("MAJOR", "MINOR")
    assert data["assignment_kind"] in ("ACTIVE_WORKOUT", "REHAB")
    assert data["assignment_status"] in ("PROVISIONAL", "ACTIVE", "WITHDRAWN")


def assert_throw_program(data: dict):
    assert_common_fields(data)
    assert data["program_phase"] in (
        "PHASE_1", "PHASE_2", "PHASE_3", "PHASE_4", "PHASE_LIVE", "SHUTDOWN",
    )
    assert data["requirement_status"] in ("NOT_REQUIRED", "MET", "UNMET")
    assert isinstance(data["cumulative_throws"], int)
    assert isinstance(data["cumulative_bullpen_sessions"], int)


def assert_program_profile(data: dict):
    assert_common_fields(data)
    assert data["eligibility_status"] in ("MEDICALS_PENDING", "CAMP_ELIGIBLE", "TURNED_AWAY")
    assert data["rehab_program_phase"] in (
        "PHASE_1", "PHASE_2", "PHASE_3", "PHASE_4", "PHASE_LIVE", "SHUTDOWN",
    )


def assert_invitation(data: dict):
    assert_common_fields(data)
    assert data["invitation_status"] in (
        "ISSUED", "ACKNOWLEDGED", "ARRIVED", "VISA_BLOCKED", "NO_SHOW",
    )
    assert data["invitation_letter_status"] in ("LETTER_PENDING", "LETTER_SENT")
    assert data["travel_arrangement_status"] in ("NOT_ARRANGED", "ARRANGED", "CANCELLED")
    assert data["arrival_band"] in ("EARLY", "MET_CURRENT", "MET_FINAL", "MISSED_WINDOW")


def assert_travel_arrangement(data: dict):
    assert_common_fields(data)
    assert data["mode"] in ("AIR", "BUS", "AUTO")
    assert data["status"] in ("PLANNED", "CONFIRMED", "CANCELLED")
    assert data["reimbursement_status"] in ("NOT_LIABLE", "LIABLE", "VOIDED")
    assert data["funding_source"] in ("AGREEMENT_FUND", "REIMBURSEMENT", "NONE")


def assert_physical(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "PERFORMED", "VOIDED")


def assert_game(data: dict):
    assert_common_fields(data)
    assert data["home_away"] in ("HOME", "AWAY")
    assert data["game_schedule_status"] in ("DRAFT", "PUBLISHED", "PLAYED", "CANCELLED")
    assert data["gameday_status"] in ("GAMEDAY", "NOT_GAMEDAY")


def assert_participation(data: dict):
    assert_common_fields(data)
    assert data["squad_side"] in ("HOME_SQUAD", "AWAY_SQUAD")
    assert data["participation_status"] in (
        "SCHEDULED", "CONFIRMED", "WITHDRAWN", "LOCKED",
    )


def assert_minor_league_assignment(data: dict):
    assert_common_fields(data)
    assert data["assigned_level"] in ("AAA", "AA")
    assert data["assignment_status"] in ("PENDING", "SETTLED", "BREAKOUT_VOIDED")
    assert isinstance(data["travel_day_count"], int)


# --- Domain invariant checkers ---

def assert_complex_invariants(data: dict):
    """Posture aggregates stay within their declared spans."""
    assert data["posted_occupancy_units"] >= 0
    assert data["reserved_major_units"] >= 0
    assert data["reserved_minor_units"] >= 0
    assert data["maintenance_block_units"] >= 0
    assert data["posture_sweep_index"] >= 0


def assert_ledger_conserved(before: dict, after: dict, field: str):
    """A compensating pair must restore `field` to its pre-action value."""
    assert after[field] == before[field], (
        f"Expected {field} to return to {before[field]} after the compensating "
        f"action, got {after[field]}"
    )