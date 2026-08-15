"""Transfusion reactions, investigation forks, and the recall/look-back machine."""
from test_helpers import (
    ApiErrorId,
    conclude_reaction,
    create_recall_case_payload,
    get_issue,
    get_reaction,
    get_recall,
    get_success_data,
    get_unit,
    identify_recall,
    investigate_reaction,
    issue_all,
    list_wastage,
    make_donor_recall,
    make_issue,
    make_compatible_crossmatch,
    make_quality_officer_headers,
    make_stock,
    make_typed_patient,
    make_verified_order,
    notify_recall,
    quarantine_recall,
    receive_unit_descriptor,
    record_reaction_workup,
    report_reaction,
    setup_investigating_reaction,
    setup_order_with_reserved_units,
    setup_started_issue,
    setup_transfused_issue,
    validate_error,
    validate_paginated,
    validate_success,
    QO_1,
    TECH_A,
    api_client,
)


def _setup_two_septic_reactions(api):
    """Two transfusing issues on two donors, each with a SEPTIC/LIFE_THREATENING
    reaction investigated with identical workups."""
    stock = make_stock([
        receive_unit_descriptor("U-101", donor_id="D-A", lot_number="LOT-4"),
        receive_unit_descriptor("U-102", donor_id="D-B", lot_number="LOT-4"),
    ])
    patient, _ts = make_typed_patient(mrn="M-9012", full_name="Pat Twelve",
                                      date_of_birth="1990-07-07")
    reactions = []
    units = []
    for number in ("U-101", "U-102"):
        order = make_verified_order(patient["id"], product_type="RBC",
                                    units_requested=1)
        make_compatible_crossmatch(order["id"], stock["units"][number]["id"])
        issue = make_issue(order["id"], stock["units"][number]["id"])
        get_success_data(api.start_transfusion(issue["id"], TECH_A))
        reaction = report_reaction(issue["id"], "SEPTIC", "LIFE_THREATENING",
                                   symptoms="rigors, hypotension")
        investigate_reaction(reaction["id"])
        record_reaction_workup(reaction["id"])
        reactions.append(reaction)
        units.append(stock["units"][number])
    return stock, patient, reactions, units


class TestInvestigationFork:
    def test_confirmed_severe_reaction_auto_creates_recall(self, api):
        """PRD §3.7: "concluding `CONFIRMED` with a `reaction_type` of
        `HEMOLYTIC_ACUTE`, `TRALI`, or `SEPTIC` auto-creates a recall case scoped
        `DONOR` on the unit's `donor_id` with disposition `DESTRUCTION` and
        `auto_created` true, runs unit identification immediately so the case is
        born in `UNITS_IDENTIFIED` status, and links it back through the reaction's
        `linked_recall_case_id`."

        Design: Difficulty/non_linear_state_machine/reaction_investigation_fork_divergent_side_effects
        """
        _stock, _patient, reactions, units = _setup_two_septic_reactions(api)
        concluded = conclude_reaction(reactions[0]["id"], "CONFIRMED",
                                      final_classification="SEPTIC_CONFIRMED")
        assert concluded["status"] == "CONFIRMED"
        recall_id = concluded["linked_recall_case_id"]
        assert recall_id is not None

        recall = get_recall(recall_id)
        assert recall["status"] == "UNITS_IDENTIFIED", (
            "identification ran inside the conclude call"
        )
        assert recall["auto_created"] is True
        assert recall["scope_type"] == "DONOR"
        assert recall["disposition"] == "DESTRUCTION"
        assert recall["implicated_unit_count"] == 1
        assert get_unit(units[0]["id"])["status"] == "DISCARDED", (
            "the held unit is disposed of at conclusion"
        )

    def test_ruled_out_fork_creates_no_recall(self, api):
        """PRD §3.7: "A `RULED_OUT` conclusion creates no recall."
        PRD §3.7: "if the implicated unit sits in `QUARANTINED_HOLD` under
        `REACTION_PRECAUTION`, it moves to `DISCARDED` with a wastage record of
        reason `REACTION_INVESTIGATION` — a unit involved in a reported reaction is
        never restocked."

        Design: Difficulty/non_linear_state_machine/reaction_investigation_fork_divergent_side_effects
        """
        _stock, _patient, reactions, units = _setup_two_septic_reactions(api)
        conclude_reaction(reactions[0]["id"], "CONFIRMED",
                          final_classification="SEPTIC_CONFIRMED")
        ruled_out = conclude_reaction(reactions[1]["id"], "RULED_OUT")
        assert ruled_out["status"] == "RULED_OUT"
        assert ruled_out["linked_recall_case_id"] is None, (
            "same type and workup, divergent fork — no recall"
        )
        assert get_unit(units[0]["id"])["status"] == "DISCARDED"
        assert get_unit(units[1]["id"])["status"] == "DISCARDED"

        _data, meta = validate_paginated(api.list_wastage_records(
            QO_1, params={"reason": "REACTION_INVESTIGATION"}))
        assert meta["total_count"] == 2, "one investigation wastage record each"


