"""Contract lifecycle cascades: termination, terminal lockdown, execution gating."""
from test_helpers import (
    ApiErrorId,
    add_approved_baseline,
    add_bundle_with_measures,
    create_contract,
    create_facility_payload,
    create_measure_payload,
    eng_headers,
    lender_headers,
    make_actor_ids,
    own_headers,
    reset_clock,
    scoped_contract,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers.factories import create_bundle_payload


def test_contract_termination_cascades_to_bundles_measures_facilities(api):
    """PRD §3.2: "Termination cascades broadly: every non-terminal bundle
    moves to `WITHDRAWN` and its non-terminal measures to `EXCLUDED`, every
    `DRAFT` or `SUBMITTED` financing facility moves to `CANCELLED`, and the
    contract's `version` increments."

    Design: Difficulty/transitive_cascade/contract_termination_cascades_to_bundles_measures_facilities
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, bundle, measures, _f = scoped_contract(
        eng_id, owner_id,
        measures=[
            create_measure_payload(measure_type="LIGHTING",
                                   installed_cost_cents=100000,
                                   annual_savings_cents=50000),
            create_measure_payload(measure_type="WATER",
                                   installed_cost_cents=50000,
                                   annual_savings_cents=20000),
        ],
        facility_name="Termination High",
    )
    cid = contract["id"]
    facility = validate_success(
        api.create_facility(cid, create_facility_payload(), eng_headers(eng_id)),
        201,
    )
    validate_success(
        api.submit_facility(cid, facility["id"], eng_headers(eng_id))
    )
    terminated = validate_success(
        api.terminate_contract(cid, own_headers(owner_id))
    )
    assert terminated["status"] == "TERMINATED"
    bundle = validate_success(api.get_bundle(cid, bundle["id"], eng_headers(eng_id)))
    assert bundle["status"] == "WITHDRAWN"
    for m in measures:
        measure = validate_success(
            api.get_measure(cid, bundle["id"], m["id"], eng_headers(eng_id))
        )
        assert measure["status"] == "EXCLUDED"
    facility = validate_success(api.get_facility(cid, facility["id"], lender_headers()))
    assert facility["status"] == "CANCELLED"


def test_terminated_contract_rejects_new_bundle_creation(api):
    """PRD §3.2: "Proposing a bundle — an engineer action requiring the
    bundle in `DRAFT` (`ERR_BUNDLE_NOT_DRAFT`), the contract in `AUDIT` or
    `SCOPED` (`ERR_CONTRACT_NOT_SCOPABLE`)"
    PRD §3.2: "Termination cascades broadly: every non-terminal bundle moves
    to `WITHDRAWN` and its non-terminal measures to `EXCLUDED`, every `DRAFT`
    or `SUBMITTED` financing facility moves to `CANCELLED`, and the contract's
    `version` increments."

    Design: Difficulty/transitive_cascade/contract_termination_cascades_to_bundles_measures_facilities
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, bundle, _m, _f = scoped_contract(
        eng_id, owner_id, facility_name="Termination High"
    )
    cid = contract["id"]
    validate_success(api.terminate_contract(cid, own_headers(owner_id)))
    response = api.propose_bundle(cid, bundle["id"], eng_headers(eng_id))
    # PRD §3.2 names both gates on propose (bundle DRAFT; contract
    # AUDIT/SCOPED) but does not state which fires first when the
    # termination cascade has both violated at once — accept either.
    validate_error_is_one_of(response, [
        ApiErrorId.ERR_CONTRACT_NOT_SCOPABLE.value,
        ApiErrorId.ERR_BUNDLE_NOT_DRAFT.value,
    ])


def test_terminal_contract_rejects_every_further_transition(api):
    """PRD §3.2: "An owner may instead terminate the contract from `AUDIT` or
    `SCOPED`; from any later state termination fails with
    `ERR_CONTRACT_NOT_TERMINABLE`."
    PRD §3.5: "A contract not in `PERFORMANCE` cannot close
    (`ERR_CONTRACT_NOT_IN_PERFORMANCE`)."

    Design: Corner/state_machines/terminal_contract_rejects_every_further_transition
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f = scoped_contract(eng_id, owner_id)
    cid = contract["id"]
    validate_success(api.terminate_contract(cid, own_headers(owner_id)))
    response = api.terminate_contract(cid, own_headers(owner_id))
    validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_TERMINABLE.value, 409)
    response = api.close_contract(cid, own_headers(owner_id))
    validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_IN_PERFORMANCE.value, 409)
    contract = validate_success(api.get_contract(cid, eng_headers(eng_id)))
    assert contract["status"] == "TERMINATED"


def test_bundle_approval_gated_by_contract_term_and_execution_gated_by_facility(api):
    """PRD §3.2: "Execution requires the contract in `SCOPED`
    (`ERR_CONTRACT_NOT_SCOPED`), at least one `MeasureBundle` in `APPROVED`
    (`ERR_NO_APPROVED_BUNDLE`), and a financing facility in `APPROVED` or
    `FUNDING` (`ERR_NO_APPROVED_FINANCING`)"

    Design: Difficulty/cross_entity_state_dependency/bundle_approval_gated_by_contract_term_and_execution_gated_by_facility
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, bundle, _m, facility = scoped_contract(
        eng_id, owner_id, approve_bundle=True, with_approved_facility=False,
        facility_name="East Middle", contract_term_years=15,
        guaranteed_annual_savings_cents=1500000, contract_value_cents=20000000,
        measures=[create_measure_payload(measure_type="HVAC",
                                         installed_cost_cents=1000000,
                                         annual_savings_cents=500000)],
    )
    cid = contract["id"]
    facility = validate_success(
        api.create_facility(cid, create_facility_payload(), eng_headers(eng_id)),
        201,
    )
    validate_success(api.submit_facility(cid, facility["id"], eng_headers(eng_id)))
    # Facility only SUBMITTED: execute is blocked.
    response = api.execute_contract(cid, own_headers(owner_id))
    validate_error(response, ApiErrorId.ERR_NO_APPROVED_FINANCING.value, 409)
    contract = validate_success(api.get_contract(cid, eng_headers(eng_id)))
    assert contract["status"] == "SCOPED"
    validate_success(api.approve_facility(cid, facility["id"], lender_headers()))
    executed = validate_success(api.execute_contract(cid, own_headers(owner_id)))
    assert executed["status"] == "EXECUTED"


def test_execute_succeeds_with_approved_facility_and_locks_baseline(api):
    """PRD §3.2: "Execution cascades: the baseline pinned by
    `executed_baseline_id` transitions from `APPROVED` to `LOCKED`, every
    approved bundle moves to `ACTIVE` (its `INCLUDED` measures remain
    `INCLUDED`), and the contract's `version` increments."

    Design: Difficulty/cross_entity_state_dependency/bundle_approval_gated_by_contract_term_and_execution_gated_by_facility
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, baseline, bundle, measures, facility = scoped_contract(
        eng_id, owner_id, approve_bundle=True, with_approved_facility=True,
        facility_name="East Middle", contract_term_years=15,
        guaranteed_annual_savings_cents=1500000, contract_value_cents=20000000,
        measures=[create_measure_payload(measure_type="HVAC",
                                         installed_cost_cents=1000000,
                                         annual_savings_cents=500000)],
    )
    cid = contract["id"]
    executed = validate_success(api.execute_contract(cid, own_headers(owner_id)))
    assert executed["status"] == "EXECUTED"
    baseline = validate_success(
        api.get_baseline(cid, baseline["id"], eng_headers(eng_id))
    )
    assert baseline["status"] == "LOCKED"
    bundle = validate_success(api.get_bundle(cid, bundle["id"], eng_headers(eng_id)))
    assert bundle["status"] == "ACTIVE"


def test_measure_simple_payback_null_when_annual_savings_zero(api):
    """PRD §3.2: "A measure's own `simple_payback_years` is its
    `installed_cost_cents` divided by its `annual_savings_cents`, or `null`
    when the savings are zero."

    Design: Corner/entities/measure_simple_payback_null_when_annual_savings_zero
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract = create_contract(eng_id)
    cid = contract["id"]
    bundle = validate_success(
        api.create_bundle(cid, create_bundle_payload(name="ZeroSaver"),
                          eng_headers(eng_id)),
        201,
    )
    measure = validate_success(
        api.create_measure(cid, bundle["id"], create_measure_payload(
            measure_type="OTHER", installed_cost_cents=100000,
            annual_savings_cents=0), eng_headers(eng_id)),
        201,
    )
    assert measure["simple_payback_years"] is None
    bundle = validate_success(api.get_bundle(cid, bundle["id"], eng_headers(eng_id)))
    assert bundle["subsidy_pool_cents"] == 0


def test_immediate_consistency_visible_in_same_response(api):
    """PRD §2.9: "Wherever a mutation touches an entity that carries
    `version`, that entity's `version` increments and its `updated_at`
    refreshes; derived fields are recomputed synchronously rather than by any
    background job."
    PRD §3.2: "On approval, every `PROPOSED` measure in the bundle moves to
    `INCLUDED`, the subsidy waterfall runs, and the bundle's `version`
    increments."

    Design: Corner/consistency_model/immediate_consistency_visible_in_same_response
    """
    import pytest

    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f = scoped_contract(
        eng_id, owner_id,
        facility_name="Immediate Consistency School",
        guaranteed_annual_savings_cents=300000, contract_value_cents=3000000,
        measures=[
            create_measure_payload(measure_type="LIGHTING",
                                   installed_cost_cents=100000,
                                   annual_savings_cents=50000),
            create_measure_payload(measure_type="CONTROLS",
                                   installed_cost_cents=400000,
                                   annual_savings_cents=100000),
            create_measure_payload(measure_type="ENVELOPE",
                                   installed_cost_cents=800000,
                                   annual_savings_cents=80000),
        ],
        approve_bundle=False,
    )
    cid = contract["id"]
    bundle_id = _bd["id"]
    approved = validate_success(
        api.approve_bundle(cid, bundle_id, own_headers(owner_id))
    )
    assert approved["blended_payback_years"] == pytest.approx(5.65)
    assert approved["subsidy_pool_cents"] == 50000
    measures = validate_success(
        api.list_measures(cid, bundle_id, eng_headers(eng_id))
    )
    envelope_measure = [m for m in measures
                        if m["measure_type"] == "ENVELOPE"][0]
    measure = validate_success(
        api.get_measure(cid, bundle_id, envelope_measure["id"],
                        eng_headers(eng_id))
    )
    assert measure["subsidy_draw_cents"] == 50000
