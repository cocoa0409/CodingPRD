"""Scenario builders.

Every helper here drives the public API only -- there is no direct database
access -- so each test can assemble the world it needs from scratch. Helpers
return plain dictionaries of the records they created and accept ``**overrides``
that are forwarded to the underlying payload factory.

Two habits are deliberate. First, the booking version is always re-read
immediately before a booking-scoped write, because the cascades of §2.8 bump
that version constantly. Second, every scenario sets the logical clock
explicitly, so no helper depends on a previous test's clock reading.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CANONICAL_CLOCK_UTC, TEST_DEFAULTS
from .factories import (
    build_activation_payload,
    build_announce_payload,
    build_artist_payload,
    build_contingency_action_payload,
    build_counter_payload,
    build_fair_edition_payload,
    build_offer_payload,
    build_revise_payload,
    build_rider_item_payload,
    build_rider_ruling_payload,
    build_sales_batch_payload,
    build_settlement_payload,
    build_sponsor_payload,
    build_stage_payload,
    build_talent_agent_payload,
    build_ticket_scale_payload,
)
from .test_users import (
    BOX_OFFICE_MANAGER_HEADERS,
    FAIR_OPERATIONS_DIRECTOR_HEADERS,
    PRODUCTION_MANAGER_HEADERS,
    SETTLEMENT_CONTROLLER_HEADERS,
    SPONSORSHIP_DIRECTOR_HEADERS,
    TALENT_BUYER_HEADERS,
    make_talent_agent_headers,
)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(current_utc=CANONICAL_CLOCK_UTC):
    """Move the logical clock and return the instant it now reads."""
    api_client.set_clock(current_utc, FAIR_OPERATIONS_DIRECTOR_HEADERS)
    return current_utc


# ---------------------------------------------------------------------------
# Primitive creators
# ---------------------------------------------------------------------------
def create_edition(**overrides):
    payload = build_fair_edition_payload(**overrides)
    return get_success_data(
        api_client.create_fair_edition(payload, FAIR_OPERATIONS_DIRECTOR_HEADERS)
    )


def create_stage(fair_edition_id, **overrides):
    payload = build_stage_payload(fair_edition_id, **overrides)
    return get_success_data(
        api_client.create_stage(payload, FAIR_OPERATIONS_DIRECTOR_HEADERS)
    )


def create_agent(**overrides):
    payload = build_talent_agent_payload(**overrides)
    return get_success_data(
        api_client.create_talent_agent(payload, TALENT_BUYER_HEADERS)
    )


def create_artist(agent_id, **overrides):
    payload = build_artist_payload(agent_id, **overrides)
    return get_success_data(api_client.create_artist(payload, TALENT_BUYER_HEADERS))


def create_offer(fair_edition_id, artist_id, target_stage_id, **overrides):
    payload = build_offer_payload(
        fair_edition_id, artist_id, target_stage_id, **overrides
    )
    return get_success_data(api_client.create_offer(payload, TALENT_BUYER_HEADERS))


def create_sponsor(**overrides):
    payload = build_sponsor_payload(**overrides)
    return get_success_data(
        api_client.create_sponsor(payload, SPONSORSHIP_DIRECTOR_HEADERS)
    )


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------
def get_edition(fair_edition_id, headers=None):
    return get_success_data(
        api_client.get_fair_edition(
            fair_edition_id, headers or FAIR_OPERATIONS_DIRECTOR_HEADERS
        )
    )


def get_stage(stage_id, headers=None):
    return get_success_data(
        api_client.get_stage(stage_id, headers or FAIR_OPERATIONS_DIRECTOR_HEADERS)
    )


def get_agent(agent_id, headers=None):
    return get_success_data(
        api_client.get_talent_agent(agent_id, headers or TALENT_BUYER_HEADERS)
    )


def get_artist(artist_id, headers=None):
    return get_success_data(
        api_client.get_artist(artist_id, headers or TALENT_BUYER_HEADERS)
    )


def get_offer(offer_id, headers=None):
    return get_success_data(
        api_client.get_offer(offer_id, headers or TALENT_BUYER_HEADERS)
    )


def get_booking(booking_id, headers=None):
    return get_success_data(
        api_client.get_show_booking(
            booking_id, headers or FAIR_OPERATIONS_DIRECTOR_HEADERS
        )
    )


def booking_version(booking_id):
    """Fresh version of a booking, read immediately before a guarded write."""
    return get_booking(booking_id)["version"]


def offer_version(offer_id):
    return get_offer(offer_id)["version"]


def get_advance(advance_id, headers=None):
    return get_success_data(
        api_client.get_production_advance(
            advance_id, headers or PRODUCTION_MANAGER_HEADERS
        )
    )


def get_rider_item(rider_item_id, headers=None):
    return get_success_data(
        api_client.get_rider_item(rider_item_id, headers or PRODUCTION_MANAGER_HEADERS)
    )


def get_ticket_scale(ticket_scale_id, headers=None):
    return get_success_data(
        api_client.get_ticket_scale(
            ticket_scale_id, headers or BOX_OFFICE_MANAGER_HEADERS
        )
    )


def get_activation(activation_id, headers=None):
    return get_success_data(
        api_client.get_sponsorship_activation(
            activation_id, headers or SPONSORSHIP_DIRECTOR_HEADERS
        )
    )


def get_settlement(settlement_id, headers=None):
    return get_success_data(
        api_client.get_settlement(settlement_id, headers or TALENT_BUYER_HEADERS)
    )


# ---------------------------------------------------------------------------
# Cascade-born record discovery. The booking, the advance, the seed rider line
# and the negotiation rounds are never returned by the request that creates
# them, so each is found through the list operation that filters on its key.
# ---------------------------------------------------------------------------
def find_booking_for_offer(offer_id, headers=None):
    response = api_client.list_show_bookings(
        headers or FAIR_OPERATIONS_DIRECTOR_HEADERS, {"offer_id": offer_id}
    )
    records = get_success_data(response)
    assert records, f"no show booking listed for offer {offer_id}"
    return records[0]


def find_replacement_booking(original_booking_id, headers=None):
    response = api_client.list_show_bookings(
        headers or FAIR_OPERATIONS_DIRECTOR_HEADERS,
        {"postponed_from_booking_id": original_booking_id},
    )
    records = get_success_data(response)
    assert records, f"no replacement booking listed for {original_booking_id}"
    return records[0]


def find_advance_for_booking(booking_id, headers=None):
    response = api_client.list_production_advances(
        headers or PRODUCTION_MANAGER_HEADERS, {"booking_id": booking_id}
    )
    records = get_success_data(response)
    assert records, f"no production advance listed for booking {booking_id}"
    return records[0]


def list_rider_items(advance_id, headers=None, params=None):
    return get_success_data(
        api_client.list_rider_items(
            advance_id, headers or PRODUCTION_MANAGER_HEADERS, params
        )
    )


def find_seed_rider_item(advance_id, headers=None):
    """The critical STAGING line created when the offer was accepted."""
    items = list_rider_items(advance_id, headers)
    seeds = [
        item
        for item in items
        if item["category"] == "STAGING"
        and item["description"] == TEST_DEFAULTS["SEED_RIDER_DESCRIPTION"]
    ]
    assert seeds, f"no seed staging rider line on advance {advance_id}"
    return seeds[0]


def list_offer_rounds(offer_id, headers=None, params=None):
    return get_success_data(
        api_client.list_offer_rounds(offer_id, headers or TALENT_BUYER_HEADERS, params)
    )


def list_ticket_scales(booking_id, headers=None, params=None):
    return get_success_data(
        api_client.list_ticket_scales(
            booking_id, headers or BOX_OFFICE_MANAGER_HEADERS, params
        )
    )


def list_sales_batches(ticket_scale_id, headers=None, params=None):
    return get_success_data(
        api_client.list_sales_batches(
            ticket_scale_id, headers or BOX_OFFICE_MANAGER_HEADERS, params
        )
    )


def list_contingency_actions(booking_id, headers=None, params=None):
    return get_success_data(
        api_client.list_contingency_actions(
            booking_id, headers or FAIR_OPERATIONS_DIRECTOR_HEADERS, params
        )
    )


def list_activations(headers=None, params=None):
    return get_success_data(
        api_client.list_sponsorship_activations(
            headers or SPONSORSHIP_DIRECTOR_HEADERS, params
        )
    )


# ---------------------------------------------------------------------------
# Composite worlds
# ---------------------------------------------------------------------------
def setup_base_world(
    clock=CANONICAL_CLOCK_UTC,
    edition_overrides=None,
    stage_overrides=None,
    agent_overrides=None,
    artist_overrides=None,
):
    """Clock, edition, one stage, one agent and one artist on that agent."""
    set_clock(clock)
    edition = create_edition(**(edition_overrides or {}))
    stage = create_stage(edition["id"], **(stage_overrides or {}))
    agent = create_agent(**(agent_overrides or {}))
    artist = create_artist(agent["id"], **(artist_overrides or {}))
    return {
        "edition": edition,
        "stage": stage,
        "agent": agent,
        "artist": artist,
        "agent_headers": make_talent_agent_headers(agent["user_id"]),
    }


def setup_draft_offer(world=None, **offer_overrides):
    """A drafted offer: it holds no stage slot and encumbers no budget."""
    world = world or setup_base_world()
    # The three foreign keys default to the world's records but may be steered by
    # an override, so one world can carry offers for several acts or stages.
    fair_edition_id = offer_overrides.pop("fair_edition_id", world["edition"]["id"])
    artist_id = offer_overrides.pop("artist_id", world["artist"]["id"])
    target_stage_id = offer_overrides.pop("target_stage_id", world["stage"]["id"])
    offer = create_offer(
        fair_edition_id,
        artist_id,
        target_stage_id,
        **offer_overrides,
    )
    scenario = dict(world)
    scenario["offer"] = offer
    return scenario


def setup_sent_offer(world=None, **offer_overrides):
    """A drafted offer carried through the six send gates into SENT."""
    scenario = setup_draft_offer(world, **offer_overrides)
    scenario["offer"] = get_success_data(
        api_client.send_offer(scenario["offer"]["id"], TALENT_BUYER_HEADERS)
    )
    return scenario


def setup_countered_offer(world=None, proposed_guarantee_cents=None, **offer_overrides):
    """A sent offer the agent has countered, leaving it in COUNTERED."""
    scenario = setup_sent_offer(world, **offer_overrides)
    asked = (
        proposed_guarantee_cents
        if proposed_guarantee_cents is not None
        else scenario["offer"]["offered_guarantee_cents"] + 1_000_000
    )
    payload = build_counter_payload(asked)
    scenario["offer"] = get_success_data(
        api_client.counter_offer(
            scenario["offer"]["id"], payload, scenario["agent_headers"]
        )
    )
    return scenario


def revise_offer(scenario, offered_guarantee_cents, **overrides):
    """Answer a counter with revised terms, echoing the offer's fresh version."""
    offer_id = scenario["offer"]["id"]
    payload = build_revise_payload(
        offer_version(offer_id), offered_guarantee_cents, **overrides
    )
    scenario["offer"] = get_success_data(
        api_client.revise_offer(offer_id, payload, TALENT_BUYER_HEADERS)
    )
    return scenario["offer"]


