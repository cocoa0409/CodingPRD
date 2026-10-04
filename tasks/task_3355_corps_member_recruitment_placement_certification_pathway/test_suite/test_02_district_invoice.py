"""District invoicing: the stored view, the projection, and the exit/reinstate pair."""
import pytest

from test_helpers import assert_district_invoice_matches_counters, validate_success

from test_helpers.fixtures import (
    PLACEMENT_COORDINATOR,
    create_confirmed_placement,
    get_district,
    setup_member_scenario,
    setup_member_with_active_placement,
)


class TestInvoiceVariants:
    """ACTUAL reports the stored value; FORWARD_LOOKING assumes every slot fills."""

    def test_actual_projection_reports_stored_invoice(self, api):
        """PRD §3.6: "The filled count is the number of placements whose school resolves to this district and whose status is `CONFIRMED` or `ACTIVE`; placements still `MATCHED`, or already `EXITED_EARLY` or `COMPLETED`, are excluded."
        PRD §3.6: "The gross charge is the filled count multiplied by `placement_fee_per_member_cents`, the penalty is the unfilled count multiplied by `unfilled_slot_penalty_cents`, and `invoice_amount_cents` is the sum of the two."
        PRD §3.6: "The default projection is `ACTUAL`, which reports the stored value."

        Design: Difficulty/dual_variant_calc/district_invoice_actual_vs_forward_looking
        """
        scenario = setup_member_scenario()
        placement = create_confirmed_placement(scenario["member_id"], scenario["school"]["id"])
        assert placement["status"] == "CONFIRMED"

        district = get_district(scenario["district"]["id"])
        assert district["committed_placement_count"] == 1
        assert district["invoice_amount_cents"] == 710000, (
            "1 filled slot * 350000 + 3 unfilled slots * 120000 = 710000"
        )
        assert_district_invoice_matches_counters(district, filled=1)

    def test_forward_looking_projection_assumes_every_slot_fills(self, api):
        """PRD §3.6: "When the caller passes `projection` with the value `FORWARD_LOOKING`, the invoice reported is the district's `hiring_commitment_slots` multiplied by its `placement_fee_per_member_cents`, with no penalty term at all — the assumption being that every committed slot will eventually be filled."
        PRD §3.6: "For any district with at least one unfilled slot the two views return different integers, and clients comparing them can read the gap as the district's remaining hiring exposure."

        Design: Difficulty/dual_variant_calc/district_invoice_actual_vs_forward_looking
        """
        scenario = setup_member_scenario()
        create_confirmed_placement(scenario["member_id"], scenario["school"]["id"])
        district_id = scenario["district"]["id"]

        actual = get_district(district_id)
        forward = get_district(district_id, projection="FORWARD_LOOKING")

        assert forward["invoice_amount_cents"] == 1400000, (
            "4 committed slots * 350000 with no penalty term = 1400000"
        )
        assert actual["invoice_amount_cents"] == 710000
        assert forward["invoice_amount_cents"] != actual["invoice_amount_cents"], (
            "one unfilled slot must make the two views observably distinct"
        )


class TestEarlyExitReinstateConservation:
    """The exit/reinstate pair leaves the district counters and invoice unchanged."""

    def test_early_exit_then_reinstate_restores_committed_count(self, api):
        """PRD §3.8: "The first hop releases the resources the placement was holding: the district's `committed_placement_count` drops by 1 and the school's `occupied_classrooms` drops by 1."
        PRD §3.8: "Reinstatement clears `early_exit_reason` back to null, sets `employment_eligible` from the eligibility calculation rather than from a stored value, increments the district's `committed_placement_count` and the school's `occupied_classrooms` by 1 each, and recomputes the district's `invoice_amount_cents`."

        Design: Difficulty/compensating_invariant/early_exit_reinstate_conserves_committed_count
        """
        scenario = setup_member_with_active_placement()
        district_id = scenario["district"]["id"]
        placement_id = scenario["placement"]["id"]

        before = get_district(district_id)
        assert before["committed_placement_count"] == 1

        exited = validate_success(
            api.early_exit_placement(placement_id, "relocated out of region", PLACEMENT_COORDINATOR)
        )
        assert exited["status"] == "EXITED_EARLY"
        assert exited.get("early_exit_reason") == "relocated out of region"

        mid = get_district(district_id)
        assert mid["committed_placement_count"] == 0, (
            "the early exit must release the district slot"
        )

        reinstated = validate_success(
            api.reinstate_placement(placement_id, PLACEMENT_COORDINATOR)
        )
        assert reinstated["status"] == "ACTIVE"
        assert reinstated.get("early_exit_reason") is None

        after = get_district(district_id)
        assert after["committed_placement_count"] == 1, (
            "the pair must leave zero drift in the district-scoped placement count"
        )
        assert after["invoice_amount_cents"] == before["invoice_amount_cents"] == 710000

    def test_early_exit_raises_the_unfilled_slot_penalty(self, api):
        """PRD §3.8: "The second hop recomputes the district's `invoice_amount_cents` from the reduced filled count, which raises the unfilled-slot penalty."
        PRD §3.6: "The unfilled count is the district's `hiring_commitment_slots` minus the filled count, floored at zero, so an over-filled commitment never produces a negative penalty."

        Design: Difficulty/compensating_invariant/early_exit_reinstate_conserves_committed_count
        """
        scenario = setup_member_with_active_placement()
        district_id = scenario["district"]["id"]

        validate_success(
            api.early_exit_placement(
                scenario["placement"]["id"], "relocated out of region", PLACEMENT_COORDINATOR
            )
        )
        mid = get_district(district_id)
        assert mid["invoice_amount_cents"] == 480000, (
            "with no filled slots the whole commitment is penalised: 4 * 120000"
        )
        assert_district_invoice_matches_counters(mid, filled=0)
