"""Filing a purchase request: the parent lookups, the version guard, the check ladder."""

from test_helpers import (
    BALANCE_AFTER_TWO_QUARTERS,
    ER1,
    MISSING_ID,
    PA,
    Q1_NET_CENTS,
    ApiErrorId,
    account_version,
    create_field_trips_category,
    create_purchase_request_payload,
    decide_purchase_request,
    file_purchase_request,
    make_guardian_headers,
    read_account,
    read_provider,
    read_purchase_request,
    run_disbursement,
    setup_approved_provider,
    setup_approved_purchase_request,
    setup_catalog,
    setup_funded_account,
    setup_purchase_environment,
    suspend_account,
    validate_error,
    validate_paginated,
    validate_success,
)

HELD_WINDOW_START = "2026-10-01T00:00:00Z"
HELD_WINDOW_END = "2026-11-01T00:00:00Z"


def _tutoring_environment(quarters=1):
    """A funded account, the catalogue, and a vendor admitted for TUTORING only."""
    return setup_purchase_environment(
        quarters=quarters, provider_flags=[], provider_codes=("TUTORING",)
    )


def _account_purchase_requests(api, account_id):
    """The account's purchase requests through the reverse lookup."""
    return validate_paginated(
        api.list_purchase_requests(PA, params={"account_id": account_id})
    )


class TestPurchaseRequestParentResolution:
    """The path identifier is resolved before anything in the body is examined."""

    def test_filing_under_an_unknown_account_reports_account_not_found(self, api):
        """PRD §2.8: "The account named by the path or by `account_id` exists —
        `ERR_ACCOUNT_NOT_FOUND`, on every account path, on misuse-case creation and on
        renewal-review filing."

        PRD §2.8: "Checks are evaluated strictly in the following order, and the first one
        that fails ends the request."

        Design: Corner/entities/purchase_request_under_nonexistent_account_returns_account_not_found
        """
        catalog = setup_catalog()
        vendor = setup_approved_provider(flags=[], codes=["MATERIALS"])
        assert vendor.provider["status"] == "APPROVED", (
            f"the vendor named in the body is impeccable, got {vendor.provider['status']!r}"
        )

        response = api.create_purchase_request(
            MISSING_ID,
            create_purchase_request_payload(
                vendor.provider_id,
                catalog.materials["id"],
                1,
                amount_cents=10000,
            ),
            make_guardian_headers(MISSING_ID),
        )
        validate_error(response, ApiErrorId.ACCOUNT_NOT_FOUND.value, 404)

        _, meta = validate_paginated(
            api.list_purchase_requests(PA, params={"provider_id": vendor.provider_id})
        )
        assert meta["total_count"] == 0, (
            f"no request was created against the vendor, got {meta['total_count']}"
        )


