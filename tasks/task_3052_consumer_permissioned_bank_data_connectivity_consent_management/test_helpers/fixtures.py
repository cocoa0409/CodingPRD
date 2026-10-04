"""Composite setup helpers.

Every fixture builds its world from scratch through the public API: the test
harness restarts the server before each test, so no state carries over.
Fixtures use the lenient get_success_data() validator so setup failures
surface as clear "Setup failed" messages rather than assertion noise.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import FAR_EXPIRY
from .factories import (
    create_agreement_payload,
    create_connection_payload,
    create_consent_payload,
    create_institution_payload,
    create_recipient_payload,
    create_tier_payload,
)
from .test_users import (
    make_admin_headers,
    make_consumer_headers,
    make_recipient_headers,
    make_reviewer_headers,
)

DEFAULT_WINDOW_START = "2026-09-10T00:00:00Z"
DEFAULT_WINDOW_END = "2026-11-30T00:00:00Z"


def _ok(resp, label: str) -> dict:
    data = get_success_data(resp)
    assert isinstance(data, dict), f"Setup failed at {label}: {resp.status_code} {resp.text}"
    return data


# ── Tier 1 / 2: institution, recipient, tier, consent building blocks ──────


def create_institution_with_agreement(
    api: ApiClient,
    name: str = "Fixture Bank",
    supported_methods: Optional[List[str]] = None,
    target_method: str = "BANK_API",
    window_start: str = DEFAULT_WINDOW_START,
    window_end: str = DEFAULT_WINDOW_END,
    rate_limit_per_hour: int = 100,
    permitted_fields_by_scope: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """Institution + its governing ACTIVE agreement. Returns both plus headers."""
    admin = make_admin_headers()
    institution = _ok(
        api.create_institution(
            create_institution_payload(
                name=name,
                supported_methods=supported_methods or ["CREDENTIALS", "BANK_API"],
                target_method=target_method,
                migration_window_start=window_start,
                migration_window_end=window_end,
            ),
            admin,
        ),
        "create institution",
    )
    agreement = _ok(
        api.create_agreement(
            institution["id"],
            create_agreement_payload(
                rate_limit_per_hour=rate_limit_per_hour,
                permitted_fields_by_scope=permitted_fields_by_scope
                or {"BALANCE": ["current_cents", "available_cents"]},
                expected_institution_version=institution["version"],
            ),
            admin,
        ),
        "create agreement",
    )
    return {"institution": institution, "agreement": agreement, "admin": admin}


def create_approved_recipient(
    api: ApiClient,
    name: str = "Fixture App",
    minimization_policy: str = "BROAD",
    tier_scopes: Optional[List[str]] = None,
    rate_class: str = "LOW",
    tier_name: str = "Fixture Tier",
) -> Dict[str, Any]:
    """Recipient approved by a distinct reviewer, enrolled in a tier.

    Returns recipient, tier, assignment and the headers used.
    """
    admin = make_admin_headers()
    reviewer = make_reviewer_headers()
    recipient = _ok(
        api.create_recipient(
            create_recipient_payload(
                name=name,
                declared_use_case="fixture use case",
                minimization_policy=minimization_policy,
            ),
            admin,
        ),
        "create recipient",
    )
    recipient = _ok(
        api.review_recipient(recipient["id"], {"decision": "APPROVE"}, reviewer),
        "approve recipient",
    )
    tier = _ok(
        api.create_tier(
            create_tier_payload(
                tier_name=tier_name,
                scopes_included=tier_scopes or ["BALANCE"],
                rate_class=rate_class,
            ),
            admin,
        ),
        "create tier",
    )
    assignment = _ok(
        api.create_tier_assignment(recipient["id"], {"tier_id": tier["id"]}, admin),
        "create tier assignment",
    )
    return {
        "recipient": recipient,
        "tier": tier,
        "assignment": assignment,
        "admin": admin,
        "reviewer": reviewer,
    }


def capture_consent(
    api: ApiClient,
    recipient_id: str,
    consumer_ref: str,
    data_scopes: Optional[List[str]] = None,
    expires_at: str = FAR_EXPIRY,
    admin_headers: Optional[Dict[str, str]] = None,
) -> dict:
    """Capture a consent, reading the recipient's current version first (OCC)."""
    admin = admin_headers or make_admin_headers()
    recipient = _ok(api.get_recipient(recipient_id, admin), "read recipient version")
    return _ok(
        api.create_consent(
            recipient_id,
            create_consent_payload(
                consumer_ref=consumer_ref,
                data_scopes=data_scopes or ["BALANCE"],
                expires_at=expires_at,
                expected_recipient_version=recipient["version"],
            ),
            make_consumer_headers(consumer_ref),
        ),
        "capture consent",
    )


def create_pending_connection(
    api: ApiClient,
    institution_id: str,
    consent_id: str,
    consumer_ref: str,
    method: str = "CREDENTIALS",
    reauth_cooldown_seconds: Optional[int] = None,
) -> dict:
    payload = create_connection_payload(
        consumer_ref=consumer_ref, consent_id=consent_id, method=method
    )
    if reauth_cooldown_seconds is not None:
        payload["reauth_cooldown_seconds"] = reauth_cooldown_seconds
    return _ok(
        api.create_connection(institution_id, payload, make_consumer_headers(consumer_ref)),
        "create connection",
    )


