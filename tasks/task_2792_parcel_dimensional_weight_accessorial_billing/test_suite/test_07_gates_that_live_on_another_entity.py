"""Requests refused because of a state that is not their own.

Nothing about the induction payload changes between the refused attempt and the
accepted one — a rate contract moved `DRAFT → ACTIVE` in between. Nothing about
the dispute payload changes either — the invoice two hops behind the named line
moved `OPEN → ISSUED`.
"""

import pytest

from test_helpers import (
    BILLING_OPS_HEADERS,
    CARRIER_OPS_HEADERS,
    DEFAULT_CLOCK_UTC,
    ERR_INVOICE_NOT_DISPUTABLE,
    ERR_NO_ACTIVE_CONTRACT,
    RESIDENTIAL_OVERRIDE_540,
    ROUNDING_DECLARED,
    TOLERANCE_EDGE_DECLARED,
    activate_rate_contract,
    assert_date,
    assert_instant,
    assert_ledger,
    assert_lbs,
    assert_money_equals,
    create_ground_service_level,
    create_shipper_account,
    delivered_shipment,
    dispute_payload,
    draft_rate_contract,
    get_success_data,
    line_for_shipment,
    open_invoice,
    refresh_invoice,
    refresh_invoice_line,
    refresh_shipper_account,
    shipment_payload,
    shipper_with_active_contract,
    validate_error,
    validate_success,
)

DEPENDENT_TRACKING_NUMBER = "1Z-DEP-0061"
DISPUTE_DEADLINE_UTC = "2026-10-30T00:00:00Z"


# ---------------------------------------------------------------------------
# Induction gated on a contract that is a third entity entirely
# ---------------------------------------------------------------------------
@pytest.fixture
def shipper_whose_only_contract_is_draft(api):
    """An ACTIVE shipper, a GROUND service level, and a contract left at DRAFT.

    Every entity the induction payload names exists and is in order; the only
    thing missing is the activation of a contract the payload never mentions.
    """
    account = create_shipper_account(
        api, account_number="SH-1001", name="Northwind Freight"
    )
    ground = create_ground_service_level(api)
    contract = draft_rate_contract(api, account["id"])
    assert contract["status"] == "DRAFT"
    assert contract["activated_at"] is None
    return {"account": account, "ground_id": ground["id"], "contract": contract}


def _induct(api, ctx):
    """Attempt the one and only induction payload this module uses."""
    return api.create_shipment(
        shipment_payload(
            ctx["account"]["id"],
            ctx["ground_id"],
            tracking_number=DEPENDENT_TRACKING_NUMBER,
            zone=2,
            residential_declared=False,
            **TOLERANCE_EDGE_DECLARED,
        ),
        CARRIER_OPS_HEADERS,
    )


def _shipments_of(api, shipper_id):
    """Every shipment row that exists for one shipper."""
    return get_success_data(
        api.list_shipments(
            CARRIER_OPS_HEADERS, {"shipper_id": shipper_id, "limit": 100}
        )
    )


def test_induction_is_refused_while_the_governing_contract_is_still_draft(
    api, shipper_whose_only_contract_is_draft
):
    """PRD §3.3: "The candidate set is every rate contract belonging to the requesting `shipper_id` whose `status` is `ACTIVE` and whose effectivity window covers the shipment's `pickup_date`, where coverage means the `pickup_date` is on or after `effective_from` and on or before `effective_to` — both ends inclusive."
    PRD §3.3: "Contracts in `DRAFT` or `SUPERSEDED` status never price a shipment, regardless of their dates."
    PRD §3.3: "If the candidate set is empty, the induction is rejected with `ERR_NO_ACTIVE_CONTRACT` (HTTP 422)."
    PRD §3.1: "Every new contract is created with `status` `DRAFT` and `activated_at` null."

    Design: Difficulty/cross_entity_state_dependency/shipment_induction_depends_on_the_contract_being_activated_first
    """
    ctx = shipper_whose_only_contract_is_draft
    validate_error(_induct(api, ctx), ERR_NO_ACTIVE_CONTRACT, 422)

    assert _shipments_of(api, ctx["account"]["id"]) == [], (
        "a refused induction persists no shipment at all"
    )
    account = refresh_shipper_account(api, ctx["account"]["id"])
    assert_ledger(account, total=0, unbilled=0, billed=0)


