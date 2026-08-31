"""Submission intake, the turnaround budget and the release-form gate."""

from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    assert_release_form,
    assert_submission,
    clear_intake,
    create_property,
    create_submission,
    create_unsolicited_submission,
    execute_release_form,
    fetch_release_form,
    fetch_submission,
    is_valid_uuid,
    open_release_form,
    send_release_form,
    set_clock,
    setup_cleared_submission,
    validate_error,
    validate_paginated,
    validate_success,
    EDITOR_ASSIGN,
    SUBMITTER,
)


def test_submission_records_clock_and_starts_in_received(api):
    """PRD 3.2: "The moment the submission is logged, the logical clock is
    stamped into `received_at`, the submission enters `RECEIVED` status, and its
    `decision` is set to `PENDING`."
    PRD 2.4: "Every resource is identified by an `id` that the server mints as a
    UUID. Identifiers carry no type prefix and are never supplied by the client."

    Design: Corner/entities/create_submission_system_fields_input_ignored
    """
    set_clock("2026-09-01T00:00:00Z")
    prop = create_property(genre="COMEDY", title="System Fields")

    resp = api.create_submission(
        {
            "property_id": prop["id"],
            "submitting_agency": "Indie Lit Co",
            "submitter_contact_email": "x@indie.example",
            "submitted_via": "MANAGER",
            "id": "11111111-1111-4111-8111-111111111111",
            "received_at": "1999-01-01T00:00:00Z",
            "status": "TRACKED",
            "release_form_required": False,
        },
        SUBMITTER,
    )
    data = validate_success(resp, 201)
    assert_submission(data)

    assert data["id"] != "11111111-1111-4111-8111-111111111111", (
        "a client-supplied id must be ignored"
    )
    assert is_valid_uuid(data["id"]) and ":" not in data["id"] and "_" not in data["id"]
    assert_instant_equals(data["received_at"], "2026-09-01T00:00:00Z", "received_at")
    assert data["status"] == "RECEIVED"
    assert data["release_form_required"] is True, (
        "release_form_required is derived, not accepted from the client"
    )
    assert data["version"] == 1


def test_submission_priority_flag_defaults_to_standard_seventy_two_hours(api):
    """PRD 3.2: "An optional `priority_flag` of `RUSH`, `STANDARD` or `BACKLOG`
    defaults to `STANDARD`."
    PRD 3.2: "The `coverage_due_at` instant is the `received_at` instant advanced
    by a turnaround budget selected by `priority_flag`: one full day for `RUSH`,
    three days for `STANDARD`, and a full week for `BACKLOG` — that is, 24, 72 and
    168 hours respectively."

    Design: Corner/entities/submission_priority_flag_defaults_to_standard_seventy_two_hours
    """
    set_clock("2026-09-01T00:00:00Z")
    prop = create_property(
        genre="FAMILY", title="Default Priority", material_type="BOOK"
    )

    resp = api.create_submission(
        {
            "property_id": prop["id"],
            "submitting_agency": "GERSH",
            "submitter_contact_email": "lit@gersh.example",
            "submitted_via": "AGENCY",
        },
        SUBMITTER,
    )
    data = validate_success(resp, 201)

    assert data["priority_flag"] == "STANDARD"
    assert_instant_equals(data["received_at"], "2026-09-01T00:00:00Z", "received_at")
    assert_instant_equals(
        data["coverage_due_at"], "2026-09-04T00:00:00Z", "coverage_due_at"
    )
    assert data["status"] == "RECEIVED"
    assert data["decision"] == "PENDING"


def test_coverage_due_at_rush_priority_applies_twenty_four_hours(api):
    """PRD 3.2: "The `coverage_due_at` instant is the `received_at` instant advanced
    by a turnaround budget selected by `priority_flag`: one full day for `RUSH`,
    three days for `STANDARD`, and a full week for `BACKLOG` — that is, 24, 72 and
    168 hours respectively."

    Design: Corner/calculations/coverage_due_at_rush_priority_applies_twenty_four_hours
    """
    set_clock("2026-09-01T00:00:00Z")
    prop = create_property(genre="THRILLER", title="Overnight")

    backlog = create_submission(
        prop["id"],
        submitting_agency="WME",
        submitter_contact_email="lit@wme.example",
        priority_flag="BACKLOG",
    )
    rush = create_submission(
        prop["id"],
        submitting_agency="WME",
        submitter_contact_email="lit@wme.example",
        priority_flag="RUSH",
    )

    assert_instant_equals(
        rush["coverage_due_at"], "2026-09-02T00:00:00Z", "RUSH coverage_due_at"
    )
    assert_instant_equals(
        backlog["coverage_due_at"], "2026-09-08T00:00:00Z", "BACKLOG coverage_due_at"
    )


