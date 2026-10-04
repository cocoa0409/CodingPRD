"""Programs, certification testing, and BIN range assignment tests."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_approved_program,
    create_production_enabled_program,
    create_program_under_certification,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

OP = TEST_USERS["network_operator_headers"]
CE = TEST_USERS["certification_engineer_headers"]


def _active_member(api, kind="BOTH"):
    member = get_success_data(api.create_member(
        {"legal_name": "B", "member_kind": kind, "region": "NA"}, OP))
    return get_success_data(api.approve_member(member["id"], OP))


class TestBinRangeCreation:
    def test_bin_prefix_format_constraint(self, api):
        """PRD §3.3: "A `NetworkOperator` requests a `BinRange` by supplying a
        `bin_prefix` of exactly six digits — anything else is rejected with
        `ERR_VALIDATION` — and the `issuer_member_id` of the owning issuer,
        which must be an `ACTIVE` member of kind `ISSUER` or `BOTH`."

        Design: Corner/entities/bin_prefix_format_constraint
        """
        issuer = _active_member(api, kind="ISSUER")
        res = api.create_bin_range(
            {"bin_prefix": "41111", "issuer_member_id": issuer["id"]}, OP)
        validate_error(res, ApiErrorId.ERR_VALIDATION)


class TestProgramCertification:
    def test_certification_fail_reverts_program_to_registered(self, api):
        """PRD §3.3: "When a run fails and no other run for the same program
        remains in `SUBMITTED`, the program reverts from
        `UNDER_CERTIFICATION` back to `REGISTERED`, again with a version
        increment."
        PRD §3.3: "failed (moving to `FAILED` with the supplied
        `failure_reason` recorded; `failure_reason` stays null on runs that do
        not fail)".

        Design: Corner/state_machines/certification_fail_reverts_program_to_registered
        """
        member = _active_member(api)
        program = get_success_data(api.create_program(
            {"name": "G", "program_type": "CARD_PRODUCT", "product_code": "CC",
             "owner_member_id": member["id"]}, CE))
        test = get_success_data(api.create_certification_test(
            program["id"], {"scope": "NEW_PRODUCT"}, CE))
        mid = get_success_data(api.get_program(program["id"], CE))
        assert mid["status"] == "UNDER_CERTIFICATION"

        res = api.fail_certification_test(test["id"],
                                          {"failure_reason": "MTI mismatch"}, CE)
        data = validate_success(res)
        assert data["status"] == "FAILED"
        assert data["failure_reason"] == "MTI mismatch"

        program_now = get_success_data(api.get_program(program["id"], CE))
        assert program_now["status"] == "REGISTERED"

    def test_certification_stale_version_blocks_approval(self, api):
        """PRD §3.3: "Approval moves the program from `UNDER_CERTIFICATION` to
        `APPROVED` only when at least one test run for the program is `PASSED`
        **and** that run's `evaluated_program_version` equals the program's
        current `version`; if every passing run was evaluated against an older
        version — because the program was edited after the test — approval is
        rejected with `ERR_CERTIFICATION_STALE`."

        Design: Corner/validations/certification_stale_version_blocks_approval
        """
        member = _active_member(api)
        program = get_success_data(api.create_program(
            {"name": "G", "program_type": "CARD_PRODUCT", "product_code": "CC",
             "owner_member_id": member["id"]}, CE))
        test = get_success_data(api.create_certification_test(
            program["id"], {"scope": "NEW_PRODUCT"}, CE))
        get_success_data(api.pass_certification_test(test["id"], CE))
        # Edit after the passing test bumps the version, orphaning the PASS.
        edited = get_success_data(api.patch_program(
            program["id"], {"name": "G-renamed"}, CE))

        res = api.approve_program(
            program["id"], {"expected_program_version": edited["version"]}, CE)
        validate_error(res, ApiErrorId.ERR_CERTIFICATION_STALE)
        program_now = get_success_data(api.get_program(program["id"], CE))
        assert program_now["status"] == "UNDER_CERTIFICATION"

    def test_occ_program_approve_stale_version_rejected(self, api):
        """PRD §2.6: "The approval request must carry
        `expected_program_version` matching the program's current `version`.
        If another writer has advanced the program's `version` since the
        client last read it — for example by editing the `product_code` — the
        approval is rejected with `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/cross_cutting_layers/occ_program_approve_stale_version
        """
        member = _active_member(api)
        program = get_success_data(api.create_program(
            {"name": "G", "program_type": "CARD_PRODUCT", "product_code": "CC",
             "owner_member_id": member["id"]}, CE))
        stale_version = program["version"]
        # Submitting the test run advances Program.version past the client's
        # captured view.
        test = get_success_data(api.create_certification_test(
            program["id"], {"scope": "NEW_PRODUCT"}, CE))
        get_success_data(api.pass_certification_test(test["id"], CE))
        fresh = get_success_data(api.get_program(program["id"], CE))
        assert fresh["version"] > stale_version

        res = api.approve_program(
            program["id"], {"expected_program_version": stale_version}, CE)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    def test_occ_program_approve_fresh_version_succeeds(self, api):
        """PRD §2.6: "A successful approval records the supplied
        `expected_program_version` into the program's `approved_version` field
        before the transition's own increment."
        PRD §3.3: "On success, `approved_version` is pinned to the
        pre-increment version — the same value the client supplied — and the
        transition then increments `version` once."

        Design: Corner/cross_cutting_layers/occ_program_approve_stale_version
        """
        member = _active_member(api)
        program, test = create_program_under_certification(member["id"])
        get_success_data(api.pass_certification_test(test["id"], CE))
        fresh = get_success_data(api.get_program(program["id"], CE))

        res = api.approve_program(
            program["id"], {"expected_program_version": fresh["version"]}, CE)
        data = validate_success(res)
        assert data["status"] == "APPROVED"
        assert data["approved_version"] == fresh["version"]
        assert data["version"] == fresh["version"] + 1


class TestProductionEnablement:
    def test_program_production_enablement_after_edit_blocked(self, api):
        """PRD §3.3: "Production enablement is the final gate, and it is
        deliberately brittle: the program must be `APPROVED` and its current
        `version` must be exactly one more than `approved_version`. The
        approval transition's own increment accounts for that single step, so
        any post-approval edit — which increments `version` again — breaks the
        pin, and enablement is then rejected with `ERR_PROGRAM_NOT_ENABLED`."

        Design: Corner/state_machines/program_production_enablement_after_edit_blocked
        """
        member = _active_member(api)
        program = create_approved_program(
            member["id"], scope="WALLET", program_type="WALLET",
            product_code="WL")
        get_success_data(api.patch_program(program["id"],
                                           {"product_code": "WL2"}, CE))
        res = api.enable_program_production(program["id"], CE)
        validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_ENABLED)
        program_now = get_success_data(api.get_program(program["id"], CE))
        assert program_now["status"] == "APPROVED"

    def test_bin_approve_nonexistent_program_not_found(self, api):
        """PRD §2.10: "Existence checking applies equally to identifiers
        referenced in the request body — a creation payload referencing a
        nonexistent sponsor member, program, rule, merchant, or window is
        rejected with `ERR_NOT_FOUND` before structural or business checks
        run, per the ordering in §2.7."

        Design: Difficulty/priority_pair_validation_conflict/bin_approve_existence_vs_program_gate
        """
        issuer = _active_member(api, kind="ISSUER")
        bin_range = get_success_data(api.create_bin_range(
            {"bin_prefix": "422222", "issuer_member_id": issuer["id"]}, OP))
        res = api.approve_bin_range(bin_range["id"],
                                    {"program_id": NON_EXISTENT_UUID}, OP)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)
        current = get_success_data(api.get_bin_range(bin_range["id"], OP))
        assert current["status"] == "REQUESTED"

    def test_bin_approve_requires_production_enabled_program(self, api):
        """PRD §3.3: "Approval binds the range to a program: the request names
        a `program_id`, and the approval succeeds only when the range is still
        `REQUESTED`, the issuer is `ACTIVE`, and the referenced program is in
        `PRODUCTION_ENABLED` status — any other program status rejects the
        approval with `ERR_PROGRAM_NOT_ENABLED`."

        Design: Difficulty/priority_pair_validation_conflict/bin_approve_existence_vs_program_gate
        """
        issuer = _active_member(api, kind="ISSUER")
        bin_range = get_success_data(api.create_bin_range(
            {"bin_prefix": "422222", "issuer_member_id": issuer["id"]}, OP))
        # Program driven to APPROVED but never production-enabled.
        program = create_approved_program(issuer["id"])
        res = api.approve_bin_range(bin_range["id"],
                                    {"program_id": program["id"]}, OP)
        validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_ENABLED)
        current = get_success_data(api.get_bin_range(bin_range["id"], OP))
        assert current["status"] == "REQUESTED"


class TestProgramRetirement:
    def test_program_retire_deactivates_bound_bins(self, api):
        """PRD §3.3: "From there, retirement moves it to the terminal
        `RETIRED` state and cascades: every BIN range whose
        `assigned_program_id` references the program and whose status is
        `ACTIVE` transitions to `DEACTIVATED`."

        Design: Corner/state_machines/program_retire_deactivates_bound_bins
        """
        member = _active_member(api)
        program = create_production_enabled_program(member["id"])
        bin_range = get_success_data(api.create_bin_range(
            {"bin_prefix": "433333", "issuer_member_id": member["id"]}, OP))
        get_success_data(api.approve_bin_range(
            bin_range["id"], {"program_id": program["id"]}, OP))

        res = api.retire_program(program["id"], CE)
        data = validate_success(res)
        assert data["status"] == "RETIRED"
        bin_now = get_success_data(api.get_bin_range(bin_range["id"], OP))
        assert bin_now["status"] == "DEACTIVATED"


class TestMemberSuspendReinstateCycle:
    def test_suspend_reinstate_restores_full_tree(self, api):
        """PRD §3.1: "Reinstating a `SUSPENDED` member clears
        `suspension_reason` back to null and lifts the cascade: sponsored
        participants still in `SUSPENDED` return to `ACTIVE` — provided the
        sponsor is active again, which the reinstatement guarantees — and the
        merchants beneath those participants return to `ACTIVE` with them."

        Design: Difficulty/non_linear_state_machine/member_suspend_reinstate_cycle
        """
        member = _active_member(api)
        participant = get_success_data(api.create_participant(
            {"name": "Part Co", "sponsor_member_id": member["id"],
             "program_name": "PartProg"},
            TEST_USERS["sponsorship_manager_headers"]))
        get_success_data(api.approve_participant(
            participant["id"], TEST_USERS["sponsorship_manager_headers"]))
        merchant = get_success_data(api.create_merchant(
            {"participant_id": participant["id"], "mcc": "5411",
             "region": "NA", "declared_monthly_volume_cents": 1000000},
            TEST_USERS["sponsorship_manager_headers"]))
        program = create_production_enabled_program(member["id"])
        bin_range = get_success_data(api.create_bin_range(
            {"bin_prefix": "411111", "issuer_member_id": member["id"]}, OP))
        get_success_data(api.approve_bin_range(
            bin_range["id"], {"program_id": program["id"]}, OP))

        # Suspend: the whole tree falls.
        validate_success(api.suspend_member(member["id"], {"reason": "AUDIT"},
                                            OP))
        assert get_success_data(api.get_member(member["id"], OP))["status"] == "SUSPENDED"
        assert get_success_data(api.get_participant(participant["id"], OP))["status"] == "SUSPENDED"
        assert get_success_data(api.get_merchant(merchant["id"], OP))["status"] == "SUSPENDED"
        assert get_success_data(api.get_bin_range(bin_range["id"], OP))["status"] == "SUSPENDED"

        # Reinstate: the cycle closes back to ACTIVE.
        res = api.reinstate_member(member["id"], OP)
        data = validate_success(res)
        assert data["status"] == "ACTIVE"
        assert data["suspension_reason"] is None
        assert get_success_data(api.get_participant(participant["id"], OP))["status"] == "ACTIVE"
        assert get_success_data(api.get_merchant(merchant["id"], OP))["status"] == "ACTIVE"
        assert get_success_data(api.get_bin_range(bin_range["id"], OP))["status"] == "ACTIVE"

    def test_suspend_reinstate_cycle_is_repeatable(self, api):
        """PRD §3.1: "Suspending an `ACTIVE` member requires a `reason` in the
        request, which is recorded into `suspension_reason`; the suspension
        then fires the full cascade described in §2.8".
        PRD §3.1: "Reinstating a `SUSPENDED` member clears `suspension_reason`
        back to null and lifts the cascade".

        Design: Difficulty/non_linear_state_machine/member_suspend_reinstate_cycle
        """
        member = _active_member(api)
        participant = get_success_data(api.create_participant(
            {"name": "Part Co", "sponsor_member_id": member["id"],
             "program_name": "PartProg"},
            TEST_USERS["sponsorship_manager_headers"]))
        get_success_data(api.approve_participant(
            participant["id"], TEST_USERS["sponsorship_manager_headers"]))

        # First cycle.
        validate_success(api.suspend_member(member["id"], {"reason": "AUDIT"},
                                            OP))
        assert get_success_data(api.get_participant(participant["id"], OP))["status"] == "SUSPENDED"
        validate_success(api.reinstate_member(member["id"], OP))
        assert get_success_data(api.get_member(member["id"], OP))["status"] == "ACTIVE"
        assert get_success_data(api.get_participant(participant["id"], OP))["status"] == "ACTIVE"

        # Second cycle: the loop is re-traversable, not a one-way pipeline.
        validate_success(api.suspend_member(member["id"],
                                            {"reason": "SECOND_HOLD"}, OP))
        member_now = get_success_data(api.get_member(member["id"], OP))
        assert member_now["status"] == "SUSPENDED"
        assert member_now["suspension_reason"] == "SECOND_HOLD"
        assert get_success_data(api.get_participant(participant["id"], OP))["status"] == "SUSPENDED"
        validate_success(api.reinstate_member(member["id"], OP))
        assert get_success_data(api.get_member(member["id"], OP))["status"] == "ACTIVE"
        assert get_success_data(api.get_participant(participant["id"], OP))["status"] == "ACTIVE"
