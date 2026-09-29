"""
Writes whose admissibility is decided by the state of a *different* row.

Two places in the licensing contract gate a call on a field the addressed row
does not own.  A rider coverage window may only be attached while its parent
licence is `ACTIVE`, so the identical request body is refused and then accepted
purely on the strength of the parent's coverage dimension.  And a licence
application may only be submitted while the applying venue carries no audit
hold — a flag the application never references, owned by the venue and flipped by
an audit case the application knows nothing about.  Each gate is checked from
three angles: the refusal itself, the proof that the refusal wrote nothing
anywhere, and the acceptance of the same call once the parent has been put back
in the state the rule demands.
"""

from test_helpers import (
    APPLICATION_STATUS_DRAFT,
    APPLICATION_STATUS_SUBMITTED,
    ASSESSMENT_KIND_SEASONAL_RIDER,
    ASSESSMENT_STATUS_ISSUED,
    AUDIT_TRIGGER_ROUTINE,
    CASE_STATUS_CLOSED_NO_ACTION,
    CASE_STATUS_OPEN,
    CLOSED_REASON_WITHIN_TOLERANCE,
    COVERAGE_ACTIVE,
    COVERAGE_SUSPENDED,
    ERR_AUDIT_HOLD_ACTIVE,
    ERR_LICENSE_NOT_ACTIVE,
    SUSPENSION_REASON_OPERATOR_REQUEST,
    WINDOW_KIND_ANNUAL_TERM,
    WINDOW_KIND_SEASONAL_EVENT_RIDER,
    WINDOW_STATUS_ACTIVE,
    admin_headers,
    application_row,
    assert_assessment,
    assert_count,
    assert_days_apart,
    assert_empty_list,
    assert_instant_equals,
    assert_money,
    assert_venue_ledger,
    assert_version_unchanged,
    auditor_headers,
    bmi_payload,
    close_case_payload,
    coverage_window_payload,
    find_row,
    get_success_data,
    given_draft_application,
    given_licensed_venue,
    given_open_case,
    given_society,
    given_venue,
    license_row,
    read_rows,
    suspend_payload,
    validate_error,
    validate_success,
    venue_operator_headers,
    venue_row,
    windows_of_license,
)

# The bar-and-grill survey sits in the second occupancy tier, so its verified
# annual fee for a 4600 bp society on a default schedule is 90017 cents, and the
# activation invoice for exactly that amount is the venue's whole ledger.
BAR_GRILL_ANNUAL_FEE_CENTS = 90017

# The rider runs from 2026-12-20 up to but not including 2027-01-04, which is 15
# whole days, and 90017 * 15 * 13500 / (365 * 10000) rounds half up to 4994 cents.
RIDER_WINDOW_START = "2026-12-20T00:00:00Z"
RIDER_WINDOW_END = "2027-01-04T00:00:00Z"
RIDER_COVERED_DAY_COUNT = 15
RIDER_FEE_CENTS = 4994


def _suspended_license_carrying_only_its_annual_window(api):
    """Drive one bar and grill to a licence that is SUSPENDED but still holds the
    ACTIVE annual-term window activation gave it.

    The suspension reason is ``OPERATOR_REQUEST``, which PRD §3.7 exempts from
    the reinstatement balance gate, so the licence can be put back to ``ACTIVE``
    later without paying anything.  The returned dict carries the venue id and
    the freshly re-read licence row.
    """
    world = given_licensed_venue(api, requested_term_start="2026-08-01T00:00:00Z")
    venue_id = world["venue"]["id"]
    license_id = world["license"]["id"]

    assert_venue_ledger(
        world["venue"],
        BAR_GRILL_ANNUAL_FEE_CENTS,
        0,
        0,
        BAR_GRILL_ANNUAL_FEE_CENTS,
    )

    suspended = get_success_data(
        api.suspend_license(
            license_id,
            suspend_payload(SUSPENSION_REASON_OPERATOR_REQUEST),
            admin_headers(),
        )
    )
    assert suspended["coverage_status"] == COVERAGE_SUSPENDED, (
        f"the licence should be SUSPENDED, got {suspended['coverage_status']!r}"
    )

    return {"venue_id": venue_id, "license": license_row(api, license_id)}


