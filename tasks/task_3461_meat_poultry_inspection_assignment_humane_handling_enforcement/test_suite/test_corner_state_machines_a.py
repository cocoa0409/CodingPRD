"""Breadth tests: state machines — grant lifecycle, record responses, and the
recall classification cycle."""

from test_helpers import (
    ApiErrorId,
    DISTRICT_MANAGER_HEADERS,
    assert_grant_application,
    assert_recall,
    factories as f,
    fixtures as fx,
    make_establishment_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_grant_decide_with_deficient_finding_blocked(api):
    """PRD §3.1: "A grant additionally requires all three findings to be
    `ADEQUATE`; if any finding is still `PENDING` or has been recorded
    `DEFICIENT`, the grant is rejected with `ERR_GRANT_DECISION_BLOCKED` (HTTP
    409)."

    Design: Corner/state_machines/grant_decide_with_deficient_finding_blocked
    """
    est = fx.create_establishment(api, name="SM1 Plant", species_classes=["CATTLE"])
    application = fx.create_grant_application(api, est["id"])
    fx.begin_grant_review(api, application["id"])
    fx.record_adequacy(api, application["id"], "FACILITY", "ADEQUATE")
    fx.record_adequacy(api, application["id"], "SANITATION", "ADEQUATE")
    fx.record_adequacy(api, application["id"], "HACCP", "DEFICIENT")

    blocked = api.decide_grant_application(
        application["id"], f.grant_decision_payload("GRANT"), DISTRICT_MANAGER_HEADERS
    )
    validate_error(blocked, ApiErrorId.ERR_GRANT_DECISION_BLOCKED)

    rows, _meta = validate_paginated(
        api.list_grant_applications(est["id"], DISTRICT_MANAGER_HEADERS)
    )
    assert len(rows) == 1 and rows[0]["status"] == "UNDER_REVIEW", (
        "the blocked grant leaves the application UNDER_REVIEW"
    )

    denied = api.decide_grant_application(
        application["id"], f.grant_decision_payload("DENY"), DISTRICT_MANAGER_HEADERS
    )
    denied_data = validate_success(denied, 200)
    assert denied_data["status"] == "DENIED", "the block is grant-specific, not a freeze"
    assert denied_data["decided_at"] is not None


def test_grant_resubmit_cycle_resets_findings(api):
    """PRD §3.1: "The `EstablishmentManager` may resubmit a `DENIED`
    application with refreshed `facility_doc_ref`, `sanitation_plan_ref`, and
    `haccp_plan_ref` values; the same ownership pinning applies (`X-User-ID`
    must equal the application's `establishment_id`, else `ERR_FORBIDDEN`), and
    resubmission from any status other than `DENIED` is rejected with
    `ERR_INVALID_STATE`. Resubmission returns the application to `SUBMITTED`,
    increments `revision_count` by 1, resets all three findings to `PENDING`,
    and replaces the document references with the payload's."

    Design: Corner/state_machines/grant_resubmit_cycle_resets_findings
    """
    est = fx.create_establishment(api, name="SM2 Plant", species_classes=["CATTLE"])
    application = fx.create_grant_application(api, est["id"])
    fx.begin_grant_review(api, application["id"])
    fx.record_adequacy(api, application["id"], "SANITATION", "DEFICIENT")
    fx.decide_grant(api, application["id"], "DENY")

    resp = api.resubmit_grant_application(
        application["id"],
        f.grant_resubmit_payload(
            facility_doc_ref="doc-fac-2", sanitation_plan_ref="doc-san-2", haccp_plan_ref="doc-hac-2"
        ),
        make_establishment_manager_headers(est["id"]),
    )

    data = validate_success(resp, 200)
    assert_grant_application(data)
    assert data["status"] == "SUBMITTED"
    assert data["revision_count"] == 1
    assert data["facility_finding"] == "PENDING"
    assert data["sanitation_finding"] == "PENDING"
    assert data["haccp_finding"] == "PENDING"
    assert data["sanitation_plan_ref"] == "doc-san-2"


def test_grant_double_decide_rejected(api):
    """PRD §3.1: "The decision call takes a `decision` of `GRANT` or `DENY`.
    Both require the application to be `UNDER_REVIEW` (otherwise
    `ERR_INVALID_STATE`, reported before any findings check, since state
    legality outranks business rules in the §2.7 pipeline)."

    Design: Corner/state_machines/grant_double_decide_rejected
    """
    est = fx.create_establishment(api, name="SM3 Plant", species_classes=["CATTLE"])
    application = fx.create_grant_application(api, est["id"])
    fx.begin_grant_review(api, application["id"])
    fx.record_all_adequate(api, application["id"])
    granted = fx.decide_grant(api, application["id"], "GRANT")
    assert granted["status"] == "GRANTED"

    second = api.decide_grant_application(
        application["id"], f.grant_decision_payload("DENY"), DISTRICT_MANAGER_HEADERS
    )
    validate_error(second, ApiErrorId.ERR_INVALID_STATE)

    rows, _meta = validate_paginated(api.list_grant_applications(est["id"], DISTRICT_MANAGER_HEADERS))
    assert len(rows) == 1 and rows[0]["status"] == "GRANTED", "the terminal decision stands"
    est_after = fx.get_establishment(api, est["id"])
    assert est_after["grant_status"] == "GRANTED" and est_after["inspection_status"] == "ACTIVE"


def test_nr_respond_twice_rejected(api):
    """PRD §3.3: "The establishment answers through its `EstablishmentManager`:
    responding moves an `OPEN` record to `RESPONSE_SUBMITTED` and stores the
    supplied `response_text`. Responding is ownership-pinned — `X-User-ID` must
    equal the record's `establishment_id`, else `ERR_FORBIDDEN` — and is
    defined only from `OPEN`, so a response to an already-answered record is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/nr_respond_twice_rejected
    """
    est = fx.create_establishment(api, name="SM4 Plant", species_classes=["CATTLE"])
    inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])
    record = fx.issue_nr(api, est["id"], inspector["id"], regulation_family="HACCP",
                         description="ccp deviation")

    first = fx.respond_to_nr(api, record["id"], est["id"], "corrective action taken")
    assert first["status"] == "RESPONSE_SUBMITTED"

    second = api.respond_to_nr(
        record["id"],
        f.nr_response_payload("second response attempt"),
        make_establishment_manager_headers(est["id"]),
    )
    validate_error(second, ApiErrorId.ERR_INVALID_STATE)

    stored = fx.get_nr(api, record["id"])
    assert stored["status"] == "RESPONSE_SUBMITTED"
    assert stored["response_text"] == "corrective action taken", "first answer is unchanged"


