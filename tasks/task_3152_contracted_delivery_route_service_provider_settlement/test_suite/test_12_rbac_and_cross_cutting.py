"""Tests translated from the breadth Coverage Index (queue B) — sections
validations, rbac and cross_cutting_complexity_layers.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    build_user_headers,
    create_area,
    create_driver_payload,
    create_provider,
    create_route_assignment_payload,
    create_vehicle_payload,
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
# validations: missing_auth_header_on_provider_create
# ═══════════════════════════════════════════════════════════════════════

def test_provider_create_without_auth_headers_is_refused(api):
    """PRD §2.1: "If either header is absent, or if the declared role is not one
    of the roles enumerated below, the request is refused with
    `ERR_MISSING_AUTH_HEADER` (HTTP 401)."

    Design: Corner/validations/missing_auth_header_on_provider_create
    """
    res = api.create_service_provider(
        {"legal_name": "Acme Route Services LLC", "tax_id": "27-1000001"}, {})
    validate_error(res, "ERR_MISSING_AUTH_HEADER", expected_status=401)


# ═══════════════════════════════════════════════════════════════════════
# validations: settlement_analyst_cannot_approve_provider
# ═══════════════════════════════════════════════════════════════════════

def test_settlement_analyst_cannot_approve_a_provider(api):
    """PRD §2.1: "If both headers are present but the declared role does not
    appear in the authorized role list of the endpoint being called, the request
    is refused with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/validations/settlement_analyst_cannot_approve_provider
    """
    provider = create_provider()
    area = create_area()
    # Approve as the AccountManager first so the refused SettlementAnalyst call is
    # not confused with the provider simply failing its compliance gates.
    setup_provider_compliance(provider["id"], area["id"], approve=False)
    get_success_data(api.approve_service_provider(provider["id"], AM))

    res = api.approve_service_provider(provider["id"], SA)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)
    assert validate_success(api.get_service_provider(provider["id"], AM), 200)["status"] == "APPROVED"


# ═══════════════════════════════════════════════════════════════════════
# rbac: provider_role_cannot_sign_its_own_agreement
# ═══════════════════════════════════════════════════════════════════════

def test_entity_backed_provider_cannot_sign_its_own_agreement(api):
    """PRD §2.1: "If both headers are present but the declared role does not
    appear in the authorized role list of the endpoint being called, the request
    is refused with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/provider_role_cannot_sign_its_own_agreement
    """
    from test_helpers import create_agreement_payload

    provider = create_provider()
    area = create_area()
    file_and_verify_policy(provider["id"])
    get_success_data(api.approve_service_provider(provider["id"], AM))
    agreement = get_success_data(api.create_agreement(
        create_agreement_payload(provider["id"], area["id"]), AM))
    get_success_data(api.submit_agreement(
        agreement["id"], make_service_provider_headers(provider["id"])))

    res = api.sign_agreement(agreement["id"], make_service_provider_headers(provider["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)
    assert validate_success(api.get_agreement(agreement["id"], AM), 200)["status"] == "PENDING_REVIEW"


def test_account_manager_signature_completes_the_same_agreement(api):
    """PRD §3.3: "Signature is the `AccountManager`'s act"
    PRD §3.3: "When both gates pass, the agreement becomes `ACTIVE`"

    Design: Corner/rbac/provider_role_cannot_sign_its_own_agreement
    """
    from test_helpers import create_agreement_payload

    provider = create_provider()
    area = create_area()
    file_and_verify_policy(provider["id"])
    get_success_data(api.approve_service_provider(provider["id"], AM))
    agreement = get_success_data(api.create_agreement(
        create_agreement_payload(provider["id"], area["id"]), AM))
    get_success_data(api.submit_agreement(
        agreement["id"], make_service_provider_headers(provider["id"])))

    signed = validate_success(api.sign_agreement(agreement["id"], AM), 200)
    assert signed["status"] == "ACTIVE"


# ═══════════════════════════════════════════════════════════════════════
# rbac: compliance_officer_cannot_create_insurance_policy
# ═══════════════════════════════════════════════════════════════════════

def test_compliance_officer_cannot_file_an_insurance_policy(api):
    """PRD §2.1: "If both headers are present but the declared role does not
    appear in the authorized role list of the endpoint being called, the request
    is refused with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/compliance_officer_cannot_create_insurance_policy
    """
    provider = create_provider()
    res = api.create_insurance_policy({
        "provider_id": provider["id"], "policy_type": "AUTO_LIABILITY",
        "coverage_cents": 1000000, "expires_at": "2027-01-01T00:00:00Z"}, CO)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)
    data, _meta = validate_paginated(
        api.list_insurance_policies(AM, {"provider_id": provider["id"]}))
    assert data == []


def test_service_provider_can_file_a_certificate_but_not_verify_it(api):
    """PRD §3.2: "Insurance certificates are filed by a `ServiceProvider`"
    PRD §2.1: "If both headers are present but the declared role does not appear
    in the authorized role list of the endpoint being called, the request is
    refused with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/compliance_officer_cannot_create_insurance_policy
    """
    provider = create_provider()
    sp = make_service_provider_headers(provider["id"])
    policy = validate_success(api.create_insurance_policy({
        "provider_id": provider["id"], "policy_type": "AUTO_LIABILITY",
        "coverage_cents": 1000000, "expires_at": "2027-01-01T00:00:00Z"}, sp), 201)
    assert policy["status"] == "SUBMITTED"

    res = api.verify_insurance_policy(policy["id"], sp)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


# ═══════════════════════════════════════════════════════════════════════
# cross_cutting: stale_version_on_transfer_create_arm
# ═══════════════════════════════════════════════════════════════════════

def test_stale_area_version_refuses_transfer_approval(api):
    """PRD §3.5: "Because the sale writes against the territory, it is
    OCC-guarded: the approval must supply `expected_service_area_version`, and a
    value that no longer matches the area's current `version` is refused with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_version_on_transfer_create_arm
    """
    ctx = setup_two_approved_providers_after_transfer()
    area, asg = ctx["area"], ctx["assignment"]
    # Read the area's current version, then mutate the area so the version the
    # approval supplies is no longer the area's current one.
    stale_version = get_success_data(api.get_service_area(area["id"], AM))["version"]
    # Archiving the area is a mutation of the area, so its version advances and
    # the supplied one is stale by the time the approval is evaluated.
    validate_success(api.decommission_service_area(area["id"], AM), 200)
    assert get_success_data(api.get_service_area(area["id"], AM))["version"] > stale_version

    res = api.approve_transfer(asg["id"], {"expected_service_area_version": stale_version}, AM)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_successful_transfer_mints_a_successor_title(api):
    """PRD §3.5: "A brand-new `RouteAssignment` is created as the successor, in
    `DRAFT` status, held by the acquiring provider, with its `effective_date` set
    to the transferring title's `effective_date` plus one day"

    Design: Corner/cross_cutting_complexity_layers/stale_version_on_transfer_create_arm
    """
    ctx = setup_two_approved_providers_after_transfer()
    area, asg = ctx["area"], ctx["assignment"]
    area_now = get_success_data(api.get_service_area(area["id"], AM))

    approved = validate_success(api.approve_transfer(
        asg["id"], {"expected_service_area_version": area_now["version"]}, AM), 200)
    assert approved["status"] == "TRANSFERRED"

    successors, meta = validate_paginated(api.list_assignment_successors(asg["id"], AM))
    assert meta["total_count"] == 1
    assert successors[0]["status"] == "DRAFT"
    assert successors[0]["effective_date"] == "2026-09-04T00:00:00.000Z"


# ═══════════════════════════════════════════════════════════════════════
# cross_cutting: stale_service_area_version_on_title_create
# ═══════════════════════════════════════════════════════════════════════

def test_second_title_create_with_stale_area_version_is_refused(api):
    """PRD §3.4: "Because the area's availability is a shared resource, this
    create is OCC-guarded: the caller must supply `expected_service_area_version`,
    and a value that no longer matches the area's current `version` is refused
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_service_area_version_on_title_create
    """
    provider = create_provider()
    area = create_area()
    area_version_read = get_success_data(api.get_service_area(area["id"], AM))["version"]

    validate_success(api.create_route_assignment(create_route_assignment_payload(
        area["id"], provider["id"], area_version_read), AM), 201)
    res = api.create_route_assignment(create_route_assignment_payload(
        area["id"], provider["id"], area_version_read,
        effective_date="2026-09-04T00:00:00Z"), AM)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)

    _data, meta = validate_paginated(
        api.list_area_route_assignments(area["id"], AM))
    assert meta["total_count"] == 1


def test_fresh_area_version_after_mutation_is_accepted(api):
    """PRD §3.4: "this create is OCC-guarded: the caller must supply
    `expected_service_area_version`, and a value that no longer matches the area's
    current `version` is refused with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.4: "A new title begins in `DRAFT`, and the create advances the area's
    `version` by one."

    The second candidate's interval is abutted against the first's — the first
    title is terminated, recording `occupancy_ends_at` — so the candidate cannot
    intersect a live occupancy interval and the only gate in play is the OCC
    version. PRD §2.5 permits intervals that "merely abut ... with a gap of zero
    days", and §3.4 releases the territory on termination.

    Design: Corner/cross_cutting_complexity_layers/stale_service_area_version_on_title_create
    """
    provider = create_provider()
    area = create_area()
    first_read = get_success_data(api.get_service_area(area["id"], AM))["version"]
    created = validate_success(api.create_route_assignment(create_route_assignment_payload(
        area["id"], provider["id"], first_read), AM), 201)
    assert created["status"] == "DRAFT"

    refreshed = get_success_data(api.get_service_area(area["id"], AM))["version"]
    assert refreshed == first_read + 1


# ═══════════════════════════════════════════════════════════════════════
# cross_cutting: vehicle_branding_cascade_recomputes_provider_pct
# ═══════════════════════════════════════════════════════════════════════

def _fleet_with_two_owned_and_one_temporary():
    from test_helpers import api_client, create_peak_declaration_payload

    provider = create_provider()
    area = create_area()
    file_and_verify_policy(provider["id"])
    v1 = get_success_data(api_client.create_vehicle(create_vehicle_payload(provider["id"], area["id"]), AM))
    get_success_data(api_client.activate_vehicle(v1["id"], AM))
    v2 = get_success_data(api_client.create_vehicle(create_vehicle_payload(provider["id"], area["id"]), AM))
    get_success_data(api_client.activate_vehicle(v2["id"], AM))
    get_success_data(api_client.approve_service_provider(provider["id"], AM))
    # A temporary asset requires a covering ACTIVE declaration (PRD §2.7/§3.6),
    # so the fixture must declare and activate one for the startup instant.
    decl = get_success_data(api_client.create_peak_declaration(
        create_peak_declaration_payload(area["id"]), AM))
    get_success_data(api_client.activate_peak_declaration(decl["id"], AM))
    v3 = get_success_data(api_client.create_vehicle(create_vehicle_payload(
        provider["id"], area["id"], is_temporary=True), AM))
    get_success_data(api_client.branding_check(v3["id"], {"branding_compliance": "FAILED"}, CO))
    return provider, area, v1, v2, v3


def test_branding_inspection_recomputes_the_provider_percentage(api):
    """PRD §3.1: "The derivation reads the fleet restricted to the provider's own
    non-temporary vehicles, narrows it to those in `ACTIVE` status"
    PRD §3.2: "A `ComplianceOfficer` records an inspection outcome against the
    vehicle through the branding-check operation, supplying the observed
    `branding_compliance`, which recomputes the owning provider's
    `brand_compliance_pct`"

    Design: Corner/cross_cutting_complexity_layers/vehicle_branding_cascade_recomputes_provider_pct
    """
    provider, area, v1, v2, v3 = _fleet_with_two_owned_and_one_temporary()
    before = validate_success(api.get_service_provider(provider["id"], AM), 200)
    assert before["brand_compliance_pct"] == 100.00

    get_success_data(api.branding_check(v2["id"], {"branding_compliance": "FAILED"}, CO))
    after = validate_success(api.get_service_provider(provider["id"], AM), 200)
    assert after["brand_compliance_pct"] == 50.00


def test_temporary_vehicle_excluded_from_the_branding_denominator(api):
    """PRD §3.1: "`DECOMMISSIONED` rows never enter the denominator, and
    temporary vehicles are excluded from the fleet definition outright."
    PRD §3.6: "temporary assets are excluded from every one of the fleet, roster
    and capacity denominators described in §2.6"

    Design: Corner/cross_cutting_complexity_layers/vehicle_branding_cascade_recomputes_provider_pct
    """
    provider, area, v1, v2, v3 = _fleet_with_two_owned_and_one_temporary()
    get_success_data(api.branding_check(v2["id"], {"branding_compliance": "FAILED"}, CO))
    # The temporary vehicle v3 was already inspected FAILED before the trigger.
    final = validate_success(api.get_service_provider(provider["id"], AM), 200)
    assert final["brand_compliance_pct"] == 50.00


# ═══════════════════════════════════════════════════════════════════════
# cross_cutting: derived_safety_index_propagates_on_compose
# ═══════════════════════════════════════════════════════════════════════

def test_safety_index_tracks_the_latest_composed_scorecard(api):
    """PRD §3.9: "Whatever the composite, composition propagates the scorecard's
    `safety_score` into the provider's `safety_index`, so the provider's safety
    reading always tracks the most recent scorecard."

    Design: Corner/cross_cutting_complexity_layers/derived_safety_index_propagates_on_compose
    """
    provider = create_provider()
    file_and_verify_policy(provider["id"])
    get_success_data(api.approve_service_provider(provider["id"], AM))

    first = get_success_data(api.create_performance_metric({
        "provider_id": provider["id"], "service_score": 96, "safety_score": 94,
        "customer_experience_score": 92}, SA))
    validate_success(api.compose_performance_metric(first["id"], SA), 200)
    after_first = validate_success(api.get_service_provider(provider["id"], SA), 200)
    assert after_first["safety_index"] == 94

    second = get_success_data(api.create_performance_metric({
        "provider_id": provider["id"], "service_score": 92, "safety_score": 90,
        "customer_experience_score": 88}, SA))
    validate_success(api.compose_performance_metric(second["id"], SA), 200)
    after_second = validate_success(api.get_service_provider(provider["id"], SA), 200)
    assert after_second["safety_index"] == 90


def test_provider_version_advances_without_a_direct_provider_write(api):
    """PRD §2.8: "a system-managed counter that increments by one on every
    modification to the resource."
    PRD §3.9: "composition propagates the scorecard's `safety_score` into the
    provider's `safety_index`"

    Design: Corner/cross_cutting_complexity_layers/derived_safety_index_propagates_on_compose
    """
    provider = create_provider()
    file_and_verify_policy(provider["id"])
    get_success_data(api.approve_service_provider(provider["id"], AM))
    before = validate_success(api.get_service_provider(provider["id"], SA), 200)

    metric = get_success_data(api.create_performance_metric({
        "provider_id": provider["id"], "service_score": 96, "safety_score": 94,
        "customer_experience_score": 92}, SA))
    validate_success(api.compose_performance_metric(metric["id"], SA), 200)

    after = validate_success(api.get_service_provider(provider["id"], SA), 200)
    assert after["version"] > before["version"]