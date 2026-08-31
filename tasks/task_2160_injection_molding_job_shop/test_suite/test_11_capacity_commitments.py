"""Selling press capacity ahead of the work, and settling it against what ran."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_capacity_commit,
    create_capacity_commit,
    create_customer,
    create_press,
    read_capacity_commit,
    set_clock,
    setup_running_job,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["plant_admin_headers"]
SE = TEST_USERS["sales_engineer_headers"]

WINDOW = {
    "window_start": "2026-09-15T00:00:00Z",
    "window_end": "2026-09-16T00:00:00Z",
}


def _customer_and_press():
    set_clock()
    return create_customer(), create_press()


def test_strict_settlement_bills_every_unconsumed_minute_at_the_full_press_rate(api):
    """PRD §3.9: "Under **`STRICT`**, every unconsumed committed minute is billed at
    the press's full rate: `shortfall_fee_cents` is `shortfall_minutes` multiplied
    by the press's `hourly_rate_cents`, divided by the 60 minutes in an hour,
    rounded half up. No waiver band exists."
    PRD §3.9: "`utilization_bp` is `consumed_minutes` multiplied by 10,000, divided
    by `committed_minutes`, rounded down. `shortfall_minutes` is `committed_minutes`
    minus `consumed_minutes` when that difference is positive, and 0 otherwise."
    PRD §3.9: "Settlement moves the commitment `OPEN → SETTLED`."

    Design: Difficulty/dual_variant_calc/capacity_commit_strict_vs_goodwill_shortfall
    """
    customer, press = _customer_and_press()
    strict = create_capacity_commit(
        customer["id"], press["id"], committed_minutes=600, shortfall_policy="STRICT", **WINDOW
    )
    create_capacity_commit(
        customer["id"], press["id"], committed_minutes=600, shortfall_policy="GOODWILL", **WINDOW
    )

    data = validate_success(api.settle_capacity_commit(strict["id"], PA))

    assert_capacity_commit(data)
    assert data["consumed_minutes"] == 0
    assert data["shortfall_minutes"] == 600
    assert data["shortfall_fee_cents"] == 72000
    assert data["utilization_bp"] == 0
    assert data["status"] == "SETTLED"


def test_goodwill_settlement_waives_a_tenth_and_bills_the_rest_at_half_rate(api):
    """PRD §3.9: "Under **`GOODWILL`**, a waiver is granted first: the waived
    minutes are `committed_minutes` multiplied by 1,000 basis points — ten percent
    of what was committed — divided by 10,000 and rounded down. The billable minutes
    are `shortfall_minutes` minus those waived minutes when that difference is
    positive, and 0 otherwise. `shortfall_fee_cents` is then the billable minutes
    multiplied by the press's `hourly_rate_cents`, multiplied by 5,000 basis points
    — half the press rate — divided by the product of 60 minutes and 10,000 basis
    points, rounded half up. For identical `committed_minutes` and identical
    consumption, a goodwill commitment therefore settles at a strictly lower fee
    than a strict one whenever any shortfall exists at all."

    Design: Difficulty/dual_variant_calc/capacity_commit_strict_vs_goodwill_shortfall
    """
    customer, press = _customer_and_press()
    strict = create_capacity_commit(
        customer["id"], press["id"], committed_minutes=600, shortfall_policy="STRICT", **WINDOW
    )
    goodwill = create_capacity_commit(
        customer["id"], press["id"], committed_minutes=600, shortfall_policy="GOODWILL", **WINDOW
    )

    settled_strict = validate_success(api.settle_capacity_commit(strict["id"], PA))
    data = validate_success(api.settle_capacity_commit(goodwill["id"], PA))

    assert data["consumed_minutes"] == 0
    assert data["shortfall_minutes"] == 600
    assert data["shortfall_fee_cents"] == 32400, (
        "60 of the 600 shortfall minutes are waived, and 540 bill at half the press rate"
    )
    assert data["utilization_bp"] == 0
    assert data["status"] == "SETTLED"
    assert data["shortfall_fee_cents"] < settled_strict["shortfall_fee_cents"]


def test_a_partly_consumed_strict_commitment_settles_once_and_only_once(api):
    """PRD §3.9: "The consumption set is every job on the commitment's press whose
    `run_status` is `RUNNING` or `COMPLETED`, whose tool belongs to the commitment's
    customer, and whose window sits **entirely** inside the commitment window — that
    is, whose `scheduled_start` is at or after `window_start` and whose
    `scheduled_end` is at or before `window_end`."
    PRD §3.9: "`utilization_bp` is `consumed_minutes` multiplied by 10,000, divided
    by `committed_minutes`, rounded down. `shortfall_minutes` is `committed_minutes`
    minus `consumed_minutes` when that difference is positive, and 0 otherwise."
    PRD §3.9: "Settlement is a `PlantAdmin` act on an `OPEN` commitment and freezes
    all four of those figures at once; settling or cancelling a commitment that is
    not `OPEN` is rejected with `ERR_CAPACITY_COMMIT_NOT_OPEN`."

    Design: Corner/calculations/capacity_commit_settles_partial_consumption_under_strict_policy
    """
    shop = setup_running_job()
    commit = create_capacity_commit(
        shop["customer"]["id"],
        shop["press"]["id"],
        window_start="2026-09-10T00:00:00Z",
        window_end="2026-09-11T00:00:00Z",
        committed_minutes=600,
        shortfall_policy="STRICT",
    )

    settled = validate_success(api.settle_capacity_commit(commit["id"], PA))

    assert settled["status"] == "SETTLED"
    assert settled["consumed_minutes"] == 480
    assert settled["utilization_bp"] == 8000
    assert settled["shortfall_minutes"] == 120
    assert settled["shortfall_fee_cents"] == 14400

    again = api.settle_capacity_commit(commit["id"], PA)
    assert again.status_code == 409, f"Expected 409, got {again.status_code}"
    validate_error(again, ApiErrorId.ERR_CAPACITY_COMMIT_NOT_OPEN.value)
    assert read_capacity_commit(commit["id"])["status"] == "SETTLED"


def test_overlapping_commitments_cannot_oversell_the_presss_available_minutes(api):
    """PRD §3.9: "The commitment is also gated on what the machine can realistically
    deliver: the window's length in whole minutes is multiplied by 8,500 basis
    points — eighty-five percent, the shop's assumed press availability — and
    divided by 10,000, rounded down, to give the available minutes; every other
    commitment on that press whose `status` is `OPEN` and whose window strictly
    overlaps the candidate's, meaning that commitment starts before the candidate's
    window ends and the candidate starts before that commitment's window ends, has
    its `committed_minutes` summed; and if that sum plus the candidate's
    `committed_minutes` exceeds the available minutes, the request is rejected with
    `ERR_CAPACITY_COMMIT_EXCEEDED`."
    PRD §3.9: "A new commitment lands in `OPEN` with `consumed_minutes`,
    `shortfall_minutes`, `shortfall_fee_cents` and `utilization_bp` all at 0."

    Design: Corner/validations/overlapping_capacity_commitments_exceed_press_availability
    """
    customer, press = _customer_and_press()
    create_capacity_commit(
        customer["id"], press["id"], committed_minutes=1000, shortfall_policy="STRICT", **WINDOW
    )

    over = api.create_capacity_commit(
        {
            "customer_id": customer["id"],
            "press_id": press["id"],
            "committed_minutes": 225,
            "shortfall_policy": "GOODWILL",
            **WINDOW,
        },
        SE,
    )
    assert over.status_code == 422, f"Expected 422, got {over.status_code}"
    validate_error(over, ApiErrorId.ERR_CAPACITY_COMMIT_EXCEEDED.value)

    exact = validate_success(
        api.create_capacity_commit(
            {
                "customer_id": customer["id"],
                "press_id": press["id"],
                "committed_minutes": 224,
                "shortfall_policy": "GOODWILL",
                **WINDOW,
            },
            SE,
        ),
        201,
    )
    assert exact["status"] == "OPEN", "1000 + 224 lands exactly on the 1224 available minutes"
    assert exact["consumed_minutes"] == 0
    assert exact["shortfall_minutes"] == 0
    assert exact["shortfall_fee_cents"] == 0
    assert exact["utilization_bp"] == 0

    _, meta = validate_paginated(
        api.list_capacity_commits(PA, params={"press_id": press["id"]})
    )
    assert meta["total_count"] == 2
