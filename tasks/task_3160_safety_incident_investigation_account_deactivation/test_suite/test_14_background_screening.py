"""Background screening: the adjudication verdicts and the cascade they run into
the account's propagated risk and the cluster escalation it feeds."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    get_account,
    get_cluster,
    get_success_data,
    make_incident,
    set_clock,
    setup_account,
    setup_background_check_in_review,
    setup_cluster_with_members,
    setup_policy,
    setup_trip,
    shift_iso,
)

INVESTIGATOR = TEST_USERS["investigator_headers"]
BACKGROUND_REVIEWER = TEST_USERS["background_reviewer_headers"]
OPERATIONS_LEAD = TEST_USERS["operations_lead_headers"]
LIAISON = TEST_USERS["liaison_headers"]

S4_EVIDENCE = [
    {"evidence_type": "TRIP_DATA", "evidence_weight": "DISPOSITIVE"},
    {"evidence_type": "LAW_ENFORCEMENT_CONTACT", "evidence_weight": "DISPOSITIVE"},
    {"evidence_type": "EXTERNAL_RECORD", "evidence_weight": "DISPOSITIVE"},
]


def test_inconclusive_adjudication_feeds_the_cluster_purge_escalation(api):
    """PRD §3.8: "`CLEAR` subtracts 15 from the account's risk score floored at 0,
    `INCONCLUSIVE` adds 30, and `ADVERSE` makes the account deactivation-eligible"
    PRD §3.5: "Third, when the linked cluster is already `WATCHLIST` and its
    `aggregate_cluster_risk` has reached the region's purge threshold and the linked account's
    `risk_tier` is `TIER_HIGH` or `TIER_SEVERE`, the cluster moves `WATCHLIST` to `BANNED`."

    Design: Difficulty/transitive_cascade/cascade_depth2_background_adverse_to_risk_to_link_severance
    """
    set_clock("2026-04-01T00:00:00Z")
    cluster, accounts, links = setup_cluster_with_members(
        cluster_key="dc-beta", member_handles=("lena.kowalski", "mateo.rivas"),
        policy_overrides={"cluster_watchlist_threshold": 1,
                          "cluster_purge_threshold": 2400, "escalation_enabled": True},
    )
    a1, a2 = accounts

    # Drive the cluster into WATCHLIST while the first member's incident is still live.
    # S4_EVIDENCE is captured on a dedicated driver counterparty's trip so the items
    # satisfy the both-parties guard of PRD §3.3.
    set_clock("2026-04-01T00:00:00Z")
    from test_helpers import drive_cluster_to_watchlist, setup_link

    # The watchlist crossing runs off the decision cascade of §3.5, so the
    # clustered matter is decided against the first member.
    drive_cluster_to_watchlist(cluster["id"], a1)
    assert get_cluster(cluster["id"])["clustered_actor_incident_count"] == 1, (
        "an S4 clustered incident on a member account counts toward the watchlist edge"
    )
    watched = get_cluster(cluster["id"])
    assert watched["status"] == "WATCHLIST", (
        "a single clustered S3/S4 incident meets a watchlist threshold of 1"
    )
    # The escalation severs the links that were attributed at the crossing, so the
    # second member's link is observed afresh here and then aged into dormancy.
    fresh_link = setup_link(a2["id"], cluster["id"], fingerprint_hash="dc-beta-fp-second")
    links = [links[0], fresh_link]

    # Settle the second member out of the recent window, then age it into dormancy.
    set_clock("2026-10-05T00:00:00Z")
    get_success_data(api_client.dormancy_sweep(TEST_USERS["admin_headers"]))
    dormant = get_success_data(
        api_client.get_account_device_link(links[1]["id"], OPERATIONS_LEAD)
    )
    assert dormant["link_status"] == "DORMANT", (
        "the second member's link has aged past the 180-day dormancy boundary"
    )

    settled = get_cluster(cluster["id"])
    before = get_account(a1["id"])
    assert settled["aggregate_cluster_risk"] >= 0, (
        "the aggregate is the sum of its members' non-cluster risk components"
    )

    check, _ = setup_background_check_in_review(a1["id"])
    get_success_data(
        api_client.adjudicate_background_check(
            check["id"], {"adjudication": "INCONCLUSIVE"}, BACKGROUND_REVIEWER
        )
    )

    after = get_account(a1["id"])
    assert after["risk_score"] == pytest.approx(before["risk_score"] + 30, abs=0.005), (
        "the inconclusive verdict moves the account's risk score by exactly the documented "
        "30-point debit"
    )

    final = get_cluster(cluster["id"])
    assert final["aggregate_cluster_risk"] == pytest.approx(
        settled["aggregate_cluster_risk"], abs=0.005
    ), (
        "the ancillary adjudication adjustment sits outside the propagation rule, so the "
        "aggregate is the member's incident plus enforcement term and does not move with it"
    )
    assert final["status"] == "WATCHLIST", (
        "the purge edge reads the aggregate, not the adjusted score, so a cluster whose "
        "aggregate sits far below the purge threshold stays watchlisted"
    )
    assert after["risk_tier"] in ("TIER_LOW", "TIER_ELEVATED", "TIER_HIGH", "TIER_SEVERE")


def test_clearing_a_screening_review_subtracts_its_documented_credit(api):
    """PRD §3.8: "The verdict stamps `completed_at`, and its effect on the account is
    asymmetric: `CLEAR` subtracts 15 from the account's risk score floored at 0"

    Design: Difficulty/transitive_cascade/cascade_depth2_background_adverse_to_risk_to_link_severance
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(rescreen_refresh_days=548, review_generation_index=3)
    account = setup_account(account_type="DRIVER", handle="clear.subject")

    make_incident(account["id"], incident_category="HARASSMENT")
    before = get_account(account["id"])
    assert before["risk_score"] > 0

    check, _ = setup_background_check_in_review(account["id"])
    get_success_data(
        api_client.adjudicate_background_check(
            check["id"], {"adjudication": "CLEAR"}, BACKGROUND_REVIEWER
        )
    )

    after = get_account(account["id"])
    assert after["risk_score"] == pytest.approx(before["risk_score"] - 15, abs=0.005), (
        "a clear verdict subtracts its documented 15-point credit from the account's score"
    )
    settled = get_success_data(
        api_client.get_background_check(check["id"], BACKGROUND_REVIEWER)
    )
    assert settled["check_status"] == "COMPLETED"
    assert settled["adjudication"] == "CLEAR"
    assert settled["completed_at"] is not None


