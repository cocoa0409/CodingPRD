"""Direct-deposit qualification, the grace cycle, churn scoring and notices."""
from test_helpers import (
    TEST_USERS,
    assert_churn_notice,
    assert_deposit_enrollment,
    create_active_enrollment,
    create_adopted_holding,
    detect_churn,
    enrollment_in_grace,
    fetch_enrollment,
    list_notices,
    make_member_headers,
    post_deposit,
    register_member,
    set_clock,
    validate_error,
    validate_success,
)


def test_enrollment_activation_stamps_the_qualification_instants(api):
    """PRD §2.6: "`qualified_at` is stamped when the enrolment first becomes
    active, `last_deposit_at` records the most recent posted deposit of any
    amount, and `grace_deadline_at` is set when the enrolment enters grace. The
    computed `consecutive_qualifying_months` counts the maximal trailing run of
    consecutive calendar months, ending at the logical month containing the
    current logical instant, in which the enrolment's posted deposits met
    `required_monthly_amount_cents`."

    Design: Difficulty/non_linear_state_machine/direct_deposit_enrollment_grace_recovery_cycle
    """
    set_clock()
    member = register_member(member_number="M-3061-006", email="fay.c@x.com")
    holding = create_adopted_holding(member["id"], "BANKING", 250000)
    enrollment = create_active_enrollment(
        member["id"], required_monthly_amount_cents=100000,
        amount_cents=200000, posted_at="2026-09-01T00:00:00Z",
        holding_id=holding["id"],
    )
    assert_deposit_enrollment(enrollment)
    assert enrollment["status"] == "ACTIVE", "activation turns a verified enrolment into a qualifying one"
    assert enrollment["qualified_at"] == "2026-09-01T00:00:00Z"
    assert enrollment["missed_cycle_count"] == 0
    assert enrollment["consecutive_qualifying_months"] == 1


def test_grace_recovery_returns_the_enrollment_to_active(api):
    """PRD §3.3: "While the enrolment sits in grace, a fresh qualifying deposit
    posted before `grace_deadline_at` returns it to `ACTIVE`, resets
    `missed_cycle_count`, recomputes `consecutive_qualifying_months`, restores
    every `PENDING_REQUALIFICATION` direct-deposit entitlement to `GRANTED`, and
    swaps any queued rate-step-down notice for a rate-step-up notice."

    Design: Difficulty/non_linear_state_machine/direct_deposit_enrollment_grace_recovery_cycle
    """
    set_clock()
    member = register_member(member_number="M-3061-006B", email="fay.c.b@x.com")
    holding = create_adopted_holding(member["id"], "BANKING", 250000)
    grace = enrollment_in_grace(member["id"], holding["id"], required_monthly_amount_cents=100000)
    assert grace["status"] == "GRACE"
    assert grace["missed_cycle_count"] >= 1
    assert grace["grace_deadline_at"] is not None

    # A fresh qualifying posting inside the grace window returns it to ACTIVE.
    post_deposit(member["id"], grace["id"], 200000, "2026-11-05T00:00:00Z",
                 holding_id=holding["id"])
    recovered = fetch_enrollment(grace["id"])
    assert recovered["status"] == "ACTIVE", (
        "the machine revisits ACTIVE by the deposit-recovery path, not only by activation"
    )
    assert recovered["missed_cycle_count"] == 0


def test_lapsing_from_grace_before_the_deadline_is_refused(api):
    """PRD §3.3: "If instead the grace deadline passes and an operator attempts
    to lapse the enrolment from `GRACE` before that deadline, the attempt is
    refused with `ERR_GRACE_PERIOD_NOT_ELAPSED`; once the deadline has passed the
    lapse succeeds, moving the enrolment to `LAPSED`."

    Design: Corner/state_machines/grace_lapse_without_elapsed_deadline_returns_grace_period_not_elapsed
    """
    set_clock()
    member = register_member(member_number="M-S-005", email="hiro.c@x.com")
    holding = create_adopted_holding(member["id"], "BANKING", 400000)
    enrollment = api.create_deposit_enrollment(
        {"member_id": member["id"], "required_monthly_amount_cents": 100000},
        TEST_USERS["platform_admin_headers"],
    ).json()["data"]
    post_deposit(member["id"], enrollment["id"], 150000, "2026-09-01T00:00:00Z",
                 holding_id=holding["id"])
    validate_success(api.activate_enrollment(enrollment["id"], TEST_USERS["platform_admin_headers"]))

    # One complete unposted month, so the ACTIVE -> GRACE transition is admitted.
    set_clock("2026-11-01T00:00:00Z")
    grace = validate_success(api.lapse_enrollment(enrollment["id"], TEST_USERS["platform_admin_headers"]))
    assert grace["status"] == "GRACE"
    deadline = grace["grace_deadline_at"]
    assert deadline is not None

    # Still inside the grace window: the lapse is refused on the clock.
    resp = api.lapse_enrollment(enrollment["id"], TEST_USERS["platform_admin_headers"])
    validate_error(resp, "ERR_GRACE_PERIOD_NOT_ELAPSED", expected_status=409)

    still_grace = fetch_enrollment(enrollment["id"])
    assert still_grace["status"] == "GRACE", "the refused lapse must leave the enrolment in grace"

    # Past the deadline the same call succeeds.
    set_clock("2027-06-01T00:00:00Z")
    lapsed = validate_success(api.lapse_enrollment(enrollment["id"], TEST_USERS["platform_admin_headers"]))
    assert lapsed["status"] == "LAPSED"


