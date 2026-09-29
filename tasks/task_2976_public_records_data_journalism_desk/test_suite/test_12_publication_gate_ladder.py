"""The publication gate ladder of PRD S3.9, rung by rung.

Publication is the last act of an investigation and the longest gate ladder in
the system: the desk's security posture, the clearance requirement it implies,
the disclosure-risk ceiling, and the three right-of-reply gates (notice pending,
notice sufficiency, attempt sufficiency) all answer in the ascending order of
PRD S2.11, and the first one violated is the whole answer.

These tests drive the logical clock deliberately, because two of the rungs are
temporal to millisecond resolution and one of them fires a state transition on
a third entity at the very instant it is satisfied.
"""

import pytest

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_ANALYSIS_NOT_READY,
    ERR_DESK_LOCKDOWN,
    ERR_DISCLOSURE_RISK_TOO_HIGH,
    ERR_INSUFFICIENT_ATTEMPTS,
    ERR_INSUFFICIENT_NOTICE,
    ERR_INVALID_INVESTIGATION_STATE,
    ERR_INVALID_SUBJECT_STATE,
    ERR_INVESTIGATION_NOT_CLEARED,
    ERR_SUBJECT_NOTICE_PENDING,
)
from test_helpers.assertions import (
    assert_field_absent_or_null,
    assert_instant_equals,
    assert_ledger_columns,
    assert_partition_counts,
    validate_error,
    validate_ok,
    validate_unpaginated,
)
from test_helpers.test_users import (
    coordinator_headers,
    editor_headers,
    expert_reviewer_headers,
    legal_headers,
    reporter_headers,
)

# --------------------------------------------------------------------------
# Private helpers and literals (this file only)
# --------------------------------------------------------------------------

# Two unsuppressed columns at risks 4 and 2 over 500 records: AGGREGATE_MAX 40,
# comfortably under the publish ceiling of 60 (PRD S3.9).
_CLOSURE_SPECS = [
    {
        "field_name": "closure_district",
        "reidentification_risk": 4,
        "null_rate_pct": 0.5,
    },
    {
        "field_name": "closure_reason",
        "reidentification_risk": 2,
        "null_rate_pct": 0.0,
    },
]

# Risks 8 and 3 over 500 records: AGGREGATE_MAX 80, over the ceiling (PRD S3.9).
_INSPECTION_SPECS = [
    {"field_name": "tenant_zip", "reidentification_risk": 8, "null_rate_pct": 1.5},
    {
        "field_name": "violation_class",
        "reidentification_risk": 3,
        "null_rate_pct": 0.0,
    },
]

_CLOSURES_METHODOLOGY = "methods/closures-2025.md"
_INSPECTIONS_METHODOLOGY = "methods/inspections-2025.md"
_METHODOLOGY_V1 = "methodology-v1"

_APPEAL_CLOCK = "2026-08-24T09:00:00Z"
_SESSION_START = "2026-09-10T09:00:00Z"
_SESSION_END = "2026-09-10T11:00:00Z"
_NOTICE_MINUS_ONE_MS = "2026-08-23T08:59:59.999Z"
_NOTICE_PLUS_ONE_MS = "2026-08-23T09:00:00.001Z"
_FORTY_EIGHT_HOURS_IN = "2026-08-22T09:00:00Z"
_COARSEN_BUCKET = "COARSEN_BUCKET"


def _publish(api, investigation_id, methodology_doc_ref, release_dataset_id=F.OMIT):
    """Attempt the publication of PRD S3.9, naming a release dataset only if given."""
    return api.publish_investigation(
        investigation_id,
        F.publication_payload(
            release_dataset_id=release_dataset_id,
            methodology_doc_ref=methodology_doc_ref,
        ),
        editor_headers(),
    )


def _fields_by_name(api, dataset_id):
    """The documented columns of a dataset, keyed by ``field_name``."""
    rows = validate_unpaginated(
        api.list_field_definitions(dataset_id, reporter_headers())
    )
    return {row["field_name"]: row for row in rows}


def _read_session(api, session_id):
    """Read one supervised reading session."""
    return validate_ok(api.get_enclave_session(session_id, legal_headers()))


def _posture_bundle(api):
    """An investigation whose desk is dragged to ``RESTRICTED`` by a sibling request.

    The investigation itself is untouched by that appeal cascade: PRD S3.5
    reaches investigations only through the appealed request's own datasets, and
    the appealed request has none.
    """
    X.set_clock(api, C.STD_CLOCK)
    bundle = X.locked_investigation(
        api,
        C.MODE_AGGREGATES_ONLY,
        subject_count=1,
        record_count=500,
        field_specs=_CLOSURE_SPECS,
    )
    subject = bundle["subjects"][0]
    X.set_clock(api, X.NOTICE_SENT_AT)
    X.record_attempt(api, subject["id"], channel="EMAIL")
    X.record_attempt(api, subject["id"], channel="PHONE")
    validate_ok(
        api.record_subject_response(
            subject["id"], F.subject_response_payload(), coordinator_headers()
        )
    )
    enclave = X.create_enclave(api)
    session = X.book_session(
        api,
        enclave["id"],
        bundle["dataset"]["id"],
        start_at=_SESSION_START,
        end_at=_SESSION_END,
        document_count=4,
    )
    X.set_clock(api, _APPEAL_CLOCK)
    desk, _appealed = X.drive_desk_to_restricted(
        api, bundle["desk"]["id"], bundle["agency"]["id"]
    )
    bundle["subject"] = X.read_subject_record(api, subject["id"])
    bundle["enclave"] = enclave
    bundle["session"] = session
    bundle["desk"] = desk
    bundle["investigation"] = X.read_investigation(api, bundle["investigation"]["id"])
    return bundle


