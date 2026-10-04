"""Composite setup helpers — multi-step preambles built only from PRD endpoints.

Every fixture is function-scoped and builds its preconditions from scratch:
the runner restarts the server before each test, so no state survives.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_host_payload,
    create_member_payload,
    create_parking_site_payload,
    create_stay_request_payload,
    create_vehicle_payload,
    create_window_payload,
)
from .test_users import (
    make_anonymous_headers,
    make_host_operator_headers,
    make_member_headers,
    make_platform_admin_headers,
)

ANON = make_anonymous_headers()
ADMIN = make_platform_admin_headers()


# ---------------------------------------------------------------------------
# Tier 0 — primitives
# ---------------------------------------------------------------------------

def set_clock(instant: str):
    """Move the logical clock to `instant` and return the clock report."""
    resp = api_client.set_current_utc(instant, ADMIN)
    return get_success_data(resp)


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text[:400]}"
    )


def host_version(host_id: str) -> int:
    """Read the host's current version — the fresh OCC precondition value."""
    resp = api_client.get_host(host_id, make_host_operator_headers(host_id))
    if resp.status_code != 200:
        _fail(f"GET /api/hosts/{host_id}", resp)
    return resp.json()["data"]["version"]


def declare_host(category="FARM", state_code="TX", self_contained_required=False,
                 **overrides):
    """Declare a host as HostOperator. Returns the created host dict."""
    payload = create_host_payload(
        category=category,
        state_code=state_code,
        self_contained_required=self_contained_required,
        **overrides,
    )
    resp = api_client.create_host(payload, make_host_operator_headers("bootstrap-host"))
    if resp.status_code != 201:
        _fail("POST /api/hosts", resp)
    return resp.json()["data"]


def declare_sites(host_id: str, count: int, labels=None, site_class="BACK_IN",
                  max_vehicle_length_feet=40, has_electric=None,
                  electric_service_code=None, blocks_sites=None,
                  ensure_electric=True, **overrides):
    """Declare `count` parking sites under the host. Returns the site dicts.

    When the caller does not state the electric surface, the first site is given
    a 30-ampere pedestal so the host's amenity precondition can be satisfied —
    the onboarding decision requires `electric_site_count` of at least 1.
    """
    headers = make_host_operator_headers(host_id)
    sites = []
    for i in range(count):
        label = labels[i] if labels else f"S{i + 1}"
        if has_electric is None:
            site_electric = bool(ensure_electric and i == 0)
        else:
            site_electric = bool(has_electric)
        if electric_service_code is None:
            site_code = "ELECTRIC_30A" if site_electric else "NONE"
        else:
            site_code = electric_service_code
        extra = {}
        if blocks_sites is not None:
            extra["blocks_sites"] = (
                blocks_sites[i] if isinstance(blocks_sites, (list, tuple))
                else blocks_sites
            )
        payload = create_parking_site_payload(
            site_label=label,
            site_class=site_class,
            max_vehicle_length_feet=max_vehicle_length_feet,
            has_electric=site_electric,
            electric_service_code=site_code,
            **extra,
            **overrides,
        )
        resp = api_client.create_parking_site(host_id, payload, headers)
        if resp.status_code != 201:
            _fail(f"POST /api/hosts/{host_id}/parking-sites [{label}]", resp)
        sites.append(resp.json()["data"])
    return sites


def approve_host(host_id: str, reason="declared"):
    """Rule APPROVE on a pending host using its current version."""
    resp = api_client.decide_host(
        host_id,
        {"action": "APPROVE", "reason": reason,
         "expected_host_version": host_version(host_id)},
        ADMIN,
    )
    if resp.status_code != 200:
        _fail(f"POST /api/hosts/{host_id}/decisions APPROVE", resp)
    return resp.json()["data"]


def suspend_host(host_id: str, reason="ordinance audit"):
    resp = api_client.decide_host(
        host_id,
        {"action": "SUSPEND", "reason": reason,
         "expected_host_version": host_version(host_id)},
        ADMIN,
    )
    if resp.status_code != 200:
        _fail(f"POST /api/hosts/{host_id}/decisions SUSPEND", resp)
    return resp.json()["data"]


def register_member(plan_tier="PLUS", home_state_code="TX", activate=True,
                    **overrides):
    """Register a member (Anonymous) and optionally activate the subscription."""
    payload = create_member_payload(
        plan_tier=plan_tier, home_state_code=home_state_code, **overrides
    )
    resp = api_client.register_member(payload, ANON)
    if resp.status_code != 201:
        _fail("POST /api/members", resp)
    member = resp.json()["data"]
    if activate:
        r2 = api_client.member_subscription_action(
            member["id"], {"action": "ACTIVATE"}, ADMIN
        )
        if r2.status_code != 200:
            _fail("POST /api/members/{id}/subscription_actions ACTIVATE", r2)
        member = r2.json()["data"]
    return member


