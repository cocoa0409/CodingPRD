"""Payload factories — one per entity, input fields only."""
import uuid

from .constants import (
    COSMETIC_DEDUCT_TABLE,
    COUNTERFEIT_DEVICE_BLOCKLIST,
    FUNCTIONAL_DEDUCT_TABLE,
    INSPECTION_FEE_CENTS,
    LOCK_DEDUCT_TABLE,
    MODEL_CATALOG_FLOOR_CENTS,
    STOLEN_DEVICE_BLOCKLIST,
    TEST_DEFAULTS,
    TRADE_IN_BASE_CENTS,
)

VALID_PROVENANCE_DIGEST = "a" * 64
ALT_PROVENANCE_DIGEST = "b" * 64
EVIDENCE_DIGEST = "b" * 64
BLOCKLIST_EVIDENCE_DIGEST = "d" * 64

# GLOBAL counter so every generated imei is distinct within a test run.
_IMEI_SEQ = [0]


def next_imei() -> str:
    """A fresh, distinct 15-digit imei that is on neither blocklist."""
    _IMEI_SEQ[0] += 1
    candidate = f"89012345678{_IMEI_SEQ[0]:04d}"
    while candidate in STOLEN_DEVICE_BLOCKLIST or candidate in COUNTERFEIT_DEVICE_BLOCKLIST:
        _IMEI_SEQ[0] += 1
        candidate = f"89012345678{_IMEI_SEQ[0]:04d}"
    return candidate


def unique_legal_name(prefix: str = "Refurb") -> str:
    return f"{prefix} {uuid.uuid4().hex[:12]}"


def create_seller_payload(**overrides) -> dict:
    defaults = {
        "legal_name": unique_legal_name(),
        "country_code": "US",
        "refurbishment_capacity_units": TEST_DEFAULTS["CAPACITY_UNITS"],
    }
    defaults.update(overrides)
    return defaults


def create_audit_record_payload(**overrides) -> dict:
    defaults = {
        "audit_scheduled_for": "2026-09-05T00:00:00Z",
        "audit_scope_note": "battery tear-down and screen swap",
        "declared_monthly_throughput": TEST_DEFAULTS["THROUGHPUT"],
    }
    defaults.update(overrides)
    return defaults


def audit_transition_payload(**overrides) -> dict:
    defaults = {
        "target_state": "PASSED",
        "audit_score": TEST_DEFAULTS["AUDIT_SCORE"],
        "auditor_user_id": "op_auditor",
    }
    defaults.update(overrides)
    return defaults


