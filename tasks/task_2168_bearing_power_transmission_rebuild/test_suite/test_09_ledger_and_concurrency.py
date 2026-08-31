# -*- coding: utf-8 -*-
"""The credit ledger's conservation invariant and the three stale-view guards."""
import pytest

from test_helpers import (
    ADMIN_1, ONE_BAND, PLANNER_1, ApiErrorId, api_client as api, asset_version,
    create_core, credit_notes, customer_version, order_version, post_manual_note,
    create_customer, create_standard, read_credit_note, read_customer, read_order,
    setup_shop, validate_error,
    validate_paginated, validate_success, void_note,
)


class TestCreditLedgerConservation:

    def _ledger_world(self):
        return setup_shop(account_code="LED-001", customer_name="Ledger Works",
                          model_code="LEDGER-SPEC-1", serial_no="SN-LED-1",
                          rebuild_count=1, declared_condition_grade="GRADE_D",
                          with_asset=False, with_order=False)

    def test_a_manual_adjustment_moves_only_its_own_stream_and_the_total(self):
        """PRD 3.1: "A `ShopAdmin` may also move an account's ledger directly, posting a manual
        adjustment with an `amount_cents` of at least zero and a free-text `memo`, guarded by
        `expected_customer_version` as described in §2.7."
        PRD 3.1: "The resulting note is created with `kind` of `MANUAL_ADJUSTMENT` and `status`
        of `POSTED`, the account's four balances are recomputed, and the account's `version`
        advances."
        PRD 2.9: "`manual_credit_balance_cents` the same sum restricted to `kind` of
        `MANUAL_ADJUSTMENT`; and `total_credit_balance_cents` is the sum of those three."

        Design: Difficulty/compensating_invariant/credit_note_issue_then_void_conserves_customer_ledger_total
        """
        world = self._ledger_world()
        cust_id = world["customer"]["id"]
        assert read_customer(cust_id)["total_credit_balance_cents"] == 10800

        note = post_manual_note(cust_id, 50000, memo="goodwill freight credit")
        assert note["kind"] == "MANUAL_ADJUSTMENT"
        assert note["status"] == "POSTED"

        customer = read_customer(cust_id)
        assert customer["manual_credit_balance_cents"] == 50000
        assert customer["core_credit_balance_cents"] == 10800
        assert customer["total_credit_balance_cents"] == 60800

    def test_voiding_the_note_returns_the_total_to_exactly_its_prior_value(self):
        """PRD 2.9: "A customer's four balance fields — `core_credit_balance_cents`,
        `warranty_credit_balance_cents`, `manual_credit_balance_cents` and
        `total_credit_balance_cents` — are always recomputed in full from that customer's
        surviving `POSTED` notes, never adjusted by a delta."
        PRD 2.9: "Notes whose `status` is `VOID` contribute nothing to any stream, which is
        exactly what makes issue-then-void conservative to the cent."

        Design: Difficulty/compensating_invariant/credit_note_issue_then_void_conserves_customer_ledger_total
        """
        world = self._ledger_world()
        cust_id = world["customer"]["id"]
        before = read_customer(cust_id)["total_credit_balance_cents"]
        assert before == 10800

        note = post_manual_note(cust_id, 50000, memo="goodwill freight credit")
        assert read_customer(cust_id)["total_credit_balance_cents"] == 60800

        voided = void_note(note["id"], "issued against the wrong account")
        assert voided["status"] == "VOID"
        assert voided["voided_at"] is not None

        after = read_customer(cust_id)
        assert after["manual_credit_balance_cents"] == 0
        assert after["core_credit_balance_cents"] == 10800
        assert after["total_credit_balance_cents"] == before, (
            "issue then void is conservative to the cent"
        )

        _, meta = credit_notes(customer_id=cust_id, status="POSTED")
        assert meta["total_count"] == 1

    def test_a_manual_note_that_would_breach_the_ceiling_is_refused(self):
        """PRD 3.1: "Manual generosity has a ceiling: the shop will not let an account's
        `total_credit_balance_cents` stand above 2,000,000 cents, so an adjustment is rejected
        with `ERR_CREDIT_CAP_EXCEEDED` when the balance the account *would* hold after the note
        was posted exceeds that figure. The projected post-posting total is what is tested, not
        the balance before."

        Design: Corner/errors/manual_credit_above_the_customer_ceiling_is_rejected
        """
        world = setup_shop(account_code="CEI-001", customer_name="Ceiling Mill",
                           serial_no="SN-CEI-1", rebuild_count=1,
                           declared_condition_grade="GRADE_D",
                           with_asset=False, with_order=False)
        cust_id = world["customer"]["id"]
        v1 = customer_version(cust_id)

        validate_error(api.create_manual_credit_note(cust_id, {
            "amount_cents": 1989201, "memo": "one cent too far",
            "expected_customer_version": v1}, ADMIN_1),
            ApiErrorId.ERR_CREDIT_CAP_EXCEEDED.value, 422)
        assert customer_version(cust_id) == v1, (
            "the refused note left the account untouched, so v1 is still current"
        )

        note = validate_success(api.create_manual_credit_note(cust_id, {
            "amount_cents": 1989200, "memo": "exactly on the ceiling",
            "expected_customer_version": v1}, ADMIN_1), 201)
        assert note["kind"] == "MANUAL_ADJUSTMENT"
        assert read_customer(cust_id)["total_credit_balance_cents"] == 2000000

        _, meta = credit_notes(customer_id=cust_id, status="POSTED")
        assert meta["total_count"] == 2


