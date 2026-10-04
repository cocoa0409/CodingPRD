"""Entity-level corner claims: creation, retrieval, defaults, listing and typing."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    activate_agreement,
    award_territory,
    create_agreement,
    create_brand,
    create_franchisee,
    create_territory,
    create_work_order,
    dispatch_and_start,
    get_agreement,
    make_franchisee_operator_headers,
    offer_agreement,
    offer_territory,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["franchise_admin_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


class TestBrandCreation:
    def test_brand_create_round_trips_every_declared_field_and_starts_active(self, api):
        """PRD §2.4: "Each brand is registered with a `brand_code` that is unique
        across the franchisor and must match the pattern of three to twelve
        characters drawn from uppercase letters, digits and hyphens; a
        `display_name` for customer-facing use; a `trade`, which is one of
        `PLUMBING`, `ELECTRICAL`, `HVAC`, `RESTORATION`, `CLEANING`, `PEST` or
        `APPLIANCE`; a `royalty_rate` and a `national_ad_fund_rate`, each of
        which must lie between 0 and 1 inclusive; a `min_certification_level` of
        `APPRENTICE`, `JOURNEYMAN` or `MASTER`; an `audit_cycle_months` of at
        least 1".
        PRD §2.4: "Creating a brand places it in an `ACTIVE` standing."
        PRD §2.11: "`id` — a unique, system-generated identifier formatted as a
        UUID with no type prefix or namespace decoration."

        Design: Corner/entities/brand_create_returns_all_declared_fields_and_starts_active
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.create_brand(
            {
                "brand_code": "MSP",
                "display_name": "Mosaic Plumbing",
                "trade": "PLUMBING",
                "royalty_rate": 0.06,
                "national_ad_fund_rate": 0.01,
                "min_certification_level": "APPRENTICE",
                "audit_cycle_months": 12,
            },
            ADMIN,
        )
        created = validate_success(resp, 201)

        assert created["brand_code"] == "MSP"
        assert created["trade"] == "PLUMBING"
        assert created["royalty_rate"] == 0.06
        assert created["national_ad_fund_rate"] == 0.01
        assert created["min_certification_level"] == "APPRENTICE"
        assert created["audit_cycle_months"] == 12
        assert created["status"] == "ACTIVE", (
            f"a brand enters service immediately, got {created['status']}"
        )
        assert created["id"], "the response must carry a server-minted id"
        assert created["created_at"], "the response must carry created_at"
        assert created["updated_at"], "the response must carry updated_at"


class TestFranchiseeRetrieval:
    def test_the_stored_aggregate_round_trips_with_its_score_basis(self, api):
        """PRD §2.4: "The franchisee's `standards_score` is a trailing brand
        standards score, and the `standards_score_basis` field records which
        variant produced it: `AUDIT_BASED` when the franchisee holds exactly one
        agreement, and `TRAILING_WINDOW` otherwise."
        PRD §2.6: "On the franchisee, `allocated_households` is a maintained
        counter".

        Design: Corner/entities/franchisee_get_returns_the_stored_aggregate_with_its_basis
        """
        set_clock("2026-09-01T00:00:00Z")
        franchisee = create_franchisee()
        brand = create_brand(
            brand_code="MSP", display_name="Mosaic Plumbing", trade="PLUMBING",
            royalty_rate=0.06, national_ad_fund_rate=0.01,
            min_certification_level="APPRENTICE", audit_cycle_months=12,
            cross_brand_fee_table={},
        )
        territory = create_territory(
            brand["id"], franchisee_id=franchisee["id"], household_count=30000,
        )
        agreement = create_agreement(franchisee["id"], brand["id"], territory["id"])
        offer_agreement(agreement["id"])
        offer_territory(territory["id"], franchisee["id"])
        award_territory(territory["id"])
        activate_agreement(agreement["id"])

        resp = api.get_franchisee(franchisee["id"], ADMIN)
        stored = validate_success(resp, 200)

        assert stored["status"] == "ACTIVE", (
            f"a franchisee still in PROSPECT is promoted to ACTIVE on first "
            f"activation, got {stored['status']}"
        )
        assert stored["entity_type"] == "LLC"
        assert stored["shared_services_enrolled"] is True
        assert stored["active_brand_count"] == 1
        assert stored["active_agreement_count"] == 1
        assert stored["allocated_households"] == 30000
        assert stored["standards_score_basis"] == "AUDIT_BASED", (
            "exactly one agreement is held, so the single-audit variant is "
            f"recorded, got {stored['standards_score_basis']}"
        )
        assert stored["lead_cost_balance_cents"] == 0


