"""The interim hold, its release, terminal lockdowns and withdrawal."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_account,
    get_incident,
    get_success_data,
    make_incident,
    make_prior_incidents,
    set_clock,
    setup_account,
    setup_decided_case,
    setup_policy,
    validate_error,
    validate_success,
)

INVESTIGATOR = TEST_USERS["investigator_headers"]
OPERATIONS_LEAD = TEST_USERS["operations_lead_headers"]


def test_hold_writes_both_state_machines_in_lockstep(api):
    """PRD §3.2: "a hold always writes both `account.status = UNDER_HOLD` and
    `incident.incident_status = INVESTIGATING`"

    Design: Corner/state_machines/incident_hold_is_idempotent_on_a_second_attempt
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    account = setup_account(account_type="DRIVER", handle="kira.sandoval")
    incident = make_incident(account["id"], incident_category="PHYSICAL_ASSAULT")
    assert incident["incident_status"] == "OPEN"

    held = get_success_data(api_client.hold_incident(incident["id"], INVESTIGATOR))

    assert held["incident_status"] == "INVESTIGATING", (
        "the hold moves the incident out of the open state into the investigation"
    )
    assert get_account(account["id"])["status"] == "UNDER_HOLD", (
        "the hold simultaneously moves the account to the under-hold status"
    )


