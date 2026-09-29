"""Uniqueness scope, structural pairing, conditional and aggregate gates."""

from __future__ import annotations

from prd_bench_local_runner.testing import (validate_error, validate_paginated,
                                            validate_success)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (ERR_DISPOSITION_POLICY_MISSING,
                                     ERR_DUPLICATE_ANIMAL_LOCAL_ID,
                                     ERR_HOLDING_CAPACITY_EXCEEDED,
                                     ERR_INVALID_PAIRING)
from test_helpers.assertions import assert_money, assert_slot_counts
from test_helpers.test_users import make_registrar_headers


class TestLocalIdUniquenessScope:
    """Uniqueness is scoped to the pair of holder and local identifier."""

    def test_a_repeated_local_id_at_the_same_holder_is_refused(self, api):
        """The second CR-101 at Cedar Ridge is refused and changes nothing.

        PRD: "If another animal at the same holding institution already carries
        the submitted `local_id`, the accession is refused with
        `ERR_DUPLICATE_ANIMAL_LOCAL_ID` (HTTP 422)"

        Design: Corner/validations/duplicate_local_id_at_same_holder_returns_duplicate_animal_local_id
        """
        world = fx.base_world(api, publish=False)
        first = fx.accession(world, world.sender_id, "CR-101", "MALE",
                             "2019-05-10", 12.45)
        response = api.create_animal(
            f.animal_payload(world.program_id, world.sender_id,
                             local_id="CR-101", sex="FEMALE",
                             birth_date="2021-04-02",
                             founder_representation_pct=5.00),
            make_registrar_headers(world.sender_id),
        )
        validate_error(response, ERR_DUPLICATE_ANIMAL_LOCAL_ID)
        _, meta = validate_paginated(
            api.list_animals(world.admin,
                             {"holding_institution_id": world.sender_id})
        )
        assert meta["total_count"] == 1
        stored = validate_success(api.get_animal(first["id"], world.admin))
        assert stored["sex"] == "MALE"
        assert stored["version"] == 1
        assert_slot_counts(world.read_institution(world.sender_id), 1, 0)

    def test_the_same_local_id_at_another_holder_is_accepted(self, api):
        """Harbor Bay may use CR-101 while Cedar Ridge already does.

        PRD: "the uniqueness constraint is scoped to the pair of holder and local
        identifier, so two institutions may each use the accession number "M-014"."

        Design: Corner/validations/same_local_id_at_a_different_holder_is_accepted
        """
        world = fx.base_world(api, publish=False)
        first = fx.accession(world, world.sender_id, "CR-101", "MALE",
                             "2019-05-10", 12.45)
        twin = validate_success(
            api.create_animal(
                f.animal_payload(world.program_id, world.receiver_id,
                                 local_id="CR-101", sex="FEMALE",
                                 birth_date="2020-03-15",
                                 founder_representation_pct=30.00),
                make_registrar_headers(world.receiver_id),
            ),
            201,
        )
        assert twin["local_id"] == "CR-101"
        assert twin["holding_institution_id"] == world.receiver_id
        assert twin["id"] != first["id"]
        _, meta = validate_paginated(api.list_animals(world.admin))
        assert meta["total_count"] == 2


class TestStructuralPairing:
    """The pairing rule reads the other animal's row before anything is written."""

    def test_two_males_are_not_a_pairing(self, api):
        """A BREED_WITH naming two MALE animals is refused and writes nothing.

        PRD: "A `BREED_WITH` directive must name a `paired_animal_id` that is not
        the subject itself, both animals must belong to the same
        `species_program_id`, neither may be `DISPOSED`, and their `sex` values
        must be `MALE` and `FEMALE` in some order"

        Design: Corner/validations/breed_with_same_sex_pair_returns_invalid_pairing
        """
        world = fx.base_world(api)
        m1 = fx.accession(world, world.sender_id, "CR-101", "MALE",
                          "2019-05-10", 12.45)
        m2 = fx.accession(world, world.sender_id, "CR-102", "MALE",
                          "2019-09-01", 22.00)
        response = api.create_recommendation(
            f.recommendation_payload(
                world.program_id, m1["id"], m1["version"],
                paired_animal_id=m2["id"],
                sending_institution_id=world.sender_id,
                receiving_institution_id=world.receiver_id,
            ),
            world.coordinator,
        )
        validate_error(response, ERR_INVALID_PAIRING)
        _, meta = validate_paginated(api.list_recommendations(world.admin))
        assert meta["total_count"] == 0
        animal = validate_success(api.get_animal(m1["id"], world.admin))
        assert animal["pending_recommendation_id"] is None
        assert animal["version"] == 1
        assert world.read_program()["open_recommendation_count"] == 0


class TestConditionalDispositionGate:
    """The policy flag is read only when the terms transfer ownership."""

    def test_an_ownership_transfer_into_a_receiver_with_no_policy_is_refused(
            self, api):
        """Acceptance was allowed, but the execute is refused at the policy gate.

        PRD: "Where `ownership_disposition` is `OWNERSHIP_TRANSFER`, the
        receiver's `disposition_policy_on_file` must be true, else
        `ERR_DISPOSITION_POLICY_MISSING` (HTTP 422)."

        Design: Corner/validations/execute_with_receiver_lacking_disposition_policy_returns_policy_missing
        """
        world = fx.world_with_accepted_agreement(
            api, receiver_overrides={"disposition_policy_on_file": False}
        )
        assert world.read_agreement()["status"] == "ACCEPTED"
        world.set_clock(fx.CLOCK_EXECUTE)
        response = api.execute_agreement(world.ta_id, world.sender, {})
        validate_error(response, ERR_DISPOSITION_POLICY_MISSING)

        agreement = world.read_agreement()
        assert agreement["status"] == "ACCEPTED"
        assert agreement["executed_at"] is None
        assert agreement["provisional_credit_points"] is None
        animal = world.read_animal()
        assert animal["location_status"] == "HELD"
        assert animal["owning_institution_id"] == world.sender_id
        assert_money(world.read_institution(world.sender_id)
                     ["transfer_credit_balance"], 0.00, "sender balance")
        assert_money(world.read_institution(world.receiver_id)
                     ["transfer_credit_balance"], 0.00, "receiver balance")
        assert world.read_recommendation()["status"] == "ENDORSED"


class TestAggregateCapacityGate:
    """Every ingredient is legal; only the collective slot count fails."""

    def test_executing_into_a_receiver_with_no_free_slot_is_refused(self, api):
        """A capacity of one already filled by the resident animal blocks the move.

        PRD: "Finally, the receiver must have a free holding slot: its
        `occupied_slots` plus its `reserved_slots` plus one for this animal must
        not exceed its `holding_capacity_slots`, or the execution is refused with
        `ERR_HOLDING_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/execute_into_a_full_receiving_institution_returns_capacity_exceeded
        """
        world = fx.world_with_accepted_agreement(
            api, receiver_overrides={"holding_capacity_slots": 1}
        )
        world.set_clock(fx.CLOCK_EXECUTE)
        response = api.execute_agreement(world.ta_id, world.sender, {})
        validate_error(response, ERR_HOLDING_CAPACITY_EXCEEDED)

        assert_slot_counts(world.read_institution(world.receiver_id), 1, 0)
        assert_slot_counts(world.read_institution(world.sender_id), 1, 0)
        assert world.read_agreement()["status"] == "ACCEPTED"
        assert world.read_animal()["location_status"] == "HELD"
