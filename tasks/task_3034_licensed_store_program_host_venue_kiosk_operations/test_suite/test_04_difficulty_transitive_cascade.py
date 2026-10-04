"""Difficulty rule: transitive_cascade."""
from test_helpers import (
    ADMIN,
    api_client,
    create_member,
    create_product,
    set_clock,
    setup_failed_inspection,
    setup_operating_store,
    validate_success,
)
from test_helpers.fixtures import (
    add_assortment_item,
    create_approved_distributor,
    create_campaign,
    create_supply_order,
    drive_order_to_submitted,
)


class TestOverdueCorrectiveCascadeSuspendsAgreement:
    def _setup(self):
        """OPERATING store with one SUBMITTED order; FAILED inspection with two
        failing categories -> two OPEN corrective actions due 14 days after the
        completion timestamp (clock 2026-09-01 -> due 2026-09-15)."""
        set_clock()
        bundle = setup_operating_store()
        lic_id = bundle["licensee_id"]
        store_id = bundle["store"]["id"]
        product = create_product(unit_cost_cents=500, case_pack_units=1)
        add_assortment_item(store_id, lic_id, product["id"], par_level=50)
        distributor = create_approved_distributor()
        order = create_supply_order(
            store_id, lic_id, distributor["id"],
            lines=[{"product_item_id": product["id"], "quantity": 10}])
        order = drive_order_to_submitted(order, lic_id)
        # FAILED inspection, two categories below 70 -> two OPEN correctives
        from test_helpers.fixtures import schedule_inspection, complete_inspection, list_corrective_actions_for_inspection
        inspection = schedule_inspection(store_id)
        complete_inspection(
            inspection["id"],
            {"BEVERAGE_QUALITY": 60, "FOOD_SAFETY": 60,
             "BRAND_PRESENTATION": 90, "SERVICE_SPEED": 90},
        )
        actions = list_corrective_actions_for_inspection(inspection["id"])
        assert len(actions) == 2
        return bundle, order, actions

    def test_second_escalation_suspends_agreement_and_cascades(self):
        """PRD §3.8: "Each escalation increments the parent store's agreement's
        `breach_strikes` by 1 — and when that counter reaches 2, the agreement
        cascade of §3.2 fires: `ACTIVE → SUSPENDED`, stores `OPERATING →
        SUSPENDED`, their `DRAFT` and `SUBMITTED` orders cancelled, their
        `ACTIVE` campaigns ended."

        Design: Difficulty/transitive_cascade/overdue_corrective_cascade_suspends_agreement
        """
        bundle, order, actions = self._setup()
        set_clock("2026-09-17T00:00:00Z")  # past due_at (2026-09-15)
        validate_success(api_client.sweep_overdue_corrective_actions(ADMIN))
        for action in actions:
            refreshed = validate_success(api_client.get_corrective_action(action["id"], ADMIN))
            assert refreshed["status"] == "ESCALATED"
        agreement = validate_success(
            api_client.get_license_agreement(bundle["agreement"]["id"], ADMIN))
        assert agreement["breach_strikes"] == 2
        assert agreement["status"] == "SUSPENDED"
        store = validate_success(api_client.get_store(bundle["store"]["id"], ADMIN))
        assert store["operating_status"] == "SUSPENDED"
        order = validate_success(api_client.get_supply_order(order["id"], ADMIN))
        assert order["status"] == "CANCELLED"

    def test_first_escalation_increments_strikes_without_suspending(self):
        """PRD §3.2: "the system suspends it automatically the moment
        `breach_strikes` reaches the breach-suspension threshold of 2 — the
        cascade checks the agreement is `ACTIVE` at the instant it fires, so a
        manual suspension can never be doubled by a strike cascade."

        Design: Difficulty/transitive_cascade/overdue_corrective_cascade_suspends_agreement
        """
        bundle, order, actions = self._setup()
        # Resolve one corrective so only ONE remains overdue -> one strike only.
        from test_helpers import make_inspector_headers, make_licensee_manager_headers
        lic_headers = make_licensee_manager_headers(bundle["licensee_id"])
        first = actions[0]
        validate_success(api_client.submit_corrective_action_evidence(
            first["id"], {"evidence_note": "done"}, lic_headers))
        validate_success(api_client.verify_corrective_action(
            first["id"], make_inspector_headers("insp-B")))
        set_clock("2026-09-17T00:00:00Z")
        validate_success(api_client.sweep_overdue_corrective_actions(ADMIN))
        remaining = validate_success(api_client.get_corrective_action(actions[1]["id"], ADMIN))
        assert remaining["status"] == "ESCALATED"
        agreement = validate_success(
            api_client.get_license_agreement(bundle["agreement"]["id"], ADMIN))
        assert agreement["breach_strikes"] == 1
        assert agreement["status"] == "ACTIVE"
        order = validate_success(api_client.get_supply_order(order["id"], ADMIN))
        assert order["status"] == "SUBMITTED"


class TestCertificationExpiryCascadeCancelsCampaign:
    def _setup(self):
        """OPERATING store with exactly two CERTIFIED baristas certified at the
        default clock 2026-09-01 (expires_at 2027-09-01) and one PLANNED
        campaign."""
        set_clock()
        bundle = setup_operating_store()
        campaign = create_campaign(
            bundle["store"]["id"], start_date="2027-09-05", end_date="2027-09-20",
            discount_pct=20, floor_price_cents=500)
        return bundle, campaign

    def test_certification_expiry_drops_posture_and_cancels_planned_campaign(self):
        """PRD §3.6: "The expiry sweep thus has a long shadow — one lapsed
        certificate can drop a store to `PROBATION` and kill promotions that
        were awaiting activation."

        Design: Difficulty/transitive_cascade/certification_expiry_cascade_cancels_campaign
        """
        bundle, campaign = self._setup()
        set_clock("2027-09-02T00:00:00Z")  # past expires_at
        validate_success(api_client.sweep_certification_expiry(ADMIN))
        for cert in bundle.get("certifications", []):
            refreshed = validate_success(api_client.get_certification(cert["id"], ADMIN))
            assert refreshed["status"] == "EXPIRED"
        store = validate_success(api_client.get_store(bundle["store"]["id"], ADMIN))
        assert store["compliance_posture"] == "PROBATION"
        assert store["operating_status"] == "OPERATING"
        campaign = validate_success(api_client.get_promotion_campaign(campaign["id"], ADMIN))
        assert campaign["status"] == "CANCELLED"

    def test_certified_baristas_expire_together_via_sweep(self):
        """PRD §3.6: "Expiry is handled by a brand-run sweep: any certification
        still `CERTIFIED` whose `expires_at` is at or before the logical clock
        becomes `EXPIRED`, also terminal."

        Design: Difficulty/transitive_cascade/certification_expiry_cascade_cancels_campaign
        """
        bundle, _campaign = self._setup()
        # Still before expiry: sweep is a no-op for these certifications.
        validate_success(api_client.sweep_certification_expiry(ADMIN))
        store = validate_success(api_client.get_store(bundle["store"]["id"], ADMIN))
        assert store["compliance_posture"] == "GOOD_STANDING"
        # Advance past expiry and sweep again.
        set_clock("2027-09-02T00:00:00Z")
        validate_success(api_client.sweep_certification_expiry(ADMIN))
        store = validate_success(api_client.get_store(bundle["store"]["id"], ADMIN))
        assert store["compliance_posture"] == "PROBATION"
