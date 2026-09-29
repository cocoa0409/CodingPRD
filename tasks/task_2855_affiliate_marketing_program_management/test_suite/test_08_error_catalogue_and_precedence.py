"""The typed error catalogue and the order in which rejection rules fire.

Every route that resolves an identifier answers with that identifier's own
not-found code, and where two rules could reject the same request the
lower-numbered rule of the global evaluation order decides the response.
"""

import pytest
from prd_bench_local_runner.testing import NON_EXISTENT_UUID

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ADJUSTMENT_EXCEEDS_ORDER,
    ERR_AFFILIATE_NOT_FOUND,
    ERR_APPLICATION_NOT_FOUND,
    ERR_BATCH_NOT_FOUND,
    ERR_BRAND_SUITABILITY_VIOLATION,
    ERR_CASE_NOT_FOUND,
    ERR_CONVERSION_NOT_ATTRIBUTED,
    ERR_CONVERSION_NOT_FOUND,
    ERR_LINE_NOT_FOUND,
    ERR_NETWORK_NOT_FOUND,
    ERR_NO_ACTIVE_COMMISSION_POLICY,
    ERR_POLICY_NOT_FOUND,
    ERR_SCREENING_NOT_PASSED,
    ERR_TAX_DOCUMENT_INVALID,
    ERR_TAX_DOCUMENT_NOT_FOUND,
    ERR_TRACKING_LINK_NOT_FOUND,
    TYPED_NOT_FOUND_ERRORS,
)
from test_helpers.assertions import (
    assert_bps,
    assert_cents,
    assert_error_response,
    assert_field,
    assert_fields,
    assert_object_response,
    assert_one_decimal_score,
    assert_total_count,
    assert_version_unchanged,
)
from test_helpers.fixtures import (
    attributed_order,
    build_program,
    create_conversion,
    create_network,
    first_line,
    generate_batch,
    ingest_click,
    pin_clock,
    read_affiliate,
    read_batch,
    read_conversion,
    read_line,
    screened_partner,
    valid_tax_document,
)
from test_helpers.test_users import (
    ANONYMOUS,
    COMPLIANCE_ANALYST,
    FINANCE_ANALYST,
    FINANCE_CONTROLLER,
    PARTNER_MANAGER,
    PROGRAM_ADMIN,
    TRACKING_INGESTOR,
)

CLOCK = f.JUL_05_00_00
SETTLEMENT_CLOCK = f.AUG_05_00_00