def setup_accepted_booking(world=None, **offer_overrides):
    """Acceptance, plus the booking spine it cascade-creates.

    Returns the offer, the show booking, the production advance and the seed
    staging rider line, each of the last three discovered through the list
    operation that filters on its foreign key.
    """
    scenario = setup_sent_offer(world, **offer_overrides)
    scenario["offer"] = get_success_data(
        api_client.accept_offer(scenario["offer"]["id"], scenario["agent_headers"])
    )
    booking = find_booking_for_offer(scenario["offer"]["id"])
    advance = find_advance_for_booking(booking["id"])
    scenario["booking"] = booking
    scenario["advance"] = advance
    scenario["seed_rider_item"] = find_seed_rider_item(advance["id"])
    return scenario


# ---------------------------------------------------------------------------
# Production advance
# ---------------------------------------------------------------------------
def add_rider_item(advance_id, **overrides):
    """Add a rider line; the first line added carries the advance into review."""
    payload = build_rider_item_payload(**overrides)
    return get_success_data(
        api_client.create_rider_item(advance_id, payload, PRODUCTION_MANAGER_HEADERS)
    )


def rule_rider_item(rider_item_id, decision, **overrides):
    payload = build_rider_ruling_payload(decision, **overrides)
    return get_success_data(
        api_client.rule_rider_item(rider_item_id, payload, PRODUCTION_MANAGER_HEADERS)
    )


