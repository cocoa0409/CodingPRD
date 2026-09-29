"""Rider-line rulings on a production advance: the blocked branch, the
substitution revert edge back into review, closure of the advance, and the
public announcement's dependency on that advance being complete."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import build_announce_payload
from test_helpers.fixtures import (
    add_rider_item,
    add_ticket_scale,
    complete_advance,
    get_advance,
    get_booking,
    get_rider_item,
    get_ticket_scale,
    rule_rider_item,
    setup_accepted_booking,
)
from test_helpers.test_users import FAIR_OPERATIONS_DIRECTOR_HEADERS

CRITICAL_SOUND_LINE = {
    "category": "SOUND",
    "description": "Line array upgrade",
    "requested_cost_cents": 800000,
    "is_critical": True,
    "artist_recoupable": True,
}

NON_CRITICAL_LIGHTING_LINE = {
    "category": "LIGHTING",
    "description": "House lighting package",
    "requested_cost_cents": 0,
    "is_critical": False,
    "artist_recoupable": False,
}

RESERVED_TIER = {
    "seating_type": "RESERVED",
    "tier_name": "GOLD",
    "face_price_cents": 6295,
    "allotment_seats": 2000,
    "bundled_with_gate_admission": False,
    "facility_fee_cents": 400,
}


def _accepted_booking_with_critical_sound_line():
    """An accepted show whose advance is in review with a critical sound line."""
    scenario = setup_accepted_booking()
    scenario["sound_rider_item"] = add_rider_item(
        scenario["advance"]["id"], **CRITICAL_SOUND_LINE
    )
    return scenario


class TestCriticalRiderRulingBranchAndRevert:
    """Refusing a critical rider line blocks the advance; substituting it reverts."""

    def test_denying_a_critical_rider_line_blocks_the_advance(self):
        """A refusal of a single critical rider line takes the advance out of
        review and onto the blocked branch, recording why it is blocked while
        leaving the refused line's approved cost at zero.

        "the advance takes the branch `ADVANCE_IN_REVIEW → ADVANCE_BLOCKED`, its `denied_item_count` is recomputed and its `blocked_reason_code` is set to `DENIED_CRITICAL_ITEM`"

        Design: Difficulty/non_linear_state_machine/production_advance_blocks_then_reverts_via_substitution
        """
        scenario = _accepted_booking_with_critical_sound_line()
        sound_line = scenario["sound_rider_item"]

        rule_rider_item(sound_line["id"], "DENIED")

        advance = get_advance(scenario["advance"]["id"])
        assert advance["status"] == "ADVANCE_BLOCKED"
        assert advance["blocked_reason_code"] == "DENIED_CRITICAL_ITEM"
        assert advance["denied_item_count"] == 1
        assert advance["approved_rider_cost_cents"] == 0
        assert get_rider_item(sound_line["id"])["approved_cost_cents"] == 0

    def test_denied_critical_line_leaves_booking_recoupment_at_zero(self):
        """A refusal writes no approved cost, so the recoupable rider total the
        booking mirrors stays at zero while the advance sits blocked.

        "the booking's `recoupable_production_cost_cents` mirrors it, reading 0 whenever the booking has no advance or its advance has been cancelled"

        Design: Difficulty/non_linear_state_machine/production_advance_blocks_then_reverts_via_substitution
        """
        scenario = _accepted_booking_with_critical_sound_line()

        rule_rider_item(scenario["sound_rider_item"]["id"], "DENIED")

        advance = get_advance(scenario["advance"]["id"])
        assert advance["recoupable_rider_cost_cents"] == 0
        booking = get_booking(scenario["booking"]["id"])
        assert booking["recoupable_production_cost_cents"] == 0

    def test_substituting_the_denied_critical_line_reverts_advance_to_review(self):
        """Re-ruling the refused critical line as a substitution walks the
        advance back off the blocked branch, clears the blocked reason and drops
        the refused-line count back to zero.

        "the advance takes the revert edge `ADVANCE_BLOCKED → ADVANCE_IN_REVIEW`, the line's `approved_cost_cents` becomes the supplied `substituted_cost_cents`"

        Design: Difficulty/non_linear_state_machine/production_advance_blocks_then_reverts_via_substitution
        """
        scenario = _accepted_booking_with_critical_sound_line()
        sound_line = scenario["sound_rider_item"]

        rule_rider_item(sound_line["id"], "DENIED")
        rule_rider_item(sound_line["id"], "SUBSTITUTED", substituted_cost_cents=500000)

        advance = get_advance(scenario["advance"]["id"])
        assert advance["status"] == "ADVANCE_IN_REVIEW"
        assert advance["blocked_reason_code"] is None
        assert advance["denied_item_count"] == 0

        line = get_rider_item(sound_line["id"])
        assert line["status"] == "SUBSTITUTED"
        assert line["approved_cost_cents"] == 500000

    def test_substituted_cost_lands_on_both_advance_ledgers_and_the_booking(self):
        """The substituted figure becomes the line's approved cost, so the
        advance's approved and recoupable rider totals both carry it and the
        booking's recoupable production cost mirrors the recoupable total.

        "the booking's `recoupable_production_cost_cents` mirrors it, reading 0 whenever the booking has no advance or its advance has been cancelled"

        Design: Difficulty/non_linear_state_machine/production_advance_blocks_then_reverts_via_substitution
        """
        scenario = _accepted_booking_with_critical_sound_line()
        sound_line = scenario["sound_rider_item"]

        rule_rider_item(sound_line["id"], "DENIED")
        rule_rider_item(sound_line["id"], "SUBSTITUTED", substituted_cost_cents=500000)

        advance = get_advance(scenario["advance"]["id"])
        assert advance["approved_rider_cost_cents"] == 500000
        assert advance["recoupable_rider_cost_cents"] == 500000
        booking = get_booking(scenario["booking"]["id"])
        assert booking["recoupable_production_cost_cents"] == 500000

    def test_advance_completes_after_the_substitution_keeping_the_approved_cost(self):
        """With the substituted sound line honoured and the seed staging line
        approved, the advance closes and keeps the substituted amount in its
        approved rider total.

        "On success the advance moves `ADVANCE_IN_REVIEW → ADVANCE_COMPLETE`, `approved_rider_cost_cents` and `recoupable_rider_cost_cents` are recomputed"

        Design: Difficulty/non_linear_state_machine/production_advance_blocks_then_reverts_via_substitution
        """
        scenario = _accepted_booking_with_critical_sound_line()
        sound_line = scenario["sound_rider_item"]

        rule_rider_item(sound_line["id"], "DENIED")
        rule_rider_item(sound_line["id"], "SUBSTITUTED", substituted_cost_cents=500000)
        rule_rider_item(scenario["seed_rider_item"]["id"], "APPROVED")
        advance = complete_advance(scenario["advance"]["id"])

        assert advance["status"] == "ADVANCE_COMPLETE"
        assert advance["approved_rider_cost_cents"] == 500000

        seed = get_rider_item(scenario["seed_rider_item"]["id"])
        assert seed["status"] == "APPROVED"
        assert seed["approved_cost_cents"] == 0


def _scaled_booking_with_advance_in_review():
    """A priced, still-held show whose advance is in review, seed line unruled."""
    scenario = setup_accepted_booking()
    scenario["ticket_scale"] = add_ticket_scale(
        scenario["booking"]["id"], **RESERVED_TIER
    )
    lighting = add_rider_item(scenario["advance"]["id"], **NON_CRITICAL_LIGHTING_LINE)
    rule_rider_item(lighting["id"], "APPROVED")
    scenario["lighting_rider_item"] = lighting
    return scenario


class TestAnnouncementDependsOnCompletedAdvance:
    """A priced, correctly held show still cannot go public until its advance closes."""

    def test_announce_is_refused_while_the_advance_is_still_in_review(self):
        """Announcing a show requires its production advance to be closed, so a
        booking whose advance is still in review is refused even though the
        booking itself is held and already carries a price tier.

        "the booking's production advance must read `ADVANCE_COMPLETE` — any other advance status is refused with `ERR_ADVANCE_NOT_COMPLETE`"

        Design: Difficulty/cross_entity_state_dependency/announce_blocked_until_production_advance_is_complete
        """
        scenario = _scaled_booking_with_advance_in_review()

        response = api_client.announce_show_booking(
            scenario["booking"]["id"],
            build_announce_payload(),
            FAIR_OPERATIONS_DIRECTOR_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_ADVANCE_NOT_COMPLETE.value)

        assert get_advance(scenario["advance"]["id"])["status"] == "ADVANCE_IN_REVIEW"
        booking = get_booking(scenario["booking"]["id"])
        assert booking["booking_status"] == "DATE_HELD"
        assert booking["ticketing_status"] == "SCALED"
        assert booking["doors_time_utc"] is None
        assert booking["announced_at_utc"] is None

    def test_closing_the_advance_leaves_the_booking_state_untouched(self):
        """Closing the advance reconciles the advance's own cost ledgers and the
        booking's recoupable production cost, and nothing else about the
        booking's own two dimensions moves with it.

        "On success the advance moves `ADVANCE_IN_REVIEW → ADVANCE_COMPLETE`, `approved_rider_cost_cents` and `recoupable_rider_cost_cents` are recomputed"

        Design: Difficulty/cross_entity_state_dependency/announce_blocked_until_production_advance_is_complete
        """
        scenario = _scaled_booking_with_advance_in_review()

        rule_rider_item(scenario["seed_rider_item"]["id"], "APPROVED")
        advance = complete_advance(scenario["advance"]["id"])
        assert advance["status"] == "ADVANCE_COMPLETE"

        booking = get_booking(scenario["booking"]["id"])
        assert booking["booking_status"] == "DATE_HELD"
        assert booking["ticketing_status"] == "SCALED"
        assert booking["doors_time_utc"] is None

    def test_completing_the_advance_admits_the_same_announce_call(self):
        """Once the seed staging line is honoured and the advance is closed, the
        identical announcement lands: the show goes public, the doors instant is
        written and the already-scaled box office joins into on-sale.

        "If at that moment the box-office dimension already reads `SCALED`, it advances `SCALED → ON_SALE` in the same request."

        Design: Difficulty/cross_entity_state_dependency/announce_blocked_until_production_advance_is_complete
        """
        scenario = _scaled_booking_with_advance_in_review()
        booking_id = scenario["booking"]["id"]

        refused = api_client.announce_show_booking(
            booking_id, build_announce_payload(), FAIR_OPERATIONS_DIRECTOR_HEADERS
        )
        validate_error(refused, ApiErrorId.ERR_ADVANCE_NOT_COMPLETE.value)

        rule_rider_item(scenario["seed_rider_item"]["id"], "APPROVED")
        complete_advance(scenario["advance"]["id"])

        accepted = api_client.announce_show_booking(
            booking_id, build_announce_payload(), FAIR_OPERATIONS_DIRECTOR_HEADERS
        )
        booking = validate_success(accepted, expected_status=200)
        assert booking["booking_status"] == "ANNOUNCED"
        assert booking["doors_time_utc"] == "2026-08-22T18:00:00.000Z"
        assert booking["ticketing_status"] == "ON_SALE"
        assert get_ticket_scale(scenario["ticket_scale"]["id"])["status"] == (
            "ON_SALE_ELIGIBLE"
        )
