"""Seat assignment lifecycle: compliance errors, OCC guards, soft delete,
404s, listing, pagination, and immediate consistency."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    contract_admin_headers, seat_admin_headers, auditor_headers,
    recruiter_headers, create_contract, activate_contract,
    create_and_activate_contract, create_recruiter, list_seats, get_seat,
    assign_seat, assign_first_seat, setup_assigned_seat, current_contract_version,
    create_contract_payload,
)


# ---------------------------------------------------------------------------
# Corner/validations/recruiter_already_seated_rejected
# ---------------------------------------------------------------------------

def test_recruiter_already_seated_rejected_second_assign():
    """PRD section 3.2: "the recruiter must not already hold a seat — if the
    recruiter's `active_seat_id` is non-null the request is rejected with
    `ERR_RECRUITER_ALREADY_SEATED`"

    Design: Corner/validations/recruiter_already_seated_rejected
    """
    contract = create_and_activate_contract(seats=2)
    cid = contract["id"]
    recruiter = create_recruiter(cid, email="val1@x.com", full_name="Val One")
    seats = list_seats(cid)
    s1, s2 = seats[0], seats[1]
    assign_seat(cid, s1["id"], recruiter["id"])

    seat2 = get_seat(s2["id"])
    resp = api_client.assign_seat(
        cid, s2["id"],
        {"recruiter_id": recruiter["id"], "expected_seat_version": seat2["version"]},
        seat_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_RECRUITER_ALREADY_SEATED)


def test_recruiter_already_seated_recruiter_keeps_first_seat():
    """PRD section 3.2: "a recruiter holds at most one seat at a time."
    PRD section 3.2: "the recruiter must not already hold a seat — if the
    recruiter's `active_seat_id` is non-null the request is rejected with
    `ERR_RECRUITER_ALREADY_SEATED`"

    Design: Corner/validations/recruiter_already_seated_rejected
    """
    contract = create_and_activate_contract(seats=2)
    cid = contract["id"]
    recruiter = create_recruiter(cid)
    seats = list_seats(cid)
    s1, s2 = seats[0], seats[1]
    assign_seat(cid, s1["id"], recruiter["id"])

    seat2 = get_seat(s2["id"])
    resp = api_client.assign_seat(
        cid, s2["id"],
        {"recruiter_id": recruiter["id"], "expected_seat_version": seat2["version"]},
        seat_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_RECRUITER_ALREADY_SEATED)

    after = get_success_data(api_client.get_recruiter(recruiter["id"], auditor_headers()))
    assert after["active_seat_id"] == s1["id"], (
        "rejected second assign must not disturb the recruiter's existing seat"
    )


# ---------------------------------------------------------------------------
# Corner/state_machines/assign_assigned_seat_rejected
# ---------------------------------------------------------------------------

def test_assign_assigned_seat_rejected_with_fresh_version():
    """PRD section 3.2: "the target seat's `seat_status` must be `UNASSIGNED` —
    a seat in any other state is rejected with `ERR_SEAT_NOT_AVAILABLE`"

    Design: Corner/state_machines/assign_assigned_seat_rejected
    """
    contract = create_and_activate_contract(seats=1)
    cid = contract["id"]
    r1 = create_recruiter(cid, email="sm1a@x.com", full_name="SM 1a")
    r2 = create_recruiter(cid, email="sm1b@x.com", full_name="SM 1b")
    seat = assign_first_seat(cid, r1["id"])

    seat_fresh = get_seat(seat["id"])
    resp = api_client.assign_seat(
        cid, seat["id"],
        {"recruiter_id": r2["id"], "expected_seat_version": seat_fresh["version"]},
        seat_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_SEAT_NOT_AVAILABLE)


def test_assign_assigned_seat_rejected_from_suspended_state():
    """PRD section 3.2: "the target seat's `seat_status` must be `UNASSIGNED` —
    a seat in any other state is rejected with `ERR_SEAT_NOT_AVAILABLE`"

    Design: Corner/state_machines/assign_assigned_seat_rejected
    """
    ctx = setup_assigned_seat(seats=1)
    cid = ctx["contract"]["id"]
    seat = ctx["seat"]
    r2 = create_recruiter(cid)
    get_success_data(api_client.suspend_seat(cid, seat["id"], seat_admin_headers()))

    seat_fresh = get_seat(seat["id"])
    assert seat_fresh["seat_status"] == "SUSPENDED"
    resp = api_client.assign_seat(
        cid, seat["id"],
        {"recruiter_id": r2["id"], "expected_seat_version": seat_fresh["version"]},
        seat_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_SEAT_NOT_AVAILABLE)


# ---------------------------------------------------------------------------
# Corner/validations/inactive_manager_reference_rejected
# ---------------------------------------------------------------------------

def test_inactive_manager_reference_rejected_on_create():
    """PRD section 3.2: "When `manager_recruiter_id` is provided, it must
    reference a recruiter whose `recruiter_status` is `ACTIVE`; otherwise the
    create is rejected with `ERR_MANAGER_INACTIVE`."

    Design: Corner/validations/inactive_manager_reference_rejected
    """
    contract = create_and_activate_contract(seats=1)
    cid = contract["id"]
    mgr = create_recruiter(cid, email="mgr@x.com", full_name="Mgr")
    get_success_data(api_client.deactivate_recruiter(mgr["id"], contract_admin_headers()))

    resp = api_client.create_recruiter(
        {
            "email": "sub@x.com",
            "full_name": "Sub",
            "home_contract_id": cid,
            "manager_recruiter_id": mgr["id"],
        },
        contract_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_MANAGER_INACTIVE)


def test_active_manager_reference_accepted_on_create():
    """PRD section 3.2: "When `manager_recruiter_id` is provided, it must
    reference a recruiter whose `recruiter_status` is `ACTIVE`; otherwise the
    create is rejected with `ERR_MANAGER_INACTIVE`."

    Design: Corner/validations/inactive_manager_reference_rejected
    """
    contract = create_and_activate_contract(seats=1)
    cid = contract["id"]
    mgr = create_recruiter(cid, email="mgr2@x.com", full_name="Mgr Two")

    resp = api_client.create_recruiter(
        {
            "email": "sub2@x.com",
            "full_name": "Sub Two",
            "home_contract_id": cid,
            "manager_recruiter_id": mgr["id"],
        },
        contract_admin_headers(),
    )
    data = validate_success(resp, expected_status=201)
    assert data["manager_recruiter_id"] == mgr["id"]


# ---------------------------------------------------------------------------
# Corner/validations/duplicate_contract_number_rejected
# ---------------------------------------------------------------------------

def test_duplicate_contract_number_rejected():
    """PRD section 2.11: "a contract's `contract_number` is unique across the
    tenant"

    Design: Corner/validations/duplicate_contract_number_rejected
    """
    create_contract(contract_number="C-DUP-1", product_tier="RECRUITER_PRO", seat_cap=3)
    resp = api_client.create_contract(
        create_contract_payload(contract_number="C-DUP-1", product_tier="RECRUITER_LITE",
                                seat_cap=9),
        contract_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)


def test_distinct_contract_numbers_accepted():
    """PRD section 2.11: "a contract's `contract_number` is unique across the
    tenant"

    Design: Corner/validations/duplicate_contract_number_rejected
    """
    create_contract(contract_number="C-DIST-1", product_tier="RECRUITER_PRO", seat_cap=3)
    resp = api_client.create_contract(
        create_contract_payload(contract_number="C-DIST-2", product_tier="RECRUITER_LITE",
                                seat_cap=9),
        contract_admin_headers(),
    )
    validate_success(resp, expected_status=201)


# ---------------------------------------------------------------------------
# Corner/entities/get_contract_not_found_returns_404
# ---------------------------------------------------------------------------

def test_get_contract_not_found_returns_404():
    """PRD section 2.5: "The request is rejected with `ERR_NOT_FOUND` as soon
    as any identifier in the chain does not resolve, without inspecting
    identifiers further to the right."

    Design: Corner/entities/get_contract_not_found_returns_404
    """
    resp = api_client.get_contract(NON_EXISTENT_UUID, contract_admin_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_get_seat_not_found_returns_404():
    """PRD section 2.5: "The request is rejected with `ERR_NOT_FOUND` as soon
    as any identifier in the chain does not resolve, without inspecting
    identifiers further to the right."

    Design: Corner/entities/get_contract_not_found_returns_404
    """
    resp = api_client.get_seat(NON_EXISTENT_UUID, auditor_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ---------------------------------------------------------------------------
# Corner/errors/missing_role_header_unauthenticated
# ---------------------------------------------------------------------------

def test_missing_role_header_unauthenticated_on_list():
    """PRD section 2.1: "A missing or unrecognised `X-User-Role` header is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/missing_role_header_unauthenticated
    """
    resp = api_client.list_contracts(headers={"X-User-ID": "someone"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_unrecognized_role_unauthenticated_on_create():
    """PRD section 2.1: "A missing or unrecognised `X-User-Role` header is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/missing_role_header_unauthenticated
    """
    headers = {
        "X-User-ID": "someone",
        "X-User-Role": "NotARealRole",
        "Content-Type": "application/json",
    }
    resp = api_client.create_contract(create_contract_payload(), headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# ---------------------------------------------------------------------------
# Corner/entities/contract_create_applies_defaults
# ---------------------------------------------------------------------------

def test_contract_create_applies_defaults():
    """PRD section 2.9: "A `true_up_allowed` boolean (defaulting to `true`
    when omitted at contract creation) governs whether true-up renewal events
    may be approved."
    PRD section 3.1: "The contract begins life in `PENDING_ACTIVATION` with
    `seats_purchased` set to 0, `seats_assigned` at 0, and the tier-derived
    quantities from §2.9 computed and attached."

    Design: Corner/entities/contract_create_applies_defaults
    """
    resp = api_client.create_contract(
        create_contract_payload(contract_number="C-ENT-1", product_tier="RECRUITER_PRO",
                                seat_cap=3),
        contract_admin_headers(),
    )
    data = validate_success(resp, expected_status=201)
    assert data["contract_status"] == "PENDING_ACTIVATION"
    assert data["seats_purchased"] == 0
    assert data["true_up_allowed"] is True

    reread = validate_success(api_client.get_contract(data["id"], contract_admin_headers()))
    assert reread["contract_status"] == "PENDING_ACTIVATION"
    assert reread["seats_purchased"] == 0


def test_contract_create_attaches_tier_derived_quantities():
    """PRD section 3.1: "The contract begins life in `PENDING_ACTIVATION` with
    `seats_purchased` set to 0, `seats_assigned` at 0, and the tier-derived
    quantities from §2.9 computed and attached."
    PRD section 2.9: "`monthly_credit_per_seat`: 30 for `RECRUITER_LITE`, 100
    for `RECRUITER_PRO`, 150 for `RECRUITER_CORP`."

    Design: Corner/entities/contract_create_applies_defaults
    """
    resp = api_client.create_contract(
        create_contract_payload(contract_number="C-ENT-1B", product_tier="RECRUITER_LITE",
                                seat_cap=3),
        contract_admin_headers(),
    )
    data = validate_success(resp, expected_status=201)
    assert data["monthly_credit_per_seat"] == 30
    assert data["monthly_search_quota_per_seat"] == 100
    assert data["search_result_page_cap"] == 40
    assert data["seats_assigned"] == 0


# ---------------------------------------------------------------------------
# Corner/entities/recruiter_soft_deleted_excluded_from_default_list
# ---------------------------------------------------------------------------

def test_soft_deleted_recruiter_excluded_from_default_list():
    """PRD section 3.2: "Recruiter listings exclude soft-deleted recruiters by
    default; a `recruiter_status` filter exposes them when needed."

    Design: Corner/entities/recruiter_soft_deleted_excluded_from_default_list
    """
    contract = create_contract(contract_number="C-ENT-2", product_tier="RECRUITER_PRO",
                               seat_cap=3)
    cid = contract["id"]
    r1 = create_recruiter(cid, email="sd1@x.com", full_name="SD One")
    r2 = create_recruiter(cid, email="sd2@x.com", full_name="SD Two")
    get_success_data(api_client.deactivate_recruiter(r1["id"], contract_admin_headers()))

    data, meta = validate_paginated(api_client.list_recruiters(auditor_headers()))
    ids = {row["id"] for row in data}
    assert r2["id"] in ids
    assert r1["id"] not in ids

    data2, meta2 = validate_paginated(
        api_client.list_recruiters(auditor_headers(), params={"recruiter_status": "DEACTIVATED"})
    )
    ids2 = {row["id"] for row in data2}
    assert r1["id"] in ids2


def test_soft_deleted_recruiter_row_remains_fetchable():
    """PRD section 3.2: "Deactivating a recruiter sets `recruiter_status` to
    `DEACTIVATED` (the row remains)."
    PRD section 3.2: "Recruiter listings exclude soft-deleted recruiters by
    default; a `recruiter_status` filter exposes them when needed."

    Design: Corner/entities/recruiter_soft_deleted_excluded_from_default_list
    """
    contract = create_contract(contract_number="C-ENT-2B", product_tier="RECRUITER_PRO",
                               seat_cap=3)
    cid = contract["id"]
    r1 = create_recruiter(cid, email="sd3@x.com", full_name="SD Three")
    get_success_data(api_client.deactivate_recruiter(r1["id"], contract_admin_headers()))

    fetched = validate_success(api_client.get_recruiter(r1["id"], auditor_headers()))
    assert fetched["recruiter_status"] == "DEACTIVATED"

    data, meta = validate_paginated(api_client.list_recruiters(auditor_headers()))
    assert r1["id"] not in {row["id"] for row in data}


# ---------------------------------------------------------------------------
# Corner/endpoints/contracts_list_pagination_envelope
# ---------------------------------------------------------------------------

def test_contracts_list_pagination_envelope():
    """PRD section 2.3: "List endpoints accept `limit` and `offset` query
    parameters. `limit` defaults to 10 when omitted, must be at least 1, and
    may not exceed 100."
    PRD section 2.3: "Every list response includes `limit`, `offset`,
    `total_count`, and `has_more` inside the envelope's `meta` object."

    Design: Corner/endpoints/contracts_list_pagination_envelope
    """
    for n in ("C-PAG-1", "C-PAG-2", "C-PAG-3"):
        create_contract(contract_number=n, product_tier="RECRUITER_LITE", seat_cap=1)

    resp = api_client.list_contracts(contract_admin_headers(),
                                     params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert len(data) == 1


def test_contracts_list_default_limit_and_offset_page():
    """PRD section 2.3: "List endpoints accept `limit` and `offset` query
    parameters. `limit` defaults to 10 when omitted, must be at least 1, and
    may not exceed 100. `offset` defaults to 0."

    Design: Corner/endpoints/contracts_list_pagination_envelope
    """
    for n in ("C-PAG-4", "C-PAG-5", "C-PAG-6"):
        create_contract(contract_number=n, product_tier="RECRUITER_LITE", seat_cap=1)

    resp = api_client.list_contracts(contract_admin_headers())
    data, meta = validate_paginated(resp)
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


# ---------------------------------------------------------------------------
# Corner/endpoints/seats_list_filter_by_status
# ---------------------------------------------------------------------------

def test_seats_list_filter_by_assigned_status():
    """PRD section 3.1: "`seats_assigned` is always the count of `Seat` rows
    in `ASSIGNED` status under this contract; it is maintained by seat
    assignment and unassignment."
    PRD section 4: GET /contracts/{id}/seats "List seats for a contract
    (paginated)".

    Design: Corner/endpoints/seats_list_filter_by_status
    """
    contract = create_and_activate_contract(seats=2, contract_number="C-EP-1")
    cid = contract["id"]
    recruiter = create_recruiter(cid, email="ep1@x.com", full_name="EP One")
    assign_first_seat(cid, recruiter["id"])

    resp = api_client.list_seats(cid, auditor_headers(), params={"seat_status": "ASSIGNED"})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert all(row["seat_status"] == "ASSIGNED" for row in data)


def test_seats_list_unfiltered_shows_all_statuses():
    """PRD section 3.1: "`seats_assigned` is always the count of `Seat` rows
    in `ASSIGNED` status under this contract; it is maintained by seat
    assignment and unassignment."

    Design: Corner/endpoints/seats_list_filter_by_status
    """
    contract = create_and_activate_contract(seats=2, contract_number="C-EP-1B")
    cid = contract["id"]
    recruiter = create_recruiter(cid, email="ep2@x.com", full_name="EP Two")
    assign_first_seat(cid, recruiter["id"])

    data, meta = validate_paginated(api_client.list_seats(cid, auditor_headers()))
    assert meta["total_count"] == 2
    statuses = {row["seat_status"] for row in data}
    assert statuses == {"ASSIGNED", "UNASSIGNED"}


# ---------------------------------------------------------------------------
# Corner/cross_cutting_layers/seat_assign_stale_version_rejected
# ---------------------------------------------------------------------------

def test_seat_assign_stale_version_rejected_after_cycle():
    """PRD section 2.7: "A seat-assignment request must carry
    `expected_seat_version`, holding the client's last-observed `version` of
    the target `Seat`. If the seat's current `version` no longer matches —
    because another writer has mutated the seat since the client read it —
    the assignment is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/seat_assign_stale_version_rejected
    """
    contract = create_and_activate_contract(seats=1, contract_number="C-OCC-1")
    cid = contract["id"]
    r1 = create_recruiter(cid, email="occ1a@x.com", full_name="OCC 1a")
    r2 = create_recruiter(cid, email="occ1b@x.com", full_name="OCC 1b")
    seat = list_seats(cid)[0]
    stale_version = seat["version"]

    assign_seat(cid, seat["id"], r1["id"])
    get_success_data(api_client.unassign_seat(cid, seat["id"], seat_admin_headers()))

    seat_after = get_seat(seat["id"])
    assert seat_after["seat_status"] == "UNASSIGNED"
    resp = api_client.assign_seat(
        cid, seat["id"],
        {"recruiter_id": r2["id"], "expected_seat_version": stale_version},
        seat_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_seat_assign_fresh_version_accepted():
    """PRD section 2.7: "A seat-assignment request must carry
    `expected_seat_version`, holding the client's last-observed `version` of
    the target `Seat`. If the seat's current `version` no longer matches —
    because another writer has mutated the seat since the client read it —
    the assignment is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/seat_assign_stale_version_rejected
    """
    contract = create_and_activate_contract(seats=1, contract_number="C-OCC-1B")
    cid = contract["id"]
    r1 = create_recruiter(cid, email="occ1c@x.com", full_name="OCC 1c")
    seat = list_seats(cid)[0]
    resp = api_client.assign_seat(
        cid, seat["id"],
        {"recruiter_id": r1["id"], "expected_seat_version": seat["version"]},
        seat_admin_headers(),
    )
    data = validate_success(resp, expected_status=200)
    assert data["seat_status"] == "ASSIGNED"


# ---------------------------------------------------------------------------
# Corner/cross_cutting_layers/renewal_event_stale_contract_version_rejected
# ---------------------------------------------------------------------------

def test_renewal_event_stale_contract_version_rejected():
    """PRD section 2.7: "A renewal-event creation request must carry
    `expected_contract_version`, holding the client's last-observed `version`
    of the parent `RecruiterContract`. A mismatch with the contract's current
    `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD section 3.9: "The event's `event_status` begins at `PROPOSED`, and
    proposing the event increments the parent contract's `version` by 1."

    Design: Corner/cross_cutting_layers/renewal_event_stale_contract_version_rejected
    """
    contract = create_and_activate_contract(seats=1, contract_number="C-OCC-2")
    cid = contract["id"]
    cv = current_contract_version(cid)

    resp = api_client.create_renewal_event(
        cid, {"event_kind": "RENEWAL", "expected_contract_version": cv}, auditor_headers(),
    )
    validate_success(resp, expected_status=201)

    resp2 = api_client.create_renewal_event(
        cid, {"event_kind": "RENEWAL", "expected_contract_version": cv}, auditor_headers(),
    )
    validate_error(resp2, ApiErrorId.ERR_STALE_VERSION)


def test_renewal_event_fresh_contract_version_accepted():
    """PRD section 2.7: "A renewal-event creation request must carry
    `expected_contract_version`, holding the client's last-observed `version`
    of the parent `RecruiterContract`. A mismatch with the contract's current
    `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD section 3.9: "The event's `event_status` begins at `PROPOSED`, and
    proposing the event increments the parent contract's `version` by 1."

    Design: Corner/cross_cutting_layers/renewal_event_stale_contract_version_rejected
    """
    contract = create_and_activate_contract(seats=1, contract_number="C-OCC-2B")
    cid = contract["id"]

    first = validate_success(
        api_client.create_renewal_event(
            cid,
            {"event_kind": "RENEWAL", "expected_contract_version": current_contract_version(cid)},
            auditor_headers(),
        ),
        expected_status=201,
    )
    assert first["event_status"] == "PROPOSED"

    second = validate_success(
        api_client.create_renewal_event(
            cid,
            {"event_kind": "RENEWAL", "expected_contract_version": current_contract_version(cid)},
            auditor_headers(),
        ),
        expected_status=201,
    )
    assert second["event_status"] == "PROPOSED"


# ---------------------------------------------------------------------------
# Corner/consistency_model/assign_immediately_visible_in_contract_and_recruiter
# ---------------------------------------------------------------------------

def test_assign_immediately_visible_in_contract_and_recruiter():
    """PRD section 3.2: "On success the seat moves from `UNASSIGNED` to
    `ASSIGNED`, `assigned_recruiter_id` is set to the recruiter,
    `assignment_started_at` is recorded, `assignment_audit_count` increments
    by 1, the recruiter's `active_seat_id` is set to the seat, the contract's
    `seats_assigned` increments by 1, and the seat's `version` increments."

    Design: Corner/consistency_model/assign_immediately_visible_in_contract_and_recruiter
    """
    contract = create_and_activate_contract(seats=1, contract_number="C-CON-1")
    cid = contract["id"]
    recruiter = create_recruiter(cid, email="con1@x.com", full_name="Con One")
    seat = list_seats(cid)[0]

    resp = api_client.assign_seat(
        cid, seat["id"],
        {"recruiter_id": recruiter["id"], "expected_seat_version": seat["version"]},
        seat_admin_headers(),
    )
    assigned = validate_success(resp, expected_status=200)
    assert assigned["seat_status"] == "ASSIGNED"
    assert assigned["assigned_recruiter_id"] == recruiter["id"]

    contract_after = validate_success(api_client.get_contract(cid, contract_admin_headers()))
    assert contract_after["seats_assigned"] == 1
    recruiter_after = validate_success(api_client.get_recruiter(recruiter["id"], auditor_headers()))
    assert recruiter_after["active_seat_id"] == seat["id"]


def test_unassign_immediately_visible_in_contract_and_recruiter():
    """PRD section 3.2: "The recruiter's `active_seat_id` is cleared, the
    seat's `assigned_recruiter_id` and `assignment_started_at` are cleared,
    the contract's `seats_assigned` decrements by 1, and the seat moves back
    to `UNASSIGNED`."

    Design: Corner/consistency_model/assign_immediately_visible_in_contract_and_recruiter
    """
    contract = create_and_activate_contract(seats=1, contract_number="C-CON-1B")
    cid = contract["id"]
    recruiter = create_recruiter(cid, email="con2@x.com", full_name="Con Two")
    seat = assign_first_seat(cid, recruiter["id"])

    resp = api_client.unassign_seat(cid, seat["id"], seat_admin_headers())
    unassigned = validate_success(resp, expected_status=200)
    assert unassigned["seat_status"] == "UNASSIGNED"
    assert unassigned["assigned_recruiter_id"] is None

    contract_after = validate_success(api_client.get_contract(cid, contract_admin_headers()))
    assert contract_after["seats_assigned"] == 0
    recruiter_after = validate_success(api_client.get_recruiter(recruiter["id"], auditor_headers()))
    assert recruiter_after["active_seat_id"] is None
