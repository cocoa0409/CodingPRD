"""
The two reservation version guards, and the one counter that never resets.

Both guards compare version equality rather than usability, so a snapshot that
has gone stale for a reason that changed nothing material is still refused; and a
carbon project's revision budget is cumulative across resubmissions.
"""

from test_helpers import fixtures as fx
from test_helpers import factories as f
from test_helpers import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_3dp,
    assert_instant_equals,
    ids_of,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    LOGISTICS_COORDINATOR,
    PLANT_MANAGER,
    PROCESS_OPERATOR,
)


def _tank_farm_whose_destination_was_held_and_released(api):
    """
    T-301 is commissioned, held OFF_SPEC and released again.  Not one gallon
    moved, yet the tank is two mutations older than the snapshot a caller took at
    commissioning.
    """
    fx.commission_plant(api)
    fx.advance_clock(api, "2026-09-04T06:00:00Z")
    neat = fx.commission_tank(
        api, "T-101", "ETHANOL_200_PROOF", 1000000.00, opening_gallons=500000.00
    )
    denaturant = fx.commission_tank(
        api, "T-201", "DENATURANT", 1000000.00, opening_gallons=500000.00
    )
    destination = fx.commission_tank(api, "T-301", "DENATURED_E100", 1000000.00)
    held = fx.hold_tank(api, destination["id"], "OFF_SPEC")
    released = fx.release_tank(api, destination["id"])
    return {
        "neat": neat,
        "denaturant": denaturant,
        "destination": destination,
        "held": held,
        "released": released,
    }


class TestTheDestinationTankVersionGuardIsExactEquality:
    """Two mutations that moved nothing still invalidate the caller's snapshot."""

    def test_the_stale_snapshot_is_refused_at_412_and_writes_no_blend(self, api):
        """A hold and a release bump the tank twice, so the commissioning version is stale.

        PRD 2.7: "If that value does not equal the tank's current `version` —
        because some other writer has since moved liquid, taken the tank off
        service or reserved another window on it — the create is rejected with
        `ERR_STALE_TANK_VERSION` and HTTP 412."
        PRD 2.4: "`version`, an integer that starts at 1 on creation and
        increments by exactly 1 on every mutation of that row"

        Design: Corner/cross_cutting_complexity_layers/stale_destination_tank_version_rejected_then_fresh_version_accepted
        """
        scenario = _tank_farm_whose_destination_was_held_and_released(api)

        assert scenario["destination"]["version"] == 1, scenario["destination"]["version"]
        assert scenario["held"]["version"] == 2, scenario["held"]["version"]
        assert scenario["held"]["service_status"] == "ON_HOLD", scenario["held"]["service_status"]
        assert scenario["released"]["version"] == 3, scenario["released"]["version"]
        assert scenario["released"]["service_status"] == "IN_SERVICE", (
            scenario["released"]["service_status"]
        )

        validate_error(
            api.create_blend(
                f.blend_payload(
                    scenario["neat"]["id"],
                    scenario["denaturant"]["id"],
                    scenario["destination"]["id"],
                    1,
                ),
                PROCESS_OPERATOR,
            ),
            ApiErrorId.STALE_TANK_VERSION,
            412,
        )

        rows, meta = validate_paginated(
            api.list_tank_blends(scenario["destination"]["id"], PROCESS_OPERATOR)
        )
        assert rows == [], rows
        assert meta["total_count"] == 0, meta["total_count"]

    def test_the_identical_body_is_accepted_once_it_carries_the_current_version(self, api):
        """Only the guard value changes, and the schedule then reserves the window.

        PRD 3.5: "The blend's `occupancy_end` is computed as `window_end` plus the
        destination tank's `settling_buffer_minutes`, and the reserved interval
        runs from `window_start` through `occupancy_end` as a **closed** interval
        on both ends."
        PRD 3.5: "A successful schedule lands the blend at `SCHEDULED` and
        increments the destination tank's `version`."

        Design: Corner/cross_cutting_complexity_layers/stale_destination_tank_version_rejected_then_fresh_version_accepted
        """
        scenario = _tank_farm_whose_destination_was_held_and_released(api)

        blend = validate_success(
            api.create_blend(
                f.blend_payload(
                    scenario["neat"]["id"],
                    scenario["denaturant"]["id"],
                    scenario["destination"]["id"],
                    scenario["released"]["version"],
                ),
                PROCESS_OPERATOR,
            ),
            201,
        )

        assert blend["status"] == "SCHEDULED", blend["status"]
        assert_instant_equals(
            blend["occupancy_end"], "2026-09-04T12:00:00Z", "occupancy_end"
        )
        assert_2dp(blend["neat_gallons"], 2565.00, "neat_gallons")
        assert_2dp(blend["denaturant_gallons"], 60.00, "denaturant_gallons")

        destination = get_success_data(
            api.get_tank(scenario["destination"]["id"], PROCESS_OPERATOR)
        )
        assert destination["version"] == 4, destination["version"]
        assert_2dp(destination["current_gallons"], 0.00, "current_gallons")


