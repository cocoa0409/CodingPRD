"""Staging a run, describing its rooms and deriving the headcount it may admit."""

import pytest

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    api_client,
    assert_room,
    assert_run,
    assert_total_count,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_error_is_one_of,
    validate_object,
    validate_paginated,
    validate_success,
)

VOM = fx.VOM
LM = fx.LM
REP = fx.REP
PRODUCER = fx.PRODUCER
OFFICER = fx.OFFICER
AGENT = fx.AGENT


class TestCapacityNestedMinimum:
    """Four heterogeneous ceilings, and the arm that wins keeps changing."""

    def test_a_tighter_room_takes_over_the_bottleneck(self):
        """Each room create recomputes the run figure, and every division floors.

        PRD: "Each room's `throughput_per_slot` is how many guests it can pass in
        one timed slot: its `room_occupancy_cap` multiplied by the run's
        `timed_slot_minutes`, divided by its own `target_dwell_minutes`, floored
        to a whole guest."
        PRD: "that figure is the tightest of four heterogeneous ceilings: the
        venue's `permitted_occupancy_load` as granted by the authority; the
        code-derived egress ceiling".

        Design: Difficulty/combinatorial_formula/capacity_nested_min_switches_arm_from_room_to_inspection_cap
        """
        bundle = fx.run_bundle()
        run_id = bundle["run"]["id"]
        assert bundle["venue"]["egress_capacity"] == 197
        assert bundle["venue"]["permitted_occupancy_load"] == 180
        assert fx.read_run(run_id)["effective_capacity"] == 0

        first = fx.add_room(run_id, 1)
        assert first["throughput_per_slot"] == 120
        assert fx.read_run(run_id)["effective_capacity"] == 120

        second = fx.add_room(
            run_id, 2, name="Mirror Hall", room_occupancy_cap=30,
            target_dwell_minutes=12, min_dwell_minutes=4,
            sensory_intensity_level=3,
        )
        assert second["throughput_per_slot"] == 112
        assert fx.read_run(run_id)["effective_capacity"] == 112

        third = fx.add_room(
            run_id, 3, name="Signal Garden", room_occupancy_cap=25,
            target_dwell_minutes=20, min_dwell_minutes=8,
            sensory_intensity_level=5,
        )
        assert third["throughput_per_slot"] == 56
        run = fx.read_run(run_id)
        assert run["effective_capacity"] == 56
        assert run["effective_capacity_cap"] == 0

    def test_a_conditional_inspection_cap_becomes_the_new_winner(self):
        """The fourth term joins the minimum and takes it below the tightest room.

        PRD: "The run's `effective_capacity_cap` becomes this inspection's
        `allowed_occupancy_cap`, and the run's `effective_capacity` is recomputed
        as the tightest of the four ceilings, now including the new cap."
        PRD: "writes `allowed_occupancy_cap` as the `measured_egress_width_cm`
        divided by 2.03 centimetres per occupant and floored."

        Design: Difficulty/combinatorial_formula/capacity_nested_min_switches_arm_from_room_to_inspection_cap
        """
        bundle = fx.run_bundle()
        run_id = bundle["run"]["id"]
        fx.add_room(run_id, 1)
        fx.add_room(
            run_id, 2, name="Mirror Hall", room_occupancy_cap=30,
            target_dwell_minutes=12, min_dwell_minutes=4,
            sensory_intensity_level=3,
        )
        fx.add_room(
            run_id, 3, name="Signal Garden", room_occupancy_cap=25,
            target_dwell_minutes=20, min_dwell_minutes=8,
            sensory_intensity_level=5,
        )
        assert fx.read_run(run_id)["effective_capacity"] == 56

        inspection = fx.finalized_inspection(
            run_id, inspection_type="CAPACITY",
            create_overrides={"scheduled_for_utc": "2026-08-03T09:00:00Z"},
            measured_egress_width_cm=100.0, findings_count=3, severity="MINOR",
            findings_note="one leaf of the west door blocked by scenic",
        )
        assert inspection["outcome"] == "CONDITIONAL"
        assert inspection["allowed_occupancy_cap"] == 49

        run = fx.read_run(run_id)
        assert run["effective_capacity_cap"] == 49
        assert run["effective_capacity"] == 49

    def test_the_four_terms_are_a_nested_minimum_over_the_whole_room_set(self):
        """A roomier room cannot raise a minimum, and each throughput floors alone.

        PRD: "the smallest `throughput_per_slot` across every room of the run,
        which is the bottleneck room".
        PRD: "A cap of 0 means no inspection ceiling is in force and the first
        three terms alone decide."

        Design: Corner/calculations/effective_capacity_is_a_nested_min_over_rooms_venue_and_cap
        """
        bundle = fx.run_bundle()
        run_id = bundle["run"]["id"]
        assert fx.read_run(run_id)["effective_capacity"] == 0

        expectations = [
            (dict(room_sequence=1, name="Vestibule", room_occupancy_cap=40,
                  target_dwell_minutes=15, min_dwell_minutes=5,
                  sensory_intensity_level=2), 120, 120),
            (dict(room_sequence=2, name="Cascade Hall", room_occupancy_cap=30,
                  target_dwell_minutes=12, min_dwell_minutes=4,
                  sensory_intensity_level=3), 112, 112),
            (dict(room_sequence=3, name="Signal Room", room_occupancy_cap=20,
                  target_dwell_minutes=16, min_dwell_minutes=6,
                  sensory_intensity_level=4), 56, 56),
            (dict(room_sequence=4, name="Atrium Finale", room_occupancy_cap=100,
                  target_dwell_minutes=10, min_dwell_minutes=4,
                  sensory_intensity_level=2), 450, 56),
        ]
        for overrides, throughput, capacity in expectations:
            sequence = overrides.pop("room_sequence")
            room = validate_object(
                api_client.create_room(
                    f.room_payload(run_id, sequence, **overrides), PRODUCER
                ),
                201,
            )
            assert_room(room)
            assert room["throughput_per_slot"] == throughput
            assert fx.read_run(run_id)["effective_capacity"] == capacity

        rows, meta = validate_paginated(
            api_client.list_rooms(PRODUCER, {"run_id": run_id})
        )
        assert meta["total_count"] == 4
        assert [row["throughput_per_slot"] for row in rows] == [120, 112, 56, 450]
        run = fx.read_run(run_id)
        assert run["effective_capacity"] == 56
        assert run["effective_capacity_cap"] == 0

    def test_a_roomless_run_has_no_capacity_to_compute(self):
        """A window on a run with no rooms is a design error, not a zero ceiling.

        PRD: "A run with no rooms at all is not a run of capacity zero — it is a
        design error, and a request that would need to compute capacity for a
        roomless run is refused with `ERR_RUN_HAS_NO_ROOMS`."

        Design: Corner/calculations/effective_capacity_is_a_nested_min_over_rooms_venue_and_cap
        """
        bundle = fx.run_bundle()
        run_id = bundle["run"]["id"]
        assert fx.read_run(run_id)["effective_capacity"] == 0
        # The empty room set is not an unbounded capacity: the window is refused.
        # Two rules bite at once here and the PRD does not order them.
        validate_error_is_one_of(
            api_client.create_slot(f.slot_payload(run_id), PRODUCER),
            [
                ApiErrorId.ERR_RUN_HAS_NO_ROOMS.value,
                ApiErrorId.ERR_SLOT_CAPACITY_ABOVE_RUN.value,
            ],
        )
        assert_total_count(api_client.list_slots(PRODUCER, {"run_id": run_id}), 0)


