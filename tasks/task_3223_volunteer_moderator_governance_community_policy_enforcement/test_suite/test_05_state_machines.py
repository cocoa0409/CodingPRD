"""State machines, dormancy boundaries and community posture moves."""
import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_BASE,
    advance_days,
    appoint_moderator,
    approve_protest,
    create_community,
    dispute_succession,
    founding_moderator,
    get_community,
    get_moderator,
    get_succession,
    open_succession,
    record_discussion,
    request_protest,
    set_clock,
    validate_error,
    make_moderator_headers,
    rule_rows,
)


class TestDormancyWindowBoundary:

    def test_anchor_exactly_ninety_days_old_is_removable(self, api):
        """PRD §3.9: "A moderator is inactive exactly when at least 90 days have
        elapsed between that anchor and the logical clock. The window constant is
        90 days, and the boundary is inclusive in the direction that counts as
        inactive: a moderator whose most recent moderation action was 91 days
        before the clock, with no community re-anchor, is counted inactive, while
        the same moderator at 89 days is not."
        PRD §3.6: "An appeal's `deadline_utc` is the field to watch".

        Design: Difficulty/boundary_precision_check/inactivity_window_at_exactly_ninety_days
        """
        state = _dormant_member_fixture(anchor_day="2026-09-16")
        community_id = state["community_id"]
        target = state["target"]

        community = get_community(community_id)
        assert community["inactive_moderator_count"] == 1

        version = get_moderator(community_id, target["id"])["moderator_version"]
        response = api.remove_moderator(
            community_id, target["id"], {"expected_moderator_version": version},
            make_moderator_headers(state["principal"]["id"]))
        removed = _success(response)
        assert removed["status"] == "REMOVED_FOR_INACTIVITY"
        assert removed["removal_reason_code"] == "INACTIVITY"
        assert get_community(community_id)["inactive_moderator_count"] == 0

    def test_anchor_eighty_nine_days_old_is_not_removable(self, api):
        """PRD §3.2: "The moderator's inactivity anchor must be at least ninety
        days before the logical clock, otherwise the request is refused with
        `ERR_INACTIVITY_REMOVAL_NOT_JUSTIFIED`."
        PRD §3.9: "The removal route of §3.2 is the enforcement arm of this rule:
        a moderator may be removed for inactivity only once the anchor has cleared
        the 90-day line".

        Design: Difficulty/boundary_precision_check/inactivity_window_at_exactly_ninety_days
        """
        state = _dormant_member_fixture(anchor_day="2026-09-17")
        community_id = state["community_id"]
        target = state["target"]

        version = get_moderator(community_id, target["id"])["moderator_version"]
        response = api.remove_moderator(
            community_id, target["id"], {"expected_moderator_version": version},
            make_moderator_headers(state["principal"]["id"]))
        validate_error(response, ApiErrorId.ERR_INACTIVITY_REMOVAL_NOT_JUSTIFIED)

        unchanged = get_moderator(community_id, target["id"])
        assert unchanged["status"] == "ACTIVE"


class TestVersionPrecedence:

    def test_restricted_coordinate_advances_the_community_version(self, api):
        """PRD §2.7: "The community-scoped create routes carry
        `expected_community_version`, which must equal the target community's
        current `version`."
        PRD §3.7: "On success the protest becomes `COORDINATED`, records
        `started_at_utc` at the logical clock, copies the community's
        `protest_exemption_until_utc` into its own
        `exemption_granted_until_utc`, and the community moves from `ACTIVE` to
        `PROTEST_RESTRICTED` with `restricted_since_utc` at the logical clock."

        Design: Difficulty/priority_pair_validation_conflict/stale_version_precedes_invalid_state
        """
        state = _restricted_by_coordination()
        community_id = state["community_id"]

        community = get_community(community_id)
        assert community["state"] == "PROTEST_RESTRICTED"
        assert community["version"] > state["observed_version"], (
            "the observed version 1 must be genuinely stale after the writes"
        )
        assert state["observed_version"] == 1

    def test_stale_succession_create_is_refused_ahead_of_the_state_gate(self, api):
        """PRD §2.7: "opening a succession ... when it fails the request is
        refused with `ERR_STALE_VERSION` and HTTP 412."
        PRD §2.6: "the supplied version field is compared with the persisted
        version before any state precondition is evaluated, so that a client whose
        view is stale and whose target is also in an ineligible state is told
        about the staleness with `ERR_STALE_VERSION` rather than about the state."

        Design: Difficulty/priority_pair_validation_conflict/stale_version_precedes_invalid_state
        """
        state = _restricted_by_coordination()
        community_id = state["community_id"]

        response = api.create_succession(
            community_id, {"expected_community_version": state["observed_version"]},
            make_moderator_headers(state["moderator_id"]))
        validate_error(response, ApiErrorId.ERR_STALE_VERSION)

        assert api.list_successions.__self__ is not None
        rows = _succession_rows(community_id)
        assert rows == []
        assert get_community(community_id)["state"] == "PROTEST_RESTRICTED"


