"""Difficulty tests: compensating_invariant — a mutation paired with its
compensating action leaves a conserved quantity unchanged (roster PRIMARY
headcount across decline+promotion; committed stipend cents across
suspend+resume).
"""
import pytest

from test_helpers import (
    activate_agreement,
    add_verified_result,
    add_verified_results,
    answer_slot,
    assert_decline_conservation,
    create_funding_agreement,
    make_eligible,
    primary_slot_count,
    read_funding_agreement,
    read_governing_body,
    set_logical_clock,
    setup_certified_body,
    setup_eligible_athlete,
    setup_nominated_roster,
    suspend_athlete,
)


def test_roster_slot_decline_promotion_conservation(api, committee_admin_headers):
    """PRD selection section: "A `DECLINED` decision marks it `DECLINED`,
    appends the athlete to `declined_athlete_ids`, and fires the promotion
    cascade: the highest-ranked `ALTERNATE` slot still `NOMINATED` becomes a
    `PRIMARY` slot with `slot_status` of `PROMOTED` and its `rank`
    reassigned".
    PRD selection section: "The roster invariant holds across a decline: the
    count of `PRIMARY` slots whose `slot_status` is `NOMINATED`, `PROMOTED`,
    or `ACCEPTED` is unchanged whenever an alternate is available to promote."
    PRD selection section: "Each candidate's `composite_score` is a weighted
    blend of 0.7 times their `trials_score` — the entry's recorded `score` —
    and 0.3 times their season points, rounded half up to two decimal places."

    Design: Difficulty/compensating_invariant/roster_slot_decline_promotion_conservation
    """
    body = setup_certified_body(
        api=api,
        name="US Karate",
        sport_code="KARA",
        funding_budget_cents=8_000_000,
        sport_science_pool_hours=100,
    )
    # All four athletes bank season 40 (one 1st/C on 2026-06-01), so the
    # top-3 sum 120 stays below the 250 quota-bonus threshold and
    # quota_effective equals quota_slots (2).
    athletes = {}
    for key, dob in (
        ("a1", "1998-01-01"), ("a2", "1998-01-02"),
        ("b1", "1998-01-03"), ("b2", "1998-01-04"),
    ):
        athletes[key] = setup_eligible_athlete(
            body["id"], api=api, full_name=f"Athlete {key}", date_of_birth=dob
        )
        add_verified_result(
            athletes[key]["id"], event_grade="C", placing=1,
            event_date="2026-06-01T00:00:00Z", event_name="June Meet", api=api,
        )

    _proc, roster = setup_nominated_roster(
        body["id"],
        {athletes["a1"]["id"]: 95, athletes["a2"]["id"]: 90,
         athletes["b1"]["id"]: 85, athletes["b2"]["id"]: 82},
        api=api,
        quota_slots=2,
        qualifying_score=80,
        nominate_at="2026-12-20T00:00:00Z",
    )
    slots_before = roster["slots"]
    by_rank = {slot["rank"]: slot for slot in slots_before}
    assert by_rank[1]["athlete_id"] == athletes["a1"]["id"]
    assert by_rank[1]["slot_type"] == "PRIMARY"
    assert by_rank[1]["composite_score"] == pytest.approx(78.5, abs=1e-9)  # 0.7*95+0.3*40
    assert by_rank[2]["athlete_id"] == athletes["a2"]["id"]
    assert by_rank[2]["slot_type"] == "PRIMARY"
    assert by_rank[2]["composite_score"] == pytest.approx(75.0, abs=1e-9)  # 0.7*90+0.3*40
    assert by_rank[3]["athlete_id"] == athletes["b1"]["id"]
    assert by_rank[3]["slot_type"] == "ALTERNATE"
    assert by_rank[3]["composite_score"] == pytest.approx(71.5, abs=1e-9)  # 0.7*85+0.3*40
    assert by_rank[4]["athlete_id"] == athletes["b2"]["id"]
    assert by_rank[4]["slot_type"] == "ALTERNATE"
    assert by_rank[4]["composite_score"] == pytest.approx(69.4, abs=1e-9)  # 0.7*82+0.3*40
    assert primary_slot_count(slots_before) == 2

    # A1 declines the rank-1 PRIMARY slot; the promotion cascade compensates.
    after = answer_slot(roster["id"], athletes["a1"]["id"], "DECLINED", api=api)
    slots_after = after["slots"]
    after_by_athlete = {s["athlete_id"]: s for s in slots_after}

    assert after_by_athlete[athletes["a1"]["id"]]["slot_status"] == "DECLINED"
    promoted = after_by_athlete[athletes["b1"]["id"]]
    assert promoted["slot_type"] == "PRIMARY", (
        "the highest-ranked live ALTERNATE must be promoted to PRIMARY"
    )
    assert promoted["slot_status"] == "PROMOTED"

    # The conserved quantity: committed PRIMARY headcount unchanged at 2.
    assert_decline_conservation(slots_before, slots_after)
    assert primary_slot_count(slots_after) == 2

    # A2 keeps its PRIMARY seat; B2 remains an unanswered ALTERNATE.
    assert after_by_athlete[athletes["a2"]["id"]]["slot_type"] == "PRIMARY"
    assert after_by_athlete[athletes["a2"]["id"]]["slot_status"] == "NOMINATED"
    assert after_by_athlete[athletes["b2"]["id"]]["slot_type"] == "ALTERNATE"
    assert after_by_athlete[athletes["b2"]["id"]]["slot_status"] == "NOMINATED"

    # The decliner is recorded for exclusion from any future re-run.
    assert athletes["a1"]["id"] in after["declined_athlete_ids"]


