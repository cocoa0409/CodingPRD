"""Financing facility payment variants, coverage gate, and draws."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_approved_baseline,
    add_bundle_with_measures,
    construction_contract,
    create_contract,
    create_draw_payload,
    create_facility_payload,
    create_measure_payload,
    eng_headers,
    lender_headers,
    make_actor_ids,
    own_headers,
    reset_clock,
    scoped_contract,
    set_clock,
    validate_error,
    validate_success,
)


def _scoped(api, eng_id, owner_id, **contract_overrides):
    return scoped_contract(
        eng_id, owner_id,
        measures=[create_measure_payload(measure_type="HVAC",
                                         installed_cost_cents=1000000,
                                         annual_savings_cents=500000)],
        **contract_overrides,
    )


def _create_and_submit_facility(api, cid, eng_id, **facility_overrides):
    facility = validate_success(
        api.create_facility(cid, create_facility_payload(**facility_overrides),
                            eng_headers(eng_id)),
        201,
    )
    return validate_success(
        api.submit_facility(cid, facility["id"], eng_headers(eng_id))
    )


def test_lease_vs_bond_annual_payment_diverge_on_identical_principal(api):
    """PRD §3.3: "For a `LEASE`, the payment is the plain annuity on the note
    rate: with the rate expressed as a fraction and the term in years, the
    payment is the principal times the rate, divided by one minus
    one-plus-the-rate raised to the negative term — rounded half-up to integer
    cents"
    PRD §3.3: "For a `BOND`, the same annuity is computed and then multiplied
    by the bond fee uplift of 1.02 before rounding, so identical inputs yield
    a higher payment than a lease."

    Design: Difficulty/dual_variant_calc/lease_vs_bond_annual_payment_diverge_on_identical_principal
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f = _scoped(
        api, eng_id, owner_id, facility_name="East Middle",
        contract_term_years=15, guaranteed_annual_savings_cents=1500000,
        contract_value_cents=20000000,
    )
    cid = contract["id"]
    lease = _create_and_submit_facility(
        api, cid, eng_id, facility_type="LEASE", principal_cents=10000000,
        annual_rate_pct=5.0, term_years=10,
    )
    bond = _create_and_submit_facility(
        api, cid, eng_id, facility_type="BOND", principal_cents=10000000,
        annual_rate_pct=5.0, term_years=10,
    )
    assert lease["annual_payment_cents"] == 1295046
    assert bond["annual_payment_cents"] == 1320947
    assert bond["annual_payment_cents"] > lease["annual_payment_cents"]


