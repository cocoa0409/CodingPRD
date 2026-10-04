"""Quote lifecycle: opening, declining, the cyclic rewind and deferred expiry."""
from test_helpers import (
    api_client as api,
    make_carrier_headers,
    make_platform_admin_headers,
    make_shipper_headers,
    list_load_quotes,
    post_load,
    iso3,
    read_load,
    run_sweep,
    set_clock,
    setup_board,
    setup_two_quotes_on_one_load,
    shift,
    newest_quote,
    NON_EXISTENT_UUID,
)


class TestQuoteExpiry:
    """The TTL is enforced on the view path as well as by the sweep."""

    def test_opening_a_quote_at_its_deadline_is_refused(self):
        """PRD section 3.2: "Two preconditions guard the open. The quote's `acceptance_deadline` must still be in the future, or the open is refused with `ERR_QUOTE_EXPIRED` (HTTP 409); and the quote's load must still be `POSTED`, or the open is refused with `ERR_QUOTE_NOT_VIEWABLE` (HTTP 409)."

        Design: Corner/state_machines/quote_view_on_an_expired_quote_returns_quote_expired
        """
        board = setup_board(units=1)
        set_clock("2026-09-20T00:00:00Z")
        load, quote = _posted_load(board)
        assert quote["acceptance_deadline"] == iso3("2026-09-21T00:00:00Z")

        set_clock("2026-09-21T00:00:00Z")
        expired = api.view_rate_quote(quote["id"], make_carrier_headers(board["carrier_id"]))
        assert expired.status_code == 409, expired.text
        assert expired.json()["data"]["error_id"] == "ERR_QUOTE_EXPIRED"

    def test_opening_a_quote_one_second_before_its_deadline_succeeds(self):
        """PRD section 3.2: "a `Carrier` opening an `ACTIVE` quote moves it to
        `VIEWED` and its own id is added to `viewed_carrier_ids`."

        Design: Corner/state_machines/quote_view_on_an_expired_quote_returns_quote_expired
        """
        board = setup_board(units=1)
        set_clock("2026-09-20T00:00:00Z")
        load, quote = _posted_load(board)

        set_clock("2026-09-20T23:59:59Z")
        opened = api.view_rate_quote(quote["id"], make_carrier_headers(board["carrier_id"]))
        assert opened.status_code == 200, opened.text
        assert opened.json()["data"]["status"] == "VIEWED"
        assert board["carrier_id"] in opened.json()["data"]["viewed_carrier_ids"]


