"""Compensating actions that must restore a conserved quantity exactly.

One reverses a physical tank count and the counters the rejection incremented;
the other reverses money without rewinding the lifetime accrual. In both cases
the record of what happened is deliberately left standing.
"""

from test_helpers import (
    approx2,
    assert_reserve_ledger,
    assert_tank_lot_ledger,
    compliance_engineer_headers,
    data_of,
    failing_holiday_payload,
    lot_inspections,
    make_fired_batch,
    make_full_plant,
    make_lined_tank_lot,
    make_model,
    make_paid_claim,
    plant_operator_headers,
    quality_inspector_headers,
    reason_payload,
    tank_lot_version,
    validate_success,
    warranty_analyst_headers,
    fixtures as x,
)


def _lot_rejected_by_its_own_direct_inspection(api):
    """A 120-tank lot rejected by its own failing holiday count.

    Ten tanks are condemned, so the lot sits at 110 in process with one rework on
    the clock and the shared batch one rejection short of quarantine. The version
    read before the inspection is returned so the compensation can be shown to be
    a forward write rather than a rollback.
    """
    model_id = make_model(api)["id"]
    batch = make_fired_batch(api)
    lot_id = make_lined_tank_lot(api, model_id, batch.batch_id)
    version_before = tank_lot_version(api, lot_id)
    inspection = data_of(
        api.create_lining_inspection(
            failing_holiday_payload(lot_id, version_before),
            quality_inspector_headers(),
        )
    )
    return batch, lot_id, inspection, version_before


def _reverse_the_rejection(api, lot_id):
    """Reverse the rejection as the quality inspector who is entitled to."""
    return validate_success(
        api.rework_reversal(
            lot_id,
            reason_payload(reason_code="GAUGE_MISREAD"),
            quality_inspector_headers(),
        )
    )


class TestReworkReversalRestoresTheTankLedger:
    """The inverse of both rejection hops, leaving the failing record standing."""

    def test_01_the_reversal_returns_the_condemned_tanks_to_work_in_process(self, api):
        """Ten tanks move back out of scrap and the rework counter is given back.

        PRD: "The reversal is the exact inverse of hops 1 and 2: `last_scrap_quantity`
        is added back to `wip_quantity` and subtracted from `scrapped_quantity`,
        `last_scrap_quantity` is then set to null, `rework_count` is decreased by 1, and
        the batch's `rejected_lot_count` is decreased by 1."

        Design: Difficulty/compensating_invariant/rework_reversal_restores_tank_count_ledger
        """
        _batch, lot_id, _inspection, _version = _lot_rejected_by_its_own_direct_inspection(api)

        reversed_lot = _reverse_the_rejection(api, lot_id)

        assert reversed_lot["status"] == "LINED"
        assert reversed_lot["wip_quantity"] == 120
        assert reversed_lot["scrapped_quantity"] == 0
        assert reversed_lot["good_quantity"] == 0
        assert reversed_lot["last_scrap_quantity"] is None
        assert reversed_lot["rework_count"] == 0

    def test_02_the_physical_count_invariant_holds_after_the_compensation(self, api):
        """Every planned tank is accounted for again as work in process.

        PRD: "A tank lot's `planned_quantity` always equals the sum of its
        `wip_quantity`, `good_quantity` and `scrapped_quantity`."

        Design: Difficulty/compensating_invariant/rework_reversal_restores_tank_count_ledger
        """
        _batch, lot_id, _inspection, _version = _lot_rejected_by_its_own_direct_inspection(api)

        _reverse_the_rejection(api, lot_id)
        lot = validate_success(api.get_tank_lot(lot_id, quality_inspector_headers()))

        assert_tank_lot_ledger(lot)
        assert lot["planned_quantity"] == 120

    def test_03_the_batch_rejection_counter_is_disarmed_as_well_as_the_lot(self, api):
        """Leaving the batch at one rejection would silently arm the quarantine.

        PRD: "**Hop 3**, caused by hop 2, quarantines that batch if its
        `rejected_lot_count` has now reached 2, moving it `FIRED → QUARANTINED` with
        `quarantine_reason_code` set to `REPEAT_LINING_FAILURE`."

        Design: Difficulty/compensating_invariant/rework_reversal_restores_tank_count_ledger
        """
        batch, lot_id, _inspection, _version = _lot_rejected_by_its_own_direct_inspection(api)

        _reverse_the_rejection(api, lot_id)
        fired = validate_success(
            api.get_lining_batch(batch.batch_id, plant_operator_headers())
        )

        assert fired["rejected_lot_count"] == 0
        assert fired["status"] == "FIRED"

    def test_04_the_failing_inspection_record_survives_the_compensation(self, api):
        """Quantities are compensated; the quality history is not rewritten.

        PRD: "The failing inspection record itself keeps `record_status` `CURRENT`
        even though the lot has returned to `LINED`, and `version` is incremented on
        both the lot and the batch."

        Design: Difficulty/compensating_invariant/rework_reversal_restores_tank_count_ledger
        """
        _batch, lot_id, _inspection, _version = _lot_rejected_by_its_own_direct_inspection(api)

        _reverse_the_rejection(api, lot_id)
        rows = lot_inspections(api, lot_id)

        assert len(rows) == 1
        assert rows[0]["record_status"] == "CURRENT"
        assert rows[0]["result"] == "FAIL"

    def test_05_the_compensation_advances_the_version_rather_than_rewinding_it(self, api):
        """The restored field vector is reached by a forward write.

        PRD: "The failing inspection record itself keeps `record_status` `CURRENT`
        even though the lot has returned to `LINED`, and `version` is incremented on
        both the lot and the batch."

        Design: Difficulty/compensating_invariant/rework_reversal_restores_tank_count_ledger
        """
        _batch, lot_id, _inspection, version_before = _lot_rejected_by_its_own_direct_inspection(api)

        reversed_lot = _reverse_the_rejection(api, lot_id)

        assert reversed_lot["version"] > version_before


