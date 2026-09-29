"""Concession programs, the two amortization modes and the committed concession ledger."""

from test_helpers import (
    ApiErrorId,
    apply_concession_credit,
    assert_concession_ledger_identity,
    assert_concession_schedule_sums,
    assert_instant_equals,
    concession_credit_payload,
    concession_decision_payload,
    concession_request_payload,
    create_concession_program,
    create_household,
    draft_lease,
    read_community,
    read_lease,
    read_program,
    request_concession,
    setup_amortizing_lease,
    setup_lease_with_approved_concession,
    setup_released_community,
    validate_error,
    validate_paginated,
    validate_success,
)

TWO_DETACHED_MIX = {"DETACHED": 2, "COTTAGE": 0, "TOWNHOME": 0}
FOUR_DETACHED_MIX = {"DETACHED": 4, "COTTAGE": 0, "TOWNHOME": 0}
ONE_DETACHED_MIX = {"DETACHED": 1, "COTTAGE": 0, "TOWNHOME": 0}


def _aster_ridge_two_available_homes() -> dict:
    """Plat-approved community whose two released DETACHED homes are priced from a single
    PUBLISHED schedule at 285000 cents, so every lease drafted on them freezes
    base_rent_cents 285000, community_services_fee_cents 13050 and
    gross_monthly_charge_cents 298050."""
    return setup_released_community(
        homesite_count=2,
        total_planned_units=2,
        product_mix=dict(TWO_DETACHED_MIX),
        asking_rent_cents=285_000,
        concession_budget_cents=5_000_000,
        facility_commitment_cents=80_000_000,
        name="Aster Ridge",
        market_code="TX-DFW",
    )


def _twelve_month_program(community_id: str, program_code: str, amortization_mode: str) -> dict:
    """ACTIVE six-free-week program differing from its sibling only in amortization_mode."""
    return create_concession_program(
        community_id,
        program_code=program_code,
        tier="AGGRESSIVE",
        free_weeks=6,
        amortization_mode=amortization_mode,
        eligible_product_types=["DETACHED"],
        restricted_posture_eligible=False,
        max_budget_cents=2_000_000,
    )


def test_straight_line_concession_repeats_the_period_credit_and_parks_the_residual_last(
    api, leasing_agent_headers
):
    """A six-free-week straight-line concession on a twelve-month lease at 298050 cents gross
    totals 412685 cents, and the schedule carries eleven 34390-cent periods followed by a
    34395-cent final period that absorbs the residual.

    "First, `total_concession_cents` is the lease's `gross_monthly_charge_cents` multiplied by the program's `free_weeks`, multiplied by 12 and divided by 52 — the weeks-per-month conversion that turns a weekly allowance into monthly charges — rounded half up to whole cents."
    "The concession is rounded exactly once, here at the total."
    "Under `STRAIGHT_LINE_NET_EFFECTIVE`, a per-period credit is computed as `total_concession_cents` divided by `term_months`, rounded half up to whole cents; the schedule then holds that per-period credit repeated for one fewer period than the term, and a final period whose credit is `total_concession_cents` minus the per-period credit multiplied by the number of those earlier periods — the final period absorbs the entire rounding residual."
    "Rounding each period independently and summing, or summing exact per-period values and rounding at the end, is wrong in both modes."
    "Finally `concession_remaining_cents` is set equal to `total_concession_cents` and `concession_applied_cents` is set to 0."

    Design: Difficulty/dual_variant_calc/concession_straight_line_versus_upfront_from_identical_lease_inputs
    """
    scenario = _aster_ridge_two_available_homes()
    household = create_household()
    lease = draft_lease(scenario["homesites"][0]["id"], household["id"], term_months=12)
    assert lease["base_rent_cents"] == 285_000
    assert lease["community_services_fee_cents"] == 13_050
    assert lease["gross_monthly_charge_cents"] == 298_050

    program = _twelve_month_program(
        scenario["community"]["id"], "CP-SL", "STRAIGHT_LINE_NET_EFFECTIVE"
    )

    data = validate_success(
        api.request_concession(
            lease["id"], concession_request_payload(program["id"]), leasing_agent_headers
        ),
        expected_status=201,
    )

    assert data["concession_status"] == "REQUESTED"
    assert data["total_concession_cents"] == 412685
    schedule = data["concession_schedule"]
    assert len(schedule) == 12
    assert [entry["credit_cents"] for entry in schedule[:11]] == [34390] * 11
    assert schedule[11]["credit_cents"] == 34395
    assert_concession_schedule_sums(data)
    assert sum(entry["credit_cents"] for entry in schedule) == 412685
    assert data["concession_remaining_cents"] == 412685
    assert data["concession_applied_cents"] == 0


