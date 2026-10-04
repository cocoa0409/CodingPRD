"""Cross-entity state gates, temporal overlap, and occupancy rules."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import ApiErrorId, factories, fixtures
from test_helpers.fixtures import ADMIN, SYSOP
from test_helpers.test_users import make_dealer_headers


def _setup_deactivated_radio(api):
    """A USED vehicle's GEN1 radio whose 30-day trial ran to expiry and whose
    DEACTIVATE signal was acked — the radio ends DEACTIVATED.
    Returns (owner, radio, trial_plan)."""
    owner = fixtures.create_customer(api, household_size=1)
    tier = fixtures.create_tier(api, includes_streaming=False,
                                min_hardware_generation="GEN1")
    trial_plan = fixtures.create_trial_plan(api, tier["id"], term_length_days=30)
    automaker = fixtures.create_automaker(api)
    vehicle = fixtures.create_vehicle(api, automaker["id"], owner["id"],
                                      condition="USED", model_year=2019)
    radio = fixtures.create_radio(api, vehicle["id"], hardware_generation="GEN1")
    fixtures.provision_trial(api, radio, owner, trial_plan)
    sig = fixtures.first_signal_for_radio(api, radio["id"])
    fixtures.dispatch_and_ack(api, sig["id"])

    fixtures.set_clock(api, "2026-10-02T00:00:00Z")
    fixtures.run_renewals(api)
    signals = validate_success(
        api.list_radio_signal_commands(radio["id"], SYSOP)
    )
    deactivates = [s for s in signals if s["command_type"] == "DEACTIVATE"]
    assert deactivates, "expiry must enqueue a DEACTIVATE"
    fixtures.dispatch_and_ack(api, deactivates[0]["id"])
    radio_now = validate_success(api.get_radio(radio["id"], ADMIN))
    assert radio_now["activation_status"] == "DEACTIVATED"
    return owner, radio, trial_plan


def test_used_reactivation_requires_dealer_enrollment_and_dead_radio(api):
    """PRD §3.2: "A `DealerPartner` reactivates a `DEACTIVATED` radio at
    resale by supplying `radio_id`, `customer_id`, and `plan_id` — this door
    additionally requires `used_program_enrolled` to be true on the acting
    dealer, and an unenrolled dealer is rejected with
    `ERR_DEALER_NOT_ENROLLED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/used_reactivation_requires_dealer_enrollment_and_dead_radio
    """
    owner, radio, trial_plan = _setup_deactivated_radio(api)
    dealer = fixtures.create_dealer(api, enrolled=False)
    buyer = fixtures.create_customer(api, household_size=1)

    resp = api.used_reactivation(
        dealer["id"],
        {"radio_id": radio["id"], "customer_id": buyer["id"],
         "plan_id": trial_plan["id"]},
        make_dealer_headers(dealer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DEALER_NOT_ENROLLED)

    fixtures.enroll_dealer(api, dealer["id"])
    resp2 = api.used_reactivation(
        dealer["id"],
        {"radio_id": radio["id"], "customer_id": buyer["id"],
         "plan_id": trial_plan["id"]},
        make_dealer_headers(dealer["id"]),
    )
    sub2 = validate_success(resp2, expected_status=201)
    assert sub2["origin"] == "USED_DEALER"
    assert sub2["status"] == "PENDING_ACTIVATION"

    radio_now = validate_success(api.get_radio(radio["id"], ADMIN))
    assert radio_now["activation_status"] == "DEACTIVATED", (
        "radio re-enters REGISTERED only when the new ACTIVATE signal acks"
    )


def test_reactivation_of_live_radio_rejected(api):
    """PRD §3.2: "A radio is trial-eligible only when its `activation_status`
    is `UNREGISTERED` or `DEACTIVATED` **and** the count of non-terminal
    subscriptions attached to that radio is exactly zero".

    An enrolled dealer attempting reactivation on a radio whose trial is
    still ACTIVE is rejected with ERR_RADIO_INELIGIBLE.

    Design: Difficulty/cross_entity_state_dependency/used_reactivation_requires_dealer_enrollment_and_dead_radio
    """
    owner = fixtures.create_customer(api, household_size=1)
    tier = fixtures.create_tier(api, includes_streaming=False,
                                min_hardware_generation="GEN1")
    trial_plan = fixtures.create_trial_plan(api, tier["id"], term_length_days=30)
    automaker = fixtures.create_automaker(api)
    vehicle = fixtures.create_vehicle(api, automaker["id"], owner["id"],
                                      condition="USED", model_year=2019)
    radio = fixtures.create_radio(api, vehicle["id"], hardware_generation="GEN1")
    fixtures.provision_trial(api, radio, owner, trial_plan)

    dealer = fixtures.create_dealer(api, enrolled=True)
    buyer = fixtures.create_customer(api, household_size=1)
    resp = api.used_reactivation(
        dealer["id"],
        {"radio_id": radio["id"], "customer_id": buyer["id"],
         "plan_id": trial_plan["id"]},
        make_dealer_headers(dealer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RADIO_INELIGIBLE)


def test_campaign_activation_gated_by_step_count_and_window(api):
    """PRD §3.7: "A campaign begins in `DRAFT` and moves to `ACTIVE` through
    activation, which enforces three checks: the campaign must have at least
    one `OfferStep`; its `window_end_at` must still be in the future; and no
    other campaign in the same `lifecycle_phase` may already occupy the
    window."
    PRD §3.7: "a `PAUSED` campaign may return to `ACTIVE` provided its window
    has not closed".

    Design: Difficulty/cross_entity_state_dependency/campaign_activation_gated_by_step_count_and_window
    """
    tier = fixtures.create_tier(api)
    plan = fixtures.create_paid_plan(api, tier["id"], price_cents=3000)
    campaign = get_success_data(
        api.create_offer_campaign(
            factories.create_campaign_payload(lifecycle_phase="WINBACK"), ADMIN
        )
    )

    resp = api.activate_campaign(campaign["id"], ADMIN)
    err = resp.json().get("data", {}).get("error_id")
    assert resp.status_code >= 400 and err, (
        f"activation with zero steps must fail, got {resp.status_code} {resp.text}"
    )

    get_success_data(
        api.add_offer_step(
            campaign["id"],
            factories.create_offer_step_payload(plan["id"], step_index=0,
                                                step_up_rank=0),
            ADMIN,
        )
    )
    activated = validate_success(api.activate_campaign(campaign["id"], ADMIN))
    assert activated["state"] == "ACTIVE"

    fixtures.set_clock(api, "2026-12-02T00:00:00Z")
    get_success_data(api.pause_campaign(campaign["id"], ADMIN))
    resp2 = api.activate_campaign(campaign["id"], ADMIN)
    validate_error(resp2, ApiErrorId.ERR_CAMPAIGN_WINDOW)


def test_campaign_activate_requires_future_window(api):
    """PRD §3.7: "activation ... enforces three checks: ... its
    `window_end_at` must still be in the future".

    A DRAFT campaign whose window has already closed cannot be activated even
    with a step attached; the rejected error belongs to the campaign window.

    Design: Difficulty/cross_entity_state_dependency/campaign_activation_gated_by_step_count_and_window
    """
    tier = fixtures.create_tier(api)
    plan = fixtures.create_paid_plan(api, tier["id"], price_cents=3000)
    campaign = get_success_data(
        api.create_offer_campaign(
            factories.create_campaign_payload(
                lifecycle_phase="WINBACK",
                window_start_at="2026-08-01T00:00:00Z",
                window_end_at="2026-09-10T00:00:00Z",
            ),
            ADMIN,
        )
    )
    get_success_data(
        api.add_offer_step(
            campaign["id"],
            factories.create_offer_step_payload(plan["id"]),
            ADMIN,
        )
    )
    fixtures.set_clock(api, "2026-09-20T00:00:00Z")
    resp = api.activate_campaign(campaign["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_WINDOW)


def _campaign_with_step(api, code_phase, start, end, activate=False):
    # The harness restarts the server per test, so nothing may be cached
    # across invocations — each call builds its own tier and plan.
    tier = fixtures.create_tier(api)
    plan = fixtures.create_paid_plan(api, tier["id"], price_cents=3000)
    campaign = get_success_data(
        api.create_offer_campaign(
            factories.create_campaign_payload(
                lifecycle_phase=code_phase,
                window_start_at=start, window_end_at=end,
            ),
            ADMIN,
        )
    )
    get_success_data(
        api.add_offer_step(
            campaign["id"],
            factories.create_offer_step_payload(plan["id"]),
            ADMIN,
        )
    )
    if activate:
        get_success_data(api.activate_campaign(campaign["id"], ADMIN))
    return campaign


def test_campaign_phase_window_overlap_adjacency_allowed(api):
    """PRD §3.7: "Occupancy uses half-open interval semantics — the
    candidate's `window_start_at` must be strictly before the incumbent's
    `window_end_at`, and the incumbent's `window_start_at` strictly before
    the candidate's `window_end_at`; windows that merely touch at a boundary
    do not overlap."
    PRD §3.7: "a conflicting activation is rejected with
    `ERR_CAMPAIGN_OVERLAP` (HTTP 409)".

    A POST_TRIAL campaign starting exactly at the incumbent's end activates;
    one starting one second earlier overlaps and is rejected.

    Design: Difficulty/resource_temporal_overlap/campaign_phase_window_overlap_adjacency_allowed
    """
    camp_a = _campaign_with_step(
        api, "POST_TRIAL", "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z",
        activate=True,
    )
    camp_b = _campaign_with_step(
        api, "POST_TRIAL", "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z",
    )
    camp_c = _campaign_with_step(
        api, "POST_TRIAL", "2026-09-30T23:59:59Z", "2026-11-01T00:00:00Z",
    )

    activated_b = validate_success(api.activate_campaign(camp_b["id"], ADMIN))
    assert activated_b["state"] == "ACTIVE"

    resp_c = api.activate_campaign(camp_c["id"], ADMIN)
    validate_error(resp_c, ApiErrorId.ERR_CAMPAIGN_OVERLAP)


def test_campaign_overlap_only_within_same_phase(api):
    """PRD §3.7: "no other campaign in the same `lifecycle_phase` may already
    occupy the window."

    An IN_TRIAL campaign overlapping an ACTIVE POST_TRIAL campaign's window
    does not conflict — occupancy is per phase.

    Design: Difficulty/resource_temporal_overlap/campaign_phase_window_overlap_adjacency_allowed
    """
    _campaign_with_step(
        api, "POST_TRIAL", "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z",
        activate=True,
    )
    other_phase = _campaign_with_step(
        api, "IN_TRIAL", "2026-09-15T00:00:00Z", "2026-11-01T00:00:00Z",
    )
    activated = validate_success(api.activate_campaign(other_phase["id"], ADMIN))
    assert activated["state"] == "ACTIVE"


def test_radio_single_nonterminal_subscription_occupancy(api):
    """PRD §3.2: "A radio is trial-eligible only when its `activation_status`
    is `UNREGISTERED` or `DEACTIVATED` **and** the count of non-terminal
    subscriptions attached to that radio is exactly zero — a single
    `PENDING_ACTIVATION` subscription is enough to block. ... Any trial
    provisioning against an ineligible radio is rejected with
    `ERR_RADIO_INELIGIBLE` (HTTP 422)."

    A second trial on an occupied radio is rejected; once the first trial has
    been activated and then expires via the billing batch (PRD §3.8 expires
    ACTIVE subscriptions whose time has come), the same provisioning succeeds.

    Design: Difficulty/resource_temporal_overlap/radio_single_nonterminal_subscription_occupancy
    """
    customer, automaker, vehicle, radio = fixtures.setup_customer_with_radio(
        api, hardware_generation="GEN2"
    )
    tier = fixtures.create_tier(api, includes_streaming=False,
                                min_hardware_generation="GEN1")
    t10 = fixtures.create_trial_plan(api, tier["id"], term_length_days=30)
    t10b = fixtures.create_trial_plan(api, tier["id"], term_length_days=30)

    first = fixtures.provision_trial(api, radio, customer, t10)

    radio_now = validate_success(api.get_radio(radio["id"], ADMIN))
    resp = api.provision_trial(
        radio["id"],
        {"plan_id": t10b["id"], "customer_id": customer["id"],
         "expected_radio_version": radio_now["version"]},
        fixtures.customer_headers(customer),
    )
    validate_error(resp, ApiErrorId.ERR_RADIO_INELIGIBLE)

    # Activate the first trial so it is ACTIVE and therefore expires when its
    # term ends (PRD §3.8 expires ACTIVE subscriptions).
    fixtures.activate_subscription(api, first, radio["id"])
    fixtures.set_clock(api, "2026-10-02T00:00:00Z")
    # PRD §2.7: the clock advance itself re-evaluates time-based transitions;
    # the explicit batch processes whatever remains.
    fixtures.run_renewals(api)
    # Expiry enqueued a DEACTIVATE signal; the radio becomes DEACTIVATED (and
    # thus trial-eligible again, PRD §3.2) only when that signal is acked.
    signals = validate_success(
        api.list_radio_signal_commands(radio["id"], SYSOP))
    deactivates = [s for s in signals if s["command_type"] == "DEACTIVATE"
                   and s["status"] == "QUEUED"]
    assert len(deactivates) == 1
    fixtures.dispatch_and_ack(api, deactivates[0]["id"])

    radio_after = validate_success(api.get_radio(radio["id"], ADMIN))
    resp2 = api.provision_trial(
        radio["id"],
        {"plan_id": t10b["id"], "customer_id": customer["id"],
         "expected_radio_version": radio_after["version"]},
        fixtures.customer_headers(customer),
    )
    sub2 = validate_success(resp2, expected_status=201)
    assert sub2["status"] == "PENDING_ACTIVATION"


def test_radio_occupancy_counts_pending_activation(api):
    """PRD §3.2: "a single `PENDING_ACTIVATION` subscription is enough to
    block."

    The very first trial is never even dispatched — its mere
    PENDING_ACTIVATION presence occupies the radio.

    Design: Difficulty/resource_temporal_overlap/radio_single_nonterminal_subscription_occupancy
    """
    customer, automaker, vehicle, radio = fixtures.setup_customer_with_radio(api)
    tier = fixtures.create_tier(api, includes_streaming=False,
                                min_hardware_generation="GEN1")
    t_a = fixtures.create_trial_plan(api, tier["id"], term_length_days=30)
    t_b = fixtures.create_trial_plan(api, tier["id"], term_length_days=60)

    fixtures.provision_trial(api, radio, customer, t_a)
    radio_now = validate_success(api.get_radio(radio["id"], ADMIN))
    resp = api.provision_trial(
        radio["id"],
        {"plan_id": t_b["id"], "customer_id": customer["id"],
         "expected_radio_version": radio_now["version"]},
        fixtures.customer_headers(customer),
    )
    validate_error(resp, ApiErrorId.ERR_RADIO_INELIGIBLE)