def _paid_thermostat_claim_against_a_two_unit_population(api):
    """Two gas units shipped, then one thermostat claim validated and paid.

    Both units accrue 42,000 cents on shipment, so the model's lifetime accrual is
    84,000 cents. Five service months keeps the thermostat mode inside its short
    warranty, and full coverage puts the payout at 4,200 + 12,525 + 3,325 cents.
    """
    plant = make_full_plant(api)
    first = x.ship_unit(api, plant, hardness_gpg=8.0)
    x.ship_unit(api, plant, hardness_gpg=2.0)
    x.set_clock(api, "2027-02-01T00:00:00Z")
    claim = make_paid_claim(api, first, failure_mode="THERMOSTAT")
    return plant, first, claim


def _reverse_the_payment(api, claim_id):
    """Credit the reserve back, recording why the payment was withdrawn."""
    return validate_success(
        api.reverse_claim_payment(
            claim_id,
            reason_payload(reason_code="DUPLICATE_PAYMENT"),
            warranty_analyst_headers(),
        )
    )


class TestPaymentReversalRestoresTheWarrantyReserve:
    """Money is credited back without the accrual being rewound."""

    def test_06_the_paid_claim_returns_to_validated_keeping_its_monetary_intent(
        self, api
    ):
        """The payout and coverage survive so the same amount can be re-paid.

        PRD: "Reversing a payment is the compensating action, performed by a
        `WarrantyAnalyst` on a claim in `status` `PAID` with a `reason_code`, and it
        returns the claim `PAID → VALIDATED` so it can be corrected and paid again."

        Design: Difficulty/compensating_invariant/payment_reversal_restores_warranty_reserve_ledger
        """
        _plant, _unit, claim = _paid_thermostat_claim_against_a_two_unit_population(api)

        reversed_claim = _reverse_the_payment(api, claim["id"])

        assert reversed_claim["status"] == "VALIDATED"
        assert reversed_claim["paid_at"] is None
        assert reversed_claim["reason_code"] == "DUPLICATE_PAYMENT"
        assert reversed_claim["approved_payout_cents"] == 20050
        assert reversed_claim["coverage_pct"] == approx2(1.00)
        assert reversed_claim["months_in_service_at_report"] == 5

    def test_07_the_credit_back_moves_paid_and_balance_but_not_the_accrual(self, api):
        """Balance rises by exactly the amount paid falls, and accrual is frozen.

        PRD: "The reversal clears `paid_at` back to null, records the `reason_code`,
        adds the payout back to the model's `warranty_reserve_balance_cents` and
        subtracts it from `warranty_paid_cents`, and again leaves
        `warranty_reserve_accrued_cents` untouched."

        Design: Difficulty/compensating_invariant/payment_reversal_restores_warranty_reserve_ledger
        """
        plant, _unit, claim = _paid_thermostat_claim_against_a_two_unit_population(api)

        before = validate_success(
            api.get_product_model(plant.model_id, compliance_engineer_headers())
        )
        _reverse_the_payment(api, claim["id"])
        after = validate_success(
            api.get_product_model(plant.model_id, compliance_engineer_headers())
        )

        assert before["warranty_paid_cents"] == 20050
        assert before["warranty_reserve_balance_cents"] == 63950
        assert after["warranty_paid_cents"] == 0
        assert after["warranty_reserve_balance_cents"] == 84000
        assert after["warranty_reserve_accrued_cents"] == 84000

    def test_08_the_money_invariant_holds_on_both_sides_of_the_reversal(self, api):
        """Balance equals accrual less payments before and after the compensation.

        PRD: "Because the accrual figure is never rewound,
        `warranty_reserve_balance_cents` always equals `warranty_reserve_accrued_cents`
        minus `warranty_paid_cents` no matter how many payments and reversals a model
        has seen."

        Design: Difficulty/compensating_invariant/payment_reversal_restores_warranty_reserve_ledger
        """
        plant, _unit, claim = _paid_thermostat_claim_against_a_two_unit_population(api)

        assert_reserve_ledger(
            validate_success(
                api.get_product_model(plant.model_id, compliance_engineer_headers())
            )
        )
        _reverse_the_payment(api, claim["id"])

        assert_reserve_ledger(
            validate_success(
                api.get_product_model(plant.model_id, compliance_engineer_headers())
            )
        )

    def test_09_a_reversal_is_not_a_de_shipment(self, api):
        """The unit is still in the field, still ageing, still accrued for.

        PRD: "A subsequent hold never claws the accrual back, and a unit that was
        scrapped before shipping never accrued at all."

        Design: Difficulty/compensating_invariant/payment_reversal_restores_warranty_reserve_ledger
        """
        _plant, unit_id, claim = _paid_thermostat_claim_against_a_two_unit_population(api)

        _reverse_the_payment(api, claim["id"])
        unit = validate_success(api.get_heater_unit(unit_id, plant_operator_headers()))

        assert unit["build_status"] == "SHIPPED"
        assert unit["months_in_service"] == 5

    def test_10_the_restored_reserve_can_fund_the_same_payout_again(self, api):
        """Paying the corrected claim a second time draws the same amount down.

        PRD: "On payment the claim records `paid_at` as the logical-clock instant,
        and the model's `warranty_reserve_balance_cents` is reduced by the payout while
        `warranty_paid_cents` is increased by it; `version` is incremented on both claim
        and model."

        Design: Difficulty/compensating_invariant/payment_reversal_restores_warranty_reserve_ledger
        """
        plant, _unit, claim = _paid_thermostat_claim_against_a_two_unit_population(api)

        _reverse_the_payment(api, claim["id"])
        repaid = validate_success(
            api.pay_claim(claim["id"], warranty_analyst_headers())
        )
        model = validate_success(
            api.get_product_model(plant.model_id, compliance_engineer_headers())
        )

        assert repaid["status"] == "PAID"
        assert repaid["approved_payout_cents"] == 20050
        assert model["warranty_paid_cents"] == 20050
        assert model["warranty_reserve_balance_cents"] == 63950
        assert model["warranty_reserve_accrued_cents"] == 84000
