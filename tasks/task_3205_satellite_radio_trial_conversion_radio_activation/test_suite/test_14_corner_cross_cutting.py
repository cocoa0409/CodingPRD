"""Corner — cross-cutting: OCC staleness, idempotent requeue, clock default,
immediate consistency."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import ApiErrorId, fixtures
from test_helpers.assertions import assert_same_instant
from test_helpers.fixtures import ADMIN, RETENTION, SYSOP


def test_occ_stale_version_on_trial_provisioning(api):
    """PRD §2.6: "Provisioning a trial subscription against a radio requires
    the request to carry `expected_radio_version`, the value of that radio's
    `version` as the client last observed it. If another writer has since
    advanced the radio's version ... the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the radio
    before retrying."
    PRD §3.2: "on success it creates the trial subscription and increments
    the radio's `version` by one."

    The first provisioning bumps the radio version; once that trial is
    terminal (immediate cancel frees the radio per PRD §3.6), a second
    provisioning carrying the pre-mutation version is rejected 412 and only
    one non-terminal subscription exists on the radio.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_trial_provisioning
    """
    customer, automaker, vehicle, radio = fixtures.setup_customer_with_radio(api)
    tier = fixtures.create_tier(api, includes_streaming=False,
                                min_hardware_generation="GEN1")
    t1 = fixtures.create_trial_plan(api, tier["id"], term_length_days=30)
    t2 = fixtures.create_trial_plan(api, tier["id"], term_length_days=60)

    observed_version = radio["version"]
    first_sub = fixtures.provision_trial(api, radio, customer, t1,
                                         expected_version=observed_version)
    # Free the radio so the stale-version check is reachable: per PRD §2.9 the
    # trial-eligibility rule fires before optimistic-concurrency staleness, so
    # a still-occupied radio would surface ERR_RADIO_INELIGIBLE instead.
    validate_success(
        api.cancel_subscription(first_sub["id"], {"effective_mode": "IMMEDIATE"},
                                fixtures.customer_headers(customer))
    )

    resp = api.provision_trial(
        radio["id"],
        {"plan_id": t2["id"], "customer_id": customer["id"],
         "expected_radio_version": observed_version},
        fixtures.customer_headers(customer),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    subs = validate_success(api.list_radio_subscriptions(radio["id"], ADMIN))
    non_terminal = [
        s for s in subs
        if s["status"] in ("PENDING_ACTIVATION", "ACTIVE", "SUSPENDED",
                           "CANCEL_SCHEDULED")
    ]
    # The stale retry must not have created anything: the only subscription is
    # the cancelled first trial.
    assert non_terminal == []
    assert len(subs) == 1 and subs[0]["status"] == "CANCELLED"


def test_idempotent_signal_requeue_key(api):
    """PRD §2.4: "when a create carries an `idempotency_key` that has already
    been used, the server does not fail — it returns the original command or
    entry that the key first produced."

    Two requeue calls with the same key return the same SignalCommand id and
    enqueue exactly one new command.

    Design: Corner/cross_cutting_complexity_layers/idempotent_signal_requeue_key
    """
    customer, automaker, vehicle, radio = fixtures.setup_customer_with_radio(api)
    tier = fixtures.create_tier(api, includes_streaming=False,
                                min_hardware_generation="GEN1")
    plan = fixtures.create_paid_plan(
        api, tier["id"], service_mode="IN_VEHICLE", term_kind="MONTHLY",
        term_length_days=30, price_cents=5000, auto_renew_default=False,
    )
    sub = fixtures.create_paid_radio_subscription(api, customer, plan, radio,
                                                  auto_renew=False)
    signal = fixtures.first_signal_for_radio(api, radio["id"])
    fixtures.exhaust_signal(api, signal["id"])

    first = validate_success(
        api.requeue_signal(
            sub["id"], {"command_type": "ACTIVATE", "idempotency_key": "idem-1"},
            RETENTION,
        ),
        expected_status=201,
    )
    second_resp = api.requeue_signal(
        sub["id"], {"command_type": "ACTIVATE", "idempotency_key": "idem-1"},
        RETENTION,
    )
    # PRD §2.4 pins only that the replay "does not fail" and returns the
    # original command; whether the replay is surfaced as 200 (no new
    # resource) or 201 (creation endpoint) is left to the implementation.
    assert second_resp.status_code in (200, 201), (
        f"idempotent replay must succeed, got {second_resp.status_code}: "
        f"{second_resp.text}"
    )
    second = second_resp.json()["data"]
    assert first["id"] == second["id"], (
        "duplicate idempotency key must return the original command"
    )

    signals = validate_success(api.list_radio_signal_commands(radio["id"], SYSOP))
    queued = [s for s in signals if s["status"] == "QUEUED"]
    assert len(queued) == 1, f"expected exactly one replacement QUEUED, got {signals}"


def test_clock_default_is_2026_09_01(api):
    """PRD §2.7: "Before any operator call, the logical clock stands at
    exactly 2026-09-01T00:00:00Z and must never fall back to the host's wall
    clock."
    PRD §3.3: "its `start_at` is stamped at creation, with `end_at` computed
    as `start_at` plus the plan's `term_length_days`."

    A 30-day trial provisioned with no clock call starts at
    2026-09-01T00:00:00Z and ends at 2026-10-01T00:00:00Z.

    Design: Corner/cross_cutting_complexity_layers/clock_default_is_2026_09_01
    """
    customer, automaker, vehicle, radio = fixtures.setup_customer_with_radio(
        api, hardware_generation="GEN1"
    )
    tier = fixtures.create_tier(api, includes_streaming=False,
                                min_hardware_generation="GEN1")
    trial_plan = fixtures.create_trial_plan(api, tier["id"], term_length_days=30)
    sub = fixtures.provision_trial(api, radio, customer, trial_plan)
    assert_same_instant(sub["start_at"], "2026-09-01T00:00:00Z", "start_at")
    assert_same_instant(sub["end_at"], "2026-10-01T00:00:00Z", "end_at")


def test_immediate_consistency_of_cascade_in_response(api):
    """PRD §3.10: "The transfer rewrites `owner_customer_id` to the new owner
    and increments the vehicle's `version` by one. Every `ACTIVE` or
    `CANCEL_SCHEDULED` subscription on the vehicle's radios moves `ACTIVE →
    TRANSFERRED_AWAY`".

    The transfer response already carries the new owner, and an immediate
    follow-up read of the old subscription shows TRANSFERRED_AWAY in the same
    logical instant.

    Design: Corner/consistency_model/immediate_consistency_of_cascade_in_response
    """
    old_owner = fixtures.create_customer(api)
    new_owner = fixtures.create_customer(api)
    tier = fixtures.create_tier(api, includes_streaming=False,
                                min_hardware_generation="GEN1")
    plan = fixtures.create_paid_plan(
        api, tier["id"], service_mode="IN_VEHICLE", term_kind="MONTHLY",
        term_length_days=30, price_cents=3000, auto_renew_default=False,
    )
    trial_plan = fixtures.create_trial_plan(api, tier["id"], term_length_days=90)
    automaker = fixtures.create_automaker(api)
    vehicle = fixtures.create_vehicle(api, automaker["id"], old_owner["id"],
                                      condition="USED", model_year=2022)
    radio = fixtures.create_radio(api, vehicle["id"], hardware_generation="GEN2")
    sub = fixtures.create_paid_radio_subscription(api, old_owner, plan, radio,
                                                  auto_renew=False)
    fixtures.activate_subscription(api, sub, radio["id"])

    vehicle_now = validate_success(api.get_vehicle(vehicle["id"], ADMIN))
    transferred = validate_success(api.transfer_ownership(
        vehicle["id"],
        {"new_owner_customer_id": new_owner["id"],
         "expected_vehicle_version": vehicle_now["version"],
         "trial_plan_id": trial_plan["id"]},
        ADMIN,
    ))
    assert transferred["owner_customer_id"] == new_owner["id"]

    sub_now = validate_success(api.get_subscription(sub["id"], ADMIN))
    assert sub_now["status"] == "TRANSFERRED_AWAY"
