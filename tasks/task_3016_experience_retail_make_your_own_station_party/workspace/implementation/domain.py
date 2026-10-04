"""Business logic: calculations, selectors, state transitions, cascades (PRD section 3)."""
from datetime import timedelta

from core import (
    db,
    err,
    new_row,
    now,
    require_owner,
    rhu_int,
    sort_created,
    touch,
)

# ---------------------------------------------------------------------------
# Constants (PRD section 3)
# ---------------------------------------------------------------------------
SOUND_CHIP_PRICE_CENTS = 1500
PER_GUEST_DEPOSIT_CENTS = 1000
FIXED_DEPOSIT_CENTS = 10000
ULTIMATE_DEPOSIT_FLOOR_CENTS = 20000
MIN_BOOKING_LEAD_HOURS = 72
SERVICE_CHARGE_PCT = 15
PACKAGE_PRICES = {"BASIC": 1899, "CELEBRATION": 4299, "ULTIMATE": 7999}
COMMISSION_PCT = 18
SETUP_BUFFER_MIN = 15
TEARDOWN_BUFFER_MIN = 15
DEFAULT_SESSION_DURATION_MIN = 45
PARTY_DURATION_MINUTES = 120

WORKSHOP_TERMINAL = ("PAID", "ABANDONED")

# Station type whose selector runs when advancing OUT of each stage.
# (PRD section 3.3: each advance re-points assigned_station_id to the station
# chosen for the next stage; BATHED -> DRESSED releases the assignment.)
NEXT_STAGE_STATION = {
    "SELECT": "STUFF",
    "SELECTED": "SOUND",
    "STUFFED": "BATHE",
    "SOUNDED": "DRESS",
}
WORKSHOP_ADVANCE_TARGET = {
    "SELECT": "SELECTED",
    "SELECTED": "STUFFED",
    "STUFFED": "SOUNDED",
    "SOUNDED": "BATHED",
    "BATHED": "DRESSED",
}


# ---------------------------------------------------------------------------
# Occupancy + selectors (walkin_capacity_occupancy, station_selector)
# ---------------------------------------------------------------------------
def _occupied_interval(session):
    """Half-open [started_at - 15min, started_at + 45min + 15min)."""
    start = session["started_at"] - timedelta(minutes=SETUP_BUFFER_MIN)
    end = session["started_at"] + timedelta(
        minutes=DEFAULT_SESSION_DURATION_MIN + TEARDOWN_BUFFER_MIN
    )
    return start, end


def station_occupancy(station, at=None):
    """Count of non-terminal sessions assigned to the station whose occupied
    interval covers `at` (start-inclusive, end-exclusive)."""
    at = at if at is not None else now()
    count = 0
    for session in db.workshops.values():
        if session["status"] in WORKSHOP_TERMINAL:
            continue
        if session["assigned_station_id"] != station["id"]:
            continue
        start, end = _occupied_interval(session)
        if start <= at < end:
            count += 1
    return count


def select_station(store_id, station_type, at=None):
    """station_selector: candidates of the matching type with occupancy strictly
    below capacity; lowest occupancy first; tie-break earliest created_at.
    Returns the station row or None when the pool is empty."""
    at = at if at is not None else now()
    candidates = []
    for station in db.stations.values():
        if station["store_id"] != store_id or station["station_type"] != station_type:
            continue
        occupancy = station_occupancy(station, at)
        if occupancy < station["capacity"]:
            candidates.append((occupancy, station["created_at"], station["_seq"], station))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return candidates[0][3]


def walk_in_admission_check(store_id):
    """POST /workshops admission: the station pool serving the first stage must
    have spare capacity, else ERR_STATION_AT_CAPACITY (PRD section 3.3)."""
    if select_station(store_id, "STUFF") is None:
        err(
            "ERR_STATION_AT_CAPACITY",
            "No station has spare capacity for a new workshop session.",
        )


# ---------------------------------------------------------------------------
# Consumables (consumables_on_hand)
# ---------------------------------------------------------------------------
def find_consumable(store_id, consumable_type):
    """The store's ledger row for a consumable type (earliest created)."""
    rows = [
        row
        for row in db.consumables.values()
        if row["store_id"] == store_id and row["consumable_type"] == consumable_type
    ]
    if not rows:
        return None
    return sort_created(rows)[0]


def consumable_on_hand(store_id, consumable_type):
    row = find_consumable(store_id, consumable_type)
    return row["on_hand_qty"] if row else 0


