"""Recording inspection deficiencies: the gates, the deduction and the cascade.

A deduction is the product of five inputs read from three entities at creation
time, and one record travels five links out to a sweep the request never names.
"""

from test_helpers import (
    ApiErrorId,
    assert_created,
    assert_error,
    assert_fields,
    assert_instant,
    assert_integer,
    assert_ok,
    assert_total_count,
    assert_two_decimals,
    constants as K,
    factories as F,
    fixtures as X,
)

CEDAR_UNIT = [
    {"unit_number": "101", "bedroom_count": 1, "occupancy_status": "OCCUPIED"}
]
CEDAR_TWO_UNITS = [
    {"unit_number": "101", "bedroom_count": 1, "occupancy_status": "OCCUPIED"},
    {"unit_number": "102", "bedroom_count": 1, "occupancy_status": "OCCUPIED"},
]
MAPLE_MIXED_UNITS = [
    {
        "unit_number": "101",
        "bedroom_count": 2,
        "occupancy_status": "OCCUPIED",
        "occupant_display_name": "Household 101",
    },
    {"unit_number": "102", "bedroom_count": 1, "occupancy_status": "VACANT"},
]
MAPLE_TWO_OCCUPIED = [
    {"unit_number": "101", "bedroom_count": 2, "occupancy_status": "OCCUPIED"},
    {"unit_number": "102", "bedroom_count": 1, "occupancy_status": "OCCUPIED"},
]
MAPLE_ONE_UNIT = [
    {
        "unit_number": "101",
        "bedroom_count": 2,
        "occupancy_status": "OCCUPIED",
        "occupant_display_name": "Household 101",
    }
]
ALT_STANDARD = {
    "code": "ALT-2026",
    "name": "Alternate 2026",
    "effective_date": "2026-02-01T00:00:00.000Z",
}
SEV_UNIT_DUE_AT = "2026-10-10T10:00:00.000Z"
VACANT_OBSERVED_AT = "2026-09-10T11:10:00.000Z"
RECURRENCE_OBSERVED_AT = "2026-09-10T12:00:00.000Z"
RECURRENCE_DUE_AT = "2026-09-11T12:00:00.000Z"
LIFE_THREATENING_DUE_AT = "2026-09-11T10:00:00.000Z"
NOTIFIED_ONLY_OBSERVED_AT = "2026-09-10T10:30:00.000Z"
SWEEP_WORK_ORDER_DUE_AT = "2026-09-02T09:00:00.000Z"
ESCALATED_WORK_ORDER_DUE_AT = "2026-09-01T09:00:00.000Z"
SWEEP_CORRECTED_AT = "2026-08-04T09:00:00.000Z"


def _occupancy_pair(api):
    """One life-threatening finding on an OCCUPIED unit and one on a VACANT one."""
    bundle = X.ready_to_record(
        api, K.MAPLE_COURT, MAPLE_MIXED_UNITS, ("LT_GAS",)
    )
    recorded = X.record_deficiencies(
        api,
        bundle["inspection_id"],
        [
            {
                "defect_definition_id": bundle["definition_ids"]["LT_GAS"],
                "unit_id": bundle["unit_ids"]["101"],
                "observed_at": K.OBSERVED_AT_1,
            },
            {
                "defect_definition_id": bundle["definition_ids"]["LT_GAS"],
                "unit_id": bundle["unit_ids"]["102"],
                "observed_at": VACANT_OBSERVED_AT,
            },
        ],
    )
    bundle["occupied_row"] = recorded["deficiencies"][0]
    bundle["vacant_row"] = recorded["deficiencies"][1]
    bundle["version"] = recorded["version"]
    return bundle


def _recurrence_on_the_occupied_unit(api):
    """The pair above, plus the recurrence that supersedes the occupied row."""
    bundle = _occupancy_pair(api)
    bundle["recurrence"] = assert_created(
        api.record_deficiency(
            bundle["inspection_id"],
            F.deficiency_payload(
                bundle["version"],
                bundle["definition_ids"]["LT_GAS"],
                bundle["unit_ids"]["101"],
                "UNIT",
                observed_at=RECURRENCE_OBSERVED_AT,
                supersedes_deficiency_id=bundle["occupied_row"]["id"],
                note="Recurrence of the same gas leak",
            ),
            X.INSPECTOR,
        )
    )
    return bundle