class TestPublicationGatedOnDeskSecurityPosture:
    """One investigation, three refusals, driven entirely by a sibling desk row."""

    def test_a_sibling_appeal_denial_restricts_the_desk_without_touching_the_investigation(
        self, api
    ):
        """The appealed request owns no datasets, so no hold cascade reaches here.

        PRD S3.5: "**Hop three:** because the request entered
        `LITIGATION_AUTHORIZED`, the desk's `litigation_exposure_count`
        increments by 1, its `open_request_count` decrements by 1, and
        `security_posture` is recomputed — landing on `RESTRICTED` unless a
        source-exposure incident has already forced `LOCKDOWN`."

        Design: Difficulty/cross_entity_state_dependency/investigation_publication_gated_on_desk_security_posture
        """
        bundle = _posture_bundle(api)

        desk = bundle["desk"]
        assert desk["security_posture"] == C.POSTURE_RESTRICTED, (
            f"security_posture: expected RESTRICTED, got {desk['security_posture']!r}"
        )
        assert desk["litigation_exposure_count"] == 1, (
            "litigation_exposure_count: expected 1 after the denied appeal, got "
            f"{desk['litigation_exposure_count']}"
        )
        assert desk["source_exposure_incident_count"] == 0, (
            "source_exposure_incident_count: expected 0, got "
            f"{desk['source_exposure_incident_count']}"
        )
        assert bundle["investigation"]["status"] == C.INV_FINDINGS_LOCKED, (
            "status: the appeal cascade must not reach an investigation built on a "
            f"different request, got {bundle['investigation']['status']!r}"
        )

    def test_a_restricted_desk_refuses_a_merely_locked_investigation(self, api):
        """The risk score and the answered subject would both pass; the posture does not.

        PRD S2.9: "Under `RESTRICTED`, publication additionally requires that the
        investigation has already reached `CLEARED`; an investigation that is
        merely `FINDINGS_LOCKED` is refused with `ERR_INVESTIGATION_NOT_CLEARED`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/investigation_publication_gated_on_desk_security_posture
        """
        bundle = _posture_bundle(api)
        investigation_id = bundle["investigation"]["id"]

        validate_error(
            _publish(
                api,
                investigation_id,
                _CLOSURES_METHODOLOGY,
                bundle["dataset"]["id"],
            ),
            ERR_INVESTIGATION_NOT_CLEARED,
        )

        after = X.read_investigation(api, investigation_id)
        assert after["status"] == C.INV_FINDINGS_LOCKED, (
            f"status: expected FINDINGS_LOCKED after the refusal, got {after['status']!r}"
        )
        assert_field_absent_or_null(after, "published_at", "investigation")
        assert_field_absent_or_null(after, "disclosure_risk_score", "investigation")

    def test_a_source_exposure_incident_locks_down_the_desk_and_cascades_twice(
        self, api
    ):
        """One incident holds the investigation and cancels the booked reading session.

        PRD S3.1: "That posture change cascades in two hops: first, every
        investigation belonging to this desk whose status is `ANALYSIS`,
        `FINDINGS_LOCKED` or `CLEARED` moves to `HOLD_LEGAL_REVIEW` with
        `hold_reason_code` set to `SOURCE_EXPOSURE_INCIDENT` ... second, every
        enclave session still in `BOOKED` whose dataset belongs to one of this
        desk's investigations moves to `CANCELLED` with
        `cancellation_reason_code` set to `DESK_LOCKDOWN`".

        Design: Difficulty/cross_entity_state_dependency/investigation_publication_gated_on_desk_security_posture
        """
        bundle = _posture_bundle(api)

        X.drive_desk_to_lockdown(
            api, bundle["desk"]["id"], severity_code="CRITICAL"
        )

        desk = X.read_desk(api, bundle["desk"]["id"])
        assert desk["source_exposure_incident_count"] == 1, (
            "source_exposure_incident_count: expected 1, got "
            f"{desk['source_exposure_incident_count']}"
        )
        assert desk["security_posture"] == C.POSTURE_LOCKDOWN, (
            f"security_posture: expected LOCKDOWN, got {desk['security_posture']!r}"
        )
        investigation = X.read_investigation(api, bundle["investigation"]["id"])
        assert investigation["status"] == C.INV_HOLD_LEGAL_REVIEW, (
            f"status: expected HOLD_LEGAL_REVIEW, got {investigation['status']!r}"
        )
        assert (
            investigation["hold_reason_code"]
            == C.HOLD_REASON_SOURCE_EXPOSURE_INCIDENT
        ), (
            "hold_reason_code: expected SOURCE_EXPOSURE_INCIDENT, got "
            f"{investigation['hold_reason_code']!r}"
        )
        session = _read_session(api, bundle["session"]["id"])
        assert session["status"] == C.SESSION_CANCELLED, (
            f"session status: expected CANCELLED, got {session['status']!r}"
        )
        assert session["cancellation_reason_code"] == C.CANCEL_REASON_DESK_LOCKDOWN, (
            "cancellation_reason_code: expected DESK_LOCKDOWN, got "
            f"{session['cancellation_reason_code']!r}"
        )

    def test_legal_clearance_is_refused_under_lockdown(self, api):
        """The hold-to-cleared transition is declared, but the posture blocks it.

        PRD S2.9: "Under `LOCKDOWN`, every publication, every legal clearance and
        every enclave-session booking is refused with `ERR_DESK_LOCKDOWN` (HTTP
        409)."

        Design: Difficulty/cross_entity_state_dependency/investigation_publication_gated_on_desk_security_posture
        """
        bundle = _posture_bundle(api)
        investigation_id = bundle["investigation"]["id"]
        X.drive_desk_to_lockdown(
            api, bundle["desk"]["id"], severity_code="CRITICAL"
        )

        validate_error(
            api.grant_legal_clearance(
                investigation_id, F.legal_clearance_payload(), legal_headers()
            ),
            ERR_DESK_LOCKDOWN,
        )

        after = X.read_investigation(api, investigation_id)
        assert after["status"] == C.INV_HOLD_LEGAL_REVIEW, (
            f"status: expected HOLD_LEGAL_REVIEW, got {after['status']!r}"
        )
        assert_field_absent_or_null(after, "legal_clearance_at", "investigation")

    def test_publication_from_a_legal_hold_fails_the_state_gate_first(self, api):
        """The hold moved the investigation out of every publishable status.

        PRD S3.9: "From any other status it is
        `ERR_INVALID_INVESTIGATION_STATE`."

        Design: Difficulty/cross_entity_state_dependency/investigation_publication_gated_on_desk_security_posture
        """
        bundle = _posture_bundle(api)
        investigation_id = bundle["investigation"]["id"]
        X.drive_desk_to_lockdown(
            api, bundle["desk"]["id"], severity_code="CRITICAL"
        )

        validate_error(
            _publish(
                api,
                investigation_id,
                _CLOSURES_METHODOLOGY,
                bundle["dataset"]["id"],
            ),
            ERR_INVALID_INVESTIGATION_STATE,
        )

        after = X.read_investigation(api, investigation_id)
        assert_field_absent_or_null(after, "published_at", "investigation")
        desk = X.read_desk(api, bundle["desk"]["id"])
        assert_ledger_columns(desk, 500000, 495500, 0, 4500)


