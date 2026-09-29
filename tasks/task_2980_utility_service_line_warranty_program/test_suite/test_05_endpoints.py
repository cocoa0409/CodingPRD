"""Endpoint-surface behaviour of the Utility Service Line Warranty Program API.

Each test here exercises one endpoint of PRD §4 end to end: the two bulk actions
whose response is a purpose-built report rather than an entity (the mail drop and
the nightly run), the two computed reads whose derived figures must be recomputed
on every GET, the conditional shapes of enrollment creation and dispatch
creation, the escalation that undoes a filed complaint response, and the
create/read/list surface of the contractor registry.

Every temporal assertion is pinned against the logical clock of PRD §2.5, which
the setup moves explicitly; no test reads a wall clock.
"""

from prd_bench_local_runner.testing import validate_error_is_one_of, validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_CAMPAIGN_NOT_FOUND,
    ERR_CAMPAIGN_NOT_MAILED,
    ERR_CONTRACTOR_NOT_FOUND,
    ERR_ENROLLMENT_NOT_ACTIVE,
    ERR_INVALID_CAMPAIGN_STATE,
    ERR_INVALID_CLAIM_STATE,
    ERR_INVALID_COMPLAINT_STATE,
    ERR_INVALID_DISPATCH_STATE,
    ERR_MAILING_SUPPRESSED,
)
from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_created_resource,
    assert_date_only,
    assert_drop_counts_agree,
    assert_drop_summary_shape,
    assert_fields,
    assert_ids_in_order,
    assert_instant,
    assert_ledger_common_fields,
    assert_list_envelope,
    assert_nightly_lists_empty,
    assert_nightly_report_shape,
    assert_nulls,
    assert_object_envelope,
    assert_refused,
)
from test_helpers.constants import (
    CLOCK_COVERAGE_ACTIVE,
    CLOCK_ENROLLMENT_DAY,
    CLOCK_START,
    COVERAGE_EFFECTIVE_AT,
    ENROLLMENT_TERM_START,
    ESTIMATED_HOURS_BY_LINE,
    ESTIMATED_MATERIALS_CENTS,
    QUANTITY_CAP_REASON,
    SLA_HOURS,
)
from test_helpers.test_users import (
    BILLING_OPS,
    CLAIMS_ADJUSTER,
    CUSTOMER_SERVICE_REP,
    MARKETING_OPS,
    OPERATIONS_ADMIN,
    PLATFORM_ADMIN,
    REGULATORY_AFFAIRS,
    make_network_contractor_headers,
)

# A well-formed UUID that matches no row of any collection.
ABSENT_UUID = "00000000-0000-4000-8000-000000000000"

# The two clock positions the drop recipes below use.
CLOCK_DROP_DAY = "2026-08-20T00:00:00.000Z"
DROP_DATE = "2026-08-20"


class TestRegulatorComplaintEscalation:
    """POST /regulator-complaints/{complaintId}/escalation (PRD §3.8)."""

    def test_complaint_escalation_reopens_an_unsubstantiated_closure(self, api):
        """Escalation is legal from exactly one status and wipes the filed finding.

        PRD: "Escalation moves `CLOSED_UNSUBSTANTIATED → ESCALATED`, increments `escalation_count`, and **clears `responded_at`, `response_summary`, `disposition`, `remedy_type` and `remedy_amount_cents` all back to null**, so the file genuinely reopens rather than carrying a stale finding."

        Design: Corner/endpoints/complaint_escalation_reopens_an_unsubstantiated_closure
        """
        world = fixtures.active_partner_with_product(api)
        premises = fixtures.create_premises(api, world["partner_id"])
        fixtures.set_clock(api, CLOCK_ENROLLMENT_DAY)
        enrollment = fixtures.create_enrollment(
            api, premises["id"], world["product_id"], premises["version"],
            prepaid_amount_cents=None,
        )
        fixtures.set_clock(api, CLOCK_COVERAGE_ACTIVE)
        fixtures.run_nightly(api)

        complaint = fixtures.create_complaint(
            api, world["partner_id"],
            enrollment_id=enrollment["id"],
            allegation="Homeowner says the waiting period was never disclosed.",
        )
        assert_created_resource(complaint)
        assert_fields(complaint, {"status": "OPEN", "escalation_count": 0})
        assert_instant(complaint["received_at"], CLOCK_COVERAGE_ACTIVE, "received_at")
        # PUC's base window is 10 days and no claim is cited, so no expedited floor.
        assert_instant(
            complaint["response_due_at"], "2026-09-20T08:00:00.000Z", "response_due_at"
        )

        at_intake = validate_success(api.get_premises(premises["id"], MARKETING_OPS))
        assert at_intake["regulator_hold"] is True, (
            "citing an enrollment sets regulator_hold on its address"
        )

        # Escalation before any response: OPEN is not CLOSED_UNSUBSTANTIATED.
        too_early = api.escalate_complaint(
            complaint["id"],
            factories.escalation_payload(escalation_note="The regulator is not satisfied."),
            REGULATORY_AFFAIRS,
        )
        assert_refused(too_early, ERR_INVALID_COMPLAINT_STATE)
        assert fixtures.refresh_complaint(api, complaint["id"])["version"] == 1, (
            "a refused escalation writes nothing"
        )

        responded = validate_success(
            api.respond_to_complaint(
                complaint["id"],
                factories.complaint_response_payload(
                    "UNSUBSTANTIATED", "APOLOGY_ONLY", complaint["version"],
                    response_summary="Disclosure was mailed with the welcome pack.",
                ),
                REGULATORY_AFFAIRS,
            ),
            200,
        )
        assert_fields(responded, {
            "status": "CLOSED_UNSUBSTANTIATED",
            "disposition": "UNSUBSTANTIATED",
            "remedy_type": "APOLOGY_ONLY",
            "days_overdue": 0,
            "version": 2,
        })
        assert_instant(responded["responded_at"], CLOCK_COVERAGE_ACTIVE, "responded_at")

        after_close = validate_success(api.get_premises(premises["id"], MARKETING_OPS))
        assert after_close["regulator_hold"] is False, (
            "the response re-derives regulator_hold and no open complaint remains"
        )

        escalated = validate_success(
            api.escalate_complaint(
                complaint["id"],
                factories.escalation_payload(
                    escalation_note="The regulator rejects the finding and demands a fresh response."
                ),
                REGULATORY_AFFAIRS,
            ),
            200,
        )
        assert_fields(escalated, {
            "status": "ESCALATED",
            "escalation_count": 1,
            "version": 3,
        })
        assert_nulls(escalated, (
            "responded_at",
            "response_summary",
            "disposition",
            "remedy_type",
            "remedy_amount_cents",
        ))
        # The deadline is anchored to received_at; reopening does not restart it.
        assert_instant(
            escalated["response_due_at"], "2026-09-20T08:00:00.000Z", "response_due_at"
        )

        after_escalation = validate_success(api.get_premises(premises["id"], MARKETING_OPS))
        assert after_escalation["regulator_hold"] is True, (
            "the hold is restored because the reopened complaint cites a policy"
        )

        twice = api.escalate_complaint(
            complaint["id"],
            factories.escalation_payload(escalation_note="Escalating again."),
            REGULATORY_AFFAIRS,
        )
        assert_refused(twice, ERR_INVALID_COMPLAINT_STATE)

        final = validate_success(api.get_complaint(complaint["id"], REGULATORY_AFFAIRS))
        assert_fields(final, {"status": "ESCALATED", "escalation_count": 1, "version": 3})
        assert_instant(
            final["response_due_at"], "2026-09-20T08:00:00.000Z", "response_due_at"
        )


