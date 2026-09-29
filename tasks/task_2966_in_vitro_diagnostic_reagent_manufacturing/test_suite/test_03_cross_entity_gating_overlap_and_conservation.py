"""Gates that read the state of a neighbouring entity, the two occupation
boundaries, and the two ledgers that a compensation must restore exactly.

Four themes live here, all of them reading or restoring state that does not
belong to the row being written:

* a finished lot's release decision reading its parent product's clearance;
* a dispensing call reading the drawn raw material lot's qualification;
* the closed filling-line interval with its 120-minute changeover buffer versus
  the half-open stability-chamber interval with aggregate capacity 2;
* the raw material ledger restored by an aborted filling run, and the
  finished-goods ledger restored by a cancelled reservation, each exercised over
  two consecutive cycles so that any drift would accumulate visibly.
"""
from prd_bench_local_runner.testing import (validate_error, validate_paginated,
                                            validate_success)

from test_helpers import assertions, constants, factories as f, fixtures
from test_helpers.test_users import (DISTRIBUTION_PLANNER, PRODUCTION_OPERATOR,
                                     QA_RELEASER, QC_ANALYST,
                                     REGULATORY_AFFAIRS)

# ---------------------------------------------------------------------------
# Filling-line probe interval.  The blocking run occupies the closed interval
# 2026-08-10T06:00 .. 2026-08-10T10:00, which is nine days and six hours after
# the logical clock's untouched reading of 2026-08-01T00:00:00.000Z.
# ---------------------------------------------------------------------------
_BLOCKER_START = constants.clock_plus(days=9, hours=6)
_BLOCKER_END = constants.clock_plus(days=9, hours=10)
# 11:00 leaves a 60-minute gap after the blocker ends, inside the buffer.
_GAP_60_START = constants.clock_plus(days=9, hours=11)
_GAP_60_END = constants.clock_plus(days=9, hours=13)
# 12:00 is exactly two hours after the blocker ends.
_GAP_120_START = constants.clock_plus(days=9, hours=12)
_GAP_120_END = constants.clock_plus(days=9, hours=14)
# 04:01 ends one minute inside the buffer that leads into the blocker.
_LEAD_119_START = constants.clock_plus(days=9, hours=2)
_LEAD_119_END = constants.clock_plus(days=9, hours=4, minutes=1)
# 04:00 ends exactly two hours before the blocker starts.
_LEAD_120_START = constants.clock_plus(days=9, hours=2)
_LEAD_120_END = constants.clock_plus(days=9, hours=4)

# ---------------------------------------------------------------------------
# Stability-chamber probe intervals.  Two live protocols saturate the chamber
# over October and November; the half-open reading is what makes December free.
# ---------------------------------------------------------------------------
_STUDY_A_START = "2026-09-01T00:00:00.000Z"
_STUDY_A_END = "2026-12-01T00:00:00.000Z"
_STUDY_B_START = "2026-10-01T00:00:00.000Z"
_STUDY_B_END = "2027-01-01T00:00:00.000Z"
# November sits inside both live protocols.
_NOVEMBER_START = "2026-11-01T00:00:00.000Z"
_NOVEMBER_END = "2026-11-15T00:00:00.000Z"
# A second, disjoint probe that also sits inside both live protocols.
_LATE_NOVEMBER_START = "2026-11-20T00:00:00.000Z"
_LATE_NOVEMBER_END = "2026-11-30T00:00:00.000Z"
# Starts at exactly the instant protocol A ends.
_DECEMBER_START = "2026-12-01T00:00:00.000Z"
_DECEMBER_END = "2026-12-15T00:00:00.000Z"
# Sits inside December, where protocol B and the December protocol both live.
_MID_DECEMBER_START = "2026-12-05T00:00:00.000Z"
_MID_DECEMBER_END = "2026-12-10T00:00:00.000Z"
# Starts at exactly the instant protocol B ends.
_JANUARY_START = "2027-01-01T00:00:00.000Z"
_JANUARY_END = "2027-03-01T00:00:00.000Z"


def _trace_complete_uncleared_setup(api, *, claim_months: int) -> dict:
    """One qualified raw material lot plus a product whose design history file
    is complete and approved but whose clearance has never been recorded."""
    setup = fixtures.manufacturing_setup(
        api, cleared=False,
        product_overrides={"shelf_life_months_claim": claim_months})
    setup["records"] = fixtures.design_history_file(api, setup["product"]["id"])
    setup["product"] = fixtures.ok(api.get_product_specification(
        setup["product"]["id"], REGULATORY_AFFAIRS))
    return setup


def _lot_and_unqualified_material(api, *, received_quantity_units: float) -> dict:
    """A finished lot open for dispensing, and one raw material lot still in
    `RECEIVED` whose material code is in the product's bill of materials."""
    spec = fixtures.create_material_specification(
        api, material_type="ENZYME", required_test_codes=["POTENCY"])
    material_lot = fixtures.create_material_lot(
        api, spec["id"], received_quantity_units=received_quantity_units)
    product = fixtures.create_product_specification(
        api, required_material_codes=[spec["material_code"]])
    lot = fixtures.create_reagent_lot(api, product["id"])
    return {"spec": spec, "material_lot": material_lot, "product": product,
            "lot": lot}


def _lot_with_line(api):
    """A finished lot with no filling run yet, for occupying a line with."""
    product = fixtures.create_product_specification(api)
    return fixtures.create_reagent_lot(api, product["id"])


def _lot_for_chamber(api) -> dict:
    """A finished lot and its product, for placing stability protocols on."""
    product = fixtures.create_product_specification(api)
    lot = fixtures.create_reagent_lot(api, product["id"])
    return {"product": product, "lot": lot}


