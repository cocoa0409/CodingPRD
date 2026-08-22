"""Composite setup helpers for multi-step test prerequisites.

Every helper uses `get_success_data()` so a broken precondition surfaces as a
clear "Setup step failed" rather than as a confusing assertion deep inside a
test. Each test starts against an empty database, so every helper builds its
own world from scratch through the PRD's own endpoints.

Identity threading: `MaterialsManager` acts as the supply room itself, so every
supply-room scope-gated call below is made with
`make_materials_manager_headers(room_id)`.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    adjust_on_hand_payload,
    claim_response_payload,
    claim_settle_payload,
    clinician_action_payload,
    contract_transition_payload,
    create_chargeback_claim_payload,
    create_contract_line_payload,
    create_contract_payload,
    create_delivery_route_payload,
    create_formulary_item_payload,
    create_item_payload,
    create_lot_payload,
    create_order_line_payload,
    create_order_payload,
    create_recall_notice_payload,
    create_route_stop_payload,
    create_substitution_request_payload,
    create_supply_room_payload,
    formulary_decision_payload,
    lot_excursion_payload,
    recall_cascade_payload,
    set_clock_payload,
    substitution_respond_payload,
)
from .test_users import (
    CLINICIAN_USER_ID,
    CONTRACT_ADMIN_USER_ID,
    DISTRIBUTION_OPERATOR_USER_ID,
    MANUFACTURER_REP_USER_ID,
    TEST_USERS,
    make_clinician_headers,
    make_contract_admin_headers,
    make_distribution_operator_headers,
    make_manufacturer_rep_headers,
    make_materials_manager_headers,
)

ADMIN = TEST_USERS["contract_admin_headers"]
OPERATOR = TEST_USERS["distribution_operator_headers"]
CLINICIAN = TEST_USERS["clinician_headers"]
REP = TEST_USERS["manufacturer_rep_headers"]


# ─── Tier 0: single-call primitives ───────────────────────────────────────

def set_clock(to_iso8601: str, user_id: str = CONTRACT_ADMIN_USER_ID) -> dict:
    """Move the server's logical clock."""
    return get_success_data(
        api_client.set_clock(
            set_clock_payload(to_iso8601), make_contract_admin_headers(user_id)
        )
    )


def create_supply_room(**overrides) -> dict:
    return get_success_data(
        api_client.create_supply_room(create_supply_room_payload(**overrides), ADMIN)
    )


def create_item(**overrides) -> dict:
    return get_success_data(
        api_client.create_item(create_item_payload(**overrides), ADMIN)
    )


def create_contract(**overrides) -> dict:
    return get_success_data(
        api_client.create_contract(create_contract_payload(**overrides), ADMIN)
    )


def add_contract_line(contract_id: str, item_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_contract_line(
            contract_id, create_contract_line_payload(item_id, **overrides), ADMIN
        )
    )


def transition_contract(contract_id: str, to_status: str) -> dict:
    return get_success_data(
        api_client.transition_contract(
            contract_id, contract_transition_payload(to_status), ADMIN
        )
    )


def activate_contract(contract_id: str) -> dict:
    """Walk DRAFT -> PENDING_ACTIVATION -> ACTIVE."""
    transition_contract(contract_id, "PENDING_ACTIVATION")
    return transition_contract(contract_id, "ACTIVE")


def map_formulary_item(room_id: str, item_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_formulary_item(
            room_id,
            create_formulary_item_payload(item_id, **overrides),
            make_materials_manager_headers(room_id),
        )
    )


def decide_formulary_item(
    formulary_item_id: str, decision: str, user_id: str = CLINICIAN_USER_ID
) -> dict:
    return get_success_data(
        api_client.decide_formulary_item(
            formulary_item_id,
            formulary_decision_payload(decision),
            make_clinician_headers(user_id),
        )
    )


def approve_formulary_item(room_id: str, item_id: str, **overrides) -> dict:
    """Map the item onto the room's formulary and have a clinician approve it."""
    mapping = map_formulary_item(room_id, item_id, **overrides)
    return decide_formulary_item(mapping["id"], "APPROVED")


