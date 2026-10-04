"""Pricing, flagging and turnaround arithmetic.

Every expected value here is computed from the numbers the PRD's own workflow
prose pins: the volume-tier rate table, the rush-tier ladder and its escalation
rule, the per-line late-credit rate, and the read-time flag ladder.
"""
import pytest

from test_helpers import (
    book_run,
    refresh_order,
    release_order,
    result_line,
    set_clock,
    setup_active_client,
    setup_specimen_and_order,
    start_testing,
    order_line,
    validate_success,
)


class TestLineFlagLadder:

    def test_result_flag_resolves_through_the_pinned_five_step_ladder(self, api, medtech_headers):
        """PRD 3.7: "A line's `result_flag` is `CRITICAL_LOW` when
        `critical_value_low` is non-null and the value falls strictly below it;
        otherwise `CRITICAL_HIGH` when `critical_value_high` is non-null and the
        value falls strictly above it; otherwise `LOW` when `reference_low` is
        non-null and the value falls strictly below it; otherwise `HIGH` when
        `reference_high` is non-null and the value falls strictly above it;
        otherwise `NORMAL`."
        PRD 3.7: "Flagging is derived on read rather than stored, and the
        derivation order is pinned because a value can sit outside more than
        one limit at once."

        Design: Corner/entities/result_flag_is_computed_from_catalogue_limits_on_read_and_never_stored
        """
        scenario = setup_active_client(
            entry_overrides={
                "stability_hours_ambient": 72,
                "reference_low": 10, "reference_high": 300,
                "critical_value_low": 5, "critical_value_high": 400,
            },
            clock="2026-09-01T00:00:00Z")
        entry_id = scenario["entry"]["id"]
        specimen = validate_success(api.create_specimen({
            "client_laboratory_id": scenario["client"]["id"],
            "courier_run_id": scenario["courier_run"]["id"],
            "accession_number": "ACC-3101-F",
            "patient_mrn": "MRN-3101",
            "specimen_type": "SERUM_SST",
            "container_type": "GOLD_SST",
            "volume_ml": 2.5,
            "collection_at": "2026-08-31T20:40:00Z",
            "received_at": "2026-09-01T00:00:00Z",
            "transport_temperature": "AMBIENT",
            "condition": "ACCEPTABLE",
            "condition_reason_code": None,
        }, self._acc()), 201)
        order = validate_success(api.create_send_out_order({
            "client_laboratory_id": scenario["client"]["id"],
            "specimen_id": specimen["id"],
            "order_number": "REQ-3101-F",
            "patient_mrn": "MRN-3101",
            "client_requested_at": "2026-08-31T20:45:00Z",
            "priority": "ROUTINE",
            "test_lines": [
                {"test_catalog_entry_id": entry_id, "line_sequence": 1},
                {"test_catalog_entry_id": entry_id, "line_sequence": 2},
                {"test_catalog_entry_id": entry_id, "line_sequence": 3},
                {"test_catalog_entry_id": entry_id, "line_sequence": 4},
            ],
            "override_utilization_guard": True,
        }, self._acc()), 201)
        book_run(entry_id, instrument_code="IMM-11",
                 reserved_start_at="2026-09-01T00:00:00Z",
                 reserved_end_at="2026-09-01T04:00:00Z")
        # The specimen-level act bubbles the SUBMITTED order to ACCESSIONED in
        # the same transaction (PRD 3.3), so no separate order accession runs.
        validate_success(api.accession_specimen(specimen["id"], self._acc()), 200)
        validate_success(api.begin_testing(specimen["id"], medtech_headers), 200)

        values = [7.0, 10.0, 350.0, 401.0]
        ids = [line["id"] for line in order["test_lines"]]
        version = refresh_order(order["id"])["version"]
        result_lines = [
            result_line(ids[0], 7.0),
            result_line(ids[1], 10.0),
            result_line(ids[2], 350.0),
            result_line(ids[3], 401.0, critical_value_notified_to="Dr. L. Okafor",
                        critical_value_notified_at="2026-09-01T03:10:00Z"),
        ]
        validate_success(api.enter_results(order["id"], {
            "expected_send_out_order_version": version,
            "result_lines": result_lines,
        }, medtech_headers), 200)

        flags = [validate_success(api.get_order_test_line(line_id, medtech_headers), 200)
                 for line_id in ids]
        assert [f["result_value"] for f in flags] == values
        assert flags[0]["result_flag"] == "LOW", "7.0 is below reference_low 10 but not below critical low 5"
        assert flags[1]["result_flag"] == "NORMAL", "10.0 sits exactly at reference_low, which is inclusive"
        assert flags[2]["result_flag"] == "HIGH", "350.0 exceeds reference_high 300 but not critical high 400"
        assert flags[3]["result_flag"] == "CRITICAL_HIGH", "401.0 steps over the reference step entirely"
        assert flags[0]["entered_by_user_id"] == medtech_headers["X-User-ID"]

    @staticmethod
    def _acc():
        from test_helpers import TEST_USERS
        return TEST_USERS["accessioning_technologist_headers"]