class TestAccountVersionGuard:
    """The optimistic-concurrency field is the only thing that catches a stale view."""

    def test_a_stale_expected_version_is_refused_and_the_fresh_one_succeeds(self, api):
        """PRD §2.7: "If that value does not equal the account's current `version` at the
        moment the request is processed, the creation is rejected with
        `ERR_STALE_ACCOUNT_VERSION` and HTTP status 412. Two purchase requests on one
        account are perfectly legal, so nothing about the account's state would signal a
        problem"

        PRD §2.7: "A successful creation itself advances the account's `version` by 1, so a
        client filing two requests back to back must re-read between them."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_account_version_on_purchase_request_is_rejected
        """
        env = _tutoring_environment(quarters=1)
        stale_version = account_version(env.account_id)

        run_disbursement(env.program_year_id, 2)
        moved_version = account_version(env.account_id)
        assert moved_version > stale_version, (
            "the quarter-2 credit moved the account past the guardian's read, got "
            f"{moved_version} against {stale_version}"
        )

        refused = api.create_purchase_request(
            env.account_id,
            create_purchase_request_payload(
                env.provider_id, env.tutoring["id"], stale_version, amount_cents=150000
            ),
            env.guardian,
        )
        validate_error(refused, ApiErrorId.STALE_ACCOUNT_VERSION.value, 412)

        _, meta = _account_purchase_requests(api, env.account_id)
        assert meta["total_count"] == 0, (
            f"the refused filing created nothing, got {meta['total_count']}"
        )

        accepted = validate_success(
            api.create_purchase_request(
                env.account_id,
                create_purchase_request_payload(
                    env.provider_id,
                    env.tutoring["id"],
                    moved_version,
                    amount_cents=150000,
                ),
                env.guardian,
            ),
            201,
        )
        assert accepted["approval_status"] == "PENDING_REVIEW", (
            "the retry against the moved version succeeds, got "
            f"{accepted['approval_status']!r}"
        )

        account = read_account(env.account_id)
        assert account["balance_cents"] == BALANCE_AFTER_TWO_QUARTERS, (
            f"the two credits still stand at 458173, got {account['balance_cents']}"
        )
        assert account["encumbered_cents"] == 0, (
            f"and creation places no hold, got {account['encumbered_cents']}"
        )
        assert account["version"] == moved_version + 1, (
            "the accepted creation consumed the guard and bumped the version, got "
            f"{account['version']}"
        )

    def test_the_version_rises_on_the_creation_and_again_on_the_approval(self, api):
        """PRD §3.7: "A successful filing lands at `PENDING_REVIEW` and `UNSETTLED`, and —
        because it consumes the account's version guard — the account's own `version` rises
        by 1 even though no money has moved."

        PRD §3.7: "On success the reviewer's `X-User-ID` is stored as
        `approved_by_user_id`, and the hold is placed: `balance_cents` falls by
        `amount_cents` and `encumbered_cents` rises by the same `amount_cents`. Both the
        request's `version` and the account's `version` rise by 1."

        Design: Corner/cross_cutting_complexity_layers/account_version_increments_on_every_write
        """
        env = _tutoring_environment(quarters=1)
        version_before_filing = account_version(env.account_id)

        request = validate_success(
            api.create_purchase_request(
                env.account_id,
                create_purchase_request_payload(
                    env.provider_id,
                    env.tutoring["id"],
                    version_before_filing,
                    amount_cents=150000,
                ),
                env.guardian,
            ),
            201,
        )
        version_after_filing = account_version(env.account_id)
        assert version_after_filing == version_before_filing + 1, (
            "the filing bumped the account by exactly one, got "
            f"{version_after_filing} against {version_before_filing}"
        )

        decided = decide_purchase_request(request["id"], "APPROVED", headers=ER1)
        assert decided["approval_status"] == "APPROVED", (
            f"the reviewer approves the request, got {decided['approval_status']!r}"
        )
        assert decided["approved_by_user_id"] == ER1["X-User-ID"], (
            f"recording who approved it, got {decided['approved_by_user_id']!r}"
        )

        account = read_account(env.account_id)
        assert account["version"] == version_after_filing + 1, (
            "the approval bumped it again, so a client reusing its pre-filing read cannot "
            f"file a second request, got {account['version']}"
        )
        assert account["balance_cents"] == Q1_NET_CENTS - 150000, (
            f"the hold took the balance to 79088, got {account['balance_cents']}"
        )
        assert account["encumbered_cents"] == 150000, (
            f"and put 150000 under encumbrance, got {account['encumbered_cents']}"
        )


