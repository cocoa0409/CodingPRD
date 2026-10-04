"""Receipt lifecycle, store-day lifecycle and the left-to-right error ladder."""
import pytest

from test_helpers import api_client, validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID
from test_helpers import factories as f
from test_helpers.fixtures import (
    ADMIN, MANAGER, LEAD, PLANNER, CASHIER, server_for, cashier_for,
    create_item, setup_open_day, open_store_day, create_receipt, create_transfer,
    stock_item, post_guest_counts, get_store_day, get_location, get_brand,
    get_receipt, settled_receipt, close_store_day, create_shift, create_check,
)

BOAT, DECOR = "ITM-BOAT-6400", "ITM-DECOR-2400"

# The fixture-level lines carry the item *id*, so they cannot be built at import
# time. `_boat_lines()` builds them from the item the test actually created; the
# module-level constant is kept only where a test references it by name.


def _boat_lines(boat):
    return [f.retail_line(boat["id"], 1, 6400, 0.0, "RETAIL")]


def _boat():
    return create_item(sku=BOAT, name="Hand-Carved Cedar Boat Shelf",
                       theme_code="SUMMER", unit_retail_cents=6400, unit_cost_cents=2400)


def _boot(**brand_overrides):
    base = {"retail_recognition_policy": "FINAL_ONLY", "food_storage_corridor_units": 310}
    base.update(brand_overrides)
    return setup_open_day(brand_overrides=base)


# ==========================================================================
# Difficulty queue A — non_linear_state_machine (Receipt cycle)
# ==========================================================================

def test_receipt_cycles_back_to_a_state_it_already_held(api):
    """PRD §3.4: "Resolution clears `reversal_posted_at`, recomputes the provisional and
    recognized amounts on the ticket's current line set, re-enters the ticket into the
    brand's inclusion set"
    PRD §3.4: "A ticket may settle only when it is in `RECONCILED` status"

    Design: Difficulty/non_linear_state_machine/receipt_cyclic_dispute_loop_on_the_receipt_entity
    """
    brand, loc, day = _boot()
    boat = _boat()
    receipt = create_receipt(loc["id"], day["id"], _boat_lines(boat), "R-1042-0005")

    first = validate_success(api.reconcile_receipt(receipt["id"], LEAD))
    assert first["status"] == "RECONCILED"
    second = validate_success(api.settle_receipt(receipt["id"], {}))
    assert second["status"] == "SETTLED"
    third = validate_success(api.dispute_receipt(receipt["id"], MANAGER))
    assert third["status"] == "DISPUTED"
    fourth = validate_success(api.resolve_receipt(receipt["id"], MANAGER))

    assert fourth["status"] == "RECONCILED", "the loop returns the row to a state it already held"
    assert fourth["version"] > third["version"], "each hop advances the version"


def test_receipt_loop_leaves_the_brand_inclusion_set_undrifted(api):
    """PRD §3.4: "re-enters the ticket into the brand's inclusion set, recomputes both brand totals"
    PRD §2.8: "`recognized_retail_revenue_cents` on a `Brand` are recomputed - never
    incremented in place - from the current inclusion set of that brand's receipts"

    Design: Difficulty/non_linear_state_machine/receipt_cyclic_dispute_loop_on_the_receipt_entity
    """
    brand, loc, day = _boot()
    boat = _boat()
    receipt = create_receipt(loc["id"], day["id"], _boat_lines(boat), "R-1042-0005")
    reconciled = validate_success(api.reconcile_receipt(receipt["id"], LEAD))
    recognized_before = reconciled["recognized_retail_cents"]

    api.settle_receipt(receipt["id"], {})
    api.dispute_receipt(receipt["id"], MANAGER)
    during = get_brand(brand["id"])
    assert during["recognized_retail_revenue_cents"] == 0, (
        "a DISPUTED receipt sits outside the brand inclusion set"
    )

    validate_success(api.resolve_receipt(receipt["id"], MANAGER))
    after = get_brand(brand["id"])

    assert after["recognized_retail_revenue_cents"] == recognized_before, (
        "the loop leaves no residue in the brand ledger"
    )
    assert get_receipt(receipt["id"])["recognized_retail_cents"] == recognized_before


