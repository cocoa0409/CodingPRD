"""Shared-space bookings and grooming risk screening (PRD §3.2)."""

from datetime import timedelta

import db
import domain
import shapes
import validate
from errors import ApiError
from services import core


def find_breed_rule(pet):
    for rule in db.rows("breed_rules"):
        if rule["species"] == pet["species"] \
                and rule["breed"].lower() == (pet["breed"] or "").lower():
            return rule
    return None


def assert_groomable(pet):
    rule = find_breed_rule(pet)
    if rule is not None and rule["allowed_for_grooming"] is False:
        raise ApiError("ERR_BREED_NOT_GROOMABLE")


def bay_conflict(bay_id, candidate_start, candidate_end, exclude_booking_id=None):
    """Half-open interval guard: adjacency is allowed, one second of overlap is not."""
    for held in db.rows("bookings"):
        if held["bay_id"] != bay_id or held["status"] not in domain.LIVE_BOOKING_STATES:
            continue
        if exclude_booking_id is not None and held["id"] == exclude_booking_id:
            continue
        if candidate_start < held["ends_at"] and held["starts_at"] < candidate_end:
            raise ApiError("ERR_BAY_SLOT_CONFLICT")


def pet_double_booked(pet_id, bay_id, candidate_start, candidate_end,
                      exclude_booking_id=None):
    """Cross-bay guard: the candidate window is buffered 15 minutes at each end."""
    buffer = timedelta(minutes=domain.PET_BUFFER_MINUTES)
    cand_start = candidate_start - buffer
    cand_end = candidate_end + buffer
    for held in db.rows("bookings"):
        if held["pet_id"] != pet_id or held["bay_id"] == bay_id:
            continue
        if held["status"] not in domain.LIVE_BOOKING_STATES:
            continue
        if exclude_booking_id is not None and held["id"] == exclude_booking_id:
            continue
        if cand_start < held["ends_at"] and held["starts_at"] < cand_end:
            raise ApiError("ERR_PET_DOUBLE_BOOKED")


# ---------------------------------------------------------------------------
# screening calculation (§3.2)
# ---------------------------------------------------------------------------

def screen_terms(pet, condition_points):
    risk_score = pet["risk_score"]
    incidents = core.pet_incidents(pet["id"])
    rewound = any(i["created_at"] > db.clock["current"] for i in incidents)
    if rewound and db.clock["current"] < db.clock["highest"]:
        # withheld_history_variant: a clock rewound behind the incident that
        # produced part of risk_score substitutes the pet term.
        pet_points = max(20, risk_score - 10)
    else:
        pet_points = risk_score
    rule = find_breed_rule(pet)
    breed_points = rule["risk_points"] if rule else 0
    score = domain.screening_score(pet_points, breed_points,
                                   pet["weight_kg"], condition_points)
    tier = rule["handling_tier"] if rule else None
    return score, domain.handling_level(score, tier)


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

def create(body, store_id):
    store = core.require_store(store_id)
    body = validate.shape(
        body,
        required=["bay_id", "pet_id", "service_type", "starts_at", "ends_at",
                  "expected_pet_version"],
        optional=[])
    bay = core.require_bay(body["bay_id"])
    pet = core.require_pet(body["pet_id"])
    if bay["store_id"] != store_id:
        raise ApiError("ERR_SERVICE_BAY_NOT_FOUND",
                       "The bay does not belong to the store named in the path.")
    starts_at = db.parse_dt(body["starts_at"])
    ends_at = db.parse_dt(body["ends_at"])
    if ends_at <= starts_at:
        raise ApiError("ERR_BOOKING_END_NOT_AFTER_START")
    validate.check_backdating(store, bay, pet)

    # priority 4 — hospital partition gate
    if store["hospital_posture"] == "FROZEN":
        raise ApiError("ERR_STORE_HOSPITAL_FROZEN")
    # priority 9 / 10 — the two temporal occupancy guards
    bay_conflict(bay["id"], starts_at, ends_at)
    pet_double_booked(pet["id"], bay["id"], starts_at, ends_at)
    # priority 15
    if body["service_type"] == "GROOMING":
        assert_groomable(pet)
    # priority 22 / 23
    if "expected_pet_version" not in body or body["expected_pet_version"] is None:
        raise ApiError("ERR_MISSING_EXPECTED_VERSION")
    if int(body["expected_pet_version"]) != pet["version"]:
        raise ApiError("ERR_STALE_VERSION")

    row = db.new_row()
    row.update({
        "store_id": store_id, "bay_id": bay["id"], "pet_id": pet["id"],
        "service_type": body["service_type"], "starts_at": starts_at,
        "ends_at": ends_at, "screening_score": 0, "pet_version": pet["version"],
        "handling_level": "STANDARD", "screening_valid_until": None,
        "re_screen_required": False, "status": "REQUESTED",
    })
    db.add("bookings", row)
    return row


