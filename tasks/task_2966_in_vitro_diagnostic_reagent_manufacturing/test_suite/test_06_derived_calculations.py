"""Derived calculations: acceptance bounds, the stability conforming prefix,
complaint reporting deadlines, design-trace completeness, the bridging
requirement and its equivalence limits, and calendar-month expiry.

Every expected figure below is recomputed longhand from the formula the PRD
states, and the arithmetic is written out in a comment next to the literal.
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import assertions, constants, factories, fixtures
from test_helpers.test_users import (QA_RELEASER, QC_ANALYST,
                                     REGULATORY_AFFAIRS)

# The clock's documented starting instant plus a fixed offset, so every
# server-stamped instant in this file is predictable.
CLOCK_AUG_20 = "2026-08-20T00:00:00.000Z"
CLOCK_AUG_21 = "2026-08-21T00:00:00.000Z"
CLOCK_SEP_06 = "2026-09-06T00:00:00.000Z"


# ---------------------------------------------------------------------------
# Private helpers — state builders this file needs and the shared fixtures do
# not offer.
# ---------------------------------------------------------------------------
def _fill_and_complete(api, lot_id):
    """Carry an already-dispensed finished lot to FILLED through one run."""
    run = fixtures.schedule_fill_run(api, lot_id)
    fixtures.start_fill_run(api, run["id"])
    fixtures.record_bioburden_sample(api, run["id"])
    fixtures.complete_fill_run(api, run["id"], run["planned_fill_units"])
    return fixtures.ok(api.get_reagent_lot(lot_id, QA_RELEASER))


def _critical_product_with_two_vendor_lots(api):
    """A cleared product whose only bill-of-materials entry is a *critical*
    antibody, with two qualified lots of it on different vendor lot codes.

    Returns ``(setup, original_material_lot, changed_material_lot)``.
    """
    setup = fixtures.manufacturing_setup(api, material_types=("ANTIBODY",),
                                         critical_types=("ANTIBODY",))
    material_spec = setup["materials"][0]["spec"]
    original = setup["materials"][0]["lot"]
    changed = fixtures.qualified_material_lot_for_spec(api, material_spec)
    return setup, original, changed


def _lot_from_material(api, product_id, material_lot_id):
    """Open a finished lot and dispense exactly one antibody component into it.

    Returns ``(lot_as_it_reads_after_the_dispense, dispensing_row)``.
    """
    lot = fixtures.create_reagent_lot(api, product_id)
    row = fixtures.dispense_component(api, lot["id"], material_lot_id,
                                      "ANTIBODY")
    return fixtures.ok(api.get_reagent_lot(lot["id"], QA_RELEASER)), row


class TestMaterialAcceptanceBounds:

    def test_every_acceptance_bound_passes_exactly_on_the_bound(self, api):
        """PRD §3.1: "The `outcome` of a raw-material measurement is `PASS` or
        `FAIL`, decided against the specification bound that governs its
        `test_code`, and every bound is inclusive so a value landing exactly on
        the bound passes."
        PRD §3.1: "A `POTENCY` measurement passes when `measured_value` is at
        least `potency_min_pct` and at most `potency_max_pct`."
        PRD §3.1: "A `PURITY` measurement passes when `measured_value` is at
        least `purity_min_pct`."
        PRD §3.1: "An `ENDOTOXIN` measurement passes when `measured_value` is at
        most `endotoxin_max_eu_per_ml`."
        PRD §3.1: "An `IDENTITY` measurement passes when `measured_value` is at
        least 1.0."

        Design: Corner/calculations/test_result_outcome_passes_exactly_on_every_inclusive_specification_bound
        """
        fixtures.set_clock(api, CLOCK_AUG_20)
        spec = fixtures.create_material_specification(
            api, potency_min_pct=90.0, potency_max_pct=110.0,
            purity_min_pct=95.0, endotoxin_max_eu_per_ml=2.0,
            required_test_codes=["POTENCY", "PURITY", "ENDOTOXIN", "IDENTITY"])
        lot = fixtures.create_material_lot(api, spec["id"])

        # One measurement per bound, each sitting exactly on it: the low and the
        # high end of the two-sided potency window, the purity floor, the
        # endotoxin ceiling and the identity constant 1.0.
        on_the_bound = [("POTENCY", 90.0), ("POTENCY", 110.0),
                        ("PURITY", 95.0), ("ENDOTOXIN", 2.0),
                        ("IDENTITY", 1.0)]
        for test_code, measured_value in on_the_bound:
            result = fixtures.record_material_measurement(
                api, lot["id"], test_code, measured_value)
            assertions.assert_test_result(result)
            assert result["outcome"] == "PASS", (
                f"{test_code} at {measured_value} lands exactly on its "
                "inclusive bound and must pass")

        reread = fixtures.ok(api.get_material_lot(lot["id"], QA_RELEASER))
        assert reread["qualification_status"] == "UNDER_TEST"
        assert reread["first_oos_at"] is None, \
            "no measurement failed, so the retest clock was never anchored"

    def test_a_failure_one_step_outside_a_bound_anchors_first_oos_at_once(self, api):
        """PRD §3.1: "On each such record the server sets `first_oos_at` to that
        record's `performed_at` when the record's `outcome` is `FAIL` and
        `first_oos_at` was still null — the earliest failure anchors the retest
        clock and is never overwritten by a later failure."
        PRD §3.1: "An `ENDOTOXIN` measurement passes when `measured_value` is at
        most `endotoxin_max_eu_per_ml`."
        PRD §3.1: "A `POTENCY` measurement passes when `measured_value` is at
        least `potency_min_pct` and at most `potency_max_pct`."

        Design: Corner/calculations/test_result_outcome_passes_exactly_on_every_inclusive_specification_bound
        """
        fixtures.set_clock(api, CLOCK_AUG_20)
        spec = fixtures.create_material_specification(
            api, potency_min_pct=90.0, potency_max_pct=110.0,
            purity_min_pct=95.0, endotoxin_max_eu_per_ml=2.0,
            required_test_codes=["POTENCY", "PURITY", "ENDOTOXIN", "IDENTITY"])
        lot = fixtures.create_material_lot(api, spec["id"])

        # 89.99 is below potency_min_pct 90.0 by one hundredth, so the two-sided
        # window rejects it and this first FAIL anchors first_oos_at on the clock.
        first_failure = fixtures.record_material_measurement(
            api, lot["id"], "POTENCY", 89.99)
        assert first_failure["outcome"] == "FAIL"
        assertions.assert_same_instant(first_failure["performed_at"],
                                       CLOCK_AUG_20, "performed_at")

        anchored = fixtures.ok(api.get_material_lot(lot["id"], QA_RELEASER))
        assertions.assert_same_instant(anchored["first_oos_at"], CLOCK_AUG_20,
                                       "first_oos_at")
        assertions.assert_three_fractional_digits(anchored["first_oos_at"],
                                                  "first_oos_at")

        # A day later, three more values each one step outside their own bound.
        fixtures.set_clock(api, CLOCK_AUG_21)
        for test_code, measured_value in [("POTENCY", 110.01),
                                          ("PURITY", 94.99),
                                          ("ENDOTOXIN", 2.01),
                                          ("IDENTITY", 0.99)]:
            later = fixtures.record_material_measurement(
                api, lot["id"], test_code, measured_value)
            assert later["outcome"] == "FAIL", (
                f"{test_code} at {measured_value} sits outside its bound and "
                "must fail")

        # first_oos_at still names the earliest failure, not the latest one.
        reread = fixtures.ok(api.get_material_lot(lot["id"], QA_RELEASER))
        assertions.assert_same_instant(reread["first_oos_at"], CLOCK_AUG_20,
                                       "first_oos_at")

    def test_a_test_code_outside_the_required_set_is_refused(self, api):
        """PRD §3.1: "The `test_code` must be a member of the governing
        specification's `required_test_codes`, otherwise the record is refused
        with `ERR_TEST_CODE_NOT_IN_SPEC`."
        PRD §3.1: "Under `ALL_PASS`, the verdict is `ACCEPT` only when every code
        in `required_test_codes` has a latest measurement whose `outcome` is
        `PASS`; a single out-of-bound measurement rejects the lot no matter how
        well the other tests scored, and `acceptance_score` stays null
        throughout."

        Design: Corner/calculations/test_result_outcome_passes_exactly_on_every_inclusive_specification_bound
        """
        fixtures.set_clock(api, CLOCK_AUG_20)
        spec = fixtures.create_material_specification(
            api, potency_min_pct=90.0, potency_max_pct=110.0,
            purity_min_pct=95.0, endotoxin_max_eu_per_ml=2.0,
            acceptance_mode="ALL_PASS",
            required_test_codes=["POTENCY", "PURITY", "ENDOTOXIN"])
        lot = fixtures.create_material_lot(api, spec["id"])

        fixtures.record_material_measurement(api, lot["id"], "POTENCY", 90.0)

        # IDENTITY is a declared acceptance test of the catalogue but is not a
        # member of this specification's required_test_codes.
        refused = api.create_test_result(
            factories.material_test_result_payload(lot["id"], "IDENTITY", 1.0),
            QC_ANALYST)
        validate_error(refused, "ERR_TEST_CODE_NOT_IN_SPEC")

        reread = fixtures.ok(api.get_material_lot(lot["id"], QA_RELEASER))
        assert reread["acceptance_score"] is None, \
            "under ALL_PASS the acceptance score stays null throughout"


class TestStabilityConformingPrefix:

    def _study_with_planned_months(self, api, planned_months, baseline_value,
                                   shelf_life_months_claim=24):
        product = fixtures.create_product_specification(
            api, shelf_life_months_claim=shelf_life_months_claim)
        lot = fixtures.create_reagent_lot(api, product["id"])
        study = fixtures.create_stability_study(
            api, product["id"], lot["id"], study_type="REAL_TIME",
            planned_timepoints_months=planned_months,
            baseline_value=baseline_value)
        fixtures.approve_stability_protocol(api, study["id"])
        return product, study

    def test_a_gap_in_the_planned_prefix_caps_the_last_conforming_month(self, api):
        """PRD §3.6: "`last_conforming_month` is the longest **conforming
        prefix** of the protocol, expressed as a month index."
        PRD §3.6: "A planned index with no record at all breaks the prefix just
        as surely as a non-conforming one does, and the field stays null when
        month 0 itself is either missing or non-conforming."
        PRD §3.6: "A study with conforming records at months 0, 3 and 9 but
        nothing at month 6 therefore has a `last_conforming_month` of 3, not 9."
        PRD §3.6: "Both hops recompute `timepoint_count` — the count of
        measurements carrying this `stability_study_id` — and
        `last_conforming_month`, and both increase the study's `version` by 1."

        Design: Corner/calculations/stability_last_conforming_month_breaks_at_the_first_gap_in_the_planned_prefix
        """
        _, study = self._study_with_planned_months(api, [0, 3, 6, 9], 200.0)

        # recovery_pct = measured_value / baseline_value * 100, rounded half-up:
        #   200.0 / 200.0 * 100 = 100.00   month 0
        #   190.0 / 200.0 * 100 =  95.00   month 3
        #   188.0 / 200.0 * 100 =  94.00   month 9
        # all three are at least 90.00, so each record conforms on its own.
        for month_index, measured_value, expected_recovery in [
                (0, 200.0, 100.00), (3, 190.0, 95.00), (9, 188.0, 94.00)]:
            timepoint = fixtures.record_timepoint(api, study["id"], month_index,
                                                  measured_value)
            assert float(timepoint["recovery_pct"]) == expected_recovery
            assert timepoint["outcome"] == "PASS"

        with_gap = fixtures.ok(api.get_stability_study(study["id"],
                                                       REGULATORY_AFFAIRS))
        assertions.assert_stability_study(with_gap)
        # Planned index 6 has no record, so the conforming prefix stops at 3.
        assert with_gap["last_conforming_month"] == 3
        assert with_gap["timepoint_count"] == 3, \
            "the count of records and the length of the prefix are independent"
        assert with_gap["status"] == "IN_PROGRESS"

    def test_back_filling_the_gap_extends_the_prefix_past_it(self, api):
        """PRD §3.6: "It is the largest planned month index such that every
        planned index at or below it has at least one recorded timepoint whose
        `recovery_pct` is at least 90.00."
        PRD §3.6: "For a `REAL_TIME` study, `established_shelf_life_months` is
        the lesser of `last_conforming_month` and the product's
        `shelf_life_months_claim`, and `shelf_life_method` is recorded as
        `REAL_TIME_LAST_CONFORMING`; there is no extrapolation, so a real-time
        shelf life can never exceed the protocol time actually elapsed."

        Design: Corner/calculations/stability_last_conforming_month_breaks_at_the_first_gap_in_the_planned_prefix
        """
        _, study = self._study_with_planned_months(api, [0, 3, 6, 9], 200.0,
                                                   shelf_life_months_claim=24)
        for month_index, measured_value in [(0, 200.0), (3, 190.0), (9, 188.0)]:
            fixtures.record_timepoint(api, study["id"], month_index,
                                      measured_value)

        # 184.0 / 200.0 * 100 = 92.00 >= 90.00, so month 6 conforms and the
        # prefix now runs 0, 3, 6, 9 without a hole.
        back_filled = fixtures.record_timepoint(api, study["id"], 6, 184.0)
        assert float(back_filled["recovery_pct"]) == 92.00
        assert back_filled["outcome"] == "PASS"

        filled = fixtures.ok(api.get_stability_study(study["id"],
                                                     REGULATORY_AFFAIRS))
        assert filled["last_conforming_month"] == 9, \
            "back-filling the gap moves the prefix straight from 3 to 9"
        assert filled["timepoint_count"] == 4

        concluded = fixtures.ok(api.conclude_stability_study(study["id"],
                                                             REGULATORY_AFFAIRS))
        assert concluded["status"] == "COMPLETE"
        # lesser of last_conforming_month 9 and shelf_life_months_claim 24 == 9
        assert concluded["established_shelf_life_months"] == 9
        assert concluded["shelf_life_method"] == "REAL_TIME_LAST_CONFORMING"

    def test_a_missing_month_zero_leaves_the_prefix_null(self, api):
        """PRD §3.6: "A planned index with no record at all breaks the prefix
        just as surely as a non-conforming one does, and the field stays null
        when month 0 itself is either missing or non-conforming."
        PRD §3.6: "Both hops recompute `timepoint_count` — the count of
        measurements carrying this `stability_study_id` — and
        `last_conforming_month`, and both increase the study's `version` by 1."

        Design: Corner/calculations/stability_last_conforming_month_breaks_at_the_first_gap_in_the_planned_prefix
        """
        _, study = self._study_with_planned_months(api, [0, 3, 6], 200.0)

        # 195.0 / 200.0 * 100 = 97.50, a conforming record — but it sits at
        # month 3, and planned month 0 has nothing at all.
        recorded = fixtures.record_timepoint(api, study["id"], 3, 195.0)
        assert float(recorded["recovery_pct"]) == 97.50
        assert recorded["outcome"] == "PASS"

        reread = fixtures.ok(api.get_stability_study(study["id"],
                                                     REGULATORY_AFFAIRS))
        assert reread["last_conforming_month"] is None
        assert reread["timepoint_count"] == 1

    def test_a_non_conforming_month_zero_leaves_the_prefix_null_and_blocks_conclusion(self, api):
        """PRD §3.6: "The server computes `recovery_pct` as `measured_value`
        divided by the study's `baseline_value`, multiplied by 100 and rounded
        half-up to two decimal places, and sets `outcome` to `PASS` when
        `recovery_pct` is at least 90.00 — inclusively — and `FAIL` otherwise."
        PRD §3.6: "A `RegulatoryAffairs` user concludes the study; it must be
        `IN_PROGRESS` and its `last_conforming_month` must not be null, so a
        study with no usable timepoints cannot be concluded and is refused with
        `ERR_STABILITY_STUDY_STATE_INVALID`."

        Design: Corner/calculations/stability_last_conforming_month_breaks_at_the_first_gap_in_the_planned_prefix
        """
        _, study = self._study_with_planned_months(api, [0, 3, 6], 200.0)

        # 179.9 / 200.0 * 100 = 89.95, one hundredth under the 90.00 floor.
        recorded = fixtures.record_timepoint(api, study["id"], 0, 179.9)
        assert float(recorded["recovery_pct"]) == 89.95
        assert recorded["outcome"] == "FAIL"

        reread = fixtures.ok(api.get_stability_study(study["id"],
                                                     REGULATORY_AFFAIRS))
        assert reread["last_conforming_month"] is None
        assert reread["status"] == "IN_PROGRESS"

        refused = api.conclude_stability_study(study["id"], REGULATORY_AFFAIRS)
        validate_error(refused, "ERR_STABILITY_STUDY_STATE_INVALID")

    def test_month_zero_exactly_at_the_recovery_floor_conforms(self, api):
        """PRD §3.6: "The server computes `recovery_pct` as `measured_value`
        divided by the study's `baseline_value`, multiplied by 100 and rounded
        half-up to two decimal places, and sets `outcome` to `PASS` when
        `recovery_pct` is at least 90.00 — inclusively — and `FAIL` otherwise."
        PRD §3.6: "It is the largest planned month index such that every planned
        index at or below it has at least one recorded timepoint whose
        `recovery_pct` is at least 90.00."

        Design: Corner/calculations/stability_last_conforming_month_breaks_at_the_first_gap_in_the_planned_prefix
        """
        _, study = self._study_with_planned_months(api, [0, 3], 200.0)

        # 180.0 / 200.0 * 100 = 90.00 exactly, and the floor is inclusive.
        recorded = fixtures.record_timepoint(api, study["id"], 0, 180.0)
        assert float(recorded["recovery_pct"]) == 90.00
        assert recorded["outcome"] == "PASS"

        reread = fixtures.ok(api.get_stability_study(study["id"],
                                                     REGULATORY_AFFAIRS))
        assert reread["last_conforming_month"] == 0, \
            "a record exactly on the floor conforms, so the prefix reaches 0"
        assert reread["timepoint_count"] == 1


class TestComplaintReportability:

    def _complaint_received_on_september_sixth(self, api, **overrides):
        """A complaint against a released lot, booked with the clock parked on a
        known instant so `received_at` is predictable."""
        lot = fixtures.released_reagent_lot(api)["lot"]
        fixtures.set_clock(api, CLOCK_SEP_06)
        complaint = fixtures.create_complaint(api, lot["id"], **overrides)
        assertions.assert_complaint(complaint)
        assertions.assert_same_instant(complaint["received_at"], CLOCK_SEP_06,
                                       "received_at")
        assert complaint["reportable"] is None
        assert complaint["report_due_at"] is None
        return complaint

    def test_a_high_severity_malfunction_takes_the_thirty_day_deadline(self, api):
        """PRD §3.8: "`reportable` is true when `malfunction_suspected` is true
        **and** at least one of the following holds:
        `device_related_death_or_injury` is true, or `severity` is `HIGH`."
        PRD §3.8: "`report_due_at` is `received_at` advanced by 5 days when
        `device_related_death_or_injury` is true and by 30 days otherwise, and it
        is null whenever `reportable` is false."

        Design: Corner/calculations/complaint_reportability_applies_the_thirty_day_deadline_and_the_inclusive_lateness_test
        """
        complaint = self._complaint_received_on_september_sixth(api)

        triaged = fixtures.triage_complaint(api, complaint["id"],
                                            severity="HIGH",
                                            malfunction_suspected=True)
        assert triaged["status"] == "TRIAGED"
        assert triaged["reportable"] is True
        # No death or injury alleged, so the deadline is the 30-day one:
        # 2026-09-06 + 30 days = 2026-09-06 + 24 days (to 2026-09-30) + 6 days.
        assertions.assert_same_instant(triaged["report_due_at"],
                                       "2026-10-06T00:00:00.000Z",
                                       "report_due_at")
        assertions.assert_three_fractional_digits(triaged["report_due_at"],
                                                  "report_due_at")
        assert triaged["report_late"] is None, \
            "lateness is only computed when the report is actually filed"

        reread = fixtures.ok(api.get_complaint(complaint["id"],
                                               REGULATORY_AFFAIRS))
        assert reread["reportable"] is True
        assertions.assert_same_instant(reread["report_due_at"],
                                       "2026-10-06T00:00:00.000Z",
                                       "report_due_at")

    def test_a_report_filed_exactly_at_the_deadline_is_on_time(self, api):
        """PRD §3.8: "Filing stores `report_ref` and stamps `reported_at` from
        the logical clock, then computes `report_late` as true exactly when
        `reported_at` is strictly later than `report_due_at` — a report filed at
        exactly the deadline instant is on time."
        PRD §3.8: "The complaint's `status` becomes `MALFUNCTION_REPORTED` when
        it was `TRIAGED`, and **stays** `FIELD_ACTION_DECIDED` when the other
        branch has already run, so the field-action outcome is never overwritten
        by the report."
        PRD §3.8: "It requires `reportable` to be true and requires the
        complaint's `status` to be either `TRIAGED` or `FIELD_ACTION_DECIDED`; a
        report against a complaint still in `RECEIVED`, or against one already in
        `MALFUNCTION_REPORTED` or `CLOSED`, is refused with
        `ERR_COMPLAINT_STATE_INVALID`."

        Design: Corner/calculations/complaint_reportability_applies_the_thirty_day_deadline_and_the_inclusive_lateness_test
        """
        complaint = self._complaint_received_on_september_sixth(api)
        triaged = fixtures.triage_complaint(api, complaint["id"],
                                            severity="HIGH",
                                            malfunction_suspected=True)
        # 2026-09-06 + 30 days = 2026-10-06T00:00:00.000Z
        deadline = "2026-10-06T00:00:00.000Z"
        assertions.assert_same_instant(triaged["report_due_at"], deadline,
                                       "report_due_at")

        # The clock is parked on the deadline instant itself, and the lateness
        # test is strict, so this report is on time.
        fixtures.set_clock(api, deadline)
        filed = fixtures.file_malfunction_report(api, complaint["id"])
        assertions.assert_same_instant(filed["reported_at"], deadline,
                                       "reported_at")
        assert filed["report_late"] is False
        assert filed["status"] == "MALFUNCTION_REPORTED"
        assert filed["report_ref"] is not None

        reread = fixtures.ok(api.get_complaint(complaint["id"],
                                               REGULATORY_AFFAIRS))
        assert reread["report_late"] is False
        assert reread["status"] == "MALFUNCTION_REPORTED"

        second = api.file_malfunction_report(
            complaint["id"], factories.malfunction_report_payload(),
            REGULATORY_AFFAIRS)
        validate_error(second, "ERR_COMPLAINT_STATE_INVALID")

    def test_a_report_filed_after_the_deadline_is_late(self, api):
        """PRD §3.8: "Filing stores `report_ref` and stamps `reported_at` from
        the logical clock, then computes `report_late` as true exactly when
        `reported_at` is strictly later than `report_due_at` — a report filed at
        exactly the deadline instant is on time."

        Design: Corner/calculations/complaint_reportability_applies_the_thirty_day_deadline_and_the_inclusive_lateness_test
        """
        complaint = self._complaint_received_on_september_sixth(api)
        fixtures.triage_complaint(api, complaint["id"], severity="HIGH",
                                  malfunction_suspected=True)

        # One day past the 2026-10-06 deadline computed above.
        fixtures.set_clock(api, "2026-10-07T00:00:00.000Z")
        filed = fixtures.file_malfunction_report(api, complaint["id"])
        assertions.assert_same_instant(filed["reported_at"],
                                       "2026-10-07T00:00:00.000Z",
                                       "reported_at")
        assert filed["report_late"] is True

        reread = fixtures.ok(api.get_complaint(complaint["id"],
                                               REGULATORY_AFFAIRS))
        assert reread["report_late"] is True

    def test_a_medium_severity_malfunction_is_not_reportable(self, api):
        """PRD §3.8: "A suspected malfunction on a `LOW` or `MEDIUM` complaint
        with no alleged death or injury is therefore not reportable, and neither
        is a `HIGH`-severity complaint whose triage found no malfunction."
        PRD §3.8: "`report_due_at` is `received_at` advanced by 5 days when
        `device_related_death_or_injury` is true and by 30 days otherwise, and it
        is null whenever `reportable` is false."

        Design: Corner/calculations/complaint_reportability_applies_the_thirty_day_deadline_and_the_inclusive_lateness_test
        """
        complaint = self._complaint_received_on_september_sixth(api)

        triaged = fixtures.triage_complaint(api, complaint["id"],
                                            severity="MEDIUM",
                                            malfunction_suspected=True)
        assert triaged["reportable"] is False
        assert triaged["report_due_at"] is None
        assert triaged["severity"] == "MEDIUM"
        assert triaged["malfunction_suspected"] is True

        reread = fixtures.ok(api.get_complaint(complaint["id"],
                                               REGULATORY_AFFAIRS))
        assert reread["reportable"] is False
        assert reread["report_due_at"] is None

    def test_high_severity_without_a_suspected_malfunction_is_not_reportable(self, api):
        """PRD §3.8: "`reportable` is true when `malfunction_suspected` is true
        **and** at least one of the following holds:
        `device_related_death_or_injury` is true, or `severity` is `HIGH`."
        PRD §3.8: "A suspected malfunction on a `LOW` or `MEDIUM` complaint with
        no alleged death or injury is therefore not reportable, and neither is a
        `HIGH`-severity complaint whose triage found no malfunction."

        Design: Corner/calculations/complaint_reportability_applies_the_thirty_day_deadline_and_the_inclusive_lateness_test
        """
        complaint = self._complaint_received_on_september_sixth(api)

        triaged = fixtures.triage_complaint(api, complaint["id"],
                                            severity="HIGH",
                                            malfunction_suspected=False)
        assert triaged["reportable"] is False, \
            "the malfunction conjunct is required whatever the severity"
        assert triaged["report_due_at"] is None

        reread = fixtures.ok(api.get_complaint(complaint["id"],
                                               REGULATORY_AFFAIRS))
        assert reread["reportable"] is False
        assert reread["report_due_at"] is None

    def test_an_alleged_death_or_injury_takes_the_five_day_deadline(self, api):
        """PRD §3.8: "`report_due_at` is `received_at` advanced by 5 days when
        `device_related_death_or_injury` is true and by 30 days otherwise, and it
        is null whenever `reportable` is false."
        PRD §3.8: "`reportable` is true when `malfunction_suspected` is true
        **and** at least one of the following holds:
        `device_related_death_or_injury` is true, or `severity` is `HIGH`."

        Design: Corner/calculations/complaint_reportability_applies_the_thirty_day_deadline_and_the_inclusive_lateness_test
        """
        complaint = self._complaint_received_on_september_sixth(
            api, device_related_death_or_injury=True)
        assert complaint["device_related_death_or_injury"] is True

        # LOW severity, so reportability rests entirely on the alleged injury,
        # and the deadline is 2026-09-06 + 5 days = 2026-09-11T00:00:00.000Z.
        triaged = fixtures.triage_complaint(api, complaint["id"],
                                            severity="LOW",
                                            malfunction_suspected=True)
        assert triaged["reportable"] is True
        assertions.assert_same_instant(triaged["report_due_at"],
                                       "2026-09-11T00:00:00.000Z",
                                       "report_due_at")

        # Filed the day before that deadline, so it is on time.
        fixtures.set_clock(api, "2026-09-10T00:00:00.000Z")
        filed = fixtures.file_malfunction_report(api, complaint["id"])
        assert filed["report_late"] is False
        assert filed["status"] == "MALFUNCTION_REPORTED"


class TestDesignTraceCompleteness:

    def _trace_to_depth_two(self, api):
        """A product specification with an approved design input and an approved
        design output, which is the platform every depth-3 record needs."""
        product = fixtures.create_product_specification(api)
        design_input = fixtures.file_design_record(api, product["id"],
                                                   "DESIGN_INPUT")
        assert design_input["trace_depth"] == 1
        assert design_input["traces_to_record_id"] is None
        design_output = fixtures.file_design_record(
            api, product["id"], "DESIGN_OUTPUT",
            traces_to_record_id=design_input["id"])
        # one more than the input's depth of 1
        assert design_output["trace_depth"] == 2
        fixtures.approve_design_record(api, design_input["id"])
        fixtures.approve_design_record(api, design_output["id"])
        return product, design_input, design_output

    def test_an_approved_verification_alone_leaves_the_trace_incomplete(self, api):
        """PRD §3.2: "From those links the server computes `trace_depth`: 1 for a
        `DESIGN_INPUT`, and otherwise one more than the `trace_depth` of the
        record named by `traces_to_record_id`."
        PRD §3.2: "A design output therefore always sits at depth 2, and a
        verification or validation always at depth 3."
        PRD §3.2: "Looking only at records on this product specification whose
        `status` is `APPROVED` — `DRAFT` and `SUPERSEDED` records are excluded
        entirely — the flag `design_trace_complete` becomes true when there is at
        least one record with `record_type` `VERIFICATION` at `trace_depth` 3
        **and** at least one record with `record_type` `VALIDATION` at
        `trace_depth` 3."
        PRD §3.2: "A `RegulatoryAffairs` user records it by supplying the
        `submission_ref`, and the request is admitted only when the
        specification's `clearance_status` is `DESIGN` — clearance on an already
        `CLEARED` or `WITHDRAWN` product is refused with
        `ERR_PRODUCT_STATE_INVALID` — and only when `design_trace_complete` is
        true, failing which the answer is `ERR_DESIGN_TRACE_INCOMPLETE`."

        Design: Corner/calculations/design_trace_completeness_needs_an_approved_verification_and_an_approved_validation_at_depth_three
        """
        product, _, design_output = self._trace_to_depth_two(api)

        verification = fixtures.file_design_record(
            api, product["id"], "VERIFICATION",
            traces_to_record_id=design_output["id"])
        assertions.assert_design_control_record(verification)
        # one more than the output's depth of 2
        assert verification["trace_depth"] == 3
        approved = fixtures.approve_design_record(api, verification["id"])
        assert approved["status"] == "APPROVED"

        reread = fixtures.ok(api.get_product_specification(product["id"],
                                                           REGULATORY_AFFAIRS))
        assert reread["design_trace_complete"] is False, \
            "the validation half of the conjunction is still missing"
        assert reread["clearance_status"] == "DESIGN"

        refused = api.record_product_clearance(product["id"],
                                               factories.clearance_payload(),
                                               REGULATORY_AFFAIRS)
        validate_error(refused, "ERR_DESIGN_TRACE_INCOMPLETE")

    def test_two_approved_verifications_do_not_complete_the_trace(self, api):
        """PRD §3.2: "Both conditions must hold simultaneously; a file with two
        approved verifications and no approved validation is not complete."
        PRD §3.2: "Looking only at records on this product specification whose
        `status` is `APPROVED` — `DRAFT` and `SUPERSEDED` records are excluded
        entirely — the flag `design_trace_complete` becomes true when there is at
        least one record with `record_type` `VERIFICATION` at `trace_depth` 3
        **and** at least one record with `record_type` `VALIDATION` at
        `trace_depth` 3."

        Design: Corner/calculations/design_trace_completeness_needs_an_approved_verification_and_an_approved_validation_at_depth_three
        """
        product, _, design_output = self._trace_to_depth_two(api)

        for _ in range(2):
            verification = fixtures.file_design_record(
                api, product["id"], "VERIFICATION",
                traces_to_record_id=design_output["id"])
            assert verification["trace_depth"] == 3
            fixtures.approve_design_record(api, verification["id"])

        reread = fixtures.ok(api.get_product_specification(product["id"],
                                                           REGULATORY_AFFAIRS))
        assert reread["design_trace_complete"] is False, \
            "two of one kind never substitute for one of each"

    def test_a_draft_validation_completes_the_trace_only_once_approved(self, api):
        """PRD §3.2: "Looking only at records on this product specification whose
        `status` is `APPROVED` — `DRAFT` and `SUPERSEDED` records are excluded
        entirely — the flag `design_trace_complete` becomes true when there is at
        least one record with `record_type` `VERIFICATION` at `trace_depth` 3
        **and** at least one record with `record_type` `VALIDATION` at
        `trace_depth` 3."
        PRD §3.2: "A successful approval recomputes the parent's
        `design_trace_complete` flag and increases the parent product
        specification's `version` by 1."
        PRD §3.2: "On success `clearance_status` becomes `CLEARED`,
        `submission_ref` and `cleared_at` are stored, and `version` increases by
        1."

        Design: Corner/calculations/design_trace_completeness_needs_an_approved_verification_and_an_approved_validation_at_depth_three
        """
        product, _, design_output = self._trace_to_depth_two(api)
        verification = fixtures.file_design_record(
            api, product["id"], "VERIFICATION",
            traces_to_record_id=design_output["id"])
        fixtures.approve_design_record(api, verification["id"])

        validation = fixtures.file_design_record(
            api, product["id"], "VALIDATION",
            traces_to_record_id=design_output["id"])
        assert validation["trace_depth"] == 3
        assert validation["status"] == "DRAFT"

        with_draft = fixtures.ok(api.get_product_specification(
            product["id"], REGULATORY_AFFAIRS))
        assert with_draft["design_trace_complete"] is False, \
            "a DRAFT validation is excluded from the computation entirely"

        fixtures.approve_design_record(api, validation["id"])
        complete = fixtures.ok(api.get_product_specification(
            product["id"], REGULATORY_AFFAIRS))
        assert complete["design_trace_complete"] is True

        cleared = fixtures.ok(api.record_product_clearance(
            product["id"], factories.clearance_payload(), REGULATORY_AFFAIRS))
        assert cleared["clearance_status"] == "CLEARED"
        assert cleared["cleared_at"] is not None
        assert cleared["submission_ref"] is not None

    def test_a_validation_tracing_to_the_design_input_is_refused(self, api):
        """PRD §3.2: "The traceability rules are strict and are enforced
        together: `traces_to_record_id` must be null exactly when `record_type`
        is `DESIGN_INPUT` and non-null otherwise, a `DESIGN_OUTPUT` must trace to
        a `DESIGN_INPUT`, a `VERIFICATION` or a `VALIDATION` must trace to a
        `DESIGN_OUTPUT`, and the predecessor must belong to the same
        `product_specification_id`."
        PRD §3.2: "Any breach — a null link on a non-input record, a link set on
        a design input, a link to the wrong predecessor type, or a link reaching
        across product specifications — is refused with `ERR_INVALID_TRACE_LINK`
        and HTTP 422."

        Design: Corner/calculations/design_trace_completeness_needs_an_approved_verification_and_an_approved_validation_at_depth_three
        """
        product, design_input, design_output = self._trace_to_depth_two(api)
        verification = fixtures.file_design_record(
            api, product["id"], "VERIFICATION",
            traces_to_record_id=design_output["id"])
        fixtures.approve_design_record(api, verification["id"])

        # A validation must trace to a design output; linking it to the design
        # input would put it at depth 2 and is refused outright.
        expected_version = fixtures.product_specification_version(
            api, product["id"])
        refused = api.create_design_control_record(
            factories.design_control_record_payload(
                product["id"], "VALIDATION", expected_version,
                traces_to_record_id=design_input["id"]),
            REGULATORY_AFFAIRS)
        validate_error(refused, "ERR_INVALID_TRACE_LINK", 422)

        reread = fixtures.ok(api.get_product_specification(product["id"],
                                                           REGULATORY_AFFAIRS))
        assert reread["design_trace_complete"] is False


class TestBridgingRequirement:

    def test_the_first_lot_of_a_product_never_needs_bridging(self, api):
        """PRD §3.7: "The flag `bridging_required` is recomputed twice in a lot's
        life — each time a component is dispensed into it, and again when a
        filling run on it completes — and it is derived as follows."
        PRD §3.7: "First the system identifies the **predicate lot**: among
        finished lots sharing this lot's `product_specification_id`, excluding
        this lot itself, and whose `disposition_status` is `RELEASED`, it ranks by
        `released_at` descending with `created_at` descending as the tie-break and
        takes the first."
        PRD §3.7: "If no such lot exists, `bridging_required` is false — the first
        commercial lot of a product has nothing to be consistent with."

        Design: Corner/calculations/bridging_requirement_ignores_unreleased_lots_when_it_picks_the_predicate
        """
        setup, original, _ = _critical_product_with_two_vendor_lots(api)

        lot, row = _lot_from_material(api, setup["product"]["id"],
                                     original["id"])
        assertions.assert_reagent_lot(lot)
        assert row["status"] == "CONSUMED"
        assert lot["bridging_required"] is False, \
            "no released sibling exists, so there is no predicate to compare to"

        filled = _fill_and_complete(api, lot["id"])
        assert filled["disposition_status"] == "FILLED"
        assert filled["bridging_required"] is False, \
            "the recomputation on run completion reaches the same verdict"

    def test_a_changed_vendor_lot_of_a_critical_material_needs_bridging(self, api):
        """PRD §3.7: "`bridging_required` becomes true when at least one of those
        critical components meets either of two conditions: the predicate lot has
        no `CONSUMED` dispensing row filling the same `component_role`, or the
        predicate lot's row for that same `component_role` carries a different
        `vendor_lot_code_snapshot` than this component does."
        PRD §3.3: "Each successful call creates a dispensing row whose
        `reagent_lot_id` points at the finished lot, whose `status` starts as
        `CONSUMED`, and whose two snapshot fields are copied at creation time:
        `material_code_snapshot` takes the `material_code` of the consumed lot's
        specification, and `vendor_lot_code_snapshot` takes the consumed lot's
        `vendor_lot_code`."

        Design: Corner/calculations/bridging_requirement_ignores_unreleased_lots_when_it_picks_the_predicate
        """
        setup, original, changed = _critical_product_with_two_vendor_lots(api)
        predicate = fixtures.released_reagent_lot(api, setup=setup)["lot"]
        assert predicate["disposition_status"] == "RELEASED"
        assert predicate["bridging_required"] is False

        candidate, row = _lot_from_material(api, setup["product"]["id"],
                                           changed["id"])
        assert row["vendor_lot_code_snapshot"] == changed["vendor_lot_code"]
        assert changed["vendor_lot_code"] != original["vendor_lot_code"]
        assert candidate["bridging_required"] is True, \
            "the ANTIBODY role now carries a different vendor lot code"

        filled = _fill_and_complete(api, candidate["id"])
        assert filled["bridging_required"] is True

    def test_a_lot_needing_bridging_cannot_be_released_without_a_study(self, api):
        """PRD §3.5: "For a release the remaining gates are evaluated in this
        exact order, so an operator always learns about the most serious defect
        first: no run of the lot may have `environmental_state` `DISQUALIFIED`
        (`ERR_ENVIRONMENTAL_NONCONFORMANCE`); every code in `release_test_codes`
        must have a measurement on the lot whose `outcome` is `PASS`
        (`ERR_RELEASE_TESTS_INCOMPLETE`); `release_bias_max_pct` must be at most
        `max_reference_bias_pct`, inclusively (`ERR_REFERENCE_BIAS_EXCEEDED`);
        every code in the product's `required_material_codes` must appear as the
        `material_code_snapshot` of a dispensing row of this lot whose `status` is
        `CONSUMED` (`ERR_BOM_INCOMPLETE`); when `bridging_required` is true a
        bridging study naming this lot as its candidate must exist in `status`
        `APPROVED` (`ERR_BRIDGING_REQUIRED`); when the requested
        `shelf_life_basis` is `REAL_TIME` or `ACCELERATED` a stability study on
        this product with that `study_type`, `status` `COMPLETE` and a non-null
        `established_shelf_life_months` must exist (`ERR_STABILITY_DATA_MISSING`);
        and last of all, the product's `clearance_status` must be `CLEARED`
        (`ERR_PRODUCT_NOT_CLEARED`)."
        PRD §3.5: "The first release measurement on a `FILLED` lot advances its
        `disposition_status` from `FILLED` to `UNDER_RELEASE_TEST`; each
        subsequent release measurement is a self-loop on `UNDER_RELEASE_TEST`."

        Design: Corner/calculations/bridging_requirement_ignores_unreleased_lots_when_it_picks_the_predicate
        """
        setup, _, changed = _critical_product_with_two_vendor_lots(api)
        fixtures.released_reagent_lot(api, setup=setup)

        candidate, _ = _lot_from_material(api, setup["product"]["id"],
                                          changed["id"])
        _fill_and_complete(api, candidate["id"])
        fixtures.record_passing_release_tests(api, candidate["id"],
                                              setup["product"])

        under_test = fixtures.ok(api.get_reagent_lot(candidate["id"],
                                                     QA_RELEASER))
        assert under_test["disposition_status"] == "UNDER_RELEASE_TEST"
        assert under_test["bridging_required"] is True

        refused = api.disposition_reagent_lot(
            candidate["id"], factories.reagent_lot_disposition_payload("RELEASE"),
            QA_RELEASER)
        validate_error(refused, "ERR_BRIDGING_REQUIRED")

        reread = fixtures.ok(api.get_reagent_lot(candidate["id"], QA_RELEASER))
        assert reread["disposition_status"] == "UNDER_RELEASE_TEST"
        assert reread["distribution_status"] == "WITHHELD"

    def test_an_unreleased_sibling_is_ignored_when_the_predicate_is_picked(self, api):
        """PRD §3.7: "First the system identifies the **predicate lot**: among
        finished lots sharing this lot's `product_specification_id`, excluding
        this lot itself, and whose `disposition_status` is `RELEASED`, it ranks by
        `released_at` descending with `created_at` descending as the tie-break and
        takes the first."
        PRD §3.7: "`bridging_required` becomes true when at least one of those
        critical components meets either of two conditions: the predicate lot has
        no `CONSUMED` dispensing row filling the same `component_role`, or the
        predicate lot's row for that same `component_role` carries a different
        `vendor_lot_code_snapshot` than this component does."

        Design: Corner/calculations/bridging_requirement_ignores_unreleased_lots_when_it_picks_the_predicate
        """
        setup, original, changed = _critical_product_with_two_vendor_lots(api)
        predicate = fixtures.released_reagent_lot(api, setup=setup)["lot"]
        assert predicate["disposition_status"] == "RELEASED"

        # A more recent sibling on the *changed* vendor lot, carried only as far
        # as FILLED — it is never released, so it can never be the predicate.
        interloper, _ = _lot_from_material(api, setup["product"]["id"],
                                          changed["id"])
        interloper = _fill_and_complete(api, interloper["id"])
        assert interloper["disposition_status"] == "FILLED"
        assert interloper["bridging_required"] is True

        # A third lot built from the same vendor lot the released predicate used.
        third, row = _lot_from_material(api, setup["product"]["id"],
                                        original["id"])
        assert row["vendor_lot_code_snapshot"] == original["vendor_lot_code"]
        assert third["bridging_required"] is False, \
            "the comparison runs against the released lot, not the newest one"

        filled = _fill_and_complete(api, third["id"])
        assert filled["bridging_required"] is False


class TestBridgingEquivalence:

    PAIRED_CODES = ["ACTIVITY", "CALIBRATION_SLOPE"]

    def _paired_lots(self, api):
        """A predicate lot and a candidate lot of the same product, both
        `FILLED`, plus the changed raw material lot the candidate was built from.

        The product's release test codes are the two codes these tests pair, and
        its reference-bias tolerance is wide enough that no measurement is
        rejected on its own account.
        """
        setup = fixtures.manufacturing_setup(
            api, material_types=("ANTIBODY",), critical_types=("ANTIBODY",),
            product_overrides={"release_test_codes": list(self.PAIRED_CODES),
                               "max_reference_bias_pct": 10.0})
        changed = fixtures.qualified_material_lot_for_spec(
            api, setup["materials"][0]["spec"])
        predicate = fixtures.filled_reagent_lot(api, setup=setup)["lot"]
        candidate, _ = _lot_from_material(api, setup["product"]["id"],
                                          changed["id"])
        candidate = _fill_and_complete(api, candidate["id"])
        return setup, changed, predicate, candidate

    def _measure_predicate_at_one_hundred(self, api, predicate_id):
        """One release measurement per paired code on the predicate lot, each at
        100.0 against a reference of 100.0, so the pairing arithmetic below has a
        clean denominator."""
        for test_code in self.PAIRED_CODES:
            fixtures.record_release_measurement(api, predicate_id, test_code,
                                                100.0, 100.0)

    def test_equivalence_holds_exactly_on_both_inclusive_limits(self, api):
        """PRD §3.7: "Otherwise the paired bias for that code is the absolute
        difference between the candidate's `measured_value` and the predicate's
        `measured_value`, divided by the predicate's `measured_value`, multiplied
        by 100, and rounded half-up to two decimal places."
        PRD §3.7: "`max_bias_pct` is the largest of those rounded per-code
        biases."
        PRD §3.7: "`mean_bias_pct` is the sum of the **already rounded** per-code
        biases divided by the number of codes, with the quotient itself rounded
        half-up to two decimal places — rounding happens once per code before the
        mean and once more on the mean."
        PRD §3.7: "`equivalence_verdict` becomes `EQUIVALENT` when
        `mean_bias_pct` is at most 3.00 **and** `max_bias_pct` is at most 5.00,
        both boundaries inclusive, and `NOT_EQUIVALENT` when either threshold is
        exceeded."

        Design: Corner/calculations/bridging_equivalence_is_inclusive_at_both_limits_and_recomputes_on_the_latest_paired_result
        """
        setup, changed, predicate, candidate = self._paired_lots(api)
        self._measure_predicate_at_one_hundred(api, predicate["id"])
        # ACTIVITY:          |101.0 - 100.0| / 100.0 * 100 = 1.00
        # CALIBRATION_SLOPE: |105.0 - 100.0| / 100.0 * 100 = 5.00
        fixtures.record_release_measurement(api, candidate["id"], "ACTIVITY",
                                            101.0, 100.0)
        fixtures.record_release_measurement(api, candidate["id"],
                                            "CALIBRATION_SLOPE", 105.0, 100.0)

        study = fixtures.create_bridging_study(
            api, predicate["id"], candidate["id"], changed["id"],
            paired_test_codes=list(self.PAIRED_CODES))
        assertions.assert_bridging_study(study)
        assert study["status"] == "DRAFT"
        # max of {1.00, 5.00} = 5.00, exactly on the inclusive max limit
        assert float(study["max_bias_pct"]) == 5.00
        # (1.00 + 5.00) / 2 = 3.00, exactly on the inclusive mean limit
        assert float(study["mean_bias_pct"]) == 3.00
        assert study["equivalence_verdict"] == "EQUIVALENT"

        approved = fixtures.decide_bridging_study(api, study["id"], "APPROVE")
        assert approved["status"] == "APPROVED"
        assert approved["decided_at"] is not None

        reread = fixtures.ok(api.get_bridging_study(study["id"], QA_RELEASER))
        assert reread["equivalence_verdict"] == "EQUIVALENT"
        assert float(reread["mean_bias_pct"]) == 3.00
        assert float(reread["max_bias_pct"]) == 5.00

    def test_a_later_paired_result_recomputes_the_verdict(self, api):
        """PRD §3.7: "For each code in `paired_test_codes`, the system takes the
        latest release measurement on the predicate lot bearing that code and the
        latest release measurement on the candidate lot bearing that code, each
        ranked by `performed_at` descending with `created_at` descending as the
        tie-break."
        PRD §3.7: "Because these figures are re-derived on every new release
        measurement on either linked lot, a bridge can move from `PENDING` to a
        real verdict without anybody touching the study."
        PRD §3.7: "Then `equivalence_verdict` must actually be `EQUIVALENT`; a
        verdict of `NOT_EQUIVALENT` yields `ERR_NOT_EQUIVALENT` with HTTP 409."

        Design: Corner/calculations/bridging_equivalence_is_inclusive_at_both_limits_and_recomputes_on_the_latest_paired_result
        """
        setup, changed, predicate, candidate = self._paired_lots(api)
        self._measure_predicate_at_one_hundred(api, predicate["id"])
        fixtures.record_release_measurement(api, candidate["id"], "ACTIVITY",
                                            101.0, 100.0)
        fixtures.record_release_measurement(api, candidate["id"],
                                            "CALIBRATION_SLOPE", 105.0, 100.0)

        study = fixtures.create_bridging_study(
            api, predicate["id"], candidate["id"], changed["id"],
            paired_test_codes=list(self.PAIRED_CODES))
        assert study["equivalence_verdict"] == "EQUIVALENT"

        # A retest of ACTIVITY on the candidate, performed a day later so it is
        # unambiguously the latest measurement for that code.
        fixtures.set_clock(api, CLOCK_AUG_21)
        fixtures.record_release_measurement(api, candidate["id"], "ACTIVITY",
                                            101.1, 100.0)
        # ACTIVITY now:      |101.1 - 100.0| / 100.0 * 100 = 1.10
        # CALIBRATION_SLOPE: |105.0 - 100.0| / 100.0 * 100 = 5.00
        # mean = (1.10 + 5.00) / 2 = 3.05, which exceeds the 3.00 limit, while
        # max = 5.00 still sits exactly on its own inclusive limit.
        recomputed = fixtures.ok(api.get_bridging_study(study["id"],
                                                        QA_RELEASER))
        assert float(recomputed["mean_bias_pct"]) == 3.05
        assert float(recomputed["max_bias_pct"]) == 5.00
        assert recomputed["equivalence_verdict"] == "NOT_EQUIVALENT"
        assert recomputed["status"] == "DRAFT"

        refused = api.decide_bridging_study(
            study["id"], factories.bridging_decision_payload("APPROVE"),
            QA_RELEASER)
        validate_error(refused, "ERR_NOT_EQUIVALENT", 409)

        still_draft = fixtures.ok(api.get_bridging_study(study["id"],
                                                         QA_RELEASER))
        assert still_draft["status"] == "DRAFT"
        assert still_draft["decided_at"] is None

    def test_the_max_limit_alone_can_defeat_equivalence(self, api):
        """PRD §3.7: "`equivalence_verdict` becomes `EQUIVALENT` when
        `mean_bias_pct` is at most 3.00 **and** `max_bias_pct` is at most 5.00,
        both boundaries inclusive, and `NOT_EQUIVALENT` when either threshold is
        exceeded."
        PRD §3.7: "`mean_bias_pct` is the sum of the **already rounded** per-code
        biases divided by the number of codes, with the quotient itself rounded
        half-up to two decimal places — rounding happens once per code before the
        mean and once more on the mean."

        Design: Corner/calculations/bridging_equivalence_is_inclusive_at_both_limits_and_recomputes_on_the_latest_paired_result
        """
        setup, changed, predicate, candidate = self._paired_lots(api)
        self._measure_predicate_at_one_hundred(api, predicate["id"])
        # ACTIVITY:          |100.0 - 100.0|  / 100.0 * 100 = 0.00
        # CALIBRATION_SLOPE: |105.02 - 100.0| / 100.0 * 100 = 5.02
        fixtures.record_release_measurement(api, candidate["id"], "ACTIVITY",
                                            100.0, 100.0)
        fixtures.record_release_measurement(api, candidate["id"],
                                            "CALIBRATION_SLOPE", 105.02, 100.0)

        study = fixtures.create_bridging_study(
            api, predicate["id"], candidate["id"], changed["id"],
            paired_test_codes=list(self.PAIRED_CODES))
        # mean = (0.00 + 5.02) / 2 = 2.51, comfortably inside the 3.00 limit,
        # but max = 5.02 is past 5.00 by two hundredths.
        assert float(study["mean_bias_pct"]) == 2.51
        assert float(study["max_bias_pct"]) == 5.02
        assert study["equivalence_verdict"] == "NOT_EQUIVALENT", \
            "either threshold on its own is enough to deny equivalence"

        refused = api.decide_bridging_study(
            study["id"], factories.bridging_decision_payload("APPROVE"),
            QA_RELEASER)
        validate_error(refused, "ERR_NOT_EQUIVALENT", 409)

    def test_a_missing_paired_code_leaves_the_verdict_pending(self, api):
        """PRD §3.7: "If either side is missing for any code,
        `equivalence_verdict` is `PENDING` and no bias figures are established."
        PRD §3.7: "Every code in `paired_test_codes` must have a latest release
        measurement on **both** the predicate and the candidate lot, so that
        `equivalence_verdict` is not `PENDING`; a gap yields
        `ERR_PAIRED_DATA_MISSING` with HTTP 422."

        Design: Corner/calculations/bridging_equivalence_is_inclusive_at_both_limits_and_recomputes_on_the_latest_paired_result
        """
        setup, changed, predicate, candidate = self._paired_lots(api)
        self._measure_predicate_at_one_hundred(api, predicate["id"])
        # The candidate is measured on one of the two paired codes only.
        fixtures.record_release_measurement(api, candidate["id"], "ACTIVITY",
                                            101.0, 100.0)

        study = fixtures.create_bridging_study(
            api, predicate["id"], candidate["id"], changed["id"],
            paired_test_codes=list(self.PAIRED_CODES))
        assert study["equivalence_verdict"] == "PENDING"

        refused = api.decide_bridging_study(
            study["id"], factories.bridging_decision_payload("APPROVE"),
            QA_RELEASER)
        validate_error(refused, "ERR_PAIRED_DATA_MISSING", 422)

        still_draft = fixtures.ok(api.get_bridging_study(study["id"],
                                                         QA_RELEASER))
        assert still_draft["status"] == "DRAFT"
        assert still_draft["equivalence_verdict"] == "PENDING"

        # Supplying the missing half of the pair moves the verdict on its own:
        # ACTIVITY 1.00 and CALIBRATION_SLOPE |102.0 - 100.0| / 100.0 * 100 =
        # 2.00, so max = 2.00 and mean = (1.00 + 2.00) / 2 = 1.50.
        fixtures.record_release_measurement(api, candidate["id"],
                                            "CALIBRATION_SLOPE", 102.0, 100.0)
        resolved = fixtures.ok(api.get_bridging_study(study["id"], QA_RELEASER))
        assert float(resolved["max_bias_pct"]) == 2.00
        assert float(resolved["mean_bias_pct"]) == 1.50
        assert resolved["equivalence_verdict"] == "EQUIVALENT"


class TestReagentLotExpiry:

    def _released_lot_filled_at(self, api, instant, shelf_life_months_claim,
                                shelf_life_basis=None):
        """A finished lot released with the clock parked on ``instant``, so
        `fill_completed_at` is exactly that instant."""
        setup = fixtures.manufacturing_setup(
            api, product_overrides={
                "shelf_life_months_claim": shelf_life_months_claim})
        fixtures.set_clock(api, instant)
        bundle = fixtures.released_reagent_lot(
            api, setup=setup, shelf_life_basis=shelf_life_basis)
        lot = bundle["lot"]
        assert lot["disposition_status"] == "RELEASED"
        assertions.assert_same_instant(lot["fill_completed_at"], instant,
                                       "fill_completed_at")
        return lot

    def test_expiry_clamps_the_day_of_month_and_keeps_the_time_of_day(self, api):
        """PRD §3.5: "From those, `expiry_date` is computed as
        `fill_completed_at` advanced by `assigned_shelf_life_months` calendar
        months: the day-of-month is preserved, and where the source day does not
        exist in the target month the date clamps to the last day of that month;
        the time-of-day is preserved and the instant is rendered in ISO 8601 UTC
        with three fractional digits."
        PRD §3.5: "When `shelf_life_basis` is `CLAIM`, `assigned_shelf_life_months`
        takes the product's `shelf_life_months_claim` and
        `shelf_life_basis_study_id` stays null."
        PRD §3.5: "Hop 2: because the lot became `RELEASED`, its
        `distribution_status` moves from `WITHHELD` to `AVAILABLE` automatically,
        without a second request."

        Design: Corner/calculations/reagent_lot_expiry_clamps_the_day_of_month_and_keeps_the_time_of_day
        """
        filled_at = "2026-08-31T10:30:00.000Z"
        lot = self._released_lot_filled_at(api, filled_at, 6,
                                          shelf_life_basis="CLAIM")

        assert lot["shelf_life_basis"] == "CLAIM"
        assert lot["assigned_shelf_life_months"] == 6
        assert lot["shelf_life_basis_study_id"] is None

        # 2026-08-31 advanced by 6 calendar months lands on 2027-02-31, which
        # does not exist: February 2027 has 28 days (2027 is not a leap year), so
        # the date clamps to the 28th and the 10:30 time-of-day is untouched.
        expected = "2027-02-28T10:30:00.000Z"
        assert constants.add_calendar_months(filled_at, 6) == expected
        assertions.assert_same_instant(lot["expiry_date"], expected,
                                       "expiry_date")
        assertions.assert_three_fractional_digits(lot["expiry_date"],
                                                  "expiry_date")
        assert lot["distribution_status"] == "AVAILABLE"

        reread = fixtures.ok(api.get_reagent_lot(lot["id"], QA_RELEASER))
        assertions.assert_same_instant(reread["expiry_date"], expected,
                                       "expiry_date")
        assert reread["distribution_status"] == "AVAILABLE"

    def test_an_existing_day_of_month_is_preserved_under_the_default_basis(self, api):
        """PRD §3.5: "A `QAReleaser` dispositions the finished lot with a
        `decision` of either `RELEASE` or `REJECT`, an optional `reason`, and —
        for a release — an optional `shelf_life_basis` of `CLAIM`, `REAL_TIME` or
        `ACCELERATED`; when `shelf_life_basis` is omitted the basis is `CLAIM`."
        PRD §3.5: "From those, `expiry_date` is computed as `fill_completed_at`
        advanced by `assigned_shelf_life_months` calendar months: the day-of-month
        is preserved, and where the source day does not exist in the target month
        the date clamps to the last day of that month; the time-of-day is
        preserved and the instant is rendered in ISO 8601 UTC with three
        fractional digits."

        Design: Corner/calculations/reagent_lot_expiry_clamps_the_day_of_month_and_keeps_the_time_of_day
        """
        filled_at = "2026-08-28T10:30:00.000Z"
        # shelf_life_basis is omitted from the release payload entirely.
        lot = self._released_lot_filled_at(api, filled_at, 6)

        assert lot["shelf_life_basis"] == "CLAIM"
        assert lot["assigned_shelf_life_months"] == 6
        assert lot["shelf_life_basis_study_id"] is None

        # The 28th exists in February 2027, so no clamping is involved and the
        # day-of-month carries straight across.
        expected = "2027-02-28T10:30:00.000Z"
        assert constants.add_calendar_months(filled_at, 6) == expected
        assertions.assert_same_instant(lot["expiry_date"], expected,
                                       "expiry_date")
        assertions.assert_three_fractional_digits(lot["expiry_date"],
                                                  "expiry_date")

    def test_expiry_clamps_to_the_leap_day_when_the_target_february_has_one(self, api):
        """PRD §3.5: "From those, `expiry_date` is computed as
        `fill_completed_at` advanced by `assigned_shelf_life_months` calendar
        months: the day-of-month is preserved, and where the source day does not
        exist in the target month the date clamps to the last day of that month;
        the time-of-day is preserved and the instant is rendered in ISO 8601 UTC
        with three fractional digits."
        PRD §3.5: "When `shelf_life_basis` is `CLAIM`, `assigned_shelf_life_months`
        takes the product's `shelf_life_months_claim` and
        `shelf_life_basis_study_id` stays null."

        Design: Corner/calculations/reagent_lot_expiry_clamps_the_day_of_month_and_keeps_the_time_of_day
        """
        filled_at = "2026-08-31T10:30:00.000Z"
        lot = self._released_lot_filled_at(api, filled_at, 18,
                                          shelf_life_basis="CLAIM")

        assert lot["assigned_shelf_life_months"] == 18

        # 2026-08-31 advanced by 18 calendar months lands on 2028-02-31; February
        # 2028 has 29 days because 2028 is a leap year, so the clamp stops at the
        # 29th rather than the 28th, and 10:30 is preserved.
        expected = "2028-02-29T10:30:00.000Z"
        assert constants.add_calendar_months(filled_at, 18) == expected
        assertions.assert_same_instant(lot["expiry_date"], expected,
                                       "expiry_date")
        assertions.assert_three_fractional_digits(lot["expiry_date"],
                                                  "expiry_date")
