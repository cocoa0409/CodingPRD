"""Invoice lifecycle: single charge per turnaround, billability, the OPEN-only
window for accrual and voiding, stale-view protection and auditor separation."""
from test_helpers import (
    ApiErrorId,
    add_agent_occupation,
    add_billing_line,
    add_gse_occupation,
    cancel_turn,
    complete_turn,
    create_billing_period,
    create_certified_agent,
    create_flight_bank,
    create_gse_unit,
    create_open_station,
    create_turn,
    finalize_period,
    get_billing_line,
    get_billing_period,
    get_flight_bank,
    get_turn,
    make_billing_controller_headers,
    make_contract_auditor_headers,
    publish_and_approve_staffing,
    start_turn,
    validate_error,
    validate_success,
)


def _setup_open_period_with_one_scheduled_turn():
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    period = create_billing_period(station["id"], period_code="2026-04")
    return station, bank, turn, period


# ---------------------------------------------------------------------------
# Queue B: validations / second_billing_line_for_same_turn_returns_duplicate_billing_line
# ---------------------------------------------------------------------------

def test_a_turn_can_carry_only_one_live_charge(api):
    """PRD §3.9: "And a turnaround may carry at most one live charge anywhere
    in the system — if any line in any period already references that
    turnaround with `status` `PROVISIONAL` or `FINAL`, the new line is refused
    with `ERR_DUPLICATE_BILLING_LINE`."

    Design: Corner/validations/second_billing_line_for_same_turn_returns_duplicate_billing_line
    """
    _station, _bank, turn, period = _setup_open_period_with_one_scheduled_turn()
    add_billing_line(period["id"], turn["id"])
    refreshed = get_billing_period(period["id"])

    resp = api.create_billing_line(
        {"billing_period_id": period["id"], "turn_id": turn["id"],
         "expected_billing_period_version": refreshed["version"]},
        make_billing_controller_headers())
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BILLING_LINE, 409)

    period = get_billing_period(period["id"])
    assert period["line_count"] == 1
    assert period["accrued_cents"] == 18000
    assert get_turn(turn["id"])["billed"] is True


# ---------------------------------------------------------------------------
# Queue B: validations / billing_line_for_a_cancelled_turn_returns_turn_not_billable
# ---------------------------------------------------------------------------

def test_a_cancelled_turn_cannot_be_charged(api):
    """PRD §3.9: "The turnaround must be billable: one whose `status` is
    `CANCELLED` or `DISRUPTED` is refused with `ERR_TURN_NOT_BILLABLE` and HTTP
    422."
    PRD §3.3: "The bank's `required_headcount` is the sum, over every
    turnaround in the bank whose `status` is `SCHEDULED`, `RESOURCED`,
    `IN_PROGRESS` or `COMPLETED`, of the agent requirement of that turnaround's
    service level; turnarounds in `CANCELLED` or `DISRUPTED` are excluded from
    the sum entirely."

    Design: Corner/validations/billing_line_for_a_cancelled_turn_returns_turn_not_billable
    """
    _station, bank, turn, period = _setup_open_period_with_one_scheduled_turn()
    assert cancel_turn(turn["id"], reason="SLOT_WITHDRAWN")["status"] == "CANCELLED"

    resp = api.create_billing_line(
        {"billing_period_id": period["id"], "turn_id": turn["id"],
         "expected_billing_period_version": period["version"]},
        make_billing_controller_headers())
    validate_error(resp, ApiErrorId.ERR_TURN_NOT_BILLABLE, 422)

    period = get_billing_period(period["id"])
    assert period["line_count"] == 0
    assert period["accrued_cents"] == 0
    assert get_flight_bank(bank["id"])["required_headcount"] == 0


# ---------------------------------------------------------------------------
# Queue B: validations / accruing_into_a_finalized_period_returns_period_not_open
# ---------------------------------------------------------------------------

def test_a_pending_period_refuses_both_accrual_and_void(api):
    """PRD §3.9: "The period must be `OPEN`, and a line written against a
    period in `PENDING_APPROVAL` or `APPROVED` is refused with
    `ERR_PERIOD_NOT_OPEN`."
    PRD §3.9: "Voiding, like accrual, is only admissible while the owning
    period is `OPEN`; a void attempted against a period in `PENDING_APPROVAL`
    or `APPROVED` is refused with `ERR_PERIOD_NOT_OPEN`."

    Design: Corner/validations/accruing_into_a_finalized_period_returns_period_not_open
    """
    station = create_open_station(otp_tolerance_minutes=15)
    bank = create_flight_bank(station["id"], planned_headcount=2)
    billed_turn = create_turn(station["id"], bank["id"], flight_number="LX701")
    spare_turn = create_turn(station["id"], bank["id"], flight_number="LX702",
                             scheduled_in="2026-04-10T09:00:00Z",
                             scheduled_out="2026-04-10T09:20:00Z")
    agent = create_certified_agent(station["id"])
    gse = create_gse_unit(station["id"])
    publish_and_approve_staffing(bank["id"])
    add_agent_occupation(billed_turn["id"], agent["id"])
    add_gse_occupation(billed_turn["id"], gse_unit_id=gse["id"])
    start_turn(billed_turn["id"], actual_in="2026-04-10T06:00:00Z")
    complete_turn(billed_turn["id"], actual_out="2026-04-10T06:20:00Z",
                  delay_code="NONE")

    period = create_billing_period(station["id"], period_code="2026-04")
    line = add_billing_line(period["id"], billed_turn["id"])
    pending = finalize_period(period["id"], user_id="bc-01")
    assert pending["status"] == "PENDING_APPROVAL"

    refused_accrual = api.create_billing_line(
        {"billing_period_id": period["id"], "turn_id": spare_turn["id"],
         "expected_billing_period_version": pending["version"]},
        make_billing_controller_headers())
    validate_error(refused_accrual, ApiErrorId.ERR_PERIOD_NOT_OPEN, 409)

    refused_void = api.void_billing_line(
        line["id"], {"reason": "TOO_LATE"}, make_billing_controller_headers())
    validate_error(refused_void, ApiErrorId.ERR_PERIOD_NOT_OPEN, 409)

    period = get_billing_period(period["id"])
    assert period["line_count"] == 1
    line = get_billing_line(line["id"])
    assert line["status"] == "FINAL"
    assert line["gross_amount_cents"] == 18000
    assert get_turn(spare_turn["id"])["billed"] is False


