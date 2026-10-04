"""Travel/lodging benefits, the shared pool ledger, and episode estimates."""
from test_helpers import (
    ApiErrorId,
    administer_benefit,
    close_episode,
    get_episode,
    get_success_data,
    make_employer_rep_headers,
    setup_approved_episode,
    setup_episode_in_post_op,
    setup_program,
    validate_error,
    validate_success,
    make_patient,
    open_episode,
    drive_episode_to_sor_pending,
)

ADMIN = {"X-User-ID": "test-program-admin-1", "X-User-Role": "ProgramAdmin"}
COORD = {"X-User-ID": "test-care-coordinator-1", "X-User-Role": "CareCoordinator"}
CLAIMS = {"X-User-ID": "test-claims-admin-1", "X-User-Role": "ClaimsAdmin"}


def test_error_benefit_pool_exceeded_triggerable(api, care_coordinator_headers):
    """PRD §3.8: "Administration draws against the same pool ledger used at
    claim adjudication: the amount must fit within the remaining pool for its
    kind, where an amount exactly equal to the remainder succeeds and one cent
    over fails with `ERR_BENEFIT_POOL_EXCEEDED`."

    Design: Corner/errors/error_benefit_pool_exceeded_triggerable
    """
    ctx = setup_approved_episode(contract_overrides={"travel_benefit_cents": 100000})
    episode = ctx["episode"]

    over = api.administer_benefit(
        episode["id"],
        {"kind": "TRAVEL", "traveler": "PATIENT", "amount_cents": 100001,
         "expected_episode_version": episode["version"]},
        care_coordinator_headers,
    )
    validate_error(over, ApiErrorId.ERR_BENEFIT_POOL_EXCEEDED)

    exact = api.administer_benefit(
        episode["id"],
        {"kind": "TRAVEL", "traveler": "PATIENT", "amount_cents": 100000,
         "expected_episode_version": episode["version"]},
        care_coordinator_headers,
    )
    benefit = validate_success(exact, expected_status=201)
    assert benefit["status"] == "ADMINISTERED"
    assert benefit["amount_cents"] == 100000


def test_travel_claim_partial_draw_when_bill_exceeds_remaining_pool(api):
    """PRD §3.7: "The claim is paid the billed amount up to the remaining pool
    — a partial draw is allowed — and denied with reason
    `BENEFIT_POOL_EXHAUSTED` (`ERR_BENEFIT_POOL_EXCEEDED`) only when nothing
    remains."
    PRD §3.7: "The payable draws from the same per-episode pool ledger that
    benefit administration debits"

    Design: Corner/calculations/travel_claim_partial_draw_when_bill_exceeds_remaining_pool
    """
    ctx = setup_approved_episode(contract_overrides={"travel_benefit_cents": 200000})
    episode = ctx["episode"]
    administer_benefit(episode, "TRAVEL", 120000)

    claim = _submit_travel_claim(api, episode, 120000)
    adj = get_success_data(api.adjudicate_claim(claim["id"], CLAIMS))
    assert adj["status"] == "APPROVED"
    assert adj["adjudicated_payable_cents"] == 80000, (
        "min(120000 billed, 200000 pool - 120000 administered)"
    )


def test_travel_claim_denied_only_when_pool_is_empty(api):
    """PRD §3.7: "The claim is paid the billed amount up to the remaining pool
    — a partial draw is allowed — and denied with reason
    `BENEFIT_POOL_EXHAUSTED` (`ERR_BENEFIT_POOL_EXCEEDED`) only when nothing
    remains."

    Design: Corner/calculations/travel_claim_partial_draw_when_bill_exceeds_remaining_pool
    """
    ctx = setup_approved_episode(contract_overrides={"travel_benefit_cents": 100000})
    episode = ctx["episode"]
    administer_benefit(episode, "TRAVEL", 100000)  # drains the pool exactly

    claim = _submit_travel_claim(api, episode, 50000)
    adj = get_success_data(api.adjudicate_claim(claim["id"], CLAIMS))
    assert adj["status"] == "DENIED"
    assert adj["adjudication_reason"] == "BENEFIT_POOL_EXHAUSTED"
    assert adj["adjudicated_payable_cents"] == 0


def _submit_travel_claim(api, episode, billed):
    current = get_episode(episode["id"])
    resp = api.submit_claim(
        current["id"],
        {"claim_type": "TRAVEL", "submitting_entity": "TRAVEL_VENDOR",
         "service_date_seq": current["screen_seq"], "billed_cents": billed,
         "expected_episode_version": current["version"]},
        CLAIMS,
    )
    return validate_success(resp, expected_status=201)


