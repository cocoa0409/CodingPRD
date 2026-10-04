"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_licensee_payload(**overrides) -> dict:
    n = _seq()
    defaults = {"name": f"Licensee-{n}", "legal_entity_code": f"LE-{n}"}
    defaults.update(overrides)
    return defaults


def create_host_venue_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"Venue-{n}",
        "venue_type": "GROCERY",
        "open_time_utc": "06:00",
        "close_time_utc": "22:00",
        "access_restricted": False,
        "max_equipment_footprint_units": 100,
        "security_badge_required": False,
    }
    defaults.update(overrides)
    return defaults


def create_license_agreement_payload(licensee_id, venue_id, **overrides) -> dict:
    defaults = {
        "licensee_id": licensee_id,
        "venue_id": venue_id,
        "royalty_tiers": [{"threshold_cents": 0, "rate_bps": 300}],
        "royalty_basis": "ACCRUAL",
        "term_start_date": "2026-09-01",
        "term_end_date": "2027-08-31",
    }
    defaults.update(overrides)
    return defaults


def create_store_payload(**overrides) -> dict:
    n = _seq()
    defaults = {"store_code": f"ST-{n}", "equipment_footprint_units": 40}
    defaults.update(overrides)
    return defaults


def create_product_item_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "sku": f"SKU-{n}",
        "name": f"Product-{n}",
        "category": "FOOD",
        "proprietary": False,
        "venue_type_restrictions": [],
        "unit_cost_cents": 500,
        "case_pack_units": 1,
        "footprint_units": 0,
    }
    defaults.update(overrides)
    return defaults


def create_assortment_item_payload(product_item_id, **overrides) -> dict:
    defaults = {"product_item_id": product_item_id, "par_level": 50}
    defaults.update(overrides)
    return defaults


def create_distributor_payload(**overrides) -> dict:
    n = _seq()
    defaults = {"name": f"Distributor-{n}", "lead_time_days": 2}
    defaults.update(overrides)
    return defaults


def create_supply_order_payload(distributor_id, **overrides) -> dict:
    defaults = {"distributor_id": distributor_id, "auto_replenish": False}
    defaults.update(overrides)
    return defaults


def create_employee_payload(**overrides) -> dict:
    n = _seq()
    defaults = {"full_name": f"Employee-{n}", "role_tag": "BARISTA"}
    defaults.update(overrides)
    return defaults


def create_certification_payload(**overrides) -> dict:
    defaults = {"program_code": "BARISTA_CORE"}
    defaults.update(overrides)
    return defaults


def create_sales_report_payload(**overrides) -> dict:
    defaults = {
        "period_start_date": "2026-09-01",
        "period_end_date": "2026-09-14",
        "gross_sales_cents": 1000,
        "returns_cents": 0,
        "loyalty_redemption_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_royalty_statement_payload(expected_agreement_version, **overrides) -> dict:
    defaults = {
        "period_start_date": "2026-09-01",
        "period_end_date": "2026-09-30",
        "expected_agreement_version": expected_agreement_version,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(**overrides) -> dict:
    defaults = {
        "scheduled_start_utc": "2026-09-02T10:00:00Z",
        "scheduled_end_utc": "2026-09-02T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_loyalty_member_payload(**overrides) -> dict:
    n = _seq()
    defaults = {"email": f"member-{n}@example.com"}
    defaults.update(overrides)
    return defaults


def create_promotion_campaign_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"Campaign-{n}",
        "start_date": "2026-10-01",
        "end_date": "2026-10-10",
        "discount_pct": 10,
        "floor_price_cents": 100,
    }
    defaults.update(overrides)
    return defaults
