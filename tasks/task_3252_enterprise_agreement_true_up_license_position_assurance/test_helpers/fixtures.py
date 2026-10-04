"""Composite setup helpers.

Every fixture builds its preconditions from scratch via PRD-declared endpoints:
the server is restarted with an empty database before every test.

Naming: setup_* returns a dict of handles so tests can pick what they need.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .factories import (
    create_agreement_payload,
    create_anniversary_payload,
    create_benefit_grant_payload,
    create_cloud_commitment_payload,
    create_hosting_authorization_payload,
    create_organization_payload,
    create_product_payload,
    create_true_up_line_payload,
)
from .test_users import TEST_USERS, make_customer_admin_headers

PA_HEADERS = TEST_USERS["program_admin_headers"]
LS_HEADERS = TEST_USERS["licensing_specialist_headers"]
AUD_HEADERS = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1: organization / agreement / product / anniversary primitives
# ---------------------------------------------------------------------------

def create_organization(**overrides):
    resp = api.create_organization(create_organization_payload(**overrides), PA_HEADERS)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"organization creation failed: {data}"
    return data


def update_organization_devices(org_id: str, qualified_device_count: int):
    resp = api.update_organization(org_id, {"qualified_device_count": qualified_device_count}, PA_HEADERS)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"organization patch failed: {data}"
    return data


def create_draft_agreement(org_id: str, **overrides):
    resp = api.create_agreement(create_agreement_payload(org_id, **overrides), PA_HEADERS)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"agreement creation failed: {data}"
    return data


def activate_agreement(agr_id: str):
    resp = api.activate_agreement(agr_id, PA_HEADERS)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"agreement activation failed: {data}"
    return data


def create_active_agreement(org_id: str = None, **overrides):
    """Organization (if needed) + ACTIVE agreement. Returns (org, agreement)."""
    org = create_organization() if org_id is None else None
    org_id = org["id"] if org is not None else org_id
    agr = create_draft_agreement(org_id, **overrides)
    agr = activate_agreement(agr["id"])
    return org, agr


def create_product(**overrides):
    resp = api.create_product(create_product_payload(**overrides), PA_HEADERS)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"product creation failed: {data}"
    return data


def register_anniversary(agr_id: str, **overrides):
    resp = api.register_anniversary(agr_id, create_anniversary_payload(**overrides), PA_HEADERS)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"anniversary registration failed: {data}"
    return data


def set_clock(to_iso8601: str):
    resp = api.set_clock(to_iso8601, PA_HEADERS)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"clock set failed: {data}"
    return data


def create_entitlement(agr_id: str, product_id: str, quantity: int = 1):
    resp = api.create_entitlement(agr_id, {"product_id": product_id, "quantity": quantity}, LS_HEADERS)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"entitlement creation failed: {data}"
    return data


def create_user_deployment(agr_id: str, org_id: str, product_id: str, user_count: int, **overrides):
    payload = {"product_id": product_id, "scope": "USER",
               "deployment_date": overrides.pop("deployment_date", "2026-09-01"),
               "user_count": user_count, "hosting": overrides.pop("hosting", "ON_PREMISES")}
    payload.update(overrides)
    resp = api.create_deployment(agr_id, payload, make_customer_admin_headers(org_id))
    data = get_success_data(resp)
    assert resp.status_code == 201, f"user deployment creation failed: {data}"
    return data


def create_device_deployment(agr_id: str, org_id: str, product_id: str, device_count: int, **overrides):
    payload = {"product_id": product_id, "scope": "DEVICE",
               "deployment_date": overrides.pop("deployment_date", "2026-09-01"),
               "device_count": device_count, "hosting": overrides.pop("hosting", "ON_PREMISES")}
    payload.update(overrides)
    resp = api.create_deployment(agr_id, payload, make_customer_admin_headers(org_id))
    data = get_success_data(resp)
    assert resp.status_code == 201, f"device deployment creation failed: {data}"
    return data


def create_server_deployment(agr_id: str, org_id: str, product_id: str, **overrides):
    payload = {"product_id": product_id, "scope": "SERVER",
               "deployment_date": overrides.pop("deployment_date", "2026-09-01"),
               "physical_cores_per_server": overrides.pop("physical_cores_per_server", 32),
               "core_factor": overrides.pop("core_factor", 1.0),
               "vm_count": overrides.pop("vm_count", 0),
               "licensing_mode": overrides.pop("licensing_mode", "PER_HOST"),
               "hosting": overrides.pop("hosting", "ON_PREMISES")}
    payload.update(overrides)
    resp = api.create_deployment(agr_id, payload, make_customer_admin_headers(org_id))
    data = get_success_data(resp)
    assert resp.status_code == 201, f"server deployment creation failed: {data}"
    return data


def create_benefit_grant(agr_id: str, **overrides):
    resp = api.create_benefit_grant(agr_id, create_benefit_grant_payload(**overrides), LS_HEADERS)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"benefit grant creation failed: {data}"
    return data


def redeem_benefit(grant_id: str, org_id: str, quantity: int):
    resp = api.redeem_benefit(grant_id, {"quantity": quantity}, make_customer_admin_headers(org_id))
    data = get_success_data(resp)
    assert resp.status_code == 201, f"redemption failed: {data}"
    return data


def create_cloud_commitment(agr_id: str, **overrides):
    resp = api.create_cloud_commitment(agr_id, create_cloud_commitment_payload(**overrides), LS_HEADERS)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"commitment creation failed: {data}"
    return data


def consume_commitment(com_id: str, org_id: str, requested_cents: int):
    resp = api.consume_commitment(com_id, {"requested_cents": requested_cents}, make_customer_admin_headers(org_id))
    data = get_success_data(resp)
    assert resp.status_code == 201, f"consumption failed: {data}"
    return data


def create_hosting_authorization(agr_id: str, org_id: str, product_id: str, **overrides):
    payload = create_hosting_authorization_payload(product_id, **overrides)
    resp = api.create_hosting_authorization(agr_id, payload, make_customer_admin_headers(org_id))
    data = get_success_data(resp)
    assert resp.status_code == 201, f"hosting authorization creation failed: {data}"
    return data


def approve_hosting_authorization(auth_id: str):
    resp = api.review_hosting_authorization(auth_id, {"decision": "APPROVE"}, LS_HEADERS)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"hosting authorization approve failed: {data}"
    return data


# ---------------------------------------------------------------------------
# Tier 2: agreement-in-ACTIVE with anniversary (the standard true-up context)
# ---------------------------------------------------------------------------

def setup_active_agreement_with_anniversary(org_devices: int = 100, with_anniversary: bool = True,
                                            agreement_overrides: dict = None):
    """Org + ACTIVE agreement (+ open anniversary year 1). Returns
    {'org', 'agreement', 'anniversary'|None, 'customer_headers'}."""
    org = create_organization(qualified_device_count=org_devices)
    agr = create_draft_agreement(org["id"], **(agreement_overrides or {}))
    agr = activate_agreement(agr["id"])
    ann = register_anniversary(agr["id"]) if with_anniversary else None
    return {
        "org": org,
        "agreement": agr,
        "anniversary": ann,
        "customer_headers": make_customer_admin_headers(org["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 3: true-up report lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_true_up_report(agr_id: str, org_id: str, anniversary_id: str):
    resp = api.create_true_up_report(agr_id, {"anniversary_id": anniversary_id},
                                     make_customer_admin_headers(org_id))
    data = get_success_data(resp)
    assert resp.status_code == 201, f"true-up report creation failed: {data}"
    return data


def add_true_up_line(rep_id: str, org_id: str, product_id: str, months_growth: int = 1,
                     pricing_variant: str = "FULL_YEAR_RETROACTIVE"):
    resp = api.add_true_up_line(rep_id, create_true_up_line_payload(
        product_id, months_growth=months_growth, pricing_variant=pricing_variant),
        make_customer_admin_headers(org_id))
    data = get_success_data(resp)
    assert resp.status_code == 201, f"line creation failed: {data}"
    return data


def submit_report(rep_id: str, org_id: str):
    resp = api.submit_true_up_report(rep_id, make_customer_admin_headers(org_id))
    data = get_success_data(resp)
    assert resp.status_code == 200, f"submit failed: {data}"
    return data


def accept_report(rep_id: str):
    resp = api.accept_true_up_report(rep_id, LS_HEADERS)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"accept failed: {data}"
    return data


def reject_report(rep_id: str):
    resp = api.reject_true_up_report(rep_id, LS_HEADERS)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"reject failed: {data}"
    return data


def invoice_report(rep_id: str):
    resp = api.invoice_true_up_report(rep_id, LS_HEADERS)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"invoice failed: {data}"
    return data


def settle_report(rep_id: str):
    resp = api.settle_true_up_report(rep_id, LS_HEADERS)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"settle failed: {data}"
    return data


def setup_report_in_state(target_state: str, org_devices: int = 100, deployment_users: int = 5,
                          entitlement_qty: int = 0, months_growth: int = 1,
                          pricing_variant: str = "FULL_YEAR_RETROACTIVE"):
    """Full lifecycle to a given report state with one PER_USER product.

    Returns dict with org, agreement, anniversary, product, entitlement,
    report, line handles.
    """
    ctx = setup_active_agreement_with_anniversary(org_devices=org_devices)
    org, agr, ann = ctx["org"], ctx["agreement"], ctx["anniversary"]
    product = create_product()
    ent = create_entitlement(agr["id"], product["id"], entitlement_qty) if entitlement_qty else None
    create_user_deployment(agr["id"], org["id"], product["id"], deployment_users)
    rep = create_true_up_report(agr["id"], org["id"], ann["id"])
    line = add_true_up_line(rep["id"], org["id"], product["id"],
                            months_growth=months_growth, pricing_variant=pricing_variant)
    state = "DRAFT"
    if target_state in ("SUBMITTED", "ACCEPTED", "REJECTED", "INVOICED", "SETTLED"):
        rep = submit_report(rep["id"], org["id"]); state = "SUBMITTED"
    if target_state in ("ACCEPTED", "INVOICED", "SETTLED"):
        rep = accept_report(rep["id"]); state = "ACCEPTED"
    if target_state == "REJECTED":
        rep = reject_report(rep["id"]); state = "REJECTED"
    if target_state in ("INVOICED", "SETTLED"):
        rep = invoice_report(rep["id"]); state = "INVOICED"
    if target_state == "SETTLED":
        rep = settle_report(rep["id"]); state = "SETTLED"
    return {
        "org": org, "agreement": agr, "anniversary": ann,
        "product": product, "entitlement": ent, "report": rep, "line": line,
        "customer_headers": make_customer_admin_headers(org["id"]),
    }


def setup_settled_report_with_ratified_baseline(org_devices: int = 100, entitlement_qty: int = 5,
                                                deployment_users: int = 11):
    """Settles a FULL_YEAR_RETROACTIVE report so the entitlement's baseline is
    ratified up to entitlement_qty + (deployment_users - entitlement_qty).
    Returns the standard handle dict."""
    return setup_report_in_state("SETTLED", org_devices=org_devices,
                                 deployment_users=deployment_users,
                                 entitlement_qty=entitlement_qty, months_growth=1)


# ---------------------------------------------------------------------------
# Tier 4: renewal-window agreement in RENEWAL_PENDING
# ---------------------------------------------------------------------------

def setup_agreement_in_renewal_pending(end_date: str = "2029-08-31", clock: str = "2029-07-01T00:00:00Z",
                                       with_anniversaries: int = 0, grants: list = None,
                                       commitments: list = None):
    """ACTIVE agreement moved into RENEWAL_PENDING inside the renewal window.

    grants/commitments: optional lists of create_benefit_grant_payload /
    create_cloud_commitment_payload override dicts, created while the
    agreement is still ACTIVE (PRD §3.1 gates both creations on ACTIVE)."""
    ctx = setup_active_agreement_with_anniversary(with_anniversary=False)
    org, agr = ctx["org"], ctx["agreement"]
    created_grants = [create_benefit_grant(agr["id"], **g) for g in (grants or [])]
    created_commitments = [create_cloud_commitment(agr["id"], **c) for c in (commitments or [])]
    anns = []
    for i in range(1, with_anniversaries + 1):
        anns.append(register_anniversary(agr["id"], year_index=i,
                                         period_start=f"{2025 + i}-09-01",
                                         period_end=f"{2026 + i}-08-31"))
    set_clock(clock)
    resp = api.open_renewal_review(agr["id"], LS_HEADERS)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"renewal-review failed: {data}"
    return {
        "org": org, "agreement": data, "anniversaries": anns,
        "grants": created_grants, "commitments": created_commitments,
        "customer_headers": make_customer_admin_headers(org["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 5: expired / non-renewed terminal agreements
# ---------------------------------------------------------------------------

def setup_expired_agreement(end_date: str = "2026-09-30", clock: str = "2026-10-01T00:00:00Z",
                            org_devices: int = 100):
    """ACTIVE agreement whose term has ended, expired via the clock."""
    org = create_organization(qualified_device_count=org_devices)
    agr = create_draft_agreement(org["id"], end_date=end_date)
    agr = activate_agreement(agr["id"])
    set_clock(clock)
    resp = api.expire_agreement(agr["id"], PA_HEADERS)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"expire failed: {data}"
    return {
        "org": org, "agreement": data,
        "customer_headers": make_customer_admin_headers(org["id"]),
    }


def setup_non_renewed_agreement(org_devices: int = 100):
    """Agreement non-renewed via decline-renewal NON_RENEW inside the window."""
    ctx = setup_agreement_in_renewal_pending()
    org, agr = ctx["org"], ctx["agreement"]
    resp = api.decline_renewal(agr["id"], {"decision": "NON_RENEW"}, ctx["customer_headers"])
    data = get_success_data(resp)
    assert resp.status_code == 200, f"decline-renewal failed: {data}"
    return {
        "org": org, "agreement": data, "anniversaries": ctx["anniversaries"],
        "customer_headers": ctx["customer_headers"],
    }


# ---------------------------------------------------------------------------
# Composite: snapshot-producing context
# ---------------------------------------------------------------------------

def setup_snapshot_context(deployments: list, products: list = None, entitlements: dict = None,
                           org_devices: int = 100):
    """Org + ACTIVE agreement + open anniversary 1 + products + deployments.

    - products: list of product override dicts for create_product.
    - deployments: list of dicts, each with 'product_index' plus
      create_*_deployment kwargs (scope chosen via 'scope' key).
    - entitlements: optional dict {product_index: quantity}.

    Returns dict with org, agreement, anniversary, products, deployments,
    entitlements (list), customer_headers.
    """
    ctx = setup_active_agreement_with_anniversary(org_devices=org_devices)
    org, agr, ann = ctx["org"], ctx["agreement"], ctx["anniversary"]
    products = [create_product(**(p or {})) for p in (products or [{}])]
    ents = []
    for idx, qty in (entitlements or {}).items():
        ents.append(create_entitlement(agr["id"], products[idx]["id"], qty))
    deps = []
    for d in deployments:
        d = dict(d)
        idx = d.pop("product_index", 0)
        scope = d.pop("scope", "USER")
        pid = products[idx]["id"]
        if scope == "USER":
            deps.append(create_user_deployment(agr["id"], org["id"], pid, d.pop("user_count"), **d))
        elif scope == "DEVICE":
            deps.append(create_device_deployment(agr["id"], org["id"], pid, d.pop("device_count"), **d))
        else:
            deps.append(create_server_deployment(agr["id"], org["id"], pid, **d))
    return {
        "org": org, "agreement": agr, "anniversary": ann, "products": products,
        "deployments": deps, "entitlements": ents,
        "customer_headers": make_customer_admin_headers(org["id"]),
    }
