"""The two optimistic-concurrency guards, and the immediate-consistency promise that a
recomputed derived figure is visible in the very next read."""

from test_helpers import (
    ANALYST,
    ApiErrorId,
    create_account,
    create_account_mapping_payload,
    create_order,
    create_partner,
    create_special_pricing_request_payload,
    make_partner_headers,
    propose_mapping,
    read_account,
    read_partner,
    read_registration,
    seed_reseller_draft_registration,
    set_clock,
    submit_review_and_approve,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStaleParentVersionsAreRefused:
    def test_a_replayed_registration_version_cannot_silently_void_a_pending_request(self, api):
        """PRD §2.7: "`POST /special-pricing-requests` requires a non-optional
        `expected_registration_version` field carrying the client's last observed `version` of the
        target `DealRegistration`. If that value does not equal the registration's current `version`,
        the create is rejected with `ERR_STALE_REGISTRATION_VERSION` (HTTP 412)."
        PRD §3.6: "Creating a request also supersedes its predecessors: every other request on the
        same `registration_id` still sitting in `SUBMITTED` moves `SUBMITTED → SUPERSEDED` with
        `approved_extra_margin_pct` set to 0.0 and its `version` advanced by 1."
        PRD §3.6: "The registration's own `version` advances by 1 as a result of the create, which is
        precisely why the stale-version guard exists: without it a client would silently void a
        pending request it had never seen."

        Design: Corner/cross_cutting_complexity_layers/stale_registration_version_blocks_a_special_pricing_create
        """
        seed = seed_reseller_draft_registration(clock="2026-04-01T00:00:00.000Z")
        partner_id = seed["partner"]["id"]
        registration_id = seed["registration"]["id"]
        approved = submit_review_and_approve(registration_id, partner_id)
        assert approved["status"] == "APPROVED"

        observed_version = read_registration(registration_id)["version"]

        first = validate_success(
            api.create_special_pricing_request(
                create_special_pricing_request_payload(
                    registration_id, observed_version, requested_extra_margin_pct=0.02
                ),
                make_partner_headers(partner_id),
            ),
            201,
        )
        assert first["status"] == "SUBMITTED"
        assert read_registration(registration_id)["version"] == observed_version + 1

        validate_error(
            api.create_special_pricing_request(
                create_special_pricing_request_payload(
                    registration_id, observed_version, requested_extra_margin_pct=0.03
                ),
                make_partner_headers(partner_id),
            ),
            ApiErrorId.ERR_STALE_REGISTRATION_VERSION.value,
            412,
        )

        untouched = validate_success(api.get_special_pricing_request(first["id"], ANALYST))
        assert untouched["status"] == "SUBMITTED"
        assert untouched["approved_extra_margin_pct"] is None
        fresh_version = read_registration(registration_id)["version"]
        assert fresh_version == observed_version + 1

        second = validate_success(
            api.create_special_pricing_request(
                create_special_pricing_request_payload(
                    registration_id, fresh_version, requested_extra_margin_pct=0.03
                ),
                make_partner_headers(partner_id),
            ),
            201,
        )
        assert second["status"] == "SUBMITTED"
        assert second["requested_extra_margin_pct"] == 0.03

        superseded = validate_success(api.get_special_pricing_request(first["id"], ANALYST))
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["approved_extra_margin_pct"] == 0.0

        assert read_registration(registration_id)["version"] == fresh_version + 1
        rows, meta = validate_paginated(
            api.list_special_pricing_requests(ANALYST, params={"registration_id": registration_id})
        )
        assert meta["total_count"] == 2
        assert sorted(row["id"] for row in rows) == sorted([first["id"], second["id"]])

    def test_a_replayed_account_version_is_refused_even_when_the_window_is_conflict_free(self, api):
        """PRD §2.7: "`POST /account-mappings` requires a non-optional `expected_account_version`
        field carrying the client's last observed `version` of the target `Account`. If that value
        does not equal the account's current `version`, the create is rejected with
        `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."
        PRD §2.7: "The guard matters because the account's coverage fields — `coverage_state`,
        `protected_until`, `protected_partner_id` and `direct_pursuit_owner_id` — are exactly the
        inputs a mapping agreement is negotiated against, and a proposed mapping is legitimately
        allowed to coexist with any coverage state, so nothing else would catch the staleness."

        Design: Corner/cross_cutting_complexity_layers/stale_account_version_blocks_an_account_mapping_create
        """
        set_clock("2026-03-01T00:00:00.000Z")
        partner = create_partner(
            company_name="Larkspur Networks", partner_type="RESELLER", marketing_commitment_cents=0
        )
        partner_id = partner["id"]
        account = create_account(account_name="Copperline Retail", region_code="NA")
        account_id = account["id"]
        assert account["coverage_state"] == "OPEN_CHANNEL"

        observed_version = read_account(account_id)["version"]

        first = propose_mapping(
            partner_id,
            account_id,
            observed_version,
            effective_from="2026-05-01T00:00:00.000Z",
            effective_until="2026-05-31T23:59:59.999Z",
        )
        assert first["mapping_status"] == "PROPOSED"
        assert read_account(account_id)["version"] == observed_version + 1

        validate_error(
            api.create_account_mapping(
                create_account_mapping_payload(
                    partner_id,
                    account_id,
                    observed_version,
                    effective_from="2026-10-01T00:00:00.000Z",
                    effective_until="2026-10-31T23:59:59.999Z",
                ),
                ANALYST,
            ),
            ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value,
            412,
        )
        rows, meta = validate_paginated(
            api.list_account_mappings(ANALYST, params={"account_id": account_id})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]

        fresh_version = read_account(account_id)["version"]
        assert fresh_version == observed_version + 1

        second = validate_success(
            api.create_account_mapping(
                create_account_mapping_payload(
                    partner_id,
                    account_id,
                    fresh_version,
                    effective_from="2026-10-01T00:00:00.000Z",
                    effective_until="2026-10-31T23:59:59.999Z",
                ),
                ANALYST,
            ),
            201,
        )
        assert second["mapping_status"] == "PROPOSED"
        assert second["counter_round"] == 0

        incumbent = validate_success(api.get_account_mapping(first["id"], ANALYST))
        assert incumbent["mapping_status"] == "PROPOSED"
        assert incumbent["effective_until"] == "2026-05-31T23:59:59.999Z"
        assert incumbent["counter_round"] == 0

        settled = read_account(account_id)
        assert settled["coverage_state"] == "OPEN_CHANNEL"
        assert settled["protected_partner_id"] is None


class TestDerivedFieldsAreVisibleImmediately:
    def test_the_invoicing_response_and_the_next_partner_read_already_carry_the_rollup(self, api):
        """PRD §3.6: "`invoiced_at` is set to the current logical instant, the order's `version`
        advances by 1, and the partner's `trailing_revenue_cents` is recomputed as the sum of
        `invoice_amount_cents` across that partner's orders whose `status` is `INVOICED` or
        `CREDITED`."
        PRD §3.6: "At the partner level, `trailing_revenue_cents` always equals the sum of
        `invoice_amount_cents` over that partner's orders in `INVOICED` and `CREDITED`."

        Design: Corner/consistency_model/derived_fields_are_visible_in_the_same_response
        """
        set_clock("2026-03-01T00:00:00.000Z")
        partner = create_partner(
            company_name="Marlin Channel", partner_type="RESELLER", marketing_commitment_cents=0
        )
        partner_id = partner["id"]

        order = create_order(partner_id, order_type="DROP_SHIP", list_amount_cents=1_000_000)
        assert order["status"] == "PENDING"
        assert order["margin_pct"] == 0.1
        assert order["invoice_amount_cents"] == 900000
        assert order["invoiced_at"] is None
        assert read_partner(partner_id)["trailing_revenue_cents"] == 0

        invoiced = validate_success(api.invoice_order(order["id"], ANALYST))
        assert invoiced["status"] == "INVOICED"
        assert invoiced["invoiced_at"] == "2026-03-01T00:00:00.000Z"
        assert invoiced["invoice_amount_cents"] == 900000

        assert read_partner(partner_id)["trailing_revenue_cents"] == 900000