class TestFinishedLotReleaseGatedOnParentProductClearance:

    def test_release_is_refused_while_the_parent_product_is_not_cleared(self, api):
        """PRD §3.5: "For a release the remaining gates are evaluated in this
        exact order, so an operator always learns about the most serious defect
        first: no run of the lot may have `environmental_state` `DISQUALIFIED`
        (`ERR_ENVIRONMENTAL_NONCONFORMANCE`); every code in `release_test_codes`
        must have a measurement on the lot whose `outcome` is `PASS`
        (`ERR_RELEASE_TESTS_INCOMPLETE`); `release_bias_max_pct` must be at most
        `max_reference_bias_pct`, inclusively (`ERR_REFERENCE_BIAS_EXCEEDED`);
        every code in the product's `required_material_codes` must appear as the
        `material_code_snapshot` of a dispensing row of this lot whose `status`
        is `CONSUMED` (`ERR_BOM_INCOMPLETE`); when `bridging_required` is true a
        bridging study naming this lot as its candidate must exist in `status`
        `APPROVED` (`ERR_BRIDGING_REQUIRED`); when the requested
        `shelf_life_basis` is `REAL_TIME` or `ACCELERATED` a stability study on
        this product with that `study_type`, `status` `COMPLETE` and a non-null
        `established_shelf_life_months` must exist (`ERR_STABILITY_DATA_MISSING`);
        and last of all, the product's `clearance_status` must be `CLEARED`
        (`ERR_PRODUCT_NOT_CLEARED`)."
        PRD §3.2: "Looking only at records on this product specification whose
        `status` is `APPROVED` — `DRAFT` and `SUPERSEDED` records are excluded
        entirely — the flag `design_trace_complete` becomes true when there is at
        least one record with `record_type` `VERIFICATION` at `trace_depth` 3
        **and** at least one record with `record_type` `VALIDATION` at
        `trace_depth` 3."

        Design: Difficulty/cross_entity_state_dependency/reagent_lot_release_gated_on_product_specification_clearance_state
        """
        setup = _trace_complete_uncleared_setup(api, claim_months=12)
        bundle = fixtures.lot_under_release_test(api, setup)

        product = fixtures.ok(api.get_product_specification(
            setup["product"]["id"], REGULATORY_AFFAIRS))
        # The lot's own quality evidence is complete: the only outstanding gate
        # lives on the neighbouring product row.
        assert product["design_trace_complete"] is True
        assert product["clearance_status"] == "DESIGN"
        assert bundle["lot"]["disposition_status"] == "UNDER_RELEASE_TEST"

        response = api.disposition_reagent_lot(
            bundle["lot"]["id"],
            f.reagent_lot_disposition_payload("RELEASE", shelf_life_basis="CLAIM"),
            QA_RELEASER)
        validate_error(response, "ERR_PRODUCT_NOT_CLEARED")

    def test_refused_release_leaves_the_finished_lot_exactly_as_it_was(self, api):
        """PRD §2.4: "Twelve of the fourteen aggregates additionally carry
        `updated_at` — same format as `created_at`, refreshed on every mutation of
        the row — and `version`, an integer that starts at 1 when the row is
        created and increases by exactly 1 on every mutation of that row,
        including mutations reached indirectly through a cascade."
        PRD §3.5: "Hop 2: because the lot became `RELEASED`, its
        `distribution_status` moves from `WITHHELD` to `AVAILABLE` automatically,
        without a second request."

        Design: Difficulty/cross_entity_state_dependency/reagent_lot_release_gated_on_product_specification_clearance_state
        """
        setup = _trace_complete_uncleared_setup(api, claim_months=12)
        bundle = fixtures.lot_under_release_test(api, setup)
        before = bundle["lot"]
        version_before = before["version"]

        validate_error(api.disposition_reagent_lot(
            bundle["lot"]["id"],
            f.reagent_lot_disposition_payload("RELEASE"),
            QA_RELEASER), "ERR_PRODUCT_NOT_CLEARED")

        after = validate_success(
            api.get_reagent_lot(bundle["lot"]["id"], QA_RELEASER), 200)
        assertions.assert_reagent_lot(after)
        # No hop of the release cascade ran, so nothing moved on either axis.
        assert after["disposition_status"] == "UNDER_RELEASE_TEST"
        assert after["distribution_status"] == "WITHHELD"
        assert after["version"] == version_before
        assert after["released_by_user_id"] is None
        assert after["released_at"] is None
        assert after["assigned_shelf_life_months"] is None
        assert after["shelf_life_basis"] is None
        assert after["expiry_date"] is None
        assertions.assert_reagent_lot_unit_conservation(after)

    def test_recording_the_clearance_admits_the_identical_release(self, api):
        """PRD §3.2: "On success `clearance_status` becomes `CLEARED`,
        `submission_ref` and `cleared_at` are stored, and `version` increases by
        1."
        PRD §3.5: "When `shelf_life_basis` is `CLAIM`,
        `assigned_shelf_life_months` takes the product's `shelf_life_months_claim`
        and `shelf_life_basis_study_id` stays null."
        PRD §3.5: "Hop 2: because the lot became `RELEASED`, its
        `distribution_status` moves from `WITHHELD` to `AVAILABLE` automatically,
        without a second request."

        Design: Difficulty/cross_entity_state_dependency/reagent_lot_release_gated_on_product_specification_clearance_state
        """
        setup = _trace_complete_uncleared_setup(api, claim_months=12)
        bundle = fixtures.lot_under_release_test(api, setup)
        product_version_before = fixtures.ok(api.get_product_specification(
            setup["product"]["id"], REGULATORY_AFFAIRS))["version"]

        validate_error(api.disposition_reagent_lot(
            bundle["lot"]["id"],
            f.reagent_lot_disposition_payload("RELEASE", shelf_life_basis="CLAIM"),
            QA_RELEASER), "ERR_PRODUCT_NOT_CLEARED")

        cleared = validate_success(api.record_product_clearance(
            setup["product"]["id"], f.clearance_payload(),
            REGULATORY_AFFAIRS), 200)
        assert cleared["clearance_status"] == "CLEARED"
        assert cleared["cleared_at"] is not None
        assert cleared["version"] == product_version_before + 1

        released = validate_success(api.disposition_reagent_lot(
            bundle["lot"]["id"],
            f.reagent_lot_disposition_payload("RELEASE", shelf_life_basis="CLAIM"),
            QA_RELEASER), 200)
        assert released["disposition_status"] == "RELEASED"
        assert released["distribution_status"] == "AVAILABLE"
        assert released["shelf_life_basis"] == "CLAIM"
        # The claim on the product is 12 months and the logical clock has never
        # been moved, so the first completed run stamped fill_completed_at at
        # 2026-08-01T00:00:00.000Z and twelve calendar months later is
        # 2027-08-01T00:00:00.000Z.
        assert released["assigned_shelf_life_months"] == 12
        assert released["shelf_life_basis_study_id"] is None
        assertions.assert_same_instant(released["fill_completed_at"],
                                       constants.DEFAULT_CLOCK_UTC)
        assertions.assert_same_instant(released["expiry_date"],
                                       "2027-08-01T00:00:00.000Z")
        assertions.assert_reagent_lot_unit_conservation(released)


class TestDispensingGatedOnDrawnMaterialLotQualification:

    def test_dispensing_is_refused_while_the_material_lot_is_received(self, api):
        """PRD §3.3: "The raw material lot must be in `qualification_status`
        `QUALIFIED`, otherwise `ERR_MATERIAL_NOT_QUALIFIED`."

        Design: Difficulty/cross_entity_state_dependency/component_consumption_gated_on_material_lot_qualification_state
        """
        setup = _lot_and_unqualified_material(api, received_quantity_units=1000.00)
        assert setup["material_lot"]["qualification_status"] == "RECEIVED"
        version = setup["lot"]["version"]

        response = api.add_reagent_lot_component(
            setup["lot"]["id"],
            f.lot_component_payload(setup["material_lot"]["id"], "ENZYME",
                                    version, quantity_used=250.00),
            PRODUCTION_OPERATOR)
        validate_error(response, "ERR_MATERIAL_NOT_QUALIFIED")

    def test_dispensing_is_still_refused_while_the_material_lot_is_under_test(self, api):
        """PRD §3.1: "The first acceptance measurement on a lot moves it from
        `RECEIVED` to `UNDER_TEST`."
        PRD §3.3: "The raw material lot must be in `qualification_status`
        `QUALIFIED`, otherwise `ERR_MATERIAL_NOT_QUALIFIED`."

        Design: Difficulty/cross_entity_state_dependency/component_consumption_gated_on_material_lot_qualification_state
        """
        setup = _lot_and_unqualified_material(api, received_quantity_units=1000.00)
        fixtures.record_material_measurement(
            api, setup["material_lot"]["id"], "POTENCY",
            fixtures.passing_value_for(setup["spec"], "POTENCY"), QC_ANALYST)

        under_test = validate_success(api.get_material_lot(
            setup["material_lot"]["id"], QC_ANALYST), 200)
        assert under_test["qualification_status"] == "UNDER_TEST"

        # A passing measurement is not a disposition: the gate names one state
        # and UNDER_TEST is not it.
        response = api.add_reagent_lot_component(
            setup["lot"]["id"],
            f.lot_component_payload(setup["material_lot"]["id"], "ENZYME",
                                    setup["lot"]["version"],
                                    quantity_used=250.00),
            PRODUCTION_OPERATOR)
        validate_error(response, "ERR_MATERIAL_NOT_QUALIFIED")

    def test_refused_dispensing_moves_no_quantity_and_writes_no_row(self, api):
        """PRD §2.8: "The invariant is that `received_quantity_units` always
        equals `available_quantity_units` plus `consumed_quantity_units`."
        PRD §3.3: "The dispensing rows of a finished lot are listable and
        filterable by `status` and by `component_role`."

        Design: Difficulty/cross_entity_state_dependency/component_consumption_gated_on_material_lot_qualification_state
        """
        setup = _lot_and_unqualified_material(api, received_quantity_units=1000.00)
        payload = f.lot_component_payload(setup["material_lot"]["id"], "ENZYME",
                                          setup["lot"]["version"],
                                          quantity_used=250.00)
        validate_error(api.add_reagent_lot_component(
            setup["lot"]["id"], payload, PRODUCTION_OPERATOR),
            "ERR_MATERIAL_NOT_QUALIFIED")
        fixtures.record_material_measurement(
            api, setup["material_lot"]["id"], "POTENCY",
            fixtures.passing_value_for(setup["spec"], "POTENCY"), QC_ANALYST)
        validate_error(api.add_reagent_lot_component(
            setup["lot"]["id"], payload, PRODUCTION_OPERATOR),
            "ERR_MATERIAL_NOT_QUALIFIED")

        material_lot = validate_success(api.get_material_lot(
            setup["material_lot"]["id"], QC_ANALYST), 200)
        assert material_lot["received_quantity_units"] == 1000.00
        assert material_lot["available_quantity_units"] == 1000.00
        assert material_lot["consumed_quantity_units"] == 0.00
        assertions.assert_material_quantity_conservation(material_lot)

        rows, meta = validate_paginated(api.list_reagent_lot_components(
            setup["lot"]["id"], PRODUCTION_OPERATOR))
        assert rows == []
        assertions.assert_paginated_meta(meta, expected_total=0,
                                         expected_has_more=False)
        finished = validate_success(api.get_reagent_lot(
            setup["lot"]["id"], PRODUCTION_OPERATOR), 200)
        assert finished["version"] == setup["lot"]["version"]
        assert finished["disposition_status"] == "PLANNED"

    def test_qualifying_the_material_lot_admits_the_pinned_dispensing(self, api):
        """PRD §3.1: "On success the lot moves `UNDER_TEST` to `QUALIFIED`,
        `dispositioned_by_user_id` and `dispositioned_at` are recorded,
        `available_quantity_units` remains `received_quantity_units` minus
        `consumed_quantity_units`, and the lot's `version` increases by 1."
        PRD §3.3: "A successful dispensing call moves quantity across the raw
        material ledger: the raw lot's `consumed_quantity_units` increases by
        `quantity_used` and its `available_quantity_units` decreases by the same
        amount, keeping `received_quantity_units` equal to the sum of the two."
        PRD §3.3: "Each successful call creates a dispensing row whose
        `reagent_lot_id` points at the finished lot, whose `status` starts as
        `CONSUMED`, and whose two snapshot fields are copied at creation time:
        `material_code_snapshot` takes the `material_code` of the consumed lot's
        specification, and `vendor_lot_code_snapshot` takes the consumed lot's
        `vendor_lot_code`."

        Design: Difficulty/cross_entity_state_dependency/component_consumption_gated_on_material_lot_qualification_state
        """
        setup = _lot_and_unqualified_material(api, received_quantity_units=1000.00)
        pinned_version = setup["lot"]["version"]
        validate_error(api.add_reagent_lot_component(
            setup["lot"]["id"],
            f.lot_component_payload(setup["material_lot"]["id"], "ENZYME",
                                    pinned_version, quantity_used=250.00),
            PRODUCTION_OPERATOR), "ERR_MATERIAL_NOT_QUALIFIED")

        fixtures.record_material_measurement(
            api, setup["material_lot"]["id"], "POTENCY",
            fixtures.passing_value_for(setup["spec"], "POTENCY"), QC_ANALYST)
        qualified = validate_success(api.disposition_material_lot(
            setup["material_lot"]["id"],
            f.material_lot_disposition_payload("QUALIFY"), QA_RELEASER), 200)
        assert qualified["qualification_status"] == "QUALIFIED"

        # The refused call mutated nothing, so the version read before it is
        # still the finished lot's current generation.
        component = validate_success(api.add_reagent_lot_component(
            setup["lot"]["id"],
            f.lot_component_payload(setup["material_lot"]["id"], "ENZYME",
                                    pinned_version, quantity_used=250.00),
            PRODUCTION_OPERATOR), 201)
        assertions.assert_lot_component(component)
        assert component["status"] == "CONSUMED"
        assert component["quantity_used"] == 250.00
        assert component["material_code_snapshot"] == setup["spec"]["material_code"]
        assert component["vendor_lot_code_snapshot"] == \
            setup["material_lot"]["vendor_lot_code"]

        # 1000.00 received, 250.00 drawn: 750.00 available and 250.00 consumed.
        material_lot = validate_success(api.get_material_lot(
            setup["material_lot"]["id"], QC_ANALYST), 200)
        assert material_lot["available_quantity_units"] == 750.00
        assert material_lot["consumed_quantity_units"] == 250.00
        assert material_lot["received_quantity_units"] == 1000.00
        assertions.assert_material_quantity_conservation(material_lot)


