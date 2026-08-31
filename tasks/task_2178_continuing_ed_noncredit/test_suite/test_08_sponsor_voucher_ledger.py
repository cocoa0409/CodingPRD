"""Corporate sponsorship: the four-bucket voucher ledger and its conservation."""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_sponsor_ledger_conserved,
    assert_voucher_value_conserved,
    deposit,
    make_learner_headers,
    make_sponsor_headers,
    new_account,
    new_learner,
    pay_payload,
    pay_with_voucher,
    read_account,
    read_registration,
    read_voucher,
    register_learner,
    reset_clock,
    set_clock,
    setup_assigned_voucher,
    setup_open_offering,
    setup_voucher_funded_enrollment,
    validate_error,
    validate_paginated,
    validate_success,
)


def _seated_voucher_scene():
    """An OPEN section, a learner with a PENDING registration, and an assigned voucher."""
    scene = setup_open_offering()
    learner = new_learner(email="ada@x.com", full_name="Ada Ito")
    money = setup_assigned_voucher(learner["id"], 200000, 200000)
    registration = register_learner(scene["offering_id"], learner["id"], scene["version"])
    scene.update(money)
    scene["learner_id"] = learner["id"]
    scene["registration_id"] = registration["id"]
    return scene


class TestVoucherPaymentDependsOnSponsorStanding:
    """The registration's money axis depends on an account two hops away."""

    def test_suspended_sponsor_makes_an_otherwise_good_voucher_unusable(self, api):
        """PRD 3.5: "Four usability conditions must all hold: the voucher's `status`
        must be `ASSIGNED` or `PARTIALLY_REDEEMED`, its `assigned_learner_id` must equal
        the registration's `learner_id`, the logical clock must be strictly earlier than
        its `expires_at`, and its sponsor account's `status` must be `ACTIVE`. Any
        failure yields `ERR_VOUCHER_NOT_USABLE` (HTTP 422)."
        PRD 3.4: "While an account is `SUSPENDED`, none of its vouchers may be issued,
        assigned or redeemed — a redemption attempt is refused with
        `ERR_VOUCHER_NOT_USABLE` — but value already committed against registrations is
        left entirely untouched."

        Design: Difficulty/cross_entity_state_dependency/voucher_payment_depends_on_sponsor_account_still_active
        """
        reset_clock()
        scene = _seated_voucher_scene()
        suspended = validate_success(
            api.suspend_corporate_account(scene["account_id"], ADMIN)
        )
        assert suspended["status"] == "SUSPENDED"

        validate_error(
            api.pay_registration(
                scene["registration_id"],
                pay_payload("VOUCHER", scene["voucher_id"]),
                make_learner_headers(scene["learner_id"]),
            ),
            ApiErrorId.ERR_VOUCHER_NOT_USABLE,
            422,
        )

    def test_the_refused_redemption_leaves_registration_voucher_and_ledger_intact(self, api):
        """PRD 3.5: "On success the registration's `voucher_id` is set from the payload,
        its `payment_status` moves `UNPAID → VOUCHER_COMMITTED`, and `amount_paid_cents`
        is set to `total_due_cents`."
        PRD 3.4: "While an account is `SUSPENDED`, none of its vouchers may be issued,
        assigned or redeemed — a redemption attempt is refused with
        `ERR_VOUCHER_NOT_USABLE` — but value already committed against registrations is
        left entirely untouched."

        Design: Difficulty/cross_entity_state_dependency/voucher_payment_depends_on_sponsor_account_still_active
        """
        reset_clock()
        scene = _seated_voucher_scene()
        api.suspend_corporate_account(scene["account_id"], ADMIN)
        api.pay_registration(
            scene["registration_id"],
            pay_payload("VOUCHER", scene["voucher_id"]),
            make_learner_headers(scene["learner_id"]),
        )

        registration = read_registration(scene["registration_id"])
        assert registration["payment_status"] == "UNPAID"
        assert registration["enrollment_status"] == "PENDING"

        voucher = read_voucher(scene["voucher_id"], scene["account_id"])
        assert voucher["remaining_cents"] == 200000
        assert voucher["committed_cents"] == 0
        assert_voucher_value_conserved(voucher)

        account = read_account(scene["account_id"])
        assert account["committed_cents"] == 0
        assert_sponsor_ledger_conserved(account)


