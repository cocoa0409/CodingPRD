"""Payload factories — one per write operation, input fields only.

Every monetary, tonnage and water figure is emitted as a JSON number, never as
a string.
"""
from .constants import TEST_DEFAULTS


class _Omit:
    """Sentinel: passing OMIT as an override removes the key from the payload."""

    def __repr__(self):  # pragma: no cover - debugging aid only
        return "OMIT"


OMIT = _Omit()


def _merge(defaults: dict, overrides: dict) -> dict:
    payload = dict(defaults)
    for key, value in overrides.items():
        if isinstance(value, _Omit):
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ─── Ranch (PRD §3.1) ─────────────────────────────────

def vineyard_payload(**overrides) -> dict:
    return _merge(
        {
            "name": TEST_DEFAULTS["VINEYARD_NAME"],
            "owner_legal_name": TEST_DEFAULTS["OWNER_LEGAL_NAME"],
            "ava_region": TEST_DEFAULTS["AVA_REGION"],
            "client_contact_email": TEST_DEFAULTS["CLIENT_CONTACT_EMAIL"],
        },
        overrides,
    )


# ─── Block (PRD §3.1) ─────────────────────────────────

def _block_defaults(vineyard_id: str) -> dict:
    """A 5-by-8-foot Cabernet planting on 12.5 acres — 1089 vines per acre."""
    return {
        "vineyard_id": vineyard_id,
        "block_code": "B-12",
        "variety": "CABERNET_SAUVIGNON",
        "clone": "FPS-08",
        "rootstock": "ROOTSTOCK_1103P",
        "trellis_system": "VSP",
        "planting_year": 2018,
        "vine_spacing_ft": 5.0,
        "row_spacing_ft": 8.0,
        "acres": 12.5,
    }


def block_payload(vineyard_id: str, **overrides) -> dict:
    """A 5-by-8-foot Cabernet planting on 12.5 acres — 1089 vines per acre."""
    return _merge(_block_defaults(vineyard_id), overrides)


def block_payload_b14(vineyard_id: str, **overrides) -> dict:
    """A 6-by-10-foot Chardonnay planting on 4.0 acres — 726 vines per acre."""
    defaults = _merge(
        _block_defaults(vineyard_id),
        {
            "block_code": "B-14",
            "variety": "CHARDONNAY",
            "clone": "FPS-04",
            "rootstock": "ROOTSTOCK_110R",
            "trellis_system": "SPRAWL",
            "planting_year": 2020,
            "vine_spacing_ft": 6.0,
            "row_spacing_ft": 10.0,
            "acres": 4.0,
        },
    )
    return _merge(defaults, overrides)


def block_payload_b16(vineyard_id: str, **overrides) -> dict:
    """A 7-by-9-foot Syrah planting on 3.6 acres — 691 vines per acre."""
    defaults = _merge(
        _block_defaults(vineyard_id),
        {
            "block_code": "B-16",
            "variety": "SYRAH",
            "clone": "FPS-07",
            "rootstock": "ROOTSTOCK_SO4",
            "trellis_system": "QUADRILATERAL_CORDON",
            "planting_year": 2019,
            "vine_spacing_ft": 7.0,
            "row_spacing_ft": 9.0,
            "acres": 3.6,
        },
    )
    return _merge(defaults, overrides)


# ─── Custom-farming agreement (PRD §3.2) ──────────────

def contract_payload(vineyard_id: str, **overrides) -> dict:
    return _merge(
        {
            "vineyard_id": vineyard_id,
            "per_acre_annual_fee": 950.00,
            "cost_pass_through_pct": 0.08,
            "quality_incentive_per_ton": 45.00,
            "quality_brix_threshold": 24.5,
            "period_overhead_pool": 1000.00,
            "period_start": "2026-01-01",
            "period_end": "2026-12-31",
        },
        overrides,
    )


def enroll_block_payload(block_id: str, contracted_acres: float, **overrides) -> dict:
    return _merge(
        {"block_id": block_id, "contracted_acres": contracted_acres}, overrides
    )


def activate_contract_payload(**overrides) -> dict:
    return _merge(
        {"client_signature_name": TEST_DEFAULTS["CLIENT_SIGNATURE_NAME"]}, overrides
    )


