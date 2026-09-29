"""Forward act and compensating act, twice over: AUMs of allotment capacity returned by an
instruction void, and cents of permittee debt returned by a bill void."""
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_aums,
    assert_ledger_conserved,
    make_officer_headers,
)
from test_helpers import factories as f
from test_helpers.fixtures import (
    add_use_record,
    allotment_with_pasture,
    bill_trespass_incident,
    create_permittee,
    create_trespass_incident,
    get_allotment,
    get_bill,
    get_permit,
    get_permittee,
    get_trespass_incident,
    issue_aoi,
    issued_aoi_setup,
    list_bills,
    void_aoi,
    void_bill,
)


def _ledger_setup():
    """An ISSUED 2026 instruction of 300 AUMs on a 1200-AUM allotment, one 103.33-AUM leg
    scheduled, and an unpaid 54,100-cent preliminary bill."""
    setup = issued_aoi_setup(authorized_aums=300, total_permitted_aums=1200,
                             pasture_aum_capacity=300, carrying_capacity_aums=400,
                             requested_aums=300, planned_head_count=100,
                             planned_entry_date="2026-04-01", planned_exit_date="2026-05-02",
                             allotment_overrides={"acres": 24000})
    assert_aums(setup["use_record"]["planned_aums"], 103.33)
    assert setup["preliminary_bill"]["total_amount_cents"] == 54100
    return setup


def test_voiding_an_issued_instruction_returns_the_capacity_ledger_to_exactly_its_pre_issue_figures():
    """Issuance took 300 AUMs (allocated 0 -> 300, open 1200 -> 900) and the void gives back
    exactly 300: allocated returns to 0, open to 1200, the invariant holds on both sides of the
    compensation, the preliminary bill is voided and the permittee's debt returns to 0 with no
    residue anywhere.

    PRD 2.9: "The compensation invariant: if an allotment's `allocated_aums` is A before an
    operating instruction is issued, then after issuance it is A plus that instruction's
    `billable_aums`, and after that same instruction is voided it is A again — exactly A, with no
    drift — while `open_aums` returns to `effective_capacity_aums` less A."
    PRD 3.5: "Voiding an instruction that had been issued does more: `aoi_status` becomes
    `VOIDED`, every bill of that instruction in `bill_status` `ISSUED` or `DELINQUENT` moves to
    `VOIDED`, the allotment's `allocated_aums` decreases by exactly that instruction's
    `billable_aums` while `open_aums` increases by the same amount — restoring the compensation
    invariant of §2.9 to the cent-exact AUM figure it held before issuance — `scheduled_aums` is
    refreshed on every pasture the instruction's records name, and the permittee's
    `outstanding_balance_cents` and the permit's `account_status` are re-derived."
    PRD 2.9: "The AUM invariant: an allotment's `open_aums` plus its `allocated_aums` always
    equals its `effective_capacity_aums`."

    Design: Difficulty/compensating_invariant/aum_conservation_on_aoi_issue_then_void
    """
    setup = _ledger_setup()
    before = get_allotment(setup["allotment"]["id"])
    assert before["allocated_aums"] == 300
    assert before["open_aums"] == 900
    assert before["effective_capacity_aums"] == 1200
    assert_ledger_conserved(before)
    assert get_permittee(setup["permittee"]["id"])["outstanding_balance_cents"] == 54100

    voided = void_aoi(setup["aoi"]["id"])
    assert voided["aoi_status"] == "VOIDED"

    after = get_allotment(setup["allotment"]["id"])
    assert after["allocated_aums"] == 0, "exactly the pre-issue value, with no residue"
    assert after["open_aums"] == 1200
    assert after["effective_capacity_aums"] == 1200
    assert_ledger_conserved(after)

    assert get_bill(setup["preliminary_bill"]["id"])["bill_status"] == "VOIDED"
    assert get_permittee(setup["permittee"]["id"])["outstanding_balance_cents"] == 0
    permit = get_permit(setup["permit"]["id"])
    assert permit["account_status"] == "CURRENT"
    assert permit["permit_status"] == "ISSUED", "voiding a year does not touch the authorization"