# One probe per typed 404, keyed by the error id the addressed route must answer.
# The inline quote beside each entry is the rule of PRD §2.10 that fixes it.
_TYPED_NOT_FOUND_PROBES = {
    # §2.10: "A partner identifier resolves to an existing partner — otherwise
    # `ERR_AFFILIATE_NOT_FOUND` (404)."
    ERR_AFFILIATE_NOT_FOUND: (
        "single_partner_read",
        lambda api: api.get_affiliate(NON_EXISTENT_UUID, PROGRAM_ADMIN),
    ),
    # §2.10: "An application identifier resolves to an existing application —
    # otherwise `ERR_APPLICATION_NOT_FOUND` (404)."
    ERR_APPLICATION_NOT_FOUND: (
        "single_application_read",
        lambda api: api.get_application(NON_EXISTENT_UUID, PARTNER_MANAGER),
    ),
    # §2.10: "A rate-card identifier resolves to an existing commission policy —
    # otherwise `ERR_POLICY_NOT_FOUND` (404)."
    ERR_POLICY_NOT_FOUND: (
        "single_rate_card_read",
        lambda api: api.get_commission_policy(NON_EXISTENT_UUID, PROGRAM_ADMIN),
    ),
    # §2.10: "A tracking-link identifier resolves to an existing link — otherwise
    # `ERR_TRACKING_LINK_NOT_FOUND` (404)."
    ERR_TRACKING_LINK_NOT_FOUND: (
        "single_tracking_link_read",
        lambda api: api.get_tracking_link(NON_EXISTENT_UUID, TRACKING_INGESTOR),
    ),
    # §2.10: "An order identifier resolves to an existing conversion — otherwise
    # `ERR_CONVERSION_NOT_FOUND` (404)."
    ERR_CONVERSION_NOT_FOUND: (
        "single_order_read",
        lambda api: api.get_conversion(NON_EXISTENT_UUID, TRACKING_INGESTOR),
    ),
    # §2.10: "A case identifier resolves to an existing violation case — otherwise
    # `ERR_CASE_NOT_FOUND` (404)."
    ERR_CASE_NOT_FOUND: (
        "single_violation_case_read",
        lambda api: api.get_violation_case(NON_EXISTENT_UUID, COMPLIANCE_ANALYST),
    ),
    # §2.10: "A batch identifier resolves to an existing payout batch — otherwise
    # `ERR_BATCH_NOT_FOUND` (404)."
    ERR_BATCH_NOT_FOUND: (
        "single_payout_batch_read",
        lambda api: api.get_payout_batch(NON_EXISTENT_UUID, FINANCE_ANALYST),
    ),
    # §2.10: "A line identifier resolves to an existing payout line — otherwise
    # `ERR_LINE_NOT_FOUND` (404)."
    ERR_LINE_NOT_FOUND: (
        "single_payout_line_read",
        lambda api: api.get_payout_line(NON_EXISTENT_UUID, FINANCE_ANALYST),
    ),
    # §2.10: "A `network_id` resolves to an existing network — otherwise
    # `ERR_NETWORK_NOT_FOUND` (404). Applies to the single-network read, partner
    # registration, and payout-batch creation."
    ERR_NETWORK_NOT_FOUND: (
        "unknown_network_on_registration",
        lambda api: api.create_affiliate(
            f.affiliate_payload(NON_EXISTENT_UUID), ANONYMOUS
        ),
    ),
    # §2.10: "A tax-document identifier resolves to an existing document —
    # otherwise `ERR_TAX_DOCUMENT_NOT_FOUND` (404)."
    ERR_TAX_DOCUMENT_NOT_FOUND: (
        "tax_document_verification",
        lambda api: api.verify_tax_document(
            NON_EXISTENT_UUID,
            f.verify_tax_document_payload("VALID"),
            FINANCE_CONTROLLER,
        ),
    ),
}

_TYPED_NOT_FOUND_CASES = [
    pytest.param(
        error_id,
        _TYPED_NOT_FOUND_PROBES[error_id][1],
        id=_TYPED_NOT_FOUND_PROBES[error_id][0],
    )
    for error_id in TYPED_NOT_FOUND_ERRORS
]


class TestTypedNotFoundCatalogue:
    @pytest.mark.parametrize("error_id,probe", _TYPED_NOT_FOUND_CASES)
    def test_unknown_identifier_answers_its_own_not_found_code(
        self, api, error_id, probe
    ):
        """Each identifier-resolving route fed a fabricated id answers its own 404.

        PRD §5: "Every failed request answers with the error envelope of §2.2,
        carrying the `error_id` from the table below in `data.error_id` and the HTTP
        status shown."

        Design: Corner/errors/unknown_ids_on_every_typed_route_return_their_own_not_found_code
        """
        pin_clock(api, CLOCK)

        response = probe(api)

        # assert_error_response cross-checks the §5 status for this error id, which
        # is 404 for each of the ten typed not-found codes.
        assert_error_response(response, error_id, 404)

    def test_registration_naming_an_unknown_network_creates_no_partner(self, api):
        """A registration that names a network nobody registered persists nothing.

        PRD §2.5: "A partner registration naming an unknown network fails with
        `ERR_NETWORK_NOT_FOUND`, and one naming an unknown `parent_affiliate_id`
        fails with `ERR_AFFILIATE_NOT_FOUND`."

        Design: Corner/errors/unknown_ids_on_every_typed_route_return_their_own_not_found_code
        """
        pin_clock(api, CLOCK)

        response = api.create_affiliate(
            f.affiliate_payload(
                NON_EXISTENT_UUID,
                legal_name="Ghost Network Partner LLC",
                contact_email="ghost@example.com",
            ),
            ANONYMOUS,
        )

        # §2.5 puts the body-level owner reference on the same footing as a path id,
        # so the answer is the network's own 404 and not a request-shape complaint.
        assert_error_response(response, ERR_NETWORK_NOT_FOUND, 404)

        # §2.10: "no later rule is evaluated and nothing is persisted."
        assert_total_count(api.list_affiliates(PROGRAM_ADMIN), 0)


