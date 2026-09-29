"""Lifecycle behaviour of the Preschool Child Find API's state machines.

Covers the initial state every new row is written in, terminal-state lockdown and
repeat-trigger refusals on appointments, consent records, assessments, plans and
service lines, the aggregate precondition on event completion, the conditional
cascade from a cancelled event to its appointments, and the roll-up that lifts an
evaluation case to DOMAINS_COMPLETE.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (  # noqa: E402
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402
from test_helpers.api_errors import ApiErrorId  # noqa: E402
from test_helpers.assertions import (  # noqa: E402
    assert_composite_profile,
    assert_delay_figures,
    assert_fields_absent,
    assert_provider_minute_ledger,
    assert_version_unchanged,
)
from test_helpers.constants import date_part, whole_months  # noqa: E402
from test_helpers.test_users import TEST_USERS, make_chair_headers, make_evaluator_headers  # noqa: E402

COORDINATOR = TEST_USERS["coordinator_headers"]
PLACEMENT = TEST_USERS["placement_headers"]

# A birth date that makes the child exactly 36 completed months old both on the
# initial logical-clock date and at the assessment windows used below.
CHILD_DOB_36_MONTHS = "2023-08-01"
COGNITIVE_WINDOW_START = "2026-08-10T09:00:00Z"

# Age-equivalent results that give this 36-month-old child percent delays of
# 33.3 (COMMUNICATION) and 36.1 (COGNITIVE) — the two qualifying domains — and
# sub-threshold delays in the remaining three domains.
FIVE_DOMAIN_AGE_EQUIVALENTS = {
    "COMMUNICATION": 24,
    "COGNITIVE": 23,
    "ADAPTIVE": 34,
    "SOCIAL_EMOTIONAL": 33,
    "PHYSICAL_MOTOR": 30,
}


# --------------------------------------------------------------- local helpers
def _case_with_one_completed_cognitive_assessment(api):
    """A case on the strict standardized protocol holding one COMPLETED domain."""
    child = fx.register_child(api, date_of_birth=CHILD_DOB_36_MONTHS)
    context = fx.setup_case(api, child["id"], assessment_protocol="STANDARDIZED")
    evaluator = fx.register_provider(api, discipline="ECSE_TEACHER")
    scheduled = fx.schedule_assessment(
        api,
        context["case"]["id"],
        evaluator["id"],
        domain="COGNITIVE",
        method="STANDARDIZED",
        window_start_utc=COGNITIVE_WINDOW_START,
    )
    context["evaluator"] = evaluator
    context["assessment"] = fx.complete_assessment(
        api, scheduled["id"], evaluator["id"], 23, standard_score=66
    )
    return context


def _case_with_five_scheduled_domains(api):
    """A case with one SCHEDULED assessment per required domain and none complete."""
    child = fx.register_child(api, date_of_birth=CHILD_DOB_36_MONTHS)
    context = fx.setup_case(api, child["id"], assessment_protocol="STANDARDIZED")
    evaluators = fx.register_domain_evaluators(api)
    scheduled = {}
    for domain, evaluator in evaluators.items():
        scheduled[domain] = fx.schedule_assessment(
            api,
            context["case"]["id"],
            evaluator["id"],
            domain=domain,
            method="STANDARDIZED",
            window_start_utc=fx.DOMAIN_WINDOW_STARTS[domain],
        )
    context["evaluators"] = evaluators
    context["scheduled"] = scheduled
    return context


def _open_event_with_two_booked_slots(api):
    """An OPEN event carrying two BOOKED appointments inside its window."""
    site = fx.register_site(api)
    event = fx.create_open_screening_event(api, site["id"])
    child_a = fx.register_child(api)
    child_b = fx.register_child(api)
    slot_a = fx.book_slot(api, event, child_a["id"])
    event = fx.read_event(api, event["id"])
    slot_b = fx.book_slot(
        api, event, child_b["id"], slot_start_utc="2026-08-10T09:20:00Z"
    )
    return {
        "site": site,
        "event": fx.read_event(api, event["id"]),
        "slot_a": slot_a,
        "slot_b": slot_b,
    }


# ------------------------------------------------- terminal appointments (§3.2)
def test_recording_a_second_outcome_on_a_resolved_slot_is_rejected(api):
    """A resolved appointment refuses every further outcome.

    PRD §3.2: "The parent event must be `OPEN` or `CLOSED` for an attendance record
    to be accepted, and the appointment itself must still be `BOOKED` — recording an
    outcome twice is `ERR_INVALID_SLOT_STATE`."
    PRD §3.2: "`ATTENDED`, `NO_SHOW` and `CANCELLED` are terminal for an appointment."
    PRD §3.2: "The live counter `booked_slot_count` is the number of this event's
    appointments whose status is `BOOKED`, `ATTENDED` or `NO_SHOW`; cancelled
    appointments are excluded and free their capacity again."

    Design: Corner/state_machines/recording_a_second_outcome_on_a_resolved_slot_is_rejected
    """
    context = fx.setup_open_event_with_booked_slot(api)
    slot = context["slot"]

    resolved = fx.record_outcome(api, slot["id"], "ATTENDED", "REFER")
    assert resolved["status"] == "ATTENDED"
    assert resolved["screening_result"] == "REFER"

    replay = api.record_slot_outcome(
        slot["id"], f.slot_outcome_payload("ATTENDED", "REFER"), COORDINATOR
    )
    validate_error(replay, ApiErrorId.ERR_INVALID_SLOT_STATE.value)

    reversal = api.record_slot_outcome(
        slot["id"], f.slot_outcome_payload("NO_SHOW"), COORDINATOR
    )
    validate_error(reversal, ApiErrorId.ERR_INVALID_SLOT_STATE.value)

    after = validate_success(api.get_screening_slot(slot["id"], COORDINATOR))
    assert after["status"] == "ATTENDED"
    assert after["screening_result"] == "REFER"
    assert_version_unchanged(resolved, after)

    event = fx.read_event(api, context["event"]["id"])
    assert event["booked_slot_count"] == 1


# --------------------------------------------------- terminal consent decisions
def test_a_second_decision_on_a_refused_consent_record_is_rejected(api):
    """A refused consent record is terminal, and the referral stays declined.

    PRD §3.4: "A decision on a record whose current `decision` does not permit it —
    granting an already-granted record, or any decision on a record that is `REFUSED`
    or `REVOKED` — is `ERR_INVALID_CONSENT_STATE`."
    PRD §3.4: "`PENDING → REFUSED` moves `intake_status` `CONSENT_PENDING → DECLINED`
    and `consent_status` `REQUESTED → REFUSED`, leaves `evaluation_due_date` absent,
    and recomputes the named interpreter's `assigned_interpreter_assignment_count`,
    since a refused record no longer occupies an assignment."
    PRD §3.9: "Plans at `SUPERSEDED`, and referrals at `DECLINED`, `WITHDRAWN` or
    `SUPERSEDED`, match no clause at all."

    Design: Corner/state_machines/a_second_decision_on_a_refused_consent_record_is_rejected
    """
    child = fx.register_child(api)
    referral = fx.create_referral(api, child["id"])
    consent = fx.issue_evaluation_notice(api, referral["id"])

    refused = fx.decide_consent(api, consent["id"], "REFUSED")
    assert refused["decision"] == "REFUSED"

    grant = api.record_consent_decision(
        consent["id"], f.consent_decision_payload("GRANTED"), COORDINATOR
    )
    validate_error(grant, ApiErrorId.ERR_INVALID_CONSENT_STATE.value)

    revoke = api.record_consent_decision(
        consent["id"], f.consent_decision_payload("REVOKED"), COORDINATOR
    )
    validate_error(revoke, ApiErrorId.ERR_INVALID_CONSENT_STATE.value)

    after = fx.read_consent(api, consent["id"])
    assert after["decision"] == "REFUSED"
    assert_version_unchanged(refused, after)

    settled = fx.read_referral(api, referral["id"])
    assert settled["intake_status"] == "DECLINED"
    assert settled["consent_status"] == "REFUSED"
    assert_fields_absent(settled, "evaluation_due_date")

    assert fx.read_child(api, child["id"])["status"] == "NO_ACTIVE_REFERRAL"

    _, meta = validate_paginated(
        api.list_consent_records(COORDINATOR, {"referral_id": referral["id"], "limit": 100})
    )
    assert meta["total_count"] == 1


# ------------------------------------------- terminal assessments (§3.5 / §2.5)
def test_completing_an_already_completed_assessment_is_rejected(api):
    """Completion is a one-shot trigger and INVALIDATED locks the row for good.

    PRD §3.5: "The parent case must be `IN_PROGRESS` or `DOMAINS_COMPLETE` for a
    completion to be accepted, and completing an assessment that is already
    `COMPLETED` or `INVALIDATED` is `ERR_INVALID_ASSESSMENT_STATE`."
    PRD §3.5: "Both `SCHEDULED → INVALIDATED` and `COMPLETED → INVALIDATED` are
    available, and `INVALIDATED` is terminal."
    PRD §3.5: "Invalidation from `COMPLETED` does the same and, in addition, retains
    `percent_delay`, `weighted_percent_delay` and `qualifies_delay` on the row as
    historical values while removing the row from every case aggregate, then
    recomputes the parent case's aggregates."
    PRD §2.5: "This rule covers terminal-state lockdown and repeat-trigger failures,
    and it deliberately sits above every referential, temporal, structural and
    capacity rule."

    Design: Corner/state_machines/completing_an_already_completed_assessment_is_rejected
    """
    context = _case_with_one_completed_cognitive_assessment(api)
    assessment = context["assessment"]
    evaluator_headers = make_evaluator_headers(context["evaluator"]["id"])
    chair_headers = make_chair_headers(context["chair"]["id"])

    assert assessment["status"] == "COMPLETED"
    assert assessment["chronological_age_months"] == 36
    assert assessment["age_equivalent_months"] == 23
    assert_delay_figures(assessment, 36.1, 36.1, True)

    replay = api.complete_domain_assessment(
        assessment["id"], f.assessment_completion_payload(34), evaluator_headers
    )
    validate_error(replay, ApiErrorId.ERR_INVALID_ASSESSMENT_STATE.value)

    unchanged = fx.read_assessment(api, assessment["id"])
    assert unchanged["age_equivalent_months"] == 23
    assert_delay_figures(unchanged, 36.1, 36.1, True)

    invalidated = validate_success(
        api.invalidate_domain_assessment(
            assessment["id"], f.assessment_invalidation_payload(), chair_headers
        )
    )
    assert invalidated["status"] == "INVALIDATED"
    assert invalidated["age_equivalent_months"] == 23
    assert_delay_figures(invalidated, 36.1, 36.1, True)

    after_invalidation = api.complete_domain_assessment(
        assessment["id"], f.assessment_completion_payload(30), evaluator_headers
    )
    validate_error(after_invalidation, ApiErrorId.ERR_INVALID_ASSESSMENT_STATE.value)

    second_invalidation = api.invalidate_domain_assessment(
        assessment["id"], f.assessment_invalidation_payload("Second attempt"), chair_headers
    )
    validate_error(second_invalidation, ApiErrorId.ERR_INVALID_ASSESSMENT_STATE.value)

    final = fx.read_assessment(api, assessment["id"])
    assert final["status"] == "INVALIDATED"
    assert_version_unchanged(invalidated, final)

    case = fx.read_case(api, context["case"]["id"])
    assert case["completed_domain_count"] == 0
    assert case["status"] == "IN_PROGRESS"


# ------------------------------------------------- plans past DRAFT (§3.8/§3.9)
def test_adding_a_service_line_after_consent_submission_is_rejected(api):
    """Once a plan is out for parental consent it accepts no more lines and no resend.

    PRD §3.8: "Lines may only be added to a plan that is still at `DRAFT`; adding one
    to any other plan is refused with `ERR_INVALID_PLAN_STATE`."
    PRD §3.9: "Submitting a plan that is not at `DRAFT` is `ERR_INVALID_PLAN_STATE`,
    as is submitting a plan whose `eligibility_decision` is not `ELIGIBLE` or whose
    `setting` is absent."
    PRD §3.8: "Adding a line recomputes the parent plan's `assigned_weekly_minutes`,
    which is the sum of `weekly_minutes` across the plan's lines whose `status` is
    `PROPOSED`, `STAFFED` or `UNSTAFFED`; lines that have been `DISCONTINUED` drop out
    of that total."
    PRD §3.9: "Only the community-preschool branch reserves a seat: on a successful
    submission the named site's `reserved_iep_seat_count` increases by exactly one."

    Design: Corner/state_machines/adding_a_service_line_after_consent_submission_is_rejected
    """
    site = fx.register_site(api)
    context = fx.setup_plan_pending_parent_consent(
        api,
        setting="COMMUNITY_PRESCHOOL",
        community_site_id=site["id"],
        discipline="SLP",
        weekly_minutes=150,
        delivery_model="DIRECT",
    )
    plan = context["plan"]
    assert plan["status"] == "PENDING_PARENT_CONSENT"

    late_line = api.add_service_line(
        plan["id"],
        f.service_line_payload(discipline="OT", weekly_minutes=60, delivery_model="DIRECT"),
        PLACEMENT,
    )
    validate_error(late_line, ApiErrorId.ERR_INVALID_PLAN_STATE.value)

    resubmission = api.submit_plan_for_consent(
        plan["id"], f.consent_submission_payload(), PLACEMENT
    )
    validate_error(resubmission, ApiErrorId.ERR_INVALID_PLAN_STATE.value)

    after = fx.read_plan(api, plan["id"])
    assert after["status"] == "PENDING_PARENT_CONSENT"
    assert after["assigned_weekly_minutes"] == 150
    assert_version_unchanged(plan, after)

    _, line_meta = validate_paginated(
        api.list_service_lines(PLACEMENT, {"service_plan_id": plan["id"], "limit": 100})
    )
    assert line_meta["total_count"] == 1

    _, consent_meta = validate_paginated(
        api.list_consent_records(COORDINATOR, {"service_plan_id": plan["id"], "limit": 100})
    )
    assert consent_meta["total_count"] == 1

    assert fx.read_site(api, site["id"])["reserved_iep_seat_count"] == 1


def test_unstaffing_a_line_that_was_never_staffed_is_rejected(api):
    """Unstaffing needs a STAFFED line, and releasing one restores the ledger exactly.

    PRD §3.8: "Unstaffing takes an optional `unstaff_reason`, requires the parent plan
    to be at `DRAFT` or `ACTIVE`, and requires the line to be `STAFFED` — unstaffing
    anything else is `ERR_INVALID_LINE_STATE`."
    PRD §3.8: "Because the minute figures are recomputed from the current set of
    contributing lines rather than adjusted by a remembered delta, the released
    provider's numbers return to exactly what they were before the line was staffed."
    PRD §3.8: "The parent plan's `assigned_weekly_minutes` is deliberately
    **unchanged** by unstaffing, because an `UNSTAFFED` line is still a commitment the
    plan has made and still counts toward the plan total."
    PRD §3.8: "it reads `AT_CAPACITY` when `assigned_weekly_service_minutes` has
    reached or passed `max_weekly_service_minutes`, `NEAR_CAPACITY` when the ratio of
    assigned minutes to the ceiling has reached eight tenths, and `OPEN` otherwise."

    Design: Corner/state_machines/unstaffing_a_line_that_was_never_staffed_is_rejected
    """
    site = fx.register_site(api)
    provider = fx.register_provider(
        api, discipline="SLP", max_weekly_service_minutes=400
    )
    context = fx.setup_staffed_draft_plan(
        api,
        setting="COMMUNITY_PRESCHOOL",
        community_site_id=site["id"],
        discipline="SLP",
        weekly_minutes=150,
        delivery_model="DIRECT",
        provider=provider,
    )
    plan = context["plan"]
    staffed_line = context["line"]
    assert staffed_line["status"] == "STAFFED"

    proposed_line = fx.add_line(
        api, plan["id"], discipline="SLP", weekly_minutes=150, delivery_model="DIRECT"
    )
    assert proposed_line["status"] == "PROPOSED"

    never_staffed = api.unstaff_service_line(
        proposed_line["id"], f.unstaffing_payload("Nobody was ever assigned"), PLACEMENT
    )
    validate_error(never_staffed, ApiErrorId.ERR_INVALID_LINE_STATE.value)

    released = fx.unstaff_line(api, staffed_line["id"], unstaff_reason="Caseload rebalance")
    assert released["status"] == "UNSTAFFED"
    assert_fields_absent(released, "provider_id", "delivery_site_id")

    replay = api.unstaff_service_line(
        staffed_line["id"], f.unstaffing_payload("Already released"), PLACEMENT
    )
    validate_error(replay, ApiErrorId.ERR_INVALID_LINE_STATE.value)

    assert fx.read_line(api, proposed_line["id"])["status"] == "PROPOSED"
    assert_version_unchanged(released, fx.read_line(api, staffed_line["id"]))

    assert_provider_minute_ledger(fx.read_provider(api, provider["id"]), 0, 0, 0, "OPEN")
    assert fx.read_plan(api, plan["id"])["assigned_weekly_minutes"] == 300


# ----------------------------------------------------- declared initial states
def test_a_new_referral_starts_at_received_and_not_requested(api):
    """Intake writes both referral dimensions in their declared initial states.

    PRD §3.3: "`intake_status` tracks the intake workflow and runs `RECEIVED`,
    `CONSENT_PENDING`, `EVALUATION_AUTHORIZED`, `DECLINED`, `WITHDRAWN` and
    `SUPERSEDED`, initialised to `RECEIVED`, with `DECLINED`, `WITHDRAWN` and
    `SUPERSEDED` terminal."
    PRD §3.3: "`consent_status` tracks the parental consent position and runs
    `NOT_REQUESTED`, `REQUESTED`, `GRANTED`, `REFUSED` and `REVOKED`, initialised to
    `NOT_REQUESTED`, with `REFUSED` and `REVOKED` terminal."

    Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
    """
    referral = fx.create_referral(api)

    assert referral["intake_status"] == "RECEIVED"
    assert referral["consent_status"] == "NOT_REQUESTED"


def test_a_new_consent_record_starts_pending_and_undecided(api):
    """An issued evaluation notice creates an undecided evaluation-consent record.

    PRD §3.4: "The issuance creates a `ConsentRecord` whose `kind` is
    `EVALUATION_CONSENT`; `kind` is set by the issuing endpoint and never by the
    client."
    PRD §3.4: "The new record's `decision` starts at `PENDING`, its `requested_at` is
    stamped from the logical clock, its `decided_at` is absent, and its
    `service_plan_id` is absent because that field is populated only on service-consent
    records."

    Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
    """
    referral = fx.create_referral(api)

    consent = fx.issue_evaluation_notice(api, referral["id"])

    assert consent["kind"] == "EVALUATION_CONSENT"
    assert consent["decision"] == "PENDING"
    assert_fields_absent(consent, "decided_at", "service_plan_id")


def test_a_new_evaluation_case_starts_planned_and_indeterminate(api):
    """A freshly opened case is planned, owes five domains and has completed none.

    PRD §3.5: "A new case is written at `PLANNED` with `revision_round` at 0 and
    `required_domain_count` fixed by the system at 5 — the five developmental domains
    the team must cover."
    PRD §3.6: "If `completed_domain_count` is below five, the recommendation is
    `INDETERMINATE` regardless of anything else."

    Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
    """
    case = fx.setup_case(api)["case"]

    assert case["status"] == "PLANNED"
    assert case["revision_round"] == 0
    assert case["required_domain_count"] == 5
    assert case["completed_domain_count"] == 0
    assert case["composite_eligibility_recommendation"] == "INDETERMINATE"


def test_a_new_domain_assessment_starts_scheduled_without_results(api):
    """Scheduling writes the age anchor only; every result field stays empty.

    PRD §3.5: "A scheduled assessment is written at `SCHEDULED`, with
    `chronological_age_months` computed as the whole completed months between the
    child's `date_of_birth` and the calendar date of `window_start_utc`, and with
    `age_equivalent_months`, `standard_score`, `percent_delay`,
    `weighted_percent_delay`, `completed_at` and `invalidation_reason` all absent and
    `qualifies_delay` false."

    Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
    """
    context = fx.setup_case(api)
    evaluator = fx.register_provider(api, discipline="ECSE_TEACHER")
    window_start = fx.DOMAIN_WINDOW_STARTS["COGNITIVE"]

    assessment = fx.schedule_assessment(
        api,
        context["case"]["id"],
        evaluator["id"],
        domain="COGNITIVE",
        window_start_utc=window_start,
    )

    assert assessment["status"] == "SCHEDULED"
    assert assessment["chronological_age_months"] == whole_months(
        context["child"]["date_of_birth"], date_part(window_start)
    )
    assert assessment["qualifies_delay"] is False
    assert_fields_absent(
        assessment,
        "age_equivalent_months",
        "standard_score",
        "percent_delay",
        "weighted_percent_delay",
        "completed_at",
        "invalidation_reason",
    )


def test_a_new_screening_event_starts_scheduled_with_no_bookings(api):
    """A screening event opens at SCHEDULED with an empty appointment book.

    PRD §3.2: "A new event opens at `SCHEDULED` and advances through the coordinator's
    status endpoint, which takes a single `target_status` input."
    PRD §3.2: "The live counter `booked_slot_count` is the number of this event's
    appointments whose status is `BOOKED`, `ATTENDED` or `NO_SHOW`; cancelled
    appointments are excluded and free their capacity again."

    Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
    """
    event = fx.create_screening_event(api)

    assert event["status"] == "SCHEDULED"
    assert event["booked_slot_count"] == 0


def test_a_new_screening_slot_starts_booked_without_a_result(api):
    """A booked appointment carries no screening result until an outcome is recorded.

    PRD §3.2: "A successful booking creates the appointment at `BOOKED`, recomputes the
    parent event's `booked_slot_count`, and increments the parent event's `version`."
    PRD §3.2: "Attendance is recorded through the appointment's outcome endpoint, which
    takes an `attendance` value and, for an attended appointment, a `screening_result`."

    Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
    """
    context = fx.setup_open_event_with_booked_slot(api)

    slot = context["slot"]
    assert slot["status"] == "BOOKED"
    assert_fields_absent(slot, "screening_result")
    assert context["event"]["booked_slot_count"] == 1


# ------------------------------------------- guarded and cascading event edges
def test_an_event_cannot_complete_while_a_slot_is_still_booked(api):
    """Completion waits until every appointment of the event has been resolved.

    PRD §3.2: "`CLOSED → COMPLETED` is permitted only when every appointment of the
    event has reached `ATTENDED`, `NO_SHOW` or `CANCELLED`; if even one is still
    `BOOKED` the completion is refused with `ERR_SCREENING_SLOTS_UNRESOLVED`."
    PRD §3.2: "The live counter `booked_slot_count` is the number of this event's
    appointments whose status is `BOOKED`, `ATTENDED` or `NO_SHOW`; cancelled
    appointments are excluded and free their capacity again."

    Design: Corner/state_machines/an_event_cannot_complete_while_a_slot_is_still_booked
    """
    context = _open_event_with_two_booked_slots(api)
    event_id = context["event"]["id"]
    closed = fx.advance_event(api, event_id, "CLOSED")
    assert closed["status"] == "CLOSED"

    both_booked = api.set_screening_event_status(
        event_id, f.event_status_payload("COMPLETED"), COORDINATOR
    )
    validate_error(both_booked, ApiErrorId.ERR_SCREENING_SLOTS_UNRESOLVED.value)

    fx.record_outcome(api, context["slot_a"]["id"], "ATTENDED", "PASS")

    one_still_booked = api.set_screening_event_status(
        event_id, f.event_status_payload("COMPLETED"), COORDINATOR
    )
    validate_error(one_still_booked, ApiErrorId.ERR_SCREENING_SLOTS_UNRESOLVED.value)
    assert fx.read_event(api, event_id)["status"] == "CLOSED"

    fx.record_outcome(api, context["slot_b"]["id"], "NO_SHOW")

    completed = fx.advance_event(api, event_id, "COMPLETED")
    assert completed["status"] == "COMPLETED"
    assert completed["booked_slot_count"] == 2

    assert validate_success(
        api.get_screening_slot(context["slot_a"]["id"], COORDINATOR)
    )["status"] == "ATTENDED"
    assert validate_success(
        api.get_screening_slot(context["slot_b"]["id"], COORDINATOR)
    )["status"] == "NO_SHOW"


def test_cancelling_an_open_event_cascades_its_booked_slots_to_cancelled(api):
    """Cancellation sweeps only the still-booked appointments and spares the resolved.

    PRD §3.2: "Cancelling from `OPEN` or from `CLOSED` additionally performs a
    **conditional** cascade: every appointment of that event still in `BOOKED` moves to
    `CANCELLED`, while appointments already `ATTENDED`, `NO_SHOW` or `CANCELLED` are
    left untouched, and `booked_slot_count` is recomputed and so drops to the number of
    attended and no-show appointments."

    Design: Corner/state_machines/cancelling_an_open_event_cascades_its_booked_slots_to_cancelled
    """
    context = _open_event_with_two_booked_slots(api)
    event_id = context["event"]["id"]
    attended = fx.record_outcome(api, context["slot_a"]["id"], "ATTENDED", "PASS")

    cancelled_event = fx.advance_event(api, event_id, "CANCELLED")

    assert cancelled_event["status"] == "CANCELLED"
    assert cancelled_event["booked_slot_count"] == 1

    untouched = validate_success(
        api.get_screening_slot(context["slot_a"]["id"], COORDINATOR)
    )
    assert untouched["status"] == "ATTENDED"
    assert untouched["screening_result"] == "PASS"
    assert_version_unchanged(attended, untouched)

    swept = validate_success(api.get_screening_slot(context["slot_b"]["id"], COORDINATOR))
    assert swept["status"] == "CANCELLED"

    _, meta = validate_paginated(
        api.list_screening_slots(
            COORDINATOR,
            {"screening_event_id": event_id, "status": "CANCELLED", "limit": 100},
        )
    )
    assert meta["total_count"] == 1


# -------------------------------------------------- the case-level roll-up (§3.5)
def test_the_case_bubbles_to_domains_complete_only_on_the_fifth_completion(api):
    """Four completed domains leave the case in progress; the fifth lifts it.

    PRD §3.5: "On acceptance the assessment moves `SCHEDULED → COMPLETED`,
    `completed_at` is stamped from the logical clock, the delay figures of §3.6 are
    computed, the parent case's `completed_domain_count`, `qualifying_domain_count`,
    `max_weighted_percent_delay`, `composite_eligibility_recommendation` and
    `recommended_weekly_minutes` are all recomputed, the assessment's `version` is
    incremented, and — once five distinct domains stand `COMPLETED` on the case — the
    case itself moves `IN_PROGRESS → DOMAINS_COMPLETE` and increments its own
    `version`."
    PRD §3.6: "If `completed_domain_count` is below five, the recommendation is
    `INDETERMINATE` regardless of anything else."
    PRD §3.6: "Otherwise, if `max_weighted_percent_delay` is present and has reached
    33.0 percent — a single domain severe enough to stand on its own — **or**
    `qualifying_domain_count` has reached 2 — two or more domains each at or above the
    25.0 threshold — the recommendation is `ELIGIBLE_RECOMMENDED`."
    PRD §3.6: "Two qualifying domains at 33.3 percent and 36.1 percent, for instance,
    both take the 1.15 multiplier and so both produce a raw allocation of 57.5 minutes:
    rounding each up to 60 and then adding gives 120 minutes, whereas adding first to
    115.0 and rounding once gives 115."

    Design: Corner/state_machines/the_case_bubbles_to_domains_complete_only_on_the_fifth_completion
    """
    context = _case_with_five_scheduled_domains(api)
    case_id = context["case"]["id"]
    order = ["COMMUNICATION", "COGNITIVE", "ADAPTIVE", "SOCIAL_EMOTIONAL", "PHYSICAL_MOTOR"]

    for domain in order[:4]:
        fx.complete_assessment(
            api,
            context["scheduled"][domain]["id"],
            context["evaluators"][domain]["id"],
            FIVE_DOMAIN_AGE_EQUIVALENTS[domain],
        )

    four_done = fx.read_case(api, case_id)
    assert four_done["status"] == "IN_PROGRESS"
    assert four_done["completed_domain_count"] == 4
    assert four_done["composite_eligibility_recommendation"] == "INDETERMINATE"

    last_domain = order[4]
    fifth = fx.complete_assessment(
        api,
        context["scheduled"][last_domain]["id"],
        context["evaluators"][last_domain]["id"],
        FIVE_DOMAIN_AGE_EQUIVALENTS[last_domain],
    )
    assert fifth["status"] == "COMPLETED"

    five_done = fx.read_case(api, case_id)
    assert five_done["status"] == "DOMAINS_COMPLETE"
    assert_composite_profile(five_done, 5, 2, 36.1, "ELIGIBLE_RECOMMENDED", 120)
