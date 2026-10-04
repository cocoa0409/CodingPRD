"""Complementary lifecycle scenarios: the neighbouring branch of each escalation
and gate, and the boundary one step either side of a pinned constant."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    decide_now,
    file_appeal,
    get_account,
    get_cluster,
    get_incident,
    get_success_data,
    make_incident,
    set_clock,
    setup_account,
    setup_banned_cluster,
    setup_cluster_with_members,
    setup_decided_case,
    setup_incident_in_state,
    setup_policy,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]
APPEAL_REVIEWER = TEST_USERS["appeal_reviewer_headers"]
OPERATIONS_LEAD = TEST_USERS["operations_lead_headers"]

S4_EVIDENCE = [
    {"evidence_type": "TRIP_DATA", "evidence_weight": "DISPOSITIVE"},
    {"evidence_type": "LAW_ENFORCEMENT_CONTACT", "evidence_weight": "DISPOSITIVE"},
    {"evidence_type": "EXTERNAL_RECORD", "evidence_weight": "DISPOSITIVE"},
]


def test_escalation_flag_is_set_only_on_the_first_crossing(api):
    """PRD §3.5: "when the linked device cluster's `clustered_actor_incident_count` has reached
    the region's watchlist threshold and the cluster is still `OPEN`, the cluster moves `OPEN`
    to `WATCHLIST` and the enforcement action's `cluster_watchlist_triggered` flag is set true —
    **only** on that first crossing; a later crossing that finds the cluster already `WATCHLIST`
    leaves the flag false."

    Design: Difficulty/transitive_cascade/cascade_depth3_decision_to_cluster_severance
    """
    set_clock("2026-10-01T00:00:00Z")
    cluster, accounts, links = setup_cluster_with_members(
        cluster_key="dc-crossing", member_handles=("joan.ferreira.c", "kwame.boateng.c"),
        policy_overrides={"cluster_watchlist_threshold": 2,
                          "cluster_purge_threshold": 99999},
    )

    from test_helpers import drive_cluster_to_watchlist

    # The first crossing: one member's decision is already on the record, the second
    # member's decision takes the count to the threshold.
    drive_cluster_to_watchlist(cluster["id"], accounts[0])
    set_clock("2026-10-08T00:00:00Z")
    drive_cluster_to_watchlist(cluster["id"], accounts[1])
    assert get_cluster(cluster["id"])["status"] == "WATCHLIST"

    # A third clustered incident on a decision that finds the cluster already watchlisted.
    set_clock("2026-10-08T00:00:00Z")
    third = make_incident(accounts[0]["id"], incident_category="SEXUAL_MISCONDUCT")
    get_success_data(api_client.hold_incident(third["id"], INVESTIGATOR))
    from test_helpers import gather_and_accept

    gather_and_accept(third["id"], S4_EVIDENCE)
    frozen = get_success_data(api_client.get_incident(third["id"], INVESTIGATOR))
    decide_now(third["id"], "DEACTIVATED", frozen["version"])

    actions = get_success_data(
        api_client.list_enforcement_actions(INVESTIGATOR, params={"incident_id": third["id"]})
    )
    assert actions, "the decision created an enforcement action for the third incident"
    assert actions[0]["cluster_watchlist_triggered"] is False, (
        "the cluster was already watchlisted when this decision landed, so the "
        "first-crossing flag stays false"
    )
    assert get_cluster(cluster["id"])["status"] == "WATCHLIST", (
        "the already-watchlisted cluster is not re-escalated"
    )


def test_purge_edge_is_unavailable_when_the_escalation_arm_is_disabled(api):
    """PRD §2.7: "The second edge exists only while the region's escalation arm is enabled;
    with the arm disabled the cluster stays `WATCHLIST`."
    PRD §3.5: "The escalation arm exists only while the region's `escalation_enabled` knob is
    true; with it false, the purge edge is unavailable and the cluster stays `WATCHLIST`."

    Design: Difficulty/non_linear_state_machine/non_linear_cluster_branch_fork_join_with_sever_cycle
    """
    set_clock("2026-10-01T00:00:00Z")
    cluster, accounts, links = setup_cluster_with_members(
        cluster_key="dc-noarm", member_handles=("fara.nkemelu.arm",),
        policy_overrides={"cluster_watchlist_threshold": 1,
                          "cluster_purge_threshold": 1, "escalation_enabled": False},
    )

    from test_helpers import drive_cluster_to_watchlist

    drive_cluster_to_watchlist(cluster["id"], accounts[0])

    watched = get_cluster(cluster["id"])
    assert watched["status"] == "WATCHLIST", (
        "the cluster still crosses into the watchlist; only the purge arm is withdrawn"
    )
    assert watched["aggregate_cluster_risk"] >= 1, (
        "the aggregate already meets the configured purge threshold"
    )

    # A further watchlisted member's deactivating decision cannot reach the disabled
    # purge edge even though the aggregate is far past the configured threshold.
    set_clock("2026-09-01T00:00:00Z")
    second_member = setup_account(account_type="DRIVER", handle="gwen.adeyemi.arm")
    from test_helpers import setup_link

    setup_link(second_member["id"], cluster["id"], fingerprint_hash="fp-noarm-2")

    set_clock("2026-10-02T00:00:00Z")
    incident = make_incident(second_member["id"], incident_category="PHYSICAL_ASSAULT")
    get_success_data(api_client.hold_incident(incident["id"], INVESTIGATOR))
    from test_helpers import gather_and_accept

    gather_and_accept(incident["id"], S4_EVIDENCE)
    frozen = get_success_data(api_client.get_incident(incident["id"], INVESTIGATOR))
    decided = decide_now(incident["id"], "DEACTIVATED", frozen["version"])
    assert decided["incident_status"] == "DECIDED", (
        "the carrier decision itself is accepted; only the purge edge is withdrawn"
    )

    after = get_cluster(cluster["id"])
    assert after["status"] == "WATCHLIST", (
        "with the escalation arm disabled the cluster remains watchlisted rather than banned"
    )
    assert after["aggregate_cluster_risk"] >= 1, (
        "the aggregate is already past the configured purge threshold, so the only thing "
        "keeping the cluster off the banned state is the disabled arm"
    )


def test_in_flight_appeal_gate_refuses_a_deactivation(api):
    """PRD §3.4: "A deactivation cannot be committed while the account carries an enforcement
    action in `ACTIVE`, `MANDATORY_REPORTED` or `APPEAL_PENDING` status — the attempt is refused
    with `ERR_IN_FLIGHT_APPEAL` (`409`)."

    Design: Difficulty/cross_entity_state_dependency/dependency_decision_blocked_by_sibling_in_flight_appeal
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(sd_floor_severity="S4", appeal_window_days=30)
    account = setup_account(account_type="DRIVER", handle="sana.iqbal.gate")

    # The first matter deactivates, leaving a DEACTIVATED action standing.
    first, _ = setup_incident_in_state(
        account["id"], incident_category="SAFETY_VIOLATION",
        evidence_specs=[
            {"evidence_type": "EXTERNAL_RECORD", "evidence_weight": "DISPOSITIVE"},
            {"evidence_type": "EXTERNAL_RECORD", "evidence_weight": "DISPOSITIVE"},
        ],
    )
    set_clock("2026-10-02T00:00:00Z")
    first_frozen = get_success_data(api_client.get_incident(first["id"], INVESTIGATOR))
    first_decided = decide_now(first["id"], "DEACTIVATED", first_frozen["version"])
    assert first_decided["decision_category"] == "DEACTIVATED"

    # A second incident on the same account. The specialised prohibition is
    # asserted ahead of the shared state check, so its own status is irrelevant.
    set_clock("2026-10-03T00:00:00Z")
    second = make_incident(account["id"], incident_category="SEXUAL_MISCONDUCT")
    second_frozen = get_success_data(api_client.get_incident(second["id"], INVESTIGATOR))

    res = api_client.commit_decision(
        second["id"],
        {
            "decision_category": "DEACTIVATED",
            "decision_basis": "Second S4 physical assault on the same account while the prior appeal is still in flight.",
            "expected_incident_version": second_frozen["version"],
        },
        INVESTIGATOR,
    )
    validate_error(res, ApiErrorId.ERR_IN_FLIGHT_APPEAL)
    assert res.status_code == 409

    after = get_account(account["id"])
    assert after["status"] == "DEACTIVATED", "the refused request produced no side effect"
    assert after["standing_enforcement_count"] >= 1
    assert get_incident(second["id"])["incident_status"] == "OPEN"


