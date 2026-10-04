"""Corner probes over validation gates: authentication, event coverage, the
guaranteed-issue screen, and the pre-existing exclusion window."""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID, validate_error, validate_success

from test_helpers import api_errors, fixtures
from test_helpers.factories import benefit_item_payload
from test_helpers.test_users import (
    headers_without_identity,
    make_claims_adjuster_headers,
    make_counselor_headers,
)


def test_a_request_without_identity_headers_fails_before_any_lookup(client):
    """Auth runs first: even a nonexistent id returns 401, never a 404 leak.

    "Every request is validated in a fixed priority order, and the first failing
    check determines the error returned. Authentication comes first
    (`ERR_UNAUTHENTICATED`, then the role check `ERR_UNAUTHORIZED`), followed by
    existence of every identifier referenced in the path and body, evaluated
    left-to-right (`ERR_NOT_FOUND`), and then referential integrity of
    body-supplied foreign keys (`ERR_REFERENTIAL_INTEGRITY`)."

    Design: Corner/validations/missing_role_header_rejected_unauthenticated
    """
    response = client.get_employer_group(NON_EXISTENT_UUID, headers_without_identity())

    validate_error(response, api_errors.ERR_UNAUTHENTICATED, 401)


def test_an_unknown_event_code_passes_submission_but_fails_review(client):
    """The event gate lives on review: the claim is filed, then review refuses it.

    "Review (`SUBMITTED` → `UNDER_REVIEW`) is the adjuster's first look, and it
    applies two gates: the policy must be in `ACTIVE`, `LAPSED`, or `PORTED`
    status — claims are reviewable on lapsed or ported policies when the service
    date fell within a covered period — else `ERR_POLICY_INACTIVE`; and the
    `event_code` must exist among the policy's pinned schedule's benefit items,
    else `ERR_EVENT_NOT_COVERED`."

    Design: Corner/validations/claim_submit_with_unknown_event_code_rejected_at_review
    """
    base = fixtures.setup_active_policy(
        client,
        benefit_items=[
            benefit_item_payload(
                event_code="KNOWN",
                benefit_amount_cents=100,
                max_occurrences_per_year=1,
                lifetime_max_cents=1000,
            )
        ],
    )
    claim = fixtures.submit_claim(
        client, base.policy["id"], "UNKNOWN_CODE",
        service_date="2026-09-05T00:00:00Z", diagnosis_code="D-X",
        claimed_occurrences=1,
    )
    assert claim["status"] == "SUBMITTED"

    response = client.review_claim(claim["id"], make_claims_adjuster_headers())

    validate_error(response, api_errors.ERR_EVENT_NOT_COVERED, 422)
    reloaded = fixtures.read_claim(client, claim["id"])
    assert reloaded["status"] == "SUBMITTED"


