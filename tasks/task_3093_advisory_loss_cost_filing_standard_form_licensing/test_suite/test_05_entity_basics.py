"""Entity basics: creation defaults, retrieval round-trips, pagination, and
input validation on the insurer and submission resources (PRD §2.2, §2.3,
§2.5, §2.6, §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_insurer_payload,
    create_statistical_plan_payload,
    create_submission_payload,
    get_success_data,
    make_active_plan,
    make_insurer,
    make_submission,
    setup_insurer_with_active_plan,
    validate_error,
    validate_paginated,
    validate_success,
    make_insurer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ACTUARY = TEST_USERS["actuary_headers"]


def test_insurer_create_returns_201_with_system_defaults(api):
    """PRD §3.1: "A `BureauAdmin` onboards a member insurer by registering its
    bureau-assigned `insurer_code` (unique across the bureau) and
    `legal_name`. A new insurer begins life with `insurer_status` `ACTIVE` and
    a perfect statistical reporting quality: `quality_score_bps` starts at
    10000, expressed in basis points on a 0 to 10000 scale."
    PRD §2.5: "Every primary resource — `MemberInsurer`, `StatisticalPlan`,
    `StatisticalSubmission`, `LossCostFiling`, `StateDepartment`,
    `LossCostMultiplierAdoption`, `PolicyForm`, `FormVariant`, `Circular`,
    `LicenseAgreement`, `ClassPlan`, and `ClassPlanRevision` — carries four
    system-managed fields: `id`, a server-minted UUID with no type prefix;
    `created_at`, an ISO 8601 UTC timestamp with three fractional digits
    captured at creation; `updated_at`, an ISO 8601 UTC timestamp refreshed on
    every mutation; and `version`, an integer starting at creation that
    increments by exactly 1 on every mutation of that resource."

    Design: Corner/entities/insurer_create_returns_201_with_system_defaults
    """
    resp = api.create_insurer(
        {"insurer_code": "INS-001", "legal_name": "First Member Mutual"}, ADMIN
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]
    data = body["data"]
    assert data["insurer_status"] == "ACTIVE"
    assert data["quality_score_bps"] == 10000
    assert data["version"] == 1
    assert data["id"] and data["created_at"] and data["updated_at"]


def test_insurer_get_round_trips_and_unknown_id_returns_not_found(api):
    """PRD §2.6: "Requests that target nested resources validate path segments
    left to right: each identifier in the path must correspond to an existing
    resource, and the first missing identifier produces `ERR_NOT_FOUND` (HTTP
    404) before later segments are examined."
    PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format: ... `response_type`: `error`, `data` carries `error_id`
    and `message`."

    Design: Corner/entities/insurer_get_round_trips_and_unknown_id_returns_not_found
    """
    insurer = make_insurer()
    fetched = validate_success(api.get_insurer(insurer["id"], ACTUARY))
    assert fetched["id"] == insurer["id"]
    assert fetched["insurer_code"] == insurer["insurer_code"]
    resp = api.get_insurer(NON_EXISTENT_UUID, ACTUARY)
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert err["error_id"] == ApiErrorId.ERR_NOT_FOUND
    assert err["message"]


def test_submissions_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "List endpoints accept the query parameters `limit` and
    `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of
    100; `offset` defaults to 0. All list endpoints return resources sorted by
    `created_at` in ascending order. List responses include the pagination
    fields `limit`, `offset`, `total_count`, and `has_more` in the `meta`
    object of the response envelope."
    PRD §3.2: "Submissions can be listed filtered by `insurer_id`, `plan_id`,
    or `submission_status`."

    Design: Corner/entities/submissions_list_paginates_with_total_count_and_has_more
    """
    insurer, plan = setup_insurer_with_active_plan()
    for i in range(3):
        make_submission(
            insurer["id"], plan["id"],
            period_start=f"2025-0{i + 1}-01T00:00:00Z",
            period_end=f"2025-0{i + 2}-01T00:00:00Z",
        )
    rows, meta = validate_paginated(
        api.list_submissions(ADMIN, params={"insurer_id": insurer["id"], "limit": 2, "offset": 0})
    )
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    rows2, meta2 = validate_paginated(
        api.list_submissions(ADMIN, params={"insurer_id": insurer["id"], "limit": 2, "offset": 2})
    )
    assert len(rows2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    rows3, meta3 = validate_paginated(api.list_submissions(ADMIN))
    assert len(rows3) == 3
    assert meta3["limit"] == 10
    assert meta3["offset"] == 0


def test_submission_create_missing_record_count_returns_invalid_request(api):
    """PRD §2.7: "**General request shape.** Required input fields must be
    present, enum values must fall in their declared sets, and numeric ranges
    (such as `record_count` at least 1 and `written_premium_cents` at least 0)
    must hold; otherwise `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.2: "the `record_count` of statistical records in the batch (at
    least 1), and the `written_premium_cents` total (at least 0)."

    Design: Corner/entities/submission_create_missing_record_count_returns_invalid_request
    """
    insurer, plan = setup_insurer_with_active_plan()
    payload = create_submission_payload(insurer["id"], plan["id"])
    del payload["record_count"]
    resp = api.create_submission(payload, make_insurer_headers(insurer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows, meta = validate_paginated(
        api.list_submissions(ADMIN, params={"insurer_id": insurer["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_filing_create_without_supersede_starts_at_version_1_draft(api):
    """PRD §3.3: "A fresh filing starts in `DRAFT` with `filing_version` 1 and
    no superseding parent (`supersedes_filing_id` is null on version 1)."
    PRD §3.3: "The creation payload may optionally include `review_notes` (the
    actuarial review narrative, nullable), an `effective_date` (the requested
    effective date of the advisory loss costs, which stays unset until the
    filing is filed), and — for resubmissions only — a `supersedes_filing_id`
    together with `expected_superseded_version`."

    Design: Corner/entities/filing_create_without_supersede_starts_at_version_1_draft
    """
    resp = api.create_filing(
        {
            "filing_code": "LC-CA-CP-001",
            "state_code": "CA",
            "line_of_business": "COMMERCIAL_PROPERTY",
            "trend_selection": "LINEAR_LEAST_SQUARES",
            "effective_date": "2027-01-01T00:00:00Z",
        },
        ADMIN,
    )
    assert resp.status_code == 201
    data = validate_success(resp, expected_status=201)
    assert data["filing_version"] == 1
    assert data["supersedes_filing_id"] is None
    assert data["review_notes"] is None
    assert data["filing_status"] == "DRAFT"
    assert data["filed_at"] is None
    assert data["last_submitted_by_admin_id"] is None


def test_accepted_record_count_computed_at_disposition(api):
    """PRD §3.2: "When the administrator disposes a submission, the server
    first computes three counters from the finding rows at that moment:
    `error_finding_count` (findings of severity `ERROR`),
    `warning_finding_count` (findings of severity `WARNING`), and
    `accepted_record_count` (the `record_count` minus the number of
    `ERROR`-severity findings)."
    PRD §3.2: "with at least one error finding it is `REJECTED`."

    Design: Corner/entities/accepted_record_count_computed_at_disposition
    """
    insurer, plan = setup_insurer_with_active_plan()
    sub = make_submission(insurer["id"], plan["id"], record_count=10)
    from test_helpers import add_finding, begin_edit, dispose
    begin_edit(sub["id"])
    add_finding(sub["id"], severity="ERROR", edit_code="E-200", affected_records=2)
    disposed = dispose(sub["id"])
    assert disposed["submission_status"] == "REJECTED"
    assert disposed["error_finding_count"] == 1
    assert disposed["warning_finding_count"] == 0
    assert disposed["accepted_record_count"] == 9


def test_submission_create_with_system_fields_in_payload_ignored_input(api):
    """PRD §2.5: "Every primary resource — `MemberInsurer`, `StatisticalPlan`,
    `StatisticalSubmission`, `LossCostFiling`, `StateDepartment`,
    `LossCostMultiplierAdoption`, `PolicyForm`, `FormVariant`, `Circular`,
    `LicenseAgreement`, `ClassPlan`, and `ClassPlanRevision` — carries four
    system-managed fields: `id`, a server-minted UUID with no type prefix;
    `created_at`, an ISO 8601 UTC timestamp with three fractional digits
    captured at creation; `updated_at`, an ISO 8601 UTC timestamp refreshed on
    every mutation; and `version`, an integer starting at creation that
    increments by exactly 1 on every mutation of that resource."
    PRD §3.2: "A new submission begins in `RECEIVED` status."

    Design: Corner/entities/submission_create_with_system_fields_in_payload_ignored_input
    """
    insurer, plan = setup_insurer_with_active_plan()
    payload = create_submission_payload(
        insurer["id"], plan["id"], record_count=5, written_premium_cents=50000
    )
    payload["submission_status"] = "ACCEPTED"
    payload["version"] = 42
    resp = api.create_submission(payload, make_insurer_headers(insurer["id"]))
    assert resp.status_code == 201
    data = validate_success(resp, expected_status=201)
    assert data["submission_status"] == "RECEIVED"
    assert data["version"] == 1


def test_finding_create_with_out_of_enum_severity_rejected(api):
    """PRD §2.7: "**General request shape.** Required input fields must be
    present, enum values must fall in their declared sets, and numeric ranges
    (such as `record_count` at least 1 and `written_premium_cents` at least 0)
    must hold; otherwise `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.2: "each finding is created as a `SubmissionEditFinding` carrying
    the owning `submission_id`, an `edit_code` (for example `E-101` for
    premium-below-minimum), a `severity` of either `ERROR` or `WARNING`, and
    the `affected_records` count (at least 1)."

    Design: Corner/entities/finding_create_with_out_of_enum_severity_rejected
    """
    from test_helpers import begin_edit
    insurer, plan = setup_insurer_with_active_plan()
    sub = make_submission(insurer["id"], plan["id"], record_count=5)
    begin_edit(sub["id"])
    resp = api.create_finding(
        sub["id"], {"edit_code": "E-X", "severity": "CRITICAL", "affected_records": 1}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows, meta = validate_paginated(api.list_findings(sub["id"], ADMIN))
    assert rows == []


def test_submission_create_body_fks_checked_in_input_order(api):
    """PRD §2.6: "The same discipline applies to foreign keys in request
    bodies: body references are validated in the order they are declared in
    the endpoint's input list — for example, on a statistical submission the
    `insurer_id` is checked before the `plan_id`, and on an adoption the
    `insurer_id` is checked before the `filing_id` — and the first dangling
    reference is rejected with `ERR_NOT_FOUND`."
    PRD §2.7: "**Body referential existence.** Body foreign keys must exist,
    validated in declared input order; otherwise `ERR_NOT_FOUND`."

    Design: Corner/entities/submission_create_body_fks_checked_in_input_order
    """
    insurer = make_insurer()
    plan = make_active_plan()
    # Unknown insurer (first FK in declared order) against a known plan.
    payload = create_submission_payload(NON_EXISTENT_UUID, plan["id"], record_count=5)
    resp = api.create_submission(payload, make_insurer_headers(NON_EXISTENT_UUID))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    # Sequential elimination: known insurer against an unknown plan.
    payload2 = create_submission_payload(insurer["id"], NON_EXISTENT_UUID, record_count=5)
    resp2 = api.create_submission(payload2, make_insurer_headers(insurer["id"]))
    validate_error(resp2, ApiErrorId.ERR_NOT_FOUND)
    rows, meta = validate_paginated(api.list_submissions(ADMIN))
    assert rows == []
