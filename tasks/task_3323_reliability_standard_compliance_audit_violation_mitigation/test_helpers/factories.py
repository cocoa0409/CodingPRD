"""Payload factories — one per entity, input fields only."""


def create_registration_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Entity Co",
        "registration_functions": ["GO"],
    }
    defaults.update(overrides)
    return defaults


def create_engagement_payload(entity_id, **overrides) -> dict:
    defaults = {
        "entity_id": entity_id,
        "engagement_type": "AUDIT",
        "standard_ids": ["STD-GO-001"],
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-01-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(engagement_id, **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "standard_id": "STD-GO-001",
        "artifact_kind": "OPERATING_RECORD",
        "coverage_start": "2026-01-01T00:00:00Z",
        "coverage_end": "2026-01-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_self_report_payload(entity_id, **overrides) -> dict:
    defaults = {
        "entity_id": entity_id,
        "standard_id": "STD-GO-001",
        "description": "Potential noncompliance observed",
        "occurred_at": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_violation_payload(entity_id, **overrides) -> dict:
    defaults = {
        "entity_id": entity_id,
        "standard_id": "STD-GO-001",
        "source_type": "SPOT_CHECK",
        "violation_start": "2026-01-01T00:00:00Z",
        "violation_end": "2026-01-02T00:00:00Z",
        "violation_risk_factor": "MINIMAL",
        "severity_level": "LOWER",
    }
    defaults.update(overrides)
    return defaults


def create_mitigation_plan_payload(expected_violation_version, **overrides) -> dict:
    defaults = {
        "description": "Mitigation plan narrative",
        "expected_violation_version": expected_violation_version,
    }
    defaults.update(overrides)
    return defaults


def create_milestone_payload(**overrides) -> dict:
    defaults = {
        "title": "Milestone",
        "due_date": "2026-10-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_self_log_entry_payload(entity_id, **overrides) -> dict:
    defaults = {
        "entity_id": entity_id,
        "standard_id": "STD-GO-001",
        "exception_note": "Minimal-risk exception",
    }
    defaults.update(overrides)
    return defaults


def create_cip_asset_payload(entity_id, **overrides) -> dict:
    defaults = {
        "entity_id": entity_id,
        "asset_name": "Relay House",
        "impact_rating": "HIGH",
    }
    defaults.update(overrides)
    return defaults


def create_access_grant_payload(asset_id, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "grantee_badge": "B-100",
        "scope": "PHYSICAL",
    }
    defaults.update(overrides)
    return defaults


def create_penalty_payload(violation_id, **overrides) -> dict:
    defaults = {"violation_id": violation_id}
    defaults.update(overrides)
    return defaults


def create_appeal_payload(expected_violation_version, **overrides) -> dict:
    defaults = {
        "grounds": "Procedural grounds",
        "expected_violation_version": expected_violation_version,
    }
    defaults.update(overrides)
    return defaults
