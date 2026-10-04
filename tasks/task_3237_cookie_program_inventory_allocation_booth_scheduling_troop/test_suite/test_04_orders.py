"""Troop order lifecycle: case-pack, windows, gates, cascades, conservation."""
from test_helpers import (
    ApiErrorId,
    add_product,
    assert_cookie_order,
    create_active_recall,
    create_and_confirm_order,
    create_and_submit_order,
    create_order_with_lines,
    create_season,
    create_troop,
    create_troop_with_account,
    get_account,
    get_order,
    get_season,
    make_council_admin_headers,
    make_troop_leader_headers,
    open_season,
    set_clock,
    setup_open_season_with_supply,
    validate_error,
    validate_success,
)


class TestOrderLineCasePack:
    def test_case_pack_violation_on_order_line(self, api):
        """PRD §3.2: "Lines are added to a draft order one at a time, each
        recorded with its owning `order_id` and carrying a `product_id` and a
        `package_qty` that must be a positive multiple of that product's
        `packages_per_case` — requesting eleven packages of a twelve-per-case
        variety fails with `ERR_CASE_PACK_VIOLATION`."

        Design: Corner/entities/case_pack_violation_on_order_line
        """
        admin = make_council_admin_headers()
        season = create_season(admin=admin)
        product = add_product(season["id"], admin=admin, packages_per_case=12)
        open_season(season["id"], admin=admin)
        troop = create_troop(admin=admin)
        leader = make_troop_leader_headers(troop["id"])
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        order = create_order_with_lines(season["id"], troop, [], leader=leader)
        resp = api.add_order_line(
            season["id"], order["id"],
            {"product_id": product["id"], "package_qty": 13}, leader,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_PACK_VIOLATION, 422)


class TestOrderSubmitGates:
    def test_initial_order_outside_window_rejected(self, api):
        """PRD §3.2: "an `INITIAL` order submits only while the logical clock
        is inside the ordering window — on or after `ordering_opens_at` and on
        or before `ordering_closes_at`, both boundaries inclusive — and a
        submission outside that window fails with `ERR_ORDER_WINDOW_CLOSED`."
        PRD §2.9: "At server startup the logical clock reads exactly
        2026-09-01T00:00:00Z, and until it is explicitly set it continues to
        read that default."

        Design: Corner/state_machines/initial_order_outside_window_rejected
        """
        admin = make_council_admin_headers()
        season = create_season(admin=admin)
        product = add_product(season["id"], admin=admin)
        open_season(season["id"], admin=admin)
        troop = create_troop(admin=admin)
        leader = make_troop_leader_headers(troop["id"])
        # Clock untouched: still at the 2026-09-01 default, before the window.
        order = create_order_with_lines(
            season["id"], troop, [(product["id"], 10)], leader=leader
        )
        resp = api.submit_order(season["id"], order["id"], leader)
        validate_error(resp, ApiErrorId.ERR_ORDER_WINDOW_CLOSED, 422)

    def test_replenishment_order_rejected_before_selling(self, api):
        """PRD §3.2: "The season must be accepting: an `INITIAL` order submits
        only while the season is `OPEN` or `SELLING`, while a `REPLENISHMENT`
        order submits only while the season is `SELLING`, with violations
        rejected as `ERR_SEASON_NOT_ACCEPTING`."

        Design: Corner/state_machines/replenishment_order_rejected_before_selling
        """
        admin = make_council_admin_headers()
        ctx = setup_open_season_with_supply(100, admin=admin)
        season, product = ctx["season"], ctx["product"]
        troop, account, leader = create_troop_with_account(season["id"], admin=admin)
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        order = create_order_with_lines(
            season["id"], troop, [(product["id"], 10)], kind="REPLENISHMENT", leader=leader
        )
        resp = api.submit_order(season["id"], order["id"], leader)
        validate_error(resp, ApiErrorId.ERR_SEASON_NOT_ACCEPTING, 422)

    def test_order_submit_empty_lines_zero_count_edge(self, api):
        """PRD §3.2: "The order must be `DRAFT`, or `ERR_ORDER_INVALID_STATE`
        results; it must hold at least one line, or `ERR_ORDER_EMPTY`
        results"."

        Design: Difficulty/boundary_precision_check/order_submit_empty_lines_zero_count_edge
        """
        admin = make_council_admin_headers()
        season = create_season(admin=admin)
        add_product(season["id"], admin=admin)
        open_season(season["id"], admin=admin)
        troop, account, leader = create_troop_with_account(season["id"], admin=admin)
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        order = create_order_with_lines(season["id"], troop, [], leader=leader)
        resp = api.submit_order(season["id"], order["id"], leader)
        validate_error(resp, ApiErrorId.ERR_ORDER_EMPTY, 422)
        unchanged = get_order(order["id"], admin=admin)
        assert unchanged["status"] == "DRAFT"