def screen(body, store_id, booking_id):
    store = core.require_store(store_id)
    booking = core.require_booking(booking_id)
    if booking["store_id"] != store_id:
        raise ApiError("ERR_BOOKING_NOT_FOUND")
    pet = core.require_pet(booking["pet_id"])
    validate.check_backdating(store, booking, pet)
    body = validate.shape(
        body,
        required=["health_condition_points", "aggression_acknowledged",
                  "expected_pet_version"],
        optional=[])
    # priority 5 — state before business rules
    if booking["service_type"] != "GROOMING":
        raise ApiError("ERR_BOOKING_NOT_GROOMING")
    if booking["status"] != "REQUESTED":
        raise ApiError("ERR_BOOKING_NOT_SCREENABLE")
    if pet["status"] != "ACTIVE":
        raise ApiError("ERR_PET_ARCHIVED")
    if "expected_pet_version" not in body or body["expected_pet_version"] is None:
        raise ApiError("ERR_MISSING_EXPECTED_VERSION")
    if int(body["expected_pet_version"]) != pet["version"]:
        raise ApiError("ERR_STALE_VERSION")

    score, level = screen_terms(pet, int(body["health_condition_points"]))
    recorded_at = db.now()
    valid_until = recorded_at + timedelta(days=domain.SCREENING_VALIDITY_DAYS)
    screening = db.new_row(versioned=False)
    screening.update({
        "booking_id": booking["id"], "risk_total": score,
        "health_condition_points": int(body["health_condition_points"]),
        "handling_level": level,
        "aggression_acknowledged": bool(body["aggression_acknowledged"]),
        "recorded_at": recorded_at, "valid_until": valid_until,
    })
    db.add("screenings", screening)

    booking["screening_score"] = score
    booking["handling_level"] = level
    booking["screening_valid_until"] = valid_until
    booking["re_screen_required"] = False
    booking["status"] = "SCREENED"
    db.touch(booking)
    pet["rabies_vaccination_expires_at"] = shapes.live_rabies_expiry(pet)
    db.touch(pet)
    booking["pet_version"] = pet["version"]
    core.schedule("SCREENING_LAPSE", {"booking_id": booking["id"]})
    return booking


