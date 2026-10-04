"""Difficulty-queue tests: transitive_cascade and priority_pair_validation_conflict."""
from test_helpers import (
    ADMIN,
    BILLING,
    DEVELOPER,
    OWNER,
    WEBHOOK,
    ApiErrorId,
    build_deployment,
    create_deployment,
    create_domain,
    create_env_var_payload,
    create_spend_cap,
    get_certificate,
    get_deployment,
    get_domain,
    get_project,
    get_spend_cap,
    setup_domain_with_active_certificate,
    setup_team_with_project,
    setup_team_with_project_and_period,
    validate_error,
    validate_success,
    api_client,
    create_plan,
    create_team,
)


class TestProjectArchiveCascade:
    def test_archive_cancels_queued_suspends_domain_revokes_certificate(self, api):
        """PRD §3.9: "The archive cascade runs three levels deep: the project's
        `status` becomes `ARCHIVED`; every `QUEUED` deployment of the project
        is canceled; every `ACTIVE` domain of the project is suspended; and
        every `ACTIVE` certificate of those domains is revoked."

        Design: Difficulty/transitive_cascade/project_archive_four_hop_cascade
        """
        plan, team, project, period = setup_team_with_project_and_period()
        dep = create_deployment(project["id"])
        assert dep["status"] == "QUEUED"
        domain, cert = setup_domain_with_active_certificate(project["id"], name="example.com")

        validate_success(api.archive_project(project["id"], OWNER))

        assert get_project(project["id"])["status"] == "ARCHIVED"
        assert get_deployment(dep["id"])["status"] == "CANCELED"
        dom_after = get_domain(domain["id"])
        assert dom_after["status"] == "SUSPENDED"
        assert get_certificate(cert["id"])["status"] == "REVOKED"

    def test_archive_clears_domain_certificate_pointer(self, api):
        """PRD §3.6: "a `TeamOwner` revokes an `ACTIVE` certificate (otherwise
        `ERR_INVALID_STATE`), moving it to `REVOKED`, clearing the domain's
        `certificate_id`, and suspending the domain."

        Design: Difficulty/transitive_cascade/project_archive_four_hop_cascade
        """
        plan, team, project, period = setup_team_with_project_and_period()
        domain, cert = setup_domain_with_active_certificate(project["id"], name="example.com")
        assert get_domain(domain["id"])["certificate_id"] == cert["id"]

        validate_success(api.archive_project(project["id"], OWNER))
        dom_after = get_domain(domain["id"])
        assert dom_after["status"] == "SUSPENDED"
        assert dom_after["certificate_id"] is None


class TestBuildCompleteSpendCapProjectSuspension:
    def _setup_capped_team(self, api):
        plan, team, project, period = setup_team_with_project_and_period(
            included_build_minutes=2, overage_build_minute_rate_cents=100,
        )
        cap = create_spend_cap(team["id"], cap_cents=300, action="BLOCK_DEPLOYS_AND_SUSPEND")
        dep = create_deployment(project["id"])
        validate_success(api.build_start(dep["id"], WEBHOOK))
        return plan, team, project, period, cap, dep

    def test_build_complete_trips_cap_and_suspends_project(self, api):
        """PRD §3.7: "If the tripped cap's action is
        `BLOCK_DEPLOYS_AND_SUSPEND`, the team's project cascades to `SUSPENDED`
        with `suspended_reason` set to `SPEND_CAP_BREACHED`, which blocks
        subsequent deploys, promotions, and rollbacks with
        `ERR_PROJECT_SUSPENDED`."

        Design: Difficulty/transitive_cascade/build_complete_to_spendcap_to_project_suspension
        """
        plan, team, project, period, cap, dep = self._setup_capped_team(api)
        done = validate_success(api.build_complete(
            dep["id"], {"outcome": "SUCCESS", "build_duration_seconds": 300}, WEBHOOK,
        ))
        assert done["status"] == "READY"
        assert done["billable_minutes"] == 5

        assert get_spend_cap(cap["id"])["status"] == "TRIPPED"
        proj = get_project(project["id"])
        assert proj["status"] == "SUSPENDED"
        assert proj["suspended_reason"] == "SPEND_CAP_BREACHED"

    def test_cap_trip_is_inclusive_at_exact_equality(self, api):
        """PRD §3.7: "Whenever the open period's `projected_bill_cents` is
        recomputed, an `ACTIVE` cap compares it against `cap_cents`; meeting
        or exceeding the cap — an inclusive comparison — trips it: the cap
        transitions `ACTIVE` → `TRIPPED` and stamps `tripped_at`."

        Design: Difficulty/transitive_cascade/build_complete_to_spendcap_to_project_suspension
        """
        plan, team, project, period, cap, dep = self._setup_capped_team(api)
        validate_success(api.build_complete(
            dep["id"], {"outcome": "SUCCESS", "build_duration_seconds": 300}, WEBHOOK,
        ))
        # billable 5, overage 3 min x 100c = 300 == cap 300 -> trips (inclusive)
        cap_after = get_spend_cap(cap["id"])
        assert cap_after["status"] == "TRIPPED"
        assert cap_after["tripped_at"] is not None


