"""Queue B - corner section ``state_machines``.

Nineteen instances covering the initial states of the two independent cycle
axes, the valid and invalid edges of every machine in the service, the
side effects those edges fire, the terminal states that lock down, the
counters that refuse an edge a status check would have admitted, and the one
cyclic edge the tariff machine owns.

Two rendering conventions apply to the PRD quotations in the docstrings below:
the PRD's em dashes are written as ASCII hyphens and its transition arrows as
``->``.  Nothing else is altered, so every quoted sentence is greppable in
``workspace/PRD.md`` once those two substitutions are made.
"""

import re

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AGREEMENT_INVALID_STATE,
    ERR_APPEAL_LIMIT,
    ERR_CHARGE_INVALID_STATE,
    ERR_CLAIM_INVALID_STATE,
    ERR_COMPLAINT_INVALID_STATE,
    ERR_DISPUTE_INVALID_STATE,
    ERR_INFO_REQUEST_LIMIT,
    ERR_INVALID_MOVEMENT_STATE,
    ERR_INVOICE_INVALID_STATE,
    ERR_REFUSAL_LIMIT,
    ERR_TARIFF_INVALID_STATE,
    ERR_TARIFF_NOT_PUBLISHED,
)
from test_helpers.assertions import (
    assert_charge_money_invariant,
    assert_common_fields,
    assert_end_of_day,
    assert_error_meta_is_minimal,
    assert_instant_eq,
    assert_invoice_money_invariant,
    assert_light_fields,
    assert_pagination_meta,
    assert_server_minted_id,
    assert_subset_equal,
    add_calendar_days,
    business_dates_strictly_after,
    calendar_dates_between,
    end_of,
    error_id_of,
    is_business_date,
)
from test_helpers.constants import (
    AGREEMENT_OPEN,
    AGREEMENT_RECONCILED,
    BASIS_STORAGE_CALENDAR,
    BILLING_DISPUTED,
    BILLING_INVOICED,
    BILLING_SETTLED,
    BILLING_UNBILLED,
    CHANNEL_EDI,
    CHANNEL_EMAIL,
    CHARGE_ADJUSTED,
    CHARGE_DISPUTED,
    CHARGE_FINAL,
    CHARGE_KIND_DEMURRAGE,
    CHARGE_KIND_STORAGE,
    CHARGE_PROVISIONAL,
    CLAIM_DENIED,
    CLAIM_SUBMITTED,
    CLOCK_BASIS_CONSTRUCTIVE,
    CLOCK_BASIS_NONE,
    COLD_START_CLOCK,
    COMPLAINT_DISMISSED,
    COMPLAINT_FILED,
    COMPLAINT_RAILROAD_ANSWERED,
    COMPLAINT_RESPONSE_DUE_AT,
    COMPLAINT_TYPE_BILLING_PRACTICE,
    COMPLAINT_TYPE_RULE_REASONABLENESS,
    CYCLE_A_ACTUAL_AT,
    CYCLE_A_CHARGEABLE_DAYS,
    CYCLE_A_CONSTRUCTIVE_AT,
    CYCLE_A_CONSTRUCTIVE_EXPIRY,
    CYCLE_A_CONSTRUCTIVE_START,
    CYCLE_A_GROSS_CENTS,
    DECISION_DENIED,
    DECISION_PARTIALLY_ALLOWED,
    DECISION_PENDING,
    DEFAULT_STORAGE_DAILY_RATE_CENTS,
    DEFAULT_STORAGE_FREE_HOURS,
    DEFAULT_TIER1_RATE_RAILROAD,
    DELIVERY_DELIVERED,
    DELIVERY_FAILED,
    DISPUTE_APPEALED,
    DISPUTE_DECIDED,
    DISPUTE_DRAFT,
    DISPUTE_ESCALATED,
    DISPUTE_INFO_REQUESTED,
    DISPUTE_POSTURE_CLEAR,
    DISPUTE_POSTURE_ESCALATED,
    DISPUTE_POSTURE_UNDER_REVIEW,
    DISPUTE_SUBMITTED,
    DISPUTE_UNDER_REVIEW,
    DOCKET_NUMBER_PATTERN,
    DUE_AT_AFTER_INFO_REQUEST,
    DUE_AT_APPEAL_ROUND,
    DUE_AT_BASE_20_MULT_1_00_WEIGHT_3,
    EVIDENCE_GATE_LOG,
    EVIDENCE_WEIGHT_CERTIFICATE,
    FACILITY_KIND_RAIL_YARD,
    INVOICE_ADJUSTED,
    INVOICE_CLOSED,
    INVOICE_ISSUED,
    INVOICE_PARTIALLY_DISPUTED,
    MOVEMENT_ACTUALLY_PLACED,
    MOVEMENT_CONSTRUCTIVELY_PLACED,
    MOVEMENT_ORDERED,
    MOVEMENT_RELEASED,
    MOVEMENT_VOIDED,
    REASON_TRACK_FULL,
    REASON_YARD_ARRIVAL,
    SCOPE_SINGLE_CHARGE,
    SCOPE_WHOLE_INVOICE,
    STORAGE_CLOCK_CALENDAR,
    TARIFF_STATUS_CHALLENGED,
    TARIFF_STATUS_DRAFT,
    TARIFF_STATUS_PUBLISHED,
    TARIFF_STATUS_SUPERSEDED,
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

# --- instance 1 literals ---------------------------------------------------
WAYBILL_FRESH_CYCLE = "WB-C9S1-1"
FRESH_CYCLE_NULL_FIELDS = (
    "constructive_placement_at",
    "constructive_reason_code",
    "notification_sent_at",
    "notification_acknowledged_at",
    "actual_placement_at",
    "released_at",
    "clock_start_at",
    "free_time_expires_at",
)

# --- instance 3 literals ---------------------------------------------------
NOTICE_EMAIL_AT = "2026-08-03T09:00:00.000Z"
NOTICE_EDI_AT = "2026-08-03T11:00:00.000Z"
CLOCK_START_AFTER_EDI_NOTICE = "2026-08-03T15:00:00.000Z"  # 11:00 plus 4 grace hours
FREE_DAYS_RAILROAD = 2

# --- instance 5 literals ---------------------------------------------------
SECOND_VOID_REASON = "Cancelled again."

# --- instance 7 literals (the RAIL_YARD storage cascade) -------------------
YARD_NOTICE_AT = "2026-08-03T09:00:00.000Z"
YARD_RELEASE_AT = "2026-08-11T09:00:00.000Z"
YARD_STORAGE_DAYS = 5  # 2026-08-05, 06, 07, 10 and 11; the weekend is skipped
YARD_STORAGE_GROSS_CENTS = 45000  # 5 x 9000

# --- shared money-chain stations -------------------------------------------
ISSUE_CLOCK_MID_AUGUST = "2026-08-15T00:00:00.000Z"
SUBMIT_CLOCK_MID_AUGUST = "2026-08-15T10:00:00.000Z"

# --- instance 9 literals ---------------------------------------------------
ADJUDICATOR_DENYING = "adj-c9s9-a"

# --- instance 10 literals --------------------------------------------------
TARIFF_CODE_INCUMBENT = "C9S10-6004"
TARIFF_CODE_UNRELATED = "C9S10-7100"

# --- instance 11 literals --------------------------------------------------
CLUSTER_WINDOW_START = "2026-08-03"
CLUSTER_WINDOW_END = "2026-08-05"
CLUSTER_CAPACITY = 3
ADJUDICATOR_ANALYZING = "adj-c9s11-a"

# --- instance 13 literals (three spots, two legal refusals) ----------------
SPOT_ONE_AT = "2026-08-05T10:00:00.000Z"
SPOT_TWO_AT = "2026-08-06T10:00:00.000Z"
SPOT_THREE_AT = "2026-08-07T10:00:00.000Z"
REFUSAL_REASON = "Wrong commodity."

# --- instance 16 literals (two legal information-request loops) -------------
ADJUDICATOR_REQUESTING = "adj-c9s16-a"
INFO_REQUEST_ONE_CLOCK = "2026-08-20T09:00:00.000Z"
RESUBMIT_ONE_CLOCK = "2026-08-22T09:00:00.000Z"
INFO_REQUEST_TWO_CLOCK = "2026-08-25T09:00:00.000Z"
RESUBMIT_TWO_CLOCK = "2026-08-27T09:00:00.000Z"
# The 10th business date strictly after 2026-08-25 is 2026-09-08.
DUE_AT_AFTER_SECOND_INFO_REQUEST = "2026-09-08T23:59:59.999Z"
EVIDENCE_WEIGHT_AFTER_ONE = 3  # SWITCH_LIST
EVIDENCE_WEIGHT_AFTER_TWO = 6  # plus GATE_LOG
EVIDENCE_WEIGHT_AFTER_THREE = 8  # plus WEIGHT_CERTIFICATE

# --- instance 17 literals (both rounds spent, then a third appeal) ----------
ADJUDICATOR_ROUND_ONE = "adj-c9s17-a"
ADJUDICATOR_ROUND_TWO = "adj-c9s17-b"
CLAIM_CEILING_R17 = 30000
ROUND_ONE_ALLOWANCE_PCT = 0.5
ROUND_ONE_CREDIT_CENTS = 23775  # 47550 x 0.50, under the 30000 claim ceiling

# --- instances 18 and 19 literals ------------------------------------------
ADJUDICATOR_BILLING_A = "adj-c9s18-a"
ADJUDICATOR_BILLING_B = "adj-c9s18-b"
ADJUDICATOR_RULE_A = "adj-c9s19-a"
ADJUDICATOR_RULE_B = "adj-c9s19-b"
COMPLAINT_FILING_CLOCK = "2026-09-05T09:00:00.000Z"
FIRST_DOCKET_NUMBER = "D-00001"
RULE_NARRATIVE = "Rule 6004 tier three is unreasonable on this lane."
WAYBILL_MID_LOOP = "WB-C9S19-2"


def _fresh_cycle_payload(api, world, car):
    return f.placement_cycle_payload(
        world["customer_id"],
        car["id"],
        world["facility_id"],
        world["tariff_id"],
        car["version"],
        waybill_number=WAYBILL_FRESH_CYCLE,
    )


# ===========================================================================
# instance: placement_cycle_starts_ordered_and_unbilled_on_both_axes
# ===========================================================================
def test_a_fresh_cycle_reports_ordered_and_unbilled_at_the_same_moment(api):
    """Two machines, two initial states, one row - and no charge line yet.

    PRD 3.2: "A cycle deliberately carries two independent state dimensions, and
    confusing them is the fastest way to build this service incorrectly.
    `movement_status` is the physical dimension and begins at `ORDERED`;
    `billing_status` is the money dimension and begins at `UNBILLED`."

    Design: Corner/state_machines/placement_cycle_starts_ordered_and_unbilled_on_both_axes
    """
    world = fx.reference_world(api)
    car = fx.make_rail_car(api)
    created = get_success_data(
        api.create_placement_cycle(_fresh_cycle_payload(api, world, car), AGENT), 201
    )

    assert_common_fields(created)
    assert_subset_equal(
        created,
        {
            "movement_status": MOVEMENT_ORDERED,
            "billing_status": BILLING_UNBILLED,
            "clock_basis": CLOCK_BASIS_NONE,
            "refusal_count": 0,
            "free_days": 0,
            "chargeable_days": 0,
            "early_release_days": 0,
            "waybill_number": WAYBILL_FRESH_CYCLE,
            "customer_id": world["customer_id"],
            "rail_car_id": car["id"],
            "facility_id": world["facility_id"],
            "tariff_rule_set_id": world["tariff_id"],
        },
    )
    # PRD 3.2: "and null in each of `constructive_placement_at`,
    # `constructive_reason_code`, `notification_sent_at`,
    # `notification_acknowledged_at`, `actual_placement_at`, `released_at`,
    # `clock_start_at` and `free_time_expires_at`."
    for field in FRESH_CYCLE_NULL_FIELDS:
        assert created[field] is None, "%s must be null on a fresh cycle" % field

    # PRD 3.2: "No charge line exists yet: a charge is born at constructive
    # placement, not at ordering."
    listed = api.list_charges(
        ADMIN, {"placement_cycle_id": created["id"], "limit": 10, "offset": 0}
    )
    assert get_success_data(listed) == []
    assert_pagination_meta(
        listed.json()["meta"], limit=10, offset=0, total_count=0, has_more=False
    )

    moved = fx.get_car(api, car["id"])
    assert moved["active_cycle_count"] == 1
    assert moved["version"] == car["version"] + 1


# ===========================================================================
# instance: valid_transition_ordered_to_constructively_placed_creates_a_provisional_charge
# ===========================================================================
def test_constructive_placement_spawns_a_provisional_line_with_no_clock_running(api):
    """The edge fires, the charge is born, and the clock still cannot start.

    PRD 3.2: "Recording constructive placement also re-runs the clock-basis
    election of §3.3, but on its own it cannot start a clock: with no arrival
    notice yet on file, `clock_basis` remains `NONE`."

    Design: Corner/state_machines/valid_transition_ordered_to_constructively_placed_creates_a_provisional_charge
    """
    world = fx.reference_world(api)
    cycle = fx.make_cycle(api, world)
    placed = fx.place_constructively(
        api, cycle["id"], CYCLE_A_CONSTRUCTIVE_AT, REASON_TRACK_FULL
    )

    assert_subset_equal(
        placed,
        {
            "movement_status": MOVEMENT_CONSTRUCTIVELY_PLACED,
            "billing_status": BILLING_UNBILLED,
            "constructive_reason_code": REASON_TRACK_FULL,
            "clock_basis": CLOCK_BASIS_NONE,
            "clock_start_at": None,
            "free_time_expires_at": None,
        },
    )
    assert_instant_eq(
        placed["constructive_placement_at"],
        CYCLE_A_CONSTRUCTIVE_AT,
        "constructive_placement_at",
    )
    assert placed["version"] == cycle["version"] + 1

    # PRD 3.2: "Constructive placement creates the cycle's single **charge
    # line**, always in status `PROVISIONAL`, always referencing its owning cycle
    # through `placement_cycle_id`, and always with `invoice_id` still null."
    charge = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        charge,
        {
            "status": CHARGE_PROVISIONAL,
            "charge_kind": CHARGE_KIND_DEMURRAGE,
            "placement_cycle_id": cycle["id"],
            "invoice_id": None,
            "bunching_exempt_days": 0,
            "billable_days": 0,
            "chargeable_days": 0,
            "gross_amount_cents": 0,
            "credit_applied_cents": 0,
            "net_amount_cents": 0,
        },
    )
    assert_charge_money_invariant(charge)


