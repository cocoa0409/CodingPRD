"""Calculation-corner tests: the exact cents the PRD's arithmetic produces.

Each test translates one instance of the SCAFFOLD_CORNER_DESIGN `calculations`
section. Every expected figure is an exact integer number of cents taken from
the design's own pre-computed literals — never a tolerance and never a value
recomputed inside the assert.

The database is empty before every test, so each test builds its whole world
through API calls. The canonical lines are dated in June 2026 and the logical
clock stands at its 2026-08-01T00:00:00.000Z epoch, so every purchase window
and every compliance window used here is closed and entirely in the past.
"""
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_member_ledger, assert_split
from test_helpers.test_users import (
    make_analyst_headers,
    make_gpo_admin_headers,
    make_member_operator_headers,
)
from test_helpers.types import (
    AccrualBasis,
    AccrualBlockReason,
    AuditStatus,
    ComplianceResult,
    DealStatus,
    DistributorStatus,
    ItemStatus,
    MatchStatus,
    MemberEnrollmentStatus,
    NormalizationStatus,
    RateCardStatus,
    RateType,
    RecoveryOutcome,
    SavingsBasis,
)

ANALYST = make_analyst_headers()
ADMIN = make_gpo_admin_headers()

# --- instance 1: the PERCENT_OF_SPEND card engineered onto a half cent -------
PERCENT_BPS = 275

# --- instance 2: the second overbilled member -------------------------------
PIER_LEGAL_NAME = "Pier 9 Oyster Bar Inc"
PIER_COMMITTED_ANNUAL_SPEND_CENTS = 9_000_000
PIER_SIGNATORY_NAME = "T Okafor"

# --- instance 3: the four-arm key space ------------------------------------
DEAL_2027_CODE = "PBC-2027"
DEAL_2027_FROM = "2027-01-01"
DEAL_2027_TO = "2027-12-31"
RIVAL_DEAL_CODE = "RVL-2026"
RIVAL_MANUFACTURER_NAME = "Rival Beef LLC"
RIVAL_REQUIRED_PURCHASE_WINDOW_DAYS = 90

CHICKEN_2027_SKU = "PBC-CHIX-TENDER"
CHICKEN_2027_KEY = "CHIX-TENDER-CS30"
CHICKEN_2027_PACK_SIZE = 30
CHICKEN_2027_BASELINE_UNIT_COST_CENTS = 7400
CHICKEN_2027_CONTRACT_UNIT_COST_CENTS = 6900
CHICKEN_2027_RATE_CENTS_PER_CASE = 90

RIVAL_BEEF_SKU = "RVL-PATTY-4OZ"
RIVAL_BRISKET_SKU = "RVL-BRISKET"
BRISKET_KEY = "BEEF-BRISKET-CS20"
BRISKET_PACK_SIZE = 20
BRISKET_BASELINE_UNIT_COST_CENTS = 14200
BRISKET_CONTRACT_UNIT_COST_CENTS = 13100

FRY_KEY = "POTATO-FRY-CS6"

# --- instance 4: the two compliance windows over one January line ----------
JAN_START = "2026-01-01"
JAN_END = "2026-01-31"
JAN_INVOICE_DATE = "2026-01-15"
JAN_BATCH_REFERENCE = "METRO-2026-01"

# --- instance 5: the superseded card ---------------------------------------
OLD_RATE_CENTS_PER_CASE = 100
NEW_RATE_CENTS_PER_CASE = 150
NEW_CARD_FROM = "2026-06-01"
TRUNCATED_EFFECTIVE_TO = "2026-05-31"
Q2B_PERIOD_START = "2026-05-01"
Q2B_PERIOD_END = "2026-06-30"
Q2B_BATCH_REFERENCE = "METRO-2026-Q2B"
MAY_INVOICE_DATE = "2026-05-20"
MAY_LINE_CASES = 20


def accrual_rows_for_line(line_id: str):
    """The accrual rows /accruals reports for one purchase line, with meta."""
    return validate_paginated(
        api_client.list_accruals(
            ANALYST, {"purchase_line_id": line_id, "limit": C.MAX_LIMIT}
        )
    )


def percent_of_spend_june_normalized() -> dict:
    """The canonical June feed (30 then 40 cases at 9140) priced by an APPROVED
    PERCENT_OF_SPEND card at 275 bps, normalized but not yet accrued."""
    return fx.setup_june_normalized(
        RateType.PERCENT_OF_SPEND.value, card_overrides={"percent_bps": PERCENT_BPS}
    )


def two_member_overbilled_june_feed() -> dict:
    """One June feed holding two members' beef lines: Harbor Grill 30 cases on
    base 8533 and Pier 9 40 cases on base 8540, both auditable through an
    ACTIVE PURCHASE_DATA_AND_PRICING letter with METRO-01. No manufacturer deal
    exists, so the lines carry pricing but no rebate.

    The feed is normalized before the audit because the PRD runs the markup
    audit only "on a batch whose `audit_status` is `NOT_AUDITED` and whose
    `normalization_status` is either `NORMALIZED` or `ACCRUED`".
    """
    tier = fx.create_tier()
    distributor = fx.create_distributor()

    harbor = fx.create_member(tier["id"])
    harbor_letter = fx.submit_letter(harbor["id"], distributor["id"])
    fx.countersign_letter(harbor_letter["id"], distributor["id"])
    harbor = fx.activate_member(harbor["id"])

    pier = fx.create_member(
        tier["id"],
        legal_name=PIER_LEGAL_NAME,
        committed_annual_spend_cents=PIER_COMMITTED_ANNUAL_SPEND_CENTS,
    )
    pier_letter = fx.submit_letter(
        pier["id"], distributor["id"], signatory_name=PIER_SIGNATORY_NAME
    )
    fx.countersign_letter(pier_letter["id"], distributor["id"])
    pier = fx.activate_member(pier["id"])

    batch = fx.create_batch(distributor["id"])
    line_harbor = fx.create_line(batch["id"], harbor["id"], distributor["id"])
    line_pier = fx.create_line_b(batch["id"], pier["id"], distributor["id"])
    batch = fx.normalize(batch["id"])

    return {
        "tier": tier,
        "distributor": distributor,
        "distributor_id": distributor["id"],
        "harbor_id": harbor["id"],
        "pier_id": pier["id"],
        "batch": batch,
        "batch_id": batch["id"],
        "line_harbor": line_harbor,
        "line_pier": line_pier,
    }


