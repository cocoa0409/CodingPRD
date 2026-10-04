"""Payload factories — one per entity, input (source: input) fields only.

Defaults form a coherent happy path: an off-peak requested_ship_date, a drop
window reachable from the default logical clock (2026-09-01T00:00:00Z), and
values that satisfy every PRD constraint (window ordering, dtc <= total,
capacity within window duration, MOQ met or controllable by the caller).

Note on uniqueness: base_sku must be unique across product lines and windows
must not overlap on a station_code, so tests creating more than one line or
slot MUST override base_sku / station_code (and windows) explicitly.
"""

# ---------------------------------------------------------------------------
# Dealer + authorization
# ---------------------------------------------------------------------------
DEALER_DEFAULTS = {
    "legal_name": "Standard Dealer Co",
    "storefront_address": "10 Main St",
    "region_code": "TX-CT",
    "sell_through_pct": 50,
    "tenure_years": 5,
    # tier and credit_limit_cents intentionally omitted: the PRD defaults them
    # to STANDARD and 500000 when absent.
}


def create_dealer_payload(**overrides) -> dict:
    payload = dict(DEALER_DEFAULTS)
    payload.update(overrides)
    return payload


APPLICATION_DEFAULTS = {
    "has_physical_storefront": True,
    "storefront_sqft": 1500,
    "document_refs": ["doc-std"],
}


def create_dealer_application_payload(dealer_id: str, **overrides) -> dict:
    payload = dict(APPLICATION_DEFAULTS)
    payload["dealer_id"] = dealer_id
    payload.update(overrides)
    return payload


def schedule_inspection_payload(inspector_user_id: str = "fi-1", **overrides) -> dict:
    payload = {
        "inspector_user_id": inspector_user_id,
        "window_start": "2026-09-02T09:00:00Z",
        "window_end": "2026-09-02T11:00:00Z",
    }
    payload.update(overrides)
    return payload


def record_inspection_payload(outcome: str = "PASSED", brand_presentation_score: int = 85) -> dict:
    return {"outcome": outcome, "brand_presentation_score": brand_presentation_score}


def verify_documents_payload(outcome: str = "VERIFIED") -> dict:
    return {"outcome": outcome}


def decide_application_payload(decision: str = "APPROVE", decision_reason: str = "ok") -> dict:
    return {"decision": decision, "decision_reason": decision_reason}


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------
ENFORCEMENT_CASE_DEFAULTS = {
    "marketplace": "AMAZON",
    "seller_handle": "reseller-1",
    "listing_url": "https://marketplace.example.com/listing/1",
    # matched_dealer_id omitted by default (unattributed listing).
}


def create_enforcement_case_payload(**overrides) -> dict:
    payload = dict(ENFORCEMENT_CASE_DEFAULTS)
    payload.update(overrides)
    return payload