class TestCategoryGates:
    """Three separate category rules that cannot be collapsed into one another."""

    def test_a_single_amount_above_the_annual_cap_is_refused_at_creation(self, api):
        """PRD §3.7: "The new `amount_cents` must not exceed the catalogue entry's
        `per_year_cap_cents` less that committed sum, or the filing is refused with
        `ERR_CATEGORY_CAP_EXCEEDED`."

        Design: Corner/validations/single_request_above_the_category_cap_is_rejected_at_creation
        """
        env = _tutoring_environment(quarters=2)
        before = read_account(env.account_id)
        assert before["balance_cents"] == BALANCE_AFTER_TWO_QUARTERS, (
            f"the account could easily fund the request, got {before['balance_cents']}"
        )
        assert env.tutoring["per_year_cap_cents"] == 200000, (
            f"but the catalogue line caps the year at 200000, got "
            f"{env.tutoring['per_year_cap_cents']}"
        )

        refused = api.create_purchase_request(
            env.account_id,
            create_purchase_request_payload(
                env.provider_id,
                env.tutoring["id"],
                before["version"],
                amount_cents=250000,
            ),
            env.guardian,
        )
        validate_error(refused, ApiErrorId.CATEGORY_CAP_EXCEEDED.value, 422)

        after = read_account(env.account_id)
        assert after["balance_cents"] == BALANCE_AFTER_TWO_QUARTERS, (
            f"the rejected write moved no money, got {after['balance_cents']}"
        )
        assert after["encumbered_cents"] == 0, (
            f"and held nothing, got {after['encumbered_cents']}"
        )
        assert after["version"] == before["version"], (
            f"nor did it consume the version guard, got {after['version']}"
        )
        _, meta = _account_purchase_requests(api, env.account_id)
        assert meta["total_count"] == 0, (
            f"and created no row, got {meta['total_count']}"
        )

    def test_a_non_allowable_category_is_refused_even_when_authorized(self, api):
        """PRD §3.7: "The catalogue entry's `allowable` must be true, or the filing is
        refused with `ERR_EXPENSE_NOT_ALLOWABLE`."

        PRD §2.8: "27. The category is marked `allowable` — `ERR_EXPENSE_NOT_ALLOWABLE`, on
        purchase-request creation."

        Design: Corner/validations/non_allowable_expense_category_is_rejected
        """
        env = setup_funded_account(quarters=1)
        env.update(setup_catalog())
        env["field_trips"] = create_field_trips_category()
        env.update(setup_approved_provider(flags=[], codes=["TUTORING", "FIELD_TRIPS"]))

        assert env.field_trips["allowable"] is False, (
            f"the catalogue line is not allowable, got {env.field_trips['allowable']!r}"
        )
        provider = read_provider(env.provider_id)
        assert "FIELD_TRIPS" in provider["authorized_category_codes"], (
            "yet the vendor is explicitly authorized for that very code, got "
            f"{provider['authorized_category_codes']!r}"
        )

        before = read_account(env.account_id)
        refused = api.create_purchase_request(
            env.account_id,
            create_purchase_request_payload(
                env.provider_id,
                env.field_trips["id"],
                before["version"],
                amount_cents=50000,
                service_end_at="2026-10-15T00:00:00Z",
            ),
            env.guardian,
        )
        error = validate_error(refused, ApiErrorId.EXPENSE_NOT_ALLOWABLE.value, 422)
        assert error["error_id"] != ApiErrorId.CATEGORY_NOT_AUTHORIZED.value, (
            "the authorization check passed, so the allowability check is what fired, got "
            f"{error['error_id']!r}"
        )

        after = read_account(env.account_id)
        assert after["balance_cents"] == Q1_NET_CENTS, (
            f"no money moved, got {after['balance_cents']}"
        )
        assert after["encumbered_cents"] == 0, (
            f"and nothing was held, got {after['encumbered_cents']}"
        )

    def test_a_category_outside_the_vendors_authorization_is_refused(self, api):
        """PRD §3.7: "The catalogue entry's `code` must appear in the provider's pinned
        `authorized_category_codes`, or the filing is refused with
        `ERR_CATEGORY_NOT_AUTHORIZED`."

        PRD §3.6: "The supplied `authorized_category_codes` are pinned onto the provider,
        fixing for good the catalogue lines it may bill, and its `version` rises by 1."

        Design: Corner/validations/category_outside_provider_authorization_is_rejected
        """
        env = _tutoring_environment(quarters=1)
        assert env.materials["allowable"] is True, (
            f"MATERIALS is a perfectly allowable line, got {env.materials['allowable']!r}"
        )
        provider = read_provider(env.provider_id)
        assert provider["authorized_category_codes"] == ["TUTORING"], (
            f"but this vendor was admitted for TUTORING only, got "
            f"{provider['authorized_category_codes']!r}"
        )
        assert provider["status"] == "APPROVED", (
            f"and it is otherwise APPROVED, got {provider['status']!r}"
        )

        before = read_account(env.account_id)
        refused = api.create_purchase_request(
            env.account_id,
            create_purchase_request_payload(
                env.provider_id,
                env.materials["id"],
                before["version"],
                amount_cents=50000,
                service_end_at="2026-10-15T00:00:00Z",
            ),
            env.guardian,
        )
        validate_error(refused, ApiErrorId.CATEGORY_NOT_AUTHORIZED.value, 422)

        _, meta = _account_purchase_requests(api, env.account_id)
        assert meta["total_count"] == 0, (
            f"no request was created, got {meta['total_count']}"
        )

    def test_reimbursement_on_a_preapproval_only_category_is_refused(self, api):
        """PRD §3.7: "A `REIMBURSEMENT` flow is only accepted when the entry's
        `requires_preapproval` is false; otherwise the filing is refused with
        `ERR_PREAPPROVAL_REQUIRED`."

        Design: Corner/validations/reimbursement_flow_on_a_preapproval_only_category_is_rejected
        """
        env = _tutoring_environment(quarters=1)
        assert env.tutoring["requires_preapproval"] is True, (
            "TUTORING demands a decision before the service is rendered, got "
            f"{env.tutoring['requires_preapproval']!r}"
        )

        before = read_account(env.account_id)
        refused = api.create_purchase_request(
            env.account_id,
            create_purchase_request_payload(
                env.provider_id,
                env.tutoring["id"],
                before["version"],
                flow="REIMBURSEMENT",
                amount_cents=100000,
                invoice_reference="INV-7781",
            ),
            env.guardian,
        )
        validate_error(refused, ApiErrorId.PREAPPROVAL_REQUIRED.value, 422)

        after = read_account(env.account_id)
        assert after["balance_cents"] == Q1_NET_CENTS, (
            f"a valid invoice reference does not buy the family a shortcut, got "
            f"{after['balance_cents']}"
        )
        assert after["encumbered_cents"] == 0, (
            f"and nothing was held, got {after['encumbered_cents']}"
        )
        _, meta = _account_purchase_requests(api, env.account_id)
        assert meta["total_count"] == 0, (
            f"no request was created, got {meta['total_count']}"
        )


