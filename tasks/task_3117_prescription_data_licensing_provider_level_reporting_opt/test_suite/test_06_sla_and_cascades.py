"""SLA period close (dual-variant credits, breach filtering), invoice preview
evaluation order, and the depth-3 agreement-suspension cascade."""
from test_helpers import (
    ApiErrorId,
    create_cell,
    create_client,
    create_delivery_period_payload,
    create_methodology,
    create_product,
    get_success_data,
    setup_validated_batch,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import DAM, PA, PO


class TestSlaCreditVariants:
    def _setup_two_recalled_period(self, api, period_code, period_end_date):
        """Client + methodology + one CURRENT cell + product + one period with
        two deliveries, both driven COMPILED -> RELEASED -> RECALLED."""
        client = create_client(name="Client SLA", entitlement_cells_total=100)
        methodology = create_methodology(name="M-SLA")
        create_cell(
            methodology["id"],
            geography_code="CA-SOUTH",
            specialty="CARDIOLOGY",
            period_code=period_code,
        )
        product = create_product(
            client["id"], methodology["id"], name=f"P-SLA-{period_code}",
            monthly_license_fee_cents=200000,
        )
        period = get_success_data(api.create_delivery_period(
            product["id"],
            create_delivery_period_payload(
                period_code=period_code,
                period_end_date=period_end_date,
                total_due_deliveries=2,
            ),
            PA,
        ))
        deliveries = [
            get_success_data(api.schedule_delivery(period["id"], PA)) for _ in range(2)
        ]
        for delivery in deliveries:
            validate_success(api.compile_delivery(delivery["id"], PA))
            validate_success(api.release_delivery(delivery["id"], PA))
            validate_success(api.recall_delivery(delivery["id"], PA))
        return product, period

    def test_period_weighted_credit_scales_per_breach(self, api):
        """PRD §3.7: "Under `PERIOD_WEIGHTED`, the credit is 5 percent of the monthly fee per
        breached delivery, capped at 25 percent of the monthly fee."

        Design: Difficulty/dual_variant_calc/sla_credit_period_vs_delivery_weighted
        """
        get_success_data(api.set_clock("2026-10-01T00:00:00Z", PA))
        _product, period = self._setup_two_recalled_period(api, "2026-08", "2026-08-31")
        closed = validate_success(
            api.close_delivery_period(period["id"], {"sla_variant": "PERIOD_WEIGHTED"}, PA)
        )
        assert closed["breach_count"] == 2
        assert closed["sla_credit_cents"] == 20000, (
            f"200000 * 0.05 * 2 = 20000, got {closed['sla_credit_cents']}"
        )
        assert closed["status"] == "CLOSED"

    def test_delivery_weighted_credit_capped_at_quarter_fee(self, api):
        """PRD §3.7: "Under `DELIVERY_WEIGHTED`, the credit is the monthly fee scaled by the
        breached share of contracted deliveries — `breach_count` divided by
        `total_due_deliveries` — again capped at 25 percent of the monthly fee."

        Design: Difficulty/dual_variant_calc/sla_credit_period_vs_delivery_weighted
        """
        get_success_data(api.set_clock("2026-10-01T00:00:00Z", PA))
        _product, period = self._setup_two_recalled_period(api, "2026-09", "2026-09-30")
        closed = validate_success(
            api.close_delivery_period(period["id"], {"sla_variant": "DELIVERY_WEIGHTED"}, PA)
        )
        assert closed["breach_count"] == 2
        assert closed["sla_credit_cents"] == 50000, (
            f"200000 * 2/2 = 200000 capped at 25% of fee = 50000, got {closed['sla_credit_cents']}"
        )
        assert closed["status"] == "CLOSED"


class TestSlaBreachFiltering:
    def test_only_recalled_deliveries_count_as_breaches(self, api):
        """PRD §3.7: "At close the system records `breach_count` as the number of the period's
        deliveries sitting in `RECALLED` status at that moment — deliveries recalled and never
        reissued before close are the breaches — and computes `sla_credit_cents` against the
        product's `monthly_license_fee_cents`."

        Design: Corner/calculations/sla_breach_count_filters_recalled_only
        """
        get_success_data(api.set_clock("2026-10-01T00:00:00Z", PA))
        client = create_client(name="Client BC", entitlement_cells_total=100)
        methodology = create_methodology(name="M-BC")
        create_cell(
            methodology["id"],
            geography_code="G1",
            specialty="ONCOLOGY",
            period_code="2026-08",
        )
        product = create_product(
            client["id"], methodology["id"], name="P-BC",
            monthly_license_fee_cents=200000,
        )
        period = get_success_data(api.create_delivery_period(
            product["id"],
            create_delivery_period_payload(
                period_code="2026-08", period_end_date="2026-08-31", total_due_deliveries=2
            ),
            PA,
        ))
        d1 = get_success_data(api.schedule_delivery(period["id"], PA))
        d2 = get_success_data(api.schedule_delivery(period["id"], PA))
        for delivery in (d1, d2):
            validate_success(api.compile_delivery(delivery["id"], PA))
            validate_success(api.release_delivery(delivery["id"], PA))
        validate_success(api.recall_delivery(d1["id"], PA))
        closed = validate_success(
            api.close_delivery_period(period["id"], {"sla_variant": "PERIOD_WEIGHTED"}, PA)
        )
        assert closed["breach_count"] == 1, (
            "the still-RELEASED delivery is not a breach"
        )
        assert closed["sla_credit_cents"] == 10000, (
            f"200000 * 0.05 * 1 = 10000, got {closed['sla_credit_cents']}"
        )


class TestInvoicePreviewEvaluationOrder:
    def test_tiered_discount_keys_on_gross_after_support(self, api):
        """PRD §3.6: "The invoice-preview operation, open to `PlatformAdmin` and to the
        `ManufacturerClient` that owns the product, takes a `period_code` and evaluates a pinned
        order: first the cell fees — the per-cell rounded fee of the product summed over the
        `CURRENT` cells of the product's methodology whose `period_code` matches the requested
        period, reported as `cell_fees_cents`; then the support fee — the cell fees multiplied by
        `support_fee_pct`, rounded half-up, reported as `support_fee_cents`; then `gross_cents` as
        the sum of the two. The discount tier depends on the gross: no discount when the gross is
        below twenty thousand cents, 5 percent when the gross is at least twenty thousand but
        below fifty thousand cents, and 10 percent when the gross reaches fifty thousand cents;
        the applicable fraction is reported as `discount_pct`. Finally `total_cents` is the gross
        multiplied by one minus the discount, rounded half-up."

        Design: Corner/calculations/invoice_total_evaluation_order
        """
        client = create_client(name="Client InvP", entitlement_cells_total=100)
        methodology = create_methodology(name="M-INVP")
        for i in range(1, 13):
            create_cell(
                methodology["id"],
                geography_code=f"G{i:02d}",
                specialty="CARDIOLOGY",
                period_code="2026-08",
            )
        product = create_product(
            client["id"],
            methodology["id"],
            name="P-INVP",
            cell_fee_base_cents=1235,
            cell_fee_multiplier=1.5,
        )
        preview = validate_success(
            api.invoice_preview(product["id"], {"period_code": "2026-08"}, PA)
        )
        assert preview["cell_fees_cents"] == 22236, (
            f"12 x round_half_up(1235 * 1.5) = 12 x 1853 = 22236, got {preview['cell_fees_cents']}"
        )
        assert preview["support_fee_cents"] == 1779, (
            f"round_half_up(22236 * 0.08) = 1779, got {preview['support_fee_cents']}"
        )
        assert preview["gross_cents"] == 24015
        assert preview["discount_pct"] == 0.05, (
            "the discount tier keys on the gross (20000 <= 24015 < 50000)"
        )
        assert preview["total_cents"] == 22814, (
            f"round_half_up(24015 * 0.95) = 22814, got {preview['total_cents']}"
        )


class TestAgreementSuspensionCascade:
    def _cascade_setup(self, api):
        """Supplier + ACTIVE agreement + VALIDATED batch + methodology + CURRENT
        cell listing the supplier + client + product + period + COMPILED
        delivery over that cell."""
        supplier, agreement, batch = setup_validated_batch(
            supplier_overrides={"supplier_type": "DISTRIBUTOR", "state_code": "NV"},
            agreement_overrides={"data_domain": "DISTRIBUTION_SHIPMENTS",
                                 "royalty_budget_cents": 10000000},
            batch_overrides={"period_code": "2026-08", "record_count": 5000},
        )
        methodology = create_methodology(name="M-CAS")
        cell = create_cell(
            methodology["id"],
            geography_code="NV-NORTH",
            specialty="PRIMARY_CARE",
            period_code="2026-08",
            sample_units=100,
            market_outlets=200,
            sampled_outlets=100,
            market_population=500000,
            sampled_population=250000,
            supplier_ids=[supplier["id"]],
        )
        client = create_client(name="Client Cas", entitlement_cells_total=100)
        product = create_product(client["id"], methodology["id"], name="P-CAS")
        period = get_success_data(api.create_delivery_period(
            product["id"],
            create_delivery_period_payload(period_code="2026-08",
                                           period_end_date="2026-08-31"),
            PA,
        ))
        delivery = get_success_data(api.schedule_delivery(period["id"], PA))
        compiled = validate_success(api.compile_delivery(delivery["id"], PA))
        return {
            "supplier": supplier, "agreement": agreement, "batch": batch,
            "cell": cell, "client": client, "delivery": compiled,
        }

    def test_suspend_quarantines_batches_marks_cells_recalls_deliveries(self, api):
        """PRD §3.2: "Suspending an `ACTIVE` agreement — directly, or via the supplier cascade — is
        the most consequential act in the acquisition pipeline, and it unfolds in three links.
        Link one: every feed batch of the agreement in `VALIDATED` or `DEIDENTIFIED` status
        transitions to `QUARANTINED`, and each such batch has its `deidentification_profile_id`
        cleared to null. Link two: each quarantined batch marks every projection cell that is
        `CURRENT`, whose `period_code` equals the batch's `period_code`, and whose `supplier_ids`
        contains the agreement's supplier as `PENDING_RESTATEMENT`. Link three: each cell so
        marked recalls every report delivery in `COMPILED` or `RELEASED` status whose
        `compiled_cell_ids` contains that cell — the delivery moves to `RECALLED`, its
        `recall_count` increments by 1, `must_recompile` becomes true, and the owning client's
        `entitlement_cells_balance` is credited back by the number of cell ids in the delivery's
        `compiled_cell_ids`."

        Design: Difficulty/transitive_cascade/agreement_suspend_cascades_batches_cells_deliveries
        """
        ctx = self._cascade_setup(api)
        suspended = validate_success(api.suspend_agreement(ctx["agreement"]["id"], DAM))
        assert suspended["status"] == "SUSPENDED"
        batch = validate_success(api.get_batch(ctx["batch"]["id"], PA))
        assert batch["status"] == "QUARANTINED", "link 1: VALIDATED batch quarantined"
        cell = validate_success(api.get_cell(ctx["cell"]["id"], PA))
        assert cell["status"] == "PENDING_RESTATEMENT", "link 2: cell marked"
        delivery = validate_success(api.get_delivery(ctx["delivery"]["id"], PA))
        assert delivery["status"] == "RECALLED", "link 3: compiled delivery recalled"
        assert delivery["recall_count"] == 1
        assert delivery["must_recompile"] is True
        client = validate_success(api.get_client(ctx["client"]["id"], PA))
        assert client["entitlement_cells_balance"] == 100, (
            "the cascade recall reverses the compile debit"
        )

    def test_suspend_leaves_unrelated_resources_untouched(self, api):
        """PRD §3.2: "Link two: each quarantined batch marks every projection cell that is
        `CURRENT`, whose `period_code` equals the batch's `period_code`, and whose `supplier_ids`
        contains the agreement's supplier as `PENDING_RESTATEMENT`."

        Design: Difficulty/transitive_cascade/agreement_suspend_cascades_batches_cells_deliveries
        """
        ctx = self._cascade_setup(api)
        # A cell of the same methodology for a different period is outside the cascade.
        other_cell = create_cell(
            ctx["cell"]["methodology_id"],
            geography_code="NV-SOUTH",
            specialty="PRIMARY_CARE",
            period_code="2026-09",
            supplier_ids=[ctx["supplier"]["id"]],
        )
        validate_success(api.suspend_agreement(ctx["agreement"]["id"], DAM))
        untouched = validate_success(api.get_cell(other_cell["id"], PA))
        assert untouched["status"] == "CURRENT", (
            "cells whose period_code differs from the quarantined batch are not marked"
        )
