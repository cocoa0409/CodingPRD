"""The four-link execution cascade and the four-link introduction-abort cascade."""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_success
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_money


class TestExecuteCascade:
    """One execute call propagates across agreement, animal, directive and plan."""

    def test_execution_moves_the_agreement_and_stamps_the_clock_instant(self, api):
        """Status becomes EXECUTED and executed_at carries the logical clock.

        PRD: "Alongside the cascade, `status` becomes `EXECUTED` and
        `executed_at` is stamped from the logical clock; where
        `ownership_disposition` is `OWNERSHIP_TRANSFER`, the animal's
        `owning_institution_id` is moved to the receiving institution, while under
        either loan form the legal owner stays with the sender."

        Design: Difficulty/transitive_cascade/execute_cascade_four_links_to_cycle_closed
        """
        world = fx.world_with_executed_agreement(api)
        agreement = world.read_agreement()
        assert agreement["status"] == "EXECUTED"
        assert agreement["executed_at"].startswith("2026-08-10T09:00:00")
        assert world.read_animal(world.m1_id)["owning_institution_id"] == \
            world.receiver_id

    def test_the_first_two_links_move_custody_and_the_directive(self, api):
        """The animal becomes RESERVED and the directive becomes FULFILLED.

        PRD: "Because the animal has left `HELD`, the directive it was moving
        under is satisfied: the founding recommendation moves from `ENDORSED` to
        `FULFILLED`, and the animal's `pending_recommendation_id` is cleared to
        null."

        Design: Difficulty/transitive_cascade/execute_cascade_four_links_to_cycle_closed
        """
        world = fx.world_with_executed_agreement(api)
        animal = world.read_animal(world.m1_id)
        assert animal["location_status"] == "RESERVED"
        assert animal["pending_recommendation_id"] is None
        assert world.read_recommendation()["status"] == "FULFILLED"

    def test_the_last_two_links_recount_and_close_the_plan_cycle(self, api):
        """open_recommendation_count reaches zero and the plan closes on the day.

        PRD: "Because the recount reached zero while the programme was
        `PUBLISHED` — and at least one recommendation exists in the current cycle
        — the programme's `plan_status` moves to `CYCLE_CLOSED` and
        `cycle_closed_on` is stamped with the logical clock instant."

        Design: Difficulty/transitive_cascade/execute_cascade_four_links_to_cycle_closed
        """
        world = fx.world_with_accepted_agreement(api)
        before = world.read_program()
        assert before["plan_status"] == "PUBLISHED"
        assert before["open_recommendation_count"] == 1
        assert before["cycle_closed_on"] is None
        fx.executed_agreement(world)
        after = world.read_program()
        assert after["open_recommendation_count"] == 0
        assert after["plan_status"] == "CYCLE_CLOSED"
        assert after["cycle_closed_on"] is not None
        assert str(after["cycle_closed_on"]).startswith("2026-08-10")

    def test_both_institutions_slot_counts_are_recomputed(self, api):
        """The sender's occupied slot becomes the receiver's reserved slot.

        PRD: "The animal's `location_status` moves from `HELD` to `RESERVED`. The
        sending institution's `occupied_slots` therefore drops by one and the
        receiving institution's `reserved_slots` rises by one, and both
        institutions' slot counts are recomputed."

        Design: Difficulty/transitive_cascade/execute_cascade_four_links_to_cycle_closed
        """
        world = fx.world_with_accepted_agreement(api)
        sender_before = world.read_institution(world.sender_id)
        receiver_before = world.read_institution(world.receiver_id)
        assert sender_before["occupied_slots"] == 1
        assert sender_before["reserved_slots"] == 0
        assert receiver_before["occupied_slots"] == 1
        assert receiver_before["reserved_slots"] == 0
        fx.executed_agreement(world)
        sender_after = world.read_institution(world.sender_id)
        receiver_after = world.read_institution(world.receiver_id)
        assert sender_after["occupied_slots"] == 0
        assert sender_after["reserved_slots"] == 0
        assert receiver_after["occupied_slots"] == 1
        assert receiver_after["reserved_slots"] == 1


def _world_with_second_open_directive(api):
    """The full journey to an open protocol, with a second directive standing.

    REC2 names F1 as its subject and M1 merely as its paired animal, so it is
    not the directive the shipment was built on.
    """
    world = fx.base_pair(api)
    fx.register_veterinarians(world)
    fx.endorsed_recommendation(world)
    mate = world.read_animal(world.f1_id)
    rec2 = validate_success(
        api.create_recommendation(
            f.recommendation_payload(
                world.program_id, world.f1_id, mate["version"],
                paired_animal_id=world.m1_id,
                sending_institution_id=world.receiver_id,
                receiving_institution_id=world.receiver_id,
                priority_rank=2,
            ),
            world.coordinator,
        ),
        201,
    )
    validate_success(api.endorse_recommendation(rec2["id"], world.receiver))
    world.extra["rec2_id"] = rec2["id"]
    fx.draft_agreement(world)
    fx.offered_agreement(world)
    fx.accepted_agreement(world)
    fx.executed_agreement(world)
    fx.record_panel(world)
    world.set_clock(fx.CLOCK_DOCUMENTS)
    fx.issue_certificate(world)
    fx.issue_permit(world)
    world.set_clock(fx.CLOCK_PRESHIPMENT)
    fx.crate_train(world)
    fx.book_transport(world)
    fx.schedule_quarantine(world)
    fx.confirm_transport(world)
    fx.depart(world)
    fx.deliver(world)
    fx.clear_quarantine(world)
    fx.open_protocol(world)
    world.set_clock("2026-10-02T09:00:00Z")
    return world