def test_evidence_score_one_item_below_the_deactivation_floor_holds_at_restricted(api):
    """PRD §3.4: "When `decision_evidence_score` is at least **4.00**, or is at least **2.50**
    with `decision_distinct_evidence_sources` of at least 2, the outcome is `DEACTIVATED`."
    PRD §3.4: "When `decision_evidence_score` is at least 2.50 but
    `decision_distinct_evidence_sources` is below 2, the outcome is whichever of the floor and
    `RESTRICTED` ranks higher"

    Design: Difficulty/boundary_precision_check/boundary_evidence_score_exactly_at_the_deactivation_floor
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    account = setup_account(handle="pia.lindqvist.below")
    incident = make_incident(account["id"], incident_category="SAFETY_VIOLATION",
                             aggravator_codes=["S3_INJURY"])
    get_success_data(api_client.hold_incident(incident["id"], INVESTIGATOR))
    set_clock("2026-10-01T00:00:00Z")

    from test_helpers import gather_and_accept

    gather_and_accept(incident["id"], [
        {"evidence_type": "TRIP_DATA", "evidence_weight": "DISPOSITIVE"}
        for _ in range(3)
    ])

    frozen = get_success_data(api_client.get_incident(incident["id"], INVESTIGATOR))
    criteria = get_success_data(api_client.get_decision_criteria(incident["id"], INVESTIGATOR))

    assert frozen["decision_evidence_score"] < 4.00, (
        "three DISPOSITIVE items sit below the deactivation constant, so the boundary is "
        f"only crossed by the fourth, got {frozen['decision_evidence_score']}"
    )
    assert criteria["proposed_decision"] == "RESTRICTED", (
        "the provisional override cannot fire on a single distinct source, so the floor is "
        "held at RESTRICTED rather than escaping to DEACTIVATED"
    )


def test_link_for_an_existing_member_is_also_refused_on_a_banned_cluster(api):
    """PRD §3.7: "because the ban must continue to hold against freshly observed fingerprints,
    **pre-existing links are preserved rather than deleted** — the refusal protects the cluster,
    not the history."

    Design: Difficulty/resource_temporal_overlap/overlap_severed_link_rejoin_refused_on_banned_cluster
    """
    set_clock("2026-07-01T00:00:00Z")
    cluster, member, member_link = setup_banned_cluster(cluster_key="dc-gamma.rejoin")
    assert get_cluster(cluster["id"])["status"] == "BANNED"
    assert get_success_data(
        api_client.get_account_device_link(member_link["id"], OPERATIONS_LEAD)
    )["link_status"] == "SEVERED"

    res = api_client.create_account_device_link(
        {"account_id": member["id"], "device_cluster_id": cluster["id"],
         "fingerprint_hash": "fp-gamma-3"},
        INVESTIGATOR,
    )
    validate_error(res, ApiErrorId.ERR_CLUSTER_BANNED)
    assert res.status_code == 422, (
        "the ban is permanent rather than a point-in-time occupation, so even an existing "
        "member cannot rejoin the cluster after its link was severed"
    )
    assert get_cluster(cluster["id"])["status"] == "BANNED"
    assert get_success_data(
        api_client.get_account_device_link(member_link["id"], OPERATIONS_LEAD)
    )["link_status"] == "SEVERED", "the history is preserved rather than rewritten"


def test_state_repaired_decision_succeeds_without_an_in_flight_appeal(api):
    """PRD §3.4: "A decision may also be committed against an incident at `PENDING_DECISION`
    whose account currently sits at `RESTRICTED` from an earlier matter, which is the
    repeat-offender path."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_state_beats_business_safety_on_decision
    """
    set_clock("2026-10-06T00:00:00Z")
    setup_policy(sd_floor_severity="S4", appeal_window_days=30)
    account, first, first_action = setup_decided_case(
        account_handle="nadia.ba.repaired", incident_category="PHYSICAL_ASSAULT",
        decision_category="RESTRICTED",
        evidence_specs=[
            {"evidence_type": "TRIP_DATA", "evidence_weight": "DISPOSITIVE"},
            {"evidence_type": "EXTERNAL_RECORD", "evidence_weight": "DISPOSITIVE"},
        ],
    )
    assert first["incident_status"] == "DECIDED"
    assert first_action["enforcement_status"] in ("ACTIVE", "MANDATORY_REPORTED"), (
        "no appeal has been filed, so the action is standing rather than in flight; the "
        "reportable cascade lands it at MANDATORY_REPORTED because PHYSICAL_ASSAULT is a "
        "reportable category"
    )

    second, _ = setup_incident_in_state(account["id"],
                                        incident_category="SEXUAL_MISCONDUCT",
                                        evidence_specs=S4_EVIDENCE)
    frozen = get_success_data(api_client.get_incident(second["id"], INVESTIGATOR))
    assert frozen["incident_status"] == "PENDING_DECISION"

    decided = decide_now(second["id"], "DEACTIVATED", frozen["version"])
    assert decided["incident_status"] == "DECIDED", (
        "with the sibling action merely ACTIVE rather than in flight, the repeat-offender "
        "deactivation is accepted"
    )
    assert decided["decision_category"] == "DEACTIVATED"
    assert get_account(account["id"])["deactivation_count"] == 1