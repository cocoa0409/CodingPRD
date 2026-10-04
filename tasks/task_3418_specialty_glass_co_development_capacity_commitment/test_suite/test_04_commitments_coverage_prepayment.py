"""Commitments: creation semantics, coverage tiers, ownership, segregation of
duties, the three-bucket prepayment ledger, and the program-version OCC guard.

All rules cited from PRD sections 2.1, 2.6, and 3.4.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    apply_prepayment,
    assert_prepayment_ledger_conserved,
    countersign_commitment,
    create_commitment,
    create_composition,
    create_device_maker,
    create_program,
    create_program_with_nda,
    create_secured_commitment,
    execute_nda,
    factories,
    get_program_version,
    make_capacity_planner_headers,
    make_device_maker_headers,
    make_finance_controller_headers,
    release_commitment,
    sign_commitment,
    validate_created,
    validate_error,
    validate_success,
    get_success_data,
)

MANAGER = TEST_USERS["program_manager_headers"]


def test_commitment_copies_device_maker_from_program():
    """PRD section 3.4: "Creation copies the program's `device_maker_id` onto
    the commitment, initializes `prepayment_remaining_cents` to the full
    `prepayment_cents` with `prepayment_applied_cents` and
    `prepayment_refunded_cents` at zero, starts the commitment in `PROPOSED`,
    and increments the Program's `version` by 1."

    Design: Corner/entities/commitment_copies_device_maker_from_program
    """
    chain = create_program_with_nda()
    payload = factories.create_commitment_payload(
        chain.program["id"],
        expected_program_version=get_program_version(chain.program["id"]),
    )
    commitment = validate_created(api_client.create_commitment(payload, MANAGER))
    assert commitment["device_maker_id"] == chain.maker["id"]
    assert commitment["status"] == "PROPOSED"
    assert commitment["prepayment_remaining_cents"] == 2500000
    assert commitment["prepayment_applied_cents"] == 0
    assert commitment["prepayment_refunded_cents"] == 0


def test_prepayment_below_minimum_returns_prepayment_insufficient():
    """PRD section 3.4: "the prepayment backing the investment
    (`prepayment_cents`, at least 1000000 cents — CONST.MIN_PREPAYMENT_CENTS —
    with exactly the minimum allowed; a smaller amount fails with
    `ERR_PREPAYMENT_INSUFFICIENT`)" — 999999 cents is one cent below the
    inclusive minimum.

    Design: Corner/errors/prepayment_below_minimum_returns_prepayment_insufficient
    """
    chain = create_program_with_nda()
    payload = factories.create_commitment_payload(
        chain.program["id"],
        expected_program_version=get_program_version(chain.program["id"]),
        prepayment_cents=999999,
    )
    resp = api_client.create_commitment(payload, MANAGER)
    validate_error(resp, ApiErrorId.ERR_PREPAYMENT_INSUFFICIENT)


def test_coverage_exactly_one_allows_secured():
    """PRD section 3.4: "The gate: confirmation succeeds only when base
    coverage is at least 1.0 — exactly 1.0 passes — and fails otherwise with
    `ERR_COMMITMENT_COVERAGE_INSUFFICIENT`." With credit units 1000 and
    committed 11000 against required 12000, base coverage is exactly 1.0, the
    tier is TIER_B, and effective units are floor(12000 * 1.02) = 12240.

    Design: Corner/calculations/coverage_exactly_one_allows_secured
    """
    chain = create_program_with_nda()
    commitment = create_commitment(chain.program, 11000, 12000, 1000000)
    commitment = sign_commitment(commitment, chain.maker)
    commitment = countersign_commitment(commitment)
    resp = api_client.confirm_prepayment(
        commitment["id"], headers=make_finance_controller_headers("fin-01")
    )
    secured = validate_success(resp)
    assert secured["status"] == "SECURED"
    assert secured["coverage_tier"] == "TIER_B"
    assert secured["effective_units"] == 12240


def test_coverage_below_one_returns_coverage_insufficient():
    """PRD section 3.4: "The gate: confirmation succeeds only when base
    coverage is at least 1.0 — exactly 1.0 passes — and fails otherwise with
    `ERR_COMMITMENT_COVERAGE_INSUFFICIENT`." Credit units 1000 plus committed
    5000 over required 12000 gives base coverage 0.5, below the gate.

    Design: Corner/calculations/coverage_below_one_returns_coverage_insufficient
    """
    chain = create_program_with_nda()
    commitment = create_commitment(chain.program, 5000, 12000, 1000000)
    commitment = sign_commitment(commitment, chain.maker)
    commitment = countersign_commitment(commitment)
    resp = api_client.confirm_prepayment(
        commitment["id"], headers=make_finance_controller_headers("fin-01")
    )
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_COVERAGE_INSUFFICIENT)
    commitment = get_success_data(api_client.get_commitment(commitment["id"], MANAGER))
    assert commitment["status"] == "COUNTERSIGNED"


def test_commitment_coverage_evaluation_order_pinned():
    """PRD section 3.4: "Step four: the coverage tier derives from pre-bonus
    base coverage only — `TIER_A` when base coverage is at least 1.2
    (CONST.TIER_A_COVERAGE_MIN), otherwise `TIER_B` when it is at least 1.0
    (CONST.TIER_B_COVERAGE_MIN), otherwise `TIER_C`." PRD section 3.4: "Step
    six: `effective_units` is base units multiplied by one plus the bonus rate,
    floored to a whole unit." With base coverage exactly 1.18 the tier is
    TIER_B even though effective coverage would cross 1.2 if the order were
    inverted; effective_units 14443 locks the pinned order.

    Design: Difficulty/combinatorial_formula/commitment_coverage_evaluation_order_pinned
    """
    chain = create_program_with_nda(maker_name="Gamma Devices", maker_region="APAC")
    create_composition(chain.program, composition_code="GX-500", complexity_multiplier=1.5)
    commitment = create_commitment(chain.program, 11000, 12000, 3160000)
    commitment = sign_commitment(commitment, chain.maker)
    commitment = countersign_commitment(commitment)
    resp = api_client.confirm_prepayment(
        commitment["id"], headers=make_finance_controller_headers("fin-01")
    )
    secured = validate_success(resp)
    # credit_units floor(3160000 / 1000) = 3160; base 11000 + 3160 = 14160;
    # base_coverage 14160 / 12000 = 1.18 exactly -> TIER_B, bonus 0.02.
    assert secured["status"] == "SECURED"
    assert secured["coverage_tier"] == "TIER_B"
    assert secured["effective_units"] == 14443  # floor(14160 * 1.02)


def test_sign_by_other_maker_returns_ownership_mismatch():
    """PRD section 2.1: "Signing a commitment, beginning or recording a
    qualification test, submitting marketing materials, and creating a usage
    report are all ownership-checked writes: if the header does not equal the
    owning maker's `id`, the request fails with `ERR_OWNERSHIP_MISMATCH`
    (HTTP 403)."

    Design: Corner/validations/sign_by_other_maker_returns_ownership_mismatch
    """
    maker_one = create_device_maker(name="Acme Devices", region="US")
    maker_two = create_device_maker(name="Beta Devices", region="EU")
    program = execute_nda(create_program(maker_one, name="Eagle"))
    commitment = create_commitment(program)
    resp = api_client.sign_commitment(
        commitment["id"], headers=make_device_maker_headers(maker_two["id"])
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
    commitment = get_success_data(api_client.get_commitment(commitment["id"], MANAGER))
    assert commitment["status"] == "PROPOSED"


def test_same_user_countersign_and_confirm_returns_segregation_error():
    """PRD section 3.4: "the confirming controller must not be the person who
    countersigned: if `X-User-ID` equals `countersigned_by`, the confirmation
    fails with `ERR_SEGREGATION_OF_DUTIES`." A different controller then
    confirms successfully; 5000/5000 with 2500000 prepayment cents buys 2500
    credit units, so base coverage 1.5 stores TIER_A.

    Design: Corner/validations/same_user_countersign_and_confirm_returns_segregation_error
    """
    chain = create_program_with_nda()
    commitment = create_commitment(chain.program)
    commitment = sign_commitment(commitment, chain.maker)
    validate_success(
        api_client.countersign_commitment(
            commitment["id"], headers=make_capacity_planner_headers("ops-77")
        )
    )
    resp = api_client.confirm_prepayment(
        commitment["id"], headers=make_finance_controller_headers("ops-77")
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    secured = validate_success(
        api_client.confirm_prepayment(
            commitment["id"], headers=make_finance_controller_headers("fin-01")
        )
    )
    assert secured["status"] == "SECURED"
    assert secured["coverage_tier"] == "TIER_A"


def test_apply_over_remaining_returns_prepayment_overapply():
    """PRD section 3.4: "an apply-prepayment request carries `amount_cents`,
    which must be strictly positive — zero or negative fails with
    `ERR_INVALID_REQUEST` — and must not exceed `prepayment_remaining_cents`,
    failing with `ERR_PREPAYMENT_OVERAPPLY` when it does."

    Design: Corner/errors/apply_over_remaining_returns_prepayment_overapply
    """
    chain = create_program_with_nda()
    commitment = create_secured_commitment(chain.program, chain.maker)
    resp = api_client.apply_prepayment(
        commitment["id"],
        factories.apply_prepayment_payload(3000000),
        make_finance_controller_headers("fin-01"),
    )
    validate_error(resp, ApiErrorId.ERR_PREPAYMENT_OVERAPPLY)
    commitment = get_success_data(api_client.get_commitment(commitment["id"], MANAGER))
    assert commitment["prepayment_applied_cents"] == 0
    assert commitment["prepayment_remaining_cents"] == 2500000


def test_prepayment_cents_conserved_under_apply_and_release():
    """PRD section 3.4: "A successful application adds the amount to
    `prepayment_applied_cents` and subtracts it from
    `prepayment_remaining_cents`; the refunded bucket is untouched." PRD
    section 3.4: "Release moves the commitment to `RELEASED`, terminal, refunds
    the ledger by adding `prepayment_remaining_cents` into
    `prepayment_refunded_cents` and zeroing the remaining bucket." The three
    buckets sum to the original prepayment after every step of the pair.

    Design: Difficulty/compensating_invariant/prepayment_cents_conserved_under_apply_and_release
    """
    chain = create_program_with_nda()
    commitment = create_secured_commitment(
        chain.program, chain.maker, 12000, 12000, 2600000
    )
    # credit 2600 -> base 14600 -> coverage 1.2167 -> TIER_A; SECURED.
    after_apply = apply_prepayment(commitment, 1000000, finance_id="fin-02")
    assert after_apply["prepayment_applied_cents"] == 1000000
    assert after_apply["prepayment_remaining_cents"] == 1600000
    assert after_apply["prepayment_refunded_cents"] == 0
    assert_prepayment_ledger_conserved(after_apply)

    after_release = release_commitment(after_apply, reason="program restructure")
    assert after_release["status"] == "RELEASED"
    assert after_release["prepayment_applied_cents"] == 1000000
    assert after_release["prepayment_remaining_cents"] == 0
    assert after_release["prepayment_refunded_cents"] == 1600000
    assert_prepayment_ledger_conserved(after_release)


def test_stale_program_version_returns_412():
    """PRD section 2.6: "If the Program's current `version` does not equal
    `expected_program_version` — because another writer has advanced it since
    the client last read the program — the creation is rejected with
    `ERR_STALE_PROGRAM_VERSION` (HTTP 412)". The first create succeeds and its
    side effect advances the Program's version, so the second create carrying
    the same observed version is stale.

    Design: Corner/cross_cutting_layers/stale_program_version_returns_412
    """
    chain = create_program_with_nda()
    observed = get_program_version(chain.program["id"])
    first = factories.create_commitment_payload(
        chain.program["id"], expected_program_version=observed
    )
    validate_created(api_client.create_commitment(first, MANAGER))
    second = factories.create_commitment_payload(
        chain.program["id"],
        expected_program_version=observed,
        committed_units=6000,
        required_units=6000,
        prepayment_cents=3000000,
    )
    resp = api_client.create_commitment(second, MANAGER)
    validate_error(resp, ApiErrorId.ERR_STALE_PROGRAM_VERSION)
