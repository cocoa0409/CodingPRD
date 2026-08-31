"""Packing and hazmat certification: classification, surcharges and window rules."""
import pytest

from test_helpers import (
    validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    create_warehouse, create_carrier, create_account, create_battery_model, receive_lot,
    create_order, add_line, submit_order, allocate_order, read_order, read_account,
    read_shipment, pack_shipment, certify_shipment, order_version, setup_base_env,
    setup_allocated_order, setup_packed_shipment,
)

OPERATOR = TEST_USERS["warehouse_operator_headers"]
CERTIFIER = TEST_USERS["hazmat_certifier_headers"]
REP = TEST_USERS["sales_rep_headers"]


def _shipments_for_order(api, order_id):
    resp = api.list_shipments(OPERATOR, params={"order_id": order_id})
    data, _meta = validate_paginated(resp)
    return data


# --------------------------------------------------------------------------
# Forecast surcharge versus the per-package actual
# --------------------------------------------------------------------------

def _packed_ten_unit_flooded_order():
    env = setup_base_env(
        "IB-31-FLD",
        account_overrides={"name": "Delta Fleet", "storm_priority_rank": 5},
        lot_overrides={"manufactured_on": "2026-06-01", "quantity_on_hand": 60},
    )
    order = create_order(env["account"]["id"], env["warehouse"]["id"],
                         requested_ship_date="2026-08-10")
    add_line(order["id"], env["model"]["id"], 10, core_expected_count=10)
    submitted = submit_order(order["id"])
    allocate_order(order["id"])
    shipment = pack_shipment(order["id"], env["carrier"]["id"])
    env["order_at_submit"] = submitted
    env["order"] = read_order(order["id"])
    env["shipment"] = shipment
    return env


def test_certification_prices_the_class_base_fee_once_per_package():
    """PRD §3.5: "The `package_count` is the total weight divided by 30.0
    kilograms and rounded **up** to a whole number: thirty kilograms is the
    maximum weight of a single hazmat package."
    PRD §3.5: "The actual computation reads the same order lines, the same
    weight and the same warehouse as the forecast did, and differs in exactly
    one respect: the class base fee is charged once per package rather than once
    per shipment, so the base fee for the shipment's class is multiplied by
    `package_count` before the per-10-kilogram weight component is added, and the
    endorsed-site discount of 0.85 is applied to the sum in the same way with
    the same half-up rounding to whole cents."

    Design: Difficulty/dual_variant_calc/hazmat_forecast_vs_shipment_actual_diverge_on_same_order
    """
    env = _packed_ten_unit_flooded_order()
    assert env["order_at_submit"]["subtotal_cents"] == 183150
    assert env["order_at_submit"]["hazmat_fee_waived"] is False
    assert env["order_at_submit"]["hazmat_fee_cents"] == 12708, \
        "The forecast charges the class base fee exactly once"
    assert env["order_at_submit"]["total_cents"] == 195858
    assert env["shipment"]["total_weight_kg"] == pytest.approx(260.0, abs=0.001)
    assert env["shipment"]["package_count"] == 9

    certified = certify_shipment(env["shipment"]["id"], "APPROVE")
    assert certified["hazmat_surcharge_cents"] == 65748, \
        f"Expected 65748 from nine packages, got {certified['hazmat_surcharge_cents']}"


def test_certification_replaces_the_order_fee_and_adjusts_the_receivable():
    """PRD §3.5: "It then cascades: unless the order's `hazmat_fee_waived` is
    true, the order's `hazmat_fee_cents` is replaced by the shipment's surcharge
    and `total_cents` is re-derived; and because the order total changed, the
    buying account's `open_receivable_cents` is adjusted by the difference
    between the new order total and the previous one."

    Design: Difficulty/dual_variant_calc/hazmat_forecast_vs_shipment_actual_diverge_on_same_order
    """
    env = _packed_ten_unit_flooded_order()
    certify_shipment(env["shipment"]["id"], "APPROVE")

    order = read_order(env["order"]["id"])
    assert order["hazmat_fee_cents"] == 65748, \
        f"The order's fee takes the actual figure, got {order['hazmat_fee_cents']}"
    assert order["total_cents"] == 248898, f"Expected 248898, got {order['total_cents']}"

    account = read_account(env["account"]["id"])
    assert account["open_receivable_cents"] == 248898, \
        f"Expected the receivable to follow the new total, got {account['open_receivable_cents']}"


# --------------------------------------------------------------------------
# Rejection-ladder pairs on the pack call
# --------------------------------------------------------------------------