class TestKitDeploymentBlocksASecondRun:
    """The blocking state is a side effect of the first run, never set by hand."""

    def test_a_deployed_kit_refuses_the_second_run(self):
        """The kit left READY by its own create is DEPLOYED by the first run.

        PRD: "On success `created_by_user_id` is copied from the creating
        `X-User-ID` — the identity that segregation of duties will later bar from
        granting this run's extension — and the deployed kit moves `READY →
        DEPLOYED`, taking its own version increment."
        PRD: "The kit must be `READY`, or the create is refused with
        `ERR_KIT_NOT_READY`".

        Design: Difficulty/cross_entity_state_dependency/run_creation_blocked_by_the_kit_already_deployed_elsewhere
        """
        bundle = fx.run_bundle(lease_active=True)
        kit_id = bundle["kit"]["id"]
        deployed = fx.read_kit(kit_id)
        assert deployed["status"] == "DEPLOYED"

        validate_error(
            api_client.create_run(
                f.run_payload(
                    bundle["venue"]["id"], bundle["agreement"]["id"], kit_id,
                    run_name="Neon Atrium NYC winter",
                    scheduled_open_date="2026-11-01",
                    scheduled_close_date="2026-12-31",
                ),
                PRODUCER,
            ),
            ApiErrorId.ERR_KIT_NOT_READY.value,
        )
        rows, meta = validate_paginated(
            api_client.list_runs(PRODUCER, {"build_kit_id": kit_id})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == bundle["run"]["id"]
        assert fx.read_kit(kit_id)["version"] == deployed["version"]

    def test_a_second_ready_kit_makes_the_identical_payload_succeed(self):
        """Only the kit changes, and the same winter run is accepted.

        PRD: "a `READY` kit is additionally refused with
        `ERR_KIT_CONDITION_BELOW_THRESHOLD` when its `condition_score` has fallen
        below 60.00 or its `localization_status` is not `LOCALIZED`".
        PRD: "The venue must be in `PERMIT_ISSUED` or `LEASE_ACTIVE` — a run may
        be planned as soon as the permit exists, before the lease is switched
        on."

        Design: Difficulty/cross_entity_state_dependency/run_creation_blocked_by_the_kit_already_deployed_elsewhere
        """
        bundle = fx.run_bundle(lease_active=True)
        first_kit_id = bundle["kit"]["id"]
        second_kit = fx.create_kit()
        assert second_kit["status"] == "READY"
        assert second_kit["localization_status"] == "LOCALIZED"
        assert second_kit["condition_score"] == 100.00
        assert second_kit["reuse_cycle_count"] == 0

        winter = validate_object(
            api_client.create_run(
                f.run_payload(
                    bundle["venue"]["id"], bundle["agreement"]["id"],
                    second_kit["id"],
                    run_name="Neon Atrium NYC winter",
                    scheduled_open_date="2026-11-01",
                    scheduled_close_date="2026-12-31",
                ),
                PRODUCER,
            ),
            201,
        )
        assert_run(winter)
        assert winter["run_status"] == "PLANNED"
        assert winter["clearance_status"] == "UNCLEARED"
        assert winter["build_kit_id"] == second_kit["id"]
        assert winter["created_by_user_id"] == "producer-1"
        assert fx.read_kit(second_kit["id"])["status"] == "DEPLOYED"
        assert fx.read_kit(first_kit_id)["status"] == "DEPLOYED"


class TestRunCreationShapeAndEligibility:
    """The busiest gate in the API, checked rung by rung."""

    def test_every_field_without_a_default_is_mandatory(self):
        """An omitted required field is a shape failure before any lookup runs.

        PRD: "Every required input field is present; every type matches; every
        enum value is a member of its declared set; every numeric value lies
        inside its declared range; dates are ten-character ISO calendar dates;
        instants are ISO 8601 UTC instants".
        PRD: "plus a `run_name` of 1 to 120 characters, the `scheduled_open_date`
        and `scheduled_close_date`, the `base_ticket_price_cents` list price from
        1 to 100000, the timed-entry cadence `timed_slot_minutes` from 15 to 120,
        and optionally `max_group_size`, which defaults to 12".

        Design: Corner/entities/run_creation_missing_required_fields_is_rejected
        """
        venue = fx.venue_permitted()
        kit = fx.create_kit()
        agreement = fx.agreement_active()
        base = f.run_payload(venue["id"], agreement["id"], kit["id"])

        for missing in (
            "base_ticket_price_cents", "timed_slot_minutes", "venue_id",
            "run_name", "scheduled_open_date", "scheduled_close_date",
            "license_agreement_id", "build_kit_id",
        ):
            payload = {k: v for k, v in base.items() if k != missing}
            validate_error(
                api_client.create_run(payload, PRODUCER),
                ApiErrorId.ERR_VALIDATION.value,
                422,
            )

        venue_payload = f.venue_payload(site_name="No cap")
        venue_payload.pop("buildout_cap_cents")
        venue_payload.pop("sprinklered")
        validate_error(
            api_client.create_venue(venue_payload, VOM),
            ApiErrorId.ERR_VALIDATION.value,
            422,
        )
        agreement_payload = f.agreement_payload()
        agreement_payload.pop("approval_scopes")
        validate_error(
            api_client.create_agreement(agreement_payload, LM),
            ApiErrorId.ERR_VALIDATION.value,
            422,
        )

        assert_total_count(api_client.list_runs(PRODUCER), 0)
        assert_total_count(api_client.list_venues(VOM), 1)
        assert fx.read_kit(kit["id"])["status"] == "READY"

    def test_the_eligibility_gates_report_in_their_declared_order(self):
        """Territory, kit condition and the agreement state are each reachable.

        PRD: "the venue's `city_code` must appear in that agreement's
        `territory_city_codes`, or the create is refused with
        `ERR_CITY_NOT_IN_TERRITORY`".
        PRD: "The agreement must be `ACTIVE`, or the create is refused with
        `ERR_AGREEMENT_NOT_ACTIVE`".

        Design: Corner/errors/run_creation_eligibility_errors_are_each_reachable
        """
        venue = fx.venue_permitted()
        good_kit = fx.create_kit()
        weak_kit = fx.create_kit(initial_condition_score=55.0)
        nyc = fx.agreement_active()
        lax = fx.agreement_active(
            ip_title="Neon Atrium West", territory_city_codes=["LAX"]
        )
        draft = fx.create_agreement(
            ip_title="Neon Atrium Draft", territory_city_codes=["LAX"]
        )

        validate_error(
            api_client.create_run(
                f.run_payload(venue["id"], lax["id"], good_kit["id"]), PRODUCER
            ),
            ApiErrorId.ERR_CITY_NOT_IN_TERRITORY.value,
            409,
        )
        validate_error(
            api_client.create_run(
                f.run_payload(venue["id"], nyc["id"], weak_kit["id"]), PRODUCER
            ),
            ApiErrorId.ERR_KIT_CONDITION_BELOW_THRESHOLD.value,
            409,
        )
        validate_error(
            api_client.create_run(
                f.run_payload(venue["id"], draft["id"], weak_kit["id"]), PRODUCER
            ),
            ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value,
            409,
        )
        validate_error(
            api_client.create_run(
                f.run_payload(venue["id"], nyc["id"], UNKNOWN_UUID), PRODUCER
            ),
            ApiErrorId.ERR_KIT_NOT_FOUND.value,
            404,
        )

        accepted = validate_object(
            api_client.create_run(
                f.run_payload(venue["id"], nyc["id"], good_kit["id"]), PRODUCER
            ),
            201,
        )
        assert accepted["run_status"] == "PLANNED"
        rows, meta = validate_paginated(
            api_client.list_runs(PRODUCER, {"venue_id": venue["id"]})
        )
        assert meta["total_count"] == 1
        ready, ready_meta = validate_paginated(
            api_client.list_kits(VOM, {"status": "READY"})
        )
        assert ready_meta["total_count"] == 1
        assert ready[0]["id"] == weak_kit["id"]

    def test_omitted_optional_fields_take_their_declared_defaults(self):
        """Six defaults across five entities, each read back from the stored row.

        PRD: "optionally the `pricing_tier` of `OFFPEAK`, `STANDARD`, `PEAK` or
        `PREMIUM` (defaulting to `STANDARD`), and optionally
        `wheelchair_positions`, which defaults to 4 and may not exceed
        `base_capacity`."
        PRD: "Two flags carry the accessibility promises: `has_quiet_bypass`,
        false when omitted, records whether a route around the room exists, and
        `wheelchair_accessible`, true when omitted".

        Design: Corner/entities/omitted_optional_fields_take_their_declared_defaults
        """
        bare_venue = f.venue_payload()
        bare_venue.pop("sprinklered")
        venue = validate_object(api_client.create_venue(bare_venue, VOM), 201)
        assert venue["lease_extension_option_days"] == 0
        assert venue["kit_reuse_credit_cents"] == 0
        assert venue["sprinklered"] is False
        validate_success(api_client.submit_permit_package(venue["id"], {}, VOM))
        permitted = validate_success(
            api_client.decide_permit(venue["id"], {"decision": "ISSUED"}, OFFICER)
        )
        assert permitted["permit_conditions_note"] is None

        bare_kit = f.kit_payload()
        bare_kit.pop("initial_condition_score")
        kit = validate_object(api_client.create_kit(bare_kit, VOM), 201)
        assert kit["initial_condition_score"] == 100.00
        assert kit["condition_score"] == 100.00
        assert kit["origin_run_id"] is None
        assert kit["localization_status"] == "LOCALIZED"

        agreement = fx.agreement_active()
        bare_run = f.run_payload(venue["id"], agreement["id"], kit["id"])
        bare_run.pop("max_group_size")
        run = validate_object(api_client.create_run(bare_run, PRODUCER), 201)
        assert run["max_group_size"] == 12

        bare_room = f.room_payload(run["id"], 1)
        bare_room.pop("has_quiet_bypass")
        bare_room.pop("wheelchair_accessible")
        room = validate_object(api_client.create_room(bare_room, PRODUCER), 201)
        assert room["has_quiet_bypass"] is False
        assert room["wheelchair_accessible"] is True
        assert room["throughput_per_slot"] == 120

        bare_slot = f.slot_payload(run["id"])
        bare_slot.pop("pricing_tier")
        bare_slot.pop("wheelchair_positions")
        slot = validate_object(api_client.create_slot(bare_slot, PRODUCER), 201)
        assert slot["pricing_tier"] == "STANDARD"
        assert slot["wheelchair_positions"] == 4

        guest = validate_object(
            api_client.create_guest(f.guest_payload(), AGENT), 201
        )
        assert guest["loyalty_tier"] == "VISITOR"
        assert guest["accommodation_profile"] == []
        assert guest["status"] == "ACTIVE"

        bare_staff = {
            "run_id": run["id"], "full_name": "Ada Perez",
            "staff_role": "PERFORMER",
        }
        member = validate_object(
            api_client.create_staff_member(bare_staff, PRODUCER), 201
        )
        assert member["certifications"] == []
        assert member["incident_count"] == 0
        assert member["status"] == "CANDIDATE"
        assert member["cert_coverage_pct"] == 0.00

    def test_client_supplied_computed_fields_are_discarded_not_refused(self):
        """The server writes its own derived values over anything the client sent.

        PRD: "Releasing a slot moves it `DRAFT → OPEN`, sets both
        `released_capacity` and `available_capacity` to `base_capacity` and
        stamps `released_at` from the clock."
        PRD: "it is derived, and the derivation is a first-match-wins ladder
        evaluated in exactly this order."

        Design: Corner/entities/computed_and_system_fields_supplied_by_the_client_are_ignored_input
        """
        bundle = fx.run_with_room()
        run_id = bundle["run"]["id"]
        guest = fx.create_guest()
        inspection = fx.scheduled_inspection(
            run_id, inspection_type="SENSORY",
            scheduled_for_utc="2026-09-01T09:00:00Z",
        )

        venue = validate_object(
            api_client.create_venue(
                f.venue_payload(
                    site_name="Self-promoted site", status="LEASE_ACTIVE",
                    egress_capacity=999, permitted_occupancy_load=500, version=44,
                ),
                VOM,
            ),
            201,
        )
        assert venue["status"] == "DRAFT"
        assert venue["egress_capacity"] == 197
        assert venue["permitted_occupancy_load"] == 0
        assert venue["version"] == 1

        slot = validate_object(
            api_client.create_slot(
                f.slot_payload(
                    run_id, released_capacity=20, available_capacity=999,
                    sold_capacity=7, status="OPEN",
                ),
                PRODUCER,
            ),
            201,
        )
        assert slot["status"] == "DRAFT"
        assert slot["released_capacity"] == 0
        assert slot["held_capacity"] == 0
        assert slot["sold_capacity"] == 0
        assert slot["available_capacity"] == 0

        released = validate_success(api_client.release_slot(slot["id"], PRODUCER))
        assert released["released_capacity"] == 20
        assert released["available_capacity"] == 20

        order = validate_object(
            api_client.create_order(
                f.order_payload(
                    slot["id"], guest["id"], unit_price_cents=1,
                    net_amount_cents=1, status="CONFIRMED",
                ),
                AGENT,
            ),
            201,
        )
        assert order["unit_price_cents"] == 32250
        assert order["net_amount_cents"] == 64500
        assert order["status"] == "PENDING"
        assert order["net_collected_cents"] == 0
        assert fx.read_guest(guest["id"])["experience_credit_cents"] == 0

        finalized = validate_success(
            api_client.finalize_inspection(
                inspection["id"],
                f.inspection_finalize_payload(
                    findings_note="clean", outcome="FAIL",
                    allowed_occupancy_cap=3,
                ),
                OFFICER,
            )
        )
        assert finalized["outcome"] == "PASS"
        assert finalized["allowed_occupancy_cap"] == 197
        run = fx.read_run(run_id)
        assert run["clearance_status"] == "UNCLEARED"
        assert run["effective_capacity_cap"] == 0

    def test_enum_range_and_format_violations_are_all_the_same_shape_failure(self):
        """Seven different malformed values, one error identifier.

        PRD: "the `sensory_intensity_level` from 1 (calm) to 5 (extreme)."
        PRD: "`approval_scopes` is a non-empty, duplicate-free subset of
        `CREATIVE_EXECUTION`, `MERCHANDISE` and `MARKETING`;
        `territory_city_codes` is a non-empty array of three-character uppercase
        city codes."

        Design: Corner/entities/enum_range_and_date_format_constraints_are_rejected
        """
        bundle = fx.run_bundle()
        run_id = bundle["run"]["id"]

        probes = [
            lambda: api_client.create_inspection(
                f.inspection_payload(
                    run_id, inspection_type="FIRE_DRILL",
                    scheduled_for_utc="2026-09-01T09:00:00Z",
                ),
                OFFICER,
            ),
            lambda: api_client.create_room(
                f.room_payload(run_id, 1, sensory_intensity_level=9), PRODUCER
            ),
            lambda: api_client.create_room(
                f.room_payload(run_id, 1, min_dwell_minutes=30), PRODUCER
            ),
            lambda: api_client.create_venue(
                f.venue_payload(city_code="nyc1", site_name="Bad city code"), VOM
            ),
            lambda: api_client.create_venue(
                f.venue_payload(lease_start_date="2026-8-1", site_name="Bad date"),
                VOM,
            ),
            lambda: api_client.create_inspection(
                f.inspection_payload(run_id, scheduled_for_utc="2026-09-01 09:00"),
                OFFICER,
            ),
            lambda: api_client.create_agreement(
                f.agreement_payload(
                    ip_title="Duplicate scopes",
                    approval_scopes=["CREATIVE_EXECUTION", "CREATIVE_EXECUTION"],
                ),
                LM,
            ),
            lambda: api_client.create_agreement(
                f.agreement_payload(
                    ip_title="Rate out of range", royalty_rate_bps=10001
                ),
                LM,
            ),
        ]
        for probe in probes:
            validate_error(probe(), ApiErrorId.ERR_VALIDATION.value, 422)

        assert_total_count(api_client.list_rooms(PRODUCER), 0)
        assert_total_count(api_client.list_inspections(OFFICER), 0)
        assert_total_count(api_client.list_agreements(LM), 1)

    def test_duplicate_codes_emails_and_room_sequences_are_rejected_in_their_own_scope(self):
        """Three uniqueness rules with three different scopes.

        PRD: "unique among the rooms of that run, with a collision refused as
        `ERR_DUPLICATE_ROOM_SEQUENCE`".

        Design: Corner/validations/duplicate_kit_code_guest_email_and_room_sequence_are_rejected
        """
        bundle = fx.run_bundle()
        first_run = bundle["run"]["id"]
        fx.add_room(first_run, 1)
        taken_code = fx.read_kit(bundle["kit"]["id"])["kit_code"]

        validate_error(
            api_client.create_kit(
                f.kit_payload(code=taken_code, module_count=12), VOM
            ),
            ApiErrorId.ERR_DUPLICATE_KIT_CODE.value,
            409,
        )
        second_kit = validate_object(
            api_client.create_kit(
                f.kit_payload(code="KIT-P9B-777", module_count=12), VOM
            ),
            201,
        )

        mixed = validate_object(
            api_client.create_guest(
                f.guest_payload(email="Ada@Example.com", display_name="Ada Nwosu"),
                AGENT,
            ),
            201,
        )
        assert mixed["email"] == "Ada@Example.com"
        validate_error(
            api_client.create_guest(
                f.guest_payload(email="ada@example.com", display_name="Ada N."),
                AGENT,
            ),
            ApiErrorId.ERR_DUPLICATE_GUEST_EMAIL.value,
            409,
        )

        validate_error(
            api_client.create_room(
                f.room_payload(
                    first_run, 1, name="Second Vestibule", room_occupancy_cap=30,
                    target_dwell_minutes=10, min_dwell_minutes=4,
                ),
                PRODUCER,
            ),
            ApiErrorId.ERR_DUPLICATE_ROOM_SEQUENCE.value,
            409,
        )
        assert_total_count(
            api_client.list_rooms(PRODUCER, {"run_id": first_run}), 1
        )

        second_run = validate_object(
            api_client.create_run(
                f.run_payload(
                    bundle["venue"]["id"], bundle["agreement"]["id"],
                    second_kit["id"],
                    run_name="Neon Atrium NYC second stage",
                ),
                PRODUCER,
            ),
            201,
        )
        validate_object(
            api_client.create_room(f.room_payload(second_run["id"], 1), PRODUCER),
            201,
        )


class TestThemedRoomImmutability:
    """The one entity with no version and no status of its own."""

    def test_a_room_carries_no_version_and_no_status(self):
        """The room's own row has neither field, yet its create advances the run.

        PRD: "Rooms are the one resource in this system with no `version` and no
        `status`, so every room of a run counts towards capacity from the moment
        it is written."
        PRD: "they are immutable once written: there is no way to edit or remove
        a room, so a mistake means a new run."

        Design: Corner/entities/themed_room_is_immutable_with_no_version_and_no_update_endpoint
        """
        bundle = fx.run_bundle()
        run_id = bundle["run"]["id"]
        assert fx.read_run(run_id)["version"] == 1

        room = validate_object(
            api_client.create_room(f.room_payload(run_id, 1), PRODUCER), 201
        )
        assert room["throughput_per_slot"] == 120
        assert "version" not in room
        assert "status" not in room

        fetched = validate_object(api_client.get_room(room["id"], OFFICER))
        assert set(fetched) == set(room)
        assert "version" not in fetched
        assert "status" not in fetched
        assert_total_count(api_client.list_rooms(PRODUCER, {"run_id": run_id}), 1)

        run = fx.read_run(run_id)
        assert run["effective_capacity"] == 120
        assert run["version"] == 2


class TestKitAndRunCycle:
    """The declared cyclic reference pair, reachable from either end."""

    def test_both_directions_of_the_cycle_are_reachable_through_filters(self):
        """A kit may name a run, and a run names its kit; both filters resolve.

        PRD: "Venues filter on `city_code` and `status`."
        PRD: "the deployed kit moves `READY → DEPLOYED`, taking its own version
        increment."

        Design: Corner/entities/kit_and_run_cyclic_reference_pair_is_reachable_from_both_ends
        """
        bundle = fx.run_bundle()
        first_kit_id = bundle["kit"]["id"]
        first_run_id = bundle["run"]["id"]

        second_kit = validate_object(
            api_client.create_kit(
                f.kit_payload(
                    code="KIT-P9B-002", module_count=14,
                    initial_condition_score=92.5,
                    localization_language="es-MX",
                    origin_run_id=first_run_id,
                ),
                VOM,
            ),
            201,
        )
        assert second_kit["origin_run_id"] == first_run_id
        assert second_kit["condition_score"] == 92.50
        assert second_kit["status"] == "READY"

        by_origin, origin_meta = validate_paginated(
            api_client.list_kits(VOM, {"origin_run_id": first_run_id})
        )
        assert origin_meta["total_count"] == 1
        assert by_origin[0]["id"] == second_kit["id"]

        by_kit, kit_meta = validate_paginated(
            api_client.list_runs(PRODUCER, {"build_kit_id": first_kit_id})
        )
        assert kit_meta["total_count"] == 1
        assert by_kit[0]["id"] == first_run_id

        ready, ready_meta = validate_paginated(
            api_client.list_kits(VOM, {"status": "READY"})
        )
        assert ready_meta["total_count"] == 1
        assert ready[0]["id"] == second_kit["id"]


class TestTwoStandingsOnOneRow:
    """The operational dimension and the compliance dimension move separately."""

    def test_clearance_oscillates_while_the_lifecycle_only_advances(self):
        """The run reaches the (OPEN, UNCLEARED) combination and comes back.

        PRD: "A run can be commercially `OPEN` while compliance-wise
        `SUSPENDED`, and a run can be `CLEARED` while still `PLANNED`."
        PRD: "`SUSPEND` moves a cleared person `CLEARED → SUSPENDED`, cancels
        every one of that person's `SCHEDULED` shifts — each cancelled shift
        taking its own version increment — and re-derives the run's gate,
        dropping the run to `UNCLEARED` when that craft no longer has a cleared
        member."

        Design: Corner/state_machines/run_status_and_clearance_status_advance_independently
        """
        bundle = fx.run_with_room(lease_active=True)
        run_id = bundle["run"]["id"]
        agreement_id = bundle["agreement"]["id"]
        roster = fx.full_roster(run_id)
        submission = fx.submission_in_review(agreement_id, run_id)
        fx.open_slot(run_id)

        staged = fx.read_run(run_id)
        assert staged["run_status"] == "PLANNED"
        assert staged["clearance_status"] == "UNCLEARED"
        assert staged["effective_capacity"] == 120

        validate_success(
            api_client.decide_submission(
                submission["id"],
                f.submission_decision_payload("APPROVED", "cleared for build"),
                REP,
            )
        )
        cleared = fx.read_run(run_id)
        assert cleared["run_status"] == "PLANNED"
        assert cleared["clearance_status"] == "CLEARED"

        opened = validate_success(api_client.open_run(run_id, PRODUCER))
        assert opened["run_status"] == "OPEN"
        assert opened["clearance_status"] == "CLEARED"

        suspended = validate_success(
            api_client.decide_staff_status(
                roster["technician"]["id"],
                f.staff_status_decision_payload(
                    "SUSPEND", note="rigging licence lapsed mid-run"
                ),
                OFFICER,
            )
        )
        assert suspended["status"] == "SUSPENDED"
        broken = fx.read_run(run_id)
        assert broken["run_status"] == "OPEN"
        assert broken["clearance_status"] == "UNCLEARED"

        validate_success(
            api_client.decide_staff_status(
                roster["technician"]["id"],
                f.staff_status_decision_payload("REINSTATE"),
                OFFICER,
            )
        )
        restored = fx.read_run(run_id)
        assert restored["run_status"] == "OPEN"
        assert restored["clearance_status"] == "CLEARED"