def test_activating_the_contract_admits_the_identical_request_and_freezes_its_terms(
    api, shipper_whose_only_contract_is_draft
):
    """PRD §3.1: "A successful activation sets the contract's `activated_at` from the logical clock and moves its `status` `DRAFT` → `ACTIVE`."
    PRD §3.3: "The first row of that ranking becomes the shipment's `contract_id`, and its `dim_divisor` is copied onto the shipment as `divisor_used`."
    PRD §3.3: "The server stamps `picked_up_at` from the logical clock and derives `pickup_date` as the UTC calendar date of that instant."
    PRD §3.3: "All three status axes open at their initial values: `measurement_status` at `PENDING_SCAN`, `movement_status` at `IN_TRANSIT`, and `billing_status` at `UNBILLED`."

    Design: Difficulty/cross_entity_state_dependency/shipment_induction_depends_on_the_contract_being_activated_first
    """
    ctx = shipper_whose_only_contract_is_draft
    validate_error(_induct(api, ctx), ERR_NO_ACTIVE_CONTRACT, 422)

    activated = activate_rate_contract(
        api, ctx["contract"]["id"], ctx["account"]["version"]
    )
    assert activated["status"] == "ACTIVE"
    assert_instant(activated["activated_at"], DEFAULT_CLOCK_UTC, "activated_at")

    shipment = validate_success(_induct(api, ctx), 201)
    assert shipment["contract_id"] == ctx["contract"]["id"], (
        "the shipment must freeze the contract that was actually read, got "
        f"{shipment['contract_id']}"
    )
    assert shipment["divisor_used"] == 139, (
        "the contract's dim_divisor must be copied onto the shipment, got "
        f"{shipment['divisor_used']}"
    )
    assert shipment["declared_cube_in3"] == 2000
    assert_lbs(shipment["preliminary_dim_weight_lbs"], 15, "preliminary_dim_weight_lbs")
    assert_lbs(
        shipment["preliminary_billable_weight_lbs"], 30, "preliminary_billable_weight_lbs"
    )
    assert shipment["preliminary_basis"] == "ACTUAL"
    assert shipment["measurement_status"] == "PENDING_SCAN"
    assert shipment["movement_status"] == "IN_TRANSIT"
    assert shipment["billing_status"] == "UNBILLED"
    assert_date(shipment["pickup_date"], "2026-08-01", "pickup_date")


def test_the_refused_induction_left_no_row_for_the_reused_tracking_number_to_collide_with(
    api, shipper_whose_only_contract_is_draft
):
    """PRD §3.3: "The payload identifies the owner with `shipper_id`, the purchased service with `service_level_id`, and the parcel itself with a `tracking_number` between 8 and 32 characters and unique across all shipments (`ERR_DUPLICATE_KEY` on a collision)."
    PRD §3.3: "The owning account's `total_shipment_count` and `unbilled_shipment_count` each increase by 1, and `open_charges_cents` is recomputed."
    PRD §2.11: "**Conserved package count:** `unbilled_shipment_count` plus `billed_shipment_count` equals `total_shipment_count`."

    Design: Difficulty/cross_entity_state_dependency/shipment_induction_depends_on_the_contract_being_activated_first
    """
    ctx = shipper_whose_only_contract_is_draft
    validate_error(_induct(api, ctx), ERR_NO_ACTIVE_CONTRACT, 422)
    activate_rate_contract(api, ctx["contract"]["id"], ctx["account"]["version"])

    shipment = validate_success(_induct(api, ctx), 201)
    assert shipment["tracking_number"] == DEPENDENT_TRACKING_NUMBER, (
        "the very tracking number the rejected attempt carried must still be free"
    )

    rows = _shipments_of(api, ctx["account"]["id"])
    assert len(rows) == 1, (
        f"exactly one shipment may exist after the pair of attempts, found {len(rows)}"
    )
    assert rows[0]["id"] == shipment["id"]

    account = refresh_shipper_account(api, ctx["account"]["id"])
    assert_ledger(account, total=1, unbilled=1, billed=0)
    assert (
        account["unbilled_shipment_count"] + account["billed_shipment_count"]
        == account["total_shipment_count"]
    )