def declare_vehicle(member_id: str, vehicle_class="CLASS_C", length_feet=30,
                    self_contained=True, inspection_state_code="TX", **overrides):
    payload = create_vehicle_payload(
        vehicle_class=vehicle_class,
        length_feet=length_feet,
        self_contained=self_contained,
        inspection_state_code=inspection_state_code,
        **overrides,
    )
    resp = api_client.create_vehicle(member_id, payload, make_member_headers(member_id))
    if resp.status_code != 201:
        _fail(f"POST /api/members/{member_id}/vehicles", resp)
    return resp.json()["data"]


def declare_window(host_id: str, kind="EVENT", label="Test Window",
                   start_date="2026-06-01", end_date="2026-06-30",
                   capacity_override=20, reserved_sites=15):
    payload = create_window_payload(
        host_id, kind=kind, label=label, start_date=start_date,
        end_date=end_date, capacity_override=capacity_override,
        reserved_sites=reserved_sites,
    )
    resp = api_client.create_window(payload, make_host_operator_headers(host_id))
    if resp.status_code != 201:
        _fail("POST /api/availability-windows", resp)
    return resp.json()["data"]


def file_stay(host_id, member_id, vehicle_id, arrival_date="2026-06-20", nights=2,
              party_size=1, electric_request_code="NONE", request_depth=0,
              same_day_hold=False):
    payload = create_stay_request_payload(
        host_id, member_id, vehicle_id, arrival_date=arrival_date, nights=nights,
        party_size=party_size, electric_request_code=electric_request_code,
        request_depth=request_depth, same_day_hold=same_day_hold,
    )
    resp = api_client.create_stay_request(payload, make_member_headers(member_id))
    if resp.status_code != 201:
        _fail("POST /api/stay-requests", resp)
    return resp.json()["data"]


def try_file_stay(host_id, member_id, vehicle_id, **kwargs):
    """File a stay request returning the raw response (no assertion)."""
    payload = create_stay_request_payload(host_id, member_id, vehicle_id, **kwargs)
    return api_client.create_stay_request(payload, make_member_headers(member_id))


def confirm_stay(host_id, request_id, site_label=None, site_id=None):
    """CONFIRM a stay as the host operator (with the PRD's site payload form)."""
    body = {"decision": "CONFIRM", "expected_host_version": host_version(host_id)}
    # The decision names the site; the PRD supplies site_id, and tests may pass
    # a label which the helper resolves through the site list.
    if site_id is not None:
        body["site_id"] = site_id
    elif site_label is not None:
        body["site_id"] = resolve_site_id(host_id, site_label)
    resp = api_client.decide_stay_request(
        request_id, body, make_host_operator_headers(host_id)
    )
    if resp.status_code != 200:
        _fail(f"POST /api/stay-requests/{request_id}/decisions CONFIRM", resp)
    return resp.json()["data"]


def try_confirm_stay(host_id, request_id, site_id=None, site_label=None,
                     expected_host_version=None):
    """Raw confirm response; used by tests that assert on failure codes."""
    body = {
        "decision": "CONFIRM",
        "expected_host_version": (
            host_version(host_id) if expected_host_version is None
            else expected_host_version
        ),
    }
    if site_id is not None:
        body["site_id"] = site_id
    elif site_label is not None:
        body["site_id"] = resolve_site_id(host_id, site_label)
    return api_client.decide_stay_request(
        request_id, body, make_host_operator_headers(host_id)
    )


def decline_stay(host_id, request_id):
    resp = api_client.decide_stay_request(
        request_id,
        {"decision": "DECLINE", "expected_host_version": host_version(host_id)},
        make_host_operator_headers(host_id),
    )
    if resp.status_code != 200:
        _fail(f"POST /api/stay-requests/{request_id}/decisions DECLINE", resp)
    return resp.json()["data"]


def resolve_site_id(host_id: str, site_label: str) -> str:
    """Look up a declared site's id by its label."""
    resp = api_client.list_parking_sites(
        host_id, make_host_operator_headers(host_id), {"limit": 100, "offset": 0}
    )
    data = get_success_data(resp)
    rows = data if isinstance(data, list) else data.get("data", [])
    for row in rows:
        if row.get("site_label") == site_label:
            return row["id"]
    raise AssertionError(f"Setup failed: no site labelled {site_label!r} on {host_id}")


def read_host(host_id: str) -> dict:
    resp = api_client.get_host(host_id, make_host_operator_headers(host_id))
    if resp.status_code != 200:
        _fail(f"GET /api/hosts/{host_id}", resp)
    return resp.json()["data"]


