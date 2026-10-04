"""Payload factories — one per entity, client-supplied fields only."""
import itertools

from .constants import CREDIT_DUAL_AUTO, PRIME_SHIFT_AUTO

_counter = itertools.count(1)


def unique(prefix: str = "gen") -> str:
    """A fresh identifier for fields that must be unique across a test."""
    return f"{prefix}-{next(_counter)}"


def _clean(**kwargs) -> dict:
    return {k: v for k, v in kwargs.items() if v is not None}


# ─── Bureau ───────────────────────────────────────────
def create_bureau_payload(**overrides) -> dict:
    defaults = {"bureau_code": "TUC", "display_name": "TransUnion"}
    defaults.update(overrides)
    return defaults


# ─── Score model ──────────────────────────────────────
def create_score_model_payload(**overrides) -> dict:
    defaults = {
        "family_code": "FICO_CORE",
        "version_label": unique("MODEL"),
        "min_input_count": 100,
    }
    defaults.update(overrides)
    return _clean(**defaults)


# ─── Score variant ────────────────────────────────────
def create_variant_payload(**overrides) -> dict:
    defaults = dict(CREDIT_DUAL_AUTO)
    defaults["industry"] = "AUTO"
    defaults.update(overrides)
    return _clean(**defaults)


def prime_shift_variant_payload(**overrides) -> dict:
    defaults = dict(PRIME_SHIFT_AUTO)
    defaults["industry"] = "AUTO"
    defaults.update(overrides)
    return _clean(**defaults)


# ─── Consumer ─────────────────────────────────────────
def create_consumer_payload(**overrides) -> dict:
    defaults = {
        "consumer_ref": unique("cons"),
        "age_years": 40,
    }
    defaults.update(overrides)
    return _clean(**defaults)


# ─── Archive sample ───────────────────────────────────
def create_archive_sample_payload(score_model_id: str = None, **overrides) -> dict:
    defaults = {
        "score_model_id": score_model_id,
        "sample_ref": unique("SAMPLE"),
        "record_count": 5000,
        "segment_name": "PRIME",
        "sample_kind": "VALIDATION",
        "observation_window_months": 24,
        "window_start_month": "2024-01",
        "window_end_month": "2026-01",
    }
    defaults.update(overrides)
    return _clean(**defaults)


# ─── Validation study ─────────────────────────────────
def create_validation_study_payload(score_model_id: str = None, sample_id: str = None,
                                    **overrides) -> dict:
    defaults = {
        "score_model_id": score_model_id,
        "sample_id": sample_id,
        "study_path": "CROSS_BUREAU",
        "performed_by": "va-001",
    }
    defaults.update(overrides)
    return _clean(**defaults)


# ─── Reference set ────────────────────────────────────
def create_reference_set_payload(consumer_id: str = None, score_model_id: str = None,
                                 **overrides) -> dict:
    defaults = {
        "consumer_id": consumer_id,
        "score_model_id": score_model_id,
    }
    defaults.update(overrides)
    return _clean(**defaults)


# ─── Score posting ────────────────────────────────────
def create_score_result_payload(consumer_id: str = None, score_variant_id: str = None,
                                bureau_id: str = None, license_id: str = None,
                                **overrides) -> dict:
    defaults = {
        "consumer_id": consumer_id,
        "score_variant_id": score_variant_id,
        "bureau_id": bureau_id,
        "license_id": license_id,
        "raw_posted_score": 715,
    }
    defaults.update(overrides)
    return _clean(**defaults)


# ─── Reason code ──────────────────────────────────────
def create_reason_code_payload(score_variant_id: str = None, **overrides) -> dict:
    defaults = {
        "score_variant_id": score_variant_id,
        "depth_tier": "PRIMARY",
        "trigger_feature_code": "SEGMENT_ZERO",
        "code_label": unique("rc"),
        "weight_pct": 0.30,
    }
    defaults.update(overrides)
    return _clean(**defaults)


# ─── Licence ──────────────────────────────────────────
def create_license_payload(score_variant_id: str = None, **overrides) -> dict:
    defaults = {
        "lender_name": "North Bank",
        "lender_code": "LEND-NORTH",
        "score_variant_id": score_variant_id,
        "volume_tier": "VOLUME_TIER_1",
        "entitled_count": 500,
        "window_start_month": "2026-01",
        "window_end_month": "2027-01",
    }
    defaults.update(overrides)
    return _clean(**defaults)


# ─── Regulatory documentation ─────────────────────────
def create_model_documentation_payload(score_model_id: str = None, **overrides) -> dict:
    defaults = {
        "score_model_id": score_model_id,
        "doc_type": "MODEL_RISK_REPORT",
        "required_version_label": "CREDIT-DUAL-V1",
    }
    defaults.update(overrides)
    return _clean(**defaults)


# ─── Migration event ──────────────────────────────────
def create_migration_event_payload(from_score_variant_id: str = None,
                                   to_score_variant_id: str = None, **overrides) -> dict:
    defaults = {
        "lender_code": "LEND-NORTH",
        "from_score_variant_id": from_score_variant_id,
        "to_score_variant_id": to_score_variant_id,
        "event_type": "RECALIBRATED",
        "evidence_ref": unique("WS"),
    }
    defaults.update(overrides)
    return _clean(**defaults)