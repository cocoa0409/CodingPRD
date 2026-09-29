"""Two variants of the same use-bill arithmetic over one operating instruction."""
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import (
    api_client,
    assert_aums,
    assert_use_bill_amounts,
    make_officer_headers,
    make_permittee_headers,
)
from test_helpers.fixtures import (
    accept_use_report,
    add_use_record,
    create_aoi,
    create_pasture,
    get_aoi,
    get_bill,
    get_permittee,
    issue_aoi,
    issued_permit_setup,
    list_bills,
)


def _sage_creek_setup():
    """1200-AUM allotment, two 300-AUM pastures, an ISSUED 300-AUM permit and a
    DRAFT 2026 instruction authorized at 300 AUMs holding two scheduled legs of
    103.33 and 100.00 planned AUMs."""
    setup = issued_permit_setup(
        total_permitted_aums=1200,
        pasture_aum_capacity=300,
        required_pasture_rotation_count=2,
        carrying_capacity_aums=400,
        requested_aums=300,
        allotment_overrides={"acres": 40000},
    )
    setup["pasture_2"] = create_pasture(
        setup["allotment"]["id"], pasture_aum_capacity=300, sequence_order=2)
    aoi = create_aoi(setup["permit"]["id"], grazing_year=2026, authorized_aums=300,
                     season_start_date="2026-01-01", season_end_date="2026-12-31")
    setup["use_record_1"] = add_use_record(
        aoi["id"], setup["pasture"]["id"], planned_entry_date="2026-04-01",
        planned_exit_date="2026-05-02", planned_head_count=100, livestock_kind="CATTLE")
    setup["use_record_2"] = add_use_record(
        aoi["id"], setup["pasture_2"]["id"], planned_entry_date="2026-05-02",
        planned_exit_date="2026-06-01", planned_head_count=100, livestock_kind="CATTLE")
    setup["aoi"] = get_aoi(aoi["id"])
    return setup


def test_preliminary_use_bill_bills_integer_authorized_aums_at_the_mid_admin_tier():
    """Issuing the instruction raises a PRELIMINARY_USE bill on the integer authorized
    figure: 300 AUMs x 172 cents = 51,600 cents of base, which lands in the middle
    administrative-fee tier and totals 54,100 cents due 30 days after the clock date.

    PRD 3.6: "The **preliminary** variant, used when an operating instruction is issued,
    sets `billed_aums` to the instruction's `authorized_aums` less its `nonuse_aums` — an
    integer, so step two is exact — and applies no minimum-charge floor."
    PRD 3.6: "Step three selects the tiered administrative fee **from `base_amount_cents`,
    never from the total**: `admin_fee_cents` is 0 when `base_amount_cents` is below 50,000
    cents, 2,500 cents when `base_amount_cents` is at least 50,000 and below 200,000 cents, and
    6,000 cents when `base_amount_cents` is 200,000 cents or more."
    PRD 3.6: "Every use bill is raised in `bill_status` `ISSUED` with `amount_paid_cents`
    of 0 and a `due_date` of the logical-clock date at issuance plus 30 days."

    Design: Difficulty/dual_variant_calc/preliminary_vs_final_use_bill_divergence
    """
    setup = _sage_creek_setup()

    issued = issue_aoi(setup["aoi"]["id"])
    assert issued["aoi_status"] == "ISSUED"

    bills = list_bills(aoi_id=setup["aoi"]["id"], bill_type="PRELIMINARY_USE")
    assert len(bills) == 1, "issuance raises exactly one preliminary bill"
    bill = bills[0]

    assert_use_bill_amounts(bill, billed_aums=300, base_amount_cents=51600,
                            admin_fee_cents=2500, total_amount_cents=54100)
    assert bill["bill_status"] == "ISSUED"
    assert bill["amount_paid_cents"] == 0
    assert bill["due_date"] == "2026-08-31", (
        "due_date is the logical-clock date 2026-08-01 plus 30 days")
    assert bill["superseded_bill_id"] is None
    assert bill["aoi_id"] == setup["aoi"]["id"]

    permittee = get_permittee(setup["permittee"]["id"])
    assert permittee["outstanding_balance_cents"] == 54100


