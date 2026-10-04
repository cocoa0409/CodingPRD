"""Sell-through reporting, coverage attainment (ACTUAL/PROJECTED variants),
the SANCTION cascade, and the rebate preview."""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, assert_rebate_preview,
    assert_sell_through_report, make_distributor_contact_headers,
    validate_error, validate_success,
)
from test_helpers import fixtures as fx

CM = TEST_USERS["channel_manager_headers"]


def test_attainment_actual_vs_projected_diverge():
    """PRD §3.6: "The **ACTUAL** variant is conservative: it sums `net_units` across the in-scope assignments' reports inside the window into a total, and sums a three-month quota built as the per-assignment floor of `annual_quota_units` divided by 4; `attainment_actual_bps` is then 0 when that quota sums to zero, and otherwise 10000 times the total net divided by the three-month quota, rounded half up to integer basis points."
    PRD §3.6: "The **PROJECTED** variant is deliberately optimistic: it takes the single best window month — summing `net_units` per month, with a missing month counting as 0 — annualizes that best month by multiplying by 12, and divides by the full annual quota (the sum of `annual_quota_units` over the in-scope assignments); `attainment_projected_bps` is 0 when that annual quota is zero, and otherwise 10000 times the annualized best month divided by the annual quota, again rounded half up."
    PRD §3.6: "The tier derives from `attainment_actual_bps` alone: `GOLD` at 12000 or above, `STANDARD` at 10000 or above, `WATCH` at 9000 or above, and `SANCTION` below that. When a recomputation lands the tier on `SANCTION` while the distributor is `APPROVED`, the suspension machinery of §3.5 fires automatically — suspension and assignment cascade, or outright termination on the third strike."

    Design: Difficulty/dual_variant_calc/attainment_actual_vs_projected_diverge
    """
    sc = fx.setup_active_coverage(quota=1200, exclusive=True)
    dist_id = sc["distributor"]["id"]
    asg_id = sc["assignment"]["id"]

    fx.file_sell_through_report(dist_id, asg_id, "2026-06", 30)
    mid = validate_success(api_client.get_distributor(dist_id, CM))
    assert mid["attainment_actual_bps"] == 1000, \
        "round_half_up(10000 * 30 / floor(1200/4)=300)"
    assert mid["status"] == "SUSPENDED", \
        "the first report already flipped the tier to SANCTION and cascaded"

    fx.file_sell_through_report(dist_id, asg_id, "2026-08", 90)
    dist = validate_success(api_client.get_distributor(dist_id, CM))
    assert dist["attainment_actual_bps"] == 4000, \
        "round_half_up(10000 * 120 / 300)"
    assert dist["attainment_projected_bps"] == 9000, \
        "round_half_up(10000 * 90 * 12 / 1200): best month 2026-08 net 90"
    assert dist["attainment_actual_bps"] != dist["attainment_projected_bps"], \
        "the two variants diverge over identical report data"
    assert dist["quota_compliance_tier"] == "SANCTION"
    assert dist["status"] == "SUSPENDED"

    preview = validate_success(api_client.get_rebate_preview(dist_id, 499, CM))
    assert_rebate_preview(preview)
    assert preview["attainment_actual_bps"] == 4000
    assert preview["attainment_projected_bps"] == 9000
    assert preview["quota_compliance_tier"] == "SANCTION"
    assert preview["window_net_units"] == 120


def test_sanction_attainment_cascade_distributor_assignments():
    """PRD §3.6: "Every accepted report recomputes the distributor's **coverage attainment**".
    PRD §3.6: "When a recomputation lands the tier on `SANCTION` while the distributor is `APPROVED`, the suspension machinery of §3.5 fires automatically — suspension and assignment cascade, or outright termination on the third strike."
    PRD §3.5: "Suspending an `APPROVED` distributor — whether by a `ChannelManager`'s manual action or automatically when an attainment recomputation flips its tier to `SANCTION` — increments `suspension_count` by one and cascades every `ACTIVE` coverage assignment of the distributor to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/sanction_attainment_cascade_distributor_assignments
    """
    sc = fx.setup_active_coverage(quota=1200)
    dist_id = sc["distributor"]["id"]
    asg_id = sc["assignment"]["id"]

    report = fx.file_sell_through_report(dist_id, asg_id, "2026-06", 200)
    assert report["net_units"] == 200

    dist = validate_success(api_client.get_distributor(dist_id, CM))
    assert dist["attainment_actual_bps"] == 6667, \
        "round_half_up(10000 * 200 / 300)"
    assert dist["quota_compliance_tier"] == "SANCTION"
    assert dist["status"] == "SUSPENDED", \
        "cascade link 1 fired from the report, not from any distributor endpoint"
    assert dist["suspension_count"] == 1

    asg = validate_success(api_client.get_coverage_assignment(asg_id, CM))
    assert asg["status"] == "SUSPENDED", "cascade link 2"


