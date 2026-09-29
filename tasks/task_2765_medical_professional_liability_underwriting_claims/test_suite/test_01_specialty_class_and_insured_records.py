"""Rate-manual publication and insured onboarding records (PRD 3.1, 3.2).

Covers what a published specialty class and a registered insured look like on
the wire: the declared and defaulted fields, the server-minted identity block,
the snapshot risk classification, and the paging and payload rules that govern
the insured collection.
"""
import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import ABSENT_UUID, CLOCK_EPOCH
from test_helpers.fixtures import advance_clock


NEUROSURGERY_CLASS = {
    "specialty_code": "NEUROSURGERY",
    "base_class_code": "CLASS_8",
    "base_rate_per_million": 92000.00,
    "hazard_index": 10.0,
    "benchmark_severity": 1250000.00,
}

FAMILY_MEDICINE_CLASS = {
    "specialty_code": "FAMILY_MEDICINE",
    "base_class_code": "CLASS_1",
    "base_rate_per_million": 9500.00,
    "hazard_index": 2.0,
    "benchmark_severity": 180000.00,
}


class TestSpecialtyClassPublication:
    """Publishing a rating specialty class into an empty rate manual."""

    def test_publication_returns_every_declared_input_and_the_two_defaults(
        self, api, actuarial_analyst_headers
    ):
        """A published class echoes its five inputs and opens un-revised.

        PRD: "Each new class starts with `rate_revision_index` at 0 and `last_approved_rate_change_pct` null, since no filing has yet touched it."

        Design: Corner/entities/specialty_class_creation_returns_every_declared_and_defaulted_field
        """
        payload = factories.specialty_class_payload(**NEUROSURGERY_CLASS)
        created = validate_success(
            api.create_specialty_class(payload, actuarial_analyst_headers), 201
        )

        assert created["specialty_code"] == "NEUROSURGERY"
        assert created["base_class_code"] == "CLASS_8"
        assertions.assert_money(created["base_rate_per_million"], 92000.00,
                                "base_rate_per_million")
        assert float(created["hazard_index"]) == pytest.approx(10.0, abs=0.0001)
        assertions.assert_money(created["benchmark_severity"], 1250000.00,
                                "benchmark_severity")
        assert created["rate_revision_index"] == 0
        assert created["last_approved_rate_change_pct"] is None
        assert created["version"] == 1
        assertions.assert_specialty_class(created)

    def test_the_class_is_read_back_by_identity_with_the_same_figures(
        self, api, actuarial_analyst_headers, underwriting_officer_headers
    ):
        """The manual rate published for a class is the rate a reader sees.

        PRD: "An `ActuarialAnalyst` or a `ChiefActuary` publishes a **specialty class** by supplying a `specialty_code` — one of `NEUROSURGERY`, `OBSTETRICS_GYNECOLOGY`, `ORTHOPEDIC_SURGERY`, `EMERGENCY_MEDICINE` or `FAMILY_MEDICINE` — together with the ISO-style hazard band `base_class_code`, drawn from `CLASS_1` through `CLASS_8`, the manual `base_rate_per_million` charged for a one-million-dollar per-claim limit, the specialty's `hazard_index`, and the industry `benchmark_severity` against which its paid severity is later measured."

        Design: Corner/entities/specialty_class_creation_returns_every_declared_and_defaulted_field
        """
        created = validate_success(
            api.create_specialty_class(
                factories.specialty_class_payload(**NEUROSURGERY_CLASS),
                actuarial_analyst_headers,
            ),
            201,
        )

        fetched = validate_success(
            api.get_specialty_class(created["id"], underwriting_officer_headers)
        )

        assert fetched["id"] == created["id"]
        assert fetched["specialty_code"] == "NEUROSURGERY"
        assert fetched["base_class_code"] == "CLASS_8"
        assertions.assert_money(fetched["base_rate_per_million"], 92000.00,
                                "base_rate_per_million")
        assertions.assert_money(fetched["benchmark_severity"], 1250000.00,
                                "benchmark_severity")
        assert fetched["rate_revision_index"] == 0

    def test_client_supplied_identity_fields_are_ignored_in_favour_of_the_server(
        self, api, actuarial_analyst_headers
    ):
        """A smuggled id, created_at and revision index never reach the record.

        PRD: "Every resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC instant with three fractional digits."

        Design: Corner/entities/specialty_class_system_fields_are_server_minted_with_client_ids_input_ignored
        """
        advance_clock(api, CLOCK_EPOCH, actuarial_analyst_headers)

        payload = factories.specialty_class_payload(
            specialty_code="EMERGENCY_MEDICINE",
            base_class_code="CLASS_4",
            base_rate_per_million=18000.00,
            hazard_index=4.0,
            benchmark_severity=320000.00,
            id=ABSENT_UUID,
            created_at="1999-01-01T00:00:00Z",
            rate_revision_index=9,
        )
        created = validate_success(
            api.create_specialty_class(payload, actuarial_analyst_headers), 201
        )

        assert created["id"] != ABSENT_UUID
        assert is_valid_uuid(created["id"])
        assert is_iso8601_timestamp(created["created_at"])
        assert assertions.canonical_instant(created["created_at"]) != \
            assertions.canonical_instant("1999-01-01T00:00:00Z")
        assert created["rate_revision_index"] == 0
        assert created["version"] == 1

    def test_the_minted_timestamps_read_from_the_logical_clock(
        self, api, actuarial_analyst_headers
    ):
        """Creation stamps come from the logical clock, not from wall time.

        PRD: "Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time."

        Design: Corner/entities/specialty_class_system_fields_are_server_minted_with_client_ids_input_ignored
        """
        advance_clock(api, CLOCK_EPOCH, actuarial_analyst_headers)

        created = validate_success(
            api.create_specialty_class(
                factories.specialty_class_payload(
                    specialty_code="EMERGENCY_MEDICINE",
                    base_class_code="CLASS_4",
                    base_rate_per_million=18000.00,
                    hazard_index=4.0,
                    benchmark_severity=320000.00,
                    created_at="1999-01-01T00:00:00Z",
                ),
                actuarial_analyst_headers,
            ),
            201,
        )

        assertions.assert_same_instant(created["created_at"], CLOCK_EPOCH,
                                       "created_at")
        assertions.assert_same_instant(created["updated_at"], CLOCK_EPOCH,
                                       "updated_at")


