"""Content decisions: tier arithmetic, quorum arithmetic and the audit chain."""
import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_BASE,
    appoint_moderator,
    approve_protest,
    audit_decision,
    create_community,
    founding_moderator,
    get_account,
    get_community,
    get_content_decision,
    get_protest,
    make_moderator_headers,
    moderator_rows,
    record_decision,
    record_detection,
    request_protest,
    sanction_rows,
    set_clock,
    validate_error,
    TEST_USERS,
)


class TestEffectiveEnforcementTier:

    def test_lock_low_band_lands_on_tier_four(self, api):
        """PRD §3.4: "The second step adds the `dissection_band` to that base,
        unconditionally — the band is always added, whatever its value."
        PRD §3.4: "A `LOCK` decision at `dissection_band` 1 lands on tier 4, while
        the same `LOCK` at band 3 lands on tier 5 — the exact line between a
        decision that is cross-power reviewable and one that is not."

        Design: Difficulty/combinatorial_formula/effective_tier_band_added_on_every_low_band
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        moderator = founding_moderator(community_id)

        item_a = record_detection(community_id, source_id="src-a",
                                  subject_account_id="u-target", signal_severity_band=4,
                                  detection_confidence=0.75, overlap_ratio=0.10,
                                  published_at_utc="2026-09-12T00:00:00Z",
                                  actor_moderator_id=moderator["id"])
        decision_low = record_decision(community_id, item_a["id"], decision_outcome="LOCK",
                                       decision_confidence=0.75, dissection_band=1,
                                       precedent_approval_count=0,
                                       actor_moderator_id=moderator["id"])

        # LOCK base 3 + band 1 = 4; the confidence credit applies only at band >= 3.
        assert decision_low["effective_enforcement_tier"] == 4
        assert decision_low["effective_enforcement_tier"] != 3
        assert decision_low["requires_cross_power_approval"] is False

    def test_lock_material_edit_band_lands_on_tier_five(self, api):
        """PRD §3.4: "The third step computes an evidence-confidence credit that
        applies only on the material-edit path: when the `dissection_band` is at
        least 3, the credit is 1 if `decision_confidence` is at least 0.60 and 0
        otherwise".
        PRD §3.4: "`requires_cross_power_approval` is true exactly when the final
        tier is 5 and `precedent_approval_count` is below 3."

        Design: Difficulty/combinatorial_formula/effective_tier_band_added_on_every_low_band
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        moderator = founding_moderator(community_id)

        item_b = record_detection(community_id, source_id="src-b",
                                  subject_account_id="u-target", signal_severity_band=4,
                                  detection_confidence=0.70, overlap_ratio=0.10,
                                  published_at_utc="2026-09-12T00:00:00Z",
                                  actor_moderator_id=moderator["id"])
        decision_high = record_decision(community_id, item_b["id"], decision_outcome="LOCK",
                                        decision_confidence=0.70, dissection_band=3,
                                        precedent_approval_count=0,
                                        actor_moderator_id=moderator["id"])

        # LOCK base 3 + band 3 = 6, capped at 5 by the credit of 1.
        assert decision_high["effective_enforcement_tier"] == 5
        assert decision_high["requires_cross_power_approval"] is True