def _notice_bundle(api, publish_at):
    """A publishable ``AGGREGATES_ONLY`` investigation with the clock parked deliberately.

    Notice is sent at ``2026-08-20T09:00:00Z`` with two documented attempts, so
    ``response_deadline_at`` lands at ``2026-08-23T09:00:00Z``; the clock is then
    moved to ``publish_at`` to sit on whichever side of the 72-hour boundary the
    test needs.
    """
    return X.publishable_investigation(
        api,
        C.MODE_AGGREGATES_ONLY,
        record_count=500,
        field_specs=_CLOSURE_SPECS,
        subject_count=1,
        notice_at=X.NOTICE_SENT_AT,
        publish_at=publish_at,
    )


class TestPublicationNoticeAtExactlySeventyTwoHours:
    """The notice gate is inclusive at 72.000 hours, to millisecond resolution."""

    def test_the_first_attempt_stamps_the_deadline_exactly_seventy_two_hours_out(
        self, api
    ):
        """The deadline is derived from the notice instant, not from the second attempt.

        PRD S3.9: "The **first** attempt is special: it drives `NOTICE_ELIGIBLE →
        NOTICE_SENT`, stamps `notice_sent_at` from the logical clock, and stamps
        `response_deadline_at` at exactly 72 hours after `notice_sent_at`."

        Design: Difficulty/boundary_precision_check/publication_notice_at_exactly_seventy_two_hours
        """
        bundle = _notice_bundle(api, _NOTICE_MINUS_ONE_MS)

        subject = bundle["subjects"][0]

        assert_instant_equals(
            subject["notice_sent_at"], X.NOTICE_SENT_AT, label="notice_sent_at"
        )
        assert_instant_equals(
            subject["response_deadline_at"],
            X.NOTICE_PLUS_72H,
            label="response_deadline_at",
        )
        assert subject["attempt_count"] == 2, (
            f"attempt_count: expected 2, got {subject['attempt_count']}"
        )

    def test_one_millisecond_short_of_the_boundary_is_refused(self, api):
        """71.99999972 hours is fewer than 72, and the lapse must not fire early.

        PRD S3.9: "For every notified record, the elapsed notice is the exact
        difference in hours between the logical clock and `notice_sent_at`,
        measured to millisecond resolution: fewer than 72 hours yields
        `ERR_INSUFFICIENT_NOTICE`".

        Design: Difficulty/boundary_precision_check/publication_notice_at_exactly_seventy_two_hours
        """
        bundle = _notice_bundle(api, _NOTICE_MINUS_ONE_MS)
        investigation_id = bundle["investigation"]["id"]

        validate_error(
            _publish(
                api,
                investigation_id,
                _CLOSURES_METHODOLOGY,
                bundle["dataset"]["id"],
            ),
            ERR_INSUFFICIENT_NOTICE,
        )

        subject = X.read_subject_record(api, bundle["subjects"][0]["id"])
        assert subject["status"] == C.SUBJ_NOTICE_SENT, (
            "subject status: the NO_RESPONSE pre-step must not fire one millisecond "
            f"early, got {subject['status']!r}"
        )
        after = X.read_investigation(api, investigation_id)
        assert after["status"] == C.INV_FINDINGS_LOCKED, (
            f"status: expected FINDINGS_LOCKED, got {after['status']!r}"
        )
        assert_field_absent_or_null(after, "published_at", "investigation")

    def test_one_second_short_of_the_boundary_is_refused(self, api):
        """The PRD's own just-under instant refuses on the same rung.

        PRD S3.9: "with `notice_sent_at` at `2026-08-20T09:00:00Z`, a logical
        clock of `2026-08-23T08:59:59Z` gives just under 72 hours and yields
        `ERR_INSUFFICIENT_NOTICE`".

        Design: Difficulty/boundary_precision_check/publication_notice_at_exactly_seventy_two_hours
        """
        bundle = _notice_bundle(api, X.NOTICE_JUST_UNDER_72H)

        validate_error(
            _publish(
                api,
                bundle["investigation"]["id"],
                _CLOSURES_METHODOLOGY,
                bundle["dataset"]["id"],
            ),
            ERR_INSUFFICIENT_NOTICE,
        )

        subject = X.read_subject_record(api, bundle["subjects"][0]["id"])
        assert subject["status"] == C.SUBJ_NOTICE_SENT, (
            f"subject status: expected NOTICE_SENT, got {subject['status']!r}"
        )

    def test_exactly_seventy_two_hours_publishes_and_lapses_the_subject_at_once(
        self, api
    ):
        """The refused investigation releases as soon as the clock reaches the boundary.

        PRD S3.9: "`2026-08-23T09:00:00Z` gives exactly 72.000 hours and passes —
        and that same instant satisfies the `response_deadline_at` comparison, so
        a still-`NOTICE_SENT` record lapses to `NO_RESPONSE` in the pre-step of
        that very attempt."

        Design: Difficulty/boundary_precision_check/publication_notice_at_exactly_seventy_two_hours
        """
        bundle = _notice_bundle(api, _NOTICE_MINUS_ONE_MS)
        investigation_id = bundle["investigation"]["id"]
        dataset_id = bundle["dataset"]["id"]
        validate_error(
            _publish(api, investigation_id, _CLOSURES_METHODOLOGY, dataset_id),
            ERR_INSUFFICIENT_NOTICE,
        )

        X.set_clock(api, X.NOTICE_PLUS_72H)
        published = validate_ok(
            _publish(api, investigation_id, _CLOSURES_METHODOLOGY, dataset_id)
        )

        assert published["status"] == C.INV_PUBLISHED, (
            f"status: expected PUBLISHED at exactly 72 hours, got {published['status']!r}"
        )
        assert_instant_equals(
            published["published_at"], X.NOTICE_PLUS_72H, label="published_at"
        )
        assert published["disclosure_risk_score"] == 40, (
            "disclosure_risk_score: risks 4 and 2 give an aggregate of 40, got "
            f"{published['disclosure_risk_score']}"
        )
        assert published["applicable_risk_variant"] == C.VARIANT_AGGREGATE_MAX, (
            "applicable_risk_variant: expected AGGREGATE_MAX, got "
            f"{published['applicable_risk_variant']!r}"
        )
        assert published["release_dataset_id"] == dataset_id, (
            "release_dataset_id: expected the published dataset, got "
            f"{published['release_dataset_id']!r}"
        )
        assert published["methodology_doc_ref"] == _CLOSURES_METHODOLOGY, (
            "methodology_doc_ref: expected the submitted write-up reference, got "
            f"{published['methodology_doc_ref']!r}"
        )
        subject = X.read_subject_record(api, bundle["subjects"][0]["id"])
        assert subject["status"] == C.SUBJ_NO_RESPONSE, (
            "subject status: the publication pre-step must lapse the record at the "
            f"same instant, got {subject['status']!r}"
        )

    def test_one_millisecond_past_the_boundary_also_publishes(self, api):
        """Past the inclusive boundary nothing changes: the release still goes out.

        PRD S3.9: "The comparison at 72 hours is inclusive".

        Design: Difficulty/boundary_precision_check/publication_notice_at_exactly_seventy_two_hours
        """
        bundle = _notice_bundle(api, _NOTICE_PLUS_ONE_MS)

        published = validate_ok(
            _publish(
                api,
                bundle["investigation"]["id"],
                _CLOSURES_METHODOLOGY,
                bundle["dataset"]["id"],
            )
        )

        assert published["status"] == C.INV_PUBLISHED, (
            f"status: expected PUBLISHED, got {published['status']!r}"
        )
        assert_instant_equals(
            published["published_at"], _NOTICE_PLUS_ONE_MS, label="published_at"
        )
        subject = X.read_subject_record(api, bundle["subjects"][0]["id"])
        assert subject["status"] == C.SUBJ_NO_RESPONSE, (
            "subject status: the deadline is past, so the pre-step lapses the record; "
            f"got {subject['status']!r}"
        )


