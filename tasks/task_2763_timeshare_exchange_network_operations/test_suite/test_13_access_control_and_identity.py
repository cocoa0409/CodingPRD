"""Authentication, the peer-role authorisation matrix and the per-family 404s."""

from test_helpers import (
    ANALYST_HEADERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    OPERATOR_HEADERS,
    bank_deposit,
    create_active_member,
    create_tier,
    factories,
    list_ledger_entries,
    list_page,
    make_headers,
    make_member_headers,
    make_resort_manager_headers,
    read_deposit,
    read_member,
    read_resort,
    setup_affiliated_resort,
    setup_market,
    validate_error,
    validate_success,
)

NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def _identities():
    """One tier, one member and one affiliated resort, so real ids of both kinds exist."""
    tier = create_tier()
    resort = setup_affiliated_resort()
    member = create_active_member(tier["id"])
    return {"tier": tier, "resort": resort, "member": member}


class TestAuthenticationAndIdentityBinding:
    def test_three_authentication_failures_answer_with_three_error_ids(self, api):
        """Absent headers, an unknown role and a mis-bound identity are distinct.

        PRD §2.1: "If either header is absent or empty, the request fails with
        `ERR_MISSING_AUTH_HEADERS` (HTTP 401). If `X-User-Role` carries a value
        outside the four recognised roles, the request fails with
        `ERR_UNKNOWN_ROLE` (HTTP 401)."

        Design: Corner/errors/missing_auth_headers_unknown_role_and_unknown_identity_are_rejected
        """
        world = _identities()
        tier_id = world["tier"]["id"]

        anonymous = validate_error(
            api.get_membership_tier(tier_id, NO_AUTH_HEADERS),
            ApiErrorId.ERR_MISSING_AUTH_HEADERS.value,
            401,
        )
        assert set(anonymous) == {"error_id", "message"}, (
            "the error envelope carries nothing but the id and the message"
        )

        stranger = validate_error(
            api.get_membership_tier(
                tier_id, make_headers(world["member"]["id"], "TravelAgent")
            ),
            ApiErrorId.ERR_UNKNOWN_ROLE.value,
            401,
        )
        assert set(stranger) == {"error_id", "message"}, (
            "an unrecognised role is 401, never 403"
        )

        mis_bound = validate_error(
            api.get_membership_tier(
                tier_id, make_member_headers(world["resort"]["id"])
            ),
            ApiErrorId.ERR_ACTING_IDENTITY_NOT_FOUND.value,
            404,
        )
        assert set(mis_bound) == {"error_id", "message"}, (
            "a real id of the wrong kind does not satisfy the Member binding"
        )

    def test_the_binding_is_checked_per_role_not_as_a_generic_lookup(self, api):
        """A Member id offered as a ResortManager identity is the same 404.

        PRD §2.1: "Because `Member` and `ResortManager` identities *are* looked
        up, a request in one of those two roles whose `X-User-ID` matches no
        existing `Member` row (respectively no existing `Resort` row) fails with
        `ERR_ACTING_IDENTITY_NOT_FOUND` (HTTP 404); operator and analyst
        identities are never subjected to that lookup."

        Design: Corner/errors/missing_auth_headers_unknown_role_and_unknown_identity_are_rejected
        """
        world = _identities()
        tier_id = world["tier"]["id"]

        validate_error(
            api.get_membership_tier(
                tier_id, make_resort_manager_headers(world["member"]["id"])
            ),
            ApiErrorId.ERR_ACTING_IDENTITY_NOT_FOUND.value,
            404,
        )

        reachable = validate_success(
            api.get_membership_tier(
                tier_id, make_member_headers(world["member"]["id"])
            )
        )
        assert reachable["id"] == tier_id, "the endpoint itself was always reachable"
        assert reachable["tier_code"] == "PLUS"

        opaque = validate_success(api.get_membership_tier(tier_id, ANALYST_HEADERS))
        assert opaque["id"] == tier_id, (
            "the analyst handle is never looked up, so it cannot fail the binding"
        )


