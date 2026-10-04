"""Optimistic concurrency: the six version-protected writes."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_appeal_outcome_payload,
    decide_now,
    file_appeal,
    first_action_for_incident,
    get_account,
    get_cluster,
    get_incident,
    get_success_data,
    make_appeal_reviewer_headers,
    set_clock,
    setup_account,
    setup_decided_case,
    setup_cluster_with_members,
    setup_incident_in_state,
    setup_policy,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]
APPEAL_REVIEWER = TEST_USERS["appeal_reviewer_headers"]
OPERATIONS_LEAD = TEST_USERS["operations_lead_headers"]


def test_stale_incident_version_is_refused_on_decision(api):
    """PRD §2.11: "a request that carries a value which does not equal the parent entity's
    current `version` is rejected with `ERR_STALE_VERSION` (`412`)."
    PRD §2.11: "Committing an incident decision requires `expected_incident_version`, compared
    against the target `SafetyIncident`'s current `version`."

    Design: Corner/cross_cutting_layers/restriction_expiry_restores_the_account_and_freezes_the_posture
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(appeal_window_days=30)
    account = setup_account(account_type="DRIVER", handle="stale.decision")
    incident, _ = setup_incident_in_state(account["id"],
                                          incident_category="PHYSICAL_ASSAULT")
    frozen = get_success_data(api_client.get_incident(incident["id"], INVESTIGATOR))
    stale_version = frozen["version"]
    assert get_account(account["id"])["status"] == "PENDING_DECISION"
    # The expectation of a superseded read is already stale.
    res = api_client.commit_decision(
        incident["id"],
        {
            "decision_category": "DEACTIVATED",
            "decision_basis": "Committed against an observation that has already moved on.",
            "expected_incident_version": stale_version - 1,
        },
        INVESTIGATOR,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    assert res.status_code == 412

    assert get_incident(incident["id"])["incident_status"] == "PENDING_DECISION", (
        "the refused write performs no transition"
    )
    assert get_account(account["id"])["status"] == "PENDING_DECISION"
    assert get_success_data(
        api_client.list_account_enforcement_actions(account["id"], OPERATIONS_LEAD)
    ) == [], "no enforcement action was created by the stale write"


def test_decision_bumps_the_incident_version_by_exactly_one(api):
    """PRD §3.4: "the incident's `version` increments by 1"
    PRD §3.4: "On success the incident moves to `DECIDED`, `decided_at` is stamped,
    `decision_category` carries the committed outcome"

    Design: Corner/consistency_model/decision_commit_is_visible_in_the_same_request
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(appeal_window_days=30)
    account = setup_account(account_type="DRIVER", handle="immediate.commit")
    incident, _ = setup_incident_in_state(account["id"],
                                          incident_category="PHYSICAL_ASSAULT")
    frozen_version = get_success_data(
        api_client.get_incident(incident["id"], INVESTIGATOR)
    )["version"]
    before = decide_now(incident["id"], "RESTRICTED", frozen_version)

    assert before["incident_status"] == "DECIDED", (
        "the decision response itself already carries the committed state"
    )
    assert before["decision_category"] == "RESTRICTED"
    assert before["decided_at"] is not None, (
        "the decided instant is visible in the same request that committed the decision"
    )
    assert before["version"] == frozen_version + 1, (
        "the incident's version advanced by exactly one on the decision write"
    )


def test_stale_account_version_is_refused_on_expiry_sweep(api):
    """PRD §2.11: "Running the restriction-expiry sweep requires `expected_account_version`,
    compared against the target `Account`'s current `version`."
    PRD §2.11: "a request that carries a value which does not equal the parent entity's current
    `version` is rejected with `ERR_STALE_VERSION` (`412`)."

    Design: Difficulty/cross_entity_state_dependency/dependency_expiry_blocked_by_sibling_severe_tier
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(appeal_window_days=30)
    account, incident, action = setup_decided_case(
        account_handle="stale.sweep", incident_category="PROPERTY_DAMAGE",
        decision_category="RESTRICTED",
        evidence_specs=[
            {"evidence_type": "EXTERNAL_RECORD", "evidence_weight": "DISPOSITIVE"},
            {"evidence_type": "TRIP_DATA", "evidence_weight": "DISPOSITIVE"},
        ],
    )
    set_clock("2027-10-01T00:00:00Z")
    current = get_account(account["id"])

    res = api_client.expiry_sweep(account["id"], current["version"] - 1, OPERATIONS_LEAD)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    assert res.status_code == 412

    after = get_account(account["id"])
    assert after["standing_enforcement_count"] == current["standing_enforcement_count"], (
        "the stale refusal applies no expiry side effect"
    )


def test_stale_incident_version_is_refused_on_appeal_outcome(api):
    """PRD §2.11: "Committing an appeal outcome requires `expected_incident_version`, compared
    against the target `SafetyIncident`'s current `version`."

    Design: Difficulty/non_linear_state_machine/non_linear_appeal_round_trip_cycle_on_account
    """
    set_clock("2026-10-05T00:00:00Z")
    setup_policy(appeal_window_days=30, expedite_appeal_baseline_count=5,
                 expedite_review_days=14, standard_review_days=30)
    _, incident, _ = setup_decided_case(
        account_handle="stale.appeal", decision_category="DEACTIVATED",
    )
    get_success_data(file_appeal(incident["id"]))
    appealed = get_incident(incident["id"])
    assert appealed["incident_status"] == "APPEAL_PENDING"

    res = api_client.commit_appeal_outcome(
        appealed["id"],
        create_appeal_outcome_payload("UPHELD", appealed["version"] - 1),
        make_appeal_reviewer_headers("ar-priya"),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    assert res.status_code == 412
    assert get_incident(appealed["id"])["incident_status"] == "APPEAL_PENDING"


def test_stale_cluster_version_is_refused_on_stabilize(api):
    """PRD §3.7: "That stabilization is version-protected — it requires `expected_cluster_version`
    and refuses a stale one with `ERR_STALE_VERSION` (`412`)"

    Design: Difficulty/resource_temporal_overlap/overlap_cluster_stabilize_refused_inside_quiet_window
    """
    set_clock("2026-10-01T00:00:00Z")
    cluster, accounts, links = setup_cluster_with_members(
        cluster_key="dc-stale", member_handles=("stale.member",),
        policy_overrides={"cluster_watchlist_threshold": 1,
                          "cluster_purge_threshold": 99999},
    )

    from test_helpers import drive_cluster_to_watchlist

    drive_cluster_to_watchlist(cluster["id"], accounts[0])
    watched = get_cluster(cluster["id"])
    assert watched["status"] == "WATCHLIST"

    set_clock("2027-03-30T00:00:00Z")
    res = api_client.stabilize_cluster(
        cluster["id"], watched["version"] - 1, OPERATIONS_LEAD
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    assert res.status_code == 412
    assert get_cluster(cluster["id"])["status"] == "WATCHLIST"


def test_stale_policy_version_is_refused_on_revision(api):
    """PRD §3.9: "Revision is version-protected: it requires `expected_policy_version` and
    refuses a stale one with `ERR_STALE_VERSION` (`412`)"

    Design: Corner/entities/platform_policy_defaults_are_applied_for_every_omitted_threshold
    """
    set_clock("2026-10-01T00:00:00Z")
    policy = setup_policy()

    res = api_client.patch_platform_policy(
        policy["id"],
        {"expected_policy_version": policy["version"] - 1, "rollup_threshold": 4},
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    assert res.status_code == 412

    unchanged = get_success_data(api_client.get_platform_policy(policy["id"], ADMIN))
    assert unchanged["rollup_threshold"] == policy["rollup_threshold"]