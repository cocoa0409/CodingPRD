"""Scholar lifecycle: two state axes, training records, withdrawal cascades
and cohort completion (PRD §3.7, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_offer,
    api_client,
    assert_scholar,
    assert_training_record,
    create_internship_payload,
    create_offer,
    create_selected_nominee,
    get_cohort,
    get_college,
    get_offer,
    get_scholar,
    get_scholar_for_nominee,
    lifecycle_payload,
    list_training_records,
    scholar_lifecycle,
    setup_cohort_foundation,
    setup_matriculated_cohort,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["program_admin_headers"]
_DIRECTOR = TEST_USERS["career_director_headers"]


def _scholar_in_pre_collegiate():
    """FORMING cohort with one accepted offer; returns (ctx, nominee, offer, scholar)."""
    ctx = setup_cohort_foundation(cohort_size=3)
    nominee = create_selected_nominee(ctx["program"], ctx["partner"], "Nom One")
    offer = create_offer(nominee["id"], ctx["cohort"]["id"])
    accept_offer(offer)
    scholar = get_scholar_for_nominee(nominee["id"])
    return ctx, nominee, offer, scholar


class TestLifecycleGates:
    def test_lifecycle_cannot_matriculate_scholar_directly(self, api):
        """PRD §3.7: "`PRE_COLLEGIATE` → `MATRICULATED` happens only inside
        cohort matriculation, under the training gate of Section 3.6; a
        lifecycle call requesting `MATRICULATED` is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/lifecycle_cannot_matriculate_scholar_directly
        """
        _ctx, _n, _o, scholar = _scholar_in_pre_collegiate()
        resp = api.scholar_lifecycle(
            scholar["id"], lifecycle_payload(to_enrollment_status="MATRICULATED"), _ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_scholar(scholar["id"])["enrollment_status"] == "PRE_COLLEGIATE"

    def test_lifecycle_cannot_skip_retained_to_graduated(self, api):
        """PRD §3.7: "`RETAINED` → `GRADUATED`, by a `ProgramAdmin`:
        `alumni_network_access` becomes true, outcome rates change on next
        read, and the completion check runs."
        PRD §2.7: "lifecycle, transition, decision, withdrawal and completion
        calls being declared transitions from the current state
        (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/lifecycle_cannot_skip_retained_to_graduated
        """
        ctx = setup_matriculated_cohort(trained_count=1)
        s1 = ctx["scholars"][0]
        assert s1["enrollment_status"] == "MATRICULATED"

        skip = api.scholar_lifecycle(
            s1["id"], lifecycle_payload(to_enrollment_status="GRADUATED"), _ADMIN
        )
        validate_error(skip, ApiErrorId.ERR_INVALID_STATE)

        retained = scholar_lifecycle(s1["id"], to_enrollment_status="RETAINED")
        assert retained["enrollment_status"] == "RETAINED"
        graduated = scholar_lifecycle(s1["id"], to_enrollment_status="GRADUATED")
        assert graduated["enrollment_status"] == "GRADUATED"
        assert graduated["alumni_network_access"] is True, (
            "graduation opens alumni network access"
        )


class TestAcceptSideEffects:
    def test_accept_creates_scholar_records_and_double_complete_rejected(self, api):
        """PRD §3.5: "A new `Scholar` is created, bound to the offer's cohort
        and nominee, with `enrollment_status` `PRE_COLLEGIATE`, `standing`
        `GOOD_STANDING`, and `ever_matriculated` false. Eight training records
        are auto-created for the new scholar, module codes `T1` through `T8`,
        all in `NOT_STARTED` status."
        PRD §3.7: "A `ProgramAdmin` marks a module complete, which moves the
        record to `COMPLETED`, stamps `completed_at` with the current
        logical-clock instant, and raises the scholar's
        `training_completed_count` by one."
        PRD §2.3: "that listing sorts by `module_code` ascending instead."

        Design: Corner/state_machines/accept_creates_scholar_records_and_double_complete_rejected
        """
        _ctx, _n, _o, scholar = _scholar_in_pre_collegiate()
        assert scholar["enrollment_status"] == "PRE_COLLEGIATE"
        assert scholar["standing"] == "GOOD_STANDING"
        assert scholar["ever_matriculated"] is False

        records = list_training_records(scholar["id"])
        assert len(records) == 8
        assert [r["module_code"] for r in records] == [
            f"T{i}" for i in range(1, 9)
        ], "module_code ascending T1..T8"
        assert all(r["status"] == "NOT_STARTED" for r in records)

        done = validate_success(api.complete_training_record(records[0]["id"], _ADMIN))
        assert done["status"] == "COMPLETED"
        assert done["completed_at"] is not None, "stamped with the logical clock"
        assert_training_record(done)
        assert get_scholar(scholar["id"])["training_completed_count"] == 1

        again = api.complete_training_record(records[0]["id"], _ADMIN)
        validate_error(again, ApiErrorId.ERR_INVALID_STATE)


class TestTerminalAxesFreeze:
    def test_internship_terminal_and_standing_frozen_after_terminal_enrollment(self, api):
        """PRD §3.8: "`COMPLETED` and `TERMINATED` are terminal."
        PRD §3.7: "The two axes evolve independently, with one exception:
        `standing` freezes once `enrollment_status` is terminal, so no standing
        change is possible for a scholar who has graduated, withdrawn, or been
        dismissed."
        PRD §3.7: "Each requires that the scholar's `enrollment_status` is not
        terminal; attempting either against a `GRADUATED`, `WITHDRAWN`, or
        `DISMISSED` scholar is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/internship_terminal_and_standing_frozen_after_terminal_enrollment
        """
        ctx = setup_matriculated_cohort(trained_count=1)
        s1 = ctx["scholars"][0]

        created = validate_success(
            api.create_internship(
                create_internship_payload(s1["id"], "Acme Corp", "2028-01-10", "2028-06-30"),
                _DIRECTOR,
            ),
            201,
        )
        terminated = validate_success(
            api.transition_internship(created["id"], {"to_status": "TERMINATED"}, _DIRECTOR)
        )
        assert terminated["status"] == "TERMINATED"
        revive = api.transition_internship(created["id"], {"to_status": "CONFIRMED"}, _DIRECTOR)
        validate_error(revive, ApiErrorId.ERR_INVALID_STATE)

        scholar_lifecycle(s1["id"], to_enrollment_status="RETAINED")
        scholar_lifecycle(s1["id"], to_enrollment_status="GRADUATED")
        frozen = api.scholar_lifecycle(
            s1["id"], lifecycle_payload(to_standing="PROBATION"), _ADMIN
        )
        validate_error(frozen, ApiErrorId.ERR_INVALID_STATE)
        after = get_scholar(s1["id"])
        assert after["enrollment_status"] == "GRADUATED"
        assert after["standing"] == "GOOD_STANDING", "the standing axis froze"


class TestAcceptWithdrawSeatInvariant:
    def test_accept_raises_committed_seats(self, api):
        """PRD §3.4: "The ledger's invariant is that `seats_committed` equals
        the count of `ACCEPTED` offers at all times — so an acceptance
        immediately followed by the scholar's pre-collegiate withdrawal nets
        to zero change, the acceptance adding one and the revocation
        subtracting one."

        Design: Difficulty/compensating_invariant/accept_then_withdraw_restores_committed_seats
        """
        ctx, _n, offer, _s = _scholar_in_pre_collegiate()
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["seats_committed"] == 1, (
            "the forward action adds one committed seat (offer ACCEPTED)"
        )
        assert get_offer(offer["id"])["status"] == "ACCEPTED"

    def test_withdrawal_returns_committed_seats_to_zero(self, api):
        """PRD §3.4: "an acceptance immediately followed by the scholar's
        pre-collegiate withdrawal nets to zero change, the acceptance adding
        one and the revocation subtracting one."
        PRD §3.7: "`PRE_COLLEGIATE` → `WITHDRAWN`, by the scholar themself or
        a `ProgramAdmin`".

        Design: Difficulty/compensating_invariant/accept_then_withdraw_restores_committed_seats
        """
        ctx, _n, offer, scholar = _scholar_in_pre_collegiate()
        scholar_lifecycle(scholar["id"], to_enrollment_status="WITHDRAWN", as_self=True)

        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["seats_committed"] == 0, "the compensating revocation subtracts one"
        assert cohort["offers_outstanding"] == 0
        assert cohort["status"] == "FORMING"
        assert get_offer(offer["id"])["status"] == "REVOKED"
        assert get_scholar(scholar["id"])["enrollment_status"] == "WITHDRAWN"


class TestCohortCompletionCascade:
    def _setup_one_graduated_one_matriculated(self):
        """Cohort of 3 matriculated: s1,s2 were trained (MATRICULATED), s3
        withdrawn by the gate; s1 then RETAINED -> GRADUATED. s2 still
        MATRICULATED, so the cohort has not completed yet."""
        ctx = setup_matriculated_cohort(trained_count=2)
        s1, s2 = ctx["scholars"][0], ctx["scholars"][1]
        scholar_lifecycle(s1["id"], to_enrollment_status="RETAINED")
        scholar_lifecycle(s1["id"], to_enrollment_status="GRADUATED")
        assert get_cohort(ctx["cohort"]["id"])["status"] == "MATRICULATED", (
            "s2 still non-terminal, so the cohort has not completed"
        )
        return ctx, s1, s2

    def test_last_terminal_scholar_completes_cohort_and_agreement(self, api):
        """PRD §3.7: "when the count of the cohort's scholars whose
        `enrollment_status` is non-terminal reaches zero — meaning every
        scholar is `GRADUATED`, `WITHDRAWN`, or `DISMISSED` — the cohort moves
        from `MATRICULATED` to `COMPLETED`, its agreement moves from `ACTIVE`
        to `FULFILLED`, and the partner college's census outcome rates are
        recomputed".

        Design: Difficulty/transitive_cascade/cohort_completion_cascade_to_college_probation
        """
        ctx, _s1, s2 = self._setup_one_graduated_one_matriculated()
        scholar_lifecycle(s2["id"], to_enrollment_status="WITHDRAWN")

        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["status"] == "COMPLETED", (
            "the last non-terminal scholar reaching WITHDRAWN completed the cohort"
        )
        agreements, _ = validate_paginated(
            api.list_college_agreements(
                ctx["college"]["id"], _ADMIN, params={"status": "FULFILLED"}
            )
        )
        assert any(a["id"] == ctx["agreement"]["id"] for a in agreements), (
            "link 2: the cohort's agreement became FULFILLED"
        )

    def test_completion_flips_college_to_probation(self, api):
        """PRD §3.9: "An `ACTIVE` college whose census retention falls below
        7000 basis points moves to `PROBATION` — a census retention of 6999
        sends the college to `PROBATION`, while exactly 7000 leaves it
        `ACTIVE`."
        PRD §3.9: "The census variant counts only scholars whose cohort has
        reached `COMPLETED`; it is the authoritative variant, driving both
        standing derivation and renewal decisions."

        Design: Difficulty/transitive_cascade/cohort_completion_cascade_to_college_probation
        """
        ctx, _s1, s2 = self._setup_one_graduated_one_matriculated()
        scholar_lifecycle(s2["id"], to_enrollment_status="WITHDRAWN")

        outcomes = validate_success(
            api.get_college_outcomes(ctx["college"]["id"], _ADMIN)
        )
        # Census set: s1 GRADUATED + s2 WITHDRAWN (s3 never matriculated,
        # excluded) -> retention round_half_up(10000 * 1 / 2) == 5000.
        assert outcomes["retention_bps_census"] == 5000
        assert get_college(ctx["college"]["id"])["status"] == "PROBATION", (
            "link 3: census retention 5000 < 7000 floor flips the college"
        )