# ---------------------------------------------------------------------------
# A dispute gated on the invoice two hops behind the named line
# ---------------------------------------------------------------------------
@pytest.fixture
def open_invoice_holding_a_residential_line(api):
    """A 7760 cent residential EXPRESS line sitting on an invoice still at OPEN."""
    shipper = shipper_with_active_contract(
        api,
        account_number="SH-1001",
        contract_kwargs={"accessorial_rate_overrides": dict(RESIDENTIAL_OVERRIDE_540)},
        with_ground=False,
    )
    parcel = delivered_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-PD-0071",
        zone=2,
        residential_declared=True,
        **ROUNDING_DECLARED,
    )
    invoice = open_invoice(api, shipper, [parcel.shipment_id])
    line = line_for_shipment(api, invoice.invoice_id, parcel.shipment_id)
    assert_money_equals(line["line_total_cents"], 7760, "line_total_cents")
    return {"shipper": shipper, "parcel": parcel, "invoice": invoice, "line": line}


def _file_accessorial_dispute(api, ctx):
    """File the one and only dispute payload this half of the module uses."""
    return api.create_dispute(
        dispute_payload(
            ctx["line"]["id"],
            claim_type="ACCESSORIAL",
            claimed_reason="Commercial dock, residential fee wrong",
            disputed_codes=["RESIDENTIAL"],
        ),
        ctx["shipper"].shipper_headers,
    )


def _disputes_on(api, line_id):
    """Every dispute row that exists against one line."""
    return get_success_data(
        api.list_disputes(
            BILLING_OPS_HEADERS, {"invoice_line_id": line_id, "limit": 100}
        )
    )


def test_a_dispute_is_refused_while_the_invoice_behind_the_line_is_still_open(
    api, open_invoice_holding_a_residential_line
):
    """PRD §3.9: "The invoice behind the line must be `ISSUED` or `ADJUSTED`, else `ERR_INVOICE_NOT_DISPUTABLE` (HTTP 409) — an `OPEN` invoice has not been published yet, and a `SETTLED` or `VOID` one is closed."
    PRD §3.9: "Five guards apply to a filing, in this order."
    PRD §3.7: "Issue stamps `issued_at` from the logical clock and derives `dispute_deadline_utc` as that instant advanced by the ninety-day dispute window."

    Design: Difficulty/cross_entity_state_dependency/dispute_admission_depends_on_the_parent_invoice_being_issued
    """
    ctx = open_invoice_holding_a_residential_line
    validate_error(_file_accessorial_dispute(api, ctx), ERR_INVOICE_NOT_DISPUTABLE, 409)

    assert _disputes_on(api, ctx["line"]["id"]) == [], (
        "a refused filing persists no dispute at all"
    )
    invoice = refresh_invoice(api, ctx["invoice"].invoice_id)
    assert invoice["status"] == "OPEN"
    assert invoice["line_count"] == 1
    assert_money_equals(invoice["gross_charges_cents"], 7760, "gross_charges_cents")
    assert_money_equals(invoice["net_amount_cents"], 7760, "net_amount_cents")
    assert invoice["dispute_deadline_utc"] is None, (
        "an unissued invoice has no dispute deadline yet, got "
        f"{invoice['dispute_deadline_utc']}"
    )


