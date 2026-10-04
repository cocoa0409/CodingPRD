"""Revenue splits, payout assembly and withholding by country.

Covers the per-record rounding order that the revenue domain turns on, the
country table versus treaty override, and the half-open payout period window.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_payout_batch,
    assert_revenue_routing,
    assert_share_conservation,
    create_approved_channel,
    create_classified_item,
    create_payout_lock_payload,
    get_success_data,
    lock_payout,
    release_payout,
    route_revenue,
    validate_error,
    validate_success,
)


# ─── Per-record rounding ─────────────────────────────

def test_ad_share_is_rounded_once_per_routing_record(api):
    """PRD §3.8: "three `AD` routing records of 1001 cents each produce creator
    shares of 551, 551 and 551 — a total of 1653 cents — because each record
    rounds independently; rounding the 3003-cent sum once instead produces 1652
    cents"
    PRD §3.8: "The creator receives the half-up rounding of the record's gross
    amount multiplied by the stream's rate: 0.55 for `AD`, 0.70 for `MEMBERSHIP`,
    0.70 for `SUPER_CHAT`, and 0.60 for `SHOPPING`."

    Design: Difficulty/dual_variant_calc/ad_share_per_record_rounding_versus_batch_rounding
    """
    channel = create_approved_channel(channel_name="Dual Variant US", country_code="US",
                                      lifetime_watch_hours=8000, subscriber_count=1200,
                                      tax_tin_status="TIN_PROVIDED",
                                      payment_threshold_cents=100)
    item = create_classified_item(channel["id"], title="Rounding Trap")

    routings = [route_revenue(item["id"], stream_type="AD", gross_revenue_cents=1001)
                for _ in range(3)]

    for routing in routings:
        assert_revenue_routing(routing)
        assert routing["creator_share_cents"] == 551, (
            "each record must round independently to 551, never to 550")
        assert routing["partner_share_cents"] == 450
        assert_share_conservation(routing)


def test_batch_creator_total_keeps_the_per_record_rounding(api):
    """PRD §3.8: "three `AD` routing records of 1001 cents each produce creator
    shares of 551, 551 and 551 — a total of 1653 cents — because each record
    rounds independently; rounding the 3003-cent sum once instead produces 1652
    cents"
    PRD §3.8: "The system must therefore never sum first and round afterwards."

    Design: Difficulty/dual_variant_calc/ad_share_per_record_rounding_versus_batch_rounding
    """
    channel = create_approved_channel(channel_name="Dual Variant Batch US",
                                      lifetime_watch_hours=8000, subscriber_count=1200,
                                      tax_tin_status="TIN_PROVIDED",
                                      payment_threshold_cents=100)
    item = create_classified_item(channel["id"], title="Rounding Trap Batch")
    for _ in range(3):
        route_revenue(item["id"], stream_type="AD", gross_revenue_cents=1001)

    batch = lock_payout(channel["id"])
    assert_payout_batch(batch)
    assert batch["gross_cents"] == 3003
    assert batch["creator_share_cents"] == 1653, (
        "the batch total must be 551 + 551 + 551, not a rounded 3003 sum of 1652")
    assert batch["status"] == "LOCKED"


def test_released_batch_commits_the_per_record_creator_total(api):
    """PRD §3.8: "rounding the 3003-cent sum once instead produces 1652 cents"
    PRD §3.11: "The selected rate is recorded on the batch as
    `withholding_rate_pct`, a three-decimal fraction, so the applied regime is
    auditable after the fact."
    PRD §3.11: "The raw net is the payer base minus the withheld amount, and the
    `adjusted_net_cents` balance is that figure, floored at zero — a computed
    negative falls to zero rather than being carried as a debt."

    Design: Difficulty/dual_variant_calc/ad_share_per_record_rounding_versus_batch_rounding
    """
    channel = create_approved_channel(channel_name="Dual Variant Release US",
                                      lifetime_watch_hours=8000, subscriber_count=1200,
                                      tax_tin_status="TIN_PROVIDED",
                                      payment_threshold_cents=100)
    item = create_classified_item(channel["id"], title="Rounding Trap Release")
    for _ in range(3):
        route_revenue(item["id"], stream_type="AD", gross_revenue_cents=1001)

    batch = lock_payout(channel["id"])
    released = validate_success(release_payout(channel["id"], batch["id"]), 200)

    assert released["gross_cents"] == 3003
    assert released["creator_share_cents"] == 1653
    assert released["withholding_rate_pct"] == 0.00
    assert released["tax_withheld_cents"] == 0
    assert released["adjusted_net_cents"] == 1653
    assert released["status"] == "RELEASED"


# ─── Withholding by country and treaty ───────────────

def _de_channel_with_ad_routing(name, tax_treaty=False):
    channel = create_approved_channel(channel_name=name, country_code="DE",
                                      lifetime_watch_hours=9000, subscriber_count=4000,
                                      tax_tin_status="TIN_PROVIDED",
                                      tax_treaty=tax_treaty,
                                      payment_threshold_cents=100)
    item = create_classified_item(channel["id"], title=f"{name} Session")
    routing = route_revenue(item["id"], stream_type="AD", gross_revenue_cents=3003)
    return channel, item, routing


def test_treaty_override_collapses_a_german_channel_to_the_treaty_rate(api):
    """PRD §3.11: "otherwise a channel with a treaty in force (`tax_treaty` true
    and a non-US country) collapses to the `TREATY_RATE` of 0.15 for every
    country it applies to, overriding the country table entirely and, for
    example, dropping a German channel from 0.26 to 0.15"

    Design: Difficulty/dual_variant_calc/treaty_override_withholding_versus_country_table
    """
    channel, _item, routing = _de_channel_with_ad_routing("Treaty DE")
    batch = lock_payout(channel["id"])
    assert batch["creator_share_cents"] == 1652
    assert routing["creator_share_cents"] == 1652

    validate_success(api_client.patch_channel(
        channel["id"], {"tax_treaty": True},
        TEST_USERS["platform_admin_headers"]), 200)
    released = validate_success(release_payout(channel["id"], batch["id"]), 200)

    assert released["withholding_rate_pct"] == 0.15
    assert released["tax_withheld_cents"] == 248, "half-up rounding of 1652 * 0.15"
    assert released["adjusted_net_cents"] == 1404
    assert_revenue_routing(routing)


def test_country_table_applies_without_a_treaty(api):
    """PRD §3.11: "otherwise the country's own rate applies, with `GB` at the
    `GB_RATE` of 0.20, `DE` at the `DE_RATE` of 0.26, `IN` at the `IN_RATE` of
    0.24 and `BR` at the `BR_RATE` of 0.24, and any other non-US country taking
    the `DEFAULT_NON_TREATY_RATE` of 0.24"

    Design: Difficulty/dual_variant_calc/treaty_override_withholding_versus_country_table
    """
    channel, _item, _routing = _de_channel_with_ad_routing("Country Table DE")
    batch = lock_payout(channel["id"])

    released = validate_success(release_payout(channel["id"], batch["id"]), 200)

    assert released["creator_share_cents"] == 1652
    assert released["withholding_rate_pct"] == 0.26, "the DE table rate, not the treaty rate"
    assert released["tax_withheld_cents"] == 430, "half-up rounding of 1652 * 0.26"
    assert released["adjusted_net_cents"] == 1222


def test_tin_missing_penalty_outranks_the_country_table(api):
    """PRD §3.11: "If the channel's `tax_tin_status` is `TIN_MISSING`, the rate is
    0.30 regardless of country and regardless of any treaty flag — the
    `TIN_MISSING_PENALTY_RATE` outranks the entire country table, and for a
    country whose documented non-treaty rate is 0.24 it produces a penalty delta
    of 0.06."

    Design: Difficulty/dual_variant_calc/treaty_override_withholding_versus_country_table
    """
    channel = create_approved_channel(channel_name="Tin Missing DE", country_code="DE",
                                      lifetime_watch_hours=9000, subscriber_count=4000,
                                      tax_tin_status="TIN_MISSING", tax_treaty=True,
                                      payment_threshold_cents=100)
    item = create_classified_item(channel["id"], title="Tin Missing Session")
    route_revenue(item["id"], stream_type="AD", gross_revenue_cents=10000)
    batch = lock_payout(channel["id"])

    released = validate_success(release_payout(channel["id"], batch["id"]), 200)

    assert released["withholding_rate_pct"] == 0.30
    assert released["creator_share_cents"] == 5500
    assert released["tax_withheld_cents"] == 1650, "half-up rounding of 5500 * 0.30"
    assert released["adjusted_net_cents"] == 3850


# ─── Payout period edges and the payment threshold ───

def test_routing_on_the_period_end_instant_falls_outside_the_window(api):
    """PRD §3.11: "The routed set is pinned precisely: it contains the routing
    rows recorded against content items owned by the channel, whose status is one
    of `RELEASED_TO_CREATOR`, `PAID_CREATOR` or `ESCROW`, and whose creation
    timestamp falls in the half-open window from `period_start_at` inclusive to
    `period_end_at` exclusive."

    Design: Difficulty/resource_temporal_overlap/held_release_routing_falls_outside_a_closed_period
    """
    validate_success(api.set_clock("2026-10-01T00:00:00Z",
                                   TEST_USERS["platform_admin_headers"]), 200)
    channel = create_approved_channel(channel_name="Period US", country_code="US",
                                      lifetime_watch_hours=8000, subscriber_count=1500,
                                      tax_tin_status="TIN_PROVIDED",
                                      payment_threshold_cents=100)
    item = create_classified_item(channel["id"], title="Boundary Dated")
    route_revenue(item["id"], stream_type="AD", gross_revenue_cents=10000)

    batch = validate_success(api_client.lock_payout(
        channel["id"],
        create_payout_lock_payload(
            get_success_data(api_client.get_channel(
                channel["id"], TEST_USERS["any_headers"]))["version"],
            period_start_at="2026-09-01T00:00:00Z",
            period_end_at="2026-10-01T00:00:00Z"),
        TEST_USERS["platform_admin_headers"]), 200)

    assert batch["creator_share_cents"] == 0, (
        "a routing stamped at exactly period_end_at belongs to the next period")
    assert batch["gross_cents"] == 0
    assert batch["adjusted_net_cents"] == 0


def test_release_of_a_batch_that_falls_short_of_the_threshold_is_rejected(api):
    """PRD §3.11: "A batch falling short is refused with
    `ERR_BELOW_PAYMENT_THRESHOLD` (HTTP 409)."
    PRD §3.11: "the batch's `adjusted_net_cents` must have reached the channel's
    `payment_threshold_cents`, which defaults to 10000 cents"

    Design: Difficulty/resource_temporal_overlap/held_release_routing_falls_outside_a_closed_period
    """
    validate_success(api.set_clock("2026-10-01T00:00:00Z",
                                   TEST_USERS["platform_admin_headers"]), 200)
    channel = create_approved_channel(channel_name="Period Threshold US",
                                      country_code="US", lifetime_watch_hours=8000,
                                      subscriber_count=1500,
                                      tax_tin_status="TIN_PROVIDED",
                                      payment_threshold_cents=100)
    item = create_classified_item(channel["id"], title="Boundary Threshold Dated")
    route_revenue(item["id"], stream_type="AD", gross_revenue_cents=10000)

    batch = validate_success(api_client.lock_payout(
        channel["id"],
        create_payout_lock_payload(
            get_success_data(api_client.get_channel(
                channel["id"], TEST_USERS["any_headers"]))["version"],
            period_start_at="2026-09-01T00:00:00Z",
            period_end_at="2026-10-01T00:00:00Z"),
        TEST_USERS["platform_admin_headers"]), 200)

    res = api.release_payout(
        channel["id"], batch["id"],
        {"expected_payout_batch_version": batch["version"]},
        TEST_USERS["platform_admin_headers"])
    validate_error(res, "ERR_BELOW_PAYMENT_THRESHOLD", expected_status=409)


def test_routing_inside_the_window_produces_the_full_creator_share(api):
    """PRD §3.11: "whose creation timestamp falls in the half-open window from
    `period_start_at` inclusive to `period_end_at` exclusive"
    PRD §3.8: "The creator receives the half-up rounding of the record's gross
    amount multiplied by the stream's rate: 0.55 for `AD`"

    Design: Difficulty/resource_temporal_overlap/held_release_routing_falls_outside_a_closed_period
    """
    channel = create_approved_channel(channel_name="Period Inside US",
                                      country_code="US", lifetime_watch_hours=8000,
                                      subscriber_count=1500,
                                      tax_tin_status="TIN_PROVIDED",
                                      payment_threshold_cents=100)
    item = create_classified_item(channel["id"], title="Inside Dated")
    route_revenue(item["id"], stream_type="AD", gross_revenue_cents=10000)

    batch = lock_payout(channel["id"])

    assert batch["creator_share_cents"] == 5500
    assert batch["gross_cents"] == 10000
    assert batch["held_cents"] == 0
    assert batch["adjusted_net_cents"] == 5500