class TestInsuredUnderwritingRecord:
    """Reading back a registered physician's underwriting and risk block."""

    @staticmethod
    def _obgyn_physician(api, underwriting_officer_headers,
                         actuarial_analyst_headers):
        specialty = validate_success(
            api.create_specialty_class(
                factories.specialty_class_payload(
                    specialty_code="OBSTETRICS_GYNECOLOGY",
                    base_class_code="CLASS_6",
                    base_rate_per_million=38000.00,
                    hazard_index=7.0,
                    benchmark_severity=640000.00,
                ),
                actuarial_analyst_headers,
            ),
            201,
        )
        insured = validate_success(
            api.create_insured(
                factories.insured_payload(
                    specialty["id"],
                    entity_type="PHYSICIAN",
                    legal_name="Rivera OBGYN PC",
                    venue_code="COOK_IL",
                    high_severity_procedure_pct=40,
                    years_in_practice=12,
                    board_certified=True,
                ),
                underwriting_officer_headers,
            ),
            201,
        )
        return specialty, insured

    def test_retrieval_echoes_every_registered_underwriting_input(
        self, api, underwriting_officer_headers, actuarial_analyst_headers
    ):
        """A GET on the insured returns the registration exactly as filed.

        PRD: "An `UnderwritingOfficer` registers an **insured** by supplying its `entity_type` — `PHYSICIAN` or `FACILITY` — its `legal_name`, the `specialty_class_id` that sets its rating specialty, its primary litigation `venue_code` from `COOK_IL`, `MIAMI_DADE_FL`, `KINGS_NY`, `TRAVIS_TX` or `MARICOPA_AZ`, and `high_severity_procedure_pct`, the share of the annual procedure mix falling in the high-severity band, which must lie between 0 and 100 inclusive."

        Design: Corner/entities/insured_retrieval_returns_the_stored_underwriting_and_risk_block
        """
        specialty, insured = self._obgyn_physician(
            api, underwriting_officer_headers, actuarial_analyst_headers
        )

        fetched = validate_success(
            api.get_insured(insured["id"], underwriting_officer_headers)
        )

        assert fetched["entity_type"] == "PHYSICIAN"
        assert fetched["legal_name"] == "Rivera OBGYN PC"
        assert fetched["specialty_class_id"] == specialty["id"]
        assert fetched["venue_code"] == "COOK_IL"
        assert float(fetched["high_severity_procedure_pct"]) == pytest.approx(
            40, abs=0.0001
        )
        assert int(fetched["years_in_practice"]) == 12
        assert fetched["board_certified"] is True
        assertions.assert_insured(fetched)

    def test_retrieval_returns_the_snapshot_risk_classification_block(
        self, api, underwriting_officer_headers, actuarial_analyst_headers
    ):
        """A hazard index of 7.0 with a 40 percent high-severity mix scores 4.20 in band R2.

        PRD: "`risk_class_score` is 0.40 times the specialty component, plus 0.35 times the procedure component, plus 0.25 times the capped history component, rounded half up to two decimal places."

        Design: Corner/entities/insured_retrieval_returns_the_stored_underwriting_and_risk_block
        """
        _specialty, insured = self._obgyn_physician(
            api, underwriting_officer_headers, actuarial_analyst_headers
        )

        fetched = validate_success(
            api.get_insured(insured["id"], underwriting_officer_headers)
        )

        assert float(fetched["risk_class_score"]) == pytest.approx(4.20, abs=0.01)
        assert fetched["risk_class_code"] == "R2"
        assert float(fetched["risk_class_factor"]) == pytest.approx(1.00, abs=0.01)


