"""Warranty claims: visit reference integrity, the diagnose-then-adjudicate
order, terminal lockdown, diagnostician/adjudicator segregation, and the
pinned per-line settlement rounding."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjudicate_claim,
    create_claim,
    create_warranty_claim_payload,
    diagnose_payload,
    make_claims_adjuster_headers,
    make_fleet_manager_headers,
    setup_commissioned_fleet,
    setup_denied_claim,
    setup_diagnosed_claim,
    setup_service_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADJUSTER = TEST_USERS["claims_adjuster_headers"]
_TECHNICIAN_ALT = TEST_USERS["service_technician_alt_headers"]

_ROUNDING_LINES = [
    {"component_class": "CHARGING", "part_cost_cents": 125, "labor_hours": 0.0},
    {"component_class": "CHARGING", "part_cost_cents": 135, "labor_hours": 0.0},
    {"component_class": "POWERTRAIN", "part_cost_cents": 100000, "labor_hours": 1.0},
]


def test_claim_referencing_unfinished_visit_rejected(api):
    """PRD section 3.11: a claim names "an optional `service_visit_id` that,
    when present, must belong to the same vehicle and be `COMPLETED`
    (`ERR_SERVICE_VISIT_NOT_COMPLETED`)".

    Design: Corner/validations/claim_referencing_unfinished_visit_rejected
    """
    scenario = setup_service_scenario()
    fleet = scenario["fleet"]
    vehicle = fleet["vehicles"][0]
    resp = api.create_warranty_claim(
        create_warranty_claim_payload(
            vehicle["id"],
            claim_lines=[{"component_class": "BODY", "part_cost_cents": 1000, "labor_hours": 0.5}],
            service_visit_id=scenario["visit"]["id"],
        ),
        make_fleet_manager_headers(fleet["customer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SERVICE_VISIT_NOT_COMPLETED)
    rows, meta = validate_paginated(
        api.list_warranty_claims(_ADJUSTER, params={"vehicle_id": vehicle["id"]})
    )
    assert rows == [] and meta["total_count"] == 0


def test_adjudicate_before_diagnosis_rejected(api):
    """PRD section 3.11: "Adjudicating a claim still sitting in `SUBMITTED` is
    refused with `ERR_CLAIM_NOT_DIAGNOSED`".

    Design: Corner/validations/adjudicate_before_diagnosis_rejected
    """
    fleet = setup_commissioned_fleet(num_vehicles=1)
    claim = create_claim(
        fleet["customer"],
        fleet["vehicles"][0]["id"],
        claim_lines=[{"component_class": "BATTERY", "part_cost_cents": 9000, "labor_hours": 1.0}],
    )
    resp = api.adjudicate_warranty_claim(claim["id"], {"decision": "APPROVE"}, _ADJUSTER)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_DIAGNOSED)
    current = validate_success(api.get_warranty_claim(claim["id"], _ADJUSTER), 200)
    assert current["status"] == "SUBMITTED"
    assert current["settlement_cents"] is None


def test_claim_diagnose_from_terminal_rejected(api):
    """PRD section 3.11: "`SETTLED` and `DENIED` are terminal, and touching
    them draws `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/claim_diagnose_from_terminal_rejected
    """
    scenario = setup_denied_claim(denial_reason="Damage from curb strike, not covered.")
    claim = scenario["claim"]
    resp = api.diagnose_warranty_claim(claim["id"], diagnose_payload("Second look."), _TECHNICIAN_ALT)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
    current = validate_success(api.get_warranty_claim(claim["id"], _ADJUSTER), 200)
    assert current["status"] == "DENIED"
    assert current["denial_reason"] == "Damage from curb strike, not covered."
    assert current["settlement_cents"] is None


def test_claim_diagnostician_cannot_adjudicate_own_claim(api):
    """PRD section 2.9: "a `ClaimsAdjuster` may not adjudicate a claim they
    diagnosed: the adjudication caller's `X-User-ID` must differ from the
    claim's `diagnosed_by_user_id`." — surfacing `ERR_SEGREGATION_VIOLATION`
    (HTTP 403); PRD section 3.11 pins the settlement arithmetic.

    Design: Corner/rbac/claim_diagnostician_cannot_adjudicate_own_claim
    """
    scenario = setup_diagnosed_claim(
        claim_lines=[{"component_class": "POWERTRAIN", "part_cost_cents": 50000, "labor_hours": 2.0}]
    )
    claim = scenario["claim"]
    assert claim["diagnosed_by_user_id"] == "st-1"
    resp = api.adjudicate_warranty_claim(
        claim["id"], {"decision": "APPROVE"}, make_claims_adjuster_headers("st-1")
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_VIOLATION)
    settled = adjudicate_claim(claim["id"], "APPROVE")
    assert settled["status"] == "SETTLED"
    assert settled["settlement_cents"] == 60000, (
        "50000 x 1.0 + 2.0 x 17500 x 1.0 = 85000, minus the single 25000 deductible"
    )


def test_warranty_settlement_per_line_rounding_order_on_response(api):
    """PRD section 3.11: "the arithmetic is pinned: for each line, the covered
    part cost is the line's `part_cost_cents` multiplied by the coverage
    fraction for its class — 1.0 for `BATTERY`, 1.0 for `POWERTRAIN`, 0.9 for
    `CHARGING`, 0.8 for `BODY` — rounded half-up to integer cents; ... A claim
    with lines of `CHARGING` at 125 cents, `CHARGING` at 135 cents, and
    `POWERTRAIN` at 100000 cents with 1.0 labor hour settles at 92735 cents —
    113 plus 122 plus 117500, minus 25000 — where sum-then-round would
    wrongly yield 92734."

    Design: Difficulty/combinatorial_formula/warranty_settlement_per_line_rounding_order
    """
    scenario = setup_diagnosed_claim(claim_lines=_ROUNDING_LINES)
    claim = scenario["claim"]
    resp = api.adjudicate_warranty_claim(claim["id"], {"decision": "APPROVE"}, _ADJUSTER)
    data = validate_success(resp, 200)
    assert data["status"] == "SETTLED"
    assert data["settlement_cents"] == 92735, (
        "per-component per-line rounding: 113 + 122 + 117500 - 25000; "
        "sum-then-round would give 92734"
    )
    assert data["adjudicated_by_user_id"] == "ca-1"
    assert data["diagnosed_by_user_id"] == "st-1"


def test_warranty_settlement_per_line_rounding_order_on_readback(api):
    """PRD section 3.11: "The settlement is the sum of all line totals minus
    a single per-claim deductible of 25000 cents, floored at zero. The nested
    rounding order is contractual: rounding each component of each line before
    summing is not the same number as summing raw values and rounding once."

    Design: Difficulty/combinatorial_formula/warranty_settlement_per_line_rounding_order
    """
    scenario = setup_diagnosed_claim(claim_lines=_ROUNDING_LINES)
    claim = scenario["claim"]
    adjudicate_claim(claim["id"], "APPROVE")
    current = validate_success(api.get_warranty_claim(claim["id"], _ADJUSTER), 200)
    assert current["status"] == "SETTLED"
    assert current["settlement_cents"] == 92735
    assert current["denial_reason"] is None
    assert current["adjudicated_by_user_id"] == "ca-1"
