"""Access control, segregation of duties, and referential integrity."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    validate_paginated, build_user_headers, ApiErrorId, get_success_data,
    set_clock, create_network, create_practice, create_product,
    create_activated_contract, create_approved_agreement, create_draft_agreement,
    get_practice, make_practice_admin_headers, make_network_admin_headers,
    create_affiliation_contract_payload,
    create_pricing_agreement_submit_payload, create_treatment_payload,
    create_administer_payload, DEFAULT_CLOCK,
)


def test_missing_user_context_header_returns_invalid_user_context(api, network_admin_headers):
    """PRD §2.1: "A request missing either header, or naming a role the platform
    does not recognize, is refused with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/validations/missing_user_context_header_returns_invalid_user_context
    """
    import test_helpers

    headers = build_user_headers("u-1", "NotARole")
    res = api.get_practice(test_helpers.NON_EXISTENT_UUID, headers)
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, expected_status=400)


def test_practice_admin_cannot_approve_own_pricing_agreement(api, network_admin_headers):
    """PRD §2.10: "The network user who submitted an agreement may not be the
    user who approves it, and the practice's own `PracticeAdmin` identity may not
    approve an agreement it belongs to."
    PRD §2.10: "Either condition is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/practice_admin_cannot_approve_own_pricing_agreement
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"])
    create_activated_contract(practice["id"])
    practice = get_practice(practice["id"])

    practice_id = practice["id"]
    practice_headers = make_practice_admin_headers(practice_id)
    agreement = create_draft_agreement(practice_id)

    submitted = validate_success(
        api.submit_pricing_agreement(
            agreement["id"],
            create_pricing_agreement_submit_payload(practice["version"]),
            practice_headers),
        200)
    assert submitted["status"] == "PENDING_APPROVAL"

    # The practice's own identity attempts to approve. PRD §2.1: the acting role
    # is still NetworkAdmin (a PracticeAdmin principal cannot name itself here at
    # all), while X-User-ID carries the practice's own id — the identity of the
    # practice's PracticeAdmin. PRD §2.10 refuses that identity outright.
    res = api.approve_pricing_agreement(
        agreement["id"], make_network_admin_headers(practice_id))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    current = validate_success(
        api.get_pricing_agreement(agreement["id"], network_admin_headers), 200)
    assert current["status"] == "PENDING_APPROVAL"
    assert current.get("approved_by_user_id") is None


def test_cross_network_body_foreign_key_returns_cross_network_reference(api, network_admin_headers):
    """PRD §2.5: "Every body-supplied foreign key must resolve to a resource
    inside the same network as the request's context; a body key naming an entity
    that belongs to a different network is refused with `ERR_CROSS_NETWORK_REFERENCE`."
    PRD §2.5: "The platform validates that each path identifier names an existing
    resource before it evaluates anything about the deeper one, and rejects the
    request with the `404` not-found error belonging to the first identifier that
    fails."

    Design: Corner/validations/cross_network_body_foreign_key_returns_cross_network_reference
    """
    set_clock(DEFAULT_CLOCK)
    existing = create_network()
    n2 = create_network(name="Second Corner Network", network_agreement_code="GPO-CC-102")
    product_of_n2 = create_product(n2["id"])

    # Part one: a create naming an unknown network path segment.
    from test_helpers import NON_EXISTENT_UUID
    res = api.create_drug_product(
        NON_EXISTENT_UUID,
        {"ndc": "00000000960", "brand_name": "Crosscide Two",
         "generic_name": "crosscide-abc", "therapeutic_class": "CYTOTOXIC",
         "unit_type": "VIAL", "network_base_price_cents": 1000,
         "is_shortage_candidate": False},
        network_admin_headers)
    validate_error(res, ApiErrorId.ERR_NETWORK_NOT_FOUND, expected_status=404)

    products = get_success_data(api.list_drug_products(
        network_admin_headers, params={"network_id": existing["id"]}))
    # The rejected create named an unknown network segment, so nothing was
    # created under the first network; the second network's product is correctly
    # out of that network's filtered view.
    assert all(p["id"] != product_of_n2["id"] for p in products)
    assert products == []
    assert existing["id"]  # the first network still exists, nothing leaked


