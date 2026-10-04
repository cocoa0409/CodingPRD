"""Breadth tests for the endpoint behaviours: computed reads and action endpoints.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import TEST_USERS, api_client, fixtures as F

DISPATCHER = TEST_USERS["dispatcher_headers"]
MANAGER = TEST_USERS["manager_headers"]


def _two_completed_100000_jobs():
    branch = F.create_branch()
    technician = F.hire_technician(
        branch["id"],
        shift_segments=[{"start_utc": "2026-09-10T08:00:00Z", "end_utc": "2026-09-30T18:00:00Z"}],
        daily_capacity_hours=40,
    )
    F.create_task(code="HVAC-COIL", estimated_hours=1.0, flat_rate_cents=100000)
    for day in (10, 11):
        appointment = F.book_appointment(
            branch["id"],
            window_start_utc=f"2026-09-{day}T09:00:00Z",
            window_end_utc=f"2026-09-{day}T11:00:00Z",
        )
        F.add_line(appointment["id"], code="HVAC-COIL", status="SOLD")
        F.dispatch_two_calls(appointment["id"])
    return branch, technician


def test_incentive_statement_agrees_with_the_revenue_ledger(api):
    """PRD §3.11: "Its first step walks the technician's `COMPLETED` appointments and, for
    each, takes that appointment's `sold_price_cents` as a base".
    PRD §3.10: "the technician's `technician_revenue_ledger_cents` is read as the amount of
    the latest entry, which is the running total after all entries have been applied."

    Design: Corner/endpoints/incentive_statement_computed_read_agrees_with_ledger
    """
    branch, technician = _two_completed_100000_jobs()

    statement = validate_success(
        api.get_incentive_statement(
            technician["id"], {"period_year": 2026, "period_month": 9}, MANAGER
        )
    )
    assert statement["gross_component_cents"] == 12000, (
        "two 100000-cent jobs each contribute a six-percent component of 6000, "
        f"got {statement['gross_component_cents']}"
    )
    assert statement["clamped_component_cents"] == 12000
    assert statement["incentive_cents"] == 240, (
        # PRD §3.11: "a figure of at most 25000 cents yields a rate of two
        # hundredths".  12000 sits in that band, so 12000 * 0.02 = 240.
        f"12000 cents at the two-hundredths rate is 240, got {statement['incentive_cents']}"
    )

    technician_row = F.get_technician(technician["id"])
    assert technician_row["technician_revenue_ledger_cents"] == 200000, (
        "the independent ledger accruals agree over the same completed set, "
        f"got {technician_row['technician_revenue_ledger_cents']}"
    )


def test_approving_an_override_publishes_both_rows(api):
    """PRD §3.6: "Otherwise the request's `status` becomes `APPROVED` and its
    `decided_by_user_id` becomes the acting `X-User-ID`; the appointment's
    `quoted_price_cents` is replaced by the request's `requested_price_cents`; the
    appointment's `pricing_status` becomes `QUOTE_APPROVED`".

    Design: Corner/endpoints/override_decision_publishes_request_state
    """
    branch, technician, task, appointment = F.setup_dispatched_appointment(
        code="HVAC-COIL", price_cents=100000, hours=1.0,
        window_start="2026-09-10T09:00:00Z", window_end="2026-09-10T11:00:00Z",
    )
    tech_headers = F.make_technician_headers(appointment["technician_id"])
    request = validate_success(
        api_client.file_override_request(
            appointment["id"], {"requested_price_cents": 110000}, tech_headers
        ),
        expected_status=201,
    )
    current = F.get_appointment(appointment["id"])

    decided = validate_success(
        api_client.decide_override(
            request["id"],
            {"decision": "APPROVE", "expected_appointment_version": current["version"]},
            MANAGER,
        )
    )
    assert decided["status"] == "APPROVED"
    assert decided["decided_by_user_id"] == TEST_USERS["manager_headers"]["X-User-ID"]

    refreshed = F.get_appointment(appointment["id"])
    assert refreshed["quoted_price_cents"] == 110000
    assert refreshed["pricing_status"] == "QUOTE_APPROVED"
    assert refreshed["authorization_required"] is False, (
        "110000 does not exceed 1.20 times 100000"
    )