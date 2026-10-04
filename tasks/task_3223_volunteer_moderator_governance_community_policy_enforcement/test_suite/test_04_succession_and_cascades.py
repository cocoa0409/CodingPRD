"""Succession cycles, cross-entity gating and the archival cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_BASE,
    appoint_moderator,
    archive_community,
    create_community,
    dispute_succession,
    founding_moderator,
    get_community,
    get_moderator,
    get_succession,
    moderator_rows,
    open_succession,
    prevent_succession,
    record_discussion,
    resign,
    setup_quarantined_community,
    set_clock,
    validate_error,
    TEST_USERS,
)


class TestSuccessionRevertCycle:

    def test_blocked_handover_reverts_and_reblocks(self, api):
        """PRD §3.2: "An administrator governs a blocked handover back to pending:
        `HANDOVER_BLOCKED` transitions to `PENDING_HANDOVER`, with `previous_state`
        set to `HANDOVER_BLOCKED`, `blocked_by_moderator_id` cleared to null, and
        `discussion_round_count` reset to 0."
        PRD §3.2: "increment `discussion_round_count` by one".

        Design: Difficulty/non_linear_state_machine/succession_dispute_block_and_revert_cycle
        """
        state = _two_moderator_community()
        community_id = state["community_id"]
        mod_a = state["mod_a"]
        mod_b = state["mod_b"]

        succession_id = open_succession(community_id, actor_moderator_id=mod_a["id"])["id"]
        record_discussion(community_id, succession_id, round_note="Round one by mod-a",
                          actor_moderator_id=mod_a["id"])
        record_discussion(community_id, succession_id, round_note="Round two by mod-b",
                          actor_moderator_id=mod_b["id"])
        blocked = dispute_succession(community_id, succession_id,
                                     dispute_note="mod-a disputes the handover",
                                     actor_moderator_id=mod_a["id"])
        assert blocked["state"] == "HANDOVER_BLOCKED"
        assert blocked["blocked_by_moderator_id"] == mod_a["id"]

        reverted = prevent_succession(community_id, succession_id)
        assert reverted["state"] == "PENDING_HANDOVER"
        assert reverted["blocked_by_moderator_id"] is None
        assert reverted["discussion_round_count"] == 0

        record_discussion(community_id, succession_id, round_note="Round three by mod-b",
                          actor_moderator_id=mod_b["id"])
        blocked_again = dispute_succession(community_id, succession_id,
                                           dispute_note="mod-a disputes again",
                                           actor_moderator_id=mod_a["id"])
        assert blocked_again["state"] == "HANDOVER_BLOCKED"
        assert blocked_again["discussion_round_count"] == 1

    def test_revert_cycle_returns_the_succession_to_discussion(self, api):
        """PRD §3.2: "Records of a discussion round move a succession from
        `PENDING_HANDOVER` to `DISCUSSION`, and a further round recorded while
        already in `DISCUSSION` keeps it there; both paths set `previous_state` to
        the state the row occupied immediately before the round, increment
        `discussion_round_count` by one".
        PRD §3.2: "An administrator governs a blocked handover back to pending:
        `HANDOVER_BLOCKED` transitions to `PENDING_HANDOVER`, with `previous_state`
        set to `HANDOVER_BLOCKED`, `blocked_by_moderator_id` cleared to null, and
        `discussion_round_count` reset to 0."

        Design: Difficulty/non_linear_state_machine/succession_dispute_block_and_revert_cycle

        PRD-ONLY READING: the accumulation of the round count across a remedy and
        a second dispute is PRD-silent, so only the post-remedy round is asserted —
        it is recorded against a count the remedy has just reset to 0.
        """
        state = _two_moderator_community()
        community_id = state["community_id"]
        mod_a = state["mod_a"]
        mod_b = state["mod_b"]

        succession_id = open_succession(community_id, actor_moderator_id=mod_a["id"])["id"]
        record_discussion(community_id, succession_id, round_note="Round one by mod-a",
                          actor_moderator_id=mod_a["id"])
        record_discussion(community_id, succession_id, round_note="Round two by mod-b",
                          actor_moderator_id=mod_b["id"])
        blocked = dispute_succession(community_id, succession_id,
                                     dispute_note="mod-a disputes the handover",
                                     actor_moderator_id=mod_a["id"])
        assert blocked["state"] == "HANDOVER_BLOCKED"

        reverted = prevent_succession(community_id, succession_id)
        assert reverted["state"] == "PENDING_HANDOVER"
        assert reverted["discussion_round_count"] == 0
        assert reverted["blocked_by_moderator_id"] is None

        record_discussion(community_id, succession_id, round_note="Round three by mod-b",
                          actor_moderator_id=mod_b["id"])

        succession = get_succession(community_id, succession_id)
        assert succession["state"] == "DISCUSSION"
        assert succession["discussion_round_count"] == 1
        assert succession["previous_state"] == "PENDING_HANDOVER"
        assert succession["blocked_by_moderator_id"] is None


class TestSegregationOfDutiesPrecedence:

    def test_self_dispute_on_an_unknown_succession_reports_misconduct(self, api):
        """PRD §3.2: "This segregation check is evaluated before the existence
        check for the succession identifier, so a self-dispute aimed at an unknown
        succession still reports the misconduct rather than a not-found response."
        PRD §2.6: "so that an account that authored the most recent discussion
        round and then attempts to open the following dispute against a succession
        identifier that does not resolve still receives
        `ERR_SEGREGATION_OF_DUTIES` rather than a not-found response."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_precedes_existence
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        mod_a = founding_moderator(community_id)

        succession = open_succession(community_id, actor_moderator_id=mod_a["id"])
        record_discussion(community_id, succession["id"],
                          round_note="Opening round authored by mod-a",
                          actor_moderator_id=mod_a["id"])

        unknown_succession = "00000000-0000-4000-8000-000000000001"
        response = api.dispute_succession(
            community_id, unknown_succession,
            {"dispute_note": "Self-dispute against an unknown succession"},
            _moderator_headers(mod_a["id"]),
        )
        error = validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert error["error_id"] != ApiErrorId.ERR_COMMUNITY_NOT_FOUND.value
        assert error["error_id"] != ApiErrorId.ERR_NOT_FOUND.value
        assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE.value

    def test_self_dispute_leaves_the_real_succession_in_discussion(self, api):
        """PRD §3.2: "the account that authored the most recent discussion round of
        this succession may not open the next dispute on the same succession, and a
        violation is refused with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.2: "A `SuccessionAuditor` may open a dispute through the same
        capability a moderator uses."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_precedes_existence
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        mod_a = founding_moderator(community_id)
        succession = open_succession(community_id, actor_moderator_id=mod_a["id"])
        record_discussion(community_id, succession["id"],
                          round_note="Opening round authored by mod-a",
                          actor_moderator_id=mod_a["id"])

        response = api.dispute_succession(
            community_id, succession["id"], {"dispute_note": "mod-a disputes its own round"},
            _moderator_headers(mod_a["id"]),
        )
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        unchanged = get_succession(community_id, succession["id"])
        assert unchanged["state"] == "DISCUSSION"
        assert unchanged["blocked_by_moderator_id"] is None


class TestCrossEntityStateDependency:

    def test_demotion_precondition_tracks_the_derived_team_counts(self, api):
        """PRD §3.2: "`is_top_moderator` ... is true only when the row's
        `moderator_role` is `TOP_MODERATOR`, its `status` is `ACTIVE`, and it
        carries the lowest `top_rank` among all `ACTIVE` top-moderator rows of the
        community."
        PRD §3.2: "On success the row's `moderator_role` becomes
        `REGULAR_MODERATOR`, `is_top_moderator` recomputes to false,
        `active_top_moderator_count` is refreshed".

        Design: Difficulty/cross_entity_state_dependency/moderator_demotion_requires_active_top_moderator
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        mod_a = founding_moderator(community_id)
        mod_b = appoint_moderator(community_id, "mod-b", moderator_role="TOP_MODERATOR",
                                  actor_moderator_id=mod_a["id"])
        resign(community_id, mod_a["id"], actor_moderator_id=mod_a["id"])

        resigned_row = get_moderator(community_id, mod_a["id"])
        assert resigned_row["status"] == "RESIGNED"
        assert resigned_row["is_top_moderator"] is False

        community_after = get_community(community_id)
        assert community_after["active_top_moderator_count"] == 1
        assert community_after["active_moderator_count"] == 1

        target = get_moderator(community_id, mod_b["id"])
        assert target["status"] == "ACTIVE"
        assert target["moderator_role"] == "TOP_MODERATOR"
        assert target["is_top_moderator"] is True


