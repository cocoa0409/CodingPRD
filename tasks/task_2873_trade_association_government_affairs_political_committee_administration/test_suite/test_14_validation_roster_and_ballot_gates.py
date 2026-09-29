"""Dependency guards on filings and the roster, ballot and seat gates."""
from test_helpers import (
    COMPLIANCE,
    DEFAULT_CLOCK_INSTANT,
    DIRECTOR,
    api_client,
    cast_ballot,
    cast_vote_payload,
    create_seat_payload,
    draft_position,
    enroll_member,
    make_member_delegate_headers,
    open_ballot_round,
    open_report,
    read_activity,
    read_committee,
    read_position,
    read_registration,
    read_report,
    seat_member,
    setup_active_registration,
    setup_certified_report,
    setup_forming_committee,
    setup_position_in_balloting,
    tally_round,
    validate_error,
    validate_paginated,
    validate_success,
    void_payload,
)


def test_a_single_open_report_blocks_termination_with_no_spend_behind_it():
    """The termination guard queries report status, not accumulated spend.

    PRD 3.5: "Termination moves `ACTIVE → TERMINATED` and stamps `terminated_at`; it is
    blocked while any expenditure report of this registration is still `OPEN`, which is
    refused with `ERR_OPEN_REPORT_BLOCKS_TERMINATION`."

    Design: Corner/Validations/terminating_a_registration_with_an_open_report_rejected
    """
    registration = setup_active_registration()
    report = open_report(registration["id"], period_code="2026Q1")
    assert report["status"] == "OPEN"
    assert report["included_activity_count"] == 0

    validate_error(
        api_client.terminate_registration(registration["id"], COMPLIANCE),
        "ERR_OPEN_REPORT_BLOCKS_TERMINATION",
        422,
    )

    stored = read_registration(registration["id"])
    assert stored["status"] == "ACTIVE"
    assert stored["terminated_at"] is None


def test_a_certified_report_freezes_the_activity_it_swept_up():
    """Certification blocks the void outright, so no total can drift after filing.

    PRD 3.5: "It is blocked outright when any expenditure report that included this
    activity has already been certified, because a certified filing's totals are frozen —
    that refusal is `ERR_ACTIVITY_IN_CERTIFIED_REPORT`."
    PRD 3.5: "Reports that are `CERTIFIED` or `SUPERSEDED` are never recomputed by a void."

    Design: Corner/Validations/voiding_an_activity_inside_a_certified_report_rejected
    """
    state = setup_certified_report(
        [{"activity_date": "2026-02-15", "hours": 2.000, "expenditure_cents": 300_000}],
        period_code="2026Q1",
        certify_on=DEFAULT_CLOCK_INSTANT,
    )
    registration_id = state["registration"]["id"]
    activity_id = state["activities"][0]["id"]

    validate_error(
        api_client.void_lobbying_activity(
            activity_id,
            void_payload(void_reason="Duplicate entry discovered after filing"),
            DIRECTOR,
        ),
        "ERR_ACTIVITY_IN_CERTIFIED_REPORT",
        422,
    )

    activity = read_activity(registration_id, activity_id)
    assert activity["status"] == "LOGGED"
    assert activity["void_reason"] is None

    registration = read_registration(registration_id)
    assert registration["ytd_reportable_cents"] == 300_000
    assert float(registration["ytd_reportable_hours"]) == 2.000

    report = read_report(registration_id, state["report"]["id"])
    assert report["status"] == "CERTIFIED"
    assert report["included_activity_count"] == 1
    assert report["method_a_total_cents"] == 300_000
    assert report["method_b_total_cents"] == 317_000
    assert report["filed_total_cents"] == 300_000


