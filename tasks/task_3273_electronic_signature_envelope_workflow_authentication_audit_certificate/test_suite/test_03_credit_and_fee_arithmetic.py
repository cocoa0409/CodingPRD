"""Credit consumption, page fees and the fee quote."""
from decimal import Decimal, ROUND_HALF_UP


from test_helpers import (
    ADMIN_HEADERS,
    api_client,
    make_account_headers,
    send_envelope,
    setup_for_credit_debit,
    setup_multi_document_envelope,
    validate_success,
)

MONEY = Decimal("0.01")


def _money(value):
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


def _signer_specs(count, prefix="s"):
    return [
        {
            "role": "SIGNER",
            "email": f"{prefix}{i + 1}@example.com",
            "routing_order": 1,
            "auth_level": "EMAIL_ACCESS",
            "consent_accepted": True,
        }
        for i in range(count)
    ]


class TestCreditSpendConsumption:
    """§2.9: five-step non-linear debit (page blocks, recipient overage, tier
    multiplier, conditional doubling)."""

    def test_send_debits_tiered_credit_consumption(self, api):
        """PRD §2.9: "Third, the base unit count is one plus the page-block
        count plus the recipient overage. Fourth, the base count is multiplied
        by a tier multiplier — one for `STANDARD`, eight tenths for `PRO`, five
        tenths for `ENTERPRISE` — and that product is rounded up to a whole
        number of credit units."
        PRD §2.9: "The account is debited: `credit_balance` decreases by the
        computed credit consumption and the account's `version` advances."

        Design: Difficulty/combinatorial_formula/credit_spend_consumption_tiered_and_status_conditional
        """
        ctx = setup_for_credit_debit(
            [70, 70, 70],
            _signer_specs(7),
            credit_balance=11000,
        )
        account, envelope = ctx["account"], ctx["envelope"]
        balance_before = account["credit_balance"]

        # page_overage = ceil((210 - 25) / 10) = 19; recipient_overage = 7 - 5 = 2;
        # base = 1 + 19 + 2 = 22; STANDARD multiplier 1.0; ACTIVE so no doubling.
        sent = send_envelope(envelope, account)

        assert sent["status"] == "SENT", f"the send must commit, got {sent['status']}"
        after = validate_success(
            api_client.get_account(account["id"], ADMIN_HEADERS), 200
        )
        assert after["credit_balance"] == balance_before - 22, (
            f"the debit must be 22 units: expected {balance_before - 22}, "
            f"got {after['credit_balance']} (a suspend-agnostic or additive reading "
            "would land elsewhere)"
        )

    def test_recipient_overage_floor_sets_one_unit_less(self, api):
        """PRD §2.9: "Second, the recipient overage is derived: the count of the
        envelope's recipients whose role is `SIGNER` or `APPROVER` is reduced by
        five and any negative excess is treated as zero."
        PRD §2.9: "the count of the envelope's recipients whose role is `SIGNER`
        or `APPROVER`".

        Design: Difficulty/combinatorial_formula/credit_spend_consumption_tiered_and_status_conditional
        """
        ctx = setup_for_credit_debit([70, 70, 70], _signer_specs(6), credit_balance=11000)
        account, envelope = ctx["account"], ctx["envelope"]
        balance_before = account["credit_balance"]

        # page_overage 19; recipient_overage = 6 - 5 = 1; base = 1 + 19 + 1 = 21.
        send_envelope(envelope, account)

        after = validate_success(api_client.get_account(account["id"], ADMIN_HEADERS), 200)
        assert after["credit_balance"] == balance_before - 21, (
            f"six signers yield a recipient overage of 1, so the debit is 21: "
            f"expected {balance_before - 21}, got {after['credit_balance']}"
        )


