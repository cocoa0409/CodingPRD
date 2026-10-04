"""Detection scoring, brigade geometry, sanctions, protests and creation shape."""
import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_BASE,
    EVIDENCE_COMPLETE_MIN_RATIO,
    TEST_USERS,
    advance_days,
    author_rule,
    create_community,
    file_report,
    founding_moderator,
    get_account,
    get_appeal,
    get_brigade_cluster,
    get_community,
    get_content_report,
    get_detection_item,
    get_protest,
    moderator_rows,
    publish_post,
    record_cluster,
    record_decision,
    record_detection,
    refer_appeal,
    report_rows,
    sanction_rows,
    set_clock,
    validate_error,
    validate_success,
    make_account_headers,
    make_moderator_headers,
)


class TestBrigadeGeometry:

    def test_overlap_threshold_at_exactly_thirty_hundredths(self, api):
        """PRD §3.5: "A third computed field, `evidence_complete`, is true exactly
        when the `overlap_ratio` is at least 0.30, and it is the gate that decides
        whether the cluster may be escalated at all."
        PRD §3.5: "the cluster's `evidence_complete` must be true, otherwise the
        request is refused with `ERR_BRIGADE_EVIDENCE_INCOMPLETE` — which is to
        say, an overlap ratio below 0.30 fails here".

        Design: Difficulty/boundary_precision_check/brigade_overlap_threshold_at_exactly_thirty_hundredths
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        moderator = founding_moderator(community_id)
        admin = TEST_USERS["platform_admin_headers"]

        # §3.5: overlap_ratio = 1 - legitimate/participants. Seven legitimate
        # participants out of ten give exactly 0.30, the inclusive evidence gate;
        # eight give 0.20, one tenth below it.
        edge = record_cluster(community_id, internal_link_count=5, external_link_count=5,
                              participant_count=10, legitimate_participant_count=7,
                              actor_moderator_id=moderator["id"])
        below = record_cluster(community_id, internal_link_count=5, external_link_count=5,
                               participant_count=10, legitimate_participant_count=8,
                               actor_moderator_id=moderator["id"])

        edge_fresh = get_brigade_cluster(community_id, edge["id"])
        assert edge_fresh["overlap_ratio"] == pytest.approx(EVIDENCE_COMPLETE_MIN_RATIO, abs=0.001)
        assert edge_fresh["evidence_complete"] is True

        escalated = api.escalate_brigade_cluster(
            {"cluster_id": edge["id"], "sanction_ladder": "WARNING"}, admin)
        assert validate_success(escalated)["status"] == "ESCALATED"

        below_fresh = get_brigade_cluster(community_id, below["id"])
        assert below_fresh["overlap_ratio"] == pytest.approx(0.20, abs=0.001)
        assert below_fresh["evidence_complete"] is False

    def test_one_hundredth_below_the_threshold_blocks_escalation(self, api):
        """PRD §3.5: "the cluster's `evidence_complete` must be true, otherwise
        the request is refused with `ERR_BRIGADE_EVIDENCE_INCOMPLETE` — which is to
        say, an overlap ratio below 0.30 fails here".
        PRD §3.5: "Escalating a cluster moves it to `ESCALATED`."

        Design: Difficulty/boundary_precision_check/brigade_overlap_threshold_at_exactly_thirty_hundredths
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        moderator = founding_moderator(community_id)
        admin = TEST_USERS["platform_admin_headers"]

        below = record_cluster(community_id, internal_link_count=5, external_link_count=5,
                               participant_count=10, legitimate_participant_count=8,
                               actor_moderator_id=moderator["id"])
        response = api.escalate_brigade_cluster(
            {"cluster_id": below["id"], "sanction_ladder": "WARNING"}, admin)
        validate_error(response, ApiErrorId.ERR_BRIGADE_EVIDENCE_INCOMPLETE)
        assert get_brigade_cluster(community_id, below["id"])["status"] == "DETECTED"

    def test_breadth_ladder_climbs_and_caps_at_five(self, api):
        """PRD §3.5: "Link breadth is the internal link count plus the external
        link count. The severity starts at 1; it becomes 2 once breadth reaches 5,
        3 once breadth reaches 10, and 4 once breadth reaches 20. A participant
        count of at least 50 adds one. An overlap ratio of at least 0.60 adds one
        more. The final band is the lesser of 5 and that sum."

        Design: Corner/calculations/brigade_signal_band_cumulative_ladder_at_the_cap
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        moderator = founding_moderator(community_id)

        low = record_cluster(community_id, internal_link_count=5, external_link_count=4,
                             participant_count=10, legitimate_participant_count=10,
                             actor_moderator_id=moderator["id"])
        assert low["overlap_ratio"] == pytest.approx(0.00, abs=0.001)
        assert low["signal_severity_band"] == 2

        mid = record_cluster(community_id, internal_link_count=24, external_link_count=0,
                             participant_count=10, legitimate_participant_count=10,
                             actor_moderator_id=moderator["id"])
        assert mid["overlap_ratio"] == pytest.approx(0.00, abs=0.001)
        assert mid["signal_severity_band"] == 4

        capped = record_cluster(community_id, internal_link_count=24, external_link_count=0,
                                participant_count=60, legitimate_participant_count=60,
                                actor_moderator_id=moderator["id"])
        assert capped["overlap_ratio"] == pytest.approx(0.00, abs=0.001)
        assert capped["signal_severity_band"] == 5
        assert capped["signal_severity_band"] != 6

    def test_escalation_severity_reads_health_after_the_recompute(self, api):
        """PRD §3.5: "an escalation severity for the escalation itself is computed
        from the cluster's band `B`, its overlap ratio `R` and the community's
        health index `H`: it is the lesser of 5 and the sum of the whole-number
        floor of `B` multiplied by one plus `R`, plus one when `H` is at least 60."
        PRD §3.5: "a band of 2 with an overlap of 0.40 and a health index of 60
        yields the floor of 2 multiplied by 1.40 — that is 2 — plus 1, or 3."

        Design: Corner/calculations/brigade_escalation_severity_health_escalator_boundary
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        moderator = founding_moderator(community_id)
        admin = TEST_USERS["platform_admin_headers"]

        cluster = record_cluster(community_id, internal_link_count=4, external_link_count=6,
                                 participant_count=10, legitimate_participant_count=6,
                                 actor_moderator_id=moderator["id"])
        assert cluster["signal_severity_band"] == 3
        assert cluster["overlap_ratio"] == pytest.approx(0.40, abs=0.001)

        escalation = validate_success(api.escalate_brigade_cluster(
            {"cluster_id": cluster["id"], "sanction_ladder": "BAN"}, admin))
        assert escalation["escalation_severity"] == 5
        assert escalation["escalation_severity"] != 4

        health = get_community(community_id)["health_index"]
        assert health == pytest.approx(85.00, abs=0.01)

    def test_revival_restores_the_cluster_and_lifts_the_health_penalty(self, api):
        """PRD §3.5: "A cluster may be revived: from `ESCALATED`, an administrator
        returns it to `DETECTED`, provided at least 7 days have passed since its
        `detected_at_utc` ... The revived cluster's health contribution is removed
        and the community's `health_index` is recomputed."

        Design: Difficulty/transitive_cascade/escalation_revive_appeal_grant_chain_depth_two
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        moderator = founding_moderator(community_id)
        admin = TEST_USERS["platform_admin_headers"]

        cluster = record_cluster(community_id, internal_link_count=10, external_link_count=10,
                                 participant_count=10, legitimate_participant_count=0,
                                 actor_moderator_id=moderator["id"])
        validate_success(api.escalate_brigade_cluster(
            {"cluster_id": cluster["id"], "sanction_ladder": "BAN"}, admin))

        advance_days(35)
        revived = validate_success(api.revive_brigade_cluster(
            {"cluster_id": cluster["id"]}, admin))
        assert revived["status"] == "DETECTED"

        rows, _meta = _paginated(api.list_brigade_clusters(
            community_id, admin, params={"status": "ESCALATED"}))
        assert rows == []

        health = get_community(community_id)["health_index"]
        assert health == pytest.approx(100.00, abs=0.01)

    def test_watchdog_deadline_lapse_grants_the_lifted_sanction(self, api):
        """PRD §3.6: "when an appeal sits in `UNDER_WATCH` and at least 30 days
        have elapsed since `last_referred_at_utc` with no evidence movement, and
        the appeal has been referred at least twice, it is granted automatically,
        which fires the same sanction transition into `LIFTED`."

        Design: Difficulty/transitive_cascade/escalation_revive_appeal_grant_chain_depth_two
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        admin = TEST_USERS["platform_admin_headers"]

        sanction = validate_success(api.apply_account_wide_sanction(
            {"account_id": "u-target", "community_id": community_id,
             "decision_outcome": "BAN_ISSUED"}, admin), 201)
        appeal = validate_success(api.file_appeal(
            "u-target", {"sanction_id": sanction["id"], "ground_code": "MODERATOR_MISCONDUCT",
                         "new_evidence_url": None,
                         "sanction_misapplication_present": False}, admin), 201)
        validate_success(api.submit_appeal("u-target", appeal["id"], admin))

        validate_success(api.refer_appeal(appeal["id"], admin, note="First referral"))
        second = validate_success(api.refer_appeal(appeal["id"], admin, note="Second referral"))
        # §3.6: the two directions traverse opposite edges, so the second referral
        # returns the watched appeal to the queue rather than parking it again.
        assert second["referral_count"] == 2
        assert second["state"] == "SUBMITTED"
        third = validate_success(api.refer_appeal(appeal["id"], admin, note="Third referral"))
        assert third["referral_count"] == 3
        assert third["state"] == "UNDER_WATCH"

        advance_days(35)

        granted = _get_appeal("u-target", appeal["id"])
        assert granted["state"] == "GRANTED"
        assert granted["decision_reason_code"] == "MISCONDUCT_CONFIRMED"

        lifted = _sanction_row("u-target", sanction["id"])
        assert lifted["status"] == "LIFTED"
        assert lifted["sanitized_on_utc"] is not None

    def test_watchdog_grant_restores_the_account_standing(self, api):
        """PRD §3.4: "`karma_points` starts at 100 and loses 3 for each distinct
        community in which the account holds a `MUTE_ISSUED` or `BAN_ISSUED`
        sanction whose `status` is `ACTIVE`; the value never falls below a floor of
        50, and it resets to 100 when the account holds no such active sanction."

        Design: Difficulty/transitive_cascade/escalation_revive_appeal_grant_chain_depth_two
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        admin = TEST_USERS["platform_admin_headers"]

        sanction = validate_success(api.apply_account_wide_sanction(
            {"account_id": "u-target", "community_id": community_id,
             "decision_outcome": "BAN_ISSUED"}, admin), 201)
        assert get_account("u-target")["karma_points"] == 97

        appeal = validate_success(api.file_appeal(
            "u-target", {"sanction_id": sanction["id"], "ground_code": "MODERATOR_MISCONDUCT",
                         "new_evidence_url": None,
                         "sanction_misapplication_present": False}, admin), 201)
        validate_success(api.submit_appeal("u-target", appeal["id"], admin))
        validate_success(api.refer_appeal(appeal["id"], admin, note="First referral"))
        validate_success(api.refer_appeal(appeal["id"], admin, note="Second referral"))
        # §3.6: the watchdog needs the appeal parked in UNDER_WATCH on at least
        # its second referral, so the odd referral count lands there.
        validate_success(api.refer_appeal(appeal["id"], admin, note="Third referral"))
        advance_days(35)

        account = get_account("u-target")
        assert account["karma_points"] == 100
        assert account["account_sanction_index"] == pytest.approx(0.00, abs=0.001)


class TestSanctionAwardLadder:

    def test_award_points_climb_the_registry_ladder(self, api):
        """PRD §3.4: "In practice this means an account whose first ever sanction
        is a `BAN_ISSUED` lands on `TIER_1` and scores exactly 150, a second
        sanction on the same account lands on `TIER_2` and scores exactly 250, and
        a fourth scores exactly 400."
        PRD §3.4: "The registry size is then counted and a tier selected: `TIER_1`
        when the registry holds no rows for this account, `TIER_2` when it holds at
        most two, and `TIER_3` beyond that."

        Design: Corner/calculations/sanction_award_points_tier_ladder

        PRD-ONLY READING: PRD §3.4 reads the registry as the write completes and
        states only that a second sanction scores 250 and a fourth scores 400. It
        is silent on the third write, so only the anchors it names are asserted.
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        admin = TEST_USERS["platform_admin_headers"]

        awards = []
        # §3.4 refuses a second account-wide sanction carrying the *same*
        # `decision_outcome` in the same community, so the ladder is climbed with
        # four distinct outcomes and the duplicate arm is never in play.
        for outcome in ("WARNING_ISSUED", "MUTE_ISSUED", "REMOVE", "BAN_ISSUED"):
            payload = {"account_id": "u-ladder", "community_id": community_id,
                       "decision_outcome": outcome}
            awards.append(validate_success(api.apply_account_wide_sanction(payload, admin), 201))

        assert awards[0]["award_points"] == 150
        assert awards[1]["award_points"] == 250
        assert awards[3]["award_points"] == 400

        rows = sanitize_sanctions("u-ladder")
        assert len(rows) == 4
        assert get_account("u-ladder")["account_sanction_index"] == pytest.approx(1.00, abs=0.001)


