"""The revision loop, the expiry instant, and the franchise standing above a quote."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_QUOTE_EXPIRED,
    ERR_REVISION_LIMIT_REACHED,
    ERR_TERRITORY_NOT_ACTIVE,
)
from test_helpers.assertions import assert_instant_equals
from test_helpers.fixtures import (
    book_consultation,
    build_quote,
    charter_territory,
    complete_consultation,
    configure_opening,
    hire_designer,
    intake_lead,
    ledger_rows,
    present_quote,
    read_opening,
    read_quote,
    read_territory,
    record_opening,
    set_clock,
)
from test_helpers.test_users import (
    designer_headers,
    franchisee_headers,
    franchisor_headers,
)

FIRST_PRESENTED_AT = "2026-08-03T12:00:00.000Z"
FIRST_EXPIRES_AT = "2026-08-17T12:00:00.000Z"
MONEY_FIELDS = ("subtotal_cents", "install_fee_cents",
                "pre_discount_total_cents", "discount_cents", "total_cents",
                "net_sales_cents")


def _single_opening_quote(api, close_the_appointment=False):
    """One 4960-cent opening on a quote first presented at 2026-08-03T12:00:00.000Z."""
    territory = charter_territory(api, royalty_rate_pct=0.055,
                                 lead_capacity_per_week=5,
                                 credit_limit_cents=2000000,
                                 liability_window="ROLLING_180D")
    designer = hire_designer(api, territory)
    lead = intake_lead(api, territory, customer_name="Ana Ruiz",
                       source="WEB_FORM",
                       requested_at="2026-08-01T08:00:00.000Z",
                       child_occupied_dwelling=False)
    consultation = book_consultation(
        api, designer, lead,
        scheduled_start_at="2026-08-03T10:00:00.000Z",
        scheduled_end_at="2026-08-03T11:00:00.000Z")
    opening = record_opening(api, designer, consultation, label="Den north",
                            room_type="LIVING_ROOM", mount_type="INSIDE")
    configure_opening(api, designer, opening, fabric_code="LT-SHEER",
                      lift_system="CORDED", motorization_option="NONE")
    if close_the_appointment:
        set_clock(api, "2026-08-03T11:30:00.000Z")
        complete_consultation(api, designer, consultation)
    quote = build_quote(api, designer, consultation)
    set_clock(api, FIRST_PRESENTED_AT)
    presented = present_quote(api, designer, quote)
    return territory, designer, lead, opening, presented


def test_a_revision_clears_the_money_and_keeps_the_openings_attached(api):
    """`PRESENTED → DRAFT` zeroes six fields, keeps `presented_at`, holds the opening.

    "A revision increments `revision_count`, clears `expires_at` to null while leaving
    `presented_at` at its previous value, and clears the six monetary results —
    `subtotal_cents`, `install_fee_cents`, `pre_discount_total_cents`,
    `discount_cents`, `total_cents` and `net_sales_cents` — back to zero, with
    `discount_pct` returning to zero alongside them, because the next presentation
    re-derives all seven from scratch."

    "The attached openings stay `QUOTED` and stay attached."

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle_restarts_the_expiry_window_and_halts_at_the_third_revise
    """
    _territory, designer, _lead, opening, presented = _single_opening_quote(api)
    dsg = designer_headers(designer["id"])

    assert presented["subtotal_cents"] == 4960
    assert presented["install_fee_cents"] == 10000
    assert presented["pre_discount_total_cents"] == 14960
    assert presented["total_cents"] == 14960
    assert_instant_equals(presented["presented_at"], FIRST_PRESENTED_AT,
                          "presented_at")
    assert_instant_equals(presented["expires_at"], FIRST_EXPIRES_AT,
                          "expires_at")

    revised = validate_success(api.revise_quote(presented["id"], dsg))
    assert revised["status"] == "DRAFT"
    assert revised["revision_count"] == 1
    assert revised["expires_at"] is None
    assert revised["discount_pct"] == 0
    for field in MONEY_FIELDS:
        assert revised[field] == 0, field
    assert_instant_equals(revised["presented_at"], FIRST_PRESENTED_AT,
                          "presented_at")

    held = read_opening(api, designer, opening["id"])
    assert held["measure_status"] == "QUOTED"
    assert held["quote_id"] == presented["id"]


def test_each_representation_restarts_the_fourteen_day_window(api):
    """Re-presenting on 08-10 expires on 08-24, not on the original 08-17.

    "The next presentation re-stamps both `presented_at` and `expires_at` from the
    clock at that later moment, so the validity window **restarts** rather than
    continuing where it left off; this is the revision cycle `PRESENTED → DRAFT →
    PRESENTED`, legal for up to two round trips."

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle_restarts_the_expiry_window_and_halts_at_the_third_revise
    """
    _territory, designer, _lead, _opening, presented = _single_opening_quote(api)
    dsg = designer_headers(designer["id"])

    validate_success(api.revise_quote(presented["id"], dsg))
    set_clock(api, "2026-08-10T08:00:00.000Z")
    second = validate_success(api.present_quote(presented["id"], dsg))

    assert second["status"] == "PRESENTED"
    assert_instant_equals(second["presented_at"], "2026-08-10T08:00:00.000Z",
                          "presented_at")
    assert_instant_equals(second["expires_at"], "2026-08-24T08:00:00.000Z",
                          "expires_at")
    assert second["subtotal_cents"] == 4960
    assert second["total_cents"] == 14960
    assert second["revision_count"] == 1


def test_the_third_revision_is_refused_and_changes_nothing(api):
    """Two round trips are legal; the third revise is refused with the cap error.

    "It requires the quote to be `PRESENTED` — otherwise `ERR_QUOTE_NOT_PRESENTED` —
    the logical clock to be strictly before `expires_at`, and `revision_count` to be
    strictly less than two, the cap on revisions."

    "Since the counter records **completed** round trips, the first revision succeeds
    moving the count from zero to one, the second succeeds moving it from one to two,
    and the third fails with `ERR_REVISION_LIMIT_REACHED`."

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle_restarts_the_expiry_window_and_halts_at_the_third_revise
    """
    _territory, designer, _lead, _opening, presented = _single_opening_quote(api)
    dsg = designer_headers(designer["id"])
    quote_id = presented["id"]

    validate_success(api.revise_quote(quote_id, dsg))
    set_clock(api, "2026-08-10T08:00:00.000Z")
    validate_success(api.present_quote(quote_id, dsg))
    twice = validate_success(api.revise_quote(quote_id, dsg))
    assert twice["revision_count"] == 2
    assert twice["status"] == "DRAFT"
    assert twice["expires_at"] is None

    set_clock(api, "2026-08-11T08:00:00.000Z")
    third = validate_success(api.present_quote(quote_id, dsg))
    assert third["status"] == "PRESENTED"
    assert third["revision_count"] == 2
    assert_instant_equals(third["expires_at"], "2026-08-25T08:00:00.000Z",
                          "expires_at")

    validate_error(api.revise_quote(quote_id, dsg),
                   ERR_REVISION_LIMIT_REACHED, 409)

    unchanged = validate_success(api.get_quote(quote_id, dsg))
    assert unchanged["status"] == "PRESENTED"
    assert unchanged["revision_count"] == 2
    assert_instant_equals(unchanged["expires_at"], "2026-08-25T08:00:00.000Z",
                          "expires_at")


def test_the_last_live_millisecond_still_admits_a_revision(api):
    """At `expires_at` minus one millisecond the quote is still alive.

    "A quote is live only while the logical clock is **strictly** before `expires_at`;
    the boundary is closed on the expired side, so at the very instant the clock equals
    `expires_at` the quote is already dead."

    Design: Difficulty/boundary_precision_check/quote_expiry_instant_is_closed_on_the_expired_side_and_restarts_on_revision
    """
    _territory, designer, _lead, _opening, presented = _single_opening_quote(
        api, close_the_appointment=True)
    dsg = designer_headers(designer["id"])

    assert_instant_equals(presented["expires_at"], FIRST_EXPIRES_AT,
                          "expires_at")

    set_clock(api, "2026-08-17T11:59:59.999Z")
    revised = validate_success(api.revise_quote(presented["id"], dsg))
    assert revised["status"] == "DRAFT"
    assert revised["revision_count"] == 1
    assert revised["expires_at"] is None

    again = validate_success(api.present_quote(presented["id"], dsg))
    assert_instant_equals(again["presented_at"], "2026-08-17T11:59:59.999Z",
                          "presented_at")
    assert_instant_equals(again["expires_at"], "2026-08-31T11:59:59.999Z",
                          "expires_at")


def test_the_expiry_instant_refuses_the_accept_and_persists_the_flip(api):
    """At exactly `expires_at` the accept fails, yet the `EXPIRED` flip survives it.

    "When any of presentation, revision, acceptance, or a manufacturing-order placement
    naming the quote is evaluated at a clock at or after `expires_at`, the service first
    flips the quote `PRESENTED → EXPIRED` — and **persists that flip** — and then
    rejects the triggering request with `ERR_QUOTE_EXPIRED`. The state change survives
    the failed request."

    "Expiry also drives the lead `CONSULT_COMPLETE → LOST`, which decrements the
    territory's `open_leads_count` and promotes one queued lead."

    Design: Difficulty/boundary_precision_check/quote_expiry_instant_is_closed_on_the_expired_side_and_restarts_on_revision
    """
    territory, designer, lead, _opening, presented = _single_opening_quote(
        api, close_the_appointment=True)
    dsg = designer_headers(designer["id"])
    owner = franchisee_headers(territory["id"])

    set_clock(api, "2026-08-17T11:59:59.999Z")
    validate_success(api.revise_quote(presented["id"], dsg))
    validate_success(api.present_quote(presented["id"], dsg))

    set_clock(api, "2026-08-31T11:59:59.999Z")
    validate_error(api.accept_quote(presented["id"], dsg), ERR_QUOTE_EXPIRED,
                   409)

    dead = read_quote(api, territory, presented["id"])
    assert dead["status"] == "EXPIRED"
    assert dead["accepted_at"] is None
    assert dead["recognized_net_sales_cents"] == 0

    assert validate_success(api.get_lead(lead["id"], owner))["status"] == "LOST"

    counters = read_territory(api, territory)
    assert counters["open_leads_count"] == 0
    assert counters["net_sales_cents"] == 0
    assert counters["royalty_accrued_cents"] == 0
    assert ledger_rows(api, territory) == []


def _quote_under_a_probation_franchise(api):
    """A live presented quote whose grandparent franchise has been put on probation."""
    territory, designer, lead, opening, presented = _single_opening_quote(api)
    set_clock(api, "2026-08-04T09:00:00.000Z")
    validate_success(api.patch_territory(territory["id"],
                                         f.territory_patch(status="PROBATION"),
                                         franchisor_headers()))
    return territory, designer, lead, opening, presented


def test_probation_two_hops_up_refuses_the_acceptance(api):
    """The quote is `PRESENTED` and live, and still cannot be signed.

    "The quote must be `PRESENTED`, the logical clock must be strictly before
    `expires_at`, the owning franchise must be `ACTIVE`, and every attached opening must
    satisfy the cordless requirement."

    "Only an `ACTIVE` territory receives routed leads or permits new work; `PROBATION`,
    `SUSPENDED` and `TERMINATED` all block it identically, with
    `ERR_TERRITORY_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/quote_acceptance_is_refused_by_its_grandparent_territorys_standing
    """
    territory, designer, lead, _opening, presented = (
        _quote_under_a_probation_franchise(api))
    owner = franchisee_headers(territory["id"])

    assert read_territory(api, territory)["status"] == "PROBATION"

    validate_error(api.accept_quote(presented["id"],
                                    designer_headers(designer["id"])),
                   ERR_TERRITORY_NOT_ACTIVE, 409)

    untouched = read_quote(api, territory, presented["id"])
    assert untouched["status"] == "PRESENTED"
    assert untouched["accepted_at"] is None
    assert_instant_equals(untouched["expires_at"], FIRST_EXPIRES_AT,
                          "expires_at")
    assert untouched["revision_count"] == 0

    assert validate_success(api.get_lead(lead["id"], owner))["status"] == "ROUTED"
    counters = read_territory(api, territory)
    assert counters["net_sales_cents"] == 0
    assert counters["royalty_accrued_cents"] == 0
    assert ledger_rows(api, territory) == []


def test_restoring_the_franchise_lets_the_same_quote_accept(api):
    """Nothing about the quote changes, so the refusal was purely the ancestor's state.

    "Acceptance stamps `accepted_at` from the logical clock and runs the **provisional**
    royalty recognition: the recognized basis is the quote's `net_sales_cents` — that is,
    the subtotal less the discount, over every attached opening whatever its install
    outcome, because install outcomes are not yet known and are deliberately ignored."

    "Finally the lead converts — `CONSULT_COMPLETE → CONVERTED`, or `ROUTED →
    CONVERTED` when the appointment is still `SCHEDULED` — which frees a unit of weekly
    capacity and can promote one queued lead."

    Design: Difficulty/cross_entity_state_dependency/quote_acceptance_is_refused_by_its_grandparent_territorys_standing
    """
    territory, designer, lead, _opening, presented = (
        _quote_under_a_probation_franchise(api))
    dsg = designer_headers(designer["id"])
    owner = franchisee_headers(territory["id"])

    validate_error(api.accept_quote(presented["id"], dsg),
                   ERR_TERRITORY_NOT_ACTIVE, 409)

    restored = validate_success(api.patch_territory(
        territory["id"], f.territory_patch(status="ACTIVE"),
        franchisor_headers()))
    assert restored["status"] == "ACTIVE"

    accepted = validate_success(api.accept_quote(presented["id"], dsg))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["net_sales_cents"] == 4960
    assert accepted["recognized_net_sales_cents"] == 4960
    assert accepted["credited_net_sales_cents"] == 0

    counters = read_territory(api, territory)
    assert counters["net_sales_cents"] == 4960
    assert counters["royalty_accrued_cents"] == 273
    assert counters["open_leads_count"] == 0

    rows = ledger_rows(api, territory, entry_type="NET_SALES_ROYALTY")
    assert len(rows) == 1
    assert rows[0]["amount_cents"] == 273
    assert rows[0]["basis_cents"] == 4960
    assert rows[0]["memo"] == "quote_accepted"

    assert validate_success(
        api.get_lead(lead["id"], owner))["status"] == "CONVERTED"