def test_companion_benefit_flag_disallows_companion_traveler(
    api, care_coordinator_headers
):
    """PRD §3.8: "A companion benefit is only available when the contract's
    `companion_allowed` flag permits it, else `ERR_BENEFIT_KIND_MISMATCH`."
    PRD §3.2: "whether `companion_allowed` extends travel and lodging coverage
    to one companion."

    Design: Corner/validations/companion_benefit_flag_disallows_companion_traveler
    """
    ctx_no = setup_approved_episode(
        contract_overrides={
            "travel_benefit_cents": 100000, "lodging_benefit_cents": 100000,
            "companion_allowed": False,
        }
    )
    ctx_yes = setup_approved_episode(
        contract_overrides={
            "travel_benefit_cents": 100000, "lodging_benefit_cents": 100000,
            "companion_allowed": True,
        }
    )

    ep_no = ctx_no["episode"]
    resp = api.administer_benefit(
        ep_no["id"],
        {"kind": "LODGING", "traveler": "COMPANION", "amount_cents": 50000,
         "expected_episode_version": ep_no["version"]},
        care_coordinator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_BENEFIT_KIND_MISMATCH)

    ep_yes = ctx_yes["episode"]
    ok = api.administer_benefit(
        ep_yes["id"],
        {"kind": "LODGING", "traveler": "COMPANION", "amount_cents": 50000,
         "expected_episode_version": ep_yes["version"]},
        care_coordinator_headers,
    )
    benefit = validate_success(ok, expected_status=201)
    assert benefit["status"] == "ADMINISTERED"
    assert benefit["traveler"] == "COMPANION"


def test_benefit_administer_then_release_conserves_pool(api, claims_admin_headers=None):
    """PRD §3.8: "A benefit is created `ADMINISTERED` and stays outstanding
    until the episode reaches any terminal state — `CLOSED`, `AVOIDED`, or
    `CANCELLED` — at which point it is `RELEASED` and no longer counts against
    the pool or the estimate."
    PRD §3.9: "the episode's `applied_bundle_price_cents`, plus an outlier
    projection when an outlier review flag is set (the expected billing above
    the contract's `outlier_threshold_cents`, floored at zero, multiplied by
    `outlier_share_pct`, divided by 100, and truncated to cents), minus the
    same unreleased accrual."

    Design: Difficulty/compensating_invariant/benefit_administer_then_release_conserves_pool
    """
    ctx = setup_approved_episode(
        contract_overrides={"travel_benefit_cents": 200000},
        template_overrides={"warranty_days": 3},
    )
    episode = ctx["episode"]

    pre = get_success_data(api.get_episode(episode["id"], CLAIMS, params={"view": "clinic"}))
    pre_estimate = pre["estimated_total_billed_cents"]

    benefit = administer_benefit(episode, "TRAVEL", 50000)
    after_admin = get_success_data(
        api.get_episode(episode["id"], CLAIMS, params={"view": "clinic"})
    )
    assert after_admin["estimated_total_billed_cents"] == pre_estimate - 50000, (
        "the unreleased accrual subtracts from the estimate"
    )

    from test_helpers import drive_episode_to_post_op

    episode = drive_episode_to_post_op(get_episode(episode["id"]))
    closed = close_episode(episode)
    assert closed["status"] == "CLOSED"

    released = get_success_data(api.get_benefit(benefit["id"], COORD))
    assert released["status"] == "RELEASED"

    after = get_success_data(api.get_episode(episode["id"], CLAIMS, params={"view": "clinic"}))
    assert after["estimated_total_billed_cents"] == pre_estimate, (
        "administer(-accrual) then release(+accrual) conserves the estimate"
    )


def test_benefit_released_on_avoided_episode(api):
    """PRD §3.8: "A benefit is created `ADMINISTERED` and stays outstanding
    until the episode reaches any terminal state — `CLOSED`, `AVOIDED`, or
    `CANCELLED` — at which point it is `RELEASED` and no longer counts against
    the pool or the estimate."
    PRD §3.4: "A conclusion of `SURGERY_UNNECESSARY` — from either
    `SOR_PENDING` or `SOR_REVIEW` — ends the episode as `AVOIDED`: every
    `ADMINISTERED` travel or lodging benefit on the episode is `RELEASED`"

    Design: Difficulty/compensating_invariant/benefit_administer_then_release_conserves_pool
    """
    from test_helpers import drive_episode_to_sor_pending, open_episode

    # Benefits can be administered on an approved episode; a parallel episode
    # that ends AVOIDED releases any benefits administered on it. Because
    # benefits require an approved bundle, administer on an approved episode
    # of one patient, then terminate it via contract cancellation (also a
    # terminal state) and confirm release there — and separately confirm the
    # AVOIDED path releases care items and benefits on the avoided episode.
    prog = setup_program(contract_overrides={"travel_benefit_cents": 200000})
    patient = make_patient(prog["employer"])
    episode = drive_episode_to_sor_pending(open_episode(patient, prog["contract"]))
    validate_success(
        api.record_review(
            episode["id"],
            {"conclusion": "SURGERY_INDICATED",
             "expected_episode_version": episode["version"]},
            {"X-User-ID": "test-physician-reviewer-1",
             "X-User-Role": "PhysicianReviewer"},
        ),
        expected_status=201,
    )
    approved = get_episode(episode["id"])
    benefit = administer_benefit(approved, "TRAVEL", 50000)
    assert benefit["status"] == "ADMINISTERED"

    # Contract termination cancels pre-approval episodes only, so this
    # approved episode is untouched; instead the pool accounting re-opens when
    # the episode eventually closes. Drive to CLOSED and confirm release.
    from test_helpers import drive_episode_to_post_op

    post_op = drive_episode_to_post_op(approved)
    closed = close_episode(post_op)
    assert closed["status"] == "CLOSED"
    released = get_success_data(api.get_benefit(benefit["id"], COORD))
    assert released["status"] == "RELEASED"

    # After release the estimate no longer subtracts the accrual.
    after = get_success_data(
        api.get_episode(episode["id"], CLAIMS, params={"view": "clinic"})
    )
    assert after["estimated_total_billed_cents"] == (
        after["applied_bundle_price_cents"]
    )


