"""Refund authority by acting role, the composed cap, and the budget ledger identity."""

from test_helpers import (
    ERR_REFUND_STATE_INVALID,
    assert_cents,
    assert_fields,
    assert_instant,
    assert_ledger,
    certified_member,
    created,
    decide_refund,
    err,
    event_in_progress_with_slot,
    file_refund,
    make_director_headers,
    make_supervisor_headers,
    ok,
    read_event,
    read_issue,
    set_clock,
)
from test_helpers.factories import (
    guest_issue_payload,
    guest_services_rep_payload,
    issue_assign_payload,
    issue_resolve_payload,
    refund_decision_payload,
)

REPORTER = make_supervisor_headers("u-sup-report")
FILER = make_supervisor_headers("u-sup-file")
SUPERVISOR_DECIDER = make_supervisor_headers("u-sup-decide")
DIRECTOR_DECIDER = make_director_headers("u-dir-decide")


def _responder_on_a_running_event(client, *, zone_code, name, budget_cents, clock):
    """An IN_PROGRESS event with a certified guest-services responder on one block."""
    set_clock(client, clock)
    context = event_in_progress_with_slot(
        client,
        position_type_payload=guest_services_rep_payload(
            base_hourly_rate_cents=2400,
            attendance_ratio_per_1000=0.35,
            min_headcount=2,
            required_certifications=["CODE_OF_CONDUCT"],
        ),
        slot_overrides={
            "zone_code": zone_code,
            "shift_start": "2026-09-12T17:00:00Z",
            "shift_end": "2026-09-12T23:00:00Z",
            "required_headcount_override": 1,
        },
        name=name,
        doors_open_at="2026-09-12T17:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=20000,
        refund_budget_total_cents=budget_cents,
    )
    context["responder"] = certified_member(
        client,
        "CODE_OF_CONDUCT",
        full_name="Rex Hall",
        employment_type="CONTRACTED",
        seniority_date="2023-05-01T00:00:00Z",
        hourly_rate_cents=2400,
    )
    return context


def _issue_with_a_filed_ask(client, context, *, cents, **issue_overrides):
    """One assigned issue carrying a refund ask filed by a third operator."""
    issue = created(
        client.create_guest_issue(
            guest_issue_payload(context["event"]["id"], **issue_overrides), REPORTER
        )
    )
    ok(client.assign_guest_issue(issue["id"], issue_assign_payload(context["responder"]["id"]), REPORTER))
    return file_refund(client, issue["id"], cents, FILER)


def _authority_fixture(client):
    """A 100000-cent budget and one CRITICAL issue asking for 12000."""
    context = _responder_on_a_running_event(
        client,
        zone_code="Z102",
        name="Refund Authority Fixture",
        budget_cents=100000,
        clock="2026-09-12T18:00:00Z",
    )
    context["issue"] = _issue_with_a_filed_ask(
        client,
        context,
        cents=12000,
        channel="TEXT_LINE",
        category="OTHER",
        severity="CRITICAL",
        description="Ejected from seat without cause",
    )
    return context


def test_a_supervisor_decision_is_held_to_the_uplifted_role_cap(client):
    """5000 plus half of 5000 is 7500, and the shortfall parks the issue.

    "So a supervisor deciding a `CRITICAL` issue works to an effective cap of 7500
    cents, being 5000 plus half of 5000, but the same supervisor on a
    `SEAT_RELOCATION` issue is held to 2500 whatever the severity."

    Design: Difficulty/dual_variant_calc/refund_authority_supervisor_vs_director
    """
    context = _authority_fixture(client)

    decided = decide_refund(client, context["issue"]["id"], "APPROVE", SUPERVISOR_DECIDER)

    assert_fields(
        decided,
        refund_status="PARTIALLY_APPROVED",
        status="AWAITING_AUTHORIZATION",
        refund_decided_by_user_id="u-sup-decide",
    )
    assert_cents(decided["refund_approved_cents"], 7500, "refund_approved_cents")
    assert_ledger(
        read_event(client, context["event"]["id"]),
        approved=7500,
        remaining=92500,
        total=100000,
    )


