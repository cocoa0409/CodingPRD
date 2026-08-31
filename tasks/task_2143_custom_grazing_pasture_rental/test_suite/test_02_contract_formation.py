"""Contract terms, commitment against the carrying budget, and signature."""

import pytest

from test_helpers import (
    SIMPLE_HEAD_DAY_TERMS,
    ApiErrorId,
    assert_grazing_contract,
    create_contract,
    make_cattle_owner_headers,
    make_grazier_headers,
    provision_draft_pasture,
    read_contract,
    read_owner,
    read_pasture,
    setup_capacity_boundary_world,
    setup_delinquency_world,
    setup_north_bench_available,
    setup_parties,
    setup_rest_buffer_world,
    submit_contract,
    validate_error,
    validate_paginated,
    validate_success,
    void_settlement,
)


# ===========================================================================
# Drafting a contract
# ===========================================================================

def test_contract_read_back_carries_both_state_dimensions_and_the_derived_head_days(api):
    """PRD 3.3: "On creation the system derives `committed_head_days` as the committed
    head multiplied by the length of the grazing window in whole days, and stamps the
    contract as `lifecycle_status` `DRAFT` and `billing_status` `UNBILLED`."
    PRD 3.3: "`billing_mode` chooses between the two pricing conventions of the trade,
    `PER_HEAD_PER_DAY` or `PER_POUND_OF_GAIN`, and `rate_cents` — which must be
    positive — is read against whichever was chosen: cents per head-day under the
    first, cents per pound of shrunk gain under the second."

    Design: Corner/entities/get_contract_by_id_returns_the_stored_row_with_both_dimensions
    """
    world = setup_north_bench_available()
    created = create_contract(world.grazier_id, world.owner_id, world.pasture_id)

    resp = api.get_contract(created["id"], make_cattle_owner_headers(world.owner_id))
    contract = validate_success(resp, 200)
    assert_grazing_contract(contract)

    assert contract["grazier_id"] == world.grazier_id
    assert contract["cattle_owner_id"] == world.owner_id
    assert contract["pasture_id"] == world.pasture_id
    assert contract["committed_head_days"] == 13800, "150 head across a 92-day window"
    assert contract["lifecycle_status"] == "DRAFT"
    assert contract["billing_status"] == "UNBILLED"
    assert contract["rate_cents"] == 85
    assert contract["shrink_pct"] == pytest.approx(3.5)


def test_contract_without_a_billing_mode_is_rejected_and_writes_nothing(api):
    """PRD 3.3: "`billing_mode` chooses between the two pricing conventions of the
    trade, `PER_HEAD_PER_DAY` or `PER_POUND_OF_GAIN`, and `rate_cents` — which must be
    positive — is read against whichever was chosen: cents per head-day under the
    first, cents per pound of shrunk gain under the second."
    PRD 2.8: "The body carries every required field, every enum value is a declared
    member of its enumeration, and every numeric field is inside its declared range —
    otherwise `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/create_contract_missing_required_billing_mode_returns_validation
    """
    world = setup_north_bench_available()

    resp = api.create_contract(
        {
            "cattle_owner_id": world.owner_id,
            "pasture_id": world.pasture_id,
            "rate_cents": 85,
            "head_count_committed": 150,
            "head_value_cents": 140000,
            "start_date": "2026-08-10",
            "end_date": "2026-11-10",
            "water_responsibility": "SHARED",
            "fence_responsibility": "GRAZIER",
            "death_loss_terms": "OWNER_BEARS_ALL",
        },
        make_grazier_headers(world.grazier_id),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)

    _, meta = validate_paginated(
        api.list_contracts(
            make_grazier_headers(world.grazier_id), params={"pasture_id": world.pasture_id}
        )
    )
    assert meta["total_count"] == 0, "The rejected draft must not have been stored"


