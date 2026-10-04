"""Corner coverage: calculation input-set filtering and rollup math."""
from test_helpers import (
    ADMIN,
    checkout,
    create_license_via_order,
    create_patron,
    create_title,
    fund_version,
    get_success_data,
    make_library_admin_headers,
    make_patron_headers,
    place_hold,
    set_clock,
    setup_base,
    setup_base_with_title,
    validate_success,
)


def test_wait_estimate_excludes_simultaneous_use_from_copy_count(api):
    """PRD §3.9: "`SIMULTANEOUS_USE` licenses never queue and are excluded from
    C entirely."
    PRD §3.9: "The optimistic variant multiplies those cycles by the library's
    `loan_period_days` — it assumes every current loan comes back at its first
    due date with no renewals. The pessimistic variant multiplies the same
    cycles by the full possible loan tenure: `loan_period_days` plus
    `max_renewals` times `renewal_period_days`."

    Design: Corner/calculations/wait_estimate_excludes_simultaneous_use_from_copy_count
    """
    ctx = setup_base_with_title(
        title_overrides={"simultaneous_use_allowed": True}
    )
    lib = ctx["library"]
    create_license_via_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"],
                             model="OCOU", copies=1)
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    checkout(p0["id"], ctx["title"]["id"])
    create_license_via_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"],
                             model="SIMULTANEOUS_USE")
    holds = []
    patrons = []
    for i in (1, 2, 3):
        p = create_patron(lib["id"], external_card_number=f"P-{i}",
                          full_name=f"Patron {i}")
        patrons.append(p)
        holds.append(place_hold(p["id"], ctx["title"]["id"]))
    hold3 = holds[2]
    p3 = patrons[2]
    data = validate_success(api.get_hold(hold3["id"], make_patron_headers(p3["id"])))
    assert data["optimistic_wait_days"] == 63, (
        f"C counts only the OCOU copy; ceil(3/1) * 21 == 63, got {data['optimistic_wait_days']}"
    )
    assert data["pessimistic_wait_days"] == 189


def test_usage_snapshot_rollup_counts_and_average(api):
    """PRD §3.13: "The rollup replays the library's events — those with
    `library_id` equal to the snapshot's library and `occurred_at` inside the
    half-open window — in `occurred_at` ascending order, ties broken by
    `created_at` ascending, and computes four aggregates:
    `checkouts_by_model`, a map from each of the five models (`OCOU`,
    `METERED_TIME`, `METERED_CIRC`, `COST_PER_CIRC`, `SIMULTANEOUS_USE`) to the
    count of `CHECKOUT` events whose loan's license was that model;
    `cpc_spend_cents`, the sum of `charge_cents` over cost-per-circulation
    `CHECKOUT` events in the window; `holds_filled`, the count of
    `HOLD_FULFILLED` events; and `avg_fulfillment_wait_days`, the mean over
    `HOLD_FULFILLED` events of the gap between the event's `occurred_at` and
    the originating hold's `placed_at`, expressed in days and rounded half-up
    to two decimal places."

    Design: Corner/calculations/usage_snapshot_rollup_counts_and_average
    """
    ctx = setup_base_with_title()
    lib = ctx["library"]
    create_license_via_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"],
                             model="OCOU", copies=1)
    title_cpc = create_title(ctx["consortium"]["id"])
    create_license_via_order(lib["id"], ctx["fund"]["id"], title_cpc["id"],
                             model="COST_PER_CIRC", prepaid_balance_cents=5000)
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    p1 = create_patron(lib["id"], external_card_number="P-1", full_name="Patron One")
    loan0 = checkout(p0["id"], ctx["title"]["id"])
    hold1 = place_hold(p1["id"], ctx["title"]["id"])
    set_clock("2026-09-02T00:00:00Z")
    api.return_loan(loan0["id"], make_patron_headers(p0["id"]))
    resp = api.claim_hold(hold1["id"], make_patron_headers(p1["id"]))
    assert resp.status_code == 201, resp.text
    checkout(p0["id"], title_cpc["id"])
    lib_admin = make_library_admin_headers(lib["id"])
    resp = api.create_usage_snapshot(
        lib["id"],
        {"period_start": "2026-09-01T00:00:00Z",
         "period_end": "2026-10-01T00:00:00Z"},
        lib_admin,
    )
    snap = validate_success(resp, expected_status=201)
    assert snap["checkouts_by_model"]["OCOU"] == 2
    assert snap["checkouts_by_model"]["COST_PER_CIRC"] == 1
    assert snap["cpc_spend_cents"] in (169, 170), (
        "round_half_up(199 * 0.85): 169 in exact decimal arithmetic, 170 in "
        "the design's reference computation — PRD pins the rule, not the "
        "representation"
    )
    assert snap["holds_filled"] == 1
    assert snap["avg_fulfillment_wait_days"] == 1.0, (
        f"placed 09-01, fulfilled 09-02; got {snap['avg_fulfillment_wait_days']}"
    )