def _one_granted_one_merely_notified(api):
    """Two sampled units where only unit 101 has granted entry."""
    bundle = X.adopted_standard(api, ("LT_GAS", "SEV_WINDOW"))
    bundle.update(X.property_with_units(api, K.MAPLE_COURT, MAPLE_TWO_OCCUPIED))
    bundle.update(
        X.in_progress_inspection(api, bundle["property_id"], bundle["standard_id"])
    )
    bundle["granted_slot"] = bundle["slots"][bundle["unit_ids"]["101"]]
    bundle["notified_slot"] = bundle["slots"][bundle["unit_ids"]["102"]]
    assert_ok(
        api.record_access(
            bundle["granted_slot"]["id"],
            F.access_payload("GRANTED", recorded_at=K.ACCESS_RECORDED_AT),
            X.INSPECTOR,
        )
    )
    recorded = X.record_deficiencies(
        api,
        bundle["inspection_id"],
        [
            {
                "defect_definition_id": bundle["definition_ids"]["SEV_WINDOW"],
                "unit_id": bundle["unit_ids"]["101"],
                "observed_at": K.OBSERVED_AT_1,
            }
        ],
    )
    bundle["first_row"] = recorded["deficiencies"][0]
    bundle["version"] = recorded["version"]
    return bundle


def _sweep_work_order_then_inspection(api):
    """An open routine work order from a sweep, plus a live inspection."""
    bundle = X.sweep_lifecycle(
        api,
        "SEV_WINDOW",
        K.MAPLE_COURT,
        MAPLE_ONE_UNIT,
        definition_codes=("LT_GAS", "SEV_WINDOW"),
        observed_at=K.SWEEP_OBSERVED_AT_1,
    )
    bundle.update(
        X.inspection_with_access(api, bundle["property_id"], bundle["standard_id"])
    )
    bundle["work_order_before"] = X.read_work_order(api, bundle["work_order_id"])
    bundle["sweep_before"] = X.read_sweep(api, bundle["sweep_id"])
    return bundle


