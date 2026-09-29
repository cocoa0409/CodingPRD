"""The partner-admission review cycle: initial states, screening, the decision fork,
resubmission and the revision cap."""

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_APPLICATION_NOT_SCREENED,
    ERR_APPLICATION_TERMINAL,
    ERR_REVISION_LIMIT_REACHED,
)
from test_helpers.assertions import (
    assert_created,
    assert_error_response,
    assert_field,
    assert_fields,
    assert_fresh_creation,
    assert_null,
    assert_object_response,
    assert_one_decimal_score,
    assert_version_bumped,
)
from test_helpers.fixtures import (
    create_network,
    decide_application,
    file_application,
    mint_link,
    pin_clock,
    read_affiliate,
    register_affiliate,
    screen_application,
)
from test_helpers.test_users import (
    ANONYMOUS,
    COMPLIANCE_ANALYST,
    COMPLIANCE_ANALYST_ID,
    PARTNER_MANAGER,
    PARTNER_MANAGER_ID,
    SECOND_COMPLIANCE_ANALYST,
    make_affiliate_partner_headers,
)

CLOCK = f.JUL_05_00_00

#: The five measurements that screen a strong editorial site: §3.2 makes the base
#: 0.45*80 + 0.35*92 + 0.20*(100 - 200/100) = 36.0 + 32.2 + 19.6 = 87.8.
STRONG_SCREEN = dict(
    domain_authority=80,
    content_originality_pct=92,
    broken_link_ratio_bps=200,
    brand_safety_flag_count=0,
    restricted_vertical_overlap_bps=0,
)


class TestInitialReviewStates:
    def test_new_partner_and_its_first_application_land_in_declared_initial_states(
        self, api
    ):
        """Registration and a first filing produce a pending partner and a submitted review.

        PRD §3.1: "A freshly registered partner starts life in `status`
        `PENDING_APPLICATION` with `suspension_cause` `NONE`."

        PRD §3.2: "The application is written with `review_state` `SUBMITTED`,
        `screening_outcome` `NOT_SCREENED` and `revision_round_count` 0, and both score
        fields — `site_quality_score` and `brand_suitability_score` — start as null,
        since nothing has been measured yet."

        Design: Corner/state_machines/affiliate_and_application_start_in_declared_initial_states
        """
        pin_clock(api, CLOCK)
        network = create_network(api)

        partner = assert_created(
            api.create_affiliate(
                {
                    "legal_name": "Beacon Content LLC",
                    "contact_email": "beacon@example.com",
                    "partner_type": "CONTENT",
                    "network_id": network["id"],
                    "payout_currency": "USD",
                },
                ANONYMOUS,
            )
        )
        application = assert_created(
            api.create_application(
                partner["id"],
                f.application_payload(
                    site_url="https://beacon.example",
                    primary_traffic_source="ORGANIC_SEARCH",
                    monthly_traffic_estimate=200000,
                    declared_promo_methods=["EDITORIAL_CONTENT"],
                    product_categories=["APPAREL"],
                ),
                PARTNER_MANAGER,
            )
        )

        assert_fields(
            partner, {"status": "PENDING_APPLICATION", "suspension_cause": "NONE"}
        )
        assert_fields(
            application,
            {
                "review_state": "SUBMITTED",
                "screening_outcome": "NOT_SCREENED",
                "revision_round_count": 0,
                # §3.2: "the application records the applicant on its `affiliate_id`."
                "affiliate_id": partner["id"],
            },
        )
        # §3.2: resubmission "clears `site_quality_score`, `brand_suitability_score`
        # and `screened_by_user_id` back to null" — null is where all three begin.
        assert_null(
            application,
            "site_quality_score",
            "brand_suitability_score",
            "screened_by_user_id",
        )
        assert_fresh_creation(application)

        stored = assert_object_response(
            api.get_application(application["id"], PARTNER_MANAGER)
        )
        assert_fields(
            stored,
            {
                "review_state": "SUBMITTED",
                "screening_outcome": "NOT_SCREENED",
                "revision_round_count": 0,
                "version": 1,
            },
        )
        assert_null(stored, "site_quality_score", "brand_suitability_score")