# ---------------------------------------------------------------------------
# Queue B: cross_cutting_complexity_layers /
#          stale_expected_billing_period_version_returns_412
# ---------------------------------------------------------------------------

def test_stale_expected_billing_period_version_is_refused_then_retried(api):
    """PRD §2.8: "Creating a billing line requires the non-optional field
    `expected_billing_period_version`, carrying the client's last observed
    `version` of the target `BillingPeriod`. A mismatch with the period's live
    `version` is rejected with `ERR_STALE_PERIOD_VERSION` and HTTP 412."
    PRD §2.8: "Accruing further lines into an open period is likewise
    legitimate and repeatable, but every accrual moves `gross_total_cents` and
    can move `rebate_tier`, so a writer with a stale view of the period would
    be accruing against a superseded rebate basis."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_billing_period_version_returns_412
    """
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=2)
    first_turn = create_turn(station["id"], bank["id"], flight_number="LX901")
    second_turn = create_turn(station["id"], bank["id"], flight_number="LX902",
                              scheduled_in="2026-04-10T08:00:00Z",
                              scheduled_out="2026-04-10T08:20:00Z")
    period = create_billing_period(station["id"], period_code="2026-04")
    original_version = period["version"]

    first_line = validate_success(api.create_billing_line(
        {"billing_period_id": period["id"], "turn_id": first_turn["id"],
         "expected_billing_period_version": original_version},
        make_billing_controller_headers()), 201)

    stale = api.create_billing_line(
        {"billing_period_id": period["id"], "turn_id": second_turn["id"],
         "expected_billing_period_version": original_version},
        make_billing_controller_headers())
    validate_error(stale, ApiErrorId.ERR_STALE_PERIOD_VERSION, 412)

    period = get_billing_period(period["id"])
    assert period["accrued_cents"] == 18000
    assert period["line_count"] == 1
    assert period["version"] == original_version + 1

    second_line = validate_success(api.create_billing_line(
        {"billing_period_id": period["id"], "turn_id": second_turn["id"],
         "expected_billing_period_version": period["version"]},
        make_billing_controller_headers()), 201)

    assert get_billing_line(first_line["id"])["status"] == "PROVISIONAL"
    assert get_billing_line(second_line["id"])["status"] == "PROVISIONAL"
    period = get_billing_period(period["id"])
    assert period["accrued_cents"] == 36000
    assert period["line_count"] == 2
    assert get_turn(second_turn["id"])["billed"] is True


# ---------------------------------------------------------------------------
# Queue B: rbac / period_finalizer_cannot_approve_the_same_period
# ---------------------------------------------------------------------------

def test_the_user_who_finalized_the_period_may_not_approve_it(api):
    """PRD §2.1: "Independently of role, three operations enforce **segregation
    of duties** on the acting `X-User-ID` value rather than on the role name:
    the user who reported an incident may not be the user who takes it into
    investigation; the user who issued findings on an incident may not be the
    user who closes it; and the user who finalized a billing period may not be
    the user who approves it."
    PRD §3.9: "Approving with `APPROVE` moves it `PENDING_APPROVAL →
    APPROVED`, stamps `approved_by_user_id`, and makes the period read-only;
    `APPROVED` is terminal. The auditor's `X-User-ID` must differ from
    `finalized_by_user_id`."

    Design: Corner/rbac/period_finalizer_cannot_approve_the_same_period
    """
    station = create_open_station(otp_tolerance_minutes=15)
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    agent = create_certified_agent(station["id"])
    gse = create_gse_unit(station["id"])
    publish_and_approve_staffing(bank["id"])
    add_agent_occupation(turn["id"], agent["id"])
    add_gse_occupation(turn["id"], gse_unit_id=gse["id"])
    start_turn(turn["id"], actual_in="2026-04-10T06:00:00Z")
    complete_turn(turn["id"], actual_out="2026-04-10T06:20:00Z",
                  delay_code="NONE")
    period = create_billing_period(station["id"], period_code="2026-04")
    line = add_billing_line(period["id"], turn["id"])
    finalized = finalize_period(period["id"], user_id="ops-7")
    assert finalized["finalized_by_user_id"] == "ops-7"

    self_approval = api.billing_period_transition(
        period["id"], {"action": "APPROVE"}, make_contract_auditor_headers("ops-7"))
    validate_error(self_approval, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    approved = validate_success(api.billing_period_transition(
        period["id"], {"action": "APPROVE"},
        make_contract_auditor_headers("ca-01")))
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "ca-01"
    assert get_billing_line(line["id"])["status"] == "FINAL"
    assert get_billing_period(period["id"])["accrued_cents"] == 18000
