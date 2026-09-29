"""Composite setup helpers.

Every helper here drives the public API only: there is no direct data access.
The harness restarts the server before each test, so each helper builds its
world from an empty database.

Tiers, from cheapest to most expensive:

  1. atomic creators and transitions (one call each)
  2. ``build_scenario`` -- the whole broadcast preparation chain, parameterised
  3. named lifecycle shortcuts built on top of it (draft / ready / live / active)
  4. accumulation helpers that drive holds, checkouts, captures and interactions
  5. terminal helpers that end and settle a show

Ownership-gated calls are always made with the identity of the entity that owns
the resource: a booked host confirms and acknowledges with its own host header,
and a viewer holds, abandons, recovers and checks out with its own viewer
header.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_EPOCH, TEST_DEFAULTS
from .factories import (
    acknowledge_payload,
    add_cart_item_payload,
    cancel_booking_payload,
    cancel_order_payload,
    certify_host_payload,
    checkout_payload,
    claim_substantiation_payload,
    clock_payload,
    create_cart_payload,
    create_chat_payload,
    create_disclosure_record_payload,
    create_flash_offer_payload,
    create_host_booking_payload,
    create_host_payload,
    create_lineup_slot_payload,
    create_poll_payload,
    create_product_payload,
    create_question_payload,
    create_show_payload,
    create_stream_channel_payload,
    create_viewer_payload,
    health_report_payload,
    host_action_payload,
    inventory_adjustment_payload,
    moderate_payload,
    next_seq,
    replay_conversion_payload,
    replay_marker_payload,
    signoff_payload,
    vote_payload,
)
from .test_users import (
    make_compliance_officer_headers,
    make_host_headers,
    make_merchandising_manager_headers,
    make_moderator_headers,
    make_platform_admin_headers,
    make_show_producer_headers,
    make_viewer_headers,
    CERT_OFFICER_ID,
    CLAIMS_OFFICER_ID,
    SIGNOFF_OFFICER_ID,
)

PRODUCER = make_show_producer_headers()
MERCHANDISER = make_merchandising_manager_headers()
MODERATOR = make_moderator_headers()
ADMIN = make_platform_admin_headers()
CERT_OFFICER = make_compliance_officer_headers(CERT_OFFICER_ID)
CLAIMS_OFFICER = make_compliance_officer_headers(CLAIMS_OFFICER_ID)
SIGNOFF_OFFICER = make_compliance_officer_headers(SIGNOFF_OFFICER_ID)


# =========================================================== tier 1: atoms ===
def set_clock(current_utc: str) -> dict:
    """Pins the logical clock to an instant."""
    return get_success_data(api_client.set_current_utc(clock_payload(current_utc), ADMIN))


def register_host(**overrides) -> dict:
    return get_success_data(api_client.create_host(create_host_payload(**overrides), PRODUCER))


def certify_host(host_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.certify_host(host_id, certify_host_payload(**overrides), CERT_OFFICER)
    )


def register_certified_host(certified_until: Optional[str] = None, **overrides) -> dict:
    """Registers a host and certifies it, returning the certified host."""
    host = register_host(**overrides)
    return certify_host(
        host["id"], certified_until=certified_until or TEST_DEFAULTS["CERT_UNTIL"]
    )


def register_viewer(**overrides) -> dict:
    return get_success_data(api_client.create_viewer(create_viewer_payload(**overrides), ADMIN))


def create_product(**overrides) -> dict:
    return get_success_data(
        api_client.create_product(create_product_payload(**overrides), MERCHANDISER)
    )


def substantiate_claim(product_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.substantiate_claim(
            product_id, claim_substantiation_payload(**overrides), CLAIMS_OFFICER
        )
    )


def create_substantiated_product(evidence_ref: str = "LAB-88", **overrides) -> dict:
    product = create_product(**overrides)
    return substantiate_claim(product["id"], decision="SUBSTANTIATED", evidence_ref=evidence_ref)


def adjust_inventory(product_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.adjust_inventory(
            product_id, inventory_adjustment_payload(**overrides), MERCHANDISER
        )
    )


def create_show(**overrides) -> dict:
    return get_success_data(api_client.create_show(create_show_payload(**overrides), PRODUCER))


def book_host(show_id: str, host_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_host_booking(
            create_host_booking_payload(show_id, host_id, **overrides), PRODUCER
        )
    )


def confirm_booking(booking_id: str, host_id: str) -> dict:
    """The booked host accepts, using its own identity."""
    return get_success_data(
        api_client.confirm_host_booking(booking_id, make_host_headers(host_id))
    )


def cancel_booking(booking_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.cancel_host_booking(booking_id, cancel_booking_payload(**overrides), PRODUCER)
    )


def register_disclosure(show_id: str, booking_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_disclosure_record(
            create_disclosure_record_payload(show_id, booking_id, **overrides), PRODUCER
        )
    )


def acknowledge_disclosure(record_id: str, host_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.acknowledge_disclosure_record(
            record_id, acknowledge_payload(**overrides), make_host_headers(host_id)
        )
    )


def create_slot(show_id: str, product_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_lineup_slot(
            create_lineup_slot_payload(show_id, product_id, **overrides), MERCHANDISER
        )
    )


def read_slot(slot_id: str) -> dict:
    return get_success_data(api_client.get_lineup_slot(slot_id, MERCHANDISER))


def create_offer(slot_id: str, expected_lineup_slot_version: Optional[int] = None, **overrides) -> dict:
    """Creates a flash offer, reading the slot's current version when not given."""
    if expected_lineup_slot_version is None:
        expected_lineup_slot_version = read_slot(slot_id)["version"]
    return get_success_data(
        api_client.create_flash_offer(
            create_flash_offer_payload(slot_id, expected_lineup_slot_version, **overrides),
            MERCHANDISER,
        )
    )


