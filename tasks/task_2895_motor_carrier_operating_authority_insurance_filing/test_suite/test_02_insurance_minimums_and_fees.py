"""The two combinatorial money formulas an application previews at draft time.

PRD S3.2 derives the three required insurance minimums from the application's
own input fields alone — a class branch, a nested hazardous-materials maximum
and a multi-jurisdiction uplift that applies only above a positive base — and
derives the filing fee from four line items each rounded to whole cents on its
own *before* the four are added together.  PRD S3.3 then freezes both at the
first submission and charges the fee to the carrier's ledger.

Each test enrolls its own carrier and opens its own applications, because the
harness empties the database before every test.
"""

from test_helpers import (
    FEE_BREAKDOWN_KEYS,
    MAX_LIMIT,
    REGISTRY_ADMIN,
    T_ENROLL,
    assert_authority_application,
    assert_fee_ledger_entry,
    assert_fee_ledger_identities,
    create_carrier,
    create_draft_application,
    expected_filing_fee,
    expected_required_minimums,
    make_carrier_headers,
    set_clock,
    submit_application,
    validate_paginated,
    validate_success,
)

# The 26-state motorcoach footprint: 26 distinct valid codes, one more than the
# 25-state uplift threshold of PRD S3.2.
TWENTY_SIX_STATES = [
    "TX", "OK", "NM", "AZ", "CA", "NV", "UT", "CO", "KS", "MO",
    "AR", "LA", "MS", "AL", "GA", "FL", "TN", "KY", "IL", "IN",
    "OH", "MI", "WI", "IA", "NE", "SD",
]
TWENTY_FIVE_STATES = TWENTY_SIX_STATES[:25]
TWENTY_FOUR_STATES = TWENTY_SIX_STATES[:24]

MOTORCOACH_CARRIER = {
    "legal_name": "Big Bend Motorcoach Inc",
    "domicile_state": "TX",
    "self_reported_vehicle_count": 18,
    "self_reported_driver_count": 30,
    "self_reported_oos_rate_pct": 6.0,
}
HOUSEHOLD_GOODS_CARRIER = {
    "legal_name": "Sooner Household Movers LLC",
    "domicile_state": "OK",
    "self_reported_vehicle_count": 12,
    "self_reported_driver_count": 15,
    "self_reported_oos_rate_pct": 3.0,
}
HOUSEHOLD_GOODS_STATES = ["OK", "TX", "AR"]


def _enrolled_carrier(api, profile):
    """S3.1: enroll one carrier with the logical clock at its startup default."""
    set_clock(api, T_ENROLL)
    return create_carrier(api, **profile)


def _passenger_application(api, carrier_id, *, seating_capacity, states):
    """S3.2: a DRAFT PASSENGER application, which previews both calculations."""
    return create_draft_application(
        api,
        carrier_id,
        application_kind="NEW",
        transportation_type="PASSENGER",
        requested_operating_states=list(states),
        hazmat_endorsement_requested=False,
        hazmat_bulk_capable=False,
        passenger_seating_capacity=seating_capacity,
    )


