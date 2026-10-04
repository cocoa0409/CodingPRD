"""List endpoint pagination envelope."""
import test_helpers as th


def test_list_operators_paginates_with_envelope(api, admin_headers, finance_headers):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return; when omitted it defaults to 10, with a minimum accepted value of
    1 and a maximum of 100. The `offset` parameter specifies how many items to
    skip and defaults to 0. List responses are sorted by the resources'
    creation timestamps in ascending order. Paginated list responses carry
    `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of
    the envelope."

    Design: Corner/endpoints/list_operators_paginates_with_envelope
    """
    for name in ("List Op A", "List Op B", "List Op C"):
        th.create_operator(legal_name=name, fy_net_worth_cents=1_000_000,
                           fy_operating_income_cents=100_000)

    rows, meta = th.validate_paginated(api.list_operators(finance_headers, params={"limit": 2, "offset": 0}))
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    rows, meta = th.validate_paginated(api.list_operators(finance_headers, params={"limit": 2, "offset": 2}))
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    rows, meta = th.validate_paginated(api.list_operators(finance_headers))
    assert len(rows) == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
