"""Auction lifecycle: open gating, offer headroom, seal-time caps, withdrawal,
mitigation gate, clearing effects, and terminal lockdown (PRD §3.3, §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_and_approve_resource,
    create_and_open_run,
    create_auction_run_payload,
    create_owner,
    get_review_for_offer,
    get_success_data,
    make_resource_owner_headers,
    seal_run,
    setup_cleared_year_single_resource,
    setup_forecast_locked_year,
    setup_delivery_year_with_forecast,
    setup_delivery_year_with_zone,
    submit_offer,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["market_admin_headers"]
OPS = TEST_USERS["settlement_ops_headers"]


class TestOpenGating:
    def test_open_rejected_while_delivery_year_draft(self, api):
        """PRD §3.3: "Opening a run — `DRAFT` → `OPEN` — requires the delivery
        year to be `FORECAST_LOCKED` and no other run of the same delivery year
        to be in `OPEN` or `SEALED`"

        Design: Difficulty/cross_entity_state_dependency/auction_open_requires_delivery_year_forecast_locked
        """
        dy, zone = setup_delivery_year_with_zone()
        run = get_success_data(
            api.create_auction_run(create_auction_run_payload(dy["id"]), ADMIN)
        )
        resp = api.open_auction_run(run["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        run_after = get_success_data(api.get_auction_run(run["id"], ADMIN))
        assert run_after["status"] == "DRAFT"

    def test_open_succeeds_after_forecast_lock(self, api):
        """PRD §3.3: "the open transition itself flips the delivery year to
        `AUCTION_OPEN` and increments the run's `version`."

        Design: Difficulty/cross_entity_state_dependency/auction_open_requires_delivery_year_forecast_locked
        """
        dy, zone, forecast = setup_forecast_locked_year()
        run = create_and_open_run(dy["id"])
        assert run["status"] == "OPEN"
        dy_after = get_success_data(api.get_delivery_year(dy["id"], ADMIN))
        assert dy_after["status"] == "AUCTION_OPEN"


class TestOfferHeadroom:
    def test_offer_beyond_accredited_ucap_rejected(self, api):
        """PRD §3.3: "`offer_mw` may not exceed the resource's
        `accredited_ucap_mw` minus the megawatts this same resource has already
        offered into the same run in `SUBMITTED` or `SEALED` status, or the
        submission is rejected with `ERR_OFFER_EXCEEDS_UCAP`."

        Design: Corner/validations/err_offer_exceeds_ucap_on_create
        """
        dy, zone, forecast = setup_forecast_locked_year()
        owner = create_owner()
        resource, _ = create_and_approve_resource(owner["id"], zone["id"], dy["id"])
        run = create_and_open_run(dy["id"])
        headers = make_resource_owner_headers(owner["id"])
        resp = api.create_offer(
            {
                "resource_id": resource["id"],
                "auction_run_id": run["id"],
                "offer_mw": 86.0,
                "offer_price_per_mw_day": 70.0,
            },
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_EXCEEDS_UCAP, expected_status=422)
        offers = get_success_data(
            api.list_offers(ADMIN, params={"resource_id": resource["id"]})
        )
        assert offers == [], "A rejected offer must not persist"


class TestSellerOfferCap:
    def _sealed_offer_for_credit(self, api, credit_score):
        dy, zone, forecast = setup_forecast_locked_year()
        owner = create_owner(legal_name=f"Owner-{credit_score}",
                             contact_email=f"o{credit_score}@x.com",
                             credit_score=credit_score)
        resource, _ = create_and_approve_resource(owner["id"], zone["id"], dy["id"])
        run = create_and_open_run(dy["id"])
        offer = submit_offer(resource["id"], owner["id"], run["id"],
                             offer_mw=10.0, offer_price_per_mw_day=200.0)
        seal_run(run["id"])
        return get_success_data(api.get_offer(offer["id"], ADMIN))

    def test_mid_band_credit_cap(self, api):
        """PRD §3.4: "The cap is the greater of two screens — one tenth of the
        net cost of new entry, and the owner's avoidable cost rate, defined as
        60.00 dollars per MW-day plus 0.10 dollars for every point the owner's
        `credit_score` falls below 1000 — and the result is then capped at the
        net cost of new entry itself, 390.00 dollars per MW-day, with the final
        cap rounded to 2 decimal places round half up."

        Design: Difficulty/combinatorial_formula/offer_cap_nonlinear_max_min_band
        """
        # credit 900 -> ACR = 60 + 0.10*(100) = 70.00 -> cap = min(max(39, 70), 390)
        offer = self._sealed_offer_for_credit(api, 900)
        assert offer["status"] == "SEALED"
        assert offer["mitigated_cap_per_mw_day"] == pytest.approx(70.0, abs=1e-9)

    def test_zero_credit_cap_clamps_inside_band(self, api):
        """PRD §3.4: "The cap is the greater of two screens — one tenth of the
        net cost of new entry, and the owner's avoidable cost rate, defined as
        60.00 dollars per MW-day plus 0.10 dollars for every point the owner's
        `credit_score` falls below 1000 — and the result is then capped at the
        net cost of new entry itself, 390.00 dollars per MW-day, with the final
        cap rounded to 2 decimal places round half up."

        Design: Difficulty/combinatorial_formula/offer_cap_nonlinear_max_min_band
        """
        # credit 0 -> ACR = 60 + 0.10*1000 = 160.00 -> cap = min(max(39, 160), 390)
        offer = self._sealed_offer_for_credit(api, 0)
        assert offer["status"] == "SEALED"
        assert offer["mitigated_cap_per_mw_day"] == pytest.approx(160.0, abs=1e-9)


class TestWithdrawalState:
    def test_withdraw_of_sealed_offer_rejected_invalid_state(self, api):
        """PRD §2.6: "State legality — the requested transition must exist from
        the target resource's current state; failure yields
        `ERR_INVALID_STATE`." PRD §3.3: "An owner may withdraw a `SUBMITTED`
        offer while its run is still `OPEN`."

        Design: Corner/state_machines/offer_withdraw_from_sealed_returns_invalid_state
        """
        dy, zone, forecast = setup_forecast_locked_year()
        owner = create_owner()
        resource, _ = create_and_approve_resource(owner["id"], zone["id"], dy["id"])
        run = create_and_open_run(dy["id"])
        offer = submit_offer(resource["id"], owner["id"], run["id"],
                             offer_mw=10.0, offer_price_per_mw_day=70.0)
        seal_run(run["id"])
        run_now = get_success_data(api.get_auction_run(run["id"], ADMIN))
        resp = api.withdraw_offer(
            offer["id"], run_now["version"],
            make_resource_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        offer_after = get_success_data(api.get_offer(offer["id"], ADMIN))
        assert offer_after["status"] == "SEALED"


class TestMitigationGate:
    def test_clear_blocked_while_review_pending(self, api):
        """PRD §3.4: "while any review for any offer in the run remains
        `PENDING`, the clear is rejected with `ERR_MITIGATION_PENDING`."

        Design: Corner/validations/err_mitigation_pending_blocks_clear
        """
        dy, zone, forecast = setup_forecast_locked_year()
        owner = create_owner(credit_score=900)
        resource, _ = create_and_approve_resource(owner["id"], zone["id"], dy["id"])
        run = create_and_open_run(dy["id"])
        # Offer priced at 200.00, above the 70.00 cap for credit 900, so the
        # auto-created review stays PENDING.
        offer = submit_offer(resource["id"], owner["id"], run["id"],
                             offer_mw=10.0, offer_price_per_mw_day=200.0)
        seal_run(run["id"])
        review = get_review_for_offer(offer["id"])
        assert review["outcome"] == "PENDING"
        resp = api.clear_auction_run(run["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_MITIGATION_PENDING, expected_status=409)
        run_after = get_success_data(api.get_auction_run(run["id"], ADMIN))
        assert run_after["status"] == "SEALED"
        zone_after = get_success_data(api.get_zone(zone["id"], ADMIN))
        assert zone_after["clearing_price_per_mw_day"] is None


class TestClearingImmediateConsistency:
    def test_clear_effects_visible_immediately(self, api):
        """PRD §3.4: "For every offer with a positive `cleared_mw`, a
        **CapacityCommitment** is created in `ACTIVE` status with
        `committed_mw` equal to the cleared quantity and
        `clearing_price_per_mw_day` taken from the resource's zone. The run
        stamps `cleared_at`, moves `SEALED` → `CLEARED`, and the delivery year
        advances `AUCTION_OPEN` → `CLEARED`, each with its `version` increment."

        Design: Corner/consistency_model/immediate_consistency_clear_effects_visible_in_response_chain
        """
        dy, zone, forecast = setup_forecast_locked_year()
        owner = create_owner()
        resource, _ = create_and_approve_resource(owner["id"], zone["id"], dy["id"])
        run = create_and_open_run(dy["id"])
        offer = submit_offer(resource["id"], owner["id"], run["id"],
                             offer_mw=10.0, offer_price_per_mw_day=70.0)
        seal_run(run["id"])
        from test_helpers import resolve_review_pass
        resolve_review_pass(offer["id"])
        cleared = validate_success(api.clear_auction_run(run["id"], ADMIN))
        assert cleared["status"] == "CLEARED"
        assert cleared["cleared_at"] is not None

        dy_after = get_success_data(api.get_delivery_year(dy["id"], ADMIN))
        assert dy_after["status"] == "CLEARED"
        zone_after = get_success_data(api.get_zone(zone["id"], ADMIN))
        assert zone_after["clearing_price_per_mw_day"] == pytest.approx(70.0, abs=1e-9)
        assert zone_after["cleared_mw"] == pytest.approx(10.0, abs=1e-9)
        offer_after = get_success_data(api.get_offer(offer["id"], ADMIN))
        assert offer_after["status"] == "CLEARED"
        assert offer_after["cleared_mw"] == pytest.approx(10.0, abs=1e-9)
        commitments = get_success_data(
            api.list_commitments(ADMIN, params={"resource_id": resource["id"]})
        )
        assert len(commitments) == 1
        assert commitments[0]["status"] == "ACTIVE"
        assert commitments[0]["committed_mw"] == pytest.approx(10.0, abs=1e-9)


class TestCommitmentsFiltered:
    def test_commitments_filtered_by_resource(self, api):
        """PRD §3.4: "For every offer with a positive `cleared_mw`, a
        **CapacityCommitment** is created in `ACTIVE` status with
        `committed_mw` equal to the cleared quantity and
        `clearing_price_per_mw_day` taken from the resource's zone."
        PRD §3.5: "Its `daily_revenue_dollars` is the `committed_mw` times its
        locked `clearing_price_per_mw_day`, rounded to 2 decimal places round
        half up"

        Design: Corner/endpoints/commitments_filtered_by_resource
        """
        dy, zone, forecast = setup_forecast_locked_year()
        owner = create_owner()
        r1, _ = create_and_approve_resource(owner["id"], zone["id"], dy["id"])
        r2, _ = create_and_approve_resource(owner["id"], zone["id"], dy["id"])
        run = create_and_open_run(dy["id"])
        off1 = submit_offer(r1["id"], owner["id"], run["id"],
                            offer_mw=6.0, offer_price_per_mw_day=70.0)
        off2 = submit_offer(r2["id"], owner["id"], run["id"],
                            offer_mw=6.0, offer_price_per_mw_day=70.0)
        seal_run(run["id"])
        from test_helpers import resolve_review_pass
        resolve_review_pass(off1["id"])
        resolve_review_pass(off2["id"])
        validate_success(api.clear_auction_run(run["id"], ADMIN))

        commitments = get_success_data(
            api.list_commitments(ADMIN, params={"resource_id": r1["id"]})
        )
        assert len(commitments) == 1
        assert commitments[0]["resource_id"] == r1["id"]
        assert commitments[0]["committed_mw"] == pytest.approx(6.0, abs=1e-9)
        assert commitments[0]["daily_revenue_dollars"] == pytest.approx(420.0, abs=1e-9)


class TestTerminalLockdown:
    def test_lock_forecast_on_closed_year_rejected(self, api):
        """PRD §3.1: "Locking the forecast is the pivotal act of setup. It is
        permitted only while the delivery year is in `DRAFT`" PRD §2.6:
        "State legality — the requested transition must exist from the target
        resource's current state; failure yields `ERR_INVALID_STATE`."

        Design: Corner/state_machines/terminal_state_lockdown_closed_delivery_year
        """
        ctx = setup_cleared_year_single_resource()
        get_success_data(api.settle_delivery_year(ctx["dy"]["id"], OPS))
        closed = get_success_data(api.close_delivery_year(ctx["dy"]["id"], OPS))
        assert closed["status"] == "CLOSED"
        resp = api.lock_forecast(ctx["dy"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        dy_after = get_success_data(api.get_delivery_year(ctx["dy"]["id"], ADMIN))
        assert dy_after["status"] == "CLOSED"


class TestRetirement:
    def test_retire_withdraws_submitted_offer(self, api):
        """PRD §3.2: "An accredited resource may later be retired by its owner,
        moving `ACCREDITED` → `RETIRED`, provided no commitment for the
        resource is in `ACTIVE` or `REPLACEMENT_PENDING`. Retirement sweeps any
        of the resource's still-`SUBMITTED` offers into `WITHDRAWN`"

        Design: Corner/state_machines/resource_retire_cascades_withdraw_submitted_offers
        """
        dy, zone, forecast = setup_forecast_locked_year()
        owner = create_owner()
        resource, _ = create_and_approve_resource(owner["id"], zone["id"], dy["id"])
        run = create_and_open_run(dy["id"])
        offer = submit_offer(resource["id"], owner["id"], run["id"],
                             offer_mw=10.0, offer_price_per_mw_day=70.0)
        retired = validate_success(
            api.retire_resource(resource["id"], make_resource_owner_headers(owner["id"]))
        )
        assert retired["status"] == "RETIRED"
        offer_after = get_success_data(api.get_offer(offer["id"], ADMIN))
        assert offer_after["status"] == "WITHDRAWN"
