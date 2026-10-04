"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() from the framework (lenient validator) so setup
failures produce clear "Setup failed" errors rather than confusing
assertion failures.

Two construction rules are load-bearing and are applied throughout:

1. A ClearingMember's X-User-ID must be the id of the Participant it acts as
   (PRD §2.1), so every member call threads the participant id through
   make_clearing_member_headers().

2. Comparison resolves `match_status` on the row that performs the lock-in
   (PRD §3.3), so when a test asserts on a participant's net or open risk the
   fixture makes that participant the LAST submitter of its comparison tuple:
   the contra is submitted first, then the participant's own row is submitted
   and locked in. That row is then unambiguously LOCKED_IN / MATCHED, which is
   what the netting inclusion set and the open-risk set both require.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_participant_payload, create_security_payload,
    create_settlement_window_payload, create_trade_submission_payload,
    create_clearing_fund_payload,
)
from .test_users import TEST_USERS, make_clearing_member_headers

ADMIN = TEST_USERS["platform_admin_headers"]
RISK = TEST_USERS["risk_officer_headers"]


def member(participant_id):
    """ClearingMember headers bound to a concrete Participant id."""
    return make_clearing_member_headers(participant_id)


# ─── Tier 1: primitive steps ──────────────────────────

def set_clock(to_iso8601=TEST_DEFAULTS["CLOCK"]):
    """Drive the logical clock (PRD §2.7)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_participant(legal_name, lei, participant_class="BANK",
                       net_capital_cents=2_000_000_000, **overrides):
    """Register a clearing member; it lands in PENDING (PRD §3.1)."""
    payload = create_participant_payload(
        legal_name=legal_name, lei=lei, participant_class=participant_class,
        net_capital_cents=net_capital_cents, **overrides)
    return get_success_data(api_client.create_participant(payload, ADMIN), 201)


def activate(participant_id):
    return get_success_data(api_client.activate_participant(participant_id, ADMIN))


def create_active_participant(legal_name, lei, participant_class="BANK",
                              net_capital_cents=2_000_000_000, **overrides):
    """Register + admit a member (PRD §3.1)."""
    p = create_participant(legal_name, lei, participant_class,
                           net_capital_cents, **overrides)
    return activate(p["id"])


def create_security(ticker, cusip, prev_settlement_price_cents=5000, **overrides):
    payload = create_security_payload(
        ticker=ticker, cusip=cusip,
        prev_settlement_price_cents=prev_settlement_price_cents, **overrides)
    return get_success_data(api_client.create_security(payload, ADMIN), 201)


def create_window(security_id, settlement_date=TEST_DEFAULTS["SETTLEMENT_DATE"],
                  trade_entry_deadline=TEST_DEFAULTS["TRADE_ENTRY_DEADLINE"],
                  affirmation_deadline=TEST_DEFAULTS["AFFIRMATION_DEADLINE"]):
    payload = create_settlement_window_payload(
        security_id, settlement_date=settlement_date,
        trade_entry_deadline=trade_entry_deadline,
        affirmation_deadline=affirmation_deadline)
    return get_success_data(api_client.create_settlement_window(payload, ADMIN), 201)


def submit_trade(security_id, counterparty_participant_id, submitter_id,
                 side="BUY", quantity=100, trade_price_cents=4000,
                 trade_date=TEST_DEFAULTS["TRADE_DATE"]):
    payload = create_trade_submission_payload(
        security_id, counterparty_participant_id, side=side, quantity=quantity,
        trade_price_cents=trade_price_cents, trade_date=trade_date)
    return get_success_data(
        api_client.create_trade_submission(payload, member(submitter_id)), 201)


def lock_in(trade_id, participant_id):
    return get_success_data(api_client.lock_in_trade(trade_id, member(participant_id)))


def dispute(trade_id, participant_id):
    return get_success_data(api_client.dispute_trade(trade_id, member(participant_id)))


def locked_in_matched_trade(security_id, participant, counterparty, side="BUY",
                            quantity=100, trade_price_cents=4000,
                            trade_date=TEST_DEFAULTS["TRADE_DATE"]):
    """A LOCKED_IN / MATCHED row owned by `participant`.

    The contra is submitted first so the participant's own row is the one
    that performs the comparison and is therefore matched on lock-in.
    """
    opposite = "SELL" if side == "BUY" else "BUY"
    submit_trade(security_id, participant["id"], counterparty["id"], opposite,
                 quantity, trade_price_cents, trade_date)
    trade = submit_trade(security_id, counterparty["id"], participant["id"], side,
                         quantity, trade_price_cents, trade_date)
    return lock_in(trade["id"], participant["id"])


def unresolved_long_position(security_id, owner, counterparty, quantity=100,
                             trade_price_cents=4000,
                             trade_date=TEST_DEFAULTS["TRADE_DATE"]):
    """A LOCKED_IN / UNRESOLVED long row owned by `owner`, with no short mirror.

    PRD §3.8 permits a SPLIT or REVERSE_SPLIT only while every net position on
    the security is non-negative, and a cash dividend only while none is net
    short, so the security must carry no short position. The mirror leg is what
    would create one, so it is pulled out of the netting population by a
    dispute.

    The owner's long row is submitted first and left OPEN. Submitting the
    counterparty's mirror then runs the submission cascade, which marks the
    mirror MATCHED and locks the owner's row in; the mirror itself stays OPEN,
    which is the entry state a dispute requires. Disputing the mirror moves it
    to DISPUTED — excluded from the §3.5 inclusion set — and sets the owner's
    contra row to UNRESOLVED, a status that set still admits. The owner
    therefore carries a positive net position and no short position exists.
    """
    submit_trade(security_id, counterparty["id"], owner["id"], "BUY",
                 quantity, trade_price_cents, trade_date)
    mirror = submit_trade(security_id, owner["id"], counterparty["id"], "SELL",
                          quantity, trade_price_cents, trade_date)
    dispute(mirror["id"], counterparty["id"])


def book_fresh_long_on_a_new_cycle(security_id, member, counterparty,
                                   quantity=10, trade_price_cents=4000,
                                   trade_date="2026-09-09T14:00:00Z"):
    """Book a fresh long for `member` on a second cycle of the same security.

    PRD §3.1 cancels the member's own live submissions when it is suspended, so
    the fail mark of §3.7 (whose inclusion set needs LOCKED_IN rows belonging
    to the position's participant) is only non-empty once the member has been
    reinstated and booked new trades. A separate settlement date keeps the new
    trades out of the already-netted cycle's inclusion set.
    """
    create_window(security_id, settlement_date="2026-09-11",
                  trade_entry_deadline="2026-09-10T20:00:00Z",
                  affirmation_deadline="2026-09-10T22:00:00Z")
    return unresolved_long_position(security_id, member, counterparty,
                                    quantity, trade_price_cents, trade_date)


def net_window(window_id):
    return get_success_data(api_client.net_window(window_id, {}, ADMIN))


def run_cycle(window_id, expected_window_version):
    return get_success_data(
        api_client.run_cycle(window_id,
                             {"expected_window_version": expected_window_version}, ADMIN))


def settle_window(window_id):
    return get_success_data(api_client.settle_window(window_id, ADMIN))


def get_deposit(participant_id):
    data = get_success_data(api_client.list_participant_deposits(participant_id, ADMIN))
    return data[0]


def post_deposit(deposit_id, participant_id, amount_cents, reason_code=None):
    payload = {"amount_cents": amount_cents}
    if reason_code is not None:
        payload["reason_code"] = reason_code
    return get_success_data(
        api_client.post_deposit_transaction(deposit_id, payload, member(participant_id)), 201)


def fund_net_position(net_position_id, participant_id, amount_cents, mark_to_market_only=None):
    payload = {"amount_cents": amount_cents}
    if mark_to_market_only is not None:
        payload["mark_to_market_only"] = mark_to_market_only
    return get_success_data(
        api_client.fund_net_position(net_position_id, payload, member(participant_id)))


def create_fund(security_id, participant_class="BANK"):
    return get_success_data(
        api_client.create_clearing_fund(
            create_clearing_fund_payload(security_id, participant_class=participant_class),
            RISK), 201)


def recompute_fund(fund_id, expected_fund_version):
    return get_success_data(
        api_client.recompute_clearing_fund(
            fund_id, {"expected_fund_version": expected_fund_version}, RISK))


def net_position_of(participant_id, window_id=None):
    data = get_success_data(api_client.list_participant_net_positions(participant_id, ADMIN))
    for row in data:
        if window_id is None or row["window_id"] == window_id:
            return row
    raise AssertionError(
        f"Setup failed: no net position for participant {participant_id} "
        f"on window {window_id}")


def component_of(participant_id, fund_id, generation=None):
    data = get_success_data(api_client.list_participant_fund_components(participant_id, ADMIN))
    rows = [r for r in data if r["clearing_fund_id"] == fund_id]
    if generation is not None:
        rows = [r for r in rows if r["generation"] == generation]
    if not rows:
        raise AssertionError(
            f"Setup failed: no fund component for participant {participant_id} "
            f"on fund {fund_id}")
    return rows[-1]


def custody_accounts(participant_id):
    return get_success_data(api_client.list_custody_accounts(participant_id, ADMIN))


# ─── Tier 2: reusable scenarios ───────────────────────

def setup_two_active_members(class_a="BANK", class_b="BANK",
                             capital_a=2_000_000_000, capital_b=2_000_000_000,
                             name_a="Alpha Clearing", name_b="Beta Clearing",
                             lei_a="LEI-ALPHA", lei_b="LEI-BETA"):
    """Set the clock and admit two members. Returns (member_a, member_b)."""
    set_clock()
    a = create_active_participant(name_a, lei_a, class_a, capital_a)
    b = create_active_participant(name_b, lei_b, class_b, capital_b)
    return a, b


def setup_security_and_window(ticker="TST1", cusip="912828ZZ0",
                              prev_settlement_price_cents=5000, **security_overrides):
    """Register a security and open its settlement window. Returns (security, window)."""
    security = create_security(ticker, cusip, prev_settlement_price_cents,
                               **security_overrides)
    window = create_window(security["id"])
    return security, window


def setup_collateralised_member(posted_cents=500_000, ticker="TST1", cusip="912828ZZ0"):
    """One ACTIVE member with a funded deposit pool. Returns (member, deposit)."""
    set_clock()
    p = create_active_participant("Deposit Co", "LEI-DEP1", "BANK", 2_000_000_000)
    deposit = get_deposit(p["id"])
    if posted_cents:
        post_deposit(deposit["id"], p["id"], posted_cents)
    return p, deposit


def setup_netted_obligation(ticker="TST1", cusip="912828ZZ0", quantity=100,
                            trade_price_cents=4000, funded_cents=None):
    """Netted window in which member A carries the cash leg.

    Member A is the last submitter of the comparison tuple, so its row is
    LOCKED_IN / MATCHED and enters the netting inclusion set.
    Returns (member_a, member_b, security, window, net_position_a).
    """
    a, b = setup_two_active_members()
    security, window = setup_security_and_window(ticker, cusip,
                                                 trade_price_cents or 5000)
    locked_in_matched_trade(security["id"], a, b, "BUY", quantity, trade_price_cents)
    window = net_window(window["id"])
    np_a = net_position_of(a["id"], window["id"])
    if funded_cents:
        np_a = fund_net_position(np_a["id"], a["id"], funded_cents)
    return a, b, security, window, np_a


# ─── Tier 3: threshold / boundary targeting ───────────

def setup_netting_convention_trades():
    """Member A holds a 100@4200 BUY and a 40@4500 SELL, both LOCKED_IN / MATCHED.

    Each leg is constructed with A as the last submitter of its own tuple so
    both legs unambiguously enter the netting inclusion set (PRD §3.5).
    Returns (a, b, security, window, trades).
    """
    a, b = setup_two_active_members()
    security, window = setup_security_and_window("NET1", "912828XK1", 5000)
    buy = locked_in_matched_trade(security["id"], a, b, "BUY", 100, 4200,
                                  "2026-09-08T14:00:00Z")
    sell = locked_in_matched_trade(security["id"], a, b, "SELL", 40, 4500,
                                   "2026-09-08T15:00:00Z")
    return a, b, security, window, {"buy": buy, "sell": sell}


def setup_fund_open_risk(quantity=1, trade_price_cents=100_000,
                         prev_settlement_price_cents=5000, volatility_bps=None,
                         ticker="FND1", cusip="912828XK2",
                         participant_class="BROKER_DEALER", capital=1_000_000_000,
                         review_capital=None, fund_class=None, review_member_index=0):
    """A member with a deterministic locked-in open risk, plus a sized fund.

    Returns (a, b, security, window, fund, component_a).

    ``review_capital`` re-runs the financial-standard review — which closes the
    reviewed member to further trade submission — after the open risk has been
    booked, so the resulting FAIL verdict is in force when the generation-1
    component is minted and its net-capital floor governs the amount.
    ``review_member_index`` selects which member is reviewed: 0 for ``a``,
    1 for ``b``.
    """
    a, b = setup_two_active_members(
        participant_class, participant_class, capital, capital,
        "Fund Alpha", "Fund Beta", "LEI-FA", "LEI-FB")
    sec_kwargs = {} if volatility_bps is None else {"current_volatility_bps": volatility_bps}
    security, window = setup_security_and_window(
        ticker, cusip, prev_settlement_price_cents, **sec_kwargs)
    locked_in_matched_trade(security["id"], a, b, "BUY", quantity, trade_price_cents)
    if review_capital is not None:
        target = (a, b)[review_member_index]
        get_success_data(api_client.financial_review(
            target["id"], {"net_capital_cents": review_capital}, RISK))
    fund = create_fund(security["id"], fund_class or participant_class)
    fund = recompute_fund(fund["id"], fund["version"])
    component_a = component_of(a["id"], fund["id"], 1)
    return a, b, security, window, fund, component_a


def reopen_fund_with_fresh_net_position(security_id, participant, counterparty):
    """Create a second window and a net position on the security.

    A fresh net position on the fund's security flips a RECOMPUTED fund back to
    OPEN so the next recompute is legitimate (PRD §3.9). The second cycle's
    cut-offs sit after the clock the fixture has driven, since netting is
    refused once the clock has reached the affirmation deadline.
    Returns the second window.
    """
    window2 = create_window(security_id, settlement_date="2026-09-11",
                            trade_entry_deadline="2026-09-10T20:00:00Z",
                            affirmation_deadline="2026-09-10T22:00:00Z")
    locked_in_matched_trade(security_id, participant, counterparty, "BUY", 10, 4000,
                            "2026-09-09T14:00:00Z")
    set_clock("2026-09-09T00:00:00Z")
    return net_window(window2["id"])


# ─── Tier 4: default management / terminal state ──────

def setup_default_proceeding(defaulter_posted_cents=5_000_000,
                             survivor_names=("Loss Beta", "Loss Gamma")):
    """Walk member A to a DECLARED default proceeding with a sized fund.

    A failing financial review after suspension makes the member defaultable
    (PRD §3.9). The defaulter's resources saturate at the total of its
    settlement obligations across all of its net positions (PRD §3.9), so the
    fixture nets a locked-in obligation for it first — otherwise the
    saturation term is zero and the estate contributes nothing.
    Returns a dict of every handle the tests need.
    """
    set_clock()
    a = create_active_participant("Default Alpha", "LEI-DA", "BANK", 2_000_000_000)
    b = create_active_participant("Default Beta", "LEI-DB", "BANK", 2_000_000_000)
    others = [create_active_participant(name, f"LEI-SV{i}", "BANK", 2_000_000_000)
              for i, name in enumerate(survivor_names)]
    security = create_security("DFT1", "912828XK5", 5000)

    if defaulter_posted_cents:
        deposit = get_deposit(a["id"])
        post_deposit(deposit["id"], a["id"], defaulter_posted_cents)

    # A netted settlement obligation for the defaulter, so its resource
    # saturation ceiling is non-zero and the survivors carry a real fund
    # component. The fund is sized afterwards, so the open risk it sees is the
    # locked-in trade rather than an empty book.
    window = create_window(security["id"])
    locked_in_matched_trade(security["id"], a, b, "BUY", 100, 100_000)
    net_window(window["id"])

    fund = create_fund(security["id"], "BANK")
    fund = recompute_fund(fund["id"], fund["version"])

    get_success_data(api_client.suspend_participant(a["id"], ADMIN))
    get_success_data(api_client.financial_review(
        a["id"], {"net_capital_cents": 100_000_000}, RISK))
    proceeding = get_success_data(api_client.create_default_proceeding(
        {"participant_id": a["id"], "reason_code": "FINANCIAL_STANDARD_BREACH"}, RISK), 201)

    return {"defaulter": a, "counterparty": b, "others": others,
            "security": security, "fund": fund, "proceeding": proceeding,
            "window": window}


def open_auction(proceeding_id):
    return get_success_data(api_client.update_default_proceeding(
        proceeding_id, {"reason_code": "AUCTION_OPEN"}, RISK))


def place_bid(proceeding_id, bidder_id, fund_component_id, bid_price_cents,
              quantity, placed_at):
    return get_success_data(api_client.place_bid(
        proceeding_id,
        {"bid_price_cents": bid_price_cents, "quantity": quantity,
         "placed_at": placed_at, "fund_component_id": fund_component_id},
        member(bidder_id)), 201)


def liquidate(proceeding_id):
    return get_success_data(api_client.liquidate_proceeding(proceeding_id, RISK))


def allocate_loss(proceeding_id):
    return get_success_data(api_client.allocate_loss(proceeding_id, RISK))


# ─── Corporate actions / windows ──────────────────────

def announce_corporate_action(security_id, action_type="SPLIT", **overrides):
    payload = {"security_id": security_id, "action_type": action_type,
               "effective_date": "2026-09-09"}
    payload.update(overrides)
    return get_success_data(api_client.create_corporate_action(payload, ADMIN), 201)


def apply_action(action_id):
    return get_success_data(api_client.apply_corporate_action(action_id, ADMIN))


def read_action(action_id, security_id):
    """Read one corporate action back through its security-scoped listing.

    PRD §4 declares no single-action GET endpoint, so the action is located in
    the `GET /clearing/securities/{id}/corporate-actions` collection it
    belongs to.
    """
    rows = get_success_data(
        api_client.list_security_corporate_actions(security_id, ADMIN))
    for row in rows:
        if row["id"] == action_id:
            return row
    raise AssertionError(
        f"Setup failed: corporate action {action_id} not found on security {security_id}")


def reverse_action(action_id):
    return get_success_data(api_client.reverse_corporate_action(action_id, ADMIN))