def recovery_requested_june_feed() -> dict:
    """Audit the two-member feed (380 cents overbilled) and open the demand, so
    the batch sits at RECOVERY_REQUESTED ready to be settled."""
    ctx = two_member_overbilled_june_feed()
    ctx["batch"] = fx.audit_markup(ctx["batch_id"])
    ctx["line_harbor"] = fx.read_line(ctx["line_harbor"]["id"])
    ctx["line_pier"] = fx.read_line(ctx["line_pier"]["id"])
    ctx["batch"] = fx.request_recovery(ctx["batch_id"])
    return ctx


def four_arm_key_space() -> dict:
    """One ACTIVE member and three deals over an overlapping key space:

    * PBC-2026 is ACTIVE for 2026 and owns BEEF-PATTY-4OZ-CS40 with an APPROVED
      PER_CASE 150 card.
    * PBC-2027 is ACTIVE but effective only in 2027 and owns CHIX-TENDER-CS30.
    * RVL-2026 stays DRAFT and owns a second BEEF-PATTY-4OZ-CS40 item plus the
      only owner of BEEF-BRISKET-CS20.

    The June feed then holds one line per arm, ingested in that order, and the
    batch is left at RECEIVED so the test itself triggers the normalize.
    """
    tier = fx.create_tier()
    distributor = fx.create_distributor()
    member = fx.create_member(tier["id"])
    letter = fx.submit_letter(member["id"], distributor["id"])
    fx.countersign_letter(letter["id"], distributor["id"])
    member = fx.activate_member(member["id"])

    deal = fx.create_deal()
    beef_item = fx.create_item(deal["id"])
    fx.approved_card(beef_item["id"], RateType.PER_CASE.value)
    deal = fx.activate_deal(deal["id"])

    deal_2027 = fx.create_deal(
        deal_code=DEAL_2027_CODE,
        effective_from=DEAL_2027_FROM,
        effective_to=DEAL_2027_TO,
    )
    chicken_item = fx.create_item(
        deal_2027["id"],
        manufacturer_sku=CHICKEN_2027_SKU,
        normalized_item_key=CHICKEN_2027_KEY,
        pack_size=CHICKEN_2027_PACK_SIZE,
        baseline_unit_cost_cents=CHICKEN_2027_BASELINE_UNIT_COST_CENTS,
        contract_unit_cost_cents=CHICKEN_2027_CONTRACT_UNIT_COST_CENTS,
    )
    fx.approved_card(
        chicken_item["id"],
        RateType.PER_CASE.value,
        flat_rate_cents_per_case=CHICKEN_2027_RATE_CENTS_PER_CASE,
        effective_from=DEAL_2027_FROM,
        effective_to=DEAL_2027_TO,
    )
    deal_2027 = fx.activate_deal(deal_2027["id"])

    rival_deal = fx.create_deal(
        manufacturer_name=RIVAL_MANUFACTURER_NAME,
        deal_code=RIVAL_DEAL_CODE,
        required_purchase_window_days=RIVAL_REQUIRED_PURCHASE_WINDOW_DAYS,
    )
    rival_beef_item = fx.create_item(rival_deal["id"], manufacturer_sku=RIVAL_BEEF_SKU)
    brisket_item = fx.create_item(
        rival_deal["id"],
        manufacturer_sku=RIVAL_BRISKET_SKU,
        normalized_item_key=BRISKET_KEY,
        pack_size=BRISKET_PACK_SIZE,
        baseline_unit_cost_cents=BRISKET_BASELINE_UNIT_COST_CENTS,
        contract_unit_cost_cents=BRISKET_CONTRACT_UNIT_COST_CENTS,
    )

    batch = fx.create_batch(distributor["id"])
    beef_line = fx.create_line(batch["id"], member["id"], distributor["id"])
    brisket_line = fx.create_line(
        batch["id"],
        member["id"],
        distributor["id"],
        distributor_sku="MF-77010",
        vendor_item_description="Whole brisket 20ct",
        normalized_item_key_reported=BRISKET_KEY,
        cases_shipped=10,
        invoice_unit_cost_cents=14000,
        distributor_base_cost_cents=13400,
        invoice_date="2026-06-06",
    )
    chicken_line = fx.create_line(
        batch["id"],
        member["id"],
        distributor["id"],
        distributor_sku="MF-66200",
        vendor_item_description="Chicken tenders 30ct",
        normalized_item_key_reported=CHICKEN_2027_KEY,
        cases_shipped=15,
        invoice_unit_cost_cents=7300,
        distributor_base_cost_cents=7000,
        invoice_date="2026-06-07",
    )
    fry_line = fx.create_line(
        batch["id"],
        member["id"],
        distributor["id"],
        distributor_sku="MF-55300",
        vendor_item_description="Shoestring fries 6ct",
        normalized_item_key_reported=FRY_KEY,
        cases_shipped=20,
        invoice_unit_cost_cents=8300,
        distributor_base_cost_cents=8000,
        invoice_date="2026-06-08",
    )
    return {
        "member_id": member["id"],
        "distributor_id": distributor["id"],
        "deal": deal,
        "deal_id": deal["id"],
        "deal_2027_id": deal_2027["id"],
        "rival_deal_id": rival_deal["id"],
        "beef_item_id": beef_item["id"],
        "chicken_item_id": chicken_item["id"],
        "rival_beef_item_id": rival_beef_item["id"],
        "brisket_item_id": brisket_item["id"],
        "batch_id": batch["id"],
        "beef_line": beef_line,
        "brisket_line": brisket_line,
        "chicken_line": chicken_line,
        "fry_line": fry_line,
    }