def activate_offer(offer_id: str) -> dict:
    return get_success_data(api_client.activate_flash_offer(offer_id, MERCHANDISER))


def read_offer(offer_id: str) -> dict:
    return get_success_data(api_client.get_flash_offer(offer_id, MERCHANDISER))


def add_channel(show_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_stream_channel(
            create_stream_channel_payload(show_id, **overrides), PRODUCER
        )
    )


def provision_channel(channel_id: str) -> dict:
    return get_success_data(api_client.provision_stream_channel(channel_id, PRODUCER))


def report_health(channel_id: str, latency_ms: int, dropped_frame_pct: float = 0.0) -> dict:
    return get_success_data(
        api_client.report_channel_health(
            channel_id,
            health_report_payload(latency_ms=latency_ms, dropped_frame_pct=dropped_frame_pct),
            PRODUCER,
        )
    )


def read_channel(channel_id: str) -> dict:
    return get_success_data(api_client.get_stream_channel(channel_id, PRODUCER))


def ready_show(show_id: str) -> dict:
    return get_success_data(api_client.ready_show(show_id, PRODUCER))


def go_live(show_id: str) -> dict:
    return get_success_data(api_client.go_live_show(show_id, PRODUCER))


def end_show(show_id: str) -> dict:
    return get_success_data(api_client.end_show(show_id, PRODUCER))


def compliance_signoff(show_id: str, officer_id: str = SIGNOFF_OFFICER_ID, **overrides) -> dict:
    return get_success_data(
        api_client.compliance_signoff_show(
            show_id, make_compliance_officer_headers(officer_id), signoff_payload(**overrides)
        )
    )


def read_show(show_id: str) -> dict:
    return get_success_data(api_client.get_show(show_id, PRODUCER))


def read_product(product_id: str) -> dict:
    return get_success_data(api_client.get_product(product_id, MERCHANDISER))


def read_viewer(viewer_id: str) -> dict:
    return get_success_data(api_client.get_viewer(viewer_id, ADMIN))


