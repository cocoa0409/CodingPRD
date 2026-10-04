"""Estimate engine and deposit calculations: dual-variant totals, tiers."""
from test_helpers import (
    TEST_USERS,
    create_slot_payload,
    create_specialty_service_payload,
    get_case_itinerary,
    get_success_data,
    hold_slot_fresh,
    issue_estimate_letter,
    set_clock,
    setup_approved_case,
    setup_case_with_holds,
    setup_cleared_case,
    setup_scheduled_case,
    validate_success,
)

FC = TEST_USERS["financial_counselor_headers"]
IC = TEST_USERS["intake_coordinator_headers"]


def _three_hold_setup(api):
    """Domestic 2-specialty case; three same-day holds priced to produce
    fractional cents under the 3-visit 5% tier."""
    ctx = setup_cleared_case()
    case_id = ctx["case"]["id"]
    card, neur = ctx["services"]
    admin = TEST_USERS["platform_admin_headers"]
    slots = [
        get_success_data(api.create_slot(card["id"], create_slot_payload(
            slot_date="2026-09-10", start_min=540, end_min=600), admin)),
        get_success_data(api.create_slot(card["id"], create_slot_payload(
            slot_date="2026-09-10", start_min=600, end_min=660), admin)),
        get_success_data(api.create_slot(neur["id"], create_slot_payload(
            slot_date="2026-09-10", start_min=540, end_min=600), admin)),
    ]
    from test_helpers import hold_slot_fresh as _hold
    prices = [100003, 100005, 100007]
    types = ["CONSULT", "IMAGING", "CONSULT"]
    for i, slot in enumerate(slots):
        _hold(
            case_id, slot["id"], visit_type=types[i],
            listed_price_cents=prices[i], sequencing_priority=i + 1,
        )
    ctx["slots"] = slots
    return ctx


def test_itinerary_provisional_vs_final_rounding_order(api):
    """PRD §3.5: "The **provisional** variant — exposed as
    `provisional_total_cents` and shown on estimate letters as the
    conservative, higher quote — rounds each visit's effective price half-up
    to whole cents first, then sums. The **final** variant — exposed as
    `final_total_cents` and used for settlement billing — sums the unrounded
    per-visit products and rounds the grand total half-up once at the end."

    Design: Difficulty/dual_variant_calc/itinerary_estimate_provisional_vs_final_rounding_order
    """
    set_clock()
    ctx = _three_hold_setup(api)
    itinerary = get_case_itinerary(ctx["case"]["id"])
    # 3 visits -> 5% tier, domestic: per-visit 95002.85 / 95004.75 / 95006.65.
    assert itinerary["provisional_total_cents"] == 285015
    assert itinerary["final_total_cents"] == 285014
    assert (
        itinerary["provisional_total_cents"] - itinerary["final_total_cents"] == 1
    )


def test_provisional_is_never_below_final(api):
    """PRD §3.5: "Whenever any per-visit product carries a fractional cent, the
    provisional total is therefore greater than or equal to the final total,
    and the two diverge."

    Design: Difficulty/dual_variant_calc/itinerary_estimate_provisional_vs_final_rounding_order
    """
    set_clock()
    ctx = _three_hold_setup(api)
    itinerary = get_case_itinerary(ctx["case"]["id"])
    assert itinerary["provisional_total_cents"] >= itinerary["final_total_cents"]


def test_approval_deposit_seed_vs_letter_final_derivation(api):
    """PRD §3.5: "At case-review approval the itinerary has no visits yet, so
    the seed estimate used for the tier computation is the care-team size
    multiplied by 150000 cents per visit — a base visit price — which keeps
    the tier well-defined even against an empty itinerary; this seeded figure
    is what lands in the case's `deposit_amount_cents`."
    PRD §3.5: "The deposit is tiered off the *final* estimate, with inclusive
    lower boundaries: a final estimate of at least 500000 cents takes a 30
    percent deposit; a final estimate of at least 100000 cents but under
    500000 takes 20 percent; anything below 100000 takes 10 percent."

    Design: Difficulty/dual_variant_calc/deposit_estimate_tier_floor_vs_final_variant_dependency
    """
    set_clock()
    ctx = _three_hold_setup(api)
    case_id = ctx["case"]["id"]
    # Approval-time tier floor: 2 specialties * 150000 = 300000 -> 20% = 60000.
    assert ctx["case"]["deposit_amount_cents"] == 60000

    letter = issue_estimate_letter(case_id)
    assert letter["final_estimate_cents"] == 285014
    # round_half_up(285014 * 0.20) = 57003.
    assert letter["deposit_amount_cents"] == 57003
    assert ctx["case"]["deposit_amount_cents"] - letter["deposit_amount_cents"] == 2997


