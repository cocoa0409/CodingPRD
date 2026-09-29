"""Five peer roles, each with a write surface it cannot leave.

Every refusal here is checked together with the row it failed to touch, and the
two shared-operation cases confirm the peers really do overlap where the
contract says they do.
"""

import pytest

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as F
from test_helpers.api_errors import ERR_UNAUTHORIZED
from test_helpers.constants import (
    ATTRIBUTION_CREATION_SITE,
    ATTRIBUTION_SURVIVOR_SITE,
    CLASSIFICATION_POTENTIAL_DUPLICATE,
    IDENTITY_ACTIVE,
    INTEGRITY_CLEAR,
    INTEGRITY_FRAUD_SUSPECTED,
    INVESTIGATION_OPEN,
    OPENED_BY_OFFICER,
    OUTCOME_SAME_PERSON,
    OVERLAY_DETECTED,
    QUEUE_NEW,
    QUEUE_RECOMMENDED_MERGE,
    RECOMMENDATION_MERGE,
    RS_BASE_VERSION_LABEL,
    SCORE_VARIANT_STRICT,
    SCORE_VARIANT_TOLERANT,
    TRIGGER_MANUAL,
)
from test_helpers.test_users import (
    STEWARD_2_USER_ID,
    admin_headers,
    analyst_headers,
    officer_headers,
    registrar_headers,
    steward_headers,
)

RA_DEMOGRAPHICS = {
    "last_name": "Haddad",
    "first_name": "Nadia",
    "dob": "1983-01-19",
    "sex": "F",
}


