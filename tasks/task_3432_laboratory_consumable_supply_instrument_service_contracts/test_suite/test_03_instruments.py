"""Instruments: placement-type commitment rule, the account-ACTIVE install
gate, the two independent status dimensions, decommission guarding, and the
pull-through projection variants.
"""

from test_helpers import (
    ACCOUNT_MANAGER,
    CLOCK_START_UTC,
    DISPATCHER,
    ApiErrorId,
    api_client,
    create_account,
    create_instrument,
    create_service_request,
    decommission_instrument,
    dispatch_request,
    ensure_install_engineer,
    get_instrument,
    install_instrument,
    instrument_payload,
    plus_days,
    reactivate_account,
    resolve_request,
    same_instant,
    suspend_account,
    validate_error,
    validate_success,
)


def test_reagent_rental_missing_commitment_invalid_request(api):
    """PRD section 3.3: "a `REAGENT_RENTAL` or `LEASE` placement requires
    `monthly_consumable_commitment_cents` to be present and greater than 0,
    while a `CAPITAL` placement must carry a commitment of exactly 0, and
    violating either rule fails creation with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/reagent_rental_missing_commitment_invalid_request
    """
    account = create_account(name="Rental Lab")
    payload = instrument_payload(account["id"], placement_type="REAGENT_RENTAL")
    payload.pop("monthly_consumable_commitment_cents", None)
    response = api_client.create_instrument(payload, headers=ACCOUNT_MANAGER)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    ok = api_client.create_instrument(
        instrument_payload(
            account["id"], placement_type="CAPITAL",
            monthly_consumable_commitment_cents=0,
        ),
        headers=ACCOUNT_MANAGER,
    )
    validate_success(ok, 201)


def test_install_blocked_while_account_suspended(api):
    """PRD section 3.3: "Installation is a `ServiceDispatcher` action gated on
    three conditions beyond the instrument's existence: the instrument is
    `ORDERED` — installing anything else is `ERR_INVALID_STATE`; the owning
    account is `ACTIVE` — otherwise `ERR_ACCOUNT_NOT_ACTIVE`; and at least one
    engineer exists who is `ACTIVE`, whose `territory_code` matches the
    account's `territory_code`, and whose `skills` include `INSTALL`".

    Design: Difficulty/cross_entity_state_dependency/install_requires_account_active
    """
    account = create_account(name="Gate Lab", segment="INDUSTRIAL")
    ensure_install_engineer(account)
    instrument = create_instrument(account, model="SEQ-5000")
    suspend_account(account)

    response = api_client.install_instrument(instrument["id"], headers=DISPATCHER)
    validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE)
    fresh = get_instrument(instrument)
    assert fresh["placement_status"] == "ORDERED", "no partial transition"


def test_install_succeeds_once_account_reactivated(api):
    """PRD section 3.3: "A successful install stamps `installed_at` from the
    logical clock, moves the instrument to `INSTALLED`, and increments its
    `version` by 1."  The account-status gate of the same section opens again
    once the account is reinstated to `ACTIVE`.

    Design: Difficulty/cross_entity_state_dependency/install_requires_account_active
    """
    account = create_account(name="Gate Lab", segment="INDUSTRIAL")
    ensure_install_engineer(account)
    instrument = create_instrument(account, model="SEQ-5000")
    created_version = instrument["version"]
    suspend_account(account)
    reactivate_account(account)

    installed = install_instrument(instrument)
    assert installed["placement_status"] == "INSTALLED"
    assert same_instant(installed["installed_at"], CLOCK_START_UTC), (
        "installed_at is stamped from the logical clock, still at startup default"
    )
    assert installed["version"] == created_version + 1


def _install_with_break_fix_engineer(account):
    """INSTALL+BREAK_FIX engineer in territory, then install the instrument."""
    from test_helpers import ensure_engineer

    ensure_engineer(account, ["INSTALL", "BREAK_FIX"], name="Multi Skilled")
    instrument = create_instrument(account, model="SEQ-5000")
    return install_instrument(instrument)


def test_operational_status_flips_down_and_up_independent_of_placement(api):
    """PRD section 3.3: "Independently of the placement lifecycle, every
    instrument derives an `operational_status`: it reads `DOWN` whenever any
    `BREAK_FIX` service request with severity `CRITICAL` sits `OPEN` or
    `DISPATCHED` on that instrument, and `UP` otherwise."

    Design: Difficulty/non_linear_state_machine/instrument_parallel_placement_and_operational
    """
    account = create_account(name="Dims Lab", segment="INDUSTRIAL")
    instrument = _install_with_break_fix_engineer(account)

    before = get_instrument(instrument)
    assert before["placement_status"] == "INSTALLED"
    assert before["operational_status"] == "UP"

    request = create_service_request(
        instrument, account, request_type="BREAK_FIX", severity="CRITICAL"
    )
    during = get_instrument(instrument)
    assert during["placement_status"] == "INSTALLED", (
        "the placement dimension does not move when a critical break-fix opens"
    )
    assert during["operational_status"] == "DOWN"

    dispatched = dispatch_request(request)
    resolve_request(dispatched, hours_on_site=1, parts_cost_cents=0)
    after = get_instrument(instrument)
    assert after["placement_status"] == "INSTALLED"
    assert after["operational_status"] == "UP", (
        "resolving the only critical break-fix re-derives operational_status UP"
    )


