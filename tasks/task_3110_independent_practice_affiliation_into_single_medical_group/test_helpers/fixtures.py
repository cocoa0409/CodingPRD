"""Composite setup helpers.

The harness restarts the API server before every test, so each fixture builds
its preconditions from scratch using only PRD-declared endpoints. Setup calls
use get_success_data() so a failure surfaces as a clear "Setup failed" error.

Naming: functions return small dicts of created entities keyed by role in the
scenario (e.g. {"group": ..., "market": ..., ...}).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS, USER_IDS
from .factories import (
    create_affiliation_agreement_payload,
    create_collection_batch_payload,
    create_committee_vote_payload,
    create_credentialing_enrollment_payload,
    create_departure_case_payload,
    create_distribution_statement_payload,
    create_fee_schedule_rate_payload,
    create_implementation_wave_payload,
    create_incentive_allocation_payload,
    create_incentive_pool_payload,
    create_market_payload,
    create_medical_group_payload,
    create_payer_contract_payload,
    create_practice_payload,
    create_provider_payload,
)
from .test_users import (
    TEST_USERS,
    make_market_committee_chair_headers,
    make_physician_board_member_headers,
    make_practice_executive_headers,
)

GA = TEST_USERS["group_admin_headers"]
PCO = TEST_USERS["payer_officer_headers"]
CC = TEST_USERS["credentialing_coordinator_headers"]
DA = TEST_USERS["distribution_accountant_headers"]
GFC = TEST_USERS["group_financial_controller_headers"]
CO = TEST_USERS["compliance_officer_headers"]

CLOCK_DEFAULT = TEST_DEFAULTS["CLOCK_DEFAULT"]


def _ok(resp, label):
    data = get_success_data(resp)
    assert isinstance(data, dict), f"Setup failed ({label}): {resp.status_code} {resp.text}"
    return data


def set_clock(iso=CLOCK_DEFAULT):
    resp = api_client.set_clock({"to_iso8601": iso}, GA)
    assert resp.status_code == 200, f"Setup failed (set_clock): {resp.status_code} {resp.text}"


# ---------------------------------------------------------------------------
# Tier 1/2: group, market, wave, practice scaffolding
# ---------------------------------------------------------------------------

def create_group(active=True, **group_overrides):
    """Create the medical group; optionally activate it (FORMING -> OPERATING)."""
    group = _ok(api_client.create_medical_group(create_medical_group_payload(**group_overrides), GA), "create group")
    if active:
        group = _ok(api_client.activate_medical_group(group["id"], GA), "activate group")
    return group


def create_market_for(group, **overrides):
    return _ok(api_client.create_market(create_market_payload(group["id"], **overrides), GA), "create market")


def create_wave_for(market, **overrides):
    return _ok(api_client.create_implementation_wave(create_implementation_wave_payload(market["id"], **overrides), GA), "create wave")


def move_wave_to_in_cutover(wave):
    """PLANNED -> LOCKED -> IN_CUTOVER (clock must be >= cutover_start_date)."""
    locked = _ok(
        api_client.lock_implementation_wave(wave["id"], {"expected_wave_version": wave["version"]}, GA),
        "lock wave",
    )
    started = _ok(api_client.start_cutover_implementation_wave(locked["id"], GA), "start cutover")
    return started


def create_practice_in(group, market, **overrides):
    return _ok(api_client.create_practice(create_practice_payload(group["id"], market["id"], **overrides), GA), "create practice")


def draft_agreement(practice, **overrides):
    """Draft an agreement for the practice (practice must be at the version
    supplied via overrides or the current one)."""
    version = overrides.pop("expected_practice_version", practice["version"])
    payload = create_affiliation_agreement_payload(practice["id"], version, **overrides)
    return _ok(
        api_client.create_affiliation_agreement(payload, make_practice_executive_headers(practice["id"])),
        "draft agreement",
    )


def execute_agreement(agreement, practice):
    return _ok(
        api_client.execute_affiliation_agreement(agreement["id"], make_practice_executive_headers(practice["id"])),
        "execute agreement",
    )


def onboard_practice(practice, **agreement_overrides):
    """Draft + execute an agreement, moving the practice PROSPECT -> ONBOARDING.
    Requires an IN_CUTOVER wave in the practice's market."""
    agreement = draft_agreement(practice, **agreement_overrides)
    executed = execute_agreement(agreement, practice)
    return executed


