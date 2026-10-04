"""Entity creation defaults, import initialization, and request validation."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_account_payload,
    create_portfolio_payload,
    create_source_organization_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_donor_relations_headers,
    make_platform_admin_headers,
    make_portfolio_analyst_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSourceOrganizationCreation:
    def test_create_returns_active_with_version_one(self, api):
        """PRD §3.1: "The organization is born `ACTIVE`, and its `org_type` is
        immutable once set."
        PRD §2.5: "`version` — an integer starting at 1 that increments on every
        mutation of the resource."

        Design: Corner/entities/source_org_create_returns_defaults
        """
        set_clock()
        headers = make_platform_admin_headers()
        resp = api.create_source_organization(
            create_source_organization_payload(
                name="Pecos Valley Physicians",
                org_type="PHYSICIAN_GROUP",
                state_code="NM",
                contact_email="ap@pecos.example",
            ),
            headers,
        )
        data = validate_success(resp, 201)
        assert resp.json()["response_type"] == "object"
        assert data["status"] == "ACTIVE"
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])
        assert data["org_type"] == "PHYSICIAN_GROUP"
        assert data["state_code"] == "NM"


class TestPortfolioCreationDefaults:
    def test_new_portfolio_defaults_draft_with_null_quote(self, api):
        """PRD §3.1: "The portfolio is born `DRAFT` with all computed totals at
        zero and `quoted_price_cents` unset."
        PRD §2.5: "`version` — an integer starting at 1 that increments on every
        mutation of the resource."

        Design: Corner/entities/portfolio_create_defaults_draft_with_null_quote
        """
        set_clock()
        admin = make_platform_admin_headers()
        org = get_success_data(
            api.create_source_organization(create_source_organization_payload(), admin)
        )
        resp = api.create_portfolio(
            create_portfolio_payload(org["id"]), make_portfolio_analyst_headers()
        )
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT"
        assert data["eligible_face_value_cents"] == 0
        assert data["eligible_account_count"] == 0
        assert data["abolished_face_value_cents"] == 0
        assert data["quoted_price_cents"] is None
        assert data["purchased_price_cents"] is None
        assert data["version"] == 1


class TestAccountImportInitialization:
    def test_import_initializes_three_parallel_dimensions(self, api):
        """PRD §3.1: "Every imported account begins with `eligibility_status`
        `UNSCREENED`, `lifecycle_status` `AVAILABLE`, and a `bureau_status`
        initialized from the reported flag — `REPORTED` when reported,
        `NOT_REPORTED` otherwise."

        Design: Corner/entities/account_import_initializes_three_parallel_dimensions
        """
        set_clock()
        admin = make_platform_admin_headers()
        analyst = make_portfolio_analyst_headers()
        org = get_success_data(
            api.create_source_organization(create_source_organization_payload(), admin)
        )
        pf = get_success_data(
            api.create_portfolio(create_portfolio_payload(org["id"]), analyst)
        )
        accounts = [
            create_account_payload(
                "X1",
                debtor_household_key="HX1",
                debtor_zip="75030",
                reported_to_bureau=True,
                bureau_name="EXPERIAN",
            ),
            create_account_payload(
                "X2",
                debtor_household_key="HX2",
                debtor_zip="75031",
                balance_cents=200000,
            ),
        ]
        resp = api.import_accounts(pf["id"], accounts, analyst)
        data = validate_success(resp, 201)
        assert len(data) == 2
        x1, x2 = data[0], data[1]
        for account in (x1, x2):
            assert account["eligibility_status"] == "UNSCREENED"
            assert account["lifecycle_status"] == "AVAILABLE"
            assert account["abolished_amount_cents"] is None
            assert account["abolished_at"] is None
            assert account["version"] == 1
        assert x1["bureau_status"] == "REPORTED"
        assert x2["bureau_status"] == "NOT_REPORTED"

    def test_import_household_size_zero_rejected_atomically(self, api):
        """PRD §3.1: "A `household_size` that is present but less than 1 fails
        the item as `ERR_INVALID_HOUSEHOLD_DATA`."
        PRD §3.1: "The import is atomic: any invalid item rejects the entire
        file, and the response array preserves request order."

        Design: Corner/entities/account_import_household_size_zero_rejected
        """
        set_clock()
        admin = make_platform_admin_headers()
        analyst = make_portfolio_analyst_headers()
        org = get_success_data(
            api.create_source_organization(create_source_organization_payload(), admin)
        )
        pf = get_success_data(
            api.create_portfolio(create_portfolio_payload(org["id"]), analyst)
        )
        bad = create_account_payload(
            "BAD", debtor_household_key="HB", debtor_zip="75040", household_size=0,
            annual_income_cents=100, balance_cents=1000,
        )
        good = create_account_payload(
            "GOOD", debtor_household_key="HG", debtor_zip="75041",
            annual_income_cents=100, balance_cents=1000,
        )
        resp = api.import_accounts(pf["id"], [bad, good], analyst)
        validate_error(resp, ApiErrorId.ERR_INVALID_HOUSEHOLD_DATA, 422)
        rows, meta = validate_paginated(
            api.list_accounts(analyst, params={"portfolio_id": pf["id"]})
        )
        assert rows == [] and meta["total_count"] == 0, (
            "atomic import: the valid sibling must not be persisted either"
        )

    def test_import_reported_without_bureau_name_rejected(self, api):
        """PRD §3.1: "when `reported_to_bureau` is false, `bureau_name` must be
        absent, and presenting a bureau flag without a bureau name is rejected
        as `ERR_INVALID_REQUEST`."

        Design: Corner/entities/account_import_reported_without_bureau_name_rejected
        """
        set_clock()
        admin = make_platform_admin_headers()
        analyst = make_portfolio_analyst_headers()
        org = get_success_data(
            api.create_source_organization(create_source_organization_payload(), admin)
        )
        pf = get_success_data(
            api.create_portfolio(create_portfolio_payload(org["id"]), analyst)
        )
        bad = create_account_payload(
            "NB",
            debtor_household_key="HNB",
            debtor_zip="75042",
            annual_income_cents=100,
            balance_cents=1000,
            reported_to_bureau=True,
            bureau_name=None,
        )
        resp = api.import_accounts(pf["id"], [bad], analyst)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
        rows, meta = validate_paginated(
            api.list_accounts(analyst, params={"portfolio_id": pf["id"]})
        )
        assert rows == [] and meta["total_count"] == 0


class TestNotFoundAndRequiredFields:
    def test_portfolio_get_unknown_id_returns_not_found(self, api):
        """PRD §2.7: "path-segment entities exist, validated left-to-right; the
        first missing segment fails the request (`ERR_NOT_FOUND`, 404)."

        Design: Corner/entities/portfolio_get_unknown_id_returns_not_found
        """
        set_clock()
        resp = api.get_portfolio(NON_EXISTENT_UUID, make_portfolio_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_portfolio_create_missing_label_returns_invalid_request(self, api):
        """PRD §2.7: "the body is well-formed, all required fields are present
        and correctly typed, and enum values are valid (`ERR_INVALID_REQUEST`,
        400)."
        PRD §3.1: "creates a `Portfolio` by naming the selling organization in
        `source_org_id` — a reference that must resolve to an existing
        organization or the create fails with `ERR_SOURCE_ORG_NOT_FOUND` —
        together with a human-readable `label`, the declared total
        `face_value_cents` of the bundled accounts, and the seller's
        `asking_price_cents`."

        Design: Corner/entities/portfolio_create_missing_label_returns_invalid_request
        """
        set_clock()
        admin = make_platform_admin_headers()
        analyst = make_portfolio_analyst_headers()
        org = get_success_data(
            api.create_source_organization(create_source_organization_payload(), admin)
        )
        resp = api.create_portfolio(
            {
                "source_org_id": org["id"],
                "face_value_cents": 1000,
                "asking_price_cents": 10,
            },
            analyst,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
        rows, meta = validate_paginated(api.list_portfolios(analyst))
        assert meta["total_count"] == 0, "no portfolio may be created"


class TestCampaignInputValidation:
    def test_campaign_create_invalid_earmark_enum_rejected(self, api):
        """PRD §2.7: "the body is well-formed, all required fields are present
        and correctly typed, and enum values are valid (`ERR_INVALID_REQUEST`,
        400)."
        PRD §3.5: "Each campaign has a `name`, an `earmark_type` of
        `GEOGRAPHY`, `HOSPITAL`, or `GENERAL`, and a funding `goal_cents`."

        Design: Corner/entities/campaign_create_invalid_earmark_enum_rejected
        """
        set_clock()
        resp = api.create_donor_campaign(
            {"name": "Bogus", "earmark_type": "COUNTY", "goal_cents": 1000},
            make_donor_relations_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestDonationComputedFields:
    def test_donation_fee_and_net_computed_from_gross(self, api):
        """PRD §3.5: "the processing `fee_cents` is the gift multiplied by a fee
        rate of 2.9 percent (0.029), rounded half-up to whole cents, and
        `net_cents` is the gross minus the fee."
        PRD §3.5: "Each donation is born `PLEDGED` against the campaign named by
        its path-bound `campaign_id`"

        Design: Corner/entities/donation_computed_fee_and_net_ignore_client_values
        """
        set_clock()
        dro = make_donor_relations_headers()
        campaign = get_success_data(
            api.create_donor_campaign(
                {
                    "name": "Fee Fund",
                    "earmark_type": "GENERAL",
                    "goal_cents": 1000000,
                },
                dro,
            )
        )
        resp = api.create_donation(
            campaign["id"],
            {"donor_name": "F", "donor_email": "f@x.com", "gross_cents": 10001},
            dro,
        )
        data = validate_success(resp, 201)
        assert data["fee_cents"] == 290  # round_half_up(10001 * 0.029)
        assert data["net_cents"] == 9711
        assert data["status"] == "PLEDGED"
        assert data["campaign_id"] == campaign["id"]