class TestOrderConfirmCascade:
    def test_order_confirm_three_hop_cascade(self, api):
        """PRD §3.2: "Confirmation swaps the order's units out of
        `pending_commit_units` and into `initial_commit_units`, pins the
        order's `total_amount_cents` from the products' current prices at that
        moment, posts that amount as a charge against the troop account's
        `balance_cents`, and accrues per-package proceeds into the account's
        `proceeds_accrued_cents`". PRD §3.3: "The gate itself is inclusive: an
        attainment of at least 80.00 percent opens selling."

        Design: Difficulty/transitive_cascade/order_confirm_three_hop_cascade
        """
        admin = make_council_admin_headers()
        ctx = setup_open_season_with_supply(100, admin=admin)
        season, product = ctx["season"], ctx["product"]
        troop, account, leader = create_troop_with_account(season["id"], admin=admin)
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        submitted = create_and_submit_order(
            season["id"], troop, [(product["id"], 80)], leader=leader
        )
        confirmed = validate_success(
            api.confirm_order(season["id"], submitted["id"], admin)
        )
        assert_cookie_order(confirmed)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["total_amount_cents"] == 48000
        acct = get_account(account["id"], admin=admin)
        assert acct["balance_cents"] == 48000
        assert acct["proceeds_accrued_cents"] == 8000
        read = get_season(season["id"], admin=admin)
        assert read["initial_commit_units"] == 80
        assert read["pending_commit_units"] == 0
        assert read["remaining_units"] == 20
        assert read["forecast_attainment_pct"] == 80.00
        # Hop 3: attainment reached the gate and the clock is past opens, so
        # the season auto-flipped OPEN -> SELLING.
        assert read["status"] == "SELLING"

    def test_confirm_recall_safety_beats_allocation_constraint(self, api):
        """PRD §2.10: "Only after those four come the business rules, in this
        relative order: recall safety (`ERR_RECALLED_PRODUCT`) before
        referential ownership (`ERR_FORBIDDEN_OWNERSHIP`), before segregation
        of duties (`ERR_SOD_SAME_TROOP`), before booth conflicts
        (`ERR_BOOTH_CONFLICT`), before season and clock acceptance gates
        (`ERR_SEASON_NOT_ACCEPTING`), before the case-pack constraint
        (`ERR_CASE_PACK_VIOLATION`), before supply and capacity checks
        (`ERR_SUPPLY_INSUFFICIENT`), before fiscal guards
        (`ERR_FISCAL_VIOLATION`), and finally optimistic-concurrency staleness
        (`ERR_STALE_VERSION`) last.""

        Design: Difficulty/priority_pair_validation_conflict/confirm_recall_safety_beats_allocation_constraint
        """
        admin = make_council_admin_headers()
        ctx = setup_open_season_with_supply(50, admin=admin)
        season, product = ctx["season"], ctx["product"]
        troop, account, leader = create_troop_with_account(season["id"], admin=admin)
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        submitted = create_and_submit_order(
            season["id"], troop, [(product["id"], 60)], leader=leader
        )
        create_active_recall(
            season["id"], product["id"], admin=admin,
            effective_at="2027-01-05T00:00:00Z",
        )
        resp = api.confirm_order(season["id"], submitted["id"], admin)
        validate_error(resp, ApiErrorId.ERR_RECALLED_PRODUCT, 422)
        unchanged = get_order(submitted["id"], admin=admin)
        assert unchanged["status"] == "SUBMITTED"

    def test_supply_insufficient_on_confirm(self, api):
        """PRD §3.2: "the allocation gate: the season's `remaining_units` must
        be at least the order's `total_units`, else `ERR_SUPPLY_INSUFFICIENT`."

        Design: Corner/validations/supply_insufficient_on_confirm
        """
        admin = make_council_admin_headers()
        ctx = setup_open_season_with_supply(50, admin=admin)
        season, product = ctx["season"], ctx["product"]
        troop, account, leader = create_troop_with_account(season["id"], admin=admin)
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        submitted = create_and_submit_order(
            season["id"], troop, [(product["id"], 60)], leader=leader
        )
        resp = api.confirm_order(season["id"], submitted["id"], admin)
        validate_error(resp, ApiErrorId.ERR_SUPPLY_INSUFFICIENT, 422)
        unchanged = get_order(submitted["id"], admin=admin)
        assert unchanged["status"] == "SUBMITTED"

    def test_error_already_terminal_second_confirm(self, api):
        """PRD §2.4: "A state transition attempted on a resource that is not in
        a state from which that transition exists is rejected with the
        domain-specific state error where one exists
        (`ERR_SEASON_INVALID_STATE`, `ERR_ORDER_INVALID_STATE`,
        `ERR_TRANSFER_INVALID_STATE`, `ERR_REQUEST_INVALID_STATE`,
        `ERR_PAYMENT_INVALID_STATE`, `ERR_FULFILLMENT_INVALID_STATE`,
        `ERR_PO_INVALID_STATE`, `ERR_RECALL_INVALID_STATE`,
        `ERR_AGREEMENT_INVALID_STATE`), or with the generic
        `ERR_INVALID_STATE` (HTTP 409) where none applies."

        Design: Corner/errors/error_already_terminal_second_confirm
        """
        admin = make_council_admin_headers()
        ctx = setup_open_season_with_supply(200, admin=admin)
        season, product = ctx["season"], ctx["product"]
        troop, account, leader = create_troop_with_account(season["id"], admin=admin)
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        order = create_and_confirm_order(
            season["id"], troop, [(product["id"], 80)], leader=leader, admin=admin
        )
        resp = api.confirm_order(season["id"], order["id"], admin)
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE, 409)
        acct = get_account(account["id"], admin=admin)
        assert acct["balance_cents"] == 48000


