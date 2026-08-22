"""Recording the award, the two remedy variants and remedy implementation."""

from test_helpers import (
    assert_award,
    assert_instant,
    read_grievance,
    record_award,
    set_clock,
    setup_award_ready_case,
    setup_split_award_case,
    validate_paginated,
    validate_success,
)


def test_gross_remedy_applies_the_split_fraction_before_the_interest(api):
    """PRD §3.8: "The remedy is then computed in two variants. Start with the ordered back
    pay: `back_pay_hours_ordered` multiplied by the grievant's `hourly_rate_cents`, rounded
    half up. Apply the split: multiply that figure by `sustained_fraction_bps`, divide by
    10,000 and round half up — this is the sustained portion. Compute the interest days as
    the whole calendar days from `interest_accrual_start` to `issued_at`, taking 0 days
    whenever `interest_rate_bps` is 0. Interest is then the sustained portion multiplied by
    `interest_rate_bps`, multiplied by the interest days, divided by 10,000 and again by 365
    days in a year, rounded half up. `gross_remedy_cents` is the sustained portion plus that
    interest."

    Design: Difficulty/dual_variant_calc/award_gross_vs_net_remedy_diverge
    """
    ctx = setup_split_award_case()
    award = ctx["award"]
    assert_award(award)

    assert award["gross_remedy_cents"] == 255_141, (
        "252000 sustained portion plus 3141 of interest over 91 days"
    )
    assert award["outcome"] == "SPLIT"
    assert award["sustained_fraction_bps"] == 6_000


def test_net_remedy_subtracts_mitigation_and_the_prior_settlement(api):
    """PRD §3.8: "`net_remedy_cents` is the gross less `mitigation_offset_cents` less the
    grievance's `settled_amount_cents` as it stands at the instant the award is recorded, and
    it is floored at 0 — it never goes negative."

    Design: Difficulty/dual_variant_calc/award_gross_vs_net_remedy_diverge
    """
    ctx = setup_split_award_case()
    award = ctx["award"]

    assert award["net_remedy_cents"] == 165_141
    assert award["gross_remedy_cents"] - award["net_remedy_cents"] == 90_000, (
        "exactly the mitigation offset, because nothing had been settled"
    )
    assert read_grievance(ctx["grievance"]["id"])["settled_amount_cents"] == 0


def test_award_issue_stamps_the_implementation_deadline_and_moves_the_grievance(api):
    """PRD §3.8: "The award is stamped with `issued_at` at the clock's current instant and
    with `implementation_deadline_at` that many days later, and `implemented_cents` starts at
    0."
    PRD §3.8: "When `net_remedy_cents` is greater than 0 or `reinstatement_ordered` is true,
    the award moves from `ISSUED` to `IMPLEMENTATION_PENDING`."

    Design: Difficulty/dual_variant_calc/award_gross_vs_net_remedy_diverge
    """
    ctx = setup_split_award_case()
    award = ctx["award"]

    assert award["status"] == "IMPLEMENTATION_PENDING"
    assert award["implemented_cents"] == 0
    assert_instant(award["issued_at"], "2026-11-14T00:00:00Z", "issued_at")
    assert_instant(
        award["implementation_deadline_at"], "2026-12-14T00:00:00Z", "implementation_deadline_at"
    )
    assert read_grievance(ctx["grievance"]["id"])["status"] == "AWARDED"


def test_the_closing_payment_implements_the_award(api, analyst_headers):
    """PRD §3.8: "The award completes when `implemented_cents` plus `paid_cents` equals
    `net_remedy_cents` **and** either no reinstatement was ordered or the grievant stands at
    `REINSTATED` after this call. The award then moves to `IMPLEMENTED` from
    `IMPLEMENTATION_PENDING`, `PARTIALLY_IMPLEMENTED` or `COMPLIANCE_DISPUTED`,
    `implemented_cents` is set to `net_remedy_cents`, and because the award became implemented
    the grievance moves from `AWARDED` to `CLOSED` with its `version` incremented by 1,
    freezing its timeliness posture."

    Design: Difficulty/transitive_cascade/award_completion_closes_grievance_and_moves_trend_metrics
    """
    ctx = setup_split_award_case()
    set_clock("2026-11-20T00:00:00Z")

    implemented = validate_success(
        api.implement_award(ctx["award"]["id"], {"paid_cents": 165_141}, analyst_headers), 200
    )

    assert implemented["status"] == "IMPLEMENTED"
    assert implemented["implemented_cents"] == 165_141


