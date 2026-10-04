"""CreditBatch pricing tiers, idempotency, settle/reverse rules, the two
rounding disciplines, and burn projection variants."""
from test_helpers import (
    ApiErrorId,
    get_batch,
    get_org,
    get_pool,
    get_success_data,
    make_named_user_headers,
    setup_base_chain,
    setup_with_key,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    add_analytics_grant_with_extension,
    create_batch,
    list_batches,
    reverse_batch,
    set_clock,
    settle_batch,
)
from test_helpers.test_users import TEST_USERS

BA_HEADERS = TEST_USERS["billing_admin_headers"]
PA_HEADERS = TEST_USERS["platform_admin_headers"]


def _setup():
    return setup_with_key()


def _user_headers(base):
    return make_named_user_headers(base["user"]["id"])


def test_geocode_tier_boundaries(api):
    """PRD section 3.7: "`GEOCODE`: units 1–100 at 4 credits per unit; units
    101–1000 at 3 per unit; units 1001 and beyond at 2 per unit. Because tier
    bounds are inclusive, a 100-unit geocode batch costs 100 times 4, or 400
    credits, and a 101-unit batch costs 400 plus 1 times 3, or 403 credits."

    Design: Corner/calculations/credit_consumption_each_tier_boundary
    """
    base = _setup()
    headers = _user_headers(base)
    org_id, key_id = base["org"]["id"], base["key"]["id"]
    cases = [(1, 4), (100, 400), (101, 403), (1000, 3100), (1001, 3102)]
    for units, expected in cases:
        resp = create_batch(org_id, key_id, "GEOCODE", units, f"gb-{units}", headers=headers)
        data = validate_success(resp, expected_status=201)
        assert data["provisional_credits"] == expected, (
            f"{units} geocode units: expected provisional {expected}, got {data['provisional_credits']}")


def test_geocode_tier_straddle_is_per_tier_rounded(api):
    """PRD section 3.7: "The platform walks the tier table for the batch's
    `service_kind` in ascending order of tier lower bounds. For each tier, it
    determines how many of the remaining requested units fall inside the tier
    — the smaller of the remaining units and the tier's width, where tier
    upper bounds are inclusive."
    PRD section 3.7: "Each tier's contribution — its unit count times its
    effective rate — is rounded half up to whole credits *individually*, and
    those rounded tier contributions are summed into `provisional_credits`."

    Design: Corner/calculations/credit_consumption_each_tier_boundary
    """
    base = _setup()
    headers = _user_headers(base)
    data = get_success_data(create_batch(
        base["org"]["id"], base["key"]["id"], "GEOCODE", 101, "straddle", headers=headers))
    # per-tier rounding then sum: round(100*4)=400, round(1*3)=3 -> 403 (not 303, not 404)
    assert data["provisional_credits"] == 403


def test_analysis_extension_uplift_applies_per_tier(api):
    """PRD section 3.7: "For an `ANALYSIS` batch carrying an `extension_code`,
    the extension's `additional_credit_rate_per_op` is added to the tier's
    per-unit rate."
    PRD section 3.7: "`ANALYSIS`: units 1–10 at 40 per unit; units 11–100 at
    30 per unit; units 101 and beyond at 20 per unit — each rate plus the
    extension uplift when one is engaged."

    Design: Difficulty/combinatorial_formula/geocode_tier_straddle_with_extension_uplift
    """
    base = _setup()
    add_analytics_grant_with_extension(base["org"]["id"])
    headers = _user_headers(base)
    data = get_success_data(create_batch(
        base["org"]["id"], base["key"]["id"], "ANALYSIS", 11, "an-11",
        headers=headers, extension_code="SPATIAL_ANALYST"))
    # tier1: 10*(40+3)=430; tier2: 1*(30+3)=33 -> 463
    assert data["provisional_credits"] == 463, (
        f"expected 463, got {data['provisional_credits']}")


