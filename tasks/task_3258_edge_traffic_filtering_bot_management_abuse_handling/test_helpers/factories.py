"""Payload factories — one per entity, input fields only."""
import itertools
from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _n():
    return next(_counter)


def create_account_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "company_name": f"{TEST_DEFAULTS['COMPANY_NAME']} {n}",
        "plan_tier": "PRO",
        "account_email": f"ops{n}@test.example.com",
    }
    defaults.update(overrides)
    return defaults


def create_pop_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        # three-letter code, unique per call
        "code": f"Q{chr(65 + (n % 26))}{chr(65 + ((n // 26) % 26))}",
        "capacity_baseline_gbps": TEST_DEFAULTS["POP_CAPACITY_GBPS"],
    }
    defaults.update(overrides)
    return defaults


def dns_record(name="www", record_type="A", content="192.0.2.1", proxied=True):
    return {
        "name": name,
        "record_type": record_type,
        "content": content,
        "proxied": proxied,
    }


def create_zone_payload(account_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "account_id": account_id,
        "domain_name": f"zone{n}.example.com",
        "onboarding_type": "FULL",
        "origin_host_email": TEST_DEFAULTS["ORIGIN_HOST_EMAIL"],
        "dns_records": [dns_record(content=f"192.0.2.{n % 250 + 1}")],
    }
    defaults.update(overrides)
    return defaults


def firewall_rule(name, expression, action, status="ACTIVE"):
    rule = {
        "name": name,
        "rule_kind": "FIREWALL_FILTER",
        "expression": expression,
        "action": action,
        "status": status,
    }
    return rule


def rate_limit_rule(name, expression, action, threshold_rpm, status="ACTIVE"):
    return {
        "name": name,
        "rule_kind": "RATE_LIMIT",
        "expression": expression,
        "action": action,
        "rate_limit_threshold_rpm": threshold_rpm,
        "status": status,
    }


def bot_band(name, action, min_score, max_score, status="ACTIVE"):
    return {
        "name": name,
        "action": action,
        "min_score": min_score,
        "max_score": max_score,
        "status": status,
    }


def ruleset_subscription(slug, sensitivity="MEDIUM", status="ACTIVE", overrides=None):
    return {
        "slug": slug,
        "sensitivity": sensitivity,
        "status": status,
        "overrides": overrides or [],
    }


def ruleset_override(managed_rule_id, override_action="DISABLE", status="ACTIVE"):
    return {
        "managed_rule_id": managed_rule_id,
        "override_action": override_action,
        "status": status,
    }


def create_traffic_hit_payload(**overrides) -> dict:
    defaults = {
        "occurred_at": "2026-09-01T00:00:00Z",
        "client_ip": "198.51.100.1",
    }
    defaults.update(overrides)
    return defaults


def create_bot_classification_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "request_fingerprint": f"fp-{n}",
        "verified_crawler": False,
        "client_ip": "203.0.113.1",
    }
    defaults.update(overrides)
    return defaults


def create_ddos_event_payload(**overrides) -> dict:
    defaults = {
        "observed_rps": 5000,
        "baseline_rps": 100,
    }
    defaults.update(overrides)
    return defaults


def create_purge_request_payload(zone_id, **overrides) -> dict:
    defaults = {
        "zone_id": zone_id,
        "purge_type": "PURGE_ALL",
    }
    defaults.update(overrides)
    return defaults


def create_ip_block_payload(zone_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "zone_id": zone_id,
        "ip": f"198.51.100.{n % 250 + 1}",
        "ip_version": "V4",
        "reason": "abusive traffic",
    }
    defaults.update(overrides)
    return defaults


def create_abuse_report_payload(zone_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "zone_id": zone_id,
        "reporter_email": f"reporter{n}@example.org",
        "category": "PHISHING",
        "description": "abuse report body",
        "target_url": "https://target.example.com/bad",
        "reporter_trust_score": 50,
    }
    defaults.update(overrides)
    return defaults


def maintenance_window_payload(start_utc, end_utc, headroom_pct=50):
    return {
        "start_utc": start_utc,
        "end_utc": end_utc,
        "headroom_pct": headroom_pct,
    }
