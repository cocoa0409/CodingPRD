"""Domestic-content attestations: dual-variant percentages, adjudication fork,
and the independent content/schedule dimensions on deliveries."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_attestation,
    create_attestation_payload,
    create_component_lot_payload,
    create_production_line,
    create_submitted_attestation,
    create_verified_lot,
    get_delivery,
    get_line,
    make_customer_admin_headers,
    setup_scheduled_delivery,
    validate_error,
    validate_success,
)

CPL = TEST_USERS["compliance_officer_headers"]
SCA = TEST_USERS["supply_chain_auditor_headers"]


def test_attestation_total_below_domestic_sum_rejected(api):
    """PRD §3.7: "Every cost field is zero or more, and the total must be at
    least the sum of the five domestic components."

    Design: Corner/entities/attestation_total_below_domestic_sum_rejected
    """
    line = create_production_line()
    resp = api.create_attestation(
        create_attestation_payload(
            line_id=line["id"],
            labor_cost_usd=100.0,
            feedstock_cost_usd=50.0,
            glass_cost_usd=30.0,
            balance_of_system_cost_usd=20.0,
            overhead_cost_usd=10.0,
            total_manufactured_cost_usd=200.0,  # below the 210.0 domestic sum
        ),
        CPL,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_qualify_below_printed_threshold_rejected(api):
    """PRD §3.7: "Qualification — `SUBMITTED → QUALIFIED` — is only permitted
    when `manufactured_products_pct` is at least 0.40 and `printed_content_pct`
    is at least 0.40; attempting to qualify an attestation below either
    threshold is rejected with `ERR_CONTENT_THRESHOLD_NOT_MET` (HTTP 422), so
    adjudication in that case must be a rejection."

    Design: Corner/validations/qualify_below_printed_threshold_rejected
    """
    line = create_production_line()
    # printed_content_pct == 78/200 == 0.3900 < 0.40
    attestation = create_submitted_attestation(
        line,
        labor_cost_usd=78.0,
        feedstock_cost_usd=0.0,
        glass_cost_usd=0.0,
        balance_of_system_cost_usd=0.0,
        overhead_cost_usd=0.0,
        total_manufactured_cost_usd=200.0,
    )
    assert attestation["status"] == "SUBMITTED"

    resp = api.adjudicate_attestation(attestation["id"], {"outcome": "QUALIFY"}, CPL)
    validate_error(resp, ApiErrorId.ERR_CONTENT_THRESHOLD_NOT_MET)

    # A failed QUALIFY leaves the attestation SUBMITTED; REJECT then succeeds.
    resp = api.adjudicate_attestation(attestation["id"], {"outcome": "REJECT"}, CPL)
    data = validate_success(resp, 200)
    assert data["status"] == "REJECTED"


def test_attestation_reject_fork_marks_deliveries_non_qualifying(api):
    """PRD §3.7: "Rejection — `SUBMITTED → REJECTED` — instead sets the line's
    `qualification_tier` to `UNQUALIFIED` and sweeps every
    `SCHEDULED`/`RESCHEDULED` delivery on the line's reservations to
    `content_status` `NON_QUALIFYING` regardless of the customer flag, again
    incrementing the line's `version`. Both `QUALIFIED` and `REJECTED` are
    terminal."

    Design: Corner/state_machines/attestation_reject_fork_marks_deliveries_non_qualifying
    """
    scenario = setup_scheduled_delivery(
        volume_mw=2.0, customer_overrides={"tax_credit_flag": False}
    )
    delivery, line = scenario["delivery"], scenario["line"]
    attestation = create_submitted_attestation(line)  # domestic 210 / total 500

    resp = api.adjudicate_attestation(attestation["id"], {"outcome": "REJECT"}, CPL)
    data = validate_success(resp, 200)
    assert data["status"] == "REJECTED"

    assert get_line(line["id"])["qualification_tier"] == "UNQUALIFIED"
    after = get_delivery(delivery["id"])
    assert after["content_status"] == "NON_QUALIFYING"
    assert after["schedule_status"] == "SCHEDULED", (
        "the reject fork does not touch the schedule dimension"
    )


class TestPrintedVsAdjustedContentPct:
    """Submission freezes three percentages: manufactured-products (verified
    lots only), printed (unadjusted), and adjusted (with the fixed 4.0 USD
    direct-cost adjustment)."""

    def test_submit_freezes_printed_adjusted_and_manufactured(self, api):
        """PRD §3.7: "First, `manufactured_products_pct`: the percentage of
        verified-lot cost from domestic origin across the attestation's period,
        aggregating only lots in `VERIFIED` status — lots in
        `PENDING_INSPECTION` or `QUARANTINED` are excluded. Second,
        `printed_content_pct`: the sum of the five domestic cost fields divided
        by `total_manufactured_cost_usd` — the unadjusted cost ratio that is the
        binding statutory test. Third, `adjusted_content_pct`: the same sum plus
        a fixed direct-cost adjustment of 4.0 USD in the numerator, over the
        total plus the same 4.0 in the denominator — a safe-harbor disclosure
        figure reported alongside, always higher than the printed figure."

        Design: Difficulty/dual_variant_calc/printed_vs_adjusted_content_pct
        """
        line = create_production_line()  # site_country US
        create_verified_lot(
            lot_code="LOT-US-400", component_type="SEMICONDUCTOR_FEEDSTOCK",
            country_of_origin="US", lot_cost_usd=400.0,
        )
        create_verified_lot(
            lot_code="LOT-CN-600", component_type="GLASS",
            country_of_origin="CN", lot_cost_usd=600.0,
        )
        # PENDING_INSPECTION domestic lot: excluded from manufactured_products_pct.
        validate_success(
            api.create_component_lot(
                create_component_lot_payload(
                    lot_code="LOT-US-PEND", component_type="FRAME",
                    country_of_origin="US", lot_cost_usd=1000.0,
                ),
                SCA,
            ),
            201,
        )

        attestation = create_attestation(line)  # domestic sum 210, total 500
        resp = api.submit_attestation(attestation["id"], CPL)
        data = validate_success(resp, 200)
        assert data["status"] == "SUBMITTED"
        # printed = 210 / 500 == 0.4200
        assert data["printed_content_pct"] == pytest.approx(0.4200, abs=1e-6)
        # adjusted = 214 / 504 == 0.4246 (4dp half-up)
        assert data["adjusted_content_pct"] == pytest.approx(0.4246, abs=1e-6)
        assert data["adjusted_content_pct"] != data["printed_content_pct"]
        # manufactured = 400 / (400 + 600) == 0.4000 (pending 1000.0 excluded)
        assert data["manufactured_products_pct"] == pytest.approx(0.4000, abs=1e-6)

    def test_submit_freezes_variants_with_single_domestic_lot(self, api):
        """PRD §3.7: "At submission three percentages are computed and frozen.
        First, `manufactured_products_pct`: the percentage of verified-lot cost
        from domestic origin across the attestation's period, aggregating only
        lots in `VERIFIED` status — lots in `PENDING_INSPECTION` or
        `QUARANTINED` are excluded."
        PRD §3.7: "The evaluation order is pinned — manufactured-products first,
        then printed, then adjusted — and all three percentages are carried at 4
        decimal places rounded half up."

        Design: Difficulty/dual_variant_calc/printed_vs_adjusted_content_pct
        """
        line = create_production_line()
        create_verified_lot(
            lot_code="LOT-US-100", component_type="SEMICONDUCTOR_FEEDSTOCK",
            country_of_origin="US", lot_cost_usd=100.0,
        )

        attestation = create_attestation(
            line,
            labor_cost_usd=100.0,
            feedstock_cost_usd=0.0,
            glass_cost_usd=0.0,
            balance_of_system_cost_usd=0.0,
            overhead_cost_usd=0.0,
            total_manufactured_cost_usd=400.0,
        )
        data = validate_success(api.submit_attestation(attestation["id"], CPL), 200)
        assert data["status"] == "SUBMITTED"
        # manufactured = 100 / 100 == 1.0000 (only verified domestic cost)
        assert data["manufactured_products_pct"] == pytest.approx(1.0000, abs=1e-6)
        # printed = 100 / 400 == 0.2500
        assert data["printed_content_pct"] == pytest.approx(0.2500, abs=1e-6)
        # adjusted = 104 / 404 == 0.2574 (4dp half-up)
        assert data["adjusted_content_pct"] == pytest.approx(0.2574, abs=1e-6)


class TestDeliveryParallelScheduleContentDims:
    """schedule_status and content_status evolve independently on one row."""

    def test_qualify_flips_content_only_then_patch_flips_schedule_only(self, api):
        """PRD §3.7: "On qualification the line's `qualification_tier` becomes
        `QUALIFIED`, and every delivery in `SCHEDULED` or `RESCHEDULED` whose
        reservation sits on this line and whose customer's `tax_credit_flag` is
        true has its `content_status` re-evaluated to `QUALIFIED_DOMESTIC`; the
        line's `version` increments."
        PRD §3.6: "Deliveries carry two independent state dimensions on the same
        row: `schedule_status` (`SCHEDULED`, `RESCHEDULED`, `DELIVERED`,
        `RECALLED`, `CANCELLED`) evolves through the actions above, while
        `content_status` (`UNEVALUATED`, `QUALIFIED_DOMESTIC`, `NON_QUALIFYING`)
        is mutated only by attestation side effects (§3.7) and by the
        lot-quarantine cascade (§3.5). Neither dimension blocks the other's
        transitions."

        Design: Difficulty/non_linear_state_machine/delivery_parallel_schedule_content_dims
        """
        scenario = setup_scheduled_delivery(
            volume_mw=2.0, customer_overrides={"tax_credit_flag": True}
        )
        customer, line, delivery = (
            scenario["customer"], scenario["line"], scenario["delivery"],
        )
        # US 400 + CN 600 verified lots -> manufactured_products_pct == 0.4000;
        # attestation 210/500 -> printed 0.4200: both thresholds met.
        create_verified_lot(
            lot_code="LOT-CN-600", component_type="FRAME",
            country_of_origin="CN", lot_cost_usd=600.0,
        )
        attestation = create_submitted_attestation(line)

        validate_success(
            api.adjudicate_attestation(attestation["id"], {"outcome": "QUALIFY"}, CPL),
            200,
        )
        after_qualify = get_delivery(delivery["id"])
        assert after_qualify["content_status"] == "QUALIFIED_DOMESTIC"
        assert after_qualify["schedule_status"] == "SCHEDULED", (
            "attestation adjudication must not touch the schedule dimension"
        )
        assert get_line(line["id"])["qualification_tier"] == "QUALIFIED"

        resp = api.reschedule_delivery(
            delivery["id"],
            {
                "scheduled_window_start": "2027-05-01T00:00:00Z",
                "scheduled_window_end": "2027-06-01T00:00:00Z",
            },
            make_customer_admin_headers(customer["id"]),
        )
        data = validate_success(resp, 200)
        assert data["schedule_status"] == "RESCHEDULED"
        assert data["content_status"] == "QUALIFIED_DOMESTIC", (
            "rescheduling must not touch the content dimension"
        )

    def test_qualify_sweep_reaches_rescheduled_deliveries(self, api):
        """PRD §3.7: "On qualification the line's `qualification_tier` becomes
        `QUALIFIED`, and every delivery in `SCHEDULED` or `RESCHEDULED` whose
        reservation sits on this line and whose customer's `tax_credit_flag` is
        true has its `content_status` re-evaluated to `QUALIFIED_DOMESTIC`; the
        line's `version` increments."

        Design: Difficulty/non_linear_state_machine/delivery_parallel_schedule_content_dims
        """
        scenario = setup_scheduled_delivery(
            volume_mw=2.0, customer_overrides={"tax_credit_flag": True}
        )
        customer, line, delivery = (
            scenario["customer"], scenario["line"], scenario["delivery"],
        )
        create_verified_lot(
            lot_code="LOT-CN-600", component_type="FRAME",
            country_of_origin="CN", lot_cost_usd=600.0,
        )
        # Reschedule BEFORE adjudication: the delivery sits in RESCHEDULED.
        resp = api.reschedule_delivery(
            delivery["id"],
            {
                "scheduled_window_start": "2027-05-01T00:00:00Z",
                "scheduled_window_end": "2027-06-01T00:00:00Z",
            },
            make_customer_admin_headers(customer["id"]),
        )
        rescheduled = validate_success(resp, 200)
        assert rescheduled["schedule_status"] == "RESCHEDULED"
        assert rescheduled["content_status"] == "UNEVALUATED"

        attestation = create_submitted_attestation(line)
        validate_success(
            api.adjudicate_attestation(attestation["id"], {"outcome": "QUALIFY"}, CPL),
            200,
        )
        after = get_delivery(delivery["id"])
        assert after["schedule_status"] == "RESCHEDULED"
        assert after["content_status"] == "QUALIFIED_DOMESTIC"
