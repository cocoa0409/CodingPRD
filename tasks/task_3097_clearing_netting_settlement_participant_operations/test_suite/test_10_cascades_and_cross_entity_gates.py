"""Cross-entity state gates, cascade hops and list-filter coverage."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    set_clock, create_active_participant, create_security, create_window,
    submit_trade, lock_in, net_window, create_fund, recompute_fund,
    fund_net_position,
    setup_two_active_members, setup_security_and_window,
    locked_in_matched_trade, net_position_of, member, read_action,
    book_fresh_long_on_a_new_cycle, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RISK = TEST_USERS["risk_officer_headers"]


# ─── TradeSubmission depends on SettlementWindow ──────

def test_lock_in_is_refused_once_the_window_has_been_netted():
    """PRD §3.3: "A settlement window must exist for the trade's security and
    settlement date and must itself still be `OPEN`."

    Design: Difficulty/cross_entity_state_dependency/trade_lockin_requires_open_window_state
    """
    set_clock()
    xa = create_active_participant("Cross Alpha", "LEI-XA")
    xb = create_active_participant("Cross Beta", "LEI-XB")
    security = create_security("XPA1", "912828XM1", 5000)
    window = create_window(security["id"])

    trade = submit_trade(security["id"], xb["id"], xa["id"], "BUY", 100, 4200)
    net_window(window["id"])

    # The window pair no longer permits lock-in. PRD §3.3 names
    # ERR_WINDOW_NOT_FOUND for a window that is not still OPEN, while PRD §3.4
    # names ERR_WINDOW_ALREADY_NETTED for an attempt after the window has left
    # OPEN; the document does not state which of the two pre-empts the other,
    # so either reading is faithful here.
    validate_error_is_one_of(
        api_client.lock_in_trade(trade["id"], member(xa["id"])),
        ["ERR_WINDOW_NOT_FOUND", "ERR_WINDOW_ALREADY_NETTED"])

    still = validate_success(api_client.get_trade_submission(trade["id"], ADMIN), 200)
    assert still["lock_status"] == "OPEN"


def test_lock_in_is_refused_when_no_window_exists_for_the_trade_date():
    """PRD §2.11: "A trade whose designated settlement window does not exist for
    its (`security_id`, `settlement_date`) is reported as `ERR_WINDOW_NOT_FOUND`
    (HTTP 404)."

    Design: Difficulty/cross_entity_state_dependency/trade_lockin_requires_open_window_state
    """
    set_clock()
    xa = create_active_participant("NoWin Alpha", "LEI-NW1")
    xb = create_active_participant("NoWin Beta", "LEI-NW2")
    security = create_security("NWN1", "912828XM3", 5000)
    # A window exists only for 2026-09-11; the trade settles on 2026-09-10.
    create_window(security["id"], settlement_date="2026-09-11",
                  trade_entry_deadline="2026-09-10T20:00:00Z",
                  affirmation_deadline="2026-09-10T22:00:00Z")

    trade = submit_trade(security["id"], xb["id"], xa["id"], "BUY", 10, 4000)
    validate_error(api_client.lock_in_trade(trade["id"], member(xa["id"])),
                   "ERR_WINDOW_NOT_FOUND", expected_status=404)
    assert validate_success(
        api_client.get_trade_submission(trade["id"], ADMIN), 200
    )["lock_status"] == "OPEN"


# ─── Suspension cascade hops and the failed-position settle gate ───

def test_suspension_cascade_fails_the_position_and_recomputes_its_mark():
    """PRD §3.1: "Every net position belonging to the member that is not already
    `FAILED` is marked `FAILED`".
    PRD §3.7: "The mark is refreshed by the daily sweep, by a funding call made in
    `mark_to_market_only` mode, at settlement, and at the close of a cycle".

    Design: Difficulty/transitive_cascade/participant_suspension_four_hop_cascade
    """
    set_clock()
    sa = create_active_participant("Suspend Alpha", "LEI-SA")
    sb = create_active_participant("Suspend Beta", "LEI-SB")
    security = create_security("SUS1", "912828XK9", 5000)
    window = create_window(security["id"])

    locked_in_matched_trade(security["id"], sa, sb, "BUY", 10, 4000)
    net_window(window["id"])

    before = net_position_of(sa["id"], window["id"])
    assert before["dvp_status"] != "FAILED"

    suspended = validate_success(api_client.suspend_participant(sa["id"], ADMIN), 200)
    assert suspended["membership_status"] == "SUSPENDED"

    after = net_position_of(sa["id"], window["id"])
    assert after["dvp_status"] == "FAILED"
    assert after["failed_at"] is not None
    assert after["failed_at_price_cents"] == security["prev_settlement_price_cents"]


def test_window_with_a_failed_position_of_an_active_member_cannot_settle():
    """PRD §3.6: "And no net position of the window may be `FAILED` for a
    participant whose `membership_status` is `ACTIVE` at the current logical
    clock, or the attempt fails with `ERR_WINDOW_HAS_ACTIVE_FAILS`."
    PRD §3.1: "Reinstatement, performed by a `PlatformAdmin`, returns a
    `SUSPENDED` member to `ACTIVE`."

    Design: Difficulty/transitive_cascade/participant_suspension_four_hop_cascade
    """
    set_clock()
    sa = create_active_participant("Suspend Alpha", "LEI-SA")
    sb = create_active_participant("Suspend Beta", "LEI-SB")
    security = create_security("SUS1", "912828XK9", 5000)
    window = create_window(security["id"])

    locked_in_matched_trade(security["id"], sa, sb, "BUY", 10, 4000)
    net_window(window["id"])
    validate_success(api_client.suspend_participant(sa["id"], ADMIN), 200)

    reinstated = validate_success(api_client.reinstate_participant(sa["id"], ADMIN), 200)
    assert reinstated["membership_status"] == "ACTIVE"

    failed = net_position_of(sa["id"], window["id"])
    assert failed["dvp_status"] == "FAILED"

    # Fund every obligation, so the only remaining gate is the active fail.
    for participant in (sa, sb):
        row = net_position_of(participant["id"], window["id"])
        if row["settlement_obligation_cents"] > 0:
            fund_net_position(row["id"], participant["id"],
                              row["settlement_obligation_cents"])

    validate_error(api_client.settle_window(window["id"], ADMIN),
                   "ERR_WINDOW_HAS_ACTIVE_FAILS")

    # The window stays NETTED: the active-fail gate blocked settlement.
    still = validate_success(api_client.get_settlement_window(window["id"], ADMIN), 200)
    assert still["status"] == "NETTED"

    # Once the fail belongs to a member that is no longer ACTIVE, settlement is
    # no longer blocked by the active-fail gate.
    validate_success(api_client.suspend_participant(sa["id"], ADMIN), 200)
    settled = validate_success(api_client.settle_window(window["id"], ADMIN), 200)
    assert settled["status"] == "SETTLED"


# ─── Empty net-position set, second angle ─────────────

def test_window_stays_netted_with_no_rows_when_every_included_trade_is_gone():
    """PRD §3.5: "Trades that are `ALLEGED` are excluded from the calculation but
    retained for comparison."
    PRD §3.6: "The window must own at least one net position row, or the attempt
    fails with `ERR_EMPTY_NET_POSITION_SET`."

    Design: Difficulty/boundary_precision_check/zero_net_position_set_boundary_on_empty_window
    """
    set_clock()
    ea = create_active_participant("Empty Alpha", "LEI-EA")
    eb = create_active_participant("Empty Beta", "LEI-EB")
    security = create_security("EMP2", "912828XL7", 5000)
    window = create_window(security["id"])

    # The comparison is resolved while both members are still ACTIVE, then EB
    # is suspended: EB's own row is cancelled and EA's contra is swept to the
    # comparison status the suspension cascade assigns, so EA's own book holds
    # no settled row and the window nets to nothing.
    contra_ea = submit_trade(security["id"], ea["id"], eb["id"], "BUY", 10, 4000)
    trade = submit_trade(security["id"], eb["id"], ea["id"], "SELL", 10, 4000)
    lock_in(trade["id"], eb["id"])
    validate_success(api_client.suspend_participant(eb["id"], ADMIN), 200)

    netted = net_window(window["id"])
    assert netted["status"] == "NETTED"

    rows = validate_success(
        api_client.list_net_positions(ADMIN, params={"window_id": window["id"]}), 200)
    assert rows == []

    # EB's contra survives at a suspended-comparison status rather than settling.
    contra_after = validate_success(
        api_client.get_trade_submission(contra_ea["id"], ADMIN), 200)
    assert contra_after["match_status"] in ("ALLEGED", "UNRESOLVED", "UNMATCHED")


# ─── Corporate-action effective-date gate, second angle ───

def test_effective_date_guard_leaves_the_windows_children_untouched():
    """PRD §3.8: "Its `effective_date` must fall on or before the settlement date
    of the net position rows it would service, or the attempt fails with
    `ERR_ACTION_NOT_EFFECTIVE`."

    Design: Difficulty/cross_entity_state_dependency/corporate_action_apply_requires_window_effective_date
    """
    set_clock()
    ya = create_active_participant("Yield Alpha", "LEI-YA")
    yb = create_active_participant("Yield Beta", "LEI-YB")
    security = create_security("YLD2", "912828XM4", 5000)
    window = create_window(security["id"])

    locked_in_matched_trade(security["id"], ya, yb, "BUY", 100, 4000)
    net_window(window["id"])
    position_before = net_position_of(ya["id"], window["id"])
    assert position_before["net_quantity"] == 100

    action = validate_success(api_client.create_corporate_action(
        {"security_id": security["id"], "action_type": "SPLIT",
         "ratio_numerator": 3, "ratio_denominator": 2,
         "effective_date": "2026-09-20"}, ADMIN), 201)

    validate_error(api_client.apply_corporate_action(action["id"], ADMIN),
                   "ERR_ACTION_NOT_EFFECTIVE")

    position_after = net_position_of(ya["id"], window["id"])
    assert position_after["net_quantity"] == 100
    assert read_action(action["id"], security["id"])["status"] == "ANNOUNCED"


# ─── Default-declaration cascade, second angle ────────

def test_default_declaration_leaves_the_proceeding_declared_and_the_fund_untouched():
    """PRD §3.9: "A `RiskOfficer` declares a `SUSPENDED` member in default by
    naming the `participant_id` and a `reason_code`, only while the member is
    `SUSPENDED` (`ERR_INVALID_STATE` otherwise) and only while its
    `financial_standard_status` is `FAIL`".

    Design: Difficulty/transitive_cascade/participant_default_declaration_three_hop_cascade
    """
    from test_helpers import setup_default_proceeding

    handles = setup_default_proceeding(defaulter_posted_cents=0,
                                       survivor_names=("Cascade Beta",))
    proceeding = handles["proceeding"]
    fund = handles["fund"]

    read = validate_success(
        api_client.get_default_proceeding(proceeding["id"], ADMIN), 200)
    assert read["status"] == "DECLARED"
    assert read["participant_id"] == handles["defaulter"]["id"]
    assert read["allocated_total_cents"] == 0

    # The declaration chain does not release or re-size the fund's components.
    from test_helpers import component_of
    component = component_of(handles["defaulter"]["id"], fund["id"])
    assert component["generation"] == 1
    assert component["status"] != "RELEASED"


# ─── Precedence pairs, second angle ───────────────────

def test_refused_settlement_leaves_the_window_open_and_the_gate_short_circuits():
    """PRD §2.12: "Only then is state evaluated, yielding `ERR_INVALID_STATE` when
    the target is not in the state a transition requires."
    PRD §3.6: "The window must be `NETTED` (`ERR_INVALID_STATE` otherwise)."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_underfunded_settlement_error_category_pair
    """
    a, b = setup_two_active_members(name_a="Prior Alpha", name_b="Prior Beta",
                                    lei_a="LEI-PA", lei_b="LEI-PB")
    security, window = setup_security_and_window("PRI2", "912828XL5", 5000)
    locked_in_matched_trade(security["id"], a, b, "BUY", 100, 4000)

    # Still OPEN and entirely unfunded: two rules are violated, the state gate wins.
    validate_error(api_client.settle_window(window["id"], ADMIN), "ERR_INVALID_STATE")
    assert validate_success(
        api_client.get_settlement_window(window["id"], ADMIN), 200
    )["status"] == "OPEN"
    rows = validate_success(
        api_client.list_net_positions(ADMIN, params={"window_id": window["id"]}), 200)
    assert rows == []


def test_unauthorized_submission_is_rejected_before_the_self_trade_rule():
    """PRD §2.12: "Authorization is next: a role that is known but not permitted
    yields `ERR_UNAUTHORIZED` before any resource is inspected."
    PRD §2.1: "`PlatformAdmin` holds no clearing-member economic role and therefore
    never posts collateral or bids."

    Design: Difficulty/priority_pair_validation_conflict/suspension_beats_self_trade_error_category_pair
    """
    set_clock()
    participant = create_active_participant("Unauth Two", "LEI-UA2")
    security = create_security("UNA2", "912828XL6", 5000)
    create_window(security["id"])

    # Both violated: PlatformAdmin may not submit (priority 2), and the
    # counterparty equals the acting participant (priority 8).
    res = api_client.create_trade_submission(
        {"counterparty_participant_id": participant["id"],
         "security_id": security["id"], "side": "BUY", "quantity": 100,
         "trade_price_cents": 4200, "trade_date": "2026-09-08T14:00:00Z"},
        ADMIN)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)

    rows = validate_success(api_client.list_trade_submissions(
        ADMIN, params={"participant_id": participant["id"]}), 200)
    assert rows == []


# ─── Corner coverage: listing and the mark-only mode ──

def test_net_position_list_applies_its_participant_filter_before_pagination():
    """PRD §2.3: "List endpoints accept a `limit` parameter naming the maximum
    number of items to return, and an `offset` parameter naming the number of
    items to skip."
    PRD §2.3: "A paginated response carries the four pagination fields in the
    `meta` object of the envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/cross_cutting_complexity_layers/pagination_filter_interaction_on_net_positions
    """
    set_clock()
    pg = create_active_participant("Pager Alpha", "LEI-PG2")
    ph = create_active_participant("Pager Beta", "LEI-PH2")
    security = create_security("PAG1", "912828XV5", 5000)

    window1 = create_window(security["id"])
    locked_in_matched_trade(security["id"], pg, ph, "BUY", 100, 4000)
    net_window(window1["id"])

    window2 = create_window(security["id"], settlement_date="2026-09-11",
                            trade_entry_deadline="2026-09-10T20:00:00Z",
                            affirmation_deadline="2026-09-10T22:00:00Z")
    locked_in_matched_trade(security["id"], pg, ph, "BUY", 200, 4000,
                            "2026-09-09T14:00:00Z")
    net_window(window2["id"])

    first_page = api_client.list_net_positions(
        ADMIN, params={"participant_id": pg["id"], "limit": 1, "offset": 0})
    body = first_page.json()
    validate_success(first_page, 200)
    assert len(body["data"]) == 1
    assert body["meta"]["total_count"] == 2
    assert body["meta"]["has_more"] is True
    assert all(r["participant_id"] == pg["id"] for r in body["data"])

    second_page = api_client.list_net_positions(
        ADMIN, params={"participant_id": pg["id"], "limit": 1, "offset": 1})
    second_body = second_page.json()
    assert len(second_body["data"]) == 1
    assert second_body["meta"]["has_more"] is False
    assert all(r["participant_id"] == pg["id"] for r in second_body["data"])


def test_mark_to_market_only_recomputes_the_mark_without_moving_funds():
    """PRD §3.6: "In that mode the call performs only the fail mark recomputation
    of §3.7 and does not move any funds."

    Design: Corner/endpoints/net_position_fund_mark_to_market_only_recomputes_mark
    """
    set_clock()
    ma = create_active_participant("Mtm Alpha", "LEI-MA3")
    mb = create_active_participant("Mtm Beta", "LEI-MB3")
    security = create_security("MTM1", "912828XU2", 5000)
    window = create_window(security["id"])

    locked_in_matched_trade(security["id"], ma, mb, "BUY", 10, 4000)
    net_window(window["id"])
    validate_success(api_client.suspend_participant(ma["id"], ADMIN), 200)
    reinstated = validate_success(api_client.reinstate_participant(ma["id"], ADMIN), 200)
    assert reinstated["membership_status"] == "ACTIVE"

    book_fresh_long_on_a_new_cycle(security["id"], ma, mb, 10, 4000)

    position = net_position_of(ma["id"], window["id"])
    assert position["dvp_status"] == "FAILED"

    validate_success(api_client.update_security(
        security["id"], {"prev_settlement_price_cents": 3000}, ADMIN), 200)

    marked = fund_net_position(position["id"], ma["id"], 0, mark_to_market_only=True)
    assert marked["mark_to_market_cents"] == 10 * (3000 - position["failed_at_price_cents"])
    assert marked["funded_amount_cents"] == 0