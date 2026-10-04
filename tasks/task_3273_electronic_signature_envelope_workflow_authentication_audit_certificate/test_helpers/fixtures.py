"""Composite setup helpers for the Esign Envelope Workflow API.

Every helper builds a precondition from scratch using only declared endpoints,
because the server is restarted before every individual test.  Setup uses the
lenient ``get_success_data`` validator so a broken precondition surfaces as a
clear "Setup failed" error rather than a confusing assertion failure.

Ownership threading: after an ``Account`` or ``Recipient`` row is created, any
ownership-gated call uses ``make_account_headers(account_id)`` /
``make_recipient_headers(recipient_id)`` — never the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_EPOCH, TEST_ACCOUNT_NAME
from .factories import (
    authenticate_payload,
    create_account_payload,
    create_bulk_send_payload,
    create_document_payload,
    create_envelope_payload,
    create_field_payload,
    create_recipient_payload,
    create_retention_policy_payload,
    create_session_payload,
    create_template_payload,
    clock_payload,
    credit_adjustment_payload,
    legal_hold_payload,
    void_payload,
)
from .test_users import make_account_headers, make_platform_admin_headers, make_recipient_headers

ADMIN = make_platform_admin_headers()
ADMIN_HEADERS = ADMIN


def _ok(response, what: str) -> dict:
    """Unwrap a setup response, failing loudly when the precondition is broken."""
    data = get_success_data(response)
    assert isinstance(data, dict), f"Setup failed: {what} returned {type(data).__name__}"
    return data


# ---------------------------------------------------------------------------
# Tier 1: primitives and state progression
# ---------------------------------------------------------------------------
def create_admin_account(
    credit_balance: int = 11000,
    name: str = TEST_ACCOUNT_NAME,
    state_code: str = "CA",
    tier: str = "STANDARD",
    page_allowance: int = 25,
    seed: int = None,
) -> dict:
    """Create an account and top its balance up to `credit_balance`.

    The adjustment is issued only to reach the requested balance, so callers
    that ask for less than the 1000 default still land exactly where asked.
    """
    account = _ok(
        api_client.create_account(
            create_account_payload(
                name=name, state_code=state_code, tier=tier, page_allowance=page_allowance
            ),
            ADMIN,
        ),
        "create account",
    )
    delta = credit_balance - account["credit_balance"]
    if delta != 0:
        account = _ok(
            api_client.adjust_account_credit(
                account["id"], credit_adjustment_payload(delta, reason="seed for tests"), ADMIN
            ),
            "seed account credit",
        )
    return account


def setup_account_and_policy(
    credit_balance: int = 11000,
    state_code: str = "CA",
    tier: str = "STANDARD",
    page_allowance: int = 25,
    scope: str = "GLOBAL",
    retention_years: int = 3,
    purge_mode: str = "ANONYMIZE_METADATA",
    purge_grace_days: int = 0,
) -> tuple:
    """Create one account and one retention policy. Returns (account, policy)."""
    account = create_admin_account(
        credit_balance=credit_balance,
        state_code=state_code,
        tier=tier,
        page_allowance=page_allowance,
    )
    policy = _ok(
        api_client.create_retention_policy(
            create_retention_policy_payload(
                scope=scope,
                retention_years=retention_years,
                purge_mode=purge_mode,
                purge_grace_days=purge_grace_days,
            ),
            ADMIN,
        ),
        "create retention policy",
    )
    return account, policy


def set_clock(to_iso8601: str = CLOCK_EPOCH) -> dict:
    """Advance the server logical clock and return the new current instant."""
    return _ok(api_client.set_current_utc(clock_payload(to_iso8601), ADMIN), "set clock")


def create_draft_envelope(
    account: dict,
    policy: dict,
    subject: str = "Test Envelope",
    routing_mode: str = "SEQUENTIAL",
    expires_after_days: int = 120,
    sender_visible_window_days: int = 30,
    **overrides,
) -> dict:
    """Create an envelope owned by `account`. Returns the CREATED envelope."""
    return _ok(
        api_client.create_envelope(
            create_envelope_payload(
                sender_account_id=account["id"],
                retention_policy_id=policy["id"],
                subject=subject,
                routing_mode=routing_mode,
                expires_after_days=expires_after_days,
                sender_visible_window_days=sender_visible_window_days,
                **overrides,
            ),
            make_account_headers(account["id"]),
        ),
        "create envelope",
    )


def add_document(envelope: dict, account: dict, name: str = "Document.pdf", page_count: int = 3) -> dict:
    """Assemble one document into the envelope."""
    return _ok(
        api_client.add_document(
            envelope["id"],
            create_document_payload(name=name, page_count=page_count),
            make_account_headers(account["id"]),
        ),
        f"add document {name}",
    )


def add_recipient(envelope: dict, account: dict, **overrides) -> dict:
    """Add one recipient to the envelope."""
    return _ok(
        api_client.add_recipient(
            envelope["id"],
            create_recipient_payload(**overrides),
            make_account_headers(account["id"]),
        ),
        "add recipient",
    )


def place_field(envelope: dict, account: dict, document: dict, recipient: dict, **overrides) -> dict:
    """Place one signing field on `document` for `recipient`."""
    return _ok(
        api_client.place_field(
            envelope["id"],
            create_field_payload(document["id"], recipient["id"], **overrides),
            make_account_headers(account["id"]),
        ),
        "place field",
    )


def send_envelope(envelope: dict, account: dict) -> dict:
    """Send the envelope, returning the SENT envelope."""
    return _ok(
        api_client.send_envelope(envelope["id"], make_account_headers(account["id"])),
        "send envelope",
    )


def deliver_envelope(envelope: dict, account: dict) -> dict:
    """Advance the delivery feed so the envelope becomes DELIVERED."""
    return _ok(
        api_client.feed_envelope(
            envelope["id"], {"feed_event": "DELIVERED"}, make_account_headers(account["id"])
        ),
        "deliver envelope",
    )


def open_session(recipient: dict, consent: bool = True) -> dict:
    """Open a signing session for `recipient`."""
    return _ok(
        api_client.open_signing_session(
            recipient["id"],
            create_session_payload(consent),
            make_recipient_headers(recipient["id"]),
        ),
        "open signing session",
    )


def authenticate_recipient(recipient: dict, method: str, **overrides) -> dict:
    """Complete the recipient's authentication challenge."""
    return _ok(
        api_client.authenticate_recipient(
            recipient["id"],
            authenticate_payload(method, **overrides),
            make_recipient_headers(recipient["id"]),
        ),
        f"authenticate recipient by {method}",
    )


