"""Queue B — complexity_layers: optimistic-concurrency stories end to end and
the sweep-driven checkpoint behaviors (suspension lift boundary; sanctions
deferred until FINAL).
"""
from datetime import datetime, timezone

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    advance_clock,
    appeal_case,
    case_decide_payload,
    create_candidate,
    create_license_application_payload,
    create_recert_application_payload,
    create_recert_draft,
    create_state_policy,
    get_success_data,
    make_candidate_headers,
    make_hearing_officer_headers,
    open_case,
    refresh_case,
    refresh_certification,
    refresh_completion_record,
    refresh_license_application,
    refresh_recert_application,
    schedule_hearing,
    setup_certified_candidate,
    setup_license_context_nremt,
    validate_error,
    walk_case_to_decided,
    walk_case_to_under_review,
)


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_occ_recert_stale_then_supersede(api):
    """PRD §2.7: "Opening a recertification draft requires
    `expected_certification_version`, carrying the `version` of the target
    certification as the client last observed it. When the certification's
    version has advanced since — for example because another writer opened a
    draft (which supersedes the previous draft) or a renewal was applied — the
    create is rejected with `ERR_STALE_VERSION` (HTTP 412)".
    PRD §3.6: "an existing `DRAFT` is automatically superseded to `SUPERSEDED`
    when a new draft opens".
    PRD §3.6: "Opening a draft is itself a mutation of the certification and
    increments its `version` by one — which is precisely what invalidates a
    second writer's pinned version."

    A create carrying the pre-draft version is rejected; re-reading the bumped
    version and retrying succeeds and supersedes the earlier draft.

    Design: Corner/complexity_layers/occ_recert_stale_then_supersede
    """
    ctx = setup_certified_candidate()
    advance_clock("2027-10-15T00:00:00Z")
    cert_id = ctx["certification"]["id"]
    stale_version = ctx["certification"]["version"]
    first = create_recert_draft(ctx["candidate"]["id"], cert_id, model="NCCP")

    resp = api_client.create_recert_application(
        create_recert_application_payload(cert_id, "HOURLY", stale_version),
        make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    fresh_version = refresh_certification(cert_id)["version"]
    second = get_success_data(api_client.create_recert_application(
        create_recert_application_payload(cert_id, "HOURLY", fresh_version),
        make_candidate_headers(ctx["candidate"]["id"]),
    ))
    assert second["status"] == "DRAFT"
    assert refresh_recert_application(first["id"])["status"] == "SUPERSEDED"


def test_occ_license_stale_version(api):
    """PRD §2.7: "Creating a state licensure application on the
    national-certification path likewise requires
    `expected_certification_version` matching the cited certification's current
    `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), since
    licensure must be pinned to the certification state the client actually
    observed — the credential may have been renewed, suspended, or revoked in
    between."

    An unrelated recertification draft creation bumps the certification, and
    the license create carrying the old version is rejected.

    Design: Corner/complexity_layers/occ_license_stale_version
    """
    create_state_policy()
    ctx = setup_certified_candidate()
    stale_version = ctx["certification"]["version"]
    advance_clock("2027-10-15T00:00:00Z")
    create_recert_draft(ctx["candidate"]["id"], ctx["certification"]["id"], model="NCCP")

    resp = api_client.create_license_application(
        create_license_application_payload(
            "WA", ctx["level"]["id"], certification_id=ctx["certification"]["id"],
            expected_certification_version=stale_version,
        ),
        make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_occ_case_decide_stale_version(api):
    """PRD §2.7: "Recording a disciplinary hearing decision requires
    `expected_case_version` matching the case's current `version`; a mismatch —
    an intermediate mutation such as an appeal filing or a rehearing reschedule
    has advanced the case — is rejected with `ERR_STALE_VERSION` (HTTP 412), so
    a decision is never recorded against a stage the officer did not observe."

    A version captured at UNDER_REVIEW goes stale once schedule-hearing
    advances the case.

    Design: Corner/complexity_layers/occ_case_decide_stale_version
    """
    candidate = create_candidate()
    case = open_case(
        candidate["id"], violation_type="CRIMINAL_CONDUCT",
        description="Disclosure review",
    )
    walk_case_to_under_review(case["id"], candidate["id"])
    stale_version = refresh_case(case["id"])["version"]
    schedule_hearing(case["id"])

    resp = api_client.decide_case(
        case["id"],
        case_decide_payload("WARNING", "stale observation", stale_version),
        make_hearing_officer_headers("ho-1"),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_suspension_lift_boundary_sweep(api):
    """PRD §3.9: "`SUSPENSION_12M` moves the subject's `ACTIVE` or `SUSPENDED`
    certifications to `SUSPENDED` with `suspension_ends` set twelve calendar
    months after `finalized_at`."
    PRD §2.5: "5. Certifications `SUSPENDED` whose `suspension_ends` is at or
    before now are lifted — returning to `ACTIVE` when their `expires_on` is at
    or after now, otherwise becoming `LAPSED`."

    The lift is inclusive: at exactly finalized_at + 12 months the sweep
    restores ACTIVE because the expiry (2028-09-04) is still ahead.

    Design: Corner/complexity_layers/suspension_lift_boundary_sweep
    """
    ctx = setup_certified_candidate()
    case = open_case(
        ctx["candidate"]["id"], violation_type="CRIMINAL_CONDUCT",
        description="Deferred-adjudication misdemeanor",
    )
    advance_clock("2027-01-01T00:00:00Z")
    walk_case_to_decided(case["id"], ctx["candidate"]["id"],
                         sanction_type="SUSPENSION_12M", findings="Substantiated")
    advance_clock("2027-02-01T00:00:00Z")  # appeal deadline 2027-01-31 has passed
    suspended = refresh_certification(ctx["certification"]["id"])
    assert suspended["status"] == "SUSPENDED"
    assert _ts(suspended["suspension_ends"]) == _ts("2028-02-01T00:00:00Z"), (
        f"finalized 2027-02-01 + 12 months, got {suspended['suspension_ends']}"
    )

    sweep = advance_clock("2028-02-01T00:00:00Z")
    assert sweep["suspensions_lifted_count"] == 1
    lifted = refresh_certification(ctx["certification"]["id"])
    assert lifted["status"] == "ACTIVE", "expires_on 2028-09-04 is still ahead of now"


def test_deferred_sanction_no_effect_before_final(api):
    """PRD §3.9: "The case becomes `DECIDED`, `decided_at` is stamped, an
    `appeal_deadline` opens thirty calendar days later with the boundary
    inclusive, and the case's `version` increments by one — but no sanction is
    applied yet."
    PRD §2.5: "7. Disciplinary cases in `DECIDED` whose `appeal_deadline` has
    passed enter `FINAL`, and the sanction cascade of §3.9 applies."

    After a REVOCATION decision with the appeal window still open, the
    certification, completion record, and license application are all
    untouched.

    Design: Corner/complexity_layers/deferred_sanction_no_effect_before_final
    """
    ctx = setup_license_context_nremt()
    case = open_case(
        ctx["candidate"]["id"], violation_type="FALSIFIED_EDUCATION",
        description="Fabricated clinical hours",
        implicated_completion_record_ids=[ctx["completion_record"]["id"]],
    )
    advance_clock("2026-09-10T00:00:00Z")
    decided = walk_case_to_decided(case["id"], ctx["candidate"]["id"],
                                   sanction_type="REVOCATION", findings="Substantiated")
    assert decided["status"] == "DECIDED"
    assert _ts(decided["appeal_deadline"]) == _ts("2026-10-10T00:00:00Z")

    assert refresh_certification(ctx["certification"]["id"])["status"] == "ACTIVE"
    assert refresh_completion_record(ctx["completion_record"]["id"])["status"] == "VERIFIED"
    assert refresh_license_application(ctx["license_application"]["id"])["status"] == "UNDER_REVIEW"
