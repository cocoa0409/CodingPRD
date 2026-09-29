"""
The role matrix, the portal user's customer scope and the two OCC gates.

Every test starts against an empty database and builds each precondition from
the endpoints the PRD declares.
"""

from test_helpers import (
    ANALYST_HEADERS,
    AUDITOR_HEADERS,
    AUDITOR_USER_ID,
    DEFAULT_CLOCK_INSTANT,
    DIRECTOR_HEADERS,
    DIRECTOR_USER_ID,
    KAM_HEADERS,
    MONDAY_AUG_03,
    MONDAY_AUG_10,
    MONDAY_AUG_17,
    MONDAY_AUG_24,
    MONDAY_JUL_06,
    SPECIALIST_HEADERS,
    AccrualMethod,
    AllocationPosture,
    AllocationStatus,
    ApiErrorId,
    AuditStatus,
    Channel,
    ComplianceAuditStatus,
    DeductionStatus,
    DeductionValidationPolicy,
    FactSource,
    FactType,
    PromotionLifecycleStatus,
    SpendStatus,
    TacticStatus,
    TradingStatus,
    UserRole,
    assert_money,
    assert_ratio,
    create_allocation_payload,
    create_brand_payload,
    create_compliance_audit_payload,
    create_customer_payload,
    create_deduction_payload,
    create_program_payload,
    create_promotion_payload,
    create_tpr_tactic_payload,
    create_volume_fact_payload,
    current_allocation_version,
    date_plus_days,
    instant,
    make_finance_analyst_headers,
    make_headers_blank_role,
    make_headers_blank_user_id,
    make_portal_user_headers,
    make_unknown_role_headers,
    post_accrual,
    read_accrual,
    read_allocation,
    read_customer,
    read_deduction,
    read_promotion,
    set_clock,
    setup_allocation_context,
    setup_customer,
    setup_deduction,
    setup_live_promotion,
    setup_matched_deduction,
    setup_program,
    setup_verified_evidence_document,
    setup_volume_fact,
    validate_deduction_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStaffWriteSurfaces:
    """Each staff role owns a write surface, and only its own."""

    def test_every_staff_role_exercises_the_surface_it_owns(self, api):
        """
        One pass over the five internal roles, each performing a write only its
        own role list permits, and every call succeeds.

        PRD: "A fiscal year of trade spending begins when a `TradeMarketingDirector` opens an annual **trade program**."
        PRD: "A `TradeMarketingDirector` or a `TradeFinanceAnalyst` creates one by supplying `program_id`, `customer_id`, `brand_id`, an `event_type` of `SEASONAL`, `EVERYDAY` or `NEW_ITEM`, a `planned_amount` in USD (strictly positive, exactly 2 decimal places), a `baseline_units` figure (a whole number at or above zero) recording the non-promoted case volume the cell assumes for the year, and a `planned_incremental_units` figure (also a whole number at or above zero) recording the incremental case volume the money is expected to buy."
        PRD: "A `KeyAccountManager` plans the actual events."
        PRD: "A `KeyAccountManager` submits a promotion that is currently `DRAFT`, moving `lifecycle_status` `DRAFT` → `SUBMITTED`."
        PRD: "A successful approval moves `lifecycle_status` `SUBMITTED` → `APPROVED` and records the acting director's identifier in `approved_by_user_id`."
        PRD: "Volume is the raw material of every accrual and every measurement, and it arrives as an append-only weekly journal loaded by a `TradeFinanceAnalyst`."
        PRD: "A `DeductionSpecialist` books each chargeback as a **deduction**, supplying the `customer_id` that took it, the retailer's own `claim_reference` (1 to 60 characters), the `claimed_amount` gross-deducted from the remittance (strictly positive, exactly 2 decimal places), the `deduction_date` printed on the remittance advice as an ISO 8601 calendar date, and optionally a `supersedes_deduction_id` naming an earlier claim this corrected re-issue replaces."
        PRD: "The audit is created in `status` `SCHEDULED` with `findings_count` 0, `recovery_claim_amount` 0.00, `issued_at` null and `auditor_user_id` set to the acting auditor; the customer's `audit_status` moves `CLEAR` → `AUDIT_IN_PROGRESS` and its `version` is incremented by 1."

        Design: Corner/rbac/each_staff_role_exercises_its_own_write_surface
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)

        program = validate_success(
            api.create_program(
                create_program_payload(
                    total_budget_amount=500000.00,
                    accrual_method_default=AccrualMethod.CONSUMPTION.value,
                ),
                DIRECTOR_HEADERS,
            ),
            expected_status=201,
        )
        brand = validate_success(
            api.create_brand(
                create_brand_payload(
                    program["id"], list_price_per_case=24.00, cogs_per_case=8.70,
                    baseline_units_per_week=1200,
                ),
                DIRECTOR_HEADERS,
            ),
            expected_status=201,
        )
        customer = validate_success(
            api.create_customer(
                create_customer_payload(
                    program["id"], channel=Channel.GROCERY.value,
                    deduction_validation_policy=(
                        DeductionValidationPolicy.EVIDENCE_BASED.value
                    ),
                ),
                DIRECTOR_HEADERS,
            ),
            expected_status=201,
        )

        allocation = validate_success(
            api.create_budget_allocation(
                create_allocation_payload(
                    program["id"], customer["id"], brand["id"],
                    planned_amount=50000.00, baseline_units=20000,
                    planned_incremental_units=10000,
                ),
                ANALYST_HEADERS,
            ),
            expected_status=201,
        )
        approved_cell = validate_success(
            api.approve_budget_allocation(allocation["id"], DIRECTOR_HEADERS)
        )
        assert approved_cell["status"] == AllocationStatus.APPROVED.value
        assert approved_cell["version"] == 2

        promotion = validate_success(
            api.create_promotion(
                create_promotion_payload(
                    allocation["id"], approved_cell["version"],
                    window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_10,
                    accrual_method=AccrualMethod.CONSUMPTION.value,
                ),
                KAM_HEADERS,
            ),
            expected_status=201,
        )
        tactic = validate_success(
            api.create_tactic(
                promotion["id"],
                create_tpr_tactic_payload(
                    planned_units=4000, rate_per_case=1.000,
                    window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_10,
                ),
                KAM_HEADERS,
            ),
            expected_status=201,
        )
        assert tactic["status"] == TacticStatus.PLANNED.value

        submitted = validate_success(api.submit_promotion(promotion["id"], KAM_HEADERS))
        assert submitted["lifecycle_status"] == PromotionLifecycleStatus.SUBMITTED.value

        approved = validate_success(
            api.approve_promotion(promotion["id"], DIRECTOR_HEADERS)
        )
        assert approved["lifecycle_status"] == PromotionLifecycleStatus.APPROVED.value
        assert approved["approved_by_user_id"] == DIRECTOR_USER_ID

        fact = validate_success(
            api.create_volume_fact(
                create_volume_fact_payload(
                    customer["id"], brand["id"],
                    fact_type=FactType.CONSUMPTION.value, period_start=MONDAY_AUG_03,
                    units=5000, source=FactSource.EDI_852.value,
                ),
                ANALYST_HEADERS,
            ),
            expected_status=201,
        )
        assert fact["units"] == 5000

        deduction = validate_success(
            api.create_deduction(
                create_deduction_payload(
                    customer["id"], claim_reference="MM-CLAIM-0040",
                    claimed_amount=400.00, deduction_date=MONDAY_AUG_03,
                ),
                SPECIALIST_HEADERS,
            ),
            expected_status=201,
        )
        assert deduction["status"] == DeductionStatus.RECEIVED.value

        audit = validate_success(
            api.create_compliance_audit(
                customer["id"],
                create_compliance_audit_payload(
                    scope_start=MONDAY_JUL_06, scope_end=MONDAY_AUG_03
                ),
                AUDITOR_HEADERS,
            ),
            expected_status=201,
        )
        assert audit["status"] == ComplianceAuditStatus.SCHEDULED.value
        assert audit["auditor_user_id"] == AUDITOR_USER_ID

        after = read_customer(api, customer["id"])
        assert after["audit_status"] == AuditStatus.AUDIT_IN_PROGRESS.value
        assert after["trading_status"] == TradingStatus.ACTIVE.value

    def test_a_role_reaching_into_another_roles_surface_is_turned_away(self, api):
        """
        Five cross-role writes against a fully built program tree are all refused
        for the role, ahead of every existence, state and fiscal rule that would
        also have something to say.

        PRD: "Once the role is recognised, it is checked against the set of roles the target endpoint permits; a recognised role that is not on that list is refused with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD: "**Rung 3** — the caller's role appears in the target endpoint's role list, on every endpoint: `ERR_ROLE_NOT_PERMITTED`."
        PRD: "`TradeMarketingDirector` owns the annual trade fund. This role opens programs, registers brands and retail customers, creates and approves budget allocations, requests changes on or approves submitted promotions, locks the program at year end, and is the only role permitted to approve a large write-off."
        PRD: "`KeyAccountManager` plans promotions at the retailer: it creates promotions and their tactic lines, performs rate maintenance, cancels planned lines, submits plans for review, revises them after changes are requested, withdraws approved promotions, and verifies retailer commitment paperwork."
        PRD: "`TradeFinanceAnalyst` runs the ledger: it loads weekly volume facts, posts and reverses accruals, values and settles deductions, verifies performance evidence paperwork, drives the activation and aging sweeps, and produces post-event analyses."
        PRD: "`DeductionSpecialist` owns deduction intake: it books retailer claims, matches them to promotion agreements, opens disputes, drives the retailer round trips, records recoveries, approves small write-offs, and may place a customer on manual credit hold."
        PRD: "`ComplianceAuditor` audits contract compliance at the customer: it opens the audit, records findings with their recovery claims, and participates in issuing them. It has no authority over money, promotions or deductions."

        Design: Corner/rbac/a_role_reaching_into_another_roles_surface_is_turned_away
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = setup_allocation_context(
            api,
            program_overrides={
                "total_budget_amount": 500000.00,
                "accrual_method_default": AccrualMethod.CONSUMPTION.value,
            },
            planned_amount=50000.00, baseline_units=20000,
            planned_incremental_units=10000,
        )
        allocation_version = current_allocation_version(api, context["allocation"]["id"])
        deduction = setup_deduction(
            api, context["customer"]["id"], claim_reference="MM-CLAIM-0041",
            claimed_amount=400.00, deduction_date=MONDAY_AUG_03,
        )

        validate_error(
            api.create_program(
                create_program_payload(
                    fiscal_year=2027, total_budget_amount=100000.00,
                    accrual_method_default=AccrualMethod.CONSUMPTION.value,
                ),
                KAM_HEADERS,
            ),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
        )
        validate_error(
            api.create_promotion(
                create_promotion_payload(
                    context["allocation"]["id"], allocation_version,
                    window_start=MONDAY_AUG_17, window_end=MONDAY_AUG_24,
                    accrual_method=AccrualMethod.CONSUMPTION.value,
                ),
                ANALYST_HEADERS,
            ),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
        )
        validate_error(
            api.validate_deduction(
                deduction["id"], validate_deduction_payload(1), SPECIALIST_HEADERS
            ),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
        )
        validate_error(
            api.create_deduction(
                create_deduction_payload(
                    context["customer"]["id"], claim_reference="MM-CLAIM-0042",
                    claimed_amount=100.00, deduction_date=MONDAY_AUG_03,
                ),
                AUDITOR_HEADERS,
            ),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
        )
        validate_error(
            api.create_compliance_audit(
                context["customer"]["id"],
                create_compliance_audit_payload(
                    scope_start=MONDAY_JUL_06, scope_end=MONDAY_AUG_03
                ),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
        )

        still_received = read_deduction(api, deduction["id"])
        assert still_received["status"] == DeductionStatus.RECEIVED.value
        assert still_received["validated_amount"] is None

        untouched_customer = read_customer(api, context["customer"]["id"])
        assert untouched_customer["audit_status"] == AuditStatus.CLEAR.value

        promotion_rows, promotion_meta = validate_paginated(
            api.list_promotions(DIRECTOR_HEADERS)
        )
        assert promotion_meta["total_count"] == 0
        assert promotion_rows == []

        deduction_rows, deduction_meta = validate_paginated(
            api.list_deductions(DIRECTOR_HEADERS)
        )
        assert deduction_meta["total_count"] == 1
        assert deduction_rows[0]["id"] == deduction["id"]

    def test_the_header_pre_checks_answer_before_the_role_matrix(self, api):
        """
        A blank role, a blank user id and an undeclared role name are all
        authentication failures on an endpoint the caller would otherwise be
        entitled to use, and the identical body then succeeds.

        PRD: "A header that is missing, or that is present but carries the empty string, counts as absent, and the request is refused with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose `X-User-Role` is not one of the six role names defined below is refused with `ERR_UNKNOWN_ROLE` (HTTP 401) — note that an unrecognised role is an authentication failure, not an authorisation failure. Once the role is recognised, it is checked against the set of roles the target endpoint permits; a recognised role that is not on that list is refused with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD: "**Rung 1** — both authentication headers present and non-empty, on every endpoint: `ERR_UNAUTHENTICATED`."
        PRD: "**Rung 2** — `X-User-Role` is one of the six declared roles, on every endpoint: `ERR_UNKNOWN_ROLE`."
        PRD: "`claim_reference` must be unique per `customer_id` across every deduction of that customer in every status; a repeat is refused with `ERR_DUPLICATE_CLAIM_REFERENCE` (HTTP 409)."

        Design: Corner/rbac/header_pre_checks_run_ahead_of_the_role_matrix
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        program = setup_program(
            api,
            total_budget_amount=500000.00,
            accrual_method_default=AccrualMethod.CONSUMPTION.value,
        )
        customer = setup_customer(api, program["id"])

        payload = create_deduction_payload(
            customer["id"], claim_reference="MM-CLAIM-0043",
            claimed_amount=400.00, deduction_date=MONDAY_AUG_03,
        )

        validate_error(
            api.create_deduction(payload, make_headers_blank_role()),
            ApiErrorId.UNAUTHENTICATED.value,
        )
        validate_error(
            api.create_deduction(
                payload,
                make_headers_blank_user_id(role=UserRole.DEDUCTION_SPECIALIST.value),
            ),
            ApiErrorId.UNAUTHENTICATED.value,
        )
        validate_error(
            api.create_deduction(payload, make_unknown_role_headers()),
            ApiErrorId.UNKNOWN_ROLE.value,
        )

        booked = validate_success(
            api.create_deduction(payload, SPECIALIST_HEADERS), expected_status=201
        )
        assert booked["claim_reference"] == "MM-CLAIM-0043"
        assert booked["status"] == DeductionStatus.RECEIVED.value

        rows, meta = validate_paginated(api.list_deductions(SPECIALIST_HEADERS))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == booked["id"]


class TestPortalCustomerScope:
    """The portal login is entity-backed and confined to its own retailer."""

    def test_the_portal_login_sees_only_its_own_customer(self, api):
        """
        The portal user reads its own claim, is refused with the scope code rather
        than a 404 on the other retailer's claim, is refused the same way on a
        list filtered to that retailer, and sees exactly one row when it filters
        to itself.

        PRD: "`CustomerPortalUser` is the single exception and is **entity-backed**: when `X-User-Role` is `CustomerPortalUser`, `X-User-ID` is the `id` of the acting `Customer`."
        PRD: "Ownership checks on any resource that references a `Customer` compare that resource's customer foreign key to `X-User-ID`: the promotion's, deduction's, dispute's or allocation's `customer_id`, or the `customer_id` query filter on a list read."
        PRD: "A portal user that addresses or filters a resource belonging to any other customer is refused with `ERR_CUSTOMER_SCOPE_VIOLATION` (HTTP 403). This refusal is deliberately evaluated **before** existence is checked, so a portal user cannot probe for other customers' identifiers by comparing a 404 against a 403."
        PRD: "**Rung 4** — a `CustomerPortalUser` addresses only its own customer's data, on every endpoint whose role list includes `CustomerPortalUser`: `ERR_CUSTOMER_SCOPE_VIOLATION`."

        Design: Corner/rbac/the_portal_login_sees_only_its_own_customer
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        program = setup_program(
            api,
            total_budget_amount=500000.00,
            accrual_method_default=AccrualMethod.CONSUMPTION.value,
        )
        mine = setup_customer(
            api, program["id"], channel=Channel.GROCERY.value,
            deduction_validation_policy=DeductionValidationPolicy.EVIDENCE_BASED.value,
        )
        theirs = setup_customer(
            api, program["id"], channel=Channel.CLUB.value,
            deduction_validation_policy=DeductionValidationPolicy.AGREEMENT_CAP.value,
        )
        my_claim = setup_deduction(
            api, mine["id"], claim_reference="MM-CLAIM-0044",
            claimed_amount=400.00, deduction_date=MONDAY_AUG_03,
        )
        their_claim = setup_deduction(
            api, theirs["id"], claim_reference="VC-CLAIM-0044",
            claimed_amount=900.00, deduction_date=MONDAY_AUG_03,
        )

        portal = make_portal_user_headers(mine["id"])

        own = validate_success(api.get_deduction(my_claim["id"], portal))
        assert own["claim_reference"] == "MM-CLAIM-0044"
        assert_money(own["claimed_amount"], 400.00, "claimed_amount")

        validate_error(
            api.get_deduction(their_claim["id"], portal),
            ApiErrorId.CUSTOMER_SCOPE_VIOLATION.value,
        )
        validate_error(
            api.list_deductions(portal, params={"customer_id": theirs["id"]}),
            ApiErrorId.CUSTOMER_SCOPE_VIOLATION.value,
        )

        rows, meta = validate_paginated(
            api.list_deductions(portal, params={"customer_id": mine["id"]})
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == my_claim["id"]

        undisclosed = read_deduction(api, their_claim["id"])
        assert_money(undisclosed["claimed_amount"], 900.00, "claimed_amount")
        assert undisclosed["status"] == DeductionStatus.RECEIVED.value


class TestOptimisticConcurrency:
    """The two version-guarded writes, each defeated by an interleaved writer."""

    def test_a_promotion_create_carries_the_allocation_version_it_last_read(self, api):
        """
        Two promotions planned against one cell: the first create advances the
        parent version, so the second create replaying the version read before it
        is refused, and re-reading the cell makes the identical body succeed.

        PRD: "Creating a promotion requires `expected_allocation_version` as a non-optional field of the request body, carrying the client's last observed `version` of the `BudgetAllocation` named by `allocation_id`."
        PRD: "If that value does not equal the allocation's current `version`, the create is refused with `ERR_STALE_ALLOCATION_VERSION` (HTTP 412)."
        PRD: "Note that the allocation's `version` advances on every child promotion create as well, which is precisely what makes a second create replaying the same expected version fail."
        PRD: "**Rung 30** — `expected_allocation_version` matches the referenced allocation's `version`, on promotion create: `ERR_STALE_ALLOCATION_VERSION`."
        PRD: "Almost every resource additionally carries `updated_at`, in the same format, refreshed on every mutation, and `version`, an integer that starts at 1 when the row is created and is incremented by exactly 1 on every mutation of that row — including mutations that are side effects of an operation aimed at a different resource."
        PRD: "A `TradeMarketingDirector` approves an allocation that is currently `DRAFT` under a program that is currently `OPEN`, moving `status` `DRAFT` → `APPROVED`; the whole ledger rollup is recomputed and the allocation's `version` is incremented by 1 with `updated_at` refreshed."
        PRD: "`committed_amount` is the sum of `planned_total_spend` across child promotions whose `lifecycle_status` is `APPROVED`, `LIVE`, `ENDED` or `ANALYZED`, rounded half up to 2 decimal places; promotions in `DRAFT`, `SUBMITTED`, `CHANGES_REQUESTED` or `WITHDRAWN` reserve nothing."

        Design: Corner/complexity_layers/promotion_create_carries_the_allocation_version_it_last_read
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        program = validate_success(
            api.create_program(
                create_program_payload(
                    total_budget_amount=500000.00,
                    accrual_method_default=AccrualMethod.CONSUMPTION.value,
                ),
                DIRECTOR_HEADERS,
            ),
            expected_status=201,
        )
        brand = validate_success(
            api.create_brand(
                create_brand_payload(
                    program["id"], list_price_per_case=24.00, cogs_per_case=8.70,
                    baseline_units_per_week=1200,
                ),
                DIRECTOR_HEADERS,
            ),
            expected_status=201,
        )
        customer = validate_success(
            api.create_customer(
                create_customer_payload(program["id"], channel=Channel.GROCERY.value),
                DIRECTOR_HEADERS,
            ),
            expected_status=201,
        )
        created = validate_success(
            api.create_budget_allocation(
                create_allocation_payload(
                    program["id"], customer["id"], brand["id"],
                    planned_amount=50000.00, baseline_units=20000,
                    planned_incremental_units=10000,
                ),
                DIRECTOR_HEADERS,
            ),
            expected_status=201,
        )
        assert created["version"] == 1
        assert created["status"] == AllocationStatus.DRAFT.value

        approved = validate_success(
            api.approve_budget_allocation(created["id"], DIRECTOR_HEADERS)
        )
        assert approved["version"] == 2
        assert approved["status"] == AllocationStatus.APPROVED.value

        first = validate_success(
            api.create_promotion(
                create_promotion_payload(
                    created["id"], approved["version"],
                    window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_10,
                    accrual_method=AccrualMethod.CONSUMPTION.value,
                ),
                KAM_HEADERS,
            ),
            expected_status=201,
        )

        replayed_body = create_promotion_payload(
            created["id"], approved["version"],
            window_start=MONDAY_AUG_17, window_end=MONDAY_AUG_24,
            accrual_method=AccrualMethod.CONSUMPTION.value,
        )
        validate_error(
            api.create_promotion(replayed_body, KAM_HEADERS),
            ApiErrorId.STALE_ALLOCATION_VERSION.value,
        )

        fresh_version = current_allocation_version(api, created["id"])
        assert fresh_version == 3

        retried_body = dict(replayed_body, expected_allocation_version=fresh_version)
        second = validate_success(
            api.create_promotion(retried_body, KAM_HEADERS), expected_status=201
        )
        assert second["lifecycle_status"] == PromotionLifecycleStatus.DRAFT.value
        assert current_allocation_version(api, created["id"]) == 4

        rows, meta = validate_paginated(
            api.list_promotions(KAM_HEADERS, params={"allocation_id": created["id"]})
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {first["id"], second["id"]}

        cell = read_allocation(api, created["id"])
        assert_money(cell["committed_amount"], 0.00, "committed_amount")
        assert cell["committed_units"] == 0

    def test_a_deduction_validation_carries_the_promotion_version_it_last_read(self, api):
        """
        An accrual posted between the client's read and its validation advances the
        promotion's version, so the validation priced off the old balance is
        refused; re-reading and resending the identical body succeeds.

        PRD: "Validating a deduction requires `expected_promotion_version` as a non-optional field of the request body, carrying the client's last observed `version` of the `Promotion` the deduction was matched to."
        PRD: "If that value does not equal the promotion's current `version`, the validation is refused with `ERR_STALE_PROMOTION_VERSION` (HTTP 412)."
        PRD: "**Rung 31** — `expected_promotion_version` matches the parent promotion's `version`, on deduction validation and on tactic patch: `ERR_STALE_PROMOTION_VERSION`."
        PRD: "On the `CONSUMPTION` basis the effective period is the requested `period_start` itself with no shift, and the facts read are those with `fact_type` `CONSUMPTION`."
        PRD: "Third, each line yields its own rounded component: a `TPR` line contributes `fact_units` multiplied by that line's `rate_per_case`, rounded half up to 2 decimal places; a `DISPLAY` or `FEATURE` line contributes its `fixed_fee` divided by its own `week_count`, rounded half up to 2 decimal places, which amortises the flat placement fee evenly across the weeks the placement runs."
        PRD: "Posting then recomputes the promotion's accrual ledger and spend status, recomputes the allocation's `accrued_amount`, and increments the promotion's `version` and the allocation's `version` by 1 each."
        PRD: "Under `EVIDENCE_BASED`, `entitled_amount` is built bottom-up from substantiated cases: the evidence units multiplied by the contract rate, rounded half up to 2 decimal places, and it is **not** capped by the accrual balance — so a well-evidenced claim can legitimately exceed what was ever accrued and push the promotion over budget."
        PRD: "From `entitled_amount` two figures follow: `validated_amount` is the lesser of the claim's `claimed_amount` and its `entitled_amount` — the portion that will actually consume promotion accrual — and `variance_amount` is `claimed_amount` minus `validated_amount`, rounded half up to 2 decimal places, which is the invalid portion eligible for dispute."
        PRD: "`accrued_balance` is `gross_accrued_amount` minus `reversed_accrual_amount` minus `consumed_deduction_amount`, rounded to 2 decimal places, and it may legitimately be negative when a retailer has deducted more than was ever accrued."
        PRD: "`recognized_spend_amount` is the **greater** of two views — the accrual-book view, `gross_accrued_amount` minus `reversed_accrual_amount`, and the deduction-book view, `consumed_deduction_amount` — rounded to 2 decimal places."
        PRD: "Otherwise `spend_ratio` is `recognized_spend_amount` divided by `planned_total_spend`, rounded half up to 4 decimal places, and `spend_status` follows exact boundaries: a ratio strictly greater than 1.0000 is `OVERSPENT`; a ratio at or above 0.9000 but not exceeding 1.0000 is `OVERSPEND_WARNING`; anything below 0.9000 is `WITHIN_BUDGET`."

        Design: Corner/complexity_layers/deduction_validation_carries_the_promotion_version_it_last_read
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = setup_allocation_context(
            api,
            program_overrides={
                "total_budget_amount": 500000.00,
                "accrual_method_default": AccrualMethod.CONSUMPTION.value,
            },
            brand_overrides={
                "list_price_per_case": 24.00, "cogs_per_case": 8.70,
                "baseline_units_per_week": 1200,
            },
            planned_amount=50000.00, baseline_units=20000,
            planned_incremental_units=10000,
        )
        context = setup_live_promotion(
            api, context,
            clock_instant=instant(date_plus_days(MONDAY_AUG_03, 2)),
            promotion_overrides={
                "window_start": MONDAY_AUG_03, "window_end": MONDAY_AUG_10,
                "accrual_method": AccrualMethod.CONSUMPTION.value,
            },
            planned_units=4000, rate_per_case=1.000,
            window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_10,
        )
        promotion_id = context["promotion"]["id"]
        assert context["promotion"]["lifecycle_status"] == (
            PromotionLifecycleStatus.LIVE.value
        )
        assert_money(
            context["promotion"]["planned_total_spend"], 4000.00, "planned_total_spend"
        )

        setup_verified_evidence_document(api, promotion_id, units_verified=500)
        setup_volume_fact(
            api, context["customer"]["id"], context["brand"]["id"],
            fact_type=FactType.CONSUMPTION.value, period_start=MONDAY_AUG_03,
            units=3000, source=FactSource.EDI_852.value,
        )
        deduction = setup_matched_deduction(
            api, context["customer"]["id"], promotion_id,
            claim_reference="MM-CLAIM-0050", claimed_amount=400.00,
            deduction_date=MONDAY_AUG_03,
        )

        read_before_the_accrual = read_promotion(api, promotion_id)
        stale_version = read_before_the_accrual["version"]

        accrual = post_accrual(api, promotion_id, MONDAY_AUG_03)
        assert accrual["fact_units"] == 3000
        assert_money(accrual["amount"], 3000.00, "amount")

        validate_error(
            api.validate_deduction(
                deduction["id"], validate_deduction_payload(stale_version),
                ANALYST_HEADERS,
            ),
            ApiErrorId.STALE_PROMOTION_VERSION.value,
        )

        fresh = read_promotion(api, promotion_id)
        assert fresh["version"] == stale_version + 1
        assert_money(fresh["accrued_balance"], 3000.00, "accrued_balance")
        assert read_deduction(api, deduction["id"])["status"] == (
            DeductionStatus.MATCHED.value
        )

        validated = validate_success(
            api.validate_deduction(
                deduction["id"], validate_deduction_payload(fresh["version"]),
                ANALYST_HEADERS,
            )
        )
        assert validated["status"] == DeductionStatus.VALIDATED.value
        assert_money(validated["entitled_amount"], 500.00, "entitled_amount")
        assert_money(validated["validated_amount"], 400.00, "validated_amount")

        after = read_promotion(api, promotion_id)
        assert_money(
            after["consumed_deduction_amount"], 400.00, "consumed_deduction_amount"
        )
        assert_money(after["accrued_balance"], 2600.00, "accrued_balance")
        assert_ratio(after["spend_ratio"], 0.7500, "spend_ratio")
        assert after["spend_status"] == SpendStatus.WITHIN_BUDGET.value

        assert_money(read_accrual(api, accrual["id"])["amount"], 3000.00, "amount")


class TestRefusedValidationCascade:
    """A validation refused for duties leaves all four cascade hops alone."""

    def test_a_refused_validation_leaves_every_hop_of_the_chain_untouched(self, api):
        """
        The claim is large enough that a successful validation would have driven
        the promotion to `OVERSPENT`, the cell to `RESTRICTED` and the retailer to
        `CREDIT_HOLD`; refused for segregation of duties, not one hop moves.

        PRD: "Two decisions in this system are too consequential to be made twice by the same person, and both checks compare **opaque user identifiers, not roles** — so a second operator holding the same role always succeeds where the first is refused."
        PRD: "The operator recorded in a promotion's `approved_by_user_id` may not validate any deduction matched to that promotion."
        PRD: "Either violation is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD: "**Rung 50** — segregation of duties on the opaque acting user, on deduction validation and on dispute write-off: `ERR_SEGREGATION_OF_DUTIES`."
        PRD: "The deepest chain in the system starts at a deduction validation: consuming accrual moves the promotion's spend figures (hop 1); the recomputed `spend_ratio` can push the promotion's `spend_status` to `OVERSPENT` (hop 2); the first time a promotion reaches `OVERSPENT` the owning allocation's `overspend_event_count` is incremented and its `posture` moves from `OPEN` to `RESTRICTED` (hop 3); and a `RESTRICTED` allocation contributes penalty points to its customer, which can move that customer's `trading_status` from `ACTIVE` to `CREDIT_HOLD` (hop 4)."
        PRD: "It then walks the four-hop chain of §2.9: the promotion's `consumed_deduction_amount` rises by `validated_amount` and its `accrued_balance` falls by the same amount; the spend status is recomputed from the new consumed figure and may reach `OVERSPENT`; reaching `OVERSPENT` for the first time increments the allocation's `overspend_event_count` and drives its `posture` `OPEN` → `RESTRICTED`; and the newly `RESTRICTED` allocation adds 10 points to the customer's `compliance_penalty_points`, which can drive that customer's `trading_status` `ACTIVE` → `CREDIT_HOLD`."
        PRD: "The recomputation runs after every accrual posting, accrual reversal, deduction validation, dispute write-off, dispute recovery and promotion withdrawal."
        PRD: "Almost every resource additionally carries `updated_at`, in the same format, refreshed on every mutation, and `version`, an integer that starts at 1 when the row is created and is incremented by exactly 1 on every mutation of that row — including mutations that are side effects of an operation aimed at a different resource."
        PRD: "A new claim is created in `status` `RECEIVED` with `promotion_id`, `validation_basis`, `entitled_amount`, `validated_amount`, `variance_amount`, `matched_by_user_id`, `validated_by_user_id` and `settled_at` all null."

        Design: Corner/complexity_layers/a_refused_validation_leaves_every_hop_of_the_chain_untouched
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = setup_allocation_context(
            api,
            program_overrides={
                "total_budget_amount": 500000.00,
                "accrual_method_default": AccrualMethod.CONSUMPTION.value,
            },
            brand_overrides={
                "list_price_per_case": 24.00, "cogs_per_case": 8.70,
                "baseline_units_per_week": 1200,
            },
            planned_amount=50000.00, baseline_units=20000,
            planned_incremental_units=10000,
        )
        context = setup_live_promotion(
            api, context,
            clock_instant=instant(date_plus_days(MONDAY_AUG_03, 2)),
            promotion_overrides={
                "window_start": MONDAY_AUG_03, "window_end": MONDAY_AUG_10,
                "accrual_method": AccrualMethod.CONSUMPTION.value,
            },
            planned_units=4000, rate_per_case=1.000,
            window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_10,
        )
        promotion_id = context["promotion"]["id"]
        assert context["promotion"]["approved_by_user_id"] == DIRECTOR_USER_ID
        assert_money(
            context["promotion"]["planned_total_spend"], 4000.00, "planned_total_spend"
        )

        setup_verified_evidence_document(api, promotion_id, units_verified=9000)
        setup_volume_fact(
            api, context["customer"]["id"], context["brand"]["id"],
            fact_type=FactType.CONSUMPTION.value, period_start=MONDAY_AUG_03,
            units=3000, source=FactSource.EDI_852.value,
        )
        post_accrual(api, promotion_id, MONDAY_AUG_03)
        deduction = setup_matched_deduction(
            api, context["customer"]["id"], promotion_id,
            claim_reference="MM-CLAIM-0051", claimed_amount=5000.00,
            deduction_date=MONDAY_AUG_03,
        )

        promotion_before = read_promotion(api, promotion_id)
        assert_money(
            promotion_before["consumed_deduction_amount"], 0.00,
            "consumed_deduction_amount",
        )
        assert_money(promotion_before["accrued_balance"], 3000.00, "accrued_balance")
        assert promotion_before["spend_status"] == SpendStatus.WITHIN_BUDGET.value

        cell_before = read_allocation(api, context["allocation"]["id"])
        assert cell_before["posture"] == AllocationPosture.OPEN.value
        assert cell_before["overspend_event_count"] == 0

        customer_before = read_customer(api, context["customer"]["id"])
        assert customer_before["compliance_penalty_points"] == 0
        assert customer_before["trading_status"] == TradingStatus.ACTIVE.value

        validate_error(
            api.validate_deduction(
                deduction["id"],
                validate_deduction_payload(promotion_before["version"]),
                make_finance_analyst_headers(DIRECTOR_USER_ID),
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
        )

        promotion_after = read_promotion(api, promotion_id)
        assert_money(
            promotion_after["consumed_deduction_amount"], 0.00,
            "consumed_deduction_amount",
        )
        assert_money(promotion_after["accrued_balance"], 3000.00, "accrued_balance")
        assert promotion_after["spend_status"] == SpendStatus.WITHIN_BUDGET.value
        assert promotion_after["version"] == promotion_before["version"]

        cell_after = read_allocation(api, context["allocation"]["id"])
        assert cell_after["posture"] == AllocationPosture.OPEN.value
        assert cell_after["overspend_event_count"] == 0

        customer_after = read_customer(api, context["customer"]["id"])
        assert customer_after["compliance_penalty_points"] == 0
        assert customer_after["trading_status"] == TradingStatus.ACTIVE.value

        unchanged = read_deduction(api, deduction["id"])
        assert unchanged["status"] == DeductionStatus.MATCHED.value
        assert unchanged["validated_amount"] is None
        assert unchanged["entitled_amount"] is None
