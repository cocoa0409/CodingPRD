"""Competing rejections resolved by the fixed admission order.

Every case below violates two rules at once, so the only interesting question is
which error comes back. The pairs are chosen where the losing rule would be the
natural one to check first.
"""

from test_helpers import (
    assert_tank_lot_ledger,
    certification_payload,
    component_lot_payload,
    compliance_engineer_headers,
    data_of,
    efficiency_test_payload,
    ERR_BATCH_NOT_FIRED,
    ERR_COMPONENT_CATEGORY_MISMATCH,
    ERR_DUPLICATE_CODE,
    ERR_FIRING_TEMP_EXCEEDS_FURNACE_MAX,
    ERR_FORBIDDEN_ROLE,
    ERR_GAS_CONTROL_NOT_APPLICABLE,
    ERR_GAS_CONTROL_REQUIRED,
    ERR_HEATER_UNIT_NOT_FOUND,
    ERR_INSUFFICIENT_TEST_SAMPLE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_WINDOW,
    ERR_LOT_UNIT_CAPACITY_EXCEEDED,
    ERR_PRODUCT_MODEL_NOT_FOUND,
    ERR_REWORK_LIMIT_EXCEEDED,
    ERR_REWORK_REVERSAL_NOT_ALLOWED,
    ERR_SAMPLE_SIZE_INSUFFICIENT,
    ERR_TANK_LOT_NOT_FOUND,
    ERR_TEST_WINDOW_NOT_ELAPSED,
    ERR_UNAUTHENTICATED,
    failing_holiday_payload,
    furnace_payload,
    headers_blank_user_id,
    headers_missing_role,
    headers_unknown_role,
    heater_unit_payload,
    holiday_inspection_payload,
    lining_batch_payload,
    make_fired_batch,
    make_full_plant,
    make_lined_tank_lot,
    make_model,
    make_released_tank_lot,
    make_test_cell,
    model_version,
    NON_EXISTENT_UUID,
    plant_admin_headers,
    plant_operator_headers,
    product_model_payload,
    quality_inspector_headers,
    reason_payload,
    ship_payload,
    supplier_payload,
    supplier_quality_headers,
    tank_lot_payload,
    tank_lot_version,
    validate_error,
    validate_paginated,
    validate_success,
    warranty_analyst_headers,
    WINDOW_AUG02_06_10,
    WINDOW_AUG02_22_AUG03_02,
    WINDOW_AUG04_06_10,
    fixtures as x,
)


class TestAuthenticationBeatsAuthorisation:
    """A malformed identity is answered before the role is even considered."""

    def test_01_a_missing_blank_or_undeclared_role_all_read_as_unauthenticated(
        self, api
    ):
        """No role header, a blank user id and an invented role are one answer.

        PRD: "A request with either header missing or empty, or naming a role outside
        the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_headers_beat_forbidden_role_unauthenticated_ladder
        """
        model_id = make_model(api)["id"]

        no_role = api.get_product_model(model_id, headers_missing_role())
        invented_role = api.get_product_model(model_id, headers_unknown_role())
        blank_user = api.get_product_model(model_id, headers_blank_user_id())
        good = api.get_product_model(model_id, compliance_engineer_headers())

        validate_error(no_role, ERR_UNAUTHENTICATED, expected_status=401)
        validate_error(invented_role, ERR_UNAUTHENTICATED, expected_status=401)
        validate_error(blank_user, ERR_UNAUTHENTICATED, expected_status=401)
        assert validate_success(good)["id"] == model_id

    def test_02_the_wrong_role_is_forbidden_but_no_role_is_still_unauthenticated(
        self, api
    ):
        """One endpoint, one payload, two identities, two different refusals.

        PRD: "Once the caller is authenticated, the service checks that the caller's
        role appears on the endpoint being invoked; if it does not, the request is rejected
        with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/validations/missing_headers_beat_forbidden_role_unauthenticated_ladder
        """
        payload = supplier_payload(name="Nope Ltd", audit_score=80, defect_ppm=500)

        wrong_role = api.create_supplier(payload, warranty_analyst_headers())
        no_role = api.create_supplier(payload, headers_missing_role())

        validate_error(wrong_role, ERR_FORBIDDEN_ROLE, expected_status=403)
        validate_error(no_role, ERR_UNAUTHENTICATED, expected_status=401)

    def test_03_none_of_the_refused_calls_left_a_row_or_moved_the_clock(self, api):
        """The gate refuses before any handler runs, so nothing was written.

        PRD: "On startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and
        until an administrator moves it, that is the instant every rule sees; the service
        never falls back to host wall-clock time under any circumstance."

        Design: Corner/validations/missing_headers_beat_forbidden_role_unauthenticated_ladder
        """
        payload = supplier_payload(name="Nope Ltd", audit_score=80, defect_ppm=500)

        api.create_supplier(payload, warranty_analyst_headers())
        api.create_supplier(payload, headers_missing_role())
        api.create_supplier(payload, headers_unknown_role())

        _rows, meta = validate_paginated(
            api.list_suppliers(supplier_quality_headers(), {"limit": 10, "offset": 0})
        )
        clock = validate_success(api.read_clock(plant_admin_headers()))

        assert meta["total_count"] == 0
        assert clock["current_utc"].startswith("2026-08-01T00:00:00")