def test_omitted_optional_contract_terms_take_their_declared_defaults(api):
    """PRD 3.3: "The pencil-shrink allowances `shrink_pct` and `out_shrink_pct` —
    applied respectively to the receiving ticket and to interim and weigh-out tickets —
    both default to 0 and must lie between 0 and 10 inclusive. `min_days`, the minimum
    days on feed the owner guarantees, defaults to 60 and may not be negative.
    `treatment_cost_split_pct`, the grazier's percentage share of a routine-protocol
    treatment, defaults to 0 and lies between 0 and 100. `infrastructure_owner_cap_cents`,
    the per-ticket ceiling on the owner's share of a repair, defaults to 100000 cents and
    may not be negative. `death_loss_threshold_pct` defaults to 2.0 and lies between 0 and
    100, but is only ever read when the liability regime calls for it."

    Design: Corner/entities/create_contract_omitting_optional_fields_applies_declared_defaults
    """
    world = setup_north_bench_available()

    resp = api.create_contract(
        {
            "cattle_owner_id": world.owner_id,
            "pasture_id": world.pasture_id,
            "billing_mode": "PER_HEAD_PER_DAY",
            "rate_cents": 100,
            "head_count_committed": 20,
            "head_value_cents": 120000,
            "start_date": "2026-08-10",
            "end_date": "2026-11-10",
            "water_responsibility": "GRAZIER",
            "fence_responsibility": "GRAZIER",
            "death_loss_terms": "OWNER_BEARS_ALL",
        },
        make_grazier_headers(world.grazier_id),
    )
    contract = validate_success(resp, 201)

    assert contract["min_days"] == 60
    assert contract["shrink_pct"] == pytest.approx(0)
    assert contract["out_shrink_pct"] == pytest.approx(0)
    assert contract["treatment_cost_split_pct"] == 0
    assert contract["infrastructure_owner_cap_cents"] == 100000
    assert contract["death_loss_threshold_pct"] == pytest.approx(2.0)
    assert contract["committed_head_days"] == 1840


def test_submitting_a_contract_books_its_head_days_against_the_pasture(api):
    """PRD 3.3: "On creation the system derives `committed_head_days` as the committed
    head multiplied by the length of the grazing window in whole days, and stamps the
    contract as `lifecycle_status` `DRAFT` and `billing_status` `UNBILLED`."
    PRD 2.9: "Its `capacity_utilization_pct` is the booked head-days divided by the
    rated head-day budget, multiplied by 100 and rounded half up to two decimal places;
    when the rated budget is 0 the utilization is reported as 0 rather than being
    treated as an error."

    Design: Corner/entities/contract_committed_head_days_is_derived_from_head_and_window
    """
    world = setup_north_bench_available()
    contract = create_contract(world.grazier_id, world.owner_id, world.pasture_id)
    assert contract["committed_head_days"] == 13800

    submit_contract(contract["id"], world.grazier_id)

    pasture = read_pasture(world.pasture_id, world.grazier_id)
    assert pasture["committed_head_days"] == 13800
    assert pasture["capacity_utilization_pct"] == pytest.approx(66.45, abs=0.005)
    assert pasture["grazing_posture"] == "OPEN"


def test_submitting_against_a_draft_pasture_reports_the_availability_failure(api):
    """PRD 3.3: "The grazier who owns the contract submits it; the pasture must be in
    `operational_status` `AVAILABLE` or the submission fails with
    `ERR_PASTURE_NOT_AVAILABLE`; and the pasture's already-booked head-days plus this
    contract's own committed head-days must not exceed the pasture's `rated_head_days`."
    PRD 2.8: "Rules are evaluated in a fixed ascending priority order and the **first**
    failing rule determines the response; no later rule is evaluated once one has
    failed."

    Design: Corner/validations/submitting_a_contract_on_a_draft_pasture_returns_pasture_not_available
    """
    world = setup_parties()
    pasture = provision_draft_pasture(world)
    contract = create_contract(
        world.grazier_id, world.owner_id, pasture["id"], **SIMPLE_HEAD_DAY_TERMS
    )

    resp = api.submit_contract(contract["id"], make_grazier_headers(world.grazier_id))
    validate_error(resp, ApiErrorId.ERR_PASTURE_NOT_AVAILABLE.value, 409)

    assert read_contract(contract["id"], world.grazier_id)["lifecycle_status"] == "DRAFT"
    assert read_pasture(pasture["id"], world.grazier_id)["committed_head_days"] == 0


