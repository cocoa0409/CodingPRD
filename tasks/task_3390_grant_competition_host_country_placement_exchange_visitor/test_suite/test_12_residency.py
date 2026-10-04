"""Two-year home residency: accrual, overlap, waivers (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    add_residency_stay,
    assert_residency_ledger,
    create_stay_payload,
    decide_residency_waiver,
    make_applicant_headers,
    request_residency_waiver,
    setup_accruing_ledger,
    setup_active_grant,
    validate_error,
    validate_success,
)


def test_residency_stay_before_accrual_start_rejected(api, program_officer_headers):
    """PRD §3.9: "A stay whose `start_date` precedes the ledger's
    `accrual_start_date` is rejected with `ERR_STAY_BEFORE_ACCRUAL_START`, and
    a stay whose end precedes its start is `ERR_VALIDATION`."

    The ledger accrues from the grant's end_date 2028-07-01; a stay starting
    2028-06-15 precedes it.

    Design: Corner/state_machines/residency_stay_before_accrual_start_rejected
    """
    bundle = setup_accruing_ledger()
    ledger = bundle["ledger"]
    assert ledger["status"] == "ACCRUING"

    resp = api.add_residency_stay(
        ledger["id"], create_stay_payload("2028-06-15", "2028-07-15"),
        make_applicant_headers(bundle["applicant"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STAY_BEFORE_ACCRUAL_START)

    fetched = validate_success(
        api.get_residency_ledger(ledger["id"], program_officer_headers)
    )
    assert fetched["accrued_days"] == 0
    assert fetched["stays"] == []


def test_residency_stay_while_pending_returns_residency_not_accruing(api):
    """PRD §3.9: "While the ledger is ACCRUING — recording a stay or
    requesting a waiver against a ledger in any other state is rejected with
    `ERR_RESIDENCY_NOT_ACCRUING` — the grantee records home-country stays by
    supplying `start_date` and `end_date`."

    While the grant is still ACTIVE the ledger sits in PENDING.

    Design: Corner/state_machines/residency_stay_while_pending_returns_residency_not_accruing
    """
    bundle = setup_active_grant()  # grant ACTIVE, ledger PENDING
    ledger = bundle["ledger"]
    assert ledger["status"] == "PENDING"

    resp = api.add_residency_stay(
        ledger["id"], create_stay_payload("2027-10-01", "2027-10-31"),
        make_applicant_headers(bundle["applicant"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RESIDENCY_NOT_ACCRUING)


def test_residency_waiver_deny_resumes_accruing(api):
    """PRD §3.9: "The waiver loop runs alongside accrual: the grantee requests
    a waiver with a `waiver_reason`, moving ACCRUING → WAIVER_PENDING with the
    reason stored; a `ProgramOfficer` then approves it (WAIVER_PENDING →
    WAIVED) or denies it (WAIVER_PENDING → ACCRUING)."
    PRD §3.9: "`accrued_days` is the running sum across all recorded stays."

    A 150-day stay (2028-07-01 to 2028-11-27 inclusive) survives the
    waiver-deny round trip intact.

    Design: Corner/state_machines/residency_waiver_deny_resumes_accruing
    """
    bundle = setup_accruing_ledger()
    ledger = bundle["ledger"]

    ledger = add_residency_stay(ledger, bundle["applicant"], "2028-07-01", "2028-11-27")
    assert_residency_ledger(ledger)
    assert ledger["accrued_days"] == 150

    pending = request_residency_waiver(
        ledger, bundle["applicant"], waiver_reason="Government employment abroad",
    )
    assert pending["status"] == "WAIVER_PENDING"
    assert pending["waiver_reason"] == "Government employment abroad"

    denied = decide_residency_waiver(ledger, "DENY_WAIVER")
    assert denied["status"] == "ACCRUING", "denial returns the ledger to accrual"
    assert denied["accrued_days"] == 150, "denial preserves recorded accrual"


def test_residency_waived_ledger_rejects_further_stays(api, program_officer_headers):
    """PRD §3.9: "While the ledger is ACCRUING — recording a stay or
    requesting a waiver against a ledger in any other state is rejected with
    `ERR_RESIDENCY_NOT_ACCRUING` — the grantee records home-country stays by
    supplying `start_date` and `end_date`."
    PRD §3.9: "The waiver loop runs alongside accrual: the grantee requests a
    waiver with a `waiver_reason`, moving ACCRUING → WAIVER_PENDING with the
    reason stored; a `ProgramOfficer` then approves it (WAIVER_PENDING →
    WAIVED) or denies it (WAIVER_PENDING → ACCRUING)."

    Design: Corner/state_machines/residency_waived_ledger_rejects_further_stays
    """
    bundle = setup_accruing_ledger()
    ledger = bundle["ledger"]
    add_residency_stay(ledger, bundle["applicant"], "2028-07-01", "2028-11-27")

    request_residency_waiver(
        ledger, bundle["applicant"],
        waiver_reason="International organization service",
    )
    waived = decide_residency_waiver(ledger, "APPROVE_WAIVER")
    assert waived["status"] == "WAIVED"

    resp = api.add_residency_stay(
        ledger["id"], create_stay_payload("2028-11-28", "2028-12-31"),
        make_applicant_headers(bundle["applicant"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RESIDENCY_NOT_ACCRUING)

    fetched = validate_success(
        api.get_residency_ledger(ledger["id"], program_officer_headers)
    )
    assert fetched["status"] == "WAIVED"
    assert fetched["accrued_days"] == 150, "WAIVED is terminal; accrual is frozen"


def test_residency_one_day_short_of_730_stays_accruing(api):
    """PRD §3.9: "Each stay's day count spans both endpoints inclusively —
    the difference between end and start in days, plus one — and the stay is
    appended to the ledger's `stays`, each entry keeping its `start_date`,
    `end_date`, and `day_count`; `accrued_days` is the running sum across all
    recorded stays."
    PRD §3.9: "The moment an appended stay pushes `accrued_days` to at least
    730 — the requirement, at an inclusive boundary — the ledger moves
    ACCRUING → FULFILLED."

    365 days (2028-07-01..2029-06-30) plus 364 days (2029-07-01..2030-06-29)
    total 729 — one day short.

    Design: Difficulty/boundary_precision_check/residency_exactly_730_days_fulfills
    """
    bundle = setup_accruing_ledger()
    ledger = bundle["ledger"]

    ledger = add_residency_stay(ledger, bundle["applicant"], "2028-07-01", "2029-06-30")
    assert ledger["accrued_days"] == 365
    assert ledger["status"] == "ACCRUING"

    ledger = add_residency_stay(ledger, bundle["applicant"], "2029-07-01", "2030-06-29")
    assert_residency_ledger(ledger)
    assert ledger["accrued_days"] == 729
    assert ledger["status"] == "ACCRUING", "729 is one day short of the requirement"


def test_residency_exactly_730_days_fulfills(api):
    """PRD §3.9: "The moment an appended stay pushes `accrued_days` to at
    least 730 — the requirement, at an inclusive boundary — the ledger moves
    ACCRUING → FULFILLED."

    A final one-day stay (2030-06-30) lands the running sum on exactly 730;
    the inclusive boundary fulfills the requirement.

    Design: Difficulty/boundary_precision_check/residency_exactly_730_days_fulfills
    """
    bundle = setup_accruing_ledger()
    ledger = bundle["ledger"]
    add_residency_stay(ledger, bundle["applicant"], "2028-07-01", "2029-06-30")
    add_residency_stay(ledger, bundle["applicant"], "2029-07-01", "2030-06-29")

    ledger = add_residency_stay(ledger, bundle["applicant"], "2030-06-30", "2030-06-30")
    assert_residency_ledger(ledger)
    assert ledger["accrued_days"] == 730
    assert ledger["status"] == "FULFILLED", (
        "the >= 730 boundary is inclusive; exactly 730 fulfills"
    )


def test_residency_stay_touching_existing_end_overlaps(api, program_officer_headers):
    """PRD §3.9: "Stays on one ledger are closed intervals: a new stay
    overlaps an existing one unless it ends strictly before the existing stay
    begins or begins strictly after the existing stay ends, and a new stay
    that begins exactly on the day an existing one ends counts as overlapping,
    because no calendar day may be counted twice (`ERR_STAY_OVERLAP`)."

    Existing stay [2028-07-01, 2028-12-31] (184 days); a new stay starting
    2028-12-31 — the exact day the existing one ends — is rejected.

    Design: Difficulty/resource_temporal_overlap/residency_stay_closed_interval_overlap
    """
    bundle = setup_accruing_ledger()
    ledger = bundle["ledger"]
    ledger = add_residency_stay(ledger, bundle["applicant"], "2028-07-01", "2028-12-31")
    assert ledger["accrued_days"] == 184

    resp = api.add_residency_stay(
        ledger["id"], create_stay_payload("2028-12-31", "2029-03-30"),
        make_applicant_headers(bundle["applicant"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STAY_OVERLAP)

    fetched = validate_success(
        api.get_residency_ledger(ledger["id"], program_officer_headers)
    )
    assert fetched["accrued_days"] == 184, "a rejected stay must not accrue"
    assert len(fetched["stays"]) == 1


def test_residency_stay_starting_next_day_is_accepted(api, program_officer_headers):
    """PRD §3.9: "Stays on one ledger are closed intervals: a new stay
    overlaps an existing one unless it ends strictly before the existing stay
    begins or begins strictly after the existing stay ends, and a new stay
    that begins exactly on the day an existing one ends counts as overlapping,
    because no calendar day may be counted twice (`ERR_STAY_OVERLAP`)."

    Starting 2029-01-01 — strictly after the existing stay's 2028-12-31 end —
    is legal and adds 90 days: 184 + 90 = 274.

    Design: Difficulty/resource_temporal_overlap/residency_stay_closed_interval_overlap
    """
    bundle = setup_accruing_ledger()
    ledger = bundle["ledger"]
    add_residency_stay(ledger, bundle["applicant"], "2028-07-01", "2028-12-31")

    ledger = add_residency_stay(ledger, bundle["applicant"], "2029-01-01", "2029-03-31")
    assert_residency_ledger(ledger)
    assert ledger["accrued_days"] == 274, (
        f"184 + 90 = 274, got {ledger['accrued_days']}"
    )
    assert len(ledger["stays"]) == 2
