"""Composite setup helpers.

Every fixture builds its preconditions from scratch against a freshly restarted
server (the harness re-launches the API before each test), using only
PRD-declared endpoints. Lenient get_success_data() is used internally so a
broken precondition surfaces as a clear setup failure rather than a confusing
assertion error. Ownership-gated calls thread entity ids through
make_firm_admin_headers / make_researcher_headers (PRD §2.1).
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import SEPT_PERIOD_END, SEPT_PERIOD_START
from .factories import (
    account_payload,
    document_payload,
    flat_plan_payload,
    headnote_payload,
    invoice_window_payload,
    license_agreement_payload,
    reference_entry,
    removal_order_payload,
    royalty_statement_payload,
    subscription_payload,
    transactional_plan_payload,
    usage_event_payload,
)
from .test_users import (
    EDITOR_AUTHOR,
    EDITOR_REVIEWER,
    TEST_USERS,
    make_attorney_editor_headers,
    make_firm_admin_headers,
    make_researcher_headers,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_INGESTER = TEST_USERS["content_ingester_headers"]
_ANALYST = TEST_USERS["citator_analyst_headers"]
_LICENSING = TEST_USERS["licensing_manager_headers"]
_BILLING = TEST_USERS["billing_admin_headers"]
_COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# --- Logical clock (PRD §2.4) ---

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, _ADMIN))


def _parse_iso(instant: str) -> datetime:
    return datetime.fromisoformat(instant.replace("Z", "+00:00")).astimezone(timezone.utc)


def _fmt_iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def advance_clock_days_past(instant: str, days: int) -> str:
    """Move the logical clock `days` after the given instant; returns new reading."""
    target = _fmt_iso(_parse_iso(instant) + timedelta(days=days))
    set_clock(target)
    return target


# --- Documents, citation graph, citator (PRD §3.1/§3.2) ---

def create_document(**overrides) -> dict:
    return get_success_data(api_client.create_document(document_payload(**overrides), _INGESTER))


def publish_document(document_id: str, references=None) -> dict:
    payload = {"references": references if references is not None else []}
    return get_success_data(api_client.publish_document(document_id, payload, _INGESTER))


def create_published_document(references=None, **overrides) -> dict:
    doc = create_document(**overrides)
    return publish_document(doc["id"], references)


def create_citing_document(cited_document_id: str, treatment: str, depth: str, **overrides) -> dict:
    """Publish a fresh document that cites `cited_document_id` with the given
    treatment/depth; the publish cascade recomputes the cited document's
    citator fields (PRD §3.1)."""
    return create_published_document(
        references=[reference_entry(cited_document_id, treatment, depth)],
        **overrides,
    )


def get_document(document_id: str) -> dict:
    return get_success_data(api_client.get_document(document_id, _INGESTER))


def list_citing_references(document_id: str, direction=None, status=None) -> list:
    params = {}
    if direction is not None:
        params["direction"] = direction
    if status is not None:
        params["status"] = status
    return get_success_data(api_client.list_citing_references(document_id, _INGESTER, params=params))


def citator_override(document_id: str, override_signal: str, expected_document_version: int, rationale=None) -> dict:
    payload = {"override_signal": override_signal, "expected_document_version": expected_document_version}
    if rationale is not None:
        payload["rationale"] = rationale
    return get_success_data(api_client.citator_override(document_id, payload, _ANALYST))


# --- Headnotes (PRD §3.3) ---

def create_headnote(document_id: str, author_id: str = EDITOR_AUTHOR, **overrides) -> dict:
    return get_success_data(
        api_client.create_headnote(document_id, headnote_payload(**overrides), make_attorney_editor_headers(author_id))
    )


def submit_headnote(headnote_id: str, author_id: str = EDITOR_AUTHOR) -> dict:
    return get_success_data(api_client.submit_headnote(headnote_id, make_attorney_editor_headers(author_id)))


def decide_headnote(headnote_id: str, reviewer_id: str = EDITOR_REVIEWER, decision: str = "APPROVE", review_note=None) -> dict:
    payload = {"decision": decision}
    if review_note is not None:
        payload["review_note"] = review_note
    return get_success_data(api_client.decide_headnote(headnote_id, payload, make_attorney_editor_headers(reviewer_id)))


def get_headnote(headnote_id: str) -> dict:
    return get_success_data(api_client.get_headnote(headnote_id, make_attorney_editor_headers(EDITOR_AUTHOR)))


def create_published_headnote(document_id: str, author_id: str = EDITOR_AUTHOR, reviewer_id: str = EDITOR_REVIEWER) -> dict:
    headnote = create_headnote(document_id, author_id)
    submit_headnote(headnote["id"], author_id)
    return decide_headnote(headnote["id"], reviewer_id, "APPROVE", review_note="ok")


# --- Commercial onboarding (PRD §3.4) ---

def create_plan(flat: bool = True, **overrides) -> dict:
    base = flat_plan_payload(**overrides) if flat else transactional_plan_payload(**overrides)
    return get_success_data(api_client.create_plan(base, _LICENSING))


def create_account(**overrides) -> dict:
    return get_success_data(api_client.create_account(account_payload(**overrides), _LICENSING))


def create_subscription(account_id: str, plan_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_subscription(subscription_payload(account_id, plan_id, **overrides), _LICENSING))


def get_subscription(subscription_id: str) -> dict:
    return get_success_data(api_client.get_subscription(subscription_id, _LICENSING))


def assign_seat(subscription_id: str, account_id: str, email=None, full_name="Seat User") -> dict:
    """ASSIGN a seat (atomically creating the SubscriberUser) and return the
    created user row. FirmAdmin identity is the owning account id (PRD §2.1)."""
    if email is None:
        email = f"user-{subscription_id[:8]}-{full_name.replace(' ', '').lower()}@example.com"
    headers = make_firm_admin_headers(account_id)
    get_success_data(api_client.manage_seats(
        subscription_id,
        {"action": "ASSIGN", "user_email": email, "user_full_name": full_name},
        headers,
    ))
    users = get_success_data(api_client.list_users(_LICENSING, params={"account_id": account_id}))
    matches = [u for u in users if u["email"] == email]
    assert len(matches) == 1, f"Setup failed: expected exactly one user with {email}, got {len(matches)}"
    return matches[0]


def release_seat(subscription_id: str, account_id: str, user_id: str) -> dict:
    return get_success_data(api_client.manage_seats(
        subscription_id,
        {"action": "RELEASE", "user_id": user_id},
        make_firm_admin_headers(account_id),
    ))


def list_users(account_id=None, seat_subscription_id=None) -> list:
    params = {}
    if account_id is not None:
        params["account_id"] = account_id
    if seat_subscription_id is not None:
        params["seat_subscription_id"] = seat_subscription_id
    return get_success_data(api_client.list_users(_LICENSING, params=params))


def get_user(user_id: str) -> dict:
    return get_success_data(api_client.get_user(user_id, _LICENSING))


# --- Metered usage (PRD §3.5) ---

def record_usage(user_id: str, event_type: str = "SEARCH", count: int = 1,
                 practice_area_tag: str = "LITIGATION", matter_code=None,
                 license_agreement_id=None) -> list:
    events = []
    for _ in range(count):
        payload = usage_event_payload(event_type=event_type, practice_area_tag=practice_area_tag)
        if matter_code is not None:
            payload["matter_code"] = matter_code
        if license_agreement_id is not None:
            payload["license_agreement_id"] = license_agreement_id
        events.append(get_success_data(api_client.create_usage_event(payload, make_researcher_headers(user_id))))
    return events


def setup_subscribed_user(plan_overrides=None, account_overrides=None, flat: bool = True,
                          seats_total: int = 1, period_start: str = SEPT_PERIOD_START,
                          period_end: str = SEPT_PERIOD_END, searches: int = 0,
                          doc_views: int = 0, practice_area_tag: str = "LITIGATION",
                          matter_code=None, license_agreement_id=None,
                          user_email=None) -> dict:
    """Plan + account + ACTIVE subscription + one seated user, with optional
    pre-recorded usage. Returns dict(plan, account, subscription, user, events)."""
    plan = create_plan(flat=flat, **(plan_overrides or {}))
    account = create_account(**(account_overrides or {}))
    subscription = create_subscription(
        account["id"], plan["id"], period_start=period_start, period_end=period_end,
        seats_total=seats_total,
    )
    user = assign_seat(subscription["id"], account["id"], email=user_email)
    events = []
    events += record_usage(user["id"], "SEARCH", searches, practice_area_tag, matter_code, license_agreement_id)
    events += record_usage(user["id"], "DOC_VIEW", doc_views, practice_area_tag, matter_code, license_agreement_id)
    return {"plan": plan, "account": account, "subscription": subscription, "user": user, "events": events}


# --- Invoices (PRD §3.6) ---

def generate_invoice(subscription_id: str, period_start: str = SEPT_PERIOD_START,
                     period_end: str = SEPT_PERIOD_END) -> dict:
    return get_success_data(api_client.generate_invoice(
        invoice_window_payload(subscription_id, period_start=period_start, period_end=period_end),
        _BILLING,
    ))


def transition_invoice(invoice_id: str, target_status: str) -> dict:
    return get_success_data(api_client.transition_invoice(invoice_id, {"target_status": target_status}, _BILLING))


def issue_invoice(invoice_id: str) -> dict:
    return transition_invoice(invoice_id, "ISSUED")


def get_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.get_invoice(invoice_id, _BILLING))


def setup_issued_invoice(plan_overrides=None, searches: int = 1, doc_views: int = 0,
                         clock_iso: str = "2026-09-10T00:00:00Z", **kwargs) -> dict:
    """Billing scenario through an ISSUED September invoice. Returns the
    setup_subscribed_user context plus the invoice under ctx["invoice"]."""
    set_clock(clock_iso)
    ctx = setup_subscribed_user(plan_overrides=plan_overrides, searches=searches,
                                doc_views=doc_views, **kwargs)
    ctx["invoice"] = issue_invoice(generate_invoice(ctx["subscription"]["id"])["id"])
    return ctx


# --- License agreements and royalties (PRD §3.7) ---

def create_license_agreement(**overrides) -> dict:
    return get_success_data(api_client.create_license_agreement(license_agreement_payload(**overrides), _LICENSING))


def terminate_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.terminate_agreement(agreement_id, _LICENSING))


def generate_royalty_statement(license_agreement_id: str, period_start: str = SEPT_PERIOD_START,
                               period_end: str = SEPT_PERIOD_END) -> dict:
    return get_success_data(api_client.generate_royalty_statement(
        royalty_statement_payload(license_agreement_id, period_start=period_start, period_end=period_end),
        _BILLING,
    ))


# --- Removal orders and compliance cascades (PRD §3.8) ---

def create_removal_order(document_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_removal_order(removal_order_payload(document_id, **overrides), _COMPLIANCE))


def transition_removal_order(order_id: str, target_status: str) -> dict:
    return get_success_data(api_client.transition_removal_order(order_id, {"target_status": target_status}, _COMPLIANCE))


def apply_removal_order(order_id: str) -> dict:
    return transition_removal_order(order_id, "APPLIED")


def reverse_removal_order(order_id: str) -> dict:
    return transition_removal_order(order_id, "REVERSED")


def seal_document(document_id: str, scope: str = "SEAL", effective_from: str = "2026-09-01",
                  effective_until: str = "2026-09-30", reason: str = "Court order") -> dict:
    """Docket and apply a removal order against the document; returns the
    APPLIED order. Caller is responsible for the logical clock being on or
    after effective_from (PRD §3.8)."""
    order = create_removal_order(
        document_id, scope=scope, effective_from=effective_from,
        effective_until=effective_until, reason=reason,
    )
    return apply_removal_order(order["id"])
