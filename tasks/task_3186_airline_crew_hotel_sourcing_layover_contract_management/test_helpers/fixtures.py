"""Composite setup helpers — multi-step API preconditions for tests.

Every fixture builds its preconditions from scratch against a fresh server.
Fixtures use get_success_data() (lenient) so setup failures surface clearly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_vendor_rep_headers
from .factories import (
    create_station_payload, create_union_agreement_payload,
    create_hotel_vendor_payload, create_rfp_cycle_payload,
    create_proposal_payload, create_award_payload, create_layover_payload,
    create_book_payload, create_invoice_payload,
)

ADMIN = TEST_USERS["admin_headers"]
SOURCING = TEST_USERS["sourcing_headers"]
CREWOPS = TEST_USERS["crewops_headers"]
FINANCE = TEST_USERS["finance_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

DEFAULT_DEADLINE = "2026-11-10T00:00:00Z"
DEFAULT_START = "2026-10-01T00:00:00Z"
DEFAULT_END = "2026-10-11T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: reference data builders
# ---------------------------------------------------------------------------

def _floor_clock():
    """PRD §2.4: the logical clock starts at exactly 2026-09-01T00:00:00Z.
    Fixture-driven scenarios live in Oct/Nov 2026, so every scenario first
    advances the clock past the startup instant (idempotent — a test that
    already set the clock later is unaffected)."""
    api_client.set_clock("2026-10-01T00:00:00Z", ADMIN)


def make_station(**overrides):
    """Create a station. Returns the station dict."""
    _floor_clock()
    resp = api_client.create_station(create_station_payload(**overrides), ADMIN)
    return get_success_data(resp)


def make_union_agreement(**overrides):
    """Create a union agreement. Returns the agreement dict."""
    resp = api_client.create_union_agreement(create_union_agreement_payload(**overrides), ADMIN)
    return get_success_data(resp)


def make_vendor(**overrides):
    """Create a hotel vendor (born ACTIVE). Returns the vendor dict."""
    resp = api_client.create_hotel_vendor(create_hotel_vendor_payload(**overrides), ADMIN)
    return get_success_data(resp)


def make_station_and_union(code, station_min_rest=10, transport=30,
                           crew_type="PILOT", union_min_rest=10,
                           variance_pct=10.0, **union_overrides):
    """Create a station plus a matching union agreement. Returns (station, union)."""
    station = make_station(code=code, min_rest_hours=station_min_rest,
                           transport_time_minutes=transport)
    union = make_union_agreement(crew_type=crew_type, min_rest_hours=union_min_rest,
                                 max_invoice_variance_pct=variance_pct, **union_overrides)
    return station, union


# ---------------------------------------------------------------------------
# Tier 2: RFP lifecycle — cycle, proposal, negotiation
# ---------------------------------------------------------------------------

def make_open_cycle_with_proposal(station_id, vendor, rate_cents=9000,
                                  rooms=5, budget_cap_cents=1_000_000,
                                  deadline=DEFAULT_DEADLINE, title="2026 crew hotel",
                                  target_room_count=None):
    """Create a DRAFT cycle, open it, and submit one proposal.
    Returns (cycle, proposal). Proposal is SUBMITTED; cycle is OPEN."""
    cycle = get_success_data(api_client.create_rfp_cycle(
        create_rfp_cycle_payload(
            station_id=station_id, title=title, response_deadline=deadline,
            target_room_count=target_room_count or rooms,
            budget_cap_cents=budget_cap_cents),
        SOURCING))
    get_success_data(api_client.open_rfp_cycle(cycle["id"], SOURCING))
    proposal = get_success_data(api_client.submit_proposal(
        cycle["id"],
        create_proposal_payload(vendor_id=vendor["id"], offered_room_count=rooms,
                                offered_rate_cents=rate_cents, quiet_room_commitment=rooms),
        make_vendor_rep_headers(vendor["id"])))
    return cycle, proposal


def make_negotiation_cycle(station_id, vendor, rate_cents=9000, rooms=5,
                           budget_cap_cents=1_000_000, deadline=DEFAULT_DEADLINE,
                           title="2026 crew hotel", target_room_count=None):
    """Walk a cycle to NEGOTIATION with one SHORTLISTED proposal.
    Returns (cycle, proposal)."""
    cycle, proposal = make_open_cycle_with_proposal(
        station_id, vendor, rate_cents=rate_cents, rooms=rooms,
        budget_cap_cents=budget_cap_cents, deadline=deadline, title=title,
        target_room_count=target_room_count)
    get_success_data(api_client.close_rfp_cycle(cycle["id"], SOURCING))
    get_success_data(api_client.shortlist_proposal(proposal["id"], SOURCING))
    get_success_data(api_client.open_negotiation(cycle["id"], SOURCING))
    cycle = get_success_data(api_client.get_rfp_cycle(cycle["id"], SOURCING))
    return cycle, proposal


# ---------------------------------------------------------------------------
# Tier 3: awarded + activated contracts
# ---------------------------------------------------------------------------

def award_cycle(cycle, proposal, room_block_size=5, start_date=DEFAULT_START,
                end_date=DEFAULT_END, late_cancel_hours=24,
                quiet_room_standard="ENHANCED", blackout_dates=None,
                blackout_protection=False, security_requirements=None):
    """Award a NEGOTIATION cycle. Returns the created DRAFT contract dict."""
    fresh = get_success_data(api_client.get_rfp_cycle(cycle["id"], SOURCING))
    resp = api_client.award_rfp_cycle(
        cycle["id"],
        create_award_payload(
            proposal_id=proposal["id"], room_block_size=room_block_size,
            start_date=start_date, end_date=end_date,
            late_cancel_hours=late_cancel_hours,
            quiet_room_standard=quiet_room_standard,
            security_requirements=security_requirements or ["KEYCARD_FLOOR"],
            blackout_dates=blackout_dates or [],
            blackout_protection=blackout_protection,
            expected_cycle_version=fresh["version"]),
        SOURCING)
    return get_success_data(resp)


def make_active_contract(station, vendor, rate_cents=9000, room_block_size=5,
                         start_date=DEFAULT_START, end_date=DEFAULT_END,
                         late_cancel_hours=24, quiet_room_standard="ENHANCED",
                         blackout_dates=None, blackout_protection=False,
                         budget_cap_cents=10_000_000, rooms_offered=None):
    """Full path: cycle -> open -> proposal -> close -> shortlist -> negotiate ->
    award -> activate. Returns the ACTIVE contract dict."""
    cycle, proposal = make_negotiation_cycle(
        station["id"], vendor, rate_cents=rate_cents,
        rooms=rooms_offered or room_block_size, budget_cap_cents=budget_cap_cents)
    contract = award_cycle(
        cycle, proposal, room_block_size=room_block_size, start_date=start_date,
        end_date=end_date, late_cancel_hours=late_cancel_hours,
        quiet_room_standard=quiet_room_standard, blackout_dates=blackout_dates,
        blackout_protection=blackout_protection)
    get_success_data(api_client.activate_contract(contract["id"], SOURCING))
    return get_success_data(api_client.get_contract(contract["id"], SOURCING))


# ---------------------------------------------------------------------------
# Tier 4: layovers and bookings
# ---------------------------------------------------------------------------

def make_layover(station_id, crew_type="PILOT", crew_count=2,
                 arrival="2026-10-02T18:00:00Z", departure="2026-10-03T09:00:00Z",
                 required_rest_hours=12, is_irregular_ops=None):
    """Create a layover requirement. Returns the layover dict (status PLANNED)."""
    payload = create_layover_payload(
        station_id=station_id, crew_type=crew_type, crew_count=crew_count,
        arrival_time=arrival, departure_time=departure,
        required_rest_hours=required_rest_hours)
    if is_irregular_ops is not None:
        payload["is_irregular_ops"] = is_irregular_ops
    resp = api_client.create_layover_requirement(payload, CREWOPS)
    return get_success_data(resp)


def book_layover(layover, contract_id, stay_date="2026-10-02T00:00:00Z",
                 blackout_rate_cents=None):
    """Book a PLANNED layover against a contract. Returns (layover, allocation)."""
    payload = create_book_payload(
        contract_id=contract_id, stay_date=stay_date,
        expected_layover_version=layover["version"])
    if blackout_rate_cents is not None:
        payload["blackout_rate_cents"] = blackout_rate_cents
    allocation = get_success_data(api_client.book_layover(layover["id"], payload, CREWOPS))
    fresh = get_success_data(api_client.get_layover_requirement(layover["id"], CREWOPS))
    return fresh, allocation


def make_confirmed_booking(station, contract, stay_date="2026-10-02T00:00:00Z",
                           crew_type="PILOT", crew_count=2,
                           arrival="2026-10-02T18:00:00Z",
                           departure="2026-10-03T09:00:00Z",
                           required_rest_hours=12, confirm=True):
    """Create layover + book + (optionally) confirm allocation.
    Returns (layover, allocation)."""
    layover = make_layover(station["id"], crew_type=crew_type, crew_count=crew_count,
                           arrival=arrival, departure=departure,
                           required_rest_hours=required_rest_hours)
    layover, allocation = book_layover(layover, contract["id"], stay_date=stay_date)
    if confirm:
        get_success_data(api_client.confirm_allocation(allocation["id"], CREWOPS))
        allocation = get_success_data(api_client.get_allocation(allocation["id"], CREWOPS))
    return layover, allocation


def make_checked_in_booking(station, contract, vendor, stay_date="2026-10-02T00:00:00Z",
                            crew_type="PILOT", crew_count=2,
                            arrival="2026-10-02T18:00:00Z",
                            departure="2026-10-03T09:00:00Z"):
    """Create layover + book + confirm + check-in.
    Returns (layover, allocation)."""
    layover, allocation = make_confirmed_booking(
        station, contract, stay_date=stay_date, crew_type=crew_type,
        crew_count=crew_count, arrival=arrival, departure=departure)
    get_success_data(api_client.check_in_allocation(
        allocation["id"], make_vendor_rep_headers(vendor["id"])))
    allocation = get_success_data(api_client.get_allocation(allocation["id"], CREWOPS))
    layover = get_success_data(api_client.get_layover_requirement(layover["id"], CREWOPS))
    return layover, allocation


def make_surged_layover(station, contract, stay_date="2026-10-02T00:00:00Z",
                        crew_type="PILOT", crew_count=2,
                        arrival="2026-10-02T18:00:00Z",
                        departure="2026-10-03T09:00:00Z"):
    """Book (leave HELD) + release -> layover SURGED. Returns (layover, released_allocation).

    PRD §3.6: release is `HELD → RELEASED`, so the allocation must NOT be
    confirmed before release; a CONFIRMED layover whose HELD allocation is
    released cascades to SURGED."""
    layover, allocation = make_confirmed_booking(
        station, contract, stay_date=stay_date, crew_type=crew_type,
        crew_count=crew_count, arrival=arrival, departure=departure,
        confirm=False)
    get_success_data(api_client.release_allocation(allocation["id"], CREWOPS))
    layover = get_success_data(api_client.get_layover_requirement(layover["id"], CREWOPS))
    return layover, allocation


def make_distressed_confirmed(layover, vendor, rate_cents=9000, confirm=True):
    """Distressed-book a SURGED layover and optionally confirm the allocation.
    Returns the distressed allocation dict."""
    allocation = get_success_data(api_client.distressed_book_layover(
        layover["id"], {"vendor_id": vendor["id"], "rate_cents": rate_cents}, CREWOPS))
    if confirm:
        get_success_data(api_client.confirm_allocation(allocation["id"], CREWOPS))
        allocation = get_success_data(api_client.get_allocation(allocation["id"], CREWOPS))
    return allocation


# ---------------------------------------------------------------------------
# Tier 5: invoices
# ---------------------------------------------------------------------------

def make_invoice(contract_id, vendor, billed_room_nights=0, billed_amount_cents=0,
                 period_start="2026-10-01T00:00:00Z", period_end="2026-10-30T00:00:00Z"):
    """Submit an invoice as the owning vendor rep. Returns the invoice dict."""
    resp = api_client.create_invoice(
        create_invoice_payload(
            contract_id=contract_id, billing_period_start=period_start,
            billing_period_end=period_end, billed_room_nights=billed_room_nights,
            billed_amount_cents=billed_amount_cents),
        make_vendor_rep_headers(vendor["id"]))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Composite: full sourcing stack in one call
# ---------------------------------------------------------------------------

def setup_sourced_station(code, station_min_rest=10, transport=30,
                          crew_type="PILOT", union_min_rest=10,
                          rate_cents=9000, room_block_size=5,
                          budget_cap_cents=10_000_000, start_date=DEFAULT_START,
                          end_date=DEFAULT_END, late_cancel_hours=24,
                          quiet_room_standard="ENHANCED", blackout_dates=None,
                          blackout_protection=False, variance_pct=10.0,
                          union_overrides=None):
    """Station + union + vendor + ACTIVE contract. Returns
    (station, union, vendor, contract)."""
    station, union = make_station_and_union(
        code, station_min_rest=station_min_rest, transport=transport,
        crew_type=crew_type, union_min_rest=union_min_rest,
        variance_pct=variance_pct, **(union_overrides or {}))
    vendor = make_vendor(name=f"{code} Hotel", contact_email=f"ops@{code.lower()}.example")
    contract = make_active_contract(
        station, vendor, rate_cents=rate_cents, room_block_size=room_block_size,
        start_date=start_date, end_date=end_date, late_cancel_hours=late_cancel_hours,
        quiet_room_standard=quiet_room_standard, blackout_dates=blackout_dates,
        blackout_protection=blackout_protection, budget_cap_cents=budget_cap_cents)
    return station, union, vendor, contract