class TestArchivalCascade:

    def test_archival_resigns_the_team_and_completes_the_succession(self, api):
        """PRD §3.8: "every moderator of the community whose `status` is `ACTIVE`
        is moved to `RESIGNED` with `removal_reason_code` `ADMIN_ARCHIVAL`".
        PRD §3.8: "every `TeamSuccession` of the community that is not already
        `COMPLETED` is completed with `completion_reason` `ALL_MODERATORS_INACTIVE`".
        PRD §3.8: "The community's `version` advances by one."

        Design: Corner/state_machines/archival_cascade_resigns_the_team_and_closes_successions
        """
        state = setup_quarantined_community(account_id="u-arch", name="r/Alpha",
                                            with_post=True, with_succession=True)
        community_id = state["community_id"]
        moderator_id = state["moderator_id"]
        succession_id = state["succession"]["id"]

        quarantined = get_community(community_id)
        assert quarantined["state"] == "QUARANTINED"

        archived = archive_community_payload(community_id)
        assert archived["state"] == "ARCHIVED"

        assert moderator_rows(community_id, params={"status": "ACTIVE"}) == []
        archived_row = get_moderator(community_id, moderator_id)
        assert archived_row["status"] == "RESIGNED"
        assert archived_row["removal_reason_code"] == "ADMIN_ARCHIVAL"

        closed = get_succession(community_id, succession_id)
        assert closed["state"] == "COMPLETED"
        assert closed["completion_reason"] == "ALL_MODERATORS_INACTIVE"

    def test_archival_preserves_the_first_departure_instant(self, api):
        """PRD §3.8: "On both paths `restricted_since_utc` is preserved — the field
        always records the instant the community first left `ACTIVE`, never the
        most recent move."
        PRD §3.8: "Once a community is `ARCHIVED`, every mutating operation that
        targets it is refused with `ERR_ARCHIVED_COMMUNITY`."

        Design: Corner/state_machines/archival_cascade_resigns_the_team_and_closes_successions
        """
        state = setup_quarantined_community(account_id="u-arch", name="r/Pinned")
        community_id = state["community_id"]

        quarantined = get_community(community_id)
        assert quarantined["state"] == "QUARANTINED"
        assert quarantined["restricted_since_utc"] is not None
        departure = quarantined["restricted_since_utc"]

        archived = archive_community_payload(community_id)
        assert archived["state"] == "ARCHIVED"
        assert archived["restricted_since_utc"] == departure

        response = api.request_reinstatement(community_id, _moderator_headers(state["moderator_id"]))
        validate_error(response, ApiErrorId.ERR_ARCHIVED_COMMUNITY)


