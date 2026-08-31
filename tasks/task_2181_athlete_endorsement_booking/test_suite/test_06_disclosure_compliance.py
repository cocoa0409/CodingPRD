"""Paid-promotion disclosure: filing, rulings, remediation and the approval gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_disclosure_record,
    assert_exposure_summary,
    create_disclosure_record_payload,
    make_athlete_headers,
    make_brand_rep_headers,
    make_compliance_officer_headers,
    read_engagement,
    review_deliverable_payload,
    rule_disclosure,
    rule_disclosure_payload,
    setup_deliverable_awaiting_disclosure,
    validate_error,
    validate_paginated,
    validate_success,
)

AGENT = TEST_USERS["talent_agent_headers"]
SCREENING_OFFICER = make_compliance_officer_headers("co-screen-1")
REVIEWING_OFFICER = make_compliance_officer_headers("co-review-9")


def test_second_live_disclosure_on_one_deliverable_is_refused(api):
    """PRD 3.8: "A deliverable may hold at most one record whose `status` is
    `PENDING_REVIEW` or `COMPLIANT` at any moment; filing a second while one of those
    is live is refused with `ERR_DUPLICATE_DISCLOSURE`."

    Design: Corner/validations/duplicate_disclosure_for_same_deliverable_is_refused
    """
    deal = setup_deliverable_awaiting_disclosure(disclosure_tag="#ad")

    response = api.create_disclosure_record(
        create_disclosure_record_payload(
            deal["deliverable"]["id"], platform="X", disclosure_tag="#ad",
            posted_at="2026-09-19T13:00:00Z",
        ),
        make_athlete_headers(deal["athlete_id"]),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_DISCLOSURE.value, 409)

    rows, _meta = validate_paginated(
        api.list_disclosure_records(deal["deliverable"]["id"], AGENT)
    )
    assert len(rows) == 1
    assert rows[0]["id"] == deal["disclosure_record"]["id"]


def test_remediation_returns_the_record_to_review_and_unblocks_approval(api):
    """PRD 3.8: "Remediating a record that is `NON_COMPLIANT` supplies a corrected
    `disclosure_tag` and a fresh `posted_at`, overwriting both, increments
    `remediation_count` by 1, clears `ruled_by_user_id` back to null, and moves the
    record `NON_COMPLIANT → PENDING_REVIEW` — closing the cycle
    `PENDING_REVIEW → NON_COMPLIANT → PENDING_REVIEW`."
    PRD 3.8: "When it passes, the record moves `PENDING_REVIEW → COMPLIANT`,
    `ruled_by_user_id` is stamped with the officer, and the parent deliverable's
    approval gate is thereby unblocked."

    Design: Corner/state_machines/disclosure_remediate_cycle_returns_to_pending_review
    """
    deal = setup_deliverable_awaiting_disclosure(disclosure_tag="#sp")
    record_id = deal["disclosure_record"]["id"]
    rule_disclosure(record_id, "NON_COMPLIANT", finding_note="#sp is not an accepted tag")

    remediated = validate_success(
        api.remediate_disclosure_record(
            record_id,
            {"disclosure_tag": "#ad", "posted_at": "2026-09-19T18:00:00Z"},
            make_athlete_headers(deal["athlete_id"]),
        ),
        200,
    )
    assert_disclosure_record(remediated)
    assert remediated["status"] == "PENDING_REVIEW"
    assert remediated["remediation_count"] == 1
    assert remediated["disclosure_tag"] == "#ad"
    assert remediated["ruled_by_user_id"] is None

    ruled = validate_success(
        api.rule_disclosure_record(
            record_id, rule_disclosure_payload("COMPLIANT"), REVIEWING_OFFICER
        ),
        200,
    )
    assert ruled["status"] == "COMPLIANT"
    assert ruled["ruled_by_user_id"] == "co-review-9"

    approved = validate_success(
        api.review_deliverable(
            deal["deliverable"]["id"], review_deliverable_payload("APPROVE"),
            make_brand_rep_headers(deal["brand_id"]),
        ),
        200,
    )
    assert approved["status"] == "APPROVED"

    engagement = read_engagement(deal["engagement_id"])
    assert engagement["contract_status"] == "COMPLETED"
    assert engagement["settlement_status"] == "BILLABLE"

    athlete = validate_success(api.get_athlete(deal["athlete_id"], AGENT))
    assert athlete["exposure_risk_snapshot_score"] == 12


def test_second_ruling_on_a_compliant_record_is_refused(api):
    """PRD 3.8: "A `ComplianceOfficer` rules on a record still in `PENDING_REVIEW`,
    supplying a `ruling` of `COMPLIANT` or `NON_COMPLIANT` and an optional
    `finding_note`. Ruling on a record that is not `PENDING_REVIEW` is refused with
    `ERR_DISCLOSURE_INVALID_STATE`."
    PRD 3.10: "The `score` is twelve points for each unit of `category_load`, plus
    eight points for each unit of `morals_exposure`, plus fifteen points for each unit
    of `noncompliance_hits`, with a ceiling of 100 applied once at the very end. All
    of the arithmetic is integer arithmetic."

    Design: Corner/validations/second_ruling_on_compliant_disclosure_returns_invalid_state
    """
    deal = setup_deliverable_awaiting_disclosure(disclosure_tag="#ad")
    record_id = deal["disclosure_record"]["id"]
    rule_disclosure(record_id, "COMPLIANT")

    response = api.rule_disclosure_record(
        record_id, rule_disclosure_payload("NON_COMPLIANT", "second look"),
        REVIEWING_OFFICER,
    )
    validate_error(response, ApiErrorId.ERR_DISCLOSURE_INVALID_STATE.value, 409)

    stored = validate_success(api.get_athlete(deal["athlete_id"], AGENT))
    assert stored["exposure_risk_snapshot_score"] == 28

    rows, _meta = validate_paginated(
        api.list_disclosure_records(deal["deliverable"]["id"], AGENT, params={"status": "COMPLIANT"})
    )
    assert len(rows) == 1


def test_the_screening_officer_may_not_rule_on_the_same_deals_disclosure(api):
    """PRD 2.1: "The officer who screened an opportunity may not later rule on any
    disclosure record belonging to that opportunity's engagement. If the `X-User-ID`
    presented on a disclosure ruling equals the `screened_by_user_id` recorded on the
    opportunity behind that deliverable's engagement, the ruling is refused with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD 3.8: "Whichever way the ruling goes, the officer must not be the same person
    who screened the underlying opportunity — the officer's `X-User-ID` is compared
    against the `screened_by_user_id` recorded on the opportunity behind this
    deliverable's engagement, and a match is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/screening_officer_cannot_rule_on_own_engagements_disclosure
    """
    deal = setup_deliverable_awaiting_disclosure(disclosure_tag="#ad")
    record_id = deal["disclosure_record"]["id"]

    refused = api.rule_disclosure_record(
        record_id, rule_disclosure_payload("COMPLIANT"), SCREENING_OFFICER
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    pending = validate_success(api.list_disclosure_records(deal["deliverable"]["id"], AGENT))
    assert pending[0]["status"] == "PENDING_REVIEW"
    assert pending[0]["ruled_by_user_id"] is None

    accepted = validate_success(
        api.rule_disclosure_record(
            record_id, rule_disclosure_payload("COMPLIANT"), REVIEWING_OFFICER
        ),
        200,
    )
    assert accepted["status"] == "COMPLIANT"
    assert accepted["ruled_by_user_id"] == "co-review-9"


def test_non_compliant_ruling_raises_the_exposure_snapshot(api):
    """PRD 3.8: "It moves the record `PENDING_REVIEW → NON_COMPLIANT`, stamps
    `ruled_by_user_id` and stores the `finding_note`, and because the athlete's
    non-compliance tally has grown by one, that athlete's
    `exposure_risk_snapshot_score` is recomputed and rewritten."
    PRD 3.10: "`noncompliance_hits` counts the disclosure records that are currently
    `NON_COMPLIANT` and belong, through their deliverable, to an engagement of this
    athlete."
    PRD 3.10: "The `score` is twelve points for each unit of `category_load`, plus
    eight points for each unit of `morals_exposure`, plus fifteen points for each unit
    of `noncompliance_hits`, with a ceiling of 100 applied once at the very end. All
    of the arithmetic is integer arithmetic."

    Design: Corner/calculations/exposure_snapshot_counts_noncompliance_hits
    """
    deal = setup_deliverable_awaiting_disclosure(
        disclosure_tag="#collab", platform="TIKTOK"
    )
    record_id = deal["disclosure_record"]["id"]

    ruled = validate_success(
        api.rule_disclosure_record(
            record_id,
            rule_disclosure_payload("NON_COMPLIANT", "#collab does not disclose payment"),
            REVIEWING_OFFICER,
        ),
        200,
    )
    assert ruled["status"] == "NON_COMPLIANT"

    athlete = validate_success(api.get_athlete(deal["athlete_id"], AGENT))
    assert athlete["exposure_risk_snapshot_score"] == 43

    summary = validate_success(api.get_exposure_summary(deal["athlete_id"], AGENT))
    assert_exposure_summary(summary, deal["athlete_id"])
    assert summary["score"] == 43
    assert summary["noncompliance_hits"] == 1
    assert summary["category_load"] == 1
    assert summary["morals_exposure"] == 2


def test_approval_is_refused_while_the_only_disclosure_is_non_compliant(api):
    """PRD 3.7: "A `decision` of `APPROVE` first checks the disclosure gate: when the
    deliverable's `disclosure_required` is true, at least one disclosure record filed
    against it must have `status` `COMPLIANT`, or the approval is refused with
    `ERR_DISCLOSURE_NOT_COMPLIANT`."

    Design: Difficulty/cross_entity_state_dependency/deliverable_approve_blocked_by_noncompliant_disclosure
    """
    deal = setup_deliverable_awaiting_disclosure(disclosure_tag="#sp")
    rule_disclosure(
        deal["disclosure_record"]["id"], "NON_COMPLIANT",
        finding_note="#sp is not an accepted disclosure tag",
    )

    response = api.review_deliverable(
        deal["deliverable"]["id"], review_deliverable_payload("APPROVE"),
        make_brand_rep_headers(deal["brand_id"]),
    )
    validate_error(response, ApiErrorId.ERR_DISCLOSURE_NOT_COMPLIANT.value, 422)


def test_refused_approval_leaves_the_engagement_counters_untouched(api):
    """PRD 3.7: "Review too requires the engagement to be `ACTIVE`, failing with
    `ERR_ENGAGEMENT_NOT_ACTIVE` otherwise, and it requires the deliverable to be
    `SUBMITTED`, failing with `ERR_DELIVERABLE_INVALID_STATE` otherwise."
    PRD 3.7: "A `decision` of `APPROVE` first checks the disclosure gate: when the
    deliverable's `disclosure_required` is true, at least one disclosure record filed
    against it must have `status` `COMPLIANT`, or the approval is refused with
    `ERR_DISCLOSURE_NOT_COMPLIANT`."

    Design: Difficulty/cross_entity_state_dependency/deliverable_approve_blocked_by_noncompliant_disclosure
    """
    deal = setup_deliverable_awaiting_disclosure(disclosure_tag="#sp")
    rule_disclosure(
        deal["disclosure_record"]["id"], "NON_COMPLIANT",
        finding_note="#sp is not an accepted disclosure tag",
    )

    response = api.review_deliverable(
        deal["deliverable"]["id"], review_deliverable_payload("APPROVE"),
        make_brand_rep_headers(deal["brand_id"]),
    )
    validate_error(response, ApiErrorId.ERR_DISCLOSURE_NOT_COMPLIANT.value, 422)

    deliverable = validate_success(api.get_deliverable(deal["deliverable"]["id"], AGENT))
    assert deliverable["status"] == "SUBMITTED"

    engagement = read_engagement(deal["engagement_id"])
    assert engagement["approved_deliverable_count"] == 0
    assert engagement["contract_status"] == "ACTIVE"
    assert engagement["settlement_status"] == "UNBILLED"