def _priority_bundle(api):
    """A locked investigation that violates the risk ceiling AND the notice clock.

    Its release dataset scores 80 under ``AGGREGATE_MAX`` while only 48 of the
    required 72 notice hours have elapsed, so two rungs are breached at once.
    """
    return X.publishable_investigation(
        api,
        C.MODE_AGGREGATES_ONLY,
        record_count=500,
        field_specs=_INSPECTION_SPECS,
        subject_count=1,
        notice_at=X.NOTICE_SENT_AT,
        publish_at=_FORTY_EIGHT_HOURS_IN,
    )


class TestDisclosureRiskBeatsInsufficientNotice:
    """Two rungs breached by one call: the lower-numbered rung is the answer."""

    def test_the_risk_ceiling_answers_before_the_notice_clock(self, api):
        """80 over the ceiling is reported even though notice is also short.

        PRD S2.11: "20. The applicable disclosure risk score must not exceed 60 —
        otherwise `ERR_DISCLOSURE_RISK_TOO_HIGH`."

        Design: Difficulty/priority_pair_validation_conflict/disclosure_risk_priority_140_beats_insufficient_notice_priority_170
        """
        bundle = _priority_bundle(api)
        investigation_id = bundle["investigation"]["id"]

        validate_error(
            _publish(
                api,
                investigation_id,
                _INSPECTIONS_METHODOLOGY,
                bundle["dataset"]["id"],
            ),
            ERR_DISCLOSURE_RISK_TOO_HIGH,
        )

        after = X.read_investigation(api, investigation_id)
        assert after["status"] == C.INV_FINDINGS_LOCKED, (
            f"status: expected FINDINGS_LOCKED after the refusal, got {after['status']!r}"
        )
        assert_field_absent_or_null(after, "published_at", "investigation")
        assert_field_absent_or_null(after, "disclosure_risk_score", "investigation")
        assert_field_absent_or_null(after, "applicable_risk_variant", "investigation")

    def test_the_refused_publication_leaves_the_notice_record_alone(self, api):
        """At 48 elapsed hours the deadline is still in the future, so nothing lapses.

        PRD S3.9: "a record still in `NOTICE_SENT` whose `response_deadline_at` is
        at or before the current logical clock moves to `NO_RESPONSE`, and this is
        evaluated as a system pre-step at the start of **every** publication
        attempt rather than by any background timer."

        Design: Difficulty/priority_pair_validation_conflict/disclosure_risk_priority_140_beats_insufficient_notice_priority_170
        """
        bundle = _priority_bundle(api)

        validate_error(
            _publish(
                api,
                bundle["investigation"]["id"],
                _INSPECTIONS_METHODOLOGY,
                bundle["dataset"]["id"],
            ),
            ERR_DISCLOSURE_RISK_TOO_HIGH,
        )

        subject = X.read_subject_record(api, bundle["subjects"][0]["id"])
        assert subject["status"] == C.SUBJ_NOTICE_SENT, (
            f"subject status: expected NOTICE_SENT at 48 hours, got {subject['status']!r}"
        )
        assert subject["attempt_count"] == 2, (
            f"attempt_count: expected 2, got {subject['attempt_count']}"
        )
        assert_instant_equals(
            subject["response_deadline_at"],
            X.NOTICE_PLUS_72H,
            label="response_deadline_at",
        )

    def test_suppressing_the_risky_column_surfaces_the_notice_rung(self, api):
        """With the risk-8 column suppressed the score drops to 30 and 170 answers.

        PRD S2.11: "25. Every notified subject-response record must carry at least
        72 hours of elapsed notice, unless its status is `UNREACHABLE` — otherwise
        `ERR_INSUFFICIENT_NOTICE`."

        Design: Difficulty/priority_pair_validation_conflict/disclosure_risk_priority_140_beats_insufficient_notice_priority_170
        """
        bundle = _priority_bundle(api)
        investigation_id = bundle["investigation"]["id"]
        dataset_id = bundle["dataset"]["id"]
        validate_error(
            _publish(api, investigation_id, _INSPECTIONS_METHODOLOGY, dataset_id),
            ERR_DISCLOSURE_RISK_TOO_HIGH,
        )

        suppressed = X.suppress_field(
            api,
            dataset_id,
            _fields_by_name(api, dataset_id)["tenant_zip"]["id"],
            suppression_method=_COARSEN_BUCKET,
        )

        assert suppressed["suppression_applied"] is True, (
            "suppression_applied: expected true, got "
            f"{suppressed['suppression_applied']!r}"
        )
        assert suppressed["suppression_method"] == _COARSEN_BUCKET, (
            "suppression_method: expected the method that was applied, got "
            f"{suppressed['suppression_method']!r}"
        )
        validate_error(
            _publish(api, investigation_id, _INSPECTIONS_METHODOLOGY, dataset_id),
            ERR_INSUFFICIENT_NOTICE,
        )
        after = X.read_investigation(api, investigation_id)
        assert after["status"] == C.INV_FINDINGS_LOCKED, (
            f"status: expected FINDINGS_LOCKED, got {after['status']!r}"
        )
        assert_field_absent_or_null(after, "published_at", "investigation")


