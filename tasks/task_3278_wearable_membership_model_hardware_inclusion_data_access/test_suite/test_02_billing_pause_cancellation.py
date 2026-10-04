"""Billing, pause/resume, and cancellation workflow tests."""
from test_helpers import (
    ApiErrorId,
    create_member,
    create_member_payload,
    create_member_with_term,
    create_pause_payload,
    create_term_payload,
    get_success_data,
    make_member_headers,
    make_support_headers,
    pause_term,
    record_payment,
    resume_term,
    validate_paginated,
    set_clock,
    validate_error,
    validate_success,
)


class TestSuspensionCascade:
    def test_payment_failure_cascade_suspends_member(self, api, anonymous_headers):
        """PRD: "When a payment fails on an ACTIVE term, two hops fire in sequence.
        Hop one moves the term from ACTIVE to PAST_DUE. Hop two suspends the
        member: member_status becomes SUSPENDED whenever the member owns at least
        one term in PAST_DUE."

        Design: Difficulty/transitive_cascade/payment_failure_cascade_term_member_merch_block
        """
        member = create_member()
        term = validate_success(
            api.create_term(
                member["id"], create_term_payload(), make_member_headers(member["id"])
            ),
            expected_status=201,
        )
        record_payment(term["id"], "FAILED")
        # read the term back via the member's term list
        terms, _ = validate_paginated(
            api.list_member_terms(member["id"], make_member_headers(member["id"]))
        )
        assert terms[0]["term_status"] == "PAST_DUE"
        member_after = validate_success(
            api.get_member(member["id"], make_member_headers(member["id"]))
        )
        assert member_after["member_status"] == "SUSPENDED"

    def test_suspended_member_merch_order_blocked(self, api, anonymous_headers):
        """PRD: "While a member is SUSPENDED, five kinds of action are blocked and
        refused with ERR_MEMBER_SUSPENDED: starting a new term, upgrading
        hardware, placing a merch order, enrolling in a research study, and
        granting consent scopes."

        Design: Difficulty/transitive_cascade/payment_failure_cascade_term_member_merch_block
        """
        member, term = create_member_with_term(
            monthly_fee_cents=30000, pause_days_per_term=90
        )
        pause_term(term["id"], member["id"], start_on="2026-09-01", days=90)
        resume_term(term["id"], member["id"])
        record_payment(term["id"], "FAILED")
        resp = api.place_merch_order(
            member["id"],
            {
                "lines": [
                    {
                        "sku": "B1",
                        "category": "BAND_ACCESSORY",
                        "unit_price_cents": 1000,
                        "qty": 1,
                    }
                ]
            },
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED, expected_status=409)


class TestTermCyclicLoops:
    def test_term_pause_pastdue_cyclic_loops(self, api, anonymous_headers):
        """PRD: "If start_on is today, the pause opens immediately: the term moves
        from ACTIVE to PAUSED".
        PRD: "When a payment fails on an ACTIVE term, two hops fire in sequence.
        Hop one moves the term from ACTIVE to PAST_DUE."
        PRD: "When a payment succeeds on a PAST_DUE term, the term returns to
        ACTIVE, months_paid increments by one, and — as a second hop — the owning
        member's member_status returns to ACTIVE, but only if the member owns no
        other term still in PAST_DUE."

        Design: Difficulty/non_linear_state_machine/term_pause_pastdue_cyclic_loops
        """
        member, term = create_member_with_term()
        headers = make_member_headers(member["id"])

        pause_term(term["id"], member["id"], start_on="2026-09-01", days=5)
        terms, _ = validate_paginated(
            api.list_member_terms(member["id"], headers)
        )
        assert terms[0]["term_status"] == "PAUSED"

        resume_term(term["id"], member["id"])
        terms, _ = validate_paginated(
            api.list_member_terms(member["id"], headers)
        )
        assert terms[0]["term_status"] == "ACTIVE"

        record_payment(term["id"], "FAILED")
        terms, _ = validate_paginated(
            api.list_member_terms(member["id"], headers)
        )
        assert terms[0]["term_status"] == "PAST_DUE"
        member_after = validate_success(api.get_member(member["id"], headers))
        assert member_after["member_status"] == "SUSPENDED"

        record_payment(term["id"], "SUCCEEDED")
        terms, _ = validate_paginated(
            api.list_member_terms(member["id"], headers)
        )
        assert terms[0]["term_status"] == "ACTIVE"
        assert terms[0]["months_paid"] == 1
        member_after = validate_success(api.get_member(member["id"], headers))
        assert member_after["member_status"] == "ACTIVE"

    def test_term_pause_resume_then_pastdue_recovery_full_cycle(self, api, anonymous_headers):
        """PRD: "A member may also resume early from an OPEN pause. Resuming moves
        the term from PAUSED back to ACTIVE, closes the window with end_on set to
        today".
        PRD: "Suspension lifts automatically on the first successful payment that
        leaves the member with no PAST_DUE term at all."

        Design: Difficulty/non_linear_state_machine/term_pause_pastdue_cyclic_loops
        """
        member, term = create_member_with_term()
        headers = make_member_headers(member["id"])
        pause_term(term["id"], member["id"], start_on="2026-09-01", days=10)
        resumed = resume_term(term["id"], member["id"])
        assert resumed["term_status"] == "ACTIVE"
        assert resumed["pause_windows"][0]["window_status"] == "CLOSED"
        record_payment(term["id"], "FAILED")
        record_payment(term["id"], "SUCCEEDED")
        member_after = validate_success(api.get_member(member["id"], headers))
        assert member_after["member_status"] == "ACTIVE"