class TestProtestRestrictionOverlap:

    def test_open_restriction_rejects_a_second_coordination(self, api):
        """PRD §3.8: "A community is never in two postures at once".
        PRD §3.7: "And the community must currently be `ACTIVE`, otherwise the
        request is refused with `ERR_INVALID_STATE`."

        Design: Difficulty/resource_temporal_overlap/protest_restriction_cooldown_rejects_overlapping_request
        """
        state = _community_with_a_coordinated_protest()
        community_id = state["community_id"]

        assert get_community(community_id)["state"] == "PROTEST_RESTRICTED"

        response = api.coordinate_protest(community_id, state["protest_two_id"],
                                          make_moderator_headers(state["mod_a_id"]))
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)

        assert get_protest_status(community_id, state["protest_two_id"]) == "REQUESTED"

    def test_ending_the_first_restriction_frees_the_second(self, api):
        """PRD §3.7: "while the community is `PROTEST_RESTRICTED` the end of the
        protest also moves the community back from `PROTEST_RESTRICTED` to
        `ACTIVE` and clears `restricted_since_utc` to null".
        PRD §3.7: "On success the protest becomes `COORDINATED`, records
        `started_at_utc` at the logical clock".

        Design: Difficulty/resource_temporal_overlap/protest_restriction_cooldown_rejects_overlapping_request
        """
        state = _community_with_a_coordinated_protest()
        community_id = state["community_id"]

        ended = _end_protest(community_id, state["protest_one_id"], state["mod_a_id"])
        assert ended["status"] == "ENDED"

        restored = get_community(community_id)
        assert restored["state"] == "ACTIVE"
        assert restored["restricted_since_utc"] is None

        coordinated = _coordinate_protest(community_id, state["protest_two_id"], state["mod_a_id"])
        assert coordinated["status"] == "COORDINATED"
        assert get_community(community_id)["state"] == "PROTEST_RESTRICTED"


