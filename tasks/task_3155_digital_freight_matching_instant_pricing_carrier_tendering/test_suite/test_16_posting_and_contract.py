"""Posting preconditions: the posting credit and the lane-contract gate."""
from test_helpers import (
    api_client as api,
    activate_lane_contract,
    create_facility,
    create_lane_contract,
    make_carrier_headers,
    make_platform_admin_headers,
    make_shipper_headers,
    post_load,
    set_clock,
    setup_board,
)


def _load_payload(board, **overrides):
    payload = {
        "shipper_id": board["shipper_id"],
        "origin_facility_id": board["origin_facility_id"],
        "destination_facility_id": board["destination_facility_id"],
        "pricing_mode": "CONTRACT",
        "equipment_type": "DRY_VAN",
        "commodity": "GENERAL",
        "weight_lbs": 40000,
        "declared_cargo_value_cents": 5000000,
        "distance_miles": 1200,
        "pickup_window_start": "2026-10-05T08:00:00Z",
        "pickup_window_end": "2026-10-05T12:00:00Z",
        "delivery_deadline": "2026-10-07T18:00:00Z",
        "market_band": "BALANCED",
    }
    payload.update(overrides)
    return payload


def _make_load(board, **overrides):
    return api.create_load(
        _load_payload(board, **overrides), make_shipper_headers(board["shipper_id"]))


def _contract(board, **overrides):
    contract = create_lane_contract(
        board["shipper_id"], board["origin_facility_id"], board["destination_facility_id"],
        **overrides)
    activate_lane_contract(board["shipper_id"], contract["id"])
    refreshed = api.get_lane_contract(
        contract["id"], make_shipper_headers(board["shipper_id"]))
    assert refreshed.status_code == 200, refreshed.text
    return refreshed.json()["data"]