class TestFillingLineClosedIntervalChangeoverBuffer:

    def test_run_starting_inside_the_trailing_buffer_conflicts(self, api):
        """PRD §3.4: "The occupation interval is **closed** — both endpoints
        belong to the run — and it is guarded by a 120-minute changeover buffer
        that must be respected on both ends."
        PRD §3.4: "Concretely: the requested run conflicts with an existing run
        on the same `line_code` whose `status` is `SCHEDULED` or `RUNNING` when
        the requested start is earlier than that run's end plus two hours **and**
        that run's start is earlier than the requested end plus two hours."
        PRD §3.4: "A conflict is refused with `ERR_FILL_LINE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/fill_line_changeover_buffer_closed_interval_symmetric_boundaries
        """
        lot = _lot_with_line(api)
        line_code = f.unique_line_code()
        blocker = fixtures.schedule_fill_run(
            api, lot["id"], line_code=line_code,
            scheduled_start=_BLOCKER_START, scheduled_end=_BLOCKER_END)
        assert blocker["status"] == "SCHEDULED"

        # Requested start 11:00 is earlier than 10:00 plus two hours (12:00), and
        # the blocker's start 06:00 is earlier than 13:00 plus two hours (15:00),
        # so both halves hold.
        response = api.create_fill_run(
            f.fill_run_payload(lot["id"], line_code=line_code,
                               scheduled_start=_GAP_60_START,
                               scheduled_end=_GAP_60_END),
            PRODUCTION_OPERATOR)
        validate_error(response, "ERR_FILL_LINE_CONFLICT")

    def test_run_starting_exactly_two_hours_after_another_ends_is_accepted(self, api):
        """PRD §3.4: "Concretely: the requested run conflicts with an existing run
        on the same `line_code` whose `status` is `SCHEDULED` or `RUNNING` when
        the requested start is earlier than that run's end plus two hours **and**
        that run's start is earlier than the requested end plus two hours."
        PRD §3.4: "Both halves must hold for it to be a conflict; a run that
        begins exactly two hours after another ends is acceptable."
        PRD §3.4: "New runs are created in `status` `SCHEDULED` with
        `environmental_state` initialised to `CONFORMING`, `minor_excursion_count`
        and `major_excursion_count` at 0, and `filled_units`, `started_at`,
        `ended_at`, `bioburden_cfu_per_ml` and `abort_reason` all null."

        Design: Difficulty/resource_temporal_overlap/fill_line_changeover_buffer_closed_interval_symmetric_boundaries
        """
        lot = _lot_with_line(api)
        line_code = f.unique_line_code()
        fixtures.schedule_fill_run(
            api, lot["id"], line_code=line_code,
            scheduled_start=_BLOCKER_START, scheduled_end=_BLOCKER_END)

        # Requested start 12:00 is not earlier than 10:00 plus two hours, so the
        # first half fails and there is no conflict.
        accepted = validate_success(api.create_fill_run(
            f.fill_run_payload(lot["id"], line_code=line_code,
                               scheduled_start=_GAP_120_START,
                               scheduled_end=_GAP_120_END),
            PRODUCTION_OPERATOR), 201)
        assertions.assert_fill_run(accepted)
        assert accepted["status"] == "SCHEDULED"
        assert accepted["environmental_state"] == "CONFORMING"
        assertions.assert_same_instant(accepted["scheduled_start"], _GAP_120_START)

        persisted = validate_success(api.get_fill_run(accepted["id"],
                                                      PRODUCTION_OPERATOR), 200)
        assert persisted["line_code"] == line_code
        assertions.assert_same_instant(persisted["scheduled_end"], _GAP_120_END)

    def test_run_ending_one_minute_inside_the_leading_buffer_conflicts(self, api):
        """PRD §3.4: "The occupation interval is **closed** — both endpoints
        belong to the run — and it is guarded by a 120-minute changeover buffer
        that must be respected on both ends."
        PRD §3.4: "Concretely: the requested run conflicts with an existing run
        on the same `line_code` whose `status` is `SCHEDULED` or `RUNNING` when
        the requested start is earlier than that run's end plus two hours **and**
        that run's start is earlier than the requested end plus two hours."

        Design: Difficulty/resource_temporal_overlap/fill_line_changeover_buffer_closed_interval_symmetric_boundaries
        """
        lot = _lot_with_line(api)
        line_code = f.unique_line_code()
        fixtures.schedule_fill_run(
            api, lot["id"], line_code=line_code,
            scheduled_start=_BLOCKER_START, scheduled_end=_BLOCKER_END)

        # The requested run ends at 04:01, so the blocker's start 06:00 is
        # earlier than 06:01 by a single minute: the symmetric half now holds.
        response = api.create_fill_run(
            f.fill_run_payload(lot["id"], line_code=line_code,
                               scheduled_start=_LEAD_119_START,
                               scheduled_end=_LEAD_119_END),
            PRODUCTION_OPERATOR)
        validate_error(response, "ERR_FILL_LINE_CONFLICT")

    def test_run_ending_exactly_two_hours_before_another_starts_is_accepted(self, api):
        """PRD §3.4: "Both halves must hold for it to be a conflict; a run that
        begins exactly two hours after another ends is acceptable."
        PRD §3.4: "Concretely: the requested run conflicts with an existing run
        on the same `line_code` whose `status` is `SCHEDULED` or `RUNNING` when
        the requested start is earlier than that run's end plus two hours **and**
        that run's start is earlier than the requested end plus two hours."

        Design: Difficulty/resource_temporal_overlap/fill_line_changeover_buffer_closed_interval_symmetric_boundaries
        """
        lot = _lot_with_line(api)
        line_code = f.unique_line_code()
        fixtures.schedule_fill_run(
            api, lot["id"], line_code=line_code,
            scheduled_start=_BLOCKER_START, scheduled_end=_BLOCKER_END)
        later = fixtures.schedule_fill_run(
            api, lot["id"], line_code=line_code,
            scheduled_start=_GAP_120_START, scheduled_end=_GAP_120_END)
        assert later["status"] == "SCHEDULED"

        # Against the 06:00 blocker: 06:00 is not earlier than 04:00 plus two
        # hours.  Against the 12:00 run: 12:00 is not earlier than 06:00 either.
        accepted = validate_success(api.create_fill_run(
            f.fill_run_payload(lot["id"], line_code=line_code,
                               scheduled_start=_LEAD_120_START,
                               scheduled_end=_LEAD_120_END),
            PRODUCTION_OPERATOR), 201)
        assert accepted["status"] == "SCHEDULED"
        assertions.assert_same_instant(accepted["scheduled_end"], _LEAD_120_END)

        rows, meta = validate_paginated(api.list_fill_runs(
            PRODUCTION_OPERATOR, params={"line_code": line_code}))
        assert len(rows) == 3
        assertions.assert_paginated_meta(meta, expected_total=3)

    def test_the_changeover_buffer_is_scoped_to_one_line_code(self, api):
        """PRD §3.4: "Concretely: the requested run conflicts with an existing run
        on the same `line_code` whose `status` is `SCHEDULED` or `RUNNING` when
        the requested start is earlier than that run's end plus two hours **and**
        that run's start is earlier than the requested end plus two hours."
        PRD §3.4: "Runs are listable and filterable by `reagent_lot_id`,
        `line_code`, `status` and `environmental_state`."

        Design: Difficulty/resource_temporal_overlap/fill_line_changeover_buffer_closed_interval_symmetric_boundaries
        """
        lot = _lot_with_line(api)
        occupied_line = f.unique_line_code()
        free_line = f.unique_line_code()
        fixtures.schedule_fill_run(
            api, lot["id"], line_code=occupied_line,
            scheduled_start=_BLOCKER_START, scheduled_end=_BLOCKER_END)

        validate_error(api.create_fill_run(
            f.fill_run_payload(lot["id"], line_code=occupied_line,
                               scheduled_start=_GAP_60_START,
                               scheduled_end=_GAP_60_END),
            PRODUCTION_OPERATOR), "ERR_FILL_LINE_CONFLICT")

        # The very interval that conflicts on one line is free on another.
        accepted = validate_success(api.create_fill_run(
            f.fill_run_payload(lot["id"], line_code=free_line,
                               scheduled_start=_GAP_60_START,
                               scheduled_end=_GAP_60_END),
            PRODUCTION_OPERATOR), 201)
        assert accepted["line_code"] == free_line

        rows, _ = validate_paginated(api.list_fill_runs(
            PRODUCTION_OPERATOR, params={"line_code": free_line}))
        assert [row["id"] for row in rows] == [accepted["id"]]

    def test_only_scheduled_and_running_runs_occupy_the_line(self, api):
        """PRD §3.4: "Concretely: the requested run conflicts with an existing run
        on the same `line_code` whose `status` is `SCHEDULED` or `RUNNING` when
        the requested start is earlier than that run's end plus two hours **and**
        that run's start is earlier than the requested end plus two hours."
        PRD §3.4: "Aborting a `SCHEDULED` run and aborting a `RUNNING` run share
        hop 1 identically: the run's `status` becomes `ABORTED`, `ended_at` is
        stamped, and `abort_reason` is stored."

        Design: Difficulty/resource_temporal_overlap/fill_line_changeover_buffer_closed_interval_symmetric_boundaries
        """
        lot = _lot_with_line(api)
        line_code = f.unique_line_code()
        blocker = fixtures.schedule_fill_run(
            api, lot["id"], line_code=line_code,
            scheduled_start=_BLOCKER_START, scheduled_end=_BLOCKER_END)
        validate_error(api.create_fill_run(
            f.fill_run_payload(lot["id"], line_code=line_code,
                               scheduled_start=_GAP_60_START,
                               scheduled_end=_GAP_60_END),
            PRODUCTION_OPERATOR), "ERR_FILL_LINE_CONFLICT")

        aborted = fixtures.abort_fill_run(api, blocker["id"],
                                          "Line released to maintenance")
        assert aborted["status"] == "ABORTED"
        assert aborted["abort_reason"] == "Line released to maintenance"

        # With the only occupant aborted, the previously conflicting interval is
        # admitted unchanged.
        accepted = validate_success(api.create_fill_run(
            f.fill_run_payload(lot["id"], line_code=line_code,
                               scheduled_start=_GAP_60_START,
                               scheduled_end=_GAP_60_END),
            PRODUCTION_OPERATOR), 201)
        assert accepted["status"] == "SCHEDULED"
        assertions.assert_same_instant(accepted["scheduled_start"], _GAP_60_START)

    def test_a_refused_schedule_leaves_the_line_holding_one_run(self, api):
        """PRD §3.4: "A conflict is refused with `ERR_FILL_LINE_CONFLICT`."
        PRD §3.4: "Runs are listable and filterable by `reagent_lot_id`,
        `line_code`, `status` and `environmental_state`."

        Design: Difficulty/resource_temporal_overlap/fill_line_changeover_buffer_closed_interval_symmetric_boundaries
        """
        lot = _lot_with_line(api)
        line_code = f.unique_line_code()
        blocker = fixtures.schedule_fill_run(
            api, lot["id"], line_code=line_code,
            scheduled_start=_BLOCKER_START, scheduled_end=_BLOCKER_END)

        validate_error(api.create_fill_run(
            f.fill_run_payload(lot["id"], line_code=line_code,
                               scheduled_start=_GAP_60_START,
                               scheduled_end=_GAP_60_END),
            PRODUCTION_OPERATOR), "ERR_FILL_LINE_CONFLICT")
        validate_error(api.create_fill_run(
            f.fill_run_payload(lot["id"], line_code=line_code,
                               scheduled_start=_LEAD_119_START,
                               scheduled_end=_LEAD_119_END),
            PRODUCTION_OPERATOR), "ERR_FILL_LINE_CONFLICT")

        rows, meta = validate_paginated(api.list_fill_runs(
            PRODUCTION_OPERATOR, params={"line_code": line_code}))
        assert [row["id"] for row in rows] == [blocker["id"]]
        assertions.assert_paginated_meta(meta, expected_total=1,
                                         expected_has_more=False)


