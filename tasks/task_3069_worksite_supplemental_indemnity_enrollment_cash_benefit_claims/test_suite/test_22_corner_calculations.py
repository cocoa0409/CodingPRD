"""Corner probes over the participation calculation and the documentation ladder."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, fixtures
from test_helpers.factories import benefit_item_payload
from test_helpers.test_users import make_claims_adjuster_headers, make_counselor_headers


def test_required_enrollments_uses_the_ceil_of_the_percentage_rule(client):
    """With 5 active employees and pct 0.41, a 2-policy campaign closes FAILED
    while a 3-policy campaign closes MET.

    "Closing a locked campaign is where participation is judged, and the caller
    does not choose the outcome: the close branches deterministically. The system
    freezes `required_enrollments` on the campaign as the larger of the group's
    `participation_minimum_count` and the group's `participation_minimum_pct`
    multiplied by the group's `eligible_employee_count` at the close instant and
    rounded up to a whole number."

    Design: Corner/calculations/required_enrollments_uses_ceil_of_pct_times_headcount
    """
    fixtures.set_clock(client, "2026-09-01T00:00:00Z")
    group = fixtures.create_active_group(
        client, participation_minimum_pct=0.41, participation_minimum_count=1
    )
    counselor = fixtures.create_counselor(client)
    series_bundle = fixtures.create_active_series(client)
    employees = [
        fixtures.create_employee(client, group["id"]) for _ in range(5)
    ]

    # First campaign: two applications -> FAILED (2 < ceil(0.41*5) = 3).
    first = fixtures.create_campaign(
        client, group["id"], counselor,
        window_start="2026-09-01T00:00:00Z", window_end="2026-09-10T00:00:00Z",
    )
    fixtures.open_campaign(client, first["id"], counselor)
    for employee in employees[:2]:
        fixtures.apply_policy(client, first["id"], employee["id"], series_bundle.series["id"], counselor)
    fixtures.set_clock(client, "2026-09-10T00:00:00Z")
    fixtures.lock_campaign(client, first["id"], counselor)
    first_close = fixtures.close_campaign(client, first["id"], group["id"], counselor)

    assert first_close["status"] == "FAILED"
    assert first_close["required_enrollments"] == 3, (
        "required = max(1, ceil(0.41*5)) = max(1, 3) = 3; got %r"
        % first_close.get("required_enrollments")
    )
    assert first_close["participation_met"] is False

    # Second campaign: three applications -> MET (3 >= 3, inclusive boundary).
    second = fixtures.create_campaign(
        client, group["id"], counselor,
        window_start="2026-09-10T00:00:00Z", window_end="2026-09-20T00:00:00Z",
    )
    fixtures.open_campaign(client, second["id"], counselor)
    for employee in employees[2:]:
        fixtures.apply_policy(client, second["id"], employee["id"], series_bundle.series["id"], counselor)
    fixtures.set_clock(client, "2026-09-20T00:00:00Z")
    fixtures.lock_campaign(client, second["id"], counselor)
    second_close = fixtures.close_campaign(client, second["id"], group["id"], counselor)

    assert second_close["status"] == "MET"
    assert second_close["required_enrollments"] == 3
    assert second_close["participation_met"] is True
    issued = validate_success(
        client.list_campaign_policies(second["id"], make_counselor_headers(counselor["id"]),
                                      filters={"status": "ISSUED"}),
        200,
    )
    assert len(issued) == 3


def test_outstanding_documents_report_pending_before_missing_proof(client):
    """With a RECEIVED document and no accepted proof, PENDING wins; once every
    document is resolved the missing proof surfaces as INSUFFICIENT.

    "First, every document of the claim must be `ACCEPTED`; any document still
    `RECEIVED` or `REJECTED` rejects the approval with `ERR_DOCUMENTS_PENDING`.
    Second, at least one `ACCEPTED` document of type `DIAGNOSIS_PROOF` or
    `ATTENDING_PHYSICIAN_STATEMENT` must exist, else
    `ERR_INSUFFICIENT_DOCUMENTS`."

    Design: Corner/calculations/claim_documentation_priority_pending_beats_insufficient
    """
    base = fixtures.setup_active_policy(
        client,
        benefit_items=[
            benefit_item_payload(
                event_code="B2",
                benefit_amount_cents=500,
                max_occurrences_per_year=2,
                lifetime_max_cents=10000,
            )
        ],
    )
    claim = fixtures.submit_claim(
        client, base.policy["id"], "B2",
        service_date="2026-09-05T00:00:00Z", diagnosis_code="D-B2",
        claimed_occurrences=1,
    )
    fixtures.review_claim(client, claim["id"])
    document = fixtures.attach_document(client, claim["id"], doc_type="ITEMIZED_BILL")

    first_response = client.adjudicate_claim(
        claim["id"], {"decision": "APPROVE"}, make_claims_adjuster_headers()
    )
    validate_error(first_response, api_errors.ERR_DOCUMENTS_PENDING, 422)

    fixtures.reject_document(client, document["id"])
    second_response = client.adjudicate_claim(
        claim["id"], {"decision": "APPROVE"}, make_claims_adjuster_headers()
    )
    validate_error(second_response, api_errors.ERR_INSUFFICIENT_DOCUMENTS, 422)

    reloaded = fixtures.read_claim(client, claim["id"])
    assert reloaded["status"] == "UNDER_REVIEW"
