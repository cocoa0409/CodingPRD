"""Device clusters: attribution, the two escalation thresholds and the cascade
they run back into their members."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_cluster,
    get_link,
    get_success_data,
    set_clock,
    setup_account,
    setup_banned_cluster,
    setup_cluster,
    setup_cluster_with_members,
    setup_policy,
    validate_error,
)

INVESTIGATOR = TEST_USERS["investigator_headers"]
OPERATIONS_LEAD = TEST_USERS["operations_lead_headers"]


def test_cluster_create_initializes_every_derived_field(api):
    """PRD §3.7: "the cluster starts at `OPEN` with `aggregate_cluster_risk` of 0,
    `clustered_actor_incident_count` of 0 and `cluster_risk_generation_index` of 1."
    PRD §3.7: "Any `aggregate_cluster_risk` value supplied at creation is ignored"

    Design: Corner/entities/explicit_hostile_risk_score_input_is_ignored_on_cluster_create
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()

    cluster = get_success_data(
        api_client.create_device_cluster(
            {"cluster_key": "dc-hostile", "region_code": "R1",
             "aggregate_cluster_risk": 99999},
            TEST_USERS["admin_headers"],
        )
    )

    assert cluster["aggregate_cluster_risk"] == 0, (
        f"a supplied aggregate is unconditionally overwritten to 0, got "
        f"{cluster['aggregate_cluster_risk']}"
    )
    assert cluster["clustered_actor_incident_count"] == 0
    assert cluster["status"] == "OPEN"
    assert cluster["cluster_risk_generation_index"] == 1, (
        "the cluster's risk generation starts in step with the region's knob counter"
    )


def test_escalation_drives_the_cluster_through_the_cascade_to_watchlist(api):
    """PRD §3.5: "when the linked device cluster's `clustered_actor_incident_count` has
    reached the region's watchlist threshold and the cluster is still `OPEN`, the cluster moves
    `OPEN` to `WATCHLIST` and the enforcement action's `cluster_watchlist_triggered` flag is set
    true — **only** on that first crossing"
    PRD §3.7: "every member link whose `link_status` is `LINKED` or `DORMANT` is set to
    `SEVERED` in the same request."

    Design: Difficulty/transitive_cascade/cascade_depth3_decision_to_cluster_severance
    """
    set_clock("2026-10-01T00:00:00Z")
    cluster, accounts, links = setup_cluster_with_members(
        cluster_key="dc-alpha", member_handles=("joan.ferreira", "kwame.boateng"),
        policy_overrides={"cluster_watchlist_threshold": 2,
                          "cluster_purge_threshold": 2400},
    )

    from test_helpers import drive_cluster_to_watchlist, decide_now, setup_incident_in_state

    # First member's incident is decided a week before the second.
    first = drive_cluster_to_watchlist(cluster["id"], accounts[0])
    assert first["incident_status"] == "DECIDED"
    mid = get_cluster(cluster["id"])
    assert mid["clustered_actor_incident_count"] == 1, (
        "a single clustered S3/S4 incident has not yet crossed the threshold of 2"
    )
    assert mid["status"] == "OPEN", (
        "the cluster stays OPEN until the watchlist threshold is reached"
    )
    assert get_link(links[0]["id"])["link_status"] == "LINKED", (
        "the severance clause only fires on the escalation itself"
    )

    set_clock("2026-10-08T00:00:00Z")
    second, _ = setup_incident_in_state(accounts[1]["id"],
                                        incident_category="PHYSICAL_ASSAULT")
    frozen = get_success_data(api_client.get_incident(second["id"], INVESTIGATOR))
    assert frozen["incident_status"] == "PENDING_DECISION"
    decided = decide_now(second["id"], "DEACTIVATED", frozen["version"])
    assert decided["incident_status"] == "DECIDED"

    after = get_cluster(cluster["id"])
    assert after["clustered_actor_incident_count"] == 2, (
        "both members now carry a clustered S3/S4 incident"
    )
    assert after["status"] == "WATCHLIST", (
        "the count reaching the watchlist threshold of 2 escalates the cluster out of OPEN"
    )

    resolution = get_success_data(
        api_client.list_enforcement_actions(
            INVESTIGATOR, params={"incident_id": second["id"]}
        )
    )
    assert resolution, "the decision created an enforcement action"
    assert resolution[0]["enforcement_status"] == "MANDATORY_REPORTED", (
        "PHYSICAL_ASSAULT at S4 sets regulator_report_required, so the action lands at "
        "MANDATORY_REPORTED rather than ACTIVE"
    )
    assert resolution[0]["cluster_watchlist_triggered"] is True, (
        "the escalation flag records the first crossing out of the open state"
    )

    assert get_link(links[0]["id"])["link_status"] == "SEVERED", (
        "the watchlist escalation severs every member link in the same request"
    )
    assert get_link(links[1]["id"])["link_status"] == "SEVERED"


