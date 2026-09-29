"""Arithmetic probes: the constants each formula multiplies by, the tier and band edges it selects
on, the direction it rounds, and which rows it is allowed to read in the first place."""
import pytest

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    api_client,
    assert_aums,
    assert_pct,
    make_officer_headers,
)
from test_helpers import factories as f
from test_helpers.fixtures import (
    add_use_record,
    approve_nonuse,
    approve_project,
    allocate_cost_share,
    create_allotment,
    create_aoi,
    create_base_property,
    create_closure_order,
    create_pasture,
    create_permit,
    create_permittee,
    create_project,
    finalized_assessment,
    get_allotment,
    get_aoi,
    get_base_property,
    get_bill,
    get_pasture,
    get_permit,
    get_permittee,
    get_project,
    issue_aoi,
    issue_permit,
    lift_closure_order,
    list_bills,
    pay_bill,
    void_bill,
)


def _live_bill(aoi_id, bill_type):
    """The one non-voided bill of that type on the instruction."""
    bills = [b for b in list_bills(aoi_id=aoi_id, bill_type=bill_type)
             if b["bill_status"] != "VOIDED"]
    assert len(bills) == 1, "expected exactly one live %s bill, got %d" % (bill_type, len(bills))
    return bills[0]


def test_planned_aums_multiplies_by_the_livestock_factor_over_half_open_days():
    """[2026-05-01, 2026-05-31) is 30 whole days, so the divide-by-30 cancels and the animal-unit
    equivalent is left standing alone: 500 head of sheep carry 100.00 AUMs at 0.2, and 40 head of
    horses carry 50.00 at 1.25 — never the raw head counts of 500 and 40. Each leg rolls up into its
    own instruction total, and neither reports any actual figure yet. Both instructions are still
    DRAFT, so the refreshed pasture roll-up comes back at 0.00 on both pastures — the roll-up counts
    only issued-or-later instructions of the current grazing year.

    PRD 3.1: "Its `scheduled_aums` is the sum of `planned_aums` over every use record naming that
    pasture whose owning operating instruction has a `grazing_year` equal to the allotment's
    `current_grazing_year` and an `aoi_status` of `ISSUED`, `USE_REPORTED`, `BILLED` or `CLOSED`;
    the figure is carried to 2 decimal places and starts at 0."
    PRD 3.1: "Records belonging to draft or voided instructions, and records for any other grazing
    year, contribute nothing."
    PRD 3.4: "Take the number of whole days in the half-open window — that is, the count of days
    from the entry date up to but excluding the exit date."
    PRD 3.4: "Multiply the head count by the animal-unit equivalent of the livestock kind, which is
    1.0 for `CATTLE`, 0.2 for `SHEEP` and 1.25 for `HORSES`."
    PRD 3.4: "Multiply that by the day count, then divide by 30, the number of grazing days that
    make up one animal unit month."
    PRD 3.4: "Once the leg is stored, the instruction's `planned_aums_total` is recomputed as the sum
    of `planned_aums` over **all** of its use records regardless of `record_status`, its
    `distinct_pasture_count` as the number of distinct `pasture_id` values across all of those
    records, and the named pasture's `scheduled_aums` roll-up is refreshed."
    PRD 3.4: "the leg's `livestock_kind` must equal the `livestock_kind` of the instruction's permit
    — a mismatch is a request-shape failure reported as `ERR_VALIDATION`."

    Design: Corner/calculations/corner_planned_aums_uses_livestock_factor_and_half_open_days
    """
    allotment = create_allotment(admin_unit_code="QB-129", total_permitted_aums=900,
                                 acres=26000, required_pasture_rotation_count=1)
    sheep_pasture = create_pasture(allotment["id"], name="Sheep Pasture",
                                   pasture_aum_capacity=400, sequence_order=1)
    horse_pasture = create_pasture(allotment["id"], name="Horse Pasture",
                                   pasture_aum_capacity=400, sequence_order=2)
    permittee = create_permittee(name="Livestock Factor Ranch",
                                 contact_email="factor@example.com")
    base_property = create_base_property(permittee["id"], base_property_type="LAND",
                                         carrying_capacity_aums=300)
    # The leg's livestock_kind must match its permit's, so each kind needs its own permit.
    sheep_permit = issue_permit(create_permit(
        allotment["id"], permittee["id"], base_property["id"], requested_aums=300,
        livestock_kind="SHEEP", term_start_date="2026-01-01",
        term_end_date="2030-12-31")["id"])
    horse_permit = issue_permit(create_permit(
        allotment["id"], permittee["id"], base_property["id"], requested_aums=300,
        livestock_kind="HORSES", term_start_date="2026-01-01",
        term_end_date="2030-12-31")["id"])
    sheep_aoi = create_aoi(sheep_permit["id"], grazing_year=2026, authorized_aums=200,
                           season_start_date="2026-01-01", season_end_date="2026-12-31")
    horse_aoi = create_aoi(horse_permit["id"], grazing_year=2026, authorized_aums=200,
                           season_start_date="2026-01-01", season_end_date="2026-12-31")

    sheep_leg = add_use_record(sheep_aoi["id"], sheep_pasture["id"], planned_head_count=500,
                               livestock_kind="SHEEP", planned_entry_date="2026-05-01",
                               planned_exit_date="2026-05-31")
    horse_leg = add_use_record(horse_aoi["id"], horse_pasture["id"], planned_head_count=40,
                               livestock_kind="HORSES", planned_entry_date="2026-05-01",
                               planned_exit_date="2026-05-31")

    assert_aums(sheep_leg["planned_aums"], 100.00)  # 500 x 0.2 x 30 / 30
    assert_aums(horse_leg["planned_aums"], 50.00)  # 40 x 1.25 x 30 / 30

    sheep_year = get_aoi(sheep_aoi["id"])
    assert_aums(sheep_year["planned_aums_total"], 100.00)
    assert_aums(sheep_year["actual_aums_total"], 0)
    assert sheep_year["distinct_pasture_count"] == 1
    horse_year = get_aoi(horse_aoi["id"])
    assert_aums(horse_year["planned_aums_total"], 50.00)
    assert_aums(horse_year["actual_aums_total"], 0)
    assert horse_year["distinct_pasture_count"] == 1

    # Both instructions are DRAFT, so their records contribute nothing (PRD 3.1).
    assert_aums(get_pasture(sheep_pasture["id"])["scheduled_aums"], 0.00)
    assert_aums(get_pasture(horse_pasture["id"])["scheduled_aums"], 0.00)