class TestContractGate:
    """A CONTRACT load must cite an ACTIVE contract whose term is open."""

    def test_a_draft_contract_cannot_be_drawn_against(self):
        """PRD section 3.4: "if the load is `CONTRACT`, the named contract must be
        `ACTIVE` and its term must currently be open: its `start_date` must be at or
        before the logical clock, and the clock must be strictly before its
        `end_date`."

        Design: Corner/calculations/high_value_commodity_takes_the_250_million_liability_cap_not_the_100_million_default
        """
        board = setup_board(units=1)
        set_clock("2026-09-20T00:00:00Z")
        draft_contract = create_lane_contract(
            board["shipper_id"], board["origin_facility_id"], board["destination_facility_id"])
        assert draft_contract["status"] == "DRAFT"

        created = _make_load(board, lane_contract_id=draft_contract["id"])
        assert created.status_code == 201, created.text
        load = created.json()["data"]
        refused = api.post_load(load["id"], make_shipper_headers(board["shipper_id"]))
        assert refused.status_code == 409, refused.text
        assert refused.json()["data"]["error_id"] == "ERR_CONTRACT_NOT_ACTIVE"
        assert api.get_load(
            load["id"], make_shipper_headers(board["shipper_id"])).json()["data"]["status"] \
            == "DRAFT"

    def test_a_term_that_has_passed_cannot_be_drawn_against(self):
        """PRD section 3.4: "A contract that is still `DRAFT`, one that has
        `EXPIRED`, or one whose dates do not cover the present instant produces
        `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409)."

        Design: Corner/calculations/high_value_commodity_takes_the_250_million_liability_cap_not_the_100_million_default
        """
        board = setup_board(units=1)
        set_clock("2026-09-20T00:00:00Z")
        contract = _contract(board, start_date="2026-09-01T00:00:00Z",
                             end_date="2026-09-30T00:00:00Z")
        assert contract["status"] == "ACTIVE"
        created = _make_load(board, lane_contract_id=contract["id"])
        assert created.status_code == 201, created.text
        load = created.json()["data"]

        set_clock("2026-11-01T00:00:00Z")
        refused = api.post_load(load["id"], make_shipper_headers(board["shipper_id"]))
        assert refused.status_code == 409, refused.text
        assert refused.json()["data"]["error_id"] == "ERR_CONTRACT_NOT_ACTIVE"

    def test_a_term_that_has_not_started_cannot_be_drawn_against(self):
        """PRD section 3.4: "its `start_date` must be at or before the logical
        clock, and the clock must be strictly before its `end_date`."

        Design: Corner/calculations/high_value_commodity_takes_the_250_million_liability_cap_not_the_100_million_default
        """
        board = setup_board(units=1)
        set_clock("2026-09-20T00:00:00Z")
        contract = _contract(board, start_date="2026-11-01T00:00:00Z",
                             end_date="2026-12-31T00:00:00Z")
        created = _make_load(board, lane_contract_id=contract["id"])
        assert created.status_code == 201, created.text
        load = created.json()["data"]

        set_clock("2026-10-05T00:00:00Z")
        refused = api.post_load(load["id"], make_shipper_headers(board["shipper_id"]))
        assert refused.status_code == 409, refused.text
        assert refused.json()["data"]["error_id"] == "ERR_CONTRACT_NOT_ACTIVE"

    def test_an_active_contract_in_term_prices_the_flat_committed_rate(self):
        """PRD section 3.3: "When the load's `pricing_mode` is `CONTRACT` and it
        names a valid `lane_contract_id`, the load's `base_rate_cents` is the
        referenced contract's `committed_rate_cents`, again subject to the same
        50,000-cent floor."

        Design: Difficulty/dual_variant_calc/quote_price_spot_vs_contract_on_identical_lane
        """
        board = setup_board(units=1)
        set_clock("2026-09-20T00:00:00Z")
        contract = _contract(board, committed_rate_cents=215000,
                             start_date="2026-09-01T00:00:00Z",
                             end_date="2026-12-31T00:00:00Z")
        created = _make_load(board, lane_contract_id=contract["id"])
        assert created.status_code == 201, created.text
        load = created.json()["data"]
        data = post_load(board["shipper_id"], load["id"])
        assert data["posted_rate_cents"] == 215000
        assert data["booked_rate_cents"] == 215000
        assert data["pricing_mode"] == "CONTRACT"

        quote = api.list_load_rate_quotes(
            data["id"], make_shipper_headers(board["shipper_id"])).json()["data"][0]
        assert quote["base_rate_cents"] == 215000
        assert quote["min_rate_cents"] == 182750


