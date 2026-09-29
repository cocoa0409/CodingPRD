"""COUNTER usage months, the cost-per-use window and the invoice split."""

from test_helpers import (
    MISSING_UUID,
    assert_allocation_sums_to_total,
    assert_cost_per_use_shape,
    assert_invoice_allocation_shape,
    assert_usage_report,
    create_vendor,
    file_usage,
    make_vendor_rep_headers,
    setup_active_subscription,
    setup_multi_member_subscription,
    usage_report_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_usage_report_before_the_term_start_is_rejected(api, admin):
    """A month one step outside the closed term interval is refused.

    PRD: "The month must lie inside the subscription's term: `period_month` must
    fall within the closed month interval running from the month of `term_start`
    to the month of `term_end`, and a month outside that interval is
    `ERR_USAGE_PERIOD_OUT_OF_TERM` (422)."

    Design: Corner/validations/usage_report_before_the_term_start_is_rejected
    """
    scenario = setup_active_subscription()
    subscription_id = scenario["subscription"]["id"]
    assert scenario["subscription"]["term_start"] == "2027-01-01"

    response = api.create_usage_report(
        subscription_id,
        usage_report_payload(scenario["member"]["id"], "2026-12", 500, 1200, 5),
        make_vendor_rep_headers(scenario["vendor"]["id"]),
    )
    validate_error(response, "ERR_USAGE_PERIOD_OUT_OF_TERM", 422)

    _, meta = validate_paginated(
        api.list_usage_reports(admin, {"subscription_id": subscription_id}))
    assert meta["total_count"] == 0, "the out-of-term month stored no row"


def test_usage_report_in_the_final_month_of_the_term_is_accepted(api):
    """The last month of the term is inside the interval, not past it.

    PRD: "Month intervals derived from a term — the cost-per-use aggregation
    window and the legal range for a usage report's `period_month` — are likewise
    inclusive at both ends."

    Design: Corner/validations/usage_report_in_the_final_month_of_the_term_is_accepted
    """
    scenario = setup_active_subscription()
    subscription_id = scenario["subscription"]["id"]
    member_id = scenario["member"]["id"]
    assert scenario["subscription"]["term_end"] == "2027-12-31"

    response = api.create_usage_report(
        subscription_id,
        usage_report_payload(member_id, "2027-12", 500, 1200, 5),
        make_vendor_rep_headers(scenario["vendor"]["id"]),
    )
    data = validate_success(response, expected_status=201)

    assert_usage_report(data)
    assert data["period_month"] == "2027-12", "the closing month of the term is admissible"
    assert data["full_text_requests"] == 500
    assert data["subscription_id"] == subscription_id
    assert data["member_id"] == member_id


def test_second_usage_report_for_the_same_member_month_is_rejected(api, admin):
    """The uniqueness key is the subscription, member and month triple.

    PRD: "And no two rows may describe the same subscription, member and month; a
    repeat is `ERR_DUPLICATE_USAGE_REPORT` (409)."

    PRD: "Usage rows are append-only ledger entries; they carry no `updated_at`
    and no `version`."

    Design: Corner/validations/second_usage_report_for_the_same_member_month_is_rejected
    """
    scenario = setup_active_subscription()
    subscription_id = scenario["subscription"]["id"]
    member_id = scenario["member"]["id"]
    first = file_usage(subscription_id, scenario["vendor"]["id"], member_id,
                       "2027-01", 500, 1200, 5)

    response = api.create_usage_report(
        subscription_id,
        usage_report_payload(member_id, "2027-01", 900, 2000, 9),
        make_vendor_rep_headers(scenario["vendor"]["id"]),
    )
    validate_error(response, "ERR_DUPLICATE_USAGE_REPORT", 409)

    rows, meta = validate_paginated(
        api.list_usage_reports(admin, {"subscription_id": subscription_id}))
    assert meta["total_count"] == 1, "the repeat created no second row"
    assert rows[0]["id"] == first["id"]
    assert rows[0]["full_text_requests"] == 500, (
        "the refused filing did not overwrite the stored month"
    )


def test_unknown_subscription_path_is_reported_before_invalid_request(api, admin):
    """A defective body cannot outrank a path segment that names nothing.

    PRD: "Asking for the archival checks of a subscription that does not exist
    yields `ERR_SUBSCRIPTION_NOT_FOUND` and never a downstream code, even if the
    rest of the request is also defective."

    Design: Corner/validations/unknown_subscription_path_is_reported_before_invalid_request
    """
    vendor = create_vendor()

    response = api.create_usage_report(
        MISSING_UUID,
        usage_report_payload(MISSING_UUID, "2027-1", -5, 1200, 5),
        make_vendor_rep_headers(vendor["id"]),
    )
    error = validate_error(response, "ERR_SUBSCRIPTION_NOT_FOUND", 404)
    assert error["error_id"] != "ERR_INVALID_REQUEST", (
        "shape checking sits at priority 6, path existence at priority 3"
    )

    _, meta = validate_paginated(api.list_usage_reports(admin))
    assert meta["total_count"] == 0


def test_cost_per_use_over_a_single_month_window_lands_in_the_poor_band(api, admin):
    """Nine million cents over three thousand requests is 3,000 a use.

    PRD: "Otherwise `cost_per_use_cents` is `settled_invoice_total_cents` divided
    by `usage_count`, rounded half up to whole cents."

    PRD: "The `band` reported alongside it is `EXCELLENT` when
    `cost_per_use_cents` is strictly below 500 cents, `GOOD` when it is 500 cents
    or more but strictly below 1,500 cents, and `POOR` at 1,500 cents or above."

    Design: Corner/calculations/cost_per_use_over_a_single_month_window_lands_in_the_poor_band
    """
    scenario = setup_active_subscription()
    subscription_id = scenario["subscription"]["id"]
    file_usage(subscription_id, scenario["vendor"]["id"], scenario["member"]["id"],
               "2027-01", 3000)

    response = api.get_cost_per_use(subscription_id, admin, {"as_of_month": "2027-01"})
    data = validate_success(response)

    assert_cost_per_use_shape(data)
    assert data["usage_count"] == 3000
    assert data["cost_per_use_cents"] == 3000, "9,000,000 divided by 3,000 requests"
    assert data["band"] == "POOR", "3,000 cents a use is at or above the 1,500 threshold"
    assert data["settled_invoice_total_cents"] == 9000000


def test_invoice_allocation_gives_the_single_participant_the_whole_invoice(api, admin):
    """With one confirmed line the exact share is the whole invoice and nothing rounds.

    PRD: "The analysis, also open to the collections office and to member
    libraries, divides the subscription's `negotiated_price_cents` across the
    commitment rows on that subscription whose `status` is `CONFIRMED`."

    PRD: "The invariant the whole procedure exists to guarantee is that the
    `allocated_cents` of all lines sum exactly to `total_cents`."

    Design: Corner/endpoints/invoice_allocation_gives_the_single_participant_the_whole_invoice
    """
    scenario = setup_active_subscription()

    response = api.get_invoice_allocation(scenario["subscription"]["id"], admin)
    data = validate_success(response)

    assert_invoice_allocation_shape(data)
    assert_allocation_sums_to_total(data)
    assert data["total_cents"] == 9000000
    assert len(data["lines"]) == 1, "only the confirmed commitment contributes a line"

    line = data["lines"][0]
    assert line["commitment_id"] == scenario["commitment"]["id"]
    assert line["member_id"] == scenario["member"]["id"]
    assert line["allocated_cents"] == 9000000
    assert line["fte_weight"] == 4000
    assert data["residual_cents"] == 0, "an exact share leaves nothing over"
    assert data["residual_assigned_commitment_id"] == scenario["commitment"]["id"]


def _one_month_of_usage_outside_the_narrow_window():
    """An ACTIVE subscription whose only usage month is 2027-06."""
    scenario = setup_active_subscription()
    scenario["usage"] = file_usage(scenario["subscription"]["id"],
                                   scenario["vendor"]["id"],
                                   scenario["member"]["id"], "2027-06", 5000)
    return scenario


def test_cost_per_use_with_no_usage_in_the_window_returns_null_and_no_use(api, admin):
    """A window that excludes the only filed month divides nothing and errors not.

    PRD: "If `usage_count` is 0, the response reports a `usage_count` of 0, a
    `cost_per_use_cents` of null, a `band` of `NO_USE` and the
    `settled_invoice_total_cents` as stated — division is never attempted and no
    error is raised."

    PRD: "Every usage row of this subscription whose `period_month` falls inside
    that window contributes, no matter which member filed it — all members are
    pooled — and rows for months outside the window are excluded even though they
    belong to the same subscription."

    Design: Difficulty/boundary_precision_check/cost_per_use_with_zero_usage_in_window_returns_null_and_no_use_band
    """
    scenario = _one_month_of_usage_outside_the_narrow_window()

    response = api.get_cost_per_use(scenario["subscription"]["id"], admin,
                                    {"as_of_month": "2027-03"})
    data = validate_success(response)

    assert_cost_per_use_shape(data)
    assert data["usage_count"] == 0, "the window [2027-01, 2027-03] excludes 2027-06"
    assert data["cost_per_use_cents"] is None, "no division was attempted"
    assert data["band"] == "NO_USE"
    assert data["settled_invoice_total_cents"] == 9000000, (
        "the invoice total is reported even with nothing to divide it by"
    )


def test_widening_the_window_to_the_filed_month_produces_a_cost_per_use(api, admin):
    """The same subscription and the same row answer differently once the window reaches it.

    PRD: "The window starts at the year-and-month prefix of the subscription's
    `term_start`. It ends at `as_of_month` when the request supplies it, and
    otherwise at the year-and-month prefix of the logical clock's calendar date.
    The window is **inclusive at both ends**."

    PRD: "The pooled `usage_count` is the sum of `full_text_requests` across the
    contributing rows, and `settled_invoice_total_cents` is the subscription's
    current `negotiated_price_cents`."

    Design: Difficulty/boundary_precision_check/cost_per_use_with_zero_usage_in_window_returns_null_and_no_use_band
    """
    scenario = _one_month_of_usage_outside_the_narrow_window()
    subscription_id = scenario["subscription"]["id"]

    _, meta = validate_paginated(
        api.list_usage_reports(admin, {"subscription_id": subscription_id}))
    assert meta["total_count"] == 1, "the row the narrow window excluded does exist"

    data = validate_success(
        api.get_cost_per_use(subscription_id, admin, {"as_of_month": "2027-06"}))

    assert_cost_per_use_shape(data)
    assert data["usage_count"] == 5000, "the closing month of the window is included"
    assert data["cost_per_use_cents"] == 1800, "9,000,000 divided by 5,000 requests"
    assert data["band"] == "POOR"
    assert data["settled_invoice_total_cents"] == 9000000


def _three_way_invoice_split():
    """Three confirmed members whose exact shares all carry the same fraction."""
    return setup_multi_member_subscription([
        {"name": "Alpha College", "fte_count": 4000},
        {"name": "Bravo University", "fte_count": 4600},
        {"name": "Charlie Institute", "fte_count": 4900},
    ])


def test_invoice_allocation_rounds_each_line_then_assigns_the_residual(api, admin):
    """Three lines round up individually, overshoot by a cent, and give it back.

    PRD: "Round **each line individually** to whole cents, half up. Summing the
    exact shares and rounding the total instead is explicitly forbidden, because
    it distributes the cents differently."

    PRD: "Compute the residual: the subscription's `negotiated_price_cents` minus
    the sum of the rounded lines. The residual may be positive or negative."

    Design: Difficulty/combinatorial_formula/invoice_allocation_rounds_each_line_then_assigns_residual_by_member_created_at
    """
    scenario = _three_way_invoice_split()

    response = api.get_invoice_allocation(scenario["subscription"]["id"], admin)
    data = validate_success(response)

    assert_invoice_allocation_shape(data)
    assert_allocation_sums_to_total(data)
    assert data["total_cents"] == 9000000
    assert len(data["lines"]) == 3

    amounts = [line["allocated_cents"] for line in data["lines"]]
    assert amounts == [2666666, 3066667, 3266667], (
        "each of the three .6667 shares rounds up to 2,666,667 / 3,066,667 / "
        "3,266,667 and the first line then absorbs the residual"
    )
    assert data["residual_cents"] == -1, (
        "9,000,000 less the 9,000,001 the rounded lines summed to"
    )
    assert sum(amounts) == 9000000


def test_the_residual_falls_on_the_earliest_member_when_the_fractions_tie(api, admin):
    """All three fractional parts are equal, so member creation order decides.

    PRD: "Assign the entire residual to a single line — the line whose exact
    unrounded share had the **largest fractional part**, where the fractional part
    is that share minus its whole-number floor. If two lines tie on fractional
    part, the tie is broken by the owning member's `created_at` ascending, and
    then by the commitment's `created_at` ascending."

    PRD: "The lines are ordered by the owning member's `created_at` ascending, and
    where two lines share a member creation instant, by the commitment's own
    `created_at` ascending."

    Design: Difficulty/combinatorial_formula/invoice_allocation_rounds_each_line_then_assigns_residual_by_member_created_at
    """
    scenario = _three_way_invoice_split()
    alpha, bravo, charlie = scenario["members"]

    data = validate_success(
        api.get_invoice_allocation(scenario["subscription"]["id"], admin))

    assert [line["member_id"] for line in data["lines"]] == [
        alpha["id"], bravo["id"], charlie["id"],
    ], "the lines come back in member creation order"
    assert [line["fte_weight"] for line in data["lines"]] == [4000, 4600, 4900]
    assert [line["commitment_id"] for line in data["lines"]] == [
        row["id"] for row in scenario["commitments"]
    ]

    assert data["residual_assigned_commitment_id"] == scenario["commitments"][0]["id"], (
        "Alpha College was registered first, so its line absorbs the tied residual"
    )
    assert data["lines"][0]["allocated_cents"] == 2666666, (
        "Alpha's rounded 2,666,667 is adjusted by the residual of -1"
    )
    assert data["lines"][1]["allocated_cents"] == 3066667, "the other lines keep their rounding"
    assert data["lines"][2]["allocated_cents"] == 3266667
    assert_allocation_sums_to_total(data)
