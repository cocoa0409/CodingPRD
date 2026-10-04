"""Payload factories — one per entity, input fields only.

Defaults cover the required input fields; optional fields are emitted only
when overridden so omission/default semantics stay testable.
"""
from . import constants as C


def create_brand_payload(**overrides) -> dict:
    """Brand create payload (name, legal_entity_name; equity_budget_bps optional)."""
    payload = {
        "name": "Multi-Use Brand",
        "legal_entity_name": "Multi-Use Products Co",
    }
    payload.update(overrides)
    return payload


def create_product_line_payload(**overrides) -> dict:
    """ProductLine create payload (line_code, name, target_channels; is_core optional)."""
    payload = {
        "line_code": "CORE",
        "name": "Core Multi-Use",
        "target_channels": ["HARDWARE"],
    }
    payload.update(overrides)
    return payload


def create_formulation_payload(**overrides) -> dict:
    """Formulation create payload (version_label, component_codes, voc_class; master_formulation_id optional)."""
    payload = {
        "version_label": "v1",
        "component_codes": ["C1", "C2", "C3", "C4"],
        "voc_class": "STANDARD",
    }
    payload.update(overrides)
    return payload


def create_contract_manufacturer_payload(**overrides) -> dict:
    """ContractManufacturer create payload (legal_name, site_country, capabilities)."""
    payload = {
        "legal_name": "Alpha Blending Co",
        "site_country": "US",
        "capabilities": ["BLENDING"],
    }
    payload.update(overrides)
    return payload


def create_confidentiality_grant_payload(*, manufacturer_id, formulation_id,
                                         **overrides) -> dict:
    """Grant create payload (manufacturer_id, formulation_id, component_scope, expires_on, grant_reason)."""
    payload = {
        "manufacturer_id": manufacturer_id,
        "formulation_id": formulation_id,
        "component_scope": ["C1", "C2"],
        "expires_on": C.GRANT_EXPIRY_FAR_FUTURE,
        "grant_reason": "PRODUCTION",
    }
    payload.update(overrides)
    return payload


def create_distributor_payload(*, home_market_id, **overrides) -> dict:
    """Distributor create payload (legal_name, home_market_id, channels_served, credit_limit_cents)."""
    payload = {
        "legal_name": "Ace Distribution",
        "home_market_id": home_market_id,
        "channels_served": ["HARDWARE"],
        "credit_limit_cents": 1000000,
    }
    payload.update(overrides)
    return payload


def create_market_payload(**overrides) -> dict:
    """Market create payload (country_code, name, registration_required, voc_regime, allowed_channels)."""
    payload = {
        "country_code": "US",
        "name": "United States",
        "registration_required": False,
        "voc_regime": "STANDARD",
        "allowed_channels": ["HARDWARE", "AUTOMOTIVE", "INDUSTRIAL", "MASS"],
    }
    payload.update(overrides)
    return payload


def create_market_registration_payload(*, market_id, product_line_id, formulation_id,
                                       **overrides) -> dict:
    """Registration create payload (market_id, product_line_id, formulation_id, expires_on)."""
    payload = {
        "market_id": market_id,
        "product_line_id": product_line_id,
        "formulation_id": formulation_id,
        "expires_on": C.REGISTRATION_EXPIRY_DEFAULT,
    }
    payload.update(overrides)
    return payload


def create_coverage_assignment_payload(*, market_id, product_line_id,
                                       expected_distributor_version,
                                       **overrides) -> dict:
    """Assignment create payload (OCC: expected_distributor_version required)."""
    payload = {
        "market_id": market_id,
        "product_line_id": product_line_id,
        "channel": "HARDWARE",
        "exclusive": False,
        "starts_on": C.DEFAULT_COVERAGE_START,
        "ends_on": C.DEFAULT_COVERAGE_END,
        "annual_quota_units": 1200,
        "expected_distributor_version": expected_distributor_version,
    }
    payload.update(overrides)
    return payload


def create_pack_format_payload(**overrides) -> dict:
    """PackFormat create payload (size_ml, delivery_system, channel_restrictions; case_pack_qty optional)."""
    payload = {
        "size_ml": 311,
        "delivery_system": "AEROSOL",
        "channel_restrictions": ["HARDWARE"],
        "case_pack_qty": 12,
    }
    payload.update(overrides)
    return payload


def create_price_list_payload(*, expected_pack_format_version, **overrides) -> dict:
    """Price list create payload (OCC: expected_pack_format_version required)."""
    payload = {
        "channel": "HARDWARE",
        "list_price_cents": 499,
        "map_price_cents": 300,
        "effective_from": C.DEFAULT_PRICE_EFFECTIVE_FROM,
        "effective_to": C.DEFAULT_PRICE_EFFECTIVE_TO,
        "expected_pack_format_version": expected_pack_format_version,
    }
    payload.update(overrides)
    return payload


def create_promotion_payload(*, product_line_id, **overrides) -> dict:
    """Promotion create payload (product_line_id, channel, discount_pct, starts_on, ends_on, funding_budget_cents)."""
    payload = {
        "product_line_id": product_line_id,
        "channel": "HARDWARE",
        "discount_pct": 10.00,
        "starts_on": "2026-10-01",
        "ends_on": "2026-10-31",
        "funding_budget_cents": 100000,
    }
    payload.update(overrides)
    return payload


def create_counterfeit_case_payload(*, market_id, **overrides) -> dict:
    """CounterfeitCase create payload (market_id, channel, severity; units_seized optional)."""
    payload = {
        "market_id": market_id,
        "channel": "HARDWARE",
        "severity": 3,
    }
    payload.update(overrides)
    return payload


def create_use_case_payload(*, submitter_ref, **overrides) -> dict:
    """UseCaseSubmission create payload (submitter_ref, title, description)."""
    payload = {
        "submitter_ref": submitter_ref,
        "title": "Loosened a bolt",
        "description": "Used it on a rusty bolt.",
    }
    payload.update(overrides)
    return payload


def create_sell_through_report_payload(*, coverage_assignment_id, period_month,
                                       units_sold, **overrides) -> dict:
    """Sell-through report payload (coverage_assignment_id, period_month, units_sold; units_returned optional)."""
    payload = {
        "coverage_assignment_id": coverage_assignment_id,
        "period_month": period_month,
        "units_sold": units_sold,
    }
    payload.update(overrides)
    return payload
