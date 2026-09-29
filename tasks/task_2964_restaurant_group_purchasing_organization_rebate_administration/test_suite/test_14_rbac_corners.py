"""RBAC corners: the positive half of the role matrix, the three scoped
refusals and the segregation-of-duties bar.

Five design instances live here. One walks a whole rebate lifecycle in which
every hop is executed by the only role entitled to it, so the roles lists
cannot be "allow everything". Three prove the refusals: an unauthorized ROLE
draws ERR_FORBIDDEN_ROLE at ladder priority 3 — ahead of the 404s, the body
checks and every state gate — a MemberOperator acting outside its own member
id draws ERR_MEMBER_SCOPE_VIOLATION at priority 5, and a DistributorFeed
acting outside its own distributor id draws ERR_DISTRIBUTOR_SCOPE_VIOLATION at
priority 6. The last proves that the arbitration bar is on the IDENTIFIER
rather than the role name.
"""
import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ANALYST_1,
    ARBITER_1,
    ARBITER_2,
    GPO_ADMIN_1,
    REP_1,
    AccrualBasis,
    AccrualStatus,
    ApiErrorId,
    AuditStatus,
    ClaimStatus,
    CountersignDecision,
    DisputeDecision,
    DisputeReasonCode,
    DisputeStatus,
    LetterScope,
    LetterStatus,
    MatchStatus,
    MemberEnrollmentStatus,
    NormalizationStatus,
    RateCardStatus,
    ReconciliationPosture,
    RecoveryOutcome,
    Role,
    api_client,
    assert_accrual,
    assert_authorization_letter,
    assert_instants_equal,
    assert_purchase_batch,
    assert_purchase_line,
    assert_split,
    make_analyst_headers,
    make_arbiter_headers,
    make_distributor_feed_headers,
    make_gpo_admin_headers,
    make_headers,
    make_member_operator_headers,
    make_rep_headers,
)
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx

# --------------------------------------------------------------- actors ----
ADMIN = make_gpo_admin_headers(GPO_ADMIN_1)
ANALYST = make_analyst_headers(ANALYST_1)
ARBITER = make_arbiter_headers(ARBITER_1)
ARBITER_OTHER = make_arbiter_headers(ARBITER_2)
REP = make_rep_headers(REP_1)

# The two GPO staff identities of the segregation-of-duties instance: the same
# opaque ids are recorded while wearing RebateAnalyst and later presented under
# the DisputeArbiter role.
DUAL_ONE = "dual-01"
DUAL_TWO = "dual-02"
DUAL_ONE_ANALYST = make_analyst_headers(DUAL_ONE)
DUAL_TWO_ANALYST = make_analyst_headers(DUAL_TWO)
DUAL_ONE_ARBITER = make_headers(Role.DISPUTE_ARBITER.value, DUAL_ONE)
DUAL_TWO_ARBITER = make_headers(Role.DISPUTE_ARBITER.value, DUAL_TWO)

# ---------------------------------------------------------------- clock ----
# Every instance parks the logical clock here before building anything.
CLOCK_0900 = "2026-08-01T09:00:00.000Z"
CLOCK_NEXT_DAY = "2026-08-02T09:00:00.000Z"
CLOCK_SEPTEMBER = "2026-09-01T00:00:00.000Z"

# A letter window that closes in 2027, leaving 2027-06-01 onwards free for a
# second, non-overlapping submission.
LETTER_TO_2027 = "2027-01-01T00:00:00.000Z"

# ------------------------------------------ the canonical 30-case accrual ----
CASES = 30                  # PER_CASE at 150 cents
GROSS = 4500                # 30 * 150
FEE_BPS = 300               # admin_fee_bps_low: ytd_net_snapshot 0 < 5_000_000
FEE = 135                   # 4500 * 300 / 10000
NET = 4365                  # 4500 - 135
SHARE = 3274                # 4365 * 7500 / 10000 rounded half up
RETENTION = 1091            # 4365 - 3274, the residual
OVERBILLED = 300            # (9140 - (8533 + 597)) * 30, markup capped at 700 bps
YTD_AFTER_CLOSE = 4365      # 3274 + 1091


# ======================================================= local setup helpers ==
# Every precondition is built through the API because the database is empty
# before each test. These helpers only assemble what a design instance's
# setup_api_calls list assembles; the calls under test always stay in the test.


def _reference_data():
    """Clock at 09:00, ELITE tier, METRO-01 distributor, PENDING Harbor Grill."""
    fx.set_clock(CLOCK_0900)
    tier = fx.create_tier()
    distributor = fx.create_distributor()
    member = fx.create_member(tier["id"])
    return {
        "tier": tier,
        "distributor": distributor,
        "distributor_id": distributor["id"],
        "member": member,
        "member_id": member["id"],
        "member_headers": make_member_operator_headers(member["id"]),
        "distributor_headers": make_distributor_feed_headers(distributor["id"]),
    }


def _priced_deal(ctx, activate=True):
    """Deal PBC-2026 with the beef item and an APPROVED 150-cents PER_CASE card."""
    deal = fx.create_deal()
    item = fx.create_item(deal["id"])
    card = fx.create_card(item["id"])
    ctx["card"] = card
    ctx["card_id"] = card["id"]
    if activate:
        ctx["card"] = fx.approve_card(card["id"])
        deal = fx.activate_deal(deal["id"])
    ctx["deal"] = deal
    ctx["deal_id"] = deal["id"]
    ctx["item"] = item
    ctx["item_id"] = item["id"]
    return ctx


def _active_member_with_letter(ctx, member=None, **letter_overrides):
    """Countersign a fresh letter for one member and activate it."""
    member = member or ctx["member"]
    letter = fx.submit_letter(member["id"], ctx["distributor_id"], **letter_overrides)
    letter = fx.countersign_letter(letter["id"], ctx["distributor_id"])
    return fx.activate_member(member["id"]), letter


def _open_analyst_batch(distributor_id, **overrides):
    """POST /purchase-batches is shared: the analyst is the non-feed holder."""
    return validate_success(
        api_client.create_purchase_batch(
            F.purchase_batch_payload(distributor_id, **overrides), ANALYST
        ),
        201,
    )