def test_a_director_decision_replaces_the_amount_and_moves_the_ledger_by_the_delta(client):
    """The same unchanged 12000 ask is fully covered once a director decides it.

    "`refund_approved_cents` is then **replaced** by the director-capped amount
    rather than added to it, and the event ledger is adjusted by the delta only, so
    the same money is never counted twice."

    Design: Difficulty/dual_variant_calc/refund_authority_supervisor_vs_director
    """
    context = _authority_fixture(client)
    issue_id = context["issue"]["id"]

    decide_refund(client, issue_id, "APPROVE", SUPERVISOR_DECIDER)
    authorized = decide_refund(client, issue_id, "APPROVE", DIRECTOR_DECIDER)

    assert_fields(
        authorized,
        refund_status="APPROVED",
        status="RESOLVED",
        resolution_type="REFUND",
        refund_decided_by_user_id="u-dir-decide",
    )
    assert_cents(authorized["refund_approved_cents"], 12000, "refund_approved_cents")
    assert_instant(authorized["resolved_at"], "2026-09-12T18:00:00.000Z", "resolved_at")

    event = read_event(client, context["event"]["id"])
    assert_ledger(event, approved=12000, remaining=88000, total=100000)
    assert event["refund_budget_remaining_cents"] != 80500, (
        "the supervisor's 7500 must be replaced, never added to the director's 12000"
    )


def test_the_budget_identity_holds_after_every_refund_decision(client):
    """Remaining plus approved equals the ceiling at creation, after one decision and after two.

    "The invariant `refund_budget_remaining_cents` plus `refund_approved_total_cents`
    equals `refund_budget_total_cents` holds after every refund decision and after
    every event update."

    Design: Difficulty/dual_variant_calc/refund_authority_supervisor_vs_director
    """
    context = _authority_fixture(client)
    issue_id = context["issue"]["id"]
    event_id = context["event"]["id"]

    assert_ledger(read_event(client, event_id), approved=0, remaining=100000, total=100000)

    decide_refund(client, issue_id, "APPROVE", SUPERVISOR_DECIDER)
    assert_ledger(read_event(client, event_id), approved=7500, remaining=92500, total=100000)

    decide_refund(client, issue_id, "APPROVE", DIRECTOR_DECIDER)
    assert_ledger(read_event(client, event_id), approved=12000, remaining=88000, total=100000)


def _cap_composition_fixture(client):
    """A 9000-cent budget and two CRITICAL issues each asking for 12000."""
    context = _responder_on_a_running_event(
        client,
        zone_code="Z110",
        name="Cap Composition Fixture",
        budget_cents=9000,
        clock="2026-09-12T19:00:00Z",
    )
    context["issue_x"] = _issue_with_a_filed_ask(
        client,
        context,
        cents=12000,
        channel="TEXT_LINE",
        category="OTHER",
        severity="CRITICAL",
        description="Struck by falling debris in concourse",
    )
    context["issue_y"] = _issue_with_a_filed_ask(
        client,
        context,
        cents=12000,
        channel="KIOSK",
        category="SEAT_RELOCATION",
        severity="CRITICAL",
        description="Obstructed view seat, guest moved twice",
        seat_reference="S-214-12",
    )
    return context


def test_the_role_cap_binds_first_and_escalates_the_issue_for_authorization(client):
    """With 9000 cents still available it is the supervisor's own cap that holds 12000 down.

    "When the acting role is `GuestServicesSupervisor` and the effective cap is
    strictly smaller than the lesser of the requested amount and the available budget,
    the issue moves `IN_PROGRESS → AWAITING_AUTHORIZATION`: `refund_approved_cents`
    holds the capped amount, `refund_budget_remaining_cents` is reduced by exactly that
    amount, and resolution is blocked — an attempt to resolve from
    `AWAITING_AUTHORIZATION` is refused with `ERR_ISSUE_STATE_INVALID` until a director
    has acted."

    Design: Difficulty/combinatorial_formula/refund_effective_cap_nonlinear_composition
    """
    context = _cap_composition_fixture(client)

    decided = decide_refund(client, context["issue_x"]["id"], "APPROVE", SUPERVISOR_DECIDER)

    assert_fields(
        decided, refund_status="PARTIALLY_APPROVED", status="AWAITING_AUTHORIZATION"
    )
    assert_cents(decided["refund_approved_cents"], 7500, "refund_approved_cents")
    assert_ledger(
        read_event(client, context["event"]["id"]),
        approved=7500,
        remaining=1500,
        total=9000,
    )


def test_the_relocation_ceiling_then_the_thin_budget_bind_without_escalating(client):
    """2500 beats the uplifted cap, 1500 beats 2500, and a budget-bound decision stays put.

    "Third, and only after the uplift has been applied, a hard ceiling of 2500 cents
    on any issue whose `category` is `SEAT_RELOCATION`: the effective cap becomes the
    smaller of itself and 2500."

    Design: Difficulty/combinatorial_formula/refund_effective_cap_nonlinear_composition
    """
    context = _cap_composition_fixture(client)
    decide_refund(client, context["issue_x"]["id"], "APPROVE", SUPERVISOR_DECIDER)

    decided = decide_refund(client, context["issue_y"]["id"], "APPROVE", SUPERVISOR_DECIDER)

    assert_fields(
        decided,
        refund_status="PARTIALLY_APPROVED",
        status="IN_PROGRESS",
        severity="CRITICAL",
        sla_minutes=5,
    )
    assert_cents(decided["refund_approved_cents"], 1500, "refund_approved_cents")
    assert decided["refund_approved_cents"] != 2500, (
        "the remaining budget of 1500 binds tighter than the relocation ceiling of 2500"
    )
    assert_ledger(
        read_event(client, context["event"]["id"]), approved=9000, remaining=0, total=9000
    )


