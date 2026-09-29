"""Declared shapes: creation defaults, stored reads, filters and rejections.

These are the contract-surface checks - what a fresh row looks like, which
fields are derived rather than supplied, which resource carries no version at
all, and what a list read hands back once a filter and a page are applied.
"""

from test_helpers import (
    approx4,
    assert_component_lot_ledger,
    assert_created_at_ascending,
    assert_immutable_record_fields,
    assert_no_pagination_meta,
    assert_system_fields,
    assert_tank_lot_ledger,
    component_lot_payload,
    compliance_engineer_headers,
    data_of,
    ERR_COMPONENT_LOT_NOT_FOUND,
    ERR_INVALID_COMPONENT_LOT_STATE,
    ERR_INVALID_REQUEST,
    ERR_TANK_LOT_NOT_FOUND,
    furnace_payload,
    heater_unit_payload,
    holiday_inspection_payload,
    make_fired_batch,
    make_lined_tank_lot,
    make_model,
    make_qualified_supplier,
    NON_EXISTENT_UUID,
    plant_admin_headers,
    plant_operator_headers,
    product_model_payload,
    quality_inspector_headers,
    safety_valve_lot_payload,
    safety_valve_supplier_payload,
    supplier_payload,
    supplier_quality_headers,
    tank_lot_payload,
    tank_lot_version,
    USER_INSPECTOR,
    validate_error,
    validate_paginated,
    validate_success,
    fixtures as x,
)


class TestSupplierCreationShape:
    """A newly registered supplier and the clock it is registered against."""

    def test_01_a_new_supplier_carries_its_declared_defaults(self, api):
        """Nothing is scored yet, nothing is contained yet, version starts at one.

        PRD: "A newly registered supplier begins at `qualification_status` `PENDING`
        with no `qualification_score`, no `qualified_until` and no
        `disqualification_reason_code`."

        Design: Corner/entities/supplier_creation_returns_declared_defaults_and_system_fields
        """
        created = validate_success(
            api.create_supplier(supplier_payload(), supplier_quality_headers()),
            expected_status=201,
        )

        assert created["qualification_status"] == "PENDING"
        assert created["qualification_score"] is None
        assert created["qualified_until"] is None
        assert created["disqualification_reason_code"] is None
        assert created["blocked_lot_count"] == 0
        assert created["name"] == "Meridian Controls"
        assert created["component_category"] == "GAS_VALVE"
        assert created["audit_score"] == 96
        assert created["defect_ppm"] == 1000
        assert created["open_capa_count"] == 0
        assert_system_fields(created, expected_version=1)

    def test_02_the_logical_clock_starts_at_its_declared_instant(self, api):
        """Every rule in a fresh service sees the first of August.

        PRD: "On startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and
        until an administrator moves it, that is the instant every rule sees; the
        service never falls back to host wall-clock time under any circumstance."

        Design: Corner/entities/supplier_creation_returns_declared_defaults_and_system_fields
        """
        clock = validate_success(api.read_clock(plant_admin_headers()))

        assert clock["current_utc"].startswith("2026-08-01T00:00:00")


class TestProductModelStoredRead:
    """A model read back by id, before anything has happened to it."""

    def test_03_a_freshly_created_model_reads_back_in_both_start_postures(self, api):
        """Two independent dimensions, four unpublished ratings, empty derived counters.

        PRD: "All four are null until a first approval lands."

        Design: Corner/entities/product_model_get_by_id_returns_stored_row
        """
        model_id = make_model(api)["id"]

        response = api.get_product_model(model_id, compliance_engineer_headers())
        model = validate_success(response)

        assert model["id"] == model_id
        assert model["model_code"] == "GX50-T"
        assert model["fuel_type"] == "GAS"
        assert model["nominal_capacity_gallons"] == 50
        assert model["channel"] == "TRADE"
        assert model["insulation_r_value"] == 20
        assert model["certification_status"] == "UNCERTIFIED"
        assert model["release_status"] == "DRAFT"
        assert model["uef_rated"] is None
        assert model["fhr_rated"] is None
        assert model["recovery_rate_rated"] is None
        assert model["label_serial_prefix"] is None
        assert model["is_private_label"] is False
        assert model["base_model_id"] is None
        assert model["brand_label"] is None
        assert model["held_unit_count"] == 0
        assert_no_pagination_meta(response)

    def test_04_a_model_with_no_shipments_carries_an_empty_reserve(self, api):
        """The accrual figure only ever rises as units ship, so it is still zero.

        PRD: "Every model row also carries the running warranty reserve for its
        population: `warranty_reserve_accrued_cents`, the cumulative accrual booked as
        its units shipped; `warranty_paid_cents`, the cumulative amount paid out on
        validated claims; and `warranty_reserve_balance_cents`, which is always exactly
        the accrual less the payments."

        Design: Corner/entities/product_model_get_by_id_returns_stored_row
        """
        model_id = make_model(api)["id"]

        model = validate_success(
            api.get_product_model(model_id, compliance_engineer_headers())
        )

        assert model["warranty_reserve_accrued_cents"] == 0
        assert model["warranty_paid_cents"] == 0
        assert model["warranty_reserve_balance_cents"] == 0


