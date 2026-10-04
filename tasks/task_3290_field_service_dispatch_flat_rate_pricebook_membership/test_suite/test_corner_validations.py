"""Breadth tests for the validation ladder: authentication, authorization,
referential guards and the two fiscal guards."""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import TEST_USERS, api_client, fixtures as F

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
TECHNICIAN = TEST_USERS["technician_headers"]
MANAGER = TEST_USERS["manager_headers"]


def test_a_request_without_a_role_header_is_unauthorized(api):
    """PRD §2.1: "A request is authenticated only when `X-User-Role` names a role declared
    in the RBAC matrix of this document *and* `X-User-ID` is present and non-empty; anything
    else — a missing `X-User-Role`, a missing `X-User-ID`, an empty `X-User-ID`, or a role
    string that this document does not declare — is rejected with `ERR_UNAUTHORIZED`
    (HTTP 401)."

    Design: Corner/validations/missing_role_header_is_unauthorized
    """
    response = api_client._request("GET", "/api/appointments", headers={})
    error = validate_error(response, "ERR_UNAUTHORIZED")
    assert error["error_id"] == "ERR_UNAUTHORIZED"


def test_a_technician_cannot_book_an_appointment(api):
    """PRD §2.1: "Endpoints restricted to a single role are exclusive to that role: catalog
    and pricebook creation, appointment booking, line addition, repricing, dispatching,
    membership payments and visit scheduling, and visit rescheduling belong to
    `Dispatcher`".
    PRD §4: "The roles column lists exactly the roles permitted on that route; a role not
    listed is refused with `ERR_FORBIDDEN`."

    Design: Corner/validations/technician_cannot_book_an_appointment
    """
    branch = F.create_branch(postal_code="78701")
    seller = F.hire_technician(branch["id"], name="Seller")
    payload = {
        "branch_id": branch["id"],
        "customer_name": "Ada",
        "postal_code": "78701",
        "window_start_utc": "2026-09-10T09:00:00Z",
        "window_end_utc": "2026-09-10T11:00:00Z",
    }

    validate_error(
        api_client.create_appointment(payload, F.make_technician_headers(seller["id"])),
        "ERR_FORBIDDEN",
    )
    accepted = validate_success(
        api_client.create_appointment(payload, F.make_dispatcher_headers(seller["id"])),
        expected_status=201,
    )
    assert accepted["status"] == "SCHEDULED"


def test_dispatch_without_a_matching_skill_reports_no_eligible_technician(api):
    """PRD §3.5: "When no candidate at all holds every required skill code of the
    appointment's published task revisions, the dispatch is refused with
    `ERR_NO_ELIGIBLE_TECHNICIAN` (HTTP 422)."
    PRD §3.5: "the skill clause: the technician's `skill_codes` must contain every
    `required_skill_code` demanded by the appointment's lines whose referenced revision is
    `PUBLISHED`."

    Design: Corner/validations/dispatch_skill_gap_reports_no_eligible_technician
    """
    branch = F.create_branch()
    F.hire_technician(
        branch["id"],
        postal_code="78701",
        skill_codes=["PLUMBING"],
        shift_segments=[{"start_utc": "2026-09-10T08:00:00Z", "end_utc": "2026-09-10T18:00:00Z"}],
        daily_capacity_hours=8,
    )
    F.create_task(
        code="HVAC-COMP", category="HVAC", required_skill_code="HVAC",
        estimated_hours=3.0, flat_rate_cents=300000,
    )
    appointment = F.book_appointment(
        branch["id"], window_start_utc="2026-09-10T09:00:00Z", window_end_utc="2026-09-10T12:00:00Z"
    )
    F.add_line(appointment["id"], code="HVAC-COMP")

    validate_error(
        api_client.dispatch_order({"appointment_id": appointment["id"]}, DISPATCHER),
        "ERR_NO_ELIGIBLE_TECHNICIAN",
    )
    refreshed = F.get_appointment(appointment["id"])
    assert refreshed["technician_id"] is None
    assert refreshed["dispatch_status"] == "UNASSIGNED"

    # Hiring a technician who holds the skill makes the same dispatch succeed.
    F.hire_technician(branch["id"], name="Eli", postal_code="78701", skill_codes=["HVAC"])
    dispatched = validate_success(
        api_client.dispatch_order({"appointment_id": appointment["id"]}, DISPATCHER),
        expected_status=201,
    )
    assert dispatched["dispatch_status"] == "DISPATCHED"
    assert dispatched["status"] == "DISPATCHED"


