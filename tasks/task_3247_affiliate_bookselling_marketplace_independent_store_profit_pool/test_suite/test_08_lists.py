"""List lifecycle and list-attribution consistency."""
from test_helpers import (
    ADMIN,
    FINANCE,
    ApiErrorId,
    create_active_partner,
    create_active_store,
    create_list_for_store,
    create_order,
    get_success_data,
    make_customer_headers,
    make_store_manager_headers,
    publish_list,
    set_clock,
    setup_catalog_and_store,
    validate_error,
    validate_success,
)


def test_booklist_publish_unpublish_republish_cycle_increments_publish_count(api):
    """PRD §3.3: "A published list can be unpublished back to `DRAFT` — it then
    attributes no new orders, though existing orders keep their recorded
    `source_list_id` — and re-publishing from `DRAFT` counts as another
    publish."
    PRD §3.3: "publishing increments the list's `publish_count` and makes the
    list eligible to drive order attribution."

    Design: Difficulty/non_linear_state_machine/booklist_publish_unpublish_republish_cycle_increments_publish_count
    """
    set_clock("2026-09-01T00:00:00Z")
    _publisher, book, store = setup_catalog_and_store(
        publisher_overrides={
            "name": "List Press",
            "discount_pct": 0.40,
            "returns_allowed": False,
            "return_window_days": 0,
            "return_credit_pct": 0.0,
        },
        book_overrides={
            "isbn": "9780000000020",
            "title": "Listable",
            "list_price_cents": 5000,
        },
    )
    lst = create_list_for_store(store["id"], book_id=book["id"], title="Staff Picks")
    mgr = make_store_manager_headers(store["id"])

    publish_list(lst["id"], store["id"])
    unpublished = get_success_data(
        api.list_action(lst["id"], {"action": "unpublish"}, mgr)
    )
    assert unpublished["status"] == "DRAFT"

    republished = get_success_data(
        api.list_action(lst["id"], {"action": "publish"}, mgr)
    )
    assert republished["status"] == "PUBLISHED"
    assert republished["publish_count"] == 2


def test_unpublished_list_no_longer_attributes_new_orders(api):
    """PRD §3.3: "A published list can be unpublished back to `DRAFT` — it then
    attributes no new orders, though existing orders keep their recorded
    `source_list_id` — and re-publishing from `DRAFT` counts as another
    publish."
    PRD §3.4: "A source list, when present, must be `PUBLISHED`, must be owned
    by the attributed store, and implies store attribution — a `source_list_id`
    on a partner-attributed order is contradictory and rejected with
    `ERR_LIST_ATTRIBUTION_MISMATCH` (HTTP 422), as is a list that is unpublished
    or owned by a different store."

    Design: Difficulty/non_linear_state_machine/booklist_publish_unpublish_republish_cycle_increments_publish_count
    """
    set_clock("2026-09-01T00:00:00Z")
    _publisher, book, store = setup_catalog_and_store(
        publisher_overrides={
            "name": "List Press",
            "discount_pct": 0.40,
            "returns_allowed": False,
            "return_window_days": 0,
            "return_credit_pct": 0.0,
        },
        book_overrides={
            "isbn": "9780000000020",
            "title": "Listable",
            "list_price_cents": 5000,
        },
    )
    lst = create_list_for_store(store["id"], book_id=book["id"], title="Staff Picks")
    mgr = make_store_manager_headers(store["id"])
    publish_list(lst["id"], store["id"])

    # While PUBLISHED the list attributes an order.
    cust = make_customer_headers("cust-l")
    resp = api.create_order(
        {
            "customer_id": "cust-l",
            "attributed_store_id": store["id"],
            "source_list_id": lst["id"],
            "lines": [{"book_id": book["id"], "quantity": 1}],
        },
        cust,
    )
    order = validate_success(resp, expected_status=201)
    assert order["source_list_id"] == lst["id"]

    get_success_data(api.list_action(lst["id"], {"action": "unpublish"}, mgr))
    # Back in DRAFT the same attribution is rejected.
    resp = api.create_order(
        {
            "customer_id": "cust-l",
            "attributed_store_id": store["id"],
            "source_list_id": lst["id"],
            "lines": [{"book_id": book["id"], "quantity": 1}],
        },
        cust,
    )
    validate_error(resp, ApiErrorId.ERR_LIST_ATTRIBUTION_MISMATCH, expected_status=422)


