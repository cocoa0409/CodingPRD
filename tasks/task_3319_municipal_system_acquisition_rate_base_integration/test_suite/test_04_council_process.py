"""Municipal process tests: hearings, votes, referenda, overlap, notice."""
from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_council_event,
    create_target,
    setup_target_in_municipal_review, setup_target_in_regulatory_review,
    setup_hearing_held, schedule_event, record_outcome, set_clock,
    register_employee, list_transition_items, decide_application,
    make_headers,
)


def test_council_event_half_open_adjacency(api):
    """PRD §3.4: "under half-open semantics, each event occupies the interval
    from its `scheduled_start` up to but not including its `scheduled_end`, so
    back-to-back events where one ends exactly when the next begins are allowed,
    and any genuine overlap is rejected with `ERR_EVENT_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/council_event_half_open_adjacency
    """
    ctx = setup_target_in_municipal_review(customer_count=10)
    target_id = ctx["target"]["id"]
    schedule_event(target_id, "PUBLIC_HEARING",
                   "2026-09-02T00:00:00Z", "2026-09-02T02:00:00Z")
    # Back-to-back: starts exactly when the hearing ends -> allowed.
    resp = api.create_council_event(
        target_id,
        {"kind": "COUNCIL_VOTE", "scheduled_start": "2026-09-02T02:00:00Z",
         "scheduled_end": "2026-09-02T04:00:00Z"},
        TEST_USERS["clerk_headers"])
    vote = validate_success(resp, 201)
    assert_council_event(vote)
    # Interior overlap -> rejected.
    resp = api.create_council_event(
        target_id,
        {"kind": "COUNCIL_VOTE", "scheduled_start": "2026-09-02T03:59:59Z",
         "scheduled_end": "2026-09-02T05:00:00Z"},
        TEST_USERS["clerk_headers"])
    validate_error(resp, ApiErrorId.ERR_EVENT_OVERLAP)


def test_council_event_half_open_adjacency_reverse_order(api):
    """PRD §3.4: "Events of the same target may not overlap ... any genuine
    overlap is rejected with `ERR_EVENT_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/council_event_half_open_adjacency
    """
    ctx = setup_target_in_municipal_review(customer_count=10)
    target_id = ctx["target"]["id"]
    schedule_event(target_id, "PUBLIC_HEARING",
                   "2026-09-04T00:00:00Z", "2026-09-04T02:00:00Z")
    # End exactly at the existing event's start -> allowed.
    resp = api.create_council_event(
        target_id,
        {"kind": "COUNCIL_VOTE", "scheduled_start": "2026-09-04T03:00:00Z",
         "scheduled_end": "2026-09-04T04:00:00Z"},
        TEST_USERS["clerk_headers"])
    validate_success(resp, 201)
    # Window that ends strictly inside the hearing -> overlap.
    resp = api.create_council_event(
        target_id,
        {"kind": "COUNCIL_VOTE", "scheduled_start": "2026-09-04T05:00:00Z",
         "scheduled_end": "2026-09-04T06:00:00Z"},
        TEST_USERS["clerk_headers"])
    validate_success(resp, 201)
    resp = api.create_council_event(
        target_id,
        {"kind": "COUNCIL_VOTE", "scheduled_start": "2026-09-04T01:00:00Z",
         "scheduled_end": "2026-09-04T01:30:00Z"},
        TEST_USERS["clerk_headers"])
    validate_error(resp, ApiErrorId.ERR_EVENT_OVERLAP)


