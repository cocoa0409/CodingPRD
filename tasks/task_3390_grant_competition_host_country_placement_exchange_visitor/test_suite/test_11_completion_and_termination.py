"""Grant completion and early termination cascades (PRD §3.8)."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    assert_alumni_profile,
    assert_award_conservation,
    get_alumni_profiles,
    get_grant,
    get_visa_ledger,
    grant_transition_payload,
    set_clock_to,
    setup_active_grant,
    setup_terminated_grant,
    terminate_grant,
    validate_error,
    validate_success,
)

JP_PROGRAM = {
    "country_code": "JP",
    "min_duration_months": 3,
    "max_duration_months": 12,
    "monthly_stipend_standard_cents": 300001,
    "monthly_stipend_high_cents": 350000,
    "travel_allowance_cents": 100001,
    "health_benefit_monthly_cents": 19999,
}
JP_APPLICATION = {"proposed_duration_months": 3, "dependents_count": 0}
JP_WINDOW = {
    "start_date": "2027-09-01T00:00:00Z", "end_date": "2027-12-01T00:00:00Z",
}
# final_total = (300001 + 19999)*3 + 100001 = 1060001; terminate 2027-10-11
# is 40 served days -> 1 served month, 2 unserved; monthly rate
# round_half_up(1060001 / 3) = 353334.


def _instant(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def test_grant_complete_without_final_report_rejected(api, program_officer_headers):
    """PRD §3.8: "Normal completion is a `ProgramOfficer` action on an ACTIVE
    grant, permitted once the logical clock has reached `end_date`
    (`ERR_END_DATE_NOT_REACHED`) and a FINAL report for the grant exists in
    SUBMITTED or ACCEPTED status (`ERR_FINAL_REPORT_MISSING`)."

    Design: Corner/state_machines/grant_complete_without_final_report_rejected
    """
    bundle = setup_active_grant()  # visa ACTIVE; no FINAL report submitted
    set_clock_to("2028-07-01T00:00:00Z")  # end_date reached

    resp = api.transition_grant(
        bundle["grant"]["id"], grant_transition_payload("COMPLETE"),
        program_officer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FINAL_REPORT_MISSING)

    assert get_grant(bundle["grant"])["status"] == "ACTIVE", (
        "a rejected COMPLETE must not partially cascade"
    )
    visa = validate_success(
        api.get_visa_sponsorship(bundle["visa"]["id"], program_officer_headers)
    )
    assert visa["status"] == "ACTIVE"
    assert get_alumni_profiles(bundle["applicant"]) == [], (
        "no alumni profile may be created by a rejected completion"
    )


def test_grant_complete_before_end_date_rejected(api, program_officer_headers):
    """PRD §3.8: "Normal completion is a `ProgramOfficer` action on an ACTIVE
    grant, permitted once the logical clock has reached `end_date`
    (`ERR_END_DATE_NOT_REACHED`) and a FINAL report for the grant exists in
    SUBMITTED or ACCEPTED status (`ERR_FINAL_REPORT_MISSING`)."

    Design: Corner/state_machines/grant_complete_before_end_date_rejected
    """
    bundle = setup_active_grant()
    set_clock_to("2028-06-01T00:00:00Z")  # one month before end_date 2028-07-01

    resp = api.transition_grant(
        bundle["grant"]["id"], grant_transition_payload("COMPLETE"),
        program_officer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_END_DATE_NOT_REACHED)

    assert get_grant(bundle["grant"])["status"] == "ACTIVE"


def test_termination_reconciliation_rounds_per_month_then_multiplies(
    api,
):
    """PRD §3.8: "Served months are the whole days between `start_date` and
    the termination date, divided by thirty and rounded down; unserved months
    are `duration_months` minus the served months, and always at least one
    because the clock precedes `end_date`."
    PRD §3.8: "The monthly rate is computed first — `final_total_cents`
    divided by `duration_months`, rounded half up to whole cents — and only
    then multiplied: `repayment_cents` is the unserved months times that rate,
    and `earned_cents` is the served months times that rate."

    final_total 1060001 over 3 months; terminating 40 days in serves 1 month:
    rate round_half_up(1060001/3) = 353334; earned 353334; repayment 706668.

    Design: Difficulty/combinatorial_formula/termination_reconciliation_rounding_order
    """
    bundle = setup_terminated_grant(
        terminate_at="2027-10-11T00:00:00Z",
        termination_reason="Family emergency",
        program_overrides=JP_PROGRAM,
        application_overrides=JP_APPLICATION,
        **JP_WINDOW,
    )
    grant = bundle["grant"]
    assert grant["status"] == "TERMINATED_EARLY"
    assert grant["final_total_cents"] == 1060001
    assert grant["earned_cents"] == 353334, (
        f"1 served month at rate 353334, got {grant['earned_cents']}"
    )
    assert grant["repayment_cents"] == 706668, (
        f"2 unserved months at rate 353334, got {grant['repayment_cents']}"
    )


def test_termination_reconciliation_adjustment_absorbs_rounding(api):
    """PRD §3.8: "Finally, `reconciliation_adjustment_cents` is whatever
    remains so that earned plus repayment plus adjustment equals
    `final_total_cents` exactly; it absorbs the per-month rounding remainder
    and may be negative, zero, or positive."
    PRD §3.8: "Summing first and rounding once would give a different cent
    value and is wrong."

    1060001 - 353334 - 706668 = -1: the per-month rounding remainder surfaces
    as a -1 cent adjustment.

    Design: Difficulty/combinatorial_formula/termination_reconciliation_rounding_order
    """
    bundle = setup_terminated_grant(
        terminate_at="2027-10-11T00:00:00Z",
        termination_reason="Family emergency",
        program_overrides=JP_PROGRAM,
        application_overrides=JP_APPLICATION,
        **JP_WINDOW,
    )
    grant = bundle["grant"]
    assert grant["reconciliation_adjustment_cents"] == -1, (
        f"expected -1, got {grant['reconciliation_adjustment_cents']}"
    )
    assert_award_conservation(grant)


def test_early_termination_cascades_to_visa_and_ledger(
    api, program_officer_headers,
):
    """PRD §3.8: "The cascade then moves the sponsorship ACTIVE → ENDED_EARLY,
    opens residency accrual from the termination date when the grantee is
    subject to home residency, creates the AlumniProfile with
    `terminated_early` true, and resolves any still-OPEN incident of the grant
    with outcome TERMINATE."

    Design: Difficulty/transitive_cascade/early_termination_cascades_to_visa_ledger_alumni
    """
    bundle = setup_active_grant(application_overrides={"dependents_count": 1})
    ledger_before = get_visa_ledger(bundle["visa"])
    assert ledger_before["status"] == "PENDING", (
        "the ledger waits in PENDING while the grant runs"
    )

    set_clock_to("2027-10-11T00:00:00Z")  # 40 days into the grant
    terminate_grant(bundle["grant"], "Program closure")

    visa = validate_success(
        api.get_visa_sponsorship(bundle["visa"]["id"], program_officer_headers)
    )
    assert visa["status"] == "ENDED_EARLY", (
        "the grant termination mutates the sponsorship, not any visa endpoint call"
    )

    ledger = get_visa_ledger(bundle["visa"])
    assert ledger["status"] == "ACCRUING"
    assert _instant(ledger["accrual_start_date"]) == _instant("2027-10-11T00:00:00Z"), (
        "accrual opens from the termination date, not the original end_date"
    )


def test_early_termination_creates_alumni_profile_and_reconciles_award(api):
    """PRD §3.8: "The cascade then moves the sponsorship ACTIVE → ENDED_EARLY,
    opens residency accrual from the termination date when the grantee is
    subject to home residency, creates the AlumniProfile with
    `terminated_early` true, and resolves any still-OPEN incident of the grant
    with outcome TERMINATE."
    PRD §2.10: "Award conservation: at early termination, the earned portion,
    the repayment portion, and the reconciliation adjustment always sum
    exactly to the grant's final total award."

    final_total 3850000 over 10 months divides exactly: rate 385000; 1 served
    month earns 385000; 9 unserved months repay 3465000; adjustment 0.

    Design: Difficulty/transitive_cascade/early_termination_cascades_to_visa_ledger_alumni
    """
    bundle = setup_terminated_grant(
        terminate_at="2027-10-11T00:00:00Z",
        termination_reason="Program closure",
        application_overrides={"dependents_count": 1},
    )
    grant = bundle["grant"]
    assert grant["earned_cents"] == 385000
    assert grant["repayment_cents"] == 3465000
    assert grant["reconciliation_adjustment_cents"] == 0, (
        "an exactly-dividing rate leaves no rounding remainder"
    )

    profiles = get_alumni_profiles(bundle["applicant"])
    assert len(profiles) == 1
    profile = profiles[0]
    assert_alumni_profile(profile)
    assert profile["terminated_early"] is True
    assert profile["grant_id"] == grant["id"]


def test_award_money_conserved_on_termination(api):
    """PRD §2.10: "Award conservation: at early termination, the earned
    portion, the repayment portion, and the reconciliation adjustment always
    sum exactly to the grant's final total award."

    353334 + 706668 + (-1) == 1060001: no cent is created or destroyed by the
    terminate/compensate pair.

    Design: Difficulty/compensating_invariant/award_money_conservation_on_termination
    """
    bundle = setup_terminated_grant(
        terminate_at="2027-10-11T00:00:00Z",
        termination_reason="Medical evacuation",
        program_overrides=JP_PROGRAM,
        application_overrides=JP_APPLICATION,
        **JP_WINDOW,
    )
    grant = bundle["grant"]
    assert grant["final_total_cents"] == 1060001
    assert_award_conservation(grant)

    persisted = get_grant(grant)
    assert_award_conservation(persisted)


def test_termination_reason_recorded_and_figures_persist(api):
    """PRD §3.8: "Early termination applies to an ACTIVE or SUSPENDED grant,
    either as a `ProgramOfficer` action — which may carry a
    `termination_reason` that is recorded on the grant — or forced by an
    incident resolved with outcome TERMINATE."
    PRD §2.10: "Award conservation: at early termination, the earned portion,
    the repayment portion, and the reconciliation adjustment always sum
    exactly to the grant's final total award."

    Design: Difficulty/compensating_invariant/award_money_conservation_on_termination
    """
    bundle = setup_terminated_grant(
        terminate_at="2027-10-11T00:00:00Z",
        termination_reason="Medical evacuation",
        program_overrides=JP_PROGRAM,
        application_overrides=JP_APPLICATION,
        **JP_WINDOW,
    )
    grant = get_grant(bundle["grant"])
    assert grant["status"] == "TERMINATED_EARLY"
    assert grant["termination_reason"] == "Medical evacuation"
    assert (
        grant["earned_cents"] + grant["repayment_cents"]
        == grant["final_total_cents"] - grant["reconciliation_adjustment_cents"]
    ), "the split reconciles against the final total to the cent"
