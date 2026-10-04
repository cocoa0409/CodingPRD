"""Programs, protocols, purchase orders — workflow, SoD, budget ledger, integrity.

Covers difficulty instances: protocol_draft_review_cycle,
program_sourcing_requires_active_protocol, measurement_requires_sample_in_lab,
po_place_cancel_budget_invariant, ready_blocks_state_vs_safety_pair,
po_place_state_vs_budget_pair — and corner instances:
protocol_terminal_retired_lockdown, po_verify_requires_distinct_officer,
sod_program_approve_same_actor, sod_po_verify_placer_rejected,
sourcing_integrity_manufacturer_direct, protocol_weights_sum_boundary,
program_get_not_found, measurement_immutable_no_version,
segregation_of_duties_full_chain, cascade_order_place_receive_sourcing.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_measurement,
    create_product_category_payload, create_lab_protocol_payload,
    create_purchase_order_payload, create_po_line_payload,
    create_measurement_payload,
    create_category, create_program, create_active_protocol, approve_program,
    create_sample, setup_category_program_protocol_sample, setup_program_sourcing,
    setup_program_testing, create_verified_po,
    TEST_USERS,
    make_lab_manager_headers, make_editorial_director_headers,
    make_purchasing_agent_headers, make_compliance_officer_headers,
)

LM = TEST_USERS["lab_manager_headers"]
MO = TEST_USERS["methodology_officer_headers"]
PA = TEST_USERS["purchasing_agent_headers"]
CO = TEST_USERS["compliance_officer_headers"]
LT = TEST_USERS["lab_technician_headers"]
ED = TEST_USERS["editorial_director_headers"]


class TestProgramLifecycle:
    def test_program_get_not_found(self, api):
        """PRD §2.5: "Existence — path-templated resources exist, checked left to right along the URL; failure yields `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/program_get_not_found
        """
        resp = api.get_test_program(NON_EXISTENT_UUID, LM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_sod_program_approve_same_actor(self, api):
        """PRD §3.2: "the approver's `X-User-ID` must differ from `proposed_by_user_id`, or the request is rejected with `ERR_SOD_VIOLATION`."

        Design: Corner/validations/sod_program_approve_same_actor
        """
        category = create_category(name="Dryers", market_share_pct=20, member_interest_pct=20)
        program = create_program(category["id"], proposer_id="lm-1")
        resp = api.transition_test_program(
            program["id"], {"action": "approve"},
            make_editorial_director_headers("lm-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        resp = api.transition_test_program(
            program["id"], {"action": "approve"},
            make_editorial_director_headers("ed-2"),
        )
        data = validate_success(resp)
        assert data["status"] == "APPROVED"
        assert data["approved_by_user_id"] == "ed-2"

    def test_start_sourcing_requires_active_protocol(self, api):
        """PRD §3.2: "Starting sourcing (`APPROVED → SAMPLE_SOURCING`) requires at least one `TestSample` planned for the program and an `ACTIVE` laboratory protocol for the program's category".

        Design: Difficulty/cross_entity_state_dependency/program_sourcing_requires_active_protocol
        """
        category = create_category(name="Dryers", market_share_pct=20, member_interest_pct=20)
        program = create_program(category["id"], proposer_id="lm-1")
        # protocol created but only pushed to IN_REVIEW, never activated
        resp = api.create_lab_protocol(
            create_lab_protocol_payload(category["id"], protocol_code="DRY-01",
                                        measurement_repeat_min=1,
                                        perf_weight_pct=50, reliability_weight_pct=25),
            LM,
        )
        proto = get_success_data(resp)
        validate_success(api.transition_lab_protocol(proto["id"], {"action": "submit_review"}, LM))
        program = approve_program(program, approver_id="ed-1")
        create_sample(program["id"], model_label="Dry1", required_units=1)
        resp = api.transition_test_program(program["id"], {"action": "start_sourcing"}, LM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        proto_now = get_success_data(api.get_lab_protocol(proto["id"], LM))
        assert proto_now["status"] == "IN_REVIEW"

    def test_start_sourcing_requires_at_least_one_sample(self, api):
        """PRD §3.2: "Starting sourcing (`APPROVED → SAMPLE_SOURCING`) requires at least one `TestSample` planned for the program and an `ACTIVE` laboratory protocol for the program's category".

        Design: Difficulty/cross_entity_state_dependency/program_sourcing_requires_active_protocol
        """
        category = create_category(name="Dryers", market_share_pct=20, member_interest_pct=20)
        program = create_program(category["id"])
        create_active_protocol(category, protocol_code="DRY-01",
                               measurement_repeat_min=1,
                               perf_weight_pct=50, reliability_weight_pct=25)
        program = approve_program(program)
        # no sample created
        resp = api.transition_test_program(program["id"], {"action": "start_sourcing"}, LM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestProtocolLifecycle:
    def test_protocol_draft_review_cycle(self, api):
        """PRD §3.4: "the `LabManager` submits a `DRAFT` protocol into `IN_REVIEW`; a `MethodologyOfficer` may return it to `DRAFT`, or activate it."

        Design: Difficulty/non_linear_state_machine/protocol_draft_review_cycle
        """
        category = create_category(name="Dryers", market_share_pct=20, member_interest_pct=20)
        resp = api.create_lab_protocol(
            create_lab_protocol_payload(category["id"], protocol_code="DRY-01",
                                        measurement_repeat_min=1,
                                        perf_weight_pct=50, reliability_weight_pct=25),
            LM,
        )
        proto = get_success_data(resp)
        assert proto["status"] == "DRAFT"
        validate_success(api.transition_lab_protocol(proto["id"], {"action": "submit_review"}, LM))
        data = validate_success(api.transition_lab_protocol(proto["id"], {"action": "return_draft"}, MO))
        assert data["status"] == "DRAFT"
        data = validate_success(api.transition_lab_protocol(proto["id"], {"action": "submit_review"}, LM))
        assert data["status"] == "IN_REVIEW"
        # loop repeats: return to DRAFT again
        data = validate_success(api.transition_lab_protocol(proto["id"], {"action": "return_draft"}, MO))
        assert data["status"] == "DRAFT"

    def test_protocol_terminal_retired_lockdown(self, api):
        """PRD §3.4: "Retirement is allowed from `DRAFT` or `ACTIVE`, but an `ACTIVE` protocol can be retired only when no program of its category is in `SAMPLE_SOURCING`, `TESTING`, or `SCORING`; `RETIRED` is terminal."
        PRD §2.5: "State — the target resource is in a valid from-state for the requested action and the action name itself is known; failure yields `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/protocol_terminal_retired_lockdown
        """
        category = create_category(name="Dryers", market_share_pct=20, member_interest_pct=20)
        resp = api.create_lab_protocol(
            create_lab_protocol_payload(category["id"], protocol_code="DRY-01",
                                        measurement_repeat_min=1,
                                        perf_weight_pct=50, reliability_weight_pct=25),
            LM,
        )
        proto = get_success_data(resp)
        validate_success(api.transition_lab_protocol(proto["id"], {"action": "retire"}, MO))
        resp = api.transition_lab_protocol(proto["id"], {"action": "submit_review"}, LM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        proto_now = get_success_data(api.get_lab_protocol(proto["id"], MO))
        assert proto_now["status"] == "RETIRED"

    def test_protocol_weights_sum_boundary(self, api):
        """PRD §3.4: "two scoring weights: `perf_weight_pct` and `reliability_weight_pct`, each an integer from 1 to 98 whose sum must not exceed 99, so that the computed `convenience_weight_pct` — one hundred minus the two supplied weights — is always at least 1. Violations of the weight arithmetic, of the minimum repeat count, or of `protocol_code` uniqueness within the category among protocols in `DRAFT`, `IN_REVIEW`, or `ACTIVE` status are rejected with `ERR_PROTOCOL_WEIGHTS`".

        Design: Corner/validations/protocol_weights_sum_boundary
        """
        category = create_category(name="Dryers", market_share_pct=20, member_interest_pct=20)
        # 60 + 40 = 100 -> convenience 0 -> rejected
        resp = api.create_lab_protocol(
            create_lab_protocol_payload(category["id"], protocol_code="DRY-100",
                                        measurement_repeat_min=1,
                                        perf_weight_pct=60, reliability_weight_pct=40),
            LM,
        )
        validate_error(resp, ApiErrorId.ERR_PROTOCOL_WEIGHTS)
        # 60 + 39 = 99 -> convenience 1 -> accepted
        resp = api.create_lab_protocol(
            create_lab_protocol_payload(category["id"], protocol_code="DRY-99",
                                        measurement_repeat_min=1,
                                        perf_weight_pct=60, reliability_weight_pct=39),
            LM,
        )
        data = validate_success(resp, expected_status=201)
        assert data["convenience_weight_pct"] == 1

    def test_protocol_duplicate_live_code_rejected(self, api):
        """PRD §3.4: "Violations of the weight arithmetic, of the minimum repeat count, or of `protocol_code` uniqueness within the category among protocols in `DRAFT`, `IN_REVIEW`, or `ACTIVE` status are rejected with `ERR_PROTOCOL_WEIGHTS`".

        Design: Corner/validations/protocol_weights_sum_boundary
        """
        category = create_category(name="Dryers", market_share_pct=20, member_interest_pct=20)
        validate_success(api.create_lab_protocol(
            create_lab_protocol_payload(category["id"], protocol_code="DRY-01",
                                        measurement_repeat_min=1,
                                        perf_weight_pct=50, reliability_weight_pct=25),
            LM,
        ), expected_status=201)
        resp = api.create_lab_protocol(
            create_lab_protocol_payload(category["id"], protocol_code="DRY-01",
                                        measurement_repeat_min=2,
                                        perf_weight_pct=40, reliability_weight_pct=30),
            LM,
        )
        validate_error(resp, ApiErrorId.ERR_PROTOCOL_WEIGHTS)


class TestPurchaseOrderWorkflow:
    def test_sourcing_integrity_manufacturer_direct(self, api):
        """PRD §3.3: "The `retailer_name` must not name a manufacturer-direct channel — that is, it must neither end with the suffix `-direct` nor equal the brand manufacturer's name — and the `buyer_alias` must not equal a manufacturer name. Violations are rejected with `ERR_SOURCING_INTEGRITY`."

        Design: Corner/validations/sourcing_integrity_manufacturer_direct
        """
        ctx = setup_program_sourcing(category_name="Mowers", protocol_code="MOW-01",
                                     model_label="Mow1", market_share_pct=30,
                                     member_interest_pct=30, refresh_cycle_months=36)
        resp = api.create_purchase_order(
            create_purchase_order_payload(
                ctx["program"]["id"],
                [create_po_line_payload(ctx["sample"]["id"], unit_price_cents=1000)],
                buyer_alias="alias-a", retailer_name="Acme-direct",
                receipt_doc_ref="RA", shipping_cents=0,
            ),
            PA,
        )
        validate_error(resp, ApiErrorId.ERR_SOURCING_INTEGRITY)

    def test_sod_po_verify_placer_rejected(self, api):
        """PRD §3.3: "the verifier's `X-User-ID` must differ from `placed_by_user_id` (`ERR_SOD_VIOLATION` otherwise)".

        Design: Corner/validations/sod_po_verify_placer_rejected
        """
        ctx = setup_program_sourcing(category_name="Mowers", protocol_code="MOW-01",
                                     model_label="Mow1", market_share_pct=30,
                                     member_interest_pct=30, refresh_cycle_months=36)
        resp = api.create_purchase_order(
            create_purchase_order_payload(
                ctx["program"]["id"],
                [create_po_line_payload(ctx["sample"]["id"], unit_price_cents=1000)],
                buyer_alias="alias-a", retailer_name="ToolMart", receipt_doc_ref="RA",
            ),
            PA,
        )
        po = get_success_data(resp)
        validate_success(api.transition_purchase_order(
            po["id"], {"action": "place"}, make_purchasing_agent_headers("pa-1")))
        validate_success(api.transition_purchase_order(
            po["id"], {"action": "receive"}, make_purchasing_agent_headers("pa-1")))
        resp = api.transition_purchase_order(
            po["id"], {"action": "verify"}, make_compliance_officer_headers("pa-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        po_now = get_success_data(api.get_purchase_order(po["id"], CO))
        assert po_now["status"] == "RECEIVED"

    def test_po_verify_success_then_terminal_lockdown(self, api):
        """PRD §3.3: "The verifier is stamped into `verified_by_user_id`. `VERIFIED` and `CANCELLED` are the order's terminal states."
        PRD §2.5: "State — the target resource is in a valid from-state for the requested action and the action name itself is known; failure yields `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/po_verify_requires_distinct_officer
        """
        ctx = setup_program_sourcing(category_name="Mowers", protocol_code="MOW-01",
                                     model_label="Mow1", market_share_pct=30,
                                     member_interest_pct=30, refresh_cycle_months=36)
        resp = api.create_purchase_order(
            create_purchase_order_payload(
                ctx["program"]["id"],
                [create_po_line_payload(ctx["sample"]["id"], unit_price_cents=1000)],
                buyer_alias="alias-a", retailer_name="ToolMart", receipt_doc_ref="RA",
            ),
            PA,
        )
        po = get_success_data(resp)
        validate_success(api.transition_purchase_order(
            po["id"], {"action": "place"}, make_purchasing_agent_headers("pa-1")))
        validate_success(api.transition_purchase_order(
            po["id"], {"action": "receive"}, make_purchasing_agent_headers("pa-1")))
        data = validate_success(api.transition_purchase_order(
            po["id"], {"action": "verify"}, make_compliance_officer_headers("co-9")))
        assert data["status"] == "VERIFIED"
        assert data["verified_by_user_id"] == "co-9"
        # VERIFIED is terminal: a second verify is rejected
        resp = api.transition_purchase_order(
            po["id"], {"action": "verify"}, make_compliance_officer_headers("co-10"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_place_then_cancel_restores_committed_cents(self, api):
        """PRD §3.3: "cancelling a `PLACED` order subtracts its `total_cents` from `committed_cents` as a compensating ledger entry, while cancelling a `DRAFT` order touches nothing."
        PRD §3.3: "On placement the logical clock is stamped into `placed_at`, the actor into `placed_by_user_id`, the order's `total_cents` is added to the program's `committed_cents`, and the program's `version` bumps."

        Design: Difficulty/compensating_invariant/po_place_cancel_budget_invariant
        """
        ctx = setup_program_sourcing(category_name="Mowers", protocol_code="MOW-01",
                                     model_label="Mow1", market_share_pct=30,
                                     member_interest_pct=30, refresh_cycle_months=36)
        resp = api.create_purchase_order(
            create_purchase_order_payload(
                ctx["program"]["id"],
                [create_po_line_payload(ctx["sample"]["id"], unit_price_cents=1000)],
                buyer_alias="alias-a", retailer_name="ToolMart", receipt_doc_ref="RA",
            ),
            PA,
        )
        po = get_success_data(resp)
        validate_success(api.transition_purchase_order(
            po["id"], {"action": "place"}, make_purchasing_agent_headers("pa-1")))
        prog = get_success_data(api.get_test_program(ctx["program"]["id"], LM))
        assert prog["committed_cents"] == 1000
        validate_success(api.transition_purchase_order(
            po["id"], {"action": "cancel"}, make_purchasing_agent_headers("pa-1")))
        prog = get_success_data(api.get_test_program(ctx["program"]["id"], LM))
        assert prog["committed_cents"] == 0

    def test_draft_cancel_touches_nothing(self, api):
        """PRD §3.3: "cancelling a `PLACED` order subtracts its `total_cents` from `committed_cents` as a compensating ledger entry, while cancelling a `DRAFT` order touches nothing."

        Design: Difficulty/compensating_invariant/po_place_cancel_budget_invariant
        """
        ctx = setup_program_sourcing(category_name="Mowers", protocol_code="MOW-02",
                                     model_label="Mow2", market_share_pct=30,
                                     member_interest_pct=30, refresh_cycle_months=36)
        resp = api.create_purchase_order(
            create_purchase_order_payload(
                ctx["program"]["id"],
                [create_po_line_payload(ctx["sample"]["id"], unit_price_cents=1000)],
                buyer_alias="alias-d", retailer_name="ToolMart", receipt_doc_ref="RD",
            ),
            PA,
        )
        po = get_success_data(resp)
        data = validate_success(api.transition_purchase_order(
            po["id"], {"action": "cancel"}, make_purchasing_agent_headers("pa-1")))
        assert data["status"] == "CANCELLED"
        prog = get_success_data(api.get_test_program(ctx["program"]["id"], LM))
        assert prog["committed_cents"] == 0

    def test_place_state_vs_budget_priority_pair(self, api):
        """PRD §2.5: "Because the state check (priority 4) precedes every business check, an action attempted from the wrong state always surfaces `ERR_INVALID_STATE` even when a business rule would also reject it".
        PRD §3.3: "the order's `total_cents` must not exceed the program's remaining budget, defined as `budget_cents` minus `committed_cents`, or the request is rejected with `ERR_BUDGET_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/po_place_state_vs_budget_pair
        """
        ctx = setup_program_sourcing(category_name="Mowers", protocol_code="MOW-01",
                                     model_label="Mow1", budget_cents=1000,
                                     market_share_pct=30, member_interest_pct=30,
                                     refresh_cycle_months=36)
        pa_headers = make_purchasing_agent_headers("pa-1")
        # PO-A total 1000: place + receive (committed 1000)
        resp = api.create_purchase_order(
            create_purchase_order_payload(
                ctx["program"]["id"],
                [create_po_line_payload(ctx["sample"]["id"], unit_price_cents=1000)],
                buyer_alias="alias-a", retailer_name="ToolMart", receipt_doc_ref="RA",
            ),
            PA,
        )
        po_a = get_success_data(resp)
        validate_success(api.transition_purchase_order(po_a["id"], {"action": "place"}, pa_headers))
        validate_success(api.transition_purchase_order(po_a["id"], {"action": "receive"}, pa_headers))
        # PO-B total 999 DRAFT
        resp = api.create_purchase_order(
            create_purchase_order_payload(
                ctx["program"]["id"],
                [create_po_line_payload(ctx["sample"]["id"], unit_price_cents=999)],
                buyer_alias="alias-b", retailer_name="ToolMart", receipt_doc_ref="RB",
            ),
            PA,
        )
        po_b = get_success_data(resp)
        # place on PO-A (already RECEIVED): state check fires first
        resp = api.transition_purchase_order(po_a["id"], {"action": "place"}, pa_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        # place on PO-B (DRAFT, valid state): budget check reached -> 999 > 1000-1000
        resp = api.transition_purchase_order(po_b["id"], {"action": "place"}, pa_headers)
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)

    def test_place_exact_remaining_budget_succeeds(self, api):
        """PRD §3.3: "the order's `total_cents` must not exceed the program's remaining budget, defined as `budget_cents` minus `committed_cents`, or the request is rejected with `ERR_BUDGET_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/po_place_state_vs_budget_pair
        """
        ctx = setup_program_sourcing(category_name="Mowers", protocol_code="MOW-03",
                                     model_label="Mow3", budget_cents=1000,
                                     market_share_pct=30, member_interest_pct=30,
                                     refresh_cycle_months=36)
        resp = api.create_purchase_order(
            create_purchase_order_payload(
                ctx["program"]["id"],
                [create_po_line_payload(ctx["sample"]["id"], unit_price_cents=1000)],
                buyer_alias="alias-c", retailer_name="ToolMart", receipt_doc_ref="RC",
            ),
            PA,
        )
        po = get_success_data(resp)
        # total 1000 == budget 1000 - committed 0 -> boundary inclusive, succeeds
        data = validate_success(api.transition_purchase_order(
            po["id"], {"action": "place"}, make_purchasing_agent_headers("pa-1")))
        assert data["status"] == "PLACED"

    def test_receive_cascade_then_start_testing_gate(self, api):
        """PRD §3.3: "Receipt moves the order `PLACED → RECEIVED`, at which point each line's `qty` is added to the referenced sample's `sourced_units` and the sample's `sourcing_complete` flag recomputes — it is true exactly when `sourced_units` is at least `required_units`."
        PRD §3.2: "Starting testing (`SAMPLE_SOURCING → TESTING`) requires that every sample of the program has `sourcing_complete` true and that no purchase order of the program remains in `DRAFT` or `PLACED`".

        Design: Corner/cross_cutting_layers/cascade_order_place_receive_sourcing
        """
        ctx = setup_program_sourcing(category_name="Mowers", protocol_code="MOW-01",
                                     model_label="Mow1", required_units=2,
                                     market_share_pct=30, member_interest_pct=30,
                                     refresh_cycle_months=36)
        pa_headers = make_purchasing_agent_headers("pa-1")
        # PO-A qty 1: place + receive -> sourced_units 1 of 2
        resp = api.create_purchase_order(
            create_purchase_order_payload(
                ctx["program"]["id"],
                [create_po_line_payload(ctx["sample"]["id"], unit_price_cents=1000, qty=1)],
                buyer_alias="alias-a", retailer_name="ToolMart", receipt_doc_ref="RA",
            ),
            PA,
        )
        po_a = get_success_data(resp)
        validate_success(api.transition_purchase_order(po_a["id"], {"action": "place"}, pa_headers))
        validate_success(api.transition_purchase_order(po_a["id"], {"action": "receive"}, pa_headers))
        # PO-B qty 1: place only
        resp = api.create_purchase_order(
            create_purchase_order_payload(
                ctx["program"]["id"],
                [create_po_line_payload(ctx["sample"]["id"], unit_price_cents=1000, qty=1)],
                buyer_alias="alias-b", retailer_name="ToolMart", receipt_doc_ref="RB",
            ),
            PA,
        )
        po_b = get_success_data(resp)
        validate_success(api.transition_purchase_order(po_b["id"], {"action": "place"}, pa_headers))
        # start_testing blocked: sourcing incomplete AND a PO is still PLACED
        resp = api.transition_test_program(ctx["program"]["id"], {"action": "start_testing"}, LM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        # receive PO-B -> sourcing_complete true
        validate_success(api.transition_purchase_order(po_b["id"], {"action": "receive"}, pa_headers))
        sample = get_success_data(api.get_test_sample(ctx["sample"]["id"], LM))
        assert sample["sourced_units"] == 2
        assert sample["sourcing_complete"] is True
        # now start_testing succeeds
        data = validate_success(api.transition_test_program(
            ctx["program"]["id"], {"action": "start_testing"}, LM))
        assert data["status"] == "TESTING"


class TestMeasurementGate:
    def test_measurement_requires_sample_in_lab(self, api):
        """PRD §3.5: "Recording against a sample not in `IN_LAB` is rejected with `ERR_REFERENTIAL_INTEGRITY`."

        Design: Difficulty/cross_entity_state_dependency/measurement_requires_sample_in_lab
        """
        ctx = setup_program_sourcing(category_name="Washers", protocol_code="WSH-01",
                                     model_label="WashA")
        resp = api.create_measurement(
            create_measurement_payload(ctx["sample"]["id"], unit_index=1,
                                       metric_code="WASH", value_num=90),
            LT,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)

    def test_measurement_append_only_and_testing_complete(self, api):
        """PRD §2.4: "A `Measurement` is an append-only lab record: it carries only `id` and `created_at`; both `updated_at` and `version` are absent from it, and no operation ever modifies a measurement after creation."
        PRD §3.5: "A sample's `tested_units` is the count of distinct unit indexes among 1 through `required_units` for which at least `measurement_repeat_min` measurements exist under the category's `ACTIVE` protocol, and `testing_complete` becomes true when `tested_units` reaches `required_units`."

        Design: Corner/entities/measurement_immutable_no_version
        """
        ctx = setup_program_testing(category_name="Washers", protocol_code="WSH-01",
                                    model_label="WashA", required_units=1,
                                    repeat_min=1, measurement_value=90)
        # setup recorded one measurement; record one more and check shape
        resp = api.create_measurement(
            create_measurement_payload(ctx["sample"]["id"], unit_index=1,
                                       metric_code="WASH", value_num=90),
            LT,
        )
        data = validate_success(resp, expected_status=201)
        assert_measurement(data)
        sample = get_success_data(api.get_test_sample(ctx["sample"]["id"], LM))
        assert sample["tested_units"] == 1
        assert sample["testing_complete"] is True

    def test_ready_from_wrong_state_surfaces_invalid_state(self, api):
        """PRD §2.5: "Because the state check (priority 4) precedes every business check, an action attempted from the wrong state always surfaces `ERR_INVALID_STATE` even when a business rule would also reject it".

        Design: Difficulty/priority_pair_validation_conflict/ready_blocks_state_vs_safety_pair
        """
        # program in TESTING (measurements incomplete for a second sample) — ready
        # is only valid from SCORING; a tier-3 OPEN finding is also present.
        ctx = setup_program_testing(category_name="Washers", protocol_code="WSH-01",
                                    model_label="WashA", measurement_value=90)
        # add a second PLANNED-impossible sample: instead, make testing incomplete by
        # adding a second sample before start_sourcing — simpler: log a tier-3 finding
        # and call ready while still in TESTING (start_scoring not yet called).
        from test_helpers import create_safety_finding_payload
        resp = api.create_safety_finding(
            create_safety_finding_payload(
                ctx["program"]["id"], ctx["sample"]["id"],
                severity="CRITICAL", description_text="shock", hazard_flag=True,
            ),
            TEST_USERS["safety_officer_headers"],
        )
        finding = get_success_data(resp)
        assert finding["escalation_tier"] == 3
        resp = api.transition_test_program(ctx["program"]["id"], {"action": "ready"}, LM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_ready_blocked_by_safety_gate_in_scoring(self, api):
        """PRD §3.2: "if any safety finding of the program is in `OPEN` or `ESCALATED` status with an `escalation_tier` of at least 2, the transition is rejected with `ERR_SAFETY_GATE`".

        Design: Difficulty/priority_pair_validation_conflict/ready_blocks_state_vs_safety_pair
        """
        ctx = setup_program_testing(category_name="Washers", protocol_code="WSH-02",
                                    model_label="WashB", measurement_value=90)
        from test_helpers import create_safety_finding_payload
        resp = api.create_safety_finding(
            create_safety_finding_payload(
                ctx["program"]["id"], ctx["sample"]["id"],
                severity="CRITICAL", description_text="shock", hazard_flag=True,
            ),
            TEST_USERS["safety_officer_headers"],
        )
        get_success_data(resp)
        # reach SCORING legitimately
        validate_success(api.transition_test_program(
            ctx["program"]["id"], {"action": "start_scoring"}, LM))
        # now ready hits the safety gate (tier 3 >= 2)
        resp = api.transition_test_program(ctx["program"]["id"], {"action": "ready"}, LM)
        validate_error(resp, ApiErrorId.ERR_SAFETY_GATE)


class TestMeasurementUnitIndexBoundary:
    def test_measurement_unit_index_beyond_required_units_rejected(self, api):
        """PRD §3.5: "While a sample is `IN_LAB`, a `LabTechnician` records measurements against it, each supplying `sample_id`, the `unit_index` (from 1 up to the sample's `required_units`), a `metric_code` such as `SUCTION_KPA`, and the raw `value_num`."
        PRD §2.5: "Structural request validity — required fields present, well-typed, enum values valid, numeric ranges respected; failure yields `ERR_INVALID_REQUEST` (400)."

        Design: Difficulty/cross_entity_state_dependency/measurement_requires_sample_in_lab
        """
        ctx = setup_program_testing(category_name="Washers", protocol_code="WSH-07",
                                    model_label="WashG", required_units=1,
                                    repeat_min=1, measurement_value=90)
        # sample is IN_LAB, but unit_index 2 exceeds required_units 1
        resp = api.create_measurement(
            create_measurement_payload(ctx["sample"]["id"], unit_index=2,
                                       metric_code="WASH", value_num=90),
            LT,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestProtocolRetireFromActive:
    def test_retire_active_protocol_when_no_program_in_flight(self, api):
        """PRD §3.4: "Retirement is allowed from `DRAFT` or `ACTIVE`, but an `ACTIVE` protocol can be retired only when no program of its category is in `SAMPLE_SOURCING`, `TESTING`, or `SCORING`; `RETIRED` is terminal."
        PRD §3.4: "Activation (`IN_REVIEW → ACTIVE`) stamps `activated_at` with the clock, supersedes any other `ACTIVE` protocol of the same category (moving it to `SUPERSEDED`), bumps the category's `version`".

        Design: Difficulty/non_linear_state_machine/protocol_draft_review_cycle
        """
        category = create_category(name="Dryers", market_share_pct=20, member_interest_pct=20)
        proto = create_active_protocol(category, protocol_code="DRY-77",
                                       measurement_repeat_min=1,
                                       perf_weight_pct=50, reliability_weight_pct=25)
        assert proto["status"] == "ACTIVE"
        assert proto["activated_at"] is not None
        # no program of the category is in SAMPLE_SOURCING/TESTING/SCORING
        data = validate_success(api.transition_lab_protocol(proto["id"], {"action": "retire"}, MO))
        assert data["status"] == "RETIRED"