def test_coverage_ratio_computed_at_four_decimal_places(api):
    """PRD §3.3: "The `coverage_ratio` is then the contract's
    `guaranteed_annual_savings_cents` divided by the computed payment, rounded
    to 4 decimal places."

    Design: Difficulty/dual_variant_calc/lease_vs_bond_annual_payment_diverge_on_identical_principal
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f = _scoped(
        api, eng_id, owner_id, facility_name="East Middle",
        contract_term_years=15, guaranteed_annual_savings_cents=1500000,
        contract_value_cents=20000000,
    )
    cid = contract["id"]
    lease = _create_and_submit_facility(
        api, cid, eng_id, facility_type="LEASE", principal_cents=10000000,
        annual_rate_pct=5.0, term_years=10,
    )
    bond = _create_and_submit_facility(
        api, cid, eng_id, facility_type="BOND", principal_cents=10000000,
        annual_rate_pct=5.0, term_years=10,
    )
    assert lease["coverage_ratio"] == pytest.approx(1.1583, abs=1e-4)
    assert bond["coverage_ratio"] == pytest.approx(1.1355, abs=1e-4)


def test_coverage_ratio_exactly_one_approves_below_one_rejects(api):
    """PRD §3.3: "Approval requires the facility in `SUBMITTED`
    (`ERR_FACILITY_NOT_SUBMITTED`) and a `coverage_ratio` of at least 1.0000;
    a facility whose guaranteed savings would not fully cover its annual
    payment is rejected with `ERR_COVERAGE_BELOW_ONE` (HTTP 422)."
    PRD §3.3: "when the rate is exactly zero, the payment is simply the
    principal divided by the term, rounded half-up"

    Design: Difficulty/boundary_precision_check/coverage_ratio_exactly_one_approves_below_one_rejects
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract1, _b1, _bd1, _m1, _f1 = _scoped(
        api, eng_id, owner_id, facility_name="Boundary One",
        guaranteed_annual_savings_cents=120000,
    )
    contract2, _b2, _bd2, _m2, _f2 = _scoped(
        api, eng_id, owner_id, facility_name="Boundary Two",
        guaranteed_annual_savings_cents=119900,
    )
    fac1 = _create_and_submit_facility(
        api, contract1["id"], eng_id, facility_type="LEASE",
        principal_cents=1200000, annual_rate_pct=0.0, term_years=10,
    )
    fac2 = _create_and_submit_facility(
        api, contract2["id"], eng_id, facility_type="LEASE",
        principal_cents=1200000, annual_rate_pct=0.0, term_years=10,
    )
    assert fac1["annual_payment_cents"] == 120000
    assert fac1["coverage_ratio"] == pytest.approx(1.0, abs=1e-4)
    assert fac2["coverage_ratio"] == pytest.approx(0.9992, abs=1e-4)
    approved = validate_success(
        api.approve_facility(contract1["id"], fac1["id"], lender_headers())
    )
    assert approved["status"] == "APPROVED"
    response = api.approve_facility(contract2["id"], fac2["id"], lender_headers())
    validate_error(response, ApiErrorId.ERR_COVERAGE_BELOW_ONE.value, 422)
    reread = validate_success(
        api.get_facility(contract2["id"], fac2["id"], lender_headers())
    )
    assert reread["status"] == "SUBMITTED"


def test_coverage_boundary_is_inclusive_not_strict(api):
    """PRD §3.3: "a `coverage_ratio` of at least 1.0000; a facility whose
    guaranteed savings would not fully cover its annual payment is rejected
    with `ERR_COVERAGE_BELOW_ONE` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/coverage_ratio_exactly_one_approves_below_one_rejects
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f = _scoped(
        api, eng_id, owner_id, guaranteed_annual_savings_cents=120000,
    )
    facility = _create_and_submit_facility(
        api, contract["id"], eng_id, facility_type="LEASE",
        principal_cents=1200000, annual_rate_pct=0.0, term_years=10,
    )
    # coverage exactly at the threshold approves; one cent less of guarantee
    # would push it below.
    assert facility["annual_payment_cents"] == 120000
    assert facility["coverage_ratio"] >= 1.0
    approved = validate_success(
        api.approve_facility(contract["id"], facility["id"], lender_headers())
    )
    assert approved["status"] == "APPROVED"


def test_state_gate_beats_fiscal_gate_on_facility_approve(api):
    """PRD §2.6: "then whether the target entity's current state even permits
    the requested transition, and only then the business rules"
    PRD §3.3: "Approval requires the facility in `SUBMITTED`
    (`ERR_FACILITY_NOT_SUBMITTED`)"

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_fiscal_on_facility_approve_and_payoff
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f = _scoped(
        api, eng_id, owner_id, facility_name="East Middle",
        contract_term_years=15, guaranteed_annual_savings_cents=1500000,
        contract_value_cents=20000000,
    )
    cid = contract["id"]
    facility = validate_success(
        api.create_facility(
            cid,
            create_facility_payload(facility_type="LEASE",
                                    principal_cents=20000000,
                                    annual_rate_pct=5.0, term_years=10),
            eng_headers(eng_id),
        ),
        201,
    )
    # Coverage would be below 1.0 once submitted, but the facility is DRAFT:
    # the state gate fires first.
    response = api.approve_facility(cid, facility["id"], lender_headers())
    validate_error(response, ApiErrorId.ERR_FACILITY_NOT_SUBMITTED.value, 409)
    reread = validate_success(api.get_facility(cid, facility["id"], lender_headers()))
    assert reread["status"] == "DRAFT"