class TestEnvelopePageFee:
    """§2.9: the per-document page fee rounds each document to cents before summing."""

    def test_fee_breakdown_rounds_per_document_before_summing(self, api):
        """PRD §2.9: "Each document's chargeable block count is multiplied by
        the per-document rate of 12.335, and that product is rounded half up to
        exactly two decimal places before it is added to the running total."
        PRD §2.9: "The rounding happens per document, before summing; the summed
        fee is never rounded a second time, and rounding the aggregate once
        instead would produce a different figure."

        Design: Difficulty/combinatorial_formula/envelope_page_fee_per_document_rounding_order
        """
        ctx = setup_multi_document_envelope(
            [70, 70, 70],
            _signer_specs(1),
            field_specs=[{"doc": 0, "recipient": 0, "value": "S1"}],
        )
        account, envelope = ctx["account"], ctx["envelope"]

        res = api_client.get_fee_breakdown(envelope["id"], make_account_headers(account["id"]))
        breakdown = validate_success(res, 200)

        # ceil(70/10) = 7 blocks; floor(25/10) = 2 free blocks; 5 chargeable
        # blocks x 12.335 = 61.675, rounded half up per document to 61.68, then
        # summed over the three documents: 185.04. Rounding the aggregate once
        # instead (15 x 12.335 = 185.025 -> 185.03) is the divergent variant.
        assert _money(breakdown["total_page_fee"]) == Decimal("185.04"), (
            "three documents rounded per document sum to 185.04; rounding the "
            f"aggregate once would give 185.03, got {breakdown['total_page_fee']}"
        )

    def test_page_fee_applies_the_free_block_floor_per_document(self, api):
        """PRD §2.9: "The free block count is derived once from the account's
        `page_allowance` by dividing it by ten and rounding down, and it is
        applied to every document independently."

        Design: Difficulty/combinatorial_formula/envelope_page_fee_per_document_rounding_order
        """
        ctx = setup_multi_document_envelope(
            [30, 30],
            _signer_specs(1),
            field_specs=[{"doc": 0, "recipient": 0, "value": "S1"}],
        )
        account, envelope = ctx["account"], ctx["envelope"]

        breakdown = validate_success(
            api_client.get_fee_breakdown(envelope["id"], make_account_headers(account["id"])),
            200,
        )

        # ceil(30/10) = 3 blocks minus 2 free blocks = 1 chargeable block each;
        # the free block count is applied to each document independently, so two
        # documents pay two chargeable blocks: 1.00 x 12.335 -> 12.34 per
        # document, summed to 24.68.
        assert _money(breakdown["total_page_fee"]) == Decimal("24.68"), (
            "the free block count is applied to each document independently, so "
            f"two documents pay two chargeable blocks: got {breakdown['total_page_fee']}"
        )


class TestEnvelopeFeeQuote:
    """§2.9: subtotal, flat tier discount, total — in a pinned evaluation order."""

    def test_quote_at_exactly_one_hundred_pages_switches_discount_on(self, api):
        """PRD §2.9: "The discount rate is determined by the envelope's total
        page count — again the sum of `page_count` over non-certificate
        documents — as a flat tier: for fewer than 100 pages the rate is zero;
        for 100 pages up to and including 500 it is 0.02".
        PRD §2.9: "The subtotal is a base charge of 1500.00 plus that page
        component. The discount is the subtotal multiplied by a discount rate,
        rounded half up to two decimal places. The total fee is the subtotal
        minus the discount."

        Design: Difficulty/boundary_precision_check/quote_discount_activates_at_exactly_hundred_pages
        """
        ctx = setup_multi_document_envelope(
            [100],
            _signer_specs(1),
            field_specs=[{"doc": 0, "recipient": 0, "value": "S1"}],
        )
        account, envelope = ctx["account"], ctx["envelope"]

        quote = validate_success(
            api_client.get_envelope_quote(envelope["id"], make_account_headers(account["id"])),
            200,
        )

        assert quote["total_pages"] == 100, (
            f"total_pages must count the non-certificate documents, got {quote['total_pages']}"
        )
        # ceil(100/10) = 10 blocks minus 2 free blocks = 8 blocks x 12.335 = 98.68
        assert _money(quote["page_component"]) == Decimal("98.68"), (
            f"the page component must be 98.68, got {quote['page_component']}"
        )
        # subtotal = 1500.00 + 98.68 = 1598.68; 2% = 31.9736 -> 31.97
        assert _money(quote["subtotal"]) == Decimal("1598.68"), (
            f"the subtotal must be 1598.68, got {quote['subtotal']}"
        )
        assert _money(quote["discount"]) == Decimal("31.97"), (
            f"the 2% tier discount must be 31.97, got {quote['discount']}"
        )
        assert _money(quote["total_fee"]) == Decimal("1566.71"), (
            f"the total fee must be 1566.71, got {quote['total_fee']}"
        )

    def test_quote_below_one_hundred_pages_carries_no_discount(self, api):
        """PRD §2.9: "for fewer than 100 pages the rate is zero".

        Design: Difficulty/boundary_precision_check/quote_discount_activates_at_exactly_hundred_pages
        """
        ctx = setup_multi_document_envelope(
            [99],
            _signer_specs(1),
            field_specs=[{"doc": 0, "recipient": 0, "value": "S1"}],
        )
        account, envelope = ctx["account"], ctx["envelope"]

        quote = validate_success(
            api_client.get_envelope_quote(envelope["id"], make_account_headers(account["id"])),
            200,
        )

        assert quote["total_pages"] == 99
        assert _money(quote["discount"]) == Decimal("0.00"), (
            "the boundary is inclusive at 100 pages, so 99 pages pays no "
            f"discount, got {quote['discount']}"
        )
        assert _money(quote["subtotal"]) == Decimal("1598.68")
        assert _money(quote["total_fee"]) == Decimal("1598.68")