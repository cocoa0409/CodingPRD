"""State-machine paths: declared initial states, the petition review loop,
refused transitions, terminal lockdown, replay refusals and the filtered
cascades that a close, an award, a certification and a carrier standing
change fan out over their children.
"""


from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_departure_identity,
    assert_instant,
    assert_money,
    assert_obligation_identity,
    assert_one_decimal,
    assert_ratio,
    assert_versioned_row,
)
from test_helpers.constants import (
    AGREEMENT_ACTIVE,
    AGREEMENT_SUSPEND,
    AGREEMENT_SUSPENDED,
    CARRIER_ACTIVE,
    CARRIER_DEBARRED,
    CARRIER_SUSPENDED,
    COMMUNITY_ELIGIBLE,
    COMMUNITY_REGISTERED,
    COMMUNITY_SUBSIDIZED,
    CREATED_REASON_INITIAL,
    CREATED_REASON_REPLACEMENT,
    DECISION_DENY,
    DECISION_GRANT_WITH_HOLD_IN,
    DECISION_OPEN_REVIEW,
    DECISION_RETURN_FOR_INFO,
    DEFAULT_CLOCK,
    EVAL_NOT_EVALUATED,
    EVAL_SELECTED,
    EVAL_UNDER_EVALUATION,
    PAYMENT_BASIS_COMPLETED_FLIGHT_PRORATION,
    PAYMENT_BASIS_SCHEDULED_FLIGHT_FLAT,
    PAYMENT_COMPUTED,
    PERIOD_CERTIFIED,
    PERIOD_OPEN,
    PERIOD_REPORTED,
    PETITION_DENIED,
    PETITION_FILED,
    PETITION_REASON_COMMUNITY_PREFERENCE_CHANGE,
    PETITION_UNDER_REVIEW,
    PETITION_WITHDRAWN,
    PROPOSAL_DRAFT,
    PROPOSAL_SUBMIT,
    PROPOSAL_SUBMITTED,
    PROPOSAL_WITHDRAW,
    PROPOSAL_WITHDRAWN,
    SERVICE_LEVEL_ENHANCED,
    SOLICITATION_AWARDED,
    SOLICITATION_CLOSE,
    SOLICITATION_CLOSED,
    SOLICITATION_OPEN,
    STANDING_DEBAR,
    STANDING_PLACE_ON_PROBATION,
    STANDING_REINSTATE,
    STANDING_SUSPEND,
)
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    OFFICER,
    OFFICER_SECOND,
    USER_OFFICER_SECOND,
)


# ─── newly_created_rows_start_in_their_declared_initial_state ─────────

def test_community_carrier_and_solicitation_open_in_their_declared_initial_states(api: ApiClient):
    """A freshly created community, carrier and solicitation each start in the state their machine declares, with the solicitation's award fields still empty.

    "A newly opened solicitation has `status` `OPEN`, `round_number` 1, `created_reason` `INITIAL`, `preference_filing_count` 0, and neither a `selected_proposal_id` nor a `candidate_count_at_award` yet."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_state
    """
    fx.set_clock(api, DEFAULT_CLOCK)

    community = validate_success(api.create_community(f.community_payload(), ADMIN), 201)
    assert community["status"] == COMMUNITY_REGISTERED

    carrier = validate_success(api.create_carrier(f.carrier_payload(), ADMIN), 201)
    assert carrier["status"] == CARRIER_ACTIVE

    get_success_data(
        api.create_eligibility_determination(
            community["id"], f.determination_payload(), ANALYST
        )
    )
    solicitation = validate_success(
        api.create_solicitation(f.solicitation_payload(community["id"]), ADMIN), 201
    )
    assert solicitation["status"] == SOLICITATION_OPEN
    assert solicitation["round_number"] == 1
    assert solicitation["created_reason"] == CREATED_REASON_INITIAL
    assert solicitation["preference_filing_count"] == 0
    assert solicitation.get("selected_proposal_id") is None
    assert solicitation.get("candidate_count_at_award") is None


def test_new_proposal_starts_draft_and_not_evaluated_in_both_dimensions(api: ApiClient):
    """A brand-new proposal is simultaneously DRAFT in the submission dimension and NOT_EVALUATED in the evaluation dimension, with no score yet.

    "A fresh draft opens with `submission_state` `DRAFT`, `evaluation_state` `NOT_EVALUATED`, and no `composite_score`."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_state
    """
    reference = fx.make_reference_data(api, clock=DEFAULT_CLOCK, fuel_month=None)
    solicitation = fx.open_solicitation(api, reference.community_id)

    proposal = validate_success(
        api.create_proposal(
            f.proposal_payload(
                solicitation["id"], reference.carrier_id, reference.aircraft_type_id
            ),
            reference.carrier_headers,
        ),
        201,
    )
    assert proposal["submission_state"] == PROPOSAL_DRAFT
    assert proposal["evaluation_state"] == EVAL_NOT_EVALUATED
    assert proposal.get("composite_score") is None
    assert_versioned_row(proposal, expected_version=1)


# ─── petition_review_then_denial_walks_the_declared_path ──────────────

