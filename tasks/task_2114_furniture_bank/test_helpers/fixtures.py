"""Composite setup helpers.

The test harness restarts the API server before every single test, so each test
starts against an empty database.  Every helper here therefore builds all of its
preconditions from scratch through declared endpoints only.

All setup calls go through `get_success_data()` so a broken precondition
surfaces as a clear "Setup step failed" instead of an opaque KeyError.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    agency_payload,
    allocate_payload,
    client_payload,
    crew_assignment_payload,
    delivery_run_payload,
    delivery_stop_payload,
    donation_item_payload,
    donation_offer_payload,
    fee_settlement_payload,
    inspection_payload,
    referral_payload,
    review_payload,
    run_cycle_payload,
    stop_outcome_payload,
    truck_payload,
    voucher_line_payload,
    voucher_payload,
)
from .test_users import (
    ADMIN,
    DISPATCH,
    INTAKE,
    WAREHOUSE,
    WAREHOUSE_INSPECTOR_ID,
    WAREHOUSE_RELEASER_ID,
    make_case_manager_headers,
    make_volunteer_headers,
    make_warehouse_lead_headers,
)

BASE_CLOCK = TEST_DEFAULTS["BASE_CLOCK"]

_LIST_PAGE = {"limit": 100, "offset": 0}


# ─── Tier 0: primitives ────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock. Mutates no entity and runs no expiry."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def run_cycle(advance_quota_epoch=None) -> dict:
    return get_success_data(
        api_client.run_cycle(run_cycle_payload(advance_quota_epoch), ADMIN)
    )


def create_agency(**overrides) -> dict:
    return get_success_data(api_client.create_agency(agency_payload(**overrides), ADMIN))


def get_agency(agency_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_agency(agency_id, headers or ADMIN))


def create_client(agency_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_client(
            client_payload(agency_id, **overrides), make_case_manager_headers(agency_id)
        )
    )


def get_client(client_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_client(client_id, headers or ADMIN))


def create_truck(**overrides) -> dict:
    return get_success_data(api_client.create_truck(truck_payload(**overrides), ADMIN))


def get_truck(truck_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_truck(truck_id, headers or ADMIN))


def create_volunteer(**overrides) -> dict:
    from .factories import volunteer_payload
    return get_success_data(
        api_client.create_volunteer(volunteer_payload(**overrides), ADMIN)
    )


def get_volunteer(volunteer_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_volunteer(volunteer_id, headers or ADMIN))


def create_referral(agency_id: str, client_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_referral(
            referral_payload(client_id, agency_id, **overrides),
            make_case_manager_headers(agency_id),
        )
    )


def submit_referral(referral_id: str, agency_id: str) -> dict:
    return get_success_data(
        api_client.submit_referral(referral_id, make_case_manager_headers(agency_id))
    )


def review_referral(referral_id: str, decision: str, note=None) -> dict:
    return get_success_data(
        api_client.review_referral(referral_id, review_payload(decision, note), ADMIN)
    )


def get_referral(referral_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_referral(referral_id, headers or ADMIN))


def issue_voucher(agency_id: str, referral_id: str, lines) -> dict:
    return get_success_data(
        api_client.create_voucher(
            voucher_payload(referral_id, lines), make_case_manager_headers(agency_id)
        )
    )


def get_voucher(voucher_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_voucher(voucher_id, headers or ADMIN))


def list_voucher_lines(voucher_id: str, headers=None, **filters) -> list:
    params = dict(_LIST_PAGE)
    params.update(filters)
    return get_success_data(
        api_client.list_voucher_lines(voucher_id, headers or ADMIN, params)
    )


def list_voucher_stops(voucher_id: str, headers=None, **filters) -> list:
    params = dict(_LIST_PAGE)
    params.update(filters)
    return get_success_data(
        api_client.list_voucher_stops(voucher_id, headers or ADMIN, params)
    )


def allocate(voucher_id: str, expected_voucher_version: int,
             user_id: str = WAREHOUSE_INSPECTOR_ID) -> dict:
    return get_success_data(
        api_client.allocate_voucher(
            voucher_id,
            allocate_payload(expected_voucher_version),
            make_warehouse_lead_headers(user_id),
        )
    )


def settle_fee(voucher_id: str, action: str, amount_cents=None) -> dict:
    return get_success_data(
        api_client.settle_voucher_fee(
            voucher_id, fee_settlement_payload(action, amount_cents), ADMIN
        )
    )


def cancel_voucher(voucher_id: str, agency_id: str, reason: str = "Household withdrew") -> dict:
    return get_success_data(
        api_client.cancel_voucher(
            voucher_id, {"reason": reason}, make_case_manager_headers(agency_id)
        )
    )


def create_donation_offer(items=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_donation_offer(donation_offer_payload(items, **overrides), INTAKE)
    )


def get_donation_offer(offer_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_donation_offer(offer_id, headers or INTAKE))


def list_donation_items(offer_id: str, headers=None, **filters) -> list:
    params = dict(_LIST_PAGE)
    params.update(filters)
    return get_success_data(
        api_client.list_donation_items(offer_id, headers or INTAKE, params)
    )


def triage_offer(offer_id: str) -> dict:
    return get_success_data(api_client.triage_donation_offer(offer_id, INTAKE))


def schedule_pickup(offer_id: str, truck_id: str) -> dict:
    return get_success_data(
        api_client.schedule_pickup(offer_id, {"truck_id": truck_id}, INTAKE)
    )


def intake_offer(offer_id: str, inspections, user_id: str = WAREHOUSE_INSPECTOR_ID) -> dict:
    return get_success_data(
        api_client.intake_donation_offer(
            offer_id, {"inspections": inspections}, make_warehouse_lead_headers(user_id)
        )
    )


def release_quarantine(offer_id: str, user_id: str = WAREHOUSE_RELEASER_ID) -> dict:
    return get_success_data(
        api_client.release_quarantine(offer_id, make_warehouse_lead_headers(user_id))
    )


def list_inventory(headers=None, **filters) -> list:
    params = dict(_LIST_PAGE)
    params.update(filters)
    return get_success_data(
        api_client.list_inventory_items(headers or WAREHOUSE, params)
    )


def get_inventory_item(item_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_inventory_item(item_id, headers or WAREHOUSE))


def create_run(truck_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_delivery_run(delivery_run_payload(truck_id, **overrides), DISPATCH)
    )


def get_run(run_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_delivery_run(run_id, headers or DISPATCH))


def book_stop(run_id: str, voucher_id: str, sequence: int, expected_run_version: int) -> dict:
    return get_success_data(
        api_client.create_delivery_stop(
            run_id,
            delivery_stop_payload(voucher_id, sequence, expected_run_version),
            DISPATCH,
        )
    )


def list_run_stops(run_id: str, headers=None, **filters) -> list:
    params = dict(_LIST_PAGE)
    params.update(filters)
    return get_success_data(api_client.list_run_stops(run_id, headers or DISPATCH, params))


def get_stop(run_id: str, stop_id: str) -> dict:
    """DeliveryStop rows are read through their run's stop collection."""
    stops = list_run_stops(run_id)
    for stop in stops:
        if stop["id"] == stop_id:
            return stop
    raise AssertionError(f"Setup step failed: stop {stop_id} not found on run {run_id}")


