"""Seat management: the seats_used conservation invariant, capacity and
held-seat gates, FirmAdmin ownership, the state-before-fiscal priority pair,
and immediate read-your-write consistency (PRD §2.1, §2.2, §3.4, §3.5)."""
from test_helpers import (
    CLOCK_SEP_05,
    ApiErrorId,
    assign_seat,
    create_account,
    create_headnote,
    create_plan,
    create_published_document,
    create_subscription,
    get_subscription,
    get_user,
    list_users,
    make_attorney_editor_headers,
    make_firm_admin_headers,
    release_seat,
    set_clock,
    setup_subscribed_user,
    submit_headnote,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

_LICENSING = TEST_USERS["licensing_manager_headers"]


def test_assign_increments_seats_used(api):
    """PRD §3.4: "`seats_used` is never written directly but is always the count of
    SubscriberUser rows holding an `ACTIVE` seat on the subscription."
    PRD §3.5: "the user is created already holding an `ACTIVE` seat, its
    `seat_subscription_id` pointing at that subscription, and the subscription's
    `seats_used` rising by one."

    Design: Difficulty/compensating_invariant/seat_assign_release_conserves_seats_used
    """
    set_clock(CLOCK_SEP_05)
    plan = create_plan(name="Seat Plan")
    account = create_account(org_name="Seat Firm")
    subscription = create_subscription(account["id"], plan["id"], seats_total=2)
    assert get_subscription(subscription["id"])["seats_used"] == 0

    user = assign_seat(subscription["id"], account["id"], email="s1@seat.com", full_name="Seat One")
    after = get_subscription(subscription["id"])
    assert after["seats_used"] == 1
    seated = list_users(seat_subscription_id=subscription["id"])
    assert len(seated) == 1 and seated[0]["id"] == user["id"]
    assert seated[0]["seat_status"] == "ACTIVE"


def test_release_returns_seats_used_to_baseline(api):
    """PRD §3.5: "Release sets the user's `seat_status` to `NONE`, clears
    `seat_subscription_id` to null, and lowers `seats_used` by one."
    PRD §3.4: "`seats_used` is never written directly but is always the count of
    SubscriberUser rows holding an `ACTIVE` seat on the subscription."

    Design: Difficulty/compensating_invariant/seat_assign_release_conserves_seats_used
    """
    set_clock(CLOCK_SEP_05)
    plan = create_plan(name="Seat Plan")
    account = create_account(org_name="Seat Firm")
    subscription = create_subscription(account["id"], plan["id"], seats_total=2)
    user = assign_seat(subscription["id"], account["id"], email="s1@seat.com", full_name="Seat One")
    assert get_subscription(subscription["id"])["seats_used"] == 1

    release_seat(subscription["id"], account["id"], user["id"])
    after = get_subscription(subscription["id"])
    assert after["seats_used"] == 0, "seats_used returns to its exact pre-ASSIGN baseline"
    released = get_user(user["id"])
    assert released["seat_status"] == "NONE"
    assert released["seat_subscription_id"] is None
    assert list_users(seat_subscription_id=subscription["id"]) == []


def test_seat_assign_full_subscription_rejected(api):
    """PRD §3.5: "and only after every state and safety gate has passed does the
    capacity check fire — when `seats_used` has already reached `seats_total`, the
    assignment is rejected with `ERR_NO_SEATS_AVAILABLE` (HTTP 409)."

    Design: Corner/validations/seat_assign_full_subscription_rejected
    """
    set_clock(CLOCK_SEP_05)
    ctx = setup_subscribed_user(plan_overrides={"name": "Full Plan"}, seats_total=1,
                                user_email="a@full.com")
    sub_id = ctx["subscription"]["id"]
    account_id = ctx["account"]["id"]
    resp = api.manage_seats(
        sub_id,
        {"action": "ASSIGN", "user_email": "b@full.com", "user_full_name": "B"},
        make_firm_admin_headers(account_id),
    )
    validate_error(resp, ApiErrorId.ERR_NO_SEATS_AVAILABLE, 409)
    assert get_subscription(sub_id)["seats_used"] == 1


def test_release_without_held_seat_rejected(api):
    """PRD §3.5: "Releasing a seat is the mirror: the request names the `user_id` of
    an existing user (an unknown id fails with `ERR_USER_NOT_FOUND`, HTTP 404)
    whose `seat_status` must be `ACTIVE` on this very subscription, else
    `ERR_NO_SEAT_HELD` (HTTP 409)."

    Design: Corner/validations/release_without_held_seat_rejected
    """
    set_clock(CLOCK_SEP_05)
    ctx = setup_subscribed_user(plan_overrides={"name": "Rel Plan"}, seats_total=2,
                                user_email="r@rel.com")
    sub_id = ctx["subscription"]["id"]
    account_id = ctx["account"]["id"]
    user_id = ctx["user"]["id"]
    release_seat(sub_id, account_id, user_id)

    resp = api.manage_seats(
        sub_id, {"action": "RELEASE", "user_id": user_id}, make_firm_admin_headers(account_id),
    )
    validate_error(resp, ApiErrorId.ERR_NO_SEAT_HELD, 409)


def test_firm_admin_cannot_touch_other_account_seats(api):
    """PRD §2.1: "When `X-User-Role` is `FirmAdmin`, `X-User-ID` is the `id` of the
    acting SubscriberAccount; ownership checks on any resource that references a
    SubscriberAccount compare the resource's account field to `X-User-ID`, and a
    mismatch is rejected with `ERR_ACCOUNT_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/firm_admin_cannot_touch_other_account_seats
    """
    set_clock(CLOCK_SEP_05)
    plan = create_plan(name="Own Plan")
    owner = create_account(org_name="Owner Co")
    stranger = create_account(org_name="Stranger Co")
    subscription = create_subscription(owner["id"], plan["id"], seats_total=2)

    resp = api.manage_seats(
        subscription["id"],
        {"action": "ASSIGN", "user_email": "x@stranger.com", "user_full_name": "X"},
        make_firm_admin_headers(stranger["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_MISMATCH, 403)
    assert list_users(account_id=owner["id"]) == [], "no user created under the victim account"


def test_suspended_seat_assign_reports_state_not_fiscal(api):
    """PRD §2.9: "Referential rules follow (`ERR_MATTER_CODE_REQUIRED`, then
    `ERR_PLAN_ACCOUNT_INCOMPATIBLE`), and the fiscal seat-capacity check
    (`ERR_NO_SEATS_AVAILABLE`) is always the final gate, evaluated only after every
    state and safety check has passed."
    PRD §3.5: "the subscription must be `ACTIVE` (`ERR_SUBSCRIPTION_NOT_ACTIVE`,
    HTTP 409)"

    Design: Difficulty/priority_pair_validation_conflict/seat_assign_state_precedes_fiscal
    """
    set_clock(CLOCK_SEP_05)
    ctx = setup_subscribed_user(plan_overrides={"name": "Prio Plan"}, seats_total=1,
                                user_email="a@prio.com")
    sub_id = ctx["subscription"]["id"]
    account_id = ctx["account"]["id"]
    validate_success(
        api.transition_subscription(sub_id, {"target_status": "SUSPENDED"}, _LICENSING), 200
    )
    # Both violations now hold: subscription SUSPENDED and seats_used == seats_total.
    resp = api.manage_seats(
        sub_id,
        {"action": "ASSIGN", "user_email": "b@prio.com", "user_full_name": "User B"},
        make_firm_admin_headers(account_id),
    )
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE, 409)


def test_suspended_seat_assign_mutates_nothing(api):
    """PRD §2.9: "Referential rules follow (`ERR_MATTER_CODE_REQUIRED`, then
    `ERR_PLAN_ACCOUNT_INCOMPATIBLE`), and the fiscal seat-capacity check
    (`ERR_NO_SEATS_AVAILABLE`) is always the final gate, evaluated only after every
    state and safety check has passed."
    PRD §3.5: "the subscription must be `ACTIVE` (`ERR_SUBSCRIPTION_NOT_ACTIVE`,
    HTTP 409)"

    Design: Difficulty/priority_pair_validation_conflict/seat_assign_state_precedes_fiscal
    """
    set_clock(CLOCK_SEP_05)
    ctx = setup_subscribed_user(plan_overrides={"name": "Prio Plan"}, seats_total=1,
                                user_email="a@prio.com")
    sub_id = ctx["subscription"]["id"]
    account_id = ctx["account"]["id"]
    validate_success(
        api.transition_subscription(sub_id, {"target_status": "SUSPENDED"}, _LICENSING), 200
    )
    version_before = get_subscription(sub_id)["version"]

    resp = api.manage_seats(
        sub_id,
        {"action": "ASSIGN", "user_email": "b@prio.com", "user_full_name": "User B"},
        make_firm_admin_headers(account_id),
    )
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE, 409)
    after = get_subscription(sub_id)
    assert after["seats_used"] == 1
    assert after["status"] == "SUSPENDED"
    assert after["version"] == version_before
    assert len(list_users(account_id=account_id)) == 1


def test_mutation_visible_immediately_in_same_response(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data field."
    PRD §3.5: "the user is created already holding an `ACTIVE` seat, its
    `seat_subscription_id` pointing at that subscription, and the subscription's
    `seats_used` rising by one."

    Design: Corner/consistency/mutation_visible_immediately_in_same_response
    """
    set_clock(CLOCK_SEP_05)
    plan = create_plan(name="Imm2 Plan")
    account = create_account(org_name="Imm2 Co")
    subscription = create_subscription(account["id"], plan["id"], seats_total=2)
    doc = create_published_document(
        title="Imm v. Read", raw_citation_string="100 P.3d 8", jurisdiction_code="ID",
    )
    headnote = create_headnote(doc["id"], "ed-author-1", topic_code="FAMILY")
    submit_headnote(headnote["id"], "ed-author-1")

    assign_resp = api.manage_seats(
        subscription["id"],
        {"action": "ASSIGN", "user_email": "i2@imm.com", "user_full_name": "I2"},
        make_firm_admin_headers(account["id"]),
    )
    assign_data = validate_success(assign_resp, 200)
    assert assign_data["seats_used"] == 1, (
        "the ASSIGN response itself carries the recomputed seats_used"
    )

    decide_resp = api.decide_headnote(
        headnote["id"], {"decision": "APPROVE", "review_note": "ok"},
        make_attorney_editor_headers("ed-reviewer-2"),
    )
    decide_data = validate_success(decide_resp, 200)
    assert decide_data["status"] == "PUBLISHED"
    assert decide_data["reviewer_editor_id"] == "ed-reviewer-2"