def test_letter_supersedes_and_updates_required_deposit(api):
    """PRD §3.5: "At most one letter per case stands `ISSUED` at a time:
    issuing a fresh letter supersedes the prior one, moving it to
    `SUPERSEDED`, and updates the case clearance's `required_deposit_cents`
    from the new letter's deposit."

    Design: Difficulty/dual_variant_calc/deposit_estimate_tier_floor_vs_final_variant_dependency
    """
    set_clock()
    ctx = _three_hold_setup(api)
    case_id = ctx["case"]["id"]
    letter = issue_estimate_letter(case_id)
    resp = api.get_financial_clearance(ctx["clearance"]["id"], FC)
    clearance = validate_success(resp, 200)
    assert clearance["required_deposit_cents"] == letter["deposit_amount_cents"]


def _four_international_hold_setup(api):
    """International patient, 4-specialty care team, 4 same-day slots on one
    imaging-capable service priced 33333 each."""
    services = []
    admin = TEST_USERS["platform_admin_headers"]
    for code in ("ONC", "ORTH", "GAST", "ENDO"):
        cap = 4 if code == "ONC" else 2
        imaging = code == "ONC"
        services.append(get_success_data(api.create_specialty_service(
            create_specialty_service_payload(
                code=code, name=code, destination_daily_capacity=cap,
                supports_imaging=imaging, supports_remote_products=True,
            ),
            admin,
        )))
    slots = [
        get_success_data(api.create_slot(services[0]["id"], create_slot_payload(
            slot_date="2026-09-11", start_min=s, end_min=s + 60), admin))
        for s in (540, 600, 660, 720)
    ]
    ctx = setup_cleared_case(
        case_type="DESTINATION", team_size=4, services=services,
        patient_overrides={
            "full_name": "Ingrid International",
            "residence_country": "DE",
            "residence_state": None,
            "preferred_language": "de",
        },
        deposit_cents=216000,
    )
    case_id = ctx["case"]["id"]
    types = ["CONSULT", "IMAGING", "LAB_TEST", "CONSULT"]
    for i, slot in enumerate(slots):
        hold_slot_fresh(
            case_id, slot["id"], visit_type=types[i],
            listed_price_cents=33333, sequencing_priority=i + 1,
        )
    ctx["slots"] = slots
    return ctx


def test_tiered_discount_with_international_multiplier(api):
    """PRD §3.5: "The discount percentage is 0 percent when the bundled count
    is at most 2, 5 percent when the bundled count is exactly 3, and 10
    percent when the bundled count is 4 or more. An international multiplier
    of 1.20 applies when the patient `is_international`, and 1.00 otherwise."

    Design: Difficulty/combinatorial_formula/itinerary_estimate_tiered_discount_international_multiplier
    """
    set_clock()
    ctx = _four_international_hold_setup(api)
    itinerary = get_case_itinerary(ctx["case"]["id"])
    # 4 visits -> 10% tier; international 1.20: per-visit 33333*0.9*1.2 = 35999.64.
    assert itinerary["provisional_total_cents"] == 144000
    assert itinerary["final_total_cents"] == 143999


def test_international_multiplier_applies_only_when_international(api):
    """PRD §3.5: "An international multiplier of 1.20 applies when the patient
    `is_international`, and 1.00 otherwise."

    Design: Difficulty/combinatorial_formula/itinerary_estimate_tiered_discount_international_multiplier
    """
    set_clock()
    ctx = _four_international_hold_setup(api)
    itinerary = get_case_itinerary(ctx["case"]["id"])
    # Without the multiplier the provisional total would be 4*30000 = 120000.
    assert itinerary["provisional_total_cents"] > 4 * 30000


def test_deposit_tier_boundary_at_mid_floor(api):
    """PRD §3.5: "Exactly 500000 cents takes the 30 percent tier; exactly
    100000 takes the 20 percent tier."

    Design: Corner/calculations/deposit_tier_boundary_exactly_at_mid_floor
    """
    set_clock()
    # Single 100000-cent visit: bundled count 1 -> 0% discount, final == 100000.
    ctx = setup_case_with_holds([{
        "start_min": 540, "end_min": 600, "visit_type": "CONSULT",
        "listed_price_cents": 100000, "sequencing_priority": 1,
    }])
    case_id = ctx["case"]["id"]
    letter = issue_estimate_letter(case_id)
    assert letter["final_estimate_cents"] == 100000
    assert letter["deposit_amount_cents"] == 20000
    clearance = get_success_data(api.get_case_financial_clearance(case_id, FC))
    assert clearance[0]["required_deposit_cents"] == 20000