def invite_crew(run_id: str, volunteer_id: str, role_on_crew: str = "DRIVER") -> dict:
    return get_success_data(
        api_client.create_crew_assignment(
            run_id, crew_assignment_payload(volunteer_id, role_on_crew), DISPATCH
        )
    )


def list_run_crew(run_id: str, headers=None, **filters) -> list:
    params = dict(_LIST_PAGE)
    params.update(filters)
    return get_success_data(api_client.list_run_crew(run_id, headers or DISPATCH, params))


def get_crew_assignment(run_id: str, assignment_id: str) -> dict:
    for assignment in list_run_crew(run_id):
        if assignment["id"] == assignment_id:
            return assignment
    raise AssertionError(
        f"Setup step failed: crew assignment {assignment_id} not found on run {run_id}"
    )


def respond_crew(assignment_id: str, volunteer_id: str, response: str) -> dict:
    return get_success_data(
        api_client.respond_crew_assignment(
            assignment_id, {"response": response}, make_volunteer_headers(volunteer_id)
        )
    )


def dispatch_run(run_id: str) -> dict:
    return get_success_data(api_client.dispatch_delivery_run(run_id, DISPATCH))


def record_outcome(stop_id: str, outcome: str, pest_observed_at_residence=None) -> dict:
    return get_success_data(
        api_client.record_stop_outcome(
            stop_id, stop_outcome_payload(outcome, pest_observed_at_residence), DISPATCH
        )
    )