def test_upfront_free_rent_concession_consumes_whole_months_of_gross_charge(
    api, leasing_agent_headers
):
    """The same 412685-cent concession under UPFRONT_FREE_RENT lays out only two periods — a
    full 298050-cent month of gross charge and a 114635-cent remainder — leaving the
    resident's first period charge at exactly 0.

    "`UPFRONT_FREE_RENT` consumes the concession in the earliest periods instead, giving the resident whole free months at the front of the term and only then reverting to the full charge."
    "Under `UPFRONT_FREE_RENT`, the schedule is built by consuming the concession in whole months of gross charge: while any concession remains unallocated, the next period takes whichever is smaller of `gross_monthly_charge_cents` and the amount still remaining, and that amount is deducted from the remainder; the loop therefore produces as many periods as it takes to exhaust the concession, with every period but the last carrying a full month of gross charge and the last carrying whatever is left."
    "`monthly_concession_credit_cents` is the `credit_cents` of period 1, or 0 when the schedule is empty — which under `STRAIGHT_LINE_NET_EFFECTIVE` is a modest figure and under `UPFRONT_FREE_RENT` is a full month of gross charge."
    "`first_period_charge_cents` is `gross_monthly_charge_cents` minus that first-period credit, floored at 0 so it is never negative — which under `UPFRONT_FREE_RENT` is exactly 0."

    Design: Difficulty/dual_variant_calc/concession_straight_line_versus_upfront_from_identical_lease_inputs
    """
    scenario = _aster_ridge_two_available_homes()
    household = create_household()
    lease = draft_lease(scenario["homesites"][1]["id"], household["id"], term_months=12)
    assert lease["gross_monthly_charge_cents"] == 298_050

    program = _twelve_month_program(scenario["community"]["id"], "CP-UP", "UPFRONT_FREE_RENT")

    data = validate_success(
        api.request_concession(
            lease["id"], concession_request_payload(program["id"]), leasing_agent_headers
        ),
        expected_status=201,
    )

    assert data["total_concession_cents"] == 412685
    assert [entry["credit_cents"] for entry in data["concession_schedule"]] == [298050, 114635]
    assert_concession_schedule_sums(data)
    assert data["monthly_concession_credit_cents"] == 298050
    assert data["first_period_charge_cents"] == 0
    assert data["concession_remaining_cents"] == 412685


def test_both_amortization_modes_report_the_same_net_effective_rent_from_identical_inputs(
    api, leasing_agent_headers
):
    """Two leases with byte-identical pricing inputs diverge only on their program's
    amortization mode: the straight-line lease reports a 34390-cent first credit against a
    263660-cent first period charge while the upfront lease reports 298050 against 0, yet
    both report total_concession_cents 412685 and net_effective_rent_cents 263660.

    "`amortization_mode` is the program field that changes the shape of every lease that attaches to it, and it takes one of two values."
    "`STRAIGHT_LINE_NET_EFFECTIVE` spreads the concession evenly across the whole lease term, which keeps the resident's first cheque close to the full charge and reports a smooth net effective rent."
    "`net_effective_rent_cents` is `gross_monthly_charge_cents` multiplied by `term_months`, minus `total_concession_cents`, divided by `term_months`, rounded half up to whole cents; it is deliberately mode-independent, so the two modes report the same net effective rent from the same inputs and differ only in cash timing."
    "A new program is stored with `status` `ACTIVE`, `committed_cents` 0 and `superseded_at` null, the community's previously `ACTIVE` program moves to `status` `SUPERSEDED` with `superseded_at` stamped at the current logical clock, and the community's `version` increments."

    Design: Difficulty/dual_variant_calc/concession_straight_line_versus_upfront_from_identical_lease_inputs
    """
    scenario = _aster_ridge_two_available_homes()
    first_household = create_household(
        primary_applicant_name="Ann Reyes", email="ann@example.com", household_size=4
    )
    second_household = create_household(
        primary_applicant_name="Ben Ortiz", email="ben@example.com", household_size=3
    )
    straight_line_lease = draft_lease(
        scenario["homesites"][0]["id"], first_household["id"], term_months=12
    )
    upfront_lease = draft_lease(
        scenario["homesites"][1]["id"], second_household["id"], term_months=12
    )
    assert straight_line_lease["gross_monthly_charge_cents"] == 298_050
    assert upfront_lease["gross_monthly_charge_cents"] == 298_050
    assert straight_line_lease["term_months"] == upfront_lease["term_months"] == 12

    straight_line_program = _twelve_month_program(
        scenario["community"]["id"], "CP-SL", "STRAIGHT_LINE_NET_EFFECTIVE"
    )
    request_concession(straight_line_lease["id"], straight_line_program["id"])
    upfront_program = _twelve_month_program(
        scenario["community"]["id"], "CP-UP", "UPFRONT_FREE_RENT"
    )

    upfront = validate_success(
        api.request_concession(
            upfront_lease["id"],
            concession_request_payload(upfront_program["id"]),
            leasing_agent_headers,
        ),
        expected_status=201,
    )
    straight_line = read_lease(straight_line_lease["id"])

    assert straight_line["total_concession_cents"] == 412685
    assert upfront["total_concession_cents"] == 412685
    assert straight_line["net_effective_rent_cents"] == 263660
    assert upfront["net_effective_rent_cents"] == 263660
    assert len(straight_line["concession_schedule"]) == 12
    assert len(upfront["concession_schedule"]) == 2
    assert straight_line["monthly_concession_credit_cents"] == 34390
    assert upfront["monthly_concession_credit_cents"] == 298050
    assert straight_line["first_period_charge_cents"] == 263660
    assert upfront["first_period_charge_cents"] == 0
    assert straight_line["concession_remaining_cents"] == 412685
    assert upfront["concession_remaining_cents"] == 412685
    assert read_program(straight_line_program["id"])["status"] == "SUPERSEDED"
    assert read_program(upfront_program["id"])["status"] == "ACTIVE"