class TestAgreementListing:
    def test_pagination_counts_the_whole_filtered_set_not_the_page(self, api):
        """PRD §2.3: "List endpoints accept a `limit` query parameter giving the
        maximum number of items to return, and an `offset` query parameter giving
        the number of items to skip. When `limit` is omitted it defaults to 10;
        its minimum accepted value is 1 and its maximum is 100."
        PRD §2.3: "Every list response carries the pagination fields `limit`,
        `offset`, `total_count` and `has_more` in the `meta` object of the
        response envelope."

        Design: Corner/entities/agreements_list_paginates_and_reports_total_count_and_has_more
        """
        set_clock("2026-09-01T00:00:00Z")
        franchisee = create_franchisee()
        profiles = (
            ("MSP", "PLUMBING", "APPRENTICE"),
            ("ILE", "ELECTRICAL", "JOURNEYMAN"),
            ("RVR", "RESTORATION", "MASTER"),
        )
        for code, trade, level in profiles:
            brand = create_brand(
                brand_code=code, display_name=f"{code} Brand", trade=trade,
                royalty_rate=0.06, national_ad_fund_rate=0.01,
                min_certification_level=level, audit_cycle_months=12,
                cross_brand_fee_table={},
            )
            territory = create_territory(brand["id"], franchisee_id=franchisee["id"])
            create_agreement(franchisee["id"], brand["id"], territory["id"])

        rows, meta = validate_paginated(
            api.list_agreements(ADMIN, {"franchisee_id": franchisee["id"],
                                        "limit": 2, "offset": 0})
        )
        assert len(rows) == 2
        assert meta["total_count"] == 3, (
            f"total_count counts the whole filtered set, got {meta['total_count']}"
        )
        assert meta["has_more"] is True

        rows, meta = validate_paginated(
            api.list_agreements(ADMIN, {"franchisee_id": franchisee["id"],
                                        "limit": 2, "offset": 2})
        )
        assert len(rows) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False

        rows, meta = validate_paginated(api.list_agreements(ADMIN, {}))
        assert len(rows) == 3
        assert meta["limit"] == 10, (
            f"an omitted limit defaults to 10, got {meta['limit']}"
        )
        assert meta["offset"] == 0


class TestAgreementNotFound:
    def test_an_unknown_agreement_id_returns_the_entity_specific_not_found(self, api):
        """PRD §2.5: "Existence holds fifth. Every referenced resource must
        exist. Path identifiers are resolved left to right, and once the path is
        exhausted the body foreign keys are resolved in the order the endpoint's
        input list declares them; the first reference that fails decides the
        error."

        Design: Corner/entities/agreement_get_with_an_unknown_id_returns_agreement_not_found
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.get_agreement("00000000-0000-4000-8000-000000000000", ADMIN)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_FOUND)

        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"]
        assert body["data"]["message"]


class TestWorkOrderDefaults:
    def test_omitted_parts_default_to_zero_and_direct_labor_is_unscaled(self, api):
        """PRD §3.4: "A `parts_cents` figure may be supplied and defaults to
        zero."
        PRD §3.4: "one whole for `STANDARD` — and the result is rounded up to a
        whole number of hours and floored at a minimum of one hour."

        Design: Corner/entities/work_order_create_without_parts_defaults_parts_and_revenue_to_zero
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

        work_order = create_work_order(
            agreement["id"], source="DIRECT", priority="STANDARD",
            service_level_hours=2,
        )
        assert work_order["parts_cents"] == 0, (
            f"an omitted parts_cents stores 0 rather than null, got "
            f"{work_order['parts_cents']!r}"
        )

        dispatch_and_start(work_order["id"], franchisee["id"])
        resp = api.complete_work_order(
            work_order["id"], make_franchisee_operator_headers(franchisee["id"]),
        )
        completed = validate_success(resp, 200)

        assert completed["status"] == "COMPLETED"
        assert completed["labor_cents"] == 29000, (
            f"2 whole hours at the STANDARD rate 14500 with a DIRECT multiplier "
            f"of 1.00 is 29000, got {completed['labor_cents']}"
        )
        assert completed["revenue_cents"] == 29000


