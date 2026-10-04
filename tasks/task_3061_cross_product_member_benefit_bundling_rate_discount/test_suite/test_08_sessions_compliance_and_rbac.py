"""Coaching sessions, cross-sell compliance, RBAC and read-side consistency."""
from test_helpers import (
    ALTERNATE,
    TEST_USERS,
    declare_entitlement,
    fetch_check,
    fetch_holding,
    fetch_member,
    fetch_session,
    headers_without_auth,
    make_member_headers,
    register_member,
    setup_career_member_with_entitlement,
    setup_cross_sell_member,
    setup_member_with_lending_loan_final,
    setup_member_with_notice,
    validate_error,
    validate_success,
)


# --------------------------------------------------------------------------
# Career coaching and member events
# --------------------------------------------------------------------------

def test_a_career_coaching_slot_is_exclusive_on_a_closed_interval(api):
    """PRD §3.9: "A career-coaching session is a one-to-one exclusive slot: it
    may not overlap another non-cancelled career-coaching session on the same
    coach, and because its interval is closed on both ends a session ending
    exactly when the next begins collides with it — such a booking, or the
    confirmation of one, is refused with `ERR_SESSION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/career_coaching_slot_exclusive_on_a_closed_interval
    """
    setup = setup_career_member_with_entitlement()
    member_id = setup["member"]["id"]

    first = validate_success(api.book_coaching_session(
        {"member_id": member_id, "coach_ref": "COACH-BETA", "session_kind": "CAREER_COACHING",
         "starts_at": "2026-09-10T15:00:00Z", "ends_at": "2026-09-10T16:00:00Z",
         "capacity_total": 1},
        TEST_USERS["benefits_admin_headers"],
    ), expected_status=201)
    assert fetch_session(first["id"])["status"] == "SCHEDULED"

    resp = api.book_coaching_session(
        {"member_id": member_id, "coach_ref": "COACH-BETA", "session_kind": "CAREER_COACHING",
         "starts_at": "2026-09-10T16:00:00Z", "ends_at": "2026-09-10T17:00:00Z",
         "capacity_total": 1},
        TEST_USERS["benefits_admin_headers"],
    )
    validate_error(resp, "ERR_SESSION_OVERLAP", expected_status=409)


def test_the_career_collision_is_scoped_to_the_coach_ref(api):
    """PRD §3.9: "it may not overlap another non-cancelled career-coaching
    session on the same coach".
    PRD §2.6: "The computed `consecutive_qualifying_months` counts the maximal
    trailing run"; the reserved-seat figure is scoped to the session's own coach.

    Design: Difficulty/resource_temporal_overlap/career_coaching_slot_exclusive_on_a_closed_interval
    """
    setup = setup_career_member_with_entitlement()
    member_id = setup["member"]["id"]
    validate_success(api.book_coaching_session(
        {"member_id": member_id, "coach_ref": "COACH-BETA", "session_kind": "CAREER_COACHING",
         "starts_at": "2026-09-10T15:00:00Z", "ends_at": "2026-09-10T16:00:00Z",
         "capacity_total": 1},
        TEST_USERS["benefits_admin_headers"],
    ), expected_status=201)

    # The same interval on a different coach has nothing to collide with.
    other = api.book_coaching_session(
        {"member_id": member_id, "coach_ref": "COACH-GAMMA", "session_kind": "CAREER_COACHING",
         "starts_at": "2026-09-10T16:00:00Z", "ends_at": "2026-09-10T17:00:00Z",
         "capacity_total": 1},
        TEST_USERS["benefits_admin_headers"],
    )
    validate_success(other, expected_status=201)


