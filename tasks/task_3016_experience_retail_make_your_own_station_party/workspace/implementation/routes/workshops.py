"""Workshop sessions (PRD sections 3.3-3.5) and stuffed animals (section 3.9)."""
from flask import Blueprint, g

from core import (
    ROLE_ASSOCIATE,
    ROLE_CUSTOMER,
    ROLE_MANAGER,
    ROLE_PARTY_HOST,
    body,
    db,
    endpoint,
    err,
    get_or_404,
    is_valid_date_string,
    new_row,
    is_int,
    req_enum,
    req_int,
    req_str,
    require_owner,
    respond_list,
    respond_object,
    touch,
)
from domain import (
    abandon_session,
    advance_session,
    create_session,
    find_guest_by_session,
    walk_in_admission_check,
)

bp = Blueprint("workshops", __name__)

ASSOC = (ROLE_ASSOCIATE,)
CUSTOMER = (ROLE_CUSTOMER,)
READ_WORKSHOP = (ROLE_CUSTOMER, ROLE_ASSOCIATE, ROLE_MANAGER)


# ---------------------------------------------------------------------------
# Workshop sessions
# ---------------------------------------------------------------------------
@bp.route("/workshops", methods=["POST"])
@endpoint(*ASSOC)
def create_workshop():
    data = body()
    # Body-referenced existence (priority 4) before any business rule.
    store = get_or_404("stores", data.get("store_id"), "store")
    customer = get_or_404("customers", data.get("customer_id"), "customer")
    model = get_or_404("plush_models", data.get("plush_model_id"), "plush model")
    origin_type = data.get("origin_type")

    # Walk-in admission (priority 8): capacity gate on the first-stage pool.
    if origin_type == "WALK_IN" or origin_type is None:
        walk_in_admission_check(store["id"])

    # Cross-entity referential integrity (priority 9).
    collection_drop_id = data.get("collection_drop_id")
    if model["is_licensed"]:
        if not collection_drop_id:
            err(
                "ERR_REFERENTIAL_INTEGRITY",
                "A licensed model requires a collection_drop_id.",
            )
        drop = get_or_404("collection_drops", collection_drop_id, "collection drop")
        if drop["plush_model_id"] != model["id"]:
            err(
                "ERR_REFERENTIAL_INTEGRITY",
                "The collection drop does not offer the selected plush model.",
            )
    else:
        if collection_drop_id is not None:
            err(
                "ERR_REFERENTIAL_INTEGRITY",
                "A non-licensed model cannot carry a collection_drop_id.",
            )

    # Field-level shape (priority 11).
    req_enum(data, "origin_type", ("WALK_IN",))
    session = create_session(
        store_id=store["id"],
        customer_id=customer["id"],
        plush_model_id=model["id"],
        origin_type="WALK_IN",
        collection_drop_id=collection_drop_id if model["is_licensed"] else None,
    )
    return respond_object(session, status=201)


@bp.route("/workshops/<session_id>", methods=["GET"])
@endpoint(*READ_WORKSHOP)
def get_workshop(session_id):
    return respond_object(get_or_404("workshops", session_id, "workshop session"))


@bp.route("/workshops/<session_id>/advance-step", methods=["POST"])
@endpoint(*ASSOC)
def advance_workshop(session_id):
    session = get_or_404("workshops", session_id, "workshop session")
    advance_session(session)
    return respond_object(session)


@bp.route("/workshops/<session_id>/abandon", methods=["POST"])
@endpoint(*ASSOC)
def abandon_workshop(session_id):
    session = get_or_404("workshops", session_id, "workshop session")
    abandon_session(session)
    return respond_object(session)