def _allocated_order_at_a_refusing_carrier():
    warehouse = create_warehouse(code="OK-TUL", state_code="OK", hazmat_endorsement=False,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=500.0)
    carrier = create_carrier(code="STDGRD", name="Standard Ground",
                             accepts_hazmat_classes=["NON_REGULATED", "UN2800_EXCEPTED"],
                             max_lithium_watt_hours_per_package=100.0, ground_only=True)
    account = create_account(name="Sooner Standby", account_tier="STANDARD",
                             state_code="OK", credit_limit_cents=100000000,
                             storm_priority_rank=8)
    model = create_battery_model("IB-31-FLD")
    lot = receive_lot(model["id"], warehouse["id"], manufactured_on="2026-06-01",
                      quantity_on_hand=30)
    order = create_order(account["id"], warehouse["id"], requested_ship_date="2026-08-10")
    add_line(order["id"], model["id"], 25, core_expected_count=0)
    submitted = submit_order(order["id"])
    order = allocate_order(order["id"])
    return {"warehouse": warehouse, "carrier": carrier, "account": account,
            "model": model, "lot": lot, "order": order, "submitted": submitted}


def test_carrier_hazmat_refusal_is_reported_ahead_of_the_dock_capacity_breach(api):
    """PRD §3.5: "Six checks guard the pack, and because the ladder is strict
    they are reported in this relative order. First, the shipment's class must
    appear in the carrier's `accepts_hazmat_classes`; a class the carrier does
    not tender is refused with `ERR_CARRIER_HAZMAT_REFUSED` (HTTP 422)."
    PRD §3.5: "Fifth, the site's dock must be able to absorb the weight."

    Design: Difficulty/priority_pair_validation_conflict/carrier_hazmat_refusal_outranks_dock_capacity_on_pack
    """
    ctx = _allocated_order_at_a_refusing_carrier()
    assert ctx["submitted"]["total_cents"] == 529300

    resp = api.create_shipment({
        "order_id": ctx["order"]["id"],
        "carrier_id": ctx["carrier"]["id"],
        "pickup_window_start": "2026-08-05T08:00:00Z",
        "pickup_window_end": "2026-08-05T18:00:00Z",
        "expected_order_version": ctx["order"]["version"],
    }, OPERATOR)
    error = validate_error(resp, ApiErrorId.ERR_CARRIER_HAZMAT_REFUSED.value)
    assert error["error_id"] != ApiErrorId.ERR_DOCK_CAPACITY_EXCEEDED.value, \
        "The hazmat safety rung outranks the remaining-constraint rung"


def test_refused_pack_creates_no_shipment_row(api):
    """PRD §3.5: "First, the shipment's class must appear in the carrier's
    `accepts_hazmat_classes`; a class the carrier does not tender is refused
    with `ERR_CARRIER_HAZMAT_REFUSED` (HTTP 422)."
    PRD §3.5: "The order must stand in `ALLOCATED`. The operator's `X-User-ID`
    is recorded as `packed_by_user_id`, and the order's `version` increments by
    1."

    Design: Difficulty/priority_pair_validation_conflict/carrier_hazmat_refusal_outranks_dock_capacity_on_pack
    """
    ctx = _allocated_order_at_a_refusing_carrier()
    api.create_shipment({
        "order_id": ctx["order"]["id"],
        "carrier_id": ctx["carrier"]["id"],
        "pickup_window_start": "2026-08-05T08:00:00Z",
        "pickup_window_end": "2026-08-05T18:00:00Z",
        "expected_order_version": ctx["order"]["version"],
    }, OPERATOR)

    assert _shipments_for_order(api, ctx["order"]["id"]) == [], \
        "A refused pack leaves no shipment behind"
    assert read_order(ctx["order"]["id"])["fulfillment_status"] == "ALLOCATED"