def _four_quarantined_lots_across_two_suppliers(api):
    """Three gas-valve lots from one supplier and one T&P lot from another."""
    gas_supplier = make_qualified_supplier(api)
    valve_supplier = make_qualified_supplier(
        api,
        safety_valve_supplier_payload(),
        audit_score=92,
        defect_ppm=1500,
        open_capa_count=1,
    )
    part_numbers = ("GV-880", "GV-881", "GV-882")
    lots = [
        data_of(
            api.create_component_lot(
                component_lot_payload(
                    gas_supplier["id"], part_number=part_number, quantity=quantity
                ),
                supplier_quality_headers(),
            )
        )
        for part_number, quantity in zip(part_numbers, (50, 40, 30))
    ]
    other = data_of(
        api.create_component_lot(
            safety_valve_lot_payload(valve_supplier["id"], quantity=20),
            supplier_quality_headers(),
        )
    )
    return gas_supplier["id"], lots, other


class TestComponentLotListing:
    """The supplier filter and the page window, applied together."""

    def test_05_the_supplier_filter_pages_in_created_at_order(self, api):
        """Two rows then the remaining one, and never the other supplier's lot.

        PRD: "Suppliers can be listed filtered by `qualification_status` or
        `component_category`; component lots can be listed filtered by `supplier_id`,
        `category` or `status`."

        Design: Corner/entities/component_lot_list_filter_by_supplier_paginates
        """
        supplier_id, _lots, other = _four_quarantined_lots_across_two_suppliers(api)

        first_page, first_meta = validate_paginated(
            api.list_component_lots(
                supplier_quality_headers(),
                {"supplier_id": supplier_id, "limit": 2, "offset": 0},
            )
        )
        second_page, second_meta = validate_paginated(
            api.list_component_lots(
                supplier_quality_headers(),
                {"supplier_id": supplier_id, "limit": 2, "offset": 2},
            )
        )

        assert [row["part_number"] for row in first_page] == ["GV-880", "GV-881"]
        assert_created_at_ascending(first_page)
        assert [row["part_number"] for row in second_page] == ["GV-882"]
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert second_meta["has_more"] is False
        assert other["id"] not in [row["id"] for row in first_page + second_page]

    def test_06_every_new_lot_is_quarantined_with_its_pieces_untouched(self, api):
        """The unfiltered read shows all four lots in their opening posture.

        PRD: "Every new lot starts at `status` `QUARANTINED` pending incoming
        inspection, with no `reject_reason_code`."

        Design: Corner/entities/component_lot_list_filter_by_supplier_paginates
        """
        _supplier_id, _lots, _other = _four_quarantined_lots_across_two_suppliers(api)

        rows, meta = validate_paginated(
            api.list_component_lots(
                supplier_quality_headers(), {"limit": 10, "offset": 0}
            )
        )

        assert len(rows) == 4
        assert meta["total_count"] == 4
        for row in rows:
            assert row["status"] == "QUARANTINED"
            assert row["reject_reason_code"] is None
            assert row["remaining_quantity"] == row["quantity"]
            assert row["consumed_quantity"] == 0
            assert_component_lot_ledger(row)


