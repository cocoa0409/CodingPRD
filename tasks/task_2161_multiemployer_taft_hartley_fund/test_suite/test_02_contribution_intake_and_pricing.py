"""Filing a contribution report, pricing its hours, and guarding its intake."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_contribution_line,
    assert_contribution_report,
    contribution_line_payload,
    create_contribution_report_payload,
    employer_version,
    file_single_line_report,
    line_for_participant,
    list_report_lines,
    make_employer_headers,
    read_employer,
    read_report,
    setup_employer_with_one_participant,
    setup_employer_with_three_participants,
    setup_intake_guard_scenario,
    three_line_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["fund_administrator_headers"]


def _file_three_line_report(api, base):
    payload = create_contribution_report_payload(
        base["employer"]["id"],
        "2026-03",
        employer_version(base["employer"]["id"]),
        three_line_payload(base["participants"]),
    )
    return validate_success(
        api.create_contribution_report(
            payload, make_employer_headers(base["employer"]["id"])
        ),
        201,
    )


def test_each_line_is_rounded_to_whole_cents_before_the_lines_are_summed(api):
    """PRD §3.3: "Round that per-line result half up to a whole number of cents
    and store it as the line's `contribution_cents`. **Only then** sum the
    rounded line amounts to obtain the report's
    `total_contributions_due_cents`."
    PRD §3.3: "Summing the unrounded line values and rounding the total
    afterwards is not an equivalent computation and will differ by whole cents
    on realistic filings."
    PRD §3.3: "The multiplier is 10,000 basis points for a `JOURNEYMAN` line,
    which is to say the full bargained rate; 5,000 basis points for an
    `APPRENTICE` line, which is half the rate; and 12,500 basis points for a
    `FOREMAN` line, which is the rate and a quarter."

    Design: Difficulty/combinatorial_formula/contribution_due_rounds_per_line_before_summing
    """
    base = setup_employer_with_three_participants()

    report = _file_three_line_report(api, base)

    assert_contribution_report(report)
    assert report["total_contributions_due_cents"] == 357668, (
        "the three rounded line amounts 124898 + 61376 + 171394 sum to 357668"
    )
    assert report["total_contributions_due_cents"] != 357669


def test_each_contribution_line_carries_its_own_rounded_cents(api):
    """PRD §3.3: "For each line, take the line's `hours`, multiply by the
    employer's `contribution_rate_millicents_per_hour`, multiply again by the
    basis-point multiplier that the line's `work_classification` selects, and
    divide the product by ten million."
    PRD §3.3: "Round that per-line result half up to a whole number of cents and
    store it as the line's `contribution_cents`. **Only then** sum the rounded
    line amounts to obtain the report's `total_contributions_due_cents`."
    PRD §3.3: "Separately, the report's `total_hours_reported` is the sum of the
    `hours` on its lines, rounded half up to two decimals."

    Design: Difficulty/combinatorial_formula/contribution_due_rounds_per_line_before_summing
    """
    base = setup_employer_with_three_participants()

    report = _file_three_line_report(api, base)

    lines = list_report_lines(report["id"])
    assert len(lines) == 3
    for line in lines:
        assert_contribution_line(line)
        assert line["report_id"] == report["id"]

    journeyman = line_for_participant(report["id"], base["participants"][0]["id"])
    apprentice = line_for_participant(report["id"], base["participants"][1]["id"])
    foreman = line_for_participant(report["id"], base["participants"][2]["id"])

    assert journeyman["contribution_cents"] == 124898, "151.30 hours at 10000 bps"
    assert apprentice["contribution_cents"] == 61376, "148.70 hours at 5000 bps"
    assert foreman["contribution_cents"] == 171394, "166.10 hours at 12500 bps"
    assert report["total_hours_reported"] == 466.10


def test_the_class_multipliers_halve_and_quarter_the_bargained_rate(api):
    """PRD §3.3: "The multiplier is 10,000 basis points for a `JOURNEYMAN` line,
    which is to say the full bargained rate; 5,000 basis points for an
    `APPRENTICE` line, which is half the rate; and 12,500 basis points for a
    `FOREMAN` line, which is the rate and a quarter."
    PRD §3.3: "Round that per-line result half up to a whole number of cents and
    store it as the line's `contribution_cents`. **Only then** sum the rounded
    line amounts to obtain the report's `total_contributions_due_cents`."

    Design: Corner/calculations/class_multipliers_price_apprentice_at_half_and_foreman_at_one_and_a_quarter
    """
    base = setup_employer_with_three_participants(
        name="Multiplier Fund", ein="36-5000006"
    )
    participants = base["participants"]

    payload = create_contribution_report_payload(
        base["employer"]["id"],
        "2026-03",
        employer_version(base["employer"]["id"]),
        [
            contribution_line_payload(participants[0]["id"], 100.00, 400_000, "JOURNEYMAN"),
            contribution_line_payload(participants[1]["id"], 100.00, 400_000, "APPRENTICE"),
            contribution_line_payload(participants[2]["id"], 100.00, 400_000, "FOREMAN"),
        ],
    )
    report = validate_success(api.create_contribution_report(payload, ADMIN), 201)

    assert line_for_participant(report["id"], participants[0]["id"])["contribution_cents"] == 82550
    assert line_for_participant(report["id"], participants[1]["id"])["contribution_cents"] == 41275
    assert line_for_participant(report["id"], participants[2]["id"])["contribution_cents"] == 103188
    assert report["total_contributions_due_cents"] == 227013
    assert report["total_hours_reported"] == 300.00


def test_a_filed_report_opens_submitted_unpaid_and_due_on_the_twentieth(api):
    """PRD §3.3: "A report that survives intake is stored with `origin`
    `EMPLOYER`, `filing_status` `SUBMITTED`, `payment_status` `UNPAID`,
    `amount_remitted_cents` at 0, and both `posted_at` and `paid_in_full_at`
    null. Its `due_date` is computed at intake as the twentieth day of the month
    following its `work_period` — a report for hours worked in a given month is
    due on the twentieth of the next one."
    PRD §3.4: "Hours do not count for anything until a fund administrator posts
    the report that carries them."

    Design: Corner/state_machines/report_starts_in_submitted_and_unpaid_with_computed_due_date
    """
    base = setup_employer_with_one_participant()

    payload = create_contribution_report_payload(
        base["employer"]["id"],
        "2026-12",
        employer_version(base["employer"]["id"]),
        [contribution_line_payload(base["participant"]["id"], 100.00, 400_000, "JOURNEYMAN")],
    )
    report = validate_success(
        api.create_contribution_report(
            payload, make_employer_headers(base["employer"]["id"])
        ),
        201,
    )

    assert_contribution_report(report)
    assert report["filing_status"] == "SUBMITTED"
    assert report["payment_status"] == "UNPAID"
    assert report["due_date"] == "2027-01-20", "the twentieth of the month after 2026-12"
    assert report["origin"] == "EMPLOYER"
    assert report["amends_report_id"] is None
    assert report["amount_remitted_cents"] == 0
    assert report["posted_at"] is None
    assert report["paid_in_full_at"] is None
    assert report["total_contributions_due_cents"] == 82550
    assert report["total_hours_reported"] == 100.00

    participant = validate_success(api.get_participant(base["participant"]["id"], ADMIN))
    assert participant["credited_hours_total"] == 0, (
        "an unposted report credits nothing to the worker"
    )


def test_report_intake_refuses_five_distinct_malformed_or_conflicting_filings(api):
    """PRD §3.3: "A filing that carries no lines whatsoever is refused with
    `ERR_EMPTY_REPORT`. An employer may hold at most one report per work period
    whose filing state is not `SUPERSEDED`, so filing a second report for a
    month that already has a live one, without naming an amendment target, is
    refused with `ERR_DUPLICATE_WORK_PERIOD`. When `amends_report_id` is
    supplied it must name a report whose filing state is `POSTED`, whose
    employer is this same employer, and whose work period is this same work
    period; any other target is refused with `ERR_AMENDMENT_TARGET_INVALID`."
    PRD §3.3: "Any worker named in a line who is enrolled in a different fund
    than the employer's own is rejected with `ERR_PARTICIPANT_FUND_MISMATCH`."
    PRD §2.8: "**Request shape.** Required fields present, types correct, enum
    members valid, every month key matching a four-digit year, a hyphen, and a
    two-digit month between 01 and 12, both prior-year arrays holding exactly
    five entries, hours values at least 0 with at most two decimal places, and
    every cents field a non-negative integer — otherwise `ERR_INVALID_REQUEST`
    (400)."

    Design: Corner/validations/report_intake_constraint_sweep_is_rejected_on_five_distinct_grounds
    """
    base = setup_intake_guard_scenario()
    employer_id = base["employer"]["id"]
    version_before = employer_version(employer_id)

    empty = create_contribution_report_payload(employer_id, "2026-04", version_before, [])
    validate_error(
        api.create_contribution_report(empty, ADMIN), ApiErrorId.ERR_EMPTY_REPORT.value
    )

    duplicate = create_contribution_report_payload(
        employer_id,
        "2026-03",
        version_before,
        [contribution_line_payload(base["participant"]["id"], 10.00, 40_000)],
    )
    validate_error(
        api.create_contribution_report(duplicate, ADMIN),
        ApiErrorId.ERR_DUPLICATE_WORK_PERIOD.value,
    )

    bad_amendment = create_contribution_report_payload(
        employer_id,
        "2026-03",
        version_before,
        [contribution_line_payload(base["participant"]["id"], 10.00, 40_000)],
        amends_report_id=base["report"]["id"],
    )
    validate_error(
        api.create_contribution_report(bad_amendment, ADMIN),
        ApiErrorId.ERR_AMENDMENT_TARGET_INVALID.value,
    )

    foreign_worker = create_contribution_report_payload(
        employer_id,
        "2026-04",
        version_before,
        [contribution_line_payload(base["foreign_participant"]["id"], 10.00, 40_000)],
    )
    validate_error(
        api.create_contribution_report(foreign_worker, ADMIN),
        ApiErrorId.ERR_PARTICIPANT_FUND_MISMATCH.value,
    )

    bad_enum = create_contribution_report_payload(
        employer_id,
        "2026-04",
        version_before,
        [
            contribution_line_payload(
                base["participant"]["id"], 10.00, 40_000, "SUPERINTENDENT"
            )
        ],
    )
    validate_error(
        api.create_contribution_report(bad_enum, ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    _rows, meta = validate_paginated(
        api.list_contribution_reports(ADMIN, params={"employer_id": employer_id})
    )
    assert meta["total_count"] == 1, "no refused filing created a report"
    assert employer_version(employer_id) == version_before, (
        "a refused filing does not bump the employer's version"
    )


def test_a_second_filing_on_a_stale_employer_version_is_rejected(api):
    """PRD §2.7: "A `POST /contribution-reports` request must carry
    `expected_employer_version`, holding the `version` of the employer as the
    client last observed it. If that value does not equal the employer's current
    `version`, the filing is rejected with `ERR_STALE_EMPLOYER_VERSION` (HTTP
    412)."
    PRD §3.3: "Finally, filing increments the employer's `version` by exactly 1,
    which is why a client that files two reports back to back must re-read the
    employer between them."

    Design: Corner/cross_cutting_layers/stale_employer_version_on_report_intake_is_rejected_with_412
    """
    base = setup_employer_with_one_participant()
    employer_id = base["employer"]["id"]
    employer_headers = make_employer_headers(employer_id)
    version_seen = employer_version(employer_id)

    january = file_single_line_report(
        employer_id,
        base["participant"]["id"],
        "2026-01",
        100.00,
        400_000,
        headers=employer_headers,
        expected_employer_version=version_seen,
    )

    stale = create_contribution_report_payload(
        employer_id,
        "2026-02",
        version_seen,
        [contribution_line_payload(base["participant"]["id"], 100.00, 400_000)],
    )
    validate_error(
        api.create_contribution_report(stale, employer_headers),
        ApiErrorId.ERR_STALE_EMPLOYER_VERSION.value,
    )

    version_now = employer_version(employer_id)
    assert version_now == version_seen + 1, "the first filing advanced the version by one"

    retried = create_contribution_report_payload(
        employer_id,
        "2026-02",
        version_now,
        [contribution_line_payload(base["participant"]["id"], 100.00, 400_000)],
    )
    february = validate_success(
        api.create_contribution_report(retried, employer_headers), 201
    )

    rows, meta = validate_paginated(
        api.list_contribution_reports(ADMIN, params={"employer_id": employer_id})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {january["id"], february["id"]}


def test_version_advances_by_one_on_the_remittance_and_again_on_the_post(api):
    """PRD §2.4: "Most resources additionally carry `updated_at` — an ISO 8601
    UTC timestamp refreshed on every mutation of the row — and `version`, an
    integer that begins at 1 when the row is created and increases by exactly 1
    on every mutation of that row, including mutations that arrive as a side
    effect of an operation performed on some other resource."
    PRD §3.4: "The act of posting stamps `posted_at` with the logical clock
    instant, sets `filing_status` to `POSTED`, and increments the report's
    `version` by 1."
    PRD §3.3: "Finally, filing increments the employer's `version` by exactly 1,
    which is why a client that files two reports back to back must re-read the
    employer between them."

    Design: Corner/cross_cutting_layers/version_increments_by_one_on_every_mutation_of_a_common_fields_entity
    """
    base = setup_employer_with_one_participant()
    employer_id = base["employer"]["id"]

    assert base["employer"]["version"] == 1, "a freshly registered employer is at 1"
    version_consumed = employer_version(employer_id)
    assert version_consumed == 1

    report = file_single_line_report(
        employer_id,
        base["participant"]["id"],
        "2026-03",
        100.00,
        400_000,
        expected_employer_version=version_consumed,
    )
    assert report["version"] == 1, "a freshly filed report is at version 1"
    assert employer_version(employer_id) == 2, "filing left the employer at version 2"

    after_remit = validate_success(
        api.remit_contribution_report(report["id"], {"amount_cents": 30_000}, ADMIN)
    )
    assert after_remit["version"] == 2

    after_post = validate_success(api.post_contribution_report(report["id"], ADMIN))
    assert after_post["version"] == 3
    assert after_post["payment_status"] == "PARTIAL"
    assert after_post["filing_status"] == "POSTED"

    employer_now = read_employer(employer_id)
    assert employer_now["cumulative_delinquent_cents"] == 52550, (
        "82550 due less the 30000 remitted"
    )

    stored = read_report(report["id"])
    assert stored["created_at"].endswith("Z") and "." in stored["created_at"]
    assert stored["updated_at"].endswith("Z") and "." in stored["updated_at"]