def test_issuing_the_invoice_admits_the_identical_filing_with_the_derived_deadline(
    api, open_invoice_holding_a_residential_line
):
    """PRD §3.7: "Issue stamps `issued_at` from the logical clock and derives `dispute_deadline_utc` as that instant advanced by the ninety-day dispute window."
    PRD §3.9: "A new dispute opens at `status` `SUBMITTED` with `shipper_user_id` stamped from the filer's `X-User-ID`, `round_count` at 0, `required_item_type` null, `accepted_evidence_count` at 0, `granted_credit_cents` at 0, and `resolved_at` null."

    Design: Difficulty/cross_entity_state_dependency/dispute_admission_depends_on_the_parent_invoice_being_issued
    """
    ctx = open_invoice_holding_a_residential_line
    validate_error(_file_accessorial_dispute(api, ctx), ERR_INVOICE_NOT_DISPUTABLE, 409)

    issued = validate_success(
        api.issue_invoice(ctx["invoice"].invoice_id, BILLING_OPS_HEADERS)
    )
    assert issued["status"] == "ISSUED"
    assert_instant(issued["issued_at"], DEFAULT_CLOCK_UTC, "issued_at")
    assert_instant(
        issued["dispute_deadline_utc"], DISPUTE_DEADLINE_UTC, "dispute_deadline_utc"
    )

    dispute = validate_success(_file_accessorial_dispute(api, ctx), 201)
    assert dispute["status"] == "SUBMITTED"
    assert dispute["invoice_line_id"] == ctx["line"]["id"]
    assert dispute["claim_type"] == "ACCESSORIAL"
    assert dispute["disputed_codes"] == ["RESIDENTIAL"]
    assert dispute["round_count"] == 0
    assert dispute["accepted_evidence_count"] == 0
    assert_money_equals(dispute["granted_credit_cents"], 0, "granted_credit_cents")
    assert dispute["shipper_user_id"] == ctx["shipper"].shipper_id
    assert dispute["resolved_at"] is None


def test_admitting_the_dispute_moves_no_money_on_the_invoice_or_its_line(
    api, open_invoice_holding_a_residential_line
):
    """PRD §2.9: "An invoice line is a **frozen quotation** the moment its invoice leaves the `OPEN` state."
    PRD §3.6: "`net_amount_cents` is `gross_charges_cents` minus `tier_discount_cents` plus `adjustment_total_cents`."
    PRD §3.6: "Invoices carry two derived pending counters — `pending_adjustment_count`, the number of adjustments on their lines whose `status` is `PROPOSED`, and `has_pending_adjustments`, which is simply true when that count is greater than 0 — both opening at 0 and false."

    Design: Difficulty/cross_entity_state_dependency/dispute_admission_depends_on_the_parent_invoice_being_issued
    """
    ctx = open_invoice_holding_a_residential_line
    validate_error(_file_accessorial_dispute(api, ctx), ERR_INVOICE_NOT_DISPUTABLE, 409)
    validate_success(api.issue_invoice(ctx["invoice"].invoice_id, BILLING_OPS_HEADERS))
    dispute = validate_success(_file_accessorial_dispute(api, ctx), 201)

    rows = _disputes_on(api, ctx["line"]["id"])
    assert len(rows) == 1, f"exactly one dispute may exist, found {len(rows)}"
    assert rows[0]["id"] == dispute["id"]

    invoice = refresh_invoice(api, ctx["invoice"].invoice_id)
    assert invoice["status"] == "ISSUED"
    assert_money_equals(invoice["net_amount_cents"], 7760, "net_amount_cents")
    assert_money_equals(invoice["adjustment_total_cents"], 0, "adjustment_total_cents")
    assert invoice["pending_adjustment_count"] == 0

    line = refresh_invoice_line(api, ctx["line"]["id"])
    assert_money_equals(line["line_total_cents"], 7760, "line_total_cents")
    assert_money_equals(line["adjustment_total_cents"], 0, "adjustment_total_cents")
