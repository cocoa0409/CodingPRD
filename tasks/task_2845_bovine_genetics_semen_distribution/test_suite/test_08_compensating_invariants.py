"""Two conserved quantities and the compensating actions that restore them."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_buckets,
    assert_dose_ledger_conserved,
    assert_null_fields,
    factories,
    fixtures as fx,
    validate_error,
)

ANCHOR_PROOF = {
    "milk_kg": 900,
    "fat_kg": 40,
    "protein_kg": 30,
    "somatic_cell_score": 2.85,
    "fertility_pct": 1.5,
    "longevity_months": 2.0,
    "reliability_pct": 75,
    "progeny_daughter_count": 120,
    "effective_at": "2026-07-01T00:00:00Z",
}

SON_PROOF = {
    "milk_kg": 1100,
    "fat_kg": 45,
    "protein_kg": 36,
    "somatic_cell_score": 2.90,
    "fertility_pct": 2.0,
    "longevity_months": 3.0,
    "reliability_pct": 68,
    "progeny_daughter_count": 50,
    "effective_at": "2026-09-01T00:00:00Z",
}


class TestDoseLedgerConservedAcrossTheConsignmentRoundTrip:
    """straw_count is the sum of the five buckets after every hop."""

    @staticmethod
    def _released_three_hundred_straw_lot(api):
        context = fx.released_lot(
            api,
            facility_overrides={
                "code": "F-IA-19",
                "housing_capacity": 2,
                "bench_capacity": 1,
                "approved_export_countries": ["CA"],
            },
            registration_code="REG-B",
            product_line="CONVENTIONAL",
            straw_count=300,
            processing_cost_cents=375000,
        )
        context.update(
            fx.distributor_with_tank(
                api,
                distributor_overrides={"name": "D-HOTEL", "credit_limit_cents": 100000000},
                tank_overrides={"serial": "TK-H", "capacity_straws": 500},
            )
        )
        return context

    def test_every_hop_moves_doses_between_buckets_and_the_return_restores_them(self, api):
        """The invariant is exact — after an approval followed by a return of the
        same consignment, the lot's `doses_available` is precisely what it was
        immediately before the approval, every other bucket is unchanged, and
        `straw_count` is untouched.

        Design: Difficulty/compensating_invariant/dose_ledger_conserved_across_approve_dispatch_receive_return
        """
        context = self._released_three_hundred_straw_lot(api)
        lot_id = context["lot"]["id"]
        distributor_id = context["distributor"]["id"]

        opening = fx.read_lot(api, lot_id)
        assert opening["straw_count"] == 300
        assert_buckets(opening, 300, 0, 0, 0, 0)
        assert_dose_ledger_conserved(opening)
        assert fx.plant_value(api) == 375000

        transfer = fx.request_consignment(
            api, lot_id, distributor_id, context["tank"]["id"], doses=40, unit_price_cents=4000
        )
        assert_buckets(fx.read_lot(api, lot_id), 300, 0, 0, 0, 0)

        fx.approve_transfer(api, transfer["id"])
        after_approve = fx.read_lot(api, lot_id)
        assert_buckets(after_approve, 260, 40, 0, 0, 0)
        assert_dose_ledger_conserved(after_approve)
        assert fx.plant_value(api) == 375000

        fx.dispatch_transfer(api, transfer["id"])
        after_dispatch = fx.read_lot(api, lot_id)
        assert_buckets(after_dispatch, 260, 40, 0, 0, 0)
        assert fx.plant_value(api) == 375000

        received = fx.receive_transfer(api, transfer["id"], distributor_id)
        after_receive = fx.read_lot(api, lot_id)
        assert_buckets(after_receive, 260, 0, 40, 0, 0)
        assert_dose_ledger_conserved(after_receive)
        assert received["carried_value_cents"] == 50000
        assert fx.read_distributor(api, distributor_id)["consignment_value_cents"] == 50000
        assert fx.plant_value(api) == 375000

        returned = fx.return_transfer(
            api, transfer["id"], distributor_id, return_reason="TANK_RELOCATION"
        )
        assert returned["status"] == "RETURNED"
        assert returned["doses_returned"] == 40
        assert returned["carried_value_cents"] == 0
        assert_null_fields(
            returned,
            (
                "gross_cents",
                "service_fee_cents",
                "rebate_cents",
                "settlement_total_cents",
            ),
        )

        restored = fx.read_lot(api, lot_id)
        assert_buckets(restored, 300, 0, 0, 0, 0)
        assert_dose_ledger_conserved(restored)
        assert restored["straw_count"] == 300
        assert fx.plant_value(api) == 375000

        partner = fx.read_distributor(api, distributor_id)
        assert partner["consignment_value_cents"] == 0
        assert partner["outstanding_balance_cents"] == 0
        assert partner["cumulative_doses_used"] == 0

    def test_a_returned_consignment_accepts_no_further_movement(self, api):
        """`REJECTED`, `RECONCILED` and `RETURNED` are all terminal for a
        consignment; any transition attempted from the wrong source state — ...
        or reporting usage or returning outside `RECEIVED` — reports
        `ERR_TRANSFER_STATE`.

        Design: Difficulty/compensating_invariant/dose_ledger_conserved_across_approve_dispatch_receive_return
        """
        context = self._released_three_hundred_straw_lot(api)
        distributor_id = context["distributor"]["id"]
        walked = fx.received_consignment(
            api, context, doses=40, unit_price_cents=4000
        )
        transfer_id = walked["transfer"]["id"]
        fx.return_transfer(api, transfer_id, distributor_id, return_reason="TANK_RELOCATION")

        validate_error(
            api.return_consignment_transfer(
                transfer_id,
                factories.transfer_return_payload(),
                context["distributor_headers"],
            ),
            ApiErrorId.ERR_TRANSFER_STATE.value,
            409,
        )
        validate_error(
            api.report_consignment_usage(
                transfer_id,
                factories.report_usage_payload(10),
                context["distributor_headers"],
            ),
            ApiErrorId.ERR_TRANSFER_STATE.value,
            409,
        )

        assert_buckets(fx.read_lot(api, context["lot"]["id"]), 300, 0, 0, 0, 0)


class TestInventoryCentsConservedAcrossPublishAndRollback:
    """Publication moves the plant value; rollback puts it back to the cent."""

    @staticmethod
    def _received_consignment_under_a_draft_proof(api):
        anchor = fx.register_sire(
            api,
            registration_code="REG-A",
            birth_date="2020-03-01",
            acquisition_cost_cents=0,
        )
        fx.published_proof(api, anchor["id"], **ANCHOR_PROOF)

        context = fx.received_consignment(
            api,
            facility_overrides={
                "code": "F-IA-20",
                "housing_capacity": 2,
                "bench_capacity": 1,
                "approved_export_countries": ["CA"],
            },
            registration_code="REG-C",
            sire_overrides={"birth_date": "2023-05-01", "sire_id": anchor["id"]},
            product_line="CONVENTIONAL",
            straw_count=200,
            processing_cost_cents=250000,
            distributor_overrides={"name": "D-INDIA", "credit_limit_cents": 100000000},
            tank_overrides={"serial": "TK-I", "capacity_straws": 500},
            doses=150,
            unit_price_cents=4000,
        )
        context["evaluation"] = fx.file_evaluation(api, context["sire"]["id"], **SON_PROOF)
        assert context["evaluation"]["status"] == "DRAFT"
        assert context["evaluation"]["composite_index"] == pytest.approx(49.95, abs=0.01)
        assert context["evaluation"]["revaluation_delta_cents"] == 0
        return context

    def test_the_rollback_restores_the_plant_value_to_the_cent(self, api):
        """The invariant that binds the pair is exact: after a rollback the plant
        inventory value returns to precisely the figure it carried before the
        corresponding publication, to the cent.

        Design: Difficulty/compensating_invariant/inventory_cents_conserved_across_publish_and_rollback
        """
        context = self._received_consignment_under_a_draft_proof(api)
        lot_id = context["lot"]["id"]
        transfer_id = context["transfer"]["id"]
        distributor_id = context["distributor"]["id"]

        before = fx.read_lot(api, lot_id)
        assert before["unit_book_value_cents"] == 1250
        assert before["valuation_basis"] == "STANDARD_COST"
        assert before["pre_revaluation_unit_value_cents"] is None
        assert_buckets(before, 50, 0, 150, 0, 0)
        assert fx.plant_value(api) == 250000
        assert fx.read_transfer(api, transfer_id)["carried_value_cents"] == 187500
        assert fx.read_distributor(api, distributor_id)["consignment_value_cents"] == 187500

        published = fx.publish_evaluation(api, context["evaluation"]["id"])
        assert published["revaluation_delta_cents"] == 199600
        revalued = fx.read_lot(api, lot_id)
        assert revalued["unit_book_value_cents"] == 2248
        assert revalued["valuation_basis"] == "MARKET_REVALUED"
        assert revalued["pre_revaluation_unit_value_cents"] == 1250
        assert fx.read_transfer(api, transfer_id)["carried_value_cents"] == 337200
        assert fx.read_distributor(api, distributor_id)["consignment_value_cents"] == 337200
        assert fx.plant_value(api) == 449600

        rolled_back = fx.rollback_evaluation(api, context["evaluation"]["id"])
        assert rolled_back["status"] == "ROLLED_BACK"

        restored = fx.read_lot(api, lot_id)
        assert restored["unit_book_value_cents"] == 1250
        assert restored["valuation_basis"] == "STANDARD_COST"
        assert restored["pre_revaluation_unit_value_cents"] is None
        assert_buckets(restored, 50, 0, 150, 0, 0)
        assert fx.read_transfer(api, transfer_id)["carried_value_cents"] == 187500
        assert fx.read_distributor(api, distributor_id)["consignment_value_cents"] == 187500
        assert fx.plant_value(api) == 250000

        sire = fx.read_sire(api, context["sire"]["id"])
        assert sire["published_composite_index"] == pytest.approx(0.00, abs=0.01)
        assert sire["published_production_index"] == pytest.approx(0.00, abs=0.01)
        assert sire["published_health_index"] == pytest.approx(0.00, abs=0.01)
        assert sire["published_evaluation_effective_at"] is None
        assert sire["progeny_daughter_count"] == 0

    def test_a_rolled_back_proof_can_be_neither_rolled_back_nor_published_again(self, api):
        """A director withdraws a `PUBLISHED` proof with a `rollback_reason`; the
        row becomes `ROLLED_BACK`, which is terminal, and rolling back anything not
        currently `PUBLISHED` reports `ERR_EVALUATION_STATE`.

        Design: Difficulty/compensating_invariant/inventory_cents_conserved_across_publish_and_rollback
        """
        context = self._received_consignment_under_a_draft_proof(api)
        evaluation_id = context["evaluation"]["id"]
        fx.publish_evaluation(api, evaluation_id)
        fx.rollback_evaluation(api, evaluation_id)

        validate_error(
            api.rollback_genomic_evaluation(
                evaluation_id, factories.rollback_payload(), fx.DIRECTOR
            ),
            ApiErrorId.ERR_EVALUATION_STATE.value,
            409,
        )
        validate_error(
            api.publish_genomic_evaluation(
                evaluation_id, factories.publish_payload(), fx.DIRECTOR
            ),
            ApiErrorId.ERR_EVALUATION_STATE.value,
            409,
        )

        assert fx.plant_value(api) == 250000
        assert fx.read_lot(api, context["lot"]["id"])["unit_book_value_cents"] == 1250
