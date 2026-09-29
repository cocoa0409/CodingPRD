"""Request payload builders.

Every builder returns a complete, contract-valid body and accepts ``**overrides``
so a test can bend exactly one field and leave the rest alone. Passing ``OMIT``
as an override value removes the key entirely, which is how a test exercises an
omitted optional field or a missing required one.

Two type disciplines are enforced here rather than at each call site. Pound,
percentage, chlorine, pH, turbidity and temperature figures are JSON numbers,
never strings. Instants are full ISO 8601 UTC timestamps, never date-only
strings, while ``code_date`` style values are plain dates - the contract asks
for a different kind of value in each place.
"""

from typing import Any, Dict, Optional

from . import constants as c

# Sentinel that removes a key from a payload instead of setting it.
OMIT = object()


def _build(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides to a default payload, dropping keys overridden with OMIT."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ── The logical clock ──────────────────────────────────────────────────────

def clock_payload(current_utc: str, **overrides: Any) -> Dict[str, Any]:
    """Body for setting the plant logical clock."""
    return _build({"current_utc": current_utc}, overrides)


# ── Products ───────────────────────────────────────────────────────────────

def product_payload(**overrides: Any) -> Dict[str, Any]:
    """The standing leafy product: romaine shred, hold-and-release required."""
    return _build(
        {
            "code": c.PRODUCT_CODE,
            "name": c.PRODUCT_NAME,
            "commodity_class": c.COMMODITY_LEAFY,
            "allergen_group": c.ALLERGEN_NONE,
            "min_dwell_seconds": c.PRODUCT_MIN_DWELL_SECONDS,
            "min_spin_rpm": c.PRODUCT_MIN_SPIN_RPM,
            "min_antimicrobial_ppm": c.PRODUCT_MIN_ANTIMICROBIAL_PPM,
            "base_shelf_life_days": c.PRODUCT_BASE_SHELF_LIFE_DAYS,
            "min_yield_pct": c.PRODUCT_MIN_YIELD_PCT,
            "hold_and_release_required": True,
        },
        overrides,
    )


def slaw_product_payload(**overrides: Any) -> Dict[str, Any]:
    """A second leafy product carrying the SULFITE allergen group."""
    return _build(
        {
            "code": "SLAW-MIX",
            "name": "Slaw Mix",
            "commodity_class": c.COMMODITY_LEAFY,
            "allergen_group": c.ALLERGEN_SULFITE,
            "min_dwell_seconds": 100,
            "min_spin_rpm": 850,
            "min_antimicrobial_ppm": 22.0,
            "base_shelf_life_days": 14,
            "min_yield_pct": 58.00,
            "hold_and_release_required": False,
        },
        overrides,
    )


def celery_product_payload(**overrides: Any) -> Dict[str, Any]:
    """A root product carrying the CELERY allergen group, for changeover work."""
    return _build(
        {
            "code": "CELR-DICE",
            "name": "Celery Dice",
            "commodity_class": c.COMMODITY_ROOT,
            "allergen_group": c.ALLERGEN_CELERY,
            "min_dwell_seconds": 120,
            "min_spin_rpm": 800,
            "min_antimicrobial_ppm": 25.0,
            "base_shelf_life_days": 12,
            "min_yield_pct": 60.00,
            "hold_and_release_required": False,
        },
        overrides,
    )


# ── Customer specification revisions ───────────────────────────────────────

def customer_spec_payload(expected_product_version: int, **overrides: Any) -> Dict[str, Any]:
    """The standing FOODSERVICE specification: 14 day cap, JULIAN code dates."""
    return _build(
        {
            "customer_code": c.SPEC_CUSTOMER_CODE,
            "channel": c.CHANNEL_FOODSERVICE,
            "max_shelf_life_days_offered": c.SPEC_MAX_SHELF_LIFE_DAYS_OFFERED,
            "min_remaining_shelf_life_days_at_ship": c.SPEC_MIN_REMAINING_SHELF_LIFE_DAYS,
            "atmosphere_required": c.ATMOSPHERE_MAP_LOW_O2,
            "case_net_weight_lb": c.SPEC_CASE_NET_WEIGHT_LB,
            "code_date_format": c.CODE_DATE_JULIAN,
            "expected_product_version": expected_product_version,
        },
        overrides,
    )


def retail_spec_payload(expected_product_version: int, **overrides: Any) -> Dict[str, Any]:
    """A RETAIL specification with CALENDAR code dates and lighter cases."""
    return _build(
        {
            "customer_code": "RTL-WEST",
            "channel": c.CHANNEL_RETAIL,
            "max_shelf_life_days_offered": 17,
            "min_remaining_shelf_life_days_at_ship": 12,
            "atmosphere_required": c.ATMOSPHERE_AIR,
            "case_net_weight_lb": 12.0,
            "code_date_format": c.CODE_DATE_CALENDAR,
            "expected_product_version": expected_product_version,
        },
        overrides,
    )


# ── Lines and wash systems ─────────────────────────────────────────────────

def line_payload(**overrides: Any) -> Dict[str, Any]:
    """The standing line L1: twelve components to strip, 200 RLU ATP limit."""
    return _build(
        {
            "line_code": c.LINE_CODE,
            "required_disassembly_component_count": c.LINE_REQUIRED_COMPONENTS,
            "max_atp_rlu": c.LINE_MAX_ATP_RLU,
        },
        overrides,
    )


def wash_system_payload(**overrides: Any) -> Dict[str, Any]:
    """The standing flume W1: 4000 working gallons, two concurrent runs."""
    return _build(
        {
            "system_code": c.WASH_SYSTEM_CODE,
            "water_volume_gal": c.WASH_WATER_VOLUME_GAL,
            "max_concurrent_runs": c.WASH_MAX_CONCURRENT_RUNS,
        },
        overrides,
    )


# ── Grower lots and raw receipts ───────────────────────────────────────────

def grower_lot_payload(**overrides: Any) -> Dict[str, Any]:
    """The standing lot: well water, no adjacent animals, negative preharvest."""
    return _build(
        {
            "grower_code": c.GROWER_CODE,
            "ranch_block": c.RANCH_BLOCK,
            "commodity_class": c.COMMODITY_LEAFY,
            "harvest_datetime": c.HARVEST_DATETIME,
            "water_source": c.WATER_WELL,
            "adjacent_animal_operation": False,
            "preharvest_test_result": c.PREHARVEST_NEGATIVE,
            "prior_rejected_receipt_count": 0,
        },
        overrides,
    )


def raw_receipt_payload(grower_lot_id: str, **overrides: Any) -> Dict[str, Any]:
    """The standing load: 42000 gross on 2000 tare, pulp 3.1 C, so IN_SPEC."""
    return _build(
        {
            "grower_lot_id": grower_lot_id,
            "received_at": c.RECEIPT_RECEIVED_AT,
            "pulp_temp_c": c.RECEIPT_PULP_TEMP_C,
            "gross_weight_lb": c.RECEIPT_GROSS_WEIGHT_LB,
            "tare_weight_lb": c.RECEIPT_TARE_WEIGHT_LB,
        },
        overrides,
    )


def disposition_payload(
    decision: str,
    trim_loss_lb: Optional[float] = None,
    override_justification: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A load disposition; the two optional fields appear only when supplied."""
    base: Dict[str, Any] = {"decision": decision}
    if trim_loss_lb is not None:
        base["trim_loss_lb"] = trim_loss_lb
    if override_justification is not None:
        base["override_justification"] = override_justification
    return _build(base, overrides)


# ── Wash-water readings and change-outs ────────────────────────────────────

def antimicrobial_reading_payload(reading_at: str, free_chlorine_ppm: float, **overrides: Any) -> Dict[str, Any]:
    """A wash-water reading; chemistry figures are numbers at their declared precision."""
    return _build(
        {
            "reading_at": reading_at,
            "free_chlorine_ppm": free_chlorine_ppm,
            "ph": 6.8,
            "orp_mv": 700,
            "turbidity_ntu": 1.2,
        },
        overrides,
    )


# ── Sanitation events ──────────────────────────────────────────────────────

def sanitation_event_payload(**overrides: Any) -> Dict[str, Any]:
    """An ordinary sanitation-shift clean, not an allergen changeover."""
    return _build(
        {
            "shift": c.SHIFT_SANITATION,
            "scheduled_for": c.SANITATION_SCHEDULED_FOR,
            "is_allergen_changeover": False,
        },
        overrides,
    )


def changeover_event_payload(**overrides: Any) -> Dict[str, Any]:
    """The documented allergen changeover clean between two allergen groups."""
    return _build(
        {
            "shift": c.SHIFT_SANITATION,
            "scheduled_for": c.SANITATION_SCHEDULED_FOR,
            "is_allergen_changeover": True,
        },
        overrides,
    )


def sanitation_submission_payload(**overrides: Any) -> Dict[str, Any]:
    """A completed clean: every component stripped, ATP well under the limit."""
    return _build(
        {
            "disassembled_component_count": c.LINE_REQUIRED_COMPONENTS,
            "atp_rlu": c.SANITATION_ATP_RLU,
            "allergen_swab_result": c.SWAB_NEGATIVE,
        },
        overrides,
    )


def outcome_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    """A PASS or FAIL verdict, used by sanitation validation and CA verification."""
    return _build({"outcome": outcome}, overrides)


# ── Environmental swabs ────────────────────────────────────────────────────

def environmental_swab_payload(**overrides: Any) -> Dict[str, Any]:
    """A product-contact swab for Listeria species at the declared site."""
    return _build(
        {
            "zone": c.ZONE_1,
            "site_code": "EMP-Z1-014",
            "organism": c.ORGANISM_LISTERIA_SPP,
            "collected_at": "2026-08-03T12:00:00Z",
        },
        overrides,
    )


def swab_result_payload(result: str, **overrides: Any) -> Dict[str, Any]:
    """A laboratory result recorded against an environmental swab."""
    return _build({"result": result}, overrides)


# ── Corrective actions ─────────────────────────────────────────────────────

def corrective_action_submission_payload(**overrides: Any) -> Dict[str, Any]:
    """The narrative submitted when work on a corrective action is complete."""
    return _build(
        {"action_taken": "Re-cleaned the shredder infeed and re-swabbed the zone."},
        overrides,
    )


# ── Processing runs ────────────────────────────────────────────────────────

def process_run_payload(
    line_id: str,
    product_id: str,
    customer_spec_id: str,
    wash_system_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """The standing planned run: a five-hour window on the morning shift."""
    return _build(
        {
            "line_id": line_id,
            "product_id": product_id,
            "customer_spec_id": customer_spec_id,
            "wash_system_id": wash_system_id,
            "planned_start_at": c.RUN_PLANNED_START_AT,
            "planned_end_at": c.RUN_PLANNED_END_AT,
            "crew_size": c.RUN_CREW_SIZE,
        },
        overrides,
    )


def close_payload(**overrides: Any) -> Dict[str, Any]:
    """The standing close report: compliant dwell, spin and atmosphere."""
    return _build(
        {
            "actual_dwell_seconds": c.CLOSE_DWELL_SECONDS,
            "spin_rpm": c.CLOSE_SPIN_RPM,
            "spin_seconds": c.CLOSE_SPIN_SECONDS,
            "atmosphere_actual": c.ATMOSPHERE_MAP_LOW_O2,
            "water_gal_used": c.CLOSE_WATER_GAL_USED,
            "cases_produced": c.CLOSE_CASES_PRODUCED,
        },
        overrides,
    )


# ── Lot consumption ────────────────────────────────────────────────────────

def lot_consumption_payload(
    raw_receipt_id: str,
    expected_process_run_version: int,
    consumed_lb: float = c.CONSUMED_LB,
    **overrides: Any,
) -> Dict[str, Any]:
    """Pounds drawn from a received load onto a run, with the run version."""
    return _build(
        {
            "raw_receipt_id": raw_receipt_id,
            "consumed_lb": consumed_lb,
            "expected_process_run_version": expected_process_run_version,
        },
        overrides,
    )


def void_payload(expected_process_run_version: int, **overrides: Any) -> Dict[str, Any]:
    """The version guard a void must carry."""
    return _build(
        {"expected_process_run_version": expected_process_run_version}, overrides
    )


# ── Hold records ───────────────────────────────────────────────────────────

def hold_record_payload(reason: str = c.REASON_HOLD_AND_RELEASE_TESTING, **overrides: Any) -> Dict[str, Any]:
    """A hold opened directly by a technician."""
    return _build({"reason": reason}, overrides)


def hold_sample_payload(latest_test_type: str = c.TEST_APC, **overrides: Any) -> Dict[str, Any]:
    """A micro sample submitted against a hold."""
    return _build({"latest_test_type": latest_test_type}, overrides)


def hold_result_payload(
    latest_test_result: str,
    latest_apc_cfu_g: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A laboratory result recorded against a hold; the plate count is optional."""
    base: Dict[str, Any] = {"latest_test_result": latest_test_result}
    if latest_apc_cfu_g is not None:
        base["latest_apc_cfu_g"] = latest_apc_cfu_g
    return _build(base, overrides)