def create_listing_payload(**overrides) -> dict:
    defaults = {
        "model_code": "APL-IP13-128",
        "imei": next_imei(),
        "cosmetic_grade": "GOOD",
        "functional_grade": "MINOR_FAULTS",
        "battery_health_pct": TEST_DEFAULTS["BATTERY_HEALTH_PCT"],
        "carrier_lock_status": "UNLOCKED",
        "part_provenance": "OEM_EQUIVALENT",
        "provenance_doc_digest": VALID_PROVENANCE_DIGEST,
        "list_price_cents": TEST_DEFAULTS["LIST_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_grading_definition_payload(**overrides) -> dict:
    defaults = {
        "definition_code": f"DEF-{uuid.uuid4().hex[:8].upper()}",
        "cosmetic_thresholds": {"FLAWLESS": 97, "GOOD": 90, "FAIR": 75, "POOR": 50},
        "functional_thresholds": {"FULLY_FUNCTIONAL": 95, "MINOR_FAULTS": 80, "MAJOR_FAULTS": 60},
        "battery_floor_pct": 80,
        "effective_from": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_verification_payload(seller_id, listing_id, **overrides) -> dict:
    """A mystery-shop verification over a half-open window.

    PRD §3.4: "a scheduled window given by `verification_start` and
    `verification_end`. The window is half-open: `verification_end` must be
    strictly later than `verification_start` and is exclusive."  Tests that care
    about specific instants override both; the default pair is a legal window
    that collides with nothing.
    """
    defaults = {
        "seller_id": seller_id,
        "listing_id": listing_id,
        "rationale_code": "GRADE_GHOST",
        "ordered_cosmetic_grade": "GOOD",
        "verification_start": "2026-09-05T00:00:00Z",
        "verification_end": "2026-09-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def disclose_verification_payload(**overrides) -> dict:
    defaults = {
        "received_cosmetic_grade": "FAIR",
        "measured_battery_health_pct": 82,
        "verifier_user_id": "op_verifier",
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(**overrides) -> dict:
    """An explicitly-opened reservation.

    PRD §3.3: "The `activated_on` instant must not be later than the current
    logical clock instant", so a caller that does not name the activation
    instant gets one that is admitted whatever instant the clock currently
    reads.
    """
    defaults = {
        "warranty_period_days": 180,
        "reserved_units": 1,
        "unit_reserve_per_day_cents": 1800,
    }
    if "activated_on" not in overrides:
        from .constants import DEFAULT_CLOCK
        defaults["activated_on"] = DEFAULT_CLOCK
    defaults.update(overrides)
    return defaults


def file_claim_payload(listing_id, **overrides) -> dict:
    defaults = {
        "listing_id": listing_id,
        "claim_reason_code": "BATTERY_SWELL",
        "evidence_included": True,
    }
    defaults.update(overrides)
    return defaults


def evidence_payload(digest=EVIDENCE_DIGEST) -> dict:
    return {"diagnostic_evidence_digest": digest}


def adjudicate_payload(**overrides) -> dict:
    defaults = {
        "decision": "APPROVED",
        "resolution_type": "REPAIR",
        "resolution_obligation_cents": TEST_DEFAULTS["REPAIR_OBLIGATION_CENTS"],
        "adjudicator_user_id": "op_adjudicator",
    }
    defaults.update(overrides)
    return defaults


def route_return_payload(**overrides) -> dict:
    defaults = {
        "return_carrier": "CARRIER_A",
        "return_shipment_cents": TEST_DEFAULTS["RETURN_SHIPMENT_CENTS"],
        "return_shipment_start": "2026-09-06T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def trade_in_payload(**overrides) -> dict:
    defaults = {
        "customer_ref": f"cust_{uuid.uuid4().hex[:10]}",
        "submitted_model_code": "APL-IP13-128",
        "self_declared_cosmetic_grade": "FLAWLESS",
        "self_declared_functional_grade": "FULLY_FUNCTIONAL",
        "self_declared_battery_health_pct": 95,
        "self_declared_carrier_lock_status": "UNLOCKED",
    }
    defaults.update(overrides)
    return defaults


def inspection_payload(**overrides) -> dict:
    defaults = {
        "inspected_cosmetic_grade": "FAIR",
        "inspected_functional_grade": "MINOR_FAULTS",
        "inspected_battery_health_pct": 82,
        "inspected_carrier_lock_status": "UNLOCKED",
    }
    defaults.update(overrides)
    return defaults


def service_score_payload(seller_id, **overrides) -> dict:
    defaults = {"seller_id": seller_id, "section_opened_on": "2026-01-05T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def blocklist_payload(**overrides) -> dict:
    defaults = {"finding": "CONFIRMED_COUNTERFEIT", "evidence_digest": BLOCKLIST_EVIDENCE_DIGEST}
    defaults.update(overrides)
    return defaults


# --- Local quote computation (mirrors the pinned pricing order) -------------

def battery_deduct(health_pct: int) -> int:
    if health_pct >= 85:
        return 0
    if health_pct >= 80:
        return 2500
    if health_pct >= 70:
        return 6000
    return 12000


def provisional_quote(self_cosmetic, self_functional, self_battery, self_lock) -> int:
    value = (
        TRADE_IN_BASE_CENTS
        - COSMETIC_DEDUCT_TABLE[self_cosmetic]
        - FUNCTIONAL_DEDUCT_TABLE[self_functional]
        - battery_deduct(self_battery)
        - LOCK_DEDUCT_TABLE[self_lock]
    )
    return max(0, value)


def model_catalog_floor(model_code: str) -> int:
    return MODEL_CATALOG_FLOOR_CENTS[model_code]


def inspection_fee_cents() -> int:
    return INSPECTION_FEE_CENTS