def test_the_void_frees_the_permit_year_slot_and_the_replacement_does_not_double_count():
    """The voided instruction releases its 2026 slot, so a replacement instruction for the same
    permit and the same year is accepted rather than refused as a duplicate, and once it is issued
    the ledger lands on the very same 300 / 900 figures instead of stacking to 600.

    PRD 2.6: "**One instruction per permit-year** — `ERR_DUPLICATE_AOI_FOR_YEAR`, HTTP 409, on
    operating-instruction creation. At most one instruction per permit and `grazing_year` may exist
    in an `aoi_status` other than `VOIDED`; voiding an instruction frees the slot so that a
    replacement may be created for the same year."
    PRD 2.9: "The second line is **allocation**: `allocated_aums` is the sum, over every annual
    operating instruction whose permit belongs to this allotment, whose `grazing_year` equals the
    allotment's `current_grazing_year`, and whose `aoi_status` is one of `ISSUED`, `USE_REPORTED`,
    `BILLED` or `CLOSED`, of that instruction's `authorized_aums` less its `nonuse_aums`."
    PRD 2.9: "Instructions in `DRAFT` or `VOIDED` contribute nothing, and instructions for any
    other grazing year contribute nothing; the window is exactly the allotment's
    `current_grazing_year`, inclusive of both ends of that calendar year."

    Design: Difficulty/compensating_invariant/aum_conservation_on_aoi_issue_then_void
    """
    setup = _ledger_setup()
    void_aoi(setup["aoi"]["id"])

    replacement = get_success_data(api_client.create_aoi(
        f.aoi_payload(setup["permit"]["id"], grazing_year=2026, authorized_aums=300,
                      season_start_date="2026-01-01", season_end_date="2026-12-31"),
        make_officer_headers()), 201)
    assert replacement["aoi_status"] == "DRAFT"
    assert replacement["id"] != setup["aoi"]["id"]

    add_use_record(replacement["id"], setup["pasture"]["id"], planned_head_count=100,
                   livestock_kind="CATTLE", planned_entry_date="2026-04-01",
                   planned_exit_date="2026-05-02")
    issued = issue_aoi(replacement["id"])
    assert issued["aoi_status"] == "ISSUED"
    assert issued["billable_aums"] == 300

    allotment = get_allotment(setup["allotment"]["id"])
    assert allotment["allocated_aums"] == 300, "the voided instruction is not counted again"
    assert allotment["open_aums"] == 900
    assert_ledger_conserved(allotment)

    live = [b for b in list_bills(aoi_id=replacement["id"]) if b["bill_status"] != "VOIDED"]
    assert len(live) == 1
    assert live[0]["total_amount_cents"] == 54100
    assert get_permittee(setup["permittee"]["id"])["outstanding_balance_cents"] == 54100


def _trespass_setup():
    """A permittee with no bills at all, and one DETECTED willful incident of 47 head of cattle
    over 11 unauthorized days."""
    land = allotment_with_pasture(total_permitted_aums=1200, pasture_aum_capacity=300,
                                  required_pasture_rotation_count=1, acres=24000)
    permittee = create_permittee()
    assert permittee["outstanding_balance_cents"] == 0
    assert permittee["billed_trespass_incident_count"] == 0
    incident = create_trespass_incident(
        land["allotment"]["id"], permittee["id"], detected_at="2026-07-15T14:30:00Z",
        head_count=47, livestock_kind="CATTLE", unauthorized_days=11, willfulness="WILLFUL")
    assert incident["incident_status"] == "DETECTED"
    assert_aums(incident["unauthorized_aums"], 17.23)
    assert incident["prior_billed_incident_count"] == 0
    return {"allotment": land["allotment"], "permittee": permittee, "incident": incident}