class TestStabilityChamberHalfOpenIntervalAggregateCapacity:

    def _protocol(self, api, setup, chamber_code, start, end):
        return fixtures.create_stability_study(
            api, setup["product"]["id"], setup["lot"]["id"],
            chamber_code=chamber_code, protocol_start=start, protocol_end=end,
            planned_timepoints_months=[0, 3])

    def _request(self, api, setup, chamber_code, start, end):
        return api.create_stability_study(
            f.stability_study_payload(
                setup["product"]["id"], setup["lot"]["id"],
                chamber_code=chamber_code, protocol_start=start,
                protocol_end=end, planned_timepoints_months=[0, 3]),
            REGULATORY_AFFAIRS)

    def test_a_third_live_protocol_over_a_shared_instant_is_refused(self, api):
        """PRD §3.6: "At most two studies whose `status` is `PROTOCOL_DRAFT`,
        `APPROVED` or `IN_PROGRESS` may occupy the same `chamber_code` over any
        single instant of the requested interval; a third live study covering any
        shared instant is refused with `ERR_CHAMBER_CAPACITY_EXCEEDED`."
        PRD §3.6: "New studies start in `status` `PROTOCOL_DRAFT` with
        `timepoint_count` at 0 and `last_conforming_month`,
        `established_shelf_life_months`, `shelf_life_method` and
        `protocol_approved_by_user_id` all null."

        Design: Difficulty/resource_temporal_overlap/stability_chamber_half_open_interval_with_aggregate_capacity_two
        """
        setup = _lot_for_chamber(api)
        chamber = f.unique_chamber_code()
        first = self._protocol(api, setup, chamber, _STUDY_A_START, _STUDY_A_END)
        second = self._protocol(api, setup, chamber, _STUDY_B_START, _STUDY_B_END)
        assert first["status"] == "PROTOCOL_DRAFT"
        assert second["status"] == "PROTOCOL_DRAFT"

        # November lies inside both live protocols, so the chamber is already at
        # its capacity of two over every instant of the request.
        validate_error(self._request(api, setup, chamber, _NOVEMBER_START,
                                     _NOVEMBER_END),
                       "ERR_CHAMBER_CAPACITY_EXCEEDED")

    def test_an_approved_protocol_still_counts_against_capacity(self, api):
        """PRD §3.6: "A `QAReleaser` approves the protocol, which moves `status`
        from `PROTOCOL_DRAFT` to `APPROVED`, records
        `protocol_approved_by_user_id`, and increases `version` by 1."
        PRD §3.6: "At most two studies whose `status` is `PROTOCOL_DRAFT`,
        `APPROVED` or `IN_PROGRESS` may occupy the same `chamber_code` over any
        single instant of the requested interval; a third live study covering any
        shared instant is refused with `ERR_CHAMBER_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/stability_chamber_half_open_interval_with_aggregate_capacity_two
        """
        setup = _lot_for_chamber(api)
        chamber = f.unique_chamber_code()
        first = self._protocol(api, setup, chamber, _STUDY_A_START, _STUDY_A_END)
        self._protocol(api, setup, chamber, _STUDY_B_START, _STUDY_B_END)

        approved = fixtures.approve_stability_protocol(api, first["id"])
        assert approved["status"] == "APPROVED"
        assert approved["protocol_approved_by_user_id"] is not None
        assert approved["version"] == first["version"] + 1

        validate_error(self._request(api, setup, chamber, _NOVEMBER_START,
                                     _NOVEMBER_END),
                       "ERR_CHAMBER_CAPACITY_EXCEEDED")

    def test_an_in_progress_protocol_still_counts_against_capacity(self, api):
        """PRD §3.6: "The first timepoint advances the study from `APPROVED` to
        `IN_PROGRESS`; each subsequent timepoint is a self-loop on `IN_PROGRESS`
        and additionally requires that no measurement with the same
        `stability_study_id`, `month_index` and `test_code` already exists."
        PRD §3.6: "At most two studies whose `status` is `PROTOCOL_DRAFT`,
        `APPROVED` or `IN_PROGRESS` may occupy the same `chamber_code` over any
        single instant of the requested interval; a third live study covering any
        shared instant is refused with `ERR_CHAMBER_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/stability_chamber_half_open_interval_with_aggregate_capacity_two
        """
        setup = _lot_for_chamber(api)
        chamber = f.unique_chamber_code()
        first = self._protocol(api, setup, chamber, _STUDY_A_START, _STUDY_A_END)
        self._protocol(api, setup, chamber, _STUDY_B_START, _STUDY_B_END)

        fixtures.approve_stability_protocol(api, first["id"])
        fixtures.record_timepoint(api, first["id"], 0,
                                  fixtures.conforming_timepoint_value(first))
        in_progress = validate_success(api.get_stability_study(
            first["id"], REGULATORY_AFFAIRS), 200)
        assert in_progress["status"] == "IN_PROGRESS"

        validate_error(self._request(api, setup, chamber, _NOVEMBER_START,
                                     _NOVEMBER_END),
                       "ERR_CHAMBER_CAPACITY_EXCEEDED")

    def test_a_completed_protocol_no_longer_counts_against_capacity(self, api):
        """PRD §3.6: "Studies in `COMPLETE` or `ABORTED` never count against
        capacity."
        PRD §3.6: "On success `status` becomes the terminal `COMPLETE`, `version`
        increases by 1, and two computed fields are filled."

        Design: Difficulty/resource_temporal_overlap/stability_chamber_half_open_interval_with_aggregate_capacity_two
        """
        setup = _lot_for_chamber(api)
        chamber = f.unique_chamber_code()
        first = self._protocol(api, setup, chamber, _STUDY_A_START, _STUDY_A_END)
        self._protocol(api, setup, chamber, _STUDY_B_START, _STUDY_B_END)
        validate_error(self._request(api, setup, chamber, _NOVEMBER_START,
                                     _NOVEMBER_END),
                       "ERR_CHAMBER_CAPACITY_EXCEEDED")

        fixtures.approve_stability_protocol(api, first["id"])
        fixtures.record_timepoint(api, first["id"], 0,
                                  fixtures.conforming_timepoint_value(first))
        concluded = validate_success(api.conclude_stability_study(
            first["id"], REGULATORY_AFFAIRS), 200)
        assert concluded["status"] == "COMPLETE"

        # One live protocol is left over November, so there is room again.
        accepted = validate_success(self._request(api, setup, chamber,
                                                 _NOVEMBER_START,
                                                 _NOVEMBER_END), 201)
        assertions.assert_stability_study(accepted)
        assert accepted["status"] == "PROTOCOL_DRAFT"
        assert accepted["chamber_code"] == chamber

    def test_capacity_is_counted_per_chamber_code(self, api):
        """PRD §3.6: "At most two studies whose `status` is `PROTOCOL_DRAFT`,
        `APPROVED` or `IN_PROGRESS` may occupy the same `chamber_code` over any
        single instant of the requested interval; a third live study covering any
        shared instant is refused with `ERR_CHAMBER_CAPACITY_EXCEEDED`."
        PRD §3.6: "Studies are listable and filterable by
        `product_specification_id`, `reagent_lot_id`, `study_type`, `status` and
        `chamber_code`."

        Design: Difficulty/resource_temporal_overlap/stability_chamber_half_open_interval_with_aggregate_capacity_two
        """
        setup = _lot_for_chamber(api)
        saturated = f.unique_chamber_code()
        empty = f.unique_chamber_code()
        self._protocol(api, setup, saturated, _STUDY_A_START, _STUDY_A_END)
        self._protocol(api, setup, saturated, _STUDY_B_START, _STUDY_B_END)

        validate_error(self._request(api, setup, saturated, _NOVEMBER_START,
                                     _NOVEMBER_END),
                       "ERR_CHAMBER_CAPACITY_EXCEEDED")
        accepted = validate_success(self._request(api, setup, empty,
                                                  _NOVEMBER_START,
                                                  _NOVEMBER_END), 201)
        assert accepted["chamber_code"] == empty

        rows, meta = validate_paginated(api.list_stability_studies(
            REGULATORY_AFFAIRS, params={"chamber_code": empty}))
        assert [row["id"] for row in rows] == [accepted["id"]]
        assertions.assert_paginated_meta(meta, expected_total=1)

    def test_a_protocol_starting_when_another_ends_shares_no_instant(self, api):
        """PRD §3.6: "Unlike a filling line, a chamber has **aggregate capacity
        2** and its occupation interval is **half-open**: `protocol_start` is
        inclusive and `protocol_end` is exclusive, so a study starting at exactly
        the instant another ends does not overlap it."
        PRD §3.6: "At most two studies whose `status` is `PROTOCOL_DRAFT`,
        `APPROVED` or `IN_PROGRESS` may occupy the same `chamber_code` over any
        single instant of the requested interval; a third live study covering any
        shared instant is refused with `ERR_CHAMBER_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/stability_chamber_half_open_interval_with_aggregate_capacity_two
        """
        setup = _lot_for_chamber(api)
        chamber = f.unique_chamber_code()
        self._protocol(api, setup, chamber, _STUDY_A_START, _STUDY_A_END)
        self._protocol(api, setup, chamber, _STUDY_B_START, _STUDY_B_END)

        # The first protocol's exclusive end is 2026-12-01, so a protocol opening
        # at that very instant meets only one live occupant, not two.
        accepted = validate_success(self._request(api, setup, chamber,
                                                  _DECEMBER_START,
                                                  _DECEMBER_END), 201)
        assert accepted["status"] == "PROTOCOL_DRAFT"
        assertions.assert_same_instant(accepted["protocol_start"],
                                       _DECEMBER_START)
        persisted = validate_success(api.get_stability_study(
            accepted["id"], REGULATORY_AFFAIRS), 200)
        assertions.assert_same_instant(persisted["protocol_end"], _DECEMBER_END)

    def test_the_saturating_pair_shifts_as_the_schedule_fills(self, api):
        """PRD §3.6: "Unlike a filling line, a chamber has **aggregate capacity
        2** and its occupation interval is **half-open**: `protocol_start` is
        inclusive and `protocol_end` is exclusive, so a study starting at exactly
        the instant another ends does not overlap it."
        PRD §3.6: "At most two studies whose `status` is `PROTOCOL_DRAFT`,
        `APPROVED` or `IN_PROGRESS` may occupy the same `chamber_code` over any
        single instant of the requested interval; a third live study covering any
        shared instant is refused with `ERR_CHAMBER_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/stability_chamber_half_open_interval_with_aggregate_capacity_two
        """
        setup = _lot_for_chamber(api)
        chamber = f.unique_chamber_code()
        self._protocol(api, setup, chamber, _STUDY_A_START, _STUDY_A_END)
        self._protocol(api, setup, chamber, _STUDY_B_START, _STUDY_B_END)
        self._protocol(api, setup, chamber, _DECEMBER_START, _DECEMBER_END)

        # Early December now carries two live occupants of its own.
        validate_error(self._request(api, setup, chamber, _MID_DECEMBER_START,
                                     _MID_DECEMBER_END),
                       "ERR_CHAMBER_CAPACITY_EXCEEDED")

        # January is past the exclusive end of both of them.
        accepted = validate_success(self._request(api, setup, chamber,
                                                  _JANUARY_START,
                                                  _JANUARY_END), 201)
        assertions.assert_same_instant(accepted["protocol_start"], _JANUARY_START)

    def test_a_refused_protocol_leaves_two_live_studies_on_file(self, api):
        """PRD §3.6: "At most two studies whose `status` is `PROTOCOL_DRAFT`,
        `APPROVED` or `IN_PROGRESS` may occupy the same `chamber_code` over any
        single instant of the requested interval; a third live study covering any
        shared instant is refused with `ERR_CHAMBER_CAPACITY_EXCEEDED`."
        PRD §3.6: "Studies are listable and filterable by
        `product_specification_id`, `reagent_lot_id`, `study_type`, `status` and
        `chamber_code`."

        Design: Difficulty/resource_temporal_overlap/stability_chamber_half_open_interval_with_aggregate_capacity_two
        """
        setup = _lot_for_chamber(api)
        chamber = f.unique_chamber_code()
        first = self._protocol(api, setup, chamber, _STUDY_A_START, _STUDY_A_END)
        second = self._protocol(api, setup, chamber, _STUDY_B_START,
                                _STUDY_B_END)

        # Both probes lie strictly inside protocol A [09-01, 12-01) and protocol
        # B [10-01, 01-01), so the chamber is already at its capacity of two over
        # every instant either probe requests.
        validate_error(self._request(api, setup, chamber, _NOVEMBER_START,
                                     _NOVEMBER_END),
                       "ERR_CHAMBER_CAPACITY_EXCEEDED")
        validate_error(self._request(api, setup, chamber, _LATE_NOVEMBER_START,
                                     _LATE_NOVEMBER_END),
                       "ERR_CHAMBER_CAPACITY_EXCEEDED")

        rows, meta = validate_paginated(api.list_stability_studies(
            REGULATORY_AFFAIRS, params={"chamber_code": chamber}))
        assert sorted(row["id"] for row in rows) == \
            sorted([first["id"], second["id"]])
        assertions.assert_paginated_meta(meta, expected_total=2,
                                         expected_has_more=False)


