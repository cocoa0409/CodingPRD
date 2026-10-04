"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert "updated_at" in data, f"{entity}.updated_at must be present"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def assert_account(data: dict):
    _assert_common_fields(data, "Account")
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert data["plan_tier"] in ["FREE", "PRO", "BUSINESS", "ENTERPRISE"]
    assert isinstance(data["account_email"], str) and len(data["account_email"]) > 0
    assert isinstance(data["support_response_sla_hours"], int)
    assert data["support_response_sla_hours"] > 0


def assert_pop(data: dict):
    _assert_common_fields(data, "Pop")
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["capacity_baseline_gbps"], int)
    assert data["capacity_baseline_gbps"] > 0
    assert data["status"] == "ACTIVE"
    assert isinstance(data["maintenance_windows"], list)


def assert_zone(data: dict):
    _assert_common_fields(data, "Zone")
    assert is_valid_uuid(data.get("account_id", "")), "Zone.account_id must be a UUID"
    assert isinstance(data["domain_name"], str) and len(data["domain_name"]) > 0
    assert data["onboarding_type"] in ["FULL", "PARTIAL"]
    assert data["status"] in ["PENDING", "ACTIVE", "MOVED", "DELETED"]
    assert isinstance(data["dns_records"], list)
    assert isinstance(data["bot_fight_mode"], bool)
    assert data["dos_sensitivity"] in ["DEFAULT", "LOW", "HIGH"]
    assert isinstance(data["traffic_rules"], list)
    assert isinstance(data["ruleset_subscriptions"], list)
    assert isinstance(data["bot_action_bands"], list)
    assert isinstance(data["honeypot_paths"], list)
    assert isinstance(data["edge_ttl_seconds"], int) and data["edge_ttl_seconds"] > 0


def assert_ddos_event(data: dict):
    _assert_common_fields(data, "DdosEvent")
    assert is_valid_uuid(data.get("zone_id", "")), "DdosEvent.zone_id must be a UUID"
    assert isinstance(data["observed_rps"], int) and data["observed_rps"] >= 0
    assert isinstance(data["baseline_rps"], int) and data["baseline_rps"] > 0
    assert isinstance(data["trigger_threshold_rps"], int)
    assert isinstance(data["auto_mitigated"], bool)
    assert data["status"] in ["ACTIVATED", "ENDED"]
    assert is_iso8601_timestamp(data.get("activated_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))


def assert_purge_request(data: dict):
    _assert_common_fields(data, "PurgeRequest")
    assert is_valid_uuid(data.get("zone_id", "")), "PurgeRequest.zone_id must be a UUID"
    assert data["purge_type"] in ["PURGE_ALL", "PURGE_URL"]
    assert data["status"] in ["QUEUED", "IN_PROGRESS", "COMPLETED"]
    assert is_iso8601_timestamp(data.get("requested_at", ""))
    assert isinstance(data["origin_shield_degraded"], bool)


def assert_ip_block(data: dict):
    _assert_common_fields(data, "IpBlock")
    assert is_valid_uuid(data.get("zone_id", "")), "IpBlock.zone_id must be a UUID"
    assert isinstance(data["ip"], str) and len(data["ip"]) > 0
    assert data["ip_version"] in ["V4", "V6"]
    assert isinstance(data["reason"], str)
    assert data["status"] in ["PROVISIONAL", "CONFIRMED", "EXPIRED"]
    assert is_iso8601_timestamp(data.get("expires_at", ""))


def assert_abuse_report(data: dict):
    _assert_common_fields(data, "AbuseReport")
    assert is_valid_uuid(data.get("zone_id", "")), "AbuseReport.zone_id must be a UUID"
    assert isinstance(data["reporter_email"], str)
    assert data["category"] in [
        "PHISHING", "MALWARE", "CSAM", "SPAM", "COPYRIGHT", "OTHER",
    ]
    assert isinstance(data["description"], str)
    assert isinstance(data["target_url"], str)
    assert isinstance(data["reporter_trust_score"], int)
    assert 1 <= data["reporter_trust_score"] <= 100
    assert isinstance(data["priority_score"], int)
    assert data["routing_mode"] in ["HOSTED", "PROXIED"]
    assert data["status"] in [
        "SUBMITTED", "REVIEWING", "FORWARDED", "ACTION_TAKEN", "CLOSED",
    ]


def assert_meta_envelope(body: dict):
    """Common envelope invariants for any JSON response body."""
    assert "meta" in body, "response must carry a meta object"
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        "api_request_id must start with req_"
    )
    assert isinstance(meta.get("api_request_timestamp"), str)
    assert "response_type" in body
    assert "data" in body
