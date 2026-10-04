"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the test runner restarts the server before every test, so the
database starts empty). Helpers use get_success_data() so setup failures
surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import REQUIRED_PHOTO_TYPES, TEST_DEFAULTS
from .factories import (
    create_auction_result_payload,
    create_claim_payload,
    create_club_event_payload,
    create_club_membership_payload,
    create_driver_payload,
    create_guide_entry_payload,
    create_member_payload,
    create_photo_payload,
    create_policy_payload,
    create_repair_shop_payload,
    create_valuation_guide_payload,
    create_valuation_payload,
    create_vehicle_payload,
)
from .test_users import (
    TEST_USERS,
    make_adjuster_headers,
    make_appraiser_headers,
    make_member_headers,
    make_underwriter_headers,
)

ADMIN = TEST_USERS["admin_headers"]
UW = TEST_USERS["underwriter_headers"]
COORD = TEST_USERS["coordinator_headers"]


def _ok(resp, what):
    data = get_success_data(resp)
    if not isinstance(data, dict) or "id" not in data:
        raise AssertionError(f"Setup failed ({what}): {resp.status_code} {resp.text}")
    return data


# ---------------------------------------------------------------------------
# Tier 1: single entities
# ---------------------------------------------------------------------------

def create_member(**overrides):
    """Create a member. Returns (member_dict, member_headers)."""
    member = _ok(
        api_client.create_member(create_member_payload(**overrides), ADMIN),
        "create_member",
    )
    return member, make_member_headers(member["id"])


def create_vehicle(member, **overrides):
    """Register a vehicle owned by the given member."""
    _, m_headers = member if isinstance(member, tuple) else (member, make_member_headers(member["id"]))
    vehicle = _ok(
        api_client.create_vehicle(create_vehicle_payload(**overrides), m_headers),
        "create_vehicle",
    )
    return vehicle


def evaluate_vehicle(vehicle_id):
    resp = api_client.evaluate_eligibility(vehicle_id, UW)
    data = get_success_data(resp)
    if "id" not in data:
        raise AssertionError(f"Setup failed (evaluate_vehicle): {resp.status_code} {resp.text}")
    return data


def get_vehicle(vehicle_id):
    resp = api_client.get_vehicle(vehicle_id, UW)
    data = get_success_data(resp)
    if "id" not in data:
        raise AssertionError(f"Setup failed (get_vehicle): {resp.status_code} {resp.text}")
    return data


def get_policy(policy_id):
    resp = api_client.get_policy(policy_id, UW)
    data = get_success_data(resp)
    if "id" not in data:
        raise AssertionError(f"Setup failed (get_policy): {resp.status_code} {resp.text}")
    return data


# ---------------------------------------------------------------------------
# Tier 2: photographic dossier
# ---------------------------------------------------------------------------

def submit_all_photos(vehicle_id, member_headers):
    """Submit all eight required photo types. Returns {photo_type: photo}."""
    photos = {}
    for ptype in REQUIRED_PHOTO_TYPES:
        photo = _ok(
            api_client.submit_photo(
                vehicle_id,
                create_photo_payload(photo_type=ptype, image_ref=f"img://{ptype.lower()}"),
                member_headers,
            ),
            f"submit_photo({ptype})",
        )
        photos[ptype] = photo
    return photos


def accept_photos(vehicle_id, photos, only_types=None):
    """Accept the given photos (all of them, or only the named types)."""
    for ptype, photo in photos.items():
        if only_types is not None and ptype not in only_types:
            continue
        resp = api_client.review_photo(vehicle_id, photo["id"], {"decision": "ACCEPT"}, UW)
        data = get_success_data(resp)
        if data.get("status") != "ACCEPTED":
            raise AssertionError(
                f"Setup failed (accept_photo {ptype}): {resp.status_code} {resp.text}"
            )


def setup_documented_vehicle(member, **vehicle_overrides):
    """Member-owned vehicle with all 8 photo types ACCEPTED (documentation COMPLETE).

    Returns (vehicle, member_headers)."""
    _, m_headers = member, make_member_headers(member["id"])
    vehicle = create_vehicle(member, **vehicle_overrides)
    photos = submit_all_photos(vehicle["id"], m_headers)
    accept_photos(vehicle["id"], photos)
    vehicle = get_vehicle(vehicle["id"])
    return vehicle, m_headers


# ---------------------------------------------------------------------------
# Tier 2: guides and valuations
# ---------------------------------------------------------------------------

