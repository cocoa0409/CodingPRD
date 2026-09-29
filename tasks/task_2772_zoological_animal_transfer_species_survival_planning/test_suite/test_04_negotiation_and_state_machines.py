"""The cyclic negotiation loop and the animal's two independent state dimensions."""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_NEGOTIATION_ROUND_LIMIT
from test_helpers.assertions import assert_money


def _drafted(api):
    world = fx.base_pair(api)
    fx.endorsed_recommendation(world)
    fx.draft_agreement(world)
    return world


class TestNegotiationRoundCap:
    """OFFERED and COUNTERED alternate until the six-round cap terminates the loop."""

    def test_the_offer_counter_cycle_is_traversed_repeatedly(self, api):
        """Six alternating acts walk OFFERED, COUNTERED, OFFERED, COUNTERED twice over.

        PRD: "Both acts increase `round_number` by exactly 1 and set
        `last_action_institution_id` to the acting `X-User-ID`. The opening offer
        therefore takes `round_number` from 0 to 1."

        Design: Difficulty/non_linear_state_machine/agreement_offer_counter_cycle_hits_round_cap
        """
        world = _drafted(api)
        assert world.read_agreement()["round_number"] == 0
        expected = [
            ("offer", world.sender, world.sender_id, "OFFERED", 1),
            ("counter", world.receiver, world.receiver_id, "COUNTERED", 2),
            ("offer", world.sender, world.sender_id, "OFFERED", 3),
            ("counter", world.receiver, world.receiver_id, "COUNTERED", 4),
            ("offer", world.sender, world.sender_id, "OFFERED", 5),
            ("counter", world.receiver, world.receiver_id, "COUNTERED", 6),
        ]
        for act, headers, actor_id, status, round_number in expected:
            call = (api.offer_agreement if act == "offer"
                    else api.counter_agreement)
            data = validate_success(
                call(world.ta_id, headers,
                     f.terms_payload(transport_cost_share_pct=40.0 + round_number))
            )
            assert data["status"] == status
            assert data["round_number"] == round_number
            assert data["last_action_institution_id"] == actor_id

    def test_the_seventh_term_changing_act_is_refused_at_the_cap(self, api):
        """With round_number at six the next offer is refused and changes nothing.

        PRD: "An offer or counter attempted when `round_number` has already
        reached six is refused with `ERR_NEGOTIATION_ROUND_LIMIT` (HTTP 422)."

        Design: Difficulty/non_linear_state_machine/agreement_offer_counter_cycle_hits_round_cap
        """
        world = _drafted(api)
        for index in range(3):
            validate_success(api.offer_agreement(
                world.ta_id, world.sender, f.terms_payload(45.0)))
            validate_success(api.counter_agreement(
                world.ta_id, world.receiver,
                f.terms_payload(
                    30.0,
                    ownership_disposition="LOAN_WITH_RETAINED_OWNERSHIP",
                ),
            ))
        before = world.read_agreement()
        assert before["round_number"] == 6
        assert before["status"] == "COUNTERED"
        assert before["last_action_institution_id"] == world.receiver_id
        response = api.offer_agreement(world.ta_id, world.sender,
                                       f.terms_payload(35.0))
        validate_error(response, ERR_NEGOTIATION_ROUND_LIMIT)
        after = world.read_agreement()
        assert after["round_number"] == 6
        assert after["status"] == "COUNTERED"
        assert after["version"] == before["version"]

    def test_the_terms_of_record_are_those_of_the_most_recent_action(self, api):
        """The last counter's disposition and cost share survive the refused offer.

        PRD: "Both acts may carry any of `ownership_disposition`,
        `offspring_disposition_rule`, `breeding_rights` and
        `transport_cost_share_pct` — all four optional — and whichever of them is
        supplied overwrites the corresponding field on the agreement, so the
        terms of record are always the terms of the most recent action."

        Design: Difficulty/non_linear_state_machine/agreement_offer_counter_cycle_hits_round_cap
        """
        world = _drafted(api)
        for index in range(3):
            validate_success(api.offer_agreement(
                world.ta_id, world.sender,
                f.terms_payload(45.0,
                                ownership_disposition="OWNERSHIP_TRANSFER")))
            validate_success(api.counter_agreement(
                world.ta_id, world.receiver,
                f.terms_payload(
                    30.0,
                    ownership_disposition="LOAN_WITH_RETAINED_OWNERSHIP",
                ),
            ))
        validate_error(
            api.offer_agreement(world.ta_id, world.sender,
                                f.terms_payload(35.0)),
            ERR_NEGOTIATION_ROUND_LIMIT,
        )
        agreement = world.read_agreement()
        assert agreement["ownership_disposition"] == \
            "LOAN_WITH_RETAINED_OWNERSHIP"
        assert_money(agreement["transport_cost_share_pct"], 30.0,
                     "transport_cost_share_pct")

    def test_acceptance_at_the_cap_closes_the_loop_without_a_round(self, api):
        """The counterparty may still accept, and round_number stays at six.

        PRD: "Acceptance is not a negotiation round: it leaves `round_number`
        untouched and leaves `last_action_institution_id` pointing at whoever put
        the accepted terms on the table."

        Design: Difficulty/non_linear_state_machine/agreement_offer_counter_cycle_hits_round_cap
        """
        world = _drafted(api)
        for index in range(3):
            validate_success(api.offer_agreement(
                world.ta_id, world.sender, f.terms_payload(45.0)))
            validate_success(api.counter_agreement(
                world.ta_id, world.receiver, f.terms_payload(30.0)))
        accepted = validate_success(
            api.accept_agreement(world.ta_id, world.sender,
                                 {"acceptance_note": "Terms accepted"})
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["round_number"] == 6
        assert accepted["last_action_institution_id"] == world.receiver_id


class TestAnimalTwoStateDimensions:
    """Custody and breeding management advance independently on one animal row."""

    def test_endorsement_moves_genetics_and_leaves_custody_alone(self, api):
        """Both animals become BREED_RECOMMENDED while both stay HELD.

        PRD: "An endorsement that sets a breeding designation leaves custody
        untouched; a shipment that moves custody leaves the breeding designation
        untouched."

        Design: Difficulty/non_linear_state_machine/animal_location_and_genetic_dimensions_move_independently
        """
        world = fx.base_pair(api)
        fx.propose_recommendation(world)
        for animal_id in (world.m1_id, world.f1_id):
            animal = world.read_animal(animal_id)
            assert animal["location_status"] == "HELD"
            assert animal["genetic_designation"] == "UNEVALUATED"
        validate_success(api.endorse_recommendation(world.rec_id, world.sender))
        for animal_id in (world.m1_id, world.f1_id):
            animal = world.read_animal(animal_id)
            assert animal["genetic_designation"] == "BREED_RECOMMENDED"
            assert animal["location_status"] == "HELD"

    def test_execution_moves_custody_and_leaves_genetics_alone(self, api):
        """The subject becomes RESERVED yet stays BREED_RECOMMENDED.

        PRD: "**Breeding management** is tracked by `genetic_designation`, which
        takes one of `UNEVALUATED`, `BREED_RECOMMENDED`, `HOLD_NO_BREED` or
        `SURPLUS_APPROVED`."

        Design: Difficulty/non_linear_state_machine/animal_location_and_genetic_dimensions_move_independently
        """
        world = fx.world_with_executed_agreement(api)
        subject = world.read_animal(world.m1_id)
        assert subject["location_status"] == "RESERVED"
        assert subject["genetic_designation"] == "BREED_RECOMMENDED"

    def test_the_paired_animal_moves_on_neither_dimension_at_execution(self, api):
        """The mate stays HELD and BREED_RECOMMENDED throughout the shipment.

        PRD: "An animal's state is genuinely two-dimensional, and the two
        dimensions advance independently of one another."

        Design: Difficulty/non_linear_state_machine/animal_location_and_genetic_dimensions_move_independently
        """
        world = fx.world_with_executed_agreement(api)
        mate = world.read_animal(world.f1_id)
        assert mate["location_status"] == "HELD"
        assert mate["genetic_designation"] == "BREED_RECOMMENDED"
