"""Teams, placement, and backfill: staffing floor, cross-entity agreement
gates, half-open member intervals, per-date team capacity, the backfill
deadline and budget, and team-version OCC."""

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    PROGRAM_MANAGER_HEADERS,
    SITE_DIRECTOR_HEADERS,
    make_school_liaison_headers,
)


class TestDeployGate:
    def test_deploy_below_minimum_rejected(self, api):
        """PRD §3.4: "Deployment is the `SiteDirector`'s gate from `FORMING`
        to `DEPLOYED`: the roster must already meet the floor,
        `active_assignment_count` at least `min_active_members`, else
        `ERR_TEAM_STAFFING_BELOW_MINIMUM`, and the school agreement must be
        `ACTIVE`, else `ERR_AGREEMENT_NOT_ACTIVE`."

        Design: Corner/validations/deploy_below_minimum_rejected
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        school = fixtures.create_active_school(api, site["id"])
        team = fixtures.create_team(api, school["id"])
        # team_size 3 freezes min_active_members at 1; zero assignments is below it.
        assert team["min_active_members"] == 1

        blocked = api.transition_team(team["id"], {"to_status": "DEPLOYED"}, SITE_DIRECTOR_HEADERS)
        validate_error(blocked, ApiErrorId.ERR_TEAM_STAFFING_BELOW_MINIMUM.value)

        after = fixtures.get_team(api, team["id"])
        assert after["status"] == "FORMING"

    def test_team_deploy_blocked_when_agreement_in_amendment_review(self, api):
        """PRD §3.4: "Deployment is the `SiteDirector`'s gate from `FORMING`
        to `DEPLOYED`: the roster must already meet the floor,
        `active_assignment_count` at least `min_active_members`, else
        `ERR_TEAM_STAFFING_BELOW_MINIMUM`, and the school agreement must be
        `ACTIVE`, else `ERR_AGREEMENT_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/team_deploy_blocked_when_agreement_in_amendment_review
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        school = fixtures.create_active_school(api, site["id"])
        team = fixtures.create_team(api, school["id"])
        member = fixtures.create_active_member(api, site["id"])
        fixtures.assign_member(api, team["id"], member["id"])

        amended = validate_success(
            api.amend_school(
                school["id"],
                {"expected_school_version": school["version"], "annual_cost_share_cents": 450_000},
                SITE_DIRECTOR_HEADERS,
            )
        )
        assert amended["agreement_status"] == "AMENDMENT_REVIEW"

        # Staffing was sufficient; only the cross-entity gate can explain this.
        blocked = api.transition_team(team["id"], {"to_status": "DEPLOYED"}, SITE_DIRECTOR_HEADERS)
        validate_error(blocked, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)

        # The liaison closes the amendment loop; the same transition succeeds.
        get_success_data(
            api.transition_school(
                school["id"], {"to_status": "ACTIVE", "dimension": "AGREEMENT"},
                make_school_liaison_headers(school["id"]),
            )
        )
        deployed = validate_success(api.transition_team(team["id"], {"to_status": "DEPLOYED"}, SITE_DIRECTOR_HEADERS))
        assert deployed["status"] == "DEPLOYED"

    def test_suspended_agreement_blocks_team_creation_and_deployment(self, api):
        """PRD §3.2: "While an agreement is `SUSPENDED`, team creation and
        deployment at that school and evaluation report submission are blocked
        until the agreement is resumed."

        Design: Difficulty/cross_entity_state_dependency/team_deploy_blocked_when_agreement_in_amendment_review
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        school = fixtures.create_active_school(api, site["id"])
        team = fixtures.create_team(api, school["id"])
        member = fixtures.create_active_member(api, site["id"])
        fixtures.assign_member(api, team["id"], member["id"])

        suspended = validate_success(
            api.transition_school(
                school["id"], {"to_status": "SUSPENDED", "dimension": "AGREEMENT"}, SITE_DIRECTOR_HEADERS
            )
        )
        assert suspended["agreement_status"] == "SUSPENDED"

        create_blocked = api.create_team(
            factories.team_payload(school["id"], name="Team Late"), SITE_DIRECTOR_HEADERS
        )
        validate_error(create_blocked, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)

        deploy_blocked = api.transition_team(team["id"], {"to_status": "DEPLOYED"}, SITE_DIRECTOR_HEADERS)
        validate_error(deploy_blocked, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)

        get_success_data(
            api.transition_school(
                school["id"], {"to_status": "ACTIVE", "dimension": "AGREEMENT"}, SITE_DIRECTOR_HEADERS
            )
        )
        deployed = validate_success(api.transition_team(team["id"], {"to_status": "DEPLOYED"}, SITE_DIRECTOR_HEADERS))
        assert deployed["status"] == "DEPLOYED"


class TestMemberIntervals:
    def test_open_ended_assignment_overlaps_later_start_then_adjacency_allowed(self, api):
        """PRD §3.4: "The member's own assignment intervals must be pairwise
        non-overlapping: an existing assignment whose `end_date` equals the
        new `start_date` does not overlap (the intervals are half-open), while
        an open-ended existing assignment overlaps any later start —
        violations are `ERR_ASSIGNMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/member_assignment_half_open_intervals
        """
        fixtures.set_clock(api)
        world = fixtures.setup_deployed_world(api)
        member = world["member"]
        team_beta = fixtures.create_team(api, world["school"]["id"], name="Team Beta")

        # [2026-09-01, open) swallows the 2026-10-01 start.
        overlap = api.create_assignment(
            team_beta["id"],
            factories.assignment_payload(member["id"], team_beta["version"], start_date="2026-10-01"),
            PROGRAM_MANAGER_HEADERS,
        )
        validate_error(overlap, ApiErrorId.ERR_ASSIGNMENT_OVERLAP.value)

        # End at 2026-12-15; a new interval starting exactly there is adjacent,
        # not overlapping. Team Beta's version is unchanged by the rejection,
        # so the originally captured version still matches.
        fixtures.end_assignment(api, world["assignment"]["id"], end_date="2026-12-15")
        adjacent = api.create_assignment(
            team_beta["id"],
            factories.assignment_payload(member["id"], team_beta["version"], start_date="2026-12-15"),
            PROGRAM_MANAGER_HEADERS,
        )
        created = validate_success(adjacent, 201)
        assert created["status"] == "ACTIVE"
        assert created["start_date"] == "2026-12-15"

    def test_end_defaults_to_clock_date_and_same_day_adjacency(self, api):
        """PRD §3.4: "A `ProgramManager` ends an `ACTIVE` assignment,
        optionally supplying an `end_date`; when omitted, the logical clock
        date is used, and a supplied date earlier than the assignment's
        `start_date` is rejected as `ERR_INVALID_REQUEST`."

        Design: Difficulty/resource_temporal_overlap/member_assignment_half_open_intervals
        """
        fixtures.set_clock(api)
        world = fixtures.setup_deployed_world(api)
        member = world["member"]

        ended = fixtures.end_assignment(api, world["assignment"]["id"])
        assert ended["status"] == "ENDED"
        assert ended["end_date"] == "2026-09-01"

        # [2026-09-01, 2026-09-01) covers nothing; a fresh start on the same
        # date is adjacent and allowed.
        team_beta = fixtures.create_team(api, world["school"]["id"], name="Team Beta")
        created = fixtures.assign_member(api, team_beta["id"], member["id"], start_date="2026-09-01")
        assert created["status"] == "ACTIVE"


class TestTeamCapacity:
    def _four_members(self, api, site_id):
        members = [fixtures.create_active_member(api, site_id, "app-jordan", full_name="Jordan Rivers")]
        members.append(fixtures.add_active_member(
            api, site_id, "app-riley", "Riley Brooks",
            date_of_birth="2004-02-11", education_level="SOME_COLLEGE",
        ))
        members.append(fixtures.add_active_member(
            api, site_id, "app-casey", "Casey Lane",
            date_of_birth="2002-11-30", education_level="GED",
            citizenship_status="PERMANENT_RESIDENT", prior_service_terms=1,
        ))
        members.append(fixtures.add_active_member(
            api, site_id, "app-devon", "Devon Kim",
            date_of_birth="2005-07-04", education_level="HS_DIPLOMA",
            citizenship_status="US_NATIONAL", prior_full_awards_received=1,
        ))
        return members

    def test_team_aggregate_capacity_ceiling(self, api):
        """PRD §3.4: "Team capacity is enforced per calendar date: for every
        date the new assignment would cover, the count of the team's
        assignments covering that date must stay at or below
        `team_size_snapshot`, else `ERR_TEAM_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/team_aggregate_capacity_ceiling
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        school = fixtures.create_active_school(api, site["id"])
        team = fixtures.create_team(api, school["id"])
        members = self._four_members(api, site["id"])
        for member in members[:3]:
            fixtures.assign_member(api, team["id"], member["id"], start_date="2026-09-01")

        pre = fixtures.get_team(api, team["id"])
        assert pre["active_assignment_count"] == 3

        # 3 same-date assignments + 1 more > team_size_snapshot 3, even though
        # member 4 holds no assignments of their own.
        overflow = api.create_assignment(
            team["id"],
            factories.assignment_payload(members[3]["id"], pre["version"], start_date="2026-09-01"),
            PROGRAM_MANAGER_HEADERS,
        )
        validate_error(overflow, ApiErrorId.ERR_TEAM_CAPACITY_EXCEEDED.value)

    def test_team_capacity_is_per_date(self, api):
        """PRD §3.4: "Team capacity is enforced per calendar date: for every
        date the new assignment would cover, the count of the team's
        assignments covering that date must stay at or below
        `team_size_snapshot`, else `ERR_TEAM_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/team_aggregate_capacity_ceiling
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        school = fixtures.create_active_school(api, site["id"])
        team = fixtures.create_team(api, school["id"])
        members = self._four_members(api, site["id"])
        assignments = [
            fixtures.assign_member(api, team["id"], m["id"], start_date="2026-09-01") for m in members[:3]
        ]

        # Member 1's interval ends at 2026-10-01, so dates from 2026-10-01 on
        # are covered by only two assignments; a third fits.
        fixtures.end_assignment(api, assignments[0]["id"], end_date="2026-10-01")
        created = fixtures.assign_member(api, team["id"], members[3]["id"], start_date="2026-10-01")
        assert created["status"] == "ACTIVE"
        assert created["start_date"] == "2026-10-01"