class TestTheAccessGate:
    """A UNIT-area finding is decided by the slot covering that unit."""

    def test_a_severe_finding_lands_once_the_slot_granted_entry(self, api):
        """8.00 x 2.0 SEVERE x 1.0 UNIT deducts 16.00 and hands back the token.

        PRD: "The raw deduction is the `base_point_value` multiplied by the
        severity multiplier, by the area multiplier, by the recurrence multiplier
        and by the occupancy multiplier."

        PRD: "the inspection's `version` then increments by 1, and that
        post-increment value is written back onto the new deficiency as
        `inspection_version_after_record`, giving the client the exact token it
        needs for its next record."

        Design: Corner/validations/unit_deficiency_accepted_once_the_slot_grants_access
        """
        bundle = X.ready_to_record(api, K.CEDAR_WALK, CEDAR_UNIT)
        before = X.read_inspection(api, bundle["inspection_id"])

        response = api.record_deficiency(
            bundle["inspection_id"],
            F.deficiency_payload(
                before["version"],
                bundle["definition_ids"]["SEV_WINDOW"],
                bundle["unit_ids"]["101"],
                "UNIT",
                observed_at=K.OBSERVED_AT_1,
            ),
            X.INSPECTOR,
        )

        row = assert_created(response)
        assert_fields(row, source="INSPECTION", status="OPEN", severity="SEVERE")
        assert_two_decimals(row["points_deducted"], 16.00, "points_deducted")
        assert_instant(
            row["correction_due_at"], SEV_UNIT_DUE_AT, "correction_due_at"
        )
        assert_integer(
            row["inspection_version_after_record"],
            before["version"] + 1,
            "inspection_version_after_record",
        )
        after = X.read_inspection(api, bundle["inspection_id"])
        assert_integer(after["version"], before["version"] + 1, "version")
        assert_two_decimals(after["unit_area_points"], 16.00, "unit_area_points")
        assert_two_decimals(
            after["total_points_deducted"], 16.00, "total_points_deducted"
        )
        owning_property = X.read_property(api, bundle["property_id"])
        assert_fields(
            owning_property, open_severe_count=1, readiness_posture="READY"
        )

    def test_a_finding_on_a_unit_holding_no_slot_is_not_in_the_sample(self, api):
        """Unit 102 exists on the property but was never drawn.

        PRD: "The membership check that follows requires the cited unit's
        `property_id` to equal the inspection's `property_id` and the unit to be
        held by an `ACTIVE` slot of that inspection; a unit belonging to another
        property, or one never drawn at all, is rejected with
        `ERR_UNIT_NOT_IN_SAMPLE` (HTTP 422)."

        Design: Corner/errors/recording_a_finding_on_an_unsampled_unit_is_rejected_as_not_in_sample
        """
        bundle = X.ready_to_record(api, K.CEDAR_WALK, CEDAR_TWO_UNITS)
        before = X.read_inspection(api, bundle["inspection_id"])
        assert_fields(before, sample_tier_value=1, sample_size=1)
        assert_total_count(
            api.list_sample_selections(
                X.INSPECTOR,
                inspection_id=bundle["inspection_id"],
                unit_id=bundle["unit_ids"]["102"],
            ),
            0,
        )

        response = api.record_deficiency(
            bundle["inspection_id"],
            F.deficiency_payload(
                before["version"],
                bundle["definition_ids"]["SEV_WINDOW"],
                bundle["unit_ids"]["102"],
                "UNIT",
                observed_at=K.OBSERVED_AT_1,
            ),
            X.INSPECTOR,
        )

        assert_error(response, ApiErrorId.UNIT_NOT_IN_SAMPLE)
        after = X.read_inspection(api, bundle["inspection_id"])
        assert_integer(after["version"], before["version"], "version")
        assert_two_decimals(after["unit_area_points"], 0.00, "unit_area_points")
        assert_total_count(
            api.list_deficiencies(
                X.INSPECTOR, inspection_id=bundle["inspection_id"]
            ),
            0,
        )

    def test_a_definition_from_a_second_standard_answers_before_the_gate(self, api):
        """The pinned standard is checked while the slot is still only notified.

        PRD: "The cited definition's `standard_id` must equal the `standard_id`
        pinned on the inspection at creation; a definition drawn from any other
        standard - including a newer standard that is now the `ADOPTED` one - is
        rejected with `ERR_DEFECT_DEFINITION_STANDARD_MISMATCH` (HTTP 422)."

        Design: Corner/errors/recording_a_finding_from_a_foreign_standard_is_rejected_as_standard_mismatch
        """
        bundle = X.adopted_standard(api, ("LT_GAS", "SEV_WINDOW"))
        foreign = X.adopted_standard(
            api, ("LT_GAS", "SEV_WINDOW"), **ALT_STANDARD
        )
        bundle.update(X.property_with_units(api, K.CEDAR_WALK, CEDAR_UNIT))
        bundle.update(
            X.in_progress_inspection(
                api, bundle["property_id"], bundle["standard_id"]
            )
        )
        before = X.read_inspection(api, bundle["inspection_id"])
        assert_fields(
            bundle["slots"][bundle["unit_ids"]["101"]], access_status="NOTIFIED"
        )

        response = api.record_deficiency(
            bundle["inspection_id"],
            F.deficiency_payload(
                before["version"],
                foreign["definition_ids"]["SEV_WINDOW"],
                bundle["unit_ids"]["101"],
                "UNIT",
                observed_at=K.OBSERVED_AT_1,
            ),
            X.INSPECTOR,
        )

        assert_error(response, ApiErrorId.DEFECT_DEFINITION_STANDARD_MISMATCH)
        after = X.read_inspection(api, bundle["inspection_id"])
        assert_integer(after["version"], before["version"], "version")
        assert_total_count(
            api.list_deficiencies(
                X.INSPECTOR, inspection_id=bundle["inspection_id"]
            ),
            0,
        )