class TestTankLotReadResolution:
    """A path id that resolves and one that does not."""

    def test_07_an_unknown_tank_lot_id_reports_the_entity_s_own_not_found_code(self, api):
        """Path resolution answers before anything else about the request.

        PRD: "Path resolution — every `id` in the URL path resolves, left to right, to
        an existing row of the expected type. A missing row yields that entity's own
        not-found code: `ERR_SUPPLIER_NOT_FOUND`, `ERR_COMPONENT_LOT_NOT_FOUND`,
        `ERR_FURNACE_NOT_FOUND`, `ERR_GLASS_LINING_BATCH_NOT_FOUND`,
        `ERR_TANK_LOT_NOT_FOUND`, `ERR_LINING_INSPECTION_NOT_FOUND`,
        `ERR_PRODUCT_MODEL_NOT_FOUND`, `ERR_TEST_CELL_NOT_FOUND`,
        `ERR_EFFICIENCY_TEST_NOT_FOUND`, `ERR_RATING_CERTIFICATION_NOT_FOUND`,
        `ERR_HEATER_UNIT_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
        `ERR_RECALL_CAMPAIGN_NOT_FOUND` or `ERR_RECALL_NOTICE_NOT_FOUND`, each HTTP 404."

        Design: Corner/entities/tank_lot_get_unknown_id_returns_not_found
        """
        model_id = make_model(api)["id"]
        data_of(
            api.create_tank_lot(tank_lot_payload(model_id), plant_operator_headers())
        )

        response = api.get_tank_lot(NON_EXISTENT_UUID, plant_operator_headers())

        validate_error(response, ERR_TANK_LOT_NOT_FOUND, expected_status=404)

    def test_08_a_new_tank_lot_opens_with_every_tank_in_process(self, api):
        """The whole planned quantity is work in process and nothing is reworked.

        PRD: "At creation the whole planned quantity is work in process:
        `wip_quantity` equals `planned_quantity`, while `good_quantity` and
        `scrapped_quantity` are both 0."

        Design: Corner/entities/tank_lot_get_unknown_id_returns_not_found
        """
        model_id = make_model(api)["id"]
        lot_id = data_of(
            api.create_tank_lot(tank_lot_payload(model_id), plant_operator_headers())
        )["id"]

        lot = validate_success(api.get_tank_lot(lot_id, plant_operator_headers()))

        assert lot["lot_code"] == "TL-001"
        assert lot["status"] == "FAB_QUEUED"
        assert lot["wip_quantity"] == 120
        assert lot["good_quantity"] == 0
        assert lot["scrapped_quantity"] == 0
        assert lot["rework_count"] == 0
        assert_tank_lot_ledger(lot)


class TestProductModelSchemaAdmission:
    """A required field left out never reaches the business rules."""

    def test_09_each_missing_required_field_is_a_schema_rejection(self, api):
        """Two separately incomplete payloads, one identifier between them.

        PRD: "Schema validation (`ERR_INVALID_REQUEST`, 400) — required inputs
        present, JSON types correct, enum members inside their declared sets, numbers
        inside their declared ranges, strings non-empty and within their maximum lengths,
        timestamps ISO 8601 with a trailing `Z`, and pagination parameters inside their
        bounds."

        Design: Corner/entities/product_model_create_missing_required_field_rejected
        """
        without_fuel = product_model_payload()
        del without_fuel["fuel_type"]
        without_r_value = product_model_payload()
        del without_r_value["insulation_r_value"]

        first = api.create_product_model(without_fuel, compliance_engineer_headers())
        second = api.create_product_model(without_r_value, compliance_engineer_headers())

        validate_error(first, ERR_INVALID_REQUEST, expected_status=400)
        validate_error(second, ERR_INVALID_REQUEST, expected_status=400)

    def test_10_neither_rejected_creation_persisted_a_partial_row(self, api):
        """Only the complete payload leaves a model behind.

        PRD: "Creating a model supplies its `model_code` — the catalogue code, unique
        across all models, non-empty, at most 24 characters and restricted to uppercase
        letters, digits and hyphens, which later becomes the model's serial-number prefix
        — together with `fuel_type` (`GAS`, `ELECTRIC` or `HEAT_PUMP`),
        `nominal_capacity_gallons` between 20 and 120 inclusive, the distribution
        `channel` the model is catalogued for (`TRADE`, `RETAIL` or `BUILDER`), and
        `insulation_r_value`, the declared insulation R-value between 10.0 and 40.0
        inclusive."

        Design: Corner/entities/product_model_create_missing_required_field_rejected
        """
        without_fuel = product_model_payload()
        del without_fuel["fuel_type"]
        api.create_product_model(without_fuel, compliance_engineer_headers())

        complete = validate_success(
            api.create_product_model(
                product_model_payload(), compliance_engineer_headers()
            ),
            expected_status=201,
        )
        rows, meta = validate_paginated(
            api.list_product_models(compliance_engineer_headers(), {"limit": 10, "offset": 0})
        )

        assert complete["fuel_type"] == "GAS"
        assert complete["insulation_r_value"] == 20
        assert len(rows) == 1
        assert meta["total_count"] == 1


