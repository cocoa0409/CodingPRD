"""Payload factories — one per entity, request-input fields only.

Money is always a JSON number of whole cents.  Every timestamp the PRD
specifies as an instant is emitted as a full ISO-8601 UTC instant, never as a
bare calendar date.
"""

from .constants import CLOCK_STARTUP_UTC, TEST_DEFAULTS

# ---------------------------------------------------------------------------
# Reference configuration
# ---------------------------------------------------------------------------

JURISDICTION_PRESETS = {
    "NE-WEST": {
        "code": "NE-WEST",
        "name": "Nebraska West",
        "seal_required": False,
        "min_design_wind_speed_mph": 95,
        "seismic_design_category": "A",
        "permit_review_days": 0,
    },
    "IA-CENTRAL": {
        "code": "IA-CENTRAL",
        "name": "Iowa Central",
        "seal_required": True,
        "min_design_wind_speed_mph": 105,
        "seismic_design_category": "B",
        "permit_review_days": 21,
    },
    "CA-VALLEY": {
        "code": "CA-VALLEY",
        "name": "California Central Valley",
        "seal_required": True,
        "min_design_wind_speed_mph": 100,
        "seismic_design_category": "D",
        "permit_review_days": 30,
    },
}

GRAIN_PROFILE_PRESETS = {
    "CORN": {
        "grain_code": "CORN",
        "bulk_density_kg_per_m3": 721,
        "janssen_k_ratio": 0.42,
        "max_safe_moisture_pct": 15.0,
        "aeration_cfm_per_m3_base": 2.5,
        "drying_multiplier": 4.0,
    },
    "LOWK": {
        "grain_code": "LOWK",
        "bulk_density_kg_per_m3": 721,
        "janssen_k_ratio": 0.30,
        "max_safe_moisture_pct": 14.0,
        "aeration_cfm_per_m3_base": 2.2,
        "drying_multiplier": 3.5,
    },
    "DENSE": {
        "grain_code": "DENSE",
        "bulk_density_kg_per_m3": 1100,
        "janssen_k_ratio": 0.55,
        "max_safe_moisture_pct": 13.0,
        "aeration_cfm_per_m3_base": 2.8,
        "drying_multiplier": 4.5,
    },
    "RICE": {
        "grain_code": "RICE",
        "bulk_density_kg_per_m3": 579,
        "janssen_k_ratio": 0.50,
        "max_safe_moisture_pct": 13.0,
        "aeration_cfm_per_m3_base": 3.2,
        "drying_multiplier": 5.5,
    },
}

COATING_SPEC_PRESETS = {
    "G90": {
        "coating_code": "G90",
        "zinc_mass_g_per_m2": 275,
        "coating_cost_per_kg_cents": 31,
        "changeover_minutes": 90,
        "max_ambient_moisture_pct": 14.0,
    },
    "G115": {
        "coating_code": "G115",
        "zinc_mass_g_per_m2": 350,
        "coating_cost_per_kg_cents": 42,
        "changeover_minutes": 120,
        "max_ambient_moisture_pct": 18.0,
    },
    "G165": {
        "coating_code": "G165",
        "zinc_mass_g_per_m2": 500,
        "coating_cost_per_kg_cents": 58,
        "changeover_minutes": 150,
        "max_ambient_moisture_pct": 20.0,
    },
    "G210": {
        "coating_code": "G210",
        "zinc_mass_g_per_m2": 620,
        "coating_cost_per_kg_cents": 71,
        "changeover_minutes": 180,
        "max_ambient_moisture_pct": 22.0,
    },
}

ROLL_FORMING_LINE_PRESETS = {
    "LINE_A": {"line_code": "LINE_A", "max_gauge_mm": 3.0},
    "LINE_LOW": {"line_code": "LINE_LOW", "max_gauge_mm": 1.3},
    "LINE_MAX": {"line_code": "LINE_MAX", "max_gauge_mm": 6.0},
}

