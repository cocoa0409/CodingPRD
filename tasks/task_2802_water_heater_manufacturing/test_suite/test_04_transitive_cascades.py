"""Multi-hop containment reaching entities the caller never named.

One supplier-quality decision walks blocked lots to the units that consumed them
and on to their catalogue model, and one quality record walks a shared furnace
batch sideways into the sibling lots fired alongside it.
"""

from test_helpers import (
    adhesion_inspection_payload,
    approx4,
    assert_tank_lot_ledger,
    compliance_engineer_headers,
    data_of,
    failing_holiday_payload,
    holiday_inspection_payload,
    make_fired_batch,
    make_full_plant,
    make_lined_tank_lot,
    make_model,
    plant_operator_headers,
    quality_inspector_headers,
    reason_payload,
    supplier_quality_headers,
    tank_lot_version,
    validate_success,
    fixtures as x,
)


def _plant_with_three_units_at_three_stages(api):
    """One released model with an assembled, a labelled and a shipped unit.

    All three units consume the same gas-control lot and the same safety-valve
    lot, so the only thing distinguishing them when containment fires is how far
    down the build they have travelled.
    """
    plant = make_full_plant(api)
    assembled = x.assemble_unit(api, plant)
    labeled = x.label_unit(api, plant)
    shipped = x.ship_unit(api, plant)
    return plant, assembled, labeled, shipped


def _disqualify_gas_supplier(api, plant):
    """Disqualify the gas-control supplier, firing the containment cascade."""
    return validate_success(
        api.disqualify_supplier(
            plant.gas_supplier_id,
            reason_payload(reason_code="AUDIT_FAILURE"),
            supplier_quality_headers(),
        )
    )


class TestSupplierDisqualificationCascade:
    """Supplier → component lot → heater unit → product model, in one request."""

    def test_01_disqualification_stores_the_reason_and_clears_the_expiry(self, api):
        """The supplier itself records the containment event before the hops fire.

        PRD: "A `SupplierQualityManager` disqualifies a supplier that is currently
        `QUALIFIED` or `CONDITIONAL`, supplying a `reason_code`; the supplier moves to
        `DISQUALIFIED`, that `reason_code` is stored as `disqualification_reason_code`,
        and `qualified_until` is cleared."

        Design: Difficulty/transitive_cascade/supplier_disqualification_three_hop_to_model_restriction
        """
        plant, _a, _l, _s = _plant_with_three_units_at_three_stages(api)

        supplier = _disqualify_gas_supplier(api, plant)

        assert supplier["qualification_status"] == "DISQUALIFIED"
        assert supplier["disqualification_reason_code"] == "AUDIT_FAILURE"
        assert supplier["qualified_until"] is None
        assert supplier["blocked_lot_count"] == 1

    def test_02_hop_one_blocks_only_the_disqualified_supplier_s_lots(self, api):
        """The safety-valve lot of the untouched supplier stays released.

        PRD: "**Hop 1** takes every component lot of that supplier whose `status` is
        `QUARANTINED` or `RELEASED`, in `created_at` ascending order, to `BLOCKED`,
        stamping each one's `reject_reason_code` with `SUPPLIER_DISQUALIFIED`."

        Design: Difficulty/transitive_cascade/supplier_disqualification_three_hop_to_model_restriction
        """
        plant, _a, _l, _s = _plant_with_three_units_at_three_stages(api)

        _disqualify_gas_supplier(api, plant)

        gas_lot = validate_success(
            api.get_component_lot(plant.gas_lot_id, supplier_quality_headers())
        )
        valve_lot = validate_success(
            api.get_component_lot(plant.valve_lot_id, supplier_quality_headers())
        )
        other_supplier = validate_success(
            api.get_supplier(plant.valve_supplier_id, supplier_quality_headers())
        )

        assert gas_lot["status"] == "BLOCKED"
        assert gas_lot["reject_reason_code"] == "SUPPLIER_DISQUALIFIED"
        assert valve_lot["status"] == "RELEASED"
        assert other_supplier["qualification_status"] == "QUALIFIED"

    def test_03_hop_two_holds_the_in_plant_units_and_remembers_where_they_were(
        self, api
    ):
        """The assembled and labelled units are held from different origins.

        PRD: "**Hop 2**, caused by hop 1, takes every heater unit whose
        `build_status` is `COMPONENTS_STAGED`, `ASSEMBLED` or `LABELED` and whose
        `gas_control_lot_id` or `safety_valve_lot_id` names one of the lots just
        blocked, again in `created_at` ascending order, to `HELD` with
        `hold_reason_code` set to `COMPONENT_LOT_BLOCKED`; a unit that was `ASSEMBLED`
        or `LABELED` records that state in `held_from_status`, while a unit that was
        `COMPONENTS_STAGED` leaves `held_from_status` null because that is the default
        state a hold release restores."

        Design: Difficulty/transitive_cascade/supplier_disqualification_three_hop_to_model_restriction
        """
        plant, assembled, labeled, _shipped = _plant_with_three_units_at_three_stages(api)

        _disqualify_gas_supplier(api, plant)

        held_assembled = validate_success(
            api.get_heater_unit(assembled, plant_operator_headers())
        )
        held_labeled = validate_success(
            api.get_heater_unit(labeled, plant_operator_headers())
        )

        assert held_assembled["build_status"] == "HELD"
        assert held_assembled["held_from_status"] == "ASSEMBLED"
        assert held_assembled["hold_reason_code"] == "COMPONENT_LOT_BLOCKED"
        assert held_assembled["label_status"] == "NONE"
        assert held_labeled["build_status"] == "HELD"
        assert held_labeled["held_from_status"] == "LABELED"
        assert held_labeled["serial_number"] == "GX50-T-202608-00001"

    def test_04_hop_two_leaves_the_shipped_unit_outside_the_hold_set(self, api):
        """A unit that already left the plant is not in the hop-2 status set.

        PRD: "**Hop 2**, caused by hop 1, takes every heater unit whose
        `build_status` is `COMPONENTS_STAGED`, `ASSEMBLED` or `LABELED` and whose
        `gas_control_lot_id` or `safety_valve_lot_id` names one of the lots just
        blocked, again in `created_at` ascending order, to `HELD` with
        `hold_reason_code` set to `COMPONENT_LOT_BLOCKED`; a unit that was `ASSEMBLED`
        or `LABELED` records that state in `held_from_status`, while a unit that was
        `COMPONENTS_STAGED` leaves `held_from_status` null because that is the default
        state a hold release restores."

        Design: Difficulty/transitive_cascade/supplier_disqualification_three_hop_to_model_restriction
        """
        plant, _a, _l, shipped = _plant_with_three_units_at_three_stages(api)

        _disqualify_gas_supplier(api, plant)

        unit = validate_success(api.get_heater_unit(shipped, plant_operator_headers()))

        assert unit["build_status"] == "SHIPPED"
        assert unit["hold_reason_code"] is None
        assert unit["label_status"] == "APPLIED"

    def test_05_hop_three_restricts_the_model_without_touching_certification(self, api):
        """Two held units restrict the channel posture and only that posture.

        PRD: "**Hop 3**, caused by hop 2, has every product model that owns at least
        one unit held in hop 2 recompute its `held_unit_count`, and any such model
        whose `release_status` is `RELEASED` moves `RELEASED → RESTRICTED`, in
        `created_at` ascending order."

        Design: Difficulty/transitive_cascade/supplier_disqualification_three_hop_to_model_restriction
        """
        plant, _a, _l, _s = _plant_with_three_units_at_three_stages(api)

        _disqualify_gas_supplier(api, plant)

        model = validate_success(
            api.get_product_model(plant.model_id, compliance_engineer_headers())
        )

        assert model["held_unit_count"] == 2
        assert model["release_status"] == "RESTRICTED"
        assert model["certification_status"] == "CERTIFIED"