def read_formulary_item(formulary_item_id: str) -> dict:
    return get_success_data(api_client.get_formulary_item(formulary_item_id, ADMIN))


def adjust_on_hand(
    formulary_item_id: str,
    room_id: str,
    delta_qty: int,
    expected_formulary_item_version: int = None,
) -> dict:
    if expected_formulary_item_version is None:
        expected_formulary_item_version = read_formulary_item(formulary_item_id)["version"]
    return get_success_data(
        api_client.adjust_on_hand(
            formulary_item_id,
            adjust_on_hand_payload(delta_qty, expected_formulary_item_version),
            make_materials_manager_headers(room_id),
        )
    )


def create_lot(item_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_lot(
            create_lot_payload(item_id, **overrides),
            make_distribution_operator_headers(DISTRIBUTION_OPERATOR_USER_ID),
        )
    )


def read_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_lot(lot_id, ADMIN))


def flag_lot_excursion(
    lot_id: str, user_id: str = DISTRIBUTION_OPERATOR_USER_ID, note: str = "Reefer alarm"
) -> dict:
    return get_success_data(
        api_client.lot_excursion(
            lot_id,
            lot_excursion_payload("FLAG", note),
            make_distribution_operator_headers(user_id),
        )
    )


def create_order(room_id: str) -> dict:
    return get_success_data(
        api_client.create_order(
            create_order_payload(room_id), make_materials_manager_headers(room_id)
        )
    )


def read_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, ADMIN))


def order_version(order_id: str) -> int:
    return read_order(order_id)["version"]


def add_order_line(
    order_id: str,
    room_id: str,
    item_id: str,
    requested_qty: int = 1,
    expected_order_version: int = None,
) -> dict:
    if expected_order_version is None:
        expected_order_version = order_version(order_id)
    return get_success_data(
        api_client.create_order_line(
            order_id,
            create_order_line_payload(item_id, requested_qty, expected_order_version),
            make_materials_manager_headers(room_id),
        )
    )


def read_order_line(order_line_id: str) -> dict:
    return get_success_data(api_client.get_order_line(order_line_id, ADMIN))


def list_order_lines_of(order_id: str) -> list:
    data, _meta = _paginate(api_client.list_order_lines, {"order_id": order_id})
    return data


def submit_order(order_id: str, room_id: str) -> dict:
    return get_success_data(
        api_client.submit_order(order_id, make_materials_manager_headers(room_id))
    )


def allocate_order(order_id: str, user_id: str = DISTRIBUTION_OPERATOR_USER_ID) -> dict:
    return get_success_data(
        api_client.allocate_order(order_id, make_distribution_operator_headers(user_id))
    )


def create_route(**overrides) -> dict:
    return get_success_data(
        api_client.create_delivery_route(create_delivery_route_payload(**overrides), OPERATOR)
    )


def read_route(route_id: str) -> dict:
    return get_success_data(api_client.get_delivery_route(route_id, ADMIN))


def add_route_stop(
    route_id: str,
    order_id: str,
    arrival_min: int = 480,
    service_minutes: int = 30,
    user_id: str = DISTRIBUTION_OPERATOR_USER_ID,
) -> dict:
    return get_success_data(
        api_client.create_route_stop(
            route_id,
            create_route_stop_payload(order_id, arrival_min, service_minutes),
            make_distribution_operator_headers(user_id),
        )
    )


def dispatch_route(route_id: str, user_id: str = DISTRIBUTION_OPERATOR_USER_ID) -> dict:
    return get_success_data(
        api_client.dispatch_route(route_id, make_distribution_operator_headers(user_id))
    )


def deliver_order(order_id: str, user_id: str = DISTRIBUTION_OPERATOR_USER_ID) -> dict:
    return get_success_data(
        api_client.deliver_order(order_id, make_distribution_operator_headers(user_id))
    )


def create_recall_notice(item_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_recall_notice(
            create_recall_notice_payload(item_id, **overrides),
            make_contract_admin_headers(CONTRACT_ADMIN_USER_ID),
        )
    )