def test_award_completion_closes_the_grievance_and_freezes_its_posture(api, analyst_headers):
    """PRD §3.8: "The award completes when `implemented_cents` plus `paid_cents` equals
    `net_remedy_cents` **and** either no reinstatement was ordered or the grievant stands at
    `REINSTATED` after this call. The award then moves to `IMPLEMENTED` from
    `IMPLEMENTATION_PENDING`, `PARTIALLY_IMPLEMENTED` or `COMPLIANCE_DISPUTED`,
    `implemented_cents` is set to `net_remedy_cents`, and because the award became implemented
    the grievance moves from `AWARDED` to `CLOSED` with its `version` incremented by 1,
    freezing its timeliness posture."

    Design: Difficulty/transitive_cascade/award_completion_closes_grievance_and_moves_trend_metrics
    """
    ctx = setup_split_award_case()
    set_clock("2026-11-20T00:00:00Z")
    before = read_grievance(ctx["grievance"]["id"])
    assert before["status"] == "AWARDED"
    assert before["timeliness_state"] == "TIMELY"

    validate_success(
        api.implement_award(ctx["award"]["id"], {"paid_cents": 165_141}, analyst_headers), 200
    )

    after = read_grievance(ctx["grievance"]["id"])
    assert after["status"] == "CLOSED"
    assert after["timeliness_state"] == "TIMELY", "frozen at the value held at closure"
    assert after["version"] == before["version"] + 1


def test_closure_moves_the_supervisor_and_clause_trend_metrics(api, analyst_headers, administrator_headers):
    """PRD §3.8: "Because the grievance closed, the cited clause's `sustained_count` and
    `sustain_rate_bps` and the respondent supervisor's `sustained_against_count` and
    `adverse_rate_bps` all observably change on the next read."
    PRD §3.9: "`adverse_rate_bps` is `sustained_against_count` multiplied by 10,000, divided
    by `closed_grievance_count`, rounded half up — and exactly 0 when `closed_grievance_count`
    is 0."

    Design: Difficulty/transitive_cascade/award_completion_closes_grievance_and_moves_trend_metrics
    """
    ctx = setup_split_award_case()
    set_clock("2026-11-20T00:00:00Z")
    before = validate_success(api.get_employee(ctx["supervisor"]["id"], analyst_headers), 200)
    assert before["open_grievance_count"] == 1
    assert before["closed_grievance_count"] == 0
    assert before["adverse_rate_bps"] == 0

    validate_success(
        api.implement_award(ctx["award"]["id"], {"paid_cents": 165_141}, analyst_headers), 200
    )

    supervisor = validate_success(
        api.get_employee(ctx["supervisor"]["id"], analyst_headers), 200
    )
    assert supervisor["open_grievance_count"] == 0
    assert supervisor["closed_grievance_count"] == 1
    assert supervisor["sustained_against_count"] == 1
    assert supervisor["adverse_rate_bps"] == 10_000

    clauses, _ = validate_paginated(
        api.list_contract_clauses(ctx["unit"]["id"], analyst_headers)
    )
    assert clauses[0]["filed_count"] == 1
    assert clauses[0]["sustained_count"] == 1
    assert clauses[0]["denied_count"] == 0
    assert clauses[0]["sustain_rate_bps"] == 10_000

    arbitrator = validate_success(
        api.get_arbitrator(ctx["chan"]["id"], administrator_headers), 200
    )
    assert arbitrator["active_case_count"] == 0
    assert arbitrator["status"] == "AVAILABLE"


def test_net_remedy_floors_at_zero_when_the_mitigation_exceeds_the_gross(api):
    """PRD §3.8: "`net_remedy_cents` is the gross less `mitigation_offset_cents` less the
    grievance's `settled_amount_cents` as it stands at the instant the award is recorded, and
    it is floored at 0 — it never goes negative."
    PRD §3.8: "When `net_remedy_cents` is exactly 0 **and** `reinstatement_ordered` is false,
    there is nothing to implement: the award goes straight from `ISSUED` to `IMPLEMENTED` and
    the grievance is moved to `CLOSED` within that same request."

    Design: Corner/calculations/award_net_remedy_floors_at_zero_when_mitigation_exceeds_gross
    """
    ctx = setup_award_ready_case(
        clock_after_hearing="2026-11-14T00:00:00Z",
        grievance_overrides={"back_pay_hours_claimed": 120},
    )

    award = record_award(
        ctx["demand"]["id"],
        outcome="SPLIT",
        sustained_fraction_bps=6_000,
        back_pay_hours_ordered=120,
        mitigation_offset_cents=300_000,
        interest_rate_bps=500,
        interest_accrual_start="2026-08-15T00:00:00Z",
    )

    assert award["gross_remedy_cents"] == 255_141, "the offset does not touch the gross figure"
    assert award["net_remedy_cents"] == 0
    assert award["status"] == "IMPLEMENTED"
    assert award["implemented_cents"] == 0
    assert read_grievance(ctx["grievance"]["id"])["status"] == "CLOSED"