def test_response_deadline_defaults_to_72h_without_contract(api):
    """PRD section 3.5: "Its `response_deadline` is computed at open: when a
    service contract on the instrument reads `ACTIVE` or `RENEWAL_DUE` at that
    moment, the deadline is `opened_at` plus that contract's `response_hours`;
    with no such contract the deadline is `opened_at` plus 72 hours."

    Design: Difficulty/non_linear_state_machine/instrument_parallel_placement_and_operational
    """
    account = create_account(name="Dims Lab", segment="INDUSTRIAL")
    instrument = _install_with_break_fix_engineer(account)
    request = create_service_request(
        instrument, account, request_type="BREAK_FIX", severity="CRITICAL"
    )
    assert same_instant(request["opened_at"], CLOCK_START_UTC)
    assert same_instant(
        request["response_deadline"], plus_days(CLOCK_START_UTC, 3)
    ), "no live contract: deadline is opened_at + 72 hours"

    dispatched = dispatch_request(request)
    resolved = resolve_request(dispatched, hours_on_site=1, parts_cost_cents=0)
    assert resolved["sla_breached"] is False, (
        "resolved at the open instant, far inside the 72-hour default window"
    )
    assert resolved["credit_memo_cents"] == 0


def test_decommission_blocked_by_open_request(api):
    """PRD section 3.3: "The request is blocked with
    `ERR_DECOMMISSION_BLOCKED` while any service request on the instrument is
    `OPEN` or `DISPATCHED`, or while any service contract on the instrument
    reads `ACTIVE` or `RENEWAL_DUE`; an instrument that is not `INSTALLED` at
    all yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/decommission_blocked_by_open_request
    """
    account = create_account(name="Decom Lab")
    instrument = _install_with_break_fix_engineer(account)
    create_service_request(
        instrument, account, request_type="BREAK_FIX", severity="LOW"
    )
    response = api_client.decommission_instrument(
        instrument["id"], headers=ACCOUNT_MANAGER
    )
    validate_error(response, ApiErrorId.ERR_DECOMMISSION_BLOCKED)
    fresh = get_instrument(instrument)
    assert fresh["placement_status"] == "INSTALLED"


def test_pull_through_installed_base_vs_forward_looking(api):
    """PRD section 3.3: "The projection reports four figures together:
    `installed_base_monthly_cents`, the sum of
    `monthly_baseline_consumable_cents` over the account's `INSTALLED`
    instruments; `forward_looking_monthly_cents`, which adds to that
    installed-base figure half of the summed baselines of the account's
    `ORDERED` instruments, with the half-weight multiplication rounded half-up
    to the nearest cent".  The two variants are returned side by side and
    differ by exactly the weighted pipeline.

    Design: Difficulty/dual_variant_calc/pull_through_installed_vs_forward
    """
    account = create_account(name="Pull Through Lab", segment="CLINICAL")
    ensure_install_engineer(account)
    install_instrument(create_instrument(
        account, monthly_baseline_consumable_cents=100000
    ))
    install_instrument(create_instrument(
        account, monthly_baseline_consumable_cents=40000
    ))
    create_instrument(
        account,
        placement_type="REAGENT_RENTAL",
        monthly_consumable_commitment_cents=60000,
        monthly_baseline_consumable_cents=60000,
    )

    response = api_client.get_pull_through_projection(
        account["id"], headers=ACCOUNT_MANAGER
    )
    data = validate_success(response, 200)
    assert data["installed_base_monthly_cents"] == 140000, (
        "installed base sums INSTALLED instruments only: 100000 + 40000"
    )
    assert data["forward_looking_monthly_cents"] == 170000, (
        "forward view adds half the ORDERED pipeline: 140000 + 0.5 x 60000"
    )
    assert data["installed_instrument_count"] == 2
    assert data["ordered_instrument_count"] == 1


def test_pull_through_excludes_decommissioned_instruments(api):
    """PRD section 3.3: "`DECOMMISSIONED` instruments are excluded from both
    sums and both counts."

    Design: Difficulty/dual_variant_calc/pull_through_installed_vs_forward
    """
    account = create_account(name="Pull Through Lab", segment="CLINICAL")
    ensure_install_engineer(account)
    install_instrument(create_instrument(
        account, monthly_baseline_consumable_cents=100000
    ))
    second = install_instrument(create_instrument(
        account, monthly_baseline_consumable_cents=40000
    ))
    create_instrument(
        account,
        placement_type="REAGENT_RENTAL",
        monthly_consumable_commitment_cents=60000,
        monthly_baseline_consumable_cents=60000,
    )
    decommission_instrument(second)

    response = api_client.get_pull_through_projection(
        account["id"], headers=ACCOUNT_MANAGER
    )
    data = validate_success(response, 200)
    assert data["installed_base_monthly_cents"] == 100000
    assert data["forward_looking_monthly_cents"] == 130000, (
        "100000 installed base + half of the 60000 ordered baseline"
    )
    assert data["installed_instrument_count"] == 1
    assert data["ordered_instrument_count"] == 1
