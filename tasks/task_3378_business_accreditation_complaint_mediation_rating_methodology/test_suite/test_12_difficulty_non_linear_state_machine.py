"""Difficulty queue — non-linear state machines: the Complaint rebuttal
cycle with its hard cap (PRD §3.4) and the Business's two parallel status
dimensions evolving independently (PRD §3.1, §3.7)."""

from test_helpers import (
    ApiErrorId,
    CLOCK_START_ISO,
    TEST_USERS,
    accept_mediation,
    business_respond,
    complaint_response_payload,
    compute_snapshot,
    conclude_advertising_review,
    conclude_mediation_case,
    consumer_accept,
    consumer_rebuttal,
    consumer_reject,
    create_bureau,
    create_business,
    create_consumer,
    create_rating_snapshot_payload,
    file_and_forward_complaint,
    get_business,
    get_complaint,
    make_business_rep_headers,
    make_consumer_headers,
    offer_mediation,
    open_advertising_review,
    reopen_complaint,
    run_daily_close,
    schedule_mediation_session,
    set_clock,
    setup_accredited_business,
    setup_world,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["bureau_admin_headers"]
REVIEWER = TEST_USERS["standards_reviewer_headers"]


def _setup_rebuttal_cap():
    """One complaint driven through three full response/rebuttal rounds and a
    final business answer: RESPONSE_RECEIVED with rebuttal_count == 3."""
    set_clock(CLOCK_START_ISO)
    create_bureau(name="Heartland Bureau", territory_state_codes=["IA", "NE"],
                  local_dues_fee_cents=0)
    consumer = create_consumer(full_name="Pat Consumer",
                               email="pat@example.com", home_state_code="IA")
    business = create_business(legal_name="BigBox Services Inc",
                               home_state_code="IA", employee_count=250,
                               founded_on="2018-01-01T00:00:00Z")
    complaint = file_and_forward_complaint(consumer, business,
                                           category="SERVICE",
                                           description="rebuttal loop")
    for round_no in (1, 2, 3):
        complaint = business_respond(complaint, business,
                                     body=f"round {round_no} answer")
        complaint = consumer_rebuttal(complaint, consumer,
                                      body=f"rebuttal {round_no}")
    complaint = business_respond(complaint, business, body="final answer")
    return consumer, business, complaint


class TestComplaintRebuttalCycle:
    def test_three_full_cycles_complete(self, api):
        """PRD §3.4: "A response of `kind` `CONSUMER_REBUTTAL` returns the
        complaint from `RESPONSE_RECEIVED` to `CONSUMER_REBUTTED` and
        increments `rebuttal_count`; a complaint admits at most 3 consumer
        rebuttals, and a fourth attempt is rejected with
        `ERR_REBUTTAL_LIMIT_REACHED`."

        Design: Difficulty/non_linear_state_machine/complaint_rebuttal_cycle_loops_until_cap_three
        """
        _consumer, _business, complaint = _setup_rebuttal_cap()
        current = get_complaint(complaint["id"])
        assert current["status"] == "RESPONSE_RECEIVED"
        assert current["rebuttal_count"] == 3
        kinds = [entry["kind"] for entry in current["responses"]]
        assert kinds == ["BUSINESS_RESPONSE", "CONSUMER_REBUTTAL"] * 3 + \
            ["BUSINESS_RESPONSE"]

    def test_fourth_rebuttal_rejected_without_state_drift(self, api):
        """PRD §3.4: "a complaint admits at most 3 consumer rebuttals, and a
        fourth attempt is rejected with `ERR_REBUTTAL_LIMIT_REACHED`."

        Design: Difficulty/non_linear_state_machine/complaint_rebuttal_cycle_loops_until_cap_three
        """
        consumer, _business, complaint = _setup_rebuttal_cap()
        resp = api.add_complaint_response(
            complaint["id"],
            complaint_response_payload(kind="CONSUMER_REBUTTAL",
                                       body="rebuttal 4"),
            make_consumer_headers(consumer["id"]))
        validate_error(resp, ApiErrorId.ERR_REBUTTAL_LIMIT_REACHED)
        current = get_complaint(complaint["id"])
        assert current["status"] == "RESPONSE_RECEIVED"
        assert current["rebuttal_count"] == 3
        assert len(current["responses"]) == 7


def _setup_suspended_under_review(api):
    """ACCREDITED MEDIUM business, one open advertising review, then a
    PUBLISHED 67 (unanswered 12 + unresolved 16 + advertising 5) whose sweep
    suspends accreditation while the ad review stays open."""
    world = setup_world(business_overrides={
        "legal_name": "MidSize Manufacturing LLC", "employee_count": 50,
        "founded_on": "2020-01-01T00:00:00Z"})
    bureau, consumer = world["bureau"], world["consumer"]
    accredited = setup_accredited_business(world=world)
    business = accredited["business"]
    review = open_advertising_review(
        business, claim_description="claims #1 in USA without substantiation",
        as_reviewer=True)
    # c3 lapses unanswered at the 2026-09-16 sweep.
    c3 = file_and_forward_complaint(consumer, business, category="DELIVERY",
                                    description="c3 expires")
    set_clock("2026-09-16T00:00:00Z")
    run_daily_close(bureau["id"])
    # c2 and c1 are answered then rejected: UNRESOLVED.
    c2 = file_and_forward_complaint(consumer, business, category="BILLING",
                                    description="c2 rejected")
    c2 = business_respond(c2, business, body="answer 2")
    consumer_reject(c2, consumer, body="no")
    c1 = file_and_forward_complaint(consumer, business, category="WARRANTY",
                                    description="c1 rejected")
    c1 = business_respond(c1, business, body="answer 1")
    consumer_reject(c1, consumer, body="no")
    resp = api.create_rating_snapshot(
        business["id"], create_rating_snapshot_payload("PUBLISHED"), ADMIN)
    published_low = validate_success(resp, 201)
    run_daily_close(bureau["id"])
    return bureau, consumer, business, review, c1, c2, c3, published_low


class TestBusinessParallelDimensions:
    def test_suspension_holds_while_advertising_review_stays_open(self, api):
        """PRD §3.1: "These are parallel dimensions recorded on the same row:
        each evolves under its own rules, and a transition on one never reads
        or writes the other except where this document explicitly says so."
        PRD §3.7: "An `ACCREDITED` business whose latest published score is
        below 75 is suspended: `accreditation_status` becomes `SUSPENDED`,
        `suspension_count_24m` increments by 1, `last_suspension_at` is
        stamped, and the business's `version` increments by 1."

        Design: Difficulty/non_linear_state_machine/business_parallel_dimensions_move_independently
        """
        (bureau, _consumer, business, review, _c1, _c2, _c3,
         published_low) = _setup_suspended_under_review(api)
        assert published_low["score"] == 67  # 12 + 16 + 5
        assert published_low["grade"] == "C"  # PRD §3.6 floors: 67 -> C
        suspended = get_business(business["id"])
        assert suspended["accreditation_status"] == "SUSPENDED"
        assert suspended["suspension_count_24m"] == 1
        assert suspended["advertising_compliance_status"] == "UNDER_AD_REVIEW"
        # The advertising dimension moves alone: accreditation is untouched.
        conclude_advertising_review(review, outcome="CLEARED")
        after = get_business(business["id"])
        assert after["advertising_compliance_status"] == "CLEAR"
        assert after["accreditation_status"] == "SUSPENDED"

    def test_reinstatement_leaves_advertising_and_count_untouched(self, api):
        """PRD §3.7: "A `SUSPENDED` business whose latest published score is
        80 or higher is reinstated to `ACCREDITED`, its `version`
        incrementing."
        PRD §3.1: "These are parallel dimensions recorded on the same row:
        each evolves under its own rules, and a transition on one never reads
        or writes the other except where this document explicitly says so."

        Design: Difficulty/non_linear_state_machine/business_parallel_dimensions_move_independently
        """
        (bureau, consumer, business, review, c1, c2, c3,
         _published_low) = _setup_suspended_under_review(api)
        conclude_advertising_review(review, outcome="CLEARED")
        # Clean up every complaint: reopen and resolve c3; mediate c1/c2.
        c3 = reopen_complaint(c3)
        c3 = business_respond(c3, business, body="now we answer")
        consumer_accept(c3, consumer, body="resolved")
        for complaint, start, end in (
                (c1, "2026-09-21T10:00:00Z", "2026-09-21T11:00:00Z"),
                (c2, "2026-09-21T13:00:00Z", "2026-09-21T14:00:00Z")):
            case = offer_mediation(complaint)
            case = accept_mediation(case, business, consumer)
            case = schedule_mediation_session(
                case, mediator_id="med-1", session_start_at=start,
                session_end_at=end)
            conclude_mediation_case(case, outcome="AGREEMENT")
        published_high = compute_snapshot(business, variant="PUBLISHED")
        assert published_high["score"] == 100
        assert published_high["grade"] == "A_PLUS"
        run_daily_close(bureau["id"])
        reinstated = get_business(business["id"])
        assert reinstated["accreditation_status"] == "ACCREDITED"
        assert reinstated["advertising_compliance_status"] == "CLEAR"
        assert reinstated["suspension_count_24m"] == 1, \
            "reinstatement does not decrement the trailing suspension count"