ENGINEER_PRESETS = {
    "PE-1001": {
        "name": "Dana Author",
        "license_number": "PE-1001",
        "licensed_jurisdiction_codes": ["IA-CENTRAL", "NE-WEST", "CA-VALLEY"],
    },
    "PE-1002": {
        "name": "Rex Sealer",
        "license_number": "PE-1002",
        "licensed_jurisdiction_codes": ["IA-CENTRAL", "NE-WEST", "CA-VALLEY"],
    },
    "PE-1003": {
        "name": "Nina Second",
        "license_number": "PE-1003",
        "licensed_jurisdiction_codes": ["IA-CENTRAL", "NE-WEST", "CA-VALLEY"],
    },
    "PE-9001": {
        "name": "Otto Outstate",
        "license_number": "PE-9001",
        "licensed_jurisdiction_codes": ["NE-WEST"],
    },
}


def create_jurisdiction_payload(preset="NE-WEST", **overrides) -> dict:
    payload = dict(JURISDICTION_PRESETS[preset])
    payload.update(overrides)
    return payload


def create_grain_profile_payload(preset="CORN", **overrides) -> dict:
    payload = dict(GRAIN_PROFILE_PRESETS[preset])
    payload.update(overrides)
    return payload


def create_coating_spec_payload(preset="G115", **overrides) -> dict:
    payload = dict(COATING_SPEC_PRESETS[preset])
    payload.update(overrides)
    return payload


def create_roll_forming_line_payload(preset="LINE_A", **overrides) -> dict:
    payload = dict(ROLL_FORMING_LINE_PRESETS[preset])
    payload.update(overrides)
    return payload


def create_engineer_payload(preset="PE-1001", **overrides) -> dict:
    payload = dict(ENGINEER_PRESETS[preset])
    payload.update(overrides)
    return payload