def january_matched_feed() -> dict:
    """One MATCHED January line — 30 cases at 9140 on 2026-01-15, so
    contracted_spend_cents is 274200 in any window containing that date. The
    logical clock still stands at its epoch, so every January window is closed
    and entirely in the past."""
    ctx = fx.setup_flat_program()
    batch = fx.create_batch(
        ctx["distributor_id"],
        period_start=JAN_START,
        period_end=JAN_END,
        source_reference=JAN_BATCH_REFERENCE,
    )
    ctx["batch_id"] = batch["id"]
    ctx["jan_line"] = fx.create_line(
        batch["id"],
        ctx["member_id"],
        ctx["distributor_id"],
        invoice_date=JAN_INVOICE_DATE,
    )
    ctx["batch"] = fx.normalize(batch["id"])
    return ctx


def superseded_card_program() -> dict:
    """The beef item carries two APPROVED PER_CASE cards: rc1 at 100 cents for
    2026-01-01..2028-12-31, then rc2 at 150 cents from 2026-06-01 proposed with
    supersede true. A 2026-05-01..2026-06-30 batch holds a 30-case June line and
    a 20-case May line, normalized and awaiting the accrual run."""
    tier = fx.create_tier()
    distributor = fx.create_distributor()
    member = fx.create_member(tier["id"])
    letter = fx.submit_letter(member["id"], distributor["id"])
    fx.countersign_letter(letter["id"], distributor["id"])
    member = fx.activate_member(member["id"])

    deal = fx.create_deal()
    item = fx.create_item(deal["id"])
    old_card = fx.approved_card(
        item["id"],
        RateType.PER_CASE.value,
        flat_rate_cents_per_case=OLD_RATE_CENTS_PER_CASE,
    )
    new_card = fx.approved_card(
        item["id"],
        RateType.PER_CASE.value,
        flat_rate_cents_per_case=NEW_RATE_CENTS_PER_CASE,
        effective_from=NEW_CARD_FROM,
        supersede=True,
    )
    deal = fx.activate_deal(deal["id"])

    batch = fx.create_batch(
        distributor["id"],
        period_start=Q2B_PERIOD_START,
        period_end=Q2B_PERIOD_END,
        source_reference=Q2B_BATCH_REFERENCE,
    )
    june_line = fx.create_line(batch["id"], member["id"], distributor["id"])
    may_line = fx.create_line(
        batch["id"],
        member["id"],
        distributor["id"],
        cases_shipped=MAY_LINE_CASES,
        invoice_date=MAY_INVOICE_DATE,
    )
    batch = fx.normalize(batch["id"])
    return {
        "member_id": member["id"],
        "distributor_id": distributor["id"],
        "deal_id": deal["id"],
        "item_id": item["id"],
        "old_card": old_card,
        "new_card": new_card,
        "batch": batch,
        "batch_id": batch["id"],
        "june_line": june_line,
        "may_line": may_line,
    }


def june_accrued_with_an_unowned_key_line() -> dict:
    """The canonical accrued June feed plus a third line of 20 fries cases at
    8300 reporting POTATO-FRY-CS6, a key no ContractedItem owns, so it stays
    UNMATCHED and earns no rebate."""
    ctx = fx.setup_flat_program()
    fx.ingest_june_feed(ctx)
    ctx["fry_line"] = fx.create_line(
        ctx["batch_id"],
        ctx["member_id"],
        ctx["distributor_id"],
        distributor_sku="MF-55300",
        vendor_item_description="Shoestring fries 6ct",
        normalized_item_key_reported=FRY_KEY,
        cases_shipped=20,
        invoice_unit_cost_cents=8300,
        distributor_base_cost_cents=8000,
        invoice_date="2026-06-08",
    )
    fx.normalize_june_feed(ctx)
    return fx.accrue_june_feed(ctx)


# ==========================================================================
# percent_of_spend_gross_rounds_half_up_at_the_half_cent
# ==========================================================================

def test_percent_of_spend_gross_rounds_the_exact_half_cent_up():
    """The 30-case line extends to 274200, so 275 bps lands on exactly 7540.5
    and must round UP to 7541 — a truncating implementation returns 7540 and
    then 226 / 5486 / 1828, which breaks the conservation identity.

    PRD: "Under `PERCENT_OF_SPEND`, the gross is the line's
    `invoice_extended_cents` multiplied by the card's `percent_bps` and divided
    by 10000, rounded half up to whole cents." and "a quotient ending in exactly
    one half rounds away from zero".

    Design: Corner/calculations/percent_of_spend_gross_rounds_half_up_at_the_half_cent
    """
    ctx = percent_of_spend_june_normalized()

    line_a = fx.read_line(ctx["line_a"]["id"])
    assert line_a["invoice_extended_cents"] == 274200, "30 cases at 9140"

    batch = validate_success(api_client.accrue_batch(ctx["batch_id"], ANALYST), 200)
    assert batch["normalization_status"] == NormalizationStatus.ACCRUED.value

    accrual_a = fx.accrual_for_line(ctx["line_a"]["id"])
    assert accrual_a["gross_rebate_cents"] == 7541, (
        "274200 * 275 / 10000 == 7540.5 rounds half UP to 7541, never down to 7540"
    )
    assert accrual_a["gross_rebate_cents"] != 7540
    assert_split(
        accrual_a,
        gross_rebate_cents=7541,
        admin_fee_bps_applied=300,
        admin_fee_cents=226,
        net_distributable_cents=7315,
        member_share_cents=5486,
        gpo_retention_cents=1829,
    )
    assert accrual_a["accrued_cases"] == 30
    assert accrual_a["basis"] == AccrualBasis.MARGINAL_BATCH.value
    assert accrual_a["final_adjustment_cents"] == 0
    assert (
        accrual_a["admin_fee_cents"]
        + accrual_a["member_share_cents"]
        + accrual_a["gpo_retention_cents"]
    ) == 7541, "226 + 5486 + 1829 == 7541"