class TestServiceIntervalGates:
    """The interval must sit inside the term, and the collision rule is conditional."""

    def test_an_interval_running_past_the_term_end_is_refused(self, api):
        """PRD §3.7: "Separately, the interval must lie inside the programme year's
        instructional term: `service_start_at` must be at or after midnight UTC on
        `term_start_date`, `service_end_at` must be at or before 23:59:59 UTC on
        `term_end_date`, and `service_end_at` must be strictly after `service_start_at`. A
        violation is refused with `ERR_SERVICE_PERIOD_OUTSIDE_TERM`."

        Design: Corner/validations/service_period_outside_the_program_term_is_rejected
        """
        env = _tutoring_environment(quarters=1)
        assert env.program_year["term_end_date"] == "2027-06-30", (
            f"the instructional term ends on 2027-06-30, got "
            f"{env.program_year['term_end_date']!r}"
        )

        before = read_account(env.account_id)
        refused = api.create_purchase_request(
            env.account_id,
            create_purchase_request_payload(
                env.provider_id,
                env.tutoring["id"],
                before["version"],
                amount_cents=100000,
                service_start_at="2027-06-01T00:00:00Z",
                service_end_at="2027-08-01T00:00:00Z",
            ),
            env.guardian,
        )
        validate_error(refused, ApiErrorId.SERVICE_PERIOD_OUTSIDE_TERM.value, 422)

        _, meta = _account_purchase_requests(api, env.account_id)
        assert meta["total_count"] == 0, (
            "the interval is refused rather than silently truncated to the term end, got "
            f"{meta['total_count']} rows"
        )
        after = read_account(env.account_id)
        assert after["balance_cents"] == Q1_NET_CENTS, (
            f"and no money moved, got {after['balance_cents']}"
        )
        assert after["encumbered_cents"] == 0, (
            f"nor was anything held, got {after['encumbered_cents']}"
        )

    def test_an_exempt_category_may_reuse_one_identical_window(self, api):
        """PRD §3.7: "Categories that leave `requires_service_period` false are wholly
        exempt and may reuse an identical interval as often as needed."

        Design: Corner/validations/categories_without_service_period_flag_may_reuse_one_window
        """
        env = setup_purchase_environment(
            quarters=1, provider_flags=[], provider_codes=("TUITION",)
        )
        assert env.tuition["requires_service_period"] is False, (
            "TUITION leaves the service-interval rule switched off, got "
            f"{env.tuition['requires_service_period']!r}"
        )

        first = file_purchase_request(
            env.account_id,
            env.student_id,
            env.provider_id,
            env.tuition["id"],
            amount_cents=100000,
        )
        second = validate_success(
            api.create_purchase_request(
                env.account_id,
                create_purchase_request_payload(
                    env.provider_id,
                    env.tuition["id"],
                    account_version(env.account_id),
                    amount_cents=100000,
                ),
                env.guardian,
            ),
            201,
        )
        assert first["id"] != second["id"], (
            f"two distinct requests were created, got {first['id']!r} twice"
        )
        assert first["service_start_at"] == second["service_start_at"], (
            f"over a byte-identical window, got {second['service_start_at']!r}"
        )
        assert first["service_end_at"] == second["service_end_at"], (
            f"on both ends, got {second['service_end_at']!r}"
        )
        for request in (first, second):
            assert request["approval_status"] == "PENDING_REVIEW", (
                f"both sit at PENDING_REVIEW, got {request['approval_status']!r}"
            )

        rows, meta = _account_purchase_requests(api, env.account_id)
        assert meta["total_count"] == 2, (
            f"and both survive as rows, got {meta['total_count']}"
        )
        assert {row["id"] for row in rows} == {first["id"], second["id"]}, (
            f"the two rows are the two filings, got {rows!r}"
        )

        account = read_account(env.account_id)
        assert account["balance_cents"] == Q1_NET_CENTS, (
            f"creation places no hold, got {account['balance_cents']}"
        )
        assert account["encumbered_cents"] == 0, (
            f"so nothing is encumbered, got {account['encumbered_cents']}"
        )


