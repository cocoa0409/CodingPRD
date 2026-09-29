"""Requests whose outcome is decided by state on an entity they never name.

A label-grant request carries only a product and an assessment, yet the
sponsoring manufacturer's derived standing decides it; a display-authorization
request carries a grant identifier, yet both of that grant's status dimensions
decide it.
"""
from test_helpers import (
    ADMIN,
    PUBLISHER,
    ApiErrorId,
    api_client,
    assert_case_statuses,
    assert_grant_statuses,
    assert_money_cents,
    assert_penalty_ledger,
    assert_status,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import DEFAULT_CLOCK

UNREGISTERED_CODE_E = "ZZ-NO-SUCH-CD-05"
PENALTY_CENTS = 28980
ISSUANCE_FEE_CENTS = 40000


def _approved_claim_with_a_delinquent_sponsor():
    """An APPROVED, in-scope, spec-current claim whose sponsor is DELINQUENT.

    Six IN_STORE units of `UNAUTHORIZED_DISPLAY` at 4200 cents against a
    first-offender multiplier of 1.00 and the 1.15 IN_STORE factor assess 28980
    cents, which crosses the 25000-cent delinquency bar.
    """
    fixtures.set_clock(DEFAULT_CLOCK)
    program = fixtures.create_program("SELF_ATTESTATION")
    sponsor = fixtures.enrol_manufacturer()
    claim = fixtures.approved_claim(program=program, sponsor=sponsor)
    case = fixtures.upheld_case(
        sponsor=sponsor,
        reported_scannable_code=UNREGISTERED_CODE_E,
        violation_type="UNAUTHORIZED_DISPLAY",
        violation_line_items=[factories.violation_line("LST-STORE-E", "IN_STORE", 6)],
        reporter_note="Unregistered mark on six retail units.",
    )
    assert_case_statuses(case, "ADJUDICATED_UPHELD", "ASSESSED")
    assert_money_cents(case["penalty_cents"], PENALTY_CENTS, "penalty_cents")
    ledger = sponsor.refresh()
    assert_status(ledger, "standing", "DELINQUENT")
    return {"program": program, "sponsor": sponsor, "claim": claim, "case": case}


def _request_grant(ctx):
    return api_client.create_label_grant(
        factories.create_label_grant_payload(
            ctx["claim"].product_id, ctx["claim"].assessment_id
        ),
        ctx["sponsor"].headers,
    )


class TestGrantIssuanceRequiresManufacturerStandingGood:
    """Issuance reads a standing derived on a third entity the request never names."""

    def test_delinquent_standing_blocks_an_otherwise_perfect_request(self):
        """Every issuance condition but standing holds, and the request still fails.

        PRD: "Then `standing` is derived in this fixed order: a manufacturer whose `upheld_case_count` is 3 or more is `BARRED`; failing that, a manufacturer whose `outstanding_penalty_cents` is 25000 or more is `DELINQUENT`; every other manufacturer is `GOOD`."
        Design: Difficulty/cross_entity_state_dependency/grant_issuance_requires_manufacturer_standing_good
        """
        ctx = _approved_claim_with_a_delinquent_sponsor()
        response = _request_grant(ctx)
        validate_error(response, ApiErrorId.ERR_SPONSOR_DELINQUENT.value)
        assert response.status_code == 402, response.text

        items, meta = validate_paginated(
            api_client.list_label_grants(ADMIN, params={"product_id": ctx["claim"].product_id})
        )
        assert items == [], items
        assert meta["total_count"] == 0, meta

    def test_paying_the_penalty_moves_the_ledger_and_restores_good_standing(self):
        """The amount leaves outstanding, enters paid, and the standing recovers.

        PRD: "Payment moves `penalty_status` from `ASSESSED` to `PAID`, which moves the amount out of `outstanding_penalty_cents` and into `paid_penalty_cents` with `total_assessed_penalty_cents` unchanged, and re-derives `standing`."
        Design: Difficulty/cross_entity_state_dependency/grant_issuance_requires_manufacturer_standing_good
        """
        ctx = _approved_claim_with_a_delinquent_sponsor()
        validate_error(_request_grant(ctx), ApiErrorId.ERR_SPONSOR_DELINQUENT.value)

        paid_case = fixtures.pay_penalty(ctx["case"], ctx["sponsor"])
        assert_case_statuses(paid_case, "ADJUDICATED_UPHELD", "PAID")

        ledger = ctx["sponsor"].refresh()
        assert_penalty_ledger(ledger, outstanding=0, paid=PENALTY_CENTS, vacated=0)
        assert_money_cents(
            ledger["total_assessed_penalty_cents"], PENALTY_CENTS, "total_assessed_penalty_cents"
        )
        assert_status(ledger, "standing", "GOOD")

    def test_the_identical_request_succeeds_once_the_standing_is_good(self):
        """The byte-identical payload is accepted after the payment clears.

        PRD: "Then select the surcharge rate from that subtotal, exactly once and with no iteration: a subtotal below 50000 cents attracts no surcharge, a subtotal from 50000 cents up to but not including 150000 cents attracts 10 percent, and a subtotal of 150000 cents or more attracts 18 percent."
        Design: Difficulty/cross_entity_state_dependency/grant_issuance_requires_manufacturer_standing_good
        """
        ctx = _approved_claim_with_a_delinquent_sponsor()
        validate_error(_request_grant(ctx), ApiErrorId.ERR_SPONSOR_DELINQUENT.value)
        fixtures.pay_penalty(ctx["case"], ctx["sponsor"])

        grant = validate_success(_request_grant(ctx), 201)
        assert_grant_statuses(grant, "PENDING_REGISTRY", "DRAFT")
        assert_money_cents(grant["issuance_fee_cents"], ISSUANCE_FEE_CENTS, "issuance_fee_cents")

    def test_payment_clears_the_balance_but_not_the_upheld_case_count(self):
        """The case count survives payment; only a vacate would reduce it.

        PRD: "Note that paying does **not** reduce `upheld_case_count`, so a subject with three upheld cases stays `BARRED` no matter how much it pays; only a vacate reduces that count."
        Design: Difficulty/cross_entity_state_dependency/grant_issuance_requires_manufacturer_standing_good
        """
        ctx = _approved_claim_with_a_delinquent_sponsor()
        fixtures.pay_penalty(ctx["case"], ctx["sponsor"])
        ledger = ctx["sponsor"].refresh()
        assert ledger["upheld_case_count"] == 1, ledger["upheld_case_count"]
        assert_status(ledger, "standing", "GOOD")


DISPLAY_FROM = "2026-08-10T00:00:00Z"
DISPLAY_UNTIL = "2026-09-10T00:00:00Z"


def _grant_awaiting_publication_and_a_ready_retailer():
    """A grant at PENDING_REGISTRY/DRAFT carrying a COMPLETE registry entry."""
    fixtures.set_clock(DEFAULT_CLOCK)
    program = fixtures.create_program("SELF_ATTESTATION")
    sponsor = fixtures.enrol_manufacturer()
    claim = fixtures.approved_claim(program=program, sponsor=sponsor)
    grant = fixtures.pending_grant(claim)
    store = fixtures.register_retailer(retailer_name="Cedar Home Retail")
    assert_grant_statuses(grant.refresh(), "PENDING_REGISTRY", "DRAFT")
    return {"claim": claim, "grant": grant, "store": store}


def _display_probe(ctx):
    """The one payload every probe reuses, so only the grant's state varies."""
    return api_client.create_display_authorization(
        factories.create_display_authorization_payload(
            ctx["store"].id,
            ctx["grant"].id,
            DISPLAY_FROM,
            DISPLAY_UNTIL,
            channel="ONLINE",
        ),
        ctx["store"].headers,
    )


class TestDisplayAuthorizationRequiresPublishedActiveGrant:
    """The display gate reads both of the grant's status dimensions at once."""

    def test_pending_registry_draft_grant_cannot_be_displayed(self):
        """A grant that is neither ACTIVE nor PUBLISHED is not displayable.

        PRD: "The target grant must be simultaneously `ACTIVE` on its grant dimension and `PUBLISHED` on its publication dimension, because a retailer may not display a label whose registry information the public cannot read; failing either yields `ERR_GRANT_NOT_PUBLISHED`."
        Design: Difficulty/cross_entity_state_dependency/display_authorization_requires_published_active_grant
        """
        ctx = _grant_awaiting_publication_and_a_ready_retailer()
        response = _display_probe(ctx)
        validate_error(response, ApiErrorId.ERR_GRANT_NOT_PUBLISHED.value)
        assert response.status_code == 409, response.text

    def test_active_but_withheld_grant_is_still_not_displayable(self):
        """An ACTIVE grant whose registry entry is WITHHELD fails the same gate.

        PRD: "Critically, withholding does **not** touch `grant_status`, and it does **not** withdraw any retailer display authorization, because display gating reads `grant_status` alone."
        Design: Difficulty/cross_entity_state_dependency/display_authorization_requires_published_active_grant
        """
        ctx = _grant_awaiting_publication_and_a_ready_retailer()
        fixtures.decide_publication(ctx["grant"], "PUBLISHED", PUBLISHER)
        fixtures.decide_publication(ctx["grant"], "WITHHELD", PUBLISHER)
        withheld = ctx["grant"].refresh()
        assert_grant_statuses(withheld, "ACTIVE", "WITHHELD")

        response = _display_probe(ctx)
        validate_error(response, ApiErrorId.ERR_GRANT_NOT_PUBLISHED.value)
        assert response.status_code == 409, response.text

    def test_active_and_published_grant_is_displayable(self):
        """Restoring publication makes the identical request succeed.

        PRD: "First, `active_display_count` is recounted as the number of that retailer's display authorizations whose `status` is `AUTHORIZED`; rows in `WITHDRAWN` or `EXPIRED` are excluded."
        Design: Difficulty/cross_entity_state_dependency/display_authorization_requires_published_active_grant
        """
        ctx = _grant_awaiting_publication_and_a_ready_retailer()
        fixtures.decide_publication(ctx["grant"], "PUBLISHED", PUBLISHER)
        assert_grant_statuses(ctx["grant"].refresh(), "ACTIVE", "PUBLISHED")

        authorization = validate_success(_display_probe(ctx), 201)
        assert_status(authorization, "status", "AUTHORIZED")

        retailer = ctx["store"].refresh()
        assert retailer["active_display_count"] == 1, retailer["active_display_count"]
        assert_status(retailer, "participation_tier", "BASELINE")

    def test_the_two_rejected_probes_persist_no_authorization_row(self):
        """Three identical requests across three grant states leave exactly one row.

        PRD: "The target grant must be simultaneously `ACTIVE` on its grant dimension and `PUBLISHED` on its publication dimension, because a retailer may not display a label whose registry information the public cannot read; failing either yields `ERR_GRANT_NOT_PUBLISHED`."
        Design: Difficulty/cross_entity_state_dependency/display_authorization_requires_published_active_grant
        """
        ctx = _grant_awaiting_publication_and_a_ready_retailer()
        validate_error(_display_probe(ctx), ApiErrorId.ERR_GRANT_NOT_PUBLISHED.value)

        fixtures.decide_publication(ctx["grant"], "PUBLISHED", PUBLISHER)
        fixtures.decide_publication(ctx["grant"], "WITHHELD", PUBLISHER)
        validate_error(_display_probe(ctx), ApiErrorId.ERR_GRANT_NOT_PUBLISHED.value)

        fixtures.decide_publication(ctx["grant"], "PUBLISHED", PUBLISHER)
        validate_success(_display_probe(ctx), 201)

        items, meta = validate_paginated(
            api_client.list_display_authorizations(
                ADMIN,
                params={
                    "retailer_id": ctx["store"].id,
                    "label_grant_id": ctx["grant"].id,
                    "channel": "ONLINE",
                },
            )
        )
        assert len(items) == 1, items
        assert meta["total_count"] == 1, meta
        assert_status(items[0], "status", "AUTHORIZED")