class TestReactionCloseGate:
    def test_reaction_close_blocked_until_recall_notified(self, api):
        """PRD §3.7: "when `linked_recall_case_id` is set the linked recall must
        already stand in `NOTIFICATION_COMPLETE` or `CLOSED` — otherwise
        `ERR_RECALL_INCOMPLETE` (HTTP 409) holds the reaction open."

        Design: Difficulty/cross_entity_state_dependency/reaction_close_requires_recall_notifications
        """
        ctx = _setup_confirmed_severe_reaction(api)
        quarantine_recall(ctx["recall"]["id"])  # recall only QUARANTINE_COMPLETE
        resp = api.close_reaction(ctx["reaction"]["id"], QO_1)
        validate_error(resp, ApiErrorId.ERR_RECALL_INCOMPLETE)

    def test_reaction_closes_after_notifications_complete(self, api):
        """PRD §3.7: "recording a notification takes an `issue_record_id` that must
        reference an implicated unit and stand in `TRANSFUSED` or
        `TRANSFUSION_STOPPED` (`ERR_ISSUE_NOT_IMPLICATED`) and must not already be
        flagged (`ERR_ISSUE_ALREADY_NOTIFIED`); it sets the issue's
        `lookback_notified` true, increments `notifications_sent_count`, and leaves
        the case in `QUARANTINE_COMPLETE`."
        PRD §3.7: "When every implicated transfused issue has been notified,
        completing notifications advances the case to `NOTIFICATION_COMPLETE`"

        Design: Difficulty/cross_entity_state_dependency/reaction_close_requires_recall_notifications
        """
        ctx = _setup_confirmed_severe_reaction(api)
        recall = quarantine_recall(ctx["recall"]["id"])
        recall = notify_recall(recall["id"], ctx["issue"]["id"])
        assert recall["notifications_sent_count"] == 1
        assert get_issue(ctx["issue"]["id"])["lookback_notified"] is True

        recall = get_success_data(
            api.complete_recall_notifications(recall["id"], QO_1))
        assert recall["status"] == "NOTIFICATION_COMPLETE"
        closed = validate_success(api.close_reaction(ctx["reaction"]["id"], QO_1))
        assert closed["status"] == "CLOSED"