# Screening inputs that leave the brand gate satisfied but the outcome a FAIL:
# §3.2 site quality on a COUPON_DIRECTORY source is
# (0.45*72 + 0.35*88 + 0.20*(100 - 450/100)) * 0.65 - 10 = 43.495 -> 43.5, and
# §3.2 brand suitability is 100 - 800/100 - 12*1 = 80.0.
_BRAND_OK_SCREEN = {
    "domain_authority": 72,
    "content_originality_pct": 88,
    "broken_link_ratio_bps": 450,
    "brand_safety_flag_count": 1,
    "restricted_vertical_overlap_bps": 800,
}
_BRAND_OK_SITE_QUALITY = 43.5
_BRAND_OK_BRAND_SUITABILITY = 80.0

# The same measurements with five brand-safety flags on an ORGANIC_SEARCH source:
# site quality is 0.45*72 + 0.35*88 + 0.20*95.5 - min(30, 50) = 52.3, and brand
# suitability is 100 - 800/100 - 12*5 = 32.0, which is below the 70.0 floor.
_BRAND_FAIL_SCREEN = dict(_BRAND_OK_SCREEN, brand_safety_flag_count=5)
_BRAND_FAIL_SITE_QUALITY = 52.3
_BRAND_FAIL_BRAND_SUITABILITY = 32.0