# ---------------------------------------------------------------------------
# Licensed collection drops (PRD section 3.2)
# ---------------------------------------------------------------------------
def customer_claimed_units(customer_id, drop_id):
    """Units of this drop the customer has selected across non-terminal sessions."""
    count = 0
    for session in db.workshops.values():
        if session["customer_id"] != customer_id:
            continue
        if session["collection_drop_id"] != drop_id:
            continue
        if session["status"] in WORKSHOP_TERMINAL or session["status"] == "SELECT":
            continue
        count += 1
    return count


def check_drop_claim_guards(session, drop):
    """Advance-time licensed rails in global order: temporal window (priority 6)
    before per-customer / total-units drop limits (priority 7)."""
    current = now()
    if not (drop["drop_start"] <= current < drop["drop_end"]):
        err(
            "ERR_OUTSIDE_TIME_WINDOW",
            "The collection drop purchase window is not open.",
        )
    if customer_claimed_units(session["customer_id"], drop["id"]) >= drop["per_customer_limit"]:
        err(
            "ERR_DROP_LIMIT_REACHED",
            "The customer has reached this drop's per-customer limit.",
        )
    if drop["units_claimed"] >= drop["total_units"]:
        err("ERR_DROP_LIMIT_REACHED", "The collection drop is sold out.")


# ---------------------------------------------------------------------------
# Workshop session lifecycle (PRD sections 3.3-3.5)
# ---------------------------------------------------------------------------
def create_session(store_id, customer_id, plush_model_id, origin_type,
                   collection_drop_id=None, party_reservation_id=None,
                   build_ship_order_id=None):
    session = new_row(
        store_id=store_id,
        customer_id=customer_id,
        plush_model_id=plush_model_id,
        collection_drop_id=collection_drop_id,
        origin_type=origin_type,
        party_reservation_id=party_reservation_id,
        build_ship_order_id=build_ship_order_id,
        assigned_station_id=None,
        stuffed_animal_id=None,
        stuffing_grams_used=0,
        sound_chip_used=False,
        total_price_cents=0,
        started_at=now(),
        status="SELECT",
    )
    db.workshops[session["id"]] = session
    return session


def advance_session(session):
    """POST /workshops/{id}/advance-step: one station step forward."""
    current = session["status"]
    if current == "DRESSED":
        # DRESSED is the end of the station line: the step release already
        # happened, so a further advance is a successful no-op replay rather
        # than a state change (the explicit negative contract covers only the
        # terminal states).
        return session
    if current == "PAID":
        if session["origin_type"] == "BUILD_SHIP":
            # Idempotent replay for the build-and-ship pipeline: the parent
            # order flow re-drives the session after payment.
            return session
        err(
            "ERR_INVALID_STATE",
            "Session in status %s cannot advance." % current,
        )
    if current not in WORKSHOP_ADVANCE_TARGET:
        err(
            "ERR_INVALID_STATE",
            "Session in status %s cannot advance." % current,
        )
    model = db.plush_models.get(session["plush_model_id"])
    # BATHED -> DRESSED releases the assignment; every other advance re-points
    # assigned_station_id to the station chosen for the next stage.
    target_station_type = NEXT_STAGE_STATION.get(current)

    if current == "SELECT":
        # Licensed rails (priorities 6 and 7) fire at the commitment step.
        if model and model["is_licensed"] and session["collection_drop_id"]:
            drop = db.collection_drops.get(session["collection_drop_id"])
            if drop is not None:
                check_drop_claim_guards(session, drop)

    # Capacity / scheduling (priority 8): select the next stage's station.
    station = None
    if target_station_type is not None:
        station = select_station(session["store_id"], target_station_type)
        if station is None:
            err(
                "ERR_STATION_AT_CAPACITY",
                "No %s station has spare capacity." % target_station_type,
            )

    # Funds / stock sufficiency (priority 10).
    if current == "SELECTED":
        fiber = find_consumable(session["store_id"], "STUFFING_FIBER")
        needed = model["required_stuffing_grams"] if model else 0
        if fiber is None or fiber["on_hand_qty"] < needed:
            err("ERR_INSUFFICIENT_STOCK", "Not enough stuffing fiber on hand.")
    elif current == "STUFFED":
        if model and model["sound_chip_compatible"]:
            chip = find_consumable(session["store_id"], "SOUND_CHIP")
            if chip is None or chip["on_hand_qty"] < 1:
                err("ERR_INSUFFICIENT_STOCK", "No sound chips on hand.")

    # ---- side effects ----
    if current == "SELECT":
        animal = new_row(
            customer_id=session["customer_id"],
            plush_model_id=session["plush_model_id"],
            origin_workshop_session_id=session["id"],
            birth_cert_name=None,
            birth_cert_birth_date=None,
            status="IN_PROGRESS",
        )
        db.animals[animal["id"]] = animal
        session["stuffed_animal_id"] = animal["id"]
        session["total_price_cents"] = model["base_price_cents"] if model else 0
        if model and model["is_licensed"] and session["collection_drop_id"]:
            drop = db.collection_drops.get(session["collection_drop_id"])
            if drop is not None:
                drop["units_claimed"] += 1
                touch(drop)
    elif current == "SELECTED":
        fiber = find_consumable(session["store_id"], "STUFFING_FIBER")
        grams = model["required_stuffing_grams"] if model else 0
        fiber["on_hand_qty"] -= grams
        touch(fiber)
        session["stuffing_grams_used"] = grams
    elif current == "STUFFED":
        if model and model["sound_chip_compatible"]:
            chip = find_consumable(session["store_id"], "SOUND_CHIP")
            chip["on_hand_qty"] -= 1
            touch(chip)
            session["sound_chip_used"] = True
            session["total_price_cents"] += SOUND_CHIP_PRICE_CENTS

    if current == "BATHED":
        session["assigned_station_id"] = None
    else:
        session["assigned_station_id"] = station["id"]
    session["status"] = WORKSHOP_ADVANCE_TARGET[current]
    touch(session)
    return session