def _trespass_bill(incident_id):
    bills = [b for b in list_bills(trespass_incident_id=incident_id,
                                   bill_type="UNAUTHORIZED_USE")
             if b["bill_status"] != "VOIDED"]
    assert len(bills) == 1, "expected exactly one live trespass bill, got %d" % len(bills)
    return bills[0]


def test_voiding_the_trespass_bill_returns_the_debt_to_zero_and_re_arms_the_incident():
    """Billing took the permittee from 0 to 84,240 cents and the counter from 0 to 1; the void
    gives back exactly that, walks the incident BILLED -> DETECTED, recomputes the derived counter
    to 0, and leaves the detection-time snapshot untouched.

    PRD 3.11: "Voiding that bill instead cycles the incident `BILLED → DETECTED` and recomputes
    both the permittee's `outstanding_balance_cents` and its `billed_trespass_incident_count`,
    restoring the money-conservation invariant of §2.9 exactly; the incident is then billable
    again, and a re-bill recomputes the charge from the incident's stored inputs and its unchanged
    `prior_billed_incident_count` snapshot."
    PRD 2.9: "If the balance is B before a bill is issued, it is B plus that bill's
    `total_amount_cents` afterwards, and voiding that bill returns it to exactly B with no
    residue."
    PRD 3.2: "the trespass counter is itself derived: it is the number of trespass incidents
    attributed to this permittee whose `incident_status` is `BILLED` or `RESOLVED`."
    PRD 3.11: "The `prior_billed_incident_count` is **snapshotted at detection time and never
    recomputed**: it is the count of other incidents of the same `permittee_id` whose
    `incident_status` is `BILLED` or `RESOLVED` and whose `detected_at` is strictly earlier than
    this incident's `detected_at`."

    Design: Difficulty/compensating_invariant/cents_conservation_on_trespass_bill_void
    """
    setup = _trespass_setup()

    billed = bill_trespass_incident(setup["incident"]["id"])
    assert billed["incident_status"] == "BILLED"
    assert billed["billed_aums"] == 18, "17.23 unauthorized AUMs round up to a whole AUM"

    bill = _trespass_bill(setup["incident"]["id"])
    assert bill["base_amount_cents"] == 42120
    assert bill["penalty_amount_cents"] == 42120
    assert bill["total_amount_cents"] == 84240
    assert bill["admin_fee_cents"] == 0
    assert bill["fee_rate_cents_per_aum"] == 2340
    assert bill["bill_status"] == "ISSUED"

    charged = get_permittee(setup["permittee"]["id"])
    assert charged["outstanding_balance_cents"] == 84240
    assert charged["billed_trespass_incident_count"] == 1
    assert charged["permittee_status"] == "IN_GOOD_STANDING", "the bill is not yet overdue"

    void_bill(bill["id"], void_reason="Incident report withdrawn after ownership review.")

    assert get_bill(bill["id"])["bill_status"] == "VOIDED"
    restored = get_permittee(setup["permittee"]["id"])
    assert restored["outstanding_balance_cents"] == 0, "exactly the pre-bill value"
    assert restored["billed_trespass_incident_count"] == 0
    assert restored["permittee_status"] == "IN_GOOD_STANDING"

    incident = get_trespass_incident(setup["incident"]["id"])
    assert incident["incident_status"] == "DETECTED"
    assert incident["prior_billed_incident_count"] == 0
    assert_aums(incident["unauthorized_aums"], 17.23)