class TestProtests:

    def test_quorum_wins_over_the_access_mode_check(self, api):
        """PRD §3.7: "The protest's `quorum_approval_count` must be at least its
        `required_quorum_count`, otherwise the request is refused with
        `ERR_QUORUM_NOT_MET`."
        PRD §2.6: "Quorum arithmetic is checked first (`ERR_QUORUM_NOT_MET` for an
        account approving the same protest twice, and
        `ERR_CROSS_POWER_QUORUM_NOT_MET` when coordination runs with insufficient
        distinct power), then the protest access-mode restriction".

        Design: Corner/state_machines/protest_coordinate_quorum_check_precedes_access_mode
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        moderator = founding_moderator(community_id)

        protest = _request_protest(community_id, moderator["id"], "READ_ONLY")
        response = api.coordinate_protest(community_id, protest["id"],
                                          make_moderator_headers(moderator["id"]))
        error = validate_error(response, ApiErrorId.ERR_QUORUM_NOT_MET)
        assert error["error_id"] != ApiErrorId.ERR_PRIVATE_PROTEST_FORBIDDEN.value
        assert error["error_id"] != ApiErrorId.ERR_CROSS_POWER_QUORUM_NOT_MET.value

        assert get_community(community_id)["state"] == "ACTIVE"
        assert get_community(community_id)["version"] == 2

    def test_quorum_requirement_reads_the_parent_team_size(self, api):
        """PRD §3.7: "Concretely, a community with 2 moderators requires 2
        approvals, one with 3 requires 2, one with 4 requires 2, and one with 5
        requires 3."
        PRD §3.7: "The floor of 2 is what stops a single-moderator community
        needing only its own approval, and the ceiling is what makes the counts
        diverge at odd sizes".

        Design: Corner/validations/cross_entity_quorum_validation_depends_on_parent_team
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        mod_a = founding_moderator(community_id)
        mod_b = appoint_moderator_row(community_id, "mod-b", mod_a["id"])

        protest = _request_protest(community_id, mod_a["id"], "READ_ONLY")
        assert protest["required_quorum_count"] == 2

        appoint_moderator_row(community_id, "mod-c", mod_a["id"])
        assert get_community(community_id)["active_moderator_count"] == 3
        assert get_protest_required(community_id, protest["id"]) == 2

        appoint_moderator_row(community_id, "mod-d", mod_a["id"])
        assert get_community(community_id)["active_moderator_count"] == 4
        assert get_protest_required(community_id, protest["id"]) == 2


