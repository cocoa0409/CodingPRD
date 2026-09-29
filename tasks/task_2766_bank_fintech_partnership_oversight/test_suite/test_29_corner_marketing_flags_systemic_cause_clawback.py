"""Corner cases of the business-model-conditional risk flags, the systemic
root-cause tie-break and the term-by-term clawback restoration."""
from test_helpers import (
    CO,
    PO,
    ApiErrorId,
    api_client,
    assert_same_instant,
    assign_root_cause,
    batch_ledger_entries,
    clawback_batch,
    close_cycle,
    create_agreement_payload,
    create_partner,
    dispose_complaint,
    file_complaint,
    file_marketing_review,
    fund_batch,
    get_success_data,
    oversight_summary,
    parse_instant,
    pass_diligence,
    read_batch,
    read_custody_account,
    read_partner,
    setup_contracted_partner,
    setup_live_partner,
    setup_matched_batch,
    set_clock,
    validate_error,
)

BARE_DISCLOSURE = {
    "material_type": "DISCLOSURE",
    "placement_channel": "PARTNER_SITE",
    "disclosure_elements": ["BANK_NAME", "FEE_SCHEDULE"],
    "apr_disclosed": False,
    "fdic_signage_correct": True,
    "effective_from": "2026-09-01T00:00:00Z",
    "effective_until": "2026-09-10T00:00:00Z",
}


def _drafted_agreement(legal_name, business_model):
    partner = create_partner(legal_name=legal_name, business_model=business_model)
    _review, partner = pass_diligence(partner)
    agreement = get_success_data(
        api_client.create_agreement(
            create_agreement_payload(partner["id"], partner["version"]), PO
        )
    )
    assert agreement["status"] == "DRAFT"
    return partner, agreement


class TestMarketingRiskFlags:
    def test_the_flags_are_business_model_conditional_and_emitted_in_declaration_order(self):
        """The emitted array is always ordered `MISSING_APR`, then `MISSING_FDIC_SIGNAGE`, then
        `MISSING_DISPUTE_RIGHTS` — the fixed declaration order, never the order in which the flags
        happened to be discovered. An empty array is the only value that permits an approval.

        Design: Corner/calculations/marketing_risk_flags_are_business_model_conditional_and_emitted_in_the_fixed_order
        """
        lender, lender_agreement = _drafted_agreement("Pinehurst Lending Inc", "LENDING")
        issuer, issuer_agreement = _drafted_agreement("Copperline Cards Inc", "CARD_ISSUING")

        lending_filing = file_marketing_review(
            lender["id"], lender_agreement["id"], **BARE_DISCLOSURE
        )
        assert lending_filing["status"] == "SUBMITTED", "there is no draft stage"
        assert lending_filing["review_round"] == 1
        assert lending_filing["change_requests"] == []
        assert lending_filing["decided_by_user_id"] is None
        assert lending_filing["risk_flags"] == ["MISSING_APR", "MISSING_DISPUTE_RIGHTS"], (
            f"declaration order, not discovery or alphabetical order, got "
            f"{lending_filing['risk_flags']}"
        )

        issuing_filing = file_marketing_review(
            issuer["id"], issuer_agreement["id"], **BARE_DISCLOSURE
        )
        assert issuing_filing["risk_flags"] == ["MISSING_DISPUTE_RIGHTS"], (
            "a CARD_ISSUING partner fires neither the APR nor the FDIC predicate, got "
            f"{issuing_filing['risk_flags']}"
        )

        refused = api_client.decide_marketing_review(
            lending_filing["id"], {"decision": "APPROVE"}, CO
        )
        validate_error(refused, ApiErrorId.ERR_DISCLOSURE_INCOMPLETE, 422)
        untouched = get_success_data(api_client.get_marketing_review(lending_filing["id"], PO))
        assert untouched["status"] == "SUBMITTED"

        advert = dict(BARE_DISCLOSURE, material_type="AD")
        clean = file_marketing_review(issuer["id"], issuer_agreement["id"], **advert)
        assert clean["risk_flags"] == [], (
            "the dispute-rights predicate only applies to DISCLOSURE material"
        )
        approved = get_success_data(
            api_client.decide_marketing_review(clean["id"], {"decision": "APPROVE"}, CO)
        )
        assert approved["status"] == "APPROVED"
        assert approved["decided_by_user_id"] == "co_1"