def _accrued_june_line(ctx, analyst_headers=None):
    """One 30-case beef line ingested by the feed, normalized and accrued."""
    analyst_headers = analyst_headers or ANALYST
    batch = fx.create_batch(ctx["distributor_id"])
    line = fx.create_line(batch["id"], ctx["member_id"], ctx["distributor_id"])
    fx.normalize(batch["id"], analyst_headers)
    ctx["batch"] = fx.accrue(batch["id"], analyst_headers)
    ctx["batch_id"] = batch["id"]
    ctx["line"] = line
    ctx["line_id"] = line["id"]
    ctx["accrual"] = fx.accrual_for_line(line["id"])
    ctx["accrual_id"] = ctx["accrual"]["id"]
    return ctx


# ============================================================================
# Instance: every_role_can_run_its_own_exclusive_operations
# ============================================================================


def test_full_lifecycle_runs_each_hop_under_its_only_entitled_role():
    """One rebate lifecycle where every hop is executed by the only role the
    routing table entitles to it, so every call must be a 2xx and the roles
    lists cannot be "allow everything".
    PRD: "Owns all reference data (program tiers, distributors, members,
    manufacturer deals, contracted items and rate cards), settles overbilling
    recoveries, closes rebate periods, and drives the logical clock."
    PRD: "The only role permitted to request evidence on a dispute or to
    decide one."
    Design: Corner/rbac/every_role_can_run_its_own_exclusive_operations
    """
    ctx = _reference_data()
    # The letter is submitted by GpoAdmin (a shared operation) and left
    # SUBMITTED for the distributor to countersign.
    letter = fx.submit_letter(ctx["member_id"], ctx["distributor_id"], headers=ADMIN)
    assert letter["status"] == LetterStatus.SUBMITTED.value
    _priced_deal(ctx)

    # 1. DistributorFeed, exclusive: countersign.
    response = api_client.countersign_letter(
        letter["id"],
        {"decision": CountersignDecision.ACCEPT.value},
        ctx["distributor_headers"],
    )
    letter = validate_success(response, 200)
    assert_authorization_letter(letter)
    assert letter["status"] == LetterStatus.ACTIVE.value
    assert_instants_equal(letter["countersigned_at"], CLOCK_0900)

    # 2. GpoAdmin, exclusive: member activation.
    member = validate_success(api_client.activate_member(ctx["member_id"], ADMIN), 200)
    assert member["enrollment_status"] == MemberEnrollmentStatus.ACTIVE.value

    # 3. RebateAnalyst on a SHARED create: the other holder is DistributorFeed.
    batch = validate_success(
        api_client.create_purchase_batch(
            F.purchase_batch_payload(ctx["distributor_id"]), ANALYST
        ),
        201,
    )
    assert batch["normalization_status"] == NormalizationStatus.RECEIVED.value

    # 4. DistributorFeed, exclusive: ingest one 30-case invoice line.
    line = validate_success(
        api_client.create_purchase_line(
            F.purchase_line_payload(batch["id"], ctx["member_id"]),
            ctx["distributor_headers"],
        ),
        201,
    )
    assert_purchase_line(line)
    assert line["cases_shipped"] == CASES

    # 5 and 6. RebateAnalyst, exclusive: normalize then accrue.
    batch = validate_success(api_client.normalize_batch(batch["id"], ANALYST), 200)
    assert batch["normalization_status"] == NormalizationStatus.NORMALIZED.value
    batch = validate_success(api_client.accrue_batch(batch["id"], ANALYST), 200)
    assert_purchase_batch(batch)
    assert batch["normalization_status"] == NormalizationStatus.ACCRUED.value
    assert batch["matched_cases"] == CASES
    assert batch["accrued_by_user_id"] == ANALYST_1

    # 7. RebateAnalyst reads its own accrual.
    rows, meta = validate_paginated(
        api_client.list_accruals(
            ANALYST, {"purchase_line_id": line["id"], "limit": C.MAX_LIMIT}
        )
    )
    assert meta["total_count"] == 1
    accrual = rows[0]
    assert_accrual(accrual)
    assert_split(accrual, GROSS, FEE_BPS, FEE, NET, SHARE, RETENTION)

    # 8 and 9. ManufacturerRep reads deal-side reference data and files the
    # only write it has: a claim on a SHARED create.
    deal = validate_success(api_client.get_deal(ctx["deal_id"], REP), 200)
    claim = validate_success(
        api_client.create_claim(
            F.claim_payload(ctx["deal_id"], deal["version"], CASES, GROSS), REP
        ),
        201,
    )
    assert claim["status"] == ClaimStatus.SUBMITTED.value

    # 10. RebateAnalyst, exclusive: reconcile.
    claim = validate_success(api_client.reconcile_claim(claim["id"], ANALYST), 200)
    assert claim["status"] == ClaimStatus.RECONCILED.value
    assert claim["accrued_amount_cents"] == GROSS
    assert claim["variance_bps"] == 0

    # 11. RebateAnalyst, exclusive: validate.
    response = api_client.validate_accrual(
        accrual["id"], {"claim_id": claim["id"]}, ANALYST
    )
    accrual = validate_success(response, 200)
    assert accrual["status"] == AccrualStatus.VALIDATED.value
    assert accrual["validated_by_user_id"] == ANALYST_1

    # 12. MemberOperator, exclusive: open the dispute.
    response = api_client.create_dispute(
        F.dispute_payload(
            accrual["id"], SHARE, DisputeReasonCode.RATE_MISMATCH.value, claim["id"]
        ),
        ctx["member_headers"],
    )
    dispute = validate_success(response, 201)
    assert dispute["status"] == DisputeStatus.OPEN.value
    assert dispute["accrual_status_before"] == AccrualStatus.VALIDATED.value
    assert dispute["opened_by_user_id"] == ctx["member_id"]
    assert fx.read_accrual(accrual["id"])["status"] == AccrualStatus.DISPUTED.value

    # 13, 14 and 15: the evidence loop and the REJECT decision.
    dispute = validate_success(api_client.request_evidence(dispute["id"], ARBITER), 200)
    assert dispute["status"] == DisputeStatus.EVIDENCE_REQUESTED.value
    response = api_client.submit_evidence(
        dispute["id"],
        {"evidence_note": "Attaching invoice 88213 and the signed rate sheet."},
        ctx["member_headers"],
    )
    dispute = validate_success(response, 200)
    assert dispute["status"] == DisputeStatus.OPEN.value
    assert dispute["evidence_round_count"] == 1
    response = api_client.decide_dispute(
        dispute["id"],
        {
            "decision": DisputeDecision.REJECT.value,
            "decision_note": "Card 150/case applied as contracted.",
        },
        ARBITER,
    )
    dispute = validate_success(response, 200)
    assert dispute["status"] == DisputeStatus.REJECTED.value
    assert dispute["decided_by_user_id"] == ARBITER_1
    assert fx.read_accrual(accrual["id"])["status"] == AccrualStatus.VALIDATED.value

    # 16 and 17. RebateAnalyst, exclusive: audit then open the demand.
    batch = validate_success(api_client.audit_markup(batch["id"], ANALYST), 200)
    assert batch["audit_status"] == AuditStatus.AUDIT_OVERBILLED.value
    assert batch["overbilled_cents"] == OVERBILLED
    batch = validate_success(api_client.request_recovery(batch["id"], ANALYST), 200)
    assert batch["audit_status"] == AuditStatus.RECOVERY_REQUESTED.value

    # 18. GpoAdmin, exclusive: settle the recovery.
    response = api_client.settle_recovery(
        batch["id"],
        {
            "outcome": RecoveryOutcome.RECOVERED.value,
            "recovered_cents": OVERBILLED,
        },
        ADMIN,
    )
    batch = validate_success(response, 200)
    assert batch["audit_status"] == AuditStatus.RECOVERED.value
    assert fx.read_member(ctx["member_id"])["recovery_credit_cents"] == OVERBILLED
    assert (
        fx.read_distributor(ctx["distributor_id"])["overbilled_recovered_cents"]
        == OVERBILLED
    )

    # 19. MemberOperator on a shared read: its OWN savings report.
    response = api_client.get_savings_report(
        ctx["member_id"],
        ctx["member_headers"],
        F.savings_report_params(C.JUNE_START, C.JUNE_END),
    )
    report = validate_success(response, 200)
    assert report["member_id"] == ctx["member_id"]

    # 20. GpoAdmin, exclusive: close the period.
    response = api_client.close_period(
        ctx["deal_id"],
        {"period_start": C.JUNE_START, "period_end": C.JUNE_END},
        ADMIN,
    )
    validate_success(response, 200)
    accrual = fx.read_accrual(accrual["id"])
    assert accrual["status"] == AccrualStatus.PAID.value
    assert accrual["basis"] == AccrualBasis.BLENDED_PERIOD.value
    assert accrual["final_adjustment_cents"] == 0
    member = fx.read_member(ctx["member_id"])
    assert member["ytd_net_snapshot_cents"] == YTD_AFTER_CLOSE
    assert member["ytd_net_snapshot_cents"] == SHARE + RETENTION

    # 21. GpoAdmin, exclusive: drive the logical clock.
    response = api_client.set_clock(CLOCK_NEXT_DAY, ADMIN)
    clock = validate_success(response, 200)
    assert_instants_equal(clock["current_utc"], CLOCK_NEXT_DAY)