class TestOptimisticConcurrency:

    def test_a_stale_order_version_blocks_a_second_part_line_creation(self):
        """PRD 2.7: "Adding a part line to a rebuild order requires `expected_order_version` in
        the request body. It is a mandatory field, not an optional one. Its value must equal the
        current `version` of the `RebuildOrder` named in the path. If any other writer has
        advanced that order's `version` since the client last read it, the creation is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."
        PRD 3.7: "Creating the line increments the order's `part_revision_counter` by 1,
        re-derives the order's `approval_status`, and increments the order's `version` by 1."

        Design: Corner/cross_cutting_layers/occ_stale_order_version_rejects_a_second_part_line_create
        """
        world = setup_shop(account_code="OCC-001", customer_name="OCC Mill",
                           asset_tag="OCC-01-GBX", serial_no="SN-OCC-1",
                           declared_condition_grade="GRADE_B", labor_hours=4.0)
        order_id = world["order"]["id"]
        v_stale = order_version(order_id)

        validate_success(api.create_part_line(order_id, {
            "part_no": "BRG-22324", "source_class": "OEM", "qty": 1,
            "unit_cost_cents": 40000, "expected_order_version": v_stale}, PLANNER_1), 201)
        assert order_version(order_id) > v_stale

        validate_error(api.create_part_line(order_id, {
            "part_no": "SEAL-9", "source_class": "OEM", "qty": 1,
            "unit_cost_cents": 5000, "expected_order_version": v_stale}, PLANNER_1),
            ApiErrorId.ERR_STALE_VERSION.value, 412)
        assert read_order(order_id)["part_revision_counter"] == 1

        v_fresh = order_version(order_id)
        validate_success(api.create_part_line(order_id, {
            "part_no": "SEAL-9", "source_class": "OEM", "qty": 1,
            "unit_cost_cents": 5000, "expected_order_version": v_fresh}, PLANNER_1), 201)

        _, meta = validate_paginated(api.list_part_lines(order_id, PLANNER_1))
        assert meta["total_count"] == 2

    def test_a_stale_customer_version_blocks_a_manual_ledger_adjustment(self):
        """PRD 2.7: "Posting a manual ledger adjustment against an account requires
        `expected_customer_version`, likewise mandatory, and likewise compared against the
        current `version` of the `Customer` named in the path; a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD 2.9: "Every recomputation of the four balances increments that `Customer` record's
        `version` by 1."

        Design: Corner/cross_cutting_layers/occ_stale_customer_version_rejects_a_manual_credit_note
        """
        customer = create_customer(name="Ledger OCC Mill", account_code="OCC-002")
        standard = create_standard(feature_bands=ONE_BAND)
        cust_id, std_id = customer["id"], standard["id"]
        cv_stale = customer_version(cust_id)

        create_core(cust_id, std_id, serial_no="SN-OCC-2", rebuild_count=1,
                    declared_condition_grade="GRADE_D")
        assert customer_version(cust_id) > cv_stale

        validate_error(api.create_manual_credit_note(cust_id, {
            "amount_cents": 5000, "memo": "computed against a stale balance",
            "expected_customer_version": cv_stale}, ADMIN_1),
            ApiErrorId.ERR_STALE_VERSION.value, 412)
        assert read_customer(cust_id)["total_credit_balance_cents"] == 10800

        cv_fresh = customer_version(cust_id)
        note = validate_success(api.create_manual_credit_note(cust_id, {
            "amount_cents": 5000, "memo": "re-posted against the fresh balance",
            "expected_customer_version": cv_fresh}, ADMIN_1), 201)
        assert note["kind"] == "MANUAL_ADJUSTMENT"

        customer = read_customer(cust_id)
        assert customer["manual_credit_balance_cents"] == 5000
        assert customer["total_credit_balance_cents"] == 15800

    def test_a_stale_asset_version_pre_empts_the_delivery_gate_on_installation(self):
        """PRD 2.7: "Creating an installation requires `expected_asset_version`, mandatory,
        compared against the current `version` of the `CustomerAsset` identified by the body's
        `customer_asset_id`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD 2.8: "A stale-version rejection at step 8 pre-empts every state check at step 9, so
        a client holding an out-of-date order version learns that fact before it learns the
        order is in the wrong state."
        PRD 3.9: "The unit must genuinely be finished and matched: the core's `status` must be
        `SHIPPED`, the order's `work_status` must be `DELIVERED`, and the order's own core and
        asset references must agree with the body's, failing any of which the attempt is
        `ERR_UNIT_NOT_DELIVERED` (HTTP 409)"

        Design: Corner/cross_cutting_layers/occ_stale_asset_version_rejects_an_installation
        """
        world = setup_shop(account_code="OCC-003", customer_name="Asset OCC Mill",
                           asset_tag="OCC-03-GBX", serial_no="SN-OCC-3",
                           declared_condition_grade="GRADE_B", labor_hours=4.0)
        core_id, asset_id, order_id = (world["core"]["id"], world["asset"]["id"],
                                       world["order"]["id"])
        av = asset_version(asset_id)

        validate_error(api.create_installation({
            "core_unit_id": core_id, "customer_asset_id": asset_id,
            "rebuild_order_id": order_id, "expected_asset_version": av - 1}, ADMIN_1),
            ApiErrorId.ERR_STALE_VERSION.value, 412)

        validate_error(api.create_installation({
            "core_unit_id": core_id, "customer_asset_id": asset_id,
            "rebuild_order_id": order_id, "expected_asset_version": av}, ADMIN_1),
            ApiErrorId.ERR_UNIT_NOT_DELIVERED.value, 409)

        assert asset_version(asset_id) == av, "neither rejection advanced the asset"
        _, meta = validate_paginated(api.list_installations(
            ADMIN_1, params={"customer_asset_id": asset_id}))
        assert meta["total_count"] == 0