@bp.route("/workshops/<session_id>/payment", methods=["POST"])
@endpoint(*CUSTOMER)
def pay_workshop(session_id):
    session = get_or_404("workshops", session_id, "workshop session")
    require_owner(session["customer_id"])
    data = body()
    pay_tender = data.get("pay_tender")

    # Body-referenced existence (priority 4) for tender instruments.
    card = None
    registry = None
    if pay_tender in ("GIFT_CARD", "GIFT_CARD_LINKED"):
        card = get_or_404("gift_cards", data.get("gift_card_id"), "gift card")
    if pay_tender == "GIFT_CARD_LINKED":
        registry = get_or_404("registries", data.get("registry_id"), "registry")

    # State (priority 5).
    amount = data.get("payment_amount_cents")
    if session["status"] == "PAID":
        # Idempotent replay: the build-and-ship pipeline re-drives payment
        # after the session has already been paid. A matching amount returns
        # the session unchanged with no repeated side effects.
        if is_int(amount) and amount == session["total_price_cents"]:
            return respond_object(session)
        err(
            "ERR_PAYMENT_AMOUNT_MISMATCH",
            "payment_amount_cents must equal the session total.",
        )
    if session["status"] != "DRESSED":
        err(
            "ERR_INVALID_STATE",
            "Only a DRESSED session can be paid (current: %s)." % session["status"],
        )

    # Referential integrity (priority 9): linked-tender linkage is checked
    # before balance sufficiency (priority 10), per PRD section 3.5.
    if pay_tender == "GIFT_CARD_LINKED":
        animal_id = session["stuffed_animal_id"]
        if (
            card["id"] not in registry["linked_gift_card_ids"]
            or animal_id not in registry["linked_animal_ids"]
        ):
            err(
                "ERR_GIFT_CARD_NOT_LINKED",
                "The registry must link both the gift card and this session's animal.",
            )

    # Fiscal checks (priority 10).
    if pay_tender in ("CASH", "GIFT_CARD", "GIFT_CARD_LINKED"):
        if not isinstance(amount, int) or isinstance(amount, bool):
            err("ERR_VALIDATION", "payment_amount_cents must be an integer.")
        if amount != session["total_price_cents"]:
            err(
                "ERR_PAYMENT_AMOUNT_MISMATCH",
                "payment_amount_cents must equal the session total.",
            )
    else:
        # Unknown tender: field-level shape failure (priority 11).
        req_enum(data, "pay_tender", ("CASH", "GIFT_CARD", "GIFT_CARD_LINKED"))

    if pay_tender in ("GIFT_CARD", "GIFT_CARD_LINKED"):
        if card["status"] != "ACTIVE" or card["balance_cents"] < amount:
            err(
                "ERR_GIFT_CARD_INSUFFICIENT",
                "The gift card cannot cover this payment.",
            )

    # ---- side effects ----
    session["status"] = "PAID"
    touch(session)

    animal = db.animals.get(session["stuffed_animal_id"])
    if animal is not None and animal["status"] == "IN_PROGRESS":
        animal["status"] = "COMPLETED"
        touch(animal)

    if session["origin_type"] == "PARTY":
        guest = find_guest_by_session(session["id"])
        if guest is not None and guest["status"] == "CONFIRMED":
            guest["status"] = "ATTENDED"
            touch(guest)
    elif session["origin_type"] == "BUILD_SHIP":
        order = db.build_ship_orders.get(session["build_ship_order_id"])
        if order is not None and order["status"] in ("PLACED", "IN_ASSEMBLY"):
            order["status"] = "READY_FOR_PICKUP"
            touch(order)

    if pay_tender in ("GIFT_CARD", "GIFT_CARD_LINKED"):
        card["balance_cents"] -= amount
        if card["balance_cents"] == 0:
            card["status"] = "EXHAUSTED"
        touch(card)

    return respond_object(session)


@bp.route("/workshops/<session_id>/animals", methods=["GET"])
@endpoint(*READ_WORKSHOP)
def list_workshop_animals(session_id):
    get_or_404("workshops", session_id, "workshop session")
    return respond_list(
        [a for a in db.animals.values() if a["origin_workshop_session_id"] == session_id]
    )


@bp.route("/workshops/<session_id>/party-guests", methods=["GET"])
@endpoint(ROLE_CUSTOMER, ROLE_PARTY_HOST, ROLE_MANAGER)
def list_workshop_party_guests(session_id):
    get_or_404("workshops", session_id, "workshop session")
    return respond_list(
        [p for p in db.party_guests.values() if p["workshop_session_id"] == session_id]
    )


