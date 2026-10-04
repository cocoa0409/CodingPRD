"""Dispatch selector policy, dispatch lifecycle, SLA latch, team counters."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_triaged_visit,
    make_care_team_member_headers,
    offer_dispatch,
    offer_dispatch_fresh,
    set_clock,
    setup_market_team_shift,
    setup_visit_on_scene,
    validate_error,
    validate_success,
    create_patient,
)

ADMIN = TEST_USERS["platform_admin_headers"]
NURSE = TEST_USERS["triage_nurse_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestDispatchSelectorAndImmediateConsistency:
    def test_selector_picks_most_recently_available_team(self, api):
        """PRD §3.4: "Each candidate is scored: start from 1000, subtract 100
        per active dispatch ... and subtract the whole minutes elapsed between
        the team's `updated_at` — the timestamp of its most recent transition
        into `AVAILABLE` — and the logical clock. Higher score wins; ties are
        broken deterministically by the team's earlier `created_at`, never by
        id".
        PRD §3.4: "The winning team's `selection_score` is recorded on the
        resulting **DispatchAssignment**, which is created in `OFFERED` status".

        Design: Corner/endpoints/dispatch_offer_returns_selector_chosen_team
        """
        set_clock("2026-09-15T10:00:00Z")
        ctx = setup_market_team_shift(
            app_user="app-FA", tech_user="tech-FA", md_user="md-FA"
        )
        market = ctx["market"]
        # Team A became AVAILABLE at 10:00. Advance clock, then roster team B
        # and bring it AVAILABLE at 10:30 -> B has the smaller
        # minutes_since_available, hence the higher score.
        set_clock("2026-09-15T10:30:00Z")
        from test_helpers import api_client as _api
        from test_helpers import create_care_team_payload, create_vehicle_shift_payload
        from test_helpers import get_success_data as _ok

        team_b = _ok(
            _api.create_care_team(
                create_care_team_payload(
                    market["id"], app_user_id="app-FB", tech_user_id="tech-FB",
                    supervising_physician_user_id="md-FB", skill_tags=["POCT"],
                ),
                DISPATCHER,
            )
        )
        _ok(_api.care_team_go_available(team_b["id"], DISPATCHER))
        shift_b = _ok(
            _api.create_vehicle_shift(
                create_vehicle_shift_payload(
                    team_b["id"], market["id"],
                    window_start="2026-09-15T08:00:00Z",
                    window_end="2026-09-15T23:00:00Z",
                ),
                DISPATCHER,
            )
        )
        _ok(_api.start_vehicle_shift(shift_b["id"], DISPATCHER))

        patient = create_patient()
        t = create_triaged_visit(market["id"], patient["id"])
        # OCC token must be the visit's CURRENT version (the triage cascade
        # incremented it after creation).
        vr_now = validate_success(api.get_visit_request(t["vr"]["id"], DISPATCHER))
        da = validate_success(
            api.create_dispatch_offer(
                t["vr"]["id"],
                {"expected_visit_request_version": vr_now["version"]},
                DISPATCHER,
            ),
            expected_status=201,
        )
        assert da["care_team_id"] == team_b["id"], (
            "more recently AVAILABLE team must win the selector policy"
        )
        assert "selection_score" in da
        assert da["status"] == "OFFERED"

    def test_offer_response_and_visit_read_consistent_immediately(self, api):
        """PRD §3.4: "The offer's side effects land in one transaction: the
        team's `active_dispatch_count` rises by one, an `AVAILABLE` team flips
        to `ON_DISPATCH`, the visit moves to `DISPATCH_PENDING`, and the
        visit's `version` increments."
        PRD §2.5: "`version` (integer): a system-managed integer starting at 1
        that increments on every mutation".

        Design: Corner/consistency_model/immediate_consistency_on_response
        """
        ctx = setup_market_team_shift(
            app_user="app-J2", tech_user="tech-J2", md_user="md-J2"
        )
        patient = create_patient()
        t = create_triaged_visit(ctx["market"]["id"], patient["id"])
        # Current version after the triage cascade incremented it.
        v0 = validate_success(
            api.get_visit_request(t["vr"]["id"], DISPATCHER)
        )["version"]
        da = validate_success(
            api.create_dispatch_offer(
                t["vr"]["id"],
                {"expected_visit_request_version": v0},
                DISPATCHER,
            ),
            expected_status=201,
        )
        assert da["status"] == "OFFERED"
        assert da["version"] == 1
        vr_after = validate_success(api.get_visit_request(t["vr"]["id"], DISPATCHER))
        assert vr_after["status"] == "DISPATCH_PENDING"
        assert vr_after["version"] == v0 + 1


class TestDispatchRejectCycle:
    def test_cancel_offer_also_returns_visit_to_triaged(self, api):
        """PRD §3.4: "A `Dispatcher` may likewise cancel an `OFFERED`
        assignment, which moves it to `CANCELLED`, applies the same
        team-counter decrement, and returns the visit to `TRIAGED`."

        Design: Difficulty/non_linear_state_machine/dispatch_offer_reject_returns_to_triaged_then_reoffer
        """
        ctx = setup_market_team_shift(
            app_user="app-A2", tech_user="tech-A2", md_user="md-A2"
        )
        patient = create_patient()
        t = create_triaged_visit(ctx["market"]["id"], patient["id"])
        da = offer_dispatch_fresh(t["vr"]["id"])
        cancelled = validate_success(api.cancel_dispatch(da["id"], DISPATCHER))
        assert cancelled["status"] == "CANCELLED"
        vr_after = validate_success(api.get_visit_request(t["vr"]["id"], DISPATCHER))
        assert vr_after["status"] == "TRIAGED"
        team_after = validate_success(api.get_care_team(ctx["team"]["id"], DISPATCHER))
        assert team_after["active_dispatch_count"] == 0

    def test_reject_returns_visit_to_triaged_and_reoffer_succeeds(self, api):
        """PRD §3.4: "Rejection from `OFFERED` moves the assignment to
        `REJECTED`, decrements the team's `active_dispatch_count` (returning a
        zeroed team to `AVAILABLE`), and returns the visit to `TRIAGED` — the
        `DISPATCH_PENDING`-to-`TRIAGED` loop may cycle as often as needed
        until a team accepts."

        Design: Difficulty/non_linear_state_machine/dispatch_offer_reject_returns_to_triaged_then_reoffer
        """
        ctx = setup_market_team_shift(
            app_user="app-A", tech_user="tech-A", md_user="md-A"
        )
        patient = create_patient()
        t = create_triaged_visit(ctx["market"]["id"], patient["id"])
        da1 = offer_dispatch_fresh(t["vr"]["id"])
        member = make_care_team_member_headers("app-A")
        rejected = validate_success(api.reject_dispatch(da1["id"], member))
        assert rejected["status"] == "REJECTED"
        vr_mid = validate_success(api.get_visit_request(t["vr"]["id"], DISPATCHER))
        assert vr_mid["status"] == "TRIAGED"
        da2 = offer_dispatch(t["vr"]["id"], vr_mid["version"])
        assert da2["status"] == "OFFERED"

    def test_reject_cascade_restores_team_available(self, api):
        """PRD §3.4: "when the first dispatch is created for an `AVAILABLE`
        team the team becomes `ON_DISPATCH`, and when its
        `active_dispatch_count` falls back to zero the team returns to
        `AVAILABLE`."

        Design: Difficulty/transitive_cascade/dispatch_reject_cascade_dispatch_to_team_status
        """
        ctx = setup_market_team_shift(
            app_user="app-F", tech_user="tech-F", md_user="md-F"
        )
        patient = create_patient()
        t = create_triaged_visit(ctx["market"]["id"], patient["id"])
        da = offer_dispatch_fresh(t["vr"]["id"])
        team_mid = validate_success(api.get_care_team(ctx["team"]["id"], DISPATCHER))
        assert team_mid["active_dispatch_count"] == 1
        assert team_mid["status"] == "ON_DISPATCH"
        member = make_care_team_member_headers("app-F")
        validate_success(api.reject_dispatch(da["id"], member))
        team_after = validate_success(api.get_care_team(ctx["team"]["id"], DISPATCHER))
        assert team_after["active_dispatch_count"] == 0
        assert team_after["status"] == "AVAILABLE"
        vr_after = validate_success(api.get_visit_request(t["vr"]["id"], DISPATCHER))
        assert vr_after["status"] == "TRIAGED"

    def test_offer_flips_available_team_to_on_dispatch(self, api):
        """PRD §3.4: "when the first dispatch is created for an `AVAILABLE`
        team the team becomes `ON_DISPATCH`, and when its
        `active_dispatch_count` falls back to zero the team returns to
        `AVAILABLE`."

        Design: Difficulty/transitive_cascade/dispatch_reject_cascade_dispatch_to_team_status
        """
        ctx = setup_market_team_shift(
            app_user="app-F2", tech_user="tech-F2", md_user="md-F2"
        )
        patient = create_patient()
        t = create_triaged_visit(ctx["market"]["id"], patient["id"])
        offer_dispatch_fresh(t["vr"]["id"])
        team_mid = validate_success(api.get_care_team(ctx["team"]["id"], DISPATCHER))
        assert team_mid["status"] == "ON_DISPATCH"
        assert team_mid["active_dispatch_count"] == 1


class TestActiveDispatchCountInvariant:
    def test_offer_increments_reject_restores(self, api):
        """PRD §3.4: "The computed `active_dispatch_count` tallies the team's
        dispatch assignments currently in `OFFERED`, `ACCEPTED`, `EN_ROUTE`,
        or `ARRIVED`."

        Design: Difficulty/compensating_invariant/care_team_active_dispatch_count_invariant
        """
        ctx = setup_market_team_shift(
            app_user="app-O", tech_user="tech-O", md_user="md-O"
        )
        team_id = ctx["team"]["id"]
        before = validate_success(api.get_care_team(team_id, DISPATCHER))
        assert before["active_dispatch_count"] == 0
        patient = create_patient()
        t = create_triaged_visit(ctx["market"]["id"], patient["id"])
        da = offer_dispatch_fresh(t["vr"]["id"])
        after_offer = validate_success(api.get_care_team(team_id, DISPATCHER))
        assert after_offer["active_dispatch_count"] == 1
        member = make_care_team_member_headers("app-O")
        validate_success(api.reject_dispatch(da["id"], member))
        after_reject = validate_success(api.get_care_team(team_id, DISPATCHER))
        assert after_reject["active_dispatch_count"] == 0
        assert after_reject["status"] == "AVAILABLE"

    def test_completion_decrements_count_at_disposition(self, api):
        """PRD §3.6: "the dispatch assignment completes, the care team's
        `active_dispatch_count` falls by one, and a team reaching zero returns
        to `AVAILABLE`."

        Design: Difficulty/compensating_invariant/care_team_active_dispatch_count_invariant
        """
        from test_helpers import discharge_home

        ctx = setup_visit_on_scene(app_user="app-O2", tech_user="tech-O2")
        team_id = ctx["team"]["id"]
        en_route = validate_success(api.get_care_team(team_id, DISPATCHER))
        assert en_route["active_dispatch_count"] == 1
        discharge_home(ctx)
        after = validate_success(api.get_care_team(team_id, DISPATCHER))
        assert after["active_dispatch_count"] == 0
        assert after["status"] == "AVAILABLE"
        da_after = validate_success(
            api.get_dispatch_assignment(ctx["da"]["id"], DISPATCHER)
        )
        assert da_after["status"] == "COMPLETED"


class TestSlaBreachBoundary:
    def test_arrival_exactly_at_deadline_is_not_a_breach(self, api):
        """PRD §3.4: "At that moment the SLA latch is evaluated once: if the
        encounter's `started_at` is strictly after the visit's
        `sla_deadline_at`, the visit's `sla_breached` is set true and stays
        true; an arrival exactly at the deadline is not a breach, because the
        comparison is strictly greater-than."

        Design: Difficulty/boundary_precision_check/sla_breach_strict_greater_than
        """
        # URGENT band: vitals give score 58 -> URGENT; window 60 minutes.
        ctx = setup_market_team_shift(app_user="app-J", tech_user="tech-J")
        patient = create_patient()
        t = create_triaged_visit(ctx["market"]["id"], patient["id"])
        vr = validate_success(api.get_visit_request(t["vr"]["id"], DISPATCHER))
        assert vr["acuity_band"] == "URGENT"
        da = offer_dispatch_fresh(t["vr"]["id"])
        member = make_care_team_member_headers("app-J")
        validate_success(api.accept_dispatch(da["id"], member))
        # accepted at 10:00 -> deadline 11:00. Arrive AT 11:00:00.
        set_clock("2026-09-15T11:00:00Z")
        validate_success(api.arrive_dispatch(da["id"], member))
        vr_after = validate_success(api.get_visit_request(t["vr"]["id"], DISPATCHER))
        assert vr_after["sla_deadline_at"] == "2026-09-15T11:00:00.000Z"
        assert vr_after["sla_breached"] is False

    def test_arrival_one_second_after_deadline_is_a_breach(self, api):
        """PRD §3.4: "if the encounter's `started_at` is strictly after the
        visit's `sla_deadline_at`, the visit's `sla_breached` is set true and
        stays true; an arrival exactly at the deadline is not a breach,
        because the comparison is strictly greater-than."

        Design: Difficulty/boundary_precision_check/sla_breach_strict_greater_than
        """
        ctx = setup_market_team_shift(app_user="app-J", tech_user="tech-J")
        patient = create_patient()
        t = create_triaged_visit(ctx["market"]["id"], patient["id"])
        da = offer_dispatch_fresh(t["vr"]["id"])
        member = make_care_team_member_headers("app-J")
        validate_success(api.accept_dispatch(da["id"], member))
        set_clock("2026-09-15T11:00:01Z")
        validate_success(api.arrive_dispatch(da["id"], member))
        vr_after = validate_success(api.get_visit_request(t["vr"]["id"], DISPATCHER))
        assert vr_after["sla_deadline_at"] == "2026-09-15T11:00:00.000Z"
        assert vr_after["sla_breached"] is True


class TestDispatchInvalidTransitions:
    def test_accept_from_arrived_rejected(self, api):
        """PRD §3.4: "Acceptance requires the assignment to be `OFFERED`
        (`ERR_DISPATCH_INVALID_STATE`, HTTP 409, otherwise)".

        Design: Corner/state_machines/dispatch_accept_from_arrived_returns_dispatch_invalid_state
        """
        ctx = setup_visit_on_scene(app_user="app-W", tech_user="tech-W")
        member = make_care_team_member_headers("app-W")
        resp = api.accept_dispatch(ctx["da"]["id"], member)
        validate_error(resp, ApiErrorId.ERR_DISPATCH_INVALID_STATE)
        da_after = validate_success(
            api.get_dispatch_assignment(ctx["da"]["id"], DISPATCHER)
        )
        assert da_after["status"] == "ARRIVED"

    def test_terminal_visit_blocks_dispatch_offer(self, api):
        """PRD §3.2: "The terminal states are `EMS_DIVERTED`, `DECLINED`, and
        `CLOSED`. Any action attempted against a visit that is not in a state
        from which that action is defined is rejected with
        `ERR_VR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/terminal_visit_request_blocks_further_transitions
        """
        from test_helpers import RED_FLAG_VITALS

        ctx = setup_market_team_shift(app_user="app-X", tech_user="tech-X")
        patient = create_patient()
        t = create_triaged_visit(
            ctx["market"]["id"], patient["id"],
            chief_complaint="crushing chest pain",
            vitals=RED_FLAG_VITALS,
            outcome="EMERGENCY_DIVERTED",
        )
        # The diversion cascade mutates the visit (band + status), incrementing
        # its version; use the current version so the OCC token is fresh and
        # the state check is what fires (PRD §2: version check precedes state).
        vr_now = validate_success(api.get_visit_request(t["vr"]["id"], DISPATCHER))
        resp = api.create_dispatch_offer(
            t["vr"]["id"],
            {"expected_visit_request_version": vr_now["version"]},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_VR_INVALID_STATE)
        vr_after = validate_success(api.get_visit_request(t["vr"]["id"], DISPATCHER))
        assert vr_after["status"] == "EMS_DIVERTED"


class TestMarketGateCrossEntity:
    def test_dispatch_offer_succeeds_when_market_active(self, api):
        """PRD §3.4: "The visit's market must still be active
        (`ERR_MARKET_INACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/visit_dispatch_requires_market_active
        """
        ctx = setup_market_team_shift(app_user="app-L", tech_user="tech-L")
        patient = create_patient()
        t = create_triaged_visit(ctx["market"]["id"], patient["id"])
        da = offer_dispatch_fresh(t["vr"]["id"])
        assert da["status"] == "OFFERED"
        vr_after = validate_success(api.get_visit_request(t["vr"]["id"], DISPATCHER))
        assert vr_after["status"] == "DISPATCH_PENDING"

    def test_intake_into_inactive_market_rejected(self, api):
        """PRD §3.2: "Two guards run before the visit exists: the chosen
        market's `is_active` must be true (else `ERR_MARKET_INACTIVE`)".

        Design: Difficulty/cross_entity_state_dependency/visit_dispatch_requires_market_active
        """
        set_clock()
        from test_helpers import create_market_payload, create_visit_request_payload
        from test_helpers import get_success_data as _ok
        from test_helpers import api_client as _api

        market = _ok(
            _api.create_market(create_market_payload(is_active=False), ADMIN)
        )
        patient = create_patient()
        resp = api.create_visit_request(
            create_visit_request_payload(patient["id"], market["id"]), NURSE
        )
        validate_error(resp, ApiErrorId.ERR_MARKET_INACTIVE)