class TestOrderRejectConservation:
    def test_season_commitment_conservation_submit_reject(self, api):
        """PRD §3.2: "A successful submission moves the order to `SUBMITTED`,
        adds its `total_units` to the season's `pending_commit_units`,
        recomputes `remaining_units`, and advances the season's `version`."
        PRD §3.2: "Rejection instead moves the order to `REJECTED`, releases
        the pending commitment back into `remaining_units`, and records the
        supplied `reason` into the order's `rejection_reason`."

        Design: Difficulty/compensating_invariant/season_commitment_conservation_submit_reject
        """
        admin = make_council_admin_headers()
        ctx = setup_open_season_with_supply(200, admin=admin)
        season, product = ctx["season"], ctx["product"]
        before = get_season(season["id"], admin=admin)
        troop, account, leader = create_troop_with_account(season["id"], admin=admin)
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        submitted = create_and_submit_order(
            season["id"], troop, [(product["id"], 50)], leader=leader
        )
        rejected = validate_success(
            api.reject_order(season["id"], submitted["id"], {"reason": "duplicate"}, admin)
        )
        assert rejected["status"] == "REJECTED"
        after = get_season(season["id"], admin=admin)
        assert after["pending_commit_units"] == 0
        assert after["initial_commit_units"] == 0
        assert after["remaining_units"] == before["remaining_units"] == 200
