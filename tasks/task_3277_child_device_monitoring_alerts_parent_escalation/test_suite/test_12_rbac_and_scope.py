"""RBAC and scope enforcement: role denial and cross-scope access."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_child,
    create_district,
    create_district_link,
    create_family,
    consent_district_link,
    ingest_content,
    make_parent_headers,
    make_school_admin_headers,
    setup_monitoring_pipeline,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_parent_cannot_create_district_returns_403(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not
    permitted for the endpoint, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "POST /api/districts | Create a district | PlatformAdmin"

    Design: Corner/rbac/parent_cannot_create_district_returns_403
    """
    fam, parent = create_family()
    headers = make_parent_headers(parent["id"])
    resp = api.create_district(
        {"district_name": "Rogue District", "contact_email": "x@y.edu",
         "jurisdiction": "DISCRETIONARY"},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_parent_cannot_read_raw_content_items_returns_403(api):
    """PRD §2.9: "The platform's founding privacy commitment is that parents
    and school administrators never see raw message text. The full `raw_text` of
    a content item is a restricted read surface: it is visible only to
    `PlatformAdmin` on the raw monitoring endpoints."
    PRD §2.1: "If the headers are well-formed but the named role is not
    permitted for the endpoint, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/parent_cannot_read_raw_content_items_returns_403
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2012)
    ingest_content(
        conn["id"], dev["id"],
        signals=[{"category": "BULLYING", "weight": 40}], raw_text="privacy item",
    )
    headers = make_parent_headers(parent["id"])
    resp = api.list_content_items_of_connection(conn["id"], headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_device_agent_cannot_acknowledge_alert_returns_403(api):
    """PRD §4: "POST /api/alerts/{id}/state | Acknowledge, resolve, or reopen
    an alert | Parent"
    PRD §2.1: "If the headers are well-formed but the named role is not
    permitted for the endpoint, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/device_agent_cannot_acknowledge_alert_returns_403
    """
    from test_helpers import make_device_agent_headers, setup_alert

    fam, parent, child, dev, conn, item = setup_alert()
    headers = make_parent_headers(parent["id"])

    resp = api.set_alert_state(
        item["alert_id"], {"to_status": "ACKNOWLEDGED"},
        make_device_agent_headers(dev["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    alert = validate_success(api.get_alert(item["alert_id"], headers))
    assert alert["alert_status"] == "DELIVERED"


def test_school_admin_severity_gate_returns_403(api):
    """PRD §2.1: "A `SchoolAdmin` may only ever view alerts whose severity is
    `HIGH` or `SEVERE`; attempting to view an alert with severity `LOW` or
    `MODERATE` is rejected with `ERR_SEVERITY_VISIBILITY_DENIED` (HTTP 403)."

    Design: Corner/rbac/school_admin_severity_gate_returns_403
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2012)
    district = create_district(
        district_name="District SG", contact_email="admin@sg.edu",
        jurisdiction="DISCRETIONARY",
    )
    link = create_district_link(district["id"], child["id"])
    consent_district_link(link["id"], parent["id"])

    # BULLYING 40 -> MODERATE alert.
    item = ingest_content(
        conn["id"], dev["id"],
        signals=[{"category": "BULLYING", "weight": 40}],
        raw_text="severity gate item",
    )
    assert item["severity"] == "MODERATE"

    resp = api.get_alert(item["alert_id"], make_school_admin_headers(district["id"]))
    validate_error(resp, ApiErrorId.ERR_SEVERITY_VISIBILITY_DENIED)


