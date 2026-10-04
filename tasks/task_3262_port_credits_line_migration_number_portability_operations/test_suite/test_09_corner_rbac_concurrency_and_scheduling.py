"""Corner coverage: role grants, optimistic concurrency and scheduled actions."""
from test_helpers import (
    ADMIN,
    TEST_USERS,
    activate_promo_schedule,
    advance_clock,
    api_client,
    assert_subscriber_line,
    check_migration_eligibility,
    create_account,
    create_activated_line,
    create_line_addition,
    create_migration_request,
    create_promo_schedule,
    get_account,
    get_line,
    get_migration_request,
    get_promo_schedule,
    make_customer_headers,
    setup_pending_port_request,
)

CARE = TEST_USERS["customer_service_headers"]


class TestRoleGrants:
    def test_a_customer_cannot_submit_a_port_request(self, api):
        """PRD §2.1: "A caller that is properly authenticated but attempts an operation
        its role is not permitted to perform is rejected with `ERR_UNAUTHORIZED` and an
        HTTP status of 403; every endpoint below lists the roles permitted for it, and any
        role not listed is refused this way."

        Design: Corner/rbac/customer_cannot_submit_a_port_request
        """
        account, _line, request = setup_pending_port_request("4155551301")
        assert request["request_state"] == "PENDING"
        response = api_client.submit_port_request(
            request["id"],
            {"transfer_pin": request["transfer_pin"],
             "account_number_at_losing_carrier": request[
                 "account_number_at_losing_carrier"]},
            make_customer_headers(account["id"]),
        )

        assert response.status_code == 403
        assert response.json()["data"]["error_id"] == "ERR_UNAUTHORIZED"

    def test_a_customer_cannot_underwrite_a_line_addition(self, api):
        """PRD §2.1: "`CreditAnalyst` alone underwrites line-addition requests."

        Design: Corner/rbac/customer_service_cannot_underwrite_a_line_addition
        """
        account = create_account(payment_history_score=850, existing_deposit_cents=50000)
        request = create_line_addition(account["id"], 1)

        response = api_client.review_line_addition_request(
            request["id"], {"decision": "APPROVE"}, CARE
        )

        assert response.status_code == 403
        assert response.json()["data"]["error_id"] == "ERR_UNAUTHORIZED"

    def test_the_refused_review_leaves_the_request_submitted(self, api):
        """PRD §2.9: "Authentication is checked before authorization, and both are checked
        before any resource is looked up."
        PRD §3.6: "A request is created in `request_state` `SUBMITTED` with `submitted_at`
        stamped"

        Design: Corner/rbac/customer_service_cannot_underwrite_a_line_addition
        """
        account = create_account(payment_history_score=850, existing_deposit_cents=50000)
        request = create_line_addition(account["id"], 1)
        api_client.review_line_addition_request(
            request["id"], {"decision": "APPROVE"}, CARE
        )

        listed = api_client.list_account_line_addition_requests(account["id"], CARE)
        assert listed.json()["data"][0]["request_state"] == "SUBMITTED"