class TestAgreementExpiryDerivation:
    def test_expires_on_is_derived_from_the_signature_and_term(self, api):
        """PRD §3.7: "The expiry is derived, not supplied: `expires_on` is the
        `signed_on` instant advanced by the contracted number of calendar
        months, and the initial term may not be shorter than twelve months."

        Design: Corner/entities/expired_territory_status_is_recomputed_on_clock_advance
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
        agreement = create_agreement(
            franchisee["id"], brand["id"], territory["id"],
            signed_on="2026-09-01T00:00:00Z", initial_term_months=12,
        )
        offer_agreement(agreement["id"])
        offer_territory(territory["id"], franchisee["id"])
        award_territory(territory["id"])
        activate_agreement(agreement["id"])

        stored = get_agreement(agreement["id"])
        assert stored["expires_on"] == "2027-09-01T00:00:00Z", (
            f"a 12-month term signed 2026-09-01T00:00:00Z expires "
            f"2027-09-01T00:00:00Z, got {stored['expires_on']}"
        )

        set_clock("2027-08-31T23:59:59Z")
        resp = api.expire_agreement(agreement["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_EXPIRABLE)
        assert get_agreement(agreement["id"])["lifecycle_status"] == "ACTIVE"


class TestFranchiseeInitialStanding:
    def test_a_new_franchisee_starts_in_prospect_with_zeroed_counters(self, api):
        """PRD §2.4: "A newly created franchisee begins in `PROSPECT` standing
        with its `active_brand_count`, `active_agreement_count` and
        `allocated_households` all set to zero and a `lead_cost_balance_cents` of
        zero."

        Design: Corner/entities/franchisee_create_ignores_client_supplied_status_and_version
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.create_franchisee(
            {
                "legal_name": "Mosaic Central LLC",
                "principal_name": "Dana Vaughn",
                "entity_type": "LLC",
                "shared_services_enrolled": True,
            },
            ADMIN,
        )
        created = validate_success(resp, 201)

        assert created["status"] == "PROSPECT", (
            f"a newly created franchisee begins in PROSPECT, got {created['status']}"
        )
        assert created["active_agreement_count"] == 0
        assert created["active_brand_count"] == 0
        assert created["allocated_households"] == 0
        assert created["lead_cost_balance_cents"] == 0

        rows, meta = validate_paginated(api.list_franchisees(ADMIN, {"status": "PROSPECT"}))
        assert meta["total_count"] == 1


class TestBrandTradeEnum:
    def test_an_undeclared_trade_is_rejected_at_the_request_shape_rung(self, api):
        """PRD §2.5: "Request shape holds third. Required body fields must be
        present, every supplied enum member must be declared, no field outside
        the endpoint's declared input list may be supplied, and
        conditionally-required fields must be present on the transition that
        requires them; any failure yields `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/brand_create_with_an_out_of_enum_trade_returns_invalid_request
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.create_brand(
            {
                "brand_code": "RFR",
                "display_name": "Ridge Roofing",
                "trade": "ROOFING",
                "royalty_rate": 0.06,
                "national_ad_fund_rate": 0.01,
                "min_certification_level": "APPRENTICE",
                "audit_cycle_months": 12,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_DUPLICATE_BRAND_CODE.value

        rows, meta = validate_paginated(api.list_brands(ADMIN, {"trade": "PLUMBING"}))
        assert meta["total_count"] == 0, "no brand may have been persisted"


class TestWorkOrderForeignKeyResolutionOrder:
    def test_body_foreign_keys_are_resolved_in_the_declared_input_order(self, api):
        """PRD §2.14: "once the path references have been resolved, the body's
        foreign keys are resolved in the order the endpoint declares them, so
        that where two body references are both broken the caller learns about
        the earlier one."
        PRD §2.5: "Every referenced resource must exist."

        Design: Corner/entities/work_order_create_checks_fk_existence_in_declared_input_order
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

        missing = "00000000-0000-4000-8000-000000000002"

        # `agreement_id` is declared before `national_account_id`, so with both
        # broken the caller learns about the agreement first.
        resp = api.create_work_order(
            {
                "agreement_id": "00000000-0000-4000-8000-000000000001",
                "source": "NATIONAL_ACCOUNT",
                "priority": "STANDARD",
                "service_level_hours": 4,
                "national_account_id": missing,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_FOUND)
        assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value

        # With only the later reference broken, the account error surfaces.
        resp = api.create_work_order(
            {
                "agreement_id": agreement["id"],
                "source": "NATIONAL_ACCOUNT",
                "priority": "STANDARD",
                "service_level_hours": 4,
                "national_account_id": missing,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_FOUND)

        rows, meta = validate_paginated(
            api.list_work_orders(ADMIN, {"agreement_id": agreement["id"]})
        )
        assert meta["total_count"] == 0