class TestTemporalWindows:

    def test_submission_turns_invalid_through_the_clock_alone(self, api):
        """PRD §3.6: "the logical clock must be strictly before the moment 7 days
        after the appeal's `filed_at_utc` — an appeal submitted 7 days or more
        after it was filed is refused with `ERR_APPEAL_WINDOW_CLOSED`."

        Design: Corner/validations/temporal_window_blocks_submission_after_seven_days
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        admin = TEST_USERS["platform_admin_headers"]

        sanction = validate_success(api.apply_account_wide_sanction(
            {"account_id": "u-late", "community_id": community_id,
             "decision_outcome": "BAN_ISSUED"}, admin), 201)
        appeal = validate_success(api.file_appeal(
            "u-late", {"sanction_id": sanction["id"], "ground_code": "ANALYSIS_ERROR",
                       "new_evidence_url": None,
                       "sanction_misapplication_present": False}, admin), 201)
        assert appeal["filed_at_utc"] == "2026-09-15T00:00:00.000Z"

        advance_days(7)
        response = api.submit_appeal("u-late", appeal["id"], admin)
        validate_error(response, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)

        fresh = _get_appeal("u-late", appeal["id"])
        assert fresh["state"] == "FILED"
        assert fresh["submitted_at_utc"] is None

    def test_submission_inside_the_window_is_accepted(self, api):
        """PRD §3.6: "On success the appeal records `submitted_at_utc` at the
        logical clock and sets `deadline_utc` to `submitted_at_utc` plus 30 days,
        which is the decider's deadline."

        Design: Corner/validations/temporal_window_blocks_submission_after_seven_days
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        admin = TEST_USERS["platform_admin_headers"]

        sanction = validate_success(api.apply_account_wide_sanction(
            {"account_id": "u-late", "community_id": community_id,
             "decision_outcome": "BAN_ISSUED"}, admin), 201)
        appeal = validate_success(api.file_appeal(
            "u-late", {"sanction_id": sanction["id"], "ground_code": "ANALYSIS_ERROR",
                       "new_evidence_url": None,
                       "sanction_misapplication_present": False}, admin), 201)

        submitted = validate_success(api.submit_appeal("u-late", appeal["id"], admin))
        assert submitted["state"] == "SUBMITTED"
        assert submitted["submitted_at_utc"] == "2026-09-15T00:00:00.000Z"
        assert submitted["deadline_utc"] == "2026-10-15T00:00:00.000Z"


