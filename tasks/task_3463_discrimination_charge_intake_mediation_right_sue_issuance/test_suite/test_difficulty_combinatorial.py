"""Difficulty queue: combinatorial formulas — multi-input computations whose
pinned evaluation order and rounding are observable to the cent."""
from test_helpers import (
    TEST_USERS,
    assign_investigator,
    charge_investigation_case_id,
    conciliation_for_charge,
    create_employer,
    create_complainant,
    create_systemic_case,
    days_between,
    decline_mediation,
    draft_cause_determination,
    expected_interest_cents,
    expected_priority_score,
    expected_remedy_valuation,
    file_charge,
    issue_evidence_request,
    link_charge,
    offer_mediation,
    read_charge,
    remedy_package_for_conciliation,
    review_determination,
    set_clock,
    submit_determination,
    validate_ok,
    validate_paginated,
)
from test_helpers import api_client

_DIRECTOR = TEST_USERS["director_headers"]


def test_remedy_interest_per_component_rounding(api):
    """PRD section 3.7: "Interest accrues at an annual rate of 0.05 (five percent) on each wage component independently: `back_pay_interest_cents` is `back_pay_cents` multiplied by 0.05, multiplied by `interest_days`, divided by 365, then rounded half-up to whole cents — and `front_pay_interest_cents` is computed identically from `front_pay_cents`."
    PRD section 3.7: "Each component is rounded before any summation; per §2.10 this round-then-sum order is load-bearing (with both wage components at 3650 cents and a single interest day, the pinned order yields 1 cent of interest on each — 2 cents total — where summing first would yield only 1)."

    Design: Difficulty/combinatorial_formula/remedy_interest_per_component_rounding
    """
    # Park the clock at 2026-08-02 before intake so the whole flow (and the
    # conciliation initiation) happens one day after the 2026-08-01 harm start.
    set_clock("2026-08-02T00:00:00Z")
    employer = create_employer(state_code="FL", employee_count_current=40,
                               legal_name="Tiny Co")
    complainant = create_complainant(full_name="Pat Four", email="p4@x.com")
    charge = file_charge(employer, complainant, basis_codes=["DISABILITY"],
                         incident_date="2026-08-01",
                         harm_description="no accommodation",
                         employee_count_at_incident=40)

    mediation = offer_mediation(charge)
    decline_mediation(charge, mediation, party="complainant")
    case_id = charge_investigation_case_id(charge["id"])
    assign_investigator(case_id, "inv-002")
    issue_evidence_request(case_id, "inv-002", request_type="RFI")
    determination = draft_cause_determination(
        case_id, "inv-002",
        rationale="rounding probe",
        back_pay_cents=3650, front_pay_cents=3650,
        compensatory_damages_cents=0, punitive_damages_cents=0,
        harm_start_date="2026-08-01",
    )
    submit_determination(determination["id"], "inv-002")
    review_determination(determination["id"], "APPROVE", director_user_id="dir-002")

    conciliation = conciliation_for_charge(charge["id"])
    package = remedy_package_for_conciliation(conciliation["id"])

    # interest_days == 1 (initiation 2026-08-02 minus harm start 2026-08-01):
    # each raw component is exactly 0.5 cents and rounds half-up to 1 BEFORE
    # the sum, so the pinned order yields 7302 (sum-then-round would give 7301).
    expected = expected_remedy_valuation(3650, 3650, 0, 0, "FROM_20_TO_100", 1)
    assert package["interest_days"] == expected["interest_days"] == 1
    assert package["back_pay_interest_cents"] == expected_interest_cents(3650, 1) == 1
    assert package["front_pay_interest_cents"] == expected_interest_cents(3650, 1) == 1
    assert package["back_pay_interest_cents"] == expected["back_pay_interest_cents"]
    assert package["front_pay_interest_cents"] == expected["front_pay_interest_cents"]
    assert package["total_cents"] == expected["total_cents"] == 7302


def test_priority_score_weighted_tiered_nonlinear(api):
    """PRD section 3.5: "The severity term is the maximum basis weight among the charge's `basis_codes` — not a sum — using 30 for `RETALIATION`, 25 for `DISABILITY`, 20 for `AGE`, and 15 for each of `SEX`, `RACE`, `COLOR`, `RELIGION`, `NATIONAL_ORIGIN`, and `GENETIC_INFO`."
    PRD section 3.5: "The age term comes from the charge's `days_elapsed_since_filing`: 0 points under 90 days, 10 points from 90 through 179 days, 20 points from 180 through 364 days, and 35 points at 365 days or more."
    PRD section 3.5: "If the charge's `systemic_case_id` is set, the sum of those three terms is multiplied by 1.5; otherwise the multiplier is 1.0."
    PRD section 3.5: "The product is rounded half-up once — a single rounding after the multiplication — and the score is clamped to a ceiling of 100."
    PRD section 3.5: "The first time a recomputed score reaches 80 or more, the charge's `priority_escalated` flag flips to true; it is sticky and never auto-clears, even if the score later subsides."

    Design: Difficulty/combinatorial_formula/priority_score_weighted_tiered_nonlinear
    """
    employer = create_employer(state_code="FL", employee_count_current=100,
                               legal_name="Score Co")
    complainant = create_complainant(full_name="Pat Five", email="p5@x.com")
    charge = file_charge(employer, complainant, basis_codes=["RETALIATION"],
                         incident_date="2026-06-01",
                         harm_description="fired after complaint",
                         employee_count_at_incident=100)

    mediation = offer_mediation(charge)
    decline_mediation(charge, mediation, party="complainant")
    case_id = charge_investigation_case_id(charge["id"])
    assign_investigator(case_id, "inv-003")
    issue_evidence_request(case_id, "inv-003", request_type="POSITION_STATEMENT")

    # 2027-02-28 is exactly 180 days after the 2026-09-01 receipt (age tier 20);
    # the request (due 2026-10-01) is long overdue (15 points).
    set_clock("2027-02-28T00:00:00Z")
    elapsed = days_between("2026-09-01", "2027-02-28")
    assert elapsed == 180

    requests, _meta = validate_paginated(
        api_client.list_evidence_requests(case_id, _DIRECTOR)
    )
    assert requests[0]["status"] == "OVERDUE"

    pre_link = validate_ok(api_client.get_investigation_case(case_id, _DIRECTOR))
    assert pre_link["overdue_request_count"] == 1
    assert pre_link["priority_score"] == expected_priority_score(
        ["RETALIATION"], elapsed, 1, False
    ) == 65

    systemic = create_systemic_case(title="Retaliation probe",
                                    basis_focus=["RETALIATION"],
                                    commissioner_user_id="com-001")
    link_charge(systemic, charge, commissioner_user_id="com-001")

    post_link = validate_ok(api_client.get_investigation_case(case_id, _DIRECTOR))
    # 65 x 1.5 = 97.5, rounded half-up once after the multiplication: 98.
    assert post_link["priority_score"] == expected_priority_score(
        ["RETALIATION"], elapsed, 1, True
    ) == 98

    sealed = read_charge(charge["id"])
    assert sealed["priority_escalated"] is True  # 98 >= 80 latches the flag
    assert sealed["disclosure_hold"] == "SEALED"