# ===========================================================================
# instance: notify_side_effect_stamps_sequence_number_and_delivery_status_failed_on_channel_mismatch
# ===========================================================================
def test_a_failed_notice_takes_a_sequence_number_and_starts_no_clock(api):
    """Three-valued delivery: the EMAIL notice fails, and only the EDI one counts.

    PRD 3.3: "The `delivery_status` is decided in a fixed order: if the `channel`
    used differs from the consignee's contractual `notification_method`, the
    notice is `FAILED`; otherwise, if the channel is `EDI`, the notice is
    `DELIVERED`; otherwise it is `SENT`."

    Design: Corner/state_machines/notify_side_effect_stamps_sequence_number_and_delivery_status_failed_on_channel_mismatch
    """
    world = fx.reference_world(api)
    cycle = fx.constructively_placed_cycle(api, world, CYCLE_A_CONSTRUCTIVE_AT)

    # The consignee is contractually on EDI, so an EMAIL notice cannot land.
    get_success_data(
        api.notify(cycle["id"], f.notify_payload(NOTICE_EMAIL_AT, CHANNEL_EMAIL), AGENT)
    )
    after_failure = get_success_data(
        api.list_notifications(cycle["id"], AGENT, {"limit": 10, "offset": 0})
    )
    assert len(after_failure) == 1
    assert_light_fields(after_failure[0])
    assert_subset_equal(
        after_failure[0],
        {
            "placement_cycle_id": cycle["id"],
            "channel": CHANNEL_EMAIL,
            "sequence_number": 1,
            "delivery_status": DELIVERY_FAILED,
            "acknowledged_at": None,
        },
    )
    assert_instant_eq(after_failure[0]["sent_at"], NOTICE_EMAIL_AT, "sent_at")

    # PRD 3.3: "Because a `FAILED` notice never qualifies, a notice transmitted
    # on the wrong channel contributes nothing at all."
    mid = fx.get_cycle(api, cycle["id"])
    assert mid["notification_sent_at"] is None
    assert mid["clock_basis"] == CLOCK_BASIS_NONE
    assert mid["free_time_expires_at"] is None

    get_success_data(
        api.notify(cycle["id"], f.notify_payload(NOTICE_EDI_AT, CHANNEL_EDI), AGENT)
    )
    listed = api.list_notifications(cycle["id"], AGENT, {"limit": 10, "offset": 0})
    rows = get_success_data(listed)
    assert_pagination_meta(
        listed.json()["meta"], limit=10, offset=0, total_count=2, has_more=False
    )
    assert [row["sequence_number"] for row in rows] == [1, 2]
    assert_subset_equal(
        rows[1],
        {
            "channel": CHANNEL_EDI,
            "sequence_number": 2,
            "delivery_status": DELIVERY_DELIVERED,
        },
    )
    assert rows[0]["delivery_status"] == DELIVERY_FAILED

    after = fx.get_cycle(api, cycle["id"])
    assert_instant_eq(
        after["notification_sent_at"], NOTICE_EDI_AT, "notification_sent_at"
    )
    assert_subset_equal(
        after,
        {
            "movement_status": MOVEMENT_CONSTRUCTIVELY_PLACED,
            "clock_basis": CLOCK_BASIS_CONSTRUCTIVE,
            "free_days": FREE_DAYS_RAILROAD,
        },
    )
    assert_instant_eq(
        after["clock_start_at"], CLOCK_START_AFTER_EDI_NOTICE, "clock_start_at"
    )
    assert_instant_eq(
        after["free_time_expires_at"],
        CYCLE_A_CONSTRUCTIVE_EXPIRY,
        "free_time_expires_at",
    )


