"""Dues billing: proration variant vs consolidated-member variant, and the
tiered late-fee / credit-floor combinatorial calculation."""
from test_helpers import (
    validate_success, get_success_data,
    create_association, create_member, create_dues_period, bill_dues_period,
    set_clock, seed_credit,
    make_member_headers, TEST_USERS, api_client,
)

STAFF = TEST_USERS["staff_headers"]


def _invoices_by_member(api, period_id):
    resp = api.list_dues_invoices_flat(STAFF, params={"dues_period_id": period_id})
    data = get_success_data(resp)
    return {inv["member_id"]: inv for inv in data}


def test_dues_proration_vs_consolidated_variant(api):
    """PRD §3.2: "When the member's `created_at` falls inside the period's
    window from `period_start_date` through `due_date`, the member is a
    mid-year joiner and the base is prorated: the period's `amount_cents` is
    multiplied by the number of remaining days in the period — computed as the
    whole days from the member's `created_at` to the `due_date`, plus one —
    divided by 365, and the result is floored toward zero before any late-fee
    or credit step. Separately, when a member's `association_id` was re-pointed
    by an executed consolidation, the member is billed by the surviving
    association's period at the survivor's `amount_cents` — but if the member
    already holds any invoice, in any status, for the same calendar year from
    the absorbed association, the survivor's billing skips that member
    entirely, so no member is double-billed for a year."

    Design: Difficulty/dual_variant_calc/dues_proration_vs_consolidated_variant
    """
    set_clock("2026-09-01T00:00:00Z")
    a1 = create_association(association_code="A1", membership_dues_cents=120000,
                            late_fee_tier1_cents=5000, late_fee_tier2_cents=15000,
                            sanction_credit_cap_cents=200000)
    a2 = create_association(association_code="A2", membership_dues_cents=90000,
                            late_fee_tier1_cents=4000, late_fee_tier2_cents=12000,
                            sanction_credit_cap_cents=200000)
    m1 = create_member(a1["id"], member_nr="M1", full_name="Member One")
    m3 = create_member(a2["id"], member_nr="M3", full_name="Member Three")
    consol = get_success_data(api.create_consolidation(
        a1["id"], {"absorbed_association_id": a2["id"],
                   "effective_at": "2027-01-01T00:00:00Z"}, STAFF))
    set_clock("2027-01-01T00:00:00Z")
    m2 = create_member(a1["id"], member_nr="M2", full_name="Member Two")
    get_success_data(api.execute_consolidation(a1["id"], consol["id"], STAFF))
    period = create_dues_period(
        a1["id"], year=2027, period_start_date="2026-12-01T00:00:00Z",
        due_date="2027-01-31T00:00:00Z", grace_end_date="2027-03-02T00:00:00Z",
        amount_cents=120000)
    bill_dues_period(a1["id"], period)
    invoices = _invoices_by_member(api, period["id"])
    assert invoices[m1["id"]]["base_amount_cents"] == 120000, \
        "M1 created before the period window: full base"
    assert invoices[m2["id"]]["base_amount_cents"] == 10191, \
        "M2 prorated: floor(120000 * 31 / 365) == 10191"
    assert invoices[m3["id"]]["base_amount_cents"] == 120000, \
        "M3 consolidated with no prior same-year invoice: full survivor amount"
    assert invoices[m2["id"]]["base_amount_cents"] != invoices[m3["id"]]["base_amount_cents"]


def test_dues_consolidated_member_skipped_when_prior_invoice_exists(api):
    """PRD §3.2: "Separately, when a member's `association_id` was re-pointed
    by an executed consolidation, the member is billed by the surviving
    association's period at the survivor's `amount_cents` — but if the member
    already holds any invoice, in any status, for the same calendar year from
    the absorbed association, the survivor's billing skips that member
    entirely, so no member is double-billed for a year."

    Design: Difficulty/dual_variant_calc/dues_proration_vs_consolidated_variant
    """
    set_clock("2026-09-01T00:00:00Z")
    survivor = create_association(association_code="AS2", membership_dues_cents=120000)
    absorbed = create_association(association_code="AA2", membership_dues_cents=90000,
                                  late_fee_tier1_cents=4000, late_fee_tier2_cents=12000)
    mx = create_member(absorbed["id"], member_nr="MX", full_name="Member X")
    consol = get_success_data(api.create_consolidation(
        survivor["id"], {"absorbed_association_id": absorbed["id"],
                         "effective_at": "2027-02-01T00:00:00Z"}, STAFF))
    a_period = create_dues_period(
        absorbed["id"], year=2027, period_start_date="2026-12-01T00:00:00Z",
        due_date="2027-01-31T00:00:00Z", grace_end_date="2027-03-02T00:00:00Z",
        amount_cents=90000)
    set_clock("2027-01-10T00:00:00Z")
    bill_dues_period(absorbed["id"], a_period)
    s_period = create_dues_period(
        survivor["id"], year=2027, period_start_date="2026-12-01T00:00:00Z",
        due_date="2027-02-28T00:00:00Z", grace_end_date="2027-03-30T00:00:00Z",
        amount_cents=120000)
    set_clock("2027-02-01T00:00:00Z")
    get_success_data(api.execute_consolidation(survivor["id"], consol["id"], STAFF))
    bill_dues_period(survivor["id"], s_period)
    resp = api.list_dues_invoices_flat(STAFF, params={"member_id": mx["id"]})
    mx_invoices = get_success_data(resp)
    assert len(mx_invoices) == 1, \
        f"consolidated member with a prior same-year invoice must be skipped by the survivor's bill; got {len(mx_invoices)} invoices"
    assert mx_invoices[0]["amount_due_cents"] == 90000, \
        "exactly one annual liability (the absorbed association's 90000c invoice)"


