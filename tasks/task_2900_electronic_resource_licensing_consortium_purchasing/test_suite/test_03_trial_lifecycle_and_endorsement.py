"""Trial windows, stakeholder feedback and the two endorsement score variants."""

from test_helpers import (
    SINGLE_CRITERION,
    TWO_CRITERIA_60_40,
    assert_trial,
    close_trial,
    create_draft_trial,
    feedback_payload,
    make_librarian_headers,
    open_trial,
    read_trial,
    setup_catalog,
    submit_feedback_rows,
    trial_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_opening_a_draft_trial_moves_it_to_active(api):
    """The declared opening trigger flips the status and leaves the scores alone.

    PRD: "Opening a trial advances it `DRAFT → ACTIVE` and is available only to
    the librarian that owns it."

    PRD: "Most resources additionally carry `updated_at` — same format as
    `created_at`, refreshed on every mutation of the row — and `version`, an
    integer that starts at 1 when the row is created and increments by exactly 1
    on every mutation."

    Design: Corner/state_machines/opening_a_draft_trial_moves_it_to_active
    """
    scenario = setup_catalog()
    member_id = scenario["member"]["id"]
    trial = create_draft_trial(scenario["product"]["id"], member_id,
                              "2026-08-01", "2026-08-31")

    response = api.open_trial(trial["id"], make_librarian_headers(member_id))
    data = validate_success(response)

    assert_trial(data)
    assert data["id"] == trial["id"]
    assert data["status"] == "ACTIVE"
    assert data["provisional_score"] is None, "opening stamps no score"
    assert data["final_score"] is None
    assert data["version"] == 2, "the opening is one mutation of the trial row"


def test_closing_a_trial_that_was_never_opened_is_rejected(api):
    """There is no direct edge out of DRAFT into CLOSED.

    PRD: "Closing a trial advances it `ACTIVE → CLOSED`, is likewise restricted
    to the owning librarian, and does real work on the way: it stamps
    `provisional_score` and refreshes `feedback_count` and
    `distinct_stakeholder_group_count`."

    Design: Corner/state_machines/closing_a_trial_that_was_never_opened_is_rejected
    """
    scenario = setup_catalog()
    member_id = scenario["member"]["id"]
    trial = create_draft_trial(scenario["product"]["id"], member_id)

    response = api.close_trial(trial["id"], make_librarian_headers(member_id))
    validate_error(response, "ERR_TRIAL_INVALID_STATE", 409)

    stored = read_trial(trial["id"])
    assert stored["status"] == "DRAFT", "the refused close moved nothing"
    assert stored["provisional_score"] is None, "no score was stamped"


def test_opening_the_same_trial_twice_is_rejected_on_the_second_call(api):
    """The opening trigger is not idempotent: there is no ACTIVE to ACTIVE edge.

    PRD: "Three conditions guard the opening: the trial must be in `DRAFT`, the
    owning member must be `IN_GOOD_STANDING`, and the logical clock's calendar
    date must fall strictly before the trial's `end_date` — there is no point
    opening a window that has already closed."

    Design: Corner/state_machines/opening_the_same_trial_twice_is_rejected_on_the_second_call
    """
    scenario = setup_catalog()
    member_id = scenario["member"]["id"]
    trial = create_draft_trial(scenario["product"]["id"], member_id)
    open_trial(trial["id"], member_id)

    response = api.open_trial(trial["id"], make_librarian_headers(member_id))
    validate_error(response, "ERR_TRIAL_INVALID_STATE", 409)

    stored = read_trial(trial["id"])
    assert stored["status"] == "ACTIVE"
    assert stored["version"] == 2, "the refused second opening is not a mutation"


def test_feedback_with_an_undeclared_criterion_code_is_rejected(api, admin):
    """A score against a criterion the trial never declared cannot be stored.

    PRD: "If `criterion_code` is not one of the codes the trial declared, the
    submission is refused with `ERR_UNKNOWN_CRITERION` (422)."

    Design: Corner/validations/feedback_with_an_undeclared_criterion_code_is_rejected
    """
    scenario = setup_catalog()
    member_id = scenario["member"]["id"]
    trial = create_draft_trial(scenario["product"]["id"], member_id,
                               trial_criteria=SINGLE_CRITERION)
    open_trial(trial["id"], member_id)

    response = api.submit_feedback(trial["id"],
                                   feedback_payload("FACULTY", "PRICE_VALUE", 90),
                                   make_librarian_headers(member_id))
    validate_error(response, "ERR_UNKNOWN_CRITERION", 422)

    stored = read_trial(trial["id"])
    assert stored["feedback_count"] == 0, "an unknown criterion never enters the average"
    assert stored["distinct_stakeholder_group_count"] == 0
    assert stored["status"] == "ACTIVE"

    _, meta = validate_paginated(api.list_trial_feedback(trial["id"], admin))
    assert meta["total_count"] == 0


def test_evaluating_a_trial_with_two_feedback_rows_is_rejected(api, admin):
    """Two stakeholder rows are not enough evidence to fork the trial.

    PRD: "The trial must be in `CLOSED`, and its `feedback_count` must be at
    least 3 rows — fewer is `ERR_INSUFFICIENT_FEEDBACK` (409)."

    Design: Corner/validations/evaluating_a_trial_with_two_feedback_rows_is_rejected
    """
    scenario = setup_catalog()
    member_id = scenario["member"]["id"]
    trial = create_draft_trial(scenario["product"]["id"], member_id,
                               trial_criteria=SINGLE_CRITERION)
    open_trial(trial["id"], member_id)
    submit_feedback_rows(trial["id"], member_id,
                         [("FACULTY", "CONTENT_FIT", 90),
                          ("GRADUATE", "CONTENT_FIT", 90)])
    closed = close_trial(trial["id"], member_id)
    assert float(closed["provisional_score"]) == 90.00

    response = api.evaluate_trial(trial["id"], admin)
    validate_error(response, "ERR_INSUFFICIENT_FEEDBACK", 409)

    stored = read_trial(trial["id"])
    assert stored["status"] == "CLOSED", "the refused evaluation did not fork the trial"
    assert stored["feedback_count"] == 2
    assert float(stored["provisional_score"]) == 90.00, (
        "the score stamped at close survives the refusal"
    )
    assert stored["final_score"] is None


# The four stakeholder rows behind the diverging score pair.  CONTENT_FIT keeps
# the same two rows in both variants and averages (1.5*60 + 1.25*70) / 2.75 =
# 64.55; INTERFACE averages 100.00 while the trial is ACTIVE and (0.5*100 +
# 1.0*75) / 1.5 = 83.33 once the post-close row joins it.
_ACTIVE_ROWS = [
    ("FACULTY", "CONTENT_FIT", 60),
    ("LIBRARIAN", "CONTENT_FIT", 70),
    ("UNDERGRADUATE", "INTERFACE", 100),
]
_POST_CLOSE_ROW = ("GRADUATE", "INTERFACE", 75)


def _trial_with_a_post_close_row():
    """A CLOSED trial carrying three ACTIVE-window rows and one grace-period row."""
    scenario = setup_catalog()
    member_id = scenario["member"]["id"]
    trial = create_draft_trial(scenario["product"]["id"], member_id,
                               trial_criteria=TWO_CRITERIA_60_40)
    open_trial(trial["id"], member_id)
    submit_feedback_rows(trial["id"], member_id, _ACTIVE_ROWS)
    scenario["closed"] = close_trial(trial["id"], member_id)
    scenario["late_feedback"] = submit_feedback_rows(
        trial["id"], member_id, [_POST_CLOSE_ROW])[0]
    scenario["trial"] = trial
    scenario["member_id"] = member_id
    return scenario


def test_trial_scores_diverge_when_a_row_arrives_after_the_close(api, admin):
    """Evaluation stores a final score below the provisional one on the same row.

    PRD: "The **provisional** computation runs when the trial is closed and is
    written to `provisional_score`. It includes only feedback rows whose
    `submitted_during_status` is `ACTIVE`, and it never applies the quorum
    penalty."

    PRD: "The **final** computation runs when the collections office evaluates
    the trial and is written to `final_score`. It includes feedback rows whose
    `submitted_during_status` is `ACTIVE` **or** `CLOSED`, so scores gathered
    during the post-close grace period do count."

    Design: Difficulty/dual_variant_calc/trial_provisional_and_final_scores_diverge_on_post_close_feedback
    """
    scenario = _trial_with_a_post_close_row()

    response = api.evaluate_trial(scenario["trial"]["id"], admin)
    data = validate_success(response)

    assert_trial(data)
    assert float(data["provisional_score"]) == 78.73, (
        "0.60 * 64.55 + 0.40 * 100.00, the ACTIVE-window rows only"
    )
    assert float(data["final_score"]) == 72.06, (
        "0.60 * 64.55 + 0.40 * 83.33, once the grace-period row is counted"
    )
    assert data["status"] == "ENDORSED"
    assert data["quorum_penalty_applied"] is False, "four distinct groups met the quorum"
    assert data["feedback_count"] == 4
    assert data["distinct_stakeholder_group_count"] == 4


def test_post_close_feedback_is_stamped_closed_and_leaves_the_provisional_score(api, admin):
    """The grace-period row is marked CLOSED and never rewrites the provisional score.

    PRD: "On acceptance the server stamps two fields the client cannot set:
    `submitted_during_status`, holding the trial's status at the instant of
    acceptance and therefore either `ACTIVE` or `CLOSED`, and
    `submitted_by_user_id`, holding the acting librarian's `X-User-ID` for audit
    only — that identifier never influences a price or an ordering."

    PRD: "For each criterion, gather the feedback rows of this trial whose
    `criterion_code` equals that criterion's `code` and whose
    `submitted_during_status` is one of the statuses the variant includes."

    Design: Difficulty/dual_variant_calc/trial_provisional_and_final_scores_diverge_on_post_close_feedback
    """
    scenario = _trial_with_a_post_close_row()
    trial_id = scenario["trial"]["id"]

    assert float(scenario["closed"]["provisional_score"]) == 78.73
    assert scenario["closed"]["feedback_count"] == 3, "the close saw three rows"
    assert scenario["late_feedback"]["submitted_during_status"] == "CLOSED"

    before = read_trial(trial_id)
    assert float(before["provisional_score"]) == 78.73, (
        "accepting a grace-period row does not re-stamp the provisional score"
    )
    assert before["final_score"] is None
    assert before["feedback_count"] == 4

    validate_success(api.evaluate_trial(trial_id, admin))

    stored = read_trial(trial_id)
    assert float(stored["provisional_score"]) == 78.73
    assert float(stored["final_score"]) == 72.06
    assert stored["status"] == "ENDORSED"

    rows, meta = validate_paginated(api.list_trial_feedback(trial_id, admin))
    assert meta["total_count"] == 4
    assert sum(1 for row in rows if row["submitted_during_status"] == "CLOSED") == 1


def _trial_at_the_endorsement_threshold():
    """A CLOSED trial whose weighted average lands on exactly 70.00."""
    scenario = setup_catalog()
    member_id = scenario["member"]["id"]
    trial = create_draft_trial(scenario["product"]["id"], member_id,
                               trial_criteria=SINGLE_CRITERION)
    open_trial(trial["id"], member_id)
    submit_feedback_rows(trial["id"], member_id,
                         [("FACULTY", "CONTENT_FIT", 70),
                          ("GRADUATE", "CONTENT_FIT", 70),
                          ("LIBRARIAN", "CONTENT_FIT", 70)])
    scenario["closed"] = close_trial(trial["id"], member_id)
    scenario["trial"] = trial
    scenario["member_id"] = member_id
    return scenario


def test_final_score_of_exactly_seventy_endorses_the_trial(api, admin):
    """The threshold comparison is inclusive, so 70.00 endorses rather than declines.

    PRD: "Then, if `final_score` is greater than or equal to 70.00, the trial
    advances `CLOSED → ENDORSED`; a final score of exactly 70.00 endorses."

    PRD: "The numerator is the sum, over the matching rows, of the row's
    stakeholder weight multiplied by its `score`; the denominator is the sum of
    those same stakeholder weights."

    Design: Difficulty/boundary_precision_check/trial_final_score_exactly_at_endorsement_threshold_endorses
    """
    scenario = _trial_at_the_endorsement_threshold()

    response = api.evaluate_trial(scenario["trial"]["id"], admin)
    data = validate_success(response)

    assert_trial(data)
    assert float(data["provisional_score"]) == 70.00, (
        "(1.5 + 1.0 + 1.25) weights all scoring 70 average to exactly 70.00"
    )
    assert float(data["final_score"]) == 70.00
    assert data["quorum_penalty_applied"] is False, "three distinct groups met the quorum"
    assert data["distinct_stakeholder_group_count"] == 3
    assert data["feedback_count"] == 3
    assert data["status"] == "ENDORSED", "at the threshold the fork goes to ENDORSED"


def test_threshold_endorsement_is_persisted_and_not_a_decline(api, admin):
    """The boundary fork is stored, terminal, and never reads DECLINED.

    PRD: "If `final_score` is strictly below 70.00, the trial advances `CLOSED →
    DECLINED` instead."

    PRD: "Whichever way the fork goes, the same two fields are written first:
    `final_score` receives the final computation's result and
    `quorum_penalty_applied` records whether the 0.90 multiplier was applied."

    Design: Difficulty/boundary_precision_check/trial_final_score_exactly_at_endorsement_threshold_endorses
    """
    scenario = _trial_at_the_endorsement_threshold()
    trial_id = scenario["trial"]["id"]

    assert float(scenario["closed"]["provisional_score"]) == 70.00
    validate_success(api.evaluate_trial(trial_id, admin))

    stored = read_trial(trial_id)
    assert stored["status"] == "ENDORSED"
    assert stored["status"] != "DECLINED", "70.00 is not strictly below the threshold"
    assert float(stored["final_score"]) == 70.00
    assert stored["quorum_penalty_applied"] is False

    data, meta = validate_paginated(
        api.list_trials(admin, {"member_id": scenario["member_id"], "status": "DECLINED"})
    )
    assert meta["total_count"] == 0, "no declined trial exists for this member"
    assert data == []


def test_second_trial_starting_inside_the_cooldown_buffer_is_rejected(api, admin):
    """A window that clears the previous window but not its cooldown is refused.

    PRD: "A conflict exists when both of two conditions hold: the new trial's
    `start_date` falls strictly before the existing trial's `end_date` advanced
    by a thirty-day cooldown buffer, and the existing trial's `start_date` falls
    strictly before the new trial's `end_date`."

    Design: Difficulty/resource_temporal_overlap/second_trial_starting_inside_the_cooldown_buffer_is_rejected
    """
    scenario = setup_catalog()
    product_id = scenario["product"]["id"]
    member_id = scenario["member"]["id"]
    first = create_draft_trial(product_id, member_id, "2026-08-01", "2026-08-31")

    response = api.create_trial(
        product_id,
        trial_payload(member_id, "2026-09-29", "2026-10-29", SINGLE_CRITERION),
        make_librarian_headers(member_id),
    )
    validate_error(response, "ERR_TRIAL_WINDOW_CONFLICT", 409)

    assert read_trial(first["id"])["status"] == "DRAFT", "the existing trial is untouched"
    _, meta = validate_paginated(
        api.list_trials(admin, {"product_id": product_id, "member_id": member_id})
    )
    assert meta["total_count"] == 1, "the refused setup created no second trial row"


def test_second_trial_starting_on_the_cooldown_boundary_is_accepted(api, admin):
    """A start exactly on the buffered end is not strictly before it, so it fits.

    PRD: "A conflict exists when both of two conditions hold: the new trial's
    `start_date` falls strictly before the existing trial's `end_date` advanced
    by a thirty-day cooldown buffer, and the existing trial's `start_date` falls
    strictly before the new trial's `end_date`."

    PRD: "Setup is refused with `ERR_TRIAL_WINDOW_CONFLICT` (409) when any
    existing trial on the same product and member pair — in *any* status
    whatsoever, including `WITHDRAWN`, `DECLINED` and `ENDORSED` — conflicts with
    the requested window."

    Design: Difficulty/resource_temporal_overlap/second_trial_starting_inside_the_cooldown_buffer_is_rejected
    """
    scenario = setup_catalog()
    product_id = scenario["product"]["id"]
    member_id = scenario["member"]["id"]
    create_draft_trial(product_id, member_id, "2026-08-01", "2026-08-31")

    response = api.create_trial(
        product_id,
        trial_payload(member_id, "2026-09-30", "2026-10-30", SINGLE_CRITERION),
        make_librarian_headers(member_id),
    )
    data = validate_success(response, expected_status=201)

    assert_trial(data)
    assert data["start_date"] == "2026-09-30", (
        "2026-08-31 advanced by the thirty-day buffer is 2026-09-30, which the "
        "new start does not fall strictly before"
    )
    assert data["end_date"] == "2026-10-30"
    assert data["status"] == "DRAFT"

    _, meta = validate_paginated(
        api.list_trials(admin, {"product_id": product_id, "member_id": member_id})
    )
    assert meta["total_count"] == 2
