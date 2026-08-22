"""Applying, replacing and voiding official identification devices."""
from test_helpers import (
    ApiErrorId,
    DEFAULT_SERIAL_START,
    ain_for_serial,
    apply_device,
    apply_tag_payload,
    assert_sighting,
    assert_tag_lot_partition,
    create_active_premises,
    create_approved_supplier,
    create_device_supplier_payload,
    create_movement_payload,
    create_premises_payload,
    issue_lot,
    make_producer_headers,
    make_program_admin_headers,
    read_animal,
    read_premises,
    read_tag,
    read_tag_lot,
    register_premises,
    register_producer,
    replace_tag_payload,
    setup_animal_scenario,
    setup_supplier_with_defects,
    sightings_of_animal,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_program_admin_headers("admin-reg")


class TestDeviceApplication:
    def test_first_observation_is_immutable_and_carries_no_mutation_stamp(self, api):
        """PRD §2.4: "`Sighting` rows are the single exception. A sighting is an immutable observation, so a sighting carries only `id` and `created_at`; it has no `updated_at` field and no `version` field. Marking a sighting as retracted is modelled by its own `reversed` flag rather than by a mutation stamp."
        PRD §3.4: "A `TAG_APPLIED` sighting is appended with `sequence_no` 1 and `observed_at` taken from the logical clock."

        Design: Corner/entities/sighting_is_immutable_and_carries_no_version_field
        """
        scenario = setup_animal_scenario(capacity=10, quantity=10, legal_name="Immutable Ranch")
        rows = sightings_of_animal(scenario["animal"]["id"], headers=scenario["producer_headers"])
        assert len(rows) == 1

        sighting = validate_success(
            api.get_sighting(rows[0]["id"], scenario["producer_headers"])
        )
        assert "id" in sighting and "created_at" in sighting
        assert "version" not in sighting, "an immutable sighting exposes no version field"
        assert "updated_at" not in sighting, "an immutable sighting exposes no updated_at field"
        assert_sighting(sighting)
        assert sighting["sequence_no"] == 1
        assert sighting["sighting_type"] == "TAG_APPLIED"
        assert sighting["reversed"] is False

    def test_application_at_a_premises_still_pending_review_is_refused(self, api):
        """PRD §3.4: "Beyond the referential rules, the supplier must be `APPROVED`, the birth premises must be `ACTIVE` in registration and must not be `QUARANTINED` in health, the lot must be neither `RECALLED` nor `VOIDED` nor `DEPLETED`, and admitting one more active animal must not push the birth premises past its `capacity`, else `ERR_PREMISES_AT_CAPACITY`."
        PRD §2.5: "A premises involved in applying a tag, reporting a movement, receiving a movement, retiring a tag or being issued a lot must have `registration_status` equal to `ACTIVE`, else `ERR_PREMISES_NOT_ACTIVE`."

        Design: Corner/validations/tag_application_rejected_at_pending_review_premises
        """
        producer = register_producer(legal_name="Pending Co")
        active_premises = create_active_premises(producer["id"], capacity=10)
        pending_premises = register_premises(producer["id"], capacity=10)
        assert pending_premises["registration_status"] == "PENDING_REVIEW"

        supplier = create_approved_supplier()
        lot = issue_lot(supplier["id"], active_premises["id"], DEFAULT_SERIAL_START, 10)

        resp = api.apply_tag(
            lot["id"],
            apply_tag_payload(ain_for_serial(DEFAULT_SERIAL_START), pending_premises["id"]),
            make_producer_headers(producer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PREMISES_NOT_ACTIVE, expected_status=409)

        lot_after = read_tag_lot(lot["id"])
        assert lot_after["applied_count"] == 0
        assert lot_after["status"] == "ISSUED"

        rows, meta = validate_paginated(
            api.list_animals(ADMIN, params={"birth_premises_id": pending_premises["id"]})
        )
        assert rows == [] and meta["total_count"] == 0

    def test_globally_unique_pin_supplier_code_and_ain_reject_their_duplicates(self, api):
        """PRD §3.1: "A registration supplies `producer_id`, a `pin` — the Premises Identification Number, exactly seven characters over the digits 0–9 and uppercase A–Z, and globally unique across the programme, with a collision rejected as `ERR_DUPLICATE_PIN` — an `operation_type` of `COW_CALF`, `FEEDLOT`, `MARKET` or `HARVEST_FACILITY`, the two-letter uppercase `state_code` of the location itself, and a `capacity` of at least one animal."
        PRD §3.2: "A `ProgramAdmin` registers a supplier with its `company_name`, a globally unique four-character `supplier_code` over uppercase A–Z and digits — a collision is `ERR_DUPLICATE_SUPPLIER_CODE` — and an optional `aid_prefix`, the exactly-three-digit country prefix that will lead every AIN the supplier stamps."
        PRD §3.4: "No two devices in the programme may carry the same `ain`, a collision being `ERR_DUPLICATE_AIN`."

        Design: Corner/validations/duplicate_pin_supplier_code_and_ain_are_rejected
        """
        producer = register_producer(legal_name="Unique Co")
        producer_headers = make_producer_headers(producer["id"])
        premises = create_active_premises(producer["id"], pin="COU0001", capacity=10)
        supplier = create_approved_supplier(company_name="AllFlex North", supplier_code="AFNA")
        lot = issue_lot(supplier["id"], premises["id"], DEFAULT_SERIAL_START, 10)
        apply_device(lot["id"], producer["id"], DEFAULT_SERIAL_START, premises["id"])

        duplicate_pin = api.create_premises(
            create_premises_payload(
                producer["id"], pin="COU0001", operation_type="FEEDLOT", capacity=10
            ),
            producer_headers,
        )
        validate_error(duplicate_pin, ApiErrorId.ERR_DUPLICATE_PIN, expected_status=409)

        duplicate_code = api.create_device_supplier(
            create_device_supplier_payload(company_name="Copycat Devices", supplier_code="AFNA"),
            ADMIN,
        )
        validate_error(
            duplicate_code, ApiErrorId.ERR_DUPLICATE_SUPPLIER_CODE, expected_status=409
        )

        duplicate_ain = api.apply_tag(
            lot["id"],
            apply_tag_payload(
                ain_for_serial(DEFAULT_SERIAL_START), premises["id"], birth_date="2026-04-19"
            ),
            producer_headers,
        )
        validate_error(duplicate_ain, ApiErrorId.ERR_DUPLICATE_AIN, expected_status=409)

        lot_after = read_tag_lot(lot["id"])
        assert lot_after["applied_count"] == 1
        assert lot_after["unapplied_count"] == 9

    def test_same_premises_move_and_capacity_ceiling_are_both_refused(self, api):
        """PRD §3.5: "The two premises must differ, else `ERR_SAME_PREMISES_MOVE`, and the origin must be exactly where the animal currently stands: the animal's `current_premises_id` must equal `origin_premises_id`, else `ERR_ANIMAL_NOT_AT_PREMISES`."
        PRD §3.4: "Beyond the referential rules, the supplier must be `APPROVED`, the birth premises must be `ACTIVE` in registration and must not be `QUARANTINED` in health, the lot must be neither `RECALLED` nor `VOIDED` nor `DEPLETED`, and admitting one more active animal must not push the birth premises past its `capacity`, else `ERR_PREMISES_AT_CAPACITY`."
        PRD §3.3: "From `ISSUED` the lot moves to `ACTIVE` on the first successful application against it — that is, when its `applied_count` goes from 0 to 1 as part of that request — and from `ACTIVE` to `DEPLETED` whenever any application, retirement, replacement or void drives its `unapplied_count` to 0."

        Design: Corner/validations/same_premises_move_and_capacity_and_exhaustion_are_rejected
        """
        producer = register_producer(legal_name="Capacity Co")
        producer_headers = make_producer_headers(producer["id"])
        small = create_active_premises(producer["id"], operation_type="COW_CALF", capacity=1)
        roomy = create_active_premises(producer["id"], operation_type="FEEDLOT", capacity=5)
        supplier = create_approved_supplier()

        single_lot = issue_lot(supplier["id"], small["id"], DEFAULT_SERIAL_START, 1)
        assert single_lot["quantity"] == 1
        ten_lot = issue_lot(supplier["id"], roomy["id"], DEFAULT_SERIAL_START + 1, 10)

        animal = apply_device(single_lot["id"], producer["id"], DEFAULT_SERIAL_START, small["id"])

        depleted = read_tag_lot(single_lot["id"])
        assert depleted["status"] == "DEPLETED", "its only serial has been materialised"
        assert depleted["unapplied_count"] == 0

        same_premises = api.create_movement_event(
            create_movement_payload(
                animal["id"], small["id"], small["id"], "2026-08-01T00:00:00Z"
            ),
            producer_headers,
        )
        validate_error(same_premises, ApiErrorId.ERR_SAME_PREMISES_MOVE, expected_status=422)

        at_capacity = api.apply_tag(
            ten_lot["id"],
            apply_tag_payload(ain_for_serial(DEFAULT_SERIAL_START + 1), small["id"]),
            producer_headers,
        )
        validate_error(at_capacity, ApiErrorId.ERR_PREMISES_AT_CAPACITY, expected_status=409)

        assert read_premises(small["id"])["animal_count"] == 1


class TestDeviceReplacement:
    def test_replacement_chain_is_traversable_through_replaces_tag_id(self, api):
        """PRD §3.4: "Replacement is a producer action available only while the old device is `APPLIED` and the tagged animal is `ACTIVE`, and it supplies a `replacement_ain` and the `tag_lot_id` of the lot the replacement serial comes from. The old device moves `APPLIED → REPLACED`. A new device is materialised in `APPLIED` with `animal_id` unchanged and `replaces_tag_id` pointing back at the device it supersedes, which is what makes replacement chains traversable."
        PRD §3.4: "The old lot's `applied_count` falls by one while its `replaced_count` rises by one; the new lot's `applied_count` rises by one and its `unapplied_count` falls by one, moving it from `ISSUED` to `ACTIVE` or from `ACTIVE` to `DEPLETED` as applicable. The animal's `ain` is re-derived from the replacement device. Notably, **no sighting is appended** — a replacement is a device event, not an observation, so the animal's location and `sighting_count` are untouched."
        PRD §3.4: "Devices may be listed and filtered by `tag_lot_id`, `animal_id`, `replaces_tag_id`, `device_status` and `ain`."

        Design: Corner/entities/tag_replacement_chain_is_discoverable_through_self_referential_fk
        """
        scenario = setup_animal_scenario(capacity=10, quantity=10, legal_name="Chain Ranch")
        old_tag = scenario["tag"]
        replacement_ain = ain_for_serial(DEFAULT_SERIAL_START + 1)

        new_tag = validate_success(
            api.replace_tag(
                old_tag["id"],
                replace_tag_payload(replacement_ain, scenario["lot"]["id"]),
                scenario["producer_headers"],
            ),
            expected_status=201,
        )

        assert read_tag(old_tag["id"])["device_status"] == "REPLACED"
        assert new_tag["device_status"] == "APPLIED"
        assert new_tag["replaces_tag_id"] == old_tag["id"]
        assert new_tag["animal_id"] == scenario["animal"]["id"]

        animal_after = read_animal(scenario["animal"]["id"])
        assert animal_after["ain"] == replacement_ain
        assert animal_after["sighting_count"] == 1, "a replacement appends no observation"

        lot_after = read_tag_lot(scenario["lot"]["id"])
        assert lot_after["applied_count"] == 1
        assert lot_after["replaced_count"] == 1
        assert lot_after["unapplied_count"] == 8
        assert_tag_lot_partition(lot_after)

        successors, meta = validate_paginated(
            api.list_tags(ADMIN, params={"replaces_tag_id": old_tag["id"]})
        )
        assert meta["total_count"] == 1
        assert successors[0]["id"] == new_tag["id"]


class TestRecalledLotBeatsSerialRange:
    def test_recalled_lot_answers_lot_not_issuable_not_ain_out_of_range(self, api):
        """PRD §2.5: "A tag lot whose status was forced by an external event — `RECALLED` or `VOIDED` — cannot supply an application and yields `ERR_LOT_NOT_ISSUABLE`; a `DEPLETED` lot is instead treated as a capacity failure and is handled in band 16; every other invalid transition yields `ERR_INVALID_STATE`."
        PRD §2.5: "Guards `POST /tag-lots/{id}/apply-tag`, `POST /tags/{id}/replace`, `POST /tags/{id}/retire` and `POST /movement-events`, yielding `ERR_AIN_OUT_OF_LOT_RANGE`, `ERR_LOT_PREMISES_MISMATCH`, `ERR_ANIMAL_NOT_AT_PREMISES`, `ERR_NOT_HARVEST_FACILITY` or `ERR_SAME_PREMISES_MOVE` as detailed in Sections 3.4, 3.5 and 3.8."
        PRD §3.3: "`VOIDED` and `RECALLED` are both terminal lot states, and a lot in either of them that is addressed for an application is refused with `ERR_LOT_NOT_ISSUABLE` — a distinct outcome from the exhaustion of a depleted lot."

        Design: Difficulty/priority_pair_validation_conflict/state_lot_not_issuable_beats_referential_ain_out_of_range
        """
        scenario = setup_supplier_with_defects(
            lot_quantity=4000,
            defect_count=11,
            premises_capacity=40,
            operation_type="COW_CALF",
        )
        lot = read_tag_lot(scenario["lot"]["id"])
        assert lot["status"] == "RECALLED"

        out_of_range_ain = ain_for_serial(DEFAULT_SERIAL_START + 9998)
        resp = api.apply_tag(
            lot["id"],
            apply_tag_payload(
                out_of_range_ain, scenario["premises"]["id"], birth_date="2026-02-10"
            ),
            scenario["producer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_ISSUABLE, expected_status=409)

    def test_refused_application_on_a_recalled_lot_materialises_nothing(self, api):
        """PRD §3.2: "A supplier that is `APPROVED` and whose recomputed score falls below 70.00 transitions to `SUSPENDED`; a supplier that is already `SUSPENDED` and whose recomputed score falls below 40.00 transitions to `REVOKED`, which is terminal — no further transition out of `REVOKED` is permitted."
        PRD §3.2: "Both of those transitions carry the same collateral consequence: every tag lot belonging to that supplier whose status is `ISSUED` or `ACTIVE` transitions to `RECALLED`."
        PRD §3.4: "Applying a device is the moment an animal enters the traceability system, and it materialises three records in a single request: the device, the animal, and the animal's first observation."
        PRD §2.5: "Rules are evaluated **strictly in ascending priority order**, the first failing rule alone decides the response, and no side effect of any kind is applied once a rule has failed."

        Design: Difficulty/priority_pair_validation_conflict/state_lot_not_issuable_beats_referential_ain_out_of_range
        """
        scenario = setup_supplier_with_defects(
            lot_quantity=4000,
            defect_count=11,
            premises_capacity=40,
            operation_type="COW_CALF",
        )
        supplier_after = scenario["supplier_after_defects"]
        assert supplier_after["conformance_score"] == 67.00
        assert supplier_after["status"] == "SUSPENDED"
        assert read_tag_lot(scenario["lot"]["id"])["status"] == "RECALLED"

        resp = api.apply_tag(
            scenario["lot"]["id"],
            apply_tag_payload(
                ain_for_serial(DEFAULT_SERIAL_START + 9998),
                scenario["premises"]["id"],
                birth_date="2026-02-10",
            ),
            scenario["producer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_ISSUABLE, expected_status=409)

        tags, tag_meta = validate_paginated(
            api.list_tags(ADMIN, params={"tag_lot_id": scenario["lot"]["id"]})
        )
        assert tags == [] and tag_meta["total_count"] == 0, "no device was materialised"

        animals, animal_meta = validate_paginated(
            api.list_animals(ADMIN, params={"birth_premises_id": scenario["premises"]["id"]})
        )
        assert animals == [] and animal_meta["total_count"] == 0, "no animal was materialised"


class TestVoidedApplicationConservesDevices:
    def test_voiding_an_application_preserves_the_lot_device_partition(self, api):
        """PRD §2.8: "First, a lot's `quantity` always equals the sum of its `unapplied_count`, `applied_count`, `retired_count`, `replaced_count` and `voided_count`."
        PRD §3.4: "The device moves `APPLIED → VOIDED`. On the lot, `applied_count` falls by one and `voided_count` rises by one, preserving the invariant that `quantity` equals the sum of `unapplied_count`, `applied_count`, `retired_count`, `replaced_count` and `voided_count`."

        Design: Difficulty/compensating_invariant/tag_partition_conserved_when_application_is_voided
        """
        scenario = setup_animal_scenario(capacity=20, quantity=10, legal_name="Coulee Cattle")
        lot_id = scenario["lot"]["id"]

        before = read_tag_lot(lot_id)
        assert before["quantity"] == 10
        assert before["unapplied_count"] == 9
        assert before["applied_count"] == 1
        assert_tag_lot_partition(before)

        validate_success(api.void_tag_application(scenario["tag"]["id"], ADMIN))

        after = read_tag_lot(lot_id)
        assert after["applied_count"] == 0
        assert after["voided_count"] == 1
        assert after["unapplied_count"] == 9, (
            "a voided serial never flows back into the unapplied remainder"
        )
        assert after["quantity"] == 10
        assert_tag_lot_partition(after)

    def test_voiding_an_application_reverses_every_sighting_and_voids_the_animal(self, api):
        """PRD §3.4: "Every one of the animal's sightings is marked `reversed`, so its `sighting_count` becomes 0 and the projection leaves it in `lifecycle_status` `VOIDED`. The `animal_count` at the animal's current premises falls by one and the owning producer's `enrolled_head_count` and `incentive_tier` are re-derived."
        PRD §2.11: "Compensating actions never delete a sighting; they set `reversed` to true, and the retracted row remains in storage and remains retrievable, which is what the `include_reversed` flag on the sighting history exists to expose."

        Design: Difficulty/compensating_invariant/tag_partition_conserved_when_application_is_voided
        """
        scenario = setup_animal_scenario(capacity=20, quantity=10, legal_name="Coulee Cattle")

        validate_success(api.void_tag_application(scenario["tag"]["id"], ADMIN))

        assert read_tag(scenario["tag"]["id"])["device_status"] == "VOIDED"

        animal_after = read_animal(scenario["animal"]["id"])
        assert animal_after["lifecycle_status"] == "VOIDED"
        assert animal_after["sighting_count"] == 0

        assert read_premises(scenario["premises"]["id"])["animal_count"] == 0

        retained = sightings_of_animal(scenario["animal"]["id"], include_reversed=True)
        assert len(retained) == 1, "the retracted row remains in storage"
        assert retained[0]["reversed"] is True
