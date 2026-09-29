"""Boundaries measured to the last unit: an integer run length, a 2-decimal AUM floor and
a single remainder cent."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import ApiErrorId, api_client, assert_aums, make_officer_headers
from test_helpers import factories as f
from test_helpers.fixtures import (
    accept_use_report,
    add_use_record,
    allocate_cost_share,
    allotment_with_pasture,
    approve_nonuse,
    approve_project,
    create_aoi,
    create_permit,
    create_project,
    get_allotment,
    get_bill,
    get_permit,
    get_permittee,
    get_project,
    get_use_record,
    issue_aoi,
    issue_permit,
    issued_aoi_setup,
    list_bills,
    permittee_with_base_property,
    report_actual_use,
)


def _successors(permit_id):
    """Every permit born of the named permit, found through the documented filter."""
    items, _meta = validate_paginated(api_client.list_permits(
        make_officer_headers(), {"predecessor_permit_id": permit_id, "limit": 100}))
    return items


def _live_bill_total(aoi_id):
    """The cents an instruction still charges: its non-voided bills, summed."""
    return sum(b["total_amount_cents"] for b in list_bills(aoi_id=aoi_id)
               if b["bill_status"] != "VOIDED")


def _nonuse_run(allotment_id, pasture_id, years, entry_md="04-01", exit_md="05-02"):
    """An ISSUED 150-AUM permit whose instruction for each named year is issued and then
    wholly elected into PERSONAL_CONVENIENCE non-use, so the run counts every year and the
    permittee never carries a balance."""
    holder = permittee_with_base_property(carrying_capacity_aums=200)
    permit = issue_permit(create_permit(
        allotment_id, holder["permittee"]["id"], holder["base_property"]["id"],
        requested_aums=150)["id"])
    aoi_ids = []
    for year in years:
        aoi = create_aoi(permit["id"], grazing_year=year, authorized_aums=150,
                         season_start_date="%d-01-01" % year,
                         season_end_date="%d-12-31" % year)
        add_use_record(aoi["id"], pasture_id, planned_head_count=50, livestock_kind="CATTLE",
                       planned_entry_date="%d-%s" % (year, entry_md),
                       planned_exit_date="%d-%s" % (year, exit_md))
        issue_aoi(aoi["id"])
        settled = approve_nonuse(aoi["id"], 150, "PERSONAL_CONVENIENCE")
        assert settled["billable_aums"] == 0
        assert _live_bill_total(aoi["id"]) == 0, (
            "full non-use leaves the year charging nothing")
        aoi_ids.append(aoi["id"])
    return {"permittee": holder["permittee"], "base_property": holder["base_property"],
            "permit": get_permit(permit["id"]), "aoi_ids": aoi_ids}


def test_renewal_is_barred_once_the_non_use_run_reaches_three_years():
    """Three consecutive wholly non-used years put consecutive_nonuse_years at exactly the
    ceiling, so the renewal is refused with ERR_NONUSE_LIMIT_EXCEEDED, the permit keeps its
    ISSUED authorization and no successor is born.

    PRD 3.5: "The permit's `consecutive_nonuse_years` is the length of the longest counting run
    that **ends at the most recent qualifying year**."
    PRD 3.5: "Once it reaches 3, the preference has lapsed and renewal is barred with
    `ERR_NONUSE_LIMIT_EXCEEDED`; at 2 a renewal still succeeds."
    PRD 2.6: "A permit whose `consecutive_nonuse_years` has reached three may not be renewed,
    because the preference has lapsed; at two the renewal still succeeds."

    Design: Difficulty/boundary_precision_check/nonuse_run_ceiling_boundary_on_renewal
    """
    land = allotment_with_pasture(total_permitted_aums=1200, pasture_aum_capacity=300,
                                  required_pasture_rotation_count=1, acres=24000)
    run = _nonuse_run(land["allotment"]["id"], land["pasture"]["id"], [2026, 2027, 2028],
                      entry_md="06-01", exit_md="07-02")
    assert run["permit"]["consecutive_nonuse_years"] == 3

    validate_error(
        api_client.renew_permit(
            run["permit"]["id"],
            f.renew_payload(run["base_property"]["id"], requested_aums=150,
                            term_start_date="2031-01-01", term_end_date="2035-12-31"),
            make_officer_headers()),
        ApiErrorId.ERR_NONUSE_LIMIT_EXCEEDED, 409)

    assert get_permit(run["permit"]["id"])["permit_status"] == "ISSUED", (
        "the refused renewal does not expire the predecessor")
    assert _successors(run["permit"]["id"]) == []

    allotment = get_allotment(land["allotment"]["id"])
    assert allotment["allocated_aums"] == 0, "every year was wholly non-used"
    assert allotment["open_aums"] == 1200
    assert get_permittee(run["permittee"]["id"])["outstanding_balance_cents"] == 0


def test_renewal_still_succeeds_one_year_short_of_the_non_use_ceiling():
    """The same fixture stopped at two non-used years renews: the predecessor expires, a
    successor is born carrying the predecessor's own consecutive_nonuse_years of 2 and its
    150 permitted AUMs, which proves the ceiling comparison is at-least-three and not
    at-least-two.

    PRD 3.4: "On success the predecessor moves to `permit_status` `EXPIRED`, and a successor
    permit is created carrying `predecessor_permit_id` pointing at the predecessor,
    `permit_status` `ISSUED`, `account_status` `CURRENT`, the same `permittee_id`,
    `allotment_id`, `base_property_id`, `permitted_aums` and `livestock_kind` as the
    predecessor, and the supplied term dates."
    PRD 3.4: "The predecessor's `consecutive_nonuse_years` is recomputed and copied onto the
    successor."

    Design: Difficulty/boundary_precision_check/nonuse_run_ceiling_boundary_on_renewal
    """
    land = allotment_with_pasture(total_permitted_aums=1200, pasture_aum_capacity=300,
                                  required_pasture_rotation_count=1, acres=24000)
    run = _nonuse_run(land["allotment"]["id"], land["pasture"]["id"], [2026, 2027])
    assert run["permit"]["consecutive_nonuse_years"] == 2

    get_success_data(api_client.renew_permit(
        run["permit"]["id"],
        f.renew_payload(run["base_property"]["id"], requested_aums=150,
                        term_start_date="2031-01-01", term_end_date="2035-12-31"),
        make_officer_headers()))

    predecessor = get_permit(run["permit"]["id"])
    assert predecessor["permit_status"] == "EXPIRED"

    successors = _successors(run["permit"]["id"])
    assert len(successors) == 1
    successor = successors[0]
    assert successor["permit_status"] == "ISSUED"
    assert successor["account_status"] == "CURRENT"
    assert successor["consecutive_nonuse_years"] == 2
    assert successor["permitted_aums"] == 150
    assert successor["permittee_id"] == run["permittee"]["id"]
    assert successor["allotment_id"] == land["allotment"]["id"]
    assert successor["base_property_id"] == run["base_property"]["id"]
    assert successor["term_start_date"] == "2031-01-01"
    assert successor["term_end_date"] == "2035-12-31"


def _floor_setup():
    """A 1200-AUM allotment, an ISSUED 300-AUM permit and an ISSUED 2026 instruction with one
    scheduled leg and an unpaid 54,100-cent preliminary bill; the minimum-charge floor for the
    year is floor(0.25 x 300) = 75 AUMs."""
    setup = issued_aoi_setup(authorized_aums=300, total_permitted_aums=1200,
                             pasture_aum_capacity=300, carrying_capacity_aums=400,
                             requested_aums=300, allotment_overrides={"acres": 24000})
    assert setup["aoi"]["nonuse_aums"] == 0
    assert setup["preliminary_bill"]["total_amount_cents"] == 54100
    return setup


def _settle(setup, actual_entry_date, actual_exit_date, actual_head_count):
    """Report the single leg, accept the report and return the resulting final bill."""
    report_actual_use(setup["use_record"]["id"], actual_entry_date=actual_entry_date,
                      actual_exit_date=actual_exit_date, actual_head_count=actual_head_count)
    accepted = accept_use_report(setup["aoi"]["id"])
    finals = list_bills(aoi_id=setup["aoi"]["id"], bill_type="FINAL_USE")
    assert len(finals) == 1
    return accepted, finals[0]


def test_reported_use_just_below_the_minimum_charge_floor_is_billed_at_the_floor():
    """70 head over 32 days is 74.67 actual AUMs, a third of an AUM short of the 75-AUM floor,
    so the final bill charges the floor: 75.00 billed AUMs, 12,900 cents of base and no
    administrative fee, superseding the unpaid preliminary bill.

    PRD 3.6: "The **final** variant, used when an accepted use report is billed, sets
    `billed_aums` to whichever is larger of the instruction's `actual_aums_total` and one
    quarter of the instruction's `authorized_aums` less its `nonuse_aums`, that quarter being
    floored to a whole AUM; because `actual_aums_total` carries two decimal places, step two
    genuinely rounds here, so identical instruction data yields a different total under the two
    variants and the difference is settled in step five."
    PRD 3.6: "When the preliminary bill's `amount_paid_cents` is exactly 0, that bill moves to
    `bill_status` `VOIDED` and a bill of `bill_type` `FINAL_USE` is issued for the final total
    with `superseded_bill_id` set to the voided bill's `id`."

    Design: Difficulty/boundary_precision_check/minimum_billable_fraction_floor_boundary
    """
    setup = _floor_setup()

    accepted, final_bill = _settle(setup, "2026-04-01", "2026-05-03", 70)
    assert_aums(get_use_record(setup["use_record"]["id"])["actual_aums"], 74.67)
    assert_aums(accepted["actual_aums_total"], 74.67)
    assert accepted["aoi_status"] == "BILLED"

    assert_aums(final_bill["billed_aums"], 75.00)
    assert final_bill["base_amount_cents"] == 12900
    assert final_bill["admin_fee_cents"] == 0
    assert final_bill["total_amount_cents"] == 12900
    assert final_bill["superseded_bill_id"] == setup["preliminary_bill"]["id"]
    assert get_bill(setup["preliminary_bill"]["id"])["bill_status"] == "VOIDED"
    assert get_permittee(setup["permittee"]["id"])["outstanding_balance_cents"] == 12900


def test_reported_use_exactly_at_the_floor_is_billed_as_itself():
    """75 head over 30 days is exactly 75.00 actual AUMs, so the larger-of comparison returns
    the reported figure and the total is still 12,900 cents — the floor is a maximum, not an
    amount added to the reported use.

    PRD 3.6: "The **final** variant, used when an accepted use report is billed, sets
    `billed_aums` to whichever is larger of the instruction's `actual_aums_total` and one
    quarter of the instruction's `authorized_aums` less its `nonuse_aums`, that quarter being
    floored to a whole AUM; because `actual_aums_total` carries two decimal places, step two
    genuinely rounds here, so identical instruction data yields a different total under the two
    variants and the difference is settled in step five."
    PRD 3.6: "Step two computes `base_amount_cents` as `billed_aums` multiplied by the grazing
    fee rate of 172 cents per AUM, rounded half-up to a whole cent; that same 172 is recorded on
    the bill as its `fee_rate_cents_per_aum`."

    Design: Difficulty/boundary_precision_check/minimum_billable_fraction_floor_boundary
    """
    setup = _floor_setup()

    accepted, final_bill = _settle(setup, "2026-04-01", "2026-05-01", 75)
    assert_aums(accepted["actual_aums_total"], 75.00)

    assert_aums(final_bill["billed_aums"], 75.00)
    assert final_bill["base_amount_cents"] == 12900
    assert final_bill["total_amount_cents"] == 12900
    assert final_bill["fee_rate_cents_per_aum"] == 172
    assert get_permittee(setup["permittee"]["id"])["outstanding_balance_cents"] == 12900


def test_reported_use_just_above_the_floor_is_billed_on_its_two_decimal_figure():
    """113 head over 20 days is 75.33 actual AUMs, a third of an AUM above the floor, so the
    reported figure governs and 75.33 x 172 = 12,956.76 cents rounds half-up to 12,957 — a
    figure that only appears if the two decimal places survive into the pricing step.

    PRD 2.7: "Rounding to 2 decimal places happens once, per record, at the moment the record's
    quantity is computed; aggregates are then formed by adding the already-rounded per-record
    values and are **not** rounded again."
    PRD 3.6: "Step two computes `base_amount_cents` as `billed_aums` multiplied by the grazing
    fee rate of 172 cents per AUM, rounded half-up to a whole cent; that same 172 is recorded on
    the bill as its `fee_rate_cents_per_aum`."

    Design: Difficulty/boundary_precision_check/minimum_billable_fraction_floor_boundary
    """
    setup = _floor_setup()

    accepted, final_bill = _settle(setup, "2026-04-01", "2026-04-21", 113)
    assert_aums(accepted["actual_aums_total"], 75.33)

    assert_aums(final_bill["billed_aums"], 75.33)
    assert final_bill["base_amount_cents"] == 12957
    assert final_bill["admin_fee_cents"] == 0
    assert final_bill["total_amount_cents"] == 12957
    assert final_bill["total_amount_cents"] != 12900, (
        "12,900 is the figure produced by rounding billed_aums to a whole AUM before pricing")
    assert get_permittee(setup["permittee"]["id"])["outstanding_balance_cents"] == 12957


def _penny_pool(share_totals=(150, 100, 50), total_cost_cents=1000001):
    """One allotment carrying ISSUED permits of the given permitted AUMs, each held by its own
    permittee, plus an APPROVED half-share project over the given cost."""
    land = allotment_with_pasture(total_permitted_aums=1200, pasture_aum_capacity=300,
                                  required_pasture_rotation_count=1, acres=24000)
    holders = []
    for aums in share_totals:
        holder = permittee_with_base_property(carrying_capacity_aums=200)
        permit = issue_permit(create_permit(
            land["allotment"]["id"], holder["permittee"]["id"],
            holder["base_property"]["id"], requested_aums=aums)["id"])
        assert permit["permitted_aums"] == aums
        holders.append({"permittee": holder["permittee"], "permit": permit})
    project = create_project(
        land["allotment"]["id"], project_type="WATER_DEVELOPMENT",
        total_cost_cents=total_cost_cents, agency_share_pct=0.5, permittee_share_pct=0.5,
        maintenance_responsibility="PERMITTEE")
    assert project["permittee_share_cents"] == 0, "the pot is fixed at approval, not proposal"
    project = approve_project(project["id"])
    return {"allotment": land["allotment"], "holders": holders, "project": project}


def _cost_share_bill(project_id, permittee_id):
    bills = list_bills(project_id=project_id, permittee_id=permittee_id)
    assert len(bills) == 1, "one cost-share bill per eligible permit"
    return bills[0]


def test_cost_share_remainder_cent_goes_to_the_largest_share_and_the_pot_lands_exactly():
    """A 1,000,001-cent project at half share fixes a 500,001-cent pot, whose pro-rata split
    over 150, 100 and 50 permitted AUMs floors to 250,000 + 166,667 + 83,333 = 500,000 and
    leaves one remainder cent; that cent is added to the largest permit, so the three bills read
    250,001, 166,667 and 83,333 and sum to the pot exactly.

    PRD 3.12: "On success `project_status` becomes `APPROVED` and `permittee_share_cents` is set
    to `total_cost_cents` multiplied by `permittee_share_pct`, rounded half-up to a whole cent."
    PRD 3.12: "Pass one computes each permit's provisional share as `permittee_share_cents`
    multiplied by that permit's `permitted_aums` divided by the pool total, **floored** to a
    whole cent."
    PRD 3.12: "Flooring every share necessarily leaves a remainder, so pass two computes that
    remainder as `permittee_share_cents` less the sum of the floored shares, ranks the eligible
    permits by `permitted_aums` **descending** and then, for ties, by `created_at` **ascending**,
    and adds exactly one cent to each of the first as many permits as there are remainder cents."
    PRD 3.12: "The invariant is unconditional: the sum of `total_amount_cents` over the project's
    non-voided `PROJECT_COST_SHARE` bills equals `permittee_share_cents`, so no cent is created
    and none is lost in the rounding."

    Design: Difficulty/boundary_precision_check/cost_share_remainder_penny_boundary
    """
    pool = _penny_pool()
    project_id = pool["project"]["id"]
    assert pool["project"]["permittee_share_cents"] == 500001, "round_half_up(500,000.5)"
    assert pool["project"]["project_status"] == "APPROVED"
    assert pool["project"]["allocated_share_cents"] == 0

    allocated = allocate_cost_share(project_id)
    assert allocated["project_status"] == "COST_ALLOCATED"
    assert allocated["allocated_share_cents"] == 500001
    assert allocated["permittee_share_cents"] == 500001

    expected = (250001, 166667, 83333)
    bills = [_cost_share_bill(project_id, h["permittee"]["id"]) for h in pool["holders"]]
    for holder, bill, amount in zip(pool["holders"], bills, expected):
        assert bill["total_amount_cents"] == amount
        assert bill["base_amount_cents"] == amount
        assert bill["bill_type"] == "PROJECT_COST_SHARE"
        assert bill["bill_status"] == "ISSUED"
        assert bill["admin_fee_cents"] == 0
        assert bill["penalty_amount_cents"] == 0
        assert bill["fee_rate_cents_per_aum"] == 0
        assert_aums(bill["billed_aums"], 0)
        assert bill["aoi_id"] is None
        assert bill["trespass_incident_id"] is None
        assert bill["project_id"] == project_id
        assert bill["due_date"] == "2026-08-31", "the clock date 2026-08-01 plus 30 days"
        assert get_permittee(holder["permittee"]["id"])["outstanding_balance_cents"] == amount

    assert sum(b["total_amount_cents"] for b in bills) == 500001
    assert sum(b["total_amount_cents"] for b in bills) != 500002, (
        "500,002 is the figure produced by rounding each raw share half-up")
    assert get_project(project_id)["allocated_share_cents"] == 500001


def test_an_empty_eligible_pool_allocates_nothing_and_is_still_a_success():
    """An allotment whose only permit is still PENDING_REVIEW has no eligible pool, so the
    allocation returns HTTP 200 with allocated_share_cents left at 0, project_status
    COST_ALLOCATED and not one cost-share bill, even though the pot was fixed at 500,002 cents.

    PRD 3.12: "An **empty pool is a success, not a failure**."
    PRD 3.12: "When the allotment has no permit in `permit_status` `ISSUED`, or when the eligible
    permits' `permitted_aums` sum to 0, the allocation still completes: nothing is distributed,
    `allocated_share_cents` is set to 0, `project_status` becomes `COST_ALLOCATED`, and no bill
    of any kind is raised."
    PRD 3.4: "A `PENDING_REVIEW` application consumes no capacity whatsoever; the ledger of §2.9
    does not see it."

    Design: Difficulty/boundary_precision_check/cost_share_remainder_penny_boundary
    """
    land = allotment_with_pasture(total_permitted_aums=1200, pasture_aum_capacity=300,
                                  required_pasture_rotation_count=1, acres=24000)
    holder = permittee_with_base_property(carrying_capacity_aums=200)
    pending = create_permit(land["allotment"]["id"], holder["permittee"]["id"],
                            holder["base_property"]["id"], requested_aums=150)
    assert pending["permit_status"] == "PENDING_REVIEW"

    project = approve_project(create_project(
        land["allotment"]["id"], project_type="WATER_DEVELOPMENT", total_cost_cents=1000004,
        agency_share_pct=0.5, permittee_share_pct=0.5,
        maintenance_responsibility="PERMITTEE")["id"])
    assert project["permittee_share_cents"] == 500002

    allocated = get_success_data(
        api_client.allocate_cost_share(project["id"], make_officer_headers()), 200)
    assert allocated["project_status"] == "COST_ALLOCATED"
    assert allocated["allocated_share_cents"] == 0
    assert allocated["permittee_share_cents"] == 500002

    assert list_bills(project_id=project["id"]) == []
    assert get_permittee(holder["permittee"]["id"])["outstanding_balance_cents"] == 0