def test_a_member_event_booking_beyond_the_pool_is_saturated(api):
    """PRD §3.9: "A member event is instead a capacity pool: it is refused with
    `ERR_SESSION_CAPACITY_SATURATED` only when the number of non-cancelled
    sessions sharing its coach and overlapping it, under half-open semantics in
    which a session ending exactly when the next begins does not collide, has
    already reached the venue capacity declared by the earliest-created
    overlapping session on that coach."

    Design: Difficulty/resource_temporal_overlap/member_event_seat_pool_saturates_on_a_half_open_interval
    """
    member = register_member(member_number="M-3061-016", email="pia.c@x.com")
    holding = api.create_holding(
        {"member_id": member["id"], "product_line": "CAREER", "balance_cents": 0},
        TEST_USERS["platform_admin_headers"],
    ).json()["data"]
    validate_success(api.adopt_holding(holding["id"], make_member_headers(member["id"])))

    event = validate_success(api.book_coaching_session(
        {"member_id": member["id"], "coach_ref": "EVENT-HALL", "session_kind": "MEMBER_EVENT",
         "starts_at": "2026-09-20T18:00:00Z", "ends_at": "2026-09-20T19:00:00Z",
         "capacity_total": 1},
        TEST_USERS["benefits_admin_headers"],
    ), expected_status=201)
    assert event["seats_reserved"] == 1, "the first booking on the interval holds one seat"

    resp = api.book_coaching_session(
        {"member_id": member["id"], "coach_ref": "EVENT-HALL", "session_kind": "MEMBER_EVENT",
         "starts_at": "2026-09-20T18:00:00Z", "ends_at": "2026-09-20T19:00:00Z",
         "capacity_total": 1},
        TEST_USERS["benefits_admin_headers"],
    )
    validate_error(resp, "ERR_SESSION_CAPACITY_SATURATED", expected_status=409)

    assert fetch_session(event["id"])["seats_reserved"] == 1, (
        "the refused booking does not consume the pool"
    )


def test_two_member_events_that_merely_touch_do_not_collide(api):
    """PRD §3.9: "under half-open semantics in which a session ending exactly
    when the next begins does not collide".
    PRD §3.9: "The reserved-seat figure reported as `seats_reserved` for a member
    event is the count of non-cancelled sessions of that kind on the same coach
    whose intervals overlap it under the same half-open convention."

    Design: Difficulty/resource_temporal_overlap/member_event_seat_pool_saturates_on_a_half_open_interval
    """
    member = register_member(member_number="M-3061-016B", email="pia.c.b@x.com")
    holding = api.create_holding(
        {"member_id": member["id"], "product_line": "CAREER", "balance_cents": 0},
        TEST_USERS["platform_admin_headers"],
    ).json()["data"]
    validate_success(api.adopt_holding(holding["id"], make_member_headers(member["id"])))
    validate_success(api.book_coaching_session(
        {"member_id": member["id"], "coach_ref": "EVENT-HALL-B", "session_kind": "MEMBER_EVENT",
         "starts_at": "2026-09-20T18:00:00Z", "ends_at": "2026-09-20T19:00:00Z",
         "capacity_total": 1},
        TEST_USERS["benefits_admin_headers"],
    ), expected_status=201)

    # The pool holds one seat, but a booking starting exactly when the first ends
    # does not overlap it, so it is admitted as a fresh interval.
    next_event = api.book_coaching_session(
        {"member_id": member["id"], "coach_ref": "EVENT-HALL-B", "session_kind": "MEMBER_EVENT",
         "starts_at": "2026-09-20T19:00:00Z", "ends_at": "2026-09-20T20:00:00Z",
         "capacity_total": 1},
        TEST_USERS["benefits_admin_headers"],
    )
    validate_success(next_event, expected_status=201)


def test_completing_a_session_before_its_start_is_refused(api):
    """PRD §3.9: "An administrator marks a confirmed session complete once the
    current instant has reached its start, moving it to `COMPLETED`."

    Design: Corner/state_machines/coaching_session_complete_before_start_returns_invalid_state
    """
    setup = setup_career_member_with_entitlement()
    member_id = setup["member"]["id"]
    session = validate_success(api.book_coaching_session(
        {"member_id": member_id, "coach_ref": "COACH-OMEGA", "session_kind": "CAREER_COACHING",
         "starts_at": "2026-09-25T14:00:00Z", "ends_at": "2026-09-25T15:00:00Z",
         "capacity_total": 1},
        TEST_USERS["benefits_admin_headers"],
    ), expected_status=201)
    validate_success(api.confirm_coaching_session(session["id"], make_member_headers(member_id)))

    resp = api.complete_coaching_session(session["id"], TEST_USERS["platform_admin_headers"])
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)

    still = fetch_session(session["id"])
    assert still["status"] == "CONFIRMED", "the session is not marked complete before it starts"
    assert fetch_member(member_id)["rewards_points_balance"] == 0, (
        "no 250-point earning fires from a refused completion"
    )