# ==========================================================================
# Difficulty queue A — boundary_precision_check
# ==========================================================================

def test_guest_count_threshold_is_inclusive_at_one_hundred_twenty(api):
    """PRD §2.10: "at or above 120 guests the day is `RUSH`, at or above 40 but below 120
    it is `STEADY`, and below 40 it is `QUIET`"
    PRD §3.1: "A count at or above 120 guests moves `traffic_state` to `RUSH` and
    simultaneously moves `conversion_gate` to `GATED_RESTRICTED`"

    Design: Difficulty/boundary_precision_check/guest_count_threshold_crossing_is_inclusive_at_one_hundred_twenty
    """
    brand, loc, day = _boot()

    at_119 = post_guest_counts(day["id"], day["version"], 119, 1190000, 30, 15)
    assert at_119["traffic_state"] == "STEADY"
    assert at_119["conversion_gate"] == "OPEN"

    at_120 = post_guest_counts(day["id"], at_119["version"], 120, 1200000, 30, 15)
    assert at_120["traffic_state"] == "RUSH", "the 120 threshold is inclusive"
    assert at_120["conversion_gate"] == "GATED_RESTRICTED"

    at_121 = post_guest_counts(day["id"], at_120["version"], 121, 1210000, 30, 15)
    assert at_121["traffic_state"] == "RUSH"
    assert at_121["conversion_gate"] == "GATED_RESTRICTED"


def test_guest_count_threshold_is_inclusive_at_forty_below_the_rush_edge(api):
    """PRD §2.10: "at or above 40 but below 120 it is `STEADY`, and below 40 it is `QUIET`"
    PRD §3.1: "A count below 40 moves `traffic_state` to `QUIET`; the gate then follows
    the day's disputes, becoming `SUSPENDED` when at least one receipt of that store
    day is in `DISPUTED` status, and returning to `OPEN` when none is"

    Design: Difficulty/boundary_precision_check/guest_count_threshold_crossing_is_inclusive_at_one_hundred_twenty
    """
    brand, loc, day = _boot()

    at_39 = post_guest_counts(day["id"], day["version"], 39, 390000, 10, 5)
    assert at_39["traffic_state"] == "QUIET"

    at_40 = post_guest_counts(day["id"], at_39["version"], 40, 400000, 10, 5)
    assert at_40["traffic_state"] == "STEADY", "the 40 threshold is inclusive"


def test_empty_receipt_set_pins_retail_sales_per_guest_to_zero_at_close(api):
    """PRD §3.1: "If the day's `restaurant_guest_count` is zero the figure is pinned to 0
    - the empty set has the value zero"
    PRD §3.1: "The **final** figure, `retail_sales_per_guest_cents`, divides the day's
    `retail_sales_cents` by the day's `restaurant_guest_count`, then rounds half-up"

    Design: Difficulty/boundary_precision_check/empty_receipt_set_pins_retail_sales_per_guest_to_zero_at_close
    """
    brand, loc, day = _boot()
    counted = post_guest_counts(day["id"], day["version"], 142, 1420000, 35, 0)

    closed = close_store_day(day["id"], counted["version"])

    assert closed["retail_sales_cents"] == 0, "no receipt exists for the day"
    assert closed["retail_sales_per_guest_cents"] == 0
    assert closed["day_status"] == "CLOSED"


def test_store_day_close_is_written_exactly_once(api):
    """PRD §2.10: "once `day_status` has reached `CLOSED` the day is terminal and is never
    returned to `OPEN`"
    PRD §3.1: "A post against a day whose `day_status` is `CLOSED` is refused earlier in
    the ladder as `ERR_STORE_DAY_CLOSED` (HTTP 409)"

    Design: Difficulty/boundary_precision_check/empty_receipt_set_pins_retail_sales_per_guest_to_zero_at_close
    """
    brand, loc, day = _boot()
    counted = post_guest_counts(day["id"], day["version"], 142, 1420000, 35, 0)
    closed = close_store_day(day["id"], counted["version"])

    validate_error(api.close_store_day(day["id"], {"expected_store_day_version": closed["version"]}, MANAGER),
                   ApiErrorId.ERR_INVALID_STATE.value)
    assert get_store_day(day["id"])["day_status"] == "CLOSED"


