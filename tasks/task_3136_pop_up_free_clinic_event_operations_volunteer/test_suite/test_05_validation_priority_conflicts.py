"""Validation gate conflicts: the posture gate on station dismantle, and
existence-beats-fiscal on agreement creation."""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_event,
    create_event_in_service,
    create_site,
    create_site_payload,
    create_station,
    setup_station,
    get_success_data,
    validate_error,
    validate_success,
)

ED = TEST_USERS["event_director_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]


class TestPostureGateOnDismantle:
    def test_dismantle_in_planning_rejected_by_posture_gate(self, api):
        """PRD §3.8: "Dismantling stations — `OPERATIONAL`, `DEGRADED`, or
        `OFFLINE` to `DISMANTLED` — is a `LogisticsCoordinator` action
        permitted only in `TEARDOWN` posture" and PRD §2.4: "nearly every
        child operation — drafting an agreement, setting up a station, issuing
        a ticket, dismantling a lane — is permitted only when the parent
        event's posture allows it, and a forbidden attempt is rejected with
        `ERR_EVENT_POSTURE_FORBIDS` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/posture_state_beats_safety_sterilization
        """
        event = create_event(
            service_date="2026-12-12",
            doors_open_utc="2026-12-12T10:00:00Z",
            total_patient_capacity=100,
        )
        station = create_station(
            event["id"],
            station_label="D-9",
            station_type="DENTAL",
            chair_count=1,
            minutes_per_patient=30,
            requires_sterilization=True,
            service_window_open_utc="2026-12-12T11:00:00Z",
            service_window_close_utc="2026-12-12T19:00:00Z",
        )
        response = api.dismantle_station(event["id"], station["id"], LC)
        validate_error(response, "ERR_EVENT_POSTURE_FORBIDS")

    def test_dismantle_in_teardown_succeeds_for_set_up_station(self, api):
        """PRD §3.8: "Dismantling stations — `OPERATIONAL`, `DEGRADED`, or
        `OFFLINE` to `DISMANTLED` — is a `LogisticsCoordinator` action
        permitted only in `TEARDOWN` posture, and it recomputes station
        counts." The posture gate is the dismantle gate: the same call passes
        once the event reaches TEARDOWN.

        Design: Difficulty/priority_pair_validation_conflict/posture_state_beats_safety_sterilization
        """
        event = create_event_in_service(
            event_overrides={
                "service_date": "2026-12-12",
                "doors_open_utc": "2026-12-12T10:00:00Z",
            }
        )
        get_success_data(api.end_service(event["id"], ED))
        # Stations reach TEARDOWN in SET_UP/OPERATIONAL state; dismantle the
        # OPERATIONAL medical station created by the fixture.
        response = api.dismantle_station(event["id"], event["station_id"], LC)
        dismantled = validate_success(response, 200)
        assert dismantled["status"] == "DISMANTLED"


class TestExistenceBeatsFiscalOnAgreementCreate:
    def test_missing_site_and_negative_cap_reports_not_found(self, api):
        """PRD §2.6: "Referential integrity requires that every foreign-key
        target named in a request exists and sits in a compatible state — ...
        a target that is missing or in an incompatible state is rejected with
        `ERR_REFERENCE_INVALID`." The agreement names a site (in the request
        body) that does not exist while also carrying a negative liability
        cap; the referential failure is the one reported.

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_agreement_create
        """
        event = create_event(
            service_date="2026-12-19",
            doors_open_utc="2026-12-19T10:00:00Z",
            total_patient_capacity=100,
        )
        response = api.create_site_agreement(
            event["id"],
            {
                "site_id": NON_EXISTENT_UUID,
                "host_org_name": "Ghost",
                "liability_cap_cents": -5,
                "insurance_certificate_ref": "C10",
                "expected_event_version": event["version"],
            },
            LC,
        )
        validate_error(response, "ERR_REFERENCE_INVALID")

    def test_negative_liability_cap_alone_is_fiscal_violation(self, api):
        """PRD §3.2: "A negative liability cap is a fiscal violation rejected
        with `ERR_FISCAL_RULE_VIOLATION`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_agreement_create
        """
        site = get_success_data(
            api.create_site(create_site_payload(), LC)
        )
        event = create_event(
            service_date="2026-12-19",
            doors_open_utc="2026-12-19T10:00:00Z",
            total_patient_capacity=100,
        )
        response = api.create_site_agreement(
            event["id"],
            {
                "site_id": site["id"],
                "host_org_name": "Arena",
                "liability_cap_cents": -5,
                "insurance_certificate_ref": "C10",
                "expected_event_version": event["version"],
            },
            LC,
        )
        validate_error(response, "ERR_FISCAL_RULE_VIOLATION")
