"""One call violating two rules at once reports only the higher-priority code.

Each pair is then separated: the winning violation is repaired and the same call
repeated, so the suppressed rule is shown to be live rather than absent.
"""

from types import SimpleNamespace

from test_helpers import (
    approx4,
    data_of,
    ERR_INVALID_UNIT_STATE,
    ERR_MODEL_NOT_CERTIFIED,
    ERR_SAMPLE_SIZE_INSUFFICIENT,
    ERR_SOD_INSPECTOR_IS_WELDER,
    compliance_engineer_headers,
    holiday_inspection_payload,
    lot_inspections,
    make_fired_batch,
    make_lined_tank_lot,
    make_model,
    plant_operator_headers,
    quality_inspector_headers,
    tank_lot_version,
    USER_WELD_OPERATOR,
    validate_error,
    validate_success,
    fixtures as x,
)


def _staged_unit_of_an_uncertified_model(api):
    """A staged unit whose model has never been tested or released.

    Labelling it therefore breaks the state rule and the certification rule in
    the same request.
    """
    supply = x.make_supply_base(api)
    model_id = make_model(api)["id"]
    batch = make_fired_batch(api)
    tank_lot_id = x.make_released_tank_lot(api, model_id, batch.batch_id)
    plant = SimpleNamespace(
        tank_lot_id=tank_lot_id,
        valve_lot_id=supply.valve_lot_id,
        gas_lot_id=supply.gas_lot_id,
    )
    return model_id, x.stage_unit(api, plant)


class TestLabellingStateBeatsCertification:
    """A staged unit of an uncertified model reports the state violation."""

    def test_01_the_state_violation_outranks_the_certification_violation(self, api):
        """Both rules answer 409, so only the error_id distinguishes them.

        PRD: "After the global gate, the business rules are evaluated in the
        following order."

        Design: Difficulty/priority_pair_validation_conflict/unit_state_beats_model_not_certified_on_label
        """
        _model_id, unit_id = _staged_unit_of_an_uncertified_model(api)

        response = api.label_unit(unit_id, plant_operator_headers())

        validate_error(response, ERR_INVALID_UNIT_STATE, expected_status=409)

    def test_02_repairing_the_state_surfaces_the_suppressed_certification_rule(
        self, api
    ):
        """Once the unit is assembled the lower-priority rule is what refuses it.

        PRD: "Model certified — `ERR_MODEL_NOT_CERTIFIED` (409), on unit labelling
        and on releasing a unit hold."

        Design: Difficulty/priority_pair_validation_conflict/unit_state_beats_model_not_certified_on_label
        """
        _model_id, unit_id = _staged_unit_of_an_uncertified_model(api)

        assembled = validate_success(
            api.assemble_unit(unit_id, plant_operator_headers())
        )
        assert assembled["build_status"] == "ASSEMBLED"

        response = api.label_unit(unit_id, plant_operator_headers())

        validate_error(response, ERR_MODEL_NOT_CERTIFIED, expected_status=409)

    def test_03_neither_refused_labelling_attempt_mints_a_serial(self, api):
        """The unit is still unlabelled and the model is still in its start postures.

        PRD: "The unit then moves `ASSEMBLED → LABELED` with `label_status` set to
        `APPLIED` and a freshly minted `serial_number`."

        Design: Difficulty/priority_pair_validation_conflict/unit_state_beats_model_not_certified_on_label
        """
        model_id, unit_id = _staged_unit_of_an_uncertified_model(api)

        api.label_unit(unit_id, plant_operator_headers())
        data_of(api.assemble_unit(unit_id, plant_operator_headers()))
        api.label_unit(unit_id, plant_operator_headers())

        unit = validate_success(api.get_heater_unit(unit_id, plant_operator_headers()))
        model = validate_success(
            api.get_product_model(model_id, compliance_engineer_headers())
        )

        assert unit["serial_number"] is None
        assert unit["label_status"] == "NONE"
        assert model["certification_status"] == "UNCERTIFIED"
        assert model["release_status"] == "DRAFT"


def _lined_lot_welded_by_the_weld_operator(api):
    """A LINED 120-tank lot whose weld operator is on record.

    The required sample for this lot is six tanks, so a two-tank sample is also
    inadequate - which is the second violation the separation rule outranks.
    """
    model_id = make_model(api)["id"]
    batch = make_fired_batch(api)
    lot_id = make_lined_tank_lot(api, model_id, batch.batch_id)
    return lot_id


class TestInspectionSeparationBeatsSampleAdequacy:
    """The welder filing his own inspection is refused before the body is judged."""

    def test_04_the_separation_rule_answers_before_the_sample_rule(self, api):
        """A 403 rather than the 422 an early body check would have produced.

        PRD: "Inspector/welder separation — `ERR_SOD_INSPECTOR_IS_WELDER` (403), on
        lining-inspection filing."

        Design: Difficulty/priority_pair_validation_conflict/sod_inspector_beats_sample_size_on_inspection
        """
        lot_id = _lined_lot_welded_by_the_weld_operator(api)

        response = api.create_lining_inspection(
            holiday_inspection_payload(
                lot_id, tank_lot_version(api, lot_id), sample_size=2, holiday_count=0
            ),
            quality_inspector_headers(USER_WELD_OPERATOR),
        )

        validate_error(response, ERR_SOD_INSPECTOR_IS_WELDER, expected_status=403)

    def test_05_an_independent_inspector_surfaces_the_sample_adequacy_rule(self, api):
        """The identical payload under a different identity reports the 422.

        PRD: "Inspection sample adequacy — `ERR_SAMPLE_SIZE_INSUFFICIENT` (422), on
        lining-inspection filing."

        Design: Difficulty/priority_pair_validation_conflict/sod_inspector_beats_sample_size_on_inspection
        """
        lot_id = _lined_lot_welded_by_the_weld_operator(api)

        response = api.create_lining_inspection(
            holiday_inspection_payload(
                lot_id, tank_lot_version(api, lot_id), sample_size=2, holiday_count=0
            ),
            quality_inspector_headers(),
        )

        validate_error(response, ERR_SAMPLE_SIZE_INSUFFICIENT, expected_status=422)

    def test_06_an_adequate_sample_from_an_independent_inspector_is_accepted(self, api):
        """Six tanks with no discontinuities passes and leaves the lot LINED.

        PRD: "The required sample is the larger of 3 tanks and five percent of the
        lot's `planned_quantity` rounded up to a whole tank; a `sample_size` below that
        figure is refused with `ERR_SAMPLE_SIZE_INSUFFICIENT` rather than producing a
        `FAIL` result."

        Design: Difficulty/priority_pair_validation_conflict/sod_inspector_beats_sample_size_on_inspection
        """
        lot_id = _lined_lot_welded_by_the_weld_operator(api)

        accepted = data_of(
            api.create_lining_inspection(
                holiday_inspection_payload(
                    lot_id, tank_lot_version(api, lot_id), holiday_count=0
                ),
                quality_inspector_headers(),
            )
        )
        lot = validate_success(api.get_tank_lot(lot_id, quality_inspector_headers()))
        rows = lot_inspections(api, lot_id)

        assert accepted["holidays_per_tank"] == approx4(0.0000)
        assert accepted["result"] == "PASS"
        assert lot["weld_operator_user_id"] == USER_WELD_OPERATOR
        assert lot["status"] == "LINED"
        assert len(rows) == 1
        assert rows[0]["record_status"] == "CURRENT"