def test_a_payment_beyond_the_annual_price_is_refused(api):
    """PRD §3.8: "Any payment that would push `collected_amount_cents` beyond the
    agreement's `annual_price_cents` is refused with `ERR_OVER_COLLECTION` (HTTP 422); the
    collected total may equal the annual price but never exceed it."

    Design: Corner/validations/over_collection_on_membership_payment
    """
    branch = F.create_branch()
    plan = F.create_plan(annual_price_cents=100000)
    agreement = F.sell_agreement(branch["id"], plan["id"])
    F.record_payment(agreement["id"], 30000)

    validate_error(
        api_client.record_payment(agreement["id"], {"amount_cents": 80000}, DISPATCHER),
        "ERR_OVER_COLLECTION",
    )

    collected = validate_success(
        api_client.record_payment(agreement["id"], {"amount_cents": 70000}, DISPATCHER)
    )
    assert collected["collected_amount_cents"] == 100000, (
        "the collected total may equal the annual price"
    )
    assert collected["status"] == "ACTIVE"


def test_the_override_ceiling_binds_at_decision_time(api):
    """PRD §3.6: "If the request's `requested_price_cents` exceeds its computed
    `max_approved_price_cents`, the approval is refused with `ERR_OVERRIDE_EXCEEDS_LIMIT`
    (HTTP 422)."

    Design: Corner/validations/override_ceiling_on_manager_decision
    """
    branch, technician, task, appointment = F.setup_dispatched_appointment(
        code="HVAC-COIL", price_cents=100000, hours=1.0,
        window_start="2026-09-10T09:00:00Z", window_end="2026-09-10T11:00:00Z",
    )
    tech_headers = F.make_technician_headers(appointment["technician_id"])
    over = validate_success(
        api_client.file_override_request(
            appointment["id"], {"requested_price_cents": 150000}, tech_headers
        ),
        expected_status=201,
    )
    assert over["max_approved_price_cents"] == 137500, (
        "100000 cents times 1.25 times 1.10 truncates to 137500, "
        f"got {over['max_approved_price_cents']}"
    )
    current = F.get_appointment(appointment["id"])

    validate_error(
        api_client.decide_override(
            over["id"],
            {"decision": "APPROVE", "expected_appointment_version": current["version"]},
            MANAGER,
        ),
        "ERR_OVERRIDE_EXCEEDS_LIMIT",
    )
    still_pending = validate_success(api_client.list_override_requests(appointment["id"], MANAGER))
    if isinstance(still_pending, dict) and "items" in still_pending:
        still_pending = still_pending["items"]
    assert still_pending[0]["status"] == "PENDING"
    assert still_pending[0]["decided_by_user_id"] is None


def test_a_short_completion_description_is_refused(api):
    """PRD §3.7: "If the supplied word count is below that requirement the completion is
    refused with `ERR_DESCRIPTION_TOO_SHORT` (HTTP 422)."
    PRD §3.7: "the required word count as the larger of ten words and five percent of the
    appointment's `estimated_hours` expressed in minutes".

    A 4.0-hour job requires twelve words.

    Design: Corner/validations/description_word_floor_on_completion
    """
    branch, technician, task, appointment = F.setup_dispatched_appointment(
        code="HVAC-COIL", price_cents=60000, hours=4.0,
        window_start="2026-09-10T09:00:00Z", window_end="2026-09-10T13:00:00Z",
    )
    F.complete_first_call(appointment["id"])
    tech_headers = F.make_technician_headers(appointment["technician_id"])

    validate_error(
        api_client.complete_appointment(
            appointment["id"], {"completion_description": "Coil cleaned."}, tech_headers
        ),
        "ERR_DESCRIPTION_TOO_SHORT",
    )
    refreshed = F.get_appointment(appointment["id"])
    assert refreshed["status"] == "DISPATCHED", "the refusal must not partially apply"

    accepted = validate_success(
        api_client.complete_appointment(
            appointment["id"],
            {
                "completion_description": (
                    "Replaced the filter, flushed the drain, verified the split and tightened every panel"
                )
            },
            tech_headers,
        )
    )
    assert accepted["status"] == "COMPLETED"