class TestSuspensionPrecedesTheCategoryCap:
    """A request that offends two rules at once reports the earlier one."""

    def test_a_suspended_account_reports_the_suspension_and_not_the_cap(self, api):
        """PRD §2.8: "This matters most in the middle of the ladder: a purchase request
        naming a suspended account, an ineligible provider, and an over-cap amount all at
        once reports the account suspension, because that check sits earlier."

        PRD §2.8: "21. The account whose money would move is `ACTIVE` rather than
        `SUSPENDED` — `ERR_ACCOUNT_SUSPENDED`, on purchase-request creation, on the
        approval-track decision and on settlement."

        Design: Difficulty/priority_pair_validation_conflict/suspended_account_check_precedes_category_cap_check
        """
        env = _tutoring_environment(quarters=1)
        suspended = suspend_account(
            env.account_id, reason="Pending compliance interview."
        )
        assert suspended["status"] == "SUSPENDED", (
            f"the account is suspended, got {suspended['status']!r}"
        )
        assert env.tutoring["per_year_cap_cents"] == 200000, (
            f"the catalogue line caps the year at 200000, got "
            f"{env.tutoring['per_year_cap_cents']}"
        )

        refused = api.create_purchase_request(
            env.account_id,
            create_purchase_request_payload(
                env.provider_id,
                env.tutoring["id"],
                account_version(env.account_id),
                amount_cents=300000,
            ),
            env.guardian,
        )
        error = validate_error(refused, ApiErrorId.ACCOUNT_SUSPENDED.value, 409)
        assert error["error_id"] != ApiErrorId.CATEGORY_CAP_EXCEEDED.value, (
            "the suspension is reported even though the amount also breaks the cap, got "
            f"{error['error_id']!r}"
        )

        account = read_account(env.account_id)
        assert account["balance_cents"] == Q1_NET_CENTS, (
            f"no money moved, got {account['balance_cents']}"
        )
        assert account["encumbered_cents"] == 0, (
            f"nothing was held, got {account['encumbered_cents']}"
        )
        _, meta = _account_purchase_requests(api, env.account_id)
        assert meta["total_count"] == 0, (
            f"and no request row exists, got {meta['total_count']}"
        )

    def test_the_same_over_cap_amount_on_an_active_account_reports_the_cap(self, api):
        """PRD §2.8: "35. The category's annual cap is not exceeded —
        `ERR_CATEGORY_CAP_EXCEEDED`, on purchase-request creation and on an approval-track
        decision of `APPROVED`."

        PRD §3.7: "The new `amount_cents` must not exceed the catalogue entry's
        `per_year_cap_cents` less that committed sum, or the filing is refused with
        `ERR_CATEGORY_CAP_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/suspended_account_check_precedes_category_cap_check
        """
        env = _tutoring_environment(quarters=1)
        account = read_account(env.account_id)
        assert account["status"] == "ACTIVE", (
            f"this time the account is ACTIVE, got {account['status']!r}"
        )

        refused = api.create_purchase_request(
            env.account_id,
            create_purchase_request_payload(
                env.provider_id,
                env.tutoring["id"],
                account["version"],
                amount_cents=300000,
            ),
            env.guardian,
        )
        error = validate_error(refused, ApiErrorId.CATEGORY_CAP_EXCEEDED.value, 422)
        assert error["error_id"] != ApiErrorId.ACCOUNT_SUSPENDED.value, (
            "with the earlier check satisfied the cap is what fires, proving the "
            f"suspension code was not a blanket refusal, got {error['error_id']!r}"
        )

        after = read_account(env.account_id)
        assert after["version"] == account["version"], (
            f"the refused filing consumed no version guard, got {after['version']}"
        )
        _, meta = _account_purchase_requests(api, env.account_id)
        assert meta["total_count"] == 0, (
            f"and created no row, got {meta['total_count']}"
        )