def test_shared_write_operations_accept_either_of_their_two_holders():
    """The lifecycle's shared hops must accept BOTH declared holders: a letter
    from the member itself and from the admin, a feed opened by the distributor
    and by the analyst, a claim filed by the rep and by the admin, and the
    savings report read by all three of its roles.
    PRD: "is submitted either by the `MemberOperator` itself or by a `GpoAdmin`
    on its behalf".
    PRD: "Either the `DistributorFeed` account itself or a `RebateAnalyst`
    opens a batch by supplying `distributor_id`".
    PRD: "A `ManufacturerRep`, or a `GpoAdmin` acting on the manufacturer's
    behalf, files one against a deal".
    Design: Corner/rbac/every_role_can_run_its_own_exclusive_operations
    """
    ctx = _reference_data()
    second = fx.create_member(
        ctx["tier"]["id"],
        legal_name="Pier 9 Oyster Bar Inc",
        committed_annual_spend_cents=9_000_000,
    )

    # POST /authorization-letters, holder 1: the MemberOperator itself.
    own = validate_success(
        api_client.create_authorization_letter(
            F.authorization_letter_payload(ctx["member_id"], ctx["distributor_id"]),
            ctx["member_headers"],
        ),
        201,
    )
    # POST /authorization-letters, holder 2: GpoAdmin on the member's behalf.
    on_behalf = validate_success(
        api_client.create_authorization_letter(
            F.authorization_letter_payload(second["id"], ctx["distributor_id"]),
            ADMIN,
        ),
        201,
    )
    for letter in (own, on_behalf):
        assert letter["status"] == LetterStatus.SUBMITTED.value
    fx.countersign_letter(own["id"], ctx["distributor_id"])
    fx.activate_member(ctx["member_id"])

    # POST /purchase-batches, both holders.
    feed_batch = validate_success(
        api_client.create_purchase_batch(
            F.purchase_batch_payload(ctx["distributor_id"]), ctx["distributor_headers"]
        ),
        201,
    )
    analyst_batch = _open_analyst_batch(
        ctx["distributor_id"],
        period_start=C.JULY_START,
        period_end=C.JULY_END,
        source_reference=C.JULY_BATCH_REFERENCE,
    )
    assert feed_batch["id"] != analyst_batch["id"]

    # POST /manufacturer-claims, both holders. The rep's filing advances the
    # deal's version, so the admin re-reads it before restating for July.
    deal = fx.create_deal()
    rep_claim = validate_success(
        api_client.create_claim(
            F.claim_payload(deal["id"], deal["version"], CASES, GROSS), REP
        ),
        201,
    )
    admin_claim = validate_success(
        api_client.create_claim(
            F.claim_payload(
                deal["id"],
                fx.deal_version(deal["id"]),
                10,
                1500,
                period_start=C.JULY_START,
                period_end=C.JULY_END,
            ),
            ADMIN,
        ),
        201,
    )
    for claim in (rep_claim, admin_claim):
        assert claim["status"] == ClaimStatus.SUBMITTED.value

    # GET /members/{member_id}/savings-report, all three holders.
    params = F.savings_report_params(C.JUNE_START, C.JUNE_END)
    for headers in (ctx["member_headers"], ADMIN, ANALYST):
        report = validate_success(
            api_client.get_savings_report(ctx["member_id"], headers, params), 200
        )
        assert report["member_id"] == ctx["member_id"]