def create_published_guide(base_value_cents=TEST_DEFAULTS["GUIDE_BASE_VALUE_CENTS"],
                           vehicle_class="CLASSIC",
                           make=TEST_DEFAULTS["VEHICLE_MAKE"],
                           year_min=TEST_DEFAULTS["GUIDE_YEAR_MIN"],
                           year_max=TEST_DEFAULTS["GUIDE_YEAR_MAX"],
                           edition=None,
                           effective_date=None):
    """Create a guide with one entry and publish it. Returns the guide."""
    payload = create_valuation_guide_payload()
    if edition is not None:
        payload["edition"] = edition
    if effective_date is not None:
        payload["effective_date"] = effective_date
    guide = _ok(api_client.create_valuation_guide(payload, ADMIN), "create_valuation_guide")
    _ok(
        api_client.add_guide_entry(
            guide["id"],
            create_guide_entry_payload(
                vehicle_class=vehicle_class,
                make=make,
                year_min=year_min,
                year_max=year_max,
                base_value_cents=base_value_cents,
            ),
            ADMIN,
        ),
        "add_guide_entry",
    )
    resp = api_client.publish_guide(guide["id"], ADMIN)
    data = get_success_data(resp)
    if data.get("status") != "PUBLISHED":
        raise AssertionError(f"Setup failed (publish_guide): {resp.status_code} {resp.text}")
    return data


def create_guide_tool_valuation(vehicle_id, proposed_agreed_value_cents, uw_headers=UW):
    """Create a GUIDE_TOOL valuation with a fresh OCC vehicle version. Returns it."""
    vehicle = get_vehicle(vehicle_id)
    payload = create_valuation_payload(
        method="GUIDE_TOOL",
        proposed_agreed_value_cents=proposed_agreed_value_cents,
        expected_vehicle_version=vehicle["version"],
    )
    return _ok(
        api_client.create_valuation(vehicle_id, payload, uw_headers),
        "create_valuation(GUIDE_TOOL)",
    )


def propose_and_approve(valuation_id, uw_headers=UW, **approve_payload):
    """DRAFT -> PROPOSED -> APPROVED. Returns the approved valuation."""
    resp = api_client.propose_valuation(valuation_id, uw_headers)
    data = get_success_data(resp)
    if data.get("status") != "PROPOSED":
        raise AssertionError(f"Setup failed (propose): {resp.status_code} {resp.text}")
    resp = api_client.approve_valuation(valuation_id, approve_payload or {}, uw_headers)
    data = get_success_data(resp)
    if data.get("status") != "APPROVED":
        raise AssertionError(f"Setup failed (approve): {resp.status_code} {resp.text}")
    return data


def setup_approved_guide_valuation(member, base_value_cents=TEST_DEFAULTS["GUIDE_BASE_VALUE_CENTS"],
                                   proposed=None, condition_grade="GOOD", document=True,
                                   **vehicle_overrides):
    """Member + vehicle (optionally documented) + published guide + APPROVED
    GUIDE_TOOL valuation. Returns dict with member, member_headers, vehicle,
    guide, valuation."""
    mult = {"EXCELLENT": 1.25, "GOOD": 1.00, "FAIR": 0.75, "PROJECT": 0.50}[condition_grade]
    if proposed is None:
        proposed = round(base_value_cents * mult)
    member, m_headers = member if isinstance(member, tuple) else (member, make_member_headers(member["id"]))
    if document:
        vehicle, _ = setup_documented_vehicle(member, condition_grade=condition_grade,
                                              **vehicle_overrides)
    else:
        vehicle = create_vehicle(member, condition_grade=condition_grade, **vehicle_overrides)
    evaluate_vehicle(vehicle["id"])
    guide = create_published_guide(base_value_cents=base_value_cents,
                                   vehicle_class=vehicle.get("vehicle_class", "CLASSIC"),
                                   make=vehicle["make"],
                                   year_min=min(TEST_DEFAULTS["GUIDE_YEAR_MIN"], vehicle["year"]),
                                   year_max=max(TEST_DEFAULTS["GUIDE_YEAR_MAX"], vehicle["year"]))
    valuation = create_guide_tool_valuation(vehicle["id"], proposed)
    valuation = propose_and_approve(valuation["id"])
    return {
        "member": member,
        "member_headers": m_headers,
        "vehicle": get_vehicle(vehicle["id"]),
        "guide": guide,
        "valuation": valuation,
        "agreed_value_cents": proposed,
    }


# ---------------------------------------------------------------------------
# Tier 3: policies
# ---------------------------------------------------------------------------

def create_policy_for(member, vehicle, valuation, **overrides):
    payload = create_policy_payload(
        member_id=member["id"], vehicle_id=vehicle["id"], valuation_id=valuation["id"],
        **overrides,
    )
    return _ok(api_client.create_policy(payload, UW), "create_policy")


def add_listed_driver(policy_id, member_headers, **overrides):
    return _ok(
        api_client.add_driver(policy_id, create_driver_payload(**overrides), member_headers),
        "add_driver",
    )