def cascade_recall_notice(
    recall_notice_id: str,
    action: str = "CASCADE",
    user_id: str = DISTRIBUTION_OPERATOR_USER_ID,
) -> dict:
    return get_success_data(
        api_client.cascade_recall_notice(
            recall_notice_id,
            recall_cascade_payload(action),
            make_distribution_operator_headers(user_id),
        )
    )


def create_substitution_request(
    order_line_id: str, room_id: str, proposed_item_id: str, **overrides
) -> dict:
    return get_success_data(
        api_client.create_substitution_request(
            order_line_id,
            create_substitution_request_payload(proposed_item_id, **overrides),
            make_materials_manager_headers(room_id),
        )
    )


def clinician_decide_substitution(
    substitution_request_id: str,
    action: str,
    note: str = None,
    user_id: str = CLINICIAN_USER_ID,
) -> dict:
    return get_success_data(
        api_client.clinician_action(
            substitution_request_id,
            clinician_action_payload(action, note),
            make_clinician_headers(user_id),
        )
    )


def requester_respond_substitution(
    substitution_request_id: str, room_id: str, action: str, response_note: str = None
) -> dict:
    return get_success_data(
        api_client.respond_substitution_request(
            substitution_request_id,
            substitution_respond_payload(action, response_note),
            make_materials_manager_headers(room_id),
        )
    )


def read_substitution_request(substitution_request_id: str) -> dict:
    return get_success_data(
        api_client.get_substitution_request(substitution_request_id, ADMIN)
    )


def create_chargeback_claim(
    order_id: str, contract_id: str, user_id: str = CONTRACT_ADMIN_USER_ID
) -> dict:
    return get_success_data(
        api_client.create_chargeback_claim(
            create_chargeback_claim_payload(order_id, contract_id),
            make_contract_admin_headers(user_id),
        )
    )


def respond_to_claim(
    claim_id: str,
    outcome: str,
    dispute_reason: str = None,
    user_id: str = MANUFACTURER_REP_USER_ID,
) -> dict:
    return get_success_data(
        api_client.respond_chargeback_claim(
            claim_id,
            claim_response_payload(outcome, dispute_reason),
            make_manufacturer_rep_headers(user_id),
        )
    )


def settle_claim(claim_id: str, action: str, user_id: str) -> dict:
    return get_success_data(
        api_client.settle_chargeback_claim(
            claim_id, claim_settle_payload(action), make_contract_admin_headers(user_id)
        )
    )


def read_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_chargeback_claim(claim_id, ADMIN))


def read_contract(contract_id: str) -> dict:
    return get_success_data(api_client.get_contract(contract_id, ADMIN))


def read_contract_line(contract_line_id: str) -> dict:
    return get_success_data(api_client.get_contract_line(contract_line_id, ADMIN))


def read_supply_room(room_id: str) -> dict:
    return get_success_data(api_client.get_supply_room(room_id, ADMIN))


def read_recall_notice(recall_notice_id: str) -> dict:
    return get_success_data(api_client.get_recall_notice(recall_notice_id, ADMIN))


def _paginate(list_method, params: dict) -> tuple:
    merged = dict(params or {})
    merged.setdefault("limit", 100)
    merged.setdefault("offset", 0)
    response = list_method(ADMIN, params=merged)
    body = get_success_data(response)
    return body, response.json().get("meta", {})


def list_claims_of_contract(contract_id: str) -> list:
    data, _meta = _paginate(api_client.list_chargeback_claims, {"contract_id": contract_id})
    return data


def list_orders_of_room(room_id: str) -> list:
    data, _meta = _paginate(api_client.list_orders, {"supply_room_id": room_id})
    return data


def list_lines_drawn_from_lot(lot_id: str) -> list:
    data, _meta = _paginate(api_client.list_order_lines, {"lot_id": lot_id})
    return data




# ─── Tier 1: a priced catalogue ready to be ordered ───────────────────────