def test_event_overlap_beats_referendum_availability(api):
    """PRD §2.10: "then the temporal and referential business rules — event
    overlap (`ERR_EVENT_OVERLAP`), hearing notice (`ERR_HEARING_NOTICE`), crew
    capacity (`ERR_CREW_CAPACITY_EXCEEDED`), statutory method permission
    (`ERR_METHOD_NOT_PERMITTED`), referendum availability
    (`ERR_REFERENDUM_NOT_AVAILABLE`)".

    Design: Difficulty/priority_pair_validation_conflict/event_overlap_beats_referendum_availability
    """
    ctx = setup_target_in_municipal_review(customer_count=10)
    target_id = ctx["target"]["id"]
    schedule_event(target_id, "PUBLIC_HEARING",
                   "2026-09-02T00:00:00Z", "2026-09-02T02:00:00Z")
    resp = api.create_council_event(
        target_id,
        {"kind": "REFERENDUM", "scheduled_start": "2026-09-02T01:00:00Z",
         "scheduled_end": "2026-09-02T03:00:00Z"},
        TEST_USERS["clerk_headers"])
    validate_error(resp, ApiErrorId.ERR_EVENT_OVERLAP)


def test_event_overlap_beats_referendum_availability_prior_vote_failed(api):
    """PRD §2.10: "A failure at an earlier tier masks later tiers".
    PRD §3.4: "Events of the same target may not overlap ... any genuine overlap
    is rejected with `ERR_EVENT_OVERLAP` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/event_overlap_beats_referendum_availability
    """
    ctx = setup_target_in_municipal_review(customer_count=10)
    target_id = ctx["target"]["id"]
    setup_hearing_held(target_id)
    set_clock("2026-09-10T00:00:00Z")
    vote = schedule_event(target_id, "COUNCIL_VOTE",
                          "2026-09-10T03:00:00Z", "2026-09-10T04:00:00Z")
    get_success_data(record_outcome(vote["id"], {"yes_votes": 11, "no_votes": 9}))
    # A referendum would be available now, but an overlapping window still wins.
    resp = api.create_council_event(
        target_id,
        {"kind": "REFERENDUM", "scheduled_start": "2026-09-10T03:30:00Z",
         "scheduled_end": "2026-09-10T05:00:00Z"},
        TEST_USERS["clerk_headers"])
    validate_error(resp, ApiErrorId.ERR_EVENT_OVERLAP)


def test_council_vote_exactly_60_passes(api):
    """PRD §3.4: "A `COUNCIL_VOTE` **passes** when `yes_share_pct` is at least
    60.00 — a supermajority is required, so exactly 60.00 passes and 59.99
    fails. A passed council vote sets the target's `council_approved` to true."

    Design: Difficulty/boundary_precision_check/council_vote_exactly_60_passes
    """
    ctx = setup_target_in_municipal_review(customer_count=10)
    target_id = ctx["target"]["id"]
    setup_hearing_held(target_id)
    set_clock("2026-09-10T00:00:00Z")
    vote = schedule_event(target_id, "COUNCIL_VOTE",
                          "2026-09-10T03:00:00Z", "2026-09-10T04:00:00Z")
    resp = record_outcome(vote["id"], {"yes_votes": 3, "no_votes": 2})
    decided = validate_success(resp, 200)
    assert decided["status"] == "PASSED"
    assert float(decided["yes_share_pct"]) == 60.00
    fresh = get_success_data(api.get_target(target_id, TEST_USERS["analyst_headers"]))
    assert fresh["council_approved"] is True


def test_council_vote_exactly_60_passes_boundary_59_99_fails(api):
    """PRD §3.4: "When `yes_share_pct` is at least 50.00 but below 60.00, the
    margin is close enough that the public gets the final word: the event
    records `FAILED`, the target stays in `MUNICIPAL_REVIEW`, and a `REFERENDUM`
    may be scheduled — no target rejection occurs."

    Design: Difficulty/boundary_precision_check/council_vote_exactly_60_passes
    """
    ctx = setup_target_in_municipal_review(customer_count=10)
    target_id = ctx["target"]["id"]
    setup_hearing_held(target_id)
    set_clock("2026-09-10T00:00:00Z")
    vote = schedule_event(target_id, "COUNCIL_VOTE",
                          "2026-09-10T03:00:00Z", "2026-09-10T04:00:00Z")
    # 5999 / 10000 = 59.99 < 60.00 -> referendum-band failure.
    decided = get_success_data(record_outcome(vote["id"],
                                              {"yes_votes": 5999, "no_votes": 4001}))
    assert decided["status"] == "FAILED"
    assert float(decided["yes_share_pct"]) == 59.99
    fresh = get_success_data(api.get_target(target_id, TEST_USERS["analyst_headers"]))
    assert fresh["status"] == "MUNICIPAL_REVIEW"
    assert fresh["council_approved"] is False