class TestDuplicateWindowPrecedesTheCategoryCap:
    """A colliding interval is reported before the ceiling that the same amount breaks."""

    def test_a_colliding_interval_reports_the_collision_and_not_the_cap(self, api):
        """PRD §2.8: "30. No colliding service interval —
        `ERR_DUPLICATE_SERVICE_PERIOD`, on purchase-request creation."

        PRD §3.7: "When the catalogue entry's `requires_service_period` is true, no other
        purchase request for the same `account_id` and the same `expense_category_id` whose
        `approval_status` is `PENDING_REVIEW` or `APPROVED` may cover an intersecting
        interval"

        Design: Difficulty/priority_pair_validation_conflict/duplicate_service_period_check_precedes_category_cap_check
        """
        env = _tutoring_environment(quarters=1)
        env = setup_approved_purchase_request(
            env, category_key="tutoring", amount_cents=150000
        )
        held = read_purchase_request(env.purchase_request_id)
        assert held["approval_status"] == "APPROVED", (
            f"the first request holds an approval, got {held['approval_status']!r}"
        )
        assert held["service_start_at"].startswith("2026-10-01"), (
            f"over the window opening on 2026-10-01, got {held['service_start_at']!r}"
        )
        before = read_account(env.account_id)
        assert before["balance_cents"] == Q1_NET_CENTS - 150000, (
            f"the hold took the balance to 79088, got {before['balance_cents']}"
        )
        assert before["encumbered_cents"] == 150000, (
            f"holding 150000, got {before['encumbered_cents']}"
        )

        refused = api.create_purchase_request(
            env.account_id,
            create_purchase_request_payload(
                env.provider_id,
                env.tutoring["id"],
                before["version"],
                amount_cents=100000,
                service_start_at="2026-10-15T00:00:00Z",
                service_end_at="2026-11-15T00:00:00Z",
            ),
            env.guardian,
        )
        error = validate_error(refused, ApiErrorId.DUPLICATE_SERVICE_PERIOD.value, 409)
        assert error["error_id"] != ApiErrorId.CATEGORY_CAP_EXCEEDED.value, (
            "the collision is reported even though 150000 already approved plus 100000 "
            f"breaks the 200000 ceiling, got {error['error_id']!r}"
        )

        after = read_account(env.account_id)
        assert after["balance_cents"] == before["balance_cents"], (
            f"the refused filing moved no money, got {after['balance_cents']}"
        )
        assert after["encumbered_cents"] == before["encumbered_cents"], (
            f"and changed no hold, got {after['encumbered_cents']}"
        )
        _, meta = _account_purchase_requests(api, env.account_id)
        assert meta["total_count"] == 1, (
            f"only the first request exists, got {meta['total_count']}"
        )

    def test_a_clear_interval_over_the_ceiling_reports_the_cap(self, api):
        """PRD §3.7: "The account's already-committed spend in that category is the sum of
        `amount_cents` across the account's purchase requests for the same category whose
        `approval_status` is `APPROVED`."

        PRD §3.7: "intervals are treated as half-open, including their start instant and
        excluding their end instant, so two requests that merely touch end-to-start do not
        collide."

        Design: Difficulty/priority_pair_validation_conflict/duplicate_service_period_check_precedes_category_cap_check
        """
        env = _tutoring_environment(quarters=1)
        env = setup_approved_purchase_request(
            env, category_key="tutoring", amount_cents=150000
        )
        before = read_account(env.account_id)

        refused = api.create_purchase_request(
            env.account_id,
            create_purchase_request_payload(
                env.provider_id,
                env.tutoring["id"],
                before["version"],
                amount_cents=100000,
                service_start_at=HELD_WINDOW_END,
                service_end_at="2026-12-01T00:00:00Z",
            ),
            env.guardian,
        )
        error = validate_error(refused, ApiErrorId.CATEGORY_CAP_EXCEEDED.value, 422)
        assert error["error_id"] != ApiErrorId.DUPLICATE_SERVICE_PERIOD.value, (
            "the interval starts exactly where the held one ends, so the temporal check "
            f"passes and the ceiling is what fires, got {error['error_id']!r}"
        )

        _, meta = _account_purchase_requests(api, env.account_id)
        assert meta["total_count"] == 1, (
            f"still only the approved request exists, got {meta['total_count']}"
        )
        after = read_account(env.account_id)
        assert after["encumbered_cents"] == 150000, (
            f"and the single hold is untouched, got {after['encumbered_cents']}"
        )


