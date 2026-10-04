"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import (
    CANONICAL_MIN_DURATION_SECONDS,
    CANONICAL_POOLED_SD_1000,
    CANONICAL_STRAIGHTLINE_MIN_ITEMS,
    CANONICAL_TIE_EPSILON,
    CANONICAL_WEIGHTS,
    CANONICAL_Z_VALUE,
    EMBARGO_LIFT_AT,
)


def create_study_payload(**overrides) -> dict:
    defaults = {
        "code": "VDS-2026",
        "name": "2026 Vehicle Dependability",
        "industry_code": "AUTO",
        "cycle_year": 2026,
        "min_sample_per_brand": 3,
        "significance_alpha": 0.05,
        "embargo_lift_at": EMBARGO_LIFT_AT,
    }
    defaults.update(overrides)
    return defaults


def create_methodology_payload(study_id, **overrides) -> dict:
    factors = overrides.pop("factors", None)
    if factors is None:
        factors = [
            {"code": code, "name": name, "weight_bp": weight, "ordinal": i + 1}
            for i, (code, name, weight) in enumerate(CANONICAL_WEIGHTS)
        ]
    defaults = {
        "study_id": study_id,
        "change_class": "FULL_COMPARABLE",
        "min_duration_seconds": CANONICAL_MIN_DURATION_SECONDS,
        "straightline_min_items": CANONICAL_STRAIGHTLINE_MIN_ITEMS,
        "pooled_sd_1000": CANONICAL_POOLED_SD_1000,
        "z_value": CANONICAL_Z_VALUE,
        "tie_epsilon": CANONICAL_TIE_EPSILON,
        "factors": factors,
    }
    defaults.update(overrides)
    return defaults


def create_brand_payload(**overrides) -> dict:
    defaults = {"name": "BrandA", "industry_code": "AUTO"}
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    defaults = {"name": "ClientA", "client_type": "BRAND", "country": "US"}
    defaults.update(overrides)
    return defaults


def create_sample_frame_payload(study_id, brand_id, **overrides) -> dict:
    defaults = {
        "study_id": study_id,
        "brand_id": brand_id,
        "source_type": "PANEL",
        "target_completes": 3,
    }
    defaults.update(overrides)
    return defaults


def factor_scores_payload(qual_score, feat_score) -> list:
    return [
        {"factor_code": "QUAL", "score": qual_score},
        {"factor_code": "FEAT", "score": feat_score},
    ]


def create_response_payload(frame_id, respondent_token, qual_score, feat_score, **overrides) -> dict:
    defaults = {
        "frame_id": frame_id,
        "respondent_token": respondent_token,
        "duration_seconds": 300,
        "item_count": 15,
        "distinct_values": 4,
        "factor_scores": factor_scores_payload(qual_score, feat_score),
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(award_id, client_id, **overrides) -> dict:
    defaults = {
        "award_id": award_id,
        "client_id": client_id,
        "tier": "DIGITAL",
        "term_months": 12,
        "markets_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_usage_audit_payload(license_id, **overrides) -> dict:
    defaults = {"license_id": license_id, "severity": "MINOR", "note": "audit note"}
    defaults.update(overrides)
    return defaults


def create_subscription_payload(client_id, study_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "study_id": study_id,
        "tier": "DIAGNOSTIC",
        "starts_at": "2026-09-01T00:00:00Z",
        "ends_at": "2027-08-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