def test_submitting_the_same_contract_twice_does_not_double_book_the_pasture(api):
    """PRD 3.3: "Submitting the draft moves it `DRAFT → PENDING_SIGNATURE` and is where
    the pasture's carrying budget is enforced."
    PRD 2.8: "The target resource is in a state from which the requested transition is
    declared — otherwise `ERR_PASTURE_INVALID_STATE`, `ERR_CONTRACT_INVALID_STATE`,
    `ERR_LOT_INVALID_STATE`, `ERR_TREATMENT_INVALID_STATE`,
    `ERR_DEATH_LOSS_INVALID_STATE`, `ERR_TICKET_INVALID_STATE` or
    `ERR_SETTLEMENT_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/submitting_a_contract_twice_rejects_the_second_call
    """
    world = setup_north_bench_available()
    contract = create_contract(world.grazier_id, world.owner_id, world.pasture_id)
    submit_contract(contract["id"], world.grazier_id)

    resp = api.submit_contract(contract["id"], make_grazier_headers(world.grazier_id))
    validate_error(resp, ApiErrorId.ERR_CONTRACT_INVALID_STATE.value, 409)

    assert read_contract(contract["id"], world.grazier_id)["lifecycle_status"] == "PENDING_SIGNATURE"
    pasture = read_pasture(world.pasture_id, world.grazier_id)
    assert pasture["committed_head_days"] == 13800, "The rejected resubmit booked nothing"
    assert pasture["capacity_utilization_pct"] == pytest.approx(66.45, abs=0.005)


def test_signing_a_contract_still_in_draft_is_refused(api):
    """PRD 3.3: "Signature belongs to the counterparty. The `CattleOwner` named on the
    contract signs it, supplying a `signature_ref` which is stored on the contract, and
    the move is `PENDING_SIGNATURE → ACTIVE`."
    PRD 3.3: "A suspended contract cannot be signed, because signature is only declared
    from `PENDING_SIGNATURE`; an attempt from any other lifecycle state is rejected with
    `ERR_CONTRACT_INVALID_STATE`."

    Design: Corner/state_machines/sign_a_contract_still_in_draft_returns_contract_invalid_state
    """
    world = setup_north_bench_available()
    contract = create_contract(world.grazier_id, world.owner_id, world.pasture_id)
    version_before = contract["version"]

    resp = api.sign_contract(
        contract["id"], {"signature_ref": "SIG-EARLY"},
        make_cattle_owner_headers(world.owner_id),
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACT_INVALID_STATE.value, 409)

    unchanged = read_contract(contract["id"], world.grazier_id)
    assert unchanged["lifecycle_status"] == "DRAFT"
    assert unchanged["version"] == version_before, "A rejected sign moves no version"


# ===========================================================================
# The carrying-budget boundary
# ===========================================================================

def test_committing_exactly_the_rated_budget_is_accepted(api):
    """PRD 3.3: "The comparison is generous at the boundary — a total exactly equal to
    the rated budget is accepted, and only a total strictly greater than it is rejected,
    with `ERR_CAPACITY_EXCEEDED`."
    PRD 2.9: "Its `capacity_utilization_pct` is the booked head-days divided by the
    rated head-day budget, multiplied by 100 and rounded half up to two decimal places;
    when the rated budget is 0 the utilization is reported as 0 rather than being
    treated as an error."

    Design: Difficulty/boundary_precision_check/contract_submit_capacity_equality_passes_and_one_head_day_over_fails
    """
    world = setup_capacity_boundary_world()
    assert read_pasture(world.pasture_id, world.grazier_id)["rated_head_days"] == 1000
    assert world.contract_exact["committed_head_days"] == 1000

    resp = api.submit_contract(
        world.contract_exact["id"], make_grazier_headers(world.grazier_id)
    )
    submitted = validate_success(resp, 200)
    assert submitted["lifecycle_status"] == "PENDING_SIGNATURE"

    pasture = read_pasture(world.pasture_id, world.grazier_id)
    assert pasture["committed_head_days"] == 1000
    assert pasture["capacity_utilization_pct"] == pytest.approx(100.00, abs=0.005)
    assert pasture["grazing_posture"] == "OPEN", (
        "Utilization of exactly 100 percent is not strictly greater than 100"
    )