class TestMailDropBulkAction:
    """POST /campaigns/{campaignId}/mail-drop (PRD §3.2)."""

    def test_mail_drop_is_a_bulk_action_that_reports_per_premises_outcomes(self, api):
        """A zero-quantity drop still mails the campaign and suppresses every survivor.

        PRD: "The degenerate case behaves the same way rather than erroring: an `approved_quantity` of 0 mails nobody, every survivor is suppressed with `QUANTITY_CAP`, and the campaign still reaches `MAILED` with `mailed_count` 0."

        Design: Corner/endpoints/mail_drop_is_a_bulk_action_that_reports_per_premises_outcomes
        """
        world = fixtures.active_partner_with_product(api)
        first = fixtures.create_premises(api, world["partner_id"], street_address="12 Alder St")
        second = fixtures.create_premises(api, world["partner_id"], street_address="14 Alder St")
        third = fixtures.create_premises(api, world["partner_id"], street_address="16 Alder St")
        for premises in (first, second, third):
            assert_fields(premises, {
                "last_mail_decision": "NOT_EVALUATED",
                "mail_count_current_year": 0,
                "suppression_reason": "NONE",
                "suppressed": False,
                "version": 1,
            })

        campaign = fixtures.create_campaign(
            api, world["partner_id"], world["product_id"],
            name="Autumn curb-stop pilot",
            drop_date=DROP_DATE,
            requested_quantity=3,
        )
        assert_created_resource(campaign)
        assert_fields(campaign, {"status": "DRAFT", "mailed_count": 0, "suppressed_count": 0})
        assert campaign.get("mail_dropped_at") is None, (
            "mail_dropped_at is only stamped by the drop itself"
        )

        fixtures.submit_campaign(api, campaign["id"], note="Three-address pilot for brand review.")
        approved = fixtures.approve_campaign(
            api, campaign["id"], world["partner_id"],
            approved_quantity=0,
            decision_note="Budget was pulled; approve the creative at zero volume.",
        )
        assert_fields(approved, {"status": "APPROVED", "approved_quantity": 0})

        fixtures.set_clock(api, CLOCK_DROP_DAY)
        summary = validate_success(api.mail_drop(campaign["id"], MARKETING_OPS), 200)
        assert_drop_summary_shape(summary)
        assert_drop_counts_agree(summary)
        assert_fields(summary, {
            "campaign_id": campaign["id"],
            "status": "MAILED",
            "mailed_count": 0,
            "suppressed_count": 3,
        })
        assert summary["mailed_premises_ids"] == [], (
            "a zero-quantity drop names no mailed address"
        )
        assert summary["suppressed_by_reason"] == {QUANTITY_CAP_REASON: 3}, (
            "reasons that did not fire are omitted from the map entirely, so the "
            f"capacity outcome is the only key: got {summary['suppressed_by_reason']!r}"
        )

        for premises in (first, second, third):
            after = validate_success(api.get_premises(premises["id"], MARKETING_OPS))
            assert_fields(after, {
                "last_mail_decision": "SUPPRESSED",
                "last_mail_suppression_reason": QUANTITY_CAP_REASON,
                "mail_count_current_year": 0,
                "suppression_reason": "NONE",
                "suppressed": False,
                "version": 2,
            })
            assert after["last_mailed_campaign_id"] is None, (
                "last_mailed_campaign_id stays null until a drop decides to mail the address"
            )

        campaign_after = validate_success(api.get_campaign(campaign["id"], MARKETING_OPS))
        assert_fields(campaign_after, {
            "status": "MAILED",
            "mailed_count": 0,
            "suppressed_count": 3,
        })
        assert_instant(campaign_after["mail_dropped_at"], CLOCK_DROP_DAY, "mail_dropped_at")

        replay = api.mail_drop(campaign["id"], MARKETING_OPS)
        assert_refused(replay, ERR_INVALID_CAMPAIGN_STATE)


