"""Research momentum decay, concept advancement gates, prototype-round budget,
and the concept deadline auto-kill (PRD §3.2, §3.9).
"""
import pytest

from test_helpers import (
    LEAD,
    ApiErrorId,
    api_client,
    add_insight,
    advance_concept,
    complete_round,
    create_concept,
    create_open_round,
    get_concept,
    run_review,
    set_clock,
    setup_season_with_category,
    validate_error,
    validate_ok,
)


def _concept_in_cycling(category_id: str) -> dict:
    """Concept walked IDENTIFIED -> RESEARCHING -> CONCEPT_LOCKED ->
    PROTOTYPE_CYCLING with the canonical two-insight 50.0 momentum (PRD §3.2);
    the logical clock is left at 2026-09-10."""
    concept = create_concept(category_id)
    add_insight(concept["id"], 40, "2026-09-01T00:00:00Z")
    add_insight(concept["id"], 16, "2026-09-08T00:00:00Z")
    set_clock("2026-09-10T00:00:00Z")
    advance_concept(concept["id"])
    advance_concept(concept["id"])
    advance_concept(concept["id"])
    return get_concept(concept["id"])


def test_research_momentum_decay_computed_exactly(api):
    """PRD §3.2: "a concept's `research_momentum` is the sum over all recorded
    insights of each entry's `points` multiplied by 0.85 raised to the number
    of full weeks elapsed between that entry's `observed_at` and the current
    logical clock."

    Design: Corner/calculations/research_momentum_decay_computed_exactly
    """
    base = setup_season_with_category()
    concept = create_concept(base["category"]["id"])
    add_insight(concept["id"], 40, "2026-09-01T00:00:00Z")
    add_insight(concept["id"], 16, "2026-09-08T00:00:00Z")
    set_clock("2026-09-10T00:00:00Z")
    data = get_concept(concept["id"])
    assert data["research_momentum"] == pytest.approx(50.0, abs=1e-9)


def test_research_momentum_below_gate_blocks_lock(api):
    """PRD §3.2: "From `RESEARCHING` to `CONCEPT_LOCKED`, the concept's
    momentum evaluated at the current logical clock must be at least 40.0 —
    the gate is inclusive, so a momentum of exactly 40.0 locks — else
    `ERR_RESEARCH_SCORE_TOO_LOW`."

    Design: Corner/calculations/research_momentum_below_gate_blocks_lock
    """
    base = setup_season_with_category()
    concept = create_concept(base["category"]["id"])
    add_insight(concept["id"], 30, "2026-09-01T00:00:00Z")
    set_clock("2026-09-29T00:00:00Z")
    advance_concept(concept["id"])  # IDENTIFIED -> RESEARCHING
    resp = api_client.advance_concept(concept["id"], LEAD)
    validate_error(resp, ApiErrorId.ERR_RESEARCH_SCORE_TOO_LOW)
    data = get_concept(concept["id"])
    assert data["research_momentum"] == pytest.approx(15.66, abs=1e-9)
    assert data["status"] == "RESEARCHING"


def test_advance_without_insights_rejected(api):
    """PRD §3.2: "From `IDENTIFIED` to `RESEARCHING`, the concept must hold at
    least one research insight, else the advance is rejected with
    `ERR_NO_RESEARCH_INSIGHTS`."

    Design: Corner/validations/advance_without_insights_rejected
    """
    base = setup_season_with_category()
    concept = create_concept(base["category"]["id"])
    resp = api_client.advance_concept(concept["id"], LEAD)
    validate_error(resp, ApiErrorId.ERR_NO_RESEARCH_INSIGHTS)
    assert get_concept(concept["id"])["status"] == "IDENTIFIED"