class TestIntroductionAbortCascade:
    """An aborting observation reaches the plan cycle through the paired animal."""

    def test_a_severe_observation_alone_does_not_abort_at_howdy(self, api):
        """Five points leaves the protocol at HOWDY with the count still at one.

        PRD: "At `HOWDY` there is no stage below to regress into, so an
        accumulator reaching 6 points at the first stage aborts the protocol
        outright, with no regard for how many regressions have been used."

        Design: Difficulty/transitive_cascade/introduction_abort_cascade_four_links_to_cycle_closed
        """
        world = _world_with_second_open_directive(api)
        assert world.read_program()["open_recommendation_count"] == 1
        data = fx.observe(world, "SEVERE_AGGRESSION", observed_on="2026-10-02")
        assert data["stage"] == "HOWDY"
        assert_money(data["aggression_score_total"], 5.00,
                     "aggression_score_total")
        assert world.read_animal(world.m1_id)["location_status"] == "INTRODUCING"

    def test_the_first_two_links_abort_the_protocol_and_flip_both_dimensions(
            self, api):
        """Seven points aborts, returning the animal to HELD and HOLD_NO_BREED.

        PRD: "The animal's `location_status` returns from `INTRODUCING` to
        `HELD`, and its `genetic_designation` moves from `BREED_RECOMMENDED` to
        `HOLD_NO_BREED` — an animal that cannot be introduced to a group is not a
        breeding candidate."

        Design: Difficulty/transitive_cascade/introduction_abort_cascade_four_links_to_cycle_closed
        """
        world = _world_with_second_open_directive(api)
        fx.observe(world, "SEVERE_AGGRESSION", observed_on="2026-10-02")
        data = fx.observe(world, "MINOR_AGGRESSION", observed_on="2026-10-02")
        assert data["stage"] == "ABORTED"
        assert data["regression_count"] == 0
        assert_money(data["aggression_score_total"], 7.00,
                     "aggression_score_total")
        animal = world.read_animal(world.m1_id)
        assert animal["location_status"] == "HELD"
        assert animal["genetic_designation"] == "HOLD_NO_BREED"

    def test_the_third_link_declines_the_directive_that_merely_paired_the_animal(
            self, api):
        """REC2, which names M1 only as its paired animal, moves to DECLINED.

        PRD: "Because the designation became `HOLD_NO_BREED`, every `BREED_WITH`
        recommendation still `PROPOSED` or `ENDORSED` that names this animal as
        either its `subject_animal_id` or its `paired_animal_id` moves to
        `DECLINED`, and where the animal's `pending_recommendation_id` pointed at
        one of those declined recommendations it is cleared to null."

        Design: Difficulty/transitive_cascade/introduction_abort_cascade_four_links_to_cycle_closed
        """
        world = _world_with_second_open_directive(api)
        fx.observe(world, "SEVERE_AGGRESSION", observed_on="2026-10-02")
        fx.observe(world, "MINOR_AGGRESSION", observed_on="2026-10-02")
        assert world.read_recommendation(world.extra["rec2_id"])["status"] == \
            "DECLINED"
        assert world.read_recommendation(world.rec_id)["status"] == "FULFILLED"

    def test_the_fourth_link_recounts_and_closes_the_cycle_on_the_abort_date(
            self, api):
        """The recount reaches zero and the plan closes on 2026-10-02.

        PRD: "Because those recommendations left the open set, the programme's
        `open_recommendation_count` is recomputed, and a `PUBLISHED` programme
        whose count has reached zero moves to `CYCLE_CLOSED` with
        `cycle_closed_on` stamped."

        Design: Difficulty/transitive_cascade/introduction_abort_cascade_four_links_to_cycle_closed
        """
        world = _world_with_second_open_directive(api)
        assert world.read_program()["plan_status"] == "PUBLISHED"
        fx.observe(world, "SEVERE_AGGRESSION", observed_on="2026-10-02")
        fx.observe(world, "MINOR_AGGRESSION", observed_on="2026-10-02")
        program = world.read_program()
        assert program["open_recommendation_count"] == 0
        assert program["plan_status"] == "CYCLE_CLOSED"
        assert str(program["cycle_closed_on"]).startswith("2026-10-02")