class TestNightlyRunReport:
    """POST /_internal/run-nightly (PRD §3.9)."""

    def test_nightly_run_returns_every_declared_id_array_and_is_idempotent_on_a_second_pass(self, api):
        """One pass reports the ids it moved in each phase; the next pass reports nothing.

        PRD: "It carries `ran_at`, the instant the run executed, and then eleven identifier lists, each in the order its phase processed them: `sla_breached_dispatch_ids`, `probated_contractor_ids`, `cancelled_dispatch_ids`, `overdue_complaint_ids`, `escalated_complaint_ids`, `activated_enrollment_ids`, `suspended_enrollment_ids`, `lapsed_enrollment_ids`, `closed_claim_ids`, `renewed_enrollment_ids` and `cap_year_reset_enrollment_ids`."

        Design: Corner/endpoints/nightly_run_returns_every_declared_id_array_and_is_idempotent_on_a_second_pass
        """
        world = fixtures.active_partner_with_product(api)
        premises = fixtures.create_premises(api, world["partner_id"])
        fixtures.set_clock(api, CLOCK_ENROLLMENT_DAY)
        enrollment = fixtures.create_enrollment(
            api, premises["id"], world["product_id"], premises["version"],
            prepaid_amount_cents=None,
        )
        assert_date_only(enrollment["term_start"], "term_start")
        assert enrollment["term_start"] == ENROLLMENT_TERM_START
        assert_instant(
            enrollment["coverage_effective_at"], COVERAGE_EFFECTIVE_AT, "coverage_effective_at"
        )

        # A claim that will be denied the day after enrollment, so the run's
        # claim-closure phase has something to close 30 days later.
        fixtures.set_clock(api, "2026-08-06T00:00:00.000Z")
        claim = fixtures.file_claim(
            api, enrollment["id"],
            defect_location="INSIDE_HOME",
            incident_description="Interior riser is dripping behind the wall.",
        )
        denied = fixtures.deny_claim(
            api, claim["id"], "OWNERSHIP_INELIGIBLE",
            coverage_note="The failure sits inside the home, past the insured boundary.",
        )
        assert_fields(denied, {"status": "DENIED", "version": 2})
        assert_instant(denied["denied_at"], "2026-08-06T00:00:00.000Z", "denied_at")

        # A complaint whose PUC response window will have run out by run time.
        fixtures.set_clock(api, "2026-08-29T00:00:00.000Z")
        complaint = fixtures.create_complaint(
            api, world["partner_id"],
            allegation="The regulator forwarded a service-quality complaint about the network.",
        )
        assert_fields(complaint, {"status": "OPEN", "version": 1})
        assert_instant(
            complaint["response_due_at"], "2026-09-08T00:00:00.000Z", "response_due_at"
        )

        fixtures.set_clock(api, CLOCK_COVERAGE_ACTIVE)
        report = validate_success(api.run_nightly(OPERATIONS_ADMIN), 200)
        assert_nightly_report_shape(report)
        assert_instant(report["ran_at"], CLOCK_COVERAGE_ACTIVE, "ran_at")
        assert report["activated_enrollment_ids"] == [enrollment["id"]]
        assert report["overdue_complaint_ids"] == [complaint["id"]]
        assert report["closed_claim_ids"] == [claim["id"]]
        assert_nightly_lists_empty(report, except_for=(
            "activated_enrollment_ids",
            "overdue_complaint_ids",
            "closed_claim_ids",
        ))

        moved_enrollment = fixtures.refresh_enrollment(api, enrollment["id"])
        assert_fields(moved_enrollment, {"coverage_status": "ACTIVE", "version": 2})
        moved_claim = fixtures.refresh_claim(api, claim["id"])
        assert_fields(moved_claim, {"status": "CLOSED", "version": 3})
        moved_complaint = fixtures.refresh_complaint(api, complaint["id"])
        assert_fields(moved_complaint, {
            "status": "OVERDUE",
            "days_overdue": 2,
            "escalation_count": 0,
            "version": 2,
        })

        # A second pass at the same instant has nothing left to do in any phase.
        second = validate_success(api.run_nightly(PLATFORM_ADMIN), 200)
        assert_nightly_report_shape(second)
        assert_instant(second["ran_at"], CLOCK_COVERAGE_ACTIVE, "ran_at")
        assert_nightly_lists_empty(second)

        assert fixtures.refresh_enrollment(api, enrollment["id"])["version"] == 2, (
            "an idempotent second pass moves no version"
        )
        assert fixtures.refresh_claim(api, claim["id"])["version"] == 3
        assert fixtures.refresh_complaint(api, complaint["id"])["version"] == 2


