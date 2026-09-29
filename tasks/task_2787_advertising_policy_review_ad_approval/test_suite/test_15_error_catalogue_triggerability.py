"""Refusals that are easy to confuse with one another, told apart one at a time.

An unusable identity is not an unauthorized one. Ten unknown ids are ten different
answers, not one. A reviewer missing a country is not a reviewer missing a queue. A notice
that already has an appeal is not a notice that can no longer be appealed. A restricted
account is not a suspended one. And a clock that refuses to go back still accepts the
instant it is already sitting on.
"""

import pytest

from test_helpers import (
    ADMIN,
    ANALYST,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    factories,
    fixtures,
    make_advertiser_headers,
    make_headers,
    make_reviewer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

FIN_CREDIT = "FIN_CREDIT"
ALC_SPIRITS = "ALC_SPIRITS"


def test_a_missing_role_an_empty_identity_and_an_unknown_role_are_all_refused_first():
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the
    acting principal, and `X-User-Role`, declaring the capacity in which it acts."

    PRD §2.1: "A request whose `X-User-Role` header is missing or empty, whose `X-User-ID`
    header is missing or empty, or whose `X-User-Role` value is not one of those four
    spellings, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD §2.10: "Authentication of the headers — `ERR_UNAUTHENTICATED`."

    PRD §2.10: "Role authorization for the addressed operation — `ERR_FORBIDDEN_ROLE`."

    Design: Corner/From Table 6 (Errors)/error_catalog_unauthenticated_requests_are_refused_before_any_role_check
    """
    rule = fixtures.create_policy_rule(
        FIN_CREDIT, "REGULATED", 4.00, title="Consumer credit offers"
    )

    validate_error(
        api_client.get_policy_rule(rule["id"], make_headers("policy-admin-1", "")),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        api_client.get_policy_rule(rule["id"], make_headers("", "Advertiser")),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )
    # An unknown role spelling on an endpoint it could never call, with a body that is
    # missing two required fields: the header check still owns the answer.
    validate_error(
        api_client.create_policy_rule(
            {"code": "AUDIT_BOT"}, make_headers("audit-bot-1", "AuditBot")
        ),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )

    _rows, pagination = validate_paginated(api_client.list_policy_rules(ADMIN))
    assert pagination["total_count"] == 1


def test_ten_unknown_ids_report_ten_different_not_found_errors():
    """PRD §2.5: "Each identifier position has its own dedicated not-found error, all of
    them HTTP 404: an unresolvable `advertiser_id` yields `ERR_ADVERTISER_NOT_FOUND`, an
    unresolvable `ad_creative_id` yields `ERR_AD_CREATIVE_NOT_FOUND`, an unresolvable
    `policy_rule_id` yields `ERR_POLICY_RULE_NOT_FOUND`, an unresolvable `reviewer_id`
    yields `ERR_REVIEWER_NOT_FOUND`, an unresolvable `screening_run_id` yields
    `ERR_SCREENING_RUN_NOT_FOUND`, an unresolvable `review_task_id` yields
    `ERR_REVIEW_TASK_NOT_FOUND`, an unresolvable `certification_id` yields
    `ERR_CERTIFICATION_NOT_FOUND`, an unresolvable `disapproval_notice_id` yields
    `ERR_DISAPPROVAL_NOTICE_NOT_FOUND`, an unresolvable `appeal_id` yields
    `ERR_APPEAL_NOT_FOUND`, and an unresolvable `enforcement_action_id` yields
    `ERR_ENFORCEMENT_ACTION_NOT_FOUND`."

    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/From Table 6 (Errors)/error_catalog_every_path_id_reports_its_own_entity_specific_not_found
    """
    # A non-empty store, so nothing answers 404 merely for being empty.
    fixtures.create_policy_rule(
        FIN_CREDIT, "REGULATED", 4.00, title="Consumer credit offers"
    )

    probes = (
        (
            api_client.get_advertiser(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_ADVERTISER_NOT_FOUND,
        ),
        (
            api_client.get_ad_creative(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_AD_CREATIVE_NOT_FOUND,
        ),
        (
            api_client.get_policy_rule(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_POLICY_RULE_NOT_FOUND,
        ),
        (
            api_client.get_reviewer(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_REVIEWER_NOT_FOUND,
        ),
        (
            api_client.get_screening_run(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_SCREENING_RUN_NOT_FOUND,
        ),
        (
            api_client.get_review_task(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_REVIEW_TASK_NOT_FOUND,
        ),
        (
            api_client.get_certification(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_CERTIFICATION_NOT_FOUND,
        ),
        (
            api_client.get_disapproval_notice(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_DISAPPROVAL_NOTICE_NOT_FOUND,
        ),
        (
            api_client.get_appeal(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_APPEAL_NOT_FOUND,
        ),
        (
            api_client.get_enforcement_action(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_ENFORCEMENT_ACTION_NOT_FOUND,
        ),
    )
    for response, expected_error_id in probes:
        validate_error(response, expected_error_id, 404)


def test_the_country_gate_the_queue_gate_and_the_successful_claim_are_told_apart():
    """PRD §3.6: "Claiming a `QUEUED` task is a `PolicyReviewer` act that advances
    `QUEUED → CLAIMED`, and it is gated by four checks that are evaluated in a fixed order
    so that the reported error is predictable."

    PRD §3.6: "Competence comes first: every element of the creative's
    `target_country_codes` must appear in the acting reviewer's `country_authorizations`,
    and a gap reports `ERR_REVIEWER_NOT_AUTHORIZED_COUNTRY` (HTTP 403)."

    PRD §3.6: "Speciality comes third: the task's `queue` must appear in the reviewer's
    `queue_specialties`, failing which the claim reports `ERR_REVIEWER_QUEUE_MISMATCH`
    (HTTP 403)."

    PRD §3.6: "A successful claim writes `assigned_reviewer_id` from `X-User-ID` and
    `claimed_at` from the logical clock, increments the reviewer's `claimed_task_count` by
    1 and the reviewer's `version` by 1, and increments the task's `version` by 1."

    Design: Corner/From Table 6 (Errors)/error_catalog_claim_authorization_separates_country_from_queue_before_capacity
    """
    rule = fixtures.create_policy_rule(
        ALC_SPIRITS,
        "RESTRICTED",
        6.00,
        title="Alcohol - spirits",
        requires_certification=True,
        requires_disclaimer=False,
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
        default_queue="REGULATED_CERT",
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Northline Spirits LLC",
        country_code="US",
        industry_code="ALCOHOL_RETAIL",
    )
    short_on_countries = fixtures.create_reviewer(
        ["REGULATED_CERT"], ["US"], display_name="A. Reviewer", max_concurrent_claims=3
    )
    short_on_queues = fixtures.create_reviewer(
        ["STANDARD"], ["CA", "US"], display_name="B. Reviewer", max_concurrent_claims=3
    )
    competent = fixtures.create_reviewer(
        ["REGULATED_CERT"],
        ["CA", "US"],
        display_name="C. Reviewer",
        max_concurrent_claims=3,
    )
    _creative, task = fixtures.creative_in_manual_review(
        advertiser["id"],
        [ALC_SPIRITS],
        [(rule["id"], 0.50)],
        ["CA", "US"],
        headline="Cross border cask",
        body_text="One spirit campaign aimed at both Canada and the United States.",
        landing_page_url="https://www.northline.example/cask",
        display_url="https://www.northline.example/cask",
    )
    assert task["queue"] == "REGULATED_CERT"

    validate_error(
        api_client.claim_review_task(
            task["id"], make_reviewer_headers(short_on_countries["id"])
        ),
        ApiErrorId.ERR_REVIEWER_NOT_AUTHORIZED_COUNTRY,
        403,
    )
    validate_error(
        api_client.claim_review_task(
            task["id"], make_reviewer_headers(short_on_queues["id"])
        ),
        ApiErrorId.ERR_REVIEWER_QUEUE_MISMATCH,
        403,
    )

    claimed = validate_success(
        api_client.claim_review_task(
            task["id"], make_reviewer_headers(competent["id"])
        )
    )
    assert claimed["status"] == "CLAIMED"
    assert claimed["assigned_reviewer_id"] == competent["id"]
    assert_instant_equals(
        claimed["claimed_at"], "2026-08-01T00:00:00Z", "claimed_at"
    )

    # A refused claim never touches the reviewer row it was refused for.
    for refused in (short_on_countries, short_on_queues):
        row = fixtures.read_reviewer(refused["id"])
        assert row["claimed_task_count"] == 0
        assert row["version"] == 1
    assert fixtures.read_reviewer(competent["id"])["claimed_task_count"] == 1


def test_a_second_decision_a_second_appeal_and_an_expired_notice_get_three_errors():
    """PRD §2.10: "The one-appeal-per-notice duplicate check —
    `ERR_APPEAL_ALREADY_EXISTS`. This deliberately runs ahead of the notice-state check
    below, because filing the first appeal moves the notice out of `ISSUED`: a second
    attempt must be reported as a duplicate, not as an un-appealable notice."

    PRD §3.9: "The notice must be `ISSUED`; one already `APPEALED`, `APPEAL_GRANTED`,
    `APPEAL_UPHELD` or `EXPIRED` is refused with `ERR_NOTICE_NOT_APPEALABLE` (HTTP 409)."

    PRD §3.9: "Both branches require that the appeal's `status` is `SUBMITTED` and its
    notice's `status` is `APPEALED` — otherwise `ERR_APPEAL_NOT_PENDING` (HTTP 409) — and
    both require that the acting reviewer's identifier differs from the notice's
    `decided_by_reviewer_id`, since no reviewer may sit in judgement on their own
    disapproval; a self-adjudication attempt is refused with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)."

    PRD §3.9: "The sweep's third phase moves an `ISSUED` notice whose `appeal_deadline_at`
    has been reached or passed to `EXPIRED`, which changes no ledger row and no advertiser
    field — it simply makes the disapproval final — and increments the notice's `version`
    by 1."

    Design: Corner/From Table 6 (Errors)/error_catalog_appeal_lifecycle_rejects_a_second_decision_a_second_appeal_and_an_expired_notice
    """
    rule = fixtures.create_policy_rule(
        FIN_CREDIT,
        "REGULATED",
        4.00,
        title="Consumer credit offers",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
        default_queue="STANDARD",
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )
    advertiser_id = advertiser["id"]
    deciding = fixtures.create_reviewer(
        ["STANDARD"], ["US"], display_name="R1 Deciding", max_concurrent_claims=3
    )
    adjudicating = fixtures.create_reviewer(
        ["STANDARD"], ["US"], display_name="R2 Adjudicating", max_concurrent_claims=3
    )

    notices = {}
    for key, headline, body, slug in (
        ("appealed", "Offer B", "The offer whose disapproval will be appealed.", "b"),
        ("expiring", "Offer C", "The offer whose notice is left unappealed.", "c"),
    ):
        creative, task = fixtures.creative_in_manual_review(
            advertiser_id,
            [FIN_CREDIT],
            [(rule["id"], 0.50)],
            ["US"],
            headline=headline,
            body_text=body,
            landing_page_url=f"https://www.beaconlending.example/{slug}",
            display_url=f"https://www.beaconlending.example/{slug}",
        )
        fixtures.claim_task(task["id"], deciding["id"])
        fixtures.decide_task(
            task["id"],
            deciding["id"],
            "DISAPPROVE",
            reason_codes=["MANUAL_REVIEW"],
            note="Unsubstantiated rate claims.",
        )
        notices[key] = fixtures.only_notice_for_creative(creative["id"])

    appeal = fixtures.file_appeal(
        notices["appealed"]["id"],
        advertiser_id,
        "The rate claims are documented in our published schedule.",
    )
    denied = fixtures.decide_appeal(
        appeal["id"],
        adjudicating["id"],
        "DENIED",
        note="The published schedule does not match the creative.",
    )
    assert denied["status"] == "DENIED"

    # Re-deciding a closed appeal.
    validate_error(
        api_client.decide_appeal(
            appeal["id"],
            factories.decide_appeal_payload(
                "GRANTED", "Attempting to re-decide an already denied appeal."
            ),
            make_reviewer_headers(adjudicating["id"]),
        ),
        ApiErrorId.ERR_APPEAL_NOT_PENDING,
        409,
    )
    assert fixtures.read_appeal(appeal["id"])["status"] == "DENIED"
    assert (
        fixtures.read_notice(notices["appealed"]["id"])["status"] == "APPEAL_UPHELD"
    )

    # Re-appealing a notice that already carries one: the duplicate check answers,
    # even though the notice has long left ISSUED.
    validate_error(
        api_client.create_appeal(
            factories.create_appeal_payload(
                notices["appealed"]["id"],
                "A second appeal against the same notice, filed after the first failed.",
            ),
            make_advertiser_headers(advertiser_id),
        ),
        ApiErrorId.ERR_APPEAL_ALREADY_EXISTS,
        409,
    )

    fixtures.set_clock("2026-08-06T00:00:00Z")
    counters = fixtures.run_sweep()
    assert counters["expired_notices"] == 1
    assert fixtures.read_notice(notices["expiring"]["id"])["status"] == "EXPIRED"

    # The state check answers here, not the window check.
    validate_error(
        api_client.create_appeal(
            factories.create_appeal_payload(
                notices["expiring"]["id"],
                "An appeal filed after the sweep expired the notice.",
            ),
            make_advertiser_headers(advertiser_id),
        ),
        ApiErrorId.ERR_NOTICE_NOT_APPEALABLE,
        409,
    )

    _rows, pagination = validate_paginated(api_client.list_appeals(ADMIN))
    assert pagination["total_count"] == 1

    account = fixtures.read_advertiser(advertiser_id)
    # Two 4.00 assessments and no reversal: a denied appeal compensates nothing.
    assert account["violation_points_raw"] == pytest.approx(8.00, abs=0.01)
    assert account["account_status"] == "ACTIVE"


def test_a_restricted_account_keeps_authoring_the_categories_it_may_still_use():
    """PRD §3.2: "Posture has teeth. A `RESTRICTED` account may not author a creative
    whose `declared_category_codes` include any rule of tier `PROHIBITED` or `RESTRICTED`,
    and may not author a creative with `political_flag` true; either attempt is refused
    with `ERR_ADVERTISER_RESTRICTED_CATEGORY` (HTTP 409)."

    PRD §3.2: "When the most severe action in force is a warning, the posture is `WARNED`;
    when it is a restriction, the posture is `RESTRICTED`; when it is a suspension, the
    posture is `SUSPENDED`, with severity running warning first, then restriction, then
    suspension."

    PRD §3.10: "An action records the `advertiser_id` under enforcement, the `action_type`
    — one of `WARNING`, `RESTRICTION` or `SUSPENSION`, listed here in ascending order of
    severity — the `origin` — `SYSTEM_CASCADE` when raised by a cascade and `MANUAL` when
    minted by an operator — the free-text `trigger_reason` of 1 to 300 characters, the
    `severity_index_at_issue` capturing the index at the moment of creation, the
    `effective_from` instant taken from the logical clock, the `effective_until` instant
    ending the window, and a `status` of `ACTIVE`, `LIFTED`, `SUPERSEDED` or `EXPIRED`
    beginning at `ACTIVE` with the last three terminal."

    PRD §3.10: "When `effective_until` is not supplied it defaults to `effective_from`
    plus the duration for the type: 30 days for a warning, 60 days for a restriction and
    180 days for a suspension."

    PRD §3.1: "`ACCOUNT_ENFORCEMENT` — satisfied when the owning advertiser's
    `account_status` is either `ACTIVE` or `WARNED`."

    Design: Corner/From Table 6 (Errors)/error_catalog_a_restricted_account_cannot_open_restricted_or_political_creatives
    """
    fixtures.create_policy_rule(
        ALC_SPIRITS,
        "RESTRICTED",
        6.00,
        title="Alcohol - spirits",
        requires_certification=True,
    )
    fixtures.create_policy_rule(
        FIN_CREDIT, "REGULATED", 4.00, title="Consumer credit offers"
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Northline Spirits LLC",
        country_code="US",
        industry_code="ALCOHOL_RETAIL",
    )
    advertiser_id = advertiser["id"]
    assert advertiser["version"] == 3
    action = fixtures.mint_enforcement_action(
        advertiser_id,
        "RESTRICTION",
        advertiser["version"],
        trigger_reason="Repeated late responses to policy correspondence",
    )
    author = make_advertiser_headers(advertiser_id)

    validate_error(
        api_client.create_ad_creative(
            factories.create_ad_creative_payload(
                advertiser_id,
                [ALC_SPIRITS],
                ["US"],
                headline="Cask finish",
                body_text=(
                    "A restricted category creative attempted while the account is "
                    "restricted."
                ),
                landing_page_url="https://www.northline.example/cask",
                display_url="https://www.northline.example/cask",
            ),
            author,
        ),
        ApiErrorId.ERR_ADVERTISER_RESTRICTED_CATEGORY,
        409,
    )
    validate_error(
        api_client.create_ad_creative(
            factories.create_ad_creative_payload(
                advertiser_id,
                [FIN_CREDIT],
                ["US"],
                headline="Vote yes",
                body_text=(
                    "A political creative attempted while the account is restricted."
                ),
                landing_page_url="https://www.northline.example/vote",
                display_url="https://www.northline.example/vote",
                political_flag=True,
                disclaimer_text="Paid for by Northline Spirits LLC",
            ),
            author,
        ),
        ApiErrorId.ERR_ADVERTISER_RESTRICTED_CATEGORY,
        409,
    )

    # The restriction is category-scoped, not a freeze on the account.
    permitted = validate_success(
        api_client.create_ad_creative(
            factories.create_ad_creative_payload(
                advertiser_id,
                [FIN_CREDIT],
                ["US"],
                headline="Tasting room financing",
                body_text=(
                    "A plain regulated creative that the restriction does not touch."
                ),
                landing_page_url="https://www.northline.example/finance",
                display_url="https://www.northline.example/finance",
            ),
            author,
        ),
        201,
    )
    assert permitted["review_status"] == "DRAFT"
    assert permitted["serving_eligible"] is False
    # The third conjunct fails as well while the account sits at RESTRICTED.
    assert permitted["blocking_reason_codes"] == [
        "REVIEW_NOT_APPROVED",
        "DESTINATION_NOT_CLEARED",
        "ACCOUNT_ENFORCEMENT",
    ]

    account = fixtures.read_advertiser(advertiser_id)
    assert account["account_status"] == "RESTRICTED"
    assert account["version"] == 4

    assert action["origin"] == "MANUAL"
    assert action["status"] == "ACTIVE"
    assert action["severity_index_at_issue"] == pytest.approx(0.00, abs=0.01)
    assert_instant_equals(
        action["effective_from"], "2026-08-01T00:00:00Z", "effective_from"
    )
    assert_instant_equals(
        action["effective_until"], "2026-09-30T00:00:00Z", "effective_until"
    )

    _rows, pagination = validate_paginated(
        api_client.list_ad_creatives(ADMIN, {"advertiser_id": advertiser_id})
    )
    assert pagination["total_count"] == 1, "the two refusals wrote nothing"


def test_the_retained_country_list_must_be_non_empty_duplicate_free_and_a_subset():
    """PRD §3.7: "Its `limited_country_codes` must be non-empty, must contain no
    duplicates and must be a subset of the creative's `target_country_codes`; a set that
    is empty, duplicated or not a subset is refused with `ERR_INVALID_LIMITED_COUNTRIES`
    (HTTP 422)."

    PRD §3.7: "On success the creative's `limited_country_codes` is written from the
    request sorted ascending, its `approved_under_certification_id` is written from the
    coverage selection — the candidate ranked first by `valid_until` descending with ties
    broken by `created_at` ascending — the task becomes `RESOLVED` with `resolution`
    `APPROVE_WITH_LIMITS`, a political creative gains exactly one archive entry, and
    `risk_score_final`, `serving_eligible` and `blocking_reason_codes` are recomputed
    before the creative's `version` increments by 1."

    Design: Corner/From Table 6 (Errors)/error_catalog_limited_country_list_must_be_a_non_empty_duplicate_free_subset
    """
    rule = fixtures.create_policy_rule(
        FIN_CREDIT,
        "REGULATED",
        4.00,
        title="Consumer credit offers",
        requires_certification=False,
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
        default_queue="STANDARD",
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )
    reviewer = fixtures.create_reviewer(
        ["STANDARD"], ["CA", "US"], display_name="Rev Limits Desk"
    )
    creative, task = fixtures.creative_in_manual_review(
        advertiser["id"],
        [FIN_CREDIT],
        [(rule["id"], 0.50)],
        ["CA", "US"],
        headline="Cross border credit",
        body_text="A credit offer aimed at Canada and the United States together.",
        landing_page_url="https://www.beaconlending.example/cross",
        display_url="https://www.beaconlending.example/cross",
    )
    fixtures.claim_task(task["id"], reviewer["id"])
    reviewer_headers = make_reviewer_headers(reviewer["id"])

    for rejected in ([], ["US", "US"], ["MX", "US"]):
        validate_error(
            api_client.decide_review_task(
                task["id"],
                factories.decide_review_task_payload(
                    "APPROVE_WITH_LIMITS",
                    limited_country_codes=rejected,
                    note="Retaining a country set the creative never targeted.",
                ),
                reviewer_headers,
            ),
            ApiErrorId.ERR_INVALID_LIMITED_COUNTRIES,
            422,
        )
        held = fixtures.read_task(task["id"])
        assert held["status"] == "CLAIMED", f"refused set {rejected} closed the task"
        assert held["resolution"] == "PENDING"
        assert fixtures.read_reviewer(reviewer["id"])["claimed_task_count"] == 1

    resolved = fixtures.decide_task(
        task["id"],
        reviewer["id"],
        "APPROVE_WITH_LIMITS",
        limited_country_codes=["US"],
        note="Clearing the United States only.",
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution"] == "APPROVE_WITH_LIMITS"

    approved = fixtures.read_creative(creative["id"], advertiser_id=advertiser["id"])
    assert approved["review_status"] == "APPROVED_LIMITED"
    assert approved["limited_country_codes"] == ["US"]
    # No matched rule demanded a licence, so the coverage selection stays empty.
    assert approved["approved_under_certification_id"] is None
    assert fixtures.read_reviewer(reviewer["id"])["claimed_task_count"] == 0


def test_evidence_belonging_to_another_advertiser_is_refused_as_a_mismatch_not_a_miss():
    """PRD §3.9: "The request names the `disapproval_notice_id` under challenge, a
    `justification` of 10 to 2000 characters, and optionally an `evidence_certification_id`
    offering a certification as evidence, which defaults to null; when supplied, that
    certification's `advertiser_id` must equal the advertiser behind the appealed notice's
    creative, and a mismatch is refused with `ERR_CERTIFICATION_OWNER_MISMATCH` (HTTP
    422)."

    PRD §3.9: "A successful filing creates the appeal in status `SUBMITTED` with a null
    `decided_by_reviewer_id`, a null `decided_at` and a null `reinstated_review_status`, and
    advances the notice `ISSUED → APPEALED` with its `version` incremented by 1."

    PRD §3.5: "A certification is born with `status` `SUBMITTED` and a null
    `revocation_reason`, except that when the logical clock is already at or after
    `valid_from` and strictly before `valid_until` it is born `ACTIVE` outright."

    Design: Corner/From Table 6 (Errors)/error_catalog_evidence_certification_must_belong_to_the_appealing_advertiser
    """
    rule = fixtures.create_policy_rule(
        ALC_SPIRITS,
        "RESTRICTED",
        6.00,
        title="Alcohol - spirits",
        requires_certification=True,
        requires_disclaimer=False,
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
        default_queue="REGULATED_CERT",
    )
    appellant = fixtures.create_verified_advertiser(
        legal_name="Northline Spirits LLC",
        country_code="US",
        industry_code="ALCOHOL_RETAIL",
    )
    stranger = fixtures.create_advertiser(
        legal_name="Harbour Cellars Ltd",
        country_code="US",
        industry_code="ALCOHOL_RETAIL",
    )
    foreign_licence = fixtures.create_certification(
        stranger["id"],
        rule["id"],
        valid_from="2026-07-01T00:00:00Z",
        valid_until="2026-12-31T00:00:00Z",
        issuing_country_code="US",
        headers=make_advertiser_headers(stranger["id"]),
        license_number="TTB-HC-2026-04",
    )
    # The clock sits inside the window, so the licence is live evidence to begin with.
    assert foreign_licence["status"] == "ACTIVE"

    reviewer = fixtures.create_reviewer(
        ["REGULATED_CERT"], ["US"], display_name="C. Mbeki"
    )
    creative, task = fixtures.creative_in_manual_review(
        appellant["id"],
        [ALC_SPIRITS],
        [(rule["id"], 0.50)],
        ["US"],
        headline="Cask finish",
        body_text="A spirit campaign disapproved for missing licence evidence.",
        landing_page_url="https://www.northline.example/cask",
        display_url="https://www.northline.example/cask",
    )
    fixtures.claim_task(task["id"], reviewer["id"])
    fixtures.decide_task(
        task["id"],
        reviewer["id"],
        "DISAPPROVE",
        reason_codes=["CERT_MISSING"],
        note="No licence on file for this advertiser",
    )
    notice = fixtures.only_notice_for_creative(creative["id"])
    assert notice["status"] == "ISSUED"

    validate_error(
        api_client.create_appeal(
            factories.create_appeal_payload(
                notice["id"],
                "Attaching a licence that belongs to a different advertiser.",
                evidence_certification_id=foreign_licence["id"],
            ),
            make_advertiser_headers(appellant["id"]),
        ),
        ApiErrorId.ERR_CERTIFICATION_OWNER_MISMATCH,
        422,
    )
    untouched = fixtures.read_notice(notice["id"])
    assert untouched["status"] == "ISSUED"
    assert untouched["version"] == 1

    appeal = validate_success(
        api_client.create_appeal(
            factories.create_appeal_payload(
                notice["id"],
                (
                    "Our own licence application was pending at review time; please "
                    "re-review."
                ),
            ),
            make_advertiser_headers(appellant["id"]),
        ),
        201,
    )
    assert appeal["status"] == "SUBMITTED"
    assert appeal["evidence_certification_id"] is None
    assert appeal["decided_by_reviewer_id"] is None
    assert appeal["decided_at"] is None
    assert appeal["reinstated_review_status"] is None

    appealed = fixtures.read_notice(notice["id"])
    assert appealed["status"] == "APPEALED"
    assert appealed["version"] == 2

    stranger_licence = fixtures.read_certification(foreign_licence["id"])
    assert stranger_licence["status"] == "ACTIVE"
    assert stranger_licence["version"] == 1


def test_the_clock_accepts_the_instant_it_already_holds_and_refuses_anything_earlier():
    """PRD §2.8: "Before any clock write the logical clock reads exactly
    `2026-08-01T00:00:00Z`, and it must never fall back to wall-clock time."

    PRD §2.8: "A `PolicyAdmin` moves it forward by supplying `to_iso8601`, and the response
    reports `current_utc` alongside `previous_utc`."

    PRD §2.8: "The clock never runs backwards: a `to_iso8601` earlier than the current
    logical clock, or one that is not a valid ISO 8601 UTC instant, is rejected with
    `ERR_CLOCK_REWIND` (HTTP 409)."

    PRD §2.8: "A value equal to the current clock is accepted."

    Design: Corner/From Table 6 (Errors)/error_catalog_the_logical_clock_accepts_the_same_instant_but_never_an_earlier_one
    """
    moved = fixtures.set_clock("2026-08-06T00:00:00Z")
    assert_instant_equals(moved["current_utc"], "2026-08-06T00:00:00Z", "current_utc")
    assert_instant_equals(
        moved["previous_utc"], "2026-08-01T00:00:00Z", "previous_utc"
    )

    standing_still = validate_success(
        api_client.set_clock(
            factories.set_clock_payload("2026-08-06T00:00:00Z"), ADMIN
        ),
        200,
    )
    assert_instant_equals(
        standing_still["current_utc"], "2026-08-06T00:00:00Z", "current_utc"
    )
    assert_instant_equals(
        standing_still["previous_utc"], "2026-08-06T00:00:00Z", "previous_utc"
    )

    validate_error(
        api_client.set_clock(
            factories.set_clock_payload("2026-08-05T23:59:59Z"), ADMIN
        ),
        ApiErrorId.ERR_CLOCK_REWIND,
        409,
    )
    validate_error(
        api_client.set_clock(
            factories.set_clock_payload("the sixth of August"), ADMIN
        ),
        ApiErrorId.ERR_CLOCK_REWIND,
        409,
    )

    forward = fixtures.set_clock("2026-08-07T00:00:00Z")
    assert_instant_equals(
        forward["previous_utc"],
        "2026-08-06T00:00:00Z",
        "previous_utc after two refusals",
    )


def test_a_destination_check_needs_a_known_category_and_a_reviewable_creative():
    """PRD §3.8: "A `fetched_content_category` that is neither the literal `GENERAL` nor
    the `code` of an existing policy rule is refused with `ERR_UNKNOWN_POLICY_CATEGORY`
    (HTTP 422)."

    PRD §3.8: "A check recorded against a creative whose `review_status` is `DRAFT` or
    `WITHDRAWN` is refused with `ERR_INVALID_CREATIVE_STATE`."

    PRD §3.8: "Fifth and otherwise, the result is `CLEARED` with a null `mismatch_detail`."

    PRD §3.8: "From `DESTINATION_PENDING`, a `CLEARED` result advances `DESTINATION_PENDING
    → DESTINATION_CLEARED` and a `MISMATCH` result advances `DESTINATION_PENDING →
    MISMATCH_FLAGGED`."

    Design: Corner/From Table 6 (Errors)/error_catalog_destination_checks_reject_unknown_categories_and_non_reviewable_creatives
    """
    fixtures.create_policy_rule(
        FIN_CREDIT, "REGULATED", 4.00, title="Consumer credit offers"
    )
    advertiser = fixtures.create_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )
    advertiser_id = advertiser["id"]
    fixtures.record_verification(advertiser_id, "IDENTITY", "VERIFIED")
    creative = fixtures.create_creative(
        advertiser_id,
        [FIN_CREDIT],
        ["US"],
        headline="Single offer",
        body_text="One offer used to probe the destination check guards.",
        landing_page_url="https://www.beaconlending.example/one",
        display_url="https://www.beaconlending.example/one",
    )
    landing = "https://www.beaconlending.example/one"

    def probe(check_type, category):
        return api_client.create_destination_check(
            creative["id"],
            factories.create_destination_check_payload(
                landing,
                check_type=check_type,
                user_agent_variant="CRAWLER",
                fetched_content_category=category,
                http_status=200,
            ),
            ANALYST,
        )

    # The destination axis is still NOT_CHECKED: only submission opens it.
    validate_error(
        probe("INITIAL", "GENERAL"), ApiErrorId.ERR_INVALID_CREATIVE_STATE, 409
    )

    fixtures.submit_creative(creative["id"], advertiser_id)

    validate_error(
        probe("INITIAL", "ADULT_CONTENT"),
        ApiErrorId.ERR_UNKNOWN_POLICY_CATEGORY,
        422,
    )

    cleared = validate_success(probe("INITIAL", "GENERAL"), 201)
    assert cleared["result"] == "CLEARED"
    assert cleared["mismatch_detail"] is None
    assert (
        fixtures.read_creative(creative["id"], advertiser_id=advertiser_id)[
            "destination_status"
        ]
        == "DESTINATION_CLEARED"
    )

    fixtures.withdraw_creative(creative["id"], advertiser_id)
    validate_error(
        probe("RECHECK", "GENERAL"), ApiErrorId.ERR_INVALID_CREATIVE_STATE, 409
    )

    _rows, pagination = validate_paginated(
        api_client.list_destination_checks(creative["id"], ADMIN)
    )
    assert pagination["total_count"] == 1, "neither refusal persisted a row"
