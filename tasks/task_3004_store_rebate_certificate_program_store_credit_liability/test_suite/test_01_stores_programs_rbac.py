"""Store provisioning, rebate-program lifecycle, and role-based access."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NO_AUTH_HEADERS,
    set_clock, create_store, create_store_payload, create_program,
    create_program_item, create_active_program, create_account,
    create_receipt, cash_line,
    setup_store_with_program, setup_account_with_receipt, submit_receipt,
    make_customer_headers, make_contractor_headers,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["store_admin_headers"]
GUEST = TEST_USERS["guest_service_headers"]
FRAUD = TEST_USERS["fraud_analyst_headers"]
FINANCE = TEST_USERS["finance_admin_headers"]


class TestStoreProvisioning:

    def test_store_create_returns_201_with_initialized_liability_fields(self, api):
        """PRD §3.1: "A new store starts with all liability fields at 0 and
        `liability_epoch` at 0."
        PRD §2.4: "`version` (integer): a system-managed integer that
        increments by exactly 1 on every mutation of the resource."

        Design: Corner/entities/store_create_returns_201_with_initialized_liability_fields
        """
        data = validate_success(api.create_store(
            {
                "store_code": "S-ENT1",
                "submission_window_days": 30,
                "certificate_validity_months": 1,
                "expected_breakage_rate": 0.25,
                "split_txn_window_hours": 2,
                "split_txn_min_receipts": 3,
            },
            ADMIN,
        ), 201)
        assert data["outstanding_liability_cents"] == 0
        assert data["net_liability_cents"] == 0
        assert data["accrued_breakage_income_cents"] == 0
        assert data["liability_epoch"] == 0
        assert data["version"] == 1
        assert data["id"] and data["created_at"] and data["updated_at"]

    def test_store_get_returns_stored_configuration_unchanged(self, api):
        """PRD §3.1: "A `StoreAdmin` onboards a store by creating it with a
        human-facing `store_code`, unique across the platform, together with
        the five policy parameters that drive every downstream rule"
        PRD §2.5: "Non-monetary numeric configuration (percentages such as
        `rebate_pct`, rates such as `expected_breakage_rate`) preserves the
        caller's input precision."

        Design: Corner/entities/store_get_returns_stored_configuration_unchanged
        """
        store = create_store(
            store_code="S-ENT2",
            submission_window_days=45,
            certificate_validity_months=3,
            expected_breakage_rate=0.33,
            split_txn_window_hours=4,
            split_txn_min_receipts=2,
        )
        data = validate_success(api.get_store(store["id"], GUEST))
        assert data["submission_window_days"] == 45
        assert data["certificate_validity_months"] == 3
        assert data["expected_breakage_rate"] == pytest.approx(0.33)
        assert data["split_txn_window_hours"] == 4
        assert data["split_txn_min_receipts"] == 2

    def test_store_create_missing_policy_field_rejected(self, api):
        """PRD §2.9: "structural payload well-formedness
        (`ERR_INVALID_REQUEST`, 400 — missing required fields, invalid enum
        values, quantities or amounts below 1 where a positive value is
        required)"

        Design: Corner/entities/store_create_missing_policy_field_rejected
        """
        resp = api.create_store(
            {
                "store_code": "S-ENT5",
                "certificate_validity_months": 1,
                "expected_breakage_rate": 0.25,
                "split_txn_window_hours": 2,
                "split_txn_min_receipts": 3,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # no store row created
        rows, meta = validate_paginated(api.list_stores(ADMIN))
        assert meta["total_count"] == 0

    def test_store_patch_with_stale_version_rejected(self, api):
        """PRD §2.8: "Updating a store's policy configuration requires the
        request to carry `expected_store_version` holding the `version` the
        caller last observed for that store; if another writer has advanced
        the store's version since that read, the update is rejected with
        `ERR_STALE_VERSION` (412), and the caller must re-read the current
        policy before overwriting it."
        PRD §3.1: "A successful update increments the store's `version` by 1"

        Design: Corner/validations/store_patch_with_stale_version_rejected
        """
        store = create_store(store_code="S-VAL9")
        observed = store["version"]
        first = validate_success(api.update_store(
            store["id"],
            {"expected_store_version": observed, "submission_window_days": 45},
            ADMIN,
        ))
        assert first["submission_window_days"] == 45
        resp = api.update_store(
            store["id"],
            {"expected_store_version": observed, "submission_window_days": 60},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        data = validate_success(api.get_store(store["id"], ADMIN))
        assert data["submission_window_days"] == 45
        assert data["version"] == observed + 1


class TestProgramLifecycle:

    def test_program_item_defaults_applied_when_optionals_omitted(self, api):
        """PRD §3.2: "each carrying a `sku`, a `rebate_pct` expressed as a
        fraction greater than 0 and at most 1 (0.11 for the classic
        eleven-percent week), an optional `excluded_categories` list
        defaulting to empty, an optional `min_quantity` defaulting to 1, and
        an optional `per_receipt_cap_cents` that is either null — uncapped —
        or a positive integer cap compared against the line's rebate *before*
        rounding."

        Design: Corner/entities/program_item_defaults_applied_when_optionals_omitted
        """
        store = create_store(store_code="S-ENT6")
        program = create_program(store["id"], name="W")
        item = validate_success(api.create_program_item(
            store["id"], program["id"],
            {"sku": "AAA", "rebate_pct": 0.11}, ADMIN,
        ), 201)
        assert item["excluded_categories"] == []
        assert item["min_quantity"] == 1
        assert item["per_receipt_cap_cents"] is None
        assert item["program_id"] == program["id"]

    def test_rebate_programs_list_paginates_with_total_count_and_has_more(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter specifies how many items to skip and defaults to
        0."
        PRD §2.3: "The `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`, as shown in §2.2."

        Design: Corner/entities/rebate_programs_list_paginates_with_total_count_and_has_more
        """
        store = create_store(store_code="S-ENT3")
        create_program(store["id"], name="P1",
                       week_start_date="2026-09-07", week_end_date="2026-09-14")
        create_program(store["id"], name="P2",
                       week_start_date="2026-09-14", week_end_date="2026-09-21")
        create_program(store["id"], name="P3",
                       week_start_date="2026-09-21", week_end_date="2026-09-28")

        page1, meta1 = validate_paginated(api.list_programs(
            store["id"], ADMIN, params={"limit": 2, "offset": 0}
        ))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_programs(
            store["id"], ADMIN, params={"limit": 2, "offset": 2}
        ))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_program_auto_closes_after_window_grace_on_next_touch(self, api):
        """PRD §3.2: "Independently, the system auto-closes a program lazily:
        the first read or write against a program observed at a logical clock
        at or after 00:00:00Z on `week_end_date` plus the store's
        `submission_window_days` days transitions it to `CLOSED`."

        Design: Corner/state_machines/program_auto_closes_after_window_grace_on_next_touch
        """
        set_clock("2026-09-07T00:00:00Z")
        store = create_store(store_code="S-SM3")
        program, _ = create_active_program(
            store["id"], [{"sku": "AAA", "rebate_pct": 0.11}]
        )
        assert program["status"] == "ACTIVE"
        # week_end 2026-09-14 + 30 days -> auto-close point 2026-10-14T00:00:00Z
        set_clock("2026-10-15T00:00:00Z")
        data = validate_success(api.get_program(store["id"], program["id"], ADMIN))
        assert data["status"] == "CLOSED"

    def test_program_activate_empty_and_week_past_rejected(self, api):
        """PRD §3.2: "Activation enforces these checks in order: the program
        must contain at least one program item — an empty program is rejected
        with `ERR_PROGRAM_EMPTY` (409); then no other program of the same
        store may already be `ACTIVE` with an overlapping advertised week,
        where two weeks that merely touch — one's end date equal to the
        other's start date — do *not* overlap, and a genuine overlap is
        rejected with `ERR_PROGRAM_WEEK_OVERLAP` (409); finally, the
        advertised week must not have already fully passed, meaning the
        logical clock must be before 00:00:00Z on `week_end_date`, otherwise
        activation is rejected with `ERR_PROGRAM_WEEK_PAST` (409)."

        Design: Corner/validations/program_activate_empty_and_week_past_rejected
        """
        set_clock("2026-09-07T00:00:00Z")
        store = create_store(store_code="S-VAL5")
        p_empty = create_program(store["id"], name="P1")
        p_full = create_program(store["id"], name="P2")
        create_program_item(store["id"], p_full["id"], sku="AAA", rebate_pct=0.11)
        set_clock("2026-09-15T00:00:00Z")

        resp1 = api.activate_program(store["id"], p_empty["id"], ADMIN)
        validate_error(resp1, ApiErrorId.ERR_PROGRAM_EMPTY)
        resp2 = api.activate_program(store["id"], p_full["id"], ADMIN)
        validate_error(resp2, ApiErrorId.ERR_PROGRAM_WEEK_PAST)


