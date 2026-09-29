"""Membership tiers, enrollment, annual dues and tier changes."""

from test_helpers import (
    ApiErrorId,
    OPERATOR_HEADERS,
    assert_common_fields,
    assert_member,
    assert_membership_tier,
    bank_deposit,
    create_member,
    create_tier,
    factories,
    file_exchange_request,
    is_iso8601_timestamp,
    is_valid_uuid,
    list_ledger_entries,
    make_member_headers,
    pay_dues,
    read_member,
    run_matching,
    set_clock,
    setup_affiliated_resort,
    validate_error,
    validate_success,
)

BASIC_TIER = {
    "tier_code": "BASIC",
    "annual_dues_cents": 9900,
    "base_exchange_fee_cents": 21900,
    "priority_surcharge_cents": 0,
    "priority_window_days": 180,
    "deposit_first_bonus_pct": 0,
    "max_active_requests": 1,
    "cancellation_fee_cents": 9900,
    "reinstatement_fee_cents": 12900,
    "extension_fee_cents_per_month": 3900,
}

ELITE_TIER = {
    "tier_code": "ELITE",
    "annual_dues_cents": 39900,
    "base_exchange_fee_cents": 18900,
    "priority_surcharge_cents": 6000,
    "priority_window_days": 730,
    "deposit_first_bonus_pct": 20,
    "max_active_requests": 5,
    "cancellation_fee_cents": 6900,
    "reinstatement_fee_cents": 8900,
    "extension_fee_cents_per_month": 2900,
}


class TestMembershipTierCreation:
    def test_tier_creation_echoes_every_declared_field(self, api):
        """A tier echoes its whole fee schedule and its four common fields.

        PRD §3.2: "A `NetworkOperator` defines a tier with a `tier_code` of
        `BASIC`, `PLUS` or `ELITE` — unique across all tiers — and the
        ten-figure fee schedule attached to it: `annual_dues_cents`, the dues
        withheld from each dues payment before the remainder becomes wallet
        credit; `base_exchange_fee_cents`, the flat base of every exchange
        charge; `priority_surcharge_cents`, a flat surcharge added to the
        exchange charge subtotal in return for the tier's priority window;
        `priority_window_days`, how many days ahead of a matching run's as-of
        date this tier may see candidate inventory, at least 1;
        `deposit_first_bonus_pct`, the percentage uplift the tier grants to a
        deposit-first request's power budget, between 0 and 100 inclusive;
        `max_active_requests`, the ceiling on the member's simultaneously live
        exchange requests, at least 1; `cancellation_fee_cents`, levied when
        one of this tier's confirmations is cancelled; `reinstatement_fee_cents`,
        levied when a cancelled confirmation is reinstated; and
        `extension_fee_cents_per_month`, charged per extension month bought on
        a deposit."

        Design: Corner/entities/membership_tier_creation_echoes_every_declared_field
        """
        payload = factories.membership_tier_payload()
        response = api.create_membership_tier(payload, OPERATOR_HEADERS)
        data = validate_success(response, 201)

        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

        for field, expected in payload.items():
            assert data[field] == expected, f"tier must echo {field} as {expected!r}"
            if field != "tier_code":
                assert isinstance(data[field], int) and not isinstance(data[field], bool), (
                    f"{field} must be echoed as an integer, got {data[field]!r}"
                )
        assert_membership_tier(data)
        assert data["version"] == 1

    def test_tier_read_back_returns_identical_values(self, api):
        """A tier read back reports the same field values it was created with.

        PRD §2.4: "Every resource is identified by `id`, a server-minted UUID
        carried as a plain string with no type prefix, and every resource
        carries `created_at`, an ISO 8601 UTC timestamp with three fractional
        digits recording the instant the row was written."

        Design: Corner/entities/membership_tier_creation_echoes_every_declared_field
        """
        payload = factories.membership_tier_payload()
        created = validate_success(api.create_membership_tier(payload, OPERATOR_HEADERS), 201)
        assert is_valid_uuid(created["id"])

        fetched = validate_success(api.get_membership_tier(created["id"], OPERATOR_HEADERS))
        for field in payload:
            assert fetched[field] == created[field], (
                f"read-back tier disagrees on {field}"
            )
        assert fetched["id"] == created["id"]
        assert fetched["version"] == created["version"]


