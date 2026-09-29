"""The owner's self-assessment sweep: planning windows and filing findings.

A sweep is the owner's own walk of the property, so its findings feed the very
same deficiency population that decides the property's readiness posture.
"""

from test_helpers import (
    ApiErrorId,
    assert_common_fields,
    assert_created,
    assert_error,
    assert_fields,
    assert_instant,
    assert_integer,
    assert_null,
    assert_ok,
    assert_pagination_meta,
    assert_property_state,
    assert_sweep_counters,
    assert_total_count,
    assert_two_decimals,
    constants as K,
    factories as F,
    fixtures as X,
)
from test_helpers.test_users import (
    make_platform_admin_headers,
    make_property_owner_headers,
)

ADMIN = make_platform_admin_headers()
SWEEP_CLOSED_AT = "2026-08-06T09:00:00.000Z"
ABANDONED_AT = "2026-08-03T09:00:00.000Z"


class TestSweepPlanning:
    """Planning a window, and the aggregate capacity that limits overlap."""

    def test_a_new_sweep_starts_planned_with_pinned_default_counters(self, api):
        """An unstarted sweep is vacuously fully verified at 100.00.

        PRD: "A planned sweep begins in `PLANNED` with `started_at` and
        `closed_at` null, with `generated_work_order_count`,
        `open_work_order_count`, `verified_work_order_count`,
        `void_work_order_count` and `urgent_work_order_count` all 0, and -
        because a sweep with no work orders is vacuously fully verified - with
        `closure_verified_rate` at `100.00` rather than at `0.00` or null."

        Design: Corner/state_machines/new_sweep_starts_planned_with_pinned_default_counters
        """
        bundle = X.property_with_units(
            api, K.CEDAR_WALK, [{"unit_number": "101", "bedroom_count": 1}]
        )

        response = api.create_sweep(
            F.sweep_payload(bundle["property_id"], planned_area_scope="UNIT_ONLY"),
            bundle["owner_headers"],
        )

        sweep = assert_created(response)
        assert_fields(sweep, status="PLANNED", planned_area_scope="UNIT_ONLY")
        assert_null(sweep, "started_at", "closed_at")
        assert_integer(
            sweep["open_work_order_count"], 0, "open_work_order_count"
        )
        assert_sweep_counters(sweep, 0, 0, 0, 0, 100.00)
        assert_common_fields(sweep, expected_version=1)

    def test_an_inverted_window_is_rejected_as_an_invalid_time_window(self, api):
        """A window ending before it starts is refused outright.

        PRD: "The `window_end` must be strictly after the `window_start`; an
        empty or inverted interval is rejected with `ERR_INVALID_TIME_WINDOW`
        (HTTP 422)."

        Design: Corner/errors/inverted_sweep_window_is_rejected_as_invalid_time_window
        """
        property_id = X.create_property(api, K.CEDAR_WALK)["id"]

        response = api.create_sweep(
            F.sweep_payload(
                property_id,
                window_start=K.SWEEP_WINDOW_END,
                window_end=K.SWEEP_WINDOW_START,
            ),
            make_property_owner_headers(property_id),
        )

        assert_error(response, ApiErrorId.INVALID_TIME_WINDOW)
        assert_total_count(api.list_sweeps(ADMIN, property_id=property_id), 0)

    def test_a_third_sweep_over_a_doubly_covered_instant_is_rejected(self, api):
        """Two live sweeps already cover 2026-08-15, so a third is refused.

        PRD: "At most two sweeps on a single property whose `status` is `PLANNED`
        or `IN_PROGRESS` may cover any single instant, measured on half-open
        windows that include `window_start` and exclude `window_end`. A third
        live sweep covering an instant already covered by two is rejected with
        `ERR_SWEEP_CAPACITY_EXCEEDED` (HTTP 409)".

        Design: Difficulty/resource_temporal_overlap/third_overlapping_sweep_rejected_by_aggregate_capacity_of_two
        """
        bundle = X.property_with_units(
            api,
            K.CEDAR_WALK,
            [
                {
                    "unit_number": "101",
                    "bedroom_count": 1,
                    "occupancy_status": "OCCUPIED",
                    "occupant_display_name": "Household 101",
                }
            ],
        )
        property_id = bundle["property_id"]
        owner = bundle["owner_headers"]
        first = X.in_progress_sweep(api, property_id)
        second = assert_created(
            api.create_sweep(
                F.sweep_payload(
                    property_id,
                    window_start="2026-08-10T00:00:00.000Z",
                    window_end="2026-08-25T00:00:00.000Z",
                    planned_area_scope="UNIT_ONLY",
                ),
                owner,
            )
        )

        response = api.create_sweep(
            F.sweep_payload(
                property_id,
                window_start="2026-08-14T00:00:00.000Z",
                window_end="2026-08-16T00:00:00.000Z",
                planned_area_scope="INSIDE_OUTSIDE",
            ),
            owner,
        )

        assert_error(response, ApiErrorId.SWEEP_CAPACITY_EXCEEDED)
        assert_fields(X.read_sweep(api, first["sweep_id"]), status="IN_PROGRESS")
        assert_fields(X.read_sweep(api, second["id"]), status="PLANNED")
        assert_total_count(api.list_sweeps(ADMIN, property_id=property_id), 2)

    def test_a_sweep_beginning_where_another_ends_shares_no_instant(self, api):
        """A window opening at 2026-08-25 clears the half-open predecessor.

        PRD: "a sweep that merely begins at the exact instant another ends does
        not share an instant with it and is therefore admitted."

        Design: Difficulty/resource_temporal_overlap/third_overlapping_sweep_rejected_by_aggregate_capacity_of_two
        """
        bundle = X.property_with_units(
            api,
            K.CEDAR_WALK,
            [
                {
                    "unit_number": "101",
                    "bedroom_count": 1,
                    "occupancy_status": "OCCUPIED",
                    "occupant_display_name": "Household 101",
                }
            ],
        )
        property_id = bundle["property_id"]
        owner = bundle["owner_headers"]
        X.in_progress_sweep(api, property_id)
        assert_created(
            api.create_sweep(
                F.sweep_payload(
                    property_id,
                    window_start="2026-08-10T00:00:00.000Z",
                    window_end="2026-08-25T00:00:00.000Z",
                    planned_area_scope="UNIT_ONLY",
                ),
                owner,
            )
        )

        response = api.create_sweep(
            F.sweep_payload(
                property_id,
                window_start="2026-08-25T00:00:00.000Z",
                window_end="2026-08-30T00:00:00.000Z",
                planned_area_scope="INSIDE_OUTSIDE",
            ),
            owner,
        )

        fourth = assert_created(response)
        assert_fields(fourth, status="PLANNED")
        assert_instant(
            fourth["window_start"], "2026-08-25T00:00:00.000Z", "window_start"
        )
        assert_total_count(api.list_sweeps(ADMIN, property_id=property_id), 3)

    def test_starting_an_abandoned_sweep_is_rejected(self, api):
        """Closing a never-started sweep abandons it, and abandonment is final.

        PRD: "From `PLANNED`, meaning a sweep that never started, the same
        operation instead moves `PLANNED -> ABANDONED`, stamping `closed_at` and
        incrementing the sweep's `version` by 1; the closure-rate floor is
        evaluated only on the `IN_PROGRESS` branch, and the abandonment branch
        touches neither the property's `last_sweep_closed_at` nor the property's
        `version`."

        Design: Corner/state_machines/start_an_abandoned_sweep_returns_invalid_state
        """
        bundle = X.property_with_units(
            api, K.CEDAR_WALK, [{"unit_number": "101", "bedroom_count": 1}]
        )
        property_id = bundle["property_id"]
        owner = bundle["owner_headers"]
        sweep_id = X.planned_sweep(api, property_id)["id"]
        abandoned = assert_ok(
            api.close_sweep(
                sweep_id, F.sweep_close_payload(closed_at=ABANDONED_AT), owner
            )
        )
        assert_fields(abandoned, status="ABANDONED")
        assert_instant(abandoned["closed_at"], ABANDONED_AT, "closed_at")

        response = api.start_sweep(
            sweep_id,
            F.sweep_start_payload(started_at="2026-08-04T09:00:00.000Z"),
            owner,
        )

        assert_error(response, ApiErrorId.SWEEP_INVALID_STATE)
        reread = X.read_sweep(api, sweep_id)
        assert_fields(reread, status="ABANDONED")
        assert_null(reread, "started_at")
        assert_null(X.read_property(api, property_id), "last_sweep_closed_at")


