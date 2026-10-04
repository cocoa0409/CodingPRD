"""Validation-ordering and error tests: auth pre-empts OCC, state pre-empts
re-evaluation, posture boundary, retention-run hold safety, budget supersession
ordering, OCC stale-version, trigger/tagging/404/RBAC validations."""
from test_helpers import (
    TEST_USERS,
    NON_EXISTENT_UUID,
    get_success_data,
    make_officer_headers,
    make_prosecutor_headers,
    make_records_officer_headers,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    create_budget_plan_payload,
    create_device_payload,
    create_officer_payload,
    create_recording_payload,
)
from test_helpers.fixtures import (
    create_agency,
    create_budget_plan,
    create_case,
    create_legal_hold,
    create_officer,
    refresh_agency,
    refresh_recording,
    run_retention,
    set_clock,
    setup_agency_with_policy,
    setup_agency_with_policy_and_officer,
    setup_closed_case_with_grant,
    setup_officer_with_device,
    upload_recording,
)
from test_helpers.test_users import (
    make_redaction_technician_headers,
    make_supervisor_headers,
)

ADMIN = TEST_USERS["agency_admin_headers"]
DC = TEST_USERS["device_coordinator_headers"]
RO = TEST_USERS["records_officer_headers"]


# ===========================================================================
# priority_pair_validation_conflict / missing_auth_beats_stale_case_version
# ===========================================================================

def test_missing_auth_headers_preempt_stale_version(api):
    """PRD §3.11: "Authentication comes first: missing or unrecognized identity
    headers fail with `ERR_UNAUTHENTICATED` before anything else is examined...
    and finally — last, so that all other causes of rejection surface first —
    the optimistic-concurrency check on share-grant creation
    (`ERR_STALE_VERSION`)."

    Design: Difficulty/priority_pair_validation_conflict/missing_auth_beats_stale_case_version
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_closed_case_with_grant()
    agency, case = ctx["agency"], ctx["case"]
    # no X-User-Role / X-User-ID headers AND a deliberately stale version
    resp = api.create_share_grant(
        agency["id"], case["id"],
        {"recipient_role": "PROSECUTOR", "recipient_email": "da@county.gov",
         "expected_case_version": case["version"] - 1},
        {},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_unauthenticated_share_grant_error_is_401_not_412(api):
    """PRD §2.1: "If either header is missing or the role value is not one of
    the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (401)."
    PRD §2.9: "If another writer has advanced the case's version since then —
    the check compares the supplied value against the case's current `version` —
    the request is rejected with `ERR_STALE_VERSION` (412)".

    Design: Difficulty/priority_pair_validation_conflict/missing_auth_beats_stale_case_version
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_closed_case_with_grant()
    agency, case = ctx["agency"], ctx["case"]
    resp = api.create_share_grant(
        agency["id"], case["id"],
        {"recipient_role": "PROSECUTOR", "recipient_email": "da@county.gov",
         "expected_case_version": case["version"] - 1},
        {},
    )
    assert resp.status_code == 401, (
        f"auth (401) pre-empts the OCC check (412); got {resp.status_code}"
    )
    body = resp.json()
    assert body["data"]["error_id"] == "ERR_UNAUTHENTICATED"


# ===========================================================================
# priority_pair_validation_conflict / state_error_beats_integrity_safety_on_terminal_case
# ===========================================================================

