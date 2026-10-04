"""Multi-step lifecycle chains: referral toggles, the audit chain and the
conservation of account-level and community-level quantities."""
import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_BASE,
    apply_account_wide_sanction,
    audit_decision,
    create_community,
    file_and_submit_appeal,
    file_report,
    find_sanction,
    founding_moderator,
    get_account,
    get_appeal,
    get_community,
    get_content_decision,
    get_content_report,
    publish_post,
    record_decision,
    record_detection,
    refer_appeal,
    report_rows,
    request_reinstatement,
    revise_decision,
    sanction_rows,
    set_clock,
    setup_restricted_community,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestAppealWatchdogReferralToggle:

    def test_referral_toggle_keeps_a_monotone_counter(self, api):
        """PRD §3.6: "Both directions use the same capability, carry an
        `appeal_id` and an optional `note`, set `last_referred_at_utc` at the
        logical clock, and increment `referral_count` by one; the difference is
        only which edge they traverse, with `SUBMITTED` moving to `UNDER_WATCH`
        and `UNDER_WATCH` moving back to `SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/appeal_watchdog_referral_toggle_cycle
        """
        state = _appeal_ready_for_watchdog()
        community_id, appeal_id, sanction_id = state["community_id"], state["appeal_id"], state["sanction_id"]

        referred = _refer(appeal_id, "Referral one")
        assert referred["state"] == "UNDER_WATCH"
        assert referred["referral_count"] == 1

        returned = _refer(appeal_id, "Return one")
        assert returned["state"] == "SUBMITTED"
        assert returned["referral_count"] == 2

        again = _refer(appeal_id, "Referral two")
        assert again["state"] == "UNDER_WATCH"
        assert again["referral_count"] == 3
        # §3.8: an account-wide sanction on a fresh account recomputes the sanction
        # index to 1.00, which clears both posture gates in the same request, so
        # the issuing community is driven past ACTIVE by the fixture's own setup.
        assert get_community(community_id)["state"] == "INSTITUTION_NEGOTIATION"

    def test_referral_cycle_survives_three_round_trips(self, api):
        """PRD §3.6: "A platform administrator can also park a submitted appeal
        with a watchdog by referring it, and can return a watched appeal to the
        queue by referring it again."
        PRD §3.6: "`decision_reason_code` ... is null until the appeal reaches a
        terminal state."

        Design: Difficulty/non_linear_state_machine/appeal_watchdog_referral_toggle_cycle
        """
        state = _appeal_ready_for_watchdog()
        appeal_id = state["appeal_id"]

        _refer(appeal_id, "Referral one")
        _refer(appeal_id, "Return one")
        _refer(appeal_id, "Referral two")

        appeal = get_appeal("u-target", appeal_id)
        assert appeal["state"] == "UNDER_WATCH"
        assert appeal["referral_count"] == 3
        assert appeal["last_referred_at_utc"] is not None
        assert appeal["decision_reason_code"] is None

        sanction = find_sanction("u-target", status="ACTIVE")
        assert sanction["id"] == state["sanction_id"]
        assert sanction["status"] == "ACTIVE"


