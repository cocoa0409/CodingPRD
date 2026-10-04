"""Cross-cutting corners: the optimistic-concurrency parent version is
observable across a creation, and mutations are visible both in the mutating
response and in an immediate read-back.
"""

from test_helpers import (
    TEST_USERS,
    create_quote,
    read_product,
    setup_decided_review_with_slot,
    setup_sourcing_product,
    validate_success,
)

_PLANNER = TEST_USERS["retail_planner_headers"]


def test_quote_create_bumps_product_version_observably(api):
    """PRD §2.7: "Both creations advance the parent's `version` by one as part
    of their side effects, which is exactly what makes a second creation
    carrying an older observed version stale."
    The product reads version 2 after the SOURCING transition (created at 1);
    a successful quote creation against expected_product_version == 2 advances
    it to 3.

    Design: Corner/cross_cutting/quote_create_bumps_product_version_observably
    """
    ctx = setup_sourcing_product()

    before = read_product(ctx["product"]["id"])["version"]
    assert before == 2

    create_quote(
        ctx["product"]["id"],
        ctx["manufacturer"]["id"],
        expected_product_version=before,
    )

    after = read_product(ctx["product"]["id"])["version"]
    assert after == before + 1


def test_mutations_are_visible_in_the_same_request_and_immediately_after(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.7: "A successful commit stamps `committed_at` — the eviction
    ordering key of §3.7's capacity revision rule — and recomputes the
    partner's facing availability."
    The commit response itself carries COMMITTED + committed_at + version 2,
    and the directly following GET returns byte-identical derived state.

    Design: Corner/consistency_model/mutations_are_visible_in_the_same_request_and_immediately_after
    """
    ctx = setup_decided_review_with_slot()

    response = api.patch_planogram_slot(ctx["slot"]["id"], {"status": "COMMITTED"}, _PLANNER)

    committed = validate_success(response)
    assert committed["status"] == "COMMITTED"
    assert committed["committed_at"] == "2026-10-21T00:00:00Z"
    assert committed["version"] == 2

    reread = validate_success(api.get_planogram_slot(ctx["slot"]["id"], _PLANNER))
    assert reread["status"] == committed["status"]
    assert reread["committed_at"] == committed["committed_at"]
    assert reread["version"] == committed["version"]
