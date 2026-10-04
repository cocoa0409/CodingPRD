"""Depth tests: the two stability channels, the dose tariff and the carry waterfall.

These translate instances from the difficulty design index that turn on a dual
variant or a pinned evaluation order.
"""

import pytest

from test_helpers import (
    api_client,
    get_success_data,
    setup_active_patient,
    setup_active_patient_and_maintenance,
    setup_approvable_carry_patient,
    setup_clinic,
    schedule_and_miss,
    run_observed_dose,
    hold_privilege,
    evaluate_privilege,
    list_doses,
    set_clock,
    advance_to_maintenance,
    validate_success,
    validate_error,
    ApiErrorId,
)


class TestStabilityChannelDivergence:
    """The two stability channels read the same Patient row and disagree."""

    def _setup(self):
        clinic = setup_clinic(allotted_carries=10,
                              lot_overrides={"lot_number": "LOT-A1",
                                             "reusable_for_take_home": True})
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(
            clinic, ordered_daily_mg=90.0, transportation_type="NO_RELIABLE_TRANSPORT")
        # Two consecutive scheduled doses on open days, each recorded missed.
        schedule_and_miss(clinic, order["id"], "2026-09-02", "2026-09-02T07:00:00Z",
                          inventory_lot_id=clinic["lot"]["id"])
        schedule_and_miss(clinic, order["id"], "2026-09-03", "2026-09-03T07:00:00Z",
                          inventory_lot_id=clinic["lot"]["id"])
        set_clock("2026-12-15T00:00:00Z")
        advance_to_maintenance(patient["id"], clinic["physician_headers"], reconciled_days=1)
        return clinic, patient, order

    def test_direction_a_publishes_the_unpenalised_reading(self):
        """PRD 2.5: "The first channel is the published stability reading, the
        DIRECTION_A_STABILITY score, which the system exposes as the patient's
        `stability_score` on every patient read."
        PRD 2.5: "The DIRECTION_B_TAKE_HOME_READINESS number is never returned
        by a patient read."
        PRD 2.5: "Because Direction B subtracts penalties that Direction A does
        not, the two channels will publish different numbers for the same
        patient at the same instant."

        Design: Difficulty/dual_variant_calc/stability_channel_divergence_on_one_patient_row
        """
        clinic, patient, order = self._setup()
        read = validate_success(api_client.get_patient(patient["id"], clinic["director_headers"]))
        assert read["stability_score"] == pytest.approx(65.5, abs=0.05), (
            f"Direction A published reading was {read['stability_score']}, expected 65.5")
        assert read["stability_score"] != 0.0, (
            "the published Direction A figure must not be the value that gated the carry")

    def test_carry_gate_reads_direction_b_and_denies(self):
        """PRD 2.5: "It gates carries, and it does so against a phase-dependent
        floor: the readiness reading must be at least 70.0 when the patient's
        `treatment_phase` is `MAINTENANCE`, and at least 75.0 in every other
        phase."
        PRD 3.6: "The patient's DIRECTION_B_TAKE_HOME_READINESS reading must be
        at least 70.0 when the phase is `MAINTENANCE` and at least 75.0
        otherwise, else `ERR_STABILITY_BELOW_THRESHOLD` (HTTP 422)."
        PRD 3.6: "The denial branch fires when at least one of those approval
        conditions fails, and it is deliberately quiet about which one."

        Design: Difficulty/dual_variant_calc/stability_channel_divergence_on_one_patient_row
        """
        clinic, patient, order = self._setup()
        current = get_success_data(api_client.get_patient(patient["id"], clinic["director_headers"]))
        priv = hold_privilege(clinic, patient["id"], current["version"], requested_carries=1)
        validate_error(evaluate_privilege(clinic, priv["id"]),
                       ApiErrorId.ERR_STABILITY_BELOW_THRESHOLD.value)
        after = get_success_data(api_client.get_privilege(priv["id"], clinic["director_headers"]))
        assert after["decision"] == "DENIED", (
            f"privilege decision was {after['decision']}, expected DENIED")
        assert after["denial_reason_code"] == "STABILITY_BELOW_THRESHOLD", (
            f"denial_reason_code was {after['denial_reason_code']}")


