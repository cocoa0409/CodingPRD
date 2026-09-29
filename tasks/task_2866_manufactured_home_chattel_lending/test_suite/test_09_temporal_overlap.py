"""Two contended timelines with two different interval conventions.

A loan's borrower-provided coverage is a plain half-open interval where touching
endpoints are legal (PRD §3.6), while a community lot's occupancy is extended
seven days past move-out and only the candidate's start instant is tested against
it (PRD §3.2).
"""

from test_helpers import (
    ApiErrorId,
    assert_insurance_policy,
    assert_instant_equals,
    assert_manufactured_unit,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
PRINCIPAL_CENTS = 4600000
REQUESTED_TERM_MONTHS = 240

# ─── The contended coverage timeline ───
INCUMBENT_EFFECTIVE_DATE = "2026-08-01T00:00:00Z"
INCUMBENT_EXPIRY_DATE = "2027-08-01T00:00:00Z"
INCUMBENT_COVERAGE_CENTS = 5200000
INCUMBENT_COVERAGE_DAYS = 365
OVERLAPPING_EFFECTIVE_DATE = "2027-01-01T00:00:00Z"
OVERLAPPING_EXPIRY_DATE = "2028-01-01T00:00:00Z"
ABUTTING_EFFECTIVE_DATE = "2027-08-01T00:00:00Z"
ABUTTING_EXPIRY_DATE = "2028-08-01T00:00:00Z"
ABUTTING_COVERAGE_CENTS = 5300000
ABUTTING_COVERAGE_DAYS = 366
CERTIFIED_CENTS = 5776403
REQUIRED_COVERAGE_CENTS = 4621122
COASTAL = {"carrier_name": "Coastal Indemnity"}

# ─── The contended lot ───
CYPRESS_LANDING = {
    "name": "Cypress Landing MHC",
    "state_code": "GA",
    "lot_count": 96,
    "monthly_lot_rent_cents": 48000,
    "sales_commission_bps": 200,
}
CONTESTED_LOT = "B-07"
NEIGHBOURING_LOT = "B-08"
INCUMBENT_PLACEMENT_START = "2026-08-01T00:00:00Z"
INCUMBENT_PLACEMENT_END = "2026-12-31T00:00:00Z"
LAST_BLOCKED_MOVE_IN = "2027-01-06T00:00:00Z"
FIRST_ADMISSIBLE_MOVE_IN = "2027-01-07T00:00:00Z"
INCUMBENT_UNIT = {
    "manufacturer": "Fleetwood",
    "model_year": 2014,
    "width_class": "SINGLE_WIDE",
    "square_feet": 1080,
    "lot_number": CONTESTED_LOT,
    "placement_start_date": INCUMBENT_PLACEMENT_START,
    "placement_end_date": INCUMBENT_PLACEMENT_END,
}
CANDIDATE_UNIT = {"manufacturer": "Clayton", "model_year": 2019}


def _approved_loan_with_one_year_of_incumbent_coverage(api):
    """An APPROVED community loan carrying a single ACTIVE borrower policy."""
    scenario = fixtures.setup_community_collateral(
        api, clock=CLOCK, agreement="EXECUTED"
    )
    scenario = fixtures.setup_approved_loan(
        api,
        scenario,
        principal_cents=PRINCIPAL_CENTS,
        requested_term_months=REQUESTED_TERM_MONTHS,
    )
    scenario["policy"] = fixtures.record_policy(
        api,
        scenario["loan"]["id"],
        INCUMBENT_COVERAGE_CENTS,
        effective_date=INCUMBENT_EFFECTIVE_DATE,
        expiry_date=INCUMBENT_EXPIRY_DATE,
    )
    scenario["loan_version"] = fixtures.read_loan(api, scenario["loan"]["id"])[
        "version"
    ]
    return scenario


def _candidate_policy(loan_id, loan_version, effective_date, expiry_date):
    """A second borrower-provided policy on the same loan, priced identically."""
    return factories.insurance_policy_payload(
        loan_id,
        loan_version,
        ABUTTING_COVERAGE_CENTS,
        effective_date=effective_date,
        expiry_date=expiry_date,
        **COASTAL,
    )


def _community_with_an_occupied_lot(api):
    """A 96-lot community whose lot B-07 is occupied through 2026-12-31."""
    community = fixtures.register_community(api, **CYPRESS_LANDING)
    incumbent = fixtures.register_community_unit(
        api, community["id"], **INCUMBENT_UNIT
    )
    assert_instant_equals(
        incumbent["placement_end_date"],
        INCUMBENT_PLACEMENT_END,
        "ManufacturedUnit.placement_end_date",
    )
    return {"community": community, "incumbent": incumbent}


def _lot_claim(community_id, lot_number, placement_start_date):
    """A fresh community placement claiming one named lot from one instant on."""
    return factories.community_unit_payload(
        community_id,
        lot_number=lot_number,
        placement_start_date=placement_start_date,
        **CANDIDATE_UNIT,
    )


def test_a_second_policy_intersecting_the_incumbent_interval_is_refused(api):
    """PRD §3.6: "A new policy's half-open interval must not intersect the half-open
    interval of any policy on the same loan whose `status` is `ACTIVE` and whose
    `source` is `BORROWER_PROVIDED`, and an intersection is refused with
    `ERR_COVERAGE_PERIOD_OVERLAP` (HTTP 409)."
    PRD §3.6: "That interval is half-open: `effective_date` is the first instant of
    coverage and is included; `expiry_date` is the first instant after coverage and
    is excluded."

    Design: Difficulty/resource_temporal_overlap/insurance_coverage_intervals_overlap_vs_touching_endpoints
    """
    scenario = _approved_loan_with_one_year_of_incumbent_coverage(api)
    incumbent = scenario["policy"]
    assert scenario["valuation"]["certified_value_cents"] == CERTIFIED_CENTS
    assert_insurance_policy(incumbent)
    assert incumbent["source"] == "BORROWER_PROVIDED"
    assert incumbent["status"] == "ACTIVE"
    assert incumbent["coverage_days"] == INCUMBENT_COVERAGE_DAYS
    assert incumbent["required_coverage_cents"] == REQUIRED_COVERAGE_CENTS

    validate_error(
        api.create_insurance_policy(
            _candidate_policy(
                scenario["loan"]["id"],
                scenario["loan_version"],
                OVERLAPPING_EFFECTIVE_DATE,
                OVERLAPPING_EXPIRY_DATE,
            ),
            fixtures.SERVICER,
        ),
        ApiErrorId.ERR_COVERAGE_PERIOD_OVERLAP.value,
        409,
    )

    rows, meta = validate_paginated(
        api.list_insurance_policies(
            fixtures.SERVICER, {"loan_id": scenario["loan"]["id"]}
        )
    )
    assert meta["total_count"] == 1, "the refused attempt created no policy row"
    assert rows[0]["id"] == incumbent["id"]
    assert rows[0]["status"] == "ACTIVE"


def test_an_abutting_policy_shares_only_an_endpoint_and_supersedes_the_incumbent(api):
    """PRD §3.6: "Touching endpoints do not intersect: if one interval's
    `expiry_date` equals the other's `effective_date`, the two are back-to-back and
    both are allowed."
    PRD §3.6: "Creating it moves any earlier `ACTIVE` borrower-provided policy on
    the same loan to `SUPERSEDED` and recomputes the loan's `insurance_compliance`
    from whichever policy survives as `ACTIVE`, which is either `COMPLIANT` or
    `NON_COMPLIANT`."
    PRD §3.6: "The platform computes `coverage_days` as the whole calendar days from
    `effective_date` up to `expiry_date`."

    Design: Difficulty/resource_temporal_overlap/insurance_coverage_intervals_overlap_vs_touching_endpoints
    """
    scenario = _approved_loan_with_one_year_of_incumbent_coverage(api)
    loan_id = scenario["loan"]["id"]
    loan_version = scenario["loan_version"]
    validate_error(
        api.create_insurance_policy(
            _candidate_policy(
                loan_id,
                loan_version,
                OVERLAPPING_EFFECTIVE_DATE,
                OVERLAPPING_EXPIRY_DATE,
            ),
            fixtures.SERVICER,
        ),
        ApiErrorId.ERR_COVERAGE_PERIOD_OVERLAP.value,
        409,
    )

    successor = validate_success(
        api.create_insurance_policy(
            _candidate_policy(
                loan_id,
                loan_version,
                ABUTTING_EFFECTIVE_DATE,
                ABUTTING_EXPIRY_DATE,
            ),
            fixtures.SERVICER,
        ),
        201,
    )

    assert successor["status"] == "ACTIVE", (
        "the refused attempt never consumed the loan version, so the same "
        "expected_loan_version still matched"
    )
    assert successor["coverage_days"] == ABUTTING_COVERAGE_DAYS
    assert successor["source"] == "BORROWER_PROVIDED"
    assert successor["required_coverage_cents"] == REQUIRED_COVERAGE_CENTS
    assert successor["compliance_state"] == "COMPLIANT"
    assert_instant_equals(
        successor["effective_date"],
        ABUTTING_EFFECTIVE_DATE,
        "InsurancePolicy.effective_date",
    )

    incumbent = fixtures.read_policy(api, scenario["policy"]["id"])
    assert incumbent["status"] == "SUPERSEDED"
    assert incumbent["coverage_days"] == INCUMBENT_COVERAGE_DAYS
    assert incumbent["unearned_premium_refund_cents"] == 0

    _, meta = validate_paginated(
        api.list_insurance_policies(fixtures.SERVICER, {"loan_id": loan_id})
    )
    assert meta["total_count"] == 2
    assert fixtures.read_loan(api, loan_id)["insurance_compliance"] == "COMPLIANT"


def test_a_move_in_inside_the_seven_day_turnover_buffer_is_refused(api):
    """PRD §3.2: "Each incumbent occupies a half-open interval that begins at its
    `placement_start_date` and ends seven days after its `placement_end_date`; those
    seven days are the turnover buffer during which the lot is being cleaned and
    re-set."
    PRD §3.2: "When a new placement claims a `community_id` and `lot_number` pair,
    the platform examines every existing unit already claiming that same pair."

    Design: Difficulty/resource_temporal_overlap/lot_occupancy_turnover_buffer_boundary
    """
    scenario = _community_with_an_occupied_lot(api)
    community_id = scenario["community"]["id"]

    validate_error(
        api.create_unit(
            _lot_claim(community_id, CONTESTED_LOT, LAST_BLOCKED_MOVE_IN),
            fixtures.CLOSER,
        ),
        ApiErrorId.ERR_LOT_OCCUPANCY_CONFLICT.value,
        409,
    )

    neighbour = validate_success(
        api.create_unit(
            _lot_claim(community_id, NEIGHBOURING_LOT, LAST_BLOCKED_MOVE_IN),
            fixtures.CLOSER,
        ),
        201,
    )

    assert_manufactured_unit(neighbour)
    assert neighbour["lot_number"] == NEIGHBOURING_LOT, (
        "the identical move-in instant is unaffected one lot over, so the conflict "
        "is keyed on the community and lot pair rather than on the date alone"
    )
    assert_instant_equals(
        neighbour["placement_start_date"],
        LAST_BLOCKED_MOVE_IN,
        "ManufacturedUnit.placement_start_date",
    )

    rows, meta = validate_paginated(
        api.list_units(fixtures.CLOSER, {"community_id": community_id})
    )
    assert meta["total_count"] == 2, "the refused registration was never persisted"
    assert sorted(row["lot_number"] for row in rows) == [
        CONTESTED_LOT,
        NEIGHBOURING_LOT,
    ]


def test_the_first_admissible_move_in_is_the_buffers_exclusive_upper_endpoint(api):
    """PRD §3.2: "If the new `placement_start_date` falls inside any incumbent's
    buffered interval, the registration is refused with
    `ERR_LOT_OCCUPANCY_CONFLICT` (HTTP 409)."
    PRD §3.2: "Two further placement fields are optional in both cases:
    `placement_end_date` closes the occupancy interval, and a null value there means
    occupancy is open-ended; `land_value_cents` records the assessed land value and
    defaults to 0."

    Design: Difficulty/resource_temporal_overlap/lot_occupancy_turnover_buffer_boundary
    """
    scenario = _community_with_an_occupied_lot(api)
    community_id = scenario["community"]["id"]
    validate_error(
        api.create_unit(
            _lot_claim(community_id, CONTESTED_LOT, LAST_BLOCKED_MOVE_IN),
            fixtures.CLOSER,
        ),
        ApiErrorId.ERR_LOT_OCCUPANCY_CONFLICT.value,
        409,
    )

    successor = validate_success(
        api.create_unit(
            _lot_claim(community_id, CONTESTED_LOT, FIRST_ADMISSIBLE_MOVE_IN),
            fixtures.CLOSER,
        ),
        201,
    )

    assert_instant_equals(
        successor["placement_start_date"],
        FIRST_ADMISSIBLE_MOVE_IN,
        "ManufacturedUnit.placement_start_date",
    )
    assert successor["lot_number"] == CONTESTED_LOT
    assert successor["placement_end_date"] is None, "the new occupancy is open-ended"
    assert successor["classification"] == "PERSONAL_PROPERTY"

    incumbent = fixtures.read_unit(api, scenario["incumbent"]["id"])
    assert_instant_equals(
        incumbent["placement_end_date"],
        INCUMBENT_PLACEMENT_END,
        "ManufacturedUnit.placement_end_date",
    )
    assert incumbent["version"] == scenario["incumbent"]["version"], (
        "neither attempt on the lot touched the sitting tenant's row"
    )