class TestComputedReads:
    """GET /enrollments/{enrollmentId} and GET /claims/{claimId} (PRD §2.10, §3.5)."""

    def test_enrollment_detail_recomputes_cap_usage_and_reservation_on_read(self, api):
        """The reservation drains and the usage fills across one completion, with no row written.

        PRD: "`annual_benefit_reserved_cents` is a different animal: it is the sum of `estimated_benefit_cents` over the dispatches of this enrollment's claims whose status is `ASSIGNED`, `ACCEPTED` or `ON_SITE` — a forward-looking hold that reduces the available pool before any invoice exists and is released the moment the dispatch leaves the open set."

        Design: Corner/endpoints/enrollment_detail_recomputes_cap_usage_and_reservation_on_read
        """
        world = fixtures.active_partner_with_product(api)
        premises = fixtures.create_premises(api, world["partner_id"])
        fixtures.set_clock(api, CLOCK_ENROLLMENT_DAY)
        enrollment = fixtures.create_enrollment(
            api, premises["id"], world["product_id"], premises["version"],
            prepaid_amount_cents=None,
        )
        assert_date_only(enrollment["cap_year_start"], "cap_year_start")
        assert enrollment["cap_year_start"] == ENROLLMENT_TERM_START, (
            "an ENROLLMENT_ANNIVERSARY cap basis pins the cap year to term_start"
        )

        fixtures.set_clock(api, CLOCK_COVERAGE_ACTIVE)
        fixtures.run_nightly(api)
        contractor = fixtures.create_contractor(
            api, license_number="OR-PL-4411", license_expires_on="2027-06-30",
        )
        claim = fixtures.file_claim(api, enrollment["id"], urgency="URGENT")
        approved = fixtures.approve_claim(api, claim["id"])
        dispatch = fixtures.dispatch_claim_to(
            api, claim["id"], approved["version"], contractor["id"],
            window_start="2026-09-10T09:00:00.000Z",
        )
        expected_estimate = (
            ESTIMATED_HOURS_BY_LINE["WATER_SERVICE_LINE"] * contractor["hourly_rate_cents"]
            + ESTIMATED_MATERIALS_CENTS["WATER_SERVICE_LINE"]
        )
        assert expected_estimate == 228000
        assert dispatch["estimated_benefit_cents"] == expected_estimate, (
            "the provisional estimate is the hours estimate at the contractor's own rate "
            "plus the fixed materials estimate, with no permit or restoration component"
        )
        assert dispatch["status"] == "ASSIGNED"

        first_read = validate_success(api.get_enrollment(enrollment["id"], BILLING_OPS), 200)
        assert_fields(first_read, {
            "annual_benefit_used_cents": 0,
            "annual_benefit_reserved_cents": expected_estimate,
            "cap_status": "WITHIN_CAP",
            "version": 2,
        })
        second_read = validate_success(api.get_enrollment(enrollment["id"], BILLING_OPS), 200)
        assert second_read["version"] == first_read["version"] == 2, (
            "the dispatch's reservation never wrote the enrollment row and neither read mutates it"
        )

        fixtures.accept_dispatch(api, dispatch["id"], contractor["id"])
        completed = validate_success(
            api.create_dispatch_event(
                dispatch["id"],
                factories.complete_event_payload(labor_cents=100000, materials_cents=50000),
                make_network_contractor_headers(contractor["id"]),
            ),
            200,
        )
        assert_fields(completed, {
            "status": "COMPLETED",
            "benefit_paid_cents": 150000,
            "customer_responsibility_cents": 0,
        })

        third_read = validate_success(api.get_enrollment(enrollment["id"], BILLING_OPS), 200)
        assert_fields(third_read, {
            "annual_benefit_used_cents": 150000,
            "annual_benefit_reserved_cents": 0,
            "cap_status": "WITHIN_CAP",
            "version": 2,
        })

        claim_after = validate_success(api.get_claim(claim["id"], BILLING_OPS), 200)
        assert_fields(claim_after, {
            "benefit_paid_cents": 150000,
            "occurrence_used_cents": 150000,
            "status": "PAID",
        })

        rows, meta = assert_list_envelope(
            api.list_ledger_entries(
                BILLING_OPS,
                params={"enrollment_id": enrollment["id"], "ledger_kind": "BENEFIT"},
            ),
            expected_total=1,
        )
        assert len(rows) == 1
        assert_ledger_common_fields(rows[0])
        assert_fields(rows[0], {
            "entry_type": "BENEFIT_CHARGE",
            "ledger_kind": "BENEFIT",
            "amount_cents": 150000,
            "cap_year_start": ENROLLMENT_TERM_START,
        })
        assert meta["has_more"] is False

    def test_claim_detail_derives_eligibility_freshly_on_every_read(self, api):
        """The verdict flips to COVERAGE_INACTIVE without the claim row ever being written.

        PRD: "First, `COVERAGE_INACTIVE` when the policy's `coverage_status` is `SUSPENDED_NONPAY`, `CANCELLED` or `LAPSED`."

        Design: Corner/endpoints/claim_detail_derives_eligibility_freshly_on_every_read
        """
        world = fixtures.active_partner_with_product(api)
        premises = fixtures.create_premises(api, world["partner_id"])
        fixtures.set_clock(api, CLOCK_ENROLLMENT_DAY)
        enrollment = fixtures.create_enrollment(
            api, premises["id"], world["product_id"], premises["version"],
            prepaid_amount_cents=None,
        )
        fixtures.set_clock(api, CLOCK_COVERAGE_ACTIVE)
        fixtures.run_nightly(api)
        claim = fixtures.file_claim(
            api, enrollment["id"],
            incident_description="Curb stop weeping at the shutoff.",
        )
        assert_fields(claim, {
            "eligibility_assessment": "ELIGIBLE",
            "status": "TRIAGE",
            "version": 1,
        })

        first_read = validate_success(api.get_claim(claim["id"], CLAIMS_ADJUSTER), 200)
        assert_fields(first_read, {
            "eligibility_assessment": "ELIGIBLE",
            "status": "TRIAGE",
            "version": 1,
        })

        # The policy falls into arrears, then ages 30 days into suspension.
        arrears = validate_success(
            api.create_billing_event(
                enrollment["id"],
                factories.billing_event_payload("MISSED_PAYMENT", "2026-09-11"),
                BILLING_OPS,
            ),
            200,
        )
        assert arrears["billing_status"] == "PAST_DUE"
        assert_date_only(arrears["past_due_since"], "past_due_since")
        assert arrears["past_due_since"] == "2026-09-11"

        fixtures.set_clock(api, "2026-10-11T00:00:00.000Z")
        report = validate_success(api.run_nightly(OPERATIONS_ADMIN), 200)
        assert_nightly_report_shape(report)
        assert report["suspended_enrollment_ids"] == [enrollment["id"]]
        assert report["lapsed_enrollment_ids"] == [], (
            "sixty whole days have not elapsed since past_due_since"
        )
        assert report["closed_claim_ids"] == [], (
            "the stale-denial phase only closes claims in DENIED"
        )
        assert fixtures.refresh_enrollment(api, enrollment["id"])["coverage_status"] == (
            "SUSPENDED_NONPAY"
        )

        second_read = validate_success(api.get_claim(claim["id"], CLAIMS_ADJUSTER), 200)
        assert_fields(second_read, {
            "eligibility_assessment": "COVERAGE_INACTIVE",
            "status": "TRIAGE",
            "version": 1,
        })

        refused = api.triage_claim(
            claim["id"],
            factories.triage_approval_payload(coverage_note="Covered curb-stop failure."),
            CLAIMS_ADJUSTER,
        )
        assert_refused(refused, ERR_ENROLLMENT_NOT_ACTIVE)

        after_refusal = validate_success(api.get_claim(claim["id"], CLAIMS_ADJUSTER), 200)
        assert_fields(after_refusal, {
            "eligibility_assessment": "COVERAGE_INACTIVE",
            "status": "TRIAGE",
            "version": 1,
        })