def setup_group_market(**overrides):
    """Clock at default; OPERATING group; one market."""
    set_clock(overrides.pop("clock", CLOCK_DEFAULT))
    group = create_group(active=True)
    market = create_market_for(group, **overrides)
    return {"group": group, "market": market}


def setup_wave_in_cutover(**overrides):
    """OPERATING group + market + one IN_CUTOVER wave."""
    ctx = setup_group_market(**overrides)
    wave = create_wave_for(ctx["market"])
    wave = move_wave_to_in_cutover(wave)
    ctx["wave"] = wave
    return ctx


def setup_practice_onboarding(**overrides):
    """Wave IN_CUTOVER + one ONBOARDING practice with an EXECUTED agreement."""
    practice_kwargs = overrides.pop("practice", {})
    agreement_kwargs = overrides.pop("agreement", {})
    ctx = setup_wave_in_cutover(**overrides)
    practice = create_practice_in(ctx["group"], ctx["market"], **practice_kwargs)
    agreement = onboard_practice(practice, **agreement_kwargs)
    ctx["practice"] = _ok(api_client.get_practice(practice["id"], GA), "get practice")
    ctx["agreement"] = agreement
    return ctx


# ---------------------------------------------------------------------------
# Providers, governance, contracts, enrollments
# ---------------------------------------------------------------------------

def add_provider(practice, **overrides):
    return _ok(api_client.create_provider(create_provider_payload(practice["id"], **overrides), GA), "create provider")


def create_contract(group, **overrides):
    return _ok(api_client.create_payer_contract(create_payer_contract_payload(group["id"], **overrides), PCO), "create contract")


def add_rate(contract, **overrides):
    return _ok(api_client.create_fee_schedule_rate(create_fee_schedule_rate_payload(contract["id"], **overrides), PCO), "create rate")


def open_and_pass_ratification_vote(market, contract, chair_provider, voter_providers):
    """Open a PAYER_CONTRACT_RATIFICATION vote and cast FOR until it passes.

    With the default single physician, one FOR ballot exceeds floor(1/2) = 0,
    so the vote closes PASSED immediately.
    """
    vote = _ok(
        api_client.create_committee_vote(
            create_committee_vote_payload(market["id"], contract["id"]),
            make_market_committee_chair_headers(chair_provider["id"]),
        ),
        "create vote",
    )
    for voter in voter_providers:
        vote = _ok(
            api_client.cast_committee_vote(vote["id"], {"ballot": "FOR"}, make_physician_board_member_headers(voter["id"])),
            "cast vote",
        )
        if vote["status"] == "PASSED":
            break
    assert vote["status"] == "PASSED", f"Setup failed (ratification vote did not pass): {vote}"
    return vote


def activate_contract(contract):
    return _ok(api_client.activate_payer_contract(contract["id"], PCO), "activate contract")


def submit_enrollment(provider, contract, **overrides):
    return _ok(
        api_client.create_credentialing_enrollment(
            create_credentialing_enrollment_payload(provider["id"], contract["id"], **overrides), CC
        ),
        "create enrollment",
    )


def approve_enrollment(enrollment):
    return _ok(api_client.approve_credentialing_enrollment(enrollment["id"], CC), "approve enrollment")


def setup_onboarding_with_active_contract(**overrides):
    """Practice ONBOARDING + physician provider + ACTIVE HYBRID contract +
    one APPROVED (not yet EFFECTIVE) enrollment. Wave still IN_CUTOVER."""
    ctx = setup_practice_onboarding(**overrides)
    provider = add_provider(ctx["practice"])
    contract = create_contract(ctx["group"])
    add_rate(contract)
    open_and_pass_ratification_vote(ctx["market"], contract, provider, [provider])
    contract = activate_contract(contract)
    enrollment = submit_enrollment(provider, contract)
    enrollment = approve_enrollment(enrollment)
    ctx.update({
        "provider": provider,
        "contract": contract,
        "enrollment": enrollment,
    })
    return ctx


