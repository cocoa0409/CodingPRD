"""State graphs that are not forward chains.

A tank lot re-enters a state it already occupied without resetting the fields it
accumulated on the way round, and a product model carries two postures at once
so that neither coordinate can be inferred from the other.
"""

from test_helpers import (
    approx2,
    approx4,
    assert_tank_lot_ledger,
    certification_approver_headers,
    compliance_engineer_headers,
    data_of,
    failing_holiday_payload,
    make_certified_model,
    make_fired_batch,
    make_lined_tank_lot,
    make_model,
    plant_operator_headers,
    quality_inspector_headers,
    reason_payload,
    tank_lot_version,
    validate_success,
)


def _lot_rejected_by_its_own_inspection(api):
    """A 120-tank lot condemned to LINING_REJECTED by a failing holiday count.

    Four discontinuities across a six-tank sample is a density above the ceiling,
    so the filing carries the ten tanks it condemns and the lot takes the first
    hop of the rework loop.
    """
    model_id = make_model(api)["id"]
    batch = make_fired_batch(api)
    lot_id = make_lined_tank_lot(api, model_id, batch.batch_id)
    inspection = data_of(
        api.create_lining_inspection(
            failing_holiday_payload(lot_id, tank_lot_version(api, lot_id)),
            quality_inspector_headers(),
        )
    )
    return batch, lot_id, inspection


class TestTankLotReworkCycle:
    """LINED → LINING_REJECTED → RELINE_QUEUED → LINED, and what survives it."""

    def test_01_a_failing_holiday_density_charges_the_scrap_and_rejects_the_lot(
        self, api
    ):
        """Four holidays over six tanks is 0.6667, strictly above the ceiling.

        PRD: "For a `HOLIDAY` record the service then computes `holidays_per_tank`
        as the `holiday_count` divided by the `sample_size`, rounded half up to four
        decimal places, and sets `result` to `FAIL` when that density is **strictly
        greater** than 0.50 and to `PASS` otherwise — a density of exactly 0.5000
        passes."

        Design: Difficulty/non_linear_state_machine/tank_lot_reline_cycle_returns_to_lined
        """
        _batch, lot_id, inspection = _lot_rejected_by_its_own_inspection(api)

        lot = validate_success(api.get_tank_lot(lot_id, quality_inspector_headers()))

        assert inspection["holidays_per_tank"] == approx4(0.6667)
        assert inspection["result"] == "FAIL"
        assert lot["status"] == "LINING_REJECTED"
        assert lot["wip_quantity"] == 110
        assert lot["scrapped_quantity"] == 10
        assert lot["rework_count"] == 1
        assert lot["last_scrap_quantity"] == 10
        assert lot["cascade_rejected"] is False

    def test_02_authorising_a_reline_queues_the_lot_and_clears_the_last_scrap(self, api):
        """The rework counter is not rewound by queueing another cycle.

        PRD: "A `PlantOperator` may authorise another lining cycle, moving it
        `LINING_REJECTED → RELINE_QUEUED` and clearing `last_scrap_quantity`; this is
        refused with `ERR_REWORK_LIMIT_EXCEEDED` when `rework_count` has already
        reached 2, since a lot may go around the loop at most twice, and refused with
        `ERR_INVALID_TANK_LOT_STATE` when nothing remains in process
        (`wip_quantity` below 1)."

        Design: Difficulty/non_linear_state_machine/tank_lot_reline_cycle_returns_to_lined
        """
        _batch, lot_id, _inspection = _lot_rejected_by_its_own_inspection(api)

        queued = validate_success(
            api.authorize_reline(lot_id, plant_operator_headers())
        )

        assert queued["status"] == "RELINE_QUEUED"
        assert queued["last_scrap_quantity"] is None
        assert queued["rework_count"] == 1

    def test_03_relining_returns_the_lot_to_lined_without_resetting_the_loop(self, api):
        """Re-entry into LINED starts from a strictly different field vector.

        PRD: "On a re-application the batch may legitimately differ from the one
        used before, and the new batch is the one whose `assigned_lot_count` is
        recomputed — this `WELDED → LINED` / `RELINE_QUEUED → LINED` pair is what
        closes the rework cycle `LINED → LINING_REJECTED → RELINE_QUEUED → LINED`."

        Design: Difficulty/non_linear_state_machine/tank_lot_reline_cycle_returns_to_lined
        """
        batch, lot_id, _inspection = _lot_rejected_by_its_own_inspection(api)

        data_of(api.authorize_reline(lot_id, plant_operator_headers()))
        relined = validate_success(
            api.apply_lining(
                lot_id,
                {"glass_lining_batch_id": batch.batch_id},
                plant_operator_headers(),
            )
        )

        assert relined["status"] == "LINED"
        assert relined["rework_count"] == 1
        assert relined["scrapped_quantity"] == 10
        assert relined["wip_quantity"] == 110

    def test_04_the_quantity_ledger_still_balances_after_the_full_lap(self, api):
        """110 in process plus 10 condemned is still the 120 that were planned.

        PRD: "A tank lot's `planned_quantity` always equals the sum of its
        `wip_quantity`, `good_quantity` and `scrapped_quantity`."

        Design: Difficulty/non_linear_state_machine/tank_lot_reline_cycle_returns_to_lined
        """
        batch, lot_id, _inspection = _lot_rejected_by_its_own_inspection(api)

        data_of(api.authorize_reline(lot_id, plant_operator_headers()))
        data_of(
            api.apply_lining(
                lot_id,
                {"glass_lining_batch_id": batch.batch_id},
                plant_operator_headers(),
            )
        )
        lot = validate_success(api.get_tank_lot(lot_id, quality_inspector_headers()))

        assert_tank_lot_ledger(lot)
        assert lot["planned_quantity"] == 120
        assert lot["good_quantity"] == 0

    def test_05_the_single_rejection_is_charged_to_the_batch_exactly_once(self, api):
        """One rejection is below the quarantine threshold, so the batch stays FIRED.

        PRD: "**Hop 3**, caused by hop 2, quarantines that batch if its
        `rejected_lot_count` has now reached 2, moving it `FIRED → QUARANTINED` with
        `quarantine_reason_code` set to `REPEAT_LINING_FAILURE`."

        Design: Difficulty/non_linear_state_machine/tank_lot_reline_cycle_returns_to_lined
        """
        batch, lot_id, _inspection = _lot_rejected_by_its_own_inspection(api)

        data_of(api.authorize_reline(lot_id, plant_operator_headers()))
        data_of(
            api.apply_lining(
                lot_id,
                {"glass_lining_batch_id": batch.batch_id},
                plant_operator_headers(),
            )
        )
        fired = validate_success(
            api.get_lining_batch(batch.batch_id, plant_operator_headers())
        )

        assert fired["rejected_lot_count"] == 1
        assert fired["status"] == "FIRED"
        assert fired["assigned_lot_count"] == 1


