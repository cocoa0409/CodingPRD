"""Corner — endpoints: bulk data feed, disclosure acknowledgment, streaming."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import ApiErrorId, factories, fixtures
from test_helpers.assertions import assert_same_instant
from test_helpers.fixtures import ADMIN, RETENTION, SYSOP
from test_helpers.test_users import make_automaker_headers


def test_data_feed_bulk_partial_success(api):
    """PRD §3.2: "An `AutomakerPartner` submits a data feed against its
    automaker: a bulk request carrying `items`, where each eligible item
    yields a created trial subscription plus an enqueued `ACTIVATE` signal,
    and each ineligible item is recorded in `results` with its rejection
    reason; the response summarizes `provisioned_count` and `rejected_count`
    rather than failing the batch wholesale."
    PRD §3.2: "`origin` ... `OEM_FEED` for the automaker feed".

    Design: Corner/endpoints/data_feed_bulk_partial_success
    """
    automaker = fixtures.create_automaker(api)
    partner = make_automaker_headers(automaker["id"])
    f1 = fixtures.create_customer(api)
    f2 = fixtures.create_customer(api)
    tier = fixtures.create_tier(api, includes_streaming=False,
                                min_hardware_generation="GEN1")
    trial_plan = fixtures.create_trial_plan(api, tier["id"], term_length_days=90)

    veh1 = get_success_data(api.create_vehicle(
        factories.create_vehicle_payload(automaker["id"], f1["id"],
                                         model_year=2026),
        partner,
    ))
    veh2 = get_success_data(api.create_vehicle(
        factories.create_vehicle_payload(automaker["id"], f2["id"],
                                         model_year=2026),
        partner,
    ))
    radio1 = get_success_data(api.create_radio(
        factories.create_radio_payload(veh1["id"]), partner,
    ))
    radio2 = fixtures.create_radio(api, veh2["id"])
    # occupy radio2 with a PENDING_ACTIVATION trial
    fixtures.provision_trial(api, radio2, f2, trial_plan)

    resp = api.submit_data_feed(
        automaker["id"],
        {"items": [
            {"radio_id": radio1["id"], "customer_id": f1["id"],
             "plan_id": trial_plan["id"]},
            {"radio_id": radio2["id"], "customer_id": f2["id"],
             "plan_id": trial_plan["id"]},
        ]},
        partner,
    )
    data = validate_success(resp)
    assert data["provisioned_count"] == 1
    assert data["rejected_count"] == 1
    assert len(data["results"]) == 2
    rejected = [r for r in data["results"] if r.get("reason")]
    assert rejected and rejected[0]["reason"] == "ERR_RADIO_INELIGIBLE"

    radio1_subs = validate_success(
        api.list_radio_subscriptions(radio1["id"], ADMIN)
    )
    assert len(radio1_subs) == 1
    assert radio1_subs[0]["status"] == "PENDING_ACTIVATION"
    assert radio1_subs[0]["origin"] == "OEM_FEED"


def test_disclosure_acknowledge_flow(api):
    """PRD §3.3: "when the subscription is paid and `auto_renew` is true —
    moves `disclosure_state` from `NONE` to `REQUIRED`".
    PRD §3.9: "The record stamps `sent_at` at send time and computes
    `due_before` as the subscription's `end_at`".
    PRD §3.9: "Acknowledgment belongs to the customer alone: the owning
    customer acknowledges a specific disclosure on their subscription, the
    record's `acknowledged_at` is set to the acknowledgment time, and when
    every required disclosure for the subscription has been acknowledged, the
    subscription's `disclosure_state` advances to `ACKNOWLEDGED`."

    Design: Corner/endpoints/disclosure_acknowledge_flow
    """
    customer = fixtures.create_customer(api)
    tier = fixtures.create_tier(api, includes_streaming=True,
                                min_hardware_generation="GEN1")
    plan = fixtures.create_paid_plan(
        api, tier["id"], service_mode="STREAMING_ONLY", term_kind="MONTHLY",
        term_length_days=30, price_cents=3000, auto_renew_default=True,
    )
    sub = fixtures.create_streaming_subscription(api, customer, plan)
    assert sub["disclosure_state"] == "REQUIRED"

    record = fixtures.send_renewal_disclosure(api, sub["id"])
    assert_same_instant(record["due_before"], "2026-10-01T00:00:00Z",
                        "due_before")

    acknowledged = validate_success(
        api.acknowledge_disclosure(
            sub["id"], record["id"], fixtures.customer_headers(customer)
        )
    )
    assert acknowledged["acknowledged_at"] is not None

    sub_now = validate_success(api.get_subscription(
        sub["id"], fixtures.customer_headers(customer)
    ))
    assert sub_now["disclosure_state"] == "ACKNOWLEDGED"


def test_streaming_only_skips_signal_pipeline(api):
    """PRD §3.3: "a `STREAMING_ONLY` plan has no radio (`radio_id` stays
    null), no `SignalCommand` exists for it, and the subscription moves from
    `PENDING_ACTIVATION` to `ACTIVE` immediately upon creation when
    `start_at` is not in the future. In-vehicle and bundled plans instead
    wait for their `ACTIVATE` signal to be acknowledged, as §3.4 describes."

    Design: Corner/endpoints/streaming_only_skips_signal_pipeline
    """
    customer, automaker, vehicle, radio = fixtures.setup_customer_with_radio(api)
    tier = fixtures.create_tier(api, includes_streaming=True,
                                min_hardware_generation="GEN1")
    streaming_plan = fixtures.create_paid_plan(
        api, tier["id"], service_mode="STREAMING_ONLY", term_kind="MONTHLY",
        term_length_days=30, price_cents=2000, auto_renew_default=False,
    )
    in_vehicle_plan = fixtures.create_paid_plan(
        api, tier["id"], service_mode="IN_VEHICLE", term_kind="MONTHLY",
        term_length_days=30, price_cents=2000, auto_renew_default=False,
    )

    sub_s = fixtures.create_streaming_subscription(api, customer,
                                                   streaming_plan,
                                                   auto_renew=False)
    assert sub_s["status"] == "ACTIVE"
    assert sub_s["radio_id"] is None

    sub_i = fixtures.create_paid_radio_subscription(api, customer,
                                                    in_vehicle_plan, radio,
                                                    auto_renew=False)
    assert sub_i["status"] == "PENDING_ACTIVATION"

    signals = validate_success(
        api.list_radio_signal_commands(radio["id"], SYSOP)
    )
    assert len(signals) == 1
    assert signals[0]["status"] == "QUEUED"
    assert signals[0]["command_type"] == "ACTIVATE"