class TestPathResolutionOutranksSchemaAndBodyReferences:
    """Three consecutive rungs, each shown to win against the rung below it."""

    def test_04_an_unknown_path_id_wins_against_a_bad_enum_in_the_body(self, api):
        """The unit is resolved first, so the impossible channel never gets read.

        PRD: "Path resolution — every `id` in the URL path resolves, left to right, to
        an existing row of the expected type."

        Design: Corner/validations/path_id_resolution_precedes_body_schema_and_body_fk_not_found
        """
        unknown_weld = api.weld_tank_lot(NON_EXISTENT_UUID, plant_operator_headers())
        unknown_ship = api.ship_unit(
            NON_EXISTENT_UUID,
            ship_payload(distribution_channel="SUPERSTORE"),
            plant_operator_headers(),
        )

        validate_error(unknown_weld, ERR_TANK_LOT_NOT_FOUND, expected_status=404)
        validate_error(unknown_ship, ERR_HEATER_UNIT_NOT_FOUND, expected_status=404)

    def test_05_a_range_violation_wins_against_an_unresolvable_body_reference(self, api):
        """Five thousand tanks is a schema fault; the same body at 100 is a not-found.

        PRD: "Schema validation (`ERR_INVALID_REQUEST`, 400) — required inputs present,
        JSON types correct, enum members inside their declared sets, numbers inside their
        declared ranges, strings non-empty and within their maximum lengths, timestamps ISO
        8601 with a trailing `Z`, and pagination parameters inside their bounds."

        Design: Corner/validations/path_id_resolution_precedes_body_schema_and_body_fk_not_found
        """
        out_of_range = api.create_tank_lot(
            tank_lot_payload(NON_EXISTENT_UUID, lot_code="TL-BAD", planned_quantity=5000),
            plant_operator_headers(),
        )
        in_range = api.create_tank_lot(
            tank_lot_payload(NON_EXISTENT_UUID, lot_code="TL-BAD", planned_quantity=100),
            plant_operator_headers(),
        )

        validate_error(out_of_range, ERR_INVALID_REQUEST, expected_status=400)
        validate_error(in_range, ERR_PRODUCT_MODEL_NOT_FOUND, expected_status=404)

    def test_06_declared_enum_sets_and_numeric_ranges_are_both_schema_faults(self, api):
        """A diesel water heater and a nineteen-gallon tank are both refused at 400.

        PRD: "Creating a model supplies its `model_code` — the catalogue code, unique
        across all models, non-empty, at most 24 characters and restricted to uppercase
        letters, digits and hyphens, which later becomes the model's serial-number prefix —
        together with `fuel_type` (`GAS`, `ELECTRIC` or `HEAT_PUMP`),
        `nominal_capacity_gallons` between 20 and 120 inclusive, the distribution `channel`
        the model is catalogued for (`TRADE`, `RETAIL` or `BUILDER`), and
        `insulation_r_value`, the declared insulation R-value between 10.0 and 40.0
        inclusive."

        Design: Corner/validations/path_id_resolution_precedes_body_schema_and_body_fk_not_found
        """
        bad_fuel = api.create_product_model(
            product_model_payload(model_code="DX50", fuel_type="DIESEL"),
            compliance_engineer_headers(),
        )
        bad_capacity = api.create_product_model(
            product_model_payload(model_code="GX19", nominal_capacity_gallons=19),
            compliance_engineer_headers(),
        )

        validate_error(bad_fuel, ERR_INVALID_REQUEST, expected_status=400)
        validate_error(bad_capacity, ERR_INVALID_REQUEST, expected_status=400)
        _models, model_meta = validate_paginated(
            api.list_product_models(
                compliance_engineer_headers(), {"limit": 10, "offset": 0}
            )
        )
        _lots, lot_meta = validate_paginated(
            api.list_tank_lots(plant_operator_headers(), {"limit": 10, "offset": 0})
        )
        assert model_meta["total_count"] == 0
        assert lot_meta["total_count"] == 0