class TestVolumeTierPricing:

    def test_the_third_reportable_line_reprices_every_line_on_the_order(
            self, api, accessioning_headers, medtech_headers):
        """PRD 3.10: "The discount factor follows the count: a count of two or
        fewer carries a factor of 1.00, a count from three through five carries
        0.85, and a count of six or more carries 0.72."
        PRD 3.10: "The count boundaries are inclusive on the lower tier: exactly
        two reportable lines price at the full factor, and exactly three price
        at the discounted factor."
        PRD 3.10: "the line's final `billed_cents` is the larger of that
        discounted amount and the catalogue entry's `floor_price_cents`."

        Design: Corner/complexity_layers/volume_tier_rate_changes_exactly_at_three_reportable_lines
        """
        from test_helpers import setup_two_and_three_line_orders
        scenario = setup_two_and_three_line_orders(
            entry_overrides={"client_price_cents": 1000, "floor_price_cents": 450})
        order_two = scenario["order_two"]
        order_three = scenario["order_three"]

        two_lines = [validate_success(api.get_order_test_line(line["id"], medtech_headers), 200)
                     for line in order_two["test_lines"]]
        three_lines = [validate_success(api.get_order_test_line(line["id"], medtech_headers), 200)
                       for line in order_three["test_lines"]]
        assert [line["billed_cents"] for line in two_lines] == [1000.00, 1000.00]
        assert [line["billed_cents"] for line in three_lines] == [850.00, 850.00, 850.00]

        # ROUTINE on a six-hour assay lands on RUSH, so the order carries the
        # 0.15 surcharge on the summed line charges.
        assert order_two["order_final_charge_cents"] == pytest.approx(2300.00, abs=0.01)
        assert order_three["order_final_charge_cents"] == pytest.approx(2932.50, abs=0.01)
        assert order_two["tat_credit_cents"] == pytest.approx(30.00, abs=0.005)
        assert order_three["tat_credit_cents"] == pytest.approx(38.25, abs=0.005)


