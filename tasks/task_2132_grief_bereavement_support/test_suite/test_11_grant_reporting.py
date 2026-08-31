"""Funder reporting: line selection, the pinned per-line rounding order and the
revision cycle."""

import pytest

from test_helpers import (
    GO,
    IC,
    PD,
    ApiErrorId,
    UNUSED_UUIDS,
    api_client,
    assert_grant_report,
    create_funding_allocation,
    create_grant_award,
    create_grant_report,
    create_meeting_space,
    create_remembrance_event,
    grant_award_version,
    make_grant_officer_headers,
    make_program_director_headers,
    read_grant_award,
    read_grant_report,
    read_funding_allocation,
    release_funding_allocation,
    set_clock,
    setup_submitted_grant_report,
    submit_grant_report,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_revision_cycle_counts_rounds_and_clears_the_submitting_operator():
    """PRD 3.9: "Submitting moves a `DRAFT` report to `SUBMITTED`, and requires the
    parent award to still be `ACTIVE` — submitting against a `CLOSED` award is
    refused with `ERR_GRANT_CLOSED`. Submission recomputes `line_count`,
    `direct_total_cents`, `indirect_total_cents`, `reported_total_cents` and
    `participants_served` from scratch, then stamps `submitted_by_user_id` with the
    acting operator's `X-User-ID` and `submitted_at` from the logical clock. A
    `GrantOfficer` may then return the report for revision, moving
    `SUBMITTED → RETURNED`, recording the free-text `return_reason` they supply and
    increasing `revision_index` by one. A `ProgramDirector` reopens a returned
    report by moving it `RETURNED → DRAFT`, which clears `submitted_by_user_id` and
    `submitted_at` and recomputes every total again against whatever the allocation
    ledger now says — so a report that sat in review while an allocation settled
    comes back with different numbers."
    PRD 3.9: "The cycle `DRAFT → SUBMITTED → RETURNED → DRAFT` may run as many
    rounds as the funder demands, and `revision_index` counts them."

    Design: Corner/state_machines/grant_report_return_and_revise_cycle_increments_revision_index
    """
    set_clock()
    award = create_grant_award(awarded_cents=100_000,
                               allowed_categories=["GROUP_PROGRAM"])
    report = create_grant_report(award["id"], user_id="pd-001")
    submitted = submit_grant_report(report["id"], user_id="pd-001")
    assert submitted["submitted_by_user_id"] == "pd-001"

    returned = validate_success(
        api_client.return_grant_report(
            report["id"], "Attach the participant roster.",
            make_grant_officer_headers("go-001")))
    assert returned["revision_index"] == 1

    revised = validate_success(
        api_client.revise_grant_report(
            report["id"], make_program_director_headers("pd-001")))
    assert revised["status"] == "DRAFT"

    refreshed = read_grant_report(report["id"])
    assert_grant_report(refreshed)
    assert refreshed["submitted_by_user_id"] is None
    assert refreshed["submitted_at"] is None
    assert refreshed["return_reason"] == "Attach the participant roster."
    assert refreshed["line_count"] == 0
    assert refreshed["reported_total_cents"] == 0


def test_released_allocations_never_appear_on_a_report():
    """PRD 3.9: "A report includes those funding allocations of its own award whose
    status is `COMMITTED` or `SETTLED` and whose effective date falls inside the
    report's inclusive window. An allocation's effective date is the calendar date
    of its `settled_at` when it has reached `SETTLED`, and the calendar date of its
    `created_at` otherwise. Allocations in `RELEASED` are excluded outright — a
    released commitment leaves no trace in any report, ever."
    PRD 3.9: "For each line, the reportable amount is the allocation's
    `settled_cents` when it has settled and its `provisional_cents` otherwise."

    Design: Corner/calculations/grant_report_lines_exclude_released_allocations
    """
    set_clock()
    space = create_meeting_space(name="Hall A", capacity=60,
                                 turnover_buffer_minutes=30)
    award = create_grant_award(awarded_cents=500_000,
                               allowed_categories=["REMEMBRANCE_EVENT"],
                               indirect_rate_bps=1200)
    kept_event = create_remembrance_event(space["id"], title="Kept Event",
                                          event_date="2026-10-05",
                                          direct_cost_cents=10_220)
    dropped_event = create_remembrance_event(space["id"], title="Dropped Event",
                                             event_date="2026-10-06",
                                             direct_cost_cents=10_220)
    kept = create_funding_allocation(award["id"], "REMEMBRANCE_EVENT",
                                     event_id=kept_event["id"],
                                     expected_grant_award_version=award["version"])
    dropped = create_funding_allocation(award["id"], "REMEMBRANCE_EVENT",
                                        event_id=dropped_event["id"])
    release_funding_allocation(dropped["id"])

    report = validate_success(
        api_client.create_grant_report(
            {"grant_award_id": award["id"], "period_start": "2026-09-01",
             "period_end": "2026-09-30"}, PD), 201)
    assert report["line_count"] == 1, (
        f"Expected the released line to be excluded, got {report['line_count']}")
    assert report["direct_total_cents"] == 11_446
    assert report["indirect_total_cents"] == 1_374
    assert report["reported_total_cents"] == 12_820
    assert report["participants_served"] == 0

    assert read_funding_allocation(dropped["id"])["status"] == "RELEASED"
    refreshed_award = read_grant_award(award["id"])
    assert refreshed_award["committed_cents"] == 11_446
    assert refreshed_award["available_cents"] == 488_554


def test_duplicate_award_references_and_overlapping_report_windows_are_refused():
    """PRD 3.9: "Award references are unique across the whole system: a second
    award carrying an `award_reference` that already exists is refused with
    `ERR_DUPLICATE_AWARD_REFERENCE`."
    PRD 3.9: "Windows on the same award must not overlap while they are still in
    play: if a report already exists for that award in status `DRAFT`, `SUBMITTED`
    or `RETURNED` whose window overlaps the requested one, the request is refused
    with `ERR_REPORT_PERIOD_OVERLAP`."

    Design: Corner/validations/duplicate_award_reference_and_overlapping_report_window_are_refused
    """
    set_clock()
    award = create_grant_award(funder_name="Hollis Foundation",
                               award_reference="HF-2026-UNIQ",
                               awarded_cents=100_000,
                               allowed_categories=["GROUP_PROGRAM"])
    create_grant_report(award["id"], period_start="2026-09-01",
                        period_end="2026-09-30")

    validate_error(
        api_client.create_grant_award(
            {"funder_name": "Other Funder", "award_reference": "HF-2026-UNIQ",
             "awarded_cents": 200_000, "allowed_categories": ["COUNSELING"],
             "period_start": "2026-01-01", "period_end": "2026-12-31",
             "indirect_rate_bps": 1000}, PD),
        ApiErrorId.ERR_DUPLICATE_AWARD_REFERENCE.value, 409)

    validate_error(
        api_client.create_grant_report(
            {"grant_award_id": award["id"], "period_start": "2026-09-15",
             "period_end": "2026-10-15"}, PD),
        ApiErrorId.ERR_REPORT_PERIOD_OVERLAP.value, 409)

    rows, meta = validate_paginated(
        api_client.list_grant_reports(PD, params={"grant_award_id": award["id"]}))
    assert meta["total_count"] == 1


def test_opening_a_report_over_an_unknown_award_is_not_found():
    """PRD 2.5: "Every entity identifier named inside the request body resolves to
    an existing record — otherwise the corresponding not-found error (404). This
    rung guards enrollment creation, counselling-referral creation,
    counselling-referral assignment, companion-match creation, cohort creation,
    remembrance-event creation, invitation creation, funding-allocation creation
    and grant-report creation."

    Design: Corner/errors/grant_report_create_with_unknown_award_returns_grant_not_found
    """
    set_clock()
    validate_error(
        api_client.create_grant_report(
            {"grant_award_id": UNUSED_UUIDS["grant"], "period_start": "2026-09-01",
             "period_end": "2026-09-30"}, PD),
        ApiErrorId.ERR_GRANT_NOT_FOUND.value, 404)


def test_submitting_an_unknown_report_is_not_found():
    """PRD 2.5: "Every resource named by a path segment exists, validated from left
    to right, so the leftmost missing segment determines the reported error —
    otherwise the corresponding not-found error (404)."

    Design: Corner/errors/grant_report_submit_with_unknown_id_returns_report_not_found
    """
    set_clock()
    validate_error(api_client.submit_grant_report(UNUSED_UUIDS["report"], PD),
                   ApiErrorId.ERR_REPORT_NOT_FOUND.value, 404)


def test_the_submitting_operator_may_not_also_accept_the_report():
    """PRD 2.1: "One additional authorisation rule stands apart from ownership.
    Accepting a submitted grant report is a segregation-of-duties boundary: the
    acting `GrantOfficer`'s `X-User-ID` must differ from the
    `submitted_by_user_id` recorded on the report. If they are equal, the
    acceptance is refused with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403."
    PRD 3.9: "Acceptance by a `GrantOfficer` moves the report
    `SUBMITTED → ACCEPTED`, which is terminal, and is subject to the
    segregation-of-duties rule of §2.1."

    Design: Corner/rbac/same_operator_submitting_and_accepting_a_report_hits_segregation_of_duties
    """
    set_clock()
    award, report = setup_submitted_grant_report(submitter_id="op-777")
    assert report["submitted_by_user_id"] == "op-777"

    validate_error(
        api_client.accept_grant_report(
            report["id"], make_grant_officer_headers("op-777")),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    accepted = validate_success(
        api_client.accept_grant_report(
            report["id"], make_grant_officer_headers("op-888")))
    assert accepted["status"] == "ACCEPTED"

    refreshed = read_grant_report(report["id"])
    assert refreshed["status"] == "ACCEPTED"
    assert refreshed["revision_index"] == 0


def _setup_three_equal_report_lines():
    """One award at 1200 basis points carrying three committed lines of 11446."""
    set_clock()
    space = create_meeting_space(name="Hall A", capacity=60,
                                 turnover_buffer_minutes=30)
    award = create_grant_award(awarded_cents=500_000,
                               allowed_categories=["REMEMBRANCE_EVENT"],
                               indirect_rate_bps=1200)
    allocations = []
    for index, event_date in enumerate(("2026-10-05", "2026-10-06", "2026-10-07"), 1):
        event = create_remembrance_event(
            space["id"], title=f"October Remembrance {index}",
            event_date=event_date, direct_cost_cents=10_220)
        allocations.append(create_funding_allocation(
            award["id"], "REMEMBRANCE_EVENT", event_id=event["id"]))
    return award, allocations


def test_indirect_totals_round_each_line_before_summing():
    """PRD 3.9: "The rounding order is pinned: round each line first, then sum the
    rounded per-line figures. The alternative reading — summing raw amounts and
    rounding the aggregate once — is explicitly not what this system does and
    produces a different answer whenever the per-line fractional remainders fail to
    cancel. Consider three lines each carrying a reportable amount of 11,446 cents
    against an award at 1200 basis points: each line's indirect amount is 1,373.52
    cents, which rounds to 1,374, and the three rounded figures sum to 4,122.
    Summing first would give 34,338 cents at twelve percent, or 4,120.56, rounding
    to 4,121 — one cent adrift, and the wrong answer."

    Design: Difficulty/combinatorial_formula/grant_report_indirect_rounded_per_line_then_summed
    """
    award, allocations = _setup_three_equal_report_lines()

    report = validate_success(
        api_client.create_grant_report(
            {"grant_award_id": award["id"], "period_start": "2026-09-01",
             "period_end": "2026-09-30"}, PD), 201)

    assert report["indirect_total_cents"] == 4_122, (
        f"Expected 4122 from per-line rounding, got {report['indirect_total_cents']}")
    assert report["indirect_total_cents"] != 4_121, (
        "summing the raw amounts before rounding is the rejected reading")


def test_report_totals_follow_from_the_selected_lines():
    """PRD 3.9: "The report's four money figures follow directly. `line_count` is
    the number of selected lines. `direct_total_cents` is the sum of the per-line
    reportable amounts. `indirect_total_cents` is the sum of the per-line rounded
    indirect amounts. `reported_total_cents` is `direct_total_cents` plus
    `indirect_total_cents`. Alongside the money sits an outcome count:
    `participants_served` is the number of distinct participants holding an
    enrollment in status `CONFIRMED`, `ATTENDING` or `COMPLETED` on any cohort
    funded by one of the included lines."
    PRD 3.9: "The report is created in status `DRAFT` with HTTP 201, its totals
    computed immediately, `submitted_by_user_id`, `submitted_at` and
    `return_reason` all null, and `revision_index` at zero."

    Design: Difficulty/combinatorial_formula/grant_report_indirect_rounded_per_line_then_summed
    """
    award, allocations = _setup_three_equal_report_lines()

    report = validate_success(
        api_client.create_grant_report(
            {"grant_award_id": award["id"], "period_start": "2026-09-01",
             "period_end": "2026-09-30"}, PD), 201)
    assert_grant_report(report)
    assert report["line_count"] == 3
    assert report["direct_total_cents"] == 34_338
    assert report["reported_total_cents"] == 38_460
    assert report["participants_served"] == 0
    assert report["status"] == "DRAFT"

    assert read_funding_allocation(allocations[0]["id"])["provisional_cents"] == 11_446
    refreshed_award = read_grant_award(award["id"])
    assert refreshed_award["committed_cents"] == 34_338
    assert refreshed_award["available_cents"] == 465_662
