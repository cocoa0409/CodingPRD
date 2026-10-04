"""Loan return: grade write-back, status re-route, restoration auto-creation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    confirm_loan,
    create_artist,
    create_loan,
    get_instrument,
    list_instruments,
    list_restorations_for_instrument,
    return_loan,
    return_loan_payload,
    setup_bank_instrument,
    setup_on_tour_loan,
    validate_error,
)

LIAISON = TEST_USERS["artist_liaison_headers"]


def test_return_grade_d_moves_instrument_to_restoration(api):
    """PRD section 3.6: "First, the instrument's `condition_grade` is overwritten
    with the observed grade. Second, its status is re-routed: ... an observed `C` or
    `D` sends an instrument currently `ON_LOAN` into `RESTORATION`."
    PRD section 3.6: "the loan moves to the terminal `RETURNED`".

    Design: Difficulty/transitive_cascade/loan_return_grade_d_restoration_cascade
    """
    ctx = setup_on_tour_loan("MODEL_B", "2028-06-01T00:00:00Z", "2028-06-22T00:00:00Z")
    returned = return_loan(ctx["loan"]["id"], "D")
    assert returned["status"] == "RETURNED"
    instrument = get_instrument(ctx["instrument"]["id"])
    assert instrument["condition_grade"] == "D"
    assert instrument["status"] == "RESTORATION"


def test_return_grade_d_autocreates_restoration_case(api):
    """PRD section 3.6: "that entry into `RESTORATION` auto-creates a restoration
    case with `origin` `LOAN_RETURN`, status `QUOTED`, zeroed quote values, the
    returning loan's technician as `lead_craftsman_id`".

    Design: Difficulty/transitive_cascade/loan_return_grade_d_restoration_cascade
    """
    ctx = setup_on_tour_loan("MODEL_B", "2028-06-01T00:00:00Z", "2028-06-22T00:00:00Z")
    return_loan(ctx["loan"]["id"], "D")
    cases = list_restorations_for_instrument(ctx["instrument"]["id"])
    assert len(cases) == 1
    case = cases[0]
    assert case["origin"] == "LOAN_RETURN"
    assert case["status"] == "QUOTED"
    assert case["authentic_parts_value_cents"] == 0
    assert case["total_parts_value_cents"] == 0
    assert case["lead_craftsman_id"] == ctx["technician"]["id"]


def test_confirm_decrements_bank_residency(api):
    """PRD section 3.6: "A successful confirm binds `instrument_id` and
    `technician_id` onto the loan, fixes `fee_cents`, moves a `BANK` instrument to
    `ON_LOAN`".

    Design: Difficulty/compensating_invariant/bank_residency_confirm_return_conserved
    """
    ctx = setup_bank_instrument("MODEL_B")
    artist = create_artist("Art A", "STANDARD", 2)
    loan = create_loan(artist, "MODEL_B", "2029-07-01T00:00:00Z", "2029-07-22T00:00:00Z")
    assert len(list_instruments({"status": "BANK"})) == 1
    confirm_loan(loan["id"], ctx["craftsmen"]["VOICING"]["id"], ctx["instrument"]["id"])
    assert len(list_instruments({"status": "BANK"})) == 0
    assert get_instrument(ctx["instrument"]["id"])["status"] == "ON_LOAN"


def test_return_restores_bank_residency(api):
    """PRD section 3.6: "an observed `A` or `B` sends an instrument currently
    `ON_LOAN` back to `BANK` only when no other `ON_TOUR` loan remains bound to it".

    Design: Difficulty/compensating_invariant/bank_residency_confirm_return_conserved
    """
    ctx = setup_bank_instrument("MODEL_B")
    artist = create_artist("Art A", "STANDARD", 2)
    loan = create_loan(artist, "MODEL_B", "2029-07-01T00:00:00Z", "2029-07-22T00:00:00Z")
    confirm_loan(loan["id"], ctx["craftsmen"]["VOICING"]["id"], ctx["instrument"]["id"])
    assert len(list_instruments({"status": "BANK"})) == 0
    return_loan(loan["id"], "A")
    assert len(list_instruments({"status": "BANK"})) == 1
    instrument = get_instrument(ctx["instrument"]["id"])
    assert instrument["status"] == "BANK"
    assert instrument["condition_grade"] == "A"


def test_loan_returned_terminal_lockdown(api):
    """PRD section 3.6: "The liaison records a `condition_grade_observed`, the loan
    moves to the terminal `RETURNED`, and a three-link cascade runs on the
    instrument." A second return finds no legal from-state and is rejected with
    `ERR_INVALID_STATE` (state validity, section 2.8 tier 4); the instrument is not
    re-graded.

    Design: Corner/state_machines/loan_returned_terminal_lockdown
    """
    ctx = setup_on_tour_loan("MODEL_B", "2028-06-01T00:00:00Z", "2028-06-22T00:00:00Z")
    returned = return_loan(ctx["loan"]["id"], "B")
    assert returned["status"] == "RETURNED"
    instrument = get_instrument(ctx["instrument"]["id"])
    assert instrument["condition_grade"] == "B"
    assert instrument["status"] == "BANK"
    resp = api.return_concert_loan(ctx["loan"]["id"], return_loan_payload("D"), LIAISON)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    instrument = get_instrument(ctx["instrument"]["id"])
    assert instrument["condition_grade"] == "B"
    assert list_restorations_for_instrument(ctx["instrument"]["id"]) == []


def test_authenticity_null_when_no_parts_replaced(api):
    """PRD section 3.7: "While `total_parts_value_cents` is zero, `authenticity_pct`
    is null — no parts replaced is treated as authentic."
    The LOAN_RETURN cascade case opens with zeroed quote values, so it sits in
    QUOTED with a null percentage rather than diverting to AUTHENTICITY_HOLD.

    Design: Corner/calculations/authenticity_null_when_no_parts_replaced
    """
    ctx = setup_on_tour_loan("MODEL_B", "2028-06-01T00:00:00Z", "2028-06-22T00:00:00Z")
    return_loan(ctx["loan"]["id"], "C")
    instrument = get_instrument(ctx["instrument"]["id"])
    assert instrument["status"] == "RESTORATION"
    assert instrument["condition_grade"] == "C"
    cases = list_restorations_for_instrument(ctx["instrument"]["id"])
    assert len(cases) == 1
    case = cases[0]
    assert case["status"] == "QUOTED"
    assert case["authenticity_pct"] is None
    assert case["lead_craftsman_id"] == ctx["technician"]["id"]