def test_final_use_bill_bills_two_decimal_actual_total_and_drops_to_the_zero_admin_tier():
    """The same instruction billed under the final variant charges the 2-decimal
    actual_aums_total of 153.34 AUMs — 26,374 cents with no administrative fee — voids the
    unpaid preliminary bill and points the replacement at it, so the two variants of the
    identical instruction differ by 26,374 - 54,100 = -27,726 cents.

    PRD 3.6: "The **final** variant, used when an accepted use report is billed, sets
    `billed_aums` to whichever is larger of the instruction's `actual_aums_total` and one
    quarter of the instruction's `authorized_aums` less its `nonuse_aums`, that quarter
    being floored to a whole AUM; because `actual_aums_total` carries two decimal places,
    step two genuinely rounds here, so identical instruction data yields a different total
    under the two variants and the difference is settled in step five."
    PRD 3.6: "When the preliminary bill's `amount_paid_cents` is exactly 0, that bill moves
    to `bill_status` `VOIDED` and a bill of `bill_type` `FINAL_USE` is issued for the final
    total with `superseded_bill_id` set to the voided bill's `id`."

    Design: Difficulty/dual_variant_calc/preliminary_vs_final_use_bill_divergence
    """
    setup = _sage_creek_setup()
    issue_aoi(setup["aoi"]["id"])
    preliminary = list_bills(aoi_id=setup["aoi"]["id"], bill_type="PRELIMINARY_USE")[0]

    permittee_headers = make_permittee_headers(setup["permittee"]["id"])
    get_success_data(api_client.report_actual_use(
        setup["use_record_1"]["id"],
        {"actual_entry_date": "2026-04-01", "actual_exit_date": "2026-04-24",
         "actual_head_count": 100},
        permittee_headers))
    get_success_data(api_client.report_actual_use(
        setup["use_record_2"]["id"],
        {"actual_entry_date": "2026-05-02", "actual_exit_date": "2026-05-25",
         "actual_head_count": 100},
        permittee_headers))

    accepted = accept_use_report(setup["aoi"]["id"])
    assert accepted["aoi_status"] == "BILLED"
    assert_aums(accepted["actual_aums_total"], 153.34)

    final_bills = list_bills(aoi_id=setup["aoi"]["id"], bill_type="FINAL_USE")
    assert len(final_bills) == 1, "acceptance raises exactly one final bill"
    final_bill = final_bills[0]

    assert_use_bill_amounts(final_bill, billed_aums=153.34, base_amount_cents=26374,
                            admin_fee_cents=0, total_amount_cents=26374)
    assert final_bill["superseded_bill_id"] == preliminary["id"]
    assert get_bill(preliminary["id"])["bill_status"] == "VOIDED"
    assert final_bill["total_amount_cents"] - preliminary["total_amount_cents"] == -27726

    permittee = get_permittee(setup["permittee"]["id"])
    assert permittee["outstanding_balance_cents"] == 26374


def test_final_variant_reads_its_admin_fee_tier_from_the_recomputed_base_amount():
    """The administrative fee is selected from the final bill's own base_amount_cents, so
    the same instruction that paid 2,500 cents of fee under the preliminary variant pays 0
    under the final variant: reading the tier off the total would keep the fee alive.

    PRD 3.6: "Step three selects the tiered administrative fee **from `base_amount_cents`,
    never from the total**: `admin_fee_cents` is 0 when `base_amount_cents` is below 50,000
    cents, 2,500 cents when `base_amount_cents` is at least 50,000 and below 200,000 cents, and
    6,000 cents when `base_amount_cents` is 200,000 cents or more."
    PRD 3.6: "Reading the tier off the total is the circular reading and produces the wrong
    fee, because the total already contains the fee."

    Design: Difficulty/dual_variant_calc/preliminary_vs_final_use_bill_divergence
    """
    setup = _sage_creek_setup()
    issue_aoi(setup["aoi"]["id"])
    preliminary = list_bills(aoi_id=setup["aoi"]["id"], bill_type="PRELIMINARY_USE")[0]
    assert preliminary["admin_fee_cents"] == 2500

    permittee_headers = make_permittee_headers(setup["permittee"]["id"])
    for record_id, entry, exit_date in (
        (setup["use_record_1"]["id"], "2026-04-01", "2026-04-24"),
        (setup["use_record_2"]["id"], "2026-05-02", "2026-05-25"),
    ):
        validate_success(api_client.report_actual_use(
            record_id,
            {"actual_entry_date": entry, "actual_exit_date": exit_date,
             "actual_head_count": 100},
            permittee_headers))

    accept_use_report(setup["aoi"]["id"])
    final_bill = list_bills(aoi_id=setup["aoi"]["id"], bill_type="FINAL_USE")[0]

    assert final_bill["base_amount_cents"] == 26374
    assert final_bill["admin_fee_cents"] == 0, (
        "26,374 cents of base is below the 50,000-cent tier threshold")
    assert final_bill["total_amount_cents"] == final_bill["base_amount_cents"]
    assert final_bill["fee_rate_cents_per_aum"] == 172
    officer = make_officer_headers()
    assert validate_success(api_client.get_bill(final_bill["id"], officer))["bill_type"] == "FINAL_USE"