# One unsuppressed risk-3 column over 900 records; the mode makes the score moot.
_OVERTIME_SPECS = [
    {"field_name": "shift_code", "reidentification_risk": 3, "null_rate_pct": 0.0}
]

_NOTICE_DEADLINE_72H = "2026-08-06T09:00:00Z"
_RELEASE_CLOCK = "2026-08-06T10:00:00Z"


def _notice_ladder_bundle(api):
    """A ``READY`` METHODOLOGY_ONLY investigation with a right-of-reply record in DRAFT.

    The findings are deliberately left unlocked: the lock is what moves the
    record out of ``DRAFT``, and these tests walk that ladder from the bottom.
    """
    X.set_clock(api, C.STD_CLOCK)
    bundle = X.ready_investigation(
        api,
        C.MODE_METHODOLOGY_ONLY,
        record_count=900,
        field_specs=_OVERTIME_SPECS,
    )
    bundle["subject"] = X.create_subject_record(
        api,
        bundle["investigation"]["id"],
        subject_name="Sheriff's Press Office",
    )
    return bundle


class TestNoticeGatesFireInPriorityOrder:
    """From an attempt on a draft record to the release, one rung at a time."""

    def test_an_attempt_on_a_draft_record_is_refused(self, api):
        """The record stays in DRAFT until the findings are locked, and attempts wait.

        PRD S3.9: "An attempt recorded while the record is `DRAFT`, `RESPONDED` or
        `UNREACHABLE` is refused with `ERR_INVALID_SUBJECT_STATE`."

        Design: Corner/validations/publication_notice_gates_fire_in_priority_order_and_then_release
        """
        bundle = _notice_ladder_bundle(api)

        validate_error(
            api.record_attempt(
                bundle["subject"]["id"],
                F.attempt_payload(channel="EMAIL"),
                coordinator_headers(),
            ),
            ERR_INVALID_SUBJECT_STATE,
        )

        subject = X.read_subject_record(api, bundle["subject"]["id"])
        assert subject["status"] == C.SUBJ_DRAFT, (
            f"subject status: expected DRAFT, got {subject['status']!r}"
        )
        assert subject["attempt_count"] == 0, (
            f"attempt_count: expected 0 after the refusal, got {subject['attempt_count']}"
        )

    def test_locking_the_findings_makes_the_record_eligible_but_not_yet_notified(
        self, api
    ):
        """The lock cascade opens the notice window and the pending rung then answers.

        PRD S3.8: "It cascades in two hops: the investigation moves `ANALYSIS →
        FINDINGS_LOCKED`, and because the findings are now locked, every
        subject-response record of that investigation still in `DRAFT` moves to
        `NOTICE_ELIGIBLE`."
        PRD S2.11: "24. Every subject-response record of the investigation must
        have progressed past `NOTICE_ELIGIBLE`, meaning its `notice_sent_at` is not
        null, before publication — otherwise `ERR_SUBJECT_NOTICE_PENDING`."

        Design: Corner/validations/publication_notice_gates_fire_in_priority_order_and_then_release
        """
        bundle = _notice_ladder_bundle(api)
        investigation_id = bundle["investigation"]["id"]

        locked = validate_ok(api.lock_findings(investigation_id, editor_headers()))

        assert locked["status"] == C.INV_FINDINGS_LOCKED, (
            f"status: expected FINDINGS_LOCKED, got {locked['status']!r}"
        )
        subject = X.read_subject_record(api, bundle["subject"]["id"])
        assert subject["status"] == C.SUBJ_NOTICE_ELIGIBLE, (
            f"subject status: expected NOTICE_ELIGIBLE, got {subject['status']!r}"
        )
        assert subject["attempt_count"] == 0, (
            f"attempt_count: expected 0, got {subject['attempt_count']}"
        )
        assert_field_absent_or_null(subject, "notice_sent_at", "subject record")
        validate_error(
            _publish(api, investigation_id, _METHODOLOGY_V1),
            ERR_SUBJECT_NOTICE_PENDING,
        )

    def test_notice_sufficiency_answers_before_attempt_sufficiency(self, api):
        """Zero elapsed hours reports the notice rung; at 72 hours the attempt rung shows.

        PRD S2.11: "in the publication ladder, notice sufficiency (rung 25) is
        checked before attempt sufficiency (rung 26), so a subject with two
        documented attempts but only 48 hours of elapsed notice yields
        `ERR_INSUFFICIENT_NOTICE`, not `ERR_INSUFFICIENT_ATTEMPTS`."

        Design: Corner/validations/publication_notice_gates_fire_in_priority_order_and_then_release
        """
        bundle = _notice_ladder_bundle(api)
        investigation_id = bundle["investigation"]["id"]
        X.lock_findings(api, investigation_id)

        notified = X.record_attempt(api, bundle["subject"]["id"], channel="EMAIL")

        assert notified["status"] == C.SUBJ_NOTICE_SENT, (
            f"subject status: expected NOTICE_SENT, got {notified['status']!r}"
        )
        assert notified["attempt_count"] == 1, (
            f"attempt_count: expected 1, got {notified['attempt_count']}"
        )
        assert_instant_equals(
            notified["notice_sent_at"], C.STD_CLOCK, label="notice_sent_at"
        )
        assert_instant_equals(
            notified["response_deadline_at"],
            _NOTICE_DEADLINE_72H,
            label="response_deadline_at",
        )
        validate_error(
            _publish(api, investigation_id, _METHODOLOGY_V1), ERR_INSUFFICIENT_NOTICE
        )

        X.set_clock(api, _NOTICE_DEADLINE_72H)

        validate_error(
            _publish(api, investigation_id, _METHODOLOGY_V1),
            ERR_INSUFFICIENT_ATTEMPTS,
        )

    def test_the_second_attempt_never_rebases_the_notice_clock_before_release(
        self, api
    ):
        """A second attempt adds to the log only, and the release follows on time.

        PRD S3.9: "Subsequent deliverable attempts are a self-loop within
        `NOTICE_SENT` that appends to the log and increments the counter but leaves
        `notice_sent_at` and `response_deadline_at` **unchanged**".

        Design: Corner/validations/publication_notice_gates_fire_in_priority_order_and_then_release
        """
        bundle = _notice_ladder_bundle(api)
        investigation_id = bundle["investigation"]["id"]
        X.lock_findings(api, investigation_id)
        version_locked = X.investigation_version(api, investigation_id)
        X.record_attempt(api, bundle["subject"]["id"], channel="EMAIL")

        chased = X.record_attempt(api, bundle["subject"]["id"], channel="PHONE")

        assert chased["status"] == C.SUBJ_NOTICE_SENT, (
            f"subject status: expected NOTICE_SENT, got {chased['status']!r}"
        )
        assert chased["attempt_count"] == 2, (
            f"attempt_count: expected 2, got {chased['attempt_count']}"
        )
        assert_instant_equals(
            chased["notice_sent_at"], C.STD_CLOCK, label="notice_sent_at"
        )
        assert_instant_equals(
            chased["response_deadline_at"],
            _NOTICE_DEADLINE_72H,
            label="response_deadline_at",
        )
        channels = [entry["channel"] for entry in chased["documented_attempts"]]
        assert channels == ["EMAIL", "PHONE"], (
            f"documented_attempts channels: expected EMAIL then PHONE, got {channels}"
        )
        validate_error(
            _publish(api, investigation_id, _METHODOLOGY_V1), ERR_INSUFFICIENT_NOTICE
        )

        X.set_clock(api, _RELEASE_CLOCK)
        published = validate_ok(_publish(api, investigation_id, _METHODOLOGY_V1))

        assert published["status"] == C.INV_PUBLISHED, (
            f"status: expected PUBLISHED, got {published['status']!r}"
        )
        assert_instant_equals(
            published["published_at"], _RELEASE_CLOCK, label="published_at"
        )
        assert published["applicable_risk_variant"] == C.VARIANT_NONE, (
            "applicable_risk_variant: expected NONE, got "
            f"{published['applicable_risk_variant']!r}"
        )
        assert published["disclosure_risk_score"] == 0, (
            f"disclosure_risk_score: expected 0, got {published['disclosure_risk_score']}"
        )
        assert_field_absent_or_null(published, "release_dataset_id", "investigation")
        assert published["version"] == version_locked + 1, (
            "version: only the successful publication may bump it, so expected "
            f"{version_locked + 1}, got {published['version']}"
        )
        subject = X.read_subject_record(api, bundle["subject"]["id"])
        assert subject["status"] == C.SUBJ_NO_RESPONSE, (
            "subject status: the deadline is past, so the publication pre-step lapses "
            f"the record; got {subject['status']!r}"
        )