class TestTheSevereCounter:
    """`open_severe_count` is a running aggregate, not an increment."""

    def test_correcting_one_of_two_findings_drops_the_tally_back(self, api):
        """CORRECTED leaves the counted set, so the tally falls from 2 to 1.

        PRD: "The property recomputes `open_life_threatening_count`,
        `overdue_life_threatening_count` and `open_severe_count` and re-derives
        `readiness_posture`; the cited unit recomputes `open_deficiency_count`;
        and the `version` of the deficiency and of the property each increment by
        1."

        Design: Corner/calculations/property_severe_counter_tracks_additions_and_reversals
        """
        bundle = X.sweep_lifecycle(
            api,
            "SEV_WINDOW",
            K.CEDAR_WALK,
            CEDAR_UNIT,
            observed_at=K.SWEEP_OBSERVED_AT_1,
        )
        second = X.record_finding(
            api,
            bundle["property_id"],
            bundle["sweep_id"],
            bundle["sweep_version"],
            bundle["definition_ids"]["SEV_WINDOW"],
            bundle["unit_ids"]["101"],
            observed_at=K.SWEEP_OBSERVED_AT_2,
        )
        assert_fields(
            X.read_property(api, bundle["property_id"]), open_severe_count=2
        )

        response = api.record_correction(
            second["deficiency_id"],
            F.correction_payload(
                corrected_at=SWEEP_CORRECTED_AT, note="Sash replaced"
            ),
            bundle["owner_headers"],
        )

        corrected = assert_ok(response)
        assert_fields(corrected, status="CORRECTED")
        assert_instant(
            corrected["corrected_at"], SWEEP_CORRECTED_AT, "corrected_at"
        )
        owning_property = X.read_property(api, bundle["property_id"])
        assert_fields(
            owning_property,
            open_severe_count=1,
            open_life_threatening_count=0,
            readiness_posture="READY",
        )
        assert_fields(
            X.read_unit(api, bundle["unit_ids"]["101"]), open_deficiency_count=1
        )


class TestTheFiveFactorDeduction:
    """Five inputs from three entities, rounded then capped at 40.00."""

    def test_the_occupancy_factor_applies_only_to_the_occupied_unit(self, api):
        """The same definition deducts 36.00 on unit 101 and 30.00 on unit 102.

        PRD: "The occupancy multiplier is 1.2 when all three of the following
        hold - the cited definition's `severity` is `LIFE_THREATENING`, the
        observation carries a non-null `unit_id`, and that unit's
        `occupancy_status` is `OCCUPIED` - and 1.0 in every other case."

        PRD: "`correction_due_at` set to the `observed_at` instant advanced by the
        definition's `correction_deadline_hours` - which for a `LIFE_THREATENING`
        defect is always exactly 24 hours, the twenty-four-hour obligation."

        Design: Difficulty/combinatorial_formula/deficiency_points_five_factor_product_with_occupancy_branch_and_cap
        """
        bundle = _occupancy_pair(api)

        occupied = X.read_deficiency(api, bundle["occupied_row"]["id"])
        vacant = X.read_deficiency(api, bundle["vacant_row"]["id"])

        assert_two_decimals(occupied["points_deducted"], 36.00, "points_deducted")
        assert_fields(occupied, recurrence_applied=False, severity="LIFE_THREATENING")
        assert_instant(
            occupied["correction_due_at"],
            LIFE_THREATENING_DUE_AT,
            "correction_due_at",
        )
        assert_two_decimals(vacant["points_deducted"], 30.00, "points_deducted")
        assert_fields(vacant, recurrence_applied=False)

    def test_the_recurrence_factor_pushes_the_raw_value_onto_the_cap(self, api):
        """A raw 54.00 is rounded and then clamped to the 40.00 ceiling.

        PRD: "The recurrence multiplier is 1.5 when the observation carries a
        non-null `supersedes_deficiency_id`, naming the earlier deficiency this
        one recurs from, and 1.0 otherwise."

        PRD: "That raw value is rounded half up to two decimal places, and only
        then is the per-deficiency cap of `40.00` applied by taking the smaller of
        the cap and the rounded value; the result is stored as `points_deducted`.
        Rounding strictly precedes the cap."

        Design: Difficulty/combinatorial_formula/deficiency_points_five_factor_product_with_occupancy_branch_and_cap
        """
        bundle = _recurrence_on_the_occupied_unit(api)

        recurrence = X.read_deficiency(api, bundle["recurrence"]["id"])

        assert_two_decimals(recurrence["points_deducted"], 40.00, "points_deducted")
        assert recurrence["points_deducted"] != 54.00
        assert_fields(recurrence, recurrence_applied=True, status="OPEN")
        assert_instant(
            recurrence["correction_due_at"], RECURRENCE_DUE_AT, "correction_due_at"
        )

    def test_the_three_rows_add_up_on_the_owning_inspection(self, api):
        """36.00 plus 30.00 plus the capped 40.00 make 106.00 of unit points.

        PRD: "The second link makes the owning inspection recompute
        `unit_area_points` as the sum of `points_deducted` over its deficiencies
        whose `inspectable_area` is `UNIT` and whose `status` is not `VOIDED`"

        Design: Difficulty/combinatorial_formula/deficiency_points_five_factor_product_with_occupancy_branch_and_cap
        """
        bundle = _recurrence_on_the_occupied_unit(api)

        inspection = X.read_inspection(api, bundle["inspection_id"])

        assert_two_decimals(
            inspection["unit_area_points"], 106.00, "unit_area_points"
        )
        assert_two_decimals(
            inspection["total_points_deducted"], 106.00, "total_points_deducted"
        )
        assert_integer(
            inspection["life_threatening_count"], 3, "life_threatening_count"
        )
        assert_total_count(
            api.list_deficiencies(
                X.INSPECTOR, inspection_id=bundle["inspection_id"]
            ),
            3,
        )