def test_stipend_suspend_resume_conservation(api, committee_admin_headers):
    """PRD funding section: "Suspension subtracts exactly the agreement's
    `monthly_stipend_cents` from the body's `committed_monthly_stipend_cents`
    — an exact reversal, never an approximation".
    PRD funding section: "the resumption adds back exactly the stipend amount
    removed at suspension, so the committed total never drifts."
    PRD athlete section: "Reinstatement restores funding: every `SUSPENDED`
    FundingAgreement of the athlete whose `tier` is not `NONE` cascades back
    to `ACTIVE`, restoring its stipend exactly."
    PRD athlete section: "Suspension — `ELIGIBLE` to `SUSPENDED`, by officer
    action or by cascade — halts the athlete's funding in the same operation:
    every `ACTIVE` FundingAgreement of the athlete moves to `SUSPENDED` and
    its stipend stops."

    Design: Difficulty/compensating_invariant/stipend_suspend_resume_conservation
    """
    body = setup_certified_body(
        api=api,
        name="US Rowing",
        sport_code="ROWI",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete_g1 = setup_eligible_athlete(
        body["id"], api=api, full_name="G One", date_of_birth="1998-01-01"
    )
    # 2 x (40 * 1.5) = 120.00 -> TIER_A, stipend 300000.
    add_verified_results(
        athlete_g1["id"],
        [
            {"event_name": "August Cup", "event_grade": "A", "placing": 1,
             "event_date": "2026-08-01T00:00:00Z"},
            {"event_name": "August Open", "event_grade": "A", "placing": 1,
             "event_date": "2026-08-01T00:00:00Z"},
        ],
        api=api,
    )
    athlete_g2 = setup_eligible_athlete(
        body["id"], api=api, full_name="G Two", date_of_birth="1998-02-02"
    )
    # 26 * 1.25 = 32.50 -> TIER_C, stipend 100000.
    add_verified_result(
        athlete_g2["id"], event_grade="B", placing=3,
        event_date="2026-08-01T00:00:00Z", event_name="August Cup", api=api,
    )

    set_logical_clock("2026-10-01T00:00:00Z", api=api)
    agreement_g1 = create_funding_agreement(
        athlete_g1["id"],
        api=api,
        coverage_start="2026-10-01T00:00:00Z",
        coverage_end="2027-04-01T00:00:00Z",
        points_method="TRAILING_365",
    )
    assert agreement_g1["trailing_points"] == pytest.approx(120.0, abs=1e-9)
    assert agreement_g1["tier"] == "TIER_A"
    assert agreement_g1["monthly_stipend_cents"] == 300000
    activate_agreement(agreement_g1["id"], api=api)

    agreement_g2 = create_funding_agreement(
        athlete_g2["id"],
        api=api,
        coverage_start="2026-10-01T00:00:00Z",
        coverage_end="2027-04-01T00:00:00Z",
        points_method="TRAILING_365",
    )
    assert agreement_g2["trailing_points"] == pytest.approx(32.5, abs=1e-9)
    assert agreement_g2["tier"] == "TIER_C"
    assert agreement_g2["monthly_stipend_cents"] == 100000
    activate_agreement(agreement_g2["id"], api=api)

    body_before = read_governing_body(body["id"], api=api)
    assert body_before["committed_monthly_stipend_cents"] == 400000, (
        "both agreements ACTIVE: 300000 + 100000 committed, "
        f"got {body_before['committed_monthly_stipend_cents']!r}"
    )

    # Suspend G1's athlete: exactly 300000 is debited.
    suspend_athlete(athlete_g1["id"], api=api)
    body_mid = read_governing_body(body["id"], api=api)
    assert body_mid["committed_monthly_stipend_cents"] == 100000, (
        "after suspension only G2's 100000 stipend remains committed, "
        f"got {body_mid['committed_monthly_stipend_cents']!r}"
    )

    # Reinstate to ELIGIBLE: the exact amount is added back, zero drift.
    make_eligible(athlete_g1["id"], api=api)
    body_after = read_governing_body(body["id"], api=api)
    assert body_after["committed_monthly_stipend_cents"] == 400000, (
        "the suspend+resume pair must conserve committed cents exactly, "
        f"got {body_after['committed_monthly_stipend_cents']!r}"
    )
    agreement_g1_after = read_funding_agreement(agreement_g1["id"], api=api)
    assert agreement_g1_after["status"] == "ACTIVE"
    assert agreement_g1_after["monthly_stipend_cents"] == 300000, (
        "the loop leaves the agreement's stipend unchanged"
    )