def test_the_meeting_band_opens_at_exactly_seventy_and_one_upland_point_closes_it():
    """Scores of 70/70/70 weight to exactly 70.00, which is inside the MEETING band because the edge
    is inclusive; dropping the upland score by a single point gives 69.60 and the same allotment
    would instead be MEETING_WITH_PROBLEMS. Neither assessment recommends any reduction, because no
    standard is unmet.

    PRD 3.7: "The `determination` follows by band: `MEETING` when `composite_score` is at least 70,
    `MEETING_WITH_PROBLEMS` when `composite_score` is at least 50 but less than 70, and
    `NOT_MEETING` in every remaining case, that is when it is below 50."
    PRD 3.7: "Multiply `upland_score` by 0.40, `riparian_score` by 0.35 and `water_quality_score` by
    0.25, add the three products, and round the sum half-up to 2 decimal places; the result is
    `composite_score`."
    PRD 3.7: "Under `INDICATOR_ASSESSMENT`, take 0.10 for each standard code listed in
    `standards_not_met`, add a further 0.10 when `causal_factor_is_livestock` is true, cap the result
    at 0.50, and round half-up to 4 decimal places; `observed_utilization_pct` is ignored entirely."
    PRD 3.7: "A `CONCUR` outcome moves `FIELD_REVIEW → FINALIZED`, computes `composite_score` and
    `determination`, computes `recommended_reduction_pct`, writes the resulting `determination` onto
    the allotment's `health_determination`, and bumps the allotment's `version`."

    Design: Corner/calculations/corner_composite_score_boundary_at_seventy
    """
    high = create_allotment(admin_unit_code="QB-130", total_permitted_aums=400, acres=12000,
                            required_pasture_rotation_count=1)
    low = create_allotment(admin_unit_code="QB-131", total_permitted_aums=420, acres=12500,
                           required_pasture_rotation_count=1)

    on_the_edge = finalized_assessment(
        high["id"], assessment_year=2026, upland_score=70, riparian_score=70,
        water_quality_score=70, standards_not_met=[], causal_factor_is_livestock=False)
    below_the_edge = finalized_assessment(
        low["id"], assessment_year=2026, upland_score=69, riparian_score=70,
        water_quality_score=70, standards_not_met=[], causal_factor_is_livestock=False)

    assert on_the_edge["composite_score"] == pytest.approx(70.00, abs=0.005)
    assert on_the_edge["determination"] == "MEETING", "the band edge is inclusive"
    # 69 x 0.40 + 70 x 0.35 + 70 x 0.25 = 27.6 + 24.5 + 17.5
    assert below_the_edge["composite_score"] == pytest.approx(69.60, abs=0.005)
    assert below_the_edge["determination"] == "MEETING_WITH_PROBLEMS"

    assert_pct(on_the_edge["recommended_reduction_pct"], 0.0)
    assert_pct(below_the_edge["recommended_reduction_pct"], 0.0)

    assert get_allotment(high["id"])["health_determination"] == "MEETING"
    assert get_allotment(low["id"])["health_determination"] == "MEETING_WITH_PROBLEMS"


