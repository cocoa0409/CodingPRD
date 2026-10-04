"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def _seq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def platform_payload(**overrides) -> dict:
    defaults = {
        "code": _seq("PF"),
        "interface_key": "INTERFACE_A",
        "chemistry_family": "LION_NMC",
        "backward_commitment_years": 10,
        "forward_commitment_generations": 2,
    }
    defaults.update(overrides)
    return defaults


def pack_payload(platform_id, **overrides) -> dict:
    defaults = {
        "platform_id": platform_id,
        "sku": _seq("P"),
        "pack_generation": 1,
        "cell_supplier_code": "SAM",
        "cell_format": "C21700",
        "rated_capacity_wh": 100,
        "max_charge_rate_w": 200,
        "replacement_price_cents": 20000,
        "warranty_days": 720,
        "free_replacement_days": 90,
    }
    defaults.update(overrides)
    return defaults


def charger_payload(platform_id, **overrides) -> dict:
    defaults = {
        "platform_id": platform_id,
        "model_code": _seq("C"),
        "charger_generation": 1,
        "max_charge_rate_w": 400,
    }
    defaults.update(overrides)
    return defaults


def tool_model_payload(platform_id, **overrides) -> dict:
    defaults = {
        "platform_id": platform_id,
        "model_code": _seq("T"),
        "trade": "CARPENTRY",
        "category": "DRILL",
        "tier": "CONSUMER",
        "corded_conversion": False,
        "avg_power_draw_w": 250,
        "min_pack_generation": 1,
        "max_pack_generation": 1,
        "replacement_price_cents": 9000,
        "warranty_days": 360,
        "free_replacement_days": 30,
        "torque_min_nm": 2,
        "torque_max_nm": 60,
    }
    defaults.update(overrides)
    return defaults


def insight_payload(tool_model_id, **overrides) -> dict:
    defaults = {
        "tool_model_id": tool_model_id,
        "kind": "FIELD_RESEARCH",
        "summary": "field finding",
        "severity": "HIGH",
    }
    defaults.update(overrides)
    return defaults


def service_center_payload(**overrides) -> dict:
    defaults = {
        "code": _seq("SC"),
        "region": "MW",
        "capabilities": ["TOOL_REPAIR", "BATTERY_SERVICE"],
        "daily_capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def asset_account_payload(**overrides) -> dict:
    defaults = {
        "org_name": _seq("Org"),
        "tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def tracked_asset_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "subject_type": "BATTERY",
        "serial_number": _seq("SN"),
        "manufactured_at": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def warranty_claim_payload(tracked_asset_id, **overrides) -> dict:
    defaults = {
        "tracked_asset_id": tracked_asset_id,
        "claim_type": "BATTERY_REPLACEMENT",
        "fault_code": "F1",
        "service_date": "2026-09-10",
    }
    defaults.update(overrides)
    return defaults


def channel_partner_payload(**overrides) -> dict:
    defaults = {
        "name": _seq("Partner"),
        "channel_type": "INDUSTRIAL_DISTRIBUTOR",
        "region": "MW",
    }
    defaults.update(overrides)
    return defaults


def listing_payload(channel_partner_id, expected_channel_partner_version, **overrides) -> dict:
    defaults = {
        "channel_partner_id": channel_partner_id,
        "wholesale_price_cents": 12000,
        "allocation_qty": 10,
        "expected_channel_partner_version": expected_channel_partner_version,
    }
    defaults.update(overrides)
    return defaults


def counterfeit_case_payload(battery_pack_id, **overrides) -> dict:
    defaults = {
        "battery_pack_id": battery_pack_id,
        "reported_serial": _seq("FAKE"),
        "detection_method": "SERIAL_MISMATCH",
    }
    defaults.update(overrides)
    return defaults


def safety_bulletin_payload(platform_id, **overrides) -> dict:
    defaults = {
        "platform_id": platform_id,
        "severity": "ADVISORY",
        "title": "bulletin",
        "effective_from": "2026-10-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