def complete_advance(advance_id):
    return get_success_data(
        api_client.complete_production_advance(advance_id, PRODUCTION_MANAGER_HEADERS)
    )


def prepare_completed_advance(scenario, **opener_overrides):
    """Carry a freshly created advance all the way to ADVANCE_COMPLETE.

    A zero-cost rider line moves the advance out of ADVANCE_PENDING and is then
    ruled, the seed staging line is approved so that closure is admitted, and
    the advance is closed. Both approved costs are 0, so the advance's cost
    ledgers stay at 0.
    """
    advance = scenario["advance"]
    opener_payload = {
        "category": "LIGHTING",
        "description": "Follow spot call sheet",
        "requested_cost_cents": 0,
    }
    opener_payload.update(opener_overrides)
    opener = add_rider_item(advance["id"], **opener_payload)
    scenario["opener_rider_item"] = opener
    rule_rider_item(opener["id"], "APPROVED")
    rule_rider_item(scenario["seed_rider_item"]["id"], "APPROVED")
    scenario["advance"] = complete_advance(advance["id"])
    scenario["seed_rider_item"] = get_rider_item(scenario["seed_rider_item"]["id"])
    return scenario["advance"]


# ---------------------------------------------------------------------------
# Price tiers and box-office movement
# ---------------------------------------------------------------------------
def add_ticket_scale(booking_id, **overrides):
    """Create a price tier, echoing the booking version read a moment ago."""
    payload = build_ticket_scale_payload(booking_version(booking_id), **overrides)
    return get_success_data(
        api_client.create_ticket_scale(booking_id, payload, BOX_OFFICE_MANAGER_HEADERS)
    )


