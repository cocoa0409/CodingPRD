"""One fabricated id, nine different 404 codes, and four replayed transitions.

The service never falls back on a generic code: every entity owns its own
not-found and invalid-state identifier, and a rejected replay leaves the row it
addressed exactly as it was.
"""

import pytest

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as F
from test_helpers.api_errors import (
    ERR_DOWNSTREAM_SYSTEM_NOT_FOUND,
    ERR_INVESTIGATION_NOT_FOUND,
    ERR_MERGE_INVALID_STATE,
    ERR_MERGE_NOT_FOUND,
    ERR_OVERLAY_INVALID_STATE,
    ERR_OVERLAY_NOT_FOUND,
    ERR_PAIR_NOT_FOUND,
    ERR_REMEDIATION_INVALID_STATE,
    ERR_REMEDIATION_NOT_FOUND,
    ERR_RULE_SET_NOT_FOUND,
    ERR_SEARCH_ATTEMPT_NOT_FOUND,
    ERR_TASK_INVALID_STATE,
    ERR_TASK_NOT_FOUND,
    ERR_UNAUTHENTICATED,
)
from test_helpers.constants import (
    IDENTITY_ACTIVE,
    MERGE_UNMERGED,
    OPERATION_MERGE,
    OPERATION_UNMERGE,
    OVERLAY_UNDER_CORRECTION,
    PROPAGATION_MODE_BATCH,
    REMEDIATION_CLOSED,
    SCORE_VARIANT_STRICT,
    TASK_CANCELLED,
    TASK_QUEUED,
)
from test_helpers.test_users import (
    STEWARD_2_USER_ID,
    admin_headers,
    analyst_headers,
    headers_without_role,
    make_headers,
    officer_headers,
    steward_headers,
)

MISSING_ID = "00000000-0000-4000-8000-000000000000"


class TestNotFoundTaxonomy:
    def test_the_same_absent_id_names_nine_different_resources(self, api):
        """Which code comes back depends only on which resource the id stood for.

        PRD §2.8: "The `MatchRuleSet` named by the `{id}` path segment or by the body's
        `rule_set_id` exists — otherwise `ERR_RULE_SET_NOT_FOUND`, HTTP 404."

        PRD §2.8: "The `RegistrationSearchAttempt` named by the body's
        `origin_search_attempt_id` exists — otherwise `ERR_SEARCH_ATTEMPT_NOT_FOUND`,
        HTTP 404."

        Design: Corner/errors/unknown_ids_return_the_entity_specific_not_found_error
        """
        site = F.create_site(
            api, "XA-SITE", name="Not Found Clinic", region_code="US-DE",
            registrar_headcount=1,
        )

        A.assert_error_envelope(
            api.get_rule_set(MISSING_ID, admin_headers()),
            ERR_RULE_SET_NOT_FOUND, 404,
        )
        A.assert_error_envelope(
            api.create_record(
                f.record_payload(
                    site["id"], "XA-1000", "Renaud", "Colette", "1980-03-03", "F",
                    origin_search_attempt_id=MISSING_ID,
                ),
                analyst_headers(),
            ),
            ERR_SEARCH_ATTEMPT_NOT_FOUND, 404,
        )
        A.assert_error_envelope(
            api.get_pair(MISSING_ID, analyst_headers()), ERR_PAIR_NOT_FOUND, 404
        )
        A.assert_error_envelope(
            api.get_merge(MISSING_ID, steward_headers()), ERR_MERGE_NOT_FOUND, 404
        )
        A.assert_error_envelope(
            api.get_overlay(MISSING_ID, steward_headers()), ERR_OVERLAY_NOT_FOUND, 404
        )
        A.assert_error_envelope(
            api.get_remediation(MISSING_ID, officer_headers()),
            ERR_REMEDIATION_NOT_FOUND, 404,
        )
        A.assert_error_envelope(
            api.get_task(MISSING_ID, admin_headers()), ERR_TASK_NOT_FOUND, 404
        )
        A.assert_error_envelope(
            api.get_investigation(MISSING_ID, officer_headers()),
            ERR_INVESTIGATION_NOT_FOUND, 404,
        )
        error = A.assert_error_envelope(
            api.get_system(MISSING_ID, admin_headers()),
            ERR_DOWNSTREAM_SYSTEM_NOT_FOUND, 404,
        )
        assert isinstance(error["message"], str) and error["message"] != ""
        assert A.list_rows(
            api.list_records(admin_headers(), {"site_id": site["id"]}),
            expected_total=0,
        ) == []


