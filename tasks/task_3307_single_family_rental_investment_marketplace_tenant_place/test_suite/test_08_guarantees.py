"""Guarantee issuance, claim variants, claim windows, and terminal states."""
import pytest

from test_helpers import (
    ApiErrorId,
    CLAIMS_ADJUSTER_HEADERS,
    DEFAULT_CLOCK_ISO,
    PLATFORM_ADMIN_HEADERS,
    attach_lease,
    claim_guarantee,
    create_guarantee_payload,
    create_payment_record_payload,
    get_success_data,
    make_buyer_headers,
    make_claims_adjuster_headers,
    make_seller_headers,
    set_clock,
    setup_closed_sale,
    validate_error,
    validate_success,
)


class TestGuaranteeIssuance:
    def test_guarantee_issued_enters_issued_status(self, api):
        """PRD §3.9: "The guarantee enters in `ISSUED` status and becomes
        `ACTIVE` when the escrow for the listing closes."

        Design: Corner/state_machines/terminal_guarantee_paid_is_locked
        """
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_closed_sale(
            with_lease=True, guarantee={"guarantee_kind": "LEASE_UP", "coverage_months": 6}
        )
        guarantees = get_success_data(
            api.list_guarantees(ctx["listing"]["id"], PLATFORM_ADMIN_HEADERS)
        )
        assert guarantees[0]["status"] == "ACTIVE"