def test_a_repeat_seating_and_a_second_chair_are_refused_by_their_own_errors():
    """Two uniqueness rules share the seating endpoint and neither moves the roster.

    PRD 3.2: "A committee may have at most one chair, and a second chair request is
    refused with `ERR_CHAIR_SEAT_TAKEN`; a member may hold at most one seat on a given
    committee, and a repeat seating is refused with `ERR_DUPLICATE_SEAT`."

    Design: Corner/Validations/duplicate_seat_and_second_chair_seat_rejected
    """
    roster = setup_forming_committee()
    committee_id = roster["committee"]["id"]
    alpha = roster["members"][0]
    gamma = enroll_member(
        legal_name="Gamma Components Co", membership_tier="ASSOCIATE", restricted_class_size=5
    )

    validate_error(
        api_client.create_committee_seat(
            committee_id, create_seat_payload(alpha["id"], seat_role="MEMBER"), DIRECTOR
        ),
        "ERR_DUPLICATE_SEAT",
        409,
    )
    validate_error(
        api_client.create_committee_seat(
            committee_id, create_seat_payload(gamma["id"], seat_role="CHAIR"), DIRECTOR
        ),
        "ERR_CHAIR_SEAT_TAKEN",
        409,
    )

    committee = read_committee(committee_id)
    assert committee["seat_count"] == 2
    assert committee["total_voting_weight"] == 5
    assert committee["roster_state"] == "FORMING"

    rows, meta = validate_paginated(
        api_client.list_committee_seats(committee_id, DIRECTOR)
    )
    assert len(rows) == 2
    assert meta["total_count"] == 2

    seated = seat_member(committee_id, gamma["id"], seat_role="MEMBER")
    assert seated["seat_role"] == "MEMBER"


def test_a_forming_roster_refuses_the_ballot_and_applies_no_side_effect():
    """The roster gate names the forming roster rather than the adopt-side error.

    PRD 3.3: "The committee's `roster_state` must not be `FORMING`; both `QUORATE` and
    `IMPAIRED` are acceptable here, and a still-forming roster is refused with
    `ERR_COMMITTEE_FORMING`."

    Design: Corner/Validations/open_ballot_on_a_forming_committee_rejected
    """
    roster = setup_forming_committee()
    committee_id = roster["committee"]["id"]
    position = draft_position(committee_id, title="Oppose Section 232 Expansion")

    validate_error(
        api_client.open_ballot(
            position["id"], DIRECTOR, {"ballot_deadline_date": "2026-09-10"}
        ),
        "ERR_COMMITTEE_FORMING",
        409,
    )

    stored = read_position(position["id"])
    assert stored["status"] == "DRAFT"
    assert stored["round_number"] == 0
    assert stored["ballot_deadline_date"] is None

    committee = read_committee(committee_id)
    assert committee["roster_state"] == "FORMING"
    assert committee["seat_count"] == 2
    assert committee["total_voting_weight"] == 5


def test_the_fourth_round_is_refused_by_the_round_allowance_not_the_state_error():
    """Three no-quorum rounds exhaust the allowance and the fourth opening is named.

    PRD 3.3: "A position whose `round_number` has already reached three is sitting in the
    terminal `FAILED_CONSENSUS` state, and an attempt to open a fourth round is refused
    specifically with `ERR_MAX_BALLOT_ROUNDS` rather than with the generic state error;
    opening a round from any other ineligible state — `BALLOTING`, `CONSENSUS_REACHED` or
    `ADOPTED` — yields `ERR_INVALID_POSITION_STATE`."

    Design: Corner/Validations/open_ballot_after_three_failed_rounds_rejected
    """
    state = setup_position_in_balloting()
    position_id = state["position"]["id"]
    gamma = state["members"][2]

    for expected_round in (1, 2, 3):
        if expected_round > 1:
            open_ballot_round(position_id)
        cast_ballot(position_id, gamma["id"])
        tallied = tally_round(position_id)
        assert tallied["round_number"] == expected_round
        assert float(tallied["quorum_pct"]) == 16.67
        assert tallied["last_tally_outcome"] == "NO_QUORUM"
        assert tallied["status"] == (
            "RECONSIDERATION" if expected_round < 3 else "FAILED_CONSENSUS"
        )

    validate_error(
        api_client.open_ballot(position_id, DIRECTOR), "ERR_MAX_BALLOT_ROUNDS", 409
    )

    stored = read_position(position_id)
    assert stored["status"] == "FAILED_CONSENSUS"
    assert stored["round_number"] == 3


