"""Payload factories — one per entity, input fields only.

Money is always an integer number of cents (never a string, never a decimal), and every
instant is a full ISO 8601 UTC instant rather than a date-only literal (PRD §2.4, §2.8).
"""

import itertools

_COUNTER = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic suffix for fields the PRD requires to be unique."""
    return str(next(_COUNTER))


def create_community_payload(**overrides) -> dict:
    """POST /communities (PRD §3.1). product_mix must sum to total_planned_units."""
    n = unique_suffix()
    payload = {
        "name": f"Cedar Hollow {n}",
        "market_code": "TX-AUS",
        "total_planned_units": 4,
        "product_mix": {"DETACHED": 4, "COTTAGE": 0, "TOWNHOME": 0},
        "single_ownership_covenant": True,
        "concession_budget_cents": 4_000_000,
        "facility_commitment_cents": 80_000_000,
        "maintenance_tech_headcount": 2,
    }
    payload.update(overrides)
    return payload


def plat_submission_payload(**overrides) -> dict:
    """POST /communities/{id}/plat-submissions (PRD §3.2)."""
    payload = {"plat_package_reference": f"PLAT-{unique_suffix()}"}
    payload.update(overrides)
    return payload


def plat_decision_payload(decision="APPROVE", **overrides) -> dict:
    """POST /communities/{id}/plat-decisions (PRD §3.2)."""
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_phase_payload(community_id, **overrides) -> dict:
    """POST /phases — housing phase by default (PRD §3.1)."""
    payload = {
        "community_id": community_id,
        "sequence_index": 1,
        "kind": "HOUSING",
        "planned_unit_count": 4,
        "amenity_weight": 0,
        "construction_window_start": "2026-08-01T00:00:00Z",
        "construction_window_end": "2026-11-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_amenity_phase_payload(community_id, **overrides) -> dict:
    """POST /phases — amenity phase: amenity_weight >= 1 and planned_unit_count 0."""
    payload = {
        "community_id": community_id,
        "sequence_index": 2,
        "kind": "AMENITY",
        "planned_unit_count": 0,
        "amenity_weight": 10,
        "construction_window_start": "2026-08-01T00:00:00Z",
        "construction_window_end": "2026-11-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_homesite_payload(phase_id, **overrides) -> dict:
    """POST /homesites (PRD §3.1)."""
    payload = {
        "phase_id": phase_id,
        "lot_number": f"L{unique_suffix()}",
        "product_type": "DETACHED",
        "bedrooms": 4,
        "square_feet": 2200,
    }
    payload.update(overrides)
    return payload


def occupancy_certificate_payload(**overrides) -> dict:
    """POST /homesites/{id}/occupancy-certificates (PRD §3.3)."""
    payload = {
        "occupancy_certificate_number": f"CO-{unique_suffix()}",
        "issued_at": "2026-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def section_release_payload(homesite_ids, **overrides) -> dict:
    """POST /phases/{id}/section-releases (PRD §3.3)."""
    payload = {"homesite_ids": list(homesite_ids)}
    payload.update(overrides)
    return payload


def halt_payload(**overrides) -> dict:
    """POST /phases/{id}/halt (PRD §3.4)."""
    payload = {"halt_reason": "Weather delay"}
    payload.update(overrides)
    return payload


def publish_schedule_payload(community_id, expected_community_version, **overrides) -> dict:
    """POST /market-rent-schedules — MANUAL mode by default (PRD §3.5, §2.7)."""
    payload = {
        "community_id": community_id,
        "product_type": "DETACHED",
        "effective_from": "2026-08-01T00:00:00Z",
        "repricing_mode": "MANUAL",
        "asking_rent_cents": 285_000,
        "expected_community_version": expected_community_version,
    }
    payload.update(overrides)
    return payload


def indexed_schedule_payload(community_id, expected_community_version, **overrides) -> dict:
    """POST /market-rent-schedules — ABSORPTION_INDEXED mode (PRD §3.5)."""
    payload = {
        "community_id": community_id,
        "product_type": "DETACHED",
        "effective_from": "2026-08-08T00:00:00Z",
        "repricing_mode": "ABSORPTION_INDEXED",
        "expected_community_version": expected_community_version,
    }
    payload.update(overrides)
    return payload


def create_concession_program_payload(
    community_id, expected_community_version, **overrides
) -> dict:
    """POST /concession-programs (PRD §3.6, §2.7)."""
    payload = {
        "community_id": community_id,
        "program_code": f"CP-{unique_suffix()}",
        "tier": "AGGRESSIVE",
        "free_weeks": 6,
        "amortization_mode": "STRAIGHT_LINE_NET_EFFECTIVE",
        "eligible_product_types": ["DETACHED"],
        "restricted_posture_eligible": False,
        "max_budget_cents": 2_000_000,
        "expected_community_version": expected_community_version,
    }
    payload.update(overrides)
    return payload


def create_household_payload(**overrides) -> dict:
    """POST /households (PRD §3.7)."""
    n = unique_suffix()
    payload = {
        "primary_applicant_name": f"Ada Vance {n}",
        "email": f"ada{n}@example.com",
        "household_size": 4,
        "monthly_income_cents": 1_200_000,
        "credit_tier": "A",
    }
    payload.update(overrides)
    return payload


def create_lease_payload(homesite_id, household_id, **overrides) -> dict:
    """POST /leases (PRD §3.7)."""
    payload = {
        "homesite_id": homesite_id,
        "household_id": household_id,
        "term_months": 12,
        "start_date": "2026-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def concession_request_payload(concession_program_id, **overrides) -> dict:
    """POST /leases/{id}/concession-requests (PRD §3.8)."""
    payload = {"concession_program_id": concession_program_id}
    payload.update(overrides)
    return payload


def concession_decision_payload(decision="APPROVE", **overrides) -> dict:
    """POST /leases/{id}/concession-decisions (PRD §3.8)."""
    payload = {"decision": decision, "decision_note": "Within budget"}
    payload.update(overrides)
    return payload


def signature_payload(signed_by_name="Ada Vance", **overrides) -> dict:
    """POST /leases/{id}/signature (PRD §3.9)."""
    payload = {"signed_by_name": signed_by_name}
    payload.update(overrides)
    return payload


def concession_credit_payload(period_index=1, **overrides) -> dict:
    """POST /leases/{id}/concession-credit-applications (PRD §3.8)."""
    payload = {"period_index": period_index}
    payload.update(overrides)
    return payload


def notice_payload(**overrides) -> dict:
    """POST /leases/{id}/notices (PRD §3.10)."""
    payload = {
        "notice_date": "2026-08-01T00:00:00Z",
        "move_out_date": "2026-09-30T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def cancellation_payload(cancellation_reason="OPERATOR_CANCELLED", **overrides) -> dict:
    """POST /leases/{id}/cancellation (PRD §3.9)."""
    payload = {"cancellation_reason": cancellation_reason}
    payload.update(overrides)
    return payload


def create_turn_work_order_payload(homesite_id, **overrides) -> dict:
    """POST /turn-work-orders (PRD §3.10)."""
    payload = {
        "homesite_id": homesite_id,
        "window_start": "2026-10-01T00:00:00Z",
        "window_end": "2026-10-03T00:00:00Z",
        "scope": "MAKE_READY",
        "tech_count": 1,
        "material_cost_cents": 12_000,
    }
    payload.update(overrides)
    return payload


def absorption_review_payload(**overrides) -> dict:
    """POST /communities/{id}/absorption-reviews (PRD §3.5)."""
    payload = {
        "product_type": "DETACHED",
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-08-08T00:00:00Z",
        "planned_absorption_units": 2,
    }
    payload.update(overrides)
    return payload


def pm_transition_payload(**overrides) -> dict:
    """POST /communities/{id}/pm-transitions (PRD §3.11)."""
    payload = {
        "pm_company_name": "Hollow Residential Services",
        "effective_from": "2026-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def facility_commitment_payload(facility_commitment_cents, **overrides) -> dict:
    """POST /communities/{id}/facility-commitments (PRD §3.11)."""
    payload = {"facility_commitment_cents": facility_commitment_cents}
    payload.update(overrides)
    return payload


def clock_payload(current_utc, **overrides) -> dict:
    """POST /_clock/set_current_utc (PRD §2.9)."""
    payload = {"current_utc": current_utc}
    payload.update(overrides)
    return payload