def test_percent_of_spend_exact_line_still_rounds_its_admin_fee_up():
    """The sibling 40-case line's gross is exact at 10054, yet its 300 bps fee
    is 301.62 and must round UP to 302, leaving an exact member share of 7314 on
    net 9752. Both accruals then reconstruct the member's three counters.

    PRD: "**Step five** assigns the residual: `gpo_retention_cents` is
    `net_distributable_cents` minus `member_share_cents`, so the GPO's retention
    absorbs whatever the rounding left behind and the three parts reconstruct the
    gross to the cent."

    Design: Corner/calculations/percent_of_spend_gross_rounds_half_up_at_the_half_cent
    """
    ctx = percent_of_spend_june_normalized()

    line_b = fx.read_line(ctx["line_b"]["id"])
    assert line_b["invoice_extended_cents"] == 365600, "40 cases at 9140"

    validate_success(api_client.accrue_batch(ctx["batch_id"], ANALYST), 200)

    accrual_b = fx.accrual_for_line(ctx["line_b"]["id"])
    assert accrual_b["gross_rebate_cents"] == 10054, (
        "365600 * 275 / 10000 == 10054.0 exactly"
    )
    assert_split(
        accrual_b,
        gross_rebate_cents=10054,
        admin_fee_bps_applied=300,
        admin_fee_cents=302,
        net_distributable_cents=9752,
        member_share_cents=7314,
        gpo_retention_cents=2438,
    )
    assert accrual_b["admin_fee_cents"] == 302, "raw 301.62 rounds UP to 302"
    assert accrual_b["basis"] == AccrualBasis.MARGINAL_BATCH.value
    assert accrual_b["final_adjustment_cents"] == 0
    assert (
        accrual_b["admin_fee_cents"]
        + accrual_b["member_share_cents"]
        + accrual_b["gpo_retention_cents"]
    ) == 10054, "302 + 7314 + 2438 == 10054"

    member = fx.read_member(ctx["member_id"])
    assert_member_ledger(
        member,
        accrued_member_share_cents=12800,
        attributed_gpo_retention_cents=4267,
        attributed_admin_fee_cents=528,
    )
    assert (
        member["accrued_member_share_cents"]
        + member["attributed_gpo_retention_cents"]
        + member["attributed_admin_fee_cents"]
    ) == 17595 == 7541 + 10054


# ==========================================================================
# recovery_allocation_floors_then_gives_the_odd_cent_to_the_larger_claim
# ==========================================================================

def test_recovery_remainder_cent_goes_to_the_larger_overbilling():
    """Two members are overbilled 300 and 80 of 380 and only 300 is recovered.
    Both pro-rata slices floor — 236.84 to 236 and 63.15 to 63 — leaving exactly
    one cent, which goes to the member overbilled 300, so the credits are 237
    and 63 and they re-sum to the recovered total exactly.

    PRD: "Each participating member's provisional slice is the batch's
    `recovered_cents` multiplied by that member's overbilling total, divided by
    the batch's `overbilled_cents`, and floored to whole cents." and "the
    remainder ... is then distributed one cent at a time: members are ordered by
    their overbilling total descending".

    Design: Corner/calculations/recovery_allocation_floors_then_gives_the_odd_cent_to_the_larger_claim
    """
    ctx = two_member_overbilled_june_feed()

    audited = validate_success(api_client.audit_markup(ctx["batch_id"], ANALYST), 200)
    assert audited["audit_status"] == AuditStatus.AUDIT_OVERBILLED.value
    assert audited["overbilled_cents"] == 380
    assert fx.read_line(ctx["line_harbor"]["id"])["overbilled_cents"] == 300, (
        "min(900, 700) == 700 bps on base 8533 allows 9130, so 10 per case over "
        "30 cases"
    )
    assert fx.read_line(ctx["line_pier"]["id"])["overbilled_cents"] == 80, (
        "700 bps on base 8540 allows 9138, so 2 per case over 40 cases"
    )

    requested = validate_success(
        api_client.request_recovery(ctx["batch_id"], ANALYST), 200
    )
    assert requested["audit_status"] == AuditStatus.RECOVERY_REQUESTED.value

    settled = validate_success(
        api_client.settle_recovery(
            ctx["batch_id"],
            {"outcome": RecoveryOutcome.RECOVERED.value, "recovered_cents": 300},
            ADMIN,
        ),
        200,
    )
    assert settled["audit_status"] == AuditStatus.RECOVERED.value
    assert settled["recovered_cents"] == 300

    harbor = fx.read_member(ctx["harbor_id"])
    pier = fx.read_member(ctx["pier_id"])
    assert harbor["recovery_credit_cents"] == 237, (
        "floor(300 * 300 / 380) == 236 plus the single remainder cent, because "
        "300 is the larger overbilling"
    )
    assert pier["recovery_credit_cents"] == 63, (
        "floor(300 * 80 / 380) == 63 and no remainder cent"
    )
    assert harbor["recovery_credit_cents"] + pier["recovery_credit_cents"] == 300, (
        "237 + 63 == 300 == recovered_cents: nothing is lost and nothing is "
        "invented"
    )


def test_recovered_total_credits_the_distributor_not_the_rebate_ledger():
    """The distributor's lifetime counter takes the full 300 — not the 299 the
    floored slices summed to and not the 380 that was overbilled — while both
    members' rebate counters stay at 0 and the normalization dimension of the
    batch never moves.

    PRD: "An outcome of `RECOVERED` stores the supplied `recovered_cents` ...
    credits the overbilled members as described next, and adds `recovered_cents`
    to the distributor's lifetime `overbilled_recovered_cents`."

    Design: Corner/calculations/recovery_allocation_floors_then_gives_the_odd_cent_to_the_larger_claim
    """
    ctx = recovery_requested_june_feed()
    assert ctx["batch"]["overbilled_cents"] == 380

    settled = validate_success(
        api_client.settle_recovery(
            ctx["batch_id"],
            {"outcome": RecoveryOutcome.RECOVERED.value, "recovered_cents": 300},
            ADMIN,
        ),
        200,
    )
    assert settled["audit_status"] == AuditStatus.RECOVERED.value

    distributor = fx.read_distributor(ctx["distributor_id"])
    assert distributor["overbilled_recovered_cents"] == 300, (
        "the full recovery, not the 299 the floored slices summed to and not 380"
    )
    assert distributor["overbilled_recovered_cents"] not in (299, 380)
    assert distributor["status"] == DistributorStatus.ACTIVE.value, (
        "only a written-off settlement suspends a distributor"
    )

    for member_id in (ctx["harbor_id"], ctx["pier_id"]):
        member = fx.read_member(member_id)
        assert member["accrued_member_share_cents"] == 0, (
            "recovery credit is a separate ledger from rebate share"
        )
        assert member["attributed_gpo_retention_cents"] == 0
        assert member["attributed_admin_fee_cents"] == 0

    # The design's own literal says the batch is still RECEIVED here, but the PRD
    # only runs the audit on a NORMALIZED or ACCRUED feed, so the feed was
    # normalized first: what the instance really pins is that neither the audit
    # nor the recovery touched the normalization dimension at all.
    assert settled["normalization_status"] == NormalizationStatus.NORMALIZED.value
    assert settled["matched_cases"] == 0, "no contracted item owns the beef key here"
    assert settled["total_cases_ingested"] == 70