class TestHalfOpenServiceWindows:
    """Touching end-to-start is legal; any shared instant is not."""

    def test_a_window_starting_at_the_held_end_is_accepted_while_a_nested_one_collides(
        self, api
    ):
        """PRD §3.7: "intervals are treated as half-open, including their start instant and
        excluding their end instant, so two requests that merely touch end-to-start do not
        collide. A collision is refused with `ERR_DUPLICATE_SERVICE_PERIOD`."

        Design: Difficulty/resource_temporal_overlap/adjacent_service_windows_coexist_while_overlapping_ones_collide
        """
        env = _tutoring_environment(quarters=1)
        env = setup_approved_purchase_request(
            env, category_key="tutoring", amount_cents=150000
        )
        assert env.tutoring["requires_service_period"] is True, (
            "TUTORING switches the collision rule on, got "
            f"{env.tutoring['requires_service_period']!r}"
        )

        adjacent = validate_success(
            api.create_purchase_request(
                env.account_id,
                create_purchase_request_payload(
                    env.provider_id,
                    env.tutoring["id"],
                    account_version(env.account_id),
                    amount_cents=40000,
                    service_start_at=HELD_WINDOW_END,
                    service_end_at="2026-12-01T00:00:00Z",
                ),
                env.guardian,
            ),
            201,
        )
        assert adjacent["service_start_at"].startswith("2026-11-01"), (
            "the accepted window opens on the very instant the held one closes, got "
            f"{adjacent['service_start_at']!r}"
        )
        assert adjacent["approval_status"] == "PENDING_REVIEW", (
            f"and it lands at PENDING_REVIEW, got {adjacent['approval_status']!r}"
        )

        nested = api.create_purchase_request(
            env.account_id,
            create_purchase_request_payload(
                env.provider_id,
                env.tutoring["id"],
                account_version(env.account_id),
                amount_cents=10000,
                service_start_at="2026-10-15T00:00:00Z",
                service_end_at="2026-10-20T00:00:00Z",
            ),
            env.guardian,
        )
        validate_error(nested, ApiErrorId.DUPLICATE_SERVICE_PERIOD.value, 409)

        account = read_account(env.account_id)
        assert account["balance_cents"] == Q1_NET_CENTS - 150000, (
            f"the balance still reflects the single hold, got {account['balance_cents']}"
        )
        assert account["encumbered_cents"] == 150000, (
            f"and nothing else is encumbered, got {account['encumbered_cents']}"
        )
        rows, meta = _account_purchase_requests(api, env.account_id)
        assert meta["total_count"] == 2, (
            f"the adjacent filing survives and the nested one never existed, got "
            f"{meta['total_count']}"
        )
        assert {row["id"] for row in rows} == {env.purchase_request_id, adjacent["id"]}, (
            f"the two rows are the held request and the adjacent one, got {rows!r}"
        )

    def test_a_window_ending_at_the_held_start_is_accepted_while_an_overlap_collides(
        self, api
    ):
        """PRD §3.7: "no other purchase request for the same `account_id` and the same
        `expense_category_id` whose `approval_status` is `PENDING_REVIEW` or `APPROVED` may
        cover an intersecting interval; intervals are treated as half-open, including their
        start instant and excluding their end instant, so two requests that merely touch
        end-to-start do not collide."

        Design: Difficulty/resource_temporal_overlap/adjacent_service_windows_coexist_while_overlapping_ones_collide
        """
        env = _tutoring_environment(quarters=1)
        env = setup_approved_purchase_request(
            env, category_key="tutoring", amount_cents=150000
        )
        held = read_purchase_request(env.purchase_request_id)
        assert held["service_start_at"].startswith("2026-10-01"), (
            f"the held window opens on 2026-10-01, got {held['service_start_at']!r}"
        )

        earlier = validate_success(
            api.create_purchase_request(
                env.account_id,
                create_purchase_request_payload(
                    env.provider_id,
                    env.tutoring["id"],
                    account_version(env.account_id),
                    amount_cents=40000,
                    service_start_at="2026-09-15T00:00:00Z",
                    service_end_at=HELD_WINDOW_START,
                ),
                env.guardian,
            ),
            201,
        )
        assert earlier["service_end_at"].startswith("2026-10-01"), (
            "the accepted window closes on the instant the held one opens, and that "
            f"instant belongs to the held request alone, got {earlier['service_end_at']!r}"
        )

        straddling = api.create_purchase_request(
            env.account_id,
            create_purchase_request_payload(
                env.provider_id,
                env.tutoring["id"],
                account_version(env.account_id),
                amount_cents=10000,
                service_start_at="2026-09-20T00:00:00Z",
                service_end_at="2026-10-15T00:00:00Z",
            ),
            env.guardian,
        )
        validate_error(straddling, ApiErrorId.DUPLICATE_SERVICE_PERIOD.value, 409)

        rows, meta = _account_purchase_requests(api, env.account_id)
        assert meta["total_count"] == 2, (
            f"one hold and one adjacent filing stand, got {meta['total_count']}"
        )
        assert {row["approval_status"] for row in rows} == {
            "APPROVED",
            "PENDING_REVIEW",
        }, f"in their respective approval states, got {rows!r}"
        account = read_account(env.account_id)
        assert account["encumbered_cents"] == 150000, (
            "and only the approved request holds money, got "
            f"{account['encumbered_cents']}"
        )
