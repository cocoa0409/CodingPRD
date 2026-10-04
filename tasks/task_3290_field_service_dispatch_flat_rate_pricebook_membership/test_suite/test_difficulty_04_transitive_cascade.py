"""Depth tests for the transitive cascades.

Two instances: the fiscal chain that runs from an over-ceiling approval refusal
down to a discount-floor refusal, and the completion chain that walks dispatch
release, ledger accrual, visit completion and agreement revenue recognition.
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    fixtures as F,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import completion_payload, decide_payload, override_request_payload

DISPATCHER = TEST_USERS["dispatcher_headers"]
MANAGER = TEST_USERS["manager_headers"]


# =====================================================================
# discount_floor_cascade_through_override_limit
# =====================================================================
def _in_service_appointment_with_over_ceiling_request(requested=500000):
    branch, technician, task, appointment = F.setup_dispatched_appointment(
        code="HVAC-COMP", price_cents=300000, hours=3.0
    )
    tech_headers = F.make_technician_headers(appointment["technician_id"])
    # First completion call only: dispatch_status becomes IN_SERVICE.
    F.complete_first_call(appointment["id"])
    request = validate_success(
        api_client.file_override_request(
            appointment["id"], override_request_payload(requested), tech_headers
        ),
        expected_status=201,
    )
    current = F.get_appointment(appointment["id"])
    return branch, technician, appointment, request, current, tech_headers


def test_approval_above_the_computed_ceiling_is_refused(api):
    """PRD §3.6: "If the request's `requested_price_cents` exceeds its computed
    `max_approved_price_cents`, the approval is refused with
    `ERR_OVERRIDE_EXCEEDS_LIMIT` (HTTP 422)."
    PRD §3.6: "Its `max_approved_price_cents` is the appointment's `labor_base_cents`
    multiplied by one and twenty-five hundredths and then by one and ten hundredths".

    Design: Difficulty/transitive_cascade/discount_floor_cascade_through_override_limit
    """
    branch, technician, appointment, request, current, tech_headers = (
        _in_service_appointment_with_over_ceiling_request()
    )

    assert request["max_approved_price_cents"] == 412500, (
        "300000 cents times 1.25 times 1.10 truncates to 412500, "
        f"got {request['max_approved_price_cents']}"
    )
    response = api_client.decide_override(
        request["id"], decide_payload("APPROVE", current["version"]), MANAGER
    )
    from prd_bench_local_runner.testing import validate_error

    validate_error(response, ApiErrorId.ERR_OVERRIDE_EXCEEDS_LIMIT)

    refreshed = F.get_appointment(appointment["id"])
    assert refreshed["pricing_status"] == "OVERRIDE_PENDING", (
        "no approval was recorded, so the pricing dimension is unchanged, "
        f"got {refreshed['pricing_status']}"
    )
    still_pending = validate_success(
        api_client.list_override_requests(appointment["id"], MANAGER)
    )
    if isinstance(still_pending, dict) and "items" in still_pending:
        still_pending = still_pending["items"]
    assert [r["status"] for r in still_pending] == ["PENDING"]


def test_discount_floor_blocks_completion_of_the_over_quoted_job(api):
    """PRD §3.7: "The effective discount is the denominator minus the numerator, divided
    by the denominator. When that fraction is strictly greater than twenty hundredths —
    a discount of more than twenty percent — the completion is refused with
    `ERR_DISCOUNT_FLOOR_REACHED` (HTTP 422)."
    PRD §3.7: "The check forms a denominator from the sum of `flat_rate_cents` over the
    appointment's lines whose `status` is `SOLD`".
    PRD §3.5: "when the appointment names a `membership_agreement_id` whose agreement's
    `status` is `ACTIVE`, the rate becomes half of that agreement's plan's
    `included_labor_discount_pct`."

    The committed quote falls below the sold labour base only through the membership
    discount — a pending override that was refused leaves the quote untouched, and an
    approval can never exceed one and twenty-five hundredths of the base — so a plan whose
    halved discount exceeds twenty percent is the PRD-realizable way to breach the floor.

    Design: Difficulty/transitive_cascade/discount_floor_cascade_through_override_limit
    """
    from prd_bench_local_runner.testing import validate_error

    branch = F.create_branch()
    technician = F.hire_technician(
        branch["id"],
        shift_segments=[{"start_utc": "2026-09-01T00:00:00Z", "end_utc": "2026-10-20T00:00:00Z"}],
        daily_capacity_hours=40,
    )
    F.create_task(code="HVAC-COMP", estimated_hours=3.0, flat_rate_cents=300000)
    plan = F.create_plan(included_labor_discount_pct=0.60)
    agreement = F.sell_agreement(branch["id"], plan["id"], tech_id=technician["id"])
    F.record_payment(agreement["id"], 30000)
    appointment = F.book_appointment(
        branch["id"],
        window_start_utc="2026-09-10T09:00:00Z",
        window_end_utc="2026-09-10T12:00:00Z",
        membership_agreement_id=agreement["id"],
    )
    F.add_line(appointment["id"], code="HVAC-COMP", status="SOLD")
    dispatched = F.dispatch(appointment["id"])

    # Half of the 0.60 plan discount applies at quote time: 300000 * 0.70 = 210000,
    # which is a 0.30 effective discount against the 300000-cent sold base.
    assert dispatched["quoted_price_cents"] == 210000, (
        "the automatic quote carries half the plan discount, "
        f"got {dispatched['quoted_price_cents']}"
    )
    refreshed = F.get_appointment(appointment["id"])
    assert refreshed["sold_price_cents"] == 300000, (
        "the sold line keeps its sold price, giving the discount check its denominator"
    )

    tech_headers = F.make_technician_headers(dispatched["technician_id"])
    description = (
        "Opened the unit, recovered the refrigerant, replaced the failed compressor and "
        "verified the charge alongside the temperature split before closing the panel"
    )
    response = api_client.complete_appointment(
        appointment["id"], completion_payload(description), tech_headers
    )
    validate_error(response, ApiErrorId.ERR_DISCOUNT_FLOOR_REACHED)


# =====================================================================
# appointment_completion_ledger_cascade
# =====================================================================
def test_completion_cascades_through_ledger_visit_and_agreement_revenue(api):
    """PRD §3.7: "For every line on the appointment whose `status` is `SOLD`, a
    `RevenueLedgerEntry` is appended: its `entry_type` is `ACCRUAL`, its `amount_cents`
    is that line's `sold_price_cents` as a positive addition".
    PRD §3.7: "The `MembershipVisit` on the linked agreement whose `sequence_number`
    equals the appointment's `membership_visit_sequence_number` and whose `status` is
    `SCHEDULED` transitions to `COMPLETED`, taking this appointment's id as its
    `completed_appointment_id`".
    PRD §3.8: "an agreement worth 100000 cents with two of four owed visits completed
    recognises 50000 cents under the base variant".

    Design: Difficulty/transitive_cascade/appointment_completion_ledger_cascade
    """
    branch, technician, plan, agreement, visit, appointment, task = (
        F.setup_member_visit_appointment(code="HVAC-TUNE", price_cents=5000, hours=1.0)
    )
    # The sold line is 5000 cents of labour base; a 12-word description is exactly the
    # floor for a 1.0-hour job (1 * 60 * 0.05 = 3, floored at ten).
    description = (
        "Tuned the system, checked the charge, cleaned the trap and tightened every "
        "visible fastener in the cabinet today"
    )
    F.complete_first_call(appointment["id"], description)
    completed = validate_success(
        api_client.complete_appointment(
            appointment["id"], completion_payload(description),
            F.make_technician_headers(appointment["technician_id"]),
        )
    )

    assert completed["status"] == "COMPLETED"
    assert completed["dispatch_status"] == "RELEASED"

    technician_row = F.get_technician(technician["id"])
    assert technician_row["technician_revenue_ledger_cents"] == 5000, (
        "the sold line's price accrues to the completing technician, "
        f"got {technician_row['technician_revenue_ledger_cents']}"
    )
    assert technician_row["dispatched_hours"] == 0, (
        "the dispatch-day ledger must return to its pre-dispatch position"
    )

    visits = F.list_visits(agreement["id"])
    assert visits[0]["status"] == "COMPLETED", f"got {visits[0]['status']}"
    assert visits[0]["completed_appointment_id"] == appointment["id"]

    refreshed = F.get_agreement(agreement["id"])
    assert refreshed["visits_fulfilled_count"] == 1
    assert refreshed["revenue_recognized_cents"] == 25000, (
        "one completed visit out of four owed on a 100000-cent agreement recognises "
        f"25000, got {refreshed['revenue_recognized_cents']}"
    )


def test_completion_cascade_releases_branch_capacity(api):
    """PRD §2.6: "after a dispatch and its paired completion or cancellation the branch's
    consumed hours and the technician's dispatched hours equal what they were immediately
    before the dispatch."

    Design: Difficulty/transitive_cascade/appointment_completion_ledger_cascade
    """
    branch, technician, task, appointment = F.setup_dispatched_appointment(
        code="HVAC-TUNE", price_cents=5000, hours=1.0,
        window_start="2026-09-10T09:00:00Z", window_end="2026-09-10T11:00:00Z",
    )
    mid_dispatch = F.get_branch(branch["id"])
    assert mid_dispatch["capacity_consumed_hours"] == 1.0

    F.dispatch_two_calls(appointment["id"])

    released = F.get_branch(branch["id"])
    assert released["capacity_consumed_hours"] == 0.0, (
        "completion returns the branch's consumed hours to their pre-dispatch value, "
        f"got {released['capacity_consumed_hours']}"
    )
    assert F.get_technician(technician["id"])["dispatched_hours"] == 0