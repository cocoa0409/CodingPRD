"""Lifecycle transition corners: declared edges, refused edges and initial states.

Every test here translates exactly one `section: state_machines` corner design
instance. The database is empty before each test, so each one builds its whole
world through API calls and then issues the call under test through the raw
api_client so both the HTTP status and the error_id are asserted. A refused
transition is always checked twice: the status did not move, and the record's
version did not move either.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_authorization_letter,
    assert_instants_equal,
    assert_purchase_batch,
    validate_unpaginated,
)
from test_helpers.test_users import (
    make_analyst_headers,
    make_distributor_feed_headers,
    make_gpo_admin_headers,
    make_member_operator_headers,
    make_rep_headers,
)
from test_helpers.types import (
    AuditStatus,
    ClaimStatus,
    CountersignDecision,
    DealStatus,
    DistributorStatus,
    ItemStatus,
    LetterScope,
    LetterStatus,
    MemberEnrollmentStatus,
    NormalizationStatus,
    RateCardStatus,
    ReconciliationPosture,
    RecoveryOutcome,
)

ADMIN = make_gpo_admin_headers()
ANALYST = make_analyst_headers()
REP = make_rep_headers()

# The canonical June feed's audit figures: min(900, 700) == 700 bps on base
# 8533 gives allowed unit 9130 (excess 10 over 30 cases) and on base 8540
# gives allowed unit 9138 (excess 2 over 40 cases).
LINE_A_OVERBILLED_CENTS = 300
LINE_B_OVERBILLED_CENTS = 80
BATCH_OVERBILLED_CENTS = 380

CLAIMED_UNITS = 70
CLAIMED_AMOUNT_CENTS = 10500


# ============================================================ world builders ==
# Each builder performs its hops one at a time so a test can read a version or
# a counter between two hops.


def submitted_letter_world(scope: str = None) -> dict:
    """An ACTIVE distributor, a PENDING member and one SUBMITTED letter."""
    tier = fx.create_tier()
    distributor = fx.create_distributor()
    member = fx.create_member(tier["id"])
    overrides = {} if scope is None else {"scope": scope}
    letter = fx.submit_letter(member["id"], distributor["id"], **overrides)
    return {
        "tier": tier,
        "distributor": distributor,
        "member": member,
        "letter": letter,
        "tier_id": tier["id"],
        "member_id": member["id"],
        "distributor_id": distributor["id"],
        "letter_id": letter["id"],
    }


def active_letter_world() -> dict:
    """The same world one hop on: the distributor has accepted the letter."""
    ctx = submitted_letter_world()
    ctx["letter"] = fx.countersign_letter(ctx["letter_id"], ctx["distributor_id"])
    return ctx


def activatable_draft_deal() -> dict:
    """A DRAFT deal whose single ACTIVE item carries one APPROVED card."""
    deal = fx.create_deal()
    item = fx.create_item(deal["id"])
    card = fx.create_card(item["id"])
    card = fx.approve_card(card["id"])
    return {"deal": deal, "item": item, "card": card, "deal_id": deal["id"]}


def recovery_requested_june_batch() -> dict:
    """The June feed audited at 380 cents overbilled and demanded back.

    The batch is normalized before the audit runs because the PRD only lets the
    markup audit run "on a batch whose `audit_status` is `NOT_AUDITED` and whose
    `normalization_status` is either `NORMALIZED` or `ACCRUED`".
    """
    ctx = active_letter_world()
    ctx["member"] = fx.activate_member(ctx["member_id"])
    batch = fx.create_batch(ctx["distributor_id"])
    ctx["batch_id"] = batch["id"]
    ctx["line_a"] = fx.create_line(batch["id"], ctx["member_id"], ctx["distributor_id"])
    ctx["line_b"] = fx.create_line_b(
        batch["id"], ctx["member_id"], ctx["distributor_id"]
    )
    ctx["batch"] = fx.normalize(batch["id"])
    ctx["batch"] = fx.audit_markup(batch["id"])
    ctx["batch"] = fx.request_recovery(batch["id"])
    return ctx


def all_letters() -> list:
    """Every authorization letter the system holds, read with a wide page."""
    return validate_unpaginated(
        api_client.list_authorization_letters(ADMIN, {"limit": C.MAX_LIMIT})
    )


def active_letters() -> list:
    return [row for row in all_letters() if row["status"] == LetterStatus.ACTIVE.value]


# ============================================================================
# AuthorizationLetter SUBMITTED -> DECLINED: the other edge out of SUBMITTED
# ============================================================================

def test_countersign_decline_moves_the_letter_to_declined_and_moves_no_counter():
    """DECLINE takes the second edge out of SUBMITTED: the letter is DECLINED,
    countersigned_at is never stamped, and neither side's active_letter_count
    moves, which is the whole observable difference from ACCEPT.

    PRD: "A `decision` of `DECLINE` moves the letter `SUBMITTED → DECLINED`,
    leaves `countersigned_at` null, and changes no counter on either side."

    Design: Corner/state_machines/countersign_decline_moves_letter_to_declined_without_counters
    """
    ctx = submitted_letter_world(LetterScope.PURCHASE_DATA_ONLY.value)

    response = api_client.countersign_letter(
        ctx["letter_id"],
        {"decision": CountersignDecision.DECLINE.value},
        make_distributor_feed_headers(ctx["distributor_id"]),
    )
    letter = validate_success(response, 200)
    assert_authorization_letter(letter)
    assert letter["status"] == LetterStatus.DECLINED.value
    assert letter["countersigned_at"] is None, (
        "the declining branch leaves countersigned_at null"
    )

    member = fx.read_member(ctx["member_id"])
    distributor = fx.read_distributor(ctx["distributor_id"])
    assert member["active_letter_count"] == 0, "a declined letter authorizes nothing"
    assert distributor["active_letter_count"] == 0

    assert active_letters() == [], (
        "no letter anywhere reached ACTIVE, so the ACTIVE population is empty"
    )


def test_a_declined_letter_is_terminal_and_enrolls_nobody():
    """DECLINED is final: a second countersign carrying ACCEPT cannot reopen it,
    and the member still cannot be activated because it holds no ACTIVE letter.

    PRD: "`DECLINED`, `REVOKED` and `EXPIRED` are all final: none of them can be
    reopened, and a member wanting authorization again must submit a fresh
    letter."

    Design: Corner/state_machines/countersign_decline_moves_letter_to_declined_without_counters
    """
    ctx = submitted_letter_world(LetterScope.PURCHASE_DATA_ONLY.value)
    declined = fx.countersign_letter(
        ctx["letter_id"],
        ctx["distributor_id"],
        CountersignDecision.DECLINE.value,
    )
    assert declined["status"] == LetterStatus.DECLINED.value
    version_after_decline = declined["version"]

    replay = api_client.countersign_letter(
        ctx["letter_id"],
        {"decision": CountersignDecision.ACCEPT.value},
        make_distributor_feed_headers(ctx["distributor_id"]),
    )
    validate_error(replay, ApiErrorId.ERR_INVALID_STATE, 409)

    letter = validate_success(
        api_client.get_authorization_letter(ctx["letter_id"], ADMIN), 200
    )
    assert letter["status"] == LetterStatus.DECLINED.value, (
        "the refused ACCEPT left the terminal status exactly where it was"
    )
    assert letter["countersigned_at"] is None
    assert letter["version"] == version_after_decline, (
        "a rejected transition performs no write, so the version stands still"
    )

    activate = api_client.activate_member(ctx["member_id"], ADMIN)
    validate_error(activate, ApiErrorId.ERR_MEMBER_HAS_NO_ACTIVE_LOA, 422)

    member = fx.read_member(ctx["member_id"])
    assert member["enrollment_status"] == MemberEnrollmentStatus.PENDING.value
    assert member["active_letter_count"] == 0


# ============================================================================
# Member PENDING -> ACTIVE: the precondition is a counter, not a status
# ============================================================================

def test_activate_is_refused_while_the_only_letter_is_still_submitted():
    """A SUBMITTED letter is not authorization: the member's active_letter_count
    is still 0, so activation is refused and the member does not move at all.

    PRD: "Both directions require the member to hold at least one `ACTIVE`
    authorization letter — an `active_letter_count` of at least 1 — and a member
    with none is rejected with `ERR_MEMBER_HAS_NO_ACTIVE_LOA`."

    Design: Corner/state_machines/member_activate_without_an_active_letter_is_rejected
    """
    ctx = submitted_letter_world()
    assert ctx["letter"]["status"] == LetterStatus.SUBMITTED.value
    assert ctx["member"]["version"] == 1

    response = api_client.activate_member(ctx["member_id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_MEMBER_HAS_NO_ACTIVE_LOA, 422)

    member = fx.read_member(ctx["member_id"])
    assert member["enrollment_status"] == MemberEnrollmentStatus.PENDING.value, (
        "the refused activation left the member PENDING"
    )
    assert member["version"] == 1, "a rejected transition performs no write"
    assert member["active_letter_count"] == 0
    assert member["reconciliation_posture"] == ReconciliationPosture.CLEAR.value
    assert member["payout_hold"] is False


def test_countersign_flips_the_same_activate_call_from_refused_to_accepted():
    """Nothing about the activate request changes; the distributor's ACCEPT is
    what lifts active_letter_count to 1, and the identical call then returns 200
    with exactly one further version step on the member.

    PRD: "A `decision` of `ACCEPT` moves the letter `SUBMITTED → ACTIVE`, stamps
    `countersigned_at` with the current logical-clock instant, and increments
    both the member's and the distributor's `active_letter_count` by 1."

    Design: Corner/state_machines/member_activate_without_an_active_letter_is_rejected
    """
    ctx = submitted_letter_world()
    validate_error(
        api_client.activate_member(ctx["member_id"], ADMIN),
        ApiErrorId.ERR_MEMBER_HAS_NO_ACTIVE_LOA,
        422,
    )

    countersign = api_client.countersign_letter(
        ctx["letter_id"],
        {"decision": CountersignDecision.ACCEPT.value},
        make_distributor_feed_headers(ctx["distributor_id"]),
    )
    letter = validate_success(countersign, 200)
    assert letter["status"] == LetterStatus.ACTIVE.value
    assert_instants_equal(letter["countersigned_at"], C.CLOCK_EPOCH)

    member_before = fx.read_member(ctx["member_id"])
    distributor = fx.read_distributor(ctx["distributor_id"])
    assert member_before["active_letter_count"] == 1
    assert distributor["active_letter_count"] == 1
    assert member_before["enrollment_status"] == MemberEnrollmentStatus.PENDING.value

    response = api_client.activate_member(ctx["member_id"], ADMIN)
    member = validate_success(response, 200)
    assert member["enrollment_status"] == MemberEnrollmentStatus.ACTIVE.value
    assert member["version"] == member_before["version"] + 1, (
        "activation increments the member's version by exactly 1"
    )
    assert member["reconciliation_posture"] == ReconciliationPosture.CLEAR.value, (
        "activation touches neither the posture nor the hold"
    )
    assert member["payout_hold"] is False


# ============================================================================
# PurchaseBatch RECOVERY_REQUESTED -> WRITTEN_OFF and Distributor -> SUSPENDED
# ============================================================================

def test_write_off_settles_at_zero_and_keeps_the_overbilled_finding():
    """A write-off credits nothing: recovered_cents is forced to 0 and no member
    receives a recovery credit, while the batch's 380-cent finding survives as
    the audit record of what was forgiven.

    PRD: "An outcome of `WRITTEN_OFF` forces `recovered_cents` to 0, moves the
    batch `RECOVERY_REQUESTED → WRITTEN_OFF`, credits no member at all"

    Design: Corner/state_machines/settle_recovery_written_off_suspends_the_distributor
    """
    ctx = recovery_requested_june_batch()
    line_a = fx.read_line(ctx["line_a"]["id"])
    line_b = fx.read_line(ctx["line_b"]["id"])
    assert line_a["overbilled_cents"] == LINE_A_OVERBILLED_CENTS, (
        "allowed unit 9130, excess 10 per case over 30 cases"
    )
    assert line_b["overbilled_cents"] == LINE_B_OVERBILLED_CENTS, (
        "allowed unit 9138, excess 2 per case over 40 cases"
    )
    assert ctx["batch"]["overbilled_cents"] == BATCH_OVERBILLED_CENTS
    assert ctx["batch"]["audit_status"] == AuditStatus.RECOVERY_REQUESTED.value

    response = api_client.settle_recovery(
        ctx["batch_id"], {"outcome": RecoveryOutcome.WRITTEN_OFF.value}, ADMIN
    )
    batch = validate_success(response, 200)
    assert_purchase_batch(batch)
    assert batch["audit_status"] == AuditStatus.WRITTEN_OFF.value
    assert batch["recovered_cents"] == 0, "the write-off collects nothing"
    assert batch["overbilled_cents"] == BATCH_OVERBILLED_CENTS, (
        "the write-off records the forgiveness, it does not erase the finding"
    )
    assert batch["normalization_status"] == NormalizationStatus.NORMALIZED.value, (
        "the settlement touched only the audit dimension"
    )

    member = fx.read_member(ctx["member_id"])
    assert member["recovery_credit_cents"] == 0, (
        "no member is credited when the overbilling is written off"
    )


def test_write_off_suspends_the_distributor_and_closes_its_feed():
    """The write-off is the one path to Distributor SUSPENDED: the distributor's
    lifetime recovered total stays at 0, its version advances by exactly 1, and
    it can no longer open a purchase feed.

    PRD: "the batch's distributor moves `ACTIVE → SUSPENDED` with its `version`
    incremented by 1, putting the contract under review and blocking that
    distributor from opening further feeds or countersigning further letters."

    Design: Corner/state_machines/settle_recovery_written_off_suspends_the_distributor
    """
    ctx = recovery_requested_june_batch()
    before = fx.read_distributor(ctx["distributor_id"])
    assert before["status"] == DistributorStatus.ACTIVE.value
    assert before["overbilled_recovered_cents"] == 0

    response = api_client.settle_recovery(
        ctx["batch_id"], {"outcome": RecoveryOutcome.WRITTEN_OFF.value}, ADMIN
    )
    validate_success(response, 200)

    distributor = fx.read_distributor(ctx["distributor_id"])
    assert distributor["status"] == DistributorStatus.SUSPENDED.value
    assert distributor["version"] == before["version"] + 1
    assert distributor["overbilled_recovered_cents"] == 0, (
        "nothing was collected, so the lifetime recovered total stays put"
    )

    reopen = api_client.create_purchase_batch(
        F.july_batch_payload(ctx["distributor_id"]),
        make_distributor_feed_headers(ctx["distributor_id"]),
    )
    validate_error(reopen, ApiErrorId.ERR_DISTRIBUTOR_SUSPENDED, 409)


def test_a_second_settle_recovery_is_refused_because_written_off_is_terminal():
    """WRITTEN_OFF is final: replaying the settlement — even with the other
    outcome — is refused, and the batch's audit dimension does not move.

    PRD: "Settlement requires the batch's `audit_status` to be
    `RECOVERY_REQUESTED`, anything else drawing `ERR_INVALID_STATE`."

    Design: Corner/state_machines/settle_recovery_written_off_suspends_the_distributor
    """
    ctx = recovery_requested_june_batch()
    written_off = fx.settle_recovery(
        ctx["batch_id"], RecoveryOutcome.WRITTEN_OFF.value
    )
    assert written_off["audit_status"] == AuditStatus.WRITTEN_OFF.value

    replay = api_client.settle_recovery(
        ctx["batch_id"], {"outcome": RecoveryOutcome.WRITTEN_OFF.value}, ADMIN
    )
    validate_error(replay, ApiErrorId.ERR_INVALID_STATE, 409)

    batch = fx.read_batch(ctx["batch_id"])
    assert batch["audit_status"] == AuditStatus.WRITTEN_OFF.value
    assert batch["recovered_cents"] == 0
    assert batch["overbilled_cents"] == BATCH_OVERBILLED_CENTS
    assert batch["version"] == written_off["version"], (
        "a rejected settlement performs no write on the batch"
    )


# ============================================================================
# ManufacturerDeal: resume is declared only from SUSPENDED
# ============================================================================

def test_resume_and_suspend_are_both_refused_from_a_draft_deal():
    """From DRAFT the only declared verb is activate, so resume and suspend both
    409 rather than quietly behaving like it — and neither rejection bumps the
    deal's version, which is an OCC parent for rate-card and claim writes.

    PRD: "The target record is in a state from which the requested transition is
    declared, and for a create whose container must still be open the container
    is in its accepting state — otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/deal_resume_from_draft_returns_invalid_state
    """
    ctx = activatable_draft_deal()
    before = fx.read_deal(ctx["deal_id"])
    assert before["status"] == DealStatus.DRAFT.value

    resume = api_client.resume_deal(ctx["deal_id"], ADMIN)
    validate_error(resume, ApiErrorId.ERR_INVALID_STATE, 409)

    suspend = api_client.suspend_deal(ctx["deal_id"], ADMIN)
    validate_error(suspend, ApiErrorId.ERR_INVALID_STATE, 409)

    deal = fx.read_deal(ctx["deal_id"])
    assert deal["status"] == DealStatus.DRAFT.value, (
        "neither refused verb moved the deal out of DRAFT"
    )
    assert deal["version"] == before["version"], (
        "a rejected transition performs no write, so the OCC token is unchanged"
    )


def test_activate_succeeds_after_the_rejections_and_resume_still_fails():
    """The same deal the two rejected verbs left untouched activates cleanly,
    counting its one ACTIVE item and taking exactly one version step; resume is
    still not declared from ACTIVE either.

    PRD: "A `GpoAdmin` activating a `DRAFT` deal moves it `DRAFT → ACTIVE`,
    recomputes `contracted_item_count` as the number of that deal's items whose
    `status` is `ACTIVE`, and increments the deal's `version` by 1."

    Design: Corner/state_machines/deal_resume_from_draft_returns_invalid_state
    """
    ctx = activatable_draft_deal()
    validate_error(
        api_client.resume_deal(ctx["deal_id"], ADMIN), ApiErrorId.ERR_INVALID_STATE, 409
    )
    validate_error(
        api_client.suspend_deal(ctx["deal_id"], ADMIN), ApiErrorId.ERR_INVALID_STATE, 409
    )
    before = fx.read_deal(ctx["deal_id"])

    response = api_client.activate_deal(ctx["deal_id"], ADMIN)
    deal = validate_success(response, 200)
    assert deal["status"] == DealStatus.ACTIVE.value
    assert deal["contracted_item_count"] == 1
    assert deal["version"] == before["version"] + 1

    still_refused = api_client.resume_deal(ctx["deal_id"], ADMIN)
    validate_error(still_refused, ApiErrorId.ERR_INVALID_STATE, 409)
    after = fx.read_deal(ctx["deal_id"])
    assert after["status"] == DealStatus.ACTIVE.value
    assert after["version"] == deal["version"], (
        "resume on an ACTIVE deal is refused and writes nothing"
    )


# ============================================================================
# Initial states: eight creatable entities, nine state dimensions
# ============================================================================

def test_every_newly_created_row_reports_its_declared_initial_state():
    """One create per entity, each read straight off its 201: a distributor is
    born ACTIVE, a batch initialises BOTH of its dimensions at once, and every
    other row sits at the initial value its own narrative declares.

    PRD: "A new batch begins with `normalization_status` of `RECEIVED`,
    `audit_status` of `NOT_AUDITED`, a `line_count` of 0, `total_cases_ingested`,
    `matched_cases`, `unmatched_cases`, `overbilled_cents` and `recovered_cents`
    all at 0, `accrued_by_user_id` null and `payout_hold` false."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    tier = fx.create_tier()

    distributor = validate_success(
        api_client.create_distributor(F.distributor_payload(), ADMIN), 201
    )
    assert distributor["status"] == DistributorStatus.ACTIVE.value, (
        "no pending state exists for distributors"
    )
    assert distributor["active_letter_count"] == 0
    assert distributor["overbilled_recovered_cents"] == 0

    member = validate_success(
        api_client.create_member(F.member_payload(tier["id"]), ADMIN), 201
    )
    assert member["enrollment_status"] == MemberEnrollmentStatus.PENDING.value
    assert member["reconciliation_posture"] == ReconciliationPosture.CLEAR.value
    assert member["payout_hold"] is False

    letter = validate_success(
        api_client.create_authorization_letter(
            F.authorization_letter_payload(member["id"], distributor["id"]),
            make_member_operator_headers(member["id"]),
        ),
        201,
    )
    assert letter["status"] == LetterStatus.SUBMITTED.value
    assert letter["countersigned_at"] is None

    deal = validate_success(api_client.create_deal(F.deal_payload(), ADMIN), 201)
    assert deal["status"] == DealStatus.DRAFT.value
    assert deal["contracted_item_count"] == 0, "no item exists yet at this instant"
    assert deal["last_purchase_date"] is None

    item = validate_success(
        api_client.create_contracted_item(F.contracted_item_payload(deal["id"]), ADMIN),
        201,
    )
    assert item["status"] == ItemStatus.ACTIVE.value
    assert item["approved_rate_card_count"] == 0

    card = validate_success(
        api_client.create_rate_card(
            F.flat_rate_card_payload(item["id"], fx.item_version(item["id"])), ADMIN
        ),
        201,
    )
    assert card["status"] == RateCardStatus.PROPOSED.value
    assert card["pinned_item_version"] is None
    assert card["supersedes_rate_card_id"] is None

    batch = validate_success(
        api_client.create_purchase_batch(
            F.purchase_batch_payload(distributor["id"]),
            make_distributor_feed_headers(distributor["id"]),
        ),
        201,
    )
    assert batch["normalization_status"] == NormalizationStatus.RECEIVED.value
    assert batch["audit_status"] == AuditStatus.NOT_AUDITED.value, (
        "both dimensions initialise from one create"
    )
    assert batch["line_count"] == 0
    assert batch["total_cases_ingested"] == 0
    assert batch["matched_cases"] == 0
    assert batch["unmatched_cases"] == 0
    assert batch["overbilled_cents"] == 0
    assert batch["recovered_cents"] == 0
    assert batch["accrued_by_user_id"] is None
    assert batch["payout_hold"] is False

    claim = validate_success(
        api_client.create_claim(
            F.claim_payload(
                deal["id"],
                fx.deal_version(deal["id"]),
                CLAIMED_UNITS,
                CLAIMED_AMOUNT_CENTS,
            ),
            REP,
        ),
        201,
    )
    assert claim["status"] == ClaimStatus.SUBMITTED.value
    assert claim["accrued_amount_cents"] == 0
    assert claim["variance_bps"] == 0
    assert claim["reconciled_at"] is None

    reread = validate_success(api_client.get_purchase_batch(batch["id"], ANALYST), 200)
    assert reread["normalization_status"] == NormalizationStatus.RECEIVED.value
    assert reread["audit_status"] == AuditStatus.NOT_AUDITED.value