def test_round_complete_records_score_and_consumes_budget(api):
    """PRD §3.2: "Completing a round records a `score` as an integer from 0 to
    100 inclusive — anything outside that range is rejected with
    `ERR_INVALID_REQUEST` — and an optional `feedback` note, moving the round
    `OPEN` → `SCORED` and incrementing the concept's `rounds_used` by one."

    Design: Corner/state_machines/round_complete_records_score_and_consumes_budget
    """
    base = setup_season_with_category()
    concept = _concept_in_cycling(base["category"]["id"])
    round_ = create_open_round(concept["id"])
    data = complete_round(round_["id"], 80)
    assert data["status"] == "SCORED"
    assert data["score"] == 80
    concept = get_concept(concept["id"])
    assert concept["status"] == "PROTOTYPE_CYCLING"
    assert concept["rounds_used"] == 1


def test_round_complete_twice_rejected(api):
    """PRD §3.2: "Completing a round that is no longer `OPEN` is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/round_complete_twice_rejected
    """
    base = setup_season_with_category()
    concept = _concept_in_cycling(base["category"]["id"])
    round_ = create_open_round(concept["id"])
    complete_round(round_["id"], 80)
    resp = api_client.complete_round(round_["id"], {"score": 10}, LEAD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    rounds = validate_ok(api_client.list_rounds(concept["id"], LEAD))
    assert rounds[0]["status"] == "SCORED"
    assert rounds[0]["score"] == 80


def test_round_expires_after_max_open_days(api):
    """PRD §3.2: "A round left `OPEN` for more than 21 days is expired by the
    run-review (§3.9), which also increments `rounds_used`: expiry consumes
    prototype budget exactly as a completion does."

    Design: Corner/state_machines/round_expires_after_max_open_days
    """
    base = setup_season_with_category()
    concept = _concept_in_cycling(base["category"]["id"])
    create_open_round(concept["id"])  # opened_at 2026-09-10
    set_clock("2026-10-02T00:00:00Z")
    run_review(base["season"]["id"])
    rounds = validate_ok(api_client.list_rounds(concept["id"], LEAD))
    assert rounds[0]["status"] == "EXPIRED"
    concept = get_concept(concept["id"])
    assert concept["rounds_used"] == 1
    assert concept["status"] == "PROTOTYPE_CYCLING"


def test_concept_reverts_to_research_when_prototype_budget_exhausted(api):
    """PRD §3.2: "Conversely, when a failing completion (a score below 75) or
    an expiry raises `rounds_used` to 4, the concept reverts from
    `PROTOTYPE_CYCLING` to `RESEARCHING` and `rounds_used` resets to 0: the
    exhausted budget sends the team back for more consumer research, and
    because momentum kept decaying throughout the cycle, the re-lock gate may
    now block what it previously allowed."

    Design: Corner/state_machines/concept_reverts_to_research_when_prototype_budget_exhausted
    """
    base = setup_season_with_category()
    concept = _concept_in_cycling(base["category"]["id"])
    for expected_used in (1, 2, 3):
        round_ = create_open_round(concept["id"])
        complete_round(round_["id"], 50)
        mid = get_concept(concept["id"])
        assert mid["status"] == "PROTOTYPE_CYCLING"
        assert mid["rounds_used"] == expected_used
    round4 = create_open_round(concept["id"])
    complete_round(round4["id"], 50)
    concept = get_concept(concept["id"])
    assert concept["status"] == "RESEARCHING"
    assert concept["rounds_used"] == 0


def test_concept_deadline_autokill_at_review(api):
    """PRD §3.2: "A concept that has not reached `ENGINEERING_LOCKED` within
    120 days of its creation is killed by the run-review, moving from any of
    `IDENTIFIED`, `RESEARCHING`, `CONCEPT_LOCKED`, or `PROTOTYPE_CYCLING` to
    `LAUNCH_KILLED` with `killed_reason` set to `DEADLINE_EXCEEDED`; any round
    still `OPEN` on the concept expires in the same sweep."

    Design: Corner/state_machines/concept_deadline_autokill_at_review
    """
    base = setup_season_with_category()
    concept = create_concept(base["category"]["id"])  # created 2026-09-01
    set_clock("2026-12-31T00:00:00Z")  # 121 days later
    run_review(base["season"]["id"])
    data = get_concept(concept["id"])
    assert data["status"] == "LAUNCH_KILLED"
    assert data["killed_reason"] == "DEADLINE_EXCEEDED"