def test_second_submit_review_returns_invalid_state(api):
    """PRD §3.11: "Then state-machine admissibility: a transition attempted from
    the wrong state fails with `ERR_INVALID_STATE`... then the referential gates
    on officer and case lifecycles (`ERR_DEVICE_STILL_ASSIGNED`,
    `ERR_LEAD_CASES_OPEN`, `ERR_CASE_EMPTY`, `ERR_EVIDENCE_NOT_READY`,
    `ERR_REVIEWS_OUTSTANDING`)".

    Design: Difficulty/priority_pair_validation_conflict/state_error_beats_integrity_safety_on_terminal_case
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    rec = upload_recording(agency["id"], device, officer, category="INCIDENT")
    case = create_case(agency["id"], officer)
    from test_helpers.fixtures import link_evidence, submit_case, get_case
    link_evidence(agency["id"], case["id"], rec["id"], officer)
    submit_case(agency["id"], case["id"], officer)
    # second submit-review: the state precondition (OPEN) no longer holds
    resp = api.submit_case_review(agency["id"], case["id"],
                                  make_officer_headers(officer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    case_now = get_case(agency["id"], case["id"])
    assert case_now["status"] == "UNDER_REVIEW"


def test_submit_review_on_under_review_case_never_reports_evidence_errors(api):
    """PRD §3.8: "An `Officer` submits the case for review, but only when
    `evidence_count` is at least 1 — an empty case fails with `ERR_CASE_EMPTY`
    (409) — and every `LINKED` recording's `upload_status` is `ACTIVE` or
    `RETENTION_DUE`".
    PRD §3.11: "Then state-machine admissibility: a transition attempted from
    the wrong state fails with `ERR_INVALID_STATE`".

    Design: Difficulty/priority_pair_validation_conflict/state_error_beats_integrity_safety_on_terminal_case
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    rec = upload_recording(agency["id"], device, officer, category="INCIDENT")
    case = create_case(agency["id"], officer)
    from test_helpers.fixtures import link_evidence, submit_case
    link_evidence(agency["id"], case["id"], rec["id"], officer)
    submit_case(agency["id"], case["id"], officer)
    resp = api.submit_case_review(agency["id"], case["id"],
                                  make_officer_headers(officer["id"]))
    body = resp.json()
    assert resp.status_code == 409
    assert body["data"]["error_id"] == "ERR_INVALID_STATE", (
        f"state admissibility fires before evidence re-evaluation, got "
        f"{body['data']['error_id']}"
    )


# ===========================================================================
# boundary_precision_check / posture_strict_greater_than_at_exact_budget_equality
# ===========================================================================

def _setup_posture_boundary(api):
    set_clock("2026-09-01T00:00:00Z")
    agency, policy = setup_agency_with_policy()
    create_budget_plan(agency["id"], monthly_budget_cents=3000,
                       cost_per_gb_month_cents=1000, alert_threshold_pct=80,
                       effective_from_month="2026-01")
    officer, device = setup_officer_with_device(agency["id"])
    # Pin the clock past the latest recorded_at used below so no upload is
    # future-dated relative to the logical clock (PRD section 3.4).
    set_clock("2026-09-01T00:03:00Z")
    for i in range(3):
        upload_recording(agency["id"], device, officer,
                         recorded_at=f"2026-09-01T00:0{i}:00Z",
                         size_bytes=1073741824, category="INCIDENT")
    return agency, officer, device


def test_posture_at_exact_budget_equality_is_warning_not_over_budget(api):
    """PRD §3.7: "When the projection exceeds `monthly_budget_cents` — strictly
    greater — posture is `OVER_BUDGET`... A projection exactly equal to the
    budget stays `WARNING` (or `OK` if below the threshold) and never flips to
    `OVER_BUDGET`."

    Design: Difficulty/boundary_precision_check/posture_strict_greater_than_at_exact_budget_equality
    """
    agency, officer, device = _setup_posture_boundary(api)
    data = validate_success(api.get_budget_projection(agency["id"], RO))
    assert data["projection_month_cost_cents"] == 3000
    assert data["posture"] == "WARNING", (
        f"equality with the 3000 budget is NOT over: posture must be WARNING, "
        f"got {data['posture']}"
    )