def confirm_bay(body, store_id, booking_id):
    store = core.require_store(store_id)
    booking = core.require_booking(booking_id)
    if booking["store_id"] != store_id:
        raise ApiError("ERR_BOOKING_NOT_FOUND")
    bay = core.require_bay(booking["bay_id"])
    pet = core.require_pet(booking["pet_id"])
    member = core.require_member(pet["member_id"])
    validate.check_backdating(store, booking, bay, pet, member)
    body = validate.shape(body,
                          required=["expected_booking_version", "expected_pet_version"],
                          optional=["starts_at", "ends_at"])

    widening = booking["status"] == "BAY_CONFIRMED"
    if not widening:
        # PRD §3.2: "Only grooming carries a screening obligation; the other three
        # service types proceed to confirmation directly." The machine declares
        # REQUESTED -> BAY_CONFIRMED for those types and SCREENED -> BAY_CONFIRMED
        # for a screened grooming booking, so each source state admits only its own
        # family and the other is refused with ERR_BOOKING_NOT_SCREENED.
        if booking["service_type"] == "GROOMING":
            if booking["status"] != "SCREENED":
                raise ApiError("ERR_BOOKING_NOT_SCREENED")
        elif booking["status"] != "REQUESTED":
            raise ApiError("ERR_BOOKING_NOT_SCREENED")

    starts_at, ends_at = booking["starts_at"], booking["ends_at"]
    supplied_start = body.get("starts_at")
    supplied_end = body.get("ends_at")
    if supplied_start is not None or supplied_end is not None:
        if supplied_start is None or supplied_end is None:
            raise ApiError("ERR_BOOKING_END_NOT_AFTER_START")
        starts_at = db.parse_dt(supplied_start)
        ends_at = db.parse_dt(supplied_end)
        if ends_at <= starts_at:
            raise ApiError("ERR_BOOKING_END_NOT_AFTER_START")
        if widening:
            # a repeat confirm must strictly contain the window already held
            contained = (starts_at <= booking["starts_at"] and ends_at >= booking["ends_at"]
                         and (starts_at < booking["starts_at"] or ends_at > booking["ends_at"]))
            if not contained:
                raise ApiError("ERR_BAY_SLOT_CONFLICT")

    if not widening:
        # priority 8 — the aggression advisory
        if booking["service_type"] == "GROOMING" \
                and booking["screening_score"] >= domain.HIGH_RISK_THRESHOLD:
            acknowledged = any(s["booking_id"] == booking["id"]
                               and s["aggression_acknowledged"]
                               for s in db.rows("screenings"))
            if not acknowledged:
                raise ApiError("ERR_HIGH_RISK_NOT_ACKNOWLEDGED")
        # priority 15
        if booking["service_type"] == "GROOMING":
            assert_groomable(pet)

    # priority 9 / 10
    bay_conflict(bay["id"], starts_at, ends_at, booking["id"])
    pet_double_booked(pet["id"], bay["id"], starts_at, ends_at, booking["id"])
    if not widening:
        # priority 5
        if bay["status"] != "ACTIVE":
            raise ApiError("ERR_BAY_NOT_ACTIVE")
        if store["hospital_posture"] == "FROZEN":
            raise ApiError("ERR_STORE_HOSPITAL_FROZEN")
        if member["status"] != "ACTIVE":
            raise ApiError("ERR_MEMBER_SUSPENDED")
    # priority 22 / 23
    if body.get("expected_booking_version") is None:
        raise ApiError("ERR_MISSING_EXPECTED_VERSION")
    if body.get("expected_pet_version") is None:
        raise ApiError("ERR_MISSING_EXPECTED_VERSION")
    if int(body["expected_booking_version"]) != booking["version"]:
        raise ApiError("ERR_STALE_VERSION")
    if int(body["expected_pet_version"]) != pet["version"]:
        raise ApiError("ERR_STALE_VERSION")

    booking["starts_at"] = starts_at
    booking["ends_at"] = ends_at
    booking["pet_version"] = pet["version"]
    booking["status"] = "BAY_CONFIRMED"
    db.touch(booking)
    if booking["service_type"] == "VETERINARY":
        core.refresh_store(store)
    return booking


def start_service(body, store_id, booking_id):
    store = core.require_store(store_id)
    booking = core.require_booking(booking_id)
    if booking["store_id"] != store_id:
        raise ApiError("ERR_BOOKING_NOT_FOUND")
    body = validate.shape(body, required=["expected_booking_version"], optional=[])
    validate.check_backdating(store, booking)
    if booking["status"] != "BAY_CONFIRMED":
        raise ApiError("ERR_BOOKING_NOT_CONFIRMED")
    if store["hospital_posture"] == "FROZEN":
        raise ApiError("ERR_STORE_HOSPITAL_FROZEN")
    validate.require_expected(body, booking["version"], "expected_booking_version")
    booking["status"] = "IN_SERVICE"
    db.touch(booking)
    return booking


