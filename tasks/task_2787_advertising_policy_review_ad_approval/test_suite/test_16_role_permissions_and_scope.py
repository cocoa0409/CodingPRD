"""Who is allowed to act, and whose rows they are allowed to act on.

The role model is a segregation of duties, so the interesting cases are the ones where a
powerful credential is refused something a weaker one may do: the platform operator who
cannot author an ad, the reviewer who cannot advance the clock, the analyst who cannot
ingest a classifier run, and the reviewer who cannot sit in judgement on their own
disapproval. Alongside those, ownership scoping keeps one advertiser out of another's
rows even for a read.
"""

import pytest

from test_helpers import (
    ADMIN,
    ANALYST,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    factories,
    fixtures,
    make_advertiser_headers,
    make_reviewer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

FIN_CREDIT = "FIN_CREDIT"
ALC_SPIRITS = "ALC_SPIRITS"
GHOST_REVIEWER_ID = "00000000-0000-4000-8000-000000000000"


def test_authoring_a_creative_is_closed_to_all_three_operator_roles():
    """PRD §2.1: "An `Advertiser` authors, revises, submits and withdraws its own
    creatives, submits certifications (a capability shared with `PolicyAdmin`) and files
    appeals."

    PRD §2.1: "A syntactically valid request whose role is not among those authorized for
    the addressed operation — the authorized set for each operation is given in the §4
    table — is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    PRD §3.3: "As a side effect the destination axis moves `NOT_CHECKED →
    DESTINATION_PENDING` when it was still `NOT_CHECKED`, and the creative's `version`
    increments by 1 with `updated_at` refreshed."

    Design: Corner/From Table 7 (RBAC)/rbac_advertiser_exclusive_creative_operations_are_refused_to_the_other_three_roles
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
    reviewer = fixtures.create_reviewer(
        ["STANDARD"], ["US"], display_name="R. Alvarez"
    )
    creative = fixtures.create_creative(
        advertiser_id,
        [FIN_CREDIT],
        ["US"],
        headline="Single offer",
        body_text="One draft creative used to probe the authoring permissions.",
        landing_page_url="https://www.beaconlending.example/one",
        display_url="https://www.beaconlending.example/one",
    )

    validate_error(
        api_client.create_ad_creative(
            factories.create_ad_creative_payload(
                advertiser_id,
                [FIN_CREDIT],
                ["US"],
                headline="Admin authored",
                body_text=(
                    "A creative the platform operator tries to author on the "
                    "advertiser's behalf."
                ),
                landing_page_url="https://www.beaconlending.example/admin",
                display_url="https://www.beaconlending.example/admin",
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api_client.revise_ad_creative(
            creative["id"],
            factories.revise_ad_creative_payload(headline="Reviewer edited"),
            make_reviewer_headers(reviewer["id"]),
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api_client.submit_ad_creative(creative["id"], ANALYST),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api_client.withdraw_ad_creative(creative["id"], ADMIN),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )

    submitted = validate_success(
        api_client.submit_ad_creative(
            creative["id"], make_advertiser_headers(advertiser_id)
        ),
        200,
    )
    assert submitted["review_status"] == "SCREENING"
    assert submitted["destination_status"] == "DESTINATION_PENDING"
    # Version 2 proves the four refusals wrote nothing: the submit was the only write.
    assert submitted["version"] == 2
    assert submitted["headline"] == "Single offer"

    _rows, pagination = validate_paginated(api_client.list_ad_creatives(ADMIN))
    assert pagination["total_count"] == 1, "the operator's create left no row"


def test_the_review_queue_belongs_to_the_reviewer_and_to_nobody_else():
    """PRD §2.1: "A `PolicyAdmin` maintains the policy framework, onboards advertisers and
    reviewers, ingests classifier screening runs, records verification outcomes, revokes
    certifications, requeues escalated tasks, mints manual enforcement actions, and drives
    the clock and sweep capabilities — but may never claim, release or decide a review
    task, and may never adjudicate an appeal."

    PRD §2.1: "A `PolicyReviewer` claims and decides queued work and adjudicates appeals —
    but may never author policy rules, country overrides or enforcement actions."

    PRD §3.6: "A successful claim writes `assigned_reviewer_id` from `X-User-ID` and
    `claimed_at` from the logical clock, increments the reviewer's `claimed_task_count` by
    1 and the reviewer's `version` by 1, and increments the task's `version` by 1."

    Design: Corner/From Table 7 (RBAC)/rbac_review_queue_operations_are_exclusive_to_the_policy_reviewer
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
    reviewer = fixtures.create_reviewer(
        ["STANDARD"], ["US"], display_name="R. Alvarez"
    )
    creative, task = fixtures.creative_in_manual_review(
        advertiser["id"],
        [FIN_CREDIT],
        [(rule["id"], 0.50)],
        ["US"],
        headline="Single offer",
        body_text="One offer routed into the standard queue for the permission probe.",
        landing_page_url="https://www.beaconlending.example/one",
        display_url="https://www.beaconlending.example/one",
    )

    validate_error(
        api_client.claim_review_task(task["id"], ADMIN),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api_client.claim_review_task(
            task["id"], make_advertiser_headers(advertiser["id"])
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )

    claimed = validate_success(
        api_client.claim_review_task(
            task["id"], make_reviewer_headers(reviewer["id"])
        ),
        200,
    )
    assert claimed["assigned_reviewer_id"] == reviewer["id"]

    validate_error(
        api_client.release_review_task(task["id"], ANALYST),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api_client.decide_review_task(
            task["id"],
            factories.decide_review_task_payload(
                "APPROVE", note="An operator trying to decide a queued review"
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )

    held = fixtures.read_task(task["id"])
    assert held["status"] == "CLAIMED", "a refused release or decision moved the task"
    assert held["resolution"] == "PENDING"
    assert held["version"] == 2, "only the claim wrote"
    assert fixtures.read_reviewer(reviewer["id"])["claimed_task_count"] == 1
    assert (
        fixtures.read_creative(creative["id"], advertiser_id=advertiser["id"])[
            "review_status"
        ]
        == "PENDING_MANUAL_REVIEW"
    )


def test_classifier_evidence_and_destination_evidence_never_share_a_credential():
    """PRD §2.1: "An `IntegrityAnalyst` is the sole source of landing-page and destination
    evidence and holds no other write capability."

    PRD §2.1: "All four roles may read; `Advertiser` reads are scoped to that advertiser's
    own creatives, certifications, notices, appeals, archive entries and ledger entries."

    PRD §3.4: "An accepted run records `ad_creative_id`, takes `sequence_index` as one
    greater than the highest index already used on that creative — so indices are
    contiguous from 1 and the greatest index is always the latest run — and snapshots the
    creative's `version` at acceptance into `creative_version_at_run`."

    PRD §3.4: "Ingesting a run increments the creative's `screening_run_count` and its
    `version` by 1."

    Design: Corner/From Table 7 (RBAC)/rbac_classifier_evidence_and_destination_evidence_can_never_share_one_role
    """
    rule = fixtures.create_policy_rule(
        FIN_CREDIT,
        "REGULATED",
        4.00,
        title="Consumer credit offers",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
    )
    advertiser = fixtures.create_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )
    advertiser_id = advertiser["id"]
    fixtures.record_verification(advertiser_id, "IDENTITY", "VERIFIED")
    creative = fixtures.submitted_creative(
        advertiser_id,
        [FIN_CREDIT],
        ["US"],
        headline="Single offer",
        body_text="One offer used to probe the two evidence endpoints.",
        landing_page_url="https://www.beaconlending.example/one",
        display_url="https://www.beaconlending.example/one",
    )
    landing = "https://www.beaconlending.example/one"
    run_payload = factories.create_screening_run_payload(
        [factories.classifier_decision_payload(rule["id"], 0.50, "credit offer")],
        creative["version"],
    )
    check_payload = factories.create_destination_check_payload(
        landing,
        check_type="INITIAL",
        user_agent_variant="CRAWLER",
        fetched_content_category="GENERAL",
        http_status=200,
    )

    validate_error(
        api_client.create_destination_check(creative["id"], check_payload, ADMIN),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api_client.create_screening_run(creative["id"], run_payload, ANALYST),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )

    run = validate_success(
        api_client.create_screening_run(creative["id"], run_payload, ADMIN), 201
    )
    assert run["sequence_index"] == 1
    check = validate_success(
        api_client.create_destination_check(creative["id"], check_payload, ANALYST),
        201,
    )
    assert check["result"] == "CLEARED"

    # Every GET is shared, so each operator sees the other's evidence.
    runs, run_page = validate_paginated(
        api_client.list_screening_runs(creative["id"], ANALYST)
    )
    assert run_page["total_count"] == 1
    assert runs[0]["id"] == run["id"]
    checks, check_page = validate_paginated(
        api_client.list_destination_checks(creative["id"], ADMIN)
    )
    assert check_page["total_count"] == 1
    assert checks[0]["id"] == check["id"]

    stored = fixtures.read_creative(creative["id"], advertiser_id=advertiser_id)
    assert stored["screening_run_count"] == 1
    assert stored["destination_status"] == "DESTINATION_CLEARED"


def test_the_catalogue_the_account_desk_and_the_test_hooks_are_admin_only():
    """PRD §2.1: "A `PolicyAdmin` maintains the policy framework, onboards advertisers and
    reviewers, ingests classifier screening runs, records verification outcomes, revokes
    certifications, requeues escalated tasks, mints manual enforcement actions, and drives
    the clock and sweep capabilities — but may never claim, release or decide a review
    task, and may never adjudicate an appeal."

    PRD §2.1: "A syntactically valid request whose role is not among those authorized for
    the addressed operation — the authorized set for each operation is given in the §4
    table — is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    PRD §3.6: "Requeueing increments `cycle_count` by 1, resets `resolution` to `PENDING`,
    recomputes `priority_score` against the advertiser's *current* state rather than the
    state at original routing, recomputes `sla_deadline_at` as the logical clock plus the
    primary rule's `review_sla_hours`, and increments the task's `version` by 1."

    Design: Corner/From Table 7 (RBAC)/rbac_policy_admin_exclusive_catalogue_and_test_driving_operations
    """
    rule = fixtures.create_policy_rule(
        FIN_CREDIT,
        "REGULATED",
        4.00,
        title="Consumer credit offers",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
        review_sla_hours=48,
        default_queue="STANDARD",
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )
    advertiser_id = advertiser["id"]
    advertiser_version = advertiser["version"]
    reviewer = fixtures.create_reviewer(
        ["STANDARD"], ["US"], display_name="R. Alvarez"
    )
    reviewer_headers = make_reviewer_headers(reviewer["id"])
    _creative, task = fixtures.creative_in_manual_review(
        advertiser_id,
        [FIN_CREDIT],
        [(rule["id"], 0.50)],
        ["US"],
        headline="Single offer",
        body_text="One offer escalated so the requeue endpoint has a live target.",
        landing_page_url="https://www.beaconlending.example/one",
        display_url="https://www.beaconlending.example/one",
    )
    fixtures.claim_task(task["id"], reviewer["id"])
    escalated = fixtures.decide_task(
        task["id"],
        reviewer["id"],
        "ESCALATE",
        note="Escalated for a policy interpretation",
    )
    assert escalated["status"] == "ESCALATED"

    validate_error(
        api_client.create_policy_rule(
            factories.create_policy_rule_payload(
                "REV_AUTHORED",
                "REGULATED",
                4.00,
                title="A rule a reviewer tries to author",
            ),
            reviewer_headers,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api_client.record_verification(
            advertiser_id,
            factories.record_verification_payload("POLITICAL_ELIGIBILITY", "ELIGIBLE"),
            make_advertiser_headers(advertiser_id),
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api_client.create_enforcement_action(
            advertiser_id,
            factories.create_enforcement_action_payload(
                "WARNING",
                advertiser_version,
                trigger_reason="An analyst trying to mint enforcement",
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api_client.requeue_review_task(task["id"], reviewer_headers),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api_client.set_clock(
            factories.set_clock_payload("2026-09-01T00:00:00Z"), reviewer_headers
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api_client.run_policy_sweep(ANALYST), ApiErrorId.ERR_FORBIDDEN_ROLE, 403
    )

    requeued = validate_success(
        api_client.requeue_review_task(task["id"], ADMIN), 200
    )
    assert requeued["status"] == "QUEUED"
    assert requeued["cycle_count"] == 1
    assert requeued["resolution"] == "PENDING"
    # The refused clock write never landed, so the deadline is 48 hours from the start.
    assert_instant_equals(
        requeued["sla_deadline_at"], "2026-08-03T00:00:00Z", "sla_deadline_at"
    )

    account = fixtures.read_advertiser(advertiser_id)
    assert account["political_eligibility_status"] == "NOT_REQUESTED"
    assert account["version"] == advertiser_version, "the refused verification wrote"

    _rules, rule_page = validate_paginated(api_client.list_policy_rules(ADMIN))
    assert rule_page["total_count"] == 1
    _actions, action_page = validate_paginated(
        api_client.list_enforcement_actions(ADMIN, {"advertiser_id": advertiser_id})
    )
    assert action_page["total_count"] == 0


def test_one_advertiser_cannot_read_or_touch_another_advertisers_creative():
    """PRD §2.1: "Concretely, an `Advertiser` may act only where `X-User-ID` equals the
    `advertiser_id` of the addressed `AdCreative`, of the addressed `Certification`, of the
    creative behind an addressed `DisapprovalNotice`, or of the creative behind the notice
    behind an addressed `Appeal`."

    PRD §2.1: "When `X-User-Role` is `PolicyReviewer`, `X-User-ID` is the `id` of the acting
    `Reviewer` record, and it must resolve to an existing `Reviewer`; task ownership
    compares a task's `assigned_reviewer_id` to `X-User-ID`, and appeal segregation compares
    a notice's `decided_by_reviewer_id` to `X-User-ID`."

    PRD §2.1: "A violation of either the advertiser-ownership rule or the reviewer-identity
    rule yields `ERR_ADVERTISER_SCOPE_VIOLATION` (HTTP 403)."

    PRD §2.10: "Ownership scoping of the acting principal —
    `ERR_ADVERTISER_SCOPE_VIOLATION`."

    PRD §2.10: "Resolution of path identifiers, left to right, as described in §2.5."

    Design: Corner/From Table 7 (RBAC)/rbac_advertiser_scope_confines_every_role_backed_identity_to_its_own_rows
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
    owner = fixtures.create_verified_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )
    stranger = fixtures.create_advertiser(
        legal_name="Harbour Cellars Ltd",
        country_code="US",
        industry_code="ALCOHOL_RETAIL",
    )
    fixtures.record_verification(stranger["id"], "IDENTITY", "VERIFIED")
    intruder = make_advertiser_headers(stranger["id"])
    creative, task = fixtures.creative_in_manual_review(
        owner["id"],
        [FIN_CREDIT],
        [(rule["id"], 0.50)],
        ["US"],
        headline="Advertiser A offer",
        body_text="A creative that belongs to advertiser A and only to advertiser A.",
        landing_page_url="https://www.beaconlending.example/one",
        display_url="https://www.beaconlending.example/one",
    )

    validate_error(
        api_client.withdraw_ad_creative(creative["id"], intruder),
        ApiErrorId.ERR_ADVERTISER_SCOPE_VIOLATION,
        403,
    )
    validate_error(
        api_client.create_ad_creative(
            factories.create_ad_creative_payload(
                owner["id"],
                [FIN_CREDIT],
                ["US"],
                headline="B authoring for A",
                body_text=(
                    "Advertiser B trying to author a creative under advertiser A's "
                    "account."
                ),
                landing_page_url="https://www.harbourcellars.example/one",
                display_url="https://www.harbourcellars.example/one",
            ),
            intruder,
        ),
        ApiErrorId.ERR_ADVERTISER_SCOPE_VIOLATION,
        403,
    )
    # The identity check runs ahead of the path-id ladder, so this is 403 and not 404.
    validate_error(
        api_client.claim_review_task(
            task["id"], make_reviewer_headers(GHOST_REVIEWER_ID)
        ),
        ApiErrorId.ERR_ADVERTISER_SCOPE_VIOLATION,
        403,
    )

    own = validate_success(
        api_client.get_ad_creative(
            creative["id"], make_advertiser_headers(owner["id"])
        ),
        200,
    )
    assert own["review_status"] == "PENDING_MANUAL_REVIEW"
    assert own["version"] == 3

    unclaimed = fixtures.read_task(task["id"])
    assert unclaimed["status"] == "QUEUED"
    assert unclaimed["assigned_reviewer_id"] is None

    _rows, pagination = validate_paginated(
        api_client.list_ad_creatives(intruder, {"advertiser_id": stranger["id"]})
    )
    assert pagination["total_count"] == 0


def test_the_reviewer_who_issued_the_notice_may_not_adjudicate_its_appeal():
    """PRD §3.9: "Both branches require that the appeal's `status` is `SUBMITTED` and its
    notice's `status` is `APPEALED` — otherwise `ERR_APPEAL_NOT_PENDING` (HTTP 409) — and
    both require that the acting reviewer's identifier differs from the notice's
    `decided_by_reviewer_id`, since no reviewer may sit in judgement on their own
    disapproval; a self-adjudication attempt is refused with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)."

    PRD §3.9: "Both branches write `decided_by_reviewer_id` and set `decided_at` to the
    logical clock, and both increment the appeal's `version` by 1."

    PRD §3.9: "A `DENIED` outcome advances the appeal `SUBMITTED → DENIED` and moves the
    notice `APPEALED → APPEAL_UPHELD`, and it does deliberately less."

    Design: Corner/From Table 7 (RBAC)/rbac_segregation_of_duties_bars_the_issuing_reviewer_from_adjudicating_the_appeal
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
    issuing = fixtures.create_reviewer(
        ["STANDARD"], ["US"], display_name="R1 Deciding"
    )
    adjudicating = fixtures.create_reviewer(
        ["STANDARD"], ["US"], display_name="R2 Adjudicating"
    )
    creative, task = fixtures.creative_in_manual_review(
        advertiser_id,
        [FIN_CREDIT],
        [(rule["id"], 0.50)],
        ["US"],
        headline="Single offer",
        body_text="One offer disapproved by R1 and appealed by its owner.",
        landing_page_url="https://www.beaconlending.example/one",
        display_url="https://www.beaconlending.example/one",
    )
    fixtures.claim_task(task["id"], issuing["id"])
    fixtures.decide_task(
        task["id"],
        issuing["id"],
        "DISAPPROVE",
        reason_codes=["MANUAL_REVIEW"],
        note="Unsubstantiated rate claims",
    )
    notice = fixtures.only_notice_for_creative(creative["id"])
    assert notice["decided_by_reviewer_id"] == issuing["id"]
    appeal = fixtures.file_appeal(
        notice["id"],
        advertiser_id,
        "The published rate schedule supports every claim in the creative.",
    )

    # Same role, same queue, same country authorisations: only the identity differs.
    validate_error(
        api_client.decide_appeal(
            appeal["id"],
            factories.decide_appeal_payload(
                "DENIED", "The issuing reviewer trying to close their own appeal"
            ),
            make_reviewer_headers(issuing["id"]),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    pending = fixtures.read_appeal(appeal["id"])
    assert pending["status"] == "SUBMITTED"
    assert pending["decided_by_reviewer_id"] is None
    assert pending["version"] == 1

    denied = validate_success(
        api_client.decide_appeal(
            appeal["id"],
            factories.decide_appeal_payload(
                "DENIED", "A second reviewer confirms the original disapproval"
            ),
            make_reviewer_headers(adjudicating["id"]),
        ),
        200,
    )
    assert denied["status"] == "DENIED"
    assert denied["decided_by_reviewer_id"] == adjudicating["id"]
    assert_instant_equals(
        denied["decided_at"], "2026-08-01T00:00:00Z", "decided_at"
    )
    assert denied["reinstated_review_status"] is None

    assert fixtures.read_notice(notice["id"])["status"] == "APPEAL_UPHELD"
    assert (
        fixtures.read_creative(creative["id"], advertiser_id=advertiser_id)[
            "review_status"
        ]
        == "DISAPPROVED"
    )

    entries = fixtures.ledger_for_advertiser(advertiser_id)
    assert len(entries) == 1, "a denied appeal writes no compensating entry"
    assert entries[0]["delta_points"] == pytest.approx(4.00, abs=0.01)


def test_filing_a_licence_is_shared_with_the_operator_but_still_scoped_for_the_owner():
    """PRD §2.1: "An `Advertiser` authors, revises, submits and withdraws its own creatives,
    submits certifications (a capability shared with `PolicyAdmin`) and files appeals."

    PRD §2.1: "This scope rule guards creative creation, creative revision, creative
    submission, creative withdrawal, certification submission, appeal filing, and every
    `PolicyReviewer` action on review tasks and appeals."

    PRD §3.5: "A certification is born with `status` `SUBMITTED` and a null
    `revocation_reason`, except that when the logical clock is already at or after
    `valid_from` and strictly before `valid_until` it is born `ACTIVE` outright."

    PRD §2.3: "Several lists do declare their own ordering, and where they do it overrides
    the default: the policy framework list is ordered by `code` ascending, a rule's country
    variations by `country_code` ascending, a creative's screening runs by `sequence_index`
    ascending, a ledger listing by `entry_index` ascending, archive entries by `archived_at`
    ascending, certifications by `valid_from` ascending and then `created_at` ascending,
    enforcement actions by `effective_from` ascending and then `created_at` ascending, and
    review tasks by `priority_score` descending and then `created_at` ascending."

    Design: Corner/From Table 7 (RBAC)/rbac_certification_submission_is_shared_by_advertiser_and_policy_admin_only
    """
    rule = fixtures.create_policy_rule(
        ALC_SPIRITS,
        "RESTRICTED",
        6.00,
        title="Alcohol - spirits",
        requires_certification=True,
    )
    holder = fixtures.create_advertiser(
        legal_name="Northline Spirits LLC",
        country_code="US",
        industry_code="ALCOHOL_RETAIL",
    )
    fixtures.record_verification(holder["id"], "IDENTITY", "VERIFIED")
    stranger = fixtures.create_advertiser(
        legal_name="Harbour Cellars Ltd",
        country_code="CA",
        industry_code="ALCOHOL_RETAIL",
    )
    fixtures.record_verification(stranger["id"], "IDENTITY", "VERIFIED")
    reviewer = fixtures.create_reviewer(
        ["REGULATED_CERT"], ["US"], display_name="R. Alvarez"
    )

    def licence_payload(license_number, issuing_country_code):
        return factories.create_certification_payload(
            holder["id"],
            rule["id"],
            "2026-07-01T00:00:00Z",
            "2026-12-31T00:00:00Z",
            issuing_country_code,
            license_number=license_number,
        )

    self_filed = validate_success(
        api_client.create_certification(
            licence_payload("TTB-NL-US-01", "US"),
            make_advertiser_headers(holder["id"]),
        ),
        201,
    )
    # The clock sits inside the window, so both licences are born live.
    assert self_filed["status"] == "ACTIVE"

    admin_filed = validate_success(
        api_client.create_certification(licence_payload("AGCO-NL-CA-01", "CA"), ADMIN),
        201,
    )
    assert admin_filed["status"] == "ACTIVE"
    assert admin_filed["advertiser_id"] == holder["id"]

    validate_error(
        api_client.create_certification(
            licence_payload("REV-NL-MX-01", "MX"),
            make_reviewer_headers(reviewer["id"]),
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api_client.create_certification(
            licence_payload("ANL-NL-BR-01", "BR"), ANALYST
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    # The shared write is still ownership-scoped for the Advertiser role.
    validate_error(
        api_client.create_certification(
            licence_payload("HC-NL-GB-01", "GB"),
            make_advertiser_headers(stranger["id"]),
        ),
        ApiErrorId.ERR_ADVERTISER_SCOPE_VIOLATION,
        403,
    )

    rows, pagination = validate_paginated(
        api_client.list_certifications(ADMIN, {"advertiser_id": holder["id"]})
    )
    assert pagination["total_count"] == 2
    # Equal `valid_from` values, so the insertion order breaks the tie.
    assert [row["issuing_country_code"] for row in rows] == ["US", "CA"]


def test_the_reviewer_roster_and_the_per_rule_decision_log_are_closed_to_advertisers():
    """PRD §2.1: "All four roles may read; `Advertiser` reads are scoped to that
    advertiser's own creatives, certifications, notices, appeals, archive entries and ledger
    entries."

    PRD §2.1: "A syntactically valid request whose role is not among those authorized for
    the addressed operation — the authorized set for each operation is given in the §4
    table — is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    PRD §3.4: "Comparing the decision's `confidence` against the thresholds of the rule it
    matched, and treating every threshold as an inclusive lower bound, the decision's
    `disposition` is `AUTO_DISAPPROVE` when `confidence` is at least that rule's
    `confidence_auto_disapprove_threshold`, otherwise `ROUTE_MANUAL` when `confidence` is at
    least that rule's `confidence_manual_threshold`, and otherwise `BELOW_THRESHOLD`."

    Design: Corner/From Table 7 (RBAC)/rbac_reads_are_shared_but_the_reviewer_roster_and_decision_log_are_closed_to_advertisers
    """
    rule = fixtures.create_policy_rule(
        FIN_CREDIT,
        "REGULATED",
        4.00,
        title="Consumer credit offers",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
    )
    advertiser = fixtures.create_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )
    advertiser_id = advertiser["id"]
    fixtures.record_verification(advertiser_id, "IDENTITY", "VERIFIED")
    reviewer = fixtures.create_reviewer(
        ["STANDARD"], ["US"], display_name="R. Alvarez"
    )
    creative = fixtures.submitted_creative(
        advertiser_id,
        [FIN_CREDIT],
        ["US"],
        headline="Single offer",
        body_text="One offer whose classifier decision lands in the per-rule log.",
        landing_page_url="https://www.beaconlending.example/one",
        display_url="https://www.beaconlending.example/one",
    )
    run = fixtures.screen_creative(
        creative["id"], [(rule["id"], 0.50)], creative["version"]
    )
    author = make_advertiser_headers(advertiser_id)

    # The framework itself and the advertiser's own screening evidence are readable.
    assert validate_success(api_client.get_policy_rule(rule["id"], author))["code"] == (
        FIN_CREDIT
    )
    own_decisions, own_page = validate_paginated(
        api_client.list_run_classifier_decisions(run["id"], author)
    )
    assert own_page["total_count"] == 1
    assert own_decisions[0]["confidence"] == pytest.approx(0.50, abs=0.01)
    assert own_decisions[0]["disposition"] == "ROUTE_MANUAL"

    validate_error(
        api_client.get_reviewer(reviewer["id"], author),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api_client.list_rule_classifier_decisions(rule["id"], author),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )

    # The same two URLs are open to the three operator roles.
    assert validate_success(api_client.get_reviewer(reviewer["id"], ANALYST))[
        "display_name"
    ] == "R. Alvarez"
    log_rows, log_page = validate_paginated(
        api_client.list_rule_classifier_decisions(
            rule["id"], make_reviewer_headers(reviewer["id"])
        )
    )
    assert log_page["total_count"] == 1
    assert log_rows[0]["screening_run_id"] == run["id"]