def test_the_two_occ_parents_are_the_rows_whose_version_moved_on_creation():
    """Every fresh row reports version 1 except the two OCC parents: the rate
    card create advances the contracted item once, and the claim create advances
    the deal once — which is why each token must be read immediately before use.

    PRD: "Submitting a manufacturer claim requires `expected_deal_version` as a
    non-optional body field, carrying the client's last observed `version` of the
    `ManufacturerDeal` the claim is filed against."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    tier = fx.create_tier()
    distributor = fx.create_distributor()
    member = fx.create_member(tier["id"])
    letter = fx.submit_letter(member["id"], distributor["id"])
    deal = fx.create_deal()
    item = fx.create_item(deal["id"])
    assert item["version"] == 1, "a new item's version is 1"

    card = validate_success(
        api_client.create_rate_card(
            F.flat_rate_card_payload(item["id"], item["version"]), ADMIN
        ),
        201,
    )
    assert card["version"] == 1
    assert fx.read_item(item["id"])["version"] == 2, (
        "the owning contracted item's version is incremented by exactly 1 for "
        "the rate-card call as a whole"
    )

    batch = fx.create_batch(distributor["id"])
    deal_before_claim = fx.read_deal(deal["id"])
    claim = validate_success(
        api_client.create_claim(
            F.claim_payload(
                deal["id"],
                deal_before_claim["version"],
                CLAIMED_UNITS,
                CLAIMED_AMOUNT_CENTS,
            ),
            REP,
        ),
        201,
    )
    assert claim["version"] == 1
    assert fx.read_deal(deal["id"])["version"] == deal_before_claim["version"] + 1, (
        "the claim create advances the owning deal's version by exactly 1"
    )

    for row in (tier, distributor, member, letter, batch):
        assert row["version"] == 1, "a newly created row starts at version 1"


# ============================================================================
# Member TERMINATED: the only terminal enrollment state
# ============================================================================

def test_a_terminated_member_can_be_neither_reactivated_nor_terminated_again():
    """TERMINATED locks the activate edge and is not idempotent for terminate,
    while payout_hold stays true and the cascaded letter revocation has already
    zeroed both sides' counters.

    PRD: "Attempting to activate a member that is already `ACTIVE`, or one that
    has been `TERMINATED`, is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminated_member_cannot_be_reactivated_or_reused
    """
    ctx = active_letter_world()
    fx.activate_member(ctx["member_id"])
    fx.create_batch(ctx["distributor_id"])
    terminated = fx.terminate_member(ctx["member_id"])
    assert terminated["enrollment_status"] == MemberEnrollmentStatus.TERMINATED.value

    reactivate = api_client.activate_member(ctx["member_id"], ADMIN)
    validate_error(reactivate, ApiErrorId.ERR_INVALID_STATE, 409)

    reterminate = api_client.terminate_member(ctx["member_id"], ADMIN)
    validate_error(reterminate, ApiErrorId.ERR_INVALID_STATE, 409)

    member = fx.read_member(ctx["member_id"])
    assert member["enrollment_status"] == MemberEnrollmentStatus.TERMINATED.value
    assert member["payout_hold"] is True, "the hold set by termination is forever"
    assert member["active_letter_count"] == 0
    assert member["version"] == terminated["version"], (
        "both rejected transitions performed no write"
    )

    letter = validate_success(
        api_client.get_authorization_letter(ctx["letter_id"], ADMIN), 200
    )
    assert letter["status"] == LetterStatus.REVOKED.value, (
        "hop 1 of terminate revoked the member's ACTIVE letter"
    )
    assert fx.read_distributor(ctx["distributor_id"])["active_letter_count"] == 0


def test_a_terminated_members_purchase_line_is_refused_at_the_enrollment_gate():
    """The same termination that closed the activate edge also closes every
    member-scoped write: the enrollment gate at priority 12 refuses the line
    before the letter check at priority 15 is ever reached.

    PRD: "The buying member must have `enrollment_status` of `ACTIVE`, and a
    `PENDING`, `SUSPENDED` or `TERMINATED` member is refused with
    `ERR_MEMBER_NOT_ENROLLED`."

    Design: Corner/state_machines/terminated_member_cannot_be_reactivated_or_reused
    """
    ctx = active_letter_world()
    fx.activate_member(ctx["member_id"])
    batch = fx.create_batch(ctx["distributor_id"])
    fx.terminate_member(ctx["member_id"])

    response = api_client.create_purchase_line(
        F.purchase_line_payload(batch["id"], ctx["member_id"]),
        make_distributor_feed_headers(ctx["distributor_id"]),
    )
    validate_error(response, ApiErrorId.ERR_MEMBER_NOT_ENROLLED, 409)

    reread = fx.read_batch(batch["id"])
    assert reread["line_count"] == 0, "the refused ingestion persisted no line"
    assert reread["total_cases_ingested"] == 0
    assert reread["normalization_status"] == NormalizationStatus.RECEIVED.value
    assert reread["version"] == batch["version"], (
        "a rejected ingestion writes nothing on the container either"
    )


# ============================================================================
# AuthorizationLetter idempotency: a replayed ACCEPT must not double-count
# ============================================================================

def test_a_replayed_accept_is_refused_and_the_counters_do_not_double_count():
    """Replaying the countersignature is an error, not a no-op: the letter is
    already ACTIVE, so the second ACCEPT is refused and both active_letter_count
    figures stay at 1 for the single letter that exists.

    PRD: "Either branch requires the letter to still be `SUBMITTED`, requires the
    acting `DistributorFeed` account's `X-User-ID` to equal the letter's
    `distributor_id`"

    Design: Corner/state_machines/second_countersign_on_an_active_letter_is_rejected
    """
    ctx = active_letter_world()
    assert ctx["letter"]["status"] == LetterStatus.ACTIVE.value
    version_after_accept = ctx["letter"]["version"]

    replay = api_client.countersign_letter(
        ctx["letter_id"],
        {"decision": CountersignDecision.ACCEPT.value},
        make_distributor_feed_headers(ctx["distributor_id"]),
    )
    validate_error(replay, ApiErrorId.ERR_INVALID_STATE, 409)

    assert fx.read_member(ctx["member_id"])["active_letter_count"] == 1, (
        "the side effect did not re-run: one letter, one count"
    )
    assert fx.read_distributor(ctx["distributor_id"])["active_letter_count"] == 1
    letter = validate_success(
        api_client.get_authorization_letter(ctx["letter_id"], ADMIN), 200
    )
    assert letter["status"] == LetterStatus.ACTIVE.value
    assert letter["version"] == version_after_accept, (
        "a rejected countersignature performs no write"
    )
    assert len(active_letters()) == 1


def test_revoke_zeroes_the_counters_once_and_a_second_revoke_is_refused():
    """The first revoke decrements both counters to 0; REVOKED is terminal, so
    the replayed revoke is refused and the counters stay at 0 rather than going
    negative, with the original countersigned_at still on the record.

    PRD: "A `MemberOperator` or a `GpoAdmin` may withdraw an authorization,
    moving it `ACTIVE → REVOKED` and decrementing both `active_letter_count`
    figures by 1."

    Design: Corner/state_machines/second_countersign_on_an_active_letter_is_rejected
    """
    ctx = active_letter_world()
    validate_error(
        api_client.countersign_letter(
            ctx["letter_id"],
            {"decision": CountersignDecision.ACCEPT.value},
            make_distributor_feed_headers(ctx["distributor_id"]),
        ),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )

    first = api_client.revoke_letter(
        ctx["letter_id"], make_member_operator_headers(ctx["member_id"])
    )
    revoked = validate_success(first, 200)
    assert revoked["status"] == LetterStatus.REVOKED.value
    assert fx.read_member(ctx["member_id"])["active_letter_count"] == 0
    assert fx.read_distributor(ctx["distributor_id"])["active_letter_count"] == 0

    second = api_client.revoke_letter(
        ctx["letter_id"], make_member_operator_headers(ctx["member_id"])
    )
    validate_error(second, ApiErrorId.ERR_INVALID_STATE, 409)

    assert fx.read_member(ctx["member_id"])["active_letter_count"] == 0, (
        "the counters stay at 0 rather than going negative"
    )
    assert fx.read_distributor(ctx["distributor_id"])["active_letter_count"] == 0
    letter = validate_success(
        api_client.get_authorization_letter(ctx["letter_id"], ADMIN), 200
    )
    assert letter["status"] == LetterStatus.REVOKED.value
    assert letter["version"] == revoked["version"], (
        "the refused second revoke performed no write"
    )
    assert_instants_equal(letter["countersigned_at"], C.CLOCK_EPOCH)
