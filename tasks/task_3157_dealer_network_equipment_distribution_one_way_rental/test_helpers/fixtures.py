"""Composite setup helpers for multi-step PRD scenarios.

Every helper builds its preconditions from scratch against the live API using
the lenient get_success_data() validator, so a setup failure surfaces as a
clear "Setup failed" message instead of a confusing assertion error.
"""
import uuid as _uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_customer_payload,
    create_dealer_payload,
    create_equipment_unit_payload,
    create_lane_rate_payload,
    create_location_payload,
    create_reservation_payload,
    create_vehicle_profile_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_dealer_agent_headers,
)


def _tag() -> str:
    return _uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Tier 1: single-resource setup
# ---------------------------------------------------------------------------

def setup_location(geo_zone="NORTH", storage_capacity=10, code_prefix="LOC"):
    """Create one OPEN location. Returns the Location dict."""
    resp = api_client.create_location(
        create_location_payload(
            location_code=f"{code_prefix}-{_tag()}",
            geo_zone=geo_zone,
            storage_capacity=storage_capacity,
        ),
        TEST_USERS["admin"],
    )
    return get_success_data(resp)


def setup_dealer(location, commission_rate_override=None, code_prefix="D"):
    """Create one ACTIVE dealer at the given location. Returns the Dealer dict."""
    payload = create_dealer_payload(
        dealer_code=f"{code_prefix}-{_tag()}",
        location_id=location["id"],
    )
    if commission_rate_override is not None:
        payload["commission_rate_override"] = commission_rate_override
    resp = api_client.create_dealer(payload, TEST_USERS["admin"])
    return get_success_data(resp)


def setup_unit(dealer, equipment_type="TRUCK_10FT", code_prefix="U"):
    """Register one AVAILABLE unit held by the given dealer. Returns the unit dict."""
    resp = api_client.create_equipment_unit(
        create_equipment_unit_payload(
            unit_code=f"{code_prefix}-{_tag()}",
            equipment_type=equipment_type,
            dealer_id=dealer["id"],
        ),
        TEST_USERS["admin"],
    )
    return get_success_data(resp)


def setup_active_rate(origin_location, dest_location, equipment_type="TRUCK_10FT",
                      season="OFF_PEAK", base_rate_cents=None,
                      reposition_surcharge_cents=0, commission_rate=None):
    """Create + activate a lane rate. Returns the ACTIVE LaneRate dict."""
    payload = create_lane_rate_payload(
        origin_location_id=origin_location["id"],
        dest_location_id=dest_location["id"],
        equipment_type=equipment_type,
        season=season,
        base_rate_cents=(
            base_rate_cents if base_rate_cents is not None
            else TEST_DEFAULTS["BASE_RATE_CENTS"]
        ),
        reposition_surcharge_cents=reposition_surcharge_cents,
        commission_rate=(
            commission_rate if commission_rate is not None
            else TEST_DEFAULTS["COMMISSION_RATE"]
        ),
    )
    rate = get_success_data(api_client.create_lane_rate(payload, TEST_USERS["pricing"]))
    return get_success_data(api_client.activate_lane_rate(rate["id"], TEST_USERS["pricing"]))


# ---------------------------------------------------------------------------
# Tier 2: hierarchy (locations + dealers + units)
# ---------------------------------------------------------------------------

def setup_two_locations(zone_a="NORTH", zone_b="SOUTH", capacity=10):
    """Two OPEN locations in distinct zones. Returns (loc_a, loc_b)."""
    loc_a = setup_location(geo_zone=zone_a, storage_capacity=capacity, code_prefix="LA")
    loc_b = setup_location(geo_zone=zone_b, storage_capacity=capacity, code_prefix="LB")
    return loc_a, loc_b


def setup_two_dealer_network(zone_a="NORTH", zone_b="SOUTH", capacity=10):
    """Locations A/B with one ACTIVE dealer at each. Returns (loc_a, loc_b, dealer_a, dealer_b)."""
    loc_a, loc_b = setup_two_locations(zone_a, zone_b, capacity)
    dealer_a = setup_dealer(loc_a, code_prefix="DA")
    dealer_b = setup_dealer(loc_b, code_prefix="DB")
    return loc_a, loc_b, dealer_a, dealer_b


# ---------------------------------------------------------------------------
# Tier 2b: customers
# ---------------------------------------------------------------------------

def setup_customer(verify_dealer=None, verify=True, email_prefix="cust", **vehicle_overrides):
    """Create a vehicle profile + customer; optionally verify the license via a dealer.

    Returns (customer, vehicle_profile).
    """
    veh = get_success_data(api_client.create_vehicle_profile(
        create_vehicle_profile_payload(**vehicle_overrides), TEST_USERS["customer"]))
    cust = get_success_data(api_client.create_customer(
        create_customer_payload(email=f"{email_prefix}-{_tag()}@x.com",
                                vehicle_profile_id=veh["id"]),
        TEST_USERS["customer"]))
    if verify:
        assert verify_dealer is not None, "verify_dealer required when verify=True"
        resp = api_client.verify_license(
            cust["id"], make_dealer_agent_headers(verify_dealer["id"]))
        assert resp.status_code == 200, \
            f"Setup failed: verify-license -> {resp.status_code} {resp.text}"
        cust["driver_license_verified"] = True
    return cust, veh