class TestPromoCreateOptimisticConcurrency:
    def test_a_second_create_with_the_stale_version_is_refused(self, api):
        """PRD §2.7: "The request is rejected when the supplied
        `expected_subscriber_line_version` does not equal the subscriber line's current
        `version`, and the rejection carries `ERR_STALE_SUBSCRIBER_LINE_VERSION` with an
        HTTP status of 412."

        Design: Corner/cross_cutting_complexity_layers/stale_subscriber_line_version_blocks_promo_create
        """
        account = create_account()
        line = create_activated_line(account["id"], "4155551502", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        observed_version = get_line(line["id"])["version"]

        create_promo_schedule(
            line, window_start="2026-09-02T00:00:00Z",
            expected_subscriber_line_version=observed_version,
        )
        response = api_client.create_promo_schedule(
            {
                "subscriber_line_id": line["id"],
                "promo_code": "SWITCH20",
                "monthly_credit_cents": 1000,
                "installment_months": 12,
                "retention_requirement_cycles": 12,
                "window_start": "2026-11-01T00:00:00Z",
                "expected_subscriber_line_version": observed_version,
            },
            CARE,
        )

        assert response.status_code == 412
        assert response.json()["data"]["error_id"] == "ERR_STALE_SUBSCRIBER_LINE_VERSION"

    def test_creating_the_schedule_increments_the_line_version(self, api):
        """PRD §3.4: "creating it increments the attached line's `version` by one — which
        is why this operation is one of the three that require the client's
        `expected_subscriber_line_version` as described in §2.7."

        Design: Corner/cross_cutting_complexity_layers/stale_subscriber_line_version_blocks_promo_create
        """
        account = create_account()
        line = create_activated_line(account["id"], "4155551503", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        before = get_line(line["id"])["version"]

        create_promo_schedule(line, window_start="2026-09-02T00:00:00Z")

        assert get_line(line["id"])["version"] == before + 1
        assert get_account(account["id"])["promo_credited_cents"] == 32000

    def test_the_refused_create_leaves_only_the_first_schedule_credited(self, api):
        """PRD §2.7: "a new promotional schedule supersedes the line's prior promotional
        posture"
        PRD §3.4: "the account's `promo_credited_cents` is incremented by the
        `provisional_total_cents` of the new schedule"

        Design: Corner/cross_cutting_complexity_layers/stale_subscriber_line_version_blocks_promo_create
        """
        account = create_account()
        line = create_activated_line(account["id"], "4155551504", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        observed_version = get_line(line["id"])["version"]
        first = create_promo_schedule(
            line, window_start="2026-09-02T00:00:00Z",
            expected_subscriber_line_version=observed_version,
        )
        api_client.create_promo_schedule(
            {
                "subscriber_line_id": line["id"],
                "promo_code": "SWITCH20",
                "monthly_credit_cents": 1000,
                "installment_months": 12,
                "retention_requirement_cycles": 12,
                "window_start": "2026-11-01T00:00:00Z",
                "expected_subscriber_line_version": observed_version,
            },
            CARE,
        )

        refreshed = get_account(account["id"])
        assert refreshed["promo_credited_cents"] == first["provisional_total_cents"]


class TestScheduledMigrationCutover:
    def test_a_future_cutover_leaves_the_migration_carrying_nothing(self, api):
        """PRD §3.3: "A migration request is born in `migration_state` `DRAFT`, with a null
        `carried_mdn`, `device_balance_cents` 0, `proration_credit_cents` 0 and a null
        `cutover_completed_at`."

        Design: Corner/cross_cutting_complexity_layers/scheduled_migration_cutover_waits_for_the_clock
        """
        account = create_account()
        line = create_activated_line(account["id"], "4155551602", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        migration = create_migration_request(
            line, prepaid_balance_cents=20000,
            requested_cutover_at="2026-10-01T00:00:00Z",
        )
        check_migration_eligibility(migration["id"])

        pending = get_migration_request(migration["id"])

        assert pending["cutover_completed_at"] is None
        assert pending["carried_mdn"] is None
        assert pending["device_balance_cents"] == 0

    def test_the_migration_schedules_without_completing_early(self, api):
        """PRD §3.3: "From `APPROVED`, scheduling is automatic: once
        `requested_cutover_at` is set to an instant at or after the current logical clock
        instant, the request moves on to `CUTOVER_SCHEDULED` with `updated_at` recomputed."

        Design: Corner/cross_cutting_complexity_layers/scheduled_migration_cutover_waits_for_the_clock
        """
        account = create_account()
        line = create_activated_line(account["id"], "4155551603", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        migration = create_migration_request(
            line, prepaid_balance_cents=20000,
            requested_cutover_at="2026-10-01T00:00:00Z",
        )

        scheduled = check_migration_eligibility(migration["id"])

        assert scheduled["migration_state"] == "CUTOVER_SCHEDULED"
        assert scheduled["cutover_completed_at"] is None

    def test_only_the_clock_advance_completes_the_cutover(self, api):
        """PRD §3.3: "Completion is also automatic, and fires when the clock reaches
        `requested_cutover_at` while the request is in `CUTOVER_SCHEDULED`, carrying the
        migration into the terminal `CUTOVER_COMPLETE` state."

        Design: Corner/cross_cutting_complexity_layers/scheduled_migration_cutover_waits_for_the_clock
        """
        account = create_account()
        line = create_activated_line(account["id"], "4155551604", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        migration = create_migration_request(
            line, prepaid_balance_cents=20000,
            requested_cutover_at="2026-10-01T00:00:00Z",
        )
        check_migration_eligibility(migration["id"])

        advance_clock("2026-10-01T00:00:00Z")
        completed = get_migration_request(migration["id"])

        assert completed["migration_state"] == "CUTOVER_COMPLETE"
        assert completed["carried_mdn"] == line["mdn"]
        assert completed["device_balance_cents"] == 0


class TestCustomerScopedVisibility:
    def test_each_account_exposes_only_its_own_line_list(self, api):
        """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the
        acting `Account`; ownership checks on any resource that references an `Account`
        compare the resource's foreign-key field to `X-User-ID`."

        Design: Corner/cross_cutting_complexity_layers/customer_reads_own_labels_only_through_scoped_lists
        """
        first, _first_line = setup_account_with_one_line("4155551703")
        second, _second_line = setup_account_with_one_line("4155551804")

        response = api_client.list_account_subscriber_lines(
            first["id"], make_customer_headers(first["id"])
        )
        rows = response.json()["data"]

        assert len(rows) == 1
        assert rows[0]["account_id"] == first["id"]
        assert_subscriber_line(rows[0])

    def test_both_accounts_count_their_single_active_line(self, api):
        """PRD §3.6: "`active_line_count`, the count of the account's lines whose
        `service_status` is `ACTIVE`"

        Design: Corner/cross_cutting_complexity_layers/customer_reads_own_labels_only_through_scoped_lists
        """
        first, _first_line = setup_account_with_one_line("4155551704")
        second, _second_line = setup_account_with_one_line("4155551805")

        assert get_account(first["id"])["active_line_count"] == 1
        assert get_account(second["id"])["active_line_count"] == 1

    def test_a_customer_reading_another_accounts_line_is_refused(self, api):
        """PRD §2.1: "Because `Account` is the only entity-backed role identity, a
        `Customer` caller reading a resource whose owning account is not their own is
        treated as unauthorized."

        Design: Corner/cross_cutting_complexity_layers/customer_reads_own_labels_only_through_scoped_lists
        """
        first, _first_line = setup_account_with_one_line("4155551705")
        second, second_line = setup_account_with_one_line("4155551806")

        response = api_client.get_subscriber_line(
            second_line["id"], make_customer_headers(first["id"])
        )

        assert response.status_code == 403
        assert response.json()["data"]["error_id"] == "ERR_UNAUTHORIZED"


class TestImmediateConsistencyOnClawback:
    def test_the_account_read_right_after_the_clawback_is_already_reversed(self, api):
        """PRD §3.4: "the account's `promo_clawed_back_cents` is incremented by the
        reversal amount and `net_promo_credit_cents` is recomputed."

        Design: Corner/consistency_model/side_effects_visible_in_the_same_clawback_response
        """
        account = create_account()
        line = create_activated_line(account["id"], "4155551902", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        schedule = create_promo_schedule(
            line, window_start="2026-09-02T00:00:00Z"
        )
        activate_promo_schedule(schedule["id"])

        api_client.claw_back_promo_schedule(schedule["id"], {}, ADMIN)

        refreshed = get_account(account["id"])
        assert refreshed["promo_credited_cents"] == 32000
        assert refreshed["promo_clawed_back_cents"] == 32000
        assert refreshed["net_promo_credit_cents"] == 0

    def test_no_clock_advance_is_needed_for_the_reversal_to_land(self, api):
        """PRD §3.4: "the credited increment and the clawed-back increment cancel."

        Design: Corner/consistency_model/side_effects_visible_in_the_same_clawback_response
        """
        account = create_account()
        line = create_activated_line(account["id"], "4155551903", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        schedule = create_promo_schedule(
            line, window_start="2026-09-02T00:00:00Z"
        )
        activate_promo_schedule(schedule["id"])
        api_client.claw_back_promo_schedule(schedule["id"], {}, ADMIN)

        assert get_promo_schedule(schedule["id"])["schedule_state"] == "CLAWED_BACK"
        assert get_account(account["id"])["net_promo_credit_cents"] == 0


# --- local helpers -----------------------------------------------------------

def setup_account_with_one_line(mdn):
    account = create_account()
    line = create_activated_line(account["id"], mdn, billing_mode="POSTPAID")
    return get_account(account["id"]), get_line(line["id"])