def list_waitlist(headers=None, **filters) -> list:
    params = dict(_LIST_PAGE)
    params.update(filters)
    return get_success_data(api_client.list_waitlist_entries(headers or ADMIN, params))


def get_waitlist_entry(entry_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_waitlist_entry(entry_id, headers or ADMIN))


def unmet_need_report(headers=None, **filters) -> dict:
    return get_success_data(
        api_client.get_unmet_need_report(headers or ADMIN, filters or None)
    )


# ─── Tier 1: state progression ─────────────────────────────────────────

def create_approved_referral(agency_id: str, client_id: str, **overrides) -> dict:
    """Draft -> SUBMITTED -> APPROVED. Returns the APPROVED referral."""
    referral = create_referral(agency_id, client_id, **overrides)
    submit_referral(referral["id"], agency_id)
    return review_referral(referral["id"], "APPROVE")


def create_returned_referral(agency_id: str, client_id: str, note="Needs revision",
                             **overrides) -> dict:
    """Draft -> SUBMITTED -> RETURNED. Returns the RETURNED referral."""
    referral = create_referral(agency_id, client_id, **overrides)
    submit_referral(referral["id"], agency_id)
    return review_referral(referral["id"], "RETURN", note)


# ─── Tier 2: entity hierarchy ──────────────────────────────────────────

def setup_agency_and_household(agency_county="CENTRAL", quota=5, household_size=4,
                               client_county="CENTRAL", has_infant=False,
                               agency_name=None) -> dict:
    """One PartnerAgency plus one Client registered under it."""
    agency_kwargs = {"county": agency_county, "quarterly_voucher_quota": quota}
    if agency_name is not None:
        agency_kwargs["name"] = agency_name
    agency = create_agency(**agency_kwargs)
    household = create_client(
        agency["id"],
        household_size=household_size,
        county=client_county,
        has_infant=has_infant,
    )
    return {
        "agency": agency,
        "client": household,
        "cm_headers": make_case_manager_headers(agency["id"]),
    }


def setup_issued_voucher(lines=None, categories=None, urgency="ROUTINE",
                         agency_county="CENTRAL", quota=5, household_size=4,
                         client_county="CENTRAL", has_infant=False,
                         agency_name=None, home_visit_completed=True) -> dict:
    """Agency + household + APPROVED referral + ISSUED voucher with its lines.

    Returns {"agency", "client", "referral", "voucher", "cm_headers"}.
    """
    lines = lines if lines is not None else [voucher_line_payload("BED")]
    categories = categories or sorted({line["category"] for line in lines})
    base = setup_agency_and_household(
        agency_county=agency_county, quota=quota, household_size=household_size,
        client_county=client_county, has_infant=has_infant, agency_name=agency_name,
    )
    referral = create_approved_referral(
        base["agency"]["id"], base["client"]["id"],
        requested_categories=list(categories), urgency=urgency,
        home_visit_completed=home_visit_completed,
    )
    voucher = issue_voucher(base["agency"]["id"], referral["id"], lines)
    base["referral"] = referral
    base["voucher"] = voucher
    return base