class TestRushTierSelection:

    def test_candidate_tier_first_pass_then_one_escalation(self, api, medtech_headers):
        """PRD 3.6: "The order's `priority` drives a candidate tier: a `STAT`
        priority yields a candidate of `CRITICAL`, while `TIMED` and `ROUTINE`
        both yield a candidate of `STANDARD`. The preliminary turnaround is the
        largest `base_tat_hours` across the order's live catalogue entries. A
        first-pass turnaround is then the preliminary value multiplied by the
        candidate tier's factor: `STANDARD` uses 1.0, `RUSH` uses 0.5 and
        `CRITICAL` uses 0.25."
        PRD 3.6: "if the candidate is `STANDARD` and the first-pass turnaround
        is strictly below 24 hours, the tier escalates to `RUSH`".

        Design: Difficulty/combinatorial_formula/rush_tier_keys_on_the_tat_the_tier_itself_changes
        """
        scenario = self._three_assay_scenario(api, medtech_headers)
        o1 = refresh_order(scenario["o1"])
        o8 = refresh_order(scenario["o8"])
        o9 = refresh_order(scenario["o9"])

        assert o1["rush_tier"] == "RUSH", "a 6-hour first pass is below the 24-hour trigger"
        assert o1["effective_tat_hours"] == pytest.approx(3.0, abs=0.01)
        assert o8["rush_tier"] == "STANDARD", "a 24-hour first pass is not below the trigger"
        assert o8["effective_tat_hours"] == pytest.approx(24.0, abs=0.01)
        assert o9["rush_tier"] == "RUSH"
        assert o9["effective_tat_hours"] == pytest.approx(11.75, abs=0.01)

    def test_tier_and_turnaround_freeze_after_a_single_escalation(self, api, medtech_headers):
        """PRD 3.6: "The tier and the turnaround are then frozen - no second
        escalation pass runs even when the escalated turnaround is itself still
        below 24 hours."
        PRD 3.6: "Finally, `expected_result_at` is the specimen's `received_at`
        plus the effective turnaround".

        Design: Difficulty/combinatorial_formula/rush_tier_keys_on_the_tat_the_tier_itself_changes
        """
        scenario = self._three_assay_scenario(api, medtech_headers)
        order = refresh_order(scenario["o1"])
        specimen = validate_success(api.get_specimen(scenario["spec1"], medtech_headers), 200)

        assert order["rush_tier"] == "RUSH", (
            "the escalated turnaround of 3.0 is itself below the trigger, but no second pass runs"
        )
        assert order["rush_tier"] != "CRITICAL"
        assert order["expected_result_at"] == "2026-09-01T08:00:00Z", (
            "received_at 05:00 plus the 3.0-hour effective turnaround"
        )
        assert specimen["received_at"] == "2026-09-01T05:00:00Z"

    @staticmethod
    def _three_assay_scenario(api, medtech_headers):
        """Three ROUTINE orders on assays with 6.0, 24.0 and 23.5-hour base TATs.

        The analyzer windows are staggered so exactly one run is RUNNING and
        covering the clock at each moment testing starts.
        """
        from test_helpers import TEST_USERS
        accessioning = TEST_USERS["accessioning_technologist_headers"]
        # The clock must already be at or past every `client_requested_at` these
        # orders carry (PRD 3.5: "it must not lie in the future relative to the
        # logical clock").
        scenario = setup_active_client(clock="2026-09-01T05:05:00Z")
        client_id = scenario["client"]["id"]
        ferritin = scenario["entry"]

        procalcitonin = validate_success(api.create_catalog_entry({
            "test_code": "PROCALCITONIN", "test_name": "Procalcitonin, Serum",
            "test_category": "ROUTINE", "method": "IMMUNOASSAY",
            "required_specimen_type": "SERUM_SST", "container_type": "GOLD_SST",
            "min_volume_ml": 1.0, "transport_temperature": "AMBIENT",
            "stability_hours_ambient": 24, "stability_hours_refrigerated": 72,
            "stability_hours_frozen": 720, "base_tat_hours": 24,
            "list_price_cents": 3800, "client_price_cents": 3200, "floor_price_cents": 0,
            "critical_value_low": None, "critical_value_high": None,
            "reflex_test_code": None, "reflex_condition": "NONE",
            "reflex_within_hours": 24, "reflex_min_remaining_hours": 6,
            "is_utilization_managed": False,
        }, TEST_USERS["lab_client_admin_headers"]), 201)
        api.publish_catalog_entry(procalcitonin["id"], TEST_USERS["lab_client_admin_headers"])
        troponin = validate_success(api.create_catalog_entry({
            "test_code": "TROPONIN_HS", "test_name": "Troponin I, High Sensitivity",
            "test_category": "ROUTINE", "method": "IMMUNOASSAY",
            "required_specimen_type": "SERUM_SST", "container_type": "GOLD_SST",
            "min_volume_ml": 1.0, "transport_temperature": "AMBIENT",
            "stability_hours_ambient": 24, "stability_hours_refrigerated": 72,
            "stability_hours_frozen": 720, "base_tat_hours": 23.5,
            "list_price_cents": 4200, "client_price_cents": 3600, "floor_price_cents": 0,
            "critical_value_low": 0.0, "critical_value_high": 14.0,
            "reflex_test_code": None, "reflex_condition": "NONE",
            "reflex_within_hours": 24, "reflex_min_remaining_hours": 6,
            "is_utilization_managed": False,
        }, TEST_USERS["lab_client_admin_headers"]), 201)
        api.publish_catalog_entry(troponin["id"], TEST_USERS["lab_client_admin_headers"])

        def _specimen_and_order(suffix, entry_id, patient, sequence):
            specimen = validate_success(api.create_specimen({
                "client_laboratory_id": client_id,
                "courier_run_id": scenario["courier_run"]["id"],
                "accession_number": f"ACC-{suffix}",
                "patient_mrn": patient,
                "specimen_type": "SERUM_SST",
                "container_type": "GOLD_SST",
                "volume_ml": 3.0,
                "collection_at": "2026-09-01T04:00:00Z",
                "received_at": "2026-09-01T05:00:00Z",
                "transport_temperature": "AMBIENT",
                "condition": "ACCEPTABLE",
                "condition_reason_code": None,
            }, accessioning), 201)
            order = validate_success(api.create_send_out_order({
                "client_laboratory_id": client_id,
                "specimen_id": specimen["id"],
                "order_number": f"REQ-{suffix}",
                "patient_mrn": patient,
                "client_requested_at": "2026-09-01T05:05:00Z",
                "priority": "ROUTINE",
                "test_lines": [{"test_catalog_entry_id": entry_id, "line_sequence": 1}],
                "override_utilization_guard": False,
            }, accessioning), 201)
            # The specimen-level act bubbles the SUBMITTED order to ACCESSIONED
            # in the same transaction (PRD 3.3).
            validate_success(api.accession_specimen(specimen["id"], accessioning), 200)
            return specimen, order

        spec1, o1 = _specimen_and_order("3001", ferritin["id"], "MRN-5001", 1)
        spec8, o8 = _specimen_and_order("3002", procalcitonin["id"], "MRN-7001", 2)
        spec9, o9 = _specimen_and_order("3003", troponin["id"], "MRN-7002", 3)

        book_run(ferritin["id"], instrument_code="IMM-01",
                 reserved_start_at="2026-09-01T06:00:00Z", reserved_end_at="2026-09-01T06:30:00Z")
        book_run(procalcitonin["id"], instrument_code="IMM-03",
                 reserved_start_at="2026-09-01T07:00:00Z", reserved_end_at="2026-09-01T07:30:00Z")
        book_run(troponin["id"], instrument_code="IMM-04",
                 reserved_start_at="2026-09-01T08:00:00Z", reserved_end_at="2026-09-01T08:30:00Z")

        set_clock("2026-09-01T06:15:00Z")
        validate_success(api.begin_testing(spec1["id"], medtech_headers), 200)
        set_clock("2026-09-01T07:15:00Z")
        validate_success(api.begin_testing(spec8["id"], medtech_headers), 200)
        set_clock("2026-09-01T08:15:00Z")
        validate_success(api.begin_testing(spec9["id"], medtech_headers), 200)

        return {"o1": o1["id"], "o8": o8["id"], "o9": o9["id"],
                "spec1": spec1["id"], "spec8": spec8["id"], "spec9": spec9["id"]}