def test_one_head_day_beyond_the_rated_budget_is_refused(api):
    """PRD 3.3: "The comparison is generous at the boundary — a total exactly equal to
    the rated budget is accepted, and only a total strictly greater than it is rejected,
    with `ERR_CAPACITY_EXCEEDED`."
    PRD 2.9: "Its `committed_head_days` is the sum of the booked head-days of the
    contracts on that pasture whose `lifecycle_status` is `PENDING_SIGNATURE`, `ACTIVE`
    or `EARLY_REMOVAL_PENDING`; contracts in `DRAFT`, `SUSPENDED`, `COMPLETED` or
    `TERMINATED` are excluded from that sum."

    Design: Difficulty/boundary_precision_check/contract_submit_capacity_equality_passes_and_one_head_day_over_fails
    """
    world = setup_capacity_boundary_world()
    submit_contract(world.contract_exact["id"], world.grazier_id)

    resp = api.submit_contract(
        world.contract_over["id"], make_grazier_headers(world.grazier_id)
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED.value, 409)

    assert read_contract(world.contract_over["id"], world.grazier_id)["lifecycle_status"] == "DRAFT"
    assert read_pasture(world.pasture_id, world.grazier_id)["committed_head_days"] == 1000


# ===========================================================================
# The grazing-window rest buffer
# ===========================================================================

def test_a_thirteen_day_rest_gap_is_refused(api):
    """PRD 3.3: "They also conflict when they merely crowd each other: the pasture is
    entitled to a rest period of 14 days between one herd leaving and the next arriving,
    so if the new window starts on or after the other's end, the gap between them in
    whole days must be at least 14, and symmetrically if the new window ends on or
    before the other's start, that gap must also be at least 14. A gap of exactly 14
    days is accepted; a gap of 13 days is not. Any conflict is reported as
    `ERR_GRAZING_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/pasture_window_half_open_plus_fourteen_day_rest_buffer
    """
    world = setup_rest_buffer_world()

    resp = api.sign_contract(
        world.contract_b["id"], {"signature_ref": "SIG-KB"},
        make_cattle_owner_headers(world.owner_id),
    )
    validate_error(resp, ApiErrorId.ERR_GRAZING_WINDOW_OVERLAP.value, 409)

    assert read_contract(world.contract_b["id"], world.grazier_id)["lifecycle_status"] == (
        "PENDING_SIGNATURE"
    )
    assert read_contract(world.contract_a["id"], world.grazier_id)["lifecycle_status"] == "ACTIVE"


def test_a_fourteen_day_rest_gap_is_accepted(api):
    """PRD 3.3: "They also conflict when they merely crowd each other: the pasture is
    entitled to a rest period of 14 days between one herd leaving and the next arriving,
    so if the new window starts on or after the other's end, the gap between them in
    whole days must be at least 14, and symmetrically if the new window ends on or
    before the other's start, that gap must also be at least 14. A gap of exactly 14
    days is accepted; a gap of 13 days is not. Any conflict is reported as
    `ERR_GRAZING_WINDOW_OVERLAP`."
    PRD 2.9: "Its `committed_head_days` is the sum of the booked head-days of the
    contracts on that pasture whose `lifecycle_status` is `PENDING_SIGNATURE`, `ACTIVE`
    or `EARLY_REMOVAL_PENDING`; contracts in `DRAFT`, `SUSPENDED`, `COMPLETED` or
    `TERMINATED` are excluded from that sum."

    Design: Difficulty/resource_temporal_overlap/pasture_window_half_open_plus_fourteen_day_rest_buffer
    """
    world = setup_rest_buffer_world()

    resp = api.sign_contract(
        world.contract_c["id"], {"signature_ref": "SIG-KC"},
        make_cattle_owner_headers(world.owner_id),
    )
    signed = validate_success(resp, 200)
    assert signed["lifecycle_status"] == "ACTIVE"

    assert read_contract(world.contract_a["id"], world.grazier_id)["lifecycle_status"] == "ACTIVE"
    pasture = read_pasture(world.pasture_id, world.grazier_id)
    assert pasture["committed_head_days"] == 4280, (
        "One ACTIVE window plus two still-pending windows are all booked"
    )


