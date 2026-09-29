"""Declared transitions, refused transitions, seeded initial states and cascades.

Each entity's lifecycle is walked one legal hop at a time and then pushed at the
hops it does not declare, so that a legal move and its illegal neighbours are
distinguished on the same row rather than assumed.
"""
from test_helpers import (
    ApiErrorId,
    assert_hra_ledger_conservation,
    assert_instant_equals,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ADMIN_1,
    ANALYST_1,
    ANALYST_2,
    BILLING_1,
    COMPLIANCE_1,
    COUNSELOR_1,
    COUNSELOR_2,
    HRA_ADMIN_1,
    make_benefits_admin_headers,
    make_billing_clerk_headers,
    make_compliance_officer_headers,
    make_eligibility_analyst_headers,
    make_enrollment_counselor_headers,
    make_hra_administrator_headers,
    make_retiree_headers,
)


def test_draft_plan_year_takes_its_single_declared_hop_to_open(api):
    """DRAFT to OPEN succeeds, bumps the version and touches nothing else.

    PRD 3.1: "Its lifecycle is a strict single-successor chain, driven by a
    `BenefitsAdmin` supplying a `to_status`: `DRAFT → OPEN`, then `OPEN →
    CLOSED`, then `CLOSED → ARCHIVED`." A lifecycle hop is a mutation like any
    other, so PRD 2.11 requires that "each row a cascade rewrites has its own
    `version` incremented by exactly 1". The valuation aggregates are the
    actuary's business, not the lifecycle's, and PRD 3.1 leaves them where
    registration put them: "`measured_retiree_count`, `epbo_total_cents`,
    `apbo_total_cents` and `service_cost_total_cents` all start at 0."

    Design: Corner/state_machines/plan_year_draft_to_open_valid_transition
    """
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_plan_year(api)
    assert plan_year["status"] == "DRAFT"
    assert plan_year["version"] == 1

    opened = validate_success(
        api.set_plan_year_status(
            plan_year["id"],
            f.plan_year_status_payload("OPEN"),
            make_benefits_admin_headers(ADMIN_1),
        ),
        expected_status=200,
    )

    assert opened["id"] == plan_year["id"]
    assert opened["status"] == "OPEN"
    assert opened["version"] == 2
    assert opened["year"] == 2027
    assert opened["measured_retiree_count"] == 0
    assert opened["epbo_total_cents"] == 0
    assert opened["apbo_total_cents"] == 0
    assert opened["service_cost_total_cents"] == 0
    assert opened["liability_method"] is None
    assert opened["liability_valued_at"] is None


def test_draft_plan_year_refuses_every_status_but_its_one_successor(api):
    """A skip, a move backwards and a repeat are all the same refusal.

    PRD 3.1: "Any requested `to_status` that is not the one legal successor of
    the current `status` — including a repeat of the current status, a skip, or a
    move backwards — is refused with `ERR_INVALID_PLAN_YEAR_TRANSITION`." PRD 2.8
    rung 16 fixes the code: "The requested plan-year status change is one of the
    three declared successors → `ERR_INVALID_PLAN_YEAR_TRANSITION` (409), on the
    plan-year lifecycle endpoint." A refused request writes nothing, so the row
    is still DRAFT at version 1 after all three attempts.

    Design: Corner/state_machines/plan_year_draft_to_archived_is_an_invalid_transition
    """
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_plan_year(api)
    admin = make_benefits_admin_headers(ADMIN_1)

    for rejected in ("ARCHIVED", "CLOSED", "DRAFT"):
        validate_error(
            api.set_plan_year_status(
                plan_year["id"], f.plan_year_status_payload(rejected), admin
            ),
            ApiErrorId.ERR_INVALID_PLAN_YEAR_TRANSITION.value,
            expected_status=409,
        )
        current = fx.reload_plan_year(api, plan_year["id"])
        assert current["status"] == "DRAFT"
        assert current["version"] == 1


