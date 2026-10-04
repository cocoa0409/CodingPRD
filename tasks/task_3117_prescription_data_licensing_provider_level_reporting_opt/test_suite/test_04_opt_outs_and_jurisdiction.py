"""Prescriber opt-outs and jurisdictional filtering: lifecycle gating,
activation/lift cascades on deliverable counts, compiled-delivery recalls,
duplicate guards, and state-law restrictions."""
from test_helpers import (
    ApiErrorId,
    create_active_opt_out,
    create_opt_out,
    create_prescriber,
    create_verified_opt_out,
    setup_compiled_delivery,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import DAM, PA, PO


class TestOptOutActivationCascade:
    def test_activation_recalls_compiled_delivery(self, api):
        """PRD §3.4: "Activation is where an opt-out bites, in two links. Link one: every report
        product in `ACTIVE` status whose `prescriber_ids` contains this prescriber has its
        `deliverable_prescriber_count` decremented by 1. Link two: for each product so mutated,
        every delivery of that product in `COMPILED` status whose `included_prescriber_ids`
        contains this prescriber is recalled — transitioning to `RECALLED` with `recall_count`
        incremented by 1, `must_recompile` set true, and the client's entitlement credited back by
        the number of cells in that delivery's `compiled_cell_ids`."

        Design: Difficulty/transitive_cascade/optout_activation_recalls_compiled_delivery
        """
        p1 = create_prescriber(full_name="Dr One", npi="NPI-001", state_code="TX")
        p2 = create_prescriber(full_name="Dr Two", npi="NPI-002", state_code="TX",
                               specialty="ONCOLOGY")
        opt_out = create_verified_opt_out(p1["id"], reason="prescriber request")
        ctx = setup_compiled_delivery(
            cells=({"period_code": "2026-08", "geography_code": "TX-ALL"},),
            prescriber_ids=[p1["id"], p2["id"]],
        )
        assert ctx["product"]["deliverable_prescriber_count"] == 2
        assert sorted(ctx["delivery"]["included_prescriber_ids"]) == sorted([p1["id"], p2["id"]])

        activated = validate_success(api.activate_opt_out(opt_out["id"], PO))
        assert activated["status"] == "ACTIVE"
        product_now = validate_success(api.get_product(ctx["product"]["id"], PA))
        assert product_now["deliverable_prescriber_count"] == 1
        delivery_now = validate_success(api.get_delivery(ctx["delivery"]["id"], PA))
        assert delivery_now["status"] == "RECALLED"
        assert delivery_now["recall_count"] == 1
        assert delivery_now["must_recompile"] is True
        client_now = validate_success(api.get_client(ctx["client"]["id"], PA))
        assert client_now["entitlement_cells_balance"] == 100, (
            "the cascade recall credits the compile debit back"
        )

    def test_activation_decrements_deliverable_count_link_one(self, api):
        """PRD §3.4: "Link one: every report product in `ACTIVE` status whose `prescriber_ids`
        contains this prescriber has its `deliverable_prescriber_count` decremented by 1."

        Design: Difficulty/transitive_cascade/optout_activation_recalls_compiled_delivery
        """
        p1 = create_prescriber(full_name="Dr One", npi="NPI-001", state_code="TX")
        p2 = create_prescriber(full_name="Dr Two", npi="NPI-002", state_code="TX",
                               specialty="ONCOLOGY")
        opt_out = create_verified_opt_out(p1["id"])
        ctx = setup_compiled_delivery(
            cells=({"period_code": "2026-08", "geography_code": "TX-ALL"},),
            prescriber_ids=[p1["id"], p2["id"]],
        )
        assert ctx["product"]["deliverable_prescriber_count"] == 2
        validate_success(api.activate_opt_out(opt_out["id"], PO))
        product_now = validate_success(api.get_product(ctx["product"]["id"], PA))
        assert product_now["deliverable_prescriber_count"] == 1


class TestOptOutLiftCompensation:
    def test_activate_then_lift_restores_deliverable_count(self, api):
        """PRD §3.4: "Lifting an `ACTIVE` opt-out — again a `PrivacyOfficer` act, terminal for the
        opt-out at `LIFTED` — compensates link one exactly: every report product whose
        `prescriber_ids` contains the prescriber has its `deliverable_prescriber_count`
        incremented by 1."

        Design: Difficulty/compensating_invariant/optout_lift_restores_deliverable_count
        """
        p1 = create_prescriber(full_name="Dr A", npi="NPI-301", state_code="TX")
        p2 = create_prescriber(full_name="Dr B", npi="NPI-302", state_code="TX",
                               specialty="ONCOLOGY")
        opt_out = create_verified_opt_out(p1["id"])
        ctx = setup_compiled_delivery(
            cells=({"period_code": "2026-08", "geography_code": "TX-ALL"},),
            prescriber_ids=[p1["id"], p2["id"]],
        )
        assert ctx["product"]["deliverable_prescriber_count"] == 2
        validate_success(api.activate_opt_out(opt_out["id"], PO))
        mid = validate_success(api.get_product(ctx["product"]["id"], PA))
        assert mid["deliverable_prescriber_count"] == 1
        lifted = validate_success(api.lift_opt_out(opt_out["id"], PO))
        assert lifted["status"] == "LIFTED"
        restored = validate_success(api.get_product(ctx["product"]["id"], PA))
        assert restored["deliverable_prescriber_count"] == 2, (
            "activate + lift leaves the deliverable count unchanged"
        )

    def test_lifted_opt_out_is_terminal(self, api):
        """PRD §3.4: "Lifting an `ACTIVE` opt-out — again a `PrivacyOfficer` act, terminal for the
        opt-out at `LIFTED` — compensates link one exactly: every report product whose
        `prescriber_ids` contains the prescriber has its `deliverable_prescriber_count`
        incremented by 1."

        Design: Difficulty/compensating_invariant/optout_lift_restores_deliverable_count
        """
        p1 = create_prescriber(full_name="Dr A", npi="NPI-301", state_code="TX")
        opt_out = create_active_opt_out(p1["id"])
        lifted = validate_success(api.lift_opt_out(opt_out["id"], PO))
        assert lifted["status"] == "LIFTED"
        fetched = validate_success(api.get_opt_out(opt_out["id"], PA))
        assert fetched["status"] == "LIFTED"


class TestOptOutGuards:
    def test_initial_state_is_submitted(self, api):
        """PRD §3.4: "The opt-out begins `SUBMITTED`."

        Design: Corner/state_machines/optout_created_initial_submitted
        """
        prescriber = create_prescriber(full_name="Dr Init", npi="NPI-900",
                                       specialty="PRIMARY_CARE")
        opt_out = validate_success(
            api.create_opt_out(prescriber["id"], {}, PO), expected_status=201
        )
        assert opt_out["status"] == "SUBMITTED"
        assert opt_out["version"] == 1

    def test_duplicate_opt_out_rejected_then_allowed_after_reject(self, api):
        """PRD §3.4: "the prescriber must be `ACTIVE` (`ERR_PRESCRIBER_NOT_ACTIVE`), and no other
        opt-out for the same prescriber may exist in `SUBMITTED`, `VERIFIED`, or `ACTIVE` status
        (`ERR_DUPLICATE_OPT_OUT`)."

        Design: Corner/validations/duplicate_optout_rejected
        """
        prescriber = create_prescriber(full_name="Dr Dup", npi="NPI-601")
        first = create_opt_out(prescriber["id"])
        assert first["status"] == "SUBMITTED"
        resp = api.create_opt_out(prescriber["id"], {}, PO)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPT_OUT)
        validate_success(api.reject_opt_out(first["id"], PO))
        second = validate_success(
            api.create_opt_out(prescriber["id"], {"reason": "second attempt"}, PO),
            expected_status=201,
        )
        assert second["status"] == "SUBMITTED"

    def test_verify_blocked_when_prescriber_inactive(self, api):
        """PRD §3.4: "Verification (`SUBMITTED` → `VERIFIED`) and activation (`VERIFIED` → `ACTIVE`)
        are both `PrivacyOfficer` acts, and both require the prescriber to still be `ACTIVE` — an
        opt-out for a deactivated prescriber cannot advance, surfacing
        `ERR_PRESCRIBER_NOT_ACTIVE`, while any other state mismatch surfaces
        `ERR_OPT_OUT_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/optout_verify_blocked_when_prescriber_inactive
        """
        prescriber = create_prescriber(full_name="Dr Y", npi="NPI-202", state_code="OR",
                                       specialty="ENDOCRINOLOGY")
        opt_out = create_opt_out(prescriber["id"])
        validate_success(api.deactivate_prescriber(prescriber["id"], PA))
        resp = api.verify_opt_out(opt_out["id"], PO)
        validate_error(resp, ApiErrorId.ERR_PRESCRIBER_NOT_ACTIVE)
        fetched = validate_success(api.get_opt_out(opt_out["id"], PA))
        assert fetched["status"] == "SUBMITTED"

    def test_verify_succeeds_while_prescriber_active(self, api):
        """PRD §3.4: "Verification (`SUBMITTED` → `VERIFIED`) and activation (`VERIFIED` → `ACTIVE`)
        are both `PrivacyOfficer` acts, and both require the prescriber to still be `ACTIVE` — an
        opt-out for a deactivated prescriber cannot advance, surfacing
        `ERR_PRESCRIBER_NOT_ACTIVE`, while any other state mismatch surfaces
        `ERR_OPT_OUT_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/optout_verify_blocked_when_prescriber_inactive
        """
        prescriber = create_prescriber(full_name="Dr Y", npi="NPI-202", state_code="OR",
                                       specialty="ENDOCRINOLOGY")
        opt_out = create_opt_out(prescriber["id"])
        verified = validate_success(api.verify_opt_out(opt_out["id"], PO))
        assert verified["status"] == "VERIFIED"


