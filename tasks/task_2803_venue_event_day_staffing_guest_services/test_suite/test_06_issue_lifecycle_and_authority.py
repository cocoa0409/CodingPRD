"""The resolve-reopen cycle of a guest issue, and state outranking the recovery budget."""

from test_helpers import (
    ERR_ISSUE_STATE_INVALID,
    ERR_REFUND_BUDGET_EXHAUSTED,
    ERR_REOPEN_LIMIT_REACHED,
    SUPERVISOR_HEADERS,
    assert_cents,
    assert_fields,
    assert_instant,
    assert_ledger,
    assign_issue,
    certified_member,
    created,
    err,
    event_in_progress_with_slot,
    file_refund,
    make_supervisor_headers,
    ok,
    read_event,
    read_issue,
    resolve_issue,
    set_clock,
)
from test_helpers.factories import (
    guest_issue_payload,
    issue_assign_payload,
    refund_decision_payload,
    ticket_taker_payload,
)

REPORTER = make_supervisor_headers("u-sup-report-6")
FILER = make_supervisor_headers("u-sup-file-6")
DECIDER = make_supervisor_headers("u-sup-decide-6")


def _cleared(issue, *fields):
    """A cleared field reads as absent or null, never as a stale value."""
    for field in fields:
        assert issue.get(field) is None, (
            f"{field} should have been cleared, got {issue.get(field)!r}"
        )


def _running_event(client, *, name, zone_code, clock, budget_cents=None):
    """An IN_PROGRESS event with one uncredentialled block, ready to carry issues."""
    set_clock(client, clock)
    extra = {} if budget_cents is None else {"refund_budget_total_cents": budget_cents}
    return event_in_progress_with_slot(
        client,
        position_type_payload=ticket_taker_payload(required_certifications=[]),
        slot_overrides={
            "zone_code": zone_code,
            "shift_start": "2026-09-12T18:00:00Z",
            "shift_end": "2026-09-12T22:00:00Z",
            "required_headcount_override": 1,
        },
        name=name,
        doors_open_at="2026-09-12T17:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=20000,
        **extra,
    )


def _lost_property_report_in_progress(client):
    """A LOW-severity lost-property report handed to a credentialled responder."""
    context = _running_event(
        client,
        name="Reopen Cycle Fixture",
        zone_code="Z710",
        clock="2026-09-12T19:00:00Z",
    )
    responder = certified_member(
        client,
        "CODE_OF_CONDUCT",
        full_name="Tess Amara",
        employment_type="CONTRACTED",
        seniority_date="2023-04-01T00:00:00Z",
        hourly_rate_cents=2400,
    )
    issue = created(
        client.create_guest_issue(
            guest_issue_payload(
                context["event"]["id"],
                channel="KIOSK",
                category="LOST_FOUND",
                severity="LOW",
                description="Camera bag left in section 214 after the second period",
            ),
            REPORTER,
        )
    )
    issue = ok(
        client.assign_guest_issue(issue["id"], issue_assign_payload(responder["id"]), REPORTER)
    )
    context["responder"] = responder
    context["issue"] = issue
    return context


def _one_resolve_and_reopen_lap(client, context):
    """One full lap: resolve the report, then reopen it and hand it out again."""
    issue_id = context["issue"]["id"]
    resolve_issue(client, issue_id, "ITEM_RETURNED", DECIDER)
    reopened = ok(client.reopen_guest_issue(issue_id, SUPERVISOR_HEADERS))
    assign_issue(client, issue_id, context["responder"]["id"])
    return reopened