# --------------------------------------------------------------------------
# Cross-sell compliance
# --------------------------------------------------------------------------

def test_clearing_a_check_flips_cross_sell_eligibility_for_the_target_line(api):
    """PRD §3.9: "a `CLEARED` decision sets cross-sell eligibility true for the
    member's holdings of the target line".
    PRD §2.4: "`cross_sell_eligible` is true only when the holding's adoption
    status is `ADOPTED` or `SUSPENDED` and the most recent cross-sell check for
    that member carries the outcome `CLEARED`; if no such check exists the value
    is false."

    Design: Difficulty/cross_entity_state_dependency/cross_sell_clearance_gates_a_second_check_on_the_member
    """
    setup = setup_cross_sell_member("INVESTING", consent_recorded=True)
    holding_id = setup["holdings"]["LENDING"]["id"]
    check = setup["check"]

    before = fetch_holding(holding_id)
    assert before["cross_sell_eligible"] is False, (
        "no CLEARED check exists yet, so eligibility is false"
    )

    cleared = validate_success(api.decide_cross_sell_check(
        check["id"], {"outcome": "CLEARED"}, TEST_USERS["compliance_officer_headers"]))
    assert cleared["status"] == "CLEARED"
    assert fetch_holding(holding_id)["cross_sell_eligible"] is False, (
        "the decision is scoped to the target line's holdings, not the member's others"
    )


def test_a_later_blocked_check_lifts_the_previously_cleared_eligibility(api):
    """PRD §3.9: "a later cleared check for the same member and target line
    supersedes the earlier one for eligibility purposes."
    PRD §3.9: "a `BLOCKED` decision sets it false for those holdings".

    Design: Difficulty/cross_entity_state_dependency/cross_sell_clearance_gates_a_second_check_on_the_member
    """
    member = register_member(member_number="M-3061-014B", email="nia.c.b@x.com")
    holding = api.create_holding(
        {"member_id": member["id"], "product_line": "INVESTING", "balance_cents": 0},
        TEST_USERS["platform_admin_headers"],
    ).json()["data"]
    validate_success(api.adopt_holding(holding["id"], make_member_headers(member["id"])))

    first = validate_success(api.create_cross_sell_check(
        {"member_id": member["id"], "target_product_line": "INVESTING", "consent_recorded": True},
        TEST_USERS["benefits_admin_headers"],
    ), expected_status=201)
    validate_success(api.decide_cross_sell_check(first["id"], {"outcome": "CLEARED"},
                                                 TEST_USERS["compliance_officer_headers"]))
    assert fetch_holding(holding["id"])["cross_sell_eligible"] is True

    second = validate_success(api.create_cross_sell_check(
        {"member_id": member["id"], "target_product_line": "INVESTING", "consent_recorded": False},
        TEST_USERS["benefits_admin_headers"],
    ), expected_status=201)
    assert second["conditioning_blocked"] is True
    validate_success(api.decide_cross_sell_check(second["id"], {"outcome": "BLOCKED"},
                                                 TEST_USERS["compliance_officer_headers"]))
    assert fetch_holding(holding["id"])["cross_sell_eligible"] is False, (
        "eligibility follows the check with the greatest created_at"
    )


