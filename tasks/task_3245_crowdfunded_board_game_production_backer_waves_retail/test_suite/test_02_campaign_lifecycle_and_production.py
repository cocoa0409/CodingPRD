"""Campaign lifecycle transitions, quote gates, and run-lock MOQ."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    charge_pledge,
    close_campaign_via_clock,
    create_campaign,
    create_charged_pledge,
    create_final_quote,
    create_pledge,
    create_quote,
    create_run,
    get_campaign,
    launch_campaign,
    set_clock,
    setup_closed_success_campaign,
    setup_live_campaign,
    submit_quote,
    validate_error,
    validate_success,
)

OWNER = TEST_USERS["campaign_owner_headers"]
FACTORY = TEST_USERS["factory_coordinator_headers"]


class TestCampaignLaunch:
    def test_campaign_launch_valid_transition(self, api):
        """PRD §3.1: "Launch moves the campaign `DRAFT → LIVE`."
        PRD §3.1: "Each of these transitions increments the campaign's
        `version`."

        Design: Corner/state_machines/campaign_launch_valid_transition
        """
        set_clock("2026-09-01T00:00:00Z")
        campaign = create_campaign()
        v0 = campaign["version"]
        resp = api.transition_campaign(campaign["id"], {"action": "launch"}, OWNER)
        data = validate_success(resp)
        assert data["status"] == "LIVE"
        assert data["version"] == v0 + 1

    def test_campaign_double_launch_returns_invalid_state(self, api):
        """PRD §3.1: "Launch requires the campaign still be in `DRAFT`
        (otherwise `ERR_INVALID_STATE`)".

        Design: Corner/state_machines/campaign_double_launch_returns_invalid_state
        """
        campaign = setup_live_campaign()
        resp = api.transition_campaign(campaign["id"], {"action": "launch"}, OWNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_campaign_terminal_cancelled_lockdown(self, api):
        """PRD §3.1: "`COMPLETE` and `CANCELLED` are terminal."

        Design: Corner/state_machines/campaign_terminal_cancelled_lockdown
        """
        set_clock("2026-09-01T00:00:00Z")
        campaign = create_campaign()
        resp = api.transition_campaign(campaign["id"], {"action": "cancel"}, OWNER)
        data = validate_success(resp)
        assert data["status"] == "CANCELLED"
        resp = api.transition_campaign(campaign["id"], {"action": "launch"}, OWNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_err_no_pledge_level_at_launch(self, api):
        """PRD §3.1: "Launch requires the campaign still be in `DRAFT`
        (otherwise `ERR_INVALID_STATE`), that at least one embedded pledge
        level is `OPEN` (otherwise `ERR_NO_PLEDGE_LEVEL`)".

        Design: Corner/errors/err_no_pledge_level_at_launch
        """
        set_clock("2026-09-01T00:00:00Z")
        campaign = create_campaign(pledge_levels=[])
        resp = api.transition_campaign(campaign["id"], {"action": "launch"}, OWNER)
        validate_error(resp, ApiErrorId.ERR_NO_PLEDGE_LEVEL)


class TestQuoteLifecycle:
    def test_quote_revise_cycle(self, api):
        """PRD §3.4: "may revise `SUBMITTED → PROVISIONAL` provided no
        production run referencing the quote has reached `LOCKED` or beyond —
        revision recomputes the provisional figures".

        Design: Corner/state_machines/quote_revise_cycle
        """
        campaign = setup_closed_success_campaign()
        quote = create_quote(campaign["id"])
        submit_quote(quote["id"])
        resp = api.transition_manufacturing_quote(
            quote["id"], {"action": "revise"}, FACTORY
        )
        data = validate_success(resp)
        assert data["status"] == "PROVISIONAL"

    def test_run_lock_gated_on_quote_final(self, api):
        """PRD §3.4: "Locking a run — `QUOTED → LOCKED`, by a
        `FactoryCoordinator` — requires the referenced quote to be `FINAL`
        (otherwise `ERR_QUOTE_NOT_FINAL`)".

        Design: Difficulty/cross_entity_state_dependency/run_lock_gated_on_quote_final
        """
        campaign = setup_closed_success_campaign()
        quote = create_quote(campaign["id"])
        submit_quote(quote["id"])
        run = create_run(campaign["id"], quote["id"])
        resp = api.transition_production_run(run["id"], {"action": "lock"}, FACTORY)
        validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_FINAL)

    def test_run_lock_succeeds_when_quote_final(self, api):
        """PRD §3.4: "Locking a run — `QUOTED → LOCKED`, by a
        `FactoryCoordinator` — requires the referenced quote to be `FINAL`
        (otherwise `ERR_QUOTE_NOT_FINAL`) and the quote's `final_units` to be
        at least the MOQ, the first tier's `min_units`".
        PRD §3.4: "At lock, `planned_units` is pinned to the quote's
        `final_units`".

        Design: Difficulty/cross_entity_state_dependency/run_lock_gated_on_quote_final
        """
        campaign = setup_closed_success_campaign()
        quote = create_final_quote(campaign["id"])
        run = create_run(campaign["id"], quote["id"])
        resp = api.transition_production_run(run["id"], {"action": "lock"}, FACTORY)
        data = validate_success(resp)
        assert data["status"] == "LOCKED"
        assert data["planned_units"] == quote["final_units"]

    def test_err_moq_not_met_at_run_lock(self, api):
        """PRD §3.4: "the quote's `final_units` to be at least the MOQ, the
        first tier's `min_units` (otherwise `ERR_MOQ_NOT_MET`, HTTP 422)".

        Design: Corner/errors/err_moq_not_met_at_run_lock
        """
        campaign = setup_closed_success_campaign()
        quote = create_quote(
            campaign["id"],
            tier_breaks=[{"min_units": 100, "unit_price_cents": 5000}],
        )
        submit_quote(quote["id"])
        resp = api.transition_manufacturing_quote(
            quote["id"], {"action": "finalize"}, FACTORY
        )
        validate_success(resp)
        run = create_run(campaign["id"], quote["id"])
        resp = api.transition_production_run(run["id"], {"action": "lock"}, FACTORY)
        validate_error(resp, ApiErrorId.ERR_MOQ_NOT_MET)


class TestSpareAllocation:
    def test_spare_units_allocation_floor_division(self, api):
        """PRD §3.4: "the run's spare pool is initialized: for each of the
        four regions, `spare_units_by_region` receives five percent of
        `planned_units` divided by four, rounded down to whole units".

        Design: Corner/calculations/spare_units_allocation_floor_division
        """
        set_clock("2026-09-01T00:00:00Z")
        campaign = create_campaign(
            goal_cents=1,
            closes_at="2026-09-05T00:00:00Z",
            pledge_levels=[
                {
                    "name": "L",
                    "price_cents": 100,
                    "contents": ["b"],
                    "quantity_cap": None,
                    "late_pledge_premium_pct": 0.0,
                    "status": "OPEN",
                }
            ],
        )
        launch_campaign(campaign["id"])
        pledge = create_pledge(campaign["id"], backer_user_id="b1", backer_email="b1@x")
        charge_pledge(pledge["id"])
        close_campaign_via_clock(campaign["id"], close_utc="2026-09-06T00:00:00Z")
        quote = create_final_quote(
            campaign["id"], tier_breaks=[{"min_units": 1, "unit_price_cents": 1}]
        )
        run = create_run(campaign["id"], quote["id"])
        resp = api.transition_production_run(run["id"], {"action": "lock"}, FACTORY)
        data = validate_success(resp)
        assert data["planned_units"] == 1
        assert data["spare_units_by_region"] == {"NA": 0, "EU": 0, "APAC": 0, "ROW": 0}