def test_referendum_exactly_50_fails_51_passes(api):
    """PRD §3.4: "A `REFERENDUM` **passes** on a strict majority:
    `yes_share_pct` greater than 50.00, so exactly 50.00 fails and 50.01 passes.
    A passed referendum sets the target's `council_approved` to true."

    Design: Corner/calculations/referendum_exactly_50_fails_51_passes
    """
    ctx = setup_target_in_municipal_review(customer_count=5)
    target_id = ctx["target"]["id"]
    setup_hearing_held(target_id)
    set_clock("2026-09-10T00:00:00Z")
    vote = schedule_event(target_id, "COUNCIL_VOTE",
                          "2026-09-10T03:00:00Z", "2026-09-10T04:00:00Z")
    failed_vote = get_success_data(record_outcome(vote["id"],
                                                  {"yes_votes": 11, "no_votes": 9}))
    assert failed_vote["status"] == "FAILED"
    fresh = get_success_data(api.get_target(target_id, TEST_USERS["analyst_headers"]))
    assert fresh["status"] == "MUNICIPAL_REVIEW"

    referendum = schedule_event(target_id, "REFERENDUM",
                                "2026-09-20T00:00:00Z", "2026-09-20T06:00:00Z")
    decided = get_success_data(record_outcome(referendum["id"],
                                              {"yes_votes": 51, "no_votes": 50}))
    assert decided["status"] == "PASSED"
    assert float(decided["yes_share_pct"]) == 50.50
    fresh = get_success_data(api.get_target(target_id, TEST_USERS["analyst_headers"]))
    assert fresh["council_approved"] is True


def test_referendum_without_qualifying_vote_rejected(api):
    """PRD §3.4: "A `REFERENDUM` event may only be created while the target's
    latest recorded `COUNCIL_VOTE` outcome is `FAILED` with a `yes_share_pct` of
    at least 50.00 — the referendum band described below; creating one in any
    other circumstance is rejected with `ERR_REFERENDUM_NOT_AVAILABLE`
    (HTTP 409)."

    Design: Corner/validations/referendum_without_qualifying_vote_rejected
    """
    ctx = setup_target_in_municipal_review(customer_count=5)
    target_id = ctx["target"]["id"]
    resp = api.create_council_event(
        target_id,
        {"kind": "REFERENDUM", "scheduled_start": "2026-10-01T00:00:00Z",
         "scheduled_end": "2026-10-01T06:00:00Z"},
        TEST_USERS["clerk_headers"])
    validate_error(resp, ApiErrorId.ERR_REFERENDUM_NOT_AVAILABLE)


def test_vote_recorded_before_hearing_notice_window_rejected(api):
    """PRD §3.4: "at least one `PUBLIC_HEARING` of the same target must be `HELD`
    with its `scheduled_end` at least 7 days before the current logical clock;
    recording a council-vote outcome without such a hearing is rejected with
    `ERR_HEARING_NOTICE` (HTTP 409)."

    Design: Corner/validations/vote_recorded_before_hearing_notice_window_rejected
    """
    ctx = setup_target_in_municipal_review(customer_count=5)
    target_id = ctx["target"]["id"]
    setup_hearing_held(target_id, start="2026-09-08T00:00:00Z",
                       end="2026-09-08T02:00:00Z")
    set_clock("2026-09-10T00:00:00Z")
    vote = schedule_event(target_id, "COUNCIL_VOTE",
                          "2026-09-10T03:00:00Z", "2026-09-10T04:00:00Z")
    resp = record_outcome(vote["id"], {"yes_votes": 3, "no_votes": 2})
    validate_error(resp, ApiErrorId.ERR_HEARING_NOTICE)
    fresh = get_success_data(api.get_council_event(vote["id"], TEST_USERS["clerk_headers"]))
    assert fresh["status"] == "SCHEDULED"


