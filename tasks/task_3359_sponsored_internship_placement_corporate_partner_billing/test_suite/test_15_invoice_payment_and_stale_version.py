"""Full-payment-only billing and the optimistic-concurrency guard on partner writes."""
from test_helpers import (
    ApiErrorId,
    create_partner,
    draft_agreement,
    invoice_payload,
    read_partner,
    setup_invoiced_placement,
    staff_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

PLACEMENT_FEE = 136339


def test_invoice_payment_amount_mismatch_returns_invalid_request(api):
    """PRD §3.7: "the amount must match the invoice's `total_amount_cents` exactly,
    since this API records full payment only; a mismatch is
    `ERR_PAYMENT_AMOUNT_MISMATCH` (422)"
    PRD §3.7: "The invoice's `total_amount_cents` is copied from the placement's
    `placement_fee_cents` at issuance"

    Design: Corner/validations/invoice_payment_amount_mismatch_returns_invalid_request
    """
    scenario = setup_invoiced_placement()
    assert scenario.invoice["total_amount_cents"] == PLACEMENT_FEE, scenario.invoice

    response = api.pay_invoice(
        scenario.invoice["id"],
        {"amount_paid_cents": 1000, "paid_on": "2026-11-01"},
        staff_headers(),
    )

    validate_error(response, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH, expected_status=422)
    invoice = validate_success(api.get_invoice(scenario.invoice["id"], staff_headers()), 200)
    assert invoice["status"] == "ISSUED", invoice["status"]
    assert invoice["total_amount_cents"] == PLACEMENT_FEE, invoice["total_amount_cents"]
    assert read_partner(scenario.partner["id"])["collected_cents"] == 0


def test_agreement_activation_with_a_stale_partner_version_is_refused(api):
    """PRD §2.8: "If the partner's `version` has advanced past the value carried in the
    request, the server rejects the write with `ERR_STALE_VERSION` at HTTP 412"

    Design: Corner/cross_cutting_layers/stale_partner_version_on_agreement_activation
    """
    partner = create_partner()
    agreement = draft_agreement(partner["id"])
    stale_version = partner["version"] - 1

    response = api.activate_agreement(
        agreement["id"], {"expected_partner_version": stale_version}, staff_headers()
    )

    validate_error(response, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    assert read_partner(partner["id"])["version"] == partner["version"]
    agreements, _ = validate_paginated(
        api.list_partner_agreements(partner["id"], staff_headers())
    )
    matching = [item for item in agreements if item["id"] == agreement["id"]]
    assert matching and matching[0]["status"] == "DRAFT", agreements


def test_second_invoice_with_the_pre_invoice_partner_version_is_refused(api):
    """PRD §2.8: "If the partner's `version` has advanced past the value carried in the
    request, the server rejects the write with `ERR_STALE_VERSION` at HTTP 412"

    Issuing the first invoice advanced the partner version, so replaying the
    version read before it is rejected while the first invoice stands.

    Design: Corner/cross_cutting_layers/stale_partner_version_on_second_invoice
    """
    scenario = setup_invoiced_placement()
    version_after_first_invoice = scenario.partner["version"]
    stale_version = version_after_first_invoice - 1
    assert scenario.invoice["status"] == "ISSUED", scenario.invoice["status"]

    response = api.issue_invoice(
        invoice_payload(
            scenario.partner["id"], scenario.placement["id"], stale_version,
            due_date="2027-03-01",
        ),
        staff_headers(),
    )

    validate_error(response, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    assert read_partner(scenario.partner["id"])["version"] == version_after_first_invoice
    invoices, meta = validate_paginated(
        api.list_invoices(staff_headers(), {"placement_id": scenario.placement["id"]})
    )
    assert meta["total_count"] == 1, invoices
    assert invoices[0]["id"] == scenario.invoice["id"], invoices