def test_entering_the_at_risk_state_queues_a_rate_step_down_notice(api):
    """PRD §3.7: "Entering `MEMBER_AT_RISK` queues a rate-step-down notice with a
    deposit-stopped reason."

    Design: Difficulty/non_linear_state_machine/member_status_cycle_prospect_lapsed_back_to_prospect
    """
    set_clock()
    member = register_member(member_number="M-CYC-005D", email="eli.cyc.d@x.com")
    create_adopted_holding(member["id"], "INVESTING", 0)
    grace = enrollment_in_grace(member["id"])

    at_risk = detect_churn(member["id"])
    assert at_risk["member_status"] in ("MEMBER_AT_RISK", "MEMBER_LAPSED"), (
        f"a GRACE enrolment contributes 40 points; score was {at_risk['churn_risk_score']}"
    )
    notices = list_notices(member["id"], status="QUEUED", notice_type="RATE_STEP_DOWN")
    assert notices, "entering the at-risk state must queue a RATE_STEP_DOWN notice"
    notice = notices[0]
    assert_churn_notice(notice)
    assert notice["member_id"] == member["id"]
    assert grace["id"]  # the grace enrolment is the premise of the notice


def test_a_queued_rate_step_down_notice_is_voided_by_recovery(api):
    """PRD §3.7: "A queued rate-step-down notice is moved to `VOIDED`
    automatically once the member's direct-deposit entitlement is granted again
    — the rate having been restored before the notice ever went out."

    Design: Corner/state_machines/queued_rate_step_down_notice_is_voided_when_activation_restores_the_rate
    """
    set_clock()
    member = register_member(member_number="M-S-009", email="lars.c@x.com")
    holding = create_adopted_holding(member["id"], "BANKING", 300000)
    enrollment = api.create_deposit_enrollment(
        {"member_id": member["id"], "required_monthly_amount_cents": 100000},
        TEST_USERS["platform_admin_headers"],
    ).json()["data"]
    entitlement = validate_success(api.create_entitlement(
        member["id"],
        {"source_holding_id": holding["id"], "benefit_code": "DIRECT_DEPOSIT", "value_bps": 50},
        TEST_USERS["benefits_admin_headers"],
    ), expected_status=201)
    post_deposit(member["id"], enrollment["id"], 200000, "2026-09-01T00:00:00Z",
                 holding_id=holding["id"])
    validate_success(api.activate_enrollment(enrollment["id"], TEST_USERS["platform_admin_headers"]))
    assert fetch_enrollment(enrollment["id"])["status"] == "ACTIVE"

    # Lapse all the way: the DEPOSIT_RATE_BOOST entitlement is stepped down.
    set_clock("2026-11-01T00:00:00Z")
    validate_success(api.lapse_enrollment(enrollment["id"], TEST_USERS["platform_admin_headers"]))
    set_clock("2027-01-01T00:00:00Z")
    lapsed = validate_success(api.lapse_enrollment(enrollment["id"], TEST_USERS["platform_admin_headers"]))
    assert lapsed["status"] == "LAPSED"
    stepped = validate_success(api.get_entitlement(entitlement["id"],
                                                   TEST_USERS["benefits_admin_headers"]))
    assert stepped["entitlement_status"] in ("STEPPED_DOWN", "PENDING_REQUALIFICATION"), (
        "a lapse steps the direct-deposit entitlement down"
    )

    queued_before = list_notices(member["id"], status="QUEUED", notice_type="RATE_STEP_DOWN")
    assert queued_before, "the lapse must queue a RATE_STEP_DOWN notice"

    # A fresh qualifying posting then re-activates the enrolment. The clock is
    # advanced to the posting instant first: a posting dated in the future cannot
    # qualify, because the platform only counts deposits that have already posted.
    set_clock("2027-01-02T00:00:00Z")
    post_deposit(member["id"], enrollment["id"], 250000, "2027-01-02T00:00:00Z",
                 holding_id=holding["id"])
    validate_success(api.activate_enrollment(enrollment["id"], TEST_USERS["platform_admin_headers"]))

    assert fetch_enrollment(enrollment["id"])["status"] == "ACTIVE"
    restored = validate_success(api.get_entitlement(entitlement["id"],
                                                    TEST_USERS["benefits_admin_headers"]))
    assert restored["entitlement_status"] == "GRANTED"
    assert restored["value_bps"] == 50, "value_bps is restored to the full magnitude"

    queued_after = list_notices(member["id"], status="QUEUED", notice_type="RATE_STEP_DOWN")
    assert queued_after == [], (
        "the queued rate-step-down notice is VOIDED once the direct-deposit entitlement is granted again"
    )
    voided = list_notices(member["id"], status="VOIDED")
    assert voided, "the notice is retained in the VOIDED terminal state"


