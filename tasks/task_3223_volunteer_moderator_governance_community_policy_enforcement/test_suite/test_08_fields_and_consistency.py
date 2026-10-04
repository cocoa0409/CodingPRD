"""Server-minted fields, the aggregate tier ladder, OCC on create-with-supersede,
denormalized-field reconciliation and the inclusive quarantine floor."""
import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_BASE,
    TEST_USERS,
    apply_account_wide_sanction,
    community_version,
    count_rows,
    create_community,
    escalate_cluster,
    file_report,
    founding_moderator,
    get_community,
    list_community_sanctions,
    record_cluster,
    report_rows,
    set_clock,
    setup_restricted_community,
    validate_error,
    validate_success,
    make_moderator_headers,
)


class TestServerMintedRuleFields:

    def test_rule_identity_and_version_are_server_minted(self, api):
        """PRD §2.5: "`id` (string): a unique, server-minted identifier formatted as
        a plain UUID, with no type prefix and no encoding of the entity kind."
        PRD §3.1: "A rule names its owner community through `community_id`, and
        every rule mutation carries the community's `expected_community_version`
        and advances that community's `version` by one."

        Design: Corner/entities/community_rule_system_fields_are_server_minted
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha")
        community_id = community["id"]
        moderator = founding_moderator(community_id)
        admin = TEST_USERS["platform_admin_headers"]

        rule = validate_success(api.create_rule(
            community_id,
            {"rule_code": "R-1", "rule_text": "Be civil", "rule_band": 1,
             "is_sitewide_floor": False, "expected_community_version": community["version"]},
            make_moderator_headers(moderator["id"])), 201)

        assert rule["status"] == "ACTIVE"
        assert rule["version"] == 1
        assert rule["id"]
        assert rule["created_at"]
        assert rule["updated_at"]
        assert rule["community_id"] == community_id

        fetched = validate_success(api.get_rule(community_id, rule["id"], admin))
        assert fetched["id"] == rule["id"]
        assert fetched["version"] == rule["version"]
        assert community_version(community_id) == community["version"] + 1


class TestAggregateTierLadder:

    def test_two_sanctions_cross_the_second_rung(self, api):
        """PRD §3.8: "It is driven by the community's `applying_sanction_count`,
        which is the number of `ACTIVE` `AccountSanction` rows whose
        `community_id` is this community. When that count is at most 1 the tier is
        1; when the count is exactly 2 the tier is 2; when the count is 3 or more
        the tier is 3."

        Design: Corner/validations/aggregate_sanction_count_drives_the_community_ladder
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha")
        community_id = community["id"]
        admin = TEST_USERS["platform_admin_headers"]

        assert get_community(community_id)["enforcement_tier"] == 1

        apply_account_wide_sanction("u-tier-1", community_id, "WARNING_ISSUED")
        assert get_community(community_id)["enforcement_tier"] == 1

        apply_account_wide_sanction("u-tier-2", community_id, "WARNING_ISSUED")
        after_two = get_community(community_id)
        assert after_two["applying_sanction_count"] == 2
        assert after_two["enforcement_tier"] == 2

    def test_three_sanctions_cross_the_third_rung(self, api):
        """PRD §3.8: "The two threshold constants are 2, where the second tier
        begins, and 3, where the third begins. The tier is an integer, and the
        ladder never skips or reverses except by the count itself falling."

        Design: Corner/validations/aggregate_sanction_count_drives_the_community_ladder
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha")
        community_id = community["id"]
        admin = TEST_USERS["platform_admin_headers"]

        for index in range(3):
            apply_account_wide_sanction(f"u-rung-{index}", community_id, "WARNING_ISSUED")

        after_three = get_community(community_id)
        assert after_three["applying_sanction_count"] == 3
        assert after_three["enforcement_tier"] == 3

        listed = list_community_sanctions(community_id).json()["data"]
        assert len(listed) == 3


class TestOptimisticConcurrencyOnProtestCreate:

    def test_protest_create_against_a_stale_version_is_refused(self, api):
        """PRD §2.7: "This applies to authoring a local rule, appointing a
        moderator, requesting a protest, and opening a succession. Each of these
        four is a create-with-supersede operation: the second write would succeed
        on its own semantics, because a newly authored rule, a newly appointed
        moderator, a new protest or a new succession legitimately supersedes the
        intent the earlier writer was reasoning about."
        PRD §3.7: "a stale `expected_community_version` is refused with
        `ERR_STALE_VERSION` and HTTP 412".

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_version_on_protest_create
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha")
        community_id = community["id"]
        observed_version = community["version"]
        moderator = founding_moderator(community_id)

        # Two later writes advance the community past the version the client saw.
        for code in ("R-1", "R-2"):
            validate_success(api.create_rule(
                community_id,
                {"rule_code": code, "rule_text": "Be civil", "rule_band": 1,
                 "is_sitewide_floor": False,
                 "expected_community_version": community_version(community_id)},
                make_moderator_headers(moderator["id"])), 201)

        response = api.create_protest(
            community_id,
            {"requested_access_mode": "READ_ONLY",
             "conflicting_cross_power_account_ids": [],
             "expected_community_version": observed_version},
            make_moderator_headers(moderator["id"]))
        validate_error(response, ApiErrorId.ERR_STALE_VERSION)

        assert count_rows(api.list_protests(
            community_id, TEST_USERS["platform_admin_headers"])) == 0
        assert get_community(community_id)["state"] == "ACTIVE"