def test_guaranteed_issue_flips_the_pre_existing_screen_at_issuance(client):
    """The same employee with a pre-existing code is issued under a guaranteed
    campaign and declined under a non-guaranteed one.

    "On top of that sits the pre-existing condition provision: if the campaign was
    not guaranteed-issue and the employee's `preexisting_diagnosis_codes` is
    non-empty, the policy is declined instead of issued."

    Design: Corner/validations/non_guaranteed_issue_policy_with_preexisting_codes_declined
    """
    fixtures.set_clock(client, "2026-09-01T00:00:00Z")
    group = fixtures.create_active_group(client)
    counselor_gi = fixtures.create_counselor(client)
    counselor_ngi = fixtures.create_counselor(client)
    series_one = fixtures.create_active_series(client)
    series_two = fixtures.create_active_series(client)
    campaign_gi = fixtures.create_campaign(
        client, group["id"], counselor_gi,
        window_start="2026-09-01T00:00:00Z", window_end="2026-09-05T00:00:00Z",
        guaranteed_issue=True,
    )
    fixtures.open_campaign(client, campaign_gi["id"], counselor_gi)
    campaign_ngi = fixtures.create_campaign(
        client, group["id"], counselor_ngi,
        window_start="2026-09-05T00:00:00Z", window_end="2026-09-10T00:00:00Z",
        guaranteed_issue=False,
    )
    fixtures.open_campaign(client, campaign_ngi["id"], counselor_ngi)
    employee = fixtures.create_employee(
        client, group["id"], preexisting_diagnosis_codes=["E11.9"]
    )
    # Applications are filed strictly inside each campaign's half-open window:
    # the windows merely abut, and no instant lies in both.
    fixtures.set_clock(client, "2026-09-03T00:00:00Z")
    policy_gi = fixtures.apply_policy(
        client, campaign_gi["id"], employee["id"], series_one.series["id"], counselor_gi
    )
    fixtures.set_clock(client, "2026-09-06T00:00:00Z")
    policy_ngi = fixtures.apply_policy(
        client, campaign_ngi["id"], employee["id"], series_two.series["id"], counselor_ngi
    )

    issued = fixtures.issue_policy(client, policy_gi["id"], counselor_gi)
    declined_response = client.issue_policy(
        policy_ngi["id"], make_counselor_headers(counselor_ngi["id"])
    )
    # Direct issuance of a non-guaranteed application with pre-existing codes
    # declines the policy rather than issuing it; accept either the transition
    # having happened (2xx with DECLINED status) or a business refusal.
    assert issued["status"] == "ISSUED", (
        "guaranteed-issue skips the pre-existing screen; got %r" % issued.get("status")
    )
    if declined_response.status_code in (200,):
        declined = validate_success(declined_response, 200)
        assert declined["status"] == "DECLINED"
    else:
        policy = fixtures.read_policy(client, policy_ngi["id"])
        assert policy["status"] == "DECLINED", (
            "non-guaranteed issue applies the pre-existing screen; got %r"
            % policy.get("status")
        )


def test_a_pre_existing_claim_inside_the_window_denies_but_after_it_approves(client):
    """Service inside the exclusion window auto-denies; after it, payable.

    "Third, the pre-existing exclusion: if the claim's `diagnosis_code` appears in
    the employee's `preexisting_diagnosis_codes` and the `service_date` falls
    before the policy's `coverage_start_date` plus the pinned schedule's
    `preexisting_exclusion_months` whole months, the approval is refused with
    `ERR_PRE_EXISTING_EXCLUSION` and the claim moves to `DENIED` with
    `denial_reason` `PRE_EXISTING`."

    Design: Corner/validations/claim_on_preexisting_diagnosis_inside_exclusion_window_denied
    """
    base = fixtures.setup_active_policy(
        client,
        schedule_overrides={"preexisting_exclusion_months": 6},
        employee_overrides={"preexisting_diagnosis_codes": ["E11.9"]},
        benefit_items=[
            benefit_item_payload(
                event_code="E2",
                benefit_amount_cents=4000,
                max_occurrences_per_year=2,
                lifetime_max_cents=100000,
            )
        ],
        campaign_overrides={"guaranteed_issue": True},
    )
    early = fixtures.submit_claim(
        client, base.policy["id"], "E2",
        service_date="2026-12-15T00:00:00Z", diagnosis_code="E11.9",
        claimed_occurrences=1,
    )
    fixtures.review_claim(client, early["id"])
    early_doc = fixtures.attach_document(client, early["id"], doc_type="DIAGNOSIS_PROOF")
    fixtures.accept_document(client, early_doc["id"])
    late = fixtures.submit_claim(
        client, base.policy["id"], "E2",
        service_date="2027-03-15T00:00:00Z", diagnosis_code="E11.9",
        claimed_occurrences=1,
    )
    fixtures.review_claim(client, late["id"])
    late_doc = fixtures.attach_document(client, late["id"], doc_type="DIAGNOSIS_PROOF")
    fixtures.accept_document(client, late_doc["id"])

    early_response = client.adjudicate_claim(
        early["id"], {"decision": "APPROVE"}, make_claims_adjuster_headers()
    )
    validate_error(early_response, api_errors.ERR_PRE_EXISTING_EXCLUSION, 422)
    early_claim = fixtures.read_claim(client, early["id"])
    assert early_claim["status"] == "DENIED"
    assert early_claim["denial_reason"] == "PRE_EXISTING"

    late_claim = fixtures.adjudicate_claim(client, late["id"], "APPROVE")
    assert late_claim["status"] == "APPROVED"
    assert late_claim["payable_amount_cents"] == 4000