# ─── Tier 3: warehouse stock supply ────────────────────────────────────

def prepare_offer_for_intake(truck_id: str, items, pickup_county="CENTRAL",
                             window_start=None, window_end=None,
                             donor_name=None, donor_phone="555-0100") -> dict:
    """Create an offer, triage it and book its pickup onto `truck_id`.

    Returns {"offer", "items"} where "items" is the DonationItem collection in
    creation order, each already carrying its triage decision.
    """
    overrides = {
        "pickup_county": pickup_county,
        "pickup_window_start": window_start or TEST_DEFAULTS["PICKUP_WINDOW_START"],
        "pickup_window_end": window_end or TEST_DEFAULTS["PICKUP_WINDOW_END"],
        "donor_phone": donor_phone,
    }
    if donor_name is not None:
        overrides["donor_name"] = donor_name
    offer = create_donation_offer(items, **overrides)
    triaged = triage_offer(offer["id"])
    scheduled = schedule_pickup(offer["id"], truck_id)
    return {
        "offer": scheduled,
        "triaged": triaged,
        "items": list_donation_items(offer["id"]),
    }


def run_intake(offer_id: str, donation_items, grades=None, pest_flags=None,
               inspector: str = WAREHOUSE_INSPECTOR_ID) -> dict:
    """Inspect exactly the ACCEPTED pieces of an offer and mint stock."""
    accepted = [item for item in donation_items if item["decision"] == "ACCEPTED"]
    grades = grades if grades is not None else ["B"] * len(accepted)
    pest_flags = pest_flags if pest_flags is not None else [False] * len(accepted)
    inspections = [
        inspection_payload(item["id"], grade, pest)
        for item, grade, pest in zip(accepted, grades, pest_flags)
    ]
    return intake_offer(offer_id, inspections, inspector)


def supply_stock(truck_id: str, items, grades=None, pest_flags=None,
                 inspector: str = WAREHOUSE_INSPECTOR_ID, **offer_overrides) -> dict:
    """Full donation pipeline: offer -> triage -> pickup -> intake.

    Returns {"offer", "items", "inventory"} where "inventory" holds the minted
    stock units keyed in the same order as the accepted donation items.
    """
    prepared = prepare_offer_for_intake(truck_id, items, **offer_overrides)
    offer = run_intake(
        prepared["offer"]["id"], prepared["items"], grades, pest_flags, inspector
    )
    inventory = []
    for item in prepared["items"]:
        units = list_inventory(donation_item_id=item["id"])
        inventory.extend(units)
    return {"offer": offer, "items": prepared["items"], "inventory": inventory}


def supply_clean_stock(truck_id: str, items, grades=None,
                       inspector: str = WAREHOUSE_INSPECTOR_ID,
                       **offer_overrides) -> dict:
    """Clean-branch supply: no live pest, no soft-surface piece, so every minted
    unit lands directly in AVAILABLE."""
    return supply_stock(truck_id, items, grades=grades, pest_flags=None,
                        inspector=inspector, **offer_overrides)


def setup_quarantined_offer(truck_id: str, items=None, grades=None,
                            inspector: str = WAREHOUSE_INSPECTOR_ID,
                            **offer_overrides) -> dict:
    """Soft-surface intake: the offer lands in QUARANTINED and every minted unit
    sits in QUARANTINED awaiting release."""
    items = items if items is not None else [
        donation_item_payload("SOFA", "B", True, 40.0),
        donation_item_payload("DRESSER", "B", False, 20.0),
        donation_item_payload("TABLE_SET", "B", False, 20.0),
    ]
    return supply_stock(truck_id, items, grades=grades, inspector=inspector,
                        **offer_overrides)


# ─── Tier 4: allocated / booked / dispatched shortcuts ─────────────────