def test_the_report_resolves_and_reopens_back_into_the_live_part_of_the_machine(client):
    """RESOLVED is not terminal: the reopen arc walks the issue backwards and clears the stamps.

    "Reopening increments `reopen_count` by 1 and clears `resolved_at`,
    `resolution_type` and `resolved_by_user_id`, but deliberately leaves
    `refund_approved_cents` and every figure in the event ledger untouched — money
    already authorized is not clawed back by a reopen."

    Design: Difficulty/non_linear_state_machine/guest_issue_resolve_reopen_cycle
    """
    context = _lost_property_report_in_progress(client)
    issue_id = context["issue"]["id"]

    assert_fields(
        context["issue"], status="IN_PROGRESS", severity="LOW", sla_minutes=120, reopen_count=0
    )
    assert_instant(
        context["issue"]["sla_deadline"], "2026-09-12T21:00:00.000Z", "sla_deadline"
    )

    resolved = resolve_issue(client, issue_id, "ITEM_RETURNED", DECIDER)
    assert_fields(
        resolved,
        status="RESOLVED",
        resolution_type="ITEM_RETURNED",
        resolved_by_user_id="u-sup-decide-6",
        sla_breached=False,
    )
    assert_instant(resolved["resolved_at"], "2026-09-12T19:00:00.000Z", "resolved_at")

    reopened = ok(client.reopen_guest_issue(issue_id, SUPERVISOR_HEADERS))
    assert_fields(reopened, status="REOPENED", reopen_count=1)
    _cleared(reopened, "resolved_at", "resolution_type", "resolved_by_user_id")
    assert_instant(reopened["sla_deadline"], "2026-09-12T21:00:00.000Z", "sla_deadline")


def test_a_reopened_report_re_enters_in_progress_and_resolves_a_second_time(client):
    """The same two arcs fire again on the second lap, keeping the original response clock.

    "It moves the issue `OPEN → IN_PROGRESS`, or `REOPENED → IN_PROGRESS` for an issue
    that had been reopened."

    Design: Difficulty/non_linear_state_machine/guest_issue_resolve_reopen_cycle
    """
    context = _lost_property_report_in_progress(client)
    issue_id = context["issue"]["id"]

    _one_resolve_and_reopen_lap(client, context)

    handed_out = read_issue(client, issue_id)
    assert_fields(handed_out, status="IN_PROGRESS", reopen_count=1, sla_minutes=120)
    assert_instant(handed_out["sla_deadline"], "2026-09-12T21:00:00.000Z", "sla_deadline")

    resolved = resolve_issue(client, issue_id, "ITEM_RETURNED", DECIDER)
    assert_fields(resolved, status="RESOLVED", resolution_type="ITEM_RETURNED", reopen_count=1)

    second_reopen = ok(client.reopen_guest_issue(issue_id, SUPERVISOR_HEADERS))
    assert_fields(second_reopen, status="REOPENED", reopen_count=2)
    _cleared(second_reopen, "resolved_at", "resolution_type", "resolved_by_user_id")


def test_the_third_reopen_is_refused_and_leaves_the_resolved_report_untouched(client):
    """Two laps are the ceiling, and the refusal mutates nothing at all.

    "An issue may be reopened at most twice: once `reopen_count` has reached 2, a
    further attempt is refused with `ERR_REOPEN_LIMIT_REACHED`, and because the window
    rule is evaluated first, an issue that is both past its window and at its ceiling
    reports `ERR_REOPEN_WINDOW_CLOSED`."

    Design: Difficulty/non_linear_state_machine/guest_issue_resolve_reopen_cycle
    """
    context = _lost_property_report_in_progress(client)
    issue_id = context["issue"]["id"]

    _one_resolve_and_reopen_lap(client, context)
    _one_resolve_and_reopen_lap(client, context)
    resolved = resolve_issue(client, issue_id, "ITEM_RETURNED", DECIDER)
    assert_fields(resolved, status="RESOLVED", reopen_count=2)

    err(client.reopen_guest_issue(issue_id, SUPERVISOR_HEADERS), ERR_REOPEN_LIMIT_REACHED)

    after = read_issue(client, issue_id)
    assert_fields(
        after,
        status="RESOLVED",
        reopen_count=2,
        resolution_type="ITEM_RETURNED",
        sla_breached=False,
    )
    assert_instant(after["resolved_at"], "2026-09-12T19:00:00.000Z", "resolved_at")
    assert_instant(after["sla_deadline"], "2026-09-12T21:00:00.000Z", "sla_deadline")


def _issue_with_an_ask(client, context, *, cents, severity, description, category="OTHER"):
    """One issue filed, handed to the standing responder, and carrying a refund ask."""
    issue = created(
        client.create_guest_issue(
            guest_issue_payload(
                context["event"]["id"],
                channel="IN_PERSON",
                category=category,
                severity=severity,
                description=description,
            ),
            REPORTER,
        )
    )
    ok(
        client.assign_guest_issue(
            issue["id"], issue_assign_payload(context["responder"]["id"]), REPORTER
        )
    )
    return file_refund(client, issue["id"], cents, FILER)