def _fee_edge_permit(allotment_id, requested_aums, permittee_name, permittee_email):
    permittee = create_permittee(name=permittee_name, contact_email=permittee_email)
    base_property = create_base_property(permittee["id"], base_property_type="LAND",
                                         carrying_capacity_aums=300)
    permit = issue_permit(create_permit(
        allotment_id, permittee["id"], base_property["id"], requested_aums=requested_aums,
        livestock_kind="CATTLE", term_start_date="2026-01-01",
        term_end_date="2030-12-31")["id"])
    return permittee, permit


def test_one_extra_billed_aum_at_the_fifty_thousand_cent_edge_costs_two_thousand_six_hundred_and_seventy_two():
    """172 cents per AUM steps straight over the tier edge without landing on it: 290 AUMs give a
    base of 49,880 with no administrative fee, while 291 give 50,052 and pick up the 2,500-cent tier,
    so the marginal AUM costs 2,672 cents rather than 172. Both bills carry the same 172 rate and the
    same clock-derived due date, and each debt lands on its own permittee.

    PRD 3.6: "Step two computes `base_amount_cents` as `billed_aums` multiplied by the grazing fee
    rate of 172 cents per AUM, rounded half-up to a whole cent; that same 172 is recorded on the bill
    as its `fee_rate_cents_per_aum`."
    PRD 3.6: "Step three selects the tiered administrative fee **from `base_amount_cents`, never
    from the total**: `admin_fee_cents` is 0 when `base_amount_cents` is below 50,000 cents, 2,500
    cents when `base_amount_cents` is at least 50,000 and below 200,000 cents, and 6,000 cents when
    `base_amount_cents` is 200,000 cents or more."
    PRD 3.6: "Step four sets `total_amount_cents` to `base_amount_cents` plus `admin_fee_cents`;
    `penalty_amount_cents` is 0 on every use bill."
    PRD 3.6: "The **preliminary** variant, used when an operating instruction is issued, sets
    `billed_aums` to the instruction's `authorized_aums` less its `nonuse_aums` — an integer, so step
    two is exact — and applies no minimum-charge floor."
    PRD 3.6: "Every use bill is raised in `bill_status` `ISSUED` with `amount_paid_cents` of 0 and a
    `due_date` of the logical-clock date at issuance plus 30 days."

    Design: Corner/calculations/corner_admin_fee_tier_one_to_two_boundary
    """
    allotment = create_allotment(admin_unit_code="QB-132", total_permitted_aums=1000,
                                 acres=30000, required_pasture_rotation_count=1)
    first_pasture = create_pasture(allotment["id"], name="Fee Edge Pasture One",
                                   pasture_aum_capacity=400, sequence_order=1)
    second_pasture = create_pasture(allotment["id"], name="Fee Edge Pasture Two",
                                    pasture_aum_capacity=400, sequence_order=2)
    below_holder, below_permit = _fee_edge_permit(allotment["id"], 290, "Fee Edge Ranch Below",
                                                  "feebelow@example.com")
    above_holder, above_permit = _fee_edge_permit(allotment["id"], 291, "Fee Edge Ranch Above",
                                                  "feeabove@example.com")

    below_aoi = create_aoi(below_permit["id"], grazing_year=2026, authorized_aums=290,
                           season_start_date="2026-01-01", season_end_date="2026-12-31")
    add_use_record(below_aoi["id"], first_pasture["id"], planned_head_count=60,
                   livestock_kind="CATTLE", planned_entry_date="2026-05-01",
                   planned_exit_date="2026-06-01")
    above_aoi = create_aoi(above_permit["id"], grazing_year=2026, authorized_aums=291,
                           season_start_date="2026-01-01", season_end_date="2026-12-31")
    add_use_record(above_aoi["id"], second_pasture["id"], planned_head_count=60,
                   livestock_kind="CATTLE", planned_entry_date="2026-05-01",
                   planned_exit_date="2026-06-01")

    assert issue_aoi(below_aoi["id"])["aoi_status"] == "ISSUED"
    assert issue_aoi(above_aoi["id"])["aoi_status"] == "ISSUED"

    below_bill = _live_bill(below_aoi["id"], "PRELIMINARY_USE")
    assert below_bill["billed_aums"] == 290
    assert below_bill["base_amount_cents"] == 49880  # 290 x 172, one cent short of the tier
    assert below_bill["admin_fee_cents"] == 0
    assert below_bill["total_amount_cents"] == 49880

    above_bill = _live_bill(above_aoi["id"], "PRELIMINARY_USE")
    assert above_bill["billed_aums"] == 291
    assert above_bill["base_amount_cents"] == 50052  # 291 x 172, just over it
    assert above_bill["admin_fee_cents"] == 2500
    assert above_bill["total_amount_cents"] == 52552

    for bill in (below_bill, above_bill):
        assert bill["fee_rate_cents_per_aum"] == 172
        assert bill["penalty_amount_cents"] == 0
        assert bill["bill_status"] == "ISSUED"
        assert bill["due_date"] == "2026-08-31"  # clock 2026-08-01 plus 30 days

    assert get_permittee(below_holder["id"])["outstanding_balance_cents"] == 49880
    assert get_permittee(above_holder["id"])["outstanding_balance_cents"] == 52552

    ledger = get_allotment(allotment["id"])
    assert ledger["allocated_aums"] == 581  # 290 + 291
    assert ledger["open_aums"] == 419