def record_sales_batch(ticket_scale_id, batch_kind="SALE", quantity=1, channel="ONLINE", **overrides):
    payload = build_sales_batch_payload(batch_kind, quantity, channel, **overrides)
    return get_success_data(
        api_client.create_sales_batch(
            ticket_scale_id, payload, BOX_OFFICE_MANAGER_HEADERS
        )
    )


def announce_booking(booking_id, doors_time_utc=None):
    payload = build_announce_payload(doors_time_utc)
    return get_success_data(
        api_client.announce_show_booking(
            booking_id, payload, FAIR_OPERATIONS_DIRECTOR_HEADERS
        )
    )


def mark_performed(booking_id):
    return get_success_data(
        api_client.mark_show_booking_performed(
            booking_id, FAIR_OPERATIONS_DIRECTOR_HEADERS
        )
    )


def setup_scaled_booking(world=None, scale_overrides=None, **offer_overrides):
    """An accepted booking carrying one price tier, so ticketing reads SCALED."""
    scenario = setup_accepted_booking(world, **offer_overrides)
    scenario["ticket_scale"] = add_ticket_scale(
        scenario["booking"]["id"], **(scale_overrides or {})
    )
    scenario["booking"] = get_booking(scenario["booking"]["id"])
    return scenario


def setup_announced_booking(
    world=None, scale_overrides=None, doors_time_utc=None, **offer_overrides
):
    """A scaled booking with a completed advance, announced and therefore on sale."""
    scenario = setup_scaled_booking(
        world, scale_overrides=scale_overrides, **offer_overrides
    )
    prepare_completed_advance(scenario)
    scenario["booking"] = announce_booking(scenario["booking"]["id"], doors_time_utc)
    scenario["ticket_scale"] = get_ticket_scale(scenario["ticket_scale"]["id"])
    return scenario


