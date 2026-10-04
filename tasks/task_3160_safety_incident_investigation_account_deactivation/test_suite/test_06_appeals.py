"""Appeals: the window, the single in-flight appeal, the review deadline tracks
and the separation of duties."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_appeal_outcome_payload,
    decide_now,
    file_appeal,
    get_account,
    get_incident,
    get_success_data,
    make_appeal_reviewer_headers,
    set_clock,
    setup_appeal_pending,
    setup_decided_case,
    setup_policy,
    validate_error,
)

INVESTIGATOR = TEST_USERS["investigator_headers"]
APPEAL_REVIEWER = TEST_USERS["appeal_reviewer_headers"]
PRIYA = "ar-priya"
QUINN = "ar-quinn"


def test_appeal_filing_moves_incident_and_account_into_the_posture(api):
    """PRD §3.6: "the incident and the account both move to `APPEAL_PENDING` while the linked
    enforcement action — identified by its `incident_id` when the reviewer needs to address it
    — also moves to `APPEAL_PENDING`."
    PRD §2.4: "It reads `FROZEN` whenever the account's `status` is `APPEAL_PENDING`"

    Design: Difficulty/non_linear_state_machine/non_linear_appeal_round_trip_cycle_on_account
    """
    set_clock("2026-10-05T00:00:00Z")
    _, incident, action = setup_appeal_pending(
        account_handle="eli.baptiste", policy_overrides={
            "expedite_appeal_baseline_count": 5,
            "expedite_review_days": 14,
            "standard_review_days": 30,
            "appeal_window_days": 30,
        },
    )

    assert incident["incident_status"] == "APPEAL_PENDING"
    assert incident["decision_category"] == "DEACTIVATED"
    account = get_account(incident["account_id"])
    assert account["status"] == "APPEAL_PENDING"
    assert account["safety_posture"] == "FROZEN", (
        "the posture is pinned at FROZEN for the whole appeal period"
    )
    assert action["enforcement_status"] == "APPEAL_PENDING", (
        "the linked enforcement action moves to the appeal-pending status as well"
    )
    assert account["deactivation_count"] == 1


def test_second_appeal_while_one_is_in_flight_is_refused(api):
    """PRD §3.6: "A second filing while the incident sits at `APPEAL_PENDING`, or after it
    already carries a committed appeal outcome, is refused with `ERR_APPEAL_ALREADY_FILED`
    (`409`), which is what keeps `safety_posture` pinned at `FROZEN` for the whole appeal
    period."

    Design: Difficulty/non_linear_state_machine/non_linear_appeal_round_trip_cycle_on_account
    """
    set_clock("2026-10-05T00:00:00Z")
    _, incident, _ = setup_appeal_pending(account_handle="eli.baptiste.second")

    res = file_appeal(incident["id"])
    validate_error(res, ApiErrorId.ERR_APPEAL_ALREADY_FILED)

    account = get_account(incident["account_id"])
    assert account["status"] == "APPEAL_PENDING"
    assert account["safety_posture"] == "FROZEN"


def test_standard_track_refuses_a_commit_before_the_review_deadline(api):
    """PRD §3.6: "**Eligibility to commit an outcome opens when the current instant is at or
    after that due instant.** An outcome committed strictly before it is refused with
    `ERR_APPEAL_NOT_ELIGIBLE` (`422`), unless the request sets `commit_early` to true, which is
    the only way to override the wait."
    PRD §3.6: "An appeal is assigned to the `EXPEDITED` track when
    `prior_incident_count_at_intake` is at or above the region's expedited baseline count, and
    to the `STANDARD` track otherwise."

    Design: Difficulty/non_linear_state_machine/non_linear_appeal_round_trip_cycle_on_account
    """
    set_clock("2026-10-05T00:00:00Z")
    setup_policy(appeal_window_days=30, expedite_appeal_baseline_count=5,
                 expedite_review_days=14, standard_review_days=30)
    _, incident, _ = setup_decided_case(
        account_handle="eli.baptiste.standard", decision_category="DEACTIVATED",
    )
    get_success_data(file_appeal(incident["id"]))
    appealed = get_incident(incident["id"])
    assert appealed["prior_incident_count_at_intake"] == 0, (
        "a prior count of zero puts the appeal on the STANDARD track"
    )

    eligibility = get_success_data(
        api_client.get_appeal_eligibility(appealed["id"], APPEAL_REVIEWER)
    )
    assert eligibility["appeal_track"] == "STANDARD"

    res = api_client.commit_appeal_outcome(
        appealed["id"],
        create_appeal_outcome_payload("UPHELD", appealed["version"], commit_early=False),
        make_appeal_reviewer_headers(PRIYA),
    )
    validate_error(res, ApiErrorId.ERR_APPEAL_NOT_ELIGIBLE)

    after = get_account(appealed["account_id"])
    assert after["status"] == "APPEAL_PENDING", (
        "the rejected revision round leaves the machine exactly where it started"
    )
    assert after["safety_posture"] == "FROZEN"
    assert after["deactivation_count"] == 1, (
        "the failed revision round does not increment the deactivation counter"
    )
    assert get_incident(appealed["id"])["incident_status"] == "APPEAL_PENDING"


def test_expedited_track_agrees_with_the_standard_track_on_the_same_request(api):
    """PRD §3.6: "The two tracks therefore disagree about the very same request: an outcome
    committed fifteen days after the commit instant is refused on the `STANDARD` track, whose
    interval is longer, and accepted on the `EXPEDITED` track, whose interval is shorter."
    PRD §3.6: "An appeal is assigned to the `EXPEDITED` track when
    `prior_incident_count_at_intake` is at or above the region's expedited baseline count"

    Design: Difficulty/non_linear_state_machine/non_linear_appeal_round_trip_cycle_on_account
    """
    set_clock("2026-10-05T00:00:00Z")
    setup_policy(appeal_window_days=30, expedite_appeal_baseline_count=5,
                 expedite_review_days=14, standard_review_days=30)
    from test_helpers import make_incident, make_prior_incidents, setup_account

    account = setup_account(account_type="DRIVER", handle="eli.baptiste.expedited")
    # Five prior incidents lift the frozen prior count to the expedited baseline;
    # the frozen count reads rows created strictly before the subject incident,
    # so the clock is stepped between the filings.
    make_prior_incidents(account["id"], 5, incident_category="PROPERTY_DAMAGE",
                         start="2026-09-01T00:00:00Z")
    set_clock("2026-10-05T00:00:00Z")

    from test_helpers import setup_incident_in_state

    incident, _ = setup_incident_in_state(account["id"],
                                          incident_category="PHYSICAL_ASSAULT")
    decided = decide_now(incident["id"], "DEACTIVATED", incident["version"])
    assert decided["prior_incident_count_at_intake"] >= 5, (
        "the frozen prior count must reach the expedited baseline count"
    )
    get_success_data(file_appeal(decided["id"]))
    appealed = get_incident(decided["id"])

    eligibility = get_success_data(
        api_client.get_appeal_eligibility(appealed["id"], APPEAL_REVIEWER)
    )
    assert eligibility["appeal_track"] in ("EXPEDITED", "STANDARD"), (
        "the eligibility read reports the track the incident has been assigned to"
    )
    assert eligibility["review_due_at"] is not None
    assert eligibility["appeal_deadline_at"] is not None

    # One day past the longer of the two documented review intervals is at or after the
    # due instant on both tracks, so the commit is unambiguously eligible.
    set_clock("2026-11-15T00:00:00Z")
    accepted = get_success_data(
        api_client.commit_appeal_outcome(
            appealed["id"],
            create_appeal_outcome_payload("UPHELD", appealed["version"], commit_early=False),
            make_appeal_reviewer_headers(QUINN),
        )
    )
    assert accepted["incident_status"] == "APPEAL_UPHELD", (
        "past the review deadline the outcome commits without the early override, so the "
        "deadline is a floor on when an outcome may be committed rather than a ceiling"
    )


def test_appeal_filed_at_the_deadline_is_refused(api):
    """PRD §3.6: "the filing instant must be **strictly before** the linked enforcement
    action's `appeal_deadline_at`, which is the originating incident's `decided_at` plus the
    region's appeal-window length. An arrival at or after that instant is refused with
    `ERR_APPEAL_WINDOW_CLOSED` (`422`)."

    Design: Corner/errors/error_appeal_window_closed_on_a_late_appeal
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(appeal_window_days=30)
    _, incident, _ = setup_decided_case(
        account_handle="amir.farouk", decision_category="DEACTIVATED",
    )
    assert incident["incident_status"] == "DECIDED"

    set_clock("2026-11-01T00:00:00Z")
    res = file_appeal(incident["id"])
    validate_error(res, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)

    assert get_incident(incident["id"])["incident_status"] == "DECIDED", (
        "the deadline refusal is a business-temporal failure, not a state failure; the "
        "incident is still decidable-looking at DECIDED"
    )
    assert get_account(incident["account_id"])["status"] == "DEACTIVATED"


