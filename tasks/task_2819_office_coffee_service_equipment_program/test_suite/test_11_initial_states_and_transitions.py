"""Declared state machines: where every row starts, which hops are refused, and
how the two-dimensional rows move one dimension without disturbing the other.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_equipment_asset,
    assert_par_level,
    assert_placement,
    assert_service_visit,
    assert_work_order,
)
from test_helpers.fixtures import (
    CATALOG_SPEC_COFFEE_ONLY,
    advance_work_order,
    assemble_invoice_for,
    cancel_account,
    complete_stop,
    create_account,
    create_asset,
    create_site,
    create_work_order,
    issue_invoice,
    lines_by_type,
    list_placements,
    loaner_return,
    par_line_for,
    place_asset_at_site,
    plan_site,
    read_account,
    read_asset,
    read_invoice,
    read_placement,
    read_site,
    read_visit,
    read_work_order,
    retrieve_placement,
    schedule_stop_with_lines,
    set_clock,
    setup_catalog,
    setup_loaner_out,
    setup_placed_site,
    setup_planned_site,
    setup_second_site,
)
from test_helpers.test_users import TEST_USERS, make_route_technician_headers

AM = TEST_USERS["account_manager_headers"]
BS = TEST_USERS["billing_specialist_headers"]

ANCHOR = "2026-08-03T08:00:00Z"


def test_every_freshly_created_row_lands_on_its_declared_initial_state():
    """Five creations, five birth states — including both dimensions of the two
    rows that carry two, and the onboarding hop that only the placement fires.

    "A newly registered asset starts with `asset_status` `IN_STOCK`,
    `reconditioning_until` null, and `last_descale_at` stamped with the current
    instant — which is why a test that needs a descale-overdue asset registers it
    at an earlier clock position and then advances the clock."

    "The new account is born in `program_posture` `ONBOARDING` with
    `green_price_factor_bps` at `10000` (meaning green-linked prices are
    unmodified), `receivable_balance_cents` at 0, `escalated_site_count` at 0,
    `allied_attachment_bps` at 0, `price_protection_until` null, and `version` 1."

    "The site starts in service posture `ACTIVE`, with `escalation_score` at 0.0,
    `forecast_cups_per_week` at 0, `required_peak_cups_per_hour` at 0,
    `consecutive_shortfall_visit_count` at 0, `recommended_model_id` null,
    `brew_style` null, and `version` 1."

    "Creation stamps `placed_at` with the current instant, starts
    `placement_status` at `ACTIVE` and `compliance_status` at `MEETING_MINIMUM`,
    sets `trailing_purchase_cents`, `shortfall_fee_cents`, `rent_charge_cents` and
    `unreturned_billed_cents` to 0, and leaves the placement's own
    `retrieval_due_by` null."

    "The work order's `site_id` is **copied from the site of that asset's `ACTIVE`
    placement** and is never client-supplied. A new work order starts with
    `wo_status` `OPEN`, `loaner_status` `NONE`, `awaiting_parts_cycles` 0, and
    `parts_eta`, `resolution_note`, `loaner_asset_id`, `loaner_out_date`,
    `loaner_due_back_date` and `loaner_returned_on` all null."

    "The account leaves onboarding the moment equipment is installed anywhere:
    when the first placement of any site of the account reaches an active
    installation state, and the account is still `ONBOARDING`, the system moves
    `program_posture` from `ONBOARDING` to `ACTIVE` and increments the account's
    `version` by 1."

    Design: Corner/state_machines/corner_freshly_created_rows_start_in_their_declared_initial_states
    """
    base = setup_catalog(clock=ANCHOR, catalog_spec=CATALOG_SPEC_COFFEE_ONLY)
    asset = create_asset(base["model"]["id"], serial_number="URN30-0001")
    assert_equipment_asset(asset)
    assert asset["asset_status"] == "IN_STOCK"
    assert asset["reconditioning_until"] is None

    account = create_account(legal_name="Northgate Holdings LLC")
    assert account["program_posture"] == "ONBOARDING"
    assert account["escalated_site_count"] == 0

    site = create_site(account["id"], base["route"]["id"], site_name="HQ Floor 3")
    assert site["service_posture"] == "ACTIVE"
    assert site["escalation_score"] == 0
    site = plan_site(site["id"], "DRIP")
    # Planning is not an installation, so onboarding has not been left yet.
    assert read_account(account["id"])["program_posture"] == "ONBOARDING"

    placement = validate_success(
        api_client.create_placement(
            f.create_placement_payload(
                site["id"],
                asset["id"],
                site["version"],
                terms_type="RENTAL",
                minimum_purchase_cents=60000,
                min_term_months=12,
            ),
            AM,
        ),
        201,
    )
    assert_placement(placement)
    assert placement["placement_status"] == "ACTIVE"
    assert placement["compliance_status"] == "MEETING_MINIMUM"
    assert placement["trailing_purchase_cents"] == 0
    assert placement["shortfall_fee_cents"] == 0
    assert placement["rent_charge_cents"] == 0
    assert placement["unreturned_billed_cents"] == 0
    assert placement["retrieval_due_by"] is None
    assert placement["placed_at"] == ANCHOR

    # Only now does the account leave onboarding.
    assert read_account(account["id"])["program_posture"] == "ACTIVE"

    work_order = create_work_order(asset["id"], base["route"]["id"], "REPAIR")
    assert_work_order(work_order)
    assert work_order["wo_status"] == "OPEN"
    assert work_order["loaner_status"] == "NONE"
    assert work_order["awaiting_parts_cycles"] == 0
    assert work_order["parts_eta"] is None
    assert work_order["resolution_note"] is None
    assert work_order["loaner_asset_id"] is None
    assert work_order["loaner_out_date"] is None
    assert work_order["loaner_due_back_date"] is None
    assert work_order["loaner_returned_on"] is None
    # The site was never supplied: it came from the asset's active placement.
    assert work_order["site_id"] == site["id"]


def test_a_work_order_cannot_jump_from_open_straight_to_resolved():
    """`OPEN` → `RESOLVED` is not one of the four declared hops, so the sign-off is
    refused until the order has actually been worked, and the refusal stamps
    nothing.

    "A `RouteTechnician` drives it by naming a `to_status`, and only four
    transitions are declared: `OPEN` → `IN_PROGRESS`, `IN_PROGRESS` →
    `AWAITING_PARTS`, `AWAITING_PARTS` → `IN_PROGRESS`, and `IN_PROGRESS` →
    `RESOLVED`. Any other requested pair — including anything at all out of
    `RESOLVED` — is rejected with `ERR_WORK_ORDER_STATE_INVALID` (HTTP 409)."

    "Resolving a work order stamps `resolution_note`."

    "Resolving a `DESCALE` order sets the asset's `last_descale_at` to the current
    instant, which is the only way the descale clock is ever reset."

    Design: Corner/state_machines/corner_work_order_cannot_advance_from_open_straight_to_resolved
    """
    base = setup_placed_site(
        clock=ANCHOR,
        terms_type="RENTAL",
        minimum_purchase_cents=60000,
        serial_number="URN30-0001",
        catalog_spec=CATALOG_SPEC_COFFEE_ONLY,
    )
    work_order = create_work_order(base["asset"]["id"], base["route"]["id"], "REPAIR")
    tech = make_route_technician_headers(base["route"]["id"])

    premature = api_client.advance_work_order(
        work_order["id"],
        f.advance_work_order_payload("RESOLVED", resolution_note="Swapped the solenoid"),
        tech,
    )
    validate_error(premature, "ERR_WORK_ORDER_STATE_INVALID", 409)

    unmoved = read_work_order(work_order["id"])
    assert unmoved["wo_status"] == "OPEN"
    assert unmoved["resolution_note"] is None
    assert unmoved["awaiting_parts_cycles"] == 0
    assert unmoved["version"] == work_order["version"]

    working = advance_work_order(work_order["id"], base["route"]["id"], "IN_PROGRESS")
    assert working["wo_status"] == "IN_PROGRESS"

    resolved = validate_success(
        api_client.advance_work_order(
            work_order["id"],
            f.advance_work_order_payload("RESOLVED", resolution_note="Swapped the solenoid"),
            tech,
        ),
        200,
    )
    assert resolved["wo_status"] == "RESOLVED"
    assert resolved["resolution_note"] == "Swapped the solenoid"

    # A repair sign-off is not a descale, so the descale clock is untouched.
    assert read_asset(base["asset"]["id"])["last_descale_at"] == ANCHOR


def test_a_stop_cannot_be_reported_before_its_window_opens_but_may_be_on_it():
    """The completion precondition is inclusive: an hour early it is refused with
    nothing written, and at the window's exact opening instant it goes through.

    "Four gates precede the arithmetic, in this order: the technician must own the
    visit's route (`ERR_ACTOR_NOT_ON_ROUTE`); the site's service posture must be
    `ACTIVE` or `ESCALATED`, so a suspended site refuses completion with
    `ERR_SITE_NOT_SERVICEABLE` even for a visit that is otherwise perfectly
    schedulable; the visit must be `SCHEDULED`, otherwise
    `ERR_VISIT_STATE_INVALID`; and the window must have opened, meaning the current
    instant is at or after `window_start` — an earlier attempt is rejected with
    `ERR_VISIT_NOT_YET_STARTED` (HTTP 422). Only then are the delivered quantities
    validated."

    "The elapsed days are the time from the par line's `last_service_at` to the
    visit's `window_start`, divided by 86400 seconds, rounded down to a whole
    number of days."

    "`stock_status` is always derived, never supplied: it is `STOCKOUT` when
    `on_hand_units` is exactly 0, `LOW` when `on_hand_units` is above 0 and at or
    below `reorder_point_units`, and `IN_STOCK` otherwise."

    "The **below-reorder count** is the number of par lines whose `on_hand_units`
    is above 0 and at or below `reorder_point_units`."

    "A site moves `ACTIVE` → `ESCALATED` when its recomputed score is at or above
    40.0 and it was `ACTIVE`; it moves `ESCALATED` → `ACTIVE` when its recomputed
    score is strictly below 40.0 and it was `ESCALATED`."

    Design: Corner/state_machines/corner_visit_cannot_be_completed_before_its_window_opens
    """
    base = setup_planned_site(clock=ANCHOR, catalog_spec=CATALOG_SPEC_COFFEE_ONLY)
    coffee_id = base["products"]["COFFEE"]["id"]
    visit = schedule_stop_with_lines(base, {"COFFEE": 10})
    assert visit["window_start"] == "2026-08-03T09:00:00Z"

    before = par_line_for(base["site"]["id"], coffee_id)
    assert_par_level(before)
    assert before["par_units"] == 65
    assert before["reorder_point_units"] == 26
    assert before["on_hand_units"] == 0

    tech = make_route_technician_headers(base["route"]["id"])
    payload = f.complete_visit_payload([f.delivered_line(coffee_id, 10)])

    # The clock still reads 08:00 and the window opens at 09:00.
    validate_error(
        api_client.complete_visit(visit["id"], payload, tech),
        "ERR_VISIT_NOT_YET_STARTED",
        422,
    )
    still_scheduled = read_visit(visit["id"])
    assert still_scheduled["visit_status"] == "SCHEDULED"
    assert still_scheduled["completed_at"] is None
    assert par_line_for(base["site"]["id"], coffee_id)["on_hand_units"] == 0

    set_clock("2026-08-03T09:00:00Z")
    completed = validate_success(
        api_client.complete_visit(visit["id"], payload, tech), 200
    )
    assert_service_visit(completed)
    assert completed["visit_status"] == "COMPLETED"
    assert completed["completed_at"] == "2026-08-03T09:00:00Z"

    after = par_line_for(base["site"]["id"], coffee_id)
    assert after["on_hand_units"] == 10
    assert after["cumulative_delivered_units"] == 10
    # An hour of elapsed time is zero whole days, so nothing was drunk.
    assert after["cumulative_consumed_units"] == 0
    assert after["stock_status"] == "LOW"

    site = read_site(base["site"]["id"])
    assert site["escalation_score"] == 7.5
    assert site["service_posture"] == "ACTIVE"


def test_a_fully_credited_invoice_refuses_every_further_transition():
    """A single-line invoice credited to the cent reaches its terminal status, and
    from there both a further credit and a re-issue are refused with the money
    left at zero.

    "A `PRODUCT` line's `amount_cents` is its `qty_units` multiplied by its
    `unit_price_micros`, divided by 10000, rounded half up — **individually, per
    line**."

    "`freight_cents` is 0 when `pre_freight_total_cents` is at or above 50000, and
    otherwise a flat 2500 cents."

    "`line_count` is the number of invoice lines written."

    "`invoice_status` takes the values `DRAFT`, `ISSUED`, `PARTIALLY_CREDITED`,
    `FULLY_CREDITED` and `VOID`, of which `VOID` and `FULLY_CREDITED` are terminal.
    Issuance requires `DRAFT`; crediting requires `ISSUED` or
    `PARTIALLY_CREDITED`; `VOID` and `FULLY_CREDITED` accept neither. Any mismatch
    yields `ERR_INVOICE_STATE_INVALID` (HTTP 409)."

    "The invoice then moves to `PARTIALLY_CREDITED` when the cumulative credits
    after this one are strictly less than the pre-credit total, and to
    `FULLY_CREDITED` when they exactly equal it, at which point the invoice's total
    is 0 and the invoice is terminal."

    Design: Corner/state_machines/corner_fully_credited_invoice_accepts_no_further_transition
    """
    base = setup_planned_site(clock=ANCHOR, catalog_spec=CATALOG_SPEC_COFFEE_ONLY)
    visit = schedule_stop_with_lines(base, {"COFFEE": 112})
    complete_stop(base, visit, {"COFFEE": 112}, complete_at="2026-08-03T09:30:00Z")

    set_clock("2026-09-01T00:00:00Z")
    draft = assemble_invoice_for(
        base["account"]["id"], "2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z"
    )
    assert draft["invoice_status"] == "DRAFT"
    assert draft["line_count"] == 1
    # 112 units at 4500000 micro-dollars is 50400 cents, clearing free freight.
    assert draft["pre_freight_total_cents"] == 50400
    assert draft["allied_discount_bps"] == 0
    assert draft["allied_discount_cents"] == 0
    assert draft["freight_cents"] == 0
    assert draft["total_cents"] == 50400

    issued = issue_invoice(draft["id"])
    assert issued["invoice_status"] == "ISSUED"
    assert issued["issued_at"] == "2026-09-01T00:00:00Z"
    assert read_account(base["account"]["id"])["receivable_balance_cents"] == 50400

    product_line = lines_by_type(issued["id"])["PRODUCT"][0]
    assert product_line["amount_cents"] == 50400

    credit_line = validate_success(
        api_client.credit_invoice(
            issued["id"],
            f.credit_invoice_payload(
                product_line["id"], 50400, credit_reason="Whole delivery rejected at the dock"
            ),
            BS,
        ),
        201,
    )
    assert credit_line["amount_cents"] == -50400

    terminal = read_invoice(issued["id"])
    assert terminal["invoice_status"] == "FULLY_CREDITED"
    assert terminal["total_cents"] == 0
    assert terminal["line_count"] == 2
    assert read_account(base["account"]["id"])["receivable_balance_cents"] == 0

    validate_error(
        api_client.credit_invoice(
            issued["id"],
            f.credit_invoice_payload(product_line["id"], 1, credit_reason="One more cent"),
            BS,
        ),
        "ERR_INVOICE_STATE_INVALID",
        409,
    )
    validate_error(
        api_client.issue_invoice(issued["id"], {}, BS), "ERR_INVOICE_STATE_INVALID", 409
    )

    unchanged = read_invoice(issued["id"])
    assert unchanged["invoice_status"] == "FULLY_CREDITED"
    assert unchanged["total_cents"] == 0
    assert unchanged["line_count"] == 2
    assert unchanged["issued_at"] == "2026-09-01T00:00:00Z"
    assert read_account(base["account"]["id"])["receivable_balance_cents"] == 0


def test_a_second_installation_supersedes_the_first_and_frees_its_brewer():
    """Installing a replacement brewer at the same break room retires the prior
    contract and hands its unit back to stock, and the retired contract is
    terminal.

    "Creation also **supersedes**. If the site already has a placement in `ACTIVE`,
    that prior placement moves `ACTIVE` → `SUPERSEDED` and its asset returns to
    `IN_STOCK`. This is exactly why the write is guarded on the site's `version`: a
    client working from a stale site view would retire a brewer contract it had
    never observed."

    "**The installation dimension** `placement_status` takes the values `ACTIVE`,
    `RETRIEVAL_SCHEDULED`, `RETRIEVED`, `UNRETURNED_BILLED` and `SUPERSEDED`, with
    `RETRIEVED` and `SUPERSEDED` terminal."

    "Retrieval requires the placement to be in `RETRIEVAL_SCHEDULED` or
    `UNRETURNED_BILLED`; from any other installation state it is refused with
    `ERR_PLACEMENT_STATE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/corner_second_placement_supersedes_the_first_and_returns_its_asset_to_stock
    """
    base = setup_placed_site(
        clock=ANCHOR,
        terms_type="RENTAL",
        minimum_purchase_cents=60000,
        serial_number="URN30-0001",
        catalog_spec=CATALOG_SPEC_COFFEE_ONLY,
    )
    first_placement = base["placement"]
    first_asset = base["asset"]
    second_asset = create_asset(base["model"]["id"], serial_number="URN30-0002")

    assert read_placement(first_placement["id"])["placement_status"] == "ACTIVE"
    assert read_asset(first_asset["id"])["asset_status"] == "PLACED"
    assert read_account(base["account"]["id"])["program_posture"] == "ACTIVE"

    site = read_site(base["site"]["id"])
    upgrade = validate_success(
        api_client.create_placement(
            f.create_placement_payload(
                site["id"],
                second_asset["id"],
                site["version"],
                terms_type="LOAN",
                minimum_purchase_cents=90000,
                min_term_months=24,
            ),
            AM,
        ),
        201,
    )
    assert_placement(upgrade)
    assert upgrade["placement_status"] == "ACTIVE"
    assert upgrade["compliance_status"] == "MEETING_MINIMUM"
    assert upgrade["terms_type"] == "LOAN"

    assert read_placement(first_placement["id"])["placement_status"] == "SUPERSEDED"
    assert read_asset(first_asset["id"])["asset_status"] == "IN_STOCK"
    assert read_asset(second_asset["id"])["asset_status"] == "PLACED"

    active = list_placements(site_id=site["id"], placement_status="ACTIVE")
    assert [row["id"] for row in active] == [upgrade["id"]]

    # The onboarding hop fired on the first installation and is not repeated.
    assert read_account(base["account"]["id"])["program_posture"] == "ACTIVE"

    # SUPERSEDED is terminal, so the retired contract cannot be retrieved.
    validate_error(
        api_client.retrieve_placement(
            first_placement["id"], f.retrieve_placement_payload("SERVICEABLE"), AM
        ),
        "ERR_PLACEMENT_STATE_INVALID",
        409,
    )


def test_the_account_closes_only_when_the_last_brewer_has_been_recovered():
    """Two break rooms are unwound one at a time: the first retrieval leaves the
    program cancelling, the second accounts for the last brewer and closes the
    program and its sites together.

    "Hop one: every equipment placement belonging to any site of this account whose
    installation state is `ACTIVE` moves to `RETRIEVAL_SCHEDULED`, and each such
    placement's own `retrieval_due_by` is copied from the account's. Hop two: each
    site owning one of those placements moves its service posture to `SUSPENDED`,
    whether it was `ACTIVE` or `ESCALATED` at the time"

    "The program **closes** only when the equipment is accounted for. When a
    placement retrieval is recorded and, after that retrieval, every placement of
    the account is in one of the terminal-or-billed installation states
    `RETRIEVED`, `UNRETURNED_BILLED` or `SUPERSEDED`, and the account is in
    `CANCELLATION_PENDING`, then the account moves `CANCELLATION_PENDING` →
    `CLOSED`, every site of the account still in `SUSPENDED` moves to `CLOSED`, and
    the account's `version` increments by 1."

    "When the reported condition is `UNSERVICEABLE` the asset moves to `RETIRED`;
    otherwise the asset moves to `RECONDITIONING` with `reconditioning_until` set
    one day past the current instant."

    "The same error and the same rule guard cancellation itself: cancellation is
    permitted from `ONBOARDING`, `ACTIVE` or `AT_RISK`, so a second cancellation
    attempt against an already-cancelling or closed account is refused with
    `ERR_ACCOUNT_NOT_OPERATING`."

    Design: Corner/state_machines/corner_account_closes_when_the_last_placement_is_retrieved
    """
    base = setup_placed_site(
        clock=ANCHOR,
        terms_type="RENTAL",
        minimum_purchase_cents=60000,
        serial_number="URN30-0001",
        catalog_spec=CATALOG_SPEC_COFFEE_ONLY,
    )
    second_site = setup_second_site(base)
    second_asset = create_asset(base["model"]["id"], serial_number="URN30-0002")
    second_placement = place_asset_at_site(
        second_site,
        second_asset["id"],
        terms_type="RENTAL",
        minimum_purchase_cents=60000,
    )

    cancelled = cancel_account(
        base["account"]["id"], retrieval_due_by="2026-09-30T00:00:00Z"
    )
    assert cancelled["program_posture"] == "CANCELLATION_PENDING"
    for placement_id in (base["placement"]["id"], second_placement["id"]):
        placement = read_placement(placement_id)
        assert placement["placement_status"] == "RETRIEVAL_SCHEDULED"
        assert placement["retrieval_due_by"] == "2026-09-30T00:00:00Z"
    for site_id in (base["site"]["id"], second_site["id"]):
        assert read_site(site_id)["service_posture"] == "SUSPENDED"

    first_recovered = retrieve_placement(base["placement"]["id"], "SERVICEABLE")
    assert first_recovered["placement_status"] == "RETRIEVED"
    # One brewer is still unaccounted for, so nothing bubbles up.
    assert read_account(base["account"]["id"])["program_posture"] == "CANCELLATION_PENDING"
    assert read_site(base["site"]["id"])["service_posture"] == "SUSPENDED"
    assert read_site(second_site["id"])["service_posture"] == "SUSPENDED"

    second_recovered = retrieve_placement(second_placement["id"], "SERVICEABLE")
    assert second_recovered["placement_status"] == "RETRIEVED"

    closed = read_account(base["account"]["id"])
    assert closed["program_posture"] == "CLOSED"
    assert closed["cancelled_at"] == ANCHOR
    for site_id in (base["site"]["id"], second_site["id"]):
        assert read_site(site_id)["service_posture"] == "CLOSED"
    for asset_id in (base["asset"]["id"], second_asset["id"]):
        assert read_asset(asset_id)["asset_status"] == "RECONDITIONING"

    # CLOSED is terminal.
    validate_error(
        api_client.cancel_account(base["account"]["id"], f.cancel_account_payload(), AM),
        "ERR_ACCOUNT_NOT_OPERATING",
        409,
    )


def test_the_service_dimension_cycles_while_the_loaner_dimension_holds_the_signoff():
    """The parts cycle runs its full round trip without ever disturbing the
    substitute brewer, and the sign-off stays blocked until that brewer is back.

    "A `MaintenanceWorkOrder` likewise carries `wo_status` (the service dimension)
    and `loaner_status` (the substitute-brewer dimension), and again they advance
    independently — except at one deliberate join point, where a work order cannot
    be resolved while its loaner is still out."

    "A successful swap stamps `loaner_asset_id`, `loaner_out_date` and
    `loaner_due_back_date`, moves `loaner_status` to `OUT`, and moves the loaner
    asset to `ON_LOAN` — passing lazily through `IN_STOCK` first when the asset was
    `RECONDITIONING` with an expired hold."

    "Entering `AWAITING_PARTS` requires a `parts_eta` instant recording when the
    parts are expected, stamps it, and increases `awaiting_parts_cycles` by 1."

    "First, the loaner dimension must be settled: resolution requires
    `loaner_status` to be `NONE`, `RETURNED`, or `WRITTEN_OFF`, and a work order
    whose substitute brewer is still out is refused with `ERR_LOANER_STATE_INVALID`
    (HTTP 409)."

    "Either way the return stamps `loaner_returned_on` with the reported date,
    moves `loaner_status` to `RETURNED`, and moves the loaner asset to
    `RECONDITIONING` with `reconditioning_until` set to the reported return date
    advanced by one day — blocking the next swap for exactly one calendar day."

    Design: Corner/state_machines/corner_loaner_dimension_gates_resolution_while_wo_status_cycles_independently
    """
    base = setup_loaner_out(
        loaner_out_date="2026-08-03T00:00:00Z",
        loaner_due_back_date="2026-08-10T00:00:00Z",
        clock=ANCHOR,
        wo_type="REPAIR",
        loaner_serial="LNR-0001",
        terms_type="RENTAL",
        minimum_purchase_cents=60000,
        serial_number="URN30-0001",
        catalog_spec=CATALOG_SPEC_COFFEE_ONLY,
    )
    work_order = base["work_order"]
    route_id = base["route"]["id"]
    loaner_id = base["loaner_asset"]["id"]
    tech = make_route_technician_headers(route_id)

    assert work_order["loaner_status"] == "OUT"
    assert work_order["loaner_asset_id"] == loaner_id
    assert read_asset(loaner_id)["asset_status"] == "ON_LOAN"

    waiting = advance_work_order(
        work_order["id"], route_id, "AWAITING_PARTS", parts_eta="2026-08-06T00:00:00Z"
    )
    assert waiting["wo_status"] == "AWAITING_PARTS"
    assert waiting["parts_eta"] == "2026-08-06T00:00:00Z"
    assert waiting["awaiting_parts_cycles"] == 1
    # The other dimension did not move.
    assert waiting["loaner_status"] == "OUT"
    assert read_asset(loaner_id)["asset_status"] == "ON_LOAN"

    working = advance_work_order(work_order["id"], route_id, "IN_PROGRESS")
    assert working["wo_status"] == "IN_PROGRESS"
    assert working["awaiting_parts_cycles"] == 1
    assert working["loaner_status"] == "OUT"

    blocked = api_client.advance_work_order(
        work_order["id"],
        f.advance_work_order_payload("RESOLVED", resolution_note="Pump replaced"),
        tech,
    )
    validate_error(blocked, "ERR_LOANER_STATE_INVALID", 409)
    assert read_work_order(work_order["id"])["wo_status"] == "IN_PROGRESS"

    set_clock("2026-08-05T10:00:00Z")
    returned = loaner_return(work_order["id"], route_id, "2026-08-05T00:00:00Z")
    assert returned["loaner_status"] == "RETURNED"
    assert returned["loaner_returned_on"] == "2026-08-05T00:00:00Z"
    assert returned["wo_status"] == "IN_PROGRESS"
    settled_loaner = read_asset(loaner_id)
    assert settled_loaner["asset_status"] == "RECONDITIONING"
    assert settled_loaner["reconditioning_until"] == "2026-08-06T00:00:00Z"

    resolved = validate_success(
        api_client.advance_work_order(
            work_order["id"],
            f.advance_work_order_payload("RESOLVED", resolution_note="Pump replaced"),
            tech,
        ),
        200,
    )
    assert resolved["wo_status"] == "RESOLVED"
    assert resolved["loaner_status"] == "RETURNED"
    assert resolved["awaiting_parts_cycles"] == 1