def test_a_pending_permit_is_outside_the_cost_share_pool_however_large_its_preference():
    """The pool filters on permit_status alone, so the 400-AUM application that was never issued
    contributes nothing: the whole 50,000-cent permittee share lands on the single 300-AUM ISSUED
    permit as one bill, rather than being split 21,428 / 28,572 across the two.

    PRD 3.12: "The eligible pool is every grazing permit on the project's allotment whose
    `permit_status` is exactly `ISSUED`; permits in `permit_status` `DRAFT`, `PENDING_REVIEW`,
    `SUSPENDED`, `CANCELLED` or `EXPIRED` are excluded, and a permit's `account_status` is irrelevant
    to eligibility, so a delinquent but issued permit still takes its share."
    PRD 3.12: "The pool's total is the sum of `permitted_aums` over the eligible permits."
    PRD 3.12: "Pass one computes each permit's provisional share as `permittee_share_cents`
    multiplied by that permit's `permitted_aums` divided by the pool total, **floored** to a whole
    cent."
    PRD 3.12: "Pass three raises one bill of `bill_type` `PROJECT_COST_SHARE` per eligible permit
    whose final share is greater than 0, charged to that permit's `permittee_id`, with `project_id`
    naming the project, `aoi_id` and `trespass_incident_id` null, `billed_aums` of 0 and
    `fee_rate_cents_per_aum` of 0 because a cost share is not forage, `base_amount_cents` and
    `total_amount_cents` both equal to the share, `admin_fee_cents` and `penalty_amount_cents` both
    0, a `due_date` of the clock date plus 30 days, and `bill_status` `ISSUED`."
    PRD 3.12: "On success `project_status` becomes `APPROVED` and `permittee_share_cents` is set to
    `total_cost_cents` multiplied by `permittee_share_pct`, rounded half-up to a whole cent."

    Design: Corner/calculations/corner_cost_share_pool_excludes_non_issued_permits
    """
    allotment = create_allotment(admin_unit_code="QB-133", total_permitted_aums=900, acres=24000,
                                 required_pasture_rotation_count=1)
    issued_holder = create_permittee(name="Pool Ranch Issued",
                                     contact_email="poolissued@example.com")
    issued_property = create_base_property(issued_holder["id"], base_property_type="LAND",
                                           carrying_capacity_aums=300)
    issued_permit = issue_permit(create_permit(
        allotment["id"], issued_holder["id"], issued_property["id"], requested_aums=300)["id"])
    assert issued_permit["permit_status"] == "ISSUED"

    pending_holder = create_permittee(name="Pool Ranch Pending",
                                      contact_email="poolpending@example.com")
    pending_property = create_base_property(pending_holder["id"], base_property_type="LAND",
                                            carrying_capacity_aums=400)
    pending_permit = create_permit(allotment["id"], pending_holder["id"], pending_property["id"],
                                   requested_aums=400)
    assert pending_permit["permit_status"] == "PENDING_REVIEW"

    project = approve_project(create_project(
        allotment["id"], project_type="FENCE", total_cost_cents=100000, agency_share_pct=0.5,
        permittee_share_pct=0.5, maintenance_responsibility="SHARED")["id"])
    assert project["permittee_share_cents"] == 50000  # 100000 x 0.5, fixed at approval

    allocated = allocate_cost_share(project["id"])
    assert allocated["project_status"] == "COST_ALLOCATED"
    assert allocated["permittee_share_cents"] == 50000
    assert allocated["allocated_share_cents"] == 50000

    bills = list_bills(project_id=project["id"])
    assert len(bills) == 1, "the pending permit takes no share, so it receives no bill"
    bill = bills[0]
    assert bill["bill_type"] == "PROJECT_COST_SHARE"
    assert bill["permittee_id"] == issued_holder["id"]
    assert bill["total_amount_cents"] == 50000
    assert bill["base_amount_cents"] == 50000
    assert bill["admin_fee_cents"] == 0
    assert bill["penalty_amount_cents"] == 0
    assert bill["billed_aums"] == 0
    assert bill["fee_rate_cents_per_aum"] == 0
    assert bill["aoi_id"] is None
    assert bill["trespass_incident_id"] is None
    assert bill["bill_status"] == "ISSUED"
    assert bill["due_date"] == "2026-08-31"

    assert get_permittee(issued_holder["id"])["outstanding_balance_cents"] == 50000
    assert get_permittee(pending_holder["id"])["outstanding_balance_cents"] == 0

    excluded = get_permit(pending_permit["id"])
    assert excluded["permit_status"] == "PENDING_REVIEW"
    assert excluded["permitted_aums"] == 400, "excluded on status, not for lacking preference"