def settle_period_payload(settlement_mode: str, period_end_date: str, **overrides) -> dict:
    return _merge(
        {"settlement_mode": settlement_mode, "period_end_date": period_end_date},
        overrides,
    )


# ─── Farming plan (PRD §3.3) ──────────────────────────

def farming_plan_payload(block_id: str, **overrides) -> dict:
    """Per-acre lines 420.00 / 310.00 / 180.00 / 265.00 — 1,175.00 per acre."""
    return _merge(
        {
            "block_id": block_id,
            "plan_year": 2026,
            "quality_target": "PREMIUM",
            "pruning_budget_per_acre": 420.00,
            "canopy_budget_per_acre": 310.00,
            "irrigation_budget_per_acre": 180.00,
            "pest_budget_per_acre": 265.00,
            "seasonal_water_cap_inches": 9.000,
        },
        overrides,
    )


def submit_plan_payload(**overrides) -> dict:
    return _merge({"submission_note": "Ready for controller review."}, overrides)


def return_plan_payload(**overrides) -> dict:
    return _merge({"revision_note": "Trim the canopy line."}, overrides)


def approve_plan_payload(**overrides) -> dict:
    return _merge({"approval_note": "Approved for the crop year."}, overrides)


# ─── Labor crew (PRD §3.4) ────────────────────────────

def _crew_defaults() -> dict:
    """A twelve-worker PIECE_RATE crew at 0.65 dollars per vine."""
    return {
        "crew_name": "Cuadrilla Norte",
        "pay_structure": "PIECE_RATE",
        "crew_size": 12,
        "base_hourly_rate": 19.50,
        "piece_rate_per_vine": 0.65,
        "vines_per_hour_standard": 45.0,
        "task_capabilities": ["PRUNING", "SUCKERING", "LEAFING", "HARVEST"],
        "pest_certified": False,
        "crew_status": "ACTIVE",
    }


def crew_payload(**overrides) -> dict:
    """A twelve-worker PIECE_RATE crew at 0.65 dollars per vine."""
    return _merge(_crew_defaults(), overrides)


def hourly_crew_payload(**overrides) -> dict:
    """An eight-worker HOURLY crew at 22.00 dollars per hour."""
    defaults = _merge(
        _crew_defaults(),
        {
            "crew_name": "Cuadrilla Sur",
            "pay_structure": "HOURLY",
            "crew_size": 8,
            "base_hourly_rate": 22.00,
            "piece_rate_per_vine": 0.0,
            "vines_per_hour_standard": 40.0,
        },
    )
    return _merge(defaults, overrides)


# ─── Work order (PRD §3.4) ────────────────────────────

def work_order_payload(block_id: str, farming_plan_id: str, crew_id: str, **overrides) -> dict:
    return _merge(
        {
            "block_id": block_id,
            "farming_plan_id": farming_plan_id,
            "crew_id": crew_id,
            "task_type": "PRUNING",
            "scheduled_start": "2026-08-02T14:00:00Z",
            "scheduled_end": "2026-08-03T00:00:00Z",
            "planned_vines": 13000,
            "planned_hours": 10.0,
        },
        overrides,
    )


def complete_work_order_payload(actual_vines: int, actual_hours: float, **overrides) -> dict:
    return _merge({"actual_vines": actual_vines, "actual_hours": actual_hours}, overrides)


def cancel_work_order_payload(cancel_reason: str = "WEATHER", **overrides) -> dict:
    return _merge({"cancel_reason": cancel_reason}, overrides)


def payroll_payload(payroll_action: str, **overrides) -> dict:
    return _merge({"payroll_action": payroll_action}, overrides)


# ─── Irrigation (PRD §3.5) ────────────────────────────

def irrigation_event_payload(block_id: str, farming_plan_id: str, **overrides) -> dict:
    """The worked readings of the PRD: demand 1.008, shortfall 1.037, refill 0.519."""
    return _merge(
        {
            "block_id": block_id,
            "farming_plan_id": farming_plan_id,
            "scheduled_start": "2026-08-05T05:00:00Z",
            "scheduled_end": "2026-08-05T07:00:00Z",
            "et0_inches": 1.40,
            "crop_coefficient": 0.72,
            "soil_moisture_pct": 42.0,
            "field_capacity_pct": 60.0,
            "root_zone_depth_in": 36.0,
            "effective_rain_inches": 0.10,
            "water_unit_cost_per_acre_inch": 42.00,
        },
        overrides,
    )