def read_capacity_summary(host_id: str) -> dict:
    resp = api_client.get_host_capacity_summary(
        host_id, make_host_operator_headers(host_id)
    )
    if resp.status_code != 200:
        _fail(f"GET /api/hosts/{host_id}/capacity_summary", resp)
    return resp.json()["data"]


def read_member(member_id: str) -> dict:
    resp = api_client.get_member(member_id, ADMIN)
    if resp.status_code != 200:
        _fail(f"GET /api/members/{member_id}", resp)
    return resp.json()["data"]


def read_stay(request_id: str, host_id: str) -> dict:
    resp = api_client.get_stay_request(
        request_id, make_host_operator_headers(host_id)
    )
    if resp.status_code != 200:
        _fail(f"GET /api/stay-requests/{request_id}", resp)
    return resp.json()["data"]


def conduct_injection(member_id: str, severity="MAJOR", resolve_as="UPHOLD",
                      narrative="test injection"):
    resp = api_client.conduct_injection(
        member_id,
        {"severity": severity, "resolve_as": resolve_as, "narrative": narrative},
        ADMIN,
    )
    if resp.status_code not in (200, 201):
        _fail(f"POST /api/_members/{member_id}/conduct_injections", resp)
    return resp.json()["data"]


# ---------------------------------------------------------------------------
# Tier 1 — state progression composites
# ---------------------------------------------------------------------------

def setup_approved_host(site_count=1, category="FARM", state_code="TX",
                        self_contained_required=False, site_class="BACK_IN",
                        max_vehicle_length_feet=40, labels=None, **host_overrides):
    """Declare → sites → APPROVE. Returns (host, sites)."""
    host = declare_host(
        category=category, state_code=state_code,
        self_contained_required=self_contained_required, **host_overrides
    )
    sites = declare_sites(
        host["id"], site_count, labels=labels, site_class=site_class,
        max_vehicle_length_feet=max_vehicle_length_feet,
    )
    host = approve_host(host["id"])
    return host, sites


def setup_active_member(plan_tier="PLUS", home_state_code="TX",
                        vehicle_class="CLASS_C", length_feet=30,
                        self_contained=True, activate=True):
    """Register → activate → declare vehicle. Returns (member, vehicle)."""
    member = register_member(
        plan_tier=plan_tier, home_state_code=home_state_code, activate=activate
    )
    vehicle = declare_vehicle(
        member["id"],
        vehicle_class=vehicle_class,
        length_feet=length_feet,
        self_contained=self_contained,
        inspection_state_code=home_state_code,
    )
    return member, vehicle


def setup_basic_scenario(site_count=1, plan_tier="PLUS", category="FARM",
                         state_code="TX", self_contained_required=False,
                         site_class="BACK_IN", max_vehicle_length_feet=40,
                         host_state_code=None, member_state_code=None,
                         labels=None, vehicle_class="CLASS_C",
                         length_feet=30, vehicle_self_contained=True):
    """Approved host + active member + one rig. Returns a dict of parts."""
    host = declare_host(
        category=category,
        state_code=host_state_code or state_code,
        self_contained_required=self_contained_required,
    )
    sites = declare_sites(
        host["id"], site_count, labels=labels, site_class=site_class,
        max_vehicle_length_feet=max_vehicle_length_feet,
    )
    host = approve_host(host["id"])
    member, vehicle = setup_active_member(
        plan_tier=plan_tier,
        home_state_code=member_state_code or state_code,
        vehicle_class=vehicle_class,
        length_feet=length_feet,
        self_contained=vehicle_self_contained,
    )
    return {"host": host, "sites": sites, "member": member, "vehicle": vehicle}


# ---------------------------------------------------------------------------
# Tier 2/3 — stay lifecycle composites
# ---------------------------------------------------------------------------

def setup_confirmed_stay(site_count=2, arrival_date="2026-06-20", nights=2,
                         party_size=1, electric_request_code="NONE",
                         plan_tier="PLUS", category="FARM", state_code="TX",
                         self_contained_required=False, site_class="BACK_IN",
                         max_vehicle_length_feet=40, vehicle_class="CLASS_C",
                         length_feet=30, vehicle_self_contained=True,
                         labels=None, site_label=None, request_depth=0):
    """Approved host + active member + one stay confirmed at the given site."""
    parts = setup_basic_scenario(
        site_count=site_count, plan_tier=plan_tier, category=category,
        state_code=state_code, self_contained_required=self_contained_required,
        site_class=site_class, max_vehicle_length_feet=max_vehicle_length_feet,
        labels=labels, vehicle_class=vehicle_class, length_feet=length_feet,
        vehicle_self_contained=vehicle_self_contained,
    )
    stay = file_stay(
        parts["host"]["id"], parts["member"]["id"], parts["vehicle"]["id"],
        arrival_date=arrival_date, nights=nights, party_size=party_size,
        electric_request_code=electric_request_code, request_depth=request_depth,
    )
    target_label = site_label or parts["sites"][0]["site_label"]
    stay = confirm_stay(parts["host"]["id"], stay["id"], site_label=target_label)
    parts["stay"] = stay
    parts["site_label"] = target_label
    return parts