def _a_plant_with_one_furnace_one_batch_and_one_lot(api):
    """A named furnace carrying a fired batch, a second empty furnace and one lot."""
    supply = x.make_supply_base(api)
    model_id = make_model(api)["id"]
    batch = x.make_fired_batch(api)
    spare_furnace = data_of(
        api.create_furnace(
            furnace_payload(furnace_code="FURN-B"), plant_admin_headers()
        )
    )
    lot_id = data_of(
        api.create_tank_lot(tank_lot_payload(model_id), plant_operator_headers())
    )["id"]
    return supply, model_id, batch, spare_furnace["id"], lot_id


class TestCodeUniquenessAndWindowSanity:
    """Plant-unique codes, supplier-scoped part numbers, and window arithmetic."""

    def test_07_a_second_furnace_or_lot_under_an_existing_code_is_refused(self, api):
        """Both codes are unique across the whole plant, not per creator.

        PRD: "A tank production lot is opened by a `PlantOperator` naming the
        `product_model_id` whose tanks it fabricates, a plant-unique `lot_code` (non-empty,
        at most 20 characters, colliding as `ERR_DUPLICATE_CODE`) and a `planned_quantity`
        between 1 and 1000 inclusive."

        Design: Corner/validations/duplicate_codes_and_window_sanity_rejected
        """
        _supply, model_id, _batch, _spare, _lot_id = _a_plant_with_one_furnace_one_batch_and_one_lot(api)

        duplicate_furnace = api.create_furnace(
            furnace_payload(max_firing_temp_c=880), plant_admin_headers()
        )
        duplicate_lot = api.create_tank_lot(
            tank_lot_payload(model_id, planned_quantity=60), plant_operator_headers()
        )

        validate_error(duplicate_furnace, ERR_DUPLICATE_CODE, expected_status=409)
        validate_error(duplicate_lot, ERR_DUPLICATE_CODE, expected_status=409)

    def test_08_a_part_number_is_unique_only_within_one_supplier(self, api):
        """The same label reused by the same supplier collides; another supplier's does not.

        PRD: "The booking names `supplier_id`, the manufacturer `part_number` printed on
        the lot label (non-empty, at most 40 characters, and unique among that one
        supplier's lots — a collision reports `ERR_DUPLICATE_CODE`), the `category` drawn
        from the same six-member component-family enumeration, the `quantity` of pieces
        received which must be at least 1, and optionally `certificate_of_conformance`, a
        boolean that defaults to `false` when omitted."

        Design: Corner/validations/duplicate_codes_and_window_sanity_rejected
        """
        supply, _model_id, _batch, _spare, _lot_id = _a_plant_with_one_furnace_one_batch_and_one_lot(api)

        same_supplier = api.create_component_lot(
            component_lot_payload(supply.gas_supplier_id, quantity=25),
            supplier_quality_headers(),
        )
        other_supplier = api.create_component_lot(
            component_lot_payload(
                supply.valve_supplier_id,
                part_number="GV-880",
                category="TP_RELIEF_VALVE",
                quantity=25,
            ),
            supplier_quality_headers(),
        )

        validate_error(same_supplier, ERR_DUPLICATE_CODE, expected_status=409)
        accepted = validate_success(other_supplier, expected_status=201)
        assert accepted["part_number"] == "GV-880"
        assert accepted["status"] == "QUARANTINED"

    def test_09_an_inverted_window_a_hot_setpoint_and_a_cold_one_are_three_answers(
        self, api
    ):
        """Orientation, the furnace ceiling and the static floor are separate rungs.

        PRD: "A window whose `firing_start` is at or after its `firing_end` is refused
        with `ERR_INVALID_WINDOW`, and a `firing_temp_c` above the furnace's
        `max_firing_temp_c` is refused with `ERR_FIRING_TEMP_EXCEEDS_FURNACE_MAX`;
        independently of the furnace, `firing_temp_c` must be at least 700, and a lower
        value fails schema validation as `ERR_INVALID_REQUEST`."

        Design: Corner/validations/duplicate_codes_and_window_sanity_rejected
        """
        _supply, _model, _batch, spare_furnace, _lot = _a_plant_with_one_furnace_one_batch_and_one_lot(api)

        zero_length = api.create_lining_batch(
            lining_batch_payload(
                spare_furnace,
                window=("2026-08-06T06:00:00Z", "2026-08-06T06:00:00Z"),
                batch_code="GLB-002",
            ),
            plant_operator_headers(),
        )
        above_ceiling = api.create_lining_batch(
            lining_batch_payload(
                spare_furnace,
                window=("2026-08-06T06:00:00Z", "2026-08-06T10:00:00Z"),
                batch_code="GLB-003",
                firing_temp_c=950,
            ),
            plant_operator_headers(),
        )
        below_floor = api.create_lining_batch(
            lining_batch_payload(
                spare_furnace,
                window=("2026-08-06T06:00:00Z", "2026-08-06T10:00:00Z"),
                batch_code="GLB-004",
                firing_temp_c=650,
            ),
            plant_operator_headers(),
        )

        validate_error(zero_length, ERR_INVALID_WINDOW, expected_status=422)
        validate_error(
            above_ceiling, ERR_FIRING_TEMP_EXCEEDS_FURNACE_MAX, expected_status=422
        )
        validate_error(below_floor, ERR_INVALID_REQUEST, expected_status=400)
        idle = validate_success(api.get_furnace(spare_furnace, plant_admin_headers()))
        assert idle["occupied_window_count"] == 0


