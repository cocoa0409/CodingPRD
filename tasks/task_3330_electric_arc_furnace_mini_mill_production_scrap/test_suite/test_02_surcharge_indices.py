"""Surcharge index supersede corner (PRD §3.1)."""
from test_helpers import (
    api_client, TEST_USERS, validate_success, validate_paginated,
    assert_surcharge_index, make_mill, publish_index, get_mill,
)

PM = TEST_USERS["plant_manager_headers"]


def test_surcharge_index_supersede_flips_prior_row():
    """PRD §3.1: "at most one row per (mill, grade category, month) key is `PUBLISHED`
    at any moment, and publishing a new row for an already-published key automatically
    flips the prior row to `SUPERSEDED`."

    Design: Corner/entities/surcharge_index_supersede_flips_prior_row
    """
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    first = publish_index(
        mill["id"], grade_category="SHREDDED", effective_month="2026-09",
        price_per_ton_cents=38000,
    )
    second = publish_index(
        mill["id"], grade_category="SHREDDED", effective_month="2026-09",
        price_per_ton_cents=38500,
    )
    assert_surcharge_index(second)
    assert second["status"] == "PUBLISHED"
    assert second["price_per_ton_cents"] == 38500

    rows, _meta = validate_paginated(api_client.list_indices(mill["id"], PM))
    by_id = {row["id"]: row for row in rows}
    assert by_id[first["id"]]["status"] == "SUPERSEDED"
    assert by_id[second["id"]]["status"] == "PUBLISHED"

    published_rows = [r for r in rows if r["status"] == "PUBLISHED"
                      and r["grade_category"] == "SHREDDED"
                      and r["effective_month"] == "2026-09"]
    assert [r["id"] for r in published_rows] == [second["id"]]
