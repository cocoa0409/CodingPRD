"""
Who may call what: role exclusivity, ownership scoping and duty segregation.

The first scenario refuses each staff role on another role's exclusive write and
then replays two of those writes under their owning roles to show the refusal was
about the caller. The second scopes the two party-facing reads and the employer
read to the caller's own row. The third proves the segregation rule compares user
identifiers rather than role names.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    CASE_WORKER_HEADERS,
    FINANCE_OFFICER_HEADERS,
    INTERSTATE_LIAISON_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    SUPERVISING_ATTORNEY_HEADERS,
    make_custodial_party_headers,
    make_employer_agent_headers,
    make_noncustodial_party_headers,
    make_supervising_attorney_headers,
)


# ---------------------------------------------------------------------------
# Role-exclusive writes
# ---------------------------------------------------------------------------


def _calculated_order_awaiting_entry() -> fx.Scenario:
    """
    A case whose order is calculated at 75,000 cents and still awaiting entry, so
    both the entry and the charge posting under test are genuinely available.
    """
    scenario = fx.open_case_with_parties(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Bettina Krause",
            "ssn_last4": "6261",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Lorenz Krause",
            "ssn_last4": "6262",
            "monthly_gross_income_cents": 300000,
        },
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=False,
    )
    scenario.paternity_action = fx.open_paternity_action(scenario.case_id, "PRESUMED_MARITAL")
    order = fx.draft_order(
        scenario.case_id,
        order_type="CURRENT_SUPPORT",
        origin_state_code="MN",
        effective_date="2026-08-01",
    )
    scenario.order = fx.calculate_order(order["id"])
    return scenario


def test_01_every_staff_role_is_refused_on_another_role_s_exclusive_write():
    """
    Seven callers, seven identical 403s, including the administrator's.

    If the role is well formed but that role is not among the roles authorised for the endpoint being called, the rejection is `ERR_UNAUTHORIZED` (HTTP 403).

    There is no hierarchical override anywhere in this model: a `ProgramAdmin` cannot draft an order, post a payment or decide findings, and a `SupervisingAttorney` cannot post a charge.

    The table below enumerates every endpoint in the service, together with the roles authorised to call it.

    Design: Corner/rbac/role_exclusive_writes_reject_every_other_role_including_program_admin
    """
    scenario = _calculated_order_awaiting_entry()
    assert scenario.order["guideline_monthly_cents"] == 75000

    # The administrator owns the registry and the clock, and nothing else.
    validate_error(
        api_client.create_case(
            f.case_payload(scenario.cp_id, scenario.ncp_id), PROGRAM_ADMIN_HEADERS
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.create_employer(
            f.employer_payload("MN", legal_name="Krause Werke", fein="41-0000115"),
            CASE_WORKER_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    # The role that drafted the order may not be the role that enters it.
    validate_error(
        api_client.enter_order(scenario.order_id, f.entry_payload(), CASE_WORKER_HEADERS),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.close_case(
            scenario.case_id, f.closure_payload("CP_REQUEST"), FINANCE_OFFICER_HEADERS
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.post_charge(
            scenario.order_id,
            f.charge_payload(
                charge_type="CURRENT_SUPPORT",
                period_start_date="2026-08-01",
                period_end_date="2026-09-01",
                due_date="2026-08-15",
                amount_cents=75000,
            ),
            SUPERVISING_ATTORNEY_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.post_payment(
            scenario.case_id,
            f.payment_payload(source="DIRECT_PAY", amount_cents=10000),
            INTERSTATE_LIAISON_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    # An EmployerAgent is absent from this read's role list, so the ownership
    # scoping rule below it is never consulted.
    validate_error(
        api_client.get_case(scenario.case_id, make_employer_agent_headers("emp_not_registered")),
        ApiErrorId.UNAUTHORIZED,
        403,
    )


def test_02_the_same_two_writes_succeed_for_the_roles_that_own_them():
    """
    Nothing about the rows changed: only the caller did.

    A `SupervisingAttorney` holds the legal authority: genetic test orders and results, deviation findings, order entry and vacatur, contest review, modification proposals and case closure.

    A `FinanceOfficer` owns the ledger: charge posting and voidance, non-withholding collections, accrual runs, remittance lapse declarations, compromise offers and compromise defaults.

    Design: Corner/rbac/role_exclusive_writes_reject_every_other_role_including_program_admin
    """
    scenario = _calculated_order_awaiting_entry()
    validate_error(
        api_client.enter_order(scenario.order_id, f.entry_payload(), CASE_WORKER_HEADERS),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.create_employer(
            f.employer_payload("MN", legal_name="Krause Werke", fein="41-0000115"),
            CASE_WORKER_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    entered = validate_success(
        api_client.enter_order(scenario.order_id, f.entry_payload(), SUPERVISING_ATTORNEY_HEADERS)
    )
    assert entered["status"] == "ENTERED"
    assert entered["monthly_obligation_cents"] == 75000

    charge = validate_success(
        api_client.post_charge(
            scenario.order_id,
            f.charge_payload(
                charge_type="CURRENT_SUPPORT",
                period_start_date="2026-08-01",
                period_end_date="2026-09-01",
                due_date="2026-08-15",
                amount_cents=75000,
            ),
            FINANCE_OFFICER_HEADERS,
        ),
        201,
    )
    assert charge["status"] == "OPEN"

    _employers, employer_meta = validate_paginated(
        api_client.list_employers(PROGRAM_ADMIN_HEADERS)
    )
    assert employer_meta["total_count"] == 0
    _cases, case_meta = validate_paginated(api_client.list_cases(CASE_WORKER_HEADERS))
    assert case_meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Identity-scoped reads and writes for the three entity-backed roles
# ---------------------------------------------------------------------------


def _two_cases_and_a_served_order_at_one_of_two_employers() -> Tuple[
    fx.Scenario, fx.Scenario, Dict[str, Any], Dict[str, Any]
]:
    """
    Case A carries a served withholding order at the Minnesota employer; case B
    exists only to supply a real participant identifier that belongs elsewhere,
    and the Texas employer holds nothing at all.
    """
    case_a = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Yaa Boateng",
            "ssn_last4": "6263",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Kofi Boateng",
            "ssn_last4": "6264",
            "monthly_gross_income_cents": 300000,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )
    case_b = fx.case_with_entered_order(
        clock=None,
        cp_overrides={
            "full_name": "Nadia Farouk",
            "ssn_last4": "6265",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Sami Farouk",
            "ssn_last4": "6266",
            "monthly_gross_income_cents": 300000,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )
    employer_m = fx.create_employer(
        legal_name="Boateng Millwork", fein="41-0000116", state_code="MN", remittance_fee_cents=0
    )
    employer_t = fx.create_employer(
        legal_name="Farouk Drilling", fein="74-0000117", state_code="TX", remittance_fee_cents=0
    )
    case_a.employer = employer_m
    case_a.withholding_order = fx.issue_withholding_order(
        case_a.order_id, employer_m["id"], reported_disposable_income_cents=150000
    )
    case_a.withholding_order = fx.serve_withholding_order(case_a.iwo_id)
    return case_a, case_b, employer_m, employer_t


def test_03_a_party_caller_is_matched_against_the_corresponding_party_field():
    """
    The obligor's own identifier under the custodial role is refused on his own case.

    When `X-User-Role` is `CustodialParty`, `X-User-ID` is the `id` of the acting `Participant`; ownership checks on any resource that references a `Participant` compare the resource's case's `custodial_party_id` to `X-User-ID`.

    A mismatch in either direction — a custodial caller reaching for a case it is not the custodial party of, or a noncustodial caller reaching for a case it is not the obligor on — is rejected with `ERR_NOT_CASE_PARTY` (HTTP 403).

    Design: Corner/rbac/party_and_employer_reads_are_scoped_to_the_caller_s_own_row
    """
    case_a, case_b, _employer_m, _employer_t = _two_cases_and_a_served_order_at_one_of_two_employers()
    assert case_a.order["monthly_obligation_cents"] == 75000
    assert case_a.withholding_order["withholding_amount_cents"] == 75000

    # A real obligor identifier, but of the wrong case.
    validate_error(
        api_client.get_case(case_a.case_id, make_noncustodial_party_headers(case_b.ncp_id)),
        ApiErrorId.NOT_CASE_PARTY,
        403,
    )

    # Both parties of case A share the very same read.
    obligor_view = validate_success(
        api_client.get_case(case_a.case_id, make_noncustodial_party_headers(case_a.ncp_id))
    )
    custodial_view = validate_success(
        api_client.get_case(case_a.case_id, make_custodial_party_headers(case_a.cp_id))
    )
    assert obligor_view["case_status"] == "ENFORCEMENT"
    assert custodial_view["case_status"] == "ENFORCEMENT"

    # The identifier is on this very case, but the custodial check compares it
    # against custodial_party_id alone.
    validate_error(
        api_client.get_case(case_a.case_id, make_custodial_party_headers(case_a.ncp_id)),
        ApiErrorId.NOT_CASE_PARTY,
        403,
    )


def test_04_an_employer_agent_is_refused_a_write_but_merely_scoped_on_a_list():
    """
    The wrong employer gets a 403 on the remittance and an empty page on the list.

    When `X-User-Role` is `EmployerAgent`, `X-User-ID` is the `id` of the acting `Employer`; posting a remittance against a withholding order whose `employer_id` differs from `X-User-ID` is rejected with `ERR_NOT_IWO_EMPLOYER` (HTTP 403), and the same check scopes the withholding-order list so that an `EmployerAgent` caller sees only rows whose `employer_id` equals `X-User-ID`.

    The remittance creates a payment on the case with `source` `INCOME_WITHHOLDING` and its `iwo_id` set to this order, which is then allocated and split exactly as described in the ledger section below; both the withholding order's `version` and the case's `version` increase by 1.

    Design: Corner/rbac/party_and_employer_reads_are_scoped_to_the_caller_s_own_row
    """
    case_a, _case_b, employer_m, employer_t = _two_cases_and_a_served_order_at_one_of_two_employers()

    # A registered employer that is simply not this order's employer.
    validate_error(
        api_client.post_remittance(
            case_a.iwo_id,
            f.remittance_payload(75000),
            make_employer_agent_headers(employer_t["id"]),
        ),
        ApiErrorId.NOT_IWO_EMPLOYER,
        403,
    )

    # The identical call from the right employer posts the remittance.
    remitted = validate_success(
        api_client.post_remittance(
            case_a.iwo_id,
            f.remittance_payload(75000),
            make_employer_agent_headers(employer_m["id"]),
        ),
        201,
    )
    assert remitted["source"] == "INCOME_WITHHOLDING"
    assert remitted["amount_cents"] == 75000
    assert remitted["iwo_id"] == case_a.iwo_id

    _payments, payment_meta = validate_paginated(
        api_client.list_payments(FINANCE_OFFICER_HEADERS, params={"case_id": case_a.case_id})
    )
    assert payment_meta["total_count"] == 1

    # The collection form scopes silently rather than refusing.
    _theirs, their_meta = validate_paginated(
        api_client.list_withholding_orders(make_employer_agent_headers(employer_t["id"]))
    )
    assert their_meta["total_count"] == 0
    ours, our_meta = validate_paginated(
        api_client.list_withholding_orders(make_employer_agent_headers(employer_m["id"]))
    )
    assert our_meta["total_count"] == 1
    assert [row["id"] for row in ours] == [case_a.iwo_id]


# ---------------------------------------------------------------------------
# Segregation of duties: an identifier comparison, not a role comparison
# ---------------------------------------------------------------------------


def _order_awaiting_findings_from_a_second_operator() -> fx.Scenario:
    """
    An order whose worksheet was run by `user-sod-1` and which now sits in
    `PENDING_DEVIATION_FINDINGS` on a request of 67,500 — exactly ten percent
    below the 75,000 guideline, the smallest deviation the rule admits.
    """
    scenario = fx.open_case_with_parties(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Rivka Salzman",
            "ssn_last4": "6267",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Ezra Salzman",
            "ssn_last4": "6268",
            "monthly_gross_income_cents": 300000,
        },
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=False,
    )
    scenario.paternity_action = fx.open_paternity_action(scenario.case_id, "PRESUMED_MARITAL")
    order = fx.draft_order(
        scenario.case_id,
        order_type="CURRENT_SUPPORT",
        origin_state_code="MN",
        effective_date="2026-08-01",
    )
    scenario.order = fx.calculate_order(order["id"], drafted_by_user_id="user-sod-1")
    scenario.order = fx.request_deviation(order["id"], 67500, "HARDSHIP")
    return scenario


def test_05_the_drafter_is_refused_the_findings_even_wearing_the_attorney_s_role():
    """
    `user-sod-1` is the drafter, so `user-sod-1` may not decide, whatever the role says.

    Two operations in this system are deliberately impossible for a single operator to complete alone.

    Deviation findings may not be decided by the same `X-User-ID` recorded in the order's `drafted_by_user_id`, and the administrative review of a contested enforcement action may not be decided by the same `X-User-ID` recorded in the action's `proposed_by_user_id`.

    Note that the role is not what enforces this — both the drafter and the decider may be `SupervisingAttorney` users; it is the identifier comparison that enforces it, so a second distinct operator is always required.

    Design: Corner/rbac/segregation_of_duties_compares_user_ids_not_roles
    """
    scenario = _order_awaiting_findings_from_a_second_operator()
    assert scenario.order["guideline_monthly_cents"] == 75000
    assert scenario.order["status"] == "PENDING_DEVIATION_FINDINGS"
    assert scenario.order["drafted_by_user_id"] == "user-sod-1"

    validate_error(
        api_client.decide_deviation_findings(
            scenario.order_id,
            f.deviation_findings_payload("APPROVE"),
            make_supervising_attorney_headers("user-sod-1"),
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        403,
    )

    # A different identifier under the very same role is accepted untouched.
    entered = fx.decide_deviation(scenario.order_id, "APPROVE", decided_by_user_id="user-sod-2")
    assert entered["status"] == "ENTERED"
    assert entered["monthly_obligation_cents"] == 67500
    assert entered["drafted_by_user_id"] == "user-sod-1"
    assert entered["findings_approved_by_user_id"] == "user-sod-2"


def test_06_the_proposer_is_refused_the_contest_review_on_the_other_anchor():
    """
    The second segregation point compares the same header against a different field.

    An action sitting in `CONTESTED` is decided by a `SupervisingAttorney` supplying a `review_decision` of `UPHOLD` or `VACATE`, and the deciding user's identifier must differ from `proposed_by_user_id`; the caseworker who proposed a remedy may never be the one who validates it, and an attempt answers with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

    `activated_at` is stamped from the logical clock, `remedy_applied` becomes true, the case's `enforcement_posture` becomes `ESCALATED`, and the participant-level flag matching the remedy is set — `LICENSE_SUSPENSION` sets `license_suspension_active` and simultaneously clears `has_valid_drivers_license`, `PROPERTY_LIEN` sets `lien_recorded`, and `CREDIT_BUREAU_REPORT` sets `credit_bureau_reported`.

    Design: Corner/rbac/segregation_of_duties_compares_user_ids_not_roles
    """
    scenario = _order_awaiting_findings_from_a_second_operator()
    fx.decide_deviation(scenario.order_id, "APPROVE", decided_by_user_id="user-sod-2")
    fx.post_charge(
        scenario.order_id,
        charge_type="ARREARS_JUDGMENT",
        period_start_date="2026-08-01",
        period_end_date="2026-09-01",
        due_date="2026-08-01",
        amount_cents=150000,
    )

    action = fx.propose_enforcement_action(
        scenario.case_id, "CREDIT_BUREAU_REPORT", proposed_by_user_id="user-sod-3"
    )
    assert action["proposed_by_user_id"] == "user-sod-3"
    # Nothing has been outstanding a whole month, so the snapshot is bare principal.
    assert action["arrears_certified_snapshot_cents"] == 150000
    assert action["eligibility_threshold_cents"] == 100000

    noticed = fx.send_enforcement_notice(action["id"])
    assert noticed["status"] == "NOTICE_SENT"
    contested = fx.contest_enforcement_action(action["id"], scenario.ncp_id, "MISTAKE_OF_FACT")
    assert contested["status"] == "CONTESTED"

    validate_error(
        api_client.decide_enforcement_review(
            action["id"],
            f.review_decision_payload("UPHOLD"),
            make_supervising_attorney_headers("user-sod-3"),
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        403,
    )

    upheld = fx.decide_enforcement_review(action["id"], "UPHOLD", decided_by_user_id="user-sod-4")
    assert upheld["status"] == "ACTIVE"
    assert upheld["review_decision"] == "UPHOLD"
    assert upheld["review_decided_by_user_id"] == "user-sod-4"
    assert upheld["remedy_applied"] is True
    assert fx.read_participant(scenario.ncp_id)["credit_bureau_reported"] is True