class TestProductModelParallelDimensions:
    """Certification posture and channel posture move independently."""

    def test_06_channel_release_leaves_the_certification_posture_alone(self, api):
        """A CERTIFIED model released to channel is still CERTIFIED afterwards.

        PRD: "Every model then evolves along **two independent state dimensions on
        the same row**, and confusing them is the most common mistake in this
        domain."

        Design: Difficulty/non_linear_state_machine/product_model_parallel_dimensions_independent
        """
        certified = make_certified_model(api)

        released = validate_success(
            api.release_model_to_channel(
                certified.model_id, compliance_engineer_headers()
            )
        )

        assert released["release_status"] == "RELEASED"
        assert released["certification_status"] == "CERTIFIED"

    def test_07_suspending_the_certification_leaves_the_channel_posture_alone(self, api):
        """The model is SUSPENDED and RELEASED at the same time.

        PRD: "Suspension leaves `release_status` untouched."

        Design: Difficulty/non_linear_state_machine/product_model_parallel_dimensions_independent
        """
        certified = make_certified_model(api)
        data_of(
            api.release_model_to_channel(
                certified.model_id, compliance_engineer_headers()
            )
        )

        suspended = validate_success(
            api.suspend_model_certification(
                certified.model_id,
                reason_payload(),
                certification_approver_headers(),
            )
        )

        assert suspended["certification_status"] == "SUSPENDED"
        assert suspended["release_status"] == "RELEASED"
        assert suspended["held_unit_count"] == 0

    def test_08_a_suspension_retains_the_four_published_values(self, api):
        """Unlike revocation, suspension does not erase the rating already on labels.

        PRD: "A `CertificationApprover` may suspend the certification of a model
        that is `CERTIFIED`, supplying a `reason_code`; the model moves `CERTIFIED →
        SUSPENDED` and — importantly — the four published values are **retained**,
        because a suspension does not erase the rating that has already gone out on
        labels, it only blocks further labelling."

        Design: Difficulty/non_linear_state_machine/product_model_parallel_dimensions_independent
        """
        certified = make_certified_model(api)
        data_of(
            api.release_model_to_channel(
                certified.model_id, compliance_engineer_headers()
            )
        )

        suspended = validate_success(
            api.suspend_model_certification(
                certified.model_id,
                reason_payload(),
                certification_approver_headers(),
            )
        )
        cert = validate_success(
            api.get_certification(certified.cert_id, compliance_engineer_headers())
        )

        assert suspended["uef_rated"] == approx2(0.59)
        assert suspended["fhr_rated"] == 63
        assert suspended["recovery_rate_rated"] == approx2(41.3)
        assert suspended["label_serial_prefix"] == "GX50-T"
        assert cert["status"] == "APPROVED"
