"""Aftercare follow-up, time-gated transitions and refund settlement."""
from test_helpers import E, api_client, validate_error, validate_paginated, validate_success
from test_helpers.fixtures import (
    COMPLIANCE,
    MANAGER,
    READER,
    file_and_resolve_incident,
    get_appointment,
    get_customer,
    get_incident,
    get_session,
    make_customer_headers,
    set_clock,
    setup_full_service,
)


def test_aftercare_follow_up_acknowledgement_is_idempotent(api):
    """PRD §3.6: "A successful acknowledgement sets `follow_up_acknowledged` to true."
    PRD §3.6: "The `Customer` role performs this acknowledgement against their own session, and
    the acting caller's `X-User-ID` must be the `id` of the customer that the session belongs to."
    PRD §3.6: "acknowledgement is accepted from `follow_up_reminder_due_at` inclusive until
    `follow_up_reminder_due_at` plus seven days exclusive."

    Design: Corner/cross_cutting/acknowledge_follow_up_twice_is_idempotent
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service(completed_at="2026-09-01T00:00:00Z")
    session_id = ctx["session"]["id"]
    customer_id = ctx["customer"]["id"]

    # The reminder is due at the completion instant plus the aftercare follow-up
    # interval, so acknowledge exactly at the window's opening instant (the
    # inclusive lower boundary) to pin the idempotent behaviour without relying
    # on the interval's unspecified length.
    due_at = get_session(session_id)["follow_up_reminder_due_at"]
    api.set_clock(due_at, COMPLIANCE)
    customer_headers = make_customer_headers(customer_id)

    first = validate_success(api.acknowledge_follow_up(session_id, customer_headers), 200)
    assert first["follow_up_acknowledged"] is True

    second = validate_success(api.acknowledge_follow_up(session_id, customer_headers), 200)
    assert second["follow_up_acknowledged"] is True

    assert get_session(session_id)["follow_up_acknowledged"] is True


def test_follow_up_acknowledgement_before_the_due_instant_is_rejected(api):
    """PRD §3.6: "The follow-up reminder is due at `follow_up_reminder_due_at`, and the customer
    may acknowledge it only within a bounded window: acknowledgement is accepted from
    `follow_up_reminder_due_at` inclusive until `follow_up_reminder_due_at` plus seven days
    exclusive."
    PRD §3.6: "Outside that window — earlier than the due instant, or at or after the seven-day
    close — acknowledgement is refused with `ERR_FOLLOW_UP_NOT_DUE` at HTTP 409."

    Design: Corner/cross_cutting/follow_up_acknowledgement_before_due_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service(completed_at="2026-09-01T00:00:00Z")

    # One day after completion: still earlier than the due instant.
    api.set_clock("2026-09-02T00:00:00Z", COMPLIANCE)
    res = api.acknowledge_follow_up(
        ctx["session"]["id"], make_customer_headers(ctx["customer"]["id"])
    )
    validate_error(res, E.FOLLOW_UP_NOT_DUE, expected_status=409)
    assert get_session(ctx["session"]["id"])["follow_up_acknowledged"] is False


def test_no_show_fires_once_the_clock_passes_the_slot_end(api):
    """PRD §3.3: "An appointment that is still `CONFIRMED` once the clock passes `slot_end_at`
    is marked `NO_SHOW` automatically, and that boundary is exclusive, so an appointment whose
    slot ends at the current instant is not yet a no-show".

    Design: Corner/cross_cutting/no_show_transition_fires_after_slot_end
    """
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers.fixtures import (
        certify,
        create_jurisdiction,
        create_piercer,
        create_store,
        setup_customer_with_active_consent,
        setup_ready_appointment,
    )

    jurisdiction = create_jurisdiction(permitted_sites=["LOBE"])
    store = create_store(jurisdiction["id"], piercing_room_count=1)
    piercer = create_piercer(store["id"])
    certify(piercer["id"])
    customer, _ = setup_customer_with_active_consent(jurisdiction["id"])

    appointment = setup_ready_appointment(
        store["id"], customer["id"], piercer["id"], jurisdiction["id"],
        slot_start="2026-09-01T09:00:00Z", slot_end="2026-09-01T09:30:00Z",
    )
    assert appointment["status"] == "CONFIRMED"

    api.set_clock("2026-09-01T10:00:00Z", COMPLIANCE)
    assert get_appointment(appointment["id"])["status"] == "NO_SHOW"


def test_refund_settlement_is_visible_in_the_same_response(api):
    """PRD §3.7: "On success `escalation_status` becomes `REFUND_ISSUED` and `refund_status`
    becomes `SETTLED`; the customer's `refunded_cents` increases by `refund_amount_cents`, and
    the customer's `retained_cents` increases by the session's `net_fee_cents` minus
    `refund_amount_cents`."

    Design: Corner/consistency_model/refund_settlement_visible_in_the_same_response
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service()
    incident = file_and_resolve_incident(ctx["session"], severity="SEVERE")
    refund_amount = incident["refund_amount_cents"]
    net_fee = ctx["session"]["net_fee_cents"]
    assert refund_amount > 0

    settled = validate_success(
        api.issue_refund(incident["id"], {"refund_destination": "CARD"}, MANAGER), 200
    )
    assert settled["refund_status"] == "SETTLED"
    assert settled["escalation_status"] == "REFUND_ISSUED"

    # The customer ledger is already reconciled when the settlement returns.
    customer = get_customer(ctx["customer"]["id"])
    assert customer["refunded_cents"] == refund_amount
    assert customer["retained_cents"] == net_fee - refund_amount
    assert customer["refunded_cents"] + customer["retained_cents"] == net_fee


def test_store_incident_listing_reaches_incidents_through_sessions(api):
    """PRD §2.7: "Posture is recomputed by the calculation `store_posture_computation`, which
    counts, over the incidents reachable through the store's sessions, those whose
    `escalation_status` is `LOGGED`, `TRIAGED`, `ESCALATED` or `REOPENED`".
    PRD §2.7: "this count is the store's `open_incident_count`".

    Design: Corner/endpoints/store_incident_listing_reaches_incidents_through_sessions
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service()
    from test_helpers.fixtures import file_and_triage_incident

    incident = file_and_triage_incident(ctx["session"], severity="MINOR", reported_at="2026-09-10T00:00:00Z")
    assert incident["escalation_status"] == "TRIAGED"

    data, meta = validate_paginated(api.list_store_incidents(ctx["store"]["id"], READER))
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["session_id"] == ctx["session"]["id"]
    from test_helpers.fixtures import get_store
    assert get_store(ctx["store"]["id"])["open_incident_count"] == 1