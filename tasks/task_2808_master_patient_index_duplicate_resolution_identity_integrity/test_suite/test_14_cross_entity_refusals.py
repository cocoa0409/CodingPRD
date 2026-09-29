"""Refusals a request earns from the condition of some other row.

Merge membership, record and site condition, exchange consent and the duty
split between the analyst who recommends and the approver who executes.
"""

import pytest

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as F
from test_helpers.api_errors import (
    ERR_EXCHANGE_CONSENT_MISSING,
    ERR_PAIR_RECORD_MISMATCH,
    ERR_RECORD_NOT_ACTIVE,
    ERR_RECORD_REMEDIATION_PENDING,
    ERR_RECORD_UNDER_FRAUD_HOLD,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SITE_SUSPENDED,
)
from test_helpers.constants import (
    EXTERNAL_MATCHED,
    EXTERNAL_NO_MATCH,
    IDENTITY_ACTIVE,
    IDENTITY_MERGED_SUBSUMED,
    INTEGRITY_CLEAR,
    INTEGRITY_FRAUD_SUSPECTED,
    INTEGRITY_REMEDIATION_PENDING,
    INVESTIGATION_OPEN,
    MERGE_COMPLETED,
    OVERLAY_CLINICAL_MISFILE,
    OVERLAY_DETECTED,
    QUEUE_RECOMMENDED_MERGE,
    QUEUE_RESOLVED_MERGED,
    RECOMMENDATION_MERGE,
    SCORE_VARIANT_STRICT,
    TRIGGER_MANUAL,
)
from test_helpers.test_users import (
    admin_headers,
    analyst_headers,
    officer_headers,
    steward_headers,
)

V8_DEMOGRAPHICS = {
    "last_name": "Mbeki",
    "first_name": "Thandiwe",
    "dob": "1990-02-11",
    "sex": "F",
    "ssn_last4": "3030",
    "postal_code": "30303",
    "phone": "4045550101",
}

V9_DEMOGRAPHICS = {
    "last_name": "Delgado",
    "first_name": "Rosalia",
    "dob": "1965-03-03",
    "sex": "F",
    "ssn_last4": "4141",
    "postal_code": "33101",
    "phone": "3055550101",
}


