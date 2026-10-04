"""Composite setup helpers — multi-step state builders shared by many tests.

Every helper builds its preconditions from scratch via PRD-declared endpoints
and uses get_success_data() so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_municipality_payload,
    create_host_municipality_payload,
    create_host_community_agreement_payload,
    create_waste_supply_agreement_payload,
    create_waste_delivery_payload,
    create_boiler_payload,
    create_outage_window_payload,
    create_diversion_plan_payload,
    create_diversion_leg_payload,
    create_daily_throughput_report_payload,
    create_power_purchase_agreement_payload,
    create_merchant_ppa_payload,
    create_landfill_payload,
    create_ash_shipment_payload,
    create_ash_test_payload,
    create_emissions_permit_payload,
    create_emissions_reading_payload,
)
from .test_users import TEST_USERS

CM = TEST_USERS["contracts_manager_headers"]
PO = TEST_USERS["plant_operator_headers"]
ET = TEST_USERS["energy_trader_headers"]
EO = TEST_USERS["environmental_officer_headers"]
REG = TEST_USERS["regulator_headers"]


def make_municipality(**overrides):
    """Create a STANDARD municipality. Returns the municipality dict."""
    return get_success_data(api_client.create_municipality(create_municipality_payload(**overrides), CM))


def make_host_municipality(**overrides):
    """Create a host-community municipality. Returns the municipality dict."""
    return get_success_data(api_client.create_municipality(create_host_municipality_payload(**overrides), CM))


def make_host_agreement(municipality_id, **overrides):
    """Create a HostCommunityAgreement for a host municipality."""
    return get_success_data(
        api_client.create_host_community_agreement(
            create_host_community_agreement_payload(municipality_id=municipality_id, **overrides), CM
        )
    )


def make_boiler(**overrides):
    """Create an ONLINE boiler. Returns the boiler dict."""
    return get_success_data(api_client.create_boiler(create_boiler_payload(**overrides), PO))


def make_active_agreement(municipality_id=None, **overrides):
    """Create a waste supply agreement and activate it.

    Returns (agreement_dict_after_activation,). The dict's `version` is the
    post-activation version — the value clients must present for the first
    OCC-guarded delivery accept / amendment against this agreement.
    """
    if municipality_id is None:
        municipality_id = make_municipality()["id"]
    created = get_success_data(
        api_client.create_waste_supply_agreement(
            create_waste_supply_agreement_payload(municipality_id=municipality_id, **overrides), CM
        )
    )
    return get_success_data(api_client.activate_waste_supply_agreement(created["id"], CM))


def make_delivery(agreement_id, **overrides):
    """Schedule a delivery against an agreement. Returns the delivery dict (SCHEDULED)."""
    return get_success_data(
        api_client.create_waste_delivery(create_waste_delivery_payload(agreement_id=agreement_id, **overrides), PO)
    )


def make_received_delivery(agreement_id, **overrides):
    """Schedule and receive a delivery. Returns the RECEIVED delivery dict."""
    delivery = make_delivery(agreement_id, **overrides)
    return get_success_data(api_client.receive_waste_delivery(delivery["id"], PO))


def make_accepted_delivery(agreement, **overrides):
    """Schedule, receive, and accept a delivery against an ACTIVE agreement.

    `agreement` must be the current agreement dict (its `version` is used as
    the OCC expected_agreement_version). Returns (delivery_dict, agreement_dict)
    with both refreshed post-accept.
    """
    delivery = make_received_delivery(agreement["id"], **overrides)
    accepted = get_success_data(
        api_client.accept_waste_delivery(
            delivery["id"], {"expected_agreement_version": agreement["version"]}, PO
        )
    )
    fresh_agreement = get_success_data(api_client.get_waste_supply_agreement(agreement["id"], CM))
    return accepted, fresh_agreement


def make_outage_with_approved_plan(boiler=None, max_diversion_tpd=200, leg_tonnes=400, **outage_overrides):
    """Outage + diversion plan with one leg, plan approved. Outage still SCHEDULED.

    Returns (outage, plan) dicts. The boiler dict needed for the OCC start call
    must be fetched fresh by the caller (GET) if other mutations intervened.
    """
    if boiler is None:
        boiler = make_boiler()
    outage = get_success_data(
        api_client.create_outage_window(create_outage_window_payload(boiler_id=boiler["id"], **outage_overrides), PO)
    )
    plan = get_success_data(
        api_client.create_diversion_plan(create_diversion_plan_payload(outage_id=outage["id"], max_diversion_tpd=max_diversion_tpd), PO)
    )
    get_success_data(
        api_client.create_diversion_leg(plan["id"], create_diversion_leg_payload(planned_tonnes=leg_tonnes), PO)
    )
    plan = get_success_data(api_client.approve_diversion_plan(plan["id"], CM))
    return outage, plan


def start_outage(outage, boiler):
    """Start a SCHEDULED outage (with its approved plan) using the boiler's current version.

    Returns (outage_dict_ACTIVE, boiler_dict_OUTAGE).
    """
    fresh_boiler = get_success_data(api_client.get_boiler(boiler["id"], PO))
    started = get_success_data(
        api_client.start_outage_window(outage["id"], {"expected_boiler_version": fresh_boiler["version"]}, PO)
    )
    fresh_boiler = get_success_data(api_client.get_boiler(boiler["id"], PO))
    return started, fresh_boiler


def make_active_ppa(**overrides):
    """Create and activate a PPA-kind power purchase agreement."""
    created = get_success_data(
        api_client.create_power_purchase_agreement(create_power_purchase_agreement_payload(**overrides), ET)
    )
    return get_success_data(api_client.activate_power_purchase_agreement(created["id"], ET))


def make_active_merchant_ppa(**overrides):
    """Create and activate a MERCHANT-kind power purchase agreement."""
    created = get_success_data(
        api_client.create_power_purchase_agreement(create_merchant_ppa_payload(**overrides), ET)
    )
    return get_success_data(api_client.activate_power_purchase_agreement(created["id"], ET))


def make_landfill(**overrides):
    """Create an ACTIVE landfill. Returns the landfill dict."""
    return get_success_data(api_client.create_landfill(create_landfill_payload(**overrides), EO))


def make_pending_shipment(landfill_id, passed=True, **shipment_overrides):
    """Create a shipment, submit for testing, record one test (passing by default).

    Returns (shipment_dict_TEST_PENDING, landfill_dict_fresh).
    """
    shipment = get_success_data(
        api_client.create_ash_shipment(create_ash_shipment_payload(landfill_id=landfill_id, **shipment_overrides), EO)
    )
    get_success_data(api_client.submit_ash_shipment_testing(shipment["id"], EO))
    if passed:
        test_payload = create_ash_test_payload(measured_value=4.0, limit_value=5.0)
    else:
        test_payload = create_ash_test_payload(measured_value=6.0, limit_value=5.0)
    get_success_data(api_client.create_ash_test(shipment["id"], test_payload, EO))
    shipment = get_success_data(api_client.get_ash_shipment(shipment["id"], EO))
    landfill = get_success_data(api_client.get_landfill(landfill_id, EO))
    return shipment, landfill


def complete_shipment(shipment, landfill):
    """Complete a TEST_PENDING shipment with the landfill's current version."""
    fresh_landfill = get_success_data(api_client.get_landfill(landfill["id"], EO))
    return get_success_data(
        api_client.complete_ash_shipment(
            shipment["id"], {"expected_landfill_version": fresh_landfill["version"]}, EO
        )
    )


def make_emissions_permit(**overrides):
    """Create an ACTIVE emissions permit."""
    return get_success_data(api_client.create_emissions_permit(create_emissions_permit_payload(**overrides), EO))


def make_emissions_reading(permit_id, **overrides):
    """Record an emissions reading against a permit."""
    return get_success_data(
        api_client.create_emissions_reading(
            create_emissions_reading_payload(permit_id=permit_id, **overrides), EO
        )
    )


def set_clock(to_iso8601):
    """Advance the logical clock (Regulator-only capability)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, REG))