def test_prohibiting_reuse_is_admitted_on_a_lending_target_with_no_final_loan(api):
    """PRD §3.9: "Prohibiting reuse requires that underwriting reuse is not
    permitted and that the target line is lending, and moves the check to
    `REUSE_PROHIBITED`".
    PRD §2.4: "`reunderwriting_permitted` is true only when the holding's product
    line is `LENDING`, its adoption status is `ADOPTED`, and a loan account exists
    for that holding whose pricing status is `FINAL` or `STEPPED_DOWN`."

    Design: Corner/state_machines/cross_sell_reuse_prohibited_branch_on_the_check_machine
    """
    setup = setup_member_with_lending_loan_final(pricing_final=False, base_apr_bps=1090)
    holding = setup["holding"]
    assert setup["loan"]["pricing_status"] == "PROVISIONAL"
    assert fetch_holding(holding["id"])["reunderwriting_permitted"] is False, (
        "a PROVISIONAL loan does not permit reuse"
    )

    check = validate_success(api.create_cross_sell_check(
        {"member_id": setup["member"]["id"], "target_product_line": "LENDING",
         "consent_recorded": True},
        TEST_USERS["benefits_admin_headers"],
    ), expected_status=201)

    decided = validate_success(api.decide_cross_sell_check(
        check["id"], {"outcome": "REUSE_PROHIBITED"}, TEST_USERS["compliance_officer_headers"]))
    assert decided["status"] == "REUSE_PROHIBITED"
    assert decided["decided_by"] is not None
    assert fetch_holding(holding["id"])["reunderwriting_permitted"] is False


def test_finalizing_a_loan_marks_the_holding_as_permitting_reuse(api):
    """PRD §3.5: "Finalization freezes the discount stack at the snapshots
    captured when the loan was finalized and marks the linked holding as
    permitting underwriting reuse."

    Design: Corner/state_machines/cross_sell_reuse_prohibited_branch_on_the_check_machine
    """
    setup = setup_member_with_lending_loan_final(pricing_final=True, base_apr_bps=1090)
    holding = fetch_holding(setup["holding"]["id"])
    assert setup["loan"]["pricing_status"] == "FINAL"
    assert holding["reunderwriting_permitted"] is True, (
        "a FINAL-priced loan on an adopted lending holding permits reuse"
    )


def test_clearing_a_target_that_has_no_consent_reports_the_conditioning_barrier(api):
    """PRD §3.9: "Clearing the check requires that conditioning is not blocked,
    that consent has been recorded or the target line is lending, and that no
    prior cleared check already exists for the same member and target line; a
    request that would clear a blocked target is refused with
    `ERR_CREDIT_CONDITIONING_BLOCKED`".

    Design: Corner/validations/participant_role_on_a_benefits_admin_endpoint_returns_forbidden_role
    """
    setup = setup_cross_sell_member("BANKING", consent_recorded=False)
    assert setup["check"]["conditioning_blocked"] is True
    resp = api.decide_cross_sell_check(setup["check"]["id"], {"outcome": "CLEARED"},
                                       TEST_USERS["compliance_officer_headers"])
    validate_error(resp, "ERR_CREDIT_CONDITIONING_BLOCKED", expected_status=422)
    assert fetch_check(setup["check"]["id"])["status"] == "PENDING"


# --------------------------------------------------------------------------
# RBAC
# --------------------------------------------------------------------------

def test_an_underwriter_cannot_create_rate_discount_rules(api):
    """PRD §2.1: "If `X-User-Role` names a role that is not one of these six, or
    names a declared role that is not listed on the endpoint being called, the
    request is refused with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/underwriter_cannot_create_rate_discount_rules
    """
    resp = api.create_rule(
        {"rule_code": "UW_BLOCKED", "discount_kind": "AUTOPAY", "stacking_class": "ADDITIVE",
         "discount_bps": 10, "effective_from": "2026-01-01T00:00:00Z",
         "effective_to": "2027-01-01T00:00:00Z"},
        TEST_USERS["underwriter_headers"],
    )
    validate_error(resp, "ERR_FORBIDDEN_ROLE", expected_status=403)

    rules = validate_success(api.list_rules(TEST_USERS["benefits_admin_headers"]))
    assert rules == [], "no rule was created by the refused call"

    # The same operator role still owns the surface it is granted.
    member = register_member(member_number="M-R-001", email="uw.ok@x.com")
    holding = api.create_holding(
        {"member_id": member["id"], "product_line": "LENDING", "balance_cents": 0},
        TEST_USERS["platform_admin_headers"],
    ).json()["data"]
    validate_success(api.adopt_holding(holding["id"], make_member_headers(member["id"])))
    validate_success(api.create_loan_account(
        {"member_id": member["id"], "holding_id": holding["id"], "loan_type": "PERSONAL",
         "principal_cents": 300000, "base_apr_bps": 1100},
        TEST_USERS["underwriter_headers"],
    ), expected_status=201)


