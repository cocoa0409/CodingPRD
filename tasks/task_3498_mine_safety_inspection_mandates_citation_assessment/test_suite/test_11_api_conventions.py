"""Cross-cutting API conventions (PRD §2.1, §2.2, §2.3, §2.5): authentication
and authorization tiers, cascade ordering between shape/existence checks, the
success/error envelopes, pagination defaults, the operating-mine requirement,
and ownership-scoped abatement.

Clock note: all readings are >= the startup reading 2026-09-01T00:00:00Z
(PRD §2.4).
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    abate_citation_payload,
    assert_system_timestamp,
    create_citation_payload,
    create_ido_payload,
    in_progress_inspection,
    issue_n_citations,
    make_inspector_headers,
    make_operator_rep_headers,
    refresh_citation,
    report_accident_payload,
    set_clock,
    setup_citation,
    setup_mine,
    setup_operator,
    setup_registry,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["admin_headers"]
_DM = TEST_USERS["district_manager_headers"]
_JUDGE = TEST_USERS["commission_judge_headers"]


def test_missing_auth_headers_rejected_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role string
    outside this declared set, is rejected with `ERR_UNAUTHENTICATED`."
    PRD §2.5 tier 1: "Both headers are present and the role is a declared role
    name; otherwise `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_rejected_unauthenticated
    """
    _operator, mine = setup_mine()
    # No X-User-ID / X-User-Role headers at all — refused at the first tier,
    # even on a read-only endpoint.
    resp = api.get_mine(mine["id"], {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_shape_error_precedes_existence_error(api):
    """PRD §2.5: "Every request is evaluated against an ordered cascade of
    validation tiers. When several checks would fail on the same request, the
    response reports the failure from the **earliest** tier; a request that
    fails an earlier tier never surfaces a later tier's error."
    PRD §2.5 tier 3: "Required fields are present, no undeclared fields appear,
    enum values fall inside their declared sets, and integer ranges hold
    (`persons_affected` at least 1, `miners_withdrawn_count` at least 0,
    `annual_tonnage_tons` at least 0); otherwise `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/validations/shape_error_precedes_existence_error
    """
    set_clock("2026-09-10T08:00:00Z")
    _operator, mine, i1 = setup_registry()
    payload = create_citation_payload(NON_EXISTENT_UUID, mine["id"])
    del payload["negligence"]  # required field missing AND bogus inspection FK
    resp = api.create_citation(payload, TEST_USERS["inspector_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_existence_error_precedes_state_error(api):
    """PRD §2.5 tier 4: "Path identifiers resolve left-to-right, then body
    foreign keys resolve (`operator_id`, `mine_id`, `inspector_id`,
    `cycle_id`, `accident_id`, `citation_id`, `new_inspector_id`); the first
    unresolvable identifier yields `ERR_NOT_FOUND` (HTTP 404)."
    PRD §2.5: "a request that fails an earlier tier never surfaces a later
    tier's error."

    Design: Corner/validations/existence_error_precedes_state_error
    """
    set_clock("2026-09-10T08:00:00Z")
    resp = api.complete_inspection(
        NON_EXISTENT_UUID, TEST_USERS["inspector_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_success_envelope_carries_meta_and_object_type(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC
    timestamp with three fractional digits."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/success_envelope_carries_meta_and_object_type
    """
    set_clock("2026-09-10T08:00:00Z")
    _operator, mine = setup_mine()
    resp = api.get_mine(mine["id"], TEST_USERS["inspector_headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert_system_timestamp(
        body["meta"]["api_request_timestamp"], "meta.api_request_timestamp"
    )
    assert body["data"]["mine_name"] == "Canyon No 1"


def test_error_envelope_carries_error_id_and_message(api):
    """PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/endpoints/error_envelope_carries_error_id_and_message
    """
    set_clock("2026-09-10T08:00:00Z")
    resp = api.get_mine(NON_EXISTENT_UUID, _ADMIN)
    assert resp.status_code == 404
    body = resp.json()
    assert body["response_type"] == "error"
    error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert error_data["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(error_data["message"], str) and error_data["message"].strip()
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_err_mine_not_active_on_accident_and_ido(api):
    """PRD §3.1: "an `IDLED` mine cannot accept an accident report or a new
    imminent-danger order (§3.5, §3.7)"
    PRD §3.5: "The mine must be `ACTIVE` — issuance at an `IDLED` mine is
    rejected with `ERR_MINE_NOT_ACTIVE`"
    PRD §3.7: "The mine must be `ACTIVE`, else `ERR_MINE_NOT_ACTIVE`."

    Design: Corner/errors/err_mine_not_active_on_accident_and_ido
    """
    set_clock("2026-09-10T08:00:00Z")
    operator, mine, i1 = setup_registry()
    validate_success(api.idle_mine(mine["id"], _ADMIN))
    assert api.get_mine(mine["id"], _ADMIN).json()["data"]["status"] == "IDLED"

    resp = api.report_accident(
        report_accident_payload(
            mine["id"], "2026-09-10T07:55:00Z",
            severity="NO_LOST_TIME",
            description="probe accident at idled mine",
        ),
        make_operator_rep_headers(operator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MINE_NOT_ACTIVE)

    resp = api.create_imminent_danger_order(
        create_ido_payload(mine["id"], hazard_description="probe order at idled mine"),
        make_inspector_headers(i1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MINE_NOT_ACTIVE)


def test_judge_cannot_issue_citations(api):
    """PRD §2.9: "District managers, who assign work, may never issue citations
    or decide contests; commission judges, who decide contests, may never
    inspect, issue, or approve plans."
    PRD §2.1: "A request whose role is declared but not permitted on the target
    endpoint is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/judge_cannot_issue_citations
    """
    set_clock("2026-09-10T08:00:00Z")
    _operator, mine, i1 = setup_registry()
    inspection = in_progress_inspection(mine, i1, kind="SPOT")
    resp = api.create_citation(
        create_citation_payload(inspection["id"], mine["id"]),
        _JUDGE,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    rows, meta = validate_paginated(
        api.list_citations(_DM, params={"mine_id": mine["id"]})
    )
    assert rows == [] and meta["total_count"] == 0


def test_operator_b_cannot_abate_operator_a_citation(api):
    """PRD §3.4: "An `OperatorRep` of the mine's operator reports abatement
    with an `abatement_note`, moving the axis from `OPEN` to `ABATED`, stamping
    `abated_at`, and incrementing the citation's `version`; a representative of
    any other operator is rejected with `ERR_OPERATOR_MISMATCH`."

    Design: Corner/rbac/operator_b_cannot_abate_operator_a_citation
    """
    set_clock("2026-09-10T08:00:00Z")
    bundle = setup_citation()
    rival = setup_operator(
        legal_name="Rival Resources", annual_tonnage_tons=500, home_district="D-12"
    )
    resp = api.abate_citation(
        bundle["citation"]["id"],
        abate_citation_payload(abatement_note="rival attempting abatement"),
        make_operator_rep_headers(rival["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OPERATOR_MISMATCH)
    assert refresh_citation(bundle["citation"]["id"])["abatement_status"] == "OPEN"


def test_pagination_defaults_applied_when_params_omitted(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The
    `offset` parameter sets the number of items skipped and defaults to 0.
    Paginated list responses carry `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/complexity_layers/pagination_defaults_applied_when_params_omitted
    """
    set_clock("2026-09-10T08:00:00Z")
    _operator, mine, i1 = setup_registry()
    inspection = in_progress_inspection(mine, i1, kind="SPOT")
    issue_n_citations(inspection, mine, i1, 3)

    # limit/offset omitted entirely: the declared defaults apply.
    rows, meta = validate_paginated(
        api.list_citations(_DM, params={"mine_id": mine["id"]})
    )
    assert len(rows) == 3
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
