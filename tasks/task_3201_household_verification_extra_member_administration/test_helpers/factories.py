"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}@x.com"


def create_account_payload(**overrides) -> dict:
    defaults = {
        "email": _uniq("acct"),
        "region_code": "NA",
        "plan_tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_household_payload(**overrides) -> dict:
    defaults = {
        "label": "Home",
        "primary_location": "1 Main St",
        "network_fingerprint": "fp-home-1",
        "geo_cell": "geo-home-1",
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {"display_name": "Household Member"}
    defaults.update(overrides)
    return defaults


def create_device_payload(**overrides) -> dict:
    defaults = {
        "device_label": "Living Room TV",
        "device_type": "TV",
        "network_fingerprint": "fp-home-1",
        "geo_cell": "geo-home-1",
    }
    defaults.update(overrides)
    return defaults


def purchase_slot_payload(payer_member_id: str, expected_account_version: int, **overrides) -> dict:
    defaults = {
        "payer_member_id": payer_member_id,
        "transfer_rights": "TRANSFERABLE",
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def assign_slot_payload(member_region: str = "NA", **overrides) -> dict:
    defaults = {
        "email": _uniq("extra"),
        "display_name": "Extra Member",
        "member_region": member_region,
    }
    defaults.update(overrides)
    return defaults


def issue_challenge_payload(**overrides) -> dict:
    defaults = {"channel": "EMAIL", "challenge_reason": "NEW_DEVICE"}
    defaults.update(overrides)
    return defaults


def submit_challenge_payload(code: str, member_id: str, **overrides) -> dict:
    defaults = {"code": code, "member_id": member_id}
    defaults.update(overrides)
    return defaults


def grant_travel_pass_payload(**overrides) -> dict:
    defaults = {
        "grant_type": "TEMPORARY_14D",
        "starts_at": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def initiate_transfer_payload(member_id: str, **overrides) -> dict:
    defaults = {"member_id": member_id, "target_email": _uniq("newhome")}
    defaults.update(overrides)
    return defaults


def accept_transfer_payload(transfer_version: int, target_email: str = None, **overrides) -> dict:
    defaults = {
        "new_account_email": target_email or _uniq("newhome-accept"),
        "new_account_region": "NA",
        "new_account_plan_tier": "BASIC",
        "expected_profile_transfer_version": transfer_version,
    }
    defaults.update(overrides)
    return defaults


def start_playback_payload(device_id: str, **overrides) -> dict:
    defaults = {"device_id": device_id, "requested_resolution": "HD"}
    defaults.update(overrides)
    return defaults


def create_download_payload(device_id: str, **overrides) -> dict:
    defaults = {"device_id": device_id, "title_id": "title-1"}
    defaults.update(overrides)
    return defaults


def create_policy_payload(**overrides) -> dict:
    defaults = {
        "region_code": "NA",
        "enforcement_enabled": True,
        "grace_days": 0,
        "messaging_variant": "SOFT",
        "effective_from": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def record_metric_payload(**overrides) -> dict:
    defaults = {"metric_type": "CHURN_SIGNAL"}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def simulate_billing_payload(account_id: str, outcome: str = "FAILED") -> dict:
    return {"account_id": account_id, "outcome": outcome}
