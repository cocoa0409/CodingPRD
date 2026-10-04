"""Return intake and risk-scoring tests: ACTIVE-config variant selection,
the five-signal weighted score with its interaction term, tier boundaries,
the IP PIN filing gate and its priority over the duplicate constraint, score
clamping, and filter-model config governance.

PRD sections 2.8 and 3.4.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_filter_hold,
    create_active_config,
    create_enrolled_taxpayer,
    create_filter_model_config_payload,
    create_return_payload,
    create_taxpayer,
    create_victim_taxpayer,
    get_return,
    get_return_hold,
    make_taxpayer_headers,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
ANALYST = TEST_USERS["fraud_analyst_headers"]


def _file(api, taxpayer_id, **overrides):
    """File a return as the taxpayer themselves (entity-backed identity)."""
    return api.file_tax_return(
        create_return_payload(taxpayer_id, **overrides),
        make_taxpayer_headers(taxpayer_id),
    )


# ─── ACTIVE-config variant selection ─────────────────

def _setup_model_variant_world(api):
    """MV-A (w_bank 20) ACTIVE and one RT filing under it; then MV-B
    (w_bank 60) created and activated, retiring MV-A."""
    set_clock("2027-02-01T00:00:00Z")
    create_active_config(
        model_version="MV-A", w_bank_product=20,
        gray_zone_threshold=25, hold_threshold=50,
    )
    taxpayer_a = create_taxpayer()
    resp_a = _file(
        api, taxpayer_a["id"], claimed_refund_cents=0,
        bank_product="REFUND_TRANSFER", bank_account_fingerprint="fp-aaa",
    )
    return_a = validate_success(resp_a, 201)

    created_b = validate_success(
        api.create_filter_model_config(
            create_filter_model_config_payload(
                model_version="MV-B", w_bank_product=60,
                gray_zone_threshold=25, hold_threshold=50,
            ),
            ADMIN,
        ),
        201,
    )
    validate_success(
        api.activate_filter_model_config(created_b["id"], ADMIN), 200
    )
    taxpayer_b = create_taxpayer()
    return taxpayer_a, return_a, taxpayer_b


def test_active_config_stamps_score_and_model_version(api):
    """PRD section 3.4: "The bank-product signal adds `w_bank_product` when
    the return's `bank_product` is `REFUND_TRANSFER`."
    PRD section 3.4: "the return's `risk_score` records the computed score
    and its `scoring_model_version` stamps the `model_version` of the config
    that scored it — so activating a new config changes the scores of
    identical payloads from that moment on, while previously scored returns
    keep their original stamp."

    Design: Difficulty/dual_variant_calc/risk_score_model_variant_divergence
    """
    _taxpayer_a, return_a, _taxpayer_b = _setup_model_variant_world(api)

    assert return_a["risk_score"] == 20
    assert return_a["status"] == "FILTER_PASSED"
    assert return_a["scoring_model_version"] == "MV-A"


def test_identical_payload_rescored_after_config_swap(api):
    """PRD section 3.4: "the return's `risk_score` records the computed score
    and its `scoring_model_version` stamps the `model_version` of the config
    that scored it — so activating a new config changes the scores of
    identical payloads from that moment on, while previously scored returns
    keep their original stamp."
    PRD section 3.4: "A score that reaches the config's `hold_threshold`
    moves the return to `FILTER_HELD` and opens a `FilterHold` in zone
    `FULL`."

    Design: Difficulty/dual_variant_calc/risk_score_model_variant_divergence
    """
    _taxpayer_a, return_a, taxpayer_b = _setup_model_variant_world(api)

    resp_b = _file(
        api, taxpayer_b["id"], claimed_refund_cents=0,
        bank_product="REFUND_TRANSFER", bank_account_fingerprint="fp-bbb",
    )
    return_b = validate_success(resp_b, 201)
    assert return_b["risk_score"] == 60
    assert return_b["status"] == "FILTER_HELD"
    assert return_b["scoring_model_version"] == "MV-B"

    reread_a = get_return(return_a["id"])
    assert reread_a["scoring_model_version"] == "MV-A"
    assert reread_a["status"] == "FILTER_PASSED"


# ─── Interaction term and tier selection ─────────────

def _setup_victim_rt_filing(api):
    """MV-INT (victim 15, delta 10, bank 20, interaction 10, gray 25, hold
    50) ACTIVE; a VICTIM_FLAGGED + ENROLLED taxpayer files a 100000-cent
    REFUND_TRANSFER return presenting their ACTIVE pin."""
    set_clock("2027-02-10T00:00:00Z")
    create_active_config(
        model_version="MV-INT", w_victim_flagged=15, w_refund_delta=10,
        w_bank_product=20, interaction_bonus=10,
        gray_zone_threshold=25, hold_threshold=50,
    )
    taxpayer, _report, pin = create_victim_taxpayer(prior_year_refund_cents=0)
    resp = _file(
        api, taxpayer["id"], claimed_refund_cents=100000,
        ip_pin_submitted=pin["pin_value"],
        bank_product="REFUND_TRANSFER", bank_account_fingerprint="fp-int",
    )
    return validate_success(resp, 201)


def test_interaction_bonus_pushes_gray_score_into_full_hold(api):
    """PRD section 3.4: "Finally, when the taxpayer is `VICTIM_FLAGGED` and
    the return routes through a `REFUND_TRANSFER` bank product at the same
    time, the config's `interaction_bonus` is added on top."
    PRD section 3.4: "A score that reaches the config's `hold_threshold`
    moves the return to `FILTER_HELD` and opens a `FilterHold` in zone
    `FULL`."

    Design: Difficulty/combinatorial_formula/risk_score_interaction_and_tier_selection
    """
    rtn = _setup_victim_rt_filing(api)
    # 15 victim + 10 one refund-delta step + 20 bank product + 10 interaction.
    assert rtn["risk_score"] == 55
    assert rtn["status"] == "FILTER_HELD"

    hold = get_return_hold(rtn["id"])
    assert_filter_hold(hold)
    assert hold["zone"] == "FULL"


def test_hold_records_score_model_version_and_reason_codes(api):
    """PRD section 3.4: "A return holds at most one `FilterHold`: the hold
    copies the intake `risk_score` and `model_version`, records its `zone`,
    lists machine `reason_codes` drawn from the signals that contributed —
    `REFUND_DELTA`, `BANK_PRODUCT`, `VICTIM_FLAGGED`, and `INTERACTION` for
    intake holds, with `SCHEME_CONFIRMED` reserved for cascade-created holds
    — starts with `priority_review` false, and opens in `OPEN`."

    Design: Difficulty/combinatorial_formula/risk_score_interaction_and_tier_selection
    """
    rtn = _setup_victim_rt_filing(api)
    hold = get_return_hold(rtn["id"])
    assert_filter_hold(hold)
    assert hold["risk_score"] == 55
    assert hold["model_version"] == "MV-INT"
    assert set(hold["reason_codes"]) == {
        "VICTIM_FLAGGED", "REFUND_DELTA", "BANK_PRODUCT", "INTERACTION",
    }
    assert hold["priority_review"] is False
    assert hold["status"] == "OPEN"


# ─── Tier boundary precision ─────────────────────────

def _setup_boundary_world():
    """MV-BND (w_bank 49, w_delta 1, gray 10, hold 50) ACTIVE; three fresh
    taxpayers with prior_year_refund_cents 0."""
    set_clock("2027-02-01T00:00:00Z")
    create_active_config(
        model_version="MV-BND", w_refund_delta=1, w_bank_product=49,
        gray_zone_threshold=10, hold_threshold=50,
    )
    return create_taxpayer(), create_taxpayer(), create_taxpayer()


def test_score_equal_hold_threshold_held_full(api):
    """PRD section 3.4: "A score that reaches the config's `hold_threshold`
    moves the return to `FILTER_HELD` and opens a `FilterHold` in zone
    `FULL`."

    Design: Difficulty/boundary_precision_check/score_exactly_at_hold_threshold
    """
    _tp_g, tp_h, _tp_p = _setup_boundary_world()
    # 49 bank + 1 x one refund-delta step == 50 == hold_threshold.
    resp = _file(
        api, tp_h["id"], claimed_refund_cents=100000,
        bank_product="REFUND_TRANSFER", bank_account_fingerprint="fp-h50",
    )
    rtn = validate_success(resp, 201)
    assert rtn["risk_score"] == 50
    assert rtn["status"] == "FILTER_HELD"
    assert get_return_hold(rtn["id"])["zone"] == "FULL"


def test_score_below_thresholds_lands_gray_or_passes(api):
    """PRD section 3.4: "A score at or above the `gray_zone_threshold` but
    still below the `hold_threshold` also moves the return to `FILTER_HELD`,
    with the hold in zone `GRAY`. A score below the `gray_zone_threshold`
    moves the return to `FILTER_PASSED` with no hold."

    Design: Difficulty/boundary_precision_check/score_exactly_at_hold_threshold
    """
    tp_g, _tp_h, tp_p = _setup_boundary_world()

    resp_g = _file(
        api, tp_g["id"], claimed_refund_cents=0,
        bank_product="REFUND_TRANSFER", bank_account_fingerprint="fp-g49",
    )
    rtn_g = validate_success(resp_g, 201)
    assert rtn_g["risk_score"] == 49
    assert rtn_g["status"] == "FILTER_HELD"
    assert get_return_hold(rtn_g["id"])["zone"] == "GRAY"

    resp_p = _file(api, tp_p["id"], claimed_refund_cents=0, bank_product="NONE")
    rtn_p = validate_success(resp_p, 201)
    assert rtn_p["risk_score"] == 0
    assert rtn_p["status"] == "FILTER_PASSED"
    assert get_return_hold(rtn_p["id"]) is None


# ─── IP PIN filing gate vs duplicate constraint ──────

def _setup_enrolled_with_first_return(api):
    """Pass-through config; taxpayer ENROLLED for 2026; first 2026 return
    filed with the correct pin and FILTER_PASSED."""
    set_clock("2027-02-01T00:00:00Z")
    create_active_config(model_version="MV-PR1")
    taxpayer, pin = create_enrolled_taxpayer()
    first = validate_success(
        _file(
            api, taxpayer["id"], claimed_refund_cents=40000,
            ip_pin_submitted=pin["pin_value"], bank_product="NONE",
        ),
        201,
    )
    assert first["status"] == "FILTER_PASSED"
    return taxpayer, pin, first


def _file_second_with_wrong_pin(api, taxpayer, pin):
    wrong_pin = "000000" if pin["pin_value"] != "000000" else "111111"
    return _file(
        api, taxpayer["id"], claimed_refund_cents=90000,
        ip_pin_submitted=wrong_pin, bank_product="NONE",
    )


def test_enrolled_second_filing_with_wrong_pin_rejected(api):
    """PRD section 2.8: "Every request is validated against the following
    checks in strict priority order; the first failing check determines the
    response, so a higher-priority rejection always masks lower-priority
    ones."
    PRD section 2.8 check 7: "For return intake only: an `ENROLLED` filer
    must present `ip_pin_submitted` (absent yields `ERR_IP_PIN_REQUIRED`,
    HTTP 422) and it must equal the `ACTIVE` pin for that taxpayer and tax
    year (mismatch yields `ERR_IP_PIN_MISMATCH`, HTTP 422)".
    PRD section 2.8 check 8: "a second non-terminal return for the same
    taxpayer TIN and tax year yields `ERR_DUPLICATE_RETURN` (HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/ip_pin_safety_beats_duplicate_constraint
    """
    taxpayer, pin, _first = _setup_enrolled_with_first_return(api)
    resp = _file_second_with_wrong_pin(api, taxpayer, pin)
    validate_error(resp, ApiErrorId.ERR_IP_PIN_MISMATCH)


def test_mismatch_rejection_leaves_first_return_untouched(api):
    """PRD section 3.4: "If the filer's `ip_pin_enrollment` is `ENROLLED`,
    the filing must present `ip_pin_submitted` — its absence yields
    `ERR_IP_PIN_REQUIRED` (HTTP 422) — and the presented value must equal the
    `ACTIVE` pin for that taxpayer and tax year, else `ERR_IP_PIN_MISMATCH`
    (HTTP 422); filers who are `NOT_ENROLLED` or `OPTED_OUT` carry no pin
    requirement."
    PRD section 3.4: "At most one non-terminal return may exist per taxpayer
    TIN and tax year: a filing that collides with a live earlier return is
    rejected with `ERR_DUPLICATE_RETURN` (HTTP 409) — and this rejection is
    itself a fraud signal, so the system still auto-creates an
    `IdentityTheftReport` with `source` `DUPLICATE_DETECTION` and
    `created_by_user_id` `system` against that taxpayer, even though the
    filing fails." (The mismatch rejection is not that duplicate path.)

    Design: Difficulty/priority_pair_validation_conflict/ip_pin_safety_beats_duplicate_constraint
    """
    taxpayer, pin, first = _setup_enrolled_with_first_return(api)
    resp = _file_second_with_wrong_pin(api, taxpayer, pin)
    validate_error(resp, ApiErrorId.ERR_IP_PIN_MISMATCH)

    rows, meta = validate_paginated(
        api.list_tax_returns(ANALYST, params={"taxpayer_id": taxpayer["id"]})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["status"] == "FILTER_PASSED"


# ─── Payload-shape and computed-field corners ────────

def test_return_create_invalid_enum_rejected(api):
    """PRD section 3.4: "a `filing_status` of `SINGLE`, `MARRIED_JOINT`, or
    `HEAD_OF_HOUSEHOLD`".
    PRD section 2.8 check 14: "Required fields present, enum values inside
    their declared sets, well-formed dates and TINs (a `tin` is exactly 9
    digits), appointment `end_at` strictly after `start_at`, `tax_year` equal
    to 2026 unless an operation states otherwise, and integers within range —
    violations yield `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/return_create_invalid_enum_rejected
    """
    create_active_config(model_version="MV-ENUM")
    taxpayer = create_taxpayer()
    resp = _file(
        api, taxpayer["id"], claimed_refund_cents=1000,
        filing_status="MARRIED", bank_product="NONE",
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_return_create_computed_risk_score_input_ignored(api):
    """PRD section 3.4: "Only after all validations pass and the claims and
    any conflicts exist does the filter model score the return, using the
    weights of the single `ACTIVE` `FilterModelConfig`."
    PRD section 3.4: "the return's `risk_score` records the computed score".

    Design: Corner/entities/return_create_computed_risk_score_input_ignored
    """
    create_active_config(model_version="MV-CI")
    taxpayer = create_taxpayer()
    resp = _file(
        api, taxpayer["id"], claimed_refund_cents=5000,
        bank_product="NONE", risk_score=99,
    )
    data = validate_success(resp, 201)
    assert data["risk_score"] == 0
    assert data["status"] == "FILTER_PASSED"


# ─── Score arithmetic corners ────────────────────────

def test_risk_score_capped_at_100(api):
    """PRD section 3.4: "The raw sum is clamped to an integer score no lower
    than 0 and no higher than 100, the score cap."

    Design: Corner/calculations/risk_score_capped_at_100
    """
    set_clock("2027-02-01T00:00:00Z")
    create_active_config(
        model_version="MV-CAP", w_bank_product=200,
        gray_zone_threshold=1, hold_threshold=50,
    )
    taxpayer = create_taxpayer()
    resp = _file(
        api, taxpayer["id"], claimed_refund_cents=0,
        bank_product="REFUND_TRANSFER", bank_account_fingerprint="fp-cap",
    )
    rtn = validate_success(resp, 201)
    assert rtn["risk_score"] == 100
    assert rtn["status"] == "FILTER_HELD"


def test_refund_delta_steps_capped_at_3(api):
    """PRD section 3.4: "The refund-delta signal measures the absolute
    difference between the return's `claimed_refund_cents` and the taxpayer's
    `prior_year_refund_cents`, divides it into whole steps of 100000 cents
    (that is, $1,000 per step) using floor division, and caps the result at 3
    steps; the config's `w_refund_delta` weight is applied once per step."

    Design: Corner/calculations/refund_delta_steps_capped_at_3
    """
    set_clock("2027-02-01T00:00:00Z")
    create_active_config(
        model_version="MV-STP", w_refund_delta=10,
        gray_zone_threshold=25, hold_threshold=50,
    )
    taxpayer = create_taxpayer(prior_year_refund_cents=0)
    resp = _file(
        api, taxpayer["id"], claimed_refund_cents=1000000, bank_product="NONE",
    )
    rtn = validate_success(resp, 201)
    # floor(1000000 / 100000) == 10 steps, capped at 3 -> score 30.
    assert rtn["risk_score"] == 30
    assert rtn["status"] == "FILTER_HELD"
    assert get_return_hold(rtn["id"])["zone"] == "GRAY"


# ─── Intake preconditions ────────────────────────────

def test_filing_without_active_config_rejected(api):
    """PRD section 3.4: "Filing requires an `ACTIVE` filter model config;
    when no config is `ACTIVE` the filing is rejected with
    `ERR_CONFIG_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/errors/filing_without_active_config_rejected
    """
    taxpayer = create_taxpayer()
    resp = _file(api, taxpayer["id"], claimed_refund_cents=1000,
                 bank_product="NONE")
    validate_error(resp, ApiErrorId.ERR_CONFIG_NOT_ACTIVE)


def test_enrolled_filing_without_pin_rejected(api):
    """PRD section 3.4: "If the filer's `ip_pin_enrollment` is `ENROLLED`,
    the filing must present `ip_pin_submitted` — its absence yields
    `ERR_IP_PIN_REQUIRED` (HTTP 422) — and the presented value must equal the
    `ACTIVE` pin for that taxpayer and tax year, else `ERR_IP_PIN_MISMATCH`
    (HTTP 422); filers who are `NOT_ENROLLED` or `OPTED_OUT` carry no pin
    requirement."

    Design: Corner/validations/enrolled_filing_without_pin_rejected
    """
    set_clock("2027-02-01T00:00:00Z")
    create_active_config(model_version="MV-PIN")
    taxpayer, _pin = create_enrolled_taxpayer()
    resp = _file(api, taxpayer["id"], claimed_refund_cents=10000,
                 bank_product="NONE")
    validate_error(resp, ApiErrorId.ERR_IP_PIN_REQUIRED)


def test_intake_response_immediately_reflects_scored_state(api):
    """PRD section 3.4: "The score selects the return's tier, and `RECEIVED`
    is transient — the creation response already shows the post-scoring
    state."

    Design: Corner/consistency_model/intake_response_immediately_reflects_scored_state
    """
    set_clock("2027-02-01T00:00:00Z")
    create_active_config(
        model_version="MV-IMM", w_bank_product=60,
        gray_zone_threshold=25, hold_threshold=50,
    )
    taxpayer = create_taxpayer()
    resp = _file(
        api, taxpayer["id"], claimed_refund_cents=60000,
        bank_product="REFUND_TRANSFER", bank_account_fingerprint="fp-imm",
    )
    created = validate_success(resp, 201)
    assert created["status"] == "FILTER_HELD"
    assert created["risk_score"] == 60

    reread = get_return(created["id"])
    assert reread["status"] == created["status"]
    assert reread["risk_score"] == created["risk_score"]


# ─── Config governance ───────────────────────────────

def test_config_activate_retires_previous(api):
    """PRD section 3.4: "Activating a config requires it to be `DRAFT`
    (activating anything else yields `ERR_CONFIG_NOT_DRAFT`, HTTP 409);
    activation moves it to `ACTIVE` and retires the previously `ACTIVE`
    config to `RETIRED`, so exactly one config is `ACTIVE` at any moment."

    Design: Corner/state_machines/config_activate_retires_previous
    """
    cfg_a = validate_success(
        api.create_filter_model_config(
            create_filter_model_config_payload(model_version="MV-R1"), ADMIN
        ),
        201,
    )
    validate_success(api.activate_filter_model_config(cfg_a["id"], ADMIN), 200)

    cfg_b = validate_success(
        api.create_filter_model_config(
            create_filter_model_config_payload(model_version="MV-R2"), ADMIN
        ),
        201,
    )
    activated_b = validate_success(
        api.activate_filter_model_config(cfg_b["id"], ADMIN), 200
    )
    assert activated_b["status"] == "ACTIVE"

    reread_a = validate_success(api.get_filter_model_config(cfg_a["id"], ADMIN), 200)
    assert reread_a["status"] == "RETIRED"

    # Re-activating the now-RETIRED cfg_a is ambiguous in PRD: section 3.4
    # says "activating anything else yields ERR_CONFIG_NOT_DRAFT", while
    # section 2.10 lists RETIRED among the terminal states whose every
    # request "is rejected with ERR_ALREADY_TERMINAL" (section 2.8 check 6).
    # Both rules are verbatim and cover this exact case, so accept either.
    reactivate = api.activate_filter_model_config(cfg_a["id"], ADMIN)
    validate_error_is_one_of(
        reactivate,
        [ApiErrorId.ERR_CONFIG_NOT_DRAFT, ApiErrorId.ERR_ALREADY_TERMINAL],
    )


def test_config_threshold_order_rejected(api):
    """PRD section 3.4: "The thresholds must be coherent —
    `gray_zone_threshold` strictly below `hold_threshold` — both at creation
    and again at activation, or the request is rejected with
    `ERR_THRESHOLD_ORDER_INVALID` (HTTP 422)."

    Design: Corner/validations/config_threshold_order_rejected
    """
    resp = api.create_filter_model_config(
        create_filter_model_config_payload(
            model_version="MV-BAD", gray_zone_threshold=50, hold_threshold=50
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_THRESHOLD_ORDER_INVALID)
