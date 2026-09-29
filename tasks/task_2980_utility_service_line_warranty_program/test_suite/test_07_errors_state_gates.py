"""State-gate and refusal-precedence tests.

Every test in this module proves a refusal that the PRD pins by name: a
transition absent from a declared state graph, a cross-entity gate on a
collaborator's status, or a precedence contest between two rules that the
ordered refusal ladder of PRD §2.8 decides.

Two habits recur below. First, a refusal must be reached at the tier under
test, so every shallower tier is deliberately satisfied — an entity-backed
caller acts as its own resource, and a version-guarded write declares the
parent's current ``version`` — which is what makes the observed ``error_id``
diagnostic. Second, a refused request must change nothing, so each test
re-reads the addressed record afterwards and asserts that its ``version`` did
not move: "``version`` is an integer that starts at 1 when the record is
created and increases by exactly 1 on every accepted mutation of that record."
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_BILL_INSERT_NOT_SUPPORTED,
    ERR_DROP_DATE_IN_FUTURE,
    ERR_DUPLICATE_ACTIVE_ENROLLMENT,
    ERR_ENROLLMENT_TERMINAL,
    ERR_INVALID_CLAIM_STATE,
    ERR_INVALID_COMPLAINT_STATE,
    ERR_INVALID_DISPATCH_STATE,
    ERR_INVALID_PARTNER_STATE,
    ERR_MAILING_SUPPRESSED,
    ERR_NO_FILED_PRODUCT,
    ERR_OWNERSHIP_NOT_ELIGIBLE,
    ERR_PARTNER_NOT_ACTIVE,
    ERR_REVISION_LIMIT_REACHED,
)
from test_helpers.assertions import (
    assert_drop_summary_shape,
    assert_instant,
    assert_list_envelope,
    assert_refused,
    assert_uuid,
)
from test_helpers.constants import (
    CLOCK_COVERAGE_ACTIVE,
    CLOCK_ENROLLMENT_DAY,
    CLOCK_START,
)
from test_helpers.test_users import (
    BILLING_OPS,
    CLAIMS_ADJUSTER,
    CLAIMS_ADJUSTER_USER_ID,
    CUSTOMER_SERVICE_REP,
    MARKETING_OPS,
    PLATFORM_ADMIN,
    REGULATORY_AFFAIRS,
    make_network_contractor_headers,
    make_policyholder_headers,
)

# The address used by every single-premises world below.
ADDRESS = "18 Alder Court"


class TestPartnerLifecycleGates:
    """The partner state graph and the cross-entity gates hanging off it."""

    def test_partner_status_transitions_outside_the_declared_graph(self, api):
        """An undefined (from, to) pair is refused even with a current version.

        PRD: "`TERMINATED` is terminal in the strongest sense: no `target_status` whatsoever is reachable from it, and any attempt is refused with `ERR_INVALID_PARTNER_STATE`. That same code answers any other undefined pairing, such as an attempt to suspend a partner that is still `ONBOARDING`."

        Design: Corner/errors/err_partner_status_transitions_outside_the_declared_graph
        """
        fixtures.set_clock(api, CLOCK_START)

        partner_a = fixtures.create_partner(api)
        fixtures.file_product(api, partner_a["id"])
        assert partner_a["status"] == "ONBOARDING"

        partner_b = fixtures.create_partner(
            api, name="Willamette Power", utility_type="ELECTRIC", state_code="OR"
        )
        product_b = fixtures.file_product(
            api,
            partner_b["id"],
            name="Electric Mast Protect",
            line_type="EXTERIOR_ELECTRIC",
            ownership_boundary="METER",
            required_owned_segment="EXTERIOR_ELECTRIC_MAST",
            monthly_price_cents=1500,
            per_occurrence_cap_cents=100000,
            annual_cap_cents=300000,
            permit_covered=False,
            restoration_covered_scope="NONE",
            cap_reset_basis="CALENDAR_YEAR",
        )
        fixtures.activate_partner(
            api, partner_b["id"], fixtures.refresh_partner_version(api, partner_b["id"])
        )
        terminated = fixtures.change_partner_status(
            api,
            partner_b["id"],
            "TERMINATED",
            fixtures.refresh_partner_version(api, partner_b["id"]),
            reason="Contract ended.",
        )
        assert terminated["status"] == "TERMINATED"
        b_version = terminated["version"]

        # ONBOARDING -> SUSPENDED: a legal enum member, an undeclared pairing.
        a_version = fixtures.refresh_partner_version(api, partner_a["id"])
        refused_suspend = api.change_partner_status(
            partner_a["id"],
            factories.partner_status_change_payload(
                "SUSPENDED", a_version, reason="Suspend straight out of onboarding."
            ),
            PLATFORM_ADMIN,
        )
        assert_refused(refused_suspend, ERR_INVALID_PARTNER_STATE, 409)

        # TERMINATED -> ACTIVE: nothing at all leaves the terminal state.
        refused_revival = api.change_partner_status(
            partner_b["id"],
            factories.partner_status_change_payload(
                "ACTIVE", b_version, reason="Try to revive a terminated partner."
            ),
            PLATFORM_ADMIN,
        )
        assert_refused(refused_revival, ERR_INVALID_PARTNER_STATE, 409)

        after_a = validate_success(api.get_partner(partner_a["id"], PLATFORM_ADMIN))
        assert after_a["status"] == "ONBOARDING"
        assert after_a["version"] == a_version, "a rejected transition never bumps the version"

        after_b = validate_success(api.get_partner(partner_b["id"], PLATFORM_ADMIN))
        assert after_b["status"] == "TERMINATED"
        assert after_b["version"] == b_version

        # The termination cascade had already withdrawn the partner's products.
        rows, _ = assert_list_envelope(
            api.list_products(PLATFORM_ADMIN, params={"partner_id": partner_b["id"]}),
            expected_total=1,
        )
        assert rows[0]["id"] == product_b["id"]
        assert rows[0]["status"] == "WITHDRAWN"

    def test_no_filed_product_blocks_partner_activation(self, api):
        """Activation is gated on a non-empty AVAILABLE product shelf.

        PRD: "From `ONBOARDING` the only reachable state is `ACTIVE`, and even that transition is gated: a partner with no product currently in `AVAILABLE` may not be activated, and the attempt is refused with `ERR_NO_FILED_PRODUCT`."

        Design: Corner/errors/err_no_filed_product_blocks_partner_activation
        """
        fixtures.set_clock(api, CLOCK_START)
        partner = fixtures.create_partner(api)
        assert partner["status"] == "ONBOARDING"

        refused = api.change_partner_status(
            partner["id"],
            factories.partner_status_change_payload(
                "ACTIVE", partner["version"], reason="Activate with an empty product shelf."
            ),
            PLATFORM_ADMIN,
        )
        assert_refused(refused, ERR_NO_FILED_PRODUCT, 409)

        unchanged = validate_success(api.get_partner(partner["id"], PLATFORM_ADMIN))
        assert unchanged["status"] == "ONBOARDING"
        assert unchanged["version"] == partner["version"], (
            "the refused transition consumed no version"
        )

        product = fixtures.file_product(api, partner["id"])
        assert product["status"] == "AVAILABLE"

        before = fixtures.refresh_partner_version(api, partner["id"])
        activated = fixtures.activate_partner(api, partner["id"], before)
        assert activated["status"] == "ACTIVE"
        assert activated["version"] == before + 1
        assert activated["suspension_reason"] is None

    def test_partner_not_active_gates_filing_campaigns_and_enrollment(self, api):
        """One gate refuses a product filing, a campaign draft and an enrollment.

        PRD: "`ERR_PARTNER_NOT_ACTIVE` fires when the owning partner is not `ACTIVE` on five operations: filing a product, creating a campaign, submitting a campaign, dropping mail, and creating an enrollment."

        Design: Corner/errors/err_partner_not_active_gates_filing_campaigns_and_enrollment
        """
        world = fixtures.partner_product_premises(
            api, premises_overrides={"street_address": ADDRESS}
        )
        suspended = fixtures.change_partner_status(
            api,
            world["partner_id"],
            "SUSPENDED",
            fixtures.refresh_partner_version(api, world["partner_id"]),
            reason="Complaint volume review.",
        )
        assert suspended["status"] == "SUSPENDED"

        refused_filing = api.create_product(
            factories.product_payload(
                world["partner_id"],
                name="Sewer Line Protect",
                line_type="SEWER_LATERAL",
                ownership_boundary="PROPERTY_LINE",
                required_owned_segment="SEWER_PROPERTY_LINE_TO_MAIN",
                monthly_price_cents=3200,
                per_occurrence_cap_cents=900000,
                annual_cap_cents=1200000,
            ),
            PLATFORM_ADMIN,
        )
        assert_refused(refused_filing, ERR_PARTNER_NOT_ACTIVE, 409)

        refused_campaign = api.create_campaign(
            factories.campaign_payload(
                world["partner_id"],
                world["product_id"],
                name="September water drop",
                drop_date="2026-09-01",
                requested_quantity=500,
            ),
            MARKETING_OPS,
        )
        assert_refused(refused_campaign, ERR_PARTNER_NOT_ACTIVE, 409)

        # The declared premises version is current, so this is the cross-entity
        # gate and not a stale-snapshot rejection.
        refused_enrollment = api.create_enrollment(
            factories.enrollment_payload(
                world["premises_id"],
                world["product_id"],
                world["premises_version"],
                prepaid_amount_cents=None,
            ),
            CUSTOMER_SERVICE_REP,
        )
        assert_refused(refused_enrollment, ERR_PARTNER_NOT_ACTIVE, 409)

        assert_list_envelope(
            api.list_products(PLATFORM_ADMIN, params={"partner_id": world["partner_id"]}),
            expected_total=1,
        )
        assert_list_envelope(
            api.list_enrollments(
                CUSTOMER_SERVICE_REP, params={"premises_id": world["premises_id"]}
            ),
            expected_total=0,
        )
        assert (
            fixtures.refresh_premises_version(api, world["premises_id"])
            == world["premises_version"]
        )


class TestClaimAndDispatchGates:
    """The claim state graph and the ordered dispatch event chain."""

    def test_claim_state_gate_rejects_an_early_appeal_and_a_second_triage(self, api):
        """An appeal before the denial and a triage after it both hit one gate.

        PRD: "A claim in the wrong state yields `ERR_INVALID_CLAIM_STATE` — a triage decision requires `TRIAGE`; dispatching requires `APPROVED`, or `DISPATCHED` when the request names an open dispatch of the same claim to supersede; opening an appeal requires `DENIED`; an appeal decision requires `APPEAL_OPEN`."

        Design: Corner/errors/err_claim_state_gate_rejects_an_early_appeal_and_a_second_triage
        """
        world = fixtures.enrolled_premises(
            api, fixtures.partner_product_premises(
                api, premises_overrides={"street_address": ADDRESS}
            )
        )
        claim = fixtures.file_claim(
            api, world["enrollment_id"], incident_description="Seepage at the curb box."
        )
        assert claim["status"] == "TRIAGE"
        assert claim["eligibility_assessment"] == "WAITING_PERIOD"

        # The policyholder of the insured premises is the right role, so the
        # refusal below is the state gate and not an authorization decision.
        early_appeal = api.create_appeal(
            claim["id"],
            factories.appeal_payload(
                appeal_reason="Appealing before anyone has decided anything."
            ),
            make_policyholder_headers(world["premises_id"]),
        )
        assert_refused(early_appeal, ERR_INVALID_CLAIM_STATE, 409)

        denied = fixtures.deny_claim(
            api,
            claim["id"],
            "WAITING_PERIOD",
            coverage_note="Loss reported inside the waiting period.",
        )
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "WAITING_PERIOD"
        assert denied["triage_decided_by_user_id"] == CLAIMS_ADJUSTER_USER_ID
        assert_instant(denied["denied_at"], CLOCK_ENROLLMENT_DAY, "denied_at")
        assert denied["version"] == 2

        second_triage = api.triage_claim(
            claim["id"],
            factories.triage_approval_payload(coverage_note="A second bite at triage."),
            CLAIMS_ADJUSTER,
        )
        assert_refused(second_triage, ERR_INVALID_CLAIM_STATE, 409)

        final = validate_success(api.get_claim(claim["id"], CLAIMS_ADJUSTER))
        assert final["status"] == "DENIED"
        assert final["appeal_count"] == 0
        assert final["version"] == 2, "neither refusal mutated the claim"

    def test_dispatch_event_order_is_enforced_by_the_state_gate(self, api):
        """ARRIVE and COMPLETE are both refused while the dispatch is ASSIGNED.

        PRD: "An event whose state precondition is unmet — accepting a dispatch that is not `ASSIGNED`, arriving at one that is not `ACCEPTED` — is refused with `ERR_INVALID_DISPATCH_STATE`."

        Design: Corner/errors/err_dispatch_event_order_is_enforced_by_the_state_gate
        """
        world = fixtures.partner_product_premises(
            api, premises_overrides={"street_address": ADDRESS}
        )
        contractor = fixtures.create_contractor(
            api, name="Cascade Trenchless", license_expires_on="2027-06-30"
        )
        world = fixtures.active_coverage(api, world, CLOCK_COVERAGE_ACTIVE)
        assert world["enrollment"]["coverage_status"] == "ACTIVE"

        claim = fixtures.file_claim(
            api,
            world["enrollment_id"],
            incident_description="Line failure at the curb stop.",
        )
        approved = fixtures.approve_claim(
            api, claim["id"], coverage_note="Covered failure inside the ownership boundary."
        )
        assert approved["status"] == "APPROVED"

        dispatch = fixtures.dispatch_claim_to(
            api,
            claim["id"],
            approved["version"],
            contractor["id"],
            "2026-09-10T09:00:00.000Z",
        )
        assert dispatch["status"] == "ASSIGNED"
        assert dispatch["selection_mode"] == "MANUAL"
        assert dispatch["version"] == 1
        # A four-hour window, and the SLA measured from the claim's reported_at.
        assert_instant(dispatch["window_end"], "2026-09-10T13:00:00.000Z", "window_end")
        assert_instant(
            dispatch["sla_deadline_at"], "2026-09-13T08:00:00.000Z", "sla_deadline_at"
        )
        assert dispatch["estimated_benefit_cents"] == 228000
        assert dispatch["responded_at"] is None
        assert dispatch["response_minutes"] is None

        contractor_headers = make_network_contractor_headers(contractor["id"])
        early_arrive = api.create_dispatch_event(
            dispatch["id"], factories.arrive_event_payload(), contractor_headers
        )
        assert_refused(early_arrive, ERR_INVALID_DISPATCH_STATE, 409)

        early_complete = api.create_dispatch_event(
            dispatch["id"],
            factories.full_complete_event_payload(),
            contractor_headers,
        )
        assert_refused(early_complete, ERR_INVALID_DISPATCH_STATE, 409)

        still_assigned = fixtures.refresh_dispatch(api, dispatch["id"])
        assert still_assigned["status"] == "ASSIGNED"
        assert still_assigned["version"] == 1, "two refused events wrote nothing"

        # Only ACCEPT is legal here, and it moves the chain on by one link.
        fixtures.set_clock(api, "2026-09-10T10:30:00.000Z")
        accepted = fixtures.accept_dispatch(api, dispatch["id"], contractor["id"])
        assert accepted["status"] == "ACCEPTED"
        assert_instant(accepted["responded_at"], "2026-09-10T10:30:00.000Z", "responded_at")
        assert accepted["response_minutes"] == 150
        assert accepted["version"] == 2
        assert fixtures.refresh_claim(api, claim["id"])["status"] == "DISPATCHED"


class TestEnrollmentAndCampaignGates:
    """Terminal coverage, the bounded revision cycle and the drop-date guard."""

    def test_enrollment_terminal_blocks_every_later_write(self, api):
        """Four different writes on a cancelled policy share one refusal code.

        PRD: "`LAPSED` is the terminal coverage state, and a lapsed or cancelled policy refuses cancellation, renewal notices, billing events and new claims alike with `ERR_ENROLLMENT_TERMINAL`."

        Design: Corner/errors/err_enrollment_terminal_blocks_every_later_write
        """
        world = fixtures.enrolled_premises(
            api, fixtures.partner_product_premises(
                api, premises_overrides={"street_address": ADDRESS}
            )
        )
        cancelled = fixtures.cancel_enrollment(
            api, world["enrollment_id"], "2026-08-05", reason="MOVED"
        )
        assert cancelled["coverage_status"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "MOVED"
        assert cancelled["version"] == 2
        terminal_version = cancelled["version"]

        refused_claim = api.create_claim(
            factories.claim_payload(
                world["enrollment_id"],
                urgency="EMERGENCY",
                incident_description="Claim filed the day after cancellation.",
            ),
            CUSTOMER_SERVICE_REP,
        )
        assert_refused(refused_claim, ERR_ENROLLMENT_TERMINAL, 409)

        refused_billing = api.create_billing_event(
            world["enrollment_id"],
            factories.billing_event_payload(
                "PREMIUM_PAYMENT", "2026-08-06", amount_cents=2499
            ),
            BILLING_OPS,
        )
        assert_refused(refused_billing, ERR_ENROLLMENT_TERMINAL, 409)

        # The guard carries the policy's current version, so this is the
        # terminal-state gate and not a stale-snapshot rejection.
        refused_renewal = api.create_renewal_notice(
            world["enrollment_id"],
            factories.renewal_notice_payload(2600, "2027-08-05", terminal_version),
            BILLING_OPS,
        )
        assert_refused(refused_renewal, ERR_ENROLLMENT_TERMINAL, 409)

        refused_second_cancellation = api.cancel_enrollment(
            world["enrollment_id"],
            factories.cancellation_payload("2026-08-06", reason="CUSTOMER_REQUEST"),
            CUSTOMER_SERVICE_REP,
        )
        assert_refused(refused_second_cancellation, ERR_ENROLLMENT_TERMINAL, 409)

        assert_list_envelope(
            api.list_claims(
                CUSTOMER_SERVICE_REP, params={"enrollment_id": world["enrollment_id"]}
            ),
            expected_total=0,
        )
        final = fixtures.refresh_enrollment(api, world["enrollment_id"])
        assert final["coverage_status"] == "CANCELLED"
        assert final["cancellation_reason"] == "MOVED"
        assert final["renewal_notice_status"] == "NONE"
        assert final["version"] == terminal_version, "four refusals wrote nothing"

    def test_revision_limit_reached_on_the_third_resubmission(self, api):
        """Two rejections may be reworked; the third resubmission is refused.

        PRD: "The cycle is bounded: a campaign whose `revision_count` has already reached 2 may not be resubmitted again, and the third attempt is refused with `ERR_REVISION_LIMIT_REACHED`."

        Design: Corner/errors/err_revision_limit_reached_on_the_third_resubmission
        """
        world = fixtures.active_partner_with_product(api)
        campaign = fixtures.create_campaign(
            api,
            world["partner_id"],
            world["product_id"],
            name="August water drop",
            drop_date="2026-08-25",
            requested_quantity=1000,
        )
        assert campaign["status"] == "DRAFT"
        assert campaign["revision_count"] == 0
        assert campaign["version"] == 1

        first = fixtures.submit_campaign(api, campaign["id"], note="First submission.")
        assert first["status"] == "PARTNER_REVIEW"
        assert first["revision_count"] == 0

        fixtures.reject_campaign(
            api, campaign["id"], world["partner_id"], decision_note="Logo placement is wrong."
        )
        second = fixtures.submit_campaign(api, campaign["id"], note="Reworked the logo.")
        assert second["status"] == "PARTNER_REVIEW"
        assert second["revision_count"] == 1

        fixtures.reject_campaign(
            api, campaign["id"], world["partner_id"], decision_note="Disclaimer font too small."
        )
        third = fixtures.submit_campaign(api, campaign["id"], note="Enlarged the disclaimer.")
        assert third["status"] == "PARTNER_REVIEW"
        assert third["revision_count"] == 2

        rejected = fixtures.reject_campaign(
            api, campaign["id"], world["partner_id"], decision_note="Still not acceptable."
        )
        assert rejected["status"] == "REJECTED"
        # Creation plus six accepted writes: three submissions and three decisions.
        assert rejected["version"] == 7

        refused = api.submit_campaign(
            campaign["id"],
            factories.campaign_submission_payload(note="A fourth attempt at review."),
            MARKETING_OPS,
        )
        assert_refused(refused, ERR_REVISION_LIMIT_REACHED, 409)

        final = validate_success(api.get_campaign(campaign["id"], MARKETING_OPS))
        assert final["status"] == "REJECTED"
        assert final["revision_count"] == 2
        assert final["version"] == 7, "the refused resubmission consumed no version"

    def test_drop_date_in_future_blocks_the_mail_drop(self, api):
        """One hour early the drop is refused; at midnight it succeeds.

        PRD: "A drop attempted before its own drop date is refused with `ERR_DROP_DATE_IN_FUTURE`."

        Design: Corner/errors/err_drop_date_in_future_blocks_the_mail_drop
        """
        world = fixtures.partner_product_premises(
            api, premises_overrides={"street_address": ADDRESS}
        )
        campaign = fixtures.create_campaign(
            api,
            world["partner_id"],
            world["product_id"],
            name="September water drop",
            piece_type="DIRECT_MAIL_LETTER",
            drop_date="2026-09-01",
            requested_quantity=1000,
        )
        fixtures.submit_campaign(api, campaign["id"], note="Submitted for brand review.")
        approved = fixtures.approve_campaign(
            api,
            campaign["id"],
            world["partner_id"],
            decision_note="Approved at the requested quantity.",
            approved_quantity=None,
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_quantity"] == 1000
        assert approved["version"] == 3

        # One hour before the drop date, on the previous calendar day.
        fixtures.set_clock(api, "2026-08-31T23:00:00.000Z")
        refused = api.mail_drop(campaign["id"], MARKETING_OPS)
        assert_refused(refused, ERR_DROP_DATE_IN_FUTURE, 422)

        still_approved = validate_success(api.get_campaign(campaign["id"], MARKETING_OPS))
        assert still_approved["status"] == "APPROVED"
        assert still_approved["mail_dropped_at"] is None
        assert still_approved["version"] == 3

        # The comparison is on the calendar date, so midnight is enough.
        fixtures.set_clock(api, "2026-09-01T00:00:00.000Z")
        summary = fixtures.mail_drop(api, campaign["id"])
        assert_drop_summary_shape(summary)
        assert summary["status"] == "MAILED"
        assert summary["mailed_count"] == 1
        assert summary["suppressed_count"] == 0
        assert summary["mailed_premises_ids"] == [world["premises_id"]]

        premises_after = validate_success(
            api.get_premises(world["premises_id"], MARKETING_OPS)
        )
        assert premises_after["last_mail_decision"] == "MAILED"
        assert premises_after["last_mailed_campaign_id"] == campaign["id"]
        assert premises_after["mail_count_current_year"] == 1
        assert premises_after["version"] == 2


class TestComplaintAndPrecedenceGates:
    """Complaint closure states, suppression at the point of sale, and precedence."""

    def test_invalid_complaint_state_on_escalating_a_live_complaint(self, api):
        """Escalation is legal only from CLOSED_UNSUBSTANTIATED, not OPEN nor substantiated.

        PRD: "A complaint in the wrong state yields `ERR_INVALID_COMPLAINT_STATE` — a response requires `OPEN`, `OVERDUE` or `ESCALATED`, an escalation requires `CLOSED_UNSUBSTANTIATED`."

        Design: Corner/errors/err_invalid_complaint_state_on_escalating_a_live_complaint
        """
        world = fixtures.active_partner_with_product(api)

        still_open = fixtures.create_complaint(
            api,
            world["partner_id"],
            allegation="The mailer implies the utility itself endorses the product.",
        )
        assert still_open["status"] == "OPEN"
        assert still_open["escalation_count"] == 0
        # PUC's base window is ten whole days from the instant of receipt.
        assert_instant(
            still_open["response_due_at"], "2026-08-11T00:00:00.000Z", "response_due_at"
        )

        admitted = fixtures.create_complaint(
            api,
            world["partner_id"],
            allegation="A second, unrelated allegation about the same mailer run.",
        )
        closed = fixtures.respond_to_complaint(
            api,
            admitted["id"],
            "SUBSTANTIATED",
            "APOLOGY_ONLY",
            admitted["version"],
            response_summary="The wording was corrected and an apology was sent.",
        )
        assert closed["status"] == "CLOSED_SUBSTANTIATED"
        assert closed["version"] == 2

        refused_open = api.escalate_complaint(
            still_open["id"],
            factories.escalation_payload(
                escalation_note="Escalating a complaint that is still open."
            ),
            REGULATORY_AFFAIRS,
        )
        assert_refused(refused_open, ERR_INVALID_COMPLAINT_STATE, 409)

        refused_substantiated = api.escalate_complaint(
            admitted["id"],
            factories.escalation_payload(
                escalation_note="Escalating an admission that cannot be un-admitted."
            ),
            REGULATORY_AFFAIRS,
        )
        assert_refused(refused_substantiated, ERR_INVALID_COMPLAINT_STATE, 409)

        after_open = fixtures.refresh_complaint(api, still_open["id"])
        assert after_open["status"] == "OPEN"
        assert after_open["escalation_count"] == 0
        assert after_open["version"] == still_open["version"]

        after_admitted = fixtures.refresh_complaint(api, admitted["id"])
        assert after_admitted["status"] == "CLOSED_SUBSTANTIATED"
        assert after_admitted["escalation_count"] == 0
        assert after_admitted["remedy_type"] == "APOLOGY_ONLY"
        assert after_admitted["version"] == 2

    def test_mailing_suppressed_blocks_a_campaign_sourced_enrollment(self, api):
        """The same address the drop suppressed cannot be sold on that campaign.

        PRD: "Furthermore the address must actually have been mailed by that campaign — if the address's `last_mailed_campaign_id` is not that campaign, or its `last_mail_decision` is `SUPPRESSED`, the enrollment is refused with `ERR_MAILING_SUPPRESSED`, because selling to an address the compliance rules suppressed is exactly what the suppression rules exist to prevent."

        Design: Corner/errors/err_mailing_suppressed_blocks_a_campaign_sourced_enrollment
        """
        world = fixtures.partner_product_premises(
            api,
            premises_overrides={"street_address": ADDRESS, "do_not_mail": True},
        )
        assert world["premises"]["suppression_reason"] == "DNM_REQUEST"
        assert world["premises"]["suppressed"] is True
        assert world["premises"]["last_mail_decision"] == "NOT_EVALUATED"

        campaign = fixtures.create_campaign(
            api,
            world["partner_id"],
            world["product_id"],
            name="August water drop",
            drop_date="2026-08-01",
            requested_quantity=1000,
        )
        fixtures.submit_campaign(api, campaign["id"], note="Submitted for brand review.")
        fixtures.approve_campaign(
            api,
            campaign["id"],
            world["partner_id"],
            decision_note="Approved as requested.",
            approved_quantity=None,
        )
        summary = fixtures.mail_drop(api, campaign["id"])
        assert_drop_summary_shape(summary)
        assert summary["status"] == "MAILED"
        assert summary["mailed_count"] == 0
        assert summary["suppressed_count"] == 1
        assert summary["suppressed_by_reason"] == {"DNM_REQUEST": 1}
        assert summary["mailed_premises_ids"] == []

        premises_after = validate_success(
            api.get_premises(world["premises_id"], MARKETING_OPS)
        )
        assert premises_after["last_mail_decision"] == "SUPPRESSED"
        assert premises_after["last_mail_suppression_reason"] == "DNM_REQUEST"
        assert premises_after["last_mailed_campaign_id"] is None
        assert premises_after["mail_count_current_year"] == 0
        assert premises_after["version"] == 2

        refused = api.create_enrollment(
            factories.enrollment_payload(
                world["premises_id"],
                world["product_id"],
                premises_after["version"],
                prepaid_amount_cents=None,
                source_campaign_id=campaign["id"],
            ),
            CUSTOMER_SERVICE_REP,
        )
        assert_refused(refused, ERR_MAILING_SUPPRESSED, 409)

        # The same sale as a direct inbound one skips the attribution gates.
        direct = validate_success(
            api.create_enrollment(
                factories.enrollment_payload(
                    world["premises_id"],
                    world["product_id"],
                    premises_after["version"],
                    prepaid_amount_cents=None,
                ),
                CUSTOMER_SERVICE_REP,
            ),
            201,
        )
        assert_uuid(direct["id"])
        assert direct["source_campaign_id"] is None
        assert direct["coverage_status"] == "PENDING_WAITING_PERIOD"

    def test_enrollment_gates_bill_insert_then_ownership_then_duplicate(self, api):
        """A referential rule outranks a constraint rule on the same request.

        PRD: "Which error the caller sees is not a matter of implementation convenience: validations are evaluated in a strict ascending precedence, the **first** violated rule produces the response, and no later rule is evaluated."

        Design: Corner/errors/err_enrollment_gates_bill_insert_then_ownership_then_duplicate
        """
        fixtures.set_clock(api, CLOCK_START)
        partner = fixtures.create_partner(api, bill_insert_supported=False)
        product = fixtures.file_product(api, partner["id"])
        fixtures.activate_partner(
            api, partner["id"], fixtures.refresh_partner_version(api, partner["id"])
        )

        # This address does not own the insured segment, so it violates the
        # ownership rule as well as the billing-mode rule.
        wrong_segment = fixtures.create_premises(
            api,
            partner["id"],
            street_address=ADDRESS,
            owned_segments=["WATER_METER_TO_HOME"],
        )
        eligible = fixtures.create_premises(
            api, partner["id"], street_address="22 Birch Lane"
        )

        both_violated = api.create_enrollment(
            factories.enrollment_payload(
                wrong_segment["id"],
                product["id"],
                wrong_segment["version"],
                billing_mode="BILL_INSERT",
                prepaid_amount_cents=None,
            ),
            CUSTOMER_SERVICE_REP,
        )
        assert_refused(both_violated, ERR_BILL_INSERT_NOT_SUPPORTED, 422)

        # With the billing mode repaired, the later rule finally speaks.
        ownership_only = api.create_enrollment(
            factories.enrollment_payload(
                wrong_segment["id"], product["id"], wrong_segment["version"]
            ),
            CUSTOMER_SERVICE_REP,
        )
        assert_refused(ownership_only, ERR_OWNERSHIP_NOT_ELIGIBLE, 422)

        first = validate_success(
            api.create_enrollment(
                factories.enrollment_payload(
                    eligible["id"], product["id"], eligible["version"]
                ),
                CUSTOMER_SERVICE_REP,
            ),
            201,
        )
        assert first["coverage_status"] == "PENDING_WAITING_PERIOD"
        assert first["billing_mode"] == "DIRECT_BILL"

        duplicate = api.create_enrollment(
            factories.enrollment_payload(
                eligible["id"],
                product["id"],
                fixtures.refresh_premises_version(api, eligible["id"]),
            ),
            CUSTOMER_SERVICE_REP,
        )
        assert_refused(duplicate, ERR_DUPLICATE_ACTIVE_ENROLLMENT, 422)

        assert_list_envelope(
            api.list_enrollments(
                CUSTOMER_SERVICE_REP, params={"premises_id": eligible["id"]}
            ),
            expected_total=1,
        )
        assert_list_envelope(
            api.list_enrollments(
                CUSTOMER_SERVICE_REP, params={"premises_id": wrong_segment["id"]}
            ),
            expected_total=0,
        )
