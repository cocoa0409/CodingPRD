"""Corner tests (validations): authentication, invitation gating, scope, duplicate
anchors, retest gating, and award uniqueness/cap."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_researcher_headers,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_report_payload
from test_helpers.fixtures import (
    PROGRAM_ADMIN,
    TRIAGER,
    approve_award,
    create_asset,
    create_award,
    create_scope_version,
    create_validated_report,
    get_award,
    issue_invitation,
    register_researcher,
    resolve_report,
    setup_active_program,
    submit_report,
)


def test_report_submit_unauthenticated(api):
    """PRD §2.1: "Every request carries two mandatory HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, naming the capacity in which
    they act. A request missing either header, or carrying an empty value for
    either, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/report_submit_unauthenticated
    """
    resp = api.create_report(
        {
            "program_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
            "asset_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
            "title": "t",
            "description": "d",
            "vulnerability_class": "XSS",
        },
        headers={"Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert resp.status_code == 401


def test_private_program_submission_requires_accepted_invitation(api):
    """PRD §3.4: "For a `PRIVATE` program, submitting a report without holding an
    `ACCEPTED` invitation for that program and researcher is rejected with
    `ERR_INVITATION_REQUIRED`."

    Design: Corner/validations/private_program_submission_requires_invitation
    """
    program, asset = setup_active_program(visibility="PRIVATE", criticality="HIGH")
    researcher = register_researcher()
    # Issued but still PENDING — not ACCEPTED
    issue_invitation(program["id"], researcher["id"])
    resp = api.create_report(
        create_report_payload(program["id"], asset["id"]),
        make_researcher_headers(researcher["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVITATION_REQUIRED)


def test_asset_excluded_from_pinned_scope_version_out_of_scope(api):
    """PRD §3.2: "Assets not listed in `in_scope_asset_ids` are out-of-scope
    exclusions for that window."
    PRD §2.5: "10. **Scope conformance** — the asset referenced by a new report
    must belong to the program, be `ACTIVE`, and appear in the scope version
    effective at submission time, else `ERR_OUT_OF_SCOPE` (HTTP 422)."

    Design: Corner/validations/asset_excluded_from_pinned_scope_version_out_of_scope
    """
    program, asset1 = setup_active_program(criticality="HIGH")
    # Second asset in the same program but NOT listed in the scope version
    asset2 = create_asset(program["id"], name="A2", asset_identifier="a2.example.com",
                          criticality="LOW")
    researcher = register_researcher()
    resp = api.create_report(
        create_report_payload(program["id"], asset2["id"]),
        make_researcher_headers(researcher["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OUT_OF_SCOPE)


def test_duplicate_anchor_self_reference_rejected(api):
    """PRD §3.6: "The anchor named in `duplicate_of_id` must reference a
    different report in the same program, sharing the same `vulnerability_class`,
    and already in `VALIDATED` or `RESOLVED` status; a missing anchor, a
    self-reference, a cross-program reference, a mismatched class, or an anchor
    in any other status is rejected with `ERR_DUPLICATE_OF_INVALID`."

    Design: Corner/validations/duplicate_anchor_self_reference_rejected
    """
    program, asset = setup_active_program(criticality="HIGH")
    researcher = register_researcher()
    report = submit_report(program, asset, researcher)
    get_success_data(api.triage_report(report["id"], {"action": "TRIAGE"}, TRIAGER))
    resp = api.triage_report(
        report["id"],
        {"action": "MARK_DUPLICATE", "duplicate_of_id": report["id"]},
        TRIAGER,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_OF_INVALID)


def test_duplicate_anchor_not_validated_rejected(api):
    """PRD §3.6: "The anchor named in `duplicate_of_id` must reference a
    different report in the same program, sharing the same `vulnerability_class`,
    and already in `VALIDATED` or `RESOLVED` status; a missing anchor, a
    self-reference, a cross-program reference, a mismatched class, or an anchor
    in any other status is rejected with `ERR_DUPLICATE_OF_INVALID`."

    Design: Corner/validations/duplicate_anchor_not_validated_rejected
    """
    program, asset = setup_active_program(criticality="HIGH")
    researcher = register_researcher()
    anchor = submit_report(program, asset, researcher, title="anchor")
    get_success_data(api.triage_report(anchor["id"], {"action": "TRIAGE"}, TRIAGER))
    dupe = submit_report(program, asset, researcher, title="dupe")
    get_success_data(api.triage_report(dupe["id"], {"action": "TRIAGE"}, TRIAGER))
    resp = api.triage_report(
        dupe["id"],
        {"action": "MARK_DUPLICATE", "duplicate_of_id": anchor["id"]},
        TRIAGER,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_OF_INVALID)


def test_retest_award_requires_resolved_report(api):
    """PRD §3.9: "A `RETEST` award is the flat program `retest_award_cents`
    snapshotted at creation, requires the report to be `RESOLVED` — otherwise
    `ERR_REPORT_NOT_RESOLVED` — and is likewise limited to one non-`VOID`
    instance per report."

    Design: Corner/validations/retest_award_requires_resolved_report
    """
    program, asset = setup_active_program()
    researcher = register_researcher()
    report = create_validated_report(
        program, asset, researcher, impact=9, exploitability=8, affected_scope=5,
        vulnerability_class="RCE")
    early = api.create_award({"report_id": report["id"], "award_type": "RETEST"}, TRIAGER)
    validate_error(early, ApiErrorId.ERR_REPORT_NOT_RESOLVED)
    resolve_report(report["id"])
    award = create_award(report["id"], "RETEST")
    assert award["amount_cents"] == 50_000  # flat program retest award default


def test_second_bounty_on_same_report_rejected(api):
    """PRD §3.9: "A `BOUNTY` may only be proposed for a report that is
    `VALIDATED` or `RESOLVED` with a `severity_final` other than `NONE`, and at
    most one non-`VOID` bounty may exist per report — a second is rejected with
    `ERR_BOUNTY_ALREADY_EXISTS`."

    Design: Corner/validations/second_bounty_on_same_report_rejected
    """
    program, asset = setup_active_program()
    researcher = register_researcher()
    report = create_validated_report(
        program, asset, researcher, impact=9, exploitability=8, affected_scope=5,
        vulnerability_class="RCE")
    create_award(report["id"], "BOUNTY")
    resp = api.create_award({"report_id": report["id"], "award_type": "BOUNTY"}, TRIAGER)
    validate_error(resp, ApiErrorId.ERR_BOUNTY_ALREADY_EXISTS)


def test_bonus_above_cap_rejected(api):
    """PRD §3.9: "A `BONUS` award echoes the supplied `amount_cents`, provided it
    does not exceed the program's `bonus_cap_cents`; an over-cap bonus is
    rejected with `ERR_AWARD_AMOUNT_CAP`."
    PRD §3.1: "`bonus_cap_cents` defaults to 100000 as the ceiling on
    discretionary bonus awards"

    Design: Corner/validations/bonus_above_cap_rejected
    """
    program, asset = setup_active_program(criticality="MEDIUM")
    researcher = register_researcher()
    report = create_validated_report(
        program, asset, researcher, impact=2, exploitability=2, affected_scope=2,
        vulnerability_class="OTHER")
    over = api.create_award(
        {"report_id": report["id"], "award_type": "BONUS", "amount_cents": 100_001},
        TRIAGER)
    validate_error(over, ApiErrorId.ERR_AWARD_AMOUNT_CAP)
    at_cap = create_award(report["id"], "BONUS", amount_cents=100_000)
    assert at_cap["amount_cents"] == 100_000
