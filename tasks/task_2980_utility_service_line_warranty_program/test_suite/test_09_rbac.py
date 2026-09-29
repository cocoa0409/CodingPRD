"""Role permission, resource ownership and segregation of duties (PRD §2.1, §2.8, §4).

Three refusal tiers are separated here. A caller whose role is absent from the
endpoint's admitted list is refused at PRD §2.8 tier 2 with ``ERR_UNAUTHORIZED``.
An entity-backed caller — a ``PartnerBrandReviewer`` carrying a partner id, a
``Policyholder`` carrying a premises id, a ``NetworkContractor`` carrying a
contractor id — acting outside its own scope is refused at tier 7 with
``ERR_NOT_RESOURCE_OWNER``. An operator whose identity collides with the one that
took the earlier half of a two-person decision is refused at tier 8 with
``ERR_SEGREGATION_OF_DUTIES``. Every deeper refusal therefore also proves that
the shallower tiers were satisfied, and each test pairs its refusals with the
call that the permitted role makes successfully on the same resource.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_INVALID_CLAIM_STATE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_created_resource,
    assert_drop_summary_shape,
    assert_fields,
    assert_instant,
    assert_list_envelope,
    assert_nulls,
    assert_refused,
    assert_uuid,
)
from test_helpers.constants import (
    CANCELLATION_FEE_CENTS,
    CLOCK_COVERAGE_ACTIVE,
    CLOCK_ENROLLMENT_DAY,
    CLOCK_START,
    ENROLLMENT_TERM_END,
    ENROLLMENT_TERM_START,
    ROLE_APPEALS_OFFICER,
    ROLE_MARKETING_OPS,
)
from test_helpers.test_users import (
    APPEALS_OFFICER,
    APPEALS_OFFICER_USER_ID,
    BILLING_OPS,
    CLAIMS_ADJUSTER,
    CLAIMS_ADJUSTER_USER_ID,
    CUSTOMER_SERVICE_REP,
    MARKETING_OPS,
    MARKETING_OPS_USER_ID,
    OPERATIONS_ADMIN,
    PLATFORM_ADMIN,
    REGULATORY_AFFAIRS,
    make_headers,
    make_network_contractor_headers,
    make_partner_brand_reviewer_headers,
    make_policyholder_headers,
)


class TestPlatformAdminExclusiveWrites:
    """The registry and operational writes reserved to the platform administrator."""

    def test_platform_admin_exclusive_writes_reject_every_other_role(self, api):
        """Partner, product, status-change, clock and nightly writes admit PlatformAdmin only.

        PRD: "The authorisation column lists exhaustively the roles permitted to call each endpoint; a caller holding any other role receives `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/rbac_platform_admin_exclusive_writes_are_closed_to_other_roles
        """
        fixtures.set_clock(api, CLOCK_START)

        # Registering a partner is a PlatformAdmin write; marketing cannot do it.
        assert_refused(
            api.create_partner(factories.partner_payload(), MARKETING_OPS),
            ERR_UNAUTHORIZED,
        )
        partner = validate_success(
            api.create_partner(factories.partner_payload(), PLATFORM_ADMIN), 201
        )
        assert_created_resource(partner)

        # Filing a product is likewise closed, even to the operations administrator.
        assert_refused(
            api.create_product(factories.product_payload(partner["id"]), OPERATIONS_ADMIN),
            ERR_UNAUTHORIZED,
        )
        product = validate_success(
            api.create_product(factories.product_payload(partner["id"]), PLATFORM_ADMIN), 201
        )
        assert product["status"] == "AVAILABLE"

        # Moving the partner's lifecycle status is closed to the service desk.
        partner_version = validate_success(api.get_partner(partner["id"], PLATFORM_ADMIN))["version"]
        assert_refused(
            api.change_partner_status(
                partner["id"],
                factories.partner_status_change_payload("ACTIVE", partner_version),
                CUSTOMER_SERVICE_REP,
            ),
            ERR_UNAUTHORIZED,
        )
        activated = validate_success(
            api.change_partner_status(
                partner["id"],
                factories.partner_status_change_payload("ACTIVE", partner_version),
                PLATFORM_ADMIN,
            )
        )
        assert activated["status"] == "ACTIVE"

        # The logical clock and the nightly run are operational writes.
        assert_refused(
            api.set_clock("2026-08-02T00:00:00.000Z", CUSTOMER_SERVICE_REP), ERR_UNAUTHORIZED
        )
        assert_refused(api.run_nightly(BILLING_OPS), ERR_UNAUTHORIZED)

        # PlatformAdmin also shares the writes that other roles may make.
        premises = validate_success(
            api.create_premises(factories.premises_payload(partner["id"]), PLATFORM_ADMIN), 201
        )
        assert_uuid(premises["id"], "premises id")
        contractor = validate_success(
            api.create_contractor(factories.contractor_payload(), PLATFORM_ADMIN), 201
        )
        assert contractor["status"] == "ACTIVE"

        # The refused clock write moved nothing: the run stamps the epoch clock.
        report = validate_success(api.run_nightly(PLATFORM_ADMIN))
        assert_instant(report["ran_at"], CLOCK_START, "ran_at")
        assert report["activated_enrollment_ids"] == []


class TestCampaignRoleSplit:
    """Building a campaign, deciding it, and the two guards on the decision."""

    def test_marketing_ops_builds_the_campaign_and_the_reviewer_decides_it(self, api):
        """Draft, submission and drop are MarketingOps writes; the decision is the reviewer's.

        PRD: "A request that carries a valid `X-User-ID` but whose `X-User-Role` is not among the roles the target operation admits is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/rbac_marketing_ops_owns_the_campaign_build_but_never_the_decision
        """
        world = fixtures.partner_product_premises(api)
        reviewer = make_partner_brand_reviewer_headers(world["partner_id"])
        draft = factories.campaign_payload(
            world["partner_id"],
            world["product_id"],
            drop_date="2026-08-01",
            requested_quantity=1000,
        )

        # The reviewer may not author the campaign.
        assert_refused(api.create_campaign(draft, reviewer), ERR_UNAUTHORIZED)
        campaign = validate_success(api.create_campaign(draft, MARKETING_OPS), 201)
        assert campaign["status"] == "DRAFT"

        # Nor may it submit the campaign for its own review.
        assert_refused(
            api.submit_campaign(
                campaign["id"], factories.campaign_submission_payload(), reviewer
            ),
            ERR_UNAUTHORIZED,
        )
        submitted = validate_success(
            api.submit_campaign(
                campaign["id"], factories.campaign_submission_payload(), MARKETING_OPS
            )
        )
        assert_fields(
            submitted,
            {"status": "PARTNER_REVIEW", "submitted_by_user_id": MARKETING_OPS_USER_ID},
        )

        # Marketing may not decide what it submitted.
        approval = factories.campaign_approval_payload(approved_quantity=None)
        assert_refused(
            api.decide_campaign(campaign["id"], approval, MARKETING_OPS), ERR_UNAUTHORIZED
        )
        untouched = validate_success(api.get_campaign(campaign["id"], MARKETING_OPS))
        assert untouched["status"] == "PARTNER_REVIEW"

        decided = validate_success(api.decide_campaign(campaign["id"], approval, reviewer))
        assert_fields(
            decided,
            {
                "status": "APPROVED",
                "approved_quantity": 1000,
                "decision_by_user_id": world["partner_id"],
            },
        )
        assert_instant(decided["decided_at"], CLOCK_START, "decided_at")

        # The drop returns to marketing.
        assert_refused(api.mail_drop(campaign["id"], reviewer), ERR_UNAUTHORIZED)
        summary = validate_success(api.mail_drop(campaign["id"], MARKETING_OPS))
        assert_drop_summary_shape(summary)
        assert_fields(summary, {"status": "MAILED", "mailed_count": 1})

    def test_brand_reviewer_may_only_decide_its_own_partners_campaign(self, api):
        """A reviewer bound to another partner is refused as a non-owner.

        PRD: "When `X-User-Role` is `PartnerBrandReviewer`, `X-User-ID` is the `id` of the acting `UtilityPartner`; ownership checks on any resource that references a `UtilityPartner` compare the resource's foreign-key field to `X-User-ID`, so a brand reviewer may only decide a campaign whose `partner_id` equals its own `X-User-ID`."

        Design: Corner/rbac/rbac_partner_brand_reviewer_is_bound_to_its_own_partners_campaign
        """
        world = fixtures.active_partner_with_product(api)
        other = fixtures.active_partner_with_product(
            api,
            partner_overrides={"name": "Willamette Power", "utility_type": "ELECTRIC"},
            product_overrides={
                "name": "Electric Mast Cover",
                "line_type": "EXTERIOR_ELECTRIC",
                "ownership_boundary": "METER",
                "required_owned_segment": "EXTERIOR_ELECTRIC_MAST",
                "monthly_price_cents": 1899,
                "per_occurrence_cap_cents": 300000,
                "annual_cap_cents": 500000,
                "permit_covered": False,
                "restoration_covered_scope": "NONE",
                "cap_reset_basis": "CALENDAR_YEAR",
            },
        )

        campaign = fixtures.create_campaign(
            api,
            world["partner_id"],
            world["product_id"],
            drop_date="2026-08-01",
            requested_quantity=1000,
        )
        submitted = fixtures.submit_campaign(api, campaign["id"])
        assert submitted["version"] == 2

        # The neighbouring partner's reviewer is a stranger to this campaign.
        assert_refused(
            api.decide_campaign(
                campaign["id"],
                factories.campaign_rejection_payload(),
                make_partner_brand_reviewer_headers(other["partner_id"]),
            ),
            ERR_NOT_RESOURCE_OWNER,
        )
        unchanged = validate_success(api.get_campaign(campaign["id"], MARKETING_OPS))
        assert_fields(unchanged, {"status": "PARTNER_REVIEW", "version": 2})
        assert_nulls(unchanged, ["approved_quantity"])

        # The campaign's own reviewer decides it, trimming the quantity.
        decided = validate_success(
            api.decide_campaign(
                campaign["id"],
                factories.campaign_approval_payload(approved_quantity=600),
                make_partner_brand_reviewer_headers(world["partner_id"]),
            )
        )
        assert_fields(
            decided,
            {
                "status": "APPROVED",
                "approved_quantity": 600,
                "decision_by_user_id": world["partner_id"],
                "version": 3,
            },
        )

    def test_campaign_decision_bars_the_operator_that_submitted_it(self, api):
        """A reviewer whose identity submitted the campaign is refused for duty segregation.

        PRD: "Note that submission and decision are guarded against the same operator playing both parts: a reviewer whose `X-User-ID` matches the campaign's `submitted_by_user_id` is refused, as is a reviewer whose `X-User-ID` is not the campaign's `partner_id` at all."

        Design: Corner/rbac/rbac_campaign_decision_segregation_of_duties_bars_its_own_submitter
        """
        world = fixtures.active_partner_with_product(api)
        partner_id = world["partner_id"]
        reviewer = make_partner_brand_reviewer_headers(partner_id)
        # A MarketingOps identifier is opaque, so it may legitimately carry the
        # same value the reviewer will later present.
        marketing_as_partner = make_headers(ROLE_MARKETING_OPS, partner_id)

        collided = fixtures.create_campaign(
            api,
            partner_id,
            world["product_id"],
            headers=marketing_as_partner,
            name="Self submitted drop",
            drop_date="2026-08-01",
            requested_quantity=500,
        )
        collided_submitted = fixtures.submit_campaign(
            api, collided["id"], headers=marketing_as_partner
        )
        assert_fields(
            collided_submitted,
            {"status": "PARTNER_REVIEW", "submitted_by_user_id": partner_id},
        )

        # A second campaign submitted by a different operator, spaced far enough
        # from the first to satisfy the partner's own drop-window rule.
        clean = fixtures.create_campaign(
            api,
            partner_id,
            world["product_id"],
            name="Marketing submitted drop",
            piece_type="BILL_INSERT",
            drop_date="2026-08-22",
            requested_quantity=500,
        )
        clean_submitted = fixtures.submit_campaign(api, clean["id"])
        assert clean_submitted["submitted_by_user_id"] == MARKETING_OPS_USER_ID

        # Same identity on both halves of the decision: refused.
        assert_refused(
            api.decide_campaign(
                collided["id"],
                factories.campaign_approval_payload(approved_quantity=500),
                reviewer,
            ),
            ERR_SEGREGATION_OF_DUTIES,
        )
        still_open = validate_success(api.get_campaign(collided["id"], MARKETING_OPS))
        assert still_open["status"] == "PARTNER_REVIEW"
        assert_nulls(still_open, ["decision_by_user_id"])

        # The very same reviewer may decide the campaign it did not submit.
        decided = validate_success(
            api.decide_campaign(
                clean["id"],
                factories.campaign_approval_payload(approved_quantity=500),
                reviewer,
            )
        )
        assert_fields(
            decided, {"status": "APPROVED", "decision_by_user_id": partner_id}
        )


class TestAppealSegregationAndOwnership:
    """Who may open an appeal, and who may not be the one to decide it."""

    def test_appeal_decision_bars_the_adjuster_who_denied_the_claim(self, api):
        """The denying adjuster's identity cannot decide the appeal; an independent officer can.

        PRD: "A caller whose `X-User-ID` equals the claim's `triage_decided_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`, and this is checked ahead of any state or business condition."

        Design: Corner/rbac/rbac_appeal_decision_segregation_of_duties_bars_the_denying_adjuster
        """
        world = fixtures.active_coverage(api)
        claim = fixtures.file_claim(api, world["enrollment_id"])
        denied = fixtures.deny_claim(api, claim["id"], "NOT_COVERED_SEGMENT")
        assert denied["triage_decided_by_user_id"] == CLAIMS_ADJUSTER_USER_ID
        assert_instant(denied["denied_at"], CLOCK_COVERAGE_ACTIVE, "denied_at")

        appealed = fixtures.open_appeal(api, claim["id"], world["premises_id"])
        assert_fields(appealed, {"status": "APPEAL_OPEN", "appeal_count": 1})

        # The appeals officer role is admitted here, so the refusal is the duty
        # segregation rule and not a role refusal.
        assert_refused(
            api.decide_appeal(
                claim["id"],
                factories.appeal_decision_payload("UPHOLD"),
                make_headers(ROLE_APPEALS_OFFICER, CLAIMS_ADJUSTER_USER_ID),
            ),
            ERR_SEGREGATION_OF_DUTIES,
        )

        # Nor can the adjuster route around the rule by re-triaging the claim.
        assert_refused(
            api.triage_claim(claim["id"], factories.triage_approval_payload(), CLAIMS_ADJUSTER),
            ERR_INVALID_CLAIM_STATE,
        )

        overturned = fixtures.decide_appeal(api, claim["id"], "OVERTURN")
        assert_fields(
            overturned,
            {"status": "APPROVED", "appeal_decided_by_user_id": APPEALS_OFFICER_USER_ID},
        )
        assert_nulls(overturned, ["denial_reason", "denied_at"])

        # The overturn released the retention hold and the mailing suppression.
        enrollment = fixtures.refresh_enrollment(api, world["enrollment_id"])
        assert enrollment["retention_hold"] is False
        premises = validate_success(api.get_premises(world["premises_id"], MARKETING_OPS))
        assert premises["suppression_reason"] == "NONE"

    def test_policyholder_may_appeal_only_a_claim_on_its_own_premises(self, api):
        """The appeal is ownership-guarded; filing a claim and reading one by id are not.

        PRD: "The `Policyholder` — and only the policyholder whose own address the claim was filed against, anyone else being refused with `ERR_NOT_RESOURCE_OWNER` — may appeal a `DENIED` claim by supplying an `appeal_reason`."

        Design: Corner/rbac/rbac_policyholder_may_appeal_only_claims_of_its_own_premises
        """
        world = fixtures.partner_product_premises(api)
        neighbour = fixtures.create_unique_premises(api, world["partner_id"])

        fixtures.set_clock(api, CLOCK_ENROLLMENT_DAY)
        own_enrollment = fixtures.create_enrollment(
            api, world["premises_id"], world["product_id"], world["premises_version"]
        )
        fixtures.create_enrollment(
            api, neighbour["id"], world["product_id"], neighbour["version"]
        )
        fixtures.set_clock(api, CLOCK_COVERAGE_ACTIVE)
        fixtures.run_nightly(api)

        own_headers = make_policyholder_headers(world["premises_id"])
        neighbour_headers = make_policyholder_headers(neighbour["id"])

        claim = validate_success(
            api.create_claim(factories.claim_payload(own_enrollment["id"]), own_headers), 201
        )
        denied = fixtures.deny_claim(api, claim["id"], "NOT_COVERED_SEGMENT")
        assert denied["status"] == "DENIED"

        # The neighbour is a stranger to this address's claim.
        assert_refused(
            api.create_appeal(claim["id"], factories.appeal_payload(), neighbour_headers),
            ERR_NOT_RESOURCE_OWNER,
        )

        # The claims collection is not in the policyholder's read list at all,
        # while the single-claim read is.
        assert_refused(api.list_claims(own_headers), ERR_UNAUTHORIZED)
        read = validate_success(api.get_claim(claim["id"], own_headers))
        assert_fields(read, {"id": claim["id"], "status": "DENIED"})

        # Filing a claim is not one of the ownership-guarded operations, so the
        # neighbour's policyholder may still open one against this policy.
        cross_filed = validate_success(
            api.create_claim(
                factories.claim_payload(
                    own_enrollment["id"],
                    defect_location="METER_TO_HOME",
                    incident_description="Neighbour reports the yard line is flooding the strip.",
                ),
                neighbour_headers,
            ),
            201,
        )
        assert cross_filed["enrollment_id"] == own_enrollment["id"]

        # The address's own policyholder appeals successfully.
        appealed = fixtures.open_appeal(api, claim["id"], world["premises_id"])
        assert_fields(
            appealed,
            {"status": "APPEAL_OPEN", "appeal_count": 1, "appeal_source": "POLICYHOLDER"},
        )


class TestDispatchEventOwnership:
    """The crew that owns the dispatch is the only one that may work it."""

    def test_network_contractor_posts_events_only_on_its_own_dispatch(self, api):
        """A crew is refused on the other crew's dispatch, and dispatching is not its write.

        PRD: "A contractor works the job by posting events against the dispatch, and only the `NetworkContractor` whose own identity matches the dispatch's `contractor_id` may do so; anyone else is refused with `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/rbac/rbac_network_contractor_posts_events_only_on_its_own_dispatch
        """
        world = fixtures.active_coverage(api)
        alpha = fixtures.create_contractor(api)
        beta = fixtures.create_contractor(
            api,
            name="Beta Excavation",
            license_number="OR-PL-5522",
            license_expires_on="2027-09-30",
            hourly_rate_cents=15000,
            sla_compliance_pct=88,
        )

        claim_one = fixtures.file_claim(api, world["enrollment_id"])
        approved_one = fixtures.approve_claim(api, claim_one["id"])
        dispatch_alpha = fixtures.dispatch_claim_to(
            api,
            claim_one["id"],
            approved_one["version"],
            alpha["id"],
            window_start="2026-09-10T09:00:00.000Z",
        )

        claim_two = fixtures.file_claim(
            api,
            world["enrollment_id"],
            defect_location="METER_TO_HOME",
            incident_description="Separate failure after the meter.",
        )
        approved_two = fixtures.approve_claim(api, claim_two["id"])
        dispatch_beta = fixtures.dispatch_claim_to(
            api,
            claim_two["id"],
            approved_two["version"],
            beta["id"],
            window_start="2026-09-11T09:00:00.000Z",
        )

        alpha_crew = make_network_contractor_headers(alpha["id"])
        beta_crew = make_network_contractor_headers(beta["id"])

        # The other crew's identity is refused as a non-owner, not as a role.
        assert_refused(
            api.create_dispatch_event(
                dispatch_alpha["id"], factories.accept_event_payload(), beta_crew
            ),
            ERR_NOT_RESOURCE_OWNER,
        )

        # Field events are the crew's exclusive write, closed even to operations.
        assert_refused(
            api.create_dispatch_event(
                dispatch_alpha["id"], factories.accept_event_payload(), OPERATIONS_ADMIN
            ),
            ERR_UNAUTHORIZED,
        )

        # And creating the dispatch is operations' exclusive write, closed to the crew.
        assert_refused(
            api.create_dispatch(
                claim_one["id"],
                factories.manual_dispatch_payload(
                    fixtures.refresh_claim(api, claim_one["id"])["version"],
                    "2026-09-12T09:00:00.000Z",
                    alpha["id"],
                ),
                alpha_crew,
            ),
            ERR_UNAUTHORIZED,
        )

        # Each crew accepts its own job; the clock has not moved since assignment.
        accepted_alpha = fixtures.accept_dispatch(api, dispatch_alpha["id"], alpha["id"])
        assert_fields(accepted_alpha, {"status": "ACCEPTED", "response_minutes": 0})
        accepted_beta = fixtures.accept_dispatch(api, dispatch_beta["id"], beta["id"])
        assert accepted_beta["status"] == "ACCEPTED"

        # The shared dispatch collection carries no ownership filter.
        rows, _meta = assert_list_envelope(api.list_dispatches(beta_crew), expected_total=2)
        assert len(rows) == 2

        # The two refused calls changed nothing on the alpha dispatch.
        unchanged = validate_success(api.get_dispatch(dispatch_alpha["id"], OPERATIONS_ADMIN))
        assert_fields(unchanged, {"contractor_id": alpha["id"], "version": 2})


class TestBillingAndServiceDeskExclusives:
    """Money writes and policy-desk writes never overlap."""

    def test_billing_ops_and_customer_service_rep_exclusives_never_overlap(self, api):
        """Enrollment and cancellation are the desk's; payments and renewal notices are billing's.

        PRD: "The authorisation column lists exhaustively the roles permitted to call each endpoint; a caller holding any other role receives `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/rbac_billing_ops_and_customer_service_rep_exclusives_never_overlap
        """
        world = fixtures.active_coverage(api)
        enrollment_id = world["enrollment_id"]
        enrollment = validate_success(api.get_enrollment(enrollment_id, BILLING_OPS))
        assert_fields(
            enrollment,
            {
                "coverage_status": "ACTIVE",
                "version": 2,
                "term_start": ENROLLMENT_TERM_START,
                "term_end": ENROLLMENT_TERM_END,
            },
        )

        # Billing may not write the policy itself.
        assert_refused(
            api.create_enrollment(
                factories.enrollment_payload(
                    world["premises_id"], world["product_id"], world["premises_version"]
                ),
                BILLING_OPS,
            ),
            ERR_UNAUTHORIZED,
        )
        assert_refused(
            api.cancel_enrollment(
                enrollment_id, factories.cancellation_payload("2026-09-15"), BILLING_OPS
            ),
            ERR_UNAUTHORIZED,
        )

        # And the service desk may not touch money.
        assert_refused(
            api.create_billing_event(
                enrollment_id,
                factories.billing_event_payload(
                    "PREMIUM_PAYMENT", "2026-09-10", amount_cents=2499
                ),
                CUSTOMER_SERVICE_REP,
            ),
            ERR_UNAUTHORIZED,
        )
        assert_refused(
            api.create_renewal_notice(
                enrollment_id,
                factories.renewal_notice_payload(2599, "2027-08-05", 2),
                CUSTOMER_SERVICE_REP,
            ),
            ERR_UNAUTHORIZED,
        )

        # Billing is also outside the dispatch read list, while the ledger is its own.
        assert_refused(api.list_dispatches(BILLING_OPS), ERR_UNAUTHORIZED)
        assert_list_envelope(
            api.list_ledger_entries(BILLING_OPS, params={"enrollment_id": enrollment_id}),
            expected_total=0,
        )

        # Each role's own write is accepted, in sequence, on the same policy.
        paid = fixtures.billing_event(
            api, enrollment_id, "PREMIUM_PAYMENT", "2026-09-10", amount_cents=2499
        )
        assert_fields(paid, {"version": 3, "premium_collected_cents": 2499})

        notice = fixtures.issue_renewal_notice(api, enrollment_id, 2599, "2027-08-05", 3)
        assert_fields(
            notice,
            {
                "renewal_notice_status": "SENT",
                "renewal_price_cents": 2599,
                "version": 4,
            },
        )
        assert_instant(
            notice["renewal_notice_sent_at"], CLOCK_COVERAGE_ACTIVE, "renewal_notice_sent_at"
        )

        cancelled = fixtures.cancel_enrollment(api, enrollment_id, "2026-09-15")
        assert_fields(
            cancelled,
            {
                "coverage_status": "CANCELLED",
                "billing_status": "REFUND_ISSUED",
                "cancellation_fee_cents": CANCELLATION_FEE_CENTS,
                "refund_cents": 24145,
                "credit_cents": 0,
                "version": 5,
            },
        )


class TestReadScopingCarveOuts:
    """The shared read lists are not uniform: each role has its own carve-outs."""

    def test_read_scoping_carve_outs_for_service_rep_marketing_and_adjuster(self, api):
        """Each role's admitted collections are exactly those the endpoint table names.

        PRD: "The authorisation column lists exhaustively the roles permitted to call each endpoint; a caller holding any other role receives `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/rbac_read_scoping_carve_outs_for_service_rep_marketing_and_adjuster
        """
        world = fixtures.partner_product_premises(api)
        neighbour = fixtures.create_unique_premises(api, world["partner_id"])
        fixtures.create_enrollment(
            api, world["premises_id"], world["product_id"], world["premises_version"]
        )
        complaint = fixtures.create_complaint(api, world["partner_id"])
        assert_instant(
            complaint["response_due_at"], "2026-08-11T00:00:00.000Z", "response_due_at"
        )

        # The complaint reads are the two GETs carved out of the service desk's list.
        assert_refused(api.list_complaints(CUSTOMER_SERVICE_REP), ERR_UNAUTHORIZED)
        assert_refused(
            api.get_complaint(complaint["id"], CUSTOMER_SERVICE_REP), ERR_UNAUTHORIZED
        )
        # Every other collection is open to it, including the empty ones.
        assert_list_envelope(api.list_ledger_entries(CUSTOMER_SERVICE_REP), expected_total=0)
        assert_list_envelope(api.list_contractors(CUSTOMER_SERVICE_REP), expected_total=0)

        # Marketing sees the sales file but nothing operational or financial.
        assert_refused(api.list_claims(MARKETING_OPS), ERR_UNAUTHORIZED)
        assert_refused(api.list_ledger_entries(MARKETING_OPS), ERR_UNAUTHORIZED)
        assert_refused(api.list_dispatches(MARKETING_OPS), ERR_UNAUTHORIZED)
        assert_list_envelope(api.list_enrollments(MARKETING_OPS), expected_total=1)

        # The adjuster reads both the complaint and the marketing file.
        assert_list_envelope(api.list_premises(CLAIMS_ADJUSTER), expected_total=2)
        adjuster_view = validate_success(api.get_complaint(complaint["id"], CLAIMS_ADJUSTER))
        assert adjuster_view["status"] == "OPEN"

        # The appeals officer's read list stops short of campaigns.
        assert_refused(api.list_campaigns(APPEALS_OFFICER), ERR_UNAUTHORIZED)

        # Ownership never applies to a read, so a policyholder reads a neighbour's
        # address, but the enrollment collection is closed to it entirely.
        policyholder = make_policyholder_headers(world["premises_id"])
        cross_read = validate_success(api.get_premises(neighbour["id"], policyholder))
        assert_fields(
            cross_read,
            {"id": neighbour["id"], "street_address": neighbour["street_address"]},
        )
        assert_refused(api.list_enrollments(policyholder), ERR_UNAUTHORIZED)


class TestClaimPipelineRoleSplit:
    """Triage, appeal decision, dispatch and intake are four different roles' writes."""

    def test_adjuster_appeals_officer_and_operations_admin_writes_are_mutually_closed(self, api):
        """No role in the claim pipeline can reach into another's write, whatever the state.

        PRD: "A role absent from the endpoint's admitted list yields `ERR_UNAUTHORIZED` (403)."

        Design: Corner/rbac/rbac_adjuster_appeals_officer_and_operations_admin_writes_are_mutually_closed
        """
        world = fixtures.partner_product_premises(api)
        contractor = fixtures.create_contractor(api, headers=PLATFORM_ADMIN)
        fixtures.set_clock(api, CLOCK_ENROLLMENT_DAY)
        enrollment = fixtures.create_enrollment(
            api, world["premises_id"], world["product_id"], world["premises_version"]
        )
        fixtures.set_clock(api, CLOCK_COVERAGE_ACTIVE)
        report = fixtures.run_nightly(api, PLATFORM_ADMIN)
        assert_instant(report["ran_at"], CLOCK_COVERAGE_ACTIVE, "ran_at")

        claim = fixtures.file_claim(api, enrollment["id"])
        assert_fields(claim, {"status": "TRIAGE", "version": 1})

        # The adjuster owns triage and nothing else on the claim.
        assert_refused(
            api.decide_appeal(
                claim["id"], factories.appeal_decision_payload("OVERTURN"), CLAIMS_ADJUSTER
            ),
            ERR_UNAUTHORIZED,
        )
        # The role check precedes the claim-state gate, so a TRIAGE claim still
        # answers with the role refusal rather than a state refusal.
        assert_refused(
            api.create_dispatch(
                claim["id"],
                factories.manual_dispatch_payload(
                    claim["version"], "2026-09-10T09:00:00.000Z", contractor["id"]
                ),
                CLAIMS_ADJUSTER,
            ),
            ERR_UNAUTHORIZED,
        )
        assert_refused(
            api.create_claim(
                factories.claim_payload(
                    enrollment["id"],
                    defect_location="METER_TO_HOME",
                    incident_description="The adjuster tries to file a claim.",
                ),
                CLAIMS_ADJUSTER,
            ),
            ERR_UNAUTHORIZED,
        )

        # Neither the appeals officer nor operations may triage.
        assert_refused(
            api.triage_claim(claim["id"], factories.triage_approval_payload(), APPEALS_OFFICER),
            ERR_UNAUTHORIZED,
        )
        assert_refused(
            api.triage_claim(claim["id"], factories.triage_approval_payload(), OPERATIONS_ADMIN),
            ERR_UNAUTHORIZED,
        )

        # Contractor onboarding, the nightly run and the clock are closed too.
        assert_refused(
            api.create_contractor(
                factories.contractor_payload(
                    name="Rogue Valley Boring",
                    license_number="OR-PL-9001",
                    hourly_rate_cents=16000,
                    sla_compliance_pct=90,
                    max_open_dispatches=3,
                ),
                MARKETING_OPS,
            ),
            ERR_UNAUTHORIZED,
        )
        assert_refused(api.run_nightly(BILLING_OPS), ERR_UNAUTHORIZED)
        assert_refused(
            api.set_clock("2026-09-11T08:00:00.000Z", REGULATORY_AFFAIRS), ERR_UNAUTHORIZED
        )

        # Each permitted role's own write lands.
        triaged = fixtures.approve_claim(api, claim["id"])
        assert_fields(triaged, {"status": "APPROVED", "version": 2})

        dispatch = fixtures.dispatch_claim_to(
            api,
            claim["id"],
            triaged["version"],
            contractor["id"],
            window_start="2026-09-10T09:00:00.000Z",
        )
        assert_fields(
            dispatch, {"status": "ASSIGNED", "contractor_id": contractor["id"]}
        )
        # The refused clock write moved nothing, so the assignment is still stamped
        # at the run's own instant and the window closes 240 minutes after it opens.
        assert_instant(dispatch["assigned_at"], CLOCK_COVERAGE_ACTIVE, "assigned_at")
        assert_instant(dispatch["window_end"], "2026-09-10T13:00:00.000Z", "window_end")