class TestScreeningStage:
    def test_screen_moves_application_to_screened_with_scores_and_screener_identity(
        self, api
    ):
        """One screen call writes both scores, the derived outcome and the analyst's identity.

        PRD §3.2: "It stamps `screened_by_user_id` with the acting `X-User-ID`, writes
        both scores and the derived `screening_outcome`, and increments the application's
        `version`."

        Design: Corner/state_machines/screen_transition_sets_screened_state_scores_and_screener_identity
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        partner = register_affiliate(api, network["id"], partner_type="CONTENT")
        application = file_application(
            api,
            partner["id"],
            site_url="https://beacon.example",
            primary_traffic_source="ORGANIC_SEARCH",
            monthly_traffic_estimate=200000,
            declared_promo_methods=["EDITORIAL_CONTENT"],
            product_categories=["APPAREL"],
        )

        screened = assert_object_response(
            api.screen_application(
                application["id"], f.screen_payload(**STRONG_SCREEN), COMPLIANCE_ANALYST
            )
        )

        assert_field(screened, "review_state", "SCREENED")
        # §3.2: the base is "forty-five hundredths of `domain_authority`, thirty-five
        # hundredths of `content_originality_pct`, and twenty hundredths of a link-health
        # term", times the 1.00 `ORGANIC_SEARCH` multiplier, with no brand-safety penalty.
        assert_one_decimal_score(screened, "site_quality_score", 87.8)
        # §3.2: brand suitability "starts at 100, subtracts one hundredth of
        # `restricted_vertical_overlap_bps`, and subtracts a further 12 points for each
        # brand-safety flag" — both inputs are 0 here.
        assert_one_decimal_score(screened, "brand_suitability_score", 100.0)
        # §3.2: "The outcome is `PASS` when `site_quality_score` is at least 60.0 and
        # `brand_suitability_score` is at least 70.0."
        assert_field(screened, "screening_outcome", "PASS")
        assert_field(screened, "screened_by_user_id", COMPLIANCE_ANALYST_ID)
        assert_version_bumped(screened, application["version"], "application")

        # The screen writes nothing on the partner: §3.2 enumerates its writes and none
        # of them touch the applicant row.
        applicant = read_affiliate(api, partner["id"])
        assert_fields(
            applicant, {"status": "PENDING_APPLICATION", "version": partner["version"]}
        )

    def test_second_screen_on_already_screened_application_is_refused(self, api):
        """Screening is not re-runnable: the second call keeps the first analyst's record.

        PRD §2.10 rule 19: "The application's `review_state` is `SUBMITTED` when
        screening, `SCREENED` when deciding, and `CHANGES_REQUESTED` when resubmitting —
        otherwise `ERR_APPLICATION_NOT_SCREENED` (409). Applies to screening, deciding
        and resubmission, and catches for example an attempt to decide a `SUBMITTED`
        application or to screen one already `SCREENED`."

        Design: Corner/state_machines/screen_on_already_screened_application_rejected
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        partner = register_affiliate(api, network["id"], partner_type="CONTENT")
        application = file_application(
            api,
            partner["id"],
            primary_traffic_source="ORGANIC_SEARCH",
            declared_promo_methods=["EDITORIAL_CONTENT"],
        )
        first = screen_application(
            api, application["id"], headers=COMPLIANCE_ANALYST, **STRONG_SCREEN
        )
        assert_field(first, "screening_outcome", "PASS")

        response = api.screen_application(
            application["id"],
            f.screen_payload(
                domain_authority=10,
                content_originality_pct=10,
                broken_link_ratio_bps=9000,
                brand_safety_flag_count=5,
                restricted_vertical_overlap_bps=9000,
            ),
            SECOND_COMPLIANCE_ANALYST,
        )

        assert_error_response(response, ERR_APPLICATION_NOT_SCREENED, 409)

        stored = assert_object_response(
            api.get_application(application["id"], SECOND_COMPLIANCE_ANALYST)
        )
        assert_one_decimal_score(stored, "site_quality_score", 87.8)
        assert_one_decimal_score(stored, "brand_suitability_score", 100.0)
        assert_fields(
            stored,
            {
                "review_state": "SCREENED",
                "screening_outcome": "PASS",
                "screened_by_user_id": COMPLIANCE_ANALYST_ID,
                # §2.10: when a rule rejects a request "nothing is persisted".
                "version": first["version"],
            },
        )


