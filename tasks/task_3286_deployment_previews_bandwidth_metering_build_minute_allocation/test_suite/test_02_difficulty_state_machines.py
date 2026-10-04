"""Difficulty-queue tests: non_linear_state_machine."""
from test_helpers import (
    DEVELOPER,
    OWNER,
    build_deployment,
    create_deployment,
    create_domain,
    get_deployment,
    get_domain,
    get_project,
    list_domain_certificates,
    setup_team_with_project,
    setup_team_with_project_and_period,
    validate_error,
    validate_success,
    api_client,
    ApiErrorId,
)


class TestDeploymentPromotionRollbackCycle:
    def test_forward_promotion_displaces_incumbent(self, api):
        """PRD §3.5: "The project's `production_deployment_id` then points at
        the newly promoted deployment, and the prior `PROMOTED` production
        deployment, if one existed, transitions to `ROLLED_BACK`, preserving
        the audit trail."

        Design: Difficulty/non_linear_state_machine/deployment_promotion_rollback_cycle_on_deployment
        """
        plan, team, project, period = setup_team_with_project_and_period()
        d1 = create_deployment(project["id"], branch="main", commit_sha="aaa111")
        build_deployment(d1["id"], "SUCCESS", 60)
        d2 = create_deployment(project["id"], branch="main", commit_sha="bbb222")
        build_deployment(d2["id"], "SUCCESS", 60)

        validate_success(api.promote_deployment(d1["id"], OWNER))
        assert get_project(project["id"])["production_deployment_id"] == d1["id"]

        validate_success(api.promote_deployment(d2["id"], OWNER))
        assert get_deployment(d1["id"])["status"] == "ROLLED_BACK"
        assert get_project(project["id"])["production_deployment_id"] == d2["id"]

    def test_rollback_swaps_pair_and_target_is_sticky(self, api):
        """PRD §3.5: "The effect is atomic: the currently `PROMOTED` deployment
        transitions `PROMOTED` → `ROLLED_BACK` with its
        `previous_promoted_deployment_id` recording the chosen prior, the
        chosen prior deployment transitions back to `PROMOTED` with its
        `previous_promoted_deployment_id` recording the displaced current
        deployment, and the project's `production_deployment_id` is updated to
        the chosen prior."

        Design: Difficulty/non_linear_state_machine/deployment_promotion_rollback_cycle_on_deployment
        """
        plan, team, project, period = setup_team_with_project_and_period()
        d1 = create_deployment(project["id"], branch="main", commit_sha="aaa111")
        build_deployment(d1["id"], "SUCCESS", 60)
        d2 = create_deployment(project["id"], branch="main", commit_sha="bbb222")
        build_deployment(d2["id"], "SUCCESS", 60)

        validate_success(api.promote_deployment(d1["id"], OWNER))
        validate_success(api.promote_deployment(d2["id"], OWNER))
        validate_success(api.rollback_project(project["id"], OWNER))

        d1_after = get_deployment(d1["id"])
        d2_after = get_deployment(d2["id"])
        assert d1_after["status"] == "PROMOTED"
        assert d2_after["status"] == "ROLLED_BACK"
        assert get_project(project["id"])["production_deployment_id"] == d1["id"]
        assert d1_after["target"] == "PRODUCTION"
        assert d2_after["target"] == "PRODUCTION"


class TestDomainVerificationRetryLoop:
    def test_failure_then_reverify_then_success_spawns_certificate(self, api):
        """PRD §3.6: "A `SUCCESS` outcome moves the domain to `VERIFIED` and,
        when the domain has no certificate yet, spawns a new certificate in
        `ISSUING` — issuance proceeds asynchronously and completes via the
        system webhook. A `FAILURE` outcome moves the domain to `FAILED`, from
        which a reverify request resets it to `PENDING` for another attempt
        (again, only from `FAILED`, otherwise `ERR_INVALID_STATE`)."

        Design: Difficulty/non_linear_state_machine/domain_verification_retry_loop_on_domain
        """
        plan, team, project = setup_team_with_project()
        domain = create_domain(project["id"], name="example.com")
        assert domain["verification_status"] == "PENDING"

        validate_success(api.verify_domain(domain["id"], {"outcome": "FAILURE"}, DEVELOPER))
        dom = get_domain(domain["id"])
        assert dom["verification_status"] == "FAILED"
        assert len(list_domain_certificates(domain["id"])) == 0

        validate_success(api.reverify_domain(domain["id"], DEVELOPER))
        assert get_domain(domain["id"])["verification_status"] == "PENDING"

        validate_success(api.verify_domain(domain["id"], {"outcome": "SUCCESS"}, DEVELOPER))
        assert get_domain(domain["id"])["verification_status"] == "VERIFIED"
        certs = list_domain_certificates(domain["id"])
        assert len(certs) == 1
        assert certs[0]["status"] == "ISSUING"

    def test_verify_failure_path_alone(self, api):
        """PRD §3.6: "A `FAILURE` outcome moves the domain to `FAILED`, from
        which a reverify request resets it to `PENDING` for another attempt
        (again, only from `FAILED`, otherwise `ERR_INVALID_STATE`)."

        Design: Difficulty/non_linear_state_machine/domain_verification_retry_loop_on_domain
        """
        plan, team, project = setup_team_with_project()
        domain = create_domain(project["id"], name="example.com")
        validate_success(api.verify_domain(domain["id"], {"outcome": "FAILURE"}, DEVELOPER))
        assert get_domain(domain["id"])["verification_status"] == "FAILED"
        # reverify from FAILED succeeds
        validate_success(api.reverify_domain(domain["id"], DEVELOPER))
        assert get_domain(domain["id"])["verification_status"] == "PENDING"
        # a second reverify from PENDING is an invalid transition
        resp = api.reverify_domain(domain["id"], DEVELOPER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