def test_an_allotment_with_no_issued_permit_allocates_zero_and_calls_it_success():
    """There is no error code for an empty pool: the allocation completes, the project reaches
    COST_ALLOCATED and allocated_share_cents is 0 even though the pot itself is a full 100,000
    cents, and not one bill is raised against anybody.

    PRD 3.12: "An **empty pool is a success, not a failure**. When the allotment has no permit in
    `permit_status` `ISSUED`, or when the eligible permits' `permitted_aums` sum to 0, the allocation
    still completes: nothing is distributed, `allocated_share_cents` is set to 0, `project_status`
    becomes `COST_ALLOCATED`, and no bill of any kind is raised."
    PRD 3.12: "There is deliberately no error for this case, and returning one is wrong."
    PRD 2.6: "The project's `total_cost_cents` must be at least 1 and the project must be in
    `project_status` `APPROVED`. An allotment with no `ISSUED` permits is expressly **not** an error
    here — see §3.12."

    Design: Corner/calculations/corner_cost_share_empty_pool_allocates_zero
    """
    allotment = create_allotment(admin_unit_code="QB-134", total_permitted_aums=450, acres=13000,
                                 required_pasture_rotation_count=1)
    project = approve_project(create_project(
        allotment["id"], project_type="SEEDING", total_cost_cents=250000, agency_share_pct=0.6,
        permittee_share_pct=0.4, maintenance_responsibility="AGENCY")["id"])
    assert project["permittee_share_cents"] == 100000  # 250000 x 0.4
    assert project["allocated_share_cents"] == 0

    allocated = allocate_cost_share(project["id"])
    assert allocated["project_status"] == "COST_ALLOCATED"
    assert allocated["permittee_share_cents"] == 100000
    assert allocated["allocated_share_cents"] == 0, "nothing is distributed to nobody"
    assert list_bills(project_id=project["id"]) == []
    assert get_project(project["id"])["allocated_share_cents"] == 0


def test_the_livestock_qualification_factor_floors_rather_than_rounds():
    """401 AUMs of controlled livestock qualify 300, because 300.75 is floored and not rounded up to
    301; the identical 401 recorded as deeded land qualifies all 401 at the factor of exactly 1.0.
    Neither row's stored carrying capacity is touched by the arithmetic.

    PRD 3.2: "Deeded land qualifies at full strength: the qualification factor for a `LAND` property
    is 1.0."
    PRD 3.2: "Controlled livestock qualifies at three-quarters strength: the factor for a
    `LIVESTOCK` property is 0.75."
    PRD 3.2: "The property's `qualified_aums` is its `carrying_capacity_aums` multiplied by that
    factor, floored to a whole AUM."
    PRD 3.2: "A `LAND` property producing 400 AUMs therefore qualifies 400; a `LIVESTOCK` property
    producing the same 400 qualifies 300, and one producing 401 qualifies 300 as well, because the
    product 300.75 is floored rather than rounded."

    Design: Corner/calculations/corner_livestock_base_property_qualification_floors_the_product
    """
    permittee = create_permittee(name="Floor Probe Ranch", contact_email="floorprobe@example.com")

    livestock = create_base_property(
        permittee["id"], base_property_type="LIVESTOCK", carrying_capacity_aums=401,
        legal_description="401 head controlled under a private lease near Battle Mountain",
        controlled_since_date="2015-02-02")
    land = create_base_property(
        permittee["id"], base_property_type="LAND", carrying_capacity_aums=401,
        legal_description="T40N R61E Sec 21 all", controlled_since_date="2015-02-03")

    assert livestock["qualified_aums"] == 300  # floor(401 x 0.75) = floor(300.75)
    assert land["qualified_aums"] == 401  # 401 x 1.0

    assert get_base_property(livestock["id"])["carrying_capacity_aums"] == 401
    assert get_base_property(land["id"])["carrying_capacity_aums"] == 401


def _ledger_window_permit(allotment_id, name, email, capacity, requested_aums):
    permittee = create_permittee(name=name, contact_email=email)
    base_property = create_base_property(permittee["id"], base_property_type="LAND",
                                         carrying_capacity_aums=capacity)
    permit = issue_permit(create_permit(allotment_id, permittee["id"], base_property["id"],
                                       requested_aums=requested_aums)["id"])
    return permittee, permit


