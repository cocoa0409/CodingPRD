"""Dual-variant calculations: one formula evaluated twice under two variants.

Two independent domains carry a dual-variant calculation in this specification.
Inspection scoring (PRD 3.5) is one calculation run under a provisional and a
final variant that differ in the on-site-correction credit, and the credited-hour
ledger (PRD 3.2) is one calculation whose apprentice branch is selected by the
subject's own ``license_type``.
"""
from test_helpers import (
    BOARD_ADMIN_HEADERS,
    apply_action,
    assert_points,
    create_candidate,
    create_establishment,
    create_school,
    create_violation_code,
    file_training_record,
    refresh_establishment,
    refresh_practitioner,
    setup_submitted_inspection,
    validate_success,
)


# --- Inspection scoring: provisional vs final on-site credit ------------------
def _glow_salon_submitted_with_two_corrected_minor_findings(api):
    """SAN-100 observed twice and REC-110 observed three times, both corrected.

    Neither code has ever appeared on a prior FINALIZED inspection of this
    establishment, so every repeat factor is 1.0 in both variants and the only
    input that moves between the passes is the on-site-correction credit.
    """
    san_100 = create_violation_code(
        api,
        severity="MINOR",
        base_points=5.0,
        fine_cents_base=4000,
        category="SANITATION",
        code="SAN-100",
    )
    rec_110 = create_violation_code(
        api,
        severity="MINOR",
        base_points=2.0,
        fine_cents_base=3000,
        category="RECORDKEEPING",
        code="REC-110",
    )
    establishment = create_establishment(
        api, station_capacity=4, establishment_type="SALON", county_code="NCA",
        legal_name="Glow Salon",
    )
    submitted = setup_submitted_inspection(
        api,
        establishment["id"],
        findings=[
            {
                "violation_code_id": san_100["id"],
                "observed_count": 2,
                "corrected_on_site": True,
            },
            {
                "violation_code_id": rec_110["id"],
                "observed_count": 3,
                "corrected_on_site": True,
            },
        ],
    )
    return {
        "establishment": establishment,
        "inspection": submitted["inspection"],
        "findings": submitted["findings"],
    }


def _read_finding(api, finding_id):
    return validate_success(api.get_violation_finding(finding_id, BOARD_ADMIN_HEADERS))


def test_provisional_variant_credits_half_the_points_of_two_corrected_findings(api):
    """PRD 3.5: "The on-site-correction credit is 0.50 for the provisional
    variant - the inspector's self-reported correction is granted in full at the
    point of submission" - so SAN-100 scores 5.0*1.0*2*1.0*(1-0.50) = 5.00 and
    REC-110 scores 2.0*1.0*3*1.0*(1-0.50) = 3.00, an 8.00 total that PRD 3.5
    bands as PASS because it is not above 10.00.  The final variant's fields are
    still null at submission.

    Design: Difficulty/dual_variant_calc/inspection_score_provisional_vs_final_on_site_credit
    """
    built = _glow_salon_submitted_with_two_corrected_minor_findings(api)
    inspection = built["inspection"]

    assert inspection["status"] == "PENDING_REVIEW"
    assert_points(
        inspection["provisional_adjusted_score"], 8.00, "provisional_adjusted_score"
    )
    assert inspection["provisional_outcome"] == "PASS"
    assert inspection["final_adjusted_score"] is None
    assert inspection["final_outcome"] is None

    san_finding = _read_finding(api, built["findings"][0]["id"])
    rec_finding = _read_finding(api, built["findings"][1]["id"])
    assert_points(san_finding["provisional_points"], 5.00, "SAN-100 provisional_points")
    assert_points(rec_finding["provisional_points"], 3.00, "REC-110 provisional_points")
    assert_points(
        san_finding["repeat_factor_provisional"], 1.0, "repeat_factor_provisional"
    )
    assert_points(
        rec_finding["repeat_factor_provisional"], 1.0, "repeat_factor_provisional"
    )
    assert san_finding["final_points"] is None
    assert rec_finding["final_points"] is None