class TestEnrollmentCampaignAttribution:
    """POST /enrollments with and without `source_campaign_id` (PRD §3.3)."""

    def test_enrollment_links_a_mailed_campaign_and_records_the_attribution(self, api):
        """The optional link is validated three ways, and omitting it skips all of them.

        PRD: "Furthermore the address must actually have been mailed by that campaign — if the address's `last_mailed_campaign_id` is not that campaign, or its `last_mail_decision` is `SUPPRESSED`, the enrollment is refused with `ERR_MAILING_SUPPRESSED`, because selling to an address the compliance rules suppressed is exactly what the suppression rules exist to prevent."

        Design: Corner/endpoints/enrollment_links_a_mailed_campaign_and_records_the_attribution
        """
        world = fixtures.active_partner_with_product(api)
        mailed_premises = fixtures.create_premises(
            api, world["partner_id"], street_address="12 Alder St"
        )
        capped_premises = fixtures.create_premises(
            api, world["partner_id"], street_address="14 Alder St"
        )
        direct_premises = fixtures.create_premises(
            api, world["partner_id"], street_address="16 Alder St"
        )

        campaign = fixtures.create_campaign(
            api, world["partner_id"], world["product_id"],
            name="Autumn Curb Stop Drop", drop_date=DROP_DATE, requested_quantity=3,
        )
        fixtures.submit_campaign(api, campaign["id"], note="Three-address pilot.")
        fixtures.approve_campaign(
            api, campaign["id"], world["partner_id"],
            approved_quantity=1, decision_note="Fund one piece only.",
        )
        draft_campaign = fixtures.create_campaign(
            api, world["partner_id"], world["product_id"],
            name="Winter Curb Stop Drop", drop_date="2026-10-01", requested_quantity=3,
        )
        assert draft_campaign["status"] == "DRAFT"

        fixtures.set_clock(api, CLOCK_DROP_DAY)
        summary = validate_success(api.mail_drop(campaign["id"], MARKETING_OPS), 200)
        assert_drop_summary_shape(summary)
        assert_drop_counts_agree(summary)
        assert_fields(summary, {"mailed_count": 1, "suppressed_count": 2})
        assert summary["mailed_premises_ids"] == [mailed_premises["id"]], (
            "created_at ascending order fills the single approved piece"
        )
        assert summary["suppressed_by_reason"] == {QUANTITY_CAP_REASON: 2}

        mailed_after = validate_success(api.get_premises(mailed_premises["id"], MARKETING_OPS))
        assert_fields(mailed_after, {
            "last_mail_decision": "MAILED",
            "last_mailed_campaign_id": campaign["id"],
            "version": 2,
        })
        assert mailed_after["last_mail_suppression_reason"] is None
        capped_after = validate_success(api.get_premises(capped_premises["id"], MARKETING_OPS))
        assert_fields(capped_after, {
            "last_mail_decision": "SUPPRESSED",
            "last_mail_suppression_reason": QUANTITY_CAP_REASON,
            "version": 2,
        })
        direct_after = validate_success(api.get_premises(direct_premises["id"], MARKETING_OPS))
        assert direct_after["version"] == 2, "the drop bumps every evaluated address"

        # The campaign exists and is MAILED, but it suppressed this address.
        suppressed_attempt = api.create_enrollment(
            factories.enrollment_payload(
                capped_premises["id"], world["product_id"], capped_after["version"],
                prepaid_amount_cents=None, source_campaign_id=campaign["id"],
            ),
            CUSTOMER_SERVICE_REP,
        )
        assert_refused(suppressed_attempt, ERR_MAILING_SUPPRESSED)

        # A body foreign key must resolve before any state or suppression check.
        absent_attempt = api.create_enrollment(
            factories.enrollment_payload(
                direct_premises["id"], world["product_id"], direct_after["version"],
                prepaid_amount_cents=None, source_campaign_id=ABSENT_UUID,
            ),
            CUSTOMER_SERVICE_REP,
        )
        assert_refused(absent_attempt, ERR_CAMPAIGN_NOT_FOUND)

        # A campaign that has never been dropped cannot source a sale.
        draft_attempt = api.create_enrollment(
            factories.enrollment_payload(
                direct_premises["id"], world["product_id"], direct_after["version"],
                prepaid_amount_cents=None, source_campaign_id=draft_campaign["id"],
            ),
            CUSTOMER_SERVICE_REP,
        )
        assert_refused(draft_attempt, ERR_CAMPAIGN_NOT_MAILED)

        attributed = validate_success(
            api.create_enrollment(
                factories.enrollment_payload(
                    mailed_premises["id"], world["product_id"], mailed_after["version"],
                    prepaid_amount_cents=None, source_campaign_id=campaign["id"],
                ),
                CUSTOMER_SERVICE_REP,
            ),
            201,
        )
        assert_created_resource(attributed)
        assert_fields(attributed, {
            "source_campaign_id": campaign["id"],
            "coverage_status": "PENDING_WAITING_PERIOD",
        })

        direct_sale = validate_success(
            api.create_enrollment(
                factories.enrollment_payload(
                    direct_premises["id"], world["product_id"], direct_after["version"],
                    prepaid_amount_cents=None,
                ),
                CUSTOMER_SERVICE_REP,
            ),
            201,
        )
        assert_created_resource(direct_sale)
        assert direct_sale["source_campaign_id"] is None, (
            "a direct inbound sale omits the link and skips both attribution gates"
        )

        rows, _ = assert_list_envelope(
            api.list_enrollments(
                CUSTOMER_SERVICE_REP, params={"source_campaign_id": campaign["id"]}
            ),
            expected_total=1,
        )
        assert_ids_in_order(rows, [attributed["id"]])

        final_direct = validate_success(api.get_premises(direct_premises["id"], MARKETING_OPS))
        assert final_direct["version"] == 3, (
            "only the accepted enrollment bumped the address; the three refusals wrote nothing"
        )


