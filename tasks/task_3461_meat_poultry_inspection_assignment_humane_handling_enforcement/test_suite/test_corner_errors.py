"""Breadth tests: error catalogue conditions — enum membership, withdrawal
eligibility, species support, and nested-path existence ordering."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    DISTRICT_MANAGER_HEADERS,
    PROGRAM_ADMINISTRATOR_HEADERS,
    factories as f,
    fixtures as fx,
    make_inspector_headers,
    validate_error,
    validate_paginated,
)


def test_invalid_enum_member_returns_invalid_request(api):
    """PRD §2.7: "Field-shape failures anywhere — a missing required field, a
    type mismatch, an enum member outside its declared set, an empty
    `species_classes` array, a `quantity_lbs` that is not greater than 0, an
    interval whose end is not strictly after its start or that falls outside
    its window, `grounds` shorter than 10 characters, `abatement_evidence`
    shorter than 20 characters, or a duplicate `badge_number` — are rejected
    with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "A `ProgramAdministrator` registers each establishment by
    supplying its `name`, the `species_classes` it handles — a non-empty array
    drawn from `CATTLE`, `SWINE`, `POULTRY`, and `SHEEP` (an empty array is
    rejected with `ERR_INVALID_REQUEST`) — and the `slaughter_capable` flag,
    which records whether the establishment performs slaughter and is therefore
    subject to the continuous-presence verification regime of §3.2."

    Design: Corner/errors/invalid_enum_member_returns_invalid_request
    """
    resp = api.create_establishment(
        f.establishment_payload(name="Duck Plant", species_classes=["DUCK"], slaughter_capable=True),
        PROGRAM_ADMINISTRATOR_HEADERS,
    )

    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_withdrawal_without_conditions_returns_409(api):
    """PRD §3.4: "A `WITHDRAWAL` requires that the establishment has an
    `IN_EFFECT` suspension whose `effective_at` is at least 30 days before the
    logical clock, or that at least 2 of its suspension actions with status
    `IN_EFFECT` or `LIFTED` were created within the trailing 365 days. When
    neither condition holds, activation (or creation) is rejected with
    `ERR_WITHDRAWAL_CONDITIONS_NOT_MET` (HTTP 409)."

    Design: Corner/errors/withdrawal_without_conditions_returns_409
    """
    base = fx.create_granted_establishment(api, species_classes=["CATTLE"], name="ER2 Plant")
    est_id = base["establishment"]["id"]

    # Zero suspensions ever: neither withdrawal condition can hold.
    resp = api.create_enforcement_action(
        est_id,
        f.enforcement_action_payload("WITHDRAWAL", "ADMINISTRATIVE",
                                     base["establishment"]["version"]),
        DISTRICT_MANAGER_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_CONDITIONS_NOT_MET)

    assert fx.list_enforcement_actions(api, est_id) == [], "the rejected proposal is not stored"


def test_humane_event_species_not_supported_returns_422(api):
    """PRD §3.5: "An `Inspector` reports an observation with the
    `establishment_id`, their own id as `reported_by_inspector_id` (it must
    equal the caller's `X-User-ID`, else `ERR_FORBIDDEN`), the `species`
    concerned — which must be a member of the establishment's `species_classes`,
    otherwise `ERR_SPECIES_NOT_SUPPORTED` (HTTP 422) — a `severity` of
    `EGREGIOUS` or `NON_EGREGIOUS`, the `observed_at` timestamp (not after the
    logical clock, else `ERR_FUTURE_OBSERVATION`), and a free-text
    `description`."

    Design: Corner/errors/humane_event_species_not_supported_returns_422
    """
    est = fx.create_establishment(api, name="ER3 Plant", species_classes=["CATTLE"])
    inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])

    # SWINE is a declared species enum member, but not one this plant handles.
    resp = api.create_humane_event(
        f.humane_event_payload(est["id"], inspector["id"], species="SWINE",
                               severity="NON_EGREGIOUS", description="wrong species cited"),
        make_inspector_headers(inspector["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SPECIES_NOT_SUPPORTED)

    rows, meta = validate_paginated(api.list_humane_events(DISTRICT_MANAGER_HEADERS))
    assert rows == [] and meta["total_count"] == 0, "the rejected event is not stored"


def test_assignments_on_unknown_window_return_not_found(api):
    """PRD §2.7: "Resource identifiers in the path are validated left to right,
    and body-supplied foreign-key references are then checked — a missing
    Establishment yields `ERR_ESTABLISHMENT_NOT_FOUND`, and correspondingly
    `ERR_GRANT_APPLICATION_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`,
    `ERR_SHIFT_WINDOW_NOT_FOUND`, `ERR_SHIFT_ASSIGNMENT_NOT_FOUND`,
    `ERR_NONCOMPLIANCE_RECORD_NOT_FOUND`, `ERR_ENFORCEMENT_ACTION_NOT_FOUND`,
    `ERR_HUMANE_EVENT_NOT_FOUND`, `ERR_PATHOGEN_SAMPLE_NOT_FOUND`,
    `ERR_LABEL_APPLICATION_NOT_FOUND`, `ERR_RECALL_NOT_FOUND`, or
    `ERR_APPEAL_NOT_FOUND` (all HTTP 404). On a nested path such as a shift
    window's assignments collection, a non-existent window id is reported
    before the request body is examined."

    Design: Corner/errors/assignments_on_unknown_window_return_not_found
    """
    inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])

    resp = api.create_assignment(
        NON_EXISTENT_UUID,
        f.assignment_payload(
            inspector["id"], 1, "2026-09-02T06:00:00Z", "2026-09-02T10:00:00Z", 1
        ),
        PROGRAM_ADMINISTRATOR_HEADERS,
    )

    validate_error(resp, ApiErrorId.ERR_SHIFT_WINDOW_NOT_FOUND)