def setup_allocated_voucher(lines=None, offer_items=None, grades=None,
                            truck_label=None, truck_capacity=600,
                            crew_minimum=1, truck_county="CENTRAL",
                            allocator: str = WAREHOUSE_INSPECTOR_ID,
                            **voucher_kwargs) -> dict:
    """Issued voucher + a clean donation offer + one allocation round.

    Returns the `setup_issued_voucher` dict plus "truck", "offer",
    "donation_items", "inventory" and "allocated" (the allocate response body).
    """
    scenario = setup_issued_voucher(lines=lines, **voucher_kwargs)
    truck_kwargs = {
        "capacity_cubic_feet": truck_capacity,
        "home_county": truck_county,
        "crew_minimum": crew_minimum,
    }
    if truck_label is not None:
        truck_kwargs["label"] = truck_label
    truck = create_truck(**truck_kwargs)
    offer_items = offer_items if offer_items is not None else [
        donation_item_payload("BED", "B", False, 30.0)
    ]
    supply = supply_clean_stock(truck["id"], offer_items, grades=grades)
    allocated = allocate(
        scenario["voucher"]["id"], scenario["voucher"]["version"], allocator
    )
    scenario.update({
        "truck": truck,
        "offer": supply["offer"],
        "donation_items": supply["items"],
        "inventory": supply["inventory"],
        "allocated": allocated,
    })
    return scenario


def setup_crewed_run(truck_id: str, voucher_id: str, sequence: int = 1,
                     service_date=None, window_start=None, window_end=None,
                     county="CENTRAL", volunteer=None,
                     volunteer_name=None, lift_certified=True) -> dict:
    """Plan a run, book the voucher onto it and confirm one certified DRIVER, so
    the run reaches CREWED.

    Returns {"run", "stop", "volunteer", "crew"}.
    """
    if volunteer is None:
        vol_kwargs = {"county": county, "lift_certified": lift_certified}
        if volunteer_name is not None:
            vol_kwargs["name"] = volunteer_name
        volunteer = create_volunteer(**vol_kwargs)
    run = create_run(
        truck_id,
        service_date=service_date or TEST_DEFAULTS["RUN_SERVICE_DATE"],
        window_start=window_start or TEST_DEFAULTS["RUN_WINDOW_START"],
        window_end=window_end or TEST_DEFAULTS["RUN_WINDOW_END"],
        county=county,
    )
    stop = book_stop(run["id"], voucher_id, sequence, run["version"])
    crew = invite_crew(run["id"], volunteer["id"], "DRIVER")
    crew = respond_crew(crew["id"], volunteer["id"], "CONFIRM")
    return {
        "run": get_run(run["id"]),
        "stop": stop,
        "volunteer": volunteer,
        "crew": crew,
    }


def setup_dispatched_run(truck_id: str, voucher_id: str, **kwargs) -> dict:
    """`setup_crewed_run` followed by dispatch, so the run is on the road and its
    stock is STAGED."""
    booked = setup_crewed_run(truck_id, voucher_id, **kwargs)
    booked["run"] = dispatch_run(booked["run"]["id"])
    return booked


def setup_delivered_voucher(lines=None, offer_items=None, run_county="CENTRAL",
                            **kwargs) -> dict:
    """Allocated voucher booked, crewed, dispatched and closed as DELIVERED."""
    scenario = setup_allocated_voucher(lines=lines, offer_items=offer_items, **kwargs)
    booked = setup_dispatched_run(
        scenario["truck"]["id"], scenario["voucher"]["id"], county=run_county
    )
    scenario.update(booked)
    scenario["outcome"] = record_outcome(booked["stop"]["id"], "DELIVERED")
    return scenario


# ─── Tier 5: accumulation / terminal state ─────────────────────────────