# ===========================================================================
# instance: actual_placement_from_ordered_returns_invalid_movement_state
# ===========================================================================
def test_there_is_no_ordered_to_actually_placed_edge(api):
    """A car cannot be spotted before it has been constructively placed.

    PRD 3.4: "A `RailroadAgent` records **actual placement** by supplying the
    `actual_placement_at` instant, taking the cycle `CONSTRUCTIVELY_PLACED ->
    ACTUALLY_PLACED`. A cycle in any other `movement_status` - an `ORDERED` cycle
    that was never constructively placed, for example - is refused with
    `ERR_INVALID_MOVEMENT_STATE`."

    Design: Corner/state_machines/actual_placement_from_ordered_returns_invalid_movement_state
    """
    world = fx.reference_world(api)
    cycle = fx.make_cycle(api, world)
    before = fx.get_cycle(api, cycle["id"])
    assert before["movement_status"] == MOVEMENT_ORDERED

    empty_track = fx.probe_facility(api, world["facility_id"])
    assert empty_track["occupied_spot_count"] == 0
    assert empty_track["last_switch_at"] is None

    refused = api.actual_placement(
        cycle["id"], f.actual_placement_payload(CYCLE_A_ACTUAL_AT), AGENT
    )
    validate_error(refused, ERR_INVALID_MOVEMENT_STATE)
    assert refused.status_code == 409
    assert_error_meta_is_minimal(refused)

    after = fx.get_cycle(api, cycle["id"])
    assert after == before
    assert after["actual_placement_at"] is None

    # The refused spot cascaded nowhere: the track is still empty and has never
    # seen switching activity.
    untouched = fx.probe_facility(api, world["facility_id"])
    assert untouched["occupied_spot_count"] == 0
    assert untouched["last_switch_at"] is None


# ===========================================================================
# instance: void_on_a_voided_cycle_is_rejected
# ===========================================================================
def test_voided_is_terminal_and_the_second_void_frees_nothing(api):
    """The same endpoint that succeeded once refuses the replay, and the count holds at 0.

    PRD 3.7: "Only a cycle whose `movement_status` is `ORDERED` or `RELEASED` may
    be voided - anything in flight between those two is refused with
    `ERR_INVALID_MOVEMENT_STATE` - and a cycle whose charge line sits on an
    invoice that is already `CLOSED` may not be voided at all, which is
    `ERR_INVOICE_INVALID_STATE`."

    Design: Corner/state_machines/void_on_a_voided_cycle_is_rejected
    """
    world = fx.reference_world(api)
    cycle = fx.make_cycle(api, world)
    car_id = cycle["rail_car_id"]

    voided = fx.void_cycle(api, cycle["id"])
    assert voided["movement_status"] == MOVEMENT_VOIDED
    assert fx.get_car(api, car_id)["active_cycle_count"] == 0

    second = api.void_cycle(
        cycle["id"], f.void_payload(void_reason=SECOND_VOID_REASON), ADMIN
    )
    validate_error(second, ERR_INVALID_MOVEMENT_STATE)
    assert second.status_code == 409
    assert_error_meta_is_minimal(second)

    after = fx.get_cycle(api, cycle["id"])
    assert after["movement_status"] == MOVEMENT_VOIDED
    assert after["version"] == voided["version"]

    # PRD 3.7: "nothing cascades except the rail car's `active_cycle_count`,
    # which is re-derived to free the car" - re-derived, so it lands on 0 and
    # never on -1.
    freed = fx.get_car(api, car_id)
    assert freed["active_cycle_count"] == 0
    assert freed["active_cycle_count"] >= 0
    # An ORDERED cycle never had a charge line for the void to unwind.
    assert fx.charges_of_cycle(api, cycle["id"]) == []


# ===========================================================================
# instance: publish_twice_on_the_same_tariff_rule_set_returns_tariff_invalid_state
# ===========================================================================
def test_publish_is_not_idempotent_on_an_already_published_rule_set(api):
    """The replay is a 409, not a silent no-op that would sweep the siblings twice.

    PRD 3.1: "Publication moves it `DRAFT -> PUBLISHED` and increments its
    `version` by 1; publication of a rule set that is not `DRAFT` is refused with
    `ERR_TARIFF_INVALID_STATE`."

    Design: Corner/state_machines/publish_twice_on_the_same_tariff_rule_set_returns_tariff_invalid_state
    """
    fx.set_clock(api, COLD_START_CLOCK)
    published = fx.make_published_tariff(api)
    assert published["status"] == TARIFF_STATUS_PUBLISHED
    assert published["challenge_count"] == 0

    replay = api.publish_tariff_rule_set(published["id"], OFFICER)
    validate_error(replay, ERR_TARIFF_INVALID_STATE)
    assert replay.status_code == 409
    assert_error_meta_is_minimal(replay)

    after = fx.get_tariff(api, published["id"])
    assert_subset_equal(
        after,
        {
            "status": TARIFF_STATUS_PUBLISHED,
            "version": published["version"],
            "challenge_count": 0,
        },
    )
    # The refused publish did not re-run the supersede sweep, so the rates the
    # incumbent was published with are still the rates it carries.
    assert after["tier1_rate_cents_railroad"] == DEFAULT_TIER1_RATE_RAILROAD


# ===========================================================================
# instance: rail_yard_constructive_placement_creates_a_storage_charge_not_a_demurrage_charge
# ===========================================================================
def test_the_same_transition_at_a_yard_bills_storage_on_the_facility_clock(api):
    """One endpoint, two cascades: the yard mints STORAGE and lets the car out early.

    PRD 3.2: "and a car at a `RAIL_YARD` or an `INTERMODAL_TERMINAL` produces a
    `STORAGE` line regardless of who owns it."

    Design: Corner/state_machines/rail_yard_constructive_placement_creates_a_storage_charge_not_a_demurrage_charge
    """
    world = fx.reference_world(
        api, facility_overrides={"kind": FACILITY_KIND_RAIL_YARD}
    )
    yard = world["facility"]
    assert_subset_equal(
        yard,
        {
            "kind": FACILITY_KIND_RAIL_YARD,
            "storage_clock_mode": STORAGE_CLOCK_CALENDAR,
            "storage_free_hours": DEFAULT_STORAGE_FREE_HOURS,
            "storage_daily_rate_cents": DEFAULT_STORAGE_DAILY_RATE_CENTS,
            "operates_weekends": False,
        },
    )

    cycle = fx.make_cycle(api, world)
    fx.place_constructively(
        api, cycle["id"], CYCLE_A_CONSTRUCTIVE_AT, REASON_YARD_ARRIVAL
    )
    provisional = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        provisional,
        {
            "charge_kind": CHARGE_KIND_STORAGE,
            "status": CHARGE_PROVISIONAL,
            "chargeable_days": 0,
            "gross_amount_cents": 0,
        },
    )
    assert provisional["charge_kind"] != CHARGE_KIND_DEMURRAGE

    fx.send_notice(api, cycle["id"], YARD_NOTICE_AT, CHANNEL_EDI)
    # PRD 3.5: "From `CONSTRUCTIVELY_PLACED -> RELEASED` is permitted **only**
    # when the facility's `kind` is `RAIL_YARD` or `INTERMODAL_TERMINAL`".
    fx.release_cycle(api, cycle["id"], YARD_RELEASE_AT, world["customer_id"])

    released = fx.get_cycle(api, cycle["id"])
    assert_subset_equal(
        released,
        {
            "movement_status": MOVEMENT_RELEASED,
            "actual_placement_at": None,
            "clock_basis": CLOCK_BASIS_CONSTRUCTIVE,
        },
    )
    assert_instant_eq(released["released_at"], YARD_RELEASE_AT, "released_at")

    # PRD 3.5: "Under `CALENDAR_DAY_MIDNIGHT`, first find the first chargeable
    # date by taking the calendar date of `constructive_placement_at` and
    # advancing it by `storage_free_hours` divided by 24 calendar days - two days
    # at the default of 48 free hours. The storage day count is then the number of
    # calendar dates from that first chargeable date through the date of
    # `released_at` inclusive, counting a date only when the facility's
    # `operates_weekends` is true or the date is a Monday through Friday."
    first_chargeable = add_calendar_days(
        CYCLE_A_CONSTRUCTIVE_AT, DEFAULT_STORAGE_FREE_HOURS // 24
    )
    counted = [
        date
        for date in calendar_dates_between(first_chargeable, YARD_RELEASE_AT)
        if is_business_date(date)
    ]
    assert len(counted) == YARD_STORAGE_DAYS

    final = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        final,
        {
            "status": CHARGE_FINAL,
            "charge_kind": CHARGE_KIND_STORAGE,
            "computation_basis": BASIS_STORAGE_CALENDAR,
            "chargeable_days": YARD_STORAGE_DAYS,
            "billable_days": YARD_STORAGE_DAYS,
            "gross_amount_cents": YARD_STORAGE_GROSS_CENTS,
            "credit_applied_cents": 0,
            "net_amount_cents": YARD_STORAGE_GROSS_CENTS,
        },
    )
    assert_charge_money_invariant(final)
    assert (
        final["gross_amount_cents"]
        == YARD_STORAGE_DAYS * DEFAULT_STORAGE_DAILY_RATE_CENTS
    )