def test_cross_family_child_read_returns_403(api):
    """PRD §2.1: "Cross-scope access is forbidden even when the role is
    otherwise allowed. A `Parent` attempting to read or mutate a resource that
    belongs to a different family is rejected with `ERR_CROSS_FAMILY_ACCESS`
    (HTTP 403)."

    Design: Corner/rbac/cross_family_child_read_returns_403
    """
    fam_a, parent_a = create_family(
        family_name="Fam XA", primary_contact_email="xa@x.com",
        primary_parent_name="Pat XA",
    )
    child_a = create_child(fam_a["id"], parent_a["id"], display_name="Kid XA")

    fam_b, parent_b = create_family(
        family_name="Fam XB", primary_contact_email="xb@x.com",
        primary_parent_name="Pat XB",
    )

    resp = api.get_child(child_a["id"], make_parent_headers(parent_b["id"]))
    validate_error(resp, ApiErrorId.ERR_CROSS_FAMILY_ACCESS)


def test_school_admin_without_link_returns_403(api):
    """PRD §2.1: "A `SchoolAdmin` attempting to access a child for whom their
    district has no `ACTIVE` `DistrictLink` is rejected with
    `ERR_CROSS_DISTRICT_ACCESS` (HTTP 403)."

    Design: Corner/rbac/school_admin_without_link_returns_403
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2012)
    item = ingest_content(
        conn["id"], dev["id"],
        signals=[
            {"category": "SELF_HARM", "weight": 45},
            {"category": "BULLYING", "weight": 30},
        ],
        raw_text="cross district item",
    )
    assert item["severity"] == "HIGH"

    district = create_district(
        district_name="District CD", contact_email="admin@cd.edu",
        jurisdiction="DISCRETIONARY",
    )
    resp = api.get_alert(item["alert_id"], make_school_admin_headers(district["id"]))
    validate_error(resp, ApiErrorId.ERR_CROSS_DISTRICT_ACCESS)


def test_scope_violation_beats_state_returns_403(api):
    """PRD §2.7: "Endpoints whose paths traverse a resource hierarchy validate
    path identifiers left to right: each identifier is resolved and checked for
    existence before the next identifier in the path is considered. Any
    identifier that does not resolve to an existing resource produces
    `ERR_NOT_FOUND` (HTTP 404). After existence, scope checks apply — a `Parent`
    reaching into another family's subtree receives `ERR_CROSS_FAMILY_ACCESS`,
    and a `SchoolAdmin` reaching outside their district linkage receives
    `ERR_CROSS_DISTRICT_ACCESS` — so a caller can never distinguish "does not
    exist" from "exists but is out of scope" except through the distinct error
    codes above."
    PRD §2.6: "Validation on these guarded writes evaluates the version check
    after authentication, authorization, existence, and scope checks, but before
    state-transition and business-rule checks."

    Design: Corner/validations/scope_violation_beats_state_returns_403
    """
    fam_a, parent_a = create_family(
        family_name="Fam SA", primary_contact_email="sa@x.com",
        primary_parent_name="Pat SA",
    )
    headers_a = make_parent_headers(parent_a["id"])
    child_a = create_child(fam_a["id"], parent_a["id"], display_name="Kid SA")
    archived_version = child_a["version"]

    # Archive the child (legitimately, as its own parent).
    validate_success(
        api.patch_child(
            child_a["id"],
            {"profile_status": "ARCHIVED",
             "expected_child_version": archived_version},
            headers_a,
        )
    )

    fam_b, parent_b = create_family(
        family_name="Fam SB", primary_contact_email="sb@x.com",
        primary_parent_name="Pat SB",
    )
    # A parent of family B PATCHing family A's (archived) child fails scope
    # before the archived-state and version checks.
    resp = api.patch_child(
        child_a["id"],
        {"monitoring_sensitivity": "STRICT",
         "expected_child_version": archived_version},
        make_parent_headers(parent_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_FAMILY_ACCESS)


def test_unauthenticated_request_returns_401(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID` and
    `X-User-Role`. A request missing either header, or carrying a malformed
    value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.1: "These two authentication checks run before any other validation
    on every endpoint."

    Design: Corner/consistency_model/unauthenticated_request_returns_401
    """
    from test_helpers import MISSING_UUID

    resp = api.get_family(MISSING_UUID, headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
