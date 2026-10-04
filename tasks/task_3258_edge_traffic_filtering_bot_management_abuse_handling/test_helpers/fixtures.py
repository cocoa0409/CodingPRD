"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints: the test harness restarts the server before each test, so no state
carries over. Setup calls use get_success_data so failures surface as clear
setup errors rather than assertion failures.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START
from .factories import (
    create_account_payload,
    create_pop_payload,
    create_zone_payload,
    create_ddos_event_payload,
    create_purge_request_payload,
    create_ip_block_payload,
    create_abuse_report_payload,
    dns_record,
    firewall_rule,
    rate_limit_rule,
    bot_band,
)
from .test_users import (
    TEST_USERS,
    make_zone_admin_headers,
)

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
TRUST_SAFETY = TEST_USERS["trust_safety_headers"]
NETWORK_PLANNER = TEST_USERS["network_planner_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# generic helpers
# ---------------------------------------------------------------------------

def parse_instant(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp with or without fractional digits."""
    assert isinstance(ts, str) and len(ts) > 0, f"not a timestamp: {ts!r}"
    text = ts.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def reset_clock():
    """Return the logical clock to its fixed startup default."""
    resp = api_client.set_clock(CLOCK_START, PLATFORM_ADMIN)
    get_success_data(resp)


def set_clock(current_utc: str):
    resp = api_client.set_clock(current_utc, PLATFORM_ADMIN)
    return get_success_data(resp)


def get_zone(zone_id: str) -> dict:
    resp = api_client.get_zone(zone_id, PLATFORM_ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: accounts and PoPs
# ---------------------------------------------------------------------------

def make_account(plan_tier: str = "PRO", **overrides) -> dict:
    """Create an account. Returns the account object."""
    payload = create_account_payload(plan_tier=plan_tier, **overrides)
    resp = api_client.create_account(payload, PLATFORM_ADMIN)
    return get_success_data(resp)


def make_pop(code: str = None, capacity_baseline_gbps: int = 200) -> dict:
    payload = create_pop_payload(capacity_baseline_gbps=capacity_baseline_gbps)
    if code is not None:
        payload["code"] = code
    resp = api_client.create_pop(payload, PLATFORM_ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: zones in a target state
# ---------------------------------------------------------------------------

def zone_headers(account: dict) -> dict:
    """ZoneAdmin headers threaded with the owning account's id (ownership)."""
    return make_zone_admin_headers(account["id"])


def make_pending_zone(account: dict, domain: str = None, onboarding_type: str = "FULL",
                      records=None) -> dict:
    """Create a PENDING zone owned by account. Records default to one proxied A."""
    kwargs = {"onboarding_type": onboarding_type}
    if records is None:
        records = [dns_record()]
    kwargs["dns_records"] = records
    if domain is not None:
        kwargs["domain_name"] = domain
    payload = create_zone_payload(account["id"], **kwargs)
    resp = api_client.create_zone(payload, zone_headers(account))
    return get_success_data(resp)


def make_active_zone(account: dict, domain: str = None, onboarding_type: str = "FULL",
                     records=None) -> dict:
    """Create a zone and verify it to ACTIVE. Returns the ACTIVE zone."""
    zone = make_pending_zone(account, domain=domain, onboarding_type=onboarding_type,
                             records=records)
    resp = api_client.verify_zone(zone["id"], zone_headers(account))
    return get_success_data(resp)


def make_active_zone_ref(account: dict, domain: str = None, onboarding_type: str = "FULL",
                         records=None) -> dict:
    """Create a zone and verify it to ACTIVE. Returns the zone with the version
    observed immediately after verification."""
    zone = make_pending_zone(account, domain=domain, onboarding_type=onboarding_type,
                             records=records)
    resp = api_client.verify_zone(zone["id"], zone_headers(account))
    return get_success_data(resp)


def make_partial_active_zone(account: dict, domain: str = None,
                             cname_content: str = "app.cdn.example.net") -> dict:
    """Create a PARTIAL zone with a compliant proxied CNAME and verify it."""
    records = [dns_record(name="app", record_type="CNAME",
                          content=cname_content, proxied=True)]
    return make_active_zone(account, domain=domain, onboarding_type="PARTIAL",
                            records=records)


def patch_zone(zone: dict, account: dict, payload: dict) -> dict:
    resp = api_client.patch_zone(zone["id"], payload, zone_headers(account))
    return get_success_data(resp)


def set_dos_sensitivity(zone: dict, account: dict, sensitivity: str) -> dict:
    """PATCH dos_sensitivity with a fresh OCC expected_zone_version."""
    current = get_zone(zone["id"])
    resp = api_client.patch_zone(
        zone["id"],
        {"dos_sensitivity": sensitivity, "expected_zone_version": current["version"]},
        zone_headers(account),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: configured zones
# ---------------------------------------------------------------------------

def make_active_zone_with_firewall_rule(account: dict, domain: str = None,
                                        rule_name: str = "r1",
                                        expression: str = '(http.request.uri.path contains "/admin")',
                                        action: str = "BLOCK") -> dict:
    """ACTIVE zone carrying one ACTIVE firewall rule."""
    zone = make_active_zone(account, domain=domain)
    return patch_zone(zone, account, {
        "traffic_rules": [firewall_rule(rule_name, expression, action)],
    })


def make_active_zone_with_rate_limit(account: dict, domain: str = None,
                                     threshold_rpm: int = 3, action: str = "BLOCK",
                                     rule_name: str = "rl1") -> dict:
    """ACTIVE zone carrying one ACTIVE RATE_LIMIT rule."""
    zone = make_active_zone(account, domain=domain)
    return patch_zone(zone, account, {
        "traffic_rules": [rate_limit_rule(
            rule_name, '(http.request.uri.path contains "/api")', action, threshold_rpm
        )],
    })


def make_shielded_zone(account: dict, pop_code: str, domain: str = None) -> dict:
    """ACTIVE zone with origin_shield_pop_code set to an existing PoP code."""
    zone = make_active_zone(account, domain=domain)
    return patch_zone(zone, account, {"origin_shield_pop_code": pop_code})


def drift_zone_to_moved(zone: dict, account: dict, advance_to: str) -> dict:
    """Replace dns_records with a non-proxied set, then advance the clock so the
    delegation re-check moves the ACTIVE zone to MOVED. Returns the MOVED zone."""
    records = [
        {**rec, "proxied": False} for rec in get_zone(zone["id"])["dns_records"]
    ]
    patch_zone(zone, account, {"dns_records": records})
    set_clock(advance_to)
    return get_zone(zone["id"])


# ---------------------------------------------------------------------------
# Tier 4: DDoS / mitigation
# ---------------------------------------------------------------------------

def make_activated_ddos_event(zone: dict, account: dict, observed_rps: int = 5000,
                              baseline_rps: int = 100) -> dict:
    """Ingest an auto-mitigating DdosEvent on an ACTIVE zone."""
    payload = create_ddos_event_payload(
        observed_rps=observed_rps, baseline_rps=baseline_rps
    )
    resp = api_client.create_ddos_event(zone["id"], payload, zone_headers(account))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: IP blocks and abuse reports
# ---------------------------------------------------------------------------

def make_provisional_block(zone: dict, ip: str = "198.51.100.7",
                           reason: str = "credential stuffing") -> dict:
    payload = create_ip_block_payload(zone["id"], ip=ip, reason=reason)
    resp = api_client.create_ip_block(payload, TRUST_SAFETY)
    return get_success_data(resp)


def make_confirmed_block(zone: dict, ip: str = "198.51.100.7") -> dict:
    block = make_provisional_block(zone, ip=ip)
    resp = api_client.confirm_ip_block(block["id"], TRUST_SAFETY)
    return get_success_data(resp)


def make_abuse_report(zone: dict, **overrides) -> dict:
    payload = create_abuse_report_payload(zone["id"], **overrides)
    resp = api_client.create_abuse_report(payload, ANONYMOUS)
    return get_success_data(resp)


def make_reviewing_report(zone: dict, **overrides) -> dict:
    report = make_abuse_report(zone, **overrides)
    resp = api_client.claim_abuse_report(report["id"], TRUST_SAFETY)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# purge helpers
# ---------------------------------------------------------------------------

def make_purge_request(zone: dict, account: dict, purge_type: str = "PURGE_ALL",
                       urls=None) -> dict:
    payload = create_purge_request_payload(zone["id"], purge_type=purge_type)
    if urls is not None:
        payload["urls"] = urls
    resp = api_client.create_purge_request(payload, zone_headers(account))
    return get_success_data(resp)


def get_purge_request(purge_id: str) -> dict:
    resp = api_client.get_purge_request(purge_id, PLATFORM_ADMIN)
    return get_success_data(resp)
