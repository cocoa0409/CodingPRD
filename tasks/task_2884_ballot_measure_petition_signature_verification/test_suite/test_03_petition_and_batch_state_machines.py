"""Non-linear state machines: revision cycles, fork-join diamonds, and a
conditional cascade that only fires on some branches.

The format-review loop that exhausts its statutory rounds, the sample ->
full-check diamond that must charge only the cost delta when the branches
rejoin, and the suspend -> reinstate cycle whose cascade depends on what the
circulator's batches have already reached.
"""
from test_helpers import (
    api_client,
    close_circulation_and_open_round,
    decide_format,
    file_batch_with_lines,
    file_petition,
    make_proponent_headers,
    open_followup_round,
    read_assignment,
    read_batch,
    read_circulator,
    read_line,
    read_petition,
    reinstate_circulator,
    setup_circulation_ready,
    submit_petition,
    suspend_circulator,
    register_standard,
    tally_round,
    validate_error,
    validate_open_sample,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.fixtures import set_clock

# The sampling standard of the design index: half the pool, never under two.
SAMPLING_STANDARD = {
    "jurisdiction_code": "SOS-POOL",
    "stratification_mode": "POOLED",
    "sample_pct_bps": 5000,
    "sample_min_count": 2,
}


class TestFormatReviewRevisionCycle:
    """DRAFT -> FORMAT_REVIEW -> FORMAT_REJECTED -> FORMAT_REVIEW, twice, and
    then no further."""

    def _draft(self):
        set_clock(CLOCK_EPOCH)
        standard = register_standard()
        return file_petition(standard["id"])

    def test_each_rejection_advances_the_review_round_and_reopens_the_draft(self):
        """Submitting does not consume a round; rejecting does, and a rejected
        petition may be resubmitted to start the next one.

        PRD §3.2: "Submitting the petition for review moves it from DRAFT to
        FORMAT_REVIEW, and the same act moves it from FORMAT_REJECTED back to
        FORMAT_REVIEW — this is the revision cycle ... A REJECT decision moves
        the petition from FORMAT_REVIEW to FORMAT_REJECTED and increments
        format_review_round by one."

        Design: Difficulty/non_linear_state_machine/petition_format_review_revision_cycle_exhausts_rounds
        """
        petition = self._draft()
        assert petition["status"] == "DRAFT"
        assert petition["format_review_round"] == 0

        submitted = submit_petition(petition["id"])
        assert submitted["status"] == "FORMAT_REVIEW"
        assert submitted["format_review_round"] == 0, "submission consumes no round"

        first_reject = decide_format(petition["id"], "REJECT")
        assert first_reject["status"] == "FORMAT_REJECTED"
        assert first_reject["format_review_round"] == 1

        resubmitted = submit_petition(petition["id"])
        assert resubmitted["status"] == "FORMAT_REVIEW"
        assert resubmitted["format_review_round"] == 1, (
            "the second cycle reuses the round the first rejection recorded"
        )

        second_reject = decide_format(petition["id"], "REJECT")
        assert second_reject["status"] == "FORMAT_REJECTED"
        assert second_reject["format_review_round"] == 2

    def test_a_third_submission_is_refused_once_the_rounds_are_exhausted(self):
        """With format_review_round already at MAX_FORMAT_REVIEW_ROUNDS the
        petition is frozen in FORMAT_REJECTED.

        PRD §3.2: "Because the counter is incremented by every format decision,
        whether the examiner approves or rejects, a committee gets two bites:
        submit, rejection, submit, and then the third submission is refused with
        ERR_FORMAT_REVIEW_ROUNDS_EXHAUSTED because format_review_round has
        reached two."

        Design: Difficulty/non_linear_state_machine/petition_format_review_revision_cycle_exhausts_rounds
        """
        petition = self._draft()
        submit_petition(petition["id"])
        decide_format(petition["id"], "REJECT")
        submit_petition(petition["id"])
        decide_format(petition["id"], "REJECT")

        validate_error(
            api_client.submit_petition(petition["id"], make_proponent_headers()),
            "ERR_FORMAT_REVIEW_ROUNDS_EXHAUSTED",
            409,
        )

        frozen = read_petition(petition["id"])
        assert frozen["status"] == "FORMAT_REJECTED"
        assert frozen["format_review_round"] == 2, (
            "the refused submission consumed nothing"
        )


class TestSignatureBatchForkJoinDiamond:
    """RECEIVED -> AFFIDAVIT_VERIFIED -> SAMPLED -> FULLY_CHECKED: the branch
    and the rejoin, where the cost ledger must move by a delta."""

    def _sampled_world(self):
        """One four-line ALPHA batch (VA3 not registered), a RANDOM_SAMPLE round
        that drew lines 1 and 3, both adjudicated, and that round tallied."""
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            standard_overrides=SAMPLING_STANDARD,
            counties=[("ALPHA", 20)],
            voters=[
                {"voter_id_number": "VA1", "registration_status": "ACTIVE"},
                {"voter_id_number": "VA2", "registration_status": "ACTIVE"},
                {"voter_id_number": "VA3", "registration_status": "INACTIVE"},
                {"voter_id_number": "VA4", "registration_status": "ACTIVE"},
            ],
        )
        file_batch_with_lines(world, ["VA1", "VA2", "VA3", "VA4"], batch_key="b1")
        close_circulation_and_open_round(world, round_type="RANDOM_SAMPLE")
        validate_open_sample(world)
        world["first_round"] = tally_round(world["round"]["id"])
        return world

    def test_the_sample_branch_charges_only_its_own_lines_and_demands_a_full_check(self):
        """A projection landing strictly between the two gates forks the
        petition into FULL_CHECK, having billed only the two sampled lines.

        PRD §3.6: "A batch's checked_signature_count is the number of its lines
        whose validation_status is neither PENDING nor INVALID_FORMAT_DEFECT ...
        The ledger then moves by a delta: the difference between the newly
        computed verification_cost_cents and the amount already stored on the
        batch is added both to the petition's verification_cost_accrued_cents and
        to the round's accrued_cost_cents."

        Design: Difficulty/non_linear_state_machine/signature_batch_fork_join_diamond_with_delta_cost
        """
        world = self._sampled_world()
        first = world["first_round"]

        assert first["sample_size"] == 2
        assert first["validity_rate_bps"] == 5000, "one of the two drawn lines is invalid"
        assert first["projected_valid_count"] == 2, "floor(4 * 5000 / 10000)"
        assert first["determination"] == "FULL_CHECK_REQUIRED"
        assert first["accrued_cost_cents"] == 10, "two examined lines only"

        batch = read_batch(world["batches"]["b1"]["batch"]["id"])
        assert batch["status"] == "SAMPLED"
        assert batch["checked_signature_count"] == 2
        assert batch["verification_cost_cents"] == 10

        petition = read_petition(world["petition"]["id"])
        assert petition["status"] == "FULL_CHECK"
        assert petition["verification_cost_accrued_cents"] == 10

    def test_the_full_check_pool_holds_only_the_lines_the_sample_left_pending(self):
        """The second branch of the diamond sees exactly the two lines the
        sample never consumed.

        PRD §3.5: "A line is eligible when its batch's status is one of
        AFFIDAVIT_VERIFIED, SAMPLED or FULLY_CHECKED; its own validation_status
        is still PENDING; and its validated_in_round_id is null, meaning no
        earlier round has already claimed it."

        Design: Difficulty/non_linear_state_machine/signature_batch_fork_join_diamond_with_delta_cost
        """
        world = self._sampled_world()
        first_round_id = world["first_round"]["id"]

        second = open_followup_round(world, round_type="FULL_CHECK")
        assert second["eligible_pool_size"] == 2, "lines 1 and 3 were consumed by the sample"
        assert second["sample_size"] == 2, "a FULL_CHECK examines the whole pool"

        lines = [read_line(line["id"]) for line in world["batches"]["b1"]["lines"]]
        assert lines[0]["validated_in_round_id"] == first_round_id
        assert lines[2]["validated_in_round_id"] == first_round_id
        assert lines[2]["validation_status"] == "INVALID_NOT_REGISTERED"

    def test_the_join_charges_the_cost_delta_and_never_the_whole_amount_again(self):
        """Re-examining the batch from SAMPLED to FULLY_CHECKED accrues 9 — the
        19-cent four-line amount less the 10 already stored.

        PRD §3.6: "At the join point — a batch re-examined from SAMPLED to
        FULLY_CHECKED — the ledger must move by that difference alone and never
        by the whole recomputed amount, or the county would be paid twice for the
        lines the sample already covered."

        Design: Difficulty/non_linear_state_machine/signature_batch_fork_join_diamond_with_delta_cost
        """
        world = self._sampled_world()

        second = open_followup_round(world, round_type="FULL_CHECK")
        validate_open_sample(world)
        closed = tally_round(second["id"])

        assert closed["accrued_cost_cents"] == 9, "19 newly computed less the 10 stored"
        assert closed["determination"] == "SUFFICIENT"

        batch = read_batch(world["batches"]["b1"]["batch"]["id"])
        assert batch["status"] == "FULLY_CHECKED"
        assert batch["checked_signature_count"] == 4
        assert batch["verification_cost_cents"] == 19

        petition = read_petition(world["petition"]["id"])
        assert petition["verification_cost_accrued_cents"] == 19, (
            "10 + 9, not 10 + 19"
        )
        assert petition["verified_valid_count"] == 3
        assert petition["projected_valid_count"] == 3
        assert petition["status"] == "PENDING_CERTIFICATION"