def test_final_variant_halves_the_credit_and_flips_the_outcome_band(api):
    """PRD 3.5: the final variant's credit is "0.25 ... because board review
    halves an unverified credit", so the identical two findings score
    5.0*1.0*2*1.0*0.75 = 7.50 and 2.0*1.0*3*1.0*0.75 = 4.50 for a 12.00 total -
    above the 10.00 threshold, hence CONDITIONAL_PASS on the very row that read
    PASS at submission.  PRD 3.7 hop four then promotes the facility
    PENDING_INSPECTION -> ACTIVE on a CONDITIONAL_PASS.

    Design: Difficulty/dual_variant_calc/inspection_score_provisional_vs_final_on_site_credit
    """
    built = _glow_salon_submitted_with_two_corrected_minor_findings(api)
    inspection_id = built["inspection"]["id"]

    finalized = validate_success(
        api.finalize_inspection(inspection_id, BOARD_ADMIN_HEADERS)
    )
    assert finalized["status"] == "FINALIZED"
    assert_points(finalized["final_adjusted_score"], 12.00, "final_adjusted_score")
    assert finalized["final_outcome"] == "CONDITIONAL_PASS"

    # Both variants persist side by side on the one inspection row.
    assert_points(
        finalized["provisional_adjusted_score"], 8.00, "provisional_adjusted_score"
    )
    assert finalized["provisional_outcome"] == "PASS"

    san_finding = _read_finding(api, built["findings"][0]["id"])
    rec_finding = _read_finding(api, built["findings"][1]["id"])
    assert_points(san_finding["final_points"], 7.50, "SAN-100 final_points")
    assert_points(rec_finding["final_points"], 4.50, "REC-110 final_points")
    assert_points(san_finding["provisional_points"], 5.00, "SAN-100 provisional_points")
    assert_points(rec_finding["provisional_points"], 3.00, "REC-110 provisional_points")
    assert_points(san_finding["repeat_factor_final"], 1.0, "repeat_factor_final")
    assert_points(rec_finding["repeat_factor_final"], 1.0, "repeat_factor_final")

    establishment = refresh_establishment(api, built["establishment"]["id"])
    assert_points(establishment["demerit_balance"], 12.00, "demerit_balance")
    assert establishment["compliance_posture"] == "CLEAR"
    assert establishment["license_status"] == "ACTIVE"


# --- Credited hours: apprentice track vs school-equivalence track -------------
# PRD 3.2 pools the very same APPRENTICE_HOUR rows differently depending on the
# subject's own license_type, so the fixture below files byte-identical rows for
# two candidates of the same school.
_APPRENTICE_WEEK_DAYS = (
    "2026-08-03",
    "2026-08-04",
    "2026-08-05",
    "2026-08-06",
    "2026-08-07",
)


def _northside_academy_with_active_sponsor(api):
    """A 30.00-hour ACCREDITED school approved for apprenticeships, plus a sponsor.

    PRD 3.2 requires an apprentice record's sponsor to be a practitioner other
    than the subject whose ``license_type`` is one of the five licensed
    disciplines and whose ``license_status`` is ``ACTIVE``, and - where the
    subject is an ``APPRENTICE`` - that the sponsor's school carry
    ``apprenticeship_program_approved``.  Rita Vance's four eight-hour days also
    cover SANITATION and DISINFECTION, which PRD 3.2 demands before
    ``GRANT_EXAM_ELIGIBILITY`` is legal.
    """
    school = create_school(
        api,
        required_clock_hours=30.0,
        accreditation_status="ACCREDITED",
        apprenticeship_program_approved=True,
        county_code="NCA",
    )
    sponsor = create_candidate(
        api, school_id=school["id"], license_type="COSMETOLOGIST", full_name="Rita Vance"
    )
    for performed_on, discipline in (
        ("2026-07-01", "SANITATION"),
        ("2026-07-02", "DISINFECTION"),
        ("2026-07-03", "THEORY"),
        ("2026-07-04", "PRACTICAL"),
    ):
        file_training_record(
            api,
            sponsor["id"],
            credit_type="SCHOOL_CLOCK_HOUR",
            hours=8.0,
            performed_on=performed_on,
            discipline=discipline,
            school_id=school["id"],
        )
    apply_action(api, sponsor["id"], "GRANT_EXAM_ELIGIBILITY")
    sponsor = apply_action(
        api, sponsor["id"], "ISSUE_LICENSE", effective_at="2026-08-01T00:00:00.000Z"
    )
    return school, sponsor