class TestSoftArchivalVisibility:

    def test_archived_community_stays_queryable(self, api):
        """PRD §3.10: "An `Anonymous` reader reaches the community list and a
        single community, which is what makes `ACTIVE` and `PROTEST_RESTRICTED`,
        `RESTRICTED`, `INSTITUTION_NEGOTIATION`, `QUARANTINED` and `ARCHIVED`
        observable to the outside world."
        PRD §3.8: "every `Post` of the community is moved to `status` `LOCKED`".

        Design: Corner/cross_cutting_complexity_layers/soft_archival_keeps_children_queryable
        """
        state = setup_quarantined_community(account_id="u-arch", name="r/Archive",
                                            with_post=True)
        community_id = state["community_id"]
        archived = archive_community_payload(community_id)
        assert archived["state"] == "ARCHIVED"

        listed = api.list_communities(_anonymous_headers(), params={"state": "ARCHIVED"})
        rows = _rows(listed)
        assert len(rows) == 1
        assert rows[0]["id"] == community_id

        unfiltered = _rows(api.list_communities(_anonymous_headers()))
        assert any(row["id"] == community_id for row in unfiltered)

        assert moderator_rows(community_id, params={"status": "ACTIVE"}) == []
        all_rows = moderator_rows(community_id)
        assert len(all_rows) == 1


# --- local helpers -----------------------------------------------------------

def _moderator_headers(moderator_id):
    from test_helpers import make_moderator_headers
    return make_moderator_headers(moderator_id)


def _anonymous_headers():
    return TEST_USERS["anonymous_headers"]


def _rows(response):
    from test_helpers import get_success_data, validate_paginated
    try:
        data, _meta = validate_paginated(response)
        return data
    except Exception:
        data = get_success_data(response)
        return data if isinstance(data, list) else data.get("data", [])


def archive_community_payload(community_id):
    return archive_community({"community_id": community_id}, TEST_USERS["platform_admin_headers"])


def _two_moderator_community():
    set_clock(CLOCK_BASE)
    community = create_community("r/Alpha", description="Alpha community")
    community_id = community["id"]
    mod_a = founding_moderator(community_id)
    mod_b = appoint_moderator(community_id, "mod-b", actor_moderator_id=mod_a["id"])
    return {"community": community, "community_id": community_id, "mod_a": mod_a, "mod_b": mod_b}