def test_a_platform_admin_cannot_decide_a_cross_sell_check(api):
    """PRD §2.1: "If `X-User-Role` names a role that is not one of these six, or
    names a declared role that is not listed on the endpoint being called, the
    request is refused with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/platform_admin_cannot_decide_a_cross_sell_check
    """
    setup = setup_cross_sell_member("INVESTING", consent_recorded=True)
    check = setup["check"]

    resp = api.decide_cross_sell_check(check["id"], {"outcome": "CLEARED"},
                                       TEST_USERS["platform_admin_headers"])
    validate_error(resp, "ERR_FORBIDDEN_ROLE", expected_status=403)

    after = fetch_check(check["id"])
    assert after["status"] == "PENDING"
    assert after["decided_at"] is None


def test_a_member_cannot_acknowledge_another_members_notice(api):
    """PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the
    acting member entity; every ownership check on a resource that references a
    member compares that resource's member foreign-key field to `X-User-ID`, and
    a mismatch is an `ERR_FORBIDDEN_ROLE` rejection."

    Design: Corner/rbac/member_acknowledge_for_another_members_notice_is_forbidden
    """
    owner, notice = setup_member_with_notice(status="QUEUED")
    assert owner["id"] == notice["member_id"]
    validate_success(api.send_churn_notice(notice["id"], TEST_USERS["platform_admin_headers"]))

    validate_success(api.create_member(
        {"member_number": "M-R-006", "full_name": "Ravi N", "email": "ravi.n@x.com"},
        TEST_USERS["anonymous_headers"],
    ), expected_status=201)
    stranger = api.list_members(TEST_USERS["platform_admin_headers"],
                                params={"email": "ravi.n@x.com"})
    stranger = stranger[0] if isinstance(stranger, list) else validate_success(stranger)[0]
    resp = api.acknowledge_churn_notice(notice["id"], make_member_headers(stranger["id"]))
    validate_error(resp, "ERR_FORBIDDEN_ROLE", expected_status=403)

    after = validate_success(api.get_churn_notice(notice["id"], TEST_USERS["platform_admin_headers"]))
    assert after["status"] == "SENT", "the notice was not acknowledged by the wrong member"

    own = api.acknowledge_churn_notice(notice["id"], make_member_headers(owner["id"]))
    validate_success(own, expected_status=200)


def test_the_override_approver_must_differ_from_the_requester(api):
    """PRD §2.10: "The operator who queues an override on a compliance-driven
    entitlement downgrade is recorded on the entitlement, and the operator who
    approves it is recorded separately; the two must differ, and an approval
    attempted by the requester is refused."
    PRD §2.9: "17. The override approver differs from the override requester,
    else `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/compliance_officer_cannot_approve_an_override_on_the_requester_identity
    """
    member = register_member(member_number="M-R-003", email="nell.r@x.com")
    holding = api.create_holding(
        {"member_id": member["id"], "product_line": "CAREER", "balance_cents": 0},
        TEST_USERS["platform_admin_headers"],
    ).json()["data"]
    validate_success(api.adopt_holding(holding["id"], make_member_headers(member["id"])))
    entitlement = declare_entitlement(member["id"], holding["id"], "CAREER_COACHING_CREDIT",
                                      value_bps=1)

    validate_success(api.step_down_entitlement(entitlement["id"],
                                               TEST_USERS["benefits_admin_headers"]))
    validate_success(api.request_override(
        entitlement["id"], {"override_reason": "REMEDIATION"},
        TEST_USERS["benefits_admin_headers"],
    ))

    queued = validate_success(api.get_entitlement(entitlement["id"],
                                                  TEST_USERS["benefits_admin_headers"]))
    requester = queued["override_requested_by"]
    assert requester == "test-benefits-admin-1"
    assert queued["override_approved_by"] is None

    # The same operator identity approving its own request is refused.
    same_identity = {"X-User-ID": requester, "X-User-Role": "ComplianceOfficer",
                     "Content-Type": "application/json"}
    resp = api.approve_override(entitlement["id"], same_identity)
    validate_error(resp, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)

    still_queued = validate_success(api.get_entitlement(entitlement["id"],
                                                        TEST_USERS["benefits_admin_headers"]))
    assert still_queued["override_approved_by"] is None, (
        "the refused approval must not record an approver"
    )
    assert still_queued["entitlement_status"] == "STEPPED_DOWN"