def sign_recipient(recipient: dict) -> dict:
    """Sign (or approve) as the recipient."""
    return _ok(
        api_client.sign_recipient(recipient["id"], make_recipient_headers(recipient["id"])),
        "sign recipient",
    )


def get_recipient(recipient_id: str, account: dict) -> dict:
    """Read a recipient row back with the owning account's headers."""
    return _ok(
        api_client.get_recipient(recipient_id, make_account_headers(account["id"])),
        "read recipient",
    )


def get_account(account_id: str) -> dict:
    """Read an account row back as the operator."""
    return _ok(api_client.get_account(account_id, ADMIN), "read account")


# ---------------------------------------------------------------------------
# Tier 1b: minimal single-signer hierarchy (the most common preamble)
# ---------------------------------------------------------------------------
def setup_single_signer_envelope(
    credit_balance: int = 11000,
    subject: str = "Single signer envelope",
    routing_mode: str = "SEQUENTIAL",
    page_count: int = 5,
    auth_level: str = "EMAIL_ACCESS",
    consent_accepted: bool = True,
    expires_after_days: int = 120,
    sender_visible_window_days: int = 30,
    state_code: str = "CA",
    scope: str = "GLOBAL",
    retention_years: int = 3,
    purge_grace_days: int = 0,
    field_overrides: dict = None,
    pin_epoch: bool = False,
) -> dict:
    """Account + policy + envelope + document + one SIGNER + one SIGNATURE field.

    Returns a dict with every entity so tests can reach any of them.  The
    envelope is left in CREATED; callers advance it with `send_envelope`.
    """
    if pin_epoch:
        set_clock(CLOCK_EPOCH)
    account, policy = setup_account_and_policy(
        credit_balance=credit_balance,
        state_code=state_code,
        page_allowance=25,
        scope=scope,
        retention_years=retention_years,
        purge_grace_days=purge_grace_days,
    )
    envelope = create_draft_envelope(
        account,
        policy,
        subject=subject,
        routing_mode=routing_mode,
        expires_after_days=expires_after_days,
        sender_visible_window_days=sender_visible_window_days,
    )
    document = add_document(envelope, account, name="Main.pdf", page_count=page_count)
    recipient = add_recipient(
        envelope,
        account,
        email="signer@example.com",
        routing_order=1,
        auth_level=auth_level,
        consent_accepted=consent_accepted,
    )
    field_payload = dict(field_overrides or {})
    field_payload.setdefault("value", "Signer Name")
    field = place_field(envelope, account, document, recipient, **field_payload)
    return {
        "account": account,
        "policy": policy,
        "envelope": envelope,
        "document": document,
        "recipient": recipient,
        "field": field,
    }


