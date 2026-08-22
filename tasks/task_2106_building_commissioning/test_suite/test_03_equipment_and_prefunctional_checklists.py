"""Equipment scope, its two state dimensions, and pre-functional verification."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_equipment_unit,
    assert_prefunctional_checklist,
    add_item,
    create_checklist,
    create_equipment_unit_payload,
    create_executed_checklist,
    create_issue,
    create_project,
    execute_checklist,
    get_checklist,
    get_equipment,
    get_project,
    record_item,
    register_equipment,
    set_install_status,
    setup_prefunctional_verified_equipment,
    setup_two_verified_checklists,
    validate_error,
    validate_paginated,
    validate_success,
    verify_checklist,
)
from test_helpers import CONTRACTOR, CXA, OWNER, make_cx_authority_headers


class TestEquipmentRegistry:
    def test_equipment_list_filters_by_engagement_and_paginates(self, api):
        """PRD §3.3: "Equipment lists can be narrowed on either dimension, by
        `install_status` or by `verification_status`, as well as by `project_id`."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
        inside the `meta` object of the envelope. `total_count` is the number of rows
        matching the request's filters before pagination is applied, and `has_more` is true
        when rows remain beyond the current page."

        Design: Corner/entities/list_equipment_units_filters_by_project_and_paginates
        """
        project_a = create_project(
            name="Alpha Cx", building_name="Alpha", contract_value_cents=50_000_000
        )
        project_b = create_project(
            name="Bravo Cx", building_name="Bravo", contract_value_cents=50_000_000
        )
        for tag in ("AHU-1", "AHU-2", "AHU-3"):
            register_equipment(
                project_a["id"], tag=tag, contract_value_cents=100_000, weight_units=1
            )
        register_equipment(
            project_b["id"],
            tag="CHW-1",
            system_type="CHILLER",
            contract_value_cents=100_000,
            weight_units=1,
        )

        response = api.list_equipment_units(
            CXA, params={"project_id": project_a["id"], "limit": 2, "offset": 0}
        )
        rows, meta = validate_paginated(response)

        assert response.json()["response_type"] == "array"
        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert all(row["project_id"] != project_b["id"] for row in rows)

    def test_unknown_equipment_id_answers_the_equipment_not_found_code(self, api):
        """PRD §2.5: "Every identifier embedded in the request path resolves to a stored
        row, checked from left to right, answering with the not-found code of the first
        identifier that fails: `ERR_PROJECT_NOT_FOUND`, `ERR_REQUIREMENT_NOT_FOUND`,
        `ERR_PLAN_NOT_FOUND`, `ERR_SUBMITTAL_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`,
        `ERR_CHECKLIST_NOT_FOUND`, `ERR_TEST_NOT_FOUND`, `ERR_ISSUE_NOT_FOUND`,
        `ERR_DEFERRED_TEST_NOT_FOUND`, `ERR_DELIVERABLE_NOT_FOUND`, `ERR_CREDIT_NOT_FOUND`
        or `ERR_BASELINE_NOT_FOUND` (all 404)."

        Design: Corner/entities/get_unknown_equipment_unit_returns_not_found
        """
        response = api.get_equipment_unit(NON_EXISTENT_UUID, CXA)
        validate_error(response, ApiErrorId.ERR_EQUIPMENT_NOT_FOUND.value, 404)
        assert response.json()["response_type"] == "error"

    def test_undeclared_system_type_is_rejected(self, api):
        """PRD §3.3: "Equipment is registered by a `PlatformAdmin` or a `CxAuthority`
        against a `project_id`, with a `tag` such as AHU-1, a `system_type` drawn from
        `AHU`, `CHILLER`, `BOILER`, `LIGHTING`, `FIRE_ALARM`, `ELEVATOR` and `BAS`, a
        `criticality` of `LIFE_SAFETY`, `CRITICAL` or `STANDARD`, a `contract_value_cents`
        of at least 1 giving the contract value attributable to this unit, and a
        `weight_units` of at least 1 giving its relative weight in the engagement's
        completion score."
        PRD §2.5: "The request body carries every required field with a well-formed type,
        every enumerated value is a declared member of its enumeration, every numeric field
        satisfies its declared range constraint, every datetime parses as ISO 8601 UTC, and
        `limit` and `offset` are inside the pagination bounds — otherwise `ERR_VALIDATION`
        (400)."

        Design: Corner/entities/equipment_unit_rejects_undeclared_system_type_enum
        """
        project = create_project(
            name="Enum Cx", building_name="Enum Block", contract_value_cents=50_000_000
        )
        payload = create_equipment_unit_payload(
            project["id"],
            tag="PV-1",
            system_type="SOLAR_ARRAY",
            contract_value_cents=100_000,
            weight_units=1,
        )

        validate_error(
            api.create_equipment_unit(payload, CXA), ApiErrorId.ERR_VALIDATION.value, 400
        )

        _, meta = validate_paginated(
            api.list_equipment_units(CXA, params={"project_id": project["id"]})
        )
        assert meta["total_count"] == 0

    def test_server_owned_equipment_fields_are_not_seeded_by_the_client(self, api):
        """PRD §3.3: "A newly registered unit reads `install_status` `NOT_INSTALLED`,
        `verification_status` `UNVERIFIED` and `blocking_issue_count` 0."
        PRD §3.3: "The **verification dimension** is never driven directly by a client."

        Design: Corner/entities/equipment_unit_system_fields_client_input_ignored
        """
        project = create_project(
            name="Sysfield Cx",
            building_name="Sysfield Block",
            contract_value_cents=50_000_000,
        )
        payload = create_equipment_unit_payload(
            project["id"],
            tag="AHU-SF",
            contract_value_cents=100_000,
            weight_units=1,
            install_status="STARTED_UP",
            verification_status="FUNCTIONAL_ACCEPTED",
            blocking_issue_count=9,
        )

        response = api.create_equipment_unit(payload, CXA)
        if response.status_code == 201:
            equipment = validate_success(response, 201)
            assert_equipment_unit(equipment)
            assert equipment["install_status"] == "NOT_INSTALLED"
            assert equipment["verification_status"] == "UNVERIFIED"
            assert equipment["blocking_issue_count"] == 0
            assert equipment["version"] == 1
        else:
            validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)


class TestInstallationDimension:
    def test_install_status_may_not_skip_the_installed_step(self, api):
        """PRD §3.3: "Progress runs `NOT_INSTALLED` → `INSTALLED` → `STARTED_UP`, one step
        at a time."
        PRD §2.5: "The target resource is in a status from which the requested transition is
        declared — otherwise `ERR_INVALID_STATE` (409). This applies to every state-changing
        action endpoint in the system."

        Design: Corner/state_machines/equipment_install_status_skipping_installed_returns_invalid_state
        """
        project = create_project(
            name="Skip Cx", building_name="Skip Block", contract_value_cents=50_000_000
        )
        equipment = register_equipment(
            project["id"], tag="AHU-SK", contract_value_cents=100_000, weight_units=1
        )

        response = api.set_install_status(
            equipment["id"], {"install_status": "STARTED_UP"}, CONTRACTOR
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

        after = get_equipment(equipment["id"])
        assert after["install_status"] == "NOT_INSTALLED"
        assert after["verification_status"] == "UNVERIFIED"


class TestParallelStateDimensions:
    def test_verification_advances_while_installation_stands_still(self, api):
        """PRD §3.3: "Every equipment unit carries **two independent state dimensions on the
        same row**, and neither constrains the other except where a rule says so in as many
        words."
        PRD §3.3: "A successful verification moves the checklist `EXECUTED` → `VERIFIED`,
        records `verified_by_user_id`, adds the unit's `weight_units` to the engagement's
        `verified_prefunctional_units`, drives the unit's verification dimension
        `UNVERIFIED` → `PREFUNCTIONAL_VERIFIED`, recomputes the provisional acceptance
        completion score, and increments the engagement's `version` by one."

        Design: Difficulty/non_linear_state_machine/equipment_install_and_verification_dimensions_advance_independently
        """
        project = create_project(name="Cedar Cx", building_name="Cedar Wing")
        unit = setup_prefunctional_verified_equipment(
            project["id"],
            started_up=False,
            tag="BLR-1",
            system_type="BOILER",
            criticality="CRITICAL",
        )

        after_verify = unit["equipment"]
        assert after_verify["install_status"] == "INSTALLED", (
            "verification does not touch the installation dimension"
        )
        assert after_verify["verification_status"] == "PREFUNCTIONAL_VERIFIED"

        after_startup = set_install_status(after_verify["id"], "STARTED_UP")
        assert after_startup["install_status"] == "STARTED_UP"
        assert after_startup["verification_status"] == "PREFUNCTIONAL_VERIFIED", (
            "the install transition leaves the verification dimension untouched"
        )

    def test_blocking_deficiency_demotes_verification_but_not_installation(self, api):
        """PRD §3.3: "When a blocking issue attaches to a unit that is sitting in
        `PREFUNCTIONAL_VERIFIED`, `FUNCTIONAL_ACCEPTED` or `CONDITIONALLY_ACCEPTED`, that
        unit is demoted to `UNVERIFIED` and every `EQUIPMENT_VERIFICATION` evidence row
        whose `evidence_ref_id` names it flips `is_stale` to true and stamps `staled_at`."
        PRD §2.7: "The **criticality factor** is 1.5 for `LIFE_SAFETY` equipment, 1.2 for
        `CRITICAL` equipment and 1.0 for `STANDARD` equipment; an issue with no equipment
        always uses the `STANDARD` factor of 1.0."

        Design: Difficulty/non_linear_state_machine/equipment_install_and_verification_dimensions_advance_independently
        """
        project = create_project(name="Cedar Cx", building_name="Cedar Wing")
        unit = setup_prefunctional_verified_equipment(
            project["id"],
            started_up=True,
            tag="BLR-1",
            system_type="BOILER",
            criticality="CRITICAL",
        )
        checklist = unit["checklist"]

        issue = create_issue(
            project["id"],
            "S2",
            origin="PREFUNCTIONAL",
            description="Combustion air louver undersized",
            equipment_id=unit["equipment"]["id"],
            source_ref_id=checklist["id"],
        )
        assert issue["retainage_hold_cents"] == 24_000, (
            "1000000 * 0.02 * 1.2 rounded half up to whole cents"
        )

        equipment = get_equipment(unit["equipment"]["id"])
        assert equipment["install_status"] == "STARTED_UP", (
            "the deficiency does not move the installation dimension"
        )
        assert equipment["verification_status"] == "UNVERIFIED"
        assert equipment["blocking_issue_count"] == 1

        assert get_checklist(checklist["id"])["status"] == "VERIFIED", (
            "the checklist dimension is untouched by the deficiency"
        )
        assert get_project(project["id"])["verified_prefunctional_units"] == 10


class TestChecklistItemsAndExecution:
    def test_execute_refuses_an_empty_checklist(self, api):
        """PRD §3.3: "Three conditions gate that sign-off: the checklist must carry at least
        one item, or it is refused with `ERR_CHECKLIST_EMPTY`; no item may still read
        `PENDING`, or it is refused with `ERR_CHECKLIST_INCOMPLETE`; and the unit's
        `install_status` must be `INSTALLED` or `STARTED_UP`, or it is refused with
        `ERR_EQUIPMENT_NOT_READY`."

        Design: Difficulty/boundary_precision_check/checklist_execute_zero_item_boundary
        """
        project = create_project(name="Willow Cx", building_name="Willow Annex")
        equipment = register_equipment(
            project["id"], tag="BAS-1", system_type="BAS"
        )
        set_install_status(equipment["id"], "INSTALLED")
        checklist = create_checklist(equipment["id"], template_code="PFC-BAS-STD")
        assert checklist["item_count"] == 0
        assert checklist["items"] == []

        response = api.execute_checklist(checklist["id"], CONTRACTOR)
        validate_error(response, ApiErrorId.ERR_CHECKLIST_EMPTY.value, 422)

        assert get_checklist(checklist["id"])["status"] == "DRAFT"
        assert get_project(project["id"])["verified_prefunctional_units"] == 0, (
            "the refused execute wrote nothing"
        )

    def test_execute_succeeds_once_a_single_item_is_recorded(self, api):
        """PRD §3.3: "When the sheet is complete the `Contractor` signs it off, moving the
        checklist to `EXECUTED` from either `DRAFT` or `REWORK` and recording
        `executed_by_user_id`."
        PRD §3.3: "An appended item enters the `items` array in insertion order with its
        `result` set to `PENDING` and its `recorded_by_user_id` and `recorded_at` null, and
        `item_count` is refreshed."

        Design: Difficulty/boundary_precision_check/checklist_execute_zero_item_boundary
        """
        project = create_project(name="Willow Cx", building_name="Willow Annex")
        equipment = register_equipment(project["id"], tag="BAS-1", system_type="BAS")
        set_install_status(equipment["id"], "INSTALLED")
        checklist = create_checklist(equipment["id"], template_code="PFC-BAS-STD")

        appended = add_item(
            checklist["id"], item_code="PFC-01", description="Points list verified"
        )
        assert appended["item_count"] == 1
        assert appended["items"][0]["result"] == "PENDING"
        assert appended["items"][0]["recorded_by_user_id"] is None

        record_item(checklist["id"], item_code="PFC-01", result="PASS")
        executed = execute_checklist(checklist["id"])

        assert_prefunctional_checklist(executed)
        assert executed["status"] == "EXECUTED"
        assert executed["item_count"] == 1

    def test_duplicate_and_unknown_item_codes_are_refused(self, api):
        """PRD §3.3: "Appending an `item_code` the checklist already carries is refused with
        `ERR_DUPLICATE_ITEM_CODE`."
        PRD §3.3: "Naming an `item_code` the checklist does not carry is refused with
        `ERR_ITEM_NOT_FOUND`."
        PRD §3.3: "Three conditions gate that sign-off: the checklist must carry at least
        one item, or it is refused with `ERR_CHECKLIST_EMPTY`; no item may still read
        `PENDING`, or it is refused with `ERR_CHECKLIST_INCOMPLETE`; and the unit's
        `install_status` must be `INSTALLED` or `STARTED_UP`, or it is refused with
        `ERR_EQUIPMENT_NOT_READY`."

        Design: Corner/validations/checklist_item_code_uniqueness_and_lookup_are_enforced
        """
        project = create_project(name="Item Cx", building_name="Item Block")
        equipment = register_equipment(project["id"], tag="AHU-IT")
        set_install_status(equipment["id"], "INSTALLED")
        checklist = create_checklist(equipment["id"])
        add_item(checklist["id"], item_code="PFC-01", description="Filters installed")
        add_item(checklist["id"], item_code="PFC-02", description="Coils clean")
        record_item(checklist["id"], item_code="PFC-01", result="PASS")

        duplicate = api.add_checklist_item(
            checklist["id"],
            {
                "item_code": "PFC-01",
                "description": "Filters installed again",
                "is_safety_critical": False,
            },
            CXA,
        )
        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_ITEM_CODE.value, 422)

        unknown = api.record_checklist_item(
            checklist["id"], {"item_code": "PFC-99", "result": "PASS"}, CONTRACTOR
        )
        validate_error(unknown, ApiErrorId.ERR_ITEM_NOT_FOUND.value, 422)

        incomplete = api.execute_checklist(checklist["id"], CONTRACTOR)
        validate_error(incomplete, ApiErrorId.ERR_CHECKLIST_INCOMPLETE.value, 422)

        after = get_checklist(checklist["id"])
        assert after["item_count"] == 2
        assert after["status"] == "DRAFT"
        assert after["passed_item_count"] == 1


class TestChecklistVerification:
    def test_verify_is_refused_while_the_checklist_is_still_draft(self, api):
        """PRD §3.3: "It is permitted only from `EXECUTED`, only when the acting `X-User-ID`
        differs from `executed_by_user_id`, only when no item whose `is_safety_critical` is
        true carries a `result` of `FAIL` — that one is refused with
        `ERR_SAFETY_ITEM_FAILED` — and only when the unit's `blocking_issue_count` is 0."

        Design: Corner/state_machines/verifying_a_draft_checklist_returns_invalid_state
        """
        project = create_project(name="Draft Cx", building_name="Draft Block")
        equipment = register_equipment(project["id"], tag="AHU-DR")
        set_install_status(equipment["id"], "INSTALLED")
        checklist = create_checklist(equipment["id"])
        add_item(checklist["id"], item_code="PFC-01", description="Access doors sealed")
        record_item(checklist["id"], item_code="PFC-01", result="PASS")

        response = api.verify_checklist(checklist["id"], CXA)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

        after = get_checklist(checklist["id"])
        assert after["status"] == "DRAFT"
        assert after["verified_by_user_id"] is None
        assert get_project(project["id"])["verified_prefunctional_units"] == 0
        assert get_equipment(equipment["id"])["verification_status"] == "UNVERIFIED"

    def test_failed_safety_critical_item_blocks_verification(self, api):
        """PRD §2.5: "No checklist item whose `is_safety_critical` is true carries `result`
        of `FAIL` — otherwise `ERR_SAFETY_ITEM_FAILED` (422). Only checklist verification is
        guarded."
        PRD §3.3: "When the sheet is complete the `Contractor` signs it off, moving the
        checklist to `EXECUTED` from either `DRAFT` or `REWORK` and recording
        `executed_by_user_id`."

        Design: Corner/validations/safety_critical_failed_item_blocks_checklist_verification
        """
        project = create_project(name="Safety Cx", building_name="Safety Block")
        equipment = register_equipment(
            project["id"],
            tag="ELV-SF",
            system_type="ELEVATOR",
            criticality="LIFE_SAFETY",
        )
        set_install_status(equipment["id"], "INSTALLED")
        checklist = create_checklist(equipment["id"], template_code="PFC-ELV-STD")
        add_item(
            checklist["id"],
            item_code="PFC-01",
            description="Hoistway fire rating verified",
            is_safety_critical=True,
        )
        add_item(
            checklist["id"],
            item_code="PFC-02",
            description="Cab finishes installed",
            is_safety_critical=False,
        )
        record_item(
            checklist["id"], item_code="PFC-01", result="FAIL", note="Penetration unsealed"
        )
        record_item(checklist["id"], item_code="PFC-02", result="PASS")
        executed = execute_checklist(checklist["id"])
        assert executed["status"] == "EXECUTED"
        assert executed["failed_item_count"] == 1

        response = api.verify_checklist(checklist["id"], CXA)
        validate_error(response, ApiErrorId.ERR_SAFETY_ITEM_FAILED.value, 422)

        after = get_checklist(checklist["id"])
        assert after["status"] == "EXECUTED"
        assert after["verified_by_user_id"] is None
        assert get_project(project["id"])["verified_prefunctional_units"] == 0
        assert get_equipment(equipment["id"])["verification_status"] == "UNVERIFIED"

    def test_verifier_may_not_be_the_executor(self, api):
        """PRD §2.11: "The `X-User-ID` recorded as a checklist's `executed_by_user_id` may
        not be the `X-User-ID` that verifies that checklist, and the `X-User-ID` recorded as
        a deliverable's `delivered_by_user_id` may not be the `X-User-ID` that accepts it."
        PRD §2.11: "Note that this is an identity comparison, not a role comparison: two
        different people holding the same role satisfy the rule, and the same person
        switching roles does not."

        Design: Corner/rbac/checklist_verifier_may_not_be_its_executor
        """
        project = create_project(name="SoD Cx", building_name="SoD Block")
        equipment = register_equipment(project["id"], tag="AHU-SD")
        set_install_status(equipment["id"], "INSTALLED", user_id="u-shared-1")
        executed = create_executed_checklist(
            equipment["id"], executor_user_id="u-shared-1"
        )
        assert executed["executed_by_user_id"] == "u-shared-1"

        self_verify = api.verify_checklist(
            executed["id"], make_cx_authority_headers("u-shared-1")
        )
        validate_error(self_verify, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

        verified = verify_checklist(executed["id"], user_id="u-cxa-9")
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == "u-cxa-9"
        assert get_project(project["id"])["verified_prefunctional_units"] == 10


class TestVerificationIsImmediatelyVisible:
    def test_verify_response_and_the_next_read_already_agree(self, api):
        """PRD §2.8: "Reconciliation is **immediate**. There is no background job, no
        eventual convergence and no lazy recomputation on read: by the time a mutating
        request returns, every roll-up it touched is already correct."
        PRD §3.9: "Each surviving unit contributes its `weight_units` multiplied by a blend
        of three sub-scores: the pre-functional sub-score weighted at 0.30, the functional
        sub-score weighted at 0.50 and the closeout sub-score weighted at 0.20."

        Design: Corner/consistency_model/cascade_effects_are_visible_in_the_same_request
        """
        project = create_project(name="Immediate Cx", building_name="Immediate Block")
        equipment = register_equipment(project["id"], tag="AHU-IM")
        set_install_status(equipment["id"], "INSTALLED")
        executed = create_executed_checklist(equipment["id"])

        verified = validate_success(api.verify_checklist(executed["id"], CXA), 200)
        assert verified["status"] == "VERIFIED"

        project_now = validate_success(api.get_cx_project(project["id"], OWNER), 200)
        assert project_now["verified_prefunctional_units"] == 10
        assert project_now["acceptance_completion_score"] == 30.00

        equipment_now = validate_success(
            api.get_equipment_unit(equipment["id"], OWNER), 200
        )
        assert equipment_now["verification_status"] == "PREFUNCTIONAL_VERIFIED"


class TestRejectionRestoresVerifiedWeight:
    def test_rejecting_a_verified_checklist_subtracts_exactly_its_weight(self, api):
        """PRD §3.3: "Rejecting from `VERIFIED` does strictly more, because there is more to
        unwind: it additionally clears `verified_by_user_id`, subtracts the unit's
        `weight_units` from `verified_prefunctional_units` so that a verify-then-reject
        cycle leaves that figure exactly where it started, and drives the unit's
        verification dimension back to `UNVERIFIED` from whichever of
        `PREFUNCTIONAL_VERIFIED`, `FUNCTIONAL_ACCEPTED` or `CONDITIONALLY_ACCEPTED` it had
        reached."
        PRD §3.3: "It is reachable from both `EXECUTED` and `VERIFIED`, and both branches
        send the checklist to `REWORK`, increment `rework_cycle_count` by one, clear
        `executed_by_user_id`, and reset every item's `result` back to `PENDING` while
        clearing that item's `recorded_by_user_id` and `recorded_at`."

        Design: Difficulty/compensating_invariant/reject_checklist_restores_verified_prefunctional_units_exactly
        """
        setup = setup_two_verified_checklists()
        project_id = setup["project"]["id"]
        assert get_project(project_id)["verified_prefunctional_units"] == 15

        rejected = validate_success(
            api.reject_checklist(
                setup["checklist_a"]["id"],
                {"reason": "Coil piping insulation missing"},
                CXA,
            ),
            200,
        )
        assert rejected["status"] == "REWORK"
        assert rejected["rework_cycle_count"] == 1
        assert rejected["executed_by_user_id"] is None
        assert all(item["result"] == "PENDING" for item in rejected["items"])

        assert get_project(project_id)["verified_prefunctional_units"] == 5, (
            "exactly the 10 weight units of the rejected unit are subtracted"
        )
        assert (
            get_equipment(setup["equipment_a"]["id"])["verification_status"]
            == "UNVERIFIED"
        )

    def test_re_verifying_after_rework_restores_the_figure_with_zero_drift(self, api):
        """PRD §2.8: "`verified_prefunctional_units` — the sum of `weight_units` over every
        equipment unit of the engagement whose pre-functional checklist is `VERIFIED`. This
        is the second conserved quantity: verification adds the unit's weight, and the
        compensating rejection subtracts exactly the same weight, so a verify-then-reject
        cycle must leave the figure precisely where it started."
        PRD §3.3: "Once in `REWORK` the checklist can be re-executed, which is what makes
        the `EXECUTED` or `VERIFIED` → `REWORK` → `EXECUTED` loop cyclic."

        Design: Difficulty/compensating_invariant/reject_checklist_restores_verified_prefunctional_units_exactly
        """
        setup = setup_two_verified_checklists()
        project_id = setup["project"]["id"]
        checklist_id = setup["checklist_a"]["id"]

        validate_success(
            api.reject_checklist(
                checklist_id, {"reason": "Coil piping insulation missing"}, CXA
            ),
            200,
        )
        assert get_project(project_id)["verified_prefunctional_units"] == 5

        record_item(checklist_id, item_code="PFC-01", result="PASS")
        execute_checklist(checklist_id)
        reverified = verify_checklist(checklist_id)

        assert reverified["status"] == "VERIFIED"
        assert reverified["rework_cycle_count"] == 1
        assert get_project(project_id)["verified_prefunctional_units"] == 15, (
            "the conserved weight returns to exactly its pre-rejection value"
        )
        assert (
            get_equipment(setup["equipment_a"]["id"])["verification_status"]
            == "PREFUNCTIONAL_VERIFIED"
        )