def test_distributor_rebate_tiered_selection_with_mass_bonus_and_cap():
    """PRD §3.6: "The rate is tier-driven: `GOLD` earns 300 basis points, `STANDARD` 200, `WATCH` 100, `SANCTION` 0, and a null tier earns 0; serving the `MASS` channel adds a 25-basis-point bonus; the sum is capped at 350. The estimate multiplies the trailing-three-month net-units total by `reference_unit_price_cents` and by `rebate_bps` per ten thousand, rounding half up to whole cents."
    PRD §3.5: "Reinstatement returns a `SUSPENDED` distributor to `APPROVED`" — reinstatement is an explicit act, so the June SANCTION strike's suspension survives the later recovery to GOLD.

    Design: Difficulty/combinatorial_formula/distributor_rebate_tiered_selection_with_mass_bonus_and_cap
    """
    sc = fx.setup_active_coverage(quota=1000,
                                  channels_served=["HARDWARE", "MASS"])
    dist_id = sc["distributor"]["id"]
    asg_id = sc["assignment"]["id"]
    fx.file_reports(dist_id, asg_id, [
        {"period_month": "2026-06", "units_sold": 100},
        {"period_month": "2026-07", "units_sold": 100},
        {"period_month": "2026-08", "units_sold": 100},
    ])

    dist = validate_success(api_client.get_distributor(dist_id, CM))
    assert dist["attainment_actual_bps"] == 12000, \
        "round_half_up(10000 * 300 / floor(1000/4)=250) — the GOLD boundary, inclusive"
    assert dist["attainment_projected_bps"] == 12000, "best month 100 annualized"
    assert dist["quota_compliance_tier"] == "GOLD"
    assert dist["status"] == "SUSPENDED", \
        "the June report alone (attainment 4000) already cascaded a SANCTION suspension"

    preview = validate_success(api_client.get_rebate_preview(dist_id, 499, CM))
    assert_rebate_preview(preview)
    assert preview["quota_compliance_tier"] == "GOLD"
    assert preview["rebate_bps"] == 325, "min(300 GOLD base + 25 MASS bonus, 350)"
    assert preview["window_net_units"] == 300
    assert preview["rebate_estimate_cents"] == 4865, \
        "round_half_up(300 * 499 * 325 / 10000) = round_half_up(4865.25)"


def test_sell_through_report_carries_no_version_or_updated_at():
    """PRD §2.5: "The sole exception is the sell-through report. A `SellThroughReport` is immutable once filed and carries only `id` and `created_at`; both `updated_at` and `version` are absent from it."
    PRD §3.6: "The stored `net_units` is the larger of zero and `units_sold` minus `units_returned`."
    PRD §4: "Operations that create a new resource return `201 Created`; operations that modify, transition or compute against an existing resource return `200 OK`."

    Design: Corner/entities/sell_through_report_carries_no_version_or_updated_at
    """
    sc = fx.setup_active_coverage()
    dist_id = sc["distributor"]["id"]
    resp = api_client.create_sell_through_report(
        dist_id,
        {"coverage_assignment_id": sc["assignment"]["id"],
         "period_month": "2026-08", "units_sold": 7, "units_returned": 2},
        make_distributor_contact_headers(dist_id))
    data = validate_success(resp, 201)
    assert_sell_through_report(data)
    assert data["distributor_id"] == dist_id
    assert data["coverage_assignment_id"] == sc["assignment"]["id"]
    assert data["period_month"] == "2026-08"
    assert data["units_sold"] == 7 and data["units_returned"] == 2
    assert data["net_units"] == 5, "max(0, 7 - 2)"


def test_attainment_window_excludes_out_of_window_reports():
    """PRD §3.6: "Every accepted report recomputes the distributor's **coverage attainment**, in two variants over the same window — the three calendar months strictly before the current logical month, matched by `period_month`."

    Design: Corner/calculations/attainment_window_excludes_out_of_window_reports
    """
    sc = fx.setup_active_coverage(quota=1200)
    dist_id = sc["distributor"]["id"]
    asg_id = sc["assignment"]["id"]

    fx.file_sell_through_report(dist_id, asg_id, "2026-06", 270)
    before = validate_success(api_client.get_distributor(dist_id, CM))
    assert before["attainment_actual_bps"] == 9000, \
        "round_half_up(10000 * 270 / 300)"
    assert before["quota_compliance_tier"] == "WATCH"

    old = fx.file_sell_through_report(dist_id, asg_id, "2026-05", 500)
    assert old["net_units"] == 500, \
        "the 2026-05 report is accepted (a completed month) but outside the window"

    after = validate_success(api_client.get_distributor(dist_id, CM))
    assert after["attainment_actual_bps"] == 9000, \
        "2026-05 is outside {2026-06, 2026-07, 2026-08} and changes nothing"
    assert after["quota_compliance_tier"] == "WATCH"
    assert after["status"] == "APPROVED", "WATCH is not SANCTION — no cascade"