def test_gate_window_rider_refused_while_the_parent_license_is_suspended(api):
    """Attaching a seasonal rider is refused on the strength of the parent
    licence's coverage dimension, a field of a different row than the one the
    request would create.

    PRD §2.12: "The addressed `License` has `coverage_status` equal to `ACTIVE`
    — otherwise `ERR_LICENSE_NOT_ACTIVE` (409)."

    Design: Difficulty/cross_entity_state_dependency/coverage_window_creation_requires_active_license
    """
    world = _suspended_license_carrying_only_its_annual_window(api)

    refused = api.create_coverage_window(
        world["license"]["id"],
        coverage_window_payload(
            RIDER_WINDOW_START,
            RIDER_WINDOW_END,
            WINDOW_KIND_SEASONAL_EVENT_RIDER,
        ),
        admin_headers(),
    )
    validate_error(refused, ERR_LICENSE_NOT_ACTIVE)


def test_gate_window_refused_rider_writes_neither_window_nor_invoice(api):
    """The refused rider leaves the licence holding only the annual-term window
    activation created, and bills the venue nothing.

    PRD §3.6: "Creating a priced rider issues a `FeeAssessment` with
    `assessment_kind` `SEASONAL_RIDER` for exactly that `rider_fee_cents`, in
    `ISSUED` status with `paid_amount_cents` at 0 and `due_date` 30 days after
    the logical clock instant."

    Design: Difficulty/cross_entity_state_dependency/coverage_window_creation_requires_active_license
    """
    world = _suspended_license_carrying_only_its_annual_window(api)
    licence = world["license"]

    refused = api.create_coverage_window(
        licence["id"],
        coverage_window_payload(
            RIDER_WINDOW_START,
            RIDER_WINDOW_END,
            WINDOW_KIND_SEASONAL_EVENT_RIDER,
        ),
        admin_headers(),
    )
    validate_error(refused, ERR_LICENSE_NOT_ACTIVE)

    windows = windows_of_license(api, licence["id"])
    assert len(windows) == 1, (
        "the licence should still hold exactly the annual-term window, got "
        f"{[w['window_kind'] for w in windows]}"
    )
    annual = find_row(windows, window_kind=WINDOW_KIND_ANNUAL_TERM)
    assert annual["status"] == WINDOW_STATUS_ACTIVE, (
        f"suspension voids no windows, got {annual['status']!r}"
    )
    assert_instant_equals(
        annual["window_start"], licence["term_start"], "annual window_start"
    )
    assert_instant_equals(
        annual["window_end"], licence["term_end"], "annual window_end"
    )
    assert_money(annual["rider_fee_cents"], 0, "annual window rider_fee_cents")

    assert_empty_list(
        api.list_fee_assessments(
            admin_headers(),
            {
                "venue_id": world["venue_id"],
                "assessment_kind": ASSESSMENT_KIND_SEASONAL_RIDER,
            },
        )
    )
    ledger = venue_row(api, world["venue_id"])
    assert_venue_ledger(
        ledger,
        BAR_GRILL_ANNUAL_FEE_CENTS,
        0,
        0,
        BAR_GRILL_ANNUAL_FEE_CENTS,
    )
    assert_version_unchanged(license_row(api, licence["id"]), licence, "licence")


