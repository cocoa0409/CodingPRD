"""Guards that read the state of a row the request never names.

In each pair nothing about the target changes between the refusal and the
acceptance; the only mutation is on the entity reached through a foreign key.
"""

from types import SimpleNamespace

from test_helpers import (
    approx2,
    assert_version_unchanged,
    certification_approver_headers,
    compliance_engineer_headers,
    component_lot_payload,
    data_of,
    ERR_COMPONENT_SUPPLIER_NOT_QUALIFIED,
    ERR_MODEL_NOT_CERTIFIED,
    ERR_MODEL_NOT_RELEASED,
    make_certified_model,
    make_fired_batch,
    make_pending_supplier,
    plant_operator_headers,
    qualify_payload,
    quality_inspector_headers,
    reason_payload,
    supplier_quality_headers,
    validate_error,
    validate_success,
    fixtures as x,
)


def _quarantined_lot_of_a_pending_supplier(api):
    """A perfectly valid quarantined lot whose supplier has never been scored.

    The lot carries its certificate of conformance and fifty pieces, so the only
    obstacle to releasing it lives on the supplier row.
    """
    supplier = make_pending_supplier(api)
    lot = data_of(
        api.create_component_lot(
            component_lot_payload(supplier["id"]), supplier_quality_headers()
        )
    )
    return supplier["id"], lot


class TestComponentLotReleaseReadsItsSupplier:
    """The release guard is satisfied only by mutating the supplier."""

    def test_01_a_pending_supplier_blocks_the_release_of_a_valid_lot(self, api):
        """The lot is untouched by the refusal, including its version.

        PRD: "The owning supplier's `qualification_status` must be `QUALIFIED` or
        `CONDITIONAL`; a `PENDING` or `DISQUALIFIED` supplier yields
        `ERR_COMPONENT_SUPPLIER_NOT_QUALIFIED`."

        Design: Difficulty/cross_entity_state_dependency/component_lot_release_requires_supplier_qualified
        """
        _supplier_id, lot = _quarantined_lot_of_a_pending_supplier(api)

        response = api.release_component_lot(lot["id"], quality_inspector_headers())

        validate_error(response, ERR_COMPONENT_SUPPLIER_NOT_QUALIFIED, expected_status=409)
        after = validate_success(
            api.get_component_lot(lot["id"], quality_inspector_headers())
        )
        assert after["status"] == "QUARANTINED"
        assert_version_unchanged(lot, after)

    def test_02_scoring_the_supplier_into_the_qualifying_band_is_the_only_change(
        self, api
    ):
        """The weighted score of 91.40 is what carries the supplier over the floor.

        PRD: "The three components are then combined with weights of 0.40 for the
        audit component, 0.35 for the parts-per-million component and 0.25 for the
        corrective-action component, and the weighted sum is rounded half up to two
        decimal places to become `qualification_score`."

        Design: Difficulty/cross_entity_state_dependency/component_lot_release_requires_supplier_qualified
        """
        supplier_id, _lot = _quarantined_lot_of_a_pending_supplier(api)

        scored = validate_success(
            api.qualify_supplier(
                supplier_id, qualify_payload(), supplier_quality_headers()
            )
        )

        assert scored["qualification_score"] == approx2(91.40)
        assert scored["qualification_status"] == "QUALIFIED"

    def test_03_the_identical_release_call_then_succeeds(self, api):
        """The same request on the same unchanged lot is now accepted.

        PRD: "A `QualityInspector` releases a quarantined lot to the line once
        incoming inspection is satisfied, moving it `QUARANTINED → RELEASED` and
        clearing any `reject_reason_code`."

        Design: Difficulty/cross_entity_state_dependency/component_lot_release_requires_supplier_qualified
        """
        supplier_id, lot = _quarantined_lot_of_a_pending_supplier(api)

        api.release_component_lot(lot["id"], quality_inspector_headers())
        data_of(
            api.qualify_supplier(
                supplier_id, qualify_payload(), supplier_quality_headers()
            )
        )
        released = validate_success(
            api.release_component_lot(lot["id"], quality_inspector_headers())
        )

        assert released["status"] == "RELEASED"
        assert released["reject_reason_code"] is None
        assert released["remaining_quantity"] == 50
        assert released["consumed_quantity"] == 0


