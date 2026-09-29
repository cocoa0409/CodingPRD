"""Request payload builders.

Each builder produces the smallest body the PRD declares for its endpoint and
lets a caller override or add any field.  Optional fields are omitted entirely
unless supplied, so "the field was not sent" and "the field was sent as null"
stay distinguishable — pass :data:`NULL` when a literal null is wanted.

Money is always an integer number of cents: never a string and never a float.
"""

from typing import Any, Optional, Sequence

from .constants import (
    BENZENE_BASIS,
    BENZENE_CAS,
    BENZENE_ENDPOINT,
    BENZENE_LEVEL,
    BENZENE_NAME,
    BPA_BASIS,
    BPA_CAS,
    BPA_ENDPOINT,
    BPA_LEVEL,
    BPA_NAME,
    CATEGORY_CONSUMER_GOOD,
    CHANNEL_RETAIL,
    LISTING_EFFECTIVE_DATE,
    MATERIAL_CLASS_RAW,
    METHOD_MODELED,
    PARTY_PRIVATE,
    ROUTE_ORAL,
    VIOLATION_FAILURE_TO_WARN,
)
from .types import Payload


class _Omit:
    """Sentinel meaning "leave this key out of the request body entirely"."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "<omitted>"


OMIT: Any = _Omit()
NULL: Any = None


def _body(**fields: Any) -> Payload:
    """Drop every omitted key, keep explicit nulls."""
    return {key: value for key, value in fields.items() if not isinstance(value, _Omit)}


# ─── Listed chemicals ─────────────────────────────────────────────────────────

def listed_chemical_payload(
    chemical_name: str,
    cas_number: str,
    endpoint_type: str,
    safe_harbor_basis: str,
    safe_harbor_level_ug_per_day: Any = OMIT,
    **overrides: Any,
) -> Payload:
    payload = _body(
        chemical_name=chemical_name,
        cas_number=cas_number,
        endpoint_type=endpoint_type,
        safe_harbor_basis=safe_harbor_basis,
        safe_harbor_level_ug_per_day=safe_harbor_level_ug_per_day,
    )
    payload.update(_body(**overrides))
    return payload


def bpa_payload(**overrides: Any) -> Payload:
    """Bisphenol A: a reproductive-harm chemical with a MADL of 0.5 ug/day."""
    return listed_chemical_payload(
        BPA_NAME, BPA_CAS, BPA_ENDPOINT, BPA_BASIS, BPA_LEVEL, **overrides
    )


def benzene_payload(**overrides: Any) -> Payload:
    """Benzene: a cancer chemical with an NSRL of 6.4 ug/day."""
    return listed_chemical_payload(
        BENZENE_NAME, BENZENE_CAS, BENZENE_ENDPOINT, BENZENE_BASIS, BENZENE_LEVEL,
        **overrides,
    )


def list_action(listing_effective_date: str = LISTING_EFFECTIVE_DATE, **overrides: Any) -> Payload:
    return action_payload("LIST", listing_effective_date=listing_effective_date, **overrides)


def revise_safe_harbor_action(
    safe_harbor_basis: Any = OMIT,
    safe_harbor_level_ug_per_day: Any = OMIT,
    **overrides: Any,
) -> Payload:
    return action_payload(
        "REVISE_SAFE_HARBOR",
        safe_harbor_basis=safe_harbor_basis,
        safe_harbor_level_ug_per_day=safe_harbor_level_ug_per_day,
        **overrides,
    )


# ─── Generic transition bodies ────────────────────────────────────────────────

def action_payload(action: str, **fields: Any) -> Payload:
    payload = {"action": action}
    payload.update(_body(**fields))
    return payload


# ─── Suppliers ────────────────────────────────────────────────────────────────

def supplier_payload(
    legal_name: str,
    contact_email: Any = OMIT,
    warranty_scope: Any = OMIT,
    pass_through_warning_obligation: Any = OMIT,
    indemnity_cap_cents: Any = OMIT,
    warranty_effective_from: Any = OMIT,
    warranty_effective_to: Any = OMIT,
    **overrides: Any,
) -> Payload:
    if isinstance(contact_email, _Omit):
        slug = "".join(ch.lower() for ch in legal_name if ch.isalnum()) or "supplier"
        contact_email = f"qa@{slug}.example"
    payload = _body(
        legal_name=legal_name,
        contact_email=contact_email,
        warranty_scope=warranty_scope,
        pass_through_warning_obligation=pass_through_warning_obligation,
        indemnity_cap_cents=indemnity_cap_cents,
        warranty_effective_from=warranty_effective_from,
        warranty_effective_to=warranty_effective_to,
    )
    payload.update(_body(**overrides))
    return payload


# ─── Materials and the bill of materials ──────────────────────────────────────

def material_payload(
    material_code: str,
    supplier_id: str,
    material_class: str = MATERIAL_CLASS_RAW,
    parent_material_id: Any = OMIT,
    parent_mass_fraction: Any = OMIT,
    naturally_occurring_claim: Any = OMIT,
    **overrides: Any,
) -> Payload:
    payload = _body(
        material_code=material_code,
        material_class=material_class,
        supplier_id=supplier_id,
        parent_material_id=parent_material_id,
        parent_mass_fraction=parent_mass_fraction,
        naturally_occurring_claim=naturally_occurring_claim,
    )
    payload.update(_body(**overrides))
    return payload


def material_chemical_payload(
    chemical_id: str, declared_concentration_ppm: Any, **overrides: Any
) -> Payload:
    payload = _body(
        chemical_id=chemical_id,
        declared_concentration_ppm=declared_concentration_ppm,
    )
    payload.update(_body(**overrides))
    return payload


def report_result_action(
    lab_name: str = "Pacific Analytical",
    lab_result_ppm: Any = OMIT,
    lab_loq_ppm: Any = OMIT,
    **overrides: Any,
) -> Payload:
    return action_payload(
        "REPORT_RESULT",
        lab_name=lab_name,
        lab_result_ppm=lab_result_ppm,
        lab_loq_ppm=lab_loq_ppm,
        **overrides,
    )


def record_response_action(response_completeness: Any = OMIT, **overrides: Any) -> Payload:
    return action_payload(
        "RECORD_RESPONSE", response_completeness=response_completeness, **overrides
    )


# ─── Products ─────────────────────────────────────────────────────────────────

def product_payload(
    sku: str,
    product_name: str = "Compliance Widget",
    product_category: str = CATEGORY_CONSUMER_GOOD,
    distribution_channels: Any = None,
    label_area_sq_in: float = 10.0,
    annual_units: int = 100,
    occupancy_type: Any = OMIT,
    **overrides: Any,
) -> Payload:
    if distribution_channels is None:
        distribution_channels = [CHANNEL_RETAIL]
    payload = _body(
        sku=sku,
        product_name=product_name,
        product_category=product_category,
        distribution_channels=distribution_channels,
        label_area_sq_in=label_area_sq_in,
        annual_units=annual_units,
        occupancy_type=occupancy_type,
    )
    payload.update(_body(**overrides))
    return payload


def component_payload(
    material_id: str,
    quantity_grams_per_unit: Any = 0.25,
    contact_factor: Any = 0.5,
    supersedes_component_id: Any = OMIT,
    **overrides: Any,
) -> Payload:
    payload = _body(
        material_id=material_id,
        quantity_grams_per_unit=quantity_grams_per_unit,
        contact_factor=contact_factor,
        supersedes_component_id=supersedes_component_id,
    )
    payload.update(_body(**overrides))
    return payload


# ─── Exposure assessments ─────────────────────────────────────────────────────

def assessment_payload(
    chemical_id: str,
    method: str = METHOD_MODELED,
    route: str = ROUTE_ORAL,
    uses_per_day: Any = 1.0,
    **overrides: Any,
) -> Payload:
    payload = _body(
        chemical_id=chemical_id,
        method=method,
        route=route,
        uses_per_day=uses_per_day,
    )
    payload.update(_body(**overrides))
    return payload


def reject_action(review_note: Any = "Recompute the dermal absorption term", **overrides: Any) -> Payload:
    return action_payload("REJECT", review_note=review_note, **overrides)


# ─── Warning determinations and placements ────────────────────────────────────

def determination_payload(
    product_id: str,
    assessment_id: str,
    decision: str,
    expected_product_version: Any,
    **overrides: Any,
) -> Payload:
    payload = _body(
        product_id=product_id,
        assessment_id=assessment_id,
        decision=decision,
        expected_product_version=expected_product_version,
    )
    payload.update(_body(**overrides))
    return payload


def placement_payload(
    channel: str,
    effective_from: str,
    effective_to: Any = OMIT,
    placement_detail: str = "Back panel, lower left",
    catalog_page_ref: Any = OMIT,
    internet_display_position: Any = OMIT,
    **overrides: Any,
) -> Payload:
    payload = _body(
        channel=channel,
        effective_from=effective_from,
        effective_to=effective_to,
        placement_detail=placement_detail,
        catalog_page_ref=catalog_page_ref,
        internet_display_position=internet_display_position,
    )
    payload.update(_body(**overrides))
    return payload


# ─── Notices and settlements ──────────────────────────────────────────────────

def notice_payload(
    product_id: str,
    chemical_id: str,
    earliest_violation_date: str,
    served_at: str,
    noticing_party_name: str = "Coastal Watch Alliance",
    noticing_party_type: str = PARTY_PRIVATE,
    alleged_violation_type: str = VIOLATION_FAILURE_TO_WARN,
    alleged_units: int = 4000,
    **overrides: Any,
) -> Payload:
    payload = _body(
        product_id=product_id,
        chemical_id=chemical_id,
        noticing_party_name=noticing_party_name,
        noticing_party_type=noticing_party_type,
        alleged_violation_type=alleged_violation_type,
        alleged_units=alleged_units,
        earliest_violation_date=earliest_violation_date,
        served_at=served_at,
    )
    payload.update(_body(**overrides))
    return payload


def settlement_payload(
    requested_attorney_fees_cents: int,
    expected_notice_version: Any,
    reformulation_commitment: Any = OMIT,
    **overrides: Any,
) -> Payload:
    payload = _body(
        requested_attorney_fees_cents=int(requested_attorney_fees_cents),
        expected_notice_version=expected_notice_version,
        reformulation_commitment=reformulation_commitment,
    )
    payload.update(_body(**overrides))
    return payload


def dismiss_action(
    evaluation_note: str = "No listed-chemical exposure above safe harbor at the alleged dates",
    **overrides: Any,
) -> Payload:
    return action_payload("DISMISS", evaluation_note=evaluation_note, **overrides)


# ─── Reformulation projects ───────────────────────────────────────────────────

def reformulation_payload(
    product_id: str,
    chemical_id: str,
    material_chemical_id: str,
    target_concentration_ppm: Any,
    planned_start_date: str,
    planned_end_date: str,
    **overrides: Any,
) -> Payload:
    payload = _body(
        product_id=product_id,
        chemical_id=chemical_id,
        material_chemical_id=material_chemical_id,
        target_concentration_ppm=target_concentration_ppm,
        planned_start_date=planned_start_date,
        planned_end_date=planned_end_date,
    )
    payload.update(_body(**overrides))
    return payload


# ─── Pagination query helpers ─────────────────────────────────────────────────

def page(limit: Any = OMIT, offset: Any = OMIT, **filters: Any) -> Payload:
    query = _body(limit=limit, offset=offset)
    query.update(_body(**filters))
    return query


def channels(*names: str) -> Sequence[str]:
    return list(names)
