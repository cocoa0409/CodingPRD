"""Difficulty tests: boundary_precision_check — inclusive numeric/temporal
thresholds exercised at X-1, X, X+1 (insurance points and 30-day wait, and
the 72-hour appeal window).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_agreement,
    add_verified_result,
    add_verified_results,
    create_funding_agreement,
    enroll_insurance,
    file_appeal,
    make_athlete_headers,
    parse_iso,
    set_logical_clock,
    setup_certified_body,
    setup_eligible_athlete,
    setup_nominated_roster,
    validate_error,
)


def test_insurance_points_and_wait_boundaries(api, committee_admin_headers):
    """PRD funding section: "Health insurance enrollment — `insurance_status`
    from `INS_NONE` or `INS_LAPSED` to `INS_ENROLLED`, by a `CommitteeAdmin` —
    is gated on two inclusive conditions evaluated as of the current logical
    clock: the agreement's operative points under its bound `points_method`
    must be at least 60, and the clock must be at or after `activated_at` plus
    30 days."
    PRD funding section: "Failing either condition rejects the enrollment with
    `ERR_INSURANCE_NOT_ELIGIBLE`; success stamps `insurance_enrolled_at` with
    the clock."
    PRD results/points section: "`TIER_A` at 100 points or more, `TIER_B` at
    60 or more, `TIER_C` at 30 or more, and `NONE` below 30 — a value exactly
    on a threshold qualifies for that tier."

    Design: Difficulty/boundary_precision_check/insurance_points_and_wait_boundaries
    """
    body = setup_certified_body(
        api=api,
        name="US Skate",
        sport_code="SKAT",
        funding_budget_cents=3_600_000,
        sport_science_pool_hours=100,
    )
    athlete_x = setup_eligible_athlete(
        body["id"], api=api, full_name="X Exact", date_of_birth="1998-01-01"
    )
    # 40 * 1.5 = 60.00 exactly (the inclusive points boundary).
    add_verified_result(
        athlete_x["id"], event_grade="A", placing=1,
        event_date="2026-08-01T00:00:00Z", event_name="August Cup", api=api,
    )
    athlete_y = setup_eligible_athlete(
        body["id"], api=api, full_name="Y Short", date_of_birth="1998-02-02"
    )
    # 26 * 1.5 + 20 * 1.0 = 39.00 + 20.00 = 59.00 (one point below).
    add_verified_results(
        athlete_y["id"],
        [
            {"event_name": "August Cup", "event_grade": "A", "placing": 3,
             "event_date": "2026-08-01T00:00:00Z"},
            {"event_name": "August Open", "event_grade": "C", "placing": 4,
             "event_date": "2026-08-01T00:00:00Z"},
        ],
        api=api,
    )

    set_logical_clock("2026-10-01T00:00:00Z", api=api)
    agreement_x = create_funding_agreement(
        athlete_x["id"],
        api=api,
        coverage_start="2026-10-01T00:00:00Z",
        coverage_end="2027-04-01T00:00:00Z",
        points_method="TRAILING_365",
    )
    assert agreement_x["trailing_points"] == pytest.approx(60.0, abs=1e-9)
    assert agreement_x["tier"] == "TIER_B", (
        "exactly 60.00 points qualifies for TIER_B (inclusive threshold)"
    )
    activate_agreement(agreement_x["id"], api=api)

    agreement_y = create_funding_agreement(
        athlete_y["id"],
        api=api,
        coverage_start="2026-10-01T00:00:00Z",
        coverage_end="2027-04-01T00:00:00Z",
        points_method="TRAILING_365",
    )
    assert agreement_y["trailing_points"] == pytest.approx(59.0, abs=1e-9)
    assert agreement_y["tier"] == "TIER_C"
    activate_agreement(agreement_y["id"], api=api)

    # 29 days of the 30-day wait: enrollment rejected on the time prong.
    set_logical_clock("2026-10-30T00:00:00Z", api=api)
    resp = api.transition_funding_agreement(
        agreement_x["id"], {"to_state": "INS_ENROLLED"}, committee_admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_INSURANCE_NOT_ELIGIBLE)

    # Exactly activated_at + 30 days: the wait boundary is inclusive.
    set_logical_clock("2026-10-31T00:00:00Z", api=api)
    enrolled_x = enroll_insurance(agreement_x["id"], api=api)
    assert enrolled_x["insurance_status"] == "INS_ENROLLED"

    # Y has waited the full 30 days but sits at 59.00 < 60: rejected on the
    # points prong.
    resp = api.transition_funding_agreement(
        agreement_y["id"], {"to_state": "INS_ENROLLED"}, committee_admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_INSURANCE_NOT_ELIGIBLE)


def test_appeal_window_boundary_72h(api, committee_admin_headers):
    """PRD selection section: "The filing instant, `filed_at`, must fall at or
    before the roster's `nominated_at` plus 72 hours — the exact boundary is
    inclusive — with later filings rejected as `ERR_APPEAL_WINDOW_EXPIRED`;
    because `nominated_at` never refreshes, a selector re-run does not reopen
    an expired window."
    PRD selection section: "the filer is taken from `X-User-ID` and recorded
    as `filed_by_athlete_id`, and must be an Athlete holding an entry on the
    appealed roster's procedure".

    Design: Difficulty/boundary_precision_check/appeal_window_boundary_72h
    """
    body = setup_certified_body(
        api=api,
        name="US Luge",
        sport_code="LUGE",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    entrant_1 = setup_eligible_athlete(
        body["id"], api=api, full_name="E One", date_of_birth="1998-01-01"
    )
    entrant_2 = setup_eligible_athlete(
        body["id"], api=api, full_name="E Two", date_of_birth="1998-02-02"
    )
    # E2's score 70 is below qualifying_score 80 (UNQUALIFIED), but the entry
    # record exists regardless, so only the temporal rule is under test.
    _proc, roster = setup_nominated_roster(
        body["id"],
        {entrant_1["id"]: 90, entrant_2["id"]: 70},
        api=api,
        quota_slots=1,
        qualifying_score=80,
        nominate_at="2026-12-20T00:00:00Z",
    )
    assert roster["status"] == "NOMINATED"
    assert parse_iso(roster["nominated_at"]) == parse_iso("2026-12-20T00:00:00Z"), (
        f"nominated_at must be stamped with the nomination-time clock, "
        f"got {roster['nominated_at']!r}"
    )

    # Exactly nominated_at + 72h00m00s: the inclusive boundary accepts.
    set_logical_clock("2026-12-23T00:00:00Z", api=api)
    appeal = file_appeal(
        roster["id"], entrant_1["id"], api=api, grounds="SCORING_ERROR"
    )
    assert appeal["status"] == "FILED"
    assert parse_iso(appeal["filed_at"]) == parse_iso("2026-12-23T00:00:00Z")

    # One second past the boundary: rejected.
    set_logical_clock("2026-12-23T00:00:01Z", api=api)
    resp = api.create_appeal(
        roster["id"],
        {"grounds": "SELECTION_PROCESS"},
        make_athlete_headers(entrant_2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED)
