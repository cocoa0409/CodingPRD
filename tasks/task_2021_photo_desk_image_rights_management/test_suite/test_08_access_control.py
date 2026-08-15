"""Access control: role exclusivity, entity-backed ownership, and authentication
(PRD §2.1, §2.8)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    commission_assignment,
    commission_decision_payload,
    create_photographer,
    create_story,
    ingest_image_payload,
    ingest_wire_image,
    make_photographer_headers,
    validate_error,
    wire_stock_decision_payload,
)


def test_photographer_cannot_clear_image(api, photo_editor_headers):
    """PRD §2.1: "An authenticated caller attempting an operation outside their
    role's permission set is rejected with `ERR_FORBIDDEN` (HTTP 403)." (The
    endpoint table in §4 reserves image clearance to `RightsManager`.)

    Design: Corner/rbac/photographer_cannot_clear_image
    """
    photographer = create_photographer()
    image = ingest_wire_image()

    resp = api.clear_image(image["id"], make_photographer_headers(photographer["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_finance_admin_cannot_decide_story(api, finance_admin_headers):
    """PRD §2.1: "An authenticated caller attempting an operation outside their
    role's permission set is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §2.8:
    "2. Authorization and ownership — role permitted for the endpoint,
    entity-backed ownership for `Photographer`, `include_archived` restricted to
    `Archivist`/`RightsManager`; else `ERR_FORBIDDEN`."

    Design: Corner/rbac/finance_admin_cannot_decide_story
    """
    story = create_story()
    resp = api.decide_story_request(
        story["id"], wire_stock_decision_payload(NON_EXISTENT_UUID), finance_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_photographer_submit_on_others_assignment_forbidden(api, photo_editor_headers):
    """PRD §3.4: "The acting photographer must own the assignment — the
    assignment's `photographer_id` must equal `X-User-ID` — or the submission is
    rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/photographer_submit_on_others_assignment_forbidden
    """
    owner = create_photographer()
    other = create_photographer(
        full_name="Fran Free", email="fran@freelance.io", photographer_type="FREELANCE",
        day_rate_cents=20000, per_image_fee_cents=30000,
    )
    story = create_story()
    _, assignment_id = commission_assignment(owner["id"], story_id=story["id"])

    resp = api.submit_assignment_image(
        assignment_id,
        {
            "caption": "Trespassing lens on the bridge",
            "credit_line": "Fran Free / ACME News",
        },
        make_photographer_headers(other["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Missing or invalid headers — either header absent, or a role
    value that is not one of the six declared roles — are rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    image = ingest_wire_image()
    resp = api.get_image(image["id"], headers=None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