# ===========================================================================
# instance: invoice_close_settles_every_attached_cycle_billing_status
# ===========================================================================
def test_close_settles_two_cycles_and_leaves_both_charges_final(api):
    """The settlement lands on the cycles' billing axis; the charges do not move.

    PRD 3.7: "Closing cascades: every attached cycle's `billing_status` moves to
    `SETTLED`, whether it was sitting at `INVOICED` or at `ADJUSTED`, and every
    dispute on the invoice whose status is `DECIDED` moves to `CLOSED`, after which
    the consignee's `dispute_posture` is re-derived and falls back to `CLEAR` once
    no dispute of theirs is open any more."

    Design: Corner/state_machines/invoice_close_settles_every_attached_cycle_billing_status
    """
    world = fx.reference_world(api)
    cycle_a, cycle_b, invoice = fx.two_line_invoice(
        api, world, issue_clock=ISSUE_CLOCK_MID_AUGUST
    )
    assert invoice["status"] == INVOICE_ISSUED
    for cycle in (cycle_a, cycle_b):
        assert fx.get_cycle(api, cycle["id"])["billing_status"] == BILLING_INVOICED

    closed = fx.close_invoice(api, invoice["id"])
    assert_subset_equal(
        closed,
        {
            "status": INVOICE_CLOSED,
            "attached_charge_count": 2,
            "total_gross_cents": TWO_LINE_GROSS_TOTAL,
            "total_credit_cents": 0,
            "total_net_cents": TWO_LINE_GROSS_TOTAL,
        },
    )
    assert_invoice_money_invariant(closed)
    assert closed["version"] == invoice["version"] + 1

    for cycle in (cycle_a, cycle_b):
        settled = fx.get_cycle(api, cycle["id"])
        assert_subset_equal(
            settled,
            {
                "billing_status": BILLING_SETTLED,
                "movement_status": MOVEMENT_RELEASED,
            },
        )

    listed = api.list_charges(ADMIN, {"invoice_id": invoice["id"], "limit": 10, "offset": 0})
    rows = get_success_data(listed)
    assert_pagination_meta(
        listed.json()["meta"], limit=10, offset=0, total_count=2, has_more=False
    )
    # DemurrageCharge has no SETTLED state: the lines stay FINAL for ever.
    assert [row["status"] for row in rows] == [CHARGE_FINAL, CHARGE_FINAL]
    assert sorted(row["gross_amount_cents"] for row in rows) == sorted(
        TWO_LINE_GROSSES
    )


# ===========================================================================
# instance: denied_decision_re_derives_the_invoice_back_to_issued
# ===========================================================================
def test_a_denied_decision_walks_the_invoice_back_to_plain_issued(api):
    """Zero credit closes the loop exactly where it started, and not at ADJUSTED.

    PRD 3.7: "A dispute denied on a line that carries no credit walks the invoice
    all the way back from `PARTIALLY_DISPUTED` to `ISSUED`, because nothing else is
    true of it any more."

    Design: Corner/state_machines/denied_decision_re_derives_the_invoice_back_to_issued
    """
    world = fx.reference_world(api)
    cycle = fx.released_cycle_a(api, world)
    invoice = fx.issued_invoice(api, world, issue_clock=ISSUE_CLOCK_MID_AUGUST)
    dispute = fx.under_review_dispute(
        api,
        invoice,
        world["customer_id"],
        CYCLE_A_GROSS_CENTS,
        ADJUDICATOR_DENYING,
        submit_clock=SUBMIT_CLOCK_MID_AUGUST,
        scope=SCOPE_WHOLE_INVOICE,
    )

    before = fx.get_invoice(api, invoice["id"])
    assert_subset_equal(
        before, {"status": INVOICE_PARTIALLY_DISPUTED, "dispute_count": 1}
    )
    assert fx.charge_of_cycle(api, cycle["id"])["status"] == CHARGE_DISPUTED
    assert (
        fx.get_customer(api, world["customer_id"])["dispute_posture"]
        == DISPUTE_POSTURE_UNDER_REVIEW
    )

    decided = fx.decide(api, dispute["id"], ADJUDICATOR_DENYING, DECISION_DENIED, 0)
    assert_subset_equal(
        decided,
        {
            "status": DISPUTE_DECIDED,
            "decision": DECISION_DENIED,
            "allowance_pct": 0,
            "allowed_credit_cents": 0,
            "first_level_adjudicator_id": ADJUDICATOR_DENYING,
        },
    )

    charge = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        charge,
        {
            "status": CHARGE_FINAL,
            "credit_applied_cents": 0,
            "net_amount_cents": CYCLE_A_GROSS_CENTS,
            "gross_amount_cents": CYCLE_A_GROSS_CENTS,
        },
    )
    assert charge["status"] != CHARGE_ADJUSTED

    after = fx.get_invoice(api, invoice["id"])
    assert_subset_equal(
        after,
        {
            "status": INVOICE_ISSUED,
            "total_gross_cents": CYCLE_A_GROSS_CENTS,
            "total_credit_cents": 0,
            "total_net_cents": CYCLE_A_GROSS_CENTS,
            "dispute_count": 1,
        },
    )
    assert after["status"] != INVOICE_PARTIALLY_DISPUTED
    assert after["status"] != INVOICE_ADJUSTED
    assert_invoice_money_invariant(after)
    assert fx.get_cycle(api, cycle["id"])["billing_status"] == BILLING_INVOICED

    # PRD 3.1: "`dispute_posture` is evaluated in a strict order: it is
    # `ESCALATED` if any of this consignee's disputes is in status `ESCALATED`;
    # otherwise it is `UNDER_REVIEW` if any of them is in status `SUBMITTED`,
    # `UNDER_REVIEW`, `INFO_REQUESTED` or `APPEALED`; otherwise it is `CLEAR`."
    consignee = fx.get_customer(api, world["customer_id"])
    assert_subset_equal(
        consignee,
        {"dispute_posture": DISPUTE_POSTURE_CLEAR, "credit_balance_cents": 0},
    )


