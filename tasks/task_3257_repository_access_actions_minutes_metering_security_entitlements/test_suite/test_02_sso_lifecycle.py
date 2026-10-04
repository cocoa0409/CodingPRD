"""SSO lifecycle: cyclic state machine, cross-entity gating, depth-3 cascade,
re-enforcement non-destructiveness."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_and_install_app,
    create_enterprise,
    create_organization,
    create_organization_payload,
    create_pat,
    create_repository_payload,
    create_user,
    get_seat_usage,
    list_audit_events,
    make_user_headers,
    org_transition,
    setup_enterprise_with_org,
    setup_org_with_repo,
    sso_transition,
    api_client,
    validate_error,
    validate_success,
)

EA = TEST_USERS["enterprise_admin_headers"]
OA = TEST_USERS["org_admin_headers"]


def _pat_status(api, user_id, token_id):
    resp = api.list_personal_access_tokens(user_id, EA)
    data = validate_success(resp)
    for tok in data:
        if tok["id"] == token_id:
            return tok["status"]
    raise AssertionError(f"token {token_id} not listed for user {user_id}")


def _org_status(api, org_id):
    return validate_success(api.get_organization(org_id, EA))["status"]


class TestSsoStateMachine:
    def test_sso_configure_from_configuring_rejected(self, api):
        """PRD §3.1: "From `DISABLED`, an `EnterpriseAdmin` issues a `CONFIGURE`
        action to move into `CONFIGURING`; if the enterprise is not currently
        `DISABLED` the request is rejected with `ERR_SSO_ALREADY_CONFIGURED`."

        Design: Corner/state_machines/sso_configure_from_configuring_rejected
        """
        ent = create_enterprise(purchased_seats=5)
        sso_transition(ent["id"], "CONFIGURE")
        resp = api.sso_transition(ent["id"], "CONFIGURE", EA)
        validate_error(resp, ApiErrorId.ERR_SSO_ALREADY_CONFIGURED)

    def test_sso_reconfigure_preserves_configuring_state(self, api):
        """PRD §3.1: "if the enterprise is not currently `DISABLED` the request
        is rejected with `ERR_SSO_ALREADY_CONFIGURED`."

        Design: Corner/state_machines/sso_configure_from_configuring_rejected
        """
        ent = create_enterprise(purchased_seats=5)
        sso_transition(ent["id"], "CONFIGURE")
        resp = api.sso_transition(ent["id"], "CONFIGURE", EA)
        validate_error(resp, ApiErrorId.ERR_SSO_ALREADY_CONFIGURED)
        data = validate_success(api.get_enterprise(ent["id"], EA))
        assert data["sso_enforcement"] == "CONFIGURING"

    def test_sso_enforcement_requires_all_orgs_active(self, api):
        """PRD §3.1: "this transition requires that the enterprise currently be
        `CONFIGURING` (otherwise `ERR_SSO_NOT_CONFIGURING`) and that **every**
        organization of the enterprise currently be `ACTIVE` (otherwise
        `ERR_ORG_SUSPENDED_BLOCKS_SSO`)."

        Design: Difficulty/cross_entity_state_dependency/sso_enforcement_requires_all_orgs_active
        """
        ent = create_enterprise(purchased_seats=9)
        org1 = create_organization(ent["id"], login="org1", plan_tier="TEAM")
        org2 = create_organization(ent["id"], login="org2", plan_tier="TEAM")
        org_transition(org2["id"], "SUSPEND")
        sso_transition(ent["id"], "CONFIGURE")
        resp = api.sso_transition(ent["id"], "ENFORCE", EA)
        validate_error(resp, ApiErrorId.ERR_ORG_SUSPENDED_BLOCKS_SSO)
        data = validate_success(api.get_enterprise(ent["id"], EA))
        assert data["sso_enforcement"] == "CONFIGURING"

    def test_sso_enforce_succeeds_when_all_orgs_active(self, api):
        """PRD §3.1: "From `CONFIGURING`, an `ENFORCE` action moves the
        enterprise to `ENFORCED`; this transition requires that the enterprise
        currently be `CONFIGURING` (otherwise `ERR_SSO_NOT_CONFIGURING`) and
        that **every** organization of the enterprise currently be `ACTIVE`
        (otherwise `ERR_ORG_SUSPENDED_BLOCKS_SSO`)."

        Design: Difficulty/cross_entity_state_dependency/sso_enforcement_requires_all_orgs_active
        """
        ent, org1 = setup_enterprise_with_org(purchased_seats=9)
        create_organization(ent["id"], login="org2", plan_tier="TEAM")
        sso_transition(ent["id"], "CONFIGURE")
        data = sso_transition(ent["id"], "ENFORCE")
        assert data["sso_enforcement"] == "ENFORCED"

    def test_sso_cyclic_reenforcement_returns_to_enforced(self, api):
        """PRD §3.1: "From `ENFORCED`, a `SUSPEND` action moves to `SUSPENDED`
        (rejected with `ERR_SSO_NOT_ENFORCED` from any other state). From
        `SUSPENDED`, an `ENFORCE` action returns to `ENFORCED`, again requiring
        every organization to be `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/enterprise_sso_cyclic_reenforcement
        """
        ent = create_enterprise(purchased_seats=5, pat_policy="UNRESTRICTED")
        create_organization(ent["id"], login="org1", plan_tier="TEAM")
        user = create_user("u1")
        sso1 = sso_transition(ent["id"], "CONFIGURE")["sso_enforcement"]
        sso1 = sso_transition(ent["id"], "ENFORCE")["sso_enforcement"]
        token = create_pat(user, ent["id"], scopes=["REPO"])
        sso2 = sso_transition(ent["id"], "SUSPEND")["sso_enforcement"]
        sso3 = sso_transition(ent["id"], "ENFORCE")["sso_enforcement"]
        assert sso1 == "ENFORCED"
        assert sso2 == "SUSPENDED"
        assert sso3 == "ENFORCED"

    def test_sso_reenforcement_is_non_destructive(self, api):
        """PRD §3.1: "The later `SUSPENDED` → `ENFORCED` re-enforcement is
        non-destructive: it emits only an `sso.reenforced` event and runs **no**
        token revocation cascade."

        Design: Difficulty/non_linear_state_machine/enterprise_sso_cyclic_reenforcement
        """
        ent = create_enterprise(purchased_seats=5, pat_policy="UNRESTRICTED")
        create_organization(ent["id"], login="org1", plan_tier="TEAM")
        user = create_user("u1")
        sso_transition(ent["id"], "CONFIGURE")
        sso_transition(ent["id"], "ENFORCE")
        token = create_pat(user, ent["id"], scopes=["REPO"])
        assert token["status"] == "ACTIVE"
        sso_transition(ent["id"], "SUSPEND")
        sso_transition(ent["id"], "ENFORCE")
        assert _pat_status(api, user["id"], token["id"]) == "ACTIVE"


class TestSsoEnforcementCascade:
    def test_sso_enforcement_revokes_unrestricted_pat(self, api):
        """PRD §3.1: "At depth one, every personal access token scoped to this
        enterprise that is currently `ACTIVE` **and** was created while
        `pat_policy` was `UNRESTRICTED` is moved to `REVOKED`."

        Design: Difficulty/transitive_cascade/sso_enforcement_depth3_cascade
        """
        ent = create_enterprise(purchased_seats=5, pat_policy="UNRESTRICTED")
        create_organization(ent["id"], login="org1", plan_tier="TEAM")
        user = create_user("u1")
        token = create_pat(user, ent["id"], scopes=["REPO"])
        assert token["status"] == "ACTIVE"
        sso_transition(ent["id"], "CONFIGURE")
        sso_transition(ent["id"], "ENFORCE")
        assert _pat_status(api, user["id"], token["id"]) == "REVOKED"

    def test_sso_enforcement_emits_pat_revoked_by_sso_and_suspends_admin_app(self, api):
        """PRD §3.1: "At depth two, each such revocation emits an audit event
        with action `pat.revoked_by_sso`. At depth three, every marketplace app
        installation of any organization of the enterprise that is currently
        `INSTALLED` and whose `permission_scopes` contain `ADMIN_ORG` is moved
        to `SUSPENDED` — a least-privilege re-baseline. The whole step is
        bookended by an `sso.configuration_started` event emitted at `CONFIGURE`
        and an `sso.enforced` event emitted on successful `ENFORCE`." PRD §3.1:
        "While the status is `STREAMING`, every newly written `AuditLogEvent` is
        marked `streamed` as true at write time."

        Design: Difficulty/transitive_cascade/sso_enforcement_depth3_cascade
        """
        ent = create_enterprise(purchased_seats=5, pat_policy="UNRESTRICTED")
        org = create_organization(ent["id"], login="org1", plan_tier="TEAM")
        user = create_user("u1")
        token = create_pat(user, ent["id"], scopes=["REPO"])
        app = create_and_install_app(org["id"], app_slug="ci-bot",
                                     permission_scopes=["ADMIN_ORG"])
        assert app["status"] == "INSTALLED"
        resp = api.audit_log_stream_toggle(ent["id"], EA)
        stream_status = validate_success(resp)["audit_log_stream_status"]
        sso_transition(ent["id"], "CONFIGURE")
        sso_transition(ent["id"], "ENFORCE")

        assert stream_status == "STREAMING"
        events = list_audit_events(ent["id"])
        actions = {e["action"]: e for e in events}
        assert "pat.revoked_by_sso" in actions
        assert actions["pat.revoked_by_sso"]["streamed"] is True
        assert "sso.enforced" in actions

        # Link 3: the ADMIN_ORG-scoped app dropped to SUSPENDED. There is no
        # single-get endpoint for installations; verify via a guarded action.
        # A SUSPENDED app cannot be re-suspended, so SUSPEND must not succeed,
        # while RESUME succeeds only from SUSPENDED.
        resp = api.app_installation_transition(app["id"], "RESUME", OA)
        resumed = validate_success(resp)
        assert resumed["status"] == "INSTALLED"