class TestComponentLotCertificateDefault:
    """The optional boolean that decides whether a lot can ever be released."""

    def test_11_an_omitted_certificate_of_conformance_defaults_to_false(self, api):
        """The default is applied rather than the field being left absent.

        PRD: "The booking names `supplier_id`, the manufacturer `part_number` printed
        on the lot label (non-empty, at most 40 characters, and unique among that one
        supplier's lots — a collision reports `ERR_DUPLICATE_CODE`), the `category` drawn
        from the same six-member component-family enumeration, the `quantity` of pieces
        received which must be at least 1, and optionally `certificate_of_conformance`, a
        boolean that defaults to `false` when omitted."

        Design: Corner/entities/component_lot_certificate_of_conformance_defaults_false
        """
        supplier = make_qualified_supplier(api)
        payload = component_lot_payload(supplier["id"])
        del payload["certificate_of_conformance"]

        lot = validate_success(
            api.create_component_lot(payload, supplier_quality_headers()),
            expected_status=201,
        )

        assert lot["certificate_of_conformance"] is False
        assert lot["status"] == "QUARANTINED"

    def test_12_a_lot_defaulted_to_no_certificate_cannot_be_released(self, api):
        """The uncertified lot is refused while its certified sibling is released.

        PRD: "The lot must carry a signed certificate of conformance — a lot whose
        `certificate_of_conformance` is `false` cannot be released and the call is refused
        with `ERR_INVALID_COMPONENT_LOT_STATE`."

        Design: Corner/entities/component_lot_certificate_of_conformance_defaults_false
        """
        supplier = make_qualified_supplier(api)
        defaulted_payload = component_lot_payload(supplier["id"])
        del defaulted_payload["certificate_of_conformance"]
        defaulted = data_of(
            api.create_component_lot(defaulted_payload, supplier_quality_headers())
        )
        certified = data_of(
            api.create_component_lot(
                component_lot_payload(supplier["id"], part_number="GV-881"),
                supplier_quality_headers(),
            )
        )

        refused = api.release_component_lot(
            defaulted["id"], quality_inspector_headers()
        )
        released = validate_success(
            api.release_component_lot(certified["id"], quality_inspector_headers())
        )

        validate_error(refused, ERR_INVALID_COMPONENT_LOT_STATE, expected_status=409)
        assert validate_success(
            api.get_component_lot(defaulted["id"], quality_inspector_headers())
        )["status"] == "QUARANTINED"
        assert released["status"] == "RELEASED"
        assert released["remaining_quantity"] == 50
        assert released["consumed_quantity"] == 0


def _released_lot_from_august_then_the_clock_moves_on(api):
    """A released August tank lot, read against a September clock.

    The cohort key belongs to the month the lot was opened in, so staging a unit
    a month and a half later must not pick the newer month up.
    """
    supply = x.make_supply_base(api)
    model_id = make_model(api)["id"]
    batch = make_fired_batch(api)
    tank_lot_id = x.make_released_tank_lot(api, model_id, batch.batch_id)
    x.set_clock(api, "2026-09-20T00:00:00Z")
    return supply, model_id, tank_lot_id