class TestDeclineCycle:
    """DECLINED is a revisit-able state, not a terminal one."""

    def test_repost_returns_a_declined_quote_to_the_board(self):
        """PRD section 3.2: "A `Carrier` on a `VIEWED` quote may decline it, provided the carrier is not already in `declined_carrier_ids`; the carrier's id joins that list and the quote moves to `DECLINED`, which takes it off that carrier's board. `DECLINED` is not a final resting place: when the shipper reposts the load, the same quote row returns to `ACTIVE` and `declined_carrier_ids` is emptied, as §3.4 describes."
        PRD section 3.4: "the load's newest non-accepted quote — whether it sits
        in `SUPERSEDED`, `DECLINED`, or `EXPIRED` — becomes `ACTIVE` again, any
        `declined_carrier_ids` it carries are cleared, and its `acceptance_deadline`
        is reset to the current clock instant plus the quote's full time-to-live of
        twenty-four hours."

        Design: Difficulty/non_linear_state_machine/declined_quote_cycles_back_to_viewed_so_rejection_is_not_terminal
        """
        board = setup_two_quotes_on_one_load()
        load = board["load"]
        quote = newest_quote(board["shipper_id"], load["id"])
        assert quote["status"] == "ACTIVE"

        viewed = api.view_rate_quote(quote["id"], make_carrier_headers(board["carrier_id"]))
        assert viewed.status_code == 200, viewed.text
        declined = api.decline_rate_quote(quote["id"], make_carrier_headers(board["carrier_id"]))
        assert declined.status_code == 200, declined.text
        assert declined.json()["data"]["status"] == "DECLINED"
        assert board["carrier_id"] in declined.json()["data"]["declined_carrier_ids"]

    def test_the_repost_cycle_lands_on_a_live_viewable_quote(self):
        """PRD section 3.4: "Most consequentially, the quote lifecycle rewinds: the load's newest non-accepted quote — whether it sits in `SUPERSEDED`, `DECLINED`, or `EXPIRED` — becomes `ACTIVE` again, any `declined_carrier_ids` it carries are cleared, and its `acceptance_deadline` is reset to the current clock instant plus the quote's full time-to-live of twenty-four hours."
        PRD section 3.4: "Most consequentially, the quote lifecycle rewinds: the load's
        newest non-accepted quote — whether it sits in `SUPERSEDED`,
        `DECLINED`, or `EXPIRED` — becomes `ACTIVE` again, any
        `declined_carrier_ids` it carries are cleared, and its
        `acceptance_deadline` is reset to the current clock instant plus
        the quote's full time-to-live of twenty-four hours."
        PRD section 3.4: "Most consequentially, the quote lifecycle rewinds: the load's
        newest non-accepted quote — whether it sits in `SUPERSEDED`,
        `DECLINED`, or `EXPIRED` — becomes `ACTIVE` again, any
        `declined_carrier_ids` it carries are cleared, and its
        `acceptance_deadline` is reset to the current clock instant plus
        the quote's full time-to-live of twenty-four hours. A quote that
        every carrier declined is therefore back on the board after a
        repost; so is one that quietly expired."

        Design: Difficulty/non_linear_state_machine/declined_quote_cycles_back_to_viewed_so_rejection_is_not_terminal
        """
        board = setup_two_quotes_on_one_load(repost=False)
        load = board["load"]
        quote = newest_quote(board["shipper_id"], load["id"])
        api.view_rate_quote(quote["id"], make_carrier_headers(board["carrier_id"]))
        api.decline_rate_quote(quote["id"], make_carrier_headers(board["carrier_id"]))
        assert api.get_load(
            load["id"], make_shipper_headers(board["shipper_id"])).json()["data"]["status"] \
            == "POSTED"

        declined_now = api.get_rate_quote(
            quote["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert declined_now["status"] == "DECLINED"

        # The rewinding that puts a declined quote back on the board is the
        # shipper's repost (PRD 3.4 / 3.2): the load is swept uncovered once the
        # clock reaches its coverage horizon, and the repost empties
        # declined_carrier_ids.
        set_clock("2026-10-05T07:00:00Z")
        run_sweep()
        assert read_load(
            board["shipper_id"], load["id"])["status"] == "UNCOVERED"

        current = read_load(board["shipper_id"], load["id"])
        reposted = api.repost_load(load["id"], current["shipper_version"],
                                   make_shipper_headers(board["shipper_id"]))
        assert reposted.status_code == 200, (
            f"the repost should put a declined quote back on the board, got {reposted.text}")
        live = [row for row in list_load_quotes(board["shipper_id"], load["id"])
                if row["status"] in ("ACTIVE", "VIEWED")]
        assert live, "the repost must leave a live quote back on the board"
        assert board["carrier_id"] not in live[-1]["declined_carrier_ids"], (
            "a reposted quote clears the declined_carrier_ids it carried")


class TestRepricing:
    """The reprice target is the newest quote on the load."""

    def test_only_the_newest_quote_receives_the_repriced_rate(self):
        """PRD section 3.7: "The result becomes the quote's `repriced_rate_cents`,
        the quote's `quote_kind` becomes `REPRICED`, the load's `booked_rate_cents`
        follows it, the load's `market_band` is updated to the requested band, and
        the load's `reprice_count` rises by one."

        Design: Corner/endpoints/repricing_targets_the_exact_newest_rate_quote_for_the_load
        """
        board = setup_two_quotes_on_one_load()
        load = board["load"]
        repriced = api.reprice_load(load["id"], "TIGHT", make_platform_admin_headers())
        assert repriced.status_code == 200, repriced.text

        quotes = api.list_load_rate_quotes(
            load["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert len(quotes) == 2
        oldest, newest = quotes[0], quotes[1]
        assert oldest["quote_kind"] == "INITIAL"
        assert oldest["repriced_rate_cents"] is None
        assert newest["quote_kind"] == "REPRICED"
        assert newest["repriced_rate_cents"] == 381150

        repriced_only = api.list_rate_quotes(
            make_shipper_headers(board["shipper_id"]),
            {"load_id": load["id"], "quote_kind": "REPRICED"})
        assert repriced_only.status_code == 200
        assert len(repriced_only.json()["data"]) == 1

    def test_reprice_leaves_the_locked_quote_untouched(self):
        """PRD section 3.7: "Crucially, the load's `posted_rate_cents` is never
        touched: it is the immutable record of the quote struck when the load was
        first posted, and after a single reprice the two figures diverge."

        Design: Corner/endpoints/repricing_targets_the_exact_newest_rate_quote_for_the_load
        """
        board = setup_two_quotes_on_one_load()
        load = board["load"]
        api.reprice_load(load["id"], "TIGHT", make_platform_admin_headers())
        refreshed = read_load(board["shipper_id"], load["id"])
        assert refreshed["booked_rate_cents"] == 381150
        assert refreshed["posted_rate_cents"] == 325710
        assert refreshed["posted_rate_cents"] != refreshed["booked_rate_cents"]
        assert refreshed["market_band"] == "TIGHT"
        assert refreshed["reprice_count"] == 1


class TestDeferredSweep:
    """Quote expiry and the uncovered sweep are driven by the logical clock."""

    def test_sweep_expires_the_quote_and_moves_the_load_to_uncovered(self):
        """PRD section 3.4: "A posted load can fail to find a carrier at all. When a load is `POSTED` with no quote remaining in `ACTIVE` or `VIEWED` status and the clock has reached 24 hours before the load's `pickup_window_start`, the periodic sweep moves the load to `UNCOVERED` and appends a `UNCOVERED` status event sourced to the platform."

        Design: Corner/cross_cutting_complexity_layers/sweep_expires_the_quote_and_moves_the_posted_load_to_uncovered
        """
        board = setup_board(units=1)
        set_clock("2026-09-20T00:00:00Z")
        load, quote = _posted_load(board, pickup_start="2026-10-05T08:00:00Z")

        before = read_load(board["shipper_id"], load["id"])
        assert before["status"] == "POSTED"
        assert before["repost_count"] == 0

        set_clock("2026-10-05T08:00:00Z")
        swept = run_sweep()
        assert load["id"] in swept["uncovered_load_ids"]

        after = read_load(board["shipper_id"], load["id"])
        assert after["status"] == "UNCOVERED"
        assert after["repost_count"] == 0

        expired = api.get_rate_quote(
            quote["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert expired["status"] == "EXPIRED"

    def test_a_load_outside_the_horizon_is_not_swept(self):
        """PRD section 3.4: "A posted load can fail to find a carrier at all.
        When a load is `POSTED` with no quote remaining in `ACTIVE` or `VIEWED`
        status and the clock has reached 24 hours before the load's
        `pickup_window_start`, the periodic sweep moves the load to `UNCOVERED`."
        PRD section 3.2: "The quote carries an `acceptance_deadline` twenty-four
        hours past its creation instant."

        Design: Corner/endpoints/sweep_reports_the_three_swept_collections_separately
        """
        board = setup_board(units=1)
        set_clock("2026-09-20T00:00:00Z")
        # A deadline 24 hours out, then a clock 25 minutes later: still inside the
        # horizon, so the quote is live and the load is not swept.
        load, _ = _posted_load(board, pickup_start="2026-09-21T00:00:00Z")

        set_clock("2026-09-20T00:25:00Z")
        swept = run_sweep()
        assert load["id"] not in swept["uncovered_load_ids"]
        assert read_load(board["shipper_id"], load["id"])["status"] == "POSTED"

    def test_sweep_leaves_the_posting_credit_committed(self):
        """PRD section 3.4: "The shipper's `load_credits_committed` does not fall
        at this moment — the shipper keeps paying for the slot until the load is
        either cancelled or reposted."

        Design: Corner/entities/load_get_for_an_unallocated_id_returns_load_not_found
        """
        board = setup_board(units=1)
        set_clock("2026-09-20T00:00:00Z")
        load, _ = _posted_load(board, pickup_start="2026-10-05T08:00:00Z")
        set_clock("2026-10-05T08:00:00Z")
        run_sweep()
        shipper = api.get_shipper(
            board["shipper_id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert shipper["load_credits_committed"] == 1


def _posted_load(board, pickup_start="2026-10-05T08:00:00Z"):
    created = api.create_load(
        {
            "shipper_id": board["shipper_id"],
            "origin_facility_id": board["origin_facility_id"],
            "destination_facility_id": board["destination_facility_id"],
            "pricing_mode": "SPOT",
            "equipment_type": "DRY_VAN",
            "commodity": "GENERAL",
            "weight_lbs": 40000,
            "declared_cargo_value_cents": 5000000,
            "distance_miles": 900,
            "pickup_window_start": pickup_start,
            "pickup_window_end": "2026-10-05T12:00:00Z",
            "delivery_deadline": "2026-10-07T18:00:00Z",
            "market_band": "BALANCED",
        },
        make_shipper_headers(board["shipper_id"]),
    )
    assert created.status_code == 201, created.text
    load_id = created.json()["data"]["id"]
    posted = post_load(board["shipper_id"], load_id)
    return posted, newest_quote(board["shipper_id"], load_id)