def open_cart(show_id: str, viewer_id: str) -> dict:
    return get_success_data(
        api_client.create_cart(create_cart_payload(show_id), make_viewer_headers(viewer_id))
    )


def read_cart(cart_id: str, viewer_id: Optional[str] = None) -> dict:
    headers = make_viewer_headers(viewer_id) if viewer_id else MERCHANDISER
    return get_success_data(api_client.get_cart(cart_id, headers))


def add_line(cart_id: str, offer_id: str, viewer_id: str, qty: int = 1, **overrides) -> dict:
    return get_success_data(
        api_client.add_cart_item(
            cart_id, add_cart_item_payload(offer_id, qty, **overrides), make_viewer_headers(viewer_id)
        )
    )


def read_line(item_id: str) -> dict:
    return get_success_data(api_client.get_cart_item(item_id, MERCHANDISER))


def abandon_cart(cart_id: str, viewer_id: str) -> dict:
    return get_success_data(api_client.abandon_cart(cart_id, make_viewer_headers(viewer_id)))


def recover_cart(cart_id: str, viewer_id: str) -> dict:
    return get_success_data(api_client.recover_cart(cart_id, make_viewer_headers(viewer_id)))


def cart_version(cart_id: str, viewer_id: str) -> int:
    """A cart's version is never assumed: it is always read back first."""
    return read_cart(cart_id, viewer_id)["version"]


def checkout(cart_id: str, viewer_id: str, expected_version: Optional[int] = None) -> dict:
    version = expected_version if expected_version is not None else cart_version(cart_id, viewer_id)
    return get_success_data(
        api_client.checkout_cart(
            cart_id, checkout_payload(version), make_viewer_headers(viewer_id)
        )
    )


def read_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, MERCHANDISER))


def capture_order(order_id: str) -> dict:
    return get_success_data(api_client.capture_order(order_id, MERCHANDISER))


def cancel_order(order_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.cancel_order(order_id, cancel_order_payload(**overrides), MERCHANDISER)
    )


def set_marker(slot_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.set_replay_marker(slot_id, replay_marker_payload(**overrides), MERCHANDISER)
    )


def publish_marker(slot_id: str) -> dict:
    return get_success_data(api_client.publish_replay_marker(slot_id, MERCHANDISER))


def record_conversion(slot_id: str, viewer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.record_replay_conversion(
            slot_id, replay_conversion_payload(viewer_id, **overrides), MERCHANDISER
        )
    )


def submit_chat(show_id: str, viewer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_interaction(
            create_chat_payload(show_id, **overrides), make_viewer_headers(viewer_id)
        )
    )


def submit_question(show_id: str, viewer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_interaction(
            create_question_payload(show_id, **overrides), make_viewer_headers(viewer_id)
        )
    )


def open_poll(show_id: str, host_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_interaction(
            create_poll_payload(show_id, **overrides), make_host_headers(host_id)
        )
    )


def moderate(interaction_id: str, action: str = "APPROVE", **overrides) -> dict:
    return get_success_data(
        api_client.moderate_interaction(
            interaction_id, moderate_payload(action, **overrides), MODERATOR
        )
    )


def route_question(interaction_id: str) -> dict:
    return get_success_data(api_client.route_interaction(interaction_id, MODERATOR))


def host_action(interaction_id: str, action: str, host_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.host_action_interaction(
            interaction_id, host_action_payload(action, **overrides), make_host_headers(host_id)
        )
    )


def cast_vote(interaction_id: str, viewer_id: str, option_index: int = 0) -> dict:
    return get_success_data(
        api_client.cast_vote(
            interaction_id, vote_payload(option_index), make_viewer_headers(viewer_id)
        )
    )