def test_passenger_small_seating_bracket_with_multistate_uplift(api):
    """A 15-seat motorcoach naming 26 states takes the small base plus the uplift.

    PRD S3.2: "For a `PASSENGER` application, the base is $1,500,000 when
    `passenger_seating_capacity` is at most 15 seats, and $5,000,000 when the
    seating capacity is 16 seats or more."  PRD S3.2: "Finally, the
    multi-jurisdiction uplift: if the base is greater than zero **and**
    `requested_operating_states` names 25 or more states, add a flat $250,000 to
    the base."  PRD S3.2: "Separately, `required_cargo_limit_cents` is $10,000
    for a `HOUSEHOLD_GOODS` application and zero for every other class, and
    `required_bond_limit_cents` is $75,000 for a `PROPERTY_BROKER` or
    `FREIGHT_FORWARDER` application and zero for every other class."  PRD S3.2:
    "Opening the draft immediately previews two calculations, and nothing is
    charged yet."

    Design: Difficulty/combinatorial_formula/insurance_minimums_nested_max_and_multistate_uplift
    """
    carrier = _enrolled_carrier(api, MOTORCOACH_CARRIER)
    application = _passenger_application(
        api, carrier["id"], seating_capacity=15, states=TWENTY_SIX_STATES
    )
    assert_authority_application(application)

    # $1,500,000 small-seating base + the $250,000 uplift, in cents.
    assert application["required_bipd_limit_cents"] == 175000000, (
        "a 15-seat PASSENGER application naming 26 states requires "
        f"175000000 cents of BIPD, got {application['required_bipd_limit_cents']}"
    )
    assert application["required_cargo_limit_cents"] == 0, (
        "cargo coverage is required only of HOUSEHOLD_GOODS applications"
    )
    assert application["required_bond_limit_cents"] == 0, (
        "a bond is required only of PROPERTY_BROKER and FREIGHT_FORWARDER "
        "applications"
    )
    minimums = expected_required_minimums(
        "PASSENGER", len(TWENTY_SIX_STATES), passenger_seating_capacity=15
    )
    for field, expected in minimums.items():
        assert application[field] == expected, (
            f"{field} must be {expected}, got {application[field]}"
        )

    # The nothing-is-charged-yet half of the preview.
    assert application["status"] == "DRAFT"
    assert application["submission_count"] == 0, "submission_count opens at zero"
    assert application["filing_fee_cents"] == 84258, (
        "the previewed filing fee for a NEW PASSENGER application naming 26 "
        f"states is 84258 cents, got {application['filing_fee_cents']}"
    )

    # The preview is durable, not a one-off in the create response.
    reread = validate_success(
        api.get_application(application["id"], make_carrier_headers(carrier["id"]))
    )
    assert reread["required_bipd_limit_cents"] == 175000000
    assert reread["filing_fee_cents"] == 84258


def test_passenger_large_seating_bracket_shifts_the_base_before_the_uplift(api):
    """A 16-seat motorcoach on the same 26 states takes the large base, then uplift.

    The seating branch is resolved before the uplift is added, so moving the
    capacity one seat up moves the answer by the full bracket step and keeps the
    same flat uplift on top.

    PRD S3.2: "For a `PASSENGER` application, the base is $1,500,000 when
    `passenger_seating_capacity` is at most 15 seats, and $5,000,000 when the
    seating capacity is 16 seats or more."  PRD S3.2: "if the base is greater
    than zero **and** `requested_operating_states` names 25 or more states, add
    a flat $250,000 to the base."

    Design: Difficulty/combinatorial_formula/insurance_minimums_nested_max_and_multistate_uplift
    """
    carrier = _enrolled_carrier(api, MOTORCOACH_CARRIER)
    application = _passenger_application(
        api, carrier["id"], seating_capacity=16, states=TWENTY_SIX_STATES
    )
    assert_authority_application(application)

    # $5,000,000 large-seating base + the $250,000 uplift, in cents.
    assert application["required_bipd_limit_cents"] == 525000000, (
        "a 16-seat PASSENGER application naming 26 states requires "
        f"525000000 cents of BIPD, got {application['required_bipd_limit_cents']}"
    )
    assert application["required_bipd_limit_cents"] != 175000000, (
        "the 16-seat bracket must not reuse the at-most-15-seat base"
    )
    assert application["required_bipd_limit_cents"] == expected_required_minimums(
        "PASSENGER", len(TWENTY_SIX_STATES), passenger_seating_capacity=16
    )["required_bipd_limit_cents"]
    assert application["required_cargo_limit_cents"] == 0
    assert application["required_bond_limit_cents"] == 0

    # The fee lines depend on the class and the state count, not on the seating
    # bracket, so the previewed fee is unchanged by the shift.
    assert application["filing_fee_cents"] == 84258