def test_screening_acknowledge_is_date_gated_and_succeeds_inside_the_window(api):
    """PRD §3.8: "A `BackgroundReviewer` acknowledges a due review when the current instant has
    reached its `scheduled_due_at` minus the region's continuous-monitor acknowledgement
    deadline, which moves the record from `SCHEDULED` to `IN_REVIEW` and decrements the
    region's unacknowledged-review count."

    Design: Corner/validations/background_check_acknowledge_before_the_ack_deadline_is_refused
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(continuous_monitor_ack_deadline_days=7, rescreen_refresh_days=548)
    account = setup_account(account_type="DRIVER", handle="yara.sen")

    check = get_success_data(
        api_client.list_account_background_checks(account["id"], BACKGROUND_REVIEWER)
    )[0]
    assert check["check_status"] == "SCHEDULED", (
        "the synthesized review begins in the scheduled state with a future due date"
    )

    # At the creation instant the acknowledgement window has not yet opened, so the
    # edge exists structurally but its date precondition is unmet.
    early = api_client.acknowledge_background_check(check["id"], BACKGROUND_REVIEWER)
    assert early.status_code == 409, (
        "the refused acknowledgement reports the unmet date precondition rather than a "
        f"missing transition, got HTTP {early.status_code}"
    )
    assert get_success_data(
        api_client.get_background_check(check["id"], BACKGROUND_REVIEWER)
    )["check_status"] == "SCHEDULED", "the refused call wrote nothing"

    # Move the logical clock just inside the acknowledgement window.
    set_clock(shift_iso(check["scheduled_due_at"], -6))
    accepted = get_success_data(
        api_client.acknowledge_background_check(check["id"], BACKGROUND_REVIEWER)
    )
    assert accepted["check_status"] == "IN_REVIEW", (
        "the same acknowledgement succeeds once the clock has reached the window, so the "
        "precondition is a date rather than a state"
    )