def drive_stop_outcome(truck_id: str, voucher_id: str, outcome: str,
                       service_date: str, window_start: str, window_end: str,
                       volunteer=None, county="CENTRAL",
                       pest_observed_at_residence=None) -> dict:
    """Book a voucher onto a fresh run, crew it, dispatch it and close the stop
    with `outcome`. Used to accumulate strikes and terminal delivery stops."""
    booked = setup_dispatched_run(
        truck_id, voucher_id,
        service_date=service_date, window_start=window_start,
        window_end=window_end, county=county, volunteer=volunteer,
    )
    booked["outcome"] = record_outcome(
        booked["stop"]["id"], outcome, pest_observed_at_residence
    )
    return booked


def setup_banned_household(truck_label_prefix="BOX-BAN") -> dict:
    """Two consecutive NO_SHOWs on one household, which lifts no_show_strikes to
    the ban threshold and puts the household ON_HOLD under a delivery ban.

    Returns the allocated-voucher scenario plus "run1"/"run2" booking records.
    """
    scenario = setup_allocated_voucher(
        lines=[voucher_line_payload("BED", 1, "B")],
        offer_items=[donation_item_payload("BED", "B", False, 30.0)],
        truck_label=f"{truck_label_prefix}-1",
    )
    truck_id = scenario["truck"]["id"]
    volunteer = create_volunteer(county="CENTRAL", lift_certified=True)
    scenario["run1"] = drive_stop_outcome(
        truck_id, scenario["voucher"]["id"], "NO_SHOW",
        "2026-08-05", "2026-08-05T09:00:00Z", "2026-08-05T17:00:00Z",
        volunteer=volunteer,
    )
    scenario["run2"] = drive_stop_outcome(
        truck_id, scenario["voucher"]["id"], "NO_SHOW",
        "2026-08-06", "2026-08-06T09:00:00Z", "2026-08-06T17:00:00Z",
        volunteer=volunteer,
    )
    scenario["volunteer"] = volunteer
    return scenario


def setup_suspended_agency() -> dict:
    """One DELIVERED stop and one NO_SHOW stop under a single agency, which is an
    exact 0.50 no-show share and therefore SUSPENDED standing.

    Returns {"agency", "clients", "vouchers", "truck", "no_show_chargeback"}.
    """
    agency = create_agency(county="CENTRAL", quarterly_voucher_quota=5)
    client_a = create_client(agency["id"], household_size=4, county="CENTRAL")
    client_b = create_client(agency["id"], household_size=4, county="CENTRAL")

    referral_a = create_approved_referral(
        agency["id"], client_a["id"], requested_categories=["BED"]
    )
    voucher_a = issue_voucher(agency["id"], referral_a["id"],
                              [voucher_line_payload("BED", 1, "B")])
    referral_b = create_approved_referral(
        agency["id"], client_b["id"], requested_categories=["DRESSER"]
    )
    voucher_b = issue_voucher(agency["id"], referral_b["id"],
                              [voucher_line_payload("DRESSER", 1, "B")])

    truck = create_truck(capacity_cubic_feet=600, home_county="CENTRAL", crew_minimum=1)
    supply_clean_stock(truck["id"], [
        donation_item_payload("BED", "B", False, 30.0),
        donation_item_payload("DRESSER", "B", False, 20.0),
    ])
    allocate(voucher_a["id"], voucher_a["version"])
    allocate(voucher_b["id"], voucher_b["version"])

    volunteer = create_volunteer(county="CENTRAL", lift_certified=True)
    drive_stop_outcome(
        truck["id"], voucher_a["id"], "DELIVERED",
        "2026-08-05", "2026-08-05T09:00:00Z", "2026-08-05T17:00:00Z",
        volunteer=volunteer,
    )
    no_show = drive_stop_outcome(
        truck["id"], voucher_b["id"], "NO_SHOW",
        "2026-08-06", "2026-08-06T09:00:00Z", "2026-08-06T17:00:00Z",
        volunteer=volunteer,
    )
    return {
        "agency": agency,
        "clients": [client_a, client_b],
        "referrals": [referral_a, referral_b],
        "vouchers": [voucher_a, voucher_b],
        "truck": truck,
        "no_show": no_show,
        "no_show_chargeback": no_show["outcome"]["chargeback_cents"],
    }
