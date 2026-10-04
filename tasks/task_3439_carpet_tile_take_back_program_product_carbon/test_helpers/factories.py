"""Payload factories — one per entity, input fields only (PRD §3).

Conventions:
- Required foreign keys and the optimistic-concurrency version fields
  (expected_collection_version / expected_site_version, PRD §2.7) are
  positional parameters — they have no safe default.
- Optional input fields (claim_intent, manufacturing_target_id, claim_id,
  verifier_org, findings_count) are omitted unless passed as overrides, so the
  PRD's server-side default behavior is exercised by default.
- Default scalar values are ordinary valid test inputs; where a test needs a
  specific carbon factor, supplier name, mass, or area it passes it explicitly.
"""
from .constants import (
    BASE_PRICE_CENTS_PER_M2,  # noqa: F401  (re-exported convenience for tests)
    TILE_MASS_KG_PER_M2,
)


# ---------------------------------------------------------------------------
# ProductCollection (PRD §3.1)
# ---------------------------------------------------------------------------
def create_collection_payload(**overrides) -> dict:
    payload = {
        "name": "Cirrus",
        "pattern_code": "CIR",
        "backing_type": "STANDARD",
        "lifecycle_boundary": "CRADLE_TO_GRAVE",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TileBatch (PRD §3.2)
# ---------------------------------------------------------------------------
def create_batch_payload(**overrides) -> dict:
    payload = {
        "dye_lot_code": "DL-100",
        "production_date": "2026-09-05T00:00:00Z",
        "produced_m2": 100,
        "mfg_intensity_kgco2e_per_m2": 1.2,
        "delta_e": 0.4,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# FeedstockLot (PRD §3.2) — supplier_name and carbon_factor are test inputs;
# the unvalued program constants of the sort cascade never appear here.
# ---------------------------------------------------------------------------
def create_feedstock_lot_payload(**overrides) -> dict:
    payload = {
        "supplier_name": "NETCO",
        "source_type": "RECLAIMED_FISHING_NET",
        "quantity_kg": 200,
        "carbon_factor_kgco2e_per_kg": 0.50,
    }
    payload.update(overrides)
    return payload


def create_virgin_lot_payload(**overrides) -> dict:
    """Convenience for the virgin half of a two-lot mix."""
    payload = {
        "supplier_name": "POLYCO",
        "source_type": "VIRGIN",
        "quantity_kg": 200,
        "carbon_factor_kgco2e_per_kg": 2.10,
    }
    payload.update(overrides)
    return payload


def create_qc_payload(outcome: str = "PASS", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_allocate_payload(batch_id: str, quantity_kg, **overrides) -> dict:
    payload = {"batch_id": batch_id, "quantity_kg": quantity_kg}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# CustomerSite (PRD §3.3) — contractor_name defaults to the shared installer
# identity so make_installer_headers(site["contractor_name"]) gates succeed.
# ---------------------------------------------------------------------------
def create_site_payload(**overrides) -> dict:
    payload = {
        "contractor_name": "inst-bob",
        "address": "1 Harbor Way",
        "install_window_start": "2026-09-02T00:00:00Z",
        "install_window_end": "2026-09-03T00:00:00Z",
        "installation_system": "CONVENTIONAL",
        "adhesive_free_certified": False,
        "cert_expires_on": "2027-01-01T00:00:00Z",
        "annual_replacement_budget_cents": 1_000_000,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# InstalledZone (PRD §3.3)
# ---------------------------------------------------------------------------
def create_zone_payload(batch_id: str, **overrides) -> dict:
    payload = {
        "batch_id": batch_id,
        "zone_code": "Z-1",
        "area_m2": 10,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ReplacementOrder (PRD §3.4) — expected_site_version is mandatory (PRD §2.7).
# ---------------------------------------------------------------------------
def create_replacement_order_payload(
    site_id: str, zone_id: str, expected_site_version: int, **overrides
) -> dict:
    payload = {
        "site_id": site_id,
        "zone_id": zone_id,
        "reason": "WEAR",
        "new_zone_code": "Z-1R",
        "expected_site_version": expected_site_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TakeBackRequest (PRD §3.5)
# ---------------------------------------------------------------------------
def create_takeback_request_payload(site_id: str, collection_id: str, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "collection_id": collection_id,
        "condition_grade": "B",
        "declared_area_m2": 40,
    }
    payload.update(overrides)
    return payload


def create_schedule_payload(**overrides) -> dict:
    payload = {
        "pickup_window_start": "2026-09-12T00:00:00Z",
        "pickup_window_end": "2026-09-13T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_collect_payload(collected_kg=160, **overrides) -> dict:
    payload = {"collected_kg": collected_kg}
    payload.update(overrides)
    return payload


def create_sort_payload(**overrides) -> dict:
    payload = {
        "reuse_kg": 40,
        "depolymerize_kg": 80,
        "downcycle_kg": 40,
        "landfill_kg": 0,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PCFReport (PRD §3.6) — expected_collection_version is mandatory (PRD §2.7).
# ---------------------------------------------------------------------------
def create_pcf_report_payload(
    collection_id: str, expected_collection_version: int, **overrides
) -> dict:
    payload = {
        "collection_id": collection_id,
        "period_start": "2026-09-01T00:00:00Z",
        "period_end": "2026-10-01T00:00:00Z",
        "boundary": "CRADLE_TO_GATE",
        "expected_collection_version": expected_collection_version,
    }
    payload.update(overrides)
    return payload


def create_verification_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# CarbonClaim (PRD §3.7)
# ---------------------------------------------------------------------------
def create_carbon_claim_payload(collection_id: str, report_id: str, **overrides) -> dict:
    payload = {
        "collection_id": collection_id,
        "report_id": report_id,
        "claim_type": "CARBON_NEUTRAL",
        "claimed_volume_m2": 50,
        "boundary": "CRADLE_TO_GATE",
    }
    payload.update(overrides)
    return payload


def create_review_payload(decision: str = "APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_offset_payload(**overrides) -> dict:
    payload = {
        "registry": "VERRA",
        "vintage_year": 2023,
        "quantity_kgco2e": 100,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ManufacturingTarget (PRD §3.7)
# ---------------------------------------------------------------------------
def create_manufacturing_target_payload(**overrides) -> dict:
    payload = {
        "program_name": "OpsNet-30",
        "baseline_intensity_kgco2e_per_m2": 8.0,
        "target_reduction_pct": 0.25,
    }
    payload.update(overrides)
    return payload


def create_reading_payload(**overrides) -> dict:
    payload = {
        "period_end": "2026-10-01T00:00:00Z",
        "intensity_kgco2e_per_m2": 6.0,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# SpecPackage (PRD §3.8) — expected_collection_version is mandatory (PRD §2.7).
# ---------------------------------------------------------------------------
def create_spec_package_payload(
    collection_id: str, report_id: str, expected_collection_version: int, **overrides
) -> dict:
    payload = {
        "architect_firm": "FIRM-A",
        "collection_id": collection_id,
        "report_id": report_id,
        "expected_collection_version": expected_collection_version,
    }
    payload.update(overrides)
    return payload


def required_batch_mix_kg(produced_m2) -> float:
    """Exact allocated mass the release gate demands: produced_m2 x 4.0 kg
    (PRD §3.2 mass-balance rule)."""
    return produced_m2 * TILE_MASS_KG_PER_M2