def _a_gas_line_and_an_electric_line_ready_to_stage(api):
    """A certified gas model and a draft electric model, each with a released lot."""
    plant = make_full_plant(api)
    electric_id = make_model(
        api,
        product_model_payload(
            model_code="EX50-R", fuel_type="ELECTRIC", channel="RETAIL"
        ),
    )["id"]
    electric_lot_id = make_released_tank_lot(
        api, electric_id, plant.batch_id, lot_code="TL-E01", planned_quantity=60
    )
    return plant, electric_id, electric_lot_id


class TestStagingCategoryBeatsFuelApplicability:
    """Both slots must be filled from the right family before fuel rules are read."""

    def test_10_two_valves_fitted_to_each_other_s_slots_is_a_category_mismatch(
        self, api
    ):
        """The gas build is complete, so only the swap can explain the refusal.

        PRD: "First the component families must match the slots they are being fitted
        to: `gas_control_lot_id` must name a lot whose `category` is `GAS_VALVE` and
        `safety_valve_lot_id` a lot whose `category` is `TP_RELIEF_VALVE`, or the staging is
        refused with `ERR_COMPONENT_CATEGORY_MISMATCH`."

        Design: Corner/validations/component_staging_category_and_fuel_rules_rejected
        """
        plant, _electric_id, _electric_lot = _a_gas_line_and_an_electric_line_ready_to_stage(api)

        swapped = api.create_heater_unit(
            heater_unit_payload(
                plant.tank_lot_id,
                safety_valve_lot_id=plant.gas_lot_id,
                gas_control_lot_id=plant.valve_lot_id,
            ),
            plant_operator_headers(),
        )

        validate_error(
            swapped, ERR_COMPONENT_CATEGORY_MISMATCH, expected_status=422
        )

    def test_11_the_gas_control_slot_is_mandatory_on_gas_and_barred_elsewhere(self, api):
        """One omission and one surplus, reported by two different identifiers.

        PRD: "Then fuel-type applicability is enforced: a unit staged for a model whose
        `fuel_type` is `GAS` must supply `gas_control_lot_id`, and omitting it is refused
        with `ERR_GAS_CONTROL_REQUIRED`; a unit staged for an `ELECTRIC` or `HEAT_PUMP`
        model must **not** supply one, and doing so is refused with
        `ERR_GAS_CONTROL_NOT_APPLICABLE`."

        Design: Corner/validations/component_staging_category_and_fuel_rules_rejected
        """
        plant, _electric_id, electric_lot = _a_gas_line_and_an_electric_line_ready_to_stage(api)

        gas_without_control = api.create_heater_unit(
            heater_unit_payload(plant.tank_lot_id, plant.valve_lot_id),
            plant_operator_headers(),
        )
        electric_with_control = api.create_heater_unit(
            heater_unit_payload(electric_lot, plant.valve_lot_id, plant.gas_lot_id),
            plant_operator_headers(),
        )

        validate_error(
            gas_without_control, ERR_GAS_CONTROL_REQUIRED, expected_status=422
        )
        validate_error(
            electric_with_control, ERR_GAS_CONTROL_NOT_APPLICABLE, expected_status=422
        )

    def test_12_an_electric_unit_with_only_a_relief_valve_is_accepted(self, api):
        """The same three refusals become one acceptance once the slots are right.

        PRD: "The unit's `product_model_id` is **never** supplied by the client: it is
        inherited from the named tank lot at creation, as is `production_period`, which is
        copied verbatim from the lot's own cohort key."

        Design: Corner/validations/component_staging_category_and_fuel_rules_rejected
        """
        plant, electric_id, electric_lot = _a_gas_line_and_an_electric_line_ready_to_stage(api)

        api.create_heater_unit(
            heater_unit_payload(
                plant.tank_lot_id,
                safety_valve_lot_id=plant.gas_lot_id,
                gas_control_lot_id=plant.valve_lot_id,
            ),
            plant_operator_headers(),
        )
        api.create_heater_unit(
            heater_unit_payload(plant.tank_lot_id, plant.valve_lot_id),
            plant_operator_headers(),
        )
        staged = validate_success(
            api.create_heater_unit(
                heater_unit_payload(electric_lot, plant.valve_lot_id),
                plant_operator_headers(),
            ),
            expected_status=201,
        )
        gas_lot = validate_success(
            api.get_component_lot(plant.gas_lot_id, quality_inspector_headers())
        )
        gas_tank_lot = validate_success(
            api.get_tank_lot(plant.tank_lot_id, plant_operator_headers())
        )

        assert staged["gas_control_lot_id"] is None
        assert staged["product_model_id"] == electric_id
        assert staged["build_status"] == "COMPONENTS_STAGED"
        assert gas_lot["consumed_quantity"] == 0
        assert gas_lot["remaining_quantity"] == 50
        assert gas_tank_lot["unit_count"] == 0