class TestDispatchSupersedeLink:
    """POST /claims/{claimId}/dispatches, second dispatch on one claim (PRD §3.6)."""

    def test_second_dispatch_needs_the_supersede_link_to_an_open_sibling(self, api):
        """From DISPATCHED the endpoint is closed unless the link names an open dispatch of that claim.

        PRD: "A dispatch is admissible from `APPROVED`, and also from `DISPATCHED` when `supersedes_dispatch_id` names a supersedable dispatch of that same claim; anything else — including a bare dispatch request against a claim already `DISPATCHED` — is refused with `ERR_INVALID_CLAIM_STATE`."

        Design: Corner/endpoints/second_dispatch_needs_the_supersede_link_to_an_open_sibling
        """
        world = fixtures.active_partner_with_product(api)
        premises = fixtures.create_premises(api, world["partner_id"])
        fixtures.set_clock(api, CLOCK_ENROLLMENT_DAY)
        enrollment = fixtures.create_enrollment(
            api, premises["id"], world["product_id"], premises["version"],
            prepaid_amount_cents=None,
        )
        fixtures.set_clock(api, CLOCK_COVERAGE_ACTIVE)
        fixtures.run_nightly(api)

        contractor_a = fixtures.create_contractor(
            api, license_number="OR-PL-4411", license_expires_on="2027-06-30",
        )
        contractor_b = fixtures.create_contractor(
            api, name="Ridgeline Plumbing", license_number="OR-PL-4412",
            license_expires_on="2027-06-30", hourly_rate_cents=6000, sla_compliance_pct=70,
        )

        first_claim = fixtures.file_claim(
            api, enrollment["id"], urgency="URGENT",
            defect_location="CURB_STOP_TO_METER",
            incident_description="Curb stop leaking.",
        )
        second_claim = fixtures.file_claim(
            api, enrollment["id"], urgency="ROUTINE",
            defect_location="METER_TO_HOME",
            incident_description="Meter-to-home run weeping.",
        )
        first_approved = fixtures.approve_claim(
            api, first_claim["id"], coverage_note="Covered curb-stop failure."
        )
        second_approved = fixtures.approve_claim(
            api, second_claim["id"], coverage_note="Covered meter-to-home failure."
        )

        first_dispatch = fixtures.dispatch_claim_to(
            api, first_claim["id"], first_approved["version"], contractor_a["id"],
            window_start="2026-09-10T09:00:00.000Z",
        )
        foreign_dispatch = fixtures.dispatch_claim_to(
            api, second_claim["id"], second_approved["version"], contractor_b["id"],
            window_start="2026-09-11T09:00:00.000Z",
        )
        assert first_dispatch["status"] == "ASSIGNED"
        claim_dispatched = validate_success(
            api.get_claim(first_claim["id"], OPERATIONS_ADMIN), 200
        )
        assert_fields(claim_dispatched, {"status": "DISPATCHED", "version": 3})

        def open_dispatch_count_of_first_claim():
            rows, meta = assert_list_envelope(
                api.list_dispatches(OPERATIONS_ADMIN, params={"claim_id": first_claim["id"]})
            )
            return rows, meta["total_count"]

        # A bare re-dispatch is closed off: the claim is already DISPATCHED.
        bare = api.create_dispatch(
            first_claim["id"],
            factories.manual_dispatch_payload(
                claim_dispatched["version"], "2026-09-10T14:00:00.000Z", contractor_a["id"]
            ),
            OPERATIONS_ADMIN,
        )
        assert_refused(bare, ERR_INVALID_CLAIM_STATE)

        # A link to an open dispatch of a *different* claim is refused too. The
        # claim-state gate and the supersede-target gate both sit in the same
        # refusal tier, so either identifier conforms; what is fixed is that the
        # request is refused and nothing is created.
        foreign = api.create_dispatch(
            first_claim["id"],
            factories.manual_dispatch_payload(
                claim_dispatched["version"], "2026-09-10T14:00:00.000Z", contractor_a["id"],
                supersedes_dispatch_id=foreign_dispatch["id"],
            ),
            OPERATIONS_ADMIN,
        )
        assert foreign.status_code == 409, (
            f"a cross-claim supersede link is a state refusal, got {foreign.status_code}"
        )
        validate_error_is_one_of(
            foreign, [ERR_INVALID_DISPATCH_STATE, ERR_INVALID_CLAIM_STATE]
        )

        after_refusals = validate_success(
            api.get_claim(first_claim["id"], OPERATIONS_ADMIN), 200
        )
        assert_fields(after_refusals, {"status": "DISPATCHED", "version": 3})
        _, total_after_refusals = open_dispatch_count_of_first_claim()
        assert total_after_refusals == 1, "neither refusal created a dispatch"

        # The same body with a link to this claim's own open dispatch is admitted.
        superseding = validate_success(
            api.create_dispatch(
                first_claim["id"],
                factories.manual_dispatch_payload(
                    after_refusals["version"], "2026-09-10T14:00:00.000Z", contractor_a["id"],
                    supersedes_dispatch_id=first_dispatch["id"],
                ),
                OPERATIONS_ADMIN,
            ),
            201,
        )
        assert_created_resource(superseding)
        assert_fields(superseding, {
            "status": "ASSIGNED",
            "supersedes_dispatch_id": first_dispatch["id"],
        })
        expected_deadline = "2026-09-11T08:00:00.000Z"
        assert SLA_HOURS["URGENT"] == 24
        assert_instant(superseding["sla_deadline_at"], expected_deadline, "sla_deadline_at")

        superseded = fixtures.refresh_dispatch(api, first_dispatch["id"])
        assert_fields(superseded, {
            "status": "SUPERSEDED",
            "cancellation_reason": "SUPERSEDED_BY_REDISPATCH",
            "version": 2,
        })
        claim_after_supersede = validate_success(
            api.get_claim(first_claim["id"], OPERATIONS_ADMIN), 200
        )
        assert_fields(claim_after_supersede, {"status": "DISPATCHED", "version": 4})

        # Replaying the same link now points at a terminal dispatch.
        replay = api.create_dispatch(
            first_claim["id"],
            factories.manual_dispatch_payload(
                claim_after_supersede["version"], "2026-09-10T19:00:00.000Z",
                contractor_a["id"], supersedes_dispatch_id=first_dispatch["id"],
            ),
            OPERATIONS_ADMIN,
        )
        assert replay.status_code == 409, (
            f"a superseded target can no longer unlock the endpoint, got {replay.status_code}"
        )
        validate_error_is_one_of(
            replay, [ERR_INVALID_DISPATCH_STATE, ERR_INVALID_CLAIM_STATE]
        )

        final_rows, final_total = open_dispatch_count_of_first_claim()
        assert final_total == 2, "the replay created nothing beyond the one supersede"
        assert sorted(row["status"] for row in final_rows) == ["ASSIGNED", "SUPERSEDED"]
        assert_ids_in_order(final_rows, [first_dispatch["id"], superseding["id"]])
        assert fixtures.refresh_contractor(api, contractor_a["id"])["open_dispatch_count"] == 1, (
            "the supersede released the outgoing slot as it took the incoming one"
        )


