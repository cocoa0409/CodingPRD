"""Tests translated from the depth Test Targeting Index (queue A) — rules
non_linear_state_machine, transitive_cascade, cross_entity_state_dependency and
resource_temporal_overlap.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_area,
    create_agreement_payload,
    create_provider,
    create_route_assignment_payload,
    draft_and_sign_agreement,
    file_and_verify_policy,
    get_success_data,
    make_service_provider_headers,
    setup_provider_compliance,
    setup_two_approved_providers,
    setup_two_approved_providers_after_transfer,
    validate_error,
    validate_paginated,
    validate_success,
)

AM = TEST_USERS["account_manager_headers"]
SA = TEST_USERS["settlement_analyst_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ═══════════════════════════════════════════════════════════════════════
# Instance: route_title_transfer_negotiation_cycle
# ═══════════════════════════════════════════════════════════════════════

def test_transfer_cycle_is_reenterable_from_active(api):
    """PRD §3.5: "A pending transfer is a pure cycle: the title may move
    `ACTIVE` to `PENDING_TRANSFER` to `ACTIVE` and back again any number of
    times."
    PRD §2.8: "a system-managed counter that increments by one on every
    modification to the resource."

    Design: Difficulty/non_linear_state_machine/route_title_transfer_negotiation_cycle
    """
    ctx = setup_two_approved_providers()
    asg, prov_a, prov_b = ctx["assignment"], ctx["provider"], ctx["provider_b"]
    sp_a = make_service_provider_headers(prov_a["id"])
    start_version = asg["version"]

    first = validate_success(api.request_transfer(
        asg["id"], {"acquiring_provider_id": prov_b["id"], "transfer_price_cents": 4500000}, sp_a), 200)
    assert first["status"] == "PENDING_TRANSFER"

    back = validate_success(api.withdraw_transfer(asg["id"], sp_a), 200)
    assert back["status"] == "ACTIVE"

    second = validate_success(api.request_transfer(
        asg["id"], {"acquiring_provider_id": prov_b["id"], "transfer_price_cents": 4500000}, sp_a), 200)
    assert second["status"] == "PENDING_TRANSFER"

    final = validate_success(api.withdraw_transfer(asg["id"], sp_a), 200)
    assert final["status"] == "ACTIVE"
    assert final["version"] == start_version + 4


def test_withdraw_transfer_restores_agreement_to_active(api):
    """PRD §3.5: "The title moves to `PENDING_TRANSFER` and the agreement
    governing its area moves to `RE_NEGOTIATION`"
    PRD §3.5: "The transferring `ServiceProvider` may withdraw a pending
    transfer, which returns the title to `ACTIVE` and restores the governing
    agreement to `ACTIVE`"

    Design: Difficulty/non_linear_state_machine/route_title_transfer_negotiation_cycle
    """
    ctx = setup_two_approved_providers()
    asg, agr, prov_a, prov_b = ctx["assignment"], ctx["agreement"], ctx["provider"], ctx["provider_b"]
    sp_a = make_service_provider_headers(prov_a["id"])

    validate_success(api.request_transfer(
        asg["id"], {"acquiring_provider_id": prov_b["id"], "transfer_price_cents": 4500000}, sp_a), 200)
    pending = validate_success(api.get_agreement(agr["id"], AM), 200)
    assert pending["status"] == "RE_NEGOTIATION"

    validate_success(api.withdraw_transfer(asg["id"], sp_a), 200)
    restored = validate_success(api.get_agreement(agr["id"], AM), 200)
    assert restored["status"] == "ACTIVE"


# ═══════════════════════════════════════════════════════════════════════
# Instance: provider_compliance_posture_review_cycle
# ═══════════════════════════════════════════════════════════════════════

def test_provider_review_cycle_returns_to_approved(api):
    """PRD §3.1: "Providers may also be returned to review from `APPROVED`, a
    cycle back-edge that reopens the vetting gate without touching held assets."
    PRD §2.8: "a system-managed counter that increments by one on every
    modification to the resource."

    Design: Difficulty/non_linear_state_machine/provider_compliance_posture_review_cycle
    """
    provider = create_provider()
    area = create_area()
    file_and_verify_policy(provider["id"])
    get_success_data(api.approve_service_provider(provider["id"], AM))
    # Each of the four transitions below is a modification of the provider, so
    # the counter must advance by exactly four from a fresh read taken now.
    start_version = validate_success(
        api.get_service_provider(provider["id"], AM), 200)["version"]

    review = validate_success(api.reopen_provider_review(provider["id"], AM), 200)
    assert review["status"] == "UNDER_REVIEW"

    # Approval requires a live verified policy; the provider's is still VERIFIED.
    approved = get_success_data(api.approve_service_provider(provider["id"], AM))
    assert approved["status"] == "APPROVED"

    validate_success(api.reopen_provider_review(provider["id"], AM), 200)
    final = get_success_data(api.approve_service_provider(provider["id"], AM))
    assert final["status"] == "APPROVED"
    assert final["version"] == start_version + 4


def test_composite_contagion_floor_limits_single_week_drop(api):
    """PRD §3.9: "A contagion floor then applies on top of the clamp: the
    composition may not fall more than 5.00 below the provider's prior
    composite, so the final value is the greater of the clamped figure and the
    prior composite minus 5.00."

    Design: Difficulty/non_linear_state_machine/provider_compliance_posture_review_cycle
    """
    provider = create_provider()
    area = create_area()
    get_success_data(api.approve_service_provider(provider["id"], AM))

    first = get_success_data(api.compose_performance_metric(
        get_success_data(api.create_performance_metric({
            "provider_id": provider["id"], "service_score": 96,
            "safety_score": 94, "customer_experience_score": 92}, SA))["id"], SA))
    second = get_success_data(api.compose_performance_metric(
        get_success_data(api.create_performance_metric({
            "provider_id": provider["id"], "service_score": 60,
            "safety_score": 60, "customer_experience_score": 60}, SA))["id"], SA))

    assert second["composite_score"] == pytest.approx(first["composite_score"] - 5.00, abs=0.01)


# ═══════════════════════════════════════════════════════════════════════
# Instance: suspension_three_hop_area_release_chain
# ═══════════════════════════════════════════════════════════════════════

def test_provider_suspension_cascades_titles_areas_and_agreements(api):
    """PRD §3.1: "Suspending an `APPROVED` provider terminates every
    `RouteAssignment` of that provider in `DRAFT`, `ACTIVE` or
    `PENDING_TRANSFER` status; it returns every `ServiceArea` whose
    `assigned_provider_id` names that provider to `UNASSIGNED` and clears the
    pointer; and it terminates every `Agreement` of that provider sitting in
    `DRAFT`, `PENDING_REVIEW`, `RE_NEGOTIATION` or `ACTIVE`."

    Design: Difficulty/transitive_cascade/suspension_three_hop_area_release_chain
    """
    ctx = setup_two_approved_providers_after_transfer()
    provider, area, agreement, assignment = (
        ctx["provider"], ctx["area"], ctx["agreement"], ctx["assignment"])

    validate_success(api.suspend_service_provider(provider["id"], AM), 200)

    provider_after = validate_success(api.get_service_provider(provider["id"], AM), 200)
    assert provider_after["status"] == "SUSPENDED"
    assignment_after = validate_success(api.get_route_assignment(assignment["id"], AM), 200)
    assert assignment_after["status"] == "TERMINATED"
    area_after = validate_success(api.get_service_area(area["id"], AM), 200)
    assert area_after["status"] == "UNASSIGNED"
    assert area_after["assigned_provider_id"] is None
    agreement_after = validate_success(api.get_agreement(agreement["id"], AM), 200)
    assert agreement_after["status"] == "TERMINATED"


def test_suspension_leaves_open_settlement_week_untouched(api):
    """PRD §3.1: "Suspending an `APPROVED` provider terminates every
    `RouteAssignment` of that provider in `DRAFT`, `ACTIVE` or
    `PENDING_TRANSFER` status; it returns every `ServiceArea` whose
    `assigned_provider_id` names that provider to `UNASSIGNED` and clears the
    pointer; and it terminates every `Agreement` of that provider sitting in
    `DRAFT`, `PENDING_REVIEW`, `RE_NEGOTIATION` or `ACTIVE`."
    PRD §3.7: "A new week begins in `OPEN`"

    Design: Difficulty/transitive_cascade/suspension_three_hop_area_release_chain
    """
    ctx = setup_two_approved_providers_after_transfer()
    provider, area = ctx["provider"], ctx["area"]
    provider_now = get_success_data(api.get_service_provider(provider["id"], SA))
    period = get_success_data(api.create_settlement_period({
        "provider_id": provider["id"], "service_area_id": area["id"],
        "week_start_at": "2026-09-07T00:00:00Z", "is_peak_week": False,
        "fuel_rate_cents_per_mile": 3,
        "expected_provider_version": provider_now["version"]}, SA))

    validate_success(api.suspend_service_provider(provider["id"], AM), 200)

    period_after = validate_success(api.get_settlement_period(period["id"], AM), 200)
    assert period_after["status"] == "OPEN"

# ═══════════════════════════════════════════════════════════════════════
# Instance: insurance_expiry_two_hop_release_chain
# ═══════════════════════════════════════════════════════════════════════

def _expiring_policy_provider(**kw):
    """Provider A APPROVED holding an ACTIVE title over area A1 with an ACTIVE
    agreement, whose only AUTO_LIABILITY policy is short-dated (§3.2/§3.3).

    The certificate's `expires_at` is only one day after the activation instant,
    so advancing the logical clock to the renewal boundary crosses both the
    renewal-due stamp and the certificate's expiry in one move.
    """
    provider = create_provider(**kw)
    area = create_area()
    _, vehicle, _ = setup_provider_compliance(
        provider["id"], area["id"], expires_at="2026-09-02T00:00:00Z")
    agreement = draft_and_sign_agreement(provider["id"], area["id"])
    area_now = get_success_data(api_client.get_service_area(area["id"], AM))
    assignment = get_success_data(api_client.create_route_assignment(
        create_route_assignment_payload(area["id"], provider["id"], area_now["version"]), AM))
    assignment = get_success_data(api_client.activate_route_assignment(assignment["id"], AM))
    return provider, area, agreement, assignment


_EXPIRY_CLOCK = "2027-08-25T00:00:00Z"  # past renewal_due_at and past the policy expiry


def test_expired_insurance_blocks_renewal_signature_at_the_insufficient_gate(api):
    """PRD §3.3: "every `AUTO_LIABILITY` policy of the provider must carry
    `coverage_cents` at or above the agreement's `insurance_coverage_cents` floor
    and must not have expired, or the signature stops with
    `ERR_INSURANCE_INSUFFICIENT` (HTTP 422)."
    PRD §2.12: "All rules phrased as "now" — the seven-day accrual close, the
    90-day dispute window, the 30-day negotiation boundary, the 365-day renewal
    due stamp, policy expiry and declaration-window coverage — read this clock."

    Design: Difficulty/transitive_cascade/insurance_expiry_two_hop_release_chain
    """
    provider, area, agreement, assignment = _expiring_policy_provider()
    # The clock moves past renewal_due_at (which the signature stamped 365 days
    # ahead) and past the certificate's expiry, so renegotiation is inside the
    # 30-day window the PRD permits it in, as §3.3 states.
    get_success_data(api.set_current_utc(_EXPIRY_CLOCK, TEST_USERS["platform_admin_headers"]))

    # The clock has crossed both the renewal-due stamp and the short-dated
    # certificate's expiry, so the renegotiation round opens inside the 30-day
    # window while the resubmission's signature meets the expired-policy gate.
    validate_success(api.renegotiate_agreement(agreement["id"], AM), 200)
    # A resumed agreement is resubmitted by the provider before the manager signs.
    validate_success(api.submit_agreement(
        agreement["id"], make_service_provider_headers(provider["id"])), 200)

    res = api.sign_agreement(agreement["id"], AM)
    validate_error(res, "ERR_INSURANCE_INSUFFICIENT", expected_status=422)


def test_unsuccessful_signature_never_terminates_the_live_title(api):
    """PRD §3.3: "Expiring an agreement closes its live title and frees the
    territory: every `RouteAssignment` on the area that is in `ACTIVE` status is
    set to `TERMINATED`"
    PRD §3.3: "every `AUTO_LIABILITY` policy of the provider must carry
    `coverage_cents` at or above the agreement's `insurance_coverage_cents` floor
    and must not have expired, or the signature stops with
    `ERR_INSURANCE_INSUFFICIENT` (HTTP 422)."

    Design: Difficulty/transitive_cascade/insurance_expiry_two_hop_release_chain
    """
    provider, area, agreement, assignment = _expiring_policy_provider()
    get_success_data(api.set_current_utc(_EXPIRY_CLOCK, TEST_USERS["platform_admin_headers"]))
    validate_success(api.renegotiate_agreement(agreement["id"], AM), 200)
    validate_success(api.submit_agreement(
        agreement["id"], make_service_provider_headers(provider["id"])), 200)
    api.sign_agreement(agreement["id"], AM)

    assignment_after = validate_success(api.get_route_assignment(assignment["id"], AM), 200)
    assert assignment_after["status"] == "ACTIVE"


# ═══════════════════════════════════════════════════════════════════════
# Instance: assignment_activation_requires_active_agreement
# ═══════════════════════════════════════════════════════════════════════

def test_activation_refused_while_governing_agreement_in_renegotiation(api):
    """PRD §3.4: "The governing agreement for the title's area must itself be
    `ACTIVE`."
    PRD §2.9: "A requested transition that is not legal from the resource's
    current status is refused with `ERR_INVALID_STATE` (HTTP 409)"

    Design: Difficulty/cross_entity_state_dependency/assignment_activation_requires_active_agreement
    """
    provider = create_provider()
    area = create_area()
    setup_provider_compliance(provider["id"], area["id"])
    agreement = get_success_data(api.create_agreement(
        create_agreement_payload(provider["id"], area["id"]), AM))
    get_success_data(api.submit_agreement(
        agreement["id"], make_service_provider_headers(provider["id"])))
    get_success_data(api.renegotiate_agreement(agreement["id"], AM))
    area_now = get_success_data(api.get_service_area(area["id"], AM))
    assignment = get_success_data(api.create_route_assignment(
        create_route_assignment_payload(area["id"], provider["id"], area_now["version"]), AM))

    res = api.activate_route_assignment(assignment["id"], AM)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    assert validate_success(api.get_route_assignment(assignment["id"], AM), 200)["status"] == "DRAFT"
    assert validate_success(api.get_service_area(area["id"], AM), 200)["status"] == "UNASSIGNED"


def test_activation_succeeds_once_governing_agreement_becomes_active(api):
    """PRD §3.4: "The governing agreement for the title's area must itself be
    `ACTIVE`."
    PRD §3.4: "A successful activation propagates in both directions. The title
    becomes `ACTIVE`; the area becomes `ASSIGNED` and its `assigned_provider_id`
    is set to the title's `provider_id`"

    Design: Difficulty/cross_entity_state_dependency/assignment_activation_requires_active_agreement
    """
    provider = create_provider()
    area = create_area()
    setup_provider_compliance(provider["id"], area["id"])
    agreement = get_success_data(api.create_agreement(
        create_agreement_payload(provider["id"], area["id"]), AM))
    get_success_data(api.submit_agreement(
        agreement["id"], make_service_provider_headers(provider["id"])))
    get_success_data(api.renegotiate_agreement(agreement["id"], AM))
    area_now = get_success_data(api.get_service_area(area["id"], AM))
    assignment = get_success_data(api.create_route_assignment(
        create_route_assignment_payload(area["id"], provider["id"], area_now["version"]), AM))

    get_success_data(api.submit_agreement(
        agreement["id"], make_service_provider_headers(provider["id"])))
    validate_success(api.sign_agreement(agreement["id"], AM), 200)
    activated = validate_success(api.activate_route_assignment(assignment["id"], AM), 200)
    assert activated["status"] == "ACTIVE"
    area_after = validate_success(api.get_service_area(area["id"], AM), 200)
    assert area_after["status"] == "ASSIGNED"
    assert area_after["assigned_provider_id"] == provider["id"]


# ═══════════════════════════════════════════════════════════════════════
# Instance: transfer_approval_requires_approved_acquirer
# ═══════════════════════════════════════════════════════════════════════

def test_approve_transfer_refused_while_acquirer_under_review(api):
    """PRD §3.5: "The acquiring provider must still be `APPROVED` at the moment
    of approval, not merely at the moment of request."
    PRD §2.9: "A requested transition that is not legal from the resource's
    current status is refused with `ERR_INVALID_STATE` (HTTP 409)"

    Design: Difficulty/cross_entity_state_dependency/transfer_approval_requires_approved_acquirer
    """
    # Provider A with a title already pending transfer to approved Provider B.
    base = setup_two_approved_providers_after_transfer()
    prov_a, prov_b, area, asg = base["provider"], base["provider_b"], base["area"], base["assignment"]
    assert asg["status"] == "PENDING_TRANSFER"
    # Demote the acquirer after the request but before approval.
    get_success_data(api.reopen_provider_review(prov_b["id"], AM))
    area_now = get_success_data(api.get_service_area(area["id"], AM))

    res = api.approve_transfer(asg["id"], {"expected_service_area_version": area_now["version"]}, AM)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_pending_transfer_title_unmoved_when_acquirer_not_approved(api):
    """PRD §3.5: "The title moves to `PENDING_TRANSFER` and the agreement
    governing its area moves to `RE_NEGOTIATION`"
    PRD §3.5: "The acquiring provider must still be `APPROVED` at the moment of
    approval, not merely at the moment of request."

    Design: Difficulty/cross_entity_state_dependency/transfer_approval_requires_approved_acquirer
    """
    base = setup_two_approved_providers_after_transfer()
    prov_a, prov_b, area, asg = base["provider"], base["provider_b"], base["area"], base["assignment"]
    get_success_data(api.reopen_provider_review(prov_b["id"], AM))
    area_now = get_success_data(api.get_service_area(area["id"], AM))
    api.approve_transfer(asg["id"], {"expected_service_area_version": area_now["version"]}, AM)

    after = validate_success(api.get_route_assignment(asg["id"], AM), 200)
    assert after["status"] == "PENDING_TRANSFER"
    area_after = validate_success(api.get_service_area(area["id"], AM), 200)
    assert area_after["assigned_provider_id"] == prov_a["id"]


# ═══════════════════════════════════════════════════════════════════════
# Instance: area_occupancy_abutting_titles
# ═══════════════════════════════════════════════════════════════════════

def test_abutting_occupancy_instant_is_permitted(api):
    """PRD §2.5: "A candidate interval that intersects another assignment's
    occupancy interval on the same area is refused with `ERR_TEMPORAL_OVERLAP`
    (HTTP 409), but two intervals that merely abut — one ending at exactly the
    instant the next begins, with a gap of zero days — are permitted."
    PRD §3.4: "Termination sets the title to `TERMINATED`, records
    `occupancy_ends_at` as the logical clock instant so the occupancy interval
    closes half-open"

    Design: Difficulty/resource_temporal_overlap/area_occupancy_abutting_titles
    """
    base = setup_two_approved_providers_after_transfer()
    prov_a, prov_b, area, asg = base["provider"], base["provider_b"], base["area"], base["assignment"]
    # Withdraw the pending sale so the title is ACTIVE again and eligible for the
    # termination that records its occupancy end.
    validate_success(api.withdraw_transfer(
        asg["id"], make_service_provider_headers(prov_a["id"])), 200)
    get_success_data(api.set_current_utc("2026-09-05T00:00:00Z", TEST_USERS["platform_admin_headers"]))
    validate_success(api.terminate_route_assignment(asg["id"], AM), 200)
    terminated = validate_success(api.get_route_assignment(asg["id"], AM), 200)
    assert terminated["occupancy_ends_at"] == "2026-09-05T00:00:00.000Z"
    area_now = get_success_data(api.get_service_area(area["id"], AM))

    created = validate_success(api.create_route_assignment(
        create_route_assignment_payload(area["id"], prov_b["id"], area_now["version"],
                                        effective_date="2026-09-05T00:00:00Z"), AM), 201)
    assert created["status"] == "DRAFT"


def test_overlapping_occupancy_instant_is_refused(api):
    """PRD §2.5: "A candidate interval that intersects another assignment's
    occupancy interval on the same area is refused with `ERR_TEMPORAL_OVERLAP`
    (HTTP 409)"

    Design: Difficulty/resource_temporal_overlap/area_occupancy_abutting_titles
    """
    base = setup_two_approved_providers_after_transfer()
    prov_a, prov_b, area, asg = base["provider"], base["provider_b"], base["area"], base["assignment"]
    # Withdraw the pending sale so the title is ACTIVE again and eligible for the
    # termination that records its occupancy end.
    validate_success(api.withdraw_transfer(
        asg["id"], make_service_provider_headers(prov_a["id"])), 200)
    get_success_data(api.set_current_utc("2026-09-05T00:00:00Z", TEST_USERS["platform_admin_headers"]))
    validate_success(api.terminate_route_assignment(asg["id"], AM), 200)
    # The candidate starts inside the interval the terminated title held, so it
    # runs from before that interval's recorded end rather than abutting it.
    area_now = get_success_data(api.get_service_area(area["id"], AM))

    res = api.create_route_assignment(
        create_route_assignment_payload(area["id"], prov_b["id"], area_now["version"],
                                        effective_date="2026-09-04T23:59:00Z"), AM)
    validate_error(res, "ERR_TEMPORAL_OVERLAP", expected_status=409)


# ═══════════════════════════════════════════════════════════════════════
# Instance: driver_duty_guard_buffer
# ═══════════════════════════════════════════════════════════════════════

def test_duty_shift_starting_at_prior_end_is_refused(api):
    """PRD §2.7: "Because the buffer is inclusive and begins at the previous end
    instant, a candidate that starts at exactly the moment the previous interval
    ended is a violation, not a legal back-to-back shift."
    PRD §3.2: "a candidate interval that intersects the previous end instant
    extended by the inclusive one-minute buffer is refused with
    `ERR_DRIVER_HOURS_EXCEEDED` (HTTP 409)"

    Design: Difficulty/resource_temporal_overlap/driver_duty_guard_buffer
    """
    provider = create_provider()
    area = create_area()
    setup_provider_compliance(provider["id"], area["id"])
    driver = get_success_data(api.create_driver({
        "provider_id": provider["id"], "service_area_id": area["id"], "full_name": "Dana Cruz",
        "license_class": "CLASS_B", "qualification_status": "QUALIFIED", "is_temporary": False}, AM))
    sp = make_service_provider_headers(provider["id"])
    validate_success(api.create_duty_shift(
        driver["id"], {"starts_at": "2026-09-04T08:00:00Z", "ends_at": "2026-09-04T17:00:00Z"}, sp), 201)

    res = api.create_duty_shift(
        driver["id"], {"starts_at": "2026-09-04T17:00:00Z", "ends_at": "2026-09-04T22:00:00Z"}, sp)
    validate_error(res, "ERR_DRIVER_HOURS_EXCEEDED", expected_status=409)


def test_duty_shift_after_guard_buffer_is_accepted(api):
    """PRD §3.2: "The record replaces the driver's `duty_window_starts_at` and
    `duty_window_ends_at`."

    Design: Difficulty/resource_temporal_overlap/driver_duty_guard_buffer
    """
    provider = create_provider()
    area = create_area()
    setup_provider_compliance(provider["id"], area["id"])
    driver = get_success_data(api.create_driver({
        "provider_id": provider["id"], "service_area_id": area["id"], "full_name": "Dana Cruz",
        "license_class": "CLASS_B", "qualification_status": "QUALIFIED", "is_temporary": False}, AM))
    sp = make_service_provider_headers(provider["id"])
    validate_success(api.create_duty_shift(
        driver["id"], {"starts_at": "2026-09-04T08:00:00Z", "ends_at": "2026-09-04T17:00:00Z"}, sp), 201)

    accepted = validate_success(api.create_duty_shift(
        driver["id"], {"starts_at": "2026-09-04T17:02:00Z", "ends_at": "2026-09-04T22:00:00Z"}, sp), 201)
    driver_after = validate_success(api.get_driver(driver["id"], AM), 200)
    assert driver_after["duty_window_ends_at"] == "2026-09-04T22:00:00.000Z"
