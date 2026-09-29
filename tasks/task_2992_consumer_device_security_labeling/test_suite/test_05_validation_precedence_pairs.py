"""Rejection-precedence pairs on POST /labeling/label-grants.

Each pair drives one request that violates two rungs of the rejection ladder at
once and a control request that violates only the lower rung, so the ladder's
ordering is observable rather than inferred.
"""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_penalty_ledger,
    assert_status,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import DEFAULT_CLOCK

# 16 characters of [A-Z0-9-] that no minted scannable_code will ever match.
UNREGISTERED_CODE_D = "ZZ-NO-SUCH-CD-04"


def _no_grant_for(product_id):
    """Every label grant currently recorded against `product_id`."""
    items, meta = validate_paginated(
        api_client.list_label_grants(ADMIN, params={"product_id": product_id})
    )
    return items, meta


def _delinquent_sponsor_with_two_products():
    """A DELINQUENT sponsor owning one APPROVED and one UNDER_REVIEW claim.

    Six IN_STORE units of UNAUTHORIZED_DISPLAY at 4200 cents per unit with a
    first-offender multiplier of 1.00 and the IN_STORE channel factor of 1.15
    assess 28980 cents, which is at or above the 25000-cent delinquency bar.
    """
    fixtures.set_clock(DEFAULT_CLOCK)
    program = fixtures.create_program("SELF_ATTESTATION")
    sponsor = fixtures.enrol_manufacturer()
    approved = fixtures.approved_claim(program=program, sponsor=sponsor)
    under_review_product = fixtures.register_product(
        program,
        sponsor,
        model_name="Northwind Speaker S2",
        sku="NW-SPK-S2",
        retail_units_shipped=4000,
    )
    under_review = fixtures.open_assessment(program, sponsor, under_review_product)
    fixtures.attach_responses(program, sponsor, under_review)
    under_review = validate_success(
        api_client.submit_assessment(under_review["id"], sponsor.headers), 201
    )
    case = fixtures.upheld_case(
        sponsor=sponsor,
        reported_scannable_code=UNREGISTERED_CODE_D,
        violation_type="UNAUTHORIZED_DISPLAY",
        violation_line_items=[factories.violation_line("LST-STORE-D", "IN_STORE", 6)],
        reporter_note="Unregistered mark on retail cartons.",
    )
    ledger = sponsor.refresh()
    assert_status(ledger, "standing", "DELINQUENT")
    assert_penalty_ledger(ledger, outstanding=28980, paid=0, vacated=0)
    return {
        "program": program,
        "sponsor": sponsor,
        "approved": approved,
        "under_review_product": under_review_product,
        "under_review": under_review,
        "case": case,
    }


class TestReferentialBeforeFiscalOnLabelGrantRequest:
    """Priority 21 (assessment approval) outranks priority 34 (sponsor standing)."""

    def test_unapproved_assessment_outranks_the_delinquent_sponsor(self):
        """A request breaking both rungs reports the assessment rung, not the fiscal one.

        PRD: "The fiscal gate is deliberately last, so a delinquent manufacturer submitting an otherwise-invalid request still sees the earlier error first."
        Design: Difficulty/priority_pair_validation_conflict/referential_before_fiscal_on_label_grant_request
        """
        ctx = _delinquent_sponsor_with_two_products()
        response = api_client.create_label_grant(
            factories.create_label_grant_payload(
                ctx["under_review_product"]["id"], ctx["under_review"]["id"]
            ),
            ctx["sponsor"].headers,
        )
        validate_error(response, ApiErrorId.ERR_ASSESSMENT_NOT_APPROVED.value)
        assert response.status_code == 409, response.text

    def test_fiscal_gate_still_bites_on_the_approved_control_request(self):
        """The same delinquent sponsor with an APPROVED assessment gets the fiscal error.

        PRD: "The sponsoring manufacturer's `standing` is `GOOD` — otherwise `ERR_SPONSOR_DELINQUENT`."
        Design: Difficulty/priority_pair_validation_conflict/referential_before_fiscal_on_label_grant_request
        """
        ctx = _delinquent_sponsor_with_two_products()
        response = api_client.create_label_grant(
            factories.create_label_grant_payload(
                ctx["approved"].product_id, ctx["approved"].assessment_id
            ),
            ctx["sponsor"].headers,
        )
        validate_error(response, ApiErrorId.ERR_SPONSOR_DELINQUENT.value)
        assert response.status_code == 402, response.text

    def test_neither_rejected_request_leaves_a_label_grant_behind(self):
        """Both rejections are total: no grant row exists for either product.

        PRD: "When more than one condition is violated by a single request, the identifier returned is the one belonging to the highest-priority rung of the rejection ladder in §2.6, and the request has no partial effect: a rejected request writes nothing, mutates no derived quantity and advances no state machine."
        Design: Difficulty/priority_pair_validation_conflict/referential_before_fiscal_on_label_grant_request
        """
        ctx = _delinquent_sponsor_with_two_products()
        first = api_client.create_label_grant(
            factories.create_label_grant_payload(
                ctx["under_review_product"]["id"], ctx["under_review"]["id"]
            ),
            ctx["sponsor"].headers,
        )
        validate_error(first, ApiErrorId.ERR_ASSESSMENT_NOT_APPROVED.value)
        second = api_client.create_label_grant(
            factories.create_label_grant_payload(
                ctx["approved"].product_id, ctx["approved"].assessment_id
            ),
            ctx["sponsor"].headers,
        )
        validate_error(second, ApiErrorId.ERR_SPONSOR_DELINQUENT.value)

        for product_id in (ctx["under_review_product"]["id"], ctx["approved"].product_id):
            items, meta = _no_grant_for(product_id)
            assert items == [], f"a grant was persisted for {product_id}: {items}"
            assert meta["total_count"] == 0, meta

        ledger = ctx["sponsor"].refresh()
        assert_status(ledger, "standing", "DELINQUENT")
        assert_penalty_ledger(ledger, outstanding=28980, paid=0, vacated=0)


