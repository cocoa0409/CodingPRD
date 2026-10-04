"""Medical clearances: request guards, decision guards, the CONDITIONAL
ruling, the TRAVEL ready gate, and the revoke/hold/restore loop.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_medical_clearance,
    clear_travel_wish,
    complete_event,
    create_medical_clearance_payload,
    create_wish_event_payload,
    decide_clearance,
    get_chapter,
    get_wish,
    request_clearance,
    revoke_clearance,
    schedule_event,
    setup_approved_wish,
    setup_determined_wish,
    setup_scheduled_wish,
    validate_error,
    validate_paginated,
    validate_success,
)

WISH_COORDINATOR = TEST_USERS["wish_coordinator_headers"]
MEDICAL_PROVIDER = TEST_USERS["medical_provider_headers"]


def test_clearance_decide_after_denied_rejected():
    """PRD section 3.7: "Asking for any of these three rulings on a clearance
    that has left `PENDING`, or asking for `REVOKED` on a clearance that is
    not in `CLEARED` or `CONDITIONAL`, fails with `ERR_INVALID_CLEARANCE_STATE`
    (HTTP 409)."

    Design: Corner/state_machines/clearance_decide_after_denied_rejected
    """
    ctx = setup_determined_wish(wish_type="TRAVEL",
                                captured_true_wish="fly to the ocean")
    clearance = request_clearance(ctx["wish"]["id"])
    decide_clearance(clearance["id"], "DENIED", decision_note="not fit to fly")

    resp = api_client.decide_clearance(
        clearance["id"], {"decision": "CLEARED", "valid_until": "2026-12-31"},
        MEDICAL_PROVIDER)
    validate_error(resp, ApiErrorId.ERR_INVALID_CLEARANCE_STATE)


def test_clearance_conditional_requires_accommodations_and_opens_gate():
    """PRD section 3.7: "`CONDITIONAL` requires both `valid_until` and a
    non-empty `accommodations` array describing needs such as wheelchair,
    oxygen, or ground-transport-only; missing decision-conditional fields make
    the request malformed (`ERR_INVALID_REQUEST`). Either ruling increments
    the clearance's `version` and re-evaluates the travel gate immediately, in
    the same request: a wish sitting in `PLAN_APPROVED` advances to
    `READY_TO_SCHEDULE`"

    Design: Corner/state_machines/clearance_conditional_requires_accommodations_and_opens_gate
    """
    ctx = setup_approved_wish(wish_type="TRAVEL",
                              captured_true_wish="fly to the ocean",
                              cash_cost_cents=100000)
    wish = ctx["wish"]
    assert wish["status"] == "PLAN_APPROVED"
    clearance = request_clearance(wish["id"])

    malformed = api_client.decide_clearance(
        clearance["id"], {"decision": "CONDITIONAL",
                          "valid_until": "2026-12-31"},
        MEDICAL_PROVIDER)
    validate_error(malformed, ApiErrorId.ERR_INVALID_REQUEST)

    decided = decide_clearance(
        clearance["id"], "CONDITIONAL", valid_until="2026-12-31",
        accommodations=["wheelchair", "ground-transport-only"])
    assert_medical_clearance(decided)
    assert decided["status"] == "CONDITIONAL"
    assert decided["accommodations"] == ["wheelchair", "ground-transport-only"]
    assert get_wish(wish["id"])["status"] == "READY_TO_SCHEDULE", (
        "CONDITIONAL satisfies the TRAVEL ready gate identically to CLEARED"
    )


def test_clearance_request_for_non_travel_wish_rejected():
    """PRD section 3.7: "The wish must be of type `TRAVEL` — requesting a
    clearance for any other wish type is rejected with
    `ERR_WISH_TYPE_NO_CLEARANCE` (HTTP 422)"

    Design: Corner/validations/clearance_request_for_non_travel_wish_rejected
    """
    ctx = setup_determined_wish(wish_type="RECEIVE_ITEM",
                                captured_true_wish="a treehouse")
    resp = api_client.create_medical_clearance(
        create_medical_clearance_payload(ctx["wish"]["id"]), WISH_COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_WISH_TYPE_NO_CLEARANCE)


def test_clearance_second_active_request_rejected():
    """PRD section 3.7: "At most one clearance per wish may be live at a time:
    when a clearance already exists in `PENDING`, `CLEARED`, or `CONDITIONAL`,
    a new request fails with `ERR_CLEARANCE_ALREADY_ACTIVE` (HTTP 409)."

    Design: Corner/validations/clearance_second_active_request_rejected
    """
    ctx = setup_determined_wish(wish_type="TRAVEL",
                                captured_true_wish="fly to the ocean")
    wish = ctx["wish"]
    first = request_clearance(wish["id"])
    assert first["status"] == "PENDING"

    resp = api_client.create_medical_clearance(
        create_medical_clearance_payload(wish["id"]), WISH_COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_CLEARANCE_ALREADY_ACTIVE)

    listed = api_client.list_wish_clearances(wish["id"], WISH_COORDINATOR)
    _, meta = validate_paginated(listed)
    assert meta["total_count"] == 1


def test_medical_hold_revoke_and_restore_loop():
    """PRD section 3.7: "A provider may revoke a `CLEARED` or a `CONDITIONAL`
    clearance — both from-states behave identically — and the hold cascade
    fires: the wish, whether in `PLAN_APPROVED`, `READY_TO_SCHEDULE`, or
    `SCHEDULED`, drops to `MEDICAL_HOLD` with a version increment and records
    a `hold_return_state` — `PLAN_APPROVED` when the wish had advanced no
    further than its approval, and `READY_TO_SCHEDULE` otherwise. For a
    `SCHEDULED` wish the return state is also `READY_TO_SCHEDULE`, because the
    event itself is lost: every `SCHEDULED` wish event of the held wish is
    cancelled to `CANCELLED`, each with a version increment. When a later
    `CLEARED` or `CONDITIONAL` ruling arrives — necessarily on a new
    clearance, since a revoked one is terminal — the wish lifts out of
    `MEDICAL_HOLD` back to the recorded return state, and `hold_return_state`
    is cleared to null."

    Design: Corner/state_machines/medical_hold_revoke_and_restore_loop
    """
    ctx = setup_scheduled_wish(wish_type="TRAVEL",
                               captured_true_wish="fly to the ocean",
                               cash_cost_cents=100000)
    wish = ctx["wish"]
    clearance1 = ctx["clearance"]
    event1 = ctx["event"]
    assert wish["status"] == "SCHEDULED"

    revoke_clearance(clearance1["id"])
    held = get_wish(wish["id"])
    assert held["status"] == "MEDICAL_HOLD"
    events_resp = api_client.list_wish_events(wish["id"], WISH_COORDINATOR)
    items, _ = validate_paginated(events_resp)
    cancelled = [e for e in items if e["id"] == event1["id"]]
    assert cancelled and cancelled[0]["status"] == "CANCELLED", (
        "the hold cascade cancels the wish's SCHEDULED events"
    )

    clearance2 = request_clearance(wish["id"])
    decide_clearance(clearance2["id"], "CONDITIONAL",
                     valid_until="2026-12-31", accommodations=["wheelchair"])
    restored = get_wish(wish["id"])
    assert restored["status"] == "READY_TO_SCHEDULE", (
        "the hold lifts back to the recorded return state (SCHEDULED "
        f"collapses to READY_TO_SCHEDULE because its event was lost), got "
        f"{restored['status']}"
    )

    event2 = schedule_event(wish["id"], "2026-10-05", "2026-10-06")
    complete_event(event2["id"])
    assert get_wish(wish["id"])["status"] == "GRANTED"
    chapter = get_chapter(ctx["chapter"]["id"])
    assert chapter["granted_cost_total_cents"] == 100000, (
        "the plan was never released by the hold: the grant books its full "
        f"total, got {chapter['granted_cost_total_cents']}"
    )


def test_travel_event_blocked_while_wish_plan_approved():
    """PRD section 3.6: "A `TRAVEL` wish waits in `PLAN_APPROVED` until a
    medical clearance satisfies its gate (§3.7)."
    PRD section 3.8: "the wish must be `READY_TO_SCHEDULE`, otherwise
    `ERR_INVALID_WISH_STATE`"

    Design: Difficulty/cross_entity_state_dependency/travel_event_gated_by_clearance_state
    """
    ctx = setup_approved_wish(wish_type="TRAVEL",
                              captured_true_wish="fly to the ocean",
                              cash_cost_cents=100000)
    wish = get_wish(ctx["wish"]["id"])
    assert wish["status"] == "PLAN_APPROVED", (
        "without a clearance the TRAVEL gate holds the wish at PLAN_APPROVED"
    )

    resp = api_client.create_wish_event(
        create_wish_event_payload(wish["id"], "2026-10-01", "2026-10-02"),
        WISH_COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_WISH_STATE)


def test_travel_clearance_decision_opens_scheduling_gate():
    """PRD section 3.7: "Either ruling increments the clearance's `version`
    and re-evaluates the travel gate immediately, in the same request: a wish
    sitting in `PLAN_APPROVED` advances to `READY_TO_SCHEDULE`"
    PRD section 3.8: "Success creates a wish event in `SCHEDULED` status and
    moves the wish `READY_TO_SCHEDULE` → `SCHEDULED` with a version increment."

    Design: Difficulty/cross_entity_state_dependency/travel_event_gated_by_clearance_state
    """
    ctx = setup_approved_wish(wish_type="TRAVEL",
                              captured_true_wish="fly to the ocean",
                              cash_cost_cents=100000)
    wish = ctx["wish"]
    assert wish["status"] == "PLAN_APPROVED"

    blocked = api_client.create_wish_event(
        create_wish_event_payload(wish["id"], "2026-10-01", "2026-10-02"),
        WISH_COORDINATOR)
    validate_error(blocked, ApiErrorId.ERR_INVALID_WISH_STATE)

    clear_travel_wish(wish["id"], decision="CLEARED",
                      valid_until="2026-12-31")
    ready = get_wish(wish["id"])
    assert ready["status"] == "READY_TO_SCHEDULE", (
        "the CLEARED ruling auto-advances the wish in the same request"
    )

    event = schedule_event(wish["id"], "2026-10-01", "2026-10-02")
    assert event["status"] == "SCHEDULED"
    assert get_wish(wish["id"])["status"] == "SCHEDULED"