def activate_connection(api: ApiClient, connection_id: str, consumer_ref: str) -> dict:
    """Complete authentication; runs the initial synchronous FULL refresh."""
    return _ok(
        api.complete_auth(connection_id, {}, make_consumer_headers(consumer_ref)),
        "complete auth",
    )


# ── Tier 2/3: the full healthy stack ────────────────────────────────────────


def setup_active_stack(
    api: ApiClient,
    institution_name: str = "Stack Bank",
    recipient_name: str = "Stack App",
    consumer_ref: str = "cons_stack",
    data_scopes: Optional[List[str]] = None,
    permitted_fields_by_scope: Optional[Dict[str, List[str]]] = None,
    tier_scopes: Optional[List[str]] = None,
    rate_class: str = "LOW",
    rate_limit_per_hour: int = 100,
    method: str = "CREDENTIALS",
    reauth_cooldown_seconds: Optional[int] = None,
    expires_at: str = FAR_EXPIRY,
    minimization_policy: str = "BROAD",
    window_start: str = DEFAULT_WINDOW_START,
    window_end: str = DEFAULT_WINDOW_END,
    target_method: str = "BANK_API",
) -> Dict[str, Any]:
    """Institution + agreement, APPROVED recipient + tier assignment, ACTIVE
    consent, and one connection completed to ACTIVE. The workhorse fixture."""
    scopes = data_scopes or ["BALANCE"]
    inst = create_institution_with_agreement(
        api,
        name=institution_name,
        target_method=target_method,
        window_start=window_start,
        window_end=window_end,
        rate_limit_per_hour=rate_limit_per_hour,
        permitted_fields_by_scope=permitted_fields_by_scope,
    )
    rec = create_approved_recipient(
        api,
        name=recipient_name,
        minimization_policy=minimization_policy,
        tier_scopes=tier_scopes or scopes,
        rate_class=rate_class,
        tier_name=f"{recipient_name} Tier",
    )
    consent = capture_consent(
        api, rec["recipient"]["id"], consumer_ref, scopes, expires_at, admin_headers=inst["admin"]
    )
    connection = create_pending_connection(
        api,
        inst["institution"]["id"],
        consent["id"],
        consumer_ref,
        method=method,
        reauth_cooldown_seconds=reauth_cooldown_seconds,
    )
    connection = activate_connection(api, connection["id"], consumer_ref)
    return {
        "institution": inst["institution"],
        "agreement": inst["agreement"],
        "recipient": rec["recipient"],
        "tier": rec["tier"],
        "assignment": rec["assignment"],
        "consent": consent,
        "connection": connection,
        "admin": inst["admin"],
        "reviewer": rec["reviewer"],
        "consumer": make_consumer_headers(consumer_ref),
        "consumer_ref": consumer_ref,
    }


# ── Tier 4: failure accumulation ────────────────────────────────────────────


def drive_consecutive_failures(
    api: ApiClient,
    connection_id: str,
    consumer_ref: str,
    count: int,
    failure_reason: str = "INSTITUTION_DOWN",
    kind: str = "FULL",
) -> List[dict]:
    """Drive ``count`` consecutive refresh failures on one connection.

    When the connection falls to BROKEN at two consecutive INSTITUTION_DOWN
    failures, a valid reauth reopens it so the next failure can land; callers
    use this to accumulate institution breakage while keeping the connection
    cycling. The reauth only fires between failures — after the final failure
    the connection is left in whatever state the last refresh produced, so
    callers can observe a terminal BROKEN. Returns the refresh job payloads.
    """
    consumer = make_consumer_headers(consumer_ref)
    jobs: List[dict] = []
    for i in range(count):
        job = _ok(
            api.refresh_connection(
                connection_id, {"kind": kind, "failure_reason": failure_reason}, consumer
            ),
            f"refresh failure ({failure_reason})",
        )
        jobs.append(job)
        connection = _ok(api.get_connection(connection_id, consumer), "read connection")
        if connection["status"] == "BROKEN" and i < count - 1:
            _ok(
                api.reauth_connection(connection_id, {"valid": True}, consumer),
                "reopen broken connection",
            )
    return jobs


def add_active_connection(
    api: ApiClient,
    stack: Dict[str, Any],
    consumer_ref: str,
    scopes: Optional[List[str]] = None,
    method: str = "CREDENTIALS",
) -> Dict[str, Any]:
    """Add a second consumer with their own consent + ACTIVE connection to an
    existing stack's institution and recipient."""
    consent = capture_consent(
        api,
        stack["recipient"]["id"],
        consumer_ref,
        scopes or ["BALANCE"],
        admin_headers=stack["admin"],
    )
    connection = create_pending_connection(
        api, stack["institution"]["id"], consent["id"], consumer_ref, method=method
    )
    connection = activate_connection(api, connection["id"], consumer_ref)
    return {
        "consent": consent,
        "connection": connection,
        "consumer": make_consumer_headers(consumer_ref),
        "consumer_ref": consumer_ref,
    }


# ── Tier 5: deletion flow ───────────────────────────────────────────────────


def open_deletion_request(api: ApiClient, consent_id: str, consumer_ref: str) -> dict:
    return _ok(
        api.create_deletion_request(consent_id, make_consumer_headers(consumer_ref)),
        "open deletion request",
    )


def recipient_headers_for(stack_or_recipient) -> Dict[str, str]:
    """Entity-backed Recipient headers keyed on the recipient row's id."""
    recipient = stack_or_recipient.get("recipient", stack_or_recipient)
    return make_recipient_headers(recipient["id"])