def test_multistate_uplift_boundary_sits_at_exactly_twenty_five_states(api):
    """24 states draw no uplift; 25 states draw the flat $250,000.

    PRD S3.2: "if the base is greater than zero **and**
    `requested_operating_states` names 25 or more states, add a flat $250,000 to
    the base. An applicant naming exactly 25 states is uplifted."

    Design: Difficulty/combinatorial_formula/insurance_minimums_nested_max_and_multistate_uplift
    """
    carrier = _enrolled_carrier(api, MOTORCOACH_CARRIER)

    below = _passenger_application(
        api, carrier["id"], seating_capacity=15, states=TWENTY_FOUR_STATES
    )
    assert_authority_application(below)
    assert len(below["requested_operating_states"]) == 24
    assert below["required_bipd_limit_cents"] == 150000000, (
        "24 named states are below the threshold, so the bare $1,500,000 base "
        f"stands, got {below['required_bipd_limit_cents']}"
    )

    at_threshold = _passenger_application(
        api, carrier["id"], seating_capacity=15, states=TWENTY_FIVE_STATES
    )
    assert_authority_application(at_threshold)
    assert len(at_threshold["requested_operating_states"]) == 25
    assert at_threshold["required_bipd_limit_cents"] == 175000000, (
        "an applicant naming exactly 25 states is uplifted, got "
        f"{at_threshold['required_bipd_limit_cents']}"
    )
    assert (
        at_threshold["required_bipd_limit_cents"]
        - below["required_bipd_limit_cents"]
        == 25000000
    ), "the uplift is a flat $250,000 added to the base"


def _household_goods_application(api, carrier_id):
    """S3.2: a DRAFT NEW HOUSEHOLD_GOODS application over three states."""
    return create_draft_application(
        api,
        carrier_id,
        application_kind="NEW",
        transportation_type="HOUSEHOLD_GOODS",
        requested_operating_states=list(HOUSEHOLD_GOODS_STATES),
        hazmat_endorsement_requested=False,
        hazmat_bulk_capable=False,
    )


def test_filing_fee_lines_are_each_rounded_before_they_are_summed(api):
    """The class line's half cent survives as a whole cent in the total.

    The class line for `HOUSEHOLD_GOODS` on the `NEW` track is 45000 x 1.0725 =
    48262.5 cents, which rounds half-up to 48263 on its own; the per-state line
    is 137 x 3 x 1.0725 = 440.7975, which rounds to 441.  Summing the four
    unrounded lines instead would give 80878.2975 and a total of 80878, one cent
    light.

    PRD S3.2: "The fee is built from four independent line items, each rounded
    to whole cents on its own before any of them are added together."  PRD S3.2:
    "`filing_fee_cents` is the sum of those four already-rounded lines, and
    `filing_fee_breakdown` records all four of them under the keys
    `line_docket_cents`, `line_states_cents`, `line_type_cents` and
    `line_hazmat_cents`. The evaluation order is pinned and it matters: rounding
    each line first and summing afterwards produces a different total from
    summing four unrounded lines and rounding once at the end. Only the per-line
    order is correct."  PRD S3.2: "This line is deliberately **not** multiplied
    by the track multiplier."

    Design: Difficulty/combinatorial_formula/filing_fee_per_line_rounding_precedes_summation
    """
    carrier = _enrolled_carrier(api, HOUSEHOLD_GOODS_CARRIER)
    application = _household_goods_application(api, carrier["id"])
    assert_authority_application(application)

    breakdown = application["filing_fee_breakdown"]
    assert breakdown is not None, (
        "filing_fee_breakdown records all four lines on the previewed draft"
    )
    assert sorted(breakdown.keys()) == sorted(FEE_BREAKDOWN_KEYS)
    assert breakdown["line_docket_cents"] == 32175, (
        "30000 x 1.0 x 1.0725 = 32175 cents, got "
        f"{breakdown['line_docket_cents']}"
    )
    assert breakdown["line_states_cents"] == 441, (
        "137 x 3 x 1.0725 = 440.7975 rounds half-up to 441 on its own line, got "
        f"{breakdown['line_states_cents']}"
    )
    assert breakdown["line_type_cents"] == 48263, (
        "45000 x 1.0 x 1.0725 = 48262.5 rounds half-up to 48263 on its own "
        f"line, got {breakdown['line_type_cents']}"
    )
    assert breakdown["line_hazmat_cents"] == 0, (
        "with no hazardous-materials endorsement requested this line is exactly zero"
    )

    assert application["filing_fee_cents"] == 80879, (
        "the sum of the four already-rounded lines is 80879 cents, got "
        f"{application['filing_fee_cents']}"
    )
    assert application["filing_fee_cents"] != 80878, (
        "80878 is the sum-then-round answer, which the pinned per-line order rules out"
    )
    assert sum(breakdown[key] for key in FEE_BREAKDOWN_KEYS) == 80879, (
        "filing_fee_cents must be exactly the sum of the four recorded lines"
    )
    expected = expected_filing_fee("NEW", "HOUSEHOLD_GOODS", len(HOUSEHOLD_GOODS_STATES))
    assert application["filing_fee_cents"] == expected["filing_fee_cents"]
    for key in FEE_BREAKDOWN_KEYS:
        assert breakdown[key] == expected[key], (
            f"{key} must be {expected[key]}, got {breakdown[key]}"
        )

    # The same draft also previews the household-goods cargo requirement.
    assert application["required_cargo_limit_cents"] == 1000000, (
        "required_cargo_limit_cents is $10,000 for a HOUSEHOLD_GOODS application"
    )
    assert application["required_bipd_limit_cents"] == 75000000, (
        "three named states are below the uplift threshold, so the $750,000 "
        "base for HOUSEHOLD_GOODS stands"
    )
    assert application["required_bond_limit_cents"] == 0


