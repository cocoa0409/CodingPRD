"""Breadth tests for the role model: exclusive operations and shared reads.
"""
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import TEST_USERS, api_client, fixtures as F

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
TECHNICIAN = TEST_USERS["technician_headers"]
MANAGER = TEST_USERS["manager_headers"]
CS = TEST_USERS["customer_service_headers"]


def test_a_technician_cannot_decide_an_override_request(api):
    """PRD §2.1: "override decisions, agreement cancellation, and coaching belong to
    `Manager`".
    PRD §3.14: "the roles column lists exactly the roles permitted on that route; a role not
    listed is refused with `ERR_FORBIDDEN`."

    Design: Corner/rbac/technician_cannot_decide_an_override_request
    """
    branch, technician, task, appointment = F.setup_dispatched_appointment(
        code="HVAC-COIL", price_cents=100000, hours=1.0,
        window_start="2026-09-10T09:00:00Z", window_end="2026-09-10T11:00:00Z",
    )
    tech_headers = F.make_technician_headers(appointment["technician_id"])
    request = validate_success(
        api_client.file_override_request(
            appointment["id"], {"requested_price_cents": 105000}, tech_headers
        ),
        expected_status=201,
    )
    current = F.get_appointment(appointment["id"])
    payload = {"decision": "APPROVE", "expected_appointment_version": current["version"]}

    validate_error(
        api_client.decide_override(request["id"], payload, tech_headers), "ERR_FORBIDDEN"
    )
    pending = validate_success(api_client.list_override_requests(appointment["id"], MANAGER))
    if isinstance(pending, dict) and "items" in pending:
        pending = pending["items"]
    assert pending[0]["status"] == "PENDING"
    assert pending[0]["decided_by_user_id"] is None

    validate_success(api_client.decide_override(request["id"], payload, MANAGER))


def test_a_manager_cannot_hire_a_technician(api):
    """PRD §2.1: "branch, plan, campaign, technician-hire, and clock operations belong to
    `PlatformAdmin`."
    PRD §4: "The roles column lists exactly the roles permitted on that route; a role not
    listed is refused with `ERR_FORBIDDEN`."

    Design: Corner/rbac/manager_cannot_hire_a_technician
    """
    branch = F.create_branch()
    payload = {
        "name": "Dana",
        "postal_code": "78701",
        "skill_codes": ["HVAC"],
        "shift_segments": [{"start_utc": "2026-09-10T08:00:00Z", "end_utc": "2026-09-10T18:00:00Z"}],
        "daily_capacity_hours": 8,
    }

    validate_error(api_client.hire_technician(branch["id"], payload, MANAGER), "ERR_FORBIDDEN")

    rows, meta = validate_paginated(api_client.list_branch_technicians(branch["id"], DISPATCHER))
    assert meta["total_count"] == 0, "the refused hire must not have created a row"

    validate_success(api_client.hire_technician(branch["id"], payload, ADMIN), expected_status=201)
    rows, meta = validate_paginated(api_client.list_branch_technicians(branch["id"], DISPATCHER))
    assert meta["total_count"] == 1


def test_the_customer_service_role_is_limited_to_call_intake(api):
    """PRD §2.1: "intake call registration belongs to `CustomerService`".
    PRD §3.13: "A `CustomerService` representative registers a recorded call against the
    campaign it belongs to".
    PRD §2.1: "Read endpoints are shared more liberally and the exact permitted set for each
    route is given in §4."

    Design: Corner/rbac/customer_service_role_is_limited_to_call_intake
    """
    branch = F.create_branch()
    campaign = F.create_campaign(spend_cents=50000)

    booking = {
        "branch_id": branch["id"],
        "customer_name": "Ada",
        "postal_code": "78701",
        "window_start_utc": "2026-09-10T09:00:00Z",
        "window_end_utc": "2026-09-10T11:00:00Z",
        "campaign_id": campaign["id"],
    }
    validate_error(api_client.create_appointment(booking, CS), "ERR_FORBIDDEN")

    registered = validate_success(
        api_client.create_call_record(
            {
                "campaign_id": campaign["id"],
                "cs_user_id": "cs-77",
                "duration_seconds": 420,
                "recording_uri": "s3://calls/1188.wav",
            },
            CS,
        ),
        expected_status=201,
    )
    assert registered["coaching_status"] == "UNREVIEWED"

    validate_success(api_client.get_campaign(campaign["id"], CS))


def test_a_dispatcher_cannot_complete_a_job(api):
    """PRD §2.1: "appointment completion, override filing, and membership sales belong to
    `Technician`".
    PRD §3.7: "A `Technician` completes an appointment by supplying a `completion_description`."

    Design: Corner/rbac/dispatcher_cannot_complete_a_job
    """
    branch, technician, task, appointment = F.setup_dispatched_appointment(
        code="HVAC-COIL", price_cents=100000, hours=1.0,
        window_start="2026-09-10T09:00:00Z", window_end="2026-09-10T11:00:00Z",
    )
    payload = {
        "completion_description": (
            "Cleaned the coil, flushed the drain and verified the temperature split across the coil."
        )
    }

    validate_error(
        api_client.complete_appointment(appointment["id"], payload, DISPATCHER), "ERR_FORBIDDEN"
    )
    refreshed = F.get_appointment(appointment["id"])
    assert refreshed["dispatch_status"] == "DISPATCHED", (
        "the IN_SERVICE hop must not have fired"
    )

    tech_headers = F.make_technician_headers(appointment["technician_id"])
    first = validate_success(
        api_client.complete_appointment(appointment["id"], payload, tech_headers)
    )
    assert first["dispatch_status"] == "IN_SERVICE"
    second = validate_success(
        api_client.complete_appointment(appointment["id"], payload, tech_headers)
    )
    assert second["status"] == "COMPLETED"