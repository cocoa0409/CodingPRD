"""Restoration: authenticity hold cycle, completion evaluation order, uniqueness."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_restoration_case,
    complete_restoration_case,
    complete_restoration_payload,
    create_restoration_case,
    create_restoration_payload,
    get_instrument,
    get_restoration,
    list_restorations_for_instrument,
    make_master_craftsman_headers,
    resolve_authenticity,
    return_loan,
    setup_completed_instrument,
    setup_on_tour_loan,
    setup_rebuilt_case,
    validate_error,
)

WM = TEST_USERS["workshop_manager_headers"]
LIAISON = TEST_USERS["artist_liaison_headers"]


def test_restoration_authenticity_hold_cycle(api):
    """PRD section 3.7: "at case creation and at each authenticity resolution, a case
    with a positive total, an `authenticity_pct` below 70.0, and no accepted waiver
    moves itself from `QUOTED` into `AUTHENTICITY_HOLD`".
    PRD section 3.7: "the case returns to `QUOTED` only if the recomputed
    `authenticity_pct` is at least 70.0 or the waiver is accepted."
    30,000/50,000 = 60.0% holds at create; 40,000/50,000 = 80.0% resolves back.

    Design: Corner/state_machines/restoration_authenticity_hold_cycle
    """
    ctx = setup_completed_instrument("MODEL_O")
    lead = ctx["craftsmen"]["ACTION_REGULATION"]
    case = create_restoration_case(
        ctx["instrument"]["id"], lead["id"], "worn action stack", 30_000, 50_000, False
    )
    assert case["status"] == "AUTHENTICITY_HOLD"
    assert get_instrument(ctx["instrument"]["id"])["status"] == "RESTORATION"
    resolved = resolve_authenticity(case, lead, 40_000, 50_000)
    assert resolved["status"] == "QUOTED"
    assert resolved["authenticity_pct"] == 80.0


def test_authenticity_exactly_70_passes_strict(api):
    """PRD section 3.7: "rounded half up to one decimal place, so exactly 70.0 passes
    the 70.0 threshold and 69.9 fails."
    PRD section 3.7: "`certified_authentic` is decided ... true exactly when the
    final percentage reaches 70.0"; grade "`A` staying `A`"; status "`BANK` when it
    is certified authentic and its post-bump grade is `A` or `B`".

    Design: Corner/calculations/authenticity_exactly_70_passes_strict
    """
    ctx = setup_completed_instrument("MODEL_O")
    lead = ctx["craftsmen"]["ACTION_REGULATION"]
    case = create_restoration_case(
        ctx["instrument"]["id"], lead["id"], "action re-pinning", 35_000, 50_000, False
    )
    assert case["status"] == "QUOTED"  # 70.0 exactly passes: no hold at create
    case = advance_restoration_case(case, "DISASSEMBLED", lead)
    case = advance_restoration_case(case, "REBUILT", lead)
    done = complete_restoration_case(case, lead, 35_000, 50_000)
    assert done["status"] == "COMPLETED"
    assert done["authenticity_pct"] == 70.0
    instrument = get_instrument(ctx["instrument"]["id"])
    assert instrument["certified_authentic"] is True
    assert instrument["condition_grade"] == "A"
    assert instrument["status"] == "BANK"


def test_authenticity_below_threshold_complete_rejected(api):
    """PRD section 3.7: "When the final total is positive and the final authenticity
    falls below 70.0, completion requires `waiver_accepted` true, else it is
    rejected with `ERR_AUTHENTICITY_BELOW_THRESHOLD`."
    Quote 45,000/50,000 (90%) advances to REBUILT; final 30,000/50,000 = 60.0%.

    Design: Corner/errors/authenticity_below_threshold_complete_rejected
    """
    ctx = setup_rebuilt_case(45_000, 50_000, False)
    case = ctx["case"]
    assert case["status"] == "REBUILT"
    resp = api.complete_restoration(
        case["id"],
        complete_restoration_payload(30_000, 50_000),
        make_master_craftsman_headers(ctx["lead"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AUTHENTICITY_BELOW_THRESHOLD)
    assert get_restoration(case["id"])["status"] == "REBUILT"
    instrument = get_instrument(ctx["instrument"]["id"])
    assert instrument["status"] == "RESTORATION"
    assert instrument["certified_authentic"] is True


def test_second_open_restoration_rejected(api):
    """PRD section 3.7: "An instrument may carry only one open case at a time:
    opening a second case while any non-`COMPLETED` case exists for the same
    instrument is refused with `ERR_RESTORATION_ALREADY_OPEN`."

    Design: Corner/endpoints/second_open_restoration_rejected
    """
    ctx = setup_completed_instrument("MODEL_O")
    lead = ctx["craftsmen"]["ACTION_REGULATION"]
    first = create_restoration_case(
        ctx["instrument"]["id"], lead["id"], "case one", 0, 0
    )
    assert first["status"] == "QUOTED"
    resp = api.create_restoration(
        create_restoration_payload(ctx["instrument"]["id"], lead["id"], "case two", 0, 0),
        WM,
    )
    validate_error(resp, ApiErrorId.ERR_RESTORATION_ALREADY_OPEN)
    assert len(list_restorations_for_instrument(ctx["instrument"]["id"])) == 1


def test_bank_intake_grade_c_rejected(api):
    """PRD section 3.4: "Bank intake requires `certified_authentic` to be true and a
    `condition_grade` of `A` or `B`; anything else is rejected with
    `ERR_INSTRUMENT_NOT_BANK_ELIGIBLE`."
    PRD section 3.7: completion with a zero final total leaves `certified_authentic`
    "unchanged", bumps grade `D` to `C`, and lands the instrument in `SHOWROOM`
    because the post-bump grade is not `A` or `B`.

    Design: Corner/endpoints/bank_intake_grade_c_rejected
    """
    ctx = setup_on_tour_loan("MODEL_B", "2029-07-01T00:00:00Z", "2029-07-22T00:00:00Z")
    return_loan(ctx["loan"]["id"], "D")
    case = list_restorations_for_instrument(ctx["instrument"]["id"])[0]
    lead = ctx["technician"]
    case = advance_restoration_case(case, "DISASSEMBLED", lead)
    case = advance_restoration_case(case, "REBUILT", lead)
    done = complete_restoration_case(case, lead, 0, 0)
    assert done["status"] == "COMPLETED"
    instrument = get_instrument(ctx["instrument"]["id"])
    assert instrument["status"] == "SHOWROOM"
    assert instrument["condition_grade"] == "C"
    assert instrument["certified_authentic"] is True
    resp = api.bank_intake_instrument(ctx["instrument"]["id"], {}, LIAISON)
    validate_error(resp, ApiErrorId.ERR_INSTRUMENT_NOT_BANK_ELIGIBLE)
