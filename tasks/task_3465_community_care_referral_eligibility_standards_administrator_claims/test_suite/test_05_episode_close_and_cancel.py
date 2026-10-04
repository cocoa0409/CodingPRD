"""Episode termination: exhaustion, auto-close on documentation acceptance,
owner cancel cascades, clock-driven expiry cascade, and the conserved visit
ledger across reserve / complete / cancel."""
from test_helpers import (
    TEST_USERS, api_client, validate_error, validate_success,
    assert_visit_ledger_conserved,
    accept_documentation, approve_extension, cancel_referral,
    complete_appointment, complete_appointment_with_doc,
    create_extension_request, get_appointment, get_authorization,
    list_extension_requests, make_tpa_admin_headers, schedule_appointment,
    set_clock, setup_closed_episode, setup_episode,
)

COORD = TEST_USERS["care_coordinator_headers"]


def test_terminal_lockdown_cancel_on_closed_referral_returns_invalid_state():
    """PRD §3.3: "A `CareCoordinator`, or the `Veteran` who owns the referral,
    may cancel it from `AUTHORIZED`, `ACTIVE`, or `DOCS_SUSPENDED`; from any
    other status the attempt is rejected with `ERR_INVALID_STATE`, and a
    veteran-role caller whose `X-User-ID` does not match the authorization's
    `veteran_id` is rejected with `ERR_OWNERSHIP_MISMATCH`."
    PRD §3.3: "`CLOSED` and `CANCELLED` are terminal."

    Design: Corner/state_machines/terminal_lockdown_cancel_on_closed_referral_returns_invalid_state
    """
    env = setup_closed_episode()  # exhausted, then auto-closed on doc ACCEPT
    auth = env["authorization"]
    assert auth["status"] == "CLOSED"

    resp = api_client.cancel_referral(auth["id"], COORD)
    validate_error(resp, "ERR_INVALID_STATE")
    assert get_authorization(auth["id"])["status"] == "CLOSED"


def test_exhausted_then_auto_closed_when_docs_accepted():
    """PRD §3.3: "Independently, whenever a completion or cancellation
    recompute drives `remaining_visits` to exactly zero, an `ACTIVE`
    authorization becomes `EXHAUSTED`."
    PRD §3.3: "Either way, if no documentation record of the authorization is
    in `AWAITED`, `RECEIVED`, or `OVERDUE` at that moment, the authorization
    falls straight through to `CLOSED`; otherwise it waits until the last
    non-accepted documentation of the episode becomes `ACCEPTED`, at which
    point `EXPIRED` or `EXHAUSTED` moves to `CLOSED`."

    Design: Corner/state_machines/exhausted_then_auto_closed_when_docs_accepted
    """
    env = setup_episode(authorized_visits=1, duration_days=60)
    auth = env["authorization"]
    appt = schedule_appointment(auth)

    appt, doc = complete_appointment_with_doc(appt, env["provider"])
    mid = get_authorization(auth["id"])
    assert mid["status"] == "EXHAUSTED"  # not CLOSED: documentation AWAITED
    assert mid["remaining_visits"] == 0

    accept_documentation(appt, env["provider"])
    end = get_authorization(auth["id"])
    assert end["status"] == "CLOSED"


def test_referral_cancel_cascades_to_appointments_and_extensions():
    """PRD §3.3: "Cancellation cascades exactly like expiry: every `SCHEDULED`
    appointment becomes `CANCELLED` with its reserved visit released, and every
    `PENDING` extension request is auto-denied with `denial_reason`
    `AUTH_CANCELLED`."
    PRD §3.3: "A `CareCoordinator`, or the `Veteran` who owns the referral, may
    cancel it from `AUTHORIZED`, `ACTIVE`, or `DOCS_SUSPENDED`; from any other
    status the attempt is rejected with `ERR_INVALID_STATE`, and a veteran-role
    caller whose `X-User-ID` does not match the authorization's `veteran_id` is
    rejected with `ERR_OWNERSHIP_MISMATCH`."

    Design: Corner/state_machines/referral_cancel_cascades_to_appointments_and_extensions
    """
    env = setup_episode(authorized_visits=2, duration_days=60)
    auth = env["authorization"]
    appt = schedule_appointment(auth)
    ext = create_extension_request(auth, requested_visits=2,
                                   requested_extra_days=0)

    cancelled = cancel_referral(auth, veteran=env["veteran"])
    assert cancelled["status"] == "CANCELLED"

    assert get_appointment(appt["id"])["status"] == "CANCELLED"
    exts, _meta = list_extension_requests(auth["id"])
    assert exts[0]["id"] == ext["id"]
    assert exts[0]["status"] == "DENIED"
    assert exts[0]["denial_reason"] == "AUTH_CANCELLED"
    after = get_authorization(auth["id"])
    assert after["reserved_visits"] == 0
    assert after["remaining_visits"] == 2


