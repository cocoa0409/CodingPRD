"""Claim submission lifecycle: cap boundary, contract window, appeal cycle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_diagnostic_order_payload,
    discharge_home,
    get_claim_for_visit,
    queue_follow_up_notice,
    result_order,
    setup_dispositioned_home_visit,
    setup_visit_on_scene,
    set_clock,
    validate_error,
    validate_success,
    get_success_data,
)

ADMIN = TEST_USERS["platform_admin_headers"]
NURSE = TEST_USERS["triage_nurse_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]
ADJUDICATOR = TEST_USERS["payer_adjudicator_headers"]
APP = TEST_USERS["app_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestClaimCapBoundary:
    def _drive_capped_scenario(self, api, iv_units):
        ctx = setup_visit_on_scene(
            app_user="app-K", tech_user="tech-K", md_user="md-K",
            skill_tags=("POCT", "IV_INFUSION"),
            with_contract=True,
            contract_overrides={
                "urgent_base_rate_cents": 40000,
                "standard_base_rate_cents": 40000,
                "place_of_service_modifier_pct": 1.0,
                "max_claim_cents": 46000,
            },
        )
        contract = ctx["contract"]
        validate_success(
            api.create_formulary_entry(
                contract["id"],
                {
                    "drug_code": "IVF-NS-1L", "max_units_per_visit": 10,
                    "requires_physician_preauth": False, "unit_price_cents": 6000,
                },
                ADMIN,
            ),
            expected_status=201,
        )
        iv = validate_success(
            api.create_diagnostic_order(
                ctx["enc"]["id"],
                create_diagnostic_order_payload(
                    order_kind="IV_INFUSION", code="IVF-NS-1L", units=iv_units
                ),
                APP,
            ),
            expected_status=201,
        )
        result_order(ctx, iv["id"], "IV done")
        discharge_home(ctx)
        queue_follow_up_notice(ctx)
        vr, claim = get_claim_for_visit(ctx["vr"]["id"])
        return vr, claim

    def test_total_equal_to_cap_is_allowed(self, api):
        """PRD §3.7: "the claim's `final_total_cents` must not exceed the
        contract's `max_claim_cents`; a total strictly above the cap is
        rejected with `ERR_CLAIM_CAP_EXCEEDED` (HTTP 422), while a total
        exactly equal to the cap is allowed, because the comparison is
        strictly greater-than."

        Design: Difficulty/boundary_precision_check/claim_cap_boundary_strict_greater_than
        """
        vr, claim = self._drive_capped_scenario(api, iv_units=1)
        assert claim["final_total_cents"] == 46000
        submitted = validate_success(
            api.submit_claim(
                claim["id"],
                {"expected_visit_request_version": vr["version"]},
                BILLING,
            )
        )
        assert submitted["status"] == "SUBMITTED"

    def test_total_one_cent_over_cap_would_be_rejected(self, api):
        """PRD §3.7: "a total strictly above the cap is rejected with
        `ERR_CLAIM_CAP_EXCEEDED` (HTTP 422)".

        Design: Difficulty/boundary_precision_check/claim_cap_boundary_strict_greater_than
        """
        vr, claim = self._drive_capped_scenario(api, iv_units=2)
        assert claim["final_total_cents"] == 52000
        resp = api.submit_claim(
            claim["id"],
            {"expected_visit_request_version": vr["version"]},
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_CAP_EXCEEDED)


class TestContractWindowMembership:
    def _drive_windowed_scenario(self, api, ended_clock, plate_suffix, md):
        set_clock("2026-09-15T08:00:00Z")
        ctx = setup_visit_on_scene(
            app_user=f"app-N2{plate_suffix}",
            tech_user=f"tech-N2{plate_suffix}",
            md_user=md,
            clock="2026-09-15T08:00:00Z",
            with_contract=True,
            contract_overrides={
                "effective_from": "2026-01-01T00:00:00Z",
                "effective_to": "2026-09-15T12:00:00Z",
            },
        )
        get_success_data(api.begin_disposition_review(ctx["enc"]["id"], APP))
        set_clock(ended_clock)
        get_success_data(
            api.create_disposition_decision(
                ctx["enc"]["id"],
                {
                    "disposition": "DISCHARGE_HOME",
                    "rationale": "Stable; discharged with precautions reviewed.",
                },
                APP,
            )
        )
        queue_follow_up_notice(ctx)
        vr, claim = get_claim_for_visit(ctx["vr"]["id"])
        return vr, claim

    def test_ended_within_window_submits(self, api):
        """PRD §3.7: "The contract must be in force: its status must be
        `ACTIVE` and its effectiveness window must contain the encounter's
        `ended_at` — `effective_from` at or before `ended_at`, which is
        strictly before `effective_to` — else `ERR_CONTRACT_NOT_IN_FORCE`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/market_response_window_payer_contract_temporal_membership
        """
        vr, claim = self._drive_windowed_scenario(
            api, "2026-09-15T11:59:59Z", "A", "md-N2A"
        )
        submitted = validate_success(
            api.submit_claim(
                claim["id"],
                {"expected_visit_request_version": vr["version"]},
                BILLING,
            )
        )
        assert submitted["status"] == "SUBMITTED"

    def test_ended_exactly_at_effective_to_rejected(self, api):
        """PRD §3.7: "its effectiveness window must contain the encounter's
        `ended_at` — `effective_from` at or before `ended_at`, which is
        strictly before `effective_to` — else `ERR_CONTRACT_NOT_IN_FORCE`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/market_response_window_payer_contract_temporal_membership
        """
        vr, claim = self._drive_windowed_scenario(
            api, "2026-09-15T12:00:00Z", "B", "md-N2B"
        )
        resp = api.submit_claim(
            claim["id"],
            {"expected_visit_request_version": vr["version"]},
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_IN_FORCE)
        vr_after = validate_success(api.get_visit_request(vr["id"], BILLING))
        assert vr_after["status"] in ("DISPOSITIONED", "CLAIM_DRAFT")


class TestClaimAppealCycle:
    def _submitted_claim(self, api):
        ctx = setup_dispositioned_home_visit(
            app_user="app-003", tech_user="tech-003", md_user="md-003",
            with_contract=True,
        )
        queue_follow_up_notice(ctx)
        vr = validate_success(api.get_visit_request(ctx["vr"]["id"], BILLING))
        claim_id = vr["claim_id"]
        submitted = validate_success(
            api.submit_claim(
                claim_id,
                {"expected_visit_request_version": vr["version"]},
                BILLING,
            )
        )
        return ctx, vr, submitted

    def test_two_appeal_rounds_cycle_back_to_submitted(self, api):
        """PRD §3.7: "A `BillingSpecialist` may appeal a denied claim, moving
        it to `APPEALED` and the visit to `CLAIM_APPEALED`, and may resubmit
        an appealed claim, which moves the claim back to `SUBMITTED` with a
        fresh `submitted_at` and the visit back to `CLAIM_SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/claim_cycle_submitted_denied_appealed_submitted
        """
        ctx, vr, claim = self._submitted_claim(api)
        for _ in range(2):
            denied = validate_success(
                api.adjudicate_claim(claim["id"], {"outcome": "DENIED"}, ADJUDICATOR)
            )
            assert denied["status"] == "ADJUDICATED_DENIED"
            appealed = validate_success(api.appeal_claim(claim["id"], BILLING))
            assert appealed["status"] == "APPEALED"
            resubmitted = validate_success(api.resubmit_claim(claim["id"], BILLING))
            assert resubmitted["status"] == "SUBMITTED"

    def test_third_resubmit_rejected_appeal_limit(self, api):
        """PRD §3.7: "The cycle from `SUBMITTED` through denial and appeal
        back to `SUBMITTED` is bounded: at most two appeal rounds are
        permitted, and a resubmission attempted beyond the second appeal is
        rejected with `ERR_APPEAL_LIMIT_REACHED` (HTTP 422)."

        Design: Difficulty/non_linear_state_machine/claim_cycle_submitted_denied_appealed_submitted
        """
        ctx, vr, claim = self._submitted_claim(api)
        claim_id = claim["id"]
        for _ in range(2):
            validate_success(
                api.adjudicate_claim(claim_id, {"outcome": "DENIED"}, ADJUDICATOR)
            )
            validate_success(api.appeal_claim(claim_id, BILLING))
            validate_success(api.resubmit_claim(claim_id, BILLING))
        validate_success(
            api.adjudicate_claim(claim_id, {"outcome": "DENIED"}, ADJUDICATOR)
        )
        validate_success(api.appeal_claim(claim_id, BILLING))
        resp = api.resubmit_claim(claim_id, BILLING)
        validate_error(resp, ApiErrorId.ERR_APPEAL_LIMIT_REACHED)
        vr_after = validate_success(api.get_visit_request(vr["id"], BILLING))
        assert vr_after["status"] == "CLAIM_APPEALED"


class TestClaimRbac:
    def test_payer_adjudicator_cannot_submit_claim(self, api):
        """PRD §4: the `POST /dh/claims/{id}/submit` row authorizes
        `BillingSpecialist` only.
        PRD §2.1: "a role not permitted on the endpoint receives
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/payer_adjudicator_cannot_submit_claim
        """
        ctx = setup_dispositioned_home_visit(
            app_user="app-H", tech_user="tech-H", md_user="md-H",
            with_contract=True,
        )
        queue_follow_up_notice(ctx)
        vr = validate_success(api.get_visit_request(ctx["vr"]["id"], BILLING))
        claim_id = vr["claim_id"]
        resp = api.submit_claim(
            claim_id,
            {"expected_visit_request_version": vr["version"]},
            ADJUDICATOR,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        claim_after = validate_success(api.get_claim(claim_id, BILLING))
        assert claim_after["status"] == "DRAFT"