def test_list_archive_is_terminal(api):
    """PRD §3.3: "Archiving is terminal and reachable from either `DRAFT` or
    `PUBLISHED`; an `ARCHIVED` list preserves its items read-only."
    PRD §2.11: "Only then are state-machine preconditions checked
    (`ERR_INVALID_STATE`, HTTP 409)"

    Design: Corner/state_machines/list_archive_is_terminal
    """
    set_clock("2026-09-01T00:00:00Z")
    _publisher, book, store = setup_catalog_and_store()
    lst = create_list_for_store(store["id"], book_id=book["id"], title="Archived Picks")
    mgr = make_store_manager_headers(store["id"])
    get_success_data(api.list_action(lst["id"], {"action": "archive"}, mgr))

    for action in ("publish", "unpublish"):
        resp = api.list_action(lst["id"], {"action": action}, mgr)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_err_list_not_publishable_on_empty_list(api):
    """PRD §3.3: "Publishing requires a non-empty list (an empty publish attempt
    fails with `ERR_LIST_NOT_PUBLISHABLE`, HTTP 422) and an owning store whose
    status is `ACTIVE`"

    Design: Corner/errors/err_list_not_publishable_on_empty_list
    """
    set_clock("2026-09-01T00:00:00Z")
    store = create_active_store(
        shop_name="State Books",
        slug="state-books",
        commission_pct=0.30,
        payout_threshold_cents=20000,
    )
    lst = create_list_for_store(store["id"], items=[], title="Empty Picks")
    resp = api.list_action(
        lst["id"], {"action": "publish"}, make_store_manager_headers(store["id"])
    )
    validate_error(resp, ApiErrorId.ERR_LIST_NOT_PUBLISHABLE, expected_status=422)


def test_list_attribution_requires_published_and_owned(api):
    """PRD §3.4: "A source list, when present, must be `PUBLISHED`, must be
    owned by the attributed store, and implies store attribution — a
    `source_list_id` on a partner-attributed order is contradictory and rejected
    with `ERR_LIST_ATTRIBUTION_MISMATCH` (HTTP 422), as is a list that is
    unpublished or owned by a different store."

    Design: Corner/validations/list_attribution_requires_published_and_owned
    """
    set_clock("2026-09-01T00:00:00Z")
    _publisher, book, store_a = setup_catalog_and_store()
    store_b = create_active_store(
        shop_name="Other Books", slug="other-books", commission_pct=0.20
    )
    draft_list = create_list_for_store(
        store_a["id"], book_id=book["id"], title="Archived Picks"
    )
    list_b = create_list_for_store(store_b["id"], book_id=book["id"], title="Other Picks")
    publish_list(list_b["id"], store_b["id"])
    partner = create_active_partner(
        display_name="Terminal Author", partner_kind="AUTHOR", commission_pct=0.10
    )

    cust = make_customer_headers("cust-c4")
    cases = [
        # (a) list is DRAFT
        {"attributed_store_id": store_a["id"], "source_list_id": draft_list["id"]},
        # (b) PUBLISHED but owned by a different store
        {"attributed_store_id": store_a["id"], "source_list_id": list_b["id"]},
        # (c) partner-attributed order carrying any source_list_id
        {"attributed_partner_id": partner["id"], "source_list_id": list_b["id"]},
    ]
    for extra in cases:
        payload = {
            "customer_id": "cust-c4",
            "lines": [{"book_id": book["id"], "quantity": 1}],
        }
        payload.update(extra)
        resp = api.create_order(payload, cust)
        validate_error(
            resp, ApiErrorId.ERR_LIST_ATTRIBUTION_MISMATCH, expected_status=422
        )