def test_archived_plan_year_is_terminal_for_every_further_trigger(api):
    """The end of the chain answers every to_status with the same 409.

    PRD 3.1: "Reaching `ARCHIVED` additionally requires that no reimbursement
    account of that plan year is still `OPEN`; `ARCHIVED` is terminal and
    cascades nothing further." Terminal means there is no legal successor left
    for rung 16 to admit, so a forward repeat and a move backwards are refused
    alike, and the four versions the walk earned — one at registration and one
    per hop — are the last the row will ever see.

    Design: Corner/state_machines/plan_year_archived_terminal_state_rejects_every_trigger
    """
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_plan_year(api)
    admin = make_benefits_admin_headers(ADMIN_1)

    for to_status in ("OPEN", "CLOSED", "ARCHIVED"):
        walked = fx.advance_plan_year(api, plan_year["id"], to_status)
        assert walked["status"] == to_status
    assert walked["version"] == 4

    for rejected in ("ARCHIVED", "OPEN", "CLOSED", "DRAFT"):
        validate_error(
            api.set_plan_year_status(
                plan_year["id"], f.plan_year_status_payload(rejected), admin
            ),
            ApiErrorId.ERR_INVALID_PLAN_YEAR_TRANSITION.value,
            expected_status=409,
        )

    final = fx.reload_plan_year(api, plan_year["id"])
    assert final["status"] == "ARCHIVED"
    assert final["version"] == 4


def test_a_new_plan_option_opens_draft_with_certification_not_started(api):
    """Both of the option's status dimensions start at their own beginnings.

    PRD 3.1: "A new option starts with `status` `DRAFT`,
    `subsidy_certification_status` `NOT_STARTED` and `enrolled_count` 0." The two
    dimensions are independent, and PRD 2.11 insists on it: "A `PlanOption`
    carries `status` alongside `subsidy_certification_status`". An EGWP option
    shows this most clearly, because its certification dimension has real work
    ahead of it while its availability dimension has only activation ahead of
    it — and PRD 3.1 states the asymmetry: "an option may be `ACTIVE` while its
    `subsidy_certification_status` is still `NOT_STARTED`".

    Design: Corner/state_machines/plan_option_initial_state_is_draft_and_not_started
    """
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_open_plan_year(api)

    option = validate_success(
        api.create_plan_option(
            f.med_wrap_payload(plan_year["id"]), make_benefits_admin_headers(ADMIN_1)
        ),
        expected_status=201,
    )

    assert option["status"] == "DRAFT"
    assert option["subsidy_certification_status"] == "NOT_STARTED"
    assert option["enrolled_count"] == 0
    assert option["plan_code"] == "MED-WRAP"
    assert option["coverage_class"] == "MEDICARE_GROUP_WRAP"
    assert option["subsidy_vehicle"] == "EGWP"
    assert option["monthly_premium_cents"] == 32900
    assert option["requires_medicare_part_b"] is True
    assert option["version"] == 1

    activated = validate_success(
        api.activate_plan_option(option["id"], make_benefits_admin_headers(ADMIN_1))
    )
    assert activated["status"] == "ACTIVE"
    assert activated["subsidy_certification_status"] == "NOT_STARTED"


