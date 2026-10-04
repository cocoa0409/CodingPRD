"""Corner queue: calculation-rule claims (size screen, cap tiers, priority
score, consolidation threshold)."""
from test_helpers import (
    TEST_USERS,
    days_between,
    create_deferral_agency,
    create_employer,
    create_complainant,
    create_systemic_case,
    expected_priority_score,
    expected_remedy_valuation,
    file_charge,
    issue_evidence_requests,
    link_charge,
    make_respondent_rep_headers,
    remedy_package_for_conciliation,
    respond_evidence_payload,
    set_clock,
    setup_conciliation,
    setup_gathering,
    update_employer_payload,
    validate_ok,
    validate_paginated,
)
from test_helpers import api_client

_INTAKE = TEST_USERS["intake_officer_headers"]
_DIRECTOR = TEST_USERS["director_headers"]


def test_age_basis_size_and_agency_coverage_matrix(api):
    """PRD section 3.2: "An `AGE` basis survives only when the snapshot headcount is at least 20 and either no deferral agency matched or the matched agency's `covers_age` is true; when the state agency's statute does not cover age, an `AGE` basis is stripped from coverage even against a 20-or-more-employee employer."
    PRD section 3.2: "Every other basis survives when the snapshot headcount is at least 15."
    PRD section 3.2: "The surviving bases are recorded in `covered_bases`, preserving the order of `basis_codes`."

    Design: Corner/calculations/age_basis_size_and_agency_coverage_matrix
    """
    create_deferral_agency(
        state_code="GA", filing_deadline_days=300,
        work_sharing_policy="DUAL_FILE_DEFAULT", covers_age=False,
        agency_name="GA FEPA",
    )
    emp_ga = create_employer(state_code="GA", employee_count_current=40,
                             legal_name="GA Co")
    emp_fl = create_employer(state_code="FL", employee_count_current=40,
                             legal_name="FL Co")
    complainants = [
        create_complainant(full_name=f"Drew {n}", email=f"d{n}@x.com")
        for n in ("One", "Two", "Three", "Four")
    ]

    # T1: AGE-only at 17 < 20 (no agency on FL) -> nothing survives.
    t1 = file_charge(emp_fl, complainants[0], basis_codes=["AGE"],
                     incident_date="2026-06-01",
                     harm_description="age-only, 17 staff",
                     employee_count_at_incident=17)
    assert t1["case_status"] == "DISMISSED_NO_JURISDICTION"
    assert t1["covered_bases"] == []

    # T2: the ADEA threshold is inclusive at 20 -> docketed.
    t2 = file_charge(emp_fl, complainants[1], basis_codes=["AGE"],
                     incident_date="2026-06-01",
                     harm_description="age-only, 20 staff",
                     employee_count_at_incident=20)
    assert t2["case_status"] == "DOCKETED"
    assert t2["covered_bases"] == ["AGE"]

    # T3: 25 >= 20 but the matched GA agency's statute excludes age -> stripped.
    t3 = file_charge(emp_ga, complainants[2], basis_codes=["AGE"],
                     incident_date="2026-06-01",
                     harm_description="age-only, 25 staff, GA agency excludes age",
                     employee_count_at_incident=25)
    assert t3["case_status"] == "DISMISSED_NO_JURISDICTION"
    assert t3["covered_bases"] == []

    # T4: mixed [RACE, AGE] at 17: AGE stripped, RACE survives at >= 15.
    t4 = file_charge(emp_fl, complainants[3], basis_codes=["RACE", "AGE"],
                     incident_date="2026-06-01", harm_description="mixed, 17 staff",
                     employee_count_at_incident=17)
    assert t4["case_status"] == "DOCKETED"
    assert t4["covered_bases"] == ["RACE"]