class TestDecisionGatePrecedence:
    """The brand-safety veto on a decision outranks the screening-outcome gate."""

    @staticmethod
    def _screened(api, traffic_source, screen_kwargs):
        """One network and one PENDING_APPLICATION partner with a SCREENED application."""
        pin_clock(api, CLOCK)
        network = create_network(api)
        return screened_partner(
            api,
            network["id"],
            application_kwargs={"primary_traffic_source": traffic_source},
            screen_kwargs=screen_kwargs,
        )

    def test_approve_on_failed_outcome_with_passing_brand_score_reports_outcome_gate(
        self, api
    ):
        """An APPROVE on a FAIL outcome whose brand score clears 70.0 cites the outcome gate.

        PRD §3.2: "A decision whose branch is incompatible with the screening outcome
        is rejected — an `APPROVE` on anything other than `PASS`, an
        `APPROVE_WITH_CONDITIONS` on a `FAIL` outcome, and an
        `APPROVE_WITH_CONDITIONS` carrying an empty `conditional_requirements` array
        all answer `ERR_SCREENING_NOT_PASSED`."

        Design: Corner/errors/brand_suitability_gate_outranks_screening_outcome_gate_on_decide
        """
        screened = self._screened(api, "COUPON_DIRECTORY", _BRAND_OK_SCREEN)
        application = screened["application"]

        assert_one_decimal_score(
            application, "site_quality_score", _BRAND_OK_SITE_QUALITY
        )
        assert_one_decimal_score(
            application, "brand_suitability_score", _BRAND_OK_BRAND_SUITABILITY
        )
        # §3.2: "It is `FAIL` when `site_quality_score` is strictly below 45.0".
        assert_field(application, "screening_outcome", "FAIL")

        affiliate = read_affiliate(api, screened["affiliate_id"])
        response = api.decide_application(
            screened["application_id"],
            f.decide_payload("APPROVE", affiliate["version"], decision_notes="let them in anyway"),
            PARTNER_MANAGER,
        )

        assert_error_response(response, ERR_SCREENING_NOT_PASSED, 422)

        after_application = assert_object_response(
            api.get_application(screened["application_id"], PARTNER_MANAGER)
        )
        assert_field(after_application, "review_state", "SCREENED")
        assert_version_unchanged(
            after_application, application["version"], "application"
        )
        after_affiliate = read_affiliate(api, screened["affiliate_id"])
        assert_field(after_affiliate, "status", "PENDING_APPLICATION")
        assert_version_unchanged(after_affiliate, affiliate["version"], "partner")

    def test_approve_with_conditions_on_failed_outcome_reports_outcome_gate(self, api):
        """A conditional approval cannot buy off a FAIL outcome, however many conditions.

        PRD §3.2: "A decision whose branch is incompatible with the screening outcome
        is rejected — an `APPROVE` on anything other than `PASS`, an
        `APPROVE_WITH_CONDITIONS` on a `FAIL` outcome, and an
        `APPROVE_WITH_CONDITIONS` carrying an empty `conditional_requirements` array
        all answer `ERR_SCREENING_NOT_PASSED`."

        Design: Corner/errors/brand_suitability_gate_outranks_screening_outcome_gate_on_decide
        """
        screened = self._screened(api, "COUPON_DIRECTORY", _BRAND_OK_SCREEN)
        application = screened["application"]
        assert_field(application, "screening_outcome", "FAIL")

        affiliate = read_affiliate(api, screened["affiliate_id"])
        response = api.decide_application(
            screened["application_id"],
            f.decide_payload(
                "APPROVE_WITH_CONDITIONS",
                affiliate["version"],
                decision_notes="conditional entry",
                conditional_requirements=["no paid search", "monthly content audit"],
            ),
            PARTNER_MANAGER,
        )

        assert_error_response(response, ERR_SCREENING_NOT_PASSED, 422)

        after_application = assert_object_response(
            api.get_application(screened["application_id"], PARTNER_MANAGER)
        )
        assert_field(after_application, "review_state", "SCREENED")
        assert_version_unchanged(
            after_application, application["version"], "application"
        )
        after_affiliate = read_affiliate(api, screened["affiliate_id"])
        assert_field(after_affiliate, "status", "PENDING_APPLICATION")
        assert_version_unchanged(after_affiliate, affiliate["version"], "partner")

    def test_approve_below_brand_floor_reports_brand_veto_before_outcome_gate(self, api):
        """An APPROVE that breaks both the brand floor and the outcome gate cites the brand veto.

        PRD §2.10: "The application's `brand_suitability_score` is at least 70.0 —
        otherwise `ERR_BRAND_SUITABILITY_VIOLATION` (422). Applies to deciding an
        application, and acts as a brand-safety veto: an application below that floor
        can never be approved, not even with conditions."

        Design: Corner/errors/brand_suitability_gate_outranks_screening_outcome_gate_on_decide
        """
        screened = self._screened(api, "ORGANIC_SEARCH", _BRAND_FAIL_SCREEN)
        application = screened["application"]

        assert_one_decimal_score(
            application, "site_quality_score", _BRAND_FAIL_SITE_QUALITY
        )
        assert_one_decimal_score(
            application, "brand_suitability_score", _BRAND_FAIL_BRAND_SUITABILITY
        )
        # §3.2: "It is `FAIL` when `site_quality_score` is strictly below 45.0, or when
        # `brand_suitability_score` is strictly below 70.0 regardless of site quality."
        # So this APPROVE breaks the brand floor and the outcome gate at once.
        assert_field(application, "screening_outcome", "FAIL")

        affiliate = read_affiliate(api, screened["affiliate_id"])
        response = api.decide_application(
            screened["application_id"],
            f.decide_payload("APPROVE", affiliate["version"], decision_notes="let them in anyway"),
            PARTNER_MANAGER,
        )

        # §2.10: "Rules are evaluated in strictly ascending order of the numbers
        # below, and the **first** rule whose condition fails decides the response".
        assert_error_response(response, ERR_BRAND_SUITABILITY_VIOLATION, 422)

        after_application = assert_object_response(
            api.get_application(screened["application_id"], PARTNER_MANAGER)
        )
        assert_field(after_application, "review_state", "SCREENED")
        assert_version_unchanged(
            after_application, application["version"], "application"
        )
        after_affiliate = read_affiliate(api, screened["affiliate_id"])
        assert_field(after_affiliate, "status", "PENDING_APPLICATION")
        assert_version_unchanged(after_affiliate, affiliate["version"], "partner")