def test_posture_flips_over_budget_one_byte_past_equality(api):
    """PRD §3.7: "When the projection exceeds `monthly_budget_cents` — strictly
    greater — posture is `OVER_BUDGET`."
    PRD §2.10: "Byte-to-gigabyte conversion treats 1 GB as exactly 1024 cubed
    bytes (1073741824 bytes)."

    Design: Difficulty/boundary_precision_check/posture_strict_greater_than_at_exact_budget_equality
    """
    agency, officer, device = _setup_posture_boundary(api)
    upload_recording(agency["id"], device, officer,
                     recorded_at="2026-09-01T00:03:00Z", size_bytes=1,
                     category="INCIDENT")
    data = validate_success(api.get_budget_projection(agency["id"], RO))
    # ceil((3 GiB + 1 byte) / GiB * 1000) == 3001 > 3000
    assert data["projection_month_cost_cents"] == 3001, (
        f"3 GiB + 1 byte at 1000 cents/GiB-month must project 3001, "
        f"got {data['projection_month_cost_cents']}"
    )
    assert data["posture"] == "OVER_BUDGET"


# ===========================================================================
# compensating_invariant / hold_place_release_preserves_purgeable_count
# ===========================================================================

def test_held_recording_skipped_by_retention_run(api):
    """PRD §3.5: "Then, in the same run, each `RETENTION_DUE` recording whose
    `legal_hold_count` is zero moves to `PURGED`; any recording under an active
    hold simply stays `RETENTION_DUE` and is counted as skipped rather than
    erroring."

    Design: Difficulty/compensating_invariant/hold_place_release_preserves_purgeable_count
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    rec = upload_recording(agency["id"], device, officer, size_bytes=1048576,
                           category="INCIDENT")
    set_clock("2027-03-20T00:00:00Z")
    hold = create_legal_hold(agency["id"], scope_type="RECORDING",
                             recording_id=rec["id"],
                             authority_reference="SUBP-2027-01")
    result = run_retention(agency["id"])
    assert result["purged"] == 0
    assert result["held_skipped"] == 1
    rec_now = refresh_recording(agency["id"], rec["id"])
    assert rec_now["upload_status"] == "RETENTION_DUE"


def test_release_then_rerun_purges_with_zero_net_drift(api):
    """PRD §3.10: "Releasing a hold — again a `RecordsOfficer` action — moves it
    `ACTIVE → RELEASED`, recomputes the counts of all covered recordings
    downward by one, writes a `HOLD_RELEASED` custody event on each, and makes
    any `RETENTION_DUE` recordings it was protecting purgeable in the next
    retention run."

    Design: Difficulty/compensating_invariant/hold_place_release_preserves_purgeable_count
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    rec = upload_recording(agency["id"], device, officer, size_bytes=1048576,
                           category="INCIDENT")
    set_clock("2027-03-20T00:00:00Z")
    hold = create_legal_hold(agency["id"], scope_type="RECORDING",
                             recording_id=rec["id"],
                             authority_reference="SUBP-2027-01")
    run_retention(agency["id"])
    resp = api.release_legal_hold(agency["id"], hold["id"], RO)
    validate_success(resp)
    rec_now = refresh_recording(agency["id"], rec["id"])
    assert rec_now["legal_hold_count"] == 0
    result = run_retention(agency["id"])
    assert result["purged"] == 1
    rec_now = refresh_recording(agency["id"], rec["id"])
    assert rec_now["upload_status"] == "PURGED"
    agency_now = refresh_agency(agency["id"])
    assert agency_now["storage_used_bytes"] == 0


# ===========================================================================
# compensating_invariant / case_link_unlink_preserves_agency_storage_total
# ===========================================================================

