"""Compensating operations measured against the ledgers they must conserve.

Invalidate/reinstate on a batch must return the signature ledger to identical
values; voiding a round must return the cost ledger to identical values and put
every line back in the eligible pool.
"""
from test_helpers import (
    api_client,
    assert_cost_ledger_restored,
    assert_signature_ledger_restored,
    file_batch_with_lines,
    invalidate_batch,
    make_examiner_headers,
    open_followup_round,
    read_batch,
    read_line,
    read_petition,
    read_round,
    reinstate_batch,
    run_verification_round,
    setup_circulation_ready,
    validate_success,
    void_round,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.fixtures import set_clock

LEDGER_VOTERS = [
    {"voter_id_number": "VA1", "registration_status": "ACTIVE"},
    {"voter_id_number": "VA2", "registration_status": "ACTIVE"},
    {"voter_id_number": "VA3", "registration_status": "ACTIVE"},
    {"voter_id_number": "VA4", "registration_status": "INACTIVE"},
]


def _fully_checked_petition():
    """Two two-line ALPHA batches, fully checked in one FULL_CHECK round: b1
    both VALID, b2 one VALID and one INVALID_NOT_REGISTERED. accepted 4,
    verified 3, cost 20, petition PENDING_CERTIFICATION."""
    set_clock(CLOCK_EPOCH)
    world = setup_circulation_ready(counties=[("ALPHA", 20)], voters=LEDGER_VOTERS)
    file_batch_with_lines(world, ["VA1", "VA2"], batch_key="b1")
    file_batch_with_lines(world, ["VA3", "VA4"], batch_key="b2")
    closed = run_verification_round(world, round_type="FULL_CHECK")
    assert closed["determination"] == "SUFFICIENT"
    assert closed["accrued_cost_cents"] == 20
    petition = read_petition(world["petition"]["id"])
    assert petition["accepted_raw_total"] == 4
    assert petition["verified_valid_count"] == 3
    assert petition["verification_cost_accrued_cents"] == 20
    assert petition["status"] == "PENDING_CERTIFICATION"
    world["closed_round"] = closed
    return world


class TestBatchInvalidateReinstateConservesSignatures:
    """`accepted_raw_total` is the conserved quantity, and restoration is
    verbatim rather than recomputed."""

    def test_invalidating_a_batch_moves_the_ledgers_by_its_stored_amounts(self):
        """The batch records what it was, its lines record what they were, and
        every petition counter drops by that batch's contribution alone.

        PRD §2.10: "Restoration is verbatim, not approximate. A batch records the
        status it held immediately before invalidation in
        status_before_invalidation and each of its lines records the validation
        outcome it held immediately before voiding in status_before_void."

        Design: Difficulty/compensating_invariant/batch_invalidate_reinstate_preserves_signature_ledger
        """
        world = _fully_checked_petition()
        batch_id = world["batches"]["b1"]["batch"]["id"]

        invalidated = invalidate_batch(batch_id)
        assert invalidated["status"] == "INVALIDATED"
        assert invalidated["status_before_invalidation"] == "FULLY_CHECKED"
        assert invalidated["accepted_raw_count"] == 0
        assert invalidated["verification_cost_cents"] == 10, (
            "the stored amount survives the invalidation, so it can be added back"
        )

        first_line = read_line(world["batches"]["b1"]["lines"][0]["id"])
        assert first_line["validation_status"] == "VOIDED"
        assert first_line["status_before_void"] == "VALID"
        assert first_line["void_reason"] == "BATCH_INVALIDATED"

        petition = read_petition(world["petition"]["id"])
        assert petition["raw_signature_count"] == 2
        assert petition["accepted_raw_total"] == 2
        assert petition["verified_valid_count"] == 1
        assert petition["voided_signature_count"] == 2
        assert petition["verification_cost_accrued_cents"] == 10
        assert petition["qualifying_county_count"] == 1, (
            "ALPHA's minimum is 1 and the surviving batch still credits one valid line"
        )
        assert petition["status"] == "PENDING_CERTIFICATION"

    def test_reinstating_the_batch_restores_every_counter_verbatim(self):
        """The round trip is exact on all five signature-ledger counters and on
        the cost ledger, and the recorded pre-images are cleared.

        PRD §2.10: "Invalidating a batch and then reinstating it must return
        accepted_raw_total to the identical value it held before the
        invalidation, along with verified_valid_count, projected_valid_count,
        voided_signature_count and qualifying_county_count ... invalidation
        subtracts exactly the stored amount rather than a freshly recomputed one,
        and reinstatement adds exactly the amount that was subtracted."

        Design: Difficulty/compensating_invariant/batch_invalidate_reinstate_preserves_signature_ledger
        """
        world = _fully_checked_petition()
        batch_id = world["batches"]["b1"]["batch"]["id"]
        before = read_petition(world["petition"]["id"])

        invalidate_batch(batch_id)
        reinstated = reinstate_batch(batch_id)

        assert reinstated["status"] == "FULLY_CHECKED"
        assert reinstated["status_before_invalidation"] is None
        assert reinstated["accepted_raw_count"] == 2
        assert reinstated["verification_cost_cents"] == 10

        first_line = read_line(world["batches"]["b1"]["lines"][0]["id"])
        assert first_line["validation_status"] == "VALID"
        assert first_line["status_before_void"] is None
        assert first_line["void_reason"] is None

        after = read_petition(world["petition"]["id"])
        assert_signature_ledger_restored(before, after)
        assert_cost_ledger_restored(before, after)
        assert after["raw_signature_count"] == before["raw_signature_count"]
        assert after["status"] == "PENDING_CERTIFICATION"


class TestRoundVoidConservesCost:
    """The round's `accrued_cost_cents` is exactly what a void subtracts, which
    is only true because the round accrued deltas."""

    def _invoice(self, petition_id):
        return validate_success(
            api_client.get_verification_invoice(petition_id, make_examiner_headers())
        )

    def test_voiding_a_round_returns_the_cost_ledger_and_the_invoice_to_zero(self):
        """Both batches lose their stored cost, the petition's accrual returns to
        0, and the tiered invoice collapses with it.

        PRD §3.9: "it restores every batch the round touched to the status that
        batch held before the round examined it and resets that batch's stored
        verification_cost_cents to 0; it subtracts the round's accrued_cost_cents
        from the petition's verification_cost_accrued_cents, which is exact
        because the round accrued only deltas."

        Design: Difficulty/compensating_invariant/round_void_preserves_cost_ledger
        """
        world = _fully_checked_petition()
        petition_id = world["petition"]["id"]

        before = self._invoice(petition_id)
        assert before["gross_cents"] == 20
        assert before["tier"] == "TIER_A"
        assert before["discount_cents"] == 2
        assert before["subtotal_cents"] == 18
        assert before["surcharge_cents"] == 1
        assert before["total_cents"] == 19

        voided = void_round(world["closed_round"]["id"])
        assert voided["status"] == "VOIDED"
        assert voided["accrued_cost_cents"] == 0

        for key in ("b1", "b2"):
            batch = read_batch(world["batches"][key]["batch"]["id"])
            assert batch["status"] == "AFFIDAVIT_VERIFIED"
            assert batch["verification_cost_cents"] == 0

        assert read_petition(petition_id)["verification_cost_accrued_cents"] == 0

        after = self._invoice(petition_id)
        assert after["gross_cents"] == 0
        assert after["tier"] == "TIER_NONE"
        assert after["discount_cents"] == 0
        assert after["subtotal_cents"] == 0
        assert after["surcharge_cents"] == 0
        assert after["total_cents"] == 0

    def test_voiding_a_round_returns_its_lines_to_the_eligible_pool(self):
        """Every selected line goes back to PENDING with its sample marks
        cleared, the petition falls back to SIGNATURES_FILED, and a fresh round
        sees the whole pool again.

        PRD §3.9: "Voiding clears in_sample and validated_in_round_id on every
        line the round selected and returns those lines to PENDING, so they
        re-enter the eligible pool of a later round ... Voiding a CLOSED round
        additionally recomputes the petition's projected_valid_count and
        verified_valid_count from whatever closed round is now the latest, or sets
        both to 0 when none remains, and returns the petition's status to
        SIGNATURES_FILED when no other CLOSED round exists."

        Design: Difficulty/compensating_invariant/round_void_preserves_cost_ledger
        """
        world = _fully_checked_petition()
        petition_id = world["petition"]["id"]

        void_round(world["closed_round"]["id"])
        assert read_round(world["closed_round"]["id"])["status"] == "VOIDED"

        first_line = read_line(world["batches"]["b1"]["lines"][0]["id"])
        assert first_line["validation_status"] == "PENDING"
        assert first_line["in_sample"] is False
        assert first_line["validated_in_round_id"] is None

        petition = read_petition(petition_id)
        assert petition["status"] == "SIGNATURES_FILED"
        assert petition["projected_valid_count"] == 0
        assert petition["verified_valid_count"] == 0
        assert petition["accepted_raw_total"] == 4, (
            "the signature ledger never moved: no batch was invalidated"
        )

        fresh = open_followup_round(world, round_type="FULL_CHECK")
        assert fresh["round_index"] == 2, "the voided round still consumed index 1"
        assert fresh["eligible_pool_size"] == 4
