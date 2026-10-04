"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "FA_NAME": "Bay Franchise",
    "FA_REGION": "BF",
    "FA_OBLIGATION_HOMES": 12000,
    "FA_OBLIGATION_DEADLINE": "2027-12-31T00:00:00Z",
    "NODE_CODE": "NE-1",
    "NODE_HOMES": 100,
    "NODE_SPECTRUM_MHZ": 48,
    "BLOCK_MHZ": 48,
    "SG_CODE": "SG-1",
    "SG_HOMES": 100,
    "WARN_PCT": 70,
    "CRIT_PCT": 85,
    "SAMPLE_DOWNSTREAM": 100,
    "SAMPLE_UPSTREAM": 10,
    "CHILD_COUNT": 2,
    "MIN_HOMES_PER_CHILD": 200,
    "MAX_HOMES_PER_CHILD": 400,
    "WAVE_CODE": "W1",
    "WAVE_START": "2026-10-01T00:00:00Z",
    "WAVE_END": "2026-10-02T00:00:00Z",
    "PREMISE_REF": "P-1",
    "PREMISE_ADDRESS": "1 Main St",
    "CPE_MODEL": "XB8",
    "CPE_DOCSIS": "4.0",
    "CPE_CAPABILITY": "D40",
    "CPE_MAX_DOWNSTREAM": 1000,
    "TIER_CODE": "T10",
    "TIER_DOWNSTREAM": 10,
    "TIER_UPSTREAM": 2,
    "CAMPAIGN_CODE": "RC1",
    "COMPLAINT_DESCRIPTION": "slow evenings",
    "CLOCK_UTC": "2026-10-01T00:00:00Z",
}


def create_franchise_area_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["FA_NAME"],
        "region_code": DEFAULTS["FA_REGION"],
        "obligation_homes_required": DEFAULTS["FA_OBLIGATION_HOMES"],
        "obligation_deadline": DEFAULTS["FA_OBLIGATION_DEADLINE"],
    }
    defaults.update(overrides)
    return defaults


def create_optical_node_payload(**overrides) -> dict:
    defaults = {
        "node_code": DEFAULTS["NODE_CODE"],
        "homes_passed": DEFAULTS["NODE_HOMES"],
        "downstream_spectrum_mhz": DEFAULTS["NODE_SPECTRUM_MHZ"],
        "upstream_config": "LEGACY",
    }
    defaults.update(overrides)
    return defaults


def create_spectrum_block_payload(**overrides) -> dict:
    defaults = {
        "block_type": "DATA",
        "mhz": DEFAULTS["BLOCK_MHZ"],
    }
    defaults.update(overrides)
    return defaults


def create_service_group_payload(**overrides) -> dict:
    defaults = {
        "sg_code": DEFAULTS["SG_CODE"],
        "homes_passed": DEFAULTS["SG_HOMES"],
        "warn_threshold_pct": DEFAULTS["WARN_PCT"],
        "critical_threshold_pct": DEFAULTS["CRIT_PCT"],
        "utilization_method": "PEAK_PCT95",
    }
    defaults.update(overrides)
    return defaults


def create_utilization_sample_payload(**overrides) -> dict:
    defaults = {
        "measured_at": "2026-09-30T18:00:00Z",
        "downstream_mbps": DEFAULTS["SAMPLE_DOWNSTREAM"],
        "upstream_mbps": DEFAULTS["SAMPLE_UPSTREAM"],
    }
    defaults.update(overrides)
    return defaults


def create_capacity_action_payload(**overrides) -> dict:
    defaults = {
        "action_type": "NODE_SPLIT",
        "expected_service_group_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_node_split_project_payload(**overrides) -> dict:
    defaults = {
        "child_count": DEFAULTS["CHILD_COUNT"],
        "min_homes_per_child": DEFAULTS["MIN_HOMES_PER_CHILD"],
        "max_homes_per_child": DEFAULTS["MAX_HOMES_PER_CHILD"],
    }
    defaults.update(overrides)
    return defaults


def create_migration_wave_payload(**overrides) -> dict:
    defaults = {
        "wave_code": DEFAULTS["WAVE_CODE"],
        "window_start": DEFAULTS["WAVE_START"],
        "window_end": DEFAULTS["WAVE_END"],
        "target_cpe_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_customer_premise_payload(**overrides) -> dict:
    defaults = {
        "premise_ref": DEFAULTS["PREMISE_REF"],
        "address": DEFAULTS["PREMISE_ADDRESS"],
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(**overrides) -> dict:
    defaults = {
        "model": DEFAULTS["CPE_MODEL"],
        "docsis_version": DEFAULTS["CPE_DOCSIS"],
        "capability_class": DEFAULTS["CPE_CAPABILITY"],
        "max_downstream_mbps": DEFAULTS["CPE_MAX_DOWNSTREAM"],
        "video_legacy": False,
    }
    defaults.update(overrides)
    return defaults


def create_speed_tier_payload(**overrides) -> dict:
    defaults = {
        "tier_code": DEFAULTS["TIER_CODE"],
        "downstream_mbps": DEFAULTS["TIER_DOWNSTREAM"],
        "upstream_mbps": DEFAULTS["TIER_UPSTREAM"],
        "min_capability_class": "D30",
        "min_upstream_config": "LEGACY",
    }
    defaults.update(overrides)
    return defaults


def create_provisioning_request_payload(**overrides) -> dict:
    defaults = {
        "speed_tier_id": "",
        "expected_customer_premise_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_refresh_campaign_payload(**overrides) -> dict:
    defaults = {
        "campaign_code": DEFAULTS["CAMPAIGN_CODE"],
        "target_capability_class": "D31",
    }
    defaults.update(overrides)
    return defaults


def create_congestion_complaint_payload(**overrides) -> dict:
    defaults = {
        "description": DEFAULTS["COMPLAINT_DESCRIPTION"],
        "plant_signal": 50,
        "home_signal": 30,
        "destination_signal": 20,
    }
    defaults.update(overrides)
    return defaults
