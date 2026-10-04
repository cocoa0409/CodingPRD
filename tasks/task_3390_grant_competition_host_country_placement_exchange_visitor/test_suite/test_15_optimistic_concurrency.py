"""Optimistic concurrency control on the application version (PRD §2.8)."""
from test_helpers import (
    ApiErrorId,
    create_placement_round_payload,
    get_application,
    make_applicant_headers,
    open_placement_round,
    patch_application_payload,
    setup_draft_application,
    setup_selected_application,
    validate_error,
    validate_success,
)


def test_occ_stale_version_on_application_patch_returns_412(api):
    """PRD §2.8: "The applicant's edit of a DRAFT application's fields, and
    the host commission's opening of a placement negotiation round, each
    require `expected_application_version` in the request body, carrying the
    `version` of the application the client last observed. If the
    application's current `version` has advanced past that value — through
    any mutation, including cascaded ones such as the version bumps applied
    by submission, committee decisions, or an earlier round's creation — the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the
    client from overwriting a state it has not observed."

    The first patch at the observed version succeeds; replaying the same
    version is stale.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_application_patch_returns_412
    """
    bundle = setup_draft_application()
    app = bundle["application"]
    applicant_headers = make_applicant_headers(bundle["applicant"]["id"])
    observed_version = app["version"]

    first = api.patch_application(
        app["id"],
        patch_application_payload(observed_version, project_title="Moorland Revised"),
        applicant_headers,
    )
    patched = validate_success(first, 200)
    assert patched["version"] == observed_version + 1
    assert patched["project_title"] == "Moorland Revised"

    replay = api.patch_application(
        app["id"],
        patch_application_payload(observed_version, project_title="Moorland Hijacked"),
        applicant_headers,
    )
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION)

    after = get_application(app)
    assert after["project_title"] == "Moorland Revised"
    assert after["version"] == observed_version + 1


def test_occ_stale_version_on_placement_round_create_returns_412(
    api, host_commission_headers,
):
    """PRD §2.8: "If the application's current `version` has advanced past
    that value — through any mutation, including cascaded ones such as the
    version bumps applied by submission, committee decisions, or an earlier
    round's creation — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412), preventing the client from overwriting a state it has not
    observed."
    PRD §2.8: "For the round-opening operation this guard is what makes the
    single-open-round rule safe to reason about: a stale writer's view of the
    negotiation position has already been superseded by whatever newer round
    or state the version bump records."

    The version captured at SELECT went stale when round 1 was created; the
    OCC rejection (priority 4) precedes the active-round constraint
    (priority 9) even though round 1 is still OFFERED.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_placement_round_create_returns_412
    """
    bundle = setup_selected_application()
    app = bundle["application"]
    stale_version = app["version"]  # the version observed at SELECT

    first = open_placement_round(app)  # bumps the application's version
    assert first["status"] == "OFFERED"

    resp = api.create_placement_round(
        app["id"],
        create_placement_round_payload(
            stale_version,
            institution_name="Aachen Institute",
            institution_band="HIGH",
            response_deadline="2027-04-01T00:00:00Z",
        ),
        host_commission_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    assert get_application(app)["placement_rounds_used"] == 1, (
        "the stale round create must not increment placement_rounds_used"
    )
