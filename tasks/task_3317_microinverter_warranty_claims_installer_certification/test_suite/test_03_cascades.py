"""Corrective-action cascades: unit failure to lot recall to campaign to orders.

Difficulty queue A: transitive_cascade. Corner queue B: errors.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_campaign,
    create_campaign,
    dispatch_order,
    force_lot_recall,
    get_lot,
    get_success_data,
    list_campaigns,
    list_orders,
    observe,
    set_clock,
    setup_system_with_units,
    validate_error,
)

from test_helpers import api_client

ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Queue A: the depth-3 lot-trend cascade ───────────────────────────

def _twenty_unit_lot(code: str, threshold: float):
    """Twenty commissioned units on one lot whose threshold the fourth failure
    crosses exactly, so the cascade is driven by a real trend rather than by hand."""
    serials = [f"{code}-U{i}" for i in range(1, 21)]
    return setup_system_with_units(
        installer_code=f"INST-{code}", unit_serials=serials,
        unit_models=["IQ7"] * 20, lot_code=f"LOT-{code}", embed_model_code="IQ7",
        replacement_model_code="IQ8", defect_threshold_pct=threshold,
        commissioned_at="2026-01-20T00:00:00Z", site_address=f"7 {code} Way",
    )


def test_unit_failure_crosses_lot_into_recall_and_opens_a_campaign(api):
    """PRD §3.5: "The instant a unit of a lot enters `FAILED`, the system recomputes
    `failed_unit_count`, `window_failed_unit_count`, `defect_rate_cumulative_pct`, and
    `lot_status`, and then asks whether the lot has just crossed into `RECALL`." PRD
    §3.5: "and if the lot has at least ten registered units, and if no campaign already
    exists for that lot in `DRAFT` or `DISPATCHING` status, the system creates a
    `ProactiveCampaign` on its own initiative." PRD §3.5: "The synthesized campaign is
    opened in `DRAFT` with `origin` set to `LOT_TREND`, its `replacement_model_code`
    copied from the lot, `guaranteed_units` set to zero, and `max_units` set to the
    count of the lot's units that are `ONLINE` or `UNDERPERFORMING`."

    Design: Difficulty/transitive_cascade/unit_failure_to_lot_recall_to_campaign_depth_three
    """
    ctx = _twenty_unit_lot("TC1", threshold=20.0)
    set_clock("2026-08-01T00:00:00Z")
    for index in range(3):
        observe(ctx["units"][index]["id"], 0.0, "2026-08-01T00:00:00Z")
    before = get_lot(ctx["lot"]["id"])
    assert before["lot_status"] == "WATCH"
    assert before["defect_rate_cumulative_pct"] == 15.0
    assert list_campaigns(lot_id=ctx["lot"]["id"]) == [], (
        "no campaign exists before the lot crosses into RECALL"
    )

    failed = observe(ctx["units"][3]["id"], 0.0, "2026-08-10T00:00:00Z")
    assert failed["monitored_status"] == "FAILED"

    after = get_lot(ctx["lot"]["id"])
    assert after["failed_unit_count"] == 4
    assert after["defect_rate_cumulative_pct"] == 20.0
    assert after["lot_status"] == "RECALL"
    assert after["corrective_action_required"] is True
    campaigns = list_campaigns(lot_id=ctx["lot"]["id"], status="DRAFT")
    assert len(campaigns) == 1, "exactly one campaign is synthesized for the lot"
    campaign = campaigns[0]
    assert campaign["origin"] == "LOT_TREND"
    assert campaign["guaranteed_units"] == 0
    assert campaign["replacement_model_code"] == "IQ8"
    assert campaign["max_units"] == 16
    assert campaign["target_unit_count"] == 16


def test_activating_the_synthesized_campaign_dispatches_orders_for_every_target(api):
    """PRD §3.5: "Activation stamps `window_start_at` with the logical clock,
    synthesizes one `ReplacementOrder` in `PENDING_DISPATCH` for every selected target
    unit, sets `dispatched_count` to the number synthesized, and moves the campaign to
    `DISPATCHING`."

    Design: Difficulty/transitive_cascade/unit_failure_to_lot_recall_to_campaign_depth_three
    """
    ctx = _twenty_unit_lot("TC1B", threshold=20.0)
    set_clock("2026-08-01T00:00:00Z")
    for index in range(4):
        observe(ctx["units"][index]["id"], 0.0, "2026-08-01T00:00:00Z")
    campaign = list_campaigns(lot_id=ctx["lot"]["id"], status="DRAFT")[0]
    activated = activate_campaign(campaign["id"])
    assert activated["status"] == "DISPATCHING"
    assert activated["window_start_at"] == "2026-08-01T00:00:00.000Z"
    assert activated["dispatched_count"] == activated["target_unit_count"]
    orders = list_orders(campaign_id=campaign["id"])
    assert len(orders) == activated["dispatched_count"]
    assert {order["status"] for order in orders} == {"PENDING_DISPATCH"}


# ─── Queue A: the campaign -> order -> counter cascade ────────────────

def _recalled_lot_with_live_orders(code: str, max_units: int = 3):
    ctx = setup_system_with_units(
        installer_code=f"INST-{code}", unit_serials=[f"{code}-U{i}" for i in range(1, 6)],
        unit_models=["IQ7"] * 5, lot_code=f"LOT-{code}", embed_model_code="IQ7",
        replacement_model_code="IQ8", defect_threshold_pct=1e6,
        commissioned_at="2026-01-20T00:00:00Z", site_address=f"8 {code} Way",
    )
    set_clock("2026-09-01T00:00:00Z")
    force_lot_recall(ctx["lot"]["id"])
    campaign = create_campaign(ctx["lot"]["id"], max_units=max_units)
    campaign = activate_campaign(campaign["id"])
    ctx["campaign"] = campaign
    return ctx


def test_canceling_a_campaign_withdraws_its_orders_and_records_the_count(api):
    """PRD §3.5: "Cancelling a dispatching campaign instead stamps `window_end_at`,
    moves the campaign to `CANCELED`, drives its `PENDING_DISPATCH` and `DISPATCHED`
    orders to `CANCELED`, and records how many orders the cancellation withdrew in
    `canceled_count`."

    Design: Difficulty/transitive_cascade/campaign_cancel_to_order_cancel_to_counter
    """
    ctx = _recalled_lot_with_live_orders("TC2")
    campaign = ctx["campaign"]
    assert campaign["dispatched_count"] == 3
    assert campaign["canceled_count"] == 0
    orders = list_orders(campaign_id=campaign["id"], status="PENDING_DISPATCH")
    assert len(orders) == 3
    for order in orders:
        dispatch_order(order["id"])

    canceled = get_success_data(api_client.cancel_campaign(campaign["id"], ADMIN))
    assert canceled["status"] == "CANCELED"
    assert canceled["canceled_count"] == 3
    assert canceled["window_end_at"] == "2026-09-01T00:00:00.000Z"
    for order in list_orders(campaign_id=campaign["id"]):
        assert order["status"] == "CANCELED"
        assert order["installed_at"] is None


def test_campaign_canceled_count_re_derives_to_the_same_value_on_every_read(api):
    """PRD §3.5: "records how many orders the cancellation withdrew in
    `canceled_count`." PRD §3.5: "A campaign's `window_end_at` is null for as long as
    the campaign is open."

    Design: Difficulty/transitive_cascade/campaign_cancel_to_order_cancel_to_counter
    """
    ctx = _recalled_lot_with_live_orders("TC2B")
    campaign = ctx["campaign"]
    assert campaign["window_end_at"] is None, "an open campaign has no closing instant"
    canceled = get_success_data(api_client.cancel_campaign(campaign["id"], ADMIN))
    assert canceled["canceled_count"] == 3
    re_read = get_success_data(api_client.get_campaign(campaign["id"], ADMIN))
    assert re_read["canceled_count"] == 3, "the count is stable across reads"
    assert re_read["status"] == "CANCELED"


def test_reactivating_withdrawn_orders_returns_the_live_count_without_drift(api):
    """PRD §3.7: "reactivating is available from `CANCELED` and returns the order to
    `PENDING_DISPATCH` with both `dispatched_at` and `installed_at` reset to null, but
    only while the source claim is in `APPROVED`, `DISPATCHED`, or `REOPENED`, or while
    the source campaign is in `DRAFT`, `DISPATCHING`, or `CANCELED`." PRD §3.5: "when
    the order belongs to a campaign the removal is reflected in that campaign's
    `canceled_count`."

    Design: Difficulty/transitive_cascade/campaign_cancel_to_order_cancel_to_counter
    """
    ctx = _recalled_lot_with_live_orders("TC2C")
    campaign = ctx["campaign"]
    orders = list_orders(campaign_id=campaign["id"])
    assert len(orders) == 3
    get_success_data(api_client.cancel_campaign(campaign["id"], ADMIN))
    for order in orders:
        get_success_data(api_client.reactivate_replacement_order(order["id"], ADMIN))
    re_read = get_success_data(api_client.get_campaign(campaign["id"], ADMIN))
    assert re_read["canceled_count"] == 0, "the compensation leaves no residue in canceled_count"
    live = list_orders(campaign_id=campaign["id"], status="PENDING_DISPATCH")
    assert len(live) == 3
    assert re_read["dispatched_count"] - re_read["canceled_count"] == len(live)


# ─── Queue B: errors ──────────────────────────────────────────────────

def test_activating_a_campaign_with_an_empty_target_pool_is_refused(api):
    """PRD §3.5: "an empty candidate pool after the status filter is refused with
    `ERR_NO_CAMPAIGN_TARGETS`." PRD §3.5: "`target_unit_count` counts the campaign
    lot's units whose `monitored_status` is `ONLINE` or `UNDERPERFORMING`; failed,
    silent, and decommissioned units are excluded because a failed unit already has
    its own claim path."

    Design: Corner/errors/campaign_activation_with_no_eligible_units
    """
    ctx = setup_system_with_units(installer_code="INST-ER1", unit_serials=["ER1-U1"],
                                  unit_models=["IQ7"], lot_code="LOT-ER1",
                                  embed_model_code="IQ7", replacement_model_code="IQ8",
                                  defect_threshold_pct=1e6,
                                  commissioned_at="2026-01-05T00:00:00Z",
                                  site_address="41 Oscar Two Way")
    set_clock("2026-09-01T00:00:00Z")
    observe(ctx["units"][0]["id"], 0.0, "2026-08-01T00:00:00Z")
    force_lot_recall(ctx["lot"]["id"])
    campaign = create_campaign(ctx["lot"]["id"], max_units=1)
    resp = api_client.activate_campaign(campaign["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_NO_CAMPAIGN_TARGETS, 409)
    after = get_success_data(api_client.get_campaign(campaign["id"], ADMIN))
    assert after["status"] == "DRAFT"
    assert after["dispatched_count"] == 0


ADMIN = ADMIN