def test_net_units_floors_at_zero_and_triggers_sanction():
    """PRD §3.6: "The stored `net_units` is the larger of zero and `units_sold` minus `units_returned`."
    PRD §3.6: "When a recomputation lands the tier on `SANCTION` while the distributor is `APPROVED`, the suspension machinery of §3.5 fires automatically — suspension and assignment cascade, or outright termination on the third strike."

    Design: Corner/calculations/net_units_floors_at_zero_and_triggers_sanction
    """
    sc = fx.setup_active_coverage(quota=1200)
    dist_id = sc["distributor"]["id"]
    asg_id = sc["assignment"]["id"]

    resp = api_client.create_sell_through_report(
        dist_id,
        {"coverage_assignment_id": asg_id, "period_month": "2026-08",
         "units_sold": 10, "units_returned": 25},
        make_distributor_contact_headers(dist_id))
    data = validate_success(resp, 201)
    assert data["net_units"] == 0, "max(0, 10 - 25), never negative"

    dist = validate_success(api_client.get_distributor(dist_id, CM))
    assert dist["attainment_actual_bps"] == 0
    assert dist["quota_compliance_tier"] == "SANCTION"
    assert dist["status"] == "SUSPENDED"

    asg = validate_success(api_client.get_coverage_assignment(asg_id, CM))
    assert asg["status"] == "SUSPENDED"


def test_rebate_preview_null_tier_without_assignments():
    """PRD §3.5: "its attainment fields `attainment_actual_bps` and `attainment_projected_bps` and its `quota_compliance_tier` are null until the first attainment recomputation (§3.6)."
    PRD §3.6: "It answers with the distributor's current `attainment_actual_bps`, `attainment_projected_bps` and `quota_compliance_tier` (each possibly null), plus a `rebate_bps` rate and a monetary `rebate_estimate_cents`, and the `window_net_units` total it was priced from."
    PRD §3.6: "The rate is tier-driven: `GOLD` earns 300 basis points, `STANDARD` 200, `WATCH` 100, `SANCTION` 0, and a null tier earns 0".

    Design: Corner/calculations/rebate_preview_null_tier_without_assignments
    """
    fx.create_brand()
    market = fx.create_market()
    dist = fx.create_approved_distributor(market["id"])

    preview = validate_success(api_client.get_rebate_preview(dist["id"], 499, CM))
    assert_rebate_preview(preview)
    assert preview["attainment_actual_bps"] is None
    assert preview["attainment_projected_bps"] is None
    assert preview["quota_compliance_tier"] is None
    assert preview["rebate_bps"] == 0
    assert preview["window_net_units"] == 0
    assert preview["rebate_estimate_cents"] == 0


def test_duplicate_report_same_assignment_month_rejected():
    """PRD §3.6: "each assignment admits exactly one report per month, a duplicate drawing `ERR_DUPLICATE_REPORT` (HTTP 409)."

    Design: Corner/validations/duplicate_report_same_assignment_month_rejected
    """
    sc = fx.setup_active_coverage(quota=1200)
    dist_id = sc["distributor"]["id"]
    asg_id = sc["assignment"]["id"]
    contact = make_distributor_contact_headers(dist_id)

    first = api_client.create_sell_through_report(
        dist_id, {"coverage_assignment_id": asg_id, "period_month": "2026-08",
                  "units_sold": 400}, contact)
    validate_success(first, 201)

    dup = api_client.create_sell_through_report(
        dist_id, {"coverage_assignment_id": asg_id, "period_month": "2026-08",
                  "units_sold": 999}, contact)
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_REPORT)

    dist = validate_success(api_client.get_distributor(dist_id, CM))
    assert dist["attainment_actual_bps"] == 13333, \
        "attainment reflects only the first filing: round_half_up(10000 * 400 / 300)"


def test_sell_through_report_requires_owning_distributor_contact():
    """PRD §3.6: "A **SellThroughReport** is filed under a distributor's path by a `DistributorContact` whose `X-User-ID` must equal that path distributor's `id` — a mismatch is refused with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/validations/sell_through_report_requires_owning_distributor_contact
    """
    sc = fx.setup_active_coverage()
    dist_id = sc["distributor"]["id"]

    resp = api_client.create_sell_through_report(
        dist_id,
        {"coverage_assignment_id": sc["assignment"]["id"],
         "period_month": "2026-08", "units_sold": 10},
        make_distributor_contact_headers("dist-impostor"))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


def test_report_period_must_be_completed():
    """PRD §3.6: "The period must be a **completed** month, strictly before the current logical month — reporting the in-progress month or a future one is refused with `ERR_PERIOD_NOT_COMPLETED` (HTTP 422)".

    Design: Corner/validations/report_period_must_be_completed
    """
    sc = fx.setup_active_coverage()
    dist_id = sc["distributor"]["id"]
    contact = make_distributor_contact_headers(dist_id)

    current = api_client.create_sell_through_report(
        dist_id, {"coverage_assignment_id": sc["assignment"]["id"],
                  "period_month": "2026-09", "units_sold": 10}, contact)
    validate_error(current, ApiErrorId.ERR_PERIOD_NOT_COMPLETED)

    future = api_client.create_sell_through_report(
        dist_id, {"coverage_assignment_id": sc["assignment"]["id"],
                  "period_month": "2026-10", "units_sold": 10}, contact)
    validate_error(future, ApiErrorId.ERR_PERIOD_NOT_COMPLETED)
