"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, because the harness restarts the server before every test and
each test starts from an empty database.  Setup calls go through the lenient
``get_success_data`` validator so a broken preamble surfaces as a clear setup
failure rather than an obscure assertion.

Identity threading (PRD §2.1): ``Customer`` calls that are ownership-gated use
``make_customer_headers(customer["id"])`` and ``ComplexManager`` feed-batch
calls use ``make_complex_manager_headers(complex["id"])`` — never the shared
placeholder constants.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    create_capital_project_payload,
    create_certification_payload,
    create_commitment_payload,
    create_complex_payload,
    create_customer_payload,
    create_depopulation_order_payload,
    create_disease_event_payload,
    create_feed_contract_payload,
    create_flock_payload,
    create_house_payload,
    create_order_payload,
    create_quotation_payload,
    hedge_payload,
    receive_payload,
    record_result_payload,
)
from .test_users import (
    TEST_USERS,
    make_complex_manager_headers,
    make_customer_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
PLANT = TEST_USERS["plant_manager_headers"]
PROCUREMENT = TEST_USERS["procurement_lead_headers"]
HEALTH = TEST_USERS["health_official_headers"]
AUDITOR = TEST_USERS["quality_auditor_headers"]
SALES = TEST_USERS["sales_manager_headers"]


# --- primitives ---------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK):
    """Move the server's logical clock to ``to_iso8601`` (PRD §2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_complex(
    name="Heartland Layers", region_code="MIDWEST",
    mill_receiving_tons_per_day=100, **overrides,
):
    """Create a production complex. Returns the created Complex."""
    return get_success_data(
        api_client.create_complex(
            create_complex_payload(
                name=name, region_code=region_code,
                mill_receiving_tons_per_day=mill_receiving_tons_per_day,
                **overrides,
            ),
            ADMIN,
        )
    )


def read_complex(complex_id, headers=ADMIN):
    return get_success_data(api_client.get_complex(complex_id, headers))


def run_ops(complex_id, headers=ADMIN):
    """Advance the complex's weekly operations checkpoint (PRD §2.4)."""
    return get_success_data(api_client.run_ops(complex_id, headers))


def create_house(
    complex_id, house_code="H1", housing_style="CONVENTIONAL",
    capacity_hens=100_000, **overrides,
):
    return get_success_data(
        api_client.create_house(
            complex_id,
            create_house_payload(
                house_code=house_code, housing_style=housing_style,
                capacity_hens=capacity_hens, **overrides,
            ),
            ADMIN,
        )
    )


def read_house(house_id, headers=ADMIN):
    return get_success_data(api_client.get_house(house_id, headers))


def create_certification(
    house_id, program="CAGE_FREE", auditor_name="Humane Farm Auditors",
    scheduled_date="2026-09-01T00:00:00Z", **overrides,
):
    return get_success_data(
        api_client.create_certification(
            house_id,
            create_certification_payload(
                program=program, auditor_name=auditor_name,
                scheduled_date=scheduled_date, **overrides,
            ),
            AUDITOR,
        )
    )


def record_certification_result(certification_id, result="PASSED"):
    return get_success_data(
        api_client.record_certification_result(
            certification_id, record_result_payload(result), AUDITOR
        )
    )


def create_planned_flock(
    house_id, flock_code="F1", program="CONVENTIONAL", ownership="OWNED",
    placement_date="2026-09-01T00:00:00Z", placed_hen_count=10_000,
    grower_name=None, **overrides,
):
    return get_success_data(
        api_client.create_flock(
            house_id,
            create_flock_payload(
                flock_code=flock_code, program=program, ownership=ownership,
                placement_date=placement_date, placed_hen_count=placed_hen_count,
                grower_name=grower_name, **overrides,
            ),
            PLANNER,
        )
    )


def place_flock(flock_id):
    return get_success_data(api_client.place_flock(flock_id, PLANNER))


def create_and_place_flock(house_id, **kwargs):
    """Plan a flock and immediately confirm placement. Returns the placed Flock."""
    flock = create_planned_flock(house_id, **kwargs)
    return place_flock(flock["id"])


def read_flock(flock_id, headers=ADMIN):
    return get_success_data(api_client.get_flock(flock_id, headers))


def create_disease_event(
    complex_id, scope_house_ids, pathogen="HPAI",
    detection_date="2026-09-01T00:00:00Z", **overrides,
):
    return get_success_data(
        api_client.create_disease_event(
            complex_id,
            create_disease_event_payload(
                pathogen=pathogen, detection_date=detection_date,
                scope_house_ids=scope_house_ids, **overrides,
            ),
            HEALTH,
        )
    )


def confirm_disease_event(event_id):
    return get_success_data(api_client.confirm_disease_event(event_id, HEALTH))


def dismiss_disease_event(event_id):
    return get_success_data(api_client.dismiss_disease_event(event_id, HEALTH))


def create_depopulation_order(event_id, house_id, disposal_method="INCINERATION"):
    return get_success_data(
        api_client.create_depopulation_order(
            event_id, create_depopulation_order_payload(house_id, disposal_method),
            HEALTH,
        )
    )


def complete_depopulation_order(order_id):
    return get_success_data(api_client.complete_depopulation_order(order_id, HEALTH))


def publish_quotation(
    region_code="MIDWEST", size_class="LARGE", price_cents_per_dozen=150,
    effective_date="2026-09-07T00:00:00Z", source=None, **overrides,
):
    return get_success_data(
        api_client.create_market_quotation(
            create_quotation_payload(
                region_code=region_code, size_class=size_class,
                price_cents_per_dozen=price_cents_per_dozen,
                effective_date=effective_date, source=source, **overrides,
            ),
            ADMIN,
        )
    )


def create_customer(
    name="Sunrise Grocers", segment="RETAIL", credit_limit_cents=500_000_000,
    **overrides,
):
    return get_success_data(
        api_client.create_customer(
            create_customer_payload(
                name=name, segment=segment,
                credit_limit_cents=credit_limit_cents, **overrides,
            ),
            ADMIN,
        )
    )


def read_customer(customer_id, headers=ADMIN):
    return get_success_data(api_client.get_customer(customer_id, headers))


def create_commitment(customer_id, **overrides):
    """Create a PENDING commitment. Returns the created CustomerCommitment."""
    return get_success_data(
        api_client.create_commitment(
            customer_id, create_commitment_payload(**overrides), SALES
        )
    )


def activate_commitment(commitment_id):
    return get_success_data(api_client.activate_commitment(commitment_id, SALES))


def create_active_commitment(customer_id, **overrides):
    """Create + activate a commitment. Returns the ACTIVE CustomerCommitment."""
    commitment = create_commitment(customer_id, **overrides)
    return activate_commitment(commitment["id"])


def read_commitment(commitment_id, headers=SALES):
    return get_success_data(api_client.get_commitment(commitment_id, headers))


def book_order(
    commitment_id, customer_id, ship_week_start="2026-09-07T00:00:00Z",
    dozen_ordered=10_000, size_class="LARGE", headers=None,
):
    """Book an order with the commitment's freshly-read version (PRD §2.10).

    The booking itself bumps the commitment's version, so the OCC field must
    be re-read immediately before every create.
    """
    version = read_commitment(commitment_id)["version"]
    if headers is None:
        headers = make_customer_headers(customer_id)
    return get_success_data(
        api_client.create_order(
            commitment_id,
            create_order_payload(
                ship_week_start=ship_week_start, dozen_ordered=dozen_ordered,
                size_class=size_class, expected_commitment_version=version,
            ),
            headers,
        )
    )


def allocate_order(order_id):
    return get_success_data(api_client.allocate_order(order_id, PLANNER))


def ship_order(order_id):
    return get_success_data(api_client.ship_order(order_id, PLANT))


def read_order(order_id, headers=ADMIN):
    return get_success_data(api_client.get_order(order_id, headers))


def read_order_settlement(order_id):
    """The order's single settlement (1:1); fails setup if absent."""
    data = get_success_data(api_client.list_order_settlements(order_id, SALES))
    rows = data if isinstance(data, list) else data.get("data", data)
    if isinstance(rows, dict):  # defensive; list endpoint returns a bare array
        rows = rows.get("data", [])
    assert isinstance(rows, list) and len(rows) == 1, (
        f"expected exactly one settlement for order {order_id}, got {rows!r}"
    )
    return rows[0]


def finalize_settlement(settlement_id):
    return get_success_data(api_client.finalize_settlement(settlement_id, SALES))


def create_feed_contract(
    complex_id, commodity="CORN", total_tons=100, basis_cents_per_ton=2_000,
    spot_reference_cents_per_ton=17_000,
    delivery_start="2026-09-01T00:00:00Z",
    delivery_end="2026-09-30T00:00:00Z", is_organic_certified=False, **overrides,
):
    return get_success_data(
        api_client.create_feed_contract(
            create_feed_contract_payload(
                complex_id, commodity=commodity, total_tons=total_tons,
                basis_cents_per_ton=basis_cents_per_ton,
                spot_reference_cents_per_ton=spot_reference_cents_per_ton,
                delivery_start=delivery_start, delivery_end=delivery_end,
                is_organic_certified=is_organic_certified, **overrides,
            ),
            PROCUREMENT,
        )
    )


def hedge_feed_contract(contract_id, hedged_tons, hedge_futures_cents_per_ton):
    return get_success_data(
        api_client.hedge_feed_contract(
            contract_id, hedge_payload(hedged_tons, hedge_futures_cents_per_ton),
            PROCUREMENT,
        )
    )


def receive_feed(contract_id, tons, spot_cents_per_ton):
    return get_success_data(
        api_client.receive_feed_contract(
            contract_id, receive_payload(tons, spot_cents_per_ton), PROCUREMENT
        )
    )


def create_capital_project(
    commitment_id, house_id, investment_cents=750_000_000,
    target_style="CAGE_FREE", construction_weeks=6, **overrides,
):
    return get_success_data(
        api_client.create_capital_project(
            commitment_id,
            create_capital_project_payload(
                house_id, investment_cents=investment_cents,
                target_style=target_style, construction_weeks=construction_weeks,
                **overrides,
            ),
            PLANNER,
        )
    )


# --- composite scenarios --------------------------------------------------------

def setup_laying_complex(
    name="Heartland Layers", region_code="MIDWEST", hens=80_000,
    placement_date="2026-04-28T00:00:00Z", capacity=100_000, program="CONVENTIONAL",
    housing_style="CONVENTIONAL",
):
    """Complex + one house + one placed flock of ``hens`` at ``placement_date``.

    Returns ``{"complex": ..., "house": ..., "flock": ...}``.
    """
    complex_ = create_complex(name=name, region_code=region_code)
    house = create_house(
        complex_["id"], housing_style=housing_style, capacity_hens=capacity
    )
    flock = create_and_place_flock(
        house["id"], program=program, placement_date=placement_date,
        placed_hen_count=hens,
    )
    return {"complex": complex_, "house": house, "flock": flock}


def setup_pricing_scenario(
    dozen_ordered=30_000,
    adjustment=12,
    weekly_dozen=100_000,
    credit_limit_cents=500_000_000,
    segment="RETAIL",
    region_code="MIDWEST",
    size_class="LARGE",
    ship_week_start="2026-09-07T00:00:00Z",
    quotations=((150, "2026-09-07T00:00:00Z"),
                (160, "2026-09-09T00:00:00Z"),
                (170, "2026-09-11T00:00:00Z")),
    ship_clock="2026-09-12T00:00:00Z",
    hens=80_000,
    placement_date="2026-04-28T00:00:00Z",
    complex_name="Heartland Layers",
    customer_name="Sunrise Grocers",
):
    """Full order-to-ship pricing fixture.

    Complex with a LAYING flock, an ACTIVE commitment, published quotations,
    an order ALLOCATED then SHIPPED at ``ship_clock``.  Returns a namespace
    dict with every created entity plus the PROVISIONAL settlement.
    """
    set_clock(DEFAULT_CLOCK)
    env = setup_laying_complex(
        name=complex_name, region_code=region_code, hens=hens,
        placement_date=placement_date,
    )
    customer = create_customer(
        name=customer_name, segment=segment, credit_limit_cents=credit_limit_cents
    )
    commitment = create_active_commitment(
        customer["id"],
        region_code=region_code,
        weekly_dozen_committed=weekly_dozen,
        price_adjustment_cents_per_dozen=adjustment,
    )
    published = [
        publish_quotation(
            region_code=region_code, size_class=size_class,
            price_cents_per_dozen=price, effective_date=effective,
        )
        for price, effective in quotations
    ]
    order = book_order(
        commitment["id"], customer["id"], ship_week_start=ship_week_start,
        dozen_ordered=dozen_ordered, size_class=size_class,
    )
    order = allocate_order(order["id"])
    set_clock(ship_clock)
    order = ship_order(order["id"])
    settlement = read_order_settlement(order["id"])
    return {
        "complex": env["complex"],
        "house": env["house"],
        "flock": env["flock"],
        "customer": customer,
        "commitment": read_commitment(commitment["id"]),
        "quotations": published,
        "order": order,
        "settlement": settlement,
    }


def finalize_scenario(scenario, finalize_clock="2026-09-15T00:00:00Z"):
    """Finalize the scenario's settlement at ``finalize_clock`` (week closed)."""
    set_clock(finalize_clock)
    settlement = finalize_settlement(scenario["settlement"]["id"])
    scenario["settlement"] = settlement
    scenario["order"] = read_order(scenario["order"]["id"])
    scenario["customer"] = read_customer(scenario["customer"]["id"])
    return scenario
