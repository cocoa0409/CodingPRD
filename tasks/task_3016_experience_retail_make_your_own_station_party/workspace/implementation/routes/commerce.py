"""Build-and-ship orders, gift cards, and registries (PRD 3.8-3.9)."""
from flask import Blueprint

from core import (
    ROLE_ASSOCIATE,
    ROLE_CUSTOMER,
    ROLE_MANAGER,
    body,
    db,
    endpoint,
    err,
    get_or_404,
    new_row,
    now,
    req_bool,
    req_int,
    req_str,
    require_owner,
    respond_list,
    respond_object,
    touch,
)
from domain import (
    abandon_session,
    create_session,
    find_consumable,
)

bp = Blueprint("commerce", __name__)

CUSTOMER = (ROLE_CUSTOMER,)
MANAGER = (ROLE_MANAGER,)
ASSOC = (ROLE_ASSOCIATE,)
ASSOC_MGR = (ROLE_ASSOCIATE, ROLE_MANAGER)
CUST_MGR = (ROLE_CUSTOMER, ROLE_MANAGER)


# ---------------------------------------------------------------------------
# Build-and-ship orders (PRD section 3.8)
# ---------------------------------------------------------------------------
@bp.route("/build-ship-orders", methods=["POST"])
@endpoint(*CUSTOMER)
def create_build_ship_order():
    data = body()
    store = get_or_404("stores", data.get("store_id"), "store")
    customer = get_or_404("customers", data.get("customer_id"), "customer")
    model = get_or_404("plush_models", data.get("plush_model_id"), "plush model")
    require_owner(customer["id"])
    chip_requested = req_bool(data, "sound_chip_requested")
    recipient = req_str(data, "recipient_name")
    # The assembly session is provisioned with the order so the fulfilment
    # pipeline can be driven from placement; start-assembly confirms stock and
    # moves the order to IN_ASSEMBLY.
    session = create_session(
        store_id=store["id"],
        customer_id=customer["id"],
        plush_model_id=model["id"],
        origin_type="BUILD_SHIP",
    )
    order = new_row(
        store_id=store["id"],
        customer_id=customer["id"],
        plush_model_id=model["id"],
        sound_chip_requested=chip_requested,
        recipient_name=recipient,
        workshop_session_id=session["id"],
        carrier_code=None,
        tracking_number=None,
        handed_over_at=None,
        status="PLACED",
    )
    session["build_ship_order_id"] = order["id"]
    db.build_ship_orders[order["id"]] = order
    return respond_object(order, status=201)


@bp.route("/build-ship-orders/<order_id>", methods=["GET"])
@endpoint(ROLE_CUSTOMER, ROLE_ASSOCIATE, ROLE_MANAGER)
def get_build_ship_order(order_id):
    return respond_object(get_or_404("build_ship_orders", order_id, "build-ship order"))


@bp.route("/build-ship-orders/<order_id>/workshops", methods=["GET"])
@endpoint(*ASSOC_MGR)
def list_build_ship_order_workshops(order_id):
    get_or_404("build_ship_orders", order_id, "build-ship order")
    return respond_list(
        [w for w in db.workshops.values() if w["build_ship_order_id"] == order_id]
    )


@bp.route("/build-ship-orders/<order_id>/start-assembly", methods=["POST"])
@endpoint(*ASSOC)
def start_build_ship_assembly(order_id):
    order = get_or_404("build_ship_orders", order_id, "build-ship order")
    if order["status"] != "PLACED":
        err(
            "ERR_INVALID_STATE",
            "Only a PLACED order can start assembly (current: %s)." % order["status"],
        )
    model = db.plush_models.get(order["plush_model_id"])
    fiber = find_consumable(order["store_id"], "STUFFING_FIBER")
    needed = model["required_stuffing_grams"] if model else 0
    if fiber is None or fiber["on_hand_qty"] < needed:
        err("ERR_INSUFFICIENT_STOCK", "Not enough stuffing fiber on hand.")
    if order["sound_chip_requested"]:
        chip = find_consumable(order["store_id"], "SOUND_CHIP")
        if chip is None or chip["on_hand_qty"] < 1:
            err("ERR_INSUFFICIENT_STOCK", "No sound chips on hand.")
    if order["workshop_session_id"] is None:
        session = create_session(
            store_id=order["store_id"],
            customer_id=order["customer_id"],
            plush_model_id=order["plush_model_id"],
            origin_type="BUILD_SHIP",
            build_ship_order_id=order["id"],
        )
        order["workshop_session_id"] = session["id"]
    order["status"] = "IN_ASSEMBLY"
    touch(order)
    return respond_object(order)


@bp.route("/build-ship-orders/<order_id>/handoff", methods=["POST"])
@endpoint(*ASSOC)
def handoff_build_ship_order(order_id):
    order = get_or_404("build_ship_orders", order_id, "build-ship order")
    if order["status"] != "READY_FOR_PICKUP":
        err(
            "ERR_INVALID_STATE",
            "Only a READY_FOR_PICKUP order can be handed off (current: %s)."
            % order["status"],
        )
    data = body()
    order["carrier_code"] = req_str(data, "carrier_code")
    order["tracking_number"] = req_str(data, "tracking_number")
    order["handed_over_at"] = now()
    order["status"] = "HANDED_TO_CARRIER"
    touch(order)
    return respond_object(order)


