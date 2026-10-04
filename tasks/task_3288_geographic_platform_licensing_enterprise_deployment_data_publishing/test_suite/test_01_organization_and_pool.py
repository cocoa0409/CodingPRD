"""Organization creation, credit posture thresholds, and derived-field
reconciliation between the pool and the organization."""
from test_helpers import (
    ApiErrorId,
    BA_HEADERS,
    LA_HEADERS,
    PA_HEADERS,
    TEST_DEFAULTS,
    assert_organization,
    assert_pool_invariants,
    create_credit_batch_payload,
    create_credit_pool_payload,
    create_org_payload,
    get_org,
    get_pool,
    get_success_data,
    make_named_user_headers,
    reverse_batch,
    settle_batch,
    setup_base_chain,
    setup_org,
    setup_with_key,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import create_batch


def test_org_create_returns_common_fields_and_provisioning_status(api):
    """PRD section 3.1: "A new organization starts in `PROVISIONING` status
    with a `credit_balance` of 0, a `seat_overage_fee_accrued_cents` of 0, and
    `current_period_index` 0."
    PRD section 2.4: "`id` (string): a unique, server-generated identifier
    formatted as a bare UUID, with no type prefix."

    Design: Corner/entities/org_create_returns_common_fields_and_provisioning_status
    """
    from test_helpers.fixtures import set_clock
    set_clock()
    resp = api.create_org(create_org_payload(), PA_HEADERS)
    data = validate_success(resp, expected_status=201)
    assert_organization(data)
    assert data["status"] == "PROVISIONING"
    assert data["version"] == 1
    assert data["current_period_index"] == 0
    assert data["credit_balance"] == 0
    assert data["seat_overage_fee_accrued_cents"] == 0


def test_org_credit_balance_ignores_client_input(api):
    """PRD section 2.11: "Unknown body fields are ignored rather than
    rejected."
    PRD section 3.1: "A new organization starts in `PROVISIONING` status with
    a `credit_balance` of 0, a `seat_overage_fee_accrued_cents` of 0, and
    `current_period_index` 0."

    Design: Corner/entities/org_credit_balance_is_computed_and_input_ignored
    """
    from test_helpers.fixtures import set_clock
    set_clock()
    payload = create_org_payload(name="Sneaky Org")
    payload["credit_balance"] = 999999
    resp = api.create_org(payload, PA_HEADERS)
    data = validate_success(resp, expected_status=201)
    assert data["credit_balance"] == 0, (
        f"client-supplied credit_balance must be ignored; got {data['credit_balance']}")


def test_org_credit_balance_mirrors_pool_capacity_after_creation(api):
    """PRD section 2.7: "the pool's available credits are its
    `capacity_credits` minus its `consumed_credits` minus its
    `reserved_credits`." and "The Organization's `credit_balance` mirrors the
    available-credits value exactly and is recomputed on the same trigger as
    the posture."

    Design: Corner/entities/org_credit_balance_is_computed_and_input_ignored
    """
    from test_helpers.fixtures import set_clock
    set_clock()
    org = get_success_data(api.create_org(create_org_payload(name="Sneaky Org"), PA_HEADERS))
    get_success_data(api.create_credit_pool(
        create_credit_pool_payload(org["id"], capacity_credits=7000), BA_HEADERS))
    after = get_org(org["id"])
    assert after["credit_balance"] == 7000


def test_posture_ok_at_exact_threshold(api):
    """PRD section 2.7: "The `LOW_CREDIT` boundary is strict: when available
    equals `low_credit_threshold_credits` exactly, the posture is `OK`, not
    `LOW_CREDIT`."

    Design: Difficulty/boundary_precision_check/posture_threshold_exact_equality_is_ok
    """
    base = setup_with_key(
        setup_base_chain(capacity=1350, pool_overrides={"low_credit_threshold_credits": 500}))
    user = base["user"]
    headers = make_named_user_headers(user["id"])
    resp = create_batch(
        base["org"]["id"], base["key"]["id"], "GEOCODE", 250, "gc-250",
        headers=headers)
    get_success_data(resp)
    pool = get_pool(base["org"]["id"])
    assert pool["reserved_credits"] == 850, f"expected reserved 850, got {pool['reserved_credits']}"
    # available = 1350 - 850 = 500 == threshold -> OK (strict less-than)
    assert pool["posture"] == "OK", f"expected OK at available==threshold, got {pool['posture']}"


def test_posture_low_credit_below_threshold(api):
    """PRD section 2.7: "available strictly less than
    `low_credit_threshold_credits` → `LOW_CREDIT`" and "The `LOW_CREDIT`
    boundary is strict: when available equals `low_credit_threshold_credits`
    exactly, the posture is `OK`, not `LOW_CREDIT`."

    Design: Difficulty/boundary_precision_check/posture_threshold_exact_equality_is_ok
    """
    base = setup_with_key(
        setup_base_chain(capacity=1350, pool_overrides={"low_credit_threshold_credits": 500}))
    headers = make_named_user_headers(base["user"]["id"])
    get_success_data(create_batch(base["org"]["id"], base["key"]["id"], "GEOCODE", 250, "gc-250", headers=headers))
    get_success_data(create_batch(base["org"]["id"], base["key"]["id"], "STORAGE", 1, "st-1", headers=headers))
    pool = get_pool(base["org"]["id"])
    # available = 1350 - 851 = 499 < 500 -> LOW_CREDIT
    assert pool["posture"] == "LOW_CREDIT", f"expected LOW_CREDIT at available 499, got {pool['posture']}"
    org = get_org(base["org"]["id"])
    assert org["credit_balance"] == 499


def test_exhausted_pool_blocks_create_and_settle_but_reverse_succeeds(api):
    """PRD section 3.2: "creation of a new batch refuses when the pool's
    available credits — capacity minus consumed minus reserved — are less than
    the batch's provisional reservation (`ERR_INSUFFICIENT_CREDITS`, HTTP
    402)."
    PRD section 3.2: "Settlement of a pending batch refuses to proceed while
    the posture is `EXHAUSTED` or `OVERDRAWN` (`ERR_CREDIT_POOL_EXHAUSTED`,
    HTTP 402)."
    PRD section 3.7: "Reversal moves a batch from `PENDING` to `REVERSED`,
    either at a `BillingAdmin`'s request or as system compensation when an
    organization terminates or a published item is retracted." and "Reversal
    decreases the pool's `reserved_credits` by the batch's
    `provisional_credits` and nothing else".

    Design: Corner/calculations/posture_exhausted_blocks_settle_but_not_reverse
    """
    base = setup_with_key(setup_base_chain(capacity=400))
    headers = make_named_user_headers(base["user"]["id"])
    batch = get_success_data(create_batch(
        base["org"]["id"], base["key"]["id"], "GEOCODE", 100, "gc-ex", headers=headers))
    pool = get_pool(base["org"]["id"])
    assert pool["posture"] == "EXHAUSTED", f"expected EXHAUSTED at available 0, got {pool['posture']}"
    pool_v = pool["version"]

    # New reservation refused
    resp = create_batch(base["org"]["id"], base["key"]["id"], "STORAGE", 1, "st-ex", headers=headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDITS)

    # Settle refused
    resp = settle_batch(batch["id"], pool_v)
    validate_error(resp, ApiErrorId.ERR_CREDIT_POOL_EXHAUSTED)

    # Reverse succeeds and restores the pool
    resp = reverse_batch(batch["id"], pool_v)
    validate_success(resp)
    pool = get_pool(base["org"]["id"])
    assert pool["reserved_credits"] == 0
    # available = 400 < 500 (default threshold) -> LOW_CREDIT
    assert pool["posture"] == "LOW_CREDIT"


def test_derived_fields_reconcile_across_reserve_and_settle(api):
    """PRD section 2.7: "the pool's available credits are its
    `capacity_credits` minus its `consumed_credits` minus its
    `reserved_credits`." and "The Organization's `credit_balance` mirrors the
    available-credits value exactly and is recomputed on the same trigger as
    the posture."
    PRD section 3.7: "The pool's `reserved_credits` decreases by the batch's
    `provisional_credits`; the pool's `consumed_credits` increases by the
    `settled_credits`".

    Design: Corner/cross_cutting_layers/derived_field_reconciles_after_reverse_and_settle
    """
    base = setup_with_key(setup_base_chain(capacity=1000))
    headers = make_named_user_headers(base["user"]["id"])
    batch = get_success_data(create_batch(
        base["org"]["id"], base["key"]["id"], "GEOCODE", 150, "dr-1", headers=headers))
    # 150 geocode units: 100*4 + 50*3 = 550 reserved; available = 1000-550 = 450
    org = get_org(base["org"]["id"])
    assert org["credit_balance"] == 450
    pool = get_pool(base["org"]["id"])
    assert pool["posture"] == "LOW_CREDIT"
    assert_pool_invariants(pool, org)

    get_success_data(settle_batch(batch["id"], pool["version"]))
    org = get_org(base["org"]["id"])
    pool = get_pool(base["org"]["id"])
    # settled in period 0: settled == 550, consumed replaces reserved 1:1
    assert pool["consumed_credits"] == 550
    assert pool["reserved_credits"] == 0
    assert org["credit_balance"] == 450
    assert_pool_invariants(pool, org)


def test_derived_fields_reconcile_after_reverse(api):
    """PRD section 3.7: "Reversal decreases the pool's `reserved_credits` by
    the batch's `provisional_credits` and nothing else: the compensation
    invariant is that create-then-reverse leaves the pool's fields exactly as
    they were."

    Design: Corner/cross_cutting_layers/derived_field_reconciles_after_reverse_and_settle
    """
    base = setup_with_key(setup_base_chain(capacity=1000))
    headers = make_named_user_headers(base["user"]["id"])
    batch = get_success_data(create_batch(
        base["org"]["id"], base["key"]["id"], "GEOCODE", 150, "dr-2", headers=headers))
    pool = get_pool(base["org"]["id"])
    get_success_data(reverse_batch(batch["id"], pool["version"]))
    pool = get_pool(base["org"]["id"])
    org = get_org(base["org"]["id"])
    assert pool["reserved_credits"] == 0
    assert pool["consumed_credits"] == 0
    assert org["credit_balance"] == 1000
    assert_pool_invariants(pool, org)