def test_re_billing_the_re_armed_incident_reproduces_the_charge_with_no_drift():
    """The compensation left nothing behind for the replay to pick up: the second bill is a new
    bill for exactly 84,240 cents — repeat factor still 1.0, so the penalty is still 42,120 — and
    the balance is 84,240, never 168,480.

    PRD 3.11: "Step five computes the repeat factor as 1.0 plus 0.25 for each prior billed
    incident recorded in `prior_billed_incident_count`, capped at 2.0 — so the factor climbs 1.0,
    1.25, 1.50, 1.75, 2.0 and then stops, a fifth and any later prior incident adding nothing."
    PRD 3.11: "Step six sets `penalty_amount_cents` to `base_amount_cents` multiplied by the
    willfulness multiplier less 1.0, multiplied by the repeat factor, rounded half-up to a whole
    cent."
    PRD 2.9: "A permittee's `outstanding_balance_cents` always equals the sum, over that
    permittee's bills whose `bill_status` is `ISSUED` or `DELINQUENT`, of each bill's
    `total_amount_cents` less its `amount_paid_cents`; bills in `PAID` or `VOIDED` contribute
    nothing, and an `ADJUSTMENT_CREDIT` bill contributes its negative total and so reduces the
    balance."

    Design: Difficulty/compensating_invariant/cents_conservation_on_trespass_bill_void
    """
    setup = _trespass_setup()
    bill_trespass_incident(setup["incident"]["id"])
    first = _trespass_bill(setup["incident"]["id"])
    void_bill(first["id"], void_reason="Incident report withdrawn after ownership review.")

    rebilled = bill_trespass_incident(setup["incident"]["id"])
    assert rebilled["incident_status"] == "BILLED"
    assert rebilled["billed_aums"] == 18
    assert rebilled["prior_billed_incident_count"] == 0, "the snapshot never moves"

    second = _trespass_bill(setup["incident"]["id"])
    assert second["id"] != first["id"]
    assert second["base_amount_cents"] == 42120
    assert second["penalty_amount_cents"] == 42120
    assert second["total_amount_cents"] == 84240
    assert second["bill_status"] == "ISSUED"

    permittee = get_permittee(setup["permittee"]["id"])
    assert permittee["outstanding_balance_cents"] == 84240
    assert permittee["billed_trespass_incident_count"] == 1


def test_the_voided_trespass_bill_can_never_be_paid():
    """A compensated bill is closed to money: a payment for its full 84,240 cents is refused with
    ERR_BILL_STATE_INVALID and the restored zero balance stands.

    PRD 3.6: "The target bill must be in `bill_status` `ISSUED` or `DELINQUENT`; paying one already
    `PAID` or `VOIDED` is `ERR_BILL_STATE_INVALID`."
    PRD 2.6: "This priority also covers the cross-entity state preconditions that name the
    subject's own parent chain: drafting an operating instruction requires the named permit to be
    `ISSUED`, so a permit in `PENDING_REVIEW`, `SUSPENDED`, `CANCELLED`, `EXPIRED` or
    `TRANSFERRED` yields `ERR_PERMIT_STATE_INVALID`; scheduling a use record requires the owning
    instruction to be in `DRAFT`; reporting actual use requires it to be in `ISSUED`; and paying a
    bill requires the bill to be in `ISSUED` or `DELINQUENT`."

    Design: Difficulty/compensating_invariant/cents_conservation_on_trespass_bill_void
    """
    setup = _trespass_setup()
    bill_trespass_incident(setup["incident"]["id"])
    bill = _trespass_bill(setup["incident"]["id"])
    void_bill(bill["id"], void_reason="Incident report withdrawn after ownership review.")

    validate_error(
        api_client.record_payment(bill["id"], f.payment_payload(84240), make_officer_headers()),
        ApiErrorId.ERR_BILL_STATE_INVALID, 409)

    unchanged = get_bill(bill["id"])
    assert unchanged["bill_status"] == "VOIDED"
    assert unchanged["amount_paid_cents"] == 0
    assert get_permittee(setup["permittee"]["id"])["outstanding_balance_cents"] == 0
    assert get_trespass_incident(setup["incident"]["id"])["incident_status"] == "DETECTED"
