"""Payload factories — request-input fields only, never server-computed ones.

Money is always an integer count of cents transmitted as a JSON number (§2.7);
vendor per-word rates are the single decimal exception.  Calendar dates are
``YYYY-MM-DD`` strings and instants are ISO-8601 UTC with a trailing ``Z``
(§2.4), and the two are never interchanged.
"""
from __future__ import annotations

import itertools
from typing import Any

from .constants import TEST_DEFAULTS

_COUNTER = itertools.count(1)


def next_seq() -> int:
    """A process-unique counter for building distinct unique keys."""
    return next(_COUNTER)


def unique_suffix() -> str:
    return f"{next_seq():04d}"


# ---------------------------------------------------------------------------
# Logical clock (§2.4)
# ---------------------------------------------------------------------------

def create_clock_payload(current_utc: str, **overrides: Any) -> dict[str, Any]:
    """Body for the clock-setting capability; ``current_utc`` is an instant."""
    payload: dict[str, Any] = {"current_utc": current_utc}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Release trains (§3.1)
# ---------------------------------------------------------------------------

def create_release_train_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "product_key": TEST_DEFAULTS["product_key"],
        "version_label": f"{TEST_DEFAULTS['version_label']}-{unique_suffix()}",
        "doc_freeze_date": TEST_DEFAULTS["doc_freeze_date"],
        "ga_date": TEST_DEFAULTS["ga_date"],
        "support_end_date": TEST_DEFAULTS["support_end_date"],
        "localization_budget_cap_cents": TEST_DEFAULTS["localization_budget_cap_cents"],
    }
    payload.update(overrides)
    return payload


def advance_release_train_payload(target_status: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"target_status": target_status}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Writers and reviewers (§3.2)
# ---------------------------------------------------------------------------

def create_writer_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "person_key": f"{TEST_DEFAULTS['writer_person_key']}-{unique_suffix()}",
        "full_name": TEST_DEFAULTS["writer_full_name"],
        "seniority_tier": TEST_DEFAULTS["seniority_tier"],
        "capacity_points": TEST_DEFAULTS["capacity_points"],
    }
    payload.update(overrides)
    return payload


def create_reviewer_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "person_key": f"{TEST_DEFAULTS['reviewer_person_key']}-{unique_suffix()}",
        "full_name": TEST_DEFAULTS["reviewer_full_name"],
        "discipline": TEST_DEFAULTS["discipline"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Plan items (§3.2)
# ---------------------------------------------------------------------------

def create_plan_item_payload(release_train_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "release_train_id": release_train_id,
        "feature_key": f"{TEST_DEFAULTS['feature_key']}-{unique_suffix()}",
        "ia_placement": TEST_DEFAULTS["ia_placement"],
        "audience_tier": TEST_DEFAULTS["audience_tier"],
        "planned_page_count": TEST_DEFAULTS["planned_page_count"],
        "complexity_points": TEST_DEFAULTS["complexity_points"],
    }
    payload.update(overrides)
    return payload


def assign_plan_item_payload(writer_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "writer_id": writer_id,
        "window_start_date": TEST_DEFAULTS["window_start_date"],
        "window_end_date": TEST_DEFAULTS["window_end_date"],
    }
    payload.update(overrides)
    return payload


def cancel_plan_item_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"cancel_reason": TEST_DEFAULTS["cancel_reason"]}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Topics and source revisions (§3.3)
# ---------------------------------------------------------------------------

def create_topic_payload(plan_item_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "plan_item_id": plan_item_id,
        "slug": f"{TEST_DEFAULTS['slug']}-{unique_suffix()}",
        "title": TEST_DEFAULTS["title"],
    }
    payload.update(overrides)
    return payload


