"""License position snapshots: core normalization, filtering, pinning, sweeps."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_benefit_grant,
    create_entitlement,
    create_product,
    get_success_data,
    make_customer_admin_headers,
    setup_active_agreement_with_anniversary,
    setup_snapshot_context,
    validate_error,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]
LS = TEST_USERS["licensing_specialist_headers"]


def _compute_snapshot(api, agr_id, ann_id, headers=LS):
    resp = api.create_snapshot(agr_id, {"anniversary_id": ann_id}, headers)
    return validate_success(resp, 201)


def test_server_core_per_host_vs_per_vm_divergence(api):
    """PRD §3.4: "If `licensing_mode` is `PER_HOST`, the deployment likewise licenses the full host demand and may run unlimited virtual machines. If `licensing_mode` is `PER_VM` with at least one virtual machine, each VM requires the larger of its `vcores_per_vm` and 8 cores, the VM total is `vm_count` times that per-VM requirement, and the deployment's contribution is that VM total capped at the host demand — the deployment never owes more than the full normalized host."

    Design: Difficulty/dual_variant_calc/server_core_per_host_vs_per_vm_divergence
    """
    ctx = setup_snapshot_context(
        products=[{"sku": "SVR1", "name": "Server Std", "license_model": "PER_SERVER_CORE",
                   "license_kind": "SUBSCRIPTION", "edition": "STANDARD", "family": "SRV",
                   "annual_unit_price_cents": 50000, "license_mobility": True}],
        deployments=[
            {"scope": "SERVER", "physical_cores_per_server": 64, "core_factor": 1.0,
             "vm_count": 2, "vcores_per_vm": 4, "licensing_mode": "PER_HOST"},
            {"scope": "SERVER", "physical_cores_per_server": 64, "core_factor": 1.0,
             "vm_count": 2, "vcores_per_vm": 4, "licensing_mode": "PER_VM"},
        ],
    )
    snap = _compute_snapshot(api, ctx["agreement"]["id"], ctx["anniversary"]["id"])
    assert len(snap["lines"]) == 1
    line = snap["lines"][0]
    # PER_HOST host contributes 64; PER_VM host contributes min(64, 2*8)=16.
    assert line["required_licenses"] == 80
    assert line["entitled_quantity"] == 0
    assert line["net_position"] == -80


def test_server_core_bare_metal_minimum_16_cores(api):
    """PRD §3.4: "The host demand is that normalized count, but never less than 16 cores — a host always licenses for at least sixteen cores regardless of its actual silicon. If the host runs no virtual machines (`vm_count` of zero), the deployment is treated as bare metal and always licenses the full host demand."

    Design: Difficulty/dual_variant_calc/server_core_per_host_vs_per_vm_divergence
    """
    ctx = setup_snapshot_context(
        products=[{"license_model": "PER_SERVER_CORE", "family": "SRV", "license_mobility": True}],
        deployments=[
            {"scope": "SERVER", "physical_cores_per_server": 8, "core_factor": 1.0,
             "vm_count": 0, "licensing_mode": "PER_HOST"},
            {"scope": "SERVER", "physical_cores_per_server": 32, "core_factor": 1.0,
             "vm_count": 0, "licensing_mode": "PER_HOST"},
        ],
    )
    snap = _compute_snapshot(api, ctx["agreement"]["id"], ctx["anniversary"]["id"])
    line = snap["lines"][0]
    assert line["required_licenses"] == 16 + 32  # bare-metal hosts, min 16 each


def test_per_vm_cap_minimum_three_way_interaction(api):
    """PRD §3.4: "The host's normalized physical core count is `physical_cores_per_server` multiplied by `core_factor`, rounded up to the next whole core. The host demand is that normalized count, but never less than 16 cores — a host always licenses for at least sixteen cores regardless of its actual silicon. ... If `licensing_mode` is `PER_VM` with at least one virtual machine, each VM requires the larger of its `vcores_per_vm` and 8 cores, the VM total is `vm_count` times that per-VM requirement, and the deployment's contribution is that VM total capped at the host demand — the deployment never owes more than the full normalized host."

    Design: Difficulty/combinatorial_formula/per_vm_cap_minimum_three_way_interaction
    """
    ctx = setup_snapshot_context(
        products=[{"sku": "SVR2", "name": "Server Ent", "license_model": "PER_SERVER_CORE",
                   "license_kind": "PERPETUAL", "edition": "ENTERPRISE", "family": "SRV",
                   "annual_unit_price_cents": 80000, "license_mobility": True}],
        deployments=[
            {"scope": "SERVER", "physical_cores_per_server": 20, "core_factor": 0.75,
             "vm_count": 4, "vcores_per_vm": 4, "licensing_mode": "PER_VM"},
        ],
    )
    snap = _compute_snapshot(api, ctx["agreement"]["id"], ctx["anniversary"]["id"])
    line = snap["lines"][0]
    # normalized host = max(16, ceil(20*0.75)) = 16 caps VM demand 4*max(8,4)=32; min(16,32)=16
    assert line["required_licenses"] == 16
    assert line["net_position"] == -16


def test_per_vm_vm_demand_below_host_demand(api):
    """PRD §3.4: "If `licensing_mode` is `PER_VM` with at least one virtual machine, each VM requires the larger of its `vcores_per_vm` and 8 cores, the VM total is `vm_count` times that per-VM requirement, and the deployment's contribution is that VM total capped at the host demand — the deployment never owes more than the full normalized host."

    Design: Difficulty/combinatorial_formula/per_vm_cap_minimum_three_way_interaction
    """
    ctx = setup_snapshot_context(
        products=[{"license_model": "PER_SERVER_CORE", "family": "SRV", "license_mobility": True}],
        deployments=[
            {"scope": "SERVER", "physical_cores_per_server": 64, "core_factor": 1.0,
             "vm_count": 3, "vcores_per_vm": 10, "licensing_mode": "PER_VM"},
        ],
    )
    snap = _compute_snapshot(api, ctx["agreement"]["id"], ctx["anniversary"]["id"])
    line = snap["lines"][0]
    # VM demand 3 * max(8,10) = 30 < host demand 64 -> contribution 30
    assert line["required_licenses"] == 30


def test_snapshot_immutability_no_version_field(api):
    """PRD §2.4: "a license position snapshot and a benefit redemption, a cloud consumption event, and a shortfall assessment are append-only computation records — each carries `id` and `created_at` only, and neither `updated_at` nor `version` exists on them."

    Design: Corner/entities/snapshot_immutability_no_version_field
    """
    ctx = setup_snapshot_context(
        products=[{"sku": "SN1"}],
        deployments=[{"scope": "USER", "user_count": 2}],
    )
    snap = _compute_snapshot(api, ctx["agreement"]["id"], ctx["anniversary"]["id"])
    assert "version" not in snap, "snapshots are append-only: no version field"
    assert "updated_at" not in snap, "snapshots are append-only: no updated_at field"
    assert snap["lines"][0]["required_licenses"] == 2
    assert snap["lines"][0]["net_position"] == -2


def test_snapshot_excludes_retired_and_future_deployments(api):
    """PRD §3.4: "Only deployments with `retired` false and a `deployment_date` on or before the current logical clock date count."
    PRD §3.3: "Retired deployments are excluded from every future license-position computation".

    Design: Corner/calculations/snapshot_excludes_retired_and_future_deployments
    """
    ctx = setup_snapshot_context(
        products=[{"sku": "FLT1"}],
        deployments=[{"scope": "USER", "user_count": 5}, {"scope": "USER", "user_count": 10}],
    )
    org, agr, ann = ctx["org"], ctx["agreement"], ctx["anniversary"]
    resp = api.retire_deployment(ctx["deployments"][1]["id"], make_customer_admin_headers(org["id"]))
    assert resp.status_code == 200, get_success_data(resp)
    snap = _compute_snapshot(api, agr["id"], ann["id"])
    assert snap["lines"][0]["required_licenses"] == 5, "retired 10-user deployment must be excluded"


def test_snapshot_creation_blocked_on_closed_anniversary(api):
    """PRD §3.4: "The target anniversary must be open: if its `true_up_closed` flag is already true, the request is rejected with `ERR_ANNIVERSARY_CLOSED` (HTTP 409)."

    Design: Corner/validations/snapshot_creation_blocked_on_closed_anniversary
    """
    from test_helpers import setup_report_in_state
    ctx = setup_report_in_state("SETTLED", deployment_users=6, entitlement_qty=5)
    agr, ann = ctx["agreement"], ctx["anniversary"]
    resp = api.create_snapshot(agr["id"], {"anniversary_id": ann["id"]}, LS)
    validate_error(resp, ApiErrorId.ERR_ANNIVERSARY_CLOSED, 409)


def test_grant_expiry_sweep_on_snapshot_creation(api):
    """PRD §3.4: "Computing a snapshot also triggers the benefit-expiry sweep described in §3.7."
    PRD §3.7: "whenever an anniversary is registered and whenever a license position snapshot is computed, the server sweeps the agreement's grants — every grant still `ACTIVE` whose `expires_on` is before the current logical clock date moves `ACTIVE → EXPIRED`."

    Design: Corner/cross_cutting_layers/grant_expiry_sweep_on_snapshot_creation
    """
    from test_helpers import set_clock
    ctx = setup_active_agreement_with_anniversary()
    org, agr, ann = ctx["org"], ctx["agreement"], ctx["anniversary"]
    grant = create_benefit_grant(agr["id"], benefit_type="SUPPORT_INCIDENT",
                                 quantity_granted=2, expires_on="2026-12-31")
    prod = create_product(sku="SW1")
    resp = api.create_deployment(
        agr["id"],
        {"product_id": prod["id"], "scope": "USER", "deployment_date": "2026-09-01",
         "user_count": 1, "hosting": "ON_PREMISES"},
        make_customer_admin_headers(org["id"]),
    )
    assert resp.status_code == 201, get_success_data(resp)
    set_clock("2027-01-15T00:00:00Z")
    _compute_snapshot(api, agr["id"], ann["id"])
    grant_after = get_success_data(api.get_benefit_grant(grant["id"], LS))
    assert grant_after["status"] == "EXPIRED", "snapshot computation must sweep expired grants"


def test_shortfall_projection_subscription_lapses_perpetual_survives(api):
    """PRD §3.6: "the `perpetual_quantity` as the summed quantity of entitlements whose product's `license_kind` is `PERPETUAL`; the `subscription_quantity` as the summed quantity of entitlements whose product is `SUBSCRIPTION`; the `effective_coverage` equal to the perpetual quantity alone — subscription coverage ends with the agreement, while perpetual licenses survive at full quantity — and the `shortfall` as the required licenses minus the effective coverage, floored at zero."

    Design: Corner/calculations/shortfall_projection_subscription_lapses_perpetual_survives
    """
    ctx = setup_active_agreement_with_anniversary(with_anniversary=False)
    org, agr = ctx["org"], ctx["agreement"]
    p_perp = create_product(sku="SHP", name="Perp Dev", license_model="PER_DEVICE",
                            license_kind="PERPETUAL", edition="STANDARD", family="DEV",
                            annual_unit_price_cents=60000, license_mobility=False)
    p_subs = create_product(sku="SHS", name="Subs Dev", license_model="PER_DEVICE",
                            license_kind="SUBSCRIPTION", edition="STANDARD", family="DEV",
                            annual_unit_price_cents=60000, license_mobility=False)
    create_entitlement(agr["id"], p_perp["id"], 25)
    create_entitlement(agr["id"], p_subs["id"], 20)
    from test_helpers import create_device_deployment, set_clock
    create_device_deployment(agr["id"], org["id"], p_perp["id"], 40)
    create_device_deployment(agr["id"], org["id"], p_subs["id"], 40)
    set_clock("2029-07-01T00:00:00Z")
    resp = api.open_renewal_review(agr["id"], LS)
    assert resp.status_code == 200, get_success_data(resp)
    resp = api.decline_renewal(agr["id"], {"decision": "NON_RENEW"}, ctx["customer_headers"])
    assert resp.status_code == 200, get_success_data(resp)
    resp = api.assess_shortfall(agr["id"], LS)
    data = validate_success(resp, 200)
    lines = {line["product_id"]: line for line in data["lines"]}
    perp = lines[p_perp["id"]]
    assert perp["required_licenses"] == 40
    assert perp["perpetual_quantity"] == 25
    assert perp["effective_coverage"] == 25
    assert perp["shortfall"] == 15
    subs = lines[p_subs["id"]]
    assert subs["required_licenses"] == 40
    assert subs["subscription_quantity"] == 20
    assert subs["effective_coverage"] == 0, "subscription coverage ends with the agreement"
    assert subs["shortfall"] == 40
    assert data["agreement_status"] == "NON_RENEWED"


def test_shortfall_assessment_rejected_on_active_agreement(api):
    """PRD §3.6: "Once an agreement is `EXPIRED` or `NON_RENEWED`, a `LicensingSpecialist` or `Auditor` may request its effective license shortfall exposure."

    Design: Corner/endpoints/shortfall_assessment_rejected_on_active_agreement
    """
    ctx = setup_active_agreement_with_anniversary(with_anniversary=False)
    resp = api.assess_shortfall(ctx["agreement"]["id"], LS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