class TestProtestQuorumArithmetic:

    def test_five_moderator_team_requires_three_approvals(self, api):
        """PRD §3.7: "It is computed as the whole number ceiling of half the
        number of moderators whose `status` is `ACTIVE`, floored at 2 by taking
        the greater of 2 and that ceiling. Concretely, a community with 2
        moderators requires 2 approvals, one with 3 requires 2, one with 4
        requires 2, and one with 5 requires 3."

        Design: Difficulty/combinatorial_formula/protest_quorum_ceiling_half_then_minimum
        """
        state = _five_moderator_protest_setup()
        community_id = state["community_id"]
        protest_id = state["protest_id"]

        rows = moderator_rows_for(community_id)
        assert len(rows) == 5
        assert get_community(community_id)["active_moderator_count"] == 5
        assert _protest_required_quorum(community_id, protest_id) == 3

    def test_two_approvals_do_not_meet_a_five_moderator_quorum(self, api):
        """PRD §3.7: "The protest's `quorum_approval_count` must be at least its
        `required_quorum_count`, otherwise the request is refused with
        `ERR_QUORUM_NOT_MET`."
        PRD §3.7: "the 5-moderator community requiring 3 is the visible
        consequence of rounding half the team upward rather than downward."

        Design: Difficulty/combinatorial_formula/protest_quorum_ceiling_half_then_minimum
        """
        state = _five_moderator_protest_setup()
        community_id = state["community_id"]
        protest_id = state["protest_id"]
        principal = state["principal"]
        moderators = state["moderators"]

        approve_protest(community_id, protest_id, moderators[1]["id"], "mod-b",
                        actor_moderator_id=moderators[1]["id"])
        approve_protest(community_id, protest_id, moderators[2]["id"], "mod-c",
                        actor_moderator_id=moderators[2]["id"])

        response = api.coordinate_protest(community_id, protest_id,
                                          _moderator_headers(principal["id"]))
        validate_error(response, ApiErrorId.ERR_QUORUM_NOT_MET)

        protest = _protest(community_id, protest_id)
        assert protest["quorum_approval_count"] == 2
        assert protest["required_quorum_count"] == 3
        assert protest["status"] == "REQUESTED"
        assert get_community(community_id)["state"] == "ACTIVE"