def test_allocated_aums_ignores_next_years_issued_instruction_and_this_years_draft():
    """Two instructions sit alongside the one that counts and neither reaches the ledger: an ISSUED
    2027 instruction of 120 AUMs is for the wrong year and a DRAFT 2026 instruction of 150 AUMs is in
    the wrong status, so allocated_aums stays at exactly 100 rather than 220, 250 or 370. The pasture
    roll-up is filtered the same way and reports only the 2026 leg's 62.00 AUMs.

    PRD 2.9: "The second line is **allocation**: `allocated_aums` is the sum, over every annual
    operating instruction whose permit belongs to this allotment, whose `grazing_year` equals the
    allotment's `current_grazing_year`, and whose `aoi_status` is one of `ISSUED`, `USE_REPORTED`,
    `BILLED` or `CLOSED`, of that instruction's `authorized_aums` less its `nonuse_aums`."
    PRD 2.9: "Instructions in `DRAFT` or `VOIDED` contribute nothing, and instructions for any other
    grazing year contribute nothing; the window is exactly the allotment's `current_grazing_year`,
    inclusive of both ends of that calendar year."
    PRD 3.1: "Its `scheduled_aums` is the sum of `planned_aums` over every use record naming that
    pasture whose owning operating instruction has a `grazing_year` equal to the allotment's
    `current_grazing_year` and an `aoi_status` of `ISSUED`, `USE_REPORTED`, `BILLED` or `CLOSED`; the
    figure is carried to 2 decimal places and starts at 0."
    PRD 3.1: "Records belonging to draft or voided instructions, and records for any other grazing
    year, contribute nothing."
    PRD 2.9: "The AUM invariant: an allotment's `open_aums` plus its `allocated_aums` always equals
    its `effective_capacity_aums`."

    Design: Corner/calculations/corner_allocated_aums_counts_only_current_year_issued_aois
    """
    allotment = create_allotment(admin_unit_code="QB-135", total_permitted_aums=1000, acres=31000,
                                 required_pasture_rotation_count=1)
    pasture = create_pasture(allotment["id"], name="Ledger Window Pasture",
                             pasture_aum_capacity=500, sequence_order=1)
    holder_a, permit_a = _ledger_window_permit(allotment["id"], "Ledger Window Ranch A",
                                               "ledgera@example.com", 500, 500)
    holder_b, permit_b = _ledger_window_permit(allotment["id"], "Ledger Window Ranch B",
                                               "ledgerb@example.com", 200, 150)

    counted = create_aoi(permit_a["id"], grazing_year=2026, authorized_aums=100,
                         season_start_date="2026-01-01", season_end_date="2026-12-31")
    add_use_record(counted["id"], pasture["id"], planned_head_count=60, livestock_kind="CATTLE",
                   planned_entry_date="2026-05-01", planned_exit_date="2026-06-01")
    issue_aoi(counted["id"])
    # Priority 28 forbids drafting the 2027 instruction while this bill is outstanding.
    preliminary = _live_bill(counted["id"], "PRELIMINARY_USE")
    assert preliminary["total_amount_cents"] == 17200
    assert pay_bill(preliminary["id"], 17200)["bill_status"] == "PAID"
    assert get_permittee(holder_a["id"])["outstanding_balance_cents"] == 0

    wrong_status = create_aoi(permit_b["id"], grazing_year=2026, authorized_aums=150,
                              season_start_date="2026-01-01", season_end_date="2026-12-31")
    assert wrong_status["aoi_status"] == "DRAFT"

    wrong_year = create_aoi(permit_a["id"], grazing_year=2027, authorized_aums=120,
                            season_start_date="2027-01-01", season_end_date="2027-12-31")
    add_use_record(wrong_year["id"], pasture["id"], planned_head_count=60, livestock_kind="CATTLE",
                   planned_entry_date="2027-05-01", planned_exit_date="2027-06-01")
    assert issue_aoi(wrong_year["id"])["aoi_status"] == "ISSUED"

    ledger = get_allotment(allotment["id"])
    assert ledger["current_grazing_year"] == 2026
    assert ledger["allocated_aums"] == 100, "only the ISSUED 2026 instruction is in the window"
    assert ledger["effective_capacity_aums"] == 1000
    assert ledger["open_aums"] == 900

    assert_aums(get_pasture(pasture["id"])["scheduled_aums"], 62.00)  # the 2027 leg is outside it

    assert get_bill(preliminary["id"])["bill_status"] == "PAID"
    assert get_aoi(counted["id"])["aoi_status"] == "ISSUED", "payment does not close the year"
    assert get_permittee(holder_b["id"])["outstanding_balance_cents"] == 0