def test_link_does_not_double_count_agency_storage(api):
    """PRD §2.6: "An agency's `storage_used_bytes` is the sum of `size_bytes`
    over all of its recordings whose `upload_status` is `ACTIVE`,
    `RETENTION_DUE`, or `UNDER_REVIEW` — recordings in `PURGED` are always
    excluded."
    PRD §3.8: "Creating the link stamps it `LINKED`... increments the case's
    `evidence_count` by one, adds the recording's `size_bytes` into the case's
    `total_evidence_bytes`".

    Design: Difficulty/compensating_invariant/case_link_unlink_preserves_agency_storage_total
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    rec = upload_recording(agency["id"], device, officer, size_bytes=1048576,
                           category="INCIDENT")
    case = create_case(agency["id"], officer)
    from test_helpers.fixtures import link_evidence, get_case
    link_evidence(agency["id"], case["id"], rec["id"], officer)
    agency_mid = refresh_agency(agency["id"])
    assert agency_mid["storage_used_bytes"] == 1048576, (
        f"linking must not double-count the agency total, "
        f"got {agency_mid['storage_used_bytes']}"
    )
    case_now = get_case(agency["id"], case["id"])
    assert case_now["evidence_count"] == 1
    assert case_now["total_evidence_bytes"] == 1048576


def test_unlink_restores_case_rollups_and_conserves_agency_storage(api):
    """PRD §3.8: "A successful unlink moves the link to `UNLINKED` with
    `unlinked_at` stamped at the logical now, decrements `evidence_count` by
    one, recomputes `total_evidence_bytes` and the case `retention_due_at`
    rollup".
    PRD §2.6: "An agency's `storage_used_bytes` is the sum of `size_bytes` over
    all of its recordings whose `upload_status` is `ACTIVE`, `RETENTION_DUE`,
    or `UNDER_REVIEW`".

    Design: Difficulty/compensating_invariant/case_link_unlink_preserves_agency_storage_total
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    rec = upload_recording(agency["id"], device, officer, size_bytes=1048576,
                           category="INCIDENT")
    case = create_case(agency["id"], officer)
    from test_helpers.fixtures import link_evidence, get_case
    link = link_evidence(agency["id"], case["id"], rec["id"], officer)
    resp = api.unlink_evidence(agency["id"], case["id"], link["id"],
                               make_officer_headers(officer["id"]))
    unlinked = validate_success(resp)
    assert unlinked["status"] == "UNLINKED"
    assert unlinked["unlinked_at"] == "2026-09-01T00:00:00Z"
    case_now = get_case(agency["id"], case["id"])
    assert case_now["evidence_count"] == 0
    assert case_now["total_evidence_bytes"] == 0
    assert case_now["retention_due_at"] is None
    agency_now = refresh_agency(agency["id"])
    assert agency_now["storage_used_bytes"] == 1048576, (
        "link+unlink pair must be net-zero on the conserved agency byte total"
    )


# ===========================================================================
# entities / agency_create_returns_defaults_and_envelope
# ===========================================================================

def test_agency_create_returns_defaults_and_envelope(api):
    """PRD §3.1: "Everything begins when an `AgencyAdmin` registers an `Agency`,
    supplying a `name` and optionally a `timezone` (defaulting to `UTC`). The
    new agency starts with `storage_used_bytes` of 0 and `storage_posture` of
    `OK`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/agency_create_returns_defaults_and_envelope
    """
    resp = api.create_agency({"name": "Metro PD"}, ADMIN)
    assert resp.status_code == 201
    body = resp.json()
    assert body["response_type"] == "object"
    data = body["data"]
    assert data["timezone"] == "UTC"
    assert data["storage_used_bytes"] == 0
    assert data["storage_posture"] == "OK"
    assert data["version"] == 1
    assert data["id"]
    assert data["created_at"]
    assert data["updated_at"]
    assert body["meta"]["api_request_id"]


# ===========================================================================
# entities / officer_required_fields_missing_returns_validation
# ===========================================================================

def test_officer_missing_rank_returns_validation(api):
    """PRD §3.2: "An `AgencyAdmin` registers each sworn member as an `Officer`
    with a `badge_number`, a `full_name`, and a `rank` of `OFFICER`,
    `CORPORAL`, `SERGEANT`, or `LIEUTENANT`."
    PRD §5: "`ERR_VALIDATION` | 422 Unprocessable Entity".

    Design: Corner/entities/officer_required_fields_missing_returns_validation
    """
    agency = create_agency()
    resp = api.create_officer(agency["id"],
                              {"badge_number": "B-1", "full_name": "Ana Ruiz"},
                              ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=422)


# ===========================================================================
# entities / recording_list_paginates_with_total_count_and_has_more
# ===========================================================================