class TestContractDrawAccounting:
    """A contract draw is counted only for loads still on the contract."""

    def test_a_draw_is_counted_against_the_contract_period(self):
        """PRD section 3.7: "Where the load was on a contract, the booking's
        `contract_lane_draw` is set and the contract's `loads_committed_this_period`
        is brought up to date — that count is the number of that contract's loads,
        restricted to those in `BOOKED`, `IN_TRANSIT`, `DELIVERED`, `INVOICED`, or
        `PAID` status, created within the half-open window running from Monday
        00:00:00Z of the ISO week containing the most recent draw up to, but not
        including, seven days later."

        Design: Difficulty/dual_variant_calc/quote_price_spot_vs_contract_on_identical_lane
        """
        board = setup_board(units=1)
        set_clock("2026-09-20T00:00:00Z")
        contract = _contract(board, committed_rate_cents=215000)
        created = _make_load(board, lane_contract_id=contract["id"])
        assert created.status_code == 201, created.text
        load = created.json()["data"]
        posted = post_load(board["shipper_id"], load["id"])
        quote = api.list_load_rate_quotes(
            load["id"], make_shipper_headers(board["shipper_id"])).json()["data"][-1]

        booked = api.create_booking(
            {"load_id": load["id"], "carrier_id": board["carrier_id"],
             "rate_quote_id": quote["id"], "equipment_id": board["equipment"][0]["id"],
             "expected_load_version": posted["version"]},
            make_carrier_headers(board["carrier_id"]))
        assert booked.status_code == 201, booked.text
        assert booked.json()["data"]["contract_lane_draw"] is True

        refreshed = api.get_lane_contract(
            contract["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert refreshed["loads_committed_this_period"] == 1
        assert refreshed["period_start"] is not None

    def test_a_cancelled_load_falls_out_of_the_count(self):
        """PRD section 3.7: "Where the load was on a contract, the booking's `contract_lane_draw` is set and the contract's `loads_committed_this_period` is brought up to date — that count is the number of that contract's loads, restricted to those in `BOOKED`, `IN_TRANSIT`, `DELIVERED`, `INVOICED`, or `PAID` status, created within the half-open window running from Monday 00:00:00Z of the ISO week containing the most recent draw up to, but not including, seven days later. CANCELLED, VOIDED, UNCOVERED, and DRAFT loads are excluded from that count, and the contract's `period_start` records the Monday that the count is measured from."

        Design: Corner/calculations/lane_index_is_a_pure_function_of_the_two_state_codes
        """
        board = setup_board(units=1)
        set_clock("2026-09-20T00:00:00Z")
        contract = _contract(board, committed_rate_cents=215000)
        created = _make_load(board, lane_contract_id=contract["id"])
        assert created.status_code == 201, created.text
        load = created.json()["data"]
        posted = post_load(board["shipper_id"], load["id"])
        quote = api.list_load_rate_quotes(
            load["id"], make_shipper_headers(board["shipper_id"])).json()["data"][-1]
        api.create_booking(
            {"load_id": load["id"], "carrier_id": board["carrier_id"],
             "rate_quote_id": quote["id"], "equipment_id": board["equipment"][0]["id"],
             "expected_load_version": posted["version"]},
            make_carrier_headers(board["carrier_id"]))

        cancelled = api.cancel_load(load["id"], make_shipper_headers(board["shipper_id"]))
        assert cancelled.status_code == 200, cancelled.text
        refreshed = api.get_lane_contract(
            contract["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert refreshed["loads_committed_this_period"] == 0


class TestRepostLimit:
    """The repost guard is measured before the increment."""

    def test_the_third_repost_succeeds_and_the_fourth_is_refused(self):
        """PRD section 3.4: "a load whose `repost_count` has already reached 3
        cannot be reposted again, and the attempt is refused with
        `ERR_REPOST_LIMIT_REACHED` (HTTP 409).  The guard is measured before the
        increment, so the third repost — taking the count from 2 to 3 — succeeds
        and only the fourth is refused."

        Design: Difficulty/non_linear_state_machine/declined_quote_cycles_back_to_viewed_so_rejection_is_not_terminal
        """
        board = setup_board(units=1)
        set_clock("2026-09-20T00:00:00Z")
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
                "pickup_window_start": "2026-10-05T08:00:00Z",
                "pickup_window_end": "2026-10-05T12:00:00Z",
                "delivery_deadline": "2026-10-07T18:00:00Z",
                "market_band": "BALANCED",
            },
            make_shipper_headers(board["shipper_id"]),
        ).json()["data"]
        post_load(board["shipper_id"], created["id"])
        headers = make_shipper_headers(board["shipper_id"])

        for expected_count in (1, 2, 3):
            set_clock(f"2026-10-{3 + expected_count:02d}T08:00:00Z")
            api.run_sweep(make_platform_admin_headers())
            current = api.get_load(created["id"], headers).json()["data"]
            assert current["status"] == "UNCOVERED", f"setup failed at repost {expected_count}"
            reposted = api.repost_load(created["id"], current["shipper_version"], headers)
            assert reposted.status_code == 200, (
                f"repost {expected_count} should succeed, got {reposted.text}")
            assert reposted.json()["data"]["repost_count"] == expected_count

        set_clock("2026-10-07T08:00:00Z")
        api.run_sweep(make_platform_admin_headers())
        current = api.get_load(created["id"], headers).json()["data"]
        assert current["repost_count"] == 3
        refused = api.repost_load(created["id"], current["shipper_version"], headers)
        assert refused.status_code == 409, refused.text
        assert refused.json()["data"]["error_id"] == "ERR_REPOST_LIMIT_REACHED"