def test_the_balance_counts_the_still_issued_bill_and_neither_the_paid_nor_the_voided_one():
    """Three identical 17,200-cent bills stand against one permittee and only one of them is still
    ISSUED after the payment and the void, so the balance is exactly 17,200 — not the 51,600 of
    counting everything, and not the 34,400 of forgetting only one exclusion. The permittee stays
    IN_GOOD_STANDING because nothing has gone overdue.

    PRD 2.9: "A permittee's `outstanding_balance_cents` always equals the sum, over that permittee's
    bills whose `bill_status` is `ISSUED` or `DELINQUENT`, of each bill's `total_amount_cents` less
    its `amount_paid_cents`; bills in `PAID` or `VOIDED` contribute nothing, and an
    `ADJUSTMENT_CREDIT` bill contributes its negative total and so reduces the balance."
    PRD 2.9: "A permittee's `permittee_status` is derived from the same aggregate: it is
    `DEBT_FLAGGED` exactly when `outstanding_balance_cents` is greater than zero **and** at least one
    of the contributing bills is in `bill_status` `DELINQUENT`, and `IN_GOOD_STANDING` in every other
    case — so an unpaid bill that is not yet overdue leaves the permittee `IN_GOOD_STANDING`."
    PRD 3.6: "A successful payment increases `amount_paid_cents` by `amount_cents`, and when the
    accumulated `amount_paid_cents` reaches or exceeds `total_amount_cents` the bill moves to
    `bill_status` `PAID`."

    Design: Corner/calculations/corner_outstanding_balance_excludes_paid_and_voided_bills
    """
    allotment = create_allotment(admin_unit_code="QB-136", total_permitted_aums=1000, acres=32000,
                                 required_pasture_rotation_count=1)
    pasture = create_pasture(allotment["id"], name="Balance Filter Pasture",
                             pasture_aum_capacity=500, sequence_order=1)
    permittee = create_permittee(name="Balance Filter Ranch",
                                 contact_email="balancefilter@example.com")
    base_property = create_base_property(permittee["id"], base_property_type="LAND",
                                         carrying_capacity_aums=300)
    # Every permit is issued while the account is clean, and every instruction is drafted before any
    # of them is issued, because the first issuance raises a bill and priority 28 then forbids
    # drafting another instruction for the same permittee.
    permits = [issue_permit(create_permit(allotment["id"], permittee["id"], base_property["id"],
                                          requested_aums=100)["id"]) for _ in range(3)]
    aois = []
    for permit in permits:
        aoi = create_aoi(permit["id"], grazing_year=2026, authorized_aums=100,
                         season_start_date="2026-01-01", season_end_date="2026-12-31")
        add_use_record(aoi["id"], pasture["id"], planned_head_count=60, livestock_kind="CATTLE",
                       planned_entry_date="2026-05-01", planned_exit_date="2026-06-01")
        aois.append(aoi)
    bills = []
    for aoi in aois:
        issue_aoi(aoi["id"])
        bill = _live_bill(aoi["id"], "PRELIMINARY_USE")
        assert bill["total_amount_cents"] == 17200
        bills.append(bill)

    assert get_permittee(permittee["id"])["outstanding_balance_cents"] == 51600

    assert pay_bill(bills[0]["id"], 17200)["bill_status"] == "PAID"
    void_bill(bills[1]["id"],
              void_reason="Raised against the wrong allotment file; superseded administratively.")

    paid = get_bill(bills[0]["id"])
    assert paid["bill_status"] == "PAID"
    assert paid["amount_paid_cents"] == 17200
    voided = get_bill(bills[1]["id"])
    assert voided["bill_status"] == "VOIDED"
    assert voided["amount_paid_cents"] == 0
    assert get_bill(bills[2]["id"])["bill_status"] == "ISSUED"

    holder = get_permittee(permittee["id"])
    assert holder["outstanding_balance_cents"] == 17200, "only the still-ISSUED bill contributes"
    assert holder["permittee_status"] == "IN_GOOD_STANDING"

    for permit in permits:
        current = get_permit(permit["id"])
        assert current["account_status"] == "CURRENT"
        assert current["permit_status"] == "ISSUED"


