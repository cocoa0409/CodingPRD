"""Encounter lifecycle, diagnostic orders, disposition cascades."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_diagnostic_order_payload,
    discharge_home,
    get_claim_for_visit,
    make_field_technician_headers,
    make_supervising_physician_headers,
    result_order,
    setup_visit_on_scene,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
NURSE = TEST_USERS["triage_nurse_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
APP = TEST_USERS["app_headers"]


class TestDispositionGating:
    def test_review_blocked_while_order_still_ordered(self, api):
        """PRD §3.5: "every diagnostic order on the encounter must already sit
        in `RESULTED`, `VERIFIED`, `AMENDED`, or `CANCELLED`; any order still
        in `ORDERED` or `COLLECTED` blocks the review with
        `ERR_UNRESOLVED_DIAGNOSTICS` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/encounter_disposition_requires_all_orders_resolved
        """
        ctx = setup_visit_on_scene(
            app_user="app-M", tech_user="tech-M", md_user="md-M",
            skill_tags=("POCT", "IV_INFUSION"),
        )
        validate_success(
            api.create_diagnostic_order(
                ctx["enc"]["id"],
                create_diagnostic_order_payload(
                    order_kind="POCT", code="POCT-STREP-A", units=1
                ),
                APP,
            ),
            expected_status=201,
        )
        resp = api.begin_disposition_review(ctx["enc"]["id"], APP)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_DIAGNOSTICS)
        enc_after = validate_success(api.get_encounter(ctx["enc"]["id"], APP))
        assert enc_after["status"] == "DIAGNOSTICS"

    def test_review_succeeds_after_all_orders_resolved(self, api):
        """PRD §3.5: "every diagnostic order on the encounter must already sit
        in `RESULTED`, `VERIFIED`, `AMENDED`, or `CANCELLED`".

        Design: Difficulty/cross_entity_state_dependency/encounter_disposition_requires_all_orders_resolved
        """
        ctx = setup_visit_on_scene(app_user="app-M2", tech_user="tech-M2")
        order = validate_success(
            api.create_diagnostic_order(
                ctx["enc"]["id"],
                create_diagnostic_order_payload(
                    order_kind="POCT", code="POCT-STREP-A", units=1
                ),
                APP,
            ),
            expected_status=201,
        )
        result_order(ctx, order["id"], "negative")
        reviewed = validate_success(
            api.begin_disposition_review(ctx["enc"]["id"], APP)
        )
        assert reviewed["status"] == "DISPOSITION_REVIEW"


class TestDischargeCascade:
    def test_discharge_creates_claim_and_two_checkins(self, api):
        """PRD §3.6: "The encounter moves to `DISCHARGED_HOME` with `ended_at`
        stamped; the visit moves to `DISPOSITIONED`; the dispatch assignment
        completes, the care team's `active_dispatch_count` falls by one, and a
        team reaching zero returns to `AVAILABLE`. A `Claim` row is created
        automatically in `DRAFT` status with both totals computed (see §3.7),
        and the visit's `claim_id` is pointed at it. Two **MonitoringCheckIn**
        rows are scheduled automatically at 24 hours and at 72 hours after
        `ended_at`."

        Design: Corner/state_machines/encounter_cascade_creates_claim_and_monitoring_checkins
        """
        ctx = setup_visit_on_scene(app_user="app-Y", tech_user="tech-Y",
                                   with_contract=True)
        disp = discharge_home(ctx)
        assert disp["disposition"] == "DISCHARGE_HOME"
        enc_after = validate_success(api.get_encounter(ctx["enc"]["id"], APP))
        assert enc_after["status"] == "DISCHARGED_HOME"
        assert enc_after["ended_at"] is not None
        vr_after = validate_success(api.get_visit_request(ctx["vr"]["id"], DISPATCHER))
        assert vr_after["status"] == "DISPOSITIONED"
        assert vr_after["claim_id"] is not None
        da_after = validate_success(
            api.get_dispatch_assignment(ctx["da"]["id"], DISPATCHER)
        )
        assert da_after["status"] == "COMPLETED"
        team_after = validate_success(
            api.get_care_team(ctx["team"]["id"], DISPATCHER)
        )
        assert team_after["active_dispatch_count"] == 0
        assert team_after["status"] == "AVAILABLE"
        checkins = validate_success(
            api.list_visit_monitoring_checkins(ctx["vr"]["id"], NURSE)
        )
        assert len(checkins) == 2
        claim = validate_success(api.get_claim(vr_after["claim_id"], TEST_USERS["billing_specialist_headers"]))
        assert claim["status"] == "DRAFT"


class TestClaimTotalsDualVariant:
    def test_resulted_iv_line_in_both_totals(self, api):
        """PRD §3.7: "The `provisional_total_cents` is optimistic: while the
        claim is in `DRAFT` it sums the base line plus the lines of every
        diagnostic order in `ORDERED`, `COLLECTED`, `RESULTED`, or `AMENDED`...
        The `final_total_cents` is conservative: it sums the base line plus
        only the orders in `RESULTED`, `VERIFIED`, or `AMENDED`, excluding
        `CANCELLED`".
        PRD §3.7: "the base visit line is the applicable contracted base rate —
        `urgent_base_rate_cents` when the visit's `acuity_band` is `URGENT`...
        multiplied by the contract's `place_of_service_modifier_pct`, rounded
        half-up to integer cents".

        Design: Difficulty/dual_variant_calc/claim_total_provisional_includes_unresulted_but_final_excludes
        """
        # Setup: contract urgent rate 40000, modifier 0.85 -> base line 34000.
        # One RESULTED IV order units=2 @ 3000 -> 6000. No other orders left
        # unresolved at disposition (a second POCT order is cancelled first).
        ctx = setup_visit_on_scene(
            app_user="app-001", tech_user="tech-001", md_user="md-001",
            skill_tags=("POCT", "IV_INFUSION"), with_contract=True,
        )
        contract = ctx["contract"]
        get_resp = api.create_formulary_entry(
            contract["id"],
            {
                "drug_code": "IVF-NS-1L", "max_units_per_visit": 3,
                "requires_physician_preauth": False, "unit_price_cents": 3000,
            },
            ADMIN,
        )
        validate_success(get_resp, expected_status=201)
        iv = validate_success(
            api.create_diagnostic_order(
                ctx["enc"]["id"],
                create_diagnostic_order_payload(
                    order_kind="IV_INFUSION", code="IVF-NS-1L", units=2
                ),
                APP,
            ),
            expected_status=201,
        )
        result_order(ctx, iv["id"], "infused uneventfully")
        # A POCT order left ORDERED would block review; cancel it first.
        poct = validate_success(
            api.create_diagnostic_order(
                ctx["enc"]["id"],
                create_diagnostic_order_payload(
                    order_kind="POCT", code="POCT-STREP-A", units=1
                ),
                APP,
            ),
            expected_status=201,
        )
        validate_success(api.cancel_diagnostic_order(poct["id"], APP))
        discharge_home(ctx)
        vr, claim = get_claim_for_visit(ctx["vr"]["id"])
        assert claim["status"] == "DRAFT"
        assert claim["provisional_total_cents"] == 40000, (
            "provisional = 34000 base + 6000 IV line"
        )
        assert claim["final_total_cents"] == 40000

    def test_amend_then_reresult_keeps_line_in_both_variants(self, api):
        """PRD §3.5: "Amendment moves the order to `AMENDED`, and a subsequent
        re-result moves it back to `RESULTED` with the line amount recomputed
        — the `RESULTED`-to-`AMENDED`-to-`RESULTED` cycle may repeat."
        PRD §3.7: "Both totals recompute whenever a diagnostic order is
        resulted, amended, re-resulted, or cancelled against the visit."

        Design: Difficulty/dual_variant_calc/claim_total_provisional_includes_unresulted_but_final_excludes
        """
        ctx = setup_visit_on_scene(
            app_user="app-001", tech_user="tech-001", md_user="md-001",
            skill_tags=("POCT", "IV_INFUSION"), with_contract=True,
        )
        contract = ctx["contract"]
        validate_success(
            api.create_formulary_entry(
                contract["id"],
                {
                    "drug_code": "IVF-NS-1L", "max_units_per_visit": 3,
                    "requires_physician_preauth": False, "unit_price_cents": 3000,
                },
                ADMIN,
            ),
            expected_status=201,
        )
        iv = validate_success(
            api.create_diagnostic_order(
                ctx["enc"]["id"],
                create_diagnostic_order_payload(
                    order_kind="IV_INFUSION", code="IVF-NS-1L", units=2
                ),
                APP,
            ),
            expected_status=201,
        )
        result_order(ctx, iv["id"], "infused uneventfully")
        discharge_home(ctx)
        vr, claim = get_claim_for_visit(ctx["vr"]["id"])
        tech = make_field_technician_headers(ctx["tech_user"])
        amended = validate_success(
            api.amend_diagnostic_order(
                iv["id"], {"result_value": "infused; mild site erythema"}, tech
            )
        )
        assert amended["status"] == "AMENDED"
        claim_mid = validate_success(api.get_claim(claim["id"], TEST_USERS["billing_specialist_headers"]))
        assert claim_mid["provisional_total_cents"] == 40000
        assert claim_mid["final_total_cents"] == 40000
        reresulted = validate_success(
            api.result_diagnostic_order(
                iv["id"], {"result_value": "infused; site clean"}, tech
            )
        )
        assert reresulted["status"] == "RESULTED"
        claim_after = validate_success(api.get_claim(claim["id"], TEST_USERS["billing_specialist_headers"]))
        assert claim_after["provisional_total_cents"] == 40000
        assert claim_after["final_total_cents"] == 40000
        assert claim_after["status"] == "DRAFT"


class TestClaimPerLineRounding:
    def test_base_line_rounded_half_up_per_line(self, api):
        """PRD §3.7: "the base visit line is the applicable contracted base
        rate ... multiplied by the contract's `place_of_service_modifier_pct`,
        rounded half-up to integer cents".
        PRD §2.8: "Where a multiplication produces a fractional cent — the
        base visit line applies a percentage modifier to a contracted rate —
        the line amount is rounded half-up to the nearest integer cent, and
        the rounding is applied per line before any summation".

        Design: Difficulty/combinatorial_formula/claim_total_per_line_rounding_then_sum
        """
        # urgent rate 33333 * 0.5 = 16666.5 -> round_half_up -> 16667
        ctx = setup_visit_on_scene(
            app_user="app-002", tech_user="tech-002", md_user="md-002",
            skill_tags=("POCT", "IV_INFUSION"),
            with_contract=True,
            contract_overrides={
                "urgent_base_rate_cents": 33333,
                "standard_base_rate_cents": 20000,
                "place_of_service_modifier_pct": 0.5,
            },
        )
        contract = ctx["contract"]
        validate_success(
            api.create_formulary_entry(
                contract["id"],
                {
                    "drug_code": "IVF-NS-1L", "max_units_per_visit": 5,
                    "requires_physician_preauth": False, "unit_price_cents": 2999,
                },
                ADMIN,
            ),
            expected_status=201,
        )
        iv = validate_success(
            api.create_diagnostic_order(
                ctx["enc"]["id"],
                create_diagnostic_order_payload(
                    order_kind="IV_INFUSION", code="IVF-NS-1L", units=1
                ),
                APP,
            ),
            expected_status=201,
        )
        result_order(ctx, iv["id"], "IV complete")
        discharge_home(ctx)
        vr, claim = get_claim_for_visit(ctx["vr"]["id"])
        lines = validate_success(
            api.list_claim_lines(claim["id"], TEST_USERS["billing_specialist_headers"])
        )
        base_lines = [ln for ln in lines if ln["line_kind"] == "BASE_VISIT"]
        assert len(base_lines) == 1
        assert base_lines[0]["amount_cents"] == 16667, (
            "base line must be round_half_up(33333 * 0.5) = 16667"
        )

    def test_iv_drug_line_uses_line_amount_verbatim(self, api):
        """PRD §3.7: "diagnostic and IV-drug lines take their diagnostic
        order's `line_amount_cents` verbatim."
        PRD §3.5: "computes `line_amount_cents` as the units multiplied by the
        unit price, rounded half-up to integer cents."

        Design: Difficulty/combinatorial_formula/claim_total_per_line_rounding_then_sum
        """
        ctx = setup_visit_on_scene(
            app_user="app-002b", tech_user="tech-002b", md_user="md-002b",
            skill_tags=("POCT", "IV_INFUSION"),
            with_contract=True,
            contract_overrides={
                "urgent_base_rate_cents": 33333,
                "standard_base_rate_cents": 20000,
                "place_of_service_modifier_pct": 0.5,
            },
        )
        contract = ctx["contract"]
        validate_success(
            api.create_formulary_entry(
                contract["id"],
                {
                    "drug_code": "IVF-NS-1L", "max_units_per_visit": 5,
                    "requires_physician_preauth": False, "unit_price_cents": 2999,
                },
                ADMIN,
            ),
            expected_status=201,
        )
        iv = validate_success(
            api.create_diagnostic_order(
                ctx["enc"]["id"],
                create_diagnostic_order_payload(
                    order_kind="IV_INFUSION", code="IVF-NS-1L", units=1
                ),
                APP,
            ),
            expected_status=201,
        )
        result_order(ctx, iv["id"], "IV complete")
        discharge_home(ctx)
        vr, claim = get_claim_for_visit(ctx["vr"]["id"])
        lines = validate_success(
            api.list_claim_lines(claim["id"], TEST_USERS["billing_specialist_headers"])
        )
        iv_lines = [ln for ln in lines if ln["line_kind"] == "IV_DRUG"]
        assert len(iv_lines) == 1
        assert iv_lines[0]["amount_cents"] == 2999
        assert iv_lines[0]["ref_diagnostic_order_id"] == iv["id"]


class TestFormularyGuards:
    def test_cap_violation_fires_before_preauth_check(self, api):
        """PRD §2.11: "the business rules — safety, temporal, fiscal, and
        payload shape — in the order each subsection of §3 lists them."
        PRD §3.5: "First, the per-visit cap: the total units across every
        intravenous order for the encounter sharing the same drug code ...
        must not exceed the formulary entry's `max_units_per_visit` for the
        applicable payer contract; a breach is rejected with
        `ERR_FORMULARY_CAP_EXCEEDED` (HTTP 422). Second, pre-authorization:
        when the formulary entry's `requires_physician_preauth` is true, the
        order must carry `physician_preauth_obtained` set true and a
        `physician_preauth_by` equal to the care team's
        `supervising_physician_user_id`; a missing or mismatched authorization
        is rejected with `ERR_PREAUTH_REQUIRED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_iv_order
        """
        ctx = setup_visit_on_scene(
            app_user="app-I", tech_user="tech-I", md_user="md-I",
            skill_tags=("POCT", "IV_INFUSION"),
            chief_complaint="severe dehydration", with_contract=True,
        )
        contract = ctx["contract"]
        validate_success(
            api.create_formulary_entry(
                contract["id"],
                {
                    "drug_code": "IV-ABX-VANCO-1G", "max_units_per_visit": 1,
                    "requires_physician_preauth": True, "unit_price_cents": 15000,
                },
                ADMIN,
            ),
            expected_status=201,
        )
        # units=2 exceeds cap of 1 AND preauth missing -> cap error fires first.
        resp = api.create_diagnostic_order(
            ctx["enc"]["id"],
            {
                "order_kind": "IV_INFUSION", "code": "IV-ABX-VANCO-1G",
                "units": 2, "physician_preauth_obtained": False,
            },
            APP,
        )
        validate_error(resp, ApiErrorId.ERR_FORMULARY_CAP_EXCEEDED)

    def test_preauth_required_when_flagged(self, api):
        """PRD §3.5: "when the formulary entry's `requires_physician_preauth`
        is true, the order must carry `physician_preauth_obtained` set true
        and a `physician_preauth_by` equal to the care team's
        `supervising_physician_user_id`; a missing or mismatched authorization
        is rejected with `ERR_PREAUTH_REQUIRED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_iv_order
        """
        ctx = setup_visit_on_scene(
            app_user="app-I2b", tech_user="tech-I2b", md_user="md-I2b",
            skill_tags=("POCT", "IV_INFUSION"),
            chief_complaint="severe dehydration", with_contract=True,
        )
        contract = ctx["contract"]
        validate_success(
            api.create_formulary_entry(
                contract["id"],
                {
                    "drug_code": "IV-ABX-VANCO-1G", "max_units_per_visit": 5,
                    "requires_physician_preauth": True, "unit_price_cents": 15000,
                },
                ADMIN,
            ),
            expected_status=201,
        )
        resp = api.create_diagnostic_order(
            ctx["enc"]["id"],
            {
                "order_kind": "IV_INFUSION", "code": "IV-ABX-VANCO-1G",
                "units": 1, "physician_preauth_obtained": False,
            },
            APP,
        )
        validate_error(resp, ApiErrorId.ERR_PREAUTH_REQUIRED)


class TestSegregationOfDuties:
    def test_verify_by_result_actor_rejected_then_physician_succeeds(self, api):
        """PRD §3.5: "A `SupervisingPhysician` verifies a `RESULTED` order,
        moving it to `VERIFIED`, with segregation of duties enforced: the
        verifying user's id must differ from the id of the technician who
        resulted the order, else `ERR_SOD_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/segregation_of_duties_result_verify_different_users
        """
        ctx = setup_visit_on_scene(
            app_user="app-I2", tech_user="tech-I2", md_user="md-I2",
            skill_tags=("POCT", "IV_INFUSION"),
            chief_complaint="dehydration",
        )
        order = validate_success(
            api.create_diagnostic_order(
                ctx["enc"]["id"],
                create_diagnostic_order_payload(
                    order_kind="POCT", code="POCT-STREP-A", units=1
                ),
                APP,
            ),
            expected_status=201,
        )
        result_order(ctx, order["id"], "done")
        resp = api.verify_diagnostic_order(
            order["id"], make_supervising_physician_headers("tech-I2")
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        order_mid = validate_success(
            api.get_diagnostic_order(order["id"], TEST_USERS["supervising_physician_headers"])
        )
        assert order_mid["status"] == "RESULTED"
        verified = validate_success(
            api.verify_diagnostic_order(
                order["id"], make_supervising_physician_headers("md-I2")
            )
        )
        assert verified["status"] == "VERIFIED"