def record_applied_payload(applied_inches: float, **overrides) -> dict:
    return _merge({"applied_inches": applied_inches}, overrides)


# ─── Pest scouting and sprays (PRD §3.6) ──────────────

def pest_observation_payload(**overrides) -> dict:
    """A 12.0 percent powdery-mildew count against a 5.0 threshold."""
    return _merge(
        {"pest_code": "POWDERY_MILDEW", "incidence_pct": 12.0, "severity_index": 3},
        overrides,
    )


def spray_record_payload(block_id: str, farming_plan_id: str,
                         pest_observation_id: str, **overrides) -> dict:
    """A 72-hour re-entry, 21-day pre-harvest product costing 812.50."""
    return _merge(
        {
            "block_id": block_id,
            "farming_plan_id": farming_plan_id,
            "pest_observation_id": pest_observation_id,
            "product_name": "Sulfur 90WDG",
            "active_ingredient": "Sulfur",
            "rei_hours": 72,
            "phi_days": 21,
            "rate_per_acre": 2.5,
            "material_cost": 812.50,
        },
        overrides,
    )


def apply_spray_payload(expected_block_version: int, **overrides) -> dict:
    return _merge(
        {
            "applicator_license_no": "CA-PCA-88210",
            "wind_speed_mph": 4.2,
            "expected_block_version": expected_block_version,
        },
        overrides,
    )


def verify_spray_payload(**overrides) -> dict:
    return _merge({"verification_note": "Record countersigned."}, overrides)


# ─── Yield estimates (PRD §3.7) ───────────────────────

def cluster_count_estimate_payload(**overrides) -> dict:
    """32 clusters per vine at a 0.42-pound historical cluster weight."""
    return _merge(
        {
            "method": "CLUSTER_COUNT",
            "sample_date": "2026-08-10",
            "avg_clusters_per_vine": 32.0,
            "avg_cluster_weight_lb": 0.42,
        },
        overrides,
    )


def berry_sample_estimate_payload(**overrides) -> dict:
    """95 berries per cluster at 1.35 grams, 30 days out — growth factor 1.120."""
    return _merge(
        {
            "method": "BERRY_SAMPLE",
            "sample_date": "2026-08-20",
            "avg_clusters_per_vine": 32.0,
            "berries_per_cluster": 95,
            "avg_berry_weight_g": 1.35,
            "days_to_harvest": 30,
        },
        overrides,
    )


# ─── Delivery windows and harvest loads (PRD §3.8) ────

def delivery_window_payload(**overrides) -> dict:
    return _merge(
        {
            "winery_name": TEST_DEFAULTS["WINERY_NAME"],
            "window_start": "2026-09-14T06:00:00Z",
            "window_end": "2026-09-14T18:00:00Z",
            "capacity_tons": 40.00,
        },
        overrides,
    )


def harvest_load_payload(block_id: str, crew_id: str, delivery_window_id: str,
                         expected_delivery_window_version: int, **overrides) -> dict:
    return _merge(
        {
            "block_id": block_id,
            "crew_id": crew_id,
            "delivery_window_id": delivery_window_id,
            "estimated_tons": 12.40,
            "delivery_eta": "2026-09-14T09:00:00Z",
            "expected_delivery_window_version": expected_delivery_window_version,
        },
        overrides,
    )


def dispatch_load_payload(gross_tons_at_dispatch: float = 13.10, **overrides) -> dict:
    return _merge({"gross_tons_at_dispatch": gross_tons_at_dispatch}, overrides)


def receive_load_payload(gross_tons: float = 13.10, tare_tons: float = 0.70,
                         mog_deduct_pct: float = 0.00,
                         brix_at_receipt: float = 25.1, **overrides) -> dict:
    return _merge(
        {
            "gross_tons": gross_tons,
            "tare_tons": tare_tons,
            "mog_deduct_pct": mog_deduct_pct,
            "brix_at_receipt": brix_at_receipt,
        },
        overrides,
    )


def reject_load_payload(rejection_reason: str = "MOG_EXCESS", **overrides) -> dict:
    return _merge({"rejection_reason": rejection_reason}, overrides)
