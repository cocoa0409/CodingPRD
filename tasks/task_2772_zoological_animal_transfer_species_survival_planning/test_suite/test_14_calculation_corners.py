"""Recency markers, per-holder aggregation and scope derivation."""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_paginated, validate_success
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_slot_counts
from test_helpers.test_users import make_registrar_headers


class TestCrateTrainingCurrency:
    """The recency marker follows the latest date, not the latest write."""

    def test_a_back_dated_session_does_not_move_the_recency_marker(self, api):
        """Three out-of-order sessions leave the marker on the maximum date.

        PRD: "`last_crate_session_on` is the latest `session_date` among them —
        the latest *date*, which need not belong to the most recently created
        record, so back-dating a session does not move the recency marker forward."

        Design: Corner/calculations/crate_training_currency_takes_the_latest_date_not_the_latest_write
        """
        world = fx.base_world(api, publish=False)
        animal = fx.accession(world, world.sender_id, "CR-101", "MALE",
                              "2019-05-10", 12.45)
        headers = make_registrar_headers(world.sender_id)

        def log(session_date, trainer_name, duration_minutes):
            validate_success(
                api.create_crate_training_session(
                    animal["id"],
                    f.crate_training_session_payload(
                        session_date=session_date, trainer_name=trainer_name,
                        duration_minutes=duration_minutes),
                    headers,
                ),
                201,
            )
            return validate_success(api.get_animal(animal["id"], world.admin))

        after_first = log("2026-07-28", "T Rios", 20)
        assert after_first["crate_training_sessions_count"] == 1
        assert str(after_first["last_crate_session_on"])[:10] == "2026-07-28"

        after_second = log("2026-07-20", "T Rios", 15)
        assert after_second["crate_training_sessions_count"] == 2
        assert str(after_second["last_crate_session_on"])[:10] == "2026-07-28"

        after_third = log("2026-07-24", "M Okafor", 35)
        assert after_third["crate_training_sessions_count"] == 3
        assert str(after_third["last_crate_session_on"])[:10] == "2026-07-28"
        assert after_third["version"] == 4


class TestHoldingSlotOccupancy:
    """Occupancy is counted per holder from the custody dimension alone."""

    def test_accessions_are_counted_at_their_holder_and_reserve_nothing(self, api):
        """Two animals at the sender and one at the receiver, no reservations.

        PRD: "An institution's `occupied_slots` is the number of animals whose
        `holding_institution_id` is that institution and whose `location_status`
        is one of `HELD`, `IN_QUARANTINE`, `AWAITING_INTRODUCTION` or
        `INTRODUCING`."

        Design: Corner/calculations/holding_slot_occupancy_counts_held_animals_per_holder
        """
        world = fx.base_world(api, publish=False)
        fx.accession(world, world.sender_id, "CR-101", "MALE", "2019-05-10", 12.45)
        fx.accession(world, world.sender_id, "CR-102", "FEMALE", "2019-09-01",
                     22.00)
        fx.accession(world, world.receiver_id, "HB-201", "FEMALE", "2020-03-15",
                     30.00)

        sender = world.read_institution(world.sender_id)
        receiver = world.read_institution(world.receiver_id)
        assert_slot_counts(sender, 2, 0)
        assert_slot_counts(receiver, 1, 0)
        assert sender["holding_capacity_slots"] == 40
        assert receiver["holding_capacity_slots"] == 40
        total = sum(row["occupied_slots"] + row["reserved_slots"]
                    for row in (sender, receiver))
        assert total == 3


class TestScopeDerivation:
    """Identical jurisdiction codes make the transfer intra-jurisdiction."""

    def test_two_same_state_parties_produce_an_intra_jurisdiction_agreement(
            self, api):
        """US-CA to US-CA is compared whole before the country prefix is read.

        PRD: "When the two codes are identical the scope is `INTRA_JURISDICTION`.
        Otherwise the two country codes — the two characters before the hyphen in
        each code — are compared: when they differ the scope is `INTERNATIONAL`,
        and when they match while the subdivisions differ the scope is
        `INTERSTATE`."

        Design: Corner/calculations/transfer_scope_derives_intra_jurisdiction_for_two_same_state_parties
        """
        world = fx.base_pair(
            api,
            receiver_overrides={"name": "Bayside Aquarium",
                                "jurisdiction_code": "US-CA"},
        )
        fx.endorsed_recommendation(world)
        agreement = fx.draft_agreement(
            world, ownership_disposition="BREEDING_LOAN",
            offspring_disposition_rule="FIRST_TO_SENDER",
            transport_cost_share_pct=0.0,
        )
        assert agreement["transfer_scope"] == "INTRA_JURISDICTION"
        assert agreement["status"] == "DRAFT"
        assert agreement["round_number"] == 0

        _, intra_meta = validate_paginated(
            api.list_agreements(world.admin,
                                {"transfer_scope": "INTRA_JURISDICTION"})
        )
        assert intra_meta["total_count"] == 1
        _, interstate_meta = validate_paginated(
            api.list_agreements(world.admin, {"transfer_scope": "INTERSTATE"})
        )
        assert interstate_meta["total_count"] == 0