def _two_assembled_units_of_a_certified_but_undistributed_model(api):
    """A model with an approved certification that has never reached a channel.

    Both units are fully built against a released tank lot and released component
    lots, so the units themselves are ready to be labelled.
    """
    supply = x.make_supply_base(api)
    certified = make_certified_model(api)
    batch = make_fired_batch(api)
    tank_lot_id = x.make_released_tank_lot(api, certified.model_id, batch.batch_id)
    plant = SimpleNamespace(
        tank_lot_id=tank_lot_id,
        valve_lot_id=supply.valve_lot_id,
        gas_lot_id=supply.gas_lot_id,
    )
    first = x.assemble_unit(api, plant)
    second = x.assemble_unit(api, plant)
    return certified.model_id, first, second


class TestUnitLabellingReadsBothModelDimensions:
    """Labelling is refused twice on the same remote row for two different reasons."""

    def test_04_a_certified_but_undistributed_model_blocks_labelling(self, api):
        """The channel dimension refuses while the certification dimension is fine.

        PRD: "A `PlantOperator` labels a unit that is `ASSEMBLED`, and the unit's
        model must have `certification_status` `CERTIFIED` — anything else, including
        `SUSPENDED` and `DECERTIFIED`, is refused with `ERR_MODEL_NOT_CERTIFIED` — and
        `release_status` `RELEASED`, with anything else refused as
        `ERR_MODEL_NOT_RELEASED`."

        Design: Difficulty/cross_entity_state_dependency/unit_label_requires_model_certified_and_released
        """
        model_id, first, _second = _two_assembled_units_of_a_certified_but_undistributed_model(api)

        response = api.label_unit(first, plant_operator_headers())

        validate_error(response, ERR_MODEL_NOT_RELEASED, expected_status=409)
        model = validate_success(
            api.get_product_model(model_id, compliance_engineer_headers())
        )
        assert model["certification_status"] == "CERTIFIED"
        assert model["release_status"] == "DRAFT"

    def test_05_releasing_the_model_lets_the_same_unit_mint_its_serial(self, api):
        """The first serial of the cohort proves the unit was never the obstacle.

        PRD: "The third is a sequence number, left-padded with zeros to a width of
        five digits, whose value is one more than the count of units that share this
        unit's `product_model_id` **and** its `production_period` **and** already hold a
        non-null `serial_number`."

        Design: Difficulty/cross_entity_state_dependency/unit_label_requires_model_certified_and_released
        """
        model_id, first, _second = _two_assembled_units_of_a_certified_but_undistributed_model(api)

        api.label_unit(first, plant_operator_headers())
        data_of(api.release_model_to_channel(model_id, compliance_engineer_headers()))
        labelled = validate_success(api.label_unit(first, plant_operator_headers()))

        assert labelled["build_status"] == "LABELED"
        assert labelled["label_status"] == "APPLIED"
        assert labelled["serial_number"] == "GX50-T-202608-00001"

    def test_06_suspending_the_certification_blocks_the_sibling_unit(self, api):
        """The same guard refuses again, now on the other dimension of the same row.

        PRD: "Model certified — `ERR_MODEL_NOT_CERTIFIED` (409), on unit labelling
        and on releasing a unit hold."

        Design: Difficulty/cross_entity_state_dependency/unit_label_requires_model_certified_and_released
        """
        model_id, first, second = _two_assembled_units_of_a_certified_but_undistributed_model(api)

        data_of(api.release_model_to_channel(model_id, compliance_engineer_headers()))
        data_of(api.label_unit(first, plant_operator_headers()))
        data_of(
            api.suspend_model_certification(
                model_id, reason_payload(), certification_approver_headers()
            )
        )

        response = api.label_unit(second, plant_operator_headers())

        validate_error(response, ERR_MODEL_NOT_CERTIFIED, expected_status=409)
        unit = validate_success(api.get_heater_unit(second, plant_operator_headers()))
        model = validate_success(
            api.get_product_model(model_id, compliance_engineer_headers())
        )
        assert unit["build_status"] == "ASSEMBLED"
        assert unit["serial_number"] is None
        assert unit["label_status"] == "NONE"
        assert model["certification_status"] == "SUSPENDED"
        assert model["release_status"] == "RELEASED"
        assert model["held_unit_count"] == 0
