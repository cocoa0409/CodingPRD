"""Entity assertions and domain invariant checkers.

Per PRD §2.4, ten resource types carry id + created_at + updated_at +
version; county links, candidates, feed sources, result deliveries, and
media invoices carry only id + created_at — the append-only assertions here
verify that updated_at and version are ABSENT, as the PRD requires.
"""
from decimal import Decimal, ROUND_HALF_UP

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .constants import (
    BASE_FEE_CENTS,
    TIER_MULTIPLIERS,
    RELIABILITY_SCORE_FLOOR,
    RELIABILITY_SCORE_CAP,
)


# ---------------------------------------------------------------------------
# Generic building blocks
# ---------------------------------------------------------------------------

def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def _assert_append_only_fields(data: dict, entity: str):
    """id + created_at only; updated_at and version must be absent (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


def round_half_up_6dp(value) -> float:
    """Round to 6 decimal places, half up — the PRD's ratio precision."""
    return float(
        Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    )


def round_half_up_cents(value) -> int:
    """Round a money product to whole cents, half up (PRD §2.8 / §3.8)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def expected_delivery_fee_cents(content_type: str, license_tier: str) -> int:
    """fee_cents a fresh VOTE_UPDATE or CALL delivery must carry (PRD §3.8).

    Per-delivery round-then-sum order: round_half_up(base * tier_multiplier).
    CALL_CREDIT is excluded — its fee is the exact negation of the CALL it
    compensates, which depends on the original row.
    """
    assert content_type in BASE_FEE_CENTS, (
        f"no base fee for content_type {content_type!r} (CALL_CREDIT is a negation)"
    )
    base = BASE_FEE_CENTS[content_type]
    multiplier = TIER_MULTIPLIERS[license_tier]
    return round_half_up_cents(base * multiplier)


# ---------------------------------------------------------------------------
# Per-entity shape assertions
# ---------------------------------------------------------------------------

def assert_election_event(data: dict):
    _assert_common_fields(data, "ElectionEvent")
    assert isinstance(data["event_name"], str) and data["event_name"]
    assert isinstance(data["event_date"], str) and len(data["event_date"]) == 10
    assert data["event_type"] in ["GENERAL", "PRIMARY", "SPECIAL", "RUNOFF"]
    assert isinstance(data["total_stringer_hour_budget"], int)
    assert data["total_stringer_hour_budget"] >= 1
    assert data["stringer_selection_mode"] in ["CAREER", "RECENT_FORM"]
    assert data["posture"] in [
        "SETUP", "CANDIDATES_LOCKED", "LIVE", "TABULATION", "CERTIFICATION", "ARCHIVED",
    ]


def assert_county(data: dict):
    _assert_common_fields(data, "County")
    assert isinstance(data["county_fips"], str) and len(data["county_fips"]) == 5
    assert isinstance(data["county_name"], str) and data["county_name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["expected_precincts"], int) and data["expected_precincts"] >= 1
    assert isinstance(data["expected_vote_total"], int) and data["expected_vote_total"] >= 1
    assert data.get("survey_turnout_estimate") is None or isinstance(
        data["survey_turnout_estimate"], int
    )
    assert data.get("historical_dem_share") is None or (
        0 <= data["historical_dem_share"] <= 1
    )
    assert isinstance(data["reported_precincts"], int) and data["reported_precincts"] >= 0
    assert data["status"] in ["PENDING", "REPORTING", "COMPLETE"]


def assert_contest(data: dict):
    _assert_common_fields(data, "Contest")
    assert isinstance(data["office_name"], str) and data["office_name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["contest_type"] in [
        "FEDERAL_EXEC", "FEDERAL_SENATE", "FEDERAL_HOUSE", "STATE", "BALLOT_MEASURE",
    ]
    assert isinstance(data["seats"], int) and data["seats"] >= 1
    assert data["tabulation_status"] in ["AWAITING", "REPORTING", "COMPLETE"]
    assert data["call_status"] in ["UNCALLED", "CALLED"]
    if data["call_status"] == "UNCALLED":
        assert data.get("called_candidate_id") is None
    else:
        assert is_valid_uuid(data.get("called_candidate_id", ""))
    assert_contest_rollup_invariants(data)


def assert_contest_rollup_invariants(data: dict):
    """Rollup invariants that must hold on any contest read (PRD §3.5)."""
    assert isinstance(data["reported_precincts"], int) and data["reported_precincts"] >= 0
    assert isinstance(data["total_votes"], int) and data["total_votes"] >= 0
    assert isinstance(data["margin_pct"], (int, float))
    assert 0.0 <= data["margin_pct"] <= 1.0
    assert isinstance(data["outstanding_estimate"], int) and data["outstanding_estimate"] >= 0


def assert_contest_county_link(data: dict):
    _assert_append_only_fields(data, "ContestCounty")
    assert is_valid_uuid(data.get("contest_id", ""))
    assert is_valid_uuid(data.get("county_id", ""))


def assert_candidate(data: dict):
    _assert_append_only_fields(data, "Candidate")
    assert isinstance(data["candidate_name"], str) and data["candidate_name"]
    assert data["party"] in ["DEM", "REP", "IND", "LIB", "GRN", "OTHER"]
    assert isinstance(data["is_incumbent"], bool)


def assert_feed_source(data: dict):
    _assert_append_only_fields(data, "FeedSource")
    assert isinstance(data["feed_name"], str) and data["feed_name"]
    assert isinstance(data["state_codes"], list) and len(data["state_codes"]) >= 1
    for code in data["state_codes"]:
        assert isinstance(code, str) and len(code) == 2
    assert data["priority_tier"] in ["PRIMARY", "SECONDARY"]


def assert_stringer(data: dict):
    _assert_common_fields(data, "Stringer")
    assert isinstance(data["stringer_name"], str) and data["stringer_name"]
    assert isinstance(data["home_state"], str) and len(data["home_state"]) == 2
    assert isinstance(data["no_show_count"], int) and data["no_show_count"] >= 0
    assert isinstance(data["accepted_report_count"], int) and data["accepted_report_count"] >= 0
    assert isinstance(data["voided_report_count"], int) and data["voided_report_count"] >= 0
    assert_stringer_score_bounds(data)


def assert_stringer_score_bounds(data: dict):
    """Both reliability variants are integers clamped to [0, 100] (PRD §3.3)."""
    for field in ("reliability_career", "reliability_recent_form"):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert RELIABILITY_SCORE_FLOOR <= data[field] <= RELIABILITY_SCORE_CAP, (
            f"{field} must be clamped to [0, 100], got {data[field]}"
        )


def assert_assignment(data: dict):
    _assert_common_fields(data, "StringerAssignment")
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("county_id", ""))
    assert data.get("stringer_id") is None or is_valid_uuid(data["stringer_id"])
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data["window_start"] < data["window_end"], (
        "window_start must be strictly before window_end"
    )
    assert data["status"] in ["SCHEDULED", "ACTIVE", "RELEASED", "NO_SHOW"]
    assert isinstance(data["auto_selected"], bool)


def assert_vote_report(data: dict):
    _assert_common_fields(data, "VoteReport")
    assert is_valid_uuid(data.get("contest_id", ""))
    assert is_valid_uuid(data.get("county_id", ""))
    assert data["source"] in ["STRINGER", "FEED"]
    if data["source"] == "STRINGER":
        assert is_valid_uuid(data.get("submitted_by_stringer_id", "")), (
            "STRINGER reports record submitted_by_stringer_id from X-User-ID"
        )
    else:
        assert data.get("submitted_by_stringer_id") is None, (
            "FEED reports leave submitted_by_stringer_id null"
        )
    assert isinstance(data["precincts_reporting"], int) and data["precincts_reporting"] >= 1
    assert isinstance(data["candidate_votes"], list) and len(data["candidate_votes"]) >= 1
    for entry in data["candidate_votes"]:
        assert is_valid_uuid(entry.get("candidate_id", ""))
        assert isinstance(entry["votes"], int) and entry["votes"] >= 0
    assert isinstance(data["reported_total"], int) and data["reported_total"] >= 0
    assert data["reported_total"] == sum(e["votes"] for e in data["candidate_votes"]), (
        "reported_total must equal the sum of candidate_votes"
    )
    assert isinstance(data["deviation_ratio"], (int, float)) and data["deviation_ratio"] >= 0
    assert data.get("swing_deviation") is None or data["swing_deviation"] >= 0
    assert data["status"] in ["RECEIVED", "FLAGGED", "ACCEPTED", "REJECTED", "VOIDED"]
    if data["status"] == "ACCEPTED":
        assert is_iso8601_timestamp(data.get("accepted_at", "")), (
            "accepted_at stamps the logical clock at ACCEPT"
        )
    else:
        assert data.get("accepted_at") is None, (
            "accepted_at is null until accepted and resets to null on VOID"
        )


def assert_race_call(data: dict):
    _assert_common_fields(data, "RaceCall")
    assert is_valid_uuid(data.get("contest_id", ""))
    assert is_valid_uuid(data.get("winner_candidate_id", ""))
    assert isinstance(data["proposed_by"], str) and data["proposed_by"]
    assert data["status"] in ["PROPOSED", "PUBLISHED", "RETRACTED"]
    if data["status"] == "PUBLISHED":
        assert isinstance(data["published_by"], str) and data["published_by"]
        assert is_iso8601_timestamp(data.get("published_at", ""))
        assert data.get("retract_reason") is None
    elif data["status"] == "RETRACTED":
        assert isinstance(data.get("retract_reason"), str) and data["retract_reason"]
    else:  # PROPOSED
        assert data.get("published_by") is None
        assert data.get("published_at") is None
        assert data.get("retract_reason") is None


def assert_recount_case(data: dict):
    _assert_common_fields(data, "RecountCase")
    assert is_valid_uuid(data.get("contest_id", ""))
    assert data["status"] in [
        "FILED", "ACTIVE", "DISMISSED", "RESOLVED_CONFIRMED", "RESOLVED_OVERTURNED",
    ]
    assert isinstance(data["filed_margin_pct"], (int, float))
    assert 0.0 <= data["filed_margin_pct"] <= 1.0


def assert_coverage_decision(data: dict):
    _assert_common_fields(data, "CoverageDecision")
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("contest_id", ""))
    assert isinstance(data["allocated_stringer_hours"], int)
    assert data["allocated_stringer_hours"] >= 1
    assert data["coverage_start"] <= data["coverage_end"], (
        "closed coverage interval: coverage_start must not fall after coverage_end"
    )
    assert data["status"] in ["PROPOSED", "APPROVED", "DECLINED", "FUNDED"]


def assert_media_customer(data: dict):
    _assert_common_fields(data, "MediaCustomer")
    assert isinstance(data["customer_name"], str) and data["customer_name"]
    assert data["license_tier"] in ["BASIC", "STANDARD", "PREMIUM"]
    assert isinstance(data["licensed_states"], list) and len(data["licensed_states"]) >= 1
    for code in data["licensed_states"]:
        assert isinstance(code, str) and len(code) == 2


def assert_result_delivery(data: dict):
    _assert_append_only_fields(data, "ResultDelivery")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("contest_id", ""))
    assert data["content_type"] in ["VOTE_UPDATE", "CALL", "CALL_CREDIT"]
    assert isinstance(data["fee_cents"], int)
    assert data["status"] in ["SENT", "STALE"]
    assert is_iso8601_timestamp(data.get("delivered_at", ""))
    if data["content_type"] == "CALL_CREDIT":
        assert data["fee_cents"] <= 0, "CALL_CREDIT carries the negated CALL fee"
        assert data["status"] == "SENT", "CALL_CREDIT deliveries are created SENT"
    if data["status"] == "STALE":
        assert data["content_type"] == "CALL", "only CALL deliveries ever become STALE"


def assert_media_invoice(data: dict):
    _assert_append_only_fields(data, "MediaInvoice")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["period"], str) and len(data["period"]) == 7
    assert isinstance(data["delivery_count"], int) and data["delivery_count"] >= 0
    assert isinstance(data["total_fee_cents"], int)


def assert_tabulation_board(data: dict):
    """Full inline shape of the tabulation board read (PRD §3.5)."""
    assert is_valid_uuid(data.get("contest_id", ""))
    assert data["tabulation_status"] in ["AWAITING", "REPORTING", "COMPLETE"]
    assert data["call_status"] in ["UNCALLED", "CALLED"]
    assert isinstance(data["reported_precincts"], int) and data["reported_precincts"] >= 0
    assert isinstance(data["expected_precincts_total"], int)
    assert data["expected_precincts_total"] >= 1
    assert isinstance(data["candidate_totals"], list)
    assert isinstance(data["total_votes"], int) and data["total_votes"] >= 0
    assert isinstance(data["margin_pct"], (int, float))
    assert 0.0 <= data["margin_pct"] <= 1.0
    assert isinstance(data["outstanding_estimate"], int) and data["outstanding_estimate"] >= 0
    # PRD §3.5 pins only "the per-county `outstanding_detail`" — the entry key
    # names for the two estimate variants are never spelled out, so no per-
    # entry key naming is asserted here (a faithful read may name them either
    # way). The per-county max() composition itself is verified through the
    # pinned contest-level `outstanding_estimate` in the divergence test.
    assert isinstance(data["outstanding_detail"], list)
    for entry in data["outstanding_detail"]:
        assert is_valid_uuid(entry.get("county_id", ""))
