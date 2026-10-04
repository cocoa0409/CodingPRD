"""Composite setup helpers.

Every helper builds its preconditions from scratch against the API (each test
runs against a freshly restarted server with an empty database), and returns a
plain dict of the created resources so tests can reach any id directly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_brand_owner_payload,
    create_territory_payload,
    create_agreement_payload,
    create_product_line_payload,
    create_price_index_payload,
    create_cpo_payload,
    create_nca_payload,
    create_customer_payload,
    create_dsd_order_payload,
    create_equipment_payload,
    create_service_window_payload,
    create_fountain_account_payload,
    create_syrup_delivery_payload,
    create_territory_transfer_payload,
    create_innovation_launch_payload,
    create_fund_entry_payload,
)
from .test_users import TEST_USERS, make_bottler_ops_headers, make_customer_manager_headers
from .constants import TEST_DEFAULTS

PA = TEST_USERS["platform_admin_headers"]
BOA = TEST_USERS["brand_owner_admin_headers"]
FT = TEST_USERS["field_technician_headers"]


# ---------------------------------------------------------------------------
# Tier 1: base seed chain
# ---------------------------------------------------------------------------

def set_clock_default():
    """Pin the logical clock to its startup default (idempotent)."""
    r = api_client.set_clock({"to_iso8601": TEST_DEFAULTS["CLOCK_DEFAULT"]}, PA)
    assert r.status_code == 200, f"Setup failed (set clock): {r.text}"
    return get_success_data(r)


def set_clock(to_iso8601: str):
    r = api_client.set_clock({"to_iso8601": to_iso8601}, PA)
    assert r.status_code == 200, f"Setup failed (set clock): {r.text}"
    return get_success_data(r)


def create_brand_owner(**overrides):
    r = api_client.create_brand_owner(create_brand_owner_payload(**overrides), PA)
    assert r.status_code == 201, f"Setup failed (brand owner): {r.text}"
    return get_success_data(r)


def create_territory(brand_owner_id, **overrides):
    payload = create_territory_payload(brand_owner_id=brand_owner_id, **overrides)
    r = api_client.create_territory(payload, PA)
    assert r.status_code == 201, f"Setup failed (territory): {r.text}"
    return get_success_data(r)


def create_draft_agreement(territory_id, **overrides):
    payload = create_agreement_payload(**overrides)
    r = api_client.create_agreement(territory_id, payload, PA)
    assert r.status_code == 201, f"Setup failed (agreement): {r.text}"
    return get_success_data(r)


def create_product_line(brand_owner_id, **overrides):
    payload = create_product_line_payload(brand_owner_id=brand_owner_id, **overrides)
    r = api_client.create_product_line(payload, BOA)
    assert r.status_code == 201, f"Setup failed (product line): {r.text}"
    return get_success_data(r)


def create_price_index(brand_owner_id, **overrides):
    payload = create_price_index_payload(brand_owner_id=brand_owner_id, **overrides)
    r = api_client.create_price_index(payload, BOA)
    assert r.status_code == 201, f"Setup failed (price index): {r.text}"
    return get_success_data(r)


def activate_agreement(agreement_id):
    r = api_client.activate_agreement(agreement_id, PA)
    assert r.status_code == 200, f"Setup failed (activate): {r.text}"
    return get_success_data(r)


# ---------------------------------------------------------------------------
# Tier 2: canonical ACTIVE agreement seed
# ---------------------------------------------------------------------------

def seed_active_agreement(
    basis="CASE_VOLUME",
    service_budget_cents=1000000,
    with_index=True,
    index_value=110.00,
    index_quarter="2026-Q2",
    line_is_mandatory=True,
    line_base_price=12.0,
    territory_code="SO-ATL-07",
    clock_to=TEST_DEFAULTS["CLOCK_DEFAULT"],
):
    """Brand owner + (optional) price index + product line + territory +
    DRAFT agreement -> activate. Returns a dict with all created resources and
    the agreement's post-activation version as 'ag_v1'.
    """
    set_clock(clock_to)
    bo = create_brand_owner()
    idx = None
    if with_index:
        idx = create_price_index(bo["id"], quarter=index_quarter, index_value=index_value)
    line = create_product_line(
        bo["id"],
        is_mandatory=line_is_mandatory,
        concentrate_base_price_per_gallon=line_base_price,
    )
    ter = create_territory(bo["id"], code=territory_code)
    ag = create_draft_agreement(
        ter["id"],
        marketing_accrual_basis=basis,
        service_budget_cents=service_budget_cents,
    )
    activated = activate_agreement(ag["id"])
    return {
        "bo": bo,
        "index": idx,
        "line": line,
        "territory": ter,
        "agreement": activated,
        "ag_v1": activated["version"],
    }


def ops_headers(env):
    return make_bottler_ops_headers(env["agreement"]["id"])


# ---------------------------------------------------------------------------
# Tier 3: children of an ACTIVE agreement
# ---------------------------------------------------------------------------

def create_customer(env, **overrides):
    payload = create_customer_payload(agreement_id=env["agreement"]["id"], **overrides)
    r = api_client.create_customer(payload, ops_headers(env))
    assert r.status_code == 201, f"Setup failed (customer): {r.text}"
    return get_success_data(r)


def create_dsd_order(env, customer, lines=None, **overrides):
    if lines is None:
        lines = [{
            "product_line_id": env["line"]["id"],
            "quantity_cases": 2,
            "discount_pct": 0,
        }]
    payload = create_dsd_order_payload(customer_id=customer["id"], lines=lines, **overrides)
    r = api_client.create_dsd_order(payload, make_customer_manager_headers(customer["id"]))
    assert r.status_code == 201, f"Setup failed (dsd order): {r.text}"
    return get_success_data(r)


def create_equipment(env, **overrides):
    payload = create_equipment_payload(agreement_id=env["agreement"]["id"], **overrides)
    r = api_client.create_equipment(payload, ops_headers(env))
    assert r.status_code == 201, f"Setup failed (equipment): {r.text}"
    return get_success_data(r)


def place_equipment(env, equipment_id, customer_id,
                    placed_from="2026-09-15", placed_until="2026-12-31"):
    r = api_client.place_equipment(
        equipment_id,
        {"customer_id": customer_id, "placed_from": placed_from, "placed_until": placed_until},
        ops_headers(env),
    )
    assert r.status_code == 200, f"Setup failed (place): {r.text}"
    return get_success_data(r)


def create_service_window(equipment_id, **overrides):
    payload = create_service_window_payload(**overrides)
    r = api_client.create_service_window(equipment_id, payload, FT)
    assert r.status_code == 201, f"Setup failed (service window): {r.text}"
    return get_success_data(r)


def create_cpo(env, quantity_gallons=10000, delivery_quarter="2026-Q3",
               expected_agreement_version=None, line=None):
    payload = create_cpo_payload(
        agreement_id=env["agreement"]["id"],
        product_line_id=(line or env["line"])["id"],
        quantity_gallons=quantity_gallons,
        delivery_quarter=delivery_quarter,
        expected_agreement_version=(
            expected_agreement_version if expected_agreement_version is not None
            else env["ag_v1"]
        ),
    )
    r = api_client.create_cpo(payload, ops_headers(env))
    assert r.status_code == 201, f"Setup failed (cpo): {r.text}"
    return get_success_data(r)


def create_published_nca(env, nca_code="NCA-2026-01", national_price_cents=200,
                         effective_start="2026-09-01", effective_end="2026-12-31"):
    payload = create_nca_payload(
        brand_owner_id=env["bo"]["id"],
        nca_code=nca_code,
        national_price_cents=national_price_cents,
        effective_start=effective_start,
        effective_end=effective_end,
    )
    r = api_client.create_nca(payload, BOA)
    assert r.status_code == 201, f"Setup failed (nca): {r.text}"
    nca = get_success_data(r)
    r = api_client.publish_nca(nca["id"], BOA)
    assert r.status_code == 200, f"Setup failed (publish nca): {r.text}"
    return get_success_data(r)


def create_fountain_account(env, customer):
    r = api_client.create_fountain_account(
        create_fountain_account_payload(customer_id=customer["id"]),
        ops_headers(env),
    )
    assert r.status_code == 201, f"Setup failed (fountain account): {r.text}"
    return get_success_data(r)


def create_territory_transfer(env, reported_ebitda_cents=600000000,
                              buyer_name="Peachtree Consolidated"):
    payload = create_territory_transfer_payload(
        territory_id=env["territory"]["id"],
        buyer_name=buyer_name,
        reported_ebitda_cents=reported_ebitda_cents,
    )
    r = api_client.create_territory_transfer(payload, PA)
    assert r.status_code == 201, f"Setup failed (transfer): {r.text}"
    return get_success_data(r)


def valuate_transfer(transfer_id, expected_transfer_version):
    r = api_client.valuate_transfer(
        transfer_id,
        {"expected_transfer_version": expected_transfer_version},
        BOA,
    )
    assert r.status_code == 200, f"Setup failed (valuate): {r.text}"
    return get_success_data(r)


def create_launch(env, committed_cases=50000, launch_start="2026-09-01",
                  launch_end="2026-10-31", product_line_id=None):
    payload = create_innovation_launch_payload(
        agreement_id=env["agreement"]["id"],
        product_line_id=product_line_id or env["line"]["id"],
        committed_cases=committed_cases,
        launch_start=launch_start,
        launch_end=launch_end,
    )
    r = api_client.create_innovation_launch(payload, BOA)
    assert r.status_code == 201, f"Setup failed (launch): {r.text}"
    return get_success_data(r)


def launch_to_in_production(env, launch_id):
    r = api_client.schedule_changeover(launch_id, ops_headers(env))
    assert r.status_code == 200, f"Setup failed (schedule-changeover): {r.text}"
    r = api_client.complete_changeover(launch_id, ops_headers(env))
    assert r.status_code == 200, f"Setup failed (complete-changeover): {r.text}"
    return get_success_data(r)


def record_sales(env, launch_id, cases):
    r = api_client.record_sales(launch_id, {"cases": cases}, ops_headers(env))
    assert r.status_code == 200, f"Setup failed (record-sales): {r.text}"
    return get_success_data(r)


def post_accrual(env, cases_sold=None, net_revenue_cents=None, period="2026-09"):
    payload = create_fund_entry_payload(
        agreement_id=env["agreement"]["id"],
        entry_type="ACCRUAL",
        period=period,
    )
    if cases_sold is not None:
        payload["cases_sold"] = cases_sold
    if net_revenue_cents is not None:
        payload["net_revenue_cents"] = net_revenue_cents
    r = api_client.create_fund_entry(payload, ops_headers(env))
    assert r.status_code == 201, f"Setup failed (accrual): {r.text}"
    return get_success_data(r)


# ---------------------------------------------------------------------------
# Tier 4: second agreement in a second territory
# ---------------------------------------------------------------------------

def add_second_active_agreement(env, territory_code="NO-ATL-09",
                                region_label="North Atlanta 09",
                                bottler_name="Peachtree Bottling",
                                basis="CASE_VOLUME",
                                service_budget_cents=1000000):
    """Create a second territory + ACTIVE agreement under the same brand."""
    ter2 = create_territory(env["bo"]["id"], code=territory_code, region_label=region_label)
    ag2 = create_draft_agreement(
        ter2["id"],
        bottler_name=bottler_name,
        marketing_accrual_basis=basis,
        service_budget_cents=service_budget_cents,
    )
    ag2_active = activate_agreement(ag2["id"])
    env["territory2"] = ter2
    env["agreement2"] = ag2_active
    env["ag2_v1"] = ag2_active["version"]
    return env
