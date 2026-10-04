"""Visa sponsorship issuance and grant activation gates (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_residency_ledger,
    assert_visa_sponsorship,
    create_visa_sponsorship_payload,
    get_grant,
    get_visa_ledger,
    grant_transition_payload,
    issue_visa_sponsorship,
    set_clock_to,
    setup_confirmed_grant,
    setup_selected_application,
    validate_error,
    validate_success,
)


def test_duplicate_visa_sponsorship_rejected(api, program_officer_headers):
    """PRD §3.7: "A grant carries at most one sponsorship
    (`ERR_DUPLICATE_VISA`), and the sponsorship's own `status` begins at
    ISSUED."

    Design: Corner/endpoints/duplicate_visa_sponsorship_rejected
    """
    bundle = setup_confirmed_grant()
    visa = issue_visa_sponsorship(bundle["grant"], subject_to_home_residency=True)
    assert visa["status"] == "ISSUED"

    resp = api.create_visa_sponsorship(
        bundle["grant"]["id"],
        create_visa_sponsorship_payload(
            subject_to_home_residency=False,
            orientation_completed_at="2027-06-10T00:00:00Z",
        ),
        program_officer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_VISA)

    visas = validate_success(
        api.list_grant_visa_sponsorships(bundle["grant"]["id"], program_officer_headers)
    )
    assert len(visas) == 1, "exactly one sponsorship may exist per grant"
    assert visas[0]["subject_to_home_residency"] is True


def test_activate_before_start_date_with_visa_returns_start_not_reached(
    api, program_officer_headers,
):
    """PRD §3.7: "Activation — moving the grant CONFIRMED → ACTIVE — is gated
    twice: the grant's `orientation_completed_at` must be set, which in
    practice means a visa sponsorship has been issued
    (`ERR_ORIENTATION_INCOMPLETE`), and the logical clock must be at or past
    the grant's `start_date` (`ERR_START_DATE_NOT_REACHED`)."

    Orientation is properly recorded, so the temporal arm fires alone.

    Design: Corner/endpoints/activate_before_start_date_with_visa_returns_start_not_reached
    """
    bundle = setup_confirmed_grant()  # start_date 2027-09-01
    issue_visa_sponsorship(bundle["grant"])
    set_clock_to("2027-08-15T00:00:00Z")  # before start_date

    resp = api.transition_grant(
        bundle["grant"]["id"], grant_transition_payload("ACTIVATE"),
        program_officer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_START_DATE_NOT_REACHED)

    grant = get_grant(bundle["grant"])
    assert grant["status"] == "CONFIRMED"
    assert grant.get("interim_report_due_date") is None
    assert grant.get("final_report_due_date") is None


def test_visa_issuance_rejected_while_grant_provisional(
    api, program_officer_headers,
):
    """PRD §3.7: "With a CONFIRMED grant in hand — otherwise
    `ERR_GRANT_NOT_CONFIRMED` — a `ProgramOfficer` issues the exchange visitor
    visa sponsorship, supplying `subject_to_home_residency`, the two-year home
    residency determination, and `orientation_completed_at`, the pre-departure
    orientation completion timestamp, which must not lie in the future
    (`ERR_VALIDATION`)."

    Design: Difficulty/cross_entity_state_dependency/visa_issue_requires_grant_confirmed
    """
    bundle = setup_selected_application()  # grant created PROVISIONAL
    grant = bundle["grant"]
    assert grant["status"] == "PROVISIONAL"

    resp = api.create_visa_sponsorship(
        grant["id"],
        create_visa_sponsorship_payload(
            subject_to_home_residency=True,
            # not in the future at the 2026-09-01 logical clock, so only the
            # grant-phase gate can fail
            orientation_completed_at="2026-08-01T00:00:00Z",
        ),
        program_officer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_GRANT_NOT_CONFIRMED)

    visas = validate_success(
        api.list_grant_visa_sponsorships(grant["id"], program_officer_headers)
    )
    assert visas == [], "a rejected issuance must not persist a sponsorship"
    assert get_grant(grant)["status"] == "PROVISIONAL"


def test_visa_issuance_succeeds_once_grant_confirmed(api, program_officer_headers):
    """PRD §3.7: "Issuance assigns the `sponsor_program_number` — the letters
    "EV-" followed by a six-digit sequence — copies the orientation timestamp
    onto the grant's own `orientation_completed_at`, and creates the grantee's
    residency ledger: bound to the sponsorship via `visa_sponsorship_id`,
    starting in PENDING when the grantee is subject to home residency and in
    NOT_REQUIRED otherwise, with `required_days` set to 730 and `accrued_days`
    at 0."

    Control arm of the grant-phase gate: the identical call succeeds against
    a CONFIRMED grant.

    Design: Difficulty/cross_entity_state_dependency/visa_issue_requires_grant_confirmed
    """
    bundle = setup_confirmed_grant()
    visa = issue_visa_sponsorship(bundle["grant"], subject_to_home_residency=True)
    assert_visa_sponsorship(visa)
    assert visa["status"] == "ISSUED"
    assert visa["sponsor_program_number"].startswith("EV-")

    grant = get_grant(bundle["grant"])
    assert grant.get("orientation_completed_at") is not None, (
        "issuance copies the orientation timestamp onto the grant"
    )

    ledger = get_visa_ledger(visa)
    assert_residency_ledger(ledger)
    assert ledger["status"] == "PENDING"
    assert ledger["required_days"] == 730
    assert ledger["accrued_days"] == 0


def test_activate_without_orientation_and_before_start_safety_wins(
    api, program_officer_headers,
):
    """PRD §2.7: "7. **Orientation gate.** Grant activation requires completed
    pre-departure orientation — otherwise `ERR_ORIENTATION_INCOMPLETE` (409)."
    PRD §2.7: "The ordering is observable behavior: an expired offer acted on
    through a nonexistent round 404s before any temporal check runs; a
    well-formed request from the wrong role 403s before state is examined; a
    stale `expected_application_version` is detected (412) before ownership is
    examined; and the quota gate fires only after every other check has
    passed."

    Both violations hold at trigger time (no sponsorship recorded, clock
    2027-08-01 before start_date 2027-09-01); the orientation gate is listed
    ahead of the temporal checks, so its error must win.

    Design: Difficulty/priority_pair_validation_conflict/activate_missing_orientation_and_early_start_safety_wins
    """
    bundle = setup_confirmed_grant()  # no visa sponsorship issued
    set_clock_to("2027-08-01T00:00:00Z")

    resp = api.transition_grant(
        bundle["grant"]["id"], grant_transition_payload("ACTIVATE"),
        program_officer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_ORIENTATION_INCOMPLETE)

    grant = get_grant(bundle["grant"])
    assert grant["status"] == "CONFIRMED"
    assert grant.get("orientation_completed_at") is None


def test_activate_with_orientation_and_before_start_temporal_fires(
    api, program_officer_headers,
):
    """PRD §3.7: "Activation — moving the grant CONFIRMED → ACTIVE — is gated
    twice: the grant's `orientation_completed_at` must be set, which in
    practice means a visa sponsorship has been issued
    (`ERR_ORIENTATION_INCOMPLETE`), and the logical clock must be at or past
    the grant's `start_date` (`ERR_START_DATE_NOT_REACHED`)."

    With orientation recorded the safety gate passes and the temporal arm is
    the one that fires at clock 2027-08-01.

    Design: Difficulty/priority_pair_validation_conflict/activate_missing_orientation_and_early_start_safety_wins
    """
    bundle = setup_confirmed_grant()
    issue_visa_sponsorship(bundle["grant"])
    set_clock_to("2027-08-01T00:00:00Z")  # before start_date 2027-09-01

    resp = api.transition_grant(
        bundle["grant"]["id"], grant_transition_payload("ACTIVATE"),
        program_officer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_START_DATE_NOT_REACHED)

    grant = get_grant(bundle["grant"])
    assert grant["status"] == "CONFIRMED"
    assert grant.get("orientation_completed_at") is not None
    assert grant.get("interim_report_due_date") is None
