"""Composite setup helpers.

Every fixture builds its preconditions from scratch against a freshly restarted
server (the harness restarts the API before every test), using only
PRD-declared endpoints. Setup calls use get_success_data() so failures surface
as clear 'Setup failed' errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS as D
from .factories import (
    create_care_space_booking_payload,
    create_care_space_payload,
    create_contribution_request_payload,
    create_family_payload,
    create_hospital_payload,
    create_house_payload,
    create_in_kind_donation_payload,
    create_meal_shift_payload,
    create_referral_payload,
    create_room_payload,
    create_stay_request_payload,
    create_volunteer_group_payload,
    record_screening_payload,
    register_guest_payload,
)
from .test_users import (
    TEST_USERS,
    make_family_contact_headers,
    make_hospital_referrer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
HM = TEST_USERS["house_manager_headers"]
VC = TEST_USERS["volunteer_coordinator_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: basic hierarchy (hospital, house, rooms)
# ---------------------------------------------------------------------------

def create_hospital(**overrides):
    resp = api_client.create_hospital(create_hospital_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_house(hospital_id, **overrides):
    resp = api_client.create_house(create_house_payload(hospital_id, **overrides), ADMIN)
    return get_success_data(resp)


def create_room(house_id, **overrides):
    resp = api_client.create_room(house_id, create_room_payload(**overrides), HM)
    return get_success_data(resp)


def setup_hospital_house(num_rooms=1, room_overrides=None):
    """Hospital + house + N rooms. Returns (hospital, house, [rooms])."""
    hospital = create_hospital()
    house = create_house(hospital["id"])
    rooms = []
    for i in range(num_rooms):
        ov = dict(room_overrides or {})
        ov.setdefault("room_number", str(101 + i))
        rooms.append(create_room(house["id"], **ov))
    return hospital, house, rooms


# ---------------------------------------------------------------------------
# Tier 2: family + referral
# ---------------------------------------------------------------------------

def create_family(**overrides):
    resp = api_client.create_family(create_family_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_referral(family_id, hospital_id, creator_headers=None, **overrides):
    """Issue a referral. Default creator is the entity-backed HospitalReferrer
    for that hospital."""
    headers = creator_headers or make_hospital_referrer_headers(hospital_id)
    resp = api_client.create_referral(
        create_referral_payload(family_id, hospital_id, **overrides), headers
    )
    return get_success_data(resp)


def verify_referral(referral_id, decision="APPROVE", headers=None, **extra):
    payload = {"decision": decision}
    payload.update(extra)
    resp = api_client.verify_referral(referral_id, payload, headers or HM)
    return get_success_data(resp)


def create_verified_referral(family_id, hospital_id, **overrides):
    referral = create_referral(family_id, hospital_id, **overrides)
    return verify_referral(referral["id"])


def setup_family_with_verified_referral(hospital_id, family_overrides=None, referral_overrides=None):
    """Family + VERIFIED referral at the hospital. Returns (family, referral)."""
    family = create_family(**(family_overrides or {}))
    referral = create_verified_referral(family["id"], hospital_id, **(referral_overrides or {}))
    return family, referral


# ---------------------------------------------------------------------------
# Tier 3: stay request lifecycle
# ---------------------------------------------------------------------------

def create_stay_request(family, house_id, referral_id, refresh_family=True, **overrides):
    """Create a stay request for a family. Reads the family's current version
    unless an explicit expected_family_version override is supplied."""
    fam = family
    if refresh_family or "expected_family_version" not in overrides:
        fam = get_success_data(api_client.get_family(family["id"], ADMIN))
    payload = create_stay_request_payload(
        fam["id"], house_id, referral_id, fam["version"], **overrides
    )
    resp = api_client.create_stay_request(payload, make_family_contact_headers(fam["id"]))
    return get_success_data(resp)


def get_stay_request(request_id):
    return get_success_data(api_client.get_stay_request(request_id, HM))


def offer_request(request_id, room_id, headers=None):
    resp = api_client.offer_stay_request(request_id, {"room_id": room_id}, headers or HM)
    return get_success_data(resp)


def respond_request(request_id, family_id, decision="ACCEPT"):
    current = get_stay_request(request_id)
    resp = api_client.respond_stay_request(
        request_id,
        {"decision": decision, "expected_stay_request_version": current["version"]},
        make_family_contact_headers(family_id),
    )
    return get_success_data(resp)


def check_in_request(request_id):
    resp = api_client.check_in_stay_request(request_id, HM)
    return get_success_data(resp)


def setup_waitlisted_request(hospital=None, house=None, family_overrides=None,
                             referral_overrides=None, request_overrides=None):
    """House + family + verified referral + WAITLISTED request.
    Returns dict with hospital, house, rooms, family, referral, request."""
    if hospital is None or house is None:
        hospital, house, rooms = setup_hospital_house(num_rooms=1)
    else:
        rooms = None
    family, referral = setup_family_with_verified_referral(
        hospital["id"], family_overrides, referral_overrides
    )
    request = create_stay_request(family, house["id"], referral["id"], **(request_overrides or {}))
    return {
        "hospital": hospital,
        "house": house,
        "rooms": rooms,
        "family": family,
        "referral": referral,
        "request": request,
    }


def setup_offered_request(hospital=None, house=None, room=None, **kwargs):
    """WAITLISTED request then OFFERED against `room`. Returns setup dict."""
    ctx = setup_waitlisted_request(hospital=hospital, house=house, **kwargs)
    room = room or ctx["rooms"][0]
    request = offer_request(ctx["request"]["id"], room["id"])
    ctx["request"] = request
    ctx["room"] = room
    return ctx


def setup_active_stay(hospital=None, house=None, room=None,
                      check_in_clock=None, **kwargs):
    """Full lifecycle: WAITLISTED -> OFFERED -> ACCEPTED -> FULFILLED with an
    ACTIVE stay. Returns setup dict with 'stay' and 'room'."""
    ctx = setup_offered_request(hospital=hospital, house=house, room=room, **kwargs)
    if check_in_clock:
        set_clock(check_in_clock)
    respond_request(ctx["request"]["id"], ctx["family"]["id"], "ACCEPT")
    stay = check_in_request(ctx["request"]["id"])
    ctx["stay"] = stay
    ctx["request"] = get_stay_request(ctx["request"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: stay-adjacent helpers
# ---------------------------------------------------------------------------

def record_pass_screening(stay_id, **overrides):
    resp = api_client.record_screening(stay_id, record_screening_payload(**overrides), HM)
    return get_success_data(resp)


def register_guest(stay_id, family_id=None, headers=None, **overrides):
    h = headers or (make_family_contact_headers(family_id) if family_id else HM)
    resp = api_client.register_guest(stay_id, register_guest_payload(**overrides), h)
    return get_success_data(resp)


def create_contribution(stay_id, **overrides):
    resp = api_client.create_contribution_request(
        stay_id, create_contribution_request_payload(**overrides), HM
    )
    return get_success_data(resp)


def get_contribution(cr_id):
    return get_success_data(api_client.get_contribution_request(cr_id, HM))


def get_stay(stay_id):
    return get_success_data(api_client.get_stay(stay_id, HM))


def get_house(house_id):
    return get_success_data(api_client.get_house(house_id, HM))


def get_room(room_id):
    return get_success_data(api_client.get_room(room_id, HM))


def get_referral(referral_id):
    return get_success_data(api_client.get_referral(referral_id, HM))


def get_family(family_id):
    return get_success_data(api_client.get_family(family_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 5: volunteer meal program / care spaces / donations
# ---------------------------------------------------------------------------

def create_volunteer_group(**overrides):
    resp = api_client.create_volunteer_group(create_volunteer_group_payload(**overrides), VC)
    return get_success_data(resp)


def create_certified_group(certified_until="2026-09-10", **overrides):
    group = create_volunteer_group(**overrides)
    resp = api_client.certify_volunteer_group(group["id"], {"certified_until": certified_until}, ADMIN)
    return get_success_data(resp)


def create_meal_shift(house_id, **overrides):
    resp = api_client.create_meal_shift(house_id, create_meal_shift_payload(**overrides), HM)
    return get_success_data(resp)


def create_care_space(hospital_id, **overrides):
    resp = api_client.create_care_space(hospital_id, create_care_space_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_booking(care_space_id, family_id, headers=None, **overrides):
    h = headers or make_family_contact_headers(family_id)
    resp = api_client.create_care_space_booking(
        care_space_id, create_care_space_booking_payload(family_id, **overrides), h
    )
    return get_success_data(resp)


def create_donation(house_id, **overrides):
    resp = api_client.create_in_kind_donation(
        house_id, create_in_kind_donation_payload(**overrides), HM
    )
    return get_success_data(resp)
