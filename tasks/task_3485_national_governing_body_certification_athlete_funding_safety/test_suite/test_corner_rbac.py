"""Corner tests: rbac section — role-list denials, entity-backed cross-body
ownership denial, and the segregation-of-duties pairs (cycle issuer/closer,
complaint triager/resolver, result submitter/verifier)."""
from test_helpers import (
    AUDITOR_CLOSER_ID,
    AUDITOR_ISSUER_ID,
    ApiErrorId,
    close_cycle,
    create_athlete,
    create_certification_cycle,
    create_governing_body,
    create_selection_procedure_payload,
    file_complaint,
    get_success_data,
    investigate_complaint,
    issue_findings,
    make_athlete_headers,
    make_auditor_headers,
    make_ngb_admin_headers,
    open_cycle,
    read_governing_body,
    resolve_complaint,
    submit_result,
    triage_complaint,
    validate_error,
)


def test_athlete_cannot_transition_governing_body(api):
    """PRD §2.1: "A request whose role is not on the endpoint's authorized list
    is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4 lists only `CommitteeAdmin` for the governing-body transitions
    endpoint ("Committee lifecycle moves: interim-manager appoint/replace
    (self-loop), return to probation, decertify"), so an Athlete caller fails
    the role check before any state or evidence rule is examined.

    Design: Corner/rbac/athlete_cannot_transition_governing_body
    """
    body = create_governing_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = create_athlete(
        body["id"], api=api, full_name="Role Test", date_of_birth="2000-01-01"
    )

    resp = api.transition_governing_body(
        body["id"],
        {"to_state": "DECERTIFIED"},
        make_athlete_headers(athlete["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    after = read_governing_body(body["id"], api=api)
    assert after["status"] == "APPLIED", "a role-denied call mutates nothing"


def test_ngbadmin_cannot_touch_other_body(api):
    """PRD §2.1: "When `X-User-Role` is `NGBAdmin`, `X-User-ID` is the `id` of
    the acting GoverningBody; ownership checks on any resource that references
    a GoverningBody compare the resource's `governing_body_id` foreign key to
    `X-User-ID`, and cross-body access is denied with `ERR_UNAUTHORIZED`."
    PRD §2.6: "2. **Authorization.** The caller's role appears in the
    endpoint's authorized-role list, entity-backed ownership holds (`NGBAdmin`
    matching `governing_body_id`, `Athlete` matching `athlete_id`), and the
    interim-management roster-submission restriction of §2.1 is satisfied;
    otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."

    Design: Corner/rbac/ngbadmin_cannot_touch_other_body
    """
    gb1 = create_governing_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    gb2 = create_governing_body(
        api=api,
        name="US Judo",
        sport_code="JUDO",
        funding_budget_cents=3_000_000,
        sport_science_pool_hours=40,
    )

    # NGBAdmin is on this endpoint's role list, but X-User-ID carries gb1
    # while the path body is gb2: entity-backed ownership fails.
    resp = api.create_selection_procedure(
        gb2["id"],
        create_selection_procedure_payload(
            games_name="2028 Summer Olympics",
            trials_start="2026-12-15T00:00:00Z",
            trials_end="2026-12-17T00:00:00Z",
            registration_deadline="2026-12-01T00:00:00Z",
            qualifying_score=80,
            quota_slots=1,
        ),
        make_ngb_admin_headers(gb1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_sod_cycle_issuer_cannot_close(api):
    """PRD §3.1: "Closing is segregated from issuing: the auditor closing a
    cycle must not be the auditor recorded in `issued_by_user_id`, or the
    request fails with `ERR_SEGREGATION_OF_DUTIES`. The closer is recorded as
    `closed_by_user_id` and `closed_at` is stamped with the logical clock."
    PRD §3.1: "A score of at least 85 qualifies for the excellent fast-path
    directly to `CLOSED_PASSED`."

    Design: Corner/rbac/sod_cycle_issuer_cannot_close
    """
    body = create_governing_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    cycle = create_certification_cycle(body["id"], api=api)
    open_cycle(cycle["id"], auditor_id=AUDITOR_ISSUER_ID, api=api)
    # 0.40*90 + 0.35*88 + 0.25*92 = 89.8 >= 85: fast-path close is legal.
    issue_findings(cycle["id"], 90, 88, 92, auditor_id=AUDITOR_ISSUER_ID, api=api)

    resp = api.transition_certification_cycle(
        cycle["id"],
        {"to_state": "CLOSED_PASSED"},
        make_auditor_headers(AUDITOR_ISSUER_ID),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    closed = close_cycle(
        cycle["id"], "CLOSED_PASSED", auditor_id=AUDITOR_CLOSER_ID, api=api
    )
    assert closed["status"] == "CLOSED_PASSED"
    assert closed["closed_by_user_id"] == AUDITOR_CLOSER_ID
    assert closed["issued_by_user_id"] == AUDITOR_ISSUER_ID


def test_sod_complaint_triager_cannot_resolve(api):
    """PRD §3.2: "The complaint starts `FILED` and moves through `TRIAGED` and
    `INVESTIGATING` to a terminal resolution of `SUBSTANTIATED` or `DISMISSED`,
    all driven by `CertificationAuditor` operators."
    PRD §3.2: "Resolution is segregated from triage: the resolver must differ
    from the triager, or the request fails with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/sod_complaint_triager_cannot_resolve
    """
    body = create_governing_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    complaint = file_complaint(
        body["id"],
        api=api,
        category="FINANCIAL",
        severity="MAJOR",
        description="Undisclosed related-party contracts",
    )
    triage_complaint(complaint["id"], auditor_id=AUDITOR_ISSUER_ID, api=api)
    investigate_complaint(complaint["id"], auditor_id=AUDITOR_ISSUER_ID, api=api)

    resp = api.transition_complaint(
        complaint["id"],
        {"to_state": "SUBSTANTIATED"},
        make_auditor_headers(AUDITOR_ISSUER_ID),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    resolved = resolve_complaint(
        complaint["id"], "SUBSTANTIATED", auditor_id=AUDITOR_CLOSER_ID, api=api
    )
    assert resolved["status"] == "SUBSTANTIATED"
    assert resolved["resolved_by_user_id"] == AUDITOR_CLOSER_ID


def test_athlete_cannot_verify_own_result(api, committee_admin_headers):
    """PRD §3.4: "A `ResultsOfficial` then verifies or rejects it — never the
    same person as the submitting athlete, with a self-verification rejected as
    `ERR_SEGREGATION_OF_DUTIES` — and verification stamps `verified_by_user_id`
    and computes `base_points`."
    PRD §2.6: "7. **Constraint checks.** Component scores within 0 to 100 and
    placings within 1 to 8 (`ERR_SCORE_OUT_OF_RANGE`, 422); malformed bodies —
    missing required fields, wrong types, unknown enum members, empty required
    strings (`ERR_INVALID_REQUEST`, 400, on every endpoint);
    segregation-of-duties pairs (`ERR_SEGREGATION_OF_DUTIES`, 403); duplicate
    trials entries (`ERR_DUPLICATE_ENTRY`, 409); roster submission blocked by
    pending appeals (`ERR_PENDING_APPEALS`, 409) or by unanswered primary slots
    (`ERR_PENDING_SLOT_DECISIONS`, 409); nomination attempted before trials
    results are final (`ERR_RESULTS_NOT_FINAL`, 409)."

    Design: Corner/rbac/athlete_cannot_verify_own_result
    """
    body = create_governing_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = create_athlete(
        body["id"], api=api, full_name="Self Verify", date_of_birth="2000-01-01"
    )
    result = submit_result(
        athlete["id"],
        api=api,
        event_name="Spring Open",
        event_grade="A",
        placing=1,
        event_date="2026-10-01T00:00:00Z",
    )
    assert result["status"] == "SUBMITTED"

    # The submitting athlete attempting to verify their own result is the
    # self-verification half of the submit/verify segregated pair.
    resp = api.transition_result(
        result["id"],
        {"to_state": "VERIFIED"},
        make_athlete_headers(athlete["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    listed = get_success_data(api.list_results(athlete["id"], committee_admin_headers))
    after = next(r for r in listed if r["id"] == result["id"])
    assert after["status"] == "SUBMITTED"
    assert after["base_points"] is None, "base_points is computed at verification"