def _batch_one_rejection_short_of_quarantine(api):
    """Three lots off one fired batch, with the batch already carrying one rejection.

    TL-001 has failed its own holiday inspection, TL-003 has passed both of its
    inspections, and TL-002 is still awaiting inspection - so the next rejection
    is the one that crosses the quarantine threshold.
    """
    model_id = make_model(api)["id"]
    batch = make_fired_batch(api)
    lot_1 = make_lined_tank_lot(
        api, model_id, batch.batch_id, lot_code="TL-001", planned_quantity=120
    )
    lot_2 = make_lined_tank_lot(
        api, model_id, batch.batch_id, lot_code="TL-002", planned_quantity=60
    )
    lot_3 = make_lined_tank_lot(
        api, model_id, batch.batch_id, lot_code="TL-003", planned_quantity=40
    )
    data_of(
        api.create_lining_inspection(
            failing_holiday_payload(lot_1, tank_lot_version(api, lot_1)),
            quality_inspector_headers(),
        )
    )
    data_of(
        api.create_lining_inspection(
            adhesion_inspection_payload(lot_3, tank_lot_version(api, lot_3)),
            quality_inspector_headers(),
        )
    )
    data_of(
        api.create_lining_inspection(
            holiday_inspection_payload(lot_3, tank_lot_version(api, lot_3)),
            quality_inspector_headers(),
        )
    )
    return batch, lot_1, lot_2, lot_3


def _fail_the_second_lot(api, lot_2):
    """File the failing holiday inspection that crosses the batch threshold."""
    return data_of(
        api.create_lining_inspection(
            failing_holiday_payload(lot_2, tank_lot_version(api, lot_2)),
            quality_inspector_headers(),
        )
    )


