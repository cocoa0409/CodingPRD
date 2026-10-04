"""Payload factories — one per entity, input fields only (PRD §3).

System-managed fields (status, computed totals, scores, version, timestamps)
are never supplied by factories.
"""
import itertools

from .constants import WEEK_1_START

_counters = itertools.count(1)


def _next() -> int:
    return next(_counters)


def create_factory_payload(**overrides) -> dict:
    """PRD §3.1: code, region DOMESTIC|OVERSEAS, non-empty component_lines,
    weekly_capacity_units > 0."""
    n = _next()
    defaults = {
        "code": f"FAC-D{n}",
        "region": "DOMESTIC",
        "component_lines": ["FOAM", "FRAMES", "UPHOLSTERY"],
        "weekly_capacity_units": 100,
    }
    defaults.update(overrides)
    return defaults


def create_product_line_payload(**overrides) -> dict:
    """PRD §3.1: name, category, style_code, price_point_cents on the ladder."""
    n = _next()
    defaults = {
        "name": f"Alder Sofa Collection {n}",
        "category": "UPHOLSTERY",
        "price_point_cents": 89900,
        "style_code": f"ALD-SOFA-{n:02d}",
    }
    defaults.update(overrides)
    return defaults


def create_licensee_payload(**overrides) -> dict:
    """PRD §3.2: business_name required; royalty_rate /
    merchandising_standard_version / latest_audit_score optional with defaults."""
    n = _next()
    defaults = {"business_name": f"Summit Home Furnishings {n}"}
    defaults.update(overrides)
    return defaults


def create_territory_payload(**overrides) -> dict:
    """PRD §3.2: unique region_code, population_tier METRO|SUBURBAN|RURAL."""
    n = _next()
    defaults = {"region_code": f"T-R{n:03d}", "population_tier": "METRO"}
    defaults.update(overrides)
    return defaults


def create_retail_account_payload(**overrides) -> dict:
    """PRD §3.3: business_name, credit_limit_cents > 0."""
    n = _next()
    defaults = {
        "business_name": f"Metro Discount Furniture {n}",
        "credit_limit_cents": 5_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_distribution_center_payload(**overrides) -> dict:
    """PRD §3.6: code, supports_home_delivery, region_codes; daily_crew_units
    optional (defaults to 6, 1..20)."""
    n = _next()
    defaults = {
        "code": f"DC-K{n:03d}",
        "supports_home_delivery": True,
        "region_codes": ["T-SEA"],
    }
    defaults.update(overrides)
    return defaults


def create_allocation_cycle_payload(factory_id: str, **overrides) -> dict:
    """PRD §3.4: factory_id + midnight-aligned week_start."""
    defaults = {"factory_id": factory_id, "week_start": WEEK_1_START}
    defaults.update(overrides)
    return defaults


def create_order_payload(
    allocation_cycle_id: str,
    product_line_id: str,
    buyer_type: str = "LICENSEE",
    licensee_id=None,
    retail_account_id=None,
    quantity: int = 1,
    delivery_mode: str = "FREIGHT_TO_STORE",
    **overrides,
) -> dict:
    """PRD §3.5: buyer FK shape follows buyer_type (LICENSEE -> licensee_id,
    retail_account_id null; RETAIL_ACCOUNT -> the reverse)."""
    defaults = {
        "buyer_type": buyer_type,
        "licensee_id": licensee_id,
        "retail_account_id": retail_account_id,
        "allocation_cycle_id": allocation_cycle_id,
        "product_line_id": product_line_id,
        "quantity": quantity,
        "delivery_mode": delivery_mode,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(
    supply_order_id: str,
    dc_id: str,
    region_code: str,
    window_start: str,
    window_end: str,
    zone: str = "LOCAL",
    crew_units: int = 1,
    **overrides,
) -> dict:
    """PRD §3.6: licensee_id is derived from the order, never client-supplied."""
    defaults = {
        "supply_order_id": supply_order_id,
        "dc_id": dc_id,
        "zone": zone,
        "region_code": region_code,
        "window_start": window_start,
        "window_end": window_end,
        "crew_units": crew_units,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(
    supply_order_id: str,
    claim_type: str = "DEFECT",
    description: str = "Claim description",
    **overrides,
) -> dict:
    """PRD §3.7: supply_order_id, claim_type, free-text description."""
    defaults = {
        "supply_order_id": supply_order_id,
        "claim_type": claim_type,
        "description": description,
    }
    defaults.update(overrides)
    return defaults
