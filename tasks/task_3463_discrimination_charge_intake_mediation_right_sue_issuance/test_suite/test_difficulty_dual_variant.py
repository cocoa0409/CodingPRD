"""Difficulty queue: dual-variant calculations — the same inputs must
diverge across the two pinned variants of one computation."""
from test_helpers import (
    TEST_USERS,
    add_days,
    assert_charge,
    assert_remedy_package,
    assign_investigator,
    charge_investigation_case_id,
    conciliation_for_charge,
    create_deferral_agency,
    create_employer,
    create_complainant,
    days_between,
    decline_mediation,
    draft_cause_determination,
    expected_remedy_valuation,
    expected_size_band,
    file_charge,
    issue_evidence_request,
    offer_mediation,
    read_charge,
    remedy_package_for_conciliation,
    review_determination,
    set_clock,
    submit_determination,
    table_offer,
    accept_conciliation,
    update_employer_payload,
    validate_ok,
)
from test_helpers import api_client

_INTAKE = TEST_USERS["intake_officer_headers"]


def test_timeliness_deadline_180_vs_300_deferral(api):
    """PRD section 3.2: "The filing deadline is then resolved: when an agency matched, its `filing_deadline_days` governs; when none matched, the federal default of 180 days applies."
    PRD section 3.2: "The same `incident_date`/`received_date` pair that is untimely for a no-agency state (a filing 181 days after the incident is dismissed) can be timely in a state whose agency sets a 300-day deadline."
    PRD section 3.2: "`investigation_owner` is `EEOC` when no agency matched or the policy is `EEOC_RETAINS_ALL` or `DUAL_FILE_DEFAULT`, `FEPA` when the policy is `FEPA_EXCLUSIVE`, and `NONE` when the charge is dismissed at intake."
    PRD section 3.2: "`dual_filed` is true exactly when an agency matched and its policy is `DUAL_FILE_DEFAULT` or `FEPA_EXCLUSIVE`."

    Design: Difficulty/dual_variant_calc/timeliness_deadline_180_vs_300_deferral
    """
    # CA has a 300-day deferral agency; FL has none (federal 180-day default).
    # The boot clock is 2026-09-01, exactly 181 days after the 2026-03-04 incident.
    create_deferral_agency(
        state_code="CA", filing_deadline_days=300,
        work_sharing_policy="DUAL_FILE_DEFAULT", covers_age=True,
        agency_name="CA FEPA",
    )
    emp_ca = create_employer(state_code="CA", employee_count_current=40,
                             legal_name="CA Employer")
    emp_fl = create_employer(state_code="FL", employee_count_current=40,
                             legal_name="FL Employer")
    cp_1 = create_complainant(full_name="Pat One", email="p1@x.com")
    cp_2 = create_complainant(full_name="Pat Two", email="p2@x.com")

    chg_ca = file_charge(emp_ca, cp_1, basis_codes=["RACE"],
                         incident_date="2026-03-04", harm_description="demoted",
                         employee_count_at_incident=40)
    chg_fl = file_charge(emp_fl, cp_2, basis_codes=["RACE"],
                         incident_date="2026-03-04", harm_description="demoted",
                         employee_count_at_incident=40)

    # DEFERRAL_EXTENDED_300 variant: 2026-03-04 + 300 days = 2026-12-29, timely.
    assert_charge(chg_ca)
    assert chg_ca["case_status"] == "DOCKETED"
    assert chg_ca["jurisdiction_outcome"] == "TIMELY_CONFIRMED"
    assert chg_ca["filing_deadline_date"][:10] == add_days("2026-03-04", 300) == "2026-12-29"
    assert chg_ca["investigation_owner"] == "EEOC"
    assert chg_ca["dual_filed"] is True

    # STANDARD_180 variant: 2026-03-04 + 180 days = 2026-08-31; received
    # 2026-09-01 is one day late, so the identical dates dismiss instead.
    assert_charge(chg_fl)
    assert chg_fl["case_status"] == "DISMISSED_UNTIMELY"
    assert chg_fl["jurisdiction_outcome"] == "DISMISSED_UNTIMELY"
    assert chg_fl["filing_deadline_date"][:10] == add_days("2026-03-04", 180) == "2026-08-31"
    assert chg_fl["investigation_owner"] == "NONE"
    assert chg_fl["dual_filed"] is False