def _tight_dock_with_one_packed_shipment(window_end="2026-08-05T12:00:00Z"):
    """A 50.0 kg dock holding one 28.0 kg shipment, plus a second allocated order."""
    env = setup_base_env(
        "IB-AGM-95",
        warehouse_overrides={"code": "TX-TIGHT", "dock_capacity_kg_per_window": 50.0},
        account_overrides={"name": "Panhandle Power", "storm_priority_rank": 4},
        lot_overrides={"manufactured_on": "2026-06-01", "quantity_on_hand": 30},
    )
    order_a = create_order(env["account"]["id"], env["warehouse"]["id"],
                           requested_ship_date="2026-08-05")
    add_line(order_a["id"], env["model"]["id"], 1, core_expected_count=0)
    submit_order(order_a["id"])
    allocate_order(order_a["id"])
    shipment_a = pack_shipment(order_a["id"], env["carrier"]["id"],
                               pickup_window_start="2026-08-05T08:00:00Z",
                               pickup_window_end=window_end)

    order_b = create_order(env["account"]["id"], env["warehouse"]["id"],
                           requested_ship_date="2026-08-05")
    add_line(order_b["id"], env["model"]["id"], 1, core_expected_count=0)
    submit_order(order_b["id"])
    order_b = allocate_order(order_b["id"])

    env.update({"order_a": order_a, "shipment_a": shipment_a, "order_b": order_b})
    return env


def test_carrier_window_conflict_is_reported_ahead_of_the_dock_breach(api):
    """PRD §3.5: "A genuine overlap against any other shipment on the same
    carrier standing in `PACKED`, `CERTIFIED` or `DISPATCHED` is refused with
    `ERR_CARRIER_WINDOW_CONFLICT` (HTTP 409)."
    PRD §2.6: "Because parent-version checking (rung 9) precedes every state
    check (rung 10 onwards), a shipment packed against a stale order version
    returns `ERR_STALE_VERSION` even when the order is also in the wrong
    fulfilment state."

    Design: Difficulty/priority_pair_validation_conflict/carrier_window_conflict_outranks_dock_capacity_on_pack
    """
    env = _tight_dock_with_one_packed_shipment()
    assert env["shipment_a"]["total_weight_kg"] == pytest.approx(28.0, abs=0.001)

    resp = api.create_shipment({
        "order_id": env["order_b"]["id"],
        "carrier_id": env["carrier"]["id"],
        "pickup_window_start": "2026-08-05T11:00:00Z",
        "pickup_window_end": "2026-08-05T13:00:00Z",
        "expected_order_version": env["order_b"]["version"],
    }, OPERATOR)
    error = validate_error(resp, ApiErrorId.ERR_CARRIER_WINDOW_CONFLICT.value)
    assert error["error_id"] != ApiErrorId.ERR_DOCK_CAPACITY_EXCEEDED.value, \
        "The temporal rung outranks the remaining-constraint rung"


def test_overlapping_tender_leaves_the_first_shipment_alone(api):
    """PRD §3.5: "One pair of touching windows on one carrier at one site can
    therefore pass the carrier check and fail the dock check, and that is
    intended."
    PRD §3.5: "A genuine overlap against any other shipment on the same carrier
    standing in `PACKED`, `CERTIFIED` or `DISPATCHED` is refused with
    `ERR_CARRIER_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/carrier_window_conflict_outranks_dock_capacity_on_pack
    """
    env = _tight_dock_with_one_packed_shipment()
    api.create_shipment({
        "order_id": env["order_b"]["id"],
        "carrier_id": env["carrier"]["id"],
        "pickup_window_start": "2026-08-05T11:00:00Z",
        "pickup_window_end": "2026-08-05T13:00:00Z",
        "expected_order_version": env["order_b"]["version"],
    }, OPERATOR)

    assert read_shipment(env["shipment_a"]["id"])["status"] == "PACKED"
    assert _shipments_for_order(api, env["order_b"]["id"]) == []


# --------------------------------------------------------------------------
# The two window axes
# --------------------------------------------------------------------------

def _three_allocated_orders_on_one_carrier():
    """A roomy dock with three one-unit orders ready to tender."""
    env = setup_base_env(
        "IB-AGM-95",
        account_overrides={"name": "Panhandle Power", "storm_priority_rank": 4},
        lot_overrides={"manufactured_on": "2026-06-01", "quantity_on_hand": 30},
    )
    orders = []
    for _ in range(3):
        order = create_order(env["account"]["id"], env["warehouse"]["id"],
                             requested_ship_date="2026-08-05")
        add_line(order["id"], env["model"]["id"], 1, core_expected_count=0)
        submit_order(order["id"])
        orders.append(allocate_order(order["id"]))
    env["orders"] = orders
    return env