# ====================================================== tier 2: the scenario ===
class Scenario:
    """A prepared broadcast, with every entity the preparation chain created."""

    def __init__(self, **fields):
        self.host: dict = fields.get("host") or {}
        self.viewers: List[dict] = fields.get("viewers") or []
        self.products: List[dict] = fields.get("products") or []
        self.show: dict = fields.get("show") or {}
        self.booking: Optional[dict] = fields.get("booking")
        self.bookings: List[dict] = fields.get("bookings") or []
        self.disclosure: Optional[dict] = fields.get("disclosure")
        self.slots: List[dict] = fields.get("slots") or []
        self.offers: List[dict] = fields.get("offers") or []
        self.channels: List[dict] = fields.get("channels") or []
        self.carts: List[dict] = fields.get("carts") or []

    # --- convenient singulars ---
    @property
    def host_id(self) -> str:
        return self.host["id"]

    @property
    def host_headers(self) -> Dict[str, str]:
        return make_host_headers(self.host["id"])

    @property
    def viewer(self) -> dict:
        return self.viewers[0]

    @property
    def viewer_id(self) -> str:
        return self.viewers[0]["id"]

    @property
    def viewer_headers(self) -> Dict[str, str]:
        return make_viewer_headers(self.viewers[0]["id"])

    @property
    def product(self) -> dict:
        return self.products[0]

    @property
    def product_id(self) -> str:
        return self.products[0]["id"]

    @property
    def show_id(self) -> str:
        return self.show["id"]

    @property
    def slot(self) -> dict:
        return self.slots[0]

    @property
    def slot_id(self) -> str:
        return self.slots[0]["id"]

    @property
    def offer(self) -> dict:
        return self.offers[0]

    @property
    def offer_id(self) -> str:
        return self.offers[0]["id"]

    @property
    def channel(self) -> dict:
        return self.channels[0]

    @property
    def channel_id(self) -> str:
        return self.channels[0]["id"]

    @property
    def cart(self) -> dict:
        return self.carts[0]

    @property
    def cart_id(self) -> str:
        return self.carts[0]["id"]

    def viewer_headers_for(self, index: int) -> Dict[str, str]:
        return make_viewer_headers(self.viewers[index]["id"])

    # --- fresh reads ---
    def fresh_show(self) -> dict:
        return read_show(self.show["id"])

    def fresh_product(self, index: int = 0) -> dict:
        return read_product(self.products[index]["id"])

    def fresh_offer(self, index: int = 0) -> dict:
        return read_offer(self.offers[index]["id"])

    def fresh_channel(self, index: int = 0) -> dict:
        return read_channel(self.channels[index]["id"])

    def fresh_cart(self, index: int = 0) -> dict:
        return read_cart(self.carts[index]["id"], self.viewers[index % len(self.viewers)]["id"])


DEFAULT_PRODUCT = {
    "sku": "SKU-ROBE",
    "title": "Silk Wrap Robe",
    "base_price_cents": 4000,
    "unit_cost_cents": 1500,
    "on_hand_qty": 50,
    "evidence_ref": "LAB-88",
}

DEFAULT_SLOT = {
    "slot_sequence": 1,
    "planned_start_at": "2026-08-10T18:05:00Z",
    "planned_end_at": "2026-08-10T18:35:00Z",
    "planned_qty": 20,
}

DEFAULT_OFFER = {
    "offer_price_cents": 3500,
    "window_start_at": "2026-08-10T18:00:00Z",
    "window_end_at": "2026-08-10T19:00:00Z",
    "max_qty": 10,
}

DEFAULT_CHANNEL = {
    "platform": "FLAGSHIP_APP",
    "target_latency_ms": 1500,
    "is_primary": True,
    "provision": True,
    "latency_ms": 1500,
    "dropped_frame_pct": 0.0,
}