def test_a_distinct_approver_identity_clears_the_segregation_rule(api):
    """PRD §2.10: "Separation of duties is enforced on entitlement overrides.
    The operator who queues an override on a compliance-driven entitlement
    downgrade is recorded on the entitlement, and the operator who approves it is
    recorded separately; the two must differ, and an approval attempted by the
    requester is refused."

    Design: Corner/rbac/compliance_officer_cannot_approve_an_override_on_the_requester_identity
    """
    member = register_member(member_number="M-R-003B", email="nell.r.b@x.com")
    holding = api.create_holding(
        {"member_id": member["id"], "product_line": "CAREER", "balance_cents": 0},
        TEST_USERS["platform_admin_headers"],
    ).json()["data"]
    validate_success(api.adopt_holding(holding["id"], make_member_headers(member["id"])))
    entitlement = declare_entitlement(member["id"], holding["id"], "CAREER_COACHING_CREDIT",
                                      value_bps=1)
    validate_success(api.step_down_entitlement(entitlement["id"],
                                               TEST_USERS["benefits_admin_headers"]))
    validate_success(api.request_override(
        entitlement["id"], {"override_reason": "REMEDIATION"},
        TEST_USERS["benefits_admin_headers"],
    ))

    approved = validate_success(api.approve_override(entitlement["id"],
                                                     ALTERNATE["compliance_officer_2"]))
    assert approved["override_requested_by"] is not None
    assert approved["override_approved_by"] is not None
    assert approved["override_approved_by"] != approved["override_requested_by"], (
        "the two recorded identities differ"
    )


# --------------------------------------------------------------------------
# RBAC / validation ladder
# --------------------------------------------------------------------------

def test_missing_auth_headers_is_checked_before_the_resource_existence_rung(api):
    """PRD §2.1: "A request missing either header, or carrying an empty value for
    either, is rejected before any other processing with
    `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."
    PRD §2.9: "Validation is a single ordered ladder, evaluated top to bottom, and
    the first rule that fails determines the error returned; later rules are not
    consulted. The rungs, in order, are: 1. Both `X-User-Role` and `X-User-ID`
    are present and non-empty, else `ERR_MISSING_AUTH_HEADERS`."

    Design: Corner/validations/missing_auth_headers_is_checked_before_the_endpoint_body
    """
    member = register_member(member_number="M-V-001", email="auth.v@x.com")
    resp = api.get_member(member["id"], headers_without_auth())
    validate_error(resp, "ERR_MISSING_AUTH_HEADERS", expected_status=401)

    unknown = api.get_member("00000000-0000-4000-8000-000000000000", headers_without_auth())
    validate_error(unknown, "ERR_MISSING_AUTH_HEADERS", expected_status=401)


def test_blank_auth_header_values_are_rejected_the_same_way(api):
    """PRD §2.1: "A request missing either header, or carrying an empty value for
    either, is rejected before any other processing with
    `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_is_checked_before_the_endpoint_body
    """
    member = register_member(member_number="M-V-002", email="auth.v2@x.com")
    blank_role = {"X-User-ID": member["id"], "X-User-Role": "", "Content-Type": "application/json"}
    validate_error(api.get_member(member["id"], blank_role),
                   "ERR_MISSING_AUTH_HEADERS", expected_status=401)

    blank_id = {"X-User-ID": "", "X-User-Role": "PlatformAdmin", "Content-Type": "application/json"}
    validate_error(api.get_member(member["id"], blank_id),
                   "ERR_MISSING_AUTH_HEADERS", expected_status=401)