def test_geocode_straddle_plus_analysis_uplift_reserves_sum(api):
    """PRD section 3.7: "a 101-unit batch costs 400 plus 1 times 3, or 403
    credits."
    PRD section 3.7: "For an `ANALYSIS` batch carrying an `extension_code`,
    the extension's `additional_credit_rate_per_op` is added to the tier's
    per-unit rate."
    PRD section 3.7: "The pool's `reserved_credits` increases by that amount
    and the posture is recomputed."

    Design: Difficulty/combinatorial_formula/geocode_tier_straddle_with_extension_uplift
    """
    base = _setup()
    add_analytics_grant_with_extension(base["org"]["id"])
    headers = _user_headers(base)
    org_id, key_id = base["org"]["id"], base["key"]["id"]
    gc = get_success_data(create_batch(org_id, key_id, "GEOCODE", 101, "gc-101", headers=headers))
    assert gc["provisional_credits"] == 403
    an = get_success_data(create_batch(
        org_id, key_id, "ANALYSIS", 11, "an-11", headers=headers,
        extension_code="SPATIAL_ANALYST"))
    assert an["provisional_credits"] == 463
    pool = get_pool(org_id)
    assert pool["reserved_credits"] == 866


def test_batch_idempotency_replays_and_conflicts(api):
    """PRD section 3.7: "A repeated `idempotency_key` carrying the same
    payload replays the original response with the original batch id; the same
    key carrying a different payload is rejected with
    `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409)."

    Design: Corner/endpoints/credit_batch_create_idempotency_replays_and_conflicts
    """
    base = _setup()
    headers = _user_headers(base)
    org_id, key_id = base["org"]["id"], base["key"]["id"]
    first = get_success_data(create_batch(org_id, key_id, "GEOCODE", 10, "dup-key", headers=headers))
    second = get_success_data(create_batch(org_id, key_id, "GEOCODE", 10, "dup-key", headers=headers))
    assert second["id"] == first["id"], "replay must return the original batch id"
    pool = get_pool(org_id)
    assert pool["reserved_credits"] == 40, (
        f"replay must not double-reserve; reserved={pool['reserved_credits']}")
    resp = create_batch(org_id, key_id, "GEOCODE", 11, "dup-key", headers=headers)
    validate_error(resp, ApiErrorId.ERR_IDEMPOTENCY_CONFLICT)


def test_batch_idempotency_replay_returns_same_provisional(api):
    """PRD section 3.7: "A repeated `idempotency_key` carrying the same
    payload replays the original response with the original batch id; the same
    key carrying a different payload is rejected with
    `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409)."

    Design: Corner/endpoints/credit_batch_create_idempotency_replays_and_conflicts
    """
    base = _setup()
    headers = _user_headers(base)
    org_id, key_id = base["org"]["id"], base["key"]["id"]
    first = get_success_data(create_batch(org_id, key_id, "GEOCODE", 25, "dup-25", headers=headers))
    second = get_success_data(create_batch(org_id, key_id, "GEOCODE", 25, "dup-25", headers=headers))
    assert second["provisional_credits"] == first["provisional_credits"] == 100


def test_settle_twice_and_reverse_after_settle_rejected(api):
    """PRD section 3.7: "The batch must be `PENDING` (else
    `ERR_BATCH_NOT_PENDING`)" and "`SETTLED` and `REVERSED` are the batch's
    terminal states."

    Design: Corner/state_machines/settle_twice_rejected_and_reverse_after_settle_rejected
    """
    base = _setup()
    headers = _user_headers(base)
    batch = get_success_data(create_batch(
        base["org"]["id"], base["key"]["id"], "GEOCODE", 10, "gc-10", headers=headers))
    pool = get_pool(base["org"]["id"])
    get_success_data(settle_batch(batch["id"], pool["version"]))
    pool = get_pool(base["org"]["id"])
    resp = settle_batch(batch["id"], pool["version"])
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_PENDING)
    resp = reverse_batch(batch["id"], pool["version"])
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_PENDING)
    pool = get_pool(base["org"]["id"])
    assert pool["consumed_credits"] == 40
    assert pool["reserved_credits"] == 0


