"""Mediation rounds: creation stamps and case flip, the one-open-round rule,
the inclusive response deadline, the documentation gate on ACCEPT, the
reserved AUDIT note category, and the escalation evidence gate."""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    add_case_note,
    assert_instant,
    assert_mediation_round,
    case_state_payload,
    create_assigned_case,
    create_case,
    make_employer_headers,
    make_ombudsman_headers,
    mediation_round_payload,
    open_round,
    read_case,
    read_employer,
    respond_as_employer,
    round_response_payload,
    set_clock,
    setup_basic_world,
    validate_error,
    validate_success,
)


def test_round_create_stamps_deadline_and_flips_case(api: ApiClient):
    """PRD §3.4: "Rounds are numbered per case starting at 1, each new round's `round_number` being the count of the case's prior rounds plus one."
    PRD §3.4: "Each new round computes its `response_deadline` as 14 days after its creation and opens in `PROPOSED` status, and its creation moves the case into `AWAITING_RESPONSE` — the case's `open_round_count`, the count of its `PROPOSED` rounds, becoming 1 with the first round and increasing by 1 with each subsequent one."

    Design: Corner/endpoints/round_create_stamps_deadline_and_flips_case
    """
    world = setup_basic_world(api)
    case = create_assigned_case(api, world["employer"], world["member"], world["ombudsman"])

    mediation_round = open_round(api, case["id"], world["ombudsman"]["id"],
                                 proposal_text="Reinstate at prior role.")
    assert_mediation_round(mediation_round)
    assert mediation_round["round_number"] == 1
    assert_instant(mediation_round["response_deadline"], "2026-09-15T00:00:00Z", "response_deadline")
    assert mediation_round["status"] == "PROPOSED"
    assert mediation_round["responded_at"] is None
    assert mediation_round["response"] is None

    case_after = read_case(api, case["id"])
    assert case_after["status"] == "AWAITING_RESPONSE"
    assert case_after["open_round_count"] == 1


def test_respond_timing_boundary_at_deadline(api: ApiClient, coordinator_headers: dict):
    """PRD §2.4: "A proposed mediation round flips from `PROPOSED` to `EXPIRED` only when the clock is strictly later than its `response_deadline` — a response recorded at exactly the deadline instant is still timely — and a round that lapses this way pulls its case from `AWAITING_RESPONSE` back to `IN_MEDIATION` as it expires."
    PRD §3.4: "When the clock has passed the deadline, the round flips `PROPOSED → EXPIRED`, the case falls back from `AWAITING_RESPONSE` to `IN_MEDIATION`, and the late answer itself fails with `ERR_RESPONSE_DEADLINE_PASSED` (HTTP 422); at exactly the deadline instant an answer is still timely."

    Design: Corner/validations/respond_timing_boundary_at_deadline
    """
    world = setup_basic_world(api)
    case = create_assigned_case(api, world["employer"], world["member"], world["ombudsman"])
    round_one = open_round(api, case["id"], world["ombudsman"]["id"])
    assert_instant(round_one["response_deadline"], "2026-09-15T00:00:00Z", "round one deadline")

    set_clock(api, "2026-09-15T00:00:00Z")
    timely = respond_as_employer(api, round_one["id"], world["employer"]["id"], "DECLINE")
    assert timely["status"] == "DECLINED", "a response at exactly the deadline instant is timely"

    round_two = open_round(api, case["id"], world["ombudsman"]["id"], proposal_text="Second offer.")
    assert_instant(round_two["response_deadline"], "2026-09-29T00:00:00Z", "round two deadline")

    set_clock(api, "2026-09-29T00:00:01Z")
    late = api.respond_to_round(
        round_two["id"], round_response_payload("ACCEPT"), make_employer_headers(world["employer"]["id"])
    )
    validate_error(late, ApiErrorId.ERR_RESPONSE_DEADLINE_PASSED)
    assert late.status_code == 422

    rounds = {r["id"]: r for r in validate_success(api.list_case_rounds(case["id"], coordinator_headers))}
    assert rounds[round_two["id"]]["status"] == "EXPIRED", "the late answer lazily flips the round to EXPIRED"
    assert read_case(api, case["id"])["status"] == "IN_MEDIATION"