def complete_service(body, store_id, booking_id):
    store = core.require_store(store_id)
    booking = core.require_booking(booking_id)
    if booking["store_id"] != store_id:
        raise ApiError("ERR_BOOKING_NOT_FOUND")
    body = validate.shape(body, required=["expected_booking_version"], optional=[])
    validate.check_backdating(store, booking)
    if booking["status"] != "IN_SERVICE":
        raise ApiError("ERR_BOOKING_NOT_IN_SERVICE")
    validate.require_expected(body, booking["version"], "expected_booking_version")
    booking["status"] = "COMPLETED"
    db.touch(booking)
    if booking["service_type"] == "VETERINARY":
        for enc in db.rows("encounters"):
            if enc["booking_id"] == booking["id"] and enc["status"] in ("SCHEDULED", "CHECKED_IN"):
                enc["status"] = "CANCELLED"
                db.touch(enc)
        core.refresh_store(store)
    return booking


def mark_no_show(body, store_id, booking_id):
    store = core.require_store(store_id)
    booking = core.require_booking(booking_id)
    if booking["store_id"] != store_id:
        raise ApiError("ERR_BOOKING_NOT_FOUND")
    body = validate.shape(body, required=["expected_booking_version"], optional=[])
    validate.check_backdating(store, booking)
    if booking["status"] not in ("REQUESTED", "SCREENED", "BAY_CONFIRMED"):
        raise ApiError("ERR_ILLEGAL_STATE_TRANSITION")
    grace = timedelta(minutes=domain.NO_SHOW_GRACE_MINUTES)
    if not db.now() > (booking["starts_at"] + grace):
        raise ApiError("ERR_ILLEGAL_STATE_TRANSITION",
                       "The no-show grace period has not yet elapsed.")
    validate.require_expected(body, booking["version"], "expected_booking_version")
    booking["status"] = "NO_SHOW"
    db.touch(booking)
    return booking


def cancel(body, store_id, booking_id):
    store = core.require_store(store_id)
    booking = core.require_booking(booking_id)
    if booking["store_id"] != store_id:
        raise ApiError("ERR_BOOKING_NOT_FOUND")
    body = validate.shape(body, required=["expected_booking_version"], optional=[])
    validate.check_backdating(store, booking)
    if booking["status"] != "BAY_CONFIRMED":
        raise ApiError("ERR_BOOKING_NOT_CANCELLABLE")
    validate.require_expected(body, booking["version"], "expected_booking_version")
    booking["status"] = "CANCELLED"
    db.touch(booking)
    pet = db.get("pets", booking["pet_id"])
    if pet is not None and core.booking_incidents(booking["id"]):
        pet["status"] = "ARCHIVED"
        db.touch(pet)
    # a cancellation also self-synthesizes the screening it regressed past
    _self_synthesize_screening(booking)
    return booking


def _self_synthesize_screening(booking):
    """The cancellation of a grooming booking re-runs the screening it voided."""
    if booking["service_type"] != "GROOMING":
        return
    if any(s["booking_id"] == booking["id"] for s in db.rows("screenings")):
        return
    pet = db.get("pets", booking["pet_id"])
    if pet is None:
        return
    score, level = screen_terms(pet, 0)
    recorded_at = db.now()
    row = db.new_row(versioned=False)
    row.update({
        "booking_id": booking["id"], "risk_total": score,
        "health_condition_points": 0, "handling_level": level,
        "aggression_acknowledged": False, "recorded_at": recorded_at,
        "valid_until": recorded_at + timedelta(days=domain.SCREENING_VALIDITY_DAYS),
        "synthesized": True,
    })
    db.add("screenings", row)


def read(booking_id):
    return core.require_booking(booking_id)