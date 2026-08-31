"""Submitting, accepting and voiding observations, and the stipend ledger."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_observation,
    conduct_observation,
    get_cycle,
    get_observation,
    get_school,
    make_evaluator_headers,
    schedule_observation,
    score_all_domains,
    score_domain,
    setup_cycle,
    submit_observation,
    validate_error,
    validate_paginated,
    void_observation,
)

HR = TEST_USERS["hr_admin_headers"]


class TestStipendCompensation:
    """Submit commits the stipend; void releases exactly the same cents."""

    @staticmethod
    def _scored_formal():
        ctx = setup_cycle()
        ctx["observation"] = add_observation(
            ctx, observation_type="FORMAL", scores=(3, 3, 4, 3), stop_at="SCORED")
        return ctx

    def test_submitting_a_formal_observation_commits_the_policy_stipend(self, api):
        """PRD §3.5: "The observation's `stipend_cents` is set to the policy's
        `observation_stipend_cents` when its `observation_type` is `FORMAL`, and
        to two fifths of that figure — the informal rate is 0.4 of the formal one,
        rounded half-up to a whole cent — when the type is `INFORMAL`. That amount
        is then committed: the building's `evaluation_budget_committed_cents`
        increases by it and `evaluation_budget_remaining_cents` is recomputed."
        PRD §3.5: "Submission also refreshes the cycle's `completed_formal_count`
        and `completed_informal_count`, refreshes `evidence_artifact_count`,
        recomputes the cycle's `observation_component`, and increments the cycle's
        `version` by 1."
        PRD §3.5: "When only one of the two averages exists, that average *is* the
        `observation_component`, unblended and unpenalised."

        Design: Difficulty/compensating_invariant/submit_then_void_restores_school_budget_exactly
        """
        ctx = self._scored_formal()
        before = get_school(ctx["school"]["id"])
        assert before["evaluation_budget_committed_cents"] == 0
        assert before["evaluation_budget_remaining_cents"] == 100000

        submitted = submit_observation(ctx["observation"]["id"], ctx["evaluator"]["id"])
        assert submitted["stipend_cents"] == 12500

        school = get_school(ctx["school"]["id"])
        assert school["evaluation_budget_committed_cents"] == 12500
        assert school["evaluation_budget_remaining_cents"] == 87500

        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["completed_formal_count"] == 1
        assert cycle["observation_component"] == pytest.approx(3.3300)

    def test_voiding_the_submitted_observation_restores_the_budget_exactly(self, api):
        """PRD §3.5: "Voiding one in `SUBMITTED` or `ACCEPTED` releases its stipend
        exactly as a return does, decreasing the building's
        `evaluation_budget_committed_cents` by `stipend_cents` and resetting
        `stipend_cents` to 0, refreshes the cycle's `evidence_artifact_count` so
        that the voided observation's artifacts leave the cycle's tally, refreshes
        `completed_formal_count` and `completed_informal_count`, recomputes
        `observation_component`, and increments the cycle's `version`."
        PRD §3.5: "In every void, if no observation of the cycle remains in
        `CONDUCTED`, `SCORED`, `SUBMITTED`, `RETURNED` or `ACCEPTED`, a cycle
        sitting at `SCORING` bubbles back down to `SCHEDULING`, which increments
        the cycle's `version`. When that reversion leaves both
        `completed_formal_count` and `completed_informal_count` at 0, the cycle's
        `observation_component` is set back to null."
        PRD §2.10: "At every instant, a school's
        `evaluation_budget_committed_cents` equals the sum of `stipend_cents` over
        all observations whose cycle's educator has that school's `id` as their
        `school_id` and whose `status` is either `SUBMITTED` or `ACCEPTED`."

        Design: Difficulty/compensating_invariant/submit_then_void_restores_school_budget_exactly
        """
        ctx = self._scored_formal()
        submit_observation(ctx["observation"]["id"], ctx["evaluator"]["id"])
        assert get_school(ctx["school"]["id"])["evaluation_budget_committed_cents"] == 12500

        voided = void_observation(ctx["observation"]["id"],
                                  "Observation rescheduled by mutual agreement")
        assert voided["status"] == "VOIDED"
        assert voided["stipend_cents"] == 0

        school = get_school(ctx["school"]["id"])
        assert school["evaluation_budget_committed_cents"] == 0
        assert school["evaluation_budget_remaining_cents"] == 100000, (
            "the compensating void returns the building to zero drift"
        )

        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["completed_formal_count"] == 0
        assert cycle["observation_component"] is None
        assert cycle["status"] == "SCHEDULING"


class TestStateCheckPrecedesBudgetCheck:
    """A submit that violates both the state rule and the budget rule."""

    @staticmethod
    def _thin_budget_district():
        return setup_cycle(school_overrides={"name": "Thin Budget Middle",
                                             "code": "TBM", "level": "MIDDLE",
                                             "evaluation_budget_allocated_cents": 10000})

    def test_partly_scored_observation_is_refused_on_state_not_on_budget(self, api):
        """PRD §3.5: "Because only a `SCORED` observation can be submitted, an
        observation with fewer than four domains is still `CONDUCTED` and is turned
        away on the state check with `ERR_OBSERVATION_STATE_INVALID`."
        PRD §2.8: "Note equally that the state check precedes every business-safety
        and business-temporal check below it: an observation whose evaluator is
        uncertified but which is also in a state that forbids the transition is
        rejected on state."
        PRD §3.5: "If committing the stipend would push the school's committed
        total above its `evaluation_budget_allocated_cents`, the submission is
        refused with `ERR_EVALUATION_BUDGET_EXCEEDED` (HTTP 402) and nothing
        moves."

        Design: Difficulty/priority_pair_validation_conflict/observation_state_beats_budget_on_submit
        """
        ctx = self._thin_budget_district()
        observation = schedule_observation(ctx["cycle"]["id"], ctx["evaluator"]["id"])
        conducted = conduct_observation(observation["id"], ctx["evaluator"]["id"])
        first = score_domain(observation["id"], ctx["evaluator"]["id"],
                             "PLANNING", 3, conducted["version"])
        score_domain(observation["id"], ctx["evaluator"]["id"],
                     "ENVIRONMENT", 3, first["observation_version_after"])

        response = api.submit_observation(
            observation["id"], make_evaluator_headers(ctx["evaluator"]["id"]))
        error_data = validate_error(
            response, ApiErrorId.ERR_OBSERVATION_STATE_INVALID.value, 409)
        assert error_data["error_id"] != ApiErrorId.ERR_EVALUATION_BUDGET_EXCEEDED.value

        reread = get_observation(observation["id"])
        assert reread["status"] == "CONDUCTED"
        assert reread["stipend_cents"] == 0
        assert get_school(ctx["school"]["id"])["evaluation_budget_committed_cents"] == 0

    def test_fully_scored_observation_is_then_refused_on_the_thin_budget(self, api):
        """PRD §3.5: "If committing the stipend would push the school's committed
        total above its `evaluation_budget_allocated_cents`, the submission is
        refused with `ERR_EVALUATION_BUDGET_EXCEEDED` (HTTP 402) and nothing
        moves."
        PRD §3.5: "A committed total exactly equal to the allocation is permitted;
        only exceeding it is refused."

        Design: Difficulty/priority_pair_validation_conflict/observation_state_beats_budget_on_submit
        """
        ctx = self._thin_budget_district()
        observation = add_observation(ctx, observation_type="FORMAL",
                                      scores=(3, 3, 4, 3), stop_at="SCORED")

        response = api.submit_observation(
            observation["id"], make_evaluator_headers(ctx["evaluator"]["id"]))
        validate_error(response, ApiErrorId.ERR_EVALUATION_BUDGET_EXCEEDED.value, 402)

        reread = get_observation(observation["id"])
        assert reread["status"] == "SCORED", "a refused submission moves nothing"
        assert reread["stipend_cents"] == 0
        school = get_school(ctx["school"]["id"])
        assert school["evaluation_budget_committed_cents"] == 0
        assert school["evaluation_budget_remaining_cents"] == 10000


def test_accepting_a_scheduled_observation_is_a_state_violation(api):
    """PRD §3.5: "**Accepting** an observation moves it from `SUBMITTED` to
    `ACCEPTED` and is permitted while the cycle's `status` is `SCHEDULING`,
    `SCORING` or `SUBMITTED`; acceptance moves no money and disturbs no counter,
    because a `SUBMITTED` observation's stipend and its contribution to the cycle's
    counters are already reflected."
    PRD §2.8: "The rejection is `ERR_OBSERVATION_STATE_INVALID`,
    `ERR_CYCLE_STATE_INVALID`, `ERR_PLAN_STATE_INVALID`, `ERR_APPEAL_STATE_INVALID`,
    `ERR_GRIEVANCE_STATE_INVALID` or `ERR_TENURE_STATE_INVALID` according to the
    entity whose state was wrong, each HTTP 409."

    Design: Corner/state_machines/accept_from_scheduled_returns_observation_state_invalid
    """
    ctx = setup_cycle()
    observation = add_observation(ctx, stop_at="SCHEDULED")

    response = api.accept_observation(observation["id"], HR)
    validate_error(response, ApiErrorId.ERR_OBSERVATION_STATE_INVALID.value, 409)

    reread = get_observation(observation["id"])
    assert reread["status"] == "SCHEDULED"
    assert reread["stipend_cents"] == 0
    assert get_school(ctx["school"]["id"])["evaluation_budget_committed_cents"] == 0


def test_informal_observation_is_capped_and_earns_the_informal_stipend(api):
    """PRD §3.4: "An `INFORMAL` observation's `weighted_score` is capped at the
    policy's `informal_cap`, taking the lower of the summed contributions and that
    cap."
    PRD §2.5: "`unannounced_multiplier` defaults to 1.10 and `informal_cap` to
    3.50."
    PRD §3.5: "The observation's `stipend_cents` is set to the policy's
    `observation_stipend_cents` when its `observation_type` is `FORMAL`, and to two
    fifths of that figure — the informal rate is 0.4 of the formal one, rounded
    half-up to a whole cent — when the type is `INFORMAL`. That amount is then
    committed: the building's `evaluation_budget_committed_cents` increases by it
    and `evaluation_budget_remaining_cents` is recomputed."

    Design: Corner/calculations/informal_observation_capped_at_informal_cap_and_stipend_rounds_to_whole_cent
    """
    ctx = setup_cycle(policy_overrides={"required_formal_count": 1,
                                        "required_informal_count": 0})
    observation = schedule_observation(
        ctx["cycle"]["id"], ctx["evaluator"]["id"], observation_type="INFORMAL",
        scheduled_start="2026-09-10T09:00:00Z", scheduled_end="2026-09-10T09:30:00Z")
    conducted = conduct_observation(observation["id"], ctx["evaluator"]["id"])
    score_all_domains(observation["id"], ctx["evaluator"]["id"], (4, 4, 4, 4),
                      start_version=conducted["version"])

    scored = get_observation(observation["id"])
    assert scored["weighted_score"] == pytest.approx(3.50), (
        "the four contributions sum to 4.00 and are capped at the informal_cap"
    )
    assert scored["weighted_score"] != pytest.approx(4.00)

    rows, _meta = validate_paginated(api.list_rubric_scores(observation["id"], HR))
    live = {row["domain_code"]: row["weighted_contribution"]
            for row in rows if not row["superseded"]}
    assert live["PLANNING"] == pytest.approx(0.88)
    assert live["ENVIRONMENT"] == pytest.approx(0.92)
    assert live["INSTRUCTION"] == pytest.approx(1.32)
    assert live["PROFESSIONALISM"] == pytest.approx(0.88)

    submitted = submit_observation(observation["id"], ctx["evaluator"]["id"])
    assert submitted["stipend_cents"] == 5000, "0.4 of 12500 cents"

    school = get_school(ctx["school"]["id"])
    assert school["evaluation_budget_committed_cents"] == 5000
    assert school["evaluation_budget_remaining_cents"] == 95000

    cycle = get_cycle(ctx["cycle"]["id"])
    assert cycle["completed_informal_count"] == 1
    assert cycle["completed_formal_count"] == 0
