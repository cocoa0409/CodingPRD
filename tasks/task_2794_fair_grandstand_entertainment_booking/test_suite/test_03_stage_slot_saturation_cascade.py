"""Sending an offer takes a stage hold, and the hops that follow: the stage's
held-show count rises, its booking posture flips, and the edition's count of open
stages is recounted.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_stage_posture
from test_helpers.test_users import TALENT_BUYER_HEADERS

SENT_GUARANTEE_CENTS = 9_000_000


def _world_with_two_single_slot_stages():
    """An edition carrying two stages, each saturated by a single hold, and one
    drafted offer aimed at the first of them.
    """
    world = fixtures.setup_base_world(stage_overrides={"slot_soft_cap": 1})
    world["pavilion"] = fixtures.create_stage(
        world["edition"]["id"],
        name="Pavilion",
        reserved_seat_capacity=500,
        ga_capacity=500,
        changeover_buffer_minutes=60,
        slot_soft_cap=1,
    )
    return fixtures.setup_draft_offer(
        world, offered_guarantee_cents=SENT_GUARANTEE_CENTS
    )


class TestSendSaturatesTheTargetStage:
    """One send, three hops: hold count, posture, open-stage count."""

    def test_send_raises_the_hold_count_flips_posture_and_recounts_open_stages(self):
        """The sent offer holds a slot on its target stage, that hold reaches the
        stage's soft cap so the stage stops advertising itself as open, and the
        edition's tally of open stages falls to the one stage still open.

        "A change to a stage's `held_show_count` may flip that stage's `booking_posture`, and a flip in `booking_posture` forces a recount of the edition's `open_stage_count`."

        Design: Difficulty/transitive_cascade/offer_send_saturates_stage_and_closes_edition_slot
        """
        scenario = _world_with_two_single_slot_stages()
        assert fixtures.get_edition(scenario["edition"]["id"])["open_stage_count"] == 2

        validate_success(
            api_client.send_offer(scenario["offer"]["id"], TALENT_BUYER_HEADERS)
        )

        target_stage = fixtures.get_stage(scenario["stage"]["id"])
        assert target_stage["held_show_count"] == 1
        assert target_stage["booking_posture"] == "SATURATED"
        assert_stage_posture(target_stage)
        assert fixtures.get_edition(scenario["edition"]["id"])["open_stage_count"] == 1

    def test_send_leaves_the_other_stage_of_the_edition_open(self):
        """A hold taken on one stage is counted only against that stage, so the
        second stage keeps an empty slot ledger and stays open, which is why the
        edition still counts one open stage rather than none.

        "Finally, the edition's `open_stage_count` is the number of that edition's stages whose `booking_posture` reads `OPEN`."

        Design: Difficulty/transitive_cascade/offer_send_saturates_stage_and_closes_edition_slot
        """
        scenario = _world_with_two_single_slot_stages()

        validate_success(
            api_client.send_offer(scenario["offer"]["id"], TALENT_BUYER_HEADERS)
        )

        untouched_stage = fixtures.get_stage(scenario["pavilion"]["id"])
        assert untouched_stage["held_show_count"] == 0
        assert untouched_stage["booking_posture"] == "OPEN"
        assert_stage_posture(untouched_stage)

    def test_send_encumbers_the_offered_guarantee_and_stamps_the_response_window(self):
        """The send also encumbers the edition's talent budget with the standing
        guarantee and starts the agent's response window, whose expiry is the send
        instant advanced by the window's length in hours.

        "The offer's `sent_at_utc` is set to the logical clock and its `expires_at_utc` to `sent_at_utc` advanced by `response_window_hours` hours"

        Design: Difficulty/transitive_cascade/offer_send_saturates_stage_and_closes_edition_slot
        """
        scenario = _world_with_two_single_slot_stages()

        sent = validate_success(
            api_client.send_offer(scenario["offer"]["id"], TALENT_BUYER_HEADERS)
        )
        assert sent["status"] == "SENT"
        assert sent["expires_at_utc"] == "2026-08-03T00:00:00.000Z"

        edition = fixtures.get_edition(scenario["edition"]["id"])
        assert edition["committed_guarantee_total_cents"] == 9_000_000