def _a_single_tank_lot_already_drawn_dry(api):
    """A one-tank lot whose only good tank has already been staged as a unit."""
    plant = make_full_plant(api)
    only_lot = make_released_tank_lot(
        api, plant.model_id, plant.batch_id, lot_code="TL-ONE", planned_quantity=1
    )
    only_unit = data_of(
        api.create_heater_unit(
            heater_unit_payload(only_lot, plant.valve_lot_id, plant.gas_lot_id),
            plant_operator_headers(),
        )
    )["id"]
    return plant, only_lot, only_unit


class TestLotUnitCapacityIsCountedLive:
    """Output is capped at the good tanks, and scrapping a unit gives one back."""

    def test_13_one_unit_too_many_is_refused_against_the_good_quantity(self, api):
        """A lot of one good tank admits exactly one unit and no more.

        PRD: "Finally the tank lot's output is capped: the number of units already drawn
        from that tank lot must be strictly less than its `good_quantity`, and one unit too
        many is refused with `ERR_LOT_UNIT_CAPACITY_EXCEEDED`."

        Design: Corner/validations/lot_unit_capacity_beyond_good_quantity_rejected
        """
        plant, only_lot, _only_unit = _a_single_tank_lot_already_drawn_dry(api)

        second = api.create_heater_unit(
            heater_unit_payload(only_lot, plant.valve_lot_id, plant.gas_lot_id),
            plant_operator_headers(),
        )

        validate_error(second, ERR_LOT_UNIT_CAPACITY_EXCEEDED, expected_status=409)
        lot = validate_success(api.get_tank_lot(only_lot, plant_operator_headers()))
        assert lot["good_quantity"] == 1
        assert lot["planned_quantity"] == 1
        assert lot["unit_count"] == 1

    def test_14_scrapping_the_unit_frees_the_tank_for_a_replacement(self, api):
        """A SCRAPPED unit stops counting, so the capped lot admits one more build.

        PRD: "Its `unit_count` is derived at read time as the number of heater units
        drawn from this lot whose `build_status` is anything other than `SCRAPPED`."

        Design: Corner/validations/lot_unit_capacity_beyond_good_quantity_rejected
        """
        plant, only_lot, only_unit = _a_single_tank_lot_already_drawn_dry(api)

        scrapped = validate_success(
            api.disassemble_unit(
                only_unit, reason_payload(reason_code="TANK_DENT"), plant_operator_headers()
            )
        )
        after_scrap = validate_success(
            api.get_tank_lot(only_lot, plant_operator_headers())
        )
        replacement = validate_success(
            api.create_heater_unit(
                heater_unit_payload(only_lot, plant.valve_lot_id, plant.gas_lot_id),
                plant_operator_headers(),
            ),
            expected_status=201,
        )

        assert scrapped["build_status"] == "SCRAPPED"
        assert after_scrap["unit_count"] == 0
        assert replacement["tank_lot_id"] == only_lot