def setup_priced_catalogue(
    item_specs: list,
    room_overrides: dict = None,
    contract_overrides: dict = None,
    activate: bool = True,
) -> dict:
    """One supply room, one contract, and N items each carrying a contract
    price line and (optionally) a formulary mapping for the room.

    Every price line is written while the contract is still DRAFT, because a
    line added after activation would stay PENDING and price nothing.

    `item_specs` entries accept:
        item                dict of item-creation overrides
        tier_price_cents    default 3000
        floor_price_cents   default 2000
        chargeback_eligible omitted unless given
        priced              set False to skip the contract line entirely
        formulary           dict of formulary-mapping overrides, or None to
                            skip the mapping
        decision            clinician decision to record, default APPROVED,
                            None to leave the mapping REQUESTED

    Returns {"room", "contract", "items", "contract_lines", "formulary_items"}
    where the three lists are index-aligned with `item_specs` (entries that
    were skipped hold None).
    """
    room = create_supply_room(**(room_overrides or {}))
    contract = create_contract(**(contract_overrides or {}))

    items, contract_lines = [], []
    for spec in item_specs:
        item = create_item(**(spec.get("item") or {}))
        items.append(item)
        if spec.get("priced", True):
            line_kwargs = {
                "tier_price_cents": spec.get("tier_price_cents", 3000),
                "floor_price_cents": spec.get("floor_price_cents", 2000),
            }
            if "chargeback_eligible" in spec:
                line_kwargs["chargeback_eligible"] = spec["chargeback_eligible"]
            contract_lines.append(
                add_contract_line(contract["id"], item["id"], **line_kwargs)
            )
        else:
            contract_lines.append(None)

    if activate:
        contract = activate_contract(contract["id"])

    formulary_items = []
    for spec, item in zip(item_specs, items):
        if spec.get("formulary", {}) is None:
            formulary_items.append(None)
            continue
        mapping = map_formulary_item(room["id"], item["id"], **(spec.get("formulary") or {}))
        decision = spec.get("decision", "APPROVED")
        if decision is not None:
            mapping = decide_formulary_item(mapping["id"], decision)
        formulary_items.append(mapping)

    return {
        "room": room,
        "contract": contract,
        "items": items,
        "contract_lines": contract_lines,
        "formulary_items": formulary_items,
    }


def setup_priced_item(
    room_overrides: dict = None,
    item_overrides: dict = None,
    contract_overrides: dict = None,
    tier_price_cents: int = 3000,
    floor_price_cents: int = 2000,
    chargeback_eligible: bool = None,
    formulary_overrides: dict = None,
    formulary_decision: str = "APPROVED",
    activate: bool = True,
) -> dict:
    """Single-item convenience wrapper over `setup_priced_catalogue`.

    Returns {"room", "item", "contract", "contract_line", "formulary_item"}.
    """
    spec = {
        "item": item_overrides or {},
        "tier_price_cents": tier_price_cents,
        "floor_price_cents": floor_price_cents,
        "formulary": formulary_overrides or {},
        "decision": formulary_decision,
    }
    if chargeback_eligible is not None:
        spec["chargeback_eligible"] = chargeback_eligible

    world = setup_priced_catalogue(
        [spec],
        room_overrides=room_overrides,
        contract_overrides=contract_overrides,
        activate=activate,
    )
    return {
        "room": world["room"],
        "item": world["items"][0],
        "contract": world["contract"],
        "contract_line": world["contract_lines"][0],
        "formulary_item": world["formulary_items"][0],
    }


# ─── Tier 2: draft order, optionally carrying one line ────────────────────

def setup_draft_order(requested_qty: int = None, **priced_item_kwargs) -> dict:
    """Tier 1 plus a DRAFT order; when `requested_qty` is given, also one line."""
    world = setup_priced_item(**priced_item_kwargs)
    world["order"] = create_order(world["room"]["id"])
    if requested_qty is not None:
        world["order_line"] = add_order_line(
            world["order"]["id"],
            world["room"]["id"],
            world["item"]["id"],
            requested_qty,
            world["order"]["version"],
        )
        world["order"] = read_order(world["order"]["id"])
    return world


# ─── Tier 3: the canonical glove order, walked to any lifecycle stage ─────

