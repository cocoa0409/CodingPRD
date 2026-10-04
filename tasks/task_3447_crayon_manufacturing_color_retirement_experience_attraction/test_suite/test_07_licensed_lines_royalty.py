"""Licensed/co-branded lines: two-party approval, version pinning, royalties."""
import test_helpers.fixtures as fx
from test_helpers import (
    api_client, ApiErrorId, validate_success, validate_error, get_success_data,
    make_licensor_headers,
)

ADMIN = fx.ADMIN
BRAND = fx.BRAND
BRAND2 = fx.BRAND2


def _formula_v3():
    """Active color + APPROVED formula (version 3). Returns (color, formula)."""
    color = fx.make_active_color()
    formula = fx.create_approved_formula(color["id"])
    assert formula["version"] == 3  # create, submit, approve
    return color, formula


def test_line_licensor_approve_moves_to_brand_review(api):
    """PRD section 3.6: "`SUBMIT`, by a `BrandManager`, moves the line from
    `DRAFT` to `LICENSOR_REVIEW` and records the submitter's `X-User-ID` as
    `submitted_by_user_id`." and "`LICENSOR_APPROVE` advances the line to
    `BRAND_REVIEW`".

    Design: Corner/state_machines/line_licensor_approve_moves_to_brand_review
    """
    fx.reset_clock()
    color, formula = _formula_v3()
    line = fx.create_licensed_line(formula["id"])
    fx.line_transition_ok(line["id"], "SUBMIT", 3, BRAND)
    resp = api_client.licensed_line_transition(
        line["id"], {"action": "LICENSOR_APPROVE", "expected_formula_version": 3},
        make_licensor_headers("lic-1"))
    data = validate_success(resp, 200)
    assert data["status"] == "BRAND_REVIEW"
    assert data["submitted_by_user_id"] == "bm-1"
    assert fx.get_formula(formula["id"])["version"] == 3  # no mutation mid-workflow


def test_line_brand_approve_pins_formula_version(api):
    """PRD section 3.6: "the formula's `licensed_use_count` increments by 1,
    which itself increments the formula's `version` by 1, and the line's
    `pinned_formula_version` is set to the formula's resulting `version`,
    pinning the approval to exactly the formula state the parties reviewed."

    Design: Corner/state_machines/line_brand_approve_pins_formula_version
    """
    fx.reset_clock()
    color, formula = _formula_v3()
    line = fx.create_licensed_line(formula["id"])
    fx.line_transition_ok(line["id"], "SUBMIT", 3, BRAND)
    fx.line_transition_ok(line["id"], "LICENSOR_APPROVE", 3, make_licensor_headers("lic-1"))
    resp = api_client.licensed_line_transition(
        line["id"], {"action": "BRAND_APPROVE", "expected_formula_version": 3}, BRAND2)
    data = validate_success(resp, 200)
    assert data["status"] == "APPROVED"
    assert data["pinned_formula_version"] == 4  # the post-bump version
    formula_now = fx.get_formula(formula["id"])
    assert formula_now["licensed_use_count"] == 1
    assert formula_now["version"] == 4