def _one_lot_around_the_loop_twice_and_a_bystander(api):
    """A quarantined batch: TL-001 failed twice by itself, TL-002 fell with it.

    TL-001 is charged 10 then 5 tanks and reaches the rework ceiling, which
    quarantines the shared batch and drags the still-lined TL-002 into rejection
    without touching its ledger.
    """
    model_id = make_model(api)["id"]
    batch = make_fired_batch(api)
    first = make_lined_tank_lot(api, model_id, batch.batch_id)
    bystander = make_lined_tank_lot(
        api, model_id, batch.batch_id, lot_code="TL-002", planned_quantity=60
    )
    data_of(
        api.create_lining_inspection(
            failing_holiday_payload(first, tank_lot_version(api, first)),
            quality_inspector_headers(),
        )
    )
    data_of(api.authorize_reline(first, plant_operator_headers()))
    data_of(
        api.apply_lining(
            first, {"glass_lining_batch_id": batch.batch_id}, plant_operator_headers()
        )
    )
    data_of(
        api.create_lining_inspection(
            failing_holiday_payload(
                first, tank_lot_version(api, first), scrap_quantity=5
            ),
            quality_inspector_headers(),
        )
    )
    return batch, first, bystander


class TestReworkCeilingAndReversalEligibility:
    """Two tries round the loop, and reversal only for a lot's own failure."""

    def test_15_a_third_reline_is_refused_once_the_lot_has_been_round_twice(self, api):
        """The ceiling is read off `rework_count`, which already stands at two.

        PRD: "A `PlantOperator` may authorise another lining cycle, moving it
        `LINING_REJECTED → RELINE_QUEUED` and clearing `last_scrap_quantity`; this is
        refused with `ERR_REWORK_LIMIT_EXCEEDED` when `rework_count` has already reached 2,
        since a lot may go around the loop at most twice, and refused with
        `ERR_INVALID_TANK_LOT_STATE` when nothing remains in process (`wip_quantity` below
        1)."

        Design: Corner/validations/rework_limit_and_reversal_guards_rejected
        """
        _batch, first, _bystander = _one_lot_around_the_loop_twice_and_a_bystander(api)

        third_try = api.authorize_reline(first, plant_operator_headers())

        validate_error(third_try, ERR_REWORK_LIMIT_EXCEEDED, expected_status=409)
        lot = validate_success(api.get_tank_lot(first, quality_inspector_headers()))
        assert lot["rework_count"] == 2
        assert lot["status"] == "LINING_REJECTED"

    def test_16_a_quarantined_batch_and_a_cascaded_rejection_both_bar_reversal(self, api):
        """Two different disqualifying conditions, one identifier for both.

        PRD: "Reversal is available **only** when the rejection was this lot's own direct
        inspection failure — `cascade_rejected` must be `false` — and only while
        `last_scrap_quantity` is not null and the lot's glass-lining batch is still `FIRED`;
        a cascade-rejected lot, a lot with nothing outstanding to reverse, or a lot whose
        batch has been quarantined is refused with `ERR_REWORK_REVERSAL_NOT_ALLOWED`."

        Design: Corner/validations/rework_limit_and_reversal_guards_rejected
        """
        batch, first, bystander = _one_lot_around_the_loop_twice_and_a_bystander(api)

        own_failure = api.rework_reversal(
            first, reason_payload(reason_code="MEASUREMENT_ERROR"), quality_inspector_headers()
        )
        cascaded = api.rework_reversal(
            bystander,
            reason_payload(reason_code="MEASUREMENT_ERROR"),
            quality_inspector_headers(),
        )

        validate_error(own_failure, ERR_REWORK_REVERSAL_NOT_ALLOWED, expected_status=409)
        validate_error(cascaded, ERR_REWORK_REVERSAL_NOT_ALLOWED, expected_status=409)
        quarantined = validate_success(
            api.get_lining_batch(batch.batch_id, plant_operator_headers())
        )
        fallen = validate_success(
            api.get_tank_lot(bystander, quality_inspector_headers())
        )
        assert quarantined["status"] == "QUARANTINED"
        assert fallen["cascade_rejected"] is True
        assert fallen["last_scrap_quantity"] is None

    def test_17_the_bystander_may_requeue_but_cannot_be_lined_from_a_dead_batch(
        self, api
    ):
        """Reline authorisation still works; the lining application has nothing to draw on.

        PRD: "The named batch must be in `status` `FIRED`; anything else is refused with
        `ERR_BATCH_NOT_FIRED`."

        Design: Corner/validations/rework_limit_and_reversal_guards_rejected
        """
        batch, first, bystander = _one_lot_around_the_loop_twice_and_a_bystander(api)

        requeued = validate_success(
            api.authorize_reline(bystander, plant_operator_headers())
        )
        relining = api.apply_lining(
            bystander,
            {"glass_lining_batch_id": batch.batch_id},
            plant_operator_headers(),
        )

        assert requeued["status"] == "RELINE_QUEUED"
        validate_error(relining, ERR_BATCH_NOT_FIRED, expected_status=409)
        charged = validate_success(api.get_tank_lot(first, quality_inspector_headers()))
        untouched = validate_success(
            api.get_tank_lot(bystander, quality_inspector_headers())
        )
        dead_batch = validate_success(
            api.get_lining_batch(batch.batch_id, plant_operator_headers())
        )
        assert (charged["wip_quantity"], charged["scrapped_quantity"]) == (105, 15)
        assert charged["good_quantity"] == 0
        assert_tank_lot_ledger(charged)
        assert (untouched["wip_quantity"], untouched["scrapped_quantity"]) == (60, 0)
        assert dead_batch["rejected_lot_count"] == 2
        assert dead_batch["quarantine_reason_code"] == "REPEAT_LINING_FAILURE"