GLOVE_ITEM_OVERRIDES = {
    "sku": "SKU-GLOVE-CS",
    "description": "Sterile surgical glove, case of 24",
    "manufacturer_code": "MFR-ACME",
    "uom": "CS",
    "wac_cents": TEST_DEFAULTS["GLOVE_WAC_CENTS"],
    "handling_class": "AMBIENT",
    "units_per_parent": TEST_DEFAULTS["GLOVE_UNITS_PER_PARENT"],
}

_STAGES = (
    "draft",
    "line",
    "submitted",
    "allocated",
    "routed",
    "dispatched",
    "delivered",
    "claimed",
)


def setup_glove_order(
    stage: str = "delivered",
    room_overrides: dict = None,
    item_overrides: dict = None,
    contract_overrides: dict = None,
    formulary_overrides: dict = None,
    tier_price_cents: int = TEST_DEFAULTS["GLOVE_TIER_PRICE_CENTS"],
    floor_price_cents: int = TEST_DEFAULTS["GLOVE_FLOOR_PRICE_CENTS"],
    chargeback_eligible: bool = True,
    requested_qty: int = 10,
    lot_overrides: dict = None,
    create_lot_row: bool = True,
    route_overrides: dict = None,
    arrival_min: int = 480,
    service_minutes: int = 30,
    claim_user_id: str = CONTRACT_ADMIN_USER_ID,
) -> dict:
    """The TIER_2 glove scenario shared by most of the deep test claims.

    An ACUTE OR core room, one AMBIENT case item of 24 eaches priced
    9000 / floor 8000 under a TIER_2 contract, one lot of 100 units, and one
    order of `requested_qty` cases walked to `stage`.

    Returns a dict with room / item / contract / contract_line /
    formulary_item / lot / order / order_line / route / claim as far as the
    requested stage reaches.
    """
    assert stage in _STAGES, f"unknown stage {stage!r}"

    room_defaults = {
        "facility_code": "FAC-GLOVE",
        "gpo_member_class": "ACUTE",
        "room_type": "OR_CORE",
        "credit_limit_cents": TEST_DEFAULTS["ROOM_CREDIT_LIMIT_CENTS"],
    }
    room_defaults.update(room_overrides or {})

    item_defaults = dict(GLOVE_ITEM_OVERRIDES)
    item_defaults.update(item_overrides or {})

    contract_defaults = {
        "manufacturer_code": "MFR-ACME",
        "tier": "TIER_2",
        "member_class_scope": "ACUTE",
        "effective_from": TEST_DEFAULTS["CONTRACT_EFFECTIVE_FROM"],
        "effective_to": TEST_DEFAULTS["CONTRACT_EFFECTIVE_TO"],
    }
    contract_defaults.update(contract_overrides or {})

    formulary_defaults = {
        "facility_item_code": "FAC-GLOVE",
        "par_qty": 400,
        "reorder_point": 100,
    }
    formulary_defaults.update(formulary_overrides or {})

    world = setup_priced_item(
        room_overrides=room_defaults,
        item_overrides=item_defaults,
        contract_overrides=contract_defaults,
        tier_price_cents=tier_price_cents,
        floor_price_cents=floor_price_cents,
        chargeback_eligible=chargeback_eligible,
        formulary_overrides=formulary_defaults,
    )

    if create_lot_row:
        lot_defaults = {
            "lot_code": "LOT-GLOVE-1",
            "expiry_date": TEST_DEFAULTS["LOT_EXPIRY"],
            "received_quantity": 100,
        }
        lot_defaults.update(lot_overrides or {})
        world["lot"] = create_lot(world["item"]["id"], **lot_defaults)

    world["order"] = create_order(world["room"]["id"])
    if stage == "draft":
        return world

    world["order_line"] = add_order_line(
        world["order"]["id"],
        world["room"]["id"],
        world["item"]["id"],
        requested_qty,
        world["order"]["version"],
    )
    world["order"] = read_order(world["order"]["id"])
    if stage == "line":
        return world

    world["order"] = submit_order(world["order"]["id"], world["room"]["id"])
    if stage == "submitted":
        return world

    world["order"] = allocate_order(world["order"]["id"])
    if stage == "allocated":
        return world

    route_defaults = {
        "route_code": "RT-GLOVE",
        "service_date": "2026-08-01",
        "vehicle_class": "AMBIENT_VAN",
    }
    route_defaults.update(route_overrides or {})
    world["route"] = create_route(**route_defaults)
    world["order"] = add_route_stop(
        world["route"]["id"], world["order"]["id"], arrival_min, service_minutes
    )
    if stage == "routed":
        return world

    world["route"] = dispatch_route(world["route"]["id"])
    world["order"] = read_order(world["order"]["id"])
    if stage == "dispatched":
        return world

    world["order"] = deliver_order(world["order"]["id"])
    if stage == "delivered":
        return world

    world["claim"] = create_chargeback_claim(
        world["order"]["id"], world["contract"]["id"], claim_user_id
    )
    world["order"] = read_order(world["order"]["id"])
    return world