class TestAttributionAndAdjustmentGates:
    """The pricing gate on attribution and the credit-dimension gate on adjustment."""

    def test_attribute_without_a_covering_rate_card_writes_nothing(self, api):
        """An order no active rate card covers fails pricing and leaves no trace behind.

        PRD §3.5: "When the candidate set is empty the whole run fails with
        `ERR_NO_ACTIVE_COMMISSION_POLICY` and **nothing** is written: no audit rows,
        no ledger entry, no version bump."

        Design: Corner/errors/attribute_without_matching_rate_card_and_adjustment_before_attribution_rejected
        """
        # The only ACTIVE card is APPAREL scoped to COUPON, so nothing covers the
        # CONTENT partner that wins this APPAREL order.
        program = build_program(api, setup_clock=CLOCK, policy_scope=["COUPON"])
        ingest_click(
            api, program["link_id"], occurred_at=f.JUL_04_10_00, device_id="D1"
        )
        conversion = create_conversion(
            api,
            order_total_cents=100000,
            product_category="APPAREL",
            is_new_customer=False,
            placed_at=f.JUL_04_12_00,
            device_id="D1",
        )
        # §3.5: "Order creation also computes `candidate_click_count` from the clicks
        # already on file", and that one organic click is inside the cookie window.
        assert_field(conversion, "candidate_click_count", 1)

        response = api.attribute_conversion(
            conversion["id"],
            f.attribute_payload(conversion["version"]),
            TRACKING_INGESTOR,
        )

        assert_error_response(response, ERR_NO_ACTIVE_COMMISSION_POLICY, 422)

        after = read_conversion(api, conversion["id"])
        assert_fields(
            after,
            {
                "attribution_status": "UNATTRIBUTED",
                "validation_status": "PENDING_VALIDATION",
                "attributed_affiliate_id": None,
                "attributed_click_id": None,
                "commission_policy_id": None,
            },
        )
        assert_cents(after, "gross_commission_cents", 0)
        assert_cents(after, "payable_commission_cents", 0)
        assert_version_unchanged(after, conversion["version"], "order")
        assert_total_count(
            api.list_attribution_decisions(conversion["id"], FINANCE_ANALYST), 0
        )
        assert_total_count(
            api.list_ledger_entries(
                FINANCE_ANALYST, {"conversion_id": conversion["id"]}
            ),
            0,
        )

    def test_order_adjustment_before_attribution_rejected(self, api):
        """A return against an order that never won credit has no commission to unwind.

        PRD §2.10: "The order's `attribution_status` is not `UNATTRIBUTED`, and its
        `validation_status` is neither `REVERSED` nor `CLAWED_BACK` — otherwise
        `ERR_CONVERSION_NOT_ATTRIBUTED` (409). Applies to order adjustment: there is
        no commission to unwind on an unattributed order, and an order already fully
        reversed or clawed back is terminal on the money dimension."

        Design: Corner/errors/attribute_without_matching_rate_card_and_adjustment_before_attribution_rejected
        """
        pin_clock(api, CLOCK)
        conversion = create_conversion(
            api, order_total_cents=100000, placed_at=f.JUL_04_12_00
        )
        assert_field(conversion, "attribution_status", "UNATTRIBUTED")

        response = api.adjust_order(
            conversion["id"],
            f.order_adjustment_payload(
                "PARTIAL_RETURN", 1000, occurred_at="2026-07-05T01:00:00.000Z"
            ),
            FINANCE_ANALYST,
        )

        assert_error_response(response, ERR_CONVERSION_NOT_ATTRIBUTED, 409)

        after = read_conversion(api, conversion["id"])
        assert_fields(
            after,
            {
                "attribution_status": "UNATTRIBUTED",
                "validation_status": "PENDING_VALIDATION",
            },
        )
        assert_cents(after, "returned_amount_cents", 0)
        assert_cents(after, "clawed_back_cents", 0)
        assert_version_unchanged(after, conversion["version"], "order")

    def test_excess_return_on_unattributed_order_reports_the_credit_gate(self, api):
        """A return that is both premature and larger than the order cites the earlier rule.

        PRD §2.10: "Rules are evaluated in strictly ascending order of the numbers
        below, and the **first** rule whose condition fails decides the response; no
        later rule is evaluated and nothing is persisted. This ordering is observable
        and is part of the contract — a request that violates three rules at once must
        answer with the lowest-numbered one."

        Design: Corner/errors/attribute_without_matching_rate_card_and_adjustment_before_attribution_rejected
        """
        pin_clock(api, CLOCK)
        conversion = create_conversion(
            api, order_total_cents=5000, placed_at=f.JUL_04_12_00
        )

        # 5001 cents against a 5000-cent order breaks the cumulative-return ceiling
        # too, but the credit-dimension gate is the earlier of the two rules.
        response = api.adjust_order(
            conversion["id"],
            f.order_adjustment_payload(
                "PARTIAL_RETURN", 5001, occurred_at="2026-07-05T01:00:00.000Z"
            ),
            FINANCE_ANALYST,
        )

        assert_error_response(response, ERR_CONVERSION_NOT_ATTRIBUTED, 409)

        after = read_conversion(api, conversion["id"])
        assert_cents(after, "returned_amount_cents", 0)
        assert_cents(after, "clawed_back_cents", 0)
        assert_version_unchanged(after, conversion["version"], "order")