# ============================================================================
# Instance: roles_cannot_run_another_roles_exclusive_operations
# ============================================================================


def _setup_forbidden_role_grid():
    """PENDING member, DRAFT deal with a PROPOSED card, empty RECEIVED batch."""
    ctx = _reference_data()
    _priced_deal(ctx, activate=False)
    batch = _open_analyst_batch(ctx["distributor_id"])
    ctx["batch"] = batch
    ctx["batch_id"] = batch["id"]
    ctx["deal_version"] = fx.deal_version(ctx["deal_id"])
    return ctx


def _analyst_approves_rate_card(ctx):
    return api_client.approve_rate_card(ctx["card_id"], ANALYST)


def _analyst_settles_recovery(ctx):
    # The batch is NOT_AUDITED and could never be settled, so priority 11 would
    # also refuse this request; priority 3 runs first.
    return api_client.settle_recovery(
        ctx["batch_id"], {"outcome": RecoveryOutcome.WRITTEN_OFF.value}, ANALYST
    )


def _admin_normalizes_batch(ctx):
    return api_client.normalize_batch(ctx["batch_id"], ADMIN)


def _arbiter_ingests_purchase_line(ctx):
    return api_client.create_purchase_line(
        F.purchase_line_payload(ctx["batch_id"], ctx["member_id"]), ARBITER
    )


def _rep_activates_member(ctx):
    return api_client.activate_member(ctx["member_id"], REP)


def _member_operator_drives_the_clock(ctx):
    return api_client.set_clock(CLOCK_SEPTEMBER, ctx["member_headers"])


def _distributor_feed_files_a_claim(ctx):
    # expected_deal_version is supplied and correct, so the refusal cannot be
    # ERR_STALE_PARENT_VERSION: priority 3 runs before priority 10.
    return api_client.create_claim(
        F.claim_payload(ctx["deal_id"], ctx["deal_version"], CASES, GROSS),
        ctx["distributor_headers"],
    )


FORBIDDEN_ROLE_CASES = [
    ("analyst_may_not_approve_a_rate_card", _analyst_approves_rate_card),
    ("analyst_may_not_settle_a_recovery", _analyst_settles_recovery),
    ("admin_may_not_normalize_a_feed", _admin_normalizes_batch),
    ("arbiter_may_not_ingest_a_purchase_line", _arbiter_ingests_purchase_line),
    ("rep_may_not_activate_a_member", _rep_activates_member),
    ("member_operator_may_not_drive_the_clock", _member_operator_drives_the_clock),
    ("distributor_feed_may_not_file_a_claim", _distributor_feed_files_a_claim),
]


