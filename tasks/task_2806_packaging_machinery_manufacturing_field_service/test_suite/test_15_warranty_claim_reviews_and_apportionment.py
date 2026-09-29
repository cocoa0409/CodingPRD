"""Arguing the warranty question: two reviews, one adjudication, and the split.

Cost is captured as immutable lines, both branches of the fork must sign off before
the join, and the OEM share is apportioned line by line with a pinned rounding order.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    SERVICE_MANAGER,
    ApiErrorId,
    api_client,
    create_warranty_claim_payload,
    read_claim,
    read_claim_line,
    read_contract,
    read_machine,
    seed_customer,
    setup_accepted_machine,
    setup_active_contract,
    setup_claim_ready_for_adjudication,
    setup_claim_with_lines,
    setup_reference_data,
)

SILVER_500K = {
    "tier": "SILVER",
    "start_date": "2026-08-01",
    "end_date": "2027-07-31",
    "pm_visits_included": 2,
    "goodwill_budget_initial_cents": 500_000,
}
SILVER_350K = dict(SILVER_500K, goodwill_budget_initial_cents=350_000)
TWO_LINES = [
    {"line_label": "Valve seat kit", "amount_cents": 12_345, "defect_attribution_pct": 80.00},
    {"line_label": "Field labour", "amount_cents": 6_789, "defect_attribution_pct": 40.00},
]


def _wandering_product_claim():
    """A two-line claim for a plant declaring 12.00% variation, both branches signed."""
    env = setup_accepted_machine(
        setup_reference_data(customer={"legal_name": "Cascade Foods", "product_variation_pct": 12.00}, line={})
    )
    return setup_claim_ready_for_adjudication(
        env,
        contract_overrides=dict(SILVER_500K),
        lines=TWO_LINES,
        claim_overrides={"failure_summary": "Filling valve seat wear with product carry-over"},
    )


def test_each_claim_line_is_rounded_to_whole_cents_before_the_shares_are_summed():
    """Rounding the two derated line shares individually yields 9185 plus 2526, one cent
    more than the 11710 a single rounding of the summed raw shares would produce.

    PRD: "Each line's `oem_line_share_cents` is then its `amount_cents` multiplied by
    its effective percentage divided by one hundred, rounded half up to whole cents
    **for that line**; `oem_share_cents` is the integer sum of those rounded line
    shares."

    Design: Difficulty/combinatorial_formula/claim_apportionment_rounds_each_line_before_summing
    """
    env = _wandering_product_claim()
    first, second = env["claim_lines"]

    data = validate_success(
        api_client.adjudicate_warranty_claim(env["claim"]["id"], "APPROVE", SERVICE_MANAGER)
    )

    assert data["status"] == "ADJUDICATED"
    assert data["claimed_cost_cents"] == 19_134
    assert read_claim_line(first["id"])["oem_line_share_cents"] == 9_185
    assert read_claim_line(second["id"])["oem_line_share_cents"] == 2_526
    assert data["oem_share_cents"] == 11_711
    assert data["oem_share_cents"] == 9_185 + 2_526


def test_the_claim_split_is_a_mixed_cause_whose_residual_funds_the_customer():
    """The cost-weighted attribution lands between the two boundaries, and the customer
    carries the exact residual so the two shares add back to the claimed cost.

    PRD: "`customer_share_cents` is then the exact residual — the claimed cost less the
    OEM share — so that the two shares always add back to `claimed_cost_cents`."

    Design: Difficulty/combinatorial_formula/claim_apportionment_rounds_each_line_before_summing
    """
    env = _wandering_product_claim()

    data = validate_success(
        api_client.adjudicate_warranty_claim(env["claim"]["id"], "APPROVE", SERVICE_MANAGER)
    )

    assert data["cause"] == "MIXED"
    assert data["customer_share_cents"] == 7_423
    assert data["oem_share_cents"] + data["customer_share_cents"] == data["claimed_cost_cents"]
    assert data["goodwill_charged_cents"] == 8_783
    contract = read_contract(env["contract"]["id"])
    assert contract["goodwill_budget_cents"] == 491_217
    assert contract["coverage_posture"] == "OPEN"


def test_a_rejected_claim_records_the_cause_but_spends_no_goodwill():
    """The rejection still classifies the failure as the machine's fault, yet the whole
    claimed cost lands on the customer and the pot is untouched.

    PRD: "Under a **rejection**, that residual arithmetic collapses to its extreme: the
    claim moves to `REJECTED`, `oem_share_cents` is set to 0 and `customer_share_cents`
    to the full `claimed_cost_cents`, the computed `cause` is still recorded, and the
    contract's `goodwill_budget_cents` is not touched at all."

    Design: Corner/calculations/claim_reject_charges_no_goodwill_and_leaves_budget_intact
    """
    env = setup_accepted_machine(setup_reference_data(line={}))
    env = setup_claim_ready_for_adjudication(
        env,
        variation_first=False,
        contract_overrides=dict(SILVER_500K, tier="GOLD", goodwill_budget_initial_cents=300_000),
        lines=[
            {
                "line_label": "valve seat assembly",
                "amount_cents": 400_000,
                "defect_attribution_pct": 100.00,
            }
        ],
        claim_overrides={"failure_summary": "filling valve seat fractured after 300 hours"},
    )

    data = validate_success(
        api_client.adjudicate_warranty_claim(env["claim"]["id"], "REJECT", SERVICE_MANAGER)
    )

    assert data["status"] == "REJECTED"
    assert data["cause"] == "MACHINE_DEFECT"
    assert data["claimed_cost_cents"] == 400_000
    assert data["oem_share_cents"] == 0
    assert data["customer_share_cents"] == 400_000
    assert data["goodwill_charged_cents"] == 0
    contract = read_contract(env["contract"]["id"])
    assert contract["goodwill_budget_cents"] == 300_000
    assert contract["coverage_posture"] == "OPEN"


def test_neither_review_branch_may_be_signed_off_on_a_claim_with_no_cost():
    """A claim carrying no lines has nothing to apportion, so the first branch of the
    fork is refused and the claim stays where it was opened.

    PRD: "Both branches require at least one cost line to exist on the claim, or they
    are refused with `ERR_CLAIM_HAS_NO_LINES`, and neither branch may be signed off
    twice (`ERR_INVALID_CLAIM_STATE`)."

    Design: Corner/errors/claim_product_variation_review_with_no_lines_returns_422_claim_has_no_lines
    """
    env = setup_accepted_machine(setup_reference_data(line={}))
    env = setup_claim_with_lines(
        env,
        lines=[],
        contract_overrides=dict(SILVER_350K),
        claim_overrides={"failure_summary": "Nozzle block cracked during production"},
    )

    response = api_client.review_product_variation_warranty_claim(
        env["claim"]["id"], SERVICE_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_CLAIM_HAS_NO_LINES.value, 422)
    claim = read_claim(env["claim"]["id"])
    assert claim["status"] == "SUBMITTED"
    assert claim["product_variation_review_done"] is False
    assert claim["claimed_cost_cents"] == 0


def test_the_product_variation_branch_may_not_be_signed_off_a_second_time():
    """The fork allows one sign-off per branch, so repeating the variation review is
    refused while the defect branch is still waiting and the cause is undetermined.

    PRD: "Both branches require at least one cost line to exist on the claim, or they
    are refused with `ERR_CLAIM_HAS_NO_LINES`, and neither branch may be signed off
    twice (`ERR_INVALID_CLAIM_STATE`)."

    Design: Corner/errors/claim_second_product_variation_signoff_returns_409_invalid_claim_state
    """
    env = setup_accepted_machine(setup_reference_data(line={}))
    env = setup_claim_with_lines(
        env,
        lines=[
            {
                "line_label": "Nozzle block replacement",
                "amount_cents": 400_000,
                "defect_attribution_pct": 100.00,
            }
        ],
        contract_overrides=dict(SILVER_350K),
        claim_overrides={"failure_summary": "Nozzle block cracked during production"},
    )
    validate_success(
        api_client.review_product_variation_warranty_claim(env["claim"]["id"], SERVICE_MANAGER)
    )

    response = api_client.review_product_variation_warranty_claim(
        env["claim"]["id"], SERVICE_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_INVALID_CLAIM_STATE.value, 409)
    claim = read_claim(env["claim"]["id"])
    assert claim["product_variation_review_done"] is True
    assert claim["defect_review_done"] is False
    assert claim["cause"] == "UNDETERMINED"


def test_the_join_cannot_be_reached_with_only_one_branch_signed_off():
    """Adjudication is the join of the parallel fork, so a half-reviewed claim is
    refused and not a cent of goodwill moves.

    PRD: "The claim must be sitting in `PRODUCT_VARIATION_REVIEW` or in `DEFECT_REVIEW`,
    both `product_variation_review_done` and `defect_review_done` must be true
    (`ERR_CLAIM_REVIEWS_INCOMPLETE`), and the funding contract must be `ACTIVE`
    (`ERR_CONTRACT_NOT_ACTIVE`)."

    Design: Corner/errors/claim_adjudicate_after_one_review_returns_409_claim_reviews_incomplete
    """
    env = setup_accepted_machine(setup_reference_data(line={}))
    env = setup_claim_with_lines(
        env,
        lines=[
            {
                "line_label": "Nozzle block replacement",
                "amount_cents": 400_000,
                "defect_attribution_pct": 100.00,
            }
        ],
        contract_overrides=dict(SILVER_350K),
        claim_overrides={"failure_summary": "Nozzle block cracked during production"},
    )
    validate_success(
        api_client.review_product_variation_warranty_claim(env["claim"]["id"], SERVICE_MANAGER)
    )

    response = api_client.adjudicate_warranty_claim(env["claim"]["id"], "APPROVE", SERVICE_MANAGER)

    validate_error(response, ApiErrorId.ERR_CLAIM_REVIEWS_INCOMPLETE.value, 409)
    claim = read_claim(env["claim"]["id"])
    assert claim["status"] == "PRODUCT_VARIATION_REVIEW"
    assert claim["goodwill_charged_cents"] == 0
    assert read_contract(env["contract"]["id"])["goodwill_budget_cents"] == 350_000


def test_a_claim_must_be_funded_by_the_contract_that_covers_its_own_machine():
    """Both machines are accepted and the contract is active, so the refusal is about the
    coverage chain rather than a lookup or a lifecycle state.

    PRD: "The named contract must actually cover the named machine — the contract's
    `installed_machine_id` must equal the claim's — or the request is refused with
    `ERR_CONTRACT_MACHINE_MISMATCH`; and a `CustomerContact` opening a claim on someone
    else's machine is refused with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/errors/warranty_claim_with_another_machines_contract_returns_422_contract_machine_mismatch
    """
    env = setup_accepted_machine(setup_reference_data(line={}))
    env = setup_active_contract(env, contract_overrides=dict(SILVER_350K))
    other_plant = {
        "customer": seed_customer(
            legal_name="Contoso Foods", region_code="EU", product_variation_pct=6.00
        ),
        "model": env["model"],
        "line": env["line"],
    }
    other_plant = setup_accepted_machine(
        other_plant,
        machine_overrides={"serial_number": "SN-2806-002"},
        start_date="2026-09-01",
    )

    response = api_client.create_warranty_claim(
        create_warranty_claim_payload(
            other_plant["machine"]["id"],
            env["contract"]["id"],
            failure_summary="Nozzle block cracked during production",
        ),
        SERVICE_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_CONTRACT_MACHINE_MISMATCH.value, 422)
    assert read_contract(env["contract"]["id"])["installed_machine_id"] == env["machine"]["id"]
    assert read_machine(other_plant["machine"]["id"])["open_claim_count"] == 0
    rows, meta = validate_paginated(
        api_client.list_warranty_claims(
            SERVICE_MANAGER, params={"installed_machine_id": other_plant["machine"]["id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_claim_read_with_unknown_id_reports_the_claim_not_found_code():
    """The warranty desk reports the claim's own miss code.

    PRD: "Each miss reports that entity's own not-found code:
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_MACHINE_MODEL_NOT_FOUND`,
    `ERR_PRODUCT_TRIAL_NOT_FOUND`, `ERR_MACHINE_ORDER_NOT_FOUND`,
    `ERR_PRODUCTION_LINE_NOT_FOUND`, `ERR_BUILD_SLOT_NOT_FOUND`,
    `ERR_COMPONENT_NOT_FOUND`, `ERR_ACCEPTANCE_TEST_NOT_FOUND`,
    `ERR_INSTALLED_MACHINE_NOT_FOUND`, `ERR_FORMAT_KIT_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_FIELD_ENGINEER_NOT_FOUND`,
    `ERR_PM_VISIT_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_CLAIM_LINE_NOT_FOUND`, `ERR_STOCKING_RECOMMENDATION_NOT_FOUND` — each with
    HTTP 404."

    Design: Corner/errors/warranty_claim_get_unknown_id_returns_404_not_found
    """
    response = api_client.get_warranty_claim(
        "dddddddd-dddd-4ddd-8ddd-dddddddddddd", SERVICE_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_WARRANTY_CLAIM_NOT_FOUND.value, 404)


def test_claim_line_read_with_unknown_id_reports_the_line_not_found_code():
    """A cost line has its own miss code, distinct from its parent claim's.

    PRD: "Each miss reports that entity's own not-found code:
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_MACHINE_MODEL_NOT_FOUND`,
    `ERR_PRODUCT_TRIAL_NOT_FOUND`, `ERR_MACHINE_ORDER_NOT_FOUND`,
    `ERR_PRODUCTION_LINE_NOT_FOUND`, `ERR_BUILD_SLOT_NOT_FOUND`,
    `ERR_COMPONENT_NOT_FOUND`, `ERR_ACCEPTANCE_TEST_NOT_FOUND`,
    `ERR_INSTALLED_MACHINE_NOT_FOUND`, `ERR_FORMAT_KIT_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_FIELD_ENGINEER_NOT_FOUND`,
    `ERR_PM_VISIT_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_CLAIM_LINE_NOT_FOUND`, `ERR_STOCKING_RECOMMENDATION_NOT_FOUND` — each with
    HTTP 404."

    Design: Corner/errors/warranty_claim_line_get_unknown_id_returns_404_not_found
    """
    response = api_client.get_warranty_claim_line(
        "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee", SERVICE_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_CLAIM_LINE_NOT_FOUND.value, 404)
