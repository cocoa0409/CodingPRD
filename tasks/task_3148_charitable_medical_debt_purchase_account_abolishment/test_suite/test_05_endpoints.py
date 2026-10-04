"""Endpoint surface: filtered listings, pagination defaults, and the fixed
error envelope."""
from test_helpers import (
    ApiErrorId,
    create_account_payload,
    create_org,
    create_portfolio_payload,
    get_success_data,
    make_donor_relations_headers,
    make_finance_officer_headers,
    make_portfolio_analyst_headers,
    set_clock,
    setup_standard_settled,
    validate_paginated,
)


class TestAccountListing:
    def test_accounts_filtered_list_reverse_reaches_portfolio_fk(self, api):
        """PRD §2.3: "List endpoints also accept the filter parameters named
        against them in §4 narratives — most commonly a `status` filter matching
        the resource's lifecycle or state field, alongside resource-specific
        filters such as `portfolio_id`, `policy_id`, `account_id`, `batch_id`,
        `source_org_id`, `campaign_id`, `partnership_id`, `eligibility_status`,
        `lifecycle_status`, `bureau_status`, `abolished_batch_id`, `org_type`,
        `state_code`, `earmark_type`, `earmark_source_org_id`, `scope`, and
        `scope_source_org_id`."
        PRD §3.4: "every account whose `eligibility_status` is `ELIGIBLE` at
        settlement moves from `AVAILABLE` to `PURCHASED` and becomes valid input
        for abolishment batches, while every other account — `INELIGIBLE`,
        `NEEDS_REVIEW`, or still `UNSCREENED` — moves from `AVAILABLE` to
        terminal `EXCLUDED`."

        Design: Corner/endpoints/accounts_filtered_list_reverse_reaches_portfolio_fk
        """
        ctx = setup_standard_settled()
        pf = ctx["portfolio"]
        a1, a2, a3 = (a["id"] for a in ctx["accounts"])
        fin = make_finance_officer_headers()
        rows, meta = validate_paginated(
            api.list_accounts(fin, params={"portfolio_id": pf["id"]})
        )
        assert meta["total_count"] == 3
        assert len(rows) == 3
        rows, meta = validate_paginated(
            api.list_accounts(
                fin, params={"portfolio_id": pf["id"], "lifecycle_status": "PURCHASED"}
            )
        )
        assert meta["total_count"] == 2
        assert {r["id"] for r in rows} == {a1, a2}
        rows, meta = validate_paginated(
            api.list_accounts(fin, params={"lifecycle_status": "EXCLUDED"})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == a3

    def test_pagination_defaults_limit_ten_offset_zero(self, api):
        """PRD §2.3: "`limit` sets the maximum number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets
        the number of items skipped and defaults to 0."
        PRD §2.3: "Paginated list responses include `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/pagination_defaults_limit_ten_offset_zero
        """
        set_clock()
        analyst = make_portfolio_analyst_headers()
        org = create_org()
        pf = get_success_data(
            api.create_portfolio(create_portfolio_payload(org["id"]), analyst)
        )
        accounts = [
            create_account_payload(
                f"P{i:02d}",
                debtor_household_key=f"HP{i:02d}",
                debtor_zip=f"750{i:02d}",
                annual_income_cents=1000,
                balance_cents=1000 + i,
            )
            for i in range(12)
        ]
        get_success_data(api.import_accounts(pf["id"], accounts, analyst))
        rows, meta = validate_paginated(
            api.list_accounts(analyst, params={"portfolio_id": pf["id"]})
        )
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        assert len(rows) == 10
        rows, meta = validate_paginated(
            api.list_accounts(
                analyst, params={"portfolio_id": pf["id"], "offset": 10}
            )
        )
        assert meta["limit"] == 10
        assert meta["offset"] == 10
        assert meta["total_count"] == 12
        assert meta["has_more"] is False
        assert len(rows) == 2


class TestErrorEnvelope:
    def test_error_envelope_shape_on_4xx(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."
        PRD §3.5: "Refund is the compensating action: a `FinanceOfficer` may
        refund a `RECEIVED` donation"

        Design: Corner/endpoints/error_envelope_shape_on_4xx
        """
        set_clock()
        dro = make_donor_relations_headers()
        campaign = get_success_data(
            api.create_donor_campaign(
                {"name": "Env Fund", "earmark_type": "GENERAL",
                 "goal_cents": 1000000},
                dro,
            )
        )
        donation = get_success_data(
            api.create_donation(
                campaign["id"],
                {"donor_name": "Dee Donor", "donor_email": "dee@x.com",
                 "gross_cents": 1600000},
                dro,
            )
        )
        # Refunding a still-PLEDGED donation is a state violation.
        resp = api.refund_donation(donation["id"], make_finance_officer_headers())
        assert resp.status_code == 409
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == ApiErrorId.ERR_INVALID_STATE
        assert isinstance(body["data"]["message"], str)
        assert len(body["data"]["message"].strip()) > 0
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)