def test_settled_batch_consumes_exactly_once(api):
    """PRD section 3.7: "The pool's `reserved_credits` decreases by the
    batch's `provisional_credits`; the pool's `consumed_credits` increases by
    the `settled_credits`" and "`SETTLED` and `REVERSED` are the batch's
    terminal states."

    Design: Corner/state_machines/settle_twice_rejected_and_reverse_after_settle_rejected
    """
    base = _setup()
    headers = _user_headers(base)
    batch = get_success_data(create_batch(
        base["org"]["id"], base["key"]["id"], "GEOCODE", 10, "gc-10b", headers=headers))
    pool = get_pool(base["org"]["id"])
    get_success_data(settle_batch(batch["id"], pool["version"]))
    pool = get_pool(base["org"]["id"])
    resp = settle_batch(batch["id"], pool["version"])
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_PENDING)
    assert get_pool(base["org"]["id"])["consumed_credits"] == 40


def test_settle_late_fee_diverges_from_provisional(api):
    """PRD section 3.7: "The platform then counts how many whole periods the
    batch has been pending — the organization's `current_period_index` now
    minus its value at batch creation — and multiplies the raw total by one
    plus one tenth per pending period. Settling in the creation period
    therefore charges the raw total exactly; each full period pending adds 10
    percent."
    PRD section 3.7: "a 100-unit geocode batch costs 100 times 4, or 400
    credits".

    Design: Difficulty/dual_variant_calc/credit_settle_late_fee_diverges_from_provisional
    """
    base = _setup()
    headers = _user_headers(base)
    batch = get_success_data(create_batch(
        base["org"]["id"], base["key"]["id"], "GEOCODE", 100, "idem-gc-100", headers=headers))
    assert batch["provisional_credits"] == 400
    set_clock("2026-09-02T00:00:00Z")
    pool = get_pool(base["org"]["id"])
    data = get_success_data(settle_batch(batch["id"], pool["version"]))
    assert data["settled_credits"] == 440, (
        f"one full period pending: round_half_up(400*1.1)=440; got {data['settled_credits']}")
    assert data["settled_credits"] != data["provisional_credits"]
    pool = get_pool(base["org"]["id"])
    assert pool["consumed_credits"] == 440
    assert pool["reserved_credits"] == 0
    assert get_org(base["org"]["id"])["credit_balance"] == 100000 - 440


def test_settle_same_period_charges_raw_total(api):
    """PRD section 3.7: "Settling in the creation period therefore charges the
    raw total exactly; each full period pending adds 10 percent."

    Design: Difficulty/dual_variant_calc/credit_settle_late_fee_diverges_from_provisional
    """
    base = _setup()
    headers = _user_headers(base)
    batch = get_success_data(create_batch(
        base["org"]["id"], base["key"]["id"], "GEOCODE", 100, "idem-gc-same", headers=headers))
    pool = get_pool(base["org"]["id"])
    data = get_success_data(settle_batch(batch["id"], pool["version"]))
    assert data["settled_credits"] == 400