# ==========================================================================
# Difficulty queue A — cross_entity_state_dependency
# ==========================================================================

def test_receipt_reconcile_writes_depend_on_the_store_day_status(api):
    """PRD §3.5: "It requires the day to still be `OPEN` and requires that every receipt
    carrying that store day's identifier has a status other than `DRAFT`"
    PRD §2.10: "a store-day-scoped mutation against a closed day is rejected as an invalid
    state, reported with `ERR_STORE_DAY_CLOSED` (HTTP 409)"

    Design: Difficulty/cross_entity_state_dependency/receipt_writes_depend_on_the_store_day_status_and_the_host_check_status
    """
    brand, loc, day = _boot()
    boat = _boat()
    settled_receipt(loc["id"], day["id"], _boat_lines(boat), "R-1042-0014")
    current = get_store_day(day["id"])
    closed = close_store_day(day["id"], current["version"])
    assert closed["day_status"] == "CLOSED"

    validate_error(
        api.create_receipt(f.create_receipt_payload(loc["id"], day["id"], "R-1042-0098",
                                                    [f.retail_line(boat["id"], 1, 6400)]), LEAD),
        ApiErrorId.ERR_STORE_DAY_CLOSED.value,
    )


def test_ringing_a_receipt_on_a_closed_day_is_refused(api):
    """PRD §2.10: "a store-day-scoped mutation against a closed day is rejected as an
    invalid state, reported with `ERR_STORE_DAY_CLOSED` (HTTP 409)"
    PRD §3.5: "requires that every receipt carrying that store day's identifier has a
    status other than `DRAFT`"

    Design: Difficulty/cross_entity_state_dependency/receipt_writes_depend_on_the_store_day_status_and_the_host_check_status
    """
    brand, loc, day = _boot()
    boat = _boat()
    current = get_store_day(day["id"])
    close_store_day(day["id"], current["version"])

    validate_error(
        api.create_receipt(f.create_receipt_payload(loc["id"], day["id"], "R-1042-0097",
                                                    [f.retail_line(boat["id"], 1, 6400)]), LEAD),
        ApiErrorId.ERR_STORE_DAY_CLOSED.value,
    )


# ==========================================================================
# Corner queue B — state_machines
# ==========================================================================

def test_reconciling_a_reconciled_receipt_reports_invalid_state(api):
    """PRD §3.4: "A ticket moves from `DRAFT` to `RECONCILED` only when it is currently in
    `DRAFT`"
    PRD §2.12: "State-machine membership - whether the target resource is in a state from
    which the requested operation is defined - is priority 7 and reports `ERR_INVALID_STATE`
    (HTTP 409)"

    Design: Corner/state_machines/receipt_reconcile_from_reconciled_returns_invalid_state
    """
    brand, loc, day = _boot()
    boat = _boat()
    receipt = create_receipt(loc["id"], day["id"], _boat_lines(boat), "R-1042-0001")
    validate_success(api.reconcile_receipt(receipt["id"], LEAD))

    validate_error(api.reconcile_receipt(receipt["id"], LEAD), ApiErrorId.ERR_INVALID_STATE.value)


def test_transfer_reconcile_cannot_skip_the_dispatch_and_receive_hops(api):
    """PRD §3.7: "A transfer moves from `RECEIVED` to `RECONCILED` - and thereby to its
    terminal status - only when its `variance_bps` is at or below the brand's
    `transfer_variance_tolerance_bps`"
    PRD §2.12: "State-machine membership - whether the target resource is in a state from which
    the requested operation is defined - is priority 7 and reports `ERR_INVALID_STATE`
    (HTTP 409)"

    Design: Corner/state_machines/transfer_reconcile_from_planned_returns_invalid_state
    """
    brand, loc, day = _boot()
    boat = _boat()
    transfer = create_transfer(loc["id"], day["id"], boat["id"], 40)

    validate_error(api.reconcile_transfer(transfer["id"], LEAD), ApiErrorId.ERR_INVALID_STATE.value)


