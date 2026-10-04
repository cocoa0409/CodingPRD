"""Monthly invoice calculation tests (surcharge components, rounding, windows)."""
from test_helpers import (
    set_clock,
    make_customer,
    make_contract,
    add_service_line,
    activate_contract,
    make_fixed_config,
    make_pickup_event,
    make_service_credit,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

OPS = TEST_USERS["ops_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


class TestMonthlyInvoicePerComponentRounding:
    def test_per_component_rounding_then_sum_matches_pinned_order(self, api):
        """PRD section 2.6: "Rounding order is pinned wherever multi-component
        totals are involved: each component is rounded individually before any
        summation, and summing unrounded values and rounding once at the end is
        forbidden."
        PRD section 3.7: "The `total_cents` is the base plus fuel plus
        environmental plus administrative plus fees, minus credits."

        Design: Difficulty/combinatorial_formula/monthly_invoice_per_component_rounding_then_sum
        """
        set_clock("2026-09-01T00:00:00Z")
        make_fixed_config(
            effective_from="2026-09-01T00:00:00Z",
            fuel_fixed_pct=0.13, environmental_pct=0.07, admin_pct=0.05,
        )
        customer = make_customer(legal_name="Round Test Co", billing_email="r@x.example")
        contract = make_contract(customer["id"], term_months=12)
        add_service_line(
            contract["id"], container_size="CY_2",
            frequency_per_week=2, base_rate_cents=33333,
        )
        activate_contract(contract["id"])

        inv = validate_success(
            api.get_monthly_invoice(contract["id"], OPS)
        )
        # Each component rounded half-up before summation:
        # 33333*0.13 = 4333.29 -> 4333; 33333*0.07 = 2333.31 -> 2333;
        # 33333*0.05 = 1666.65 -> 1667.
        assert inv["base_cents"] == 33333
        assert inv["fuel_cents"] == 4333
        assert inv["env_cents"] == 2333
        assert inv["admin_cents"] == 1667
        assert inv["fees_cents"] == 0
        assert inv["credits_cents"] == 0
        assert inv["total_cents"] == 41666, (
            "per-component rounding then summation must give 41666; rounding "
            f"once at the end would give 41667, got {inv['total_cents']}"
        )

    def test_invoice_breakdown_has_all_seven_components(self, api):
        """PRD section 3.7: "A computed read returns a contract's current monthly
        invoice breakdown with seven integer-cent components: `base_cents`,
        `fuel_cents`, `env_cents`, `admin_cents`, `fees_cents`, `credits_cents`,
        and `total_cents`."

        Design: Difficulty/combinatorial_formula/monthly_invoice_per_component_rounding_then_sum
        """
        set_clock("2026-09-01T00:00:00Z")
        make_fixed_config(
            effective_from="2026-09-01T00:00:00Z",
            fuel_fixed_pct=0.13, environmental_pct=0.07, admin_pct=0.05,
        )
        customer = make_customer(legal_name="Round Test Co", billing_email="r@x.example")
        contract = make_contract(customer["id"], term_months=12)
        add_service_line(
            contract["id"], container_size="CY_2",
            frequency_per_week=2, base_rate_cents=33333,
        )
        activate_contract(contract["id"])

        inv = validate_success(api.get_monthly_invoice(contract["id"], OPS))
        for field in (
            "base_cents", "fuel_cents", "env_cents", "admin_cents",
            "fees_cents", "credits_cents", "total_cents",
        ):
            assert isinstance(inv.get(field), int), f"{field} must be integer cents"


class TestIndexedFuelFloor:
    def test_indexed_fuel_below_base_yields_zero(self, api):
        """PRD section 3.7: "when the mode is `INDEXED`, the fuel percentage is
        the amount by which `fuel_index_current` exceeds `fuel_index_base`,
        floored at zero, divided by `fuel_index_base` — a current index at or
        below the base yields a zero fuel surcharge and the percentage is never
        negative."

        Design: Corner/calculations/monthly_invoice_indexed_fuel_below_base_zero
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.create_surcharge_config(
            {
                "fuel_mode": "INDEXED",
                "fuel_index_base": 4.00,
                "fuel_index_current": 3.00,
                "environmental_pct": 0.10,
                "admin_pct": 0.05,
                "contamination_fee_cents": 15000,
                "overweight_fee_cents": 20000,
                "effective_from": "2026-09-01T00:00:00Z",
            },
            ADMIN,
        )
        assert resp.status_code == 201, f"Setup failed: {resp.text}"
        customer = make_customer(legal_name="Idx Co", billing_email="ix@x.example")
        contract = make_contract(customer["id"], term_months=12)
        add_service_line(contract["id"], base_rate_cents=200000)
        activate_contract(contract["id"])

        inv = validate_success(api.get_monthly_invoice(contract["id"], OPS))
        assert inv["fuel_cents"] == 0, (
            f"current index 3.00 below base 4.00 must floor the fuel surcharge "
            f"to zero, got {inv['fuel_cents']}"
        )
        assert inv["env_cents"] == 20000
        assert inv["admin_cents"] == 10000
        assert inv["total_cents"] == 230000


class TestInvoiceFeesAndCredits:
    def test_window_filters_event_fees_and_active_credits(self, api):
        """PRD section 3.7: "The `fees_cents` is the sum of
        `contamination_fee_cents` plus `overweight_fee_cents` over every pickup
        event on the contract's lines whose `occurred_date` falls inside the
        trailing 30-day window from 30 days before the logical clock up to and
        including the clock time. The `credits_cents` is the sum of
        `credit_cents` over every `ACTIVE` service credit on the contract's
        lines."

        Design: Corner/calculations/invoice_includes_event_fees_and_credits
        """
        set_clock("2026-09-01T00:00:00Z")
        # credit_pct_of_base names the percentage the credit is computed from;
        # 0.05 of 100000 yields the asserted 5000 credit. effective_from is
        # backdated to 2026-08-01 so a pre-September occurred_date still has an
        # active configuration.
        make_fixed_config(
            effective_from="2026-08-01T00:00:00Z",
            fuel_fixed_pct=0.10, environmental_pct=0.10, admin_pct=0.05,
            contamination_fee_cents=15000, overweight_fee_cents=20000,
            credit_pct_of_base=0.05,
        )
        customer = make_customer(legal_name="Fee Co", billing_email="f@x.example")
        contract = make_contract(customer["id"], term_months=12)
        line = add_service_line(
            contract["id"], frequency_per_week=3, base_rate_cents=100000
        )
        activate_contract(contract["id"])

        # Event older than 30 days before the final clock time (2026-09-20):
        # 2026-08-20 is outside [2026-08-20, 2026-09-20]... 2026-08-20 is the
        # inclusive lower bound; use 2026-08-19 to be strictly outside.
        set_clock("2026-09-01T00:00:00Z")
        make_pickup_event(
            line["id"], "2026-08-19", "CONTAMINATED",
            photo_evidence_url="https://img.example/old.jpg",
        )
        # MISSED event inside the window, for the credit.
        set_clock("2026-09-14T12:00:00Z")
        missed = make_pickup_event(line["id"], "2026-09-14", "MISSED")
        # CONTAMINATED_OVERWEIGHT event inside the window: 15000 + 20000 fees.
        set_clock("2026-09-15T12:00:00Z")
        make_pickup_event(
            line["id"], "2026-09-15", "CONTAMINATED_OVERWEIGHT",
            photo_evidence_url="https://img.example/new.jpg",
        )
        make_service_credit(customer["id"], line["id"], missed["id"])

        set_clock("2026-09-20T00:00:00Z")
        inv = validate_success(api.get_monthly_invoice(contract["id"], OPS))
        assert inv["fees_cents"] == 35000, (
            "only the 2026-09-15 event is inside the trailing 30-day window; "
            f"the 2026-08-19 event must be excluded, got {inv['fees_cents']}"
        )
        assert inv["credits_cents"] == 5000
        assert inv["total_cents"] == 100000 + 10000 + 10000 + 5000 + 35000 - 5000


class TestPickupEventFeeSnapshot:
    def test_event_fee_snapshots_config_active_at_occurred_date(self, api):
        """PRD section 3.5: "Fees are stamped onto the event at recording time
        from the surcharge configuration active at the `occurred_date` (per the
        active-window rule in section 2.9)."
        PRD section 3.5: "When the outcome includes contamination, the event's
        `contamination_fee_cents` equals the active configuration's
        `contamination_fee_cents`; otherwise it is 0."

        Design: Corner/calculations/pickup_event_fee_snapshot_at_occurred_date
        """
        set_clock("2026-09-01T00:00:00Z")
        make_fixed_config(
            effective_from="2026-09-01T00:00:00Z", contamination_fee_cents=15000,
        )
        make_fixed_config(
            effective_from="2026-09-10T00:00:00Z", contamination_fee_cents=18000,
        )
        customer = make_customer(legal_name="Snap Co", billing_email="s@x.example")
        contract = make_contract(customer["id"], term_months=12)
        line = add_service_line(contract["id"], base_rate_cents=100000)
        activate_contract(contract["id"])

        set_clock("2026-09-05T12:00:00Z")
        event = make_pickup_event(
            line["id"], "2026-09-05", "CONTAMINATED",
            photo_evidence_url="https://img.example/c.jpg",
        )
        assert event["contamination_fee_cents"] == 15000

        # Advance past config B's effective_from; the stored fee must not move.
        set_clock("2026-09-12T00:00:00Z")
        fetched = validate_success(api.get_pickup_event(event["id"], OPS))
        assert fetched["contamination_fee_cents"] == 15000, (
            "fee is a snapshot of the configuration active at occurred_date "
            f"2026-09-05, got {fetched['contamination_fee_cents']}"
        )