def build_scenario(
    *,
    clock_start: str = CLOCK_EPOCH,
    host_overrides: Optional[dict] = None,
    certified_until: Optional[str] = None,
    certify: bool = True,
    num_viewers: int = 1,
    products: Optional[Sequence[dict]] = None,
    show_overrides: Optional[dict] = None,
    with_booking: bool = True,
    booking_overrides: Optional[dict] = None,
    confirm: bool = True,
    with_disclosure: bool = True,
    disclosure_overrides: Optional[dict] = None,
    acknowledge: bool = True,
    slots: Optional[Sequence[dict]] = None,
    offers: Optional[Sequence[dict]] = None,
    channels: Optional[Sequence[dict]] = None,
    run_ready: bool = False,
    take_live: bool = False,
    clock_prelive: str = TEST_DEFAULTS["CLOCK_PRELIVE"],
    clock_live: Optional[str] = TEST_DEFAULTS["CLOCK_LIVE"],
    activate: bool = False,
    num_carts: int = 0,
) -> Scenario:
    """Drives the broadcast preparation chain as far as the caller asks.

    ``products``, ``slots``, ``offers`` and ``channels`` take lists of override
    dicts; a slot override may carry ``product_index`` and an offer override may
    carry ``slot_index`` to point at an earlier member of the same scenario.
    """
    set_clock(clock_start)

    host = register_host(
        full_name=TEST_DEFAULTS["HOST_FULL_NAME"],
        handle=f"ada-vance-{next_seq()}",
        commission_pct=TEST_DEFAULTS["HOST_COMMISSION_PCT"],
        **(host_overrides or {}),
    )
    if certify:
        host = certify_host(host["id"], certified_until=certified_until or TEST_DEFAULTS["CERT_UNTIL"])

    viewers = [register_viewer() for _ in range(num_viewers)]

    product_specs = list(products) if products is not None else [dict(DEFAULT_PRODUCT)]
    built_products: List[dict] = []
    for spec in product_specs:
        spec = dict(spec)
        evidence_ref = spec.pop("evidence_ref", "LAB-88")
        decision = spec.pop("decision", "SUBSTANTIATED")
        substantiate = spec.pop("substantiate", True)
        spec.setdefault("sku", f"SKU-{next_seq():04d}")
        item = create_product(**spec)
        if substantiate:
            item = substantiate_claim(item["id"], decision=decision, evidence_ref=evidence_ref)
        built_products.append(item)

    show = create_show(**(show_overrides or {}))

    booking = None
    if with_booking:
        booking = book_host(show["id"], host["id"], **(booking_overrides or {}))

    disclosure = None
    if with_disclosure and booking is not None:
        disclosure = register_disclosure(show["id"], booking["id"], **(disclosure_overrides or {}))

    if booking is not None and confirm:
        booking = confirm_booking(booking["id"], host["id"])

    if disclosure is not None and acknowledge:
        disclosure = acknowledge_disclosure(disclosure["id"], host["id"])

    slot_specs = list(slots) if slots is not None else [dict(DEFAULT_SLOT)]
    built_slots: List[dict] = []
    for spec in slot_specs:
        spec = dict(spec)
        product_index = spec.pop("product_index", 0)
        built_slots.append(
            create_slot(show["id"], built_products[product_index]["id"], **spec)
        )

    offer_specs = list(offers) if offers is not None else [dict(DEFAULT_OFFER)]
    built_offers: List[dict] = []
    for spec in offer_specs:
        spec = dict(spec)
        slot_index = spec.pop("slot_index", 0)
        built_offers.append(create_offer(built_slots[slot_index]["id"], **spec))

    channel_specs = list(channels) if channels is not None else [dict(DEFAULT_CHANNEL)]
    built_channels: List[dict] = []
    for spec in channel_specs:
        spec = dict(spec)
        do_provision = spec.pop("provision", True)
        latency_ms = spec.pop("latency_ms", 1500)
        dropped_frame_pct = spec.pop("dropped_frame_pct", 0.0)
        channel = add_channel(show["id"], **spec)
        if do_provision:
            channel = provision_channel(channel["id"])
            if latency_ms is not None:
                channel = report_health(channel["id"], latency_ms, dropped_frame_pct)
        built_channels.append(channel)

    if run_ready or take_live:
        show = ready_show(show["id"])

    if take_live:
        set_clock(clock_prelive)
        show = go_live(show["id"])
        if clock_live is not None:
            set_clock(clock_live)

    if activate:
        built_offers = [activate_offer(offer["id"]) for offer in built_offers]

    carts: List[dict] = []
    for index in range(num_carts):
        owner = viewers[index % len(viewers)]
        carts.append(open_cart(show["id"], owner["id"]))

    return Scenario(
        host=host,
        viewers=viewers,
        products=built_products,
        show=show,
        booking=booking,
        bookings=[booking] if booking else [],
        disclosure=disclosure,
        slots=built_slots,
        offers=built_offers,
        channels=built_channels,
        carts=carts,
    )


