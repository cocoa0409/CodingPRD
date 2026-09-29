"""Who may act: role lists, shared authority, identity resolution and separation.

The first test walks four operations that exactly one role holds, each refused for
one role and then accepted for its holder.  The rest cover the endpoint two roles
share, the identity a lodging operator's header must resolve to, the two same-actor
prohibitions, and the line between what the public may read and what it may not.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ASSESSMENT_STATEMENT_NOT_FOUND,
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_OPERATOR_IDENTITY_UNKNOWN,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_null_fields,
)
from test_helpers.test_users import (
    ADMIN,
    ADMIN_2,
    ADMIN_USER_ID,
    AUDITOR,
    AUDITOR_2,
    AUDITOR_USER_ID,
    BOARD_MEMBER,
    BOARD_MEMBER_USER_ID,
    DMO_LIAISON,
    HEARING_OFFICER,
    HEARING_OFFICER_USER_ID,
    PUBLIC_VIEWER,
    UNKNOWN_OPERATOR,
    operator_headers,
)


def _first_statement_filed(api, ctx=None):
    """A period of four statements of which only the core hotel's is filed, at 2,000
    room nights on 41,225,000 cents of revenue, which assesses 824,500."""
    ctx = ctx if ctx is not None else fx.period_with_statements(api)
    fx.file_statement(api, ctx, "st1_id", "b1_id", 2000, 41225000)
    return ctx


# --------------------------------------------------------------------------
# Four operations, each held by exactly one role
# --------------------------------------------------------------------------
def test_four_single_role_operations_refuse_a_neighbour_and_accept_their_holder(api):
    """A board action, an audit, a dispute resolution and a transparency filing are
    each attempted by a role that holds a different part of the surface and then by
    the role that holds them.  Every refusal is the role check and nothing else: the
    target row is untouched, and the identical request then succeeds.

    PRD 2.1: "When the headers are well-formed but the declared role does not appear
    in the authorized-role list published for the requested operation in section 4,
    the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    PRD 4: "The Authorized Role(s) column is exhaustive and is the authoritative
    input to the role check described in section 2.1; a caller whose X-User-Role is
    absent from a row is refused with ERR_FORBIDDEN_ROLE".

    Design: Corner/rbac/role_exclusive_operations_cannot_be_performed_by_other_roles
    """
    ctx = _first_statement_filed(api)
    fx.draft_work_plan(api, ctx)
    fx.file_dispute(api, ctx, statement_key="st1_id", business_key="b1_id")
    fx.open_dispute_review(api, ctx)
    fx.set_clock(api, "2026-11-16T00:00:00Z")
    fx.close_period(api, ctx)

    sponsor = f.board_action_payload("SPONSOR", "put before the board")
    validate_error(
        api.board_action(ctx.wp_id, sponsor, headers=DMO_LIAISON),
        ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )
    untouched_plan = validate_success(api.get_work_plan(ctx.wp_id, headers=ADMIN))
    assert_fields(untouched_plan, status="DRAFT", version=1)
    assert_null_fields(untouched_plan, "sponsor_user_id")
    sponsored = validate_success(api.board_action(ctx.wp_id, sponsor, headers=BOARD_MEMBER))
    assert_fields(sponsored, status="BOARD_REVIEW", sponsor_user_id=BOARD_MEMBER_USER_ID)

    audit = f.audit_payload(audit_note="independent field audit")
    validate_error(
        api.audit_certify_statement(ctx.st1_id, audit, headers=HEARING_OFFICER),
        ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )
    untouched_statement = validate_success(
        api.get_assessment_statement(ctx.st1_id, headers=ADMIN)
    )
    assert_fields(untouched_statement, filing_status="FILED")
    assert_null_fields(untouched_statement, "audited_by_user_id", "final_assessment_cents")
    audited = validate_success(
        api.audit_certify_statement(ctx.st1_id, audit, headers=AUDITOR)
    )
    assert_fields(
        audited,
        filing_status="AUDITED",
        audited_by_user_id=AUDITOR_USER_ID,
        final_assessment_cents=824500,
        effective_assessment_cents=824500,
    )

    upheld = f.resolution_payload("UPHELD", resolution_note="the basis stands")
    validate_error(
        api.resolve_dispute(ctx.dsp_id, upheld, headers=AUDITOR),
        ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )
    untouched_dispute = validate_success(api.get_dispute(ctx.dsp_id, headers=ADMIN))
    assert_fields(untouched_dispute, status="UNDER_REVIEW")
    assert_null_fields(untouched_dispute, "resolved_by_user_id")
    resolved = validate_success(
        api.resolve_dispute(ctx.dsp_id, upheld, headers=HEARING_OFFICER)
    )
    assert_fields(
        resolved,
        status="RESOLVED_UPHELD",
        resolved_by_user_id=HEARING_OFFICER_USER_ID,
        granted_adjustment_cents=0,
    )

    record = f.transparency_record_payload(
        ctx.d_id,
        record_type="ANNUAL_REPORT",
        fiscal_year=2027,
        scheduled_for="2026-12-15T00:00:00Z",
        required_by="2027-01-15T00:00:00Z",
    )
    validate_error(
        api.create_transparency_record(record, headers=BOARD_MEMBER),
        ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )
    _, before = validate_paginated(
        api.list_district_transparency_records(ctx.d_id, headers=ADMIN)
    )
    assert before["total_count"] == 0, (
        "the refused filing must not have created a record, got %r" % (before,)
    )
    scheduled = validate_success(
        api.create_transparency_record(record, headers=ADMIN), expected_status=201
    )
    assert_fields(
        scheduled, status="SCHEDULED", engaged_by_user_id=ADMIN_USER_ID, fiscal_year=2027
    )

    final_statement = validate_success(
        api.get_assessment_statement(ctx.st1_id, headers=ADMIN)
    )
    assert_fields(final_statement, effective_assessment_cents=824500)


# --------------------------------------------------------------------------
# One endpoint, two holders, and the ownership row that binds only one of them
# --------------------------------------------------------------------------
def test_the_operator_files_only_its_own_statement_while_the_administrator_files_any(api):
    """Three filings on one endpoint end three different ways.  The core hotel files
    its own statement, the administrator files the limited-service property's on its
    behalf, and the limited-service property filing the boutique's statement is
    refused, because ownership is compared only for the operator role.

    PRD 2.1: "When X-User-Role is LodgingOperator, X-User-ID is the id of the acting
    lodging business, and ownership checks on any resource that references a lodging
    business compare that resource's lodging_business_id to X-User-ID."

    PRD 3.3: "An operator files its period figures by supplying reported_room_nights
    and reported_gross_room_revenue_cents, each an integer that may not be negative. A
    DistrictAdministrator may file on the operator's behalf."

    Design: Corner/rbac/shared_filing_authority_covers_the_operator_and_the_administrator_while_ownership_still_binds
    """
    ctx = fx.period_with_statements(api)

    own = validate_success(
        api.file_statement(
            ctx.st1_id,
            f.filing_payload(2000, 41225000),
            headers=operator_headers(ctx.b1_id),
        ),
    )
    assert_fields(own, filing_status="FILED", provisional_assessment_cents=824500)
    assert_instant_equals(own["filed_at"], "2026-08-01T00:00:00Z", "filed_at")

    on_behalf = validate_success(
        api.file_statement(ctx.st2_id, f.filing_payload(600, 20000000), headers=ADMIN),
    )
    assert_fields(
        on_behalf,
        filing_status="FILED",
        provisional_assessment_cents=340000,
        lodging_business_id=ctx.b2_id,
    )

    validate_error(
        api.file_statement(
            ctx.st3_id,
            f.filing_payload(400, 12000000),
            headers=operator_headers(ctx.b2_id),
        ),
        ERR_NOT_RESOURCE_OWNER,
        expected_status=403,
    )
    untouched = validate_success(api.get_assessment_statement(ctx.st3_id, headers=ADMIN))
    assert_fields(untouched, filing_status="NOT_FILED", version=1)
    assert_null_fields(untouched, "reported_room_nights", "reported_gross_room_revenue_cents")

    period = validate_success(api.get_assessment_period(ctx.ap_id, headers=ADMIN))
    assert_fields(period, billed_total_cents=1164500)


# --------------------------------------------------------------------------
# The operator header is itself a foreign key
# --------------------------------------------------------------------------
def test_an_unresolvable_operator_header_is_answered_before_the_path_is_looked_up(api):
    """The same absent statement identifier is filed against twice.  Under a header
    naming no lodging business the answer is the identity failure; under a real
    property's header the same path answers not found.  Nothing is written either way.

    PRD 2.1: "If the supplied X-User-ID matches no existing lodging business at all,
    the request is rejected with ERR_OPERATOR_IDENTITY_UNKNOWN (HTTP 403) before any
    path identifier is looked up; this check applies on every operation whose
    authorized-role list contains LodgingOperator."

    Design: Corner/rbac/an_unknown_operator_identity_is_forbidden_before_any_path_id_is_resolved
    """
    ctx = fx.period_with_statements(api)
    district_before = validate_success(api.get_district(ctx.d_id))
    filing = f.filing_payload(2000, 41225000)

    validate_error(
        api.file_statement(NON_EXISTENT_UUID, filing, headers=UNKNOWN_OPERATOR),
        ERR_OPERATOR_IDENTITY_UNKNOWN,
        expected_status=403,
    )
    validate_error(
        api.file_statement(NON_EXISTENT_UUID, filing, headers=operator_headers(ctx.b1_id)),
        ERR_ASSESSMENT_STATEMENT_NOT_FOUND,
        expected_status=404,
    )

    statement = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(statement, filing_status="NOT_FILED", version=1)
    district_after = validate_success(api.get_district(ctx.d_id))
    assert_fields(district_after, version=district_before["version"])
    _, meta = validate_paginated(api.list_period_statements(ctx.ap_id, headers=ADMIN))
    assert meta["total_count"] == 4, (
        "neither refused call may add a statement, got %r" % (meta,)
    )


# --------------------------------------------------------------------------
# One auditor may not both audit and certify
# --------------------------------------------------------------------------
def test_the_auditor_who_audited_a_statement_cannot_also_certify_it(api):
    """Both halves of the audit belong to the independent auditor alone, so the
    refusal here cannot be about the role: the first auditor is barred from certifying
    what it audited, and a second auditor holding the very same role certifies it.

    PRD 3.3: "With action CERTIFY, the statement moves AUDITED to CERTIFIED and its
    amount is locked permanently. Certification requires that no dispute on the
    statement is still live — no dispute of that statement may be in SUBMITTED,
    UNDER_REVIEW or INFO_REQUESTED — and it requires an X-User-ID different from the
    stored audited_by_user_id, failing with ERR_SEGREGATION_OF_DUTIES otherwise."

    Design: Corner/rbac/the_same_auditor_cannot_audit_and_then_certify_one_statement
    """
    ctx = _first_statement_filed(api)
    fx.set_clock(api, "2026-11-16T00:00:00Z")
    fx.close_period(api, ctx)
    audited = fx.audit_statement(api, ctx, "st1_id")
    assert_fields(
        audited,
        filing_status="AUDITED",
        audited_by_user_id=AUDITOR_USER_ID,
        final_assessment_cents=824500,
        effective_assessment_cents=824500,
    )

    certify = f.certify_statement_payload("locking the audited amount")
    validate_error(
        api.audit_certify_statement(ctx.st1_id, certify, headers=AUDITOR),
        ERR_SEGREGATION_OF_DUTIES,
        expected_status=403,
    )
    still_audited = validate_success(
        api.get_assessment_statement(ctx.st1_id, headers=ADMIN)
    )
    assert_fields(
        still_audited,
        filing_status="AUDITED",
        audited_by_user_id=AUDITOR_USER_ID,
        final_assessment_cents=824500,
    )

    certified = validate_success(
        api.audit_certify_statement(ctx.st1_id, certify, headers=AUDITOR_2)
    )
    assert_fields(
        certified,
        filing_status="CERTIFIED",
        audited_by_user_id=AUDITOR_USER_ID,
        final_assessment_cents=824500,
        effective_assessment_cents=824500,
    )


# --------------------------------------------------------------------------
# The engaging administrator is barred from both advances of an audit
# --------------------------------------------------------------------------
def test_the_administrator_who_engaged_a_financial_audit_may_neither_complete_nor_publish_it(api):
    """A financial audit engaged by one administrator is refused twice in its own
    hands, once at completion and again at publication, and each refused advance is
    carried through immediately afterwards by a second administrator holding exactly
    the same role.

    PRD 3.9: "On a record whose record_type is FINANCIAL_AUDIT, both the COMPLETED
    and the PUBLISHED advances additionally require the acting X-User-ID to differ
    from the stored engaged_by_user_id, and equality is refused with
    ERR_SEGREGATION_OF_DUTIES. The administrator who engaged the audit may neither
    record its completion nor put its opinion on the public record."

    Design: Corner/rbac/the_administrator_who_engaged_the_financial_audit_cannot_complete_or_publish_it
    """
    ctx = fx.active_district(api)
    scheduled = fx.schedule_transparency_record(
        api,
        ctx,
        record_type="FINANCIAL_AUDIT",
        fiscal_year=2027,
        scheduled_for="2026-08-20T00:00:00Z",
        required_by="2026-09-30T00:00:00Z",
    )
    assert_fields(scheduled, status="SCHEDULED", engaged_by_user_id=ADMIN_USER_ID)
    fx.advance_transparency_record(api, ctx, "NOTICED")
    fx.set_clock(api, "2026-08-20T00:00:00Z")

    validate_error(
        api.advance_transparency_record(
            ctx.tr_id, f.advance_transparency_payload("COMPLETED"), headers=ADMIN
        ),
        ERR_SEGREGATION_OF_DUTIES,
        expected_status=403,
    )
    record = validate_success(api.get_transparency_record(ctx.tr_id))
    assert_fields(record, status="NOTICED")
    assert_null_fields(record, "completed_on")

    completed = fx.advance_transparency_record(api, ctx, "COMPLETED", headers=ADMIN_2)
    assert_fields(completed, status="COMPLETED", engaged_by_user_id=ADMIN_USER_ID)
    assert_instant_equals(completed["completed_on"], "2026-08-20T00:00:00Z", "completed_on")

    validate_error(
        api.advance_transparency_record(
            ctx.tr_id,
            f.advance_transparency_payload("PUBLISHED", "FY2027-audit-opinion.pdf"),
            headers=ADMIN,
        ),
        ERR_SEGREGATION_OF_DUTIES,
        expected_status=403,
    )
    record = validate_success(api.get_transparency_record(ctx.tr_id))
    assert_fields(record, status="COMPLETED")
    assert_null_fields(record, "published_on", "document_reference")

    published = fx.advance_transparency_record(
        api,
        ctx,
        "PUBLISHED",
        document_reference="FY2027-audit-opinion.pdf",
        headers=ADMIN_2,
    )
    assert_fields(
        published, status="PUBLISHED", document_reference="FY2027-audit-opinion.pdf"
    )
    assert_instant_equals(published["published_on"], "2026-08-20T00:00:00Z", "published_on")

    district = validate_success(api.get_district(ctx.d_id))
    assert_fields(district, transparency_standing="COMPLIANT")


# --------------------------------------------------------------------------
# What the public may see, and where the public record stops
# --------------------------------------------------------------------------
def test_the_public_reads_the_money_and_the_record_but_not_the_roll_or_the_statements(api):
    """Two public reads answer without any headers at all while two neighbouring
    reads of the same district refuse the public viewer outright, which shows the
    published totals are open precisely because the underlying roll is not.

    PRD 2.1: "Ten read operations are published for the general public and are
    served with no headers at all, because publication is the point of them: the
    district list, a single district, a district's financial summary, a district's
    petition drives, a district's annual work plans, a district's transparency
    records, a single petition drive, a single annual work plan, a single marketing
    program, and a single transparency record."

    PRD 2.1: "When the headers are well-formed but the declared role does not appear
    in the authorized-role list published for the requested operation in §4, the
    request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    PRD 4: "GET /districts/{id}/lodging-businesses | Lodging businesses on the
    district roll, optionally filtered by assessability status or boundary zone. |
    DistrictAdministrator, BoardMember, IndependentAuditor, HearingOfficer" and "GET
    /assessment-periods/{id}/statements | Statements of a period, filterable by
    owning business, filing status and payment status, in created_at ascending
    order. | DistrictAdministrator, IndependentAuditor, HearingOfficer"

    Design: Corner/rbac/public_viewer_cannot_read_the_assessment_roll_or_any_statement
    """
    ctx = _first_statement_filed(api)

    summary = validate_success(api.get_district_financial_summary(ctx.d_id, headers=None))
    assert_fields(
        summary,
        district_id=ctx.d_id,
        billed_total_cents=824500,
        collected_to_date_cents=0,
        outstanding_total_cents=824500,
        statement_count=4,
    )

    records, meta = validate_paginated(
        api.list_district_transparency_records(ctx.d_id, headers=None)
    )
    assert records == [], "a district with no transparency records must list none"
    assert meta["total_count"] == 0, (
        "total_count must be 0 for a district with no transparency records, got %r" % (meta,)
    )

    validate_error(
        api.list_district_lodging_businesses(ctx.d_id, headers=PUBLIC_VIEWER),
        ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )
    validate_error(
        api.list_period_statements(ctx.ap_id, headers=PUBLIC_VIEWER),
        ERR_FORBIDDEN_ROLE,
        expected_status=403,
    )