class TestHeaterUnitDerivedFromItsLot:
    """The two fields a staging caller is never allowed to supply."""

    def test_13_a_staged_unit_inherits_its_model_and_cohort_from_the_tank_lot(self, api):
        """The September clock is ignored in favour of the lot's August cohort key.

        PRD: "The unit's `product_model_id` is **never** supplied by the client: it is
        inherited from the named tank lot at creation, as is `production_period`, which is
        copied verbatim from the lot's own cohort key."

        Design: Corner/entities/heater_unit_computed_model_and_period_derived_from_lot
        """
        supply, model_id, tank_lot_id = _released_lot_from_august_then_the_clock_moves_on(api)

        unit = validate_success(
            api.create_heater_unit(
                heater_unit_payload(tank_lot_id, supply.valve_lot_id, supply.gas_lot_id),
                plant_operator_headers(),
            ),
            expected_status=201,
        )

        assert unit["build_status"] == "COMPONENTS_STAGED"
        assert unit["product_model_id"] == model_id
        assert unit["production_period"] == "2026-08"
        assert unit["serial_number"] is None
        assert unit["label_status"] == "NONE"
        assert unit["shipped_at"] is None
        assert unit["months_in_service"] is None
        assert unit["water_hardness_band"] is None

    def test_14_the_lot_counts_the_unit_without_giving_up_a_good_tank(self, api):
        """Drawing a tank into a unit does not disturb the settled lot ledger.

        PRD: "Its `unit_count` is derived at read time as the number of heater units
        drawn from this lot whose `build_status` is anything other than `SCRAPPED`."

        Design: Corner/entities/heater_unit_computed_model_and_period_derived_from_lot
        """
        supply, _model_id, tank_lot_id = _released_lot_from_august_then_the_clock_moves_on(api)

        data_of(
            api.create_heater_unit(
                heater_unit_payload(tank_lot_id, supply.valve_lot_id, supply.gas_lot_id),
                plant_operator_headers(),
            )
        )
        lot = validate_success(api.get_tank_lot(tank_lot_id, plant_operator_headers()))

        assert lot["unit_count"] == 1
        assert lot["good_quantity"] == 120
        assert_tank_lot_ledger(lot)