class TestDecisionSanctionLiftChain:

    def test_revision_is_refused_before_the_audit(self, api):
        """PRD §3.4: "From `AUDITED`, an administrator may reverse the decision,
        which transitions it to `REVISED` and unwinds a wide set of effects".
        PRD §2.6: "State eligibility follows, yielding `ERR_INVALID_STATE`."

        Design: Difficulty/transitive_cascade/decision_sanction_lift_chain_depth_three
        """
        state = _restricted_community_with_gate_five_decision()
        decision_id = state["decision_id"]

        response = api.revise_decision({"decision_id": decision_id}, ADMIN)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        assert get_content_decision(state["community_id"], decision_id)["status"] == "RECORDED"

    def test_audit_then_revision_lifts_the_sanction_and_reopens_the_report(self, api):
        """PRD §3.4: "the issuing `AccountSanction`, if there is one, moves to
        `status` `LIFTED` with `sanitized_on_utc` at the logical clock".
        PRD §3.4: "every `ContentReport` that this decision moved out of `OPEN`
        returns to `status` `OPEN`, except a report already in the terminal
        `RESOLVED_LOCKED` state".
        PRD §3.4: "The index is the numerator divided by the denominator".

        Design: Difficulty/transitive_cascade/decision_sanction_lift_chain_depth_three
        """
        state = _restricted_community_with_gate_five_decision()
        community_id = state["community_id"]
        decision_id = state["decision_id"]
        report_id = state["report_id"]

        audited = audit_decision(decision_id)
        assert audited["status"] == "AUDITED"

        revised = revise_decision(decision_id)
        assert revised["status"] == "REVISED"

        reopened = get_content_report(community_id, report_id)
        assert reopened["status"] == "OPEN"

        lifted = [row for row in sanction_rows("u-target") if row["status"] == "LIFTED"]
        assert lifted, "the decision's sanction must be lifted by the revision"
        assert lifted[0]["sanitized_on_utc"] is not None

        open_rows = report_rows(community_id, params={"status": "OPEN"})
        assert len(open_rows) == 1
        assert open_rows[0]["id"] == report_id

        account = get_account("u-target")
        # §3.4: "A `LIFTED` row is excluded from the numerator while remaining in
        # the denominator." This subject holds exactly the one sanction the
        # revision has just lifted, so the index rests at zero.
        assert account["account_sanction_index"] == pytest.approx(0.00, abs=0.001)

        released = validate_success(
            request_reinstatement(community_id, actor_moderator_id=state["moderator_id"]))
        assert released["id"] == community_id
        community = get_community(community_id)
        assert community["state"] == "ACTIVE"
        assert community["restricted_since_utc"] is None


class TestCommunityLevelConservation:

    def test_revision_returns_the_open_report_set_to_its_prior_size(self, api):
        """PRD §3.4: "every `ContentReport` that this decision moved out of `OPEN`
        returns to `status` `OPEN`, except a report already in the terminal
        `RESOLVED_LOCKED` state — that state is the one the system will not
        unwind, and once a report has reached it no transition returns it to
        `OPEN`."
        PRD §3.5: "The rounding is applied twice — once per report at the first
        step and once at the third — and both applications are specified."

        Design: Difficulty/compensating_invariant/open_report_count_conserved_across_revision_of_removal
        """
        state = _two_report_lock_fixture()
        community_id = state["community_id"]

        open_before_revision = report_rows(community_id, params={"status": "OPEN"})
        assert open_before_revision == []

        revise_decision(state["decision_remove"])

        assert get_content_report(community_id, state["report_remove"])["status"] == "OPEN"
        assert get_content_report(community_id, state["report_lock"])["status"] == "RESOLVED_LOCKED"

        open_after = report_rows(community_id, params={"status": "OPEN"})
        assert len(open_after) == 1
        assert open_after[0]["id"] == state["report_remove"]

        community = get_community(community_id)
        assert community["open_report_weight"] == pytest.approx(0.67, abs=0.001)
        assert community["health_index"] == pytest.approx(99.33, abs=0.001)
        assert community["health_index"] != pytest.approx(100.00, abs=0.001)

    def test_the_locked_report_is_never_unwound(self, api):
        """PRD §3.4: "to `RESOLVED_LOCKED` when the outcome is `LOCK`".
        PRD §3.3: "A report's `status` is one of `OPEN`, `RESOLVED`,
        `RESOLVED_LOCKED` or `DISMISSED`."
        PRD §3.5: "only `ESCALATED` clusters contribute to it and only `ACTIVE`
        moderators contribute to the inactivity penalty".

        Design: Difficulty/compensating_invariant/open_report_count_conserved_across_revision_of_removal
        """
        state = _two_report_lock_fixture()
        community_id = state["community_id"]

        locked = get_content_report(community_id, state["report_lock"])
        assert locked["status"] == "RESOLVED_LOCKED"

        revise_decision(state["decision_remove"])
        still_locked = get_content_report(community_id, state["report_lock"])
        assert still_locked["status"] == "RESOLVED_LOCKED"

        resolved = [row for row in report_rows(community_id)
                    if row["id"] == state["report_lock"]]
        assert resolved[0]["status"] == "RESOLVED_LOCKED"

        community = get_community(community_id)
        assert community["health_index"] == pytest.approx(
            100.00 - community["open_report_weight"], abs=0.01)


# --- local fixtures ----------------------------------------------------------

def _refer(appeal_id, note):
    return refer_appeal(appeal_id, note=note)


