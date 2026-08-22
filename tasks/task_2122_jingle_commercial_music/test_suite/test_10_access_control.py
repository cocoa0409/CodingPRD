"""Identity headers, role authorization and entity-backed ownership."""
from test_helpers import (
    ApiErrorId,
    build_user_headers,
    create_client,
    create_composer,
    create_project,
    get_demo,
    get_project,
    make_composer_headers,
    make_producer_headers,
    pitch_demo,
    setup_engagement,
    setup_engagement_in_demo,
    submit_demo,
    validate_error,
)
from test_helpers.fixtures import get_brief


def test_composer_cannot_shortlist_a_demo(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not among
    those authorized for the endpoint (see the table in §4), the request is rejected
    with `ERR_FORBIDDEN_ROLE` and HTTP 403."
    PRD §3.3: "Shortlisting is the advertiser's first filter: a `ClientRep` owning the
    engagement moves a demo `SUBMITTED → SHORTLISTED`, again with no money movement."

    Design: Corner/rbac/corner_composer_cannot_shortlist_a_demo
    """
    env = setup_engagement_in_demo(budget_cents=4_000_000)
    composer = create_composer(index=0)
    demo = pitch_demo(env["project"]["id"], composer["id"], title="Cut One",
                      demo_fee_cents=100_000, submitted_length_seconds=30)
    submit_demo(demo["id"], composer["id"])

    validate_error(
        api.shortlist_demo(demo["id"], make_composer_headers(composer["id"])),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    assert get_demo(demo["id"])["status"] == "SUBMITTED", (
        "A forbidden role must not move the demo")


def test_client_rep_of_another_advertiser_cannot_approve_this_brief(api):
    """PRD §2.1: "When `X-User-Role` is `ClientRep`, `X-User-ID` is the `id` of the
    acting `Client`; ownership checks on any resource that references a `Client` compare
    the governing engagement's `client_id` field to `X-User-ID`."
    PRD §2.1: "Any mismatch on either of these comparisons is rejected with
    `ERR_NOT_RESOURCE_OWNER` and HTTP 403."

    Design: Corner/rbac/corner_client_rep_of_another_client_cannot_approve_this_brief
    """
    env = setup_engagement(budget_cents=4_000_000)
    rival = create_client(name="Rival Drinks", billing_email="ap@rival.example")

    validate_error(
        api.approve_brief(env["brief"]["id"], build_user_headers(rival["id"], "ClientRep")),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    brief = get_brief(env["project"]["id"], env["brief"]["id"])
    assert brief["status"] == "DRAFT", f"Expected DRAFT, got {brief['status']}"
    project = get_project(env["project"]["id"])
    assert project["status"] == "BRIEFING", f"Expected BRIEFING, got {project['status']}"


def test_composer_cannot_submit_another_writers_demo(api):
    """PRD §2.1: "When `X-User-Role` is `Composer`, `X-User-ID` is the `id` of the
    acting `Composer`; ownership checks on a demo compare that demo's `composer_id` to
    `X-User-ID`, and when a composer pitches a new demo the server takes `composer_id`
    from the header and never from the request body."
    PRD §2.1: "Any mismatch on either of these comparisons is rejected with
    `ERR_NOT_RESOURCE_OWNER` and HTTP 403."
    PRD §3.3: "Both require the acting `Composer` to own the demo and the engagement to
    be in `IN_DEMO`; neither has any fiscal effect."

    Design: Corner/rbac/corner_composer_cannot_submit_another_composers_demo
    """
    env = setup_engagement_in_demo(budget_cents=4_000_000)
    owner = create_composer(index=0)
    stranger = create_composer(index=1)
    demo = pitch_demo(env["project"]["id"], owner["id"], title="Cut One",
                      demo_fee_cents=100_000, submitted_length_seconds=30)

    validate_error(
        api.submit_demo(demo["id"], make_composer_headers(stranger["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    assert get_demo(demo["id"])["status"] == "DRAFT", (
        "A non-owning writer must not move the demo")


def test_composer_cannot_read_the_afm_wage_report(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not among
    those authorized for the endpoint (see the table in §4), the request is rejected
    with `ERR_FORBIDDEN_ROLE` and HTTP 403."
    PRD §3.9: "The AFM wage report rolls an engagement's union obligations into a single
    read for the house's producers, the rights desk and the AFM steward."

    Design: Corner/rbac/corner_composer_cannot_read_the_afm_wage_report
    """
    client = create_client(name="Harborline Foods")
    project = create_project(client["id"], title="Winter Warmth", budget_cents=4_000_000)
    composer = create_composer(index=0)

    validate_error(
        api.get_afm_report(project["id"], make_composer_headers(composer["id"])),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_unrecognised_or_missing_role_header_is_unauthenticated(api):
    """PRD §2.1: "Every request to every endpoint — reads included — must carry both
    `X-User-ID` and `X-User-Role`."
    PRD §2.1: "If either header is absent, or if the supplied role is not one of the
    five declared roles, the request is rejected with `ERR_UNAUTHENTICATED` and HTTP
    401."
    PRD §2.1: "The five roles, spelled exactly as they must appear in the header, are
    `MusicHouseProducer`, `ClientRep`, `Composer`, `RightsAdmin` and `AFMSteward`."

    Design: Corner/rbac/corner_unknown_role_header_returns_unauthenticated
    """
    client = create_client(name="Harborline Foods")
    project = create_project(client["id"], title="Winter Warmth", budget_cents=4_000_000)

    validate_error(
        api.get_project(project["id"], build_user_headers("intern-1", "StudioIntern")),
        ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    validate_error(
        api.get_project(project["id"],
                        {"X-User-ID": "intern-1", "Content-Type": "application/json"}),
        ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    # The same read succeeds under a declared role, so the 401 is about the header only.
    assert get_project(project["id"], make_producer_headers())["id"] == project["id"]
