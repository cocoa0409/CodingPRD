"""Queue B - corner section ``validations``.

Twenty-one instances, one per band of the PRD 2.8 ladder that this section
reaches: the dispute window at both edges, the two non-empty prerequisite sets,
the two claim ceilings, decision consistency, the grounds prerequisite, the
three bunching-window rules, agreement-month exclusivity, the fiscal posture,
event chronology, the two reference-pairing rules, the supersede target, the
regulator's money cap, the two tariff referential-integrity arms, and the two
notice-availability rules at the very bottom of the ladder.

Two rendering conventions apply to the PRD quotations in the docstrings below:
the PRD's em dashes are written as ASCII hyphens and its transition arrows as
``->``.  Nothing else is altered, so every quoted sentence is greppable in
``workspace/PRD.md`` once those two substitutions are made.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ALLOWANCE_PCT_MISMATCH,
    ERR_BUNCHING_CLAIM_NOT_GRANTED,
    ERR_CHARGE_INVOICE_MISMATCH,
    ERR_CLAIM_EXCEEDS_CHARGE,
    ERR_CLAIM_NO_DELIVERIES,
    ERR_CLUSTER_WINDOW_OVERLAP,
    ERR_CUSTOMER_CREDIT_HOLD,
    ERR_DISPUTE_NO_EVIDENCE,
    ERR_DISPUTE_SCOPE_MISMATCH,
    ERR_DISPUTE_WINDOW_CLOSED,
    ERR_DUPLICATE_AGREEMENT_MONTH,
    ERR_INVALID_CLUSTER_WINDOW,
    ERR_INVOICE_NO_CHARGES,
    ERR_NON_CHRONOLOGICAL_EVENT,
    ERR_NOTIFICATION_NOT_SENT,
    ERR_NO_PENDING_NOTIFICATION,
    ERR_ORDERED_CREDIT_EXCEEDS_CLAIM,
    ERR_SUPERSEDE_TARGET_INVALID,
    ERR_TARIFF_SCOPE_MISMATCH,
    ERR_TARIFF_WITHDRAWN,
)
from test_helpers.assertions import (
    add_business_dates,
    assert_end_of_day,
    assert_error_meta_is_minimal,
    assert_instant_eq,
    assert_server_minted_id,
    assert_subset_equal,
    calendar_dates_between,
    end_of,
    error_id_of,
    ids_of,
)
from test_helpers.constants import (
    ACCESS_MODE_OPEN,
    AGREEMENT_MONTH,
    AGREEMENT_OPEN,
    BILLING_DISPUTED,
    BILLING_INVOICED,
    BILLING_POSTURE_CREDIT_HOLD,
    BILLING_POSTURE_CURRENT,
    BILLING_UNBILLED,
    CAR_OWNERSHIP_SCOPE_ANY,
    CAR_OWNERSHIP_SCOPE_RAILROAD_OWNED,
    CHANNEL_EDI,
    CHARGE_DISPUTED,
    CHARGE_FINAL,
    CHARGE_PROVISIONAL,
    CLAIM_DENIED,
    CLAIM_PARTIALLY_GRANTED,
    CLAIM_SUBMITTED,
    CLOCK_AFTER_RELEASE,
    CLOCK_BASIS_ACTUAL,
    CLOCK_BASIS_CONSTRUCTIVE,
    CLOCK_BASIS_NONE,
    COLD_START_CLOCK,
    COMPLAINT_DECIDED_FOR_CUSTOMER,
    COMPLAINT_DECIDED_FOR_RAILROAD,
    COMPLAINT_RAILROAD_ANSWERED,
    COMPLAINT_TYPE_RULE_REASONABLENESS,
    CYCLE_A_ACTUAL_AT,
    CYCLE_A_ACTUAL_EXPIRY,
    CYCLE_A_CHARGEABLE_DAYS,
    CYCLE_A_CONSTRUCTIVE_AT,
    CYCLE_A_GROSS_CENTS,
    CYCLE_A_NOTICE_SENT_AT,
    CYCLE_A_RELEASE_AT,
    DECISION_ALLOWED,
    DECISION_DENIED,
    DECISION_PENDING,
    DEFAULT_ADJUDICATION_DAYS_BASE,
    DEFAULT_FREE_TIME_HOURS_RAILROAD,
    DEFAULT_NORMAL_DAILY_PLACEMENT_CAPACITY,
    DEFAULT_TIER1_RATE_RAILROAD,
    DELIVERY_DELIVERED,
    DELIVERY_FAILED,
    DISPUTE_DRAFT,
    DISPUTE_ESCALATED,
    DISPUTE_POSTURE_UNDER_REVIEW,
    DISPUTE_SUBMITTED,
    DISPUTE_UNDER_REVIEW,
    EVIDENCE_SWITCH_LIST,
    EVIDENCE_WEIGHT_POINTS,
    GROUNDS_BUNCHING,
    GROUNDS_CLOCK_BASIS_ERROR,
    GROUNDS_RAILROAD_CAUSED_DELAY,
    GROUNDS_RATE_UNREASONABLE,
    INVOICE_DRAFT,
    INVOICE_ISSUED,
    INVOICE_PARTIALLY_DISPUTED,
    MAX_CLUSTER_WINDOW_DATES,
    METHOD_ORDERED_VS_CAPACITY,
    METHOD_ROLLING_AVERAGE_BASELINE,
    MOVEMENT_ACTUALLY_PLACED,
    MOVEMENT_CONSTRUCTIVELY_PLACED,
    MOVEMENT_RELEASED,
    NOTIFICATION_METHOD_FAX,
    OWNERSHIP_PRIVATE,
    SCOPE_SINGLE_CHARGE,
    SCOPE_WHOLE_INVOICE,
    TARIFF_STATUS_CHALLENGED,
    TARIFF_STATUS_PUBLISHED,
    TARIFF_STATUS_WITHDRAWN,
    TWO_LINE_GROSSES,
    TWO_LINE_GROSS_TOTAL,
)
from test_helpers.test_users import (
    ADMIN,
    AGENT,
    OFFICER,
    make_adjudicator_headers,
    make_customer_headers,
)

# --- the mid-August issue station and the window it opens ------------------
ISSUE_CLOCK_MID_AUGUST = "2026-08-15T00:00:00.000Z"
DEADLINE_FROM_MID_AUGUST = "2026-09-14T23:59:59.999Z"
CLOCK_ONE_DAY_PAST_THE_DEADLINE = "2026-09-15T00:00:00.000Z"
CLOCK_AT_THE_FINAL_MILLISECOND = DEADLINE_FROM_MID_AUGUST
# CEIL(20 x 1.00) - FLOOR(3 / 2) = 19 business dates from 2026-09-14.
ROUND_ONE_ALLOWANCE_DATES = 19
DUE_AT_FROM_THE_FINAL_MILLISECOND = "2026-10-09T23:59:59.999Z"

# --- the two claim ceilings -------------------------------------------------
ONE_CENT_OVER_LINE_A = CYCLE_A_GROSS_CENTS + 1
ADJUDICATOR_CLAIM_CAP = "adj-v05-a"
ADJUDICATOR_ALLOWANCE = "adj-v06-a"
HALF_A_PERCENT = 0.5

# --- the bunching instances -------------------------------------------------
ADJUDICATOR_BUNCHING = "adj-v07-a"
CAPACITY_THREE = 3
CLUSTER_WINDOW_START = "2026-08-03T00:00:00.000Z"
CLUSTER_WINDOW_END = "2026-08-05T23:59:59.999Z"
EMPTY_WINDOW_START = "2026-08-20T00:00:00.000Z"
EMPTY_WINDOW_END = "2026-08-22T23:59:59.999Z"
INVERTED_WINDOW_START = "2026-08-05T00:00:00.000Z"
INVERTED_WINDOW_END = "2026-08-03T23:59:59.999Z"
FIFTEEN_DATE_WINDOW_START = "2026-08-01T00:00:00.000Z"
FIFTEEN_DATE_WINDOW_END = "2026-08-15T23:59:59.999Z"
FOURTEEN_DATE_WINDOW_END = "2026-08-14T23:59:59.999Z"
FIFTEEN_DATES = 15
OVERLAPPING_WINDOW_START = "2026-08-05T00:00:00.000Z"
OVERLAPPING_WINDOW_END = "2026-08-07T23:59:59.999Z"
DISJOINT_WINDOW_START = "2026-08-06T00:00:00.000Z"
ONE_EXEMPT_DAY = 1
TWO_BILLABLE_DAYS = 2
GROSS_AFTER_ONE_EXEMPTION = 25100  # the ladder is re-walked from tier one

# --- the agreement and the fiscal posture ----------------------------------
FIRST_CAP_RATIO = 0.25
SECOND_CAP_RATIO = 0.4
NEXT_AGREEMENT_MONTH = "2026-09"

# --- event chronology -------------------------------------------------------
LATE_CONSTRUCTIVE_AT = "2026-08-05T08:00:00.000Z"
LATE_NOTICE_AT = "2026-08-05T09:00:00.000Z"
BACKDATED_ACTUAL_AT = "2026-08-04T10:00:00.000Z"

# --- the July invoice used by the charge-to-invoice link -------------------
JULY_CLOCK = "2026-07-27T00:00:00.000Z"
JULY_CONSTRUCTIVE_AT = "2026-07-28T08:00:00.000Z"
JULY_NOTICE_AT = "2026-07-28T09:00:00.000Z"
JULY_ACTUAL_AT = "2026-07-29T10:00:00.000Z"
JULY_RELEASE_AT = "2026-07-31T09:00:00.000Z"
JULY_PERIOD_START = "2026-07-01T00:00:00.000Z"
JULY_PERIOD_END = "2026-07-31T23:59:59.999Z"
JULY_DRAFT_CLOCK = "2026-07-31T12:00:00.000Z"

# --- the escalation chain ---------------------------------------------------
ADJUDICATOR_ESCALATION_A = "adj-v17-a"
ADJUDICATOR_ESCALATION_B = "adj-v17-b"
ESCALATION_CLAIM_CENTS = 20000
ONE_CENT_OVER_THE_CLAIM = ESCALATION_CLAIM_CENTS + 1

# --- the FAX customer with nothing to acknowledge --------------------------
FAX_ACK_AT = "2026-08-03T20:00:00.000Z"


def _issued_single_line_invoice(api):
    """Cycle A released and issued at 2026-08-15, so the window closes 2026-09-14."""
    world = fx.reference_world(api)
    cycle = fx.released_cycle_a(api, world)
    invoice = fx.issued_invoice(api, world, issue_clock=ISSUE_CLOCK_MID_AUGUST)
    assert_subset_equal(
        invoice,
        {"status": INVOICE_ISSUED, "total_gross_cents": CYCLE_A_GROSS_CENTS},
    )
    assert_instant_eq(
        invoice["dispute_deadline_at"], DEADLINE_FROM_MID_AUGUST, "dispute_deadline_at"
    )
    return world, cycle, invoice


# ===========================================================================
# instance: dispute_submit_after_deadline_on_issued_invoice
# ===========================================================================
def test_a_submit_one_day_past_the_deadline_is_refused(api):
    """The state band is satisfied twice over, so only the temporal band can fail.

    PRD 2.8 band 18: "Submitting a dispute requires the logical clock to be at
    or before the invoice's dispute deadline, or `ERR_DISPUTE_WINDOW_CLOSED`."

    Design: Corner/validations/dispute_submit_after_deadline_on_issued_invoice
    """
    world, cycle, invoice = _issued_single_line_invoice(api)
    dispute = fx.evidenced_dispute(
        api, invoice, world["customer_id"], CYCLE_A_GROSS_CENTS
    )
    assert dispute["status"] == DISPUTE_DRAFT

    fx.set_clock(api, CLOCK_ONE_DAY_PAST_THE_DEADLINE)
    refused = api.submit_dispute(
        dispute["id"], make_customer_headers(world["customer_id"])
    )
    validate_error(refused, ERR_DISPUTE_WINDOW_CLOSED)
    assert refused.status_code == 422
    assert_error_meta_is_minimal(refused)

    # PRD 3.8: "Every exhibit re-derives the dispute's `evidence_weight` as the
    # sum of the `weight_points` of its exhibits", so the one SWITCH_LIST filed at
    # DRAFT already reads 3; the refused submit simply leaves it there.
    frozen = fx.get_dispute(api, dispute["id"])
    assert_subset_equal(
        frozen,
        {
            "status": DISPUTE_DRAFT,
            "submitted_at": None,
            "adjudication_due_at": None,
            "evidence_weight": dispute["evidence_weight"],
            "target_charge_count": 0,
            "version": dispute["version"],
        },
    )
    assert dispute["evidence_weight"] == EVIDENCE_WEIGHT_POINTS[EVIDENCE_SWITCH_LIST]
    assert fx.charge_of_cycle(api, cycle["id"])["status"] == CHARGE_FINAL
    assert fx.get_cycle(api, cycle["id"])["billing_status"] == BILLING_INVOICED

    # PRD 3.8: filing "increments the invoice's `version` by 1 and re-derives its
    # `dispute_count`, but **no charge changes status yet**", so the count is 1
    # from the create and the refused submit leaves the invoice exactly there.
    unmoved = fx.get_invoice(api, invoice["id"])
    assert_subset_equal(
        unmoved,
        {
            "status": INVOICE_ISSUED,
            "dispute_count": 1,
            "total_credit_cents": 0,
            "total_net_cents": CYCLE_A_GROSS_CENTS,
        },
    )
    assert unmoved["version"] == invoice["version"] + 1


# ===========================================================================
# instance: dispute_submit_at_the_final_millisecond_of_the_window
# ===========================================================================
def test_a_submit_at_the_final_millisecond_is_accepted(api):
    """The comparison is inclusive, and the accepted submit starts its own clock.

    PRD 3.8: "The deadline itself is the last millisecond of the allowance-th
    **business date** - Monday through Friday, unconditionally, and never the
    tariff's `weekend_excluded` calendar - counted forward from the date of
    `submitted_at`, at `23:59:59.999Z`."

    Design: Corner/validations/dispute_submit_at_the_final_millisecond_of_the_window
    """
    world, cycle, invoice = _issued_single_line_invoice(api)
    dispute = fx.evidenced_dispute(
        api,
        invoice,
        world["customer_id"],
        CYCLE_A_GROSS_CENTS,
        evidence_types=[EVIDENCE_SWITCH_LIST],
    )

    fx.set_clock(api, CLOCK_AT_THE_FINAL_MILLISECOND)
    submitted = get_success_data(
        api.submit_dispute(dispute["id"], make_customer_headers(world["customer_id"]))
    )
    assert_subset_equal(
        submitted,
        {
            "status": DISPUTE_SUBMITTED,
            "grounds": GROUNDS_RAILROAD_CAUSED_DELAY,
            "evidence_weight": EVIDENCE_WEIGHT_POINTS[EVIDENCE_SWITCH_LIST],
            "target_charge_count": 1,
            "round_number": 1,
        },
    )
    assert_instant_eq(
        submitted["submitted_at"], CLOCK_AT_THE_FINAL_MILLISECOND, "submitted_at"
    )
    assert_instant_eq(
        submitted["submitted_at"], invoice["dispute_deadline_at"], "submitted_at"
    )

    # 20 x 1.00 rounded up is 20; the weight of 3 halves down to 1 day of credit.
    assert DEFAULT_ADJUDICATION_DAYS_BASE - 1 == ROUND_ONE_ALLOWANCE_DATES
    assert_end_of_day(submitted["adjudication_due_at"], "adjudication_due_at")
    assert_instant_eq(
        submitted["adjudication_due_at"],
        end_of(
            add_business_dates(
                CLOCK_AT_THE_FINAL_MILLISECOND, ROUND_ONE_ALLOWANCE_DATES
            )
        ),
        "adjudication_due_at",
    )
    assert_instant_eq(
        submitted["adjudication_due_at"],
        DUE_AT_FROM_THE_FINAL_MILLISECOND,
        "adjudication_due_at",
    )

    assert fx.charge_of_cycle(api, cycle["id"])["status"] == CHARGE_DISPUTED
    assert fx.get_cycle(api, cycle["id"])["billing_status"] == BILLING_DISPUTED
    assert_subset_equal(
        fx.get_invoice(api, invoice["id"]),
        {"status": INVOICE_PARTIALLY_DISPUTED, "dispute_count": 1},
    )
    assert (
        fx.get_customer(api, world["customer_id"])["dispute_posture"]
        == DISPUTE_POSTURE_UNDER_REVIEW
    )


# ===========================================================================
# instance: issue_an_invoice_with_no_attached_charges
# ===========================================================================
def test_an_empty_period_is_legal_to_open_and_illegal_to_issue(api):
    """Emptiness is not a create-time error; it is a band-24 error at issue.

    PRD 2.8 band 24: "Issuing an invoice requires at least one live attached
    charge, or `ERR_INVOICE_NO_CHARGES`; submitting or resubmitting a dispute
    requires a non-empty evidence set, or `ERR_DISPUTE_NO_EVIDENCE`."

    Design: Corner/validations/issue_an_invoice_with_no_attached_charges
    """
    world = fx.reference_world(api)
    draft = fx.draft_invoice(api, world, clock=CLOCK_AFTER_RELEASE)
    assert_server_minted_id(draft["id"])
    assert_subset_equal(
        draft,
        {
            "status": INVOICE_DRAFT,
            "attached_charge_count": 0,
            "total_gross_cents": 0,
            "total_credit_cents": 0,
            "total_net_cents": 0,
            "agreement_credit_cents": 0,
            "dispute_count": 0,
            "dispute_deadline_at": None,
        },
    )

    refused = api.issue_invoice(draft["id"], ADMIN)
    validate_error(refused, ERR_INVOICE_NO_CHARGES)
    assert refused.status_code == 422
    assert_error_meta_is_minimal(refused)

    # Nothing moved: the invoice is still openable-but-unissuable.
    after = fx.get_invoice(api, draft["id"])
    assert after == draft
    assert_subset_equal(
        after,
        {"status": INVOICE_DRAFT, "dispute_deadline_at": None, "version": draft["version"]},
    )


# ===========================================================================
# instance: submit_a_dispute_with_no_evidence_at_all
# ===========================================================================
def test_the_evidence_set_is_checked_before_the_window_or_the_invoice(api):
    """A perfectly disputable invoice inside its window still fails on an empty file.

    PRD 3.8: "The dispute must carry at least one exhibit, or
    `ERR_DISPUTE_NO_EVIDENCE`."

    Design: Corner/validations/submit_a_dispute_with_no_evidence_at_all
    """
    world, cycle, invoice = _issued_single_line_invoice(api)
    dispute = fx.draft_dispute(
        api, invoice, world["customer_id"], CYCLE_A_GROSS_CENTS
    )
    assert dispute["status"] == DISPUTE_DRAFT
    assert dispute["evidence_weight"] == 0
    filed = get_success_data(
        api.list_evidence(dispute["id"], make_customer_headers(world["customer_id"]))
    )
    assert filed == []

    refused = api.submit_dispute(
        dispute["id"], make_customer_headers(world["customer_id"])
    )
    validate_error(refused, ERR_DISPUTE_NO_EVIDENCE)
    assert refused.status_code == 422
    assert_error_meta_is_minimal(refused)

    frozen = fx.get_dispute(api, dispute["id"])
    assert_subset_equal(
        frozen,
        {
            "status": DISPUTE_DRAFT,
            "submitted_at": None,
            "adjudication_due_at": None,
            "version": dispute["version"],
        },
    )
    # The money is untouched: the invoice is still ISSUED and the line still FINAL.
    assert fx.charge_of_cycle(api, cycle["id"])["status"] == CHARGE_FINAL
    assert fx.get_invoice(api, invoice["id"])["status"] == INVOICE_ISSUED

    # One exhibit is all it takes for the same request to be accepted.
    fx.add_evidence(api, dispute["id"], world["customer_id"])
    fx.set_clock(api, ISSUE_CLOCK_MID_AUGUST)
    accepted = get_success_data(
        api.submit_dispute(dispute["id"], make_customer_headers(world["customer_id"]))
    )
    assert accepted["status"] == DISPUTE_SUBMITTED
    assert accepted["evidence_weight"] == EVIDENCE_WEIGHT_POINTS[EVIDENCE_SWITCH_LIST]


# ===========================================================================
# instance: single_charge_claim_one_cent_above_the_charge_gross
# ===========================================================================
def test_the_claim_ceiling_is_the_resolved_target_set_and_not_the_invoice(api):
    """47551 fails against the 47550 line even though the invoice grosses 60100.

    PRD 2.8 band 25: "`claimed_credit_cents` must not exceed the gross of the
    dispute's resolved target set, or `ERR_CLAIM_EXCEEDS_CHARGE`; and
    `ordered_credit_cents` on a regulatory decision must not exceed the escalated
    dispute's `claimed_credit_cents`, or `ERR_ORDERED_CREDIT_EXCEEDS_CLAIM`."

    Design: Corner/validations/single_charge_claim_one_cent_above_the_charge_gross
    """
    world = fx.reference_world(api)
    cycle_a, cycle_b, invoice = fx.two_line_invoice(
        api, world, issue_clock=ISSUE_CLOCK_MID_AUGUST
    )
    charge_a = fx.charge_of_cycle(api, cycle_a["id"])
    charge_b = fx.charge_of_cycle(api, cycle_b["id"])
    assert (charge_a["gross_amount_cents"], charge_b["gross_amount_cents"]) == (
        TWO_LINE_GROSSES
    )
    assert invoice["total_gross_cents"] == TWO_LINE_GROSS_TOTAL

    def attempt(claimed, **extra):
        fresh = fx.get_invoice(api, invoice["id"])
        payload = f.dispute_payload(
            fresh["id"], fresh["version"], claimed, **extra
        )
        return api.create_dispute(payload, make_customer_headers(world["customer_id"]))

    refused = attempt(
        ONE_CENT_OVER_LINE_A,
        scope=SCOPE_SINGLE_CHARGE,
        demurrage_charge_id=charge_a["id"],
    )
    validate_error(refused, ERR_CLAIM_EXCEEDS_CHARGE)
    assert refused.status_code == 422
    assert_error_meta_is_minimal(refused)

    # The refused create wrote nothing at all, not even the invoice's counter.
    untouched = fx.get_invoice(api, invoice["id"])
    assert untouched == invoice
    assert untouched["dispute_count"] == 0

    # One cent lower - exactly the line's gross - is accepted.
    accepted = get_success_data(
        attempt(
            CYCLE_A_GROSS_CENTS,
            scope=SCOPE_SINGLE_CHARGE,
            demurrage_charge_id=charge_a["id"],
        ),
        201,
    )
    assert_subset_equal(
        accepted,
        {
            "status": DISPUTE_DRAFT,
            "scope": SCOPE_SINGLE_CHARGE,
            "demurrage_charge_id": charge_a["id"],
            "claimed_credit_cents": CYCLE_A_GROSS_CENTS,
            "target_charge_count": 0,
        },
    )

    # And the whole-invoice gross is only claimable under the wider scope.
    whole = get_success_data(attempt(TWO_LINE_GROSS_TOTAL, scope=SCOPE_WHOLE_INVOICE), 201)
    assert whole["claimed_credit_cents"] == TWO_LINE_GROSS_TOTAL
    assert fx.get_invoice(api, invoice["id"])["dispute_count"] == 2


# ===========================================================================
# instance: allowed_decision_carrying_a_fractional_allowance_pct
# ===========================================================================
def test_a_fractional_pct_is_only_legal_beside_partially_allowed(api):
    """0.5 is inside its declared range, so only the consistency rule can catch it.

    PRD 3.8: "The `allowance_pct` must agree with the `decision`: `ALLOWED`
    demands exactly 1, `DENIED` demands exactly 0, and `PARTIALLY_ALLOWED`
    demands a value strictly between 0 and 1; a mismatch is refused with
    `ERR_ALLOWANCE_PCT_MISMATCH`."

    Design: Corner/validations/allowed_decision_carrying_a_fractional_allowance_pct
    """
    world, cycle, invoice = _issued_single_line_invoice(api)
    dispute = fx.under_review_dispute(
        api,
        invoice,
        world["customer_id"],
        CYCLE_A_GROSS_CENTS,
        ADJUDICATOR_ALLOWANCE,
        submit_clock=ISSUE_CLOCK_MID_AUGUST,
        scope=SCOPE_WHOLE_INVOICE,
    )
    assert dispute["status"] == DISPUTE_UNDER_REVIEW

    headers = make_adjudicator_headers(ADJUDICATOR_ALLOWANCE)
    refused = api.decide_dispute(
        dispute["id"], f.decide_payload(DECISION_ALLOWED, HALF_A_PERCENT), headers
    )
    validate_error(refused, ERR_ALLOWANCE_PCT_MISMATCH)
    assert refused.status_code == 422
    assert_error_meta_is_minimal(refused)

    frozen = fx.get_dispute(api, dispute["id"])
    assert_subset_equal(
        frozen,
        {
            "status": DISPUTE_UNDER_REVIEW,
            "decision": DECISION_PENDING,
            "allowance_pct": None,
            "allowed_credit_cents": 0,
            "version": dispute["version"],
        },
    )
    assert fx.charge_of_cycle(api, cycle["id"])["status"] == CHARGE_DISPUTED
    assert fx.get_invoice(api, invoice["id"])["status"] == INVOICE_PARTIALLY_DISPUTED

    # The other exact-value arm fails identically on the same fraction.
    denied_at_a_half = api.decide_dispute(
        dispute["id"], f.decide_payload(DECISION_DENIED, HALF_A_PERCENT), headers
    )
    validate_error(denied_at_a_half, ERR_ALLOWANCE_PCT_MISMATCH)
    assert fx.get_dispute(api, dispute["id"])["version"] == dispute["version"]

    # The value the decision demands is accepted.
    decided = get_success_data(
        api.decide_dispute(dispute["id"], f.decide_payload(DECISION_ALLOWED, 1), headers)
    )
    assert_subset_equal(
        decided,
        {
            "decision": DECISION_ALLOWED,
            "allowance_pct": 1,
            "allowed_credit_cents": CYCLE_A_GROSS_CENTS,
        },
    )


# ===========================================================================
# instance: bunching_dispute_submitted_on_a_denied_claim
# ===========================================================================
def test_the_bunching_prerequisite_bites_at_submit_and_not_at_filing(api):
    """One arrival against a capacity of three is no cluster, and the denial waits.

    PRD 3.8: "when the grounds are `BUNCHING`, the referenced claim's status must
    be `GRANTED` or `PARTIALLY_GRANTED`, or `ERR_BUNCHING_CLAIM_NOT_GRANTED` - a
    condition tested at submission and deliberately not at filing, so a consignee
    may file a dispute while its bunching claim is still under analysis and submit
    once the claim lands."

    Design: Corner/validations/bunching_dispute_submitted_on_a_denied_claim
    """
    world = fx.reference_world(
        api, customer_overrides={"normal_daily_placement_capacity": CAPACITY_THREE}
    )
    assert world["customer"]["normal_daily_placement_capacity"] == CAPACITY_THREE
    assert CAPACITY_THREE != DEFAULT_NORMAL_DAILY_PLACEMENT_CAPACITY

    cycle = fx.released_cycle_a(api, world)
    invoice = fx.issued_invoice(api, world, issue_clock=ISSUE_CLOCK_MID_AUGUST)

    claim = fx.file_bunching_claim(
        api,
        world["customer_id"],
        CLUSTER_WINDOW_START,
        CLUSTER_WINDOW_END,
        method=METHOD_ORDERED_VS_CAPACITY,
    )
    analysed = fx.analyze_claim(api, claim["id"], ADJUDICATOR_BUNCHING)
    assert_subset_equal(
        analysed,
        {
            "status": CLAIM_DENIED,
            "baseline_per_day": CAPACITY_THREE,
            "delivered_car_count": 1,
            "cluster_chargeable_days": CYCLE_A_CHARGEABLE_DAYS,
            "exempt_days_granted": 0,
            "exempted_cycle_ids": [],
        },
    )

    # PRD 3.6: "When `exempt_days_granted` is zero the claim is `DENIED`, and no
    # charge line is touched at all".
    charge = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        charge,
        {
            "status": CHARGE_FINAL,
            "bunching_exempt_days": 0,
            "billable_days": CYCLE_A_CHARGEABLE_DAYS,
            "gross_amount_cents": CYCLE_A_GROSS_CENTS,
        },
    )

    dispute = fx.evidenced_dispute(
        api,
        invoice,
        world["customer_id"],
        CYCLE_A_GROSS_CENTS,
        grounds=GROUNDS_BUNCHING,
        bunching_claim_id=claim["id"],
    )
    # Filing against an already-denied claim is accepted, which is the whole point.
    assert_subset_equal(
        dispute,
        {
            "status": DISPUTE_DRAFT,
            "grounds": GROUNDS_BUNCHING,
            "bunching_claim_id": claim["id"],
        },
    )

    refused = api.submit_dispute(
        dispute["id"], make_customer_headers(world["customer_id"])
    )
    validate_error(refused, ERR_BUNCHING_CLAIM_NOT_GRANTED)
    assert refused.status_code == 422
    assert_error_meta_is_minimal(refused)
    assert fx.get_dispute(api, dispute["id"])["status"] == DISPUTE_DRAFT
    assert fx.charge_of_cycle(api, cycle["id"]) == charge


# ===========================================================================
# instance: analyze_a_cluster_window_that_caught_no_deliveries
# ===========================================================================
def test_an_empty_cluster_window_is_refused_rather_than_denied(api):
    """Membership is by constructive placement, so a late window catches nothing.

    PRD 3.6: "`delivered_car_count` is the size of that set, and if it is zero the
    request is refused with `ERR_CLAIM_NO_DELIVERIES`."

    Design: Corner/validations/analyze_a_cluster_window_that_caught_no_deliveries
    """
    world = fx.reference_world(api)
    cycle = fx.released_cycle_a(api, world)
    assert_instant_eq(
        cycle["constructive_placement_at"], CYCLE_A_CONSTRUCTIVE_AT, "constructive_placement_at"
    )
    assert_instant_eq(cycle["released_at"], CYCLE_A_RELEASE_AT, "released_at")

    claim = fx.file_bunching_claim(
        api, world["customer_id"], EMPTY_WINDOW_START, EMPTY_WINDOW_END
    )
    assert_subset_equal(
        claim,
        {
            "status": CLAIM_SUBMITTED,
            "baseline_per_day": 0,
            "delivered_car_count": 0,
            "cluster_chargeable_days": 0,
            "exempt_days_granted": 0,
            "exempted_cycle_ids": [],
        },
    )

    refused = api.analyze_bunching_claim(
        claim["id"], make_adjudicator_headers(ADJUDICATOR_BUNCHING)
    )
    validate_error(refused, ERR_CLAIM_NO_DELIVERIES)
    assert refused.status_code == 422
    assert_error_meta_is_minimal(refused)

    # An empty window is not a denial: the claim keeps its SUBMITTED state.
    after = fx.get_claim(api, world["customer_id"], claim["id"])
    assert after == claim
    assert after["status"] == CLAIM_SUBMITTED
    assert after["status"] != CLAIM_DENIED
    assert fx.charge_of_cycle(api, cycle["id"])["gross_amount_cents"] == CYCLE_A_GROSS_CENTS


# ===========================================================================
# instance: inverted_cluster_window_is_rejected_at_create
# ===========================================================================
def test_the_window_shape_rule_polices_order_and_span_with_one_code(api):
    """Both endpoints are well-formed instants; only their order and span are wrong.

    PRD 3.6: "The window must not be inverted and must span at most 14 calendar
    dates, or the claim is refused with `ERR_INVALID_CLUSTER_WINDOW`."

    Design: Corner/validations/inverted_cluster_window_is_rejected_at_create
    """
    world = fx.reference_world(api)
    customer_id = world["customer_id"]
    headers = make_customer_headers(customer_id)

    def attempt(start, end):
        return api.create_bunching_claim(
            f.bunching_claim_payload(customer_id, start, end), headers
        )

    inverted = attempt(INVERTED_WINDOW_START, INVERTED_WINDOW_END)
    validate_error(inverted, ERR_INVALID_CLUSTER_WINDOW)
    assert inverted.status_code == 422
    assert inverted.status_code != 400
    assert_error_meta_is_minimal(inverted)
    assert fx.claims_of(api, customer_id) == []

    # The same code guards the span, one date over the limit.
    assert (
        len(calendar_dates_between(FIFTEEN_DATE_WINDOW_START, FIFTEEN_DATE_WINDOW_END))
        == FIFTEEN_DATES
    )
    assert FIFTEEN_DATES == MAX_CLUSTER_WINDOW_DATES + 1
    too_wide = attempt(FIFTEEN_DATE_WINDOW_START, FIFTEEN_DATE_WINDOW_END)
    validate_error(too_wide, ERR_INVALID_CLUSTER_WINDOW)
    assert too_wide.status_code == 422
    assert fx.claims_of(api, customer_id) == []

    # Exactly fourteen dates is accepted, which is what makes the bound a bound.
    assert (
        len(calendar_dates_between(FIFTEEN_DATE_WINDOW_START, FOURTEEN_DATE_WINDOW_END))
        == MAX_CLUSTER_WINDOW_DATES
    )
    accepted = get_success_data(
        attempt(FIFTEEN_DATE_WINDOW_START, FOURTEEN_DATE_WINDOW_END), 201
    )
    assert accepted["status"] == CLAIM_SUBMITTED
    assert ids_of(fx.claims_of(api, customer_id)) == [accepted["id"]]


# --- claim sizes small enough that no ceiling can be what refuses -----------
SMALL_CLAIM_CENTS = 5000
TINY_CLAIM_CENTS = 1000


# ===========================================================================
# instance: second_cluster_window_sharing_one_date_with_a_granted_claim
# ===========================================================================
def test_two_windows_sharing_one_endpoint_date_overlap(api):
    """08-03..08-05 and 08-05..08-07 look disjoint and are not.

    PRD 3.6: "The consignee must also have no other claim in status `GRANTED` or
    `PARTIALLY_GRANTED` whose window overlaps this one, or
    `ERR_CLUSTER_WINDOW_OVERLAP`; windows are **closed** intervals, so two windows
    sharing even a single endpoint date overlap."

    Design: Corner/validations/second_cluster_window_sharing_one_date_with_a_granted_claim
    """
    world = fx.reference_world(api)
    customer_id = world["customer_id"]
    cycle = fx.released_cycle_a(api, world)
    assert cycle["chargeable_days"] == CYCLE_A_CHARGEABLE_DAYS

    first = fx.file_bunching_claim(
        api,
        customer_id,
        CLUSTER_WINDOW_START,
        CLUSTER_WINDOW_END,
        method=METHOD_ROLLING_AVERAGE_BASELINE,
    )
    # PRD 3.6: "A consignee with no history therefore gets a baseline of zero,
    # under which *every* car in the window is excess".
    granted = fx.analyze_claim(api, first["id"], ADJUDICATOR_BUNCHING)
    assert_subset_equal(
        granted,
        {
            "status": CLAIM_PARTIALLY_GRANTED,
            "baseline_per_day": 0,
            "delivered_car_count": 1,
            "cluster_chargeable_days": CYCLE_A_CHARGEABLE_DAYS,
            "exempt_days_granted": ONE_EXEMPT_DAY,
            "exempted_cycle_ids": [cycle["id"]],
        },
    )
    assert_subset_equal(
        fx.charge_of_cycle(api, cycle["id"]),
        {
            "bunching_exempt_days": ONE_EXEMPT_DAY,
            "billable_days": TWO_BILLABLE_DAYS,
            "gross_amount_cents": GROSS_AFTER_ONE_EXEMPTION,
        },
    )
    assert GROSS_AFTER_ONE_EXEMPTION == TWO_BILLABLE_DAYS * DEFAULT_TIER1_RATE_RAILROAD

    def attempt(start, end):
        return api.create_bunching_claim(
            f.bunching_claim_payload(
                customer_id, start, end, method=METHOD_ROLLING_AVERAGE_BASELINE
            ),
            make_customer_headers(customer_id),
        )

    refused = attempt(OVERLAPPING_WINDOW_START, OVERLAPPING_WINDOW_END)
    validate_error(refused, ERR_CLUSTER_WINDOW_OVERLAP)
    assert refused.status_code == 409
    assert_error_meta_is_minimal(refused)
    assert ids_of(fx.claims_of(api, customer_id)) == [first["id"]]

    # One date later there is no shared endpoint, and the same create lands.
    accepted = get_success_data(
        attempt(DISJOINT_WINDOW_START, OVERLAPPING_WINDOW_END), 201
    )
    assert accepted["status"] == CLAIM_SUBMITTED
    assert sorted(ids_of(fx.claims_of(api, customer_id))) == sorted(
        [first["id"], accepted["id"]]
    )


# ===========================================================================
# instance: second_open_average_agreement_for_the_same_month
# ===========================================================================
def test_the_agreement_month_is_exclusive_only_against_an_open_row(api):
    """A different ratio does not make it a different agreement.

    PRD 3.7: "A consignee may hold at most one `OPEN` agreement per month, and a
    second attempt is refused with `ERR_DUPLICATE_AGREEMENT_MONTH`; an agreement
    already `RECONCILED` or `FORFEITED` for that month does not block a new one."

    Design: Corner/validations/second_open_average_agreement_for_the_same_month
    """
    world = fx.reference_world(api)
    customer_id = world["customer_id"]
    first = fx.open_agreement(api, customer_id, credit_cap_ratio=FIRST_CAP_RATIO)
    assert_subset_equal(
        first,
        {
            "status": AGREEMENT_OPEN,
            "agreement_month": AGREEMENT_MONTH,
            "credit_cap_ratio": FIRST_CAP_RATIO,
            "credit_days_earned": 0,
            "debit_days_incurred": 0,
            "net_days": 0,
            "agreement_credit_cents": 0,
        },
    )

    refused = api.create_average_agreement(
        f.average_agreement_payload(customer_id, credit_cap_ratio=SECOND_CAP_RATIO),
        ADMIN,
    )
    validate_error(refused, ERR_DUPLICATE_AGREEMENT_MONTH)
    assert refused.status_code == 409
    assert_error_meta_is_minimal(refused)

    # Nothing was written, so the surviving row keeps the ratio it was born with.
    assert ids_of(fx.agreements_of(api, customer_id)) == [first["id"]]
    survivor = fx.get_agreement(api, customer_id, first["id"])
    assert_subset_equal(
        survivor, {"status": AGREEMENT_OPEN, "credit_cap_ratio": FIRST_CAP_RATIO}
    )
    assert survivor["version"] == first["version"]

    # The key includes the month, so September is free.
    september = get_success_data(
        api.create_average_agreement(
            f.average_agreement_payload(
                customer_id,
                agreement_month=NEXT_AGREEMENT_MONTH,
                credit_cap_ratio=SECOND_CAP_RATIO,
            ),
            ADMIN,
        ),
        201,
    )
    assert_subset_equal(
        september,
        {
            "status": AGREEMENT_OPEN,
            "agreement_month": NEXT_AGREEMENT_MONTH,
            "credit_cap_ratio": SECOND_CAP_RATIO,
        },
    )
    assert len(fx.agreements_of(api, customer_id)) == 2


# ===========================================================================
# instance: release_a_car_for_a_customer_on_credit_hold
# ===========================================================================
def test_the_fiscal_band_is_the_last_thing_a_release_can_fail_on(api):
    """Track OPEN, notice delivered, instant sound - and a 402 all the same.

    PRD 3.5: "The consignee's `billing_posture` must be `CURRENT`, or the release
    is refused with `ERR_CUSTOMER_CREDIT_HOLD` (HTTP 402); this is the sole
    operation the credit hold of §3.1 actually blocks."

    Design: Corner/validations/release_a_car_for_a_customer_on_credit_hold
    """
    world = fx.reference_world(api)
    customer_id = world["customer_id"]
    cycle = fx.actually_placed_cycle(api, world)
    assert_subset_equal(
        cycle,
        {"movement_status": MOVEMENT_ACTUALLY_PLACED, "released_at": None},
    )
    assert cycle["notification_sent_at"] is not None
    # The track is releasable and the car really is on a spot, so nothing
    # physical can be what refuses the release below.
    track = fx.probe_facility(api, world["facility_id"])
    assert_subset_equal(
        track, {"access_mode": ACCESS_MODE_OPEN, "occupied_spot_count": 1}
    )

    held = fx.put_on_credit_hold(api, customer_id)
    assert held["billing_posture"] == BILLING_POSTURE_CREDIT_HOLD

    payload = f.release_payload(CYCLE_A_RELEASE_AT)
    refused = api.release(cycle["id"], payload, make_customer_headers(customer_id))
    validate_error(refused, ERR_CUSTOMER_CREDIT_HOLD)
    assert refused.status_code == 402
    assert refused.status_code not in (409, 422)
    assert_error_meta_is_minimal(refused)

    frozen = fx.get_cycle(api, cycle["id"])
    assert frozen == cycle
    assert_subset_equal(
        frozen,
        {
            "movement_status": MOVEMENT_ACTUALLY_PLACED,
            "released_at": None,
            "chargeable_days": 0,
        },
    )
    assert fx.charge_of_cycle(api, cycle["id"])["status"] == CHARGE_PROVISIONAL

    # Clear the hold and the byte-identical release is accepted.
    cleared = get_success_data(
        api.set_credit_hold(customer_id, f.credit_hold_payload(False), ADMIN)
    )
    assert cleared["billing_posture"] == BILLING_POSTURE_CURRENT
    get_success_data(api.release(cycle["id"], payload, make_customer_headers(customer_id)))

    released = fx.get_cycle(api, cycle["id"])
    assert_subset_equal(
        released,
        {
            "movement_status": MOVEMENT_RELEASED,
            "chargeable_days": CYCLE_A_CHARGEABLE_DAYS,
        },
    )
    assert_instant_eq(released["released_at"], CYCLE_A_RELEASE_AT, "released_at")
    assert_subset_equal(
        fx.charge_of_cycle(api, cycle["id"]),
        {"status": CHARGE_FINAL, "gross_amount_cents": CYCLE_A_GROSS_CENTS},
    )


# ===========================================================================
# instance: actual_placement_dated_before_the_constructive_placement
# ===========================================================================
def test_chronology_compares_recorded_instants_and_never_the_clock(api):
    """The whole cycle is dated after the clock, which the service does not mind.

    PRD 3.4: "And `actual_placement_at` must be at or after the cycle's
    `constructive_placement_at`, or `ERR_NON_CHRONOLOGICAL_EVENT`."

    Design: Corner/validations/actual_placement_dated_before_the_constructive_placement
    """
    world = fx.reference_world(api, clock=COLD_START_CLOCK)
    # PRD 3.2: "These comparisons are always between *recorded* instants and never
    # against the logical clock, so back-dating an entire cycle is perfectly legal
    # as long as the recorded instants remain mutually consistent."  Here the
    # recorded instants sit four days AHEAD of the clock and are still accepted.
    cycle = fx.noticed_cycle(
        api, world, constructive_at=LATE_CONSTRUCTIVE_AT, sent_at=LATE_NOTICE_AT
    )
    assert_instant_eq(
        cycle["constructive_placement_at"],
        LATE_CONSTRUCTIVE_AT,
        "constructive_placement_at",
    )
    assert_instant_eq(cycle["notification_sent_at"], LATE_NOTICE_AT, "notification_sent_at")
    before_charge = fx.charge_of_cycle(api, cycle["id"])
    assert before_charge["status"] == CHARGE_PROVISIONAL

    refused = api.actual_placement(
        cycle["id"], f.actual_placement_payload(BACKDATED_ACTUAL_AT), AGENT
    )
    validate_error(refused, ERR_NON_CHRONOLOGICAL_EVENT)
    assert refused.status_code == 422
    assert_error_meta_is_minimal(refused)

    frozen = fx.get_cycle(api, cycle["id"])
    assert frozen == cycle
    assert_subset_equal(
        frozen,
        {
            "movement_status": MOVEMENT_CONSTRUCTIVELY_PLACED,
            "actual_placement_at": None,
            "clock_basis": CLOCK_BASIS_CONSTRUCTIVE,
        },
    )
    assert fx.charge_of_cycle(api, cycle["id"]) == before_charge
    assert fx.probe_facility(api, world["facility_id"])["occupied_spot_count"] == 0

    # "At or after" includes the instant itself, so the equal case is accepted.
    fx.place_actually(api, cycle["id"], LATE_CONSTRUCTIVE_AT)
    spotted = fx.get_cycle(api, cycle["id"])
    assert_subset_equal(
        spotted,
        {"movement_status": MOVEMENT_ACTUALLY_PLACED, "clock_basis": CLOCK_BASIS_ACTUAL},
    )
    assert_instant_eq(
        spotted["actual_placement_at"], LATE_CONSTRUCTIVE_AT, "actual_placement_at"
    )
    assert fx.probe_facility(api, world["facility_id"])["occupied_spot_count"] == 1


# ===========================================================================
# instance: whole_invoice_dispute_that_also_names_a_single_charge
# ===========================================================================
def test_the_scope_pairing_is_wrong_even_though_both_fields_are_right(api):
    """The charge really does belong to the invoice; naming it is still illegal.

    PRD 3.8: "The `scope` and the `demurrage_charge_id` must agree -
    `SINGLE_CHARGE` requires the charge reference and `WHOLE_INVOICE` requires its
    absence - or the filing is refused with `ERR_DISPUTE_SCOPE_MISMATCH`; the same
    pairing discipline governs the `BUNCHING` grounds against `bunching_claim_id`."

    Design: Corner/validations/whole_invoice_dispute_that_also_names_a_single_charge
    """
    world, cycle, invoice = _issued_single_line_invoice(api)
    charge = fx.charge_of_cycle(api, cycle["id"])
    assert charge["invoice_id"] == invoice["id"]

    def attempt(**extra):
        fresh = fx.get_invoice(api, invoice["id"])
        return api.create_dispute(
            f.dispute_payload(
                fresh["id"],
                fresh["version"],
                SMALL_CLAIM_CENTS,
                grounds=GROUNDS_CLOCK_BASIS_ERROR,
                **extra
            ),
            make_customer_headers(world["customer_id"]),
        )

    both = attempt(scope=SCOPE_WHOLE_INVOICE, demurrage_charge_id=charge["id"])
    validate_error(both, ERR_DISPUTE_SCOPE_MISMATCH)
    assert both.status_code == 422
    # The pairing band sits above the link band, so this is not the link failing.
    assert error_id_of(both) != ERR_CHARGE_INVOICE_MISMATCH
    assert_error_meta_is_minimal(both)
    assert fx.get_invoice(api, invoice["id"]) == invoice
    assert invoice["dispute_count"] == 0

    # The mirror-image omission fails on the very same code.
    neither = attempt(scope=SCOPE_SINGLE_CHARGE)
    validate_error(neither, ERR_DISPUTE_SCOPE_MISMATCH)
    assert neither.status_code == 422
    assert fx.get_invoice(api, invoice["id"])["dispute_count"] == 0

    # Dropping the reference makes the WHOLE_INVOICE filing land.
    created = get_success_data(attempt(scope=SCOPE_WHOLE_INVOICE), 201)
    assert_subset_equal(
        created,
        {
            "status": DISPUTE_DRAFT,
            "scope": SCOPE_WHOLE_INVOICE,
            "demurrage_charge_id": None,
            "claimed_credit_cents": SMALL_CLAIM_CENTS,
        },
    )
    assert fx.get_invoice(api, invoice["id"])["dispute_count"] == 1


# ===========================================================================
# instance: single_charge_dispute_pointing_at_another_invoices_charge
# ===========================================================================
def test_a_line_from_the_august_bill_cannot_be_disputed_on_the_july_bill(api):
    """Same consignee, both ids real, scope and reference in agreement - wrong bill.

    PRD 3.8: "If they agree but the named charge is not attached to the named
    invoice, the refusal is `ERR_CHARGE_INVOICE_MISMATCH`."

    Design: Corner/validations/single_charge_dispute_pointing_at_another_invoices_charge
    """
    world = fx.reference_world(api, clock=JULY_CLOCK)
    customer_id = world["customer_id"]
    july_track = fx.make_industry_track(api)
    july_cycle = fx.released_cycle(
        api,
        world,
        constructive_at=JULY_CONSTRUCTIVE_AT,
        sent_at=JULY_NOTICE_AT,
        actual_at=JULY_ACTUAL_AT,
        released_at=JULY_RELEASE_AT,
        facility_id=july_track["id"],
    )
    july_line = fx.charge_of_cycle(api, july_cycle["id"])
    assert_subset_equal(
        july_line, {"status": CHARGE_FINAL, "gross_amount_cents": 0}
    )

    july_invoice = fx.issued_invoice(
        api,
        world,
        draft_clock=JULY_DRAFT_CLOCK,
        issue_clock=JULY_DRAFT_CLOCK,
        billing_period_start=JULY_PERIOD_START,
        billing_period_end=JULY_PERIOD_END,
    )
    # A zero-money line is still an attached line, so the issue is not refused.
    assert_subset_equal(
        july_invoice,
        {
            "status": INVOICE_ISSUED,
            "attached_charge_count": 1,
            "total_gross_cents": 0,
            "dispute_count": 0,
        },
    )
    assert fx.get_charge(api, july_line["id"])["invoice_id"] == july_invoice["id"]

    august_cycle = fx.released_cycle_a(api, world)
    august_invoice = fx.issued_invoice(
        api, world, issue_clock=ISSUE_CLOCK_MID_AUGUST
    )
    august_line = fx.charge_of_cycle(api, august_cycle["id"])
    assert_subset_equal(
        august_invoice,
        {
            "status": INVOICE_ISSUED,
            "attached_charge_count": 1,
            "total_gross_cents": CYCLE_A_GROSS_CENTS,
        },
    )
    assert august_line["invoice_id"] == august_invoice["id"]
    assert august_invoice["customer_id"] == july_invoice["customer_id"]

    fresh = fx.get_invoice(api, july_invoice["id"])
    refused = api.create_dispute(
        f.dispute_payload(
            fresh["id"],
            fresh["version"],
            TINY_CLAIM_CENTS,
            scope=SCOPE_SINGLE_CHARGE,
            demurrage_charge_id=august_line["id"],
            grounds=GROUNDS_RAILROAD_CAUSED_DELAY,
        ),
        make_customer_headers(customer_id),
    )
    validate_error(refused, ERR_CHARGE_INVOICE_MISMATCH)
    assert refused.status_code == 422
    # Both ids exist and the pairing is sound: neither 404 nor the pairing code.
    assert refused.status_code != 404
    assert error_id_of(refused) != ERR_DISPUTE_SCOPE_MISMATCH
    assert_error_meta_is_minimal(refused)

    assert fx.get_invoice(api, july_invoice["id"])["dispute_count"] == 0
    assert fx.get_invoice(api, august_invoice["id"])["dispute_count"] == 0


# --- the supersede target and the escalation chain --------------------------
SUPERSEDE_CLAIM_CENTS = 6000


# ===========================================================================
# instance: supersedes_a_dispute_that_was_never_decided
# ===========================================================================
def test_a_draft_dispute_cannot_be_superseded(api):
    """The target exists and sits on this very invoice; it is simply not DECIDED.

    PRD 3.8: "A `supersedes_dispute_id` pointing at a dispute on a different
    invoice, or at one whose status is not `DECIDED`, is refused with
    `ERR_SUPERSEDE_TARGET_INVALID`."

    Design: Corner/validations/supersedes_a_dispute_that_was_never_decided
    """
    world, _cycle, invoice = _issued_single_line_invoice(api)
    first = fx.draft_dispute(
        api, invoice, world["customer_id"], SMALL_CLAIM_CENTS, scope=SCOPE_WHOLE_INVOICE
    )
    assert first["status"] == DISPUTE_DRAFT
    assert first["invoice_id"] == invoice["id"]
    after_first = fx.get_invoice(api, invoice["id"])
    assert after_first["dispute_count"] == 1

    def attempt(**extra):
        fresh = fx.get_invoice(api, invoice["id"])
        return api.create_dispute(
            f.dispute_payload(
                fresh["id"],
                fresh["version"],
                SUPERSEDE_CLAIM_CENTS,
                scope=SCOPE_WHOLE_INVOICE,
                grounds=GROUNDS_CLOCK_BASIS_ERROR,
                **extra
            ),
            make_customer_headers(world["customer_id"]),
        )

    refused = attempt(supersedes_dispute_id=first["id"])
    validate_error(refused, ERR_SUPERSEDE_TARGET_INVALID)
    assert refused.status_code == 422
    assert refused.status_code != 404
    assert_error_meta_is_minimal(refused)

    assert fx.get_dispute(api, first["id"])["status"] == DISPUTE_DRAFT
    assert fx.get_invoice(api, invoice["id"]) == after_first

    # Dropping the reference is all it takes: the rest of the filing was valid.
    created = get_success_data(attempt(), 201)
    assert_subset_equal(
        created,
        {
            "status": DISPUTE_DRAFT,
            "supersedes_dispute_id": None,
            "claimed_credit_cents": SUPERSEDE_CLAIM_CENTS,
        },
    )
    assert created["id"] != first["id"]
    assert fx.get_invoice(api, invoice["id"])["dispute_count"] == 2


def _answered_complaint_on_a_challenged_tariff(api):
    """A twice-decided RATE_UNREASONABLE dispute claiming 20000, escalated and answered.

    Every state band on the decide endpoint is satisfied by this fixture, so the
    only thing a refusal can be about is the money.
    """
    world = fx.reference_world(api)
    cycle = fx.released_cycle_a(api, world)
    invoice = fx.issued_invoice(api, world)
    assert invoice["total_gross_cents"] == CYCLE_A_GROSS_CENTS

    dispute = fx.twice_decided_dispute(
        api,
        invoice,
        world["customer_id"],
        ESCALATION_CLAIM_CENTS,
        ADJUDICATOR_ESCALATION_A,
        ADJUDICATOR_ESCALATION_B,
        round1_decision=DECISION_DENIED,
        round1_allowance_pct=0,
        round2_decision=DECISION_DENIED,
        round2_allowance_pct=0,
        scope=SCOPE_WHOLE_INVOICE,
        grounds=GROUNDS_RATE_UNREASONABLE,
    )
    assert_subset_equal(
        dispute,
        {
            "round_number": 2,
            "claimed_credit_cents": ESCALATION_CLAIM_CENTS,
            "allowed_credit_cents": 0,
        },
    )

    complaint = fx.filed_complaint(
        api,
        dispute["id"],
        world["customer_id"],
        complaint_type=COMPLAINT_TYPE_RULE_REASONABLENESS,
        tariff_rule_set_id=world["tariff_id"],
    )
    assert complaint["ordered_credit_cents"] == 0
    assert fx.get_dispute(api, dispute["id"])["status"] == DISPUTE_ESCALATED
    challenged = fx.get_tariff(api, world["tariff_id"])
    assert_subset_equal(
        challenged, {"status": TARIFF_STATUS_CHALLENGED, "challenge_count": 1}
    )

    answered = fx.answered_complaint(api, complaint["id"])
    assert answered["status"] == COMPLAINT_RAILROAD_ANSWERED
    return world, cycle, invoice, dispute, answered


def _get_complaint(api, complaint_id):
    return get_success_data(api.get_regulatory_complaint(complaint_id, OFFICER))


# ===========================================================================
# instance: regulatory_decision_ordering_more_credit_than_was_claimed
# ===========================================================================
def test_the_regulators_order_is_capped_by_the_claim_not_by_the_bill(api):
    """20001 fails against a 20000 claim on an invoice that grossed 47550.

    PRD 3.9: "The `ordered_credit_cents` must be 0 unless the outcome is
    `DECIDED_FOR_CUSTOMER`, and on any outcome it may never exceed the escalated
    dispute's `claimed_credit_cents`; both violations are refused with
    `ERR_ORDERED_CREDIT_EXCEEDS_CLAIM`."

    Design: Corner/validations/regulatory_decision_ordering_more_credit_than_was_claimed
    """
    world, cycle, _invoice, dispute, answered = _answered_complaint_on_a_challenged_tariff(
        api
    )
    assert ONE_CENT_OVER_THE_CLAIM < CYCLE_A_GROSS_CENTS

    refused = api.decide_regulatory_complaint(
        answered["id"],
        f.complaint_decision_payload(
            COMPLAINT_DECIDED_FOR_CUSTOMER, ONE_CENT_OVER_THE_CLAIM
        ),
        OFFICER,
    )
    validate_error(refused, ERR_ORDERED_CREDIT_EXCEEDS_CLAIM)
    assert refused.status_code == 422
    assert_error_meta_is_minimal(refused)

    frozen = _get_complaint(api, answered["id"])
    assert_subset_equal(
        frozen,
        {
            "status": COMPLAINT_RAILROAD_ANSWERED,
            "ordered_credit_cents": 0,
            "version": answered["version"],
        },
    )
    # The tariff's own loop did not close either: it is still under challenge.
    assert_subset_equal(
        fx.get_tariff(api, world["tariff_id"]),
        {"status": TARIFF_STATUS_CHALLENGED, "challenge_count": 1},
    )
    assert fx.get_dispute(api, dispute["id"])["status"] == DISPUTE_ESCALATED
    assert_subset_equal(
        fx.charge_of_cycle(api, cycle["id"]),
        {"status": CHARGE_FINAL, "gross_amount_cents": CYCLE_A_GROSS_CENTS},
    )

    # The other arm of the same rule: any non-zero amount for the railroad.
    for_railroad = api.decide_regulatory_complaint(
        answered["id"],
        f.complaint_decision_payload(
            COMPLAINT_DECIDED_FOR_RAILROAD, ESCALATION_CLAIM_CENTS
        ),
        OFFICER,
    )
    validate_error(for_railroad, ERR_ORDERED_CREDIT_EXCEEDS_CLAIM)
    assert for_railroad.status_code == 422
    assert _get_complaint(api, answered["id"])["version"] == answered["version"]

    # Exactly the claim is accepted, which is what makes the cap a cap.
    decided = get_success_data(
        api.decide_regulatory_complaint(
            answered["id"],
            f.complaint_decision_payload(
                COMPLAINT_DECIDED_FOR_CUSTOMER, ESCALATION_CLAIM_CENTS
            ),
            OFFICER,
        )
    )
    assert_subset_equal(
        decided,
        {
            "status": COMPLAINT_DECIDED_FOR_CUSTOMER,
            "ordered_credit_cents": ESCALATION_CLAIM_CENTS,
            "version": answered["version"] + 1,
        },
    )


# ===========================================================================
# instance: new_cycle_on_a_tariff_withdrawn_by_the_regulator
# ===========================================================================
def test_a_withdrawn_tariff_blocks_new_cycles_without_touching_the_old_one(api):
    """The regulator's order kills the rule set forward and rewrites nothing behind it.

    PRD 3.9: "A `WITHDRAWN` rule set is terminal and can no longer back a new
    placement cycle, which is where `ERR_TARIFF_WITHDRAWN` comes from, but the
    withdrawal is not retroactive - cycles already pinned to it keep the rates they
    were rated at, exactly as a superseded rule set's cycles do."

    Design: Corner/validations/new_cycle_on_a_tariff_withdrawn_by_the_regulator
    """
    world, cycle, invoice, dispute, answered = _answered_complaint_on_a_challenged_tariff(
        api
    )
    decided = get_success_data(
        api.decide_regulatory_complaint(
            answered["id"],
            f.complaint_decision_payload(
                COMPLAINT_DECIDED_FOR_CUSTOMER, ESCALATION_CLAIM_CENTS
            ),
            OFFICER,
        )
    )
    assert_subset_equal(
        decided,
        {
            "status": COMPLAINT_DECIDED_FOR_CUSTOMER,
            "ordered_credit_cents": ESCALATION_CLAIM_CENTS,
        },
    )
    withdrawn = fx.get_tariff(api, world["tariff_id"])
    assert_subset_equal(
        withdrawn, {"status": TARIFF_STATUS_WITHDRAWN, "challenge_count": 1}
    )

    second_car = fx.make_rail_car(api)
    assert second_car["active_cycle_count"] == 0
    payload = f.placement_cycle_payload(
        world["customer_id"],
        second_car["id"],
        world["facility_id"],
        world["tariff_id"],
        second_car["version"],
    )
    refused = api.create_placement_cycle(payload, AGENT)
    validate_error(refused, ERR_TARIFF_WITHDRAWN)
    assert refused.status_code == 422
    assert_error_meta_is_minimal(refused)

    untouched_car = fx.get_car(api, second_car["id"])
    assert_subset_equal(
        untouched_car,
        {"version": second_car["version"], "active_cycle_count": 0},
    )

    # PRD 3.9: "no charge line is rewritten, no invoice total moves".
    assert_subset_equal(
        fx.charge_of_cycle(api, cycle["id"]),
        {
            "status": CHARGE_FINAL,
            "gross_amount_cents": CYCLE_A_GROSS_CENTS,
        },
    )
    # PRD 3.2 pins the rule set on the cycle, not on the charge line, and the
    # withdrawal is not retroactive: the old cycle keeps pointing at it.
    assert (
        fx.get_cycle(api, cycle["id"])["tariff_rule_set_id"] == world["tariff_id"]
    )
    assert fx.get_invoice(api, invoice["id"])["total_gross_cents"] == CYCLE_A_GROSS_CENTS
    assert fx.get_dispute(api, dispute["id"])["status"] == DISPUTE_ESCALATED
    assert fx.get_dispute(api, dispute["id"])["allowed_credit_cents"] == 0


# ===========================================================================
# instance: private_car_placed_under_a_railroad_only_tariff
# ===========================================================================
def test_a_railroad_only_tariff_will_not_rate_a_private_car(api):
    """The rule set is PUBLISHED and in force; it simply does not cover this car.

    PRD 3.2: "A rule set whose `car_ownership_scope` does not cover the car's
    `ownership` - a `RAILROAD_OWNED`-scoped tariff cited for a `PRIVATE` car, for
    instance - yields `ERR_TARIFF_SCOPE_MISMATCH`."

    Design: Corner/validations/private_car_placed_under_a_railroad_only_tariff
    """
    fx.set_clock(api, COLD_START_CLOCK)
    customer = fx.make_customer(api)
    facility = fx.make_industry_track(api)
    railroad_only = fx.make_published_tariff(
        api, car_ownership_scope=CAR_OWNERSHIP_SCOPE_RAILROAD_OWNED
    )
    car = fx.make_rail_car(api, ownership=OWNERSHIP_PRIVATE)
    assert car["ownership"] == OWNERSHIP_PRIVATE
    assert railroad_only["car_ownership_scope"] == CAR_OWNERSHIP_SCOPE_RAILROAD_OWNED
    assert railroad_only["status"] == TARIFF_STATUS_PUBLISHED

    refused = api.create_placement_cycle(
        f.placement_cycle_payload(
            customer["id"],
            car["id"],
            facility["id"],
            railroad_only["id"],
            car["version"],
        ),
        AGENT,
    )
    validate_error(refused, ERR_TARIFF_SCOPE_MISMATCH)
    assert refused.status_code == 422
    assert error_id_of(refused) != ERR_TARIFF_WITHDRAWN
    assert_error_meta_is_minimal(refused)

    frozen = fx.get_car(api, car["id"])
    assert_subset_equal(
        frozen, {"version": car["version"], "active_cycle_count": 0}
    )

    # A wide-scope rule set takes the identical car without complaint.
    any_scope = fx.make_published_tariff(
        api, car_ownership_scope=CAR_OWNERSHIP_SCOPE_ANY
    )
    created = get_success_data(
        api.create_placement_cycle(
            f.placement_cycle_payload(
                customer["id"],
                car["id"],
                facility["id"],
                any_scope["id"],
                frozen["version"],
            ),
            AGENT,
        ),
        201,
    )
    assert_subset_equal(
        created,
        {
            "tariff_rule_set_id": any_scope["id"],
            "billing_status": BILLING_UNBILLED,
            "rail_car_id": car["id"],
        },
    )
    assert fx.get_car(api, car["id"])["active_cycle_count"] == 1


# ===========================================================================
# instance: release_before_any_notice_reached_the_customer
# ===========================================================================
def test_the_notice_is_optional_for_the_spot_and_mandatory_for_the_release(api):
    """A car legitimately sits on a spot with a clock the notice never authorised.

    PRD 3.5: "The industry-track path carries one further guard: the cycle's
    `notification_sent_at` must not be null, or the release is refused with
    `ERR_NOTIFICATION_NOT_SENT` - which is precisely what happens when the only
    notice on the cycle `FAILED` because it went out on the wrong channel."

    Design: Corner/validations/release_before_any_notice_reached_the_customer
    """
    world = fx.reference_world(api)
    customer_id = world["customer_id"]
    cycle = fx.constructively_placed_cycle(api, world)
    assert_subset_equal(
        cycle,
        {
            "movement_status": MOVEMENT_CONSTRUCTIVELY_PLACED,
            "notification_sent_at": None,
            "clock_basis": CLOCK_BASIS_NONE,
            "clock_start_at": None,
        },
    )

    # The spot needs no notice at all, and the clock starts on the spot alone.
    fx.place_actually(api, cycle["id"], CYCLE_A_ACTUAL_AT)
    spotted = fx.get_cycle(api, cycle["id"])
    assert_subset_equal(
        spotted,
        {
            "movement_status": MOVEMENT_ACTUALLY_PLACED,
            "notification_sent_at": None,
            "clock_basis": CLOCK_BASIS_ACTUAL,
        },
    )
    assert_instant_eq(spotted["clock_start_at"], CYCLE_A_ACTUAL_AT, "clock_start_at")
    assert_instant_eq(
        spotted["free_time_expires_at"], CYCLE_A_ACTUAL_EXPIRY, "free_time_expires_at"
    )
    assert_end_of_day(spotted["free_time_expires_at"], "free_time_expires_at")

    payload = f.release_payload(CYCLE_A_RELEASE_AT)
    refused = api.release(cycle["id"], payload, make_customer_headers(customer_id))
    validate_error(refused, ERR_NOTIFICATION_NOT_SENT)
    assert refused.status_code == 422
    assert_error_meta_is_minimal(refused)

    frozen = fx.get_cycle(api, cycle["id"])
    assert frozen == spotted
    assert frozen["released_at"] is None
    assert fx.charge_of_cycle(api, cycle["id"])["status"] == CHARGE_PROVISIONAL

    # One matching EDI notice, and the byte-identical release lands.
    notice = fx.send_notice(api, cycle["id"], CYCLE_A_NOTICE_SENT_AT, CHANNEL_EDI)
    assert notice["delivery_status"] == DELIVERY_DELIVERED
    get_success_data(api.release(cycle["id"], payload, make_customer_headers(customer_id)))

    released = fx.get_cycle(api, cycle["id"])
    assert_subset_equal(
        released,
        {
            "movement_status": MOVEMENT_RELEASED,
            "chargeable_days": CYCLE_A_CHARGEABLE_DAYS,
        },
    )
    assert_subset_equal(
        fx.charge_of_cycle(api, cycle["id"]),
        {"status": CHARGE_FINAL, "gross_amount_cents": CYCLE_A_GROSS_CENTS},
    )


# ===========================================================================
# instance: acknowledge_when_the_only_notice_failed_on_the_wrong_channel
# ===========================================================================
def test_a_failed_notice_leaves_nothing_to_acknowledge(api):
    """A notification row exists, so this is not an empty collection - it is unselectable.

    PRD 3.3: "If the cycle has no such notification - because its only notice
    `FAILED` on the wrong channel, or because every eligible notice is already
    `ACKNOWLEDGED` - the request is refused with `ERR_NO_PENDING_NOTIFICATION`."

    Design: Corner/validations/acknowledge_when_the_only_notice_failed_on_the_wrong_channel
    """
    world = fx.reference_world(
        api, customer_overrides={"notification_method": NOTIFICATION_METHOD_FAX}
    )
    assert world["customer"]["notification_method"] == NOTIFICATION_METHOD_FAX
    cycle = fx.constructively_placed_cycle(api, world)

    notice = fx.send_notice(api, cycle["id"], CYCLE_A_NOTICE_SENT_AT, CHANNEL_EDI)
    assert_subset_equal(
        notice,
        {
            "placement_cycle_id": cycle["id"],
            "channel": CHANNEL_EDI,
            "delivery_status": DELIVERY_FAILED,
            "sequence_number": 1,
            "acknowledged_at": None,
        },
    )

    refused = api.acknowledge_notification(
        cycle["id"],
        f.acknowledge_payload(FAX_ACK_AT),
        make_customer_headers(world["customer_id"]),
    )
    validate_error(refused, ERR_NO_PENDING_NOTIFICATION)
    assert refused.status_code == 422
    assert_error_meta_is_minimal(refused)

    # PRD 3.3: "Because a `FAILED` notice never qualifies, a notice transmitted on
    # the wrong channel contributes nothing at all".
    # PRD 3.3 step 5 nulls `clock_start_at` and `free_time_expires_at` when the
    # constructive start is null, but step 3 computes `free_days` unconditionally
    # from the tariff - 48 railroad free-time hours divided by 24 - so it reads 2.
    frozen = fx.get_cycle(api, cycle["id"])
    assert_subset_equal(
        frozen,
        {
            "notification_sent_at": None,
            "notification_acknowledged_at": None,
            "clock_basis": CLOCK_BASIS_NONE,
            "clock_start_at": None,
            "free_time_expires_at": None,
            "free_days": DEFAULT_FREE_TIME_HOURS_RAILROAD // 24,
        },
    )

    rows = get_success_data(
        api.list_notifications(cycle["id"], AGENT, {"limit": 10, "offset": 0})
    )
    assert ids_of(rows) == [notice["id"]]
    assert_subset_equal(
        rows[0],
        {
            "delivery_status": DELIVERY_FAILED,
            "acknowledged_at": None,
            "sequence_number": 1,
        },
    )