def test_remedy_cap_tier_boundary_100_vs_101(api):
    """PRD section 3.1: "Band boundaries are inclusive at the low end: a headcount of 14 lands `UNDER_15`, 15 lands `FROM_15_TO_19`, 20 lands `FROM_20_TO_100`, 100 stays `FROM_20_TO_100`, and 101 lands `FROM_101_TO_200`."
    PRD section 3.1: "Updating an employer (the intake officer may patch `employee_count_current` and/or `legal_name`) increments the employer's `version` by 1, recomputes `size_band`, and re-bands every `PROVISIONAL` `RemedyPackage` attached to that employer's non-terminal conciliations — each re-banded package keeps its original `projection_date`, only the cap tier moves."
    PRD section 3.7: "`capped_nonpecuniary_cents` is the smaller of (`compensatory_damages_cents` plus `punitive_damages_cents`) and the statutory cap tier for `band_used` — 5000000 cents for `FROM_15_TO_19` and `FROM_20_TO_100` alike, 10000000 cents for `FROM_101_TO_200`, 20000000 cents for `FROM_201_TO_500`, and 30000000 cents for `OVER_500`."

    Design: Corner/calculations/remedy_cap_tier_boundary_100_vs_101
    """
    base = setup_conciliation(
        cause_components={
            "rationale": "emotional harm testimony",
            "back_pay_cents": 0, "front_pay_cents": 0,
            "compensatory_damages_cents": 6_000_000, "punitive_damages_cents": 0,
            "harm_start_date": "2026-06-01",
        },
        employee_count=100, investigator_user_id="inv-029",
        director_user_id="dir-009",
    )
    employer = base["employer"]
    conciliation = base["conciliation"]
    interest_days = days_between("2026-06-01", "2026-09-01")  # zero wage parts

    # At 100 staff the inclusive upper edge keeps FROM_20_TO_100 (cap 5000000).
    package = base["remedy_package"]
    expected_100 = expected_remedy_valuation(
        0, 0, 6_000_000, 0, "FROM_20_TO_100", interest_days
    )
    assert package["band_used"] == "FROM_20_TO_100"
    assert package["capped_nonpecuniary_cents"] == expected_100["capped_nonpecuniary_cents"] == 5_000_000
    assert package["total_cents"] == expected_100["total_cents"] == 5_000_000

    # Crossing to 101 re-bands the PROVISIONAL package in place; the
    # 6000000 nonpecuniary now fits under the 10000000 cap.
    validate_ok(
        api_client.update_employer(
            employer["id"], update_employer_payload(employee_count_current=101),
            _INTAKE,
        )
    )
    rebanded = remedy_package_for_conciliation(conciliation["id"])
    expected_101 = expected_remedy_valuation(
        0, 0, 6_000_000, 0, "FROM_101_TO_200", interest_days
    )
    assert rebanded["id"] == package["id"]  # recomputed in place
    assert rebanded["valuation_variant"] == "PROVISIONAL"
    assert rebanded["band_used"] == "FROM_101_TO_200"
    assert rebanded["capped_nonpecuniary_cents"] == expected_101["capped_nonpecuniary_cents"] == 6_000_000
    assert rebanded["total_cents"] == expected_101["total_cents"] == 6_000_000


def test_priority_score_ceiling_clamp_at_100(api):
    """PRD section 3.5: "The overdue term adds 15 points per currently-`OVERDUE` evidence request, capped at 45 points no matter how many requests are late."
    PRD section 3.5: "The product is rounded half-up once — a single rounding after the multiplication — and the score is clamped to a ceiling of 100."

    Design: Corner/calculations/priority_score_ceiling_clamp_at_100
    """
    base = setup_gathering(basis_codes=["RETALIATION"],
                           investigator_user_id="inv-030")
    case_id = base["investigation_case_id"]
    issue_evidence_requests(case_id, "inv-030", 2)  # three requests total

    # 365 days elapsed: severity 30 + age 35 + overdue min(15*3, 45)=45 = 110 raw.
    set_clock("2027-09-01T00:00:00Z")
    elapsed = days_between("2026-09-01", "2027-09-01")
    assert elapsed == 365

    requests, _meta = validate_paginated(
        api_client.list_evidence_requests(case_id, _DIRECTOR)
    )
    assert all(row["status"] == "OVERDUE" for row in requests)
    assert len(requests) == 3

    investigation = validate_ok(api_client.get_investigation_case(case_id, _DIRECTOR))
    assert investigation["overdue_request_count"] == 3
    # The ceiling clamp applies after rounding: 100, not 110.
    assert investigation["priority_score"] == expected_priority_score(
        ["RETALIATION"], elapsed, 3, False
    ) == 100


