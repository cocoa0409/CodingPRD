"""Access control, error catalogue, unknown identifiers and list reads."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    create_hit_payload,
    create_acceptance_payload,
    create_cancel_payload,
    create_exam_payload,
    get_success_data,
    make_requester_headers,
    make_worker_headers,
    register_requester,
    register_worker,
    fund_requester,
    get_requester,
    get_worker,
    get_hit,
    get_assignment,
    create_task,
    publish_task,
    create_published_task,
    create_qualification_type,
    accept_task,
    submit_assignment,
    setup_requester,
    setup_worker,
    setup_requester_and_hit,
    setup_review_probe,
    setup_review_probe_multi_slot,
    seed_review_history,
    set_clock,
    CLOCK_EPOCH,
    iso_at,
    NON_EXISTENT_UUID,
)


# ═════════════════════════════════════════════════════════════════════════════
# Registration defaults
# ═════════════════════════════════════════════════════════════════════════════

def test_requester_registration_returns_every_declared_field_active(api, anonymous_headers):
    """PRD §3.1: "The owning `Requester` is named by `requester_id`"
    PRD §2.1: "a requester is created with a legal `name`"
    PRD §4: "Operations that create a new, stand-alone resource — a requester, a
    worker, a qualification type, its exam, an exam attempt, a task, a deposit, an
    acceptance, or a payout request — respond with `201 Created`."

    None of the balance, count or flag fields is client-supplied, so all of them
    must come back at their opening values.

    Design: Corner/entities/requester_create_returns_every_declared_field_and_starts_active
    """
    set_clock(CLOCK_EPOCH)
    res = api.create_requester({"name": "Acme Corner"}, anonymous_headers)
    requester = validate_success(res, 201)

    body = res.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert requester["status"] == "ACTIVE"
    assert requester["prepaid_balance_cents"] == 0
    assert requester["escrowed_cents"] == 0
    assert requester["lifetime_spent_cents"] == 0
    assert requester["abuse_score"] == 0
    assert requester["task_abuse_flag"] is False
    assert requester["id"]
    assert requester["created_at"]
    assert requester["updated_at"]


def test_worker_registration_opens_at_a_hundred_percent_approval_rate(api, anonymous_headers):
    """PRD §2.9: "Whenever a worker's `approval_rate_pct` is recomputed — on an
    approval, on a rejection, or on an administrative resolution"
    PRD §3.7: "When the two counters sum to zero the lifetime rate is 100 by
    definition"

    With both counters at zero the rate is defined as 100 rather than 0, and the
    account opens ACTIVE and unverified.

    Design: Corner/entities/worker_create_defaults_counters_to_zero_and_rate_to_100
    """
    set_clock(CLOCK_EPOCH)
    res = api.create_worker({"display_name": "W1 Corner", "country": "US"}, anonymous_headers)
    worker = validate_success(res, 201)

    assert worker["approval_rate_pct"] == 100
    assert worker["approved_count"] == 0
    assert worker["rejected_count"] == 0
    assert worker["returned_count"] == 0
    assert worker["expired_count"] == 0
    assert worker["identity_verified"] is False
    assert worker["status"] == "ACTIVE"
    assert worker["total_earned_cents"] == 0
    assert worker["withdrawable_cents"] == 0


def test_requester_profile_round_trips_through_a_read(api, admin_headers):
    """PRD §3.7: "When the two counters sum to zero the lifetime rate is 100 by
    definition"
    PRD §3.7: "it is null whenever the requester's status is not `SUSPENDED`"

    Design: Corner/entities/requester_get_returns_the_stored_profile_unchanged
    """
    set_clock(CLOCK_EPOCH)
    requester = setup_requester(name="Acme Retrieval")

    res = api.get_requester(requester["id"], make_requester_headers(requester["id"]))
    stored = validate_success(res, 200)
    assert stored["name"] == "Acme Retrieval"
    assert stored["lifetime_rejection_rate_pct"] == 100
    assert stored["lifetime_spent_cents"] == 0
    assert stored["status"] == "ACTIVE"
    assert stored["suspension_reason"] is None


# ═════════════════════════════════════════════════════════════════════════════
# Access control
# ═════════════════════════════════════════════════════════════════════════════

def test_a_request_with_no_role_header_is_unauthenticated(api, no_auth_headers):
    """PRD §2.1: "Both must be present and must name a registered actor; a missing
    or unrecognised pairing is refused with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/unauthenticated_request_without_role_header_is_rejected
    """
    set_clock(CLOCK_EPOCH)
    res = api.get_assignment(NON_EXISTENT_UUID, no_auth_headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_another_requester_cannot_publish_your_task(api, admin_headers):
    """PRD §2.1: "for requester-owned or worker-owned resources the acting
    principal must be the owner. A request that clears authentication but fails
    this gate is refused with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.4: "Cancelling,
    publishing, or sweeping a task, approving, rejecting, or bonusing submitted
    work, disputing a rejection, returning or submitting an assignment, and
    requesting a withdrawal are all gated on the acting principal being the
    resource's owner, as described in §2.1."

    Design: Corner/errors/requester_role_cannot_act_on_another_requesters_hit
    """
    set_clock(CLOCK_EPOCH)
    owner = register_requester(name="Acme Owner")
    intruder = register_requester(name="Beta Intruder")
    hit = create_task(owner["id"], title="Owned", reward_cents=100, max_assignments=1,
                      assignment_duration_minutes=60, time_limit_minutes=120)

    res = api.publish_hit(hit["id"], make_requester_headers(intruder["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, 403)

    assert get_hit(hit["id"], as_requester_id=owner["id"])["status"] == "DRAFT"


def test_the_anonymous_role_cannot_draft_a_task(api, anonymous_headers):
    """PRD §2.1: "the only operations it may reach are requester registration and
    worker registration."
    PRD §2.1: "Authorisation itself is a second, separate gate: the acting role
    must appear in the operation's permitted role set"

    Design: Corner/rbac/anonymous_cannot_create_a_hit
    """
    set_clock(CLOCK_EPOCH)
    requester = setup_requester(name="Acme RBAC")

    res = api.create_hit(
        create_hit_payload(requester["id"], title="Nope", reward_cents=100,
                           max_assignments=1),
        anonymous_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, 403)

    listed = api_client.list_hits(
        make_requester_headers(requester["id"]), params={"requester_id": requester["id"]}
    )
    assert listed.json()["data"] == []


def test_the_worker_who_submitted_cannot_approve_their_own_work(api, admin_headers):
    """PRD §2.1: "the acting role must appear in the operation's permitted role
    set, and for requester-owned or worker-owned resources the acting principal
    must be the owner."
    PRD §4: Approve submitted work — Authorized Role(s): Requester

    Design: Corner/rbac/worker_cannot_approve_their_own_submitted_work
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignment = setup_review_probe(
        decision=None, title="SelfApprove Probe", deposit_cents=1_000,
    )

    res = api.approve_assignment(assignment["id"], make_worker_headers(worker["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, 403)

    stored = get_assignment(assignment["id"], as_worker_id=worker["id"])
    assert stored["status"] == "SUBMITTED"
    assert get_worker(worker["id"])["approved_count"] == 0


def test_a_platform_operator_reads_any_requester_profile(api, admin_headers):
    """PRD §2.1: "When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque
    operator identifier that is not tied to any persisted entity"
    PRD §4: Get a requester profile — Authorized Role(s): Requester, PlatformAdmin

    Design: Corner/rbac/platform_admin_can_read_any_requester_profile
    """
    set_clock(CLOCK_EPOCH)
    requester = setup_requester(name="Acme Shared")

    res = api.get_requester(requester["id"], admin_headers)
    stored = validate_success(res, 200)
    assert stored["name"] == "Acme Shared"


def test_a_requester_cannot_reinstate_even_their_own_suspended_account(api, admin_headers):
    """PRD §4: Reinstate a suspended requester — Authorized Role(s): PlatformAdmin
    PRD §2.4: "Administrative operations — deposit settlement, abuse review
    and reinstatement, identity verification, worker suspension, exam authoring,
    dispute resolution, payout release and payout rejection, and the logical clock
    controls — are reserved to `PlatformAdmin` and are not ownership-scoped."

    Design: Corner/rbac/requester_cannot_reinstate_a_suspended_requester
    """
    set_clock(CLOCK_EPOCH)
    requester = setup_requester(name="Acme Suspend RBAC", deposit_cents=20_000)
    seed_review_history(
        requester, ["APPROVE", "REJECT", "APPROVE", "REJECT", "REJECT"]
    )
    api.run_abuse_review(requester["id"], admin_headers)
    assert get_requester(requester["id"])["status"] == "SUSPENDED"

    res = api.reinstate_requester(requester["id"], make_requester_headers(requester["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, 403)

    assert get_requester(requester["id"])["status"] == "SUSPENDED"


# ═════════════════════════════════════════════════════════════════════════════
# Unknown identifiers and the path-resolution order
# ═════════════════════════════════════════════════════════════════════════════

def test_an_unallocated_assignment_id_reads_not_found(api, admin_headers):
    """PRD §2.4: "the first identifier that does not name an existing row of its
    collection short-circuits the request with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/assignment_get_with_unknown_id_returns_not_found
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignment = setup_review_probe(
        decision=None, title="NotFound Probe", deposit_cents=1_000,
    )

    live = api.get_assignment(assignment["id"], make_worker_headers(worker["id"]))
    validate_success(live, 200)

    missing = api.get_assignment(NON_EXISTENT_UUID, admin_headers)
    validate_error(missing, ApiErrorId.ERR_NOT_FOUND, 404)


def test_an_unknown_task_segment_outranks_the_balance_check(api, admin_headers):
    """PRD §2.4: "A request that reaches an assignment through a task that does
    not exist, or a review through an assignment that does not exist, therefore
    fails on the outer segment before any inner logic runs."
    PRD §2.7: "a request that violates an earlier step never reaches a later one"

    The requester's balance is zero, but existence is resolved first, so the 404
    is returned rather than any state or fiscal error.

    Design: Corner/validations/unknown_hit_path_segment_outranks_state_checks
    """
    set_clock(CLOCK_EPOCH)
    requester = setup_requester(name="Acme Existence")

    res = api.publish_hit(NON_EXISTENT_UUID, make_requester_headers(requester["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, 404)
    assert get_requester(requester["id"])["prepaid_balance_cents"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# Type constraints and closed enumerations
# ═════════════════════════════════════════════════════════════════════════════

def test_a_qualification_kind_outside_the_enum_is_a_bad_request(api, admin_headers):
    """PRD §3.2: "A `QualificationType` is authored with a human-readable `name`,
    a `kind` of `SYSTEM` or `REQUESTER` that is descriptive only"
    PRD §2.10: "`ERR_INVALID_REQUEST` (HTTP 400) rejects a malformed body, a
    missing required field, or a value outside its declared enum or type"

    Design: Corner/entities/qualification_type_out_of_enum_kind_returns_invalid_request
    """
    set_clock(CLOCK_EPOCH)
    res = api.create_qualification_type(
        {"name": "Bad Kind", "kind": "BOGUS", "auto_assign_threshold_pct": 80},
        admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_an_exam_cannot_be_authored_for_a_type_that_cannot_carry_one(api, admin_headers):
    """PRD §3.2: "Authoring an exam against a type whose `exam_available` is false
    is refused with `ERR_EXAM_NOT_AVAILABLE` (HTTP 409)."
    PRD §3.2: "an `exam_available` flag, false when omitted"

    Design: Corner/errors/exam_creation_for_a_type_without_exam_available_is_refused
    """
    set_clock(CLOCK_EPOCH)
    qualification_type = create_qualification_type(
        name="ClosedType", kind="SYSTEM", auto_assign_threshold_pct=90,
    )

    res = api.create_exam(qualification_type["id"], create_exam_payload(passing_score=80),
                          admin_headers)
    validate_error(res, ApiErrorId.ERR_EXAM_NOT_AVAILABLE, 409)

    listed = api.list_exams(qualification_type["id"], admin_headers)
    assert listed.json()["data"] == []


# ═════════════════════════════════════════════════════════════════════════════
# Listing and pagination
# ═════════════════════════════════════════════════════════════════════════════

def test_task_list_paginates_and_filters_by_status(api, admin_headers):
    """PRD §2.3: "List endpoints accept a `limit` query parameter giving the
    maximum number of items to return, defaulting to 10 when omitted, with a
    minimum of 1 and a maximum of 100"
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object"

    With two published and one draft task, a limit of one still reports
    total_count 2 — the count covers the whole filtered set, not the page.

    Design: Corner/entities/hits_list_paginates_and_filters_by_status
    """
    set_clock(CLOCK_EPOCH)
    requester = register_requester(name="Acme Listing")
    requester = fund_requester(requester, 2_000)
    first = create_task(requester["id"], title="List A", reward_cents=100,
                        max_assignments=1, assignment_duration_minutes=60,
                        time_limit_minutes=120)
    second = create_task(requester["id"], title="List B", reward_cents=100,
                         max_assignments=1, assignment_duration_minutes=60,
                         time_limit_minutes=120)
    create_task(requester["id"], title="List C", reward_cents=100,
                        max_assignments=1, assignment_duration_minutes=60,
                        time_limit_minutes=120)
    publish_task(first["id"], requester["id"])
    publish_task(second["id"], requester["id"])

    headers = make_requester_headers(requester["id"])
    page, meta = validate_paginated(
        api.list_hits(headers, params={"requester_id": requester["id"],
                                       "status": "PUBLISHED", "limit": 1, "offset": 0})
    )
    assert len(page) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True

    everything, meta_all = validate_paginated(
        api.list_hits(headers, params={"requester_id": requester["id"]})
    )
    assert len(everything) == 3
    assert meta_all["total_count"] == 3

    published, meta_published = validate_paginated(
        api.list_hits(headers, params={"requester_id": requester["id"],
                                       "status": "PUBLISHED", "limit": 10, "offset": 0})
    )
    assert len(published) == 2
    assert meta_published["has_more"] is False


def test_requester_task_list_is_scoped_to_its_owner(api, admin_headers):
    """PRD §4: List the tasks owned by a requester
    PRD §2.3: "`total_count`"

    Acme owns two tasks and Beta owns one; the requester-scoped list must return
    Acme's two and never Beta's.

    Design: Corner/endpoints/hit_list_by_requester_returns_only_that_requesters_hits
    """
    set_clock(CLOCK_EPOCH)
    acme = register_requester(name="Acme Scoped")
    beta = register_requester(name="Beta Scoped")

    acme_first = create_task(acme["id"], title="A1", reward_cents=100, max_assignments=1,
                             assignment_duration_minutes=60, time_limit_minutes=120)
    acme_second = create_task(acme["id"], title="A2", reward_cents=100, max_assignments=1,
                              assignment_duration_minutes=60, time_limit_minutes=120)
    beta_first = create_task(beta["id"], title="B1", reward_cents=100, max_assignments=1,
                             assignment_duration_minutes=60, time_limit_minutes=120)

    res = api.list_requester_hits(acme["id"], make_requester_headers(acme["id"]))
    page, meta = validate_paginated(res)
    assert len(page) == 2
    assert meta["total_count"] == 2
    returned = {row["id"] for row in page}
    assert returned == {acme_first["id"], acme_second["id"]}
    assert beta_first["id"] not in returned