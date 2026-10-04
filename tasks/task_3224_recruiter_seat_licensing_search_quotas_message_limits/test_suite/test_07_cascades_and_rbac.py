"""Cross-entity cascades, project lifecycle, and role-based access control."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId,
    contract_admin_headers, seat_admin_headers, auditor_headers,
    ats_service_headers, recruiter_headers, make_recruiter_user_headers,
    create_and_activate_contract, create_recruiter, list_seats, get_seat,
    assign_seat, assign_first_seat, setup_assigned_seat, setup_messaging,
    create_candidate, send_message, get_message, current_contract_version,
    propose_and_approve, propose_event, suspend_contract_via_event,
    create_open_project, create_posting, create_job_posting_payload,
    create_contract_payload,
)


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/contract_suspend_cascade_seat_then_message
# ---------------------------------------------------------------------------

def test_contract_suspend_cascades_seat_then_message():
    """PRD section 2.8: "When a contract is suspended, every seat in
    `ASSIGNED` status under that contract moves to `SUSPENDED`, and every
    message on those seats whose `response_status` is `AWAITING` is moved to
    `EXPIRED` — a three-level cascade from contract through seat to message."

    Design: Difficulty/transitive_cascade/contract_suspend_cascade_seat_then_message
    """
    ctx = setup_messaging(contract_number="C-CAS-1")
    cid = ctx["contract"]["id"]
    message = send_message(ctx["seat"]["id"], ctx["recruiter"]["id"],
                           ctx["candidate"]["id"], ctx["project"]["id"], body="hi")

    suspend_contract_via_event(cid)

    seat_after = get_seat(ctx["seat"]["id"])
    assert seat_after["seat_status"] == "SUSPENDED"
    message_after = get_message(message["id"])
    assert message_after["response_status"] == "EXPIRED"


def test_contract_resume_restores_assigned_seats():
    """PRD section 3.1: "Resume moves the contract from `SUSPENDED` back to
    `ACTIVE`, returns each `SUSPENDED` seat to its pre-suspension `ASSIGNED`
    posture, and bumps `version`. Resume requires no precondition beyond the
    contract being `SUSPENDED`."

    Design: Difficulty/transitive_cascade/contract_suspend_cascade_seat_then_message
    """
    ctx = setup_messaging(contract_number="C-CAS-1B")
    cid = ctx["contract"]["id"]
    message = send_message(ctx["seat"]["id"], ctx["recruiter"]["id"],
                           ctx["candidate"]["id"], ctx["project"]["id"], body="hi")

    suspend_contract_via_event(cid)
    assert get_seat(ctx["seat"]["id"])["seat_status"] == "SUSPENDED"

    resp = api_client.resume_contract(cid, contract_admin_headers())
    assert validate_success(resp)["contract_status"] == "ACTIVE"
    assert get_seat(ctx["seat"]["id"])["seat_status"] == "ASSIGNED"


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/recruiter_deactivate_cascade_seat_release
# ---------------------------------------------------------------------------

def test_recruiter_deactivate_cascades_seat_release():
    """PRD section 3.2: "Deactivating a recruiter sets `recruiter_status` to
    `DEACTIVATED` (the row remains). If the recruiter holds a seat, that seat
    is unassigned in the same operation: the seat moves to `UNASSIGNED`, the
    recruiter's `active_seat_id` is cleared, and the contract's
    `seats_assigned` decrements by 1."

    Design: Difficulty/transitive_cascade/recruiter_deactivate_cascade_seat_release
    """
    ctx = setup_assigned_seat(contract_number="C-CAS-2")
    cid = ctx["contract"]["id"]
    recruiter, seat = ctx["recruiter"], ctx["seat"]

    resp = api_client.deactivate_recruiter(recruiter["id"], contract_admin_headers())
    assert validate_success(resp)["recruiter_status"] == "DEACTIVATED"

    seat_after = get_seat(seat["id"])
    assert seat_after["seat_status"] == "UNASSIGNED"
    assert seat_after["assigned_recruiter_id"] is None

    recruiter_after = validate_success(
        api_client.get_recruiter(recruiter["id"], auditor_headers())
    )
    assert recruiter_after["active_seat_id"] is None


def test_recruiter_deactivate_decrements_contract_seats_assigned():
    """PRD section 3.2: "Deactivating a recruiter sets `recruiter_status` to
    `DEACTIVATED` (the row remains). If the recruiter holds a seat, that seat
    is unassigned in the same operation: the seat moves to `UNASSIGNED`, the
    recruiter's `active_seat_id` is cleared, and the contract's
    `seats_assigned` decrements by 1."

    Design: Difficulty/transitive_cascade/recruiter_deactivate_cascade_seat_release
    """
    ctx = setup_assigned_seat(contract_number="C-CAS-2B")
    cid = ctx["contract"]["id"]
    before = get_success_data(api_client.get_contract(cid, contract_admin_headers()))
    assert before["seats_assigned"] == 1

    get_success_data(api_client.deactivate_recruiter(ctx["recruiter"]["id"],
                                                     contract_admin_headers()))
    after = get_success_data(api_client.get_contract(cid, contract_admin_headers()))
    assert after["seats_assigned"] == 0


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/project_open_hold_open_cycle
# ---------------------------------------------------------------------------

def test_project_open_hold_open_cycle():
    """PRD section 3.5: "The project's `project_status` begins at `DRAFT` and
    may move `DRAFT` → `OPEN`, `OPEN` → `ON_HOLD`, `ON_HOLD` → `OPEN`,
    `OPEN` → `CLOSED`, or `ON_HOLD` → `CLOSED`."

    Design: Difficulty/non_linear_state_machine/project_open_hold_open_cycle
    """
    ctx = setup_assigned_seat(contract_number="C-PRJ-1")
    cid = ctx["contract"]["id"]
    resp = api_client.create_project(
        cid, {"name": "CycP", "owner_seat_id": ctx["seat"]["id"]}, seat_admin_headers(),
    )
    project = validate_success(resp, expected_status=201)
    assert project["project_status"] == "DRAFT"

    statuses = []
    statuses.append(validate_success(
        api_client.open_project(project["id"], seat_admin_headers()))["project_status"])
    statuses.append(validate_success(
        api_client.hold_project(project["id"], seat_admin_headers()))["project_status"])
    statuses.append(validate_success(
        api_client.open_project(project["id"], seat_admin_headers()))["project_status"])
    statuses.append(validate_success(
        api_client.hold_project(project["id"], seat_admin_headers()))["project_status"])
    assert statuses == ["OPEN", "ON_HOLD", "OPEN", "ON_HOLD"]


def test_project_close_from_open_is_terminal():
    """PRD section 3.5: "The project's `project_status` begins at `DRAFT` and
    may move `DRAFT` → `OPEN`, `OPEN` → `ON_HOLD`, `ON_HOLD` → `OPEN`,
    `OPEN` → `CLOSED`, or `ON_HOLD` → `CLOSED`."

    Design: Difficulty/non_linear_state_machine/project_open_hold_open_cycle
    """
    ctx = setup_assigned_seat(contract_number="C-PRJ-1B")
    project = create_open_project(ctx["contract"]["id"], ctx["seat"]["id"])
    closed = validate_success(api_client.close_project(project["id"], seat_admin_headers()))
    assert closed["project_status"] == "CLOSED"

    resp = api_client.open_project(project["id"], seat_admin_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/project_open_requires_owner_seat_assigned
# ---------------------------------------------------------------------------

def test_project_open_requires_owner_seat_assigned():
    """PRD section 3.5: "The DRAFT → OPEN transition additionally requires
    the parent contract to be `ACTIVE` and the `owner_seat_id` to reference
    an `ASSIGNED` seat on the same contract."

    Design: Difficulty/cross_entity_state_dependency/project_open_requires_owner_seat_assigned
    """
    ctx = setup_assigned_seat(contract_number="C-XD-1")
    cid = ctx["contract"]["id"]
    resp = api_client.create_project(
        cid, {"name": "XDP", "owner_seat_id": ctx["seat"]["id"]}, seat_admin_headers(),
    )
    project = validate_success(resp, expected_status=201)

    get_success_data(api_client.unassign_seat(cid, ctx["seat"]["id"], seat_admin_headers()))
    assert get_seat(ctx["seat"]["id"])["seat_status"] == "UNASSIGNED"

    resp = api_client.open_project(project["id"], seat_admin_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_project_open_with_assigned_owner_seat_succeeds():
    """PRD section 3.5: "The DRAFT → OPEN transition additionally requires
    the parent contract to be `ACTIVE` and the `owner_seat_id` to reference
    an `ASSIGNED` seat on the same contract."

    Design: Difficulty/cross_entity_state_dependency/project_open_requires_owner_seat_assigned
    """
    ctx = setup_assigned_seat(contract_number="C-XD-1B")
    resp = api_client.create_project(
        ctx["contract"]["id"],
        {"name": "XDP2", "owner_seat_id": ctx["seat"]["id"]},
        seat_admin_headers(),
    )
    project = validate_success(resp, expected_status=201)
    opened = validate_success(api_client.open_project(project["id"], seat_admin_headers()))
    assert opened["project_status"] == "OPEN"


# ---------------------------------------------------------------------------
# Corner/rbac/auditor_cannot_create_contract_forbidden
# ---------------------------------------------------------------------------

def test_auditor_cannot_create_contract_forbidden():
    """PRD section 2.1: "A request whose role is not authorised for the
    target endpoint (per §4) is rejected with `ERR_ROLE_FORBIDDEN`."
    PRD section 4: POST /contracts is authorised for ContractAdmin only.

    Design: Corner/rbac/auditor_cannot_create_contract_forbidden
    """
    resp = api_client.create_contract(
        create_contract_payload(contract_number="C-RBAC-1", product_tier="RECRUITER_PRO",
                                seat_cap=3),
        auditor_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN)


def test_auditor_cannot_activate_contract_forbidden():
    """PRD section 2.1: "A request whose role is not authorised for the
    target endpoint (per §4) is rejected with `ERR_ROLE_FORBIDDEN`."
    PRD section 4: POST /contracts/{contract_id}/activate is authorised for
    ContractAdmin only.

    Design: Corner/rbac/auditor_cannot_create_contract_forbidden
    """
    from test_helpers import create_contract
    contract = create_contract(contract_number="C-RBAC-1B")
    resp = api_client.activate_contract(
        contract["id"], {"seats_purchased_initial": 1}, auditor_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN)


# ---------------------------------------------------------------------------
# Corner/rbac/seat_admin_cannot_approve_renewal_forbidden
# ---------------------------------------------------------------------------

def test_seat_admin_cannot_approve_renewal_forbidden():
    """PRD section 2.1: "A request whose role is not authorised for the
    target endpoint (per §4) is rejected with `ERR_ROLE_FORBIDDEN`."
    PRD section 4: POST /renewal-events/{renewal_event_id}/approve is
    authorised for Auditor only.

    Design: Corner/rbac/seat_admin_cannot_approve_renewal_forbidden
    """
    contract = create_and_activate_contract(seats=1, contract_number="C-RBAC-2")
    cid = contract["id"]
    version = current_contract_version(cid)
    event = validate_success(
        api_client.create_renewal_event(
            cid, {"event_kind": "RENEWAL", "expected_contract_version": version},
            auditor_headers(),
        ),
        expected_status=201,
    )
    resp = api_client.approve_renewal_event(event["id"], seat_admin_headers())
    validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN)


def test_seat_admin_cannot_apply_renewal_forbidden():
    """PRD section 2.1: "A request whose role is not authorised for the
    target endpoint (per §4) is rejected with `ERR_ROLE_FORBIDDEN`."
    PRD section 4: POST /renewal-events/{renewal_event_id}/apply is
    authorised for Auditor only.

    Design: Corner/rbac/seat_admin_cannot_approve_renewal_forbidden
    """
    contract = create_and_activate_contract(seats=1, contract_number="C-RBAC-2B")
    cid = contract["id"]
    version = current_contract_version(cid)
    event = validate_success(
        api_client.create_renewal_event(
            cid, {"event_kind": "RENEWAL", "expected_contract_version": version},
            auditor_headers(),
        ),
        expected_status=201,
    )
    get_success_data(api_client.approve_renewal_event(event["id"], auditor_headers()))
    resp = api_client.apply_renewal_event(event["id"], seat_admin_headers())
    validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN)


# ---------------------------------------------------------------------------
# Corner/rbac/ats_service_cannot_record_spend_forbidden
# ---------------------------------------------------------------------------

def test_ats_service_cannot_record_spend_forbidden():
    """PRD section 2.1: "A request whose role is not authorised for the
    target endpoint (per §4) is rejected with `ERR_ROLE_FORBIDDEN`."
    PRD section 4: POST
    /contracts/{contract_id}/job-postings/{job_posting_id}/record-spend is
    authorised for SeatAdmin only.

    Design: Corner/rbac/ats_service_cannot_record_spend_forbidden
    """
    ctx = setup_assigned_seat(contract_number="C-RBAC-3")
    cid, seat_id = ctx["contract"]["id"], ctx["seat"]["id"]
    posting = create_posting(cid, seat_id, title="RBACJob", budget_cents=5000,
                             daily_cap_cents=1000, end_at="2026-09-05T00:00:00Z")
    resp = api_client.record_spend(cid, posting["id"], {"amount_cents": 100},
                                   ats_service_headers())
    validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN)


def test_ats_service_cannot_pause_posting_forbidden():
    """PRD section 2.1: "A request whose role is not authorised for the
    target endpoint (per §4) is rejected with `ERR_ROLE_FORBIDDEN`."
    PRD section 4: POST
    /contracts/{contract_id}/job-postings/{job_posting_id}/pause is
    authorised for SeatAdmin only.

    Design: Corner/rbac/ats_service_cannot_record_spend_forbidden
    """
    ctx = setup_assigned_seat(contract_number="C-RBAC-3B")
    cid, seat_id = ctx["contract"]["id"], ctx["seat"]["id"]
    posting = create_posting(cid, seat_id, title="RBACJobB", budget_cents=5000,
                             daily_cap_cents=1000, end_at="2026-09-05T00:00:00Z")
    resp = api_client.pause_job_posting(cid, posting["id"], ats_service_headers())
    validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN)


# ---------------------------------------------------------------------------
# Corner/rbac/recruiter_user_identity_ownership_enforced
# ---------------------------------------------------------------------------

def test_recruiter_user_identity_ownership_enforced_on_send():
    """PRD section 3.5: "When the caller is a `RecruiterUser`, the caller's
    `X-User-ID` must equal the sending seat's `assigned_recruiter_id`;
    otherwise the request is rejected with `ERR_ROLE_FORBIDDEN`."

    Design: Corner/rbac/recruiter_user_identity_ownership_enforced
    """
    ctx = setup_messaging(seats=2, contract_number="C-RBAC-4")
    cid = ctx["contract"]["id"]
    r2 = create_recruiter(cid, email="rbac4b@x.com", full_name="RB 4b")

    resp = api_client.send_message(
        ctx["seat"]["id"],
        {"candidate_id": ctx["candidate"]["id"], "project_id": ctx["project"]["id"],
         "body": "b"},
        make_recruiter_user_headers(r2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN)


def test_recruiter_user_owner_send_accepted():
    """PRD section 3.5: "When the caller is a `RecruiterUser`, the caller's
    `X-User-ID` must equal the sending seat's `assigned_recruiter_id`;
    otherwise the request is rejected with `ERR_ROLE_FORBIDDEN`."

    Design: Corner/rbac/recruiter_user_identity_ownership_enforced
    """
    ctx = setup_messaging(contract_number="C-RBAC-4B")
    resp = api_client.send_message(
        ctx["seat"]["id"],
        {"candidate_id": ctx["candidate"]["id"], "project_id": ctx["project"]["id"],
         "body": "b"},
        make_recruiter_user_headers(ctx["recruiter"]["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["delivery_status"] == "SENT"
