"""Difficulty queue — cross-entity state dependencies: a MediationCase can
only open on an UNRESOLVED complaint (PRD §3.5), and an application's APPROVE
is gated on the business's advertising-review state (PRD §3.2)."""

from test_helpers import (
    ApiErrorId,
    CLOCK_START_ISO,
    PREPAID_TOTAL_FEE0_CENTS,
    TEST_USERS,
    business_respond,
    conclude_advertising_review,
    consumer_reject,
    create_application,
    create_bureau,
    create_business,
    create_consumer,
    decide_application_payload,
    file_and_forward_complaint,
    get_application,
    get_business,
    get_complaint,
    get_invoice,
    open_advertising_review,
    parse_iso,
    set_clock,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)
from datetime import timedelta

ADMIN = TEST_USERS["bureau_admin_headers"]
REVIEWER = TEST_USERS["standards_reviewer_headers"]


def _setup_world_with_business():
    set_clock(CLOCK_START_ISO)
    bureau = create_bureau(name="Heartland Bureau",
                           territory_state_codes=["IA", "NE"],
                           local_dues_fee_cents=0)
    consumer = create_consumer(full_name="Pat Consumer",
                               email="pat@example.com", home_state_code="IA")
    return bureau, consumer


class TestMediationOfferRequiresUnresolved:
    def _setup_response_received(self):
        _bureau, consumer = _setup_world_with_business()
        business = create_business(legal_name="BigBox Services Inc",
                                   home_state_code="IA", employee_count=250,
                                   founded_on="2018-01-01T00:00:00Z")
        complaint = file_and_forward_complaint(consumer, business,
                                               category="SERVICE",
                                               description="mediation gate")
        complaint = business_respond(complaint, business,
                                     body="initial offer")
        return consumer, business, complaint

    def test_offer_on_response_received_rejected(self, api):
        """PRD §3.5: "A `BureauAdmin` may offer mediation on an `UNRESOLVED`
        complaint, but only within the mediation window: the offer must arrive
        no later than 14 days after the complaint's `last_unresolved_at`, and
        a later offer is rejected with `ERR_MEDIATION_WINDOW_EXPIRED`."
        PRD §2.7: "The target resource must be in a valid from-state for the
        requested transition — submit needs `DRAFT`, decision needs
        `SUBMITTED`, reapplication needs `DENIED`; forward needs `RECEIVED`;
        a business response needs `FORWARDED` or `CONSUMER_REBUTTED`; a
        consumer verdict or rebuttal needs `RESPONSE_RECEIVED`; reopen needs
        `RESOLVED` or `UNANSWERED`; a mediation offer needs `UNRESOLVED`;
        arbitration needs `MEDIATION_FAILED`"

        Design: Difficulty/cross_entity_state_dependency/mediation_offer_requires_complaint_unresolved
        """
        _consumer, _business, complaint = self._setup_response_received()
        resp = api.create_mediation_case(complaint["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_INVALID_STATE)
        rows, meta = validate_paginated(
            api.list_mediation_cases(complaint["id"], ADMIN))
        assert rows == [] and meta["total_count"] == 0
        assert get_complaint(complaint["id"])["status"] == "RESPONSE_RECEIVED"

    def test_offer_after_consumer_reject_succeeds(self, api):
        """PRD §3.5: "The offer creates a MediationCase in `OFFERED` — its
        `complaint_id` is implied by the complaint under which it is created —
        stamps `offered_at`, and sets `offer_deadline_at` exactly 7 days
        later; the complaint moves to `MEDIATION_OFFERED`."
        PRD §3.4: "`last_unresolved_at` is stamped on the first entry into
        `UNRESOLVED` only — later returns to `UNRESOLVED` do not refresh it"

        Design: Difficulty/cross_entity_state_dependency/mediation_offer_requires_complaint_unresolved
        """
        consumer, _business, complaint = self._setup_response_received()
        complaint = consumer_reject(complaint, consumer,
                                    body="still unhappy")
        assert complaint["status"] == "UNRESOLVED"
        resp = api.create_mediation_case(complaint["id"], ADMIN)
        case = validate_success(resp, 201)
        assert case["status"] == "OFFERED"
        assert case["complaint_id"] == complaint["id"]
        assert parse_iso(case["offer_deadline_at"]) == parse_iso(
            case["offered_at"]) + timedelta(days=7)
        after = get_complaint(complaint["id"])
        assert after["status"] == "MEDIATION_OFFERED"
        assert parse_iso(after["last_unresolved_at"]) == parse_iso(
            CLOCK_START_ISO)


class TestApproveBlockedUntilAdReviewClears:
    def _setup_submitted_with_open_review(self):
        _bureau, _consumer = _setup_world_with_business()
        business = create_business(legal_name="MidSize Manufacturing LLC",
                                   home_state_code="IA", employee_count=50,
                                   founded_on="2020-01-01T00:00:00Z")
        app = create_application(business, billing_plan="ANNUAL_PREPAID",
                                 license_number="LIC-M-1")
        app = submit_application(app)
        review = open_advertising_review(
            business,
            claim_description="claims #1 in USA without substantiation",
            as_reviewer=True)
        return business, app, review

    def test_approve_rejected_while_review_under_review(self, api):
        """PRD §3.2: "The business must have no advertising review in
        `UNDER_REVIEW` or `REFERRED_TO_REGULATOR`, or the decision is rejected
        with `ERR_ADVERTISING_REVIEW_ADVERSE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/application_approve_blocked_until_ad_review_clears
        """
        business, app, _review = self._setup_submitted_with_open_review()
        resp = api.decide_application(app["id"], decide_application_payload(),
                                      REVIEWER)
        validate_error(resp, ApiErrorId.ERR_ADVERTISING_REVIEW_ADVERSE)
        current = get_application(business["id"], app["id"])
        assert current["status"] == "SUBMITTED"
        assert current["dues_invoice_id"] is None

    def test_approve_succeeds_after_review_cleared(self, api):
        """PRD §3.8: "An `outcome` of `CLEARED` closes the review as `CLEARED`
        with `concluded_at` stamped; the business returns to `CLEAR` only when
        no other review of that business remains `UNDER_REVIEW` — if one does,
        the business stays `UNDER_AD_REVIEW` — and the same condition lets a
        referred business return to `CLEAR`."
        PRD §3.3: "its `base_amount_cents` is the tier base dues — 42500 cents
        for `MICRO`, 68000 cents for `SMALL`, 115000 cents for `MEDIUM`, and
        240000 cents for `LARGE`"

        Design: Difficulty/cross_entity_state_dependency/application_approve_blocked_until_ad_review_clears
        """
        business, app, review = self._setup_submitted_with_open_review()
        conclude_advertising_review(review, outcome="CLEARED")
        assert get_business(business["id"])[
            "advertising_compliance_status"] == "CLEAR"
        resp = api.decide_application(app["id"], decide_application_payload(),
                                      REVIEWER)
        decided = validate_success(resp, 200)
        assert decided["status"] == "APPROVED_PENDING_DUES"
        assert decided["dues_invoice_id"], "approval must issue an invoice"
        invoice = get_invoice(business["id"], decided["dues_invoice_id"])
        # MEDIUM prepaid in a zero-fee bureau: 115000 * 0.95.
        assert invoice["amount_due_cents"] == \
            PREPAID_TOTAL_FEE0_CENTS["MEDIUM"] == 109250
        assert invoice["status"] == "ISSUED"
