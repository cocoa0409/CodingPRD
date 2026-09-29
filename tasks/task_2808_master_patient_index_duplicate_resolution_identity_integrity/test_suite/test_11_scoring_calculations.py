"""Per-attribute credit, the conflict penalty and the variant the exchange picks."""

import pytest

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as F
from test_helpers.constants import (
    CLASSIFICATION_NON_DUPLICATE,
    CLASSIFICATION_POTENTIAL_DUPLICATE,
    CONFLICT_BIOMETRIC,
    CONFLICT_INSURANCE,
    CONFLICT_SSN4,
    EXTERNAL_MATCHED,
    IDENTITY_ACTIVE,
    INTEGRITY_CLEAR,
    QUEUE_NEW,
    SCORE_VARIANT_STRICT,
)
from test_helpers.test_users import admin_headers, analyst_headers, officer_headers


class TestPartialAgreementCredit:
    def test_a_shared_three_character_prefix_pays_exactly_half_the_weight(self, api):
        """last_name and postal_code earn half credit; phone is all-or-nothing.

        PRD §3.3: "Where both sides have a value: `last_name` and `first_name` each
        score full agreement of 1 when the two values are equal, half agreement of 0.5
        when their first three characters are equal but the full values differ, and no
        agreement of 0 otherwise."

        Design: Corner/calculations/prefix_agreement_awards_exactly_half_the_attribute_weight
        """
        site = F.create_site(
            api, "SITE-C1", name="Prefix Agreement Clinic", region_code="US-NE",
            registrar_headcount=2,
        )
        rule_set = F.create_rule_set(api, activate=False)
        record_a = F.create_record(
            api, site["id"], "C1-1000", "Brannigan", "Colette", "1983-05-14", "F",
            ssn_last4="7788", postal_code="68102", phone="4025550101",
            clinical_element_count=3,
        )
        record_b = F.create_record(
            api, site["id"], "C1-2000", "Brandeis", "Colette", "1983-05-14", "F",
            ssn_last4="7788", postal_code="68155", phone="4025550202",
            clinical_element_count=2,
        )

        pair = A.assert_created(
            api.create_pair(
                f.pair_payload(
                    record_a["id"], record_b["id"], rule_set["id"],
                    SCORE_VARIANT_STRICT,
                ),
                analyst_headers(),
            )
        )

        A.assert_breakdown(
            pair["attribute_score_breakdown"],
            {
                "last_name": 12.50,
                "first_name": 15.00,
                "dob": 25.00,
                "ssn_last4": 15.00,
                "sex": 5.00,
                "postal_code": 5.00,
                "phone": 0.00,
            },
        )
        A.assert_score(pair["raw_score"], 77.50, "raw_score")
        A.assert_score(pair["match_score"], 77.50, "match_score")
        assert pair["conflict_flags"] == []
        assert pair["classification"] == CLASSIFICATION_POTENTIAL_DUPLICATE
        assert pair["queue_state"] == QUEUE_NEW
        assert pair["base_band"] == "P2"
        A.assert_score(pair["effective_score"], 77.50, "effective_score")
        assert pair["priority_band"] == "P2"
        assert pair["subject_record_mrn"] == "C1-2000"

    def test_a_day_month_transposition_pays_half_the_dob_weight(self, api):
        """The 12.50 shortfall is exactly what keeps the pair out of AUTO_LINK.

        PRD §3.3: "`dob` has three ways to earn credit: full agreement of 1 when the
        two `YYYY-MM-DD` values are equal; half agreement of 0.5 when the year and
        month parts are equal but the day parts differ; and also half agreement of 0.5
        when the two dates are a day-and-month transposition of one another, meaning
        the years are equal, the first date's month equals the second date's day, the
        first date's day equals the second date's month, and the first date's month and
        day are not themselves equal."

        Design: Corner/calculations/dob_day_month_transposition_scores_half_agreement
        """
        site = F.create_site(
            api, "SITE-C2", name="Transposition Clinic", region_code="US-AZ",
            registrar_headcount=2,
        )
        rule_set = F.create_rule_set(api, activate=False)
        record_a = F.create_record(
            api, site["id"], "C2-1000", "Vasquez", "Ramona", "1985-03-07", "F",
            ssn_last4="4455", postal_code="85001", clinical_element_count=4,
        )
        record_b = F.create_record(
            api, site["id"], "C2-2000", "Vasquez", "Ramona", "1985-07-03", "F",
            ssn_last4="4455", postal_code="85001", clinical_element_count=1,
        )

        pair = F.create_pair(
            api, record_a["id"], record_b["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )

        A.assert_breakdown(
            pair["attribute_score_breakdown"],
            {
                "last_name": 25.00,
                "first_name": 15.00,
                "dob": 12.50,
                "ssn_last4": 15.00,
                "sex": 5.00,
                "postal_code": 10.00,
                "phone": 0.00,
            },
        )
        A.assert_score(pair["raw_score"], 82.50, "raw_score")
        A.assert_score(pair["match_score"], 82.50, "match_score")
        assert pair["classification"] == CLASSIFICATION_POTENTIAL_DUPLICATE
        assert pair["queue_state"] == QUEUE_NEW
        assert pair["base_band"] == "P2"
        assert pair["priority_band"] == "P2"


class TestConflictPenalty:
    def test_the_penalty_is_multiplied_by_the_number_of_flags(self, api):
        """Two flags cost 24.00, not one flat 12.00 charge.

        PRD §3.3: "`match_score` is `raw_score` reduced by the rule set's
        `conflict_penalty_points` multiplied by the number of entries in
        `conflict_flags`, floored at 0.00 so the score never goes negative, and rounded
        half up to two decimal places."

        Design: Corner/calculations/conflict_penalty_is_charged_once_per_conflict_flag
        """
        site = F.create_site(
            api, "SITE-C3", name="Conflict Penalty Clinic", region_code="US-IL",
            registrar_headcount=4,
        )
        rule_set = F.create_rule_set(api, activate=False)
        record_a = F.create_record(
            api, site["id"], "C3-1000", "Okonkwo", "Chidi", "1990-11-02", "M",
            ssn_last4="1234", postal_code="60601", phone="3125550101",
            insurance_member_id="INS-A", clinical_element_count=5,
        )
        record_b = F.create_record(
            api, site["id"], "C3-2000", "Okonkwo", "Chidi", "1975-06-23", "M",
            ssn_last4="5678", postal_code="60601", phone="3125550101",
            insurance_member_id="INS-B", clinical_element_count=2,
        )

        pair = F.create_pair(
            api, record_a["id"], record_b["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )

        A.assert_score(pair["raw_score"], 60.00, "raw_score")
        assert pair["conflict_flags"] == [CONFLICT_SSN4, CONFLICT_INSURANCE]
        A.assert_score(pair["match_score"], 36.00, "match_score")
        assert pair["classification"] == CLASSIFICATION_NON_DUPLICATE
        assert pair["base_band"] == "P3"
        assert pair["priority_band"] == "P3"
        assert pair["queue_state"] == QUEUE_NEW
        assert A.list_rows(api.list_investigations(officer_headers())) == []
        assert F.get_record(api, record_a["id"])["integrity_state"] == INTEGRITY_CLEAR
        assert F.get_record(api, record_b["id"])["integrity_state"] == INTEGRITY_CLEAR

    def test_the_penalty_cannot_drive_the_score_below_zero(self, api):
        """Three flags cost 36.00 against a raw 25.00 and the floor reports 0.00.

        PRD §3.3: "Three demographic contradictions are recognised, and
        `conflict_flags` lists whichever of them apply, always emitted in this fixed
        order: `SSN4_CONFLICT` when both sides have a non-null `ssn_last4` and the two
        values differ; `BIOMETRIC_CONFLICT` when both sides have a non-null
        `biometric_template_hash` and the two hashes differ; and `INSURANCE_CONFLICT`
        when both sides have a non-null `insurance_member_id` and the two identifiers
        differ."

        Design: Corner/calculations/conflict_penalty_floors_match_score_at_zero
        """
        site = F.create_site(
            api, "SITE-C4", name="Score Floor Clinic", region_code="US-NY",
            registrar_headcount=6,
        )
        rule_set = F.create_rule_set(api, activate=False)
        record_a = F.create_record(
            api, site["id"], "C4-1000", "Lindqvist", "Anna", "1980-01-01", "F",
            ssn_last4="1111", postal_code="10001", phone="2125550101",
            biometric_template_hash="BIO-1", insurance_member_id="INS-1",
            clinical_element_count=6,
        )
        record_b = F.create_record(
            api, site["id"], "C4-2000", "Lindqvist", "Teodor", "1955-12-31", "M",
            ssn_last4="2222", postal_code="99501", phone="9075550102",
            biometric_template_hash="BIO-2", insurance_member_id="INS-2",
            clinical_element_count=3,
        )

        pair = F.create_pair(
            api, record_a["id"], record_b["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )

        A.assert_score(pair["raw_score"], 25.00, "raw_score")
        assert pair["conflict_flags"] == [
            CONFLICT_SSN4,
            CONFLICT_BIOMETRIC,
            CONFLICT_INSURANCE,
        ]
        A.assert_score(pair["match_score"], 0.00, "match_score")
        assert pair["match_score"] >= 0
        assert pair["classification"] == CLASSIFICATION_NON_DUPLICATE
        A.assert_score(pair["effective_score"], 0.00, "effective_score")
        assert pair["priority_band"] == "P3"
        assert pair["queue_state"] == QUEUE_NEW
        assert A.list_rows(api.list_investigations(officer_headers())) == []


class TestExchangeScoringVariant:
    def test_the_exchange_probe_scores_under_the_tolerant_variant(self, api):
        """Null credit on the three omitted keys lifts the score to the link threshold.

        PRD §3.3: "The request then computes `external_score` — the local record
        against `external_demographics`, always under the `TOLERANT` variant, always
        against the rule set whose `status` is `ACTIVE`, carried to two decimal places."

        Design: Corner/calculations/external_match_request_always_scores_with_the_tolerant_variant
        """
        site = F.create_site(
            api, "SITE-C5", name="Exchange Clinic", region_code="US-WI",
            registrar_headcount=3,
        )
        F.create_rule_set(api, activate=True)
        record = F.create_record(
            api, site["id"], "C5-1000", "Amarasinghe", "Nuwan", "1972-08-15", "M",
            ssn_last4="9090", postal_code="53703", phone="6085550101",
            clinical_element_count=8,
        )

        request = A.assert_created(
            api.create_external_match(
                f.external_match_payload(
                    record["id"], "HIE-MIDWEST", True,
                    {
                        "last_name": "Amarasinghe",
                        "first_name": "Nuwan",
                        "dob": "1972-08-15",
                        "ssn_last4": "9090",
                    },
                ),
                analyst_headers(),
            )
        )

        A.assert_score(request["external_score"], 85.00, "external_score")
        assert request["state"] == EXTERNAL_MATCHED
        assert request["exchange_partner_code"] == "HIE-MIDWEST"
        assert request["consent_on_file"] is True
        assert request["record_id"] == record["id"]
        untouched = F.get_record(api, record["id"])
        A.assert_version(untouched, 1)
        assert untouched["identity_state"] == IDENTITY_ACTIVE
        assert untouched["integrity_state"] == INTEGRITY_CLEAR
        rows = A.list_rows(
            api.list_external_matches(admin_headers(), {"record_id": record["id"]}),
            expected_total=1,
        )
        assert len(rows) == 1