class TestContractorRegistry:
    """POST /contractors, GET /contractors and GET /contractors/{contractorId} (PRD §3.6)."""

    def test_contractor_registry_supports_create_read_and_a_membership_filtered_list(self, api):
        """The line_type filter is a membership test, so a dual-certified crew matches both.

        PRD: "Contractors may be filtered by `state_code`, by `status`, and by `line_type` — and that last filter matches a contractor when the supplied value is a member of its `line_types_certified` array, which makes the contractor list the observable form of the dispatch candidate pool."

        Design: Corner/endpoints/contractor_registry_supports_create_read_and_a_membership_filtered_list
        """
        fixtures.set_clock(api, CLOCK_START)

        dual = validate_success(
            api.create_contractor(
                factories.contractor_payload(
                    name="Alder Plumbing",
                    license_number="OR-PL-4411",
                    license_expires_on="2027-06-30",
                    line_types_certified=["WATER_SERVICE_LINE", "SEWER_LATERAL"],
                ),
                OPERATIONS_ADMIN,
            ),
            201,
        )
        assert_created_resource(dual)
        assert_fields(dual, {
            "status": "ACTIVE",
            "sla_breach_count": 0,
            "open_dispatch_count": 0,
        })

        sewer_only = validate_success(
            api.create_contractor(
                factories.contractor_payload(
                    name="Ridgeline Sewer",
                    license_number="OR-PL-4412",
                    license_expires_on="2027-06-30",
                    line_types_certified=["SEWER_LATERAL"],
                    hourly_rate_cents=6000,
                    sla_compliance_pct=70,
                    max_open_dispatches=3,
                    permit_pull_authorized=False,
                ),
                OPERATIONS_ADMIN,
            ),
            201,
        )
        washington = validate_success(
            api.create_contractor(
                factories.contractor_payload(
                    name="Cascade Water Works",
                    state_code="WA",
                    license_number="WA-PL-9001",
                    license_expires_on="2027-12-31",
                    line_types_certified=["WATER_SERVICE_LINE"],
                    hourly_rate_cents=9000,
                    sla_compliance_pct=88,
                    max_open_dispatches=4,
                ),
                PLATFORM_ADMIN,
            ),
            201,
        )

        read_back = assert_object_envelope(api.get_contractor(dual["id"], OPERATIONS_ADMIN))
        assert_fields(read_back, {
            "name": "Alder Plumbing",
            "state_code": "OR",
            "license_number": "OR-PL-4411",
            "license_expires_on": "2027-06-30",
            "line_types_certified": ["WATER_SERVICE_LINE", "SEWER_LATERAL"],
            "hourly_rate_cents": 18000,
            "max_open_dispatches": 5,
            "permit_pull_authorized": True,
            "version": 1,
        })
        assert_date_only(read_back["license_expires_on"], "license_expires_on")

        water_rows, _ = assert_list_envelope(
            api.list_contractors(
                OPERATIONS_ADMIN, params={"line_type": "WATER_SERVICE_LINE"}
            ),
            expected_total=2,
        )
        assert_ids_in_order(water_rows, [dual["id"], washington["id"]])

        sewer_rows, _ = assert_list_envelope(
            api.list_contractors(OPERATIONS_ADMIN, params={"line_type": "SEWER_LATERAL"}),
            expected_total=2,
        )
        assert_ids_in_order(sewer_rows, [dual["id"], sewer_only["id"]])

        intersected_rows, _ = assert_list_envelope(
            api.list_contractors(
                OPERATIONS_ADMIN,
                params={
                    "state_code": "OR",
                    "line_type": "WATER_SERVICE_LINE",
                    "status": "ACTIVE",
                },
            ),
            expected_total=1,
        )
        assert_ids_in_order(intersected_rows, [dual["id"]])

        page_one, page_one_meta = assert_list_envelope(
            api.list_contractors(OPERATIONS_ADMIN, params={"limit": 2, "offset": 0}),
            expected_total=3,
        )
        assert_ids_in_order(page_one, [dual["id"], sewer_only["id"]])
        assert_created_at_ascending(page_one)
        assert_fields(page_one_meta, {"limit": 2, "offset": 0, "has_more": True})

        page_two, page_two_meta = assert_list_envelope(
            api.list_contractors(OPERATIONS_ADMIN, params={"limit": 2, "offset": 2}),
            expected_total=3,
        )
        assert_ids_in_order(page_two, [washington["id"]])
        assert_fields(page_two_meta, {"limit": 2, "offset": 2, "has_more": False})

        missing = api.get_contractor(ABSENT_UUID, OPERATIONS_ADMIN)
        assert_refused(missing, ERR_CONTRACTOR_NOT_FOUND)