def test_cancelled_visits_excluded_from_estimate_input_set(api):
    """PRD §3.5: "The visit set for both variants comprises the itinerary's
    visits in `PENDING`, `CONFIRMED`, or `COMPLETED` status; `CANCELLED` and
    `NO_SHOW` visits are excluded."

    Design: Corner/calculations/cancelled_and_no_show_visits_excluded_from_input_set
    """
    set_clock()
    ctx = setup_case_with_holds([
        {"start_min": 540, "end_min": 600, "visit_type": "CONSULT",
         "listed_price_cents": 200000, "sequencing_priority": 1},
        {"start_min": 600, "end_min": 660, "visit_type": "IMAGING",
         "listed_price_cents": 200000, "sequencing_priority": 2},
    ])
    case_id = ctx["case"]["id"]
    itinerary_before = get_case_itinerary(case_id)
    assert itinerary_before["provisional_total_cents"] == 400000

    resp = api.release_slot(ctx["slots"][1]["id"], IC)
    validate_success(resp, 200)
    itinerary_after = get_case_itinerary(case_id)
    # 2 visits -> 0% tier; after release only one 200000 visit remains.
    assert itinerary_after["provisional_total_cents"] == 200000
    assert itinerary_after["final_total_cents"] == 200000
    assert itinerary_after["revision"] == itinerary_before["revision"] + 1


def test_estimate_letter_staleness_reacts_to_revision(api):
    """PRD §3.5: "A letter's `is_stale` flag is computed, not stored: it is
    true exactly when `itinerary_revision_at_issue` is lower than the
    itinerary's current `revision` — so any confirmed-slot reschedule or
    cancellation that bumped the revision instantly stales the outstanding
    letter, and travel authorization (§3.6) will refuse to rely on it."

    Design: Corner/calculations/estimate_letter_staleness_flag_reacts_to_revision
    """
    set_clock()
    ctx = setup_scheduled_case()
    case_id = ctx["case"]["id"]
    letter = issue_estimate_letter(case_id)
    assert letter["is_stale"] is False
    revision_at_issue = letter["itinerary_revision_at_issue"]

    visit_id = ctx["visits"][0]["id"]
    resp = api.cancel_visit(visit_id, IC)
    validate_success(resp, 200)

    letters = get_success_data(api.list_estimate_letters(case_id, FC))
    stale = {l["id"]: l for l in letters}[letter["id"]]
    assert stale["is_stale"] is True
    itinerary = get_case_itinerary(case_id)
    assert itinerary["revision"] == revision_at_issue + 1


def test_estimate_letter_issuance_supersedes_prior_letter(api):
    """PRD §3.5: "At most one letter per case stands `ISSUED` at a time:
    issuing a fresh letter supersedes the prior one, moving it to
    `SUPERSEDED`, and updates the case clearance's `required_deposit_cents`
    from the new letter's deposit."

    Design: Corner/endpoints/estimate_letter_issuance_supersedes_prior_letter
    """
    set_clock()
    ctx = setup_case_with_holds([{"start_min": 540, "end_min": 600}])
    case_id = ctx["case"]["id"]
    letter_a = issue_estimate_letter(case_id)
    letter_b = issue_estimate_letter(case_id)
    letters = get_success_data(api.list_estimate_letters(case_id, FC))
    by_id = {l["id"]: l for l in letters}
    assert by_id[letter_a["id"]]["status"] == "SUPERSEDED"
    assert by_id[letter_b["id"]]["status"] == "ISSUED"
    assert sum(1 for l in letters if l["status"] == "ISSUED") == 1


def test_itinerary_get_returns_computed_totals_and_revision(api):
    """PRD §3.5: "The estimate engine maintains two variants of the itinerary
    total in parallel, recomputed whenever the visit set changes — on every
    slot hold, every slot release, every visit cancellation, and at
    estimate-letter issuance."
    PRD §3.3: "An `APPROVE` outcome moves the case `INTAKE →
    AWAITING_FINANCIAL` and performs a multi-resource fan-out: for
    `DESTINATION` cases an `Itinerary` is created in `DRAFT` status at
    `revision` 1; a `FinancialClearance` is created in `PENDING` status with
    `deposit_paid_cents` 0; the case's `deposit_amount_cents` is computed from
    the tiered deposit rule of §3.5 — at approval the itinerary is still
    empty, so the tier floor applies against a base estimate seeded from the
    care-team size; and the owning referral advances `IN_REVIEW → REVIEWED`."

    Design: Corner/entities/itinerary_get_returns_computed_totals_and_revision
    """
    set_clock()
    ctx = setup_approved_case()
    itinerary = ctx["itinerary"]
    resp = api.get_itinerary(itinerary["id"], IC)
    data = validate_success(resp, 200)
    assert data["status"] == "DRAFT"
    assert data["revision"] == 1
    assert data["provisional_total_cents"] == 0
    assert data["final_total_cents"] == 0
