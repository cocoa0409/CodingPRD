"""Payload factories — one per entity, input fields only.

Every factory accepts keyword overrides so a test or fixture can pin the exact
value under assertion while every other field keeps a sensible default.
"""
from .constants import TEST_DEFAULTS


def create_community_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["COMMUNITY_NAME"],
        "description": TEST_DEFAULTS["COMMUNITY_DESCRIPTION"],
    }
    payload.update(overrides)
    return payload


def create_rule_payload(**overrides) -> dict:
    payload = {
        "rule_code": TEST_DEFAULTS["RULE_CODE"],
        "rule_text": TEST_DEFAULTS["RULE_TEXT"],
        "rule_band": 1,
        "is_sitewide_floor": False,
    }
    payload.update(overrides)
    return payload


def create_moderator_payload(**overrides) -> dict:
    payload = {
        "moderator_account_id": "mod-new",
        "display_name": "New Moderator",
        "moderator_role": "REGULAR_MODERATOR",
    }
    payload.update(overrides)
    return payload


def create_post_payload(**overrides) -> dict:
    payload = {
        "author_account_id": "user-ap",
        "title": TEST_DEFAULTS["POST_TITLE"],
        "body": TEST_DEFAULTS["POST_BODY"],
        "post_type": "TEXT",
    }
    payload.update(overrides)
    return payload


def create_content_report_payload(**overrides) -> dict:
    payload = {
        "content_source_type": "POST",
        "content_source_id": "src-1",
        "reporter_account_id": "rep-1",
        "report_reason_code": "SPAM",
        "resolution_tier": 1,
    }
    payload.update(overrides)
    return payload


def create_detection_item_payload(**overrides) -> dict:
    payload = {
        "source_type": "POST",
        "source_id": "src-1",
        "subject_account_id": TEST_DEFAULTS["SUBJECT_ACCOUNT_ID"],
        "signal_severity_band": TEST_DEFAULTS["DETECTION_SEVERITY_BAND"],
        "detection_confidence": TEST_DEFAULTS["DETECTION_CONFIDENCE"],
        "overlap_ratio": TEST_DEFAULTS["DETECTION_OVERLAP_RATIO"],
        "published_at_utc": "2026-09-12T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_content_decision_payload(**overrides) -> dict:
    payload = {
        "auto_detection_backlog_item_id": "item-1",
        "decision_outcome": "REMOVE",
        "decision_confidence": 0.90,
        "dissection_band": 0,
        "precedent_approval_count": 0,
    }
    payload.update(overrides)
    return payload


def create_account_wide_sanction_payload(**overrides) -> dict:
    payload = {
        "account_id": TEST_DEFAULTS["SUBJECT_ACCOUNT_ID"],
        "community_id": "community-1",
        "decision_outcome": "BAN_ISSUED",
    }
    payload.update(overrides)
    return payload


def create_brigade_cluster_payload(**overrides) -> dict:
    payload = {
        "internal_link_count": 10,
        "external_link_count": 10,
        "participant_count": 10,
        "legitimate_participant_count": 0,
    }
    payload.update(overrides)
    return payload


def file_appeal_payload(**overrides) -> dict:
    payload = {
        "sanction_id": "sanction-1",
        "ground_code": "ANALYSIS_ERROR",
        "new_evidence_url": None,
        "sanction_misapplication_present": False,
    }
    payload.update(overrides)
    return payload


def create_protest_payload(**overrides) -> dict:
    payload = {
        "requested_access_mode": "READ_ONLY",
        "conflicting_cross_power_account_ids": [],
    }
    payload.update(overrides)
    return payload


def approve_protest_payload(**overrides) -> dict:
    payload = {
        "moderator_id": "moderator-1",
        "approving_account_id": "account-1",
    }
    payload.update(overrides)
    return payload


def remove_moderator_payload(**overrides) -> dict:
    payload = {"expected_moderator_version": 1}
    payload.update(overrides)
    return payload


def create_succession_payload(**overrides) -> dict:
    payload = {"expected_community_version": 1}
    payload.update(overrides)
    return payload