def test_projection_forward_and_chronological_diverge(api):
    """PRD section 3.2: "The default `forward` mode computes the projection as
    the pool's `consumed_credits` plus its `reserved_credits`, plus the
    horizon length multiplied by a per-seat burn summed over the
    organization's `ACTIVE` grants: each in-use seat of a `NAMED_USER` grant
    burns 2 credits per period, each in-use seat of a `CONCURRENT_USE` grant
    burns 5 credits per period, and in-use cores of a `DEPLOYMENT_SERVER`
    grant burn nothing."
    PRD section 3.2: "The `chronological` mode instead replays the
    organization's `SETTLED` batches in creation order; for each batch it
    computes how many periods the batch has been alive — the organization's
    current period index minus the period index at batch creation, floored at
    1 — divides the batch's `settled_credits` by that span, multiplies by the
    horizon length, and then rounds half up the sum of those per-batch
    projections to whole credits."

    Design: Difficulty/dual_variant_calc/credit_projection_forward_vs_chronological
    """
    base = _setup()
    headers = _user_headers(base)
    org_id, key_id = base["org"]["id"], base["key"]["id"]
    # seats_in_use on the NAMED_USER grant is 1 (the accepted user).
    batch = get_success_data(create_batch(org_id, key_id, "GEOCODE", 100, "idem-gc-100", headers=headers))
    pool = get_pool(org_id)
    get_success_data(settle_batch(batch["id"], pool["version"]))
    set_clock("2026-09-03T00:00:00Z")  # period 2

    fwd = get_success_data(api.get_credit_pool_projection(
        org_id, BA_HEADERS, params={"periods": 10, "mode": "forward"}))
    # forward = consumed 400 + reserved 0 + 10 periods * (1 seat * 2) = 420
    assert fwd["projected_credits"] == 420, (
        f"forward projection: expected 420, got {fwd['projected_credits']}")

    chr_ = get_success_data(api.get_credit_pool_projection(
        org_id, BA_HEADERS, params={"periods": 10, "mode": "chronological"}))
    # chronological: batch alive max(1, 2-0)=2 periods; 400/2*10 = 2000
    assert chr_["projected_credits"] == 2000, (
        f"chronological projection: expected 2000, got {chr_['projected_credits']}")
    assert fwd["projected_credits"] != chr_["projected_credits"]


def test_projection_forward_uses_live_seats(api):
    """PRD section 3.2: "The default `forward` mode computes the projection as
    the pool's `consumed_credits` plus its `reserved_credits`, plus the
    horizon length multiplied by a per-seat burn summed over the
    organization's `ACTIVE` grants: each in-use seat of a `NAMED_USER` grant
    burns 2 credits per period".

    Design: Difficulty/dual_variant_calc/credit_projection_forward_vs_chronological
    """
    base = _setup()
    org_id = base["org"]["id"]
    # No batches: consumed 0, reserved 0; one seat in use -> 10 * 2 = 20
    fwd = get_success_data(api.get_credit_pool_projection(
        org_id, BA_HEADERS, params={"periods": 10}))
    assert fwd["projected_credits"] == 20
    assert fwd["mode"] == "forward"


def test_create_then_reverse_conserves_pool(api):
    """PRD section 3.7: "Reversal decreases the pool's `reserved_credits` by
    the batch's `provisional_credits` and nothing else: the compensation
    invariant is that create-then-reverse leaves the pool's fields exactly as
    they were."

    Design: Difficulty/compensating_invariant/batch_create_then_reverse_conserves_pool
    """
    base = _setup()
    headers = _user_headers(base)
    org_id, key_id = base["org"]["id"], base["key"]["id"]
    batch = get_success_data(create_batch(org_id, key_id, "GEOCODE", 250, "gc-inv", headers=headers))
    pool = get_pool(org_id)
    # 250 geocode units: 100*4 + 150*3 = 850
    assert pool["reserved_credits"] == 850
    get_success_data(reverse_batch(batch["id"], pool["version"]))
    pool = get_pool(org_id)
    assert pool["reserved_credits"] == 0
    assert pool["consumed_credits"] == 0
    assert get_org(org_id)["credit_balance"] == 100000


def test_second_reverse_of_reversed_batch_rejected(api):
    """PRD section 3.7: "Reversal moves a batch from `PENDING` to `REVERSED`"
    and "The batch must be `PENDING` (else `ERR_BATCH_NOT_PENDING`)" and
    "`SETTLED` and `REVERSED` are the batch's terminal states."

    Design: Difficulty/compensating_invariant/batch_create_then_reverse_conserves_pool
    """
    base = _setup()
    headers = _user_headers(base)
    org_id, key_id = base["org"]["id"], base["key"]["id"]
    batch = get_success_data(create_batch(org_id, key_id, "GEOCODE", 250, "gc-inv2", headers=headers))
    pool = get_pool(org_id)
    get_success_data(reverse_batch(batch["id"], pool["version"]))
    assert get_batch(batch["id"])["status"] == "REVERSED"
    pool = get_pool(org_id)
    resp = reverse_batch(batch["id"], pool["version"])
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_PENDING)