def _appeal_ready_for_watchdog():
    """A community with a banned account whose sanction is ACTIVE and an appeal
    filed and submitted against it."""
    set_clock(CLOCK_BASE)
    community = create_community("r/Alpha", description="Alpha community")
    community_id = community["id"]
    moderator = founding_moderator(community_id)
    sanction = apply_account_wide_sanction("u-target", community_id, "BAN_ISSUED")
    appeal = file_and_submit_appeal("u-target", sanction["id"], ground_code="ANALYSIS_ERROR")
    return {
        "community_id": community_id,
        "moderator_id": moderator["id"],
        "sanction_id": sanction["id"],
        "appeal_id": appeal["id"],
    }


def _restricted_community_with_gate_five_decision():
    """A genuinely RESTRICTED community plus a gate-5 decision that resolved a
    report on a fresh post."""
    state = setup_restricted_community(account_id="u-subject")
    community_id = state["community_id"]
    moderator_id = state["moderator_id"]

    post = publish_post(community_id, author_account_id="u-target")
    report = _file_report_on(community_id, post["id"], "rep-1")
    item = record_detection(community_id, source_id=post["id"], subject_account_id="u-target",
                            signal_severity_band=5, detection_confidence=0.90,
                            overlap_ratio=0.40, published_at_utc="2026-09-12T00:00:00Z",
                            actor_moderator_id=moderator_id)
    decision = record_decision(community_id, item["id"], decision_outcome="BAN_ISSUED",
                               decision_confidence=0.90, dissection_band=0,
                               precedent_approval_count=0, actor_moderator_id=moderator_id)
    assert decision["effective_enforcement_tier"] == 5
    assert decision["requires_cross_power_approval"] is True

    state.update({
        "post_id": post["id"],
        "report_id": report["id"],
        "decision_id": decision["id"],
    })
    return state


def _file_report_on(community_id, source_id, reporter, resolution_tier=1):
    return file_report(community_id, content_source_type="POST", content_source_id=source_id,
                       reporter_account_id=reporter, report_reason_code="VIOLENCE",
                       resolution_tier=resolution_tier)


def _two_report_lock_fixture():
    """Two tier-3 reports on one post, each resolved by a gate-5 decision that
    has been audited so the revision is admissible."""
    set_clock(CLOCK_BASE)
    community = create_community("r/Alpha", description="Alpha community")
    community_id = community["id"]
    moderator = founding_moderator(community_id)
    moderator_id = moderator["id"]

    # §3.5: a tier-3 report carries weight 2.0, so 2.0 / 3 = 0.67 — the value the
    # conserving revision must restore when exactly one of the two reopens.
    report_remove = _file_report_on(community_id, "src-remove", "rep-1", resolution_tier=3)
    report_lock = _file_report_on(community_id, "src-lock", "rep-2", resolution_tier=3)

    item_remove = record_detection(community_id, source_id="src-remove",
                                   subject_account_id="u-target", signal_severity_band=5,
                                   detection_confidence=0.90, overlap_ratio=0.20,
                                   published_at_utc="2026-09-12T00:00:00Z",
                                   actor_moderator_id=moderator_id)
    item_lock = record_detection(community_id, source_id="src-lock",
                                 subject_account_id="u-other", signal_severity_band=5,
                                 detection_confidence=0.90, overlap_ratio=0.20,
                                 published_at_utc="2026-09-12T00:00:00Z",
                                 actor_moderator_id=moderator_id)

    decision_remove = record_decision(community_id, item_remove["id"],
                                      decision_outcome="MUTE_ISSUED",
                                      decision_confidence=0.90, dissection_band=3,
                                      precedent_approval_count=0,
                                      actor_moderator_id=moderator_id)
    decision_lock = record_decision(community_id, item_lock["id"],
                                    decision_outcome="LOCK", decision_confidence=0.90,
                                    dissection_band=3, precedent_approval_count=0,
                                    actor_moderator_id=moderator_id)
    assert decision_remove["effective_enforcement_tier"] == 5
    assert decision_lock["effective_enforcement_tier"] == 5

    audit_decision(decision_remove["id"])
    audit_decision(decision_lock["id"])

    return {
        "community_id": community_id,
        "moderator_id": moderator_id,
        "report_remove": report_remove["id"],
        "report_lock": report_lock["id"],
        "decision_remove": decision_remove["id"],
        "decision_lock": decision_lock["id"],
    }