def test_draft_facility_approve_rejected_regardless_of_coverage(api):
    """PRD §3.3: "A `LenderOfficer` approves a submitted facility. Approval
    requires the facility in `SUBMITTED` (`ERR_FACILITY_NOT_SUBMITTED`)"

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_fiscal_on_facility_approve_and_payoff
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f = _scoped(api, eng_id, owner_id)
    cid = contract["id"]
    facility = validate_success(
        api.create_facility(cid, create_facility_payload(), eng_headers(eng_id)),
        201,
    )
    response = api.approve_facility(cid, facility["id"], lender_headers())
    validate_error(response, ApiErrorId.ERR_FACILITY_NOT_SUBMITTED.value, 409)
    reread = validate_success(api.get_facility(cid, facility["id"], lender_headers()))
    assert reread["status"] == "DRAFT"


def test_financing_draw_immutable_no_update_endpoint(api):
    """PRD §3.3: "Draws carry only `id` and `created_at` — they have no
    `version` and no `updated_at`."
    PRD §3.3: "An engineer requests a draw with an `amount_cents` (greater
    than zero) and a free-text `purpose`; the draw is born `REQUESTED`."

    Design: Corner/entities/financing_draw_immutable_no_update_endpoint
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, facility, _ph = construction_contract(
        eng_id, owner_id
    )
    cid = contract["id"]
    draw = validate_success(
        api.create_draw(cid, facility["id"],
                        create_draw_payload(amount_cents=100000,
                                            purpose="deposit"),
                        eng_headers(eng_id)),
        201,
    )
    assert draw["status"] == "REQUESTED"
    assert draw.get("id")
    assert draw.get("created_at")
    assert "version" not in draw
    assert "updated_at" not in draw


def test_draw_exceeds_available_rejected(api):
    """PRD §3.3: "A lender approves a requested draw only while the facility
    is in `FUNDING` (`ERR_FACILITY_NOT_FUNDING` otherwise, and
    `ERR_DRAW_NOT_REQUESTED` if the draw itself has left `REQUESTED`), and
    only if the `amount_cents` fits within the remaining availability: the
    facility's `principal_cents` minus its `drawn_cents` minus the sum of
    every other approved-but-not-yet-released draw on the facility. An
    over-availability draw is rejected with `ERR_DRAW_EXCEEDS_AVAILABLE`
    (HTTP 422)."

    Design: Corner/errors/draw_exceeds_available_rejected
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, facility, _ph = construction_contract(
        eng_id, owner_id
    )
    cid, fid = contract["id"], facility["id"]
    d1 = validate_success(
        api.create_draw(cid, fid, create_draw_payload(amount_cents=400000,
                                                      purpose="d1"),
                        eng_headers(eng_id)),
        201,
    )
    validate_success(api.approve_draw(cid, fid, d1["id"], lender_headers()))
    d2 = validate_success(
        api.create_draw(cid, fid, create_draw_payload(amount_cents=700000,
                                                      purpose="d2"),
                        eng_headers(eng_id)),
        201,
    )
    response = api.approve_draw(cid, fid, d2["id"], lender_headers())
    validate_error(response, ApiErrorId.ERR_DRAW_EXCEEDS_AVAILABLE.value, 422)
    draws = validate_success(api.list_draws(cid, fid, lender_headers()))
    d2_now = [d for d in draws if d["id"] == d2["id"]][0]
    assert d2_now["status"] == "REQUESTED"


def test_financing_drawn_conserved_across_approve_release_reject(api):
    """PRD §3.3: "Releasing an approved draw (`ERR_DRAW_NOT_APPROVED` if it
    is not in `APPROVED`) moves it to `RELEASED` and adds its amount to the
    facility's `drawn_cents`; a lender may instead reject a requested draw
    outright."

    Design: Difficulty/compensating_invariant/financing_drawn_conserved_across_approve_release_reject
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, facility, _ph = construction_contract(
        eng_id, owner_id
    )
    cid, fid = contract["id"], facility["id"]
    d1 = validate_success(
        api.create_draw(cid, fid, create_draw_payload(amount_cents=400000,
                                                      purpose="mobilization"),
                        eng_headers(eng_id)),
        201,
    )
    d2 = validate_success(
        api.create_draw(cid, fid, create_draw_payload(amount_cents=300000,
                                                      purpose="equipment deposit"),
                        eng_headers(eng_id)),
        201,
    )
    validate_success(api.approve_draw(cid, fid, d1["id"], lender_headers()))
    validate_success(api.release_draw(cid, fid, d1["id"], lender_headers()))
    validate_success(api.reject_draw(cid, fid, d2["id"], lender_headers()))
    facility = validate_success(api.get_facility(cid, fid, lender_headers()))
    assert facility["drawn_cents"] == 400000
    draws = validate_success(api.list_draws(cid, fid, lender_headers()))
    by_id = {d["id"]: d for d in draws}
    assert by_id[d1["id"]]["status"] == "RELEASED"
    assert by_id[d2["id"]]["status"] == "REJECTED"


