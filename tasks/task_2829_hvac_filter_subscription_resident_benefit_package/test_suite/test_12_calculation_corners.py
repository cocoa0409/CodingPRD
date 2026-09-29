"""
Calculation corners: inclusive proration, the filtered evidence input set, the
cadence grid snap, per-leg rounding, the capped fee read off a snapshot, the
selection ranking key, and the rollup's input set.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import OPERATOR


class TestProrationAndEvidenceInputs:
    """The activation month, and which readings may be scored."""

    def test_the_activation_day_itself_is_billable(self, api):
        """
        Activating on 5 August bills 27 of August's 31 days, not the 26 an
        exclusive count would give and not the whole month, so the opening
        MONTHLY_FEE row is 3088 and the property owes 5588 in total.

        PRD §3.4: "Take the logical-clock date as the activation date, count the number of days in the calendar month containing it, and count the billable days as that month length minus the activation day-of-month plus one — activating on the eighteenth of a thirty-one-day month gives fourteen billable days."

        Design: Corner/calculations/first_month_fee_prorates_the_activation_month_inclusively
        """
        env = fx.build_base_env(api, activate=False)
        assert a.property_balance(api, env.property_id, OPERATOR) == 0

        validate_success(api.activate_subscription(env.subscription_id, OPERATOR))

        rows, meta = validate_paginated(
            api.list_ledger_entries(env.subscription_id, OPERATOR, {"entry_type": "MONTHLY_FEE"})
        )
        assert meta["total_count"] == 1
        a.assert_cents(rows[0]["amount_cents"], 3088, "monthly fee row")
        assert rows[0]["amount_cents"] != 2974
        assert rows[0]["amount_cents"] != 3546

        assert a.property_balance(api, env.property_id, OPERATOR) == 5588

    def test_readings_taken_before_the_last_delivery_are_filtered_out_of_the_score(
        self, api
    ):
        """
        Four readings sit on the unit but only the two whose window opens at or
        after the delivery instant may be scored: the in-window pair is flat and
        scores 20, where dragging the two pre-delivery windows in would have
        produced 96 and a suspicion — and the excluded rows are filtered, not
        deleted.

        PRD §3.6: "Identify the subscription's most recently delivered shipment — the one with the greatest `delivered_at` among shipments whose `status` is `DELIVERED`, `RETURN_REQUESTED`, `RETURNED` or `UNRETURNED_WRITTEN_OFF`, breaking ties by the greatest `created_at` — and collect every reading on that unit whose `window_start` is at or after that shipment's `delivered_at`, ordered by `window_start` ascending and then by `created_at` ascending."

        Design: Corner/calculations/runtime_readings_before_the_latest_delivery_are_excluded
        """
        env = fx.build_base_env(api)
        fx.deliver_first_shipment(api, env.subscription_id, "2026-08-06T00:00:00Z")

        fx.add_runtime_reading(
            api, env.unit_id, "2026-08-05T00:00:00Z", "2026-08-05T12:00:00Z", 400, 80,
            "PRESSURE_SENSOR",
        )
        fx.add_runtime_reading(
            api, env.unit_id, "2026-08-05T12:00:00Z", "2026-08-06T00:00:00Z", 400, 90,
            "PRESSURE_SENSOR",
        )
        fx.add_runtime_reading(
            api, env.unit_id, "2026-08-06T00:00:00Z", "2026-08-07T00:00:00Z", 240, 100,
            "PRESSURE_SENSOR",
        )
        fx.add_runtime_reading(
            api, env.unit_id, "2026-08-07T00:00:00Z", "2026-08-08T00:00:00Z", 240, 100,
            "PRESSURE_SENSOR",
        )
        fx.set_clock(api, "2026-08-08T00:00:00Z")

        case = validate_success(
            api.create_non_install_evaluation(
                env.subscription_id,
                f.non_install_evaluation_payload("RUNTIME_ANALYTICS", "2026-08-08"),
                OPERATOR,
            ),
            201,
        )
        assert case["evidence_score"] == 20
        assert case["evidence_score"] != 96
        assert case["status"] == "CLOSED_UNSUBSTANTIATED"
        assert case["suspect_threshold"] == 40
        assert case["confirm_threshold"] == 60

        subscription = fx.read_subscription(api, env.subscription_id)
        assert subscription["installation_posture"] == "COMPLIANT"
        assert subscription["latest_evidence_score"] == 20

        _readings, reading_meta = validate_paginated(
            api.list_runtime_readings(env.unit_id, OPERATOR)
        )
        assert reading_meta["total_count"] == 4


class TestCadenceGridAndSelectionRanking:
    """Two households on identical units, diverging only through the derivation."""

    def _two_units_two_residents(self, api, resident_b_overrides, sku_setup=None):
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        skus = sku_setup(api) if sku_setup else [fx.create_sku(api)]
        prop = fx.create_property(api)
        unit_a = fx.create_unit(api, prop["id"], unit_label="A-101")
        fx.activate_property(api, prop["id"])
        unit_b = fx.create_unit(api, prop["id"], unit_label="A-102")
        resident_a = fx.create_resident(api)
        resident_b = fx.create_resident(api, **resident_b_overrides)
        fx.set_clock(api, "2026-08-05T00:00:00Z")
        sub_a = fx.create_subscription(api, resident_a["id"], unit_a["id"])
        sub_b = fx.create_subscription(api, resident_b["id"], unit_b["id"])
        return skus, sub_a, sub_b

    def test_a_household_of_four_lands_on_the_lower_grid_slot(self, api):
        """
        One load point shortens 75 days to 65, and the grid snap takes it down to
        60 — never leaving 65 and never rounding back up to 75 — and the faster
        cadence raises both usage-driven fee components, giving 3782 against 3546.

        PRD §3.3: "Finally snap the clamped value **down** onto the fifteen-day logistics grid — take the largest multiple of fifteen that does not exceed it, discarding any remainder, never rounding to nearest and never rounding up — and re-apply the thirty-day floor to that snapped value."

        Design: Corner/calculations/household_size_four_snaps_cadence_to_the_sixty_day_grid_slot
        """
        skus, sub_a, sub_b = self._two_units_two_residents(
            api,
            {
                "full_name": "Ben Ortiz",
                "email": "ben.ortiz@example.com",
                "household_size": 4,
            },
        )

        assert sub_a["ship_cadence_days"] == 75
        assert sub_b["ship_cadence_days"] == 60
        assert sub_b["ship_cadence_days"] != 65
        assert sub_b["ship_cadence_days"] != 75
        a.assert_cents(sub_a["monthly_fee_cents"], 3546, "monthly_fee_cents")
        a.assert_cents(sub_b["monthly_fee_cents"], 3782, "monthly_fee_cents")
        for subscription in (sub_a, sub_b):
            assert subscription["filters_per_shipment"] == 2
            assert subscription["assigned_sku_id"] == skus[0]["id"]

    def test_a_dearer_lower_merv_pack_beats_a_cheaper_higher_merv_pack(self, api):
        """
        With a MERV 11 pack at 680 registered first and a MERV 8 pack at 900
        registered second, the ordinary household is mapped onto the dearer MERV 8
        because filtration level is the primary key; the allergy household's floor
        of 11 removes that pack from the pool entirely and flips the winner.

        PRD §3.3: "Candidates are then ranked cheapest-adequate-filtration-first: the lowest `merv_rating` wins, ties among equal ratings go to the lowest `unit_cost_cents`, and any remaining tie goes to the entry with the earliest `created_at`."

        Design: Corner/calculations/sku_selection_prefers_lower_merv_over_lower_price
        """

        def two_skus(inner_api):
            merv_11 = fx.create_sku(
                inner_api,
                sku_code="SKU-16251-M11",
                merv_rating=11,
                unit_cost_cents=680,
            )
            merv_8 = fx.create_sku(
                inner_api,
                sku_code="SKU-16251-M8",
                merv_rating=8,
                unit_cost_cents=900,
            )
            return [merv_11, merv_8]

        skus, sub_a, sub_c = self._two_units_two_residents(
            api,
            {
                "full_name": "Cara Nunez",
                "email": "cara.nunez@example.com",
                "household_size": 3,
                "allergy_flag": True,
            },
            sku_setup=two_skus,
        )
        merv_11, merv_8 = skus

        assert sub_a["assigned_sku_id"] == merv_8["id"]
        assert sub_a["assigned_sku_id"] != merv_11["id"]
        assert sub_a["ship_cadence_days"] == 75
        a.assert_cents(sub_a["monthly_fee_cents"], 3787, "monthly_fee_cents")

        assert sub_c["assigned_sku_id"] == merv_11["id"]
        assert sub_c["ship_cadence_days"] == 60

        assert sub_a["filters_per_shipment"] == 2
        assert sub_c["filters_per_shipment"] == 2


class TestMoneyBearingCorners:
    """Per-leg rounding, the capped fee on a snapshot, and the rollup input set."""

    def test_each_transfer_leg_is_rounded_before_the_subtraction(self, api):
        """
        With a seven-day remainder in a thirty-one-day month the two legs round to
        801 and 716, so the net is -85; computing the difference on the unrounded
        legs would have produced -84, and the ledger books the net once.

        PRD §3.8: "Both roundings are independent and both happen before the subtraction — the difference is never computed on unrounded values, and the two legs are never posted to the ledger separately."

        Design: Corner/calculations/transfer_proration_rounds_each_leg_before_subtracting
        """
        env = fx.build_base_env(api)
        unit_b = fx.create_unit(
            api,
            env.property_id,
            unit_label="B-201",
            hvac_system_type="TWO_STAGE",
            filter_slot_count=1,
            return_grille_count=1,
            nominal_size_code="16x25x1",
        )
        assert a.property_balance(api, env.property_id, OPERATOR) == 5588
        fx.set_clock(api, "2026-08-25T00:00:00Z")

        transfer = validate_success(
            api.create_subscription_transfer(
                f.transfer_payload(env.subscription_id, unit_b["id"], "2026-08-25", 2),
                OPERATOR,
            ),
            201,
        )
        validate_success(api.remap_transfer_sku(transfer["id"], OPERATOR))
        completed = validate_success(api.complete_transfer(transfer["id"], OPERATOR))

        a.assert_cents(completed["proration_credit_cents"], 801, "proration_credit_cents")
        a.assert_cents(completed["proration_charge_cents"], 716, "proration_charge_cents")
        a.assert_cents(completed["net_adjustment_cents"], -85, "net_adjustment_cents")
        assert completed["net_adjustment_cents"] != -84

        successor = fx.read_subscription(api, completed["successor_subscription_id"])
        a.assert_cents(successor["monthly_fee_cents"], 3173, "monthly_fee_cents")
        assert successor["ship_cadence_days"] == 75
        assert successor["filters_per_shipment"] == 1

        successor_ledger = fx.read_ledger(api, successor["id"])
        assert len(successor_ledger) == 1
        a.assert_ledger_row(
            successor_ledger[0],
            "TRANSFER_ADJUSTMENT",
            -85,
            "PROPERTY_MANAGER",
            transfer["id"],
        )
        assert a.property_balance(api, env.property_id, OPERATOR) == 5503

    def test_the_unreturned_fee_reads_each_shipment_own_snapshot_and_clamps_at_the_cap(
        self, api
    ):
        """
        Two write-offs on one subscription straddle the per-shipment cap: the first
        shipment keeps the 1200-cent SKU it was created with and charges 2400 even
        though the subscription has since been remapped onto the 1400-cent SKU,
        while the second shipment's 2800 is clamped down to 2500.

        PRD §3.5: "Note that the fee reads the shipment's snapshotted `sku_id`, not the subscription's current `assigned_sku_id`."

        Design: Corner/calculations/unreturned_fee_clamps_at_the_cap_and_reads_the_shipment_sku_snapshot
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        sku_a = fx.create_sku(
            api, sku_code="SKU-16251-M8", size_code="16x25x1", unit_cost_cents=1200,
            ship_weight_oz=14,
        )
        sku_b = fx.create_sku(
            api, sku_code="SKU-20251-M8", size_code="20x25x1", unit_cost_cents=1400,
            ship_weight_oz=18,
        )
        prop = fx.create_property(api)
        unit = fx.create_unit(api, prop["id"])
        fx.activate_property(api, prop["id"])
        resident = fx.create_resident(api)
        fx.set_clock(api, "2026-08-05T00:00:00Z")
        subscription = fx.create_subscription(api, resident["id"], unit["id"])
        assert subscription["assigned_sku_id"] == sku_a["id"]
        a.assert_cents(subscription["monthly_fee_cents"], 4115, "monthly_fee_cents")
        fx.activate_subscription(api, subscription["id"])
        assert a.property_balance(api, prop["id"], OPERATOR) == 6084

        shipment_one = fx.first_shipment(api, subscription["id"])
        assert shipment_one["sku_id"] == sku_a["id"]
        validate_success(
            api.ship_shipment(shipment_one["id"], f.ship_payload("TRK-A-0001"), OPERATOR)
        )
        validate_success(
            api.deliver_shipment(
                shipment_one["id"], f.deliver_payload("2026-08-06T00:00:00Z"), OPERATOR
            )
        )
        fx.request_return_on(api, shipment_one["id"])

        occupied_unit = validate_success(api.get_unit(unit["id"], OPERATOR))
        # The PRD lists no FilterSizeCapture record type (§2.4 enumerates every
        # persisted type), so this call's 200-vs-201 status is not pinned; any 2xx
        # is accepted and the remap it causes is asserted immediately below.
        get_success_data(
            api.capture_filter_size(
                unit["id"],
                f.size_capture_payload("20x25x1", occupied_unit["version"]),
                OPERATOR,
            )
        )
        remapped = fx.read_subscription(api, subscription["id"])
        assert remapped["assigned_sku_id"] == sku_b["id"]

        shipment_two = validate_success(
            api.create_shipment(subscription["id"], f.shipment_payload("2026-10-19"), OPERATOR),
            201,
        )
        assert shipment_two["sku_id"] == sku_b["id"]
        validate_success(
            api.ship_shipment(shipment_two["id"], f.ship_payload("TRK-A-0002"), OPERATOR)
        )
        validate_success(
            api.deliver_shipment(
                shipment_two["id"], f.deliver_payload("2026-08-07T00:00:00Z"), OPERATOR
            )
        )
        fx.request_return_on(api, shipment_two["id"])

        first_write_off = validate_success(api.write_off_shipment(shipment_one["id"], OPERATOR))
        assert first_write_off["sku_id"] == sku_a["id"]
        a.assert_cents(first_write_off["unreturned_fee_cents"], 2400, "unreturned_fee_cents")
        assert first_write_off["unreturned_fee_cents"] != 2500
        assert first_write_off["unreturned_fee_cents"] != 2800

        second_write_off = validate_success(api.write_off_shipment(shipment_two["id"], OPERATOR))
        assert second_write_off["sku_id"] == sku_b["id"]
        a.assert_cents(second_write_off["unreturned_fee_cents"], 2500, "unreturned_fee_cents")

        fees, fee_meta = validate_paginated(
            api.list_ledger_entries(
                subscription["id"], OPERATOR, {"entry_type": "UNRETURNED_SHIPMENT_FEE"}
            )
        )
        assert fee_meta["total_count"] == 2
        by_ref = {row["source_ref_id"]: row for row in fees}
        a.assert_ledger_row(
            by_ref[shipment_one["id"]], "UNRETURNED_SHIPMENT_FEE", 2400, "PROPERTY_MANAGER"
        )
        a.assert_ledger_row(
            by_ref[shipment_two["id"]], "UNRETURNED_SHIPMENT_FEE", 2500, "PROPERTY_MANAGER"
        )
        assert a.property_balance(api, prop["id"], OPERATOR) == 10984

    def test_the_property_balance_sums_only_the_manager_billed_rows(self, api):
        """
        A resident-billed subscription at a manager-billed property loses the
        insurance rider, prices at 2246 and posts both of its opening rows as
        RESIDENT — so the property's balance stays at the manager-billed
        subscription's 5588 rather than climbing to 10044.

        PRD §2.11: "Rows whose `billed_party` is `RESIDENT` never enter a property's balance."

        Design: Corner/calculations/property_rollup_ignores_resident_billed_ledger_entries
        """
        env = fx.build_base_env(api)
        assert a.property_balance(api, env.property_id, OPERATOR) == 5588

        unit_b = fx.create_unit(api, env.property_id, unit_label="A-102")
        resident_b = fx.create_resident(
            api, full_name="Ben Ortiz", email="ben.ortiz@example.com", household_size=3
        )
        subscription_b = fx.create_subscription(
            api, resident_b["id"], unit_b["id"], billing_party="RESIDENT"
        )
        assert subscription_b["entitled_benefit_codes"] == [
            "AIR_QUALITY_GUARANTEE",
            "CREDIT_REPORTING",
            "DAMAGE_WAIVER",
        ]
        a.assert_cents(subscription_b["monthly_fee_cents"], 2246, "monthly_fee_cents")

        fx.activate_subscription(api, subscription_b["id"])

        rows, meta = validate_paginated(api.list_ledger_entries(subscription_b["id"], OPERATOR))
        assert meta["total_count"] == 2
        by_type = {row["entry_type"]: row for row in rows}
        a.assert_ledger_row(
            by_type["ENROLLMENT_FEE"], "ENROLLMENT_FEE", 2500, "RESIDENT", subscription_b["id"]
        )
        a.assert_ledger_row(
            by_type["MONTHLY_FEE"], "MONTHLY_FEE", 1956, "RESIDENT", subscription_b["id"]
        )

        balance = a.property_balance(api, env.property_id, OPERATOR)
        assert balance == 5588
        assert balance != 10044
