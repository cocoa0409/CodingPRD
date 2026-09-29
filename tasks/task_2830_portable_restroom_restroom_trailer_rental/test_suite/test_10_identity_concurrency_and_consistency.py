"""Request identity, the two optimistic-concurrency guards and immediate consistency."""

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_instants_equal,
    assert_route_density,
    factories as f,
    fixtures as fx,
    headers_without_role,
    headers_without_user_id,
    make_customer_contact_headers,
    make_headers_for_role,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
COORDINATOR = TEST_USERS["permit_coordinator_headers"]
PLANNER = TEST_USERS["dispatch_planner_headers"]
DRIVER = TEST_USERS["driver_operator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
SECOND_OFFICER = TEST_USERS["second_compliance_officer_headers"]

CLOCK_START = "2026-08-03T08:00:00Z"
CLOCK_START_CANONICAL = "2026-08-03T08:00:00.000Z"


def _event_contract_payload(account_id, site_id):
    return f.rental_contract_payload(
        account_id,
        site_id,
        contract_kind="EVENT",
        term_start="2026-08-03",
        term_end="2026-08-20",
        headcount=40,
        event_duration_hours=6,
        service_frequency_per_week=3,
        season_code="OFF",
        construction_phase="EVENT_NA",
        ada_required=False,
    )


class TestSharedOperations:
    """Two write endpoints are shared by two different role pairs."""

    def test_01_both_members_of_each_sharing_pair_succeed_on_one_account(self):
        """SalesRep and PlatformAdmin both register sites; SalesRep and CustomerContact both raise contracts.

        PRD 2.1: "A `SalesRep` books demand: it registers placement sites, raises
        contracts, runs the unit-mix quote, mobilizes the contract and issues the invoice."
        PRD 2.1: "A `CustomerContact` is the renting customer. It may raise its own
        contracts and dispute charges billed to it."
        PRD 2.1: "When `X-User-Role` is `CustomerContact`, `X-User-ID` is the `id` of the
        acting `RentalAccount`; ownership checks on any resource that references a
        `RentalAccount` compare the resource's account reference to `X-User-ID`."

        Design: Corner/rbac/each_role_can_perform_its_own_shared_operations
        """
        fx.reposition_clock(CLOCK_START)
        account = fx.open_account(
            "Ivyholt Event Group", account_type="EVENT", credit_terms_days=15
        )
        account_id = account["id"]
        customer = make_customer_contact_headers(account_id)

        site_by_rep = validate_success(
            api_client.create_service_site(
                f.service_site_payload(
                    account_id, site_label="Ivyholt Green",
                    jurisdiction_code="MD-BA-CITY",
                ),
                SALES,
            ),
            201,
        )
        site_by_admin = validate_success(
            api_client.create_service_site(
                f.service_site_payload(
                    account_id, site_label="Ivyholt Annex",
                    jurisdiction_code="MD-BA-CITY",
                ),
                ADMIN,
            ),
            201,
        )
        assert site_by_rep["id"] != site_by_admin["id"]
        assert site_by_rep["account_id"] == account_id
        assert site_by_admin["account_id"] == account_id

        contract_by_rep = validate_success(
            api_client.create_rental_contract(
                _event_contract_payload(account_id, site_by_rep["id"]), SALES
            ),
            201,
        )
        contract_by_customer = validate_success(
            api_client.create_rental_contract(
                _event_contract_payload(account_id, site_by_admin["id"]), customer
            ),
            201,
        )
        assert contract_by_rep["id"] != contract_by_customer["id"]

        assert fx.read_site(site_by_rep["id"], DRIVER)["account_id"] == account_id
        assert fx.read_site(site_by_admin["id"], COORDINATOR)["account_id"] == account_id

        rows, meta = validate_paginated(
            api_client.list_rental_contracts(OFFICER, {"account_id": account_id})
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2
        assert {row["id"] for row in rows} == {
            contract_by_rep["id"], contract_by_customer["id"]
        }


class TestExclusiveOperations:
    """Each exclusive action is probed by a privileged stranger, then by its owner."""

    def test_02_five_exclusive_actions_refuse_the_wrong_role_then_accept_the_right_one(self):
        """Approve, quote, route creation, asset minting and the clock are role-locked.

        PRD 2.1: "When both headers are well formed but the named role is not among the
        roles authorized for the endpoint being called (see the table in §4), the request is
        rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD 2.1: "A `PlatformAdmin` is the operator of record. It owns reference and master
        data — customer accounts, yard assets, disposal facilities — settles invoices, and
        is the only role permitted to reposition the logical clock. It is deliberately
        excluded from quoting, permit decisions, dispatch and charge assessment."
        PRD 2.1: "A `PermitCoordinator` files placement and right-of-way permits and drives
        the resubmission cycle. It may never decide its own filings."

        Design: Corner/rbac/exclusive_operations_are_refused_to_every_other_role
        """
        fx.reposition_clock(CLOCK_START)
        account = fx.open_account("Thistledown Works")
        site = fx.register_site(
            account["id"], "Thistledown Lot", jurisdiction_code="KS-JO-CITY"
        )
        permit = fx.file_permit(site["id"], authority_ref="PL-12001")
        submitted = fx.submit_permit(permit["id"])
        assert submitted["status"] == "SUBMITTED"

        contract = fx.raise_contract(account["id"], site["id"])
        assert contract["fulfillment_state"] == "DRAFT"

        validate_error(
            api_client.approve_placement_permit(
                permit["id"], f.permit_approval_payload("AD-12001"), SALES
            ),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )
        validate_error(
            api_client.quote_rental_contract(
                contract["id"],
                f.quote_payload(contract["version"]),
                ADMIN,
            ),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )
        validate_error(
            api_client.create_route(f.route_payload(route_code="RT-MON-99"), OFFICER),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )
        validate_error(
            api_client.create_asset_unit(
                f.asset_unit_payload(asset_tag="SP-990"), PLANNER
            ),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )
        validate_error(
            api_client.set_clock("2026-09-01T00:00:00Z", PLANNER),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )

        minted = fx.add_asset_unit("SP-990")
        assert_instants_equal(
            minted["created_at"],
            CLOCK_START_CANONICAL,
            "AssetUnit.created_at proves the refused clock move did nothing",
        )

        approved = validate_success(
            api_client.approve_placement_permit(
                permit["id"], f.permit_approval_payload("AD-12001"), OFFICER
            )
        )
        assert approved["status"] == "APPROVED"

        quoted = validate_success(
            api_client.quote_rental_contract(
                contract["id"], f.quote_payload(contract["version"]), SALES
            )
        )
        assert quoted["fulfillment_state"] == "QUOTED"


class TestSegregationOfDuties:
    """Two officers hold one role, so the control turns on X-User-ID alone."""

    def test_03_an_officer_may_not_resolve_the_charge_it_assessed(self):
        """officer-1 is blocked from both uphold and waive on its own charge; officer-2 is not.

        PRD 2.1: "Those recorded operator identifiers do, however, drive one control: a
        charge event's resolution requires that the resolving `X-User-ID` differ from the
        `X-User-ID` that assessed it."
        PRD 2.1: "A `ComplianceOfficer` may both assess charges and resolve charges, but
        never the same charge; an attempt to do so is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/the_officer_who_assessed_a_charge_cannot_resolve_it
        """
        env = fx.setup_placeable_site(
            legal_name="Kettlewick Contracting",
            site_label="Kettlewick Yard",
            authority_ref="PL-12101",
            authority_decision_ref="AD-12101",
            clock=CLOCK_START,
        )
        asset_one = fx.add_asset_unit("SP-921")
        asset_two = fx.add_asset_unit("SP-922")
        contract = fx.raise_contract(env["account"]["id"], env["site"]["id"])
        fx.quote_contract(contract)
        fx.commit_deployment(contract["id"], asset_one["id"])
        fx.commit_deployment(contract["id"], asset_two["id"])
        fx.mobilize_contract(contract["id"])

        charge_a = fx.assess_damage_charge(
            contract["id"], asset_one["id"], "MODERATE", headers=OFFICER
        )
        charge_b = fx.assess_damage_charge(
            contract["id"], asset_two["id"], "MODERATE", headers=SECOND_OFFICER
        )
        assert charge_a["assessed_by_user_id"] == "officer-1"
        assert charge_b["assessed_by_user_id"] == "officer-2"
        assert charge_a["amount_cents"] == 24000

        validate_error(
            api_client.uphold_charge_event(charge_a["id"], OFFICER, {}),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )
        validate_error(
            api_client.waive_charge_event(charge_a["id"], OFFICER, {}),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )
        assert fx.read_charge(charge_a["id"])["state"] == "ASSESSED"

        upheld = fx.uphold_charge(charge_a["id"], headers=SECOND_OFFICER)
        assert upheld["state"] == "UPHELD"
        assert upheld["resolved_by_user_id"] == "officer-2"

        waived = fx.waive_charge(charge_b["id"], headers=OFFICER)
        assert waived["state"] == "WAIVED"
        assert waived["resolved_by_user_id"] == "officer-1"


class TestCustomerContactScope:
    """CustomerContact identity is entity-backed, so scope is checked against the account."""

    def test_04_a_customer_contact_cannot_write_or_dispute_across_accounts(self):
        """Account 1's contact may neither raise account 2's contract nor dispute its charge.

        PRD 2.1: "Concretely, a `CustomerContact` raising a contract must supply an
        `account_id` equal to its own `X-User-ID`, and a `CustomerContact` disputing a
        charge must be the account behind that charge's contract; either mismatch is
        rejected with `ERR_ACCOUNT_SCOPE_VIOLATION` (HTTP 403)."
        PRD 3.8: "Only the `CustomerContact` behind the charge's contract may do it — a
        mismatch is `ERR_ACCOUNT_SCOPE_VIOLATION`"

        Design: Corner/rbac/customer_contact_cannot_act_outside_its_own_account
        """
        fx.reposition_clock(CLOCK_START)
        account_one = fx.open_account("Stonecrop Holdings")
        env = fx.setup_placeable_site(
            legal_name="Ravensdale Builders",
            site_label="Ravensdale Pad",
            authority_ref="PL-12201",
            authority_decision_ref="AD-12201",
            clock=None,
        )
        account_two = env["account"]
        asset = fx.add_asset_unit("SP-931")
        contract = fx.raise_contract(account_two["id"], env["site"]["id"])
        fx.quote_contract(contract)
        fx.commit_deployment(contract["id"], asset["id"])
        fx.mobilize_contract(contract["id"])
        charge = fx.assess_damage_charge(
            contract["id"], asset["id"], "MODERATE", headers=OFFICER
        )
        assert charge["amount_cents"] == 24000

        stranger = make_customer_contact_headers(account_one["id"])

        validate_error(
            api_client.create_rental_contract(
                f.rental_contract_payload(account_two["id"], env["site"]["id"]),
                stranger,
            ),
            "ERR_ACCOUNT_SCOPE_VIOLATION",
            403,
        )
        validate_error(
            api_client.dispute_charge_event(
                charge["id"], f.dispute_payload("not our unit"), stranger
            ),
            "ERR_ACCOUNT_SCOPE_VIOLATION",
            403,
        )
        assert fx.read_charge(charge["id"])["state"] == "ASSESSED"

        disputed = fx.dispute_charge(charge["id"], account_two["id"])
        assert disputed["state"] == "DISPUTED"

        rows, meta = validate_paginated(
            api_client.list_rental_contracts(ADMIN, {"account_id": account_one["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []


class TestUnauthenticatedRequests:
    """Header presence and role recognition sit at priority 1, ahead of everything."""

    def test_05_missing_and_unknown_headers_are_401_before_any_other_check(self):
        """No role, an invented role and a missing user id are all unauthenticated, not forbidden.

        PRD 2.1: "Every request must carry both `X-User-ID` and `X-User-Role`. If either
        header is absent, or if the value of `X-User-Role` is not one of the seven role
        names declared below, the request is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."
        PRD 2.11: "1. Header presence and role recognition — `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/requests_with_a_missing_or_unknown_role_header_are_unauthenticated
        """
        fx.reposition_clock(CLOCK_START)
        account = fx.open_account(
            "Sentinel Baseline Co", account_type="EVENT", credit_terms_days=15
        )
        account_id = account["id"]

        validate_error(
            api_client.get_rental_account(account_id, headers_without_role(account_id)),
            "ERR_UNAUTHENTICATED",
            401,
        )
        body = validate_error(
            api_client.get_rental_account(
                account_id, make_headers_for_role(account_id, "SuperUser")
            ),
            "ERR_UNAUTHENTICATED",
            401,
        )
        assert body["error_id"] != "ERR_ROLE_NOT_PERMITTED"
        validate_error(
            api_client.get_rental_account(
                account_id, headers_without_user_id("PlatformAdmin")
            ),
            "ERR_UNAUTHENTICATED",
            401,
        )

        shape_violation = validate_error(
            api_client.create_rental_account(
                {"legal_name": "Sentinel Ghost"}, headers_without_role()
            ),
            "ERR_UNAUTHENTICATED",
            401,
        )
        assert shape_violation["error_id"] != "ERR_VALIDATION"

        readable = validate_success(api_client.get_rental_account(account_id, ADMIN))
        assert readable["legal_name"] == "Sentinel Baseline Co"


class TestStaleContractVersion:
    """The requote guard is checked before anything is superseded."""

    def test_06_a_replayed_quote_token_is_refused_and_supersedes_nothing(self):
        """Token 1 quotes, token 1 again is 412, token 2 requotes — one supersede in total.

        PRD 2.10: "If the supplied value does not equal the contract's stored `version`,
        the request is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412)."
        PRD 2.10: "Each successful quote run increments the contract's `version` by one, so
        a second quote replayed with the same expected version is rejected."
        PRD 3.3: "The optimistic-concurrency guard of §2.10 is what makes the loop safe: a
        re-quote whose `expected_contract_version` no longer matches the stored `version`
        is rejected with `ERR_STALE_CONTRACT_VERSION` before any line is touched."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_contract_version_on_a_requote_returns_stale_contract_version
        """
        env = fx.setup_placeable_site(
            legal_name="Windlass Civil Group",
            site_label="Windlass Terrace",
            authority_ref="PL-12301",
            authority_decision_ref="AD-12301",
            clock=CLOCK_START,
        )
        contract = fx.raise_thirteen_unit_contract(
            env["account"]["id"], env["site"]["id"]
        )
        contract_id = contract["id"]
        assert contract["fulfillment_state"] == "DRAFT"
        assert contract["version"] == 1

        quoted = validate_success(
            api_client.quote_rental_contract(contract_id, f.quote_payload(1), SALES)
        )
        assert quoted["fulfillment_state"] == "QUOTED"
        assert quoted["version"] == 2
        assert quoted["quoted_cents"] == 181500
        assert len(fx.live_quote_lines(contract_id)) == 3
        assert fx.superseded_quote_lines(contract_id) == []

        validate_error(
            api_client.quote_rental_contract(contract_id, f.quote_payload(1), SALES),
            "ERR_STALE_CONTRACT_VERSION",
            412,
        )

        after_refusal = fx.read_contract(contract_id)
        assert after_refusal["version"] == 2
        assert after_refusal["quoted_cents"] == 181500
        assert after_refusal["fulfillment_state"] == "QUOTED"
        assert len(fx.live_quote_lines(contract_id)) == 3
        assert fx.superseded_quote_lines(contract_id) == []

        requoted = validate_success(
            api_client.quote_rental_contract(contract_id, f.quote_payload(2), SALES)
        )
        assert requoted["version"] == 3
        assert requoted["quoted_cents"] == 181500
        assert len(fx.live_quote_lines(contract_id)) == 3
        assert len(fx.superseded_quote_lines(contract_id)) == 3
        assert len(fx.all_quote_lines(contract_id)) == 6


class TestStaleRouteVersion:
    """The seal guard is checked before the facility's allowance is touched."""

    def test_07_a_second_seal_replaying_the_first_token_is_refused_then_retries_clean(self):
        """Seal one bumps the route version; seal two on the old token is 412 and commits nothing.

        PRD 2.10: "If the supplied value does not equal the route's stored `version`, the
        seal is rejected with `ERR_STALE_ROUTE_VERSION` (HTTP 412)."
        PRD 3.7: "A successful seal freezes `gallons_total` at its rolled-up value,
        recomputes the facility's `committed_gallons_today`, and increments the route's
        `version` by one — which is what makes a second seal on the same route, replayed
        with the same `expected_route_version`, fail."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_route_version_on_a_second_manifest_seal_returns_stale_route_version
        """
        env = fx.setup_serviced_visit_with_manifest(
            gallons_pumped=380,
            disposal_site_code="DS-124",
            daily_gallon_cap=5000,
            shape=fx.SEVEN_UNIT,
            route_code="RT-MON-124",
            truck_capacity_units=20,
            legal_name="Hollowmere Groundworks",
            site_label="Hollowmere Verge",
            authority_ref="PL-12401",
            authority_decision_ref="AD-12401",
            site_overrides={
                "jurisdiction_code": "OR-PO-CITY",
                "access_class": "OPEN_LOT",
                "gate_open_minute": 360,
                "gate_close_minute": 1080,
                "max_truck_length_ft": 40,
            },
        )
        route_id = env["route"]["id"]
        facility_id = env["disposal_site"]["id"]
        manifest_one = env["manifest"]
        manifest_two = fx.open_manifest(route_id, facility_id, "2026-08-10", "BLACKWATER")
        stale_token = env["route_version_before_seal"]
        assert manifest_one["id"] != manifest_two["id"]
        assert fx.read_disposal_site(facility_id)["committed_gallons_today"] == 0

        sealed_one = fx.seal_manifest(manifest_one["id"], stale_token)
        assert sealed_one["state"] == "SEALED"
        assert sealed_one["gallons_total"] == 380
        assert fx.read_route(route_id)["version"] == stale_token + 1
        assert fx.read_disposal_site(facility_id)["committed_gallons_today"] == 380

        validate_error(
            api_client.seal_waste_manifest(
                manifest_two["id"], {"expected_route_version": stale_token}, DRIVER
            ),
            "ERR_STALE_ROUTE_VERSION",
            412,
        )

        assert fx.read_route(route_id)["version"] == stale_token + 1
        refused = fx.read_manifest(manifest_two["id"])
        assert refused["state"] == "OPEN"
        assert refused["gallons_total"] == 380
        assert fx.read_disposal_site(facility_id)["committed_gallons_today"] == 380

        sealed_two = fx.seal_manifest(manifest_two["id"], stale_token + 1)
        assert sealed_two["state"] == "SEALED"
        assert sealed_two["gallons_total"] == 380
        assert fx.read_route(route_id)["version"] == stale_token + 2
        assert fx.read_disposal_site(facility_id)["committed_gallons_today"] == 760


class TestCumulativeCreditHold:
    """The hold is a property of the account, not of any one contract."""

    def test_08_the_hold_fires_only_when_two_credits_together_reach_the_threshold(self):
        """One 33746 credit leaves the account clear; the second crosses 60000 and blocks the third contract.

        PRD 3.6: "The owning account's `open_credit_balance_cents` is recomputed as the
        sum of `amount_cents` over every missed-service-credit charge in `state` `ASSESSED`
        or `UPHELD` across every contract of that account."
        PRD 3.6: "The account's `billing_hold` is set to true when
        `open_credit_balance_cents` is greater than or equal to 60000 cents — six hundred
        dollars of unapplied credit is where our credit team wants the brakes applied — and
        to false otherwise."
        PRD 3.9: "Either way the owning account's `billing_hold` must be false, or the
        attempt is refused with `ERR_ACCOUNT_BILLING_HOLD`: an account sitting on six
        hundred dollars of unapplied credit does not get another invoice until the credit is
        cleared."

        Design: Corner/cross_cutting_complexity_layers/the_account_credit_hold_fires_only_once_the_cumulative_balance_reaches_the_threshold
        """
        env = fx.setup_placeable_site(
            legal_name="Netherfield Sitework",
            site_label="Netherfield Bench",
            authority_ref="PL-12501",
            authority_decision_ref="AD-12501",
            clock=CLOCK_START,
        )
        account_id = env["account"]["id"]
        site_id = env["site"]["id"]
        assert env["account"]["open_credit_balance_cents"] == 0
        assert env["account"]["billing_hold"] is False

        route_a = fx.create_route("RT-MON-125A", truck_capacity_units=20)
        route_b = fx.create_route("RT-MON-125B", truck_capacity_units=20)

        contract_a = fx.raise_contract(account_id, site_id)
        contract_b = fx.raise_contract(account_id, site_id)
        contract_c = fx.raise_contract(account_id, site_id)
        quoted_a = fx.quote_contract(contract_a)
        quoted_b = fx.quote_contract(contract_b)
        quoted_c = fx.quote_contract(contract_c)
        assert quoted_a["quoted_cents"] == 91500
        assert quoted_b["quoted_cents"] == 91500
        assert quoted_c["quoted_cents"] == 91500

        assert fx.mobilize_contract(contract_a["id"])["fulfillment_state"] == "ACTIVE"
        assert fx.mobilize_contract(contract_b["id"])["fulfillment_state"] == "ACTIVE"

        schedule_a = fx.attach_schedule(contract_a["id"], route_a["id"], "MON", 480, 600)
        schedule_b = fx.attach_schedule(contract_b["id"], route_b["id"], "MON", 480, 600)
        assert schedule_a["units_on_route"] == 7
        assert schedule_b["units_on_route"] == 7
        assert_route_density(
            fx.read_route(route_a["id"]), committed_units=7, density_planned_pct=35
        )
        assert_route_density(
            fx.read_route(route_b["id"]), committed_units=7, density_planned_pct=35
        )

        visit_a = fx.plan_visit(schedule_a["id"], "2026-08-10", 480, 540)
        visit_b = fx.plan_visit(schedule_b["id"], "2026-08-10", 480, 540)

        fx.mark_visit_missed(visit_a["id"], "truck breakdown")
        credit_a = fx.missed_service_credit_for_contract(contract_a["id"])
        assert credit_a["amount_cents"] == 33746
        assert credit_a["assessed_by_user_id"] == "SYSTEM"
        account = fx.read_account(account_id)
        assert account["open_credit_balance_cents"] == 33746
        assert account["billing_hold"] is False

        assert fx.mobilize_contract(contract_c["id"])["fulfillment_state"] == "ACTIVE"

        fx.mark_visit_missed(visit_b["id"], "truck breakdown")
        credit_b = fx.missed_service_credit_for_contract(contract_b["id"])
        assert credit_b["amount_cents"] == 33746
        account = fx.read_account(account_id)
        assert account["open_credit_balance_cents"] == 67492
        assert account["open_credit_balance_cents"] == 33746 + 33746
        assert account["billing_hold"] is True

        validate_error(
            api_client.invoice_rental_contract(contract_c["id"], SALES),
            "ERR_ACCOUNT_BILLING_HOLD",
            402,
        )
        assert fx.read_contract(contract_c["id"])["billing_state"] == "UNBILLED"


class TestImmediateConsistency:
    """Every derived field is legible in the write's own response or the very next read."""

    def test_09_each_derived_field_is_current_at_the_first_opportunity_to_observe_it(self):
        """Posture, permit status, unit counts, route figures and the ledger never lag a write.

        PRD 3.1: "A newly registered site has `deployed_unit_count` of 0, a `permit_status`
        of `NONE`, and — following directly from §2.5 — a `site_posture` of `RESTRICTED`,
        because a site with no filings can be planned against but not mobilized onto."
        PRD 3.5: "The load a schedule places on the truck is frozen at creation into
        `units_on_route`: it is the sum of `quantity` over every quote line of the named
        contract that has not been superseded, taken at the instant the schedule is created."
        PRD 3.4: "The contract's site then has its `deployed_unit_count` recomputed — that
        field is simply the number of deployments whose `site_id` is the site and whose
        `state` is `DEPLOYED`."
        PRD 2.7: "`net_billable_cents` is `invoice_subtotal_cents` plus
        `charge_debits_cents` minus `credit_accrued_cents`, and it is recomputed on every
        change to any of its three inputs."

        Design: Corner/consistency_model/every_derived_value_is_visible_in_the_same_response_or_the_next_read
        """
        fx.reposition_clock(CLOCK_START)
        account = fx.open_account("Larkspur Foundations")
        site = fx.register_site(
            account["id"], "Larkspur Cut", jurisdiction_code="ID-BO-CITY",
            access_class="OPEN_LOT", gate_open_minute=360, gate_close_minute=1080,
            max_truck_length_ft=40,
        )
        site_id = site["id"]
        permit = fx.file_permit(site_id, authority_ref="PL-12601")

        assert site["site_posture"] == "RESTRICTED"
        assert site["permit_status"] == "NONE"
        assert site["deployed_unit_count"] == 0

        route = fx.create_route("RT-MON-126", truck_capacity_units=20)
        assert_route_density(
            route, committed_units=0, density_planned_pct=0, density_realized_pct=0
        )

        asset = fx.add_asset_unit("SP-961")
        contract = fx.raise_thirteen_unit_contract(account["id"], site_id)
        contract_id = contract["id"]
        assert contract["fulfillment_state"] == "DRAFT"
        assert contract["quoted_cents"] == 0
        assert contract["credit_accrued_cents"] == 0
        assert contract["charge_debits_cents"] == 0
        assert contract["net_billable_cents"] == 0

        assert fx.submit_permit(permit["id"])["status"] == "SUBMITTED"
        after_submit = fx.read_site(site_id)
        assert after_submit["permit_status"] == "PENDING"
        assert after_submit["site_posture"] == "RESTRICTED"

        assert fx.approve_permit(permit["id"], "AD-12601")["status"] == "APPROVED"
        after_approve = fx.read_site(site_id)
        assert after_approve["permit_status"] == "APPROVED"
        assert after_approve["site_posture"] == "OPEN"

        quote_write = validate_success(
            api_client.quote_rental_contract(
                contract_id, f.quote_payload(contract["version"]), SALES
            )
        )
        assert quote_write["quoted_cents"] == 181500
        assert quote_write["credit_accrued_cents"] == 0
        assert quote_write["charge_debits_cents"] == 0
        # PRD 2.7 pins net_billable_cents to invoice_subtotal + debits - credits, and
        # nothing has been invoiced yet, so the quote leaves the net at zero.
        assert quote_write["net_billable_cents"] == 0

        schedule_write = fx.attach_schedule(contract_id, route["id"], "MON", 480, 600)
        assert schedule_write["units_on_route"] == 13

        assert_route_density(
            fx.read_route(route["id"]), committed_units=13, density_planned_pct=65,
            density_realized_pct=0,
        )

        deployment = fx.commit_deployment(contract_id, asset["id"])
        assert deployment["state"] == "RESERVED"
        assert fx.read_site(site_id)["deployed_unit_count"] == 0

        assert fx.mobilize_contract(contract_id)["fulfillment_state"] == "ACTIVE"
        assert fx.read_site(site_id)["deployed_unit_count"] == 1
        assert fx.read_deployment(deployment["id"])["state"] == "DEPLOYED"

        tip_over_write = fx.assess_tip_over_charge(contract_id, asset["id"])
        assert tip_over_write["amount_cents"] == 27500
        assert tip_over_write["state"] == "ASSESSED"
        assert_instants_equal(
            tip_over_write["assessed_at"], CLOCK_START_CANONICAL, "ChargeEvent.assessed_at"
        )

        after_charge = fx.read_contract(contract_id)
        assert after_charge["charge_debits_cents"] == 27500
        assert after_charge["credit_accrued_cents"] == 0
        assert after_charge["invoice_subtotal_cents"] == 0
        # PRD 2.7 again: 0 + 27500 - 0. The quoted figure is not an input to the net.
        assert after_charge["net_billable_cents"] == 27500

        after_charge_site = fx.read_site(site_id)
        assert after_charge_site["site_posture"] == "RESTRICTED"
        assert after_charge_site["permit_status"] == "APPROVED"
        assert after_charge_site["deployed_unit_count"] == 1