def test_release_form_required_true_for_non_signatory_agency(api):
    """PRD 3.2: "A release form is required when the submission arrived through the
    `UNSOLICITED` channel, or when the submitting agency is not one of the five
    signatory agencies the studio has a standing submission agreement with — `CAA`,
    `WME`, `UTA`, `GERSH` and `APA`."

    Design: Corner/calculations/release_form_required_true_for_non_signatory_agency
    """
    set_clock("2026-09-01T00:00:00Z")
    prop = create_property(genre="DRAMA", title="Small Shop")

    signatory = create_submission(
        prop["id"], submitting_agency="CAA", submitter_contact_email="desk@caa.example"
    )
    indie = create_submission(
        prop["id"],
        submitting_agency="Indie Lit Co",
        submitter_contact_email="hello@indie.example",
    )

    assert signatory["release_form_required"] is False
    assert indie["release_form_required"] is True, (
        "an AGENCY submission from a non-signatory still requires a release"
    )
    assert indie["status"] == "RECEIVED"


def test_create_submission_missing_required_field_returns_invalid_request(api):
    """PRD 2.6: "Every required input field is present and carries its declared JSON
    type, or `ERR_INVALID_REQUEST` (400)."
    PRD 3.2: "Either the submitting party itself or a story editor logs one, naming
    the `property_id` of the material, the `submitting_agency` it came through, a
    `submitter_contact_email` for correspondence, and the `submitted_via` channel —
    one of `AGENCY`, `MANAGER`, `ATTORNEY`, `UNSOLICITED` or `INTERNAL`."

    Design: Corner/entities/create_submission_missing_required_field_returns_invalid_request
    """
    set_clock("2026-09-01T00:00:00Z")
    prop = create_property(genre="DRAMA", title="Missing Field")

    resp = api.create_submission(
        {
            "property_id": prop["id"],
            "submitting_agency": "CAA",
            "submitter_contact_email": "a@caa.example",
        },
        SUBMITTER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(
        api.list_submissions(EDITOR_ASSIGN, {"property_id": prop["id"]})
    )
    assert meta["total_count"] == 0, "the rejected submission must not persist"


def test_create_submission_with_unknown_property_id_returns_not_found(api):
    """PRD 2.6: "Every foreign-key identifier supplied in a request body must resolve
    to an existing row — `property_id`, `option_agreement_id`, `project_id`,
    `writer_id`, `reader_id` and `supersedes_document_id` — failing with the
    corresponding not-found code (`ERR_PROPERTY_NOT_FOUND`, `ERR_OPTION_NOT_FOUND`,
    `ERR_PROJECT_NOT_FOUND`, `ERR_WRITER_NOT_FOUND`, `ERR_READER_NOT_FOUND`,
    `ERR_DOCUMENT_NOT_FOUND`) at HTTP 404."

    Design: Corner/entities/create_submission_with_unknown_property_id_returns_not_found
    """
    set_clock("2026-09-01T00:00:00Z")

    resp = api.create_submission(
        {
            "property_id": "00000000-0000-4000-8000-0000000000ff",
            "submitting_agency": "CAA",
            "submitter_contact_email": "desk@caa.example",
            "submitted_via": "AGENCY",
        },
        SUBMITTER,
    )
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND, 404)


