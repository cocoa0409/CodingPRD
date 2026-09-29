"""Booking, guarding and unwinding witnessing slots against the day ledger.

Every test in this module translates exactly one design instance; the
``Design:`` line closing each docstring names it.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.assertions import (
    assert_capacity_ledger,
    assert_effort_breakdown,
    assert_total_count,
)
from test_helpers.api_errors import (
    ERR_ASSESSOR_CAPACITY_EXCEEDED,
    ERR_ASSESSOR_SCHEDULE_CONFLICT,
    ERR_PLAN_NOT_APPROVED,
    ERR_REMOTE_WITNESS_NOT_PERMITTED,
    ERR_SITE_BUFFER_CONFLICT,
    ERR_WITNESS_COVERAGE_INSUFFICIENT,
)
from test_helpers.constants import (
    ACTIVITY_CALIBRATION,
    ACTIVITY_TESTING,
    APP_IN_ASSESSMENT,
    APP_PLANNED,
    DELIVERY_ON_SITE,
    DELIVERY_REMOTE,
    PLAN_APPROVED,
    PLAN_CANCELLED,
    PLAN_MODE_HYBRID,
    PLAN_MODE_ON_SITE,
    QUAL_GRANTED,
    ROLE_TYPE_LEAD_ASSESSOR,
    SESSION_ABORTED,
    SESSION_COMPLETED,
    SESSION_SCHEDULED,
    OUTCOME_SATISFACTORY,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import ASSESSMENT_MANAGER, SCHEME_MANAGER

NORTHLIGHT = {
    "legal_name": "Northlight Testing AB",
    "country_code": "SE",
    "contact_email": "qa@northlight.test",
}
THREE_SCOPE_LINES = [
    "mass calibration 1 mg - 20 kg",
    "temperature calibration -40 C - 250 C",
    "pressure calibration 0 - 700 bar",
]
SITE = "NORTHLIGHT-LAB-1"


def test_assessor_booking_uses_half_open_intervals_so_touching_slots_are_allowed(client):
    """A slot beginning exactly when another ends is accepted; one minute of
    genuine overlap is not.

    PRD section 3.6: "Intervals that merely touch are fine — a slot starting
    at exactly the instant another slot ends is accepted, because half-open
    intervals that abut do not overlap."

    Design: Difficulty/resource_temporal_overlap/assessor_booking_uses_half_open_intervals_so_touching_slots_are_allowed
    """
    ctx = fx.new_context(client, "ISO17025-CAL")
    fx.with_lead(ctx)
    fx.with_organization(ctx)
    fx.with_initial_cycle(ctx)
    fx.with_confirmed_team(ctx, ("lead",))
    fx.with_approved_plan(ctx, 3, 2, PLAN_MODE_HYBRID)
    slot_a = fx.book_session(
        client,
        ctx["plan_id"],
        ctx["lead_id"],
        "2026-09-07T08:00:00Z",
        "2026-09-07T16:00:00Z",
        ACTIVITY_CALIBRATION,
        "ACME-LAB-1",
        DELIVERY_ON_SITE,
    )
    slot_b = fx.book_session(
        client,
        ctx["plan_id"],
        ctx["lead_id"],
        "2026-09-07T16:00:00Z",
        "2026-09-08T00:00:00Z",
        ACTIVITY_TESTING,
        "ACME-LAB-1",
        DELIVERY_ON_SITE,
    )

    response = client.schedule_witness_session(
        ctx["plan_id"],
        f.witness_session_payload(
            ctx["lead_id"],
            "2026-09-07T15:59:00Z",
            "2026-09-07T23:59:00Z",
            ACTIVITY_TESTING,
            "ACME-LAB-1",
            DELIVERY_ON_SITE,
        ),
        ASSESSMENT_MANAGER,
    )

    validate_error(response, ERR_ASSESSOR_SCHEDULE_CONFLICT, 409)
    assert slot_a["day_count"] == 1
    assert slot_b["day_count"] == 1, (
        "The abutting slot was accepted at booking time, so it carries its own cost"
    )
    assert_total_count(
        client.list_witness_sessions(ASSESSMENT_MANAGER, {"plan_id": ctx["plan_id"]}), 2
    )
    owner = fx.read_assessor(client, ctx["lead_id"])
    assert_capacity_ledger(owner, committed=2, available=18)
    application = fx.read_application(client, ctx["app_id"])
    assert application["status"] == APP_PLANNED
    assert application["completed_witness_session_count"] == 0


def test_shared_site_buffer_rejects_a_fourteen_day_gap_across_organizations(client):
    """Fourteen whole days between two applicants at one venue is too few;
    fifteen is enough, and the same applicant is exempt outright.

    PRD section 3.6: "That gap must be strictly greater than the fourteen-day
    site buffer; a gap of exactly 14 days is rejected, and so is anything
    smaller, with `ERR_SITE_BUFFER_CONFLICT`. Sessions belonging to the *same*
    applicant organization are exempt from the buffer entirely — an applicant
    may be witnessed at its own site as often as the plan requires."

    Design: Difficulty/resource_temporal_overlap/shared_site_buffer_rejects_a_fourteen_day_gap_across_organizations
    """
    shared_site = "SHARED-SITE-9"
    ctx = fx.new_context(client, "ISO17025-CAL")
    fx.with_lead(ctx)
    fx.with_assessor(
        ctx,
        "lead2",
        full_name="Miro Salas",
        email="miro.salas@ab.test",
        role_type=ROLE_TYPE_LEAD_ASSESSOR,
    )
    fx.with_organization(ctx)
    fx.with_initial_cycle(ctx)
    fx.with_confirmed_team(ctx, ("lead",))
    fx.with_approved_plan(ctx, 3, 2, PLAN_MODE_HYBRID)
    session_one = fx.book_session(
        client,
        ctx["plan_id"],
        ctx["lead_id"],
        "2026-09-11T08:00:00Z",
        "2026-09-11T16:00:00Z",
        ACTIVITY_CALIBRATION,
        shared_site,
        DELIVERY_ON_SITE,
    )
    # The same-applicant exemption is probed here, while the only other
    # session at the venue belongs to this very organization: one day before
    # ``session_one`` is far inside the fourteen-day buffer, so an acceptance
    # can only be the exemption at work.
    same_applicant = validate_success(
        client.schedule_witness_session(
            ctx["plan_id"],
            f.witness_session_payload(
                ctx["lead_id"],
                "2026-09-10T08:00:00Z",
                "2026-09-10T16:00:00Z",
                ACTIVITY_CALIBRATION,
                shared_site,
                DELIVERY_ON_SITE,
            ),
            ASSESSMENT_MANAGER,
        ),
        201,
    )
    assert same_applicant["site_ref"] == shared_site
    fx.with_organization(
        ctx,
        key="org2",
        legal_name="Borealis Test House AB",
        country_code="SE",
        contact_email="qa@borealis.test",
    )
    fx.with_initial_cycle(
        ctx,
        key="app2",
        organization_key="org2",
        requested_scope_lines=["Torque 0-100Nm", "Volume 0-10L", "Length 0-1m"],
    )
    fx.with_confirmed_team(ctx, ("lead2",), application_key="app2")
    fx.with_approved_plan(
        ctx,
        3,
        2,
        PLAN_MODE_HYBRID,
        planned_start="2026-09-20",
        planned_end="2026-10-10",
        application_key="app2",
        key="plan2",
    )

    response = client.schedule_witness_session(
        ctx["plan2_id"],
        f.witness_session_payload(
            ctx["lead2_id"],
            "2026-09-25T08:00:00Z",
            "2026-09-25T16:00:00Z",
            ACTIVITY_CALIBRATION,
            shared_site,
            DELIVERY_ON_SITE,
        ),
        ASSESSMENT_MANAGER,
    )

    validate_error(response, ERR_SITE_BUFFER_CONFLICT, 409)
    assert_total_count(
        client.list_witness_sessions(ASSESSMENT_MANAGER, {"plan_id": ctx["plan2_id"]}), 0
    )
    assert_capacity_ledger(
        fx.read_assessor(client, ctx["lead2_id"]), committed=0, available=20
    )
    accepted = validate_success(
        client.schedule_witness_session(
            ctx["plan2_id"],
            f.witness_session_payload(
                ctx["lead2_id"],
                "2026-09-26T08:00:00Z",
                "2026-09-26T16:00:00Z",
                ACTIVITY_CALIBRATION,
                shared_site,
                DELIVERY_ON_SITE,
            ),
            ASSESSMENT_MANAGER,
        ),
        201,
    )
    assert accepted["status"] == SESSION_SCHEDULED, "A fifteen-day gap clears the buffer"
    stored = validate_success(
        client.get_witness_session(session_one["id"], ASSESSMENT_MANAGER), 200
    )
    assert stored["status"] == SESSION_SCHEDULED
    assert stored["version"] == session_one["version"]


def test_witness_session_abort_restores_the_assessor_day_ledger_exactly(client):
    """The abort hands back exactly the four days the booking took, and the
    freed capacity is genuinely re-bookable.

    PRD section 3.6: "The `evidence_note` then records the abort reason, and
    the ledger is unwound: `committed_witness_days` is decremented by the
    session's `day_count`, `available_witness_days` is incremented by the same
    `day_count`, leaving `annual_witness_capacity_days` still equal to the sum
    of the two, and both the assessor's `version` and the session's `version`
    are bumped."

    Design: Difficulty/compensating_invariant/witness_session_abort_restores_the_assessor_day_ledger_exactly
    """
    abort_note = "Applicant postponed the calibration run; slot released."
    ctx = fx.new_context(client, "ISO17025-CAL")
    fx.with_lead(ctx)
    fx.with_organization(ctx)
    fx.with_initial_cycle(ctx)
    fx.with_confirmed_team(ctx, ("lead",))
    fx.with_approved_plan(ctx, 3, 2, PLAN_MODE_HYBRID)
    session = fx.book_session(
        client,
        ctx["plan_id"],
        ctx["lead_id"],
        "2026-09-07T08:00:00Z",
        "2026-09-08T16:00:00Z",
    )
    assert session["day_count"] == 4
    before = fx.read_assessor(client, ctx["lead_id"])
    assert_capacity_ledger(before, committed=4, available=16)

    response = client.record_session_outcome(
        session["id"],
        f.session_outcome_payload(SESSION_ABORTED, None, abort_note),
        ctx["lead_headers"],
    )

    aborted = validate_success(response, 200)
    assert aborted["status"] == SESSION_ABORTED
    assert aborted["outcome"] is None
    assert aborted["evidence_note"] == abort_note
    assert aborted["day_count"] == 4, "The abort does not rewrite the stored day_count"
    after = fx.read_assessor(client, ctx["lead_id"])
    assert_capacity_ledger(after, committed=0, available=20)
    assert (
        after["annual_witness_capacity_days"] == before["annual_witness_capacity_days"]
    )
    application = fx.read_application(client, ctx["app_id"])
    assert application["completed_witness_session_count"] == 0
    assert application["status"] == APP_PLANNED
    rebooked = validate_success(
        client.schedule_witness_session(
            ctx["plan_id"],
            f.witness_session_payload(
                ctx["lead_id"], "2026-09-07T08:00:00Z", "2026-09-08T16:00:00Z"
            ),
            ASSESSMENT_MANAGER,
        ),
        201,
    )
    assert rebooked["day_count"] == 4, "The released capacity really was available again"


def test_completing_a_witness_session_refreshes_the_qualification_recency_date(client):
    """The completion writes today's logical-clock date onto the qualification
    that made the assessor eligible.

    PRD section 3.6: "The `GRANTED` qualification joining the witnessing
    assessor to the cycle's programme has its `last_witness_on` refreshed to
    the current logical-clock date and its `version` bumped, which is how
    witnessing feeds back into the recency factor of §3.2."

    Design: Corner/state_machines/completing_a_witness_session_refreshes_the_qualification_recency_date
    """
    ctx = fx.new_context(client, "ISO17025-CAL")
    fx.with_lead(ctx)
    fx.with_organization(ctx, **NORTHLIGHT)
    fx.with_initial_cycle(ctx, requested_scope_lines=THREE_SCOPE_LINES)
    fx.with_confirmed_team(ctx, ("lead",))
    fx.with_approved_plan(ctx, 3, 2, PLAN_MODE_HYBRID)
    session = fx.book_session(
        client,
        ctx["plan_id"],
        ctx["lead_id"],
        "2026-09-07T08:00:00Z",
        "2026-09-08T16:00:00Z",
        ACTIVITY_CALIBRATION,
        SITE,
        DELIVERY_ON_SITE,
    )
    assert ctx["lead_qualification"]["last_witness_on"] == "2026-05-10"
    fx.set_clock(client, "2026-09-09T17:00:00Z")

    response = client.record_session_outcome(
        session["id"],
        f.session_outcome_payload(
            SESSION_COMPLETED,
            OUTCOME_SATISFACTORY,
            "witnessed two mass calibrations end to end",
        ),
        ctx["lead_headers"],
    )

    completed = validate_success(response, 200)
    assert completed["status"] == SESSION_COMPLETED
    assert completed["outcome"] == OUTCOME_SATISFACTORY
    assert completed["day_count"] == 4
    qualification = validate_success(
        client.get_qualification(ctx["lead_qualification_id"], SCHEME_MANAGER), 200
    )
    assert qualification["last_witness_on"] == "2026-09-09"
    assert qualification["status"] == QUAL_GRANTED
    application = fx.read_application(client, ctx["app_id"])
    assert application["status"] == APP_IN_ASSESSMENT
    assert application["completed_witness_session_count"] == 1
    assert_capacity_ledger(
        fx.read_assessor(client, ctx["lead_id"]), committed=4, available=16
    )


def test_witness_coverage_counts_only_completed_sessions(client):
    """One completed session and one long scheduled session do not discharge a
    two-session witnessing floor.

    PRD section 3.6: "the cycle's `completed_witness_session_count` must be at
    least the `witness_min_count` of the pinned scheme revision, **and** the
    sum of `day_count` over those witnessing sessions of the cycle's
    `APPROVED` plan whose status is `COMPLETED` must be at least that plan's
    `witness_days_planned`."

    Design: Corner/calculations/witness_coverage_counts_only_completed_sessions
    """
    ctx = fx.new_context(client, "ISO17025-CAL")
    fx.with_lead(ctx)
    fx.with_organization(ctx, **NORTHLIGHT)
    fx.with_initial_cycle(ctx, requested_scope_lines=THREE_SCOPE_LINES)
    fx.with_confirmed_team(ctx, ("lead",))
    fx.with_approved_plan(ctx, 3, 2, PLAN_MODE_HYBRID)
    short_session = fx.book_session(
        client,
        ctx["plan_id"],
        ctx["lead_id"],
        "2026-09-07T08:00:00Z",
        "2026-09-07T16:00:00Z",
        ACTIVITY_CALIBRATION,
        SITE,
        DELIVERY_ON_SITE,
    )
    long_session = fx.book_session(
        client,
        ctx["plan_id"],
        ctx["lead_id"],
        "2026-09-08T08:00:00Z",
        "2026-09-09T16:00:00Z",
        ACTIVITY_CALIBRATION,
        SITE,
        DELIVERY_ON_SITE,
    )
    fx.set_clock(client, "2026-09-07T17:00:00Z")
    fx.complete_session(
        client,
        short_session["id"],
        ctx["lead_headers"],
        OUTCOME_SATISFACTORY,
        "witnessed one mass calibration",
    )

    response = client.close_assessment(ctx["app_id"], ASSESSMENT_MANAGER)

    validate_error(response, ERR_WITNESS_COVERAGE_INSUFFICIENT, 422)
    stored_short = validate_success(
        client.get_witness_session(short_session["id"], ASSESSMENT_MANAGER), 200
    )
    assert stored_short["day_count"] == 1
    assert stored_short["status"] == SESSION_COMPLETED
    stored_long = validate_success(
        client.get_witness_session(long_session["id"], ASSESSMENT_MANAGER), 200
    )
    assert stored_long["day_count"] == 4
    assert stored_long["status"] == SESSION_SCHEDULED
    application = fx.read_application(client, ctx["app_id"])
    assert application["completed_witness_session_count"] == 1
    assert application["status"] == APP_IN_ASSESSMENT
    plan = validate_success(client.get_plan(ctx["plan_id"], ASSESSMENT_MANAGER), 200)
    assert plan["witness_days_planned"] == 2
    assert plan["status"] == PLAN_APPROVED
    assert_capacity_ledger(
        fx.read_assessor(client, ctx["lead_id"]), committed=5, available=15
    )


def test_remote_witness_session_rejected_when_the_pinned_scheme_forbids_remote(client):
    """A programme that bars remote assessment bars remote witnessing too.

    PRD section 3.6: "The `delivery_mode` is either `ON_SITE` or `REMOTE`, and
    a `REMOTE` slot is accepted only when the scheme revision pinned on the
    cycle has `remote_assessment_allowed` true, failing which the booking is
    rejected with `ERR_REMOTE_WITNESS_NOT_PERMITTED`."

    Design: Corner/validations/remote_witness_session_rejected_when_the_pinned_scheme_forbids_remote
    """
    ctx = fx.new_context(client, "ISO17025-CAL", remote_assessment_allowed=False)
    fx.with_lead(ctx)
    fx.with_organization(ctx, **NORTHLIGHT)
    fx.with_initial_cycle(ctx, requested_scope_lines=THREE_SCOPE_LINES)
    fx.with_confirmed_team(ctx, ("lead",))
    fx.with_approved_plan(
        ctx, 3, 0, PLAN_MODE_ON_SITE, planned_start="2026-09-07", planned_end="2026-09-14"
    )
    on_site_session = fx.book_session(
        client,
        ctx["plan_id"],
        ctx["lead_id"],
        "2026-09-07T08:00:00Z",
        "2026-09-07T16:00:00Z",
        ACTIVITY_CALIBRATION,
        SITE,
        DELIVERY_ON_SITE,
    )

    response = client.schedule_witness_session(
        ctx["plan_id"],
        f.witness_session_payload(
            ctx["lead_id"],
            "2026-09-10T08:00:00Z",
            "2026-09-10T16:00:00Z",
            ACTIVITY_CALIBRATION,
            SITE,
            DELIVERY_REMOTE,
        ),
        ASSESSMENT_MANAGER,
    )

    validate_error(response, ERR_REMOTE_WITNESS_NOT_PERMITTED, 422)
    stored = validate_success(
        client.get_witness_session(on_site_session["id"], ASSESSMENT_MANAGER), 200
    )
    assert stored["status"] == SESSION_SCHEDULED
    assert stored["day_count"] == 1
    assert_capacity_ledger(
        fx.read_assessor(client, ctx["lead_id"]), committed=1, available=19
    )
    assert_total_count(
        client.list_witness_sessions(ASSESSMENT_MANAGER, {"plan_id": ctx["plan_id"]}), 1
    )
    plan = validate_success(client.get_plan(ctx["plan_id"], ASSESSMENT_MANAGER), 200)
    assert_effort_breakdown(
        plan, witness_days_planned=2, core_days=5, travel_days=0, total_effort_days=5
    )


def test_scheduling_a_session_under_a_superseded_draft_plan_is_rejected(client):
    """The cancelled predecessor cannot take bookings even though its
    successor is approved.

    PRD section 3.6: "Witnessing slots are booked against an `APPROVED` plan —
    a plan in any other status rejects the booking with
    `ERR_PLAN_NOT_APPROVED`"

    Design: Corner/endpoints/scheduling_a_session_under_a_superseded_draft_plan_rejected
    """
    ctx = fx.new_context(client, "ISO17025-CAL")
    fx.with_lead(ctx)
    fx.with_organization(ctx, **NORTHLIGHT)
    fx.with_initial_cycle(ctx, requested_scope_lines=THREE_SCOPE_LINES)
    fx.with_confirmed_team(ctx, ("lead",))
    plan_a = fx.create_plan(
        client, ctx["app_id"], 3, 2, PLAN_MODE_HYBRID, "2026-09-07", "2026-09-18"
    )
    plan_b = fx.create_plan(
        client, ctx["app_id"], 3, 2, PLAN_MODE_HYBRID, "2026-09-21", "2026-10-02"
    )
    fx.approve_plan(client, plan_b["id"])

    response = client.schedule_witness_session(
        plan_a["id"],
        f.witness_session_payload(
            ctx["lead_id"],
            "2026-09-07T08:00:00Z",
            "2026-09-07T16:00:00Z",
            ACTIVITY_CALIBRATION,
            SITE,
            DELIVERY_ON_SITE,
        ),
        ASSESSMENT_MANAGER,
    )

    validate_error(response, ERR_PLAN_NOT_APPROVED, 422)
    stored_a = validate_success(client.get_plan(plan_a["id"], ASSESSMENT_MANAGER), 200)
    assert stored_a["status"] == PLAN_CANCELLED
    assert stored_a["superseded_by_plan_id"] == plan_b["id"]
    stored_b = validate_success(client.get_plan(plan_b["id"], ASSESSMENT_MANAGER), 200)
    assert stored_b["status"] == PLAN_APPROVED
    assert_total_count(
        client.list_witness_sessions(ASSESSMENT_MANAGER, {"plan_id": plan_a["id"]}), 0
    )
    assert_capacity_ledger(
        fx.read_assessor(client, ctx["lead_id"]), committed=0, available=20
    )
    application = fx.read_application(client, ctx["app_id"])
    assert application["status"] == APP_PLANNED
    assert application["planned_effort_days"] == 8


def test_assessor_capacity_threshold_at_the_exact_annual_limit_is_accepted(client):
    """Booking up to exactly the annual capacity is allowed; the next day is
    not, and only an abort frees it again.

    PRD section 3.6: "A booking whose `day_count` added to the current
    `committed_witness_days` would exceed `annual_witness_capacity_days` is
    rejected with `ERR_ASSESSOR_CAPACITY_EXCEEDED`."

    Design: Corner/cross_cutting_complexity_layers/assessor_capacity_threshold_at_the_exact_annual_limit_is_accepted
    """
    ctx = fx.new_context(client, "ISO17025-CAL")
    fx.with_lead(ctx, capacity_days=4)
    fx.with_organization(ctx, **NORTHLIGHT)
    fx.with_initial_cycle(ctx, requested_scope_lines=THREE_SCOPE_LINES)
    fx.with_confirmed_team(ctx, ("lead",))
    fx.with_approved_plan(ctx, 3, 2, PLAN_MODE_HYBRID)

    first = validate_success(
        client.schedule_witness_session(
            ctx["plan_id"],
            f.witness_session_payload(
                ctx["lead_id"],
                "2026-09-07T08:00:00Z",
                "2026-09-08T16:00:00Z",
                ACTIVITY_CALIBRATION,
                SITE,
                DELIVERY_ON_SITE,
            ),
            ASSESSMENT_MANAGER,
        ),
        201,
    )

    assert first["day_count"] == 4, "Thirty-two hours over an eight-hour day is four days"
    assert_capacity_ledger(
        fx.read_assessor(client, ctx["lead_id"]), committed=4, available=0
    )

    response = client.schedule_witness_session(
        ctx["plan_id"],
        f.witness_session_payload(
            ctx["lead_id"],
            "2026-09-14T08:00:00Z",
            "2026-09-14T16:00:00Z",
            ACTIVITY_CALIBRATION,
            SITE,
            DELIVERY_ON_SITE,
        ),
        ASSESSMENT_MANAGER,
    )

    validate_error(response, ERR_ASSESSOR_CAPACITY_EXCEEDED, 422)
    assert_capacity_ledger(
        fx.read_assessor(client, ctx["lead_id"]), committed=4, available=0
    )
    assert_total_count(
        client.list_witness_sessions(ASSESSMENT_MANAGER, {"plan_id": ctx["plan_id"]}), 1
    )
    aborted = validate_success(
        client.record_session_outcome(
            first["id"],
            f.session_outcome_payload(
                SESSION_ABORTED, None, "Applicant rescheduled the whole witnessing block."
            ),
            ctx["lead_headers"],
        ),
        200,
    )
    assert aborted["status"] == SESSION_ABORTED
    assert_capacity_ledger(
        fx.read_assessor(client, ctx["lead_id"]), committed=0, available=4
    )
