"""The ops-run checkpoint: delinquency sweeps, suspension and the waiver that lifts it."""

from test_helpers import (
    TEST_USERS,
    create_employer,
    create_fund,
    create_participant,
    file_single_line_report,
    list_report_assessments,
    read_employer,
    read_fund,
    read_report,
    run_collections,
    set_clock,
    setup_ld_waiver_ready_to_tally,
    setup_three_reports_past_grace,
    tally_motion,
    validate_success,
)

ADMIN = TEST_USERS["fund_administrator_headers"]


def test_the_first_sweep_flips_every_overdue_report_to_delinquent(api):
    """PRD §3.10: "**The first sweep identifies delinquency.** Every contribution
    report of this fund's employers whose payment state is `UNPAID` or
    `PARTIAL`, whose filing state is not `SUPERSEDED`, and whose `due_date` plus
    the fund's `grace_days` now lies strictly in the past relative to the logical
    clock date, is swept into `DELINQUENT`."
    PRD §3.10: "each invocation increments the fund's `collections_run_index` by
    1 and reports what it did, returning `reports_marked_delinquent`,
    `installments_marked_missed`, `installments_defaulted`,
    `employers_suspended`, `accruals_finalized`, and the new
    `collections_run_index`."
    PRD §3.6: "A report may be `POSTED` while still `UNPAID`, and may be
    `PAID_IN_FULL` while still only `SUBMITTED`; nothing about one axis
    constrains the other."

    Design: Difficulty/transitive_cascade/run_collections_delinquency_suspension_cascade
    """
    base = setup_three_reports_past_grace()

    summary = validate_success(api.run_collections(base["fund"]["id"], ADMIN))

    assert summary["reports_marked_delinquent"] == 3
    assert summary["employers_suspended"] == 1
    assert summary["collections_run_index"] == 1

    for report in base["reports"]:
        stored = read_report(report["id"])
        assert stored["payment_status"] == "DELINQUENT"
        assert stored["filing_status"] == "SUBMITTED", (
            "the sweep touches the payment axis only"
        )


def test_three_delinquent_reports_suspend_the_employer_and_count_on_the_fund(api):
    """PRD §3.10: "Second, because that report flipped, the owning employer's
    `delinquency_strikes` increases by 1 and its `cumulative_delinquent_cents` is
    recomputed. Third, because `delinquency_strikes` has reached three, the
    employer's `status` becomes `SUSPENDED`. Fourth, because an employer entered
    suspension, the fund's `suspended_employer_count` is recomputed."
    PRD §3.10: "Strikes count distinct reports swept into delinquency and are
    wiped back to 0 only when the employer's ledger returns to 0 — through
    remittance, through settlement, or through a carried waiver motion — at which
    point the employer also leaves suspension."
    PRD §3.6: "The first is unpaid contributions: across every contribution
    report of this employer whose filing state is not `SUPERSEDED` and whose
    payment state is `UNPAID`, `PARTIAL`, or `DELINQUENT`, add up the report's
    `total_contributions_due_cents` less its `amount_remitted_cents`."

    Design: Difficulty/transitive_cascade/run_collections_delinquency_suspension_cascade
    """
    base = setup_three_reports_past_grace()

    run_collections(base["fund"]["id"])

    employer = read_employer(base["employer"]["id"])
    assert employer["delinquency_strikes"] == 3
    assert employer["cumulative_delinquent_cents"] == 247650, "three reports of 82550"
    assert employer["status"] == "SUSPENDED"

    fund = read_fund(base["fund"]["id"])
    assert fund["suspended_employer_count"] == 1


def test_a_carried_waiver_moves_the_assessment_to_waived_for_its_full_total(api):
    """PRD §3.2: "First, the referenced delinquency assessment moves to `WAIVED`
    and its `waived_cents` is set to that assessment's own `total_cents`. Second,
    because a waived assessment leaves the employer's ledger sum entirely, the
    employer's `cumulative_delinquent_cents` is recomputed and falls by exactly
    the waived amount."
    PRD §3.2: "Otherwise the party's bloc position is `FOR` when its `FOR` count
    exceeds its `AGAINST` count, `AGAINST` when its `AGAINST` count exceeds its
    `FOR` count, and `TIED` when the two counts are equal."
    PRD §3.2: "If both blocs read `FOR`, the motion becomes `CARRIED`."

    Design: Difficulty/compensating_invariant/ld_waiver_conserves_employer_delinquency_ledger
    """
    base = setup_ld_waiver_ready_to_tally()

    before = read_employer(base["employer"]["id"])
    assert before["cumulative_delinquent_cents"] == 100281
    assert before["status"] == "SUSPENDED"

    motion = tally_motion(base["motion"]["id"])

    assert motion["union_bloc_position"] == "FOR"
    assert motion["employer_bloc_position"] == "FOR"
    assert motion["status"] == "CARRIED"

    rows = list_report_assessments(base["reports"][2]["id"])
    waived = [row for row in rows if row["id"] == base["assessment"]["id"]][0]
    assert waived["status"] == "WAIVED"
    assert waived["waived_cents"] == 100281
    assert waived["settlement_amount_cents"] is None

    after = read_employer(base["employer"]["id"])
    assert after["cumulative_delinquent_cents"] == 0, (
        "the ledger fell by exactly 100281 with no residual cent"
    )
    assert before["cumulative_delinquent_cents"] - after["cumulative_delinquent_cents"] == 100281