class TestSweepFindings:
    """Filing a finding writes a deficiency, a work order and every counter."""

    def test_a_moderate_inside_finding_deducts_four_point_eight_points(self, api):
        """A base of 6.00 at MODERATE severity in an INSIDE area gives 4.80.

        PRD: "The severity multiplier is 3.0 for `LIFE_THREATENING`, 2.0 for
        `SEVERE`, 1.0 for `MODERATE` and 0.5 for `LOW`. The area multiplier is
        1.0 for `UNIT`, 0.8 for `INSIDE` and 0.6 for `OUTSIDE`."

        Design: Corner/calculations/moderate_inside_finding_deducts_four_point_eight_points
        """
        bundle = X.adopted_standard(api, ("LT_GAS", "MOD_HANDRAIL"))
        bundle.update(
            X.property_with_units(
                api, K.CEDAR_WALK, [{"unit_number": "101", "bedroom_count": 1}]
            )
        )
        sweep = X.in_progress_sweep(api, bundle["property_id"])

        response = api.record_finding(
            sweep["sweep_id"],
            F.finding_payload(
                sweep["sweep_version"],
                bundle["definition_ids"]["MOD_HANDRAIL"],
                inspectable_area="INSIDE",
                observed_at=K.SWEEP_OBSERVED_AT_1,
            ),
            bundle["owner_headers"],
        )

        work_order = assert_created(response)
        deficiency = X.read_deficiency(api, work_order["deficiency_id"])
        assert_two_decimals(
            deficiency["points_deducted"], 4.80, "points_deducted"
        )
        assert_fields(
            deficiency,
            inspectable_area="INSIDE",
            status="OPEN",
            source="SELF_ASSESSMENT",
        )
        assert_null(deficiency, "unit_id", "inspection_id")
        assert_instant(
            deficiency["correction_due_at"],
            "2026-09-02T09:00:00.000Z",
            "correction_due_at",
        )
        assert_fields(work_order, priority_tier="ROUTINE")
        assert_instant(work_order["due_at"], "2026-09-02T09:00:00.000Z", "due_at")
        assert_property_state(
            X.read_property(api, bundle["property_id"]), "READY", 0, 0, 0
        )

    def test_the_finding_response_carries_every_derived_consequence(self, api):
        """One life-threatening finding restricts the property in the same call.

        PRD: "Finally the owning property recomputes
        `open_life_threatening_count` and `open_severe_count` and re-derives
        `readiness_posture` - an owner's own finding of a life-threatening defect
        restricts their property exactly as an inspector's would, which in turn
        may raise this very sweep's open work orders to `URGENT`."

        Design: Corner/consistency_model/sweep_finding_response_already_carries_every_derived_consequence
        """
        bundle = X.adopted_standard(api, ("LT_GAS",))
        bundle.update(
            X.property_with_units(
                api,
                K.CEDAR_WALK,
                [
                    {
                        "unit_number": "101",
                        "bedroom_count": 1,
                        "occupancy_status": "OCCUPIED",
                    }
                ],
            )
        )
        unit_id = bundle["unit_ids"]["101"]
        sweep = X.in_progress_sweep(api, bundle["property_id"])

        response = api.record_finding(
            sweep["sweep_id"],
            F.finding_payload(
                sweep["sweep_version"],
                bundle["definition_ids"]["LT_GAS"],
                unit_id,
                observed_at=K.SWEEP_OBSERVED_AT_1,
            ),
            bundle["owner_headers"],
        )

        work_order = assert_created(response)
        assert work_order["deficiency_id"] is not None
        assert_fields(work_order, priority_tier="URGENT")

        deficiency = X.read_deficiency(api, work_order["deficiency_id"])
        assert_two_decimals(
            deficiency["points_deducted"], 36.00, "points_deducted"
        )
        assert_fields(deficiency, status="OPEN")
        assert_instant(
            deficiency["correction_due_at"],
            "2026-08-04T09:00:00.000Z",
            "correction_due_at",
        )

        reread = X.read_sweep(api, sweep["sweep_id"])
        # Two increments, both pinned by the PRD: the finding narrative recomputes
        # this sweep's own work-order counters and increments its version by 1, and
        # then the RESTRICTED posture escalates this very sweep's new work order, so
        # per PRD 2.9 "every sweep that owns a work order touched by either direction
        # recomputes its urgent_work_order_count and has its own version incremented".
        assert_integer(
            reread["version"], sweep["sweep_version"] + 2, "version"
        )
        assert_sweep_counters(reread, 1, 0, 0, 1, 0.00)
        assert_property_state(
            X.read_property(api, bundle["property_id"]), "RESTRICTED", 1, 0, 0
        )
        assert_integer(
            X.read_unit(api, unit_id)["open_deficiency_count"],
            1,
            "open_deficiency_count",
        )

    def test_an_area_outside_the_planned_scope_is_rejected(self, api):
        """A UNIT_ONLY sweep admits no INSIDE finding.

        PRD: "Scope admission is exact: a `UNIT_ONLY` sweep admits `UNIT` alone,
        an `INSIDE_OUTSIDE` sweep admits `INSIDE` and `OUTSIDE`, and an
        `ALL_AREAS` sweep admits all three. An area outside scope is rejected
        with `ERR_AREA_OUT_OF_SCOPE` (HTTP 422)."

        Design: Corner/validations/finding_outside_the_planned_area_scope_returns_area_out_of_scope
        """
        bundle = X.adopted_standard(api, ("LT_GAS", "MOD_HANDRAIL"))
        bundle.update(
            X.property_with_units(
                api, K.CEDAR_WALK, [{"unit_number": "101", "bedroom_count": 1}]
            )
        )
        sweep = X.in_progress_sweep(
            api, bundle["property_id"], planned_area_scope="UNIT_ONLY"
        )

        response = api.record_finding(
            sweep["sweep_id"],
            F.finding_payload(
                sweep["sweep_version"],
                bundle["definition_ids"]["MOD_HANDRAIL"],
                inspectable_area="INSIDE",
                observed_at=K.SWEEP_OBSERVED_AT_1,
            ),
            bundle["owner_headers"],
        )

        assert_error(response, ApiErrorId.AREA_OUT_OF_SCOPE)
        reread = X.read_sweep(api, sweep["sweep_id"])
        assert_integer(reread["version"], sweep["sweep_version"], "version")
        assert_integer(
            reread["generated_work_order_count"],
            0,
            "generated_work_order_count",
        )
        assert_total_count(
            api.list_deficiencies(ADMIN, sweep_id=sweep["sweep_id"]), 0
        )

    def test_a_unit_area_finding_without_a_unit_id_is_rejected(self, api):
        """A UNIT finding must name the dwelling unit it was observed in.

        PRD: "Independently of scope, the submitted `inspectable_area` must equal
        the `inspectable_area` on the cited definition, and `unit_id` must be
        present exactly when the area is `UNIT` and absent otherwise; a
        disagreement is rejected with `ERR_AREA_MISMATCH` (HTTP 422)."

        Design: Corner/validations/unit_area_finding_without_unit_id_returns_area_mismatch
        """
        bundle = X.adopted_standard(api, ("LT_GAS", "SEV_WINDOW"))
        bundle.update(
            X.property_with_units(
                api, K.CEDAR_WALK, [{"unit_number": "101", "bedroom_count": 1}]
            )
        )
        sweep = X.in_progress_sweep(api, bundle["property_id"])

        response = api.record_finding(
            sweep["sweep_id"],
            F.finding_payload(
                sweep["sweep_version"],
                bundle["definition_ids"]["SEV_WINDOW"],
                inspectable_area="UNIT",
                observed_at=K.SWEEP_OBSERVED_AT_1,
            ),
            bundle["owner_headers"],
        )

        assert_error(response, ApiErrorId.AREA_MISMATCH)
        assert_integer(
            X.read_sweep(api, sweep["sweep_id"])["generated_work_order_count"],
            0,
            "generated_work_order_count",
        )
        assert_integer(
            X.read_unit(api, bundle["unit_ids"]["101"])["open_deficiency_count"],
            0,
            "open_deficiency_count",
        )

    def test_an_unknown_defect_definition_is_a_body_identifier_not_found(self, api):
        """The findings endpoint resolves its own body foreign key.

        PRD: "foreign-key identifiers carried in the body are resolved in the
        order the endpoint declares its inputs, each producing the 404 for its
        own resource type: `ERR_STANDARD_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`,
        `ERR_UNIT_NOT_FOUND`, `ERR_DEFECT_DEFINITION_NOT_FOUND`".

        Design: Corner/entities/record_finding_with_unknown_defect_definition_returns_not_found
        """
        bundle = X.property_with_units(
            api,
            K.MAPLE_COURT,
            [
                {
                    "unit_number": "101",
                    "bedroom_count": 2,
                    "occupancy_status": "OCCUPIED",
                }
            ],
        )
        sweep = X.in_progress_sweep(api, bundle["property_id"])

        response = api.record_finding(
            sweep["sweep_id"],
            F.finding_payload(
                sweep["sweep_version"],
                "00000000-0000-4000-8000-000000000000",
                bundle["unit_ids"]["101"],
                observed_at=K.SWEEP_OBSERVED_AT_1,
            ),
            bundle["owner_headers"],
        )

        assert_error(response, ApiErrorId.DEFECT_DEFINITION_NOT_FOUND)
        reread = X.read_sweep(api, sweep["sweep_id"])
        assert_integer(reread["version"], sweep["sweep_version"], "version")
        assert_integer(
            reread["generated_work_order_count"],
            0,
            "generated_work_order_count",
        )
        assert_total_count(
            api.list_work_orders(ADMIN, sweep_id=sweep["sweep_id"]), 0
        )

    def test_a_finding_on_a_closed_sweep_is_rejected(self, api):
        """A sweep closed with no findings admits no late finding.

        PRD: "Any sweep transition requested from a status that does not admit it
        is rejected with `ERR_SWEEP_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/record_finding_on_a_closed_sweep_returns_invalid_state
        """
        bundle = X.adopted_standard(api, ("LT_GAS",))
        bundle.update(
            X.property_with_units(
                api,
                K.CEDAR_WALK,
                [
                    {
                        "unit_number": "101",
                        "bedroom_count": 1,
                        "occupancy_status": "OCCUPIED",
                    }
                ],
            )
        )
        sweep = X.in_progress_sweep(api, bundle["property_id"])
        closed = assert_ok(
            api.close_sweep(
                sweep["sweep_id"],
                F.sweep_close_payload(closed_at=SWEEP_CLOSED_AT),
                bundle["owner_headers"],
            )
        )
        assert_fields(closed, status="CLOSED")

        response = api.record_finding(
            sweep["sweep_id"],
            F.finding_payload(
                closed["version"],
                bundle["definition_ids"]["LT_GAS"],
                bundle["unit_ids"]["101"],
                observed_at="2026-08-07T09:00:00.000Z",
            ),
            bundle["owner_headers"],
        )

        assert_error(response, ApiErrorId.SWEEP_INVALID_STATE)
        reread = X.read_sweep(api, sweep["sweep_id"])
        assert_integer(
            reread["generated_work_order_count"],
            0,
            "generated_work_order_count",
        )
        assert_two_decimals(
            reread["closure_verified_rate"], 100.00, "closure_verified_rate"
        )
        assert_total_count(
            api.list_deficiencies(ADMIN, sweep_id=sweep["sweep_id"]), 0
        )

    def test_a_second_finding_replaying_the_pre_cascade_version_is_stale(self, api):
        """The first finding advanced the sweep, so its token no longer holds.

        PRD: "Filing a finding against a self-assessment sweep requires
        `expected_sweep_version` to equal the target `SelfAssessmentSweep`'s
        current `version`. A mismatch is rejected with
        `ERR_STALE_SWEEP_VERSION` (HTTP 412), so a client cannot add another work
        order to a sweep whose work-order counters it has not observed."

        Design: Corner/cross_cutting_complexity_layers/second_sweep_finding_with_the_pre_cascade_sweep_version_is_rejected_as_stale
        """
        bundle = X.adopted_standard(api, ("LT_GAS", "SEV_WINDOW"))
        bundle.update(
            X.property_with_units(
                api,
                K.CEDAR_WALK,
                [
                    {
                        "unit_number": "101",
                        "bedroom_count": 1,
                        "occupancy_status": "OCCUPIED",
                    }
                ],
            )
        )
        unit_id = bundle["unit_ids"]["101"]
        definition_id = bundle["definition_ids"]["SEV_WINDOW"]
        sweep = X.in_progress_sweep(api, bundle["property_id"])
        first_version = sweep["sweep_version"]
        X.record_finding(
            api,
            bundle["property_id"],
            sweep["sweep_id"],
            first_version,
            definition_id,
            unit_id,
            observed_at=K.SWEEP_OBSERVED_AT_1,
        )
        second_version = X.read_sweep(api, sweep["sweep_id"])["version"]
        assert_integer(second_version, first_version + 1, "version")

        response = api.record_finding(
            sweep["sweep_id"],
            F.finding_payload(
                first_version,
                definition_id,
                unit_id,
                observed_at=K.SWEEP_OBSERVED_AT_2,
            ),
            bundle["owner_headers"],
        )

        assert_error(response, ApiErrorId.STALE_SWEEP_VERSION)
        reread = X.read_sweep(api, sweep["sweep_id"])
        assert_integer(
            reread["generated_work_order_count"],
            1,
            "generated_work_order_count",
        )
        assert_integer(reread["version"], second_version, "version")
        assert_total_count(
            api.list_work_orders(ADMIN, sweep_id=sweep["sweep_id"]), 1
        )

        replay = api.record_finding(
            sweep["sweep_id"],
            F.finding_payload(
                second_version,
                definition_id,
                unit_id,
                observed_at=K.SWEEP_OBSERVED_AT_2,
            ),
            bundle["owner_headers"],
        )

        assert_created(replay)
        assert_integer(
            X.read_sweep(api, sweep["sweep_id"])["generated_work_order_count"],
            2,
            "generated_work_order_count",
        )

    def test_the_property_listing_reflects_the_derived_counters(self, api):
        """A posture-filtered listing carries the same derived block as the read.

        PRD: "Otherwise, if `open_life_threatening_count` is at least 1, the
        posture is `RESTRICTED`."

        Design: Corner/endpoints/property_list_read_reflects_derived_counters_after_a_sweep_finding
        """
        bundle = X.sweep_lifecycle(
            api,
            "LT_GAS",
            K.CEDAR_WALK,
            [
                {
                    "unit_number": "101",
                    "bedroom_count": 1,
                    "occupancy_status": "OCCUPIED",
                }
            ],
            ("LT_GAS",),
        )
        property_id = bundle["property_id"]

        rows = assert_pagination_meta(
            api.list_properties(
                X.INSPECTOR,
                readiness_posture="RESTRICTED",
                limit=10,
                offset=0,
            ),
            1,
            10,
            0,
            False,
        )

        listed = rows[0]
        assert_fields(listed, id=property_id)
        assert_property_state(listed, "RESTRICTED", 1, 0, 0)
        assert_null(listed, "last_final_score")

        deficiency = X.read_deficiency(api, bundle["deficiency_id"])
        assert_two_decimals(
            deficiency["points_deducted"], 36.00, "points_deducted"
        )
        assert_instant(
            deficiency["correction_due_at"],
            "2026-08-04T09:00:00.000Z",
            "correction_due_at",
        )
        assert_fields(
            X.read_work_order(api, bundle["work_order_id"]),
            priority_tier="URGENT",
        )

        single = X.read_property(api, property_id)
        assert_property_state(single, "RESTRICTED", 1, 0, 0)