class TestLiningQuarantineSiblingCascade:
    """Tank lot → shared batch → quarantine → sibling tank lots."""

    def test_06_the_second_direct_failure_charges_its_own_scrap_to_its_own_lot(
        self, api
    ):
        """TL-002 is rejected by its own inspection, not by the cascade.

        PRD: "**Hop 1** charges the scrap to the lot: `scrap_quantity` is added to
        `scrapped_quantity` and subtracted from `wip_quantity`, `last_scrap_quantity`
        is set to that same `scrap_quantity`, `rework_count` is increased by 1, and
        `cascade_rejected` is set to `false`."

        Design: Difficulty/transitive_cascade/lining_fail_quarantine_cascades_sibling_lots
        """
        _batch, _lot_1, lot_2, _lot_3 = _batch_one_rejection_short_of_quarantine(api)

        inspection = _fail_the_second_lot(api, lot_2)
        lot = validate_success(api.get_tank_lot(lot_2, quality_inspector_headers()))

        assert inspection["holidays_per_tank"] == approx4(0.6667)
        assert inspection["result"] == "FAIL"
        assert lot["status"] == "LINING_REJECTED"
        assert lot["wip_quantity"] == 50
        assert lot["scrapped_quantity"] == 10
        assert lot["last_scrap_quantity"] == 10
        assert lot["rework_count"] == 1
        assert lot["cascade_rejected"] is False

    def test_07_the_second_rejection_quarantines_the_shared_batch(self, api):
        """Crossing the threshold on this request is what fires the quarantine.

        PRD: "**Hop 3**, caused by hop 2, quarantines that batch if its
        `rejected_lot_count` has now reached 2, moving it `FIRED → QUARANTINED` with
        `quarantine_reason_code` set to `REPEAT_LINING_FAILURE`."

        Design: Difficulty/transitive_cascade/lining_fail_quarantine_cascades_sibling_lots
        """
        batch, _lot_1, lot_2, _lot_3 = _batch_one_rejection_short_of_quarantine(api)

        _fail_the_second_lot(api, lot_2)
        quarantined = validate_success(
            api.get_lining_batch(batch.batch_id, plant_operator_headers())
        )

        assert quarantined["rejected_lot_count"] == 2
        assert quarantined["status"] == "QUARANTINED"
        assert quarantined["quarantine_reason_code"] == "REPEAT_LINING_FAILURE"

    def test_08_the_quarantine_reaches_the_verified_sibling_lot_without_scrapping_it(
        self, api
    ):
        """TL-003 was never inspected badly, yet it is rejected laterally.

        PRD: "**Hop 4**, caused by hop 3, takes every **other** tank lot carrying
        that same batch whose `status` is `LINED`, `LINING_VERIFIED` or `FOAMED`, in
        `created_at` ascending order, to `LINING_REJECTED` — each with
        `cascade_rejected` set to `true` and `rework_count` increased by 1, but with
        `scrapped_quantity` and `wip_quantity` left exactly as they were and
        `last_scrap_quantity` left null, since no tanks were condemned by an
        inspection of those lots."

        Design: Difficulty/transitive_cascade/lining_fail_quarantine_cascades_sibling_lots
        """
        _batch, _lot_1, lot_2, lot_3 = _batch_one_rejection_short_of_quarantine(api)

        _fail_the_second_lot(api, lot_2)
        sibling = validate_success(api.get_tank_lot(lot_3, quality_inspector_headers()))

        assert sibling["status"] == "LINING_REJECTED"
        assert sibling["cascade_rejected"] is True
        assert sibling["rework_count"] == 1
        assert sibling["wip_quantity"] == 40
        assert sibling["scrapped_quantity"] == 0
        assert sibling["last_scrap_quantity"] is None

    def test_09_the_already_rejected_lot_is_not_swept_up_a_second_time(self, api):
        """TL-001 sits outside the hop-4 status set and adds no further rejection.

        PRD: "These cascade-induced rejections do **not** increase
        `rejected_lot_count`, so no further quarantine can follow from them."

        Design: Difficulty/transitive_cascade/lining_fail_quarantine_cascades_sibling_lots
        """
        batch, lot_1, lot_2, lot_3 = _batch_one_rejection_short_of_quarantine(api)

        _fail_the_second_lot(api, lot_2)

        first = validate_success(api.get_tank_lot(lot_1, quality_inspector_headers()))
        assert first["status"] == "LINING_REJECTED"
        assert first["rework_count"] == 1

        after = validate_success(
            api.get_lining_batch(batch.batch_id, plant_operator_headers())
        )
        assert after["rejected_lot_count"] == 2

        for lot_id in (lot_1, lot_2, lot_3):
            assert_tank_lot_ledger(
                validate_success(api.get_tank_lot(lot_id, quality_inspector_headers()))
            )