def test_the_waiver_that_zeroes_the_ledger_lifts_the_suspension(api):
    """PRD §3.2: "Third, if that recomputation brings the ledger to 0 while the
    employer's `status` is `SUSPENDED`, the employer returns to `ACTIVE` and its
    `delinquency_strikes` resets to 0. Fourth, because an employer left
    suspension, the fund's `suspended_employer_count` is recomputed."
    PRD §3.6: "A remittance exactly equal to the outstanding balance settles the
    report: `amount_remitted_cents` becomes `total_contributions_due_cents`,
    `paid_in_full_at` is stamped with the logical clock instant, and the payment
    state becomes `PAID_IN_FULL` — this same closing move is available from
    `UNPAID`, from `PARTIAL`, and from `DELINQUENT` alike, on identical terms."

    Design: Difficulty/compensating_invariant/ld_waiver_conserves_employer_delinquency_ledger
    """
    base = setup_ld_waiver_ready_to_tally()

    tally_motion(base["motion"]["id"])

    employer = read_employer(base["employer"]["id"])
    assert employer["status"] == "ACTIVE"
    assert employer["delinquency_strikes"] == 0

    fund = read_fund(base["fund"]["id"])
    assert fund["suspended_employer_count"] == 0

    for report in base["reports"]:
        stored = read_report(report["id"])
        assert stored["payment_status"] == "PAID_IN_FULL"
        assert stored["amount_remitted_cents"] == 82550


def test_a_run_over_a_quiet_fund_reports_zeroes_and_still_advances_the_index(api):
    """PRD §3.10: "The run is idempotent only in the sense that it acts on
    whatever the clock now justifies; each invocation increments the fund's
    `collections_run_index` by 1 and reports what it did, returning
    `reports_marked_delinquent`, `installments_marked_missed`,
    `installments_defaulted`, `employers_suspended`, `accruals_finalized`, and
    the new `collections_run_index`."
    PRD §3.1: "A freshly registered employer opens with `status` `ACTIVE`,
    `delinquency_strikes` at 0 and `cumulative_delinquent_cents` at 0."

    Design: Corner/endpoints/run_collections_on_a_quiet_fund_returns_zero_counts_and_bumps_the_index
    """
    set_clock()
    fund = create_fund(name="Quiet Fund", ein="36-8000001")
    employer = create_employer(fund["id"])

    first = validate_success(api.run_collections(fund["id"], ADMIN))
    assert first["reports_marked_delinquent"] == 0
    assert first["installments_marked_missed"] == 0
    assert first["installments_defaulted"] == 0
    assert first["employers_suspended"] == 0
    assert first["accruals_finalized"] == 0
    assert first["collections_run_index"] == 1

    second = validate_success(api.run_collections(fund["id"], ADMIN))
    assert second["collections_run_index"] == 2

    fund_now = read_fund(fund["id"])
    assert fund_now["collections_run_index"] == 2
    assert fund_now["suspended_employer_count"] == 0

    employer_now = read_employer(employer["id"])
    assert employer_now["status"] == "ACTIVE"
    assert employer_now["delinquency_strikes"] == 0


def test_the_untouched_clock_reads_august_and_drives_the_sweep(api):
    """PRD §2.5: "The server keeps a logical clock rather than reading wall-clock
    time. Before any client has set it, the logical clock reads exactly
    `2026-08-01T00:00:00Z`, and it never falls back to real time."
    PRD §3.10: "**The first sweep identifies delinquency.** Every contribution
    report of this fund's employers whose payment state is `UNPAID` or
    `PARTIAL`, whose filing state is not `SUPERSEDED`, and whose `due_date` plus
    the fund's `grace_days` now lies strictly in the past relative to the logical
    clock date, is swept into `DELINQUENT`."
    PRD §3.3: "Its `due_date` is computed at intake as the twentieth day of the
    month following its `work_period` — a report for hours worked in a given
    month is due on the twentieth of the next one."

    Design: Corner/endpoints/logical_clock_defaults_to_2026_08_01_before_any_set_call
    """
    fund = create_fund(name="Default Clock Fund", ein="36-8000002")
    employer = create_employer(fund["id"])
    participant = create_participant(fund["id"])
    report = file_single_line_report(employer["id"], participant["id"], "2026-05", 100.00)

    assert report["due_date"] == "2026-06-20"

    summary = validate_success(api.run_collections(fund["id"], ADMIN))

    assert summary["reports_marked_delinquent"] == 1
    assert read_report(report["id"])["payment_status"] == "DELINQUENT"

    employer_now = read_employer(employer["id"])
    assert employer_now["delinquency_strikes"] == 1
    assert employer_now["status"] == "ACTIVE", "one strike is short of the three-strike limit"
    assert employer_now["cumulative_delinquent_cents"] == 82550
