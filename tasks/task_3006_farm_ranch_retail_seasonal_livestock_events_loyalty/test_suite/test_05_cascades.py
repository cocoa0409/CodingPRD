"""Transitive cascades: mortality quarantine (depth 4) and posture flip
(depth 5)."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_campaign,
    brooder_verify,
    create_account,
    create_campaign_ready,
    create_chick_order_payload,
    create_hatchery_schedule_payload,
    create_on_sale_lot,
    create_published_schedule,
    make_customer_headers,
    place_chick_order,
    post_care_log,
    set_clock,
    setup_reserved_order,
    setup_spring_store,
    validate_error,
    validate_paginated,
    validate_success,
)

RA = TEST_USERS["regional_admin_headers"]
MGR = TEST_USERS["store_manager_headers"]
ASSOC = TEST_USERS["store_associate_headers"]


def test_mortality_quarantine_cascade_suspends_lot_and_cancels_orders(api):
    """PRD §3.3: "When the recomputed rate is strictly greater than 0.05 — a rate of exactly 0.05 does not trigger anything — the lot is quarantined: it transitions `ON_SALE → SUSPENDED`, its `health_flag` becomes `QUARANTINED`, and every `RESERVED` or `BROODER_VERIFIED` chick order against the lot is cancelled by the system with cause quarantine."
    PRD §3.3: "Those cancellations release their reserved birds into `quantity_quarantined`, not back to `quantity_on_hand`"

    Design: Difficulty/transitive_cascade/mortality_quarantine_cascade_depth4
    """
    ctx = setup_reserved_order()

    # 10 deaths of 100 -> rate 0.1 > 0.05 -> quarantine cascade.
    post_care_log(ctx["lot"]["id"], "MORTALITY", mortality_count=10)

    lot = validate_success(api.get_livestock_lot(ctx["lot"]["id"], MGR))
    assert lot["status"] == "SUSPENDED"
    assert lot["health_flag"] == "QUARANTINED"
    assert lot["mortality_count"] == 10
    assert lot["mortality_rate"] == 0.1
    # Reserved birds landed in quarantine, not back on hand.
    assert lot["quantity_on_hand"] == 84
    assert lot["quantity_quarantined"] == 6

    order = validate_success(api.get_chick_order(ctx["order"]["id"], MGR))
    assert order["status"] == "CANCELLED"


def test_mortality_quarantine_cascade_posts_goodwill_points(api):
    """PRD §3.3: "each affected order's loyalty account receives an `ADJUSTMENT` ledger entry of +500 goodwill points."
    PRD §3.7: "The `points_balance`, by contrast, is the plain sum of `points_delta` over all ledger entries regardless of age or tier-counting"

    Design: Difficulty/transitive_cascade/mortality_quarantine_cascade_depth4
    """
    ctx = setup_reserved_order()
    post_care_log(ctx["lot"]["id"], "MORTALITY", mortality_count=10)

    account = validate_success(api.get_loyalty_account(ctx["account"]["id"], MGR))
    assert account["points_balance"] == 500

    entries, _meta = validate_paginated(
        api.list_account_ledger_entries(ctx["account"]["id"], MGR)
    )
    adjustments = [e for e in entries if e["entry_type"] == "ADJUSTMENT"]
    assert len(adjustments) == 1
    assert adjustments[0]["points_delta"] == 500
    assert adjustments[0]["counts_toward_tier"] is False


def test_posture_flip_cascade_supersedes_campaign_and_recomputes_posture(api):
    """PRD §3.1: "First, any other `ACTIVE` campaign on the same store is superseded to `COMPLETED`. Second, the store's `posture` is recomputed to the new campaign's `season`, `active_campaign_id` points at the newly active campaign, and the store's `version` increments."

    Design: Difficulty/transitive_cascade/posture_flip_cascade_depth5
    """
    ctx = setup_spring_store()
    spring_campaign_id = ctx["campaign_id"]
    assert ctx["store"]["posture"] == "SPRING_PLANTING"

    fall_campaign = create_campaign_ready(ctx["store"], "FALL_FEED", aisle_count=3)
    activate_campaign(fall_campaign["id"])

    old = validate_success(api.get_season_campaign(spring_campaign_id, RA))
    assert old["status"] == "COMPLETED"

    store = validate_success(api.get_store(ctx["store"]["id"], RA))
    assert store["posture"] == "FALL_FEED"
    assert store["active_campaign_id"] == fall_campaign["id"]
    assert store["version"] == ctx["store"]["version"] + 1


def test_posture_flip_cascade_closes_schedules_lots_and_expires_orders(api):
    """PRD §3.1: "Third, if the new posture is anything other than `SPRING_PLANTING`, every `PUBLISHED` hatchery schedule on the store is closed to `CLOSED`. Fourth, each such schedule closure forces every `ON_SALE` livestock lot beneath it to `SALE_CLOSED`. Fifth, each such lot closure expires every `RESERVED` or `BROODER_VERIFIED` chick order against the lot to `EXPIRED`, releasing its reserved quantity back into the lot's `quantity_on_hand`."

    Design: Difficulty/transitive_cascade/posture_flip_cascade_depth5
    """
    ctx = setup_reserved_order()
    brooder_verify(ctx["order"]["id"])

    fall_campaign = create_campaign_ready(ctx["store"], "FALL_FEED", aisle_count=3)
    activate_campaign(fall_campaign["id"])

    schedule = validate_success(api.get_hatchery_schedule(ctx["schedule"]["id"], MGR))
    assert schedule["status"] == "CLOSED"

    lot = validate_success(api.get_livestock_lot(ctx["lot"]["id"], MGR))
    assert lot["status"] == "SALE_CLOSED"
    assert lot["quantity_on_hand"] == 100  # 6 reserved birds released back

    order = validate_success(api.get_chick_order(ctx["order"]["id"], MGR))
    assert order["status"] == "EXPIRED"
