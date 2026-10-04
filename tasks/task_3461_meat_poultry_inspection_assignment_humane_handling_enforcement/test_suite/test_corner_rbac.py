"""Breadth tests: role-based access control and segregation of duties."""

from test_helpers import (
    ApiErrorId,
    DISTRICT_MANAGER_HEADERS,
    LABEL_OFFICER_HEADERS,
    RECALL_COORDINATOR_HEADERS,
    factories as f,
    fixtures as fx,
    make_establishment_manager_headers,
    make_supervisory_reviewer_headers,
    validate_error,
    validate_paginated,
)


def test_rbac_establishment_manager_cannot_decide_grant(api):
    """PRD §2.1: "A request whose declared role is not permitted on the target
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403); the same error also
    reports a failed ownership check wherever a workflow pins `X-User-ID` to a
    specific resource's identifier."
    PRD §4: the `POST /inspection/grant-applications/{id}/decide` row
    authorizes DistrictManager alone ("Grant or deny the application").

    Design: Corner/rbac/rbac_establishment_manager_cannot_decide_grant
    """
    est = fx.create_establishment(api, name="RB1 Plant", species_classes=["CATTLE"])
    application = fx.create_grant_application(api, est["id"])
    fx.begin_grant_review(api, application["id"])
    fx.record_all_adequate(api, application["id"])

    # Even the applicant establishment itself may not decide.
    resp = api.decide_grant_application(
        application["id"], f.grant_decision_payload("GRANT"),
        make_establishment_manager_headers(est["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    rows, _meta = validate_paginated(api.list_grant_applications(est["id"], DISTRICT_MANAGER_HEADERS))
    assert len(rows) == 1 and rows[0]["status"] == "UNDER_REVIEW", "the denial of access changes nothing"


def test_rbac_label_officer_cannot_issue_nr(api):
    """PRD §2.1: "A request whose declared role is not permitted on the target
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403); the same error also
    reports a failed ownership check wherever a workflow pins `X-User-ID` to a
    specific resource's identifier."
    PRD §2.1: "`Inspector` is the field force: issuing noncompliance records,
    reporting humane handling events, collecting pathogen samples and recording
    their results, verifying shift coverage, and confirming their own
    assignments."

    Design: Corner/rbac/rbac_label_officer_cannot_issue_nr
    """
    est = fx.create_establishment(api, name="RB2 Plant", species_classes=["CATTLE"])

    resp = api.create_noncompliance_record(
        f.nr_payload(est["id"], est["id"], regulation_family="SANITATION",
                     description="label officer attempt"),
        LABEL_OFFICER_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    assert fx.list_nrs(api) == [], "the forbidden issuance stores nothing"


def test_rbac_recall_coordinator_cannot_determine_class(api):
    """PRD §2.1: "A request whose declared role is not permitted on the target
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403); the same error also
    reports a failed ownership check wherever a workflow pins `X-User-ID` to a
    specific resource's identifier."
    PRD §2.1: "`DistrictManager` runs the district office: grant application
    review and decisions, the enforcement action lifecycle, and recall class
    determination."

    Design: Corner/rbac/rbac_recall_coordinator_cannot_determine_class
    """
    est = fx.create_establishment(api, name="RB3 Plant", species_classes=["CATTLE"])
    # RecallCoordinator opens the case — every other recall endpoint is theirs.
    recall = fx.create_recall(api, est["id"], product_description="sausage lot 8",
                              quantity_lbs=250, reason_code="MISBRANDING")
    assert recall["status"] == "INITIATED"

    resp = api.determine_recall_class(
        recall["id"], f.determine_class_payload("CLASS_III"), RECALL_COORDINATOR_HEADERS
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    stored = fx.get_recall(api, recall["id"])
    assert stored["status"] == "INITIATED"
    assert stored["recall_class"] is None


def test_sod_reviewer_is_issuer_on_appeal_decide(api):
    """PRD §3.9: "Decisions belong to a `SupervisoryReviewer` who is not the
    issuing inspector. Deciding requires the appeal to be `FILED` and the
    underlying record to be `APPEALED` — a decision attempted when either has
    moved on is rejected with `ERR_INVALID_STATE` — and the caller's
    `X-User-ID` must differ from the record's `issued_by_inspector_id`,
    otherwise `ERR_SOD_REVIEWER_IS_ISSUER` (HTTP 403); per §2.7 the state check
    fires first, so a segregation violation on a stale appeal still reports the
    state error. Every decision stamps `decided_by_reviewer_id` with the
    caller's `X-User-ID` and `decided_at` with the logical clock, and the
    record moves with the outcome:"

    Design: Corner/rbac/sod_reviewer_is_issuer_on_appeal_decide
    """
    est = fx.create_establishment(api, name="RB4 Plant", species_classes=["CATTLE"])
    pair = fx.create_inspector_pair(api, ["CATTLE"])
    record = fx.issue_nr(api, est["id"], pair["issuer"]["id"], regulation_family="HUMANE",
                         description="nr under appeal")
    appeal = fx.file_appeal(api, record["id"], est["id"], grounds="grounds-text-dd")

    # The issuing inspector acting as the reviewer: segregation violation.
    own = api.decide_appeal(
        appeal["id"], f.appeal_decision_payload("AFFIRM"),
        make_supervisory_reviewer_headers(pair["issuer"]["id"]),
    )
    validate_error(own, ApiErrorId.ERR_SOD_REVIEWER_IS_ISSUER)

    # A different inspector identity in the reviewer capacity decides.
    decided = fx.decide_appeal(api, appeal["id"], pair["reviewer"]["id"], "AFFIRM")
    assert decided["status"] == "AFFIRMED"
    assert decided["decided_by_reviewer_id"] == pair["reviewer"]["id"]


def test_sod_reporter_cannot_confirm_own_humane_event(api):
    """PRD §3.5: "Only a `SupervisoryReviewer` may confirm or dismiss, and
    never their own report: the caller's `X-User-ID` must differ from the
    event's `reported_by_inspector_id`, otherwise `ERR_SOD_REVIEWER_IS_ISSUER`
    (HTTP 403). Both decisions require the event to be `REPORTED` (otherwise
    `ERR_INVALID_STATE`), and per §2.7 the state check is evaluated before the
    segregation check, so a decision attempted on an already-decided event
    reports the state error."

    Design: Corner/rbac/sod_reporter_cannot_confirm_own_humane_event
    """
    est = fx.create_establishment(api, name="RB5 Plant", species_classes=["CATTLE"])
    pair = fx.create_inspector_pair(api, ["CATTLE"])
    event = fx.report_humane_event(
        api, est["id"], pair["issuer"]["id"], species="CATTLE", severity="NON_EGREGIOUS",
        description="prod usage observation",
    )

    own = api.confirm_humane_event(
        event["id"], make_supervisory_reviewer_headers(pair["issuer"]["id"])
    )
    validate_error(own, ApiErrorId.ERR_SOD_REVIEWER_IS_ISSUER)

    confirmed = fx.confirm_humane_event(api, event["id"], pair["reviewer"]["id"])
    assert confirmed["status"] == "CONFIRMED"