def abandon_session(session, cascade_parents=True):
    """POST /workshops/{id}/abandon: compensating restoration per stage."""
    current = session["status"]
    if current in WORKSHOP_TERMINAL:
        err("ERR_INVALID_STATE", "Session in status %s cannot be abandoned." % current)
    model = db.plush_models.get(session["plush_model_id"])

    if current != "SELECT":
        # The shell was committed: release the licensed unit claim.
        if model and model["is_licensed"] and session["collection_drop_id"]:
            drop = db.collection_drops.get(session["collection_drop_id"])
            if drop is not None and drop["units_claimed"] > 0:
                drop["units_claimed"] -= 1
                touch(drop)
    if current in ("STUFFED", "SOUNDED", "BATHED", "DRESSED"):
        fiber = find_consumable(session["store_id"], "STUFFING_FIBER")
        if fiber is not None and session["stuffing_grams_used"]:
            fiber["on_hand_qty"] += session["stuffing_grams_used"]
            touch(fiber)
    if current in ("SOUNDED", "BATHED", "DRESSED") and session["sound_chip_used"]:
        chip = find_consumable(session["store_id"], "SOUND_CHIP")
        if chip is not None:
            chip["on_hand_qty"] += 1
            touch(chip)

    session["assigned_station_id"] = None
    session["status"] = "ABANDONED"
    touch(session)

    if cascade_parents:
        # PRD section 3.7: abandonment of a party-origin session marks the
        # linked guest NO_SHOW; section 3.4: build-ship-origin abandonment
        # cancels the linked order.
        if session["origin_type"] == "PARTY":
            guest = find_guest_by_session(session["id"])
            if guest is not None and guest["status"] == "CONFIRMED":
                guest["status"] = "NO_SHOW"
                touch(guest)
        elif session["origin_type"] == "BUILD_SHIP":
            order = db.build_ship_orders.get(session["build_ship_order_id"])
            if order is not None and order["status"] == "IN_ASSEMBLY":
                order["status"] = "CANCELLED"
                touch(order)
    return session


def find_guest_by_session(session_id):
    for guest in db.party_guests.values():
        if guest["workshop_session_id"] == session_id:
            return guest
    return None


def find_order_by_session(session_id):
    for order in db.build_ship_orders.values():
        if order["workshop_session_id"] == session_id:
            return order
    return None


