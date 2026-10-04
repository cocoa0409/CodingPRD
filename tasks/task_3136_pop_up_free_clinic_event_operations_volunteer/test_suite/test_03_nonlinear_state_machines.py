"""Non-linear state machines: the volunteer AUTHORIZED -> SUSPENDED ->
VERIFIED -> AUTHORIZED cycle, and the station OPERATIONAL -> DEGRADED ->
OPERATIONAL loop driven by the sterilization backlog."""

from test_helpers import (
    TEST_USERS,
    authorize_volunteer,
    create_authorized_volunteer,
    create_assignment_payload,
    create_event_site_locked,
    get_success_data,
    run_completed_cycle,
    setup_event_with_operational_sterile_station,
    suspend_payload,
    validate_paginated,
    validate_success,
)

ED = TEST_USERS["event_director_headers"]
SL = TEST_USERS["station_lead_headers"]
ST = TEST_USERS["sterilization_tech_headers"]
VC = TEST_USERS["volunteer_coordinator_headers"]


class TestVolunteerSuspendReinstateCycle:
    def test_suspend_reinstate_returns_to_verified_not_authorized(self, api):
        """PRD §3.3: "A `SUSPENDED` volunteer can be reinstated — returning
        them to `VERIFIED`, not directly to `AUTHORIZED` — provided the license
        verification that originally authorized them remains `APPROVED`."

        Design: Difficulty/non_linear_state_machine/volunteer_suspend_reinstate_cycle
        """
        event = create_event_site_locked()
        volunteer = create_authorized_volunteer(event["id"])

        get_success_data(
            api.suspend_volunteer(
                volunteer["id"], suspend_payload(event["id"]), VC
            )
        )
        suspended = validate_success(api.get_volunteer(volunteer["id"], VC))
        assert suspended["status"] == "SUSPENDED"

        get_success_data(
            api.reinstate_volunteer(
                volunteer["id"], {"clinic_event_id": event["id"]}, VC
            )
        )
        reinstated = validate_success(api.get_volunteer(volunteer["id"], VC))
        assert reinstated["status"] == "VERIFIED"

    def test_full_cycle_reauthorization_and_assignment_not_restored(self, api):
        """PRD §3.3: "Suspension cascades: every `ROSTERED` or `CONFIRMED`
        `DisciplineAssignment` for that volunteer transitions to `RELEASED`" —
        and reinstatement does not restore the released assignment, so the
        volunteer must be re-authorized explicitly to complete the cycle.

        Design: Difficulty/non_linear_state_machine/volunteer_suspend_reinstate_cycle
        """
        event = create_event_site_locked()
        volunteer = create_authorized_volunteer(event["id"])
        assignments, _ = validate_paginated(
            api.list_event_assignments(event["id"], VC)
        )
        assignment_id = assignments[0]["id"]
        assert assignments[0]["status"] == "ROSTERED"

        get_success_data(
            api.suspend_volunteer(
                volunteer["id"], suspend_payload(event["id"]), VC
            )
        )
        assignments, _ = validate_paginated(
            api.list_event_assignments(event["id"], VC)
        )
        assert assignments[0]["status"] == "RELEASED"

        get_success_data(
            api.reinstate_volunteer(
                volunteer["id"], {"clinic_event_id": event["id"]}, VC
            )
        )
        assignments, _ = validate_paginated(
            api.list_event_assignments(event["id"], VC)
        )
        assert assignments[0]["status"] == "RELEASED", (
            "reinstatement must not restore the released assignment"
        )

        reauthorized = authorize_volunteer(volunteer["id"], event["id"])
        assert reauthorized["status"] == "AUTHORIZED"


class TestStationDegradedOperationalLoop:
    def test_backlog_above_ceiling_degrades_then_completion_recovers(self, api):
        """PRD §3.5: "Whenever the backlog for an event with a
        sterilization-requiring `OPERATIONAL` station rises strictly above 6
        pending batches, that station degrades automatically to `DEGRADED`"
        and "A `DEGRADED` station returns to `OPERATIONAL` automatically when
        a cycle completes and the backlog falls back to 6 or fewer."

        Design: Difficulty/non_linear_state_machine/station_operational_degraded_operational_sterilization_loop
        """
        ctx = setup_event_with_operational_sterile_station()
        event_id, station_id = ctx["id"], ctx["station_id"]

        # Two RUNNING cycles of 4 and 3 batches put the pending backlog at 7.
        cycle_b = get_success_data(
            api.start_sterilization_cycle(
                event_id, {"instrument_batch_size": 4}, ST
            )
        )
        get_success_data(
            api.start_sterilization_cycle(
                event_id, {"instrument_batch_size": 3}, ST
            )
        )
        stations, _ = validate_paginated(
            api.list_event_stations(event_id, SL)
        )
        assert stations[0]["status"] == "DEGRADED"

        # Completing the 4-batch cycle drops the backlog to 3 (<= 6).
        get_success_data(api.complete_cycle(event_id, cycle_b["id"], ST))
        stations, _ = validate_paginated(
            api.list_event_stations(event_id, SL)
        )
        assert stations[0]["status"] == "OPERATIONAL"

    def test_degrade_recovers_and_can_degrade_again(self, api):
        """PRD §3.5: "Whenever the backlog for an event with a
        sterilization-requiring `OPERATIONAL` station rises strictly above 6
        pending batches, that station degrades automatically to `DEGRADED`;
        a backlog of exactly 6 does not trigger degradation. A `DEGRADED`
        station returns to `OPERATIONAL` automatically when a cycle completes
        and the backlog falls back to 6 or fewer."

        Design: Difficulty/non_linear_state_machine/station_operational_degraded_operational_sterilization_loop
        """
        ctx = setup_event_with_operational_sterile_station()
        event_id, station_id = ctx["id"], ctx["station_id"]

        for _ in range(2):
            cycle = get_success_data(
                api.start_sterilization_cycle(
                    event_id, {"instrument_batch_size": 7}, ST
                )
            )
            stations, _ = validate_paginated(
                api.list_event_stations(event_id, SL)
            )
            assert stations[0]["status"] == "DEGRADED"
            get_success_data(api.complete_cycle(event_id, cycle["id"], ST))
            stations, _ = validate_paginated(
                api.list_event_stations(event_id, SL)
            )
            assert stations[0]["status"] == "OPERATIONAL"