class TestDecisionForkPreconditions:
    def test_approve_on_an_unscreened_application_is_refused(self, api):
        """A decision cannot skip the screen, even with a current applicant version guard.

        PRD §2.10 rule 19: "The application's `review_state` is `SUBMITTED` when
        screening, `SCREENED` when deciding, and `CHANGES_REQUESTED` when resubmitting —
        otherwise `ERR_APPLICATION_NOT_SCREENED` (409). Applies to screening, deciding
        and resubmission, and catches for example an attempt to decide a `SUBMITTED`
        application or to screen one already `SCREENED`."

        Design: Corner/state_machines/decide_before_screening_rejected
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        partner = register_affiliate(api, network["id"], partner_type="CONTENT")
        application = file_application(
            api,
            partner["id"],
            primary_traffic_source="ORGANIC_SEARCH",
            declared_promo_methods=["EDITORIAL_CONTENT"],
        )
        applicant_before = read_affiliate(api, partner["id"])

        response = api.decide_application(
            application["id"],
            f.decide_payload(
                "APPROVE",
                applicant_before["version"],
                decision_notes="looks fine to me",
            ),
            PARTNER_MANAGER,
        )

        assert_error_response(response, ERR_APPLICATION_NOT_SCREENED, 409)

        stored = assert_object_response(
            api.get_application(application["id"], PARTNER_MANAGER)
        )
        assert_field(stored, "review_state", "SUBMITTED")
        # §3.2: "every branch stamps `decided_by_user_id` with the deciding
        # `X-User-ID`" — a refused decision stamps nothing.
        assert_null(stored, "decided_by_user_id")

        applicant = read_affiliate(api, partner["id"])
        assert_fields(
            applicant,
            {
                "status": "PENDING_APPLICATION",
                "version": applicant_before["version"],
                # §3.5: a fresh partner "scores 4500 less its type discount, which places
                # `CONTENT` and `INFLUENCER` partners at 4500 in `MEDIUM`" — the refused
                # decision never reached the activation recompute.
                "incrementality_score_bps": 4500,
                "incrementality_tier": "MEDIUM",
            },
        )


class TestRejectBranchCascade:
    def test_reject_terminates_the_partner_and_disables_its_active_tracking_link(
        self, api
    ):
        """One rejection writes two entities: the partner terminates and its link disables.

        PRD §3.2: "Termination through a rejection is likewise a cascade: the partner
        moves to `TERMINATED`, every one of its tracking links that is still `ACTIVE` is
        disabled with a `disabled_reason` of `APPLICATION_REJECTED`, and the partner's
        `version` increments."

        Design: Corner/state_machines/reject_decision_terminates_partner_and_disables_active_tracking_links
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        partner = register_affiliate(api, network["id"], partner_type="COUPON")
        link = mint_link(
            api,
            partner["id"],
            landing_url="https://retail.example/apparel",
            sub_id="cove-apparel",
            cookie_window_days=30,
            device_graph_enabled=False,
        )
        application = file_application(
            api,
            partner["id"],
            site_url="https://cove.example",
            primary_traffic_source="COUPON_DIRECTORY",
            monthly_traffic_estimate=400000,
            declared_promo_methods=["EDITORIAL_CONTENT"],
            product_categories=["APPAREL"],
        )
        screened = screen_application(
            api,
            application["id"],
            headers=COMPLIANCE_ANALYST,
            domain_authority=72,
            content_originality_pct=88,
            broken_link_ratio_bps=450,
            brand_safety_flag_count=1,
            restricted_vertical_overlap_bps=800,
        )
        # §3.2: base 32.4 + 30.8 + 19.1 = 82.3, times the 0.65 `COUPON_DIRECTORY`
        # multiplier, less a 10-point penalty for the one brand-safety flag.
        assert_one_decimal_score(screened, "site_quality_score", 43.5)
        assert_one_decimal_score(screened, "brand_suitability_score", 80.0)
        # §3.2: "It is `FAIL` when `site_quality_score` is strictly below 45.0".
        assert_field(screened, "screening_outcome", "FAIL")
        applicant_before = read_affiliate(api, partner["id"])

        decided = assert_object_response(
            api.decide_application(
                application["id"],
                f.decide_payload(
                    "REJECT",
                    applicant_before["version"],
                    decision_notes="site quality 43.5 is below the conditional gate",
                ),
                PARTNER_MANAGER,
            )
        )

        # §3.2: "`REJECT` moves the application `SCREENED → REJECTED` and accepts any
        # `screening_outcome`."
        assert_fields(
            decided,
            {"review_state": "REJECTED", "decided_by_user_id": PARTNER_MANAGER_ID},
        )

        applicant = read_affiliate(api, partner["id"])
        assert_field(applicant, "status", "TERMINATED")
        assert_version_bumped(applicant, applicant_before["version"], "partner")
        # §3.5: a fresh `COUPON` partner sits "at 3000 in `LOW`"; the reject branch runs
        # no activation recompute, so the registration figure is what stands.
        assert_fields(
            applicant,
            {"incrementality_score_bps": 3000, "incrementality_tier": "LOW"},
        )

        disabled = assert_object_response(
            api.get_tracking_link(link["id"], PARTNER_MANAGER)
        )
        assert_fields(
            disabled,
            {"status": "DISABLED", "disabled_reason": "APPLICATION_REJECTED"},
        )
        # §3.4: "Each of those system disablings increments the link's `version` too."
        assert_version_bumped(disabled, link["version"], "tracking link")