def test_the_drought_year_breaks_the_run_instead_of_joining_its_neighbours():
    """Full non-use runs three years deep — 2024 personal convenience, 2025 drought, 2026 personal
    convenience — and the counter reads 1: the agency-directed 2025 year neither counts nor bridges,
    so the only run ending at the most recent qualifying year is 2026 alone, never 3 and never 2.
    One is below the ceiling, so renewal still succeeds.

    PRD 3.5: "A year **counts** toward the run when its instruction has a `nonuse_aums` greater than
    0 **and** a `nonuse_reason` of either `RESOURCE_CONSERVATION` or `PERSONAL_CONVENIENCE`."
    PRD 3.5: "A year **breaks** the run when its instruction has `nonuse_aums` of 0, when its
    `nonuse_reason` is `DROUGHT` or `WILDFIRE` — agency-directed non-use is never held against the
    permittee — or when that grazing year has no qualifying instruction at all, a gap being as good
    as a break."
    PRD 3.5: "The permit's `consecutive_nonuse_years` is the length of the longest counting run that
    **ends at the most recent qualifying year**."
    PRD 3.5: "Once it reaches 3, the preference has lapsed and renewal is barred with
    `ERR_NONUSE_LIMIT_EXCEEDED`; at 2 a renewal still succeeds."
    PRD 3.5: "The requested `nonuse_aums` must be at least 1 and no greater than the instruction's
    current `authorized_aums`, and the two agency-directed reasons are conditional: `DROUGHT` is
    accepted only while a closure order of `order_type` `DROUGHT_REDUCTION` is `ACTIVE` on the
    allotment, and `WILDFIRE` only while an order of `order_type` `WILDFIRE_CLOSURE` is `ACTIVE` on
    it."
    PRD 3.5: "The instruction's `billable_aums` becomes its `authorized_aums` less the approved
    `nonuse_aums`, the allotment's ledger is recomputed so that the released AUMs reappear in
    `open_aums`, any still-unpaid preliminary bill for that instruction is superseded by a revised
    bill at the lower figure, the permit's `consecutive_nonuse_years` is recomputed, and the
    permittee's `outstanding_balance_cents` is brought back into line."

    Design: Corner/calculations/corner_drought_nonuse_breaks_the_consecutive_run
    """
    allotment = create_allotment(admin_unit_code="QB-137", total_permitted_aums=1000, acres=28000,
                                 required_pasture_rotation_count=1)
    pasture = create_pasture(allotment["id"], name="Nonuse Reason Pasture",
                             pasture_aum_capacity=400, sequence_order=1)
    permittee = create_permittee(name="Nonuse Reason Ranch",
                                 contact_email="nonusereason@example.com")
    base_property = create_base_property(permittee["id"], base_property_type="LAND",
                                         carrying_capacity_aums=300)
    permit = issue_permit(create_permit(
        allotment["id"], permittee["id"], base_property["id"], requested_aums=100,
        term_start_date="2023-01-01", term_end_date="2030-12-31")["id"])

    def full_year_of_nonuse(grazing_year, nonuse_reason):
        aoi = create_aoi(permit["id"], grazing_year=grazing_year, authorized_aums=100,
                         season_start_date="%d-01-01" % grazing_year,
                         season_end_date="%d-12-31" % grazing_year)
        add_use_record(aoi["id"], pasture["id"], planned_head_count=60, livestock_kind="CATTLE",
                       planned_entry_date="%d-05-01" % grazing_year,
                       planned_exit_date="%d-06-01" % grazing_year)
        issue_aoi(aoi["id"])
        approved = approve_nonuse(aoi["id"], 100, nonuse_reason=nonuse_reason)
        assert approved["nonuse_aums"] == 100
        assert approved["nonuse_reason"] == nonuse_reason
        # Non-use at the full authorization re-prices the year to nothing, which clears the account
        # and so lets the next year's instruction be drafted at all.
        assert get_permittee(permittee["id"])["outstanding_balance_cents"] == 0
        return approved

    counting_2024 = full_year_of_nonuse(2024, "PERSONAL_CONVENIENCE")
    assert counting_2024["billable_aums"] == 0

    # DROUGHT non-use is only accepted while a drought reduction order stands, so the order is
    # raised for the 2025 approval and lifted again before the 2026 year is drafted.
    order = create_closure_order(
        allotment["id"], order_type="DROUGHT_REDUCTION", reduction_pct=0.25,
        effective_start_date="2026-08-01", effective_end_date="2026-08-31",
        justification="Reservoir storage and forage transects both below the drought trigger.")
    assert order["order_status"] == "ACTIVE"
    breaking_2025 = full_year_of_nonuse(2025, "DROUGHT")
    assert breaking_2025["billable_aums"] == 0
    assert lift_closure_order(order["id"])["order_status"] == "LIFTED"
    restored = get_allotment(allotment["id"])
    assert restored["allotment_status"] == "OPEN"
    assert restored["effective_capacity_aums"] == 1000

    counting_2026 = full_year_of_nonuse(2026, "PERSONAL_CONVENIENCE")
    assert counting_2026["nonuse_aums"] == 100
    assert counting_2026["billable_aums"] == 0

    assert get_permit(permit["id"])["consecutive_nonuse_years"] == 1, "2025 breaks the run"

    ledger = get_allotment(allotment["id"])
    assert ledger["allocated_aums"] == 0, "the 2026 year now commits nothing"
    assert ledger["open_aums"] == 1000

    # Control: at 1 the ceiling of 3 is nowhere near, so preference has not lapsed.
    successor = get_success_data(api_client.renew_permit(
        permit["id"], f.renew_payload(base_property["id"], requested_aums=100,
                                      term_start_date="2031-01-01",
                                      term_end_date="2035-12-31"),
        make_officer_headers()), 201)
    assert successor["permit_status"] == "ISSUED"
    assert successor["predecessor_permit_id"] == permit["id"]
    assert successor["consecutive_nonuse_years"] == 1
    assert get_permit(permit["id"])["permit_status"] == "EXPIRED"