def create_dealer_payload(
    jurisdiction_id,
    name="Alpha Grain Systems",
    region_code="NE-01",
    credit_limit_cents=TEST_DEFAULTS["DEALER_CREDIT_LIMIT_CENTS"],
    program_tier="BASE",
    staging_slots=2,
    high_cube_access=True,
    **overrides,
) -> dict:
    payload = {
        "name": name,
        "region_code": region_code,
        "jurisdiction_id": jurisdiction_id,
        "credit_limit_cents": credit_limit_cents,
        "program_tier": program_tier,
        "staging_slots": staging_slots,
        "high_cube_access": high_cube_access,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Bin designs
# ---------------------------------------------------------------------------

# The canonical 12.0 m x 9.6 m bin used by most scenarios.
D1_GEOMETRY = {
    "diameter_m": 12.0,
    "eave_height_m": 9.6,
    "roof_pitch_deg": 30,
    "design_wind_speed_mph": 105,
    "moisture_pct": 14.0,
    "design_method": "ASD",
}


def create_bin_design_payload(
    dealer_id,
    jurisdiction_id,
    grain_profile_id,
    coating_spec_id,
    **overrides,
) -> dict:
    """Body for POST /bin-designs.

    The four foreign keys appear first and in the order the endpoint declares
    them, so left-to-right body resolution is observable.
    """
    payload = {
        "dealer_id": dealer_id,
        "jurisdiction_id": jurisdiction_id,
        "grain_profile_id": grain_profile_id,
        "coating_spec_id": coating_spec_id,
    }
    payload.update(D1_GEOMETRY)
    payload.update(overrides)
    return payload


def create_design_analysis_payload(design_method, expected_bin_design_version) -> dict:
    return {
        "design_method": design_method,
        "expected_bin_design_version": expected_bin_design_version,
    }


def request_revision_payload(revision_note="Add a roof ring and resubmit.") -> dict:
    return {"revision_note": revision_note}


def revise_bin_design_payload(**fields) -> dict:
    """Every field of a revision is optional; omitted fields keep their value."""
    return dict(fields)


# ---------------------------------------------------------------------------
# Dealer orders
# ---------------------------------------------------------------------------


def create_dealer_order_payload(
    dealer_id,
    bin_design_id,
    order_season="OFFSEASON",
    aeration_package="NONE",
    unload_system="GRAVITY",
    **overrides,
) -> dict:
    payload = {
        "dealer_id": dealer_id,
        "bin_design_id": bin_design_id,
        "order_season": order_season,
        "aeration_package": aeration_package,
        "unload_system": unload_system,
    }
    payload.update(overrides)
    return payload


def order_payment_payload(amount_cents: int) -> dict:
    """`amount_cents` is a whole-cent JSON number, never a string."""
    return {"amount_cents": amount_cents}


def assign_crew_payload(installation_crew_id) -> dict:
    return {"installation_crew_id": installation_crew_id}


def credit_limit_payload(credit_limit_cents: int) -> dict:
    return {"credit_limit_cents": credit_limit_cents}


# ---------------------------------------------------------------------------
# Coil, runs, freight, crews, failures
# ---------------------------------------------------------------------------


def create_coil_lot_payload(
    coating_spec_id,
    heat_number="H-70001",
    gauge_mm=TEST_DEFAULTS["COIL_GAUGE_MM"],
    received_kg=TEST_DEFAULTS["COIL_RECEIVED_KG"],
    **overrides,
) -> dict:
    payload = {
        "coating_spec_id": coating_spec_id,
        "heat_number": heat_number,
        "gauge_mm": gauge_mm,
        "received_kg": received_kg,
    }
    payload.update(overrides)
    return payload


def create_roll_forming_run_payload(
    roll_forming_line_id,
    coil_lot_id,
    dealer_order_id,
    window_start,
    window_end,
    planned_kg,
    **overrides,
) -> dict:
    payload = {
        "roll_forming_line_id": roll_forming_line_id,
        "coil_lot_id": coil_lot_id,
        "dealer_order_id": dealer_order_id,
        "window_start": window_start,
        "window_end": window_end,
        "planned_kg": planned_kg,
    }
    payload.update(overrides)
    return payload


def complete_run_payload(consumed_kg, scrap_kg) -> dict:
    return {"consumed_kg": consumed_kg, "scrap_kg": scrap_kg}


def create_freight_load_payload(
    dealer_id,
    expected_dealer_version,
    trailer_type="FLATBED",
    allocation_basis="WEIGHT",
    yard_window_start="2026-08-10T08:00:00Z",
    yard_window_end="2026-08-12T17:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "dealer_id": dealer_id,
        "trailer_type": trailer_type,
        "allocation_basis": allocation_basis,
        "yard_window_start": yard_window_start,
        "yard_window_end": yard_window_end,
        "expected_dealer_version": expected_dealer_version,
    }
    payload.update(overrides)
    return payload


def assign_order_to_load_payload(dealer_order_id) -> dict:
    return {"dealer_order_id": dealer_order_id}


def create_installation_crew_payload(
    dealer_id,
    crew_name="Alpha Erectors T3",
    certification_tier="T3",
    certified_until=TEST_DEFAULTS["CREW_CERTIFIED_UNTIL"],
    **overrides,
) -> dict:
    payload = {
        "dealer_id": dealer_id,
        "crew_name": crew_name,
        "certification_tier": certification_tier,
        "certified_until": certified_until,
    }
    payload.update(overrides)
    return payload


def create_field_failure_payload(
    dealer_order_id,
    failure_mode="SIDEWALL_BUCKLE",
    observed_load_kpa=10.0,
    measured_coating_loss_pct=10.0,
    service_years=4.0,
    **overrides,
) -> dict:
    payload = {
        "dealer_order_id": dealer_order_id,
        "failure_mode": failure_mode,
        "observed_load_kpa": observed_load_kpa,
        "measured_coating_loss_pct": measured_coating_loss_pct,
        "service_years": service_years,
    }
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601=CLOCK_STARTUP_UTC) -> dict:
    return {"to_iso8601": to_iso8601}
