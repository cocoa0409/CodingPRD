"""Tax deposit scheduling, statutory due dates, and late-penalty tests (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_deposit,
    create_run,
    create_settled_run,
    get_deposit,
    get_run,
    impound_run,
    run_version,
    set_clock,
    setup_active_client,
    submit_run,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_semiweekly_due_date_tuesday_paydate_vs_wednesday_paydate():
    """PRD §3.6: "For `SEMIWEEKLY` jurisdictions, when P falls on a Wednesday,
    Thursday, or Friday the due date is the next Wednesday strictly after P; when
    P falls on a Saturday, Sunday, Monday, or Tuesday the due date is the next
    Friday strictly after P."

    Design: Difficulty/boundary_precision_check/semiweekly_due_date_wednesday_paydate_vs_friday_paydate
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    # Tuesday 2026-09-01 -> Sat/Sun/Mon/Tue bucket -> next Friday 2026-09-04.
    tue = create_settled_run(
        client,
        pay_date="2026-09-01T00:00:00Z",
        period_start="2026-08-16T00:00:00Z",
        period_end="2026-08-31T00:00:00Z",
        gross_pay_cents=500000,
        total_tax_cents=100000,
    )
    dep_tue = create_deposit(tue["run"], jurisdiction["id"], 100000)
    # Wednesday 2026-09-02 -> Wed/Thu/Fri bucket -> next Wednesday 2026-09-09.
    wed = create_settled_run(
        client,
        pay_date="2026-09-02T00:00:00Z",
        period_start="2026-08-16T00:00:00Z",
        period_end="2026-08-31T00:00:00Z",
        gross_pay_cents=500000,
        total_tax_cents=100000,
    )
    dep_wed = create_deposit(wed["run"], jurisdiction["id"], 100000)
    assert dep_tue["due_date"][:10] == "2026-09-04"
    assert dep_wed["due_date"][:10] == "2026-09-09"
    assert dep_tue["due_date"][:10] != dep_wed["due_date"][:10]