class TestCirculatorSuspendReinstateCycle:
    """REGISTERED -> SUSPENDED -> REGISTERED, whose cascade reaches assignments
    but deliberately stops short of filed batches."""

    def _world_with_verified_batch(self):
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            counties=[("ALPHA", 20)],
            voters=[{"voter_id_number": "VA1", "registration_status": "ACTIVE"}],
        )
        file_batch_with_lines(world, ["VA1"], batch_key="b1")
        return world

    def test_suspension_freezes_the_assignment_and_spares_every_filed_batch(self):
        """A discretionary suspension suspends the ACTIVE assignment and leaves
        the affidavit-verified batch and the petition's ledger alone.

        PRD §3.9: "Suspension applies to a circulator in REGISTERED, takes an
        optional reason, moves registration_status to SUSPENDED, and sets every
        ACTIVE assignment of that circulator to SUSPENDED — which blocks new
        batches against those assignments — while leaving every existing
        SignatureBatch untouched."

        Design: Difficulty/non_linear_state_machine/circulator_suspend_reinstate_cycle_with_conditional_cascade
        """
        world = self._world_with_verified_batch()
        circulator_id = world["circulators"]["c1"]["id"]

        suspended = suspend_circulator(circulator_id)
        assert suspended["registration_status"] == "SUSPENDED"
        assert suspended["misconduct_strike_count"] == 0, (
            "a discretionary suspension is not a proven strike"
        )

        assert read_assignment(world["assignments"]["c1"]["id"])["status"] == "SUSPENDED"

        batch = read_batch(world["batches"]["b1"]["batch"]["id"])
        assert batch["status"] == "AFFIDAVIT_VERIFIED"
        assert batch["accepted_raw_count"] == 1

        petition = read_petition(world["petition"]["id"])
        assert petition["accepted_raw_total"] == 1
        assert petition["voided_signature_count"] == 0

    def test_reinstatement_reactivates_the_assignment_and_disturbs_no_ledger(self):
        """Because no strike was recorded the cycle is reversible, and the
        signature ledger reads identically on both legs.

        PRD §3.9: "Reinstatement applies to a circulator in SUSPENDED, takes no
        body, moves registration_status back to REGISTERED and returns every
        SUSPENDED assignment to ACTIVE ... A fraud-driven suspension is
        consequently permanent in practice, while a discretionary one is
        reversible."

        Design: Difficulty/non_linear_state_machine/circulator_suspend_reinstate_cycle_with_conditional_cascade
        """
        world = self._world_with_verified_batch()
        circulator_id = world["circulators"]["c1"]["id"]

        suspend_circulator(circulator_id)
        reinstated = reinstate_circulator(circulator_id)
        assert reinstated["registration_status"] == "REGISTERED"
        assert reinstated["misconduct_strike_count"] == 0

        assert read_assignment(world["assignments"]["c1"]["id"])["status"] == "ACTIVE"
        assert read_circulator(circulator_id)["registration_status"] == "REGISTERED"

        batch = read_batch(world["batches"]["b1"]["batch"]["id"])
        assert batch["status"] == "AFFIDAVIT_VERIFIED"

        petition = read_petition(world["petition"]["id"])
        assert petition["accepted_raw_total"] == 1
        assert petition["voided_signature_count"] == 0
