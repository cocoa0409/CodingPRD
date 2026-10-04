"""Reporting calendar: grace windows, occupancy, lifecycle, standing."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS,
    validate_success, validate_error, validate_paginated,
    create_institution_with_registrars, create_period_payload,
    add_agreement, add_period, advance_clock, get_period_version,
    upload_file, certify_file, enrollment_row,
)

OPS = TEST_USERS["ops_headers"]


def test_period_grace_ends_at_computed_from_due_date(api):
    """PRD section 3.2: "From these the system derives `grace_ends_at` as
    fourteen days after `submission_due_at` — a two-week grace window in
    which late certification is still accepted — and computes the period's
    initial status from the current logical time."
    PRD section 2.5: "`version` (integer): starts at 1 at creation".

    Design: Corner/entities/period_grace_ends_at_computed_from_due_date
    """
    ctx = create_institution_with_registrars()
    resp = api_client.create_reporting_period(
        ctx["inst_id"], create_period_payload(), OPS,
    )
    period = validate_success(resp, 201)
    assert period["grace_ends_at"] == "2027-01-03T00:00:00Z", (
        "submission_due_at 2026-12-20 plus fourteen days"
    )
    assert period["status"] == "SCHEDULED", (
        "default now 2026-09-01 < submission_opens_at 2026-11-01"
    )
    assert period["version"] == 1


def test_period_overlap_same_day_collides(api):
    """PRD section 3.2: "Each period occupies the closed interval from its
    `term_start` through its `submission_due_at`, inclusive, and a new
    period's `term_start` must fall strictly after every existing period's
    `submission_due_at` for that institution; even a same-day start collides.
    A colliding period is rejected with `ERR_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/period_closed_occupancy_through_due_date
    """
    ctx = create_institution_with_registrars()
    add_period(ctx["inst_id"])
    resp = api_client.create_reporting_period(
        ctx["inst_id"],
        create_period_payload(
            term_label="Winter 2026", term_start="2026-12-20",
            term_end="2027-03-15", submission_opens_at="2027-01-05",
            submission_due_at="2027-03-31",
        ),
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_OVERLAP)


def test_period_day_after_due_allowed(api):
    """PRD section 3.2: "a new period's `term_start` must fall strictly after
    every existing period's `submission_due_at` for that institution; even a
    same-day start collides."

    Design: Difficulty/resource_temporal_overlap/period_closed_occupancy_through_due_date
    """
    ctx = create_institution_with_registrars()
    add_period(ctx["inst_id"])
    resp = api_client.create_reporting_period(
        ctx["inst_id"],
        create_period_payload(
            term_label="Winter 2026", term_start="2026-12-21",
            term_end="2027-03-15", submission_opens_at="2027-01-05",
            submission_due_at="2027-03-31",
        ),
        OPS,
    )
    period = validate_success(resp, 201)
    assert period["status"] == "SCHEDULED", (
        "submission_opens_at 2027-01-05 is after the default clock"
    )


def test_period_grace_boundary_strictly_after(api):
    """PRD section 3.2: "A period's lifecycle is clock-driven: `SCHEDULED`
    before submissions open, `OPEN` once now reaches `submission_opens_at`,
    `GRACE` once now passes `submission_due_at`, and `CLOSED` once now passes
    `grace_ends_at`."
    PRD section 3.2: "At close, the period's `outcome` becomes `ON_TIME` when
    a `CERTIFIED` file exists whose `certified_at` is on or before
    `submission_due_at`, `LATE` when the only certified files were certified
    after `submission_due_at`, and `DELINQUENT` when nothing was ever
    certified."

    Design: Corner/state_machines/period_grace_boundary_strictly_after
    """
    ctx = create_institution_with_registrars()
    add_agreement(ctx["inst_id"])
    add_period(ctx["inst_id"])

    def status():
        data, _m = validate_paginated(
            api_client.list_reporting_periods(ctx["inst_id"], OPS),
        )
        return data[0]

    advance_clock("2026-12-20T00:00:00Z")
    assert status()["status"] == "OPEN", "now == due; GRACE requires now > due"

    advance_clock("2026-12-21T00:00:00Z")
    assert status()["status"] == "GRACE"

    advance_clock("2027-01-03T00:00:00Z")
    assert status()["status"] == "GRACE", (
        "now == grace_ends_at; CLOSED requires now > grace_ends_at"
    )

    advance_clock("2027-01-04T00:00:00Z")
    period = status()
    assert period["status"] == "CLOSED"
    assert period["outcome"] == "DELINQUENT", "nothing was ever certified"


def test_period_field_date_ordering_rejected(api):
    """PRD section 3.2: "The field-level date rules are then applied:
    `term_end` strictly after `term_start`, and `submission_opens_at` no
    earlier than `term_start` and strictly before `submission_due_at`;
    violations are rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/validations/period_field_date_ordering_rejected
    """
    ctx = create_institution_with_registrars()
    bad_term = api_client.create_reporting_period(
        ctx["inst_id"],
        create_period_payload(term_label="Bad Term", term_end="2026-09-01"),
        OPS,
    )
    validate_error(bad_term, ApiErrorId.ERR_VALIDATION)
    bad_window = api_client.create_reporting_period(
        ctx["inst_id"],
        create_period_payload(
            term_label="Bad Window", submission_opens_at="2026-12-20",
        ),
        OPS,
    )
    validate_error(bad_window, ApiErrorId.ERR_VALIDATION)


def test_compliance_standing_lookback_ages_out_old_delinquent(api):
    """PRD section 3.2: "The recompute considers the institution's `CLOSED`
    periods, at most the three most recent ordered by `submission_due_at`
    descending with `created_at` ascending breaking ties. If any of those
    periods is `DELINQUENT`, the institution becomes `NON_COMPLIANT`;
    otherwise, if any is `LATE`, it moves to `WATCH`; otherwise — including
    when no period has ever closed — it stands `COMPLIANT`."

    Design: Corner/calculations/compliance_standing_lookback_ages_out_old_delinquent
    """
    ctx = create_institution_with_registrars()
    add_agreement(ctx["inst_id"],
                  effective_from="2026-01-01", effective_to="2028-06-30")
    periods = [
        add_period(ctx["inst_id"], term_label="P1", term_start="2026-09-01",
                   term_end="2026-12-15", submission_opens_at="2026-11-01",
                   submission_due_at="2026-12-20"),
        add_period(ctx["inst_id"], term_label="P2", term_start="2026-12-21",
                   term_end="2027-05-01", submission_opens_at="2027-03-01",
                   submission_due_at="2027-05-15"),
        add_period(ctx["inst_id"], term_label="P3", term_start="2027-05-16",
                   term_end="2027-09-01", submission_opens_at="2027-07-01",
                   submission_due_at="2027-09-15"),
        add_period(ctx["inst_id"], term_label="P4", term_start="2027-09-16",
                   term_end="2028-01-15", submission_opens_at="2027-11-01",
                   submission_due_at="2028-01-15"),
    ]

    def certify_into(index, row_term_start, row_term_end):
        scope = {"inst_id": ctx["inst_id"], "sub_uid": ctx["sub_uid"],
                 "cert_uid": ctx["cert_uid"],
                 "period_id": periods[index]["id"]}
        f = upload_file(scope, [enrollment_row(
            term_start=row_term_start, term_end=row_term_end,
        )], expected_version=get_period_version(ctx["inst_id"], index))
        certify_file(scope, f["id"])

    # P1 never receives a file: it will close DELINQUENT.
    advance_clock("2027-03-10T00:00:00Z")
    certify_into(1, "2026-12-21", "2027-05-01")
    advance_clock("2027-07-15T00:00:00Z")
    certify_into(2, "2027-05-16", "2027-09-01")
    advance_clock("2027-11-15T00:00:00Z")
    certify_into(3, "2027-09-16", "2028-01-15")

    mid = validate_success(api_client.get_institution(ctx["inst_id"], OPS), 200)
    assert mid["compliance_standing"] == "NON_COMPLIANT", (
        "closed periods are {P1 DELINQUENT, P2 ON_TIME, P3 ON_TIME} and P1 "
        "is still inside the three-period window"
    )

    advance_clock("2028-02-01T00:00:00Z")
    end = validate_success(api_client.get_institution(ctx["inst_id"], OPS), 200)
    assert end["compliance_standing"] == "COMPLIANT", (
        "after P4 closes ON_TIME the lookback window is {P4, P3, P2} and "
        "P1's DELINQUENT has aged out"
    )