class TestComplaintLifecycleExclusive:
    """The complaint trio belongs to regulatory affairs alone, and nothing else does."""

    def test_regulatory_affairs_alone_drives_the_complaint_lifecycle(self, api):
        """Logging, responding and escalating are exclusive; reading them is not.

        PRD: "A request that carries a valid `X-User-ID` but whose `X-User-Role` is not among the roles the target operation admits is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/rbac_regulatory_affairs_alone_drives_the_complaint_lifecycle
        """
        world = fixtures.active_partner_with_product(api)

        # Even the platform administrator cannot log a complaint.
        assert_refused(
            api.create_complaint(factories.complaint_payload(world["partner_id"]), PLATFORM_ADMIN),
            ERR_UNAUTHORIZED,
        )
        # And regulatory affairs holds no write outside the complaint trio.
        assert_refused(
            api.create_premises(
                factories.premises_payload(world["partner_id"]), REGULATORY_AFFAIRS
            ),
            ERR_UNAUTHORIZED,
        )
        assert_refused(api.run_nightly(REGULATORY_AFFAIRS), ERR_UNAUTHORIZED)

        complaint = fixtures.create_complaint(api, world["partner_id"])
        assert_fields(
            complaint, {"status": "OPEN", "version": 1, "escalation_count": 0}
        )
        assert_instant(
            complaint["response_due_at"], "2026-08-11T00:00:00.000Z", "response_due_at"
        )

        # The adjuster may read this complaint but not answer it, and operations
        # may not escalate it; both are refused before any version or state gate.
        assert_refused(
            api.respond_to_complaint(
                complaint["id"],
                factories.complaint_response_payload("UNSUBSTANTIATED", "APOLOGY_ONLY", 1),
                CLAIMS_ADJUSTER,
            ),
            ERR_UNAUTHORIZED,
        )
        assert_refused(
            api.escalate_complaint(
                complaint["id"], factories.escalation_payload(), OPERATIONS_ADMIN
            ),
            ERR_UNAUTHORIZED,
        )

        # Version 1 is still current, because neither refusal bumped anything.
        closed = fixtures.respond_to_complaint(
            api, complaint["id"], "UNSUBSTANTIATED", "APOLOGY_ONLY", 1
        )
        assert_fields(
            closed,
            {
                "status": "CLOSED_UNSUBSTANTIATED",
                "remedy_type": "APOLOGY_ONLY",
                "version": 2,
            },
        )
        assert_nulls(closed, ["remedy_amount_cents"])

        escalated = fixtures.escalate_complaint(api, complaint["id"])
        assert_fields(
            escalated, {"status": "ESCALATED", "escalation_count": 1, "version": 3}
        )
        assert_nulls(escalated, ["responded_at", "disposition"])

        # Operations holds every read, so its write refusal was not a read refusal.
        assert_list_envelope(api.list_complaints(OPERATIONS_ADMIN), expected_total=1)
