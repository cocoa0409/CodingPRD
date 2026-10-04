"""Corner tests: calculations section — pinned placing/grade constants,
funding-points input-set filtering, the sport-science hours waterfall with
partial fill, and the roster composite tie-break."""
import pytest

from test_helpers import (
    activate_agreement,
    add_verified_result,
    add_verified_results,
    create_athlete,
    create_funding_agreement,
    create_funding_agreement_payload,
    create_governing_body,
    create_roster,
    read_funding_agreement,
    read_governing_body,
    reject_result,
    run_nominations,
    set_logical_clock,
    setup_certified_body,
    setup_eligible_athlete,
    setup_finalized_procedure,
    submit_result,
    validate_success,
    verify_result,
)


def test_placing_points_constants_applied(api):
    """PRD §3.4: "The placing ladder pays 40 points for 1st, 32 for 2nd, 26
    for 3rd, 20 for 4th, 16 for 5th, 12 for 6th, 8 for 7th, and 4 for 8th. The
    grade multiplier is 1.5 for an `A`-graded event, 1.25 for a `B`, and 1.0
    for a `C`. The `base_points` of a result are the placing points multiplied
    by the grade multiplier — a 2nd place at an `A` event banks 48 points, a
    1st at a `C` event banks 40."
    PRD §3.4: "A `ResultsOfficial` then verifies or rejects it — never the
    same person as the submitting athlete, with a self-verification rejected
    as `ERR_SEGREGATION_OF_DUTIES` — and verification stamps
    `verified_by_user_id` and computes `base_points`."

    Design: Corner/calculations/placing_points_constants_applied
    """
    body = create_governing_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = create_athlete(
        body["id"], api=api, full_name="Const Check", date_of_birth="2000-01-01"
    )
    result = submit_result(
        athlete["id"],
        api=api,
        event_name="Spring Open",
        event_grade="B",
        placing=3,
        event_date="2026-10-01T00:00:00Z",
    )
    verified = verify_result(result["id"], api=api)
    assert verified["status"] == "VERIFIED"
    # PLACING_POINTS[3] = 26 times EVENT_MULTIPLIER B = 1.25 -> 32.5;
    # not 26 (multiplier dropped) and not 39 (grade A multiplier).
    assert verified["base_points"] == pytest.approx(32.5, abs=1e-9)


def test_funding_points_input_set_filtering(api, committee_admin_headers):
    """PRD §3.4: "Funding points aggregate `VERIFIED` results only;
    `SUBMITTED` and `REJECTED` results never count."
    PRD §3.4: "`TRAILING_365` anchors on the current logical clock and
    includes each verified result whose age — clock minus `event_date` — is at
    least 0 days and at most 365 days. A recency weight applies per result:
    full weight for results aged at most 180 days, and half weight — a
    multiplier of 0.5 — for results aged 181 through 365 days."
    PRD §3.4: "the operative value fixes the funding `tier` against inclusive
    thresholds: `TIER_A` at 100 points or more, `TIER_B` at 60 or more,
    `TIER_C` at 30 or more, and `NONE` below 30 — a value exactly on a
    threshold qualifies for that tier."

    Design: Corner/calculations/funding_points_input_set_filtering
    """
    body = create_governing_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = setup_eligible_athlete(
        body["id"], api=api, full_name="Filter Test", date_of_birth="2000-01-01"
    )
    # Three identical 1st/A results; only the first is VERIFIED.
    r1 = submit_result(
        athlete["id"], api=api, event_name="Cup 1", event_grade="A", placing=1,
        event_date="2026-08-01T00:00:00Z",
    )
    verify_result(r1["id"], api=api)
    submit_result(
        athlete["id"], api=api, event_name="Cup 2", event_grade="A", placing=1,
        event_date="2026-08-01T00:00:00Z",
    )  # left SUBMITTED — must not count
    r3 = submit_result(
        athlete["id"], api=api, event_name="Cup 3", event_grade="A", placing=1,
        event_date="2026-08-01T00:00:00Z",
    )
    reject_result(r3["id"], api=api)  # REJECTED — must not count

    set_logical_clock("2026-10-01T00:00:00Z", api=api)
    resp = api.create_funding_agreement(
        athlete["id"],
        create_funding_agreement_payload(
            coverage_start="2026-10-01T00:00:00Z",
            coverage_end="2027-04-01T00:00:00Z",
            points_method="TRAILING_365",
        ),
        committee_admin_headers,
    )
    agreement = validate_success(resp, 201)
    # Only the VERIFIED result counts: 40 * 1.5 = 60.0 at full recency weight
    # (61 days old), not 180.0.
    assert agreement["trailing_points"] == pytest.approx(60.0, abs=1e-9)
    assert agreement["tier"] == "TIER_B", "60.0 meets the inclusive TIER_B threshold"


