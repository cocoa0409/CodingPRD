"""Proving a tool runs at rate on a machine, and routing production onto it."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_press_qualification,
    book_run_at_rate,
    create_customer,
    create_mold,
    create_mold_payload,
    create_press,
    create_press_qualification_payload,
    create_production_job_payload,
    open_qualification,
    qualify_pair,
    read_qualification,
    read_quote,
    set_clock,
    setup_approved_tool,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["plant_admin_headers"]
SE = TEST_USERS["sales_engineer_headers"]
PE = TEST_USERS["process_engineer_headers"]
QE = TEST_USERS["quality_engineer_headers"]


def test_a_failed_junction_row_can_book_a_fresh_trial_and_pass_it(api):
    """PRD §3.2: "Booking is accepted out of `UNQUALIFIED`, out of `FAILED` and out
    of `REVOKED`, and in all three cases moves the row to `RUN_AT_RATE_SCHEDULED`,
    requires that the press's `status` is `AVAILABLE`, and requires that the
    supplied window's start is strictly before its end."
    PRD §3.2: "Rebooking after a failure clears the previously recorded
    `actual_parts_per_hour` back to unset before storing the new window and target,
    so a failed row never carries a stale observation into its next trial."
    PRD §3.2: "If that achievement is at least 9,000 basis points — ninety percent
    of contract, with an exact ninety percent qualifying — the row moves
    `RUN_AT_RATE_SCHEDULED → QUALIFIED`; below it, the row moves
    `RUN_AT_RATE_SCHEDULED → FAILED`. Either verdict stores the observed rate and
    increments `attempt_count` by 1, and the verdict reads only the trial just
    recorded — earlier attempts do not average in. Recording a rate against a row
    that is not in `RUN_AT_RATE_SCHEDULED` is rejected with
    `ERR_RUN_AT_RATE_NOT_SCHEDULED`."

    Design: Corner/state_machines/press_qualification_failed_trial_can_be_rescheduled_and_pass
    """
    set_clock()
    customer = create_customer()
    press = create_press()
    mold = create_mold(customer["id"])
    qualification = qualify_pair(mold["id"], press["id"], actual_parts_per_hour=300)
    assert qualification["status"] == "FAILED"
    assert qualification["attempt_count"] == 1

    repeat = api.record_run_at_rate(
        qualification["id"], {"actual_parts_per_hour": 400}, QE
    )
    assert repeat.status_code == 409, f"Expected 409, got {repeat.status_code}"
    validate_error(repeat, ApiErrorId.ERR_RUN_AT_RATE_NOT_SCHEDULED.value)

    rebooked = validate_success(
        api.schedule_run_at_rate(
            qualification["id"],
            {
                "scheduled_start": "2026-09-03T08:00:00Z",
                "scheduled_end": "2026-09-03T12:00:00Z",
                "target_parts_per_hour": 400,
            },
            PE,
        )
    )
    assert rebooked["status"] == "RUN_AT_RATE_SCHEDULED"
    assert rebooked.get("actual_parts_per_hour") is None

    settled = validate_success(
        api.record_run_at_rate(qualification["id"], {"actual_parts_per_hour": 360}, QE)
    )
    assert_press_qualification(settled)
    assert settled["status"] == "QUALIFIED", (
        "360 * 10000 / 400 == 9000 basis points, exactly ninety percent of contract"
    )
    assert settled["attempt_count"] == 2


def test_duplicate_tool_code_and_duplicate_junction_row_are_both_conflicts(api):
    """PRD §3.1: "Any of the four unique codes in the system — a customer's `code`,
    a press's `press_code`, a mold's `mold_code` or a resin lot's
    `supplier_lot_code` — colliding with an existing record is rejected with
    `ERR_DUPLICATE_CODE`."
    PRD §3.2: "At most one qualification row may exist per tool-and-machine pair; a
    second attempt on the same pair is rejected with `ERR_DUPLICATE_QUALIFICATION`."

    Design: Corner/errors/duplicate_codes_and_duplicate_qualification_return_conflicts
    """
    set_clock()
    customer = create_customer()
    press = create_press()
    mold = create_mold(customer["id"], mold_code="M-1")
    open_qualification(mold["id"], press["id"])

    duplicate_mold = api.create_mold(
        create_mold_payload(
            customer["id"],
            mold_code="M-1",
            cavity_count=2,
            shot_weight_grams=90,
            required_min_tonnage=60,
            required_max_tonnage=120,
            pm_interval_shots=4000,
            tooling_cost_cents=100000,
        ),
        PA,
    )
    assert duplicate_mold.status_code == 409, f"Expected 409, got {duplicate_mold.status_code}"
    validate_error(duplicate_mold, ApiErrorId.ERR_DUPLICATE_CODE.value)

    duplicate_pair = api.create_press_qualification(
        create_press_qualification_payload(mold["id"], press["id"]), PE
    )
    assert duplicate_pair.status_code == 409, f"Expected 409, got {duplicate_pair.status_code}"
    validate_error(duplicate_pair, ApiErrorId.ERR_DUPLICATE_QUALIFICATION.value)

    _, mold_meta = validate_paginated(
        api.list_molds(PA, params={"customer_id": customer["id"]})
    )
    assert mold_meta["total_count"] == 1
    _, pair_meta = validate_paginated(
        api.list_press_qualifications(PE, params={"mold_id": mold["id"]})
    )
    assert pair_meta["total_count"] == 1


def test_pinning_a_press_reports_each_routing_predicate_with_its_own_code(api):
    """PRD §3.6: "A pinned press must be `AVAILABLE`, must sit inside the tool's
    tonnage band, must have a `shot_size_grams_max` at least as large as the tool's
    `shot_weight_grams`, and must carry a `QUALIFIED` qualification row for that
    tool-and-machine pair — a missing or unqualified row is rejected with
    `ERR_PRESS_NOT_QUALIFIED`."
    PRD §2.7: "The press is online, within the tonnage band, large enough in shot
    size, and qualified for the tool — or `ERR_PRESS_OFFLINE`,
    `ERR_PRESS_TONNAGE_MISMATCH`, `ERR_PRESS_SHOT_SIZE_EXCEEDED`,
    `ERR_PRESS_NOT_QUALIFIED` or `ERR_NO_ELIGIBLE_PRESS` (the first at 409, the rest
    at 422)."
    PRD §3.6: "Candidates are ranked by `tonnage` ascending, then `hourly_rate_cents`
    ascending, then `created_at` ascending, and the first is chosen."

    Design: Corner/errors/pinned_press_routing_errors_are_reported_individually
    """
    shop = setup_approved_tool(with_lot=False)
    big = create_press(press_code="P-BIG", tonnage=500, shot_size_grams_max=900)
    small_shot = create_press(press_code="P-SMALLSHOT", tonnage=150, shot_size_grams_max=100)
    alternative = create_press(press_code="P-ALT", tonnage=160, shot_size_grams_max=400)

    def open_job(press_id=None):
        payload = create_production_job_payload(shop["quote"]["id"], planned_qty=1000)
        if press_id:
            payload["press_id"] = press_id
        return api.create_production_job(payload, PE)

    tonnage = open_job(big["id"])
    assert tonnage.status_code == 422, f"Expected 422, got {tonnage.status_code}"
    validate_error(tonnage, ApiErrorId.ERR_PRESS_TONNAGE_MISMATCH.value)

    shot_size = open_job(small_shot["id"])
    assert shot_size.status_code == 422, f"Expected 422, got {shot_size.status_code}"
    validate_error(shot_size, ApiErrorId.ERR_PRESS_SHOT_SIZE_EXCEEDED.value)

    unqualified = open_job(alternative["id"])
    assert unqualified.status_code == 422, f"Expected 422, got {unqualified.status_code}"
    validate_error(unqualified, ApiErrorId.ERR_PRESS_NOT_QUALIFIED.value)

    routed = validate_success(open_job(), 201)
    assert routed["press_id"] == shop["press"]["id"], (
        "the qualified press is the only routing candidate"
    )


def test_taking_a_press_offline_empties_both_selectors(api):
    """PRD §3.1: "The two values `status` may hold are `AVAILABLE` and `OFFLINE`,
    and a `PlantAdmin` moves a machine between them by supplying the new `status`
    together with an optional `note`. Taking a machine `OFFLINE` removes it from the
    candidate set of both press selectors described in §3.3 and §3.6; it does not
    disturb work already booked on it."
    PRD §2.7: "The press is online, within the tonnage band, large enough in shot
    size, and qualified for the tool — or `ERR_PRESS_OFFLINE`,
    `ERR_PRESS_TONNAGE_MISMATCH`, `ERR_PRESS_SHOT_SIZE_EXCEEDED`,
    `ERR_PRESS_NOT_QUALIFIED` or `ERR_NO_ELIGIBLE_PRESS` (the first at 409, the rest
    at 422)."
    PRD §3.6: "An empty candidate set is rejected with `ERR_NO_ELIGIBLE_PRESS`."

    Design: Corner/endpoints/taking_a_press_offline_removes_it_from_both_selectors
    """
    shop = setup_approved_tool(with_lot=False)
    offline = validate_success(
        api.set_press_status(
            shop["press"]["id"], {"status": "OFFLINE", "note": "screw pulled"}, PA
        )
    )
    assert offline["status"] == "OFFLINE"

    payload = create_production_job_payload(
        shop["quote"]["id"], press_id=shop["press"]["id"]
    )
    pinned = api.create_production_job(payload, PE)
    assert pinned.status_code == 409, f"Expected 409, got {pinned.status_code}"
    validate_error(pinned, ApiErrorId.ERR_PRESS_OFFLINE.value)

    unpinned_payload = create_production_job_payload(shop["quote"]["id"])
    unpinned = api.create_production_job(unpinned_payload, PE)
    assert unpinned.status_code == 422, f"Expected 422, got {unpinned.status_code}"
    validate_error(unpinned, ApiErrorId.ERR_NO_ELIGIBLE_PRESS.value)

    _, meta = validate_paginated(
        api.list_production_jobs(PE, params={"quote_id": shop["quote"]["id"]})
    )
    assert meta["total_count"] == 0


def test_a_failed_trial_leaves_the_routing_selector_with_no_candidates(api):
    """PRD §3.6: "Candidates are presses whose `status` is `AVAILABLE`, whose
    `tonnage` sits at or above the tool's `required_min_tonnage` and at or below its
    `required_max_tonnage`, whose `shot_size_grams_max` is at or above the tool's
    `shot_weight_grams`, for which a qualification row with status `QUALIFIED`
    exists on this tool-and-machine pair, and whose existing occupancy does not
    collide with the requested window under the half-open plus 45-minute changeover
    semantics of §2.9."
    PRD §3.6: "An empty candidate set is rejected with `ERR_NO_ELIGIBLE_PRESS`."

    Design: Difficulty/boundary_precision_check/empty_eligible_press_pool_on_job_creation
    """
    shop = setup_approved_tool(trial_actual=300, pin_rate_press=False, with_lot=False)
    qualification = read_qualification(shop["qualification"]["id"])
    assert qualification["status"] == "FAILED", "300 * 10000 / 400 == 7500 basis points"
    assert qualification["attempt_count"] == 1

    response = api.create_production_job(
        create_production_job_payload(shop["quote"]["id"]), PE
    )

    assert response.status_code == 422, f"Expected 422, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_PRESS.value)
    _, meta = validate_paginated(
        api.list_production_jobs(PE, params={"quote_id": shop["quote"]["id"]})
    )
    assert meta["total_count"] == 0


def test_the_quoting_selector_accepts_the_press_the_router_rejects(api):
    """PRD §3.3: "Note carefully what is *not* in that filter: a qualification row
    is deliberately **not** required here, because quoting prices the cheapest
    adequate machine long before any run-at-rate trial exists."
    PRD §3.3: "Whichever way the machine is determined, its id is recorded on the
    quote as `rate_press_id`, and the quote moves `DRAFT → PRICED`."
    PRD §3.6: "An empty candidate set is rejected with `ERR_NO_ELIGIBLE_PRESS`."

    Design: Difficulty/boundary_precision_check/empty_eligible_press_pool_on_job_creation
    """
    shop = setup_approved_tool(trial_actual=300, pin_rate_press=False, with_lot=False)

    quote = read_quote(shop["quote"]["id"])
    assert quote["rate_press_id"] == shop["press"]["id"], (
        "the rate-press selector took the only adequate machine, unqualified or not"
    )
    assert quote["quoted_piece_price_cents"] == 95

    response = api.create_production_job(
        create_production_job_payload(shop["quote"]["id"]), PE
    )
    assert response.status_code == 422, f"Expected 422, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_PRESS.value)