class TestTurnaroundCredit:

    def test_late_credit_rounds_each_line_before_summing(self, api, accessioning_headers,
                                                         medtech_headers):
        """PRD 3.10: "A line with an overrun earns the line's own charge
        multiplied by the overrun hours multiplied by the per-hour late-credit
        rate of 0.015, rounded half-up to two decimal places. The order's
        `tat_credit_cents` is then the sum of those per-line credits, rounded
        half-up once more."
        PRD 3.10: "rounding each line first and then summing can differ by a
        cent from summing first and rounding once, and this specification
        requires the per-line round."

        Design: Difficulty/combinatorial_formula/late_credit_rounds_per_line_then_sums
        """
        scenario = self._two_line_refrigerated_order(api, accessioning_headers)
        order = refresh_order(scenario["order"])
        lines = [validate_success(api.get_order_test_line(line["id"], medtech_headers), 200)
                 for line in order["test_lines"]]

        assert [line["billed_cents"] for line in lines] == [1237.00, 1237.00]
        assert [line["tat_credit_cents"] for line in lines] == pytest.approx([18.56, 18.56], abs=0.005)
        assert order["tat_credit_cents"] == pytest.approx(37.12, abs=0.005), (
            "per-line rounding gives 18.56 + 18.56; summing first would give 37.11"
        )

    def test_no_overrun_earns_no_credit(self, api, accessioning_headers, medtech_headers):
        """PRD 3.10: "the overrun is the number of whole hours by which the
        order's release instant exceeds its `expected_result_at`, rounded up,
        and never less than zero - a release that met or beat the expected
        instant produces an overrun of zero. A line with no overrun earns a
        credit of zero."

        Design: Difficulty/combinatorial_formula/late_credit_rounds_per_line_then_sums
        """
        scenario = self._two_line_refrigerated_order(api, accessioning_headers, release_at=None)
        order = refresh_order(scenario["order"])
        assert order["expected_result_at"] == "2026-09-01T09:30:00Z"

        set_clock("2026-09-01T09:25:00Z")
        released = release_order(order["id"], "Lactate and ammonia within reference intervals.")
        assert released["tat_credit_cents"] == 0.00
        lines = [validate_success(api.get_order_test_line(line["id"], medtech_headers), 200)
                 for line in released["test_lines"]]
        assert [line["tat_credit_cents"] for line in lines] == [0.00, 0.00]

    @staticmethod
    def _two_line_refrigerated_order(api, accessioning_headers, release_at="2026-09-01T10:00:00Z"):
        """A two-line order on a refrigerated plasma tube, 1237 cents per line."""
        from test_helpers import TEST_USERS
        medtech = TEST_USERS["medical_technologist_headers"]
        scenario = setup_active_client(
            entry_overrides={
                "test_code": "LACTATE_PLASMA", "test_name": "Lactate, Plasma",
                "method": "PHOTOMETRY", "required_specimen_type": "PLASMA_LITHIUM_HEPARIN",
                "container_type": "GREEN_TOP", "transport_temperature": "REFRIGERATED",
                "stability_hours_ambient": 0.5, "stability_hours_refrigerated": 24,
                "base_tat_hours": 6, "list_price_cents": 1400, "client_price_cents": 1237,
                "floor_price_cents": 0, "critical_value_low": None,
                "critical_value_high": None, "reflex_test_code": None,
                "reflex_condition": "NONE", "reflex_min_remaining_hours": 6,
                "is_utilization_managed": False,
            },
            clock="2026-09-01T07:00:00Z")
        ammonia = validate_success(api.create_catalog_entry({
            "test_code": "AMMONIA_PLASMA", "test_name": "Ammonia, Plasma",
            "test_category": "ROUTINE", "method": "ENZYMATIC",
            "required_specimen_type": "PLASMA_LITHIUM_HEPARIN", "container_type": "GREEN_TOP",
            "min_volume_ml": 1.0, "transport_temperature": "REFRIGERATED",
            "stability_hours_ambient": 0.5, "stability_hours_refrigerated": 24,
            "stability_hours_frozen": 720, "base_tat_hours": 6,
            "list_price_cents": 1450, "client_price_cents": 1237, "floor_price_cents": 0,
            "critical_value_low": None, "critical_value_high": 60,
            "reflex_test_code": None, "reflex_condition": "NONE",
            "reflex_within_hours": 24, "reflex_min_remaining_hours": 6,
            "is_utilization_managed": False,
        }, TEST_USERS["lab_client_admin_headers"]), 201)
        api.publish_catalog_entry(ammonia["id"], TEST_USERS["lab_client_admin_headers"])

        lines = [order_line(scenario["entry"]["id"], 1), order_line(ammonia["id"], 2)]
        scenario = setup_specimen_and_order(
            scenario, lines=lines,
            specimen_overrides={
                "accession_number": "ACC-4001", "patient_mrn": "MRN-8001",
                "specimen_type": "PLASMA_LITHIUM_HEPARIN", "container_type": "GREEN_TOP",
                "volume_ml": 3.0, "collection_at": "2026-09-01T06:00:00Z",
                "received_at": "2026-09-01T06:30:00Z",
                "transport_temperature": "REFRIGERATED",
            },
            run_overrides={"instrument_code": "CHM-01", "section": "CHEM"})
        scenario = start_testing(scenario)
        order = refresh_order(scenario["order"]["id"])
        ids = [line["id"] for line in order["test_lines"]]
        validate_success(api.enter_results(order["id"], {
            "expected_send_out_order_version": order["version"],
            "result_lines": [result_line(ids[0], 2.4, "mmol/L"), result_line(ids[1], 22.0, "umol/L")],
        }, medtech), 200)
        if release_at is not None:
            set_clock(release_at)
            release_order(order["id"], "Lactate and ammonia within reference intervals.")
        return {"order": order["id"]}


