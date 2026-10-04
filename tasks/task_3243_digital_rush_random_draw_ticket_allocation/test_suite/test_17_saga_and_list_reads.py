"""The refund saga's compensating no-op and the purchase list's paging."""
import pytest

from test_helpers import (
    validate_paginated, validate_success, get_success_data,
)
from test_helpers import constants as C
from test_helpers import fixtures as X


def test_rejecting_a_refund_leaves_every_purchase_figure_untouched(api):
    """PRD §3.9: "Rejection is deliberately a no-op on the purchase: no purchase
    field changes and the rejection is the compensating act of refusing; the
    purchase's `version` still advances by one, because the workflow itself
    moved."

    Design: Corner/consistency_model/saga_refund_rejection_leaves_the_purchase_untouched
    """
    production, performance, allocation, patron, purchase = \
        X.setup_settled_then_sold_out(quantity=2, daily_quantity=6)

    refund = X.open_refund(purchase, patron)
    approved = X.approve_refund(refund, purchase)
    before = X.get_purchase(purchase["id"])

    rejected = X.approve_refund(approved, before, decision="REJECT")

    assert rejected["status"] == "REJECTED", (
        f"the operator's decision names the outcome, got {rejected['status']}"
    )
    after = X.get_purchase(purchase["id"])
    assert after["refunded_cents"] == 0, (
        f"no money had moved, so nothing is reversed, got {after['refunded_cents']}"
    )
    assert after["payment_status"] == "SETTLED", (
        "the payment posture is the same value the approval step observed, got "
        f"{after['payment_status']}"
    )


def test_rejection_leaves_the_seat_accounting_at_its_pre_request_value(api):
    """PRD §2.6: "the refund postures evaluation rejects the request."
    PRD §3.9: "no purchase field changes; the rejection is the compensating act of
    refusing; the purchase's `version` still advances by one, because the workflow
    itself moved."
    PRD §3.9: "the rejection leaves no purchase field changed while still
    advancing the purchase's `version` by one."

    Design: Corner/consistency_model/saga_refund_rejection_leaves_the_purchase_untouched
    """
    production, performance, allocation, patron, purchase = \
        X.setup_settled_then_sold_out(quantity=2, daily_quantity=6)
    sold_before = X.get_allocation(performance, allocation["id"])["quantity_sold_today"]

    refund = X.open_refund(purchase, patron)
    approved = X.approve_refund(refund, purchase)
    X.approve_refund(approved, X.get_purchase(purchase["id"]), decision="REJECT")

    final = X.get_allocation(performance, allocation["id"])
    assert final["quantity_sold_today"] == sold_before, (
        "the rejection left the seat accounting at its pre-request value, got "
        f"{final['quantity_sold_today']} against {sold_before}"
    )


def test_a_purchase_list_pages_while_its_filter_holds(api):
    """PRD §2.3: "`limit` defaults to 10, may be no smaller than 1 and no larger
    than 100, and a value outside that band is refused rather than silently
    clamped."
    PRD §2.3: "Four pagination fields are reported in the `meta` object of a list
    response: `limit` and `offset` echo the request, `total_count` reports the
    number of resources matching the filter before paging, and `has_more` is a
    boolean that tells the caller whether further pages remain."

    Design: Corner/validations/purchase_list_filters_interact_with_pagination
    """
    production, performance, allocation, pairs = X.setup_two_settled_orders()

    first_page = api.list_purchases(
        X.PRODUCER,
        params={"performance_id": performance["id"], "limit": 1, "offset": 0})
    rows, meta = validate_paginated(first_page)

    assert len(rows) == 1, f"the first page carries exactly one row, got {len(rows)}"
    assert meta["total_count"] == 2, f"the filtered set holds two orders, got {meta['total_count']}"
    assert meta["has_more"] is True, "a further page remains"
    assert meta["limit"] == 1 and meta["offset"] == 0, \
        "the reported paging fields echo the request"


def test_the_second_page_walks_the_same_ordered_set(api):
    """PRD §2.3: "Collections are ordered by `created_at` ascending unless the
    endpoint's own description states otherwise, so that paging with `offset`
    walks the set in a stable sequence."

    Design: Corner/validations/purchase_list_filters_interact_with_pagination
    """
    production, performance, allocation, pairs = X.setup_two_settled_orders()

    first_rows, first_meta = validate_paginated(api.list_purchases(
        X.PRODUCER,
        params={"performance_id": performance["id"], "limit": 1, "offset": 0}))
    second_rows, second_meta = validate_paginated(api.list_purchases(
        X.PRODUCER,
        params={"performance_id": performance["id"], "limit": 1, "offset": 1}))

    assert len(second_rows) == 1
    assert second_meta["total_count"] == 2
    assert second_meta["has_more"] is False, "the second page is the last"
    assert first_rows[0]["id"] != second_rows[0]["id"], (
        "the two pages return different rows: "
        f"{first_rows[0]['id']} and {second_rows[0]['id']}"
    )


def test_a_status_filter_narrows_the_whole_paged_set(api):
    """PRD §2.3: "Filters are always optional query parameters and are combined
    conjunctively: supplying `patron_id` and `status` to a collection read narrows
    to rows that satisfy both."
    PRD §2.3: "A filter naming a value the system does not recognise returns an
    empty collection rather than an error, because a filter is a narrowing device
    and not a validating one."

    Design: Corner/validations/purchase_list_filters_interact_with_pagination
    """
    production, performance, allocation, pairs = X.setup_two_settled_orders()

    settled_rows, settled_meta = validate_paginated(api.list_purchases(
        X.PRODUCER,
        params={"performance_id": performance["id"],
                "payment_status": "SETTLED", "limit": 100}))
    assert settled_meta["total_count"] == 2, (
        f"both settled orders match the filter, got {settled_meta['total_count']}"
    )

    pending_rows, pending_meta = validate_paginated(api.list_purchases(
        X.PRODUCER,
        params={"performance_id": performance["id"],
                "payment_status": "PENDING", "limit": 100}))
    assert pending_meta["total_count"] == 0, (
        f"the whole filtered set is empty of pending orders, got {pending_meta['total_count']}"
    )
    assert pending_rows == []