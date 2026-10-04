"""The take-back loop (PRD §3.5): pickup scheduling and collection windows,
sort mass balance at 2dp, the pinned credit rounding order, the dual
STANDARD/CIRCULAR credit variants with the 40% bonus cap, cascade-created
feedstock lots, and terminal-state lockdown.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    collect_takeback,
    create_collection,
    create_collect_payload,
    create_installed_site,
    create_schedule_payload,
    create_site,
    create_sort_payload,
    create_takeback,
    find_lots_by_origin_takeback,
    install_site,
    make_installer_headers,
    make_manager_headers,
    make_specifier_headers,
    schedule_takeback,
    set_clock,
    setup_collected_takeback,
    setup_credited_takeback,
    sort_takeback,
    validate_error,
    validate_success,
    DEFAULT_MANAGER_ID,
)

TEST_MANAGER = make_manager_headers(DEFAULT_MANAGER_ID)


def test_standard_variant_credits_area_only(api):
    """PRD §3.5: "Under the `STANDARD` variant — selected when the collection's
    `claim_intent` is `NONE` — the pathway split is irrelevant and the
    `credit_cents` is simply the base credit rounded half up to whole cents."
    PRD §3.5: "the recovered square meters are multiplied by the grade rate for
    the request's `condition_grade` — 250 cents per square meter for grade `A`,
    150 for grade `B`, and 40 for grade `C`."

    Design: Difficulty/dual_variant_calc/takeback_credit_standard_vs_circular
    """
    set_clock()
    col = create_collection(claim_intent="NONE")
    site = create_installed_site()
    tb = setup_credited_takeback(site, col["id"])
    assert tb["status"] == "CREDITED"
    assert tb["credit_variant"] == "STANDARD"
    # 160 kg / 4.0 = 40.00 m2 x 150 (grade B) = 6000 cents.
    assert tb["credit_cents"] == 6000


def test_circular_variant_adds_capped_pathway_bonus(api):
    """PRD §3.5: "Under the `CIRCULAR` variant — selected when `claim_intent`
    is `CARBON_NEUTRAL` or `CARBON_NEGATIVE` — a pathway bonus is added: the
    raw bonus is `reuse_kg` times 30 cents per kilogram, plus `depolymerize_kg`
    times 18, plus `downcycle_kg` times 6, plus `landfill_kg` times 0; this raw
    bonus is capped at forty percent of the base credit, the cap itself
    computed at 2 decimal places, and the applied bonus is the smaller of the
    cap and the raw bonus; the `credit_cents` is then the base credit plus the
    applied bonus, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/takeback_credit_standard_vs_circular
    """
    set_clock()
    col = create_collection(
        name="Looplet", pattern_code="LOP", backing_type="ADHESIVE_FREE_CAPABLE",
        claim_intent="CARBON_NEUTRAL",
    )
    site = create_installed_site(
        contractor_name="inst-cory",
        address="9 Meadow Ln",
        installation_system="ADHESIVE_FREE",
        adhesive_free_certified=True,
    )
    tb = setup_credited_takeback(site, col["id"])
    assert tb["credit_variant"] == "CIRCULAR"
    # Base 6000; raw bonus 40*30 + 80*18 + 40*6 + 0*0 = 2880 capped to
    # 0.40 * 6000 = 2400.00 -> 8400.
    assert tb["credit_cents"] == 8400


def test_credit_bonus_cap_binds_when_raw_bonus_exceeds_it(api):
    """PRD §3.5: "this raw bonus is capped at forty percent of the base credit,
    the cap itself computed at 2 decimal places, and the applied bonus is the
    smaller of the cap and the raw bonus"

    Design: Difficulty/combinatorial_formula/credit_pathway_bonus_cap_binds
    """
    set_clock()
    col = create_collection(
        name="Looplet", pattern_code="LOP", backing_type="ADHESIVE_FREE_CAPABLE",
        claim_intent="CARBON_NEUTRAL",
    )
    site = create_installed_site()
    tb = setup_credited_takeback(site, col["id"])
    # Grade B 160 kg: base 6000; raw bonus 2880 > cap 2400 -> cap binds.
    assert tb["credit_cents"] == 8400


def test_credit_bonus_passes_through_under_cap_and_cascade_lot(api):
    """PRD §3.5: "the `credit_cents` is then the base credit plus the applied
    bonus, rounded half up to whole cents."
    PRD §2.9 (cascade C): "When a take-back sort records a `depolymerize_kg`
    greater than zero, the system creates a new feedstock lot whose
    `source_type` is `POST_CONSUMER_TILE`, whose `quantity_kg` equals the
    `depolymerize_kg`, whose `carbon_factor_kgco2e_per_kg` is the program
    constant `TAKEBACK_LOT_CARBON_FACTOR`, whose `supplier_name` is the program
    constant `TAKEBACK_SUPPLIER_NAME`, whose status is `RECEIVED`, and whose
    `origin_takeback_id` is the id of the take-back that produced it."

    Design: Difficulty/combinatorial_formula/credit_pathway_bonus_cap_binds
    """
    set_clock()
    col = create_collection(
        name="Looplet", pattern_code="LOP", backing_type="ADHESIVE_FREE_CAPABLE",
        claim_intent="CARBON_NEUTRAL",
    )
    site = create_installed_site()
    tb = setup_credited_takeback(
        site,
        col["id"],
        condition_grade="A",
        sort_overrides={
            "reuse_kg": 10,
            "depolymerize_kg": 20,
            "downcycle_kg": 5,
            "landfill_kg": 125,
        },
    )
    assert tb["credit_variant"] == "CIRCULAR"
    # Grade A: base 40.00 x 250 = 10000; raw bonus 10*30 + 20*18 + 5*6 = 690
    # stays under the 4000 cap -> 10690.
    assert tb["credit_cents"] == 10690
    lots = find_lots_by_origin_takeback(tb["id"])
    assert len(lots) == 1
    lot = lots[0]
    assert lot["quantity_kg"] == 20
    assert lot["source_type"] == "POST_CONSUMER_TILE"
    assert lot["status"] == "RECEIVED"
    assert lot["origin_takeback_id"] == tb["id"]


def test_sort_mass_sum_below_collected_rejected_without_side_effects(api):
    """PRD §3.5: "The sort call records four pathway masses — `reuse_kg`,
    `depolymerize_kg`, `downcycle_kg`, and `landfill_kg` — each of which must
    be zero or greater, and whose sum must equal the request's `collected_kg`
    when compared at 2 decimal places; any imbalance is rejected with
    `ERR_SORT_MASS_IMBALANCE` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/sort_mass_sum_exact_equality
    """
    set_clock()
    col = create_collection(claim_intent="NONE")
    site = create_installed_site()
    tb = setup_collected_takeback(site, col["id"])  # collected 160 kg
    # 40 + 80 + 39.99 + 0 = 159.99 != 160 at 2 decimal places.
    resp = api.sort_takeback(
        tb["id"],
        create_sort_payload(downcycle_kg=39.99),
        make_manager_headers(DEFAULT_MANAGER_ID),
    )
    validate_error(resp, ApiErrorId.ERR_SORT_MASS_IMBALANCE)
    data = validate_success(api.get_takeback_request(tb["id"], TEST_MANAGER))
    assert data["status"] == "COLLECTED"
    assert data["credit_cents"] is None


def test_sort_mass_sum_exact_equality_credits_once(api):
    """PRD §3.5: "A balanced sort moves the request from `COLLECTED` to its
    terminal `CREDITED` state, stamps `credited_at` with the current logical
    clock, computes and stores the `credit_variant` and the `credit_cents`, and
    fires cascade C from §2.9"
    PRD §2.9 (cascade C): "When a take-back sort records a `depolymerize_kg`
    greater than zero, the system creates a new feedstock lot whose
    `source_type` is `POST_CONSUMER_TILE`, whose `quantity_kg` equals the
    `depolymerize_kg`"

    Design: Difficulty/boundary_precision_check/sort_mass_sum_exact_equality
    """
    set_clock()
    col = create_collection(claim_intent="NONE")
    site = create_installed_site()
    tb = setup_collected_takeback(site, col["id"])  # collected 160 kg
    # A failed sort fires nothing...
    validate_error(
        api.sort_takeback(
            tb["id"],
            create_sort_payload(downcycle_kg=39.99),
            make_manager_headers(DEFAULT_MANAGER_ID),
        ),
        ApiErrorId.ERR_SORT_MASS_IMBALANCE,
    )
    # ...and the exact-sum retry lands the terminal state with the credit.
    tb = sort_takeback(tb)
    assert tb["status"] == "CREDITED"
    assert tb["credit_variant"] == "STANDARD"
    assert tb["credit_cents"] == 6000
    lots = find_lots_by_origin_takeback(tb["id"])
    assert len(lots) == 1, "cascade C fired exactly once, on the successful sort"
    assert lots[0]["quantity_kg"] == 80
    assert lots[0]["source_type"] == "POST_CONSUMER_TILE"
    assert lots[0]["status"] == "RECEIVED"
    assert lots[0]["origin_takeback_id"] == tb["id"]


def test_credited_takeback_is_terminal_for_sort_and_cancel(api, admin_headers):
    """PRD §3.5: "`CREDITED` and `CANCELLED` are terminal."
    PRD §2.8 (rule 5): "The target resource is in a state from which the
    requested transition exists; otherwise `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/credited_takeback_is_terminal_for_sort_and_cancel
    """
    set_clock()
    col = create_collection()
    site = create_installed_site()
    tb = setup_credited_takeback(site, col["id"])
    assert tb["credit_cents"] == 6000

    resp = api.sort_takeback(
        tb["id"],
        create_sort_payload(
            reuse_kg=160, depolymerize_kg=0, downcycle_kg=0, landfill_kg=0
        ),
        make_manager_headers(DEFAULT_MANAGER_ID),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    resp = api.cancel_takeback(tb["id"], make_specifier_headers(tb["created_by"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    data = validate_success(api.get_takeback_request(tb["id"], admin_headers))
    assert data["status"] == "CREDITED"
    assert data["credit_cents"] == 6000


def test_collect_before_pickup_window_returns_422(api, admin_headers):
    """PRD §3.5: "the current logical clock must have reached the
    `pickup_window_start` — collecting earlier is rejected with
    `ERR_COLLECT_WINDOW_NOT_OPEN` (HTTP 422)"

    Design: Corner/state_machines/collect_before_pickup_window_returns_422
    """
    set_clock()
    col = create_collection()
    site = create_installed_site()
    tb = create_takeback(site, col["id"])
    tb = schedule_takeback(tb, site)  # window [2026-09-12, 2026-09-13]
    # Clock still reads 2026-09-01T00:00:00Z — the window is not open.
    resp = api.collect_takeback(
        tb["id"],
        create_collect_payload(160),
        make_installer_headers(site["contractor_name"]),
    )
    validate_error(resp, ApiErrorId.ERR_COLLECT_WINDOW_NOT_OPEN)
    data = validate_success(api.get_takeback_request(tb["id"], admin_headers))
    assert data["status"] == "SCHEDULED"
    assert data["collected_kg"] is None
    # Advancing the logical clock into the window opens collection.
    set_clock("2026-09-12T06:00:00Z")
    tb = collect_takeback(tb, site, collected_kg=160)
    assert tb["status"] == "COLLECTED"
    assert tb["collected_kg"] == 160


def test_schedule_window_shape_and_pastness_validated(api, admin_headers):
    """PRD §3.5: "the window must be well-formed, with the start strictly
    earlier than the end, and the start must lie strictly after the current
    logical clock, otherwise `ERR_PICKUP_WINDOW_INVALID` (HTTP 422)."

    Design: Corner/state_machines/schedule_window_shape_and_pastness_validated
    """
    set_clock()
    col = create_collection()
    site = create_installed_site()
    tb1 = create_takeback(site, col["id"])
    tb2 = create_takeback(site, col["id"], condition_grade="A", declared_area_m2=25)
    set_clock("2026-09-12T06:00:00Z")
    installer = make_installer_headers(site["contractor_name"])
    # Inverted window: start not strictly earlier than end.
    resp = api.schedule_takeback(
        tb1["id"],
        create_schedule_payload(
            pickup_window_start="2026-09-20T00:00:00Z",
            pickup_window_end="2026-09-19T00:00:00Z",
        ),
        installer,
    )
    validate_error(resp, ApiErrorId.ERR_PICKUP_WINDOW_INVALID)
    # Well-formed but opening before the current logical clock.
    resp = api.schedule_takeback(
        tb2["id"],
        create_schedule_payload(
            pickup_window_start="2026-09-10T00:00:00Z",
            pickup_window_end="2026-09-20T00:00:00Z",
        ),
        installer,
    )
    validate_error(resp, ApiErrorId.ERR_PICKUP_WINDOW_INVALID)
    for tb in (tb1, tb2):
        data = validate_success(api.get_takeback_request(tb["id"], admin_headers))
        assert data["status"] == "REQUESTED"
        assert data["pickup_window_start"] is None
        assert data["pickup_window_end"] is None


def test_credit_rounding_order_pinned(api):
    """PRD §3.5: "First, recovered area: the `collected_kg` is divided by the
    canonical 4.0 kilograms per square meter and the quotient is rounded half
    up to 2 decimal places — this rounding happens before any money is
    computed, and the alternative order (multiplying mass by the rate and
    dividing once at the end) is a rejected variant that yields different
    cents."

    Design: Corner/calculations/credit_rounding_order_pinned
    """
    set_clock()
    col = create_collection(claim_intent="NONE")
    site = create_installed_site()
    tb = setup_credited_takeback(
        site,
        col["id"],
        collected_kg=160.26,
        sort_overrides={
            "reuse_kg": 40.26,
            "depolymerize_kg": 80,
            "downcycle_kg": 40,
            "landfill_kg": 0,
        },
    )
    assert tb["credit_variant"] == "STANDARD"
    # Pinned: 160.26 / 4.0 = 40.065 -> 40.07 (2dp half-up); 40.07 x 150 =
    # 6010.5 -> 6011 (whole cents half-up). The rejected multiply-first order
    # would give 6010.
    assert tb["credit_cents"] == 6011


def test_lots_traceability_filter_finds_cascade_created_lot(api):
    """PRD §3.2: "Lots can be listed with optional `supplier_name`,
    `source_type`, `status`, and `origin_takeback_id` filters — the last of
    these being the traceability channel that surfaces cascade-created lots."
    PRD §2.9 (cascade C): "whose status is `RECEIVED`, and whose
    `origin_takeback_id` is the id of the take-back that produced it. The new
    lot's `supplier_reliability_pct` is computed at creation exactly like any
    directly posted lot's, grouping on the `TAKEBACK_SUPPLIER_NAME` string."
    (The PRD names but never values TAKEBACK_SUPPLIER_NAME and
    TAKEBACK_LOT_CARBON_FACTOR, so this test pins only the fields the PRD
    derives: quantity, source type, status, origin linkage, and the 100.00
    default reliability of a supplier string with no decided lots.)

    Design: Corner/endpoints/lots_traceability_filter_finds_cascade_created_lot
    """
    set_clock()
    col = create_collection(claim_intent="NONE")
    site = create_installed_site()
    tb = setup_credited_takeback(site, col["id"])  # depolymerize_kg 80
    lots = find_lots_by_origin_takeback(tb["id"])
    assert len(lots) == 1
    lot = lots[0]
    assert lot["quantity_kg"] == 80
    assert lot["source_type"] == "POST_CONSUMER_TILE"
    assert lot["status"] == "RECEIVED"
    assert lot["origin_takeback_id"] == tb["id"]
    assert lot["supplier_reliability_pct"] == 100.00