@pytest.mark.parametrize(
    "invoke",
    [case[1] for case in FORBIDDEN_ROLE_CASES],
    ids=[case[0] for case in FORBIDDEN_ROLE_CASES],
)
def test_a_role_outside_the_endpoints_list_is_refused_before_any_other_check(invoke):
    """Seven operations, each attempted by a recognized role the routing table
    does not list, must all draw ERR_FORBIDDEN_ROLE with HTTP 403 — never the
    state, version or enrollment error the same request would earn later.
    PRD: "When the role is recognized but the endpoint does not list it among
    its authorized roles, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD: "Requests are validated as an ordered ladder, and the **first** check
    that fails determines the response."
    Design: Corner/rbac/roles_cannot_run_another_roles_exclusive_operations
    """
    ctx = _setup_forbidden_role_grid()

    response = invoke(ctx)

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_refused_roles_mutate_nothing_and_the_entitled_role_still_succeeds():
    """The seven refusals leave the world untouched, and the very approve the
    analyst was refused succeeds for GpoAdmin while the very normalize the
    admin was refused succeeds for RebateAnalyst.
    PRD: "A `RebateAnalyst` cannot approve rate cards, cannot settle recoveries
    and cannot decide disputes."
    PRD: "`updated_at` uses the same ISO 8601 UTC format and is refreshed to
    the current logical-clock instant whenever any field of the record changes."
    Design: Corner/rbac/roles_cannot_run_another_roles_exclusive_operations
    """
    ctx = _setup_forbidden_role_grid()
    for _name, invoke in FORBIDDEN_ROLE_CASES:
        validate_error(invoke(ctx), ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    # Nothing the seven refusals aimed at moved.
    card = validate_success(api_client.get_rate_card(ctx["card_id"], ADMIN), 200)
    assert card["status"] == RateCardStatus.PROPOSED.value
    batch = validate_success(api_client.get_purchase_batch(ctx["batch_id"], ANALYST), 200)
    assert batch["normalization_status"] == NormalizationStatus.RECEIVED.value
    assert batch["line_count"] == 0
    assert batch["audit_status"] == AuditStatus.NOT_AUDITED.value
    member = fx.read_member(ctx["member_id"])
    assert member["enrollment_status"] == MemberEnrollmentStatus.PENDING.value
    _rows, meta = validate_paginated(api_client.list_claims(ADMIN))
    assert meta["total_count"] == 0

    # 8: the same approve succeeds for GpoAdmin. Its updated_at also proves the
    # MemberOperator never moved the clock off 2026-08-01T09:00:00.000Z.
    card = validate_success(api_client.approve_rate_card(ctx["card_id"], ADMIN), 200)
    assert card["status"] == RateCardStatus.APPROVED.value
    assert_instants_equal(card["updated_at"], CLOCK_0900)

    # 9: the same normalize succeeds for RebateAnalyst. The PRD refuses an
    # empty batch with ERR_INVALID_STATE ("an empty batch with a `line_count`
    # of 0, is rejected with `ERR_INVALID_STATE`"), so the feed is authorized
    # and one line ingested first — the admin's 403 above was raised while the
    # batch was still empty, which is exactly the priority the instance pins.
    letter = fx.submit_letter(ctx["member_id"], ctx["distributor_id"])
    fx.countersign_letter(letter["id"], ctx["distributor_id"])
    fx.activate_member(ctx["member_id"])
    line = fx.create_line(ctx["batch_id"], ctx["member_id"], ctx["distributor_id"])
    assert line["match_status"] == MatchStatus.UNMATCHED.value
    batch = validate_success(api_client.normalize_batch(ctx["batch_id"], ANALYST), 200)
    assert batch["normalization_status"] == NormalizationStatus.NORMALIZED.value


# ============================================================================
# Instance: member_operator_cannot_act_outside_its_own_member_id
# ============================================================================


def _setup_member_scope_grid():
    """Two ACTIVE members, each with its own ACTIVE letter from METRO-01, and an
    EVIDENCE_REQUESTED dispute on Harbor Grill's own 30-case accrual."""
    ctx = _reference_data()
    other = fx.create_member(
        ctx["tier"]["id"],
        legal_name="Pier 9 Oyster Bar Inc",
        committed_annual_spend_cents=9_000_000,
    )
    # Both letters end in 2027 so that the 2027-06-01 window the refused
    # submission below asks for does not overlap them: the only defect in that
    # request is the foreign member_id.
    ctx["member"], letter = _active_member_with_letter(ctx, effective_to=LETTER_TO_2027)
    ctx["letter"] = letter
    ctx["letter_id"] = letter["id"]
    ctx["other"], _other_letter = _active_member_with_letter(
        ctx,
        member=other,
        scope=LetterScope.PURCHASE_DATA_ONLY.value,
        effective_to=LETTER_TO_2027,
    )
    ctx["other_id"] = other["id"]
    ctx["other_headers"] = make_member_operator_headers(other["id"])
    _priced_deal(ctx)
    _accrued_june_line(ctx)
    dispute = fx.open_dispute(
        ctx["accrual_id"],
        ctx["member_id"],
        SHARE,
        DisputeReasonCode.RATE_MISMATCH.value,
    )
    ctx["dispute"] = fx.request_evidence(dispute["id"])
    ctx["dispute_id"] = dispute["id"]
    assert ctx["dispute"]["status"] == DisputeStatus.EVIDENCE_REQUESTED.value
    return ctx


def _foreign_member_reads_savings_report(ctx):
    # Reached through the {member_id} PATH SEGMENT.
    return api_client.get_savings_report(
        ctx["member_id"],
        ctx["other_headers"],
        F.savings_report_params(C.JUNE_START, C.JUNE_END),
    )


def _foreign_member_opens_dispute(ctx):
    # Reached through dispute -> accrual.member_id. Priority 5 outranks the
    # duplicate-open-dispute check at priority 38.
    return api_client.create_dispute(
        F.dispute_payload(
            ctx["accrual_id"], 100, DisputeReasonCode.UNITS_MISMATCH.value
        ),
        ctx["other_headers"],
    )


def _foreign_member_submits_letter(ctx):
    # Reached through the letter's member_id in the BODY.
    return api_client.create_authorization_letter(
        F.authorization_letter_payload(
            ctx["member_id"],
            ctx["distributor_id"],
            effective_from="2027-06-01T00:00:00.000Z",
            effective_to="2027-12-01T00:00:00.000Z",
            scope=LetterScope.PURCHASE_DATA_ONLY.value,
        ),
        ctx["other_headers"],
    )


def _foreign_member_revokes_letter(ctx):
    # Reached through letter.member_id on a path-addressed action.
    return api_client.revoke_letter(ctx["letter_id"], ctx["other_headers"])


def _foreign_member_submits_evidence(ctx):
    # Priority 5 outranks the transition precondition: the dispute really is in
    # EVIDENCE_REQUESTED and the payload really is valid.
    return api_client.submit_evidence(
        ctx["dispute_id"], {"evidence_note": "Not my dispute."}, ctx["other_headers"]
    )


MEMBER_SCOPE_CASES = [
    ("savings_report_path_segment", _foreign_member_reads_savings_report),
    ("open_dispute_via_accrual_member_id", _foreign_member_opens_dispute),
    ("submit_letter_member_id_in_body", _foreign_member_submits_letter),
    ("revoke_letter_via_letter_member_id", _foreign_member_revokes_letter),
    ("submit_evidence_via_accrual_member_id", _foreign_member_submits_evidence),
]


@pytest.mark.parametrize(
    "invoke",
    [case[1] for case in MEMBER_SCOPE_CASES],
    ids=[case[0] for case in MEMBER_SCOPE_CASES],
)
def test_member_operator_outside_its_own_member_id_is_refused(invoke):
    """All five member-scoped operations reach their owning member — through the
    path segment, the body, the letter and the cited accrual — and a foreign
    MemberOperator is refused on every one of them.
    PRD: "Five operations are scoped this way: submitting an authorization
    letter (compared against the `member_id` in the body), revoking an
    authorization letter (compared against the letter's `member_id`), opening a
    dispute and submitting evidence on one (compared against the cited
    accrual's `member_id`), and requesting a member savings report (compared
    against the member id in the path). A mismatch on any of the five is
    rejected with `ERR_MEMBER_SCOPE_VIOLATION` (HTTP 403)."
    Design: Corner/rbac/member_operator_cannot_act_outside_its_own_member_id
    """
    ctx = _setup_member_scope_grid()

    response = invoke(ctx)

    validate_error(response, ApiErrorId.ERR_MEMBER_SCOPE_VIOLATION, 403)


def test_member_scope_rule_is_role_conditioned_and_the_owner_still_acts():
    """The five refusals change nothing, and the same reads and the same
    submit-evidence succeed for GpoAdmin and for the owning member, because the
    rule is conditioned on X-User-Role == MemberOperator.
    PRD: "When `X-User-Role` is `MemberOperator`, `X-User-ID` is the `id` of the
    acting `Member`; ownership checks on any resource that references a `Member`
    compare the resource's member foreign key to `X-User-ID`."
    PRD: "A `MemberOperator` may request its own report, and a `GpoAdmin` or
    `RebateAnalyst` may request any member's".
    Design: Corner/rbac/member_operator_cannot_act_outside_its_own_member_id
    """
    ctx = _setup_member_scope_grid()
    for _name, invoke in MEMBER_SCOPE_CASES:
        validate_error(invoke(ctx), ApiErrorId.ERR_MEMBER_SCOPE_VIOLATION, 403)

    # No refusal changed anything.
    letter = validate_success(
        api_client.get_authorization_letter(ctx["letter_id"], ADMIN), 200
    )
    assert letter["status"] == LetterStatus.ACTIVE.value
    assert fx.read_member(ctx["member_id"])["active_letter_count"] == 1
    _rows, dispute_meta = validate_paginated(
        api_client.list_disputes(ADMIN, {"accrual_id": ctx["accrual_id"]})
    )
    assert dispute_meta["total_count"] == 1
    _rows, letter_meta = validate_paginated(api_client.list_authorization_letters(ADMIN))
    assert letter_meta["total_count"] == 2

    # 6 and 7: GpoAdmin reads the report unhindered, and so does the owner.
    params = F.savings_report_params(C.JUNE_START, C.JUNE_END)
    for headers in (ADMIN, ctx["member_headers"]):
        report = validate_success(
            api_client.get_savings_report(ctx["member_id"], headers, params), 200
        )
        assert report["member_id"] == ctx["member_id"]

    # 8: the same submit-evidence succeeds for the owning member.
    response = api_client.submit_evidence(
        ctx["dispute_id"], {"evidence_note": "Invoice 88213 attached."},
        ctx["member_headers"],
    )
    dispute = validate_success(response, 200)
    assert dispute["status"] == DisputeStatus.OPEN.value
    assert dispute["evidence_round_count"] == 1


# ============================================================================
# Instance: distributor_feed_cannot_act_outside_its_own_distributor_id
# ============================================================================


def _setup_distributor_scope_grid():
    """Two distributors, an ACTIVE letter from METRO-01 and a SUBMITTED letter to
    SYSCO-02, and one RECEIVED batch per distributor, both opened by the analyst."""
    ctx = _reference_data()
    other = fx.create_distributor(
        name="Sysco Northeast",
        dba_code="SYSCO-02",
        contracted_markup_bps=600,
    )
    ctx["other_distributor"] = other
    ctx["other_distributor_id"] = other["id"]
    ctx["other_distributor_headers"] = make_distributor_feed_headers(other["id"])
    ctx["member"], ctx["letter"] = _active_member_with_letter(ctx)
    # A second letter, to the OTHER distributor, deliberately left SUBMITTED.
    ctx["other_letter"] = fx.submit_letter(ctx["member_id"], other["id"],
                                           scope=LetterScope.PURCHASE_DATA_ONLY.value)
    ctx["other_letter_id"] = ctx["other_letter"]["id"]
    assert ctx["other_letter"]["status"] == LetterStatus.SUBMITTED.value
    # Both feeds are opened by the analyst, so neither batch's existence depends
    # on the scope rule under test.
    ctx["batch"] = _open_analyst_batch(ctx["distributor_id"])
    ctx["batch_id"] = ctx["batch"]["id"]
    ctx["other_batch"] = _open_analyst_batch(other["id"], source_reference="SYSCO-2026-06")
    ctx["other_batch_id"] = ctx["other_batch"]["id"]
    return ctx


def _foreign_feed_opens_a_batch(ctx):
    # Reached through the distributor_id in the BODY.
    return api_client.create_purchase_batch(
        F.purchase_batch_payload(
            ctx["other_distributor_id"],
            period_start=C.JULY_START,
            period_end=C.JULY_END,
            source_reference="SYSCO-2026-07",
        ),
        ctx["distributor_headers"],
    )


def _foreign_feed_countersigns(ctx):
    # Reached through the letter's distributor_id.
    return api_client.countersign_letter(
        ctx["other_letter_id"],
        {"decision": CountersignDecision.ACCEPT.value},
        ctx["distributor_headers"],
    )


def _foreign_feed_ingests_a_line(ctx):
    # Reached through the owning batch's distributor_id. Priority 6 outranks the
    # LOA check at priority 15, which would otherwise fire because this member's
    # letter to the other distributor is still only SUBMITTED.
    return api_client.create_purchase_line(
        F.purchase_line_payload(ctx["other_batch_id"], ctx["member_id"]),
        ctx["distributor_headers"],
    )


DISTRIBUTOR_SCOPE_CASES = [
    ("open_batch_distributor_id_in_body", _foreign_feed_opens_a_batch),
    ("countersign_via_letter_distributor_id", _foreign_feed_countersigns),
    ("ingest_line_via_batch_distributor_id", _foreign_feed_ingests_a_line),
]


@pytest.mark.parametrize(
    "invoke",
    [case[1] for case in DISTRIBUTOR_SCOPE_CASES],
    ids=[case[0] for case in DISTRIBUTOR_SCOPE_CASES],
)
def test_distributor_feed_outside_its_own_distributor_id_is_refused(invoke):
    """METRO-01's feed account is refused on all three distributor-scoped
    operations when the target belongs to SYSCO-02, whether the foreign id is
    read from the body, from the letter or from the owning batch.
    PRD: "Three operations are scoped this way: countersigning an authorization
    letter (compared against the letter's `distributor_id`), opening a purchase
    batch (compared against the `distributor_id` in the body), and ingesting a
    purchase line (compared against the owning batch's `distributor_id`). A
    mismatch on any of the three is rejected with
    `ERR_DISTRIBUTOR_SCOPE_VIOLATION` (HTTP 403)."
    Design: Corner/rbac/distributor_feed_cannot_act_outside_its_own_distributor_id
    """
    ctx = _setup_distributor_scope_grid()

    response = invoke(ctx)

    validate_error(response, ApiErrorId.ERR_DISTRIBUTOR_SCOPE_VIOLATION, 403)


def test_the_owning_distributor_countersigns_the_letter_the_foreign_feed_could_not():
    """The refused countersignature left the letter untouched, and SYSCO-02's own
    feed account then accepts it and moves both active_letter_count figures.
    PRD: "Either branch requires the letter to still be `SUBMITTED`, requires
    the acting `DistributorFeed` account's `X-User-ID` to equal the letter's
    `distributor_id`".
    PRD: "A `decision` of `ACCEPT` moves the letter `SUBMITTED → ACTIVE`, stamps
    `countersigned_at` with the current logical-clock instant, and increments
    both the member's and the distributor's `active_letter_count` by 1."
    Design: Corner/rbac/distributor_feed_cannot_act_outside_its_own_distributor_id
    """
    ctx = _setup_distributor_scope_grid()
    validate_error(
        _foreign_feed_countersigns(ctx), ApiErrorId.ERR_DISTRIBUTOR_SCOPE_VIOLATION, 403
    )
    # Still SUBMITTED: the refusal was raised before any transition.
    assert validate_success(
        api_client.get_authorization_letter(ctx["other_letter_id"], ADMIN), 200
    )["status"] == LetterStatus.SUBMITTED.value

    response = api_client.countersign_letter(
        ctx["other_letter_id"],
        {"decision": CountersignDecision.ACCEPT.value},
        ctx["other_distributor_headers"],
    )
    letter = validate_success(response, 200)
    assert_authorization_letter(letter)
    assert letter["status"] == LetterStatus.ACTIVE.value
    assert_instants_equal(letter["countersigned_at"], CLOCK_0900)
    assert fx.read_member(ctx["member_id"])["active_letter_count"] == 2
    assert fx.read_distributor(ctx["other_distributor_id"])["active_letter_count"] == 1
    assert fx.read_distributor(ctx["distributor_id"])["active_letter_count"] == 1


def test_distributor_scope_rule_is_role_conditioned_and_the_owner_still_feeds():
    """A RebateAnalyst opens a feed for SYSCO-02 with no scope check at all, and
    METRO-01's feed ingests into its own batch — while SYSCO-02's batch, the one
    the refusal targeted, is still empty.
    PRD: "Either the `DistributorFeed` account itself or a `RebateAnalyst` opens
    a batch by supplying `distributor_id`, the inclusive `period_start` and
    `period_end` with the end not before the start, and a `source_reference` of
    3 to 40 characters that is the distributor's own file reference".
    PRD: "A `DistributorFeed` caller's `X-User-ID` matches the distributor that
    owns the target resource — otherwise `ERR_DISTRIBUTOR_SCOPE_VIOLATION`."
    Design: Corner/rbac/distributor_feed_cannot_act_outside_its_own_distributor_id
    """
    ctx = _setup_distributor_scope_grid()
    for _name, invoke in DISTRIBUTOR_SCOPE_CASES:
        validate_error(invoke(ctx), ApiErrorId.ERR_DISTRIBUTOR_SCOPE_VIOLATION, 403)

    # The analyst carries no distributor identity, so the very batch the feed was
    # refused is created for the asking.
    analyst_batch = validate_success(
        api_client.create_purchase_batch(
            F.purchase_batch_payload(
                ctx["other_distributor_id"],
                period_start=C.JULY_START,
                period_end=C.JULY_END,
                source_reference="SYSCO-2026-07",
            ),
            ANALYST,
        ),
        201,
    )
    assert_purchase_batch(analyst_batch)
    assert analyst_batch["distributor_id"] == ctx["other_distributor_id"]
    assert analyst_batch["normalization_status"] == NormalizationStatus.RECEIVED.value

    # The same ingest succeeds into METRO-01's own batch.
    response = api_client.create_purchase_line(
        F.purchase_line_payload(ctx["batch_id"], ctx["member_id"]),
        ctx["distributor_headers"],
    )
    line = validate_success(response, 201)
    assert_purchase_line(line)
    assert line["cases_shipped"] == CASES
    own_batch = fx.read_batch(ctx["batch_id"])
    assert own_batch["line_count"] == 1
    assert own_batch["total_cases_ingested"] == CASES
    foreign_batch = fx.read_batch(ctx["other_batch_id"])
    assert foreign_batch["line_count"] == 0
    assert foreign_batch["total_cases_ingested"] == 0


# ============================================================================
# Instance: an_arbiter_who_accrued_or_validated_cannot_decide_that_dispute
# ============================================================================


def _setup_sod_dispute():
    """One OPEN dispute whose workflow records three distinct identifiers:
    accrued_by_user_id = dual-01, validated_by_user_id = dual-02 and
    opened_by_user_id = the member's own id."""
    ctx = _reference_data()
    ctx["member"], ctx["letter"] = _active_member_with_letter(ctx)
    _priced_deal(ctx)
    # dual-01 wears the analyst's hat for the accrual run.
    _accrued_june_line(ctx, analyst_headers=DUAL_ONE_ANALYST)
    assert fx.read_batch(ctx["batch_id"])["accrued_by_user_id"] == DUAL_ONE
    claim = fx.create_claim(ctx["deal_id"], CASES, GROSS)
    claim = fx.reconcile_claim(claim["id"], DUAL_ONE_ANALYST)
    ctx["claim_id"] = claim["id"]
    assert claim["status"] == ClaimStatus.RECONCILED.value
    # dual-02 validates, so the two recorded analysts are different people.
    accrual = fx.validate_accrual(ctx["accrual_id"], claim["id"], DUAL_TWO_ANALYST)
    assert accrual["status"] == AccrualStatus.VALIDATED.value
    assert accrual["validated_by_user_id"] == DUAL_TWO
    dispute = fx.open_dispute(
        ctx["accrual_id"],
        ctx["member_id"],
        SHARE,
        DisputeReasonCode.RATE_MISMATCH.value,
        claim_id=ctx["claim_id"],
    )
    assert dispute["opened_by_user_id"] == ctx["member_id"]
    assert dispute["status"] == DisputeStatus.OPEN.value
    ctx["dispute"] = dispute
    ctx["dispute_id"] = dispute["id"]
    return ctx


def _evidence_round(ctx):
    """One arbiter/member evidence exchange, leaving the dispute OPEN again."""
    assert fx.request_evidence(ctx["dispute_id"], ARBITER)["status"] == (
        DisputeStatus.EVIDENCE_REQUESTED.value
    )
    dispute = fx.submit_evidence(ctx["dispute_id"], ctx["member_id"], "Rate sheet attached")
    assert dispute["status"] == DisputeStatus.OPEN.value
    assert dispute["evidence_round_count"] == 1
    return dispute


def test_the_opener_cannot_request_evidence_on_its_own_dispute_but_an_arbiter_can():
    """The member's own id, presented under the DisputeArbiter role, collides with
    opened_by_user_id and is barred; a genuine arbiter runs the same call.
    PRD: "Requesting evidence is barred when the caller's `X-User-ID` equals the
    dispute's `opened_by_user_id`, which draws `ERR_SEGREGATION_OF_DUTIES`."
    Design: Corner/rbac/an_arbiter_who_accrued_or_validated_cannot_decide_that_dispute
    """
    ctx = _setup_sod_dispute()

    response = api_client.request_evidence(
        ctx["dispute_id"], make_headers(Role.DISPUTE_ARBITER.value, ctx["member_id"])
    )

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    dispute = validate_success(api_client.request_evidence(ctx["dispute_id"], ARBITER), 200)
    assert dispute["status"] == DisputeStatus.EVIDENCE_REQUESTED.value
    assert dispute["evidence_round_count"] == 0


def _accruer_decides(ctx):
    # dual-01 is the batch's accrued_by_user_id.
    return api_client.decide_dispute(
        ctx["dispute_id"],
        {"decision": DisputeDecision.REJECT.value, "decision_note": "Accruer ruling"},
        DUAL_ONE_ARBITER,
    )


def _validator_decides(ctx):
    # dual-02 is the accrual's validated_by_user_id.
    return api_client.decide_dispute(
        ctx["dispute_id"],
        {"decision": DisputeDecision.REJECT.value, "decision_note": "Validator ruling"},
        DUAL_TWO_ARBITER,
    )


def _opener_decides(ctx):
    # The member id is the dispute's opened_by_user_id.
    return api_client.decide_dispute(
        ctx["dispute_id"],
        {"decision": DisputeDecision.UPHOLD.value, "decision_note": "Opener ruling"},
        make_headers(Role.DISPUTE_ARBITER.value, ctx["member_id"]),
    )


SOD_DECIDE_CASES = [
    ("accrued_by_user_id_of_the_batch", _accruer_decides),
    ("validated_by_user_id_of_the_accrual", _validator_decides),
    ("opened_by_user_id_of_the_dispute", _opener_decides),
]


@pytest.mark.parametrize(
    "invoke",
    [case[1] for case in SOD_DECIDE_CASES],
    ids=[case[0] for case in SOD_DECIDE_CASES],
)
def test_every_identifier_already_on_the_workflow_is_barred_from_deciding(invoke):
    """All three recorded identifiers are refused a decision even though each
    presents a valid DisputeArbiter role and the dispute is squarely OPEN, and
    the bar catches UPHOLD exactly as it catches REJECT.
    PRD: "Deciding is barred when the caller's `X-User-ID` equals the dispute's
    `opened_by_user_id`, or the cited accrual's `validated_by_user_id`, or the
    `accrued_by_user_id` of the purchase batch the accrual's line arrived on.
    Any of these collisions is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP
    403)."
    Design: Corner/rbac/an_arbiter_who_accrued_or_validated_cannot_decide_that_dispute
    """
    ctx = _setup_sod_dispute()
    _evidence_round(ctx)

    response = invoke(ctx)

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)


