"""One contested resource under each of the service's two interval shapes: the half-open
exclusivity slot with a single occupant, and the closed fiscal period whose endpoints touch."""

import pytest
from test_helpers import (
    ANALYST,
    DIRECTOR,
    ApiErrorId,
    draft_registration,
    find_conflict_cases,
    make_partner_headers,
    read_account,
    read_allocation,
    read_partner,
    read_registration,
    seed_gold_distributor_with_two_orders,
    seed_protected_account,
    set_clock,
    start_review,
    submit_registration,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestExclusivitySlotHasOneOccupant:
    def test_the_incumbents_own_renewal_is_exempt_from_the_conflict_that_stops_a_rival(self, api):
        """PRD §3.3: "The account must not be in `DIRECT_LOCKED`, and no **other** registration on
        the same account-and-product-line pair may be in `APPROVED` holding a live exclusivity
        window at the current logical instant — with one carve-out: an incumbent is ignored when it
        is precisely the registration this one supersedes and it belongs to the same partner."

        Design: Difficulty/resource_temporal_overlap/exclusivity_half_open_single_occupant_with_renewal_exemption
        """
        seed = seed_protected_account()
        incumbent_id = seed["incumbent"]["id"]
        challenger_id = seed["challenger"]["id"]
        account_id = seed["account"]["id"]

        rival = draft_registration(
            challenger_id,
            account_id,
            product_line="ANALYTICS_ADDON",
            expected_amount_cents=400_000,
            expected_close_date="2026-09-30T00:00:00.000Z",
        )
        renewal = draft_registration(
            incumbent_id,
            account_id,
            product_line="ANALYTICS_ADDON",
            expected_amount_cents=700_000,
            expected_close_date="2026-10-31T00:00:00.000Z",
            supersedes_registration_id=seed["incumbent_registration"]["id"],
        )

        set_clock("2026-04-15T00:00:00.000Z")
        validate_error(
            api.submit_deal_registration(rival["id"], make_partner_headers(challenger_id)),
            ApiErrorId.ERR_EXCLUSIVITY_CONFLICT.value,
            409,
        )
        assert read_registration(rival["id"])["status"] == "DRAFT"

        submitted = validate_success(
            api.submit_deal_registration(renewal["id"], make_partner_headers(incumbent_id))
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_at"] == "2026-04-15T00:00:00.000Z"

    def test_the_renewal_replaces_the_window_rather_than_extending_it(self, api):
        """PRD §3.4: "Registrations on a different `product_line` of the same account never
        interact with this window, and windows are never merged: a renewal replaces the incumbent's
        window rather than extending it."
        PRD §3.4: "When `supersedes_registration_id` is set, the predecessor moves
        `APPROVED → SUPERSEDED` with `closure_reason` `SUPERSEDED_BY_RENEWAL` and its `version`
        advanced by 1."

        Design: Difficulty/resource_temporal_overlap/exclusivity_half_open_single_occupant_with_renewal_exemption
        """
        seed = seed_protected_account()
        incumbent_id = seed["incumbent"]["id"]
        predecessor_id = seed["incumbent_registration"]["id"]

        renewal = draft_registration(
            incumbent_id,
            seed["account"]["id"],
            product_line="ANALYTICS_ADDON",
            expected_amount_cents=700_000,
            expected_close_date="2026-10-31T00:00:00.000Z",
            supersedes_registration_id=predecessor_id,
        )

        set_clock("2026-04-15T00:00:00.000Z")
        submit_registration(renewal["id"], incumbent_id)
        start_review(renewal["id"])
        approved = validate_success(
            api.decide_deal_registration(renewal["id"], {"decision": "APPROVE"}, DIRECTOR)
        )

        assert approved["exclusivity_start_at"] == "2026-04-15T00:00:00.000Z"
        assert approved["exclusivity_end_at"] == "2026-05-15T00:00:00.000Z"
        assert approved["protection_days"] == 30

        predecessor = read_registration(predecessor_id)
        assert predecessor["status"] == "SUPERSEDED"
        assert predecessor["closure_reason"] == "SUPERSEDED_BY_RENEWAL"
        assert predecessor["exclusivity_start_at"] == "2026-04-01T00:00:00.000Z"
        assert predecessor["exclusivity_end_at"] == "2026-05-01T00:00:00.000Z"
        assert predecessor["registration_margin_uplift_pct"] == pytest.approx(0.06, abs=1e-9)

    def test_the_account_stays_protected_and_the_slot_keeps_exactly_one_occupant(self, api):
        """PRD §3.5: "There is one other way an account already in `CHANNEL_PROTECTED` stays there
        while its protection instant moves: a renewal approval that supersedes the current protector
        overwrites `protected_until` with the successor registration's `exclusivity_end_at`, and the
        account's `version` advances by 1."
        PRD §2.6: "At most one registration may hold a live window on a given
        account-and-product-line pair at any instant; windows are never merged or unioned."

        Design: Difficulty/resource_temporal_overlap/exclusivity_half_open_single_occupant_with_renewal_exemption
        """
        seed = seed_protected_account()
        incumbent_id = seed["incumbent"]["id"]
        challenger_id = seed["challenger"]["id"]
        account_id = seed["account"]["id"]

        rival = draft_registration(
            challenger_id,
            account_id,
            product_line="ANALYTICS_ADDON",
            expected_amount_cents=400_000,
            expected_close_date="2026-09-30T00:00:00.000Z",
        )
        renewal = draft_registration(
            incumbent_id,
            account_id,
            product_line="ANALYTICS_ADDON",
            expected_amount_cents=700_000,
            expected_close_date="2026-10-31T00:00:00.000Z",
            supersedes_registration_id=seed["incumbent_registration"]["id"],
        )

        set_clock("2026-04-15T00:00:00.000Z")
        api.submit_deal_registration(rival["id"], make_partner_headers(challenger_id))
        submit_registration(renewal["id"], incumbent_id)
        start_review(renewal["id"])
        validate_success(
            api.decide_deal_registration(renewal["id"], {"decision": "APPROVE"}, DIRECTOR)
        )

        account = read_account(account_id)
        assert account["coverage_state"] == "CHANNEL_PROTECTED"
        assert account["protected_until"] == "2026-05-15T00:00:00.000Z"
        assert account["protected_partner_id"] == incumbent_id

        rows, _ = validate_paginated(
            api.list_account_deal_registrations(
                account_id, ANALYST, params={"product_line": "ANALYTICS_ADDON"}
            )
        )
        approved_rows = [row for row in rows if row["status"] == "APPROVED"]
        assert len(approved_rows) == 1
        assert approved_rows[0]["id"] == renewal["id"]

        assert find_conflict_cases(account_id=account_id) == []
        assert read_partner(challenger_id)["open_conflict_count"] == 0


class TestFundPeriodCapacityOverTouchingIntervals:
    def test_two_periods_touching_at_one_endpoint_breach_the_annual_cap(self, api):
        """PRD §3.7: "The candidate period's `allocated_cents`, added to the `allocated_cents` of
        every existing period of the same partner whose inclusive interval intersects the
        candidate's, must stay at or below the tier's annual cap: 0 cents for `REGISTERED`, 400000
        for `SILVER`, 900000 for `GOLD`, 2000000 for `PLATINUM`."
        PRD §3.7: "Two periods that merely touch at a single endpoint do intersect."

        Design: Difficulty/resource_temporal_overlap/mdf_period_capacity_over_inclusive_intersecting_periods
        """
        seed = seed_gold_distributor_with_two_orders()
        partner_id = seed["partner"]["id"]

        assert seed["gold_invoice"]["margin_pct"] == pytest.approx(0.2150, abs=1e-9)
        assert seed["gold_invoice"]["invoice_amount_cents"] == 15700000
        first = seed["allocation"]
        assert first["basis_revenue_cents"] == 24350000
        assert first["allocated_cents"] == 587000
        assert first["available_cents"] == 587000
        assert first["status"] == "OPEN"

        validate_error(
            api.create_mdf_allocation(
                {
                    "partner_id": partner_id,
                    "period_start": "2026-06-30T23:59:59.999Z",
                    "period_end": "2026-12-31T23:59:59.999Z",
                },
                ANALYST,
            ),
            ApiErrorId.ERR_MDF_PERIOD_CAPACITY_EXCEEDED.value,
            422,
        )

        unchanged = read_allocation(first["id"])
        assert unchanged["allocated_cents"] == 587000
        assert unchanged["available_cents"] == 587000

    def test_a_period_starting_one_millisecond_later_does_not_intersect_and_is_accepted(self, api):
        """PRD §3.7: "A candidate that would breach the cap is rejected with
        `ERR_MDF_PERIOD_CAPACITY_EXCEEDED` and nothing is created."
        PRD §3.7: "A period that clears the cap is stored with `committed_cents`, `paid_cents` and
        `expired_cents` all 0, `available_cents` equal to `allocated_cents`, `status` `OPEN` and
        `closed_at` null."

        Design: Difficulty/resource_temporal_overlap/mdf_period_capacity_over_inclusive_intersecting_periods
        """
        seed = seed_gold_distributor_with_two_orders()
        partner_id = seed["partner"]["id"]

        api.create_mdf_allocation(
            {
                "partner_id": partner_id,
                "period_start": "2026-06-30T23:59:59.999Z",
                "period_end": "2026-12-31T23:59:59.999Z",
            },
            ANALYST,
        )

        second = validate_success(
            api.create_mdf_allocation(
                {
                    "partner_id": partner_id,
                    "period_start": "2026-07-01T00:00:00.000Z",
                    "period_end": "2026-12-31T23:59:59.999Z",
                },
                ANALYST,
            ),
            201,
        )
        assert second["allocated_cents"] == 587000
        assert second["committed_cents"] == 0
        assert second["paid_cents"] == 0
        assert second["expired_cents"] == 0
        assert second["available_cents"] == 587000
        assert second["status"] == "OPEN"
        assert second["closed_at"] is None

        rows, meta = validate_paginated(
            api.list_mdf_allocations(ANALYST, params={"partner_id": partner_id})
        )
        assert meta["total_count"] == 2
        assert sorted(row["id"] for row in rows) == sorted([seed["allocation"]["id"], second["id"]])
        assert sum(row["allocated_cents"] for row in rows) == 1174000
