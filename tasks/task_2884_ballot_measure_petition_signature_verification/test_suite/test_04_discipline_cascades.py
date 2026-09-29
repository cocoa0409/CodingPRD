"""Transitive cascades that travel four levels from one write.

Revoking a circulator reaches assignment, batch, line and petition ledger;
substantiating a fraud referral reaches the named batch, its lines, the
circulator's credibility and the petition's counters — but stops at SUSPENDED
rather than TERMINATED on the assignment.
"""
from test_helpers import (
    SECOND_EXAMINER_USER_ID,
    THIRD_EXAMINER_USER_ID,
    adjudicate_referral,
    file_batch_with_lines,
    make_examiner_headers,
    open_referral,
    read_assignment,
    read_batch,
    read_circulator,
    read_line,
    read_petition,
    refer_referral_to_ag,
    revoke_circulator,
    run_verification_round,
    setup_circulation_ready,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.fixtures import set_clock

TWO_ACTIVE_VOTERS = [
    {"voter_id_number": "VA1", "registration_status": "ACTIVE"},
    {"voter_id_number": "VA2", "registration_status": "ACTIVE"},
]


def _sampled_petition():
    """A petition whose single two-line ALPHA batch has been census-sampled and
    tallied: batch SAMPLED at 10 cents, petition FULL_CHECK."""
    set_clock(CLOCK_EPOCH)
    world = setup_circulation_ready(counties=[("ALPHA", 20)], voters=TWO_ACTIVE_VOTERS)
    file_batch_with_lines(world, ["VA1", "VA2"], batch_key="b1")
    closed = run_verification_round(world)
    assert closed["determination"] == "FULL_CHECK_REQUIRED"
    assert closed["accrued_cost_cents"] == 10
    assert read_batch(world["batches"]["b1"]["batch"]["id"])["status"] == "SAMPLED"
    assert read_petition(world["petition"]["id"])["status"] == "FULL_CHECK"
    return world


class TestCirculatorRevocationCascade:
    """One revoke, four levels: assignment, batch, line, petition."""

    def test_revocation_terminates_the_assignment_and_invalidates_its_batches(self):
        """The first two levels of the cascade, with the batch recording the
        status it held so the invalidation is auditable.

        PRD §3.9: "Revocation applies from PENDING_TRAINING, TRAINED, REGISTERED
        or SUSPENDED — anything but the terminal REVOKED — takes an optional
        reason, and cascades four levels with a fifth level of derived-field
        reconciliation. It moves registration_status to the terminal REVOKED; it
        terminates every assignment not already TERMINATED; it sets every
        SignatureBatch of those assignments whose status is not already
        REJECTED_FORMAT or INVALIDATED to INVALIDATED, recording each batch's
        status_before_invalidation."

        Design: Difficulty/transitive_cascade/circulator_revoke_cascades_four_levels_to_petition_ledger
        """
        world = _sampled_petition()

        revoked = revoke_circulator(world["circulators"]["c1"]["id"])
        assert revoked["registration_status"] == "REVOKED"
        assert revoked["misconduct_strike_count"] == 0, (
            "administrative revocation is not a proven misconduct strike"
        )

        assert read_assignment(world["assignments"]["c1"]["id"])["status"] == "TERMINATED"

        batch = read_batch(world["batches"]["b1"]["batch"]["id"])
        assert batch["status"] == "INVALIDATED"
        assert batch["status_before_invalidation"] == "SAMPLED"

    def test_revocation_voids_every_line_and_zeroes_the_petition_ledgers(self):
        """The last two levels: each line records what it was, and every derived
        petition counter is recomputed rather than patched.

        PRD §3.9: "it sets every line of those batches not already VOIDED to
        VOIDED with a void_reason of CIRCULATOR_REVOKED, recording each line's
        status_before_void; and it recomputes accepted_raw_total,
        projected_valid_count, verified_valid_count, voided_signature_count,
        verification_cost_accrued_cents and qualifying_county_count on every
        affected petition."

        Design: Difficulty/transitive_cascade/circulator_revoke_cascades_four_levels_to_petition_ledger
        """
        world = _sampled_petition()

        revoke_circulator(world["circulators"]["c1"]["id"])

        lines = [read_line(line["id"]) for line in world["batches"]["b1"]["lines"]]
        for line in lines:
            assert line["validation_status"] == "VOIDED"
            assert line["status_before_void"] == "VALID"
            assert line["void_reason"] == "CIRCULATOR_REVOKED"

        petition = read_petition(world["petition"]["id"])
        assert petition["accepted_raw_total"] == 0
        assert petition["raw_signature_count"] == 0, (
            "an INVALIDATED batch drops out of the raw sum as well"
        )
        assert petition["voided_signature_count"] == 2
        assert petition["verification_cost_accrued_cents"] == 0
        assert petition["projected_valid_count"] == 0
        assert petition["qualifying_county_count"] == 0


class TestFraudSubstantiationCascade:
    """One SUBSTANTIATED finding, four levels — and the assignment stops at
    SUSPENDED, not TERMINATED."""

    def _referred_world(self):
        """The sampled petition plus an OPENED FORGED_SIGNATURES referral naming
        the petition, the circulator and the batch, opened by a second
        examiner."""
        world = _sampled_petition()
        world["referral"] = open_referral(
            world["petition"]["id"],
            world["circulators"]["c1"]["id"],
            batch_id=world["batches"]["b1"]["batch"]["id"],
            referral_type="FORGED_SIGNATURES",
            opened_by=SECOND_EXAMINER_USER_ID,
        )
        assert world["referral"]["status"] == "OPENED"
        return world

    def test_substantiation_invalidates_the_named_batch_and_voids_its_lines(self):
        """Because the referral named a batch_id, that batch and its lines are
        struck with a fraud-specific void reason.

        PRD §3.9: "A SUBSTANTIATED finding cascades four levels. When the
        referral named a batch_id, that batch is set to INVALIDATED and every one
        of its lines not already VOIDED is set to VOIDED with a void_reason of
        FRAUD_SUBSTANTIATED, with the number of lines so voided recorded on the
        referral as voided_signature_count."

        Design: Difficulty/transitive_cascade/fraud_substantiation_cascades_to_batch_and_assignment
        """
        world = self._referred_world()

        referred = refer_referral_to_ag(
            world["referral"]["id"], examiner_id=SECOND_EXAMINER_USER_ID
        )
        assert referred["status"] == "REFERRED_TO_AG"

        adjudicated = adjudicate_referral(
            world["referral"]["id"],
            "SUBSTANTIATED",
            adjudicator_headers=make_examiner_headers(THIRD_EXAMINER_USER_ID),
        )
        assert adjudicated["status"] == "SUBSTANTIATED"
        assert adjudicated["voided_signature_count"] == 2

        batch = read_batch(world["batches"]["b1"]["batch"]["id"])
        assert batch["status"] == "INVALIDATED"
        assert batch["status_before_invalidation"] == "SAMPLED"

        lines = [read_line(line["id"]) for line in world["batches"]["b1"]["lines"]]
        for line in lines:
            assert line["validation_status"] == "VOIDED"
            assert line["void_reason"] == "FRAUD_SUBSTANTIATED"
        assert lines[0]["status_before_void"] == "VALID"

        petition = read_petition(world["petition"]["id"])
        assert petition["accepted_raw_total"] == 0
        assert petition["voided_signature_count"] == 2
        assert petition["verification_cost_accrued_cents"] == 0

    def test_substantiation_suspends_the_circulator_and_only_suspends_its_assignment(self):
        """A single strike hits the suspension threshold, and the assignment is
        suspended — not terminated, which is revocation's reach alone.

        PRD §3.9: "The circulator's misconduct_strike_count is incremented and
        its credibility_score_bps recomputed under the adjudicated variant. Once
        misconduct_strike_count reaches the suspension threshold of one, the
        circulator is moved to SUSPENDED, which in turn sets each of its ACTIVE
        assignments to SUSPENDED."

        Design: Difficulty/transitive_cascade/fraud_substantiation_cascades_to_batch_and_assignment
        """
        world = self._referred_world()
        circulator_id = world["circulators"]["c1"]["id"]

        refer_referral_to_ag(world["referral"]["id"], examiner_id=SECOND_EXAMINER_USER_ID)
        adjudicate_referral(
            world["referral"]["id"],
            "SUBSTANTIATED",
            adjudicator_headers=make_examiner_headers(THIRD_EXAMINER_USER_ID),
        )

        circulator = read_circulator(circulator_id)
        assert circulator["misconduct_strike_count"] == 1
        assert circulator["registration_status"] == "SUSPENDED"
        assert circulator["credibility_score_bps"] == 8000, (
            "both lines still score on their status_before_void of VALID, so the "
            "invalid rate is 0 and only the 2000-bps strike penalty applies"
        )

        assert read_assignment(world["assignments"]["c1"]["id"])["status"] == "SUSPENDED"
