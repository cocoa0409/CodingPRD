"""Endpoint corners and the immediate-consistency contract.

Five endpoint instances and one consistency-model instance. The endpoint group
pins behaviour that only shows up at an endpoint's own boundary: the savings
report is a pure projection that must answer differently once a compensating
renormalize unwound its inputs, accrue is all-or-skip rather than
all-or-nothing, a manual map is legal only into the line's own eligible
candidate set, settle-recovery makes one optional field conditionally mandatory
and conditionally forbidden, and revoking a letter closes the data feed for that
member alone. The consistency instance pins the PRD's promise that a write is
visible in its OWN response body and in the very next read of every other row it
touched, with no polling and no refresh step.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ANALYST_1,
    AccrualBlockReason,
    AccrualStatus,
    ApiErrorId,
    AuditStatus,
    DistributorStatus,
    LetterStatus,
    MatchStatus,
    MemberEnrollmentStatus,
    NormalizationStatus,
    RecoveryOutcome,
    ReversalReason,
    api_client,
    assert_accrual,
    assert_authorization_letter,
    assert_case_conservation,
    assert_distributor,
    assert_instants_equal,
    assert_member,
    assert_member_ledger,
    assert_purchase_batch,
    assert_purchase_line,
    assert_split,
    make_analyst_headers,
    make_distributor_feed_headers,
    make_gpo_admin_headers,
    make_member_operator_headers,
)
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx

ADMIN = make_gpo_admin_headers()
ANALYST = make_analyst_headers(ANALYST_1)

# ---------------------------------------------- the canonical PER_CASE split ----
# 30 cases at 150 cents: gross 4500, fee 300 bps (ytd snapshot 0 < 5,000,000),
# fee 135, net 4365, share round_half_up(4365 * 7500 / 10000) == 3274,
# retention 4365 - 3274 == 1091.
ADMIN_FEE_BPS_LOW = 300
GROSS_A = 4500
FEE_A = 135
NET_A = 4365
SHARE_A = 3274
RETENTION_A = 1091

# 40 cases at 150 cents: gross 6000, fee 180, net 5820, share 4365, retention 1455.
GROSS_B = 6000
FEE_B = 180
NET_B = 5820
SHARE_B = 4365
RETENTION_B = 1455

LEDGER_SHARE = 7639        # 3274 + 4365
LEDGER_RETENTION = 2546    # 1091 + 1455
LEDGER_FEE = 315           # 135 + 180

# ------------------------------------------------ the June savings projection ----
REALIZED_CENTS = 53839         # 46200 hard price savings + 7639 rebate share
HARD_PRICE_SAVINGS = 46200     # (9800 - 9140) * 30 + (9800 - 9140) * 40
OPPORTUNITY_CENTS = 63000      # (9800 - 8900) * 70
MISSED_OPPORTUNITY_CENTS = 9161
CAPTURE_RATE_BPS = 8545        # floor(53839 * 10000 / 63000)
INVOICE_SPEND_CENTS = 639800   # 30 * 9140 + 40 * 9140
JUNE_MATCHED_CASES = 70
EARLY_JUNE_END = "2026-06-04"  # strictly before both invoice dates

# ------------------------------------------------------- the all-or-skip batch ----
MAY_START = "2026-05-01"
Q2B_REFERENCE = "METRO-2026-Q2B"
OUT_OF_CARD_WINDOW_CASES = 20
OUT_OF_CARD_WINDOW_DATE = "2026-05-20"
NO_KEY_CANDIDATE_KEY = "POTATO-FRY-CS6"
NO_KEY_CANDIDATE_SKU = "MF-55300"
NO_KEY_CANDIDATE_DESCRIPTION = "Shoestring fries 6ct"
NO_KEY_CANDIDATE_CASES = 15
NO_KEY_CANDIDATE_UNIT_COST = 8300
NO_KEY_CANDIDATE_BASE_COST = 8000
NO_KEY_CANDIDATE_DATE = "2026-06-08"
Q2B_TOTAL_CASES = 105          # 30 + 40 + 20 + 15
Q2B_MATCHED_CASES = 90         # the three beef lines
Q2B_UNMATCHED_CASES = 15       # the un-contracted key

# ------------------------------------------------------- the two-candidate map ----
BRISKET_SKU = "PBC-BRISKET"
BRISKET_KEY = "BEEF-BRISKET-CS20"
RIVAL_MANUFACTURER = "Rival Beef LLC"
RIVAL_DEAL_CODE = "RVL-2026"
RIVAL_SKU = "RVL-PATTY-4OZ"
RIVAL_RATE_CENTS = 220
# 30 cases at 220: gross 6600, fee 198, net 6402,
# share round_half_up(6402 * 7500 / 10000) == round_half_up(4801.5) == 4802,
# retention 6402 - 4802 == 1600.
RIVAL_GROSS = 6600
RIVAL_FEE = 198
RIVAL_NET = 6402
RIVAL_SHARE = 4802
RIVAL_RETENTION = 1600

# -------------------------------------------------------- the markup recovery ----
# allowed markup == min(distributor 900, tier cap 700) == 700 bps.
# line A: 8533 + round_half_up(8533 * 700 / 10000) == 8533 + 597 == 9130,
#         excess 9140 - 9130 == 10, overbilled 10 * 30 == 300.
# line B: 8540 + round_half_up(8540 * 700 / 10000) == 8540 + 598 == 9138,
#         excess 9140 - 9138 == 2, overbilled 2 * 40 == 80.
OVERBILLED_A = 300
OVERBILLED_B = 80
BATCH_OVERBILLED = 380
RECOVERED_CENTS = 200
REJECTED_WRITE_OFF_CENTS = 100

# ------------------------------------------------------------ the second member ----
PIER9_LEGAL_NAME = "Pier 9 Oyster Bar Inc"
PIER9_COMMITTED_SPEND_CENTS = 9_000_000
PIER9_SIGNATORY = "T Okafor"

# --------------------------------------------------------- the consistency clock ----
CONSISTENCY_CLOCK = "2026-08-01T09:00:00.000Z"
CONSISTENCY_SIGNATORY = "Dana Reyes"
CONSISTENCY_LETTER_TO = "2027-01-01T00:00:00.000Z"


# ============================================================= local helpers ====
# test_helpers must not be edited, so the composites these six instances need
# that fixtures.py does not offer are built here out of its phased hops.


def _report(member_id: str, period_start: str, period_end: str, headers: dict = None):
    """The raw savings-report response, so status and body are both assertable."""
    return api_client.get_savings_report(
        member_id,
        headers or ADMIN,
        F.savings_report_params(period_start, period_end),
    )


def _program_without_a_deal(**tier_overrides) -> dict:
    """An ACTIVE member holding an ACTIVE PURCHASE_DATA_AND_PRICING letter.

    No manufacturer deal, no contracted item and no rate card: the markup audit
    and the letter/ingest gates never read any of them.
    """
    tier = fx.create_tier(**tier_overrides)
    distributor = fx.create_distributor()
    member = fx.create_member(tier["id"])
    letter = fx.submit_letter(member["id"], distributor["id"])
    letter = fx.countersign_letter(letter["id"], distributor["id"])
    member = fx.activate_member(member["id"])
    return {
        "tier": tier,
        "tier_id": tier["id"],
        "distributor": distributor,
        "distributor_id": distributor["id"],
        "member": member,
        "member_id": member["id"],
        "letter": letter,
        "letter_id": letter["id"],
    }


def _recovery_requested_june_batch() -> dict:
    """Two June lines overbilled 300 and 80, audited and demanded.

    The feed is normalized first because the PRD runs the markup audit only on a
    batch "whose `normalization_status` is either `NORMALIZED` or `ACCRUED`".
    With no contracted item in the system both lines stay UNMATCHED, which the
    audit ignores: it visits every line "regardless of `match_status`".
    """
    ctx = _program_without_a_deal()
    batch = fx.create_batch(ctx["distributor_id"])
    ctx["batch_id"] = batch["id"]
    ctx["line_a"] = fx.create_line(batch["id"], ctx["member_id"], ctx["distributor_id"])
    ctx["line_b"] = fx.create_line_b(batch["id"], ctx["member_id"], ctx["distributor_id"])
    fx.normalize(batch["id"])
    fx.audit_markup(batch["id"])
    ctx["batch"] = fx.request_recovery(batch["id"])
    return ctx


def _two_members_one_open_feed() -> dict:
    """Harbor Grill and Pier 9, both ACTIVE with an ACTIVE letter for METRO-01,
    plus one RECEIVED June batch on that distributor."""
    ctx = _program_without_a_deal()
    member_2 = fx.create_member(
        ctx["tier_id"],
        legal_name=PIER9_LEGAL_NAME,
        committed_annual_spend_cents=PIER9_COMMITTED_SPEND_CENTS,
    )
    letter_2 = fx.submit_letter(
        member_2["id"], ctx["distributor_id"], signatory_name=PIER9_SIGNATORY
    )
    letter_2 = fx.countersign_letter(letter_2["id"], ctx["distributor_id"])
    ctx["member_2"] = fx.activate_member(member_2["id"])
    ctx["member_2_id"] = member_2["id"]
    ctx["letter_2"] = letter_2
    batch = fx.create_batch(ctx["distributor_id"])
    ctx["batch"] = batch
    ctx["batch_id"] = batch["id"]
    return ctx


def _all_or_skip_batch() -> dict:
    """A 2026-05-01..2026-06-30 feed of four lines, normalized but not accrued.

    The only APPROVED card covers 2026-06-01..2026-06-30, so the 2026-05-20 beef
    line is MATCHED with no selectable card, and the POTATO-FRY-CS6 line has no
    key candidate at all.
    """
    ctx = fx.setup_flat_program(
        card_overrides={"effective_from": C.JUNE_START, "effective_to": C.JUNE_END}
    )
    batch = fx.create_batch(
        ctx["distributor_id"],
        period_start=MAY_START,
        period_end=C.JUNE_END,
        source_reference=Q2B_REFERENCE,
    )
    ctx["batch"] = batch
    ctx["batch_id"] = batch["id"]
    ctx["line_a"] = fx.create_line(batch["id"], ctx["member_id"], ctx["distributor_id"])
    ctx["line_b"] = fx.create_line_b(batch["id"], ctx["member_id"], ctx["distributor_id"])
    ctx["line_c"] = fx.create_line(
        batch["id"],
        ctx["member_id"],
        ctx["distributor_id"],
        cases_shipped=OUT_OF_CARD_WINDOW_CASES,
        invoice_date=OUT_OF_CARD_WINDOW_DATE,
    )
    ctx["line_d"] = fx.create_line(
        batch["id"],
        ctx["member_id"],
        ctx["distributor_id"],
        distributor_sku=NO_KEY_CANDIDATE_SKU,
        vendor_item_description=NO_KEY_CANDIDATE_DESCRIPTION,
        normalized_item_key_reported=NO_KEY_CANDIDATE_KEY,
        cases_shipped=NO_KEY_CANDIDATE_CASES,
        invoice_unit_cost_cents=NO_KEY_CANDIDATE_UNIT_COST,
        distributor_base_cost_cents=NO_KEY_CANDIDATE_BASE_COST,
        invoice_date=NO_KEY_CANDIDATE_DATE,
    )
    ctx["batch"] = fx.normalize(batch["id"])
    return ctx


def _ambiguous_line_with_two_candidates() -> dict:
    """One 30-case beef line that two ACTIVE deals both price.

    PBC-2026 carries the 150-cent card, RVL-2026 the 220-cent card, and PBC-2026
    also carries a brisket item that is ACTIVE under an ACTIVE deal covering the
    invoice date but whose normalized key is different.
    """
    ctx = fx.setup_flat_program()
    ctx["item_c"] = fx.create_item(
        ctx["deal_id"],
        manufacturer_sku=BRISKET_SKU,
        normalized_item_key=BRISKET_KEY,
        pack_size=20,
        baseline_unit_cost_cents=14200,
        contract_unit_cost_cents=13100,
    )
    deal_b = fx.create_deal(
        manufacturer_name=RIVAL_MANUFACTURER,
        deal_code=RIVAL_DEAL_CODE,
        required_purchase_window_days=90,
    )
    item_b = fx.create_item(
        deal_b["id"],
        manufacturer_sku=RIVAL_SKU,
        normalized_item_key=C.BEEF_KEY,
        pack_size=C.BEEF_PACK_SIZE,
        baseline_unit_cost_cents=9700,
        contract_unit_cost_cents=8850,
    )
    ctx["card_b"] = fx.approved_card(
        item_b["id"], flat_rate_cents_per_case=RIVAL_RATE_CENTS
    )
    ctx["deal_b"] = fx.activate_deal(deal_b["id"])
    ctx["item_b"] = item_b
    fx.ingest_june_feed(ctx, second_line=False)
    ctx["batch"] = fx.normalize_june_feed(ctx)["batch"]
    return ctx


def _consistency_program() -> dict:
    """Clock at 09:00, a PENDING member with a SUBMITTED letter, an ACTIVE deal."""
    fx.set_clock(CONSISTENCY_CLOCK)
    tier = fx.create_tier()
    distributor = fx.create_distributor()
    member = fx.create_member(tier["id"])
    letter = fx.submit_letter(
        member["id"],
        distributor["id"],
        headers=ADMIN,
        signatory_name=CONSISTENCY_SIGNATORY,
        effective_to=CONSISTENCY_LETTER_TO,
    )
    deal = fx.create_deal()
    item = fx.create_item(deal["id"])
    card = fx.approved_card(item["id"])
    deal = fx.activate_deal(deal["id"])
    return {
        "tier": tier,
        "distributor": distributor,
        "distributor_id": distributor["id"],
        "member": member,
        "member_id": member["id"],
        "letter": letter,
        "letter_id": letter["id"],
        "deal": deal,
        "deal_id": deal["id"],
        "item": item,
        "item_id": item["id"],
        "card": card,
    }


# ================================================== savings report vs renormalize ====
# Instance: savings_report_drops_everything_a_renormalize_unwound


def test_savings_report_projects_both_sides_of_the_ratio_before_the_renormalize():
    """The accrued June feed's report: 46200 of hard price savings plus the 7639
    rebate share against 63000 of opportunity on 70 MATCHED cases.

    PRD §3.9: "`capture_rate_bps` is 0 when `opportunity_cents` is zero or
    negative, and otherwise `realized_cents` multiplied by 10000, divided by
    `opportunity_cents`, and floored to a whole basis point."

    Design: Corner/endpoints/savings_report_drops_everything_a_renormalize_unwound
    """
    ctx = fx.setup_june_accrued()
    assert_member_ledger(
        fx.read_member(ctx["member_id"]), LEDGER_SHARE, LEDGER_RETENTION, LEDGER_FEE
    )

    response = _report(ctx["member_id"], C.JUNE_START, C.JUNE_END)
    report = validate_success(response, 200)

    assert report["realized_cents"] == REALIZED_CENTS
    assert report["realized_cents"] == HARD_PRICE_SAVINGS + LEDGER_SHARE
    assert report["rebate_member_share_cents"] == LEDGER_SHARE
    assert report["opportunity_cents"] == OPPORTUNITY_CENTS
    assert report["missed_opportunity_cents"] == MISSED_OPPORTUNITY_CENTS
    assert report["capture_rate_bps"] == CAPTURE_RATE_BPS
    assert report["matched_cases"] == JUNE_MATCHED_CASES
    assert report["unmatched_cases"] == 0
    assert report["invoice_spend_cents"] == INVOICE_SPEND_CENTS


def test_savings_report_drops_realized_and_opportunity_after_the_renormalize():
    """Renormalize the accrued feed and read the same URL again: both accruals are
    REVERSED and both lines are UNMATCHED, so every contract-attributed figure is 0.

    PRD §3.3: "Every accrual of the batch whose `status` is `ACCRUED` or
    `FLAGGED` moves to `REVERSED` with `reversal_reason` set to `RENORMALIZED`".
    PRD §3.9: "Accruals in `REVERSED` status never count toward realized savings."

    Design: Corner/endpoints/savings_report_drops_everything_a_renormalize_unwound
    """
    ctx = fx.setup_june_accrued()
    before = validate_success(_report(ctx["member_id"], C.JUNE_START, C.JUNE_END), 200)
    assert before["realized_cents"] == REALIZED_CENTS

    response = api_client.renormalize_batch(ctx["batch_id"], ANALYST)
    batch = validate_success(response, 200)
    assert_purchase_batch(batch)
    assert batch["normalization_status"] == NormalizationStatus.RECEIVED.value

    for accrual in fx.accruals_for_member(ctx["member_id"]):
        assert_accrual(accrual)
        assert accrual["status"] == AccrualStatus.REVERSED.value
        assert accrual["reversal_reason"] == ReversalReason.RENORMALIZED.value
    member = fx.read_member(ctx["member_id"])
    assert member["accrued_member_share_cents"] == 0

    after = validate_success(_report(ctx["member_id"], C.JUNE_START, C.JUNE_END), 200)
    # The rebate component and the hard-price component both vanish: the accruals
    # are REVERSED and there is no MATCHED line left to price against a baseline.
    assert after["realized_cents"] == 0
    assert after["rebate_member_share_cents"] == 0
    # AS_PURCHASED measures opportunity over the MATCHED lines only, and there are
    # none, so the guard reports 0 rather than dividing by zero.
    assert after["opportunity_cents"] == 0
    assert after["capture_rate_bps"] == 0
    assert after["missed_opportunity_cents"] == 0
    # The volume and the spend survive; only the contract attribution is gone.
    assert after["matched_cases"] == 0
    assert after["unmatched_cases"] == JUNE_MATCHED_CASES
    assert after["invoice_spend_cents"] == INVOICE_SPEND_CENTS


def test_savings_report_is_period_scoped_by_invoice_date():
    """A 2026-06-01..2026-06-04 report over the same accrued feed sees nothing,
    because both invoice dates fall on 06-05 and 06-18.

    PRD §3.9: "Only the named member's own purchase lines are considered, and
    only those whose `invoice_date` falls inside the requested inclusive period."

    Design: Corner/endpoints/savings_report_drops_everything_a_renormalize_unwound
    """
    ctx = fx.setup_june_accrued()

    response = _report(ctx["member_id"], C.JUNE_START, EARLY_JUNE_END)
    report = validate_success(response, 200)

    assert report["period_start"] == C.JUNE_START
    assert report["period_end"] == EARLY_JUNE_END
    assert report["matched_cases"] == 0
    assert report["invoice_spend_cents"] == 0
    assert report["realized_cents"] == 0
    assert report["opportunity_cents"] == 0


# ======================================================== accrue is all-or-skip ====
# Instance: accrue_skips_unaccruable_lines_instead_of_failing_the_batch


def test_accrue_returns_200_and_monetizes_only_the_two_accruable_lines():
    """Two of four lines are accruable; the call succeeds, advances the batch and
    creates exactly two accruals of 4500 and 6000 cents.

    PRD §3.4: "a normalized batch in which not one `MATCHED` line resolves an
    approved rate card for its own `invoice_date` is refused with
    `ERR_NO_ACCRUABLE_LINES`, because an accrual run that would produce nothing
    should not advance the batch's state."

    Design: Corner/endpoints/accrue_skips_unaccruable_lines_instead_of_failing_the_batch
    """
    ctx = _all_or_skip_batch()

    response = api_client.accrue_batch(ctx["batch_id"], ANALYST)
    batch = validate_success(response, 200)
    assert_purchase_batch(batch)
    assert batch["normalization_status"] == NormalizationStatus.ACCRUED.value
    assert batch["accrued_by_user_id"] == ANALYST_1

    rows, meta = validate_paginated(
        api_client.list_accruals(ANALYST, {"member_id": ctx["member_id"], "limit": C.MAX_LIMIT})
    )
    assert meta["total_count"] == 2
    by_line = {a["purchase_line_id"]: a for a in rows}
    assert set(by_line) == {ctx["line_a"]["id"], ctx["line_b"]["id"]}
    accrual_a = by_line[ctx["line_a"]["id"]]
    accrual_b = by_line[ctx["line_b"]["id"]]
    assert_split(accrual_a, GROSS_A, ADMIN_FEE_BPS_LOW, FEE_A, NET_A, SHARE_A, RETENTION_A)
    assert_split(accrual_b, GROSS_B, ADMIN_FEE_BPS_LOW, FEE_B, NET_B, SHARE_B, RETENTION_B)

    # Only the two accrued lines contributed to the member's ledger.
    assert_member_ledger(
        fx.read_member(ctx["member_id"]), LEDGER_SHARE, LEDGER_RETENTION, LEDGER_FEE
    )


def test_accrue_blames_only_the_matched_line_that_found_no_rate_card():
    """The 2026-05-20 line stays MATCHED but is stamped NO_RATE_CARD with no
    zero-value accrual, while the un-contracted key keeps accrual_block_reason NONE.

    PRD §3.4: "When no candidate survives, the line is given
    `accrual_block_reason` of `NO_RATE_CARD` and produces no accrual, while the
    rest of the run proceeds."

    Design: Corner/endpoints/accrue_skips_unaccruable_lines_instead_of_failing_the_batch
    """
    ctx = _all_or_skip_batch()
    validate_success(api_client.accrue_batch(ctx["batch_id"], ANALYST), 200)

    line_c = validate_success(api_client.get_purchase_line(ctx["line_c"]["id"], ANALYST), 200)
    assert_purchase_line(line_c)
    assert line_c["match_status"] == MatchStatus.MATCHED.value
    assert line_c["contracted_item_id"] == ctx["item_id"]
    assert line_c["accrual_block_reason"] == AccrualBlockReason.NO_RATE_CARD.value

    # An unmatched line is not blamed on a missing rate card: with no key
    # candidate at all the PRD leaves accrual_block_reason at NONE.
    line_d = validate_success(api_client.get_purchase_line(ctx["line_d"]["id"], ANALYST), 200)
    assert line_d["match_status"] == MatchStatus.UNMATCHED.value
    assert line_d["contracted_item_id"] is None
    assert line_d["accrual_block_reason"] == AccrualBlockReason.NONE.value

    accrued_lines = {a["purchase_line_id"] for a in fx.accruals_for_member(ctx["member_id"])}
    assert ctx["line_c"]["id"] not in accrued_lines
    assert ctx["line_d"]["id"] not in accrued_lines


def test_accrue_leaves_the_case_counters_normalize_wrote_and_is_not_idempotent():
    """Accrue does not rewrite matched/unmatched cases, and a second accrue on the
    now-ACCRUED batch is state-gated rather than repeated.

    PRD §3.3: "`total_cases_ingested` is never recomputed by normalization; it
    records what the distributor sent and stays fixed for the life of the batch."
    PRD §3.4: "A batch in any other normalization state is refused with
    `ERR_INVALID_STATE`".

    Design: Corner/endpoints/accrue_skips_unaccruable_lines_instead_of_failing_the_batch
    """
    ctx = _all_or_skip_batch()
    assert ctx["batch"]["matched_cases"] == Q2B_MATCHED_CASES
    assert ctx["batch"]["unmatched_cases"] == Q2B_UNMATCHED_CASES

    batch = validate_success(api_client.accrue_batch(ctx["batch_id"], ANALYST), 200)
    assert batch["total_cases_ingested"] == Q2B_TOTAL_CASES
    assert batch["matched_cases"] == Q2B_MATCHED_CASES
    assert batch["unmatched_cases"] == Q2B_UNMATCHED_CASES
    assert_case_conservation(batch)

    response = api_client.accrue_batch(ctx["batch_id"], ANALYST)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)


# ================================================ map into the candidate set only ====
# Instance: map_resolves_an_ambiguous_line_to_one_of_its_candidates


def test_map_to_an_item_outside_the_candidate_set_is_refused_and_changes_nothing():
    """The brisket item is ACTIVE under an ACTIVE deal covering the invoice date,
    but its normalized key differs, so the map is refused and the line stays AMBIGUOUS.

    PRD §3.3: "requires the supplied item to be a member of that line's eligible
    candidate set — same normalized key, item `ACTIVE`, deal `ACTIVE` and deal
    dates covering the invoice date. An item outside that set is rejected with
    `ERR_ITEM_NOT_A_CANDIDATE`".

    Design: Corner/endpoints/map_resolves_an_ambiguous_line_to_one_of_its_candidates
    """
    ctx = _ambiguous_line_with_two_candidates()
    line = fx.read_line(ctx["line_a"]["id"])
    assert line["match_status"] == MatchStatus.AMBIGUOUS.value
    assert line["contracted_item_id"] is None
    assert line["accrual_block_reason"] == AccrualBlockReason.NONE.value
    assert ctx["batch"]["matched_cases"] == 0
    assert ctx["batch"]["unmatched_cases"] == C.LINE_A_CASES

    response = api_client.map_purchase_line(
        ctx["line_a"]["id"], {"contracted_item_id": ctx["item_c"]["id"]}, ANALYST
    )
    validate_error(response, ApiErrorId.ERR_ITEM_NOT_A_CANDIDATE, 422)

    unchanged = fx.read_line(ctx["line_a"]["id"])
    assert unchanged["match_status"] == MatchStatus.AMBIGUOUS.value
    assert unchanged["contracted_item_id"] is None


def test_map_to_an_eligible_candidate_matches_the_line_and_recomputes_the_counters():
    """Mapping to the rival deal's item moves the line AMBIGUOUS to MATCHED and
    rewrites both batch case counters; a second map on it is then state-gated.

    PRD §3.3: "A `RebateAnalyst` may map an `AMBIGUOUS` line by supplying the
    `contracted_item_id` it should resolve to, moving the line `AMBIGUOUS →
    MATCHED` and recomputing the batch's `matched_cases` and `unmatched_cases`."

    Design: Corner/endpoints/map_resolves_an_ambiguous_line_to_one_of_its_candidates
    """
    ctx = _ambiguous_line_with_two_candidates()

    response = api_client.map_purchase_line(
        ctx["line_a"]["id"], {"contracted_item_id": ctx["item_b"]["id"]}, ANALYST
    )
    line = validate_success(response, 200)
    assert_purchase_line(line)
    assert line["match_status"] == MatchStatus.MATCHED.value
    assert line["contracted_item_id"] == ctx["item_b"]["id"]

    batch = fx.read_batch(ctx["batch_id"])
    assert batch["matched_cases"] == C.LINE_A_CASES
    assert batch["unmatched_cases"] == 0
    assert_case_conservation(batch)

    # PRD §2.7 step 11: "The target record is in a state from which the requested
    # transition is declared ... otherwise `ERR_INVALID_STATE`." Map declares
    # AMBIGUOUS -> MATCHED only.
    second = api_client.map_purchase_line(
        ctx["line_a"]["id"], {"contracted_item_id": ctx["item_b"]["id"]}, ANALYST
    )
    validate_error(second, ApiErrorId.ERR_INVALID_STATE, 409)


def test_accrual_after_a_map_prices_from_the_chosen_deals_rate_card():
    """The stored association decides the price: 30 cases at the rival card's 220
    cents is 6600, not the other candidate's 4500.

    PRD §3.4: "Under `PER_CASE`, the gross is the line's `cases_shipped`
    multiplied by the card's `flat_rate_cents_per_case`." and "**Step five**
    assigns the residual: `gpo_retention_cents` is `net_distributable_cents`
    minus `member_share_cents`".

    Design: Corner/endpoints/map_resolves_an_ambiguous_line_to_one_of_its_candidates
    """
    ctx = _ambiguous_line_with_two_candidates()
    fx.map_line(ctx["line_a"]["id"], ctx["item_b"]["id"])

    response = api_client.accrue_batch(ctx["batch_id"], ANALYST)
    validate_success(response, 200)

    accrual = fx.accrual_for_line(ctx["line_a"]["id"])
    assert_accrual(accrual)
    assert accrual["rate_card_id"] == ctx["card_b"]["id"]
    assert accrual["accrued_cases"] == C.LINE_A_CASES
    assert accrual["gross_rebate_cents"] == RIVAL_GROSS == C.LINE_A_CASES * RIVAL_RATE_CENTS
    assert accrual["gross_rebate_cents"] != GROSS_A
    assert_split(
        accrual,
        RIVAL_GROSS,
        ADMIN_FEE_BPS_LOW,
        RIVAL_FEE,
        RIVAL_NET,
        RIVAL_SHARE,
        RIVAL_RETENTION,
    )
    assert (
        accrual["member_share_cents"]
        + accrual["gpo_retention_cents"]
        + accrual["admin_fee_cents"]
        == RIVAL_GROSS
    )


# ============================================ settle-recovery's conditional field ====
# Instance: settle_recovery_requires_recovered_cents_for_recovered_only


def test_settle_recovery_recovered_without_recovered_cents_is_invalid_request():
    """RECOVERED with the amount omitted is a 400, and the batch is untouched.

    PRD §3.7: "with `recovered_cents` required when the outcome is `RECOVERED`
    and required to be **omitted** when the outcome is `WRITTEN_OFF`".

    Design: Corner/endpoints/settle_recovery_requires_recovered_cents_for_recovered_only
    """
    ctx = _recovery_requested_june_batch()
    assert ctx["batch"]["audit_status"] == AuditStatus.RECOVERY_REQUESTED.value
    assert ctx["batch"]["overbilled_cents"] == BATCH_OVERBILLED

    response = api_client.settle_recovery(
        ctx["batch_id"], {"outcome": RecoveryOutcome.RECOVERED.value}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    batch = fx.read_batch(ctx["batch_id"])
    assert batch["audit_status"] == AuditStatus.RECOVERY_REQUESTED.value
    assert batch["recovered_cents"] == 0
    assert fx.read_member(ctx["member_id"])["recovery_credit_cents"] == 0


def test_settle_recovery_written_off_with_recovered_cents_is_invalid_request():
    """WRITTEN_OFF carrying recovered_cents is an unknown-field 400 — and because
    it is rejected, the distributor is not suspended.

    PRD §3.7: "supplying it in the write-off case is an unknown-field violation
    reported as `ERR_INVALID_REQUEST`." and "An outcome of `WRITTEN_OFF` forces
    `recovered_cents` to 0, moves the batch `RECOVERY_REQUESTED → WRITTEN_OFF`,
    credits no member at all, and cascades into the distributor relationship: the
    batch's distributor moves `ACTIVE → SUSPENDED`".

    Design: Corner/endpoints/settle_recovery_requires_recovered_cents_for_recovered_only
    """
    ctx = _recovery_requested_june_batch()

    response = api_client.settle_recovery(
        ctx["batch_id"],
        {
            "outcome": RecoveryOutcome.WRITTEN_OFF.value,
            "recovered_cents": REJECTED_WRITE_OFF_CENTS,
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    batch = fx.read_batch(ctx["batch_id"])
    assert batch["audit_status"] == AuditStatus.RECOVERY_REQUESTED.value
    assert batch["recovered_cents"] == 0
    distributor = fx.read_distributor(ctx["distributor_id"])
    assert_distributor(distributor)
    assert distributor["status"] == DistributorStatus.ACTIVE.value
    assert distributor["overbilled_recovered_cents"] == 0


def test_settle_recovery_credits_the_member_from_its_aggregated_overbilling():
    """The legal RECOVERED form succeeds and prorates by MEMBER, not by line: one
    member owning 300 + 80 == 380 of 380 takes all 200 cents with no lost cent.

    PRD §3.7: "First, each member's overbilling on this batch is totalled as the
    sum of `overbilled_cents` over that member's lines within the batch" and
    "Each participating member's provisional slice is the batch's
    `recovered_cents` multiplied by that member's overbilling total, divided by
    the batch's `overbilled_cents`, and floored to whole cents."

    Design: Corner/endpoints/settle_recovery_requires_recovered_cents_for_recovered_only
    """
    ctx = _recovery_requested_june_batch()
    assert fx.read_line(ctx["line_a"]["id"])["overbilled_cents"] == OVERBILLED_A
    assert fx.read_line(ctx["line_b"]["id"])["overbilled_cents"] == OVERBILLED_B

    response = api_client.settle_recovery(
        ctx["batch_id"],
        {
            "outcome": RecoveryOutcome.RECOVERED.value,
            "recovered_cents": RECOVERED_CENTS,
        },
        ADMIN,
    )
    batch = validate_success(response, 200)
    assert_purchase_batch(batch)
    assert batch["audit_status"] == AuditStatus.RECOVERED.value
    assert batch["recovered_cents"] == RECOVERED_CENTS
    assert batch["overbilled_cents"] == BATCH_OVERBILLED

    # A per-LINE prorate would floor twice (157 + 42) and lose a cent.
    member = fx.read_member(ctx["member_id"])
    assert_member(member)
    assert member["recovery_credit_cents"] == RECOVERED_CENTS

    distributor = fx.read_distributor(ctx["distributor_id"])
    assert distributor["overbilled_recovered_cents"] == RECOVERED_CENTS
    assert distributor["status"] == DistributorStatus.ACTIVE.value


# ============================================ revoke closes one member's data feed ====
# Instance: revoking_a_letter_closes_the_data_feed_for_that_member


def test_revoke_decrements_both_counters_without_unenrolling_the_member():
    """Revoking Harbor Grill's letter drops both active_letter_count figures, and
    the distributor keeps Pier 9's, while the member stays ACTIVE and unheld.

    PRD §3.1: "A `MemberOperator` or a `GpoAdmin` may withdraw an authorization,
    moving it `ACTIVE → REVOKED` and decrementing both `active_letter_count`
    figures by 1."

    Design: Corner/endpoints/revoking_a_letter_closes_the_data_feed_for_that_member
    """
    ctx = _two_members_one_open_feed()
    assert fx.read_distributor(ctx["distributor_id"])["active_letter_count"] == 2

    response = api_client.revoke_letter(
        ctx["letter_id"], make_member_operator_headers(ctx["member_id"])
    )
    letter = validate_success(response, 200)
    assert_authorization_letter(letter)
    assert letter["status"] == LetterStatus.REVOKED.value

    member = fx.read_member(ctx["member_id"])
    assert member["active_letter_count"] == 0
    assert fx.read_distributor(ctx["distributor_id"])["active_letter_count"] == 1
    # Revoking a letter is not a termination.
    assert member["enrollment_status"] == MemberEnrollmentStatus.ACTIVE.value
    assert member["payout_hold"] is False


def test_revoked_letter_closes_ingest_for_that_member_only():
    """The very next line for Harbor Grill is refused, while Pier 9's line lands in
    the same batch: the gate is per member, not per batch.

    PRD §3.3: "the member must hold at least one authorization letter whose
    `status` is `ACTIVE`, whose `distributor_id` is the batch's distributor, and
    whose half-open window contains the current logical-clock instant, and a line
    lacking one is rejected with `ERR_LOA_NOT_ACTIVE`."

    Design: Corner/endpoints/revoking_a_letter_closes_the_data_feed_for_that_member
    """
    ctx = _two_members_one_open_feed()
    fx.revoke_letter(ctx["letter_id"], ctx["member_id"])
    feed_headers = make_distributor_feed_headers(ctx["distributor_id"])

    refused = api_client.create_purchase_line(
        F.purchase_line_payload(ctx["batch_id"], ctx["member_id"]), feed_headers
    )
    validate_error(refused, ApiErrorId.ERR_LOA_NOT_ACTIVE, 409)
    assert fx.read_batch(ctx["batch_id"])["line_count"] == 0

    accepted = api_client.create_purchase_line(
        F.purchase_line_payload(
            ctx["batch_id"],
            ctx["member_2_id"],
            cases_shipped=C.LINE_B_CASES,
            distributor_base_cost_cents=C.LINE_B_BASE_COST_CENTS,
            invoice_date=C.LINE_B_INVOICE_DATE,
        ),
        feed_headers,
    )
    line = validate_success(accepted, 201)
    assert_purchase_line(line)
    assert line["member_id"] == ctx["member_2_id"]

    batch = fx.read_batch(ctx["batch_id"])
    assert batch["line_count"] == 1
    assert batch["total_cases_ingested"] == C.LINE_B_CASES


def test_second_revoke_is_terminal_and_no_counter_goes_negative():
    """REVOKED is final: the repeat is a 409 and the distributor's counter stays at
    the one letter it still holds.

    PRD §3.1: "`DECLINED`, `REVOKED` and `EXPIRED` are all final: none of them can
    be reopened, and a member wanting authorization again must submit a fresh
    letter."

    Design: Corner/endpoints/revoking_a_letter_closes_the_data_feed_for_that_member
    """
    ctx = _two_members_one_open_feed()
    fx.revoke_letter(ctx["letter_id"], ctx["member_id"])

    response = api_client.revoke_letter(
        ctx["letter_id"], make_member_operator_headers(ctx["member_id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)
    assert fx.read_distributor(ctx["distributor_id"])["active_letter_count"] == 1

    # Harbor Grill's only letter is the revoked one; the distributor side still
    # lists both letters of the relationship.
    own_rows, own_meta = validate_paginated(
        api_client.list_authorization_letters(
            ADMIN, {"member_id": ctx["member_id"], "limit": C.MAX_LIMIT}
        )
    )
    assert own_meta["total_count"] == 1
    assert own_rows[0]["id"] == ctx["letter_id"]
    assert own_rows[0]["status"] == LetterStatus.REVOKED.value

    dist_rows, dist_meta = validate_paginated(
        api_client.list_authorization_letters(
            ADMIN, {"distributor_id": ctx["distributor_id"], "limit": C.MAX_LIMIT}
        )
    )
    assert dist_meta["total_count"] == 2
    live = [r for r in dist_rows if r["status"] == LetterStatus.ACTIVE.value]
    assert [r["id"] for r in live] == [ctx["letter_2"]["id"]]


# =============================================== immediate consistency everywhere ====
# Instance: every_write_is_visible_in_its_own_response_and_the_very_next_read


def test_countersign_shows_the_transition_in_its_own_response_and_both_counters_next():
    """The countersign response already carries ACTIVE and the 09:00 stamp, and the
    first read of the member and of the distributor already shows one live letter.

    PRD §3.1: "A `decision` of `ACCEPT` moves the letter `SUBMITTED → ACTIVE`,
    stamps `countersigned_at` with the current logical-clock instant, and
    increments both the member's and the distributor's `active_letter_count` by 1."
    PRD §2.10: "when a request returns, every consequence of it is already visible
    to the next read."

    Design: Corner/consistency_model/every_write_is_visible_in_its_own_response_and_the_very_next_read
    """
    ctx = _consistency_program()

    response = api_client.countersign_letter(
        ctx["letter_id"],
        {"decision": "ACCEPT"},
        make_distributor_feed_headers(ctx["distributor_id"]),
    )
    letter = validate_success(response, 200)
    assert_authorization_letter(letter)
    # No follow-up read is needed to see the transition.
    assert letter["status"] == LetterStatus.ACTIVE.value
    assert letter["countersigned_at"] is not None
    assert_instants_equal(letter["countersigned_at"], CONSISTENCY_CLOCK)

    # The very next read of each row the same write touched is already current.
    assert fx.read_member(ctx["member_id"])["active_letter_count"] == 1
    assert fx.read_distributor(ctx["distributor_id"])["active_letter_count"] == 1


def test_line_create_response_and_the_parents_three_counters_are_current_at_once():
    """The line's own response carries its extended cost and match fields, and the
    very next read of the batch shows all three counters already moved.

    PRD §3.3: "A stored line's invoiced extended cost is computed immediately and
    exactly: `invoice_extended_cents` is `cases_shipped` multiplied by
    `invoice_unit_cost_cents`" and "Its arrival increments the batch's
    `line_count` by 1 and adds the line's `cases_shipped` to both
    `total_cases_ingested` and `unmatched_cases`."

    Design: Corner/consistency_model/every_write_is_visible_in_its_own_response_and_the_very_next_read
    """
    ctx = _consistency_program()
    fx.countersign_letter(ctx["letter_id"], ctx["distributor_id"])
    fx.activate_member(ctx["member_id"])
    feed_headers = make_distributor_feed_headers(ctx["distributor_id"])
    batch = fx.create_batch(ctx["distributor_id"])

    response = api_client.create_purchase_line(
        F.purchase_line_payload(batch["id"], ctx["member_id"]), feed_headers
    )
    line = validate_success(response, 201)
    assert_purchase_line(line)
    assert line["invoice_extended_cents"] == 274200
    assert line["invoice_extended_cents"] == C.LINE_A_CASES * C.INVOICE_UNIT_COST_CENTS
    assert line["match_status"] == MatchStatus.UNMATCHED.value
    assert line["contracted_item_id"] is None
    assert line["accrual_block_reason"] == AccrualBlockReason.NONE.value

    parent = validate_success(api_client.get_purchase_batch(batch["id"], feed_headers), 200)
    assert_purchase_batch(parent)
    assert parent["line_count"] == 1
    assert parent["total_cases_ingested"] == C.LINE_A_CASES
    assert parent["unmatched_cases"] == C.LINE_A_CASES


def test_normalize_accrue_and_audit_are_each_current_in_response_and_next_read():
    """Three writes in a row: each returns its own recomputed figures, and the first
    read of the dependent row is already correct with no second call.

    PRD §3.3: "the batch's `matched_cases` is rewritten as the sum of
    `cases_shipped` over its lines whose `match_status` is `MATCHED`".
    PRD §3.4: "Posting it moves the member's ledger: `accrued_member_share_cents`,
    `attributed_gpo_retention_cents` and `attributed_admin_fee_cents` are each
    incremented by the accrual's corresponding component."
    PRD §3.7: "Only after every line is done is the batch's `overbilled_cents` set
    to the sum of its lines' figures."

    Design: Corner/consistency_model/every_write_is_visible_in_its_own_response_and_the_very_next_read
    """
    ctx = _consistency_program()
    fx.countersign_letter(ctx["letter_id"], ctx["distributor_id"])
    fx.activate_member(ctx["member_id"])
    batch = fx.create_batch(ctx["distributor_id"])
    line = fx.create_line(batch["id"], ctx["member_id"], ctx["distributor_id"])

    normalized = validate_success(api_client.normalize_batch(batch["id"], ANALYST), 200)
    assert normalized["matched_cases"] == C.LINE_A_CASES
    assert normalized["unmatched_cases"] == 0
    # The per-line result of the batch-level calculation is readable at once.
    after_normalize = validate_success(api_client.get_purchase_line(line["id"], ANALYST), 200)
    assert after_normalize["match_status"] == MatchStatus.MATCHED.value
    assert after_normalize["contracted_item_id"] == ctx["item_id"]

    validate_success(api_client.accrue_batch(batch["id"], ANALYST), 200)
    # The member ledger moved inside the accrue call, not in a later sweep.
    member = validate_success(api_client.get_member(ctx["member_id"], ANALYST), 200)
    assert member["accrued_member_share_cents"] == SHARE_A
    assert member["attributed_gpo_retention_cents"] == RETENTION_A
    assert member["attributed_admin_fee_cents"] == FEE_A

    audited = validate_success(api_client.audit_markup(batch["id"], ANALYST), 200)
    assert audited["overbilled_cents"] == OVERBILLED_A
    assert audited["audit_status"] == AuditStatus.AUDIT_OVERBILLED.value
    # The per-line figure the batch total was summed from is already stored.
    after_audit = validate_success(api_client.get_purchase_line(line["id"], ANALYST), 200)
    assert after_audit["overbilled_cents"] == OVERBILLED_A