def _dunmore_field_eighteen_month_draft() -> tuple:
    """One released DETACHED home at 285000 cents, an ACTIVE eleven-free-week straight-line
    program and a DRAFT lease whose term_months is 18 and gross charge 298050 cents."""
    scenario = setup_released_community(
        homesite_count=1,
        total_planned_units=1,
        product_mix=dict(ONE_DETACHED_MIX),
        asking_rent_cents=285_000,
        concession_budget_cents=5_000_000,
        facility_commitment_cents=20_000_000,
        maintenance_tech_headcount=1,
        name="Dunmore Field",
        market_code="TX-DFW",
    )
    household = create_household(
        primary_applicant_name="Eli Novak", email="eli@example.com", household_size=5
    )
    lease = draft_lease(scenario["homesites"][0]["id"], household["id"], term_months=18)
    assert lease["gross_monthly_charge_cents"] == 298_050
    assert lease["term_months"] == 18
    program = create_concession_program(
        scenario["community"]["id"],
        program_code="CP-18",
        tier="AGGRESSIVE",
        free_weeks=11,
        amortization_mode="STRAIGHT_LINE_NET_EFFECTIVE",
        eligible_product_types=["DETACHED"],
        restricted_posture_eligible=False,
        max_budget_cents=2_000_000,
    )
    return lease, program


def test_an_eighteen_month_straight_line_schedule_rounds_once_at_the_total(
    api, leasing_agent_headers
):
    """An eleven-free-week concession over eighteen months totals 756588 cents and lays out
    seventeen 42033-cent periods with a smaller 42027-cent residual in period eighteen, so the
    schedule sums to 756588 rather than the 756594 that per-period rounding would produce.

    "First, `total_concession_cents` is the lease's `gross_monthly_charge_cents` multiplied by the program's `free_weeks`, multiplied by 12 and divided by 52 — the weeks-per-month conversion that turns a weekly allowance into monthly charges — rounded half up to whole cents."
    "The two amortization modes then lay out the periods differently, and both must satisfy the same invariant: the `credit_cents` values across `concession_schedule` sum to `total_concession_cents` exactly."
    "Under `STRAIGHT_LINE_NET_EFFECTIVE`, a per-period credit is computed as `total_concession_cents` divided by `term_months`, rounded half up to whole cents; the schedule then holds that per-period credit repeated for one fewer period than the term, and a final period whose credit is `total_concession_cents` minus the per-period credit multiplied by the number of those earlier periods — the final period absorbs the entire rounding residual."
    "Rounding each period independently and summing, or summing exact per-period values and rounding at the end, is wrong in both modes."

    Design: Difficulty/combinatorial_formula/concession_rounding_order_places_residual_in_the_final_period
    """
    lease, program = _dunmore_field_eighteen_month_draft()

    data = validate_success(
        api.request_concession(
            lease["id"], concession_request_payload(program["id"]), leasing_agent_headers
        ),
        expected_status=201,
    )

    assert data["total_concession_cents"] == 756588
    schedule = data["concession_schedule"]
    assert len(schedule) == 18
    assert schedule[0]["credit_cents"] == 42033
    assert schedule[16]["credit_cents"] == 42033
    assert [entry["credit_cents"] for entry in schedule[:17]] == [42033] * 17
    assert schedule[17]["credit_cents"] == 42027
    assert sum(entry["credit_cents"] for entry in schedule) == 756588
    assert sum(entry["credit_cents"] for entry in schedule) != 756594
    assert_concession_schedule_sums(data)


def test_an_eighteen_month_lease_reports_figures_taken_from_its_pinned_first_period_credit(
    api, leasing_agent_headers
):
    """The eighteen-month straight-line lease reports monthly_concession_credit_cents 42033
    from period one, a first period charge of 256017 cents, and the same 256017-cent net
    effective rent, with the whole 756588-cent concession still outstanding.

    "`concession_schedule` itself is an ordered array of objects, each carrying a `period_index` numbered from 1 upward and the `credit_cents` for that period."
    "`monthly_concession_credit_cents` is the `credit_cents` of period 1, or 0 when the schedule is empty — which under `STRAIGHT_LINE_NET_EFFECTIVE` is a modest figure and under `UPFRONT_FREE_RENT` is a full month of gross charge."
    "`first_period_charge_cents` is `gross_monthly_charge_cents` minus that first-period credit, floored at 0 so it is never negative — which under `UPFRONT_FREE_RENT` is exactly 0."
    "`net_effective_rent_cents` is `gross_monthly_charge_cents` multiplied by `term_months`, minus `total_concession_cents`, divided by `term_months`, rounded half up to whole cents; it is deliberately mode-independent, so the two modes report the same net effective rent from the same inputs and differ only in cash timing."
    "Finally `concession_remaining_cents` is set equal to `total_concession_cents` and `concession_applied_cents` is set to 0."

    Design: Difficulty/combinatorial_formula/concession_rounding_order_places_residual_in_the_final_period
    """
    lease, program = _dunmore_field_eighteen_month_draft()

    data = validate_success(
        api.request_concession(
            lease["id"], concession_request_payload(program["id"]), leasing_agent_headers
        ),
        expected_status=201,
    )

    assert data["total_concession_cents"] == 756588
    assert [entry["period_index"] for entry in data["concession_schedule"]] == list(range(1, 19))
    assert data["monthly_concession_credit_cents"] == 42033
    assert data["first_period_charge_cents"] == 256017
    assert data["net_effective_rent_cents"] == 256017
    assert data["concession_remaining_cents"] == 756588
    assert data["concession_applied_cents"] == 0