def test_recording_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "`limit` sets the maximum number of items returned; it defaults
    to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of
    items to skip and defaults to 0... the response's `meta` object carries
    `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/recording_list_paginates_with_total_count_and_has_more
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    upload_recording(agency["id"], device, officer,
                     recorded_at="2026-09-01T00:00:00Z", category="INCIDENT")
    # Advance the clock so the second upload is not future-dated relative to
    # the logical clock (PRD section 3.4).
    set_clock("2026-09-01T00:01:00Z")
    upload_recording(agency["id"], device, officer,
                     recorded_at="2026-09-01T00:01:00Z", category="INCIDENT")
    resp = api.list_recordings(
        make_supervisor_headers(officer["id"]),
        params={"agency_id": agency["id"], "limit": 1, "offset": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["response_type"] == "array"
    assert len(body["data"]) == 1
    assert body["meta"]["total_count"] == 2
    assert body["meta"]["has_more"] is True


# ===========================================================================
# entities / get_recording_unknown_id_returns_not_found
# ===========================================================================

def test_get_recording_unknown_id_returns_not_found(api):
    """PRD §2.7: "The first identifier that does not resolve yields
    `ERR_NOT_FOUND` (404) before any business rule is evaluated."

    Design: Corner/entities/get_recording_unknown_id_returns_not_found
    """
    agency = create_agency()
    resp = api.get_recording(agency["id"], NON_EXISTENT_UUID, RO)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


# ===========================================================================
# entities / device_serial_uniqueness_scoped_per_agency
# ===========================================================================

def test_device_serial_uniqueness_scoped_per_agency(api):
    """PRD §3.3: "Registering a `Device` takes a `serial_number` (unique within
    the agency, else `ERR_VALIDATION`)".

    Design: Corner/entities/device_serial_uniqueness_scoped_per_agency
    """
    aga = create_agency(name="Metro PD")
    agb = create_agency(name="County SO")
    resp = api.create_device(aga["id"], create_device_payload(serial_number="SN-1"), DC)
    validate_success(resp, expected_status=201)
    resp = api.create_device(aga["id"], create_device_payload(serial_number="SN-1"), DC)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=422)
    resp = api.create_device(agb["id"], create_device_payload(serial_number="SN-1"), DC)
    devb = validate_success(resp, expected_status=201)
    assert devb["serial_number"] == "SN-1"


# ===========================================================================
# entities / audit_log_entry_immutable_no_update_endpoint
# ===========================================================================

def test_audit_log_entry_unknown_id_returns_not_found(api):
    """PRD §3.11: "The audit log — one `AuditLogEntry` per consequential
    mutation, filterable by `agency_id`, `entity_type`, `entity_id`, and
    `action` — is the administrative record."
    PRD §2.4: "`AuditLogEntry` and `CustodyEvent` are append-only records that
    carry `id` and `created_at` only".

    Design: Corner/entities/audit_log_entry_immutable_no_update_endpoint
    """
    create_agency()
    resp = api.get_audit_log_entry(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


# ===========================================================================
# validations / trigger_code_outside_active_policy_rejected
# ===========================================================================

def test_trigger_code_outside_active_policy_rejected(api):
    """PRD §3.4: "The `trigger_code` must be a member of the currently `ACTIVE`
    policy's `recording_triggers` list."
    PRD §3.4: "Shape violations of any of these rules — including a
    `content_hash_sha256` that is not exactly 64 lowercase hex characters, or an
    out-of-range duration — are rejected with `ERR_VALIDATION` (422)."

    Design: Corner/validations/trigger_code_outside_active_policy_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    payload = create_recording_payload(device["id"], trigger_code="TASER_ARMED")
    resp = api.create_recording(agency["id"], payload,
                                make_officer_headers(officer["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=422)


# ===========================================================================
# validations / tagging_required_upload_without_category_rejected
# ===========================================================================

def test_tagging_required_upload_without_category_rejected(api):
    """PRD §3.4: "When the active policy's `tagging_required` is true, the
    category must arrive with the upload; an upload without one is rejected
    with `ERR_CATEGORY_REQUIRED` (422), and the transition happens immediately
    at upload."

    Design: Corner/validations/tagging_required_upload_without_category_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    payload = create_recording_payload(device["id"])
    del payload["category"]
    resp = api.create_recording(agency["id"], payload,
                                make_officer_headers(officer["id"]))
    validate_error(resp, ApiErrorId.ERR_CATEGORY_REQUIRED, expected_status=422)


def test_tagging_not_required_allows_categoryless_upload(api):
    """PRD §3.4: "When tagging is not required, the category may arrive later
    via categorization by the owning officer or a `Supervisor`".

    Design: Corner/validations/tagging_required_upload_without_category_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer(
        policy_overrides={"tagging_required": False})
    payload = create_recording_payload(device["id"])
    del payload["category"]
    resp = api.create_recording(agency["id"], payload,
                                make_officer_headers(officer["id"]))
    rec = validate_success(resp, expected_status=201)
    assert rec["upload_status"] == "INTEGRITY_VERIFIED", (
        f"category-less upload lands in INTEGRITY_VERIFIED (retention clock "
        f"not started), got {rec['upload_status']}"
    )


# ===========================================================================
# validations / unauthorized_role_denied_before_existence
# ===========================================================================

def test_unauthorized_role_denied_before_existence(api):
    """PRD §3.11: "Authorization follows: role permissions and ownership checks
    fail with `ERR_UNAUTHORIZED`. Existence checks come next — path resources
    validated left to right, then body-supplied references — failing with
    `ERR_NOT_FOUND`."

    Design: Corner/validations/unauthorized_role_denied_before_existence
    """
    agency = create_agency()
    resp = api.get_recording(agency["id"], NON_EXISTENT_UUID, make_prosecutor_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


# ===========================================================================
# validations / segregation_of_duties_submitter_cannot_approve
# ===========================================================================

def test_segregation_of_duties_submitter_cannot_approve(api):
    """PRD §3.6: "approval carries a hard segregation-of-duties rule: the
    approver's `X-User-ID` must differ from the `X-User-ID` of the technician
    who submitted the job, or the attempt is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (403)."

    Design: Corner/validations/segregation_of_duties_submitter_cannot_approve
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    rec = upload_recording(agency["id"], device, officer, duration_seconds=600,
                           category="INCIDENT")
    from test_helpers.fixtures import create_redaction_job
    job = create_redaction_job(agency["id"], rec["id"])
    tech_as_shared_id = make_redaction_technician_headers("ro-1")
    api.start_redaction_job(agency["id"], job["id"], tech_as_shared_id)
    api.submit_redaction_job(agency["id"], job["id"], {"actual_minutes": 20},
                             tech_as_shared_id)
    resp = api.approve_redaction_job(agency["id"], job["id"],
                                     make_records_officer_headers("ro-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)


def test_segregation_of_duties_different_approver_succeeds(api):
    """PRD §3.6: "the approver's `X-User-ID` must differ from the `X-User-ID` of
    the technician who submitted the job, or the attempt is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (403). Approval moves the job `SUBMITTED →
    APPROVED`".

    Design: Corner/validations/segregation_of_duties_submitter_cannot_approve
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    rec = upload_recording(agency["id"], device, officer, duration_seconds=600,
                           category="INCIDENT")
    from test_helpers.fixtures import create_redaction_job
    job = create_redaction_job(agency["id"], rec["id"])
    tech_as_shared_id = make_redaction_technician_headers("ro-1")
    api.start_redaction_job(agency["id"], job["id"], tech_as_shared_id)
    api.submit_redaction_job(agency["id"], job["id"], {"actual_minutes": 20},
                             tech_as_shared_id)
    resp = api.approve_redaction_job(agency["id"], job["id"],
                                     make_records_officer_headers("ro-2"))
    approved = validate_success(resp)
    assert approved["status"] == "APPROVED"


# ===========================================================================
# endpoints / share_access_lazy_expiry_blocks_before_sweep
# ===========================================================================

def test_share_access_lazy_expiry_blocks_before_sweep(api):
    """PRD §3.9: "Access is lazily gated on expiry: even before the sweep runs,
    a grant whose `expires_at` is at or before the logical now is rejected with
    `ERR_GRANT_EXPIRED` (410), as is any grant already `REVOKED` or `EXPIRED`."

    Design: Corner/endpoints/share_access_lazy_expiry_blocks_before_sweep
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_closed_case_with_grant(grant_overrides={"expires_in_days": 7})
    agency, grant = ctx["agency"], ctx["grant"]
    set_clock("2026-09-04T00:00:00Z")
    resp = api.share_access(agency["id"], {"access_token": grant["access_token"]},
                            make_prosecutor_headers())
    validate_success(resp)
    set_clock("2026-09-09T00:00:00Z")
    resp = api.share_access(agency["id"], {"access_token": grant["access_token"]},
                            make_prosecutor_headers())
    validate_error(resp, ApiErrorId.ERR_GRANT_EXPIRED, expected_status=410)


def test_share_grant_sweep_marks_expired_and_refused_access_not_counted(api):
    """PRD §3.9: "an `AgencyAdmin`-driven sweep expires every `ACTIVE` grant
    whose `expires_at` is at or before the logical now, moving each to
    `EXPIRED`... and reporting the count affected (`expired_count`)."
    PRD §3.9: "A successful access increments the grant's `access_count` by
    one".

    Design: Corner/endpoints/share_access_lazy_expiry_blocks_before_sweep
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_closed_case_with_grant(grant_overrides={"expires_in_days": 7})
    agency, case, grant = ctx["agency"], ctx["case"], ctx["grant"]
    set_clock("2026-09-04T00:00:00Z")
    api.share_access(agency["id"], {"access_token": grant["access_token"]},
                     make_prosecutor_headers())
    set_clock("2026-09-09T00:00:00Z")
    api.share_access(agency["id"], {"access_token": grant["access_token"]},
                     make_prosecutor_headers())
    resp = api.sweep_share_grants(agency["id"], ADMIN)
    sweep = validate_success(resp)
    assert sweep["expired_count"] == 1
    data, meta = validate_paginated(api.list_case_share_grants(agency["id"], case["id"], RO))
    grant_now = [g for g in data if g["id"] == grant["id"]][0]
    assert grant_now["status"] == "EXPIRED"
    assert grant_now["access_count"] == 1, (
        "the refused (expired) access must not increment the counter"
    )


# ===========================================================================
# endpoints / budget_plan_supersession_requires_later_effective_month
# ===========================================================================

def test_budget_plan_equal_effective_month_rejected(api):
    """PRD §3.7: "Creating a new plan while one is active atomically supersedes
    the incumbent (`ACTIVE → SUPERSEDED`) — but only when the new plan's
    `effective_from_month` is strictly later than the incumbent's, failing with
    `ERR_PLAN_NOT_LATER` (409) otherwise."

    Design: Corner/endpoints/budget_plan_supersession_requires_later_effective_month
    """
    agency = create_agency()
    create_budget_plan(agency["id"], monthly_budget_cents=10000,
                       effective_from_month="2026-01")
    resp = api.create_budget_plan(
        agency["id"],
        create_budget_plan_payload(monthly_budget_cents=20000,
                                   effective_from_month="2026-01"),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_LATER, expected_status=409)


def test_budget_plan_later_month_supersedes_incumbent(api):
    """PRD §3.7: "Creating a new plan while one is active atomically supersedes
    the incumbent (`ACTIVE → SUPERSEDED`) — but only when the new plan's
    `effective_from_month` is strictly later than the incumbent's".

    Design: Corner/endpoints/budget_plan_supersession_requires_later_effective_month
    """
    agency = create_agency()
    plan1 = create_budget_plan(agency["id"], monthly_budget_cents=10000,
                               effective_from_month="2026-01")
    resp = api.create_budget_plan(
        agency["id"],
        create_budget_plan_payload(monthly_budget_cents=20000,
                                   effective_from_month="2027-01"),
        ADMIN,
    )
    plan2 = validate_success(resp, expected_status=201)
    assert plan2["status"] == "ACTIVE"
    plan1_now = get_success_data(api.get_budget_plan(plan1["id"], ADMIN))
    assert plan1_now["status"] == "SUPERSEDED"


# ===========================================================================
# errors / occ_stale_version_conflict_is_412_not_409
# ===========================================================================

def test_occ_stale_version_conflict_is_412(api):
    """PRD §2.9: "That request must carry `expected_case_version`, holding the
    case `version` the caller last observed. If another writer has advanced the
    case's version since then — the check compares the supplied value against
    the case's current `version` — the request is rejected with
    `ERR_STALE_VERSION` (412)".

    Design: Corner/errors/occ_stale_version_conflict_is_412_not_409
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_closed_case_with_grant()
    agency, case, grant = ctx["agency"], ctx["case"], ctx["grant"]
    # the first grant bumped the case version past the observed value
    from test_helpers.factories import create_share_grant_payload
    resp = api.create_share_grant(
        agency["id"], case["id"],
        create_share_grant_payload(case["version"], recipient_role="DEFENSE",
                                   recipient_email="defense@firm.com"),
        RO,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_occ_fresh_version_retry_succeeds(api):
    """PRD §2.9: "forcing the caller to re-read the case and its current
    evidence rollup before granting access."
    PRD §3.9: "Creation mints an opaque `access_token` returned only at creation
    time... sets the grant `ACTIVE`, increments the case's `version`".

    Design: Corner/errors/occ_stale_version_conflict_is_412_not_409
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_closed_case_with_grant()
    agency, case = ctx["agency"], ctx["case"]
    from test_helpers.fixtures import get_case
    from test_helpers.factories import create_share_grant_payload
    case_now = get_case(agency["id"], case["id"])
    resp = api.create_share_grant(
        agency["id"], case["id"],
        create_share_grant_payload(case_now["version"], recipient_role="DEFENSE",
                                   recipient_email="defense@firm.com"),
        RO,
    )
    grant2 = validate_success(resp, expected_status=201)
    assert grant2["status"] == "ACTIVE"


# ===========================================================================
# roles / officer_cannot_run_retention_or_manage_devices
# ===========================================================================

def test_officer_cannot_run_retention(api):
    """PRD §2.1: "If the role is recognized but not permitted for the target
    endpoint — or an ownership check described below fails — the request is
    rejected with `ERR_UNAUTHORIZED` (403)."
    PRD §4: POST /agencies/{agencyId}/retention/run is authorized for
    AgencyAdmin only.

    Design: Corner/roles/officer_cannot_run_retention_or_manage_devices
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    resp = api.run_retention(agency["id"], make_officer_headers(officer["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_records_officer_cannot_register_devices(api):
    """PRD §2.1: "If the role is recognized but not permitted for the target
    endpoint — or an ownership check described below fails — the request is
    rejected with `ERR_UNAUTHORIZED` (403)."
    PRD §4: POST /agencies/{agencyId}/devices is authorized for
    DeviceCoordinator only.

    Design: Corner/roles/officer_cannot_run_retention_or_manage_devices
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy = setup_agency_with_policy()
    resp = api.create_device(agency["id"],
                             create_device_payload(serial_number="SN-2"), RO)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


# ===========================================================================
# roles / officer_ownership_upload_from_others_device_denied
# ===========================================================================

def test_officer_ownership_upload_from_others_device_denied(api):
    """PRD §3.4: "An `Officer` uploads footage from their own assigned device"
    PRD §2.1: "Ownership checks on any resource that references an officer —
    notably device dock/undock and recording upload/reverify — compare the
    resource's foreign-key field (the device's `assigned_officer_id`, or the
    recording's `officer_id`) to `X-User-ID`."

    Design: Corner/roles/officer_ownership_upload_from_others_device_denied
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy = setup_agency_with_policy()
    offa, deva = setup_officer_with_device(agency["id"], badge_number="B-100",
                                           serial_number="SN-1")
    offb = create_officer(agency["id"], badge_number="B-200", full_name="Ben Day")
    payload = create_recording_payload(deva["id"])
    resp = api.create_recording(agency["id"], payload,
                                make_officer_headers(offb["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