def test_draw_headroom_boundary_after_release(api):
    """PRD §3.3: "only if the `amount_cents` fits within the remaining
    availability: the facility's `principal_cents` minus its `drawn_cents`
    minus the sum of every other approved-but-not-yet-released draw on the
    facility. An over-availability draw is rejected with
    `ERR_DRAW_EXCEEDS_AVAILABLE` (HTTP 422)."

    Design: Difficulty/compensating_invariant/financing_drawn_conserved_across_approve_release_reject
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, facility, _ph = construction_contract(
        eng_id, owner_id
    )
    cid, fid = contract["id"], facility["id"]
    d1 = validate_success(
        api.create_draw(cid, fid, create_draw_payload(amount_cents=400000,
                                                      purpose="mobilization"),
                        eng_headers(eng_id)),
        201,
    )
    validate_success(api.approve_draw(cid, fid, d1["id"], lender_headers()))
    validate_success(api.release_draw(cid, fid, d1["id"], lender_headers()))
    # Headroom is exactly 600000: a draw of 600000 approves, 600001 rejects.
    d_ok = validate_success(
        api.create_draw(cid, fid, create_draw_payload(amount_cents=600000,
                                                      purpose="full headroom"),
                        eng_headers(eng_id)),
        201,
    )
    approved = validate_success(
        api.approve_draw(cid, fid, d_ok["id"], lender_headers())
    )
    assert approved["status"] == "APPROVED"
    d_over = validate_success(
        api.create_draw(cid, fid, create_draw_payload(amount_cents=600001,
                                                      purpose="over headroom"),
                        eng_headers(eng_id)),
        201,
    )
    # The previously approved 600000 draw now occupies headroom, so the
    # 600001 draw is over availability.
    response = api.approve_draw(cid, fid, d_over["id"], lender_headers())
    validate_error(response, ApiErrorId.ERR_DRAW_EXCEEDS_AVAILABLE.value, 422)


def test_payoff_before_term_elapsed_rejected(api):
    """PRD §3.3: "A facility in `FUNDING` is paid off by an `OwnerRep` once
    its term has fully elapsed — the logical clock must have reached the
    `guarantee_start_date` plus `term_years` years, otherwise the payoff is
    rejected with `ERR_FACILITY_TERM_NOT_ELAPSED` (HTTP 422)"

    Design: Corner/validations/payoff_before_term_elapsed_rejected
    """
    from test_helpers import performance_contract
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, facility, _ph = performance_contract(
        eng_id, owner_id, end_year_1=False
    )
    cid, fid = contract["id"], facility["id"]
    assert facility["status"] == "FUNDING"
    set_clock("2031-10-01T00:00:00Z")  # guarantee_start 2026-10-01 + 5y of a 10y term
    response = api.payoff_facility(cid, fid, own_headers(owner_id))
    validate_error(response, ApiErrorId.ERR_FACILITY_TERM_NOT_ELAPSED.value, 422)
    set_clock("2036-10-01T00:00:00Z")  # guarantee_start + term_years elapsed
    paid = validate_success(api.payoff_facility(cid, fid, own_headers(owner_id)))
    assert paid["status"] == "PAID_OFF"