# ===========================================================================
# Signature gated by the counterparty's credit standing
# ===========================================================================

def test_signing_is_refused_while_the_owner_is_delinquent(api):
    """PRD 3.3: "The second check is fiscal: the signing owner's `credit_status` must be
    `GOOD_STANDING`, or the signature is refused with `ERR_OWNER_DELINQUENT`."
    PRD 3.1: "From those two numbers the system derives `credit_status`, which is
    `DELINQUENT` when the open balance is strictly greater than the credit limit and
    `GOOD_STANDING` otherwise; a balance exactly equal to the limit leaves the owner in
    `GOOD_STANDING`."

    Design: Difficulty/cross_entity_state_dependency/contract_sign_gated_by_cattle_owner_credit_status
    """
    world = setup_delinquency_world(issue=True, clean_second_contract=True)

    owner = read_owner(world.owner_id, world.grazier_id)
    assert owner["open_settlement_balance_cents"] == 184000
    assert owner["credit_status"] == "DELINQUENT"

    resp = api.sign_contract(
        world.contract_k9["id"], {"signature_ref": "SIG-K9"},
        make_cattle_owner_headers(world.owner_id),
    )
    validate_error(resp, ApiErrorId.ERR_OWNER_DELINQUENT.value, 409)

    assert read_contract(world.contract_k9["id"], world.grazier_id)["lifecycle_status"] == (
        "PENDING_SIGNATURE"
    )


def test_the_same_signature_succeeds_once_the_owner_is_back_in_good_standing(api):
    """PRD 3.3: "The second check is fiscal: the signing owner's `credit_status` must be
    `GOOD_STANDING`, or the signature is refused with `ERR_OWNER_DELINQUENT`."
    PRD 3.9: "Voiding backs the charge out of the ledger: the owner's
    `open_settlement_balance_cents` and `credit_status` are recomputed without it, and
    if that returns the owner to `GOOD_STANDING`, every contract of theirs in
    `SUSPENDED` moves back to `PENDING_SIGNATURE`."

    Design: Difficulty/cross_entity_state_dependency/contract_sign_gated_by_cattle_owner_credit_status
    """
    world = setup_delinquency_world(issue=True, clean_second_contract=True)
    void_settlement(world.settlement_id, world.grazier_id, "Corrected certified scale ticket")

    owner = read_owner(world.owner_id, world.grazier_id)
    assert owner["open_settlement_balance_cents"] == 0
    assert owner["credit_status"] == "GOOD_STANDING"

    resp = api.sign_contract(
        world.contract_k9["id"], {"signature_ref": "SIG-K9"},
        make_cattle_owner_headers(world.owner_id),
    )
    signed = validate_success(resp, 200)
    assert signed["lifecycle_status"] == "ACTIVE"


# ===========================================================================
# Competing failures on the same signature request
# ===========================================================================

def test_a_suspended_contract_reports_the_state_failure_not_the_fiscal_one(api):
    """PRD 2.8: "Rules are evaluated in a fixed ascending priority order and the
    **first** failing rule determines the response; no later rule is evaluated once one
    has failed."
    PRD 3.3: "A suspended contract cannot be signed, because signature is only declared
    from `PENDING_SIGNATURE`; an attempt from any other lifecycle state is rejected with
    `ERR_CONTRACT_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/sign_on_suspended_contract_state_beats_owner_delinquent_fiscal
    """
    world = setup_delinquency_world(issue=True)

    resp = api.sign_contract(
        world.contract_k7["id"], {"signature_ref": "SIG-K7"},
        make_cattle_owner_headers(world.owner_id),
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACT_INVALID_STATE.value, 409)