# ============================================ tier 3: lifecycle shortcuts ===
def prepared_draft_show(**overrides) -> Scenario:
    """A DRAFT show with everything the readiness gate wants already in place."""
    return build_scenario(**overrides)


def ready_show_scenario(**overrides) -> Scenario:
    """The same show, taken through the readiness gate."""
    overrides.setdefault("run_ready", True)
    return build_scenario(**overrides)


def live_show_scenario(**overrides) -> Scenario:
    """A LIVE show whose offer is still SCHEDULED."""
    overrides.setdefault("take_live", True)
    return build_scenario(**overrides)


def live_show_with_active_offer(**overrides) -> Scenario:
    """A LIVE show with its flash offer ACTIVE and open for purchase."""
    overrides.setdefault("take_live", True)
    overrides.setdefault("activate", True)
    return build_scenario(**overrides)


def base_scenario(**overrides) -> Scenario:
    """The canonical shopping world: LIVE show, ACTIVE offer, two viewers, two open carts."""
    overrides.setdefault("num_viewers", 2)
    overrides.setdefault("num_carts", 2)
    overrides.setdefault("take_live", True)
    overrides.setdefault("activate", True)
    return build_scenario(**overrides)


# ================================= tier 4: accumulation and thresholds ===
def hold_line(
    scenario: Scenario,
    qty: int = 1,
    *,
    cart_index: int = 0,
    offer_index: int = 0,
    viewer_index: Optional[int] = None,
) -> dict:
    """Holds ``qty`` units of one offer into one of the scenario's carts."""
    if viewer_index is None:
        viewer_index = cart_index % len(scenario.viewers)
    return add_line(
        scenario.carts[cart_index]["id"],
        scenario.offers[offer_index]["id"],
        scenario.viewers[viewer_index]["id"],
        qty,
    )


def checkout_cart_of(scenario: Scenario, cart_index: int = 0, viewer_index: Optional[int] = None) -> dict:
    """Checks out one of the scenario's carts, reading its version first."""
    if viewer_index is None:
        viewer_index = cart_index % len(scenario.viewers)
    return checkout(scenario.carts[cart_index]["id"], scenario.viewers[viewer_index]["id"])


def held_cart_scenario(qty: int = 1, **overrides) -> Scenario:
    """A LIVE show with one viewer already holding units in an OPEN cart."""
    overrides.setdefault("num_carts", 1)
    scenario = base_scenario(**overrides)
    hold_line(scenario, qty)
    return scenario


def order_scenario(qty: int = 1, **overrides) -> tuple:
    """Holds units, checks out, and returns ``(scenario, order)``."""
    scenario = held_cart_scenario(qty, **overrides)
    order = checkout_cart_of(scenario, 0)
    return scenario, order


def captured_order_scenario(qty: int = 1, **overrides) -> tuple:
    """Holds units, checks out and captures, returning ``(scenario, order)``."""
    scenario, order = order_scenario(qty, **overrides)
    return scenario, capture_order(order["id"])