def _two_material_setup(api) -> dict:
    """Two qualified raw material lots of different sizes — 1000.00 and 500.00
    received units — and a finished lot whose bill of materials names both."""
    antibody = fixtures.qualified_material(
        api,
        spec_overrides={"material_type": "ANTIBODY",
                        "required_test_codes": ["POTENCY"]},
        lot_overrides={"received_quantity_units": 1000.00})
    buffer_material = fixtures.qualified_material(
        api,
        spec_overrides={"material_type": "BUFFER",
                        "required_test_codes": ["POTENCY"]},
        lot_overrides={"received_quantity_units": 500.00})
    product = fixtures.create_product_specification(
        api, required_material_codes=[antibody["spec"]["material_code"],
                                      buffer_material["spec"]["material_code"]])
    lot = fixtures.create_reagent_lot(api, product["id"])
    return {"antibody": antibody, "buffer": buffer_material,
            "product": product, "lot": lot}


def _dispense_both(api, setup) -> list:
    """Draw 250.00 units of the larger material and 100.00 of the smaller one
    into the finished lot."""
    return [
        fixtures.dispense_component(api, setup["lot"]["id"],
                                    setup["antibody"]["lot"]["id"], "ANTIBODY",
                                    quantity_used=250.00),
        fixtures.dispense_component(api, setup["lot"]["id"],
                                    setup["buffer"]["lot"]["id"], "BUFFER",
                                    quantity_used=100.00),
    ]