class TestRegistrarSurface:
    def test_the_registrar_cannot_touch_the_duplicate_queue(self, api):
        """Search and registration are the whole of this role's write surface.

        PRD §2.1: "`SiteRegistrar` can search the index and create records at its own
        site and nothing else — it cannot create or rescore candidate pairs, attach
        evidence, recommend, approve, merge, unmerge, correct overlays, remediate
        contamination, open investigations, submit external matches, or run metrics."

        Design: Corner/rbac/site_registrar_cannot_work_the_duplicate_queue
        """
        site = F.create_site(
            api, "RA-SITE", name="Registrar Limits Clinic", region_code="US-NH",
            registrar_headcount=2,
        )
        rule_set = F.create_rule_set(api, activate=False)
        record_a = F.create_record(
            api, site["id"], "RA-1000", ssn_last4="1717", postal_code="03301",
            phone="6035550101", clinical_element_count=3, **RA_DEMOGRAPHICS
        )
        record_b = F.create_record(
            api, site["id"], "RA-2000", clinical_element_count=1, **RA_DEMOGRAPHICS
        )
        pair = F.create_pair(
            api, record_a["id"], record_b["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        assert pair["queue_state"] == QUEUE_NEW
        desk = registrar_headers(site["id"])

        refused_pair = api.create_pair(
            f.pair_payload(
                record_a["id"], record_b["id"], rule_set["id"], SCORE_VARIANT_TOLERANT
            ),
            desk,
        )
        refused_triage = api.triage_pair(
            pair["id"], f.triage_payload("Registrar attempting triage."), desk
        )
        refused_merge = api.create_merge(
            f.merge_payload(
                pair["id"], record_a["id"], record_b["id"],
                rationale="Registrar attempting approval.",
            ),
            desk,
        )

        A.assert_error_envelope(refused_pair, ERR_UNAUTHORIZED, 403)
        A.assert_error_envelope(refused_triage, ERR_UNAUTHORIZED, 403)
        A.assert_error_envelope(refused_merge, ERR_UNAUTHORIZED, 403)
        rows = A.list_rows(api.list_pairs(admin_headers()), expected_total=1)
        assert A.ids(rows) == [pair["id"]]
        untouched = F.get_pair(api, pair["id"])
        assert untouched["queue_state"] == QUEUE_NEW
        A.assert_version(untouched, 1)
        assert A.list_rows(api.list_merges(admin_headers()), expected_total=0) == []
        kept = F.get_record(api, record_a["id"])
        assert kept["identity_state"] == IDENTITY_ACTIVE
        A.assert_integer(kept["clinical_element_count"], 3, "clinical_element_count")
        other = F.get_record(api, record_b["id"])
        assert other["identity_state"] == IDENTITY_ACTIVE
        A.assert_integer(other["clinical_element_count"], 1, "clinical_element_count")


RB_DEMOGRAPHICS = {
    "last_name": "Petrosyan",
    "first_name": "Armen",
    "dob": "1969-12-24",
    "sex": "M",
    "ssn_last4": "2828",
    "postal_code": "05601",
    "phone": "8025550101",
}


class TestAnalystSurface:
    def test_the_analyst_cannot_approve_reverse_or_apply(self, api):
        """Detection and review are the analyst's half; execution is not.

        PRD §2.1: "`IdentityAnalyst` owns the detection and manual-review half of the
        workflow but cannot approve a merge, unmerge, resolve a pair as distinct, return
        a recommendation to review, apply or complete an overlay, reassign or close a
        remediation, adjudicate fraud, or configure sites, rule sets and downstream
        systems."

        Design: Corner/rbac/identity_analyst_cannot_approve_reverse_or_apply
        """
        site = F.create_site(
            api, "RB-SITE", name="Analyst Limits Clinic", region_code="US-VT",
            registrar_headcount=2,
        )
        rule_set = F.create_rule_set(api, activate=False)
        survivor = F.create_record(
            api, site["id"], "RB-1000", clinical_element_count=4, **RB_DEMOGRAPHICS
        )
        subsumed = F.create_record(
            api, site["id"], "RB-2000", clinical_element_count=2, **RB_DEMOGRAPHICS
        )
        pair = F.create_pair(
            api, survivor["id"], subsumed["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        assert pair["queue_state"] == QUEUE_RECOMMENDED_MERGE
        overlay = F.create_overlay(
            api, survivor["id"], {"phone": "8025550999"}, 1, survivor["version"],
            encounter_from_date="2026-07-05", encounter_to_date="2026-07-05",
            headers=analyst_headers(),
        )
        assert overlay["state"] == OVERLAY_DETECTED

        refused_merge = api.create_merge(
            f.merge_payload(
                pair["id"], survivor["id"], subsumed["id"],
                rationale="Analyst attempting approval.",
            ),
            analyst_headers(),
        )
        refused_distinct = api.resolve_distinct(
            pair["id"],
            f.resolve_distinct_payload("Analyst attempting resolution."),
            analyst_headers(),
        )
        refused_return = api.return_to_review(
            pair["id"],
            f.return_to_review_payload("Analyst attempting to return it."),
            analyst_headers(),
        )
        refused_apply = api.apply_overlay(overlay["id"], analyst_headers())

        A.assert_error_envelope(refused_merge, ERR_UNAUTHORIZED, 403)
        A.assert_error_envelope(refused_distinct, ERR_UNAUTHORIZED, 403)
        A.assert_error_envelope(refused_return, ERR_UNAUTHORIZED, 403)
        A.assert_error_envelope(refused_apply, ERR_UNAUTHORIZED, 403)
        frozen_pair = F.get_pair(api, pair["id"])
        assert frozen_pair["queue_state"] == QUEUE_RECOMMENDED_MERGE
        A.assert_version(frozen_pair, 1)
        frozen_overlay = F.get_overlay(api, overlay["id"])
        assert frozen_overlay["state"] == OVERLAY_DETECTED
        A.assert_version(frozen_overlay, 1)
        assert A.list_rows(api.list_merges(admin_headers()), expected_total=0) == []
        assert F.get_record(api, subsumed["id"])["identity_state"] == IDENTITY_ACTIVE


RC_DEMOGRAPHICS = {
    "last_name": "Delacroix",
    "first_name": "Margot",
    "dob": "1991-02-28",
    "sex": "F",
}


class TestApproverSurface:
    def test_the_approver_cannot_manufacture_the_recommendation_it_approves(self, api):
        """The duty split is enforced by role before any user identifier is compared.

        PRD §2.1: "`IdentityStewardApprover` owns the approval half and correspondingly
        cannot triage, start review, attach evidence or recommend, cannot create or
        rescore pairs, cannot adjudicate fraud, cannot quarantine, reassign or close
        remediations, and cannot configure sites, rule sets or downstream systems."

        Design: Corner/rbac/steward_approver_cannot_perform_the_analyst_half_of_the_duty_split
        """
        site = F.create_site(
            api, "RC-SITE", name="Steward Limits Clinic", region_code="US-ME",
            registrar_headcount=2,
        )
        rule_set = F.create_rule_set(api, activate=False)
        record_a = F.create_record(
            api, site["id"], "RC-1000", ssn_last4="3939", postal_code="04101",
            phone="2075550101", clinical_element_count=3, **RC_DEMOGRAPHICS
        )
        record_b = F.create_record(
            api, site["id"], "RC-2000", clinical_element_count=1, **RC_DEMOGRAPHICS
        )
        pair = F.create_pair(
            api, record_a["id"], record_b["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )

        refused_triage = api.triage_pair(
            pair["id"], f.triage_payload("Approver attempting triage."),
            steward_headers(),
        )
        refused_review = api.start_review(pair["id"], steward_headers())
        refused_evidence = api.add_evidence(
            pair["id"],
            f.evidence_payload(
                "PHOTO_ID", OUTCOME_SAME_PERSON, 5.00,
                note="Approver attempting evidence.",
            ),
            steward_headers(),
        )
        refused_recommend = api.recommend(
            pair["id"], f.recommend_payload(RECOMMENDATION_MERGE),
            steward_headers(STEWARD_2_USER_ID),
        )

        A.assert_error_envelope(refused_triage, ERR_UNAUTHORIZED, 403)
        A.assert_error_envelope(refused_review, ERR_UNAUTHORIZED, 403)
        A.assert_error_envelope(refused_evidence, ERR_UNAUTHORIZED, 403)
        A.assert_error_envelope(refused_recommend, ERR_UNAUTHORIZED, 403)
        frozen = F.get_pair(api, pair["id"])
        assert frozen["queue_state"] == QUEUE_NEW
        A.assert_version(frozen, 1)
        assert frozen["recommendation"] is None
        assert frozen["recommended_by_user_id"] is None
        rows, _ = A.assert_list_meta(
            api.list_evidence(pair["id"], steward_headers()), expected_total=0
        )
        assert rows == []


class TestPrivacyOfficerSurface:
    def test_the_privacy_officer_cannot_configure_the_platform(self, api):
        """Configuration is closed to the officer; fraud adjudication is not.

        PRD §2.1: "`PrivacyOfficer` owns fraud adjudication and clinical
        cross-contamination remediation and cannot create records or search attempts,
        cannot create, rescore, triage, review or recommend on pairs, cannot approve or
        reverse merges, cannot create, apply or complete overlay corrections, cannot
        submit external matches, and cannot configure sites, rule sets or downstream
        systems."

        Design: Corner/rbac/privacy_officer_cannot_configure_the_platform
        """
        site = F.create_site(
            api, "RD-SITE", name="Officer Limits Clinic", region_code="US-NH",
            registrar_headcount=2,
        )
        record = F.create_record(
            api, site["id"], "RD-1000", "Achterberg", "Joop", "1957-07-31", "M",
            ssn_last4="4040", postal_code="06103", phone="8605550101",
            clinical_element_count=2,
        )

        refused_site = api.create_site(
            f.site_payload("RD-OTHER", name="Officer's Own Desk", region_code="US-NH"),
            officer_headers(),
        )
        refused_patch = api.patch_site(
            site["id"], {"status": "SUSPENDED"}, officer_headers()
        )
        refused_rule_set = api.create_rule_set(
            f.rule_set_payload(name="Officer Rules", version_label="V-OFF-1"),
            officer_headers(),
        )
        refused_system = api.create_system(
            f.system_payload("RD-SYS", name="Officer's Consumer"), officer_headers()
        )

        A.assert_error_envelope(refused_site, ERR_UNAUTHORIZED, 403)
        A.assert_error_envelope(refused_patch, ERR_UNAUTHORIZED, 403)
        A.assert_error_envelope(refused_rule_set, ERR_UNAUTHORIZED, 403)
        A.assert_error_envelope(refused_system, ERR_UNAUTHORIZED, 403)
        untouched = F.get_site(api, site["id"])
        assert untouched["status"] == "ACTIVE"
        A.assert_version(untouched, 1)

        accepted = A.assert_created(
            api.create_investigation(
                f.investigation_payload(
                    record["id"], TRIGGER_MANUAL,
                    note="Presented insurance card does not match the chart.",
                ),
                officer_headers(),
            )
        )

        assert accepted["state"] == INVESTIGATION_OPEN
        assert accepted["opened_by"] == OPENED_BY_OFFICER
        assert accepted["opened_by_user_id"] == "officer-1"
        assert F.get_record(api, record["id"])["integrity_state"] == (
            INTEGRITY_FRAUD_SUSPECTED
        )
        A.assert_site_counters(
            F.get_site(api, site["id"]), active_record_count=1, flagged_record_count=1
        )


class TestAdministratorSurface:
    def test_the_administrator_cannot_register_patients_or_adjudicate_fraud(self, api):
        """Owning configuration is not the same as owning the clinical workflow.

        PRD §2.1: "`MpiAdmin` in particular is **not** a superset of the others: an
        administrator owns configuration and propagation but cannot create a patient
        record, cannot triage or recommend on a candidate pair, cannot approve a merge,
        cannot resolve a pair as distinct, cannot create, apply or complete an overlay
        correction, cannot remediate contamination, cannot adjudicate fraud, and cannot
        submit an external match."

        Design: Corner/rbac/mpi_admin_cannot_register_patients_or_adjudicate_fraud
        """
        site = F.create_site(
            api, "RE-SITE", name="Admin Limits Clinic", region_code="US-NJ",
            registrar_headcount=3,
        )
        F.create_rule_set(api, activate=True)
        record = F.create_record(
            api, site["id"], "RE-1000", "Wijeratne", "Dilani", "1993-06-06", "F",
            ssn_last4="5151", postal_code="07102", phone="9735550101",
            clinical_element_count=2,
        )

        refused_record = api.create_record(
            f.record_payload(
                site["id"], "RE-2000", "Wijeratne", "Dilani", "1993-06-06", "F",
                clinical_element_count=1,
            ),
            admin_headers(),
        )
        refused_search = api.create_search_attempt(
            site["id"],
            f.search_attempt_payload(
                "Wijeratne", searched_first_name="Dilani", searched_dob="1993-06-06",
                searched_sex="F",
            ),
            admin_headers(),
        )
        refused_investigation = api.create_investigation(
            f.investigation_payload(
                record["id"], TRIGGER_MANUAL, note="Administrator suspects fraud."
            ),
            admin_headers(),
        )
        refused_probe = api.create_external_match(
            f.external_match_payload(
                record["id"], "HIE-NJ", True,
                {
                    "last_name": "Wijeratne",
                    "first_name": "Dilani",
                    "dob": "1993-06-06",
                    "sex": "F",
                },
            ),
            admin_headers(),
        )

        A.assert_error_envelope(refused_record, ERR_UNAUTHORIZED, 403)
        A.assert_error_envelope(refused_search, ERR_UNAUTHORIZED, 403)
        A.assert_error_envelope(refused_investigation, ERR_UNAUTHORIZED, 403)
        A.assert_error_envelope(refused_probe, ERR_UNAUTHORIZED, 403)
        rows = A.list_rows(
            api.list_records(admin_headers(), {"site_id": site["id"]}),
            expected_total=1,
        )
        assert A.mrns(rows) == ["RE-1000"]
        A.assert_site_counters(
            F.get_site(api, site["id"]), active_record_count=1, flagged_record_count=0
        )
        assert A.list_rows(
            api.list_search_attempts(site["id"], analyst_headers()), expected_total=0
        ) == []
        assert A.list_rows(
            api.list_investigations(officer_headers()), expected_total=0
        ) == []
        assert A.list_rows(
            api.list_external_matches(analyst_headers()), expected_total=0
        ) == []
        assert F.get_record(api, record["id"])["integrity_state"] == INTEGRITY_CLEAR


RF_DEMOGRAPHICS = {
    "last_name": "Grabowski",
    "first_name": "Irena",
    "dob": "1965-11-02",
    "sex": "F",
}


class TestSharedOperations:
    def test_the_analyst_and_the_administrator_share_both_ends_of_a_shared_endpoint(
        self, api
    ):
        """The administrator opens the pair, the analyst rescores it, and both publish metrics.

        PRD §4: "| POST | `/mpi/candidate-pairs` | Score two records under one rule set
        and place the pair on the triage queue | `IdentityAnalyst`, `MpiAdmin` |"

        PRD §3.9: "An `MpiAdmin` or an `IdentityAnalyst` runs a metric for a site over a
        closed date window, supplying `window_start_date`, `window_end_date` — no
        earlier than the start — and an `attribution_variant`."

        Design: Corner/rbac/shared_operations_accept_either_declared_role
        """
        F.pin_clock(api, "2026-08-01T00:00:00Z")
        site = F.create_site(
            api, "RF-SITE", name="Shared Ops Clinic", region_code="US-NY",
            registrar_headcount=3,
        )
        rule_set = F.create_rule_set(api, activate=True)
        record_a = F.create_record(
            api, site["id"], "RF-1000", ssn_last4="6363", postal_code="10001",
            phone="2125550101", clinical_element_count=3, **RF_DEMOGRAPHICS
        )
        record_b = F.create_record(
            api, site["id"], "RF-2000", clinical_element_count=1, **RF_DEMOGRAPHICS
        )
        F.pin_clock(api, "2026-08-15T00:00:00Z")

        opened_by_admin = A.assert_created(
            api.create_pair(
                f.pair_payload(
                    record_a["id"], record_b["id"], rule_set["id"],
                    SCORE_VARIANT_STRICT,
                ),
                admin_headers(),
            )
        )
        rescored_by_analyst = A.assert_ok(
            api.rescore_pair(
                opened_by_admin["id"],
                f.rescore_payload(
                    rule_set["id"], score_variant=SCORE_VARIANT_TOLERANT,
                    expected_pair_version=opened_by_admin["version"],
                ),
                analyst_headers(),
            )
        )
        analyst_run = A.assert_created(
            F.run_metric(
                api, site["id"], "2026-08-01", "2026-08-10",
                attribution_variant=ATTRIBUTION_CREATION_SITE,
                headers=analyst_headers(),
            )
        )
        admin_run = A.assert_created(
            F.run_metric(
                api, site["id"], "2026-08-01", "2026-08-10",
                attribution_variant=ATTRIBUTION_SURVIVOR_SITE,
                headers=admin_headers(),
            )
        )

        A.assert_score(opened_by_admin["match_score"], 70.00, "match_score")
        assert opened_by_admin["classification"] == CLASSIFICATION_POTENTIAL_DUPLICATE
        assert opened_by_admin["queue_state"] == QUEUE_NEW
        assert rescored_by_analyst["score_variant"] == SCORE_VARIANT_TOLERANT
        A.assert_score(rescored_by_analyst["match_score"], 77.50, "match_score")
        assert rescored_by_analyst["classification"] == (
            CLASSIFICATION_POTENTIAL_DUPLICATE
        )
        A.assert_version(rescored_by_analyst, 2)
        assert analyst_run["attribution_variant"] == ATTRIBUTION_CREATION_SITE
        A.assert_integer(analyst_run["records_created"], 2, "records_created")
        A.assert_integer(
            analyst_run["confirmed_duplicates"], 0, "confirmed_duplicates"
        )
        A.assert_integer(analyst_run["duplicate_rate_bps"], 0, "duplicate_rate_bps")
        assert analyst_run["sample_size_sufficient"] is False
        assert analyst_run["rule_set_version_label"] == RS_BASE_VERSION_LABEL
        assert admin_run["attribution_variant"] == ATTRIBUTION_SURVIVOR_SITE
        A.assert_integer(admin_run["records_created"], 2, "records_created")
        rows = A.list_rows(
            api.list_metric_runs(site["id"], admin_headers()), expected_total=2
        )
        assert len(rows) == 2
        for row in rows:
            assert "version" not in row

    def test_all_five_roles_read_the_same_record_payload(self, api):
        """The registrar's site scope constrains writes, never reads.

        PRD §2.1: "All five roles may read every retrieval endpoint."

        PRD §2.1: "Ownership checks therefore compare a resource's site reference to
        `X-User-ID` directly: when a `SiteRegistrar` records a registration search, the
        site named by the `{id}` path segment must equal `X-User-ID`, and when a
        `SiteRegistrar` creates a patient record, the body's `site_id` must equal
        `X-User-ID`."

        Design: Corner/rbac/every_declared_role_can_read_a_patient_record
        """
        site_a = F.create_site(
            api, "RG-SITE-A", name="Reader Clinic A", region_code="US-PA",
            registrar_headcount=2,
        )
        site_b = F.create_site(
            api, "RG-SITE-B", name="Reader Clinic B", region_code="US-PA",
            registrar_headcount=2,
        )
        record = F.create_record(
            api, site_a["id"], "RG-1000", "Szymanski", "Pawel", "1972-09-14", "M",
            ssn_last4="7474", postal_code="19104", phone="2155550101",
            clinical_element_count=5,
        )

        views = [
            A.assert_ok(api.get_record(record["id"], headers))
            for headers in (
                registrar_headers(site_b["id"]),
                analyst_headers(),
                steward_headers(),
                officer_headers(),
                admin_headers(),
            )
        ]

        assert len(views) == 5
        for view in views:
            assert view["id"] == record["id"]
            assert view["mrn"] == "RG-1000"
            assert view["enterprise_id"] == record["enterprise_id"]
            assert view["identity_state"] == IDENTITY_ACTIVE
            assert view["integrity_state"] == INTEGRITY_CLEAR
            assert view == views[0]
        A.assert_site_counters(F.get_site(api, site_a["id"]), active_record_count=1)
        A.assert_site_counters(F.get_site(api, site_b["id"]), active_record_count=0)