# ===========================================================================
# instance: publishing_a_sibling_tariff_code_supersedes_the_incumbent
# ===========================================================================
def test_the_supersede_sweep_is_keyed_on_tariff_code_and_nothing_else(api):
    """Revision B demotes revision A of 6004 and leaves 7100 entirely alone.

    PRD 3.1: "Publication has one cascade: any sibling rule set sharing the same
    `tariff_code` and currently `PUBLISHED` moves `PUBLISHED -> SUPERSEDED` and its
    own `version` increments by 1."

    Design: Corner/state_machines/publishing_a_sibling_tariff_code_supersedes_the_incumbent
    """
    fx.set_clock(api, COLD_START_CLOCK)
    customer = fx.make_customer(api)
    facility = fx.make_industry_track(api)
    incumbent = fx.make_published_tariff(api, tariff_code=TARIFF_CODE_INCUMBENT)
    unrelated = fx.make_published_tariff(api, tariff_code=TARIFF_CODE_UNRELATED)
    revision = fx.make_draft_tariff(api, tariff_code=TARIFF_CODE_INCUMBENT)
    assert revision["status"] == TARIFF_STATUS_DRAFT

    promoted = get_success_data(api.publish_tariff_rule_set(revision["id"], OFFICER))
    assert promoted["status"] == TARIFF_STATUS_PUBLISHED
    assert promoted["tariff_code"] == TARIFF_CODE_INCUMBENT

    demoted = fx.get_tariff(api, incumbent["id"])
    assert_subset_equal(
        demoted,
        {
            "status": TARIFF_STATUS_SUPERSEDED,
            "version": incumbent["version"] + 1,
            # PRD 3.1: "placement cycles already pinned to it keep using it and
            # are never re-rated" - the demotion did not rewrite its rates.
            "tier1_rate_cents_railroad": DEFAULT_TIER1_RATE_RAILROAD,
        },
    )

    untouched = fx.get_tariff(api, unrelated["id"])
    assert_subset_equal(
        untouched,
        {
            "status": TARIFF_STATUS_PUBLISHED,
            "version": unrelated["version"],
            "tariff_code": TARIFF_CODE_UNRELATED,
        },
    )

    # The demoted rule set can no longer back a *new* cycle; the promoted one can.
    car = fx.make_rail_car(api)
    stale = api.create_placement_cycle(
        f.placement_cycle_payload(
            customer["id"], car["id"], facility["id"], incumbent["id"], car["version"]
        ),
        AGENT,
    )
    validate_error(stale, ERR_TARIFF_NOT_PUBLISHED)
    assert stale.status_code == 422
    assert fx.get_car(api, car["id"])["version"] == car["version"]

    accepted = get_success_data(
        api.create_placement_cycle(
            f.placement_cycle_payload(
                customer["id"], car["id"], facility["id"], revision["id"], car["version"]
            ),
            AGENT,
        ),
        201,
    )
    assert accepted["tariff_rule_set_id"] == revision["id"]
    assert accepted["movement_status"] == MOVEMENT_ORDERED


# ===========================================================================
# instance: analyze_twice_on_a_bunching_claim_returns_claim_invalid_state
# ===========================================================================
def test_analyze_disposes_of_the_claim_and_refuses_the_second_run(api):
    """ANALYZED is transient, the fork is terminal, and the exemption cannot be handed out twice.

    PRD 3.6: "A `DemurrageAdjudicator` triggers it against a claim that must
    currently be `SUBMITTED`, or the request is refused with
    `ERR_CLAIM_INVALID_STATE`."

    Design: Corner/state_machines/analyze_twice_on_a_bunching_claim_returns_claim_invalid_state
    """
    world = fx.reference_world(
        api, customer_overrides={"normal_daily_placement_capacity": CLUSTER_CAPACITY}
    )
    customer_id = world["customer_id"]
    cycle = fx.released_cycle_a(api, world)
    charge_before = fx.charge_of_cycle(api, cycle["id"])
    assert charge_before["gross_amount_cents"] == CYCLE_A_GROSS_CENTS

    claim = fx.file_bunching_claim(
        api, customer_id, CLUSTER_WINDOW_START, CLUSTER_WINDOW_END
    )
    assert claim["status"] == CLAIM_SUBMITTED

    # PRD 3.6: "When `exempt_days_granted` is zero the claim is `DENIED`, and no
    # charge line is touched at all: `exempted_cycle_ids` stays empty and every
    # `gross_amount_cents` in the cluster is left exactly where it was."
    analyzed = fx.analyze_claim(api, claim["id"], ADJUDICATOR_ANALYZING)
    assert_subset_equal(
        analyzed,
        {
            "status": CLAIM_DENIED,
            "baseline_per_day": CLUSTER_CAPACITY,
            "delivered_car_count": 1,
            "exempt_days_granted": 0,
            "exempted_cycle_ids": [],
            "cluster_chargeable_days": CYCLE_A_CHARGEABLE_DAYS,
            "version": claim["version"] + 1,
        },
    )

    replay = api.analyze_bunching_claim(
        claim["id"], make_adjudicator_headers(ADJUDICATOR_ANALYZING)
    )
    validate_error(replay, ERR_CLAIM_INVALID_STATE)
    assert replay.status_code == 409
    assert_error_meta_is_minimal(replay)

    after = fx.get_claim(api, customer_id, claim["id"])
    assert_subset_equal(
        after,
        {
            "status": CLAIM_DENIED,
            "version": analyzed["version"],
            "exempt_days_granted": 0,
        },
    )
    # Neither analyze touched the money on the cluster's single line.
    assert fx.charge_of_cycle(api, cycle["id"]) == charge_before
    assert charge_before["bunching_exempt_days"] == 0


# ===========================================================================
# instance: reconcile_twice_on_an_average_agreement_returns_agreement_invalid_state
# ===========================================================================
def test_reconciled_is_terminal_even_though_the_fork_condition_still_holds(api):
    """net_days is still zero, so the fork would still choose RECONCILED - and 409 wins.

    PRD 3.7: "A `BillingAdmin` reconciles an agreement that must currently be
    `OPEN`, or the request is refused with `ERR_AGREEMENT_INVALID_STATE`."

    Design: Corner/state_machines/reconcile_twice_on_an_average_agreement_returns_agreement_invalid_state
    """
    world = fx.reference_world(api)
    customer_id = world["customer_id"]
    agreement = fx.open_agreement(api, customer_id)
    assert_subset_equal(
        agreement,
        {
            "status": AGREEMENT_OPEN,
            "credit_days_earned": 0,
            "debit_days_incurred": 0,
            "net_days": 0,
            "agreement_credit_cents": 0,
        },
    )

    # PRD 3.7: "When `net_days` is zero or positive the agreement moves
    # `OPEN -> RECONCILED` and its `agreement_credit_cents` is frozen at the value
    # landed at issue time - the credit is honoured."
    reconciled = fx.reconcile(api, agreement["id"])
    assert_subset_equal(
        reconciled,
        {
            "status": AGREEMENT_RECONCILED,
            "net_days": 0,
            "agreement_credit_cents": 0,
            "version": agreement["version"] + 1,
        },
    )

    replay = api.reconcile_average_agreement(agreement["id"], ADMIN)
    validate_error(replay, ERR_AGREEMENT_INVALID_STATE)
    assert replay.status_code == 409
    assert_error_meta_is_minimal(replay)

    after = fx.get_agreement(api, customer_id, agreement["id"])
    assert_subset_equal(
        after,
        {
            "status": AGREEMENT_RECONCILED,
            "agreement_credit_cents": 0,
            "version": reconciled["version"],
        },
    )
    assert fx.get_customer(api, customer_id)["credit_balance_cents"] == 0


# ===========================================================================
# instance: third_refusal_on_one_cycle_returns_refusal_limit
# ===========================================================================
def test_the_third_refusal_fails_from_a_state_that_permits_the_edge(api):
    """The cycle is legally ACTUALLY_PLACED; the counter on the cycle is what refuses.

    PRD 3.4: "Refusal is capped: the cycle's `refusal_count` must currently be
    less than 2, so the first and second refusals succeed and the third is rejected
    with `ERR_REFUSAL_LIMIT`."

    Design: Corner/state_machines/third_refusal_on_one_cycle_returns_refusal_limit
    """
    world = fx.reference_world(api)
    customer_id = world["customer_id"]
    cycle = fx.noticed_cycle(api, world)
    assert world["facility"]["switch_buffer_minutes"] == 0

    for attempt, spot_at in enumerate((SPOT_ONE_AT, SPOT_TWO_AT), start=1):
        fx.place_actually(api, cycle["id"], spot_at)
        spotted = fx.get_cycle(api, cycle["id"])
        assert spotted["movement_status"] == MOVEMENT_ACTUALLY_PLACED
        assert fx.probe_facility(api, world["facility_id"])["occupied_spot_count"] == 1

        # PRD 3.4: "On success the cycle's `actual_placement_at` is set back to
        # null, `refusal_count` increments by 1, the facility's
        # `occupied_spot_count` is re-derived downward - freeing the spot for
        # another car - the clock-basis election is re-run and reverts
        # `clock_basis` to `CONSTRUCTIVE` with `clock_start_at` back at the
        # constructive instant".
        fx.refuse_cycle(api, cycle["id"], customer_id, refusal_reason=REFUSAL_REASON)
        rewound = fx.get_cycle(api, cycle["id"])
        assert_subset_equal(
            rewound,
            {
                "movement_status": MOVEMENT_CONSTRUCTIVELY_PLACED,
                "actual_placement_at": None,
                "refusal_count": attempt,
                "clock_basis": CLOCK_BASIS_CONSTRUCTIVE,
            },
        )
        assert_instant_eq(
            rewound["clock_start_at"], CYCLE_A_CONSTRUCTIVE_START, "clock_start_at"
        )
        assert_instant_eq(
            rewound["free_time_expires_at"],
            CYCLE_A_CONSTRUCTIVE_EXPIRY,
            "free_time_expires_at",
        )
        assert fx.probe_facility(api, world["facility_id"])["occupied_spot_count"] == 0

    fx.place_actually(api, cycle["id"], SPOT_THREE_AT)
    before = fx.get_cycle(api, cycle["id"])
    assert_subset_equal(
        before, {"movement_status": MOVEMENT_ACTUALLY_PLACED, "refusal_count": 2}
    )

    third = api.refuse(
        cycle["id"],
        f.refuse_payload(refusal_reason=REFUSAL_REASON),
        make_customer_headers(customer_id),
    )
    validate_error(third, ERR_REFUSAL_LIMIT)
    assert third.status_code == 409
    assert error_id_of(third) != ERR_INVALID_MOVEMENT_STATE
    assert_error_meta_is_minimal(third)

    after = fx.get_cycle(api, cycle["id"])
    assert after == before
    assert_subset_equal(
        after, {"movement_status": MOVEMENT_ACTUALLY_PLACED, "refusal_count": 2}
    )
    assert_instant_eq(
        after["actual_placement_at"], SPOT_THREE_AT, "actual_placement_at"
    )
    # The spot the third refusal would have freed is still occupied.
    assert fx.probe_facility(api, world["facility_id"])["occupied_spot_count"] == 1


