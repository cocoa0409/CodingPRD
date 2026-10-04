"""Composite setup helpers.

The workhorse fixture is the dealer onboarding chain (PRD section 3.3):
region -> colorant system -> product line -> dealer (APPLIED) ->
begin-onboarding -> equipment install -> license grant -> PASS calibration
(activates the license) -> INITIAL_STOCK order -> approve -> fulfill ->
invoice (flips inventory_minimum_met) -> activate. DealerPrincipal calls are
identity-threaded with make_dealer_principal_headers(dealer_id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START, TEST_DEFAULTS
from .factories import (
    create_application_payload,
    create_channel_event_payload,
    create_colorant_system_payload,
    create_contractor_payload,
    create_coop_claim_payload,
    create_dealer_payload,
    create_equipment_payload,
    create_formula_payload,
    create_formulation_change_payload,
    create_license_payload,
    create_order_payload,
    create_product_line_payload,
    create_purchase_payload,
    create_region_payload,
)
from .test_users import TEST_USERS, make_dealer_principal_headers

ADMIN = TEST_USERS["platform_admin_headers"]
RM = TEST_USERS["region_manager_headers"]
CD = TEST_USERS["channel_director_headers"]
CLA = TEST_USERS["color_lab_admin_headers"]
ET = TEST_USERS["equipment_tech_headers"]


def set_clock(to_iso8601=CLOCK_START):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def setup_region(**overrides):
    return get_success_data(api_client.create_region(create_region_payload(**overrides), ADMIN))


def setup_system(**overrides):
    return get_success_data(api_client.create_colorant_system(create_colorant_system_payload(**overrides), CLA))


def setup_line(system_id, **overrides):
    return get_success_data(api_client.create_product_line(create_product_line_payload(system_id, **overrides), CLA))


def setup_formula(line_id, **overrides):
    return get_success_data(api_client.create_formula(create_formula_payload(line_id, **overrides), CLA))


def setup_dealer(region_id, **overrides):
    """Create an APPLIED dealer directly. Returns the dealer dict."""
    return get_success_data(api_client.create_dealer(create_dealer_payload(region_id, **overrides), RM))


def setup_onboarding_dealer(region_id, **overrides):
    """APPLIED dealer moved to ONBOARDING. Returns the dealer dict."""
    dealer = setup_dealer(region_id, **overrides)
    get_success_data(api_client.begin_onboarding(dealer["id"], RM))
    return get_success_data(api_client.get_dealer(dealer["id"], RM))


def setup_equipment(dealer_id, system_id, installed_on=CLOCK_START, **overrides):
    return get_success_data(
        api_client.create_equipment(
            create_equipment_payload(dealer_id, system_id, installed_on, **overrides), ET
        )
    )


def setup_license(dealer_id, system_id):
    return get_success_data(api_client.create_license(create_license_payload(dealer_id, system_id), RM))


def record_calibration(equip_id, result, performed_on=CLOCK_START):
    return get_success_data(
        api_client.record_calibration(equip_id, {"performed_on": performed_on, "result": result}, ET)
    )


def place_order(dealer_id, line_id, units=40, purpose="INITIAL_STOCK"):
    return get_success_data(
        api_client.create_order(
            create_order_payload(dealer_id, line_id, units=units, purpose=purpose),
            make_dealer_principal_headers(dealer_id),
        )
    )


def walk_order_to_invoiced(order_id):
    get_success_data(api_client.approve_order(order_id, RM))
    get_success_data(api_client.fulfill_order(order_id, RM))
    return get_success_data(api_client.invoice_order(order_id, RM))


def walk_order_to_paid(order_id, dealer_id):
    walk_order_to_invoiced(order_id)
    return get_success_data(api_client.pay_order(order_id, make_dealer_principal_headers(dealer_id)))


def setup_base(with_line=True, line_overrides=None, system_overrides=None, region_overrides=None):
    """Clock at 2026-09-01 + region + colorant system (+ specialty line).
    Returns a dict of created entities."""
    set_clock()
    out = {}
    out["region"] = setup_region(**(region_overrides or {}))
    out["system"] = setup_system(**(system_overrides or {}))
    if with_line:
        out["line"] = setup_line(out["system"]["id"], **(line_overrides or {}))
    return out


def setup_onboarded_dealer(
    dealer_overrides=None, line_overrides=None, system_overrides=None,
    region_overrides=None, with_line=True, initial_stock_units=None, pay_stock=False,
):
    """Full onboarding chain to an ACTIVE dealer (PRD section 3.3 gates:
    calibrated unit, ACTIVE license, inventory_minimum_met via an invoiced
    INITIAL_STOCK order). Returns a dict with region/system/line/dealer/
    equipment/license/stock_order."""
    out = setup_base(
        with_line=with_line, line_overrides=line_overrides,
        system_overrides=system_overrides, region_overrides=region_overrides,
    )
    dealer = setup_dealer(out["region"]["id"], **(dealer_overrides or {}))
    get_success_data(api_client.begin_onboarding(dealer["id"], RM))
    equip = setup_equipment(dealer["id"], out["system"]["id"])
    lic = setup_license(dealer["id"], out["system"]["id"])
    record_calibration(equip["id"], "PASS")
    stock_order = None
    if with_line:
        units = (
            initial_stock_units
            if initial_stock_units is not None
            else out["system"]["min_initial_inventory_units"]
        )
        stock_order = place_order(dealer["id"], out["line"]["id"], units=units)
        if pay_stock:
            walk_order_to_paid(stock_order["id"], dealer["id"])
        else:
            walk_order_to_invoiced(stock_order["id"])
    get_success_data(api_client.activate_dealer(dealer["id"], RM))
    out["dealer"] = get_success_data(api_client.get_dealer(dealer["id"], RM))
    out["equipment"] = equip
    out["license"] = lic
    out["stock_order"] = stock_order
    return out


def setup_contractor(dealer_id, **overrides):
    return get_success_data(
        api_client.create_contractor(
            create_contractor_payload(dealer_id, **overrides),
            make_dealer_principal_headers(dealer_id),
        )
    )


def post_purchase(dealer_id, contractor_id, line_id, **overrides):
    return get_success_data(
        api_client.create_purchase(
            create_purchase_payload(contractor_id, line_id, **overrides),
            make_dealer_principal_headers(dealer_id),
        )
    )


def seed_rolling_spend(dealer_id, contractor_id, line_id, units, base_price_cents,
                       reward_points_redeemed=0):
    """Post one purchase sized so rolling net spend lands exactly at
    units * base_price_cents - reward_points_redeemed (STANDARD flat pricing,
    since the account starts at 0 spend)."""
    return post_purchase(
        dealer_id, contractor_id, line_id, units=units,
        reward_points_redeemed=reward_points_redeemed,
    )


def setup_effective_change(ctx, effective_date="2026-09-02T00:00:00Z"):
    """Create -> announce (OCC) -> advance clock -> make-effective.
    ctx must contain 'line'. Returns (change, tasks_list)."""
    change = get_success_data(
        api_client.create_formulation_change(
            create_formulation_change_payload(ctx["line"]["id"], effective_date=effective_date), CLA
        )
    )
    get_success_data(
        api_client.announce_formulation_change(
            change["id"], {"expected_change_version": change["version"]}, CLA
        )
    )
    set_clock(effective_date)
    get_success_data(api_client.make_effective_formulation_change(change["id"], CLA))
    change = get_success_data(api_client.get_formulation_change(change["id"], CLA))
    tasks = api_client.list_rematch_tasks(CLA, params={"formulation_change_id": change["id"]})
    return change, tasks


def setup_coop_claim(dealer_id, **overrides):
    return get_success_data(
        api_client.create_coop_claim(
            create_coop_claim_payload(dealer_id, **overrides),
            make_dealer_principal_headers(dealer_id),
        )
    )


def post_channel_event(dealer_id, **overrides):
    return get_success_data(
        api_client.create_channel_event(dealer_id, create_channel_event_payload(**overrides), CD)
    )


def setup_application(region_id, **overrides):
    return get_success_data(api_client.create_application(create_application_payload(region_id, **overrides), RM))