def test_repeated_hold_is_refused_and_suppresses_the_account_only_once(api):
    """PRD §3.2: "Once an incident is `OPEN` and its `severity` is `S3` or `S4` and its
    `account_id` matches the account being acted on, a `SafetyInvestigator` may place an
    **interim hold**"
    PRD §3.2: "Releasing a hold is the inverse operation and its destination depends on what
    the account still carries."

    Design: Corner/state_machines/incident_hold_is_idempotent_on_a_second_attempt
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    account = setup_account(account_type="DRIVER", handle="kira.sandoval.twice")
    incident = make_incident(account["id"], incident_category="PHYSICAL_ASSAULT")

    first = get_success_data(api_client.hold_incident(incident["id"], INVESTIGATOR))
    assert first["incident_status"] == "INVESTIGATING"

    second = api_client.hold_incident(incident["id"], INVESTIGATOR)
    validate_error(second, ApiErrorId.ERR_INVALID_STATE)

    after = get_account(account["id"])
    assert after["status"] == "UNDER_HOLD", (
        "the investigation state has no hold self-edge, so the refusal leaves the "
        "suppression applied exactly once"
    )
    assert get_incident(incident["id"])["version"] == first["version"], (
        "the refused request performs no transition, so the incident's version is untouched"
    )


def test_decision_from_the_open_state_is_refused(api):
    """PRD §3.4: "an incident that is not in a state from which the requested transition is
    declared — a withdrawn incident, for instance — is refused with `ERR_INVALID_STATE`
    (`409`), with no enforcement action created."
    PRD §3.4: "A `SafetyInvestigator` commits it once the incident sits at `PENDING_DECISION`"

    Design: Corner/state_machines/incident_decision_from_open_state_is_rejected
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    account = setup_account(account_type="DRIVER", handle="jonas.weiss")
    incident = make_incident(account["id"], incident_category="PHYSICAL_ASSAULT")

    res = api_client.commit_decision(
        incident["id"],
        {
            "decision_category": "DEACTIVATED",
            "decision_basis": "Attempted straight from intake without any investigation round trip.",
            "expected_incident_version": incident["version"],
        },
        INVESTIGATOR,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    assert get_incident(incident["id"])["incident_status"] == "OPEN"
    account_after = get_account(account["id"])
    assert account_after["status"] == "ACTIVE", (
        "no side effect of the refused decision reached the account"
    )
    assert account_after["standing_enforcement_count"] == 0, (
        "no enforcement action was created by the refused decision"
    )

    # The superseded hold path is still available from the same state.
    held = validate_success(api_client.hold_incident(incident["id"], INVESTIGATOR), 200)
    assert held["incident_status"] == "INVESTIGATING"


def test_decided_incident_is_sealed_against_a_hold(api):
    """PRD §3.2: "And an incident that has already reached `DECIDED` is under terminal
    lockdown — a hold placed against it performs no transition, is rejected with
    `ERR_INVALID_STATE` (`409`), and leaves the account's status untouched."

    Design: Corner/state_machines/incident_withdraw_is_refused_once_the_incident_is_decided
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    account, decided, _ = setup_decided_case(
        account_handle="milo.frost", incident_category="PHYSICAL_ASSAULT",
        decision_category="DEACTIVATED",
    )
    before = get_account(account["id"])

    res = api_client.hold_incident(decided["id"], INVESTIGATOR)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    assert get_incident(decided["id"])["incident_status"] == "DECIDED"
    after = get_account(account["id"])
    assert after["status"] == before["status"] == "DEACTIVATED", (
        "the refused hold leaves the account's status untouched"
    )


def test_second_withdraw_is_refused_on_a_withdrawn_incident(api):
    """PRD §3.2: "Withdrawal moves the incident to `WITHDRAWN`, creates **no** enforcement
    action at all"
    PRD §3.2: "`WITHDRAWN`; of these, `DECIDED`, `APPEAL_UPHELD`, `APPEAL_OVERTURNED` and
    `WITHDRAWN` are terminal."

    Design: Corner/state_machines/incident_withdraw_is_refused_once_the_incident_is_decided
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    account = setup_account(handle="lena.doyle")
    incident = make_incident(account["id"], incident_category="PROPERTY_DAMAGE")

    withdrawn = get_success_data(api_client.withdraw_incident(incident["id"], OPERATIONS_LEAD))
    assert withdrawn["incident_status"] == "WITHDRAWN"

    res = api_client.withdraw_incident(incident["id"], OPERATIONS_LEAD)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert get_incident(incident["id"])["incident_status"] == "WITHDRAWN"


def test_revising_the_aggravators_back_down_makes_a_held_incident_withdrawable(api):
    """PRD §2.7: "When the request supplies **no** aggravator codes at all, the band instead
    floors at `S2` whenever `prior_incident_count_at_intake` is at least 2 and the category
    base level is 1"
    PRD §3.2: "An incident whose `severity` is `S1` or `S2` is below the floor required to
    open a hold and the request is refused with `ERR_SEVERITY_BELOW_HOLD_FLOOR` (`422`)."
    PRD §3.1: "Before any interim hold exists, a `SafetyInvestigator` may revise the intake
    codes by patching the incident's `aggravator_codes`, and the same derivation re-runs."

    Design: Corner/state_machines/withdrawal_of_a_decidable_s2_incident_restores_the_account
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_policy(sd_floor_severity="S3")
    account = setup_account(account_type="DRIVER", handle="ivan.petrov")

    # Two prior reports so the PROPERTY_DAMAGE floor band engages once the
    # aggravator is revised away. The frozen prior count reads rows created
    # strictly before this incident, so the clock is stepped between filings.
    make_prior_incidents(account["id"], 2, incident_category="HARASSMENT")

    set_clock("2026-10-01T00:00:00Z")
    incident = make_incident(account["id"], incident_category="PROPERTY_DAMAGE",
                             aggravator_codes=["S3_INJURY",
                                               "S3_LAW_ENFORCEMENT_SEVERITY"])
    assert incident["severity"] == "S3"

    # The revision is permitted only before any interim hold exists (§3.1).
    set_clock("2026-10-02T00:00:00Z")
    downgraded = get_success_data(
        api_client.patch_incident_severity(incident["id"], [], INVESTIGATOR)
    )
    assert downgraded["severity"] == "S2", (
        "with the aggravator revised away the floor band applies and the incident drops "
        "below the hold floor"
    )
    assert downgraded["incident_status"] == "OPEN", (
        "revising the intake codes does not disturb the intake state"
    )

    # The revision leaves the incident below the hold floor, so the hold edge is
    # unavailable for it from that point on.
    set_clock("2026-10-03T00:00:00Z")
    res = api_client.hold_incident(incident["id"], INVESTIGATOR)
    validate_error(res, ApiErrorId.ERR_SEVERITY_BELOW_HOLD_FLOOR)
    assert get_incident(incident["id"])["incident_status"] == "OPEN", (
        "the refused hold performs no transition"
    )
    assert get_account(account["id"])["status"] == "ACTIVE"
    assert get_success_data(
        api_client.list_account_enforcement_actions(account["id"], OPERATIONS_LEAD)
    ) == [], "no revision produced an enforcement action"


def test_release_without_a_standing_action_returns_the_account_to_active(api):
    """PRD §3.2: "When the account holds no enforcement action in `ACTIVE` or
    `MANDATORY_REPORTED` status and no standing action at all, the release returns the account
    to `ACTIVE` and the incident to `OPEN`, and the account's member announcements resume."
    PRD §2.4: "The posture is recomputed after every incident and enforcement mutation."

    Design: Difficulty/compensating_invariant/invariant_hold_release_restores_account_risk_score
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(appeal_window_days=30)
    account = setup_account(account_type="DRIVER", handle="zara.nasser")
    incident = make_incident(account["id"], incident_category="PHYSICAL_ASSAULT")
    get_success_data(api_client.hold_incident(incident["id"], INVESTIGATOR))
    assert get_account(account["id"])["status"] == "UNDER_HOLD"

    released = get_success_data(api_client.release_hold(incident["id"], INVESTIGATOR))
    assert released["incident_status"] == "OPEN"
    after = get_account(account["id"])
    assert after["status"] == "ACTIVE", (
        "with no standing action the release restores the account to ACTIVE"
    )
    assert after["standing_enforcement_count"] == 0
    assert after["safety_posture"] == "OPEN"


def test_release_with_a_standing_action_restricts_the_account(api):
    """PRD §3.2: "When the account still carries at least one standing `ACTIVE` or
    `MANDATORY_REPORTED` enforcement action, the release instead lands the account at
    `RESTRICTED` while still returning the incident to `OPEN`."

    Design: Difficulty/compensating_invariant/invariant_hold_release_restores_account_risk_score
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(appeal_window_days=30)
    account, first_decided, _ = setup_decided_case(
        account_handle="jules.marsh", incident_category="PHYSICAL_ASSAULT",
        decision_category="RESTRICTED",
    )
    assert get_account(account["id"])["status"] == "RESTRICTED"

    second = make_incident(account["id"], incident_category="SEXUAL_MISCONDUCT")
    get_success_data(api_client.hold_incident(second["id"], INVESTIGATOR))
    assert get_account(account["id"])["status"] == "UNDER_HOLD"

    released = get_success_data(api_client.release_hold(second["id"], INVESTIGATOR))
    assert released["incident_status"] == "OPEN"
    after = get_account(account["id"])
    assert after["status"] == "RESTRICTED", (
        "the account still carries a standing ACTIVE action, so the release lands it at "
        "RESTRICTED rather than ACTIVE"
    )
    assert after["standing_enforcement_count"] >= 1