def _two_line_invoice_with_cycle_a_disputed(api):
    """The 60100-cent two-line invoice with a SINGLE_CHARGE dispute on line A."""
    world = fx.reference_world(api)
    cycle_a, cycle_b, invoice = fx.two_line_invoice(
        api, world, issue_clock=ISSUE_CLOCK_MID_AUGUST
    )
    charge_a = fx.charge_of_cycle(api, cycle_a["id"])
    dispute = fx.submitted_dispute(
        api,
        invoice,
        world["customer_id"],
        CYCLE_A_GROSS_CENTS,
        submit_clock=SUBMIT_CLOCK_MID_AUGUST,
        scope=SCOPE_SINGLE_CHARGE,
        demurrage_charge_id=charge_a["id"],
    )
    assert dispute["status"] == DISPUTE_SUBMITTED
    return world, cycle_a, cycle_b, invoice, charge_a, dispute


# ===========================================================================
# instance: close_an_invoice_while_a_charge_is_disputed_returns_invoice_invalid_state
# ===========================================================================
def test_one_disputed_line_blocks_the_close_for_the_whole_invoice(api):
    """The refusal is all-or-nothing: the undisputed cycle is not settled either.

    PRD 3.7: "A `DRAFT` invoice cannot be closed, a `PARTIALLY_DISPUTED` invoice
    cannot be closed, and an invoice carrying any `DISPUTED` charge line cannot be
    closed; all three refusals are `ERR_INVOICE_INVALID_STATE`."

    Design: Corner/state_machines/close_an_invoice_while_a_charge_is_disputed_returns_invoice_invalid_state
    """
    _world, cycle_a, cycle_b, invoice, _charge_a, _dispute = (
        _two_line_invoice_with_cycle_a_disputed(api)
    )
    before = fx.get_invoice(api, invoice["id"])
    assert before["status"] == INVOICE_PARTIALLY_DISPUTED

    refused = api.close_invoice(invoice["id"], ADMIN)
    validate_error(refused, ERR_INVOICE_INVALID_STATE)
    assert refused.status_code == 409
    assert_error_meta_is_minimal(refused)

    after = fx.get_invoice(api, invoice["id"])
    assert after == before
    assert_subset_equal(
        after,
        {
            "status": INVOICE_PARTIALLY_DISPUTED,
            "total_gross_cents": TWO_LINE_GROSS_TOTAL,
        },
    )

    assert fx.get_cycle(api, cycle_a["id"])["billing_status"] == BILLING_DISPUTED
    assert fx.get_cycle(api, cycle_b["id"])["billing_status"] == BILLING_INVOICED
    for cycle in (cycle_a, cycle_b):
        assert fx.get_cycle(api, cycle["id"])["billing_status"] != BILLING_SETTLED
    # Cycle B's own line never entered the dispute and is still FINAL.
    assert fx.charge_of_cycle(api, cycle_b["id"])["status"] == CHARGE_FINAL


# ===========================================================================
# instance: second_dispute_submit_on_an_already_disputed_charge_returns_charge_invalid_state
# ===========================================================================
def test_the_second_submit_is_refused_by_the_target_charge_not_by_the_invoice(api):
    """A perfectly legal DRAFT dispute, refused two entities away at the charge.

    PRD 3.8: "Every target charge must be `FINAL`, or `ERR_CHARGE_INVALID_STATE`."

    Design: Corner/state_machines/second_dispute_submit_on_an_already_disputed_charge_returns_charge_invalid_state
    """
    world = fx.reference_world(api)
    customer_id = world["customer_id"]
    cycle = fx.released_cycle_a(api, world)
    invoice = fx.issued_invoice(api, world, issue_clock=ISSUE_CLOCK_MID_AUGUST)
    charge = fx.charge_of_cycle(api, cycle["id"])

    fx.submitted_dispute(
        api,
        invoice,
        customer_id,
        CYCLE_A_GROSS_CENTS,
        submit_clock=SUBMIT_CLOCK_MID_AUGUST,
        scope=SCOPE_SINGLE_CHARGE,
        demurrage_charge_id=charge["id"],
    )
    assert fx.charge_of_cycle(api, cycle["id"])["status"] == CHARGE_DISPUTED

    # PRD 3.8: "Creation increments the invoice's `version` by 1 and re-derives
    # its `dispute_count`, but **no charge changes status yet**".
    second = fx.evidenced_dispute(
        api,
        invoice,
        customer_id,
        CYCLE_A_GROSS_CENTS,
        scope=SCOPE_SINGLE_CHARGE,
        demurrage_charge_id=charge["id"],
    )
    assert second["status"] == DISPUTE_DRAFT
    invoice_before = fx.get_invoice(api, invoice["id"])
    assert_subset_equal(
        invoice_before,
        {"status": INVOICE_PARTIALLY_DISPUTED, "dispute_count": 2},
    )
    charge_before = fx.charge_of_cycle(api, cycle["id"])

    refused = api.submit_dispute(second["id"], make_customer_headers(customer_id))
    validate_error(refused, ERR_CHARGE_INVALID_STATE)
    assert refused.status_code == 409
    assert_error_meta_is_minimal(refused)

    # The refused submit is a complete no-op on all three entities.
    still_draft = fx.get_dispute(api, second["id"])
    assert_subset_equal(
        still_draft,
        {
            "status": DISPUTE_DRAFT,
            "version": second["version"],
            "submitted_at": None,
            "adjudication_due_at": None,
            "target_charge_count": 0,
            "decision": DECISION_PENDING,
        },
    )
    assert fx.get_invoice(api, invoice["id"]) == invoice_before
    assert fx.charge_of_cycle(api, cycle["id"]) == charge_before
    assert charge_before["credit_applied_cents"] == 0
    assert fx.get_cycle(api, cycle["id"])["billing_status"] == BILLING_DISPUTED


def _issued_single_line_invoice(api):
    """Cycle A released, invoiced and issued at 2026-08-15, with its charge."""
    world = fx.reference_world(api)
    cycle = fx.released_cycle_a(api, world)
    invoice = fx.issued_invoice(api, world, issue_clock=ISSUE_CLOCK_MID_AUGUST)
    assert invoice["status"] == INVOICE_ISSUED
    assert invoice["total_gross_cents"] == CYCLE_A_GROSS_CENTS
    return world, cycle, invoice


