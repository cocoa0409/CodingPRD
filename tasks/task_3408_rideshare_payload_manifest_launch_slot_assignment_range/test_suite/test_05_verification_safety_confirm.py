"""Interface verification immutability, safety-review gating, segregation of
duties, and confirm/remove state gates."""
from test_helpers import (
    ApiErrorId,
    assert_verification,
    confirm_assignment,
    create_granted_customer_license,
    create_assignment,
    get_assignment,
    get_mission,
    review_assignment,
    set_clock,
    setup_confirmed_mission,
    setup_locked_mission,
    setup_provisional_assignments,
    validate_error,
    validate_success,
    verification_payload,
    verify_assignment,
    api_client,
)
from test_helpers.test_users import TEST_USERS, make_engineer_headers, make_safety_headers

MOPS = TEST_USERS["mission_ops_headers"]
SAFETY = TEST_USERS["safety_headers"]


def test_confirm_rejected_while_latest_safety_review_is_reject(api):
    """PRD §3.3: "the latest safety review must be an `APPROVE`, else
    `ERR_SAFETY_REVIEW_REQUIRED` (409)"
    PRD §3.3: "The latest safety review by `created_at` governs the assignment."

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_until_latest_safety_review_approves
    """
    ctx = setup_provisional_assignments()
    a1 = ctx["assignments"][0]
    verify_assignment(a1["id"])
    review_assignment(a1["id"], decision="REJECT", rationale="wiring harness doubt")
    resp = api_client.confirm_assignment(a1["id"], MOPS)
    validate_error(resp, ApiErrorId.ERR_SAFETY_REVIEW_REQUIRED)
    assert get_assignment(a1["id"])["status"] == "PROVISIONAL"


def test_confirm_succeeds_once_newer_approve_review_governs(api):
    """PRD §3.3: "the latest safety review must be an `APPROVE`, else
    `ERR_SAFETY_REVIEW_REQUIRED` (409)"
    PRD §3.3: "The latest safety review by `created_at` governs the assignment."

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_until_latest_safety_review_approves
    """
    ctx = setup_provisional_assignments()
    a1 = ctx["assignments"][0]
    verify_assignment(a1["id"])
    review_assignment(a1["id"], decision="REJECT", rationale="wiring harness doubt")
    review_assignment(a1["id"], decision="APPROVE", rationale="harness reworked and re-inspected")
    confirmed = confirm_assignment(a1["id"])
    assert confirmed["status"] == "CONFIRMED"
    reviews = validate_success(api_client.list_safety_reviews(a1["id"], SAFETY), 200)
    assert len(reviews) == 2, "both reviews persist; the latest governs"


def test_interface_verification_records_are_immutable_after_create(api):
    """PRD §2.5: "Append-only records — `InterfaceVerification`, `SafetyReview`,
    `ExclusionWindow`, and `DelayEvent` — carry only `id` and `created_at`; both
    `updated_at` and `version` are absent from these entities."
    PRD §3.3: "Each verification stores the recording engineer's `X-User-ID` as
    `created_by_user_id`. Verifications are never updated; the latest record per
    `check_type` is the one that governs confirmation."

    Design: Corner/entities/interface_verification_records_are_immutable_after_create
    """
    ctx = setup_provisional_assignments()
    a1 = ctx["assignments"][0]
    resp = api_client.create_verification(
        a1["id"],
        verification_payload(check_type="MECHANICAL", outcome="PASSED", notes="bolt pattern ok"),
        make_engineer_headers("eng-1"),
    )
    created = validate_success(resp, 201)
    assert_verification(created)
    assert created["created_by_user_id"] == "eng-1", "recorded from the X-User-ID header"

    first_list = validate_success(api_client.list_verifications(a1["id"], SAFETY), 200)
    assert len(first_list) == 1
    assert first_list[0]["check_type"] == "MECHANICAL"
    assert first_list[0]["outcome"] == "PASSED"

    resp2 = api_client.create_verification(
        a1["id"],
        verification_payload(check_type="MECHANICAL", outcome="PASSED", notes="bolt pattern ok"),
        make_engineer_headers("eng-1"),
    )
    validate_success(resp2, 201)
    filtered = validate_success(
        api_client.list_verifications(a1["id"], SAFETY, params={"check_type": "MECHANICAL"}),
        200,
    )
    assert len(filtered) == 2, "append-only: the identical second POST creates a second row"