def test_a_freshly_opened_store_day_is_open_quiet_and_unclosed(api):
    """PRD §3.1: "A freshly opened day carries `day_status` of `OPEN`, `traffic_state` of
    `QUIET`, `conversion_gate` of `OPEN`, and every counter at zero"
    PRD §3.1: "Its `closed_at` is null, and it stays null for as long as `day_status` is
    `OPEN`."

    Design: Corner/state_machines/store_day_initial_state_is_open_quiet_and_unclosed
    """
    brand, loc, day = _boot()

    assert day["day_status"] == "OPEN"
    assert day["traffic_state"] == "QUIET"
    assert day["conversion_gate"] == "OPEN"
    assert day["closed_at"] is None


def test_receipt_closed_is_terminal_for_further_writes(api):
    """PRD §3.4: "A ticket reaches `CLOSED` only when its store day closes, and `CLOSED`
    is the ticket's terminal status: a closed ticket accepts no dispute, resolution,
    settle or edit"
    PRD §2.12: "State-machine membership - whether the target resource is in a state from which
    the requested operation is defined - is priority 7 and reports `ERR_INVALID_STATE`
    (HTTP 409)"

    Design: Corner/state_machines/receipt_closed_is_terminal_for_further_writes
    """
    brand, loc, day = _boot()
    boat = _boat()
    receipt = create_receipt(loc["id"], day["id"], _boat_lines(boat), "R-1042-0001")
    validate_success(api.reconcile_receipt(receipt["id"], LEAD))
    validate_success(api.settle_receipt(receipt["id"], {}))
    current = get_store_day(day["id"])
    close_store_day(day["id"], current["version"])
    assert get_receipt(receipt["id"])["status"] == "CLOSED"

    validate_error(api.dispute_receipt(receipt["id"], MANAGER), ApiErrorId.ERR_INVALID_STATE.value)


def test_a_closed_receipt_refuses_a_repeat_settle(api):
    """PRD §3.4: "`CLOSED` is the ticket's terminal status: a closed ticket accepts no
    dispute, resolution, settle or edit, and re-entering the lifecycle from it is not
    possible."
    PRD §2.12: "State-machine membership - whether the target resource is in a state from which
    the requested operation is defined - is priority 7 and reports `ERR_INVALID_STATE`
    (HTTP 409)"

    Design: Corner/state_machines/receipt_closed_is_terminal_for_further_writes
    """
    brand, loc, day = _boot()
    boat = _boat()
    receipt = create_receipt(loc["id"], day["id"], _boat_lines(boat), "R-1042-0001")
    validate_success(api.reconcile_receipt(receipt["id"], LEAD))
    validate_success(api.settle_receipt(receipt["id"], {}))
    current = get_store_day(day["id"])
    close_store_day(day["id"], current["version"])

    validate_error(api.settle_receipt(receipt["id"], {}), ApiErrorId.ERR_INVALID_STATE.value)


# ==========================================================================
# Corner queue B — validations
# ==========================================================================

def test_ringing_a_receipt_reports_the_state_row_ahead_of_the_existence_row(api):
    """PRD §2.12: "State-machine membership - whether the target resource is in a state from
    which the requested operation is defined - is priority 7 ... with the closed-day case
    surfacing as `ERR_STORE_DAY_CLOSED`"
    PRD §2.12: "Reference validity of item identifiers is priority 9 and reports
    `ERR_ITEM_NOT_FOUND` (HTTP 404)."

    Design: Corner/validations/receipt_ring_priority_puts_state_ahead_of_existence
    """
    brand, loc, day = _boot()
    current = get_store_day(day["id"])
    close_store_day(day["id"], current["version"])

    payload = f.create_receipt_payload(
        loc["id"], day["id"], "R-1042-0071",
        [f.retail_line(NON_EXISTENT_UUID, 1, 100, 0.0, "RETAIL")],
    )
    validate_error(api.create_receipt(payload, LEAD), ApiErrorId.ERR_STORE_DAY_CLOSED.value)