def test_petition_opened_for_review_then_denied_records_the_decision_trail(api: ApiClient):
    """Opening review moves the petition to UNDER_REVIEW with no decision stamped yet, and the denial that follows records the deciding officer and the note.

    "Every terminal decision records `decided_by_user_id` and `decision_note`."

    Design: Corner/state_machines/petition_review_then_denial_walks_the_declared_path
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    petition = fx.file_petition(
        api, award.agreement, narrative="chronic misconnects at the hub"
    )
    assert petition["status"] == PETITION_FILED

    opened = validate_success(
        api.petition_decision(
            petition["id"],
            f.petition_decision_payload(DECISION_OPEN_REVIEW, decision_note="docketed"),
            OFFICER,
        )
    )
    assert opened["status"] == PETITION_UNDER_REVIEW
    assert opened["return_count"] == 0
    assert opened.get("decided_by_user_id") is None

    denied = validate_success(
        api.petition_decision(
            petition["id"],
            f.petition_decision_payload(
                DECISION_DENY, decision_note="quality remedied under existing terms"
            ),
            OFFICER_SECOND,
        )
    )
    assert denied["status"] == PETITION_DENIED
    assert denied["decided_by_user_id"] == USER_OFFICER_SECOND
    assert denied["decision_note"] == "quality remedied under existing terms"


def test_petition_denial_leaves_the_agreement_community_and_rounds_alone(api: ApiClient):
    """Denying a petition changes only the petition: the agreement stays ACTIVE and unterminated, the community stays SUBSIDIZED with one agreement, and no replacement round opens.

    "The three terminal-ish decisions all require the petition to be `UNDER_REVIEW`: **denying** it moves it to `DENIED`, while the two grant branches also require the target agreement's `status` to be `ACTIVE`."

    Design: Corner/state_machines/petition_review_then_denial_walks_the_declared_path
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    petition = fx.petition_under_review(api, award.agreement)
    validate_success(
        api.petition_decision(
            petition["id"],
            f.petition_decision_payload(DECISION_DENY, decision_note="no cause shown"),
            OFFICER,
        )
    )

    agreement = validate_success(api.get_service_agreement(award.agreement_id, ADMIN))
    assert agreement["status"] == AGREEMENT_ACTIVE
    assert agreement.get("terminated_at") is None

    community = validate_success(api.get_community(award.community_id, ADMIN))
    assert community["status"] == COMMUNITY_SUBSIDIZED
    assert community["active_agreement_count"] == 1

    rows, meta = validate_paginated(
        api.list_community_solicitations(
            award.community_id, ADMIN, {"created_reason": CREATED_REASON_REPLACEMENT}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


# ─── petition_return_for_info_loops_back_and_counts ───────────────────

def test_returning_a_petition_for_information_loops_it_back_and_counts_each_lap(api: ApiClient):
    """Two laps of OPEN_REVIEW then RETURN_FOR_INFO leave the petition back in FILED with return_count 2 and still no decision stamped.

    "**Returning for information** moves it `UNDER_REVIEW → FILED`, increases `return_count` by 1 and records the note — the cycle `FILED → UNDER_REVIEW → FILED` may repeat as often as the officer needs."

    Design: Corner/state_machines/petition_return_for_info_loops_back_and_counts
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    petition = fx.file_petition(
        api,
        award.agreement,
        reason_code=PETITION_REASON_COMMUNITY_PREFERENCE_CHANGE,
        narrative="council prefers jet service",
    )

    opened = validate_success(
        api.petition_decision(
            petition["id"],
            f.petition_decision_payload(DECISION_OPEN_REVIEW, decision_note="lap 1"),
            OFFICER,
        )
    )
    assert opened["status"] == PETITION_UNDER_REVIEW

    returned = validate_success(
        api.petition_decision(
            petition["id"],
            f.petition_decision_payload(
                DECISION_RETURN_FOR_INFO, decision_note="need enplanement detail"
            ),
            OFFICER,
        )
    )
    assert returned["status"] == PETITION_FILED
    assert returned["return_count"] == 1
    assert returned["decision_note"] == "need enplanement detail"

    opened_again = validate_success(
        api.petition_decision(
            petition["id"],
            f.petition_decision_payload(DECISION_OPEN_REVIEW, decision_note="lap 2"),
            OFFICER,
        )
    )
    assert opened_again["status"] == PETITION_UNDER_REVIEW
    assert opened_again["return_count"] == 1

    returned_again = validate_success(
        api.petition_decision(
            petition["id"],
            f.petition_decision_payload(
                DECISION_RETURN_FOR_INFO, decision_note="still short"
            ),
            OFFICER,
        )
    )
    assert returned_again["status"] == PETITION_FILED
    assert returned_again["return_count"] == 2
    assert returned_again.get("decided_by_user_id") is None


def test_petition_can_still_be_withdrawn_from_filed_after_two_return_laps(api: ApiClient):
    """After two return laps the community can still withdraw its own petition from FILED, which keeps return_count at 2 and leaves the agreement ACTIVE.

    "Withdrawal is admissible from `FILED` or `UNDER_REVIEW`, requires the acting `X-User-ID` to equal the petition's `community_id`, and moves the petition to `WITHDRAWN` while touching neither the agreement nor the community."

    Design: Corner/state_machines/petition_return_for_info_loops_back_and_counts
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    petition = fx.file_petition(
        api,
        award.agreement,
        reason_code=PETITION_REASON_COMMUNITY_PREFERENCE_CHANGE,
        narrative="council prefers jet service",
    )
    for lap in ("lap 1", "lap 2"):
        get_success_data(
            api.petition_decision(
                petition["id"],
                f.petition_decision_payload(DECISION_OPEN_REVIEW, decision_note=lap),
                OFFICER,
            )
        )
        get_success_data(
            api.petition_decision(
                petition["id"],
                f.petition_decision_payload(
                    DECISION_RETURN_FOR_INFO, decision_note=f"more detail after {lap}"
                ),
                OFFICER,
            )
        )

    withdrawn = validate_success(
        api.withdraw_petition(
            petition["id"],
            f.petition_withdraw_payload(withdraw_note="council reversed itself"),
            award.community_headers,
        )
    )
    assert withdrawn["status"] == PETITION_WITHDRAWN
    assert withdrawn["return_count"] == 2

    agreement = validate_success(api.get_service_agreement(award.agreement_id, ADMIN))
    assert agreement["status"] == AGREEMENT_ACTIVE


# ─── petition_decision_from_wrong_state_is_refused ────────────────────

def test_decisions_other_than_opening_review_are_refused_from_filed(api: ApiClient):
    """Granting with hold-in, denying and returning for information are each refused while the petition is still FILED, and the petition keeps its untouched decision fields.

    "Any decision attempted from a status the action does not admit — opening review from something other than `FILED`, or any other decision from something other than `UNDER_REVIEW` — is refused with `ERR_PETITION_NOT_DECIDABLE`."

    Design: Corner/state_machines/petition_decision_from_wrong_state_is_refused
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    petition = fx.file_petition(api, award.agreement, narrative="petition A")

    for action in (
        DECISION_GRANT_WITH_HOLD_IN,
        DECISION_DENY,
        DECISION_RETURN_FOR_INFO,
    ):
        response = api.petition_decision(
            petition["id"],
            f.petition_decision_payload(action, decision_note="skipping review"),
            OFFICER,
        )
        validate_error(response, E.ERR_PETITION_NOT_DECIDABLE, 409)

    stored = validate_success(api.get_termination_petition(petition["id"], ADMIN))
    assert stored["status"] == PETITION_FILED
    assert stored["return_count"] == 0
    assert stored.get("decision_note") is None
    assert stored.get("decided_by_user_id") is None

    agreement = validate_success(api.get_service_agreement(award.agreement_id, ADMIN))
    assert agreement["status"] == AGREEMENT_ACTIVE
    community = validate_success(api.get_community(award.community_id, ADMIN))
    assert community["status"] == COMMUNITY_SUBSIDIZED


def test_opening_review_on_a_withdrawn_petition_is_refused(api: ApiClient):
    """A withdrawn petition cannot be revived: opening review on it is refused and it stays WITHDRAWN.

    "`GRANTED_IMMEDIATE`, `DENIED`, `WITHDRAWN` and `CLOSED` are terminal petition states."

    Design: Corner/state_machines/petition_decision_from_wrong_state_is_refused
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    petition = fx.file_petition(api, award.agreement, narrative="petition B")
    withdrawn = get_success_data(
        api.withdraw_petition(
            petition["id"],
            f.petition_withdraw_payload(withdraw_note="duplicate filing"),
            award.community_headers,
        )
    )
    assert withdrawn["status"] == PETITION_WITHDRAWN

    response = api.petition_decision(
        petition["id"],
        f.petition_decision_payload(
            DECISION_OPEN_REVIEW, decision_note="reviving a withdrawn petition"
        ),
        OFFICER,
    )
    validate_error(response, E.ERR_PETITION_NOT_DECIDABLE, 409)

    stored = validate_success(api.get_termination_petition(petition["id"], ADMIN))
    assert stored["status"] == PETITION_WITHDRAWN


# ─── debarred_carrier_and_withdrawn_proposal_are_locked ───────────────

def _withdrawn_proposal_of_a_debarred_carrier(api: ApiClient):
    """A DRAFT proposal withdrawn by its carrier, whose carrier is then debarred."""
    reference = fx.make_reference_data(api, clock=DEFAULT_CLOCK, fuel_month=None)
    solicitation = fx.open_solicitation(api, reference.community_id)
    proposal = fx.draft_proposal(
        api, solicitation["id"], reference.carrier_id, reference.aircraft_type_id
    )
    proposal = get_success_data(
        api.proposal_action(
            proposal["id"],
            f.proposal_action_payload(PROPOSAL_WITHDRAW),
            reference.carrier_headers,
        )
    )
    assert proposal["submission_state"] == PROPOSAL_WITHDRAWN
    carrier = get_success_data(
        api.carrier_standing_action(
            reference.carrier_id,
            f.carrier_standing_payload(STANDING_DEBAR, note="certificate revoked"),
            ADMIN,
        )
    )
    assert carrier["status"] == CARRIER_DEBARRED
    return reference, proposal


def test_every_standing_action_on_a_debarred_carrier_is_refused(api: ApiClient):
    """Reinstating, suspending or placing a debarred carrier on probation are all refused and the carrier stays DEBARRED.

    "Debarring moves it to `DEBARRED` from `ACTIVE`, `PROBATION` or `SUSPENDED`, and withdraws the carrier from every open competition by moving each of its proposals whose `submission_state` is `DRAFT` to `WITHDRAWN`; `DEBARRED` is terminal, so any standing action against an already-debarred carrier is refused with `ERR_CARRIER_NOT_ACTIONABLE`."

    Design: Corner/state_machines/debarred_carrier_and_withdrawn_proposal_are_locked
    """
    reference, _proposal = _withdrawn_proposal_of_a_debarred_carrier(api)

    for action, note in (
        (STANDING_REINSTATE, "appeal granted"),
        (STANDING_SUSPEND, "belt and braces"),
        (STANDING_PLACE_ON_PROBATION, "downgrade"),
    ):
        response = api.carrier_standing_action(
            reference.carrier_id, f.carrier_standing_payload(action, note=note), ADMIN
        )
        validate_error(response, E.ERR_CARRIER_NOT_ACTIONABLE, 409)

    carrier = validate_success(api.get_carrier(reference.carrier_id, ADMIN))
    assert carrier["status"] == CARRIER_DEBARRED


def test_both_proposal_actions_on_a_withdrawn_proposal_are_refused(api: ApiClient):
    """A withdrawn proposal can be neither submitted nor withdrawn again, and both refusals leave both of its dimensions untouched.

    "**Withdrawing** moves the proposal to `submission_state` `WITHDRAWN` from either `DRAFT` or `SUBMITTED` and changes nothing else; a proposal that is already `WITHDRAWN` cannot be withdrawn again and the attempt is refused with `ERR_PROPOSAL_NOT_SUBMITTABLE`."

    Design: Corner/state_machines/debarred_carrier_and_withdrawn_proposal_are_locked
    """
    reference, proposal = _withdrawn_proposal_of_a_debarred_carrier(api)

    resubmit = api.proposal_action(
        proposal["id"],
        f.proposal_action_payload(PROPOSAL_SUBMIT),
        reference.carrier_headers,
    )
    validate_error(resubmit, E.ERR_PROPOSAL_NOT_SUBMITTABLE, 409)

    rewithdraw = api.proposal_action(
        proposal["id"],
        f.proposal_action_payload(PROPOSAL_WITHDRAW),
        reference.carrier_headers,
    )
    validate_error(rewithdraw, E.ERR_PROPOSAL_NOT_SUBMITTABLE, 409)

    stored = validate_success(api.get_proposal(proposal["id"], ADMIN))
    assert stored["submission_state"] == PROPOSAL_WITHDRAWN
    assert stored["evaluation_state"] == EVAL_NOT_EVALUATED


# ─── repeating_a_completed_transition_is_refused ──────────────────────

def test_replaying_a_completed_submit_is_refused(api: ApiClient):
    """A proposal that is already SUBMITTED and under evaluation refuses a second SUBMIT rather than silently accepting it.

    "The proposal must currently be in `DRAFT`, or the request is refused with `ERR_PROPOSAL_NOT_SUBMITTABLE`."

    Design: Corner/state_machines/repeating_a_completed_transition_is_refused
    """
    reference = fx.make_reference_data(api, clock=DEFAULT_CLOCK, fuel_month=None)
    solicitation = fx.open_solicitation(api, reference.community_id)
    proposal = fx.submitted_proposal(
        api, solicitation["id"], reference.carrier_id, reference.aircraft_type_id
    )
    fx.close_solicitation(api, solicitation["id"])

    replay = api.proposal_action(
        proposal["id"],
        f.proposal_action_payload(PROPOSAL_SUBMIT),
        reference.carrier_headers,
    )
    validate_error(replay, E.ERR_PROPOSAL_NOT_SUBMITTABLE, 409)

    stored = validate_success(api.get_proposal(proposal["id"], ADMIN))
    assert stored["submission_state"] == PROPOSAL_SUBMITTED
    assert stored["evaluation_state"] == EVAL_UNDER_EVALUATION


def test_replaying_a_completed_close_is_refused(api: ApiClient):
    """Closing an already CLOSED solicitation is refused and the round is not reopened or renumbered by the attempt.

    "**Closing** a round moves it `OPEN → CLOSED` and is refused with `ERR_SOLICITATION_NOT_OPEN` from any other status; as it closes, every proposal of that solicitation whose `submission_state` is `SUBMITTED` and whose `evaluation_state` is still `NOT_EVALUATED` moves `NOT_EVALUATED → UNDER_EVALUATION`, which is how the candidate pool for scoring is formed."

    Design: Corner/state_machines/repeating_a_completed_transition_is_refused
    """
    reference = fx.make_reference_data(api, clock=DEFAULT_CLOCK, fuel_month=None)
    solicitation = fx.open_solicitation(api, reference.community_id)
    fx.submitted_proposal(
        api, solicitation["id"], reference.carrier_id, reference.aircraft_type_id
    )
    closed = fx.close_solicitation(api, solicitation["id"])
    assert closed["status"] == SOLICITATION_CLOSED

    replay = api.solicitation_action(
        solicitation["id"],
        f.solicitation_action_payload(SOLICITATION_CLOSE, note="closing again"),
        ADMIN,
    )
    validate_error(replay, E.ERR_SOLICITATION_NOT_OPEN, 409)

    stored = validate_success(api.get_solicitation(solicitation["id"], ADMIN))
    assert stored["status"] == SOLICITATION_CLOSED
    assert stored["round_number"] == 1
    assert stored["preference_filing_count"] == 0


# ─── debar_withdraws_only_the_carriers_draft_proposals ────────────────

def test_debar_withdraws_only_the_debarred_carriers_draft_proposals(api: ApiClient):
    """Debarring one carrier withdraws only its own DRAFT bid, sparing its SUBMITTED bid elsewhere and a peer carrier's DRAFT bid in the same round.

    "Debarring moves it to `DEBARRED` from `ACTIVE`, `PROBATION` or `SUSPENDED`, and withdraws the carrier from every open competition by moving each of its proposals whose `submission_state` is `DRAFT` to `WITHDRAWN`; `DEBARRED` is terminal, so any standing action against an already-debarred carrier is refused with `ERR_CARRIER_NOT_ACTIONABLE`."

    Design: Corner/state_machines/debar_withdraws_only_the_carriers_draft_proposals
    """
    reference = fx.make_reference_data(api, clock=DEFAULT_CLOCK, fuel_month=None)
    dodge = fx.register_second_community(api)
    hays_round = fx.open_solicitation(api, reference.community_id)
    dodge_round = fx.open_solicitation(api, dodge["id"])

    own_draft = fx.draft_proposal(
        api, hays_round["id"], reference.carrier_id, reference.aircraft_type_id
    )
    own_submitted = fx.submitted_proposal(
        api, dodge_round["id"], reference.carrier_id, reference.aircraft_type_id
    )
    peer_draft = fx.draft_proposal(
        api,
        hays_round["id"],
        reference.second_carrier_id,
        reference.aircraft_type_id,
        service_level=SERVICE_LEVEL_ENHANCED,
        weekly_round_trips=13,
        annual_subsidy_request_usd=1700000.00,
        payment_basis=PAYMENT_BASIS_SCHEDULED_FLIGHT_FLAT,
    )

    debarred = validate_success(
        api.carrier_standing_action(
            reference.carrier_id,
            f.carrier_standing_payload(STANDING_DEBAR, note="certificate revoked"),
            ADMIN,
        )
    )
    assert debarred["status"] == CARRIER_DEBARRED

    cascaded = validate_success(api.get_proposal(own_draft["id"], ADMIN))
    assert cascaded["submission_state"] == PROPOSAL_WITHDRAWN
    assert cascaded["evaluation_state"] == EVAL_NOT_EVALUATED

    spared = validate_success(api.get_proposal(own_submitted["id"], ADMIN))
    assert spared["submission_state"] == PROPOSAL_SUBMITTED

    peer = validate_success(api.get_proposal(peer_draft["id"], ADMIN))
    assert peer["submission_state"] == PROPOSAL_DRAFT

    for solicitation_id in (hays_round["id"], dodge_round["id"]):
        stored = validate_success(api.get_solicitation(solicitation_id, ADMIN))
        assert stored["status"] == SOLICITATION_OPEN


# ─── close_moves_only_submitted_proposals_under_evaluation ────────────

def _closed_round_with_one_submitted_and_one_draft(api: ApiClient):
    """Close a round holding one SUBMITTED bid and one DRAFT bid."""
    reference = fx.make_reference_data(api, clock=DEFAULT_CLOCK, fuel_month=None)
    solicitation = fx.open_solicitation(api, reference.community_id)
    submitted = fx.submitted_proposal(
        api, solicitation["id"], reference.carrier_id, reference.aircraft_type_id
    )
    draft = fx.draft_proposal(
        api,
        solicitation["id"],
        reference.second_carrier_id,
        reference.aircraft_type_id,
        service_level=SERVICE_LEVEL_ENHANCED,
        weekly_round_trips=13,
        annual_subsidy_request_usd=1700000.00,
        payment_basis=PAYMENT_BASIS_SCHEDULED_FLIGHT_FLAT,
    )
    return reference, solicitation, submitted, draft


def test_closing_a_round_moves_only_its_submitted_proposals_under_evaluation(api: ApiClient):
    """Closing the round promotes the SUBMITTED bid to UNDER_EVALUATION while the DRAFT bid in the same round stays NOT_EVALUATED and outside the candidate set.

    "**Closing** a round moves it `OPEN → CLOSED` and is refused with `ERR_SOLICITATION_NOT_OPEN` from any other status; as it closes, every proposal of that solicitation whose `submission_state` is `SUBMITTED` and whose `evaluation_state` is still `NOT_EVALUATED` moves `NOT_EVALUATED → UNDER_EVALUATION`, which is how the candidate pool for scoring is formed."

    Design: Corner/state_machines/close_moves_only_submitted_proposals_under_evaluation
    """
    _reference, solicitation, submitted, draft = _closed_round_with_one_submitted_and_one_draft(api)

    closed = validate_success(
        api.solicitation_action(
            solicitation["id"],
            f.solicitation_action_payload(SOLICITATION_CLOSE, note="window over"),
            ADMIN,
        )
    )
    assert closed["status"] == SOLICITATION_CLOSED

    candidate = validate_success(api.get_proposal(submitted["id"], ADMIN))
    assert candidate["submission_state"] == PROPOSAL_SUBMITTED
    assert candidate["evaluation_state"] == EVAL_UNDER_EVALUATION

    bystander = validate_success(api.get_proposal(draft["id"], ADMIN))
    assert bystander["submission_state"] == PROPOSAL_DRAFT
    assert bystander["evaluation_state"] == EVAL_NOT_EVALUATED


def test_ranking_preview_sees_one_candidate_and_writes_nothing_back(api: ApiClient):
    """The ranking preview of the closed round reports the single candidate as the leader and leaves that proposal without a stored score.

    "The preview persists nothing at all — no scores are written and no states move."

    Design: Corner/state_machines/close_moves_only_submitted_proposals_under_evaluation
    """
    _reference, solicitation, submitted, draft = _closed_round_with_one_submitted_and_one_draft(api)
    fx.close_solicitation(api, solicitation["id"])

    ranking = validate_success(api.get_ranking(solicitation["id"], OFFICER))
    assert ranking["candidate_count"] == 1
    assert ranking["top_proposal_id"] == submitted["id"]
    assert ranking["ranked_proposal_ids"] == [submitted["id"]]
    assert_ratio(ranking["top_composite_score"], 60.0000, "top_composite_score")

    unscored = validate_success(api.get_proposal(submitted["id"], ADMIN))
    assert unscored.get("composite_score") is None
    assert unscored["evaluation_state"] == EVAL_UNDER_EVALUATION

    untouched = validate_success(api.get_proposal(draft["id"], ADMIN))
    assert untouched["evaluation_state"] == EVAL_NOT_EVALUATED


# ─── award_books_the_obligation_and_marks_the_community ───────────────

def _closed_single_candidate_round(api: ApiClient):
    """Reference data with a published 2026-08 fuel index and one closed round."""
    reference = fx.make_reference_data(api, clock=DEFAULT_CLOCK)
    solicitation = fx.open_solicitation(api, reference.community_id)
    proposal = fx.submitted_proposal(
        api, solicitation["id"], reference.carrier_id, reference.aircraft_type_id
    )
    fx.close_solicitation(api, solicitation["id"])
    return reference, solicitation, proposal


def test_award_copies_the_winning_terms_and_derives_the_service_floors(api: ApiClient):
    """The selection order books an ACTIVE agreement carrying the winning terms verbatim, the derived monthly seat and block-hour floors, the baseline fuel index and the two-year rate window.

    "It derives `min_monthly_seats` — the monthly seat-availability floor a later performance review measures against — as the committed weekly round trips multiplied by two, multiplied by the winning proposal's `seats_per_departure`, multiplied by 52 weeks and divided by 12 months, with the fractional part discarded."

    Design: Corner/state_machines/award_books_the_obligation_and_marks_the_community
    """
    reference, solicitation, proposal = _closed_single_candidate_round(api)

    agreement = validate_success(
        api.create_selection_order(
            solicitation["id"],
            f.selection_order_payload(order_note="sole responsive proposal"),
            OFFICER,
        ),
        201,
    )

    assert agreement["status"] == AGREEMENT_ACTIVE
    assert agreement["community_id"] == reference.community_id
    assert agreement["carrier_id"] == reference.carrier_id
    assert agreement["proposal_id"] == proposal["id"]

    assert agreement["min_weekly_round_trips"] == 12
    assert agreement["min_monthly_seats"] == 1976
    assert_one_decimal(agreement["annual_block_hours"], 1872.0, "annual_block_hours")
    assert_money(agreement["annual_subsidy_usd"], 1600000.00, "annual_subsidy_usd")
    assert agreement["term_months"] == 24
    assert agreement["payment_basis"] == PAYMENT_BASIS_COMPLETED_FLIGHT_PRORATION

    assert_ratio(agreement["baseline_fuel_index_usd"], 2.4000, "baseline_fuel_index_usd")
    assert_instant(agreement["rate_effective_from"], DEFAULT_CLOCK, "rate_effective_from")
    assert_instant(
        agreement["rate_effective_to"], "2028-08-01T00:00:00Z", "rate_effective_to"
    )
    assert agreement.get("predecessor_agreement_id") is None
    assert_versioned_row(agreement, expected_version=1)


def test_award_opens_the_obligation_ledger_at_the_committed_total(api: ApiClient):
    """The new agreement opens its ledger at 3,200,000.00 committed with nothing disbursed, no hold-in premium paid and every cumulative departure counter at zero.

    "And it opens the ledger: `total_committed_usd` is the annual subsidy multiplied by `term_months` and divided by 12, rounded half-up to cents; `disbursed_to_date_usd` and `hold_in_premium_paid_usd` start at 0.00; `obligated_remaining_usd` is the committed total less the disbursed total, rounded to cents."

    Design: Corner/state_machines/award_books_the_obligation_and_marks_the_community
    """
    _reference, solicitation, _proposal = _closed_single_candidate_round(api)

    agreement = validate_success(
        api.create_selection_order(
            solicitation["id"], f.selection_order_payload(), OFFICER
        ),
        201,
    )

    assert_money(agreement["total_committed_usd"], 3200000.00, "total_committed_usd")
    assert_money(agreement["disbursed_to_date_usd"], 0.00, "disbursed_to_date_usd")
    assert_money(
        agreement["obligated_remaining_usd"], 3200000.00, "obligated_remaining_usd"
    )
    assert_money(
        agreement["hold_in_premium_paid_usd"], 0.00, "hold_in_premium_paid_usd"
    )
    assert_obligation_identity(agreement)

    assert agreement["cumulative_scheduled_departures"] == 0
    assert agreement["cumulative_completed_departures"] == 0
    assert agreement["cumulative_cancelled_carrier_departures"] == 0
    assert agreement["cumulative_cancelled_weather_departures"] == 0
    assert_departure_identity(agreement)


def test_award_marks_the_community_and_records_the_candidate_count(api: ApiClient):
    """The same selection order moves the community to SUBSIDIZED with one agreement, records the winner and the candidate count on the round, and stores the winner's score.

    "If the community is `ELIGIBLE` it moves `ELIGIBLE → SUBSIDIZED`; if it was already `SUBSIDIZED` and this is an additional, non-overlapping agreement it stays `SUBSIDIZED`; in both cases `active_agreement_count` increases by 1."

    Design: Corner/state_machines/award_books_the_obligation_and_marks_the_community
    """
    reference, solicitation, proposal = _closed_single_candidate_round(api)
    assert reference.community["status"] == COMMUNITY_ELIGIBLE

    get_success_data(
        api.create_selection_order(
            solicitation["id"], f.selection_order_payload(), OFFICER
        ),
        expected_status=201,
    )

    community = validate_success(api.get_community(reference.community_id, ADMIN))
    assert community["status"] == COMMUNITY_SUBSIDIZED
    assert community["active_agreement_count"] == 1

    awarded = validate_success(api.get_solicitation(solicitation["id"], ADMIN))
    assert awarded["status"] == SOLICITATION_AWARDED
    assert awarded["selected_proposal_id"] == proposal["id"]
    assert awarded["candidate_count_at_award"] == 1

    winner = validate_success(api.get_proposal(proposal["id"], ADMIN))
    assert winner["evaluation_state"] == EVAL_SELECTED
    assert_ratio(winner["composite_score"], 60.0000, "composite_score")


# ─── certification_requires_every_earlier_month_settled ───────────────

MONTH_COUNTS = {
    "scheduled_departures": 100,
    "completed_departures": 100,
    "cancelled_carrier_departures": 0,
    "cancelled_weather_departures": 0,
    "seats_offered": 1900,
    "passengers_enplaned": 700,
}


def test_certification_is_refused_while_an_earlier_month_is_still_open(api: ApiClient):
    """A fully reported September cannot be certified while August of the same agreement is still OPEN, and the refusal creates no payment.

    "It is refused with `ERR_PERIOD_NOT_CERTIFIABLE` when the period is in any other status, and also when any earlier month of the same agreement is still `OPEN` — months are settled in order."

    Design: Corner/state_machines/certification_requires_every_earlier_month_settled
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    august = fx.open_period(api, award.agreement_id, "2026-08")
    september = fx.open_period(api, award.agreement_id, "2026-09")
    reported = fx.file_report(
        api, september["id"], award.carrier_id, **MONTH_COUNTS
    )
    assert reported["status"] == PERIOD_REPORTED

    response = api.certify_service_period(
        september["id"], f.certify_payload(certification_note="out of order"), ADMIN
    )
    validate_error(response, E.ERR_PERIOD_NOT_CERTIFIABLE, 409)

    stored_september = validate_success(api.get_service_period(september["id"], ADMIN))
    assert stored_september["status"] == PERIOD_REPORTED
    stored_august = validate_success(api.get_service_period(august["id"], ADMIN))
    assert stored_august["status"] == PERIOD_OPEN

    rows, meta = validate_paginated(
        api.list_subsidy_payments(ADMIN, {"service_period_id": september["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_certification_succeeds_once_the_earlier_month_has_been_settled(api: ApiClient):
    """Once August is reported and certified, the identical September certification is accepted, and each month computes the same 133,333.00 net payment without disbursing anything.

    "Certification is the `ProgramAdmin`'s act, takes an optional `certification_note`, and moves the period `REPORTED → CERTIFIED`."

    Design: Corner/state_machines/certification_requires_every_earlier_month_settled
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    august = fx.open_period(api, award.agreement_id, "2026-08")
    september = fx.open_period(api, award.agreement_id, "2026-09")
    fx.file_report(api, september["id"], award.carrier_id, **MONTH_COUNTS)
    validate_error(
        api.certify_service_period(september["id"], f.certify_payload(), ADMIN),
        E.ERR_PERIOD_NOT_CERTIFIABLE,
        409,
    )

    fx.file_report(api, august["id"], award.carrier_id, **MONTH_COUNTS)
    certified_august = validate_success(
        api.certify_service_period(
            august["id"], f.certify_payload(certification_note="august settled"), ADMIN
        )
    )
    assert certified_august["status"] == PERIOD_CERTIFIED

    august_rows, august_meta = validate_paginated(
        api.list_subsidy_payments(ADMIN, {"service_period_id": august["id"]})
    )
    assert august_meta["total_count"] == 1
    august_payment = august_rows[0]
    assert august_payment["status"] == PAYMENT_COMPUTED
    assert august_payment["variant_used"] == PAYMENT_BASIS_COMPLETED_FLIGHT_PRORATION
    assert_money(
        august_payment["monthly_entitlement_usd"], 133333.33, "monthly_entitlement_usd"
    )
    assert_money(
        august_payment["per_departure_rate_usd"], 1333.33, "per_departure_rate_usd"
    )
    assert august_payment["credited_departures"] == 100
    assert_money(august_payment["gross_subsidy_usd"], 133333.00, "gross_subsidy_usd")
    assert_money(
        august_payment["cancellation_adjustment_usd"], 0.00, "cancellation_adjustment_usd"
    )
    assert_money(august_payment["withholding_pct"], 0.00, "withholding_pct")
    assert_money(august_payment["net_payment_usd"], 133333.00, "net_payment_usd")

    certified_september = validate_success(
        api.certify_service_period(
            september["id"],
            f.certify_payload(certification_note="september settled"),
            ADMIN,
        )
    )
    assert certified_september["status"] == PERIOD_CERTIFIED

    september_rows, september_meta = validate_paginated(
        api.list_subsidy_payments(ADMIN, {"service_period_id": september["id"]})
    )
    assert september_meta["total_count"] == 1
    assert september_rows[0]["status"] == PAYMENT_COMPUTED
    assert_money(september_rows[0]["net_payment_usd"], 133333.00, "net_payment_usd")

    agreement = validate_success(api.get_service_agreement(award.agreement_id, ADMIN))
    assert_money(
        agreement["obligated_remaining_usd"], 3200000.00, "obligated_remaining_usd"
    )
    assert_money(agreement["disbursed_to_date_usd"], 0.00, "disbursed_to_date_usd")
    assert_obligation_identity(agreement)


# ─── carrier_suspension_reaches_only_its_active_agreements ────────────

def test_carrier_suspension_cascades_only_to_its_active_agreements(api: ApiClient):
    """Suspending a carrier that holds one ACTIVE and one already SUSPENDED agreement moves only the ACTIVE one, leaves the other row untouched, and keeps both communities SUBSIDIZED.

    "Suspending moves it to `SUSPENDED` from either `ACTIVE` or `PROBATION`, and every agreement of that carrier whose `status` is `ACTIVE` moves `ACTIVE → SUSPENDED` with it."

    Design: Corner/state_machines/carrier_suspension_reaches_only_its_active_agreements
    """
    reference = fx.make_reference_data(
        api, clock=DEFAULT_CLOCK, with_second_carrier=False
    )
    hays_award = fx.build_award(api, ref=reference)

    dodge = fx.register_second_community(api)
    dodge_round = fx.open_solicitation(api, dodge["id"])
    fx.submitted_proposal(
        api, dodge_round["id"], reference.carrier_id, reference.aircraft_type_id
    )
    fx.close_solicitation(api, dodge_round["id"])
    dodge_agreement = fx.issue_selection_order(api, dodge_round["id"])

    presuspended = get_success_data(
        api.agreement_status_action(
            dodge_agreement["id"],
            f.agreement_status_payload(
                AGREEMENT_SUSPEND, note="pre-existing suspension"
            ),
            ADMIN,
        )
    )
    assert presuspended["status"] == AGREEMENT_SUSPENDED
    frozen_version = presuspended["version"]

    carrier = validate_success(
        api.carrier_standing_action(
            reference.carrier_id,
            f.carrier_standing_payload(STANDING_SUSPEND, note="safety finding"),
            ADMIN,
        )
    )
    assert carrier["status"] == CARRIER_SUSPENDED
    assert carrier["consecutive_watch_count"] == 0

    cascaded = validate_success(
        api.get_service_agreement(hays_award.agreement_id, ADMIN)
    )
    assert cascaded["status"] == AGREEMENT_SUSPENDED
    assert_money(cascaded["total_committed_usd"], 3200000.00, "total_committed_usd")
    assert_money(
        cascaded["obligated_remaining_usd"], 3200000.00, "obligated_remaining_usd"
    )

    spared = validate_success(api.get_service_agreement(dodge_agreement["id"], ADMIN))
    assert spared["status"] == AGREEMENT_SUSPENDED
    assert spared["version"] == frozen_version

    for community_id in (reference.community_id, dodge["id"]):
        community = validate_success(api.get_community(community_id, ADMIN))
        assert community["status"] == COMMUNITY_SUBSIDIZED
        assert community["active_agreement_count"] == 1
