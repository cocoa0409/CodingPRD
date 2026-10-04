"""Privacy directives: windows, supersession, gating, and student OCC."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated,
    advance_clock, setup_uploaded_file, setup_vetted_requester,
    place_directive, get_student_version, create_directive_payload,
    create_verification_request_payload, make_requester_headers,
)

OPS = TEST_USERS["ops_headers"]


def test_directive_create_defaults_indefinite_window(api):
    """PRD section 3.8: "Placing a directive names the `directive_type` —
    `FULL_BLOCK`, `DIRECTORY_BLOCK`, or `RESEARCH_OPT_OUT` — an
    `effective_from` marking the inclusive window start, an optional
    `effective_to` marking the exclusive window end (absent means
    indefinite)".
    PRD section 3.8: "A directive is `ACTIVE` from creation".

    Design: Corner/entities/directive_create_defaults_indefinite_window
    """
    ctx = setup_uploaded_file()
    student_id = ctx["entries"][0]["student_id"]
    directive = place_directive(student_id, directive_type="FULL_BLOCK")
    assert directive["status"] == "ACTIVE"
    assert directive["effective_to"] is None, "absent means indefinite"
    data, meta = validate_paginated(
        api_client.list_privacy_directives(student_id, OPS),
    )
    assert meta["total_count"] == 1


def test_directive_same_type_supersession(api):
    """PRD section 3.8: "Creating a new directive of the same type for the
    same student supersedes the prior `ACTIVE` one, moving it `ACTIVE` →
    `SUPERSEDED`, and the student record's `version` increments as part of
    that create mutation."

    Design: Corner/state_machines/directive_same_type_supersession
    """
    ctx = setup_uploaded_file()
    student_id = ctx["entries"][0]["student_id"]
    v1 = get_student_version(student_id)
    assert v1 == 1
    d1 = validate_success(api_client.create_privacy_directive(
        student_id, create_directive_payload(v1), OPS,
    ), 201)
    v2 = get_student_version(student_id)
    assert v2 == 2
    d2 = validate_success(api_client.create_privacy_directive(
        student_id,
        create_directive_payload(v2, effective_from="2026-06-01"),
        OPS,
    ), 201)
    v3 = get_student_version(student_id)
    assert v3 == 3
    data, _m = validate_paginated(
        api_client.list_privacy_directives(student_id, OPS),
    )
    assert data[0]["status"] == "SUPERSEDED", "the older same-type directive"
    assert data[1]["status"] == "ACTIVE", "the newer directive wins"


def test_directive_expiry_relaxes_privacy_gate(api):
    """PRD section 3.8: "When the clock reaches a directive's
    `effective_to`, the directive moves `ACTIVE` → `EXPIRED`."
    PRD section 3.8: "A directive gates only while it is `ACTIVE` and its
    window actually covers the current instant: `effective_from` on or
    before now, and `effective_to` either absent or strictly after now."

    Design: Corner/state_machines/directive_expiry_relaxes_privacy_gate
    """
    ctx = setup_uploaded_file()
    student_id = ctx["entries"][0]["student_id"]
    rq = setup_vetted_requester(credit=100000)
    place_directive(
        student_id, directive_type="DIRECTORY_BLOCK",
        effective_from="2026-01-01", effective_to="2026-12-01",
    )
    blocked = api_client.create_verification_request(
        create_verification_request_payload(
            student_id, ctx["inst_id"], requester_id=rq["id"],
        ),
        make_requester_headers(rq["id"]),
    )
    validate_error(blocked, ApiErrorId.ERR_PRIVACY_BLOCKED)
    advance_clock("2026-12-01T00:00:00Z")
    data, _m = validate_paginated(
        api_client.list_privacy_directives(student_id, OPS),
    )
    assert data[0]["status"] == "EXPIRED", "now 2026-12-01 >= effective_to"
    allowed = api_client.create_verification_request(
        create_verification_request_payload(
            student_id, ctx["inst_id"], requester_id=rq["id"],
        ),
        make_requester_headers(rq["id"]),
    )
    assert validate_success(allowed, 201)["status"] == "QUOTED"


def test_directive_window_must_be_strictly_positive(api):
    """PRD section 3.8: "The window itself must be non-empty —
    `effective_to`, when present, strictly after `effective_from` —
    otherwise `ERR_DIRECTIVE_WINDOW_INVALID` (HTTP 422)."

    Design: Corner/validations/directive_window_must_be_strictly_positive
    """
    ctx = setup_uploaded_file()
    student_id = ctx["entries"][0]["student_id"]
    version = get_student_version(student_id)
    resp = api_client.create_privacy_directive(
        student_id,
        create_directive_payload(
            version, effective_from="2026-06-01", effective_to="2026-06-01",
        ),
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_DIRECTIVE_WINDOW_INVALID)
    assert get_student_version(student_id) == version, (
        "no mutation landed on rejection"
    )


def test_occ_stale_student_version_rejected(api):
    """PRD section 2.6: "Placing a privacy directive on a student record
    requires a non-optional `expected_student_version` field carrying the
    student record's `version` as last observed by the client. A same-type
    directive create legitimately supersedes the prior `ACTIVE` directive
    under the privacy rules of §3.8, so the client must present the student
    version it based the decision on; if the record's current `version` no
    longer matches — because another directive create or a standing update
    landed in between — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/complexity_layers/occ_stale_student_version_rejected
    """
    ctx = setup_uploaded_file()
    student_id = ctx["entries"][0]["student_id"]
    observed = get_student_version(student_id)
    assert observed == 1
    first = validate_success(api_client.create_privacy_directive(
        student_id, create_directive_payload(observed), OPS,
    ), 201)
    assert first["status"] == "ACTIVE"
    stale = api_client.create_privacy_directive(
        student_id,
        create_directive_payload(observed, directive_type="RESEARCH_OPT_OUT"),
        OPS,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert get_student_version(student_id) == 2, (
        "exactly one mutation landed"
    )


def test_err_student_not_found(api):
    """PRD section 3.8: "A learner reads their own student record and places
    directives only on it — a path or body `student_id` other than the
    caller's own is rejected with `ERR_UNAUTHORIZED`, and an unknown student
    with `ERR_STUDENT_NOT_FOUND`."

    Design: Corner/errors/err_student_not_found
    """
    ctx = setup_uploaded_file()
    student_id = ctx["entries"][0]["student_id"]
    version = get_student_version(student_id)
    resp = api_client.create_privacy_directive(
        NON_EXISTENT_UUID, create_directive_payload(version), OPS,
    )
    validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_FOUND)