# ---------------------------------------------------------------------------
# Party reservations (PRD sections 3.6-3.7)
# ---------------------------------------------------------------------------
def compute_deposit(package_tier, guest_count):
    """party_deposit_required, guest_count mode (quote time)."""
    if package_tier == "ULTIMATE":
        return max(guest_count * PER_GUEST_DEPOSIT_CENTS, ULTIMATE_DEPOSIT_FLOOR_CENTS)
    return FIXED_DEPOSIT_CENTS


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval overlap; touching endpoints do not overlap."""
    return a_start < b_end and b_start < a_end


def room_overlap_count(store_id, start, end, exclude_party_id=None):
    count = 0
    for block in db.appointment_blocks.values():
        if block["store_id"] != store_id or block["status"] != "ACTIVE":
            continue
        if exclude_party_id and block["party_reservation_id"] == exclude_party_id:
            continue
        if _overlaps(block["block_start"], block["block_end"], start, end):
            count += 1
    return count


def check_room_available(store, start, end, exclude_party_id=None):
    if room_overlap_count(store["id"], start, end, exclude_party_id) >= store["party_room_count"]:
        err(
            "ERR_STATION_AT_CAPACITY",
            "No party room is available for the requested block.",
        )


def select_host(store_id, start, end, exclude_party_id=None):
    """party_host_selector: PARTY_HOST staff at the store with no overlapping
    ACTIVE reserved block (touching endpoints allowed); fewest ACTIVE reserved
    blocks first; tie-break earliest created_at."""
    candidates = []
    for member in db.staff.values():
        if member["store_id"] != store_id or member["role_title"] != "PARTY_HOST":
            continue
        active_blocks = [
            block
            for block in db.appointment_blocks.values()
            if block["status"] == "ACTIVE"
            and block["reserved_host_id"] == member["id"]
            and not (exclude_party_id and block["party_reservation_id"] == exclude_party_id)
        ]
        if any(_overlaps(b["block_start"], b["block_end"], start, end) for b in active_blocks):
            continue
        candidates.append((len(active_blocks), member["created_at"], member["_seq"], member))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return candidates[0][3]


def party_guests_of(party_id):
    return [g for g in db.party_guests.values() if g["party_reservation_id"] == party_id]


def auto_confirm_parties():
    """DEPOSIT_PAID -> CONFIRMED once the clock reaches party_start - 24h;
    creates a party-origin workshop session for every CONFIRMED guest."""
    for party in sort_created(list(db.parties.values())):
        if party["status"] != "DEPOSIT_PAID":
            continue
        threshold = party["party_start"] - timedelta(hours=24)
        if now() < threshold:
            continue
        party["status"] = "CONFIRMED"
        touch(party)
        model_id = _default_party_model_id()
        for guest in sort_created(party_guests_of(party["id"])):
            if guest["status"] != "CONFIRMED":
                continue
            session = create_session(
                store_id=party["store_id"],
                customer_id=party["customer_id"],
                plush_model_id=model_id,
                origin_type="PARTY",
                party_reservation_id=party["id"],
            )
            guest["workshop_session_id"] = session["id"]
            touch(guest)


def _default_party_model_id():
    """Party guests build the house model: the earliest-registered plush model."""
    models = sort_created(list(db.plush_models.values()))
    return models[0]["id"] if models else None


def compute_final_amount_due(party):
    """party_final_amount_due: per-line rounding BEFORE summation, deposit
    credited, negative results clamped to zero (excess deposit forfeited)."""
    per_guest = PACKAGE_PRICES[party["package_tier"]]
    billable = [
        g for g in party_guests_of(party["id"]) if g["status"] in ("CONFIRMED", "ATTENDED")
    ]
    subtotal = 0
    for _guest in billable:
        line = per_guest + rhu_int(per_guest * SERVICE_CHARGE_PCT, 100)
        subtotal += line
    return max(0, subtotal - party["deposit_amount_cents"])


def compute_cancel_refund(party):
    """party_deposit_required, cancel-refund mode: zero inside the 72h lead
    window, otherwise per-guest deposit times min(booked, honored)."""
    lead_deadline = party["party_start"] - timedelta(hours=MIN_BOOKING_LEAD_HOURS)
    if now() >= lead_deadline:
        return 0
    honored = sum(1 for g in party_guests_of(party["id"]) if g["status"] != "NO_SHOW")
    return min(party["guest_count"], honored) * PER_GUEST_DEPOSIT_CENTS


def release_party_block(party):
    for block in db.appointment_blocks.values():
        if block["party_reservation_id"] == party["id"] and block["status"] == "ACTIVE":
            block["status"] = "RELEASED"
            touch(block)


def find_party_block(party_id):
    for block in db.appointment_blocks.values():
        if block["party_reservation_id"] == party_id:
            return block
    return None
