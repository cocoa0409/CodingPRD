"""Difficulty tests: non_linear_state_machine — parallel state dimensions on
one entity evolving independently, and a non-terminal revert loop on the
roster lifecycle.
"""
import pytest

from test_helpers import (
    add_verified_result,
    clear_screening,
    create_athlete,
    decide_appeal,
    file_appeal,
    make_eligible,
    move_appeal_to_hearing,
    read_roster,
    record_training,
    run_nominations,
    setup_certified_body,
    setup_nominated_roster,
    suspend_athlete,
)


def test_athlete_parallel_dimensions_suspend_reinstate_loop(
    api, committee_admin_headers
):
    """PRD athlete section: "An Athlete carries two parallel state dimensions
    that move independently. The eligibility dimension, `eligibility_status`,
    runs `REGISTERED` to `ELIGIBLE`, may drop to `SUSPENDED` and return, and
    ends at the terminal `RETIRED`."
    PRD athlete section: "A `SafeSportOfficer` clears screening from
    `SCREENING_PENDING`, `SCREENING_FLAGGED`, or `SCREENING_EXPIRED` — never
    while the athlete is `RETIRED` — moving the athlete to `SCREENING_CLEARED`
    and setting `screening_expires_at` to the current logical clock plus 730
    days."
    PRD athlete section: "Suspension — `ELIGIBLE` to `SUSPENDED`, by officer
    action or by cascade — halts the athlete's funding in the same operation".
    PRD athlete section: "Reinstatement from `SUSPENDED` to `ELIGIBLE` carries
    the same two prongs plus a third: no AbuseReport of this athlete may sit
    in `REPORTED` or `FORWARDED` status."

    Design: Difficulty/non_linear_state_machine/athlete_parallel_dimensions_suspend_reinstate_loop
    """
    body = setup_certified_body(
        api=api,
        name="US Fencing",
        sport_code="FENC",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = create_athlete(
        body["id"], api=api, full_name="Rio Foil", date_of_birth="2001-03-03"
    )
    cleared = clear_screening(athlete["id"], api=api)
    screening_expires_before = cleared["screening_expires_at"]
    assert screening_expires_before is not None
    record_training(athlete["id"], api=api)
    onboarded = make_eligible(athlete["id"], api=api)
    assert onboarded["eligibility_status"] == "ELIGIBLE"
    assert onboarded["screening_status"] == "SCREENING_CLEARED"

    suspended = suspend_athlete(athlete["id"], api=api)
    # Dimension independence: eligibility drops while screening stays pinned.
    assert suspended["eligibility_status"] == "SUSPENDED"
    assert suspended["screening_status"] == "SCREENING_CLEARED", (
        "the screening dimension must not move with an eligibility suspension"
    )
    assert suspended["screening_expires_at"] == screening_expires_before, (
        "screening_expires_at must be unchanged across the suspend/reinstate loop"
    )

    reinstated = make_eligible(athlete["id"], api=api)
    assert reinstated["eligibility_status"] == "ELIGIBLE"
    assert reinstated["screening_status"] == "SCREENING_CLEARED"
    # The full cycle REGISTERED -> ELIGIBLE -> SUSPENDED -> ELIGIBLE completed
    # on one entity while the screening dimension never left SCREENING_CLEARED.


def test_roster_nominated_draft_renomination_loop(api, committee_admin_headers):
    """PRD appeals paragraph of the selection section: "An upheld appeal
    cascades the roster from `NOMINATED` back to `DRAFT`: the `slots` list is
    cleared entirely, the selector must be re-run to rebuild it, and
    `declined_athlete_ids` is preserved rather than cleared so athletes who
    declined stay excluded from the re-run."
    PRD selection section: "The roster lifecycle runs `DRAFT` to `NOMINATED`
    to `SUBMITTED` to the terminal `CONFIRMED`, with `CANCELLED` as the
    cascade-driven terminal exit and a revert path from `NOMINATED` back to
    `DRAFT`."
    PRD selection section: "Each candidate's `composite_score` is a weighted
    blend of 0.7 times their `trials_score` — the entry's recorded `score` —
    and 0.3 times their season points, rounded half up to two decimal places."

    Design: Difficulty/non_linear_state_machine/roster_nominated_draft_renomination_loop
    """
    body = setup_certified_body(
        api=api,
        name="US Judo",
        sport_code="JUDO",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete_1 = create_athlete(
        body["id"], api=api, full_name="A One", date_of_birth="1998-01-01"
    )
    clear_screening(athlete_1["id"], api=api)
    record_training(athlete_1["id"], api=api)
    make_eligible(athlete_1["id"], api=api)
    # A1 season points 40 (1st/C on 2026-06-01).
    add_verified_result(
        athlete_1["id"], event_grade="C", placing=1,
        event_date="2026-06-01T00:00:00Z", event_name="June Meet", api=api,
    )
    athlete_2 = create_athlete(
        body["id"], api=api, full_name="A Two", date_of_birth="1998-01-02"
    )
    clear_screening(athlete_2["id"], api=api)
    record_training(athlete_2["id"], api=api)
    make_eligible(athlete_2["id"], api=api)
    # A2 season points 32 (2nd/C on 2026-06-01).
    add_verified_result(
        athlete_2["id"], event_grade="C", placing=2,
        event_date="2026-06-01T00:00:00Z", event_name="June Meet", api=api,
    )

    _proc, roster = setup_nominated_roster(
        body["id"],
        {athlete_1["id"]: 90, athlete_2["id"]: 85},
        api=api,
        quota_slots=1,
        qualifying_score=80,
        nominate_at="2026-12-20T00:00:00Z",
    )
    assert roster["status"] == "NOMINATED"
    first_by_rank = {slot["rank"]: slot for slot in roster["slots"]}
    assert first_by_rank[1]["athlete_id"] == athlete_1["id"]
    assert first_by_rank[1]["slot_type"] == "PRIMARY"
    assert first_by_rank[1]["composite_score"] == pytest.approx(75.0, abs=1e-9)
    assert first_by_rank[2]["athlete_id"] == athlete_2["id"]
    assert first_by_rank[2]["slot_type"] == "ALTERNATE"
    assert first_by_rank[2]["composite_score"] == pytest.approx(69.1, abs=1e-9)

    # A2 (an entrant) appeals within the window; the arbitrator upholds.
    appeal = file_appeal(
        roster["id"], athlete_2["id"], api=api, grounds="SELECTION_PROCESS"
    )
    move_appeal_to_hearing(appeal["id"], api=api)
    decide_appeal(
        appeal["id"], "UPHELD",
        decision_rationale="scoring table misapplied", api=api,
    )

    reverted = read_roster(roster["id"], api=api)
    assert reverted["status"] == "DRAFT", (
        f"an upheld appeal must revert the roster to DRAFT, got {reverted['status']!r}"
    )
    assert reverted["slots"] == [], (
        f"the slots list must be cleared entirely, got {reverted['slots']!r}"
    )

    # A fresh nomination legitimately re-runs the selector: DRAFT -> NOMINATED
    # again (the DRAFT -> NOMINATED -> DRAFT -> NOMINATED loop, not lockdown).
    renominated = run_nominations(reverted, body["id"], api=api)
    assert renominated["status"] == "NOMINATED"
    second_by_rank = {slot["rank"]: slot for slot in renominated["slots"]}
    assert set(second_by_rank) == {1, 2}
    assert second_by_rank[1]["athlete_id"] == athlete_1["id"]
    assert second_by_rank[1]["slot_type"] == "PRIMARY"
    assert second_by_rank[1]["composite_score"] == pytest.approx(75.0, abs=1e-9)
    assert second_by_rank[2]["athlete_id"] == athlete_2["id"]
    assert second_by_rank[2]["slot_type"] == "ALTERNATE"
    assert second_by_rank[2]["composite_score"] == pytest.approx(69.1, abs=1e-9)
