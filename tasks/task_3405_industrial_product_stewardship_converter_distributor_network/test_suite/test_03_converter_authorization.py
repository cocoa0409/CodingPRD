"""Converter onboarding, audit, authorization, and windows (PRD §2.6, §3.3)."""
from test_helpers import (
    ApiErrorId,
    audit_payload,
    authorization_payload,
    authorize_converter,
    build_user_headers,
    converter_payload,
    create_authorized_converter,
    create_converter,
    get_converter,
    grant_authorization,
    record_audit,
    set_clock,
    TEST_USERS,
    validate_error,
    validate_success,
)

CM = TEST_USERS["channel_manager_headers"]
QA = TEST_USERS["quality_auditor_headers"]


def test_authorize_at_score_74_rejected_75_accepted(api):
    """PRD §3.3: "the score check follows — `quality_audit_score` must be at
    least 75, else `ERR_AUDIT_SCORE_INSUFFICIENT` (409)."

    Design: Corner/state_machines/authorize_at_score_74_rejected_75_accepted
    """
    set_clock()
    c_low = create_converter(name="LowScore Converting")
    record_audit(c_low["id"], audit_score=74)
    resp = api.authorize_converter(c_low["id"], CM)
    validate_error(resp, ApiErrorId.ERR_AUDIT_SCORE_INSUFFICIENT)
    assert get_converter(c_low["id"])["status"] == "AUDIT_RECORDED"

    c_edge = create_converter(name="EdgeScore Converting")
    record_audit(c_edge["id"], audit_score=75)
    ok = api.authorize_converter(c_edge["id"], CM)
    data = validate_success(ok, 200)
    assert data["status"] == "AUTHORIZED", "75 >= 75 is inclusive"