def _approved_medium_refund(client):
    """A fully covered 3000-cent authorization sitting on an IN_PROGRESS issue."""
    context = _responder_on_a_running_event(
        client,
        zone_code="B200",
        name="Ledger Invariant Fixture",
        budget_cents=100000,
        clock="2026-09-12T19:00:00Z",
    )
    context["issue"] = _issue_with_a_filed_ask(
        client,
        context,
        cents=3000,
        channel="KIOSK",
        category="OTHER",
        severity="MEDIUM",
        description="Merchandise voucher dispute",
    )
    context["approved"] = decide_refund(
        client, context["issue"]["id"], "APPROVE", SUPERVISOR_DECIDER
    )
    return context


def test_a_reversal_restores_the_ledger_to_its_exact_pre_authorization_value(client):
    """The rescan puts back 3000 cents, neither 2999 nor 6000.

    "A reversal — available only to a `GuestExperienceDirector` — moves
    `refund_status` to `VOIDED` and resets `refund_approved_cents` to 0, and because
    the ledger is always re-derived by rescanning the event's issues,
    `refund_approved_total_cents` and `refund_budget_remaining_cents` return to
    exactly their pre-authorization values."

    Design: Difficulty/compensating_invariant/refund_void_restores_budget_ledger_identity
    """
    context = _approved_medium_refund(client)
    event_id = context["event"]["id"]

    assert_fields(
        context["approved"], refund_status="APPROVED", status="IN_PROGRESS"
    )
    assert_cents(context["approved"]["refund_approved_cents"], 3000, "approved cents")
    assert_ledger(read_event(client, event_id), approved=3000, remaining=97000, total=100000)

    voided = decide_refund(client, context["issue"]["id"], "VOID", DIRECTOR_DECIDER)

    assert_fields(voided, refund_status="VOIDED")
    assert_cents(voided["refund_approved_cents"], 0, "refund_approved_cents")
    assert_ledger(read_event(client, event_id), approved=0, remaining=100000, total=100000)


def test_a_second_reversal_is_refused_so_the_budget_cannot_be_credited_twice(client):
    """The ledger is a full rescan, and the sub-state gate stops a replay outright.

    "Both derived totals are always re-derived from scratch by rescanning the event's
    issues — never adjusted incrementally — which is what makes an authorization
    followed by a reversal restore the ledger to its exact pre-authorization value
    and prevents drift accumulating across repeated approve-and-reverse cycles."

    Design: Difficulty/compensating_invariant/refund_void_restores_budget_ledger_identity
    """
    context = _approved_medium_refund(client)
    issue_id = context["issue"]["id"]
    event_id = context["event"]["id"]

    decide_refund(client, issue_id, "VOID", DIRECTOR_DECIDER)

    err(
        client.file_refund_decision(
            issue_id, refund_decision_payload("VOID"), DIRECTOR_DECIDER
        ),
        ERR_REFUND_STATE_INVALID,
    )

    assert_ledger(read_event(client, event_id), approved=0, remaining=100000, total=100000)
    assert_fields(read_issue(client, issue_id), refund_status="VOIDED", status="IN_PROGRESS")


def test_the_reversal_undoes_the_authorization_but_never_the_ask(client):
    """The filed amount and its filer survive, so a refund resolution is now impossible.

    "A `REFUND` resolution requires the issue's `refund_status` to already stand at
    `APPROVED` or `PARTIALLY_APPROVED`, failing which it is refused with
    `ERR_REFUND_STATE_INVALID`."

    Design: Difficulty/compensating_invariant/refund_void_restores_budget_ledger_identity
    """
    context = _approved_medium_refund(client)
    issue_id = context["issue"]["id"]

    decide_refund(client, issue_id, "VOID", DIRECTOR_DECIDER)

    reversed_issue = read_issue(client, issue_id)
    assert_fields(reversed_issue, refund_requested_by_user_id="u-sup-file")
    assert_cents(
        reversed_issue["refund_requested_cents"], 3000, "refund_requested_cents"
    )

    err(
        client.resolve_guest_issue(
            issue_id, issue_resolve_payload("REFUND"), SUPERVISOR_DECIDER
        ),
        ERR_REFUND_STATE_INVALID,
    )
