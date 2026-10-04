"""Scorecards, round scores, advancement decisions and the waitlist cycle
(PRD §3.2, §2.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_evaluation,
    assert_nominee,
    create_evaluation_payload,
    create_nominee_at_round_1,
    create_waitlisted_nominee,
    decide,
    get_nominee,
    make_assessor_headers,
    nominate,
    setup_city_with_partner,
    submit_evaluation,
    submit_round_evals,
    submit_round_evals_pair,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["program_admin_headers"]
_OFFICER = TEST_USERS["selection_officer_headers"]


def _setup_round_1_nominee():
    """City + partner + one nominee advanced to ROUND_1."""
    program, partner = setup_city_with_partner(quota=20)
    nominee = create_nominee_at_round_1(program, partner, "Nom One")
    return program, partner, nominee


class TestEvaluationRecordShape:
    def test_evaluation_record_has_no_version_field(self, api):
        """PRD §2.5: "The `Evaluation` record is the exception: it carries only
        `id` and `created_at`, and both `updated_at` and `version` are absent,
        because evaluations are immutable — no update or delete endpoint exists
        for them."

        Design: Corner/entities/evaluation_record_has_no_version_field
        """
        _program, _partner, nominee = _setup_round_1_nominee()
        submit_evaluation(nominee["id"], 1, 90, 90, 90, "assessor-a")
        evals, meta = validate_paginated(
            api.list_evaluations(nominee["id"], _ADMIN)
        )
        assert meta["total_count"] == 1
        record = evals[0]
        assert_evaluation(record)
        assert record["nominee_id"] == nominee["id"]
        assert record["round_number"] == 1
        assert record["assessor_ref"] == "assessor-a"
        assert record["leadership"] == 90
        assert record["teamwork"] == 90
        assert record["group_presence"] == 90
        assert record["weighted_score"] == 900


class TestAdvancementBasics:
    def test_nominee_advance_from_nominated_to_round_1(self, api):
        """PRD §3.2: "The step from `NOMINATED` to `ROUND_1` has no
        preconditions and sets `current_round` to 1."

        Design: Corner/state_machines/nominee_advance_from_nominated_to_round_1
        """
        program, partner = setup_city_with_partner(quota=5)
        nominee = nominate(program, partner, "Nom One", by_nominator=True)
        resp = api.decide_nominee(nominee["id"], {"decision": "ADVANCE"}, _OFFICER)
        data = validate_success(resp)
        assert data["status"] == "ROUND_1"
        assert data["current_round"] == 1
        assert data["round_1_score"] is None, "no evaluations exist yet"
        assert_nominee(data)

    def test_nominee_waitlist_before_round_3_and_thin_evals_rejected(self, api):
        """PRD §3.2: "A `WAITLIST` decision exists only from `ROUND_3`: it
        requires at least 2 round-3 evaluations (otherwise
        `ERR_INSUFFICIENT_EVALUATIONS`) but imposes no cutoff, and moves the
        nominee to `WAITLISTED`."
        PRD §2.7: "lifecycle, transition, decision, withdrawal and completion
        calls being declared transitions from the current state
        (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/nominee_waitlist_before_round_3_and_thin_evals_rejected
        """
        _program, _partner, nominee = _setup_round_1_nominee()
        submit_evaluation(nominee["id"], 1, 90, 90, 90, "assessor-a")

        resp_w = api.decide_nominee(nominee["id"], {"decision": "WAITLIST"}, _OFFICER)
        validate_error(resp_w, ApiErrorId.ERR_INVALID_STATE)

        resp_a = api.decide_nominee(nominee["id"], {"decision": "ADVANCE"}, _OFFICER)
        validate_error(resp_a, ApiErrorId.ERR_INSUFFICIENT_EVALUATIONS)

        after = get_nominee(nominee["id"])
        assert after["status"] == "ROUND_1"
        assert after["round_1_score"] is None


class TestEvaluationGuards:
    def test_evaluation_duplicate_and_wrong_round_rejected(self, api):
        """PRD §3.2: "The server copies the caller's `X-User-ID` onto the record
        as `assessor_ref`, and the triple of `nominee_id`, `round_number` and
        `assessor_ref` is a uniqueness key: a second scorecard from the same
        assessor for the same nominee in the same round is rejected with
        `ERR_DUPLICATE_EVALUATION`."
        PRD §3.2: "The `round_number` must equal the nominee's `current_round`
        at submission ... a mismatch is rejected with
        `ERR_NOMINEE_NOT_IN_ROUND`."

        Design: Corner/validations/evaluation_duplicate_and_wrong_round_rejected
        """
        _program, _partner, nominee = _setup_round_1_nominee()
        submit_evaluation(nominee["id"], 1, 90, 90, 90, "assessor-a")

        dup = api.create_evaluation(
            create_evaluation_payload(nominee["id"], 1, 50, 50, 50),
            make_assessor_headers("assessor-a"),
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_EVALUATION)

        wrong_round = api.create_evaluation(
            create_evaluation_payload(nominee["id"], 2, 90, 90, 90),
            make_assessor_headers("assessor-b"),
        )
        validate_error(wrong_round, ApiErrorId.ERR_NOMINEE_NOT_IN_ROUND)

        evals, meta = validate_paginated(api.list_evaluations(nominee["id"], _ADMIN))
        assert meta["total_count"] == 1, "both rejected scorecards left no trace"


class TestWeightedScoreCap:
    def _setup_cap_pair(self):
        """One nominee in ROUND_1; assessor-a submits (100,100,39), assessor-b
        submits (100,100,40)."""
        _program, _partner, nominee = _setup_round_1_nominee()
        submit_round_evals_pair(nominee["id"], 1, (100, 100, 39), (100, 100, 40))
        return nominee

    def test_floor_cap_branch_caps_at_499(self, api):
        """PRD §3.2: "If any single dimension falls below 40, the stored
        `weighted_score` is capped: it becomes the smaller of the base score
        and 499. A dimension score of exactly 40 does not trigger the cap."

        Design: Difficulty/combinatorial_formula/evaluation_floor_cap_nonlinearity
        """
        nominee = self._setup_cap_pair()
        evals, _ = validate_paginated(
            api.list_evaluations(nominee["id"], _ADMIN, params={"round_number": 1})
        )
        by_assessor = {e["assessor_ref"]: e for e in evals}
        capped = by_assessor["assessor-a"]
        assert capped["weighted_score"] == 499, (
            "base 4*100+3*100+3*39 = 817, min dimension 39 < 40 -> min(817, 499) = 499"
        )

    def test_uncapped_branch_at_exactly_40_and_round_average(self, api):
        """PRD §3.2: "A dimension score of exactly 40 does not trigger the cap."
        PRD §3.2: "Once at least 2 evaluations exist, the round score becomes
        the round-half-up average of their `weighted_score` values, stored as
        an integer on the nominee as `round_1_score`, `round_2_score`, or
        `round_3_score`."

        Design: Difficulty/combinatorial_formula/evaluation_floor_cap_nonlinearity
        """
        nominee = self._setup_cap_pair()
        evals, _ = validate_paginated(
            api.list_evaluations(nominee["id"], _ADMIN, params={"round_number": 1})
        )
        by_assessor = {e["assessor_ref"]: e for e in evals}
        uncapped = by_assessor["assessor-b"]
        assert uncapped["weighted_score"] == 820, (
            "base 4*100+3*100+3*40 = 820, min dimension 40 >= 40 -> no cap"
        )
        after = get_nominee(nominee["id"])
        assert after["round_1_score"] == 660, (
            "round_half_up((499 + 820) / 2) = round_half_up(659.5) = 660"
        )


class TestRoundOneCutoff:
    def _nominee_with_scores(self, program, partner, name, triple):
        nominee = create_nominee_at_round_1(program, partner, name)
        submit_round_evals_pair(nominee["id"], 1, triple, triple)
        return nominee

    def test_score_exactly_600_advances(self, api):
        """PRD §3.2: "Every cutoff boundary is inclusive: a score exactly equal
        to the cutoff advances, while a score one point below the cutoff fails
        with `ERR_CUTOFF_NOT_MET`."
        PRD §3.2: "then `round_1_score` must be at least 600, otherwise
        `ERR_CUTOFF_NOT_MET`."

        Design: Difficulty/boundary_precision_check/round_one_cutoff_exactly_600
        """
        program, partner = setup_city_with_partner(quota=20)
        nominee = self._nominee_with_scores(program, partner, "Nom A", (60, 60, 60))
        resp = api.decide_nominee(nominee["id"], {"decision": "ADVANCE"}, _OFFICER)
        data = validate_success(resp)
        assert data["status"] == "ROUND_2", "score == 600 == cutoff advances (inclusive)"
        assert data["round_1_score"] == 600
        assert data["current_round"] == 2

    def test_score_599_fails_cutoff(self, api):
        """PRD §3.2: "Every cutoff boundary is inclusive: a score exactly equal
        to the cutoff advances, while a score one point below the cutoff fails
        with `ERR_CUTOFF_NOT_MET`."

        Design: Difficulty/boundary_precision_check/round_one_cutoff_exactly_600
        """
        program, partner = setup_city_with_partner(quota=20)
        nominee = self._nominee_with_scores(program, partner, "Nom B", (59, 60, 61))
        # 4*59 + 3*60 + 3*61 = 599, exactly one below the 600 cutoff.
        assert get_nominee(nominee["id"])["round_1_score"] == 599
        resp = api.decide_nominee(nominee["id"], {"decision": "ADVANCE"}, _OFFICER)
        validate_error(resp, ApiErrorId.ERR_CUTOFF_NOT_MET)
        assert get_nominee(nominee["id"])["status"] == "ROUND_1"


class TestWaitlistCycle:
    def test_waitlist_decision_moves_to_waitlisted(self, api):
        """PRD §3.2: "A `WAITLIST` decision exists only from `ROUND_3`: it
        requires at least 2 round-3 evaluations (otherwise
        `ERR_INSUFFICIENT_EVALUATIONS`) but imposes no cutoff, and moves the
        nominee to `WAITLISTED`. The `current_round` stays at 3 in both
        `SELECTED` and `WAITLISTED`."

        Design: Difficulty/non_linear_state_machine/nominee_waitlist_selection_cycle
        """
        program, partner = setup_city_with_partner(quota=20)
        nominee = create_waitlisted_nominee(program, partner, "Nom W")
        assert nominee["status"] == "WAITLISTED"
        assert nominee["current_round"] == 3, "current_round stays 3 in WAITLISTED"
        assert nominee["round_3_score"] == 900

    def test_waitlisted_nominee_advances_to_selected_without_gates(self, api):
        """PRD §3.2: "A waitlisted nominee returns to `SELECTED` either through
        a manual `ADVANCE` decision, which carries no preconditions from
        `WAITLISTED`, or through the system-driven waitlist promotion cascade
        of Section 3.5."

        Design: Difficulty/non_linear_state_machine/nominee_waitlist_selection_cycle
        """
        program, partner = setup_city_with_partner(quota=20)
        nominee = create_waitlisted_nominee(program, partner, "Nom W")
        resp = api.decide_nominee(nominee["id"], {"decision": "ADVANCE"}, _OFFICER)
        data = validate_success(resp)
        assert data["status"] == "SELECTED", "the WAITLISTED -> SELECTED edge completes the cycle"
        assert data["current_round"] == 3
        assert data["round_3_score"] == 900
