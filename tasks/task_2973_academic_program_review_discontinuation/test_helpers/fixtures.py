"""Composite setup helpers, arranged as a ladder from cheapest to deepest.

Each helper returns the records it created so a test can assert against them
without re-reading. Helpers that walk several hops read the parent's current
``version`` immediately before the hop that needs it, rather than counting
increments, because §2.4 makes derived-field recomputation on a parent bump that
parent's version as a side effect of activity elsewhere.

The database is empty before every test, so every helper starts from nothing.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .constants import CLOCK_STARTUP_DEFAULT, FIXTURE_A_SNAPSHOTS
from .test_users import (
    make_external_reviewer_headers,
    make_hr_partner_headers,
    make_program_chair_headers,
    make_provost_proposer_headers,
    make_provost_ratifier_headers,
    make_registrar_headers,
    make_review_coordinator_headers,
)

# Clock anchors the ladder uses. Every one is a full instant with a trailing Z.
CLOCK_AT_START = CLOCK_STARTUP_DEFAULT
VISIT_WINDOW_START = "2026-08-20T09:00:00Z"
VISIT_WINDOW_END = "2026-08-22T17:00:00Z"
CLOCK_AFTER_VISIT = "2026-08-25T00:00:00Z"
CLOCK_AT_RATIFICATION = "2026-09-15T10:00:00Z"


@dataclass
class ReviewContext:
    """Everything a deep workflow test needs to keep hold of."""

    program: Dict[str, Any]
    cycle: Optional[Dict[str, Any]] = None
    self_study: Optional[Dict[str, Any]] = None
    reviewer: Optional[Dict[str, Any]] = None
    visit: Optional[Dict[str, Any]] = None
    report: Optional[Dict[str, Any]] = None
    decision: Optional[Dict[str, Any]] = None
    notifications: List[Dict[str, Any]] = field(default_factory=list)
    plan: Optional[Dict[str, Any]] = None
    guarantees: List[Dict[str, Any]] = field(default_factory=list)
    students: List[Dict[str, Any]] = field(default_factory=list)
    appointments: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def program_id(self) -> str:
        return self.program["id"]

    @property
    def cycle_id(self) -> str:
        assert self.cycle is not None
        return self.cycle["id"]

    @property
    def chair_headers(self) -> Dict[str, str]:
        return make_program_chair_headers(self.program["id"])


# --- Tier 1: the clock ------------------------------------------------------


def set_clock(api: ApiClient, current_utc: str) -> str:
    """Move the logical clock and return the instant the server adopted."""
    data = get_success_data(
        api.set_clock(current_utc, make_review_coordinator_headers())
    )
    return data["current_utc"]


# --- Tier 2: a program ------------------------------------------------------


def create_program(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register one academic program."""
    return get_success_data(
        api.create_program(
            factories.program_payload(**overrides), make_review_coordinator_headers()
        ),
        201,
    )