class TestDerivedFieldReconciliation:

    def test_a_late_report_reconciles_the_denormalized_fields(self, api):
        """PRD §3.3: "Filing refreshes the community's `open_report_weight` and
        `health_index`. A report's `status` is one of `OPEN`, `RESOLVED`,
        `RESOLVED_LOCKED` or `DISMISSED`."
        PRD §3.5: "for every `OPEN` report, a tier weight is selected — 1.0 for a
        tier-1 report, 1.5 for tier 2 and 2.0 for tier 3 — divided by 3, and
        rounded half-up to two decimal places to give that report's effective
        open-report weight".

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_after_a_late_report
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha")
        community_id = community["id"]
        admin = TEST_USERS["platform_admin_headers"]

        before = validate_success(api.get_community(community_id, admin))
        assert before["open_report_weight"] == pytest.approx(0.00, abs=0.001)
        assert before["health_index"] == pytest.approx(100.00, abs=0.001)

        report = file_report(community_id, content_source_type="COMMENT",
                             content_source_id="cmt-late", reporter_account_id="rep-late",
                             report_reason_code="IMPERSONATION", resolution_tier=2)

        after = validate_success(api.get_community(community_id, admin))
        # round_half_up(1.5 / 3, 2) = 0.50, and 100.00 - 0.50 = 99.50.
        assert after["open_report_weight"] == pytest.approx(0.50, abs=0.001)
        assert after["health_index"] == pytest.approx(99.50, abs=0.001)

        open_rows = report_rows(community_id, params={"status": "OPEN"})
        assert len(open_rows) == 1
        assert open_rows[0]["id"] == report["id"]


class TestReinstatementConditions:

    def test_restricted_exit_is_blocked_by_the_health_floor(self, api):
        """PRD §3.8: "Four conditions guard the release from `RESTRICTED`: the same
        `health_index` floor of 70.00, the same zero inactive moderators, the same
        requirement of at least one active top moderator, and the same absence of
        an `OPEN` tier-3 report — the ninety-day clock is not part of the
        restricted exit and applies only to a community leaving quarantine."
        PRD §3.8: "The exit conditions are evaluated as one combined test, in a
        single pass, and any single unsatisfied condition blocks the request with
        `ERR_REINSTATEMENT_CONDITIONS_UNMET`."

        Design: Corner/calculations/quarantine_health_floor_blocks_reinstatement

        PRD-ONLY READING: with the ninety-day clock expressly excluded from the
        restricted exit, the health floor is the only arm this fixture can isolate —
        so the two escalated clusters drive `health_index` below 70.00 while the
        other three conditions stay satisfied.
        """
        set_clock(CLOCK_BASE)
        state = setup_restricted_community(account_id="u-target", name="r/Alpha")
        community_id = state["community_id"]
        moderator_id = state["moderator_id"]

        for index in range(3):
            file_report(community_id, content_source_type="COMMENT",
                        content_source_id=f"cmt-floor-{index}",
                        reporter_account_id=f"rep-floor-{index}",
                        report_reason_code="SPAM", resolution_tier=1)
        cluster = record_cluster(community_id, internal_link_count=10,
                                 external_link_count=10, participant_count=10,
                                 legitimate_participant_count=0,
                                 actor_moderator_id=moderator_id)
        escalate_cluster(cluster["id"], sanction_ladder="BAN")

        before = get_community(community_id)
        assert before["state"] == "RESTRICTED"
        # §3.5: three tier-1 reports weigh 3 * round(1.0 / 3, 2) = 0.99 and one
        # band-5 cluster at overlap 1.00 contributes its 30-point cap, so the
        # health index lands at 69.01 — under the 70.00 floor but still above the
        # 40.00 quarantine line.
        assert before["health_index"] == pytest.approx(69.01, abs=0.01)
        assert before["health_index"] < 70.00
        assert before["inactive_moderator_count"] == 0
        assert before["active_top_moderator_count"] == 1

        response = api.request_reinstatement(community_id,
                                             make_moderator_headers(state["moderator_id"]))
        error = validate_error(response, ApiErrorId.ERR_REINSTATEMENT_CONDITIONS_UNMET)
        assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE.value

        after = get_community(community_id)
        assert after["state"] == "RESTRICTED"
        assert after["quarantine_reinstatement_count"] == 0


class TestQuarantineFloorInclusivity:

    def test_health_on_or_below_the_line_is_quarantined(self, api):
        """PRD §3.8: "A community that is `RESTRICTED` is quarantined automatically
        when its recomputed `community_health_index` lands at or below 40.00."
        PRD §3.5: "only `ESCALATED` clusters contribute to it and only `ACTIVE`
        moderators contribute to the inactivity penalty".

        Design: Corner/cross_cutting_complexity_layers/community_quarantine_floor_is_inclusive_at_exactly_forty
        """
        set_clock(CLOCK_BASE)
        state = setup_restricted_community(account_id="u-pin", name="r/Pinned")
        community_id = state["community_id"]
        moderator_id = state["moderator_id"]

        # Two escalated band-5 clusters at overlap 1.00 drive the health index
        # onto the quarantine line whatever the per-cluster cap reading.
        for _index in range(2):
            cluster = record_cluster(community_id, internal_link_count=10,
                                     external_link_count=10, participant_count=10,
                                     legitimate_participant_count=0,
                                     actor_moderator_id=moderator_id)
            escalate_cluster(cluster["id"], sanction_ladder="BAN")

        community = get_community(community_id)
        assert community["health_index"] <= 40.00
        assert community["state"] == "QUARANTINED"
        assert community["inactive_moderator_count"] == 0
        assert community["open_report_weight"] == pytest.approx(0.00, abs=0.001)


# --- local fixtures ----------------------------------------------------------

def _succession_rows(community_id):
    from test_helpers import succession_rows
    return succession_rows(community_id)