def test_priority_score_drops_after_late_response(api):
    """PRD section 3.5: "The request then becomes `RESPONDED`, and a response that arrives while the request is `OVERDUE` is still accepted, flagged `responded_late` true; an on-time response carries `responded_late` false."
    PRD section 3.5: "Each case tracks `open_request_count` — its requests in `PENDING` or `OVERDUE`, excluding `RESPONDED` and `WAIVED` — and `overdue_request_count`, counting `OVERDUE` only; both are recomputed whenever a request transitions."

    Design: Corner/calculations/priority_score_drops_after_late_response
    """
    base = setup_gathering(basis_codes=["RETALIATION"],
                           investigator_user_id="inv-031")
    case_id = base["investigation_case_id"]
    request = base["evidence_request"]

    # 2026-10-05 is 34 days after receipt (age tier 0); the request due
    # 2026-10-01 has flipped OVERDUE: score = 30 + 0 + 15 = 45.
    set_clock("2026-10-05T00:00:00Z")
    elapsed = days_between("2026-09-01", "2026-10-05")
    assert elapsed == 34
    requests, _meta = validate_paginated(
        api_client.list_evidence_requests(case_id, _DIRECTOR)
    )
    assert requests[0]["status"] == "OVERDUE"
    before = validate_ok(api_client.get_investigation_case(case_id, _DIRECTOR))
    assert before["priority_score"] == expected_priority_score(
        ["RETALIATION"], elapsed, 1, False
    ) == 45

    # A late response is still accepted and flagged; the overdue term leaves
    # the input set and the score drops to 30.
    answered = validate_ok(
        api_client.respond_evidence_request(
            request["id"],
            respond_evidence_payload(response_text="our position statement, late"),
            make_respondent_rep_headers(base["employer"]["id"]),
        )
    )
    assert answered["status"] == "RESPONDED"
    assert answered["responded_late"] is True

    after = validate_ok(api_client.get_investigation_case(case_id, _DIRECTOR))
    assert after["overdue_request_count"] == 0
    assert after["priority_score"] == expected_priority_score(
        ["RETALIATION"], elapsed, 0, False
    ) == 30


def test_consolidation_requires_shared_basis_minimum(api):
    """PRD section 3.9: "The case becomes `CONSOLIDATED` once at least 3 linked charges are non-terminal and at least 2 of those non-terminal charges share a basis with `basis_focus` — that is, the intersection of the charge's `basis_codes` with the case's `basis_focus` is non-empty."
    PRD section 3.9: "Consolidation and resolution are threshold rules re-evaluated on every link and on every transition of a linked charge into a terminal state."

    Design: Corner/calculations/consolidation_requires_shared_basis_minimum
    """
    employer = create_employer(state_code="FL", employee_count_current=40,
                               legal_name="Share Co")
    complainant = create_complainant(full_name="Drew Eight", email="d8@x.com")
    bases = ["AGE", "SEX", "DISABILITY", "RACE", "RACE"]
    charges = [
        file_charge(employer, complainant, basis_codes=[basis],
                    incident_date=f"2026-06-0{index + 1}",
                    harm_description=f"h{index + 1}", employee_count_at_incident=40)
        for index, basis in enumerate(bases)
    ]
    systemic = create_systemic_case(title="Shared-basis probe",
                                    basis_focus=["RACE"],
                                    commissioner_user_id="com-004")

    # Three links with zero RACE overlap: the count arm alone is not enough.
    link_charge(systemic, charges[0], commissioner_user_id="com-004")
    link_charge(systemic, charges[1], commissioner_user_id="com-004")
    third = link_charge(systemic, charges[2], commissioner_user_id="com-004")
    assert third["status"] == "EXPANDING"
    assert third["linked_charge_count"] == 3

    # One shared basis is still below the minimum of 2.
    fourth = link_charge(systemic, charges[3], commissioner_user_id="com-004")
    assert fourth["status"] == "EXPANDING"

    # The second sharing charge completes both arms.
    fifth = link_charge(systemic, charges[4], commissioner_user_id="com-004")
    assert fifth["status"] == "CONSOLIDATED"
    assert fifth["linked_charge_count"] == 5
