"""Alumni engagement indices and follow-on eligibility (PRD §3.9)."""
from test_helpers import (
    add_country_program,
    assert_alumni_profile,
    assert_application,
    complete_grant_action,
    create_application_payload,
    create_cycle,
    get_alumni_profiles,
    get_grant,
    make_applicant_headers,
    open_cycle,
    set_clock_to,
    setup_completed_grant,
    setup_active_grant,
    submit_report,
    validate_success,
)


def test_alumni_engagement_provisional_counts_submitted_reports(api):
    """PRD §3.9: "The provisional index, `engagement_index_provisional` — the
    default surface shown to the grantee — starts from a base of 50 points,
    adds 10 points for every report of the grant in SUBMITTED or ACCEPTED
    status, subtracts 20 points per compliance strike, and is clamped so it
    never falls below 0 or exceeds 100."
    PRD §3.9: "The certified index, `engagement_index_certified` — the variant
    that governs eligibility decisions and the program office view — applies
    the same arithmetic but counts only ACCEPTED reports."

    One SUBMITTED (never reviewed) FINAL report, zero strikes: provisional
    60, certified 50 — the variants diverge on identical underlying data.

    Design: Difficulty/dual_variant_calc/alumni_engagement_provisional_vs_certified
    """
    bundle = setup_completed_grant()  # on-time FINAL left in SUBMITTED
    profiles = get_alumni_profiles(bundle["applicant"])
    assert len(profiles) == 1
    profile = profiles[0]
    assert_alumni_profile(profile)
    assert profile["engagement_index_provisional"] == 60, (
        f"50 base + 10 for the SUBMITTED report = 60, "
        f"got {profile['engagement_index_provisional']}"
    )
    assert profile["engagement_index_certified"] == 50, (
        f"no ACCEPTED reports yet: 50, got {profile['engagement_index_certified']}"
    )
    assert (
        profile["engagement_index_provisional"]
        != profile["engagement_index_certified"]
    )


def test_alumni_residency_mirror_gates_follow_on_eligibility(api):
    """PRD §3.9: "The profile's `residency_status` mirrors the linked
    residency ledger's state live, as of the read."
    PRD §3.9: "The profile's `follow_on_eligible` is ELIGIBLE exactly when the
    grant did not terminate early, the strikes number fewer than two, and the
    residency status is FULFILLED, WAIVED, or NOT_REQUIRED; in every other
    case it is INELIGIBLE."

    The completed grant's ledger is ACCRUING, so the otherwise clean grantee
    is INELIGIBLE until residency resolves.

    Design: Difficulty/dual_variant_calc/alumni_engagement_provisional_vs_certified
    """
    bundle = setup_completed_grant()  # subject_to_home_residency=True
    profiles = get_alumni_profiles(bundle["applicant"])
    profile = profiles[0]
    assert profile["residency_status"] == "ACCRUING", (
        "the profile mirrors the linked ledger live"
    )
    assert profile["terminated_early"] is False
    assert profile["compliance_strikes"] == 0
    assert profile["follow_on_eligible"] == "INELIGIBLE", (
        "ACCRUING residency is not FULFILLED, WAIVED, or NOT_REQUIRED"
    )


def test_alumni_follow_on_eligible_path_allows_follow_on_application(api):
    """PRD §3.9: "The profile's `follow_on_eligible` is ELIGIBLE exactly when
    the grant did not terminate early, the strikes number fewer than two, and
    the residency status is FULFILLED, WAIVED, or NOT_REQUIRED; in every other
    case it is INELIGIBLE."
    PRD §3.2: "A follow-on application — `is_follow_on` set to true — is only
    accepted when the applicant's most recent alumni profile by `created_at`
    reports `follow_on_eligible` as ELIGIBLE (`ERR_FOLLOW_ON_INELIGIBLE`)."

    Completed on time, zero strikes, visa not subject to home residency
    (ledger NOT_REQUIRED): ELIGIBLE, and the follow-on draft is accepted.

    Design: Corner/cross_cutting_complexity_layers/alumni_follow_on_eligible_path_allows_follow_on_application
    """
    bundle = setup_completed_grant(subject_to_home_residency=False)
    profile = get_alumni_profiles(bundle["applicant"])[0]
    assert profile["residency_status"] == "NOT_REQUIRED"
    assert profile["follow_on_eligible"] == "ELIGIBLE"

    cycle2 = create_cycle(
        academic_year="2028-2029", application_deadline="2028-12-01T23:59:59Z",
    )
    program2 = add_country_program(cycle2)
    open_cycle(cycle2)

    payload = create_application_payload(
        bundle["applicant"]["id"], cycle2["id"], program2["id"],
        project_title="Return Stay", project_summary="Follow-on research",
        proposed_duration_months=6, is_follow_on=True,
    )
    resp = api.create_application(
        payload, make_applicant_headers(bundle["applicant"]["id"]),
    )
    app2 = validate_success(resp, 201)
    assert_application(app2)
    assert app2["status"] == "DRAFT"
    assert app2["is_follow_on"] is True


def test_alumni_with_two_strikes_is_follow_on_ineligible(api):
    """PRD §3.9: "The profile's `follow_on_eligible` is ELIGIBLE exactly when
    the grant did not terminate early, the strikes number fewer than two, and
    the residency status is FULFILLED, WAIVED, or NOT_REQUIRED; in every other
    case it is INELIGIBLE."
    PRD §3.9: "A late first submission adds one to the grant's
    `compliance_strikes`, once; a resubmission never re-strikes, because
    `submitted_at` never moves."

    INTERIM late at 2028-01-15 (due 2028-01-01) and FINAL late at 2028-08-05
    (due 2028-07-31): exactly two strikes — the boundary is strikes < 2, so
    the grantee is INELIGIBLE; provisional 30 (50 + 10*2 - 20*2) diverges
    from certified 10 (50 + 0 - 40).

    Design: Corner/cross_cutting_complexity_layers/alumni_with_two_strikes_is_follow_on_ineligible
    """
    bundle = setup_active_grant(subject_to_home_residency=False)

    set_clock_to("2028-01-15T10:00:00Z")
    interim = submit_report(
        bundle["grant"], bundle["applicant"], report_type="INTERIM",
        content="Late midterm",
    )
    assert interim["late"] is True

    set_clock_to("2028-08-05T10:00:00Z")
    final = submit_report(
        bundle["grant"], bundle["applicant"], report_type="FINAL",
        content="Late final",
    )
    assert final["late"] is True

    grant = complete_grant_action(bundle["grant"])
    assert grant["status"] == "COMPLETED"
    assert get_grant(bundle["grant"])["compliance_strikes"] == 2

    profile = get_alumni_profiles(bundle["applicant"])[0]
    assert_alumni_profile(profile)
    assert profile["compliance_strikes"] == 2
    assert profile["follow_on_eligible"] == "INELIGIBLE", (
        "exactly two strikes meets the failure boundary (strikes < 2 fails)"
    )
    assert profile["engagement_index_provisional"] == 30
    assert profile["engagement_index_certified"] == 10
