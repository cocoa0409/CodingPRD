"""List endpoints: pagination envelope defaults and filter scoping (PRD §2.2, §2.3, §4)."""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import PROGRAM_MANAGER_HEADERS, order_line
from test_helpers import fixtures


def test_orders_list_pagination_defaults_and_envelope(api):
    """An unparameterized list applies the declared defaults and reports the
    four pagination fields.

    PRD §2.3: "The `limit` parameter sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "The `offset` parameter sets how many items to skip and defaults to 0."
    PRD §2.3: "List responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."
    Design: Corner/endpoints/orders_list_pagination_defaults_and_envelope
    """
    world = fixtures.setup_active_program(api)
    fixtures.place_order(api, world["account"], world["program"])
    fixtures.place_order(
        api, world["account"], world["program"],
        jobsite_address="2 Job Ln", lines=[order_line(quantity=2)],
    )

    resp = api.list_orders(PROGRAM_MANAGER_HEADERS, params={"account_id": world["account"]["id"]})
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2


def test_orders_filtered_list_returns_only_matching_account(api):
    """The account_id filter scopes the listing to that account's orders.

    PRD §4: "List orders; optional account_id/program_id/design_job_id/status filters; paginated"
    Design: Corner/endpoints/orders_filtered_list_returns_only_matching_account
    """
    fixtures.reset_clock(api)
    account_a = fixtures.create_account(api, name="Dealer A")
    account_b = fixtures.create_account(api, name="Dealer B")
    program_a = fixtures.create_program(api, account_a["id"], name="PA")
    fixtures.create_first_line(api, program_a["id"])
    fixtures.activate_program(api, program_a["id"])
    program_b = fixtures.create_program(api, account_b["id"], name="PB")
    fixtures.create_first_line(api, program_b["id"])
    fixtures.activate_program(api, program_b["id"])

    fixtures.place_order(api, account_a, program_a)
    fixtures.place_order(api, account_a, program_a, jobsite_address="2 Job Ln",
                         lines=[order_line(quantity=2)])
    order_b = fixtures.place_order(api, account_b, program_b, jobsite_address="3 Job Ln",
                                   lines=[order_line(quantity=3)])

    data, meta = validate_paginated(
        api.list_orders(PROGRAM_MANAGER_HEADERS, params={"account_id": account_a["id"]})
    )
    assert meta["total_count"] == 2
    assert len(data) == 2
    assert all(order["account_id"] == account_a["id"] for order in data)
    assert order_b["id"] not in {order["id"] for order in data}