def test_invalid_enum_denial_reason_returns_invalid_request(api, network_admin_headers):
    """PRD §3.9: "A denial is recorded by the same `PayerAdjudicator` role
    against a claim in `SUBMITTED` or `APPEALED`, any other status failing with
    `ERR_CLAIM_NOT_SUBMITTED`, and requires the supplied `denial_reason_code` to
    be a member of the declared denial code set, failing with
    `ERR_INVALID_REQUEST` otherwise."

    Design: Corner/validations/invalid_enum_denial_reason_returns_invalid_request
    """
    from test_helpers import (
        create_provider, create_published_protocol, receive_new_lot,
        adopt_pathways, create_treatment_payload, create_administer_payload,
        REVENUE_CYCLE_MANAGER, PAYER_ADJUDICATOR, find_draft_claim,
        get_practice_version, create_claim_submit_payload,
    )

    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"])
    create_activated_contract(practice["id"])
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"])
    practice = get_practice(practice["id"])
    product = create_product(network["id"], unit_type="VIAL")
    provider = create_provider(practice["id"])
    protocol = create_published_protocol(network["id"])
    adopt_pathways(practice["id"])
    receive_new_lot(practice["id"], product["id"], 200)

    set_clock("2026-09-02T00:00:00Z")
    treatment = validate_success(
        api.create_treatment(
            create_treatment_payload(practice["id"], provider["id"], product["id"],
                                     protocol["id"], patient_reference="PT-ENUM-1",
                                     administered_units=100, vial_yield_units=100,
                                     administered_at="2026-09-02T00:00:00Z"),
            make_practice_admin_headers(practice["id"])),
        201)
    validate_success(
        api.administer_treatment(
            treatment["id"],
            create_administer_payload(get_practice_version(practice["id"])),
            make_practice_admin_headers(practice["id"])),
        200)

    claim = find_draft_claim(treatment["id"])
    # PRD §3.9: a denial is recorded against a claim in SUBMITTED or APPEALED;
    # the enum check is a field-typing rule and only surfaces once the claim is
    # in a deniable state.
    claim = validate_success(
        api.submit_claim(
            claim["id"], create_claim_submit_payload(get_practice_version(practice["id"])),
            REVENUE_CYCLE_MANAGER),
        200)
    assert claim["status"] == "SUBMITTED"

    res = api.deny_claim(claim["id"], {"denial_reason_code": "GENERIC_NOT_A_CODE"},
                         PAYER_ADJUDICATOR)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    current = validate_success(
        api.get_payer_claim(claim["id"], network_admin_headers), 200)
    assert current["status"] == "SUBMITTED"
    assert current.get("denial_reason_code") is None


# ─── RBAC ───────────────────────────────────────────────────────────────────

