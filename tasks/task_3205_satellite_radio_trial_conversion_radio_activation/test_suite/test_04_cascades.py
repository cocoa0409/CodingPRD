"""Transitive cascades: ownership transfer and billing-batch expiry."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import fixtures
from test_helpers.fixtures import ADMIN, SYSOP


def test_transfer_cascade_sub_signal_radio_discount(api):
    """PRD §3.10: "Every `ACTIVE` or `CANCEL_SCHEDULED` subscription on the
    vehicle's radios moves `ACTIVE → TRANSFERRED_AWAY` ... a `DEACTIVATE`
    signal is enqueued revoking the old entitlement".
    PRD §3.3: "When the anchor itself is cancelled, transferred, or expired,
    the next-highest subscription becomes the anchor and **loses** its
    discount ... so an anchor change recomputes `current_term_price_cents` for
    every surviving paid subscription of that customer."

    Chain depth >= 3: transfer terminalizes the anchor (1), enqueues a
    DEACTIVATE signal (2), whose ack deactivates the radio (3), while the
    family recompute reprices the surviving 6000-base streaming sub from its
    discounted 4500 back to 6000 (4).

    The transfer omits `trial_plan_id`: with a fresh trial, PRD §3.4
    supersession would immediately supersede the DEACTIVATE with the trial's
    newer contradictory ACTIVATE, and the radio-deactivation leg of the
    cascade could not be observed. (The TRANSFER_IN fresh-trial leg is covered
    by test_01_refund_and_transfer_pricing.)

    Design: Difficulty/transitive_cascade/transfer_cascade_sub_signal_radio_discount
    """
    old_owner = fixtures.create_customer(api, household_size=2)
    buyer = fixtures.create_customer(api, household_size=1)
    tier = fixtures.create_tier(api, includes_streaming=True,
                                min_hardware_generation="GEN1")
    p9 = fixtures.create_paid_plan(
        api, tier["id"], service_mode="IN_VEHICLE", term_kind="MONTHLY",
        term_length_days=30, price_cents=9000, auto_renew_default=False,
    )
    p6s = fixtures.create_paid_plan(
        api, tier["id"], service_mode="STREAMING_ONLY", term_kind="MONTHLY",
        term_length_days=30, price_cents=6000, auto_renew_default=False,
    )
    automaker = fixtures.create_automaker(api)
    vehicle = fixtures.create_vehicle(api, automaker["id"], old_owner["id"],
                                      condition="USED", model_year=2021)
    radio = fixtures.create_radio(api, vehicle["id"], hardware_generation="GEN1")

    sub_a = fixtures.create_paid_radio_subscription(api, old_owner, p9, radio,
                                                    auto_renew=False)
    # The family-anchor candidate set (PRD §3.3) excludes PENDING_ACTIVATION
    # subscriptions, so the anchor must be ACTIVE before sub_b is created for
    # sub_b's creation-time price to carry the family discount.
    sub_a = fixtures.activate_subscription(api, sub_a, radio["id"])
    sub_b = fixtures.create_streaming_subscription(api, old_owner, p6s,
                                                   auto_renew=False)
    assert sub_b["current_term_price_cents"] == 4500, (
        f"family-discounted price must be 4500 pre-transfer, got "
        f"{sub_b['current_term_price_cents']}"
    )

    fixtures.set_clock(api, "2026-09-11T00:00:00Z")
    vehicle_now = validate_success(api.get_vehicle(vehicle["id"], ADMIN))

    validate_success(api.transfer_ownership(
        vehicle["id"],
        {"new_owner_customer_id": buyer["id"],
         "expected_vehicle_version": vehicle_now["version"]},
        ADMIN,
    ))

    sub_a_now = validate_success(api.get_subscription(sub_a["id"], ADMIN))
    assert sub_a_now["status"] == "TRANSFERRED_AWAY"
    entries = fixtures.ledger_entries(api, sub_a["id"])
    adj = [e for e in entries if e["entry_type"] == "TRANSFER_ADJUSTMENT"]
    assert adj and adj[0]["amount_cents"] == -6000

    signals = validate_success(api.list_radio_signal_commands(radio["id"], SYSOP))
    deactivates = [s for s in signals if s["command_type"] == "DEACTIVATE"]
    assert len(deactivates) == 1, f"expected one DEACTIVATE, got {signals}"
    fixtures.dispatch_and_ack(api, deactivates[0]["id"])

    radio_now = validate_success(api.get_radio(radio["id"], ADMIN))
    assert radio_now["activation_status"] == "DEACTIVATED"

    sub_b_now = validate_success(api.get_subscription(sub_b["id"], ADMIN))
    assert sub_b_now["is_primary_for_discount"] is True
    assert sub_b_now["current_term_price_cents"] == 6000


def test_transfer_cascade_deactivates_radio_only_after_signal_ack(api):
    """PRD §3.10: "a `DEACTIVATE` signal is enqueued revoking the old
    entitlement".
    PRD §3.4: "Acknowledgment moves it `SENT → ACKED`, applies the command's
    effect to the radio per the radio lifecycle".

    Between the transfer and the signal acknowledgment the radio has not yet
    been deactivated — the radio follows the signal, not the API call.

    Design: Difficulty/transitive_cascade/transfer_cascade_sub_signal_radio_discount
    """
    old_owner = fixtures.create_customer(api, household_size=1)
    buyer = fixtures.create_customer(api, household_size=1)
    tier = fixtures.create_tier(api, includes_streaming=False,
                                min_hardware_generation="GEN1")
    plan = fixtures.create_paid_plan(
        api, tier["id"], service_mode="IN_VEHICLE", term_kind="MONTHLY",
        term_length_days=30, price_cents=3000, auto_renew_default=False,
    )
    automaker = fixtures.create_automaker(api)
    vehicle = fixtures.create_vehicle(api, automaker["id"], old_owner["id"],
                                      condition="USED", model_year=2021)
    radio = fixtures.create_radio(api, vehicle["id"], hardware_generation="GEN2")
    sub = fixtures.create_paid_radio_subscription(api, old_owner, plan, radio,
                                                  auto_renew=False)
    fixtures.activate_subscription(api, sub, radio["id"])

    vehicle_now = validate_success(api.get_vehicle(vehicle["id"], ADMIN))
    validate_success(api.transfer_ownership(
        vehicle["id"],
        {"new_owner_customer_id": buyer["id"],
         "expected_vehicle_version": vehicle_now["version"]},
        ADMIN,
    ))

    radio_mid = validate_success(api.get_radio(radio["id"], ADMIN))
    assert radio_mid["activation_status"] == "REGISTERED", (
        "radio must stay REGISTERED until the DEACTIVATE signal is acked"
    )

    signals = validate_success(api.list_radio_signal_commands(radio["id"], SYSOP))
    deactivates = [s for s in signals if s["command_type"] == "DEACTIVATE"]
    assert len(deactivates) == 1
    fixtures.dispatch_and_ack(api, deactivates[0]["id"])

    radio_done = validate_success(api.get_radio(radio["id"], ADMIN))
    assert radio_done["activation_status"] == "DEACTIVATED"


def _setup_renewal_cascade_world(api):
    """Customer (household 2) with: a GEN2 trial radio (RB), an ACTIVE 8000/
    30d anchor paid sub on RC (auto_renew false), and an ACTIVE 6000/365d
    streaming sub (auto_renew false) family-discounted to 4500."""
    customer = fixtures.create_customer(api, household_size=2)
    tier = fixtures.create_tier(api, includes_streaming=True,
                                min_hardware_generation="GEN1")
    p8m = fixtures.create_paid_plan(
        api, tier["id"], service_mode="IN_VEHICLE", term_kind="MONTHLY",
        term_length_days=30, price_cents=8000, auto_renew_default=False,
    )
    p6a = fixtures.create_paid_plan(
        api, tier["id"], service_mode="STREAMING_ONLY", term_kind="ANNUAL",
        term_length_days=365, price_cents=6000, auto_renew_default=False,
    )
    tp6 = fixtures.create_trial_plan(api, tier["id"], term_length_days=90)
    automaker = fixtures.create_automaker(api)
    veh_b = fixtures.create_vehicle(api, automaker["id"], customer["id"])
    veh_c = fixtures.create_vehicle(api, automaker["id"], customer["id"])
    radio_b = fixtures.create_radio(api, veh_b["id"], hardware_generation="GEN2")
    radio_c = fixtures.create_radio(api, veh_c["id"], hardware_generation="GEN2")

    trial = fixtures.provision_trial(api, radio_b, customer, tp6)
    sig_b = fixtures.first_signal_for_radio(api, radio_b["id"])
    fixtures.dispatch_and_ack(api, sig_b["id"])

    sub8 = fixtures.create_paid_radio_subscription(api, customer, p8m, radio_c,
                                                   auto_renew=False)
    sig_c = fixtures.first_signal_for_radio(api, radio_c["id"])
    fixtures.dispatch_and_ack(api, sig_c["id"])

    sub6 = fixtures.create_streaming_subscription(api, customer, p6a,
                                                  auto_renew=False)
    return customer, radio_b, radio_c, trial, sub8, sub6


def test_renewal_cascade_expiry_signal_and_family_reprice(api):
    """PRD §3.8: "An `ACTIVE` subscription whose time has come expires —
    moving `ACTIVE → EXPIRED` — when it is a trial or has `auto_renew` false;
    expiry enqueues a `DEACTIVATE` signal (whose acknowledgment deactivates the
    radio when unreferenced) and recomputes the family discount for the
    customer's surviving paid subscriptions."

    At 2026-10-02 only the 30-day anchor is due: expired_count == 1, the
    anchor goes EXPIRED, a DEACTIVATE signal appears on its radio, and the
    surviving annual sub is promoted to anchor with its price raised
    4500 -> 6000; the 90-day trial is untouched.

    Design: Difficulty/transitive_cascade/renewal_cascade_expiry_signal_and_family_reprice
    """
    customer, radio_b, radio_c, trial, sub8, sub6 = (
        _setup_renewal_cascade_world(api)
    )
    assert sub6["current_term_price_cents"] == 4500, (
        f"pre-batch family discount must price the annual sub at 4500, got "
        f"{sub6['current_term_price_cents']}"
    )

    fixtures.set_clock(api, "2026-10-02T00:00:00Z")
    # PRD §2.7: advancing the clock itself re-evaluates time-based
    # transitions, so the expiry may already have been applied by the clock
    # advance; the explicit batch then reports only what remained. The
    # cascade's observable effects are asserted on the entities below.
    fixtures.run_renewals(api)

    sub8_now = validate_success(api.get_subscription(sub8["id"], ADMIN))
    assert sub8_now["status"] == "EXPIRED"

    signals = validate_success(api.list_radio_signal_commands(radio_c["id"], SYSOP))
    deactivates = [s for s in signals if s["command_type"] == "DEACTIVATE"]
    assert len(deactivates) == 1, f"expected a DEACTIVATE signal, got {signals}"

    sub6_now = validate_success(api.get_subscription(sub6["id"], ADMIN))
    assert sub6_now["is_primary_for_discount"] is True
    assert sub6_now["current_term_price_cents"] == 6000

    trial_now = validate_success(api.get_subscription(trial["id"], ADMIN))
    assert trial_now["status"] == "ACTIVE"

    fixtures.dispatch_and_ack(api, deactivates[0]["id"])
    radio_c_now = validate_success(api.get_radio(radio_c["id"], ADMIN))
    assert radio_c_now["activation_status"] == "DEACTIVATED"


def test_renewal_batch_leaves_future_subs_untouched(api):
    """PRD §3.8: "The billing batch — run by a `SystemOperator` — processes
    everything due as of the current logical time".

    Running the batch at the default clock (nothing due) expires nothing and
    renews nothing.

    Design: Difficulty/transitive_cascade/renewal_cascade_expiry_signal_and_family_reprice
    """
    customer, radio_b, radio_c, trial, sub8, sub6 = (
        _setup_renewal_cascade_world(api)
    )
    batch = fixtures.run_renewals(api)
    assert batch["expired_count"] == 0
    assert batch["renewed_count"] == 0

    assert validate_success(
        api.get_subscription(sub8["id"], ADMIN)
    )["status"] == "ACTIVE"
    assert validate_success(
        api.get_subscription(trial["id"], ADMIN)
    )["status"] == "ACTIVE"