class TestGuaranteeClaimVariants:
    def test_lease_up_claim_sums_unpaid_records_in_window(self, api):
        """PRD §3.9: "For `LEASE_UP`, the claim amount is the lesser of two
        quantities: the sum of `amount_cents` over payment records on the
        listing's leases with `due_date` between the sale timestamp and the
        claim timestamp inclusive that are unpaid (no `paid_date`) or flagged
        `late`; and a cap equal to the resolved lease's `monthly_rent_cents` —
        the assigned lease, else the most recent terminated lease as above —
        multiplied by `coverage_months`."

        Design: Difficulty/dual_variant_calc/guarantee_claim_vacancy_vs_lease_up_variant
        """
        set_clock(DEFAULT_CLOCK_ISO)  # sale timestamp pinned at 2026-09-01
        ctx = setup_closed_sale(
            with_lease=True,
            guarantee={"guarantee_kind": "LEASE_UP", "coverage_months": 6},
            lease_overrides={"monthly_rent_cents": 150_000},
        )
        seller_h = make_seller_headers(ctx["seller"]["id"])
        get_success_data(
            api.create_payment_record(
                ctx["lease"]["id"],
                create_payment_record_payload(
                    due_date="2026-10-01T00:00:00Z", amount_cents=150_000
                ),
                seller_h,
            )
        )
        set_clock("2026-10-10T00:00:00Z")
        claimed = claim_guarantee(ctx["buyer"], ctx["guarantee"])
        assert claimed["status"] == "CLAIMED"
        # one unpaid October record of 150000 < cap 150000*6
        assert claimed["claim_amount_cents"] == 150_000

    def test_vacancy_claim_rejected_while_tenancy_running(self, api):
        """PRD §3.9: "For a `VACANCY` guarantee, no lease on the listing may be
        in `ACTIVE` or `ASSIGNED` status at claim time — a still-running tenancy
        makes the claim invalid."
        PRD §3.9: "A claim whose kind-specific conditions are unmet — including
        the case where no lease history exists at all to price the claim — is
        rejected with `ERR_GUARANTEE_NOT_CLAIMABLE`."

        Design: Difficulty/dual_variant_calc/guarantee_claim_vacancy_vs_lease_up_variant
        """
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_closed_sale(
            with_lease=True,
            guarantee={"guarantee_kind": "VACANCY", "coverage_months": 6},
            lease_overrides={"monthly_rent_cents": 150_000},
        )
        set_clock("2026-10-10T00:00:00Z")
        resp = api.transition_guarantee(
            ctx["guarantee"]["id"], {"action": "CLAIM"}, make_buyer_headers(ctx["buyer"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_GUARANTEE_NOT_CLAIMABLE)
        guarantees = get_success_data(
            api.list_guarantees(ctx["listing"]["id"], PLATFORM_ADMIN_HEADERS)
        )
        assert guarantees[0]["status"] == "ACTIVE"


class TestGuaranteeVacancyNoLeaseHistory:
    def test_vacancy_claim_without_any_lease_rejected(self, api):
        """PRD §3.9: "For `VACANCY`, the monthly coverage is the
        `monthly_rent_cents` of the lease that was assigned at closing; if none
        exists, the listing's most recent `TERMINATED` lease is used instead —
        most recent by `lease_end`, with ties broken by `created_at`
        descending; if no lease exists at all, the claim is invalid as above."

        Design: Corner/calculations/guarantee_vacancy_claim_forward_months
        """
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_closed_sale(
            with_lease=False, guarantee={"guarantee_kind": "VACANCY", "coverage_months": 6}
        )
        set_clock("2026-10-10T00:00:00Z")
        resp = api.transition_guarantee(
            ctx["guarantee"]["id"], {"action": "CLAIM"}, make_buyer_headers(ctx["buyer"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_GUARANTEE_NOT_CLAIMABLE)
        guarantees = get_success_data(
            api.list_guarantees(ctx["listing"]["id"], PLATFORM_ADMIN_HEADERS)
        )
        assert guarantees[0]["status"] == "ACTIVE"


class TestGuaranteeClaimSettlingAndTerminalLock:
    def _setup_paid_guarantee(self, api):
        set_clock(DEFAULT_CLOCK_ISO)  # sale at 2026-09-01
        ctx = setup_closed_sale(
            with_lease=True,
            guarantee={"guarantee_kind": "LEASE_UP", "coverage_months": 6},
            lease_overrides={"monthly_rent_cents": 100_000},
        )
        seller_h = make_seller_headers(ctx["seller"]["id"])
        get_success_data(
            api.create_payment_record(
                ctx["lease"]["id"],
                create_payment_record_payload(
                    due_date="2026-10-01T00:00:00Z", amount_cents=100_000
                ),
                seller_h,
            )
        )
        set_clock("2026-10-10T00:00:00Z")
        claim_guarantee(ctx["buyer"], ctx["guarantee"])
        paid = get_success_data(
            api.transition_guarantee(
                ctx["guarantee"]["id"], {"action": "PAY"}, CLAIMS_ADJUSTER_HEADERS
            )
        )
        return ctx, paid

    def test_paid_guarantee_rejects_further_deny(self, api):
        """PRD §3.9: "A `ClaimsAdjuster` settles a claim by paying it
        (`CLAIMED` → `PAID`) or denying it (`CLAIMED` → `VOID`). A guarantee
        whose claim window passes while still `ACTIVE` moves to `EXPIRED`,
        evaluated when the clock is set. Guarantees can also be voided before
        closing by listing withdrawal or escrow cancellation (§3.4, §3.7).
        `PAID`, `EXPIRED`, and `VOID` are terminal."
        PRD §2.8: "A request whose `action` is not defined from the entity's
        current state fails the state check with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/terminal_guarantee_paid_is_locked
        """
        ctx, paid = self._setup_paid_guarantee(api)
        assert paid["status"] == "PAID"
        resp = api.transition_guarantee(
            ctx["guarantee"]["id"], {"action": "DENY"}, CLAIMS_ADJUSTER_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        guarantees = get_success_data(
            api.list_guarantees(ctx["listing"]["id"], PLATFORM_ADMIN_HEADERS)
        )
        assert guarantees[0]["status"] == "PAID"

    def test_claimed_guarantee_pays_out_with_computed_amount(self, api):
        """PRD §3.9: "A valid claim stamps `claimed_at` with the logical clock
        and computes `claim_amount_cents`."

        Design: Corner/state_machines/terminal_guarantee_paid_is_locked
        """
        ctx, paid = self._setup_paid_guarantee(api)
        assert paid["status"] == "PAID"
        assert paid["claim_amount_cents"] == 100_000


class TestDisputeResolutionGuaranteeCascade:
    def _setup_dispute_with_active_guarantee(self, api):
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_closed_sale(
            with_lease=True,
            guarantee={"guarantee_kind": "LEASE_UP", "coverage_months": 6},
            lease_overrides={"monthly_rent_cents": 150_000},
            listing_kwargs={
                "inspection_overrides": {
                    "disclosed_defects": [
                        {"code": "ROOF-1", "severity": "MEDIUM", "description": "shingles"}
                    ]
                }
            },
        )
        seller_h = make_seller_headers(ctx["seller"]["id"])
        buyer_h = make_buyer_headers(ctx["buyer"]["id"])
        dispute = get_success_data(
            api.create_dispute(
                ctx["listing"]["id"],
                {"opened_by": "BUYER", "condition_code": "ROOF-1", "remedy_cents": 500_000},
                buyer_h,
            )
        )
        get_success_data(
            api.transition_dispute(
                dispute["id"], {"action": "START_EVIDENCE"}, CLAIMS_ADJUSTER_HEADERS
            )
        )
        return ctx, dispute, seller_h, buyer_h

    def test_resolve_buyer_claims_active_guarantee(self, api):
        """PRD §3.9: "Resolving for the buyer carries a cascade: if a guarantee
        in `ACTIVE` covers the listing and the contested `condition_code` maps
        to a disclosed defect, that guarantee moves from `ACTIVE` to `CLAIMED`
        with its `claim_amount_cents` recomputed per §3.9's claim formula."

        Design: Difficulty/transitive_cascade/dispute_resolution_triggers_guarantee_claim
        """
        ctx, dispute, seller_h, buyer_h = self._setup_dispute_with_active_guarantee(api)
        resolved = get_success_data(
            api.transition_dispute(
                dispute["id"], {"action": "RESOLVE_BUYER"}, CLAIMS_ADJUSTER_HEADERS
            )
        )
        assert resolved["status"] == "RESOLVED_BUYER"
        guarantees = get_success_data(
            api.list_guarantees(ctx["listing"]["id"], PLATFORM_ADMIN_HEADERS)
        )
        assert guarantees[0]["status"] == "CLAIMED"

    def test_resolve_buyer_stamps_claimed_at_with_logical_clock(self, api):
        """PRD §3.9: "A valid claim stamps `claimed_at` with the logical clock
        and computes `claim_amount_cents`."

        Design: Difficulty/transitive_cascade/dispute_resolution_triggers_guarantee_claim
        """
        from test_helpers import assert_instants_equal

        ctx, dispute, seller_h, buyer_h = self._setup_dispute_with_active_guarantee(api)
        get_success_data(
            api.transition_dispute(
                dispute["id"], {"action": "RESOLVE_BUYER"}, CLAIMS_ADJUSTER_HEADERS
            )
        )
        guarantees = get_success_data(
            api.list_guarantees(ctx["listing"]["id"], PLATFORM_ADMIN_HEADERS)
        )
        assert guarantees[0]["status"] == "CLAIMED"
        assert_instants_equal(guarantees[0]["claimed_at"], "2026-09-01T00:00:00Z", "claimed_at")