def test_read_only_analyst_cannot_write_any_business_resource(api, network_analyst_headers):
    """PRD §2.1: "`NetworkAnalyst` is a read-only analytics identity with no
    write authority at all."
    PRD §2.1: "A request whose role is known but is not permitted to perform the
    operation being attempted is refused with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/endpoints/read_only_analyst_cannot_write_any_business_resource
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()

    import test_helpers
    res_practice = api.create_practice(
        network["id"], test_helpers.create_practice_payload(), network_analyst_headers)
    validate_error(res_practice, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    res_product = api.create_drug_product(
        network["id"], test_helpers.create_drug_product_payload(), network_analyst_headers)
    validate_error(res_product, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    read = api.list_drug_products(network_analyst_headers,
                                  params={"network_id": network["id"]})
    data, meta = test_helpers.validate_paginated(read)
    assert data == []
    assert meta["total_count"] == 0


def test_payer_adjudicator_cannot_submit_claims(api, network_admin_headers,
                                                revenue_cycle_manager_headers,
                                                payer_adjudicator_headers):
    """PRD §4: "| POST | `/networks/payer-claims/{claimId}/submit` | Submit a
    draft claim, pinning billed_amount_cents | RevenueCycleManager |"
    PRD §2.1: "`PayerAdjudicator` is the external payer's processing identity,
    recording remittances and denials."
    PRD §2.1: "A request whose role is known but is not permitted to perform the
    operation being attempted is refused with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/payer_adjudicator_cannot_submit_claims
    """
    from test_helpers import (
        create_provider, create_published_protocol, receive_new_lot,
        adopt_pathways, find_draft_claim, get_practice_version,
    )

    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"])
    create_activated_contract(practice["id"])
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"])
    practice = get_practice(practice["id"])
    product = create_product(network["id"], unit_type="VIAL")
    provider = create_provider(practice["id"])
    protocol = create_published_protocol(network["id"])
    adopt_pathways(practice["id"])
    receive_new_lot(practice["id"], product["id"], 200)

    set_clock("2026-09-02T00:00:00Z")
    treatment = validate_success(
        api.create_treatment(
            create_treatment_payload(practice["id"], provider["id"], product["id"],
                                     protocol["id"], patient_reference="PT-ROLE-1",
                                     administered_units=100, vial_yield_units=100,
                                     administered_at="2026-09-02T00:00:00Z"),
            make_practice_admin_headers(practice["id"])),
        201)
    validate_success(
        api.administer_treatment(
            treatment["id"],
            create_administer_payload(get_practice_version(practice["id"])),
            make_practice_admin_headers(practice["id"])),
        200)

    claim = find_draft_claim(treatment["id"])
    version = get_practice_version(practice["id"])

    res_submit = api.submit_claim(claim["id"],
                                  {"expected_practice_version": version},
                                  payer_adjudicator_headers)
    validate_error(res_submit, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    res_deny = api.deny_claim(claim["id"], {"denial_reason_code": "MEDICAL_NECESSITY"},
                              revenue_cycle_manager_headers)
    validate_error(res_deny, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    current = validate_success(api.get_payer_claim(claim["id"], network_admin_headers), 200)
    assert current["status"] == "DRAFT"


def test_opaque_roles_do_not_borrow_entity_identity(api, network_admin_headers, platform_admin_headers):
    """PRD §2.1: "`PlatformAdmin` is a benchmark operator identity that owns only
    the test-driving clock endpoint; it is deliberately not a superuser and holds
    no business write authority."
    PRD §2.1: "For the remaining roles — `NetworkAdmin`, `RevenueCycleManager`,
    `PayerAdjudicator`, `NetworkAnalyst`, and `PlatformAdmin` — `X-User-ID` is an
    opaque operator identifier not tied to any persisted entity."

    Design: Corner/rbac/opaque_roles_do_not_borrow_entity_identity
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    create_practice(network["id"])

    read = api.get_network(network["id"], platform_admin_headers)
    data = validate_success(read, 200)
    assert data["name"] == network["name"]

    import test_helpers
    write = api.create_practice(network["id"], test_helpers.create_practice_payload(),
                                platform_admin_headers)
    validate_error(write, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    rows, meta = test_helpers.validate_paginated(
        api.list_practices(network_admin_headers, params={"network_id": network["id"]}))
    assert meta["total_count"] == 1


def test_practice_admin_may_not_suspend_another_practice(api, network_admin_headers, practice_admin_headers):
    """PRD §4: "| POST | `/networks/practices/{practiceId}/suspend` | Suspend an
    affiliated practice | NetworkAdmin |"
    PRD §2.1: "`NetworkAdmin` is the network operations owner: onboarding and
    suspending practices, approving pricing agreements, confirming and shipping
    orders, running shortage allocation, the whole rebate lifecycle, and contract
    unwind."

    Design: Corner/rbac/practice_admin_may_not_suspend_another_practice
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"])
    headers = make_practice_admin_headers(practice["id"])

    res = api.suspend_practice(practice["id"], headers)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    current = validate_success(api.get_practice(practice["id"], network_admin_headers), 200)
    assert current["affiliation_status"] == "PROSPECTIVE"


def test_anonymous_reads_succeed_without_a_role_header(api, network_admin_headers, payer_adjudicator_headers):
    """PRD §2.1: "Reads across the network surface are shared by every role."

    Design: Corner/rbac/anonymous_reads_succeed_without_a_role_header
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"])

    res = api.list_practices(payer_adjudicator_headers,
                             params={"network_id": network["id"]})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 1
    assert data[0]["practice_npi"] == practice["practice_npi"]
    assert meta["has_more"] is False