def test_first_submission_freezes_the_per_line_rounded_fee_as_a_ledger_debit(api):
    """The per-line total, not the sum-then-round total, is what the carrier owes.

    PRD S3.3: "When `submission_count` becomes 1, the three required insurance
    minimums and the filing fee are recomputed and then **frozen**:
    `filing_fee_cents` and `filing_fee_breakdown` take their final values, a
    ledger entry with `entry_type` `FILING_FEE_DEBIT` and an `amount_cents`
    equal to positive `filing_fee_cents` is appended with its `docket_ref`
    naming this application, and both `fees_assessed_total_cents` and
    `fee_balance_cents` on the owning carrier increase by that amount."  PRD
    S3.2: "`filing_fee_cents` is the sum of those four already-rounded lines".

    Design: Difficulty/combinatorial_formula/filing_fee_per_line_rounding_precedes_summation
    """
    carrier = _enrolled_carrier(api, HOUSEHOLD_GOODS_CARRIER)
    assert carrier["fees_assessed_total_cents"] == 0
    assert carrier["fee_balance_cents"] == 0

    application = _household_goods_application(api, carrier["id"])
    submitted = submit_application(api, carrier["id"], application["id"])
    assert_authority_application(submitted)
    assert submitted["submission_count"] == 1
    assert submitted["filing_fee_cents"] == 80879, (
        "the recomputation at the first submission repeats the per-line rounding, "
        f"got {submitted['filing_fee_cents']}"
    )
    assert (
        sum(submitted["filing_fee_breakdown"][key] for key in FEE_BREAKDOWN_KEYS)
        == 80879
    )
    assert submitted["required_cargo_limit_cents"] == 1000000
    assert submitted["required_bipd_limit_cents"] == 75000000

    entries, meta = validate_paginated(
        api.list_fee_ledger_entries(carrier["id"], REGISTRY_ADMIN, limit=MAX_LIMIT)
    )
    assert meta["total_count"] == 1, (
        "the fee is assessed exactly once, so the first submission appends one "
        f"ledger entry, got {meta['total_count']}"
    )
    debit = assert_fee_ledger_entry(entries[0])
    assert debit["entry_type"] == "FILING_FEE_DEBIT"
    assert debit["amount_cents"] == 80879, (
        "the debit is the positive frozen filing_fee_cents, got "
        f"{debit['amount_cents']}"
    )
    assert debit["carrier_id"] == carrier["id"]
    assert debit["docket_ref"] is not None, (
        "a FILING_FEE_DEBIT carries a docket_ref naming this application"
    )

    reread = validate_success(api.get_carrier(carrier["id"], REGISTRY_ADMIN))
    assert reread["fees_assessed_total_cents"] == 80879, (
        "fees_assessed_total_cents increases by the frozen fee, got "
        f"{reread['fees_assessed_total_cents']}"
    )
    assert reread["fee_balance_cents"] == 80879, (
        f"fee_balance_cents increases by the same amount, got {reread['fee_balance_cents']}"
    )
    assert reread["fees_reversed_total_cents"] == 0
    assert reread["fees_paid_total_cents"] == 0
    assert_fee_ledger_identities(api, carrier["id"], REGISTRY_ADMIN)