# One low-risk vehicle identifier over 700 records.
_DEFERRAL_SPECS = [
    {"field_name": "bus_number", "reidentification_risk": 2, "null_rate_pct": 0.0}
]

_REVIEW_WINDOW_START = "2026-08-05T00:00:00Z"
_REVIEW_WINDOW_END = "2026-08-10T00:00:00Z"


def _unconfirmed_bundle(api):
    """An investigation one expert verdict short of ``READY``.

    The chain is built hop by hop rather than through a ready-made helper
    precisely so the verdict can be withheld: the assignment is left ``ASSIGNED``
    and the finding ``DOC_MATCHED``.
    """
    X.set_clock(api, C.STD_CLOCK)
    desk, agency = X.desk_and_agency(api)
    request = X.released_request(api, desk["id"], agency["id"])
    investigation = X.create_investigation(
        api,
        desk["id"],
        C.MODE_METHODOLOGY_ONLY,
        headline="Deferred brake inspections",
    )
    dataset = X.clean_locked_dataset(
        api,
        request["id"],
        investigation["id"],
        record_count=700,
        field_specs=_DEFERRAL_SPECS,
        name=F.unique_dataset_name("maintenance-deferrals"),
    )
    run = X.approved_and_allocated_run(
        api, investigation["id"], compute_cost_cents=5000, labor_hours=1.0
    )
    finding = X.doc_matched_finding(
        api, investigation["id"], run["id"], matched_page=9
    )
    reviewer = X.create_reviewer(
        api,
        affiliation="Transit Safety Lab",
        expertise_code="STATISTICS",
        max_concurrent_assignments=2,
    )
    assignment = X.assign_review(
        api,
        reviewer["id"],
        finding["id"],
        window_start=_REVIEW_WINDOW_START,
        window_end=_REVIEW_WINDOW_END,
    )
    subject = X.create_subject_record(
        api, investigation["id"], subject_name="Transit Agency Spokesperson"
    )
    return {
        "desk": desk,
        "request": request,
        "investigation": investigation,
        "dataset": dataset,
        "run": run,
        "finding": finding,
        "reviewer": reviewer,
        "assignment": assignment,
        "subject": subject,
    }


