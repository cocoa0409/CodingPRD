"""Claims and billing: repricing rounding, deductible application, accumulator
compensation, savings variants, and negotiation rounds."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    claim_line, create_billing_case_payload,
    set_clock, setup_employer_with_member, setup_provider,
    grant_consent, setup_claim, setup_adjudicated_claim,
    setup_billing_case_error_identified,
)
from test_helpers.test_users import (
    make_member_headers,
    make_billing_advocate_headers,
    make_plan_administrator_headers,
)

PLAN_ADMIN = None  # bound in each test via make_plan_administrator_headers


def _plan():
    return make_plan_administrator_headers("pa-1")


def _advocate():
    return make_billing_advocate_headers("ba-1")


class TestClaimCreation:
    def test_claim_create_computes_error_line_count(self, api):
        """PRD §3.7: "The claim is born `RECEIVED` with its `error_line_count`
        computed at creation as the number of lines whose error flag is not
        `NONE`; `repriced_total_cents`, `deductible_applied_cents`, and
        `member_responsibility_cents` remain null until adjudication."

        Design: Corner/entities/claim_create_computes_error_line_count
        """
        set_clock()
        _, member = setup_employer_with_member()
        provider = setup_provider(name="Osborne Clinic")
        claim = setup_claim(
            member, provider,
            billed_amount_cents=30000, allowed_amount_cents=25000,
            lines=[
                claim_line("A", 10000, 1.0, "DUPLICATE"),
                claim_line("B", 10000, 0.9, "UPCODING"),
                claim_line("C", 10000, 1.0, "NONE"),
            ])
        assert claim["error_line_count"] == 2
        assert claim["status"] == "RECEIVED"
        assert claim["repriced_total_cents"] is None


class TestClaimRepricingRounding:
    def test_per_line_rounding_beats_sum_then_round(self, api):
        """PRD §3.7: "The claim's `repriced_total_cents` is the sum of the
        per-line rounded amounts — each line is rounded first and then summed,
        never summed unrounded and rounded once, because the two orders can
        disagree by a cent."
        PRD §3.7: "An `UPCODING` line reprices to its `billed_cents`
        multiplied by its `schedule_rate`, rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/claim_repricing_per_line_rounding_beats_sum_then_round
        """
        set_clock()
        _, member = setup_employer_with_member()
        provider = setup_provider(name="Peak Surgical", specialty="SURGERY")
        claim = setup_claim(
            member, provider,
            billed_amount_cents=2331, allowed_amount_cents=2000,
            lines=[
                claim_line("A", 777, 0.666, "UPCODING"),
                claim_line("B", 777, 0.666, "UPCODING"),
                claim_line("C", 777, 0.666, "UPCODING"),
            ])
        data = validate_success(api.adjudicate_claim(claim["id"], _plan()))
        # 777 * 0.666 = 517.482 -> 517 per line; 517*3 = 1551 (not 1552)
        assert data["repriced_total_cents"] == 1551

    def test_duplicate_lines_reprice_to_zero_and_clean_lines_keep_billed(
            self, api):
        """PRD §3.7: "Step one, repricing: walk the lines in array order. A
        `DUPLICATE` line reprices to zero cents. An `UPCODING` line reprices to
        its `billed_cents` multiplied by its `schedule_rate`, rounded half-up to
        whole cents. A clean line keeps its `billed_cents`."

        Design: Difficulty/combinatorial_formula/claim_repricing_per_line_rounding_beats_sum_then_round
        """
        set_clock()
        _, member = setup_employer_with_member()
        provider = setup_provider(name="Peak Surgical", specialty="SURGERY")
        claim = setup_claim(
            member, provider,
            billed_amount_cents=150000, allowed_amount_cents=100000,
            lines=[
                claim_line("D", 50000, 0.9, "DUPLICATE"),
                claim_line("U", 50000, 0.702, "UPCODING"),
                claim_line("N", 50000, 1.0, "NONE"),
            ])
        data = validate_success(api.adjudicate_claim(claim["id"], _plan()))
        # 0 + round(35100.0) + 50000 = 85100
        assert data["repriced_total_cents"] == 85100

    def test_immediate_consistency_mutation_visible_in_same_response(
            self, api, platform_admin_headers):
        """PRD §3.7: "Adjudication then adds `deductible_applied_cents` to the
        member's `deductible_used_cents`, adds `member_responsibility_cents` to
        `oop_used_cents`, and bumps the member's `version`."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_same_response
        """
        set_clock()
        _, member = setup_employer_with_member(
            member_overrides={"deductible_limit_cents": 100000})
        provider = setup_provider(name="Imm Clinic")
        claim = setup_claim(
            member, provider,
            billed_amount_cents=100000, allowed_amount_cents=100000,
            lines=[claim_line("A", 100000, 0.7, "UPCODING")])

        body = validate_success(api.adjudicate_claim(claim["id"], _plan()))
        assert body["repriced_total_cents"] == 70000
        assert body["deductible_applied_cents"] == 100000

        reread = validate_success(api.get_claim(claim["id"], _plan()))
        assert reread["repriced_total_cents"] == 70000
        assert reread["deductible_applied_cents"] == 100000

        m = validate_success(api.get_member(
            member["id"], platform_admin_headers))
        assert m["deductible_used_cents"] == 100000


class TestDeductibleApplication:
    def test_deductible_saturates_exactly_at_limit(
            self, api, platform_admin_headers):
        """PRD §3.7: "The remaining deductible is the member's
        `deductible_limit_cents` minus `deductible_used_cents`, floored at
        zero; this claim's `deductible_applied_cents` is the smaller of that
        remainder and the claim's `allowed_amount_cents` — a member whose used
        amount already equals the limit exactly applies nothing."

        Design: Difficulty/boundary_precision_check/deductible_saturates_exactly_at_limit
        """
        set_clock()
        _, member = setup_employer_with_member(
            member_overrides={"deductible_limit_cents": 100000})
        provider = setup_provider(name="Metro Care")
        c1 = setup_claim(member, provider, service_date="2026-07-01",
                         billed_amount_cents=100000, allowed_amount_cents=100000,
                         lines=[claim_line("A", 100000, 1.0, "NONE")])
        c2 = setup_claim(member, provider, service_date="2026-08-01",
                         billed_amount_cents=50000, allowed_amount_cents=50000,
                         lines=[claim_line("B", 50000, 1.0, "NONE")])

        d1 = validate_success(api.adjudicate_claim(c1["id"], _plan()))
        assert d1["deductible_applied_cents"] == 100000
        assert d1["member_responsibility_cents"] == 100000

        d2 = validate_success(api.adjudicate_claim(c2["id"], _plan()))
        assert d2["deductible_applied_cents"] == 0
        assert d2["member_responsibility_cents"] == 10000

        m = validate_success(api.get_member(
            member["id"], platform_admin_headers))
        assert m["deductible_used_cents"] == 100000

    def test_deductible_one_cent_below_limit_still_applies(self, api):
        """PRD §3.7: "this claim's `deductible_applied_cents` is the smaller of
        that remainder and the claim's `allowed_amount_cents` — a member whose
        used amount already equals the limit exactly applies nothing."

        Design: Difficulty/boundary_precision_check/deductible_saturates_exactly_at_limit
        """
        set_clock()
        _, member = setup_employer_with_member(
            member_overrides={"deductible_limit_cents": 100000})
        provider = setup_provider(name="Metro Care")
        claim = setup_claim(
            member, provider, service_date="2026-07-01",
            billed_amount_cents=99999, allowed_amount_cents=99999,
            lines=[claim_line("A", 99999, 1.0, "NONE")])
        data = validate_success(api.adjudicate_claim(claim["id"], _plan()))
        assert data["deductible_applied_cents"] == 99999
        assert data["member_responsibility_cents"] == 99999

    def test_deductible_chronological_order_service_date_not_creation(
            self, api, platform_admin_headers):
        """PRD §3.7: "claims of a member apply against the deductible in
        `service_date` ascending order, ties broken by the claim's
        `created_at` ascending (never by id)."

        Design: Corner/calculations/deductible_chronological_order_service_date_not_creation
        """
        set_clock()
        _, member = setup_employer_with_member(
            member_overrides={"deductible_limit_cents": 100000})
        provider = setup_provider(name="Chrono Clinic")
        c_aug = setup_claim(member, provider, service_date="2026-08-01",
                            billed_amount_cents=80000, allowed_amount_cents=80000,
                            lines=[claim_line("A", 80000, 1.0, "NONE")])
        c_jul = setup_claim(member, provider, service_date="2026-07-01",
                            billed_amount_cents=50000, allowed_amount_cents=50000,
                            lines=[claim_line("B", 50000, 1.0, "NONE")])

        dj = validate_success(api.adjudicate_claim(c_jul["id"], _plan()))
        assert dj["deductible_applied_cents"] == 50000

        da = validate_success(api.adjudicate_claim(c_aug["id"], _plan()))
        assert da["deductible_applied_cents"] == 50000

        m = validate_success(api.get_member(
            member["id"], platform_admin_headers))
        assert m["deductible_used_cents"] == 100000


class TestClaimAdjudicateIdempotency:
    def test_claim_adjudicate_twice_rejected(self, api,
                                             platform_admin_headers):
        """PRD §3.7: "Adjudicating a claim not in `RECEIVED` is rejected with
        `ERR_CLAIM_ALREADY_ADJUDICATED` (409)."

        Design: Corner/state_machines/claim_adjudicate_twice_rejected
        """
        set_clock()
        _, member = setup_employer_with_member(
            member_overrides={"deductible_limit_cents": 100000})
        provider = setup_provider(name="Animus Health")
        claim = setup_claim(member, provider,
                            billed_amount_cents=60000, allowed_amount_cents=60000,
                            lines=[claim_line("A", 60000, 1.0, "NONE")])

        validate_success(api.adjudicate_claim(claim["id"], _plan()))
        second = api.adjudicate_claim(claim["id"], _plan())
        validate_error(second, ApiErrorId.ERR_CLAIM_ALREADY_ADJUDICATED,
                       expected_status=409)

        m = validate_success(api.get_member(
            member["id"], platform_admin_headers))
        assert m["deductible_used_cents"] == 60000


class TestVoidCompensation:
    def test_adjudicate_then_void_restores_member_accumulators(
            self, api, platform_admin_headers):
        """PRD §3.7: "Voiding reverses adjudication exactly: the same amounts
        are subtracted from the member's two accumulators, the member's
        `version` bumps again, and the claim moves to terminal `VOID`."

        Design: Difficulty/compensating_invariant/adjudicate_then_void_restores_member_accumulators
        """
        set_clock()
        _, member = setup_employer_with_member(
            member_overrides={"deductible_limit_cents": 100000})
        provider = setup_provider(name="Pine Clinic")
        setup_adjudicated_claim(
            member, provider, service_date="2026-07-01",
            billed_amount_cents=60000, allowed_amount_cents=60000,
            lines=[claim_line("A", 60000, 1.0, "NONE")])
        c2 = setup_claim(member, provider, service_date="2026-08-01",
                         billed_amount_cents=50000, allowed_amount_cents=50000,
                         lines=[claim_line("B", 50000, 1.0, "NONE")])

        validate_success(api.adjudicate_claim(c2["id"], _plan()))
        mid = validate_success(api.get_member(
            member["id"], platform_admin_headers))
        # deductible: 60000 + min(40000, 50000) = 100000
        # oop: 60000 + (40000 + 0.2*10000) = 102000
        assert mid["deductible_used_cents"] == 100000
        assert mid["oop_used_cents"] == 102000

        validate_success(api.void_claim(c2["id"], _plan()))
        after = validate_success(api.get_member(
            member["id"], platform_admin_headers))
        assert after["deductible_used_cents"] == 60000
        assert after["oop_used_cents"] == 60000

        c2_after = validate_success(api.get_claim(c2["id"], _plan()))
        assert c2_after["status"] == "VOID"

    def test_void_moves_claim_to_terminal_void(self, api,
                                               platform_admin_headers):
        """PRD §3.7: "Voiding reverses adjudication exactly: the same amounts
        are subtracted from the member's two accumulators, the member's
        `version` bumps again, and the claim moves to terminal `VOID`."

        Design: Difficulty/compensating_invariant/adjudicate_then_void_restores_member_accumulators
        """
        set_clock()
        _, member = setup_employer_with_member(
            member_overrides={"deductible_limit_cents": 100000})
        provider = setup_provider(name="Pine Clinic")
        claim = setup_adjudicated_claim(
            member, provider, service_date="2026-08-01",
            billed_amount_cents=50000, allowed_amount_cents=50000,
            lines=[claim_line("B", 50000, 1.0, "NONE")])

        voided = validate_success(api.void_claim(claim["id"], _plan()))
        assert voided["status"] == "VOID"

        m = validate_success(api.get_member(
            member["id"], platform_admin_headers))
        assert m["deductible_used_cents"] == 0
        assert m["oop_used_cents"] == 0

    def test_claim_void_cascades_void_to_open_billing_case_only(
            self, api, platform_admin_headers):
        """PRD §3.7: "Voiding also cascades to billing: any linked billing case
        in `OPENED`, `ERROR_IDENTIFIED`, `NEGOTIATING`, or
        `SETTLEMENT_PROPOSED` moves to `VOIDED` with its savings fields nulled,
        while cases already `RESOLVED_ACCEPTED`, `RESOLVED_NO_CHANGE`, or
        `CLOSED` are left unchanged."

        Design: Corner/state_machines/claim_void_cascades_void_to_open_billing_case_only
        """
        set_clock()
        _, member = setup_employer_with_member()
        grant_consent(member, "BILLING_ADVOCACY")
        provider = setup_provider(name="Diamond City Med")
        claim, bc = setup_billing_case_error_identified(
            member, provider,
            claim_overrides={
                "billed_amount_cents": 100000, "allowed_amount_cents": 90000,
                "lines": [claim_line("A", 100000, 0.7, "UPCODING")]})
        validate_success(api.propose_settlement(
            bc["id"], {"counter_offer_cents": 80000}, _advocate()))
        rejected = validate_success(api.reject_settlement(
            bc["id"], make_member_headers(member["id"])))
        assert rejected["status"] == "NEGOTIATING"

        validate_success(api.void_claim(claim["id"], _plan()))

        bc_after = validate_success(api.get_billing_case(
            bc["id"], _advocate()))
        assert bc_after["status"] == "VOIDED"
        assert bc_after["provisional_savings_cents"] is None
        assert bc_after["final_savings_cents"] is None

        resp = api.propose_settlement(
            bc["id"], {"counter_offer_cents": 70000}, _advocate())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE,
                       expected_status=409)


class TestBillingSavingsVariants:
    def test_billing_savings_provisional_vs_final_on_same_claim(self, api):
        """PRD §3.8: "Identifying errors moves the case to `ERROR_IDENTIFIED`
        and computes the provisional savings view: `provisional_savings_cents`
        is the claim's `billed_amount_cents` minus its `repriced_total_cents` —
        the system-priced fair-value view of what the member should save."
        PRD §3.8: "Accepting moves the case to `RESOLVED_ACCEPTED`, copies the
        accepted `counter_offer_cents` into `settled_amount_cents`, and
        computes the final, negotiated-outcome savings view:
        `final_savings_cents` is the claim's `billed_amount_cents` minus
        `settled_amount_cents`."

        Design: Difficulty/dual_variant_calc/billing_savings_provisional_vs_final_on_same_claim
        """
        set_clock()
        _, member = setup_employer_with_member()
        grant_consent(member, "BILLING_ADVOCACY")
        provider = setup_provider(name="City General",
                                  specialty="ORTHOPEDICS")
        claim, bc = setup_billing_case_error_identified(
            member, provider,
            claim_overrides={
                "billed_amount_cents": 200000, "allowed_amount_cents": 180000,
                "lines": [
                    claim_line("L1", 100000, 0.8, "UPCODING"),
                    claim_line("L2", 50000, 0.702, "UPCODING"),
                    claim_line("L3", 50000, 1.0, "NONE"),
                ]})

        claim_after = validate_success(api.get_claim(claim["id"], _plan()))
        assert claim_after["repriced_total_cents"] == 165100

        assert bc["provisional_savings_cents"] == 34900

        validate_success(api.propose_settlement(
            bc["id"], {"counter_offer_cents": 140000}, _advocate()))
        accepted = validate_success(api.accept_settlement(
            bc["id"], make_member_headers(member["id"])))
        assert accepted["final_savings_cents"] == 60000
        assert accepted["provisional_savings_cents"] == 34900
        assert accepted["final_savings_cents"] != accepted["provisional_savings_cents"]

    def test_provisional_survives_through_negotiation_states(self, api):
        """PRD §3.8: "Identifying errors moves the case to `ERROR_IDENTIFIED`
        and computes the provisional savings view: `provisional_savings_cents`
        is the claim's `billed_amount_cents` minus its `repriced_total_cents` —
        the system-priced fair-value view of what the member should save."
        PRD §3.8: "The provisional and final views routinely differ for
        identical claim data whenever the negotiated settlement differs from
        the system repricing."

        Design: Difficulty/dual_variant_calc/billing_savings_provisional_vs_final_on_same_claim
        """
        set_clock()
        _, member = setup_employer_with_member()
        grant_consent(member, "BILLING_ADVOCACY")
        provider = setup_provider(name="City General",
                                  specialty="ORTHOPEDICS")
        _, bc = setup_billing_case_error_identified(
            member, provider,
            claim_overrides={
                "billed_amount_cents": 200000, "allowed_amount_cents": 180000,
                "lines": [
                    claim_line("L1", 100000, 0.8, "UPCODING"),
                    claim_line("L2", 50000, 0.702, "UPCODING"),
                    claim_line("L3", 50000, 1.0, "NONE"),
                ]})
        assert bc["provisional_savings_cents"] == 34900

        proposed = validate_success(api.propose_settlement(
            bc["id"], {"counter_offer_cents": 140000}, _advocate()))
        assert proposed["provisional_savings_cents"] == 34900

        accepted = validate_success(api.accept_settlement(
            bc["id"], make_member_headers(member["id"])))
        assert accepted["provisional_savings_cents"] == 34900
        assert accepted["final_savings_cents"] == 60000

    def test_billing_case_negotiation_rounds_cycle_with_rejection(self, api):
        """PRD §3.8: "Each proposal increments `proposal_count` and moves the
        case to `SETTLEMENT_PROPOSED`, whether from `ERROR_IDENTIFIED` or,
        cyclically, from `NEGOTIATING`. The member then decides."
        PRD §3.8: "Rejecting moves the case back to `NEGOTIATING`, retaining
        the refused `counter_offer_cents` as the last rejected offer."

        Design: Difficulty/non_linear_state_machine/billing_case_negotiation_rounds_cycle_with_rejection
        """
        set_clock()
        _, member = setup_employer_with_member()
        grant_consent(member, "BILLING_ADVOCACY")
        provider = setup_provider(name="Northside Clinic")
        _, bc = setup_billing_case_error_identified(
            member, provider,
            claim_overrides={
                "billed_amount_cents": 200000, "allowed_amount_cents": 180000,
                "lines": [
                    claim_line("L1", 100000, 0.8, "UPCODING"),
                    claim_line("L2", 50000, 0.702, "UPCODING"),
                    claim_line("L3", 50000, 1.0, "NONE"),
                ]})
        member_h = make_member_headers(member["id"])

        for offer in (160000, 150000):
            validate_success(api.propose_settlement(
                bc["id"], {"counter_offer_cents": offer}, _advocate()))
            validate_success(api.reject_settlement(bc["id"], member_h))

        validate_success(api.propose_settlement(
            bc["id"], {"counter_offer_cents": 145000}, _advocate()))
        accepted = validate_success(api.accept_settlement(bc["id"], member_h))
        assert accepted["proposal_count"] == 3
        assert accepted["status"] == "RESOLVED_ACCEPTED"
        assert accepted["settled_amount_cents"] == 145000
        assert accepted["final_savings_cents"] == 55000

    def test_rejection_returns_case_to_negotiating(self, api):
        """PRD §3.8: "Rejecting moves the case back to `NEGOTIATING`, retaining
        the refused `counter_offer_cents` as the last rejected offer."

        Design: Difficulty/non_linear_state_machine/billing_case_negotiation_rounds_cycle_with_rejection
        """
        set_clock()
        _, member = setup_employer_with_member()
        grant_consent(member, "BILLING_ADVOCACY")
        provider = setup_provider(name="Northside Clinic")
        _, bc = setup_billing_case_error_identified(
            member, provider,
            claim_overrides={
                "billed_amount_cents": 200000, "allowed_amount_cents": 180000,
                "lines": [claim_line("A", 200000, 0.7, "UPCODING")]})

        validate_success(api.propose_settlement(
            bc["id"], {"counter_offer_cents": 160000}, _advocate()))
        rejected = validate_success(api.reject_settlement(
            bc["id"], make_member_headers(member["id"])))
        assert rejected["status"] == "NEGOTIATING"
        assert rejected["counter_offer_cents"] == 160000
        assert rejected["proposal_count"] == 1


class TestBillingGatesAndPriority:
    def test_propose_on_closed_case_state_beats_fiscal_settlement_cap(
            self, api):
        """PRD §2.6: "Sixth, state-machine legality: the target entity must be
        in a valid from-state (else `ERR_INVALID_STATE` or the more specific
        state error the workflow declares). Only after all of these do business
        rules run — consent gates, uniqueness constraints, capacity limits,
        fiscal guards, temporal windows — each at the priority stated in §3
        where the rule lives."

        Design: Difficulty/priority_pair_validation_conflict/propose_on_closed_case_state_beats_fiscal_settlement_cap
        """
        set_clock()
        _, member = setup_employer_with_member()
        grant_consent(member, "BILLING_ADVOCACY")
        provider = setup_provider(name="Lakeside Hospital")
        _, bc = setup_billing_case_error_identified(
            member, provider,
            claim_overrides={
                "billed_amount_cents": 200000, "allowed_amount_cents": 180000,
                "lines": [claim_line("L1", 200000, 0.5, "DUPLICATE")]})
        validate_success(api.propose_settlement(
            bc["id"], {"counter_offer_cents": 140000}, _advocate()))
        validate_success(api.accept_settlement(
            bc["id"], make_member_headers(member["id"])))
        closed = validate_success(api.close_billing_case(bc["id"], _advocate()))
        assert closed["status"] == "CLOSED"

        resp = api.propose_settlement(
            bc["id"], {"counter_offer_cents": 250000}, _advocate())
        err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE,
                             expected_status=409)
        assert err["error_id"] != "ERR_SETTLEMENT_EXCEEDS_BILLED"

        after = validate_success(api.get_billing_case(bc["id"], _advocate()))
        assert after["proposal_count"] == 1

    def test_fiscal_guard_fires_on_open_case_when_state_legal(self, api):
        """PRD §3.8: "The advocate proposes a settlement by naming a
        `counter_offer_cents`, which must be strictly below the claim's
        `billed_amount_cents` — a settlement at or above billed saves nothing
        and is rejected with `ERR_SETTLEMENT_EXCEEDS_BILLED` (422)."

        Design: Difficulty/priority_pair_validation_conflict/propose_on_closed_case_state_beats_fiscal_settlement_cap
        """
        set_clock()
        _, member = setup_employer_with_member()
        grant_consent(member, "BILLING_ADVOCACY")
        provider = setup_provider(name="Lakeside Hospital")
        _, bc = setup_billing_case_error_identified(
            member, provider,
            claim_overrides={
                "billed_amount_cents": 200000, "allowed_amount_cents": 180000,
                "lines": [claim_line("L1", 200000, 0.5, "DUPLICATE")]})

        resp = api.propose_settlement(
            bc["id"], {"counter_offer_cents": 250000}, _advocate())
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_EXCEEDS_BILLED,
                       expected_status=422)

    def test_billing_identify_errors_requires_adjudicated_claim(self, api):
        """PRD §3.8: "Error identification requires the linked claim to be
        `ADJUDICATED` (else `ERR_CLAIM_NOT_ADJUDICATED`, 409)".

        Design: Difficulty/cross_entity_state_dependency/billing_identify_errors_requires_adjudicated_claim
        """
        set_clock()
        _, member = setup_employer_with_member()
        grant_consent(member, "BILLING_ADVOCACY")
        provider = setup_provider(name="East Clinic",
                                  network_status="OUT_OF_NETWORK")
        claim = setup_claim(
            member, provider,
            billed_amount_cents=90000, allowed_amount_cents=80000,
            lines=[claim_line("A", 90000, 0.5, "UPCODING")])
        bc = validate_success(api.create_billing_case(
            member["id"], create_billing_case_payload(claim_id=claim["id"]),
            _advocate()), expected_status=201)

        resp = api.identify_errors(bc["id"], _advocate())
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_ADJUDICATED,
                       expected_status=409)
        after = validate_success(api.get_billing_case(bc["id"], _advocate()))
        assert after["status"] == "OPENED"
        assert after["provisional_savings_cents"] is None

    def test_identify_errors_succeeds_once_claim_is_adjudicated(self, api):
        """PRD §3.8: "Error identification requires the linked claim to be
        `ADJUDICATED` (else `ERR_CLAIM_NOT_ADJUDICATED`, 409) and to carry at
        least one error-flagged line (else `ERR_NO_LINE_ERRORS`, 422).
        Identifying errors moves the case to `ERROR_IDENTIFIED`".

        Design: Difficulty/cross_entity_state_dependency/billing_identify_errors_requires_adjudicated_claim
        """
        set_clock()
        _, member = setup_employer_with_member()
        grant_consent(member, "BILLING_ADVOCACY")
        provider = setup_provider(name="East Clinic",
                                  network_status="OUT_OF_NETWORK")
        claim = setup_claim(
            member, provider,
            billed_amount_cents=90000, allowed_amount_cents=80000,
            lines=[claim_line("A", 90000, 0.5, "UPCODING")])
        bc = validate_success(api.create_billing_case(
            member["id"], create_billing_case_payload(claim_id=claim["id"]),
            _advocate()), expected_status=201)

        validate_success(api.adjudicate_claim(claim["id"], _plan()))
        identified = validate_success(api.identify_errors(
            bc["id"], _advocate()))
        assert identified["status"] == "ERROR_IDENTIFIED"
        assert identified["provisional_savings_cents"] is not None

    def test_settlement_at_exactly_billed_rejected(self, api):
        """PRD §3.8: "The advocate proposes a settlement by naming a
        `counter_offer_cents`, which must be strictly below the claim's
        `billed_amount_cents` — a settlement at or above billed saves nothing
        and is rejected with `ERR_SETTLEMENT_EXCEEDS_BILLED` (422)."

        Design: Corner/validations/settlement_at_exactly_billed_rejected
        """
        set_clock()
        _, member = setup_employer_with_member()
        grant_consent(member, "BILLING_ADVOCACY")
        provider = setup_provider(name="Settle Clinic")
        _, bc = setup_billing_case_error_identified(
            member, provider,
            claim_overrides={
                "billed_amount_cents": 100000, "allowed_amount_cents": 90000,
                "lines": [claim_line("A", 100000, 0.7, "UPCODING")]})

        at_billed = api.propose_settlement(
            bc["id"], {"counter_offer_cents": 100000}, _advocate())
        validate_error(at_billed, ApiErrorId.ERR_SETTLEMENT_EXCEEDS_BILLED,
                       expected_status=422)
        after_bad = validate_success(api.get_billing_case(bc["id"], _advocate()))
        assert after_bad["proposal_count"] == 0

        below = api.propose_settlement(
            bc["id"], {"counter_offer_cents": 99999}, _advocate())
        data = validate_success(below)
        assert data["status"] == "SETTLEMENT_PROPOSED"
        assert data["proposal_count"] == 1

    def test_identify_errors_without_flagged_lines_rejected(self, api):
        """PRD §3.8: "and to carry at least one error-flagged line (else
        `ERR_NO_LINE_ERRORS`, 422)."

        Design: Corner/validations/identify_errors_without_flagged_lines_rejected
        """
        set_clock()
        _, member = setup_employer_with_member()
        grant_consent(member, "BILLING_ADVOCACY")
        provider = setup_provider(name="Clean Clinic")
        claim = setup_adjudicated_claim(
            member, provider,
            billed_amount_cents=50000, allowed_amount_cents=45000,
            lines=[claim_line("A", 50000, 1.0, "NONE")])
        bc = validate_success(api.create_billing_case(
            member["id"], create_billing_case_payload(claim_id=claim["id"]),
            _advocate()), expected_status=201)

        resp = api.identify_errors(bc["id"], _advocate())
        validate_error(resp, ApiErrorId.ERR_NO_LINE_ERRORS,
                       expected_status=422)
        after = validate_success(api.get_billing_case(bc["id"], _advocate()))
        assert after["status"] == "OPENED"
        assert after["provisional_savings_cents"] is None

    def test_negotiation_round_cap_at_three(self, api):
        """PRD §3.8: "A case may carry at most three proposals; a fourth is
        rejected with `ERR_NEGOTIATION_ROUND_EXCEEDED` (422)."

        Design: Corner/validations/negotiation_round_cap_at_three
        """
        set_clock()
        _, member = setup_employer_with_member()
        grant_consent(member, "BILLING_ADVOCACY")
        provider = setup_provider(name="Cap Clinic")
        _, bc = setup_billing_case_error_identified(
            member, provider,
            claim_overrides={
                "billed_amount_cents": 200000, "allowed_amount_cents": 180000,
                "lines": [claim_line("A", 200000, 0.7, "UPCODING")]})
        member_h = make_member_headers(member["id"])

        for offer in (150000, 145000, 140000):
            validate_success(api.propose_settlement(
                bc["id"], {"counter_offer_cents": offer}, _advocate()))
            validate_success(api.reject_settlement(bc["id"], member_h))

        fourth = api.propose_settlement(
            bc["id"], {"counter_offer_cents": 135000}, _advocate())
        validate_error(fourth, ApiErrorId.ERR_NEGOTIATION_ROUND_EXCEEDED,
                       expected_status=422)
        after = validate_success(api.get_billing_case(bc["id"], _advocate()))
        assert after["proposal_count"] == 3
        assert after["status"] == "NEGOTIATING"