def test_the_suspended_signature_attempt_leaves_both_failing_conditions_standing(api):
    """PRD 3.3: "When an owner's `credit_status` flips from `GOOD_STANDING` to
    `DELINQUENT`, every contract of that owner sitting in `PENDING_SIGNATURE` is moved
    by the system to `SUSPENDED`, each such move incrementing that contract's
    `version`."
    PRD 3.3: "The second check is fiscal: the signing owner's `credit_status` must be
    `GOOD_STANDING`, or the signature is refused with `ERR_OWNER_DELINQUENT`."

    Design: Difficulty/priority_pair_validation_conflict/sign_on_suspended_contract_state_beats_owner_delinquent_fiscal
    """
    world = setup_delinquency_world(issue=True)

    assert read_contract(world.contract_k7["id"], world.grazier_id)["lifecycle_status"] == (
        "SUSPENDED"
    ), "The delinquency cascade must have suspended the pending contract"
    assert read_owner(world.owner_id, world.grazier_id)["credit_status"] == "DELINQUENT"

    api.sign_contract(
        world.contract_k7["id"], {"signature_ref": "SIG-K7"},
        make_cattle_owner_headers(world.owner_id),
    )

    after = read_contract(world.contract_k7["id"], world.grazier_id)
    assert after["lifecycle_status"] == "SUSPENDED", "The refused signature changed nothing"
    assert read_owner(world.owner_id, world.grazier_id)["credit_status"] == "DELINQUENT"


def test_a_window_conflict_outranks_the_owners_delinquency(api):
    """PRD 2.8: "Rules are evaluated in a fixed ascending priority order and the
    **first** failing rule determines the response; no later rule is evaluated once one
    has failed."
    PRD 2.8: "The contract's grazing window does not conflict with a live window on the
    same pasture — otherwise `ERR_GRAZING_WINDOW_OVERLAP`. Applies to contract
    signature."
    PRD 2.8: "The contract's cattle owner is in good credit standing — otherwise
    `ERR_OWNER_DELINQUENT`. Applies to contract signature."

    Design: Difficulty/priority_pair_validation_conflict/sign_window_overlap_temporal_beats_owner_delinquent_fiscal
    """
    world = setup_delinquency_world(issue=True, overlapping_contract=True)

    resp = api.sign_contract(
        world.contract_k8["id"], {"signature_ref": "SIG-K8"},
        make_cattle_owner_headers(world.owner_id),
    )
    validate_error(resp, ApiErrorId.ERR_GRAZING_WINDOW_OVERLAP.value, 409)


def test_the_conflicting_contract_stays_pending_while_the_owner_stays_delinquent(api):
    """PRD 3.3: "Two windows conflict when they overlap, meaning the new window starts
    before the other ends and the other starts before the new one ends."
    PRD 2.9: "Its `committed_head_days` is the sum of the booked head-days of the
    contracts on that pasture whose `lifecycle_status` is `PENDING_SIGNATURE`, `ACTIVE`
    or `EARLY_REMOVAL_PENDING`; contracts in `DRAFT`, `SUSPENDED`, `COMPLETED` or
    `TERMINATED` are excluded from that sum."

    Design: Difficulty/priority_pair_validation_conflict/sign_window_overlap_temporal_beats_owner_delinquent_fiscal
    """
    world = setup_delinquency_world(issue=True, overlapping_contract=True)

    api.sign_contract(
        world.contract_k8["id"], {"signature_ref": "SIG-K8"},
        make_cattle_owner_headers(world.owner_id),
    )

    assert read_contract(world.contract_k8["id"], world.grazier_id)["lifecycle_status"] == (
        "PENDING_SIGNATURE"
    )
    assert read_owner(world.owner_id, world.grazier_id)["credit_status"] == "DELINQUENT"
    assert read_pasture(world.home_field["id"], world.grazier_id)["committed_head_days"] == 2755