def test_a_repeated_visit_sequence_number_is_refused(api):
    """PRD §3.8: "it must not already be present on the agreement, and a repeat is refused
    with `ERR_DUPLICATE_VISIT_SEQUENCE` (HTTP 409)."

    Design: Corner/validations/binding_duplicate_visit_sequence
    """
    branch = F.create_branch()
    plan = F.create_plan()
    agreement = F.sell_agreement(branch["id"], plan["id"])
    F.record_payment(agreement["id"], 30000)
    F.schedule_visit(agreement["id"], 1, "2026-10-01T00:00:00Z")

    validate_error(
        api_client.schedule_visit(
            agreement["id"], {"sequence_number": 1, "scheduled_date": "2026-11-01T00:00:00Z"}, DISPATCHER
        ),
        "ERR_DUPLICATE_VISIT_SEQUENCE",
    )
    assert len(F.list_visits(agreement["id"])) == 1


def test_a_visit_beyond_the_term_entitlement_is_refused(api):
    """PRD §3.8: "It must not exceed the agreement's total visit entitlement, which is the
    plan's `included_service_visit_count` multiplied by the agreement's `term_months` and
    divided by twelve; a sequence number beyond that is refused with
    `ERR_SUBSCRIPTION_TERM_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/visit_entitlement_ceiling
    """
    branch = F.create_branch()
    plan = F.create_plan(included_service_visit_count=4)
    agreement = F.sell_agreement(branch["id"], plan["id"])
    F.record_payment(agreement["id"], 30000)
    for index, date in enumerate(
        ("2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z", "2027-01-01T00:00:00Z"),
        start=1,
    ):
        F.schedule_visit(agreement["id"], index, date)

    validate_error(
        api_client.schedule_visit(
            agreement["id"], {"sequence_number": 5, "scheduled_date": "2027-02-01T00:00:00Z"}, DISPATCHER
        ),
        "ERR_SUBSCRIPTION_TERM_EXCEEDED",
    )
    assert len(F.list_visits(agreement["id"])) == 4


def test_a_second_override_while_one_is_pending_is_refused(api):
    """PRD §3.6: "filing while another request on the same appointment still has `status` of
    `PENDING` is refused with `ERR_OVERRIDE_ALREADY_PENDING` (HTTP 409)."

    Design: Corner/validations/event_and_state_error_priority_on_override_filing
    """
    branch, technician, task, appointment = F.setup_dispatched_appointment(
        code="HVAC-COIL", price_cents=100000, hours=1.0,
        window_start="2026-09-10T09:00:00Z", window_end="2026-09-10T11:00:00Z",
    )
    tech_headers = F.make_technician_headers(appointment["technician_id"])
    first = validate_success(
        api_client.file_override_request(
            appointment["id"], {"requested_price_cents": 110000}, tech_headers
        ),
        expected_status=201,
    )

    validate_error(
        api_client.file_override_request(
            appointment["id"], {"requested_price_cents": 115000}, tech_headers
        ),
        "ERR_OVERRIDE_ALREADY_PENDING",
    )
    requests = validate_success(api_client.list_override_requests(appointment["id"], MANAGER))
    if isinstance(requests, dict) and "items" in requests:
        requests = requests["items"]
    assert len(requests) == 1
    assert requests[0]["status"] == "PENDING"