"""Two deliberately different temporal treatments: a half-open live-call interval on
the agent, and a closed buffered scope-validity window.
"""
import pytest

from test_helpers import (
    validate_paginated, api_client, utc, get_success_data, validate_error, validate_success,
    set_clock, create_agency, create_carrier, create_plan, create_agency_payload,
    create_and_activate_agent, create_member_for_agent, capture_scope,
    open_call, connect_call, complete_call, get_call, submit_enrollment,
    create_enrollment_payload, create_call_session_payload, setup_master_data,
    CLOCK_START, TEST_USERS, make_licensed_agent_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DIRECTOR = TEST_USERS["director_of_sales_headers"]


class TestHalfOpenLiveCallInterval:
    """A live call occupies [started_at, scheduled_end_at); adjacency is free."""

    def _live_call_scenario(self):
        set_clock("2026-10-01T09:00:00Z")
        agency = get_success_data(api_client.create_agency(create_agency_payload(), ADMIN))
        carrier = get_success_data(api_client.create_carrier(
            {"legal_name": "Meridian Health Plan of Texas", "naic_number": "60211",
             "contract_type": "CONTRACTED", "initial_commission_rate_pct": 0.20,
             "renewal_commission_rate_pct": 0.10, "chargeback_clawback_pct": 0.25,
             "ack_expected_within_days": 5, "effectuation_expected_within_days": 30},
            ADMIN))
        plan = create_plan(carrier["id"])
        agent, _, _, _ = create_and_activate_agent(agency["id"], carrier["id"])

        member, version = create_member_for_agent(agency["id"], agent["id"])
        scope = capture_scope(member["id"], agent["id"], version)
        member_two, version_two = create_member_for_agent(
            agency["id"], agent["id"], full_name="Hollis Pike",
            medicare_beneficiary_id="3GH6-VG7-PM94",
            date_of_birth="1952-11-19T00:00:00Z")
        scope_two = capture_scope(member_two["id"], agent["id"], version_two)

        call_a = open_call(agent["id"], member["id"], scope["id"],
                           started_at="2026-10-01T09:00:00Z",
                           scheduled_end_at="2026-10-01T10:00:00Z",
                           recording_id="REC-A")
        connect_call(agent["id"], call_a["id"], recording_id="REC-A")
        return {"agency": agency, "carrier": carrier, "plan": plan, "agent": agent,
                "member": member, "scope": scope, "member_two": member_two,
                "scope_two": scope_two, "call_a": call_a}

    def _overlapping_call_payload(self, scn, started_at, scheduled_end_at):
        return create_call_session_payload(
            scn["agent"]["id"], scn["member_two"]["id"], scn["scope_two"]["id"],
            started_at=started_at, scheduled_end_at=scheduled_end_at,
            recording_id="REC-B")

    def test_a_call_opening_inside_the_live_interval_is_refused(self):
        """PRD §3.3: "An agent may not run two live calls at once: if another call of the
        same agent is in `IN_PROGRESS` and its half-open interval contains the current
        logical clock, the new call is refused with `ERR_AGENT_HAS_ACTIVE_CALL`."

        Design: Difficulty/resource_temporal_overlap/overlap_half_open_live_call_interval_on_agent
        """
        scn = self._live_call_scenario()
        headers = make_licensed_agent_headers(scn["agent"]["id"])
        resp = api_client.create_call_session(
            self._overlapping_call_payload(scn, "2026-10-01T09:59:00Z",
                                           "2026-10-01T10:29:00Z"), headers)
        validate_error(resp, "ERR_AGENT_HAS_ACTIVE_CALL", expected_status=409)

    def test_a_call_opening_exactly_at_the_prior_close_is_accepted(self):
        """PRD §3.3: "The boundary is deliberately exclusive at the touching point — an
        interval that ends exactly where the next begins is not an overlap."
        PRD §2.6: "A call session records the live interval during which plan discussion
        occurs as the half-open range from `started_at` up to but excluding
        `scheduled_end_at`."

        Design: Difficulty/resource_temporal_overlap/overlap_half_open_live_call_interval_on_agent
        """
        scn = self._live_call_scenario()
        headers = make_licensed_agent_headers(scn["agent"]["id"])
        result = validate_success(api_client.create_call_session(
            self._overlapping_call_payload(scn, "2026-10-01T10:00:00Z",
                                           "2026-10-01T10:30:00Z"), headers), 201)
        assert result["started_at"] == utc("2026-10-01T10:00:00Z"), (
            "exactly the instant the first interval closed"
        )

    def test_the_prior_call_is_unchanged_and_only_one_row_was_refused(self):
        """PRD §3.3: "The call begins in `RINGING`, `recording_retained_until` is derived
        as `started_at` plus the agency's `recording_retention_days`, and `live_call_count`
        is recomputed for the agent."

        Design: Difficulty/resource_temporal_overlap/overlap_half_open_live_call_interval_on_agent
        """
        scn = self._live_call_scenario()
        headers = make_licensed_agent_headers(scn["agent"]["id"])
        api_client.create_call_session(
            self._overlapping_call_payload(scn, "2026-10-01T09:59:00Z",
                                           "2026-10-01T10:29:00Z"), headers)

        call_a = get_call(scn["agent"]["id"], scn["call_a"]["id"])
        assert call_a["status"] == "IN_PROGRESS"
        assert call_a["scheduled_end_at"] == utc("2026-10-01T10:00:00Z")

        rows, _meta = validate_paginated(api_client.list_agent_call_sessions(
            scn["agent"]["id"], DIRECTOR))
        assert len(rows) == 1, "the refused request created nothing"

    def test_the_connected_call_raises_live_call_count_on_the_agent(self):
        """PRD §3.3: "On success the call advances to `IN_PROGRESS` and `live_call_count`
        is recomputed."

        Design: Difficulty/resource_temporal_overlap/overlap_half_open_live_call_interval_on_agent
        """
        scn = self._live_call_scenario()
        agent = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
        assert agent["live_call_count"] == 1


class TestClosedBufferedScopeValidityWindow:
    """The scope window is [captured_on, expires_on] inclusive at both ends."""

    def _boundary_scenario(self):
        scn = setup_master_data()
        agent, _, _, _ = create_and_activate_agent(
            scn["agency"]["id"], scn["carrier"]["id"])
        member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
        scope = capture_scope(member["id"], agent["id"], version)
        call = open_call(agent["id"], member["id"], scope["id"])
        connect_call(agent["id"], call["id"])
        call = complete_call(agent["id"], call["id"])
        scn.update({"agent": agent, "member": member, "scope": scope, "call": call})
        return scn

    def test_the_expiry_boundary_is_inclusive(self):
        """PRD §2.5: "Its `expires_on` is the `captured_on` instant plus the owning agency's
        `soa_max_age_days`, which defaults to 30."
        PRD §2.5: "The expiry boundary is inclusive — a clock reading exactly at
        `expires_on` is still usable."

        Design: Difficulty/resource_temporal_overlap/overlap_closed_buffered_scope_validity_window
        """
        scn = self._boundary_scenario()
        set_clock("2026-10-31T00:00:00Z")
        scope = get_success_data(api_client.get_scope(
            scn["scope"]["id"], make_licensed_agent_headers(scn["agent"]["id"])))
        assert scope["status"] == "CAPTURED"
        assert scope["expires_on"] == utc("2026-10-31T00:00:00Z")

        scn["call"] = get_call(scn["agent"]["id"], scn["call"]["id"])
        enrollment = submit_enrollment(
            scn["agent"]["id"], scn["call"]["id"], scn["member"]["id"],
            scn["plan"]["id"], scn["scope"]["id"], scn["call"]["version"])
        assert enrollment["submission_status"] == "SUBMITTED", (
            "the closed window admits the submission at its far end"
        )

    def test_one_day_past_the_window_the_same_request_is_refused(self):
        """PRD §2.5: "A scope that has been consumed is no longer usable".
        PRD §2.5: "a scope that is `CONSUMED` or `VOIDED` is permanently unusable."

        Design: Difficulty/resource_temporal_overlap/overlap_closed_buffered_scope_validity_window
        """
        scn = self._boundary_scenario()
        set_clock("2026-11-01T00:00:00Z")
        scn["call"] = get_call(scn["agent"]["id"], scn["call"]["id"])
        headers = make_licensed_agent_headers(scn["agent"]["id"])
        resp = api_client.create_enrollment(create_enrollment_payload(
            scn["call"]["id"], scn["member"]["id"], scn["plan"]["id"],
            scn["agent"]["id"], scn["scope"]["id"], scn["call"]["version"]), headers)
        validate_error(resp, "ERR_SCOPE_OF_APPOINTMENT_MISSING", expected_status=422)

    def test_the_scope_row_is_retained_after_its_usability_lapses(self):
        """PRD §2.5: "Its `retained_until` is `captured_on` plus the agency's
        `soa_retention_days`, which defaults to 3650 — the ten-year record the compliance
        function is obliged to keep."
        PRD §2.5: "Anything that is not `CAPTURED` is unusable".

        Design: Difficulty/resource_temporal_overlap/overlap_closed_buffered_scope_validity_window
        """
        scn = self._boundary_scenario()
        set_clock("2026-11-01T00:00:00Z")
        scope = get_success_data(api_client.get_scope(
            scn["scope"]["id"], make_licensed_agent_headers(scn["agent"]["id"])))
        assert scope["status"] == "CAPTURED", (
            "the stored enum does not move; only its usability lapsed"
        )
        assert scope["captured_on"] == utc("2026-10-01T00:00:00Z")
        assert scope["retained_until"] == utc("2036-09-28T00:00:00Z")

    def test_consuming_the_scope_writes_the_enrollment_id_into_the_row(self):
        """PRD §2.5: "consuming a scope writes the consuming enrollment's id into
        `consumed_by_enrollment_id` and moves the scope to `CONSUMED`."

        Design: Difficulty/resource_temporal_overlap/overlap_closed_buffered_scope_validity_window
        """
        scn = self._boundary_scenario()
        set_clock("2026-10-31T00:00:00Z")
        scn["call"] = get_call(scn["agent"]["id"], scn["call"]["id"])
        enrollment = submit_enrollment(
            scn["agent"]["id"], scn["call"]["id"], scn["member"]["id"],
            scn["plan"]["id"], scn["scope"]["id"], scn["call"]["version"])
        effectuated = validate_success(api_client.effectuate_enrollment(
            enrollment["id"], TEST_USERS["carrier_integration_headers"]), 200)
        assert effectuated["disenrollment_status"] == "ENROLLED"

        scope = get_success_data(api_client.get_scope(
            scn["scope"]["id"], make_licensed_agent_headers(scn["agent"]["id"])))
        assert scope["status"] == "CONSUMED"
        assert scope["consumed_by_enrollment_id"] == enrollment["id"]