class TestAdjustmentCeilingAndHoldRelease:
    """The cumulative-return ceiling, and the tax form a hold release insists on."""

    @staticmethod
    def _held_line(api):
        """A 5,000-cent attributed order settled into one below-minimum payout line."""
        program = build_program(api, setup_clock=CLOCK, fee_bps=0, flat_fee_cents=0)
        order = attributed_order(
            api,
            program,
            order_total_cents=5000,
            is_new_customer=False,
            click_at=f.JUL_04_10_00,
            placed_at=f.JUL_04_12_00,
        )
        pin_clock(api, SETTLEMENT_CLOCK)
        batch = generate_batch(api, program["network_id"])
        line = first_line(api, batch["id"])
        return program, order, batch, line

    @staticmethod
    def _assert_backup_withheld_line(line):
        """§3.9 line math for a partner with no tax form at all: 200 gross, 152 net."""
        # §3.9: "The line's `withholding_bps` comes from the partner's most recent tax
        # document ordered by `created_at` descending: when that document's `status`
        # is `VALID` the line uses its `treaty_withholding_bps`, and in every other
        # case — no document at all, `PENDING`, `EXPIRED` or `REJECTED` — the line
        # uses the default backup withholding rate of 2400 basis points."
        assert_cents(line, "gross_cents", 200)
        assert_cents(line, "clawback_cents", 0)
        assert_cents(line, "net_before_fees_cents", 200)
        assert_cents(line, "network_fee_cents", 0)
        assert_bps(line, "withholding_bps", 2400)
        assert_cents(line, "withholding_cents", 48)
        assert_cents(line, "net_cents", 152)
        # §3.9: "the boundary is inclusive on the pay side, so exactly 2500 stays
        # `INCLUDED` and 2499 holds."
        assert_fields(
            line,
            {"state": "HELD_BELOW_MINIMUM", "hold_reason": "BELOW_MINIMUM_PAYOUT"},
        )

    def test_return_exceeding_the_order_total_rejected(self, api):
        """A return of more merchandise than the order held is refused before any clawback.

        PRD §2.10: "The order's accumulated returned amount plus the amount on this
        request is at most the order total — otherwise `ERR_ADJUSTMENT_EXCEEDS_ORDER`
        (422). Applies to order adjustment."

        Design: Corner/errors/adjustment_exceeding_order_and_release_without_valid_tax_form_rejected
        """
        program = build_program(api, setup_clock=CLOCK, fee_bps=0, flat_fee_cents=0)
        order = attributed_order(
            api,
            program,
            order_total_cents=5000,
            is_new_customer=False,
            click_at=f.JUL_04_10_00,
            placed_at=f.JUL_04_12_00,
        )
        conversion = order["conversion"]
        # The order carries credit, so the credit-dimension gate is satisfied and the
        # cumulative-return ceiling is the rule left to decide this request.
        assert_field(conversion, "attribution_status", "AFFILIATE_ATTRIBUTED")

        pin_clock(api, SETTLEMENT_CLOCK)
        response = api.adjust_order(
            order["conversion_id"],
            f.order_adjustment_payload("PARTIAL_RETURN", 5001),
            FINANCE_ANALYST,
        )

        assert_error_response(response, ERR_ADJUSTMENT_EXCEEDS_ORDER, 422)

        after = read_conversion(api, order["conversion_id"])
        assert_cents(after, "returned_amount_cents", 0)
        assert_cents(after, "clawed_back_cents", 0)
        assert_field(after, "validation_status", "PENDING_VALIDATION")
        assert_version_unchanged(after, conversion["version"], "order")

    def test_release_hold_without_a_valid_tax_form_rejected(self, api):
        """A below-minimum hold cannot be released while no tax form is on file.

        PRD §2.10: "The partner has a tax document whose `status` is `VALID` and whose
        `expires_on` is strictly after the logical clock — otherwise
        `ERR_TAX_DOCUMENT_INVALID` (422). Applies to hold release, and is deliberately
        ranked below the fraud-hold check so that a fraud-held line on a partner with
        an expired form reports the fraud hold."

        Design: Corner/errors/adjustment_exceeding_order_and_release_without_valid_tax_form_rejected
        """
        program, _order, _batch, line = self._held_line(api)
        self._assert_backup_withheld_line(line)
        assert_field(
            read_affiliate(api, program["affiliate_id"]), "tax_document_status", "NONE"
        )

        response = api.release_hold(
            line["id"],
            f.release_hold_payload("partner asked for settlement of the residual"),
            FINANCE_CONTROLLER,
        )

        assert_error_response(response, ERR_TAX_DOCUMENT_INVALID, 422)

        after = read_line(api, line["id"])
        assert_fields(
            after,
            {"state": "HELD_BELOW_MINIMUM", "hold_reason": "BELOW_MINIMUM_PAYOUT"},
        )
        assert_bps(after, "withholding_bps", 2400)
        assert_version_unchanged(after, line["version"], "payout line")

    def test_release_hold_after_a_verified_w9_recomputes_the_line(self, api):
        """Once a W9 is verified the same release succeeds and the withholding falls away.

        PRD §3.9: "Release additionally requires the partner to hold a tax document
        that is `VALID` and whose `expires_on` is strictly after the logical clock. On
        success the line returns to `INCLUDED`, its `hold_reason` clears to null,
        `released_by_user_id` records the controller, the line is recomputed, and the
        batch's `network_fee_cents`, `withholding_cents` and `net_payable_cents` are
        recomputed with the batch's `version` incremented while its `state` stays
        exactly as it was."

        Design: Corner/errors/adjustment_exceeding_order_and_release_without_valid_tax_form_rejected
        """
        program, _order, batch, line = self._held_line(api)
        self._assert_backup_withheld_line(line)

        document = valid_tax_document(
            api,
            program["affiliate_id"],
            form_type="W9",
            treaty_withholding_bps=0,
            expires_on=f.TAX_EXPIRY_2027,
        )
        assert_field(document, "status", "VALID")
        assert_field(
            read_affiliate(api, program["affiliate_id"]), "tax_document_status", "VALID"
        )

        released = assert_object_response(
            api.release_hold(
                line["id"],
                f.release_hold_payload("W9 on file, releasing the residual"),
                FINANCE_CONTROLLER,
            )
        )

        assert_fields(released, {"state": "INCLUDED", "hold_reason": None})
        # §3.9: the recomputed line reads `withholding_bps` off the now-`VALID` W9,
        # whose `treaty_withholding_bps` is 0, so all 200 cents become payable.
        assert_bps(released, "withholding_bps", 0)
        assert_cents(released, "withholding_cents", 0)
        assert_cents(released, "net_cents", 200)

        after_batch = read_batch(api, batch["id"])
        assert_cents(after_batch, "withholding_cents", 0)
        assert_cents(after_batch, "net_payable_cents", 200)
        assert_field(after_batch, "state", "DRAFT")