class TestTerminalApplicationLockdown:
    def test_resubmit_on_an_approved_application_is_refused(self, api):
        """An admitted partner cannot reopen its approved application to change its story.

        PRD §2.10 rule 18: "The application's `review_state` is not one of the terminal
        values `APPROVED`, `APPROVED_WITH_CONDITIONS` or `REJECTED` — otherwise
        `ERR_APPLICATION_TERMINAL` (409). Applies to screening, deciding and resubmission,
        and doubles as the idempotency guard on a repeated decision."

        Design: Corner/state_machines/resubmit_on_approved_application_returns_409
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        partner = register_affiliate(api, network["id"], partner_type="CONTENT")
        application = file_application(
            api,
            partner["id"],
            site_url="https://beacon.example",
            primary_traffic_source="ORGANIC_SEARCH",
            declared_promo_methods=["EDITORIAL_CONTENT"],
        )
        screen_application(
            api, application["id"], headers=COMPLIANCE_ANALYST, **STRONG_SCREEN
        )
        approved = decide_application(
            api,
            application["id"],
            "APPROVE",
            partner["version"],
            decision_notes="strong editorial site",
        )
        assert_field(approved, "review_state", "APPROVED")

        response = api.resubmit_application(
            application["id"],
            f.resubmit_payload(
                site_url="https://beacon.example/v2",
                primary_traffic_source="PAID_SEARCH",
                declared_promo_methods=["TRADEMARK_PAID_SEARCH"],
            ),
            make_affiliate_partner_headers(partner["id"]),
        )

        assert_error_response(response, ERR_APPLICATION_TERMINAL, 409)

        stored = assert_object_response(
            api.get_application(application["id"], PARTNER_MANAGER)
        )
        # §3.2: resubmission "overwrites `site_url`, `primary_traffic_source` and
        # `declared_promo_methods`" — a refused resubmission overwrites nothing.
        assert_fields(
            stored,
            {
                "review_state": "APPROVED",
                "site_url": "https://beacon.example",
                "primary_traffic_source": "ORGANIC_SEARCH",
                "declared_promo_methods": ["EDITORIAL_CONTENT"],
                "revision_round_count": 0,
                "version": approved["version"],
            },
        )

        # §3.2: "It cascades the applicant partner `PENDING_APPLICATION → ACTIVE`."
        # The refusal leaves that admission standing.
        applicant = read_affiliate(api, partner["id"])
        assert_field(applicant, "status", "ACTIVE")


class TestRevisionLoopLimit:
    def test_third_request_changes_is_refused_once_two_revision_rounds_are_spent(
        self, api
    ):
        """After two revision rounds the reviewer must approve or reject outright.

        PRD §3.2: "The application must then be screened again by a `ComplianceAnalyst`,
        and the loop can run at most twice: once `revision_round_count` reaches 2 both a
        further `REQUEST_CHANGES` decision and a further resubmission are refused with
        `ERR_REVISION_LIMIT_REACHED`, forcing the reviewer to approve or reject outright."

        Design: Corner/state_machines/third_revision_round_rejected_when_revision_limit_reached
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        partner = register_affiliate(api, network["id"], partner_type="CONTENT")
        applicant_version = partner["version"]
        application = file_application(
            api,
            partner["id"],
            site_url="https://beacon.example",
            primary_traffic_source="ORGANIC_SEARCH",
            monthly_traffic_estimate=200000,
            declared_promo_methods=["EDITORIAL_CONTENT"],
            product_categories=["APPAREL"],
        )
        partner_headers = make_affiliate_partner_headers(partner["id"])

        # Round one: screen, send back for changes, resubmit unchanged in source.
        screen_application(
            api, application["id"], headers=COMPLIANCE_ANALYST, **STRONG_SCREEN
        )
        sent_back = decide_application(
            api,
            application["id"],
            "REQUEST_CHANGES",
            applicant_version,
            decision_notes="disclose the affiliate relationship on every review page",
        )
        # §3.2: "`REQUEST_CHANGES` moves the application `SCREENED → CHANGES_REQUESTED`".
        assert_field(sent_back, "review_state", "CHANGES_REQUESTED")
        resubmitted = assert_object_response(
            api.resubmit_application(
                application["id"],
                f.resubmit_payload(
                    site_url="https://beacon.example/reviews",
                    primary_traffic_source="ORGANIC_SEARCH",
                    declared_promo_methods=["EDITORIAL_CONTENT"],
                ),
                partner_headers,
            )
        )
        assert_fields(
            resubmitted, {"review_state": "SUBMITTED", "revision_round_count": 1}
        )

        # Round two: the second resubmission switches the traffic source to a newsletter.
        screen_application(
            api, application["id"], headers=COMPLIANCE_ANALYST, **STRONG_SCREEN
        )
        decide_application(
            api,
            application["id"],
            "REQUEST_CHANGES",
            applicant_version,
            decision_notes="the disclosure is still below the fold",
        )
        second_round = assert_object_response(
            api.resubmit_application(
                application["id"],
                f.resubmit_payload(
                    site_url="https://beacon.example/reviews",
                    primary_traffic_source="CONTENT_NEWSLETTER",
                    declared_promo_methods=["EDITORIAL_CONTENT", "EMAIL"],
                ),
                partner_headers,
            )
        )
        # §3.2: resubmission "increments `revision_round_count` by 1, clears
        # `site_quality_score`, `brand_suitability_score` and `screened_by_user_id` back
        # to null, resets `screening_outcome` to `NOT_SCREENED`, moves the application
        # `CHANGES_REQUESTED → SUBMITTED`".
        assert_fields(
            second_round,
            {
                "review_state": "SUBMITTED",
                "revision_round_count": 2,
                "screening_outcome": "NOT_SCREENED",
                "primary_traffic_source": "CONTENT_NEWSLETTER",
            },
        )
        assert_null(
            second_round,
            "site_quality_score",
            "brand_suitability_score",
            "screened_by_user_id",
        )

        # The third screen still succeeds — the cap binds the decision, not the screen.
        rescreened = assert_object_response(
            api.screen_application(
                application["id"], f.screen_payload(**STRONG_SCREEN), COMPLIANCE_ANALYST
            )
        )
        # §3.2: the source multiplier is "0.95 for `CONTENT_NEWSLETTER`", so the 87.8
        # base becomes 83.41 and rounds half up to one decimal place.
        assert_one_decimal_score(rescreened, "site_quality_score", 83.4)
        assert_one_decimal_score(rescreened, "brand_suitability_score", 100.0)
        assert_fields(
            rescreened, {"review_state": "SCREENED", "screening_outcome": "PASS"}
        )

        refused = api.decide_application(
            application["id"],
            f.decide_payload(
                "REQUEST_CHANGES",
                applicant_version,
                decision_notes="one more pass please",
            ),
            PARTNER_MANAGER,
        )

        assert_error_response(refused, ERR_REVISION_LIMIT_REACHED, 422)

        held = assert_object_response(
            api.get_application(application["id"], PARTNER_MANAGER)
        )
        assert_fields(
            held,
            {
                "review_state": "SCREENED",
                "revision_round_count": 2,
                # §2.10: the refused decision persisted nothing.
                "version": rescreened["version"],
            },
        )

        # §3.2: "`REJECT` moves the application `SCREENED → REJECTED` and accepts any
        # `screening_outcome`. It cascades the applicant partner
        # `PENDING_APPLICATION → TERMINATED`." The cap never traps the application.
        rejected = assert_object_response(
            api.decide_application(
                application["id"],
                f.decide_payload(
                    "REJECT",
                    applicant_version,
                    decision_notes="disclosure never fixed after two rounds",
                ),
                PARTNER_MANAGER,
            )
        )
        assert_fields(
            rejected,
            {"review_state": "REJECTED", "decided_by_user_id": PARTNER_MANAGER_ID},
        )

        applicant = read_affiliate(api, partner["id"])
        assert_field(applicant, "status", "TERMINATED")
        assert_version_bumped(applicant, applicant_version, "partner")
