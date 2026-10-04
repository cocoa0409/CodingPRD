"""Conserved quantities on the campaign counters and the installer ledger.

Difficulty queue A: compensating_invariant, cross_entity_state_dependency.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_transfer,
    create_campaign,
    create_transfer,
    dispatch_order,
    force_lot_recall,
    get_success_data,
    install_order,
    list_orders,
    set_clock,
    setup_failed_unit_claim,
    setup_system_with_units,
    validate_error,
)

from test_helpers import api_client

ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Queue A: withdrawn orders are returned without drift ─────────────

def test_withdrawn_campaign_orders_are_returned_without_counter_drift(api):
    """PRD §3.7: "reactivating is available from `CANCELED` and returns the order to
    `PENDING_DISPATCH` with both `dispatched_at` and `installed_at` reset to null, but
    only while the source claim is in `APPROVED`, `DISPATCHED`, or `REOPENED`, or while
    the source campaign is in `DRAFT`, `DISPATCHING`, or `CANCELED`." PRD §3.5: "when
    the order belongs to a campaign the removal is reflected in that campaign's
    `canceled_count`."

    Design: Difficulty/compensating_invariant/campaign_cancel_reactivate_restores_live_order_count
    """
    ctx = setup_system_with_units(
        installer_code="INST-CI1", unit_serials=[f"CI1-U{i}" for i in range(1, 6)],
        unit_models=["IQ7"] * 5, lot_code="LOT-CI1", embed_model_code="IQ7",
        replacement_model_code="IQ8", defect_threshold_pct=1e6,
        commissioned_at="2026-01-20T00:00:00Z", site_address="17 Tango Way",
    )
    set_clock("2026-09-01T00:00:00Z")
    force_lot_recall(ctx["lot"]["id"])
    campaign = create_campaign(ctx["lot"]["id"], max_units=3)
    from test_helpers import activate_campaign
    campaign = activate_campaign(campaign["id"])
    assert campaign["dispatched_count"] == 3
    assert campaign["canceled_count"] == 0
    orders = list_orders(campaign_id=campaign["id"])
    assert len(orders) == 3

    canceled = get_success_data(api_client.cancel_campaign(campaign["id"], ADMIN))
    assert canceled["canceled_count"] == 3
    for order in orders:
        reactivated = get_success_data(
            api_client.reactivate_replacement_order(order["id"], ADMIN))
        assert reactivated["status"] == "PENDING_DISPATCH"
        assert reactivated["dispatched_at"] is None
        assert reactivated["installed_at"] is None
    final = get_success_data(api_client.get_campaign(campaign["id"], ADMIN))
    assert final["canceled_count"] == 0, "the compensation leaves no drift in the named quantity"
    live = list_orders(campaign_id=campaign["id"], status="PENDING_DISPATCH")
    assert len(live) == final["dispatched_count"] - final["canceled_count"] == 3


def test_reactivating_only_one_order_leaves_the_rest_withdrawn(api):
    """PRD §3.7: "reactivating is available from `CANCELED` and returns the order to
    `PENDING_DISPATCH` with both `dispatched_at` and `installed_at` reset to null".
    PRD §3.5: "records how many orders the cancellation withdrew in `canceled_count`."

    Design: Difficulty/compensating_invariant/campaign_cancel_reactivate_restores_live_order_count
    """
    ctx = setup_system_with_units(
        installer_code="INST-CI1B", unit_serials=[f"CI1B-U{i}" for i in range(1, 6)],
        unit_models=["IQ7"] * 5, lot_code="LOT-CI1B", embed_model_code="IQ7",
        replacement_model_code="IQ8", defect_threshold_pct=1e6,
        commissioned_at="2026-01-20T00:00:00Z", site_address="17b Tango Way",
    )
    set_clock("2026-09-01T00:00:00Z")
    force_lot_recall(ctx["lot"]["id"])
    campaign = create_campaign(ctx["lot"]["id"], max_units=3)
    from test_helpers import activate_campaign
    campaign = activate_campaign(campaign["id"])
    orders = list_orders(campaign_id=campaign["id"])
    get_success_data(api_client.cancel_campaign(campaign["id"], ADMIN))
    get_success_data(api_client.reactivate_replacement_order(orders[0]["id"], ADMIN))
    final = get_success_data(api_client.get_campaign(campaign["id"], ADMIN))
    assert final["canceled_count"] == 2, "each order still withdrawn keeps its slot in the tally"
    live = list_orders(campaign_id=campaign["id"], status="PENDING_DISPATCH")
    assert len(live) == 1
    assert final["dispatched_count"] - final["canceled_count"] == len(live)


# ─── Queue A: rejecting approved labor restores the installer balance ─

def test_rejecting_an_approved_reimbursement_moves_the_cents_to_reversed(api):
    """PRD §3.1: "`labor_approved_cents_total` sums the `net_amount_cents` of every
    `LaborReimbursement` currently in `APPROVED` or `PAID` status." PRD §3.1:
    "`labor_reversed_cents_total` sums the `net_amount_cents` of reimbursements that
    were `APPROVED` and were later reversed into `REJECTED`, which is a strictly
    different figure from the approved total because a reversed amount leaves the
    approved total at the moment of reversal."

    Design: Difficulty/compensating_invariant/labor_rejection_restores_installer_payable_balance
    """
    ctx = setup_failed_unit_claim(
        installer_code="INST-CI2", claim_target="DISPATCHED", claimed_hours=4.0,
        unit_serials=["CI2-U1"], unit_models=["IQ7"], lot_code="LOT-CI2",
        embed_model_code="IQ7", replacement_model_code="IQ8",
        commissioned_at="2019-03-01T00:00:00Z", site_address="18 Uniform Way",
    )
    installer, labor = ctx["installer"], ctx["reimbursement"]
    before = get_success_data(api_client.get_installer_portfolio(installer["id"], ADMIN))
    assert before["labor_approved_cents_total"] == 34425
    assert before["labor_reversed_cents_total"] == 0
    rejected = get_success_data(api_client.reject_labor_reimbursement(
        labor["id"], {"rejection_reason": "duplicate invoice"}, ADMIN))
    assert rejected["status"] == "REJECTED"
    after = get_success_data(api_client.get_installer_portfolio(installer["id"], ADMIN))
    assert after["labor_approved_cents_total"] == 0
    assert after["labor_reversed_cents_total"] == 34425


def test_a_reimbursement_cannot_be_rejected_while_the_claim_is_only_approved(api):
    """PRD §3.8: "a `PlatformAdmin` may reverse an already-`APPROVED` reimbursement by
    supplying a `rejection_reason`, provided the claim it belongs to is in
    `DISPATCHED`, `CLOSED`, or `REOPENED` — a reversal is not available while the claim
    is simply `APPROVED`".

    Design: Difficulty/compensating_invariant/labor_rejection_restores_installer_payable_balance
    """
    ctx = setup_failed_unit_claim(
        installer_code="INST-CI2B", claim_target="APPROVED", claimed_hours=4.0,
        unit_serials=["CI2B-U1"], unit_models=["IQ7"], lot_code="LOT-CI2B",
        embed_model_code="IQ7", replacement_model_code="IQ8",
        commissioned_at="2019-03-01T00:00:00Z", site_address="18b Uniform Way",
    )
    labor = ctx["reimbursement"]
    assert ctx["claim"]["status"] == "APPROVED"
    assert labor["status"] == "PENDING", (
        "the reversal window opens only once the claim leaves APPROVED"
    )
    resp = api_client.reject_labor_reimbursement(
        labor["id"], {"rejection_reason": "duplicate invoice"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


# ─── Queue A: a concluded sale is fully reversed by reopen ────────────

def test_reopening_an_approved_transfer_restores_the_previous_holder(api):
    """PRD §3.9: "an approved transfer can be reopened, moving it from `APPROVED` back
    to `SUBMITTED`, which reverts the system's `homeowner_name` and `homeowner_email` to
    the pre-transfer holder recorded on the transfer and decrements
    `owner_change_count`." PRD §3.9: "Because the reversal restores the prior holder
    exactly, a sale that falls through leaves the warranty record as though the transfer
    had never been approved."

    Design: Difficulty/compensating_invariant/labor_rejection_restores_installer_payable_balance
    """
    ctx = setup_system_with_units(
        installer_code="INST-CI3", unit_serials=["CI3-U1"], unit_models=["IQ8"],
        lot_code="LOT-CI3", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2026-01-01T00:00:00Z",
        site_address="18c Uniform Way", homeowner_name="Original Holder",
        homeowner_email="original@holder.example",
    )
    set_clock("2026-09-01T00:00:00Z")
    transfer = create_transfer(ctx["system"]["id"], effective_date="2026-08-15T00:00:00Z",
                               new_owner_name="N. Owner", new_owner_email="n@owner.example")
    approve_transfer(transfer["id"])
    sold = get_success_data(api_client.get_system_registration(ctx["system"]["id"], ADMIN))
    assert sold["owner_change_count"] == 1
    assert sold["homeowner_name"] == "N. Owner"
    voided = get_success_data(api_client.reopen_warranty_transfer(transfer["id"], ADMIN))
    assert voided["status"] == "SUBMITTED"
    restored = get_success_data(api_client.get_system_registration(ctx["system"]["id"], ADMIN))
    assert restored["homeowner_name"] == "Original Holder"
    assert restored["owner_change_count"] == 0


def test_a_rejected_transfer_is_terminal(api):
    """PRD §3.9: "Rejection writes the supplied `rejection_reason` onto the transfer and
    moves it to `REJECTED`, which is terminal."

    Design: Difficulty/compensating_invariant/labor_rejection_restores_installer_payable_balance
    """
    ctx = setup_system_with_units(
        installer_code="INST-CI3B", unit_serials=["CI3B-U1"], unit_models=["IQ8"],
        lot_code="LOT-CI3B", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2026-01-01T00:00:00Z",
        site_address="18d Uniform Way",
    )
    set_clock("2026-09-01T00:00:00Z")
    transfer = create_transfer(ctx["system"]["id"], effective_date="2026-08-15T00:00:00Z")
    rejected = get_success_data(api_client.reject_warranty_transfer(
        transfer["id"], {"rejection_reason": "paperwork missing"}, ADMIN))
    assert rejected["status"] == "REJECTED"
    resp = api_client.reopen_warranty_transfer(transfer["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


# ─── Queue B: cross-cutting complexity layers ─────────────────────────

def test_transferred_system_still_reports_its_coverage_window(api):
    """PRD §3.3: "Step four stamps `extended_warranty_end_at` as the base end advanced
    by the chosen number of months." PRD §3.3: "`warranty_status` begins at `ACTIVE` and
    may become `EXPIRED` or `TRANSFERRED`."

    Design: Corner/cross_cutting_complexity_layers/derived_installer_active_system_count_tracks_transfer
    """
    ctx = setup_system_with_units(
        installer_code="INST-XC3B", unit_serials=["XC3B-U1"], unit_models=["IQ8"],
        lot_code="LOT-XC3B", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2020-01-01T00:00:00Z",
        site_address="44b Sierra Two Way",
    )
    set_clock("2026-09-01T00:00:00Z")
    coverage_before = get_success_data(api_client.get_system_coverage(ctx["system"]["id"], ADMIN))
    transfer = create_transfer(ctx["system"]["id"], effective_date="2026-08-15T00:00:00Z")
    approve_transfer(transfer["id"])
    system = get_success_data(api_client.get_system_registration(ctx["system"]["id"], ADMIN))
    assert system["warranty_status"] == "TRANSFERRED"
    assert system["extended_warranty_end_at"] == coverage_before["extended_warranty_end_at"], (
        "a change of homeowner does not move the coverage window"
    )


def test_installing_a_replacement_consumes_a_position_on_the_system(api):
    """PRD §3.4: "it starts at five and is decremented by one for every replacement
    installed anywhere on that system."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_unit_version_on_replacement_order_create
    """
    ctx = setup_system_with_units(
        installer_code="INST-XC10", unit_serials=["XC10-U1"], unit_models=["IQ8"],
        lot_code="LOT-XC10", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2026-04-01T00:00:00Z",
        site_address="50 Sierra Two Way",
    )
    unit = ctx["units"][0]
    assert unit["replacement_window_position"] == 5
    order = get_success_data(api_client.create_replacement_order(
        {"unit_id": unit["id"], "replacement_model_code": "IQ8",
         "expected_unit_version": unit["version"]}, ADMIN), 201)
    dispatch_order(order["id"])
    install_order(order["id"], "XC10-R1", "2026-08-20T00:00:00Z", ctx["installer"]["id"])
    after = get_success_data(api_client.get_unit(unit["id"], ADMIN))
    assert after["replacement_count"] == 1
    assert after["replacement_window_position"] == 4


def test_reinstatement_after_the_window_flows_without_a_state_error(api):
    """PRD §3.1: "Reinstatement re-issues `certified_until` from the current clock
    instant and recomputes both entitlement booleans."

    Design: Corner/cross_cutting_complexity_layers/derived_installer_active_system_count_tracks_transfer
    """
    ctx = setup_system_with_units(
        installer_code="INST-XC11", unit_serials=["XC11-U1"], unit_models=["IQ8"],
        lot_code="LOT-XC11", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2026-04-01T00:00:00Z",
        site_address="51 Sierra Two Way",
    )
    installer = ctx["installer"]
    suspended = get_success_data(api_client.suspend_installer(installer["id"], ADMIN))
    assert suspended["certification_status"] == "SUSPENDED"
    reinstated = get_success_data(api_client.reinstate_installer(installer["id"], ADMIN))
    assert reinstated["certification_status"] == "ACTIVE"
    assert reinstated["certified_until"] is not None
    assert reinstated["commissioning_enabled"] is True