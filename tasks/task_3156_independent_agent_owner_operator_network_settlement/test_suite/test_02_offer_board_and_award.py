"""The internal load board: offer posting, the ranking selector policy, the
award edge and its guards."""
from test_helpers import (
    ApiErrorId,
    enroll_agent,
    enroll_capacity_owner,
    get_load_version,
    get_success_data,
    post_offer,
    promote_load,
    register_customer,
    setup_two_loads_one_bco,
    setup_qualified_bco,
    set_logical_clock,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBoardRanking:
    """The selector policy that decides which offer may be accepted."""

    def test_board_ranks_pay_ties_by_offered_at_then_created_at(self, api):
        """PRD §2.4: "The ranking key is the offer's `offered_pay_cents` in
        descending order, then its `offered_at` ascending, then its `created_at`
        ascending."
        PRD §2.4: "Reading a load's board returns the offers under the same
        selector policy the ranks encode — `selected_rank` ascending".

        Design: Corner/cross_cutting_complexity_layers/board_ranks_pay_ties_by_offered_at_then_created_at
        """
        set_logical_clock()
        agent = enroll_agent()
        customer = register_customer(agent)
        load = promote_load(agent, customer["customer_ref"])
        first = setup_qualified_bco()["bco"]
        second = setup_qualified_bco()["bco"]

        offer_early = post_offer(agent, load, first, 126000, "2026-09-01T01:00:00Z")
        offer_late = post_offer(agent, load, second, 126000, "2026-09-01T02:00:00Z")

        assert offer_early["offered_pay_cents"] == 126000
        assert offer_late["offered_pay_cents"] == 126000
        assert offer_early["selected_rank"] == 1
        assert offer_late["selected_rank"] == 2

        board, _meta = validate_paginated(
            api.get_board(TEST_USERS["network_admin_headers"], params={"load_id": load["id"]})
        )
        assert [row["id"] for row in board][0] == offer_early["id"], (
            "the tie is broken by offered_at ascending"
        )

        # The later-offered tie is refused, the earlier one is admissible.
        refused = api.accept_load_offer(
            offer_late["id"], {"accepted_at": "2026-09-01T03:00:00Z"},
            TEST_USERS["capacity_owner_headers"],
        )
        validate_error(refused, ApiErrorId.ERR_OFFER_NOT_TOP_RANKED)

        accepted = validate_success(
            api.accept_load_offer(
                offer_early["id"], {"accepted_at": "2026-09-01T03:00:00Z"},
                _headers_for(first),
            ), 200
        )
        assert accepted["status"] == "ACCEPTED"

    def test_accept_second_ranked_offer_is_rejected(self, api):
        """PRD §3.5: "that the offer be the top-ranked open offer on its load by
        `selected_rank` (else `ERR_OFFER_NOT_TOP_RANKED`)".
        PRD §3.5: "at depth one every other open offer on that load becomes
        `DECLINED` with its rank re-derived to null".

        Design: Corner/state_machines/accept_second_ranked_offer_is_rejected
        """
        set_logical_clock()
        agent = enroll_agent()
        customer = register_customer(agent)
        load = promote_load(agent, customer["customer_ref"])
        bco = setup_qualified_bco()["bco"]

        offer_low = post_offer(agent, load, bco, 120000, "2026-09-01T01:00:00Z")
        offer_high = post_offer(agent, load, bco, 126000, "2026-09-01T02:00:00Z")

        board, _meta = validate_paginated(
            api.get_board(TEST_USERS["network_admin_headers"], params={"load_id": load["id"]})
        )
        assert [row["id"] for row in board] == [offer_high["id"], offer_low["id"]], (
            "126000 beats 120000 under the descending-pay ranking key"
        )
        # PRD §2.4 pins `selected_rank` to the board's selector policy, which is
        # state re-derived on read — not the rank reported by the POST that
        # created an offer (offer_low was rank 1 at its own creation instant).
        assert [row["selected_rank"] for row in board] == [1, 2]

        refused = api.accept_load_offer(
            offer_low["id"], {"accepted_at": "2026-09-01T03:00:00Z"}, _headers_for(bco)
        )
        validate_error(refused, ApiErrorId.ERR_OFFER_NOT_TOP_RANKED)

        accepted = validate_success(
            api.accept_load_offer(
                offer_high["id"], {"accepted_at": "2026-09-01T04:00:00Z"}, _headers_for(bco)
            ), 200
        )
        assert accepted["status"] == "ACCEPTED"
        low_after = get_success_data(api.get_load_offer(offer_low["id"], TEST_USERS["network_admin_headers"]))
        assert low_after["status"] == "DECLINED"


class TestSingleCommitment:
    """A truck can only be in one place."""

    def test_bco_single_commitment_window_adjacency(self, api):
        """PRD §3.5: "that no other load already in `AWARDED`, `COVERED`, or
        `IN_TRANSIT` points its `awarded_capacity_owner_id` at this same owner,
        since a truck can only be in one place (else `ERR_CAPACITY_OWNER_BUSY`)".

        Design: Difficulty/resource_temporal_overlap/bco_single_commitment_window_adjacency
        """
        state = setup_two_loads_one_bco()
        agent, bco = state["agent"], state["bco"]

        validate_success(
            api.accept_load_offer(
                state["offer_a"]["id"], {"accepted_at": "2026-09-01T02:00:00Z"}, _headers_for(bco)
            ), 200
        )

        refused = api.accept_load_offer(
            state["offer_b"]["id"], {"accepted_at": "2026-09-01T02:30:00Z"}, _headers_for(bco)
        )
        validate_error(refused, ApiErrorId.ERR_CAPACITY_OWNER_BUSY)

    def test_blocked_award_leaves_the_second_load_and_offer_untouched(self, api):
        """PRD §3.5: "the load's `awarded_capacity_owner_id` is set to the
        accepting owner, the load becomes `AWARDED`".
        PRD §2.4: "Ranks are re-derived for every remaining open offer whenever
        the set of open offers changes".

        Design: Difficulty/resource_temporal_overlap/bco_single_commitment_window_adjacency
        """
        state = setup_two_loads_one_bco()
        bco = state["bco"]

        validate_success(
            api.accept_load_offer(
                state["offer_a"]["id"], {"accepted_at": "2026-09-01T02:00:00Z"}, _headers_for(bco)
            ), 200
        )
        api.accept_load_offer(
            state["offer_b"]["id"], {"accepted_at": "2026-09-01T02:30:00Z"}, _headers_for(bco)
        )

        load_a = get_success_data(api.get_load(state["load_a"]["id"], TEST_USERS["network_admin_headers"]))
        load_b = get_success_data(api.get_load(state["load_b"]["id"], TEST_USERS["network_admin_headers"]))
        assert load_a["status"] == "AWARDED"
        assert load_b["status"] == "POSTED"

        held, meta = validate_paginated(
            api.list_loads(TEST_USERS["network_admin_headers"],
                           params={"awarded_capacity_owner_id": bco["id"]})
        )
        assert meta["total_count"] == 1 and len(held) == 1

        offer_b = get_success_data(api.get_load_offer(state["offer_b"]["id"], TEST_USERS["network_admin_headers"]))
        assert offer_b["status"] == "OPEN", "the blocked award left the offer for a future attempt"


class TestEmptyBoard:
    """The selector policy's empty-pool case."""

    def test_empty_board_reports_no_ranked_offer(self, api):
        """PRD §2.4: "A load may only be awarded while it is genuinely on the
        board. Each load carries a read-only `board_required` flag, true when the
        promoting agent's `status` is `ACTIVE` and that agent's `settlement_hold`
        is false, and false otherwise."
        PRD §3.6: "requires the load to be `DELIVERED` or `SETTLED` (else
        `ERR_LOAD_NOT_SETTLEABLE`)".

        Design: Difficulty/boundary_precision_check/empty_board_no_top_ranked_offer
        """
        set_logical_clock()
        agent = enroll_agent()
        customer = register_customer(agent)
        load = promote_load(agent, customer["customer_ref"])

        board, meta = validate_paginated(
            api.list_load_board_offers(load["id"], TEST_USERS["network_admin_headers"])
        )
        assert board == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False

        load_now = get_success_data(api.get_load(load["id"], TEST_USERS["network_admin_headers"]))
        assert load_now["board_required"] is True

    def test_empty_board_load_has_no_settlement_path(self, api):
        """PRD §3.6: "where the load-side preconditions are evaluated, requires
        the load to be `DELIVERED` or `SETTLED` (else `ERR_LOAD_NOT_SETTLEABLE`)".

        Design: Difficulty/boundary_precision_check/empty_board_no_top_ranked_offer
        """
        set_logical_clock()
        agent = enroll_agent()
        customer = register_customer(agent)
        load = promote_load(agent, customer["customer_ref"])

        refused = api.evaluate_load_settlement(
            load["id"], {"settlement_method": "PROVISIONAL"}, TEST_USERS["settlement_operator_headers"]
        )
        validate_error(refused, ApiErrorId.ERR_LOAD_NOT_SETTLEABLE)

        load_now = get_success_data(api.get_load(load["id"], TEST_USERS["network_admin_headers"]))
        assert load_now["status"] == "POSTED"


class TestOfferConcurrency:
    """The version guard on the parent load."""

    def test_offer_create_with_stale_load_version_is_rejected(self, api):
        """PRD §2.8: "Posting an offer requires `expected_network_load_version`,
        carrying the client's last observed version of the parent `Load`. A
        mismatch is rejected with `ERR_STALE_VERSION`."
        PRD §3.4: "an offer whose `expected_network_load_version` no longer
        matches the load's version is refused with `ERR_STALE_VERSION`."

        Design: Corner/cross_cutting_complexity_layers/offer_create_with_stale_load_version_is_rejected
        """
        set_logical_clock()
        agent = enroll_agent()
        customer = register_customer(agent)
        load = promote_load(agent, customer["customer_ref"])
        bco = enroll_capacity_owner()

        stale_version = get_load_version(load["id"])
        post_offer(agent, load, bco, 120000, "2026-09-01T01:00:00Z")  # advances load.version

        refused = api.create_load_offer(
            {
                "load_id": load["id"],
                "capacity_owner_id": bco["id"],
                "offered_pay_cents": 126000,
                "offered_at": "2026-09-01T02:00:00Z",
                "expected_network_load_version": stale_version,
            },
            _agent_headers(agent),
        )
        validate_error(refused, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_freshly_read_load_version_accepts_the_offer(self, api):
        """PRD §2.8: "it holds the version of the parent entity that the caller
        last observed. If the supplied value does not equal the parent entity's
        current `version`, the request is rejected with `ERR_STALE_VERSION`."

        Design: Corner/cross_cutting_complexity_layers/offer_create_with_stale_load_version_is_rejected
        """
        set_logical_clock()
        agent = enroll_agent()
        customer = register_customer(agent)
        load = promote_load(agent, customer["customer_ref"])
        bco = enroll_capacity_owner()

        stale_version = get_load_version(load["id"])
        post_offer(agent, load, bco, 120000, "2026-09-01T01:00:00Z")
        load_v_now = get_load_version(load["id"])
        assert load_v_now != stale_version, "the board write advanced the load's version"

        accepted_offer = validate_success(
            api.create_load_offer(
                {
                    "load_id": load["id"],
                    "capacity_owner_id": bco["id"],
                    "offered_pay_cents": 126000,
                    "offered_at": "2026-09-01T03:00:00Z",
                    "expected_network_load_version": load_v_now,
                },
                _agent_headers(agent),
            ), 201
        )
        assert accepted_offer["status"] == "OPEN"

        rows, meta = validate_paginated(
            api.list_load_board_offers(load["id"], TEST_USERS["network_admin_headers"])
        )
        assert meta["total_count"] == 2, "the rejected stale create wrote nothing"


def _agent_headers(agent):
    from test_helpers import make_freight_agent_headers
    return make_freight_agent_headers(agent["id"])


def _headers_for(bco):
    from test_helpers import make_capacity_owner_headers
    return make_capacity_owner_headers(bco["id"])