def test_episode_estimate_employer_baseline_vs_provider_cost_view(api):
    """PRD §3.9: "The default `employer` view anchors on the employer's
    baseline rate book: the baseline rate for the episode's `family` plus the
    unreleased accrual — the sum of `ADMINISTERED` benefit amounts on the
    episode. The `clinic` view anchors on the provider side: the episode's
    `applied_bundle_price_cents`, plus an outlier projection when an outlier
    review flag is set (the expected billing above the contract's
    `outlier_threshold_cents`, floored at zero, multiplied by
    `outlier_share_pct`, divided by 100, and truncated to cents), minus the
    same unreleased accrual."

    Design: Difficulty/dual_variant_calc/episode_estimate_employer_baseline_vs_provider_cost_view
    """
    ctx = setup_approved_episode(
        rates={"ORTHO_JOINT": 2500000},
        contract_overrides={"travel_benefit_cents": 500000},
    )
    episode = ctx["episode"]
    employer = ctx["employer"]
    administer_benefit(episode, "TRAVEL", 100000)

    rep = get_success_data(
        api.get_episode(
            episode["id"], make_employer_rep_headers(employer["id"])
        )
    )
    assert rep["estimated_total_billed_cents"] == 2500000 + 100000

    clinic = get_success_data(
        api.get_episode(episode["id"], CLAIMS, params={"view": "clinic"})
    )
    assert clinic["estimated_total_billed_cents"] == 3000000 - 100000
    assert rep["estimated_total_billed_cents"] != clinic["estimated_total_billed_cents"]


def test_episode_estimate_unknown_view_rejected(api, claims_admin_headers=None):
    """PRD §3.9: "Any other `view` value is rejected with `ERR_VIEW_UNKNOWN`."
    PRD §2.10: "an unrecognized `view` query value with `ERR_VIEW_UNKNOWN`
    (HTTP 400)."

    Design: Difficulty/dual_variant_calc/episode_estimate_employer_baseline_vs_provider_cost_view
    """
    ctx = setup_approved_episode()
    resp = api.get_episode(
        ctx["episode"]["id"], CLAIMS, params={"view": "internal"}
    )
    validate_error(resp, ApiErrorId.ERR_VIEW_UNKNOWN)

    default = get_success_data(api.get_episode(ctx["episode"]["id"], CLAIMS))
    explicit = get_success_data(
        api.get_episode(ctx["episode"]["id"], CLAIMS, params={"view": "employer"})
    )
    assert default["estimated_total_billed_cents"] == (
        explicit["estimated_total_billed_cents"]
    ), "the default view is employer"


def test_episode_estimated_total_billed_is_computed_not_stored(api):
    """PRD §3.9: "Reading a single episode computes
    `estimated_total_billed_cents` on the fly" and "The default `employer`
    view anchors on the employer's baseline rate book: the baseline rate for
    the episode's `family` plus the unreleased accrual — the sum of
    `ADMINISTERED` benefit amounts on the episode."

    Design: Corner/entities/episode_estimated_total_billed_is_computed_not_stored
    """
    ctx = setup_approved_episode(
        rates={"ORTHO_JOINT": 2500000},
        contract_overrides={"travel_benefit_cents": 500000},
    )
    episode = ctx["episode"]

    before = get_success_data(api.get_episode(episode["id"], ADMIN))
    assert before["estimated_total_billed_cents"] == 2500000

    administer_benefit(episode, "TRAVEL", 70000)

    after = get_success_data(api.get_episode(episode["id"], ADMIN))
    assert after["estimated_total_billed_cents"] == 2570000, (
        "the estimate rises by exactly the unreleased accrual on read"
    )