@bp.route("/workshops/<session_id>/build-ship-orders", methods=["GET"])
@endpoint(ROLE_ASSOCIATE, ROLE_MANAGER)
def list_workshop_build_ship_orders(session_id):
    get_or_404("workshops", session_id, "workshop session")
    return respond_list(
        [o for o in db.build_ship_orders.values() if o["workshop_session_id"] == session_id]
    )


# ---------------------------------------------------------------------------
# Stuffed animals (PRD section 3.9)
# ---------------------------------------------------------------------------
@bp.route("/animals/<animal_id>", methods=["GET"])
@endpoint(*READ_WORKSHOP)
def get_animal(animal_id):
    return respond_object(get_or_404("animals", animal_id, "stuffed animal"))


@bp.route("/animals/<animal_id>/workshops", methods=["GET"])
@endpoint(*READ_WORKSHOP)
def list_animal_workshops(animal_id):
    get_or_404("animals", animal_id, "stuffed animal")
    return respond_list(
        [w for w in db.workshops.values() if w["stuffed_animal_id"] == animal_id]
    )


@bp.route("/animals/<animal_id>/birth-certificate", methods=["POST"])
@endpoint(*CUSTOMER)
def personalize_birth_certificate(animal_id):
    animal = get_or_404("animals", animal_id, "stuffed animal")
    require_owner(animal["customer_id"])
    data = body()
    # Birth-certificate fields freeze once the origin session is PAID
    # (referential integrity, priority 9).
    session = db.workshops.get(animal["origin_workshop_session_id"])
    if session is not None and session["status"] == "PAID":
        err(
            "ERR_REFERENTIAL_INTEGRITY",
            "Birth certificate fields are immutable once the session is paid.",
        )
    name = req_str(data, "birth_cert_name")
    birth_date = data.get("birth_cert_birth_date")
    if not is_valid_date_string(birth_date):
        err(
            "ERR_VALIDATION",
            "birth_cert_birth_date must be a YYYY-MM-DD date string.",
        )
    animal["birth_cert_name"] = name
    animal["birth_cert_birth_date"] = birth_date
    touch(animal)
    return respond_object(animal)


@bp.route("/animals/<animal_id>/report-lost", methods=["POST"])
@endpoint(*CUSTOMER)
def report_lost(animal_id):
    animal = get_or_404("animals", animal_id, "stuffed animal")
    require_owner(animal["customer_id"])
    if animal["status"] != "COMPLETED":
        err(
            "ERR_INVALID_STATE",
            "Only a COMPLETED animal can be reported lost (current: %s)."
            % animal["status"],
        )
    animal["status"] = "LOST_REPORTED"
    touch(animal)
    return respond_object(animal)


@bp.route("/animals/<animal_id>/mark-recovered", methods=["POST"])
@endpoint(*CUSTOMER)
def mark_recovered(animal_id):
    animal = get_or_404("animals", animal_id, "stuffed animal")
    require_owner(animal["customer_id"])
    if animal["status"] != "LOST_REPORTED":
        err(
            "ERR_INVALID_STATE",
            "Only a LOST_REPORTED animal can be marked recovered (current: %s)."
            % animal["status"],
        )
    animal["status"] = "RECOVERED"
    touch(animal)
    return respond_object(animal)


@bp.route("/animals/<animal_id>/mark-found-cancel", methods=["POST"])
@endpoint(*CUSTOMER)
def mark_found_cancel(animal_id):
    animal = get_or_404("animals", animal_id, "stuffed animal")
    require_owner(animal["customer_id"])
    if animal["status"] != "LOST_REPORTED":
        err(
            "ERR_INVALID_STATE",
            "Only a LOST_REPORTED report can be cancelled (current: %s)."
            % animal["status"],
        )
    animal["status"] = "COMPLETED"
    touch(animal)
    return respond_object(animal)
