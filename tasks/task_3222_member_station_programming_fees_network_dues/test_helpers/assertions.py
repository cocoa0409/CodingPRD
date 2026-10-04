"""Entity assertions and domain invariant checkers (PRD §2.4, §2.10, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .constants import (
    MEMBERSHIP_CLASS_VOTE_WEIGHT,
    operations_score as derive_operations_score,
    membership_class_for,
)


def _assert_common(data: dict, *, has_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if has_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_member_station(data: dict):
    _assert_common(data)
    assert data["eligibility_status"] in [
        "APPLICANT", "UNDER_REVIEW", "DEFICIENT", "REMEDIATION_SUBMITTED",
        "ELIGIBLE", "PROBATION", "SUSPENDED", "WITHDRAWN",
    ], f"unexpected eligibility_status {data['eligibility_status']}"
    assert data["membership_class"] in ["CLASS_A", "CLASS_B", "CLASS_C", "CLASS_D"]
    assert data["board_seat_region"] in [
        "REGION_NORTHEAST", "REGION_SOUTH", "REGION_MIDWEST", "REGION_WEST",
    ]
    assert isinstance(data["operations_score"], (int, float))
    for field in ("dues_arrears_cents", "contribution_credit_cents", "applied_relief_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer cent figure"
    assert isinstance(data["dues_vote_eligible"], bool)


def assert_station_derived_fields_match_inputs(data: dict):
    """PRD §3.1: operations_score and membership_class follow the pinned ladder."""
    expected_score = derive_operations_score(
        data["coverage_population"],
        data["full_time_staff_count"],
        data["newsroom_staff_count"],
    )
    assert data["operations_score"] == expected_score, (
        f"operations_score should be {expected_score}, got {data['operations_score']}"
    )
    expected_class = membership_class_for(expected_score, data["dma_households"])
    assert data["membership_class"] == expected_class, (
        f"membership_class should be {expected_class}, got {data['membership_class']}"
    )


def assert_schedule(data: dict):
    """PRD §2.4: "ProgrammingFeeSchedule has no `updated_at` and no `version`"."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "ProgrammingFeeSchedule carries no version field"
    assert "updated_at" not in data, "ProgrammingFeeSchedule carries no updated_at field"
    assert data["rounding_mode"] == "ROUND_PER_COMPONENT_THEN_SUM"


