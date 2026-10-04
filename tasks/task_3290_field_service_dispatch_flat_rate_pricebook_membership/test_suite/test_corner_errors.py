"""Breadth tests for the error catalogue: the published-revision guard and the
stale-version conflict on an override decision.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import TEST_USERS, api_client, fixtures as F

DISPATCHER = TEST_USERS["dispatcher_headers"]
MANAGER = TEST_USERS["manager_headers"]


def test_a_line_on_a_draft_only_code_is_refused(api):
    """PRD §3.2: "The candidate pool is every `PricebookTask` row whose `code` equals the
    requested code and whose `status` is `PUBLISHED`; rows that are `DRAFT` or `RETIRED`
    never enter the pool, however recent they are."
    PRD §3.2: "When the pool is empty — the code has never been published, or every row
    carrying it has been retired — the request is refused with
    `ERR_PRICEBOOK_REVISION_NOT_PUBLISHED` (HTTP 422)."

    Design: Corner/errors/revision_not_published_on_line_add
    """
    branch = F.create_branch()
    F.create_task(
        code="HVAC-DRAFT", display_name="Draft Tune", estimated_hours=1.0,
        flat_rate_cents=5000, status="DRAFT",
    )
    appointment = F.book_appointment(branch["id"])

    validate_error(
        api_client.add_line(
            appointment["id"], {"pricebook_task_code": "HVAC-DRAFT"}, DISPATCHER
        ),
        "ERR_PRICEBOOK_REVISION_NOT_PUBLISHED",
    )
    lines = validate_success(api_client.list_lines(appointment["id"], DISPATCHER))
    if isinstance(lines, dict) and "items" in lines:
        lines = lines["items"]
    assert lines == [], "the refused addition must leave the line collection empty"

    # Publishing the same code makes the identical addition succeed.
    F.create_task(
        code="HVAC-DRAFT", display_name="Draft Tune", estimated_hours=1.0,
        flat_rate_cents=5000, status="PUBLISHED",
    )
    accepted = validate_success(
        api_client.add_line(
            appointment["id"], {"pricebook_task_code": "HVAC-DRAFT"}, DISPATCHER
        ),
        expected_status=201,
    )
    assert accepted["flat_rate_cents"] == 5000


def test_a_decision_on_a_stale_appointment_version_is_refused(api):
    """PRD §2.7: "If the supplied value differs from the appointment's current `version` —
    because a reprice or a line sale has since recomputed the appointment's
    `labor_base_cents` and its approvable ceiling — the decision is rejected with
    `ERR_STALE_VERSION` (HTTP 412)".
    PRD §2.7: "A client that has not observed the latest version of the parent is refused
    regardless of when it sends its request."

    Design: Corner/errors/stale_appointment_version_on_override_decision
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
    # Filing the request advanced the appointment's version (it moved the pricing
    # dimension), so the manager's snapshot is read after the filing.
    stale_version = F.get_appointment(appointment["id"])["version"]
    approved = validate_success(
        api_client.decide_override(
            request["id"],
            {"decision": "APPROVE", "expected_appointment_version": stale_version},
            MANAGER,
        )
    )
    assert approved["status"] == "APPROVED"

    # The approval advanced the appointment's version, so the snapshot is now stale.
    validate_error(
        api_client.decide_override(
            request["id"],
            {"decision": "REJECT", "expected_appointment_version": stale_version},
            MANAGER,
        ),
        "ERR_STALE_VERSION",
    )
    still = validate_success(api_client.get_appointment(appointment["id"], MANAGER))
    assert still["version"] == stale_version + 1, (
        f"the appointment's version advanced by exactly one, got {still['version']}"
    )