# ---------------------------------------------------------------------------
# Tier 3: reservation lifecycle
# ---------------------------------------------------------------------------

def create_quoted_reservation(customer, origin_dealer, dest_location,
                              equipment_type="TRUCK_10FT", rental_kind="ONE_WAY",
                              pickup_date=None, dropoff_date=None):
    """Create a QUOTED reservation owned by `customer`. Returns the reservation dict."""
    payload = create_reservation_payload(
        customer_id=customer["id"],
        origin_dealer_id=origin_dealer["id"],
        dest_location_id=dest_location["id"],
        equipment_type=equipment_type,
        rental_kind=rental_kind,
        pickup_date=pickup_date or TEST_DEFAULTS["PICKUP"],
        dropoff_date=dropoff_date or TEST_DEFAULTS["DROPOFF_1D"],
    )
    resp = api_client.create_reservation(payload, make_customer_headers(customer["id"]))
    return get_success_data(resp)


def create_confirmed_reservation(customer, origin_dealer, dest_location,
                                 equipment_type="TRUCK_10FT", rental_kind="ONE_WAY",
                                 pickup_date=None, dropoff_date=None):
    """Create + confirm a reservation. Returns the CONFIRMED reservation dict."""
    rsv = create_quoted_reservation(
        customer, origin_dealer, dest_location, equipment_type, rental_kind,
        pickup_date, dropoff_date)
    resp = api_client.confirm_reservation(
        rsv["id"], {"expected_reservation_version": rsv["version"]},
        make_customer_headers(customer["id"]))
    return get_success_data(resp)


def setup_confirmed_scenario(pickup_date=None, dropoff_date=None,
                             equipment_type="TRUCK_10FT",
                             base_rate_cents=None, reposition_surcharge_cents=0,
                             zone_a="NORTH", zone_b="SOUTH"):
    """Standard confirmed-reservation scenario.

    Builds: locations A/B, dealer A with one unit of the requested type,
    ACTIVE lane rate A->B, verified customer, QUOTED->CONFIRMED reservation.
    Returns dict with keys: loc_a, loc_b, dealer_a, unit, rate, customer,
    vehicle, reservation.
    """
    loc_a, loc_b = setup_two_locations(zone_a, zone_b)
    dealer_a = setup_dealer(loc_a)
    unit = setup_unit(dealer_a, equipment_type=equipment_type)
    rate = setup_active_rate(
        loc_a, loc_b, equipment_type=equipment_type,
        base_rate_cents=base_rate_cents,
        reposition_surcharge_cents=reposition_surcharge_cents)
    customer, vehicle = setup_customer(verify_dealer=dealer_a)
    reservation = create_confirmed_reservation(
        customer, dealer_a, loc_b, equipment_type=equipment_type,
        pickup_date=pickup_date, dropoff_date=dropoff_date)
    return {
        "loc_a": loc_a, "loc_b": loc_b, "dealer_a": dealer_a, "unit": unit,
        "rate": rate, "customer": customer, "vehicle": vehicle,
        "reservation": reservation,
    }


def setup_agreement(pickup_date=None, dropoff_date=None, equipment_type="TRUCK_10FT",
                    base_rate_cents=None, reposition_surcharge_cents=0,
                    zone_a="NORTH", zone_b="SOUTH", with_dest_dealer=False):
    """Full pickup: confirmed reservation + ACTIVE rental agreement.

    Returns dict with keys of setup_confirmed_scenario plus: agreement,
    dealer_b (the return-location dealer) when with_dest_dealer=True.
    """
    scenario = setup_confirmed_scenario(
        pickup_date=pickup_date, dropoff_date=dropoff_date,
        equipment_type=equipment_type, base_rate_cents=base_rate_cents,
        reposition_surcharge_cents=reposition_surcharge_cents,
        zone_a=zone_a, zone_b=zone_b)
    return_location = scenario["loc_b"]
    if with_dest_dealer:
        scenario["dealer_b"] = setup_dealer(scenario["loc_b"], code_prefix="DB")
    payload = {
        "reservation_id": scenario["reservation"]["id"],
        "equipment_unit_id": scenario["unit"]["id"],
        "return_location_id": return_location["id"],
    }
    agreement = get_success_data(api_client.create_rental_agreement(
        payload, make_dealer_agent_headers(scenario["dealer_a"]["id"])))
    scenario["agreement"] = agreement
    return scenario


def setup_returned_agreement(**kwargs):
    """Agreement returned at its return location (status RETURNED).

    Always creates a destination dealer so the unit handoff succeeds.
    Returns the scenario dict; scenario["agreement"] reflects the RETURNED row
    and scenario["returned_agreement"] is the return response payload.
    """
    kwargs["with_dest_dealer"] = True
    scenario = setup_agreement(**kwargs)
    returned = get_success_data(api_client.return_rental_agreement(
        scenario["agreement"]["id"],
        make_dealer_agent_headers(scenario["dealer_b"]["id"])))
    scenario["returned_agreement"] = returned
    return scenario
