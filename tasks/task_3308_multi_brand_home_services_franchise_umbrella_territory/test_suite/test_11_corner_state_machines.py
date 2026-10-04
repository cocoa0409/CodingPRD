"""State-machine corner claims: terminal lockdown, initial state and supersession."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    activate_agreement,
    award_territory,
    conduct_audit,
    create_agreement,
    create_audit,
    create_brand,
    create_franchisee,
    create_referral,
    create_territory,
    get_agreement,
    get_audit,
    get_referral,
    get_territory,
    make_franchisee_operator_headers,
    offer_agreement,
    offer_territory,
    publish_audit,
    set_clock,
    setup_two_brand_pair,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["franchise_admin_headers"]


class TestTerritoryReclaimedIsTerminal:
    def test_offering_a_reclaimed_territory_is_refused_as_an_invalid_state(self, api):
        """PRD §3.3: "it clears the holder by setting the territory's
        `franchisee_id` to null, resets its `allocated_households` to zero, and
        moves it to `RECLAIMED`, from which no further transition is declared
        and any further attempt is refused with `ERR_INVALID_STATE`".

        Design: Corner/state_machines/territory_offer_from_reclaimed_returns_invalid_state
        """
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
        api.suspend_agreement(
            agreement["id"], ADMIN, reason="Standing down ahead of a reallocation",
        )
        api.reclaim_territory(territory["id"], ADMIN)

        resp = api.offer_territory(territory["id"], franchisee["id"], ADMIN)
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE.value,
                   ApiErrorId.ERR_ALREADY_TERMINAL.value],
        )

        refused = get_territory(territory["id"])
        assert refused["status"] == "RECLAIMED"
        assert refused["franchisee_id"] is None


class TestReferralInitialState:
    def test_a_new_referral_starts_pending_with_a_seven_day_expiry(self, api):
        """PRD §3.5: "A referral is born in `PENDING` status with a
        `referral_fee_cents` of zero, and its `expires_clock_iso` is set to its
        creation instant advanced by 168 logical hours, so a referral expires
        exactly seven logical days after it is created."

        Design: Corner/state_machines/referral_first_creation_starts_pending_with_expiry_window
        """
        ctx = setup_two_brand_pair()
        resp = api.create_referral(
            {
                "referral_code": "R1",
                "originating_agreement_id": ctx["agt_a1"]["id"],
                "receiving_agreement_id": ctx["agt_a2"]["id"],
                "customer_household_ref": "HH-9101",
                "job_description": "Water heater replacement surfaced during an electrical visit",
                "estimated_job_value_cents": 200000,
                "referral_fee_rate": 0.10,
            },
            make_franchisee_operator_headers(ctx["fr_ms"]["id"]),
        )
        created = validate_success(resp, 201)

        assert created["status"] == "PENDING"
        assert created["referral_fee_cents"] == 0
        assert created["accepted_clock_iso"] is None
        assert created["settled_clock_iso"] is None
        assert created["expires_clock_iso"] == "2026-09-08T00:00:00Z", (
            "a referral created at the 2026-09-01T00:00:00Z clock expires 168 "
            f"logical hours later, got {created['expires_clock_iso']}"
        )


class TestDeclinedReferralLockdown:
    def test_a_declined_referral_refuses_every_later_action(self, api):
        """PRD §3.5: "The receiving franchisee may instead decline outright,
        which moves it to `DECLINED`, a terminal state."

        Design: Corner/state_machines/declined_referral_is_locked_against_acceptance
        """
        ctx = setup_two_brand_pair()
        referral = create_referral(
            ctx["agt_a1"]["id"], ctx["agt_a2"]["id"], ctx["fr_ms"]["id"],
            customer_household_ref="HH-9102",
            estimated_job_value_cents=150000,
        )
        receiving = make_franchisee_operator_headers(ctx["fr_il"]["id"])

        resp = api.decline_referral(referral["id"], receiving)
        declined = validate_success(resp, 200)
        assert declined["status"] == "DECLINED"

        resp = api.accept_referral(referral["id"], receiving)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)

        refused = get_referral(referral["id"])
        assert refused["status"] == "DECLINED", (
            f"the terminal state must be left exactly where it was, got "
            f"{refused['status']}"
        )
        assert refused["accepted_clock_iso"] is None
        assert refused["referral_fee_cents"] == 0

        rows, meta = validate_paginated(
            api.list_referrals(ADMIN, {"originating_agreement_id": ctx["agt_a1"]["id"],
                                       "status": "PENDING"})
        )
        assert meta["total_count"] == 0

    def test_declining_a_referral_requires_the_receiving_side(self, api):
        """PRD §3.5: "Accepting is the receiving franchisee's act; an operator
        who is not the receiving agreement's franchisee is refused with
        `ERR_NOT_RECEIVING_FRANCHISEE`" — declining is the same act on the other
        branch.

        Design: Corner/state_machines/declined_referral_is_locked_against_acceptance
        """
        ctx = setup_two_brand_pair()
        referral = create_referral(
            ctx["agt_a1"]["id"], ctx["agt_a2"]["id"], ctx["fr_ms"]["id"],
        )

        resp = api.decline_referral(
            referral["id"], make_franchisee_operator_headers(ctx["fr_ms"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RECEIVING_FRANCHISEE)
        assert get_referral(referral["id"])["status"] == "PENDING"


class TestAuditSupersession:
    def test_publishing_a_later_audit_supersedes_the_earlier_one(self, api):
        """PRD §3.8: "Every earlier audit for the same agreement that was
        `PUBLISHED` is moved to `SUPERSEDED`, so an agreement carries at most one
        current published audit and its superseded history behind it."

        Design: Corner/state_machines/audit_second_publish_supersedes_the_first_on_the_same_agreement
        """
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

        first = create_audit(
            agreement["id"], audit_kind="ANNOUNCED", raw_score=92.0,
            findings_count=2, critical_findings_count=0,
            conducted_iso="2026-09-01T00:00:00Z",
        )
        conduct_audit(first["id"])

        publish_audit(first["id"], agreement["id"])

        second = create_audit(
            agreement["id"], audit_kind="ANNOUNCED", raw_score=88.0,
            findings_count=1, critical_findings_count=0,
            conducted_iso="2026-10-01T00:00:00Z",
        )
        conduct_audit(second["id"])
        published = publish_audit(second["id"], agreement["id"])

        assert published["audit_status"] == "PUBLISHED"
        assert published["outcome"] == "PASS"
        assert get_audit(first["id"])["audit_status"] == "SUPERSEDED", (
            "the earlier published audit must be superseded exactly once"
        )

        rows, meta = validate_paginated(
            api.list_audits(ADMIN, {"agreement_id": agreement["id"],
                                    "audit_status": "PUBLISHED"})
        )
        assert meta["total_count"] == 1, (
            f"an agreement carries at most one current published audit, got "
            f"{meta['total_count']}"
        )

    def test_the_agreement_deadline_follows_the_later_audit(self, api):
        """PRD §2.7: "thereafter is the `conducted_iso` of the latest audit that
        is `PUBLISHED` or `SUPERSEDED`, advanced by the brand's
        `audit_cycle_months`."

        Design: Corner/state_machines/audit_second_publish_supersedes_the_first_on_the_same_agreement
        """
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

        first = create_audit(
            agreement["id"], audit_kind="ANNOUNCED", raw_score=92.0,
            findings_count=2, conducted_iso="2026-09-01T00:00:00Z",
        )
        conduct_audit(first["id"])

        publish_audit(first["id"], agreement["id"])
        second = create_audit(
            agreement["id"], audit_kind="ANNOUNCED", raw_score=88.0,
            findings_count=1, conducted_iso="2026-10-01T00:00:00Z",
        )
        conduct_audit(second["id"])
        publish_audit(second["id"], agreement["id"])

        refreshed = get_agreement(agreement["id"])
        assert refreshed["audit_due_iso"] == "2027-10-01T00:00:00Z", (
            "only the newer audit's conducted_iso plus the brand's 12 "
            f"audit_cycle_months advances the deadline, got {refreshed['audit_due_iso']}"
        )