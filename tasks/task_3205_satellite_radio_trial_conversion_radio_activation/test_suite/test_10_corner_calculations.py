"""Corner — calculations: disclosure gate, retry bases, paused occupancy."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import ApiErrorId, fixtures
from test_helpers.assertions import assert_same_instant
from test_helpers.fixtures import ADMIN, SYSOP


def test_renewal_disclosure_gate_blocks_charge(api):
    """PRD §3.8: "When the timely disclosure is missing, the subscription is
    neither renewed nor expired: it is left `ACTIVE` past its `end_at` in a
    regulatory limbo, with `disclosure_state` set to `REQUIRED`, until the
    disclosure is sent and a later billing run picks it up. Automatic renewal
    may not charge without timely disclosure."

    Design: Corner/calculations/renewal_disclosure_gate_blocks_charge
    """
    customer = fixtures.create_customer(api)
    tier = fixtures.create_tier(api, includes_streaming=True,
                                min_hardware_generation="GEN1")
    plan = fixtures.create_paid_plan(
        api, tier["id"], service_mode="STREAMING_ONLY", term_kind="MONTHLY",
        term_length_days=30, price_cents=5000, auto_renew_default=True,
    )
    sub = fixtures.create_streaming_subscription(api, customer, plan)

    fixtures.set_clock(api, "2026-10-02T00:00:00Z")
    batch1 = fixtures.run_renewals(api)
    assert batch1["renewed_count"] == 0
    assert batch1["disclosure_blocked_count"] == 1

    sub_now = validate_success(api.get_subscription(sub["id"], ADMIN))
    assert sub_now["status"] == "ACTIVE"
    assert_same_instant(sub_now["start_at"], "2026-09-01T00:00:00Z", "start_at")
    assert sub_now["disclosure_state"] == "REQUIRED"
    charges = [e for e in fixtures.ledger_entries(api, sub["id"])
               if e["entry_type"] == "CHARGE"]
    assert len(charges) == 1, "no renewal charge may post without disclosure"

    fixtures.send_renewal_disclosure(api, sub["id"])
    batch2 = fixtures.run_renewals(api)
    assert batch2["renewed_count"] == 1

    sub_after = validate_success(api.get_subscription(sub["id"], ADMIN))
    assert_same_instant(sub_after["start_at"], "2026-10-01T00:00:00Z", "start_at")
    assert_same_instant(sub_after["end_at"], "2026-10-31T00:00:00Z", "end_at")
    charges_after = [e for e in fixtures.ledger_entries(api, sub["id"])
                     if e["entry_type"] == "CHARGE"]
    assert len(charges_after) == 2
    assert charges_after[-1]["amount_cents"] == 5000


def test_signal_retry_backoff_bases_differ_by_path(api):
    """PRD §2.8: "radios of generation `GEN2` or `GEN3` can be reached over
    `CELLULAR`, while `GEN1` radios can only be reached over `SATELLITE`."
    PRD §2.8: "A `CELLULAR` command retries with a base interval of 15
    minutes; a `SATELLITE` command retries with a base interval of 60
    minutes ... after a failure, `next_retry_at` is set to the time of the
    last attempt plus the current `attempt_count` multiplied by the path's
    base interval."

    A GEN1 radio's failed ACTIVATE requeues at 2026-09-01T01:00:00Z; a GEN3
    radio's at 2026-09-01T00:15:00Z.

    Design: Corner/calculations/signal_retry_backoff_bases_differ_by_path
    """
    customer = fixtures.create_customer(api)
    tier = fixtures.create_tier(api, includes_streaming=False,
                                min_hardware_generation="GEN1")
    trial_plan = fixtures.create_trial_plan(api, tier["id"], term_length_days=30)
    automaker = fixtures.create_automaker(api)
    veh1 = fixtures.create_vehicle(api, automaker["id"], customer["id"],
                                   model_year=2020)
    veh3 = fixtures.create_vehicle(api, automaker["id"], customer["id"],
                                   model_year=2026)
    radio1 = fixtures.create_radio(api, veh1["id"], hardware_generation="GEN1")
    radio3 = fixtures.create_radio(api, veh3["id"], hardware_generation="GEN3")

    fixtures.provision_trial(api, radio1, customer, trial_plan)
    fixtures.provision_trial(api, radio3, customer, trial_plan)
    sig1 = fixtures.first_signal_for_radio(api, radio1["id"])
    sig3 = fixtures.first_signal_for_radio(api, radio3["id"])
    assert sig1["path"] == "SATELLITE"
    assert sig3["path"] == "CELLULAR"

    get_success_data(api.dispatch_signals(SYSOP))
    failed1 = get_success_data(api.fail_signal(sig1["id"], SYSOP))
    failed3 = get_success_data(api.fail_signal(sig3["id"], SYSOP))
    assert failed1["next_retry_at"] is not None
    assert failed3["next_retry_at"] is not None
    assert_same_instant(failed1["next_retry_at"], "2026-09-01T01:00:00Z",
                        "satellite next_retry_at")
    assert_same_instant(failed3["next_retry_at"], "2026-09-01T00:15:00Z",
                        "cellular next_retry_at")


def test_campaign_overlap_paused_blocks_new(api):
    """PRD §3.7: "the occupancy set includes both `ACTIVE` **and** `PAUSED`
    campaigns — pausing a campaign does not free its phase-window — and a
    conflicting activation is rejected with `ERR_CAMPAIGN_OVERLAP`
    (HTTP 409)."

    Design: Corner/calculations/campaign_overlap_paused_blocks_new
    """
    tier = fixtures.create_tier(api)
    plan = fixtures.create_paid_plan(api, tier["id"], price_cents=2000)
    c1 = get_success_data(
        api.create_offer_campaign(
            {
                "code": "CP1", "name": "CP1", "lifecycle_phase": "WINBACK",
                "window_start_at": "2026-09-01T00:00:00Z",
                "window_end_at": "2026-10-01T00:00:00Z",
            },
            ADMIN,
        )
    )
    get_success_data(api.add_offer_step(
        c1["id"], {"step_index": 0, "plan_id": plan["id"], "step_up_rank": 0},
        ADMIN,
    ))
    get_success_data(api.activate_campaign(c1["id"], ADMIN))
    get_success_data(api.pause_campaign(c1["id"], ADMIN))

    c2 = get_success_data(
        api.create_offer_campaign(
            {
                "code": "CP2", "name": "CP2", "lifecycle_phase": "WINBACK",
                "window_start_at": "2026-09-15T00:00:00Z",
                "window_end_at": "2026-11-01T00:00:00Z",
            },
            ADMIN,
        )
    )
    get_success_data(api.add_offer_step(
        c2["id"], {"step_index": 0, "plan_id": plan["id"], "step_up_rank": 0},
        ADMIN,
    ))
    resp = api.activate_campaign(c2["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_OVERLAP)