class TestCreationShape:

    def test_community_creation_returns_posture_and_a_first_top_moderator(self, api):
        """PRD §3.1: "The creating call establishes the community at `state`
        `ACTIVE` with `enforcement_tier` 1, `health_index` 100.00,
        `active_moderator_count` 1, `active_top_moderator_count` 1,
        `inactive_moderator_count` 0, `active_rule_count` 0,
        `applying_sanction_count` 0, `quarantine_approval_count` 0 and
        `quarantine_reinstatement_count` 0, with `restricted_since_utc` and
        `protest_exemption_until_utc` both null."

        Design: Corner/entities/community_create_returns_posture_fields_and_first_top_moderator
        """
        set_clock(CLOCK_BASE)
        community = validate_success(api.create_community(
            {"name": "r/Alpha", "description": "Alpha community", "is_over_18": False},
            make_account_headers("mod-alpha")), 201)
        community_id = community["id"]

        assert community["name"] == "r/Alpha"
        assert community["is_over_18"] is False
        assert community["state"] == "ACTIVE"
        assert community["enforcement_tier"] == 1
        assert community["health_index"] == pytest.approx(100.00, abs=0.001)
        assert community["active_moderator_count"] == 1
        assert community["active_top_moderator_count"] == 1
        assert community["inactive_moderator_count"] == 0
        assert community["active_rule_count"] == 0
        assert community["version"] == 1
        assert community["restricted_since_utc"] is None
        assert community["quarantine_approval_count"] == 0
        assert community["quarantine_reinstatement_count"] == 0

        rows = moderator_rows(community_id)
        assert len(rows) == 1
        assert rows[0]["moderator_role"] == "TOP_MODERATOR"
        assert rows[0]["status"] == "ACTIVE"
        assert rows[0]["top_rank"] == 1
        assert rows[0]["is_top_moderator"] is True
        assert rows[0]["moderator_version"] == 1

    def test_omitted_is_over_18_defaults_to_false_on_post_and_community(self, api):
        """PRD §3.3: "`post_type` is one of `TEXT`, `LINK`, `IMAGE` or `CROSSPOST`,
        and `is_over_18` defaults to false."
        PRD §3.1: "The maturity declaration defaults to false when omitted".

        Design: Corner/entities/community_create_omitting_is_over_18_defaults_to_false
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha")
        community_id = community["id"]
        post = publish_post(community_id, author_account_id="user-ap")

        assert post["is_over_18"] is False
        assert post["is_over_18"] is not None
        assert post["status"] == "PUBLISHED"
        assert post["removal_count"] == 0
        assert get_community(community_id)["is_over_18"] is False

    def test_get_round_trips_configuration_and_null_derived_fields(self, api):
        """PRD §2.5: "`id` (string): a unique, server-minted identifier formatted as
        a plain UUID, with no type prefix and no encoding of the entity kind."
        PRD §3.1: "The maturity declaration defaults to false when omitted, and it
        is a hard sitewide-policy flag".

        Design: Corner/entities/community_get_round_trips_configuration_and_derived_fields
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/NightShift", founder_account_id="mod-alpha",
                                     description="Late night discussion", is_over_18=True)
        fresh = api.get_community(community["id"], TEST_USERS["anonymous_headers"])
        data = validate_success(fresh)

        assert data["name"] == "r/NightShift"
        assert data["description"] == "Late night discussion"
        assert data["is_over_18"] is True
        assert data["protest_exemption_until_utc"] is None
        assert data["restricted_since_utc"] is None
        assert data["applying_sanction_count"] == 0
        assert data["open_report_weight"] == pytest.approx(0.00, abs=0.001)
        assert data["health_index"] == pytest.approx(100.00, abs=0.001)

    def test_community_derived_fields_move_independently(self, api):
        """PRD §3.5: "First, for every `OPEN` report, a tier weight is selected —
        1.5 for tier 2 ... divided by 3, and rounded half-up to two decimal places
        to give that report's effective open-report weight".
        PRD §3.1: "refreshes `active_rule_count`, advances the community's
        `version` by one".

        Design: Corner/entities/community_derived_fields_recompute_from_children
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha")
        community_id = community["id"]
        moderator = founding_moderator(community_id)

        author_rule(community_id, rule_code="R-3", rule_text="Adult only", rule_band=3,
                    is_sitewide_floor=True, actor_moderator_id=moderator["id"])
        file_report(community_id, content_source_type="COMMENT", content_source_id="cmt-1",
                    reporter_account_id="rep-1", report_reason_code="HARASSMENT",
                    resolution_tier=2)
        file_report(community_id, content_source_type="COMMENT", content_source_id="cmt-2",
                    reporter_account_id="rep-2", report_reason_code="SPAM",
                    resolution_tier=2)

        fresh = get_community(community_id)
        assert fresh["open_report_weight"] == pytest.approx(1.00, abs=0.001)
        assert fresh["health_index"] == pytest.approx(99.00, abs=0.001)
        assert fresh["active_rule_count"] == 1
        assert fresh["active_moderator_count"] == 1
        assert fresh["active_top_moderator_count"] == 1
        assert fresh["applying_sanction_count"] == 0

    def test_community_name_uniqueness_blocks_an_active_holder(self, api):
        """PRD §3.1: "The name must be unique among all communities whose `state`
        is other than `CLOSED`; a collision is refused with
        `ERR_DUPLICATE_COMMUNITY_NAME`."

        Design: Corner/validations/community_name_uniqueness_among_non_closed_communities
        """
        set_clock(CLOCK_BASE)
        first = create_community("r/Alpha", founder_account_id="mod-a",
                                 description="First holder")

        response = api.create_community({"name": "r/Alpha", "description": "Contender"},
                                        make_account_headers("mod-b"))
        validate_error(response, ApiErrorId.ERR_DUPLICATE_COMMUNITY_NAME)

        rows, _meta = _paginated(api.list_communities(TEST_USERS["platform_admin_headers"]))
        assert len(rows) == 1
        assert get_community(first["id"])["state"] == "ACTIVE"


class TestReportResolution:

    def test_decision_cascades_consume_resolve_and_recompute(self, api):
        """PRD §3.4: "The consumed backlog item moves to `status` `CONSUMED`.
        Every `ContentReport` of the community whose `content_source_type` and
        `content_source_id` equal the consumed item's `source_type` and `source_id`
        moves out of `OPEN`: to `RESOLVED` in the ordinary case".
        PRD §3.3: "Filing refreshes the community's `open_report_weight` and
        `health_index`. A report's `status` is one of `OPEN`, `RESOLVED`,
        `RESOLVED_LOCKED` or `DISMISSED`."

        Design: Corner/cross_cutting_complexity_layers/cascade_ordering_within_one_decision_request
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        moderator = founding_moderator(community_id)

        post = publish_post(community_id, author_account_id="u-target")
        report = file_report(community_id, content_source_type="POST",
                             content_source_id=post["id"], reporter_account_id="rep-1",
                             report_reason_code="SPAM", resolution_tier=1)
        item = record_detection(community_id, source_id=post["id"],
                                subject_account_id="u-target", signal_severity_band=3,
                                detection_confidence=0.80, overlap_ratio=0.20,
                                published_at_utc="2026-09-12T00:00:00Z",
                                actor_moderator_id=moderator["id"])
        record_decision(community_id, item["id"], decision_outcome="REMOVE",
                        decision_confidence=0.80, dissection_band=0,
                        precedent_approval_count=0, actor_moderator_id=moderator["id"])

        assert get_detection_item(community_id, item["id"])["status"] == "CONSUMED"
        assert get_content_report(community_id, report["id"])["status"] == "RESOLVED"
        assert report_rows(community_id, params={"status": "OPEN"}) == []

        fresh = get_community(community_id)
        assert fresh["open_report_weight"] == pytest.approx(0.00, abs=0.001)
        assert fresh["health_index"] == pytest.approx(100.00, abs=0.001)
        assert fresh["state"] == "ACTIVE"

    def test_denied_appeal_cannot_be_decided_again(self, api):
        """PRD §3.6: "A denial moves the appeal from `SUBMITTED` to `DENIED` and
        carries a single temporal precondition — the logical clock must be strictly
        before `deadline_utc` ... and it records `decision_reason_code` as
        `NO_NEW_EVIDENCE`."
        PRD §2.6: "State eligibility follows, yielding `ERR_INVALID_STATE`."

        Design: Corner/errors/appeal_decide_on_an_already_decided_appeal_is_invalid_state
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        admin = TEST_USERS["platform_admin_headers"]

        sanction = validate_success(api.apply_account_wide_sanction(
            {"account_id": "u-denied", "community_id": community_id,
             "decision_outcome": "BAN_ISSUED"}, admin), 201)
        appeal = validate_success(api.file_appeal(
            "u-denied", {"sanction_id": sanction["id"], "ground_code": "ANALYSIS_ERROR",
                         "new_evidence_url": None,
                         "sanction_misapplication_present": False}, admin), 201)
        validate_success(api.submit_appeal("u-denied", appeal["id"], admin))

        denied = validate_success(api.decide_appeal("u-denied", appeal["id"],
                                                    {"decision": "DENY"}, admin))
        assert denied["state"] == "DENIED"
        assert denied["decision_reason_code"] == "NO_NEW_EVIDENCE"

        response = api.decide_appeal("u-denied", appeal["id"], {"decision": "GRANT"}, admin)
        error = validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        assert error["error_id"] != ApiErrorId.ERR_NO_NEW_EVIDENCE.value
        assert _sanction_status("u-denied", sanction["id"]) == "ACTIVE"


class TestAtomicReinstatement:

    def test_reinstatement_of_an_active_sanction_changes_nothing(self, api):
        """PRD §3.6: "Two conditions guard the reactivation: the sanction must
        currently be `LIFTED`, otherwise the request is refused with
        `ERR_INVALID_STATE`; and the issuing community must be `ACTIVE` or
        `RESTRICTED`, otherwise the request is refused with
        `ERR_ACTIVE_SANCTION_CONFLICT`."
        PRD §3.6: "The same conflict code covers the related case in which a
        reinstatement targets a sanction that is already `ACTIVE`".

        Design: Corner/endpoints/bulk_reinstatement_has_no_partial_success_semantics
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        admin = TEST_USERS["platform_admin_headers"]

        active_sanction = validate_success(api.apply_account_wide_sanction(
            {"account_id": "u-mixed", "community_id": community_id,
             "decision_outcome": "WARNING_ISSUED"}, admin), 201)
        liftable = validate_success(api.apply_account_wide_sanction(
            {"account_id": "u-mixed", "community_id": community_id,
             "decision_outcome": "BAN_ISSUED"}, admin), 201)
        appeal = validate_success(api.file_appeal(
            "u-mixed", {"sanction_id": liftable["id"], "ground_code": "ANALYSIS_ERROR",
                        "sanction_misapplication_present": True}, admin), 201)
        validate_success(api.submit_appeal("u-mixed", appeal["id"], admin))
        validate_success(api.decide_appeal("u-mixed", appeal["id"], {"decision": "GRANT"}, admin))

        response = api.reinstate_sanction({"sanction_id": active_sanction["id"]}, admin)
        validate_error(response, ApiErrorId.ERR_ACTIVE_SANCTION_CONFLICT)

        assert _sanction_status("u-mixed", active_sanction["id"]) == "ACTIVE"
        lifted = _sanction_row("u-mixed", liftable["id"])
        assert lifted["status"] == "LIFTED"
        assert lifted["sanitized_on_utc"] is not None
        assert len(sanitize_sanctions("u-mixed", status="ACTIVE")) == 1


