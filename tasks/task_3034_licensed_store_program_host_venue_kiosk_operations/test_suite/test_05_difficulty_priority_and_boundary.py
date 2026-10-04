"""Difficulty rules: priority_pair_validation_conflict and boundary_precision_check."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    generate_statement,
    make_licensee_manager_headers,
    set_clock,
    setup_operating_store,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    add_assortment_item,
    create_approved_distributor,
    create_product,
    create_sales_report,
    create_supply_order,
    finalize_sales_report,
)
from test_helpers.test_users import make_inspector_headers


class TestStateBeatsFiscalOnOrderSubmit:
    def _setup(self):
        set_clock()
        bundle = setup_operating_store()
        lic_id = bundle["licensee_id"]
        store_id = bundle["store"]["id"]
        product = create_product(unit_cost_cents=500, case_pack_units=1)
        add_assortment_item(store_id, lic_id, product["id"], par_level=50)
        distributor = create_approved_distributor()
        validate_success(api_client.suspend_store(store_id, ADMIN))
        order = create_supply_order(
            store_id, lic_id, distributor["id"],
            lines=[{"product_item_id": product["id"], "quantity": 50000}])
        # PRD §3.5: quantity >= 100 earns discount_bps 500, so the total is
        # round_half_up(50000*500*9500/10000) = 23750000 > 20000000 budget ceiling
        assert order["total_cost_cents"] == 23750000
        return bundle, order

    def test_suspended_store_submit_reports_state_not_budget(self):
        """PRD §2.6: "then state preconditions (the per-machine checks such as
        `ERR_INVALID_AGREEMENT_STATE`, ... plus the operating-state gates
        `ERR_AGREEMENT_NOT_ACTIVE` and `ERR_STORE_NOT_OPERATING`), ... and
        finally fiscal rules (order budget, loyalty balance, dispute credit,
        and the optimistic-concurrency check)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_order_submit
        """
        bundle, order = self._setup()
        resp = api_client.submit_supply_order(
            order["id"], make_licensee_manager_headers(bundle["licensee_id"]))
        validate_error(resp, ApiErrorId.ERR_STORE_NOT_OPERATING.value)
        order = validate_success(api_client.get_supply_order(order["id"], ADMIN))
        assert order["status"] == "DRAFT"

    def test_operating_store_submit_reports_budget(self):
        """PRD §3.5: "It requires lines (an empty submission is
        `ERR_EMPTY_ORDER`), requires the store to be `OPERATING` (else
        `ERR_STORE_NOT_OPERATING`), requires the distributor's `approved` flag
        (else `ERR_DISTRIBUTOR_NOT_APPROVED`), and requires the total to fit
        within the per-order budget ceiling of 20000000 cents (else
        `ERR_ORDER_BUDGET_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_order_submit
        """
        set_clock()
        bundle = setup_operating_store()
        lic_id = bundle["licensee_id"]
        store_id = bundle["store"]["id"]
        product = create_product(unit_cost_cents=500, case_pack_units=1)
        add_assortment_item(store_id, lic_id, product["id"], par_level=50)
        distributor = create_approved_distributor()
        order = create_supply_order(
            store_id, lic_id, distributor["id"],
            lines=[{"product_item_id": product["id"], "quantity": 50000}])
        resp = api_client.submit_supply_order(
            order["id"], make_licensee_manager_headers(lic_id))
        validate_error(resp, ApiErrorId.ERR_ORDER_BUDGET_EXCEEDED.value)
        order = validate_success(api_client.get_supply_order(order["id"], ADMIN))
        assert order["status"] == "DRAFT"


class TestSafetyBeatsConstraintOnAssortmentAdd:
    def _setup(self):
        set_clock()
        bundle = setup_operating_store()
        product = create_product(
            category="MERCHANDISE", venue_type_restrictions=["AIRPORT"])
        return bundle, product

    def test_venue_gate_reported_not_par_shape(self):
        """PRD §2.6: "then business-safety gates (venue-type eligibility,
        proprietary-item posture, staffing floor, posture gates), then business
        constraints (uniqueness, shape/value sanity, footprint, empty-order,
        reopen cap)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_assortment_add
        """
        bundle, product = self._setup()
        resp = api_client.create_assortment_item(
            bundle["store"]["id"],
            {"product_item_id": product["id"], "par_level": 5000},
            make_licensee_manager_headers(bundle["licensee_id"]))
        validate_error(resp, ApiErrorId.ERR_VENUE_TYPE_PROHIBITED.value)

    def test_venue_gate_reported_at_valid_par(self):
        """PRD §3.4: "Venue eligibility: the product's `venue_type_restrictions`
        must be empty or contain the venue type of the store's venue, else
        `ERR_VENUE_TYPE_PROHIBITED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_assortment_add
        """
        bundle, product = self._setup()
        resp = api_client.create_assortment_item(
            bundle["store"]["id"],
            {"product_item_id": product["id"], "par_level": 10},
            make_licensee_manager_headers(bundle["licensee_id"]))
        validate_error(resp, ApiErrorId.ERR_VENUE_TYPE_PROHIBITED.value)


class TestRoyaltyTierBoundaryExactThreshold:
    def _setup(self, net_cents):
        set_clock()
        bundle = setup_operating_store(
            agreement_overrides={
                "royalty_tiers": [
                    {"threshold_cents": 0, "rate_bps": 300},
                    {"threshold_cents": 50000000, "rate_bps": 350},
                ],
            }
        )
        report = create_sales_report(
            bundle["store"]["id"], bundle["licensee_id"],
            period_start_date="2026-09-01", period_end_date="2026-09-30",
            gross_sales_cents=net_cents, returns_cents=0, loyalty_redemption_cents=0)
        finalize_sales_report(report["id"], bundle["licensee_id"])
        return bundle

    def test_recognized_sales_exactly_at_tier_threshold(self):
        """PRD §3.7: "The statement's `royalty_amount_cents` applies the tier
        table marginally to the recognized figure: for each tier, take the
        portion of recognized sales falling between that tier's `threshold_cents`
        and the next tier's threshold (unbounded for the last tier) — never
        less than zero — multiply by the tier's `rate_bps` over the 10000
        denominator, sum all tier products unrounded, and apply a single
        round-half-up to the total for integer cents."

        Design: Difficulty/boundary_precision_check/royalty_tier_boundary_exact_threshold
        """
        bundle = self._setup(50000000)
        stmt = generate_statement(
            bundle["agreement"]["id"],
            period_start_date="2026-09-01", period_end_date="2026-09-30")
        assert stmt["recognized_sales_cents"] == 50000000
        assert stmt["royalty_amount_cents"] == 1500000

    def test_recognized_sales_one_cent_over_tier_threshold(self):
        """PRD §3.7: "The statement's `royalty_amount_cents` applies the tier
        table marginally to the recognized figure: for each tier, take the
        portion of recognized sales falling between that tier's `threshold_cents`
        and the next tier's threshold (unbounded for the last tier) — never
        less than zero — multiply by the tier's `rate_bps` over the 10000
        denominator, sum all tier products unrounded, and apply a single
        round-half-up to the total for integer cents."

        Design: Difficulty/boundary_precision_check/royalty_tier_boundary_exact_threshold
        """
        bundle = self._setup(50000001)
        stmt = generate_statement(
            bundle["agreement"]["id"],
            period_start_date="2026-09-01", period_end_date="2026-09-30")
        assert stmt["recognized_sales_cents"] == 50000001
        # 1500000 + round_half_up(0.035) = 1500000 (single round at the end)
        assert stmt["royalty_amount_cents"] == 1500000


class TestCertificationExamExactPassThreshold:
    def _two_enrolled_certs(self):
        from test_helpers import (
            create_certification_payload,
            create_employee_payload,
            create_licensee_payload,
        )
        licensee = validate_success(
            api_client.create_licensee(create_licensee_payload(), ADMIN),
            expected_status=201)
        lic_headers = make_licensee_manager_headers(licensee["id"])
        certs = []
        for _ in range(2):
            emp = validate_success(api_client.create_employee(
                licensee["id"], create_employee_payload(), lic_headers),
                expected_status=201)
            cert = validate_success(api_client.create_certification(
                emp["id"], create_certification_payload(), lic_headers),
                expected_status=201)
            certs.append(cert)
        return certs

    def test_score_80_passes_and_79_fails(self):
        """PRD §3.6: "The pass line is 80, inclusive — but the flag changes the
        arithmetic: when `proctor_anomaly` is false the raw score is compared
        to 80; when true, an anomaly penalty of 5 points is subtracted first,
        and the adjusted score is compared to 80."

        Design: Difficulty/boundary_precision_check/certification_exam_exact_pass_threshold
        """
        certs = self._two_enrolled_certs()
        proctor = make_inspector_headers("insp-P")
        passed = validate_success(api_client.record_certification_exam(
            certs[0]["id"], {"exam_score": 80, "proctor_anomaly": False}, proctor))
        failed = validate_success(api_client.record_certification_exam(
            certs[1]["id"], {"exam_score": 79, "proctor_anomaly": False}, proctor))
        assert passed["status"] == "EXAM_PASSED"
        assert failed["status"] == "ENROLLED"
        assert failed["exam_attempts"] == 1

    def test_failing_attempt_can_be_retaken(self):
        """PRD §3.6: "A passing outcome moves the certification to
        `EXAM_PASSED`; a failing one leaves it `ENROLLED`, free to be examined
        again."

        Design: Difficulty/boundary_precision_check/certification_exam_exact_pass_threshold
        """
        certs = self._two_enrolled_certs()
        proctor = make_inspector_headers("insp-P")
        failed = validate_success(api_client.record_certification_exam(
            certs[0]["id"], {"exam_score": 79, "proctor_anomaly": False}, proctor))
        assert failed["status"] == "ENROLLED"
        passed = validate_success(api_client.record_certification_exam(
            certs[0]["id"], {"exam_score": 80, "proctor_anomaly": False}, proctor))
        assert passed["status"] == "EXAM_PASSED"
        assert passed["exam_attempts"] == 2