class TestReadinessAndItsCascadeAreVisibleImmediately:
    """No settling delay: the flip is readable on the very next request."""

    def test_the_outstanding_verdict_is_the_only_missing_readiness_condition(
        self, api
    ):
        """Everything but the expert confirmation is in place, so readiness is NOT_READY.

        PRD S3.7: "`analysis_readiness` is `READY` when **all seven** of the
        following hold: a current run exists; that current run's
        `code_review_status` is `APPROVED`; its `cost_allocation_status` is
        `ALLOCATED`; `sme_confirmed_finding_count` is at least 1;
        `sme_disputed_finding_count` is 0; `unverified_finding_count` is 0; and
        `doc_matched_finding_count` is 0."

        Design: Corner/consistency model/readiness_and_its_cascade_are_visible_in_the_same_request_that_causes_them
        """
        bundle = _unconfirmed_bundle(api)

        investigation = X.read_investigation(api, bundle["investigation"]["id"])

        assert investigation["analysis_readiness"] == C.READINESS_NOT_READY, (
            "analysis_readiness: expected NOT_READY while the finding is only "
            f"document-matched, got {investigation['analysis_readiness']!r}"
        )
        assert_partition_counts(investigation, 1, 0, 1, 0, 0)

    def test_locking_the_findings_is_refused_while_readiness_is_outstanding(
        self, api
    ):
        """The editorial gate refuses and leaves the investigation in analysis.

        PRD S3.8: "It is only declared from `ANALYSIS`, and it requires
        `analysis_readiness` to be `READY`, otherwise `ERR_ANALYSIS_NOT_READY`."

        Design: Corner/consistency model/readiness_and_its_cascade_are_visible_in_the_same_request_that_causes_them
        """
        bundle = _unconfirmed_bundle(api)
        investigation_id = bundle["investigation"]["id"]

        validate_error(
            api.lock_findings(investigation_id, editor_headers()),
            ERR_ANALYSIS_NOT_READY,
        )

        investigation = X.read_investigation(api, investigation_id)
        assert investigation["status"] == C.INV_ANALYSIS, (
            f"status: expected ANALYSIS after the refusal, got {investigation['status']!r}"
        )
        assert investigation["analysis_readiness"] == C.READINESS_NOT_READY, (
            "analysis_readiness: expected NOT_READY, got "
            f"{investigation['analysis_readiness']!r}"
        )

    def test_the_verdict_completes_the_assignment_and_the_next_read_is_ready(
        self, api
    ):
        """One request moves the unit across the partition and readiness follows it.

        PRD S3.8: "`CONFIRMED` drives the finding `DOC_MATCHED → SME_CONFIRMED`,
        moves its unit from `doc_matched_finding_count` to
        `sme_confirmed_finding_count`, and copies the `rationale` into the
        finding's `sme_verdict_rationale`".

        Design: Corner/consistency model/readiness_and_its_cascade_are_visible_in_the_same_request_that_causes_them
        """
        bundle = _unconfirmed_bundle(api)

        completed = validate_ok(
            api.submit_verdict(
                bundle["assignment"]["id"],
                F.verdict_payload(C.VERDICT_CONFIRMED),
                expert_reviewer_headers(bundle["reviewer"]["id"]),
            )
        )

        assert completed["status"] == C.ASSIGN_COMPLETED, (
            f"assignment status: expected COMPLETED, got {completed['status']!r}"
        )
        investigation = X.read_investigation(api, bundle["investigation"]["id"])
        assert investigation["analysis_readiness"] == C.READINESS_READY, (
            "analysis_readiness: the verdict alone must flip it, so expected READY "
            f"on the very next read, got {investigation['analysis_readiness']!r}"
        )
        assert_partition_counts(investigation, 1, 0, 0, 1, 0)

    def test_the_lock_response_itself_reports_the_state_and_the_notice_cascade(
        self, api
    ):
        """The locking call answers with the new state, and the subject is already eligible.

        PRD S3.8: "It cascades in two hops: the investigation moves `ANALYSIS →
        FINDINGS_LOCKED`, and because the findings are now locked, every
        subject-response record of that investigation still in `DRAFT` moves to
        `NOTICE_ELIGIBLE`. The investigation's `version` and each affected
        subject-response record's `version` increment by 1."

        Design: Corner/consistency model/readiness_and_its_cascade_are_visible_in_the_same_request_that_causes_them
        """
        bundle = _unconfirmed_bundle(api)
        investigation_id = bundle["investigation"]["id"]
        X.verdict_on_finding(
            api,
            bundle["finding"]["id"],
            C.VERDICT_CONFIRMED,
            reviewer=bundle["reviewer"],
            window_start=_REVIEW_WINDOW_START,
            window_end=_REVIEW_WINDOW_END,
        )
        version_before = X.investigation_version(api, investigation_id)

        locked = validate_ok(api.lock_findings(investigation_id, editor_headers()))

        assert locked["status"] == C.INV_FINDINGS_LOCKED, (
            "status: the locking response body itself must report the transition, "
            f"got {locked['status']!r}"
        )
        assert locked["version"] == version_before + 1, (
            f"version: expected {version_before + 1}, got {locked['version']}"
        )
        subject = X.read_subject_record(api, bundle["subject"]["id"])
        assert subject["status"] == C.SUBJ_NOTICE_ELIGIBLE, (
            "subject status: the cascade landed inside the locking request, so "
            f"expected NOTICE_ELIGIBLE, got {subject['status']!r}"
        )
        assert subject["version"] == bundle["subject"]["version"] + 1, (
            f"subject version: expected {bundle['subject']['version'] + 1}, "
            f"got {subject['version']}"
        )