XB_DEMOGRAPHICS = {
    "last_name": "Iwuchukwu",
    "first_name": "Ngozi",
    "dob": "1974-04-14",
    "sex": "F",
    "ssn_last4": "9595",
    "postal_code": "21201",
    "phone": "4105550101",
}


class TestReplayedTransitions:
    def test_each_lifecycle_reports_its_own_invalid_state_code(self, api):
        """Four finished transitions are replayed and four different codes come back.

        PRD §2.8: "The merge operation's `state` is a declared origin state of the
        requested merge transition — otherwise `ERR_MERGE_INVALID_STATE`, HTTP 409."

        PRD §2.8: "The propagation task's `state` is `QUEUED` or `FAILED` for a send,
        and `SENT` for an acknowledgement or a failure report — otherwise
        `ERR_TASK_INVALID_STATE`, HTTP 409."

        Design: Corner/errors/re_triggering_a_finished_transition_returns_that_entity_s_invalid_state_error
        """
        site = F.create_site(
            api, "XB-SITE", name="Invalid State Clinic", region_code="US-MD",
            registrar_headcount=3,
        )
        rule_set = F.create_rule_set(api, activate=False)
        F.create_system(
            api, "XB-SYS", name="Warehouse",
            propagation_mode=PROPAGATION_MODE_BATCH, ack_required=True,
            max_concurrent_dispatch=1,
        )
        survivor = F.create_record(
            api, site["id"], "XB-1000", clinical_element_count=2, **XB_DEMOGRAPHICS
        )
        subsumed = F.create_record(
            api, site["id"], "XB-2000", clinical_element_count=30, **XB_DEMOGRAPHICS
        )
        unrelated = F.create_record(
            api, site["id"], "XB-3000", "Sandoval", "Ramiro", "1958-10-10", "M",
            ssn_last4="0606", postal_code="21202", phone="4105550202",
            clinical_element_count=6,
        )
        pair = F.create_pair(
            api, survivor["id"], subsumed["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        merge_row = F.merge(
            api, pair["id"], survivor["id"], subsumed["id"], rationale="Same patient."
        )
        A.assert_integer(
            merge_row["moved_clinical_element_count"], 30,
            "moved_clinical_element_count",
        )
        remediation = A.list_rows(
            api.list_remediations(
                officer_headers(), {"merge_operation_id": merge_row["id"]}
            ),
            expected_total=1,
        )[0]
        A.assert_ok(
            api.quarantine(
                remediation["id"], f.quarantine_payload(30), officer_headers()
            )
        )
        closed = A.assert_ok(
            api.close_remediation(
                remediation["id"],
                f.close_remediation_payload("Adjudicated; nothing to refile."),
                officer_headers(),
            )
        )
        assert closed["state"] == REMEDIATION_CLOSED
        A.assert_version(closed, 3)
        undone = A.assert_ok(
            api.unmerge(
                merge_row["id"],
                f.unmerge_payload("Wrong survivor chosen."),
                steward_headers(STEWARD_2_USER_ID),
            )
        )
        assert undone["state"] == MERGE_UNMERGED
        A.assert_version(undone, 2)
        overlay = F.create_overlay(
            api, unrelated["id"], {"phone": "4105550303"}, 2, unrelated["version"],
            encounter_from_date="2026-07-01", encounter_to_date="2026-07-02",
        )
        applied = F.apply_overlay(api, overlay["id"])
        assert applied["state"] == OVERLAY_UNDER_CORRECTION
        A.assert_version(applied, 2)
        task = F.first_task_for_overlay(api, overlay["id"])
        assert task["state"] == TASK_QUEUED

        replayed_unmerge = api.unmerge(
            merge_row["id"],
            f.unmerge_payload("Replayed reversal."),
            steward_headers(STEWARD_2_USER_ID),
        )
        replayed_apply = api.apply_overlay(overlay["id"], steward_headers())
        replayed_quarantine = api.quarantine(
            remediation["id"], f.quarantine_payload(5), officer_headers()
        )
        replayed_ack = api.ack_task(task["id"], admin_headers())

        A.assert_error_envelope(replayed_unmerge, ERR_MERGE_INVALID_STATE, 409)
        frozen_merge = F.get_merge(api, merge_row["id"])
        A.assert_version(frozen_merge, 2)
        assert frozen_merge["unmerge_reason"] == "Wrong survivor chosen."
        A.assert_error_envelope(replayed_apply, ERR_OVERLAY_INVALID_STATE, 409)
        A.assert_version(F.get_overlay(api, overlay["id"]), 2)
        assert len(F.tasks_for_overlay(api, overlay["id"])) == 1
        A.assert_error_envelope(
            replayed_quarantine, ERR_REMEDIATION_INVALID_STATE, 409
        )
        frozen_remediation = F.get_remediation(api, remediation["id"])
        A.assert_integer(
            frozen_remediation["element_count_quarantined"], 30,
            "element_count_quarantined",
        )
        A.assert_version(frozen_remediation, 3)
        A.assert_error_envelope(replayed_ack, ERR_TASK_INVALID_STATE, 409)
        A.assert_version(F.get_task(api, task["id"]), 1)
        # PRD §3.6: "`merge_operation_id` is populated and `overlay_correction_id`
        # is null when the kind is `MERGE` or `UNMERGE`", and PRD §3.7 raises "one
        # fresh task with `operation_kind` of `UNMERGE` ... per downstream system
        # whose `status` is `ACTIVE`" alongside cancelling the original -- so the
        # merge owns two tasks after the reversal.
        merge_tasks = F.tasks_for_merge(api, merge_row["id"])
        assert len(merge_tasks) == 2
        cancelled = [
            row for row in merge_tasks if row["operation_kind"] == OPERATION_MERGE
        ]
        assert len(cancelled) == 1
        assert cancelled[0]["state"] == TASK_CANCELLED
        replacement = [
            row for row in merge_tasks if row["operation_kind"] == OPERATION_UNMERGE
        ]
        assert len(replacement) == 1
        assert replacement[0]["state"] == TASK_QUEUED
        restored = F.get_record(api, subsumed["id"])
        assert restored["identity_state"] == IDENTITY_ACTIVE
        A.assert_integer(
            restored["clinical_element_count"], 30, "clinical_element_count"
        )


class TestAuthenticationOutranksEverything:
    def test_a_missing_or_unknown_role_is_401_even_on_a_nonsense_path(self, api):
        """Rank 1 answers first, so neither the role check nor the lookup is reached.

        PRD §2.8: "`X-User-ID` and `X-User-Role` are both present and `X-User-Role` is
        one of the five declared roles — otherwise `ERR_UNAUTHENTICATED`, HTTP 401."

        PRD §2.8: "A later rule's condition is not even evaluated once an earlier one
        has failed."

        Design: Corner/errors/missing_x_user_role_header_returns_unauthenticated
        """
        site = F.create_site(
            api, "XC-SITE", name="Auth Clinic", region_code="US-RI",
            registrar_headcount=1,
        )

        no_role = api.get_site(site["id"], headers_without_role())
        unknown_role = api.create_site(
            f.site_payload(
                "XC-OTHER", name="Rejected Site", region_code="US-RI",
                registrar_headcount=1,
            ),
            make_headers("ChiefOfStaff", "admin-1"),
        )
        no_role_and_no_site = api.get_site(MISSING_ID, headers_without_role())

        A.assert_error_envelope(no_role, ERR_UNAUTHENTICATED, 401)
        A.assert_error_envelope(unknown_role, ERR_UNAUTHENTICATED, 401)
        A.assert_error_envelope(no_role_and_no_site, ERR_UNAUTHENTICATED, 401)
        readable = F.get_site(api, site["id"])
        assert readable["site_code"] == "XC-SITE"
        assert readable["name"] == "Auth Clinic"
        A.assert_version(readable, 1)