def append_snapshots(
    api: ApiClient, program_id: str, snapshots: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Append term observations in the order given."""
    created = []
    for snapshot in snapshots:
        created.append(
            get_success_data(
                api.create_metric_snapshot(
                    program_id,
                    factories.metric_snapshot_payload(**snapshot),
                    make_review_coordinator_headers(),
                ),
                201,
            )
        )
    return created


def read_program(api: ApiClient, program_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_program(program_id, make_review_coordinator_headers())
    )


def read_cycle(api: ApiClient, cycle_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_review_cycle(cycle_id, make_review_coordinator_headers())
    )


def read_plan(api: ApiClient, plan_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_teach_out_plan(plan_id, make_review_coordinator_headers())
    )


def read_decision(api: ApiClient, decision_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_decision_record(decision_id, make_review_coordinator_headers())
    )


def create_nonviable_program(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A program carrying the three-snapshot fixture whose band is NONVIABLE."""
    program = create_program(api, **overrides)
    append_snapshots(api, program["id"], FIXTURE_A_SNAPSHOTS)
    return read_program(api, program["id"])


def create_continue_eligible_program(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A program whose band is CONTINUE_ELIGIBLE, for use as a consolidation target.

    Rising enrolment, strong completions, top demand and a cost well below the
    50,000-cent benchmark put every factor at or near its clamp.
    """
    program = create_program(api, **overrides)
    append_snapshots(
        api,
        program["id"],
        [
            {
                "term_code": "2025FA",
                "term_index": 1,
                "enrollment_headcount": 100,
                "credit_hours": 1000,
                "direct_cost_cents": 20000000,
                "completions_count": 40,
                "market_demand_index": 100,
            },
            {
                "term_code": "2026SP",
                "term_index": 2,
                "enrollment_headcount": 150,
                "credit_hours": 1500,
                "direct_cost_cents": 30000000,
                "completions_count": 60,
                "market_demand_index": 100,
            },
            {
                "term_code": "2026FA",
                "term_index": 3,
                "enrollment_headcount": 200,
                "credit_hours": 2000,
                "direct_cost_cents": 40000000,
                "completions_count": 80,
                "market_demand_index": 100,
            },
        ],
    )
    return read_program(api, program["id"])


# --- Tier 3: a review cycle and its self-study -----------------------------


def open_cycle(api: ApiClient, program_id: str, **overrides: Any) -> Dict[str, Any]:
    """Open a review cycle, which also moves the program to UNDER_REVIEW."""
    return get_success_data(
        api.create_review_cycle(
            program_id,
            factories.review_cycle_payload(**overrides),
            make_review_coordinator_headers(),
        ),
        201,
    )


def create_self_study(
    api: ApiClient, cycle_id: str, program_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_self_study(
            cycle_id,
            factories.self_study_payload(**overrides),
            make_program_chair_headers(program_id),
        ),
        201,
    )


def accept_self_study(
    api: ApiClient, self_study_id: str, program_id: str
) -> Dict[str, Any]:
    """Submit as the chair, then accept as the coordinator."""
    get_success_data(
        api.transition_self_study(
            self_study_id,
            factories.self_study_submit_payload(),
            make_program_chair_headers(program_id),
        )
    )
    return get_success_data(
        api.transition_self_study(
            self_study_id,
            factories.self_study_accept_payload(),
            make_review_coordinator_headers(),
        )
    )


def register_reviewer(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_external_reviewer(
            factories.external_reviewer_payload(**overrides),
            make_review_coordinator_headers(),
        ),
        201,
    )


def schedule_visit(
    api: ApiClient,
    cycle_id: str,
    reviewer_id: str,
    window_start_at: str = VISIT_WINDOW_START,
    window_end_at: str = VISIT_WINDOW_END,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_reviewer_visit(
            factories.reviewer_visit_payload(
                cycle_id, reviewer_id, window_start_at, window_end_at
            ),
            make_review_coordinator_headers(),
        ),
        201,
    )


def complete_visit(api: ApiClient, visit_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.complete_reviewer_visit(visit_id, make_review_coordinator_headers())
    )


def file_report(
    api: ApiClient, visit_id: str, reviewer_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_reviewer_report(
            visit_id,
            factories.reviewer_report_payload(**overrides),
            make_external_reviewer_headers(reviewer_id),
        ),
        201,
    )


def file_program_response(
    api: ApiClient, cycle_id: str, program_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.file_program_response(
            cycle_id,
            factories.program_response_payload(**overrides),
            make_program_chair_headers(program_id),
        )
    )


# --- Tier 4: a cycle carried to RESPONSE_SUBMITTED -------------------------


def carry_cycle_to_response_submitted(
    api: ApiClient,
    program: Optional[Dict[str, Any]] = None,
    concurrence: str = "CONCUR",
    **program_overrides: Any,
) -> ReviewContext:
    """Walk a cycle from SELF_STUDY_OPEN to RESPONSE_SUBMITTED.

    The clock is moved past the visit window so that completion is permitted,
    and the self-study is submitted before the move so that its own deadline is
    still open when it matters.
    """
    if program is None:
        program = create_nonviable_program(api, **program_overrides)
    program_id = program["id"]
    cycle = open_cycle(api, program_id)
    self_study = create_self_study(api, cycle["id"], program_id)
    self_study = accept_self_study(api, self_study["id"], program_id)
    reviewer = register_reviewer(api)
    visit = schedule_visit(api, cycle["id"], reviewer["id"])
    set_clock(api, CLOCK_AFTER_VISIT)
    visit = complete_visit(api, visit["id"])
    report = file_report(api, visit["id"], reviewer["id"])
    file_program_response(api, cycle["id"], program_id, response_concurrence=concurrence)
    return ReviewContext(
        program=read_program(api, program_id),
        cycle=read_cycle(api, cycle["id"]),
        self_study=self_study,
        reviewer=reviewer,
        visit=visit,
        report=report,
    )


# --- Tier 5: decisions ------------------------------------------------------


def propose_decision(
    api: ApiClient, ctx: ReviewContext, outcome: str = "DISCONTINUATION", **overrides: Any
) -> Dict[str, Any]:
    """Propose an outcome, reading the cycle's current version first."""
    cycle = read_cycle(api, ctx.cycle_id)
    payload = factories.decision_payload(
        outcome=outcome, expected_cycle_version=cycle["version"], **overrides
    )
    decision = get_success_data(
        api.create_decision_record(
            ctx.cycle_id, payload, make_provost_proposer_headers()
        ),
        201,
    )
    ctx.decision = decision
    ctx.cycle = read_cycle(api, ctx.cycle_id)
    return decision


def ratify_decision(api: ApiClient, ctx: ReviewContext) -> Dict[str, Any]:
    """Ratify as the second provost, which fires the four-hop cascade."""
    assert ctx.decision is not None
    decision = get_success_data(
        api.transition_decision_record(
            ctx.decision["id"],
            factories.ratify_payload(),
            make_provost_ratifier_headers(),
        )
    )
    ctx.decision = decision
    ctx.cycle = read_cycle(api, ctx.cycle_id)
    ctx.program = read_program(api, ctx.program_id)
    ctx.notifications = list_notifications(api, decision["id"])
    return decision


def list_notifications(api: ApiClient, decision_id: str) -> List[Dict[str, Any]]:
    data, _meta = _paginated(
        api.list_agency_notifications(decision_id, make_review_coordinator_headers())
    )
    return data


def acknowledge_notification(api: ApiClient, notification_id: str) -> Dict[str, Any]:
    """Send then acknowledge one notice."""
    get_success_data(
        api.transition_agency_notification(
            notification_id,
            factories.notification_send_payload(),
            make_review_coordinator_headers(),
        )
    )
    return get_success_data(
        api.transition_agency_notification(
            notification_id,
            factories.notification_acknowledge_payload(),
            make_review_coordinator_headers(),
        )
    )


def acknowledge_all_notifications(api: ApiClient, decision_id: str) -> List[Dict[str, Any]]:
    """Clear the compliance gate on a decision."""
    cleared = []
    for notification in list_notifications(api, decision_id):
        if notification["status"] in ("PENDING", "OVERDUE"):
            cleared.append(acknowledge_notification(api, notification["id"]))
        elif notification["status"] == "SENT":
            cleared.append(
                get_success_data(
                    api.transition_agency_notification(
                        notification["id"],
                        factories.notification_acknowledge_payload(),
                        make_review_coordinator_headers(),
                    )
                )
            )
    return cleared


def effectuate_decision(api: ApiClient, ctx: ReviewContext) -> Dict[str, Any]:
    assert ctx.decision is not None
    decision = get_success_data(
        api.transition_decision_record(
            ctx.decision["id"],
            factories.effectuate_payload(),
            make_review_coordinator_headers(),
        )
    )
    ctx.decision = decision
    ctx.cycle = read_cycle(api, ctx.cycle_id)
    ctx.program = read_program(api, ctx.program_id)
    return decision


def _paginated(response):
    """Unwrap a list response's data and meta without a second envelope hop."""
    assert response.status_code == 200, (
        f"expected 200 from a list channel, got {response.status_code}: "
        f"{response.text}"
    )
    body = response.json()
    return body["data"], body["meta"]


# --- Tier 6: teach-out plans ------------------------------------------------


def file_plan(api: ApiClient, ctx: ReviewContext, **overrides: Any) -> Dict[str, Any]:
    """File a teach-out plan, reading the program's current version first."""
    assert ctx.decision is not None
    program = read_program(api, ctx.program_id)
    payload = factories.teach_out_plan_payload(
        decision_id=ctx.decision["id"],
        expected_program_version=program["version"],
        **overrides,
    )
    plan = get_success_data(
        api.create_teach_out_plan(ctx.program_id, payload, ctx.chair_headers), 201
    )
    ctx.plan = plan
    ctx.program = read_program(api, ctx.program_id)
    return plan


def add_guarantee(api: ApiClient, ctx: ReviewContext, **overrides: Any) -> Dict[str, Any]:
    assert ctx.plan is not None
    guarantee = get_success_data(
        api.create_course_guarantee(
            ctx.plan["id"],
            factories.course_guarantee_payload(**overrides),
            ctx.chair_headers,
        ),
        201,
    )
    ctx.guarantees.append(guarantee)
    return guarantee


def enrol_student(api: ApiClient, ctx: ReviewContext, **overrides: Any) -> Dict[str, Any]:
    assert ctx.plan is not None
    student = get_success_data(
        api.create_displaced_student(
            ctx.plan["id"],
            factories.displaced_student_payload(**overrides),
            make_registrar_headers(),
        ),
        201,
    )
    ctx.students.append(student)
    return student


def record_advising(
    api: ApiClient, student_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.record_advising(
            student_id, factories.advising_payload(**overrides), make_registrar_headers()
        )
    )


def submit_plan(api: ApiClient, ctx: ReviewContext) -> Dict[str, Any]:
    assert ctx.plan is not None
    plan = get_success_data(
        api.transition_teach_out_plan(
            ctx.plan["id"], factories.plan_transition_payload("SUBMIT"), ctx.chair_headers
        )
    )
    ctx.plan = plan
    return plan


def approve_plan(api: ApiClient, ctx: ReviewContext) -> Dict[str, Any]:
    assert ctx.plan is not None
    plan = get_success_data(
        api.transition_teach_out_plan(
            ctx.plan["id"],
            factories.plan_transition_payload("APPROVE"),
            make_provost_ratifier_headers(),
        )
    )
    ctx.plan = plan
    return plan


def activate_plan(api: ApiClient, ctx: ReviewContext) -> Dict[str, Any]:
    assert ctx.plan is not None
    plan = get_success_data(
        api.transition_teach_out_plan(
            ctx.plan["id"],
            factories.plan_transition_payload("ACTIVATE"),
            make_review_coordinator_headers(),
        )
    )
    ctx.plan = plan
    ctx.program = read_program(api, ctx.program_id)
    return plan


# --- Tier 7: faculty appointments ------------------------------------------


def create_appointment(
    api: ApiClient, program_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_faculty_appointment(
            program_id,
            factories.faculty_appointment_payload(**overrides),
            make_hr_partner_headers(),
        ),
        201,
    )


def transition_appointment(
    api: ApiClient, appointment_id: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    return get_success_data(
        api.transition_faculty_appointment(
            appointment_id, payload, make_hr_partner_headers()
        )
    )


def list_appointments(api: ApiClient, program_id: str) -> List[Dict[str, Any]]:
    data, _meta = _paginated(
        api.list_faculty_appointments(program_id, make_hr_partner_headers())
    )
    return data


# --- Composite setups the deep tests share ---------------------------------


def setup_ratified_discontinuation(
    api: ApiClient, **program_overrides: Any
) -> ReviewContext:
    """A NONVIABLE program with a RATIFIED DISCONTINUATION decision.

    The clock sits at the ratification anchor so that the two auto-minted
    notices fall due at exactly the instants §2.5 works through.
    """
    ctx = carry_cycle_to_response_submitted(api, **program_overrides)
    set_clock(api, CLOCK_AT_RATIFICATION)
    propose_decision(api, ctx, "DISCONTINUATION")
    ratify_decision(api, ctx)
    return ctx


def setup_approved_plan(api: ApiClient, **program_overrides: Any) -> ReviewContext:
    """A RATIFIED discontinuation carrying an APPROVED teach-out plan.

    The plan holds one guarantee of six seats and one student needing four, so
    both approval gates — ``seat_shortfall`` and ``at_risk_student_count`` — read
    0 at the moment approval is requested.
    """
    ctx = setup_ratified_discontinuation(api, **program_overrides)
    file_plan(api, ctx)
    add_guarantee(api, ctx)
    enrol_student(api, ctx, credits_remaining=12, max_credits_per_term=15)
    submit_plan(api, ctx)
    approve_plan(api, ctx)
    ctx.plan = read_plan(api, ctx.plan["id"])
    return ctx


def setup_effectuated_discontinuation(
    api: ApiClient, **program_overrides: Any
) -> ReviewContext:
    """An EFFECTUATED discontinuation: notices cleared, plan APPROVED, no deferred FTE."""
    ctx = setup_approved_plan(api, **program_overrides)
    acknowledge_all_notifications(api, ctx.decision["id"])
    effectuate_decision(api, ctx)
    return ctx


def setup_plan_in_effect(api: ApiClient, **program_overrides: Any) -> ReviewContext:
    """A teach-out plan in IN_EFFECT, holding one open student.

    The open student is what stops activation from auto-completing the plan, so
    the plan stays in IN_EFFECT for the test to work against.
    """
    ctx = setup_effectuated_discontinuation(api, **program_overrides)
    activate_plan(api, ctx)
    ctx.plan = read_plan(api, ctx.plan["id"])
    return ctx
