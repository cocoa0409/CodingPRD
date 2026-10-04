"""Validation priority: which of two simultaneously violated gates a single
request reports."""
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
    make_incident,
    make_appeal_reviewer_headers,
    set_clock,
    setup_account,
    setup_incident_in_state,
    setup_policy,
    validate_error,
)

INVESTIGATOR = TEST_USERS["investigator_headers"]

S4_EVIDENCE = [
    {"evidence_type": "TRIP_DATA", "evidence_weight": "DISPOSITIVE"},
    {"evidence_type": "LAW_ENFORCEMENT_CONTACT", "evidence_weight": "DISPOSITIVE"},
    {"evidence_type": "EXTERNAL_RECORD", "evidence_weight": "DISPOSITIVE"},
]


def test_in_flight_appeal_gate_outranks_the_state_check_on_a_decision(api):
    """PRD §3.4: "Two specialised prohibitions are asserted ahead of the shared state check on
    this surface. A deactivation cannot be committed while the account carries an enforcement
    action in `ACTIVE`, `MANDATORY_REPORTED` or `APPEAL_PENDING` status — the attempt is refused
    with `ERR_IN_FLIGHT_APPEAL` (`409`)."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_state_beats_business_safety_on_decision
    """
    set_clock("2026-10-06T00:00:00Z")
    setup_policy(sd_floor_severity="S4", appeal_window_days=30)
    account = setup_account(account_type="DRIVER", handle="nadia.ba")

    first, _ = setup_incident_in_state(account["id"],
                                       incident_category="PHYSICAL_ASSAULT",
                                       evidence_specs=S4_EVIDENCE)
    first_frozen = get_success_data(api_client.get_incident(first["id"], INVESTIGATOR))
    decide_now(first["id"], "DEACTIVATED", first_frozen["version"])

    standing = get_account(account["id"])
    assert standing["standing_enforcement_count"] == 1, (
        "the first decision left a standing enforcement action on the account, which is "
        "what the in-flight-appeal gate reads"
    )

    # A second incident that was never held or investigated, so it sits at OPEN and has no
    # declared edge to the decided state.
    second = make_incident(account["id"], incident_category="PHYSICAL_ASSAULT")
    assert second["incident_status"] == "OPEN"
    assert get_incident(second["id"])["incident_status"] == "OPEN"

    res = api_client.commit_decision(
        second["id"],
        {
            "decision_category": "DEACTIVATED",
            "decision_basis": "Second S4 physical assault while the first enforcement action is still standing.",
            "expected_incident_version": second["version"],
        },
        INVESTIGATOR,
    )
    validate_error(res, ApiErrorId.ERR_IN_FLIGHT_APPEAL)
    assert res.status_code == 409, (
        "the specialised prohibition is asserted ahead of the shared state check, so the "
        "in-flight-appeal identifier is the one reported"
    )

    after = get_incident(second["id"])
    assert after["incident_status"] == "OPEN", (
        "the refused request performs no transition and creates no enforcement action"
    )
    assert after["decision_category"] == "PENDING"
    assert get_account(account["id"])["deactivation_count"] == 1, (
        "the refused request produced no fresh deactivation side effect"
    )


def test_state_error_pre_empts_the_appeal_window_gate_on_a_refiled_appeal(api):
    """PRD §3.2: "of these, `DECIDED`, `APPEAL_UPHELD`, `APPEAL_OVERTURNED` and `WITHDRAWN` are
    terminal."
    PRD §3.6: "An arrival at or after that instant is refused with `ERR_APPEAL_WINDOW_CLOSED`
    (`422`)."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_state_beats_temporal_below_hold_floor
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(sd_floor_severity="S4", appeal_window_days=30,
                 expedite_review_days=14, standard_review_days=30)
    account = setup_account(account_type="DRIVER", handle="omar.haddad")

    incident, _ = setup_incident_in_state(account["id"],
                                          incident_category="PHYSICAL_ASSAULT",
                                          evidence_specs=S4_EVIDENCE)
    decided = decide_now(incident["id"], "DEACTIVATED", incident["version"])
    get_success_data(file_appeal(decided["id"]))
    appealed = get_incident(decided["id"])

    set_clock("2026-10-20T00:00:00Z")
    upheld = get_success_data(
        api_client.commit_appeal_outcome(
            appealed["id"],
            create_appeal_outcome_payload("UPHELD", appealed["version"], commit_early=True),
            make_appeal_reviewer_headers("ar-quinn"),
        )
    )
    assert upheld["incident_status"] == "APPEAL_UPHELD", (
        "the early commit is the documented override for the review-deadline wait"
    )

    res = api_client.file_appeal(upheld["id"], TEST_USERS["appeal_reviewer_headers"])
    assert res.status_code == 409, (
        "a re-filing against an incident that already carries a committed appeal is refused"
    )

    body = res.json()["data"]
    assert body["error_id"] != "ERR_APPEAL_WINDOW_CLOSED", (
        "the terminal state outranks the business-temporal window check on the same request"
    )
    reloaded = get_incident(upheld["id"])
    assert reloaded["incident_status"] == "APPEAL_UPHELD", (
        "the terminal state is a lockdown, so the refused filing changes nothing"
    )
    assert get_account(account["id"])["status"] == "DEACTIVATED"


def test_hold_on_a_below_floor_incident_reports_the_severity_gate(api):
    """PRD §3.2: "An incident whose `severity` is `S1` or `S2` is below the floor required to
    open a hold and the request is refused with `ERR_SEVERITY_BELOW_HOLD_FLOOR` (`422`)."
    PRD §3.2: "Once an incident is `OPEN` and its `severity` is `S3` or `S4` and its
    `account_id` matches the account being acted on, a `SafetyInvestigator` may place an
    **interim hold**"

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_state_beats_temporal_below_hold_floor
    """
    set_clock("2026-10-06T00:00:00Z")
    setup_policy(sd_floor_severity="S4")
    set_clock("2026-09-01T00:00:00Z")
    account = setup_account(account_type="DRIVER", handle="omar.haddad.floor")
    low = make_incident(account["id"], incident_category="PROPERTY_DAMAGE")
    set_clock("2026-10-06T00:00:00Z")
    assert low["severity"] == "S1", (
        "the category alone derives the lowest band when no prior reports exist"
    )

    res = api_client.hold_incident(low["id"], INVESTIGATOR)
    validate_error(res, ApiErrorId.ERR_SEVERITY_BELOW_HOLD_FLOOR)
    assert res.status_code == 422

    assert get_incident(low["id"])["incident_status"] == "OPEN"
    assert get_account(account["id"])["status"] == "ACTIVE", (
        "the refusal suppresses every later check and every side effect"
    )