def test_quality_auditor_cannot_authorize_converter(api):
    """PRD §2.1: "a request whose `X-User-Role` is not admitted by the endpoint
    is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." PRD §4: authorize is a
    ChannelManager operation.

    Design: Corner/rbac/quality_auditor_cannot_authorize_converter
    """
    set_clock()
    conv = create_converter()
    record_audit(conv["id"], audit_score=90, auditor="qa-1")
    resp = api.authorize_converter(conv["id"], build_user_headers("qa-1", "QualityAuditor"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert get_converter(conv["id"])["status"] == "AUDIT_RECORDED"


def test_sod_auditor_identity_cannot_authorize_own_audit(api):
    """PRD §3.3: "the segregation-of-duties check comes first — the authorizing
    user's `X-User-ID` must differ from `audited_by`, else
    `ERR_SEGREGATION_OF_DUTIES` (403) — and the score check follows."

    Design: Corner/rbac/sod_auditor_identity_cannot_authorize_own_audit
    """
    set_clock()
    conv = create_converter()
    record_audit(conv["id"], audit_score=90, auditor="qa-7")
    resp = api.authorize_converter(conv["id"], build_user_headers("qa-7", "ChannelManager"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    ok = api.authorize_converter(conv["id"], build_user_headers("cm-1", "ChannelManager"))
    data = validate_success(ok, 200)
    assert data["status"] == "AUTHORIZED"


def test_immediate_read_after_write_consistency(api):
    """PRD §3.3: "the submission stores the score into `quality_audit_score`,
    records the auditor's `X-User-ID` in `audited_by`, and moves the converter
    from `APPLIED` to `AUDIT_RECORDED`." PRD §2.5: "`version` (integer): starts
    at 1 and increments by one on every mutation, including mutations driven
    indirectly by cascades or by writes on a related resource."

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    set_clock()
    conv = create_converter()
    assert conv["version"] == 1
    resp = api.record_audit(conv["id"], audit_payload(audit_score=88),
                            build_user_headers("qa-3", "QualityAuditor"))
    data = validate_success(resp, 200)
    assert data["status"] == "AUDIT_RECORDED"
    assert data["version"] == 2
    got = validate_success(api.get_converter(conv["id"], CM), 200)
    assert got["status"] == "AUDIT_RECORDED"
    assert got["version"] == 2
    assert got["quality_audit_score"] == 88
    assert got["audited_by"] == "qa-3"


def test_authorization_grant_blocked_while_converter_applied(api):
    """PRD §3.3: "The target converter must currently be `AUTHORIZED`, else
    `ERR_CONVERTER_NOT_AUTHORIZED` (409)."

    Design: Difficulty/cross_entity_state_dependency/authorization_create_gated_by_converter_state
    """
    set_clock()
    conv = create_converter()
    assert conv["status"] == "APPLIED"
    resp = api.create_converter_authorization(
        authorization_payload(conv["id"], expected_converter_version=conv["version"]),
        CM,
    )
    validate_error(resp, ApiErrorId.ERR_CONVERTER_NOT_AUTHORIZED)


def test_authorization_grant_succeeds_after_authorize(api):
    """PRD §3.3: "A `ChannelManager` grants one by naming `converter_id`, a
    `capability` of `SLITTING`, `DIE_CUTTING`, or `LAMINATION`, the
    `territory_code` covered, and the half-open validity window `valid_from`
    (inclusive) to `valid_to` (exclusive), together with
    `expected_converter_version` (the OCC guard of §2.6 — the grant itself
    increments the converter's `version`)." "The target converter must
    currently be `AUTHORIZED`, else `ERR_CONVERTER_NOT_AUTHORIZED` (409)."

    Design: Difficulty/cross_entity_state_dependency/authorization_create_gated_by_converter_state
    """
    set_clock()
    conv = create_converter()
    record_audit(conv["id"], audit_score=80, auditor="qa-1")
    authorize_converter(conv["id"], authorizer="cm-1")
    assert get_converter(conv["id"])["status"] == "AUTHORIZED"
    az = grant_authorization(conv["id"], capability="SLITTING", territory_code="DE",
                             valid_from="2026-10-01T00:00:00Z",
                             valid_to="2027-04-01T00:00:00Z")
    assert az["capability"] == "SLITTING"
    assert az["territory_code"] == "DE"
    assert az["converter_id"] == conv["id"]


def test_authorization_window_adjacent_to_existing_is_allowed(api):
    """PRD §2.8: "Overlap checks respect the same half-open reading, which makes
    **adjacency legal**: an authorization running to noon and another beginning
    at noon do not overlap."

    Design: Difficulty/resource_temporal_overlap/authorization_windows_half_open_adjacency_allowed
    """
    set_clock()
    conv = create_authorized_converter()
    az1 = grant_authorization(conv["id"], capability="SLITTING", territory_code="DE",
                              valid_from="2026-10-01T00:00:00Z",
                              valid_to="2027-04-01T00:00:00Z")
    az2 = grant_authorization(conv["id"], capability="SLITTING", territory_code="DE",
                              valid_from="2027-04-01T00:00:00Z",
                              valid_to="2027-10-01T00:00:00Z")
    assert az1["id"] != az2["id"]
    assert az2["valid_from"] == az1["valid_to"], (
        "the second window begins exactly at the first window's exclusive end"
    )


def test_authorization_window_overlap_rejected_but_other_capability_allowed(api):
    """PRD §3.3: "the new window must not overlap an existing authorization for
    the same (`converter_id`, `capability`, `territory_code`) triple — half-open
    intervals, adjacency allowed — else `ERR_AUTHORIZATION_WINDOW_OVERLAP`
    (409)."

    Design: Difficulty/resource_temporal_overlap/authorization_windows_half_open_adjacency_allowed
    """
    set_clock()
    conv = create_authorized_converter()
    grant_authorization(conv["id"], capability="SLITTING", territory_code="DE",
                        valid_from="2026-10-01T00:00:00Z", valid_to="2027-04-01T00:00:00Z")
    current = get_converter(conv["id"])
    overlap = api.create_converter_authorization(
        authorization_payload(
            conv["id"], capability="SLITTING", territory_code="DE",
            valid_from="2027-03-31T00:00:00Z", valid_to="2027-05-01T00:00:00Z",
            expected_converter_version=current["version"]),
        CM,
    )
    validate_error(overlap, ApiErrorId.ERR_AUTHORIZATION_WINDOW_OVERLAP)
    az4 = grant_authorization(conv["id"], capability="DIE_CUTTING", territory_code="DE",
                              valid_from="2026-11-01T00:00:00Z",
                              valid_to="2027-02-01T00:00:00Z")
    assert az4["capability"] == "DIE_CUTTING", (
        "time overlap for a different capability is a different resource key"
    )