def _a_programme_two_thirds_finished_with_a_lined_lot(api):
    """Two passed UEF runs, one unfired first-hour run, a draft certificate, a lined lot.

    The clock stops at the second UEF window's end, which is late enough to book
    those two results and early enough to leave the first-hour-rating window open.
    """
    model_id = make_model(api)["id"]
    cell_id = make_test_cell(api)["id"]
    first_uef = data_of(
        api.create_efficiency_test(
            efficiency_test_payload(model_id, cell_id, window=WINDOW_AUG02_06_10),
            compliance_engineer_headers(),
        )
    )["id"]
    second_uef = data_of(
        api.create_efficiency_test(
            efficiency_test_payload(model_id, cell_id, window=WINDOW_AUG02_22_AUG03_02),
            compliance_engineer_headers(),
        )
    )["id"]
    first_hour = data_of(
        api.create_efficiency_test(
            efficiency_test_payload(
                model_id,
                cell_id,
                window=WINDOW_AUG04_06_10,
                test_type="FIRST_HOUR_RATING",
            ),
            compliance_engineer_headers(),
        )
    )["id"]
    batch = make_fired_batch(api, clock="2026-08-03T02:00:00Z")
    data_of(
        api.record_test_result(
            first_uef, {"measured_value": 0.585}, quality_inspector_headers()
        )
    )
    data_of(
        api.record_test_result(
            second_uef, {"measured_value": 0.585}, quality_inspector_headers()
        )
    )
    certificate = data_of(
        api.create_certification(
            certification_payload(model_id, model_version(api, model_id)),
            compliance_engineer_headers(),
        )
    )["id"]
    lot_id = make_lined_tank_lot(api, model_id, batch.batch_id)
    return model_id, first_hour, certificate, lot_id