def create_revision_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "body_word_count": TEST_DEFAULTS["body_word_count"],
        "used_terms": [],
        "summary": TEST_DEFAULTS["summary"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Terminology terms (§3.4)
# ---------------------------------------------------------------------------

def create_terminology_term_payload(**overrides: Any) -> dict[str, Any]:
    seq = unique_suffix()
    payload: dict[str, Any] = {
        "term": f"term-{seq}",
        "preferred_form": f"preferred form {seq}",
        "forbidden_forms": [f"forbidden form {seq}"],
        "enforcement_severity": TEST_DEFAULTS["enforcement_severity"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Sign-offs (§3.5)
# ---------------------------------------------------------------------------

def request_signoff_payload(reviewer_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"reviewer_id": reviewer_id}
    payload.update(overrides)
    return payload


def decide_signoff_payload(decision: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Doc set versions (§3.6)
# ---------------------------------------------------------------------------

def create_doc_set_version_payload(
    release_train_id: str, expected_release_train_version: int, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "release_train_id": release_train_id,
        "version_label": f"{TEST_DEFAULTS['doc_set_version_label']}-{unique_suffix()}",
        "expected_release_train_version": expected_release_train_version,
    }
    payload.update(overrides)
    return payload


def archive_doc_set_version_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"eol_notice_text": TEST_DEFAULTS["eol_notice_text"]}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Change records (§3.7)
# ---------------------------------------------------------------------------

def create_change_record_payload(release_train_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "release_train_id": release_train_id,
        "internal_summary": TEST_DEFAULTS["internal_summary"],
        "severity": TEST_DEFAULTS["severity"],
        "category": TEST_DEFAULTS["category"],
        "affected_component": f"{TEST_DEFAULTS['affected_component']}-{unique_suffix()}",
    }
    payload.update(overrides)
    return payload


def editorial_pass_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "customer_facing_text": TEST_DEFAULTS["customer_facing_text"],
        "used_terms": [],
    }
    payload.update(overrides)
    return payload


def exclude_change_record_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"exclusion_reason": TEST_DEFAULTS["exclusion_reason"]}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Release notes (§3.7)
# ---------------------------------------------------------------------------

def create_release_note_payload(
    doc_set_version_id: str, expected_doc_set_version_version: int, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "doc_set_version_id": doc_set_version_id,
        "expected_doc_set_version_version": expected_doc_set_version_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Locale profiles (§3.8)
# ---------------------------------------------------------------------------

_LOCALE_LANGUAGES = [
    "fr", "de", "es", "it", "pt", "nl", "sv", "da", "fi", "no",
    "pl", "cs", "hu", "ro", "el", "tr", "ru", "uk", "ja", "ko",
    "zh", "th", "vi", "id", "ms", "hi", "bn", "ta", "he", "ar",
]
_LOCALE_REGIONS = ["FR", "DE", "ES", "IT", "BR", "NL", "SE", "DK", "FI", "NO"]


def unique_locale_code() -> str:
    """A distinct 5-character ``ll-CC`` code per call (§3.8)."""
    seq = next_seq()
    lang = _LOCALE_LANGUAGES[seq % len(_LOCALE_LANGUAGES)]
    region = _LOCALE_REGIONS[(seq // len(_LOCALE_LANGUAGES)) % len(_LOCALE_REGIONS)]
    return f"{lang}-{region}"


def create_locale_profile_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "locale_code": unique_locale_code(),
        "publication_mode": TEST_DEFAULTS["publication_mode"],
        "tm_coverage_pct": TEST_DEFAULTS["tm_coverage_pct"],
        "per_word_rate_cents": TEST_DEFAULTS["per_word_rate_cents"],
        "sla_days": TEST_DEFAULTS["sla_days"],
        "parallel_job_limit": TEST_DEFAULTS["parallel_job_limit"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Localization jobs (§3.8)
# ---------------------------------------------------------------------------

def create_localization_job_payload(
    topic_id: str, locale_profile_id: str, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "topic_id": topic_id,
        "locale_profile_id": locale_profile_id,
        "window_start_date": TEST_DEFAULTS["job_window_start_date"],
        "window_end_date": TEST_DEFAULTS["job_window_end_date"],
    }
    payload.update(overrides)
    return payload


def deliver_localization_job_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "translated_word_count": TEST_DEFAULTS["translated_word_count"],
        "tm_matched_word_count": TEST_DEFAULTS["tm_matched_word_count"],
    }
    payload.update(overrides)
    return payload


def cancel_localization_job_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"cancel_reason": TEST_DEFAULTS["cancel_reason"]}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Deprecation notices (§3.9)
# ---------------------------------------------------------------------------

def create_deprecation_notice_payload(
    release_train_id: str, migration_guide_topic_id: str, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "release_train_id": release_train_id,
        "feature_key": f"{TEST_DEFAULTS['deprecation_feature_key']}-{unique_suffix()}",
        "severity_tier": TEST_DEFAULTS["severity_tier"],
        "announce_date": TEST_DEFAULTS["announce_date"],
        "deprecated_date": TEST_DEFAULTS["deprecated_date"],
        "removal_date": TEST_DEFAULTS["removal_date"],
        "migration_guide_topic_id": migration_guide_topic_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Reader feedback (§3.10)
# ---------------------------------------------------------------------------

def create_feedback_payload(locale_code: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "rating": TEST_DEFAULTS["rating"],
        "outcome": TEST_DEFAULTS["outcome"],
        "locale_code": locale_code,
        "session_key": f"{TEST_DEFAULTS['session_key']}-{unique_suffix()}",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Default field sets, for shape-violation probes
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, dict[str, Any]] = {
    "release_train": {
        "product_key": TEST_DEFAULTS["product_key"],
        "version_label": TEST_DEFAULTS["version_label"],
        "doc_freeze_date": TEST_DEFAULTS["doc_freeze_date"],
        "ga_date": TEST_DEFAULTS["ga_date"],
        "support_end_date": TEST_DEFAULTS["support_end_date"],
        "localization_budget_cap_cents": TEST_DEFAULTS["localization_budget_cap_cents"],
    },
    "writer": {
        "person_key": TEST_DEFAULTS["writer_person_key"],
        "full_name": TEST_DEFAULTS["writer_full_name"],
        "seniority_tier": TEST_DEFAULTS["seniority_tier"],
        "capacity_points": TEST_DEFAULTS["capacity_points"],
    },
    "reviewer": {
        "person_key": TEST_DEFAULTS["reviewer_person_key"],
        "full_name": TEST_DEFAULTS["reviewer_full_name"],
        "discipline": TEST_DEFAULTS["discipline"],
    },
    "plan_item": {
        "feature_key": TEST_DEFAULTS["feature_key"],
        "ia_placement": TEST_DEFAULTS["ia_placement"],
        "audience_tier": TEST_DEFAULTS["audience_tier"],
        "planned_page_count": TEST_DEFAULTS["planned_page_count"],
        "complexity_points": TEST_DEFAULTS["complexity_points"],
    },
    "topic": {
        "slug": TEST_DEFAULTS["slug"],
        "title": TEST_DEFAULTS["title"],
    },
    "revision": {
        "body_word_count": TEST_DEFAULTS["body_word_count"],
        "used_terms": [],
        "summary": TEST_DEFAULTS["summary"],
    },
    "terminology_term": {
        "term": TEST_DEFAULTS["term"],
        "preferred_form": TEST_DEFAULTS["preferred_form"],
        "forbidden_forms": list(TEST_DEFAULTS["forbidden_forms"]),
        "enforcement_severity": TEST_DEFAULTS["enforcement_severity"],
    },
    "locale_profile": {
        "locale_code": TEST_DEFAULTS["locale_code"],
        "publication_mode": TEST_DEFAULTS["publication_mode"],
        "tm_coverage_pct": TEST_DEFAULTS["tm_coverage_pct"],
        "per_word_rate_cents": TEST_DEFAULTS["per_word_rate_cents"],
        "sla_days": TEST_DEFAULTS["sla_days"],
        "parallel_job_limit": TEST_DEFAULTS["parallel_job_limit"],
    },
    "change_record": {
        "internal_summary": TEST_DEFAULTS["internal_summary"],
        "severity": TEST_DEFAULTS["severity"],
        "category": TEST_DEFAULTS["category"],
        "affected_component": TEST_DEFAULTS["affected_component"],
    },
    "deprecation_notice": {
        "feature_key": TEST_DEFAULTS["deprecation_feature_key"],
        "severity_tier": TEST_DEFAULTS["severity_tier"],
        "announce_date": TEST_DEFAULTS["announce_date"],
        "deprecated_date": TEST_DEFAULTS["deprecated_date"],
        "removal_date": TEST_DEFAULTS["removal_date"],
    },
    "feedback": {
        "rating": TEST_DEFAULTS["rating"],
        "outcome": TEST_DEFAULTS["outcome"],
        "locale_code": TEST_DEFAULTS["locale_code"],
        "session_key": TEST_DEFAULTS["session_key"],
    },
}