def _yewbank_amortizing_lease() -> dict:
    """ACTIVE lease whose APPROVED 412685-cent straight-line concession became AMORTIZING at
    activation, so both committed ledgers stand at 412685 cents before any credit is posted."""
    scenario = setup_amortizing_lease(
        homesite_count=1,
        total_planned_units=2,
        product_mix=dict(TWO_DETACHED_MIX),
        asking_rent_cents=285_000,
        concession_budget_cents=2_000_000,
        facility_commitment_cents=40_000_000,
        maintenance_tech_headcount=1,
        name="Yewbank",
        market_code="TX-SAT",
        household_overrides={
            "primary_applicant_name": "Bree Halloway",
            "email": "bree@example.com",
        },
        program_overrides={
            "program_code": "CP-YB",
            "tier": "AGGRESSIVE",
            "free_weeks": 6,
            "amortization_mode": "STRAIGHT_LINE_NET_EFFECTIVE",
            "eligible_product_types": ["DETACHED"],
            "restricted_posture_eligible": False,
            "max_budget_cents": 2_000_000,
        },
    )
    lease = scenario["lease"]
    assert lease["lease_status"] == "ACTIVE"
    assert lease["concession_status"] == "AMORTIZING"
    assert lease["total_concession_cents"] == 412685
    assert lease["concession_remaining_cents"] == 412685
    assert lease["credits_applied_count"] == 0
    assert lease["monthly_concession_credit_cents"] == 34390
    assert scenario["community"]["committed_concession_cents"] == 412685
    assert scenario["program"]["committed_cents"] == 412685
    return scenario


def test_posting_the_first_concession_credit_moves_all_three_committed_totals_in_lockstep(
    api, property_manager_headers
):
    """Posting period one of the twelve-period schedule applies 34390 cents and drives the
    lease, the program and the community from 412685 to 378295 cents by the same amount, with
    the concession still AMORTIZING.

    "Credits are posted one period at a time by the `PropertyManager` once the lease is amortizing."
    "The credit taken is the `credit_cents` of the schedule entry at that `period_index`."
    "No rounding occurs at application time."
    "A community's `committed_concession_cents` must always equal the sum of `concession_remaining_cents` across the leases of that community whose `concession_status` is `APPROVED` or `AMORTIZING`."
    "The parallel invariant holds per program: a `ConcessionProgram`'s `committed_cents` must always equal the sum of `concession_remaining_cents` across the leases carrying that `concession_program_id` whose `concession_status` is `APPROVED` or `AMORTIZING`."

    Design: Difficulty/compensating_invariant/concession_credit_application_preserves_the_committed_ledger_identity
    """
    scenario = _yewbank_amortizing_lease()

    data = validate_success(
        api.apply_concession_credit(
            scenario["lease"]["id"], concession_credit_payload(1), property_manager_headers
        ),
        expected_status=201,
    )

    assert data["concession_applied_cents"] == 34390
    assert data["concession_remaining_cents"] == 378295
    assert data["credits_applied_count"] == 1
    assert data["concession_status"] == "AMORTIZING"

    community = read_community(scenario["community"]["id"])
    program = read_program(scenario["program"]["id"])
    assert community["committed_concession_cents"] == 378295
    assert program["committed_cents"] == 378295
    assert_concession_ledger_identity(community, [read_lease(scenario["lease"]["id"])], program)