def setup_active_policy(base_value_cents=TEST_DEFAULTS["GUIDE_BASE_VALUE_CENTS"],
                        proposed=None, usage_tier="REGULAR",
                        annual_mileage_allowance=None,
                        condition_grade="GOOD", member_overrides=None,
                        **vehicle_overrides):
    """Full stack: member + documented eligible vehicle + published guide +
    APPROVED GUIDE_TOOL valuation + QUOTED policy + listed driver + ACTIVE.

    Returns dict with member, member_headers, vehicle, guide, valuation,
    policy, driver."""
    member, m_headers = create_member(**(member_overrides or {}))
    ctx = setup_approved_guide_valuation(
        (member, m_headers), base_value_cents=base_value_cents, proposed=proposed,
        condition_grade=condition_grade, **vehicle_overrides,
    )
    policy_overrides = {"usage_tier": usage_tier}
    if annual_mileage_allowance is not None:
        policy_overrides["annual_mileage_allowance"] = annual_mileage_allowance
    policy = create_policy_for(member, ctx["vehicle"], ctx["valuation"], **policy_overrides)
    driver = add_listed_driver(policy["id"], m_headers)
    resp = api_client.activate_policy(policy["id"], UW)
    data = get_success_data(resp)
    if data.get("status") != "ACTIVE":
        raise AssertionError(f"Setup failed (activate_policy): {resp.status_code} {resp.text}")
    return {
        "member": member,
        "member_headers": m_headers,
        "vehicle": ctx["vehicle"],
        "guide": ctx["guide"],
        "valuation": ctx["valuation"],
        "policy": data,
        "driver": driver,
    }


# ---------------------------------------------------------------------------
# Tier 3: claims
# ---------------------------------------------------------------------------

def create_certified_shop(**overrides):
    shop = _ok(
        api_client.create_repair_shop(create_repair_shop_payload(**overrides), ADMIN),
        "create_repair_shop",
    )
    resp = api_client.certify_repair_shop(shop["id"], ADMIN)
    data = get_success_data(resp)
    if data.get("status") != "CERTIFIED":
        raise AssertionError(f"Setup failed (certify shop): {resp.status_code} {resp.text}")
    return data


def setup_claim_under_investigation(estimate_cents=None, adjuster_id="adj-1",
                                    loss_type="COLLISION", **policy_kwargs):
    """Active policy + certified shop + claim in UNDER_INVESTIGATION
    (optionally with an estimate recorded). Returns the active-policy dict
    extended with shop and claim."""
    ctx = setup_active_policy(**policy_kwargs)
    shop = create_certified_shop()
    claim = _ok(
        api_client.open_claim(
            ctx["policy"]["id"], create_claim_payload(loss_type=loss_type), ctx["member_headers"]
        ),
        "open_claim",
    )
    adj_headers = make_adjuster_headers(adjuster_id)
    resp = api_client.assign_shop(claim["id"], {"repair_shop_id": shop["id"]}, adj_headers)
    data = get_success_data(resp)
    if data.get("status") != "UNDER_INVESTIGATION":
        raise AssertionError(f"Setup failed (assign_shop): {resp.status_code} {resp.text}")
    claim = data
    if estimate_cents is not None:
        claim = _ok(
            api_client.submit_estimate(claim["id"], {"estimate_cents": estimate_cents}, adj_headers),
            "submit_estimate",
        )
    ctx["shop"] = shop
    ctx["claim"] = claim
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: mileage ledger helpers
# ---------------------------------------------------------------------------

def record_usage(ctx, reported_miles, event_date, event_kind="ORDINARY"):
    """Record a usage event with a fresh OCC policy version. Returns the event."""
    policy = get_policy(ctx["policy"]["id"])
    payload = {
        "reported_miles": reported_miles,
        "event_date": event_date,
        "event_kind": event_kind,
        "expected_policy_version": policy["version"],
    }
    return api_client.record_usage_event(policy["id"], payload, ctx["member_headers"])


def record_usage_ok(ctx, reported_miles, event_date, event_kind="ORDINARY"):
    resp = record_usage(ctx, reported_miles, event_date, event_kind)
    return _ok(resp, "record_usage_event")


# ---------------------------------------------------------------------------
# Tier 2: club helpers
# ---------------------------------------------------------------------------

def create_club_membership_for(member, tier="BASIC"):
    return _ok(
        api_client.create_club_membership(
            create_club_membership_payload(member_id=member["id"], tier=tier), ADMIN
        ),
        "create_club_membership",
    )


def create_event(**overrides):
    return _ok(
        api_client.create_club_event(create_club_event_payload(**overrides), COORD),
        "create_club_event",
    )


def register_member(event_id, member):
    _, m_headers = member, make_member_headers(member["id"])
    return api_client.register_for_event(event_id, {"member_id": member["id"]}, m_headers)


# ---------------------------------------------------------------------------
# Auction comps
# ---------------------------------------------------------------------------

def post_auction_comp(sale_price_cents, sale_date, **overrides):
    return _ok(
        api_client.create_auction_result(
            create_auction_result_payload(
                sale_price_cents=sale_price_cents, sale_date=sale_date, **overrides
            ),
            ADMIN,
        ),
        "create_auction_result",
    )