class TestAdequacyAndElapseGuardsRunBeforeAnyVerdict:
    """Three refusals that each prevent a figure from being computed at all."""

    def test_18_a_short_inspection_sample_is_refused_instead_of_failing_the_lot(
        self, api
    ):
        """Five tanks out of a hundred and twenty is not a `FAIL`, it is no verdict.

        PRD: "Sampling adequacy is checked before any verdict is computed, and an
        inadequate sample is never allowed to masquerade as a failure. The required sample is
        the larger of 3 tanks and five percent of the lot's `planned_quantity` rounded up to
        a whole tank; a `sample_size` below that figure is refused with
        `ERR_SAMPLE_SIZE_INSUFFICIENT` rather than producing a `FAIL` result."

        Design: Corner/validations/verdict_guards_before_booking_a_result_rejected
        """
        _model_id, _first_hour, _certificate, lot_id = _a_programme_two_thirds_finished_with_a_lined_lot(api)

        short_sample = api.create_lining_inspection(
            holiday_inspection_payload(
                lot_id,
                tank_lot_version(api, lot_id),
                sample_size=5,
                holiday_count=4,
                scrap_quantity=10,
            ),
            quality_inspector_headers(),
        )

        validate_error(short_sample, ERR_SAMPLE_SIZE_INSUFFICIENT, expected_status=422)
        lot = validate_success(api.get_tank_lot(lot_id, quality_inspector_headers()))
        assert lot["status"] == "LINED"
        assert lot["wip_quantity"] == 120
        assert lot["scrapped_quantity"] == 0
        assert lot["rework_count"] == 0

    def test_19_a_certificate_short_of_its_test_programme_cannot_be_submitted(self, api):
        """Two passed UEF runs and no rating runs at all leaves the draft untouched.

        PRD: "It requires the model to hold at least 3 `PASSED` `UEF` tests, at least one
        `PASSED` `FIRST_HOUR_RATING` test and at least one `PASSED` `RECOVERY` test; a model
        short on any of the three is refused with `ERR_INSUFFICIENT_TEST_SAMPLE`, and on a
        resubmission all three counts are re-evaluated afresh against the model's current
        passed tests rather than reusing the earlier figures."

        Design: Corner/validations/verdict_guards_before_booking_a_result_rejected
        """
        _model_id, _first_hour, certificate, _lot_id = _a_programme_two_thirds_finished_with_a_lined_lot(api)

        premature = api.submit_certification(certificate, compliance_engineer_headers())

        validate_error(premature, ERR_INSUFFICIENT_TEST_SAMPLE, expected_status=409)
        draft = validate_success(
            api.get_certification(certificate, compliance_engineer_headers())
        )
        assert draft["status"] == "DRAFT"
        assert draft["certified_uef"] is None
        assert draft["uef_test_count"] is None
        assert draft["submitted_by_user_id"] is None

    def test_20_a_reading_cannot_be_booked_before_its_own_window_has_run_out(self, api):
        """The instrument reading is refused while the first-hour window is still open.

        PRD: "The call is refused with `ERR_INVALID_TEST_STATE` unless the test is still
        `SCHEDULED`, and with `ERR_TEST_WINDOW_NOT_ELAPSED` unless the logical clock has
        reached the test's own `window_end`; the clock exactly at `window_end` is sufficient."

        Design: Corner/validations/verdict_guards_before_booking_a_result_rejected
        """
        model_id, first_hour, _certificate, _lot_id = _a_programme_two_thirds_finished_with_a_lined_lot(api)

        early = api.record_test_result(
            first_hour, {"measured_value": 62.5}, quality_inspector_headers()
        )

        validate_error(early, ERR_TEST_WINDOW_NOT_ELAPSED, expected_status=409)
        still_open = validate_success(
            api.get_efficiency_test(first_hour, compliance_engineer_headers())
        )
        model = validate_success(
            api.get_product_model(model_id, compliance_engineer_headers())
        )
        assert still_open["status"] == "SCHEDULED"
        assert still_open["measured_value"] is None
        assert still_open["margin"] is None
        assert still_open["recorded_at"] is None
        assert model["certification_status"] == "TEST_PENDING"