def setup_performed_booking(
    world=None,
    scale_overrides=None,
    doors_time_utc=None,
    sales=None,
    **offer_overrides,
):
    """An announced booking taken through its sales and marked performed.

    ``sales`` is a list of keyword dictionaries forwarded to
    ``record_sales_batch`` while the show is on sale. The clock is then moved to
    the booking's ``load_out_end_utc``, the instant at which the show counts as
    concluded.
    """
    scenario = setup_announced_booking(
        world,
        scale_overrides=scale_overrides,
        doors_time_utc=doors_time_utc,
        **offer_overrides,
    )
    scenario["batches"] = []
    for batch in sales or []:
        scenario["batches"].append(
            record_sales_batch(scenario["ticket_scale"]["id"], **batch)
        )
    set_clock(scenario["booking"]["load_out_end_utc"])
    scenario["booking"] = mark_performed(scenario["booking"]["id"])
    scenario["ticket_scale"] = get_ticket_scale(scenario["ticket_scale"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Sponsorship
# ---------------------------------------------------------------------------
def create_activation(sponsor_id, booking_id, **overrides):
    """Buy a rights package, echoing the booking version read a moment ago."""
    payload = build_activation_payload(
        sponsor_id, booking_id, booking_version(booking_id), **overrides
    )
    return get_success_data(
        api_client.create_sponsorship_activation(payload, SPONSORSHIP_DIRECTOR_HEADERS)
    )


def confirm_activation(activation_id):
    return get_success_data(
        api_client.confirm_sponsorship_activation(
            activation_id, SPONSORSHIP_DIRECTOR_HEADERS
        )
    )


def cancel_activation(activation_id):
    return get_success_data(
        api_client.cancel_sponsorship_activation(
            activation_id, SPONSORSHIP_DIRECTOR_HEADERS
        )
    )


def setup_confirmed_activation(scenario, sponsor_overrides=None, **activation_overrides):
    """A sponsor, an activation on the scenario's booking, and its confirmation."""
    sponsor = create_sponsor(**(sponsor_overrides or {}))
    activation = create_activation(
        sponsor["id"], scenario["booking"]["id"], **activation_overrides
    )
    scenario["sponsor"] = sponsor
    scenario["activation"] = confirm_activation(activation["id"])
    scenario["booking"] = get_booking(scenario["booking"]["id"])
    return scenario["activation"]


# ---------------------------------------------------------------------------
# Weather contingency
# ---------------------------------------------------------------------------
def record_contingency_action(
    booking_id,
    action_type="CANCEL",
    reason_code="SEVERE_WEATHER",
    refund_policy="FULL_REFUND",
    **overrides,
):
    """Record a decision, echoing the booking version read a moment ago."""
    payload = build_contingency_action_payload(
        booking_version(booking_id),
        action_type=action_type,
        reason_code=reason_code,
        refund_policy=refund_policy,
        **overrides,
    )
    return get_success_data(
        api_client.create_contingency_action(
            booking_id, payload, FAIR_OPERATIONS_DIRECTOR_HEADERS
        )
    )


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------
def open_settlement(booking_id, **overrides):
    payload = build_settlement_payload(**overrides)
    return get_success_data(
        api_client.create_settlement(booking_id, payload, TALENT_BUYER_HEADERS)
    )


def submit_settlement(settlement_id):
    return get_success_data(
        api_client.submit_settlement(settlement_id, TALENT_BUYER_HEADERS)
    )


def approve_settlement(settlement_id):
    """Approve as the controller, whose identifier differs from the submitter's."""
    return get_success_data(
        api_client.approve_settlement(settlement_id, SETTLEMENT_CONTROLLER_HEADERS)
    )


def settlement_preview(booking_id, params=None, headers=None):
    return get_success_data(
        api_client.get_settlement_preview(
            booking_id, headers or TALENT_BUYER_HEADERS, params
        )
    )


def buying_strategy_report(fair_edition_id, headers=None):
    return get_success_data(
        api_client.get_buying_strategy_report(
            fair_edition_id, headers or TALENT_BUYER_HEADERS
        )
    )


def setup_draft_settlement(scenario, **overrides):
    scenario["settlement"] = open_settlement(scenario["booking"]["id"], **overrides)
    return scenario["settlement"]


def setup_submitted_settlement(scenario, **overrides):
    """A settlement whose whole waterfall has been computed on submission."""
    settlement = setup_draft_settlement(scenario, **overrides)
    scenario["settlement"] = submit_settlement(settlement["id"])
    return scenario["settlement"]


def setup_approved_settlement(scenario, **overrides):
    """A submitted settlement approved by a user other than the submitter."""
    settlement = setup_submitted_settlement(scenario, **overrides)
    scenario["settlement"] = approve_settlement(settlement["id"])
    return scenario["settlement"]
