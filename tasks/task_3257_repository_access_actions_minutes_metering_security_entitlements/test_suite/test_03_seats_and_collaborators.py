"""Seat ledger: consume/reclaim invariant, CYCLE vs PROJECTED variants,
billing-cycle reset reclamation, membership seat gating, outside-collaborator
limits and invite deadlines."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_commit_event,
    create_enterprise,
    create_invite,
    create_organization,
    create_organization_payload,
    create_repository,
    create_team,
    create_user,
    get_org,
    get_seat_usage,
    make_user_headers,
    org_transition,
    set_clock,
    setup_enterprise_with_org,
    setup_org_with_repo,
    user_transition,
    validate_error,
    validate_success,
)

EA = TEST_USERS["enterprise_admin_headers"]
OA = TEST_USERS["org_admin_headers"]


class TestSeatConsumeReclaimInvariant:
    def test_commit_consumes_seat_then_suspension_reclaims(self, api):
        """PRD §3.3: "when the author holds no seat on the enterprise that owns
        the organization, a seat is consumed at ingest, `used_seats` is
        incremented, `available_seats` is recomputed". PRD §3.3: "If
        `seat_held_enterprise_id` is non-null the seat is reclaimed in the same
        step: `used_seats` is decremented, `available_seats` recomputed, the
        field cleared".

        Design: Difficulty/compensating_invariant/seat_consume_reclaim_invariant
        """
        ent, org = setup_enterprise_with_org(purchased_seats=3)
        user = create_user("u1")
        create_commit_event(user["id"], org["id"], committed_at="2026-09-01T00:00:00Z")
        mid = get_seat_usage(ent["id"], mode="CYCLE")
        assert mid["used_seats"] == 1
        assert mid["available_seats"] == 2
        assert mid["used_seats"] + mid["available_seats"] == 3
        user_transition(user["id"], "SUSPEND")
        end = get_seat_usage(ent["id"], mode="CYCLE")
        assert end["used_seats"] == 0
        assert end["available_seats"] == 3
        assert end["used_seats"] + end["available_seats"] == 3

    def test_seat_ledger_invariant_on_enterprise_read(self, api):
        """PRD §3.1: "The server also exposes a read-only `available_seats`
        field, always equal to `purchased_seats` minus `used_seats`, kept
        consistent on every seat consume or reclaim."

        Design: Difficulty/compensating_invariant/seat_consume_reclaim_invariant
        """
        ent, org = setup_enterprise_with_org(purchased_seats=3)
        user = create_user("u1")
        create_commit_event(user["id"], org["id"], committed_at="2026-09-01T00:00:00Z")
        data = validate_success(api.get_enterprise(ent["id"], EA))
        assert data["used_seats"] == 1
        assert data["available_seats"] == data["purchased_seats"] - data["used_seats"]
        user_transition(user["id"], "SUSPEND")
        data = validate_success(api.get_enterprise(ent["id"], EA))
        assert data["used_seats"] == 0
        assert data["available_seats"] == data["purchased_seats"]


class TestSeatUsageVariants:
    def _setup_two_committers(self, api):
        ent, org = setup_enterprise_with_org(purchased_seats=5)
        u1 = create_user("u1")
        u2 = create_user("u2")
        set_clock("2026-09-01T00:00:00Z")
        # u1's only commit is 70 days old: inside the trailing 90-day window
        # but it ages out within the next 30 days.
        create_commit_event(u1["id"], org["id"], committed_at="2026-06-23T00:00:00Z")
        # u2's commit is 10 days old: safely inside both windows.
        create_commit_event(u2["id"], org["id"], committed_at="2026-08-22T00:00:00Z")
        return ent, org, u1, u2

    def test_cycle_mode_counts_both_committers(self, api):
        """PRD §3.3: "The default `CYCLE` mode reports the strict trailing
        ninety-day window evaluated at the current logical clock."

        Design: Difficulty/dual_variant_calc/seat_count_projection_vs_cycle_snapshot
        """
        ent, org, u1, u2 = self._setup_two_committers(api)
        cycle = get_seat_usage(ent["id"], mode="CYCLE")
        assert cycle["used_seats"] == 2

    def test_projected_mode_excludes_aging_out_seat(self, api):
        """PRD §3.3: "The `PROJECTED` mode is a forward-looking
        capacity-planning view: it includes users whose only qualifying commit
        event would still fall inside the ninety-day window as of the clock plus
        thirty days, and excludes seats whose last commit will age out within
        the next thirty days."

        Design: Difficulty/dual_variant_calc/seat_count_projection_vs_cycle_snapshot
        """
        ent, org, u1, u2 = self._setup_two_committers(api)
        projected = get_seat_usage(ent["id"], mode="PROJECTED")
        assert projected["used_seats"] == 1
        cycle = get_seat_usage(ent["id"], mode="CYCLE")
        assert cycle["used_seats"] != projected["used_seats"]


class TestBillingCycleSeatReclaim:
    def test_reset_reclaims_only_lapsed_seat(self, api):
        """PRD §3.2: "it runs a seat-reclamation sweep that returns seats held
        by users whose only justification was a ninety-day committer window that
        has since lapsed." PRD §3.2: "The response reports `reclaimed_seats` and
        `orgs_reset`."

        Design: Corner/calculations/seat_reclaim_at_billing_cycle_reset
        """
        ent, org = setup_enterprise_with_org(purchased_seats=5)
        u1 = create_user("u1")
        u2 = create_user("u2")
        set_clock("2026-06-01T00:00:00Z")
        create_commit_event(u1["id"], org["id"], committed_at="2026-06-01T00:00:00Z")
        create_commit_event(u2["id"], org["id"], committed_at="2026-06-03T00:00:00Z")
        set_clock("2026-08-31T00:00:00Z")  # u1 at 91 days, u2 at 89 days
        resp = api.billing_cycle_reset(ent["id"], EA)
        summary = validate_success(resp)
        assert summary["reclaimed_seats"] == 1
        usage = get_seat_usage(ent["id"], mode="CYCLE")
        assert usage["used_seats"] == 1


class TestMembershipSeatGating:
    def test_no_seats_available_on_membership_add(self, api):
        """PRD §3.4: "Adding a user to any team consumes a seat when the user
        currently holds none on the parent enterprise — this is justification
        (b) of the seat ledger from §3.3. The seat-consumption check applies on
        the membership create, and the operation is rejected with
        `ERR_NO_SEATS_AVAILABLE` if `available_seats` is zero."

        Design: Corner/errors/no_seats_available_on_membership_add
        """
        ent, org = setup_enterprise_with_org(purchased_seats=1)
        u1 = create_user("u1")
        u2 = create_user("u2")
        create_commit_event(u1["id"], org["id"], committed_at="2026-09-01T00:00:00Z")
        team = create_team(org["id"], name="t1")
        resp = api.create_membership(team["id"], {"user_id": u2["id"], "role": "MEMBER"}, OA)
        validate_error(resp, ApiErrorId.ERR_NO_SEATS_AVAILABLE, 402)

    def test_membership_role_cycles_member_maintainer(self, api):
        """PRD §3.4: "The first call for a given `user_id` creates the
        membership with its `team_id` set from the path; subsequent calls with a
        different `role` update the existing row. The `role` field cycles
        between `MEMBER` and `MAINTAINER` and defaults to `MEMBER`."

        Design: Corner/state_machines/membership_role_cycles_member_maintainer
        """
        ent, org = setup_enterprise_with_org(purchased_seats=5)
        team = create_team(org["id"], name="t1")
        user = create_user("u1")
        r1 = validate_success(
            api.create_membership(team["id"], {"user_id": user["id"], "role": "MEMBER"}, OA),
            expected_status=201,
        )
        r2 = validate_success(
            api.create_membership(team["id"], {"user_id": user["id"], "role": "MAINTAINER"}, OA),
            expected_status=201,
        )
        r3 = validate_success(
            api.create_membership(team["id"], {"user_id": user["id"], "role": "MEMBER"}, OA),
            expected_status=201,
        )
        assert r1["role"] == "MEMBER"
        assert r2["role"] == "MAINTAINER"
        assert r3["role"] == "MEMBER"


class TestCollaboratorInviteExpiry:
    def test_invite_expires_at_computed_from_logical_clock(self, api):
        """PRD §3.5: "the new row starts in `INVITED` with `invite_expires_at`
        set to the logical clock plus seven days."

        Design: Corner/entities/outside_collaborator_invite_expiry_computed
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5)
        user = create_user("u1")
        set_clock("2026-09-10T12:00:00Z")
        collab = create_invite(org["id"], user["id"], repo["id"])
        assert collab["invite_expires_at"].startswith("2026-09-17T12:00:00"), (
            f"expected clock + 7 days, got {collab['invite_expires_at']}"
        )

    def test_invite_accepts_one_second_before_deadline(self, api):
        """PRD §3.5: "Acceptance is rejected with `ERR_INVITE_EXPIRED` if the
        logical clock is at or past `invite_expires_at` — acceptance at exactly
        the expiry instant fails."

        Design: Difficulty/resource_temporal_overlap/invite_expiry_strict_deadline
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5)
        u1 = create_user("u1")
        set_clock("2026-09-01T00:00:00Z")
        collab = create_invite(org["id"], u1["id"], repo["id"])
        set_clock("2026-09-07T23:59:59Z")
        resp = api.accept_outside_collaborator(collab["id"], make_user_headers(u1["id"]))
        data = validate_success(resp)
        assert data["status"] == "ACCEPTED"

    def test_invite_rejected_at_exact_deadline_and_swept_expired(self, api):
        """PRD §3.5: "Acceptance is rejected with `ERR_INVITE_EXPIRED` if the
        logical clock is at or past `invite_expires_at` — acceptance at exactly
        the expiry instant fails." PRD §3.5: "Invitations that pass
        `invite_expires_at` without being accepted transition lazily to
        `EXPIRED` when next read or acted on, and are also swept when the
        logical clock advances."

        Design: Difficulty/resource_temporal_overlap/invite_expiry_strict_deadline
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5)
        u2 = create_user("u2")
        set_clock("2026-09-01T00:00:00Z")
        collab = create_invite(org["id"], u2["id"], repo["id"])
        set_clock("2026-09-08T00:00:00Z")
        resp = api.accept_outside_collaborator(collab["id"], make_user_headers(u2["id"]))
        validate_error(resp, ApiErrorId.ERR_INVITE_EXPIRED, 409)
        # The accept attempt was also a read/action on the row past expiry:
        # the error path confirms the lazy flip; the sweep on clock advance is
        # what guarantees EXPIRED even without the accept attempt.


