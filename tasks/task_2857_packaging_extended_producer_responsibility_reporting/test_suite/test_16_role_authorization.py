"""Role authorisation: the allow-lists, the denials and the ownership dimension.

Authorisation is checked before path existence and before state, so a wrong-role
call and a wrong-owner call both answer from their own layer without disturbing
the resources they named.
"""

from test_helpers import (
    ApiErrorId,
    EngagementStatus,
    FeePaymentStatus,
    FeeVariant,
    MembershipStatus,
    REGULATOR_HEADERS,
    REGULATOR_USER_ID,
    ReportFeeStatus,
    SubmissionStatus,
    VERIFIER_HEADERS,
    VERIFIER_USER_ID,
    assert_engagement,
    assert_membership,
    assert_no_version_movement,
    assert_report,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

NON_EXISTENT_REPORT_ID = "66666666-6666-4666-8666-666666666666"
SECOND_HALF_PERIOD = dict(
    period_label="CA-2026-H2",
    data_start="2027-01-01",
    data_end="2027-07-01",
    submission_open="2026-07-15T00:00:00Z",
    submission_deadline="2027-06-30T23:59:59Z",
    correction_window_days=30,
)


# ---------------------------------------------------------------------------
# One exclusive operation from each of the four allow-lists, in sequence
# ---------------------------------------------------------------------------
def test_each_role_performs_the_operation_only_it_is_allowed(api):
    """Four consecutive calls, one per role, all land on the same fixture.

    The regulator opens a second period, the producer's officer opens a report in
    it, the organisation's administrator prices the first report at fifty cents and
    the regulator engages a verifier who starts the fieldwork; the assessment
    survives the move into verification, so the allow-lists are permissive where
    the endpoint table says they are.

    Design: Corner/rbac/each_role_can_perform_its_own_exclusive_operations
    """
    chain = fx.base_ca_chain(api)
    officer_headers, admin_headers = chain["officer_headers"], chain["admin_headers"]

    second_period = validate_success(
        api.create_reporting_period(
            chain["program"]["id"],
            f.reporting_period_payload(**SECOND_HALF_PERIOD),
            REGULATOR_HEADERS,
        ),
        201,
    )

    second_report = validate_success(
        api.create_report(
            f.report_payload(chain["registration"]["id"], second_period["id"]),
            officer_headers,
        ),
        201,
    )
    assert_report(second_report, submission_status=SubmissionStatus.DRAFT)

    assessed = validate_success(
        api.assess_report(
            chain["report"]["id"], f.assess_payload(FeeVariant.FINAL), admin_headers
        )
    )
    assert_report(
        assessed, fee_status=ReportFeeStatus.FINAL, fee_subtotal_cents=50
    )

    engagement = validate_success(
        api.create_engagement(
            f.engagement_payload(
                chain["report"]["id"], VERIFIER_USER_ID, "2026-08-05", "2026-08-10"
            ),
            REGULATOR_HEADERS,
        ),
        201,
    )
    assert_engagement(
        engagement,
        status=EngagementStatus.ASSIGNED,
        assigned_by_user_id=REGULATOR_USER_ID,
        verifier_user_id=VERIFIER_USER_ID,
    )
    assert_report(
        validate_success(api.get_report(chain["report"]["id"], officer_headers)),
        submission_status=SubmissionStatus.UNDER_VERIFICATION,
    )

    started = validate_success(
        api.start_engagement(engagement["id"], None, VERIFIER_HEADERS)
    )

    assert_engagement(started, status=EngagementStatus.IN_PROGRESS)
    assert_report(
        validate_success(api.get_report(chain["report"]["id"], officer_headers)),
        submission_status=SubmissionStatus.UNDER_VERIFICATION,
        fee_status=ReportFeeStatus.FINAL,
        fee_subtotal_cents=50,
    )


# ---------------------------------------------------------------------------
# The same operations attempted from the wrong role
# ---------------------------------------------------------------------------
def test_wrong_role_calls_are_refused_before_the_path_is_resolved(api):
    """Four cross-role attempts answer 403, one of them for a report that does not exist.

    Onboarding a producer, pricing a report, filing a report and issuing an
    invoice each belong to exactly one role, so each attempt from another role is
    refused; the invoice attempt names an identifier that exists nowhere and still
    answers with the authorisation refusal, because the role check outranks the
    existence check. Nothing is created and the report stays unassessed.

    Design: Corner/rbac/cross_role_calls_on_other_roles_exclusive_operations_are_rejected
    """
    chain = fx.base_ca_chain(api)
    officer_headers, admin_headers = chain["officer_headers"], chain["admin_headers"]

    validate_error(
        api.create_producer(
            f.producer_payload(
                legal_name="Unauthorised Create",
                annual_gross_revenue_usd=100000,
                brand_owner_flag=True,
                contact_email="x@x.example",
            ),
            admin_headers,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api.assess_report(
            chain["report"]["id"], f.assess_payload(FeeVariant.FINAL), officer_headers
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api.create_report(
            f.report_payload(chain["registration"]["id"], chain["period"]["id"]),
            REGULATOR_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    unknown_report = validate_error(
        api.create_invoice(
            f.invoice_payload(NON_EXISTENT_REPORT_ID, chain["membership"]["id"]),
            VERIFIER_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    assert unknown_report["error_id"] != ApiErrorId.REPORT_NOT_FOUND.value

    assert_report(
        validate_success(api.get_report(chain["report"]["id"], officer_headers)),
        fee_status=ReportFeeStatus.UNASSESSED,
        fee_subtotal_cents=0,
    )
    producers, producer_meta = validate_paginated(api.list_producers(REGULATOR_HEADERS))
    assert producer_meta["total_count"] == 1
    assert [row["id"] for row in producers] == [chain["producer"]["id"]]
    invoices, invoice_meta = validate_paginated(api.list_invoices(REGULATOR_HEADERS))
    assert invoice_meta["total_count"] == 0
    assert invoices == []


# ---------------------------------------------------------------------------
# Ownership: the two entity-backed identities cannot reach across
# ---------------------------------------------------------------------------
def test_peer_producers_and_peer_organisations_cannot_touch_foreign_rows(api):
    """Ownership is answered before state, and a shared read still serves both peers.

    A peer producer's officer submitting someone else's already-submitted report is
    refused as a non-owner rather than for the report's position; a peer
    organisation can neither price that report nor decide the other organisation's
    membership; and both peers still read the state program, which has no
    ownership dimension at all. The report's version never moves.

    Design: Corner/rbac/peer_producers_and_peer_pros_cannot_touch_each_others_resources
    """
    chain = fx.base_ca_chain(api)
    officer_headers = chain["officer_headers"]
    peer_producer = fx.make_producer(
        api,
        legal_name="Peerless Packaging Inc",
        annual_gross_revenue_usd=2000000,
        brand_owner_flag=True,
        contact_email="epr@peerless.example",
    )
    peer_pro = fx.make_pro(
        api, name="Rival Stewardship Group", contact_email="ops@rival.example"
    )
    peer_officer_headers = fx.officer(peer_producer)
    peer_admin_headers = fx.admin(peer_pro)
    before = validate_success(api.get_report(chain["report"]["id"], officer_headers))

    denied = validate_error(
        api.submit_report(chain["report"]["id"], None, peer_officer_headers),
        ApiErrorId.NOT_RESOURCE_OWNER,
        403,
    )
    assert denied["error_id"] != ApiErrorId.REPORT_NOT_IN_DRAFT.value

    validate_error(
        api.assess_report(
            chain["report"]["id"], f.assess_payload(FeeVariant.FINAL), peer_admin_headers
        ),
        ApiErrorId.NOT_RESOURCE_OWNER,
        403,
    )
    validate_error(
        api.decide_membership(
            chain["membership"]["id"],
            f.decision_payload("REJECT", "hostile decision by a foreign organisation"),
            peer_admin_headers,
        ),
        ApiErrorId.NOT_RESOURCE_OWNER,
        403,
    )

    assert_membership(
        validate_success(api.get_membership(chain["membership"]["id"], officer_headers)),
        status=MembershipStatus.ACTIVE,
        fee_payment_status=FeePaymentStatus.PAID,
    )
    validate_success(api.get_state_program(chain["program"]["id"], peer_officer_headers))
    validate_success(api.get_state_program(chain["program"]["id"], peer_admin_headers))

    after = validate_success(api.get_report(chain["report"]["id"], officer_headers))
    assert_report(
        after,
        submission_status=SubmissionStatus.SUBMITTED,
        fee_status=ReportFeeStatus.UNASSESSED,
    )
    assert_no_version_movement(before, after, "report")


# ---------------------------------------------------------------------------
# Segregation of duties on the engagement
# ---------------------------------------------------------------------------
def test_neither_the_filing_producer_nor_the_assigning_regulator_may_verify(api):
    """Both self-dealing shapes are refused and only a third party is engaged.

    Naming the report's own submitter as the verifier is refused, and so is naming
    the assigning regulator's own identifier; while both attempts fail no
    engagement exists at all and the report stays submitted, and only the
    independent verifier's assignment moves it into verification.

    Design: Corner/rbac/the_assigning_regulator_and_the_filing_producer_cannot_be_the_verifier
    """
    chain = fx.base_ca_chain(api)
    officer_headers = chain["officer_headers"]
    report_id = chain["report"]["id"]
    assert chain["report"]["submitted_by_user_id"] == chain["producer"]["id"]

    for self_dealing_id in (chain["producer"]["id"], REGULATOR_USER_ID):
        validate_error(
            api.create_engagement(
                f.engagement_payload(
                    report_id, self_dealing_id, "2026-08-05", "2026-08-10"
                ),
                REGULATOR_HEADERS,
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES,
            422,
        )

    assert_report(
        validate_success(api.get_report(report_id, officer_headers)),
        submission_status=SubmissionStatus.SUBMITTED,
    )
    engagements, meta = validate_paginated(
        api.list_engagements(REGULATOR_HEADERS, {"packaging_report_id": report_id})
    )
    assert meta["total_count"] == 0
    assert engagements == []

    accepted = validate_success(
        api.create_engagement(
            f.engagement_payload(report_id, VERIFIER_USER_ID, "2026-08-05", "2026-08-10"),
            REGULATOR_HEADERS,
        ),
        201,
    )

    assert_engagement(
        accepted,
        status=EngagementStatus.ASSIGNED,
        verifier_user_id=VERIFIER_USER_ID,
        assigned_by_user_id=REGULATOR_USER_ID,
        round_index=1,
    )
    assert_report(
        validate_success(api.get_report(report_id, officer_headers)),
        submission_status=SubmissionStatus.UNDER_VERIFICATION,
    )
