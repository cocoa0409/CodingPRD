"""Deployments: scope matching, clock ceiling, retirement, mobility hosting gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_hosting_authorization,
    create_active_agreement,
    create_hosting_authorization,
    create_product,
    get_success_data,
    make_customer_admin_headers,
    setup_active_agreement_with_anniversary,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]
LS = TEST_USERS["licensing_specialist_headers"]
AUD = TEST_USERS["auditor_headers"]


def test_deployment_scope_mismatch_with_license_model(api):
    """PRD §3.3: "A `DEVICE` scope pairs only with a `PER_DEVICE` product and requires `device_count` of at least 1."
    PRD §3.3: "The scope must agree with the product's licensing basis, and the scope-dependent numbers must be present and in range, or the report is rejected with `ERR_SCOPE_MISMATCH` (HTTP 422)."

    Design: Corner/validations/deployment_scope_mismatch_with_license_model
    """
    org, agr = create_active_agreement(enrollment_number="E-SCP-1")
    prod = create_product(sku="SM1", license_model="PER_USER")
    resp = api.create_deployment(
        agr["id"],
        {"product_id": prod["id"], "scope": "DEVICE", "deployment_date": "2026-09-01",
         "device_count": 5, "hosting": "ON_PREMISES"},
        make_customer_admin_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_SCOPE_MISMATCH, 422)


def test_clock_default_is_2026_09_01(api):
    """PRD §2.5: "At server startup the logical clock reads exactly 2026-09-01T00:00:00Z and must not advance or fall back to wall-clock time before it is explicitly set."
    PRD §3.3: "The deployment date must not lie in the future of the logical clock; a future date is rejected with `ERR_INVALID_DATE_RANGE` (HTTP 422)."

    Design: Corner/endpoints/clock_default_is_2026_09_01
    """
    org, agr = create_active_agreement(enrollment_number="E-CLK-1")
    prod = create_product(sku="CK1")
    resp = api.create_deployment(
        agr["id"],
        {"product_id": prod["id"], "scope": "USER", "deployment_date": "2026-09-05",
         "user_count": 1, "hosting": "ON_PREMISES"},
        make_customer_admin_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE, 422)


def test_customer_admin_cannot_touch_other_organizations_agreement(api):
    """PRD §2.1: "When `X-User-Role` is `CustomerAdmin`, `X-User-ID` is the `id` of the acting `Organization`; ownership checks on any resource that references an `Organization` compare the resource's owning organization — resolved through the agreement's `organization_id` or the path's organization id — to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/customer_admin_cannot_touch_other_organizations_agreement
    """
    org_a = api.create_organization({"legal_name": "Org A", "qualified_device_count": 100}, PA)
    org_a = validate_success(org_a, 201)
    org_b = api.create_organization({"legal_name": "Org B", "qualified_device_count": 100}, PA)
    org_b = validate_success(org_b, 201)
    resp = api.create_agreement({"organization_id": org_b["id"], "enrollment_number": "E-OWN-1",
                                 "start_date": "2026-09-01", "end_date": "2029-08-31"}, PA)
    agr_b = validate_success(resp, 201)
    act = api.activate_agreement(agr_b["id"], PA)
    assert act.status_code == 200, get_success_data(act)
    prod = create_product(sku="OWN1")
    resp = api.create_deployment(
        agr_b["id"],
        {"product_id": prod["id"], "scope": "USER", "deployment_date": "2026-09-01",
         "user_count": 2, "hosting": "ON_PREMISES"},
        make_customer_admin_headers(org_a["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


def test_third_party_hosting_requires_approved_authorization(api):
    """PRD §3.10: "A `SERVER`-scoped deployment whose `hosting` is `THIRD_PARTY_DATACENTER` is rejected with `ERR_HOSTING_NOT_AUTHORIZED` (HTTP 422) unless both of the following hold: the deployed product's `license_mobility` is true, and there exists a hosting authorization for the same agreement and product in `APPROVED` status whose `effective_on` is on or before the deployment's `deployment_date`."

    Design: Difficulty/cross_entity_state_dependency/third_party_hosting_requires_approved_authorization
    """
    ctx = setup_active_agreement_with_anniversary()
    org, agr = ctx["org"], ctx["agreement"]
    prod = create_product(sku="HP", name="Host Prod", license_model="PER_SERVER_CORE",
                          family="SRV", annual_unit_price_cents=50000, license_mobility=True)
    auth = create_hosting_authorization(agr["id"], org["id"], prod["id"],
                                        provider_name="HosterCo", effective_on="2026-09-01")
    payload = {"product_id": prod["id"], "scope": "SERVER", "deployment_date": "2026-09-01",
               "physical_cores_per_server": 32, "core_factor": 1.0, "vm_count": 0,
               "licensing_mode": "PER_HOST", "hosting": "THIRD_PARTY_DATACENTER"}
    resp = api.create_deployment(agr["id"], payload, make_customer_admin_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_HOSTING_NOT_AUTHORIZED, 422)
    approve_hosting_authorization(auth["id"])
    resp2 = api.create_deployment(agr["id"], payload, make_customer_admin_headers(org["id"]))
    dep = validate_success(resp2, 201)
    assert dep["hosting"] == "THIRD_PARTY_DATACENTER"


def test_suspended_authorization_does_not_gate_deployment(api):
    """PRD §3.10: "A `SERVER`-scoped deployment whose `hosting` is `THIRD_PARTY_DATACENTER` is rejected with `ERR_HOSTING_NOT_AUTHORIZED` (HTTP 422) unless both of the following hold: the deployed product's `license_mobility` is true, and there exists a hosting authorization for the same agreement and product in `APPROVED` status whose `effective_on` is on or before the deployment's `deployment_date`."

    Design: Difficulty/cross_entity_state_dependency/third_party_hosting_requires_approved_authorization
    """
    ctx = setup_active_agreement_with_anniversary()
    org, agr = ctx["org"], ctx["agreement"]
    prod = create_product(sku="HP2", license_model="PER_SERVER_CORE", family="SRV",
                          annual_unit_price_cents=50000, license_mobility=True)
    auth = create_hosting_authorization(agr["id"], org["id"], prod["id"],
                                        provider_name="HosterCo", effective_on="2026-09-01")
    approve_hosting_authorization(auth["id"])
    resp = api.suspend_hosting_authorization(auth["id"], LS)
    assert resp.status_code == 200, get_success_data(resp)
    resp = api.create_deployment(
        agr["id"],
        {"product_id": prod["id"], "scope": "SERVER", "deployment_date": "2026-09-01",
         "physical_cores_per_server": 32, "core_factor": 1.0, "vm_count": 0,
         "licensing_mode": "PER_HOST", "hosting": "THIRD_PARTY_DATACENTER"},
        make_customer_admin_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_HOSTING_NOT_AUTHORIZED, 422)


def test_error_license_mobility_required_on_authorization(api):
    """PRD §3.10: "The product must actually carry mobility rights — requesting authorization for a product whose `license_mobility` flag is false is rejected with `ERR_LICENSE_MOBILITY_REQUIRED` (HTTP 422)".

    Design: Corner/errors/error_license_mobility_required_on_authorization
    """
    ctx = setup_active_agreement_with_anniversary(with_anniversary=False)
    org, agr = ctx["org"], ctx["agreement"]
    prod = create_product(sku="NM1", name="NoMob Srv", license_model="PER_SERVER_CORE",
                          family="SRV", annual_unit_price_cents=50000, license_mobility=False)
    resp = api.create_hosting_authorization(
        agr["id"],
        {"product_id": prod["id"], "provider_name": "HosterCo", "effective_on": "2026-09-01"},
        make_customer_admin_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_LICENSE_MOBILITY_REQUIRED, 422)


def test_hosting_authorization_suspend_reinstate_cycle(api):
    """PRD §3.10: "An approved authorization can later be suspended (`APPROVED → SUSPENDED`) and reinstated (`SUSPENDED → APPROVED`) repeatedly — the cycle permits any number of suspension and reinstatement rounds".

    Design: Difficulty/non_linear_state_machine/hosting_authorization_suspend_reinstate_cycle
    """
    ctx = setup_active_agreement_with_anniversary()
    org, agr = ctx["org"], ctx["agreement"]
    prod = create_product(sku="H1", name="Host Srv", license_model="PER_SERVER_CORE",
                          family="SRV", annual_unit_price_cents=50000, license_mobility=True)
    auth = create_hosting_authorization(agr["id"], org["id"], prod["id"],
                                        provider_name="HosterCo", effective_on="2026-09-01")
    approve_hosting_authorization(auth["id"])
    resp = api.suspend_hosting_authorization(auth["id"], LS)
    data = validate_success(resp, 200)
    assert data["status"] == "SUSPENDED"
    resp = api.reinstate_hosting_authorization(auth["id"], LS)
    data2 = validate_success(resp, 200)
    assert data2["status"] == "APPROVED", "reinstatement returns to the pre-suspension state"


def test_hosting_authorization_revoke_from_approved_is_terminal(api):
    """PRD §3.10: "and can be revoked from either `APPROVED` or `SUSPENDED` into the terminal `REVOKED` state. `DENIED` is also terminal. Any of these transitions attempted from the wrong status is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/hosting_authorization_suspend_reinstate_cycle
    """
    ctx = setup_active_agreement_with_anniversary()
    org, agr = ctx["org"], ctx["agreement"]
    prod = create_product(sku="H2", license_model="PER_SERVER_CORE", family="SRV",
                          annual_unit_price_cents=50000, license_mobility=True)
    auth = create_hosting_authorization(agr["id"], org["id"], prod["id"],
                                        provider_name="HosterCo", effective_on="2026-09-01")
    approve_hosting_authorization(auth["id"])
    resp = api.suspend_hosting_authorization(auth["id"], LS)
    assert validate_success(resp, 200)["status"] == "SUSPENDED"
    resp = api.reinstate_hosting_authorization(auth["id"], LS)
    assert validate_success(resp, 200)["status"] == "APPROVED"
    resp = api.revoke_hosting_authorization(auth["id"], LS)
    assert validate_success(resp, 200)["status"] == "REVOKED"
    resp = api.suspend_hosting_authorization(auth["id"], LS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_hosting_review_from_approved_is_invalid_transition(api):
    """PRD §3.10: "Any of these transitions attempted from the wrong status is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/hosting_review_from_approved_is_invalid_transition
    """
    ctx = setup_active_agreement_with_anniversary(with_anniversary=False)
    org, agr = ctx["org"], ctx["agreement"]
    prod = create_product(sku="HA1", license_model="PER_SERVER_CORE", family="SRV",
                          annual_unit_price_cents=50000, license_mobility=True)
    auth = create_hosting_authorization(agr["id"], org["id"], prod["id"],
                                        provider_name="HosterCo", effective_on="2026-09-01")
    approve_hosting_authorization(auth["id"])
    resp = api.review_hosting_authorization(auth["id"], {"decision": "APPROVE"}, LS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_fk_reverse_reachability_lists(api):
    """PRD §3.5: "Lines of a report can be listed through the report-scoped view".
    PRD §3.7: "Redemption records are append-only (`id` and `created_at` only) and listable per grant."
    PRD §3.9: "Conversions are readable individually, per source entitlement, or through the flat conversion list filtered by `entitlement_id` or `target_product_id`."

    Design: Corner/endpoints/fk_reverse_reachability_lists
    """
    ctx = setup_active_agreement_with_anniversary()
    org, agr, ann = ctx["org"], ctx["agreement"], ctx["anniversary"]
    from test_helpers import (
        add_true_up_line,
        create_benefit_grant,
        create_entitlement,
        create_true_up_report,
        create_user_deployment,
        redeem_benefit,
    )
    p_std = create_product(sku="FKS", name="FK Std", edition="STANDARD", family="CAL",
                           annual_unit_price_cents=100000)
    p_ent = create_product(sku="FKE", name="FK Ent", edition="ENTERPRISE", family="CAL",
                           annual_unit_price_cents=200000)
    ent = create_entitlement(agr["id"], p_std["id"], 10)
    resp = api.create_step_up(ent["id"], {"target_product_id": p_ent["id"], "quantity": 2}, LS)
    assert resp.status_code == 201, get_success_data(resp)
    grant = create_benefit_grant(agr["id"], benefit_type="TRAINING_VOUCHER",
                                 quantity_granted=3, expires_on="2028-01-01")
    redeem_benefit(grant["id"], org["id"], 1)
    create_user_deployment(agr["id"], org["id"], p_std["id"], 12)
    rep = create_true_up_report(agr["id"], org["id"], ann["id"])
    add_true_up_line(rep["id"], org["id"], p_std["id"], months_growth=1,
                     pricing_variant="FULL_YEAR_RETROACTIVE")
    lines, _ = validate_paginated(api.list_lines_of_report(rep["id"], AUD))
    assert len(lines) == 1 and lines[0]["report_id"] == rep["id"]
    reds, _ = validate_paginated(api.list_redemptions_of_grant(grant["id"], AUD))
    assert len(reds) == 1 and reds[0]["grant_id"] == grant["id"]
    convs, _ = validate_paginated(api.list_step_ups_of_entitlement(ent["id"], AUD))
    assert len(convs) == 1 and convs[0]["entitlement_id"] == ent["id"]
