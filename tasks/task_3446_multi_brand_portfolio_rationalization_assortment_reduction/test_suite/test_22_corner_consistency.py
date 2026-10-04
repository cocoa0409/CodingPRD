"""Corner queue: consistency-model claim — a mutation is visible on the very
next read within the same request cycle.
"""
from test_helpers import (
    CLOCK_START_ISO_MILLIS,
    TEST_USERS,
    api_client,
    assert_brand,
    create_brand_payload,
    validate_created,
    validate_paginated,
)

PM = TEST_USERS["portfolio_manager_headers"]


def test_post_then_get_immediately_reflects_mutation():
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §2.5: "`version` (an integer that starts at 1 and increments by exactly
    1 on every mutation of that resource, including mutations performed as side
    effects of operations on other resources)".
    PRD §2.4: "At startup, before any clock-setting call has been made, the
    logical clock reads exactly 2026-09-01T00:00:00Z".

    Design: Corner/consistency_model/post_then_get_immediately_reflects_mutation
    """
    created = validate_created(
        api_client.create_brand(create_brand_payload(name="B-CM1"), PM)
    )
    brands, meta = validate_paginated(api_client.list_brands(PM))
    assert meta["total_count"] == 1
    assert brands[0]["id"] == created["id"], (
        "a created brand must be visible in the very next list read"
    )
    assert_brand(brands[0])
    assert brands[0]["version"] == 1
    assert brands[0]["created_at"] == CLOCK_START_ISO_MILLIS, (
        f"created_at must be stamped from the logical clock default "
        f"2026-09-01T00:00:00.000Z, got {brands[0]['created_at']}"
    )