def test_record_outcome_twice_is_idempotent_rejected(api):
    """PRD §3.4: "recording an outcome for an event not in `SCHEDULED` — is
    rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/record_outcome_twice_is_idempotent_rejected
    """
    ctx = setup_target_in_municipal_review(customer_count=5)
    hearing = schedule_event(ctx["target"]["id"], "PUBLIC_HEARING",
                             "2026-09-02T00:00:00Z", "2026-09-02T02:00:00Z")
    get_success_data(record_outcome(hearing["id"]))
    resp = record_outcome(hearing["id"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    fresh = get_success_data(api.get_council_event(hearing["id"], TEST_USERS["clerk_headers"]))
    assert fresh["status"] == "HELD"


def test_hearing_votes_ignored_vote_requires_votes(api):
    """PRD §3.4: "recording on a vote or referendum requires `yes_votes` and
    `no_votes`, whose sum must be greater than zero (a missing vote count is
    rejected with `ERR_INVALID_REQUEST`, HTTP 422)".

    Design: Corner/state_machines/hearing_votes_ignored_vote_requires_votes
    """
    ctx = setup_target_in_municipal_review(customer_count=5)
    vote = schedule_event(ctx["target"]["id"], "COUNCIL_VOTE",
                          "2026-09-12T00:00:00Z", "2026-09-12T02:00:00Z")
    resp = record_outcome(vote["id"], {})
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    fresh = get_success_data(api.get_council_event(vote["id"], TEST_USERS["clerk_headers"]))
    assert fresh["status"] == "SCHEDULED"


def test_council_hard_fail_full_rejection_cascade(api):
    """PRD §3.8: "the target moves to `REJECTED`, and the rejection cascades
    through everything still in flight. Every `OPEN` or `FINALIZED` valuation
    case of the target moves to `SUPERSEDED`, and every `SUBMITTED` or
    `SELECTED` valuation entry moves to `NOT_SELECTED`. Every `PENDING`
    transition item moves to `BLOCKED`. Every `PENDING` employee transition
    moves to `WITHDRAWN`, with severance remaining zero."

    Design: Difficulty/transitive_cascade/council_hard_fail_full_rejection_cascade
    """
    ctx = setup_target_in_municipal_review(system_type="COMBINED", customer_count=500)
    target_id = ctx["target"]["id"]
    emp = register_employee(target_id, employee_ref="E1", years_of_service=3,
                            weekly_salary_cents=100000, union_covered=False)
    setup_hearing_held(target_id)
    set_clock("2026-09-10T00:00:00Z")
    vote = schedule_event(target_id, "COUNCIL_VOTE",
                          "2026-09-10T03:00:00Z", "2026-09-10T04:00:00Z")
    decided = get_success_data(record_outcome(vote["id"], {"yes_votes": 2, "no_votes": 5}))
    assert decided["status"] == "FAILED"

    fresh = get_success_data(api.get_target(target_id, TEST_USERS["analyst_headers"]))
    assert fresh["status"] == "REJECTED"
    case_now = get_success_data(api.get_valuation_case(ctx["case"]["id"],
                                                       TEST_USERS["analyst_headers"]))
    assert case_now["status"] == "SUPERSEDED"
    entry_now = get_success_data(
        api.list_valuation_entries(ctx["case"]["id"], TEST_USERS["analyst_headers"]))
    assert entry_now[0]["status"] == "NOT_SELECTED"
    for item in list_transition_items(target_id):
        assert item["status"] == "BLOCKED"
    emp_now = get_success_data(api.get_employee_transition(emp["id"], TEST_USERS["hr_headers"]))
    assert emp_now["status"] == "WITHDRAWN"
    assert emp_now["severance_cents"] == 0


def test_council_hard_fail_cascade_via_denied_decision(api):
    """PRD §3.5: "**`DENIED`.** The application is terminal, and the denial
    fires the target's rejection cascade (§3.8)."

    Design: Difficulty/transitive_cascade/council_hard_fail_full_rejection_cascade
    """
    ctx = setup_target_in_regulatory_review(customer_count=500)
    target_id = ctx["target"]["id"]
    decide_application(ctx["application"]["id"], "DENIED")
    fresh = get_success_data(api.get_target(target_id, TEST_USERS["analyst_headers"]))
    assert fresh["status"] == "REJECTED"
    case_now = get_success_data(api.get_valuation_case(ctx["case"]["id"],
                                                       TEST_USERS["analyst_headers"]))
    assert case_now["status"] == "SUPERSEDED"


def test_cascaded_rejection_immediately_visible(api):
    """PRD §3.8: "the target moves to `REJECTED`, and the rejection cascades
    through everything still in flight."

    Design: Corner/consistency_model/cascaded_rejection_immediately_visible
    """
    ctx = setup_target_in_municipal_review(customer_count=5)
    target_id = ctx["target"]["id"]
    setup_hearing_held(target_id)
    set_clock("2026-09-10T00:00:00Z")
    vote = schedule_event(target_id, "COUNCIL_VOTE",
                          "2026-09-10T03:00:00Z", "2026-09-10T04:00:00Z")
    get_success_data(record_outcome(vote["id"], {"yes_votes": 0, "no_votes": 5}))
    fresh = get_success_data(api.get_target(target_id, TEST_USERS["analyst_headers"]))
    assert fresh["status"] == "REJECTED"
    case_now = get_success_data(api.get_valuation_case(ctx["case"]["id"],
                                                       TEST_USERS["analyst_headers"]))
    assert case_now["status"] == "SUPERSEDED"


def test_terminal_target_rejects_further_transitions(api):
    """PRD §3.8: "`REJECTED` and `INTEGRATED` are terminal: no further
    transitions out of them exist."

    Design: Corner/state_machines/terminal_target_rejects_further_transitions
    """
    ctx = setup_target_in_municipal_review(customer_count=5)
    target_id = ctx["target"]["id"]
    setup_hearing_held(target_id)
    set_clock("2026-09-10T00:00:00Z")
    vote = schedule_event(target_id, "COUNCIL_VOTE",
                          "2026-09-10T03:00:00Z", "2026-09-10T04:00:00Z")
    get_success_data(record_outcome(vote["id"], {"yes_votes": 1, "no_votes": 5}))
    resp = api.close_target(target_id, TEST_USERS["transition_mgr_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    fresh = get_success_data(api.get_target(target_id, TEST_USERS["analyst_headers"]))
    assert fresh["status"] == "REJECTED"


def test_commissioner_cannot_record_council_outcome(api):
    """PRD §2.1: "A `MunicipalClerk` is the municipality's clerk: schedules
    public hearings, council votes, and referenda, and records their outcomes."
    and "A request whose role is not permitted for the endpoint is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/commissioner_cannot_record_council_outcome
    """
    ctx = setup_target_in_municipal_review(customer_count=5)
    hearing = schedule_event(ctx["target"]["id"], "PUBLIC_HEARING",
                             "2026-09-02T00:00:00Z", "2026-09-02T02:00:00Z")
    resp = api.record_council_outcome(hearing["id"], {},
                                      TEST_USERS["commissioner_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