class TestMemberEnrollment:
    def test_member_system_fields_are_initialised_by_the_server(self, api):
        """A new member opens PENDING_PAYMENT with zeroed balances.

        PRD §3.2: "A new member starts with `enrollment_status`
        `PENDING_PAYMENT`, a null `dues_paid_through`, a
        `trading_power_balance` of 0, a `wallet_credit_cents` of 0 and an
        `active_request_count` of 0."

        Design: Corner/entities/member_system_and_computed_fields_initialised_by_server
        """
        tier = create_tier()
        response = api.create_member(
            factories.member_payload(tier["id"]), OPERATOR_HEADERS
        )
        data = validate_success(response, 201)

        assert data["enrollment_status"] == "PENDING_PAYMENT"
        assert data["trading_power_balance"] == 0
        assert data["wallet_credit_cents"] == 0
        assert data["active_request_count"] == 0
        assert data["dues_paid_through"] is None
        assert data["home_resort_id"] is None
        assert_member(data)
        assert_common_fields(data, "member")
        assert data["version"] == 1

    def test_member_creation_writes_no_ledger_row(self, api):
        """Enrolling a member moves neither balance, so no entry is posted.

        PRD §2.7: "a member's `trading_power_balance` always equals the sum of
        `power_delta` across every ledger entry whose `member_id` is that
        member, and their `wallet_credit_cents` always equals the sum of
        `cash_delta_cents` across those same entries."

        Design: Corner/entities/member_system_and_computed_fields_initialised_by_server
        """
        tier = create_tier()
        member = create_member(tier["id"])

        rows, meta = list_ledger_entries(member_id=member["id"])
        assert meta["total_count"] == 0, (
            "a member with zero balances must have no ledger rows"
        )
        assert rows == []