class TestTheSlotStateDecidesTheWrite:
    """The third entity, not the inspection or the unit, holds the gate."""

    def test_a_merely_notified_slot_refuses_the_finding(self, api):
        """Unit 102 is in the sample but nobody has been let in yet.

        PRD: "for a `UNIT`-area observation, the cited unit must be held by a
        sample slot of this inspection whose `selection_status` is `ACTIVE` and
        whose `access_status` is `GRANTED`; a slot in any other access position
        yields `ERR_UNIT_ACCESS_NOT_GRANTED` (HTTP 409), and this check precedes
        the broader membership check, so a notified-but-not-yet-entered unit
        reports the access error."

        Design: Difficulty/cross_entity_state_dependency/unit_deficiency_rejected_when_that_units_selection_is_only_notified
        """
        bundle = _one_granted_one_merely_notified(api)

        response = api.record_deficiency(
            bundle["inspection_id"],
            F.deficiency_payload(
                bundle["version"],
                bundle["definition_ids"]["SEV_WINDOW"],
                bundle["unit_ids"]["102"],
                "UNIT",
                observed_at=NOTIFIED_ONLY_OBSERVED_AT,
            ),
            X.INSPECTOR,
        )

        assert_error(response, ApiErrorId.UNIT_ACCESS_NOT_GRANTED)
        assert_fields(
            X.read_selection(api, bundle["notified_slot"]["id"]),
            access_status="NOTIFIED",
            selection_status="ACTIVE",
        )
        assert_fields(
            X.read_selection(api, bundle["granted_slot"]["id"]),
            access_status="GRANTED",
        )

    def test_the_refused_finding_leaves_the_first_one_standing(self, api):
        """The identical call on the granted unit had already been accepted.

        PRD: "The submitted `inspectable_area` must equal the cited definition's
        `inspectable_area`, and `unit_id` must be present exactly when the area is
        `UNIT`, else `ERR_AREA_MISMATCH` (HTTP 422)."

        PRD: "for a `UNIT`-area observation, the cited unit must be held by a
        sample slot of this inspection whose `selection_status` is `ACTIVE` and
        whose `access_status` is `GRANTED`; a slot in any other access position
        yields `ERR_UNIT_ACCESS_NOT_GRANTED` (HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/unit_deficiency_rejected_when_that_units_selection_is_only_notified
        """
        bundle = _one_granted_one_merely_notified(api)

        response = api.record_deficiency(
            bundle["inspection_id"],
            F.deficiency_payload(
                bundle["version"],
                bundle["definition_ids"]["SEV_WINDOW"],
                bundle["unit_ids"]["102"],
                "UNIT",
                observed_at=NOTIFIED_ONLY_OBSERVED_AT,
            ),
            X.INSPECTOR,
        )

        assert_error(response, ApiErrorId.UNIT_ACCESS_NOT_GRANTED)
        rows = assert_total_count(
            api.list_deficiencies(
                X.INSPECTOR, inspection_id=bundle["inspection_id"]
            ),
            1,
        )
        assert [row["id"] for row in rows] == [bundle["first_row"]["id"]]
        inspection = X.read_inspection(api, bundle["inspection_id"])
        assert_integer(inspection["version"], bundle["version"], "version")
        assert_two_decimals(
            inspection["unit_area_points"], 16.00, "unit_area_points"
        )