def test_dues_invoice_tiered_late_fee_with_credit_floor(api):
    """PRD §3.2: "`late_fee_cents` is 0 when `days_overdue_at_issue` is 0; the
    association's `late_fee_tier1_cents` when it is at least 1 and at most 30
    (day 30 belongs to tier 1); and the association's `late_fee_tier2_cents`
    when it is 31 or more — tier 2 replaces tier 1, it is not added to it."
    PRD §3.2: "`credit_applied_cents` is the smaller of the member's current
    `sanction_credit_balance_cents` and the sum of base plus late fee; that
    amount is debited from the member's balance at issuance."
    PRD §3.2: "`amount_due_cents` is the base plus the late fee minus the
    applied credit."

    Design: Difficulty/combinatorial_formula/dues_invoice_tiered_late_fee_with_credit_floor
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="CA", membership_dues_cents=120000,
                               late_fee_tier1_cents=5000, late_fee_tier2_cents=15000,
                               sanction_credit_cap_cents=200000)
    m1 = create_member(assoc["id"], member_nr="M1", full_name="One")
    m2 = create_member(assoc["id"], member_nr="M2", full_name="Two")
    m3 = create_member(assoc["id"], member_nr="M3", full_name="Three")
    seed_credit(assoc["id"], m2["id"], 4000, note="seed 4000")
    seed_credit(assoc["id"], m3["id"], 20000, note="seed 20000")
    period = create_dues_period(
        assoc["id"], year=2027, period_start_date="2026-12-01T00:00:00Z",
        due_date="2027-01-31T00:00:00Z", grace_end_date="2027-03-02T00:00:00Z",
        amount_cents=120000)
    set_clock("2027-02-10T00:00:00Z")
    bill_dues_period(assoc["id"], period)
    invoices = _invoices_by_member(api, period["id"])

    i1 = invoices[m1["id"]]
    assert i1["days_overdue_at_issue"] == 10
    assert i1["late_fee_cents"] == 5000, "tier1 applies at 10 days overdue"
    assert i1["credit_applied_cents"] == 0
    assert i1["amount_due_cents"] == 125000

    i2 = invoices[m2["id"]]
    assert i2["late_fee_cents"] == 5000
    assert i2["credit_applied_cents"] == 4000, "min(balance 4000, base+fee) consumed all credit"
    assert i2["amount_due_cents"] == 121000
    member_m2 = get_success_data(api.get_member(assoc["id"], m2["id"], STAFF))
    assert member_m2["sanction_credit_balance_cents"] == 0

    i3 = invoices[m3["id"]]
    assert i3["credit_applied_cents"] == 20000
    assert i3["amount_due_cents"] == 105000


def test_dues_invoice_late_fee_tier2_replaces_tier1(api):
    """PRD §3.2: "the association's `late_fee_tier2_cents` when it is 31 or
    more — tier 2 replaces tier 1, it is not added to it. Tier selection uses
    the days at issue, never the days at payment."

    Design: Difficulty/combinatorial_formula/dues_invoice_tiered_late_fee_with_credit_floor
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="CA2", membership_dues_cents=120000,
                               late_fee_tier1_cents=5000, late_fee_tier2_cents=15000)
    m = create_member(assoc["id"], member_nr="M1", full_name="One")
    period = create_dues_period(
        assoc["id"], year=2027, period_start_date="2026-12-01T00:00:00Z",
        due_date="2027-01-31T00:00:00Z", grace_end_date="2027-03-02T00:00:00Z",
        amount_cents=120000)
    # 2027-03-03 is 31 days after due_date 2027-01-31 -> tier2.
    set_clock("2027-03-03T00:00:00Z")
    bill_dues_period(assoc["id"], period)
    invoices = _invoices_by_member(api, period["id"])
    inv = invoices[m["id"]]
    assert inv["days_overdue_at_issue"] == 31
    assert inv["late_fee_cents"] == 15000, \
        "tier2 replaces tier1 at 31 days (15000, not 5000+15000)"
    assert inv["amount_due_cents"] == 135000