class TestPerFamilyNotFoundErrors:
    def test_eleven_single_row_reads_name_eleven_different_families(self, api):
        """No generic ERR_NOT_FOUND: each family owns its own 404 identifier.

        PRD §2.10: "Every path parameter identifies an existing row, on every
        endpoint carrying one, checked left to right — otherwise the
        family-specific 404 listed in §2.4."

        Design: Corner/errors/every_path_and_body_reference_has_its_own_not_found_error
        """
        reads = (
            (api.get_membership_tier, ApiErrorId.ERR_TIER_NOT_FOUND),
            (api.get_resort, ApiErrorId.ERR_RESORT_NOT_FOUND),
            (api.get_season_band, ApiErrorId.ERR_SEASON_BAND_NOT_FOUND),
            (api.get_member, ApiErrorId.ERR_MEMBER_NOT_FOUND),
            (api.get_exchange_request, ApiErrorId.ERR_EXCHANGE_REQUEST_NOT_FOUND),
            (api.get_confirmation, ApiErrorId.ERR_CONFIRMATION_NOT_FOUND),
            (api.get_getaway_offer, ApiErrorId.ERR_GETAWAY_OFFER_NOT_FOUND),
            (api.get_dispute, ApiErrorId.ERR_DISPUTE_NOT_FOUND),
            (api.get_matching_run, ApiErrorId.ERR_MATCHING_RUN_NOT_FOUND),
            (api.get_quality_review, ApiErrorId.ERR_QUALITY_REVIEW_NOT_FOUND),
            (api.get_ledger_entry, ApiErrorId.ERR_LEDGER_ENTRY_NOT_FOUND),
        )

        observed = []
        for read, expected in reads:
            error = validate_error(
                read(NON_EXISTENT_UUID, OPERATOR_HEADERS), expected.value, 404
            )
            observed.append(error["error_id"])

        assert observed == [expected.value for _, expected in reads]
        assert len(set(observed)) == 11, "no shared generic code across the families"

    def test_the_matching_collection_reads_are_empty_rather_than_missing(self, api):
        """Absence of rows is not an error on a list endpoint.

        PRD §2.3: "The `meta` block of every list response carries `limit` and
        `offset` as they were applied, `total_count` as the number of rows
        matching the filters before pagination, and `has_more` as a boolean that
        is true when rows remain beyond the current page."

        Design: Corner/errors/every_path_and_body_reference_has_its_own_not_found_error
        """
        collections = (
            api.list_membership_tiers,
            api.list_resorts,
            api.list_season_bands,
            api.list_members,
            api.list_exchange_requests,
            api.list_confirmations,
            api.list_getaway_offers,
            api.list_disputes,
            api.list_matching_runs,
            api.list_quality_reviews,
            api.list_ledger_entries,
        )
        for listing in collections:
            rows, meta = list_page(listing(OPERATOR_HEADERS))
            assert rows == []
            assert meta["total_count"] == 0


