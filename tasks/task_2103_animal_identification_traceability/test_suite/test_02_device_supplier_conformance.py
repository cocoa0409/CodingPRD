"""Device supplier vetting: conformance scoring, probation, suspension and reinstatement."""
from test_helpers import (
    ApiErrorId,
    DEFAULT_SERIAL_START,
    create_active_premises,
    create_tag_lot_payload,
    make_supplier_rep_headers,
    read_supplier,
    read_tag_lot,
    register_producer,
    register_supplier,
    reinstate_payload,
    setup_supplier_with_defects,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import make_program_admin_headers

ADMIN = make_program_admin_headers("admin-reg")


class TestConformanceScoring:
    def test_five_defects_against_four_thousand_devices_lands_exactly_on_probation_boundary(self, api):
        """PRD §3.2: "The first is defect density: the supplier's `defect_report_count` divided by the greater of 1.0 and its `issued_tag_count` expressed in thousands, giving defects per thousand devices issued."
        PRD §3.2: "The raw score is 100.00 less 12.0 multiplied by defects per thousand, less 20.0 multiplied by the shortfall of the retention rate below 1.0000; the result is clamped to lie no lower than 0.00 and no higher than 100.00, then rounded half up to two decimal places."
        PRD §3.2: "`probation` is true whenever `conformance_score` is strictly below 85.00, and probation is what attaches the issuance surcharge described in Section 3.3."
        PRD §3.2: "`issuance_cap` — the largest `quantity` permitted on a single new lot — is 10000 when the score is at least 95.00, 5000 when the score is at least 85.00 but below 95.00, 2000 when the score is at least 70.00 but below 85.00, and 0 when the score is below 70.00."

        Design: Corner/calculations/probation_boundary_at_exactly_eighty_five_leaves_supplier_off_probation
        """
        scenario = setup_supplier_with_defects(lot_quantity=4000, defect_count=5)
        supplier = scenario["supplier_after_defects"]

        assert supplier["conformance_score"] == 85.00, (
            "100.00 - 12.0 * (5 / 4.0) is exactly 85.00"
        )
        assert supplier["probation"] is False, "probation is strictly below 85.00, so 85.00 is off"
        assert supplier["issuance_cap"] == 5000
        assert supplier["status"] == "APPROVED"

    def test_reinstatement_lifts_the_score_and_approval_but_never_the_recalled_lot(self, api):
        """PRD §3.2: "A supplier that is `APPROVED` and whose recomputed score falls below 70.00 transitions to `SUSPENDED`; a supplier that is already `SUSPENDED` and whose recomputed score falls below 40.00 transitions to `REVOKED`, which is terminal — no further transition out of `REVOKED` is permitted."
        PRD §3.2: "Both of those transitions carry the same collateral consequence: every tag lot belonging to that supplier whose status is `ISSUED` or `ACTIVE` transitions to `RECALLED`."
        PRD §3.2: "Reinstatement by a `ProgramAdmin` is available only from `SUSPENDED` and requires a `forgiven_defects` count of at least 0 representing the corrective action credited to the manufacturer. The supplier's `defect_report_count` is reduced by that amount, floored at zero, and the conformance figures are re-derived; the supplier returns to `APPROVED` only if the recomputed `conformance_score` is at least 70.00."
        PRD §3.2: "Lots already recalled are **not** restored — they remain `RECALLED` permanently."

        Design: Corner/state_machines/supplier_reinstatement_restores_approval_but_not_recalled_lots
        """
        scenario = setup_supplier_with_defects(lot_quantity=4000, defect_count=11)
        suspended = scenario["supplier_after_defects"]
        assert suspended["conformance_score"] == 67.00, "100.00 - 12.0 * (11 / 4.0) is 67.00"
        assert suspended["status"] == "SUSPENDED"
        assert read_tag_lot(scenario["lot"]["id"])["status"] == "RECALLED"

        reinstated = validate_success(
            api.reinstate_device_supplier(
                scenario["supplier"]["id"], reinstate_payload(5), ADMIN
            )
        )
        assert reinstated["defect_report_count"] == 6, "11 defects less 5 forgiven"
        assert reinstated["conformance_score"] == 82.00, "100.00 - 12.0 * (6 / 4.0) is 82.00"
        assert reinstated["status"] == "APPROVED"
        assert reinstated["probation"] is True, "82.00 is strictly below 85.00"
        assert reinstated["issuance_cap"] == 2000

        assert read_tag_lot(scenario["lot"]["id"])["status"] == "RECALLED", (
            "a lot recalled by the suspension is never restored by reinstatement"
        )


class TestSupplierApprovalGatesIssuance:
    def test_lot_issuance_is_refused_while_the_supplier_is_still_pending_review(self, api):
        """PRD §2.5: "A lot's device supplier must be `APPROVED` to issue a lot or to apply or replace a tag, else `ERR_SUPPLIER_NOT_APPROVED`."
        PRD §3.3: "Both serial bounds must fall between 100000000000 and 999999999999 inclusive, and `serial_end` must not be lower than `serial_start`."
        PRD §3.3: "Issuance additionally requires the supplier to be `APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/lot_issuance_blocked_by_unapproved_supplier
        """
        producer = register_producer(legal_name="Willamette Cattle", state_code="OR")
        premises = create_active_premises(
            producer["id"], operation_type="COW_CALF", state_code="OR", capacity=40
        )
        supplier = register_supplier(company_name="Shearwell Data")
        assert supplier["status"] == "PENDING_REVIEW"

        payload = create_tag_lot_payload(
            supplier["id"],
            premises["id"],
            supplier["version"],
            serial_start=DEFAULT_SERIAL_START,
            quantity=100,
        )
        resp = api.create_tag_lot(payload, make_supplier_rep_headers(supplier["id"]))
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_APPROVED, expected_status=409)

    def test_refused_issuance_leaves_the_supplier_and_the_lot_collection_untouched(self, api):
        """PRD §2.5: "A lot's device supplier must be `APPROVED` to issue a lot or to apply or replace a tag, else `ERR_SUPPLIER_NOT_APPROVED`."
        PRD §2.5: "Rules are evaluated **strictly in ascending priority order**, the first failing rule alone decides the response, and no side effect of any kind is applied once a rule has failed."
        PRD §3.2: "The `issued_tag_count` sums the `quantity` of every lot belonging to the supplier whose status is `ISSUED`, `ACTIVE`, `DEPLETED` or `RECALLED`; voided lots are excluded entirely."

        Design: Difficulty/cross_entity_state_dependency/lot_issuance_blocked_by_unapproved_supplier
        """
        producer = register_producer(legal_name="Willamette Cattle", state_code="OR")
        premises = create_active_premises(
            producer["id"], operation_type="COW_CALF", state_code="OR", capacity=40
        )
        supplier = register_supplier(company_name="Shearwell Data")

        payload = create_tag_lot_payload(
            supplier["id"],
            premises["id"],
            supplier["version"],
            serial_start=DEFAULT_SERIAL_START,
            quantity=100,
        )
        resp = api.create_tag_lot(payload, make_supplier_rep_headers(supplier["id"]))
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_APPROVED, expected_status=409)

        after = read_supplier(supplier["id"])
        assert after["issued_tag_count"] == 0, "the refused lot must not be counted"
        assert after["status"] == "PENDING_REVIEW"

        rows, meta = validate_paginated(
            api.list_tag_lots(ADMIN, params={"supplier_id": supplier["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0
