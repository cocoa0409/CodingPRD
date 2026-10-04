"""Breadth tests: the fixed validation pipeline — user context, optimistic
concurrency, ownership pinning, and observation-time rules."""

from test_helpers import (
    ApiErrorId,
    CLOCK_START_ISO,
    DISTRICT_MANAGER_HEADERS,
    PROGRAM_ADMINISTRATOR_HEADERS,
    assert_instant,
    factories as f,
    fixtures as fx,
    headers_without_role,
    headers_without_user_id,
    make_establishment_manager_headers,
    make_inspector_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_missing_auth_header_on_write_returns_400(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring the capacity in
    which they act. A request missing either header, or carrying a role string
    the system does not declare, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_on_write_returns_400
    """
    payload = f.establishment_payload(name="NoAuth Plant", species_classes=["CATTLE"])

    no_role = api.create_establishment(payload, headers_without_role("some-operator"))
    validate_error(no_role, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    no_user = api.create_establishment(payload, headers_without_user_id())
    validate_error(no_user, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_occ_stale_establishment_version_returns_412(api):
    """PRD §2.8: "Creating an enforcement action against an establishment
    requires the request body to carry `expected_establishment_version`,
    holding the client's last observed `version` of that establishment. If the
    establishment's version has advanced since — for example because a
    categorization cascade or a grant decision mutated it in between — the
    creation is rejected with `ERR_STALE_ESTABLISHMENT_VERSION` (HTTP 412), and
    the client must re-read the establishment and re-base the proposal."

    Design: Corner/validations/occ_stale_establishment_version_returns_412
    """
    est = fx.create_establishment(api, name="V2 Plant", species_classes=["CATTLE"])
    inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])
    fx.issue_nr(api, est["id"], inspector["id"], regulation_family="SANITATION",
                description="qualifying nr")
    stale_version = fx.get_establishment(api, est["id"])["version"]

    first = api.create_enforcement_action(
        est["id"],
        f.enforcement_action_payload("WITHHOLD_MARKS", "NR_LINKAGE", stale_version,
                                     regulation_family="SANITATION"),
        DISTRICT_MANAGER_HEADERS,
    )
    validate_success(first, 201)

    # The first create advanced the establishment version; the same value is
    # now stale even though the second proposal is perfectly eligible.
    second = api.create_enforcement_action(
        est["id"],
        f.enforcement_action_payload("NOTICE_OF_INTENDED_ENFORCEMENT", "ADMINISTRATIVE", stale_version),
        DISTRICT_MANAGER_HEADERS,
    )
    validate_error(second, ApiErrorId.ERR_STALE_ESTABLISHMENT_VERSION)

    actions = fx.list_enforcement_actions(api, est["id"])
    assert len(actions) == 1, "only the fresh-version create landed"


def test_occ_stale_shift_window_version_returns_412(api):
    """PRD §2.8: "Adding a shift assignment to a shift window requires the
    request body to carry `expected_shift_window_version`, holding the client's
    last observed `version` of that window. Because every assignment creation
    itself increments the window's `version` by 1, a client stacking several
    assignments must re-read the window between creations; a mismatch is
    rejected with `ERR_STALE_SHIFT_WINDOW_VERSION` (HTTP 412)."

    Design: Corner/validations/occ_stale_shift_window_version_returns_412
    """
    base = fx.setup_granted_with_window(
        api, species_classes=["CATTLE"], name="V3 Plant", planned_line_count=2
    )
    window = base["window"]
    inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])
    create_time_version = window["version"]

    first = api.create_assignment(
        window["id"],
        f.assignment_payload(inspector["id"], 1, "2026-09-02T06:00:00Z", "2026-09-02T10:00:00Z",
                             create_time_version),
        PROGRAM_ADMINISTRATOR_HEADERS,
    )
    validate_success(first, 201)

    # Same create-time version on the second create: stale. The interval sits
    # on line 2, so no other rule can fail.
    second = api.create_assignment(
        window["id"],
        f.assignment_payload(inspector["id"], 2, "2026-09-02T06:00:00Z", "2026-09-02T10:00:00Z",
                             create_time_version),
        PROGRAM_ADMINISTRATOR_HEADERS,
    )
    validate_error(second, ApiErrorId.ERR_STALE_SHIFT_WINDOW_VERSION)

    rows = api.list_shift_assignments(DISTRICT_MANAGER_HEADERS)
    data, _meta = validate_paginated(rows)
    assert len(data) == 1, "only the first create landed"


def test_nr_respond_by_other_establishment_forbidden(api):
    """PRD §3.3: "The establishment answers through its `EstablishmentManager`:
    responding moves an `OPEN` record to `RESPONSE_SUBMITTED` and stores the
    supplied `response_text`. Responding is ownership-pinned — `X-User-ID` must
    equal the record's `establishment_id`, else `ERR_FORBIDDEN` — and is
    defined only from `OPEN`, so a response to an already-answered record is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/validations/nr_respond_by_other_establishment_forbidden
    """
    est_a = fx.create_establishment(api, name="V4 Plant A", species_classes=["CATTLE"])
    est_b = fx.create_establishment(api, name="V4 Plant B", species_classes=["SWINE"])
    inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])
    record = fx.issue_nr(api, est_a["id"], inspector["id"], regulation_family="SANITATION",
                         description="nr on A")

    # EstablishmentManager of B answers a record owned by A: role permitted on
    # the endpoint, but the ownership pin fails.
    resp = api.respond_to_nr(
        record["id"],
        f.nr_response_payload("B tries to answer for A"),
        make_establishment_manager_headers(est_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    stored = fx.get_nr(api, record["id"])
    assert stored["status"] == "OPEN"
    assert stored["response_text"] is None


def test_future_collected_at_on_sample_returns_422(api):
    """PRD §2.4: "Wherever a workflow below says a timestamp "must not be after
    the logical clock," or that a count is taken "within the trailing N days,"
    the comparison instant is this logical clock. An `observed_at`,
    `collected_at`, or `checked_at` that lies after the logical clock is
    rejected with `ERR_FUTURE_OBSERVATION` (HTTP 422)."

    Design: Corner/validations/future_collected_at_on_sample_returns_422
    """
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    base = fx.create_granted_establishment(api, species_classes=["POULTRY"], name="V6 Plant")
    est_id = base["establishment"]["id"]
    inspector = fx.create_inspector(api, species_qualifications=["POULTRY"])

    # One second past the logical clock.
    future = api.create_pathogen_sample(
        f.pathogen_sample_payload(est_id, inspector["id"], pathogen="SALMONELLA",
                                  collected_at="2026-09-01T00:00:01Z"),
        make_inspector_headers(inspector["id"]),
    )
    validate_error(future, ApiErrorId.ERR_FUTURE_OBSERVATION)

    # Exactly at the logical clock: not "after", so accepted.
    at_clock = api.create_pathogen_sample(
        f.pathogen_sample_payload(est_id, inspector["id"], pathogen="SALMONELLA",
                                  collected_at="2026-09-01T00:00:00Z"),
        make_inspector_headers(inspector["id"]),
    )
    data = validate_success(at_clock, 201)
    assert data["result"] == "PENDING"


def test_satisfaction_of_temporal_rule_lets_valid_nr_pass(api):
    """PRD §3.3: "The record is born `OPEN`, with `issued_at` stamped from the
    logical clock."
    PRD §3.3: "When `shift_window_id` is supplied, the referenced window must
    belong to the same establishment as the record; a cross-establishment link
    is rejected with `ERR_SHIFT_WINDOW_MISMATCH` (HTTP 422)."

    Design: Corner/validations/satisfaction_of_temporal_rule_lets_valid_nr_pass
    """
    base = fx.setup_granted_with_window(api, species_classes=["CATTLE"], name="V7 Plant")
    est_id = base["establishment"]["id"]
    inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])

    resp = api.create_noncompliance_record(
        f.nr_payload(
            est_id, inspector["id"], regulation_family="SANITATION",
            description="properly linked nr", observed_at="2026-08-31T06:00:00Z",
            shift_window_id=base["window"]["id"],
        ),
        make_inspector_headers(inspector["id"]),
    )

    data = validate_success(resp, 201)
    assert data["status"] == "OPEN"
    assert data["shift_window_id"] == base["window"]["id"]
    assert_instant(data["issued_at"], CLOCK_START_ISO, "issued_at stamped from the logical clock")
