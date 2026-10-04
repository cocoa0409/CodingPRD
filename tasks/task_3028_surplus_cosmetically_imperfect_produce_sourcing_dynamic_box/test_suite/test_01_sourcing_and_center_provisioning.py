"""Provisioning: centers, suppliers, lots, bids, award fork-join and make-ready."""
import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    make_center,
    make_customer,
    make_supplier,
    make_bid,
    make_lot,
    make_lot_ready,
    make_order_buildable,
    make_subscription,
    provision_ready_lot,
    reset_clock,
    setup_center_supplier_lot,
    setup_subscriber,
    TEST_USERS,
    make_operator_headers,
    make_supplier_headers,
)
from test_helpers.fixtures import ADMIN, ANON, award_lot, refresh_lot

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Creation defaults
# ---------------------------------------------------------------------------
def test_center_create_returns_declared_defaults(api):
    """PRD §2.6: "A centre is born with `forward_posture` at `OPEN`, its
    `serving_cycle_index` at 0 and its `open_claim_count` at 0."
    PRD §2.6: "The `is_active` flag defaults to true and governs whether the
    center accepts new assignments and new orders."
    PRD §2.6: "a `max_concurrent_building_cycles` capacity that must be a whole
    number of at least 1 and at most 100, defaulting to 1 when it is not supplied."

    Design: Corner/entities/center_create_returns_every_declared_field_and_starts_open
    """
    reset_clock(api)
    payload = {
        "code": "LONE-1",
        "name": "Lone Star Center",
        "region": "SO",
        "insulation_profile": "LIGHT",
    }
    data = validate_success(api.create_fulfillment_center(payload, ADMIN), 201)

    assert data["forward_posture"] == "OPEN"
    assert data["serving_cycle_index"] == 0
    assert data["open_claim_count"] == 0
    assert data["is_active"] is True
    assert data["max_concurrent_building_cycles"] == 1
    assert data["version"] == 1
    assert data["id"] and data["created_at"]

    body = api.create_fulfillment_center(
        {"code": "LONE-2", "name": "Second", "region": "SO", "insulation_profile": "LIGHT"}, ADMIN
    ).json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_supplier_create_starts_preferred_at_a_perfect_score(api):
    """PRD §3.1: "it starts with `status` at `ACTIVE`, `reliability_score_bp` at
    10000 and `relationship_status` at `PREFERRED`."
    PRD §3.1: "When `lots_accepted_total` is zero the quality ratio has no
    denominator and is pinned to ten thousand rather than being treated as undefined"

    Design: Corner/entities/supplier_create_starts_preferred_with_a_perfect_score
    """
    reset_clock(api)
    created = validate_success(
        api.create_supplier({"name": "Green Start Farms", "region": "MW"}, ADMIN), 201
    )
    supplier = get_success_data(api.get_supplier(created["id"], ADMIN))

    assert supplier["status"] == "ACTIVE"
    assert supplier["lots_awarded_total"] == 0
    assert supplier["lots_accepted_total"] == 0
    assert supplier["reliability_score_bp"] == 10000
    assert supplier["relationship_status"] == "PREFERRED"