# ===========================================================================
# instance: third_information_request_returns_info_request_limit
# ===========================================================================
def test_the_third_information_request_fails_from_a_valid_under_review_state(api):
    """The loop is walked twice legally, and the counter - not the status - stops the third.

    PRD 3.8: "The `info_request_count` must be below 2, so the third request is
    refused with `ERR_INFO_REQUEST_LIMIT`, and a successful request increments the
    counter by 1."

    Design: Corner/state_machines/third_information_request_returns_info_request_limit
    """
    world, cycle, invoice = _issued_single_line_invoice(api)
    customer_id = world["customer_id"]
    dispute = fx.under_review_dispute(
        api,
        invoice,
        customer_id,
        CYCLE_A_GROSS_CENTS,
        ADJUDICATOR_REQUESTING,
        submit_clock=SUBMIT_CLOCK_MID_AUGUST,
        scope=SCOPE_WHOLE_INVOICE,
    )
    assert_subset_equal(
        dispute,
        {
            "status": DISPUTE_UNDER_REVIEW,
            "info_request_count": 0,
            "evidence_weight": EVIDENCE_WEIGHT_AFTER_ONE,
        },
    )
    assert_instant_eq(
        dispute["adjudication_due_at"],
        DUE_AT_BASE_20_MULT_1_00_WEIGHT_3,
        "adjudication_due_at",
    )

    # PRD 3.8: "The request **replaces** `adjudication_due_at` outright with the
    # last millisecond of the 10th business date strictly after the current
    # logical-clock date, rather than extending the deadline it found there".
    first = fx.request_more_info(
        api, dispute["id"], ADJUDICATOR_REQUESTING, clock=INFO_REQUEST_ONE_CLOCK
    )
    assert_subset_equal(
        first, {"status": DISPUTE_INFO_REQUESTED, "info_request_count": 1}
    )
    assert_end_of_day(first["adjudication_due_at"], "adjudication_due_at")
    assert_instant_eq(
        first["adjudication_due_at"],
        end_of(business_dates_strictly_after(INFO_REQUEST_ONE_CLOCK, 10)),
        "adjudication_due_at",
    )
    assert_instant_eq(
        first["adjudication_due_at"], DUE_AT_AFTER_INFO_REQUEST, "adjudication_due_at"
    )

    # PRD 3.8: "At least one exhibit must have been filed *after* the information
    # request - not merely one exhibit overall - or the resubmission is refused
    # with `ERR_DISPUTE_NO_EVIDENCE`."
    fx.add_evidence(
        api, dispute["id"], customer_id, evidence_type=EVIDENCE_GATE_LOG
    )
    resubmitted = fx.resubmit(
        api, dispute["id"], customer_id, clock=RESUBMIT_ONE_CLOCK
    )
    assert_subset_equal(
        resubmitted,
        {
            "status": DISPUTE_SUBMITTED,
            "evidence_weight": EVIDENCE_WEIGHT_AFTER_TWO,
            "info_request_count": 1,
        },
    )
    # PRD 3.8: "it leaves `adjudication_due_at` exactly where the information
    # request put it".
    assert_instant_eq(
        resubmitted["adjudication_due_at"],
        DUE_AT_AFTER_INFO_REQUEST,
        "adjudication_due_at",
    )
    fx.begin_review(api, dispute["id"], ADJUDICATOR_REQUESTING)

    second = fx.request_more_info(
        api, dispute["id"], ADJUDICATOR_REQUESTING, clock=INFO_REQUEST_TWO_CLOCK
    )
    assert_subset_equal(
        second, {"status": DISPUTE_INFO_REQUESTED, "info_request_count": 2}
    )
    assert_instant_eq(
        second["adjudication_due_at"],
        DUE_AT_AFTER_SECOND_INFO_REQUEST,
        "adjudication_due_at",
    )
    fx.add_evidence(
        api, dispute["id"], customer_id, evidence_type=EVIDENCE_WEIGHT_CERTIFICATE
    )
    fx.resubmit(api, dispute["id"], customer_id, clock=RESUBMIT_TWO_CLOCK)
    before = fx.begin_review(api, dispute["id"], ADJUDICATOR_REQUESTING)
    assert_subset_equal(
        before,
        {
            "status": DISPUTE_UNDER_REVIEW,
            "info_request_count": 2,
            "evidence_weight": EVIDENCE_WEIGHT_AFTER_THREE,
        },
    )

    third = api.request_info(
        dispute["id"],
        f.request_info_payload(),
        make_adjudicator_headers(ADJUDICATOR_REQUESTING),
    )
    validate_error(third, ERR_INFO_REQUEST_LIMIT)
    assert third.status_code == 409
    assert error_id_of(third) != ERR_DISPUTE_INVALID_STATE
    assert_error_meta_is_minimal(third)

    after = fx.get_dispute(api, dispute["id"])
    assert after == before
    assert_subset_equal(
        after,
        {
            "status": DISPUTE_UNDER_REVIEW,
            "info_request_count": 2,
            "evidence_weight": EVIDENCE_WEIGHT_AFTER_THREE,
        },
    )
    assert after["status"] != DISPUTE_INFO_REQUESTED
    # The refused request pushed the deadline nowhere and touched no money.
    assert_instant_eq(
        after["adjudication_due_at"],
        DUE_AT_AFTER_SECOND_INFO_REQUEST,
        "adjudication_due_at",
    )
    assert fx.charge_of_cycle(api, cycle["id"])["status"] == CHARGE_DISPUTED
    assert fx.get_invoice(api, invoice["id"])["status"] == INVOICE_PARTIALLY_DISPUTED


# ===========================================================================
# instance: second_appeal_after_the_appeal_round_returns_appeal_limit
# ===========================================================================
def test_the_second_appeal_is_refused_by_the_round_counter_alone(api):
    """Round two ends DECIDED, so only round_number < 2 can stop the next appeal.

    PRD 3.8: "The `round_number` must be below 2, so a second appeal is refused
    with `ERR_APPEAL_LIMIT`."

    Design: Corner/state_machines/second_appeal_after_the_appeal_round_returns_appeal_limit
    """
    world, cycle, invoice = _issued_single_line_invoice(api)
    customer_id = world["customer_id"]
    dispute = fx.under_review_dispute(
        api,
        invoice,
        customer_id,
        CLAIM_CEILING_R17,
        ADJUDICATOR_ROUND_ONE,
        submit_clock=SUBMIT_CLOCK_MID_AUGUST,
        scope=SCOPE_WHOLE_INVOICE,
    )
    round_one = fx.decide(
        api,
        dispute["id"],
        ADJUDICATOR_ROUND_ONE,
        DECISION_PARTIALLY_ALLOWED,
        ROUND_ONE_ALLOWANCE_PCT,
    )
    assert_subset_equal(
        round_one,
        {
            "status": DISPUTE_DECIDED,
            "round_number": 1,
            "decision": DECISION_PARTIALLY_ALLOWED,
            "allowed_credit_cents": ROUND_ONE_CREDIT_CENTS,
            "first_level_adjudicator_id": ADJUDICATOR_ROUND_ONE,
            "appeal_adjudicator_id": None,
        },
    )
    credited = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        credited,
        {
            "status": CHARGE_ADJUSTED,
            "credit_applied_cents": ROUND_ONE_CREDIT_CENTS,
            "net_amount_cents": CYCLE_A_GROSS_CENTS - ROUND_ONE_CREDIT_CENTS,
        },
    )
    assert_charge_money_invariant(credited)
    adjusted = fx.get_invoice(api, invoice["id"])
    assert_subset_equal(
        adjusted,
        {
            "status": INVOICE_ADJUSTED,
            "total_gross_cents": CYCLE_A_GROSS_CENTS,
            "total_credit_cents": ROUND_ONE_CREDIT_CENTS,
            "total_net_cents": CYCLE_A_GROSS_CENTS - ROUND_ONE_CREDIT_CENTS,
        },
    )

    # PRD 3.8: "every target charge returns to `DISPUTED` with its
    # `credit_applied_cents` restored to the pre-decision value it held".
    appealed = fx.appealed_dispute(api, dispute["id"], customer_id)
    assert_subset_equal(
        appealed,
        {
            "status": DISPUTE_APPEALED,
            "round_number": 2,
            "decision": DECISION_PENDING,
            "allowance_pct": None,
            "allowed_credit_cents": 0,
        },
    )
    assert_instant_eq(
        appealed["adjudication_due_at"], DUE_AT_APPEAL_ROUND, "adjudication_due_at"
    )
    reversed_charge = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        reversed_charge,
        {
            "status": CHARGE_DISPUTED,
            "credit_applied_cents": 0,
            "net_amount_cents": CYCLE_A_GROSS_CENTS,
        },
    )
    assert_subset_equal(
        fx.get_invoice(api, invoice["id"]),
        {"status": INVOICE_PARTIALLY_DISPUTED, "total_credit_cents": 0},
    )

    # PRD 3.8: "Crucially, `first_level_adjudicator_id` is left untouched by the
    # round change, so the bar survives it".
    taken_up = fx.begin_review(api, dispute["id"], ADJUDICATOR_ROUND_TWO)
    assert_subset_equal(
        taken_up,
        {
            "status": DISPUTE_UNDER_REVIEW,
            "first_level_adjudicator_id": ADJUDICATOR_ROUND_ONE,
            "appeal_adjudicator_id": ADJUDICATOR_ROUND_TWO,
        },
    )

    before = fx.decide(api, dispute["id"], ADJUDICATOR_ROUND_TWO, DECISION_DENIED, 0)
    assert_subset_equal(
        before,
        {
            "status": DISPUTE_DECIDED,
            "round_number": 2,
            "decision": DECISION_DENIED,
            "allowed_credit_cents": 0,
        },
    )
    assert fx.charge_of_cycle(api, cycle["id"])["status"] == CHARGE_FINAL
    assert fx.get_invoice(api, invoice["id"])["status"] == INVOICE_ISSUED

    refused = api.appeal_dispute(
        dispute["id"], f.appeal_payload(), make_customer_headers(customer_id)
    )
    validate_error(refused, ERR_APPEAL_LIMIT)
    assert refused.status_code == 409
    assert_error_meta_is_minimal(refused)

    after = fx.get_dispute(api, dispute["id"])
    assert after == before
    assert_subset_equal(
        after, {"status": DISPUTE_DECIDED, "round_number": 2, "decision": DECISION_DENIED}
    )
    assert fx.get_customer(api, customer_id)["credit_balance_cents"] == 0