def test_list_submissions_returns_pagination_envelope(api):
    """PRD 2.3: "List responses populate four pagination fields inside `meta`:
    `limit` and `offset` echo the effective values used for the page, `total_count`
    reports how many rows match the filters before the page window is applied, and
    `has_more` is true when rows remain beyond the current window."

    Design: Corner/entities/list_submissions_returns_pagination_envelope
    """
    set_clock("2026-09-01T00:00:00Z")
    prop = create_property(genre="DRAMA", title="Three Submissions")
    for agency, email in (
        ("CAA", "a@caa.example"),
        ("WME", "b@wme.example"),
        ("UTA", "c@uta.example"),
    ):
        create_submission(
            prop["id"], submitting_agency=agency, submitter_contact_email=email
        )

    resp = api.list_submissions(
        EDITOR_ASSIGN, {"property_id": prop["id"], "limit": 2, "offset": 1}
    )
    rows, meta = validate_paginated(resp)

    assert resp.json()["response_type"] == "array"
    assert len(rows) == 2, f"Expected a 2-row page, got {len(rows)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is False, "rows 2 and 3 exhaust a 3-row population"
    assert meta["limit"] == 2
    assert meta["offset"] == 1


def test_release_form_opens_in_required_and_send_moves_it_to_sent(api):
    """PRD 3.2: "Opening a release form is only declared from `RECEIVED` and only
    when the submission's `release_form_required` is true and no release form already
    exists on that submission in `REQUIRED`, `SENT`, `EXECUTED` or `WAIVED` status;
    the new form is created in `REQUIRED` status and the submission advances
    `RECEIVED → RELEASE_PENDING`."
    PRD 3.2: "A story editor sends the form, taking it `REQUIRED → SENT`, which is
    admissible only while the logical clock is at or before `expires_at`."

    Design: Corner/state_machines/release_form_initial_state_is_required_and_send_moves_to_sent
    """
    set_clock("2026-09-01T00:00:00Z")
    prop = create_property(genre="COMEDY", title="Paper Trail")
    submission = create_unsolicited_submission(prop["id"])
    form = open_release_form(submission["id"], expires_at="2026-10-01T00:00:00Z")

    assert form["status"] == "REQUIRED"
    assert fetch_submission(submission["id"])["status"] == "RELEASE_PENDING"

    resp = api.send_release_form(form["id"], EDITOR_ASSIGN)
    data = validate_success(resp, 200)
    assert_release_form(data)

    assert data["status"] == "SENT"
    assert data["signed_at"] is None
    assert_instant_equals(data["expires_at"], "2026-10-01T00:00:00Z", "expires_at")
    assert fetch_submission(submission["id"])["status"] == "RELEASE_PENDING"


