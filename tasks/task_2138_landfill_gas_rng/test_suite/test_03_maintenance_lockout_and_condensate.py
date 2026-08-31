"""Collection-system maintenance: buffered lockout occupancy, the job lifecycle,
and regulated condensate hauling."""

from test_helpers import (
    ApiErrorId,
    approx_2dp,
    assert_condensate_haul,
    assert_instant_equals,
    create_work_order_payload,
    fixtures,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import BASE_CLOCK_UTC


def _site_and_well():
    set_clock(BASE_CLOCK_UTC)
    site = fixtures.create_site()
    well = fixtures.create_well(site["id"], well_code="W-01")
    return site, well


def _plan(api, headers, well_id, **overrides):
    return api.create_work_order(
        create_work_order_payload(well_id, **overrides), headers
    )


class TestBufferedLockoutOccupancy:
    def test_buffered_lockout_windows_that_merely_touch_collide(
        self, api, technician_headers
    ):
        """PRD §3.3: "Each job — the one being planned and every incumbent — is treated
        as occupying a closed interval that runs from its `window_start` less the purge
        buffer through its `window_end` plus the same buffer, where the buffer is the
        job's `lockout_buffer_minutes`, fixed by the system at 120 minutes."
        PRD §3.3: "If the new job's buffered closed interval shares even a single instant
        with an incumbent's buffered closed interval, the request is refused with
        `ERR_WELL_LOCKOUT_CONFLICT`."
        PRD §3.3: "Two jobs whose buffered windows merely touch at one endpoint therefore
        do conflict — the opposite of how nomination windows behave — because the buffer
        exists so the well can be purged and allowed to settle, and a purge that begins
        the instant the previous one ends is not a purge."

        Design: Difficulty/resource_temporal_overlap/work_order_buffered_closed_window_collision_on_well
        """
        site, well = _site_and_well()
        validate_success(
            _plan(
                api,
                technician_headers,
                well["id"],
                work_type="WELL_RETUNE",
                window_start="2026-08-12T08:00:00Z",
                window_end="2026-08-12T12:00:00Z",
            ),
            201,
        )

        # Incumbent occupies [06:00, 14:00]; the new job would occupy [14:00, 20:00].
        validate_error(
            _plan(
                api,
                technician_headers,
                well["id"],
                work_type="SUMP_PUMP_SERVICE",
                window_start="2026-08-12T16:00:00Z",
                window_end="2026-08-12T18:00:00Z",
            ),
            ApiErrorId.ERR_WELL_LOCKOUT_CONFLICT.value,
        )

        _, meta = validate_paginated(
            api.list_work_orders(
                technician_headers,
                params={"well_id": well["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1, "the colliding plan must not be persisted"

    def test_one_minute_past_the_buffered_endpoint_clears_the_lockout_conflict(
        self, api, technician_headers
    ):
        """PRD §3.3: "Each job — the one being planned and every incumbent — is treated
        as occupying a closed interval that runs from its `window_start` less the purge
        buffer through its `window_end` plus the same buffer, where the buffer is the
        job's `lockout_buffer_minutes`, fixed by the system at 120 minutes."
        PRD §3.3: "If the new job's buffered closed interval shares even a single instant
        with an incumbent's buffered closed interval, the request is refused with
        `ERR_WELL_LOCKOUT_CONFLICT`."
        PRD §3.3: "The job is created in `PLANNED` with `actual_start_at` and
        `actual_end_at` both null and `condensate_gallons_removed` at 0."

        Design: Difficulty/resource_temporal_overlap/work_order_buffered_closed_window_collision_on_well
        """
        site, well = _site_and_well()
        _plan(
            api,
            technician_headers,
            well["id"],
            work_type="WELL_RETUNE",
            window_start="2026-08-12T08:00:00Z",
            window_end="2026-08-12T12:00:00Z",
        )

        second = validate_success(
            _plan(
                api,
                technician_headers,
                well["id"],
                work_type="SUMP_PUMP_SERVICE",
                window_start="2026-08-12T16:01:00Z",
                window_end="2026-08-12T18:00:00Z",
            ),
            201,
        )
        assert second["status"] == "PLANNED"
        assert second["lockout_buffer_minutes"] == 120
        assert second["actual_start_at"] is None
        assert second["actual_end_at"] is None
        assert second["condensate_gallons_removed"] == approx_2dp(0.0)

        _, meta = validate_paginated(
            api.list_work_orders(
                technician_headers,
                params={"well_id": well["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 2


class TestRejectionOrderOnWorkOrderPlanning:
    def test_decommissioned_well_is_reported_ahead_of_the_lockout_conflict(
        self, api, admin_headers, technician_headers
    ):
        """PRD §2.5: "Checks run in a fixed ascending priority order and the **first**
        failing check decides the response."
        PRD §2.5: "**State legality (priority 80).** The target resource sits in a state
        from which the requested transition is declared, or `ERR_INVALID_TRANSITION` with
        HTTP 409. Several state failures have their own specific code at this same rung:
        `ERR_WELL_DECOMMISSIONED` when an operation targets a well whose
        `operating_state` is `DECOMMISSIONED` — which also blocks planning a work order
        against that well"
        PRD §2.5: "**Window and occupancy rules (priority 110).** A buffered lockout
        collision on a well reports `ERR_WELL_LOCKOUT_CONFLICT` (409); starting a work
        order outside its window reports `ERR_WORK_ORDER_WINDOW_NOT_ACTIVE` (422); a
        nomination window escaping the contract term reports `ERR_CONTRACT_TERM_WINDOW`
        (422); and a royalty period that has not fully elapsed reports
        `ERR_ROYALTY_PERIOD_NOT_CLOSED` (422)."

        Design: Difficulty/priority_pair_validation_conflict/decommissioned_well_state_beats_lockout_window_conflict
        """
        site, well = _site_and_well()
        _plan(
            api,
            technician_headers,
            well["id"],
            work_type="WELL_RETUNE",
            window_start="2026-08-12T08:00:00Z",
            window_end="2026-08-12T12:00:00Z",
        )
        validate_success(
            api.set_well_status(
                well["id"],
                {
                    "to_state": "DECOMMISSIONED",
                    "reason": "Well abandoned under the closure plan",
                },
                admin_headers,
            )
        )

        # The requested window's buffered interval [11:00, 17:00] also collides with the
        # incumbent's [06:00, 14:00]; the priority-80 state error still wins.
        error = validate_error(
            _plan(
                api,
                technician_headers,
                well["id"],
                work_type="LATERAL_REPAIR",
                window_start="2026-08-12T13:00:00Z",
                window_end="2026-08-12T15:00:00Z",
            ),
            ApiErrorId.ERR_WELL_DECOMMISSIONED.value,
        )
        assert error["error_id"] != ApiErrorId.ERR_WELL_LOCKOUT_CONFLICT.value

    def test_plan_refused_on_a_decommissioned_well_leaves_the_incumbent_in_place(
        self, api, admin_headers, technician_headers
    ):
        """PRD §3.1: "`DECOMMISSIONED` is terminal: no further transition is accepted
        from it, and any operation aimed at such a well, including planning maintenance
        on it, is refused with `ERR_WELL_DECOMMISSIONED`."
        PRD §3.1: "Work orders already planned against a well at the moment it is
        decommissioned are deliberately left in place; they can never start, and they
        keep occupying their buffered lockout window until they are cancelled."

        Design: Difficulty/priority_pair_validation_conflict/decommissioned_well_state_beats_lockout_window_conflict
        """
        site, well = _site_and_well()
        incumbent = validate_success(
            _plan(
                api,
                technician_headers,
                well["id"],
                work_type="WELL_RETUNE",
                window_start="2026-08-12T08:00:00Z",
                window_end="2026-08-12T12:00:00Z",
            ),
            201,
        )
        api.set_well_status(
            well["id"],
            {"to_state": "DECOMMISSIONED", "reason": "Well abandoned under the closure plan"},
            admin_headers,
        )

        validate_error(
            _plan(
                api,
                technician_headers,
                well["id"],
                work_type="LATERAL_REPAIR",
                window_start="2026-08-12T13:00:00Z",
                window_end="2026-08-12T15:00:00Z",
            ),
            ApiErrorId.ERR_WELL_DECOMMISSIONED.value,
        )

        rows, meta = validate_paginated(
            api.list_work_orders(
                technician_headers,
                params={"well_id": well["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == incumbent["id"]
        assert fixtures.get_success_data(
            api.get_work_order(incumbent["id"], technician_headers)
        )["status"] == "PLANNED"


class TestWorkOrderLifecycle:
    def test_starting_a_job_before_its_window_opens_is_refused(
        self, api, technician_headers
    ):
        """PRD §3.3: "Starting a job moves it `PLANNED → IN_PROGRESS`, and the logical
        clock must be inside the planned window, from `window_start` through `window_end`
        inclusive; starting early or late is refused with
        `ERR_WORK_ORDER_WINDOW_NOT_ACTIVE`."

        Design: Corner/validations/work_order_start_outside_its_window_is_rejected
        """
        site, well = _site_and_well()
        fixtures.post_good_reading(well["id"], "2026-08-09T01:00:00Z", flow_scfm=480.0)
        work_order = validate_success(
            _plan(
                api,
                technician_headers,
                well["id"],
                work_type="WELL_RETUNE",
                window_start="2026-08-12T08:00:00Z",
                window_end="2026-08-12T12:00:00Z",
            ),
            201,
        )

        validate_error(
            api.set_work_order_status(
                work_order["id"], {"to_status": "IN_PROGRESS"}, technician_headers
            ),
            ApiErrorId.ERR_WORK_ORDER_WINDOW_NOT_ACTIVE.value,
        )

        unchanged = fixtures.get_success_data(
            api.get_work_order(work_order["id"], technician_headers)
        )
        assert unchanged["status"] == "PLANNED"
        assert unchanged["actual_start_at"] is None

        well_after = fixtures.read_well(well["id"])
        assert well_after["operating_state"] == "ONLINE", "the well is never locked out"
        assert well_after["current_flow_scfm"] == approx_2dp(480.0)

    def test_completing_a_job_drops_the_well_back_to_isolated(
        self, api, technician_headers
    ):
        """PRD §3.3: "Completing a job moves it `IN_PROGRESS → COMPLETED`, stamps
        `actual_end_at` from `current_utc`, and recomputes `condensate_gallons_removed`
        as the sum of `gallons` over every condensate haul recorded against the job. The
        well is released from lockout, and the release is deliberately cautious: it drops
        back to `ISOLATED`, never straight to `ONLINE`. Its `lockout_work_order_id` is
        cleared to null, its `consecutive_good_readings` is reset to 0, and its
        `current_flow_scfm` stays 0 until fresh good readings and an explicit return to
        service bring it back, exactly as described in §3.2."

        Design: Corner/state_machines/work_order_completion_drops_well_back_to_isolated
        """
        site, well = _site_and_well()
        fixtures.post_good_reading(well["id"], "2026-08-09T01:00:00Z", flow_scfm=480.0)
        work_order = fixtures.setup_work_order_in_progress(
            well["id"], work_type="WELL_RETUNE"
        )

        completed = validate_success(
            api.set_work_order_status(
                work_order["id"], {"to_status": "COMPLETED"}, technician_headers
            )
        )
        assert completed["status"] == "COMPLETED"

        released = fixtures.read_well(well["id"])
        assert released["operating_state"] == "ISOLATED"
        assert released["lockout_work_order_id"] is None
        assert released["consecutive_good_readings"] == 0
        assert released["current_flow_scfm"] == approx_2dp(0.0)
        assert released["last_reading_flow_scfm"] == approx_2dp(480.0)

        assert fixtures.read_site(site["id"])["collected_flow_scfm"] == approx_2dp(0.0)

    def test_cancelling_a_completed_job_is_refused(self, api, technician_headers):
        """PRD §3.3: "A job may also be abandoned before it starts, moving
        `PLANNED → CANCELLED`, which releases the buffered lockout window so a later job
        may occupy it. A job that is already `IN_PROGRESS` cannot be cancelled — it must
        be completed — and any other status pair is refused with
        `ERR_INVALID_TRANSITION`."

        Design: Corner/state_machines/cancel_completed_work_order_returns_invalid_transition
        """
        site, well = _site_and_well()
        work_order = fixtures.setup_work_order_in_progress(
            well["id"], work_type="HEADER_DEWATERING"
        )
        validate_success(
            api.set_work_order_status(
                work_order["id"], {"to_status": "COMPLETED"}, technician_headers
            )
        )

        validate_error(
            api.set_work_order_status(
                work_order["id"], {"to_status": "CANCELLED"}, technician_headers
            ),
            ApiErrorId.ERR_INVALID_TRANSITION.value,
        )

        unchanged = fixtures.get_success_data(
            api.get_work_order(work_order["id"], technician_headers)
        )
        assert unchanged["status"] == "COMPLETED"
        assert_instant_equals(
            unchanged["actual_end_at"], BASE_CLOCK_UTC, "actual_end_at"
        )


class TestCondensateHauling:
    def test_condensate_haul_is_an_append_only_record(self, api, technician_headers):
        """PRD §2.4: "Two resources are append-only event records and deliberately do
        not carry them: a `WellTuningReading` and a `CondensateHaul` each expose only
        `id` and `created_at` — neither `updated_at` nor `version` is present on those
        two, because neither is ever modified after it is written."
        PRD §3.3: "Recording a haul immediately refreshes the job's
        `condensate_gallons_removed`."

        Design: Corner/entities/condensate_haul_is_an_immutable_event_without_version
        """
        site, well = _site_and_well()
        work_order = fixtures.setup_work_order_in_progress(
            well["id"], work_type="SUMP_PUMP_SERVICE"
        )

        haul = validate_success(
            api.create_condensate_haul(
                work_order["id"],
                {
                    "gallons": 250.5,
                    "disposal_manifest_no": "MAN-4471",
                    "hauled_at": "2026-08-10T03:00:00Z",
                    "is_hazardous": False,
                },
                technician_headers,
            ),
            201,
        )
        assert_condensate_haul(haul)
        assert haul["gallons"] == approx_2dp(250.5)
        assert haul["is_hazardous"] is False

        _, meta = validate_paginated(
            api.list_condensate_hauls(
                work_order["id"], technician_headers, params={"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 1

        refreshed = fixtures.get_success_data(
            api.get_work_order(work_order["id"], technician_headers)
        )
        assert refreshed["condensate_gallons_removed"] == approx_2dp(250.5)

    def test_hazardous_haul_needs_a_hazardous_waste_manifest_number(
        self, api, technician_headers
    ):
        """PRD §3.3: "The optional `is_hazardous` flag defaults to false; when it is
        true the manifest number must begin with the prefix `HW-`, and a hazardous haul
        carrying a manifest that does not is refused with
        `ERR_CONDENSATE_MANIFEST_REQUIRED`."

        Design: Corner/validations/hazardous_condensate_without_hw_manifest_is_rejected
        """
        site, well = _site_and_well()
        work_order = fixtures.setup_work_order_in_progress(
            well["id"], work_type="SUMP_PUMP_SERVICE"
        )

        validate_error(
            api.create_condensate_haul(
                work_order["id"],
                {
                    "gallons": 120.0,
                    "disposal_manifest_no": "MAN-4471",
                    "hauled_at": "2026-08-10T02:00:00Z",
                    "is_hazardous": True,
                },
                technician_headers,
            ),
            ApiErrorId.ERR_CONDENSATE_MANIFEST_REQUIRED.value,
        )

        accepted = validate_success(
            api.create_condensate_haul(
                work_order["id"],
                {
                    "gallons": 120.0,
                    "disposal_manifest_no": "HW-4471",
                    "hauled_at": "2026-08-10T02:00:00Z",
                    "is_hazardous": True,
                },
                technician_headers,
            ),
            201,
        )
        assert accepted["disposal_manifest_no"] == "HW-4471"

        refreshed = fixtures.get_success_data(
            api.get_work_order(work_order["id"], technician_headers)
        )
        assert refreshed["condensate_gallons_removed"] == approx_2dp(120.0)

        _, meta = validate_paginated(
            api.list_condensate_hauls(
                work_order["id"], technician_headers, params={"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 1, "the refused haul left no row behind"
