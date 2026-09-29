"""One hazardous draft quote, two endpoints, two different first-violated rules."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_CORD_HAZARD_NOT_PERMITTED,
    ERR_QUOTE_NOT_PRESENTED,
)
from test_helpers.fixtures import (
    book_consultation,
    build_quote,
    charter_territory,
    configure_opening,
    hire_designer,
    intake_lead,
    ledger_rows,
    read_opening,
    read_quote,
    read_territory,
    record_opening,
)
from test_helpers.test_users import designer_headers, franchisee_headers

MONEY_FIELDS = ("subtotal_cents", "install_fee_cents",
                "pre_discount_total_cents", "discount_cents", "total_cents",
                "net_sales_cents")


def _hazardous_draft_quote(api):
    """A corded nursery blind, stored happily, sitting on a quote still in `DRAFT`.

    The dwelling declares no children, so the hazard comes from the room alone. The
    quote is never presented, so an `/accept` call violates both the state rule and
    the safety rule at once.
    """
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
        scheduled_start_at="2026-08-04T14:00:00.000Z",
        scheduled_end_at="2026-08-04T15:00:00.000Z")
    opening = record_opening(api, designer, consultation,
                            label="Nursery east", room_type="NURSERY",
                            mount_type="INSIDE")
    stored = configure_opening(api, designer, opening, fabric_code="LT-SHEER",
                               lift_system="CORDED",
                               motorization_option="NONE")
    quote = build_quote(api, designer, consultation)
    return territory, designer, lead, stored, quote


def test_accept_on_a_draft_quote_reports_the_state_not_the_hazard(api):
    """Both rules are broken and the caller sees the earlier one.

    "Note that the child-safety cordless requirement is deliberately **not** checked
    here: a hazardous configuration is perfectly storable, and is blocked only at the
    point of sale, as §3.6 describes."

    "Safety deliberately sits **below** state: a request against a wrongly-staged
    resource is never evaluated for cord-hazard compliance at all, so when both are
    violated the caller sees the state error."

    Design: Difficulty/priority_pair_validation_conflict/accept_reports_quote_state_before_cord_hazard_while_present_reports_the_hazard
    """
    _territory, designer, _lead, stored, quote = _hazardous_draft_quote(api)

    assert stored["lift_system"] == "CORDED"
    assert stored["measure_status"] in ("CONFIGURED", "QUOTED")
    assert quote["status"] == "DRAFT"

    validate_error(api.accept_quote(quote["id"],
                                    designer_headers(designer["id"])),
                   ERR_QUOTE_NOT_PRESENTED, 409)


def test_present_on_the_same_quote_surfaces_the_armed_hazard_rule(api):
    """With the state rule satisfied, the cordless requirement is the first failure.

    "Where the requirement applies, `lift_system` must be `CORDLESS` or `MOTORIZED`;
    both `CORDED` and `CONTINUOUS_LOOP` are refused with `ERR_CORD_HAZARD_NOT_PERMITTED`
    (HTTP 422)."

    "A quote may be freely built and freely revised carrying a hazardous configuration;
    it simply may never be shown to the homeowner, signed, or sent to a factory."

    Design: Difficulty/priority_pair_validation_conflict/accept_reports_quote_state_before_cord_hazard_while_present_reports_the_hazard
    """
    territory, designer, lead, stored, quote = _hazardous_draft_quote(api)
    dsg = designer_headers(designer["id"])

    validate_error(api.accept_quote(quote["id"], dsg),
                   ERR_QUOTE_NOT_PRESENTED, 409)
    validate_error(api.present_quote(quote["id"], dsg),
                   ERR_CORD_HAZARD_NOT_PERMITTED, 422)

    intact = read_quote(api, territory, quote["id"])
    assert intact["status"] == "DRAFT"
    assert intact["presented_at"] is None
    assert intact["expires_at"] is None
    assert intact["revision_count"] == 0
    for field in MONEY_FIELDS:
        assert intact[field] == 0, field

    unchanged = read_opening(api, designer, stored["id"])
    assert unchanged["measure_status"] == "QUOTED"
    assert unchanged["lift_system"] == "CORDED"

    assert validate_success(api.get_lead(
        lead["id"], franchisee_headers(territory["id"])))["status"] == "ROUTED"
    counters = read_territory(api, territory)
    assert counters["net_sales_cents"] == 0
    assert counters["royalty_accrued_cents"] == 0
    assert ledger_rows(api, territory) == []