def test_double_confirm_rejected_as_invalid_state(api):
    """PRD §3.3: "the assignment must be `PROVISIONAL` (else
    `ERR_INVALID_STATE`)"
    PRD §2.5: "An entity's `version` starts at 1 when the entity is created and
    increments by exactly 1 only where a state-machine transition or an
    endpoint's documented side effects say so."

    Design: Corner/state_machines/double_confirm_rejected_as_invalid_state
    """
    ctx = setup_confirmed_mission()
    a1 = ctx["assignments"][0]
    version_before = get_assignment(a1["id"])["version"]
    resp = api_client.confirm_assignment(a1["id"], MOPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_assignment(a1["id"])
    assert after["status"] == "CONFIRMED"
    assert after["version"] == version_before, "the rejected call has no side effects"


def test_manual_remove_of_integrated_assignment_rejected(api):
    """PRD §3.3: "A `MissionOps` operator may remove an assignment — optionally
    recording a `reason_code` — only while it is `PROVISIONAL` or `CONFIRMED`;
    any other state is rejected with `ERR_INVALID_STATE`, though the cascade
    paths of §3.4 and §3.7 may also remove `INTEGRATED` assignments."

    Design: Corner/state_machines/manual_remove_of_integrated_assignment_rejected
    """
    ctx = setup_locked_mission()
    a1 = ctx["assignments"][0]
    assert a1["status"] == "INTEGRATED"
    resp = api_client.remove_assignment(a1["id"], MOPS, reason_code="CUSTOMER_REQUEST")
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_assignment(a1["id"])["status"] == "INTEGRATED"
    assert get_mission(ctx["mission"]["id"])["committed_mass_kg"] == 100, (
        "no capacity release on a rejected removal"
    )


def test_confirm_without_all_verifications_rejected(api):
    """PRD §3.3: "the latest `MECHANICAL` verification must be `PASSED` and the
    latest `ELECTRICAL` verification must be `PASSED`, else
    `ERR_VERIFICATION_INCOMPLETE` (HTTP 409)"

    Design: Corner/errors/confirm_without_all_verifications_rejected
    """
    ctx = setup_provisional_assignments()
    a1 = ctx["assignments"][0]
    get_success = api_client.create_verification(
        a1["id"],
        verification_payload(check_type="MECHANICAL", outcome="PASSED"),
        make_engineer_headers("eng-1"),
    )
    assert get_success.status_code == 201
    review_assignment(a1["id"])
    resp = api_client.confirm_assignment(a1["id"], MOPS)
    validate_error(resp, ApiErrorId.ERR_VERIFICATION_INCOMPLETE)
    assert get_assignment(a1["id"])["status"] == "PROVISIONAL"


def test_confirm_without_payload_license_rejected(api):
    """PRD §3.3: "the payload's customer must hold a `GRANTED` license of kind
    `PAYLOAD_OPERATOR`, else `ERR_LICENSE_NOT_GRANTED` (422)."

    Design: Corner/errors/confirm_without_payload_license_rejected
    """
    ctx = setup_provisional_assignments(with_customer_license=False)
    a1 = ctx["assignments"][0]
    verify_assignment(a1["id"])
    review_assignment(a1["id"])
    resp = api_client.confirm_assignment(a1["id"], MOPS)
    err = validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_GRANTED)
    assert err["error_id"] not in ("ERR_VERIFICATION_INCOMPLETE", "ERR_SAFETY_REVIEW_REQUIRED"), (
        "both state gates passed; the license gate is the one that fires"
    )
    assert get_assignment(a1["id"])["status"] == "PROVISIONAL"


def test_safety_reviewer_who_recorded_verification_is_denied(api):
    """PRD §2.11: "A `SafetyOfficer` recording a safety review must not be the
    same individual as any engineer who recorded a `PASSED` verification on the
    same assignment: if the reviewer's `X-User-ID` equals the
    `created_by_user_id` of any `PASSED` interface verification on that
    assignment, the review is rejected with `ERR_SOD_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/safety_reviewer_who_recorded_verification_is_denied
    """
    ctx = setup_provisional_assignments()
    a1 = ctx["assignments"][0]
    verify_assignment(a1["id"], engineer_id="eng-1")

    resp = api_client.create_safety_review(
        a1["id"],
        {"decision": "APPROVE", "rationale": "self-review attempt"},
        make_safety_headers("eng-1"),
    )
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

    ok = api_client.create_safety_review(
        a1["id"],
        {"decision": "APPROVE", "rationale": "independent review"},
        make_safety_headers("so-1"),
    )
    validate_success(ok, 201)
    reviews = validate_success(api_client.list_safety_reviews(a1["id"], SAFETY), 200)
    assert len(reviews) == 1, "only the independent review persisted"