class TestProgramWeekOverlap:

    def test_adjacent_week_activation_succeeds(self, api):
        """PRD §3.2: "then no other program of the same store may already be
        `ACTIVE` with an overlapping advertised week, where two weeks that
        merely touch — one's end date equal to the other's start date — do
        *not* overlap, and a genuine overlap is rejected with
        `ERR_PROGRAM_WEEK_OVERLAP` (409)"

        Design: Difficulty/resource_temporal_overlap/program_week_overlap_adjacency_is_not_overlap
        """
        set_clock("2026-09-07T00:00:00Z")
        store = create_store(store_code="S-TO1")
        p1, _ = create_active_program(
            store["id"], [{"sku": "AAA", "rebate_pct": 0.11}],
            week_start="2026-09-07", week_end="2026-09-14",
        )
        assert p1["status"] == "ACTIVE"
        p2 = create_program(store["id"], name="P2",
                            week_start_date="2026-09-14",
                            week_end_date="2026-09-21")
        create_program_item(store["id"], p2["id"], sku="BBB", rebate_pct=0.11)
        activated = validate_success(
            api.activate_program(store["id"], p2["id"], ADMIN)
        )
        assert activated["status"] == "ACTIVE", (
            "adjacency at 2026-09-14 is not an overlap under half-open semantics"
        )

    def test_genuinely_overlapping_week_activation_rejected(self, api):
        """PRD §3.2: "then no other program of the same store may already be
        `ACTIVE` with an overlapping advertised week, where two weeks that
        merely touch — one's end date equal to the other's start date — do
        *not* overlap, and a genuine overlap is rejected with
        `ERR_PROGRAM_WEEK_OVERLAP` (409)"

        Design: Difficulty/resource_temporal_overlap/program_week_overlap_adjacency_is_not_overlap
        """
        set_clock("2026-09-07T00:00:00Z")
        store = create_store(store_code="S-TO1B")
        p1, _ = create_active_program(
            store["id"], [{"sku": "AAA", "rebate_pct": 0.11}],
            week_start="2026-09-07", week_end="2026-09-14",
        )
        p3 = create_program(store["id"], name="P3",
                            week_start_date="2026-09-13",
                            week_end_date="2026-09-20")
        create_program_item(store["id"], p3["id"], sku="CCC", rebate_pct=0.11)
        resp = api.activate_program(store["id"], p3["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_WEEK_OVERLAP)
        data = validate_success(api.get_program(store["id"], p3["id"], ADMIN))
        assert data["status"] == "DRAFT"


class TestRoleAccess:

    def test_missing_role_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request whose `X-User-Role` header is missing or does
        not name one of these six roles is rejected with
        `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/roles/missing_role_header_returns_unauthenticated
        """
        resp = api.create_store(
            create_store_payload(store_code="S-AUTH1"), NO_AUTH_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        _, meta = validate_paginated(api.list_stores(ADMIN))
        assert meta["total_count"] == 0

    def test_customer_cannot_adjudicate_or_issue_certificates(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted
        for the targeted endpoint is rejected with `ERR_FORBIDDEN` (403)."

        Design: Corner/roles/customer_cannot_adjudicate_or_issue_certificates
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-RBAC1"},
            items=[{"sku": "AAA", "rebate_pct": 0.11}],
        )
        # build an UNDER_REVIEW submission (not yet adjudicated)
        sub_ctx = setup_account_with_receipt(base["store"], owner_name="Ann")
        submission = submit_receipt(
            base["store"]["id"], sub_ctx["receipt"]["id"], sub_ctx["account"]
        )
        assert submission["status"] == "UNDER_REVIEW"
        cust = make_customer_headers(sub_ctx["account"]["id"])
        resp1 = api.adjudicate_submission(
            base["store"]["id"], submission["id"], {"decision": "APPROVE"}, cust
        )
        validate_error(resp1, ApiErrorId.ERR_FORBIDDEN)
        resp2 = api.issue_certificate(
            base["store"]["id"], submission["id"], cust
        )
        validate_error(resp2, ApiErrorId.ERR_FORBIDDEN)
        data = validate_success(api.get_submission(
            base["store"]["id"], submission["id"], GUEST
        ))
        assert data["status"] == "UNDER_REVIEW"

    def test_customer_cannot_submit_against_another_accounts_receipt(self, api):
        """PRD §2.1: "When `X-User-Role` is `Customer` or `Contractor`,
        `X-User-ID` is the `id` of the acting `CreditAccount`; ownership
        checks on any resource that references a `CreditAccount` compare the
        resource's account foreign key to `X-User-ID`, and an entity-backed
        role acting on another account's resource is rejected with
        `ERR_FORBIDDEN`."

        Design: Corner/roles/customer_cannot_submit_against_another_accounts_receipt
        """
        set_clock("2026-09-08T12:00:00Z")
        store = create_store(store_code="S-RBAC2")
        ac1 = create_account(store["id"], owner_name="Ann")
        ac2 = create_account(store["id"], owner_name="Bob")
        receipt = create_receipt(
            store["id"], ac2["id"],
            [cash_line(1, "ZZZ", "PAINT", 1, 1000)],
            receipt_number="R-RBAC2",
        )
        resp = api.create_submission(
            store["id"], {"receipt_id": receipt["id"]},
            make_customer_headers(ac1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_fraud_analyst_cannot_create_receipts_and_store_admin_cannot_run_breakage(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted
        for the targeted endpoint is rejected with `ERR_FORBIDDEN` (403)."

        Design: Corner/roles/fraud_analyst_cannot_create_receipts_and_store_admin_cannot_run_breakage
        """
        set_clock("2026-09-08T12:00:00Z")
        store = create_store(store_code="S-RBAC3")
        account = create_account(store["id"], owner_name="Ann")
        resp1 = api.create_receipt(
            store["id"],
            {
                "receipt_number": "R-RBAC3",
                "account_id": account["id"],
                "purchase_at": "2026-09-08T10:00:00Z",
                "lines": [cash_line(1, "ZZZ", "PAINT", 1, 1000)],
            },
            FRAUD,
        )
        validate_error(resp1, ApiErrorId.ERR_FORBIDDEN)
        resp2 = api.create_breakage_run(
            store["id"], {"expected_store_version": store["version"]}, ADMIN
        )
        validate_error(resp2, ApiErrorId.ERR_FORBIDDEN)

    def test_contractor_can_create_own_job_purchase_but_not_others(self, api):
        """PRD §2.1: "When `X-User-Role` is `Customer` or `Contractor`,
        `X-User-ID` is the `id` of the acting `CreditAccount`; ownership
        checks on any resource that references a `CreditAccount` compare the
        resource's account foreign key to `X-User-ID`, and an entity-backed
        role acting on another account's resource is rejected with
        `ERR_FORBIDDEN`."
        PRD §3.3: "A `Contractor` registers a job purchase on their own
        account by supplying a `job_reference`, unique within that contractor
        account; the job is created in `OPEN` status"

        Design: Corner/roles/contractor_can_create_own_job_purchase_but_not_others
        """
        store = create_store(store_code="S-RBAC4")
        acc1 = create_account(store["id"], owner_name="Carl One",
                              account_type="CONTRACTOR")
        acc2 = create_account(store["id"], owner_name="Carl Two",
                              account_type="CONTRACTOR")
        job = validate_success(api.create_job_purchase(
            store["id"], acc1["id"], {"job_reference": "JOB-1"},
            make_contractor_headers(acc1["id"]),
        ), 201)
        assert job["status"] == "OPEN"
        resp = api.create_job_purchase(
            store["id"], acc2["id"], {"job_reference": "JOB-2"},
            make_contractor_headers(acc1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