def test_a_window_beginning_where_another_ends_is_accepted_on_the_carrier_axis():
    """PRD §3.5: "The **carrier** conflict check treats windows as half-open,
    spanning from the start instant inclusive up to but excluding the end
    instant: two windows collide only when they genuinely overlap, so a window
    that begins at the exact instant another ends does not collide and is
    accepted."

    Design: Difficulty/resource_temporal_overlap/carrier_windows_are_half_open_adjacency_allowed_overlap_rejected
    """
    env = _three_allocated_orders_on_one_carrier()
    order_a, order_b = env["orders"][0], env["orders"][1]

    pack_shipment(order_a["id"], env["carrier"]["id"],
                  pickup_window_start="2026-08-05T08:00:00Z",
                  pickup_window_end="2026-08-05T12:00:00Z")
    shipment_b = pack_shipment(order_b["id"], env["carrier"]["id"],
                               pickup_window_start="2026-08-05T12:00:00Z",
                               pickup_window_end="2026-08-05T16:00:00Z")

    assert shipment_b["status"] == "PACKED", "Adjacency is not a collision"
    assert shipment_b["pickup_window_start"].startswith("2026-08-05T12:00:00")


def test_a_genuinely_overlapping_window_is_refused_on_the_carrier_axis(api):
    """PRD §3.5: "A genuine overlap against any other shipment on the same
    carrier standing in `PACKED`, `CERTIFIED` or `DISPATCHED` is refused with
    `ERR_CARRIER_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/carrier_windows_are_half_open_adjacency_allowed_overlap_rejected
    """
    env = _three_allocated_orders_on_one_carrier()
    order_a, order_b, order_c = env["orders"]

    pack_shipment(order_a["id"], env["carrier"]["id"],
                  pickup_window_start="2026-08-05T08:00:00Z",
                  pickup_window_end="2026-08-05T12:00:00Z")
    pack_shipment(order_b["id"], env["carrier"]["id"],
                  pickup_window_start="2026-08-05T12:00:00Z",
                  pickup_window_end="2026-08-05T16:00:00Z")

    resp = api.create_shipment({
        "order_id": order_c["id"],
        "carrier_id": env["carrier"]["id"],
        "pickup_window_start": "2026-08-05T11:00:00Z",
        "pickup_window_end": "2026-08-05T13:00:00Z",
        "expected_order_version": order_c["version"],
    }, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_CARRIER_WINDOW_CONFLICT.value)

    assert _shipments_for_order(api, order_c["id"]) == []
    assert read_order(order_c["id"])["fulfillment_status"] == "ALLOCATED"


def test_touching_windows_aggregate_against_the_dock_capacity(api):
    """PRD §3.5: "The **dock capacity** check treats windows as closed at both
    ends, so windows that merely touch at an endpoint *do* aggregate: the new
    shipment's `total_weight_kg` is added to the total weight of every other
    shipment at the same warehouse standing in `PACKED`, `CERTIFIED` or
    `DISPATCHED` whose window shares any instant with the new one, endpoints
    included, and the sum must be no greater than the site's
    `dock_capacity_kg_per_window`. Exceeding it is refused with
    `ERR_DOCK_CAPACITY_EXCEEDED` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/warehouse_dock_capacity_aggregates_touching_windows
    """
    env = _tight_dock_with_one_packed_shipment()
    assert env["shipment_a"]["total_weight_kg"] == pytest.approx(28.0, abs=0.001)

    resp = api.create_shipment({
        "order_id": env["order_b"]["id"],
        "carrier_id": env["carrier"]["id"],
        "pickup_window_start": "2026-08-05T12:00:00Z",
        "pickup_window_end": "2026-08-05T16:00:00Z",
        "expected_order_version": env["order_b"]["version"],
    }, OPERATOR)
    error = validate_error(resp, ApiErrorId.ERR_DOCK_CAPACITY_EXCEEDED.value)
    assert error["error_id"] != ApiErrorId.ERR_CARRIER_WINDOW_CONFLICT.value, \
        "The same touching pair passes the carrier axis"


def test_dock_breach_leaves_the_earlier_tender_packed(api):
    """PRD §3.5: "One pair of touching windows on one carrier at one site can
    therefore pass the carrier check and fail the dock check, and that is
    intended."
    PRD §3.1: "a `dock_capacity_kg_per_window` weight ceiling, strictly
    positive, that limits how much tonnage the site may tender across mutually
    overlapping pickup windows"

    Design: Difficulty/resource_temporal_overlap/warehouse_dock_capacity_aggregates_touching_windows
    """
    env = _tight_dock_with_one_packed_shipment()
    api.create_shipment({
        "order_id": env["order_b"]["id"],
        "carrier_id": env["carrier"]["id"],
        "pickup_window_start": "2026-08-05T12:00:00Z",
        "pickup_window_end": "2026-08-05T16:00:00Z",
        "expected_order_version": env["order_b"]["version"],
    }, OPERATOR)

    assert _shipments_for_order(api, env["order_b"]["id"]) == []
    assert read_shipment(env["shipment_a"]["id"])["status"] == "PACKED"