def _setup_confirmed_severe_reaction(api):
    """Started issue on a donor-D-C unit; SEPTIC reaction concluded CONFIRMED,
    which auto-creates and identifies the linked recall."""
    stock = make_stock([
        receive_unit_descriptor("U-901", donor_id="D-C", lot_number="LOT-9A"),
    ])
    patient, _ts = make_typed_patient(mrn="M-9033", full_name="Pat Thirtythree",
                                      date_of_birth="1970-01-01")
    order = make_verified_order(patient["id"], product_type="RBC",
                                units_requested=1)
    make_compatible_crossmatch(order["id"], stock["units"]["U-901"]["id"])
    issue = make_issue(order["id"], stock["units"]["U-901"]["id"])
    get_success_data(api_client.start_transfusion(issue["id"], TECH_A))
    reaction = report_reaction(issue["id"], "SEPTIC", "LIFE_THREATENING")
    investigate_reaction(reaction["id"])
    record_reaction_workup(reaction["id"], clerical_check_passed=True,
                           dat_result="POSITIVE", hemolysis_present=True)
    reaction = conclude_reaction(reaction["id"], "CONFIRMED",
                                 final_classification="SEPTIC_CONFIRMED")
    recall = get_recall(reaction["linked_recall_case_id"])
    return {"stock": stock, "patient": patient, "order": order, "issue": issue,
            "reaction": reaction, "recall": recall}


