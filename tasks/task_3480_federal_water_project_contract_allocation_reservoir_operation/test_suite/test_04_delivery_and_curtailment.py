"""Delivery orders against allocation lines and the revision curtailment.

Covers the remaining-balance formula, the fiscal gate at and above the
boundary, the quantity floor, the suspension gate (alone and in priority
over the fiscal check), unknown-contract and ownership rejections, terminal
delivery orders, the over-outstanding recording, and the depth-3 cascade in
which a revision publish demotes the newest over-committed orders - PRD
§2.8, §2.9, §3.1, §3.3 and §3.6.
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    RECLAMATION_OPERATOR_HEADERS,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
)

OPERATOR = RECLAMATION_OPERATOR_HEADERS


def test_revision_curtailment_cascade_depth3(api):
    """A revision publish recomputes the lines, demotes over-committed orders
    newest-first to SHORTED (preserving their recorded deliveries), and only
    then recomputes each line's remaining balance.

    PRD §3.3: "Then, per contract line, the over-commitment is measured as
    the line's `delivered_af` plus the summed outstanding quantities
    (`ordered_af` minus `delivered_af`) over that line's orders still in
    `CONFIRMED` or `PARTIALLY_DELIVERED`. While the over-commitment exceeds
    the line's `allocated_af` and active orders remain, the newest active
    order — latest `created_at`, ties broken by larger `ordered_af` — is
    demoted to `SHORTED`; a demoted order keeps the `delivered_af` already
    recorded against it, and its undelivered remainder simply stops
    reserving water. Only after all demotions does each line's
    `remaining_af` get recomputed."

    Design: Difficulty/transitive_cascade/revision_curtailment_cascade_depth3
    """
    world = fixtures.setup_announced_year(api)  # declared 7,500: SR 6,000 / JR 1,500
    first_announcement_id = world["announcement"]["id"]

    older = fixtures.create_delivery(api, world, side="jr", ordered_af=400)
    older = fixtures.record_delivery(api, older["id"], 200)
    assert older["fulfillment_status"] == "PARTIALLY_DELIVERED"

    fixtures.set_clock(api, "2027-01-16T00:00:00Z")
    newer = fixtures.create_delivery(api, world, side="jr", ordered_af=500)

    # Revision: runoff 4,000 observed 2027-01-20, published in January ->
    # declared 5,500 + round(4,000*80/100) - 2,000 = 6,700; junior line 700.
    revision = fixtures.publish_revision(api, world, runoff=4_000)
    assert revision["declared_supply_af"] == 6_700
    superseded = fixtures.find_announcement(api, world["year"]["id"], first_announcement_id)
    assert superseded["status"] == "SUPERSEDED"

    older_after = fixtures.get_delivery_order(api, older["id"])
    newer_after = fixtures.get_delivery_order(api, newer["id"])
    assert newer_after["fulfillment_status"] == "SHORTED", (
        "the newest active order is demoted first"
    )
    assert older_after["fulfillment_status"] == "PARTIALLY_DELIVERED"
    assert older_after["delivered_af"] == 200, "recorded deliveries survive the cascade"

    line_jr = world["line_jr"]
    assert line_jr["allocated_af"] == 700
    assert line_jr["delivered_af"] == 200, "carried forward from the superseded line"
    assert line_jr["remaining_af"] == 300, "700 - 200 delivered - 200 outstanding"

    line_sr = world["line_sr"]
    assert line_sr["allocated_af"] == 6_000
    assert line_sr["remaining_af"] == 6_000, "the senior line is untouched"


def test_delivery_gated_by_contract_status(api):
    """The same delivery-order payload is accepted while the contract is
    ACTIVE and rejected ERR_CONTRACT_SUSPENDED after suspension; the earlier
    order is untouched.

    PRD §3.1: "Suspension is deliberately narrow: existing delivery orders
    and in-flight transfers are not affected, and only the creation of new
    delivery orders and participation in new transfers is blocked — those
    creations surface the refusal as `ERR_CONTRACT_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/delivery_gated_by_contract_status
    """
    world = fixtures.setup_announced_year(api)

    created = fixtures.create_delivery(api, world, side="sr", ordered_af=100)
    assert created["fulfillment_status"] == "CONFIRMED"

    fixtures.suspend_contract(api, world["contract_sr"]["id"])

    validate_error(
        api.create_delivery_order(
            factories.delivery_order_payload(
                world["contract_sr"]["id"], world["year"]["id"], 100
            ),
            world["mgr_sr_headers"],
        ),
        ApiErrorId.ERR_CONTRACT_SUSPENDED,
    )

    untouched = fixtures.get_delivery_order(api, created["id"])
    assert untouched["fulfillment_status"] == "CONFIRMED"


def test_suspended_contract_beats_allocation_shortfall(api):
    """A delivery order on a SUSPENDED contract that would also exceed the
    line's remaining balance returns ERR_CONTRACT_SUSPENDED, never
    ERR_ALLOCATION_EXCEEDED: the state gate runs before the fiscal gate.

    PRD §2.9: "6. **State gates** — the target resource is in a valid state
    for the requested transition (`ERR_INVALID_STATE` and its more specific
    siblings `ERR_CONTRACT_SUSPENDED`, `ERR_YEAR_NOT_ANNOUNCED`,
    `ERR_YEAR_CLOSED`, `ERR_NO_PUBLISHED_ANNOUNCEMENT`,
    `ERR_REVISION_LIMIT_EXCEEDED`, and `ERR_COMPLIANCE_HOLD`)."
    PRD §2.9: "11. **Fiscal sufficiency** — the ordered or transferred
    quantity must fit within the resolved allocation line's remaining balance
    (`ERR_ALLOCATION_EXCEEDED`)."
    PRD §3.6: "the contract must not be `SUSPENDED` (else
    `ERR_CONTRACT_SUSPENDED`, and this contract check runs before the year
    check)"

    Design: Difficulty/priority_pair_validation_conflict/suspended_contract_beats_allocation_shortfall
    """
    world = fixtures.setup_announced_year(api)  # junior line remaining 1,500
    fixtures.suspend_contract(api, world["contract_jr"]["id"])

    response = api.create_delivery_order(
        factories.delivery_order_payload(world["contract_jr"]["id"], world["year"]["id"], 2_000),
        world["mgr_jr_headers"],
    )
    error = validate_error(response, ApiErrorId.ERR_CONTRACT_SUSPENDED)
    assert response.status_code == 409
    assert error["error_id"] != "ERR_ALLOCATION_EXCEEDED", (
        "2,000 af over the 1,500 remaining is masked by the earlier state gate"
    )

    orders, meta = validate_paginated(
        api.list_delivery_orders(fixtures.READ_HEADERS, {"contract_id": world["contract_jr"]["id"]})
    )
    assert meta["total_count"] == 0 and orders == []


def test_zero_quantity_delivery_rejected(api):
    """ordered_af == 0 is a 400 ERR_INVALID_QUANTITY domain error - it is not
    a fiscal overflow even though zero would fit any balance.

    PRD §3.6: "A `DistrictManager` places a delivery order with a
    `contract_id`, a `water_year_id`, and an `ordered_af` greater than zero —
    a non-positive quantity fails with `ERR_INVALID_QUANTITY`."

    Design: Difficulty/boundary_precision_check/zero_quantity_delivery_rejected
    """
    world = fixtures.setup_announced_year(api)

    response = api.create_delivery_order(
        factories.delivery_order_payload(world["contract_sr"]["id"], world["year"]["id"], 0),
        world["mgr_sr_headers"],
    )
    error = validate_error(response, ApiErrorId.ERR_INVALID_QUANTITY)
    assert response.status_code == 400
    assert error["error_id"] != "ERR_ALLOCATION_EXCEEDED"

    orders, meta = validate_paginated(
        api.list_delivery_orders(fixtures.READ_HEADERS, {"contract_id": world["contract_sr"]["id"]})
    )
    assert meta["total_count"] == 0 and orders == []


def test_allocation_line_remaining_recomputed_after_partial_delivery(api):
    """remaining_af nets the delivered part and the still-reserved part
    exactly once: 6,000 - 150 - (400 - 150) = 5,600.

    PRD §3.6: "A line's `remaining_af` is computed precisely: its
    `allocated_af` plus `transfer_in_af` minus `transfer_out_af` minus
    `delivered_af` minus the summed outstanding commitments — `ordered_af`
    minus `delivered_af` over every delivery order on the line in `CONFIRMED`
    or `PARTIALLY_DELIVERED` status."

    Design: Corner/entities/allocation_line_remaining_recomputed_after_partial_delivery
    """
    world = fixtures.setup_announced_year(api)
    order = fixtures.create_delivery(api, world, side="sr", ordered_af=400)

    order = fixtures.record_delivery(api, order["id"], 150)
    assert order["fulfillment_status"] == "PARTIALLY_DELIVERED"
    assert order["delivered_af"] == 150

    line = fixtures.find_line(api, world["announcement"]["id"], world["contract_sr"]["id"])
    assert line["allocated_af"] == 6_000, "delivery activity never rewrites the allocation"
    assert line["delivered_af"] == 150
    assert line["remaining_af"] == 5_600


def test_delivery_create_with_unknown_contract_returns_not_found(api):
    """Body foreign keys resolve in declared input order: an unknown
    contract_id is a 404 even when the year exists.

    PRD §2.8: "Only after every path identifier resolves does the server
    resolve foreign-key identifiers supplied in the request body, and it does
    so in the endpoint's declared input order, rejecting the first unresolved
    one with `ERR_NOT_FOUND` in the same way."

    Design: Corner/validations/delivery_create_with_unknown_contract_returns_not_found
    """
    world = fixtures.setup_announced_year(api)

    validate_error(
        api.create_delivery_order(
            factories.delivery_order_payload(NON_EXISTENT_UUID, world["year"]["id"], 10),
            world["mgr_sr_headers"],
        ),
        ApiErrorId.ERR_NOT_FOUND,
    )

    orders, meta = validate_paginated(
        api.list_delivery_orders(fixtures.READ_HEADERS, {"water_year_id": world["year"]["id"]})
    )
    assert meta["total_count"] == 0 and orders == []


def test_delivery_over_remaining_returns_allocation_exceeded(api):
    """Ordering 1,501 af against a 1,500 af remaining balance fails 422
    ERR_ALLOCATION_EXCEEDED, while exactly 1,500 succeeds and drains the line.

    PRD §3.6: "The fiscal gate follows: `ordered_af` must not exceed the
    resolved line's `remaining_af`, else `ERR_ALLOCATION_EXCEEDED`."

    Design: Corner/validations/delivery_over_remaining_returns_allocation_exceeded
    """
    world = fixtures.setup_announced_year(api)  # junior line allocated 1,500

    validate_error(
        api.create_delivery_order(
            factories.delivery_order_payload(world["contract_jr"]["id"], world["year"]["id"], 1_501),
            world["mgr_jr_headers"],
        ),
        ApiErrorId.ERR_ALLOCATION_EXCEEDED,
    )

    exact = fixtures.create_delivery(api, world, side="jr", ordered_af=1_500)
    assert exact["fulfillment_status"] == "CONFIRMED"

    line = fixtures.find_line(api, world["announcement"]["id"], world["contract_jr"]["id"])
    assert line["remaining_af"] == 0, "the exact-fill order drains the line"


def test_record_delivery_over_outstanding_returns_invalid_quantity(api):
    """A recording above the outstanding balance (ordered 400, delivered 150,
    then 300) fails 400 ERR_INVALID_QUANTITY; exactly the outstanding 250
    succeeds and completes the order.

    PRD §3.6: "The amount must be greater than zero and no more than the
    order's outstanding quantity — `ordered_af` minus the `delivered_af`
    already recorded — otherwise `ERR_INVALID_QUANTITY`."

    Design: Corner/validations/record_delivery_over_outstanding_returns_invalid_quantity
    """
    world = fixtures.setup_announced_year(api)
    order = fixtures.create_delivery(api, world, side="sr", ordered_af=400)
    fixtures.record_delivery(api, order["id"], 150)

    validate_error(
        api.record_delivery(order["id"], factories.record_delivery_payload(300), OPERATOR),
        ApiErrorId.ERR_INVALID_QUANTITY,
    )

    completed = fixtures.record_delivery(api, order["id"], 250)
    assert completed["fulfillment_status"] == "DELIVERED"
    assert completed["delivered_af"] == 400


def test_record_delivery_on_delivered_order_returns_invalid_state(api):
    """A fully-delivered order is terminal for record-delivery: the repeat
    call fails 409 ERR_INVALID_STATE and delivered_af does not drift.

    PRD §3.6: "recording against a `DELIVERED` or `SHORTED` order fails with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/record_delivery_on_delivered_order_returns_invalid_state
    """
    world = fixtures.setup_announced_year(api)
    order = fixtures.create_delivery(api, world, side="sr", ordered_af=100)
    order = fixtures.record_delivery(api, order["id"], 100)
    assert order["fulfillment_status"] == "DELIVERED"

    validate_error(
        api.record_delivery(order["id"], factories.record_delivery_payload(1), OPERATOR),
        ApiErrorId.ERR_INVALID_STATE,
    )

    after = fixtures.get_delivery_order(api, order["id"])
    assert after["delivered_af"] == 100


def test_district_manager_cannot_order_against_other_districts_contract(api):
    """DistrictManager identity is entity-backed: the junior district's
    manager ordering against the senior district's contract fails 403
    ERR_OWNERSHIP_MISMATCH.

    PRD §3.6: "The caller must own the contract: their `X-User-ID` must equal
    the contract's `district_id`, else `ERR_OWNERSHIP_MISMATCH`."
    PRD §2.1: "When `X-User-Role` is `DistrictManager`, `X-User-ID` is the
    `id` of the acting District; ownership checks on any resource that
    references a district — a contract's `district_id`, an impact review's
    `reviewer_district_id`, a shortage agreement's signatory list — compare
    the resource's district foreign key to `X-User-ID`."

    Design: Corner/rbac/district_manager_cannot_order_against_other_districts_contract
    """
    world = fixtures.setup_announced_year(api)

    validate_error(
        api.create_delivery_order(
            factories.delivery_order_payload(world["contract_sr"]["id"], world["year"]["id"], 10),
            world["mgr_jr_headers"],
        ),
        ApiErrorId.ERR_OWNERSHIP_MISMATCH,
    )

    orders, meta = validate_paginated(
        api.list_delivery_orders(fixtures.READ_HEADERS, {"contract_id": world["contract_sr"]["id"]})
    )
    assert meta["total_count"] == 0 and orders == []