class TestSponsorLedgerConservation:
    """funded_cents stays whole across commit, release and void."""

    def test_committing_voucher_value_moves_it_between_buckets_only(self, api):
        """PRD 2.10: "For a sponsor account, `funded_cents` always equals
        `available_cents` plus `unallocated_voucher_cents` plus `committed_cents` plus
        `consumed_cents`."
        PRD 3.5: "In parallel the sponsor account's `unallocated_voucher_cents`
        decreases by `total_due_cents` and its `committed_cents` increases by the same
        amount."

        Design: Difficulty/compensating_invariant/voucher_commit_release_and_void_conserve_sponsor_ledger_identity
        """
        reset_clock()
        scene = setup_voucher_funded_enrollment()
        pay_with_voucher(scene["registration_id"], scene["voucher_id"], scene["learner_id"])

        account = read_account(scene["account_id"])
        assert account["funded_cents"] == 500000
        assert account["available_cents"] == 300000
        assert account["unallocated_voucher_cents"] == 137600
        assert account["committed_cents"] == 62400
        assert account["consumed_cents"] == 0
        assert_sponsor_ledger_conserved(account)

    def test_release_then_void_returns_every_cent_to_available(self, api):
        """PRD 2.10: "Committing voucher value against a registration and later
        releasing it — through a settled refund, or through the section-cancellation
        cascade — is a forward-and-compensating pair that must leave `funded_cents`,
        `available_cents` and the identity above exactly as they were before the
        commitment."
        PRD 3.4: "Voiding sets the voucher's `status` to `VOIDED` and its
        `remaining_cents` to 0, returns `face_value_cents` to the sponsor's
        `available_cents`, removes the same amount from `unallocated_voucher_cents`, and
        increments both the voucher's `version` and the account's `version` by 1 each."

        Design: Difficulty/compensating_invariant/voucher_commit_release_and_void_conserve_sponsor_ledger_identity
        """
        reset_clock()
        scene = setup_voucher_funded_enrollment()
        pay_with_voucher(scene["registration_id"], scene["voucher_id"], scene["learner_id"])
        set_clock("2026-09-05T00:00:00Z")
        api.census_offering(scene["offering_id"], ADMIN)

        released = read_account(scene["account_id"])
        assert released["available_cents"] == 300000
        assert released["unallocated_voucher_cents"] == 200000
        assert released["committed_cents"] == 0
        assert released["consumed_cents"] == 0
        assert_sponsor_ledger_conserved(released)

        voided = validate_success(
            api.void_voucher(
                scene["voucher_id"], make_sponsor_headers(scene["account_id"])
            )
        )
        assert voided["status"] == "VOIDED"

        final = read_account(scene["account_id"])
        assert final["funded_cents"] == 500000
        assert final["available_cents"] == 500000
        assert final["unallocated_voucher_cents"] == 0
        assert final["committed_cents"] == 0
        assert final["consumed_cents"] == 0
        assert_sponsor_ledger_conserved(final)


def test_voucher_issue_beyond_available_budget_returns_402(api):
    """PRD 3.4: "The account's `available_cents` must be at least `face_value_cents`,
    or the issue is refused with `ERR_ACCOUNT_FUNDS_INSUFFICIENT` (HTTP 402)."
    PRD 3.4: "Either the `ProgramAdmin` or the sponsor itself posts an `amount_cents`
    figure, which is added to `funded_cents` and to `available_cents` and increments the
    account's `version` by 1."

    Design: Corner/validations/sponsor_budget_insufficient_on_voucher_issue_returns_402
    """
    reset_clock()
    account = new_account()
    funded = deposit(account["id"], 1000)

    validate_error(
        api.issue_voucher(
            account["id"],
            {
                "face_value_cents": 200000,
                "expires_at": "2027-06-30T00:00:00Z",
                "expected_corporate_account_version": funded["version"],
            },
            make_sponsor_headers(account["id"]),
        ),
        ApiErrorId.ERR_ACCOUNT_FUNDS_INSUFFICIENT,
        402,
    )
    after = read_account(account["id"])
    assert after["funded_cents"] == 1000
    assert after["available_cents"] == 1000
    assert after["unallocated_voucher_cents"] == 0
    assert_sponsor_ledger_conserved(after)
    _, meta = validate_paginated(
        api.list_vouchers(ADMIN, params={"corporate_account_id": account["id"]})
    )
    assert meta["total_count"] == 0


def test_stale_account_version_on_voucher_issue_returns_412(api):
    """PRD 2.6: "Issuing a voucher against a corporate account requires the request to
    carry `expected_corporate_account_version`, a non-optional input field holding the
    `version` of the target `CorporateAccount` as the client last observed it."
    PRD 2.6: "A mismatch is refused with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_account_version_on_voucher_issue_returns_412
    """
    reset_clock()
    account = new_account()
    funded = deposit(account["id"], 500000)
    stale_version = funded["version"]

    validate_success(
        api.issue_voucher(
            account["id"],
            {
                "face_value_cents": 200000,
                "expires_at": "2027-06-30T00:00:00Z",
                "expected_corporate_account_version": stale_version,
            },
            make_sponsor_headers(account["id"]),
        ),
        201,
    )
    validate_error(
        api.issue_voucher(
            account["id"],
            {
                "face_value_cents": 100000,
                "expires_at": "2027-06-30T00:00:00Z",
                "expected_corporate_account_version": stale_version,
            },
            make_sponsor_headers(account["id"]),
        ),
        ApiErrorId.ERR_STALE_VERSION,
        412,
    )
    _, meta = validate_paginated(
        api.list_vouchers(ADMIN, params={"corporate_account_id": account["id"]})
    )
    assert meta["total_count"] == 1
    after = read_account(account["id"])
    assert after["funded_cents"] == 500000
    assert after["available_cents"] == 300000
    assert after["unallocated_voucher_cents"] == 200000