def test_semiweekly_friday_paydate_due_next_wednesday():
    """PRD §3.6: "For `SEMIWEEKLY` jurisdictions, when P falls on a Wednesday,
    Thursday, or Friday the due date is the next Wednesday strictly after P."

    Design: Difficulty/boundary_precision_check/semiweekly_due_date_wednesday_paydate_vs_friday_paydate
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    # Friday 2026-09-04 -> next Wednesday strictly after P = 2026-09-09.
    fri = create_settled_run(
        client,
        pay_date="2026-09-04T00:00:00Z",
        period_start="2026-08-22T00:00:00Z",
        period_end="2026-09-04T00:00:00Z",
        gross_pay_cents=500000,
        total_tax_cents=100000,
    )
    dep = create_deposit(fri["run"], jurisdiction["id"], 100000)
    assert dep["due_date"][:10] == "2026-09-09"
    assert dep["due_date"].endswith("23:59:59Z") or "23:59:59" in dep["due_date"]


def test_monthly_frequency_due_is_15th_of_next_month():
    """PRD §3.6: "For `MONTHLY` jurisdictions, the due date is the 15th day of the
    month following P's month."
    PRD §3.6: "The `quarter` field is the quarter bucket of the pay date in the
    form 2026-Q3."

    Design: Corner/calculations/c_monthly_frequency_due_is_15th_of_next_month
    """
    from test_helpers import create_jurisdiction

    jurisdiction = create_jurisdiction(
        code="NY-NYS45", name="NY NYS-45", deposit_frequency="MONTHLY",
        underpayment_threshold_cents=100000,
    )
    setup = setup_active_client(jurisdiction=jurisdiction)
    client = setup["client"]
    built = create_settled_run(
        client,
        pay_date="2026-09-16T00:00:00Z",
        period_start="2026-09-01T00:00:00Z",
        period_end="2026-09-15T00:00:00Z",
        gross_pay_cents=800000,
        total_tax_cents=160000,
    )
    dep = create_deposit(built["run"], jurisdiction["id"], 160000)
    assert dep["due_date"][:10] == "2026-10-15"
    assert dep["quarter"] == "2026-Q3"


def test_quarterly_frequency_due_is_month_after_quarter_end():
    """PRD §3.6: "For `QUARTERLY` jurisdictions, the due date is the last day of
    the month following P's quarter — April 30 for Q1, July 31 for Q2, October 31
    for Q3, and January 31 of the following year for Q4."

    Design: Corner/calculations/c_quarterly_frequency_due_is_month_after_quarter_end
    """
    from test_helpers import create_jurisdiction

    jurisdiction = create_jurisdiction(
        code="CA-DE9", name="CA EDD DE9", deposit_frequency="QUARTERLY",
        underpayment_threshold_cents=250000,
    )
    setup = setup_active_client(jurisdiction=jurisdiction)
    client = setup["client"]
    built = create_settled_run(
        client,
        pay_date="2026-08-17T00:00:00Z",
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-15T00:00:00Z",
        gross_pay_cents=800000,
        total_tax_cents=160000,
    )
    dep = create_deposit(built["run"], jurisdiction["id"], 160000)
    assert dep["due_date"][:10] == "2026-10-31"
    assert dep["quarter"] == "2026-Q3"


def test_late_deposit_penalty_tier1_inclusive_at_five_days():
    """PRD §3.6: "The `penalty_exposure_cents` is zero when the deposit is on time;
    otherwise it is the deposit's `amount_cents` multiplied by the jurisdiction's
    tier rate, rounded half up to whole cents: `penalty_tier1_rate` when
    `late_days` is between 1 and 5 inclusive."
    PRD §3.6: "The tier boundaries are inclusive at the edges — exactly 5 days late
    is tier 1, exactly 6 is tier 2, exactly 15 is tier 2, exactly 16 is tier 3."

    Design: Difficulty/combinatorial_formula/late_deposit_penalty_tiered_threshold
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    # Friday 2026-09-04 pay date -> SEMIWEEKLY due Wednesday 2026-09-09.
    built = create_settled_run(
        client,
        pay_date="2026-09-04T00:00:00Z",
        period_start="2026-08-22T00:00:00Z",
        period_end="2026-09-04T00:00:00Z",
        gross_pay_cents=5000000,
        total_tax_cents=1000000,
    )
    dep = create_deposit(built["run"], jurisdiction["id"], 1000000)
    assert dep["due_date"][:10] == "2026-09-09"
    set_clock("2026-09-08T10:00:00Z")
    validate_success(
        api_client.submit_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    )
    # Confirm 2026-09-14: exactly 5 calendar days late -> tier 1.
    set_clock("2026-09-14T09:00:00Z")
    confirmed = validate_success(
        api_client.confirm_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert confirmed["late_days"] == 5
    assert confirmed["penalty_exposure_cents"] == 20000  # 1000000 * 0.02
    assert confirmed["penalty_exposure_cents"] != 50000  # tier 2 starts at 6 days


def test_late_deposit_penalty_tier2_at_six_days():
    """PRD §3.6: "`penalty_tier2_rate` when between 6 and 15 inclusive."
    PRD §3.6: "The tier boundaries are inclusive at the edges — exactly 5 days late
    is tier 1, exactly 6 is tier 2, exactly 15 is tier 2, exactly 16 is tier 3."

    Design: Difficulty/combinatorial_formula/late_deposit_penalty_tiered_threshold
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    built = create_settled_run(
        client,
        pay_date="2026-09-04T00:00:00Z",
        period_start="2026-08-22T00:00:00Z",
        period_end="2026-09-04T00:00:00Z",
        gross_pay_cents=5000000,
        total_tax_cents=1000000,
    )
    dep = create_deposit(built["run"], jurisdiction["id"], 1000000)
    set_clock("2026-09-08T10:00:00Z")
    validate_success(
        api_client.submit_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    )
    # Confirm 2026-09-15: exactly 6 calendar days late -> tier 2.
    set_clock("2026-09-15T09:00:00Z")
    confirmed = validate_success(
        api_client.confirm_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert confirmed["late_days"] == 6
    assert confirmed["penalty_exposure_cents"] == 50000  # 1000000 * 0.05


def test_late_deposit_penalty_rounding_half_up():
    """PRD §3.6: "otherwise it is the deposit's `amount_cents` multiplied by the
    jurisdiction's tier rate, rounded half up to whole cents."
    PRD §2.5: "Where a calculation multiplies a cent amount by a fractional rate —
    specifically the late-deposit penalty and the quarterly shortfall penalty —
    the product is rounded half up to the nearest whole cent, and the stored
    result is an integer."

    Design: Corner/calculations/c_late_deposit_penalty_rounding_half_up
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    built = create_settled_run(
        client,
        pay_date="2026-09-04T00:00:00Z",
        period_start="2026-08-22T00:00:00Z",
        period_end="2026-09-04T00:00:00Z",
        gross_pay_cents=1666665,
        total_tax_cents=333333,
    )
    dep = create_deposit(built["run"], jurisdiction["id"], 333333)
    set_clock("2026-09-08T10:00:00Z")
    validate_success(
        api_client.submit_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    )
    set_clock("2026-09-14T09:00:00Z")  # 5 days late -> tier 1
    confirmed = validate_success(
        api_client.confirm_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert confirmed["late_days"] == 5
    # 333333 * 0.02 = 6666.66 -> 6667 under round-half-up.
    assert confirmed["penalty_exposure_cents"] == 6667


def test_deposit_failure_reschedule_loop_accumulates_lateness():
    """PRD §3.6: "A failed deposit may be rescheduled back to `SCHEDULED`, which
    clears `submitted_at` but leaves `due_date` untouched — the due date is
    statutory and rescheduling never moves it, so the failure loop `SCHEDULED` →
    `SUBMITTED` → `FAILED` → `SCHEDULED` is unbounded and lateness accrues."

    Design: Difficulty/non_linear_state_machine/deposit_failure_reschedule_loop_accumulates_lateness
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    built = create_settled_run(
        client,
        pay_date="2026-09-04T00:00:00Z",
        period_start="2026-08-22T00:00:00Z",
        period_end="2026-09-04T00:00:00Z",
        gross_pay_cents=2500000,
        total_tax_cents=500000,
    )
    dep = create_deposit(built["run"], jurisdiction["id"], 500000)
    original_due = dep["due_date"]
    assert original_due[:10] == "2026-09-09"

    set_clock("2026-09-08T10:00:00Z")
    validate_success(api_client.submit_deposit(dep["id"], TEST_USERS["filer_alpha_headers"]))
    set_clock("2026-09-10T10:00:00Z")
    failed = validate_success(
        api_client.fail_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert failed["status"] == "FAILED"
    set_clock("2026-09-11T10:00:00Z")
    rescheduled = validate_success(
        api_client.reschedule_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert rescheduled["status"] == "SCHEDULED"
    assert rescheduled["due_date"] == original_due, "due_date is statutory and never moves"
    assert rescheduled.get("submitted_at") in (None, ""), "reschedule clears submitted_at"
    validate_success(api_client.submit_deposit(dep["id"], TEST_USERS["filer_alpha_headers"]))

    # Confirm 2026-09-21: 12 calendar days late -> tier 2 (6..15 inclusive).
    set_clock("2026-09-21T10:00:00Z")
    confirmed = validate_success(
        api_client.confirm_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["late_days"] == 12
    assert confirmed["penalty_exposure_cents"] == 25000  # 500000 * 0.05
    assert confirmed["due_date"] == original_due


def test_reschedule_does_not_move_due_date():
    """PRD §3.6: "A failed deposit may be rescheduled back to `SCHEDULED`, which
    clears `submitted_at` but leaves `due_date` untouched — the due date is
    statutory and rescheduling never moves it."

    Design: Difficulty/non_linear_state_machine/deposit_failure_reschedule_loop_accumulates_lateness
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    built = create_settled_run(client)
    dep = create_deposit(built["run"], jurisdiction["id"], 100000)
    original_due = dep["due_date"]
    validate_success(api_client.submit_deposit(dep["id"], TEST_USERS["filer_alpha_headers"]))
    validate_success(api_client.fail_deposit(dep["id"], TEST_USERS["filer_alpha_headers"]))
    rescheduled = validate_success(
        api_client.reschedule_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert rescheduled["due_date"] == original_due
    assert rescheduled["status"] == "SCHEDULED"


def test_deposit_uniqueness_window_per_run_jurisdiction():
    """PRD §3.6: "the same (`payroll_run_id`, `jurisdiction_id`) pair may not
    already have a deposit in `SCHEDULED` or `SUBMITTED` status, else
    `ERR_DUPLICATE_DEPOSIT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/deposit_uniqueness_window_per_run_jurisdiction
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    built = create_settled_run(client, gross_pay_cents=500000, total_tax_cents=100000)
    run = built["run"]
    dep1 = create_deposit(run, jurisdiction["id"], 100000)

    resp = api_client.create_deposit(
        run["id"],
        {
            "jurisdiction_id": jurisdiction["id"],
            "amount_cents": 100000,
            "expected_payroll_run_version": run_version(run["id"]),
        },
        TEST_USERS["filer_alpha_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_DEPOSIT, 409)

    # FAILED vacates the occupation window: a new deposit for the pair succeeds.
    validate_success(api_client.submit_deposit(dep1["id"], TEST_USERS["filer_alpha_headers"]))
    validate_success(api_client.fail_deposit(dep1["id"], TEST_USERS["filer_alpha_headers"]))
    dep2 = validate_success(
        api_client.create_deposit(
            run["id"],
            {
                "jurisdiction_id": jurisdiction["id"],
                "amount_cents": 100000,
                "expected_payroll_run_version": run_version(run["id"]),
            },
            TEST_USERS["filer_alpha_headers"],
        ),
        expected_status=201,
    )
    assert dep2["status"] == "SCHEDULED"
    assert get_deposit(dep1["id"])["status"] == "FAILED"


def test_submitted_deposit_still_occupies_pair_window():
    """PRD §3.6: "the same (`payroll_run_id`, `jurisdiction_id`) pair may not
    already have a deposit in `SCHEDULED` or `SUBMITTED` status, else
    `ERR_DUPLICATE_DEPOSIT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/deposit_uniqueness_window_per_run_jurisdiction
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    built = create_settled_run(client, gross_pay_cents=500000, total_tax_cents=100000)
    run = built["run"]
    dep1 = create_deposit(run, jurisdiction["id"], 100000)
    validate_success(api_client.submit_deposit(dep1["id"], TEST_USERS["filer_alpha_headers"]))
    resp = api_client.create_deposit(
        run["id"],
        {
            "jurisdiction_id": jurisdiction["id"],
            "amount_cents": 100000,
            "expected_payroll_run_version": run_version(run["id"]),
        },
        TEST_USERS["filer_alpha_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_DEPOSIT, 409)


def test_aggregate_deposit_cap_returns_exceeds_liability():
    """PRD §3.6: "the cumulative amount of the run's `SCHEDULED`, `SUBMITTED`, and
    `CONFIRMED` deposits — including the new one — must not exceed the run's
    `total_tax_cents`, else `ERR_DEPOSIT_EXCEEDS_LIABILITY` (HTTP 422)."

    Design: Corner/validations/v_aggregate_deposit_cap_returns_exceeds_liability
    """
    from test_helpers import create_jurisdiction, create_registration_payload, get_success_data

    j_fed = create_jurisdiction()  # FED-941 SEMIWEEKLY
    j_ca = create_jurisdiction(
        code="CA-DE9", name="CA EDD DE9", deposit_frequency="QUARTERLY",
        underpayment_threshold_cents=250000,
    )
    setup = setup_active_client(jurisdiction=j_fed)
    client = setup["client"]
    # Verify the CA registration too so nothing else interferes.
    reg_ca = get_success_data(
        api_client.create_registration(
            client["id"],
            create_registration_payload(jurisdiction_id=j_ca["id"]),
            TEST_USERS["onboarder_headers"],
        )
    )
    get_success_data(
        api_client.verify_registration(reg_ca["id"], TEST_USERS["onboarder_headers"])
    )
    built = create_settled_run(
        client, gross_pay_cents=1500000, total_tax_cents=300000
    )
    run = built["run"]
    create_deposit(run, j_fed["id"], 200000)
    resp = api_client.create_deposit(
        run["id"],
        {
            "jurisdiction_id": j_ca["id"],
            "amount_cents": 200000,
            "expected_payroll_run_version": run_version(run["id"]),
        },
        TEST_USERS["filer_alpha_headers"],
    )
    err = validate_error(resp, ApiErrorId.ERR_DEPOSIT_EXCEEDS_LIABILITY, 422)
    assert err["error_id"] != ApiErrorId.ERR_DUPLICATE_DEPOSIT.value


def test_deposit_exactly_at_liability_cap_allowed():
    """PRD §3.6: "the cumulative amount of the run's `SCHEDULED`, `SUBMITTED`, and
    `CONFIRMED` deposits — including the new one — must not exceed the run's
    `total_tax_cents`, else `ERR_DEPOSIT_EXCEEDS_LIABILITY` (HTTP 422)."

    Design: Corner/validations/v_aggregate_deposit_cap_returns_exceeds_liability
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    built = create_settled_run(client, gross_pay_cents=1000000, total_tax_cents=200000)
    run = built["run"]
    dep = validate_success(
        api_client.create_deposit(
            run["id"],
            {
                "jurisdiction_id": jurisdiction["id"],
                "amount_cents": 200000,
                "expected_payroll_run_version": run_version(run["id"]),
            },
            TEST_USERS["filer_alpha_headers"],
        ),
        expected_status=201,
    )
    assert dep["status"] == "SCHEDULED"


def test_occ_stale_client_version_on_deposit_create():
    """PRD §2.7: "Scheduling a tax deposit against a payroll run requires
    `expected_payroll_run_version` to equal that PayrollRun's current `version`.
    ... a caller whose last read of the run predates another deposit's scheduling
    is refused rather than serialized over the newer state."
    PRD §2.7: "a mismatch is always rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/l_occ_stale_client_version_on_deposit_create
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    built = create_settled_run(client, gross_pay_cents=1500000, total_tax_cents=300000)
    run = built["run"]
    stale_version = run["version"]
    create_deposit(run, jurisdiction["id"], 150000)  # bumps run version
    resp = api_client.create_deposit(
        run["id"],
        {
            "jurisdiction_id": jurisdiction["id"],
            "amount_cents": 150000,
            "expected_payroll_run_version": stale_version,
        },
        TEST_USERS["filer_alpha_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
    _, meta = validate_paginated(
        api_client.list_deposits(
            TEST_USERS["filer_alpha_headers"], params={"payroll_run_id": run["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_occ_current_version_on_deposit_create_accepted():
    """PRD §2.7: "Scheduling a tax deposit against a payroll run requires
    `expected_payroll_run_version` to equal that PayrollRun's current `version`."
    PRD §2.7: "a mismatch is always rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/l_occ_stale_client_version_on_deposit_create
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    built = create_settled_run(client, gross_pay_cents=1500000, total_tax_cents=300000)
    run = built["run"]
    dep = validate_success(
        api_client.create_deposit(
            run["id"],
            {
                "jurisdiction_id": jurisdiction["id"],
                "amount_cents": 150000,
                "expected_payroll_run_version": run_version(run["id"]),
            },
            TEST_USERS["filer_alpha_headers"],
        ),
        expected_status=201,
    )
    assert dep["status"] == "SCHEDULED"
    # Scheduling a deposit advances the run's version (PRD §2.4/§2.7).
    assert get_run(run["id"])["version"] == run["version"] + 1


def test_deposit_submit_blocked_on_pending_registration():
    """PRD §3.6: "Two preconditions guard submission, evaluated after the generic
    layers: the backing PayrollRun must be `SETTLED` — funds actually in the
    bureau account — else `ERR_FUNDS_NOT_SETTLED` (HTTP 409); and the
    JurisdictionRegistration for the (client, jurisdiction) pair must be
    `VERIFIED`, else `ERR_REGISTRATION_NOT_VERIFIED` (HTTP 422)."

    Design: Corner/errors/x_electronic_deposit_submit_blocked_on_pending_registration
    """
    from test_helpers import create_jurisdiction, create_registration_payload, get_success_data

    j_fed = create_jurisdiction()
    j_ca = create_jurisdiction(
        code="CA-DE9", name="CA EDD DE9", deposit_frequency="QUARTERLY",
        underpayment_threshold_cents=250000,
    )
    setup = setup_active_client(jurisdiction=j_fed)
    client = setup["client"]
    # CA registration exists but is left PENDING.
    get_success_data(
        api_client.create_registration(
            client["id"],
            create_registration_payload(jurisdiction_id=j_ca["id"]),
            TEST_USERS["onboarder_headers"],
        )
    )
    built = create_settled_run(client)
    dep = create_deposit(built["run"], j_ca["id"], 100000)
    resp = api_client.submit_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_NOT_VERIFIED, 422)
    assert get_deposit(dep["id"])["status"] == "SCHEDULED"


def test_deposit_submit_after_verification_succeeds():
    """PRD §3.6: "the JurisdictionRegistration for the (client, jurisdiction)
    pair must be `VERIFIED`, else `ERR_REGISTRATION_NOT_VERIFIED` (HTTP 422)."

    Design: Corner/errors/x_electronic_deposit_submit_blocked_on_pending_registration
    """
    from test_helpers import create_jurisdiction, create_registration_payload, get_success_data

    j_fed = create_jurisdiction()
    j_ca = create_jurisdiction(
        code="CA-DE9", name="CA EDD DE9", deposit_frequency="QUARTERLY",
        underpayment_threshold_cents=250000,
    )
    setup = setup_active_client(jurisdiction=j_fed)
    client = setup["client"]
    reg_ca = get_success_data(
        api_client.create_registration(
            client["id"],
            create_registration_payload(jurisdiction_id=j_ca["id"]),
            TEST_USERS["onboarder_headers"],
        )
    )
    built = create_settled_run(client)
    dep = create_deposit(built["run"], j_ca["id"], 100000)
    resp = api_client.submit_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_NOT_VERIFIED, 422)
    # After verification the same submission succeeds.
    get_success_data(
        api_client.verify_registration(reg_ca["id"], TEST_USERS["onboarder_headers"])
    )
    submitted = validate_success(
        api_client.submit_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert submitted["status"] == "SUBMITTED"