def _material_lot(api, material_lot_id: str) -> dict:
    return validate_success(api.get_material_lot(material_lot_id, QC_ANALYST), 200)


def _run_and_abort(api, setup, *, abort_reason: str) -> dict:
    """Schedule a run on its own line, start it so the lot leaves `PLANNED`, and
    abort it."""
    run = fixtures.schedule_fill_run(api, setup["lot"]["id"])
    started = fixtures.start_fill_run(api, run["id"])
    assert started["status"] == "RUNNING"
    return fixtures.abort_fill_run(api, run["id"], abort_reason)


class TestFillRunAbortRestoresMaterialQuantityConservation:

    def test_abort_of_a_running_run_reverts_the_lot_and_returns_every_row(self, api):
        """PRD §3.4: "Aborting a `SCHEDULED` run and aborting a `RUNNING` run
        share hop 1 identically: the run's `status` becomes `ABORTED`, `ended_at`
        is stamped, and `abort_reason` is stored."
        PRD §3.4: "The one difference is hop 2 and it follows from where the lot
        already was: a `RUNNING` run's abort reverts the lot's
        `disposition_status` from `IN_PROCESS` back to `PLANNED`, whereas a
        `SCHEDULED` run's abort finds the lot already `PLANNED` and leaves it
        there."
        PRD §3.4: "Starting a run advances the run from `SCHEDULED` to `RUNNING`
        and, on the parent's quality axis, advances `disposition_status` from
        `PLANNED` to `IN_PROCESS`."

        Design: Difficulty/compensating_invariant/fill_run_abort_restores_material_quantity_conservation_over_two_cycles
        """
        setup = _two_material_setup(api)
        _dispense_both(api, setup)
        run = fixtures.schedule_fill_run(api, setup["lot"]["id"])
        fixtures.start_fill_run(api, run["id"])
        in_process = validate_success(api.get_reagent_lot(
            setup["lot"]["id"], PRODUCTION_OPERATOR), 200)
        assert in_process["disposition_status"] == "IN_PROCESS"

        aborted = fixtures.abort_fill_run(api, run["id"], "Stopper jam")
        assert aborted["status"] == "ABORTED"
        assert aborted["abort_reason"] == "Stopper jam"
        assert aborted["ended_at"] is not None

        reverted = validate_success(api.get_reagent_lot(
            setup["lot"]["id"], PRODUCTION_OPERATOR), 200)
        assert reverted["disposition_status"] == "PLANNED"
        assert reverted["version"] == in_process["version"] + 1
        assert reverted["filled_units"] == 0
        assertions.assert_reagent_lot_unit_conservation(reverted)

        rows, _ = validate_paginated(api.list_reagent_lot_components(
            setup["lot"]["id"], PRODUCTION_OPERATOR))
        assert len(rows) == 2
        assert {row["status"] for row in rows} == {"RETURNED"}

    def test_abort_restores_each_material_ledger_by_its_own_quantity(self, api):
        """PRD §2.8: "Dispensing moves a quantity from available to consumed; the
        compensation that follows an aborted filling run flips the dispensing row
        to `RETURNED` and moves exactly the same quantity back, so the ledger
        returns to its pre-dispensing values with zero drift."
        PRD §3.4: "They also share hops 3 and 4 identically: every dispensing row
        of the parent lot whose `status` is `CONSUMED` becomes `RETURNED`, and
        because those rows left `CONSUMED`, each raw material lot they referenced
        has its `consumed_quantity_units` reduced by that row's `quantity_used`
        and its `available_quantity_units` increased by exactly the same amount,
        restoring the raw material ledger of §2.8 to its pre-dispensing values
        with zero drift; every raw material lot touched has its `version`
        increased by 1."

        Design: Difficulty/compensating_invariant/fill_run_abort_restores_material_quantity_conservation_over_two_cycles
        """
        setup = _two_material_setup(api)
        antibody_id = setup["antibody"]["lot"]["id"]
        buffer_id = setup["buffer"]["lot"]["id"]
        _dispense_both(api, setup)

        # 1000.00 less 250.00 drawn, and 500.00 less 100.00 drawn.
        antibody_before = _material_lot(api, antibody_id)
        buffer_before = _material_lot(api, buffer_id)
        assert antibody_before["available_quantity_units"] == 750.00
        assert antibody_before["consumed_quantity_units"] == 250.00
        assert buffer_before["available_quantity_units"] == 400.00
        assert buffer_before["consumed_quantity_units"] == 100.00
        assertions.assert_material_quantity_conservation(antibody_before)
        assertions.assert_material_quantity_conservation(buffer_before)

        _run_and_abort(api, setup, abort_reason="Filling needle failure")

        antibody_after = _material_lot(api, antibody_id)
        buffer_after = _material_lot(api, buffer_id)
        assert antibody_after["available_quantity_units"] == 1000.00
        assert antibody_after["consumed_quantity_units"] == 0.00
        assert antibody_after["received_quantity_units"] == 1000.00
        assert antibody_after["version"] == antibody_before["version"] + 1
        assert buffer_after["available_quantity_units"] == 500.00
        assert buffer_after["consumed_quantity_units"] == 0.00
        assert buffer_after["received_quantity_units"] == 500.00
        assert buffer_after["version"] == buffer_before["version"] + 1
        assertions.assert_material_quantity_conservation(antibody_after)
        assertions.assert_material_quantity_conservation(buffer_after)

    def test_two_consume_and_return_cycles_leave_no_drift(self, api):
        """PRD §2.8: "Dispensing moves a quantity from available to consumed; the
        compensation that follows an aborted filling run flips the dispensing row
        to `RETURNED` and moves exactly the same quantity back, so the ledger
        returns to its pre-dispensing values with zero drift."
        PRD §3.3: "A successful dispensing call moves quantity across the raw
        material ledger: the raw lot's `consumed_quantity_units` increases by
        `quantity_used` and its `available_quantity_units` decreases by the same
        amount, keeping `received_quantity_units` equal to the sum of the two."
        PRD §2.8: "The invariant is that `received_quantity_units` always equals
        `available_quantity_units` plus `consumed_quantity_units`."

        Design: Difficulty/compensating_invariant/fill_run_abort_restores_material_quantity_conservation_over_two_cycles
        """
        setup = _two_material_setup(api)
        antibody_id = setup["antibody"]["lot"]["id"]
        buffer_id = setup["buffer"]["lot"]["id"]

        for cycle in range(2):
            _dispense_both(api, setup)
            drawn_antibody = _material_lot(api, antibody_id)
            drawn_buffer = _material_lot(api, buffer_id)
            # Every cycle draws the same quantities from the same starting
            # values, so the mid-cycle ledger is identical each time.
            assert drawn_antibody["available_quantity_units"] == 750.00
            assert drawn_antibody["consumed_quantity_units"] == 250.00
            assert drawn_buffer["available_quantity_units"] == 400.00
            assert drawn_buffer["consumed_quantity_units"] == 100.00
            assertions.assert_material_quantity_conservation(drawn_antibody)
            assertions.assert_material_quantity_conservation(drawn_buffer)

            _run_and_abort(api, setup, abort_reason=f"Deviation {cycle + 1}")

            restored_antibody = _material_lot(api, antibody_id)
            restored_buffer = _material_lot(api, buffer_id)
            assert restored_antibody["available_quantity_units"] == 1000.00
            assert restored_antibody["consumed_quantity_units"] == 0.00
            assert restored_buffer["available_quantity_units"] == 500.00
            assert restored_buffer["consumed_quantity_units"] == 0.00
            assertions.assert_material_quantity_conservation(restored_antibody)
            assertions.assert_material_quantity_conservation(restored_buffer)

        final_lot = validate_success(api.get_reagent_lot(
            setup["lot"]["id"], PRODUCTION_OPERATOR), 200)
        assert final_lot["disposition_status"] == "PLANNED"
        assert final_lot["filled_units"] == 0
        assertions.assert_reagent_lot_unit_conservation(final_lot)

    def test_returned_rows_survive_both_cycles_and_leave_consumption_at_zero(self, api):
        """PRD §2.8: "`RETURNED` rows are excluded from `consumed_quantity_units`
        but are never deleted, so the audit trail survives the compensation."
        PRD §3.1: "Every dispensing record ever drawn from a raw material lot
        remains readable against that lot, `CONSUMED` and `RETURNED` rows alike,
        filterable by `status`."
        PRD §3.3: "The dispensing rows of a finished lot are listable and
        filterable by `status` and by `component_role`."

        Design: Difficulty/compensating_invariant/fill_run_abort_restores_material_quantity_conservation_over_two_cycles
        """
        setup = _two_material_setup(api)
        antibody_id = setup["antibody"]["lot"]["id"]
        buffer_id = setup["buffer"]["lot"]["id"]
        _dispense_both(api, setup)
        _run_and_abort(api, setup, abort_reason="First deviation")
        _dispense_both(api, setup)
        _run_and_abort(api, setup, abort_reason="Second deviation")

        all_rows, meta = validate_paginated(api.list_reagent_lot_components(
            setup["lot"]["id"], PRODUCTION_OPERATOR))
        # Two cycles of two dispensing calls: four rows, none of them deleted.
        assert len(all_rows) == 4
        assertions.assert_paginated_meta(meta, expected_total=4)
        assert {row["status"] for row in all_rows} == {"RETURNED"}

        still_consumed, _ = validate_paginated(api.list_reagent_lot_components(
            setup["lot"]["id"], PRODUCTION_OPERATOR,
            params={"status": "CONSUMED"}))
        assert still_consumed == []

        for material_lot_id, quantity in ((antibody_id, 250.00),
                                          (buffer_id, 100.00)):
            returned, _ = validate_paginated(api.list_material_lot_components(
                material_lot_id, QC_ANALYST, params={"status": "RETURNED"}))
            assert len(returned) == 2
            assert [row["quantity_used"] for row in returned] == \
                [quantity, quantity]
            assert _material_lot(api, material_lot_id)["consumed_quantity_units"] \
                == 0.00


