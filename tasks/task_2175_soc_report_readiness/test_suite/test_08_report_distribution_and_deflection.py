"""Reaching the report, distributing it, bridging it forward, articulating the
complementary user entity controls, and deflecting customer questionnaires."""

from test_helpers import (
    CLOCK_DEFAULT,
    TEST_USERS,
    ApiErrorId,
    create_bridge_letter,
    create_cuec,
    create_distribution,
    create_engagement,
    create_manual_gap,
    create_questionnaire,
    distribution_action,
    issue_bridge_letter,
    read_engagement,
    setup_delivered_report,
    setup_engagement_at,
    validate_error,
    validate_paginated,
    validate_success,
)

CL_HEADERS = TEST_USERS["compliance_lead_headers"]
AE_HEADERS = TEST_USERS["account_executive_headers"]
AUD_HEADERS = TEST_USERS["auditor_headers"]


def test_delivery_before_the_engagement_is_issued_is_rejected(api):
    """PRD 3.8: "`APPROVED → DELIVERED`, performed by an `AccountExecutive`, is where the
    report actually changes hands, and it is doubly gated: the engagement's `status` must
    be `ISSUED` and its `gap_posture` must be exactly `OPEN`, so a frozen engagement blocks
    delivery with `ERR_ENGAGEMENT_FROZEN` and a restricted one with
    `ERR_ENGAGEMENT_RESTRICTED`."
    PRD 2.7: "**Engagement phase.** The engagement's `status` is a member of the phase set
    the operation requires, else `ERR_ENGAGEMENT_PHASE_INVALID` (409)."

    Design: Corner/state_machines/corner_report_distribution_deliver_before_engagement_issued_rejected
    """
    engagement = create_engagement(client_name="Eager")
    distribution = create_distribution(engagement["id"])
    distribution_action(distribution["id"], "REQUEST_NDA", AE_HEADERS)
    distribution_action(distribution["id"], "APPROVE", CL_HEADERS, nda_reference="NDA-0001")

    response = api.transition_report_distribution(
        distribution["id"], {"action": "DELIVER"}, AE_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_ENGAGEMENT_PHASE_INVALID.value, 409)

    stored = validate_success(api.get_report_distribution(distribution["id"], CL_HEADERS))
    assert stored["status"] == "APPROVED"
    assert stored["nda_reference"] == "NDA-0001"
    assert stored["delivered_at"] is None
    assert stored["report_period_end"] is None


def test_cuec_walks_draft_to_articulated_to_retired(api):
    """PRD 3.9: "Drafts begin with `articulation_status` `DRAFT` and a null
    `articulated_at`."
    PRD 3.9: "`ARTICULATE` moves `DRAFT → ARTICULATED` and requires the engagement to be in
    `READINESS`, `OBSERVATION`, `FIELDWORK` or `REPORTING`, and requires afresh that the
    referenced criterion's `category` is a member of the engagement's
    `required_criteria_categories` and that its `applies_to_report_types` contains the
    engagement's `report_type`. It stamps `articulated_at` from the logical clock."
    PRD 3.9: "`RETIRE` moves either `ARTICULATED → RETIRED` or `DRAFT → RETIRED` and is
    permitted while the engagement has not reached `ISSUED`; retiring from `ARTICULATED`
    removes the statement from the third deflection bucket, while retiring from `DRAFT` has
    no cross-entity effect."

    Design: Corner/state_machines/corner_cuec_articulate_then_retire_walks_the_full_lifecycle
    """
    scenario = setup_engagement_at(phase="READINESS", client_name="Complementary")
    cuec = create_cuec(
        scenario["engagement_id"],
        scenario["criteria"]["CC1.1"]["id"],
        statement="User entities must review their own access reports quarterly.",
        deflection_topic="user-access",
    )
    assert cuec["articulation_status"] == "DRAFT"
    assert cuec["articulated_at"] is None

    articulated = validate_success(
        api.articulate_cuec(cuec["id"], {"action": "ARTICULATE"}, CL_HEADERS)
    )
    assert articulated["articulation_status"] == "ARTICULATED"
    assert articulated["articulated_at"] == CLOCK_DEFAULT

    retired = validate_success(
        api.articulate_cuec(cuec["id"], {"action": "RETIRE"}, CL_HEADERS)
    )
    assert retired["articulation_status"] == "RETIRED"

    _, meta = validate_paginated(
        api.list_cuecs(
            CL_HEADERS,
            params={
                "engagement_id": scenario["engagement_id"],
                "articulation_status": "ARTICULATED",
            },
        )
    )
    assert meta["total_count"] == 0