# ==========================================================================
# normalization_eligibility_filters_candidates_by_deal_state_and_dates
# ==========================================================================

def test_a_single_eligible_candidate_matches_and_an_unowned_key_stays_unmatched():
    """Two contracted items share BEEF-PATTY-4OZ-CS40, but the rival's deal is
    DRAFT, so exactly one eligible candidate survives and the line MATCHES
    instead of turning AMBIGUOUS. The POTATO-FRY-CS6 line, whose key nobody
    contracted, stays UNMATCHED with no block reason at all.

    PRD: "When exactly one eligible candidate exists, the line's
    `contracted_item_id` is set to that item, `match_status` becomes `MATCHED`
    and `accrual_block_reason` stays `NONE`." and "When there are no key
    candidates at all — an item key nobody has contracted — the line stays
    `UNMATCHED` with `accrual_block_reason` of `NONE`".

    Design: Corner/calculations/normalization_eligibility_filters_candidates_by_deal_state_and_dates
    """
    ctx = four_arm_key_space()

    batch = validate_success(api_client.normalize_batch(ctx["batch_id"], ANALYST), 200)
    assert batch["normalization_status"] == NormalizationStatus.NORMALIZED.value

    beef_line = fx.read_line(ctx["beef_line"]["id"])
    assert beef_line["match_status"] == MatchStatus.MATCHED.value, (
        "the rival key owner sits under a DRAFT deal, so it is a key candidate "
        "but never an eligible one and the line is not AMBIGUOUS"
    )
    assert beef_line["match_status"] != MatchStatus.AMBIGUOUS.value
    assert beef_line["contracted_item_id"] == ctx["beef_item_id"]
    assert beef_line["contracted_item_id"] != ctx["rival_beef_item_id"]
    assert beef_line["accrual_block_reason"] == AccrualBlockReason.NONE.value

    fry_line = fx.read_line(ctx["fry_line"]["id"])
    assert fry_line["match_status"] == MatchStatus.UNMATCHED.value, (
        "no item anywhere owns POTATO-FRY-CS6, so it is unmatched rather than "
        "excluded"
    )
    assert fry_line["contracted_item_id"] is None
    assert fry_line["accrual_block_reason"] == AccrualBlockReason.NONE.value

    assert batch["total_cases_ingested"] == 75, "30 + 10 + 15 + 20"
    assert batch["matched_cases"] == 30
    assert batch["unmatched_cases"] == 45, (
        "the UNMATCHED, AMBIGUOUS and EXCLUDED lines together"
    )


def test_a_draft_deal_candidate_excludes_the_line_as_deal_not_active():
    """BEEF-BRISKET-CS20's only owner is an ACTIVE item under a DRAFT deal, so
    key candidates exist but none is eligible: the line is EXCLUDED with
    DEAL_NOT_ACTIVE and its contracted_item_id stays null.

    PRD: "And when key candidates exist but none is eligible, `match_status`
    becomes `EXCLUDED` and `accrual_block_reason` records why: `ITEM_DELISTED`
    when every key candidate has `status` of `DELISTED`, and `DEAL_NOT_ACTIVE`
    otherwise."

    Design: Corner/calculations/normalization_eligibility_filters_candidates_by_deal_state_and_dates
    """
    ctx = four_arm_key_space()

    validate_success(api_client.normalize_batch(ctx["batch_id"], ANALYST), 200)

    brisket_item = fx.read_item(ctx["brisket_item_id"])
    assert brisket_item["status"] == ItemStatus.ACTIVE.value
    assert fx.read_deal(ctx["rival_deal_id"])["status"] == DealStatus.DRAFT.value

    brisket_line = fx.read_line(ctx["brisket_line"]["id"])
    assert brisket_line["match_status"] == MatchStatus.EXCLUDED.value, (
        "the item is ACTIVE but its deal never went live, so the only candidate "
        "is ineligible and the line is EXCLUDED rather than UNMATCHED"
    )
    assert brisket_line["match_status"] != MatchStatus.UNMATCHED.value
    assert brisket_line["contracted_item_id"] is None
    assert brisket_line["accrual_block_reason"] == (
        AccrualBlockReason.DEAL_NOT_ACTIVE.value
    )


def test_deal_dates_that_miss_the_invoice_date_also_exclude_the_line():
    """CHIX-TENDER-CS30's owner is ACTIVE and its deal is ACTIVE, yet the deal's
    2027-01-01..2027-12-31 range does not contain the 2026-06-07 invoice date, so
    the line is still EXCLUDED with DEAL_NOT_ACTIVE. Both gates bite
    independently.

    PRD: "Then it narrows those to the **eligible candidates**: the key
    candidates whose own `status` is `ACTIVE`, whose deal's `status` is `ACTIVE`,
    and whose deal's inclusive `effective_from` through `effective_to` range
    contains the line's `invoice_date`."

    Design: Corner/calculations/normalization_eligibility_filters_candidates_by_deal_state_and_dates
    """
    ctx = four_arm_key_space()

    validate_success(api_client.normalize_batch(ctx["batch_id"], ANALYST), 200)

    chicken_item = fx.read_item(ctx["chicken_item_id"])
    assert chicken_item["status"] == ItemStatus.ACTIVE.value
    deal_2027 = fx.read_deal(ctx["deal_2027_id"])
    assert deal_2027["status"] == DealStatus.ACTIVE.value, (
        "the item is ACTIVE and its deal is ACTIVE — only the dates lose"
    )
    assert deal_2027["effective_from"] == DEAL_2027_FROM
    assert deal_2027["effective_to"] == DEAL_2027_TO

    chicken_line = fx.read_line(ctx["chicken_line"]["id"])
    assert chicken_line["invoice_date"] == "2026-06-07"
    assert chicken_line["match_status"] == MatchStatus.EXCLUDED.value
    assert chicken_line["contracted_item_id"] is None
    assert chicken_line["accrual_block_reason"] == (
        AccrualBlockReason.DEAL_NOT_ACTIVE.value
    )