def add_offer_target(
    scenario: Scenario,
    *,
    product_overrides: Optional[dict] = None,
    slot_overrides: Optional[dict] = None,
    offer_overrides: Optional[dict] = None,
    evidence_ref: str = "LAB-89",
    activate: bool = True,
) -> dict:
    """Adds another substantiated product, lineup slot and flash offer to the show.

    The new members are appended to the scenario's own lists, so later helpers
    can address them by index.
    """
    product_spec = dict(product_overrides or {})
    product_spec.setdefault("sku", f"SKU-{next_seq():04d}")
    product = create_product(**product_spec)
    product = substantiate_claim(product["id"], decision="SUBSTANTIATED", evidence_ref=evidence_ref)

    slot_spec = {k: v for k, v in DEFAULT_SLOT.items() if k != "slot_sequence"}
    slot_spec.update(slot_overrides or {})
    slot_spec.setdefault("slot_sequence", len(scenario.slots) + 1)
    slot = create_slot(scenario.show["id"], product["id"], **slot_spec)

    offer_spec = dict(DEFAULT_OFFER)
    offer_spec.update(offer_overrides or {})
    offer = create_offer(slot["id"], **offer_spec)
    if activate:
        offer = activate_offer(offer["id"])

    scenario.products.append(product)
    scenario.slots.append(slot)
    scenario.offers.append(offer)
    return {"product": product, "slot": slot, "offer": offer}


def add_viewer_with_cart(scenario: Scenario) -> dict:
    """Registers one more viewer and opens a cart for it on the scenario's show."""
    viewer = register_viewer()
    cart = open_cart(scenario.show["id"], viewer["id"])
    scenario.viewers.append(viewer)
    scenario.carts.append(cart)
    return {"viewer": viewer, "cart": cart}


def book_second_show(
    scenario: Scenario,
    *,
    show_overrides: Optional[dict] = None,
    booking_overrides: Optional[dict] = None,
) -> dict:
    """Creates a second show and returns it, for host-calendar collision work."""
    show = create_show(**(show_overrides or {}))
    result = {"show": show, "booking": None}
    if booking_overrides is not None:
        result["booking"] = book_host(show["id"], scenario.host["id"], **booking_overrides)
    return result


def approved_question(scenario: Scenario, viewer_index: int = 0, route: bool = False) -> dict:
    """Submits a question, approves it, and optionally routes it to the host."""
    question = submit_question(scenario.show["id"], scenario.viewers[viewer_index]["id"])
    question = moderate(question["id"], "APPROVE")
    if route:
        question = route_question(question["id"])
    return question


def open_poll_on(scenario: Scenario, **overrides) -> dict:
    """Opens a poll on the scenario's live show, hosted by its booked host."""
    return open_poll(scenario.show["id"], scenario.host["id"], **overrides)


# ================================ tier 5: finalisation and terminal states ===
def end_scenario(scenario: Scenario, end_clock: str = "2026-08-10T19:30:00Z") -> dict:
    """Moves the clock past the airtime and ends the broadcast."""
    set_clock(end_clock)
    return end_show(scenario.show["id"])


def settle_scenario(
    scenario: Scenario,
    *,
    end_clock: str = "2026-08-10T19:30:00Z",
    officer_id: str = SIGNOFF_OFFICER_ID,
) -> dict:
    """Ends the broadcast and takes compliance sign-off, settling the show."""
    end_scenario(scenario, end_clock)
    return compliance_signoff(scenario.show["id"], officer_id)


def published_marker_scenario(
    *,
    marker_offset_sec: int = 600,
    end_clock: str = "2026-08-10T19:30:00Z",
    **overrides
) -> Scenario:
    """An ENDED show whose first lineup slot carries a PUBLISHED replay marker."""
    scenario = base_scenario(**overrides)
    end_scenario(scenario, end_clock)
    set_marker(scenario.slots[0]["id"], marker_offset_sec=marker_offset_sec)
    publish_marker(scenario.slots[0]["id"])
    return scenario