def resolve_case_payload(outcome: str = "CONFIRMED_VIOLATION", **overrides) -> dict:
    """Resolve payload. For a matched CONFIRMED_VIOLATION pass
    infraction_category=... and expected_dealer_version=... via overrides."""
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def overturn_case_payload(reason: str = "appeal granted", **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Catalog: product lines and colorway drops
# ---------------------------------------------------------------------------
PRODUCT_LINE_DEFAULTS = {
    "name": "Rambler Std",
    "category": "DRINKWARE",
    "base_sku": "RAMSTD",
    "base_custom_price_cents": 3000,
    "map_price_cents": 3499,
    "min_custom_quantity": 5,
    "warranty_months_lid": 24,
    "warranty_months_insulation": 36,
    "warranty_months_hardware": 12,
}


def create_product_line_payload(**overrides) -> dict:
    payload = dict(PRODUCT_LINE_DEFAULTS)
    payload.update(overrides)
    return payload


COLORWAY_DROP_DEFAULTS = {
    "color_name": "Standard Navy",
    "pantone_code": "PMS 533",
    "drop_type": "STANDARD",
    "total_units": 3000,
    "dtc_reserved_units": 500,
    "dealer_unit_price_cents": 1800,
    "allocation_opens_at": "2026-09-05T00:00:00Z",
    "allocation_closes_at": "2026-09-20T00:00:00Z",
    "go_live_at": "2026-10-01T00:00:00Z",
    "sales_end_at": "2026-12-31T00:00:00Z",
}


def create_colorway_drop_payload(product_line_id: str, **overrides) -> dict:
    payload = dict(COLORWAY_DROP_DEFAULTS)
    payload["product_line_id"] = product_line_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Launch allocations
# ---------------------------------------------------------------------------
def create_launch_allocation_payload(dealer_id: str, drop_id: str,
                                     requested_units: int = 5, **overrides) -> dict:
    payload = {
        "dealer_id": dealer_id,
        "drop_id": drop_id,
        "requested_units": requested_units,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Customization orders and artwork proofs
# ---------------------------------------------------------------------------
CUSTOMIZATION_ORDER_DEFAULTS = {
    "buyer_type": "INDIVIDUAL",
    "buyer_ref": "buyer-std",
    "quantity": 10,
    "declared_color_count": 1,
    "declared_placement_count": 1,
    "print_technology": "LASER",
    "requested_ship_date": "2026-09-16T00:00:00Z",
}


def create_customization_order_payload(product_line_id: str, colorway_drop_id: str,
                                       **overrides) -> dict:
    payload = dict(CUSTOMIZATION_ORDER_DEFAULTS)
    payload["product_line_id"] = product_line_id
    payload["colorway_drop_id"] = colorway_drop_id
    payload.update(overrides)
    return payload


ARTWORK_PROOF_DEFAULTS = {
    "artwork_file_ref": "s3://art/std-v1.ai",
    "color_count": 1,
    "placement_count": 1,
    "pantone_codes": ["PMS 533"],
}


def create_artwork_proof_payload(order_id: str, **overrides) -> dict:
    payload = dict(ARTWORK_PROOF_DEFAULTS)
    payload["order_id"] = order_id
    payload.update(overrides)
    return payload


def request_return_payload(reason: str = "DEFECT", affected_unit_count: int = 1,
                           **overrides) -> dict:
    payload = {"reason": reason, "affected_unit_count": affected_unit_count}
    payload.update(overrides)
    return payload


def decide_return_payload(decision: str = "APPROVE", **overrides) -> dict:
    """Decide-return payload. For APPROVE pass resolution=... via overrides."""
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def complete_production_payload(qc_outcome: str = "PASS") -> dict:
    return {"qc_outcome": qc_outcome}


# ---------------------------------------------------------------------------
# Print slots
# ---------------------------------------------------------------------------
PRINT_SLOT_DEFAULTS = {
    "station_code": "L-C1",
    "technology": "LASER",
    "window_start": "2026-09-14T09:00:00Z",
    "window_end": "2026-09-14T12:00:00Z",
    "capacity_minutes": 180,
}


def create_print_slot_payload(**overrides) -> dict:
    payload = dict(PRINT_SLOT_DEFAULTS)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Warranty claims
# ---------------------------------------------------------------------------
WARRANTY_CLAIM_DEFAULTS = {
    "claim_source": "DTC",
    "buyer_ref": "buyer-std",
    "serial_number": "S-1",
    "component": "LID",
    "failure_description": "seal failed",
    "purchase_date": "2026-06-01T00:00:00Z",
}


def create_warranty_claim_payload(**overrides) -> dict:
    """Warranty claim payload. Defaults describe an order-less DTC claim
    (product_line_id must be supplied via overrides). For a DEALER-source
    claim pass claim_source="DEALER" and dealer_id=...; for an order-anchored
    claim pass order_id=... and omit purchase_date."""
    payload = dict(WARRANTY_CLAIM_DEFAULTS)
    payload.update(overrides)
    return payload


def decide_claim_payload(outcome: str = "APPROVE_REPAIR",
                         decision_reason: str = "covered") -> dict:
    return {"outcome": outcome, "decision_reason": decision_reason}