# ─── Tier 4: lifecycle walkers and backorder staging ──────────────────────

def walk_order_to_delivered(
    world: dict,
    route_overrides: dict = None,
    arrival_min: int = 480,
    service_minutes: int = 30,
) -> dict:
    """Submit -> allocate -> route -> dispatch -> deliver an order already
    carrying at least one line. Mutates and returns `world`."""
    world["order"] = submit_order(world["order"]["id"], world["room"]["id"])
    world["order"] = allocate_order(world["order"]["id"])
    world["route"] = create_route(**(route_overrides or {}))
    world["order"] = add_route_stop(
        world["route"]["id"], world["order"]["id"], arrival_min, service_minutes
    )
    world["route"] = dispatch_route(world["route"]["id"])
    world["order"] = deliver_order(world["order"]["id"])
    return world


def setup_backordered_line(
    primary_spec: dict = None,
    alternate_spec: dict = None,
    room_overrides: dict = None,
    contract_overrides: dict = None,
    requested_qty: int = 4,
) -> dict:
    """A submitted order whose only line found no lot and is therefore
    BACKORDERED, plus a second, priced-and-approved item to substitute in.

    No lot exists for either item, so allocation backorders the line and the
    order lands in HELD.

    Returns {"room", "contract", "item", "alt_item", "contract_line",
    "alt_contract_line", "formulary_item", "alt_formulary_item", "order",
    "order_line"}.
    """
    primary = {
        "item": {
            "sku": "SKU-PRIMARY-CS",
            "description": "Primary commodity, case",
            "uom": "CS",
            "wac_cents": 8000,
            "handling_class": "AMBIENT",
            "units_per_parent": 10,
        },
        "tier_price_cents": 6000,
        "floor_price_cents": 5000,
        "formulary": {"facility_item_code": "FAC-PRIMARY", "par_qty": 40,
                      "reorder_point": 8},
    }
    primary.update(primary_spec or {})

    alternate = {
        "item": {
            "sku": "SKU-ALTERNATE-CS",
            "description": "Alternate commodity, case",
            "uom": "CS",
            "wac_cents": 8500,
            "handling_class": "AMBIENT",
            "units_per_parent": 10,
        },
        "tier_price_cents": 6000,
        "floor_price_cents": 5000,
        "formulary": {"facility_item_code": "FAC-ALTERNATE", "par_qty": 40,
                      "reorder_point": 8},
    }
    alternate.update(alternate_spec or {})

    world = setup_priced_catalogue(
        [primary, alternate],
        room_overrides=room_overrides,
        contract_overrides=contract_overrides,
    )
    world["item"] = world["items"][0]
    world["alt_item"] = world["items"][1]
    world["contract_line"] = world["contract_lines"][0]
    world["alt_contract_line"] = world["contract_lines"][1]
    world["formulary_item"] = world["formulary_items"][0]
    world["alt_formulary_item"] = world["formulary_items"][1]

    world["order"] = create_order(world["room"]["id"])
    world["order_line"] = add_order_line(
        world["order"]["id"],
        world["room"]["id"],
        world["item"]["id"],
        requested_qty,
        world["order"]["version"],
    )
    world["order"] = submit_order(world["order"]["id"], world["room"]["id"])
    world["order"] = allocate_order(world["order"]["id"])
    world["order_line"] = read_order_line(world["order_line"]["id"])
    return world