# --- local helpers -----------------------------------------------------------

def _paginated(response):
    from test_helpers import validate_paginated
    return validate_paginated(response)


def _request_protest(community_id, moderator_id, mode):
    from test_helpers import request_protest
    return request_protest(community_id, requested_access_mode=mode,
                           actor_moderator_id=moderator_id)


def appoint_moderator_row(community_id, account_id, actor_moderator_id):
    from test_helpers import appoint_moderator
    return appoint_moderator(community_id, account_id, actor_moderator_id=actor_moderator_id)


def get_protest_required(community_id, protest_id):
    from test_helpers import get_protest
    return get_protest(community_id, protest_id)["required_quorum_count"]


def _get_appeal(account_id, appeal_id):
    from test_helpers import get_appeal
    return get_appeal(account_id, appeal_id)


def sanitize_sanctions(account_id, status=None):
    params = {"status": status} if status else None
    return sanction_rows(account_id, params=params)


def _sanction_row(account_id, sanction_id):
    for row in sanction_rows(account_id):
        if row["id"] == sanction_id:
            return row
    raise AssertionError(f"sanction {sanction_id!r} not found for {account_id!r}")


def _sanction_status(account_id, sanction_id):
    return _sanction_row(account_id, sanction_id)["status"]


def _community_with_a_coordinated_protest():
    """One community holding a COORDINATED protest, plus a second REQUESTED
    protest already carrying its two approvals."""
    set_clock(CLOCK_BASE)
    community = create_community("r/Alpha", description="Alpha community")
    community_id = community["id"]
    mod_a = founding_moderator(community_id)
    mod_b = appoint_moderator_row(community_id, "mod-b", mod_a["id"])
    create_community("r/Beta", founder_account_id="mod-b")

    from test_helpers import approve_protest, request_protest
    protest_one = request_protest(community_id, actor_moderator_id=mod_a["id"])
    approve_protest(community_id, protest_one["id"], mod_a["id"], "mod-a",
                    actor_moderator_id=mod_a["id"])
    approve_protest(community_id, protest_one["id"], mod_b["id"], "mod-b",
                    actor_moderator_id=mod_b["id"])
    _coordinate_protest(community_id, protest_one["id"], mod_a["id"])

    protest_two = request_protest(community_id, requested_access_mode="RESTRICTED",
                                  actor_moderator_id=mod_a["id"])
    approve_protest(community_id, protest_two["id"], mod_a["id"], "mod-a",
                    actor_moderator_id=mod_a["id"])
    approve_protest(community_id, protest_two["id"], mod_b["id"], "mod-b",
                    actor_moderator_id=mod_b["id"])

    return {
        "community_id": community_id,
        "mod_a_id": mod_a["id"],
        "mod_b": mod_b,
        "protest_one_id": protest_one["id"],
        "protest_two_id": protest_two["id"],
    }


def _coordinate_protest(community_id, protest_id, moderator_id):
    from test_helpers import coordinate_protest
    return coordinate_protest(community_id, protest_id, actor_moderator_id=moderator_id)


def _end_protest(community_id, protest_id, moderator_id):
    from test_helpers import end_protest
    return end_protest(community_id, protest_id, actor_moderator_id=moderator_id)


def get_protest_status(community_id, protest_id):
    from test_helpers import get_protest
    return get_protest(community_id, protest_id)["status"]