"""Security: unauthenticated requests and org-ownership enforcement."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_org_owner_headers,
    validate_success,
    validate_error,
    get_success_data,
    create_org,
    create_editor_version,
    create_project,
    setup_personal_and_pro_tiers,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Queue B — validations / unauthenticated_request_rejected
# ---------------------------------------------------------------------------

class TestUnauthenticated:
    def test_missing_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying an unrecognized role
        value, is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

        Design: Corner/validations/unauthenticated_request_rejected
        """
        resp = api.list_tiers(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---------------------------------------------------------------------------
# Queue B — rbac / org_owner_cannot_touch_other_orgs_project
# ---------------------------------------------------------------------------

class TestCrossOrgOwnership:
    def test_foreign_org_ship_rejected(self, api):
        """PRD §2.1: "An OrgOwner acting on a resource whose org chain resolves to a
        different org's id is rejected with ERR_FORBIDDEN_ORG (HTTP 403)."

        Design: Corner/rbac/org_owner_cannot_touch_other_orgs_project
        """
        setup_personal_and_pro_tiers()
        org_a = create_org("PRO", legal_name="Org A", contact_email="a2@x.com")
        org_b = create_org("PRO", legal_name="Org B", contact_email="b3@x.com")
        ev = create_editor_version("2022.3.60f1", "2022.3", "2025-09-01")
        project_b = create_project(org_b, ev["id"], title="Game B")

        resp = api.ship_project(project_b["id"], make_org_owner_headers(org_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ORG.value)

        project_now = get_success_data(api.get_project(project_b["id"], ADMIN), 200)
        assert project_now["project_status"] == "DEVELOPMENT"