def test_link_against_a_watchlisted_cluster_is_still_accepted(api):
    """PRD §3.7: "Links are otherwise accepted against a cluster whose `status` is `OPEN` or
    `WATCHLIST`, in which case the cluster simply stays where it is."

    Design: Difficulty/non_linear_state_machine/non_linear_cluster_branch_fork_join_with_sever_cycle
    """
    set_clock("2026-10-08T00:00:00Z")
    cluster, accounts, links = setup_cluster_with_members(
        cluster_key="dc-watch", member_handles=("fara.nkemelu", "gwen.adeyemi"),
        policy_overrides={"cluster_watchlist_threshold": 2,
                          "cluster_purge_threshold": 2400},
    )

    from test_helpers import drive_cluster_to_watchlist

    drive_cluster_to_watchlist(cluster["id"], accounts[0])
    drive_cluster_to_watchlist(cluster["id"], accounts[1])

    watched = get_cluster(cluster["id"])
    assert watched["status"] == "WATCHLIST"

    set_clock("2026-10-08T00:00:00Z")
    newcomer = setup_account(account_type="DRIVER", handle="hana.suzuki")
    fresh = get_success_data(
        api_client.create_account_device_link(
            {"account_id": newcomer["id"], "device_cluster_id": cluster["id"],
             "fingerprint_hash": "fp-watch-3"},
            INVESTIGATOR,
        )
    )
    assert fresh["link_status"] == "LINKED", (
        "a fresh link against a watchlisted cluster is accepted rather than refused"
    )
    assert get_cluster(cluster["id"])["status"] == "WATCHLIST", (
        "the cluster simply stays where it is"
    )


def test_link_against_a_banned_cluster_is_refused_and_preserves_the_history(api):
    """PRD §3.7: "A link aimed at a `BANNED` cluster is refused with `ERR_CLUSTER_BANNED`
    (`422`), and because the ban must continue to hold against freshly observed fingerprints,
    **pre-existing links are preserved rather than deleted**"

    Design: Difficulty/resource_temporal_overlap/overlap_severed_link_rejoin_refused_on_banned_cluster
    """
    # The setup helper steps the clock between the two chained clustered
    # decisions, so the subject instant is asserted from the helper's result.
    set_clock("2026-07-01T00:00:00Z")
    cluster, member, member_link = setup_banned_cluster(cluster_key="dc-gamma")

    assert get_cluster(cluster["id"])["status"] == "BANNED", (
        "the lowest possible purge threshold escalates the cluster to BANNED"
    )
    assert get_link(member_link["id"])["link_status"] == "SEVERED"

    set_clock("2026-09-01T00:00:00Z")
    outsider = setup_account(account_type="DRIVER", handle="willa.mbeki")
    res = api_client.create_account_device_link(
        {"account_id": outsider["id"], "device_cluster_id": cluster["id"],
         "fingerprint_hash": "fp-gamma-2"},
        INVESTIGATOR,
    )
    validate_error(res, ApiErrorId.ERR_CLUSTER_BANNED)

    assert get_cluster(cluster["id"])["status"] == "BANNED"
    assert get_link(member_link["id"])["link_status"] == "SEVERED", (
        "the pre-existing link is preserved rather than deleted by the refusal"
    )