def test_licensed_spec_without_approved_line_returns_license_required(api):
    """PRD section 3.4: "a `LICENSED` spec must be backed by an `APPROVED`
    licensed line covering one of the spec's colors, else
    `ERR_LICENSE_REQUIRED`".

    Design: Corner/errors/licensed_spec_without_approved_line_returns_license_required
    """
    fx.reset_clock()
    env = fx.production_setup()
    spec_l = fx.create_spec([{"color_id": env["color"]["id"], "count": 8}],
                            name="SpaceMovie 8-box", kind="LICENSED",
                            wholesale_price_cents=2000)
    resp = api_client.create_production_run(
        {"assortment_spec_id": spec_l["id"],
         "pigment_batch_id": env["batch"]["id"], "planned_boxes": 40,
         "planned_start_date": "2027-04-15T00:00:00Z",
         "planned_end_date": "2027-05-20T00:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_LICENSE_REQUIRED)
    assert resp.status_code == 409


def test_line_transition_from_wrong_state_returns_license_state(api):
    """PRD section 3.6: "Any other action attempted from a state that does not
    permit it is rejected with `ERR_LICENSE_STATE` (HTTP 409)."

    Design: Corner/errors/line_transition_from_wrong_state_returns_license_state
    """
    fx.reset_clock()
    color, formula = _formula_v3()
    line = fx.create_licensed_line(formula["id"])  # stays DRAFT
    resp = api_client.licensed_line_transition(
        line["id"], {"action": "LICENSOR_APPROVE", "expected_formula_version": 3},
        make_licensor_headers("lic-1"))
    validate_error(resp, ApiErrorId.ERR_LICENSE_STATE)
    assert resp.status_code == 409
    assert resp.json()["data"]["error_id"] != "ERR_STALE_VERSION"


def test_stale_formula_version_on_line_transition_returns_412(api):
    """PRD section 2.7: "every transition call on a line must carry
    `expected_formula_version`, holding the `version` of the line's formula the
    client last observed. If the formula's current `version` has advanced — for
    example because another line's brand approval incremented
    `licensed_use_count` — the transition is rejected with `ERR_STALE_VERSION`
    (HTTP 412)".

    Design: Corner/validations/stale_formula_version_on_line_transition_returns_412
    """
    fx.reset_clock()
    color, formula = _formula_v3()
    fx.create_approved_licensed_line(formula["id"])  # formula now version 4
    line2 = fx.create_licensed_line(formula["id"], name="Second Line",
                                    royalty_rate=0.1, royalty_base="NET")
    resp = api_client.licensed_line_transition(
        line2["id"], {"action": "SUBMIT", "expected_formula_version": 3}, BRAND)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert resp.status_code == 412
    assert fx.get_line(line2["id"])["status"] == "DRAFT"


def test_occ_stale_beats_state_on_line_transition(api):
    """PRD section 2.7: "a mismatch with the formula's current `version` is
    rejected with `ERR_STALE_VERSION` (HTTP 412) before anything else about the
    transition is considered."

    Design: Corner/validations/occ_stale_beats_state_on_line_transition
    """
    fx.reset_clock()
    color, formula = _formula_v3()
    fx.create_approved_licensed_line(formula["id"])  # formula now version 4
    line2 = fx.create_licensed_line(formula["id"], name="Second Line",
                                    royalty_rate=0.1, royalty_base="NET")
    # DRAFT line cannot be licensor-approved, but the stale version answers first.
    resp = api_client.licensed_line_transition(
        line2["id"], {"action": "LICENSOR_APPROVE", "expected_formula_version": 3},
        make_licensor_headers("lic-1"))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert resp.status_code == 412
    assert resp.json()["data"]["error_id"] != "ERR_LICENSE_STATE"


def test_licensor_cannot_decide_with_mismatched_user(api):
    """PRD section 3.6: "the acting `Licensor`'s `X-User-ID` must equal the
    line's `licensor_user_id`, else `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/licensor_cannot_decide_with_mismatched_user
    """
    fx.reset_clock()
    color, formula = _formula_v3()
    line = fx.create_licensed_line(formula["id"])
    fx.line_transition_ok(line["id"], "SUBMIT", 3, BRAND)
    resp = api_client.licensed_line_transition(
        line["id"], {"action": "LICENSOR_APPROVE", "expected_formula_version": 3},
        make_licensor_headers("lic-9"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert resp.status_code == 403
    assert fx.get_line(line["id"])["status"] == "LICENSOR_REVIEW"


def test_brand_manager_who_submitted_line_cannot_brand_approve(api):
    """PRD section 2.9: "A `BrandManager` brand-approving a licensed line must
    not be the `X-User-ID` recorded as that line's `submitted_by_user_id`." —
    violations are `ERR_SOD_VIOLATION` (HTTP 403).

    Design: Corner/rbac/brand_manager_who_submitted_line_cannot_brand_approve
    """
    fx.reset_clock()
    color, formula = _formula_v3()
    line = fx.create_licensed_line(formula["id"])
    fx.line_transition_ok(line["id"], "SUBMIT", 3, BRAND)
    fx.line_transition_ok(line["id"], "LICENSOR_APPROVE", 3, make_licensor_headers("lic-1"))
    resp = api_client.licensed_line_transition(
        line["id"], {"action": "BRAND_APPROVE", "expected_formula_version": 3}, BRAND)  # bm-1 again
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
    assert resp.status_code == 403
    ok = api_client.licensed_line_transition(
        line["id"], {"action": "BRAND_APPROVE", "expected_formula_version": 3}, BRAND2)
    data = validate_success(ok, 200)
    assert data["status"] == "APPROVED"


def _licensed_spec_with_approved_line():
    """LICENSED spec {color:8} @2000 with an APPROVED line on the color's
    formula, term [2026-09-01T00:00:00Z, 2028-08-31T23:59:59Z]."""
    env = fx.production_setup()
    spec_l = fx.create_spec([{"color_id": env["color"]["id"], "count": 8}],
                            name="SpaceMovie 8-box", kind="LICENSED",
                            wholesale_price_cents=2000)
    line = fx.create_approved_licensed_line(env["formula"]["id"])
    env["spec_l"] = spec_l
    env["line"] = line
    return env


def test_licensed_run_inside_term_is_created(api):
    """PRD section 3.4: "a `LICENSED` spec must be backed by an `APPROVED`
    licensed line covering one of the spec's colors, else
    `ERR_LICENSE_REQUIRED` — with the run's planned dates fully contained
    in that line's term, a temporal-stage check rejected as
    `ERR_LICENSE_TERM_WINDOW`". PRD section 3.6: the term
    brackets "the license term inclusively".

    Design: Difficulty/resource_temporal_overlap/licensed_run_dates_must_be_contained_in_term
    """
    fx.reset_clock()
    env = _licensed_spec_with_approved_line()
    resp = api_client.create_production_run(
        {"assortment_spec_id": env["spec_l"]["id"],
         "pigment_batch_id": env["batch"]["id"], "planned_boxes": 40,
         "planned_start_date": "2027-04-15T00:00:00Z",
         "planned_end_date": "2027-05-20T00:00:00Z"}, ADMIN)
    data = validate_success(resp, 201)
    assert data["stage"] == "PLANNED"


def test_licensed_run_partially_outside_term_returns_term_window(api):
    """PRD section 3.4: the licensed run's planned dates must be "fully
    contained in that line's term, a temporal-stage check rejected as
    `ERR_LICENSE_TERM_WINDOW`" — a run ending 2028-09-05 is past the line's
    term_end 2028-08-31T23:59:59Z even though it starts inside the term.

    Design: Difficulty/resource_temporal_overlap/licensed_run_dates_must_be_contained_in_term
    """
    fx.reset_clock()
    env = _licensed_spec_with_approved_line()
    resp = api_client.create_production_run(
        {"assortment_spec_id": env["spec_l"]["id"],
         "pigment_batch_id": env["batch"]["id"], "planned_boxes": 40,
         "planned_start_date": "2028-08-01T00:00:00Z",
         "planned_end_date": "2028-09-05T00:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_LICENSE_TERM_WINDOW)
    assert resp.status_code == 422
    assert resp.json()["data"]["error_id"] != "ERR_LICENSE_REQUIRED"


def _walk_revision_loop(line_id, frm_v=3):
    """DRAFT -> LICENSOR_REVIEW -> DRAFT -> LICENSOR_REVIEW -> BRAND_REVIEW ->
    LICENSOR_REVIEW -> BRAND_REVIEW, exercising both revision edges."""
    fx.line_transition_ok(line_id, "SUBMIT", frm_v, BRAND)
    fx.line_transition_ok(line_id, "LICENSOR_REQUEST_REVISION", frm_v,
                          make_licensor_headers("lic-1"))
    fx.line_transition_ok(line_id, "SUBMIT", frm_v, BRAND)
    fx.line_transition_ok(line_id, "LICENSOR_APPROVE", frm_v, make_licensor_headers("lic-1"))
    fx.line_transition_ok(line_id, "BRAND_REQUEST_REVISION", frm_v, BRAND2)
    fx.line_transition_ok(line_id, "LICENSOR_APPROVE", frm_v, make_licensor_headers("lic-1"))


def test_licensed_line_revision_loop_reaches_approved(api):
    """PRD section 3.6: "`LICENSOR_REQUEST_REVISION` sends it back to `DRAFT` in
    the licensor-side revision loop" and "`BRAND_REQUEST_REVISION` returns the
    line to `LICENSOR_REVIEW` — the two review states form a negotiation cycle".

    Design: Difficulty/non_linear_state_machine/licensed_line_brand_and_licensor_revision_loop
    """
    fx.reset_clock()
    color, formula = _formula_v3()
    line = fx.create_licensed_line(formula["id"])
    _walk_revision_loop(line["id"], 3)
    resp = api_client.licensed_line_transition(
        line["id"], {"action": "BRAND_APPROVE", "expected_formula_version": 3}, BRAND2)
    data = validate_success(resp, 200)
    assert data["status"] == "APPROVED"


def test_licensed_line_revision_loop_pins_post_bump_version(api):
    """PRD section 3.6: "the formula's `licensed_use_count` increments by 1,
    which itself increments the formula's `version` by 1, and the line's
    `pinned_formula_version` is set to the formula's resulting `version`" — the
    formula was at version 3 going in, so the pin is 4.

    Design: Difficulty/non_linear_state_machine/licensed_line_brand_and_licensor_revision_loop
    """
    fx.reset_clock()
    color, formula = _formula_v3()
    line = fx.create_licensed_line(formula["id"])
    _walk_revision_loop(line["id"], 3)
    api_client.licensed_line_transition(
        line["id"], {"action": "BRAND_APPROVE", "expected_formula_version": 3}, BRAND2)
    line_now = fx.get_line(line["id"])
    assert line_now["status"] == "APPROVED"
    assert line_now["pinned_formula_version"] == 4
    assert line_now["submitted_by_user_id"] == "bm-1"
    formula_now = fx.get_formula(formula["id"])
    assert formula_now["licensed_use_count"] == 1
    assert formula_now["version"] == 4


def _royalty_sales_setup():
    """Two-color env. S1 {c1:8} @1600 with R1 COMPLETED 125 boxes; S2 (duo)
    with R2 completed 78/78 (penalty 76); A1 (PLATINUM, 100) COMMITTED; A2
    (GOLD, 25) COMMITTED then RELEASED. Lifetime gross for c1: 200000 cents,
    returns 40000, penalties 76."""
    env = fx.two_color_production_setup()
    s1 = fx.create_spec([{"color_id": env["color1"]["id"], "count": 8}],
                        name="Cerulean 8-box", wholesale_price_cents=1600)
    r1 = fx.create_run(s1["id"], env["batch"]["id"], planned_boxes=125)
    fx.advance_run_to_packing(r1["id"])
    fx.complete_run(r1["id"], [{"color_id": env["color1"]["id"], "count": 1000}])
    r2 = fx.create_run(env["spec"]["id"], env["batch"]["id"], planned_boxes=10)
    fx.advance_run_to_packing(r2["id"])
    fx.complete_run(r2["id"], [{"color_id": env["color1"]["id"], "count": 78},
                               {"color_id": env["color2"]["id"], "count": 78}])
    a1 = fx.create_allocation(s1["id"], requested_boxes=100)
    fx.allocation_decision(a1["id"], "COMMIT")
    a2 = fx.create_allocation(s1["id"], requested_boxes=25,
                              priority_tier="GOLD", retailer_name="ValueShop")
    fx.allocation_decision(a2["id"], "COMMIT")
    fx.allocation_decision(a2["id"], "RELEASE")
    env["s1"] = s1
    return env


def test_licensed_royalty_gross_base_ignores_returns_and_penalties(api):
    """PRD section 3.6: "First, gross is the sum, over every allocation of
    those specs whose status is `COMMITTED`, `FULFILLED`, `RELEASED`, or
    `SHORTED`, of the allocation's `allocated_boxes_final` multiplied by its
    spec's `wholesale_price_cents`" and "under `GROSS` the base is gross itself,
    returns and penalties ignored" — round_half_up(0.08 x 200000) = 16000.

    Design: Difficulty/dual_variant_calc/licensed_royalty_gross_base_vs_net_base_diverge
    """
    fx.reset_clock()
    env = _royalty_sales_setup()
    line = fx.create_approved_licensed_line(env["formula1"]["id"], royalty_base="GROSS")
    data = fx.get_line(line["id"])
    assert data["status"] == "APPROVED"
    assert data["projected_royalty_cents"] == 16000


def test_licensed_royalty_net_base_subtracts_returns_and_penalties(api):
    """PRD section 3.6: "under `NET` the base is gross minus returns minus
    penalties, floored at 0 — the two variants diverge whenever returns or
    penalties are nonzero" and "`projected_royalty_cents` is the `royalty_rate`
    multiplied by the base, rounded half up to integer cents at this final step
    only" — round_half_up(0.08 x (200000 - 40000 - 76)) = 12794.

    Design: Difficulty/dual_variant_calc/licensed_royalty_gross_base_vs_net_base_diverge
    """
    fx.reset_clock()
    env = _royalty_sales_setup()
    line = fx.create_approved_licensed_line(env["formula1"]["id"], royalty_base="NET")
    data = fx.get_line(line["id"])
    assert data["status"] == "APPROVED"
    assert data["projected_royalty_cents"] == 12794
    # the variants diverge by exactly the returns-plus-penalties term
    assert 16000 - 12794 == 3206  # round_half_up(0.08 * (40000 + 76))


def _net_line_after_commit_release():
    """Single-color env, 125 boxes on hand; A1 (PLATINUM, 100) COMMITTED; A2
    (GOLD, 25) COMMITTED then RELEASED; NET line APPROVED on the formula.
    Gross 200000 (lifetime-committed), returns 40000, penalties 0."""
    env = fx.production_setup_with_completed_run()
    a1 = fx.create_allocation(env["spec"]["id"], requested_boxes=100)
    fx.allocation_decision(a1["id"], "COMMIT")
    a2 = fx.create_allocation(env["spec"]["id"], requested_boxes=25,
                              priority_tier="GOLD", retailer_name="ValueShop")
    fx.allocation_decision(a2["id"], "COMMIT")
    fx.allocation_decision(a2["id"], "RELEASE")
    line = fx.create_approved_licensed_line(env["formula"]["id"], royalty_base="NET")
    env["a1"] = a1
    env["line"] = line
    return env


def test_licensed_royalty_net_counts_released_boxes_in_gross_once(api):
    """PRD section 3.6: "The evaluation order is pinned, because the steps are
    interdependent — gross is established first and is lifetime-committed, not
    currently-committed, and penalties are never subtracted before gross
    exists." — the released allocation sits inside gross at step one and is
    removed exactly once at step two: round_half_up(0.08 x (200000 - 40000)) =
    12800, not the double-netted 9600.

    Design: Difficulty/combinatorial_formula/licensed_royalty_evaluation_order_gross_returns_penalties
    """
    fx.reset_clock()
    env = _net_line_after_commit_release()
    data = fx.get_line(env["line"]["id"])
    assert data["projected_royalty_cents"] == 12800
    assert data["projected_royalty_cents"] != 9600


def test_licensed_royalty_net_unchanged_when_committed_allocation_fulfills(api):
    """PRD section 3.6: "gross is the sum, over every allocation of those specs
    whose status is `COMMITTED`, `FULFILLED`, `RELEASED`, or `SHORTED`" — a
    FULFILL does not leave the gross set and is not a return, so the projection
    stays round_half_up(0.08 x (200000 - 40000)) = 12800 afterwards.

    Design: Difficulty/combinatorial_formula/licensed_royalty_evaluation_order_gross_returns_penalties
    """
    fx.reset_clock()
    env = _net_line_after_commit_release()
    fx.allocation_decision(env["a1"]["id"], "FULFILL")
    data = fx.get_line(env["line"]["id"])
    assert data["projected_royalty_cents"] == 12800
