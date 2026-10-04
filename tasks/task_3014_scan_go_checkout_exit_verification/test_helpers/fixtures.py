"""Composite setup helpers for the Scan-Go Checkout API.

Each helper builds its preconditions from scratch using only public API
operations, and uses the lenient get_success_data() so a setup failure
surfaces as a clear setup error rather than an assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import NOON_ISO
from .factories import (
    create_catalog_item_payload,
    create_club_payload,
    create_member_payload,
    create_offer_payload,
)
from .test_users import (
    TEST_USERS,
    make_associate_headers,
    make_member_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["club_manager_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]
LPO = TEST_USERS["lpo_headers"]


# ---------------------------------------------------------------------------
# Primitive setup helpers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=NOON_ISO):
    resp = api_client.set_clock(to_iso8601, ADMIN)
    assert resp.status_code == 200, f"Setup failed: set_clock -> {resp.text}"


def create_club(**overrides):
    resp = api_client.create_club(create_club_payload(**overrides), ADMIN)
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("id"), (
        f"Setup failed: create club -> {resp.text}"
    )
    return data


def patch_club(club_id, current_version, **fields):
    payload = {"expected_club_version": current_version}
    payload.update(fields)
    resp = api_client.update_club(club_id, payload, MANAGER)
    data = get_success_data(resp)
    assert isinstance(data, dict), f"Setup failed: patch club -> {resp.text}"
    return data


def create_item(club_id, **overrides):
    resp = api_client.create_catalog_item(
        club_id, create_catalog_item_payload(**overrides), ADMIN,
    )
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("id"), (
        f"Setup failed: create catalog item -> {resp.text}"
    )
    return data


def create_offer(club_id, catalog_item_id, **overrides):
    resp = api_client.create_instant_savings_offer(
        club_id, create_offer_payload(catalog_item_id=catalog_item_id, **overrides),
        MANAGER,
    )
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("id"), (
        f"Setup failed: create offer -> {resp.text}"
    )
    return data


def create_member(club_id, **overrides):
    resp = api_client.create_member(
        create_member_payload(home_club_id=club_id, **overrides), ADMIN,
    )
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("id"), (
        f"Setup failed: create member -> {resp.text}"
    )
    return data


def member_headers(member):
    return make_member_headers(member["id"])


def get_session(session_id):
    resp = api_client.get_scan_session(session_id, ADMIN)
    data = get_success_data(resp)
    assert isinstance(data, dict), f"Setup failed: get session -> {resp.text}"
    return data


def get_member(member_id):
    resp = api_client.get_member(member_id, ADMIN)
    data = get_success_data(resp)
    assert isinstance(data, dict), f"Setup failed: get member -> {resp.text}"
    return data


def get_line(line_id):
    resp = api_client.get_scan_line(line_id, ADMIN)
    data = get_success_data(resp)
    assert isinstance(data, dict), f"Setup failed: get line -> {resp.text}"
    return data


def get_curbside_order(order_id):
    resp = api_client.get_curbside_order(order_id, ADMIN)
    data = get_success_data(resp)
    assert isinstance(data, dict), f"Setup failed: get curbside order -> {resp.text}"
    return data


# ---------------------------------------------------------------------------
# Tier 1-3: scan session lifecycle
# ---------------------------------------------------------------------------

def setup_club_member(clock_iso=NOON_ISO, member_overrides=None, club_overrides=None):
    """Clock set, one club, one member. Returns (club, member)."""
    set_clock(clock_iso)
    club = create_club(**(club_overrides or {}))
    member = create_member(club["id"], **(member_overrides or {}))
    return club, member


def create_session(club, member):
    resp = api_client.create_scan_session(club["id"], member_headers(member))
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("id"), (
        f"Setup failed: create session -> {resp.text}"
    )
    return data


def scan_unit_line(session, member, item, quantity=1):
    resp = api_client.scan_line(
        session["id"], {"catalog_item_id": item["id"], "quantity": quantity},
        member_headers(member),
    )
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("id"), (
        f"Setup failed: scan unit line -> {resp.text}"
    )
    return data


def scan_weighted_line(session, member, item, weight_grams):
    resp = api_client.scan_line(
        session["id"], {"catalog_item_id": item["id"], "weight_grams": weight_grams},
        member_headers(member),
    )
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("id"), (
        f"Setup failed: scan weighted line -> {resp.text}"
    )
    return data


def setup_session_with_unit_item(
    price_cents=500,
    quantity=1,
    member_overrides=None,
    club_overrides=None,
    restricted_class=None,
):
    """Club + member + one UNIT item + session with `quantity` scanned.

    Returns (club, item, member, session, line).
    """
    club, member = setup_club_member(
        member_overrides=member_overrides, club_overrides=club_overrides,
    )
    item_kwargs = {"unit_price_cents": price_cents}
    if restricted_class:
        item_kwargs["restricted_class"] = restricted_class
    item = create_item(club["id"], **item_kwargs)
    session = create_session(club, member)
    line = scan_unit_line(session, member, item, quantity=quantity)
    return club, item, member, session, line


def setup_paid_session(
    price_cents=500,
    quantity=1,
    member_overrides=None,
    club_overrides=None,
):
    """Session paid for `quantity` x one UNIT item. Returns
    (club, item, member, session, pay_data) where pay_data carries the
    final total and the minted receipt_code."""
    club, item, member, session, _line = setup_session_with_unit_item(
        price_cents=price_cents,
        quantity=quantity,
        member_overrides=member_overrides,
        club_overrides=club_overrides,
    )
    resp = api_client.pay_session(session["id"], member_headers(member))
    pay_data = get_success_data(resp)
    assert isinstance(pay_data, dict) and pay_data.get("status") == "PAID", (
        f"Setup failed: pay session -> {resp.text}"
    )
    return club, item, member, session, pay_data


def setup_exit_pending_session(club_overrides=None, **kwargs):
    """Paid session moved to EXIT_PENDING via exit-scan (method omitted, so the
    club's exit_verification_mode is used). Returns
    (club, item, member, session, pay_data, verification)."""
    club, item, member, session, pay_data = setup_paid_session(
        club_overrides=club_overrides, **kwargs,
    )
    resp = api_client.exit_scan(session["id"], member_headers(member))
    verification = get_success_data(resp)
    assert isinstance(verification, dict) and verification.get("id"), (
        f"Setup failed: exit-scan -> {resp.text}"
    )
    return club, item, member, session, pay_data, verification


def setup_flagged_session_by_cv(observed_item_count=5, **kwargs):
    """CV_ARCH session flagged by a cv-report mismatch; an OPEN LP case exists.

    Returns (club, item, member, session, pay_data, verification, lp_case).
    """
    club, item, member, session, pay_data, verification = (
        setup_exit_pending_session(
            club_overrides={"exit_verification_mode": "CV_ARCH"}, **kwargs,
        )
    )
    resp = api_client.cv_report(verification["id"], observed_item_count, ASSOCIATE)
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("status") == "MISMATCH", (
        f"Setup failed: cv-report did not mismatch -> {resp.text}"
    )
    cases, _meta = _list_lp_cases()
    case = next(c for c in cases if c["session_id"] == session["id"])
    return club, item, member, session, pay_data, verification, case


def _list_lp_cases():
    resp = api_client.list_lp_cases(LPO)
    assert resp.status_code == 200, f"Setup failed: list LP cases -> {resp.text}"
    body = resp.json()
    return body["data"], body["meta"]


def resolve_pending_intercept_for_session(session_id, decision_payload):
    """Find the session's first PENDING intercept and resolve it. Returns the
    resolve response data."""
    resp = api_client.list_session_intercepts(session_id, ASSOCIATE)
    assert resp.status_code == 200, f"Setup failed: list intercepts -> {resp.text}"
    intercepts = resp.json()["data"]
    pending = [i for i in intercepts if i["status"] == "PENDING"]
    assert pending, f"Setup failed: no PENDING intercept on session {session_id}"
    resp = api_client.resolve_intercept(pending[0]["id"], decision_payload, ASSOCIATE)
    data = get_success_data(resp)
    assert isinstance(data, dict), f"Setup failed: resolve intercept -> {resp.text}"
    return data


# ---------------------------------------------------------------------------
# Tier 4-5: curbside lifecycle
# ---------------------------------------------------------------------------

def setup_club_with_capacity(capacity=1):
    """Club whose staging_slot_capacity is patched to `capacity` via OCC.

    Returns the club (fresh view after the patch)."""
    club = create_club()
    return patch_club(club["id"], club["version"], staging_slot_capacity=capacity)


def create_curbside_order(club, member, item_count=1):
    resp = api_client.create_curbside_order(
        club["id"], item_count, member_headers(member),
    )
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("id"), (
        f"Setup failed: create curbside order -> {resp.text}"
    )
    return data


def stage_order(order_id, slot_label="S1", start="2026-09-01T14:00:00Z",
                end="2026-09-01T15:00:00Z"):
    resp = api_client.stage_curbside_order(
        order_id,
        {
            "staging_slot_label": slot_label,
            "window_start_iso": start,
            "window_end_iso": end,
        },
        ASSOCIATE,
    )
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("status") == "STAGING", (
        f"Setup failed: stage order -> {resp.text}"
    )
    return data
