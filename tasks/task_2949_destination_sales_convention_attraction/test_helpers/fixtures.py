"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, using the lenient ``get_success_data`` validator so a broken
precondition reports as a setup failure rather than as a confusing assertion.

Identity threading: calls the PRD guards by ownership (a commitment offer,
withdrawal or pickup filing, and the planner's response) always use the
per-instance header builders with the acting entity's own ``id``.
"""
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_board_report_payload,
    create_bid_package_payload,
    create_center_hall_payload,
    create_hotel_payload,
    create_incentive_fund_payload,
    create_meeting_planner_payload,
    create_opportunity_payload,
    create_servicing_order_payload,
    create_space_hold_payload,
    estimate_payload,
    incentive_decision_payload,
    offer_payload,
    pickup_record_payload,
    planner_response_payload,
    request_incentive_payload,
    submit_payload,
    support_letter_payload,
    withdraw_payload,
)
from .test_users import (
    INCENTIVE_APPROVER_USER_ID,
    SALES_MANAGER_USER_ID,
    TEST_USERS,
    make_hotel_partner_headers,
    make_incentive_approver_headers,
    make_meeting_planner_headers,
    make_sales_manager_headers,
)

ADMIN = TEST_USERS["bureau_admin_headers"]
SALES = TEST_USERS["sales_manager_headers"]
SCHEDULER = TEST_USERS["center_scheduler_headers"]
APPROVER = TEST_USERS["incentive_approver_headers"]
SERVICES = TEST_USERS["services_manager_headers"]
ANALYST = TEST_USERS["board_analyst_headers"]

DEFAULT_CLOCK = "2027-03-01T00:00:00Z"


# --- primitives --------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Pin the server's logical clock; returns the answered clock payload."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def register_planner(**overrides) -> dict:
    payload = create_meeting_planner_payload(**overrides)
    return get_success_data(api_client.create_meeting_planner(payload, ADMIN))


def register_hotel(**overrides) -> dict:
    payload = create_hotel_payload(**overrides)
    return get_success_data(api_client.create_hotel(payload, ADMIN))


def register_hall(**overrides) -> dict:
    payload = create_center_hall_payload(**overrides)
    return get_success_data(api_client.create_center_hall(payload, ADMIN))


def open_fund(**overrides) -> dict:
    payload = create_incentive_fund_payload(**overrides)
    return get_success_data(api_client.create_incentive_fund(payload, ADMIN))


def post_receipt(fund_id: str, amount: float, received_at: str) -> dict:
    return get_success_data(
        api_client.create_lodging_tax_receipt(
            fund_id, {"amount": amount, "received_at": received_at}, ADMIN
        )
    )


def suspend_hotel(hotel_id: str) -> dict:
    return get_success_data(
        api_client.set_hotel_participation(
            hotel_id, {"participation_status": "SUSPENDED"}, ADMIN
        )
    )


def reinstate_hotel(hotel_id: str) -> dict:
    return get_success_data(
        api_client.set_hotel_participation(
            hotel_id, {"participation_status": "PARTICIPATING"}, ADMIN
        )
    )


def create_lead(planner_id: str, **overrides) -> dict:
    payload = create_opportunity_payload(planner_id, **overrides)
    return get_success_data(api_client.create_opportunity(payload, SALES))


def read_opportunity(opportunity_id: str) -> dict:
    return get_success_data(api_client.get_opportunity(opportunity_id, SALES))


def opportunity_version(opportunity_id: str) -> int:
    return read_opportunity(opportunity_id)["version"]


def read_fund(fund_id: str) -> dict:
    return get_success_data(api_client.get_incentive_fund(fund_id, APPROVER))


def fund_version(fund_id: str) -> int:
    return read_fund(fund_id)["version"]


def read_hotel(hotel_id: str) -> dict:
    return get_success_data(api_client.get_hotel(hotel_id, ADMIN))


def read_hall(hall_id: str) -> dict:
    return get_success_data(api_client.get_center_hall(hall_id, SCHEDULER))


def read_hold(hold_id: str) -> dict:
    return get_success_data(api_client.get_space_hold(hold_id, SCHEDULER))


def read_commitment(commitment_id: str) -> dict:
    return get_success_data(api_client.get_room_block_commitment(commitment_id, SALES))


def read_bid(bid_id: str) -> dict:
    return get_success_data(api_client.get_bid_package(bid_id, SALES))


def read_planner(planner_id: str) -> dict:
    return get_success_data(api_client.get_meeting_planner(planner_id, ADMIN))


def read_servicing_order(order_id: str) -> dict:
    return get_success_data(api_client.get_servicing_order(order_id, SERVICES))


def qualify_lead(opportunity_id: str) -> dict:
    return get_success_data(api_client.qualify_opportunity(opportunity_id, SALES))


def lose_lead(opportunity_id: str, lost_reason: str) -> dict:
    return get_success_data(
        api_client.lose_opportunity(opportunity_id, {"lost_reason": lost_reason}, SALES)
    )


def place_hold(opportunity_id: str, hall_id: str, **overrides) -> dict:
    payload = create_space_hold_payload(opportunity_id, hall_id, **overrides)
    return get_success_data(api_client.create_space_hold(payload, SCHEDULER))


def challenge_hold(target_hold_id: str, challenging_space_hold_id: str) -> dict:
    return get_success_data(
        api_client.challenge_space_hold(
            target_hold_id,
            {"challenging_space_hold_id": challenging_space_hold_id},
            SCHEDULER,
        )
    )


def release_hold(hold_id: str) -> dict:
    return get_success_data(api_client.release_space_hold(hold_id, SCHEDULER))


def run_expiry() -> dict:
    return get_success_data(api_client.run_space_hold_expiry(SCHEDULER))


# --- room block assembly -----------------------------------------------------

def invite_hotel(opportunity_id: str, hotel_id: str, rooms_peak_invited: int = 500) -> dict:
    """Invite one property into the citywide block, guarded on the live version."""
    payload = {
        "opportunity_id": opportunity_id,
        "hotel_id": hotel_id,
        "rooms_peak_invited": rooms_peak_invited,
        "expected_opportunity_version": opportunity_version(opportunity_id),
    }
    return get_success_data(api_client.create_room_block_commitment(payload, SALES))


def offer_block(commitment_id: str, hotel_id: str, rooms_peak_offered: int,
                rate_offered_amount: float, cutoff_days_before_arrival: int) -> dict:
    payload = offer_payload(
        rooms_peak_offered=rooms_peak_offered,
        rate_offered_amount=rate_offered_amount,
        cutoff_days_before_arrival=cutoff_days_before_arrival,
    )
    return get_success_data(
        api_client.offer_room_block_commitment(
            commitment_id, payload, make_hotel_partner_headers(hotel_id)
        )
    )


def commit_block(commitment_id: str) -> dict:
    return get_success_data(api_client.commit_room_block_commitment(commitment_id, SALES))


def withdraw_block(commitment_id: str, hotel_id: str, withdraw_reason: str) -> dict:
    return get_success_data(
        api_client.withdraw_room_block_commitment(
            commitment_id,
            withdraw_payload(withdraw_reason),
            make_hotel_partner_headers(hotel_id),
        )
    )


def add_committed_block(opportunity_id: str, hotel_id: str, rooms: int,
                        rate: float, cutoff_days: int,
                        rooms_peak_invited: Optional[int] = None) -> dict:
    """Invite -> offer -> commit one property.  Returns the COMMITTED commitment."""
    commitment = invite_hotel(
        opportunity_id, hotel_id, rooms_peak_invited if rooms_peak_invited else rooms
    )
    offer_block(commitment["id"], hotel_id, rooms, rate, cutoff_days)
    return commit_block(commitment["id"])


def file_pickup(commitment_id: str, hotel_id: str, night_date: str,
                rooms_picked_up: int, rate_charged_amount: float) -> dict:
    return get_success_data(
        api_client.create_pickup_record(
            commitment_id,
            pickup_record_payload(night_date, rooms_picked_up, rate_charged_amount),
            make_hotel_partner_headers(hotel_id),
        )
    )


# --- bid package lifecycle ---------------------------------------------------

def open_bid(opportunity_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    payload = create_bid_package_payload(
        opportunity_id, opportunity_version(opportunity_id)
    )
    return get_success_data(api_client.create_bid_package(payload, headers or SALES))


def attach_letter(bid_id: str, letter_type: str, organization_name: Optional[str] = None) -> dict:
    return get_success_data(
        api_client.create_support_letter(
            bid_id, support_letter_payload(letter_type, organization_name), SALES
        )
    )


def attach_letters(bid_id: str, letter_types: Sequence[str] = ("MAYOR", "CHAMBER")) -> List[dict]:
    return [attach_letter(bid_id, lt) for lt in letter_types]


def ask_for_incentive(bid_id: str, amount: float,
                      headers: Optional[Dict[str, str]] = None,
                      service_commitment_codes: Optional[List[str]] = None) -> dict:
    payload = request_incentive_payload(amount)
    if service_commitment_codes is not None:
        payload["service_commitment_codes"] = service_commitment_codes
    return get_success_data(
        api_client.request_incentive(bid_id, payload, headers or SALES)
    )


def decide_incentive(bid_id: str, fund_id: str, decision: str, approved_amount: float,
                     approver_user_id: str = INCENTIVE_APPROVER_USER_ID,
                     rationale: Optional[str] = None) -> dict:
    payload = incentive_decision_payload(
        fund_id, decision, approved_amount, fund_version(fund_id)
    )
    if rationale is not None:
        payload["rationale"] = rationale
    return get_success_data(
        api_client.create_incentive_decision(
            bid_id, payload, make_incentive_approver_headers(approver_user_id)
        )
    )


def submit_bid(bid_id: str, response_due_at: str) -> dict:
    return get_success_data(
        api_client.submit_bid_package(bid_id, submit_payload(response_due_at), SALES)
    )


def answer_bid(bid_id: str, planner_id: str, response: str,
               decline_reason: Optional[str] = None) -> dict:
    payload = planner_response_payload(response)
    if decline_reason is not None:
        payload["decline_reason"] = decline_reason
    return get_success_data(
        api_client.planner_response(
            bid_id, payload, make_meeting_planner_headers(planner_id)
        )
    )


def compute_estimate(opportunity_id: str, variant: str) -> dict:
    return get_success_data(
        api_client.create_economic_impact_estimate(
            estimate_payload(opportunity_id, variant), ANALYST
        )
    )


def list_estimates(opportunity_id: str, variant: Optional[str] = None) -> List[dict]:
    params = {"variant": variant} if variant else None
    body = get_success_data(
        api_client.list_opportunity_estimates(opportunity_id, ANALYST, params=params)
    )
    return body


# --- servicing ---------------------------------------------------------------

def open_servicing_order(opportunity_id: str, **overrides) -> dict:
    payload = create_servicing_order_payload(opportunity_id, **overrides)
    return get_success_data(api_client.create_servicing_order(payload, SERVICES))


def schedule_order(order_id: str, assigned_units: int) -> dict:
    return get_success_data(
        api_client.schedule_servicing_order(
            order_id, {"assigned_units": assigned_units}, SERVICES
        )
    )


def deliver_order(order_id: str, delivered_units: int) -> dict:
    return get_success_data(
        api_client.deliver_servicing_order(
            order_id, {"delivered_units": delivered_units}, SERVICES
        )
    )


def cancel_order(order_id: str) -> dict:
    return get_success_data(api_client.cancel_servicing_order(order_id, SERVICES))


# --- board reports -----------------------------------------------------------

def create_report(period_start: str, period_end: str) -> dict:
    return get_success_data(
        api_client.create_board_report(
            create_board_report_payload(period_start, period_end), ANALYST
        )
    )


def publish_report(report_id: str) -> dict:
    return get_success_data(api_client.publish_board_report(report_id, ANALYST))


# --- Tier 2: inventory + lead scenarios --------------------------------------

# The canonical citywide scenario used by most composite fixtures:
#   clock 2027-03-01, a TIER_B planner (2 legacy definites / 6000 legacy room
#   nights -> relationship_score_lifetime 36), three participating properties,
#   one 48h-turnaround hall, one 500,000.00 fund, and a two-night convention
#   arriving 2028-04-10 with a 1,000-room peak request.
CANONICAL_HOTELS: Tuple[Tuple[str, int, int], ...] = (
    ("Harborview Grand", 600, 2),
    ("Bayside Suites", 400, 4),
    ("Cityline Inn", 200, 6),
)

CANONICAL_PLANNER = {
    "org_name": "Continental Dental Assembly",
    "contact_email": "meetings@cda.org",
    "legacy_definite_count": 2,
    "legacy_definite_room_nights": 6000,
}

CANONICAL_OPPORTUNITY = {
    "event_name": "CDA Annual 2028",
    "arrival_date": "2028-04-10",
    "departure_date": "2028-04-12",
    "peak_rooms_requested": 1000,
    "total_room_nights_requested": 1800,
    "attendance_estimate": 8000,
    "exhibit_sqft_requested": 200_000,
    "rate_ceiling_amount": 219.00,
}


def setup_inventory(clock: str = DEFAULT_CLOCK,
                    planner_overrides: Optional[Dict[str, Any]] = None,
                    hotel_specs: Sequence[Tuple[str, int, int]] = CANONICAL_HOTELS,
                    hall_overrides: Optional[Dict[str, Any]] = None,
                    fund_overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Clock + planner + properties + one hall + one fund.  No lead yet."""
    set_clock(clock)
    planner_payload = dict(CANONICAL_PLANNER)
    planner_payload.update(planner_overrides or {})
    planner = register_planner(**planner_payload)
    hotels = [
        register_hotel(name=name, committable_rooms=rooms, walk_distance_blocks=walk)
        for (name, rooms, walk) in hotel_specs
    ]
    hall = register_hall(**(hall_overrides or {}))
    fund = open_fund(**(fund_overrides or {}))
    return {
        "clock": clock,
        "planner": planner,
        "planner_id": planner["id"],
        "hotels": hotels,
        "hall": hall,
        "hall_id": hall["id"],
        "fund": fund,
        "fund_id": fund["id"],
    }


def setup_lead(clock: str = DEFAULT_CLOCK,
               opportunity_overrides: Optional[Dict[str, Any]] = None,
               qualify: bool = True,
               **inventory_kwargs) -> Dict[str, Any]:
    """Inventory plus one citywide lead, qualified by default."""
    scenario = setup_inventory(clock=clock, **inventory_kwargs)
    opp_payload = dict(CANONICAL_OPPORTUNITY)
    opp_payload.update(opportunity_overrides or {})
    opportunity = create_lead(scenario["planner_id"], **opp_payload)
    if qualify:
        opportunity = qualify_lead(opportunity["id"])
    scenario["opportunity"] = opportunity
    scenario["opportunity_id"] = opportunity["id"]
    return scenario


def setup_lead_with_hold(clock: str = DEFAULT_CLOCK,
                         hold_overrides: Optional[Dict[str, Any]] = None,
                         **lead_kwargs) -> Dict[str, Any]:
    """Qualified lead holding FIRST-rank space on the scenario's hall."""
    scenario = setup_lead(clock=clock, **lead_kwargs)
    hold = place_hold(
        scenario["opportunity_id"], scenario["hall_id"], **(hold_overrides or {})
    )
    scenario["hold"] = hold
    scenario["hold_id"] = hold["id"]
    scenario["opportunity"] = read_opportunity(scenario["opportunity_id"])
    return scenario


DEFAULT_ALLOCATIONS: Tuple[Tuple[int, int, float, int], ...] = (
    (0, 500, 214.33, 30),
    (1, 300, 209.77, 30),
    (2, 100, 199.51, 30),
)


def assemble_block(scenario: Dict[str, Any],
                   allocations: Sequence[Tuple[int, int, float, int]] = DEFAULT_ALLOCATIONS
                   ) -> Dict[str, Any]:
    """Invite, offer and commit each (hotel_index, rooms, rate, cutoff_days) row."""
    commitments = scenario.setdefault("commitments", [])
    for (hotel_index, rooms, rate, cutoff_days) in allocations:
        hotel = scenario["hotels"][hotel_index]
        commitments.append(
            add_committed_block(
                scenario["opportunity_id"], hotel["id"], rooms, rate, cutoff_days
            )
        )
    scenario["opportunity"] = read_opportunity(scenario["opportunity_id"])
    return scenario


def setup_block_assembled(clock: str = DEFAULT_CLOCK,
                          allocations: Sequence[Tuple[int, int, float, int]] = DEFAULT_ALLOCATIONS,
                          **hold_kwargs) -> Dict[str, Any]:
    """Qualified lead with a FIRST-rank hold and a committed citywide block."""
    scenario = setup_lead_with_hold(clock=clock, **hold_kwargs)
    return assemble_block(scenario, allocations)


# --- Tier 3: bid package lifecycle shortcuts ---------------------------------

def setup_bid_in_draft(clock: str = DEFAULT_CLOCK,
                       letter_types: Sequence[str] = ("MAYOR", "CHAMBER"),
                       allocations: Sequence[Tuple[int, int, float, int]] = DEFAULT_ALLOCATIONS,
                       **kwargs) -> Dict[str, Any]:
    """Block assembled, bid package opened in DRAFT with its support letters."""
    scenario = setup_block_assembled(clock=clock, allocations=allocations, **kwargs)
    bid = open_bid(scenario["opportunity_id"])
    attach_letters(bid["id"], letter_types)
    scenario["bid"] = read_bid(bid["id"])
    scenario["bid_id"] = bid["id"]
    return scenario


def setup_bid_incentive_pending(incentive_request_amount: float = 12_000.00,
                                **kwargs) -> Dict[str, Any]:
    """Bid package in INCENTIVE_PENDING with a fresh PROVISIONAL estimate."""
    scenario = setup_bid_in_draft(**kwargs)
    ask_for_incentive(scenario["bid_id"], incentive_request_amount)
    scenario["incentive_request_amount"] = incentive_request_amount
    scenario["bid"] = read_bid(scenario["bid_id"])
    return scenario


def setup_bid_approved(incentive_request_amount: float = 12_000.00,
                       approved_amount: Optional[float] = None,
                       decision: str = "APPROVED",
                       approver_user_id: str = INCENTIVE_APPROVER_USER_ID,
                       **kwargs) -> Dict[str, Any]:
    """Bid package in APPROVED with the fund charged for the decided amount."""
    scenario = setup_bid_incentive_pending(
        incentive_request_amount=incentive_request_amount, **kwargs
    )
    gross = incentive_request_amount if approved_amount is None else approved_amount
    scenario["decision"] = decide_incentive(
        scenario["bid_id"], scenario["fund_id"], decision, gross,
        approver_user_id=approver_user_id,
    )
    scenario["bid"] = read_bid(scenario["bid_id"])
    scenario["fund"] = read_fund(scenario["fund_id"])
    return scenario


DEFAULT_RESPONSE_DUE_AT = "2027-04-01T00:00:00Z"


def setup_bid_submitted(response_due_at: str = DEFAULT_RESPONSE_DUE_AT,
                        **kwargs) -> Dict[str, Any]:
    """Bid package in SUBMITTED with the lead moved to BIDDING."""
    scenario = setup_bid_approved(**kwargs)
    submit_bid(scenario["bid_id"], response_due_at)
    scenario["response_due_at"] = response_due_at
    scenario["bid"] = read_bid(scenario["bid_id"])
    scenario["opportunity"] = read_opportunity(scenario["opportunity_id"])
    return scenario


def setup_definite_lead(**kwargs) -> Dict[str, Any]:
    """Full pipeline through the planner's acceptance: lead is DEFINITE."""
    scenario = setup_bid_submitted(**kwargs)
    answer_bid(scenario["bid_id"], scenario["planner_id"], "ACCEPTED")
    scenario["bid"] = read_bid(scenario["bid_id"])
    scenario["opportunity"] = read_opportunity(scenario["opportunity_id"])
    scenario["hold"] = read_hold(scenario["hold_id"])
    scenario["planner"] = read_planner(scenario["planner_id"])
    return scenario


# --- Tier 4/5: pickup, servicing and terminal states -------------------------

DEFAULT_PICKUPS: Tuple[Tuple[int, str, int, float], ...] = (
    (0, "2028-04-10", 400, 214.33),
    (0, "2028-04-11", 250, 214.33),
    (1, "2028-04-10", 180, 209.77),
    (1, "2028-04-11", 150, 209.77),
    (2, "2028-04-10", 10, 199.51),
)


def report_pickups(scenario: Dict[str, Any],
                   pickups: Sequence[Tuple[int, str, int, float]] = DEFAULT_PICKUPS,
                   post_event_clock: Optional[str] = "2028-04-13T00:00:00Z"
                   ) -> Dict[str, Any]:
    """File nightly pickup rows against the scenario's committed commitments."""
    if post_event_clock:
        set_clock(post_event_clock)
        scenario["clock"] = post_event_clock
    records = scenario.setdefault("pickup_records", [])
    for (commitment_index, night_date, rooms, rate) in pickups:
        commitment = scenario["commitments"][commitment_index]
        hotel_id = commitment["hotel_id"]
        records.append(
            file_pickup(commitment["id"], hotel_id, night_date, rooms, rate)
        )
    scenario["opportunity"] = read_opportunity(scenario["opportunity_id"])
    return scenario


def setup_definite_lead_with_pickup(
        pickups: Sequence[Tuple[int, str, int, float]] = DEFAULT_PICKUPS,
        post_event_clock: Optional[str] = "2028-04-13T00:00:00Z",
        **kwargs) -> Dict[str, Any]:
    """DEFINITE lead whose properties have reported their actual pickup."""
    scenario = setup_definite_lead(**kwargs)
    return report_pickups(scenario, pickups, post_event_clock)


def setup_serviced_lead(deliver_units: int = 8, requested_units: int = 10,
                        **kwargs) -> Dict[str, Any]:
    """DEFINITE lead driven to SERVICED through one delivered servicing order."""
    scenario = kwargs.pop("scenario", None) or setup_definite_lead(**kwargs)
    order = open_servicing_order(scenario["opportunity_id"], requested_units=requested_units)
    schedule_order(order["id"], min(requested_units, max(deliver_units, 1)))
    deliver_order(order["id"], deliver_units)
    scenario["servicing_order"] = read_servicing_order(order["id"])
    scenario["opportunity"] = read_opportunity(scenario["opportunity_id"])
    scenario["fund"] = read_fund(scenario["fund_id"])
    return scenario