def test_bridge_letter_coverage_days_counts_both_closed_endpoints(api):
    """PRD 3.9: "The coverage window is **closed**: both endpoints lie inside it, so
    `coverage_days` is the difference between `as_of_date` and `coverage_start` in seconds,
    divided by 86400, truncated downward to a whole number, and then increased by one — a
    single-instant letter whose `as_of_date` equals its `coverage_start` therefore has a
    `coverage_days` of 1."
    PRD 3.9: "Drafts begin in `DRAFT` with `issued_at` and `issued_by_user_id` null."

    Design: Corner/calculations/corner_bridge_letter_coverage_days_counts_both_closed_endpoints
    """
    engagement = create_engagement(client_name="Bridge Math")

    single_instant = validate_success(
        api.create_bridge_letter(
            {
                "engagement_id": engagement["id"],
                "coverage_start": "2026-11-30T00:00:00.000Z",
                "as_of_date": "2026-11-30T00:00:00.000Z",
            },
            AE_HEADERS,
        ),
        201,
    )
    assert single_instant["coverage_days"] == 1
    assert single_instant["status"] == "DRAFT"
    assert single_instant["issued_at"] is None

    month_long = validate_success(
        api.create_bridge_letter(
            {
                "engagement_id": engagement["id"],
                "coverage_start": "2026-11-30T00:00:00.000Z",
                "as_of_date": "2026-12-31T00:00:00.000Z",
            },
            AE_HEADERS,
        ),
        201,
    )
    assert month_long["coverage_days"] == 32, (
        f"31 whole days plus the closed endpoint is 32, got {month_long['coverage_days']}"
    )
    assert month_long["supersedes_bridge_letter_id"] is None


def test_bridge_letter_longer_than_the_maximum_is_rejected(api):
    """PRD 3.9: "A letter may not stretch beyond 120 days: a `coverage_days` above that is
    rejected as a malformed request under `ERR_VALIDATION`."

    Design: Corner/calculations/corner_bridge_letter_beyond_max_days_rejected
    """
    engagement = create_engagement(client_name="Too Long")

    response = api.create_bridge_letter(
        {
            "engagement_id": engagement["id"],
            "coverage_start": "2026-11-30T00:00:00.000Z",
            "as_of_date": "2027-04-30T00:00:00.000Z",
        },
        AE_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)

    _, meta = validate_paginated(
        api.list_bridge_letters(AE_HEADERS, params={"engagement_id": engagement["id"]})
    )
    assert meta["total_count"] == 0


def test_a_restricted_posture_blocks_the_report_track(api):
    """PRD 3.8: "Four conditions must hold together. The engagement's posture must be
    exactly `OPEN` — a merely restricted engagement is rejected with
    `ERR_ENGAGEMENT_RESTRICTED`."
    PRD 2.8: "Four operations demand the strictly stronger condition that the posture be
    `OPEN` and reject a merely restricted engagement with `ERR_ENGAGEMENT_RESTRICTED`:
    advancing the engagement to the reporting phase, issuing the report, delivering a
    report distribution, and issuing a bridge letter."

    Design: Corner/errors/corner_restricted_posture_blocks_start_reporting
    """
    scenario = setup_engagement_at(phase="FIELDWORK", client_name="Held Back")
    create_manual_gap(scenario["engagement_id"], "HIGH", "Late remediation finding")
    create_manual_gap(scenario["engagement_id"], "MODERATE", "Documentation lag")

    response = api.transition_engagement(
        scenario["engagement_id"], {"action": "START_REPORTING"}, AUD_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_ENGAGEMENT_RESTRICTED.value, 409)

    engagement = read_engagement(scenario["engagement_id"])
    assert engagement["status"] == "FIELDWORK"
    assert engagement["base_debt_points"] == 11
    assert engagement["gap_debt_points"] == 12.65
    assert engagement["gap_posture"] == "RESTRICTED"


