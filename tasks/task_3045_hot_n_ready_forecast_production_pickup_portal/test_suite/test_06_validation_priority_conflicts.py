"""Fixed validation precedence: state beats pickup-code checks; the PRD's
"Four preconditions are evaluated in order" pins the order-create pair."""

from test_helpers import (
    ApiErrorId,
    OrderKind,
    fixtures,
    factories,
    make_customer_headers,
    make_shift_lead_headers,
    validate_success,
    validate_error,
)


def _cancelled_portal_order(client, business_date="2026-09-18"):
    day = fixtures.open_store_day_with_active_daypart(
        client, business_date, "%sT11:00:00Z" % business_date
    )
    fixtures.create_locker_slot(client, day.store_day["id"], slot_number=1)
    product = fixtures.create_product(client)
    order = fixtures.paid_portal_order(
        client, day.store_day["id"], day.daypart["id"], "cust-4", product["id"]
    )
    cancelled = validate_success(
        client.cancel_order(order["id"], make_customer_headers("cust-4")), 200
    )
    assert cancelled["fulfillment_status"] == "CANCELLED"
    return order


def test_state_beats_temporal_on_claim_of_cancelled_order(client):
    """A claim on a CANCELLED order with a wrong code surfaces ERR_INVALID_STATE,
    never the pickup-code errors — state preconditions run before claim checks.

    "Only after every referenced resource exists does the server evaluate state
    preconditions (`ERR_INVALID_STATE` and the operation-specific state errors),
    then the posture gate on order preparation, then the business-safety rules in
    their defined sequence"
    "then the pickup-code checks on claims, then optimistic-concurrency version
    matching, then uniqueness, and finally field shape and range
    (`ERR_VALIDATION`)."
    "claiming an order that is not `READY` yields `ERR_INVALID_STATE`"

    Design: Difficulty/priority_pair_validation_conflict/state_existence_vs_business_temporal_on_claim
    """
    order = _cancelled_portal_order(client)

    resp = client.claim_order(
        order["id"], {"pickup_code": "000000"}, make_customer_headers("cust-4")
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_PICKUP_CODE_INVALID

    stored = fixtures.read_order(client, order["id"], customer_id="cust-4")
    assert stored["fulfillment_status"] == "CANCELLED"


def test_expired_code_still_invalid_state_when_order_not_ready(client):
    """Even a claim whose code would also fail the temporal check reports the
    state error first on a non-READY order.

    "claiming an order that is not `READY` yields `ERR_INVALID_STATE`"
    "then the pickup-code checks on claims"

    Design: Difficulty/priority_pair_validation_conflict/state_existence_vs_business_temporal_on_claim
    """
    order = _cancelled_portal_order(client)

    resp = client.claim_order(
        order["id"], {"pickup_code": "999999"}, make_customer_headers("cust-4")
    )
    error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert error["error_id"] == ApiErrorId.ERR_INVALID_STATE


def test_customization_checked_before_daypart_state_on_order_create(client):
    """A PORTAL_STANDARD order that is both customized on a locked product and
    aimed at a PLANNED daypart surfaces ERR_CUSTOMIZATION_NOT_ALLOWED: the
    customization rule runs before the placement daypart-status rule.

    "then the remaining business constraints (customization permission,
    order-placement daypart status, rack capacity, locker availability)"
    "Customization is the exception, not the rule: any line with `customized`
    set true must reference a product whose `customization_allowed` is true,
    otherwise placement is rejected with `ERR_CUSTOMIZATION_NOT_ALLOWED`."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_on_order_create
    """
    bundle = fixtures.planned_store_day(
        client,
        "2026-09-19",
        daypart_overrides={
            "label": "DINNER",
            "window_start_minute": 960,
            "window_end_minute": 1080,
        },
    )
    product = fixtures.create_product(client)  # customization_allowed defaults false

    resp = client.create_order(
        factories.order_payload(
            bundle.store_day["id"],
            bundle.daypart["id"],
            "cust-5",
            OrderKind.PORTAL_STANDARD,
            [factories.order_line(product["id"], quantity=1, customized=True)],
        ),
        make_customer_headers("cust-5"),
    )
    validate_error(resp, ApiErrorId.ERR_CUSTOMIZATION_NOT_ALLOWED)
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_DAYPART_NOT_ACTIVE


def test_daypart_state_violation_alone_surfaces_daypart_not_active(client):
    """Without the customization violation, the same PLANNED-daypart placement
    surfaces ERR_DAYPART_NOT_ACTIVE — the two rules are independently observable.

    "while `PORTAL_STANDARD` and `COUNTER` orders require the daypart to already
    be `ACTIVE` (otherwise `ERR_DAYPART_NOT_ACTIVE`)"

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_on_order_create
    """
    bundle = fixtures.planned_store_day(
        client,
        "2026-09-19",
        daypart_overrides={
            "label": "DINNER",
            "window_start_minute": 960,
            "window_end_minute": 1080,
        },
    )
    product = fixtures.create_product(client)

    resp = client.create_order(
        factories.order_payload(
            bundle.store_day["id"],
            bundle.daypart["id"],
            "cust-5",
            OrderKind.PORTAL_STANDARD,
            [factories.order_line(product["id"], quantity=1, customized=False)],
        ),
        make_customer_headers("cust-5"),
    )
    validate_error(resp, ApiErrorId.ERR_DAYPART_NOT_ACTIVE)
