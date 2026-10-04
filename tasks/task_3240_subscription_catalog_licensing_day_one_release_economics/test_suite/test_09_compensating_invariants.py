"""Compensating actions conserve the quantity they are defined over.

A revoke followed by its restore returns the entitlement census to its
pre-revoke value, and a purchase followed by its reversal returns the
subscriber's wallet credit to the balance they held before the purchase.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    create_entry,
    create_projection,
    list_entitlements,
    make_subscriber_headers,
    publish_entry,
    scenario_ready_to_purchase,
    scenario_with_subscriber,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]

BACK_CATALOG_ENTRY = {
    "removal_date": "2026-12-30T00:00:00Z",
    "release_class": "BACK_CATALOG",
    "popularity_index_cents": 4000,
    "popularity_index_cents_30d_avg": 4000,
}


def _active_census(api, subscription_id):
    rows = list_entitlements(api, subscription_id=subscription_id)
    return sum(1 for row in rows if row["status"] == "ACTIVE"), rows


def test_revoke_and_restore_conserve_the_active_entitlement_census(api):
    """PRD §3.4: "The compensating action restores a `REVOKED` entitlement to
    `ACTIVE`, recomputing its `access_channels` from the tier flags and
    restoring `subscriber_impact_count` to its pre-revocation value, but only
    while two conditions hold: the subscription's `lifecycle_status` must not be
    `CANCELLED`, and the entitlement's entry must still be readable".
    PRD §3.4: "a successful revocation recomputes the related entry's
    `subscriber_impact_count`."

    Design: Difficulty/compensating_invariant/revoke_restore_conserves_the_entitlement_census
    """
    sc = scenario_with_subscriber(api)

    census_before, rows = _active_census(api, sc.subscription["id"])
    assert census_before == 1, \
        "PRD §2.8 fixes one entitlement row per (subscription, title, region) " \
        "triple, so the single published entry resolves exactly one ACTIVE row"
    assert len(rows) == 1

    entitlement_id = rows[0]["id"]

    revoked = validate_success(api.revoke_entitlement(entitlement_id, ADMIN))
    assert revoked["status"] == "REVOKED"
    assert revoked["entry_id"] is not None, "entry_id is kept for audit"

    after_revoke = validate_success(api.get_catalog_entry(sc.entry["id"], ADMIN))
    assert after_revoke["subscriber_impact_count"] == 0

    restored = validate_success(api.restore_entitlement(entitlement_id, ADMIN))
    assert restored["status"] == "ACTIVE"

    after_restore = validate_success(api.get_catalog_entry(sc.entry["id"], ADMIN))
    assert after_restore["subscriber_impact_count"] == 1, \
        "subscriber_impact_count is back to its pre-revocation value"


def test_the_revoke_restore_pair_neither_creates_nor_deletes_any_row(api):
    """PRD §3.4: "An entitlement's own lifecycle is `ACTIVE`, `GRACE` or `REVOKED`, with `REVOKED` terminal apart from a single compensating path."

    Design: Difficulty/compensating_invariant/revoke_restore_conserves_the_entitlement_census
    """
    sc = scenario_with_subscriber(api)

    rows_before = list_entitlements(api, subscription_id=sc.subscription["id"])
    assert len(rows_before) == 1, \
        "the (subscription, title, region) triple carries a single row (PRD §2.8)"

    entitlement_id = rows_before[0]["id"]

    validate_success(api.revoke_entitlement(entitlement_id, ADMIN))
    validate_success(api.restore_entitlement(entitlement_id, ADMIN))

    census_after, rows_after = _active_census(api, sc.subscription["id"])
    assert census_after == 1, "the census term is back to its pre-revoke value"
    assert len(rows_after) == 1, "the pair created and deleted nothing"

    revoking_twice = validate_success(api.revoke_entitlement(entitlement_id, ADMIN))
    assert revoking_twice["status"] == "REVOKED"
    validate_error(api.revoke_entitlement(entitlement_id, ADMIN),
                   "ERR_ENTITLEMENT_ALREADY_REVOKED")


def test_purchase_and_reversal_conserve_the_subscribers_wallet_credit(api):
    """PRD §2.9: "when a purchase consumes part of a subscriber's
    `wallet_credit_cents`, that amount is recorded on the row as
    `wallet_applied_cents` and remains recorded there even after the purchase is
    reversed, so that the sum of the subscriber's live balance and the retained
    `wallet_applied_cents` across reversed rows reconciles."
    PRD §3.8: "Reversal ... increases the subscriber's `wallet_credit_cents` by
    the retained `wallet_applied_cents`".

    Design: Difficulty/compensating_invariant/purchase_and_reversal_conserve_subscriber_currency
    """
    sc = scenario_ready_to_purchase(api, wallet_credit_cents=1000)

    purchase = validate_success(
        api.create_purchase(
            {
                "subscriber_id": sc.subscriber["id"],
                "title_id": sc.title["id"],
                "entry_id": sc.entry["id"],
                "region_code": sc.region_code,
                "quantity": 1,
            },
            make_subscriber_headers(sc.subscriber["id"]),
        ),
        expected_status=201,
    )

    # 8400.00 list less the 630.00 rounded PREMIUM discount is 7770.00, and the
    # wallet credit is the smaller of 1000.00 and that subtotal.
    assert purchase["list_price_cents_per_unit"] == pytest.approx(8400.00, abs=0.01)
    assert purchase["wallet_applied_cents"] == 1000
    assert purchase["total_charged_cents"] == pytest.approx(6770.00, abs=0.01)
    assert purchase["status"] == "COMPLETED"
    assert purchase["wallet_restored_cents"] == 0

    after_purchase = validate_success(api.get_subscriber(sc.subscriber["id"], ADMIN))
    assert after_purchase["wallet_credit_cents"] == 0
    assert after_purchase["wallet_credit_cents"] + purchase["wallet_applied_cents"] == 1000, \
        "the conserved quantity is unchanged from the seed"

    reversed_purchase = validate_success(api.reverse_purchase(purchase["id"], ADMIN))
    assert reversed_purchase["status"] == "REFUNDED"
    assert reversed_purchase["wallet_restored_cents"] == 1000
    assert reversed_purchase["wallet_applied_cents"] == 1000, \
        "the retained offset stays on the row for audit"

    after_reversal = validate_success(api.get_subscriber(sc.subscriber["id"], ADMIN))
    assert after_reversal["wallet_credit_cents"] == 1000, \
        "the credit returned by the reversal restores the original balance"


def test_a_reversed_purchase_leaves_the_accumulator_and_cannot_be_reversed_twice(api):
    """PRD §3.9: "`REFUNDED` rows are excluded, so a reversed purchase drops out
    of the accumulator."
    PRD §3.8: "a second reversal of an already-`REFUNDED` row is rejected with
    `ERR_PURCHASE_ALREADY_REVERSED`."
    PRD §3.8: "The row is never deleted."

    Design: Difficulty/compensating_invariant/purchase_and_reversal_conserve_subscriber_currency
    """
    sc = scenario_ready_to_purchase(
        api, wallet_credit_cents=1000,
        entry_overrides=dict(BACK_CATALOG_ENTRY),
    )

    purchase = validate_success(
        api.create_purchase(
            {
                "subscriber_id": sc.subscriber["id"],
                "title_id": sc.title["id"],
                "entry_id": sc.entry["id"],
                "region_code": sc.region_code,
                "quantity": 1,
            },
            make_subscriber_headers(sc.subscriber["id"]),
        ),
        expected_status=201,
    )
    validate_success(api.reverse_purchase(purchase["id"], ADMIN))
    validate_error(api.reverse_purchase(purchase["id"], ADMIN),
                   "ERR_PURCHASE_ALREADY_REVERSED")

    rows, meta = validate_paginated(
        api.list_purchases(ADMIN, params={"subscriber_id": sc.subscriber["id"]})
    )
    assert len(rows) == 1 and meta["total_count"] == 1, "the row was retained rather than deleted"
    assert rows[0]["status"] == "REFUNDED"
    assert rows[0]["unit_sales_credit_cents"] == purchase["unit_sales_credit_cents"], \
        "unit_sales_credit_cents is retained on the row for audit"

    projection = create_projection(api, sc, release_class="BACK_CATALOG")
    finalized = validate_success(
        api.finalize_availability_projection(projection["id"], ADMIN)
    )
    assert finalized["projected_cannibalized_unit_sales_cents"] == \
        pytest.approx(0.00, abs=0.01), \
        "the REFUNDED row is excluded, so the accumulator holds nothing"
    assert finalized["projected_subscription_value_cents"] > 0, \
        "the subscription upside is untouched by the reversal"