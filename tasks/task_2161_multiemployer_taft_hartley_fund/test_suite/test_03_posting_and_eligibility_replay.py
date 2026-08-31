"""Posting a report, superseding its predecessor, and replaying welfare eligibility."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accrual_for,
    assert_coverage_month,
    coverage_month_keys,
    file_single_line_report,
    granted_coverage_months,
    list_coverage_months,
    make_employer_headers,
    post_report,
    read_employer,
    read_participant,
    read_report,
    revoked_coverage_months,
    setup_amendment_pair_ready_to_post,
    setup_employer_with_one_participant,
    setup_filed_single_line_report,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["fund_administrator_headers"]


def test_the_filing_axis_moves_while_the_payment_axis_stands_still(api):
    """PRD §3.6: "A report may be `POSTED` while still `UNPAID`, and may be
    `PAID_IN_FULL` while still only `SUBMITTED`; nothing about one axis
    constrains the other."
    PRD §3.6: "A remittance strictly greater than zero and strictly smaller than
    the outstanding balance adds itself to `amount_remitted_cents` and moves the
    report from `UNPAID` to `PARTIAL`."
    PRD §3.6: "A remittance exactly equal to the outstanding balance settles the
    report: `amount_remitted_cents` becomes `total_contributions_due_cents`,
    `paid_in_full_at` is stamped with the logical clock instant, and the payment
    state becomes `PAID_IN_FULL` — this same closing move is available from
    `UNPAID`, from `PARTIAL`, and from `DELINQUENT` alike, on identical terms."

    Design: Difficulty/non_linear_state_machine/report_filing_and_payment_axes_advance_independently
    """
    base = setup_filed_single_line_report()
    report_id = base["report"]["id"]
    employer_headers = make_employer_headers(base["employer"]["id"])

    after_partial = validate_success(
        api.remit_contribution_report(report_id, {"amount_cents": 50_000}, employer_headers)
    )
    assert after_partial["filing_status"] == "SUBMITTED"
    assert after_partial["payment_status"] == "PARTIAL"
    assert after_partial["amount_remitted_cents"] == 50_000

    after_post = validate_success(api.post_contribution_report(report_id, ADMIN))
    assert after_post["filing_status"] == "POSTED"
    assert after_post["payment_status"] == "PARTIAL", (
        "posting leaves the payment axis exactly where it stood"
    )

    after_settlement = validate_success(
        api.remit_contribution_report(report_id, {"amount_cents": 74_898}, employer_headers)
    )
    assert after_settlement["filing_status"] == "POSTED"
    assert after_settlement["payment_status"] == "PAID_IN_FULL"


def test_both_axes_leave_their_own_stamps_and_the_ledger_closes(api):
    """PRD §3.4: "The act of posting stamps `posted_at` with the logical clock
    instant, sets `filing_status` to `POSTED`, and increments the report's
    `version` by 1."
    PRD §3.6: "A remittance exactly equal to the outstanding balance settles the
    report: `amount_remitted_cents` becomes `total_contributions_due_cents`,
    `paid_in_full_at` is stamped with the logical clock instant, and the payment
    state becomes `PAID_IN_FULL` — this same closing move is available from
    `UNPAID`, from `PARTIAL`, and from `DELINQUENT` alike, on identical terms."
    PRD §3.6: "The first is unpaid contributions: across every contribution
    report of this employer whose filing state is not `SUPERSEDED` and whose
    payment state is `UNPAID`, `PARTIAL`, or `DELINQUENT`, add up the report's
    `total_contributions_due_cents` less its `amount_remitted_cents`."

    Design: Difficulty/non_linear_state_machine/report_filing_and_payment_axes_advance_independently
    """
    base = setup_filed_single_line_report()
    report_id = base["report"]["id"]
    employer_headers = make_employer_headers(base["employer"]["id"])

    api.remit_contribution_report(report_id, {"amount_cents": 50_000}, employer_headers)
    post_report(report_id)
    api.remit_contribution_report(report_id, {"amount_cents": 74_898}, employer_headers)

    settled = read_report(report_id)
    assert settled["amount_remitted_cents"] == 124898
    assert settled["total_contributions_due_cents"] == 124898
    assert settled["posted_at"] is not None, "posted_at is stamped by the post"
    assert settled["paid_in_full_at"] is not None, "paid_in_full_at is stamped by the settlement"

    participant = read_participant(base["participant"]["id"])
    assert participant["credited_hours_total"] == 151.30

    employer = read_employer(base["employer"]["id"])
    assert employer["cumulative_delinquent_cents"] == 0, (
        "a fully remitted report leaves nothing outstanding"
    )


def test_the_amendment_leaves_exactly_its_own_hours_credited(api):
    """PRD §3.4: "The first hop applies only to amendments: if
    `amends_report_id` is non-null, the report it names moves from `POSTED` to
    `SUPERSEDED` and its own `version` increments by 1."
    PRD §3.4: "Supersession is how an amendment displaces its predecessor —
    every downstream aggregate in this system reads contribution lines only from
    reports whose filing state is `POSTED`, so the superseded report's hours
    silently leave every total, every coverage grant and every accrual the
    moment its state changes."
    PRD §3.4: "**Step four totals**: the participant's `credited_hours_total` is
    the sum of the hours across contribution events, rounded half up to two
    decimals, and `reciprocal_hours_total` is the sum of the hours across
    reciprocal events, rounded half up to two decimals the same way."

    Design: Difficulty/compensating_invariant/amendment_supersede_conserves_credited_hours
    """
    base = setup_amendment_pair_ready_to_post()
    participant_id = base["participant"]["id"]

    before = read_participant(participant_id)
    assert before["credited_hours_total"] == 151.30
    assert before["hour_bank_hours"] == 31.30
    assert before["coverage_through_month"] == "2026-05"

    post_report(base["amendment"]["id"])

    assert read_report(base["original"]["id"])["filing_status"] == "SUPERSEDED"
    assert read_report(base["amendment"]["id"])["filing_status"] == "POSTED"

    after = read_participant(participant_id)
    assert after["credited_hours_total"] == 100.00, (
        "exactly the hours of the one report still POSTED, with no residue"
    )
    assert after["hour_bank_hours"] == 100.00
    assert after["forfeited_hours_total"] == 0.00


def test_the_amendment_revokes_the_coverage_its_predecessor_had_bought(api):
    """PRD §3.4: "**Step zero wipes.** Every coverage month of this participant
    whose `status` is `GRANTED` is set to `REVOKED`; `hour_bank_hours` is reset
    to 0, `forfeited_hours_total` is reset to 0, and `coverage_through_month` is
    set to null. Revoked rows are never deleted — they remain readable as the
    historical record of grants the fund has withdrawn."
    PRD §3.4: "The third hop rewrites each replayed participant's
    `coverage_through_month` to the highest coverage month the replay granted, or
    to null when the replay granted none."
    PRD §3.1: "A participant's `eligibility_status` is never stored as a decision
    made at write time — it is derived every time the participant is read, and
    reads `ELIGIBLE` exactly when `coverage_through_month` is non-null and is not
    earlier than the logical clock's own year-and-month key, and `NOT_ELIGIBLE`
    otherwise."

    Design: Difficulty/compensating_invariant/amendment_supersede_conserves_credited_hours
    """
    base = setup_amendment_pair_ready_to_post()
    participant_id = base["participant"]["id"]

    post_report(base["amendment"]["id"])

    participant = read_participant(participant_id)
    assert participant["coverage_through_month"] is None, (
        "100.00 hours buys no whole 120-hour coverage month"
    )
    assert participant["eligibility_status"] == "NOT_ELIGIBLE"

    assert granted_coverage_months(participant_id) == []
    revoked = revoked_coverage_months(participant_id)
    assert len(revoked) == 1
    assert_coverage_month(revoked[0])
    assert revoked[0]["coverage_month"] == "2026-05"
    assert revoked[0]["granting_report_id"] == base["original"]["id"]

    accrual = accrual_for(participant_id, 2026)
    assert accrual["hours_credited"] == 100.00
    assert accrual["pension_credit"] == 0.00

    employer = read_employer(base["employer"]["id"])
    assert employer["cumulative_delinquent_cents"] == 82550, (
        "the superseded report has left the ledger entirely"
    )


def test_posting_a_report_a_second_time_is_refused_and_credits_nothing_twice(api):
    """PRD §3.4: "Posting requires the report's `filing_status` to be
    `SUBMITTED` — a report already `POSTED` or already `SUPERSEDED` is refused
    with `ERR_REPORT_ALREADY_POSTED` — requires the report to carry at least one
    line, and requires that the employer has not since withdrawn."
    PRD §3.4: "The number of months this event buys is the smaller of two
    quantities: the available hours divided by the fund's
    `hours_per_coverage_month` and rounded down to a whole number, and the
    allowance floored at zero."

    Design: Corner/state_machines/report_post_twice_returns_report_already_posted
    """
    base = setup_employer_with_one_participant()
    report = file_single_line_report(
        base["employer"]["id"], base["participant"]["id"], "2026-03", 100.00
    )
    post_report(report["id"])

    validate_error(
        api.post_contribution_report(report["id"], ADMIN),
        ApiErrorId.ERR_REPORT_ALREADY_POSTED.value,
    )

    participant = read_participant(base["participant"]["id"])
    assert participant["credited_hours_total"] == 100.00, "not doubled to 200.00"
    assert participant["hour_bank_hours"] == 100.00
    assert participant["coverage_through_month"] is None
    assert granted_coverage_months(base["participant"]["id"]) == []


def test_a_still_submitted_report_contributes_nothing_to_the_replay(api):
    """PRD §3.4: "**Step one builds the credit-event list.** One event is created
    for every contribution line naming this participant whose owning report has
    filing state `POSTED`, carrying the owning report's `work_period` as its
    month, the line's `hours`, the owning report's identifier, and a kind of
    contribution."
    PRD §3.4: "Lines on reports that are merely `SUBMITTED`, and lines on reports
    that are `SUPERSEDED`, contribute nothing."
    PRD §3.3: "Reports may be listed and filtered by `employer_id`, by
    `amends_report_id`, by `filing_status`, by `payment_status`, by
    `work_period`, and by `origin`; the lines of one report may be listed on
    their own, and a participant's lines across every report may be listed and
    narrowed with a `report_id` filter."

    Design: Corner/calculations/eligibility_replay_counts_only_posted_report_lines
    """
    base = setup_employer_with_one_participant(name="Filing Filter Fund", ein="36-5000002")
    participant_id = base["participant"]["id"]
    january = file_single_line_report(
        base["employer"]["id"], participant_id, "2026-01", 130.00, 520_000
    )
    february = file_single_line_report(
        base["employer"]["id"], participant_id, "2026-02", 200.00, 800_000
    )

    post_report(january["id"])

    assert read_report(february["id"])["filing_status"] == "SUBMITTED"

    participant = read_participant(participant_id)
    assert participant["credited_hours_total"] == 130.00, "the SUBMITTED 200.00 hours do not count"
    assert participant["hour_bank_hours"] == 10.00

    granted = granted_coverage_months(participant_id)
    assert len(granted) == 1
    assert granted[0]["coverage_month"] == "2026-03"
    assert granted[0]["granting_report_id"] == january["id"]

    assert accrual_for(participant_id, 2026)["hours_credited"] == 130.00

    _lines, line_meta = validate_paginated(
        api.list_participant_contribution_lines(participant_id, ADMIN)
    )
    assert line_meta["total_count"] == 2, "lines exist on both reports regardless of filing state"


def test_leftover_hours_above_the_bank_cap_are_forfeited(api):
    """PRD §3.4: "Any leftover in excess of the fund's `bank_cap_hours` is
    forfeited: that excess, floored at zero, is added to the participant's
    `forfeited_hours_total`, and the participant's `hour_bank_hours` becomes the
    smaller of `bank_cap_hours` and the leftover."
    PRD §3.4: "The participant's outstanding advance is the number of their
    coverage months that are currently `GRANTED` and whose month key is strictly
    later than the logical clock's own year-and-month key; the allowance is the
    fund's `max_advance_coverage_months` less that outstanding count."
    PRD §3.4: "Starting at that month, mint as many consecutive coverage months
    as the event bought, each with `status` `GRANTED`, each with `hours_applied`
    equal to the fund's `hours_per_coverage_month`, and each with
    `granting_report_id` set to the event's report identifier — which is null for
    a reciprocal event, since no report granted it."
    PRD §3.4: "The `source` of each minted row is `RECIPROCAL` when the event
    came from a reciprocity transfer; otherwise it is `CURRENT_HOURS` when the
    event's own hours were at least `hours_per_coverage_month`, and `BANK_DRAW`
    when they were not, because in that case the purchase was only possible by
    drawing on hours banked earlier."

    Design: Corner/calculations/bank_cap_forfeits_hours_above_four_hundred_eighty
    """
    base = setup_employer_with_one_participant(
        clock="2026-05-01T00:00:00Z", name="Bank Cap Fund", ein="36-5000003"
    )
    participant_id = base["participant"]["id"]
    report = file_single_line_report(
        base["employer"]["id"], participant_id, "2026-03", 2000.00, 8_000_000
    )

    posted = post_report(report["id"])

    assert posted["total_contributions_due_cents"] == 1651000

    participant = read_participant(participant_id)
    assert participant["credited_hours_total"] == 2000.00
    assert participant["hour_bank_hours"] == 480.00, "the cap keeps only 480.00 of the 560.00 left"
    assert participant["forfeited_hours_total"] == 80.00
    assert participant["coverage_through_month"] == "2027-04"
    assert participant["eligibility_status"] == "ELIGIBLE"

    granted = granted_coverage_months(participant_id)
    assert len(granted) == 12, "the advance allowance stops the grant at twelve months"
    assert coverage_month_keys(granted) == [
        "2026-05",
        "2026-06",
        "2026-07",
        "2026-08",
        "2026-09",
        "2026-10",
        "2026-11",
        "2026-12",
        "2027-01",
        "2027-02",
        "2027-03",
        "2027-04",
    ]
    for row in granted:
        assert row["hours_applied"] == 120
        assert row["source"] == "CURRENT_HOURS"


def test_coverage_month_provenance_survives_the_amendment_replay(api):
    """PRD §3.4: "Coverage months are readable individually and as a list,
    filterable by `participant_id`, by `granting_report_id`, by `status`, by
    `coverage_month`, and by `source`."
    PRD §3.4: "**Step zero wipes.** Every coverage month of this participant
    whose `status` is `GRANTED` is set to `REVOKED`; `hour_bank_hours` is reset
    to 0, `forfeited_hours_total` is reset to 0, and `coverage_through_month` is
    set to null. Revoked rows are never deleted — they remain readable as the
    historical record of grants the fund has withdrawn."

    Design: Corner/endpoints/coverage_month_list_filters_by_participant_status_and_granting_report
    """
    base = setup_employer_with_one_participant(name="Provenance Fund", ein="36-8000003")
    participant_id = base["participant"]["id"]
    original = file_single_line_report(
        base["employer"]["id"], participant_id, "2026-03", 300.00, 1_200_000
    )
    post_report(original["id"])
    amendment = file_single_line_report(
        base["employer"]["id"],
        participant_id,
        "2026-03",
        250.00,
        1_000_000,
        amends_report_id=original["id"],
    )

    post_report(amendment["id"])

    from_original = list_coverage_months(granting_report_id=original["id"], limit=100)
    assert len(from_original) == 2
    assert all(row["status"] == "REVOKED" for row in from_original)

    from_amendment = list_coverage_months(
        granting_report_id=amendment["id"], status="GRANTED", limit=100
    )
    assert coverage_month_keys(from_amendment) == ["2026-05", "2026-06"]

    everything = list_coverage_months(participant_id=participant_id, limit=100)
    assert len(everything) == 4

    may_rows = list_coverage_months(
        participant_id=participant_id, coverage_month="2026-05", limit=100
    )
    assert len(may_rows) == 2
    assert {row["status"] for row in may_rows} == {"GRANTED", "REVOKED"}

    participant = read_participant(participant_id)
    assert participant["credited_hours_total"] == 250.00
    assert participant["hour_bank_hours"] == 10.00
    assert participant["coverage_through_month"] == "2026-06"


def test_the_whole_posting_cascade_is_readable_on_the_very_next_call(api):
    """PRD §2.9: "There is no deferred settlement, no background job, and no
    eventual consistency: a read issued immediately after a write observes the
    fully-cascaded state."
    PRD §2.9: "When they do, every downstream figure named in the workflow is
    recomputed inside the same request, before the response is written, and every
    mutated row has its `updated_at` refreshed and its `version` incremented."
    PRD §3.5: "Under `HOURS_BASED`, the year's `pension_credit` is the countable
    hours divided by 250 and rounded down to a whole number of quarter-credits —
    each quarter-credit worth 0.25 — with the result capped at a full credit of
    1.00; and the year counts as a year of vesting service, setting
    `vesting_year_earned` to true, when the countable hours are **at least** 870,
    an inclusive threshold rather than a strict one."

    Design: Corner/consistency_model/posting_cascade_is_visible_immediately_in_the_same_request_cycle
    """
    base = setup_employer_with_one_participant(name="Immediate Fund", ein="36-9500001")
    participant_id = base["participant"]["id"]
    report = file_single_line_report(
        base["employer"]["id"], participant_id, "2026-03", 300.00, 1_200_000
    )

    posted = validate_success(api.post_contribution_report(report["id"], ADMIN))

    assert posted["filing_status"] == "POSTED"
    assert posted["total_contributions_due_cents"] == 247650
    assert posted["posted_at"] is not None

    participant = validate_success(api.get_participant(participant_id, ADMIN))
    assert participant["credited_hours_total"] == 300.00
    assert participant["hour_bank_hours"] == 60.00
    assert participant["coverage_through_month"] == "2026-06"
    assert participant["eligibility_status"] == "ELIGIBLE"

    assert coverage_month_keys(granted_coverage_months(participant_id)) == [
        "2026-05",
        "2026-06",
    ]

    accruals, accrual_meta = validate_paginated(
        api.list_pension_accruals(participant_id, ADMIN)
    )
    assert accrual_meta["total_count"] == 1
    assert accruals[0]["plan_year"] == 2026
    assert accruals[0]["hours_credited"] == 300.00
    assert accruals[0]["pension_credit"] == 0.25
    assert accruals[0]["accrual_status"] == "OPEN"