def test_only_the_gaining_deal_records_a_last_purchase_date():
    """Only PBC-2026 gained a MATCHED line, so only its last_purchase_date moves
    — to 2026-06-05 — while the 2027 deal and the DRAFT rival stay null. The
    following accrual run then produces exactly one accrual, worth 30 * 150.

    PRD: "Every manufacturer deal that gained a matched line also has its
    `last_purchase_date` refreshed to the greatest `invoice_date` among the lines
    matched to that deal's items."

    Design: Corner/calculations/normalization_eligibility_filters_candidates_by_deal_state_and_dates
    """
    ctx = four_arm_key_space()

    validate_success(api_client.normalize_batch(ctx["batch_id"], ANALYST), 200)

    assert fx.read_deal(ctx["deal_id"])["last_purchase_date"] == "2026-06-05"
    assert fx.read_deal(ctx["deal_2027_id"])["last_purchase_date"] is None
    assert fx.read_deal(ctx["rival_deal_id"])["last_purchase_date"] is None

    validate_success(api_client.accrue_batch(ctx["batch_id"], ANALYST), 200)

    every_accrual, meta = validate_paginated(
        api_client.list_accruals(ANALYST, {"limit": C.MAX_LIMIT})
    )
    assert meta["total_count"] == 1, "only the one MATCHED line monetizes"
    assert every_accrual[0]["purchase_line_id"] == ctx["beef_line"]["id"]
    assert every_accrual[0]["gross_rebate_cents"] == 4500, "30 cases at 150"


# ==========================================================================
# prorated_commitment_uses_a_365_day_year_and_counts_both_endpoints
# ==========================================================================

def test_a_single_day_window_counts_one_day_and_prorates_by_a_365_day_year():
    """A window whose start and end are both 2026-01-15 is one day long, so the
    20000000 cent annual promise prorates to 54795 and the January line's 274200
    of contracted spend floors to a 50041 bps ratio — a comfortable PASS that
    leaves the member untouched.

    PRD: "`window_days` is the number of days from `window_start` to
    `window_end` with **both endpoints counted**, so a window whose start and end
    are the same date is 1 day long." and "it is `committed_annual_spend_cents`
    multiplied by `window_days`, divided by 365, and rounded half up".

    Design: Corner/calculations/prorated_commitment_uses_a_365_day_year_and_counts_both_endpoints
    """
    ctx = january_matched_feed()
    before = fx.read_member(ctx["member_id"])

    review = validate_success(
        api_client.create_compliance_review(
            F.compliance_review_payload(
                ctx["member_id"], ctx["deal_id"], JAN_INVOICE_DATE, JAN_INVOICE_DATE
            ),
            ANALYST,
        ),
        201,
    )

    assert review["window_days"] == 1, (
        "a single-day closed window counts one day, not zero"
    )
    assert review["committed_spend_prorated_cents"] == 54795, (
        "round_half_up(20000000 / 365) == 54795"
    )
    assert review["contracted_spend_cents"] == 274200
    assert review["deal_wide_contracted_spend_cents"] == 274200
    assert review["purchase_ratio_bps"] == 50041, (
        "floor(274200 * 10000 / 54795) == 50041"
    )
    assert review["result"] == ComplianceResult.PASS.value
    assert review["triggered_deal_loss"] is False, (
        "deal_wide_contracted_spend_cents is non-zero, so the DEAL_LOST branch "
        "cannot fire"
    )

    after = fx.read_member(ctx["member_id"])
    assert after["enrollment_status"] == MemberEnrollmentStatus.ACTIVE.value
    assert after["payout_hold"] is False
    assert after["version"] == before["version"], "a PASS changes nothing"
    assert fx.read_deal(ctx["deal_id"])["status"] == DealStatus.ACTIVE.value


def test_a_thirty_one_day_window_prorates_to_1698630_and_breaches():
    """The same 274200 of contracted spend over the whole of January prorates
    the commitment to 1698630 — 366 days would give 1693989 and dropping the
    inclusive endpoint 1643836 — so the floored ratio is 1614 bps and the verdict
    flips to BREACH, suspending the member and holding its payouts.

    PRD: "otherwise `contracted_spend_cents` multiplied by 10000, divided by
    `committed_spend_prorated_cents`, and **floored**" and "A `BREACH` costs the
    member its standing: it moves `ACTIVE → SUSPENDED`, its `payout_hold` is set
    to true and its `version` is incremented by 1".

    Design: Corner/calculations/prorated_commitment_uses_a_365_day_year_and_counts_both_endpoints
    """
    ctx = january_matched_feed()
    passing = fx.create_review(
        ctx["member_id"], ctx["deal_id"], JAN_INVOICE_DATE, JAN_INVOICE_DATE,
        headers=ANALYST,
    )
    assert passing["result"] == ComplianceResult.PASS.value

    review = validate_success(
        api_client.create_compliance_review(
            F.compliance_review_payload(
                ctx["member_id"], ctx["deal_id"], JAN_START, JAN_END
            ),
            ANALYST,
        ),
        201,
    )

    assert review["window_days"] == 31
    assert review["committed_spend_prorated_cents"] == 1698630, (
        "round_half_up(20000000 * 31 / 365) == 1698630"
    )
    assert review["committed_spend_prorated_cents"] not in (1693989, 1643836), (
        "a 366-day year gives 1693989 and omitting the inclusive day gives 1643836"
    )
    assert review["contracted_spend_cents"] == 274200
    assert review["deal_wide_contracted_spend_cents"] == 274200
    assert review["purchase_ratio_bps"] == 1614, (
        "floor(2742000000 / 1698630) == 1614"
    )
    assert review["result"] == ComplianceResult.BREACH.value
    assert review["triggered_deal_loss"] is False
    assert review["contracted_spend_cents"] == passing["contracted_spend_cents"], (
        "both rows carry the same contracted spend, so the verdict difference is "
        "produced purely by the prorating constants"
    )

    member = fx.read_member(ctx["member_id"])
    assert member["enrollment_status"] == MemberEnrollmentStatus.SUSPENDED.value
    assert member["payout_hold"] is True
    assert fx.read_deal(ctx["deal_id"])["status"] == DealStatus.ACTIVE.value