def test_execute_release_form_twice_returns_invalid_state(api):
    """PRD 3.2: "The submitting party then executes it by supplying a `signer_name`;
    execution is declared only from `SENT`, only while the logical clock is at or
    before `expires_at`, stamps the clock into `signed_at`, and carries the parent
    submission `RELEASE_PENDING → INTAKE_CLEARED`."
    PRD 2.6: "The target resource sits in a state from which the requested transition
    is declared, or `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/execute_release_form_twice_returns_invalid_state
    """
    set_clock("2026-09-01T00:00:00Z")
    prop = create_property(genre="HORROR", title="Signed Once")
    submission = create_unsolicited_submission(
        prop["id"], submitter_contact_email="nf@mail.example"
    )
    form = open_release_form(submission["id"], expires_at="2026-10-01T00:00:00Z")
    send_release_form(form["id"])
    execute_release_form(form["id"], signer_name="N. Ferrer")

    resp = api.execute_release_form(
        form["id"], {"signer_name": "Someone Else"}, SUBMITTER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    stored = fetch_release_form(form["id"])
    assert stored["status"] == "EXECUTED"
    assert stored["signer_name"] == "N. Ferrer", (
        "the second attempt must not overwrite the first signature"
    )
    assert_instant_equals(stored["signed_at"], "2026-09-01T00:00:00Z", "signed_at")
    assert fetch_submission(submission["id"])["status"] == "INTAKE_CLEARED"


def test_waive_release_form_clears_intake_on_the_parent_submission(api):
    """PRD 3.2: "Alternatively a story editor waives the requirement outright by
    supplying a `waiver_reason`; waiving is admissible from either `REQUIRED` or
    `SENT`, and likewise carries the submission `RELEASE_PENDING → INTAKE_CLEARED`."

    Design: Corner/state_machines/waive_release_form_clears_intake_cross_entity
    """
    set_clock("2026-09-01T00:00:00Z")
    prop = create_property(
        genre="DOCUMENTARY", title="Legal Says Fine", material_type="ARTICLE"
    )
    submission = create_unsolicited_submission(
        prop["id"], submitter_contact_email="ob@mail.example"
    )
    form = open_release_form(submission["id"], expires_at="2026-10-01T00:00:00Z")

    resp = api.waive_release_form(
        form["id"],
        {"waiver_reason": "Material already in the public domain."},
        EDITOR_ASSIGN,
    )
    data = validate_success(resp, 200)

    assert data["status"] == "WAIVED"
    assert data["waiver_reason"] == "Material already in the public domain."
    assert data["signed_at"] is None, "a waiver is not a signature"
    assert fetch_submission(submission["id"])["status"] == "INTAKE_CLEARED"


def test_clear_intake_on_release_pending_submission_returns_invalid_state(api):
    """PRD 3.2: "Clearing intake is declared *only* from `RECEIVED`; attempting it on
    a submission already sitting in `RELEASE_PENDING` is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/clear_intake_on_release_pending_submission_returns_invalid_state
    """
    set_clock("2026-09-01T00:00:00Z")
    prop = create_property(genre="THRILLER", title="Over The Transom")
    submission = create_unsolicited_submission(
        prop["id"], submitter_contact_email="kd@mail.example"
    )
    form = open_release_form(submission["id"], expires_at="2026-10-01T00:00:00Z")

    resp = api.clear_intake(submission["id"], EDITOR_ASSIGN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    stored = fetch_submission(submission["id"])
    assert stored["status"] == "RELEASE_PENDING"
    assert stored["release_form_required"] is True
    assert fetch_release_form(form["id"])["status"] == "REQUIRED"


def test_clear_intake_without_executed_release_returns_release_form_required(api):
    """PRD 3.2: "But an unsolicited submission that requires a release and has none in
    `EXECUTED` or `WAIVED` status is refused at this step with
    `ERR_RELEASE_FORM_REQUIRED` rather than `ERR_INVALID_STATE` — the difference
    matters, because it tells the editor to chase the paper rather than to look for a
    different state."

    Design: Corner/validations/clear_intake_without_executed_release_returns_release_form_required
    """
    set_clock("2026-09-01T00:00:00Z")
    prop = create_property(genre="DRAMA", title="Unsigned Release")
    signatory = create_submission(
        prop["id"], submitting_agency="CAA", submitter_contact_email="desk@caa.example"
    )
    clear_intake(signatory["id"])
    unsolicited = create_unsolicited_submission(
        prop["id"], submitter_contact_email="dw@mail.example"
    )

    resp = api.clear_intake(unsolicited["id"], EDITOR_ASSIGN)
    validate_error(resp, ApiErrorId.ERR_RELEASE_FORM_REQUIRED, 409)

    stored = fetch_submission(unsolicited["id"])
    assert stored["release_form_required"] is True
    assert stored["status"] == "RECEIVED", (
        "the state check passed; only the release-form requirement failed"
    )
    assert fetch_submission(signatory["id"])["release_form_required"] is False
    assert fetch_submission(signatory["id"])["status"] == "INTAKE_CLEARED"

    _, meta = validate_paginated(
        api.list_submission_release_forms(unsolicited["id"], EDITOR_ASSIGN)
    )
    assert meta["total_count"] == 0


def test_withdraw_already_withdrawn_submission_returns_terminal_state(api):
    """PRD 3.2: "A submission already in `PASSED`, `IN_DEVELOPMENT` or `WITHDRAWN` is
    refused with `ERR_TERMINAL_STATE`."
    PRD 3.2: "The `reason` is stored as `withdrawal_reason`."

    Design: Corner/state_machines/withdraw_already_withdrawn_submission_returns_terminal_state
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_cleared_submission(
        genre="DRAMA", title="Pulled", submitting_agency="APA",
        submitter_contact_email="lit@apa.example",
    )
    submission_id = ctx["submission"]["id"]
    validate_success(
        api.withdraw_submission(submission_id, {"reason": "Client pulled it."}, SUBMITTER)
    )

    resp = api.withdraw_submission(
        submission_id, {"reason": "Second attempt."}, SUBMITTER
    )
    validate_error(resp, ApiErrorId.ERR_TERMINAL_STATE, 409)

    stored = fetch_submission(submission_id)
    assert stored["status"] == "WITHDRAWN"
    assert stored["withdrawal_reason"] == "Client pulled it."