class TestInsuredBookPagination:
    """Paging the insured book of a single family-medicine rating class."""

    @staticmethod
    def _three_insureds(api, underwriting_officer_headers,
                        actuarial_analyst_headers):
        specialty = validate_success(
            api.create_specialty_class(
                factories.specialty_class_payload(**FAMILY_MEDICINE_CLASS),
                actuarial_analyst_headers,
            ),
            201,
        )
        created = []
        for name in ("Ash Family Medicine", "Beal Family Medicine",
                     "Chen Family Medicine"):
            created.append(validate_success(
                api.create_insured(
                    factories.insured_payload(
                        specialty["id"],
                        entity_type="PHYSICIAN",
                        legal_name=name,
                        venue_code="TRAVIS_TX",
                        high_severity_procedure_pct=10,
                        years_in_practice=8,
                        board_certified=True,
                    ),
                    underwriting_officer_headers,
                ),
                201,
            ))
        return created

    def test_the_page_window_reports_total_count_and_has_more_on_both_pages(
        self, api, underwriting_officer_headers, actuarial_analyst_headers
    ):
        """Three insureds paged two at a time count three throughout and exhaust on the second page.

        PRD: "Every list response carries the four pagination fields in its `meta` block: `limit` and `offset` echoing the effective values used, `total_count` giving the number of records matching the filters before the page window is applied, and `has_more` indicating whether records remain beyond the current page."

        Design: Corner/entities/insured_listing_paginates_with_total_count_and_has_more
        """
        insureds = self._three_insureds(
            api, underwriting_officer_headers, actuarial_analyst_headers
        )

        first_rows, first_meta = validate_paginated(
            api.list_insureds(underwriting_officer_headers,
                              {"limit": 2, "offset": 0})
        )
        assert len(first_rows) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0

        second_rows, second_meta = validate_paginated(
            api.list_insureds(underwriting_officer_headers,
                              {"limit": 2, "offset": 2})
        )
        assert len(second_rows) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert second_rows[0]["id"] == insureds[2]["id"]

    def test_the_book_is_ordered_by_creation_so_the_last_page_holds_the_last_row(
        self, api, underwriting_officer_headers, actuarial_analyst_headers
    ):
        """The three registrations page out in the order they were filed.

        PRD: "Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending."

        Design: Corner/entities/insured_listing_paginates_with_total_count_and_has_more
        """
        insureds = self._three_insureds(
            api, underwriting_officer_headers, actuarial_analyst_headers
        )

        rows, meta = validate_paginated(
            api.list_insureds(underwriting_officer_headers,
                              {"limit": 2, "offset": 0})
        )
        assert [row["id"] for row in rows] == [insureds[0]["id"], insureds[1]["id"]]
        assert meta["total_count"] == 3


class TestInsuredRegistrationPayloadShape:
    """The registration payload check that guards the litigation venue."""

    def test_registration_without_a_venue_code_is_refused_and_files_nothing(
        self, api, underwriting_officer_headers, actuarial_analyst_headers
    ):
        """An insured with no primary litigation venue is rejected before it is filed.

        PRD: "5. **Payload shape** — on every write endpoint: required fields present, enum values drawn from the declared members, money fields non-negative and carrying at most two decimal places, and every declared numeric range respected (`ERR_VALIDATION`, HTTP 400)."

        Design: Corner/entities/insured_create_missing_required_venue_code_returns_validation_error
        """
        specialty = validate_success(
            api.create_specialty_class(
                factories.specialty_class_payload(**FAMILY_MEDICINE_CLASS),
                actuarial_analyst_headers,
            ),
            201,
        )

        payload = {
            "entity_type": "PHYSICIAN",
            "legal_name": "Nowhere Clinic",
            "specialty_class_id": specialty["id"],
            "high_severity_procedure_pct": 10,
        }
        response = api.create_insured(payload, underwriting_officer_headers)

        validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

        _rows, meta = validate_paginated(
            api.list_insureds(underwriting_officer_headers)
        )
        assert meta["total_count"] == 0