class TestSystemicRootCauseTieBreak:
    def test_a_count_tie_is_broken_by_the_earliest_created_at_and_not_by_code_order(self):
        """Otherwise the pool is grouped by `root_cause_code` and the codes tied for the highest
        count are the candidates. Ties are broken first by whichever candidate code has the earliest
        `created_at` among its own qualifying complaints, and then — if two candidates' earliest
        `created_at` values are identical — by the lexicographically smallest code.

        Design: Corner/calculations/systemic_root_cause_breaks_a_count_tie_on_earliest_created_at_not_lexicographic_order
        """
        ctx = setup_contracted_partner(
            partner_overrides={
                "legal_name": "Ashgrove Wallet Inc",
                "end_user_account_count": 100_000,
            }
        )
        partner_id = ctx["partner"]["id"]

        # created_at is stamped from the logical clock, and no complaint may be received later
        # than that clock, so the clock is walked forward one intake at a time. That is what gives
        # the two diagnosed complaints distinct created_at values for the tie-break to read.
        set_clock("2026-08-05T10:00:00Z")
        first = file_complaint(partner_id, received_at="2026-08-05T09:00:00Z")
        assign_root_cause(
            first["id"],
            root_cause_code="VENDOR_ERROR",
            investigation_note="the card processor dropped the authorisation reversal",
        )
        set_clock("2026-08-06T10:00:00Z")
        second = file_complaint(partner_id, received_at="2026-08-06T09:00:00Z")
        assign_root_cause(
            second["id"],
            root_cause_code="KYC_FRICTION",
            investigation_note="the identity vendor rejected a valid document",
        )
        assert parse_instant(second["created_at"]) > parse_instant(first["created_at"]), (
            "the KYC_FRICTION complaint is the later arrival, so a created_at tie-break and a "
            "lexicographic tie-break cannot agree"
        )
        set_clock("2026-08-07T10:00:00Z")
        third = file_complaint(
            partner_id,
            channel="SOCIAL",
            received_at="2026-08-07T09:00:00Z",
            narrative="a Friday post about a failed transfer",
        )
        assert_same_instant(
            third["response_due_at"], "2026-08-14T23:59:59.999Z", "third response_due_at"
        )
        set_clock("2026-08-08T10:00:00Z")
        fourth = file_complaint(partner_id, received_at="2026-08-08T09:00:00Z")
        withdrawn = dispose_complaint(
            fourth["id"], "WITHDRAWN", resolution_note="the consumer withdrew the complaint"
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["root_cause_code"] is None

        set_clock("2026-09-01T00:00:00Z")
        closed = close_cycle(ctx["cycle"]["id"])
        assert closed["status"] == "CLOSED"
        assert closed["complaints_escalated_count"] == 1, "only the SOCIAL complaint is overdue"

        escalated = get_success_data(api_client.get_complaint(third["id"], PO))
        assert escalated["status"] == "ESCALATED"
        assert escalated["root_cause_code"] is None, (
            "an escalated complaint with no diagnosis is still outside the pool"
        )

        summary = oversight_summary(partner_id)
        assert summary["systemic_root_cause_code"] == "VENDOR_ERROR", (
            "the one-to-one count tie is broken by the earliest created_at, which belongs to "
            f"the VENDOR_ERROR complaint, got {summary['systemic_root_cause_code']}"
        )
        assert summary["systemic_root_cause_code"] != "KYC_FRICTION", (
            "a lexicographic-first tie-break would have returned KYC_FRICTION"
        )
        assert summary["last_closed_cycle_index"] == 1


class TestClawbackRestoresEachTerm:
    def test_every_conserved_term_returns_to_its_pre_funding_value(self):
        """Because clawback restores each of the four conserved terms of §2.11 individually, the
        end-user balance, the reserve balance, the cumulative payout and the cumulative fee all
        return to precisely the values they held before the funding. The batch advances
        `FUNDED → CLAWED_BACK`, and `funded_at`, `bank_fee_cents`, `bank_fee_bps_applied`,
        `reserve_funding_cents` and `net_to_partner_cents` are all left untouched as the historical
        record of what was paid.

        Design: Corner/calculations/clawback_restores_all_four_conserved_settlement_terms_to_their_pre_funding_values
        """
        ctx = setup_live_partner(
            partner_overrides={
                "legal_name": "Quarrystone Cards Inc",
                "business_model": "CARD_ISSUING",
                "end_user_account_count": 8_000,
            },
            agreement_overrides={"reserve_requirement_bps": 500},
            fbo_balance_cents=8_100_000,
            reserve_balance_cents=506_250,
        )
        partner_id = ctx["partner"]["id"]
        before = read_partner(partner_id)
        assert before["cumulative_paid_out_cents"] == 0
        assert before["cumulative_bank_fee_cents"] == 0

        batch = setup_matched_batch(
            partner_id,
            gross_settlement_cents=8_000_000,
            interchange_cents=200_000,
            returns_cents=100_000,
            partner_reported_net_cents=8_100_000,
        )
        funded = fund_batch(batch["id"], funding_reference="WIRE-CB-1")
        assert funded["funding_status"] == "FUNDED"
        assert funded["bank_fee_cents"] == 61_000
        assert funded["reserve_funding_cents"] == 400_000
        assert funded["net_to_partner_cents"] == 7_639_000
        assert_same_instant(funded["funded_at"], "2026-08-01T00:00:00Z", "funded_at")

        assert read_custody_account(ctx["fbo"]["id"])["balance_cents"] == 0
        assert read_custody_account(ctx["reserve"]["id"])["balance_cents"] == 845_250
        mid = read_partner(partner_id)
        assert mid["cumulative_paid_out_cents"] == 7_639_000
        assert mid["cumulative_bank_fee_cents"] == 61_000

        clawed = clawback_batch(batch["id"], clawback_reason="RECONCILIATION_ERROR")
        assert clawed["funding_status"] == "CLAWED_BACK"

        legs = [e for e in batch_ledger_entries(partner_id, batch["id"])
                if e["entry_type"] == "CLAWBACK"]
        assert len(legs) == 3, (
            f"one CLAWBACK entry per funding leg, got {len(legs)}"
        )
        assert all(leg["reversal_of_entry_id"] is not None for leg in legs)
        assert len({leg["reversal_of_entry_id"] for leg in legs}) == 3, (
            "each clawback entry names a distinct reversed entry"
        )
        assert sorted(leg["amount_cents"] for leg in legs) == [-400_000, 61_000, 8_100_000], (
            "each leg is the exact negation of the entry it reverses, so the reversal of the "
            "positive RESERVE_FUND leg is itself negative, got "
            f"{sorted(leg['amount_cents'] for leg in legs)}"
        )

        assert read_custody_account(ctx["fbo"]["id"])["balance_cents"] == 8_100_000
        assert read_custody_account(ctx["reserve"]["id"])["balance_cents"] == 506_250
        after = read_partner(partner_id)
        assert after["cumulative_paid_out_cents"] == 0
        assert after["cumulative_bank_fee_cents"] == 0

        historical = read_batch(batch["id"])
        assert historical["bank_fee_cents"] == 61_000
        assert historical["bank_fee_bps_applied"] == 45
        assert historical["reserve_funding_cents"] == 400_000
        assert historical["net_to_partner_cents"] == 7_639_000
        assert_same_instant(historical["funded_at"], "2026-08-01T00:00:00Z", "funded_at retained")
        assert historical["clawback_reason"] == "RECONCILIATION_ERROR"
