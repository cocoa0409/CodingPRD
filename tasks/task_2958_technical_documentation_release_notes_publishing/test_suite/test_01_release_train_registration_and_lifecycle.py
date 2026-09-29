"""Release-train registration, the lifecycle spine, and the readiness posture.

The release train is the root of the whole system: nothing can be planned,
published, localized or deprecated except against one.  This module covers the
registration response shape, the vacuous-readiness convention that governs an
empty train, the two time-and-state preconditions on the spine, and the state
gates that close planning down once a release goes generally available.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_release_train_payload,
    advance_train,
    assign_plan_item_payload,
    assert_instant_format,
    assert_new_release_train_defaults,
    assert_release_train,
    assert_response_envelope,
    assert_versioned_audit_fields,
    cancel_plan_item_payload,
    cancelled_plan_item_context,
    create_plan_item,
    create_plan_item_payload,
    create_release_train_payload,
    create_writer,
    instants_equal,
    is_valid_uuid,
    maintenance_train_context,
    plan_item_context,
    read_plan_item,
    read_release_train,
    read_topic,
    read_writer,
    request_signoff_payload,
    set_clock,
    submitted_topic_context,
    create_doc_set_version,
    create_reviewer,
    draft_doc_set_context,
    read_doc_set_version,
    validate_error,
    validate_paginated,
    validate_success,
)


CLOCK = "2026-08-01T00:00:00Z"


class TestReleaseTrainRegistration:
    """Registration echoes every declared field and seeds every derived one."""

    def test_registration_returns_the_complete_declared_field_set(self, api, docs_lead_headers):
        """Every stored and derived field appears in the creation response.

        PRD §3.1: "A newly registered train opens with `status` `PLANNED`,
        `doc_readiness_posture` `OPEN`, `approved_topic_ratio` `1.00`,
        `plan_item_count`, `approved_plan_item_count`,
        `localization_committed_cents` all zero, and `eol_notice_posted` false."

        PRD §4: "Creating a new resource returns HTTP 201; every other
        successful operation, including every state transition and every read,
        returns HTTP 200."

        Design: Corner/entities/release_train_create_returns_every_declared_field
        """
        set_clock(CLOCK)
        payload = create_release_train_payload(
            product_key="ATLAS",
            doc_freeze_date="2026-08-20",
            ga_date="2026-09-01",
            support_end_date="2027-09-01",
            localization_budget_cap_cents=5000000,
        )

        response = api.create_release_train(payload, docs_lead_headers)
        data = validate_success(response, 201)

        assert_response_envelope(response, "object")
        assert_release_train(data)
        assert is_valid_uuid(data["id"])
        assert data["product_key"] == "ATLAS"
        assert data["version_label"] == payload["version_label"]
        assert data["doc_freeze_date"] == "2026-08-20"
        assert data["ga_date"] == "2026-09-01"
        assert data["support_end_date"] == "2027-09-01"
        assert data["localization_budget_cap_cents"] == 5000000
        assert_new_release_train_defaults(data)
        assert_versioned_audit_fields(data, expected_version=1)
        assert_instant_format(data["created_at"])
        assert instants_equal(data["created_at"], CLOCK)

    def test_registration_of_an_empty_train_reports_a_vacuous_readiness_ratio(
        self, api, docs_lead_headers
    ):
        """A train with no counted deliverables reads 1.00, not 0.00 and not null.

        PRD §3.1: "Third, `approved_topic_ratio` is `1.00` when
        `plan_item_count` is zero — a train with no counted deliverables is
        vacuously ready, not zero and not null — and otherwise the approved
        count divided by the total count, rounded half up to two decimal
        places."

        Design: Corner/calculations/release_train_readiness_empty_set_is_vacuously_one
        """
        set_clock(CLOCK)
        train = validate_success(
            api.create_release_train(create_release_train_payload(), docs_lead_headers), 201
        )

        read_back = validate_success(api.get_release_train(train["id"], docs_lead_headers))

        assert read_back["plan_item_count"] == 0
        assert read_back["approved_plan_item_count"] == 0
        assert read_back["approved_topic_ratio"] == pytest.approx(1.00, abs=0.01)
        assert read_back["approved_topic_ratio"] is not None
        assert read_back["doc_readiness_posture"] == "OPEN"

    def test_empty_train_stays_open_after_the_freeze_advance_makes_the_band_live(
        self, api, docs_lead_headers
    ):
        """At DOC_FREEZE the ratio band is consulted, and 1.00 still clears 0.80.

        PRD §3.1: "otherwise — that is, for `DOC_FREEZE` and `GA`, the
        ratio-driven band — the posture is `OPEN` when the ratio is at least
        0.80, `RESTRICTED` when it is at least 0.50 but below 0.80, and
        `FROZEN` when it is below 0.50."

        Design: Corner/calculations/release_train_readiness_empty_set_is_vacuously_one
        """
        set_clock(CLOCK)
        train = validate_success(
            api.create_release_train(create_release_train_payload(), docs_lead_headers), 201
        )

        frozen = validate_success(
            api.advance_release_train(
                train["id"], advance_release_train_payload("DOC_FREEZE"), docs_lead_headers
            )
        )

        assert frozen["status"] == "DOC_FREEZE"
        assert frozen["plan_item_count"] == 0
        assert frozen["approved_topic_ratio"] == pytest.approx(1.00, abs=0.01)
        assert frozen["doc_readiness_posture"] == "OPEN"
        assert frozen["version"] == 2

    def test_first_unapproved_deliverable_drags_a_frozen_train_below_the_band(
        self, api, docs_lead_headers
    ):
        """One DRAFTED plan item takes the ratio to 0.00 and the posture to FROZEN.

        PRD §3.1: "First, `plan_item_count` is the number of the train's plan
        items whose status is anything other than `CANCELLED`."

        PRD §3.1: "Both band boundaries are inclusive from below: a ratio of
        exactly 0.80 yields `OPEN`, exactly 0.50 yields `RESTRICTED`, and 0.49
        yields `FROZEN`."

        PRD §2.4: "Alongside `id`, most resources expose `created_at` and
        `updated_at` as ISO 8601 UTC instants with exactly three
        fractional-second digits and a trailing `Z`, plus a `version` integer
        that begins at 1 when the resource is created and increases by exactly 1
        on every mutation the server applies to that resource — including
        mutations that arrive as the side effect of an operation on a different
        resource."

        Design: Corner/calculations/release_train_readiness_empty_set_is_vacuously_one
        """
        set_clock(CLOCK)
        train = validate_success(
            api.create_release_train(create_release_train_payload(), docs_lead_headers), 201
        )
        advance_train(train["id"], "DOC_FREEZE")

        validate_success(
            api.create_plan_item(create_plan_item_payload(train["id"]), docs_lead_headers), 201
        )
        read_back = validate_success(api.get_release_train(train["id"], docs_lead_headers))

        assert read_back["plan_item_count"] == 1
        assert read_back["approved_plan_item_count"] == 0
        assert read_back["approved_topic_ratio"] == pytest.approx(0.00, abs=0.01)
        assert read_back["doc_readiness_posture"] == "FROZEN"
        assert read_back["version"] == 3, (
            "registration seeds version 1, the advance bumps it to 2, and the "
            "plan-item create mutates the train's counters as a side effect"
        )


class TestLifecycleSpinePreconditions:
    """Two of the four hops on the spine carry an extra precondition."""

    def test_general_availability_is_refused_while_the_documentation_set_is_a_draft(
        self, api, docs_lead_headers
    ):
        """DOC_FREEZE -> GA needs a PUBLISHED doc set, not merely an open draft.

        PRD §3.1: "The `DOC_FREEZE → GA` hop requires that at least one
        documentation set of this train has already reached `PUBLISHED` status,
        and refuses with `ERR_DOC_SET_NOT_PUBLISHED` otherwise — a release
        cannot go generally available with no published documentation."

        Design: Corner/state_machines/release_train_advance_to_ga_without_published_doc_set_rejected
        """
        set_clock(CLOCK)
        train = validate_success(
            api.create_release_train(create_release_train_payload(), docs_lead_headers), 201
        )
        doc_set = create_doc_set_version(train["id"])
        advance_train(train["id"], "DOC_FREEZE")

        response = api.advance_release_train(
            train["id"], advance_release_train_payload("GA"), docs_lead_headers
        )
        validate_error(response, ApiErrorId.DOC_SET_NOT_PUBLISHED, 409)

        assert read_release_train(train["id"])["status"] == "DOC_FREEZE"
        unchanged = read_doc_set_version(doc_set["id"])
        assert unchanged["status"] == "DRAFT"
        assert unchanged["published_at"] is None

    def test_end_of_life_is_refused_while_the_clock_is_short_of_the_support_end_date(
        self, api, docs_lead_headers
    ):
        """MAINTENANCE -> END_OF_LIFE is time-gated on the logical clock.

        PRD §3.1: "The `MAINTENANCE → END_OF_LIFE` hop requires that the
        logical clock's date has reached or passed `support_end_date`, and
        refuses with `ERR_SUPPORT_END_DATE_NOT_REACHED` while the clock is still
        earlier than that date."

        Design: Corner/state_machines/release_train_advance_to_end_of_life_before_support_end_date_rejected
        """
        set_clock(CLOCK)
        bundle = maintenance_train_context(
            train_overrides={
                "doc_freeze_date": "2026-08-20",
                "ga_date": "2026-09-01",
                "support_end_date": "2027-09-01",
            }
        )

        response = api.advance_release_train(
            bundle["train_id"], advance_release_train_payload("END_OF_LIFE"), docs_lead_headers
        )
        validate_error(response, ApiErrorId.SUPPORT_END_DATE_NOT_REACHED, 409)

        train = read_release_train(bundle["train_id"])
        assert train["status"] == "MAINTENANCE"
        assert train["eol_notice_posted"] is False
        assert train["doc_readiness_posture"] == "FROZEN"
        assert read_doc_set_version(bundle["doc_set_id"])["status"] == "PUBLISHED"
        assert read_topic(bundle["topic_id"])["publication_state"] == "PUBLISHED"

    def test_maintenance_train_reports_a_frozen_posture_before_the_ratio_band(
        self, api, docs_lead_headers
    ):
        """MAINTENANCE short-circuits the posture decision before the ratio band.

        PRD §3.1: "Fourth, `doc_readiness_posture` is decided as follows: if the
        train's status is `MAINTENANCE` or `END_OF_LIFE` the posture is
        `FROZEN`, and this test short-circuits before the ratio is consulted at
        all; otherwise, if the status is `PLANNED` the posture is `OPEN`,
        because planning is always open; otherwise — that is, for `DOC_FREEZE`
        and `GA`, the ratio-driven band — the posture is `OPEN` when the ratio
        is at least 0.80, `RESTRICTED` when it is at least 0.50 but below 0.80,
        and `FROZEN` when it is below 0.50."

        Design: Corner/state_machines/release_train_advance_to_end_of_life_before_support_end_date_rejected
        """
        set_clock(CLOCK)
        bundle = maintenance_train_context()

        train = validate_success(api.get_release_train(bundle["train_id"], docs_lead_headers))

        assert train["status"] == "MAINTENANCE"
        assert train["approved_topic_ratio"] == pytest.approx(1.00, abs=0.01)
        assert train["doc_readiness_posture"] == "FROZEN"


class TestPlanningSpineStateGates:
    """Four state preconditions on the planning spine, each reached from a
    different state rather than from a malformed request."""

    def test_writer_on_leave_cannot_receive_a_deliverable(self, api, docs_lead_headers):
        """An ON_LEAVE assignee is refused and their ledger stays untouched.

        PRD §3.2: "The target writer's `status` must be `ACTIVE`; an `ON_LEAVE`
        writer cannot receive work, and the attempt is refused with
        `ERR_WRITER_ON_LEAVE`."

        Design: Corner/errors/plan_item_and_train_state_gate_rejections_swept_together
        """
        set_clock(CLOCK)
        bundle = plan_item_context()
        on_leave = create_writer(status="ON_LEAVE")

        response = api.assign_plan_item(
            bundle["plan_item_id"], assign_plan_item_payload(on_leave["id"]), docs_lead_headers
        )
        validate_error(response, ApiErrorId.WRITER_ON_LEAVE, 409)

        ledger = read_writer(on_leave["id"])
        assert ledger["committed_load_points"] == pytest.approx(0.00, abs=0.01)
        assert ledger["assignment_count"] == 0
        assert read_plan_item(bundle["plan_item_id"])["status"] == "DRAFTED"

    def test_deliverable_already_in_review_cannot_change_hands(self, api, docs_lead_headers):
        """Assignment is permitted only from DRAFTED, ASSIGNED, or IN_AUTHORING.

        PRD §3.2: "The plan item's own status must be `DRAFTED`, `ASSIGNED`, or
        `IN_AUTHORING`; a deliverable that has already entered review, been
        approved, published, or cancelled cannot change hands, and the attempt
        is refused with `ERR_PLAN_ITEM_NOT_ASSIGNABLE`."

        Design: Corner/errors/plan_item_and_train_state_gate_rejections_swept_together
        """
        set_clock(CLOCK)
        bundle = submitted_topic_context()
        assert read_plan_item(bundle["plan_item_id"])["status"] == "IN_REVIEW"

        response = api.assign_plan_item(
            bundle["plan_item_id"],
            assign_plan_item_payload(
                bundle["writer_id"],
                window_start_date="2026-08-04",
                window_end_date="2026-08-18",
            ),
            docs_lead_headers,
        )
        validate_error(response, ApiErrorId.PLAN_ITEM_NOT_ASSIGNABLE, 409)

        unchanged = read_plan_item(bundle["plan_item_id"])
        assert unchanged["assigned_writer_id"] == bundle["writer_id"]
        assert unchanged["window_start_date"] == "2026-08-02"
        assert unchanged["window_end_date"] == "2026-08-09"

    def test_cancelling_an_already_cancelled_deliverable_is_refused(
        self, api, docs_lead_headers
    ):
        """A CANCELLED plan item cannot be cancelled a second time.

        PRD §3.2: "A `DocsLead` supplies a `cancel_reason` and the item moves to
        `CANCELLED`, which is permitted only from `DRAFTED`, `ASSIGNED`,
        `IN_AUTHORING`, `IN_REVIEW`, or `IN_REVISION`; an item that is
        `APPROVED_CONTENT`, `PUBLISHED`, or already `CANCELLED` is refused with
        `ERR_PLAN_ITEM_NOT_CANCELLABLE`."

        Design: Corner/errors/plan_item_and_train_state_gate_rejections_swept_together
        """
        set_clock(CLOCK)
        bundle = cancelled_plan_item_context()
        original_reason = read_plan_item(bundle["plan_item_id"])["cancel_reason"]

        response = api.cancel_plan_item(
            bundle["plan_item_id"],
            cancel_plan_item_payload(cancel_reason="Cutting it a second time."),
            docs_lead_headers,
        )
        validate_error(response, ApiErrorId.PLAN_ITEM_NOT_CANCELLABLE, 409)

        assert read_plan_item(bundle["plan_item_id"])["cancel_reason"] == original_reason

    def test_skipping_a_step_on_the_lifecycle_spine_is_refused(self, api, docs_lead_headers):
        """GA is not the immediate successor of PLANNED, so the hop is rejected.

        PRD §3.1: "A `DocsLead` advances it by naming the desired
        `target_status`; if that value is not the immediate successor of the
        current status in that order — including any attempt to skip a step, to
        move backwards, or to advance out of the terminal `END_OF_LIFE` — the
        request is rejected with `ERR_RELEASE_TRAIN_INVALID_ADVANCE`."

        Design: Corner/errors/plan_item_and_train_state_gate_rejections_swept_together
        """
        set_clock(CLOCK)
        train = validate_success(
            api.create_release_train(create_release_train_payload(), docs_lead_headers), 201
        )

        response = api.advance_release_train(
            train["id"], advance_release_train_payload("GA"), docs_lead_headers
        )
        validate_error(response, ApiErrorId.RELEASE_TRAIN_INVALID_ADVANCE, 409)

        assert read_release_train(train["id"])["status"] == "PLANNED"
        assert read_release_train(train["id"])["version"] == 1


class TestPlanningClosesAtGeneralAvailability:
    """Once a release goes generally available the planning spine is closed, and
    that closure is a property of the TRAIN rather than of the deliverable."""

    def test_pristine_deliverable_cannot_be_assigned_once_the_train_reaches_ga(
        self, api, docs_lead_headers
    ):
        """The train's own status closes assignment even for a DRAFTED item.

        PRD §3.2: "The train's own lifecycle status must be `PLANNED` or
        `DOC_FREEZE`; an assignment against a train that has reached `GA`,
        `MAINTENANCE`, or `END_OF_LIFE` is refused with
        `ERR_RELEASE_TRAIN_CLOSED_FOR_PLANNING`."

        Design: Corner/errors/planning_closed_after_ga_and_second_signoff_of_one_discipline_rejected
        """
        set_clock(CLOCK)
        bundle = draft_doc_set_context(writer_overrides={"capacity_points": 500.0})
        publish_response = api.publish_doc_set_version(bundle["doc_set_id"], {}, docs_lead_headers)
        validate_success(publish_response)
        second_item = create_plan_item(bundle["train_id"])
        advance_train(bundle["train_id"], "DOC_FREEZE")
        train = advance_train(bundle["train_id"], "GA")
        assert train["status"] == "GA"

        response = api.assign_plan_item(
            second_item["id"],
            assign_plan_item_payload(
                bundle["writer_id"],
                window_start_date="2026-08-20",
                window_end_date="2026-08-28",
            ),
            docs_lead_headers,
        )
        validate_error(response, ApiErrorId.RELEASE_TRAIN_CLOSED_FOR_PLANNING, 409)

        unassigned = read_plan_item(second_item["id"])
        assert unassigned["status"] == "DRAFTED"
        assert unassigned["assigned_writer_id"] is None

    def test_second_reviewer_of_a_covered_discipline_is_refused(self, api, docs_lead_headers):
        """Discipline uniqueness keys on the discipline, not on the reviewer id.

        PRD §3.5: "**Only then** is discipline uniqueness checked: the topic must
        hold no sign-off in state `PENDING`, `APPROVED`, or `CHANGES_REQUESTED`
        for the requested reviewer's discipline, else
        `ERR_DUPLICATE_SIGNOFF_DISCIPLINE`."

        Design: Corner/errors/planning_closed_after_ga_and_second_signoff_of_one_discipline_rejected
        """
        set_clock(CLOCK)
        bundle = submitted_topic_context()
        first_engineer = create_reviewer(discipline="ENGINEERING")
        second_engineer = create_reviewer(discipline="ENGINEERING")

        accepted = validate_success(
            api.request_signoff(
                bundle["topic_id"], request_signoff_payload(first_engineer["id"]), docs_lead_headers
            ),
            201,
        )
        assert accepted["state"] == "PENDING"
        assert accepted["discipline"] == "ENGINEERING"

        response = api.request_signoff(
            bundle["topic_id"], request_signoff_payload(second_engineer["id"]), docs_lead_headers
        )
        validate_error(response, ApiErrorId.DUPLICATE_SIGNOFF_DISCIPLINE, 409)

        rows, _ = validate_paginated(api.list_topic_signoffs(bundle["topic_id"], docs_lead_headers))
        assert len([row for row in rows if row["state"] == "PENDING"]) == 1