def test_deflection_before_the_report_is_delivered_is_rejected(api):
    """PRD 3.9: "It is refused unless the questionnaire's own referenced distribution has
    reached `DELIVERED`, with `ERR_REPORT_NOT_DELIVERED` otherwise."
    PRD 3.9: "The server sets `item_count` to the sum of the three and starts the row in
    `RECEIVED` with every bucket counter and `deflection_ratio` at 0,
    `bridge_letter_id_used` null and `as_of_date` null."

    Design: Corner/errors/corner_questionnaire_deflect_before_distribution_delivered_rejected
    """
    engagement = create_engagement(client_name="Too Early")
    distribution = create_distribution(engagement["id"])
    questionnaire = create_questionnaire(
        engagement["id"],
        distribution["id"],
        criteria_item_count=2,
        post_period_item_count=1,
        cuec_item_count=1,
    )

    response = api.deflect_customer_questionnaire(
        questionnaire["id"], {"as_of_date": "2026-12-15T00:00:00.000Z"}, AE_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_REPORT_NOT_DELIVERED.value, 409)

    stored = validate_success(
        api.get_customer_questionnaire(questionnaire["id"], AE_HEADERS)
    )
    assert stored["status"] == "RECEIVED"
    assert stored["item_count"] == 4
    assert stored["deflected_by_report_count"] == 0
    assert stored["deflected_by_bridge_count"] == 0
    assert stored["deflected_by_cuec_count"] == 0
    assert stored["manual_response_count"] == 0
    assert stored["deflection_ratio"] == 0.0000
    assert stored["as_of_date"] is None
    assert validate_success(api.get_report_distribution(distribution["id"], CL_HEADERS))[
        "status"
    ] == "REQUESTED"


