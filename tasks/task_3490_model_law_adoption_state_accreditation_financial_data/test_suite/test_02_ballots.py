"""Member ballots: adoption rule boundaries, ABSTAIN semantics, duplicate and
suspension guards, ownership, and the failure-driven revision cycle."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    constants,
    factories,
    fixtures,
    make_state_regulator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

STAFF = TEST_USERS["association_staff_headers"]


def _list_ballots(api, act_id):
    data, _meta = validate_paginated(api.list_ballots(act_id, STAFF))
    return data


class TestBallots:
    def test_ballot_failure_revision_cycle(self, api):
        """PRD §3.1: "On a failure the act loops back from `BALLOTING` to `DRAFTING` for revision: every `CAST` ballot of the act cascades to `VOID` and is excluded from both counters thereafter, the counters themselves reset to zero, and the act's `version` increments."
        PRD §3.1: "each additional draft takes the next sequential number — one more than the count of the act's prior drafts in any status — and leaves the act in `EXPOSURE_OPEN`"
        PRD §3.1: "On a pass the act moves from `BALLOTING` to `ADOPTED`, its counters are recomputed from the `CAST` ballots, and its `version` increments."

        Design: Difficulty/non_linear_state_machine/model_act_ballot_failure_revision_cycle
        """
        bundle = fixtures.create_act_in_balloting(
            api, states=("CA", "NY"), model_code="MDL-700", version_label="v1",
            title="Model Guaranty Act",
        )
        act_id = bundle.act["id"]
        states = bundle.states
        # Round 1: 1 YEA, 1 NAY — quorum 2 met, but 1 < ceil(2/3 x 2) == 2.
        fixtures.cast_ballot(api, act_id, states["CA"], "YEA")
        fixtures.cast_ballot(api, act_id, states["NY"], "NAY")
        failed = validate_success(api.close_ballot(act_id, STAFF))
        assert failed["status"] == "DRAFTING", "failed supermajority loops to DRAFTING"
        assert failed["votes_cast"] == 0, "counters reset to zero on failure"
        assert failed["favorable_votes"] == 0
        ballots = _list_ballots(api, act_id)
        assert len(ballots) == 2
        assert all(b["status"] == "VOID" for b in ballots), (
            "every CAST ballot of the failed round becomes VOID"
        )
        # Round 2: a second exposure/ballot round reaches ADOPTED.
        draft2 = fixtures.open_exposure_draft(
            api, act_id,
            start=constants.SECOND_EXPOSURE_START,
            end=constants.SECOND_EXPOSURE_END,
        )
        assert draft2["exposure_number"] == 2
        fixtures.close_exposure_draft(
            api, draft2["id"], window_end=constants.SECOND_EXPOSURE_END
        )
        fixtures.cast_ballot(api, act_id, states["CA"], "YEA")
        fixtures.cast_ballot(api, act_id, states["NY"], "YEA")
        adopted = validate_success(api.close_ballot(act_id, STAFF))
        assert adopted["status"] == "ADOPTED"
        assert adopted["votes_cast"] == 2
        assert adopted["favorable_votes"] == 2

    def test_ballot_supermajority_count_boundary(self, api):
        """PRD §3.1: "The required favorable count is the smallest whole number that is at least two-thirds of `votes_cast`."
        PRD §3.1: "The adoption passes if and only if `votes_cast` is at least the quorum and `favorable_votes` is at least the required favorable count; both thresholds are computed with integer arithmetic, rounding up at exactly those two points."
        PRD §3.1: "A successful ballot is recorded with status `CAST` and a `cast_at` read from the logical clock; the act's `votes_cast` and `favorable_votes` are recomputed and the act's `version` increments."

        Design: Difficulty/boundary_precision_check/ballot_supermajority_count_boundary
        """
        bundle = fixtures.create_act_in_balloting(
            api, states=("CA", "NV", "OR", "WA", "AZ"),
            model_code="MDL-702", version_label="v1",
        )
        act_id = bundle.act["id"]
        states = bundle.states
        for code, vote in (("CA", "YEA"), ("NV", "YEA"), ("OR", "YEA"),
                           ("WA", "NAY"), ("AZ", "NAY")):
            fixtures.cast_ballot(api, act_id, states[code], vote)
        live = fixtures.read_model_act(api, act_id)
        assert live["votes_cast"] == 5
        assert live["favorable_votes"] == 3
        # Quorum (3 of 5 eligible) is met; 3 YEA is below ceil(2/3 x 5) == 4.
        closed = validate_success(api.close_ballot(act_id, STAFF))
        assert closed["status"] == "DRAFTING", (
            "3 favorable of 5 cast fails the two-thirds bar (4 required)"
        )
        assert closed["votes_cast"] == 0, "counters reset to zero on failure"
        assert closed["favorable_votes"] == 0

    def test_ballot_quorum_exact_boundary(self, api):
        """PRD §3.1: "The eligible electorate is the count of states whose `accreditation_status` is `ACCREDITED` or `PROBATION`; `SUSPENDED` states do not count. Quorum is the smallest whole number that is at least 60 percent of that eligible count."
        PRD §3.1: "The adoption passes if and only if `votes_cast` is at least the quorum and `favorable_votes` is at least the required favorable count"

        Design: Corner/calculations/ballot_quorum_exact_boundary
        """
        bundle = fixtures.create_act_in_balloting(
            api, states=("CA", "NV", "OR", "WA", "AZ"),
            model_code="MDL-820", version_label="v1",
        )
        act_id = bundle.act["id"]
        states = bundle.states
        # Exactly quorum: ceil(0.60 x 5) == 3 votes cast, all YEA.
        for code in ("CA", "NV", "OR"):
            fixtures.cast_ballot(api, act_id, states[code], "YEA")
        closed = validate_success(api.close_ballot(act_id, STAFF))
        assert closed["votes_cast"] == 3
        assert closed["favorable_votes"] == 3
        assert closed["status"] == "ADOPTED", (
            "3 >= quorum 3 and 3 >= ceil(2/3 x 3) == 2, so the act is adopted"
        )

    def test_ballot_abstain_counts_for_quorum_not_favorable(self, api):
        """PRD §3.1: "An `ABSTAIN` ballot counts toward `votes_cast` but never toward `favorable_votes`, which counts only `CAST` ballots whose vote is `YEA`."
        PRD §3.1: "On a failure the act loops back from `BALLOTING` to `DRAFTING` for revision: every `CAST` ballot of the act cascades to `VOID` and is excluded from both counters thereafter, the counters themselves reset to zero, and the act's `version` increments."

        Design: Corner/calculations/ballot_abstain_counts_for_quorum_not_favorable
        """
        bundle = fixtures.create_act_in_balloting(
            api, states=("CA", "NV", "OR", "WA", "AZ"),
            model_code="MDL-821", version_label="v1",
        )
        act_id = bundle.act["id"]
        states = bundle.states
        for code, vote in (("CA", "YEA"), ("NV", "YEA"), ("OR", "NAY"),
                           ("WA", "NAY"), ("AZ", "ABSTAIN")):
            fixtures.cast_ballot(api, act_id, states[code], vote)
        live = fixtures.read_model_act(api, act_id)
        assert live["votes_cast"] == 5, "ABSTAIN counts toward votes_cast"
        assert live["favorable_votes"] == 2, "ABSTAIN never counts as favorable"
        # Quorum met (5 >= 3) but 2 < ceil(2/3 x 5) == 4, so the ballot fails.
        closed = validate_success(api.close_ballot(act_id, STAFF))
        assert closed["status"] == "DRAFTING"
        ballots = _list_ballots(api, act_id)
        assert len(ballots) == 5
        assert all(b["status"] == "VOID" for b in ballots)

    def test_duplicate_ballot_rejected(self, api):
        """PRD §3.1: "the state must not already hold a `CAST` ballot on this act (`ERR_DUPLICATE_BALLOT`, 409)."
        PRD §3.1: "A successful ballot is recorded with status `CAST` and a `cast_at` read from the logical clock; the act's `votes_cast` and `favorable_votes` are recomputed and the act's `version` increments."

        Design: Corner/validations/duplicate_ballot_rejected
        """
        bundle = fixtures.create_act_in_balloting(
            api, states=("CA",), model_code="MDL-831", version_label="v1"
        )
        act_id = bundle.act["id"]
        state = bundle.states["CA"]
        fixtures.cast_ballot(api, act_id, state, "YEA")
        resp = api.cast_ballot(
            act_id,
            factories.ballot_payload(state_code="CA", vote="NAY"),
            make_state_regulator_headers(state["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BALLOT)
        act = fixtures.read_model_act(api, act_id)
        assert act["votes_cast"] == 1, "the rejected ballot must not be counted"
        assert act["favorable_votes"] == 1

    def test_voter_suspended_ballot_rejected(self, api):
        """PRD §3.1: "the voting state's `accreditation_status` must not be `SUSPENDED` (`ERR_VOTING_STATE_SUSPENDED`, 422)"
        PRD §3.3: "a `SUSPENDED` state may not cast ballots (§3.1) and may not issue producer licenses (§3.6)."

        Design: Corner/validations/voter_suspended_ballot_rejected
        """
        state = fixtures.create_state(api, code="CA")
        state = fixtures.drive_state_to(api, state["id"], "SUSPENDED")
        assert state["accreditation_status"] == "SUSPENDED"
        bundle = fixtures.create_act_in_balloting(
            api, state_map={"CA": state}, model_code="MDL-834", version_label="v1"
        )
        resp = api.cast_ballot(
            bundle.act["id"],
            factories.ballot_payload(state_code="CA", vote="YEA"),
            make_state_regulator_headers(state["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VOTING_STATE_SUSPENDED)
        assert _list_ballots(api, bundle.act["id"]) == []

    def test_rbac_wrong_state_ballot_forbidden(self, api):
        """PRD §3.1: "A `StateRegulator` casts the ballot of its own state — the supplied `state_code` must equal the acting regulator's State `code`, or the request fails ownership with `ERR_FORBIDDEN`"

        Design: Corner/rbac/rbac_wrong_state_ballot_forbidden
        """
        bundle = fixtures.create_act_in_balloting(
            api, states=("CA", "NY"), model_code="MDL-851", version_label="v1"
        )
        act_id = bundle.act["id"]
        resp = api.cast_ballot(
            act_id,
            factories.ballot_payload(state_code="NY", vote="YEA"),
            make_state_regulator_headers(bundle.states["CA"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert _list_ballots(api, act_id) == []
