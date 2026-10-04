"""Shared builders for the calculation-family corner translations.

Each builder composes a composite helper already present in
``test_helpers.fixtures`` rather than re-inventing its chain, and every monetary
literal asserted by the calculation tests is recomputed from the calculation
rules stated in the PRD against the catalogue the fixture actually builds.

The builders here deliberately pin the whole production catalogue (model code,
build hours, per-component costs, per-car quantities, lead times and opening
stock) so that a quote, an accrual or a book value asserted in a test is a
function of the PRD's formulas alone and not of a default the fixture happens
to carry.
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    create_car_type_component_requirement_payload,
    create_lessee_and_contract,
    get_success_data,
    setup_catalogue,
    setup_retained_order_with_fleet_cars,
)

PLANNER = TEST_USERS["production_planner_headers"]
SUPPLY = TEST_USERS["supply_chain_coordinator_headers"]
LEASE = TEST_USERS["lease_administrator_headers"]
PORTFOLIO = TEST_USERS["portfolio_manager_headers"]
RETROFIT = TEST_USERS["regulatory_retrofitist_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def single_row_catalogue(wheelset_qty_per_car: int = 1, **kwargs):
    """A catalogue whose car type carries exactly one bill-of-material row.

    The shared catalogue helper always binds a wheelset and a casting row; the
    scenarios below are stated against a car type that consumes one component
    only, so the row is added here on top of the helper's component catalogue.
    """
    catalogue = setup_catalogue(
        include_bom=False, wheelset_qty_per_car=wheelset_qty_per_car, **kwargs
    )
    catalogue["bom"] = [
        get_success_data(
            api_client.create_car_type_component_requirement(
                create_car_type_component_requirement_payload(
                    car_type_id=catalogue["car_type"]["id"],
                    component_id=catalogue["wheelset"]["id"],
                    qty_per_car=wheelset_qty_per_car,
                ),
                PLANNER,
            )
        )
    ]
    return catalogue


def flat_car_catalogue(**kwargs):
    """The one-wheelset-row car type the placement and return scenarios build."""
    defaults = dict(
        model_code="FLT-100",
        car_class="BOXCAR",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="FLT_LINE",
        wheelset_part_number="WS-310",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        on_hand_qty=1000,
        include_coating=False,
    )
    defaults.update(kwargs)
    return single_row_catalogue(**defaults)


def box_car_catalogue(**kwargs):
    """The three-row car type the order-quote scenarios are stated against."""
    defaults = dict(
        model_code="BOX-200",
        car_class="BOXCAR",
        build_hours=30,
        regulatory_life_years=25,
        line_count_family="LINE-B",
        wheelset_part_number="WS-210",
        wheelset_unit_cost_cents=18000,
        wheelset_qty_per_car=4,
        wheelset_lead_time_days=30,
        wheelset_overrides={"on_hand_qty": 40},
        casting_part_number="CS-210",
        casting_unit_cost_cents=40000,
        casting_qty_per_car=2,
        casting_lead_time_days=45,
        casting_overrides={"on_hand_qty": 20},
        coating_part_number="CT-210",
        coating_unit_cost_cents=12500,
        coating_qty_per_car=3,
        coating_lead_time_days=20,
        coating_overrides={"on_hand_qty": 100},
    )
    defaults.update(kwargs)
    return setup_catalogue(**defaults)


def commercial(legal_name: str, **kwargs):
    """A lessee account plus an activated contract for it."""
    defaults = dict(
        credit_tier="A",
        utilization_threshold_pct=80,
        credit_ceiling_cents=50000000,
        lease_type="FULL_SERVICE",
        per_diem_rate_cents=2000,
        liability_bearer="LESSOR",
        term_start_date="2026-09-01",
        term_end_date="2027-09-01",
        fleet_car_cap=10,
        activate=True,
    )
    defaults.update(kwargs)
    return create_lessee_and_contract(legal_name=legal_name, **defaults)


def held_cars(catalogue, car_count: int = 2, commercial_pair=None, **kwargs):
    """A RETAINED order walked to COMPLETED, returning its HELD fleet cars.

    ``commercial_pair`` is the ``{"lessee": ..., "contract": ...}`` world when
    the scenario needs a specific threshold, rate or liability bearer; without
    it the order is built and released with no contract at all.
    """
    if commercial_pair is None:
        world = setup_retained_order_with_fleet_cars(
            car_count=car_count, catalogue=catalogue, build_contract=False, **kwargs
        )
    else:
        world = setup_retained_order_with_fleet_cars(
            car_count=car_count,
            catalogue=catalogue,
            contract=commercial_pair["contract"],
            lessee=commercial_pair["lessee"],
            **kwargs,
        )
    world["catalogue"] = catalogue
    return world


__all__ = [
    "ADMIN",
    "LEASE",
    "PLANNER",
    "PORTFOLIO",
    "RETROFIT",
    "SUPPLY",
    "box_car_catalogue",
    "commercial",
    "flat_car_catalogue",
    "held_cars",
    "single_row_catalogue",
]