def _twice_decided_on_an_issued_invoice(api, adjudicator_a, adjudicator_b):
    """The only dispute shape PRD 3.9 will escalate: DECIDED at round 2."""
    world, cycle, invoice = _issued_single_line_invoice(api)
    dispute = fx.twice_decided_dispute(
        api,
        invoice,
        world["customer_id"],
        CYCLE_A_GROSS_CENTS,
        adjudicator_a,
        adjudicator_b,
        round1_decision=DECISION_DENIED,
        round1_allowance_pct=0,
        round2_decision=DECISION_DENIED,
        round2_allowance_pct=0,
        submit_clock=SUBMIT_CLOCK_MID_AUGUST,
        scope=SCOPE_WHOLE_INVOICE,
    )
    assert_subset_equal(dispute, {"status": DISPUTE_DECIDED, "round_number": 2})
    return world, cycle, invoice, dispute


# ===========================================================================
# instance: decide_a_regulatory_complaint_before_the_railroad_answers_returns_complaint_invalid_state
# ===========================================================================
def test_the_regulator_cannot_rule_before_the_railroad_has_been_heard(api):
    """RAILROAD_ANSWERED is a mandatory intermediate state, not a courtesy.

    PRD 3.9: "Answering anything that is not `FILED` is refused with
    `ERR_COMPLAINT_INVALID_STATE`, as is deciding anything that is not
    `RAILROAD_ANSWERED`: the regulator cannot rule before the railroad has been
    heard."

    Design: Corner/state_machines/decide_a_regulatory_complaint_before_the_railroad_answers_returns_complaint_invalid_state
    """
    world, _cycle, _invoice, dispute = _twice_decided_on_an_issued_invoice(
        api, ADJUDICATOR_BILLING_A, ADJUDICATOR_BILLING_B
    )
    customer_id = world["customer_id"]
    complaint = fx.filed_complaint(
        api,
        dispute["id"],
        customer_id,
        complaint_type=COMPLAINT_TYPE_BILLING_PRACTICE,
        filing_clock=COMPLAINT_FILING_CLOCK,
    )
    assert_subset_equal(
        complaint,
        {
            "status": COMPLAINT_FILED,
            "answer_narrative": None,
            "ordered_credit_cents": 0,
            "tariff_rule_set_id": None,
        },
    )
    assert_instant_eq(complaint["filed_at"], COMPLAINT_FILING_CLOCK, "filed_at")
    assert_instant_eq(
        complaint["response_due_at"], COMPLAINT_RESPONSE_DUE_AT, "response_due_at"
    )
    assert re.match(DOCKET_NUMBER_PATTERN, complaint["docket_number"])
    assert fx.get_dispute(api, dispute["id"])["status"] == DISPUTE_ESCALATED

    refused = api.decide_regulatory_complaint(
        complaint["id"], f.complaint_decision_payload(COMPLAINT_DISMISSED), OFFICER
    )
    validate_error(refused, ERR_COMPLAINT_INVALID_STATE)
    assert refused.status_code == 409
    assert_error_meta_is_minimal(refused)

    after = get_success_data(
        api.get_regulatory_complaint(complaint["id"], OFFICER)
    )
    assert after == complaint
    assert_subset_equal(
        after,
        {
            "status": COMPLAINT_FILED,
            "answer_narrative": None,
            "ordered_credit_cents": 0,
            "version": complaint["version"],
        },
    )
    assert after["status"] != COMPLAINT_RAILROAD_ANSWERED

    # The refused decision left the two entities filing had already moved.
    assert fx.get_dispute(api, dispute["id"])["status"] == DISPUTE_ESCALATED
    assert (
        fx.get_customer(api, customer_id)["dispute_posture"]
        == DISPUTE_POSTURE_ESCALATED
    )
    # A BILLING_PRACTICE complaint cites no tariff, so none was challenged.
    assert_subset_equal(
        fx.get_tariff(api, world["tariff_id"]),
        {"status": TARIFF_STATUS_PUBLISHED, "challenge_count": 0},
    )


# ===========================================================================
# instance: tariff_rule_set_loops_challenged_back_to_published_after_a_dismissal
# ===========================================================================
def test_a_dismissal_returns_the_challenged_tariff_and_keeps_the_scar(api):
    """The cyclic edge: PUBLISHED to CHALLENGED and back, with challenge_count preserved.

    PRD 3.9: "On a `RULE_REASONABLENESS` complaint the cited rule set moves
    `CHALLENGED -> WITHDRAWN` when the outcome is `DECIDED_FOR_CUSTOMER`, and
    `CHALLENGED -> PUBLISHED` on either of the other two outcomes, with its
    `version` incremented either way."

    Design: Corner/state_machines/tariff_rule_set_loops_challenged_back_to_published_after_a_dismissal
    """
    world, _cycle, _invoice, dispute = _twice_decided_on_an_issued_invoice(
        api, ADJUDICATOR_RULE_A, ADJUDICATOR_RULE_B
    )
    customer_id = world["customer_id"]
    tariff_id = world["tariff_id"]
    published = fx.get_tariff(api, tariff_id)
    assert_subset_equal(
        published, {"status": TARIFF_STATUS_PUBLISHED, "challenge_count": 0}
    )

    complaint = fx.filed_complaint(
        api,
        dispute["id"],
        customer_id,
        complaint_type=COMPLAINT_TYPE_RULE_REASONABLENESS,
        filing_clock=COMPLAINT_FILING_CLOCK,
        tariff_rule_set_id=tariff_id,
        docket_narrative=RULE_NARRATIVE,
    )
    assert_subset_equal(
        complaint,
        {
            "status": COMPLAINT_FILED,
            "complaint_type": COMPLAINT_TYPE_RULE_REASONABLENESS,
            "tariff_rule_set_id": tariff_id,
            "docket_number": FIRST_DOCKET_NUMBER,
        },
    )
    assert_server_minted_id(complaint["id"])
    assert_instant_eq(complaint["filed_at"], COMPLAINT_FILING_CLOCK, "filed_at")

    # PRD 3.9 declares only the status move and the challenge_count increment on
    # the filing cascade; per PRD 2.9 "where 3 is silent, no increment occurs on
    # that secondary resource", so the tariff's own version is not asserted here.
    challenged = fx.get_tariff(api, tariff_id)
    assert_subset_equal(
        challenged,
        {
            "status": TARIFF_STATUS_CHALLENGED,
            "challenge_count": 1,
        },
    )
    assert fx.get_dispute(api, dispute["id"])["status"] == DISPUTE_ESCALATED

    # PRD 3.9: "A challenged tariff **stays in force**: as 3.2 states, a
    # `CHALLENGED` rule set may still back a new placement cycle, because a
    # pending challenge is an allegation and not a suspension."
    spare_car = fx.make_rail_car(api)
    mid_loop = get_success_data(
        api.create_placement_cycle(
            f.placement_cycle_payload(
                customer_id,
                spare_car["id"],
                world["facility_id"],
                tariff_id,
                spare_car["version"],
                waybill_number=WAYBILL_MID_LOOP,
            ),
            AGENT,
        ),
        201,
    )
    assert_subset_equal(
        mid_loop,
        {
            "movement_status": MOVEMENT_ORDERED,
            "billing_status": BILLING_UNBILLED,
            "tariff_rule_set_id": tariff_id,
        },
    )

    answered = fx.answered_complaint(api, complaint["id"])
    assert answered["status"] == COMPLAINT_RAILROAD_ANSWERED
    assert answered["answer_narrative"] is not None

    dismissed = get_success_data(
        api.decide_regulatory_complaint(
            complaint["id"], f.complaint_decision_payload(COMPLAINT_DISMISSED), OFFICER
        )
    )
    assert_subset_equal(
        dismissed, {"status": COMPLAINT_DISMISSED, "ordered_credit_cents": 0}
    )

    # PRD 3.9: "it preserves `challenge_count` rather than resetting it: the
    # tariff carries the scar of every challenge it has survived."
    restored = fx.get_tariff(api, tariff_id)
    assert_subset_equal(
        restored,
        {
            "status": TARIFF_STATUS_PUBLISHED,
            "challenge_count": 1,
            "version": challenged["version"] + 1,
        },
    )
    assert restored["challenge_count"] != 0
    # The regulator's outcome does not reopen the railroad's own adjudication.
    assert fx.get_dispute(api, dispute["id"])["status"] == DISPUTE_ESCALATED
    assert (
        fx.get_customer(api, customer_id)["dispute_posture"]
        == DISPUTE_POSTURE_ESCALATED
    )
