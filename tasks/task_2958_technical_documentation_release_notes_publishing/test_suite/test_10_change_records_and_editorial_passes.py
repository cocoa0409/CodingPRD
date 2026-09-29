"""Change records, the editorial pass, and the rework loop it drives.

A change record starts as engineering language and only becomes customer language
once a *different* operator has rewritten it and the style guide has cleared the
wording.  That fork stores two disjoint field sets, keeps a rework counter that a
clean pass must never reset, and it is the state a record ends in — not the fact
that it exists — that decides whether a release note will ever carry it.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DOCS_LEAD_ALT_USER_ID,
    change_record_context,
    create_change_record,
    create_release_note_payload,
    create_terminology_term,
    editorial_pass,
    editorial_pass_payload,
    exclude_change_record,
    expected_impact_score,
    published_topic_context,
    read_change_record,
    read_doc_set_version,
    read_plan_item,
    set_clock,
    validate_error,
    validate_success,
)


CLOCK = "2026-08-01T00:00:00Z"
APPROVED_TEXT = "Signing in is now faster and more reliable."


class TestEditorialReworkCycle:
    """A blocked pass stores none of the wording it proposed, raises the rework
    counter, and the counter survives the eventual clean pass."""

    def test_blocked_editorial_pass_bounces_the_record_and_stores_no_wording(
        self, api, docs_lead_alt_headers
    ):
        """A single forbidden token sends the record to REWORK_REQUESTED.

        PRD §3.7: "When the scan raises one or more `BLOCKER` violations, the
        record moves to `REWORK_REQUESTED` (or stays there, if it was already
        `REWORK_REQUESTED`): `rework_count` increases by 1 and
        `terminology_blocker_count` is refreshed to the blocker violation count,
        while `customer_facing_text` is **not** stored and `editorial_by_user_id`
        is **not** set."

        PRD §3.7: "The record opens in state `SUBMITTED` with
        `submitted_by_user_id` taken from the submitter's `X-User-ID`,
        `customer_facing_text` null, `terminology_blocker_count` 0,
        `rework_count` 0, and `exclusion_reason` null."

        Design: Corner/state_machines/change_record_editorial_rework_cycle_increments_rework_count
        """
        set_clock(CLOCK)
        create_terminology_term(
            term="login",
            preferred_form="sign in",
            forbidden_forms=["log in", "logon"],
            enforcement_severity="BLOCKER",
        )
        bundle = change_record_context()
        assert bundle["change_record"]["state"] == "SUBMITTED"
        assert bundle["change_record"]["rework_count"] == 0
        assert bundle["change_record"]["terminology_blocker_count"] == 0

        bounced = validate_success(
            api.editorial_pass(
                bundle["change_record_id"],
                editorial_pass_payload(
                    customer_facing_text="Use logon to reach your account.",
                    used_terms=["logon"],
                ),
                docs_lead_alt_headers,
            )
        )

        assert bounced["state"] == "REWORK_REQUESTED"
        assert bounced["rework_count"] == 1
        assert bounced["terminology_blocker_count"] == 1
        assert bounced["customer_facing_text"] is None
        assert bounced["editorial_by_user_id"] is None
        assert read_change_record(bundle["change_record_id"])["customer_facing_text"] is None

    def test_second_blocked_pass_raises_the_counter_while_one_term_still_counts_once(
        self, api, docs_lead_alt_headers
    ):
        """Two forbidden tokens of one term are one violation, but a second bounce.

        PRD §3.4: "Walking the candidate list in that pinned order, a term
        records exactly **one** violation if any submitted token equals any entry
        of that term's `forbidden_forms` under a case-insensitive comparison — a
        term violated by three different tokens still counts once — and that
        violation carries the term's `enforcement_severity`."

        PRD §3.7: "When the scan raises one or more `BLOCKER` violations, the
        record moves to `REWORK_REQUESTED` (or stays there, if it was already
        `REWORK_REQUESTED`): `rework_count` increases by 1 and
        `terminology_blocker_count` is refreshed to the blocker violation count,
        while `customer_facing_text` is **not** stored and `editorial_by_user_id`
        is **not** set."

        Design: Corner/state_machines/change_record_editorial_rework_cycle_increments_rework_count
        """
        set_clock(CLOCK)
        create_terminology_term(
            term="login",
            preferred_form="sign in",
            forbidden_forms=["log in", "logon"],
            enforcement_severity="BLOCKER",
        )
        bundle = change_record_context()
        first = editorial_pass(
            bundle["change_record_id"],
            customer_facing_text="Use logon to reach your account.",
            used_terms=["logon"],
        )
        assert first["rework_count"] == 1

        second = validate_success(
            api.editorial_pass(
                bundle["change_record_id"],
                editorial_pass_payload(
                    customer_facing_text="You can log in or logon as before.",
                    used_terms=["log in", "logon"],
                ),
                docs_lead_alt_headers,
            )
        )

        assert second["state"] == "REWORK_REQUESTED"
        assert second["rework_count"] == 2
        assert second["terminology_blocker_count"] == 1, (
            "one term violated by two tokens is still one violation"
        )
        assert second["customer_facing_text"] is None
        assert second["editorial_by_user_id"] is None

    def test_clean_pass_approves_the_record_without_resetting_the_rework_history(
        self, api, docs_lead_alt_headers
    ):
        """After two bounces a clean pass approves and leaves rework_count at 2.

        PRD §3.7: "When the scan raises zero `BLOCKER` violations, the record
        moves to `EDITORIALLY_APPROVED`: `customer_facing_text` is stored,
        `editorial_by_user_id` is set to the acting `X-User-ID`, and
        `terminology_blocker_count` is set to 0."

        PRD §3.7: "Reaching `EDITORIALLY_APPROVED` from `REWORK_REQUESTED`
        behaves identically, and in particular leaves `rework_count` exactly as
        it stands — a clean pass never resets the rework history."

        Design: Corner/state_machines/change_record_editorial_rework_cycle_increments_rework_count
        """
        set_clock(CLOCK)
        create_terminology_term(
            term="login",
            preferred_form="sign in",
            forbidden_forms=["log in", "logon"],
            enforcement_severity="BLOCKER",
        )
        bundle = change_record_context()
        editorial_pass(
            bundle["change_record_id"],
            customer_facing_text="Use logon to reach your account.",
            used_terms=["logon"],
        )
        editorial_pass(
            bundle["change_record_id"],
            customer_facing_text="You can log in or logon as before.",
            used_terms=["log in", "logon"],
        )

        approved = validate_success(
            api.editorial_pass(
                bundle["change_record_id"],
                editorial_pass_payload(
                    customer_facing_text=APPROVED_TEXT, used_terms=["sign in"]
                ),
                docs_lead_alt_headers,
            )
        )

        assert approved["state"] == "EDITORIALLY_APPROVED"
        assert approved["customer_facing_text"] == APPROVED_TEXT
        assert approved["editorial_by_user_id"] == DOCS_LEAD_ALT_USER_ID
        assert approved["terminology_blocker_count"] == 0
        assert approved["rework_count"] == 2, "a clean pass never resets the rework history"
        assert read_change_record(bundle["change_record_id"])["rework_count"] == 2


class TestEditorialSegregationOfDuties:
    """The editorial pass is deliberately a different person's job, and the identity
    test is on the acting header rather than on the role."""

    def test_the_submitting_operator_cannot_edit_their_own_change_record(
        self, api, docs_lead_headers, docs_lead_user_id
    ):
        """A `DocsLead` who submitted the record is refused as its editor.

        PRD §3.7: "The acting `X-User-ID` must differ from the record's
        `submitted_by_user_id`; an editor who is also the submitter is refused
        with `ERR_EDITORIAL_SOD_VIOLATION` (HTTP 403)."

        PRD §2.5: "**Safety and segregation of duties.** Self-review prohibition,
        editorial separation of duties, and the requirement that a breaking
        change already have a published migration path."

        Design: Corner/validations/editorial_pass_by_the_submitting_operator_rejected_then_allowed_for_another
        """
        set_clock(CLOCK)
        bundle = change_record_context(severity="MAJOR", category="FIX")
        submitted = bundle["change_record"]
        assert submitted["submitted_by_user_id"] == docs_lead_user_id

        response = api.editorial_pass(
            bundle["change_record_id"],
            editorial_pass_payload(customer_facing_text=APPROVED_TEXT),
            docs_lead_headers,
        )
        validate_error(response, ApiErrorId.EDITORIAL_SOD_VIOLATION, 403)

        unchanged = read_change_record(bundle["change_record_id"])
        assert unchanged["state"] == "SUBMITTED"
        assert unchanged["customer_facing_text"] is None
        assert unchanged["editorial_by_user_id"] is None
        assert unchanged["rework_count"] == 0
        assert unchanged["terminology_blocker_count"] == 0
        assert unchanged["version"] == submitted["version"]

    def test_a_second_operator_carries_the_identical_pass_through(
        self, api, docs_lead_headers, docs_lead_user_id, docs_lead_alt_headers
    ):
        """The very payload the submitter was refused succeeds for another editor.

        PRD §3.7: "The acting `X-User-ID` must differ from the record's
        `submitted_by_user_id`; an editor who is also the submitter is refused
        with `ERR_EDITORIAL_SOD_VIOLATION` (HTTP 403)."

        PRD §3.7: "When the scan raises zero `BLOCKER` violations, the record
        moves to `EDITORIALLY_APPROVED`: `customer_facing_text` is stored,
        `editorial_by_user_id` is set to the acting `X-User-ID`, and
        `terminology_blocker_count` is set to 0."

        Design: Corner/validations/editorial_pass_by_the_submitting_operator_rejected_then_allowed_for_another
        """
        set_clock(CLOCK)
        bundle = change_record_context(severity="MAJOR", category="FIX")
        payload = editorial_pass_payload(customer_facing_text=APPROVED_TEXT)
        validate_error(
            api.editorial_pass(bundle["change_record_id"], payload, docs_lead_headers),
            ApiErrorId.EDITORIAL_SOD_VIOLATION,
            403,
        )

        approved = validate_success(
            api.editorial_pass(bundle["change_record_id"], payload, docs_lead_alt_headers)
        )

        assert approved["state"] == "EDITORIALLY_APPROVED"
        assert approved["customer_facing_text"] == APPROVED_TEXT
        assert approved["editorial_by_user_id"] == DOCS_LEAD_ALT_USER_ID
        assert approved["editorial_by_user_id"] != docs_lead_user_id
        assert approved["submitted_by_user_id"] == docs_lead_user_id
        assert approved["terminology_blocker_count"] == 0
        assert approved["rework_count"] == 0


class TestOnlyEditoriallyApprovedRecordsReachCustomers:
    """Submitted-but-unedited and excluded records are invisible to a release note,
    and the note's score is computed over the surviving set only."""

    def test_compilation_gathers_the_approved_record_and_ignores_the_other_two(
        self, api, docs_lead_headers
    ):
        """Of three records only the editorially approved one is compiled.

        PRD §3.7: "The included set is the change records of the documentation
        set's release train whose `state` is `EDITORIALLY_APPROVED`, ordered by
        `created_at` ascending; records that are `SUBMITTED`,
        `REWORK_REQUESTED`, `EXCLUDED`, or already `PUBLISHED` are never
        included."

        PRD §3.7: "`severity_counts` maps each of the five severities to the
        number of included records carrying it, with keys `BREAKING`,
        `SECURITY`, `MAJOR`, `MINOR`, and `PATCH`."

        PRD §3.7: "`headline_severity` is the severity with the highest weight
        present in the included set, using the weights `BREAKING` 40, `SECURITY`
        25, `MAJOR` 12, `MINOR` 4, and `PATCH` 1."

        Design: Corner/calculations/release_note_includes_only_editorially_approved_records
        """
        set_clock(CLOCK)
        bundle = published_topic_context()
        feature_key = read_plan_item(bundle["plan_item_id"])["feature_key"]
        approved_record = create_change_record(
            bundle["train_id"],
            severity="MINOR",
            category="FEATURE",
            affected_component=feature_key,
        )
        editorial_pass(approved_record["id"], customer_facing_text=APPROVED_TEXT)
        submitted_record = create_change_record(
            bundle["train_id"], severity="MAJOR", category="FIX", affected_component=feature_key
        )
        excluded_record = create_change_record(
            bundle["train_id"], severity="PATCH", category="FIX", affected_component=feature_key
        )
        exclude_change_record(
            excluded_record["id"], exclusion_reason="Internal refactor with no visible effect."
        )

        note = validate_success(
            api.create_release_note(
                create_release_note_payload(
                    bundle["doc_set_id"], read_doc_set_version(bundle["doc_set_id"])["version"]
                ),
                docs_lead_headers,
            ),
            201,
        )

        expected = expected_impact_score(["MINOR"], 1)
        assert note["included_change_record_ids"] == [approved_record["id"]]
        assert submitted_record["id"] not in note["included_change_record_ids"]
        assert excluded_record["id"] not in note["included_change_record_ids"]
        assert note["severity_counts"] == {
            "BREAKING": 0,
            "SECURITY": 0,
            "MAJOR": 0,
            "MINOR": 1,
            "PATCH": 0,
        }
        assert note["severity_counts"] == expected["severity_counts"]
        assert note["headline_severity"] == "MINOR"
        assert note["coverage_factor_provisional"] == pytest.approx(1.00, abs=0.01)
        assert note["impact_score_provisional"] == pytest.approx(4.00, abs=0.01)
        assert note["impact_score_provisional"] == pytest.approx(
            expected["impact_score"], abs=0.01
        )

    def test_the_records_left_out_of_the_note_are_not_touched_by_the_compilation(
        self, api, docs_lead_headers
    ):
        """Compilation moves nothing: the omitted records keep their own states.

        PRD §3.7: "An excluded record can never enter a release note."

        PRD §3.7: "Compilation opens the note with `status` `COMPILED`, stamps
        `compiled_at` from the logical clock, moves any existing `COMPILED` note
        of that documentation set to `SUPERSEDED` while leaving that superseded
        note's change records `EDITORIALLY_APPROVED` so they are recompiled into
        the new note, and increments the documentation set's `version` by 1."

        Design: Corner/calculations/release_note_includes_only_editorially_approved_records
        """
        set_clock(CLOCK)
        bundle = published_topic_context()
        feature_key = read_plan_item(bundle["plan_item_id"])["feature_key"]
        approved_record = create_change_record(
            bundle["train_id"],
            severity="MINOR",
            category="FEATURE",
            affected_component=feature_key,
        )
        editorial_pass(approved_record["id"], customer_facing_text=APPROVED_TEXT)
        submitted_record = create_change_record(
            bundle["train_id"], severity="MAJOR", category="FIX", affected_component=feature_key
        )
        excluded_record = create_change_record(
            bundle["train_id"], severity="PATCH", category="FIX", affected_component=feature_key
        )
        excluded_record = exclude_change_record(
            excluded_record["id"], exclusion_reason="Internal refactor with no visible effect."
        )
        doc_set_version_before = read_doc_set_version(bundle["doc_set_id"])["version"]

        note = validate_success(
            api.create_release_note(
                create_release_note_payload(bundle["doc_set_id"], doc_set_version_before),
                docs_lead_headers,
            ),
            201,
        )

        assert note["status"] == "COMPILED"
        assert read_doc_set_version(bundle["doc_set_id"])["version"] == doc_set_version_before + 1

        untouched_submitted = read_change_record(submitted_record["id"])
        assert untouched_submitted["state"] == "SUBMITTED"
        assert untouched_submitted["customer_facing_text"] is None
        assert untouched_submitted["version"] == submitted_record["version"]

        untouched_excluded = read_change_record(excluded_record["id"])
        assert untouched_excluded["state"] == "EXCLUDED"
        assert untouched_excluded["exclusion_reason"] == (
            "Internal refactor with no visible effect."
        )
        assert untouched_excluded["version"] == excluded_record["version"]

        still_approved = read_change_record(approved_record["id"])
        assert still_approved["state"] == "EDITORIALLY_APPROVED"
