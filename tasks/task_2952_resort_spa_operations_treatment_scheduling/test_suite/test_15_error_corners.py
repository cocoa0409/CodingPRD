"""Error corners: six error families provoked against one world, each arriving
with its own declared HTTP status inside the declared error envelope, and none of
them mutating anything.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_error_envelope,
    assert_list_count,
    make_compliance_headers,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers import factories as f
from test_helpers import fixtures as fx

ENVELOPE_CLOCK = "2026-08-01T09:00:00.000Z"
# Exactly the empty string in both headers, never a whitespace string.
BLANK_HEADERS = {"X-User-ID": "", "X-User-Role": ""}
GUEST_VERSION_AFTER_SCREENING = 3        # created 1, +1 form opened, +1 screened
STALE_GUEST_VERSION = 1


def _envelope_world():
    """One guest whose form has already been screened to SCREENED_CLEAR and one
    therapist whose licence has already been reviewed to VERIFIED, so both
    repeat-the-trigger probes have a real target."""
    fx.set_clock(ENVELOPE_CLOCK)
    world = fx.SpaWorld()
    world.guest = fx.create_guest(full_name="Envelope Guest",
                                  resort_room_number="2501")
    world.intake = fx.screened_intake(world.guest["id"], world.guest["version"])
    therapist = fx.create_therapist(full_name="Envelope Therapist")
    world.therapists["Envelope Therapist"] = therapist
    world.licenses["Envelope Therapist"] = fx.verified_license(
        therapist["id"], license_number="HI-LMT-9001", expires_on="2027-06-30")
    return world


def _request_id(response):
    return response.json()["meta"]["api_request_id"]


def test_the_authentication_role_path_and_shape_families_keep_their_own_statuses():
    """Four families, four statuses, one envelope shape, four distinct request ids.

    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    PRD §2.1: "If either header is absent or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs."

    PRD §2.1: "A recognised role that is not listed as authorised for the requested
    operation — and likewise an unrecognised role string — is rejected with
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/errors/error_envelope_shape_and_http_status_fidelity_across_families
    """
    world = _envelope_world()
    request_ids = []

    unauthenticated = api_client.create_guest(
        f.guest_payload(full_name="No Auth Guest", resort_room_number="2502"),
        BLANK_HEADERS)
    assert unauthenticated.status_code == 401, (
        f"expected 401, got {unauthenticated.status_code}")
    assert_error_envelope(unauthenticated, ApiErrorId.ERR_UNAUTHENTICATED.value)
    request_ids.append(_request_id(unauthenticated))

    forbidden = api_client.create_treatment_type(
        f.treatment_type_payload(code="DRY60"), fx.COORDINATOR)
    assert forbidden.status_code == 403, f"expected 403, got {forbidden.status_code}"
    assert_error_envelope(forbidden, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)
    request_ids.append(_request_id(forbidden))

    missing = api_client.get_guest(NON_EXISTENT_UUID, fx.COORDINATOR)
    assert missing.status_code == 404, f"expected 404, got {missing.status_code}"
    assert_error_envelope(missing, ApiErrorId.ERR_GUEST_NOT_FOUND.value)
    request_ids.append(_request_id(missing))

    shapeless = api_client.create_guest(
        f.guest_payload(full_name="Shapeless Guest", resort_room_number="2503",
                        folio_limit_cents=None, loyalty_tier=None),
        fx.COORDINATOR)
    assert shapeless.status_code == 422, (
        f"expected 422, got {shapeless.status_code}")
    assert_error_envelope(shapeless, ApiErrorId.ERR_INVALID_REQUEST.value)
    request_ids.append(_request_id(shapeless))

    assert len(set(request_ids)) == len(request_ids), (
        f"every api_request_id must be unique, got {request_ids}")

    guest = validate_success(api_client.get_guest(world.guest["id"],
                                                 fx.COORDINATOR))
    assert guest["version"] == GUEST_VERSION_AFTER_SCREENING, (
        "no rejected call touched the guest")
    assert guest["folio_balance_cents"] == 0, (
        "the four refusals posted nothing to the folio")


def test_the_optimistic_concurrency_family_is_the_only_four_hundred_and_twelve():
    """The version captured at registration is two writes stale, so the form is
    refused and no row is created.

    PRD §2.7 rung 8: "**Optimistic concurrency** — the submitted expected-version
    field equals the parent resource's current `version`. Applies to intake-form
    creation and final-settlement creation. Violation: `ERR_STALE_GUEST_VERSION` or
    `ERR_STALE_APPOINTMENT_VERSION` (412)."

    PRD §2.9: "Creating an intake form for a guest requires `expected_guest_version`
    carrying the `version` of that `Guest` as the client last observed it. If the
    guest's current `version` differs, the request is rejected with
    `ERR_STALE_GUEST_VERSION` (HTTP 412)."

    Design: Corner/errors/error_envelope_shape_and_http_status_fidelity_across_families
    """
    world = _envelope_world()

    stale = api_client.create_intake_form(
        world.guest["id"], f.intake_form_payload(STALE_GUEST_VERSION),
        fx.COORDINATOR)
    assert stale.status_code == 412, f"expected 412, got {stale.status_code}"
    assert_error_envelope(stale, ApiErrorId.ERR_STALE_GUEST_VERSION.value)

    forms = assert_list_count(api_client.list_intake_forms(
        world.guest["id"], fx.COORDINATOR), 1, "intake forms of this guest")
    assert forms[0]["id"] == world.intake["id"], (
        "the refused creation wrote no second form")
    assert validate_success(api_client.get_guest(
        world.guest["id"], fx.COORDINATOR))["version"] == \
        GUEST_VERSION_AFTER_SCREENING


def test_the_two_state_legality_families_are_distinct_ids_on_the_same_status():
    """Re-screening a screened form and re-reviewing a verified licence both land on
    rung 9, yet each answers with its own error identifier.

    PRD §2.7 rung 9: "**State legality** — the target resource currently sits in a
    state from which the requested transition departs. This rung also rejects
    repeating a trigger that has already been applied and acting on a resource in a
    terminal state. Applies to every action endpoint. Violation:
    `ERR_INVALID_APPOINTMENT_STATE`, `ERR_INVALID_INTAKE_STATE`,
    `ERR_INVALID_LICENSE_STATE`, `ERR_INVALID_THERAPIST_STATE`,
    `ERR_INVALID_ATTACHMENT_STATE` or `ERR_SETTLEMENT_ALREADY_FINAL` (409)."

    PRD §3.3: "reviewing a licence that is not `PENDING_REVIEW` is refused with
    `ERR_INVALID_LICENSE_STATE`, and a reviewer whose `X-User-ID` equals
    `submitted_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`"

    Design: Corner/errors/error_envelope_shape_and_http_status_fidelity_across_families
    """
    world = _envelope_world()
    licence = world.licenses["Envelope Therapist"]

    rescreen = api_client.screen_intake_form(
        world.intake["id"], {}, make_compliance_headers(fx.CO_REVOKE))
    assert rescreen.status_code == 409, f"expected 409, got {rescreen.status_code}"
    assert_error_envelope(rescreen, ApiErrorId.ERR_INVALID_INTAKE_STATE.value)

    rereview = api_client.review_license(
        licence["id"], f.review_payload("VERIFIED"),
        make_compliance_headers(fx.CO_REVIEW))
    assert rereview.status_code == 409, f"expected 409, got {rereview.status_code}"
    assert_error_envelope(rereview, ApiErrorId.ERR_INVALID_LICENSE_STATE.value)

    assert _request_id(rescreen) != _request_id(rereview)

    form = validate_success(api_client.get_intake_form(
        world.intake["id"], fx.DIRECTOR))
    assert form["status"] == "SCREENED_CLEAR"
    assert form["screened_by_user_id"] == fx.CO_SCREEN, (
        "the refused re-screening did not overwrite the original officer")
    stored = validate_success(api_client.get_license(licence["id"], fx.DIRECTOR))
    assert stored["verification_status"] == "VERIFIED"
    assert stored["version"] == licence["version"], (
        "the refused re-review left the licence untouched"
    )
