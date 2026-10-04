"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because the server is restarted before each test. Setup calls use
`get_success_data()` so a broken precondition surfaces as a clear "Setup failed"
rather than as a confusing assertion inside the test body.
"""
from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from .api_client import api_client
from .factories import (
    add_line_payload,
    completion_payload,
    create_appointment_payload,
    create_branch_payload,
    create_call_record_payload,
    create_campaign_payload,
    create_membership_plan_payload,
    create_pricebook_task_payload,
    hire_technician_payload,
    payment_payload,
    schedule_visit_payload,
    sell_membership_payload,
)
from .test_users import (
    TEST_USERS,
    make_dispatcher_headers,
    make_technician_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
MANAGER = TEST_USERS["manager_headers"]
CS = TEST_USERS["customer_service_headers"]
TECHNICIAN = TEST_USERS["technician_headers"]

__all__ = [
    "ADMIN",
    "DISPATCHER",
    "MANAGER",
    "CS",
    "TECHNICIAN",
    "create_branch",
    "hire_technician",
    "create_plan",
    "create_campaign",
    "create_task",
    "create_call_record",
    "book_appointment",
    "add_line",
    "dispatch",
    "dispatch_two_calls",
    "complete_first_call",
    "get_appointment",
    "get_branch",
    "get_technician",
    "get_agreement",
    "list_visits",
    "sell_agreement",
    "record_payment",
    "schedule_visit",
    "make_dispatcher_headers",
    "make_technician_headers",
    "setup_branch_and_technician",
    "setup_branch_with_live_window",
    "setup_branch_appointment_and_task",
    "setup_dispatched_appointment",
    "setup_completed_appointment",
    "setup_two_hvac_jobs_on_one_branch",
    "setup_membership",
    "setup_member_visit_appointment",
]


def _ok(response, what: str) -> dict:
    data = get_success_data(response)
    assert data is not None, f"Setup failed: {what} returned no data"
    return data


def _ok_array(response, what: str) -> list:
    data = get_success_data(response)
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    assert isinstance(data, list), f"Setup failed: {what} did not return an array"
    return data


# =====================================================================
# Primitives
# =====================================================================
def create_branch(**overrides) -> dict:
    return _ok(api_client.create_branch(create_branch_payload(**overrides), ADMIN), "create branch")


def hire_technician(branch_id: str, **overrides) -> dict:
    return _ok(
        api_client.hire_technician(branch_id, hire_technician_payload(**overrides), ADMIN),
        "hire technician",
    )


def create_plan(**overrides) -> dict:
    return _ok(api_client.create_membership_plan(create_membership_plan_payload(**overrides), ADMIN),
               "create membership plan")


def create_campaign(**overrides) -> dict:
    return _ok(api_client.create_campaign(create_campaign_payload(**overrides), ADMIN),
               "create campaign")


def create_task(**overrides) -> dict:
    return _ok(api_client.create_pricebook_task(create_pricebook_task_payload(**overrides), DISPATCHER),
               "create pricebook task")


def create_call_record(campaign_id: str, **overrides) -> dict:
    payload = create_call_record_payload(campaign_id=campaign_id, **overrides)
    return _ok(api_client.create_call_record(payload, CS), "create call record")


def book_appointment(branch_id: str, **overrides) -> dict:
    payload = create_appointment_payload(branch_id=branch_id, **overrides)
    return _ok(api_client.create_appointment(payload, DISPATCHER), "book appointment")


def add_line(appointment_id: str, code: str = "HVAC-TUNE", **overrides) -> dict:
    payload = add_line_payload(pricebook_task_code=code, **overrides)
    return _ok(api_client.add_line(appointment_id, payload, DISPATCHER), "add line")


def dispatch(appointment_id: str) -> dict:
    return _ok(api_client.dispatch_order({"appointment_id": appointment_id}, DISPATCHER),
               "dispatch appointment")


def dispatch_two_calls(appointment_id: str) -> dict:
    """Dispatch if the appointment is still booked, then walk the two-call completion
    flow. Returns the completed row.  Several callers hand in an appointment their own
    fixture already dispatched, so the dispatch hop is conditional rather than blind."""
    row = get_appointment(appointment_id)
    if row["status"] == "SCHEDULED":
        row = dispatch(appointment_id)
    tech_headers = make_technician_headers(row["technician_id"])
    payload = completion_payload()
    api_client.complete_appointment(appointment_id, payload, tech_headers)  # DISPATCHED -> IN_SERVICE
    return _ok(api_client.complete_appointment(appointment_id, payload, tech_headers),
               "complete appointment")


def complete_first_call(appointment_id: str, description: str = C.LONG_COMPLETION_DESCRIPTION) -> dict:
    """Only the first completion call: dispatch_status becomes IN_SERVICE."""
    appointment = get_appointment(appointment_id)
    tech_headers = make_technician_headers(appointment["technician_id"])
    return _ok(
        api_client.complete_appointment(appointment_id, completion_payload(description), tech_headers),
        "move appointment into service",
    )


def get_appointment(appointment_id: str) -> dict:
    return _ok(api_client.get_appointment(appointment_id, DISPATCHER), "read appointment")


def get_branch(branch_id: str) -> dict:
    return _ok(api_client.get_branch(branch_id, DISPATCHER), "read branch")


def get_technician(technician_id: str) -> dict:
    return _ok(api_client.get_technician(technician_id, DISPATCHER), "read technician")


def get_agreement(agreement_id: str) -> dict:
    return _ok(api_client.get_membership_agreement(agreement_id, DISPATCHER), "read agreement")


def list_visits(agreement_id: str, params=None) -> list:
    return _ok_array(api_client.list_visits(agreement_id, DISPATCHER, params=params), "list visits")


def sell_agreement(branch_id: str, plan_id: str, tech_id: str = None, **overrides) -> dict:
    if tech_id is None:
        # Membership sales are the Technician role's operation, and the acting user must
        # be a persisted technician row.
        tech_id = hire_technician(branch_id, name="Seller")["id"]
    payload = sell_membership_payload(
        membership_plan_id=plan_id, branch_id=branch_id, **overrides
    )
    headers = make_technician_headers(tech_id)
    return _ok(api_client.sell_membership(payload, headers), "sell membership")


def record_payment(agreement_id: str, amount_cents: int) -> dict:
    return _ok(api_client.record_payment(agreement_id, payment_payload(amount_cents), DISPATCHER),
               "record membership payment")


def schedule_visit(agreement_id: str, sequence_number: int, scheduled_date: str) -> dict:
    return _ok(
        api_client.schedule_visit(
            agreement_id, schedule_visit_payload(sequence_number, scheduled_date), DISPATCHER
        ),
        f"schedule visit {sequence_number}",
    )


# =====================================================================
# Tier 1 — state progression
# =====================================================================
def setup_branch_and_technician(
    capacity_hours: float = C.DEFAULT_BRANCH_CAPACITY_HOURS,
    tech_capacity_hours: float = 40,
    tech_postal: str = C.POSTAL_CODE_AUSTIN,
    skill: str = C.TECHNICIAN_SKILL_HVAC,
    name: str = "Dana",
):
    """A branch plus one technician holding `skill`. Returns (branch, technician)."""
    branch = create_branch(daily_dispatch_capacity_hours=capacity_hours)
    technician = hire_technician(
        branch["id"],
        name=name,
        postal_code=tech_postal,
        skill_codes=[skill],
        daily_capacity_hours=tech_capacity_hours,
    )
    return branch, technician


def setup_branch_with_live_window(start="2026-09-10T09:00:00Z", end="2026-09-10T11:00:00Z"):
    """A branch already carrying one live appointment. Returns (branch, appointment)."""
    branch = create_branch()
    live = book_appointment(branch["id"], window_start_utc=start, window_end_utc=end)
    return branch, live


# =====================================================================
# Tier 2 — entity hierarchy
# =====================================================================
def setup_branch_appointment_and_task(
    code="HVAC-TUNE",
    price_cents=5000,
    hours=1.0,
    category="HVAC",
    skill=C.TECHNICIAN_SKILL_HVAC,
    tech_skill=C.TECHNICIAN_SKILL_HVAC,
    tech_postal=C.POSTAL_CODE_AUSTIN,
    tech_capacity_hours=40,
    capacity_hours=C.DEFAULT_BRANCH_CAPACITY_HOURS,
    window_start="2026-09-10T09:00:00Z",
    window_end="2026-09-10T11:00:00Z",
    with_line=True,
):
    """Branch + one technician + one published task + one appointment (optionally with a line).

    Returns (branch, technician, task, appointment, line_or_None).
    """
    branch = create_branch(daily_dispatch_capacity_hours=capacity_hours)
    technician = hire_technician(
        branch["id"],
        postal_code=tech_postal,
        skill_codes=[tech_skill],
        daily_capacity_hours=tech_capacity_hours,
    )
    task = create_task(
        code=code,
        category=category,
        required_skill_code=skill,
        estimated_hours=hours,
        flat_rate_cents=price_cents,
    )
    appointment = book_appointment(
        branch["id"], window_start_utc=window_start, window_end_utc=window_end
    )
    line = add_line(appointment["id"], code=code) if with_line else None
    return branch, technician, task, appointment, line


def setup_dispatched_appointment(
    code="HVAC-COMP",
    price_cents=100000,
    hours=3.0,
    category="HVAC",
    tech_postal=C.POSTAL_CODE_AUSTIN,
    tech_capacity_hours=8,
    window_start="2026-09-10T09:00:00Z",
    window_end="2026-09-10T12:00:00Z",
):
    """Branch + technician + published task + appointment dispatched to that technician.

    Returns (branch, technician, task, appointment).
    """
    branch = create_branch()
    technician = hire_technician(
        branch["id"], postal_code=tech_postal, daily_capacity_hours=tech_capacity_hours
    )
    task = create_task(
        code=code, category=category, estimated_hours=hours, flat_rate_cents=price_cents
    )
    appointment = book_appointment(
        branch["id"], window_start_utc=window_start, window_end_utc=window_end
    )
    # A sold line is what makes the appointment's labour base non-zero, so the automatic
    # quote and the approvable ceiling have something to bound.
    add_line(appointment["id"], code=code, status="SOLD")
    dispatched = dispatch(appointment["id"])
    return branch, technician, task, dispatched


def setup_completed_appointment(
    code="HVAC-COIL",
    price_cents=60000,
    hours=1.0,
    window_start="2026-09-10T09:00:00Z",
    window_end="2026-09-10T11:00:00Z",
    tech_capacity_hours=40,
):
    """Branch + technician + task + appointment dispatched and completed.

    Returns (branch, technician, task, completed_appointment).
    """
    branch = create_branch()
    technician = hire_technician(branch["id"], daily_capacity_hours=tech_capacity_hours)
    task = create_task(code=code, estimated_hours=hours, flat_rate_cents=price_cents)
    appointment = book_appointment(
        branch["id"], window_start_utc=window_start, window_end_utc=window_end
    )
    add_line(appointment["id"], code=code, status="SOLD")
    completed = dispatch_two_calls(appointment["id"])
    return branch, technician, task, completed


# =====================================================================
# Tier 3 — full lifecycle shortcuts
# =====================================================================
def setup_override_pending(
    price_cents=100000, requested_price_cents=105000, hours=1.0, code="HVAC-COIL"
):
    """Dispatched appointment carrying one pending override request.

    Returns (branch, technician, task, appointment, override_request).
    """
    branch, technician, task, appointment = setup_dispatched_appointment(
        code=code, price_cents=price_cents, hours=hours, window_end="2026-09-10T11:00:00Z"
    )
    request = _ok(
        api_client.file_override_request(
            appointment["id"],
            {"requested_price_cents": requested_price_cents},
            make_technician_headers(appointment["technician_id"]),
        ),
        "file override request",
    )
    return branch, technician, task, appointment, request


def setup_membership(
    annual_price_cents=C.DEFAULT_PLAN_PRICE_CENTS,
    visit_count=C.DEFAULT_PLAN_VISIT_COUNT,
    interval_days=C.DEFAULT_PLAN_INTERVAL_DAYS,
    term_months=C.DEFAULT_TERM_MONTHS,
    visit_dates=None,
    activate=True,
    down_payment_cents=None,
    tech_id=None,
    homeowner="Ada",
):
    """Branch + published plan + agreement (optionally activated) + its visits.

    Returns (branch, plan, agreement, visits).
    """
    branch = create_branch()
    plan = create_plan(
        annual_price_cents=annual_price_cents,
        included_service_visit_count=visit_count,
        maintenance_visit_interval_days=interval_days,
    )
    agreement = sell_agreement(
        branch["id"], plan["id"], tech_id=tech_id, homeowner_name=homeowner, term_months=term_months
    )
    if activate:
        amount = down_payment_cents
        if amount is None:
            amount = -(-annual_price_cents * 30 // 100)  # ceil(0.30 * price)
        record_payment(agreement["id"], amount)
    visits = []
    for index, date in enumerate(visit_dates or [], start=1):
        visits.append(schedule_visit(agreement["id"], index, date))
    return branch, plan, get_agreement(agreement["id"]), visits


def setup_member_visit_appointment(visit_index=1, code="HVAC-TUNE", price_cents=5000, hours=1.0,
                                  do_dispatch=True):
    """Activated agreement whose visit `visit_index` is fulfilled by its own appointment.

    Returns (branch, technician, plan, agreement, visit, appointment, task).
    """
    branch = create_branch()
    # The dispatch happens against a 2026-10-01 window, so the hire must declare a
    # shift segment that genuinely overlaps it (PRD §3.5's strict shift clause).
    technician = hire_technician(
        branch["id"],
        daily_capacity_hours=40,
        shift_segments=[{"start_utc": "2026-09-10T08:00:00Z", "end_utc": "2026-10-20T18:00:00Z"}],
    )
    task = create_task(code=code, estimated_hours=hours, flat_rate_cents=price_cents)
    plan = create_plan()
    agreement = sell_agreement(branch["id"], plan["id"], tech_id=technician["id"])
    record_payment(agreement["id"], 30000)
    # The plan owes four visits (its `included_service_visit_count` * `term_months` /
    # 12), and PRD §3.8 recognises revenue against the visits the plan owes, so the
    # whole obligation is scheduled; the rest expose the denominator.
    visit = schedule_visit(agreement["id"], 1, "2026-10-01T00:00:00Z")
    for seq, date in ((2, "2026-11-01T00:00:00Z"), (3, "2026-12-01T00:00:00Z"),
                      (4, "2027-01-01T00:00:00Z")):
        schedule_visit(agreement["id"], seq, date)
    appointment = book_appointment(
        branch["id"],
        window_start_utc="2026-10-01T09:00:00Z",
        window_end_utc="2026-10-01T11:00:00Z",
        membership_agreement_id=agreement["id"],
        membership_visit_sequence_number=1,
    )
    add_line(appointment["id"], code=code, status="SOLD")
    if do_dispatch:
        appointment = dispatch(appointment["id"])
    return branch, technician, plan, get_agreement(agreement["id"]), visit, appointment, task


def setup_two_hvac_jobs_on_one_branch(hours=4.0, code="HVAC-COIL", price_cents=60000):
    """Branch with capacity 8 + one technician + one 4.0-hour task + two appointments
    on distinct windows. The first is dispatched; the second is left booked.

    Returns (branch, technician, task, first_dispatched, second_booked).
    """
    branch = create_branch(daily_dispatch_capacity_hours=8)
    technician = hire_technician(branch["id"], daily_capacity_hours=8)
    task = create_task(code=code, estimated_hours=hours, flat_rate_cents=price_cents)
    first = book_appointment(
        branch["id"], window_start_utc="2026-09-11T09:00:00Z", window_end_utc="2026-09-11T11:00:00Z"
    )
    add_line(first["id"], code=code, status="SOLD")
    first = dispatch(first["id"])
    second = book_appointment(
        branch["id"], window_start_utc="2026-09-12T09:00:00Z", window_end_utc="2026-09-12T11:00:00Z"
    )
    add_line(second["id"], code=code, status="SOLD")
    return branch, technician, task, first, second