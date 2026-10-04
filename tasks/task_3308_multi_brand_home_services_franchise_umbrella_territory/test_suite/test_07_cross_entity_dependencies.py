"""Cross-entity state dependencies: renewal gating and program suspension gating."""
from test_helpers import (
    api_client,
    TEST_USERS,
    ApiErrorId,
    activate_agreement,
    award_territory,
    create_agreement,
    create_brand,
    create_franchisee,
    create_national_account,
    create_territory,
    create_work_order,
    dispatch_and_start,
    dispatch_work_order,
    get_agreement,
    get_national_account,
    get_work_order,
    make_franchisee_operator_headers,
    offer_agreement,
    offer_territory,
    set_clock,
    setup_published_failing_audit,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["franchise_admin_headers"]


class TestRenewalBlockedByOpenRemediation:
    def _agreement_in_renewal_pending_with_open_remediation(self):
        _, _, _, agreement, _ = setup_published_failing_audit(
            agreement={"signed_on": "2025-10-01T00:00:00Z", "initial_term_months": 12},
        )
        assert agreement["expires_on"] == "2026-10-01T00:00:00Z", (
            f"a term signed 2025-10-01T00:00:00Z for 12 months expires "
            f"2026-10-01T00:00:00Z, got {agreement['expires_on']}"
        )
        assert agreement["open_remediation_count"] == 1
        operator = make_franchisee_operator_headers(agreement["franchisee_id"])
        api_client.renew_agreement(agreement["id"], operator)
        pending = get_agreement(agreement["id"])
        assert pending["lifecycle_status"] == "RENEWAL_PENDING"
        return pending

    def test_activating_a_renewal_is_refused_while_a_remediation_is_open(self, api):
        """PRD §3.7: "The renewed term is then activated by a `FranchiseAdmin`,
        which requires the agreement's `open_remediation_count` to be zero —
        otherwise `ERR_OPEN_REMEDIATION`".

        Design: Difficulty/cross_entity_state_dependency/renewal_activation_blocked_by_open_remediation_on_audit
        """
        agreement = self._agreement_in_renewal_pending_with_open_remediation()

        resp = api.activate_renewal(agreement["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_OPEN_REMEDIATION)

        refused = get_agreement(agreement["id"])
        assert refused["lifecycle_status"] == "RENEWAL_PENDING"
        assert refused["open_remediation_count"] == 1

    def test_the_pending_renewal_keeps_the_agreement_out_of_the_active_set(self, api):
        """PRD §2.4: "`active_agreement_count` counts the franchisee's agreements
        whose commercial lifecycle is `ACTIVE`, `RENEWAL_PENDING` or
        `TRANSFER_PENDING`" — the listing filtered to `ACTIVE` must therefore
        omit the pending renewal.

        Design: Difficulty/cross_entity_state_dependency/renewal_activation_blocked_by_open_remediation_on_audit
        """
        agreement = self._agreement_in_renewal_pending_with_open_remediation()

        resp = api.list_agreements(
            ADMIN,
            {"franchisee_id": agreement["franchisee_id"], "lifecycle_status": "ACTIVE"},
        )
        rows, meta = validate_paginated(resp)
        assert meta["total_count"] == 0, (
            f"no agreement of this franchisee is ACTIVE, got {meta['total_count']}"
        )


class TestDispatchBlockedBySuspendedProgram:
    def _suspended_program_with_a_fresh_work_order(self):
        set_clock("2026-09-01T00:00:00Z")
        brand = create_brand(
            brand_code="MSP", display_name="Mosaic Plumbing", trade="PLUMBING",
            royalty_rate=0.06, national_ad_fund_rate=0.01,
            min_certification_level="APPRENTICE", audit_cycle_months=12,
            cross_brand_fee_table={},
        )
        franchisee = create_franchisee()
        territory = create_territory(brand["id"], franchisee_id=franchisee["id"])
        agreement = create_agreement(franchisee["id"], brand["id"], territory["id"])
        offer_agreement(agreement["id"])
        offer_territory(territory["id"], franchisee["id"])
        award_territory(territory["id"])
        activate_agreement(agreement["id"])
        account = create_national_account(
            account_name="Single Strike Trust", account_type="NATIONAL_ACCOUNT",
            contracted_brands=[brand["id"]], service_level_hours=8,
            sla_credit_per_breach_cents=7500, breach_tolerance=1,
            annual_commitment_cents=12000000,
        )
        operator = make_franchisee_operator_headers(franchisee["id"])
        old = create_work_order(
            agreement["id"], source="NATIONAL_ACCOUNT", priority="STANDARD",
            service_level_hours=4, parts_cents=0, national_account_id=account["id"],
        )
        second = create_work_order(
            agreement["id"], source="NATIONAL_ACCOUNT", priority="STANDARD",
            service_level_hours=4, parts_cents=0, national_account_id=account["id"],
        )
        # Both orders are dispatched at the 2026-09-01T00:00:00Z clock, so each
        # carries its own 04:00 deadline; the clock is then advanced past both.
        dispatch_and_start(old["id"], franchisee["id"])
        dispatch_and_start(second["id"], franchisee["id"])
        set_clock("2026-09-01T05:00:00Z")
        # PRD 3.4: with tolerance 1 the program absorbs its first breach and is
        # suspended on the second, which blocks every later dispatch.
        api_client.breach_work_order(old["id"], ADMIN)
        api_client.breach_work_order(second["id"], ADMIN)
        fresh = create_work_order(
            agreement["id"], source="NATIONAL_ACCOUNT", priority="STANDARD",
            service_level_hours=4, parts_cents=0, national_account_id=account["id"],
        )
        return franchisee, account, old, fresh

    def test_a_suspended_program_blocks_every_later_dispatch(self, api):
        """PRD §3.4: "work may only be dispatched for a program that is still
        `ACTIVE`; a dispatch naming a suspended or closed program is refused
        with `ERR_ACCOUNT_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_by_suspended_national_account
        """
        franchisee, account, _, fresh = self._suspended_program_with_a_fresh_work_order()
        program = get_national_account(account["id"])
        assert program["status"] == "SUSPENDED"
        assert program["open_breach_count"] == 2

        resp = api.dispatch_work_order(
            fresh["id"], make_franchisee_operator_headers(franchisee["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED)

    def test_the_refused_dispatch_leaves_the_order_created_and_undispatched(self, api):
        """PRD §3.4: "On success the dispatch instant is stamped as
        `dispatched_clock_iso`, the status becomes `DISPATCHED`, and the
        deadline is set."

        Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_by_suspended_national_account
        """
        franchisee, _, _, fresh = self._suspended_program_with_a_fresh_work_order()
        api.dispatch_work_order(
            fresh["id"], make_franchisee_operator_headers(franchisee["id"]),
        )

        refused = get_work_order(fresh["id"])
        assert refused["status"] == "CREATED"
        assert refused["dispatched_clock_iso"] is None