def _sponsor_with_speaker_and_excluded_implant():
    """One sponsor owning an APPROVED speaker, a bare speaker and an EXCLUDED implant.

    The implant sits in a MEDICAL_IMPLANT category whose `eligibility_status`
    is `EXCLUDED`, under a second tier, so a grant request naming it breaks the
    regulatory-scope rung as well as the pairing rung.
    """
    fixtures.set_clock(DEFAULT_CLOCK)
    program = fixtures.create_program("SELF_ATTESTATION")
    second_tier = validate_success(
        api_client.create_program_tier(factories.create_third_party_tier_payload(), ADMIN), 201
    )
    implant_category = validate_success(
        api_client.create_device_category(
            factories.create_excluded_category_payload(
                second_tier["id"],
                display_name="Connected Medical Implant",
                min_support_period_days=1095,
                exclusion_reason="Regulated medical device outside program scope",
            ),
            ADMIN,
        ),
        201,
    )
    sponsor = fixtures.enrol_manufacturer()
    approved = fixtures.approved_claim(program=program, sponsor=sponsor)
    bare_speaker = fixtures.register_product(
        program,
        sponsor,
        model_name="Northwind Speaker S2",
        sku="NW-SPK-S2",
        retail_units_shipped=4000,
    )
    implant = fixtures.register_product(
        program,
        sponsor,
        category_id=implant_category["id"],
        model_name="Northwind Cardiac Link M1",
        sku="NW-IMP-M1",
        retail_units_shipped=300,
    )
    return {
        "program": program,
        "sponsor": sponsor,
        "approved": approved,
        "bare_speaker": bare_speaker,
        "implant": implant,
        "implant_category": implant_category,
    }


class TestSafetyBeforeReferentialOnLabelGrantRequest:
    """Priority 15 (regulatory scope) outranks priority 20 (assessment pairing)."""

    def test_excluded_device_class_outranks_the_mismatched_assessment(self):
        """An out-of-scope product paired with another product's assessment reports scope.

        PRD: "Scope is checked ahead of every referential, constraint, temporal and fiscal rule."
        Design: Difficulty/priority_pair_validation_conflict/safety_before_referential_on_label_grant_request
        """
        ctx = _sponsor_with_speaker_and_excluded_implant()
        response = api_client.create_label_grant(
            factories.create_label_grant_payload(
                ctx["implant"]["id"], ctx["approved"].assessment_id
            ),
            ctx["sponsor"].headers,
        )
        validate_error(response, ApiErrorId.ERR_DEVICE_CLASS_EXCLUDED.value)
        assert response.status_code == 422, response.text

    def test_in_scope_control_request_reports_the_pairing_error_instead(self):
        """An eligible third product paired with the same assessment reports the mismatch.

        PRD: "A caller who owns both rows but pairs them wrongly gets this referential error rather than a state or fiscal one."
        Design: Difficulty/priority_pair_validation_conflict/safety_before_referential_on_label_grant_request
        """
        ctx = _sponsor_with_speaker_and_excluded_implant()
        response = api_client.create_label_grant(
            factories.create_label_grant_payload(
                ctx["bare_speaker"]["id"], ctx["approved"].assessment_id
            ),
            ctx["sponsor"].headers,
        )
        validate_error(response, ApiErrorId.ERR_ASSESSMENT_PRODUCT_MISMATCH.value)
        assert response.status_code == 422, response.text

    def test_both_rejections_share_one_status_and_write_nothing(self):
        """Only the error identifier separates the two 422s, and neither mints a grant.

        PRD: "The product's device category is in scope — otherwise `ERR_DEVICE_CLASS_EXCLUDED`."
        Design: Difficulty/priority_pair_validation_conflict/safety_before_referential_on_label_grant_request
        """
        ctx = _sponsor_with_speaker_and_excluded_implant()
        payloads = [
            (ctx["implant"]["id"], ApiErrorId.ERR_DEVICE_CLASS_EXCLUDED.value),
            (ctx["bare_speaker"]["id"], ApiErrorId.ERR_ASSESSMENT_PRODUCT_MISMATCH.value),
        ]
        seen_statuses = set()
        for product_id, expected_error in payloads:
            response = api_client.create_label_grant(
                factories.create_label_grant_payload(
                    product_id, ctx["approved"].assessment_id
                ),
                ctx["sponsor"].headers,
            )
            validate_error(response, expected_error)
            seen_statuses.add(response.status_code)
        assert seen_statuses == {422}, seen_statuses

        for product_id in (ctx["implant"]["id"], ctx["bare_speaker"]["id"]):
            items, meta = _no_grant_for(product_id)
            assert items == [], f"a grant was persisted for {product_id}: {items}"
            assert meta["total_count"] == 0, meta

        assert_status(ctx["sponsor"].refresh(), "standing", "GOOD")