class TestJurisdictionalFiltering:
    def test_forced_include_of_restricted_prescriber_rejected(self, api):
        """PRD §3.6: "the safety checks on any `include_prescriber_ids` supplied in the payload — an
        entry holding an `ACTIVE` opt-out is rejected with `ERR_PRESCRIBER_OPT_OUT_VIOLATION`, and
        an entry whose practice state has an effective restrictive jurisdiction rule is rejected
        with `ERR_JURISDICTION_RESTRICTED`"

        Design: Corner/validations/include_jurisdiction_restricted_prescriber_rejected
        """
        from test_helpers import setup_scheduled_delivery

        p1 = create_prescriber(full_name="Dr CA", npi="NPI-501", state_code="CA",
                               specialty="ONCOLOGY")
        validate_success(
            api.create_jurisdiction_rule(
                {
                    "state_code": "CA",
                    "restrict_prescriber_identifiable": True,
                    "effective_from": "2026-01-01",
                },
                PO,
            ),
            expected_status=201,
        )
        ctx = setup_scheduled_delivery(
            cells=({"period_code": "2026-08", "geography_code": "CA-ALL",
                    "specialty": "ONCOLOGY"},),
            prescriber_ids=[p1["id"]],
        )
        resp = api.compile_delivery(
            ctx["delivery"]["id"], PA, payload={"include_prescriber_ids": [p1["id"]]}
        )
        validate_error(resp, ApiErrorId.ERR_JURISDICTION_RESTRICTED)

    def test_plain_compile_auto_excludes_restricted_prescriber(self, api):
        """PRD §3.6: "On success, compilation selects exactly those matching `CURRENT` cells —
        sorted by `geography_code` ascending, then `specialty` ascending, then `created_at`
        ascending — into `compiled_cell_ids`; sets `included_prescriber_ids` to the product's
        `prescriber_ids` minus prescriber panel members with `ACTIVE` opt-outs minus those
        restricted by effective jurisdiction rules, or, when a valid `include_prescriber_ids` was
        supplied, exactly that supplied list; computes `fee_cents`; and debits the client's
        `entitlement_cells_balance` by the number of compiled cells."

        Design: Corner/validations/include_jurisdiction_restricted_prescriber_rejected
        """
        from test_helpers import setup_scheduled_delivery

        p1 = create_prescriber(full_name="Dr CA", npi="NPI-501", state_code="CA",
                               specialty="ONCOLOGY")
        validate_success(
            api.create_jurisdiction_rule(
                {
                    "state_code": "CA",
                    "restrict_prescriber_identifiable": True,
                    "effective_from": "2026-01-01",
                },
                PO,
            ),
            expected_status=201,
        )
        ctx = setup_scheduled_delivery(
            cells=({"period_code": "2026-08", "geography_code": "CA-ALL",
                    "specialty": "ONCOLOGY"},),
            prescriber_ids=[p1["id"]],
        )
        compiled = validate_success(api.compile_delivery(ctx["delivery"]["id"], PA))
        assert compiled["status"] == "COMPILED"
        assert compiled["included_prescriber_ids"] == [], (
            "the restricted prescriber is auto-excluded from the compiled delivery"
        )
