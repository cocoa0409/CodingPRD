"""Composite setup helpers — build the preconditions each claim needs.

Every helper here creates its own entities from scratch: the runner restarts
the service before each test, so no state survives between tests.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories as F
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_franchise_owner_headers,
    make_route_sales_rep_headers,
    make_technician_headers,
)

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["franchise_manager_headers"]
CREDIT_OFFICER = TEST_USERS["credit_officer_headers"]
WARRANTY_ADMIN = TEST_USERS["warranty_admin_headers"]


# --- clock and catalogue ----------------------------------------------------
def set_clock(current_utc):
    return get_success_data(api_client.set_clock(current_utc, PLATFORM_ADMIN))


def create_product(sku="P1", product_name="Torque Wrench", category="POWER_TOOLS",
                   unit_cost_cents=12_000, retail_price_cents=15_000,
                   default_warranty_months=12, is_new_launch=False, launch_iso_week=None):
    payload = F.product_payload(
        sku=sku, product_name=product_name, category=category,
        unit_cost_cents=unit_cost_cents, retail_price_cents=retail_price_cents,
        default_warranty_months=default_warranty_months, is_new_launch=is_new_launch)
    if launch_iso_week:
        payload["launch_iso_week"] = launch_iso_week
    return get_success_data(api_client.create_product(payload, PLATFORM_ADMIN))


# --- franchisee -------------------------------------------------------------
def create_franchisee(legal_name=F.DEFAULTS["LEGAL_NAME"]):
    data = get_success_data(
        api_client.create_franchisee(F.franchisee_payload(legal_name=legal_name),
                                     PLATFORM_ADMIN))
    data["owner_headers"] = make_franchise_owner_headers(data["id"])
    data["rep_headers"] = make_route_sales_rep_headers(data["id"])
    return data


def create_certified_franchisee(legal_name=F.DEFAULTS["LEGAL_NAME"], training_points=45):
    franchisee = create_franchisee(legal_name)
    set_clock("2026-09-07T00:00:00Z")
    get_success_data(api_client.advance_training(
        franchisee["id"], F.training_payload("ENROLL", training_points),
        franchisee["owner_headers"]))
    return franchisee


# --- routes and territory ---------------------------------------------------
def create_route(franchisee, route_code="R1", route_tier="A", zip_codes=None,
                 visit_weekday=1, truck_label="T-01", inventory_invested_cents=100_000,
                 mix_plan="DIAGNOSTIC_WEIGHTED", territory_model="FRANCHISEE_ASSUMED",
                 territory_points=None):
    payload = F.route_payload(
        route_code=route_code, route_tier=route_tier,
        zip_codes=list(zip_codes or ["75001"]), visit_weekday=visit_weekday,
        truck_label=truck_label, inventory_invested_cents=inventory_invested_cents,
        mix_plan=mix_plan, territory_model=territory_model)
    if territory_points is not None:
        payload["territory_points"] = territory_points
    return get_success_data(
        api_client.create_route(franchisee["id"], payload, franchisee["owner_headers"]))


def advance_route(franchisee, route, action, **extra):
    payload = {"action": action}
    payload.update(extra)
    headers = (franchisee["owner_headers"] if action in ("ACTIVATE",)
               else MANAGER)
    return api_client.advance_route_status(route["id"], payload, headers)


def activate_route(franchisee, route):
    return get_success_data(advance_route(franchisee, route, "ACTIVATE"))


def advance_territory(franchisee, route, action, territory_points, headers=None):
    payload = {"action": action, "territory_points": territory_points}
    return api_client.advance_territory(
        route["id"], payload, headers or franchisee["owner_headers"])


def qualify_territory(franchisee, route, points=90):
    return get_success_data(advance_territory(franchisee, route, "DEVELOP", points))


def create_shop(franchisee, route, shop_name="Northside Diesel", street_line="12 Elm",
                zip_code="75001"):
    return get_success_data(api_client.create_shop(
        route["id"], F.shop_payload(shop_name=shop_name, street_line=street_line,
                                    zip_code=zip_code),
        franchisee["owner_headers"]))


def update_shop(franchisee, shop, **fields):
    return api_client.update_shop(shop["id"], fields, franchisee["owner_headers"])


# --- technicians ------------------------------------------------------------
def create_technician(franchisee, shop, full_name="Dana Reyes",
                      credit_line_limit_cents=100_000, months_in_trade=100,
                      employment_verified=True):
    data = get_success_data(api_client.create_technician(
        F.technician_payload(shop["id"], full_name=full_name,
                             credit_line_limit_cents=credit_line_limit_cents,
                             months_in_trade=months_in_trade,
                             employment_verified=employment_verified),
        franchisee["owner_headers"]))
    data["headers"] = make_technician_headers(data["id"])
    return data


# --- credit applications and accounts ---------------------------------------
def file_application(franchisee, shop, technician, requested_limit_cents=50_000,
                     requested_kind="REVOLVING", requested_term_months=None,
                     employment_verified=True, months_in_trade=100,
                     prior_delinquency_count=0, decision_source="FRANCHISEE"):
    payload = F.credit_application_payload(
        technician["id"], requested_limit_cents=requested_limit_cents,
        requested_kind=requested_kind, employment_verified=employment_verified,
        months_in_trade=months_in_trade,
        prior_delinquency_count=prior_delinquency_count,
        decision_source=decision_source)
    if requested_term_months is not None:
        payload["requested_term_months"] = requested_term_months
    headers = (franchisee["owner_headers"] if decision_source == "FRANCHISEE"
               else CREDIT_OFFICER)
    return get_success_data(
        api_client.file_credit_application(shop["id"], payload, headers))


def advance_application(franchisee, application, action):
    headers = (CREDIT_OFFICER if application["decision_source"] == "FRANCHISOR"
               else franchisee["owner_headers"])
    return api_client.advance_application(application["id"], {"action": action}, headers)


def approve_application(franchisee, application, review=False):
    if review:
        advance_application(franchisee, application, "REVIEW")
    return get_success_data(advance_application(franchisee, application, "APPROVE"))


def mint_account(application):
    version = get_success_data(
        api_client.get_credit_application(application["id"], CREDIT_OFFICER))["version"]
    return get_success_data(api_client.mint_credit_account(
        application["id"], {"expected_application_version": version}, CREDIT_OFFICER))


def setup_account(franchisee, shop, technician, requested_limit_cents=50_000,
                  requested_kind="REVOLVING", requested_term_months=None,
                  employment_verified=True, months_in_trade=100,
                  prior_delinquency_count=0, decision_source="FRANCHISEE",
                  review=False):
    """File, approve and mint in one step. Returns the account dict."""
    application = file_application(
        franchisee, shop, technician, requested_limit_cents=requested_limit_cents,
        requested_kind=requested_kind, requested_term_months=requested_term_months,
        employment_verified=employment_verified, months_in_trade=months_in_trade,
        prior_delinquency_count=prior_delinquency_count,
        decision_source=decision_source)
    approve_application(franchisee, application, review=review)
    account = mint_account(application)
    account["application_id_ref"] = application["id"]
    return account


# --- inventory --------------------------------------------------------------
def add_inventory(franchisee, route, product, on_hand_qty, position_id=None):
    payload = F.inventory_position_payload(product["id"], on_hand_qty)
    if position_id:
        payload["inventory_position_id"] = position_id
    return get_success_data(api_client.write_inventory_position(
        route["id"], payload, franchisee["owner_headers"]))


# --- sales orders -----------------------------------------------------------
def create_order(franchisee, route, technician, account, lines,
                 mix_profile="DIAGNOSTIC_WEIGHTED"):
    return get_success_data(api_client.create_sales_order(
        route["id"],
        F.sales_order_payload(technician["id"], account["id"], lines,
                              mix_profile=mix_profile),
        franchisee["rep_headers"]))


def order_line(product, quantity=1, unit_price_cents=None, warranty_months=12):
    return F.sales_order_line(product["id"], quantity, unit_price_cents,
                              warranty_months)


def advance_order(franchisee, order, action, expected_version=None):
    payload = {"action": action}
    if expected_version is not None:
        payload["expected_sales_order_version"] = expected_version
    return api_client.advance_sales_order(order["id"], payload, franchisee["rep_headers"])


def confirm_order(franchisee, order, expected_version=None):
    return get_success_data(advance_order(franchisee, order, "CONFIRM",
                                          expected_version))


def deliver_order(franchisee, order):
    return get_success_data(advance_order(franchisee, order, "DELIVER"))


def create_confirmed_order(franchisee, route, technician, account, lines,
                           mix_profile="DIAGNOSTIC_WEIGHTED"):
    order = create_order(franchisee, route, technician, account, lines, mix_profile)
    confirm_order(franchisee, order, order["version"])
    return order


def create_delivered_order(franchisee, route, technician, account, lines,
                           mix_profile="DIAGNOSTIC_WEIGHTED"):
    order = create_confirmed_order(franchisee, route, technician, account, lines,
                                   mix_profile)
    deliver_order(franchisee, order)
    return order


# --- composite storefront ---------------------------------------------------
def setup_storefront(route_code="R1", visit_weekday=1, mix_plan="DIAGNOSTIC_WEIGHTED",
                     zip_codes=None, territory_points=90, activate=True, tier="A",
                     territory_model="FRANCHISEE_ASSUMED"):
    """Certified franchisee + one route. Returns {"franchisee", "route"}."""
    franchisee = create_certified_franchisee()
    route = create_route(franchisee, route_code=route_code, route_tier=tier,
                         zip_codes=zip_codes, visit_weekday=visit_weekday,
                         mix_plan=mix_plan, territory_model=territory_model)
    if territory_points is not None:
        qualify_territory(franchisee, route, territory_points)
    if activate:
        activate_route(franchisee, route)
    return {"franchisee": franchisee, "route": route}


def setup_shop_and_technician(store, full_name="Dana Reyes",
                              credit_line_limit_cents=100_000, months_in_trade=100,
                              employment_verified=True, shop_name="Northside Diesel",
                              zip_code="75001"):
    """Adds an ACTIVE shop to the storefront route and one technician on it."""
    franchisee = store["franchisee"]
    shop = create_shop(franchisee, store["route"], shop_name=shop_name, zip_code=zip_code)
    technician = create_technician(
        franchisee, shop, full_name=full_name,
        credit_line_limit_cents=credit_line_limit_cents, months_in_trade=months_in_trade,
        employment_verified=employment_verified)
    return {"shop": shop, "technician": technician}


def setup_credit_scenario(store, limit=50_000, kind="REVOLVING", source="FRANCHISEE",
                          term_months=None, months_in_trade=100, verified=True,
                          delinquencies=0, review=False, shop=None, technician=None):
    """Storefront + shop + technician + approved and minted account."""
    people = setup_shop_and_technician(
        store, credit_line_limit_cents=max(limit, 100_000),
        months_in_trade=months_in_trade, employment_verified=verified)
    if shop is not None:
        people["shop"] = shop
    if technician is not None:
        people["technician"] = technician
    account = setup_account(
        store["franchisee"], people["shop"], people["technician"],
        requested_limit_cents=limit, requested_kind=kind,
        requested_term_months=term_months, employment_verified=verified,
        months_in_trade=months_in_trade, prior_delinquency_count=delinquencies,
        decision_source=source, review=review)
    result = dict(store)
    result.update(people)
    result["account"] = account
    return result