class TestDecisionAuditChainReads:

    def test_decision_read_reports_every_derived_field(self, api):
        """PRD §3.10: "Every content decision carries `audit_log_ref`, a
        server-minted string that is distinct from the decision's own `id`."
        PRD §3.4: "`community_safety_override` is true exactly when the final tier
        is 5 and `community_health_index_override_present` is false."
        PRD §3.4: "The record also snapshots `overlap_ratio` from the consumed
        backlog item."

        Design: Corner/endpoints/decision_read_reports_every_derived_field
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        moderator = founding_moderator(community_id)
        item = record_detection(community_id, source_id="src-a",
                                subject_account_id="u-target", signal_severity_band=5,
                                detection_confidence=0.90, overlap_ratio=0.30,
                                published_at_utc="2026-09-12T00:00:00Z",
                                actor_moderator_id=moderator["id"])
        decision = record_decision(community_id, item["id"], decision_outcome="BAN_ISSUED",
                                   decision_confidence=0.90, dissection_band=0,
                                   precedent_approval_count=0,
                                   actor_moderator_id=moderator["id"])
        fresh = get_content_decision(community_id, decision["id"])

        assert fresh["effective_enforcement_tier"] == 5
        assert fresh["community_safety_override"] is True
        assert fresh["requires_cross_power_approval"] is True
        assert fresh["overlap_ratio"] == pytest.approx(0.30, abs=0.001)
        assert fresh["is_account_wide"] is False
        assert fresh["audit_log_ref"]
        assert fresh["audit_log_ref"] != fresh["id"]

    def test_audit_requires_cross_power_approval_flag(self, api):
        """PRD §3.4: "From `RECORDED`, an administrator may audit the decision,
        which requires the decision's `requires_cross_power_approval` flag to be
        true — an attempt to audit a decision that does not require cross-power
        approval is refused with `ERR_INVALID_STATE`."
        PRD §3.4: "A `LOCK` decision at `dissection_band` 1 lands on tier 4".

        Design: Corner/endpoints/conditional_action_requires_cross_power_approval_flag
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        moderator = founding_moderator(community_id)
        item = record_detection(community_id, source_id="src-la",
                                subject_account_id="u-target", signal_severity_band=4,
                                detection_confidence=0.85, overlap_ratio=0.20,
                                published_at_utc="2026-09-12T00:00:00Z",
                                actor_moderator_id=moderator["id"])
        decision = record_decision(community_id, item["id"], decision_outcome="LOCK",
                                   decision_confidence=0.85, dissection_band=1,
                                   precedent_approval_count=0,
                                   actor_moderator_id=moderator["id"])

        assert decision["effective_enforcement_tier"] == 4
        assert decision["requires_cross_power_approval"] is False

        response = api.audit_decision({"decision_id": decision["id"]}, _admin_headers())
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        assert get_content_decision(community_id, decision["id"])["status"] == "RECORDED"

    def test_second_audit_of_a_decision_is_invalid_state(self, api):
        """PRD §3.4: "Auditing transitions the decision to `AUDITED`, appends an
        administrator audit entry to `audit_log_ref`, and fires the community's
        recompute."
        PRD §3.4: "A decision's lifecycle is a short audit chain rather than a
        simple state."

        Design: Corner/errors/restatement_of_a_decided_decision_audit_is_invalid_state
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        moderator = founding_moderator(community_id)
        item = record_detection(community_id, source_id="src-twice",
                                subject_account_id="u-target", signal_severity_band=5,
                                detection_confidence=0.90, overlap_ratio=0.20,
                                published_at_utc="2026-09-12T00:00:00Z",
                                actor_moderator_id=moderator["id"])
        decision = record_decision(community_id, item["id"], decision_outcome="BAN_ISSUED",
                                   decision_confidence=0.90, dissection_band=0,
                                   precedent_approval_count=0,
                                   actor_moderator_id=moderator["id"])
        audited = audit_decision(decision["id"])
        assert audited["status"] == "AUDITED"

        response = api.audit_decision({"decision_id": decision["id"]}, _admin_headers())
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        assert get_content_decision(community_id, decision["id"])["status"] == "AUDITED"


class TestImmediateConsistency:

    def test_decision_synthesized_sanction_is_visible_immediately(self, api):
        """PRD §3.4: "an `AccountSanction` row is synthesized for the backlog
        item's `subject_account_id` with `status` `ACTIVE`, `decision_outcome`
        copied from the decision, `sanction_date_utc` at the logical clock,
        `is_account_wide` false and `account_wide_enforcement_counted` false."
        PRD §3.4: "the community's `applying_sanction_count` is recomputed".

        Design: Corner/consistency_model/immediate_consistency_of_sanction_effects_within_the_request
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        moderator = founding_moderator(community_id)
        item = record_detection(community_id, source_id="src-now",
                                subject_account_id="u-now", signal_severity_band=4,
                                detection_confidence=0.85, overlap_ratio=0.20,
                                published_at_utc="2026-09-12T00:00:00Z",
                                actor_moderator_id=moderator["id"])
        decision = record_decision(community_id, item["id"], decision_outcome="MUTE_ISSUED",
                                   decision_confidence=0.85, dissection_band=0,
                                   precedent_approval_count=0,
                                   actor_moderator_id=moderator["id"])
        assert decision["effective_enforcement_tier"] == 4

        community_after = get_community(community_id)
        assert community_after["applying_sanction_count"] == 1
        assert community_after["enforcement_tier"] == 1

        account = get_account("u-now")
        # §3.4: "`karma_points` starts at 100 and loses 3 for each distinct
        # community in which the account holds a `MUTE_ISSUED` or `BAN_ISSUED`
        # sanction whose `status` is `ACTIVE`." The decision has just synthesized
        # exactly such a row, so the account stands at 100 - 3 = 97.
        assert account["karma_points"] == 97
        assert account["account_sanction_index"] == pytest.approx(0.00, abs=0.001)

        rows = sanction_rows("u-now", params={"status": "ACTIVE"})
        assert len(rows) == 1
        assert rows[0]["account_wide_enforcement_counted"] is False
        assert rows[0]["sanction_date_utc"] == "2026-09-15T00:00:00.000Z"


# --- local helpers -----------------------------------------------------------

def _admin_headers():
    return TEST_USERS["platform_admin_headers"]


def _moderator_headers(moderator_id):
    return make_moderator_headers(moderator_id)


def _five_moderator_protest_setup():
    """A community with five ACTIVE moderators and one REQUESTED protest."""
    set_clock(CLOCK_BASE)
    community = create_community("r/Alpha", description="Alpha community")
    community_id = community["id"]
    principal = founding_moderator(community_id)
    moderators = [principal]
    for account_id in ("mod-b", "mod-c", "mod-d", "mod-e"):
        moderators.append(appoint_moderator(community_id, account_id,
                                            actor_moderator_id=principal["id"]))
    protest = request_protest(community_id, actor_moderator_id=principal["id"])
    return {
        "community_id": community_id,
        "protest_id": protest["id"],
        "principal": principal,
        "moderators": moderators,
    }


def moderator_rows_for(community_id):
    return moderator_rows(community_id, params={"status": "ACTIVE"})


def _protest(community_id, protest_id):
    return get_protest(community_id, protest_id)


def _protest_required_quorum(community_id, protest_id):
    return _protest(community_id, protest_id)["required_quorum_count"]