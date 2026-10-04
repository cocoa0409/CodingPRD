"""Role authorization and entity-backed ownership rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_build_payload,
    confirm_loan_payload,
    create_apprentice,
    create_artist,
    create_craftsman,
    create_loan,
    create_wood_batch_payload,
    get_concert_loan,
    get_endorsement,
    log_hours_payload,
    make_apprentice_headers,
    make_artist_headers,
    make_master_craftsman_headers,
    setup_commissioned_build,
    setup_endorsement,
    setup_pending_endorsement,
    validate_error,
)

WM = TEST_USERS["workshop_manager_headers"]
LIAISON = TEST_USERS["artist_liaison_headers"]


def test_rbac_artist_cannot_create_wood_batch(api):
    """PRD section 2.1: "A request whose role is not in the endpoint's authorized
    list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." Section 4 limits
    POST /piano-works/wood-batches to WorkshopManager.

    Design: Corner/rbac/rbac_artist_cannot_create_wood_batch
    """
    artist = create_artist("Art X", "STANDARD", 2)
    resp = api.create_wood_batch(
        create_wood_batch_payload("MAPLE", 12.0), make_artist_headers(artist["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_rbac_workshop_manager_cannot_assess(api):
    """PRD section 2.1: "A request whose role is not in the endpoint's authorized
    list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." Section 4 limits
    the assess endpoint to MasterCraftsman.

    Design: Corner/rbac/rbac_workshop_manager_cannot_assess
    """
    ctx = setup_pending_endorsement("RIM_BENDING")
    resp = api.assess_endorsement(ctx["endorsement"]["id"], {"outcome": "ENDORSE"}, WM)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert get_endorsement(ctx["endorsement"]["id"])["status"] == "PENDING_ASSESSMENT"


def test_rbac_apprentice_cannot_confirm_loan(api):
    """PRD section 2.1: "A request whose role is not in the endpoint's authorized
    list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." Section 4 limits
    loan confirm to ArtistLiaison.

    Design: Corner/rbac/rbac_apprentice_cannot_confirm_loan
    """
    cr_voi = create_craftsman("VOICING", "Voi Master")
    apprentice = create_apprentice("Apr V")
    artist = create_artist("Art V", "STANDARD", 2)
    loan = create_loan(artist, "MODEL_B", "2027-01-10T00:00:00Z", "2027-01-24T00:00:00Z")
    resp = api.confirm_concert_loan(
        loan["id"],
        confirm_loan_payload(cr_voi["id"]),
        make_apprentice_headers(apprentice["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert get_concert_loan(loan["id"])["status"] == "REQUESTED"


def test_rbac_liaison_cannot_advance_build(api):
    """PRD section 2.1: "A request whose role is not in the endpoint's authorized
    list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." Section 4 limits
    the build advance to MasterCraftsman and Apprentice.

    Design: Corner/rbac/rbac_liaison_cannot_advance_build
    """
    ctx = setup_commissioned_build("MODEL_O")
    build = ctx["build"]
    resp = api.advance_build_order(
        build["id"], advance_build_payload("RIM_BENT", 100, build["version"]), LIAISON
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    after = api.get_build_order(build["id"], WM).json()["data"]
    assert after["status"] == "COMMISSIONED"
    assert after["version"] == build["version"]


def test_rbac_craftsman_cannot_log_hours(api):
    """PRD section 2.1: "A request whose role is not in the endpoint's authorized
    list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." Section 4 limits
    log-hours to Apprentice.

    Design: Corner/rbac/rbac_craftsman_cannot_log_hours
    """
    ctx = setup_endorsement("RIM_BENDING")
    cr_rim = create_craftsman("RIM_BENDING", "Rim Master")
    resp = api.log_endorsement_hours(
        ctx["endorsement"]["id"],
        log_hours_payload(10, cr_rim["id"]),
        make_master_craftsman_headers(cr_rim["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_apprentice_cannot_log_others_endorsement_forbidden(api):
    """PRD section 2.1: "an apprentice may log hours only against an endorsement
    track whose `apprentice_id` equals their `X-User-ID`, and an attempt against
    another apprentice's track is rejected with `ERR_FORBIDDEN_RESOURCE`
    (HTTP 403)."

    Design: Corner/rbac/apprentice_cannot_log_others_endorsement_forbidden
    """
    cr_rim = create_craftsman("RIM_BENDING", "Rim Master")
    intruder = create_apprentice("Apr Two")
    ctx = setup_endorsement("RIM_BENDING")  # owned by a different apprentice
    resp = api.log_endorsement_hours(
        ctx["endorsement"]["id"],
        log_hours_payload(10, cr_rim["id"]),
        make_apprentice_headers(intruder["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_RESOURCE)
    assert get_endorsement(ctx["endorsement"]["id"])["logged_hours"] == 0
