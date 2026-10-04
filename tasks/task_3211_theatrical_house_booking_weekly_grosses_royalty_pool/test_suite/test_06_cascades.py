"""Cascade claims: eviction depth-3 chain, maintenance completion, in-use guard."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_active_booking, sell_week1_order, open_report, set_clock,
    submit_report, verify_report, get_booking, get_order, get_report,
    list_stop_notices, create_capital_project_payload,
    TEST_DEFAULTS,
)

HM = TEST_USERS["house_manager_headers"]
BO = TEST_USERS["box_office_agent_headers"]


def _drive_two_under_floor_weeks(ctx):
    """Verify two consecutive under-floor weeks (gross 10000 < floor 50000)
    so the stop-notice counter reaches 2."""
    sell_week1_order(ctx["booking"]["id"],
                     performance_date="2026-09-08T19:00:00Z")
    rep1 = open_report(ctx["booking"]["id"], ctx["company"]["id"],
                       week_start=TEST_DEFAULTS["WEEK1_START"])
    set_clock(TEST_DEFAULTS["WEEK1_END"])
    submit_report(rep1["id"], ctx["company"]["id"])
    verify_report(rep1["id"])
    sell_week1_order(ctx["booking"]["id"],
                     performance_date="2026-09-15T19:00:00Z")
    rep2 = open_report(ctx["booking"]["id"], ctx["company"]["id"],
                       week_start=TEST_DEFAULTS["WEEK2_START"])
    set_clock(TEST_DEFAULTS["WEEK2_END"])
    submit_report(rep2["id"], ctx["company"]["id"])
    verify_report(rep2["id"])
    return rep1, rep2


class TestEvictionCascadeDepth3:
    def _setup(self, api):
        ctx = setup_active_booking(stop_clause_weekly_floor_cents=50000,
                                   stop_clause_consecutive_weeks=2,
                                   company_name="EvictCo",
                                   company_email="e@x.com")
        _drive_two_under_floor_weeks(ctx)
        future_order = sell_week1_order(
            ctx["booking"]["id"], performance_date="2026-09-23T19:00:00Z")
        rep3 = open_report(ctx["booking"]["id"], ctx["company"]["id"],
                           week_start=TEST_DEFAULTS["WEEK3_START"])
        return ctx, future_order, rep3

    def test_eviction_moves_booking_and_executes_notice(self, api):
        """PRD §3.7: "once the counter reaches
        `stop_clause_consecutive_weeks`, a `HouseManager` may execute the stop
        notice, which moves the booking from `ACTIVE` to `EVICTED` and the
        notice from `OPEN` to `EXECUTED`."

        Design: Difficulty/transitive_cascade/eviction_cascade_depth3
        """
        ctx, future_order, rep3 = self._setup(api)
        validate_success(api_client.execute_stop_notice(ctx["booking"]["id"], HM))
        assert get_booking(ctx["booking"]["id"])["status"] == "EVICTED"
        notices = list_stop_notices(ctx["booking"]["id"])
        assert len(notices) == 1
        assert notices[0]["status"] == "EXECUTED", (
            f"depth 1: notice must be EXECUTED, got {notices[0]['status']}")

    def test_eviction_refunds_future_orders_and_recomputes_draft_report(self, api):
        """PRD §3.7: "Depth 2: every future-dated `SOLD` ticket order — one
        whose `performance_date` is strictly after the eviction timestamp — is
        refunded, its status moving to `REFUNDED`. Depth 3: each cascaded
        refund reduces the gross of the covering `DRAFT` or `SUBMITTED` weekly
        gross report for the affected week, recomputed via the provisional
        weekly-gross variant."

        Design: Difficulty/transitive_cascade/eviction_cascade_depth3
        """
        ctx, future_order, rep3 = self._setup(api)
        validate_success(api_client.execute_stop_notice(ctx["booking"]["id"], HM))
        assert get_order(future_order["id"])["status"] == "REFUNDED"
        assert get_report(rep3["id"])["gross_cents"] == 0, (
            f"depth 3: DRAFT report recomputed to 0 after cascade refund, "
            f"got {get_report(rep3['id'])['gross_cents']}")


def _setup_maintenance_hold_landmark(api, company_name="MaintCo",
                                     company_email="m@x.com"):
    from test_helpers import (
        reset_clock, create_company, create_theatre, create_production,
        create_booking, approve_booking, create_and_sign_license, engage_crew,
        make_company_rep_headers,
    )
    reset_clock()
    company = create_company(company_name, company_email)
    theatre = create_theatre("Palace", size_class="LARGE", is_landmark=True,
                             base_weekly_rent_cents=900000, capacity=1800)
    production = create_production(company["id"], title="Show P",
                                   required_size_class="LARGE",
                                   required_loadout_hours=48)
    rep = make_company_rep_headers(company["id"])
    # Landmark approval precondition: a SCHEDULED capital project disjoint
    # from the run within 365 days before loadin_start.
    get_success_data(api_client.create_capital_project(
        theatre["id"],
        create_capital_project_payload(
            description="Rigging overhaul",
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-20T00:00:00Z"), HM))
    booking = create_booking(production["id"], theatre["id"], company["id"],
                             loadin_start="2026-09-06T00:00:00Z",
                             run_end="2026-09-27T00:00:00Z")
    approve_booking(booking["id"])
    # Post-run maintenance window containing the load-out interval
    # (run_end 09-27 + 48h = 09-29T00:00Z, inside [09-27, 10-15)).
    cp = get_success_data(api_client.create_capital_project(
        theatre["id"],
        create_capital_project_payload(
            description="Post-run seat restoration",
            window_start="2026-09-27T00:00:00Z",
            window_end="2026-10-15T00:00:00Z"), HM))
    create_and_sign_license(booking["id"], company["id"],
                            weekly_rent_cents=900000,
                            stop_clause_weekly_floor_cents=100000)
    engage_crew(booking["id"], 14)
    set_clock(TEST_DEFAULTS["WEEK1_START"])
    set_clock("2026-09-28T00:00:00Z")
    validate_success(api_client.close_booking(booking["id"], rep))
    set_clock("2026-09-29T00:00:00Z")
    booking = get_booking(booking["id"])
    assert booking["status"] == "MAINTENANCE_HOLD", (
        f"landmark booking with load-out inside a SCHEDULED window must be "
        f"MAINTENANCE_HOLD, got {booking['status']}")
    return {"company": company, "theatre": theatre, "production": production,
            "booking": booking, "rep": rep, "project": cp}


class TestMaintenanceCompletionCascade:
    def test_complete_moves_project_to_completed(self, api):
        """PRD §3.10: "Completing a project whose window holds bookings in
        `MAINTENANCE_HOLD` releases them: the project moves to `COMPLETED`
        (cascade depth 1) and each held booking whose load-out fell inside the
        completed window moves to `DONE` (cascade depth 2)."

        Design: Difficulty/transitive_cascade/maintenance_completion_cascade_depth2
        """
        ctx = _setup_maintenance_hold_landmark(api)
        data = validate_success(api_client.complete_capital_project(
            ctx["project"]["id"], HM))
        assert data["status"] == "COMPLETED"

    def test_complete_releases_held_booking_to_done(self, api):
        """PRD §3.10: "Completing a project whose window holds bookings in
        `MAINTENANCE_HOLD` releases them: the project moves to `COMPLETED`
        (cascade depth 1) and each held booking whose load-out fell inside the
        completed window moves to `DONE` (cascade depth 2)."

        Design: Difficulty/transitive_cascade/maintenance_completion_cascade_depth2
        """
        ctx = _setup_maintenance_hold_landmark(api)
        validate_success(api_client.complete_capital_project(
            ctx["project"]["id"], HM))
        assert get_booking(ctx["booking"]["id"])["status"] == "DONE", (
            f"held booking must cascade to DONE, got "
            f"{get_booking(ctx['booking']['id'])['status']}")


def test_capital_project_in_use_error_triggerable(api):
    """PRD §3.10: "A project can be cancelled from `SCHEDULED` — moving it to
    `CANCELLED` — only when no booking in `MAINTENANCE_HOLD` depends on its
    window; cancelling one that does is rejected with
    `ERR_CAPITAL_PROJECT_IN_USE` (HTTP 409)."

    Design: Corner/errors/capital_project_in_use_error_triggerable
    """
    ctx = _setup_maintenance_hold_landmark(api, company_name="CpCo",
                                           company_email="cp@x.com")
    resp = api_client.cancel_capital_project(ctx["project"]["id"], HM)
    validate_error(resp, ApiErrorId.ERR_CAPITAL_PROJECT_IN_USE)
