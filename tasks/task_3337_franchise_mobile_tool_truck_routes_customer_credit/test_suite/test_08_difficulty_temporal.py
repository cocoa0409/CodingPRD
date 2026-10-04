"""Difficulty queue A — resource_temporal_overlap: window semantics."""
from test_helpers import (
    MANAGER,
    advance_territory,
    api_client,
    create_certified_franchisee,
    create_delivered_order,
    create_route,
    create_shop,
    create_technician,
    get_account,
    get_franchisee,
    get_route,
    list_charges,
    order_line,
    qualify_territory,
    set_clock,
    setup_account,
    setup_product_with_stock,
    setup_shop_and_technician,
    setup_storefront,
    activate_route,
    validate_success,
)


def test_weekly_accrual_buckets_never_double_charge_a_week(api):
    """PRD §3.5: "Each accrual is written as a new charge row
    with its own `accrual_iso_week`, a monotonic `accrual_seq` that restarts at 1 within each week, and a
    `charge_status` of `OPEN`."
    PRD §3.5: "The accrual runs the first time a request is served whose
    logical clock week is later than the account's last `accrual_iso_week`"

    Design: Difficulty/resource_temporal_overlap/weekly_accrual_buckets_never_double_charge_one_week
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront(mix_plan="POWER_TOOLS")
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    create_delivered_order(store["franchisee"], store["route"], people["technician"],
                           account, [order_line(product, 3)],
                           mix_profile="DIAGNOSTIC_WEIGHTED")

    set_clock("2026-09-14T00:00:00Z")
    first_read = get_account(account["id"])
    second_read = get_account(account["id"])
    assert first_read["accrued_finance_charge_cents"] == 136
    assert second_read["accrued_finance_charge_cents"] == 136, (
        "the week's bucket is already occupied")

    set_clock("2026-09-21T00:00:00Z")
    third_read = get_account(account["id"])
    assert third_read["accrued_finance_charge_cents"] == 272

    charges = list_charges(account["id"])
    assert len(charges) == 2
    assert charges[0]["accrual_iso_week"] == "2026-09-14T00:00:00Z"
    assert charges[1]["accrual_iso_week"] == "2026-09-21T00:00:00Z"
    assert charges[0]["accrual_seq"] == 1
    assert charges[1]["accrual_seq"] == 1, "the sequence restarts at 1 within each week"
    assert third_read["principal_balance_cents"] == 45338, "accrual never touches principal"


def test_territory_window_close_never_re_resolves_a_frozen_holder(api):
    """PRD §3.5: "The holder is frozen at minting and is never recomputed — neither a later
    surrender of the opening territory nor a shop change touches it."
    PRD §3.5: "a
    `FRANCHISEE_ASSUMED` territory yields a `FRANCHISOR` recourse holder"

    Design: Difficulty/resource_temporal_overlap/half_open_territory_window_freezes_recourse_at_minting
    """
    franchisee = create_certified_franchisee()
    route = create_route(franchisee, route_code="R1")
    set_clock("2026-09-07T00:00:00Z")
    developed = validate_success(advance_territory(franchisee, route, "DEVELOP", 90))
    assert developed["in_force_from_week"] == "2026-09-07T00:00:00Z"
    assert developed["in_force_to_week"] is None
    activate_route(franchisee, route)
    qualify_territory(franchisee, route, 90)

    shop = create_shop(franchisee, route)
    technician = create_technician(franchisee, shop)
    product = setup_product_with_stock({"franchisee": franchisee, "route": route}, on_hand=10)
    account = setup_account(franchisee, shop, technician, requested_limit_cents=400_000)
    assert account["recourse_holder"] == "FRANCHISOR", (
        "FRANCHISEE_ASSUMED maps to the franchisor as the recourse holder")
    create_delivered_order(franchisee, route, technician, account, [order_line(product, 3)],
                           mix_profile="DIAGNOSTIC_WEIGHTED")

    set_clock("2026-09-21T00:00:00Z")
    surrendered = validate_success(advance_territory(
        franchisee, route, "SURRENDER", 90, headers=MANAGER))
    assert surrendered["in_force_to_week"] == "2026-09-21T00:00:00Z"
    assert surrendered["territory_development_status"] == "SURRENDERED"

    assert get_account(account["id"])["recourse_holder"] == "FRANCHISOR"
    assert get_franchisee(franchisee["id"])["recourse_exposure_cents"] == 0
    assert get_franchisee(franchisee["id"])["outstanding_credit_cents"] == 45474