def test_gate_window_reinstated_license_accepts_the_identical_rider(api):
    """Reinstating the parent licence and changing nothing in the request body
    turns the same rider POST into a priced, billed coverage window.

    PRD §3.6: "For a `SEASONAL_EVENT_RIDER` or a `FESTIVAL_RIDER`,
    `rider_fee_cents` is derived from the owning licence's `annual_fee_cents` as
    it stands **at the moment the rider is created**: multiply that
    `annual_fee_cents` by the window's `covered_day_count`, multiply by the
    seasonal peak factor of 13500 basis points, divide by the product of 365
    term-days and 10000, and round half up to whole cents — a **single** rounding
    step at the very end, with the day fraction and the peak factor combined
    inside one expression rather than rounded independently."

    Design: Difficulty/cross_entity_state_dependency/coverage_window_creation_requires_active_license
    """
    world = _suspended_license_carrying_only_its_annual_window(api)
    licence = world["license"]
    body = coverage_window_payload(
        RIDER_WINDOW_START, RIDER_WINDOW_END, WINDOW_KIND_SEASONAL_EVENT_RIDER
    )

    first_attempt = api.create_coverage_window(licence["id"], body, admin_headers())
    validate_error(first_attempt, ERR_LICENSE_NOT_ACTIVE)

    reinstated = get_success_data(
        api.reinstate_license(licence["id"], admin_headers())
    )
    assert reinstated["coverage_status"] == COVERAGE_ACTIVE, (
        f"reinstatement must restore ACTIVE, got {reinstated['coverage_status']!r}"
    )

    rider = validate_success(
        api.create_coverage_window(licence["id"], body, admin_headers()), 201
    )
    assert rider["window_kind"] == WINDOW_KIND_SEASONAL_EVENT_RIDER, (
        f"expected a seasonal rider, got {rider['window_kind']!r}"
    )
    assert_days_apart(
        rider["window_start"], rider["window_end"], RIDER_COVERED_DAY_COUNT, "rider span"
    )
    assert_count(
        rider["covered_day_count"], RIDER_COVERED_DAY_COUNT, "covered_day_count"
    )
    assert_money(rider["rider_fee_cents"], RIDER_FEE_CENTS, "rider_fee_cents")

    billed = read_rows(
        api.list_fee_assessments(
            admin_headers(),
            {
                "venue_id": world["venue_id"],
                "assessment_kind": ASSESSMENT_KIND_SEASONAL_RIDER,
            },
        ),
        expected_total=1,
    )
    assert_assessment(
        billed[0],
        ASSESSMENT_KIND_SEASONAL_RIDER,
        RIDER_FEE_CENTS,
        ASSESSMENT_STATUS_ISSUED,
        paid=0,
    )
    ledger = venue_row(api, world["venue_id"])
    assert_venue_ledger(
        ledger,
        BAR_GRILL_ANNUAL_FEE_CENTS + RIDER_FEE_CENTS,
        0,
        0,
        BAR_GRILL_ANNUAL_FEE_CENTS + RIDER_FEE_CENTS,
    )


def _draft_application_on_a_venue_under_audit(api):
    """File a DRAFT application, then put its venue under an audit hold.

    No rate schedule and no licence take part: the hold arrives entirely through
    a third row, a routine audit case the application never references.  The
    returned dict carries the venue row, the DRAFT application row and the open
    case row.
    """
    society = given_society(api, bmi_payload())
    venue = given_venue(api)
    application = given_draft_application(
        api, venue, society["id"], "2026-08-01T00:00:00Z"
    )
    assert application["status"] == APPLICATION_STATUS_DRAFT, (
        f"a freshly filed application should be DRAFT, got {application['status']!r}"
    )

    case = given_open_case(
        api,
        venue["id"],
        [society["id"]],
        "2025-01-01T00:00:00Z",
        "2026-01-01T00:00:00Z",
        AUDIT_TRIGGER_ROUTINE,
    )
    assert case["status"] == CASE_STATUS_OPEN, (
        f"a freshly opened case should be OPEN, got {case['status']!r}"
    )

    return {"venue": venue, "application": application, "case": case}


