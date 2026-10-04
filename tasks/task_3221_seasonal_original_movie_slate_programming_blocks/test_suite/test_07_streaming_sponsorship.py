"""Streaming windows and sponsorship reconciliation."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    set_clock, make_studio, make_season, make_locked_season, make_title, approve_title,
    make_location, book_slot, make_published_block, make_air_slot, make_sponsorship,
    make_streaming_window, setup_locked_season_with_approved_title,
    setup_delivered_title, setup_archived_season_with_premieres,
)
from test_helpers.fixtures import ADMIN, PLANNER, PROD, EXEC, ADS, STREAM


class TestStreamingOpenRequiresAiredPremiere:
    def test_open_before_any_aired_premiere_rejected(self, api):
        """PRD §3.7: "for `OWN_STREAMER` windows only, at least one `AIRED` air
        slot of kind `PREMIERE` must already exist for the title — the network's
        own service never streams a title before its broadcast premiere —
        otherwise `ERR_STREAMING_BEFORE_PREMIERE`."

        Design: Difficulty/cross_entity_state_dependency/streaming_open_requires_aired_premiere
        """
        ctx = setup_delivered_title()
        block, bv = make_published_block(ctx["season"]["id"])
        make_air_slot(block["id"], ctx["title"]["id"], "2027-11-05T00:00:00Z", "PREMIERE", bv)
        win = make_streaming_window(ctx["season"]["id"], ctx["title"]["id"],
                                    platform="OWN_STREAMER",
                                    window_start="2027-11-06T00:00:00Z",
                                    window_end="2027-12-06T00:00:00Z")
        set_clock("2027-11-06T12:00:00Z")
        resp = api_client.open_streaming_window(win["id"], STREAM)
        validate_error(resp, ApiErrorId.ERR_STREAMING_BEFORE_PREMIERE)

    def test_open_after_premiere_aired_succeeds(self, api):
        """PRD §3.7: "A successful open moves the window `SCHEDULED → OPEN`." and
        PRD §3.5: "when the slot's `kind` is `PREMIERE`, the season's
        `premiered_title_count` is recomputed".

        Design: Difficulty/cross_entity_state_dependency/streaming_open_requires_aired_premiere
        """
        ctx = setup_delivered_title()
        block, bv = make_published_block(ctx["season"]["id"])
        air = make_air_slot(block["id"], ctx["title"]["id"], "2027-11-05T00:00:00Z",
                            "PREMIERE", bv)
        win = make_streaming_window(ctx["season"]["id"], ctx["title"]["id"],
                                    platform="OWN_STREAMER",
                                    window_start="2027-11-06T00:00:00Z",
                                    window_end="2027-12-06T00:00:00Z")
        set_clock("2027-11-06T12:00:00Z")
        validate_success(api_client.mark_air_slot_aired(air["id"], EXEC))
        opened = validate_success(api_client.open_streaming_window(win["id"], STREAM))
        assert opened["status"] == "OPEN"
        season_after = get_success_data(api_client.get_season(ctx["season"]["id"], ADMIN))
        assert season_after["premiered_title_count"] == 1


class TestStreamingOpenUndeliveredTitle:
    def test_open_for_approved_title_rejected_invalid_state(self, api):
        """PRD §3.7: "The title must be `DELIVERED` — otherwise
        `ERR_INVALID_STATE`."

        Design: Corner/errors/streaming_open_undelivered_title_returns_invalid_state
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        win = make_streaming_window(ctx["season"]["id"], ctx["title"]["id"],
                                    platform="OWN_STREAMER",
                                    window_start="2027-11-06T00:00:00Z",
                                    window_end="2027-12-06T00:00:00Z")
        set_clock("2027-11-07T00:00:00Z")
        resp = api_client.open_streaming_window(win["id"], STREAM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        win_after = get_success_data(api_client.get_streaming_window(win["id"], STREAM))
        assert win_after["status"] == "SCHEDULED"


class TestSponsorshipComputedRead:
    def test_booked_sponsorship_projection_and_null_actual(self, api):
        """PRD §3.6: "Booking immediately computes and stores
        `projected_cost_cents` and leaves `actual_cost_cents` unset; the
        sponsorship starts `BOOKED`." and "If there is no intersection, the
        projection is simply the base with no multiplier."

        Design: Corner/endpoints/sponsorship_computed_read_projection_then_actual
        """
        studio = make_studio(ad_budget_cents=500000)
        season = make_season(
            studio["id"], label="Winter Warmup",
            air_window_start="2027-02-01T00:00:00Z",
            air_window_end="2027-03-01T00:00:00Z",
            delivery_deadline="2027-01-01T00:00:00Z")
        spon = make_sponsorship(season["id"], advertiser="CardsCo",
                                season_cpm_cents=2000, viewership_thousands=8)
        assert spon["projected_cost_cents"] == 16000
        assert spon["actual_cost_cents"] is None
        assert spon["status"] == "BOOKED"


class TestSponsorshipReconcileGate:
    def test_reconcile_before_archive_rejected_no_debit(self, api):
        """PRD §3.6: "reconciling a sponsorship requires the owning season to be
        `ARCHIVED`, and any attempt earlier — including against a season still
        `LOCKED` — is rejected with `ERR_SEASON_NOT_LOCKED`."

        Design: Corner/errors/sponsorship_reconcile_before_archive_returns_season_not_locked
        """
        studio = make_studio(ad_budget_cents=100000)
        season, sv = make_locked_season(studio["id"])
        spon = make_sponsorship(season["id"], advertiser="CardsCo",
                                season_cpm_cents=1000, viewership_thousands=5)
        resp = api_client.reconcile_sponsorship(spon["id"], ADS)
        validate_error(resp, ApiErrorId.ERR_SEASON_NOT_LOCKED)
        spon_after = get_success_data(api_client.get_sponsorship(spon["id"], ADS))
        assert spon_after["status"] == "BOOKED"
        assert spon_after["actual_cost_cents"] is None
        studio_after = get_success_data(api_client.get_studio(studio["id"], ADMIN))
        assert studio_after["ad_budget_cents"] == 100000


class TestAdBudgetReconcileConservation:
    def test_failed_reconcile_conserves_budget_and_state(self, api):
        """PRD §3.6: "if subtracting the `actual_cost_cents` would drive the budget
        below zero, the reconciliation is rejected with `ERR_AD_BUDGET_EXCEEDED`
        (HTTP 402) and the sponsorship stays `BOOKED`".

        Design: Difficulty/compensating_invariant/ad_budget_reconcile_conservation
        """
        ctx = setup_archived_season_with_premieres(1, ad_budget_cents=30000)
        s_big = make_sponsorship(ctx["season"]["id"], advertiser="BigBrand",
                                 season_cpm_cents=2000, viewership_thousands=20)
        resp = api_client.reconcile_sponsorship(s_big["id"], ADS)
        validate_error(resp, ApiErrorId.ERR_AD_BUDGET_EXCEEDED)
        studio_after = get_success_data(api_client.get_studio(ctx["studio"]["id"], ADMIN))
        assert studio_after["ad_budget_cents"] == 30000
        spon_after = get_success_data(api_client.get_sponsorship(s_big["id"], ADS))
        assert spon_after["status"] == "BOOKED"

    def test_successful_reconcile_debits_exact_actual_cost(self, api):
        """PRD §3.6: "otherwise the budget is debited by the actual cost and the
        sponsorship moves `BOOKED → RECONCILED`" and "The `actual_cost_cents` is
        therefore the `season_cpm_cents` multiplied by that premiere-weighted
        viewership total".

        Design: Difficulty/compensating_invariant/ad_budget_reconcile_conservation
        """
        ctx = setup_archived_season_with_premieres(1, ad_budget_cents=30000)
        s_small = make_sponsorship(ctx["season"]["id"], advertiser="SmallBrand",
                                   season_cpm_cents=1000, viewership_thousands=10)
        reconciled = validate_success(api_client.reconcile_sponsorship(s_small["id"], ADS))
        assert reconciled["status"] == "RECONCILED"
        # actual = 1000 * (10 + 1 premiere) == 11000
        assert reconciled["actual_cost_cents"] == 11000
        studio_after = get_success_data(api_client.get_studio(ctx["studio"]["id"], ADMIN))
        assert studio_after["ad_budget_cents"] == 30000 - 11000