def test_a_shared_transition_endpoint_still_splits_its_actions_by_role(api):
    """PRD 2.1: "Several endpoints accept an `action`, `disposition` or `method` field and
    are shared between two roles that are each permitted only a subset of the possible
    values; where §3 names the acting role for a particular transition, a
    permitted-on-the-endpoint role that is not the named actor for the requested value is
    likewise rejected with `ERR_ROLE_NOT_PERMITTED`."
    PRD 3.8: "An `AccountExecutive` moves `REQUESTED → NDA_PENDING` with `REQUEST_NDA`. A
    `ComplianceLead` then moves `NDA_PENDING → APPROVED` with `APPROVE`, which requires a
    non-null `nda_reference` in the payload and stamps it onto the row — a distribution
    cannot leave `NDA_PENDING` without an executed agreement reference."

    Design: Corner/rbac/corner_action_level_role_split_inside_shared_transition_endpoints
    """
    engagement = create_engagement(client_name="Shared Endpoint")
    distribution = create_distribution(engagement["id"])
    distribution_action(distribution["id"], "REQUEST_NDA", AE_HEADERS)

    wrong_actor = api.transition_report_distribution(
        distribution["id"], {"action": "APPROVE", "nda_reference": "NDA-0002"}, AE_HEADERS
    )
    validate_error(wrong_actor, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    approved = validate_success(
        api.transition_report_distribution(
            distribution["id"], {"action": "APPROVE", "nda_reference": "NDA-0002"}, CL_HEADERS
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["nda_reference"] == "NDA-0002"


def build_ceiling_of_one():
    """An engagement whose distribution ceiling is 1 and which already holds one live
    REQUESTED row for 'Acme Corp'."""
    engagement = create_engagement(client_name="Proseware", max_distribution_recipients=1)
    distribution = create_distribution(
        engagement["id"], recipient_name="Acme Corp", recipient_email="soc@acme.example"
    )
    return engagement, distribution


def test_a_duplicate_recipient_at_the_ceiling_reports_the_duplicate(api):
    """PRD 3.8: "The recipient name must be unique within the engagement among rows whose
    `status` is neither `REVOKED` nor `DENIED`, and a repeat is `ERR_DUPLICATE_RESOURCE`."
    PRD 3.8: "Because uniqueness is judged first, a duplicate recipient submitted while the
    engagement already sits at its ceiling reports the duplicate."

    Design: Difficulty/priority_pair_validation_conflict/duplicate_recipient_constraint_beats_distribution_ceiling_fiscal
    """
    engagement, distribution = build_ceiling_of_one()

    response = api.create_report_distribution(
        {
            "engagement_id": engagement["id"],
            "recipient_name": "Acme Corp",
            "recipient_email": "audit@acme.example",
        },
        AE_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_RESOURCE.value, 409)

    _, meta = validate_paginated(
        api.list_report_distributions(AE_HEADERS, params={"engagement_id": engagement["id"]})
    )
    assert meta["total_count"] == 1
    assert validate_success(api.get_report_distribution(distribution["id"], CL_HEADERS))[
        "status"
    ] == "REQUESTED"


def test_a_distinct_recipient_at_the_ceiling_reports_the_limit(api):
    """PRD 3.8: "The engagement's ceiling is then enforced: the count of that engagement's
    distribution rows whose `status` is not `REVOKED` and not `DENIED` must be strictly
    less than `max_distribution_recipients`, else `ERR_DISTRIBUTION_LIMIT_EXCEEDED`."
    PRD 2.7: "**Distribution ceiling**, else `ERR_DISTRIBUTION_LIMIT_EXCEEDED` (409). This
    runs *after* the uniqueness check, so a duplicate recipient submitted while the
    engagement already sits at its ceiling reports the duplicate, not the ceiling."

    Design: Difficulty/priority_pair_validation_conflict/duplicate_recipient_constraint_beats_distribution_ceiling_fiscal
    """
    engagement, _ = build_ceiling_of_one()

    response = api.create_report_distribution(
        {
            "engagement_id": engagement["id"],
            "recipient_name": "Globex",
            "recipient_email": "soc@globex.example",
        },
        AE_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DISTRIBUTION_LIMIT_EXCEEDED.value, 409)

    _, meta = validate_paginated(
        api.list_report_distributions(AE_HEADERS, params={"engagement_id": engagement["id"]})
    )
    assert meta["total_count"] == 1, "Neither rejected request may be stored"


def build_bridged_report(articulated_cuec_count=0):
    """An issued SOC 1 report with a delivered distribution and one ISSUED bridge letter
    covering 2026-11-30 through 2027-01-31."""
    scenario = setup_delivered_report(
        client_name="Relecloud",
        report_type="SOC_1_TYPE_2",
        articulated_cuec_count=articulated_cuec_count,
    )
    letter = create_bridge_letter(
        scenario["engagement_id"], "2026-11-30T00:00:00.000Z", "2027-01-31T00:00:00.000Z"
    )
    scenario["bridge_letter"] = issue_bridge_letter(letter["id"])
    return scenario


def test_a_questionnaire_asked_on_the_letters_final_instant_is_bridged(api):
    """PRD 3.9: "The **second bucket is the bridge letter**. The candidate pool is the
    engagement's letters in `ISSUED` whose closed coverage window contains the supplied
    instant — that is, whose `coverage_start` is at or before it and whose own `as_of_date`
    is at or after it."
    PRD 3.9: "Candidates are ranked by their own `as_of_date` descending, so the letter
    reaching furthest forward wins, with ties broken by `created_at` ascending; the
    winner's identifier is recorded as `bridge_letter_id_used` and
    `deflected_by_bridge_count` absorbs the whole of `post_period_item_count`."
    PRD 3.9: "Whatever remains is the fourth bucket: `manual_response_count` is `item_count`
    less the three bucket counts. The `deflection_ratio` is exactly 0.0000 when `item_count`
    is 0, and otherwise `item_count` less `manual_response_count`, divided by `item_count`,
    rounded half up to four decimal places."

    Design: Difficulty/boundary_precision_check/bridge_letter_closed_interval_includes_as_of_date_endpoint
    """
    scenario = build_bridged_report(articulated_cuec_count=2)
    assert scenario["bridge_letter"]["status"] == "ISSUED"
    assert scenario["bridge_letter"]["coverage_days"] == 63
    assert read_engagement(scenario["engagement_id"])["covered_criteria_count_attestation"] == 1

    questionnaire = create_questionnaire(
        scenario["engagement_id"],
        scenario["distribution"]["id"],
        customer_name="Acme Corp Security",
        criteria_item_count=4,
        post_period_item_count=3,
        cuec_item_count=5,
    )
    deflected = validate_success(
        api.deflect_customer_questionnaire(
            questionnaire["id"], {"as_of_date": "2027-01-31T00:00:00.000Z"}, AE_HEADERS
        )
    )

    assert deflected["item_count"] == 12
    assert deflected["deflected_by_report_count"] == 1
    assert deflected["deflected_by_bridge_count"] == 3, (
        "The letter's own as_of_date is inside its closed window"
    )
    assert deflected["deflected_by_cuec_count"] == 2
    assert deflected["manual_response_count"] == 6
    assert deflected["deflection_ratio"] == 0.5000
    assert deflected["bridge_letter_id_used"] == scenario["bridge_letter"]["id"]
    assert deflected["status"] == "PARTIALLY_DEFLECTED"


def test_a_questionnaire_asked_a_day_past_the_letter_is_not_bridged(api):
    """PRD 3.9: "When the pool is empty the bucket absorbs 0 and `bridge_letter_id_used`
    stays null."
    PRD 3.9: "When `manual_response_count` is greater than 0 but strictly less than
    `item_count`, it moves `RECEIVED → PARTIALLY_DEFLECTED`."
    PRD 3.9: "The **third bucket is the articulated complementary user entity controls**:
    `deflected_by_cuec_count` is the smaller of `cuec_item_count` and the number of that
    engagement's statements whose `articulation_status` is `ARTICULATED`, with drafts and
    retired statements excluded."

    Design: Difficulty/boundary_precision_check/bridge_letter_closed_interval_includes_as_of_date_endpoint
    """
    scenario = build_bridged_report(articulated_cuec_count=2)
    questionnaire = create_questionnaire(
        scenario["engagement_id"],
        scenario["distribution"]["id"],
        customer_name="Acme Corp Procurement",
        criteria_item_count=4,
        post_period_item_count=3,
        cuec_item_count=5,
    )

    deflected = validate_success(
        api.deflect_customer_questionnaire(
            questionnaire["id"], {"as_of_date": "2027-02-01T00:00:00.000Z"}, AE_HEADERS
        )
    )
    assert deflected["deflected_by_bridge_count"] == 0, (
        "A single day past the letter's as_of_date leaves the candidate pool empty"
    )
    assert deflected["bridge_letter_id_used"] is None
    assert deflected["deflected_by_report_count"] == 1
    assert deflected["deflected_by_cuec_count"] == 2
    assert deflected["manual_response_count"] == 9
    assert deflected["deflection_ratio"] == 0.2500
    assert deflected["status"] == "PARTIALLY_DEFLECTED"


def build_three_letter_engagement():
    """An issued report with BL1 already ISSUED for 2026-11-30 to 2027-01-31, plus a
    touching draft BL2 and a one-day-later draft BL3."""
    scenario = build_bridged_report()
    scenario["touching"] = create_bridge_letter(
        scenario["engagement_id"], "2027-01-31T00:00:00.000Z", "2027-03-31T00:00:00.000Z"
    )
    scenario["clear"] = create_bridge_letter(
        scenario["engagement_id"], "2027-02-01T00:00:00.000Z", "2027-03-31T00:00:00.000Z"
    )
    return scenario


def test_two_letters_touching_at_a_single_instant_collide(api):
    """PRD 3.9: "And the letter's closed window must not intersect the closed window of any
    *other* letter of the same engagement in `ISSUED`; because both endpoints are inside
    each window, **two letters that merely touch at a single shared instant do collide** and
    are rejected with `ERR_BRIDGE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/bridge_letter_windows_on_an_engagement_are_closed_so_touching_collides
    """
    scenario = build_three_letter_engagement()

    response = api.issue_bridge_letter(scenario["touching"]["id"], AE_HEADERS)
    validate_error(response, ApiErrorId.ERR_BRIDGE_WINDOW_OVERLAP.value, 409)

    stored = validate_success(
        api.get_bridge_letter(scenario["touching"]["id"], AE_HEADERS)
    )
    assert stored["status"] == "DRAFT"
    assert stored["issued_at"] is None


def test_a_letter_starting_one_day_later_issues_cleanly(api):
    """PRD 3.9: "On success the letter moves `DRAFT → ISSUED`, stamping `issued_at` from the
    logical clock and `issued_by_user_id` from the header, and when
    `supersedes_bridge_letter_id` is non-null the named letter moves `ISSUED → SUPERSEDED`."
    PRD 3.9: "The coverage window is **closed**: both endpoints lie inside it, so
    `coverage_days` is the difference between `as_of_date` and `coverage_start` in seconds,
    divided by 86400, truncated downward to a whole number, and then increased by one — a
    single-instant letter whose `as_of_date` equals its `coverage_start` therefore has a
    `coverage_days` of 1."

    Design: Difficulty/resource_temporal_overlap/bridge_letter_windows_on_an_engagement_are_closed_so_touching_collides
    """
    scenario = build_three_letter_engagement()
    rejected = api.issue_bridge_letter(scenario["touching"]["id"], AE_HEADERS)
    assert rejected.status_code == 409

    issued = validate_success(api.issue_bridge_letter(scenario["clear"]["id"], AE_HEADERS))
    assert issued["status"] == "ISSUED"
    assert issued["coverage_days"] == 59

    assert validate_success(
        api.get_bridge_letter(scenario["bridge_letter"]["id"], AE_HEADERS)
    )["status"] == "ISSUED"

    _, meta = validate_paginated(
        api.list_bridge_letters(
            AE_HEADERS,
            params={"engagement_id": scenario["engagement_id"], "status": "ISSUED"},
        )
    )
    assert meta["total_count"] == 2