def test_gate_submit_application_refused_while_the_venue_is_held(api):
    """Submitting an application is refused because of a flag on the applying
    venue, not because of anything on the application itself.

    PRD §2.12: "The governing `Venue` has `audit_hold` false — otherwise
    `ERR_AUDIT_HOLD_ACTIVE` (409)."

    Design: Difficulty/cross_entity_state_dependency/application_submit_requires_venue_without_audit_hold
    """
    world = _draft_application_on_a_venue_under_audit(api)

    refused = api.submit_application(
        world["application"]["id"],
        venue_operator_headers(world["venue"]["id"]),
    )
    validate_error(refused, ERR_AUDIT_HOLD_ACTIVE)


def test_gate_submit_hold_traces_back_to_the_open_case_alone(api):
    """The refused submission leaves the application untouched in DRAFT, and the
    venue's hold is explained purely by the open audit case.

    PRD §2.10: "A venue also carries `audit_hold`, a boolean that is true for
    exactly as long as at least one `AuditCase` on that venue has a `status` in
    the non-terminal set `OPEN`, `FINDINGS_ISSUED`, `SETTLEMENT_PROPOSED` or
    `DISPUTED`, and false otherwise."

    Design: Difficulty/cross_entity_state_dependency/application_submit_requires_venue_without_audit_hold
    """
    world = _draft_application_on_a_venue_under_audit(api)
    before = application_row(api, world["application"]["id"])

    refused = api.submit_application(
        world["application"]["id"],
        venue_operator_headers(world["venue"]["id"]),
    )
    validate_error(refused, ERR_AUDIT_HOLD_ACTIVE)

    after = application_row(api, world["application"]["id"])
    assert after["status"] == APPLICATION_STATUS_DRAFT, (
        f"the refused application must stay DRAFT, got {after['status']!r}"
    )
    assert_version_unchanged(after, before, "application")

    held = venue_row(api, world["venue"]["id"])
    assert held["audit_hold"] is True, (
        "the venue must be held while its only audit case is open"
    )
    cases = read_rows(
        api.list_audit_cases(admin_headers(), {"venue_id": world["venue"]["id"]}),
        expected_total=1,
    )
    assert cases[0]["status"] == CASE_STATUS_OPEN, (
        f"the one case on the venue should be OPEN, got {cases[0]['status']!r}"
    )


def test_gate_submit_closing_the_case_releases_the_application(api):
    """Closing the audit case with no action lifts the venue's hold, and the
    identical submission then goes through.

    PRD §3.9: "The venue's `audit_hold` is then recomputed and becomes false when
    no other `AuditCase` of that venue remains in `OPEN`, `FINDINGS_ISSUED`,
    `SETTLEMENT_PROPOSED` or `DISPUTED`; `Venue.version` increments by 1."

    Design: Difficulty/cross_entity_state_dependency/application_submit_requires_venue_without_audit_hold
    """
    world = _draft_application_on_a_venue_under_audit(api)
    operator = venue_operator_headers(world["venue"]["id"])

    first_attempt = api.submit_application(world["application"]["id"], operator)
    validate_error(first_attempt, ERR_AUDIT_HOLD_ACTIVE)

    closed = validate_success(
        api.close_audit_case(
            world["case"]["id"],
            close_case_payload(CLOSED_REASON_WITHIN_TOLERANCE),
            auditor_headers(),
        )
    )
    assert closed["status"] == CASE_STATUS_CLOSED_NO_ACTION, (
        f"a no-action closure should be CLOSED_NO_ACTION, got {closed['status']!r}"
    )
    released = venue_row(api, world["venue"]["id"])
    assert released["audit_hold"] is False, (
        "closing the only open case must lift the audit hold"
    )

    submitted = validate_success(
        api.submit_application(world["application"]["id"], operator)
    )
    assert submitted["status"] == APPLICATION_STATUS_SUBMITTED, (
        f"the released application should be SUBMITTED, got {submitted['status']!r}"
    )
