"""RBAC tests: role denial and entity-backed ownership."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_publisher,
    create_channel,
    create_viewer,
    submit_channel_version,
    generate_statement,
    create_manufacturer,
    make_publisher_headers,
    make_viewer_headers,
    make_manufacturer_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ADOPS = TEST_USERS["adops_headers"]


def test_viewer_cannot_create_channel_forbidden_role():
    """PRD §2.1: "If the named role is not permitted to invoke the endpoint,
    the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/viewer_cannot_create_channel_forbidden_role
    """
    publisher = create_publisher(legal_name="RB Pub")
    viewer = create_viewer(email="rb@x.com")

    resp = api_client.create_channel(
        {
            "publisher_id": publisher["id"],
            "name": "Nope",
            "category": "VIDEO",
            "content_rating": "G",
        },
        make_viewer_headers(viewer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_publisher_cannot_operate_another_publishers_channel():
    """PRD §2.1: "When `X-User-Role` is `Publisher`, `X-User-ID` is the `id`
    of the acting `Publisher`; ownership checks on any resource that
    references a publisher — a channel, a campaign, a statement, a dispute —
    compare the resource's foreign-key field to `X-User-ID`, and a mismatch
    is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/publisher_cannot_operate_another_publishers_channel
    """
    p1 = create_publisher(legal_name="Own P1")
    p2 = create_publisher(legal_name="Own P2")
    channel = create_channel(p1, name="Owned Channel")

    resp = api_client.create_channel_version(
        channel["id"],
        {
            "version_label": "9.9.9",
            "technical_checklist": {
                "deep_linking": True, "drm": True, "trick_play": True,
            },
            "expected_channel_version": channel["version"],
        },
        make_publisher_headers(p2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    current = get_success_data(api_client.get_channel(channel["id"], ADMIN))
    assert current["status"] == "DRAFT"
    rows = get_success_data(
        api_client.list_channel_versions(channel["id"], ADMIN)
    )
    assert len(rows) == 0


def test_adops_cannot_finalize_statement():
    """PRD §2.1: "`PlatformAdmin` is the platform operator: it owns publisher
    onboarding and standing, channel publication and removal, certification
    decisions, viewer account creation, refunds, ad-grant administration,
    manufacturer licensing, OS update administration, device sales, statement
    generation/finalization/settlement, dispute adjudication, and the logical
    clock."

    Design: Corner/rbac/adops_cannot_finalize_statement
    """
    publisher = create_publisher(legal_name="SoD Pub")
    statement = generate_statement(publisher["id"], "2026-09")

    resp = api_client.finalize_statement(statement["id"], ADOPS)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    assert get_success_data(api_client.get_statement(statement["id"], ADMIN))[
        "status"] == "OPEN"


def test_tvmanufacturer_cannot_decide_channel_version():
    """PRD §2.1: "`PlatformAdmin` is the platform operator: it owns publisher
    onboarding and standing, channel publication and removal, certification
    decisions, viewer account creation, refunds, ad-grant administration,
    manufacturer licensing, OS update administration, device sales, statement
    generation/finalization/settlement, dispute adjudication, and the logical
    clock."

    Design: Corner/rbac/tvmanufacturer_cannot_decide_channel_version
    """
    publisher = create_publisher(legal_name="Dec Pub")
    channel = create_channel(publisher, name="Dec Channel")
    version = submit_channel_version(channel["id"], publisher["id"],
                                     version_label="1.0.0")
    get_success_data(api_client.review_channel_version(version["id"], ADMIN))
    manufacturer = create_manufacturer(legal_name="Dec TV")

    resp = api_client.decide_channel_version(
        version["id"], {"outcome": "PASS"},
        make_manufacturer_headers(manufacturer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    assert get_success_data(
        api_client.get_channel_version(version["id"], ADMIN)
    )["review_status"] == "IN_REVIEW"