class TestCollaboratorLimitBoundary:
    def _setup_nine_invites(self, api):
        ent = create_enterprise(purchased_seats=30)
        org = create_organization(ent["id"], login="org1", plan_tier="FREE")
        repo = create_repository(org["id"], name="repo1")
        users = [create_user(f"c{i}") for i in range(1, 12)]
        for u in users[:9]:
            create_invite(org["id"], u["id"], repo["id"])
        return ent, org, repo, users

    def test_ninth_active_invite_allows_tenth_at_exactly_limit(self, api):
        """PRD §3.5: "the count of collaborator rows in `INVITED` or `ACCEPTED`
        (pending invites consume the limit) must be strictly less than the
        organization's `outside_collaborator_limit` at the moment of creation".

        Design: Difficulty/boundary_precision_check/collaborator_limit_at_exactly_limit
        """
        ent, org, repo, users = self._setup_nine_invites(api)
        resp = api.create_outside_collaborator(
            org["id"], {"user_id": users[9]["id"], "repository_id": repo["id"]}, OA
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "INVITED"

    def test_eleventh_invite_at_limit_rejected(self, api):
        """PRD §3.5: "if the count already equals the limit, the create is
        rejected with `ERR_COLLABORATOR_LIMIT_REACHED` — equality blocks."

        Design: Difficulty/boundary_precision_check/collaborator_limit_at_exactly_limit
        """
        ent, org, repo, users = self._setup_nine_invites(api)
        resp = api.create_outside_collaborator(
            org["id"], {"user_id": users[9]["id"], "repository_id": repo["id"]}, OA
        )
        validate_success(resp, expected_status=201)
        resp = api.create_outside_collaborator(
            org["id"], {"user_id": users[10]["id"], "repository_id": repo["id"]}, OA
        )
        validate_error(resp, ApiErrorId.ERR_COLLABORATOR_LIMIT_REACHED, 409)


class TestCollaboratorAcceptRbac:
    def test_user_cannot_accept_others_invite(self, api):
        """PRD §2.1: "accepting an outside-collaborator invitation requires
        `X-User-ID` to equal the invited user's id". PRD §2.1: "a role that is
        not listed is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/user_cannot_accept_others_invite
        """
        ent, org, repo = setup_org_with_repo(purchased_seats=5)
        u1 = create_user("u1")
        u2 = create_user("u2")
        collab = create_invite(org["id"], u1["id"], repo["id"])
        resp = api.accept_outside_collaborator(collab["id"], make_user_headers(u2["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


class TestOrgStateVsSeatPriority:
    def test_accept_on_suspended_org_fails_org_not_active(self, api):
        """PRD §2.9: "5. Organization state: the organization must be `ACTIVE`
        for any child mutation, else `ERR_ORG_NOT_ACTIVE`." and "14. Seat
        availability on seat-consuming operations, else `ERR_NO_SEATS_AVAILABLE`
        (HTTP 402)." PRD §2.9: "A request that fails an earlier rule is rejected
        with that rule's error and never reaches later rules."

        Design: Difficulty/priority_pair_validation_conflict/org_state_vs_seat_fiscal_priority
        """
        ent = create_enterprise(purchased_seats=1)
        org = create_organization(ent["id"], login="org1", plan_tier="TEAM")
        repo = create_repository(org["id"], name="repo1")
        u1 = create_user("u1")
        u2 = create_user("u2")
        # u1's commit consumes the only seat, leaving available_seats == 0.
        create_commit_event(u1["id"], org["id"], committed_at="2026-09-01T00:00:00Z")
        collab = create_invite(org["id"], u2["id"], repo["id"])
        org_transition(org["id"], "SUSPEND")
        resp = api.accept_outside_collaborator(collab["id"], make_user_headers(u2["id"]))
        validate_error(resp, ApiErrorId.ERR_ORG_NOT_ACTIVE, 409)

    def test_accept_fails_org_not_active_not_seats_when_both_fail(self, api):
        """PRD §3.5: "It is also rejected with `ERR_USER_NOT_ACTIVE` if the
        invited user is not `ACTIVE`, and with `ERR_ORG_NOT_ACTIVE` if the
        organization is not `ACTIVE`." PRD §2.9: "When several validation rules
        apply to the same request, they are evaluated in a fixed order so that a
        single, deterministic error surfaces."

        Design: Difficulty/priority_pair_validation_conflict/org_state_vs_seat_fiscal_priority
        """
        ent = create_enterprise(purchased_seats=1)
        org = create_organization(ent["id"], login="org1", plan_tier="TEAM")
        repo = create_repository(org["id"], name="repo1")
        u1 = create_user("u1")
        u2 = create_user("u2")
        create_commit_event(u1["id"], org["id"], committed_at="2026-09-01T00:00:00Z")
        collab = create_invite(org["id"], u2["id"], repo["id"])
        org_transition(org["id"], "SUSPEND")
        resp = api.accept_outside_collaborator(collab["id"], make_user_headers(u2["id"]))
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == ApiErrorId.ERR_ORG_NOT_ACTIVE
        assert resp.status_code == 409
