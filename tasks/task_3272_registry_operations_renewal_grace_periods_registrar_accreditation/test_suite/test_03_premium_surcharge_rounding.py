"""Premium surcharge rounding-order tests (PRD §2.6, §3.3)."""
from test_helpers import (
    find_invoice,
    get_success_data,
    make_admin_headers,
    make_operator_headers,
    set_clock,
)


def _restore_invoice_for_premium_domain(api, name, renew_fee, restore_fee):
    resp = api.create_price_schedule(
        {
            "create_fee_cents": 700,
            "renew_fee_cents": renew_fee,
            "restore_fee_cents": restore_fee,
            "transfer_fee_cents": 700,
            "effective_on": "2027-03-01T00:00:00Z",
        },
        make_admin_headers(),
    )
    get_success_data(resp, expected_status=201)
    resp = api.create_registrar(
        {
            "iana_number": 8003,
            "legal_name": "Gamma Registrar SA",
            "application_fee_cents": 250000,
            "annual_fee_cents": 400000,
            "escrow_deposit_cents": 1000000,
            "technical_test_score": 88,
            "financial_statement_verified": True,
        },
        make_admin_headers(),
    )
    registrar = get_success_data(resp, expected_status=201)
    resp = api.accredit_registrar(registrar["id"], make_admin_headers())
    get_success_data(resp)
    set_clock("2027-03-01T00:00:00Z")
    headers = make_operator_headers(registrar["id"])
    resp = api.create_domain(
        {"name": name, "registrar_id": registrar["id"], "years": 1,
         "premium": True},
        headers,
    )
    domain = get_success_data(resp, expected_status=201)
    resp = api.delete_domain(domain["id"], headers)
    deleted = get_success_data(resp)
    assert deleted["status"] == "REDEMPTION_GRACE"
    resp = api.restore_domain(domain["id"], headers)
    get_success_data(resp)
    return find_invoice(domain_id=domain["id"], kind="RESTORE")


class TestPremiumSurchargeCompositeBase:
    def test_surcharge_computed_on_composite_restore_base(self, api):
        """PRD §3.3: "mints a `RESTORE` invoice whose base is the effective
        schedule's `renew_fee_cents` plus its `restore_fee_cents`."
        PRD §2.6: "`premium_surcharge_cents` is ten percent of the base,
        rounded half-up to whole cents."

        The base is the composite (renew 850 + restore 12000 = 12850); the
        surcharge is round_half_up(12850 * 0.10) = 1285 and the total is
        14135.

        Design: Difficulty/combinatorial_formula/premium_surcharge_rounds_composite_restore_base_once
        """
        invoice = _restore_invoice_for_premium_domain(
            api, "roundtrip-premium", renew_fee=850, restore_fee=12000)
        assert invoice["base_cents"] == 12850
        assert invoice["premium_surcharge_cents"] == 1285
        assert invoice["total_cents"] == 14135

    def test_surcharge_rounds_once_on_composite_base(self, api):
        """PRD §2.6: "Where a computation produces a fraction of a cent
        (proration of an annual fee, the premium surcharge, a price-cap
        ceiling), the result is rounded half-up to the nearest whole cent,
        and rounding is applied exactly once at the end of the computation
        with no intermediate rounding."
        PRD §3.3: "mints a `RESTORE` invoice whose base is the effective
        schedule's `renew_fee_cents` plus its `restore_fee_cents`."

        Discriminating probe: renew 833 + restore 12134 gives composite base
        12967, whose tenth is 1296.7 -> 1297 under a single final rounding.
        Rounding each component's tenth separately would give
        round_half_up(83.3) + round_half_up(1213.4) = 83 + 1213 = 1296 —
        the forbidden intermediate-rounding order.

        Design: Difficulty/combinatorial_formula/premium_surcharge_rounds_composite_restore_base_once
        """
        invoice = _restore_invoice_for_premium_domain(
            api, "roundtrip-premium-849", renew_fee=833, restore_fee=12134)
        assert invoice["base_cents"] == 12967
        assert invoice["premium_surcharge_cents"] == 1297, (
            f"composite-base single rounding yields 1297, got "
            f"{invoice['premium_surcharge_cents']}"
        )
        assert invoice["total_cents"] == 14264