def test_science_hours_waterfall_partial_fill(api, committee_admin_headers):
    """PRD §3.5: "The buckets are the `ACTIVE` FundingAgreements of athletes
    whose `governing_body_id` is that body, ordered tier `TIER_A` before
    `TIER_B` before `TIER_C`; within a tier, the agreement with the earlier
    `activated_at` fills first, and a final tie between two agreements breaks
    toward the earlier `created_at`. Walking that order, each bucket receives
    the smaller of the remaining pool and its tier cap — 40 hours for
    `TIER_A`, 25 for `TIER_B`, 10 for `TIER_C`. A partial fill is allowed for
    the last bucket the pool reaches, and every bucket the pool never reaches
    receives zero."
    PRD §3.5: "The waterfall writes `science_hours_allocated` onto each
    agreement and the body's `allocated_science_hours` as the sum of those
    allocations, which therefore never exceeds the pool. It reruns on every
    activation, suspension, termination, and reassessment of any agreement
    under the body, so allocations always reflect the currently-active set."

    Design: Corner/calculations/science_hours_waterfall_partial_fill
    """
    body = setup_certified_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=10_000_000,
        sport_science_pool_hours=80,
    )

    # TIER_A athlete: two VERIFIED 1st/A results -> 120.00 trailing points.
    a_tier = setup_eligible_athlete(
        body["id"], api=api, full_name="Tier A", date_of_birth="1998-01-01"
    )
    add_verified_results(
        a_tier["id"],
        [
            {"event_name": "Cup 1", "event_grade": "A", "placing": 1,
             "event_date": "2026-08-01T00:00:00Z"},
            {"event_name": "Cup 2", "event_grade": "A", "placing": 1,
             "event_date": "2026-08-01T00:00:00Z"},
        ],
        api=api,
    )
    # TIER_B athletes: one VERIFIED 1st/A each -> 60.00 points.
    b1 = setup_eligible_athlete(
        body["id"], api=api, full_name="Tier B1", date_of_birth="1998-01-02"
    )
    add_verified_result(
        b1["id"], event_grade="A", placing=1,
        event_date="2026-08-01T00:00:00Z", event_name="Cup 1", api=api,
    )
    b2 = setup_eligible_athlete(
        body["id"], api=api, full_name="Tier B2", date_of_birth="1998-01-03"
    )
    add_verified_result(
        b2["id"], event_grade="A", placing=1,
        event_date="2026-08-01T00:00:00Z", event_name="Cup 1", api=api,
    )
    # TIER_C athlete: one VERIFIED 3rd/B -> 26 * 1.25 = 32.50 points.
    c_tier = setup_eligible_athlete(
        body["id"], api=api, full_name="Tier C", date_of_birth="1998-01-04"
    )
    add_verified_result(
        c_tier["id"], event_grade="B", placing=3,
        event_date="2026-08-01T00:00:00Z", event_name="Cup 1", api=api,
    )

    def offer_and_activate(athlete_id, day):
        set_logical_clock(f"2026-10-0{day}T00:00:00Z", api=api)
        agreement = create_funding_agreement(
            athlete_id,
            api=api,
            coverage_start=f"2026-10-0{day}T00:00:00Z",
            coverage_end=f"2027-04-0{day}T00:00:00Z",
            points_method="TRAILING_365",
        )
        activate_agreement(agreement["id"], api=api)
        return agreement["id"]

    # Activation order pins the within-tier fill order.
    ag_a = offer_and_activate(a_tier["id"], 1)
    ag_b1 = offer_and_activate(b1["id"], 2)
    ag_b2 = offer_and_activate(b2["id"], 3)
    ag_c = offer_and_activate(c_tier["id"], 4)

    hours_a = read_funding_agreement(ag_a, api=api)["science_hours_allocated"]
    hours_b1 = read_funding_agreement(ag_b1, api=api)["science_hours_allocated"]
    hours_b2 = read_funding_agreement(ag_b2, api=api)["science_hours_allocated"]
    hours_c = read_funding_agreement(ag_c, api=api)["science_hours_allocated"]
    body_after = read_governing_body(body["id"], api=api)

    assert hours_a == 40, "TIER_A fills first to its 40-hour cap"
    assert hours_b1 == 25, "earlier-activated TIER_B fills to its 25-hour cap"
    assert hours_b2 == 15, "partial fill: 80 - 40 - 25 = 15 hours remain"
    assert hours_c == 0, "pool exhausted before tier C is reached"
    assert body_after["allocated_science_hours"] == 80, (
        "the body total is the sum of allocations, fully consuming the 80-hour pool"
    )