class TestSuccessionTerminalLockdown:

    def test_completed_succession_refuses_a_late_discussion_round(self, api):
        """PRD §3.2: "Once `handover_deadline_utc` has passed while the succession
        is still `HANDOVER_BLOCKED` and the block was never resolved, it completes
        with `completion_reason` `PREVENTED_BY_DISPUTE`."
        PRD §2.6: "State eligibility follows, yielding `ERR_INVALID_STATE`."

        Design: Corner/state_machines/succession_discussion_round_after_completion_is_invalid_state
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        mod_a = founding_moderator(community_id)
        mod_b = appoint_moderator(community_id, "mod-b", actor_moderator_id=mod_a["id"])

        succession = open_succession(community_id, actor_moderator_id=mod_a["id"])
        record_discussion(community_id, succession["id"], round_note="Round by mod-a",
                          actor_moderator_id=mod_a["id"])
        dispute_succession(community_id, succession["id"], dispute_note="mod-b blocks",
                           actor_moderator_id=mod_b["id"])
        advance_days(35)

        closed = get_succession(community_id, succession["id"])
        assert closed["state"] == "COMPLETED"
        assert closed["completion_reason"] == "PREVENTED_BY_DISPUTE"

        response = api.record_succession_discussion(
            community_id, succession["id"], {"round_note": "Too late"},
            make_moderator_headers(mod_b["id"]))
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        assert get_succession(community_id, succession["id"])["discussion_round_count"] == 1


class TestPostureTransitions:

    def test_reinstatement_from_active_is_refused(self, api):
        """PRD §3.8: "From `QUARANTINED` a successful request moves the community
        to `RESTRICTED`, increments the community's lifetime
        `quarantine_reinstatement_count` by one".
        PRD §2.6: "The existence band occupies the next rank ... and it is followed
        immediately by the optimistic-concurrency band ... State eligibility
        follows, yielding `ERR_INVALID_STATE`."

        Design: Corner/state_machines/community_reinstatement_from_active_is_invalid_state
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        moderator = founding_moderator(community_id)

        response = api.request_reinstatement(community_id, make_moderator_headers(moderator["id"]))
        error = validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        assert error["error_id"] != ApiErrorId.ERR_REINSTATEMENT_CONDITIONS_UNMET.value

        after = get_community(community_id)
        assert after["state"] == "ACTIVE"
        assert after["quarantine_reinstatement_count"] == 0

    def test_escalation_retires_the_conflicting_rule(self, api):
        """PRD §3.1: "the offending rule is retired through the escalation route,
        which carries a `rule_id` identifying the rule and an `escalation_note`
        describing the conflict. The escalation records an audit entry against the
        community, marks the targeted rule `RETIRED`, refreshes
        `active_rule_count`, advances the community's `version` by one".
        PRD §3.1: "A rule's `status` is either `ACTIVE` or `RETIRED`, and
        `RETIRED` is reached by escalation or by an explicit retirement; there is
        no third status."

        Design: Corner/state_machines/escalation_retires_the_conflicting_rule
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        moderator = founding_moderator(community_id)

        rule = _author_rule(community_id, moderator["id"], "R-1", 2)
        escalated = _escalate(community_id, rule["id"], moderator["id"])
        assert escalated["status"] == "RETIRED"

        assert get_community(community_id)["active_rule_count"] == 0
        retired = [row for row in rule_rows(community_id, params={"status": "RETIRED"})]
        assert len(retired) == 1
        assert retired[0]["id"] == rule["id"]


# --- local helpers -----------------------------------------------------------

def _success(response):
    from test_helpers import validate_success
    return validate_success(response)


def _author_rule(community_id, moderator_id, code, band):
    from test_helpers import author_rule
    return author_rule(community_id, rule_code=code, rule_band=band,
                       actor_moderator_id=moderator_id)


def _escalate(community_id, rule_id, moderator_id):
    from test_helpers import escalate_rule
    return escalate_rule(community_id, rule_id, actor_moderator_id=moderator_id)


def _succession_rows(community_id):
    from test_helpers import succession_rows
    return succession_rows(community_id)


def _dormant_member_fixture(anchor_day):
    """A two-moderator team whose regular moderator's action anchor sits on
    ``anchor_day``; the principal acted later so only the target is dormant."""
    set_clock(CLOCK_BASE)
    community = create_community("r/Alpha", description="Alpha community")
    community_id = community["id"]
    principal = founding_moderator(community_id)
    target = appoint_moderator(community_id, "mod-b", actor_moderator_id=principal["id"])

    set_clock(f"{anchor_day}T00:00:00Z")
    _author_rule(community_id, target["id"], "R-B", 1)

    # The principal acts 15 days after the target so its own anchor stays fresh.
    set_clock(_plus_days(anchor_day, 15))
    _author_rule(community_id, principal["id"], "R-A", 1)

    set_clock("2026-12-15T00:00:00Z")
    return {
        "community_id": community_id,
        "principal": principal,
        "target": target,
    }


def _plus_days(iso_day, days):
    from test_helpers.fixtures import _advance_days
    return _advance_days(f"{iso_day}T00:00:00Z", days)


def _restricted_by_coordination():
    """A community driven into PROTEST_RESTRICTED; the observed version 1 is left
    genuinely stale."""
    set_clock(CLOCK_BASE)
    community = create_community("r/Alpha", description="Alpha community")
    community_id = community["id"]
    observed_version = community["version"]
    mod_a = founding_moderator(community_id)
    mod_b = appoint_moderator(community_id, "mod-b", actor_moderator_id=mod_a["id"])
    create_community("r/Beta", founder_account_id="mod-b")

    protest = request_protest(community_id, actor_moderator_id=mod_a["id"])
    approve_protest(community_id, protest["id"], mod_a["id"], "mod-a",
                    actor_moderator_id=mod_a["id"])
    approve_protest(community_id, protest["id"], mod_b["id"], "mod-b",
                    actor_moderator_id=mod_b["id"])
    coordinated = api_coordinate(community_id, protest["id"], mod_a["id"])
    assert coordinated["status"] == "COORDINATED"

    return {
        "community_id": community_id,
        "moderator_id": mod_a["id"],
        "observed_version": observed_version,
        "protest_id": protest["id"],
    }


def api_coordinate(community_id, protest_id, moderator_id):
    from test_helpers import coordinate_protest
    return coordinate_protest(community_id, protest_id, actor_moderator_id=moderator_id)