# --------------------------------------------------------------------------
# Certification requires an endorsed shipping site
# --------------------------------------------------------------------------

def _packed_shipment_out_of_an_unendorsed_site():
    warehouse = create_warehouse(code="OK-TUL", state_code="OK", hazmat_endorsement=False,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=5000.0)
    carrier = create_carrier()
    account = create_account(name="Sooner Standby", account_tier="STANDARD",
                             state_code="OK", credit_limit_cents=100000000,
                             storm_priority_rank=8)
    model = create_battery_model("IB-31-FLD")
    receive_lot(model["id"], warehouse["id"], manufactured_on="2026-06-01",
                quantity_on_hand=30)
    order = create_order(account["id"], warehouse["id"], requested_ship_date="2026-08-10")
    add_line(order["id"], model["id"], 1, core_expected_count=0)
    submitted = submit_order(order["id"])
    allocate_order(order["id"])
    shipment = pack_shipment(order["id"], carrier["id"])
    return {"warehouse": warehouse, "carrier": carrier, "account": account,
            "model": model, "order": read_order(order["id"]), "submitted": submitted,
            "shipment": shipment}


def test_approval_out_of_an_unendorsed_site_is_refused(api):
    """PRD §3.5: "An `APPROVE` decision first requires that, when the shipment's
    class is anything other than `NON_REGULATED`, the order's warehouse holds a
    hazmat endorsement; an unendorsed site is refused with
    `ERR_WAREHOUSE_NOT_HAZMAT_ENDORSED` (HTTP 422)."
    PRD §3.1: "The classification rules are exhaustive and mutually exclusive:
    a flooded lead-acid model is always `UN2794`; a nickel-cadmium model is
    always `UN2795`; an AGM or gel model is `UN2800_EXCEPTED` when its unit
    weight is at most 30.0 kilograms and `UN2800` when it is heavier, so a unit
    weighing exactly 30.0 kilograms is excepted; and a lithium-iron-phosphate
    model is `NON_REGULATED` when its watt-hour rating is at most 20.0
    watt-hours, `UN3480_SECTION_II` when the rating is greater than 20.0 but at
    most 100.0 watt-hours, so a cell rated at exactly 100.0 watt-hours is
    Section II, and `UN3480_SECTION_IA` above that."

    Design: Difficulty/cross_entity_state_dependency/shipment_certify_requires_warehouse_hazmat_endorsement
    """
    ctx = _packed_shipment_out_of_an_unendorsed_site()
    assert ctx["submitted"]["total_cents"] == 29325
    assert ctx["shipment"]["hazmat_class_code"] == "UN2794"

    resp = api.certify_shipment(ctx["shipment"]["id"],
                                {"certification_decision": "APPROVE"}, CERTIFIER)
    validate_error(resp, ApiErrorId.ERR_WAREHOUSE_NOT_HAZMAT_ENDORSED.value)


def test_refused_certification_leaves_the_shipment_and_the_order_fee_alone(api):
    """PRD §3.5: "The shipment moves `PACKED → CERTIFIED` and the platform
    recomputes the surcharge against the **actual** package count."
    PRD §3.3: "Step three sets `hazmat_fee_cents` to zero when the waiver
    applies and otherwise to the forecast hazmat surcharge described below."

    Design: Difficulty/cross_entity_state_dependency/shipment_certify_requires_warehouse_hazmat_endorsement
    """
    ctx = _packed_shipment_out_of_an_unendorsed_site()
    api.certify_shipment(ctx["shipment"]["id"], {"certification_decision": "APPROVE"},
                         CERTIFIER)

    shipment = read_shipment(ctx["shipment"]["id"])
    assert shipment["status"] == "PACKED"
    assert shipment["hazmat_surcharge_cents"] == 0

    order = read_order(ctx["order"]["id"])
    assert order["hazmat_fee_cents"] == 8625, \
        f"The unendorsed forecast fee stands, got {order['hazmat_fee_cents']}"