def test_composite_tiebreak_higher_trials_wins(api):
    """PRD §3.6: "Each candidate's `composite_score` is a weighted blend of
    0.7 times their `trials_score` — the entry's recorded `score` — and 0.3
    times their season points, rounded half up to two decimal places. Ranking
    orders candidates by `composite_score` descending; ties break by
    `trials_score` descending, then by the earlier entry `result_recorded_at`,
    then by the earlier athlete `created_at`. The first `quota_effective`
    candidates fill `PRIMARY` slots ranked 1 through N, and the next 2
    candidates fill `ALTERNATE` slots."
    PRD §3.6: "The quota bonus sums the three highest season-point totals
    among athletes holding `QUALIFIED` entries — when fewer than three
    athletes are qualified, it sums all of them — and when that sum reaches
    250 the roster's `bonus_slot_applied` is set true and `quota_effective`
    becomes `quota_slots` plus one bonus slot; below 250, `bonus_slot_applied`
    is false and `quota_effective` equals `quota_slots` unchanged."

    Design: Corner/calculations/composite_tiebreak_higher_trials_wins
    """
    body = setup_certified_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=8_000_000,
        sport_science_pool_hours=100,
    )
    # P: season 50 (1st/C = 40.0 plus 7th/B = 8*1.25 = 10.0), trials 90.
    p = setup_eligible_athlete(
        body["id"], api=api, full_name="P Tied", date_of_birth="1998-01-01"
    )
    add_verified_results(
        p["id"],
        [
            {"event_name": "June Meet", "event_grade": "C", "placing": 1,
             "event_date": "2026-06-01T00:00:00Z"},
            {"event_name": "June Open", "event_grade": "B", "placing": 7,
             "event_date": "2026-06-01T00:00:00Z"},
        ],
        api=api,
    )
    # Q: season 57 (2nd/C = 32.0, 4th/C = 20.0, 8th/B = 4*1.25 = 5.0), trials 87.
    q = setup_eligible_athlete(
        body["id"], api=api, full_name="Q Tied", date_of_birth="1998-01-02"
    )
    add_verified_results(
        q["id"],
        [
            {"event_name": "June Meet", "event_grade": "C", "placing": 2,
             "event_date": "2026-06-01T00:00:00Z"},
            {"event_name": "June Open", "event_grade": "C", "placing": 4,
             "event_date": "2026-06-01T00:00:00Z"},
            {"event_name": "June Classic", "event_grade": "B", "placing": 8,
             "event_date": "2026-06-01T00:00:00Z"},
        ],
        api=api,
    )

    proc = setup_finalized_procedure(
        body["id"], {p["id"]: 90, q["id"]: 87}, api=api, quota_slots=1
    )
    roster = create_roster(proc["id"], body["id"], api=api)
    set_logical_clock("2026-12-20T00:00:00Z", api=api)
    roster = run_nominations(roster, body["id"], api=api)

    # Both composites: P = 0.7*90 + 0.3*50 = 78.0; Q = 0.7*87 + 0.3*57 = 78.0.
    # Season sum 50 + 57 = 107 < 250, so quota_effective stays 1: one PRIMARY
    # slot and the next candidate takes an ALTERNATE slot.
    assert roster["bonus_slot_applied"] is False
    assert roster["quota_effective"] == 1
    slots = {s["rank"]: s for s in roster["slots"]}
    assert set(slots) == {1, 2}, f"expected exactly ranks 1 and 2, got {roster['slots']}"

    rank1, rank2 = slots[1], slots[2]
    assert rank1["composite_score"] == pytest.approx(78.0, abs=1e-9)
    assert rank2["composite_score"] == pytest.approx(78.0, abs=1e-9)
    assert rank1["athlete_id"] == p["id"], (
        "tie at 78.0 breaks by trials_score descending: 90 beats 87"
    )
    assert rank1["slot_type"] == "PRIMARY"
    assert rank1["trials_score"] == 90
    assert rank2["athlete_id"] == q["id"]
    assert rank2["slot_type"] == "ALTERNATE", "quota_slots 1 leaves one PRIMARY"
    assert rank2["trials_score"] == 87
