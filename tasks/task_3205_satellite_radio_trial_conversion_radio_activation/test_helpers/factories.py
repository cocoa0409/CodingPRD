"""Payload factories — input fields only, with unique-value generators so
tests never collide on unique constraints."""

import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def unique_email() -> str:
    return f"user{_seq()}@example.com"


def unique_vin() -> str:
    # 17 chars exactly
    return f"1HGCM82633A{_seq():06d}"[-17:].ljust(17, "0")


def unique_esn() -> str:
    return f"ESN{_seq():08d}"


def unique_code(prefix: str) -> str:
    return f"{prefix}{_seq():06d}"


def create_customer_payload(**overrides) -> dict:
    payload = {
        "email": unique_email(),
        "full_name": f"Customer {_seq()}",
        "household_size": 1,
    }
    payload.update(overrides)
    return payload


def create_automaker_payload(**overrides) -> dict:
    payload = {
        "oem_code": unique_code("OEM"),
        "name": f"Automaker {_seq()}",
        "feed_contact_email": unique_email(),
    }
    payload.update(overrides)
    return payload


def create_dealer_payload(**overrides) -> dict:
    payload = {
        "dealer_code": unique_code("DLR"),
        "name": f"Dealer {_seq()}",
        "used_program_enrolled": False,
    }
    payload.update(overrides)
    return payload


def create_package_tier_payload(**overrides) -> dict:
    payload = {
        "code": unique_code("TIER"),
        "name": f"Tier {_seq()}",
        "channel_entitlements": ["CH1"],
        "includes_streaming": True,
        "min_hardware_generation": "GEN1",
    }
    payload.update(overrides)
    return payload


def create_subscription_plan_payload(package_tier_id: str, **overrides) -> dict:
    payload = {
        "code": unique_code("PLAN"),
        "name": f"Plan {_seq()}",
        "package_tier_id": package_tier_id,
        "service_mode": "STREAMING_ONLY",
        "is_trial": False,
        "term_kind": "MONTHLY",
        "term_length_days": 30,
        "price_cents": 3000,
        "auto_renew_default": False,
    }
    payload.update(overrides)
    return payload


def create_trial_plan_payload(package_tier_id: str, **overrides) -> dict:
    payload = create_subscription_plan_payload(
        package_tier_id,
        service_mode="IN_VEHICLE",
        is_trial=True,
        term_kind="TRIAL",
        term_length_days=30,
        price_cents=0,
    )
    payload.update(overrides)
    return payload


def create_vehicle_payload(automaker_id: str, owner_customer_id: str, **overrides) -> dict:
    payload = {
        "vin": unique_vin(),
        "automaker_id": automaker_id,
        "model_year": 2025,
        "owner_customer_id": owner_customer_id,
        "condition": "NEW",
    }
    payload.update(overrides)
    return payload


def create_radio_payload(vehicle_id: str, **overrides) -> dict:
    payload = {
        "esn": unique_esn(),
        "vehicle_id": vehicle_id,
        "hardware_generation": "GEN2",
    }
    payload.update(overrides)
    return payload


def create_campaign_payload(**overrides) -> dict:
    payload = {
        "code": unique_code("CAMP"),
        "name": f"Campaign {_seq()}",
        "lifecycle_phase": "POST_TRIAL",
        "window_start_at": "2026-08-01T00:00:00Z",
        "window_end_at": "2026-12-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_offer_step_payload(plan_id: str, **overrides) -> dict:
    payload = {
        "step_index": 0,
        "plan_id": plan_id,
        "step_up_rank": 0,
        "discount_pct_bps": 0,
        "flat_discount_cents": 0,
    }
    payload.update(overrides)
    return payload