class TestRoleExclusiveEndpoints:
    def test_each_role_is_refused_on_another_roles_exclusive_endpoint(self, api):
        """Four peers, four fences, and the gate runs before any row lookup.

        PRD §2.1: "The role model is one of peers rather than a hierarchy. A
        `Member` ... may never create or affiliate a resort, edit a resort's
        demand rating or unit capacity, create season bands, create tiers or
        other members, drive any enrollment status, execute a matching run, set
        the clock, withdraw a getaway listing, list the whole member roster, or
        take any dispute review action."

        Design: Corner/rbac/role_not_permitted_on_each_roles_exclusive_endpoints
        """
        stranger = make_member_headers(NON_EXISTENT_UUID)

        validate_error(
            api.create_membership_tier(factories.membership_tier_payload(), stranger),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            403,
        )
        validate_error(
            api.create_matching_run(
                factories.matching_run_payload("unauthorised checkpoint"),
                make_resort_manager_headers(NON_EXISTENT_UUID),
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            403,
        )
        validate_error(
            api.create_dispute(
                factories.trading_power_dispute_payload(
                    NON_EXISTENT_UUID, NON_EXISTENT_UUID
                ),
                ANALYST_HEADERS,
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            403,
        )

    def test_the_authorisation_gate_precedes_the_existence_checks(self, api):
        """Fabricated path ids still answer 403, so priority 3 beats priority 6.

        PRD §2.10: "`X-User-Role` appears among the roles authorised for the
        endpoint being called, on every endpoint — otherwise
        `ERR_ROLE_NOT_PERMITTED` (403)."

        Design: Corner/rbac/role_not_permitted_on_each_roles_exclusive_endpoints
        """
        validate_error(
            api.resolve_dispute(
                NON_EXISTENT_UUID,
                factories.dispute_resolution_payload("DENIED", "Not my place."),
                OPERATOR_HEADERS,
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            403,
        )
        validate_error(
            api.withdraw_getaway_offer(
                NON_EXISTENT_UUID, make_member_headers(NON_EXISTENT_UUID)
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            403,
        )

        _, tiers = list_page(api.list_membership_tiers(OPERATOR_HEADERS))
        assert tiers["total_count"] == 0, "none of the refused calls wrote anything"


class TestMemberOwnershipScope:
    def test_a_stranger_cannot_withdraw_someone_elses_week(self, api):
        """The role check passes and the ownership check at priority 8 stops it.

        PRD §2.10: "A `Member` caller acts only on rows it owns — otherwise
        `ERR_NOT_RESOURCE_OWNER` (403). This guards sixteen operations: recording
        a dues payment, banking a deposit, buying deposit extensions, withdrawing
        a deposit"

        Design: Corner/rbac/member_cannot_withdraw_another_members_deposit
        """
        market = setup_market(member_count=2)
        m1, m2 = market["members"][0], market["members"][1]
        week = bank_deposit(m1["id"], market["resort"]["id"])
        assert week["awarded_power"] == 82

        response = api.withdraw_deposit(week["id"], make_member_headers(m2["id"]))
        validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

        untouched = read_deposit(week["id"])
        assert untouched["deposit_status"] == "BANKED", (
            "a 403 that admits the row exists, rather than hiding it behind a 404"
        )
        assert untouched["remaining_power"] == 82
        assert read_member(m1["id"])["trading_power_balance"] == 82
        assert read_member(m2["id"])["trading_power_balance"] == 0

    def test_the_owner_making_the_identical_call_succeeds(self, api):
        """Only the identity in the header differs between the 403 and the 200.

        PRD §3.3: "On success the deposit's `remaining_power` is reversed out of
        the owner's balance through a `DEPOSIT_WITHDRAWAL_REVERSAL` ledger entry,
        and the resort's `deposits_committed_count` falls by 1 while its
        `committed_nights` falls by eight nights."

        Design: Corner/rbac/member_cannot_withdraw_another_members_deposit
        """
        market = setup_market(member_count=2)
        m1, m2 = market["members"][0], market["members"][1]
        week = bank_deposit(m1["id"], market["resort"]["id"])
        validate_error(
            api.withdraw_deposit(week["id"], make_member_headers(m2["id"])),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
            403,
        )

        withdrawn = validate_success(
            api.withdraw_deposit(week["id"], make_member_headers(m1["id"]))
        )
        assert withdrawn["deposit_status"] == "WITHDRAWN"

        assert read_member(m1["id"])["trading_power_balance"] == 0
        resort = read_resort(market["resort"]["id"])
        assert resort["deposits_committed_count"] == 0
        assert resort["committed_nights"] == 0


class TestResortManagerScope:
    def test_a_manager_cannot_read_a_neighbours_compliance_report(self, api):
        """The scope is a comparison of the path id against X-User-ID.

        PRD §2.10: "A `ResortManager` caller acts only on its own resort —
        otherwise `ERR_NOT_RESORT_MANAGER` (403). This guards two operations:
        creating a season band and reading a resort's compliance report."

        Design: Corner/rbac/resort_manager_cannot_read_another_resorts_compliance
        """
        aspen = setup_affiliated_resort()
        coral = setup_affiliated_resort(**factories.RESORT_B)

        response = api.get_resort_compliance(
            aspen["id"], make_resort_manager_headers(coral["id"])
        )
        validate_error(response, ApiErrorId.ERR_NOT_RESORT_MANAGER.value, 403)

        own = validate_success(
            api.get_resort_compliance(
                aspen["id"], make_resort_manager_headers(aspen["id"])
            )
        )
        assert own["obligation_units"] == 2
        assert own["counted_by_stay_year"] == 0
        assert own["shortfall_by_stay_year"] == 2

        neighbour = validate_success(
            api.get_resort_compliance(
                coral["id"], make_resort_manager_headers(coral["id"])
            )
        )
        assert neighbour["obligation_units"] == 1, (
            "each manager sees exactly one resort, its own"
        )

    def test_the_same_endpoint_is_unscoped_for_the_network_operator(self, api):
        """The scope is per role, not per endpoint.

        PRD §2.1: "the manager ... may read the deposit-obligation compliance
        report only for that resort, the `resort_id` path parameter again having
        to equal `X-User-ID`."

        Design: Corner/rbac/resort_manager_cannot_read_another_resorts_compliance
        """
        aspen = setup_affiliated_resort()
        coral = setup_affiliated_resort(**factories.RESORT_B)

        as_manager = validate_success(
            api.get_resort_compliance(
                aspen["id"], make_resort_manager_headers(aspen["id"])
            )
        )
        as_operator = validate_success(
            api.get_resort_compliance(aspen["id"], OPERATOR_HEADERS)
        )
        assert as_operator == as_manager, "the operator is not resort-scoped"

        both = validate_success(api.get_resort_compliance(coral["id"], OPERATOR_HEADERS))
        assert both["resort_id"] == coral["id"]
        assert both["obligation_units"] == 1


class TestSharedDepositCreation:
    def test_the_member_route_and_the_operator_proxy_route_value_alike(self, api):
        """Two roles, one endpoint, and the role changes only who may call.

        PRD §3.3: "A member — or an operator acting for one — banks a week by
        naming the depositing `member_id`, the `resort_id` whose week is being
        surrendered, the `unit_size` of that week ... and the `check_in_date` of
        the first night, written as `YYYY-MM-DD`."

        Design: Corner/rbac/deposit_creation_is_shared_between_member_and_network_operator
        """
        market = setup_market(member_count=2)
        m1, m2 = market["members"][0], market["members"][1]
        resort_id = market["resort"]["id"]

        own = validate_success(
            api.create_deposit(
                factories.deposit_payload(m1["id"], resort_id),
                make_member_headers(m1["id"]),
            ),
            201,
        )
        proxy = validate_success(
            api.create_deposit(
                factories.deposit_payload(m2["id"], resort_id), OPERATOR_HEADERS
            ),
            201,
        )
        assert own["awarded_power"] == 82
        assert proxy["awarded_power"] == 82, "the role does not change the valuation"
        assert proxy["member_id"] == m2["id"], "the operator banked for somebody else"
        assert proxy["season_band_code"] == "GOLD"

        assert read_member(m1["id"])["trading_power_balance"] == 82
        assert read_member(m2["id"])["trading_power_balance"] == 82

        rows, credits = list_ledger_entries(entry_type="DEPOSIT_CREDIT")
        assert credits["total_count"] == 2
        assert [row["power_delta"] for row in rows] == [82, 82]
        assert {row["member_id"] for row in rows} == {m1["id"], m2["id"]}

        resort = read_resort(resort_id)
        assert resort["deposits_committed_count"] == 2
        assert resort["committed_nights"] == 16

    def test_the_other_two_roles_are_refused_on_the_same_endpoint(self, api):
        """The endpoint is shared by exactly two of the four peers.

        PRD §2.1: "A `ResortManager` ... may not set demand ratings or quality
        ratings, affiliate or suspend a resort, create or read the member list,
        create deposits, file or resolve disputes, run a matching run, set the
        clock, or read another resort's compliance report."

        Design: Corner/rbac/deposit_creation_is_shared_between_member_and_network_operator
        """
        market = setup_market(member_count=2)
        m2 = market["members"][1]
        resort_id = market["resort"]["id"]
        payload = factories.deposit_payload(m2["id"], resort_id)

        validate_error(
            api.create_deposit(payload, make_resort_manager_headers(resort_id)),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            403,
        )
        validate_error(
            api.create_deposit(payload, ANALYST_HEADERS),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            403,
        )

        _, deposits = list_ledger_entries(entry_type="DEPOSIT_CREDIT")
        assert deposits["total_count"] == 0, "neither refusal banked anything"
        assert read_member(m2["id"])["trading_power_balance"] == 0
