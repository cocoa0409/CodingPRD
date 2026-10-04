"""Supply-mode evaluation: threshold ladder branches, payload validation,
supersession, and acceptance state rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_evaluation,
    api_client,
    assert_evaluation,
    create_customer,
    create_evaluation,
    create_evaluation_payload,
    make_customer_ops_headers,
    set_logical_clock,
    validate_error,
    validate_success,
)


def _eval_by_id(customer_id, evaluation_id):
    """Fetch one evaluation through the customer's evaluation list."""
    evaluations = api_client.list_customer_evaluations(
        customer_id, TEST_USERS["supply_planner_headers"]
    )
    data = validate_success(evaluations)
    match = [e for e in data if e["id"] == evaluation_id]
    assert len(match) == 1, f"evaluation {evaluation_id} not found in customer list"
    return match[0]


def test_mode_threshold_exact_boundary(api):
    """PRD section 3.1: "a site averaging at least 4,000 Nm3/h is recommended
    `ONSITE_PLANT`; below that, a site with pipeline frontage averaging at
    least 1,500 Nm3/h is recommended `PIPELINE`; otherwise a site averaging at
    least 200 Nm3/h is recommended `BULK_LIQUID`; anything smaller falls to
    `CYLINDER`. The thresholds are inclusive — a demand exactly equal to a
    threshold takes the higher mode."

    Design: Difficulty/boundary_precision_check/mode_threshold_exact_boundary
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    high = create_evaluation(
        customer["id"], site_label="S-HI", demand_avg_nm3h=4000,
        demand_peak_nm3h=5000, required_purity_percent=99.9,
        required_product="N2", pipeline_available=True,
    )
    low = create_evaluation(
        customer["id"], site_label="S-LO", demand_avg_nm3h=3999.99,
        demand_peak_nm3h=5000, required_purity_percent=99.9,
        required_product="N2", pipeline_available=True,
    )
    assert high["recommended_mode"] == "ONSITE_PLANT", (
        f"demand exactly 4000 must take ONSITE_PLANT (inclusive), got {high['recommended_mode']}"
    )
    assert low["recommended_mode"] == "PIPELINE", (
        f"demand 3999.99 with pipeline frontage must take PIPELINE, got {low['recommended_mode']}"
    )


def test_mode_recommendation_bulk_and_cylinder_branches(api):
    """PRD section 3.1: "otherwise a site averaging at least 200 Nm3/h is
    recommended `BULK_LIQUID`; anything smaller falls to `CYLINDER`."

    Design: Corner/calculations/mode_recommendation_bulk_and_cylinder_branches
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    bulk = create_evaluation(
        customer["id"], site_label="S-BULK", demand_avg_nm3h=300,
        demand_peak_nm3h=400, required_purity_percent=99.9,
        required_product="AR", pipeline_available=False,
    )
    cylinder = create_evaluation(
        customer["id"], site_label="S-CYL", demand_avg_nm3h=150,
        demand_peak_nm3h=220, required_purity_percent=99.9,
        required_product="AR", pipeline_available=False,
    )
    assert bulk["recommended_mode"] == "BULK_LIQUID", (
        f"avg 300 without pipeline must be BULK_LIQUID, got {bulk['recommended_mode']}"
    )
    assert cylinder["recommended_mode"] == "CYLINDER", (
        f"avg 150 must be CYLINDER, got {cylinder['recommended_mode']}"
    )


def test_evaluation_missing_customer_id_returns_400(api):
    """PRD section 2.8: "Structural validation (`ERR_VALIDATION`): malformed
    bodies, missing required fields, invalid enum values, a peak demand below
    average demand, a tank reorder point at or below its safety stock, an
    out-of-range level, or `apply_makeup_cents` supplied on a provisional
    statement."
    PRD section 3.1: "a `SupplyPlanner` commissions a supply-mode evaluation
    for a particular site by submitting the `customer_id`, a free-form
    `site_label`, the site's `demand_avg_nm3h` and `demand_peak_nm3h`, the
    `required_purity_percent` (99.999 is typical for electronics-grade
    nitrogen), the `required_product` (`N2`, `O2`, `H2`, `AR`, or `HE`), and a
    `pipeline_available` flag recording whether pipeline frontage exists at the
    site."

    Design: Corner/entities/evaluation_missing_customer_id_returns_400
    """
    set_logical_clock()
    payload = {
        "site_label": "FAB-1",
        "demand_avg_nm3h": 5000,
        "demand_peak_nm3h": 7000,
        "required_purity_percent": 99.999,
        "required_product": "N2",
        "pipeline_available": True,
    }
    response = api_client.create_evaluation(
        payload, TEST_USERS["supply_planner_headers"]
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION)


def test_evaluation_peak_below_average_rejected(api):
    """PRD section 3.1: "A peak demand below the average demand is rejected
    with `ERR_VALIDATION`."

    Design: Corner/entities/evaluation_peak_below_average_rejected
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    payload = create_evaluation_payload(
        customer["id"], demand_avg_nm3h=5000, demand_peak_nm3h=4000
    )
    response = api_client.create_evaluation(
        payload, TEST_USERS["supply_planner_headers"]
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION)


def test_evaluation_accept_supersedes_evaluated_sibling(api):
    """PRD section 3.1: "Creating a fresh evaluation for the same `customer_id`
    and `site_label` moves every sibling still in `EVALUATED` to `SUPERSEDED`."
    PRD section 3.1: "Acceptance moves the evaluation to `ACCEPTED` and
    supersedes every sibling in either `EVALUATED` or `ACCEPTED`."

    Design: Corner/state_machines/evaluation_accept_supersedes_evaluated_sibling
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    first = create_evaluation(customer["id"])
    assert first["status"] == "EVALUATED", (
        f"a newly created evaluation starts in EVALUATED, got {first['status']}"
    )
    second = create_evaluation(customer["id"], demand_avg_nm3h=5200,
                               demand_peak_nm3h=7200)
    assert second["status"] == "EVALUATED"
    accepted = accept_evaluation(second["id"], customer["id"])
    assert_evaluation(accepted)
    assert accepted["status"] == "ACCEPTED"
    first_after = _eval_by_id(customer["id"], first["id"])
    assert first_after["status"] == "SUPERSEDED", (
        f"the EVALUATED sibling must be SUPERSEDED, got {first_after['status']}"
    )


def test_evaluation_accept_twice_returns_invalid_state(api):
    """PRD section 3.1: "Acceptance is performed by `CustomerOps`, and only
    when the caller's `X-User-ID` equals the evaluation's `customer_id` —
    otherwise the call is rejected with `ERR_UNAUTHORIZED_ROLE`; acceptance is
    legal only from `EVALUATED`, any other current state drawing
    `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/evaluation_accept_twice_returns_invalid_state
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    evaluation = create_evaluation(customer["id"])
    accept_evaluation(evaluation["id"], customer["id"])
    response = api_client.accept_evaluation(
        evaluation["id"], make_customer_ops_headers(customer["id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    still = _eval_by_id(customer["id"], evaluation["id"])
    assert still["status"] == "ACCEPTED", (
        f"the evaluation must remain ACCEPTED, got {still['status']}"
    )
