"""Epoch share grants, the append-only ledger, and derived member balances."""
import pytest

from test_helpers import (
    EPOCH_2026_09,
    TEST_USERS,
    ApiErrorId,
    assert_ledger_entry,
    assert_ledger_reconciles,
    create_active_agreement,
    create_bidding_load,
    create_certified_member,
    create_certified_member_with_shares,
    get_success_data,
    grant_shares,
    make_member_headers,
    setup_two_member_epoch,
    submit_bid,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _grant_two_member_epoch(api):
    """Both members certified and granted: frozen split 71429 / 28571."""
    m1, m2 = setup_two_member_epoch(api)
    return m1, m2


def test_epoch_grant_split_is_frozen_before_any_grant(api):
    """PRD §3.2: "Every member's demand is computed from the pre-grant state in a
    single pass: applying one member's grant never feeds back into another
    member's demand within the same epoch."
    PRD §3.2: "Residual shares are handed out one share at a time, in descending
    order of the fractional part that was discarded — the fractional part of the
    exact proportional entitlement before flooring — with the earliest member
    `created_at` breaking ties between equal fractions."

    Design: Difficulty/combinatorial_formula/share_grant_evaluation_order_frozen_demands
    """
    m1, m2 = _grant_two_member_epoch(api)
    # Demand: floor(250000/1000)*120 = 30000 and floor(100000/1000)*120 = 12000.
    # floor(100000*30000/42000) = 71428 with fraction .5714, so M1 takes the residual share.
    assert m1["share_balance"] == 71429
    assert m1["share_reserved"] == 0
    assert m1["active_bid_count"] == 0
    assert m1["last_grant_epoch"] == EPOCH_2026_09

    ledger = validate_success(api.list_member_ledger(m1["id"], ADMIN), 200)
    assert len(ledger) == 1
    assert ledger[0]["entry_type"] == "GRANT"
    assert ledger[0]["amount"] == 71429
    assert ledger[0]["balance_after"] == 71429
    assert_ledger_entry(ledger[0])


def test_second_grant_uses_pre_grant_demand(api):
    """PRD §3.2: "The member's resulting demand is then divided by the sum of
    every eligible member's demand, multiplied by the pool of 100,000 shares,
    and floored to a whole number of shares."
    PRD §3.2: "Each grant then appends one ledger entry of type `GRANT` whose
    `amount` is the member's grant, tagged with the epoch label, and sets the
    member's `last_grant_epoch` to that epoch."

    Design: Difficulty/combinatorial_formula/share_grant_evaluation_order_frozen_demands
    """
    m1, m2 = _grant_two_member_epoch(api)
    # floor(100000*12000/42000) = 28571; the pool is exhausted with no drift.
    assert m2["share_balance"] == 28571
    assert m2["last_grant_epoch"] == EPOCH_2026_09
    assert m1["share_balance"] + m2["share_balance"] == 100_000

    ledger = validate_success(api.list_member_ledger(m2["id"], ADMIN), 200)
    assert ledger[0]["entry_type"] == "GRANT"
    assert ledger[0]["amount"] == 28571
    assert ledger[0]["balance_after"] == 28571


def test_bid_of_exact_share_balance_is_accepted_and_empties_balance(api):
    """PRD §3.4: "The member's `share_balance` must be at least the
    `shares_offered` amount, with equality permitted — a member may commit its
    exact balance and end at zero — and a shortfall is rejected with
    `ERR_INSUFFICIENT_SHARES`."
    PRD §3.4: "The commitment is real money: the create appends a `BID_HOLD`
    ledger entry whose `amount` is the negative of `shares_offered`, which reduces
    the member's `share_balance` by that amount, raises the member's
    `share_reserved` by the same amount, and increments the member's
    `active_bid_count`."

    Design: Difficulty/boundary_precision_check/exact_share_balance_equality_boundary_on_bid
    """
    m1, _m2 = _grant_two_member_epoch(api)
    agreement = create_active_agreement(api)
    load_a = create_bidding_load(
        api, agreement["id"], weight_lbs=20_000, lot_code="LOT-8A", distance_miles=300
    )

    res = api.create_bid(
        load_a["id"],
        {"member_id": m1["id"], "shares_offered": 71429, "preference_rank": 1,
         "can_self_transport": False, "expected_load_version": load_a["version"]},
        make_member_headers(m1["id"]),
    )
    bid = validate_success(res, 201)
    assert bid["bid_status"] == "SUBMITTED"
    assert bid["shares_offered"] == 71429

    member = validate_success(api.get_member(m1["id"], ADMIN), 200)
    assert member["share_balance"] == 0
    assert member["share_reserved"] == 71429
    assert member["active_bid_count"] == 1


def test_bid_above_zero_balance_is_rejected_insufficient_shares(api):
    """PRD §3.4: "The member's `share_balance` must be at least the
    `shares_offered` amount, with equality permitted — a member may commit its
    exact balance and end at zero — and a shortfall is rejected with
    `ERR_INSUFFICIENT_SHARES`."

    Design: Difficulty/boundary_precision_check/exact_share_balance_equality_boundary_on_bid
    """
    m1, _m2 = _grant_two_member_epoch(api)
    agreement = create_active_agreement(api)
    load_a = create_bidding_load(
        api, agreement["id"], weight_lbs=20_000, lot_code="LOT-8A", distance_miles=300
    )
    load_b = create_bidding_load(
        api, agreement["id"], weight_lbs=20_000, lot_code="LOT-8B", distance_miles=300
    )

    exact = api.create_bid(
        load_a["id"],
        {"member_id": m1["id"], "shares_offered": 71429, "preference_rank": 1,
         "can_self_transport": False, "expected_load_version": load_a["version"]},
        make_member_headers(m1["id"]),
    )
    validate_success(exact, 201)

    res = api.create_bid(
        load_b["id"],
        {"member_id": m1["id"], "shares_offered": 1, "preference_rank": 2,
         "can_self_transport": False, "expected_load_version": load_b["version"]},
        make_member_headers(m1["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_SHARES)

    member = validate_success(api.get_member(m1["id"], ADMIN), 200)
    assert member["share_balance"] == 0
    assert member["active_bid_count"] == 1


def test_derived_member_fields_reconcile_after_grant_and_bid(api):
    """PRD §2.5: "The member's `share_reserved` is the sum of `shares_offered`
    across that member's bids that are currently `SUBMITTED`."
    PRD §2.5: "Each row also records the `balance_after` value — the member's
    `share_balance` immediately after that row was appended — the `epoch` label
    the row belongs to, formatted as a four-digit year, a hyphen and a two-digit
    month, and a `reference_id`, which is a plain reference rather than a foreign
    key to the load or bid that caused the movement and which is null on grant rows."

    Design: Corner/entities/member_balance_reserved_and_active_bid_count_recomputed
    """
    member = create_certified_member_with_shares(api)
    assert member["share_balance"] == 100_000
    assert member["share_reserved"] == 0
    assert member["active_bid_count"] == 0

    agreement = create_active_agreement(api)
    load = create_bidding_load(api, agreement["id"])
    submit_bid(api, load, member, shares_offered=400)

    after = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert after["share_balance"] == 99_600
    assert after["share_reserved"] == 400
    assert after["active_bid_count"] == 1

    ledger = validate_success(api.list_member_ledger(member["id"], ADMIN), 200)
    assert len(ledger) == 2
    assert ledger[0]["entry_type"] == "GRANT"
    assert ledger[0]["balance_after"] == 100_000
    assert ledger[1]["entry_type"] == "BID_HOLD"
    assert ledger[1]["amount"] == -400
    assert ledger[1]["balance_after"] == 99_600


def test_ledger_entry_is_append_only_shape(api):
    """PRD §2.4: "`ShareLedgerEntry` and `RecallHold` are append-only records:
    each carries only `id` and `created_at`, and neither carries `updated_at` nor
    `version`, because neither is ever modified after it is written."

    Design: Corner/entities/ledger_entry_exposes_no_version_or_update_path
    """
    member = create_certified_member_with_shares(api)
    ledger = validate_success(api.list_member_ledger(member["id"], ADMIN), 200)
    assert len(ledger) == 1
    entry = ledger[0]
    assert_ledger_entry(entry)
    assert entry["entry_type"] == "GRANT"
    assert entry["amount"] == 100_000
    assert entry["balance_after"] == 100_000
    assert entry["reference_id"] is None
    assert "version" not in entry
    assert "updated_at" not in entry


def test_second_grant_with_stale_member_version_rejected(api):
    """PRD §2.7: "Applying an epoch share grant to a member requires
    `expected_member_version` carrying the client's last observed `version` of
    that member."
    PRD §2.7: "If the member's `version` has advanced past that value, the grant
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_member_version_on_second_grant
    """
    member = create_certified_member(api)
    stale_version = member["version"]

    first = grant_shares(api, member)
    assert first["amount"] == 100_000
    assert first["balance_after"] == 100_000

    payload = {"member_id": member["id"], "epoch": EPOCH_2026_09,
               "expected_member_version": stale_version}
    res = api.create_share_grant(payload, ADMIN)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    after = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert after["share_balance"] == 100_000
    ledger = validate_success(api.list_member_ledger(member["id"], ADMIN), 200)
    assert len(ledger) == 1


def test_cancel_releases_both_holds_and_reconciles_derived_fields(api):
    """PRD §3.3: "Every bid still `SUBMITTED` on that load becomes `REJECTED` with
    `rejection_reason` `LOAD_CANCELLED`; each of those rejections appends a
    `BID_RELEASE` ledger entry for the positive `shares_offered` amount and
    recomputes the affected member's `share_balance`, `share_reserved` and
    `active_bid_count`."

    Design: Corner/cross_cutting_complexity_layers/balances_reconcile_after_load_cancel
    """
    m1, m2 = _grant_two_member_epoch(api)
    agreement = create_active_agreement(api)
    load = create_bidding_load(api, agreement["id"])

    bid1 = submit_bid(api, load, m1, shares_offered=400)
    fresh = get_success_data(api.get_load(load["id"], ADMIN))
    bid2 = submit_bid(api, fresh, m2, shares_offered=300, preference_rank=2)

    cancelled = validate_success(api.cancel_load(load["id"], ADMIN), 200)
    assert cancelled["status"] == "CANCELLED"

    bid1_after = validate_success(api.get_bid(bid1["id"], ADMIN), 200)
    bid2_after = validate_success(api.get_bid(bid2["id"], ADMIN), 200)
    assert bid1_after["bid_status"] == "REJECTED"
    assert bid1_after["rejection_reason"] == "LOAD_CANCELLED"
    assert bid2_after["bid_status"] == "REJECTED"
    assert bid2_after["rejection_reason"] == "LOAD_CANCELLED"

    m1_after = validate_success(api.get_member(m1["id"], ADMIN), 200)
    m2_after = validate_success(api.get_member(m2["id"], ADMIN), 200)
    assert m1_after["share_balance"] == 71429
    assert m1_after["share_reserved"] == 0
    assert m1_after["active_bid_count"] == 0
    assert m2_after["share_balance"] == 28571
    assert m2_after["share_reserved"] == 0
    assert m2_after["active_bid_count"] == 0

    assert_ledger_reconciles(api, m1_after, ADMIN)
    assert_ledger_reconciles(api, m2_after, ADMIN)