def setup_affiliated(**overrides):
    """Full base scenario: practice AFFILIATED via wave completion, provider
    ACTIVE with one EFFECTIVE enrollment on an ACTIVE HYBRID contract."""
    ctx = setup_onboarding_with_active_contract(**overrides)
    api_client.complete_implementation_wave(ctx["wave"]["id"], GA)
    ctx["wave"] = _ok(api_client.get_implementation_wave(ctx["wave"]["id"], GA), "get wave")
    ctx["practice"] = _ok(api_client.get_practice(ctx["practice"]["id"], GA), "get practice")
    ctx["provider"] = _ok(api_client.get_provider(ctx["provider"]["id"], GA), "get provider")
    ctx["enrollment"] = _ok(api_client.get_credentialing_enrollment(ctx["enrollment"]["id"], CC), "get enrollment")
    assert ctx["practice"]["status"] == "AFFILIATED", f"Setup failed (affiliation): {ctx['practice']}"
    return ctx


def affiliate_additional_practice(ctx, provider_overrides=None, **practice_overrides):
    """Add a second practice to an existing scenario and affiliate it through
    the same (still IN_CUTOVER) wave. Call BEFORE wave completion."""
    practice = create_practice_in(ctx["group"], ctx["market"], **practice_overrides)
    agreement = onboard_practice(practice)
    provider = add_provider(practice, **(provider_overrides or {}))
    enrollment = submit_enrollment(provider, ctx["contract"])
    enrollment = approve_enrollment(enrollment)
    return {"practice": practice, "agreement": agreement, "provider": provider, "enrollment": enrollment}


def complete_wave_and_refresh(ctx):
    """Complete the wave and refresh the practice/provider/enrollment in ctx."""
    api_client.complete_implementation_wave(ctx["wave"]["id"], GA)
    ctx["wave"] = _ok(api_client.get_implementation_wave(ctx["wave"]["id"], GA), "get wave")
    for key, getter, hdrs in (
        ("practice", api_client.get_practice, GA),
        ("provider", api_client.get_provider, GA),
        ("enrollment", api_client.get_credentialing_enrollment, CC),
    ):
        if key in ctx:
            ctx[key] = _ok(getter(ctx[key]["id"], hdrs), f"get {key}")
    return ctx


def setup_two_affiliated_practices(**overrides):
    """Two practices in the same market, both AFFILIATED, each with an ACTIVE
    physician holding an EFFECTIVE enrollment on the shared contract."""
    ctx = setup_onboarding_with_active_contract(**overrides)
    extra = affiliate_additional_practice(
        ctx,
        provider_overrides={
            "npi": "4445556667",
            "full_name": "Dr. Ben Osei",
            "specialty": "Pediatrics",
            "employment_start_date": "2026-02-01",
        },
        legal_name="Bishop Arts Pediatrics",
        legacy_tin="75-8888888",
        org_npi="2234567891",
    )
    ctx["practice2"] = extra["practice"]
    ctx["agreement2"] = extra["agreement"]
    ctx["provider2"] = extra["provider"]
    ctx["enrollment2"] = extra["enrollment"]
    complete_wave_and_refresh(ctx)
    ctx["practice2"] = _ok(api_client.get_practice(ctx["practice2"]["id"], GA), "get practice2")
    ctx["provider2"] = _ok(api_client.get_provider(ctx["provider2"]["id"], GA), "get provider2")
    ctx["enrollment2"] = _ok(api_client.get_credentialing_enrollment(ctx["enrollment2"]["id"], CC), "get enrollment2")
    assert ctx["practice2"]["status"] == "AFFILIATED", f"Setup failed (affiliation p2): {ctx['practice2']}"
    return ctx