def test_an_uninvolved_arbiter_decides_the_dispute_the_other_three_could_not():
    """The three refusals leave the dispute and the accrual exactly as they were,
    and arbiter-02 — the same role, a different identifier — then rejects it.
    PRD: "The bar is on the identifier, not on the role name: two different
    `DisputeArbiter` operators are free to act on each other's disputes, and a
    single operator who wore an analyst's hat earlier cannot then wear the
    arbiter's."
    PRD: "The dispute moves `OPEN → REJECTED` and the accrual returns from
    `DISPUTED` to exactly the status recorded in `accrual_status_before`".
    Design: Corner/rbac/an_arbiter_who_accrued_or_validated_cannot_decide_that_dispute
    """
    ctx = _setup_sod_dispute()
    _evidence_round(ctx)
    for _name, invoke in SOD_DECIDE_CASES:
        validate_error(invoke(ctx), ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    # Nothing was decided and nothing was stored.
    dispute = fx.read_dispute(ctx["dispute_id"])
    assert dispute["status"] == DisputeStatus.OPEN.value
    assert dispute["decided_by_user_id"] is None
    assert dispute["decision_note"] is None
    assert dispute["evidence_round_count"] == 1
    assert dispute["accrual_status_before"] == AccrualStatus.VALIDATED.value
    assert fx.read_accrual(ctx["accrual_id"])["status"] == AccrualStatus.DISPUTED.value

    response = api_client.decide_dispute(
        ctx["dispute_id"],
        {"decision": DisputeDecision.REJECT.value,
         "decision_note": "Rate card matches the invoiced rate."},
        ARBITER_OTHER,
    )
    dispute = validate_success(response, 200)
    assert dispute["status"] == DisputeStatus.REJECTED.value
    assert dispute["decided_by_user_id"] == ARBITER_2
    assert dispute["decision_note"] == "Rate card matches the invoiced rate."

    # A REJECT is a pure state restore: no money and no counter moves.
    accrual = fx.read_accrual(ctx["accrual_id"])
    assert accrual["status"] == AccrualStatus.VALIDATED.value
    assert accrual["validated_by_user_id"] == DUAL_TWO
    assert accrual["member_share_cents"] == SHARE
    assert accrual["reversal_reason"] == "NONE"
    member = fx.read_member(ctx["member_id"])
    assert member["dispute_reversal_count"] == 0
    assert member["reconciliation_posture"] == ReconciliationPosture.CLEAR.value
    assert member["accrued_member_share_cents"] == SHARE