class TestAssetRangeAndEnumAdmission:
    """Declared numeric ranges are inclusive; declared enumerations are closed."""

    def test_15_a_firing_ceiling_outside_the_declared_range_is_refused(self, api):
        """One thousand degrees is admissible; twelve hundred and six-fifty are not.

        PRD: "Furnaces are asset master data, registered by a `PlantAdmin` with a
        `furnace_code` — plant-unique, non-empty, at most 20 characters, colliding as
        `ERR_DUPLICATE_CODE` — and a `max_firing_temp_c`, the maximum sustained chamber
        temperature in Celsius, between 700 and 1000 inclusive."

        Design: Corner/entities/furnace_and_batch_numeric_range_and_enum_constraints
        """
        too_hot = api.create_furnace(
            furnace_payload(furnace_code="FURN-HOT", max_firing_temp_c=1200),
            plant_admin_headers(),
        )
        too_cold = api.create_furnace(
            furnace_payload(furnace_code="FURN-COLD", max_firing_temp_c=650),
            plant_admin_headers(),
        )
        at_the_ceiling = validate_success(
            api.create_furnace(
                furnace_payload(furnace_code="FURN-MAX", max_firing_temp_c=1000),
                plant_admin_headers(),
            ),
            expected_status=201,
        )

        validate_error(too_hot, ERR_INVALID_REQUEST, expected_status=400)
        validate_error(too_cold, ERR_INVALID_REQUEST, expected_status=400)
        assert at_the_ceiling["max_firing_temp_c"] == 1000
        assert at_the_ceiling["occupied_window_count"] == 0

    def test_16_a_fuel_type_outside_the_declared_enumeration_is_refused(self, api):
        """Solar is not one of the three fuels the catalogue admits.

        PRD: "Schema validation (`ERR_INVALID_REQUEST`, 400) — required inputs
        present, JSON types correct, enum members inside their declared sets, numbers
        inside their declared ranges, strings non-empty and within their maximum lengths,
        timestamps ISO 8601 with a trailing `Z`, and pagination parameters inside their
        bounds."

        Design: Corner/entities/furnace_and_batch_numeric_range_and_enum_constraints
        """
        response = api.create_product_model(
            product_model_payload(model_code="SOLAR-1", fuel_type="SOLAR"),
            compliance_engineer_headers(),
        )

        validate_error(response, ERR_INVALID_REQUEST, expected_status=400)
        _rows, meta = validate_paginated(
            api.list_product_models(
                compliance_engineer_headers(), {"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 0


def _lined_lot_with_two_holiday_records(api):
    """Two successive holiday records of the same type on one lined lot."""
    model_id = make_model(api)["id"]
    batch = make_fired_batch(api)
    lot_id = make_lined_tank_lot(api, model_id, batch.batch_id)
    first = data_of(
        api.create_lining_inspection(
            holiday_inspection_payload(
                lot_id, tank_lot_version(api, lot_id), holiday_count=1
            ),
            quality_inspector_headers(),
        )
    )
    second = data_of(
        api.create_lining_inspection(
            holiday_inspection_payload(
                lot_id, tank_lot_version(api, lot_id), holiday_count=2
            ),
            quality_inspector_headers(),
        )
    )
    return lot_id, first, second


class TestLiningInspectionImmutability:
    """The one resource type that carries no version and no updated_at."""

    def test_17_an_inspection_record_carries_only_an_id_and_a_creation_stamp(self, api):
        """Neither of the mutation fields appears on either record.

        PRD: "It therefore carries only `id` and `created_at`. Both `updated_at` and
        `version` are **absent** from every lining-inspection response — the single-record
        read and the per-lot sub-resource listing alike."

        Design: Corner/entities/lining_inspection_is_immutable_and_has_no_version
        """
        lot_id, first, _second = _lined_lot_with_two_holiday_records(api)

        rows = x.lot_inspections(api, lot_id)
        single = validate_success(
            api.get_lining_inspection(first["id"], quality_inspector_headers())
        )

        assert len(rows) == 2
        assert_created_at_ascending(rows)
        for row in rows:
            assert_immutable_record_fields(row)
        assert_immutable_record_fields(single)

    def test_18_the_older_record_of_the_same_type_is_superseded_not_rewritten(self, api):
        """Both measurements survive, distinguished only by their record status.

        PRD: "Supersession is expressed by the `record_status` field on the record
        itself rather than by mutating history."

        Design: Corner/entities/lining_inspection_is_immutable_and_has_no_version
        """
        lot_id, first, _second = _lined_lot_with_two_holiday_records(api)

        rows = x.lot_inspections(api, lot_id)
        lot = validate_success(api.get_tank_lot(lot_id, quality_inspector_headers()))

        assert rows[0]["id"] == first["id"]
        assert rows[0]["holiday_count"] == 1
        assert rows[0]["holidays_per_tank"] == approx4(0.1667)
        assert rows[0]["result"] == "PASS"
        assert rows[0]["record_status"] == "SUPERSEDED"
        assert rows[1]["holiday_count"] == 2
        assert rows[1]["holidays_per_tank"] == approx4(0.3333)
        assert rows[1]["result"] == "PASS"
        assert rows[1]["record_status"] == "CURRENT"
        assert all(row["inspector_user_id"] == USER_INSPECTOR for row in rows)
        assert lot["status"] == "LINED"


def _a_staged_unit_and_a_spare_released_lot(api):
    """One staged unit drawing three lots, plus a fourth lot nothing references."""
    supply = x.make_supply_base(api)
    model_id = make_model(api)["id"]
    batch = make_fired_batch(api)
    tank_lot_id = x.make_released_tank_lot(api, model_id, batch.batch_id)
    spare = data_of(
        api.create_component_lot(
            component_lot_payload(
                supply.gas_supplier_id, part_number="GV-899", quantity=10
            ),
            supplier_quality_headers(),
        )
    )
    data_of(api.release_component_lot(spare["id"], quality_inspector_headers()))
    unit = data_of(
        api.create_heater_unit(
            heater_unit_payload(tank_lot_id, supply.valve_lot_id, supply.gas_lot_id),
            plant_operator_headers(),
        )
    )
    return supply, tank_lot_id, spare["id"], unit


class TestHeaterUnitForeignKeyResolution:
    """Each identifier in the staging body is resolved before anything is built."""

    def test_19_an_unresolvable_body_reference_names_the_type_it_could_not_find(
        self, api
    ):
        """A bad tank lot and a bad valve lot report two different not-founds.

        PRD: "Body reference resolution — every foreign-key id supplied in the request
        **body** resolves to an existing row, yielding that referenced entity's not-found
        code. This applies to every create endpoint and to every action endpoint that takes
        an id in its body."

        Design: Corner/entities/heater_unit_body_fk_unknown_tank_lot_returns_not_found
        """
        supply, tank_lot_id, _spare_id, _unit = _a_staged_unit_and_a_spare_released_lot(api)

        unknown_tank = api.create_heater_unit(
            heater_unit_payload(
                NON_EXISTENT_UUID, supply.valve_lot_id, supply.gas_lot_id
            ),
            plant_operator_headers(),
        )
        unknown_valve = api.create_heater_unit(
            heater_unit_payload(tank_lot_id, NON_EXISTENT_UUID, supply.gas_lot_id),
            plant_operator_headers(),
        )

        validate_error(unknown_tank, ERR_TANK_LOT_NOT_FOUND, expected_status=404)
        validate_error(unknown_valve, ERR_COMPONENT_LOT_NOT_FOUND, expected_status=404)

    def test_20_the_same_body_with_every_reference_resolvable_stages_the_unit(self, api):
        """Only the identifiers changed between the refusals and this acceptance.

        PRD: "A `PlantOperator` stages one by naming the `tank_lot_id` the tank came
        from, the `safety_valve_lot_id` supplying its temperature-and-pressure relief valve
        — required for every fuel type without exception — and, where the fuel type calls
        for it, the `gas_control_lot_id` supplying its gas control valve."

        Design: Corner/entities/heater_unit_body_fk_unknown_tank_lot_returns_not_found
        """
        _supply, tank_lot_id, _spare_id, unit = _a_staged_unit_and_a_spare_released_lot(api)

        lot = validate_success(api.get_tank_lot(tank_lot_id, plant_operator_headers()))

        assert unit["build_status"] == "COMPONENTS_STAGED"
        assert unit["tank_lot_id"] == tank_lot_id
        assert lot["unit_count"] == 1


class TestHeaterUnitReverseLookups:
    """Every foreign key on a unit is also a list filter on the unit collection."""

    def test_21_each_of_the_three_lot_filters_finds_the_one_unit(self, api):
        """Tank lot, gas control lot and safety valve lot each return that unit alone.

        PRD: "Units can be listed filtered by `tank_lot_id`, `product_model_id`,
        `gas_control_lot_id`, `safety_valve_lot_id`, `build_status`, `production_period` or
        `serial_number`."

        Design: Corner/entities/heater_unit_reverse_lookup_by_each_foreign_key
        """
        supply, tank_lot_id, spare_id, unit = _a_staged_unit_and_a_spare_released_lot(api)

        filters = {
            "tank_lot_id": tank_lot_id,
            "gas_control_lot_id": supply.gas_lot_id,
            "safety_valve_lot_id": supply.valve_lot_id,
        }
        for field, value in filters.items():
            rows, meta = validate_paginated(
                api.list_heater_units(
                    plant_operator_headers(), {field: value, "limit": 10, "offset": 0}
                )
            )
            assert meta["total_count"] == 1, field
            assert [row["id"] for row in rows] == [unit["id"]], field

        empty, empty_meta = validate_paginated(
            api.list_heater_units(
                plant_operator_headers(),
                {"gas_control_lot_id": spare_id, "limit": 10, "offset": 0},
            )
        )
        assert empty == []
        assert empty_meta["total_count"] == 0

    def test_22_a_staged_unit_has_not_yet_drawn_the_pieces_it_references(self, api):
        """The reverse lookup finds the unit, but the piece ledger has not moved.

        PRD: "Units still at `COMPONENTS_STAGED` have not drawn their pieces yet, and
        units that reached `SCRAPPED` have returned theirs, so neither contributes."

        Design: Corner/entities/heater_unit_reverse_lookup_by_each_foreign_key
        """
        supply, _tank_lot_id, _spare_id, _unit = _a_staged_unit_and_a_spare_released_lot(api)

        gas = validate_success(
            api.get_component_lot(supply.gas_lot_id, quality_inspector_headers())
        )
        valve = validate_success(
            api.get_component_lot(supply.valve_lot_id, quality_inspector_headers())
        )

        for lot in (gas, valve):
            assert lot["status"] == "RELEASED"
            assert lot["consumed_quantity"] == 0
            assert lot["remaining_quantity"] == 50
            assert_component_lot_ledger(lot)