def test_remedy_provisional_vs_final_divergence(api):
    """PRD section 3.7: "While the conciliation is open (`INITIATED`, `OFFER_TABLED`, or `COUNTERED`), the package is `PROVISIONAL`: `band_used` is the employer's current `size_band` at computation time (so the employer update of §3.1 re-bands it in place), and `projection_date` is pinned to the conciliation-initiation date."
    PRD section 3.7: "At acceptance the package flips to `FINAL`: `band_used` is re-derived from the charge's immutable `employee_count_at_incident` snapshot — never from the employer's mutable headcount — and `projection_date` is pinned to the acceptance date."
    PRD section 3.7: "`capped_nonpecuniary_cents` is the smaller of (`compensatory_damages_cents` plus `punitive_damages_cents`) and the statutory cap tier for `band_used` — 5000000 cents for `FROM_15_TO_19` and `FROM_20_TO_100` alike, 10000000 cents for `FROM_101_TO_200`, 20000000 cents for `FROM_201_TO_500`, and 30000000 cents for `OVER_500`."

    Design: Difficulty/dual_variant_calc/remedy_provisional_vs_final_divergence
    """
    create_deferral_agency(
        state_code="CA", filing_deadline_days=300,
        work_sharing_policy="DUAL_FILE_DEFAULT", covers_age=True,
        agency_name="CA FEPA",
    )
    employer = create_employer(state_code="CA", employee_count_current=90,
                               legal_name="Growth Co")
    complainant = create_complainant(full_name="Pat Three", email="p3@x.com")
    charge = file_charge(employer, complainant, basis_codes=["RACE"],
                         incident_date="2026-03-05", harm_description="fired",
                         employee_count_at_incident=90)

    mediation = offer_mediation(charge)
    decline_mediation(charge, mediation, party="complainant")
    case_id = charge_investigation_case_id(charge["id"])
    assign_investigator(case_id, "inv-001")
    issue_evidence_request(case_id, "inv-001", request_type="POSITION_STATEMENT")

    # The employer grows to 250 staff before the cause approval, so the
    # PROVISIONAL package will band FROM_201_TO_500 (cap 20000000).
    patched = validate_ok(
        api_client.update_employer(
            employer["id"], update_employer_payload(employee_count_current=250),
            _INTAKE,
        )
    )
    assert patched["size_band"] == expected_size_band(250) == "FROM_201_TO_500"

    determination = draft_cause_determination(
        case_id, "inv-001",
        rationale="docs show pretext",
        back_pay_cents=1_000_000, front_pay_cents=500_000,
        compensatory_damages_cents=3_000_000, punitive_damages_cents=3_000_000,
        harm_start_date="2026-03-05",
    )
    submit_determination(determination["id"], "inv-001")

    # Approving at 2027-01-15 pins the PROVISIONAL projection date there.
    set_clock("2027-01-15T00:00:00Z")
    review_determination(determination["id"], "APPROVE", director_user_id="dir-001")

    conciliation = conciliation_for_charge(charge["id"])
    package = remedy_package_for_conciliation(conciliation["id"])
    assert_remedy_package(package)

    provisional_days = days_between("2026-03-05", "2027-01-15")
    provisional = expected_remedy_valuation(
        1_000_000, 500_000, 3_000_000, 3_000_000,
        "FROM_201_TO_500", provisional_days,
    )
    assert package["valuation_variant"] == "PROVISIONAL"
    assert package["band_used"] == provisional["band_used"] == "FROM_201_TO_500"
    assert package["interest_days"] == provisional["interest_days"] == 316
    assert package["capped_nonpecuniary_cents"] == provisional["capped_nonpecuniary_cents"] == 6_000_000
    assert package["total_cents"] == provisional["total_cents"] == 7_564_932

    offer = table_offer(conciliation, 7_000_000, "COMMISSION", charge,
                        director_user_id="dir-001")

    # Accepting at 2027-02-10 pins the FINAL projection date there and re-bands
    # from the incident snapshot (90 -> FROM_20_TO_100, cap 5000000).
    set_clock("2027-02-10T00:00:00Z")
    accept_conciliation(offer, charge)

    final_package = remedy_package_for_conciliation(conciliation["id"])
    final_days = days_between("2026-03-05", "2027-02-10")
    final = expected_remedy_valuation(
        1_000_000, 500_000, 3_000_000, 3_000_000,
        "FROM_20_TO_100", final_days,
    )
    assert final_package["valuation_variant"] == "FINAL"
    assert final_package["band_used"] == final["band_used"] == "FROM_20_TO_100"
    assert final_package["interest_days"] == final["interest_days"] == 342
    assert final_package["back_pay_interest_cents"] == final["back_pay_interest_cents"] == 46_849
    assert final_package["front_pay_interest_cents"] == final["front_pay_interest_cents"] == 23_425
    assert final_package["capped_nonpecuniary_cents"] == final["capped_nonpecuniary_cents"] == 5_000_000
    assert final_package["total_cents"] == final["total_cents"] == 6_570_274
    # FINAL is LOWER than PROVISIONAL despite 26 extra interest days: the
    # snapshot band caps the 6000000 nonpecuniary at 5000000.
    assert final_package["total_cents"] < package["total_cents"]

    settled = read_charge(charge["id"])
    assert settled["case_status"] == "CLOSED_SETTLED"
    assert settled["settled_amount_cents"] == 7_000_000
    assert settled["settled_via"] == "CONCILIATION"