# ==========================================================================
# accrual_prices_a_line_from_the_approved_card_not_the_superseded_one
# ==========================================================================

def test_supersede_truncates_the_incumbent_to_the_day_before():
    """Proposing the 150 cent card from 2026-06-01 with supersede true rewrites
    the 100 cent incumbent's effective_to to 2026-05-31, flips it to SUPERSEDED
    and points the new card back at it, and the item ends with exactly one
    approved card after the decrement and the re-approval.

    PRD: "the incumbent's `effective_to` is rewritten to the new card's
    `effective_from` minus one calendar day, the incumbent moves
    `APPROVED → SUPERSEDED`, the new card's `supersedes_rate_card_id` is set to
    the incumbent's `id`, and the item's `approved_rate_card_count` is
    decremented by 1."

    Design: Corner/calculations/accrual_prices_a_line_from_the_approved_card_not_the_superseded_one
    """
    ctx = superseded_card_program()

    old_card = validate_success(
        api_client.get_rate_card(ctx["old_card"]["id"], ADMIN), 200
    )
    assert old_card["status"] == RateCardStatus.SUPERSEDED.value
    assert old_card["effective_to"] == TRUNCATED_EFFECTIVE_TO, (
        "2026-06-01 minus one calendar day"
    )
    assert old_card["flat_rate_cents_per_case"] == OLD_RATE_CENTS_PER_CASE

    new_card = validate_success(
        api_client.get_rate_card(ctx["new_card"]["id"], ADMIN), 200
    )
    assert new_card["status"] == RateCardStatus.APPROVED.value
    assert new_card["supersedes_rate_card_id"] == ctx["old_card"]["id"]
    assert new_card["effective_from"] == NEW_CARD_FROM

    item = fx.read_item(ctx["item_id"])
    assert item["approved_rate_card_count"] == 1, (
        "decremented by the supersede, re-incremented by approving the new card"
    )


def test_accrual_never_prices_a_line_from_a_superseded_card():
    """The June line prices at the new 150 while the May line — MATCHED, and
    inside the incumbent's truncated 2026-01-01..2026-05-31 window — gets no
    accrual at all and carries NO_RATE_CARD, because a SUPERSEDED card is not
    selectable on any date.

    PRD: "Cards in `PROPOSED`, `SUPERSEDED` or `EXPIRED` status are never
    selectable no matter how well their dates fit." and "When no candidate
    survives, the line is given `accrual_block_reason` of `NO_RATE_CARD` and
    produces no accrual, while the rest of the run proceeds."

    Design: Corner/calculations/accrual_prices_a_line_from_the_approved_card_not_the_superseded_one
    """
    ctx = superseded_card_program()
    assert ctx["batch"]["matched_cases"] == 50, "both lines matched the beef item"

    validate_success(api_client.accrue_batch(ctx["batch_id"], ANALYST), 200)

    june_rows, june_meta = accrual_rows_for_line(ctx["june_line"]["id"])
    assert june_meta["total_count"] == 1
    accrual = june_rows[0]
    assert accrual["rate_card_id"] == ctx["new_card"]["id"]
    assert accrual["gross_rebate_cents"] == 4500, "30 cases at the new 150"
    assert accrual["member_share_cents"] == 3274, (
        "300 bps of 4500 is 135, and 75% of the 4365 net rounds half up to 3274"
    )

    may_rows, may_meta = accrual_rows_for_line(ctx["may_line"]["id"])
    assert may_meta["total_count"] == 0, "the May line produced no accrual at all"
    assert may_rows == []

    may_line = fx.read_line(ctx["may_line"]["id"])
    assert may_line["match_status"] == MatchStatus.MATCHED.value, (
        "the line keeps its match; only the pricing is blocked"
    )
    assert may_line["accrual_block_reason"] == AccrualBlockReason.NO_RATE_CARD.value

    every_accrual, meta = validate_paginated(
        api_client.list_accruals(ANALYST, {"limit": C.MAX_LIMIT})
    )
    assert meta["total_count"] == 1
    assert all(
        a["rate_card_id"] != ctx["old_card"]["id"] for a in every_accrual
    ), "no accrual may cite the superseded card"
    assert all(a["gross_rebate_cents"] != 2000 for a in every_accrual), (
        "20 cases at the old 100 per case appears nowhere"
    )
    assert fx.read_member(ctx["member_id"])["accrued_member_share_cents"] == 3274


# ==========================================================================
# savings_report_defaults_the_basis_to_as_purchased
# ==========================================================================

def test_savings_report_omitting_the_basis_computes_as_purchased():
    """A request that omits basis echoes AS_PURCHASED and measures opportunity
    over the MATCHED lines only: 46200 of price savings plus 7639 of rebate is
    53839 realized against 63000 available, so 9161 was missed and the floored
    capture rate is 8545 basis points.

    PRD: "an optional `basis`, which is either `AS_PURCHASED` or `FULL_BASKET`
    and defaults to `AS_PURCHASED` when omitted." and "`capture_rate_bps` is 0
    when `opportunity_cents` is zero or negative, and otherwise `realized_cents`
    multiplied by 10000, divided by `opportunity_cents`, and floored to a whole
    basis point."

    Design: Corner/calculations/savings_report_defaults_the_basis_to_as_purchased
    """
    ctx = june_accrued_with_an_unowned_key_line()
    member_headers = make_member_operator_headers(ctx["member_id"])

    response = api_client.get_savings_report(
        ctx["member_id"],
        member_headers,
        F.savings_report_params(C.JUNE_START, C.JUNE_END),
    )
    report = validate_success(response, 200)

    assert report["basis"] == SavingsBasis.AS_PURCHASED.value, (
        "the omitted basis defaults to AS_PURCHASED and is echoed back"
    )
    assert report["member_id"] == ctx["member_id"]
    assert report["period_start"] == C.JUNE_START
    assert report["period_end"] == C.JUNE_END

    assert report["rebate_member_share_cents"] == 7639, (
        "the June accruals paid 3274 on the 30-case line and 4365 on the 40-case"
    )
    assert report["realized_cents"] == 53839, (
        "(9800 - 9140) * 70 == 46200 of price savings plus 7639 of rebate"
    )
    assert report["opportunity_cents"] == 63000, (
        "(9800 - 8900) * 900 bps spread over the 70 MATCHED cases only"
    )
    assert report["missed_opportunity_cents"] == 9161 == 63000 - 53839
    assert report["capture_rate_bps"] == 8545, (
        "floor(53839 * 10000 / 63000) is 8545, never the 8546 a half-up would give"
    )
    assert report["recovery_credit_cents"] == 0, "nothing was ever recovered"