def test_reinstating_the_sponsor_restores_voucher_redemption(api):
    """PRD 3.4: "A `ProgramAdmin` suspends an `ACTIVE` account, moving it `ACTIVE →
    SUSPENDED` and incrementing its `version` by 1, and reinstates a `SUSPENDED`
    account, moving it `SUSPENDED → ACTIVE` and again incrementing `version` by 1; the
    cycle may be repeated indefinitely and the account has no terminal state."
    PRD 3.5: "The voucher's `remaining_cents` decreases by `total_due_cents` while its
    `committed_cents` increases by the same amount, and its `status` is re-derived:
    `PARTIALLY_REDEEMED` when some `remaining_cents` survives, `EXHAUSTED` when the
    commitment consumed the last of it."

    Design: Corner/state_machines/sponsor_account_reinstate_restores_voucher_redemption
    """
    reset_clock()
    scene = _seated_voucher_scene()
    api.suspend_corporate_account(scene["account_id"], ADMIN)

    validate_error(
        api.pay_registration(
            scene["registration_id"],
            pay_payload("VOUCHER", scene["voucher_id"]),
            make_learner_headers(scene["learner_id"]),
        ),
        ApiErrorId.ERR_VOUCHER_NOT_USABLE,
        422,
    )
    reinstated = validate_success(
        api.reinstate_corporate_account(scene["account_id"], ADMIN)
    )
    assert reinstated["status"] == "ACTIVE"

    paid = validate_success(
        api.pay_registration(
            scene["registration_id"],
            pay_payload("VOUCHER", scene["voucher_id"]),
            make_learner_headers(scene["learner_id"]),
        )
    )
    assert paid["payment_status"] == "VOUCHER_COMMITTED"
    assert paid["enrollment_status"] == "ENROLLED"

    voucher = read_voucher(scene["voucher_id"], scene["account_id"])
    assert voucher["remaining_cents"] == 137600
    assert voucher["committed_cents"] == 62400
    assert voucher["status"] == "PARTIALLY_REDEEMED"

    account = read_account(scene["account_id"])
    assert account["committed_cents"] == 62400
    assert account["unallocated_voucher_cents"] == 137600
    assert_sponsor_ledger_conserved(account)


def test_voucher_status_is_rederived_across_full_redemption_and_release(api):
    """PRD 3.5: "The voucher's `remaining_cents` decreases by `total_due_cents` while
    its `committed_cents` increases by the same amount, and its `status` is re-derived:
    `PARTIALLY_REDEEMED` when some `remaining_cents` survives, `EXHAUSTED` when the
    commitment consumed the last of it."
    PRD 3.6: "A voucher returns all the way to `ASSIGNED` — from either `EXHAUSTED` or
    `PARTIALLY_REDEEMED` — when the release leaves both `committed_cents` and
    `consumed_cents` at exactly zero; in the `EXHAUSTED` case this coincides with
    `remaining_cents` having been restored to the full `face_value_cents`."

    Design: Corner/cross_cutting_complexity_layers/voucher_status_rederived_across_full_redemption_and_release
    """
    reset_clock()
    scene = setup_voucher_funded_enrollment(
        funded_cents=62400, face_value_cents=62400
    )
    pay_with_voucher(scene["registration_id"], scene["voucher_id"], scene["learner_id"])

    committed = read_voucher(scene["voucher_id"], scene["account_id"])
    assert committed["status"] == "EXHAUSTED"
    assert committed["remaining_cents"] == 0
    assert committed["committed_cents"] == 62400
    assert_voucher_value_conserved(committed)

    set_clock("2026-09-05T00:00:00Z")
    cancelled = validate_success(api.census_offering(scene["offering_id"], ADMIN))
    assert cancelled["status"] == "CANCELLED"

    released = read_voucher(scene["voucher_id"], scene["account_id"])
    assert released["status"] == "ASSIGNED"
    assert released["remaining_cents"] == 62400
    assert released["committed_cents"] == 0
    assert_voucher_value_conserved(released)

    account = read_account(scene["account_id"])
    assert account["funded_cents"] == 62400
    assert account["available_cents"] == 0
    assert account["unallocated_voucher_cents"] == 62400
    assert_sponsor_ledger_conserved(account)