class TestDoseTariffRoundingOrder:
    """The tariff rounds each component first and then sums."""

    def test_no_waste_case_pins_both_variants(self):
        """PRD 3.4: "The rounding order of this tariff is pinned and is the
        single most easily mis-implemented rule in the system. Every component
        is rounded half up to two decimal places first, and the rounded
        components are then summed; the unrounded sum is never the reported
        figure."
        PRD 3.4: "For an order of 90 milligrams of methadone against a
        120-milligram ceiling, with no waste and no split authorisation, the
        reported total is 392.31."
        PRD 3.4: "An implementation that sums the unrounded components and
        rounds once at the end will produce a reconciling figure one cent lower
        at 392.30, and this is exposed rather than hidden: the charge-preview
        reading for an already-dispensed dose returns both variants side by
        side, as `total_charge_per_component_rounded` and
        `total_charge_sum_then_round`, together with `per_component_delta`
        stating the difference between them."

        Design: Difficulty/dual_variant_calc/dose_tariff_per_component_versus_sum_then_round_delta
        """
        clinic = setup_clinic()
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(clinic, ordered_daily_mg=90.0)
        set_clock("2026-12-15T00:00:00Z")
        dose = run_observed_dose(clinic, order["id"], "2026-12-16", "2026-12-16T07:00:00Z",
                                 90.0, clinic["lot"]["id"])

        preview = validate_success(api_client.get_charge_preview(dose["id"], clinic["admin_headers"]))
        assert preview["total_charge_per_component_rounded"] == pytest.approx(392.31, abs=0.001)
        assert preview["total_charge_sum_then_round"] == pytest.approx(392.30, abs=0.001)
        assert preview["per_component_delta"] == pytest.approx(0.01, abs=0.001)

        row = validate_success(api_client.get_dose_dispense(dose["id"], clinic["nurse_headers"]))
        assert row["status"] == "COMPLETED"
        assert row["dispensed_mg"] == pytest.approx(90.0)

        lot = validate_success(api_client.get_lot(clinic["lot"]["id"], clinic["admin_headers"]))
        assert lot["running_on_hand_mg"] == pytest.approx(49910.0, abs=0.01)

    def test_source_yaml_assertions_mirrored_on_the_dispensed_row(self):
        """PRD 3.4: "The billed dispensed and billed wasted quantities are the
        dose's `dispensed_mg` and `wasted_mg` when the program's posture is
        `NORMAL` and the patient's status is `ACTIVE`, and zero otherwise."
        PRD 3.4: "A `DISPENSE` movement is appended with a negative
        `quantity_mg` equal to the dispensed milligrams and the selected lot
        recorded as `lot_id`."
        PRD 2.9: "`on_hand_mg` is a read alias of that running figure."

        Design: Difficulty/dual_variant_calc/dose_tariff_per_component_versus_sum_then_round_delta
        """
        clinic = setup_clinic()
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(clinic, ordered_daily_mg=90.0)
        set_clock("2026-12-15T00:00:00Z")
        dose = run_observed_dose(clinic, order["id"], "2026-12-16", "2026-12-16T07:00:00Z",
                                 90.0, clinic["lot"]["id"])

        lot = validate_success(api_client.get_lot(clinic["lot"]["id"], clinic["admin_headers"]))
        assert lot["on_hand_mg"] == pytest.approx(lot["running_on_hand_mg"], abs=0.01)

        txs = list_doses(clinic, {"dose_dispense_id": dose["id"]}, clinic["admin_headers"])
        # The dose's own inventory movements are reached through the lot filter.
        lot_txs = [t for t in _transactions(clinic) if t["lot_id"] == clinic["lot"]["id"]]
        dispenses = [t for t in lot_txs if t["transaction_type"] == "DISPENSE"]
        assert len(dispenses) == 1, f"expected one DISPENSE row, got {len(dispenses)}"
        assert dispenses[0]["quantity_mg"] == pytest.approx(-90.0)


def _transactions(clinic):
    from prd_bench_local_runner.testing import validate_paginated
    data, _meta = validate_paginated(
        api_client.list_transactions(clinic["admin_headers"]))
    return data


