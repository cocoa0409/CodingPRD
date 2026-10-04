"""Agreement creation, reads, version discipline and the logical clock."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_agreement,
    create_agreement_payload,
    create_case_payload,
    is_iso8601_timestamp,
    make_subscriber_headers,
    validate_error,
    validate_success,
)

from test_helpers.fixtures import (
    create_agreement,
    create_case,
    create_plan,
    create_subscriber,
    current_agreement_version,
    get_plan,
    get_subscriber,
    get_summary,
    get_term,
    offer_plan,
    purchase_term,
    quote_term,
    set_clock,
    setup_active_agreement,
    setup_agreement_with_offered_plan,
)

MISSING_ID = "00000000-0000-4000-8000-000000000000"


def test_agreement_creation_returns_derived_defaults(api):
    """PRD §3.1: "A newly registered agreement sits in `DRAFT` — its `agreement_status` is
    `DRAFT` — so nothing is sellable yet, `congestion_active` is `false`, `congestion_index`
    is 0, `allocated_data_mb` is 0, and `remaining_data_mb` equals `committed_data_mb` because
    none of the bought volume has been promised to anyone."

    Design: Corner/entities/capacity_agreement_create_returns_derived_defaults
    """
    set_clock()
    resp = api.create_agreement(
        create_agreement_payload(), TEST_USERS["planner_headers"]
    )
    data = validate_success(resp, expected_status=201)
    assert resp.json()["response_type"] == "object"
    assert_agreement(data)
    assert data["agreement_status"] == "DRAFT"
    assert data["version"] == 1
    assert data["allocated_data_mb"] == 0
    assert data["remaining_data_mb"] == data["committed_data_mb"] == 16000
    assert data["congestion_index"] == 0
    assert data["congestion_active"] is False
    assert data["resolved_purchase_cost_microcents"] == 0
    meta = resp.json()["meta"]
    assert meta["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(meta["api_request_timestamp"])


def test_agreement_read_round_trips_every_configuration_field(api):
    """PRD §3.1: "The registration names the counterparty through `host_network_name`, fixes
    the two-letter `state_code` the agreement is priced for, and records the three negotiated
    unit rates".

    Design: Corner/entities/capacity_agreement_get_round_trips_every_configuration_field
    """
    set_clock()
    created = create_agreement()
    resp = api.get_agreement(created["id"], TEST_USERS["agent_headers"])
    data = validate_success(resp)
    assert data["data_rate_microcents_per_mb"] == 1237
    assert data["voice_rate_microcents_per_min"] == 60
    assert data["sms_rate_microcents_per_msg"] == 3
    assert data["committed_data_mb"] == 16000
    assert data["committed_voice_minutes"] == 200000
    assert data["committed_sms_messages"] == 400000
    assert data["state_code"] == "CA"
    assert data["host_network_name"] == "Pacific Host Network"
    assert data["congestion_active"] is False
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])


def test_agreement_read_with_unknown_id_returns_agreement_not_found(api):
    """PRD §2.9: "A missing agreement yields `ERR_AGREEMENT_NOT_FOUND`".

    Design: Corner/entities/capacity_agreement_get_with_unknown_id_returns_agreement_not_found
    """
    set_clock()
    resp = api.get_agreement(MISSING_ID, TEST_USERS["planner_headers"])
    error_data = validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_FOUND)
    assert resp.json()["response_type"] == "error"
    assert error_data["error_id"] == "ERR_AGREEMENT_NOT_FOUND"
    assert error_data.get("message")


def test_agreement_creation_without_committed_data_is_invalid_request(api):
    """PRD §2.11: "a request that supplies an unknown field, or omits a required one, is
    rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/capacity_agreement_create_missing_commitment_returns_invalid_request
    """
    set_clock()
    payload = create_agreement_payload()
    del payload["committed_data_mb"]
    resp = api.create_agreement(payload, TEST_USERS["planner_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_agreement_version_advances_by_one_on_every_write(api):
    """PRD §2.5: "`version` — a system-managed integer that starts at 1 and increments by 1 on
    every modification to the row, including modifications performed by derived-field
    recomputation."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_version_increments_on_every_write
    """
    set_clock()
    created = create_agreement()
    assert created["version"] == 1

    # PRD 3.1: the DRAFT -> ACTIVE transition is admitted only when at least one plan on
    # the agreement is already OFFERED, and every write to either row recomputes the
    # agreement balance, so each of these steps advances the agreement's version by one.
    seed = create_plan(created["id"], plan_code="SEED1")
    assert seed["version"] == 1
    assert current_agreement_version(created["id"]) == 2

    offered = offer_plan(seed["id"], current_agreement_version(created["id"]))
    assert offered["plan_status"] == "OFFERED"
    assert offered["version"] == 2
    assert current_agreement_version(created["id"]) == 3

    activated = api.activate_agreement(
        created["id"], TEST_USERS["planner_headers"]
    ).json()["data"]
    assert activated["agreement_status"] == "ACTIVE"
    assert activated["version"] == 4
    assert current_agreement_version(created["id"]) == 4

    subscriber = create_subscriber()
    quote_term(subscriber["id"], seed["id"], 4)
    assert current_agreement_version(created["id"]) == 5

    # A read is not a modification.
    api.get_agreement(created["id"], TEST_USERS["planner_headers"])
    assert current_agreement_version(created["id"]) == 5


def test_derived_allocation_reconciles_on_every_read(api):
    """PRD §3.1: "the invariant `allocated_data_mb` plus `remaining_data_mb` equals
    `committed_data_mb` holds after every event while the agreement is in `ACTIVE` or
    `SUSPENDED`."

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_after_source_change
    """
    set_clock()
    agreement, plan = setup_agreement_with_offered_plan()

    summary = get_summary(agreement["id"])
    assert summary["allocated_data_mb"] == 0
    assert summary["remaining_data_mb"] == 16000

    first = create_subscriber()
    first_term = quote_term(
        first["id"], plan["id"], current_agreement_version(agreement["id"])
    )
    purchase_term(first_term["id"], first["id"])
    summary = get_summary(agreement["id"])
    assert summary["allocated_data_mb"] == 3000
    assert summary["remaining_data_mb"] == 13000
    assert summary["allocated_data_mb"] + summary["remaining_data_mb"] == 16000

    second = create_subscriber(msisdn="13055550121", full_name="Second Recon")
    second_term = quote_term(
        second["id"], plan["id"], current_agreement_version(agreement["id"])
    )
    purchase_term(second_term["id"], second["id"])
    summary = get_summary(agreement["id"])
    assert summary["allocated_data_mb"] == 6000
    assert summary["remaining_data_mb"] == 10000
    assert summary["allocated_data_mb"] + summary["remaining_data_mb"] == 16000


def test_repeated_reads_and_clock_reset_are_idempotent(api):
    """PRD §2.8: "Only a `PlatformAdmin` may move it, through a capability that sets the clock
    to a supplied `current_utc` instant; the capability returns the new clock reading."

    Design: Corner/cross_cutting_complexity_layers/idempotency_of_repeated_reads_and_the_clock_endpoint
    """
    set_clock()
    agreement, plan = setup_agreement_with_offered_plan()
    subscriber = create_subscriber()
    term = quote_term(subscriber["id"], plan["id"], agreement["version"])
    purchase_term(term["id"], subscriber["id"])

    first_read = get_summary(agreement["id"])
    version_before = current_agreement_version(agreement["id"])
    second_read = get_summary(agreement["id"])
    version_after = current_agreement_version(agreement["id"])
    assert first_read == second_read
    assert version_before == version_after

    clock = set_clock("2026-10-01T00:00:00Z")
    assert clock["current_utc"].startswith("2026-10-01T00:00:00")
    assert get_summary(agreement["id"]) == first_read
    assert get_term(term["id"])["deferred_revenue_cents"] == 1332


def test_allocation_visible_immediately_after_purchase(api):
    """PRD §3.5: "On success the term's `term_price_cents` is resolved by the
    `prepaid_term_price` rule and the two revenue fields are seeded with the provisional
    schedule; the plan is moved from `OFFERED` to `ACTIVE`, and the agreement's
    `allocated_data_mb` and `remaining_data_mb` are recomputed."

    Design: Corner/consistency_model/immediate_visibility_of_allocation_after_purchase
    """
    set_clock()
    agreement, plan = setup_agreement_with_offered_plan()
    subscriber = create_subscriber()
    term = quote_term(subscriber["id"], plan["id"], agreement["version"])

    resp = api.purchase_term(term["id"], make_subscriber_headers(subscriber["id"]))
    purchased = validate_success(resp)
    assert purchased["term_status"] == "PURCHASED"
    assert purchased["term_price_cents"] == 1999

    assert get_summary(agreement["id"])["allocated_data_mb"] == 3000
    assert get_plan(plan["id"])["plan_status"] == "ACTIVE"
    assert get_subscriber(subscriber["id"])["allocation_status"] == "HELD"


def test_clock_defaults_to_2026_09_01_not_wall_clock(api):
    """PRD §2.8: "That clock reads exactly `2026-09-01T00:00:00Z` at startup and holds that
    value until it is moved."

    Design: Corner/endpoints/clock_default_is_2026_09_01_and_is_never_wall_clock
    """
    agreement = setup_active_agreement()
    create_plan(agreement["id"])
    subscriber = create_subscriber(msisdn="13055550091", full_name="Default Clock Rider")

    resp = api.create_case(
        create_case_payload(subscriber["id"]), TEST_USERS["agent_headers"]
    )
    case = validate_success(resp, expected_status=201)
    assert case["sla_due_at"].startswith("2026-09-01T04:00:00"), (
        "the default logical clock, not the wall clock, anchors the SLA deadline"
    )

    set_clock("2026-10-01T00:00:00Z")
    second = create_case(subscriber["id"])
    assert second["sla_due_at"].startswith("2026-10-01T04:00:00")