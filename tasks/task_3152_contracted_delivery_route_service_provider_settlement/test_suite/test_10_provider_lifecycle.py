"""Tests translated from the breadth Coverage Index (queue B) — sections
entities and state_machines.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_area,
    create_deduction_payload,
    create_peak_declaration_payload,
    create_provider,
    create_route_assignment_payload,
    create_service_area_payload,
    get_success_data,
    make_service_provider_headers,
    setup_active_provider,
    setup_disputed_week,
    setup_reconciled_week,
    validate_error,
    validate_paginated,
    validate_success,
)

AM = TEST_USERS["account_manager_headers"]
SA = TEST_USERS["settlement_analyst_headers"]


# ═══════════════════════════════════════════════════════════════════════
# entities: provider_creation_defaults_and_initial_state
# ═══════════════════════════════════════════════════════════════════════

def test_provider_defaults_and_initial_derived_state(api):
    """PRD §3.1: "`provider_type` distinguishes the ordinary contracted operator
    from an approved successor acquirer: it is either `AGREED` or `SUCCESSOR`,
    and when it is omitted it defaults to `AGREED`. A newly registered provider
    begins life in status `UNDER_REVIEW`, and its `brand_compliance_pct` is
    derived immediately at registration even though, with no fleet on file, that
    derivation may legitimately yield zero."
    PRD §3.1: "Its declared default is 100.0."

    Design: Corner/entities/provider_creation_defaults_and_initial_state
    """
    provider = validate_success(api.create_service_provider({
        "legal_name": "Acme Route Services LLC", "tax_id": "27-1000001"}, AM), 201)
    assert provider["provider_type"] == "AGREED"
    assert provider["status"] == "UNDER_REVIEW"
    assert provider["chargeback_outstanding_cents"] == 0
    assert provider["brand_compliance_pct"] == 0.00
    assert provider["qualification_pct"] == 100.0


# ═══════════════════════════════════════════════════════════════════════
# entities: provider_retrieval_not_found
# ═══════════════════════════════════════════════════════════════════════

def test_reading_an_unallocated_provider_reports_not_found(api):
    """PRD §2.9: "a provider path id that does not resolve yields
    `ERR_PROVIDER_NOT_FOUND`"

    Design: Corner/entities/provider_retrieval_not_found
    """
    res = api.get_service_provider("3f1a9c22-5b47-4d80-9e11-7c2d4a6f8b30", AM)
    validate_error(res, "ERR_PROVIDER_NOT_FOUND", expected_status=404)


# ═══════════════════════════════════════════════════════════════════════
# entities: service_area_listing_pagination_shape
# ═══════════════════════════════════════════════════════════════════════

def test_area_listing_honours_limit_offset_and_reports_meta(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; when
    omitted it defaults to 10, and it may be set no lower than 1 and no higher
    than 100. The `offset` parameter states how many leading items to skip and
    defaults to 0."
    PRD §2.3: "The pagination fields `limit`, `offset`, `total_count` and
    `has_more` appear inside the `meta` object of the response envelope for list
    endpoints."

    Design: Corner/entities/service_area_listing_pagination_shape
    """
    get_success_data(api.create_service_area(create_service_area_payload(
        area_code="TR11", state_code="TN", zip_prefix_low="372",
        zip_prefix_high="374", stop_capacity_weekly=2000), AM))
    get_success_data(api.create_service_area(create_service_area_payload(
        area_code="TR12", state_code="TN", zip_prefix_low="375",
        zip_prefix_high="377", stop_capacity_weekly=1500), AM))
    get_success_data(api.create_service_area(create_service_area_payload(
        area_code="TR13", state_code="GA", zip_prefix_low="300",
        zip_prefix_high="302", stop_capacity_weekly=1200), AM))

    data, meta = validate_paginated(
        api.list_service_areas(AM, {"state_code": "TN", "limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    data2, meta2 = validate_paginated(
        api.list_service_areas(AM, {"state_code": "TN", "limit": 1, "offset": 1}))
    assert len(data2) == 1
    assert meta2["has_more"] is False


# ═══════════════════════════════════════════════════════════════════════
# entities: settlement_period_version_increments_on_every_mutation
# ═══════════════════════════════════════════════════════════════════════

def test_settlement_period_version_advances_on_close_accrual_self_loop(api):
    """PRD §2.8: "a system-managed counter that increments by one on every
    modification to the resource."
    PRD §3.7: "Closing an already-`ACCRUAL_CLOSED` week is legal and is a
    self-loop: a second close refreshes the derived totals without reopening the
    accrual window"

    Design: Corner/entities/settlement_period_version_increments_on_every_mutation
    """
    from test_helpers import CLOCK_PAST_WEEK, open_week, set_clock
    import test_helpers.fixtures as fx

    ctx = setup_active_provider()
    period = open_week(ctx["provider"]["id"], ctx["area"]["id"])
    fx.add_observation(period["id"], stops_count=300, packages_count=250,
                       accessorial_cents=2000)
    set_clock(CLOCK_PAST_WEEK)

    first = validate_success(api.close_accrual(period["id"], SA), 200)
    second = validate_success(api.close_accrual(period["id"], SA), 200)
    assert first["version"] == period["version"] + 1
    assert second["version"] == period["version"] + 2
    assert second["status"] == "ACCRUAL_CLOSED"


# ═══════════════════════════════════════════════════════════════════════
# state_machines: peak_declaration_end_from_declared_returns_invalid_state
# ═══════════════════════════════════════════════════════════════════════

def test_ending_a_never_activated_declaration_is_refused(api):
    """PRD §3.6: "Ending a declaration is likewise clock-gated: it may be ended
    only once the logical clock has reached `ends_on`."
    PRD §2.9: "A requested transition that is not legal from the resource's
    current status is refused with `ERR_INVALID_STATE` (HTTP 409)"

    Design: Corner/state_machines/peak_declaration_end_from_declared_returns_invalid_state
    """
    area = create_area()
    declaration = get_success_data(api.create_peak_declaration(
        create_peak_declaration_payload(area["id"]), AM))

    res = api.end_peak_declaration(declaration["id"], AM)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_peak_declaration(declaration["id"], AM), 200)
    assert after["status"] == "DECLARED"


# ═══════════════════════════════════════════════════════════════════════
# state_machines: peak_declaration_terminal_lockdown_after_cancel
# ═══════════════════════════════════════════════════════════════════════

def test_canceled_declaration_rejects_every_further_transition(api):
    """PRD §3.6: "A declaration may be canceled while it is still `DECLARED`,
    before any asset has been authorized against it, and cancellation is
    terminal."
    PRD §2.9: "any request against a resource that has already reached a
    terminal state is refused with `ERR_ALREADY_TERMINAL` (HTTP 409)"

    Design: Corner/state_machines/peak_declaration_terminal_lockdown_after_cancel
    """
    area = create_area()
    declaration = get_success_data(api.create_peak_declaration(
        create_peak_declaration_payload(area["id"]), AM))
    canceled = validate_success(api.cancel_peak_declaration(declaration["id"], AM), 200)
    assert canceled["status"] == "CANCELED"

    res = api.activate_peak_declaration(declaration["id"], AM)
    validate_error(res, "ERR_ALREADY_TERMINAL", expected_status=409)
    assert validate_success(api.get_peak_declaration(declaration["id"], AM), 200)["status"] == "CANCELED"


# ═══════════════════════════════════════════════════════════════════════
# state_machines: route_assignment_initial_state_is_draft
# ═══════════════════════════════════════════════════════════════════════

def test_new_route_title_is_draft_and_leaves_area_unassigned(api):
    """PRD §3.4: "A new title begins in `DRAFT`, and the create advances the
    area's `version` by one."
    PRD §2.5: "The area carries `assigned_provider_id` for the provider
    currently holding the active title, and it is null whenever no `ACTIVE`
    assignment exists."

    Design: Corner/state_machines/route_assignment_initial_state_is_draft
    """
    provider = create_provider()
    area = create_area()
    area_now = get_success_data(api.get_service_area(area["id"], AM))

    created = validate_success(api.create_route_assignment(
        create_route_assignment_payload(area["id"], provider["id"], area_now["version"]), AM), 201)
    assert created["status"] == "DRAFT"
    assert created["occupancy_ends_at"] is None
    area_after = validate_success(api.get_service_area(area["id"], AM), 200)
    assert area_after["status"] == "UNASSIGNED"


# ═══════════════════════════════════════════════════════════════════════
# state_machines: dispute_counter_round_budget_refused
# ═══════════════════════════════════════════════════════════════════════

def test_third_counter_offer_on_one_dispute_is_refused(api):
    """PRD §3.11: "A counter may only be placed while `rounds_used` is at most 1,
    which combined with the hard round limit means a dispute may consume at most
    two counter-offers (the limit is 2) and the third counter-offer on one
    dispute is refused with `ERR_NEGOTIATION_ROUND_LIMIT` (HTTP 422)."

    Design: Corner/state_machines/dispute_counter_round_budget_refused
    """
    ctx = setup_disputed_week()
    dispute, provider = ctx["dispute"], ctx["provider"]
    sp = make_service_provider_headers(provider["id"])

    validate_success(api.submit_dispute_evidence(dispute["id"], sp), 200)
    validate_success(api.counter_dispute(dispute["id"], {"counter_amount_cents": 2000}, SA), 200)
    validate_success(api.resubmit_dispute_evidence(dispute["id"], sp), 200)
    validate_success(api.counter_dispute(dispute["id"], {"counter_amount_cents": 2500}, SA), 200)
    validate_success(api.resubmit_dispute_evidence(dispute["id"], sp), 200)

    res = api.counter_dispute(dispute["id"], {"counter_amount_cents": 3000}, SA)
    validate_error(res, "ERR_NEGOTIATION_ROUND_LIMIT", expected_status=422)

    listed, _meta = validate_paginated(api.list_period_disputes(ctx["period"]["id"], SA))
    assert listed[0]["rounds_used"] == 2
    assert listed[0]["status"] == "EVIDENCE_SUBMITTED"


# ═══════════════════════════════════════════════════════════════════════
# state_machines: release_refused_while_dispute_still_open
# ═══════════════════════════════════════════════════════════════════════

def test_release_refused_while_a_dispute_is_still_open(api):
    """PRD §3.11: "From `DISPUTED`, every dispute on the week must be in
    `RESOLVED` or `WITHDRAWN` status *and* the logical clock must still be
    strictly before `week_start_at` plus seven days plus 90 days."
    PRD §2.4: "a mutation that fails must not touch it."

    Design: Corner/state_machines/release_refused_while_dispute_still_open
    """
    ctx = setup_disputed_week()
    res = api.release_period(ctx["period"]["id"], AM)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    provider_after = validate_success(api.get_service_provider(ctx["provider"]["id"], SA), 200)
    assert provider_after["lifetime_paid_cents"] == 0


def test_release_after_withdrawal_moves_net_into_lifetime_paid(api):
    """PRD §3.11: "The week's `net_amount_cents` is added to the provider's
    `lifetime_paid_cents`, which is the conserved total §2.4 describes and which
    no other operation may touch."
    PRD §3.11: "a `ServiceProvider` may withdraw a dispute in `OPEN` or in
    `COUNTERED`, and the only precondition is that the dispute's `filed_by_role`"

    Design: Corner/state_machines/release_refused_while_dispute_still_open
    """
    ctx = setup_disputed_week()
    provider, period = ctx["provider"], ctx["period"]
    sp = make_service_provider_headers(provider["id"])

    validate_success(api.withdraw_dispute(ctx["dispute"]["id"], sp), 200)
    released = validate_success(api.release_period(period["id"], AM), 200)
    assert released["status"] == "RELEASED"

    provider_after = validate_success(api.get_service_provider(provider["id"], SA), 200)
    assert provider_after["lifetime_paid_cents"] == released["net_amount_cents"]