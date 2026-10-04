"""API-surface corners: the thank-you sub-resource's empty-array read, the
authentication floor, role and ownership authorization, and OCC on the
donation row."""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    assert_cents,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    make_donor_headers,
    make_teacher_headers,
    make_vendor_headers,
)


def test_thank_you_package_sub_resource_is_an_empty_array_before_funding(api):
    """The 1:1 sub-resource reads as an empty array, not a 404, while the
    project has not been funded.

    PRD: "The teacher discharges that obligation by submitting the package — the project's single thank-you package, readable as an array of length 0 or 1"
    PRD: "The `data` field contains the resource object or an array of resource objects."
    Design: Corner/endpoints/thank_you_package_sub_resource_empty_before_funding
    """
    world = fixtures.setup_funding_project(api)
    assert world["project"]["status"] == "FUNDING"

    res = api.get_thank_you_package(world["project"]["id"], ADMIN_HEADERS)
    assert res.status_code == 200
    assert res.json()["response_type"] == "array"
    rows, meta = validate_paginated(res)
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_missing_auth_headers_returns_unauthenticated(api):
    """A call without the identity headers fails authentication before any
    other rule.

    PRD: "Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their role."
    PRD: "A request missing either header, or carrying a role that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    Design: Corner/errors/missing_auth_headers_returns_unauthenticated
    """
    fixtures.set_clock(api)
    res = api.create_school(
        f.school_payload(name="No Auth Elementary", poverty_pct=50.0, ell_pct=10.0),
        headers={},
    )
    assert res.status_code == 401
    body = res.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_UNAUTHENTICATED"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert "meta" in body


def test_teacher_cannot_create_a_school(api):
    """School registration is PlatformAdmin-exclusive; a Teacher caller is a
    403 before the body is considered.

    PRD: "A request whose role is not permitted on the endpoint, or that violates entity-backed ownership, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD: "`PlatformAdmin` — the platform operator, who manages schools, vendors, employment verification, match campaigns, equity funds, sweeps, and fraud resolution."
    Design: Corner/rbac/teacher_cannot_create_school_returns_forbidden
    """
    world = fixtures.seed_school_teacher(api)
    school = world["school"]

    res = api.create_school(
        f.school_payload(name="Rogue Academy", district="Rogue ISD",
                         poverty_pct=50.0, ell_pct=10.0),
        make_teacher_headers(world["teacher"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, 403)

    # The original school row is untouched.
    reread = fixtures.get_success_data(api.get_school(school["id"], ADMIN_HEADERS))
    assert reread["name"] == school["name"]
    assert reread["district"] == school["district"]
    assert reread["state_code"] == school["state_code"]


def test_donor_cannot_review_a_project(api):
    """Review decisions are Reviewer-exclusive; the project's own funder is
    still a Donor and is refused.

    PRD: "A request whose role is not permitted on the endpoint, or that violates entity-backed ownership, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD: "`Reviewer` — a vetting reviewer who screens and vets projects."
    Design: Corner/rbac/donor_cannot_review_project_returns_forbidden
    """
    world = fixtures.setup_draft_project(api)
    project_id = world["project"]["id"]
    fixtures.submit_project(api, project_id, world["teacher"])
    donor = fixtures.create_donor(api)

    res = api.review_project(
        project_id, f.review_payload("SCREEN", "APPROVE"), make_donor_headers(donor["id"])
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, 403)

    project = fixtures.read_project(api, project_id)
    assert project["status"] == "IN_REVIEW"
    assert project.get("screened_by_id") is None


def test_vendor_cannot_ship_another_vendors_purchase_order(api):
    """SHIP is entity-backed: the caller's X-User-ID must equal the order's
    vendor_id.

    PRD: "The vendor ships its own orders: advancing the purchase order identified by `po_id` with `action` value `SHIP` requires the acting `X-User-ID` to equal the order's `vendor_id` (`ERR_FORBIDDEN` otherwise)"
    Design: Corner/rbac/vendor_cannot_ship_other_vendors_po_returns_forbidden
    """
    world = fixtures.setup_funded_project(api)
    po = world["purchase_orders"][0]
    assert po["vendor_id"] == world["vendor"]["id"]

    other_vendor = fixtures.create_vendor(api, name="RugCo", contact_email="ops@rugco.example")

    res = api.advance_purchase_order(
        po["id"],
        f.po_advance_payload("SHIP", tracking_number="1Z888BB20123456789"),
        make_vendor_headers(other_vendor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, 403)

    po_after = fixtures.read_purchase_order(api, po["id"])
    assert po_after["status"] == "ISSUED"
    assert po_after["shipped_at"] is None


def test_occ_conflict_on_a_stale_donation_version(api):
    """The sweep's transition into CHOICE_PENDING advanced the donation's
    version; a choice replaying the pre-sweep version is stale.

    PRD: "**Recording a reallocation choice on a donation** requires `expected_donation_version` matching the donation's current `version`. A client whose observed version predates, for example, the sweep's transition of the donation into `CHOICE_PENDING` with a fresh `choice_deadline` holds a stale view, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    Design: Corner/cross_cutting_layers/occ_conflict_on_stale_donation_version
    """
    world = fixtures.setup_expired_project(api, amounts=(5000,))
    donor = world["donor"]
    donation = world["donations"][0]
    assert donation["status"] == "CHOICE_PENDING"

    fresh_version = donation["version"]
    assert fresh_version > 1, "the sweep bumped the version at the transition"

    res = api.reallocation_choice(
        donation["id"],
        f.reallocation_choice_payload("REFUND", fresh_version - 1),
        make_donor_headers(donor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, 412)

    still_pending = fixtures.read_donation(api, donation["id"])
    assert still_pending["status"] == "CHOICE_PENDING"

    # A retry carrying the fresh version succeeds.
    retried = validate_success(
        api.reallocation_choice(
            donation["id"],
            f.reallocation_choice_payload("REFUND", fresh_version),
            make_donor_headers(donor["id"]),
        ),
        200,
    )
    assert retried["status"] == "REFUNDED"
    assert retried["refund_reason"] == "EXPIRED_CHOICE"