def test_a_skipped_concession_period_is_refused_and_leaves_the_committed_ledger_untouched(
    api, property_manager_headers
):
    """After period one has been posted, jumping to period three is refused and leaves the
    lease, the program and the community all standing at 378295 cents; posting period two then
    advances all three to 343905 cents against the same frozen schedule.

    "The posting names a `period_index`, which must be exactly `credits_applied_count` plus 1 and must not exceed the number of periods in `concession_schedule`; anything else is `ERR_CONCESSION_PERIOD_OUT_OF_ORDER`."
    "A community's `committed_concession_cents` must always equal the sum of `concession_remaining_cents` across the leases of that community whose `concession_status` is `APPROVED` or `AMORTIZING`."
    "The parallel invariant holds per program: a `ConcessionProgram`'s `committed_cents` must always equal the sum of `concession_remaining_cents` across the leases carrying that `concession_program_id` whose `concession_status` is `APPROVED` or `AMORTIZING`."

    Design: Difficulty/compensating_invariant/concession_credit_application_preserves_the_committed_ledger_identity
    """
    scenario = _yewbank_amortizing_lease()
    lease_id = scenario["lease"]["id"]
    apply_concession_credit(lease_id, 1)

    validate_error(
        api.apply_concession_credit(
            lease_id, concession_credit_payload(3), property_manager_headers
        ),
        ApiErrorId.ERR_CONCESSION_PERIOD_OUT_OF_ORDER.value,
    )

    after_refusal = read_lease(lease_id)
    community = read_community(scenario["community"]["id"])
    program = read_program(scenario["program"]["id"])
    assert after_refusal["concession_applied_cents"] == 34390
    assert after_refusal["concession_remaining_cents"] == 378295
    assert after_refusal["credits_applied_count"] == 1
    assert community["committed_concession_cents"] == 378295
    assert program["committed_cents"] == 378295
    assert_concession_ledger_identity(community, [after_refusal], program)

    second = validate_success(
        api.apply_concession_credit(
            lease_id, concession_credit_payload(2), property_manager_headers
        ),
        expected_status=201,
    )
    assert second["concession_applied_cents"] == 68780
    assert second["concession_remaining_cents"] == 343905
    assert second["credits_applied_count"] == 2
    assert [entry["credit_cents"] for entry in second["concession_schedule"]] == (
        [34390] * 11 + [34395]
    )

    community = read_community(scenario["community"]["id"])
    program = read_program(scenario["program"]["id"])
    assert community["committed_concession_cents"] == 343905
    assert program["committed_cents"] == 343905
    assert_concession_ledger_identity(community, [read_lease(lease_id)], program)