class TestProvisionalVersusFinalCharge:

    def test_one_line_prices_differently_in_the_two_variants(self, api, medtech_headers):
        """PRD 3.10: "The provisional variant runs once at accession, before any
        line has a final charge, and it records the order's
        `provisional_charge_cents` as the sum of the catalogue list prices of
        the order's lines, rounded half-up to two decimal places."
        PRD 3.10: "The `charge_variance_cents` field is
        `order_final_charge_cents` minus `provisional_charge_cents`, and it is
        the honest measure of what the estimate missed."

        Design: Difficulty/dual_variant_calc/order_charge_provisional_vs_final_on_one_ferritin_line
        """
        scenario = self._single_line_scenario(api, medtech_headers)
        order = refresh_order(scenario["order"])
        line = validate_success(api.get_order_test_line(scenario["line"], medtech_headers), 200)

        assert order["provisional_charge_cents"] == pytest.approx(1200.00, abs=0.01)
        assert line["billed_cents"] == pytest.approx(1000.00, abs=0.01), (
            "the contracted client price applies at the volume tier of one line"
        )
        assert order["order_final_charge_cents"] == pytest.approx(1150.00, abs=0.01)
        assert order["charge_variance_cents"] == pytest.approx(-50.00, abs=0.01)
        assert order["order_status"] == "RESULT_RELEASED"
        assert order["billing_status"] == "BILLED"

    def test_the_two_variants_diverge_by_exactly_discount_plus_surcharge(
            self, api, medtech_headers):
        """PRD 3.10: "the provisional variant reads neither the contracted client
        price, nor the volume-tier factor, nor the rush surcharge, so for
        identical line data the two variants diverge by exactly the contract
        discount plus the rush surcharge, and nothing else."

        Design: Difficulty/dual_variant_calc/order_charge_provisional_vs_final_on_one_ferritin_line
        """
        scenario = self._single_line_scenario(api, medtech_headers)
        order = refresh_order(scenario["order"])
        entry = scenario["entry"]

        list_price = entry["list_price_cents"]
        contract_price = entry["client_price_cents"]
        discount_cents = list_price - contract_price
        surcharge_cents = contract_price * 0.15  # RUSH on a six-hour ROUTINE assay
        assert order["provisional_charge_cents"] == pytest.approx(list_price, abs=0.01), (
            "the estimate reads the list price and nothing else"
        )
        assert order["charge_variance_cents"] == pytest.approx(
            surcharge_cents - discount_cents, abs=0.01), (
            "the divergence is the surcharge less the contract discount"
        )
        # PRD 3.10 credits "the line's own charge" — the line's billed_cents, not
        # the order's surcharged final charge — so 1000.00 x 1 overrun hour x the
        # 0.015 per-hour rate gives 15.00.
        assert order["tat_credit_cents"] == pytest.approx(15.00, abs=0.005), (
            "1000.00 of line charge x 1 hour x 0.015 rounds half-up to 15.00"
        )
        assert order["rush_tier"] == "RUSH"
        assert order["effective_tat_hours"] == pytest.approx(3.0, abs=0.01)
        assert order["expected_result_at"] == "2026-09-01T09:30:00Z"

    @staticmethod
    def _single_line_scenario(api, medtech_headers):
        scenario = setup_active_client(clock="2026-09-01T07:00:00Z")
        scenario = setup_specimen_and_order(scenario, run_overrides={"instrument_code": "IMM-01"})
        scenario = start_testing(scenario)
        order = refresh_order(scenario["order"]["id"])
        line_id = order["test_lines"][0]["id"]
        validate_success(api.enter_results(order["id"], {
            "expected_send_out_order_version": order["version"],
            "result_lines": [result_line(line_id, 250.0)],
        }, medtech_headers), 200)
        set_clock("2026-09-01T10:00:00Z")
        release_order(order["id"], "Ferritin within reference interval.")
        return {"client": scenario["client"], "entry": scenario["entry"],
                "order": order["id"], "line": line_id}