def test_supplier_create_with_an_unknown_region_is_refused(api):
    """PRD §2.6: "A `Customer` names a `service_region` drawn from the
    four-region enumeration `NE`, `MW`, `SO` and `WE`"
    PRD §3.9: "every supplied enum member must be one the endpoint actually
    declares ... a failure yields `ERR_INVALID_REQUEST` with HTTP status 400."

    Design: Corner/entities/supplier_create_with_an_unknown_region_returns_invalid_request
    """
    reset_clock(api)
    response = api.create_supplier({"name": "Bad Region Co", "region": "XX"}, ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    rows = get_success_data(api.list_suppliers(ADMIN))
    assert all(row["name"] != "Bad Region Co" for row in rows)


# ---------------------------------------------------------------------------
# Lot reads
# ---------------------------------------------------------------------------
def test_supply_lot_read_returns_billing_weight_and_display_price(api):
    """PRD §3.6: "the clamped figure is what the customer is actually billed;
    a report that used the raw weight would understate light items"
    PRD §3.6: "a lot with only non-equivalent evidence, or with no evidence at
    all, is priced off the `CONVENTIONAL` multiplier of 1.40"
    PRD §3.1: "`shelf_life_days` is the whole number of days between
    `harvest_date` and `expiry_date`, counting neither boundary day"

    Design: Corner/entities/supply_lot_read_returns_the_computed_billing_weight_and_display_price
    """
    center, supplier, lot = setup_center_supplier_lot(
        api, code="DEMO-SO", region="SO", category="FRUIT", procurement_grade="SURPLUS",
        unit_weight_grams=100, unit_cost_cents=300, quantity_available=300,
        harvest_date="2026-09-01T00:00:00Z", expiry_date="2026-09-20T00:00:00Z",
    )
    lot = refresh_lot(api, lot)

    assert lot["billing_weight_grams"] == 120
    assert lot["display_price_cents"] == 420
    assert lot["shelf_life_days"] == 14
    assert lot["preference_eligible"] is False
    assert lot["quality_status"] == "PASS"
    assert lot["status"] == "READY"


def test_supply_lot_read_with_unknown_id_returns_lot_not_found(api):
    """PRD §3.9: "with any unresolved reference yielding one of ... `ERR_SUPPLY_LOT_NOT_FOUND`
    ... each with HTTP status 404."
    PRD §3.9: "Fourth comes existence: path parameters are resolved left to
    right in the order they appear in the path"

    Design: Corner/entities/supply_lot_read_with_an_unknown_id_returns_lot_not_found
    """
    reset_clock(api)
    response = api.get_supply_lot(NON_EXISTENT_UUID, ADMIN)
    error = validate_error(response, ApiErrorId.ERR_SUPPLY_LOT_NOT_FOUND, 404)
    body = response.json()
    assert body["response_type"] == "error"
    assert error["error_id"] and error["message"]


# ---------------------------------------------------------------------------
# Cross-entity references
# ---------------------------------------------------------------------------
def test_subscription_create_with_unknown_customer_returns_not_found(api):
    """PRD §3.9: "Fourth comes existence: path parameters are resolved left to right in the
    order they appear in the path, and body foreign keys are resolved in the
    order the endpoint's input list declares them, with any unresolved
    reference yielding one of `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_BOX_ORDER_NOT_FOUND`, `ERR_BUILD_ITEM_NOT_FOUND`,
    `ERR_SUPPLY_LOT_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`,
    `ERR_CLAIM_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`,
    `ERR_FULFILLMENT_CENTER_NOT_FOUND` or `ERR_BID_NOT_FOUND`, each with HTTP
    status 404."

    Design: Corner/entities/subscription_create_with_an_unknown_customer_returns_customer_not_found
    """
    center, supplier, lot = setup_center_supplier_lot(api, code="DEMO-NE", region="NE")
    customer, subscription = setup_subscriber(api, region="NE", email="pr@example.com")

    response = api.create_subscription(
        {"customer_id": NON_EXISTENT_UUID, "cadence": "WEEKLY"}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_CUSTOMER_NOT_FOUND, 404)

    rows = get_success_data(api.list_subscriptions(ADMIN, {"customer_id": customer["id"]}))
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Award fork-join
# ---------------------------------------------------------------------------
def test_award_with_a_quota_of_one_joins_the_sole_bid_through_to_selected(api):
    """PRD §3.2: "With a `bidder_quota` of exactly 1, the allocation shortlists
    a single bid, moving it from `PENDING` to `SHORTLISTED`, and because the
    shortlist has exactly one member that member is immediately and
    automatically joined through to `SELECTED`."
    PRD §3.2: "Whenever a bid is selected — whether by the sole-bid join or by
    the ranked join — the lot's own procurement `status` advances to `READY`."

    Design: Difficulty/non_linear_state_machine/sourcing_bid_fork_join_two_branches_and_three_joins
    """
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE")
    s1 = make_supplier(api, name="Sigma One", region="NE")
    s2 = make_supplier(api, name="Sigma Two", region="NE")
    s3 = make_supplier(api, name="Sigma Three", region="NE")
    lot = make_lot(api, s1["id"], center["id"], category="FRUIT", unit_cost_cents=300,
                   unit_weight_grams=120, quantity_available=100)
    b1 = make_bid(api, lot["id"], s1["id"], cost=100, quantity=100)
    b2 = make_bid(api, lot["id"], s2["id"], cost=200, quantity=100)
    b3 = make_bid(api, lot["id"], s3["id"], cost=300, quantity=100)

    awarded = award_lot(api, lot, bidder_quota=1)

    by_id = {row["id"]: row for row in get_success_data(api.list_bids(ADMIN))}
    assert by_id[b1["id"]]["status"] == "SELECTED"
    assert by_id[b2["id"]]["status"] == "NOT_SELECTED"
    assert by_id[b3["id"]]["status"] == "NOT_SELECTED"
    assert awarded["status"] == "READY"
    shortlisted = get_success_data(
        api.list_bids(ADMIN, {"supply_lot_id": lot["id"], "status": "SHORTLISTED"})
    )
    assert len(shortlisted) == 0


def test_award_with_a_quota_of_two_selects_the_top_ranked_bid_only(api):
    """PRD §3.2: "With a `bidder_quota` of 2 or more, up to `bidder_quota` bids
    are moved from `PENDING` to `SHORTLISTED`, and then the shortlist is
    resolved: the highest-ranked bid by the allocation selector's ordering joins
    to `SELECTED` in a `SHORTLISTED` to `SELECTED` move, while every other
    shortlisted bid moves from `SHORTLISTED` to `NOT_SELECTED`"
    PRD §2.8: "then by `unit_cost_cents` in ascending order"

    Design: Difficulty/non_linear_state_machine/sourcing_bid_fork_join_two_branches_and_three_joins
    """
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE")
    s1 = make_supplier(api, name="Sigma One", region="NE")
    s2 = make_supplier(api, name="Sigma Two", region="NE")
    s3 = make_supplier(api, name="Sigma Three", region="NE")
    lot = make_lot(api, s1["id"], center["id"], category="FRUIT", unit_cost_cents=300,
                   unit_weight_grams=120, quantity_available=100)
    b1 = make_bid(api, lot["id"], s1["id"], cost=100, quantity=100)
    b2 = make_bid(api, lot["id"], s2["id"], cost=200, quantity=100)
    b3 = make_bid(api, lot["id"], s3["id"], cost=300, quantity=100)

    awarded = award_lot(api, lot, bidder_quota=2)

    by_id = {row["id"]: row for row in get_success_data(api.list_bids(ADMIN))}
    assert by_id[b1["id"]]["status"] == "SELECTED"
    assert by_id[b2["id"]]["status"] == "NOT_SELECTED"
    assert by_id[b3["id"]]["status"] == "NOT_SELECTED"
    assert awarded["status"] == "READY"
    shortlisted = get_success_data(
        api.list_bids(ADMIN, {"supply_lot_id": lot["id"], "status": "SHORTLISTED"})
    )
    assert len(shortlisted) == 0


def test_advance_lot_from_quoted_to_awarded_moves_remaining_bids_off_pending(api):
    """PRD §3.2: "It moves up to `bidder_quota` bids from `PENDING` to
    `SHORTLISTED`. And it moves every remaining `PENDING` bid on the lot to
    `NOT_SELECTED`."
    PRD §3.2: "it requires at least one bid on the lot to still be in `PENDING`."

    Design: Difficulty/non_linear_state_machine/sourcing_bid_fork_join_two_branches_and_three_joins
    """
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE")
    s1 = make_supplier(api, name="Sigma One", region="NE")
    s2 = make_supplier(api, name="Sigma Two", region="NE")
    s3 = make_supplier(api, name="Sigma Three", region="NE")
    lot = make_lot(api, s1["id"], center["id"], category="FRUIT", unit_cost_cents=300,
                   unit_weight_grams=120, quantity_available=100)
    b1 = make_bid(api, lot["id"], s1["id"], cost=100, quantity=100)
    b2 = make_bid(api, lot["id"], s2["id"], cost=200, quantity=100)
    b3 = make_bid(api, lot["id"], s3["id"], cost=300, quantity=100)

    award_lot(api, lot, bidder_quota=2)

    pending = get_success_data(
        api.list_bids(ADMIN, {"supply_lot_id": lot["id"], "status": "PENDING"})
    )
    assert len(pending) == 0
    by_id = {row["id"]: row for row in get_success_data(api.list_bids(ADMIN))}
    assert by_id[b3["id"]]["status"] == "NOT_SELECTED"


# ---------------------------------------------------------------------------
# Bid terminal states
# ---------------------------------------------------------------------------
def test_withdraw_from_selected_bid_is_refused(api):
    """PRD §3.2: "Withdrawing a bid that is already `SELECTED`, `NOT_SELECTED`
    or `WITHDRAWN` is a state refusal carrying `ERR_INVALID_STATE`."
    PRD §5: "| `ERR_INVALID_STATE` | 409 Conflict |"

    Design: Corner/state_machines/sourcing_bid_withdraw_from_selected_returns_invalid_state
    """
    center, supplier, lot = setup_center_supplier_lot(api, code="DEMO-NE", region="NE")
    bids = get_success_data(api.list_bids(ADMIN, {"supply_lot_id": lot["id"]}))
    selected = [b for b in bids if b["status"] == "SELECTED"]
    assert len(selected) == 1, "Setup failed: no SELECTED bid on the awarded lot"

    response = api.withdraw_bid(selected[0]["id"], {}, make_supplier_headers(supplier["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    still_selected = get_success_data(
        api.list_bids(ADMIN, {"supply_lot_id": lot["id"], "status": "SELECTED"})
    )
    assert len(still_selected) == 1
    withdrawn = get_success_data(
        api.list_bids(ADMIN, {"supply_lot_id": lot["id"], "status": "WITHDRAWN"})
    )
    assert len(withdrawn) == 0


def test_withdraw_twice_returns_invalid_state(api):
    """PRD §3.2: "A supplier may withdraw a bid it no longer stands behind, and
    withdrawal is permitted from either `PENDING` or `SHORTLISTED`"
    PRD §3.2: "Withdrawing moves the bid to `WITHDRAWN`, which is terminal"
    PRD §3.2: "Withdrawing a bid that is already `SELECTED`, `NOT_SELECTED`
    or `WITHDRAWN` is a state refusal carrying `ERR_INVALID_STATE`."

    Design: Corner/state_machines/sourcing_bid_withdraw_from_not_selected_returns_invalid_state
    """
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE")
    supplier = make_supplier(api, name="Supply Co SZ", region="NE")
    peer = make_supplier(api, name="Second Bidder", region="NE")
    lot = make_lot(api, supplier["id"], center["id"], category="FRUIT", unit_cost_cents=100)
    make_bid(api, lot["id"], supplier["id"], cost=100)
    first = make_bid(api, lot["id"], peer["id"], cost=300, quantity=100)

    validate_success(api.withdraw_bid(first["id"], {}, make_supplier_headers(peer["id"])), 200)

    response = api.withdraw_bid(first["id"], {}, make_supplier_headers(peer["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    pending = get_success_data(
        api.list_bids(ADMIN, {"supply_lot_id": lot["id"], "status": "PENDING"})
    )
    assert len(pending) == 1


# ---------------------------------------------------------------------------
# Make-ready and the supplier score
# ---------------------------------------------------------------------------
def test_make_ready_stamps_arrival_and_moves_the_supplier_counters(api):
    """PRD §3.1: "Inspection is run by an administrator, who supplies a
    `quality_outcome` and may either supply an `arrived_at` instant or leave
    the server to stamp the current logical clock"
    PRD §3.1: "it counts toward `lots_accepted_total` once it clears make-ready
    quality inspection; and it counts toward `lots_on_time_total` only when its
    `arrived_at` is not after the `ready_date` the supplier promised."

    Design: Corner/endpoints/make_ready_stamps_the_arrival_and_moves_the_supplier_score
    """
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE")
    supplier = make_supplier(api, name="Supply Co MK", region="NE")
    lot = make_lot(api, supplier["id"], center["id"], category="FRUIT", unit_cost_cents=100,
                   ready_date="2026-09-05T00:00:00Z")
    make_bid(api, lot["id"], supplier["id"], cost=100)
    lot = award_lot(api, lot)
    lot = make_lot_ready(api, lot, "PASS")

    supplier = get_success_data(api.get_supplier(supplier["id"], ADMIN))
    assert lot["quality_status"] == "PASS"
    assert lot["status"] == "READY"
    assert lot["arrived_at"].startswith("2026-09-01T00:00:00")
    assert supplier["lots_accepted_total"] == 1
    assert supplier["lots_awarded_total"] == 1
    assert supplier["lots_on_time_total"] == 1


def test_reliability_score_recomputes_from_lifetime_counters_after_make_ready(api):
    """PRD §3.1: "on-time performance worth forty per cent, computed as ten
    thousand times `lots_on_time_total` divided by `lots_awarded_total`;
    acceptance worth forty per cent ... and quality worth twenty per cent"
    PRD §3.1: "at or above 6000 but below 7500 it is `ON_WATCH`"

    Design: Corner/calculations/reliability_score_recomputes_from_the_lifetime_counters_after_a_make_ready
    """
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE")
    supplier = make_supplier(api, name="Supply Co RL", region="NE")
    lot = make_lot(api, supplier["id"], center["id"], category="FRUIT", unit_cost_cents=100,
                   ready_date="2026-09-05T00:00:00Z")
    make_bid(api, lot["id"], supplier["id"], cost=100)
    lot = award_lot(api, lot)
    make_lot_ready(api, lot, "PASS", arrived_at="2026-09-10T00:00:00Z")

    supplier = get_success_data(api.get_supplier(supplier["id"], ADMIN))
    assert supplier["lots_awarded_total"] == 1
    assert supplier["lots_accepted_total"] == 1
    assert supplier["lots_on_time_total"] == 0
    assert supplier["reliability_score_bp"] == 6000
    assert supplier["relationship_status"] == "ON_WATCH"


def test_make_ready_rejection_keeps_the_lot_out_of_boxes(api):
    """PRD §3.1: "on a failing outcome the `quality_status` becomes `REJECTED`
    and the lot never enters the build pool"
    PRD §3.9: "Eleventh is the lot quality gate: only lots whose `quality_status` is `PASS`
    may be drawn into boxes or committed, and a build or finalise that would
    draw from a lot that is not `PASS`, or a review whose cited lot is not
    `PASS`, is refused with `ERR_LOT_QUALITY_HOLD` with HTTP status 409."

    Design: Corner/state_machines/supply_lot_make_ready_rejection_leaves_the_lot_out_of_boxes
    """
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE")
    supplier = make_supplier(api, name="Supply Co QR", region="NE")
    lot = make_lot(api, supplier["id"], center["id"], category="FRUIT", unit_cost_cents=100)
    make_bid(api, lot["id"], supplier["id"], cost=100)
    lot = award_lot(api, lot)
    customer, subscription = setup_subscriber(api, region="NE", email="qr@example.com")
    order = get_success_data(
        api.create_box_order(
            {"customer_id": customer["id"], "subscription_id": subscription["id"],
             "serving_cycle_index": 2, "cuisine_preference": "STANDARD"},
            ADMIN,
        )
    )
    lot = make_lot_ready(api, lot, "REJECTED")

    buildable = make_order_buildable(api, order, center)
    response = api.build_box_order(
        buildable["id"],
        {"expected_box_order_version": buildable["version"],
         "line_plan": [{"supply_lot_id": lot["id"], "units": 6}]},
        make_operator_headers(center["id"]),
    )
    validate_error(response, ApiErrorId.ERR_LOT_QUALITY_HOLD, 409)

    lot = refresh_lot(api, lot)
    assert lot["quality_status"] == "REJECTED"
    # §3.1: the award had already advanced the procurement dimension to READY
    # before the REJECTED make-ready outcome; a failing inspection only moves
    # the quality dimension.
    assert lot["status"] == "READY"
    items = get_success_data(
        api.list_box_order_items(buildable["id"], ADMIN, {"status": "INCLUDED"})
    )
    assert len(items) == 0