def test_savings_report_counts_the_unmatched_line_in_spend_but_not_the_ratio():
    """The 20 fries cases report a key no item owns, so they land in
    unmatched_cases and in invoice_spend_cents while contributing to neither
    realized nor opportunity — the report cannot quietly drop off-contract volume.

    PRD: "`invoice_spend_cents` is the sum of `invoice_extended_cents` over
    **all** the member's period lines regardless of match status." and "an
    unmatched or excluded line contributes to neither side of the comparison."

    Design: Corner/calculations/savings_report_defaults_the_basis_to_as_purchased
    """
    ctx = june_accrued_with_an_unowned_key_line()
    member_headers = make_member_operator_headers(ctx["member_id"])

    fry_line = fx.read_line(ctx["fry_line"]["id"])
    assert fry_line["match_status"] == MatchStatus.UNMATCHED.value
    assert fry_line["invoice_extended_cents"] == 166_000 == 20 * 8300

    report = validate_success(
        api_client.get_savings_report(
            ctx["member_id"],
            member_headers,
            F.savings_report_params(C.JUNE_START, C.JUNE_END),
        ),
        200,
    )

    assert report["matched_cases"] == 70, "only the two beef lines matched"
    assert report["unmatched_cases"] == 20, "the fries line is counted, not dropped"
    assert report["invoice_spend_cents"] == 805_800 == 70 * 9140 + 20 * 8300
    assert report["realized_cents"] == 53839, (
        "the unmatched cases add nothing to realized savings"
    )
    assert report["opportunity_cents"] == 63000, (
        "and nothing to the AS_PURCHASED opportunity either"
    )


def test_explicit_as_purchased_and_full_basket_agree_on_this_data():
    """Asking for AS_PURCHASED explicitly reproduces the defaulted body figure
    for figure, and FULL_BASKET returns the same numbers here because the only
    non-matched line is UNMATCHED, a status the FULL_BASKET basis set never adds.

    PRD: "Under `FULL_BASKET`, the basis set additionally includes the member's
    `AMBIGUOUS` and `EXCLUDED` period lines"

    Design: Corner/calculations/savings_report_defaults_the_basis_to_as_purchased
    """
    ctx = june_accrued_with_an_unowned_key_line()
    member_headers = make_member_operator_headers(ctx["member_id"])
    figures = (
        "basis",
        "member_id",
        "period_start",
        "period_end",
        "realized_cents",
        "rebate_member_share_cents",
        "opportunity_cents",
        "missed_opportunity_cents",
        "capture_rate_bps",
        "matched_cases",
        "unmatched_cases",
        "invoice_spend_cents",
        "recovery_credit_cents",
    )

    defaulted = validate_success(
        api_client.get_savings_report(
            ctx["member_id"],
            member_headers,
            F.savings_report_params(C.JUNE_START, C.JUNE_END),
        ),
        200,
    )
    explicit = validate_success(
        api_client.get_savings_report(
            ctx["member_id"],
            member_headers,
            F.savings_report_params(
                C.JUNE_START, C.JUNE_END, SavingsBasis.AS_PURCHASED.value
            ),
        ),
        200,
    )
    assert explicit == defaulted, (
        "the explicit AS_PURCHASED body is identical to the defaulted one"
    )

    full_basket = validate_success(
        api_client.get_savings_report(
            ctx["member_id"],
            member_headers,
            F.savings_report_params(
                C.JUNE_START, C.JUNE_END, SavingsBasis.FULL_BASKET.value
            ),
        ),
        200,
    )
    assert full_basket["basis"] == SavingsBasis.FULL_BASKET.value
    for field in figures:
        if field == "basis":
            continue
        assert full_basket[field] == defaulted[field], (
            f"{field} must not move: the UNMATCHED fries line is outside both "
            "basis sets"
        )
    assert full_basket["opportunity_cents"] == 63000
    assert full_basket["capture_rate_bps"] == 8545


def test_savings_report_over_an_empty_period_guards_the_capture_rate_division():
    """July holds none of this member's lines, so every figure is zero and
    capture_rate_bps is 0 rather than a division by a zero opportunity, while the
    non-period-scoped recovery credit stays 0 too.

    PRD: "`capture_rate_bps` is 0 when `opportunity_cents` is zero or negative"

    Design: Corner/calculations/savings_report_defaults_the_basis_to_as_purchased
    """
    ctx = june_accrued_with_an_unowned_key_line()
    member_headers = make_member_operator_headers(ctx["member_id"])

    report = validate_success(
        api_client.get_savings_report(
            ctx["member_id"],
            member_headers,
            F.savings_report_params(C.JULY_START, C.JULY_END),
        ),
        200,
    )

    assert report["basis"] == SavingsBasis.AS_PURCHASED.value
    assert report["period_start"] == C.JULY_START
    assert report["period_end"] == C.JULY_END
    assert report["realized_cents"] == 0
    assert report["rebate_member_share_cents"] == 0
    assert report["opportunity_cents"] == 0
    assert report["missed_opportunity_cents"] == 0, "floored at zero, never negative"
    assert report["capture_rate_bps"] == 0, "the zero opportunity guards the division"
    assert report["matched_cases"] == 0
    assert report["unmatched_cases"] == 0
    assert report["invoice_spend_cents"] == 0
    assert report["recovery_credit_cents"] == 0