class TestMergeMemberAgreement:
    def test_naming_a_third_record_as_the_subsumed_side_is_refused(self, api):
        """Merge authority comes from the pair, not from the approver's choice.

        PRD §2.8: "The unordered set of `survivor_record_id` and
        `subsumed_record_id` equals the unordered set of the pair's `record_a_id` and
        `record_b_id` — otherwise `ERR_PAIR_RECORD_MISMATCH`, HTTP 422."

        Design: Corner/validations/merging_a_record_outside_the_pair_returns_pair_record_mismatch
        """
        site = F.create_site(
            api, "SITE-V8", name="Mismatch Clinic", region_code="US-GA",
            registrar_headcount=3,
        )
        rule_set = F.create_rule_set(api, activate=False)
        record_a = F.create_record(
            api, site["id"], "V8-1000", clinical_element_count=4, **V8_DEMOGRAPHICS
        )
        record_b = F.create_record(
            api, site["id"], "V8-2000", clinical_element_count=2, **V8_DEMOGRAPHICS
        )
        outsider = F.create_record(
            api, site["id"], "V8-3000", clinical_element_count=1, **V8_DEMOGRAPHICS
        )
        pair = F.create_pair(
            api, record_a["id"], record_b["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        assert pair["queue_state"] == QUEUE_RECOMMENDED_MERGE
        assert pair["recommended_by_user_id"] is None

        response = api.create_merge(
            f.merge_payload(
                pair["id"], record_a["id"], outsider["id"],
                rationale="Wrong third record named as the subsumed side.",
            ),
            steward_headers(),
        )

        A.assert_error_envelope(response, ERR_PAIR_RECORD_MISMATCH, 422)
        assert A.list_rows(api.list_merges(admin_headers()), expected_total=0) == []
        unchanged = F.get_pair(api, pair["id"])
        assert unchanged["queue_state"] == QUEUE_RECOMMENDED_MERGE
        A.assert_version(unchanged, 1)
        untouched = F.get_record(api, outsider["id"])
        assert untouched["identity_state"] == IDENTITY_ACTIVE
        A.assert_integer(
            untouched["clinical_element_count"], 1, "clinical_element_count"
        )


class TestRecordConditionGuards:
    def test_an_already_subsumed_record_cannot_be_merged_a_second_time(self, api):
        """Scoring tolerates an absorbed record; the merge endpoint does not.

        PRD §2.8: "Every patient record in scope has `identity_state` of `ACTIVE` —
        otherwise `ERR_RECORD_NOT_ACTIVE`, HTTP 409."

        Design: Corner/validations/merging_an_already_subsumed_record_returns_record_not_active
        """
        site = F.create_site(
            api, "SITE-V9", name="Not Active Clinic", region_code="US-FL",
            registrar_headcount=3,
        )
        rule_set = F.create_rule_set(api, activate=False)
        survivor = F.create_record(
            api, site["id"], "V9-1000", clinical_element_count=3, **V9_DEMOGRAPHICS
        )
        subsumed = F.create_record(
            api, site["id"], "V9-2000", clinical_element_count=2, **V9_DEMOGRAPHICS
        )
        third = F.create_record(
            api, site["id"], "V9-3000", clinical_element_count=1, **V9_DEMOGRAPHICS
        )
        first_pair = F.create_pair(
            api, survivor["id"], subsumed["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        F.merge(
            api, first_pair["id"], survivor["id"], subsumed["id"],
            rationale="First merge.",
        )
        second_pair = F.create_pair(
            api, subsumed["id"], third["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        A.assert_score(second_pair["match_score"], 100.00, "match_score")

        response = api.create_merge(
            f.merge_payload(
                second_pair["id"], third["id"], subsumed["id"],
                rationale="Attempting to re-merge a subsumed record.",
            ),
            steward_headers(),
        )

        A.assert_error_envelope(response, ERR_RECORD_NOT_ACTIVE, 409)
        rows = A.list_rows(api.list_merges(admin_headers()), expected_total=1)
        assert len(rows) == 1
        absorbed = F.get_record(api, subsumed["id"])
        assert absorbed["identity_state"] == IDENTITY_MERGED_SUBSUMED
        assert absorbed["survivor_record_id"] == survivor["id"]
        spared = F.get_record(api, third["id"])
        A.assert_integer(spared["clinical_element_count"], 1, "clinical_element_count")
        A.assert_integer(spared["subsumed_member_count"], 0, "subsumed_member_count")
        assert F.get_pair(api, second_pair["id"])["queue_state"] == (
            QUEUE_RECOMMENDED_MERGE
        )

    def test_a_suspended_desk_cannot_register_until_it_is_reactivated(self, api):
        """The identical body is refused and then accepted as the site status moves.

        PRD §2.8: "The registration site in scope has `status` of `ACTIVE` —
        otherwise `ERR_SITE_SUSPENDED`, HTTP 409."

        Design: Corner/validations/registering_at_a_suspended_site_returns_site_suspended
        """
        site = F.create_site(
            api, "SITE-VA", name="Suspended Clinic", region_code="US-WV",
            registrar_headcount=2,
        )
        suspended = A.assert_ok(
            api.patch_site(site["id"], {"status": "SUSPENDED"}, admin_headers())
        )
        assert suspended["status"] == "SUSPENDED"
        A.assert_version(suspended, 2)
        payload = f.record_payload(
            site["id"], "VA-1000", "Novotny", "Petra", "1982-08-28", "F",
            clinical_element_count=1,
        )

        refused = api.create_record(payload, analyst_headers())
        A.assert_ok(api.patch_site(site["id"], {"status": "ACTIVE"}, admin_headers()))
        accepted = api.create_record(payload, analyst_headers())

        A.assert_error_envelope(refused, ERR_SITE_SUSPENDED, 409)
        created = A.assert_created(accepted)
        assert created["mrn"] == "VA-1000"
        assert created["identity_state"] == IDENTITY_ACTIVE
        reopened = F.get_site(api, site["id"])
        assert reopened["status"] == "ACTIVE"
        A.assert_site_counters(reopened, active_record_count=1, flagged_record_count=0)


VB_DEMOGRAPHICS = {
    "last_name": "Sarkisian",
    "first_name": "Vahan",
    "dob": "1970-10-30",
    "sex": "M",
    "ssn_last4": "6060",
    "postal_code": "70112",
    "phone": "5045550101",
}


class TestExchangeEligibility:
    def test_an_open_investigation_freezes_the_record_for_the_exchange(self, api):
        """Consent and an ACTIVE identity are not enough while a fraud hold stands.

        PRD §2.8: "No patient record in scope has `integrity_state` of
        `FRAUD_SUSPECTED` or `FRAUD_CONFIRMED` — otherwise
        `ERR_RECORD_UNDER_FRAUD_HOLD`, HTTP 409."

        Design: Corner/validations/external_match_on_a_fraud_held_record_returns_record_under_fraud_hold
        """
        site = F.create_site(
            api, "SITE-VB", name="Fraud Hold Clinic", region_code="US-LA",
            registrar_headcount=2,
        )
        F.create_rule_set(api, activate=True)
        record = F.create_record(
            api, site["id"], "VB-1000", clinical_element_count=5, **VB_DEMOGRAPHICS
        )
        investigation = F.open_manual_investigation(
            api, record["id"], TRIGGER_MANUAL,
            note="Conflicting insurance cards on file.",
        )
        assert investigation["state"] == INVESTIGATION_OPEN
        assert F.get_record(api, record["id"])["integrity_state"] == (
            INTEGRITY_FRAUD_SUSPECTED
        )
        payload = f.external_match_payload(
            record["id"], "HIE-GULF", True, dict(VB_DEMOGRAPHICS)
        )

        refused = api.create_external_match(payload, analyst_headers())
        A.assert_error_envelope(refused, ERR_RECORD_UNDER_FRAUD_HOLD, 409)
        assert A.list_rows(
            api.list_external_matches(admin_headers()), expected_total=0
        ) == []
        A.assert_ok(
            api.unsubstantiate(
                investigation["id"],
                f.unsubstantiate_payload(
                    "Cards belonged to the patient across two employers."
                ),
                officer_headers(),
            )
        )
        accepted = api.create_external_match(payload, analyst_headers())

        probe = A.assert_created(accepted)
        A.assert_score(probe["external_score"], 100.00, "external_score")
        assert probe["state"] == EXTERNAL_MATCHED
        released = F.get_record(api, record["id"])
        assert released["integrity_state"] == INTEGRITY_CLEAR
        assert released["identity_state"] == IDENTITY_ACTIVE

    def test_an_open_correction_blocks_the_exchange_with_its_own_error(self, api):
        """No investigation exists, so the lower-ranked remediation rule is the one heard.

        PRD §2.8: "The target patient record's `integrity_state` is not
        `REMEDIATION_PENDING` — otherwise `ERR_RECORD_REMEDIATION_PENDING`, HTTP 409."

        Design: Corner/validations/external_match_on_a_remediation_pending_record_returns_record_remediation_pending
        """
        site = F.create_site(
            api, "SITE-VC", name="Remediation Hold Clinic", region_code="US-OK",
            registrar_headcount=2,
        )
        F.create_rule_set(api, activate=True)
        record = F.create_record(
            api, site["id"], "VC-1000", "Bouazizi", "Salma", "1988-04-08", "F",
            ssn_last4="7171", postal_code="73102", phone="4055550101",
            clinical_element_count=6,
        )
        overlay = F.create_overlay(
            api, record["id"], {"first_name": "Selma"}, 2, record["version"],
            overlay_type=OVERLAY_CLINICAL_MISFILE,
        )
        assert overlay["state"] == OVERLAY_DETECTED

        response = api.create_external_match(
            f.external_match_payload(
                record["id"], "HIE-PLAINS", True,
                {
                    "last_name": "Bouazizi",
                    "first_name": "Salma",
                    "dob": "1988-04-08",
                    "sex": "F",
                },
            ),
            analyst_headers(),
        )

        A.assert_error_envelope(response, ERR_RECORD_REMEDIATION_PENDING, 409)
        assert A.list_rows(
            api.list_external_matches(admin_headers()), expected_total=0
        ) == []
        held = F.get_record(api, record["id"])
        assert held["integrity_state"] == INTEGRITY_REMEDIATION_PENDING
        A.assert_version(held, 2)
        assert A.list_rows(api.list_investigations(officer_headers())) == []

    def test_a_probe_without_consent_is_refused_and_succeeds_once_consent_is_stated(
        self, api
    ):
        """The only difference between the two calls is the consent boolean.

        PRD §2.8: "`consent_on_file` is true — otherwise
        `ERR_EXCHANGE_CONSENT_MISSING`, HTTP 403."

        Design: Corner/validations/external_match_without_consent_returns_exchange_consent_missing
        """
        site = F.create_site(
            api, "SITE-VD", name="Consent Clinic", region_code="US-KY",
            registrar_headcount=2,
        )
        F.create_rule_set(api, activate=True)
        record = F.create_record(
            api, site["id"], "VD-1000", "Ferraro", "Luca", "1996-01-06", "M",
            ssn_last4="8181", postal_code="40202", phone="5025550101",
            clinical_element_count=2,
        )
        partner_view = {
            "last_name": "Ferraro",
            "first_name": "Luca",
            "dob": "1996-01-06",
            "sex": "M",
        }

        refused = api.create_external_match(
            f.external_match_payload(
                record["id"], "HIE-BLUEGRASS", False, partner_view
            ),
            analyst_headers(),
        )
        accepted = api.create_external_match(
            f.external_match_payload(
                record["id"], "HIE-BLUEGRASS", True, partner_view
            ),
            analyst_headers(),
        )

        A.assert_error_envelope(refused, ERR_EXCHANGE_CONSENT_MISSING, 403)
        probe = A.assert_created(accepted)
        assert probe["consent_on_file"] is True
        A.assert_score(probe["external_score"], 77.50, "external_score")
        assert probe["state"] == EXTERNAL_NO_MATCH
        rows = A.list_rows(
            api.list_external_matches(admin_headers(), {"record_id": record["id"]}),
            expected_total=1,
        )
        assert len(rows) == 1


class TestDutySeparation:
    def test_the_recommending_operator_cannot_approve_the_merge_they_asked_for(
        self, api
    ):
        """A different approver sends the identical body straight through.

        PRD §2.8: "`X-User-ID` differs from the pair's `recommended_by_user_id` —
        otherwise `ERR_SEGREGATION_OF_DUTIES`, HTTP 403. The check is vacuously
        satisfied when `recommended_by_user_id` is null."

        Design: Corner/validations/approving_a_merge_you_recommended_returns_segregation_of_duties
        """
        site = F.create_site(
            api, "SITE-VE", name="Duties Clinic", region_code="US-IN",
            registrar_headcount=3,
        )
        rule_set = F.create_rule_set(api, activate=False)
        survivor = F.create_record(
            api, site["id"], "VE-1000", "Duguay", "Camille", "1975-09-27", "F",
            ssn_last4="9191", postal_code="46204", phone="3175550101",
            clinical_element_count=4,
        )
        subsumed = F.create_record(
            api, site["id"], "VE-2000", "Duguay", "Camille", "1975-09-27", "F",
            clinical_element_count=2,
        )
        pair = F.create_pair(
            api, survivor["id"], subsumed["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        recommended = F.ladder_to_recommendation(
            api, pair["id"], RECOMMENDATION_MERGE,
            headers=analyst_headers("user-9"),
        )
        assert recommended["recommended_by_user_id"] == "user-9"
        A.assert_score(recommended["effective_score"], 72.00, "effective_score")
        A.assert_version(recommended, 6)
        payload = f.merge_payload(
            pair["id"], survivor["id"], subsumed["id"],
            rationale="Approval of the recommended merge.",
        )

        refused = api.create_merge(payload, steward_headers("user-9"))
        A.assert_error_envelope(refused, ERR_SEGREGATION_OF_DUTIES, 403)
        assert A.list_rows(api.list_merges(admin_headers()), expected_total=0) == []
        still_open = F.get_pair(api, pair["id"])
        assert still_open["queue_state"] == QUEUE_RECOMMENDED_MERGE
        A.assert_version(still_open, 6)

        accepted = api.create_merge(payload, steward_headers())

        merge_row = A.assert_created(accepted)
        assert merge_row["state"] == MERGE_COMPLETED
        assert merge_row["approved_by_user_id"] == "steward-1"
        A.assert_integer(
            merge_row["moved_clinical_element_count"], 2,
            "moved_clinical_element_count",
        )
        resolved = F.get_pair(api, pair["id"])
        assert resolved["queue_state"] == QUEUE_RESOLVED_MERGED
        assert resolved["approved_by_user_id"] == "steward-1"
        A.assert_version(resolved, 7)
        A.assert_integer(
            F.get_record(api, survivor["id"])["clinical_element_count"], 6,
            "clinical_element_count",
        )
        assert F.get_record(api, subsumed["id"])["identity_state"] == (
            IDENTITY_MERGED_SUBSUMED
        )