def test_a_concession_request_against_a_superseded_program_is_rejected(
    api, leasing_agent_headers, asset_manager_headers
):
    """Publishing a second program retires the first, so a request still citing the retired
    program code is refused while the identical request against the live program succeeds; the
    retired program stays readable.

    "A concession program is the community's standing offer, and only one is live at a time."
    "A new program is stored with `status` `ACTIVE`, `committed_cents` 0 and `superseded_at` null, the community's previously `ACTIVE` program moves to `status` `SUPERSEDED` with `superseded_at` stamped at the current logical clock, and the community's `version` increments."
    "The named program must have `status` `ACTIVE` and must belong to the lease's community, so a request against a program that has been superseded is `ERR_CONCESSION_PROGRAM_NOT_ACTIVE`."
    "Concession programs may be filtered by `community_id` and `status`."
    "Read endpoints return HTTP 200, as does the logical-clock endpoint."

    Design: Corner/validations/a_concession_request_against_a_superseded_program_is_rejected
    """
    scenario = setup_released_community(
        homesite_count=1,
        total_planned_units=4,
        product_mix=dict(FOUR_DETACHED_MIX),
        asking_rent_cents=285_000,
        concession_budget_cents=2_000_000,
        facility_commitment_cents=25_000_000,
        name="Umberton",
        market_code="OH-CMH",
    )
    community_id = scenario["community"]["id"]
    retired_program = create_concession_program(
        community_id,
        program_code="UB-FALL",
        tier="LIGHT",
        free_weeks=2,
        amortization_mode="STRAIGHT_LINE_NET_EFFECTIVE",
        eligible_product_types=["DETACHED"],
        max_budget_cents=1_000_000,
    )
    live_program = create_concession_program(
        community_id,
        program_code="UB-WINTER",
        tier="MODERATE",
        free_weeks=4,
        amortization_mode="STRAIGHT_LINE_NET_EFFECTIVE",
        eligible_product_types=["DETACHED"],
        max_budget_cents=1_000_000,
    )
    household = create_household(
        primary_applicant_name="Uma Bright", email="uma@example.com"
    )
    lease = draft_lease(scenario["homesites"][0]["id"], household["id"])

    retired = read_program(retired_program["id"])
    assert retired["status"] == "SUPERSEDED"
    assert_instant_equals(retired["superseded_at"], "2026-08-01T00:00:00Z", "superseded_at")
    assert read_program(live_program["id"])["status"] == "ACTIVE"

    validate_error(
        api.request_concession(
            lease["id"],
            concession_request_payload(retired_program["id"]),
            leasing_agent_headers,
        ),
        ApiErrorId.ERR_CONCESSION_PROGRAM_NOT_ACTIVE.value,
    )
    assert read_lease(lease["id"])["concession_status"] == "NONE"

    accepted = validate_success(
        api.request_concession(
            lease["id"],
            concession_request_payload(live_program["id"]),
            leasing_agent_headers,
        ),
        expected_status=201,
    )
    assert accepted["concession_status"] == "REQUESTED"
    assert accepted["concession_program_id"] == live_program["id"]

    programs, meta = validate_paginated(
        api.list_concession_programs(
            asset_manager_headers, {"community_id": community_id, "status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 1
    assert [program["id"] for program in programs] == [live_program["id"]]
    validate_success(
        api.get_concession_program(retired_program["id"], asset_manager_headers),
        expected_status=200,
    )


def test_concession_decisions_and_re_requests_outside_the_requested_state_are_rejected(
    api, asset_manager_headers, leasing_agent_headers, property_manager_headers
):
    """Once a two-free-week concession of 137562 cents has been approved, a second decision, a
    re-request and a credit posting are all refused with the same concession-state error, and
    none of them moves the committed budget.

    "The request is legal when `concession_status` is `NONE`, `REJECTED` or `REVOKED` — the transitions `NONE → REQUESTED`, `REJECTED → REQUESTED` and `REVOKED → REQUESTED` are the three entry paths and all three run identical arithmetic — and illegal while the concession is already `REQUESTED`, `APPROVED`, `AMORTIZING` or `EXHAUSTED`, which is `ERR_INVALID_CONCESSION_STATE`."
    "The concession must be `REQUESTED` — deciding anything else is `ERR_INVALID_CONCESSION_STATE` — and the deciding `X-User-ID` must differ from `concession_requested_by_user_id`, or the decision is `ERR_SEGREGATION_OF_DUTIES`."
    "The concession must be `AMORTIZING`, or the posting is `ERR_INVALID_CONCESSION_STATE`."
    "On approval `concession_status` becomes `APPROVED`, `concession_decided_by_user_id` records the deciding `X-User-ID`, and both ledgers grow by `total_concession_cents` — the community's `committed_concession_cents` and the program's `committed_cents`."

    Design: Corner/validations/concession_decisions_and_re_requests_outside_the_requested_state_are_rejected
    """
    scenario = setup_lease_with_approved_concession(
        homesite_count=1,
        total_planned_units=4,
        product_mix=dict(FOUR_DETACHED_MIX),
        asking_rent_cents=285_000,
        concession_budget_cents=2_000_000,
        facility_commitment_cents=25_000_000,
        name="Vinewood",
        market_code="OH-CLE",
        household_overrides={"primary_applicant_name": "Vera Wood", "email": "vera@example.com"},
        program_overrides={
            "program_code": "VW-SPRING",
            "tier": "LIGHT",
            "free_weeks": 2,
            "amortization_mode": "STRAIGHT_LINE_NET_EFFECTIVE",
            "eligible_product_types": ["DETACHED"],
            "max_budget_cents": 1_000_000,
        },
    )
    lease_id = scenario["lease"]["id"]
    assert scenario["lease"]["concession_status"] == "APPROVED"
    assert scenario["lease"]["total_concession_cents"] == 137562
    assert scenario["community"]["committed_concession_cents"] == 137562
    assert scenario["program"]["committed_cents"] == 137562

    validate_error(
        api.decide_concession(
            lease_id,
            concession_decision_payload("REJECT", decision_note="second thoughts"),
            asset_manager_headers,
        ),
        ApiErrorId.ERR_INVALID_CONCESSION_STATE.value,
    )
    validate_error(
        api.request_concession(
            lease_id,
            concession_request_payload(scenario["program"]["id"]),
            leasing_agent_headers,
        ),
        ApiErrorId.ERR_INVALID_CONCESSION_STATE.value,
    )
    validate_error(
        api.apply_concession_credit(
            lease_id, concession_credit_payload(1), property_manager_headers
        ),
        ApiErrorId.ERR_INVALID_CONCESSION_STATE.value,
    )

    lease = read_lease(lease_id)
    community = read_community(scenario["community"]["id"])
    program = read_program(scenario["program"]["id"])
    assert lease["concession_status"] == "APPROVED"
    assert lease["credits_applied_count"] == 0
    assert lease["concession_remaining_cents"] == 137562
    assert community["committed_concession_cents"] == 137562
    assert program["committed_cents"] == 137562
    assert_concession_ledger_identity(community, [lease], program)


def test_a_concession_approval_beyond_the_community_budget_is_rejected(
    api, asset_manager_headers, leasing_agent_headers
):
    """A 412685-cent concession is computed and parked in REQUESTED without complaint, and only
    the approval is refused against a community budget of 100000 cents; rejecting it and
    re-requesting under a one-free-week program that costs 68781 cents then approves cleanly.

    "An `APPROVE` decision additionally tests two budgets."
    "The program's `committed_cents` plus this lease's `total_concession_cents` must not exceed the program's `max_budget_cents`, and the community's `committed_concession_cents` plus the same amount must not exceed the community's `concession_budget_cents`; either overrun is refused with `ERR_CONCESSION_BUDGET_EXCEEDED`."
    "A `REJECT` decision carries no budget test: `concession_status` becomes `REJECTED`, `concession_decided_by_user_id` records the deciding `X-User-ID`, and the lease's concession arithmetic is wound back — `total_concession_cents`, `monthly_concession_credit_cents`, `first_period_charge_cents` and `concession_remaining_cents` all return to 0 and `concession_schedule` returns to an empty list."
    "On approval `concession_status` becomes `APPROVED`, `concession_decided_by_user_id` records the deciding `X-User-ID`, and both ledgers grow by `total_concession_cents` — the community's `committed_concession_cents` and the program's `committed_cents`."

    Design: Corner/validations/a_concession_approval_beyond_the_community_budget_is_rejected
    """
    scenario = setup_released_community(
        homesite_count=1,
        total_planned_units=4,
        product_mix=dict(FOUR_DETACHED_MIX),
        asking_rent_cents=285_000,
        concession_budget_cents=100_000,
        facility_commitment_cents=25_000_000,
        name="Wrenfield",
        market_code="MO-STL",
    )
    community_id = scenario["community"]["id"]
    generous_program = create_concession_program(
        community_id,
        program_code="WF-SIXWEEK",
        tier="AGGRESSIVE",
        free_weeks=6,
        amortization_mode="STRAIGHT_LINE_NET_EFFECTIVE",
        eligible_product_types=["DETACHED"],
        max_budget_cents=1_000_000,
    )
    household = create_household(primary_applicant_name="Wes Finn", email="wes@example.com")
    lease = draft_lease(scenario["homesites"][0]["id"], household["id"])
    requested = request_concession(lease["id"], generous_program["id"])
    assert requested["total_concession_cents"] == 412685
    assert requested["concession_status"] == "REQUESTED"

    validate_error(
        api.decide_concession(
            lease["id"],
            concession_decision_payload("APPROVE", decision_note="too rich"),
            asset_manager_headers,
        ),
        ApiErrorId.ERR_CONCESSION_BUDGET_EXCEEDED.value,
    )
    assert read_lease(lease["id"])["concession_status"] == "REQUESTED"
    assert read_community(community_id)["committed_concession_cents"] == 0
    assert read_program(generous_program["id"])["committed_cents"] == 0

    rejected = validate_success(
        api.decide_concession(
            lease["id"],
            concession_decision_payload("REJECT", decision_note="over budget"),
            asset_manager_headers,
        ),
        expected_status=201,
    )
    assert rejected["concession_status"] == "REJECTED"
    assert rejected["total_concession_cents"] == 0
    assert rejected["concession_schedule"] == []
    assert rejected["monthly_concession_credit_cents"] == 0
    assert rejected["first_period_charge_cents"] == 0
    assert rejected["concession_remaining_cents"] == 0

    modest_program = create_concession_program(
        community_id,
        program_code="WF-ONEWEEK",
        tier="LIGHT",
        free_weeks=1,
        amortization_mode="STRAIGHT_LINE_NET_EFFECTIVE",
        eligible_product_types=["DETACHED"],
        max_budget_cents=1_000_000,
    )
    re_requested = validate_success(
        api.request_concession(
            lease["id"],
            concession_request_payload(modest_program["id"]),
            leasing_agent_headers,
        ),
        expected_status=201,
    )
    assert re_requested["total_concession_cents"] == 68781
    assert re_requested["concession_status"] == "REQUESTED"

    approved = validate_success(
        api.decide_concession(
            lease["id"],
            concession_decision_payload("APPROVE", decision_note="fits"),
            asset_manager_headers,
        ),
        expected_status=201,
    )
    assert approved["concession_status"] == "APPROVED"
    community = read_community(community_id)
    program = read_program(modest_program["id"])
    assert community["committed_concession_cents"] == 68781
    assert program["committed_cents"] == 68781
    assert_concession_ledger_identity(community, [read_lease(lease["id"])], program)


def test_a_concession_program_that_does_not_list_the_product_type_is_rejected(
    api, leasing_agent_headers
):
    """A COTTAGE-only program refuses a request from a DETACHED home and leaves the lease's
    concession fields untouched, while an otherwise identical program that lists DETACHED alongside
    COTTAGE accepts the same request and prices a single-period upfront credit of 137562 cents.

    "The home's `product_type` must appear in the program's `eligible_product_types`, failing which the request is `ERR_PRODUCT_TYPE_NOT_ELIGIBLE`."
    "The program also declares `eligible_product_types`, a non-empty subset of `DETACHED`, `COTTAGE` and `TOWNHOME`, a `max_budget_cents` program-level cap that may not be negative, and an optional `restricted_posture_eligible` flag that defaults to false."
    "On success `concession_status` becomes `REQUESTED`, `concession_program_id` is stored, and `concession_requested_by_user_id` records the acting `X-User-ID`; on the re-request path after a rejection, `concession_decided_by_user_id` is reset to null."
    "Under `UPFRONT_FREE_RENT`, the schedule is built by consuming the concession in whole months of gross charge: while any concession remains unallocated, the next period takes whichever is smaller of `gross_monthly_charge_cents` and the amount still remaining, and that amount is deducted from the remainder; the loop therefore produces as many periods as it takes to exhaust the concession, with every period but the last carrying a full month of gross charge and the last carrying whatever is left."

    Design: Corner/validations/a_concession_program_that_does_not_list_the_product_type_is_rejected
    """
    scenario = setup_released_community(
        homesite_count=1,
        total_planned_units=4,
        product_mix=dict(FOUR_DETACHED_MIX),
        asking_rent_cents=285_000,
        concession_budget_cents=2_000_000,
        facility_commitment_cents=25_000_000,
        name="Yewbank Commons",
        market_code="MO-KCY",
    )
    community_id = scenario["community"]["id"]
    cottage_only_program = create_concession_program(
        community_id,
        program_code="YB-COTTAGE",
        tier="MODERATE",
        free_weeks=2,
        amortization_mode="UPFRONT_FREE_RENT",
        eligible_product_types=["COTTAGE"],
        max_budget_cents=1_000_000,
    )
    assert cottage_only_program["eligible_product_types"] == ["COTTAGE"]
    household = create_household(primary_applicant_name="Yuri Bank", email="yuri@example.com")
    # The eligibility rule reads the *home's* product_type; the PRD declares product_type on
    # the homesite, not on the lease, so the precondition is asserted where it is declared.
    assert scenario["homesites"][0]["product_type"] == "DETACHED"
    lease = draft_lease(scenario["homesites"][0]["id"], household["id"])

    validate_error(
        api.request_concession(
            lease["id"],
            concession_request_payload(cottage_only_program["id"]),
            leasing_agent_headers,
        ),
        ApiErrorId.ERR_PRODUCT_TYPE_NOT_ELIGIBLE.value,
    )
    untouched = read_lease(lease["id"])
    assert untouched["concession_status"] == "NONE"
    assert untouched["concession_program_id"] is None
    assert untouched["total_concession_cents"] == 0
    assert untouched["concession_schedule"] == []
    assert read_program(cottage_only_program["id"])["committed_cents"] == 0

    all_product_program = create_concession_program(
        community_id,
        program_code="YB-ALLPROD",
        tier="MODERATE",
        free_weeks=2,
        amortization_mode="UPFRONT_FREE_RENT",
        eligible_product_types=["DETACHED", "COTTAGE"],
        max_budget_cents=1_000_000,
    )
    accepted = validate_success(
        api.request_concession(
            lease["id"],
            concession_request_payload(all_product_program["id"]),
            leasing_agent_headers,
        ),
        expected_status=201,
    )
    assert accepted["concession_status"] == "REQUESTED"
    assert accepted["concession_program_id"] == all_product_program["id"]
    assert accepted["total_concession_cents"] == 137562
    assert len(accepted["concession_schedule"]) == 1
    assert accepted["concession_schedule"][0]["period_index"] == 1
    assert accepted["concession_schedule"][0]["credit_cents"] == 137562
    assert accepted["monthly_concession_credit_cents"] == 137562
    assert accepted["first_period_charge_cents"] == 160488
    assert_concession_schedule_sums(accepted)


def test_applying_the_final_concession_credit_exhausts_the_committed_budget(
    api, property_manager_headers
):
    """A one-free-week upfront concession of 68781 cents fits inside a single month of gross charge,
    so its only credit posting is also its last: the concession jumps to EXHAUSTED, both committed
    ledgers fall to 0 in the same request, and the contract dimension stays ACTIVE.

    "The concession dimension of a lease evolves independently of its contract dimension."
    "Credits are posted one period at a time by the `PropertyManager` once the lease is amortizing."
    "The credit taken is the `credit_cents` of the schedule entry at that `period_index`."
    "When the posting brings `concession_remaining_cents` to 0, the concession moves `AMORTIZING → EXHAUSTED`, which is terminal, and this lease's contribution to both committed totals has reached 0."

    Design: Corner/endpoints/applying_the_final_concession_credit_exhausts_the_committed_budget
    """
    scenario = setup_amortizing_lease(
        homesite_count=1,
        total_planned_units=4,
        product_mix=dict(FOUR_DETACHED_MIX),
        asking_rent_cents=285_000,
        concession_budget_cents=1_000_000,
        facility_commitment_cents=25_000_000,
        name="Kelmsley",
        market_code="NV-RNO",
        household_overrides={"primary_applicant_name": "Kara Sloan", "email": "kara@example.com"},
        program_overrides={
            "program_code": "KS-ONEWEEK",
            "tier": "LIGHT",
            "free_weeks": 1,
            "amortization_mode": "UPFRONT_FREE_RENT",
            "eligible_product_types": ["DETACHED"],
            "max_budget_cents": 500_000,
        },
    )
    lease_id = scenario["lease"]["id"]
    community_id = scenario["community"]["id"]
    program_id = scenario["program"]["id"]

    before = read_lease(lease_id)
    assert before["total_concession_cents"] == 68781
    assert len(before["concession_schedule"]) == 1
    assert before["concession_schedule"][0]["period_index"] == 1
    assert before["concession_schedule"][0]["credit_cents"] == 68781
    assert before["monthly_concession_credit_cents"] == 68781
    assert before["first_period_charge_cents"] == 229269
    assert before["concession_status"] == "AMORTIZING"
    assert before["lease_status"] == "ACTIVE"
    assert before["credits_applied_count"] == 0
    assert read_community(community_id)["committed_concession_cents"] == 68781
    assert read_program(program_id)["committed_cents"] == 68781

    applied = validate_success(
        api.apply_concession_credit(
            lease_id, concession_credit_payload(1), property_manager_headers
        ),
        expected_status=201,
    )
    assert applied["credits_applied_count"] == 1
    assert applied["concession_applied_cents"] == 68781
    assert applied["concession_remaining_cents"] == 0
    assert applied["concession_status"] == "EXHAUSTED"
    assert applied["lease_status"] == "ACTIVE"

    community = read_community(community_id)
    program = read_program(program_id)
    assert community["committed_concession_cents"] == 0
    assert program["committed_cents"] == 0
    assert_concession_ledger_identity(community, [read_lease(lease_id)], program)