def setup_checked_in_stay(arrival_date="2026-06-10", nights=1, check_in_at=None,
                          **kwargs):
    """File and confirm the stay at a clock early enough to clear the 48-hour
    lead-time guard, then advance the clock to the stay's occupancy_start and
    check in."""
    # The stay must be filed at least 48 hours before its occupancy_start, so
    # file it first at a clock two whole days before the arrival date and only
    # then let the caller's clock setting reach the arrival window. An explicit
    # `check_in_at` still wins.
    from datetime import date, timedelta

    y, m, d = (int(x) for x in arrival_date.split("-"))
    file_day = (date(y, m, d) - timedelta(days=2)).isoformat()
    set_clock(f"{file_day}T00:00:00Z")
    parts = setup_confirmed_stay(arrival_date=arrival_date, nights=nights, **kwargs)
    set_clock(check_in_at or f"{arrival_date}T14:00:00Z")
    resp = api_client.check_in_stay(
        parts["stay"]["id"], make_host_operator_headers(parts["host"]["id"])
    )
    if resp.status_code != 200:
        _fail("POST /stay-requests/{id}/check_ins", resp)
    parts["stay"] = resp.json()["data"]
    return parts


def setup_checked_out_stay(arrival_date="2026-06-05", nights=1, **kwargs):
    """Confirmed → checked in → checked out. Returns a dict of parts."""
    parts = setup_checked_in_stay(arrival_date=arrival_date, nights=nights, **kwargs)
    from datetime import date, timedelta

    y, m, d = (int(x) for x in arrival_date.split("-"))
    departure = date(y, m, d) + timedelta(days=nights)
    set_clock(f"{departure.isoformat()}T11:00:00Z")
    resp = api_client.check_out_stay(
        parts["stay"]["id"], make_host_operator_headers(parts["host"]["id"])
    )
    if resp.status_code != 200:
        _fail("POST /stay-requests/{id}/check_outs", resp)
    parts["stay"] = resp.json()["data"]
    return parts


def setup_declined_stay(decline_arrival="2026-07-05", **kwargs):
    """Approved host + requested stay, declined by the host (depth 1).

    The stay is filed from a clock at least two whole days before `decline_arrival`
    so it clears the PRD's 48-hour lead-time guard; the scenario's own clock is
    left untouched afterwards, so callers keep whatever instant they set.
    """
    from datetime import date, timedelta

    parts = setup_basic_scenario(site_count=1, **kwargs)
    y, m, d = (int(x) for x in decline_arrival.split("-"))
    file_day = (date(y, m, d) - timedelta(days=2)).isoformat()
    set_clock(f"{file_day}T00:00:00Z")
    stay = file_stay(
        parts["host"]["id"], parts["member"]["id"], parts["vehicle"]["id"],
        arrival_date=decline_arrival, nights=2,
    )
    stay = decline_stay(parts["host"]["id"], stay["id"])
    parts["stay"] = stay
    return parts


def declare_patronization_record(host_id, member_id, stay_request_id,
                                 receipt_cents=10000, purchase_kind="TASTING"):
    """Record a purchase carrying the stay's current version precondition."""
    stay = read_stay(stay_request_id, host_id)
    resp = api_client.create_patronization_record(
        {
            "host_id": host_id,
            "member_id": member_id,
            "stay_request_id": stay_request_id,
            "receipt_cents": receipt_cents,
            "purchase_kind": purchase_kind,
            "expected_request_version": stay["version"],
        },
        make_host_operator_headers(host_id),
    )
    if resp.status_code != 201:
        _fail("POST /api/patronization-records", resp)
    return resp.json()["data"]


def verify_patronization_record(host_id, record_id, verification_code=None,
                                action="VERIFY"):
    body = {"action": action}
    if action == "VERIFY":
        body["verification_code"] = verification_code
    resp = api_client.verify_patronization_record(
        record_id, body, make_host_operator_headers(host_id)
    )
    if resp.status_code != 200:
        _fail(f"POST /api/patronization-records/{record_id}/verification", resp)
    return resp.json()["data"]