def test_certifying_an_already_certified_determination_is_refused_by_state(api):
    """The second certify hits the state rung, not the duties rung.

    PRD 2.8 rung 19: "The determination's `status` permits the requested move —
    certification requires `DRAFT`, opening an appeal requires `CERTIFIED`, and
    deciding an appeal requires `UNDER_APPEAL` → `ERR_INVALID_DETERMINATION_STATE`
    (409)." The second caller is a `ComplianceOfficer` who never touched the row,
    so no duties pairing is even in question; and rung 19 sits above rung 25 in a
    ladder PRD 2.8 declares "total", where "no later rule is evaluated or
    reported". Nothing is rewritten, so PRD 3.4's record of the first
    certification stands: "the determination records `certified_by_user_id` as
    the certifying user's `X-User-ID` and `certified_at` at the logical clock" —
    even though the clock has since moved on.

    Design: Corner/state_machines/determination_certify_twice_rejected_on_second_call
    """
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_open_plan_year(api)
    retiree = fx.make_retiree_r1(api)

    determination = fx.make_determination(
        api,
        retiree,
        plan_year["id"],
        certify=False,
        creator_user_id=ANALYST_1,
    )
    assert determination["status"] == "DRAFT"

    certified = validate_success(
        api.certify_determination(
            determination["id"], make_eligibility_analyst_headers(ANALYST_2)
        )
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == ANALYST_2
    assert_instant_equals(
        certified["certified_at"], "2026-10-20T00:00:00.000Z", "certified_at"
    )
    version_after_first = certified["version"]

    fx.set_clock(api, "2026-10-25T00:00:00Z")

    error = validate_error(
        api.certify_determination(
            determination["id"], make_compliance_officer_headers(COMPLIANCE_1)
        ),
        ApiErrorId.ERR_INVALID_DETERMINATION_STATE.value,
        expected_status=409,
    )
    assert error["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value

    unchanged = fx.reload_determination(api, determination["id"])
    assert unchanged["status"] == "CERTIFIED"
    assert unchanged["certified_by_user_id"] == ANALYST_2
    assert_instant_equals(
        unchanged["certified_at"], "2026-10-20T00:00:00.000Z", "certified_at"
    )
    assert unchanged["version"] == version_after_first


def test_reviewing_an_election_that_is_already_under_review_is_refused(api):
    """Review is a one-way door out of SUBMITTED, and it does not re-open.

    PRD 2.8 rung 20: "The election event's `status` permits the requested move —
    taking it into review requires `SUBMITTED` and deciding it requires
    `UNDER_REVIEW` → `ERR_INVALID_ELECTION_STATE` (409)." PRD 3.5 says what the
    first review wrote: it "moves `status` to `UNDER_REVIEW`, and records
    `reviewed_by_user_id` as the acting user's `X-User-ID`". A second, different
    counselor therefore cannot overwrite that attribution by re-reviewing, and
    the refusal leaves the version where the first review left it.

    Design: Corner/state_machines/election_review_from_under_review_rejected_by_precondition
    """
    program = fx.standard_program(api)
    plan_year_id = program["plan_year"]["id"]
    certified = fx.make_certified_retiree(api, plan_year_id, f.retiree_r1_payload())

    election = fx.make_election_event(
        api,
        certified["retiree"]["id"],
        plan_year_id,
        program["pre65_core"]["id"],
        creator_user_id=COUNSELOR_1,
        reviewer_user_id=COUNSELOR_2,
        review=True,
    )
    assert election["status"] == "UNDER_REVIEW"
    assert election["reviewed_by_user_id"] == COUNSELOR_2
    assert election["version"] == 2

    validate_error(
        api.review_election_event(
            election["id"], make_enrollment_counselor_headers(COUNSELOR_1)
        ),
        ApiErrorId.ERR_INVALID_ELECTION_STATE.value,
        expected_status=409,
    )

    unchanged = fx.reload_election_event(api, election["id"])
    assert unchanged["status"] == "UNDER_REVIEW"
    assert unchanged["reviewed_by_user_id"] == COUNSELOR_2
    assert unchanged["version"] == 2
    assert unchanged["resulting_enrollment_id"] is None


def test_a_one_cent_payment_partially_pays_and_the_remainder_settles_it(api):
    """ISSUED to PARTIALLY_PAID to PAID, driven by the paid_cents comparison.

    PRD 3.8: "An accepted payment increases `paid_cents` by `amount_cents`; the
    invoice moves to `PARTIALLY_PAID` while `paid_cents` remains below
    `net_due_cents` and to `PAID` once the two are equal, and its `version`
    increments." The amount owed is the full retiree share because no
    reimbursement account exists: PRD 3.8 step 7 says "The available
    reimbursement balance is the `available_balance_cents` of the `OPEN` account
    belonging to the invoice's retiree and plan year, and it is treated as 0 when
    no such account exists." Settling the invoice leaves the billing dimension
    alone, since PRD 3.8 only unwinds delinquency on "Full payment of an invoice
    that had aged into `PAST_DUE`" and this invoice never aged.

    Design: Corner/state_machines/invoice_exact_full_payment_executes_declared_side_effects
    """
    enrolled = fx.enrolled_retiree(api)
    retiree_id = enrolled["retiree"]["id"]
    invoice = fx.make_invoice(api, enrolled["enrollment"]["id"])

    assert invoice["status"] == "ISSUED"
    assert invoice["net_due_cents"] == 15422
    assert invoice["hra_applied_cents"] == 0
    assert invoice["paid_cents"] == 0
    assert invoice["version"] == 1

    partial = validate_success(
        api.pay_invoice(
            invoice["id"], f.payment_payload(1), make_retiree_headers(retiree_id)
        )
    )
    assert partial["status"] == "PARTIALLY_PAID"
    assert partial["paid_cents"] == 1
    assert partial["net_due_cents"] == 15422
    assert partial["version"] == 2

    settled = validate_success(
        api.pay_invoice(
            invoice["id"], f.payment_payload(15421), make_retiree_headers(retiree_id)
        )
    )
    assert settled["status"] == "PAID"
    assert settled["paid_cents"] == 15422
    assert settled["paid_cents"] == settled["net_due_cents"]
    assert settled["version"] == 3

    enrollment = fx.reload_enrollment(api, enrolled["enrollment"]["id"])
    assert enrollment["billing_status"] == "CURRENT"
    assert enrollment["consecutive_unpaid_periods"] == 0
    assert enrollment["delinquency_first_unpaid_period_start"] is None


def test_a_due_plan_termination_notice_retires_the_option_and_its_pending_book(api):
    """The sweep, not the notice, applies the change — and PENDING coverage falls.

    PRD 3.1: "On admission the option records `change_notice_issued_at` at the
    logical clock, `pending_change_type`, `pending_change_effective_date` and
    `pending_new_monthly_premium_cents`, and nothing else changes yet — the
    announced change is applied later, by the nightly sweep, when the clock
    reaches the effective instant." PRD 3.9 phase 3 then does the work: "A
    `pending_change_type` of `PLAN_TERMINATION` moves the option's `status` to
    `RETIRED` and terminates its book of business: every enrollment on that
    option whose `coverage_status` is `PENDING`, `ACTIVE` or `SUSPENDED` moves to
    `TERMINATED` with `coverage_end_date` at the clock and `termination_reason`
    `PLAN_TERMINATION`, in `created_at` ascending order, and `enrolled_count` is
    set to 0. Either way `pending_change_type`, `pending_change_effective_date`
    and `pending_new_monthly_premium_cents` are all cleared to null". The
    enrollment is still PENDING when the cascade reaches it, because the clock at
    2026-12-19 has not reached the 2027-01-01 coverage start, which is also why
    PRD 3.9 phase 1 activates nothing.

    Design: Corner/state_machines/plan_termination_change_cascades_down_to_enrollments
    """
    program = fx.standard_program(api)
    plan_year_id = program["plan_year"]["id"]
    option_id = program["pre65_core"]["id"]
    certified = fx.make_certified_retiree(api, plan_year_id, f.retiree_r1_payload())
    enrolled = fx.make_enrollment(
        api, certified["retiree"]["id"], plan_year_id, option_id
    )
    enrollment_id = enrolled["enrollment"]["id"]
    assert enrolled["enrollment"]["coverage_status"] == "PENDING"

    staged = validate_success(
        api.issue_change_notice(
            option_id,
            f.change_notice_payload(
                change_type="PLAN_TERMINATION",
                effective_date="2026-12-19T00:00:00Z",
                new_monthly_premium_cents=None,
            ),
            make_benefits_admin_headers(ADMIN_1),
        )
    )
    assert staged["status"] == "ACTIVE"
    assert staged["pending_change_type"] == "PLAN_TERMINATION"
    assert staged["pending_new_monthly_premium_cents"] is None
    assert_instant_equals(
        staged["pending_change_effective_date"],
        "2026-12-19T00:00:00.000Z",
        "pending_change_effective_date",
    )
    assert_instant_equals(
        staged["change_notice_issued_at"],
        "2026-10-20T00:00:00.000Z",
        "change_notice_issued_at",
    )
    assert staged["enrolled_count"] == 1

    fx.set_clock(api, "2026-12-19T00:00:00Z")
    counters = fx.run_daily(api)

    assert counters["applied_plan_change_count"] == 1
    assert counters["activated_enrollment_count"] == 0
    assert counters["processed_invoice_count"] == 0
    assert counters["suspended_enrollment_count"] == 0
    assert counters["lapsed_enrollment_count"] == 0
    assert counters["recomputed_msp_count"] == 0

    retired = fx.reload_plan_option(api, option_id)
    assert retired["status"] == "RETIRED"
    assert retired["pending_change_type"] is None
    assert retired["pending_change_effective_date"] is None
    assert retired["pending_new_monthly_premium_cents"] is None
    assert retired["enrolled_count"] == 0
    assert retired["monthly_premium_cents"] == 74500

    enrollment = fx.reload_enrollment(api, enrollment_id)
    assert enrollment["coverage_status"] == "TERMINATED"
    assert_instant_equals(
        enrollment["coverage_end_date"],
        "2026-12-19T00:00:00.000Z",
        "coverage_end_date",
    )
    assert enrollment["termination_reason"] == "PLAN_TERMINATION"

    assert fx.reload_election_event(api, enrolled["election"]["id"])["status"] == (
        "APPROVED"
    )


def test_closing_the_hra_year_releases_the_hold_before_it_forfeits(api):
    """Order is observable: the cap bites 122206, not the post-hold 82206.

    PRD 3.7: "First the account sheds its unfinished work: every claim on the
    account whose `status` is `SUBMITTED`, `PENDING_SUBSTANTIATION` or `APPROVED`
    moves to `DENIED` with `denial_reason_code` `ACCOUNT_NOT_OPEN`, its held
    `eligible_cents` returning from `pending_hold_cents` to
    `available_balance_cents`, processed in `created_at` ascending order with each
    claim's `version` incrementing. Because that cascade runs first,
    `pending_hold_cents` is 0 by the time forfeiture is computed. Then forfeiture
    runs: the carryover cap is `annual_credit_cents` multiplied by the plan
    year's `carryover_cap_pct`, truncated down to whole cents; `forfeited_cents`
    is the excess of `available_balance_cents` over that cap, or 0 when the
    balance does not exceed the cap; and `available_balance_cents` is reduced by
    exactly `forfeited_cents`." and it ends with "Finally `status` moves from
    `OPEN` to `CLOSED`, `closed_at` is set to the logical clock, and the account's
    `version` increments." Half of 122206 truncates to 61103, so the excess
    forfeited is also 61103; forfeiting before releasing would instead have
    capped 82206 and left a hold standing. Afterwards the account is beyond
    claiming, by PRD 2.8 rung 22: "The reimbursement account's `status` is `OPEN`
    → `ERR_HRA_ACCOUNT_NOT_OPEN` (409), on claim creation and on year-end close."

    Design: Corner/state_machines/hra_close_year_denies_open_claims_then_forfeits_balance
    """
    funded = fx.hra_funded_retiree(api, covered_months=7)
    account = funded["hra_account"]
    retiree_id = funded["retiree"]["id"]
    assert account["annual_credit_cents"] == 122206
    assert account["funded_cents"] == 122206

    fx.set_clock(api, "2027-06-10T00:00:00Z")
    claim = fx.make_claim(
        api,
        account,
        retiree_id,
        expense_category="QUALIFIED_MEDICAL",
        service_date="2027-06-01",
        submitted_cents=40000,
        documentation_reference="EOB-2027-0601",
    )
    held = fx.reload_hra_account(api, account["id"])
    assert held["pending_hold_cents"] == 40000
    assert held["available_balance_cents"] == 82206

    fx.set_clock(api, "2027-12-31T00:00:00Z")
    closed = validate_success(
        api.close_hra_year(account["id"], make_hra_administrator_headers(HRA_ADMIN_1)),
        expected_status=200,
    )

    denied = fx.reload_claim(api, claim["id"])
    assert denied["status"] == "DENIED"
    assert denied["denial_reason_code"] == "ACCOUNT_NOT_OPEN"

    assert closed["pending_hold_cents"] == 0
    assert closed["forfeited_cents"] == 61103
    assert closed["available_balance_cents"] == 61103
    assert closed["available_balance_cents"] != 21103
    assert closed["status"] == "CLOSED"
    assert_instant_equals(
        closed["closed_at"], "2027-12-31T00:00:00.000Z", "closed_at"
    )
    assert closed["funded_cents"] == 122206
    assert closed["substantiated_paid_cents"] == 0
    assert closed["premium_offset_cents"] == 0
    assert_hra_ledger_conservation(closed)

    validate_error(
        api.create_claim(
            f.claim_payload(
                account["id"],
                closed["version"],
                expense_category="QUALIFIED_MEDICAL",
                service_date="2027-06-02",
                submitted_cents=1000,
                documentation_reference="EOB-2027-0602",
            ),
            make_retiree_headers(retiree_id),
        ),
        ApiErrorId.ERR_HRA_ACCOUNT_NOT_OPEN.value,
        expected_status=409,
    )


def test_reinstating_a_lapsed_enrollment_also_unfreezes_its_hra_account(api):
    """The return leg repairs the enrollment and the sibling account together.

    PRD 3.8: "On success, `billing_status` moves from `LAPSED` to `REINSTATED`,
    `consecutive_unpaid_periods` resets to 0,
    `delinquency_first_unpaid_period_start` and `lapse_date` are cleared to null,
    `reinstatement_count` increments by 1, `coverage_status` returns to `ACTIVE`
    with `coverage_end_date` and `termination_reason` cleared to null, the plan
    option's `enrolled_count` increments by 1 with that option's `version`
    incrementing, the `FROZEN` account for the same retiree and plan year returns
    to `OPEN` with its own `version` incrementing, the Medicare secondary-payer
    determination is re-run to refresh `payer_order` and `msp_basis_code`, and
    the enrollment's `version` increments." The refreshed determination lands on
    the first branch of PRD 3.6, because this retiree never left PRE_MEDICARE:
    "If the retiree's `medicare_status` is anything other than
    `MEDICARE_ENROLLED`, then `payer_order` is `GROUP_PRIMARY` with
    `msp_basis_code` `NO_OTHER_COVERAGE`." Nothing resurrects the written-off
    invoices, which is what PRD 3.8 relies on elsewhere: "Written-off invoices are
    excluded from the candidate set entirely, which is what lets a reinstated
    enrollment be re-billed for a period whose earlier invoice was written off at
    lapse."

    Design: Corner/state_machines/lapsed_enrollment_reinstatement_cycle_unfreezes_hra_account
    """
    program = fx.standard_program(api)
    plan_year_id = program["plan_year"]["id"]
    option_id = program["pre65_core"]["id"]
    certified = fx.make_certified_retiree(api, plan_year_id, f.retiree_r1_payload())
    retiree_id = certified["retiree"]["id"]
    enrollment_id = fx.make_enrollment(
        api, retiree_id, plan_year_id, option_id
    )["enrollment"]["id"]

    invoice_ids = [
        fx.make_invoice(api, enrollment_id, start, end)["id"]
        for start, end in (
            ("2027-01-01T00:00:00Z", "2027-01-31T00:00:00Z"),
            ("2027-02-01T00:00:00Z", "2027-02-28T00:00:00Z"),
            ("2027-03-01T00:00:00Z", "2027-03-31T00:00:00Z"),
        )
    ]
    account = fx.make_hra_account(api, retiree_id, plan_year_id, 12)
    assert account["funded_cents"] == 184992
    assert account["available_balance_cents"] == 184992

    fx.set_clock(api, "2027-06-01T00:00:00Z")
    fx.run_daily(api)

    lapsed = fx.reload_enrollment(api, enrollment_id)
    assert lapsed["billing_status"] == "LAPSED"
    assert lapsed["coverage_status"] == "TERMINATED"
    assert lapsed["consecutive_unpaid_periods"] == 3
    assert_instant_equals(
        lapsed["lapse_date"], "2027-06-01T00:00:00.000Z", "lapse_date"
    )
    assert_instant_equals(
        lapsed["reinstatement_deadline"],
        "2027-07-31T00:00:00.000Z",
        "reinstatement_deadline",
    )
    assert fx.reload_hra_account(api, account["id"])["status"] == "FROZEN"
    assert fx.reload_plan_option(api, option_id)["enrolled_count"] == 0

    fx.set_clock(api, "2027-06-15T00:00:00Z")
    reinstated = validate_success(
        api.reinstate_enrollment(
            enrollment_id, make_billing_clerk_headers(BILLING_1)
        ),
        expected_status=200,
    )

    assert reinstated["billing_status"] == "REINSTATED"
    assert reinstated["coverage_status"] == "ACTIVE"
    assert reinstated["coverage_end_date"] is None
    assert reinstated["termination_reason"] is None
    assert reinstated["consecutive_unpaid_periods"] == 0
    assert reinstated["delinquency_first_unpaid_period_start"] is None
    assert reinstated["lapse_date"] is None
    assert reinstated["reinstatement_count"] == 1
    assert reinstated["payer_order"] == "GROUP_PRIMARY"
    assert reinstated["msp_basis_code"] == "NO_OTHER_COVERAGE"

    assert fx.reload_plan_option(api, option_id)["enrolled_count"] == 1

    unfrozen = fx.reload_hra_account(api, account["id"])
    assert unfrozen["status"] == "OPEN"
    assert unfrozen["available_balance_cents"] == 184992
    assert unfrozen["version"] > account["version"]

    rows, meta = validate_paginated(
        api.list_invoices(
            make_billing_clerk_headers(BILLING_1), {"enrollment_id": enrollment_id}
        )
    )
    assert meta["total_count"] == 3
    assert sorted(fx.list_ids(rows)) == sorted(invoice_ids)
    assert [row["status"] for row in rows] == ["WRITTEN_OFF"] * 3