def test_referral_expiry_cascade_on_clock_crossing():
    """PRD §3.3: "When a logical-clock set finds an `AUTHORIZED` or `ACTIVE`
    authorization whose current date has reached or passed
    `end_date_exclusive` with `remaining_visits` still above zero, the episode
    transitions to `EXPIRED`: every `SCHEDULED` appointment on it is cancelled
    (releasing its reserved visit), `remaining_visits` is recomputed per
    cancellation, and every `PENDING` extension request is auto-denied with
    `denial_reason` `AUTH_CANCELLED`."
    PRD §3.3: "Either way, if no documentation record of the authorization is
    in `AWAITED`, `RECEIVED`, or `OVERDUE` at that moment, the authorization
    falls straight through to `CLOSED`; otherwise it waits until the last
    non-accepted documentation of the episode becomes `ACCEPTED`, at which
    point `EXPIRED` or `EXHAUSTED` moves to `CLOSED`."

    Design: Corner/state_machines/referral_expiry_cascade_on_clock_crossing
    """
    env = setup_episode(authorized_visits=2, duration_days=10)
    auth = env["authorization"]
    appt = schedule_appointment(auth)
    ext = create_extension_request(auth, requested_visits=2,
                                   requested_extra_days=5)

    # Episode window is [2026-09-05, 2026-09-15); the 09-15 clock set crosses
    # the half-open boundary. No documentation exists, so EXPIRED falls
    # straight through to CLOSED.
    set_clock("2026-09-15T00:00:00Z")

    after = get_authorization(auth["id"])
    assert after["status"] == "CLOSED"
    assert after["reserved_visits"] == 0
    assert after["remaining_visits"] == 2
    assert get_appointment(appt["id"])["status"] == "CANCELLED"
    exts, _meta = list_extension_requests(auth["id"])
    assert exts[0]["status"] == "DENIED"
    assert exts[0]["denial_reason"] == "AUTH_CANCELLED"


def test_visit_ledger_conserved_across_create_complete_cancel():
    """PRD §2.10: "First, the visit ledger of every authorization always
    balances: `authorized_visits` plus `extended_visits` equals
    `completed_visits` plus `reserved_visits` plus `remaining_visits`."
    PRD §2.10: "Scheduling an appointment is the forward action (the reserved
    count rises by one and the remaining count falls by one); cancelling a
    scheduled appointment is the compensating action (the reserved count falls
    by one and the remaining count rises by one)."

    Design: Difficulty/compensating_invariant/visit_ledger_conserved_across_create_complete_cancel
    """
    env = setup_episode(authorized_visits=2, duration_days=60)
    auth = env["authorization"]
    ext = create_extension_request(auth, requested_visits=3,
                                   requested_extra_days=0)
    approve_extension(auth["id"], ext["id"])

    ap_a = schedule_appointment(auth, scheduled_start="2026-09-06T10:00:00Z")
    ap_b = schedule_appointment(auth, scheduled_start="2026-09-07T10:00:00Z")
    s1 = get_authorization(auth["id"])
    assert (s1["reserved_visits"], s1["completed_visits"],
            s1["remaining_visits"]) == (2, 0, 3)  # 2 + 3 == 0 + 2 + 3
    assert_visit_ledger_conserved(s1)

    complete_appointment(ap_a, env["provider"])
    s2 = get_authorization(auth["id"])
    assert (s2["reserved_visits"], s2["completed_visits"],
            s2["remaining_visits"]) == (1, 1, 3)  # 2 + 3 == 1 + 1 + 3
    assert_visit_ledger_conserved(s2)

    resp = api_client.cancel_appointment(
        ap_b["id"], make_tpa_admin_headers(env["tpa"]["id"])
    )
    validate_success(resp, 200)
    s3 = get_authorization(auth["id"])
    assert (s3["reserved_visits"], s3["completed_visits"],
            s3["remaining_visits"]) == (0, 1, 4)  # 2 + 3 == 1 + 0 + 4
    assert_visit_ledger_conserved(s3)
    assert s3["extended_visits"] == 3 and s3["authorized_visits"] == 2