def test_stabilize_is_refused_inside_the_quiet_window_and_accepted_at_its_end(api):
    """PRD §3.7: "A `SafetyOperationsLead` may stabilize a `WATCHLIST` cluster once 180
    consecutive days have passed with no new clustered `S3`/`S4` incident and its aggregate sits
    below the region's purge threshold, restoring it to `OPEN` and restoring every `SEVERED`
    member link to `LINKED`"

    Design: Difficulty/resource_temporal_overlap/overlap_cluster_stabilize_refused_inside_quiet_window
    """
    set_clock("2026-10-01T00:00:00Z")
    cluster, accounts, links = setup_cluster_with_members(
        cluster_key="dc-delta", member_handles=("xu.lan",),
        policy_overrides={"cluster_watchlist_threshold": 1,
                          "cluster_purge_threshold": 99999},
    )

    from test_helpers import drive_cluster_to_watchlist

    drive_cluster_to_watchlist(cluster["id"], accounts[0])
    watched = get_cluster(cluster["id"])
    assert watched["status"] == "WATCHLIST"

    res = api_client.stabilize_cluster(cluster["id"], watched["version"], OPERATIONS_LEAD)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert get_cluster(cluster["id"])["status"] == "WATCHLIST", (
        "at the escalation instant the quiet window is still open, so the reversion collides"
    )

    set_clock("2027-03-30T00:00:00Z")
    later = get_cluster(cluster["id"])
    restored = get_success_data(
        api_client.stabilize_cluster(cluster["id"], later["version"], OPERATIONS_LEAD)
    )
    assert restored["status"] == "OPEN", (
        "at exactly 180 days after the newest clustered incident the window's end is "
        "inclusive and the same stabilization succeeds"
    )
    assert get_link(links[0]["id"])["link_status"] == "LINKED", (
        "every severed member link is restored by the reversion"
    )


def test_dormancy_sweep_moves_a_link_through_both_age_boundaries(api):
    """PRD §3.7: "A sweep driven by a `PlatformAdmin` walks every link and moves one whose
    `last_seen_at` has aged at least 180 days from `LINKED` to `DORMANT`, at which point it
    stops counting toward the cluster's `clustered_actor_incident_count`; a second interval
    carries a `DORMANT` link past 365 days from `last_seen_at` into `SEVERED`, its terminal
    state."

    Design: Corner/cross_cutting_layers/dormancy_sweep_advances_links_through_both_boundaries
    """
    set_clock("2026-04-01T00:00:00Z")
    setup_policy()
    account = setup_account(account_type="DRIVER", handle="femi.adebayo")
    cluster = setup_cluster(cluster_key="dc-dormancy")
    link = get_success_data(
        api_client.create_account_device_link(
            {"account_id": account["id"], "device_cluster_id": cluster["id"],
             "fingerprint_hash": "fp-dormancy"},
            INVESTIGATOR,
        )
    )
    assert link["link_status"] == "LINKED"
    assert link["last_seen_at"].startswith("2026-04-01"), (
        f"last_seen_at is stamped from the logical clock, got {link['last_seen_at']}"
    )

    set_clock("2026-09-01T00:00:00Z")   # 153 days
    get_success_data(api_client.dormancy_sweep(TEST_USERS["admin_headers"]))
    assert get_link(link["id"])["link_status"] == "LINKED", (
        "at 153 days the 180-day dormancy boundary has not been reached"
    )

    set_clock("2026-10-05T00:00:00Z")   # 187 days
    get_success_data(api_client.dormancy_sweep(TEST_USERS["admin_headers"]))
    assert get_link(link["id"])["link_status"] == "DORMANT"

    set_clock("2027-04-01T00:00:00Z")   # 365 days exactly
    get_success_data(api_client.dormancy_sweep(TEST_USERS["admin_headers"]))
    assert get_link(link["id"])["link_status"] == "SEVERED", (
        "the second boundary is inclusive at 365 days exactly"
    )


def test_unknown_link_id_reports_resource_not_found(api):
    """PRD §2.9: "an enforcement action, background check or policy that does not exist
    surfaces as `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/entities/evidence_item_get_with_an_unknown_id_returns_resource_not_found
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()

    res = api_client.get_account_device_link(
        "7f3a91c4-0b2e-4d55-9a10-6c8e2f4b1d30", OPERATIONS_LEAD
    )
    error = validate_error(res, ApiErrorId.ERR_RESOURCE_NOT_FOUND)
    assert isinstance(error["message"], str) and error["message"].strip()
    assert res.status_code == 404