def test_accept_with_incomplete_documentation_returns_documentation_incomplete(api: ApiClient):
    """PRD §3.4: "If the predicate is false when an `ACCEPT` arrives, the response is rejected with `ERR_DOCUMENTATION_INCOMPLETE` and the round stays `PROPOSED` with no side effects firing."
    PRD §3.4: "The case's `documentation_complete` predicate, recomputed whenever the case is read, requires four things at once, with system-generated `AUDIT` notes never counting toward any category: at least one note of `note_type` `INTAKE`; at least as many `CONTACT` notes as the case has mediation rounds of any status; at least one `RESOLUTION` note; and — only when the case's `issue_type` is `BENEFITS` or `PENSION` — at least one `EMPLOYER_EDUCATION` note."

    Design: Corner/state_machines/accept_with_incomplete_documentation_returns_documentation_incomplete
    """
    world = setup_basic_world(api)
    case = create_assigned_case(api, world["employer"], world["member"], world["ombudsman"])
    add_case_note(api, case["id"], "INTAKE", "Intake done.")
    mediation_round = open_round(api, case["id"], world["ombudsman"]["id"])
    assert read_case(api, case["id"])["documentation_complete"] is False

    response = api.respond_to_round(
        mediation_round["id"], round_response_payload("ACCEPT"), make_employer_headers(world["employer"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_DOCUMENTATION_INCOMPLETE)
    assert response.status_code == 409

    rounds = validate_success(api.list_case_rounds(case["id"], make_ombudsman_headers(world["ombudsman"]["id"])))
    assert rounds[0]["status"] == "PROPOSED" and rounds[0]["responded_at"] is None
    assert read_case(api, case["id"])["status"] == "AWAITING_RESPONSE"
    assert read_employer(api, world["employer"]["id"])["resolved_case_count"] == 0


def test_case_note_with_audit_type_returns_invalid_request(api: ApiClient, coordinator_headers: dict):
    """PRD §3.4: "the `AUDIT` category is reserved for system-generated entries and is refused on input with `ERR_INVALID_REQUEST`."
    PRD §2.7: "Third, request shape: required fields present, enum members valid, the system-reserved `AUDIT` note category refused on input, and intervals whose end is not strictly after their start, all failing with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/case_note_with_audit_type_returns_invalid_request
    """
    world = setup_basic_world(api)
    case = create_case(api, world["member"]["id"], world["employer"]["id"])

    response = api.create_case_note(
        {"case_id": case["id"], "note_type": "AUDIT", "body": "Forged audit entry"}, coordinator_headers
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    assert response.status_code == 400

    notes = validate_success(api.list_case_notes(case["id"], coordinator_headers))
    assert notes == [], "nothing is persisted by a refused AUDIT note"


def test_escalate_requires_declined_or_expired_round(api: ApiClient):
    """PRD §3.7: "When mediation stalls, the assigned ombudsman escalates the case — from `IN_MEDIATION`, or from `AWAITING_RESPONSE` while a proposal is still out — into `ESCALATION_PENDING`. Escalation demands evidence that the informal track has been tried: at least one of the case's rounds must be `DECLINED` or `EXPIRED`, failing with `ERR_NO_EXHAUSTED_ROUND` otherwise."
    PRD §2.7: "Sixth, state gates: the target entity must be in a state from which the requested transition exists, and cross-entity state gates apply, failing with `ERR_INVALID_STATE`, `ERR_ROUND_NOT_OPEN`, or `ERR_OMBUDSMAN_NOT_CERTIFIED`."

    Design: Corner/state_machines/escalate_requires_declined_or_expired_round
    """
    world = setup_basic_world(api)
    ombudsman_headers = make_ombudsman_headers(world["ombudsman"]["id"])
    case = create_assigned_case(api, world["employer"], world["member"], world["ombudsman"])

    early = api.transition_case(case["id"], case_state_payload("ESCALATION_PENDING"), ombudsman_headers)
    validate_error(early, ApiErrorId.ERR_INVALID_STATE)

    mediation_round = open_round(api, case["id"], world["ombudsman"]["id"])
    respond_as_employer(api, mediation_round["id"], world["employer"]["id"], "COUNTER",
                        counter_text="90 percent pay.")
    assert read_case(api, case["id"])["status"] == "IN_MEDIATION"

    unexhausted = api.transition_case(case["id"], case_state_payload("ESCALATION_PENDING"), ombudsman_headers)
    error_data = validate_error(unexhausted, ApiErrorId.ERR_NO_EXHAUSTED_ROUND)
    assert error_data["error_id"] != "ERR_INVALID_STATE", \
        "from IN_MEDIATION the transition exists, so the exhausted-round gate is what fails"

    after = read_case(api, case["id"])
    assert after["status"] == "IN_MEDIATION"
    assert after["escalated_at"] is None


def test_respond_countered_round_past_deadline_state_error_wins(api: ApiClient):
    """PRD §3.4: "Answers are accepted only while the round is still `PROPOSED` — answering a round that has already reached any terminal status fails with `ERR_ROUND_NOT_OPEN` — and only while the logical clock has not passed the round's `response_deadline`."
    PRD §2.7: "Sixth, state gates: the target entity must be in a state from which the requested transition exists, and cross-entity state gates apply, failing with `ERR_INVALID_STATE`, `ERR_ROUND_NOT_OPEN`, or `ERR_OMBUDSMAN_NOT_CERTIFIED`."
    PRD §2.7: "Ninth, the temporal windows — response deadline, referral window, reopen window — failing with `ERR_RESPONSE_DEADLINE_PASSED`, `ERR_REFERRAL_WINDOW_PASSED`, or `ERR_REOPEN_WINDOW_PASSED`."

    Design: Difficulty/priority_pair_validation_conflict/respond_closed_round_with_passed_deadline_state_wins
    """
    world = setup_basic_world(api)
    case = create_assigned_case(api, world["employer"], world["member"], world["ombudsman"])
    mediation_round = open_round(api, case["id"], world["ombudsman"]["id"],
                                 proposal_text="Reinstate at prior pay.")
    respond_as_employer(api, mediation_round["id"], world["employer"]["id"], "COUNTER",
                        counter_text="Reinstate at 90 percent pay.")

    set_clock(api, "2026-09-20T00:00:00Z")
    response = api.respond_to_round(
        mediation_round["id"], round_response_payload("DECLINE"), make_employer_headers(world["employer"]["id"])
    )
    error_data = validate_error(response, ApiErrorId.ERR_ROUND_NOT_OPEN)
    assert response.status_code == 409
    assert error_data["error_id"] != "ERR_RESPONSE_DEADLINE_PASSED", \
        "the state-tier error (sixth) wins over the temporal tier (ninth)"


def test_respond_countered_round_past_deadline_fires_no_side_effects(api: ApiClient, coordinator_headers: dict):
    """PRD §3.4: "Answers are accepted only while the round is still `PROPOSED` — answering a round that has already reached any terminal status fails with `ERR_ROUND_NOT_OPEN`"
    PRD §3.4: "a counter carries the party's `counter_text`, which is stored on the round, and any recorded response stamps `responded_at`."

    Design: Difficulty/priority_pair_validation_conflict/respond_closed_round_with_passed_deadline_state_wins
    """
    world = setup_basic_world(api)
    case = create_assigned_case(api, world["employer"], world["member"], world["ombudsman"])
    mediation_round = open_round(api, case["id"], world["ombudsman"]["id"],
                                 proposal_text="Reinstate at prior pay.")
    assert_instant(mediation_round["response_deadline"], "2026-09-15T00:00:00Z", "round deadline")
    respond_as_employer(api, mediation_round["id"], world["employer"]["id"], "COUNTER",
                        counter_text="Reinstate at 90 percent pay.")

    set_clock(api, "2026-09-20T00:00:00Z")
    api.respond_to_round(
        mediation_round["id"], round_response_payload("DECLINE"), make_employer_headers(world["employer"]["id"])
    )

    rounds = validate_success(api.list_case_rounds(case["id"], coordinator_headers))
    assert len(rounds) == 1
    assert rounds[0]["status"] == "COUNTERED", "the rejected answer does not move the terminal round"
    assert rounds[0]["counter_text"] == "Reinstate at 90 percent pay."
    assert read_case(api, case["id"])["status"] == "IN_MEDIATION"


def test_open_round_count_conserved_across_propose_and_decline(api: ApiClient):
    """PRD §3.4: "its creation moves the case into `AWAITING_RESPONSE` — the case's `open_round_count`, the count of its `PROPOSED` rounds, becoming 1 with the first round and increasing by 1 with each subsequent one."
    PRD §3.4: "A `COUNTERED` or `DECLINED` round — or one that expires, whether discovered lazily on a read of the case's rounds or on a response attempt — likewise returns the case from `AWAITING_RESPONSE` to `IN_MEDIATION`, decrementing `open_round_count` by 1, and the ombudsman may then open the next round."

    Design: Difficulty/compensating_invariant/open_round_count_conserved_across_propose_and_respond
    """
    world = setup_basic_world(api)
    case = create_assigned_case(api, world["employer"], world["member"], world["ombudsman"])
    assert read_case(api, case["id"])["open_round_count"] == 0

    round_one = open_round(api, case["id"], world["ombudsman"]["id"], proposal_text="Offer one.")
    assert read_case(api, case["id"])["open_round_count"] == 1

    respond_as_employer(api, round_one["id"], world["employer"]["id"], "DECLINE")
    after = read_case(api, case["id"])
    assert after["open_round_count"] == 0, "the DECLINE compensated the open"
    assert after["status"] == "IN_MEDIATION"

    rounds = validate_success(api.list_case_rounds(case["id"], make_ombudsman_headers(world["ombudsman"]["id"])))
    assert len(rounds) == 1 and rounds[0]["status"] == "DECLINED"


def test_open_round_count_conserved_across_counter_and_counter_text_stored(
    api: ApiClient, coordinator_headers: dict
):
    """PRD §3.4: "A `COUNTERED` or `DECLINED` round — or one that expires, whether discovered lazily on a read of the case's rounds or on a response attempt — likewise returns the case from `AWAITING_RESPONSE` to `IN_MEDIATION`, decrementing `open_round_count` by 1, and the ombudsman may then open the next round."
    PRD §3.4: "a counter carries the party's `counter_text`, which is stored on the round, and any recorded response stamps `responded_at`."

    Design: Difficulty/compensating_invariant/open_round_count_conserved_across_propose_and_respond
    """
    world = setup_basic_world(api)
    case = create_assigned_case(api, world["employer"], world["member"], world["ombudsman"])

    round_one = open_round(api, case["id"], world["ombudsman"]["id"], proposal_text="Offer one.")
    respond_as_employer(api, round_one["id"], world["employer"]["id"], "DECLINE")

    round_two = open_round(api, case["id"], world["ombudsman"]["id"], proposal_text="Offer two.")
    assert round_two["round_number"] == 2
    assert read_case(api, case["id"])["open_round_count"] == 1
    countered = respond_as_employer(api, round_two["id"], world["employer"]["id"], "COUNTER",
                                    counter_text="Half measure.")
    assert countered["status"] == "COUNTERED"
    assert countered["counter_text"] == "Half measure."
    assert countered["responded_at"] is not None
    assert read_case(api, case["id"])["open_round_count"] == 0, "the COUNTER compensated the second open"

    rounds = validate_success(api.list_case_rounds(case["id"], coordinator_headers))
    assert {r["status"] for r in rounds} == {"DECLINED", "COUNTERED"}
    assert len(rounds) == 2