def setup_sent_single_signer(**kwargs) -> dict:
    """`setup_single_signer_envelope` advanced through SENT."""
    ctx = setup_single_signer_envelope(**kwargs)
    ctx["envelope"] = send_envelope(ctx["envelope"], ctx["account"])
    return ctx


def setup_delivered_single_signer(**kwargs) -> dict:
    """`setup_single_signer_envelope` advanced through SENT then DELIVERED."""
    ctx = setup_sent_single_signer(**kwargs)
    ctx["envelope"] = deliver_envelope(ctx["envelope"], ctx["account"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy helpers
# ---------------------------------------------------------------------------
def setup_multi_document_envelope(
    page_counts,
    recipient_specs,
    field_specs=None,
    credit_balance: int = 11000,
    routing_mode: str = "SEQUENTIAL",
    subject: str = "Multi document envelope",
    expires_after_days: int = 120,
    sender_visible_window_days: int = 30,
    state_code: str = "CA",
    scope: str = "GLOBAL",
    retention_years: int = 3,
) -> dict:
    """Account + policy + envelope + N documents + M recipients + fields.

    `page_counts`  — list of page counts, one document each (names D1, D2, ...).
    `recipient_specs` — list of dicts of recipient overrides (role, email,
                        routing_order, auth_level, consent_accepted, ...).
    `field_specs`  — optional list of dicts: {"doc": index, "recipient": index,
                     plus field overrides}.  Defaults to one SIGNATURE field per
                     SIGNER/APPROVER recipient on document 0.
    """
    account, policy = setup_account_and_policy(
        credit_balance=credit_balance,
        state_code=state_code,
        page_allowance=25,
        scope=scope,
        retention_years=retention_years,
    )
    envelope = create_draft_envelope(
        account,
        policy,
        subject=subject,
        routing_mode=routing_mode,
        expires_after_days=expires_after_days,
        sender_visible_window_days=sender_visible_window_days,
    )
    documents = [
        add_document(envelope, account, name=f"D{i + 1}.pdf", page_count=pages)
        for i, pages in enumerate(page_counts)
    ]
    recipients = [add_recipient(envelope, account, **spec) for spec in recipient_specs]

    if field_specs is None:
        field_specs = []
        tab = 1
        for index, spec in enumerate(recipient_specs):
            if spec.get("role", "SIGNER") in ("SIGNER", "APPROVER"):
                field_specs.append(
                    {
                        "doc": 0,
                        "recipient": index,
                        "value": f"Signer {index + 1}",
                        "tab_order": tab,
                    }
                )
                tab += 1

    fields = []
    for spec in field_specs:
        spec = dict(spec)
        doc_index = spec.pop("doc", 0)
        recipient_index = spec.pop("recipient", 0)
        fields.append(
            place_field(
                envelope,
                account,
                documents[doc_index],
                recipients[recipient_index],
                **spec,
            )
        )

    return {
        "account": account,
        "policy": policy,
        "envelope": envelope,
        "documents": documents,
        "recipients": recipients,
        "fields": fields,
    }


def setup_parallel_envelope(recipient_specs, page_counts=(6,), **kwargs) -> dict:
    """A PARALLEL envelope with the supplied recipients."""
    kwargs.setdefault("routing_mode", "PARALLEL")
    return setup_multi_document_envelope(page_counts, recipient_specs, **kwargs)


# ---------------------------------------------------------------------------
# Tier 2b: recipient-in-a-state helpers
# ---------------------------------------------------------------------------
def _spec(**overrides) -> dict:
    spec = {
        "role": "SIGNER",
        "email": "recipient@example.com",
        "routing_order": 1,
        "auth_level": "EMAIL_ACCESS",
        "consent_accepted": True,
    }
    spec.update(overrides)
    return spec


def setup_signing_recipient(
    auth_level: str = "EMAIL_ACCESS",
    authenticate: bool = False,
    consent: bool = True,
    signed_field: bool = True,
    routing_mode: str = "SEQUENTIAL",
    send: bool = True,
    subject: str = "Signing recipient envelope",
    **kwargs,
) -> dict:
    """A recipient ready to sign: SENT envelope, OPEN session, fields filled.

    With `authenticate=True` the recipient is authenticated first (required for
    ACCESS_CODE / KBA / ID_DOCUMENT levels).
    """
    ctx = setup_single_signer_envelope(
        routing_mode=routing_mode,
        auth_level=auth_level,
        subject=subject,
        field_overrides=(
            {"value": "Signer Name", "required": True}
            if signed_field
            else {"value": None, "required": False}
        ),
        **kwargs,
    )
    if send:
        ctx["envelope"] = send_envelope(ctx["envelope"], ctx["account"])
    ctx["recipient"] = get_recipient(ctx["recipient"]["id"], ctx["account"])
    if authenticate:
        ctx["recipient"] = authenticate_recipient(
            ctx["recipient"],
            auth_level,
            **(
                {"access_code": "P-7781"}
                if auth_level == "ACCESS_CODE"
                else {"kba_answers_correct": True}
                if auth_level == "KBA"
                else {"identity_document_verified": True}
                if auth_level == "ID_DOCUMENT"
                else {}
            ),
        )
    ctx["session"] = open_session(ctx["recipient"], consent=consent)
    ctx["recipient"] = get_recipient(ctx["recipient"]["id"], ctx["account"])
    return ctx


def setup_authenticated_signer(
    auth_level: str = "EMAIL_ACCESS",
    consent: bool = True,
    routing_mode: str = "SEQUENTIAL",
    **kwargs,
) -> dict:
    """A recipient that has authenticated and holds an OPEN session."""
    return setup_signing_recipient(
        auth_level=auth_level,
        authenticate=auth_level != "EMAIL_ACCESS",
        consent=consent,
        routing_mode=routing_mode,
        **kwargs,
    )


def setup_signed_envelope(subject: str = "Signed envelope", **kwargs) -> dict:
    """A SEQUENTIAL envelope whose single signer has fully signed."""
    ctx = setup_signing_recipient(subject=subject, **kwargs)
    ctx["recipient"] = sign_recipient(ctx["recipient"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_delivered_all_signed(
    subject: str = "Fully signed envelope",
    auth_level: str = "EMAIL_ACCESS",
    routing_mode: str = "SEQUENTIAL",
    page_count: int = 5,
    **kwargs,
) -> dict:
    """SEQUENTIAL envelope delivered, its signer signed, envelope still DELIVERED."""
    ctx = setup_single_signer_envelope(
        subject=subject,
        routing_mode=routing_mode,
        auth_level=auth_level,
        page_count=page_count,
        **kwargs,
    )
    account = ctx["account"]
    ctx["envelope"] = send_envelope(ctx["envelope"], account)
    ctx["envelope"] = deliver_envelope(ctx["envelope"], account)
    recipient = get_recipient(ctx["recipient"]["id"], account)
    if auth_level != "EMAIL_ACCESS":
        recipient = authenticate_recipient(
            recipient,
            auth_level,
            **(
                {"access_code": "P-7781"}
                if auth_level == "ACCESS_CODE"
                else {"kba_answers_correct": True}
                if auth_level == "KBA"
                else {"identity_document_verified": True}
            ),
        )
    open_session(recipient)
    ctx["recipient"] = sign_recipient(recipient)
    return ctx


def create_and_complete_envelope(subject: str = "Completed envelope", **kwargs) -> dict:
    """Full lifecycle through COMPLETED. For post-seal lockdown assertions."""
    ctx = setup_delivered_all_signed(subject=subject, **kwargs)
    account = ctx["account"]
    envelope = get_success_data(
        api_client.get_envelope(ctx["envelope"]["id"], make_account_headers(account["id"]))
    )
    ctx["envelope"] = _ok(
        api_client.complete_envelope(
            envelope["id"],
            {"expected_envelope_version": envelope["version"]},
            make_account_headers(account["id"]),
        ),
        "complete envelope",
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------
def setup_for_credit_debit(
    page_counts,
    recipient_specs,
    credit_balance: int = 11000,
    routing_mode: str = "PARALLEL",
    state_code: str = "CA",
    **kwargs,
) -> dict:
    """A CREATED envelope shaped so its next send debits a known unit count.

    The balance is seeded before the send so a failing precondition is
    impossible unless a test deliberately asks for it.
    """
    return setup_multi_document_envelope(
        page_counts,
        recipient_specs,
        credit_balance=credit_balance,
        routing_mode=routing_mode,
        state_code=state_code,
        **kwargs,
    )


def setup_account_near_credit_limit(deficit: int = 995, **kwargs) -> dict:
    """An account driven down to 1000 - `deficit` credits."""
    return create_admin_account(credit_balance=1000 - deficit, **kwargs)


def setup_recipient_with_kba_failures(failures: int = 2, subject: str = "KBA boundary envelope") -> dict:
    """A SENT envelope whose KBA signer already carries `failures` KBA failures."""
    ctx = setup_single_signer_envelope(auth_level="KBA", subject=subject)
    account = ctx["account"]
    ctx["envelope"] = send_envelope(ctx["envelope"], account)
    recipient = ctx["recipient"]
    for _ in range(failures):
        recipient = authenticate_recipient(recipient, "KBA", kba_answers_correct=False)
    ctx["recipient"] = recipient
    return ctx


def setup_recipient_with_one_reminder(
    first_reminder_at: str = "2026-09-02T00:00:00Z", **kwargs
) -> dict:
    """A SENT envelope whose single signer has already received one reminder."""
    ctx = setup_single_signer_envelope(pin_epoch=True, **kwargs)
    account = ctx["account"]
    ctx["envelope"] = send_envelope(ctx["envelope"], account)
    set_clock(first_reminder_at)
    ctx["envelope"] = _ok(
        api_client.send_reminders(ctx["envelope"]["id"], make_account_headers(account["id"])),
        "send first reminder",
    )
    ctx["recipient"] = get_recipient(ctx["recipient"]["id"], account)
    return ctx


def setup_expiry_pending_envelope(subject: str = "Scheduled envelope", **kwargs) -> dict:
    """An envelope sent from the epoch with a 30-day expiry, awaiting the clock."""
    kwargs.setdefault("expires_after_days", 30)
    return setup_sent_single_signer(subject=subject, pin_epoch=True, **kwargs)


def setup_risk_peer_envelope(
    peer_auth_level: str = "ACCESS_CODE",
    target_auth_level: str = "EMAIL_ACCESS",
    peer_access_code: str = "P-7781",
    authenticate_peer: bool = True,
    peer_identity_verified: bool = False,
    target_identity_verified: bool = False,
    subject: str = "Risk scoring envelope",
    target_signed_field: bool = True,
    **kwargs,
) -> dict:
    """A PARALLEL envelope with two SIGNERs at routing_order 1.

    The peer authenticates (optionally identity-verified) so the envelope's
    collective risk posture is raised; the target holds an OPEN consented
    session and is ready to sign.
    """
    kwargs.setdefault("routing_mode", "PARALLEL")
    ctx = setup_multi_document_envelope(
        [10],
        [
            _spec(
                email="peer@example.com",
                auth_level=peer_auth_level,
                consent_accepted=True,
                **({"access_code": peer_access_code} if peer_auth_level == "ACCESS_CODE" else {}),
            ),
            _spec(
                email="target@example.com",
                auth_level=target_auth_level,
                consent_accepted=True,
            ),
        ],
        field_specs=[
            {"doc": 0, "recipient": 0, "value": "Peer Name", "tab_order": 1},
            {
                "doc": 0,
                "recipient": 1,
                "value": "Target Name" if target_signed_field else None,
                "required": target_signed_field,
                "tab_order": 2,
            },
        ],
        subject=subject,
        **kwargs,
    )
    account = ctx["account"]
    ctx["envelope"] = send_envelope(ctx["envelope"], account)
    peer, target = ctx["recipients"]

    if authenticate_peer:
        peer = authenticate_recipient(
            peer,
            peer_auth_level,
            **(
                {"access_code": peer_access_code}
                if peer_auth_level == "ACCESS_CODE"
                else {"kba_answers_correct": True}
                if peer_auth_level == "KBA"
                else {"identity_document_verified": True}
                if peer_auth_level == "ID_DOCUMENT"
                else {}
            ),
        )
    if peer_identity_verified:
        peer = authenticate_recipient(peer, peer_auth_level, identity_document_verified=True)
    if target_identity_verified:
        target = authenticate_recipient(target, target_auth_level, identity_document_verified=True)

    target = get_recipient(target["id"], account)
    ctx["peer"] = get_recipient(peer["id"], account)
    ctx["target"] = get_recipient(target["id"], account)
    ctx["session"] = open_session(ctx["target"], consent=True)
    ctx["target"] = get_recipient(target["id"], account)
    return ctx


def setup_sequential_routing_pair(
    first_auth_level: str = "KBA",
    second_auth_level: str = "ID_DOCUMENT",
    first_authenticated: bool = True,
    subject: str = "Routing release envelope",
    **kwargs,
) -> dict:
    """A SENT SEQUENTIAL envelope with a routing_order-1 and a routing_order-2 signer.

    The first recipient is authenticated, consented and holds an OPEN session
    with a filled SIGNATURE field, so it is ready to sign; the second is still
    WAITING.
    """
    ctx = setup_multi_document_envelope(
        [9],
        [
            _spec(
                email="first@example.com",
                routing_order=1,
                auth_level=first_auth_level,
                consent_accepted=True,
            ),
            _spec(
                email="second@example.com",
                routing_order=2,
                auth_level=second_auth_level,
                consent_accepted=True,
            ),
        ],
        subject=subject,
        **kwargs,
    )
    account = ctx["account"]
    ctx["envelope"] = send_envelope(ctx["envelope"], account)
    first, second = ctx["recipients"]
    if first_authenticated:
        first = authenticate_recipient(
            first,
            first_auth_level,
            **(
                {"access_code": "P-7781"}
                if first_auth_level == "ACCESS_CODE"
                else {"kba_answers_correct": True}
                if first_auth_level == "KBA"
                else {"identity_document_verified": True}
                if first_auth_level == "ID_DOCUMENT"
                else {}
            ),
        )
    ctx["first"] = get_recipient(first["id"], account)
    ctx["second"] = get_recipient(second["id"], account)
    ctx["session"] = open_session(ctx["first"], consent=True)
    ctx["first"] = get_recipient(first["id"], account)
    return ctx


def setup_parallel_decline_envelope(subject: str = "Decline cascade envelope") -> dict:
    """A SENT PARALLEL envelope with two SIGNER peers, both with OPEN sessions."""
    ctx = setup_multi_document_envelope(
        [6],
        [
            _spec(email="decliner@example.com", routing_order=1, auth_level="EMAIL_ACCESS"),
            _spec(email="peer@example.com", routing_order=1, auth_level="EMAIL_ACCESS"),
        ],
        subject=subject,
        routing_mode="PARALLEL",
    )
    account = ctx["account"]
    ctx["envelope"] = send_envelope(ctx["envelope"], account)
    decliner, peer = ctx["recipients"]
    ctx["decliner_session"] = open_session(decliner, consent=True)
    ctx["peer_session"] = open_session(peer, consent=True)
    ctx["decliner"] = get_recipient(decliner["id"], account)
    ctx["peer"] = get_recipient(peer["id"], account)
    return ctx


def setup_unsent_draft(subject: str = "Never sent envelope", **kwargs) -> dict:
    """A CREATED envelope with a large document and a recipient, never sent."""
    account, policy = setup_account_and_policy(credit_balance=1000)
    envelope = create_draft_envelope(account, policy, subject=subject, **kwargs)
    document = add_document(envelope, account, name="Big.pdf", page_count=400)
    recipient = add_recipient(envelope, account, email="never@example.com")
    place_field(envelope, account, document, recipient, value="Never")
    return {
        "account": account,
        "policy": policy,
        "envelope": envelope,
        "document": document,
        "recipient": recipient,
    }


def setup_completed_then_ages(
    anchor: str = "2026-09-01T00:00:00Z",
    subject: str = "Overlap envelope",
    scope: str = "GLOBAL",
    retention_years: int = 3,
    purge_grace_days: int = 0,
    state_code: str = "CA",
    age_to: str = None,
) -> dict:
    """An envelope sent on `anchor` and fully sealed, ready for retention checks.

    When `age_to` is supplied the logical clock is advanced there afterwards, so
    a caller can address instants inside the retention window as well as past
    its end.
    """
    set_clock(anchor)
    account, policy = setup_account_and_policy(
        credit_balance=11000,
        state_code=state_code,
        scope=scope,
        retention_years=retention_years,
        purge_grace_days=purge_grace_days,
    )
    envelope = create_draft_envelope(account, policy, subject=subject)
    document = add_document(envelope, account, name="Overlap.pdf", page_count=5)
    recipient = add_recipient(envelope, account, email="overlap@example.com")
    place_field(envelope, account, document, recipient, value="Overlap")
    envelope = send_envelope(envelope, account)
    envelope = deliver_envelope(envelope, account)
    recipient = get_recipient(recipient["id"], account)
    open_session(recipient)
    recipient = sign_recipient(recipient)
    envelope = get_success_data(
        api_client.get_envelope(envelope["id"], make_account_headers(account["id"]))
    )
    envelope = _ok(
        api_client.complete_envelope(
            envelope["id"],
            {"expected_envelope_version": envelope["version"]},
            make_account_headers(account["id"]),
        ),
        "complete envelope",
    )
    if age_to is not None:
        set_clock(age_to)
    return {
        "account": account,
        "policy": policy,
        "envelope": envelope,
        "document": document,
        "recipient": recipient,
    }


def setup_retention_elapsed_envelope(
    anchor: str = "2026-09-01T00:00:00Z",
    retention_years: int = 5,
    purge_grace_days: int = 0,
    scope: str = "GLOBAL",
    subject: str = "Retention elapsed envelope",
) -> dict:
    """A sealed envelope whose retention window has fully elapsed at send time."""
    ctx = setup_completed_then_ages(
        anchor=anchor,
        subject=subject,
        scope=scope,
        retention_years=retention_years,
        purge_grace_days=purge_grace_days,
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: templates, bulk send and terminal states
# ---------------------------------------------------------------------------
def setup_published_template(
    name: str = "Published Template",
    page_count: int = 3,
    role_slot_count: int = 1,
    default_routing_mode: str = "SEQUENTIAL",
    default_auth_level: str = "EMAIL_ACCESS",
    credit_balance: int = 11000,
) -> dict:
    """An account plus one PUBLISHED template owned by it.

    Also creates the `GLOBAL` retention policy a bulk-send row's resulting
    envelope is governed by (PRD §3.1 requires an envelope's
    `retention_policy_id` to resolve).
    """
    account, policy = setup_account_and_policy(credit_balance=credit_balance)
    template = _ok(
        api_client.create_template(
            create_template_payload(
                owning_account_id=account["id"],
                name=name,
                default_routing_mode=default_routing_mode,
                default_auth_level=default_auth_level,
                page_count=page_count,
                role_slot_count=role_slot_count,
            ),
            make_account_headers(account["id"]),
        ),
        "create template",
    )
    template = _ok(
        api_client.publish_template(template["id"], make_account_headers(account["id"])),
        "publish template",
    )
    return {"account": account, "template": template, "policy": policy}


def setup_draft_template(name: str = "Draft Template", **kwargs) -> dict:
    """An account plus one DRAFT template owned by it."""
    account = create_admin_account(credit_balance=kwargs.pop("credit_balance", 11000))
    template = _ok(
        api_client.create_template(
            create_template_payload(owning_account_id=account["id"], name=name, **kwargs),
            make_account_headers(account["id"]),
        ),
        "create template",
    )
    return {"account": account, "template": template}


def setup_bulk_send_batch(
    total_rows: int = 2,
    template_name: str = "Bulk Template",
    role_slot_count: int = 1,
    page_count: int = 3,
    credit_balance: int = 11000,
) -> dict:
    """An account, a PUBLISHED template and a CREATED bulk send batch."""
    built = setup_published_template(
        name=template_name,
        role_slot_count=role_slot_count,
        page_count=page_count,
        credit_balance=credit_balance,
    )
    account, template = built["account"], built["template"]
    batch = _ok(
        api_client.create_bulk_send(
            create_bulk_send_payload(account["id"], template["id"], total_rows),
            make_account_headers(account["id"]),
        ),
        "create bulk send batch",
    )
    return {
        "account": account,
        "template": template,
        "batch": batch,
        "policy": built["policy"],
    }


def setup_voided_envelope(subject: str = "Voided envelope", refund_credit: bool = False) -> dict:
    """A SENT envelope that the sender has voided."""
    ctx = setup_single_signer_envelope(subject=subject)
    account = ctx["account"]
    ctx["envelope"] = send_envelope(ctx["envelope"], account)
    ctx["envelope"] = _ok(
        api_client.void_envelope(
            ctx["envelope"]["id"],
            void_payload(
                ctx["envelope"]["version"],
                void_reason="superseded",
                refund_credit=refund_credit,
            ),
            make_account_headers(account["id"]),
        ),
        "void envelope",
    )
    return ctx


def setup_voided_and_held_envelope(subject: str = "Priority envelope") -> dict:
    """A voided envelope that has then been placed under an open-ended legal hold."""
    ctx = setup_voided_envelope(subject=subject)
    ctx["envelope"] = _ok(
        api_client.set_legal_hold(
            ctx["envelope"]["id"],
            legal_hold_payload(True),
            ADMIN,
        ),
        "place envelope under legal hold",
    )
    return ctx


def setup_legal_held_envelope(
    subject: str = "Held envelope",
    hold_until=None,
    hold_started_at: str = None,
) -> dict:
    """A SENT envelope frozen under a legal hold."""
    ctx = setup_single_signer_envelope(subject=subject)
    account = ctx["account"]
    ctx["envelope"] = send_envelope(ctx["envelope"], account)
    if hold_started_at is not None:
        set_clock(hold_started_at)
    ctx["envelope"] = _ok(
        api_client.set_legal_hold(
            ctx["envelope"]["id"],
            legal_hold_payload(True, hold_until),
            ADMIN,
        ),
        "place envelope under legal hold",
    )
    return ctx


def setup_routing_gap_envelope(subject: str = "Gap envelope", credit_balance: int = 5) -> dict:
    """An account short on credit plus a SEQUENTIAL envelope with a routing gap."""
    account, policy = setup_account_and_policy(credit_balance=credit_balance)
    envelope = create_draft_envelope(account, policy, subject=subject)
    document = add_document(envelope, account, name="Gap.pdf", page_count=320)
    first = add_recipient(envelope, account, email="gap1@example.com", routing_order=1)
    third = add_recipient(envelope, account, email="gap3@example.com", routing_order=3)
    place_field(envelope, account, document, first, value="G1", tab_order=1)
    place_field(envelope, account, document, third, value="G3", tab_order=2)
    return {
        "account": account,
        "policy": policy,
        "envelope": envelope,
        "document": document,
        "first": first,
        "third": third,
    }


def setup_chain_envelope(subject: str = "Chain envelope") -> dict:
    """A DELIVERED envelope so at least two audit events exist."""
    return setup_delivered_single_signer(subject=subject)