def test_delivering_a_certified_shipment_before_dispatch_is_refused(api):
    """PRD §3.5: "Confirming delivery on a `DISPATCHED` shipment is the heaviest
    single operation in the system, because it drives a five-hop cascade that
    runs to completion inside the request."
    PRD §3.5: "**Hop one** writes the shipment's `delivered_at` from the logical
    clock and moves it `DISPATCHED → DELIVERED`."

    Design: Corner/state_machines/deliver_before_dispatch_returns_invalid_state
    """
    from test_helpers import setup_certified_shipment
    env = setup_certified_shipment(
        quantity=2, core_expected_count=0, model_preset="IB-AGM-95",
        lot_overrides={"manufactured_on": "2026-06-01", "quantity_on_hand": 30},
        order_overrides={"requested_ship_date": "2026-08-05"},
    )
    assert env["shipment"]["status"] == "CERTIFIED"

    resp = api.deliver_shipment(env["shipment"]["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    shipment = read_shipment(env["shipment"]["id"])
    assert shipment["status"] == "CERTIFIED"
    assert shipment["delivered_at"] is None
    assert read_order(env["order"]["id"])["fulfillment_status"] == "ALLOCATED"


def test_rejecting_certification_blacklists_the_carrier_and_moves_no_money():
    """PRD §3.5: "A `REJECT` decision moves the shipment `PACKED →
    HAZMAT_REJECTED` and records the `rejection_reason`. It sets the order's
    `hazmat_hold` to true and appends the shipment's `carrier_id` to the order's
    `rejected_carrier_ids`, and it releases both the shipment's carrier window
    and its dock-capacity contribution so the freight can be re-packed onto a
    different carrier. It touches none of the money: the order's
    `hazmat_fee_cents`, the order's `total_cents` and the account's
    `open_receivable_cents` are all left exactly as they were."
    PRD §3.5: "Whichever way it goes, the certifier's `X-User-ID` is written to
    `certified_by_user_id`."

    Design: Corner/state_machines/certify_reject_blacklists_carrier_and_sets_hazmat_hold
    """
    env = setup_packed_shipment(
        quantity=2, core_expected_count=0, model_preset="IB-AGM-95",
        lot_overrides={"manufactured_on": "2026-06-01", "quantity_on_hand": 30},
        order_overrides={"requested_ship_date": "2026-08-05"},
    )
    order_at_submit = read_order(env["order"]["id"])
    assert order_at_submit["hazmat_fee_cents"] == 2678
    assert order_at_submit["total_cents"] == 59678

    rejected = certify_shipment(
        env["shipment"]["id"], "REJECT",
        rejection_reason="Vent caps not sealed to the carrier's non-spillable standard.",
    )
    assert rejected["status"] == "HAZMAT_REJECTED"
    assert rejected["certified_by_user_id"] == "cert-1"
    assert rejected["hazmat_surcharge_cents"] == 0

    order = read_order(env["order"]["id"])
    assert order["hazmat_hold"] is True
    assert env["carrier"]["id"] in order["rejected_carrier_ids"]
    assert order["hazmat_fee_cents"] == 2678, "The REJECT branch moves no money"
    assert order["total_cents"] == 59678
    assert order["fulfillment_status"] == "ALLOCATED"
    assert read_account(env["account"]["id"])["open_receivable_cents"] == 59678


def test_dispatch_on_a_previously_rejected_carrier_is_refused(api):
    """PRD §3.5: "Two gates apply beyond the requirement that the shipment stand
    in `CERTIFIED`: the shipment's carrier must not appear in the order's
    `rejected_carrier_ids`, and a blacklisted carrier is refused with
    `ERR_CARRIER_PREVIOUSLY_REJECTED` (HTTP 409); and the logical clock must lie
    inside the pickup window read as **half-open** — at or after
    `pickup_window_start` and strictly before `pickup_window_end` — with
    anything outside refused as `ERR_DISPATCH_WINDOW_NOT_OPEN` (HTTP 409)."
    PRD §2.5: "An order may legitimately carry more than one shipment row over
    its life, because a refused tender is re-packed onto a different carrier; a
    second pack against a freshly re-read order version therefore succeeds, and
    only a stale view of the order is refused."

    Design: Corner/state_machines/dispatch_on_previously_rejected_carrier_is_refused
    """
    from test_helpers import set_clock
    env = setup_packed_shipment(
        quantity=2, core_expected_count=0, model_preset="IB-AGM-95",
        lot_overrides={"manufactured_on": "2026-06-01", "quantity_on_hand": 30},
        order_overrides={"requested_ship_date": "2026-08-05"},
    )
    certify_shipment(env["shipment"]["id"], "REJECT", rejection_reason="Vent caps not sealed.")
    assert read_order(env["order"]["id"])["hazmat_hold"] is True

    second = pack_shipment(env["order"]["id"], env["carrier"]["id"])
    certified = certify_shipment(second["id"], "APPROVE")
    assert certified["hazmat_surcharge_cents"] == 3953
    order = read_order(env["order"]["id"])
    assert order["hazmat_fee_cents"] == 3953
    assert order["total_cents"] == 60953

    set_clock("2026-08-05T09:00:00Z")
    resp = api.dispatch_shipment(second["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_CARRIER_PREVIOUSLY_REJECTED.value)

    shipment = read_shipment(second["id"])
    assert shipment["status"] == "CERTIFIED"
    assert shipment["dispatched_at"] is None
    assert read_order(env["order"]["id"])["fulfillment_status"] == "ALLOCATED"


def test_shipment_class_is_the_maximum_severity_across_the_order_lines(api):
    """PRD §3.5: "The shipment's `hazmat_class_code` is the class whose severity
    rank equals the highest severity rank among the models on the order's lines,
    computed over every line regardless of its allocated quantity and without
    quantity weighting — the same rule the order's forecast used, so the two
    normally agree."
    PRD §3.5: "The `total_weight_kg` is the sum over the lines of quantity
    multiplied by the model's unit weight, rounded half up to three decimals;
    `total_lead_kg` is the same sum against each model's `lead_content_kg`,
    likewise to three decimals."

    Design: Corner/calculations/shipment_class_is_the_maximum_severity_over_its_order_lines
    """
    env = setup_base_env(
        "IB-AGM-95",
        account_overrides={"name": "Delta Fleet", "storm_priority_rank": 5},
        lot_overrides={"manufactured_on": "2026-06-01", "quantity_on_hand": 30},
    )
    flooded = create_battery_model("IB-31-FLD")
    receive_lot(flooded["id"], env["warehouse"]["id"], manufactured_on="2026-06-01",
                quantity_on_hand=30)

    order = create_order(env["account"]["id"], env["warehouse"]["id"],
                         requested_ship_date="2026-08-05")
    add_line(order["id"], env["model"]["id"], 2, core_expected_count=0)
    add_line(order["id"], flooded["id"], 1, core_expected_count=0)
    submit_order(order["id"])
    allocate_order(order["id"])

    shipment = pack_shipment(order["id"], env["carrier"]["id"])
    assert shipment["hazmat_class_code"] == "UN2794", \
        f"The flooded line outranks the AGM lines, got {shipment['hazmat_class_code']}"
    assert shipment["total_weight_kg"] == pytest.approx(82.0, abs=0.001)
    assert shipment["package_count"] == 3
    assert shipment["total_lead_kg"] == pytest.approx(38.500, abs=0.0005)
    assert read_order(order["id"])["line_count"] == 2


def _allocated_lithium_order(carrier_overrides):
    env = setup_base_env(
        "IB-LFP-100",
        account_overrides={"name": "Delta Fleet", "storm_priority_rank": 5},
        carrier_overrides=carrier_overrides,
        lot_overrides={"manufactured_on": "2026-06-01", "quantity_on_hand": 30},
    )
    order = create_order(env["account"]["id"], env["warehouse"]["id"],
                         requested_ship_date="2026-08-05")
    add_line(order["id"], env["model"]["id"], 1, core_expected_count=0)
    env["order_at_submit"] = submit_order(order["id"])
    env["order"] = allocate_order(order["id"])
    return env


def test_lithium_above_the_carrier_watt_hour_cap_is_refused(api):
    """PRD §3.5: "Third, for every line whose model chemistry is
    `LITHIUM_IRON_PHOSPHATE`, that model's `watt_hour_rating` must be no greater
    than the carrier's `max_lithium_watt_hours_per_package`, and a breach is
    refused with `ERR_LITHIUM_WH_LIMIT_EXCEEDED` (HTTP 422)."
    PRD §3.1: "Registering a carrier captures its `code` and display `name`, an
    explicit `accepts_hazmat_classes` list enumerating exactly which
    classification codes that carrier will tender, a
    `max_lithium_watt_hours_per_package` ceiling that may not be negative, and a
    `ground_only` boolean that defaults to true"

    Design: Corner/validations/pack_exceeding_carrier_lithium_watt_hour_cap_is_refused
    """
    env = _allocated_lithium_order({"code": "LOWLI", "name": "Low Lithium Ground",
                                    "max_lithium_watt_hours_per_package": 100.0,
                                    "ground_only": True})
    assert env["order_at_submit"]["total_cents"] == 100093

    resp = api.create_shipment({
        "order_id": env["order"]["id"], "carrier_id": env["carrier"]["id"],
        "pickup_window_start": "2026-08-05T08:00:00Z",
        "pickup_window_end": "2026-08-05T18:00:00Z",
        "expected_order_version": env["order"]["version"],
    }, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_LITHIUM_WH_LIMIT_EXCEEDED.value)

    assert _shipments_for_order(api, env["order"]["id"]) == []
    assert read_order(env["order"]["id"])["fulfillment_status"] == "ALLOCATED"


def test_section_ia_freight_may_not_be_tendered_to_an_air_carrier(api):
    """PRD §3.5: "Second, a shipment classified `UN3480_SECTION_IA` may only go
    to a carrier whose `ground_only` is true, because that class may not move by
    air; an air carrier is refused with `ERR_AIR_MODE_PROHIBITED` (HTTP 422)."
    PRD §3.1: "a carrier with `ground_only` false moves freight by air, which as
    Section 3.5 explains prohibits the most severe lithium class outright"

    Design: Corner/validations/section_ia_tender_to_an_air_carrier_is_refused
    """
    env = _allocated_lithium_order({"code": "AIRX", "name": "AirEx Cargo",
                                    "max_lithium_watt_hours_per_package": 5000.0,
                                    "ground_only": False})

    resp = api.create_shipment({
        "order_id": env["order"]["id"], "carrier_id": env["carrier"]["id"],
        "pickup_window_start": "2026-08-05T08:00:00Z",
        "pickup_window_end": "2026-08-05T18:00:00Z",
        "expected_order_version": env["order"]["version"],
    }, OPERATOR)
    error = validate_error(resp, ApiErrorId.ERR_AIR_MODE_PROHIBITED.value)
    assert error["error_id"] != ApiErrorId.ERR_LITHIUM_WH_LIMIT_EXCEEDED.value, \
        "The 5000.0 Wh cap is not breached here"
    assert _shipments_for_order(api, env["order"]["id"]) == []


def test_a_second_live_shipment_on_the_same_order_is_refused(api):
    """PRD §3.5: "Sixth, the order must not already carry a live shipment: if
    any other shipment for the same order stands in `PACKED`, `CERTIFIED`,
    `DISPATCHED` or `DELIVERED`, the request is refused with
    `ERR_SHIPMENT_ALREADY_OPEN` (HTTP 409)."

    Design: Corner/validations/second_open_shipment_on_the_same_order_is_refused
    """
    env = setup_packed_shipment(
        quantity=2, core_expected_count=0, model_preset="IB-AGM-95",
        lot_overrides={"manufactured_on": "2026-06-01", "quantity_on_hand": 30},
        order_overrides={"requested_ship_date": "2026-08-05"},
    )
    current = read_order(env["order"]["id"])

    resp = api.create_shipment({
        "order_id": env["order"]["id"], "carrier_id": env["carrier"]["id"],
        "pickup_window_start": "2026-08-06T08:00:00Z",
        "pickup_window_end": "2026-08-06T18:00:00Z",
        "expected_order_version": current["version"],
    }, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_ALREADY_OPEN.value)

    assert read_shipment(env["shipment"]["id"])["status"] == "PACKED"
    assert len(_shipments_for_order(api, env["order"]["id"])) == 1


def test_dispatch_before_the_window_opens_is_refused(api):
    """PRD §3.5: "and the logical clock must lie inside the pickup window read
    as **half-open** — at or after `pickup_window_start` and strictly before
    `pickup_window_end` — with anything outside refused as
    `ERR_DISPATCH_WINDOW_NOT_OPEN` (HTTP 409)."
    PRD §2.4: "Before the clock is ever set, it reads exactly
    `2026-08-01T00:00:00Z`, and it never falls back to real time."

    Design: Corner/validations/dispatch_before_the_pickup_window_opens_is_refused
    """
    from test_helpers import setup_certified_shipment
    env = setup_certified_shipment(
        quantity=2, core_expected_count=0, model_preset="IB-AGM-95",
        lot_overrides={"manufactured_on": "2026-06-01", "quantity_on_hand": 30},
        order_overrides={"requested_ship_date": "2026-08-05"},
    )
    assert env["shipment"]["status"] == "CERTIFIED"

    resp = api.dispatch_shipment(env["shipment"]["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_DISPATCH_WINDOW_NOT_OPEN.value)

    shipment = read_shipment(env["shipment"]["id"])
    assert shipment["status"] == "CERTIFIED"
    assert shipment["dispatched_at"] is None
    assert read_order(env["order"]["id"])["fulfillment_status"] == "ALLOCATED"