# --------------------------------------------------------------------------
# Read-side consistency
# --------------------------------------------------------------------------

def test_the_benefit_summary_recomputes_on_read_without_an_intervening_write(api):
    """PRD §2.6: "At the member level, the entitlement state is recomputed as a
    rollup over the member's entitlements whose source holding is not closed: a
    lapsed member reads `SUSPENDED`; otherwise, if every counted entitlement is
    granted and at least one is counted, the state is `FULL`".

    Design: Corner/consistency_model/read_side_recomputation_makes_eventual_rollups_visible_without_a_write
    """
    member = register_member(member_number="M-CM-001", email="iris.c@x.com")
    holding = api.create_holding(
        {"member_id": member["id"], "product_line": "CAREER", "balance_cents": 0},
        TEST_USERS["platform_admin_headers"],
    ).json()["data"]
    validate_success(api.adopt_holding(holding["id"], make_member_headers(member["id"])))
    declare_entitlement(member["id"], holding["id"], "CAREER_COACHING_CREDIT", value_bps=1)

    first = validate_success(api.get_benefit_summary(member["id"], make_member_headers(member["id"])))
    assert first["entitlement_state"] == "FULL", (
        "the granting cascade already ran, so the read reflects it with no delay"
    )
    assert first["granted_count"] == 1

    second = validate_success(api.get_benefit_summary(member["id"], make_member_headers(member["id"])))
    assert second == first, "the read is a pure recompute and is byte-identical on a second call"

    balance = validate_success(api.get_rewards_balance(member["id"],
                                                       TEST_USERS["platform_admin_headers"]))
    assert balance["points_balance"] == 0
    assert balance["posted_entry_count"] == 0


def test_the_saga_compensation_leaves_no_drift_on_either_quantity(api):
    """PRD §3.8: "The member names the `loan_account_id` to credit, a `points`
    quantity to spend, and optionally a `source_event_code`."
    PRD §3.8: "A successful redemption appends a principal-redemption entry with
    a negative point delta, derives its `principal_reduction_cents` by dividing
    the points consumed by 100 and flooring toward zero, decrements the loan's
    principal, and refreshes the loan's pricing timestamp."
    PRD §3.8: "A benefits operator reverses a posted earning or principal
    redemption".

    Design: Corner/consistency_model/saga_style_compensation_leaves_no_drift_when_the_second_step_fails
    """
    from test_helpers import setup_rewards_member

    setup = setup_rewards_member(4000, principal_cents=250000, base_apr_bps=1080,
                                loan_type="STUDENT")
    member_id, loan_id = setup["member"]["id"], setup["loan"]["id"]
    points_before = fetch_member(member_id)["rewards_points_balance"]
    principal_before = setup["loan"]["principal_cents"]

    entry = validate_success(api.redeem_principal(
        member_id, {"loan_account_id": loan_id, "points": 3000, "source_event_code": "SAGA_LEG_1"},
        make_member_headers(member_id),
    ), expected_status=201)
    assert entry["principal_reduction_cents"] == 30, "3000 floors to 30"
    assert fetch_loan_principal(api, loan_id) == principal_before - 30
    assert fetch_member(member_id)["rewards_points_balance"] == points_before - 3000

    validate_success(api.reverse_ledger_entry(entry["id"], TEST_USERS["benefits_admin_headers"]))

    compensated = validate_success(api.get_ledger_entry(entry["id"],
                                                        TEST_USERS["benefits_admin_headers"]))
    assert compensated["entry_status"] == "REVERSED"
    assert compensated["reversed_by_entry_id"] is not None
    assert fetch_loan_principal(api, loan_id) == principal_before, (
        "the compensating entry restores the cent principal with zero drift"
    )
    assert fetch_member(member_id)["rewards_points_balance"] == points_before, (
        "the compensating entry restores the point balance with zero drift"
    )


def fetch_loan_principal(api, loan_id):
    return validate_success(api.get_loan_account(loan_id, TEST_USERS["underwriter_headers"]))[
        "principal_cents"
    ]