class TestReactionReportingGates:
    def test_reaction_report_on_unstarted_issue_rejected(self, api):
        """PRD §3.7: "A suspected reaction is reported by a `BloodBankTechnologist`
        against an `issue_record_id` whose issue stands in `TRANSFUSION_STARTED` or
        `TRANSFUSED` — any other status draws `ERR_ISSUE_NOT_REACTIONABLE`
        (HTTP 409)."

        Design: Corner/state_machines/reaction_report_on_unstarted_issue_rejected
        """
        ctx = setup_order_with_reserved_units_for_test()
        resp = api.create_transfusion_reaction(
            {"issue_record_id": ctx["issue"]["id"],
             "reaction_type": "ALLERGIC_MILD", "severity": "MILD"}, TECH_A)
        validate_error(resp, ApiErrorId.ERR_ISSUE_NOT_REACTIONABLE)
        _data, meta = validate_paginated(api.list_transfusion_reactions(
            TECH_A, params={"issue_record_id": ctx["issue"]["id"]}))
        assert meta["total_count"] == 0

    def test_reaction_conclude_without_workup_rejected(self, api):
        """PRD §3.7: "Concluding likewise requires `INVESTIGATING` and additionally
        demands a recorded workup — concluding with `workup_recorded_at` still null
        meets `ERR_REACTION_WORKUP_MISSING` (HTTP 409)."

        Design: Corner/state_machines/reaction_conclude_without_workup_rejected
        """
        ctx = setup_investigating_reaction(reaction_type="FEBRILE_NON_HEMOLYTIC",
                                           severity="MODERATE", mrn="M-2005",
                                           with_workup=False)
        resp = api.conclude_reaction(ctx["reaction"]["id"],
                                     {"conclusion": "RULED_OUT"}, QO_1)
        validate_error(resp, ApiErrorId.ERR_REACTION_WORKUP_MISSING)
        assert get_reaction(ctx["reaction"]["id"])["status"] == "INVESTIGATING"

    def test_sod_reaction_investigator_equals_reporter_rejected(self, api):
        """PRD §3.7: "Beginning it requires `REPORTED`
        (`ERR_REACTION_NOT_INVESTIGABLE`) and an investigator whose `X-User-ID`
        differs from `reported_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); the
        officer is stamped as `investigator_user_id` and the record moves to
        `INVESTIGATING`."

        Design: Corner/rbac/sod_reaction_investigator_equals_reporter_rejected
        """
        ctx = setup_started_issue(mrn="M-5004", unit_number="U-100")
        reaction = report_reaction(ctx["issue"]["id"], "ALLERGIC_MILD", "MILD")
        # The same human (tech-a) wearing the QualityOfficer role cannot
        # investigate their own report.
        resp = api.begin_investigation(
            reaction["id"], make_quality_officer_headers("tech-a"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        investigating = validate_success(api.begin_investigation(reaction["id"],
                                                                 QO_1))
        assert investigating["status"] == "INVESTIGATING"


def setup_order_with_reserved_units_for_test():
    """Issued (never started) standard unit — local alias for readability."""
    ctx = setup_order_with_reserved_units(mrn="M-2004", unit_numbers=["U-100"])
    issue_all(ctx)
    ctx["issue"] = ctx["issues"]["U-100"]
    return ctx


class TestRecallEdges:
    def test_recall_scope_invalid_returns_400(self, api):
        """PRD §3.7: "Scope fields must agree with the scope type — `DONOR`
        requires a `donor_id`, `LOT` requires a `lot_number`, `UNIT` requires a
        `unit_id`, and `implicated_since` is meaningful only for `DONOR` scope —
        with inconsistencies rejected as `ERR_RECALL_SCOPE_INVALID` (HTTP 400)."

        Design: Corner/entities/recall_scope_invalid_returns_400
        """
        resp = api.create_recall_case(
            {"scope_type": "DONOR", "reason": "missing donor id",
             "disposition": "DESTRUCTION"}, QO_1)
        validate_error(resp, ApiErrorId.ERR_RECALL_SCOPE_INVALID)

    def test_recall_void_after_quarantine_rejected(self, api):
        """PRD §3.7: "A false-alarm case may instead be voided from `OPEN` or
        `UNITS_IDENTIFIED` — crucially, before quarantine has executed — settling
        in `VOIDED`; from any later state the attempt draws
        `ERR_RECALL_NOT_VOIDABLE`."

        Design: Corner/state_machines/recall_void_after_quarantine_rejected
        """
        make_stock([receive_unit_descriptor("U-100", donor_id="D-X")],
                   release=False)
        recall = make_donor_recall("D-X", reason="deferral notice")
        recall = identify_recall(recall["id"])
        recall = quarantine_recall(recall["id"])
        assert recall["status"] == "QUARANTINE_COMPLETE"

        resp = api.void_recall(recall["id"], QO_1)
        validate_error(resp, ApiErrorId.ERR_RECALL_NOT_VOIDABLE)
        assert get_recall(recall["id"])["status"] == "QUARANTINE_COMPLETE"

    def test_error_issue_already_notified(self, api):
        """PRD §3.7: "recording a notification takes an `issue_record_id` that must
        reference an implicated unit and stand in `TRANSFUSED` or
        `TRANSFUSION_STOPPED` (`ERR_ISSUE_NOT_IMPLICATED`) and must not already be
        flagged (`ERR_ISSUE_ALREADY_NOTIFIED`)"

        Design: Corner/errors/error_issue_already_notified
        """
        ctx = setup_transfused_issue(mrn="M-4005", unit_number="U-100",
                                     donor_prefix="D-N")
        recall = make_donor_recall("D-N-0", reason="donor deferral")
        recall = identify_recall(recall["id"])
        recall = quarantine_recall(recall["id"])
        recall = notify_recall(recall["id"], ctx["issue"]["id"])
        assert recall["notifications_sent_count"] == 1

        resp = api.record_recall_notification(
            recall["id"], {"issue_record_id": ctx["issue"]["id"]}, QO_1)
        validate_error(resp, ApiErrorId.ERR_ISSUE_ALREADY_NOTIFIED)
        assert get_recall(recall["id"])["notifications_sent_count"] == 1

    def test_error_notifications_pending(self, api):
        """PRD §3.7: "When every implicated transfused issue has been notified,
        completing notifications advances the case to `NOTIFICATION_COMPLETE`;
        attempting it with any outstanding meets `ERR_NOTIFICATIONS_PENDING`
        (HTTP 409)."

        Design: Corner/errors/error_notifications_pending
        """
        setup_transfused_issue(mrn="M-4006", unit_number="U-100",
                               donor_prefix="D-N2")
        recall = make_donor_recall("D-N2-0", reason="donor deferral")
        recall = identify_recall(recall["id"])
        assert recall["transfused_issue_count"] == 1
        recall = quarantine_recall(recall["id"])

        resp = api.complete_recall_notifications(recall["id"], QO_1)
        validate_error(resp, ApiErrorId.ERR_NOTIFICATIONS_PENDING)
        assert get_recall(recall["id"])["status"] == "QUARANTINE_COMPLETE"