class TestTheFiveLinkRecordCascade:
    """One record reaches a sweep and a work order it never names."""

    def test_the_record_drives_the_property_to_restricted(self, api):
        """Links one to three: the row, the inspection totals, the posture.

        PRD: "The third link makes the property recompute
        `open_life_threatening_count` and `open_severe_count` and re-derive
        `readiness_posture` by the rules of §2.8 - one open life-threatening
        observation is enough to make the property `RESTRICTED`."

        PRD: "The occupancy multiplier is 1.2 when all three of the following
        hold - the cited definition's `severity` is `LIFE_THREATENING`, the
        observation carries a non-null `unit_id`, and that unit's
        `occupancy_status` is `OCCUPIED` - and 1.0 in every other case."

        Design: Difficulty/transitive_cascade/cascade_a_life_threatening_record_reaches_sweep_urgency_five_links
        """
        bundle = _sweep_work_order_then_inspection(api)
        before = X.read_inspection(api, bundle["inspection_id"])
        assert_fields(
            X.read_property(api, bundle["property_id"]), readiness_posture="READY"
        )

        response = api.record_deficiency(
            bundle["inspection_id"],
            F.deficiency_payload(
                before["version"],
                bundle["definition_ids"]["LT_GAS"],
                bundle["unit_ids"]["101"],
                "UNIT",
                observed_at=K.OBSERVED_AT_1,
            ),
            X.INSPECTOR,
        )

        row = assert_created(response)
        assert_fields(row, status="OPEN", severity="LIFE_THREATENING")
        assert_two_decimals(row["points_deducted"], 36.00, "points_deducted")
        assert_instant(
            row["correction_due_at"], LIFE_THREATENING_DUE_AT, "correction_due_at"
        )
        inspection = X.read_inspection(api, bundle["inspection_id"])
        assert_integer(
            inspection["life_threatening_count"], 1, "life_threatening_count"
        )
        assert_two_decimals(
            inspection["unit_area_points"], 36.00, "unit_area_points"
        )
        assert_integer(
            inspection["version"], before["version"] + 1, "version"
        )
        assert_integer(
            row["inspection_version_after_record"],
            inspection["version"],
            "inspection_version_after_record",
        )
        owning_property = X.read_property(api, bundle["property_id"])
        assert_fields(
            owning_property,
            open_life_threatening_count=1,
            overdue_life_threatening_count=0,
            readiness_posture="RESTRICTED",
        )

    def test_the_record_escalates_a_work_order_the_request_never_names(self, api):
        """Links four and five reach the sweep through its open work order.

        PRD: "The fourth link, triggered when that re-derivation lands on
        `RESTRICTED` or `FROZEN`, raises every work order on the property whose
        `repair_status` is `OPEN` to `priority_tier` `URGENT` and pulls each such
        `due_at` 24 hours earlier."

        PRD: "The fifth link makes every sweep owning one of those escalated work
        orders recompute `urgent_work_order_count` and increment its own `version`
        by 1."

        Design: Difficulty/transitive_cascade/cascade_a_life_threatening_record_reaches_sweep_urgency_five_links
        """
        bundle = _sweep_work_order_then_inspection(api)
        before = X.read_inspection(api, bundle["inspection_id"])
        assert_fields(bundle["work_order_before"], priority_tier="ROUTINE")
        assert_instant(
            bundle["work_order_before"]["due_at"],
            SWEEP_WORK_ORDER_DUE_AT,
            "due_at",
        )

        response = api.record_deficiency(
            bundle["inspection_id"],
            F.deficiency_payload(
                before["version"],
                bundle["definition_ids"]["LT_GAS"],
                bundle["unit_ids"]["101"],
                "UNIT",
                observed_at=K.OBSERVED_AT_1,
            ),
            X.INSPECTOR,
        )

        assert_created(response)
        work_order = X.read_work_order(api, bundle["work_order_id"])
        assert_fields(work_order, priority_tier="URGENT", repair_status="OPEN")
        assert_instant(
            work_order["due_at"], ESCALATED_WORK_ORDER_DUE_AT, "due_at"
        )
        assert_integer(
            work_order["version"],
            bundle["work_order_before"]["version"] + 1,
            "version",
        )
        sweep = X.read_sweep(api, bundle["sweep_id"])
        assert_integer(
            sweep["urgent_work_order_count"], 1, "urgent_work_order_count"
        )
        assert_integer(
            sweep["version"], bundle["sweep_before"]["version"] + 1, "version"
        )