class TestValidationPriorityPairs:
    def test_archived_project_error_beats_env_scope_overlap(self, api):
        """PRD §3.9: "Once archived, the project refuses all child mutations —
        deployments, environment variables, domains, redirects — with
        `ERR_PROJECT_ARCHIVED` (HTTP 409), and archival itself is
        irreversible."
        PRD §2.8: "5. Lifecycle guards on parents — the project must not be
        `ARCHIVED` for child mutations (`ERR_PROJECT_ARCHIVED`)"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_referential_env_scope_on_archived_project
        """
        plan, team, project = setup_team_with_project()
        validate_success(api.create_env_var(
            project["id"],
            create_env_var_payload(key="DATABASE_URL", value="postgres://x", scopes=["PRODUCTION"]),
            DEVELOPER,
        ), expected_status=201)
        validate_success(api.archive_project(project["id"], OWNER))
        # duplicate scope on an archived project: state guard wins
        resp = api.create_env_var(
            project["id"],
            create_env_var_payload(key="DATABASE_URL", value="postgres://y", scopes=["PRODUCTION"]),
            DEVELOPER,
        )
        validate_error(resp, ApiErrorId.ERR_PROJECT_ARCHIVED)

    def test_archived_project_env_var_create_non_overlapping_also_rejected(self, api):
        """PRD §3.9: "Once archived, the project refuses all child mutations —
        deployments, environment variables, domains, redirects — with
        `ERR_PROJECT_ARCHIVED` (HTTP 409), and archival itself is
        irreversible."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_referential_env_scope_on_archived_project
        """
        plan, team, project = setup_team_with_project()
        validate_success(api.archive_project(project["id"], OWNER))
        # even a non-overlapping key is refused once the project is archived
        resp = api.create_env_var(
            project["id"],
            create_env_var_payload(key="NEW_KEY", value="v", scopes=["DEVELOPMENT"]),
            DEVELOPER,
        )
        validate_error(resp, ApiErrorId.ERR_PROJECT_ARCHIVED)

    def test_duplicate_member_error_beats_seat_limit(self, api):
        """PRD §2.8: "6. Referential and uniqueness rules
        (`ERR_ENV_SCOPE_OVERLAP`, `ERR_DOMAIN_ALREADY_ASSIGNED`,
        `ERR_SPEND_CAP_EXISTS`, `ERR_MEMBER_ALREADY_EXISTS`,
        `ERR_REDIRECT_PRIORITY_CONFLICT`)."
        PRD §2.8: "9. Seat capacity (`ERR_SEAT_LIMIT_EXCEEDED`)."
        PRD §3.2: "The member's email must be unique within the team — adding
        an address that already belongs to the team is rejected with
        `ERR_MEMBER_ALREADY_EXISTS` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/business_fiscal_seat_limit_vs_business_referential_duplicate_member
        """
        create_plan(**{
            "tier": "HOBBY", "seat_limit": 1, "included_build_minutes": 100,
            "build_concurrency_limit": 1, "included_bandwidth_gb": 10,
            "included_invocations_millions": 1,
            "bandwidth_tier1_rate_cents_per_gb": 20,
            "bandwidth_tier2_rate_cents_per_gb": 10,
            "bandwidth_tier2_threshold_gb": 100,
            "invocation_rate_cents_per_million": 100,
            "seat_price_cents_monthly": 0, "overage_build_minute_rate_cents": 10,
        })
        team = create_team(plan_tier="HOBBY", name="Tiny")
        validate_success(api.add_member(
            team["id"], {"user_email": "dev@acme.com", "role": "DEVELOPER"}, OWNER,
        ), expected_status=201)
        # team now at seat limit AND the email is a duplicate: referential (6)
        # precedes fiscal (9)
        resp = api.add_member(
            team["id"], {"user_email": "dev@acme.com", "role": "VIEWER"}, OWNER,
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_ALREADY_EXISTS)

    def test_seat_limit_alone_fires_when_email_is_fresh(self, api):
        """PRD §3.2: "Capacity is enforced before insertion: if the team's
        `seats_used` already equals its `seat_limit`, the add is rejected with
        `ERR_SEAT_LIMIT_EXCEEDED` (HTTP 422); the boundary is inclusive, so a
        team exactly at its limit cannot add even one more seat."

        Design: Difficulty/priority_pair_validation_conflict/business_fiscal_seat_limit_vs_business_referential_duplicate_member
        """
        create_plan(**{
            "tier": "HOBBY", "seat_limit": 1, "included_build_minutes": 100,
            "build_concurrency_limit": 1, "included_bandwidth_gb": 10,
            "included_invocations_millions": 1,
            "bandwidth_tier1_rate_cents_per_gb": 20,
            "bandwidth_tier2_rate_cents_per_gb": 10,
            "bandwidth_tier2_threshold_gb": 100,
            "invocation_rate_cents_per_million": 100,
            "seat_price_cents_monthly": 0, "overage_build_minute_rate_cents": 10,
        })
        team = create_team(plan_tier="HOBBY", name="Tiny")
        validate_success(api.add_member(
            team["id"], {"user_email": "dev@acme.com", "role": "DEVELOPER"}, OWNER,
        ), expected_status=201)
        # fresh email, but the team is exactly at its seat limit
        resp = api.add_member(
            team["id"], {"user_email": "other@acme.com", "role": "VIEWER"}, OWNER,
        )
        validate_error(resp, ApiErrorId.ERR_SEAT_LIMIT_EXCEEDED)