def test_a_round_with_nothing_cast_cannot_be_scored():
    """An untouched round is refused rather than tallied into a zero result.

    PRD 3.4: "A round in which every ballot has been superseded, or in which nothing was
    ever cast, cannot be scored, and the attempt is refused with `ERR_NO_BALLOTS_CAST`."

    Design: Corner/Validations/tally_with_no_cast_ballot_in_the_current_round_rejected
    """
    state = setup_position_in_balloting()
    position_id = state["position"]["id"]

    validate_error(
        api_client.tally_position(position_id, DIRECTOR), "ERR_NO_BALLOTS_CAST", 409
    )

    stored = read_position(position_id)
    assert stored["status"] == "BALLOTING"
    assert stored["round_number"] == 1
    assert stored["last_tally_outcome"] == "NONE"
    assert stored["support_weight"] == 0
    assert stored["oppose_weight"] == 0
    assert stored["abstain_weight"] == 0
    assert float(stored["quorum_pct"]) == 0.00
    assert float(stored["consensus_pct"]) == 0.00


def test_a_dissent_statement_on_a_supporting_ballot_persists_no_vote_at_all():
    """The statement is not silently dropped: the whole cast is refused.

    PRD 3.3: "Its `dissent_status` is `FILED` when a non-empty `dissent_statement` was
    supplied and `NONE` when it was not; a dissent statement is only meaningful alongside
    an opposing ballot, so supplying one together with `SUPPORT` or `ABSTAIN` is refused
    with `ERR_DISSENT_REQUIRES_OPPOSE`."

    Design: Corner/Validations/dissent_statement_on_a_support_ballot_rejected
    """
    state = setup_position_in_balloting()
    position_id = state["position"]["id"]
    alpha = state["members"][0]
    statement = "We support the position but object to the timetable."

    validate_error(
        api_client.cast_vote(
            position_id,
            cast_vote_payload("SUPPORT", dissent_statement=statement),
            make_member_delegate_headers(alpha["id"]),
        ),
        "ERR_DISSENT_REQUIRES_OPPOSE",
        409,
    )

    rows, meta = validate_paginated(
        api_client.list_position_votes(position_id, DIRECTOR)
    )
    assert rows == []
    assert meta["total_count"] == 0

    vote = validate_success(
        api_client.cast_vote(
            position_id,
            cast_vote_payload("OPPOSE", dissent_statement=statement),
            make_member_delegate_headers(alpha["id"]),
        ),
        201,
    )
    assert vote["ballot_status"] == "CAST"
    assert vote["dissent_status"] == "FILED"


def test_an_active_member_without_a_seat_on_this_committee_cannot_vote():
    """Committee membership, not association membership, confers the ballot.

    PRD 3.3: "It also requires the caller to be a seated committee member in good
    standing: the caller must hold a seat on the position's committee whose status is
    `ACTIVE` or `DAMPENED`, failing which the cast is refused with `ERR_MEMBER_NOT_SEATED`,
    and the caller's member record must itself be `ACTIVE`, failing which it is refused
    with `ERR_MEMBER_NOT_ACTIVE`."

    Design: Corner/Validations/vote_cast_by_a_member_without_a_seat_rejected
    """
    state = setup_position_in_balloting()
    position_id = state["position"]["id"]
    delta = enroll_member(
        legal_name="Delta Tooling Group", membership_tier="FULL", restricted_class_size=15
    )
    assert delta["status"] == "ACTIVE"

    validate_error(
        api_client.cast_vote(
            position_id,
            cast_vote_payload("SUPPORT"),
            make_member_delegate_headers(delta["id"]),
        ),
        "ERR_MEMBER_NOT_SEATED",
        409,
    )

    rows, meta = validate_paginated(
        api_client.list_position_votes(position_id, DIRECTOR)
    )
    assert rows == []
    assert meta["total_count"] == 0

    own_rows, own_meta = validate_paginated(
        api_client.list_member_position_votes(
            delta["id"], make_member_delegate_headers(delta["id"])
        )
    )
    assert own_rows == []
    assert own_meta["total_count"] == 0