def test_recall_determine_class_twice_rejected(api):
    """PRD §3.8: "Determining the class of a `CLOSED_INEFFECTIVE` recall — the
    only statuses from which classification is defined are `INITIATED` and
    `CLOSED_INEFFECTIVE`, otherwise `ERR_INVALID_STATE` — replaces the
    `recall_class`, recomputes `required_min_checks` and
    `required_effectiveness_ratio` for the new class, returns the recall to
    `CLASS_DETERMINED`, and resets the effectiveness evidence:
    `checks_performed` and `checks_effective` return to 0 and
    `effectiveness_ratio` to null, so the new classification is monitored on
    fresh evidence."

    Design: Corner/state_machines/recall_determine_class_twice_rejected
    """
    est = fx.create_establishment(api, name="SM5 Plant", species_classes=["CATTLE"])
    recall = fx.create_class_determined_recall(
        api, est["id"], "CLASS_II", product_description="franks lot 3", quantity_lbs=500,
        reason_code="MISBRANDING",
    )
    assert recall["status"] == "CLASS_DETERMINED"

    resp = api.determine_recall_class(
        recall["id"], f.determine_class_payload("CLASS_I"), DISTRICT_MANAGER_HEADERS
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    stored = fx.get_recall(api, recall["id"])
    assert stored["recall_class"] == "CLASS_II", "the first classification stands"
    assert stored["status"] == "CLASS_DETERMINED"
    assert stored["required_min_checks"] == 5
    assert stored["required_effectiveness_ratio"] == 0.80


def test_recall_reclassification_cycle_resets_counters(api):
    """PRD §3.8: "Determining the class of a `CLOSED_INEFFECTIVE` recall — the
    only statuses from which classification is defined are `INITIATED` and
    `CLOSED_INEFFECTIVE`, otherwise `ERR_INVALID_STATE` — replaces the
    `recall_class`, recomputes `required_min_checks` and
    `required_effectiveness_ratio` for the new class, returns the recall to
    `CLASS_DETERMINED`, and resets the effectiveness evidence:
    `checks_performed` and `checks_effective` return to 0 and
    `effectiveness_ratio` to null, so the new classification is monitored on
    fresh evidence."

    Design: Corner/state_machines/recall_reclassification_cycle_resets_counters
    """
    est = fx.create_establishment(api, name="SM6 Plant", species_classes=["CATTLE"])
    # CLASS_III (min 4 checks, ratio 0.75) with 2 EFFECTIVE + 2 INEFFECTIVE
    # -> ratio 0.50 < 0.75 -> CLOSED_INEFFECTIVE.
    recall = fx.create_closed_recall(
        api, est["id"], "CLASS_III",
        ["EFFECTIVE", "EFFECTIVE", "INEFFECTIVE", "INEFFECTIVE"],
        product_description="trim lot 11", quantity_lbs=300,
    )
    assert recall["status"] == "CLOSED_INEFFECTIVE", (
        f"0.50 < 0.75 closes ineffective, got {recall['status']}"
    )

    resp = api.determine_recall_class(
        recall["id"], f.determine_class_payload("CLASS_I"), DISTRICT_MANAGER_HEADERS
    )
    data = validate_success(resp, 200)

    assert_recall(data)
    assert data["status"] == "CLASS_DETERMINED"
    assert data["recall_class"] == "CLASS_I"
    assert data["required_min_checks"] == 10
    assert data["required_effectiveness_ratio"] == 0.95
    assert data["checks_performed"] == 0, "evidence reset"
    assert data["checks_effective"] == 0
    assert data["effectiveness_ratio"] is None
