"""Read-after-write: every derived value is already final when the writer answers.

The mutating responses carry the recomputed rollups themselves, and the very
first read of each neighbouring resource repeats the same figures inside the
declared envelope, so nothing in this service is eventually consistent.
"""

from test_helpers import (
    CompliancePosture,
    FeeVariant,
    InvoiceStatus,
    REGULATOR_HEADERS,
    ReportFeeStatus,
    SubmissionStatus,
    assert_cents,
    assert_common_fields,
    assert_invoice,
    assert_registration,
    assert_report,
    assert_weight,
    fixtures as fx,
    validate_success,
)


def _first_read(response):
    """Unwrap one read and confirm the envelope declares a single object."""
    body = response.json()
    assert body["response_type"] == "object", body["response_type"]
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    data = validate_success(response)
    assert_common_fields(data)
    return data


def test_every_derived_field_is_visible_on_the_first_read_after_the_write(api):
    """The submit and the invoice already answer with the numbers the reads repeat.

    The submission response itself shows the 5.500 kg rollup and the verification
    verdict, and the invoice response itself shows the fifty-cent subtotal, the
    three cents of administration and the total of fifty-three; the first read of
    the registration, the producer, the report and the invoice then show the same
    running total, the same balance, the same billed position and the same total,
    each inside a well-formed single-object envelope.

    Design: Corner/consistency_model/every_derived_field_is_visible_on_the_first_read_after_the_write
    """
    chain = fx.base_ca_chain(api)
    officer_headers, admin_headers = chain["officer_headers"], chain["admin_headers"]
    submitted = chain["report"]
    assert_report(
        submitted,
        submission_status=SubmissionStatus.SUBMITTED,
        verification_required=False,
        fee_status=ReportFeeStatus.UNASSESSED,
    )
    assert_weight(submitted["total_weight_kg"], 5.500, "total_weight_kg")

    fx.assess_report(api, chain["pro"], chain["report"], FeeVariant.FINAL)
    invoice = fx.issue_invoice(
        api, chain["pro"], chain["report"], chain["membership"]
    )
    assert_invoice(
        invoice,
        status=InvoiceStatus.ISSUED,
        fee_subtotal_cents=50,
        admin_fee_cents=3,
        total_cents=53,
    )

    registration = _first_read(
        api.get_registration(chain["registration"]["id"], officer_headers)
    )
    assert_registration(registration, compliance_posture=CompliancePosture.COMPLIANT)
    assert_weight(
        registration["reported_weight_kg_ytd"], 5.500, "reported_weight_kg_ytd"
    )

    producer = _first_read(api.get_producer(chain["producer"]["id"], REGULATOR_HEADERS))
    assert_cents(
        producer["assessed_fee_balance_cents"], 53, "assessed_fee_balance_cents"
    )

    report = _first_read(api.get_report(chain["report"]["id"], REGULATOR_HEADERS))
    assert_report(
        report,
        fee_status=ReportFeeStatus.INVOICED,
        fee_subtotal_cents=50,
        submission_status=SubmissionStatus.SUBMITTED,
    )
    assert_weight(report["total_weight_kg"], 5.500, "total_weight_kg")

    billed = _first_read(api.get_invoice(invoice["id"], admin_headers))
    assert_invoice(
        billed,
        status=InvoiceStatus.ISSUED,
        fee_subtotal_cents=50,
        admin_fee_cents=3,
        total_cents=53,
    )