def _exhausted_budget_with_a_frozen_issue(client):
    """A 5000-cent budget spent in full, one closed issue and one live issue behind it."""
    context = _running_event(
        client,
        name="State Beats Fiscal Fixture",
        zone_code="Z810",
        clock="2026-09-12T18:00:00Z",
        budget_cents=5000,
    )
    context["responder"] = certified_member(
        client,
        "CODE_OF_CONDUCT",
        full_name="Uma Bright",
        employment_type="CONTRACTED",
        seniority_date="2023-07-01T00:00:00Z",
        hourly_rate_cents=2400,
    )

    spender = _issue_with_an_ask(
        client,
        context,
        cents=5000,
        severity="MEDIUM",
        description="Concession voucher never honoured at gate four",
    )
    approved = ok(client.file_refund_decision(spender["id"], refund_decision_payload("APPROVE"), DECIDER))
    assert_fields(approved, refund_status="APPROVED", status="IN_PROGRESS")
    assert_cents(approved["refund_approved_cents"], 5000, "refund_approved_cents")
    resolve_issue(client, spender["id"], "REFUND", DECIDER)

    frozen = _issue_with_an_ask(
        client,
        context,
        cents=1000,
        severity="LOW",
        description="Programme booklet missing from the seat pocket",
    )
    resolve_issue(client, frozen["id"], "NO_ACTION", DECIDER)

    live = _issue_with_an_ask(
        client,
        context,
        cents=1000,
        severity="LOW",
        description="Queue at the merchandise stand mismanaged",
    )

    set_clock(client, "2026-09-13T18:01:00Z")
    frozen = ok(client.close_guest_issue(frozen["id"], SUPERVISOR_HEADERS))
    assert_fields(frozen, status="CLOSED")

    context["spender"] = spender
    context["frozen"] = frozen
    context["live"] = live
    return context


def test_a_closed_issue_reports_its_own_state_even_with_the_budget_spent_out(client):
    """Rung 10 answers before rung 23, so frozen beats broke.

    "A closed issue is frozen: reopening it, resolving it again and deciding a refund
    on it all return `ERR_ISSUE_STATE_INVALID` from then on."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_closed_issue_refund
    """
    context = _exhausted_budget_with_a_frozen_issue(client)
    event_id = context["event"]["id"]

    assert_ledger(read_event(client, event_id), approved=5000, remaining=0, total=5000)

    err(
        client.file_refund_decision(
            context["frozen"]["id"], refund_decision_payload("APPROVE"), DECIDER
        ),
        ERR_ISSUE_STATE_INVALID,
    )

    after = read_issue(client, context["frozen"]["id"])
    assert_fields(after, status="CLOSED", refund_status="PENDING")
    assert_cents(after["refund_approved_cents"], 0, "refund_approved_cents")
    assert_ledger(read_event(client, event_id), approved=5000, remaining=0, total=5000)


def test_the_fiscal_rung_answers_once_the_issue_state_rung_is_satisfied(client):
    """An identical ask on a live issue is refused for the budget instead.

    "Before an approval is attempted at all, the event must still have room: the
    event's `refund_budget_remaining_cents` plus this issue's already-recorded
    `refund_approved_cents` must be greater than zero, or the approval is refused with
    `ERR_REFUND_BUDGET_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_closed_issue_refund
    """
    context = _exhausted_budget_with_a_frozen_issue(client)
    event_id = context["event"]["id"]

    err(
        client.file_refund_decision(
            context["live"]["id"], refund_decision_payload("APPROVE"), DECIDER
        ),
        ERR_REFUND_BUDGET_EXHAUSTED,
    )

    after = read_issue(client, context["live"]["id"])
    assert_fields(after, status="IN_PROGRESS", refund_status="PENDING")
    assert_cents(after["refund_approved_cents"], 0, "refund_approved_cents")
    assert_ledger(read_event(client, event_id), approved=5000, remaining=0, total=5000)
    assert_fields(read_issue(client, context["spender"]["id"]), refund_status="APPROVED")