class TestBackfill:
    def test_team_understaffed_backfill_recovers_deployed(self, api):
        """PRD §3.4: "a `DEPLOYED` team whose roster falls below
        `min_active_members` automatically slides to `UNDERSTAFFED`."
        PRD §3.4: "when the team was `UNDERSTAFFED` and the addition restores
        the roster to at least `min_active_members` — automatically returns
        the team to `DEPLOYED`."

        Design: Corner/state_machines/team_understaffed_backfill_recovers_deployed
        """
        fixtures.set_clock(api)
        world = fixtures.setup_deployed_world(api)
        team_id = world["team"]["id"]
        member2 = fixtures.add_active_member(
            api, world["site"]["id"], "app-riley", "Riley Brooks",
            date_of_birth="2004-02-11", education_level="SOME_COLLEGE",
        )

        ended = fixtures.end_assignment(api, world["assignment"]["id"])
        assert ended["end_date"] == "2026-09-01"

        mid = fixtures.get_team(api, team_id)
        assert mid["status"] == "UNDERSTAFFED"

        backfill = fixtures.assign_member(api, team_id, member2["id"], start_date="2026-09-02")
        assert backfill["is_backfill"] is True

        after = fixtures.get_team(api, team_id)
        assert after["status"] == "DEPLOYED"
        assert after["backfill_count"] == 1
        assert after["active_assignment_count"] == 1

    def test_backfill_deadline_boundary(self, api):
        """PRD §3.4: "Then, for a backfill creation, the backfill window: the
        logical clock date must be on or before the team's
        `backfill_deadline`, else `ERR_BACKFILL_WINDOW_CLOSED`."

        Design: Corner/validations/backfill_deadline_boundary
        """
        fixtures.set_clock(api)
        world = fixtures.setup_deployed_world(api)
        team_id = world["team"]["id"]
        site_id = world["site"]["id"]
        fixtures.end_assignment(api, world["assignment"]["id"])
        member2 = fixtures.add_active_member(
            api, site_id, "app-riley", "Riley Brooks",
            date_of_birth="2004-02-11", education_level="SOME_COLLEGE",
        )

        # Deadline day itself is inside the window (inclusive).
        fixtures.set_clock(api, "2027-01-15T00:00:00Z")
        backfill = fixtures.assign_member(api, team_id, member2["id"], start_date="2027-01-15")
        assert backfill["is_backfill"] is True
        fixtures.end_assignment(api, backfill["id"])

        fixtures.set_clock(api, "2027-01-16T00:00:00Z")
        member3 = fixtures.add_active_member(
            api, site_id, "app-casey", "Casey Lane",
            date_of_birth="2002-11-30", education_level="GED",
            citizenship_status="PERMANENT_RESIDENT", prior_service_terms=1,
        )
        pre = fixtures.get_team(api, team_id)
        assert pre["backfill_count"] == 1  # budget still available: 1 < 2

        blocked = api.create_assignment(
            team_id,
            factories.assignment_payload(member3["id"], pre["version"], start_date="2027-01-16"),
            PROGRAM_MANAGER_HEADERS,
        )
        validate_error(blocked, ApiErrorId.ERR_BACKFILL_WINDOW_CLOSED.value)

    def test_backfill_limit_reached_at_budget_boundary(self, api):
        """PRD §3.4: "Finally the backfill budget: any assignment created while
        the team is `DEPLOYED` or `UNDERSTAFFED` is a backfill (`is_backfill`
        is set true), and it is allowed only while the team's `backfill_count`
        is still below its `backfill_limit` — a team that has exhausted its
        budget rejects the placement with `ERR_BACKFILL_LIMIT_REACHED`."

        Design: Corner/errors/backfill_limit_reached_at_budget_boundary"""
        fixtures.set_clock(api)  # stays 2026-09-01: the deadline window is open
        world = fixtures.setup_deployed_world(api)
        team_id = world["team"]["id"]
        site_id = world["site"]["id"]

        fixtures.end_assignment(api, world["assignment"]["id"])
        member2 = fixtures.add_active_member(
            api, site_id, "app-riley", "Riley Brooks",
            date_of_birth="2004-02-11", education_level="SOME_COLLEGE",
        )
        backfill2 = fixtures.assign_member(api, team_id, member2["id"], start_date="2026-09-01")
        fixtures.end_assignment(api, backfill2["id"])

        member3 = fixtures.add_active_member(
            api, site_id, "app-casey", "Casey Lane",
            date_of_birth="2002-11-30", education_level="GED",
            citizenship_status="PERMANENT_RESIDENT", prior_service_terms=1,
        )
        backfill3 = fixtures.assign_member(api, team_id, member3["id"], start_date="2026-09-01")
        assert backfill3["is_backfill"] is True
        fixtures.end_assignment(api, backfill3["id"])

        member4 = fixtures.add_active_member(
            api, site_id, "app-devon", "Devon Kim",
            date_of_birth="2005-07-04", education_level="HS_DIPLOMA",
            citizenship_status="US_NATIONAL", prior_full_awards_received=1,
        )
        pre = fixtures.get_team(api, team_id)
        assert pre["backfill_count"] == 2
        assert pre["status"] == "UNDERSTAFFED"

        # Count 2 is not < limit 2; the deadline months away cannot explain it.
        blocked = api.create_assignment(
            team_id,
            factories.assignment_payload(member4["id"], pre["version"], start_date="2026-09-01"),
            PROGRAM_MANAGER_HEADERS,
        )
        validate_error(blocked, ApiErrorId.ERR_BACKFILL_LIMIT_REACHED.value)


class TestTeamAssignmentOcc:
    def test_occ_team_assignment_stale_version_rejected(self, api):
        """PRD §2.7: "Creating a team assignment requires
        `expected_team_version` matching the team's current `version`. A
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because
        roster capacity and backfill accounting must be evaluated against the
        current roster, not a superseded one."

        Design: Corner/cross_cutting_layers/occ_team_assignment_stale_version_rejected
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        school = fixtures.create_active_school(api, site["id"])
        team = fixtures.create_team(api, school["id"])
        member = fixtures.create_active_member(api, site["id"])

        assert team["version"] == 1
        stale = api.create_assignment(
            team["id"],
            factories.assignment_payload(member["id"], team["version"] - 1, start_date="2026-09-01"),
            PROGRAM_MANAGER_HEADERS,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)

        after = fixtures.get_team(api, team["id"])
        assert after["active_assignment_count"] == 0
        assert after["version"] == team["version"], "a rejected creation must mutate nothing"