def test_a_split_award_counts_as_an_adverse_outcome(api, analyst_headers, administrator_headers):
    """PRD §3.9: "A grievance meets that predicate, counted once however many of the
    following are true, when an award exists on its arbitration demand with an `outcome` of
    `SUSTAINED` or `SPLIT`; or when its status is `SETTLED` or `CLOSED` and its
    `settled_amount_cents` is greater than 0; or when any of its steps carries a `disposition`
    of `GRANTED` or `PARTIAL`."

    Design: Corner/calculations/award_net_remedy_floors_at_zero_when_mitigation_exceeds_gross
    """
    ctx = setup_award_ready_case(
        clock_after_hearing="2026-11-14T00:00:00Z",
        grievance_overrides={"back_pay_hours_claimed": 120},
    )
    record_award(
        ctx["demand"]["id"],
        outcome="SPLIT",
        sustained_fraction_bps=6_000,
        back_pay_hours_ordered=120,
        mitigation_offset_cents=300_000,
        interest_rate_bps=500,
        interest_accrual_start="2026-08-15T00:00:00Z",
    )

    supervisor = validate_success(
        api.get_employee(ctx["supervisor"]["id"], analyst_headers), 200
    )
    assert supervisor["closed_grievance_count"] == 1
    assert supervisor["sustained_against_count"] == 1
    assert supervisor["adverse_rate_bps"] == 10_000

    arbitrator = validate_success(
        api.get_arbitrator(ctx["chan"]["id"], administrator_headers), 200
    )
    assert arbitrator["active_case_count"] == 0
    assert arbitrator["status"] == "AVAILABLE"


def test_a_late_short_payment_opens_a_compliance_dispute(api, analyst_headers):
    """PRD §3.8: "When the clock is past `implementation_deadline_at` and the payment still
    leaves `implemented_cents` plus `paid_cents` below `net_remedy_cents`, the award moves
    from `IMPLEMENTATION_PENDING` or `PARTIALLY_IMPLEMENTED` to `COMPLIANCE_DISPUTED`:
    `implemented_cents` grows by the payment, and because the award went past its deadline
    unsatisfied, a system-origin cost entry is posted against the grievance with `category`
    `COUNSEL`, `bearing_party` `EMPLOYER` and `amount_cents` of 150,000 — the office's
    standing enforcement-counsel charge — which in turn re-derives the grievance's cost
    allocation and `cost_posture`."

    Design: Corner/state_machines/late_implementation_opens_compliance_dispute_then_completes
    """
    ctx = setup_split_award_case()
    assert_instant(
        ctx["award"]["implementation_deadline_at"], "2026-12-14T00:00:00Z",
        "implementation_deadline_at",
    )
    set_clock("2026-12-20T00:00:00Z")

    disputed = validate_success(
        api.implement_award(ctx["award"]["id"], {"paid_cents": 100_000}, analyst_headers), 200
    )

    assert disputed["status"] == "COMPLIANCE_DISPUTED"
    assert disputed["implemented_cents"] == 100_000

    entries, meta = validate_paginated(
        api.list_cost_entries(
            ctx["grievance"]["id"], analyst_headers, params={"category": "COUNSEL"}
        )
    )
    assert meta["total_count"] == 1
    assert entries[0]["amount_cents"] == 150_000
    assert entries[0]["bearing_party"] == "EMPLOYER"
    assert entries[0]["origin"] == "SYSTEM"

    grievance = read_grievance(ctx["grievance"]["id"])
    assert grievance["total_cost_cents"] == 574_800
    assert grievance["union_cost_share_cents"] == 240_000
    assert grievance["employer_cost_share_cents"] == 334_800
    assert grievance["cost_posture"] == "COST_OK"
    assert grievance["status"] == "AWARDED"