def _released_lot_of_five_hundred(api) -> dict:
    """A released, available finished lot holding exactly 500 filled units."""
    return fixtures.released_reagent_lot(
        api, lot_overrides={"planned_units": 500},
        run_overrides={"planned_fill_units": 500})


def _order_for(api, bundle, requested_units: int) -> dict:
    return fixtures.create_distribution_order(
        api, bundle["product"]["id"], requested_units=requested_units)


def _reagent_lot(api, lot_id: str) -> dict:
    return validate_success(api.get_reagent_lot(lot_id, QA_RELEASER), 200)


def _assert_lot_buckets(lot: dict, *, available: int, allocated: int) -> None:
    """The four finished-goods buckets, then the ledger invariant over them."""
    assert lot["filled_units"] == 500
    assert lot["available_units"] == available
    assert lot["allocated_units"] == allocated
    assert lot["shipped_units"] == 0
    assert lot["quarantined_units"] == 0
    assertions.assert_reagent_lot_unit_conservation(lot)


class TestAllocationCancelRestoresReagentLotUnitConservation:

    def test_allocation_moves_units_from_available_to_allocated(self, api):
        """PRD §3.9: "Each drawn lot has its `available_units` reduced and its
        `allocated_units` increased by that reservation's `allocated_units`,
        preserving the finished-goods ledger."
        PRD §3.9: "From each candidate it takes the smaller of the outstanding
        need and that candidate's `available_units`, records the pair of candidate
        and quantity taken, assigns `sequence_index` values 1, 2, 3 and so on in
        draw order, and reduces the need by the quantity taken."
        PRD §2.8: "The invariant is that `filled_units` always equals
        `available_units` plus `allocated_units` plus `shipped_units` plus
        `quarantined_units`."

        Design: Difficulty/compensating_invariant/allocation_cancel_restores_reagent_lot_unit_conservation_with_replay
        """
        bundle = _released_lot_of_five_hundred(api)
        _assert_lot_buckets(bundle["lot"], available=500, allocated=0)
        order = _order_for(api, bundle, 200)

        allocated = validate_success(api.allocate_distribution_order(
            order["id"], DISTRIBUTION_PLANNER), 200)
        assertions.assert_distribution_order(allocated)
        assert allocated["status"] == "ALLOCATED"
        assert allocated["allocated_units"] == 200
        assert allocated["shortfall_units"] == 0
        assertions.assert_order_shortfall_consistent(allocated)

        reservations, meta = validate_paginated(
            api.list_distribution_order_allocations(order["id"],
                                                    DISTRIBUTION_PLANNER))
        assert len(reservations) == 1
        assertions.assert_allocation(reservations[0])
        assert reservations[0]["status"] == "RESERVED"
        assert reservations[0]["allocated_units"] == 200
        assert reservations[0]["sequence_index"] == 1
        assert reservations[0]["reagent_lot_id"] == bundle["lot"]["id"]
        assertions.assert_paginated_meta(meta, expected_total=1)

        # 500 filled, 200 reserved: 300 left available.
        _assert_lot_buckets(_reagent_lot(api, bundle["lot"]["id"]),
                            available=300, allocated=200)

    def test_cancelling_the_reservation_restores_the_lot_counters(self, api):
        """PRD §3.9: "The reservation moves to the terminal `CANCELLED` state, the
        lot's `allocated_units` decreases and its `available_units` increases by
        exactly that reservation's `allocated_units` — restoring the lot's
        counters to their pre-allocation values with no drift, because cancelled
        reservations count towards none of the four ledger buckets — and the
        reservation's `version` increases by 1."
        PRD §2.8: "Reservations whose `status` is `CANCELLED` contribute to none
        of the four buckets, which is precisely what makes cancellation an exact
        compensation of allocation: the units land back in `available_units`."

        Design: Difficulty/compensating_invariant/allocation_cancel_restores_reagent_lot_unit_conservation_with_replay
        """
        bundle = _released_lot_of_five_hundred(api)
        order = _order_for(api, bundle, 200)
        fixtures.allocate_order(api, order["id"])
        reservation = fixtures.order_allocations(api, order["id"])[0]
        _assert_lot_buckets(_reagent_lot(api, bundle["lot"]["id"]),
                            available=300, allocated=200)

        cancelled = validate_success(api.cancel_allocation(
            reservation["id"], DISTRIBUTION_PLANNER,
            f.cancel_allocation_payload("Customer withdrew")), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["allocated_units"] == 200
        assert cancelled["version"] == reservation["version"] + 1

        # Exactly the 200 units the reservation held are back in available_units.
        _assert_lot_buckets(_reagent_lot(api, bundle["lot"]["id"]),
                            available=500, allocated=0)

    def test_a_cancelled_reservation_is_retained_and_holds_no_units(self, api):
        """PRD §2.8: "Reservations whose `status` is `CANCELLED` contribute to none
        of the four buckets, which is precisely what makes cancellation an exact
        compensation of allocation: the units land back in `available_units`."
        PRD §3.5: "Every reservation ever drawn from a finished lot remains
        readable against that lot in any status, filterable by `status`."

        Design: Difficulty/compensating_invariant/allocation_cancel_restores_reagent_lot_unit_conservation_with_replay
        """
        bundle = _released_lot_of_five_hundred(api)
        order = _order_for(api, bundle, 200)
        fixtures.allocate_order(api, order["id"])
        reservation = fixtures.order_allocations(api, order["id"])[0]
        fixtures.cancel_allocation(api, reservation["id"], "Customer withdrew")

        persisted = validate_success(api.get_allocation(
            reservation["id"], DISTRIBUTION_PLANNER), 200)
        assert persisted["status"] == "CANCELLED"
        assert persisted["allocated_units"] == 200
        assert persisted["sequence_index"] == 1

        on_lot, meta = validate_paginated(api.list_reagent_lot_allocations(
            bundle["lot"]["id"], QA_RELEASER, params={"status": "CANCELLED"}))
        assert [row["id"] for row in on_lot] == [reservation["id"]]
        assertions.assert_paginated_meta(meta, expected_total=1)
        _assert_lot_buckets(_reagent_lot(api, bundle["lot"]["id"]),
                            available=500, allocated=0)

    def test_the_parent_order_drops_to_partially_allocated(self, api):
        """PRD §3.9: "The parent order then recomputes its `allocated_units` and
        `shortfall_units`, and where the recomputed `allocated_units` has fallen
        below `requested_units` and the order was `ALLOCATED`, the order drops to
        `PARTIALLY_ALLOCATED` with its `version` increased by 1."
        PRD §3.9: "As an ongoing rule, an order's `allocated_units` is the sum of
        `allocated_units` over its reservations whose `status` is `RESERVED`,
        `SHIPPED` or `DELIVERED`, and its `shortfall_units` is `requested_units`
        minus that sum floored at 0."

        Design: Difficulty/compensating_invariant/allocation_cancel_restores_reagent_lot_unit_conservation_with_replay
        """
        bundle = _released_lot_of_five_hundred(api)
        order = _order_for(api, bundle, 200)
        allocated = fixtures.allocate_order(api, order["id"])
        reservation = fixtures.order_allocations(api, order["id"])[0]

        fixtures.cancel_allocation(api, reservation["id"], "Customer withdrew")

        recomputed = validate_success(api.get_distribution_order(
            order["id"], DISTRIBUTION_PLANNER), 200)
        # The only reservation left the RESERVED bucket, so the sum is 0 and the
        # shortfall is the whole requested quantity.
        assert recomputed["allocated_units"] == 0
        assert recomputed["shortfall_units"] == 200
        assert recomputed["status"] == "PARTIALLY_ALLOCATED"
        assert recomputed["version"] == allocated["version"] + 1
        assertions.assert_order_shortfall_consistent(recomputed)

    def test_the_replayed_allocation_reproduces_the_identical_draw(self, api):
        """PRD §3.9: "From each candidate it takes the smaller of the outstanding
        need and that candidate's `available_units`, records the pair of candidate
        and quantity taken, assigns `sequence_index` values 1, 2, 3 and so on in
        draw order, and reduces the need by the quantity taken."
        PRD §3.9: "A finished lot enters the pool only when all five of the
        following hold: its `product_specification_id` equals the order's, its
        `disposition_status` is `RELEASED`, its `distribution_status` is
        `AVAILABLE`, its `available_units` is greater than 0, and its remaining
        shelf life in whole days is at least `floor_days` — the boundary is
        inclusive, so a lot with exactly `floor_days` remaining is eligible."
        PRD §3.9: "Each drawn lot has its `available_units` reduced and its
        `allocated_units` increased by that reservation's `allocated_units`,
        preserving the finished-goods ledger."

        Design: Difficulty/compensating_invariant/allocation_cancel_restores_reagent_lot_unit_conservation_with_replay
        """
        bundle = _released_lot_of_five_hundred(api)
        first_order = _order_for(api, bundle, 200)
        second_order = _order_for(api, bundle, 200)
        fixtures.allocate_order(api, first_order["id"])
        first_reservation = fixtures.order_allocations(api,
                                                       first_order["id"])[0]
        fixtures.cancel_allocation(api, first_reservation["id"],
                                   "Customer withdrew")

        replayed = validate_success(api.allocate_distribution_order(
            second_order["id"], DISTRIBUTION_PLANNER), 200)
        assert replayed["status"] == "ALLOCATED"
        assert replayed["allocated_units"] == 200
        assert replayed["shortfall_units"] == 0

        reservations = fixtures.order_allocations(api, second_order["id"])
        assert len(reservations) == 1
        # The same lot is drawn again, in the same quantity, at the same rank.
        assert reservations[0]["reagent_lot_id"] == bundle["lot"]["id"]
        assert reservations[0]["allocated_units"] == 200
        assert reservations[0]["sequence_index"] == 1
        assert reservations[0]["status"] == "RESERVED"
        assert reservations[0]["id"] != first_reservation["id"]
        _assert_lot_buckets(_reagent_lot(api, bundle["lot"]["id"]),
                            available=300, allocated=200)

    def test_a_second_cancel_of_the_same_reservation_is_refused(self, api):
        """PRD §3.9: "It requires the reservation to be `RESERVED` and accepts an
        optional `reason`."
        PRD §2.6: "The code is the owning aggregate's own state code —
        `ERR_MATERIAL_LOT_STATE_INVALID`, `ERR_PRODUCT_STATE_INVALID`,
        `ERR_DESIGN_RECORD_STATE_INVALID`, `ERR_REAGENT_LOT_STATE_INVALID`,
        `ERR_FILL_RUN_STATE_INVALID`, `ERR_STABILITY_STUDY_STATE_INVALID`,
        `ERR_BRIDGING_STUDY_STATE_INVALID`, `ERR_COMPLAINT_STATE_INVALID`,
        `ERR_ORDER_STATE_INVALID` or `ERR_ALLOCATION_STATE_INVALID` — all with
        HTTP 409."
        PRD §2.8: "Reservations whose `status` is `CANCELLED` contribute to none
        of the four buckets, which is precisely what makes cancellation an exact
        compensation of allocation: the units land back in `available_units`."

        Design: Difficulty/compensating_invariant/allocation_cancel_restores_reagent_lot_unit_conservation_with_replay
        """
        bundle = _released_lot_of_five_hundred(api)
        order = _order_for(api, bundle, 200)
        fixtures.allocate_order(api, order["id"])
        reservation = fixtures.order_allocations(api, order["id"])[0]
        cancelled = fixtures.cancel_allocation(api, reservation["id"],
                                               "Customer withdrew")

        validate_error(api.cancel_allocation(
            reservation["id"], DISTRIBUTION_PLANNER,
            f.cancel_allocation_payload("Cancelled twice")),
            "ERR_ALLOCATION_STATE_INVALID")

        # A refused compensation must not compensate a second time.
        unchanged = validate_success(api.get_allocation(
            reservation["id"], DISTRIBUTION_PLANNER), 200)
        assert unchanged["status"] == "CANCELLED"
        assert unchanged["version"] == cancelled["version"]
        _assert_lot_buckets(_reagent_lot(api, bundle["lot"]["id"]),
                            available=500, allocated=0)

    def test_two_allocate_and_cancel_cycles_leave_no_drift(self, api):
        """PRD §2.8: "Reservations whose `status` is `CANCELLED` contribute to none
        of the four buckets, which is precisely what makes cancellation an exact
        compensation of allocation: the units land back in `available_units`."
        PRD §2.8: "The invariant is that `filled_units` always equals
        `available_units` plus `allocated_units` plus `shipped_units` plus
        `quarantined_units`."
        PRD §3.9: "The reservation moves to the terminal `CANCELLED` state, the
        lot's `allocated_units` decreases and its `available_units` increases by
        exactly that reservation's `allocated_units` — restoring the lot's
        counters to their pre-allocation values with no drift, because cancelled
        reservations count towards none of the four ledger buckets — and the
        reservation's `version` increases by 1."

        Design: Difficulty/compensating_invariant/allocation_cancel_restores_reagent_lot_unit_conservation_with_replay
        """
        bundle = _released_lot_of_five_hundred(api)
        lot_id = bundle["lot"]["id"]
        orders = [_order_for(api, bundle, 200), _order_for(api, bundle, 200)]

        for order in orders:
            fixtures.allocate_order(api, order["id"])
            # Each cycle draws the same 200 units from the same 500-unit lot.
            _assert_lot_buckets(_reagent_lot(api, lot_id), available=300,
                                allocated=200)
            reservation = fixtures.order_allocations(api, order["id"])[0]
            assert reservation["allocated_units"] == 200
            assert reservation["sequence_index"] == 1

            fixtures.cancel_allocation(api, reservation["id"], "Customer withdrew")
            _assert_lot_buckets(_reagent_lot(api, lot_id), available=500,
                                allocated=0)
            closed = validate_success(api.get_distribution_order(
                order["id"], DISTRIBUTION_PLANNER), 200)
            assert closed["allocated_units"] == 0
            assert closed["shortfall_units"] == 200
            assert closed["status"] == "PARTIALLY_ALLOCATED"

        # Both cancelled reservations are still on file against the lot, and none
        # of them holds a single unit.
        cancelled_rows, meta = validate_paginated(
            api.list_reagent_lot_allocations(lot_id, QA_RELEASER,
                                             params={"status": "CANCELLED"}))
        assert len(cancelled_rows) == 2
        assertions.assert_paginated_meta(meta, expected_total=2)
        _assert_lot_buckets(_reagent_lot(api, lot_id), available=500,
                            allocated=0)
