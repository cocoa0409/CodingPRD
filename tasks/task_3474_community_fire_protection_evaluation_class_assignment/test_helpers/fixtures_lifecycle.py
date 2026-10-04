"""Composite fixtures, tier 3–5: rating, reevaluation, and appeal lifecycles.

Quote binding and request approval carry optimistic-concurrency fields, so
those helpers always re-read the parent's fresh version before writing.
Transition helpers that a fixed role owns come pre-wired with that role's
headers; the raw ``transition_*`` variants take explicit headers for tests
that probe authorization boundaries.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .fixtures_core import COORDINATOR, community_version
from .test_users import (
    DEFAULT_ANALYST_ID,
    DEFAULT_REGISTRAR_ID,
    TEST_USERS,
    make_community_official_headers,
    make_field_analyst_headers,
    make_class_registrar_headers,
    make_insurer_headers,
)

INSURER = TEST_USERS["insurer_headers"]


# ── Properties and quotes ────────────────────────────────────────────────

def create_property(api: ApiClient, community_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_property_risk_profile(f.property_risk_profile_payload(community_id, **overrides), COORDINATOR)
    )


def create_quote(api: ApiClient, property_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_premium_quote(f.premium_quote_payload(property_id, **overrides), INSURER)
    )


def bind_quote(
    api: ApiClient,
    community_id: str,
    quote_id: str,
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Bind a QUOTED quote; captures the fresh community version unless given."""
    version = expected_version if expected_version is not None else community_version(api, community_id)
    return get_success_data(
        api.bind_premium_quote(quote_id, f.bind_quote_payload(version), INSURER)
    )


def void_quote(api: ApiClient, quote_id: str) -> Dict[str, Any]:
    return get_success_data(api.void_premium_quote(quote_id, INSURER))


def get_quote(api: ApiClient, quote_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_premium_quote(quote_id, INSURER))


def list_quotes(api: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    return get_success_data(api.list_premium_quotes(INSURER, params=params or None))


# ── Reevaluation requests ────────────────────────────────────────────────

def file_reevaluation_request(api: ApiClient, community_id: str, **overrides: Any) -> Dict[str, Any]:
    """Filed by the community's own official; moves community out of CLASSIFIED."""
    return get_success_data(
        api.create_reevaluation_request(
            f.reevaluation_request_payload(community_id, **overrides),
            make_community_official_headers(community_id),
        )
    )


def transition_request(
    api: ApiClient,
    request_id: str,
    target_state: str,
    headers: Dict[str, str],
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """Raw request transition with explicit headers (role per target varies)."""
    return get_success_data(
        api.transition_reevaluation_request(
            request_id, f.request_transition_payload(target_state, note), headers
        )
    )


def open_documentation_review(api: ApiClient, request_id: str) -> Dict[str, Any]:
    return transition_request(api, request_id, "DOCUMENTATION_REVIEW", COORDINATOR)


def return_request_for_docs(api: ApiClient, request_id: str, note: Optional[str] = None) -> Dict[str, Any]:
    return transition_request(api, request_id, "SUBMITTED", COORDINATOR, note)


def begin_field_reverification(api: ApiClient, request_id: str, analyst_id: str = DEFAULT_ANALYST_ID) -> Dict[str, Any]:
    return transition_request(api, request_id, "FIELD_REVERIFICATION", make_field_analyst_headers(analyst_id))


def deny_reevaluation_request(
    api: ApiClient, request_id: str, registrar_id: str = DEFAULT_REGISTRAR_ID, note: Optional[str] = None
) -> Dict[str, Any]:
    return transition_request(api, request_id, "DENIED", make_class_registrar_headers(registrar_id), note)


def withdraw_reevaluation_request(api: ApiClient, request_id: str, community_id: str) -> Dict[str, Any]:
    return transition_request(
        api, request_id, "WITHDRAWN", make_community_official_headers(community_id)
    )


def patch_request_evidence(api: ApiClient, request_id: str, community_id: str, evidence_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Replace evidence items; only valid while the request is SUBMITTED."""
    return get_success_data(
        api.patch_reevaluation_request(
            request_id, {"evidence_items": evidence_items}, make_community_official_headers(community_id)
        )
    )


def approve_reevaluation_request(
    api: ApiClient,
    request_id: str,
    community_id: str,
    field_analyst_id: str = DEFAULT_ANALYST_ID,
    registrar_id: str = DEFAULT_REGISTRAR_ID,
    note: Optional[str] = None,
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Registrar approval; OCC on the community, spawns the new cycle."""
    version = expected_version if expected_version is not None else community_version(api, community_id)
    return get_success_data(
        api.approve_reevaluation_request(
            request_id,
            f.approve_reevaluation_payload(version, field_analyst_id, note),
            make_class_registrar_headers(registrar_id),
        )
    )


# ── Appeals ──────────────────────────────────────────────────────────────

def file_appeal(
    api: ApiClient,
    classification_id: str,
    community_id: str,
    grounds: str = "DATA_ERROR",
    evidence_items: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Filed by the community's own official against its own classification."""
    overrides: Dict[str, Any] = {"grounds": grounds}
    if evidence_items is not None:
        overrides["evidence_items"] = evidence_items
    return get_success_data(
        api.create_appeal(
            f.appeal_payload(classification_id, community_id, **overrides),
            make_community_official_headers(community_id),
        )
    )


def transition_appeal(
    api: ApiClient,
    appeal_id: str,
    target_state: str,
    headers: Dict[str, str],
    adjudication_note: Optional[str] = None,
    new_score_sheet_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Raw appeal transition with explicit headers (role per target varies)."""
    return get_success_data(
        api.transition_appeal(
            appeal_id,
            f.appeal_transition_payload(target_state, adjudication_note, new_score_sheet_id),
            headers,
        )
    )


def begin_data_verification(api: ApiClient, appeal_id: str, analyst_id: str = DEFAULT_ANALYST_ID) -> Dict[str, Any]:
    return transition_appeal(api, appeal_id, "DATA_VERIFICATION", make_field_analyst_headers(analyst_id))


def return_appeal_for_evidence(api: ApiClient, appeal_id: str, analyst_id: str = DEFAULT_ANALYST_ID) -> Dict[str, Any]:
    return transition_appeal(api, appeal_id, "FILED", make_field_analyst_headers(analyst_id))


def adjudicate_upheld(
    api: ApiClient,
    appeal_id: str,
    registrar_id: str = DEFAULT_REGISTRAR_ID,
    adjudication_note: Optional[str] = None,
) -> Dict[str, Any]:
    """Registrar must differ from the classification's published_by (SoD)."""
    return transition_appeal(
        api, appeal_id, "ADJUDICATED_UPHELD", make_class_registrar_headers(registrar_id), adjudication_note
    )


def adjudicate_revised(
    api: ApiClient,
    appeal_id: str,
    new_score_sheet_id: str,
    registrar_id: str = DEFAULT_REGISTRAR_ID,
    adjudication_note: Optional[str] = None,
) -> Dict[str, Any]:
    """Registrar must differ from published_by; new sheet must be FINAL and
    belong to the classification's cycle."""
    return transition_appeal(
        api, appeal_id, "ADJUDICATED_REVISED", make_class_registrar_headers(registrar_id),
        adjudication_note, new_score_sheet_id,
    )


def withdraw_appeal(api: ApiClient, appeal_id: str, community_id: str) -> Dict[str, Any]:
    return transition_appeal(api, appeal_id, "WITHDRAWN", make_community_official_headers(community_id))
