"""Difficulty queue: transitive cascades — a single trigger whose effects
propagate link by link across entities."""
from test_helpers import (
    TEST_USERS,
    assert_remedy_package,
    conciliation_for_charge,
    create_deferral_agency,
    days_between,
    expected_priority_score,
    expected_remedy_valuation,
    read_charge,
    remedy_package_for_conciliation,
    review_determination,
    set_clock,
    setup_gathering,
    setup_pending_review,
    validate_ok,
    validate_paginated,
)
from test_helpers import api_client

_DIRECTOR = TEST_USERS["director_headers"]


def test_cause_approval_cascade_depth3(api):
    """PRD section 3.6: "Approving a `CAUSE` determination drives a three-link cascade: the charge moves to `CONCILIATION`; that entry auto-creates a `ConciliationProcess` in `INITIATED` with its `origin_determination_id` set to the approved determination, `rounds_count` at 0, and both `current_offer_cents` and `last_offer_by` null; and the new conciliation's creation in turn auto-creates exactly one `RemedyPackage` with `valuation_variant` `PROVISIONAL`, valued per §3.7."
    PRD section 3.6: "Either approval cascade also closes the investigation case and moves its `PENDING`/`OVERDUE` evidence requests to `WAIVED`."

    Design: Difficulty/transitive_cascade/cause_approval_cascade_depth3
    """
    agency = create_deferral_agency(
        state_code="CA", filing_deadline_days=300,
        work_sharing_policy="DUAL_FILE_DEFAULT", covers_age=True,
        agency_name="CA FEPA",
    )
    base = setup_pending_review(
        outcome="CAUSE",
        cause_components={
            "rationale": "comparator evidence",
            "back_pay_cents": 200_000, "front_pay_cents": 100_000,
            "compensatory_damages_cents": 400_000,
            "punitive_damages_cents": 100_000,
            "harm_start_date": "2026-03-05",
        },
        basis_codes=["RACE"], incident_date="2026-03-05",
        employee_count=60, state_code="CA", investigator_user_id="inv-005",
        agency=agency,
    )
    charge = base["charge"]
    determination = base["determination"]
    case_id = base["investigation_case_id"]

    # Approve at 2026-11-01; the PROVISIONAL projection date pins there.
    set_clock("2026-11-01T00:00:00Z")
    approved = review_determination(determination["id"], "APPROVE",
                                    director_user_id="dir-004")

    # Link A: the determination itself.
    assert approved["status"] == "APPROVED"
    assert approved["reviewed_by_user_id"] == "dir-004"

    # Link B (caused by A): the charge moves to CONCILIATION.
    assert read_charge(charge["id"])["case_status"] == "CONCILIATION"

    # Link C (caused by B): exactly one ConciliationProcess, INITIATED, traced
    # to the approved determination.
    conciliation = conciliation_for_charge(charge["id"])
    assert conciliation["status"] == "INITIATED"
    assert conciliation["origin_determination_id"] == determination["id"]
    assert conciliation["rounds_count"] == 0

    # Link D (caused by C): the PROVISIONAL RemedyPackage, verifiable to the
    # cent. Employer is steady at 60 staff -> FROM_20_TO_100 (cap 5000000);
    # interest runs 2026-03-05 -> 2026-11-01 (241 days).
    package = remedy_package_for_conciliation(conciliation["id"])
    assert_remedy_package(package)
    interest_days = days_between("2026-03-05", "2026-11-01")
    expected = expected_remedy_valuation(
        200_000, 100_000, 400_000, 100_000, "FROM_20_TO_100", interest_days,
    )
    assert package["valuation_variant"] == "PROVISIONAL"
    assert package["interest_days"] == expected["interest_days"] == 241
    assert package["back_pay_interest_cents"] == expected["back_pay_interest_cents"] == 6_603
    assert package["front_pay_interest_cents"] == expected["front_pay_interest_cents"] == 3_301
    assert package["capped_nonpecuniary_cents"] == expected["capped_nonpecuniary_cents"] == 500_000
    assert package["total_cents"] == expected["total_cents"] == 809_904

    # Side fan-out: investigation CLOSED, its open evidence request WAIVED.
    investigation = validate_ok(api_client.get_investigation_case(case_id, _DIRECTOR))
    assert investigation["status"] == "CLOSED"
    requests, _meta = validate_paginated(
        api_client.list_evidence_requests(case_id, _DIRECTOR)
    )
    assert requests[0]["status"] == "WAIVED"


def test_evidence_overdue_escalation_cascade(api):
    """PRD section 2.4: "An `EvidenceRequest` flips from `PENDING` to `OVERDUE` on read once the logical clock passes its `due_date`."
    PRD section 3.5: "The overdue term adds 15 points per currently-`OVERDUE` evidence request, capped at 45 points no matter how many requests are late."
    PRD section 3.5: "The first time a recomputed score reaches 80 or more, the charge's `priority_escalated` flag flips to true; it is sticky and never auto-clears, even if the score later subsides."

    Design: Difficulty/transitive_cascade/evidence_overdue_escalation_cascade
    """
    base = setup_gathering(
        basis_codes=["RETALIATION", "AGE"], employee_count=25,
        investigator_user_id="inv-006",
    )
    charge = base["charge"]
    case_id = base["investigation_case_id"]

    # 2027-09-01 is exactly 365 days after the 2026-09-01 receipt: age tier 35,
    # and the 2026-10-01-due request flipped OVERDUE (15 points).
    set_clock("2027-09-01T00:00:00Z")
    elapsed = days_between("2026-09-01", "2027-09-01")
    assert elapsed == 365

    # Link A: the lazy overdue flip is visible on read.
    requests, _meta = validate_paginated(
        api_client.list_evidence_requests(case_id, _DIRECTOR)
    )
    assert requests[0]["status"] == "OVERDUE"
    assert requests[0]["due_date"][:10] == "2026-10-01"

    # Link B (caused by A): counts and score recomputed —
    # max severity 30 (RETALIATION) + 35 + 15 = 80.
    investigation = validate_ok(api_client.get_investigation_case(case_id, _DIRECTOR))
    assert investigation["overdue_request_count"] == 1
    assert investigation["priority_score"] == expected_priority_score(
        ["RETALIATION", "AGE"], elapsed, 1, False
    ) == 80

    # Link C (caused by B crossing the threshold): exactly 80 escalates —
    # the boundary is inclusive ("reaches 80 or more").
    escalated = read_charge(charge["id"])
    assert escalated["priority_escalated"] is True
