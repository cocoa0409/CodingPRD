"""Donated load lifecycle and the bidding gates."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_bid,
    assert_load,
    create_active_agreement,
    create_bidding_load,
    create_certified_member,
    create_certified_member_with_shares,
    create_load,
    create_load_payload,
    get_success_data,
    make_member_headers,
    setup_awarded_load,
    setup_two_member_epoch,
    submit_bid,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_new_load_starts_posted_clear_pending(api):
    """PRD §3.3: "A newly created load starts in `POSTED` with `safety_status`
    `CLEAR`, `freight_decision` `PENDING`, `delivered_lbs` zero, `meal_equivalent`
    zero, `delivery_window_start` and `delivery_window_end` null, and both
    `awarded_bid_id` and `awarded_member_id` null."

    Design: Corner/state_machines/donated_load_created_posted_clear
    """
    agreement = create_active_agreement(api)
    load = create_load(api, agreement["id"], weight_lbs=12_000, lot_code="LOT-NEW",
                       distance_miles=180)
    assert_load(load)
    assert load["status"] == "POSTED"
    assert load["safety_status"] == "CLEAR"
    assert load["freight_decision"] == "PENDING"
    assert load["freight_subsidy_cents"] == 0
    assert load["delivered_lbs"] == 0
    assert load["meal_equivalent"] == 0
    assert load["awarded_bid_id"] is None
    assert load["awarded_member_id"] is None
    assert load["delivery_window_start"] is None
    assert load["delivery_window_end"] is None
    assert load["version"] == 1


def test_get_unknown_load_returns_load_not_found(api):
    """PRD §2.9: "`ERR_LOAD_NOT_FOUND` (HTTP 404) guards load read, load posting,
    award, freight decision, dispatch, delivery, cancellation and bid creation:
    the load named by the path must exist."

    Design: Corner/entities/load_get_unknown_id_returns_load_not_found
    """
    res = api.get_load(NON_EXISTENT_UUID, ADMIN)
    error = validate_error(res, ApiErrorId.ERR_LOAD_NOT_FOUND)
    assert error["error_id"] == "ERR_LOAD_NOT_FOUND"


def test_post_on_awarded_load_rejected(api):
    """PRD §2.9: "`ERR_LOAD_NOT_POSTED` when posting a load that is not `POSTED`
    and when cancelling a load that is neither `POSTED` nor `BIDDING`;"

    Design: Corner/state_machines/post_on_awarded_load_returns_load_not_posted
    """
    member = create_certified_member_with_shares(api)
    agreement = create_active_agreement(api)
    awarded, _bid = setup_awarded_load(api, agreement["id"], member)

    res = api.post_load(awarded["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_LOAD_NOT_POSTED)

    after = validate_success(api.get_load(awarded["id"], ADMIN), 200)
    assert after["status"] == "AWARDED"
    assert after["awarded_bid_id"] == awarded["awarded_bid_id"]


def test_cancel_rejects_submitted_bids_and_releases_holds(api):
    """PRD §3.3: "Every bid still `SUBMITTED` on that load becomes `REJECTED` with
    `rejection_reason` `LOAD_CANCELLED`; each of those rejections appends a
    `BID_RELEASE` ledger entry for the positive `shares_offered` amount and
    recomputes the affected member's `share_balance`, `share_reserved` and
    `active_bid_count`."

    Design: Corner/state_machines/cancelled_load_rejects_post_and_bid
    """
    member = create_certified_member_with_shares(api)
    agreement = create_active_agreement(api)
    load = create_bidding_load(api, agreement["id"])
    bid = submit_bid(api, load, member, shares_offered=400)

    validate_success(api.cancel_load(load["id"], ADMIN), 200)

    bid_after = validate_success(api.get_bid(bid["id"], ADMIN), 200)
    assert bid_after["bid_status"] == "REJECTED"
    assert bid_after["rejection_reason"] == "LOAD_CANCELLED"

    member_after = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert member_after["share_balance"] == 100_000
    assert member_after["share_reserved"] == 0
    assert member_after["active_bid_count"] == 0


def test_cancelled_load_is_terminal_for_post_and_bid(api):
    """PRD §3.3: "The load itself moves to `CANCELLED`, which is terminal, and its
    `version` increments."
    PRD §2.9: "`ERR_LOAD_NOT_BIDDING` when awarding or bidding on a load that is
    not `BIDDING`;"

    Design: Corner/state_machines/cancelled_load_rejects_post_and_bid
    """
    member = create_certified_member_with_shares(api)
    agreement = create_active_agreement(api)
    load = create_bidding_load(api, agreement["id"])
    cancelled = validate_success(api.cancel_load(load["id"], ADMIN), 200)
    assert cancelled["status"] == "CANCELLED"

    validate_error(api.post_load(load["id"], ADMIN), ApiErrorId.ERR_LOAD_NOT_POSTED)

    res = api.create_bid(
        load["id"],
        {"member_id": member["id"], "shares_offered": 100, "preference_rank": 1,
         "can_self_transport": False, "expected_load_version": cancelled["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(res, ApiErrorId.ERR_LOAD_NOT_BIDDING)


def test_second_withdraw_rejected_bid_not_submitted(api):
    """PRD §3.4: "A member may withdraw a bid it owns at any time while the bid is
    `SUBMITTED`; a bid that is already `AWARDED`, `REJECTED` or `WITHDRAWN` cannot
    be withdrawn and yields `ERR_BID_NOT_SUBMITTED`."

    Design: Corner/state_machines/second_withdraw_returns_bid_not_submitted
    """
    member = create_certified_member_with_shares(api)
    agreement = create_active_agreement(api)
    load = create_bidding_load(api, agreement["id"])
    bid = submit_bid(api, load, member, shares_offered=400)

    first = api.withdraw_bid(bid["id"], make_member_headers(member["id"]))
    withdrawn = validate_success(first, 200)
    assert withdrawn["bid_status"] == "WITHDRAWN"
    assert withdrawn["rejection_reason"] == "WITHDRAWN_BY_MEMBER"

    second = api.withdraw_bid(bid["id"], make_member_headers(member["id"]))
    validate_error(second, ApiErrorId.ERR_BID_NOT_SUBMITTED)

    member_after = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert member_after["share_balance"] == 100_000
    assert member_after["active_bid_count"] == 0


def test_bid_missing_shares_offered_rejected_before_state_checks(api):
    """PRD §2.9: "Malformed JSON, unknown enum members and missing required fields
    are all rejected here, before any existence check, state check or business
    rule is evaluated."

    Design: Corner/entities/bid_missing_required_shares_returns_invalid_request
    """
    member = create_certified_member_with_shares(api)
    agreement = create_active_agreement(api)
    load = create_bidding_load(api, agreement["id"])

    res = api.create_bid(
        load["id"],
        {"member_id": member["id"], "preference_rank": 1,
         "can_self_transport": False, "expected_load_version": load["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    member_after = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert member_after["share_balance"] == 100_000
    data, meta = validate_paginated(api.list_bids(ADMIN, params={"load_id": load["id"]}))
    assert meta["total_count"] == 0
    assert data == []


def test_payload_error_wins_over_load_state_error(api):
    """PRD §2.9: "The order below is authoritative: a check is evaluated only
    after every check with a lower number has passed, and the first failure
    produces its error."

    Design: Corner/validations/invalid_request_beats_load_state_on_bid
    """
    member = create_certified_member_with_shares(api)
    agreement = create_active_agreement(api)
    posted = create_load(api, agreement["id"])
    assert posted["status"] == "POSTED"

    res = api.create_bid(
        posted["id"],
        {"member_id": member["id"], "preference_rank": 1,
         "can_self_transport": False, "expected_load_version": posted["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_valid_bid_creates_submitted_bid_and_hold(api):
    """PRD §3.4: "An accepted bid is created in `SUBMITTED` status with a
    `submitted_round` equal to one plus the number of bids this member has
    previously placed on this load, so a member that withdraws and re-bids is
    visibly on its second round."
    PRD §3.4: "The commitment is real money: the create appends a `BID_HOLD`
    ledger entry whose `amount` is the negative of `shares_offered`, which reduces
    the member's `share_balance` by that amount, raises the member's
    `share_reserved` by the same amount, and increments the member's
    `active_bid_count`."

    Design: Corner/validations/valid_bid_passes_all_guards
    """
    member = create_certified_member_with_shares(api)
    agreement = create_active_agreement(api)
    load = create_bidding_load(api, agreement["id"])

    bid = submit_bid(api, load, member, shares_offered=400)
    assert_bid(bid)
    assert bid["bid_status"] == "SUBMITTED"
    assert bid["submitted_round"] == 1
    assert bid["rejection_reason"] is None

    member_after = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert member_after["share_balance"] == 99_600
    assert member_after["share_reserved"] == 400
    assert member_after["active_bid_count"] == 1

    ledger = validate_success(api.list_member_ledger(member["id"], ADMIN), 200)
    holds = [e for e in ledger if e["entry_type"] == "BID_HOLD"]
    assert len(holds) == 1
    assert holds[0]["amount"] == -400


def test_second_bid_with_stale_load_version_rejected(api):
    """PRD §2.7: "Submitting a new bid against a posted load requires
    `expected_load_version` carrying the client's last observed `version` of the
    target load."
    PRD §2.7: "If the load's `version` has advanced past that value, the create is
    rejected with `ERR_STALE_VERSION` (HTTP 412) rather than being applied against
    a load state the client has not seen."

    Design: Corner/cross_cutting_complexity_layers/stale_load_version_on_second_bid
    """
    m1, m2 = setup_two_member_epoch(api)
    agreement = create_active_agreement(api)
    load = create_bidding_load(api, agreement["id"])
    stale_version = load["version"]

    first = api.create_bid(
        load["id"],
        {"member_id": m1["id"], "shares_offered": 300, "preference_rank": 1,
         "can_self_transport": False, "expected_load_version": stale_version},
        make_member_headers(m1["id"]),
    )
    validate_success(first, 201)

    after_first = validate_success(api.get_load(load["id"], ADMIN), 200)
    assert after_first["version"] > stale_version

    second = api.create_bid(
        load["id"],
        {"member_id": m2["id"], "shares_offered": 300, "preference_rank": 2,
         "can_self_transport": False, "expected_load_version": stale_version},
        make_member_headers(m2["id"]),
    )
    validate_error(second, ApiErrorId.ERR_STALE_VERSION)

    data, meta = validate_paginated(api.list_bids(ADMIN, params={"load_id": load["id"]}))
    assert meta["total_count"] == 1
    m2_after = validate_success(api.get_member(m2["id"], ADMIN), 200)
    assert m2_after["share_balance"] == 28_571


def test_bid_on_posted_load_reports_state_error_over_fiscal(api):
    """PRD §2.9: "`ERR_LOAD_NOT_BIDDING` when awarding or bidding on a load that
    is not `BIDDING`;"
    PRD §2.9: "`ERR_INSUFFICIENT_SHARES` (HTTP 409) guards bid creation and award:
    the member's `share_balance` must be at least `shares_offered`, and equality is
    allowed — a member may commit its exact balance."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_bid_for_unopened_load
    """
    member = create_certified_member(api)
    assert member["share_balance"] == 0
    agreement = create_active_agreement(api)
    posted = create_load(api, agreement["id"])
    assert posted["status"] == "POSTED"

    res = api.create_bid(
        posted["id"],
        {"member_id": member["id"], "shares_offered": 500, "preference_rank": 1,
         "can_self_transport": False, "expected_load_version": posted["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(res, ApiErrorId.ERR_LOAD_NOT_BIDDING)


def test_state_error_blocks_bid_and_leaves_no_row(api):
    """PRD §3.4: "The load must exist and be in `BIDDING` status — bidding on a
    load that has not been posted, or on one that has already been awarded, is
    rejected with `ERR_LOAD_NOT_BIDDING`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_bid_for_unopened_load
    """
    member = create_certified_member(api)
    agreement = create_active_agreement(api)
    posted = create_load(api, agreement["id"])

    res = api.create_bid(
        posted["id"],
        {"member_id": member["id"], "shares_offered": 500, "preference_rank": 1,
         "can_self_transport": False, "expected_load_version": posted["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(res, ApiErrorId.ERR_LOAD_NOT_BIDDING)

    after = validate_success(api.get_load(posted["id"], ADMIN), 200)
    assert after["status"] == "POSTED"
    member_after = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert member_after["share_balance"] == 0
    data, meta = validate_paginated(api.list_bids(ADMIN, params={"load_id": posted["id"]}))
    assert meta["total_count"] == 0
    assert data == []


def test_bid_rejected_while_load_posted_then_accepted_after_post(api):
    """PRD §3.4: "The load must exist and be in `BIDDING` status — bidding on a
    load that has not been posted, or on one that has already been awarded, is
    rejected with `ERR_LOAD_NOT_BIDDING`."

    Design: Difficulty/cross_entity_state_dependency/bid_creation_gated_by_load_status
    """
    member = create_certified_member_with_shares(api)
    agreement = create_active_agreement(api)
    posted = create_load(api, agreement["id"])

    rejected = api.create_bid(
        posted["id"],
        {"member_id": member["id"], "shares_offered": 400, "preference_rank": 1,
         "can_self_transport": False, "expected_load_version": posted["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(rejected, ApiErrorId.ERR_LOAD_NOT_BIDDING)

    bidding = validate_success(api.post_load(posted["id"], ADMIN), 200)
    assert bidding["status"] == "BIDDING"

    accepted = api.create_bid(
        posted["id"],
        {"member_id": member["id"], "shares_offered": 400, "preference_rank": 1,
         "can_self_transport": False, "expected_load_version": bidding["version"]},
        make_member_headers(member["id"]),
    )
    bid = validate_success(accepted, 201)
    assert bid["bid_status"] == "SUBMITTED"


def test_bid_on_awarded_load_rejected_not_bidding(api):
    """PRD §3.4: "The load must exist and be in `BIDDING` status — bidding on a
    load that has not been posted, or on one that has already been awarded, is
    rejected with `ERR_LOAD_NOT_BIDDING`."

    Design: Difficulty/cross_entity_state_dependency/bid_creation_gated_by_load_status
    """
    member = create_certified_member_with_shares(api)
    agreement = create_active_agreement(api)
    load = create_bidding_load(api, agreement["id"])
    submit_bid(api, load, member, shares_offered=400)
    awarded = validate_success(api.award_load(load["id"], ADMIN), 200)
    assert awarded["status"] == "AWARDED"

    res = api.create_bid(
        load["id"],
        {"member_id": member["id"], "shares_offered": 10, "preference_rank": 2,
         "can_self_transport": False, "expected_load_version": awarded["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(res, ApiErrorId.ERR_LOAD_NOT_BIDDING)


def test_accepted_bid_bumps_load_version(api):
    """PRD §3.4: "The bid itself also bumps the load's `version`, because the
    load's bidding state has changed."

    Design: Difficulty/cross_entity_state_dependency/bid_creation_gated_by_load_status
    """
    member = create_certified_member_with_shares(api)
    agreement = create_active_agreement(api)
    load = create_bidding_load(api, agreement["id"])
    version_before = load["version"]

    submit_bid(api, load, member, shares_offered=400)
    after = validate_success(api.get_load(load["id"], ADMIN), 200)
    assert after["status"] == "BIDDING"
    assert after["version"] > version_before


def test_member_cannot_withdraw_another_members_bid(api):
    """PRD §2.1: "a member may only bid, schedule, collect and withdraw as itself,
    and acting on another member's bid is rejected with `ERR_FORBIDDEN`."

    Design: Corner/endpoints/member_cannot_withdraw_another_members_bid
    """
    m1, m2 = setup_two_member_epoch(api)
    agreement = create_active_agreement(api)
    load = create_bidding_load(api, agreement["id"])
    bid = submit_bid(api, load, m1, shares_offered=400)

    m1_after_bid = validate_success(api.get_member(m1["id"], ADMIN), 200)
    assert m1_after_bid["share_balance"] == 71_029

    res = api.withdraw_bid(bid["id"], make_member_headers(m2["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    bid_after = validate_success(api.get_bid(bid["id"], ADMIN), 200)
    assert bid_after["bid_status"] == "SUBMITTED"
    still_held = validate_success(api.get_member(m1["id"], ADMIN), 200)
    assert still_held["share_balance"] == 71_029

    own = api.withdraw_bid(bid["id"], make_member_headers(m1["id"]))
    withdrawn = validate_success(own, 200)
    assert withdrawn["bid_status"] == "WITHDRAWN"
    released = validate_success(api.get_member(m1["id"], ADMIN), 200)
    assert released["share_balance"] == 71_429


def test_load_category_mismatch_rejected(api):
    """PRD §3.3: "Creating one requires the `donor_agreement_id`, a
    `product_category` that must equal the agreement's own category — a mismatch
    is rejected with `ERR_CATEGORY_MISMATCH`"

    Design: Corner/errors/category_mismatch_on_load_create_returns_409
    """
    agreement = create_active_agreement(api)
    payload = create_load_payload(
        agreement["id"], product_category="PRODUCE", storage_type="REFRIGERATED",
        weight_lbs=900, lot_code="LOT-MISMATCH", distance_miles=120,
    )
    res = api.create_load(payload, ADMIN)
    validate_error(res, ApiErrorId.ERR_CATEGORY_MISMATCH)

    loads, meta = validate_paginated(api.list_agreement_loads(agreement["id"], ADMIN))
    assert meta["total_count"] == 0
    assert loads == []