def _track_carrying_one_accepted_train(api):
    """
    TRK-A opens with 110 spots and SH-1 commits ten of them, which moves the
    track to version 2 while a hundred spots remain free.
    """
    fx.commission_plant(api)
    fx.advance_clock(api, "2026-09-04T06:00:00Z")
    tank = fx.commission_tank(
        api, "T-301", "DENATURED_E100", 1000000.00, opening_gallons=400000.00
    )
    track = fx.commission_track(api)
    first = fx.schedule_shipment(
        api,
        track["id"],
        tank["id"],
        track["version"],
        shipment_code="SH-1",
        railcar_count=10,
        gallons_per_railcar=2659.00,
        window_start="2026-09-04T06:00:00Z",
        window_end="2026-09-04T12:00:00Z",
        price_cents_per_gallon=181.50,
    )
    refreshed = get_success_data(api.get_track(track["id"], LOGISTICS_COORDINATOR))
    return {"tank": tank, "track": track, "first": first, "refreshed": refreshed}


def _second_train_payload(scenario, expected_track_version):
    """SH-2, ten railcars in the afternoon window, differing only in the guard."""
    return f.shipment_payload(
        scenario["track"]["id"],
        scenario["tank"]["id"],
        expected_track_version,
        shipment_code="SH-2",
        destination_terminal="Peoria Terminal",
        railcar_count=10,
        gallons_per_railcar=2659.00,
        window_start="2026-09-04T12:00:00Z",
        window_end="2026-09-04T18:00:00Z",
        price_cents_per_gallon=180.00,
    )


class TestTheLoadingTrackVersionGuardIsExactEquality:
    """Free spots do not excuse a stale view of the shared track."""

    def test_the_stale_guard_is_refused_at_412_even_with_a_hundred_spots_free(self, api):
        """The guard fires before capacity, so the refusal is not a capacity error.

        PRD 2.7: "If it does not equal the track's current `version`, the create
        is rejected with `ERR_STALE_TRACK_VERSION` and HTTP 412, because the
        caller's view of `committed_railcars` no longer reflects the track and a
        shipment legitimately commits a slice of the track's aggregate spot
        capacity."
        PRD 3.6: "Its railcars are added to the track's `committed_railcars` and
        the track's `version` increments."

        Design: Corner/cross_cutting_complexity_layers/stale_loading_track_version_rejected_then_fresh_version_accepted
        """
        scenario = _track_carrying_one_accepted_train(api)

        assert scenario["track"]["version"] == 1, scenario["track"]["version"]
        assert scenario["track"]["committed_railcars"] == 0, scenario["track"]["committed_railcars"]
        assert scenario["refreshed"]["version"] == 2, scenario["refreshed"]["version"]
        assert scenario["refreshed"]["committed_railcars"] == 10, (
            scenario["refreshed"]["committed_railcars"]
        )

        response = api.create_shipment(
            _second_train_payload(scenario, 1), LOGISTICS_COORDINATOR
        )
        validate_error(response, ApiErrorId.STALE_TRACK_VERSION, 412)
        assert response.json()["data"]["error_id"] != ApiErrorId.TRACK_CAPACITY_EXCEEDED, (
            "a hundred of the hundred and ten spots were still free"
        )

        rows, _ = validate_paginated(api.list_shipments(LOGISTICS_COORDINATOR))
        assert ids_of(rows) == [scenario["first"]["id"]], ids_of(rows)
        track = get_success_data(api.get_track(scenario["track"]["id"], LOGISTICS_COORDINATOR))
        assert track["version"] == 2, track["version"]
        assert track["committed_railcars"] == 10, track["committed_railcars"]

    def test_the_retry_at_the_fresh_version_commits_the_second_slice(self, api):
        """Re-read at version 2 the same train is accepted and the commitment doubles.

        PRD 3.6: "A scheduled shipment lands with `planned_gallons` computed as
        `railcar_count` multiplied by `gallons_per_railcar` (two decimals), its
        `loading_status` at `SCHEDULED` and its `billing_status` at
        `PENDING_BOL`."
        PRD 3.6: "that figure being the sum of `railcar_count` over shipments on
        the track whose `loading_status` is `SCHEDULED`, `BLOCKED` or `LOADED`"

        Design: Corner/cross_cutting_complexity_layers/stale_loading_track_version_rejected_then_fresh_version_accepted
        """
        scenario = _track_carrying_one_accepted_train(api)

        second = validate_success(
            api.create_shipment(
                _second_train_payload(scenario, scenario["refreshed"]["version"]),
                LOGISTICS_COORDINATOR,
            ),
            201,
        )

        assert_2dp(second["planned_gallons"], 26590.00, "planned_gallons")
        assert second["loading_status"] == "SCHEDULED", second["loading_status"]
        assert second["billing_status"] == "PENDING_BOL", second["billing_status"]

        track = get_success_data(api.get_track(scenario["track"]["id"], LOGISTICS_COORDINATOR))
        assert track["committed_railcars"] == 20, track["committed_railcars"]
        assert track["version"] == 3, track["version"]