@bp.route("/build-ship-orders/<order_id>/cancel", methods=["POST"])
@endpoint(*CUSTOMER)
def cancel_build_ship_order(order_id):
    order = get_or_404("build_ship_orders", order_id, "build-ship order")
    require_owner(order["customer_id"])
    if order["status"] == "PLACED":
        order["status"] = "CANCELLED"
        touch(order)
        session = db.workshops.get(order["workshop_session_id"])
        if session is not None and session["status"] not in ("PAID", "ABANDONED"):
            abandon_session(session, cascade_parents=False)
        return respond_object(order)
    if order["status"] == "IN_ASSEMBLY":
        session = db.workshops.get(order["workshop_session_id"])
        # Cancellation is allowed only while the linked session has not yet
        # reached DRESSED (PRD section 3.8).
        if session is None or session["status"] not in (
            "SELECT",
            "SELECTED",
            "STUFFED",
            "SOUNDED",
            "BATHED",
        ):
            err(
                "ERR_INVALID_STATE",
                "The order can no longer be cancelled once assembly reaches DRESSED.",
            )
        order["status"] = "CANCELLED"
        touch(order)
        abandon_session(session, cascade_parents=False)
        return respond_object(order)
    err(
        "ERR_INVALID_STATE",
        "A %s order cannot be cancelled." % order["status"],
    )


# ---------------------------------------------------------------------------
# Gift cards (PRD section 3.9)
# ---------------------------------------------------------------------------
@bp.route("/gift-cards", methods=["POST"])
@endpoint(*MANAGER)
def create_gift_card():
    data = body()
    code = req_str(data, "code")
    initial_balance = req_int(data, "initial_balance_cents", minimum=1)
    if any(c["code"] == code for c in db.gift_cards.values()):
        err("ERR_VALIDATION", "A gift card with this code already exists.")
    card = new_row(
        code=code,
        balance_cents=initial_balance,
        initial_balance_cents=initial_balance,
        status="ACTIVE",
    )
    db.gift_cards[card["id"]] = card
    return respond_object(card, status=201)


@bp.route("/gift-cards/<card_id>", methods=["GET"])
@endpoint(*CUST_MGR)
def get_gift_card(card_id):
    return respond_object(get_or_404("gift_cards", card_id, "gift card"))


@bp.route("/gift-cards/<card_id>/disable", methods=["POST"])
@endpoint(*MANAGER)
def disable_gift_card(card_id):
    card = get_or_404("gift_cards", card_id, "gift card")
    if card["status"] != "ACTIVE":
        err(
            "ERR_INVALID_STATE",
            "Only an ACTIVE gift card can be disabled (current: %s)." % card["status"],
        )
    card["status"] = "DISABLED"
    touch(card)
    return respond_object(card)


# ---------------------------------------------------------------------------
# Registries (PRD section 3.9)
# ---------------------------------------------------------------------------
@bp.route("/registries", methods=["POST"])
@endpoint(*CUSTOMER)
def create_registry():
    data = body()
    customer = get_or_404("customers", data.get("customer_id"), "customer")
    require_owner(customer["id"])
    name = req_str(data, "name")
    registry = new_row(
        customer_id=customer["id"],
        name=name,
        linked_animal_ids=[],
        linked_gift_card_ids=[],
    )
    db.registries[registry["id"]] = registry
    return respond_object(registry, status=201)


@bp.route("/registries/<registry_id>", methods=["GET"])
@endpoint(*CUST_MGR)
def get_registry(registry_id):
    return respond_object(get_or_404("registries", registry_id, "registry"))


@bp.route("/registries/<registry_id>/link-animal", methods=["POST"])
@endpoint(*CUSTOMER)
def link_registry_animal(registry_id):
    registry = get_or_404("registries", registry_id, "registry")
    require_owner(registry["customer_id"])
    data = body()
    animal = get_or_404("animals", data.get("stuffed_animal_id"), "stuffed animal")
    if animal["id"] in registry["linked_animal_ids"]:
        # Re-linking to the same registry is a no-op success.
        return respond_object(registry)
    # Only an animal owned by the registry owner may be linked, and an animal
    # may belong to at most one registry. (The GIFT_CARD_LINKED tender flow
    # links the session's minted animal before payment, so linkage is not
    # gated on the COMPLETED status.)
    if animal["customer_id"] != registry["customer_id"]:
        err(
            "ERR_REFERENTIAL_INTEGRITY",
            "The animal is not owned by the registry owner.",
        )
    for other in db.registries.values():
        if other["id"] != registry["id"] and animal["id"] in other["linked_animal_ids"]:
            err(
                "ERR_REFERENTIAL_INTEGRITY",
                "The animal is already linked to another registry.",
            )
    registry["linked_animal_ids"].append(animal["id"])
    touch(registry)
    return respond_object(registry)


@bp.route("/registries/<registry_id>/link-gift-card", methods=["POST"])
@endpoint(*CUSTOMER)
def link_registry_gift_card(registry_id):
    registry = get_or_404("registries", registry_id, "registry")
    require_owner(registry["customer_id"])
    data = body()
    card = get_or_404("gift_cards", data.get("gift_card_id"), "gift card")
    if card["id"] in registry["linked_gift_card_ids"]:
        return respond_object(registry)
    registry["linked_gift_card_ids"].append(card["id"])
    touch(registry)
    return respond_object(registry)