def _file_one_week_of_nine_hour_days(api, candidate_id, sponsor_id):
    """Five 9.0-hour PRACTICAL apprentice days, all inside ISO week 2026-W32."""
    for performed_on in _APPRENTICE_WEEK_DAYS:
        file_training_record(
            api,
            candidate_id,
            credit_type="APPRENTICE_HOUR",
            hours=9.0,
            performed_on=performed_on,
            discipline="PRACTICAL",
            sponsor_practitioner_id=sponsor_id,
        )


def test_apprentice_track_pools_by_iso_week_caps_at_forty_and_credits_sixty_percent(api):
    """PRD 3.2: for a candidate whose ``license_type`` is ``APPRENTICE`` the
    apprentice-hour records "are pooled by the ISO-8601 week containing
    performed_on ... capped at 40 hours, the capped figure is multiplied by the
    apprenticeship credit ratio of 0.60".  Five 9.0-hour days claim 45.0 hours in
    ISO week 2026-W32, so 40.0 * 0.60 = 24.00 hours are credited and the
    candidate stays short of the school's 30.00-hour requirement.  The sponsor's
    own school ledger shows the separate eight-hour daily cap of PRD 3.2.

    Design: Difficulty/dual_variant_calc/apprentice_hour_credit_track_vs_school_equivalence_track
    """
    school, sponsor = _northside_academy_with_active_sponsor(api)
    apprentice = create_candidate(
        api, school_id=school["id"], license_type="APPRENTICE", full_name="Ana Ruiz"
    )
    _file_one_week_of_nine_hour_days(api, apprentice["id"], sponsor["id"])

    apprentice = refresh_practitioner(api, apprentice["id"])
    assert_points(
        apprentice["credited_hours_apprentice"], 24.00, "credited_hours_apprentice"
    )
    assert_points(apprentice["credited_hours_school"], 0.00, "credited_hours_school")
    assert_points(apprentice["credited_hours_total"], 24.00, "credited_hours_total")
    assert_points(
        apprentice["required_clock_hours_effective"],
        30.00,
        "required_clock_hours_effective",
    )
    assert apprentice["exam_eligible"] is False

    sponsor = refresh_practitioner(api, sponsor["id"])
    assert_points(sponsor["credited_hours_school"], 32.00, "sponsor credited_hours_school")
    assert sponsor["license_status"] == "ACTIVE"


def test_school_equivalence_track_pools_the_same_rows_by_date_at_a_ratio_of_one(api):
    """PRD 3.2: "For a candidate whose license_type is anything other than
    APPRENTICE ... the identical set of apprentice-hour records is instead pooled
    by performed_on UTC date, each date's total capped at the same eight-hour
    daily cap, credited at a ratio of 1.00".  The same five 9.0-hour days
    therefore credit 5 * 8.0 * 1.00 = 40.00 hours to a COSMETOLOGIST candidate,
    clearing the 30.00-hour requirement and flipping ``exam_eligible`` - while
    the APPRENTICE candidate holding byte-identical rows sits at 24.00.

    Design: Difficulty/dual_variant_calc/apprentice_hour_credit_track_vs_school_equivalence_track
    """
    school, sponsor = _northside_academy_with_active_sponsor(api)
    apprentice = create_candidate(
        api, school_id=school["id"], license_type="APPRENTICE", full_name="Ana Ruiz"
    )
    cosmetologist = create_candidate(
        api, school_id=school["id"], license_type="COSMETOLOGIST", full_name="Ben Cole"
    )
    _file_one_week_of_nine_hour_days(api, apprentice["id"], sponsor["id"])
    _file_one_week_of_nine_hour_days(api, cosmetologist["id"], sponsor["id"])

    cosmetologist = refresh_practitioner(api, cosmetologist["id"])
    assert_points(
        cosmetologist["credited_hours_apprentice"], 40.00, "credited_hours_apprentice"
    )
    assert_points(cosmetologist["credited_hours_school"], 0.00, "credited_hours_school")
    assert_points(cosmetologist["credited_hours_total"], 40.00, "credited_hours_total")
    assert_points(
        cosmetologist["required_clock_hours_effective"],
        30.00,
        "required_clock_hours_effective",
    )
    assert cosmetologist["exam_eligible"] is True

    # The identical rows on the APPRENTICE track credit a different figure.
    apprentice = refresh_practitioner(api, apprentice["id"])
    assert_points(
        apprentice["credited_hours_total"], 24.00, "apprentice credited_hours_total"
    )
    assert apprentice["exam_eligible"] is False