def _project_resubmitted_after_two_returns(api):
    """
    CP-1 has been submitted, returned, resubmitted, returned again and
    resubmitted, so it is `SUBMITTED` with its two revisions already spent.
    """
    plant = fx.commission_plant(api, baseline_ci_g_per_mj=58.0)
    fx.advance_clock(api, "2026-09-04T06:00:00Z")
    project = fx.draft_project(
        api,
        project_code="CP-1",
        project_name="Combined heat and power retrofit",
        project_type="COMBINED_HEAT_POWER",
        claimed_reduction_g_per_mj=8.0,
        certification_tier="FULL",
    )
    states = [project]
    for note in ("Metering plan incomplete.", "Baseline still unsupported."):
        get_success_data(
            api.submit_carbon_project(
                project["id"],
                {"verification_body": "Prairie Verification Services"},
                COMPLIANCE_OFFICER,
            )
        )
        states.append(
            get_success_data(
                api.review_carbon_project(
                    project["id"],
                    {"determination": "RETURN", "review_note": note},
                    PLANT_MANAGER,
                )
            )
        )
    states.append(
        get_success_data(
            api.submit_carbon_project(
                project["id"],
                {"verification_body": "Prairie Verification Services"},
                COMPLIANCE_OFFICER,
            )
        )
    )
    return {"plant": plant, "project": project, "states": states}


class TestTheRevisionBudgetIsCumulativeAcrossResubmissions:
    """Two returns are the whole budget, and resubmitting does not buy another."""

    def test_a_third_return_is_refused_at_the_limit_and_not_as_a_state_error(self, api):
        """The counter survives every resubmission, so the third return has no budget.

        PRD 3.8: "Revisions are capped at two: a return is only permitted while
        `revision_count` is **strictly below** 2, so the first and second returns
        are allowed and a third is refused with `ERR_REVISION_LIMIT_REACHED`."
        PRD 3.8: "A `RETURN` moves the project `SUBMITTED →
        RETURNED_FOR_REVISION`, increments `revision_count`, and records the
        `review_note` and `reviewed_at`."

        Design: Corner/cross_cutting_complexity_layers/third_return_for_revision_is_refused_at_the_cumulative_limit
        """
        scenario = _project_resubmitted_after_two_returns(api)
        drafted, first_return, second_return, resubmitted = scenario["states"]

        assert drafted["revision_count"] == 0, drafted["revision_count"]
        assert first_return["revision_count"] == 1, first_return["revision_count"]
        assert first_return["verification_status"] == "RETURNED_FOR_REVISION", (
            first_return["verification_status"]
        )
        assert second_return["revision_count"] == 2, second_return["revision_count"]
        assert second_return["verification_status"] == "RETURNED_FOR_REVISION", (
            second_return["verification_status"]
        )
        assert resubmitted["verification_status"] == "SUBMITTED", (
            resubmitted["verification_status"]
        )
        assert resubmitted["revision_count"] == 2, resubmitted["revision_count"]

        response = api.review_carbon_project(
            scenario["project"]["id"],
            {"determination": "RETURN", "review_note": "Third attempt at a return."},
            PLANT_MANAGER,
        )
        validate_error(response, ApiErrorId.REVISION_LIMIT_REACHED, 422)
        assert response.json()["data"]["error_id"] != ApiErrorId.INVALID_PROJECT_STATE, (
            "the project was legitimately SUBMITTED, so this is not a state error"
        )

        after = get_success_data(
            api.get_carbon_project(scenario["project"]["id"], COMPLIANCE_OFFICER)
        )
        assert after["verification_status"] == "SUBMITTED", after["verification_status"]
        assert after["revision_count"] == 2, after["revision_count"]

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_3dp(plant["ci_score_g_per_mj"], 58.000, "ci_score_g_per_mj")

    def test_certifying_the_same_submission_is_still_accepted(self, api):
        """Only the return is exhausted; the submission may still be certified.

        PRD 3.8: "The effective verified reduction is the
        `verified_reduction_g_per_mj` from the body when the manager supplied one,
        and otherwise falls back to the project's stored
        `claimed_reduction_g_per_mj`"
        PRD 3.8: "`ci_score_g_per_mj` is the plant's `baseline_ci_g_per_mj` less
        the total credited reduction, rounded half up to three decimals, and then
        floored at zero so the score is never negative."

        Design: Corner/cross_cutting_complexity_layers/third_return_for_revision_is_refused_at_the_cumulative_limit
        """
        scenario = _project_resubmitted_after_two_returns(api)

        certified = validate_success(
            api.review_carbon_project(
                scenario["project"]["id"],
                {"determination": "CERTIFY", "review_note": "Metering plan accepted."},
                PLANT_MANAGER,
            ),
            200,
        )

        assert certified["verification_status"] == "CERTIFIED", certified["verification_status"]
        assert_1dp(certified["verified_reduction_g_per_mj"], 8.0, "verified_reduction_g_per_mj")
        assert_3dp(certified["credited_reduction_g_per_mj"], 8.000, "credited_reduction_g_per_mj")
        assert certified["revision_count"] == 2, certified["revision_count"]

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_3dp(plant["ci_score_g_per_mj"], 50.000, "ci_score_g_per_mj")