def test_a_disputed_award_still_completes_on_the_closing_payment(api, analyst_headers):
    """PRD §3.8: "The award completes when `implemented_cents` plus `paid_cents` equals
    `net_remedy_cents` **and** either no reinstatement was ordered or the grievant stands at
    `REINSTATED` after this call. The award then moves to `IMPLEMENTED` from
    `IMPLEMENTATION_PENDING`, `PARTIALLY_IMPLEMENTED` or `COMPLIANCE_DISPUTED`,
    `implemented_cents` is set to `net_remedy_cents`, and because the award became implemented
    the grievance moves from `AWARDED` to `CLOSED` with its `version` incremented by 1,
    freezing its timeliness posture."

    Design: Corner/state_machines/late_implementation_opens_compliance_dispute_then_completes
    """
    ctx = setup_split_award_case()
    set_clock("2026-12-20T00:00:00Z")
    validate_success(
        api.implement_award(ctx["award"]["id"], {"paid_cents": 100_000}, analyst_headers), 200
    )

    completed = validate_success(
        api.implement_award(ctx["award"]["id"], {"paid_cents": 65_141}, analyst_headers), 200
    )

    assert completed["status"] == "IMPLEMENTED"
    assert completed["implemented_cents"] == 165_141
    assert read_grievance(ctx["grievance"]["id"])["status"] == "CLOSED"


def _reinstatement_award_case():
    ctx = setup_award_ready_case(
        grievant_overrides={"employment_status": "TERMINATED"},
        grievance_overrides={"back_pay_hours_claimed": 100},
    )
    ctx["award"] = record_award(
        ctx["demand"]["id"],
        outcome="SUSTAINED",
        sustained_fraction_bps=10_000,
        back_pay_hours_ordered=100,
        reinstatement_ordered=True,
        remedy_deadline_days=45,
    )
    return ctx


def test_full_payment_alone_leaves_a_reinstatement_award_partially_implemented(
    api, analyst_headers
):
    """PRD §3.8: "While the clock is at or before `implementation_deadline_at` and the
    payment leaves the balance short — either because `implemented_cents` plus `paid_cents` is
    still less than `net_remedy_cents`, or because reinstatement was ordered and the grievant
    is not yet `REINSTATED` — the award moves to `PARTIALLY_IMPLEMENTED`, from
    `IMPLEMENTATION_PENDING`, from `PARTIALLY_IMPLEMENTED` itself, or from
    `COMPLIANCE_DISPUTED`, and `implemented_cents` grows by the payment."

    Design: Corner/state_machines/reinstatement_award_completes_only_after_employment_status_reinstated
    """
    ctx = _reinstatement_award_case()
    award = ctx["award"]

    assert award["gross_remedy_cents"] == 350_000
    assert award["net_remedy_cents"] == 350_000
    assert award["status"] == "IMPLEMENTATION_PENDING"
    assert_instant(
        award["implementation_deadline_at"], "2026-11-21T00:00:00Z", "implementation_deadline_at"
    )

    paid = validate_success(
        api.implement_award(award["id"], {"paid_cents": 350_000}, analyst_headers), 200
    )
    assert paid["implemented_cents"] == 350_000
    assert paid["status"] == "PARTIALLY_IMPLEMENTED", "the reinstatement is still outstanding"

    grievant = validate_success(api.get_employee(ctx["grievant"]["id"], analyst_headers), 200)
    assert grievant["employment_status"] == "TERMINATED"


def test_the_reinstatement_date_completes_the_award_and_reinstates_the_grievant(
    api, analyst_headers
):
    """PRD §3.8: "Whenever a `reinstatement_effective_date` is supplied, the grievant's
    `employment_status` is set to `REINSTATED`."
    PRD §3.8: "**Implementation** is recorded by a `LaborRelationsAnalyst`, one payment at a
    time. The payload carries `paid_cents` — which may legitimately be 0 when the money is
    already settled and only the reinstatement is outstanding — and, only for an award that
    ordered reinstatement, a `reinstatement_effective_date`."

    Design: Corner/state_machines/reinstatement_award_completes_only_after_employment_status_reinstated
    """
    ctx = _reinstatement_award_case()
    validate_success(
        api.implement_award(ctx["award"]["id"], {"paid_cents": 350_000}, analyst_headers), 200
    )

    completed = validate_success(
        api.implement_award(
            ctx["award"]["id"],
            {"paid_cents": 0, "reinstatement_effective_date": "2026-10-19T00:00:00Z"},
            analyst_headers,
        ),
        200,
    )

    assert completed["status"] == "IMPLEMENTED"
    grievant = validate_success(api.get_employee(ctx["grievant"]["id"], analyst_headers), 200)
    assert grievant["employment_status"] == "REINSTATED"
    assert read_grievance(ctx["grievance"]["id"])["status"] == "CLOSED"