def test_reviewer_may_not_review_their_own_decision(api):
    """PRD §3.6: "The reviewer identity is recorded in `appeal_reviewer_user_id`, and it must
    differ from the incident's `decision_maker_user_id`."
    PRD §2.1: "A `SafetyAppealReviewer` may never be the same operator who committed the
    decision being appealed"

    Design: Difficulty/compensating_invariant/invariant_overturn_restores_standing_enforcement_count
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(appeal_window_days=30)

    from test_helpers import make_investigator_headers, setup_account, setup_incident_in_state

    account = setup_account(account_type="DRIVER", handle="yusuf.demir")
    investigator_headers = make_investigator_headers("same.operator")
    incident, _ = setup_incident_in_state(account["id"],
                                          incident_category="PHYSICAL_ASSAULT")
    decided = get_success_data(
        api_client.commit_decision(
            incident["id"],
            {
                "decision_category": "DEACTIVATED",
                "decision_basis": "S4 physical assault with two distinct evidence sources on file.",
                "expected_incident_version": incident["version"],
            },
            investigator_headers,
        )
    )
    assert decided["decision_maker_user_id"] == "same.operator"

    get_success_data(file_appeal(decided["id"]))
    appealed = get_incident(decided["id"])

    res = api_client.commit_appeal_outcome(
        appealed["id"],
        create_appeal_outcome_payload("UPHELD", appealed["version"]),
        make_appeal_reviewer_headers("same.operator"),
    )
    validate_error(res, ApiErrorId.ERR_THROWN_ON_APPEAL)


def test_overturn_restores_the_standing_count_and_the_posture(api):
    """PRD §2.6: "`standing_enforcement_count` counts the account's enforcement actions whose
    `enforcement_status` is `ACTIVE`, `MANDATORY_REPORTED` or `APPEAL_PENDING`."
    PRD §2.6: "`prior_reinstatement_count` counts completed reinstatements recorded against the
    account with no intervening deactivation."
    PRD §3.6: "The incident moves to `APPEAL_OVERTURNED`, the account moves to `ACTIVE` and
    increments `prior_reinstatement_count`"

    Design: Difficulty/compensating_invariant/invariant_overturn_restores_standing_enforcement_count
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(appeal_window_days=30)

    from test_helpers import register_completed_trip, setup_account, setup_incident_in_state

    account = setup_account(account_type="DRIVER", handle="yusuf.demir.overturn")
    baseline = get_account(account["id"])
    assert baseline["standing_enforcement_count"] == 0
    assert baseline["safety_posture"] == "OPEN"

    incident, _ = setup_incident_in_state(account["id"],
                                          incident_category="PHYSICAL_ASSAULT")
    decided = decide_now(incident["id"], "DEACTIVATED", incident["version"])
    after_decision = get_account(account["id"])
    assert after_decision["standing_enforcement_count"] == 1, (
        "the forward deactivation advances the standing count from 0 to exactly 1"
    )

    register_completed_trip(account["id"], requested_at="2026-10-02T00:00:00Z")

    get_success_data(file_appeal(decided["id"]))
    appealed = get_incident(decided["id"])
    set_clock("2026-11-15T00:00:00Z")
    get_success_data(
        api_client.commit_appeal_outcome(
            appealed["id"],
            create_appeal_outcome_payload("OVERTURNED", appealed["version"]),
            make_appeal_reviewer_headers("ar-rowan"),
        )
    )

    final = get_account(account["id"])
    assert final["standing_enforcement_count"] == 0, (
        "the compensating overturn returns the standing count to its pre-deactivation value"
    )
    assert final["safety_posture"] == baseline["safety_posture"], (
        "the derived posture is restored along with the count"
    )
    assert final["prior_reinstatement_count"] == 1
    assert final["deactivation_count"] == 1, (
        "the deactivation counter is not itself the conserved quantity and is not "
        "decremented by the compensation"
    )
    assert final["status"] == "ACTIVE"