def add_second_active_contract(ctx, payer_name="Second Payer Co"):
    """Create + ratify + activate a second payer contract for ctx["group"],
    and enroll ctx["provider"] on it (AFFILIATED practice -> EFFECTIVE).

    PRD §3.6 allows only one batch per (practice, contract, period), so tests
    that need two batches in one period must spread them across two contracts.
    """
    contract2 = create_contract(ctx["group"], payer_name=payer_name)
    add_rate(contract2)
    open_and_pass_ratification_vote(ctx["market"], contract2, ctx["provider"], [ctx["provider"]])
    contract2 = activate_contract(contract2)
    enrollment2 = submit_enrollment(ctx["provider"], contract2)
    enrollment2 = approve_enrollment(enrollment2)
    return {"contract2": contract2, "enrollment2": enrollment2}


# ---------------------------------------------------------------------------
# Collections, statements, pools
# ---------------------------------------------------------------------------

def post_batch(practice, contract, **overrides):
    return _ok(
        api_client.create_collection_batch(
            create_collection_batch_payload(practice["id"], contract["id"], **overrides), DA
        ),
        "create batch",
    )


def settle_batch(batch, denial_amount_cents=0, headers=None):
    return _ok(
        api_client.settle_collection_batch(batch["id"], {"denial_amount_cents": denial_amount_cents}, headers or DA),
        "settle batch",
    )


def adjust_batch(batch, adjustment_cents, headers=None):
    return _ok(
        api_client.adjust_collection_batch(batch["id"], {"adjustment_cents": adjustment_cents}, headers or DA),
        "adjust batch",
    )


def create_statement(practice, **overrides):
    return _ok(
        api_client.create_distribution_statement(
            create_distribution_statement_payload(practice["id"], **overrides), DA
        ),
        "create statement",
    )


def finalize_statement(statement, headers=None):
    return _ok(api_client.finalize_distribution_statement(statement["id"], headers or GFC), "finalize statement")


def create_pool(contract, **overrides):
    return _ok(api_client.create_incentive_pool(create_incentive_pool_payload(contract["id"], **overrides), PCO), "create pool")


def enter_allocation(pool, practice, **overrides):
    return _ok(
        api_client.create_incentive_allocation(
            create_incentive_allocation_payload(pool["id"], practice["id"], **overrides),
            make_practice_executive_headers(practice["id"]),
        ),
        "create allocation",
    )


# ---------------------------------------------------------------------------
# Departure helpers
# ---------------------------------------------------------------------------

def create_departure(practice, requested_exit_date="2027-12-01"):
    return _ok(
        api_client.create_departure_case(
            create_departure_case_payload(practice["id"], requested_exit_date=requested_exit_date),
            make_practice_executive_headers(practice["id"]),
        ),
        "create departure case",
    )


def setup_departure_settlement_pending(requested_exit_date="2027-12-01", notice_clock=TEST_DEFAULTS["CLOCK_MID"]):
    """Affiliated base scenario; clock advanced to notice_clock; departure case
    created and moved to SETTLEMENT_PENDING. Clock remains at notice_clock."""
    ctx = setup_affiliated()
    set_clock(notice_clock)
    case = create_departure(ctx["practice"], requested_exit_date=requested_exit_date)
    case = _ok(api_client.complete_review_departure_case(case["id"], CO), "complete review")
    ctx["case"] = case
    ctx["practice"] = _ok(api_client.get_practice(ctx["practice"]["id"], GA), "get practice")
    return ctx


def setup_practice_departed(requested_exit_date="2027-12-01", settle_clock=TEST_DEFAULTS["CLOCK_EXIT"]):
    """Full departure: case settled; practice DEPARTED with cascade applied."""
    ctx = setup_departure_settlement_pending(requested_exit_date=requested_exit_date)
    set_clock(settle_clock)
    case = _ok(api_client.settle_departure_case(ctx["case"]["id"], CO), "settle departure")
    ctx["case"] = case
    ctx["practice"] = _ok(api_client.get_practice(ctx["practice"]["id"], GA), "get practice")
    ctx["provider"] = _ok(api_client.get_provider(ctx["provider"]["id"], GA), "get provider")
    ctx["enrollment"] = _ok(api_client.get_credentialing_enrollment(ctx["enrollment"]["id"], CC), "get enrollment")
    return ctx
