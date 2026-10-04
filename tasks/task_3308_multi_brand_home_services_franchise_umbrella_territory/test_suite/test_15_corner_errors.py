"""Error-corner claims: uniqueness, request shape, ownership and linkage refusals."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_referral,
    activate_agreement,
    award_territory,
    begin_review,
    complete_referral,
    create_agreement,
    create_brand,
    create_franchisee,
    create_lead,
    create_national_account,
    create_referral,
    create_territory,
    create_transfer_application,
    create_work_order,
    franchisee_version,
    get_agreement,
    get_audit,
    get_franchisee,
    get_lead,
    get_referral,
    get_territory,
    get_transfer_application,
    get_work_order,
    make_franchisee_operator_headers,
    offer_agreement,
    offer_territory,
    set_clock,
    setup_completed_referral,
    setup_two_brand_pair,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["franchise_admin_headers"]


def _brand(code="MSP", trade="PLUMBING", level="APPRENTICE"):
    return create_brand(
        brand_code=code, display_name=f"{code} Brand", trade=trade,
        royalty_rate=0.06, national_ad_fund_rate=0.01,
        min_certification_level=level, audit_cycle_months=12,
        cross_brand_fee_table={},
    )


def _pair_of_territories_and_agreements(brand_id, franchisee_id):
    ter_one = create_territory(brand_id, franchisee_id=franchisee_id, territory_code="MS-01")
    ter_two = create_territory(brand_id, franchisee_id=franchisee_id, territory_code="MS-02")
    agt_one = create_agreement(
        franchisee_id, brand_id, ter_one["id"], agreement_number="A-MS-01",
    )
    agt_two = create_agreement(
        franchisee_id, brand_id, ter_two["id"], agreement_number="A-MS-02",
    )
    return ter_one, ter_two, agt_one, agt_two


class TestDuplicateBrandCode:
    def test_a_second_brand_with_the_same_code_is_refused(self, api):
        """PRD §2.4: "A brand code that is already taken is rejected with
        `ERR_DUPLICATE_BRAND_CODE`."

        Design: Corner/errors/duplicate_brand_code_returns_duplicate_brand_code
        """
        set_clock("2026-09-01T00:00:00Z")
        _brand()
        resp = api.create_brand(
            {
                "brand_code": "MSP", "display_name": "Mosaic Plumbing West",
                "trade": "PLUMBING", "royalty_rate": 0.05,
                "national_ad_fund_rate": 0.01,
                "min_certification_level": "APPRENTICE", "audit_cycle_months": 12,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BRAND_CODE)

        rows, meta = validate_paginated(api.list_brands(ADMIN, {"brand_code": "MSP"}))
        assert meta["total_count"] == 1, (
            f"brand_code is franchisor-unique, got {meta['total_count']} rows"
        )
        assert rows[0]["display_name"] == "MSP Brand"


class TestDuplicateAgreementNumber:
    def test_a_second_agreement_with_the_same_number_is_refused(self, api):
        """PRD §3.7: "A duplicate `agreement_number` is refused with
        `ERR_DUPLICATE_AGREEMENT_NUMBER`."
        PRD §2.5: "Uniqueness, set and threshold constraints hold ninth,
        reporting `ERR_TERRITORY_POSTAL_OVERLAP` alongside
        `ERR_DUPLICATE_BRAND_CODE`, `ERR_DUPLICATE_TERRITORY_CODE`,
        `ERR_DUPLICATE_AGREEMENT_NUMBER`".

        Design: Corner/errors/duplicate_agreement_number_returns_duplicate_agreement_number
        """
        set_clock("2026-09-01T00:00:00Z")
        franchisee = create_franchisee()
        brand = _brand()
        _, ter_two, _, _ = _pair_of_territories_and_agreements(brand["id"], franchisee["id"])

        resp = api.create_agreement(
            {
                "agreement_number": "A-MS-01", "franchisee_id": franchisee["id"],
                "brand_id": brand["id"], "territory_id": ter_two["id"],
                "signed_on": "2026-09-01T00:00:00Z", "initial_term_months": 120,
                "certification_level": "JOURNEYMAN",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_AGREEMENT_NUMBER)

        rows, meta = validate_paginated(
            api.list_agreements(ADMIN, {"territory_id": ter_two["id"]})
        )
        assert meta["total_count"] == 1, (
            "the refused duplicate must not be persisted; ter_two keeps only "
            f"its pre-existing agreement, got {meta['total_count']}"
        )
        assert rows[0]["agreement_number"] == "A-MS-02", (
            "the refused row must not have replaced the existing agreement"
        )
        rows, meta = validate_paginated(
            api.list_agreements(ADMIN, {"brand_id": brand["id"]})
        )
        assert meta["total_count"] == 2


class TestConductWithoutAuditor:
    def test_conducting_without_a_recorded_auditor_is_refused(self, api):
        """PRD §2.7: "Conducting requires a non-empty `auditor_operator_id`,
        supplied either on the request or already recorded on the audit, and
        refuses with `ERR_AUDITOR_REQUIRED` otherwise."

        Design: Corner/errors/conduct_audit_without_an_auditor_returns_auditor_required
        """
        set_clock("2026-09-01T00:00:00Z")
        franchisee = create_franchisee()
        brand = _brand()
        territory = create_territory(brand["id"], franchisee_id=franchisee["id"])
        agreement = create_agreement(franchisee["id"], brand["id"], territory["id"])
        offer_agreement(agreement["id"])
        offer_territory(territory["id"], franchisee["id"])
        award_territory(territory["id"])
        activate_agreement(agreement["id"])

        payload = {
            "agreement_id": agreement["id"], "audit_kind": "ANNOUNCED",
            "conducted_iso": "2026-09-01T00:00:00Z", "raw_score": 90.0,
            "findings_count": 0,
        }
        audit = validate_success(api.create_audit(payload, ADMIN), 201)

        resp = api.conduct_audit(audit["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_AUDITOR_REQUIRED)

        refused = get_audit(audit["id"])
        assert refused["audit_status"] == "SCHEDULED", (
            f"a refused conduct leaves the audit scheduled, got {refused['audit_status']}"
        )
        assert refused["weighted_score"] == 0


class TestDispatchOwnership:
    def test_a_franchisee_that_owns_no_agreement_cannot_dispatch(self, api):
        """PRD §3.4: "A work order is dispatched by the `FranchiseeOperator` who
        owns the performing agreement; an operator acting for any other
        franchisee is refused with `ERR_NOT_PERFORMING_FRANCHISEE`."

        Design: Corner/errors/terminating_a_franchisee_on_its_last_agreement_is_refused_by_ownership
        """
        set_clock("2026-09-01T00:00:00Z")
        owner = create_franchisee()
        stranger = create_franchisee(
            legal_name="Illume Metro Corp", principal_name="Ruben Salas",
            entity_type="CORPORATION", shared_services_enrolled=True,
        )
        brand = _brand()
        territory = create_territory(brand["id"], franchisee_id=owner["id"])
        agreement = create_agreement(owner["id"], brand["id"], territory["id"])
        offer_agreement(agreement["id"])
        offer_territory(territory["id"], owner["id"])
        award_territory(territory["id"])
        activate_agreement(agreement["id"])
        work_order = create_work_order(
            agreement["id"], source="DIRECT", priority="STANDARD", service_level_hours=3,
        )

        resp = api.dispatch_work_order(
            work_order["id"], make_franchisee_operator_headers(stranger["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_PERFORMING_FRANCHISEE)

        refused = get_work_order(work_order["id"])
        assert refused["status"] == "CREATED"
        assert refused["dispatched_clock_iso"] is None

        resp = api.dispatch_work_order(
            work_order["id"], make_franchisee_operator_headers(owner["id"]),
        )
        validate_success(resp, 200)


class TestReferralPartyOwnership:
    def test_a_stranger_cannot_dispute_a_referral(self, api):
        """PRD §3.5: "A `COMPLETED` referral may be disputed by either party —
        the originating franchisee or the receiving one, and an operator
        belonging to neither is refused with `ERR_NOT_REFERRAL_PARTY`".

        Design: Corner/errors/disputing_a_referral_as_a_stranger_returns_not_referral_party
        """
        ctx = setup_two_brand_pair()
        stranger = create_franchisee(
            legal_name="Copperline Services LLC", principal_name="Neve Adeyemi",
            entity_type="LLC", shared_services_enrolled=False,
        )
        referral = create_referral(
            ctx["agt_a1"]["id"], ctx["agt_a2"]["id"], ctx["fr_ms"]["id"],
        )
        accept_referral(referral["id"], ctx["fr_il"]["id"])
        complete_referral(referral["id"], ctx["fr_il"]["id"], 180000)

        resp = api.dispute_referral(
            referral["id"], "Value disputed by a third party",
            make_franchisee_operator_headers(stranger["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_REFERRAL_PARTY)

        assert get_referral(referral["id"])["status"] == "COMPLETED", (
            "the refused dispute must leave the referral completed"
        )


class TestSettleStaleAgreementVersion:
    def test_a_stale_originating_version_is_refused_and_then_accepted(self, api):
        """PRD §2.12: "Settling a referral requires `expected_agreement_version`,
        carrying the client's last observed `version` of the originating
        `FranchiseAgreement`. A mismatch is rejected with `ERR_STALE_VERSION` at
        HTTP 412."
        PRD §3.5: "The settling `FranchiseAdmin` must supply
        `expected_agreement_version` carrying the originating agreement's
        version as last observed; if another writer has advanced it, the
        settlement is refused with `ERR_STALE_VERSION` and nothing is posted."

        Design: Corner/errors/settling_a_referral_missing_its_agreement_version_returns_stale_version
        """
        ctx, referral = setup_completed_referral()
        assert get_agreement(ctx["agt_a1"]["id"])["cumulative_referral_net_cents"] == 0

        stale = ctx["agt_a1"]["version"] - 1
        resp = api.settle_referral(referral["id"], stale, ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        refused = get_agreement(ctx["agt_a1"]["id"])
        assert refused["cumulative_referral_net_cents"] == 0, (
            "a refused settlement posts nothing to the attribution ledger"
        )

        assert get_referral(referral["id"])["status"] == "COMPLETED"
        assert get_referral(referral["id"])["referral_fee_cents"] == 0

        fresh = api.get_agreement(ctx["agt_a1"]["id"], ADMIN).json()["data"]["version"]
        resp = api.settle_referral(referral["id"], fresh, ADMIN)
        settled = validate_success(resp, 200)
        assert settled["status"] == "SETTLED"


class TestApproveTransferTwice:
    def _under_review_application(self):
        set_clock("2026-09-01T00:00:00Z")
        seller = create_franchisee()
        buyer = create_franchisee(
            legal_name="Illume Metro Corp", principal_name="Ruben Salas",
            entity_type="CORPORATION", shared_services_enrolled=True,
        )
        brand = _brand()
        territory = create_territory(brand["id"], franchisee_id=seller["id"])
        agreement = create_agreement(seller["id"], brand["id"], territory["id"])
        offer_agreement(agreement["id"])
        offer_territory(territory["id"], seller["id"])
        award_territory(territory["id"])
        activate_agreement(agreement["id"])
        application = create_transfer_application(
            agreement["id"], territory["id"], buyer["id"], seller["id"],
        )
        begin_review(application["id"], "op-reviewer-macon")
        return seller, buyer, agreement, application

    def test_a_second_approval_is_refused_and_the_fee_is_not_doubled(self, api):
        """PRD §3.9: "The approving `FranchiseAdmin` must supply a non-empty
        `approval_operator_id` — absence is refused with
        `ERR_APPROVER_REQUIRED` — and that approver must differ from the
        reviewer, or `ERR_SEGREGATION_OF_DUTIES` applies."
        PRD §2.5: "State holds sixth. The target resource must be in a state from
        which the requested transition is declared, must not already have reached
        a terminal state".

        Design: Corner/errors/approving_a_transfer_twice_returns_invalid_state
        """
        _, _, _, application = self._under_review_application()

        first = validate_success(
            api.approve_transfer(application["id"], "op-approver-quill", ADMIN), 200,
        )
        assert first["status"] == "APPROVED"
        fee = first["transfer_fee_cents"]

        resp = api.approve_transfer(application["id"], "op-approver-quinn", ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        refused = get_transfer_application(application["id"])
        assert refused["transfer_fee_cents"] == fee, (
            f"the refused second approval must not recompute the fee, got "
            f"{refused['transfer_fee_cents']} against {fee}"
        )


class TestSecondTransferApplication:
    def test_a_colliding_application_is_refused(self, api):
        """PRD §3.9: "No other application for the same agreement may still be
        in `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED` or `APPROVED`
        status, because an agreement can only be in one disposition at a time; a
        collision is refused with `ERR_TRANSFER_ALREADY_PENDING`."
        PRD §3.9: "The target agreement must itself be `ACTIVE`, or the
        submission is refused with `ERR_INVALID_STATE`."

        Design: Corner/errors/second_transfer_application_for_a_pending_agreement_returns_already_pending
        """
        set_clock("2026-09-01T00:00:00Z")
        seller = create_franchisee()
        buyer = create_franchisee(
            legal_name="Illume Metro Corp", principal_name="Ruben Salas",
            entity_type="CORPORATION", shared_services_enrolled=True,
        )
        brand = _brand()
        territory = create_territory(brand["id"], franchisee_id=seller["id"])
        agreement = create_agreement(seller["id"], brand["id"], territory["id"])
        offer_agreement(agreement["id"])
        offer_territory(territory["id"], seller["id"])
        award_territory(territory["id"])
        activate_agreement(agreement["id"])
        create_transfer_application(
            agreement["id"], territory["id"], buyer["id"], seller["id"],
        )

        resp = api.create_transfer_application(
            {
                "agreement_id": agreement["id"], "territory_id": territory["id"],
                "applicant_franchisee_id": buyer["id"], "transfer_kind": "TRANSFER",
                "purchase_price_cents": 4000000, "target_territory_ids": [],
            },
            make_franchisee_operator_headers(seller["id"]),
        )
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_TRANSFER_ALREADY_PENDING.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])

        rows, meta = validate_paginated(
            api.list_transfer_applications(ADMIN, {"agreement_id": agreement["id"]})
        )
        assert meta["total_count"] == 1, (
            f"only one disposition may be open per agreement, got {meta['total_count']}"
        )
        assert get_agreement(agreement["id"])["lifecycle_status"] == "TRANSFER_PENDING"


class TestActivateBeforeTerritoryAwarded:
    def test_activating_an_offered_agreement_on_an_unawarded_territory_is_refused(self, api):
        """PRD §3.7: "The bound territory must already be `AWARDED`; activating
        an agreement whose territory has not been awarded is refused with
        `ERR_AGREEMENT_TERRITORY_NOT_AWARDED`."

        Design: Corner/errors/activating_an_agreement_before_its_territory_is_awarded_returns_territory_not_awarded
        """
        set_clock("2026-09-01T00:00:00Z")
        franchisee = create_franchisee()
        brand = _brand()
        territory = create_territory(brand["id"], franchisee_id=franchisee["id"])
        agreement = create_agreement(franchisee["id"], brand["id"], territory["id"])
        offer_territory(territory["id"], franchisee["id"])
        offer_agreement(agreement["id"])

        resp = api.activate_agreement(agreement["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_TERRITORY_NOT_AWARDED)

        assert get_agreement(agreement["id"])["lifecycle_status"] == "OFFERED"
        refused = get_territory(territory["id"])
        assert refused["status"] == "OFFERED"
        assert refused["allocated_households"] == 0
        assert get_franchisee(franchisee["id"])["active_agreement_count"] == 0


class TestDispatchUncontractedBrand:
    def test_a_brand_outside_the_programs_list_is_refused(self, api):
        """PRD §2.4: "Where a program applies, the performing brand must be a
        member of that program's `contracted_brands`, or the dispatch is refused
        with `ERR_ACCOUNT_BRAND_NOT_CONTRACTED`."

        Design: Corner/errors/dispatch_of_an_uncontracted_brand_returns_account_brand_not_contracted
        """
        set_clock("2026-09-01T00:00:00Z")
        franchisee = create_franchisee()
        ms_brand = _brand(code="MSP")
        il_brand = _brand(code="ILE", trade="ELECTRICAL", level="JOURNEYMAN")
        territory = create_territory(ms_brand["id"], franchisee_id=franchisee["id"])
        agreement = create_agreement(franchisee["id"], ms_brand["id"], territory["id"])
        offer_agreement(agreement["id"])
        offer_territory(territory["id"], franchisee["id"])
        award_territory(territory["id"])
        activate_agreement(agreement["id"])
        account = create_national_account(
            account_name="Electrics-Only Portfolio", account_type="NATIONAL_ACCOUNT",
            contracted_brands=[il_brand["id"]], service_level_hours=8,
            sla_credit_per_breach_cents=5000, breach_tolerance=3,
            annual_commitment_cents=9000000,
        )
        work_order = create_work_order(
            agreement["id"], source="NATIONAL_ACCOUNT", priority="STANDARD",
            service_level_hours=4, national_account_id=account["id"],
        )

        resp = api.dispatch_work_order(
            work_order["id"], make_franchisee_operator_headers(franchisee["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_BRAND_NOT_CONTRACTED)
        assert get_work_order(work_order["id"])["status"] == "CREATED"


class TestLeadBrandMismatch:
    def test_a_lead_cannot_be_allocated_to_an_agreement_of_another_brand(self, api):
        """PRD §3.6: "A lead may only be allocated if its `source` is
        `CALL_CENTER` and its `brand_id` matches the receiving agreement's brand;
        a mismatch is refused with `ERR_LEAD_BRAND_MISMATCH`."

        Design: Corner/errors/lead_allocation_across_brands_returns_lead_brand_mismatch
        """
        set_clock("2026-09-01T00:00:00Z")
        franchisee = create_franchisee()
        ms_brand = _brand(code="MSP")
        il_brand = _brand(code="ILE", trade="ELECTRICAL", level="JOURNEYMAN")
        ter_ms = create_territory(ms_brand["id"], franchisee_id=franchisee["id"])
        ter_il = create_territory(il_brand["id"], franchisee_id=franchisee["id"])
        agt_ms = create_agreement(franchisee["id"], ms_brand["id"], ter_ms["id"])
        agt_il = create_agreement(
            franchisee["id"], il_brand["id"], ter_il["id"], certification_level="MASTER",
        )
        for territory, agreement in ((ter_ms, agt_ms), (ter_il, agt_il)):
            offer_agreement(agreement["id"])
            offer_territory(territory["id"], franchisee["id"])
            award_territory(territory["id"])
            activate_agreement(agreement["id"])

        lead = create_lead(
            ms_brand["id"], source="CALL_CENTER", household_income_band="BAND_2",
            estimated_value_cents=120000,
        )
        resp = api.allocate_lead(
            lead["id"], franchisee_version(franchisee["id"]), ADMIN,
            allocated_agreement_id=agt_il["id"],
        )
        validate_error(resp, ApiErrorId.ERR_LEAD_BRAND_MISMATCH)

        assert get_lead(lead["id"])["status"] == "RECEIVED"