class TestTheConcurrencyToken:
    """Only the version check catches a writer on the pre-cascade view."""

    def test_replaying_the_pre_cascade_version_is_stale(self, api):
        """The first record advanced the inspection out from under the client.

        PRD: "a client that reads an inspection, records one deficiency, and then
        attempts a second deficiency with the same `expected_inspection_version`
        will be rejected - the first record advanced the inspection."

        PRD: "The supplied `expected_inspection_version` must equal the
        inspection's current `version`, else `ERR_STALE_INSPECTION_VERSION`."

        Design: Corner/cross_cutting_complexity_layers/second_deficiency_with_the_pre_cascade_inspection_version_is_rejected_as_stale
        """
        bundle = X.ready_to_record(api, K.CEDAR_WALK, CEDAR_UNIT)
        first_version = X.read_inspection(api, bundle["inspection_id"])["version"]
        recorded = X.record_deficiencies(
            api,
            bundle["inspection_id"],
            [
                {
                    "defect_definition_id": bundle["definition_ids"]["SEV_WINDOW"],
                    "unit_id": bundle["unit_ids"]["101"],
                    "observed_at": K.OBSERVED_AT_1,
                }
            ],
            expected_version=first_version,
        )
        second_version = recorded["version"]
        assert_integer(second_version, first_version + 1, "version")

        response = api.record_deficiency(
            bundle["inspection_id"],
            F.deficiency_payload(
                first_version,
                bundle["definition_ids"]["SEV_WINDOW"],
                bundle["unit_ids"]["101"],
                "UNIT",
                observed_at=K.OBSERVED_AT_2,
            ),
            X.INSPECTOR,
        )

        assert_error(response, ApiErrorId.STALE_INSPECTION_VERSION)
        inspection = X.read_inspection(api, bundle["inspection_id"])
        assert_integer(inspection["version"], second_version, "version")
        assert_two_decimals(
            inspection["unit_area_points"], 16.00, "unit_area_points"
        )
        assert_total_count(
            api.list_deficiencies(
                X.INSPECTOR, inspection_id=bundle["inspection_id"]
            ),
            1,
        )
        assert_created(
            api.record_deficiency(
                bundle["inspection_id"],
                F.deficiency_payload(
                    second_version,
                    bundle["definition_ids"]["SEV_WINDOW"],
                    bundle["unit_ids"]["101"],
                    "UNIT",
                    observed_at=K.OBSERVED_AT_2,
                ),
                X.INSPECTOR,
            )
        )
        assert_two_decimals(
            X.read_inspection(api, bundle["inspection_id"])["unit_area_points"],
            32.00,
            "unit_area_points",
        )