def test_sending_a_queued_notice_then_acknowledging_it_completes_the_lifecycle(api):
    """PRD §3.7: "An administrator dispatches a queued notice once the current
    instant has reached its `issued_at`, moving it to `SENT`; the owning member
    then acknowledges a sent notice, moving it to `ACKNOWLEDGED`."

    Design: Corner/endpoints/churn_notice_send_is_conditional_on_the_clock_passing_issue_time
    """
    set_clock()
    member = register_member(member_number="M-E-003", email="gia.c@x.com")
    holding = create_adopted_holding(member["id"], "BANKING", 200000)
    enrollment = api.create_deposit_enrollment(
        {"member_id": member["id"], "required_monthly_amount_cents": 100000},
        TEST_USERS["platform_admin_headers"],
    ).json()["data"]
    post_deposit(member["id"], enrollment["id"], 200000, "2026-09-01T00:00:00Z",
                 holding_id=holding["id"])
    validate_success(api.activate_enrollment(enrollment["id"], TEST_USERS["platform_admin_headers"]))
    set_clock("2026-11-01T00:00:00Z")
    validate_success(api.lapse_enrollment(enrollment["id"], TEST_USERS["platform_admin_headers"]))

    queued = list_notices(member["id"], status="QUEUED")
    assert queued, "the grace transition queues a requalification reminder"
    notice = queued[0]
    assert notice["issued_at"] is not None
    assert notice["effective_at"] is not None

    sent = validate_success(api.send_churn_notice(notice["id"], TEST_USERS["platform_admin_headers"]))
    assert sent["status"] == "SENT"

    acknowledged = validate_success(
        api.acknowledge_churn_notice(notice["id"], make_member_headers(member["id"]))
    )
    assert acknowledged["status"] == "ACKNOWLEDGED", (
        "ACKNOWLEDGED is a terminal notice state reached only from SENT"
    )


def test_acknowledging_a_still_queued_notice_is_refused(api):
    """PRD §3.7: "An administrator dispatches a queued notice once the current
    instant has reached its `issued_at`, moving it to `SENT`; the owning member
    then acknowledges a sent notice, moving it to `ACKNOWLEDGED`."
    PRD §2.9: "6. The target resource is in a state that permits the requested
    transition, else `ERR_INVALID_STATE`; this applies to every state-transition
    operation."

    Design: Corner/state_machines/churn_notice_acknowledge_from_queued_returns_invalid_state
    """
    set_clock()
    member = register_member(member_number="M-S-008A", email="kira.c@x.com")
    holding = create_adopted_holding(member["id"], "INVESTING", 0)
    enrollment = api.create_deposit_enrollment(
        {"member_id": member["id"], "required_monthly_amount_cents": 100000},
        TEST_USERS["platform_admin_headers"],
    ).json()["data"]
    post_deposit(member["id"], enrollment["id"], 200000, "2026-09-01T00:00:00Z")
    validate_success(api.activate_enrollment(enrollment["id"], TEST_USERS["platform_admin_headers"]))
    set_clock("2026-11-01T00:00:00Z")
    validate_success(api.lapse_enrollment(enrollment["id"], TEST_USERS["platform_admin_headers"]))

    queued = list_notices(member["id"], status="QUEUED")
    assert queued
    notice_id = queued[0]["id"]

    resp = api.acknowledge_churn_notice(notice_id, make_member_headers(member["id"]))
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)
    assert fetch_enrollment(enrollment["id"])["status"] == "GRACE"
    assert holding["id"]  # the holding is the premise of the enrolment setup

    # The send path still works from the same row, so the refusal was state, not identity.
    validate_success(api.send_churn_notice(notice_id, TEST_USERS["platform_admin_headers"]))