class TestDuesPaymentGate:
    def test_dues_one_cent_below_the_tier_amount_is_rejected(self, api):
        """A payment one cent short of the tier dues is refused with 422.

        PRD §3.2: "The payment must be at least the tier's
        `annual_dues_cents`, or it is refused with
        `ERR_INSUFFICIENT_DUES_PAYMENT`."

        Design: Corner/validations/dues_payment_below_the_tier_annual_amount_is_rejected
        """
        tier = create_tier()
        member = create_member(tier["id"])

        response = api.create_dues_payment(
            member["id"],
            factories.dues_payment_payload(
                member["version"],
                amount_cents=19899,
                paid_through_date="2027-08-31",
            ),
            make_member_headers(member["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_DUES_PAYMENT.value, 422)

        after = read_member(member["id"])
        assert after["enrollment_status"] == "PENDING_PAYMENT"
        assert after["wallet_credit_cents"] == 0
        assert after["dues_paid_through"] is None
        assert after["version"] == 1, "a rejected payment mutates nothing"

        _, meta = list_ledger_entries(member_id=member["id"])
        assert meta["total_count"] == 0, "no partial DUES_PAYMENT row may be written"

    def test_dues_exactly_at_the_tier_amount_activates_with_zero_credit(self, api):
        """Paying exactly the dues activates the member and credits nothing.

        PRD §3.2: "A member who pays exactly the dues receives a ledger entry
        of zero cash movement."

        Design: Corner/validations/dues_payment_below_the_tier_annual_amount_is_rejected
        """
        tier = create_tier()
        member = create_member(tier["id"])

        data = validate_success(
            api.create_dues_payment(
                member["id"],
                factories.dues_payment_payload(
                    member["version"],
                    amount_cents=19900,
                    paid_through_date="2027-08-31",
                ),
                make_member_headers(member["id"]),
            )
        )
        assert data["enrollment_status"] == "ACTIVE"
        assert data["wallet_credit_cents"] == 0
        assert data["dues_paid_through"] == "2027-08-31"

        rows, meta = list_ledger_entries(
            member_id=member["id"], entry_type="DUES_PAYMENT"
        )
        assert meta["total_count"] == 1
        assert rows[0]["cash_delta_cents"] == 0


class TestEnrollmentLapseCycle:
    def test_clock_alone_lapses_nobody(self, api):
        """Advancing the clock past the paid-through date lapses no member.

        PRD §2.5: "Moving the clock has no consequences of its own: no deposit
        expires, no request is swept, no confirmation completes and no resort
        changes its affiliation state merely because the clock advanced past a
        threshold."

        Design: Corner/state_machines/member_lapsed_then_reactivated_by_a_new_dues_payment
        """
        tier = create_tier()
        member = create_member(tier["id"])
        pay_dues(member, amount_cents=19900, paid_through_date="2026-08-31")

        set_clock("2026-10-01T00:00:00Z")

        after = read_member(member["id"])
        assert after["enrollment_status"] == "ACTIVE", (
            "only a matching run may lapse a member"
        )
        assert after["dues_paid_through"] == "2026-08-31"

    def test_run_lapses_the_member_and_a_new_payment_reactivates_it(self, api):
        """The cycle ACTIVE to LAPSED to ACTIVE closes through step 0 and a payment.

        PRD §3.5: "Every member whose `enrollment_status` is `ACTIVE` and whose
        `dues_paid_through` is earlier than the calendar date of `as_of_utc`
        moves `ACTIVE` → `LAPSED`, processed in `created_at` ascending order."
        PRD §3.2: "The move `LAPSED` → `ACTIVE` requires both that
        `amount_cents` is at least the tier's `annual_dues_cents` and that the
        submitted `paid_through_date` is not earlier than the calendar date of
        the current logical clock instant."

        Design: Corner/state_machines/member_lapsed_then_reactivated_by_a_new_dues_payment
        """
        tier = create_tier()
        member = create_member(tier["id"])
        pay_dues(member, amount_cents=19900, paid_through_date="2026-08-31")
        set_clock("2026-10-01T00:00:00Z")

        run = validate_success(
            api.create_matching_run(
                factories.matching_run_payload("october sweep"), OPERATOR_HEADERS
            ),
            201,
        )
        assert run["lapsed_member_count"] == 1

        lapsed = read_member(member["id"])
        assert lapsed["enrollment_status"] == "LAPSED"
        assert lapsed["wallet_credit_cents"] == 0
        assert lapsed["dues_paid_through"] == "2026-08-31"

        reactivated = validate_success(
            api.create_dues_payment(
                member["id"],
                factories.dues_payment_payload(
                    lapsed["version"],
                    amount_cents=19900,
                    paid_through_date="2027-08-31",
                ),
                make_member_headers(member["id"]),
            )
        )
        assert reactivated["enrollment_status"] == "ACTIVE"
        assert reactivated["dues_paid_through"] == "2027-08-31"

        _, meta = list_ledger_entries(
            member_id=member["id"], entry_type="DUES_PAYMENT"
        )
        assert meta["total_count"] == 2

    def test_reactivating_with_the_pre_run_version_is_stale(self, api):
        """The run bumped the member row, so its earlier version no longer writes.

        PRD §2.9: "`POST /exchange-network/members/{member_id}/dues-payments`
        requires `expected_member_version` carrying the client's last observed
        `version` of the target `Member`. On mismatch the rejection is
        `ERR_STALE_VERSION` with HTTP 412 and `enrollment_status`,
        `dues_paid_through` and `wallet_credit_cents` keep their previous values
        with no `DUES_PAYMENT` ledger entry written."

        Design: Corner/state_machines/member_lapsed_then_reactivated_by_a_new_dues_payment
        """
        tier = create_tier()
        member = create_member(tier["id"])
        activated = pay_dues(member, amount_cents=19900, paid_through_date="2026-08-31")
        pre_run_version = activated["version"]
        set_clock("2026-10-01T00:00:00Z")
        run_matching("october sweep")

        response = api.create_dues_payment(
            member["id"],
            factories.dues_payment_payload(
                pre_run_version,
                amount_cents=19900,
                paid_through_date="2027-08-31",
            ),
            make_member_headers(member["id"]),
        )
        validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

        still_lapsed = read_member(member["id"])
        assert still_lapsed["enrollment_status"] == "LAPSED"
        assert still_lapsed["dues_paid_through"] == "2026-08-31"
        assert still_lapsed["wallet_credit_cents"] == 0
        _, meta = list_ledger_entries(
            member_id=member["id"], entry_type="DUES_PAYMENT"
        )
        assert meta["total_count"] == 1


class TestTierChange:
    def test_tier_change_rewrites_only_the_pointer(self, api):
        """Switching tiers keeps the enrollment and the wallet exactly as they were.

        PRD §3.2: "A member may be moved onto a different tier at any time by
        an operator supplying the new `tier_id`."

        Design: Corner/endpoints/member_tier_change_switches_the_fee_schedule
        """
        basic = create_tier(**BASIC_TIER)
        elite = create_tier(**ELITE_TIER)
        member = create_member(basic["id"])
        member = pay_dues(member, amount_cents=100000, paid_through_date="2030-12-31")
        assert member["wallet_credit_cents"] == 90100, (
            "BASIC withholds 9900 of the 100000 paid"
        )

        changed = validate_success(
            api.change_member_tier(
                member["id"], factories.tier_change_payload(elite["id"]), OPERATOR_HEADERS
            )
        )
        assert changed["tier_id"] == elite["id"]
        assert changed["version"] > member["version"]
        assert changed["enrollment_status"] == "ACTIVE"
        assert changed["dues_paid_through"] == "2030-12-31"
        assert changed["wallet_credit_cents"] == 90100, (
            "moving to a dearer tier does not retroactively withhold its dues"
        )

    def test_request_after_the_switch_is_priced_by_the_new_tier(self, api):
        """A request filed after the switch reads budget and fees through the new tier.

        PRD §3.2: "The change is forward-looking only: it governs requests
        created after the change, and any exchange charge already quoted on an
        existing request is not repriced."

        Design: Corner/endpoints/member_tier_change_switches_the_fee_schedule
        """
        basic = create_tier(**BASIC_TIER)
        elite = create_tier(**ELITE_TIER)
        resort = setup_affiliated_resort()
        member = create_member(basic["id"])
        member = pay_dues(member, amount_cents=100000, paid_through_date="2030-12-31")
        deposit = bank_deposit(member["id"], resort["id"], check_in_date="2027-06-15")
        assert deposit["awarded_power"] == 82

        validate_success(
            api.change_member_tier(
                member["id"], factories.tier_change_payload(elite["id"]), OPERATOR_HEADERS
            )
        )

        request = file_exchange_request(
            member["id"],
            resort["id"],
            requested_unit_size="ONE_BR",
            window_start_date="2027-06-15",
            window_end_date="2027-06-15",
            deposit_id=deposit["id"],
        )
        assert request["power_budget"] == 98, (
            "the ELITE 20 percent deposit-first bonus turns 82 into 98"
        )
        assert request["quoted_charge_cents"] == 24410, (
            "subtotal 18900 + 0 shortfall + 6000 surcharge, credit 2490, fee 2000"
        )

        after = read_member(member["id"])
        assert after["wallet_credit_cents"] == 65690
        assert after["active_request_count"] == 1