class TestResumeGuards:
    def test_resume_on_active_term_rejected(self, api, anonymous_headers):
        """PRD: "Calling resume on a term that is not PAUSED is rejected with
        ERR_TERM_NOT_PAUSED."

        Design: Corner/state_machines/term_invalid_transition_resume_when_active
        """
        member, term = create_member_with_term()
        resp = api.resume_term(term["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_TERM_NOT_PAUSED, expected_status=409)

    def test_resume_on_active_term_leaves_term_unchanged(self, api, anonymous_headers):
        """PRD: "Calling resume on a term that is not PAUSED is rejected with
        ERR_TERM_NOT_PAUSED."

        Design: Corner/state_machines/term_invalid_transition_resume_when_active
        """
        member, term = create_member_with_term()
        headers = make_member_headers(member["id"])
        api.resume_term(term["id"], headers)
        terms, _ = validate_paginated(
            api.list_member_terms(member["id"], headers)
        )
        assert terms[0]["term_status"] == "ACTIVE"
        assert terms[0]["pause_windows"] == []


class TestEarlyCancelCharge:
    def test_early_cancel_charge_remaining_vs_paid_floor(self, api, anonymous_headers):
        """PRD: "Under REMAINING_MONTHS, the fee is forward-looking: the months
        remaining are commitment_months minus months_paid, and the charge is fifty
        percent of the monthly fee for each remaining month — that is,
        monthly_fee_cents times the months remaining times one-half — rounded
        half-up to whole cents, then raised to at least
        early_cancel_fee_floor_cents. Under PAID_MONTHS_FLOOR, the fee is
        chronological: the charge is twenty-five percent of the monthly fee for
        each month already paid — monthly_fee_cents times months_paid times
        one-quarter — again rounded half-up to whole cents and floored at
        early_cancel_fee_floor_cents."

        Design: Difficulty/dual_variant_calc/early_cancel_charge_remaining_vs_paid_floor
        """
        member_a = create_member()
        term_a = validate_success(
            api.create_term(
                member_a["id"],
                create_term_payload(
                    monthly_fee_cents=3000,
                    commitment_months=12,
                    cancel_fee_policy="REMAINING_MONTHS",
                    early_cancel_fee_floor_cents=5000,
                ),
                make_member_headers(member_a["id"]),
            ),
            expected_status=201,
        )
        for _ in range(3):
            record_payment(term_a["id"], "SUCCEEDED")

        member_b = create_member()
        term_b = validate_success(
            api.create_term(
                member_b["id"],
                create_term_payload(
                    monthly_fee_cents=3000,
                    commitment_months=12,
                    cancel_fee_policy="PAID_MONTHS_FLOOR",
                    early_cancel_fee_floor_cents=5000,
                ),
                make_member_headers(member_b["id"]),
            ),
            expected_status=201,
        )
        for _ in range(3):
            record_payment(term_b["id"], "SUCCEEDED")

        cancelled_a = validate_success(
            api.cancel_term(term_a["id"], make_member_headers(member_a["id"]))
        )
        cancelled_b = validate_success(
            api.cancel_term(term_b["id"], make_member_headers(member_b["id"]))
        )
        assert cancelled_a["cancel_fee_charged_cents"] == 13500
        assert cancelled_b["cancel_fee_charged_cents"] == 5000
        assert cancelled_a["term_status"] == "CANCELLED_EARLY"
        assert cancelled_b["term_status"] == "CANCELLED_EARLY"

    def test_early_cancel_floor_binds_when_computed_fee_below_floor(self, api, anonymous_headers):
        """PRD: "Under PAID_MONTHS_FLOOR, the fee is chronological: the charge is
        twenty-five percent of the monthly fee for each month already paid —
        monthly_fee_cents times months_paid times one-quarter — again rounded
        half-up to whole cents and floored at early_cancel_fee_floor_cents."

        Design: Difficulty/dual_variant_calc/early_cancel_charge_remaining_vs_paid_floor
        """
        member = create_member()
        term = validate_success(
            api.create_term(
                member["id"],
                create_term_payload(
                    monthly_fee_cents=3000,
                    commitment_months=12,
                    cancel_fee_policy="PAID_MONTHS_FLOOR",
                    early_cancel_fee_floor_cents=5000,
                ),
                make_member_headers(member["id"]),
            ),
            expected_status=201,
        )
        # months_paid == 1 -> 3000 * 1 * 0.25 = 750 < floor 5000 -> floor binds
        record_payment(term["id"], "SUCCEEDED")
        cancelled = validate_success(
            api.cancel_term(term["id"], make_member_headers(member["id"]))
        )
        assert cancelled["cancel_fee_charged_cents"] == 5000
        assert cancelled["term_status"] == "CANCELLED_EARLY"


class TestCancelGuards:
    def test_cancel_paused_term_rejected_state_beats_fiscal(self, api, anonymous_headers):
        """PRD: "A member (or Support on their behalf) may cancel a term early, but
        only from ACTIVE or PAST_DUE; cancelling a term that is PAUSED, already
        CANCELLED_EARLY, or COMPLETED is rejected with ERR_TERM_NOT_CANCELLABLE."

        Design: Difficulty/priority_pair_validation_conflict/cancel_paused_term_state_beats_fiscal
        """
        member, term = create_member_with_term()
        pause_term(term["id"], member["id"], start_on="2026-09-01", days=10)
        resp = api.cancel_term(term["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_TERM_NOT_CANCELLABLE, expected_status=409)

    def test_cancel_paused_term_leaves_term_and_fee_unchanged(self, api, anonymous_headers):
        """PRD: "A member (or Support on their behalf) may cancel a term early, but
        only from ACTIVE or PAST_DUE; cancelling a term that is PAUSED, already
        CANCELLED_EARLY, or COMPLETED is rejected with ERR_TERM_NOT_CANCELLABLE."

        Design: Difficulty/priority_pair_validation_conflict/cancel_paused_term_state_beats_fiscal
        """
        member, term = create_member_with_term()
        pause_term(term["id"], member["id"], start_on="2026-09-01", days=10)
        api.cancel_term(term["id"], make_member_headers(member["id"]))
        terms, _ = validate_paginated(
            api.list_member_terms(member["id"], make_member_headers(member["id"]))
        )
        assert terms[0]["term_status"] == "PAUSED"
        assert terms[0]["cancel_fee_charged_cents"] is None


class TestPauseBudgetBoundary:
    def test_pause_budget_equality_allowed_and_strictly_greater_rejected(self, api, anonymous_headers):
        """PRD: "a new pause of days length is rejected with
        ERR_PAUSE_BUDGET_EXCEEDED only when committed days plus the new request is
        strictly greater than pause_days_per_term — hitting the budget exactly is
        allowed."

        Design: Difficulty/boundary_precision_check/pause_budget_equality_boundary
        """
        member, term = create_member_with_term(pause_days_per_term=30)
        pause_term(term["id"], member["id"], start_on="2026-09-10", days=20)
        # 20 + 10 == 30 -> allowed (adjacent to first window: [09-30, 10-10))
        pause_term(term["id"], member["id"], start_on="2026-09-30", days=10)
        # 30 + 1 == 31 -> rejected
        resp = api.pause_term(
            term["id"],
            create_pause_payload(start_on="2026-10-10", days=1),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAUSE_BUDGET_EXCEEDED, expected_status=422)

    def test_pause_budget_equality_records_two_windows(self, api, anonymous_headers):
        """PRD: "a new pause of days length is rejected with
        ERR_PAUSE_BUDGET_EXCEEDED only when committed days plus the new request is
        strictly greater than pause_days_per_term — hitting the budget exactly is
        allowed."

        Design: Difficulty/boundary_precision_check/pause_budget_equality_boundary
        """
        member, term = create_member_with_term(pause_days_per_term=30)
        pause_term(term["id"], member["id"], start_on="2026-09-10", days=20)
        pause_term(term["id"], member["id"], start_on="2026-09-30", days=10)
        terms, _ = validate_paginated(
            api.list_member_terms(member["id"], make_member_headers(member["id"]))
        )
        assert len(terms[0]["pause_windows"]) == 2


class TestPauseWindowOverlap:
    def test_pause_windows_half_open_adjacency_allowed(self, api, anonymous_headers):
        """PRD: "A new half-open window may not overlap any existing SCHEDULED or
        OPEN window on the same term; adjacency — one window ending exactly where
        another begins — is allowed. A violation is rejected with
        ERR_PAUSE_WINDOW_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/pause_windows_half_open_adjacency_allowed
        """
        member, term = create_member_with_term(pause_days_per_term=60)
        pause_term(term["id"], member["id"], start_on="2026-09-10", days=10)
        # Adjacent: [2026-09-20, 2026-09-25) starts where first ends
        pause_term(term["id"], member["id"], start_on="2026-09-20", days=5)
        # Overlapping: [2026-09-19, 2026-09-21) overlaps first window
        resp = api.pause_term(
            term["id"],
            create_pause_payload(start_on="2026-09-19", days=2),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAUSE_WINDOW_OVERLAP, expected_status=409)

    def test_pause_windows_overlap_leaves_existing_windows_intact(self, api, anonymous_headers):
        """PRD: "A new half-open window may not overlap any existing SCHEDULED or
        OPEN window on the same term; adjacency — one window ending exactly where
        another begins — is allowed. A violation is rejected with
        ERR_PAUSE_WINDOW_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/pause_windows_half_open_adjacency_allowed
        """
        member, term = create_member_with_term(pause_days_per_term=60)
        pause_term(term["id"], member["id"], start_on="2026-09-10", days=10)
        pause_term(term["id"], member["id"], start_on="2026-09-20", days=5)
        api.pause_term(
            term["id"],
            create_pause_payload(start_on="2026-09-19", days=2),
            make_member_headers(member["id"]),
        )
        terms, _ = validate_paginated(
            api.list_member_terms(member["id"], make_member_headers(member["id"]))
        )
        assert len(terms[0]["pause_windows"]) == 2


class TestPauseProrationRounding:
    def test_pause_proration_per_window_rounding_order(self, api, anonymous_headers):
        """PRD: "the credit is the term's monthly_fee_cents multiplied by those
        unused days and divided by the thirty days of a billing cycle, rounded
        half-up to whole cents. The credit is computed and rounded per resumed
        window before being added to wallet_credit_cents."

        Design: Difficulty/combinatorial_formula/pause_proration_per_window_rounding_order
        """
        member, term = create_member_with_term(
            monthly_fee_cents=1000, commitment_months=6,
            upgrade_eligibility_months=3, pause_days_per_term=10,
            early_cancel_fee_floor_cents=1000,
        )
        pause_term(term["id"], member["id"], start_on="2026-09-01", days=2)
        set_clock("2026-09-02T00:00:00Z")
        resume_term(term["id"], member["id"])  # unused 1 day -> round(1000/30)=33
        pause_term(term["id"], member["id"], start_on="2026-09-02", days=2)
        set_clock("2026-09-03T00:00:00Z")
        resume_term(term["id"], member["id"])  # another 33
        member_after = validate_success(
            api.get_member(member["id"], make_member_headers(member["id"]))
        )
        assert member_after["wallet_credit_cents"] == 66

    def test_pause_proration_updates_pause_days_used(self, api, anonymous_headers):
        """PRD: "for each OPEN window it counts today minus its start, and for each
        CLOSED window it counts end minus start. When a window closes,
        pause_days_used accumulates the window's actual half-open day count."

        Design: Difficulty/combinatorial_formula/pause_proration_per_window_rounding_order
        """
        member, term = create_member_with_term(
            monthly_fee_cents=1000, commitment_months=6,
            upgrade_eligibility_months=3, pause_days_per_term=10,
            early_cancel_fee_floor_cents=1000,
        )
        pause_term(term["id"], member["id"], start_on="2026-09-01", days=2)
        set_clock("2026-09-02T00:00:00Z")
        resume_term(term["id"], member["id"])
        pause_term(term["id"], member["id"], start_on="2026-09-02", days=2)
        set_clock("2026-09-03T00:00:00Z")
        resume_term(term["id"], member["id"])
        terms, _ = validate_paginated(
            api.list_member_terms(member["id"], make_member_headers(member["id"]))
        )
        assert terms[0]["pause_days_used"] == 2


class TestTermCompletion:
    def test_term_completion_via_clock(self, api, anonymous_headers):
        """PRD: "A term that runs its course completes instead: when the logical
        clock reaches a day on or after commitment_end_on and months_paid is at
        least commitment_months, the system moves the term from ACTIVE to
        COMPLETED."

        Design: Corner/state_machines/term_completion_via_clock
        """
        member, term = create_member_with_term(commitment_months=1)
        record_payment(term["id"], "SUCCEEDED")
        set_clock("2026-10-01T00:00:00Z")
        terms, _ = validate_paginated(
            api.list_member_terms(member["id"], make_member_headers(member["id"]))
        )
        assert terms[0]["term_status"] == "COMPLETED"