def assert_audience_report(data: dict):
    """PRD §3.7: a filing is immutable, so it carries no version and no updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "AudienceReport carries no version field"
    assert "updated_at" not in data, "AudienceReport carries no updated_at field"


def assert_agreement(data: dict):
    _assert_common(data)
    assert data["agreement_status"] in [
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "CLEARED", "CARRIED", "ACTIVE",
        "EMBARGOED", "EXPIRED", "TERMINATED",
    ]
    assert data["obligation_type"] in ["MANDATORY", "OPTIONAL", "DISCRETIONARY"]


def assert_window(data: dict):
    _assert_common(data)
    assert data["clearance_status"] in [
        "DRAFT", "PENDING_CLEARANCE", "CLEARED", "REJECTED", "SCHEDULED",
        "BROADCAST", "MISSED", "VIOLATED",
    ]
    assert isinstance(data["is_cleared"], bool)
    assert isinstance(data["carriage_exception_liability_cents"], int)
    if data["clearance_status"] in ("DRAFT", "PENDING_CLEARANCE"):
        assert data["is_cleared"] is False, "an uncleared window must report is_cleared false"


def assert_feed(data: dict):
    _assert_common(data)
    assert data["feed_status"] in [
        "PLANNED", "ONLINE", "CROWDED", "MAINTENANCE", "OFFLINE", "SUSPENDED",
    ]
    assert data["feed_type"] in ["SATELLITE", "DIGITAL", "HYBRID"]
    assert isinstance(data["crowded"], bool)
    assert 0 <= data["reserved_capacity_units"] <= data["total_capacity_units"], (
        "reserved capacity must sit inside the feed's total"
    )


def assert_slot(data: dict):
    _assert_common(data)
    assert data["slot_status"] in [
        "RESERVED", "SCHEDULED", "PREEMPTED", "CANCELLED", "RELEASED", "AIRED",
    ]
    assert 1 <= data["priority_rank"] <= 5


def assert_underwriting(data: dict):
    _assert_common(data)
    assert data["agreement_status"] in [
        "SUBMITTED", "COMPLIANCE_REVIEW", "APPROVED", "SCHEDULED", "AIRING",
        "AIRING_COMPLETE", "REJECTED", "NO_AIRED",
    ]
    assert isinstance(data["disclosure_test_passed"], bool)


def assert_contribution(data: dict):
    _assert_common(data)
    assert data["contribution_status"] in [
        "DRAFT", "SUBMITTED", "SHORTLISTED", "LICENSED", "USED", "WITHDRAWN", "REJECTED",
    ]
    assert 0 <= data["compensation_credit_cents"] <= 250000


def assert_drive(data: dict):
    _assert_common(data)
    assert data["drive_status"] in [
        "PLANNED", "ACTIVE", "CLOSED", "REPORTED", "SETTLED", "CANCELLED",
    ]
    if data["pledged_cents"] == 0:
        assert data["collection_ratio_bps"] == 0, "ratio is zero when nothing was pledged"
    else:
        assert 0 <= data["collection_ratio_bps"] <= 10000


def assert_program(data: dict):
    _assert_common(data)
    assert data["production_status"] in [
        "DEVELOPMENT", "PRODUCTION", "SCHEDULED", "RUNNING", "PUBLISHED",
        "RESCHEDULED", "RETIRED",
    ]
    assert data["publication_cycle"] >= 0
    assert data["licensed_contribution_count"] >= 0


def assert_proposal(data: dict):
    _assert_common(data)
    assert data["proposal_status"] in [
        "DRAFT", "OPEN", "PASSED", "ENACTED", "REJECTED", "TABLED", "ENACTMENT_CLOSED",
    ]
    assert data["yes_votes"] >= 0 and data["no_votes"] >= 0 and data["votes_cast_count"] >= 0


def assert_station_vote(data: dict):
    _assert_common(data)
    assert data["vote_status"] in ["RECORDED", "SUPERSEDED", "INVALIDATED"]
    assert data["vote_choice"] in ["YES", "NO"]


def assert_vote_weight_matches_choice(data: dict):
    """PRD §3.9: a live row's recorded_weight follows its choice and the station's class."""
    if data["vote_status"] != "RECORDED":
        return
    base = MEMBERSHIP_CLASS_VOTE_WEIGHT.get(data.get("membership_class", "CLASS_A"))
    if base is None:
        return
    if data["vote_choice"] == "YES":
        assert data["recorded_weight"] == base, (
            f"a YES should record {base}, got {data['recorded_weight']}"
        )


def assert_election(data: dict):
    _assert_common(data)
    assert data["election_status"] in [
        "OPEN", "CLOSED", "CERTIFIED", "CONTESTED", "REOPENED", "FINALIZED",
    ]
    assert data["seats_available"] >= 1


def assert_candidate(data: dict):
    _assert_common(data)
    assert data["candidate_status"] in [
        "FILED", "QUALIFIED", "ELECTED", "DEFEATED", "LAPSED", "WITHDRAWN",
    ]


def assert_seat(data: dict):
    _assert_common(data)
    assert data["seat_status"] in ["VACANT", "CONTESTED", "HOLDOVER", "FILLED", "RECALLED"]
    if data["seat_status"] == "VACANT":
        assert data.get("station_id") in (None, ""), "a vacant seat holds no station"
    assert data["carried_credit_cents"] >= 0


def assert_assessment(data: dict):
    _assert_common(data)
    assert data["assessment_status"] in ["INITIAL", "FINALIZED", "SUPERSEDED"]
    assert isinstance(data["provisional_fee_cents"], int)
    assert isinstance(data["final_fee_cents"], int)


# --- domain invariant checkers ----------------------------------------------

def assert_vote_tally_matches_live_rows(proposal: dict, live_rows: list):
    """PRD §3.9: only RECORDED rows contribute; votes_cast_count is a station headcount."""
    recorded = [r for r in live_rows if r["vote_status"] == "RECORDED"]
    yes = sum(r["recorded_weight"] for r in recorded if r["vote_choice"] == "YES")
    no = sum(r["recorded_weight"] for r in recorded if r["vote_choice"] == "NO")
    distinct = len({r["station_id"] for r in recorded})
    assert proposal["yes_votes"] == yes, f"yes_votes should be {yes}, got {proposal['yes_votes']}"
    assert proposal["no_votes"] == no, f"no_votes should be {no}, got {proposal['no_votes']}"
    assert proposal["votes_cast_count"] == distinct, (
        f"votes_cast_count should be {distinct}, got {proposal['votes_cast_count']}"
    )


def assert_feed_congestion_flag(feed: dict):
    """PRD §3.4: crowded is true exactly when the reserved ratio reaches the threshold.

    PRD §2.5 makes the ratio an integer basis-point figure (10000 == one whole
    unit), so the comparison is made in basis points on both sides.
    """
    threshold_bps = feed.get("max_reserved_capacity_ratio")
    if threshold_bps is None:
        return
    ratio_bps = (feed["reserved_capacity_units"] * 10000) // feed["total_capacity_units"]
    assert feed["crowded"] == (ratio_bps >= threshold_bps), (
        f"crowded should be {ratio_bps >= threshold_bps} at ratio {ratio_bps} bps "
        f"against {threshold_bps} bps"
    )


def assert_pool_allocation_sums_to_pot(assessments: list, total_pot_cents: int):
    """PRD §3.9: the allocated shares sum exactly to the pool."""
    allocated = sum(a["allocated_dues_cents"] for a in assessments)
    assert allocated == total_pot_cents, (
        f"allocated {allocated} must equal the pool {total_pot_cents}"
    )