def test_an_unknown_item_on_an_open_day_reports_item_not_found(api):
    """PRD §3.3: "every `item_id` named by the ticket's lines must resolve to an existing
    item, with a failure reported as `ERR_ITEM_NOT_FOUND` (HTTP 404) at priority 9"
    PRD §2.7: "A request that references an `item_id` for which no `Item` exists reports
    `ERR_ITEM_NOT_FOUND` (HTTP 404)"

    Design: Corner/validations/receipt_ring_priority_puts_state_ahead_of_existence
    """
    brand, loc, day = _boot()
    payload = f.create_receipt_payload(
        loc["id"], day["id"], "R-1042-0072",
        [f.retail_line(NON_EXISTENT_UUID, 1, 100, 0.0, "RETAIL")],
    )
    validate_error(api.create_receipt(payload, LEAD), ApiErrorId.ERR_ITEM_NOT_FOUND.value)


# ==========================================================================
# Corner queue B — errors
# ==========================================================================

def test_a_request_without_a_role_header_is_rejected_as_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` carries a value that is
    not one of the eight declared roles, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.12: "Authentication comes first. The presence of both headers and the
    well-formedness of the role is priority 1"

    Design: Corner/errors/unauthenticated_request_returns_401_before_anything_else
    """
    brand, loc, day = _boot()
    boat = _boat()
    payload = f.create_receipt_payload(loc["id"], day["id"], "R-1042-0091",
                                       [f.retail_line(boat["id"], 1, 6400)])

    validate_error(
        api.create_receipt(payload, {"X-User-ID": "opaque-operator", "Content-Type": "application/json"}),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )


def test_a_role_outside_the_endpoint_roles_is_refused(api):
    """PRD §2.1: "Presenting a well-formed role that is not permitted for the requested
    operation is a different failure and is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "A `BoutiqueManager` alone opens and closes store days"

    Design: Corner/errors/role_outside_the_endpoint_roles_returns_403
    """
    brand, loc, day = _boot()
    validate_error(
        api.close_store_day(day["id"], {"expected_store_day_version": day["version"]}, PLANNER),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )


def test_an_unknown_item_on_a_clearance_create_reports_item_not_found(api):
    """PRD §2.7: "A request that references an `item_id` for which no `Item` exists
    reports `ERR_ITEM_NOT_FOUND` (HTTP 404)"
    PRD §3.8: "every `item_id` a schedule names must resolve to an existing item, with a
    failure reported as `ERR_ITEM_NOT_FOUND` (HTTP 404) at priority 9"

    Design: Corner/errors/unknown_item_on_a_clearance_create_returns_404
    """
    brand, loc, day = _boot()
    boat = _boat()
    payload = f.create_clearance_schedule_payload(
        loc["id"], NON_EXISTENT_UUID, boat["version"],
        start_date="2026-09-25T00:00:00Z", end_date="2026-10-25T00:00:00Z",
    )
    validate_error(api.create_clearance_schedule(payload, MANAGER),
                   ApiErrorId.ERR_ITEM_NOT_FOUND.value)


def test_an_unknown_transfer_id_on_a_path_segment_reports_transfer_not_found(api):
    """PRD §2.7: "a `Transfer` segment yields `ERR_TRANSFER_NOT_FOUND`"
    PRD §2.7: "the server resolves each path segment from left to right and confirms that
    the named resource exists before evaluating anything else about the request"

    Design: Corner/errors/unknown_transfer_id_on_a_path_segment_returns_transfer_not_found
    """
    brand, loc, day = _boot()
    validate_error(api.get_transfer_discrepancy(NON_EXISTENT_UUID, MANAGER),
                   ApiErrorId.ERR_TRANSFER_NOT_FOUND.value)


# ==========================================================================
# Corner queue B — consistency_model
# ==========================================================================

def test_every_response_reports_the_state_written_in_that_request(api):
    """PRD §3.3: "The new ticket begins in `DRAFT` status, and its `provisional_retail_cents`
    is computed immediately."
    PRD §3.4: "stamps `reconciled_at` from the logical clock, and moves the status to
    `RECONCILED`"

    Design: Corner/consistency_model/every_response_reports_the_state_written_in_that_request
    """
    brand, loc, day = _boot()
    boat = _boat()
    # PRD 3.3: the cleared-value deduction applies only "On a ticket that rides on
    # a dining check"; a standalone ticket reports the raw net line sum.
    shift = create_shift(loc["id"], employee_id="E-105",
                         start_utc="2026-09-01T09:00:00Z", end_utc="2026-09-01T13:00:00Z",
                         workcode="CASHIER")
    check = create_check(loc["id"], day["id"], shift["id"],
                         restaurant_subtotal_cents=11200)

    created = validate_success(
        api.create_receipt(f.create_receipt_payload(loc["id"], day["id"], "R-1042-0001",
                                                    [f.retail_line(boat["id"], 1, 6400)],
                                                    guest_check_id=check["id"],
                                                    expected_guest_check_version=check["version"]),
                           LEAD),
        201,
    )
    assert created["status"] == "DRAFT"
    assert created["provisional_retail_cents"] == 6071

    reconciled = validate_success(api.reconcile_receipt(created["id"], LEAD))
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["recognized_retail_cents"] == 5632
    assert reconciled["reconciled_at"] is not None


def test_the_creation_and_the_follow_up_read_agree_on_the_written_state(api):
    """PRD §3.3: "Ringing a ticket has a wide fan-out. The ticket increments the store
    day's `retail_transaction_count` and triggers a recomputation of the store day's
    `retail_sales_cents`."
    PRD §2.8: "Whenever the server mutates a resource as a consequence of an operation on
    a different resource, the mutated resource's `version` is incremented"

    Design: Corner/consistency_model/every_response_reports_the_state_written_in_that_request
    """
    brand, loc, day = _boot()
    boat = _boat()
    created = validate_success(
        api.create_receipt(f.create_receipt_payload(loc["id"], day["id"], "R-1042-0001",
                                                    [f.retail_line(boat["id"], 1, 6400)]), LEAD),
        201,
    )

    assert get_store_day(day["id"])["retail_transaction_count"] == 1
    assert get_receipt(created["id"])["provisional_retail_cents"] == created["provisional_retail_cents"]


def test_a_day_scoped_write_is_refused_once_the_day_is_closed(api):
    """PRD §2.10: "once `day_status` has reached `CLOSED` the day is terminal and is never
    returned to `OPEN`, and a store-day-scoped mutation against a closed day is rejected as
    an invalid state, reported with `ERR_STORE_DAY_CLOSED` (HTTP 409)."
    PRD §3.5: "Every receipt of that store day currently in `SETTLED` status is bubbled to
    `CLOSED` with `closed_at` stamped from the logical clock"

    Design: Corner/consistency_model/store_day_mutation_is_refused_once_the_day_is_closed
    """
    brand, loc, day = _boot()
    boat = _boat()
    receipt = settled_receipt(loc["id"], day["id"], _boat_lines(boat), "R-1042-0001")
    current = get_store_day(day["id"])
    closed = close_store_day(day["id"], current["version"])

    assert closed["day_status"] == "CLOSED"
    bubbled = get_receipt(receipt["id"])
    assert bubbled["status"] == "CLOSED"
    assert bubbled["closed_at"] is not None

    validate_error(
        api.post_guest_counts(day["id"], {
            "expected_store_day_version": closed["version"],
            "restaurant_guest_count": 99,
            "restaurant_sales_cents": 990000,
            "waiting_area_shopper_count": 10,
            "waiting_area_converted_count": 5,
        }, MANAGER),
        ApiErrorId.ERR_STORE_DAY_CLOSED.value,
    )