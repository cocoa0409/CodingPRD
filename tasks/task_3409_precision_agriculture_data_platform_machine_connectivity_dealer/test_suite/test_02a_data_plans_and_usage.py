"""Data plan creation, usage metering, and plan lifecycle guards."""

from test_helpers import (
    ApiErrorId,
    SYSTEM,
    add_machine,
    create_data_plan_payload,
    create_plan,
    ingest_batch,
    make_grower_manager_headers,
    read_plan,
    resume_org,
    setup_connected_machine,
    setup_org_dealer,
    suspend_org,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_data_plan_create_sets_tier_price_and_pending_state(api):
    """PRD section 3.2: "A new plan starts `PENDING` with `monthly_price_cents`
    taken from the tier price table of §2.6, `used_mb` at 0, `usage_posture`
    `NORMAL`, and `cycle_anchor_day`, `cycle_start_date`, and
    `last_proration_charge_cents` all null." PRD section 2.6: "`BASIC` costs
    30000 cents per month and carries a 5120 MB monthly cap; `STANDARD` costs
    60000 cents per month with a 20480 MB cap; `UNLIMITED` costs 120000 cents
    per month and has no cap at all."

    Design: Corner/entities/data_plan_create_sets_tier_price_and_pending_state
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api, serial_number="SN-0001", modem_imei="IMEI-0001")
    machine2 = add_machine(ctx, api, serial_number="SN-0002", modem_imei="IMEI-0002")

    plan = create_plan(ctx, api, machine["id"], tier="STANDARD",
                       proration_method="CALENDAR_DAY")
    assert plan["monthly_price_cents"] == 60000
    assert plan["status"] == "PENDING"
    assert plan["used_mb"] == 0
    assert plan["usage_posture"] == "NORMAL"
    assert plan["cycle_anchor_day"] is None
    assert plan["cycle_start_date"] is None
    assert plan["last_proration_charge_cents"] is None

    plan2 = create_plan(ctx, api, machine2["id"], tier="UNLIMITED",
                        proration_method="THIRTY_DAY")
    assert plan2["monthly_price_cents"] == 120000
    assert plan2["proration_method"] == "THIRTY_DAY"


def test_second_plan_per_machine_rejected(api):
    """PRD section 3.2: "a machine may carry at most one plan in `PENDING`,
    `ACTIVE`, or `SUSPENDED`, with a second attempt rejected as
    `ERR_PLAN_ALREADY_EXISTS`."

    Design: Corner/entities/second_plan_per_machine_rejected
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    create_plan(ctx, api, machine["id"], tier="STANDARD")

    payload = create_data_plan_payload(
        ctx["org"]["id"], machine["id"], tier="BASIC",
        proration_method="CALENDAR_DAY",
    )
    response = api.create_data_plan(payload, headers=ctx["grower_headers"])
    validate_error(response, ApiErrorId.ERR_PLAN_ALREADY_EXISTS)

    rows, _meta = validate_paginated(
        api.list_data_plans(
            headers=ctx["grower_headers"], params={"machine_id": machine["id"]}
        )
    )
    assert len(rows) == 1


def test_plan_resume_from_active_rejected(api):
    """PRD section 3.2: "Resuming returns a `SUSPENDED` plan to `ACTIVE`" — the
    resume transition does not exist from `ACTIVE`, so calling it on an
    already-active plan is a state-precondition failure
    (`ERR_INVALID_STATE_TRANSITION`, PRD section 2.10 step 6).

    Design: Corner/state_machines/plan_resume_from_active_rejected
    """
    ctx = setup_connected_machine(api)
    plan_id = ctx["plan"]["id"]
    response = api.resume_data_plan(plan_id, headers=ctx["grower_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    plan = read_plan(ctx, api, plan_id)
    assert plan["status"] == "ACTIVE"


def test_usage_accumulates_additively_across_batches(api):
    """PRD section 2.6: "Usage accumulates in `used_mb`, which sums the
    `payload_mb` of every accepted telemetry batch in the current cycle." 100
    MB then 150 MB against the 20480 MB STANDARD cap sums to 250 MB and stays
    well below the 0.8 throttle ratio, so `usage_posture` remains `NORMAL`.

    Design: Corner/calculations/usage_accumulates_additively_across_batches
    """
    ctx = setup_connected_machine(api)
    machine_id = ctx["machine"]["id"]
    plan_id = ctx["plan"]["id"]

    ingest_batch(ctx, api, machine_id, batch_id="b-1", payload_mb=100,
                 start_hour_iso="2026-09-01T00:00:00Z")
    ingest_batch(ctx, api, machine_id, batch_id="b-2", payload_mb=150,
                 start_hour_iso="2026-09-01T01:00:00Z")

    plan = read_plan(ctx, api, plan_id)
    assert plan["used_mb"] == 250
    assert plan["usage_posture"] == "NORMAL"


def test_duplicate_telemetry_batch_rejected_without_double_counting(api):
    """PRD section 3.2: "Batches are idempotent per machine by `batch_id`:
    re-submitting an already-accepted `batch_id` for the same machine is
    rejected with `ERR_DUPLICATE_TELEMETRY_BATCH` rather than double-counted."

    Design: Corner/validations/duplicate_telemetry_batch_rejected_without_double_counting
    """
    ctx = setup_connected_machine(api)
    machine_id = ctx["machine"]["id"]
    plan_id = ctx["plan"]["id"]

    ingest_batch(ctx, api, machine_id, batch_id="b-dup", payload_mb=100,
                 start_hour_iso="2026-09-01T00:00:00Z")
    response = api.telemetry_ingest(
        machine_id,
        {
            "batch_id": "b-dup",
            "start_hour_iso": "2026-09-01T02:00:00Z",
            "hour_count": 1,
            "payload_mb": 100,
        },
        headers=SYSTEM,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_TELEMETRY_BATCH)

    plan = read_plan(ctx, api, plan_id)
    assert plan["used_mb"] == 100


def test_plan_create_with_out_of_enum_tier_rejected(api):
    """PRD section 2.10 step 3: "**Request body shape** — required fields are
    present, enum values are inside their declared sets, types are correct"
    (`ERR_INVALID_REQUEST`, HTTP 400). PRD section 3.2 declares "a `tier` of
    `BASIC`, `STANDARD`, or `UNLIMITED`".

    Design: Corner/entities/plan_create_with_out_of_enum_tier_rejected
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    payload = create_data_plan_payload(
        ctx["org"]["id"], machine["id"], tier="PREMIUM",
        proration_method="CALENDAR_DAY",
    )
    response = api.create_data_plan(payload, headers=ctx["grower_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    rows, _meta = validate_paginated(
        api.list_data_plans(
            headers=ctx["grower_headers"], params={"machine_id": machine["id"]}
        )
    )
    assert len(rows) == 0


def test_shape_error_beats_existence_error(api):
    """PRD section 2.10: the platform "reports exactly one error, and the rule
    categories are evaluated in a fixed priority order" — step "3. **Request
    body shape**" runs before step "4. **Existence**", so a malformed body
    (out-of-enum `tier`) on unknown ids yields `ERR_INVALID_REQUEST`, never
    `ERR_NOT_FOUND`.

    Design: Corner/validations/shape_error_beats_existence_error
    """
    missing_org = "00000000-0000-4000-8000-000000000001"
    payload = {
        "organization_id": missing_org,
        "machine_id": "00000000-0000-4000-8000-000000000002",
        "tier": "PREMIUM",
        "proration_method": "CALENDAR_DAY",
    }
    response = api.create_data_plan(
        payload, headers=make_grower_manager_headers(missing_org)
    )
    error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    assert error["error_id"] != "ERR_NOT_FOUND"


def test_plan_resume_while_org_suspended_rejected(api):
    """PRD section 3.2: "Resuming returns a `SUSPENDED` plan to `ACTIVE`, again
    requiring an `ACTIVE` organization (`ERR_ORG_SUSPENDED`) and recomputing
    posture."

    Design: Corner/validations/plan_resume_while_org_suspended_rejected
    """
    ctx = setup_connected_machine(api)
    plan_id = ctx["plan"]["id"]
    suspend_org(api, ctx["org"]["id"])

    response = api.resume_data_plan(plan_id, headers=ctx["grower_headers"])
    validate_error(response, ApiErrorId.ERR_ORG_SUSPENDED)

    resume_org(api, ctx["org"]["id"])
    plan = validate_success(
        api.resume_data_plan(plan_id, headers=ctx["grower_headers"]), 200
    )
    assert plan["status"] == "ACTIVE"


def test_tier_change_to_same_tier_rejected(api):
    """PRD section 3.2: "The `new_tier` must differ from the current `tier`
    (`ERR_TIER_CHANGE_INVALID`)" — a same-tier change computes no proration
    charge and leaves the plan untouched.

    Design: Corner/validations/tier_change_to_same_tier_rejected
    """
    ctx = setup_connected_machine(api)
    plan_id = ctx["plan"]["id"]
    plan = read_plan(ctx, api, plan_id)

    response = api.change_data_plan_tier(
        plan_id,
        {"new_tier": "STANDARD", "expected_plan_version": plan["version"]},
        headers=ctx["grower_headers"],
    )
    validate_error(response, ApiErrorId.ERR_TIER_CHANGE_INVALID)

    plan = read_plan(ctx, api, plan_id)
    assert plan["last_proration_charge_cents"] is None
    assert plan["tier"] == "STANDARD"