class TestDoseTariffNestedRoundingWithWaste:
    """A 100 mg order dispensed as 90 mg with 10 mg wasted."""

    def _setup(self):
        clinic = setup_clinic(lot_overrides={"lot_number": "LOT-A1",
                                             "reusable_for_take_home": True})
        set_clock("2026-09-01T00:00:00Z")
        patient, order = setup_active_patient(clinic, ordered_daily_mg=100.0)
        set_clock("2026-12-15T00:00:00Z")
        return clinic, patient, order

    def test_waste_case_pins_the_rounding_order(self):
        """PRD 3.4: "a waste fee of 1.15 for each whole block of ten milligrams
        of billed waste beyond a ten-milligram free allowance, again rounded
        half up to two decimal places."
        PRD 3.4: "Every component is rounded half up to two decimal places
        first, and the rounded components are then summed; the unrounded sum is
        never the reported figure."

        Design: Difficulty/combinatorial_formula/dose_tariff_nested_rounding_order_is_pinned
        """
        clinic, patient, order = self._setup()
        dose = run_observed_dose(clinic, order["id"], "2026-12-17", "2026-12-17T07:00:00Z",
                                 90.0, clinic["lot"]["id"], wasted_mg=10.0,
                                 witness_staff_id="staff-witness-77", complete=False)
        preview = validate_success(api_client.get_charge_preview(dose["id"], clinic["admin_headers"]))
        assert preview["total_charge_per_component_rounded"] == pytest.approx(460.31, abs=0.001)
        assert preview["total_charge_sum_then_round"] == pytest.approx(460.30, abs=0.001)

    def test_waste_movement_is_recorded_with_the_witness(self):
        """PRD 3.4: "when `wasted_mg` is greater than zero a `WASTE` movement is
        appended with a negative quantity equal to the wasted milligrams."
        PRD 3.12: "A `witness_staff_id` is required for `WASTE` and
        `DESTRUCTION` movements, and must differ from the acting user, else
        `ERR_WITNESS_REQUIRED` (HTTP 422)."

        Design: Difficulty/combinatorial_formula/dose_tariff_nested_rounding_order_is_pinned
        """
        clinic, patient, order = self._setup()
        dose = run_observed_dose(clinic, order["id"], "2026-12-17", "2026-12-17T07:00:00Z",
                                 90.0, clinic["lot"]["id"], wasted_mg=10.0,
                                 witness_staff_id="staff-witness-77", complete=False)
        row = validate_success(api_client.get_dose_dispense(dose["id"], clinic["nurse_headers"]))
        assert row["status"] == "DISPENSED"
        assert row["wasted_mg"] == pytest.approx(10.0)

        lot_txs = [t for t in _transactions(clinic) if t["lot_id"] == clinic["lot"]["id"]]
        waste = [t for t in lot_txs if t["transaction_type"] == "WASTE"]
        assert len(waste) == 1, f"expected one WASTE row, got {len(waste)}"
        assert waste[0]["quantity_mg"] == pytest.approx(-10.0)
        assert waste[0]["witness_staff_id"] == "staff-witness-77"

        lot = validate_success(api_client.get_lot(clinic["lot"]["id"], clinic["admin_headers"]))
        assert lot["running_on_hand_mg"] == pytest.approx(49900.0, abs=0.01)


class TestReadinessEvaluationOrder:
    """Direction B is well-defined only once the evaluation order is pinned."""

    def test_pinned_order_approves_at_the_maintenance_floor(self):
        """PRD 3.6: "The patient's DIRECTION_B_TAKE_HOME_READINESS reading must
        be at least 70.0 when the phase is `MAINTENANCE` and at least 75.0
        otherwise, else `ERR_STABILITY_BELOW_THRESHOLD` (HTTP 422)."
        PRD 3.6: "When every condition holds, the evaluation computes the grant
        size through the carry waterfall, records `evaluation_basis` as
        `TIME_IN_TREATMENT`."
        PRD 3.6: "The new row begins in `PENDING_REVIEW` with `approved_carries`
        at 0, `freed_carries` at 0 and `expires_on` null — the expiration stamp
        is written at approval, not at request."
        PRD 3.6: "When every condition holds, the evaluation computes the grant
        size through the carry waterfall, records `evaluation_basis` as
        `TIME_IN_TREATMENT`, and stamps `expires_on` with the withdrawal-report
        expiration date computed as of the approval instant."

        Design: Difficulty/combinatorial_formula/readiness_evaluation_order_pinned_against_stale_posting
        """
        clinic = setup_clinic(allotted_carries=10)
        patient, order = setup_approvable_carry_patient(clinic, ordered_daily_mg=90.0)

        priv = hold_privilege(clinic, patient["id"], patient["version"], requested_carries=1)
        approved = validate_success(evaluate_privilege(clinic, priv["id"]))
        assert approved["decision"] == "APPROVED"
        assert approved["denial_reason_code"] is None
        assert approved["approved_carries"] == 1
        assert approved["evaluation_basis"] == "TIME_IN_TREATMENT"

    def test_direction_a_reading_is_freshly_recomputed_not_the_stale_posting(self):
        """PRD 2.5: "The second channel is the DIRECTION_B_TAKE_HOME_READINESS
        score. It begins from the DIRECTION_A_STABILITY value computed at the
        same instant."
        PRD 2.5: "It starts from a base of 50.0 and credits the patient for time
        in treatment — the smaller of 25.0 and one quarter of one point per
        whole day of `time_in_treatment_days`."
        PRD 2.4: "it is copied into the cached `stability_posting` field on the
        same row whenever the channel is recomputed."

        Design: Difficulty/combinatorial_formula/readiness_evaluation_order_pinned_against_stale_posting
        """
        clinic = setup_clinic(allotted_carries=10)
        patient, order = setup_approvable_carry_patient(clinic, ordered_daily_mg=90.0)

        read = validate_success(api_client.get_patient(patient["id"], clinic["director_headers"]))
        assert read["stability_score"] == pytest.approx(75.0, abs=0.05), (
            f"Direction A was {read['stability_score']}, expected 75.0 "
            "(50.0 base plus the capped 25.0 treatment-days term)")


class TestCarryCapWaterfall:
    """Three caps nest by minimum; the program pool is the binding term."""

    def _setup(self):
        # PRD 3.7's worked arithmetic is a quota of 40 with 30 already granted,
        # leaving a remainder of 10 whose half is the pool cap of 5. Each of the
        # three prior grants is 10 carries, so each holder needs a table
        # allowance of at least 10 — that is 540 days under PRD 3.7's
        # time-in-treatment table — otherwise the table term would cap the grant
        # below 10 and the pool would never reach a remainder of 10.
        clinic = setup_clinic(allotted_carries=40)
        for i in range(3):
            patient_i, _order_i = setup_approvable_carry_patient(
                clinic, time_in_treatment_days=600, ordered_daily_mg=90.0,
                full_name=f"Granted Patient {i + 1}",
                government_id_hash="sha256:grant%04d" % (i + 1))
            priv_i = hold_privilege(clinic, patient_i["id"], patient_i["version"],
                                    requested_carries=10)
            granted_i = validate_success(evaluate_privilege(clinic, priv_i["id"]))
            assert granted_i["approved_carries"] == 10, (
                f"prior grant {i + 1} was capped at {granted_i['approved_carries']}, "
                "so the pool would not reach PRD 3.7's remainder of 10")
        quota = _quota(clinic)
        assert quota["granted_carries"] == 30, (
            f"setup expected 30 carries granted, got {quota['granted_carries']}")
        assert quota["available_carries"] == 10

        patient, order = setup_approvable_carry_patient(
            clinic, time_in_treatment_days=600, ordered_daily_mg=90.0,
            full_name="Applicant Patient",
            government_id_hash="sha256:applicant01")
        return clinic, patient, order

    def test_pool_cap_binds_the_three_way_minimum(self):
        """PRD 3.7: "It then sets the privilege's `eligible_carry_cap` to the
        smallest of three numbers: the privilege's `requested_carries`, the
        table allowance for the patient's time in treatment, and the pool cap."
        PRD 3.7: "The pool term applies before the table term in the sense that
        both are minima, but it is worth being explicit about the arithmetic:
        with an allotted quota of 40 and 30 already granted, the remainder is
        10, the pool cap is the floor of half of 10, which is 5."
        PRD 3.7: "Once the grant is recorded, the program's `granted_carries` is
        increased by `approved_carries` and `available_carries` is restated as
        `allotted_carries` minus `granted_carries`, preserving the C1 identity."

        Design: Difficulty/combinatorial_formula/carry_cap_waterfall_nested_three_cap_min
        """
        clinic, patient, order = self._setup()
        priv = hold_privilege(clinic, patient["id"], patient["version"], requested_carries=6)
        granted = validate_success(evaluate_privilege(clinic, priv["id"]))
        assert granted["decision"] == "APPROVED"
        assert granted["eligible_carry_cap"] == 5
        assert granted["approved_carries"] == 5
        assert granted["evaluation_basis"] == "TIME_IN_TREATMENT"

        quota = _quota(clinic)
        assert quota["granted_carries"] == 35
        assert quota["available_carries"] == 5

    def test_reduced_grant_is_not_an_error(self):
        """PRD 2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD 3.6: "A grant smaller than what the patient requested is not an
        error. When the waterfall returns a cap below `requested_carries`, the
        evaluation returns HTTP 200 with the reduced count, and
        `denial_reason_code` is left unset."

        Design: Difficulty/combinatorial_formula/carry_cap_waterfall_nested_three_cap_min
        """
        clinic, patient, order = self._setup()
        priv = hold_privilege(clinic, patient["id"], patient["version"], requested_carries=6)
        res = evaluate_privilege(clinic, priv["id"])
        assert res.status_code == 200, f"reduced grant must not be an error, got {res.status_code}"
        body = res.json()
        assert body["response_type"] == "object"
        assert body["data"]["denial_reason_code"] is None
        assert body["data"]["approved_carries"] == 5


def _quota(clinic):
    res = api_client.get_carry_quota(clinic["program"]["id"], clinic["admin_headers"])
    data = validate_success(res)
    if isinstance(data, list):
        return data[0]
    return data