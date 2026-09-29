"""Resource creation contracts: echoes, declared defaults, and intake listing.

The three configuration resources of §2.7 carry only `id` and `created_at`; the
managed resources carry `updated_at` and `version` as well. Creation echoes
every declared input, omitted optional inputs fall back to their declared
defaults, and client-supplied system fields never win.

Adjudication recorded here rather than weakened silently: PRD §2.7 declares
`version` "a server-managed counter that increments by one on every mutation"
but never pins the value a freshly created resource starts at, so every test
below asserts the *increment* and the integer type rather than a literal 1.
PRD §2.3 pins the default list order to "creation timestamp in ascending
order", but the logical clock of §2.4 does not move on its own, so resources
created inside one test share an identical `created_at` and the PRD does not
break that tie; the listing test therefore asserts page partitioning, counts
and `meta`, never a positional identity.
"""
from test_helpers import (
    api_client,
    assert_instants_equal,
    assert_millisecond_instant,
    create_petition_payload,
    create_voter_record_payload,
    file_petition,
    make_proponent_headers,
    make_sos_admin_headers,
    minimal_verification_standard_payload,
    read_petition,
    register_circulator,
    register_standard,
    submit_petition,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.fixtures import set_clock

EPOCH_STAMP = "2026-08-01T00:00:00.000Z"

# Every declared input of a VerificationStandard, stated explicitly.
FULL_STANDARD = {
    "jurisdiction_code": "SOS-CFG",
    "gubernatorial_vote_total": 12345,
    "signature_pct_bps": 375,
    "sample_pct_bps": 4000,
    "sample_min_count": 3,
    "sufficiency_upper_bps": 11000,
    "sufficiency_lower_bps": 6000,
    "stratification_mode": "STRATIFIED",
    "county_distribution_pct_bps": 750,
    "required_qualifying_counties": 2,
    "verification_rate_millicents_per_signature": 4750,
    "county_surcharge_bps": 250,
    "cure_allowed": False,
    "cure_window_days": 21,
    "cure_eligibility_floor_bps": 6500,
    "circulation_window_days": 150,
}


class TestConfigurationResourcesRoundTripWithoutVersion:
    """`VerificationStandard`, `County` and `VoterRecord` echo their declared
    inputs, stamp `created_at` from the logical clock, and carry neither
    `updated_at` nor `version`."""

    def test_a_standard_echoes_every_declared_parameter_and_omits_version(self):
        """All sixteen declared parameters come back verbatim, `created_at` is
        the clock in force, and the two managed fields are absent.

        PRD §2.7: "The three configuration types — `VerificationStandard`,
        `County` and `VoterRecord` — are different, and the difference is
        deliberate. Each carries only `id` and `created_at`. Neither
        `updated_at` nor `version` exists on them, and neither field appears in
        their responses."

        Design: Corner/entities/configuration_entities_create_read_round_trip_without_version
        """
        set_clock(CLOCK_EPOCH)

        response = api_client.create_verification_standard(
            dict(FULL_STANDARD), make_sos_admin_headers()
        )
        body = response.json()
        standard = validate_success(response, 201)

        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        for field, expected in FULL_STANDARD.items():
            assert standard[field] == expected, f"{field} was not echoed verbatim"

        assert_millisecond_instant(standard["created_at"], "standard.created_at")
        assert_instants_equal(standard["created_at"], EPOCH_STAMP)
        assert "updated_at" not in standard
        assert "version" not in standard

        reread = validate_success(
            api_client.get_verification_standard(standard["id"], make_sos_admin_headers())
        )
        assert reread == standard, "the read-back must be byte-identical to the create"

    def test_a_county_and_a_voter_record_round_trip_the_same_way(self):
        """The other two configuration types behave identically, including the
        voter's supplied `registration_date` and `registration_status`.

        PRD §2.7: "Each carries only `id` and `created_at`. Neither
        `updated_at` nor `version` exists on them, and neither field appears in
        their responses."

        Design: Corner/entities/configuration_entities_create_read_round_trip_without_version
        """
        set_clock(CLOCK_EPOCH)

        county_response = api_client.create_county(
            {"county_code": "ALPHA", "name": "Alpha County", "registered_voter_count": 20},
            make_sos_admin_headers(),
        )
        county = validate_success(county_response, 201)
        assert county_response.json()["response_type"] == "object"
        assert county["county_code"] == "ALPHA"
        assert county["name"] == "Alpha County"
        assert county["registered_voter_count"] == 20
        assert_instants_equal(county["created_at"], EPOCH_STAMP)
        assert "updated_at" not in county and "version" not in county

        voter_payload = create_voter_record_payload(
            county["id"],
            voter_id_number="VA1",
            full_name="Ada Adams",
            signature_on_file_hash="H-VA1",
            registration_date="2020-01-01T00:00:00Z",
            registration_status="INACTIVE",
        )
        voter = validate_success(
            api_client.create_voter_record(voter_payload, make_sos_admin_headers()), 201
        )
        assert voter["county_id"] == county["id"]
        assert voter["voter_id_number"] == "VA1"
        assert voter["full_name"] == "Ada Adams"
        assert voter["signature_on_file_hash"] == "H-VA1"
        assert_instants_equal(voter["registration_date"], "2020-01-01T00:00:00.000Z")
        assert voter["registration_status"] == "INACTIVE", (
            "a supplied registration_status is honoured rather than defaulted"
        )
        assert_instants_equal(voter["created_at"], EPOCH_STAMP)
        assert "updated_at" not in voter and "version" not in voter

        assert validate_success(
            api_client.get_county(county["id"], make_sos_admin_headers())
        ) == county
        assert validate_success(
            api_client.get_voter_record(voter["id"], make_sos_admin_headers())
        ) == voter


class TestDeclaredDefaultsApplyWhenOptionalInputsAreOmitted:
    """Omitting an optional input is not the same as sending null: the server
    supplies the value §3 declares."""

    def test_the_four_optional_standard_parameters_fall_back_to_their_defaults(self):
        """Sending only the twelve mandatory parameters leaves the other four
        at true, 30, 8000 and 180.

        PRD §3.1: "Four of the sixteen parameters are optional on the way in:
        omitting `cure_allowed` accepts `true`, omitting `cure_window_days`
        accepts 30, omitting `cure_eligibility_floor_bps` accepts 8000, and
        omitting `circulation_window_days` accepts 180."

        Design: Corner/entities/declared_defaults_applied_when_optional_inputs_omitted
        """
        set_clock(CLOCK_EPOCH)

        payload = minimal_verification_standard_payload(jurisdiction_code="SOS-DEF")
        for absent in (
            "cure_allowed",
            "cure_window_days",
            "cure_eligibility_floor_bps",
            "circulation_window_days",
        ):
            assert absent not in payload, "the optional input must be omitted, not nulled"

        standard = validate_success(
            api_client.create_verification_standard(payload, make_sos_admin_headers()), 201
        )
        assert standard["cure_allowed"] is True
        assert standard["cure_window_days"] == 30
        assert standard["cure_eligibility_floor_bps"] == 8000
        assert standard["circulation_window_days"] == 180

    def test_a_fresh_petition_starts_at_every_declared_zero_and_null(self):
        """`status`, `challenge_status`, the format counter, nine derived
        counters and four nullable fields all start where §3.2 says.

        PRD §3.2: "A fresh petition begins with `status` at `DRAFT`,
        `challenge_status` at `NONE`, `format_review_round` at 0, and every
        derived counter at 0 — `required_valid_signatures`,
        `raw_signature_count`, `accepted_raw_total`, `projected_valid_count`,
        `verified_valid_count`, `qualifying_county_count`,
        `verification_cost_accrued_cents`, `voided_signature_count` and
        `cure_period_count` all start there — with `official_title`,
        `official_summary`, `cleared_at` and `circulation_deadline` all null."

        Design: Corner/entities/declared_defaults_applied_when_optional_inputs_omitted
        """
        set_clock(CLOCK_EPOCH)
        standard = register_standard(jurisdiction_code="SOS-PDF")

        petition = validate_success(
            api_client.create_petition(
                create_petition_payload(
                    standard["id"],
                    proponent_name="Defaults Committee",
                    submitted_title="Defaults Measure",
                    measure_subject_codes=["TAX"],
                ),
                make_proponent_headers("prop-1"),
            ),
            201,
        )

        assert petition["status"] == "DRAFT"
        assert petition["challenge_status"] == "NONE"
        assert petition["format_review_round"] == 0
        for counter in (
            "required_valid_signatures",
            "raw_signature_count",
            "accepted_raw_total",
            "projected_valid_count",
            "verified_valid_count",
            "qualifying_county_count",
            "verification_cost_accrued_cents",
            "voided_signature_count",
            "cure_period_count",
        ):
            assert petition[counter] == 0, f"{counter} must start at 0"
        for nullable in (
            "official_title",
            "official_summary",
            "cleared_at",
            "circulation_deadline",
        ):
            assert petition[nullable] is None, f"{nullable} must start null"

        assert petition["proponent_user_id"] == "prop-1", (
            "PRD §3.2: the server records the filer's identifier in proponent_user_id"
        )
        assert isinstance(petition["version"], int) and petition["version"] >= 1
        assert_instants_equal(petition["created_at"], EPOCH_STAMP)
        assert_instants_equal(petition["updated_at"], petition["created_at"])

    def test_a_fresh_circulator_is_unpaid_untrained_and_fully_credible(self):
        """`is_paid` accepts false, `employer_name` accepts null, and an unpaid
        circulator's `paid_disclosure_on_file` is therefore already true.

        PRD §3.3: "A new circulator begins with `registration_status` at
        `PENDING_TRAINING`, with `training_course_code`,
        `training_completed_at`, `affidavit_filed_at` and
        `disclosure_document_id` all null, with `misconduct_strike_count` at 0,
        and with `credibility_score_bps` at its ceiling of 10000, because a
        circulator with nothing yet examined has nothing held against it."

        Design: Corner/entities/declared_defaults_applied_when_optional_inputs_omitted
        """
        set_clock(CLOCK_EPOCH)

        circulator = register_circulator(full_name="Cora Carter")

        assert circulator["registration_status"] == "PENDING_TRAINING"
        assert circulator["is_paid"] is False
        assert circulator["employer_name"] is None
        assert circulator["paid_disclosure_on_file"] is True, (
            "PRD §3.3: paid_disclosure_on_file is true when is_paid is false"
        )
        for nullable in (
            "training_course_code",
            "training_completed_at",
            "affidavit_filed_at",
            "disclosure_document_id",
        ):
            assert circulator[nullable] is None, f"{nullable} must start null"
        assert circulator["misconduct_strike_count"] == 0
        assert circulator["credibility_score_bps"] == 10000
        assert circulator["residency_state_code"] == "CA"


class TestPetitionIntakeIgnoresClientSuppliedSystemFields:
    """A create body that carries system and computed fields is accepted, and
    every one of those fields is decided by the server."""

    def test_spoofed_id_status_version_and_owner_are_all_ignored(self):
        """Six system/computed keys ride along in the body; the petition still
        comes back server-minted, `DRAFT`, and owned by the acting principal.

        PRD §3.2: "The server records the filer's identifier in
        `proponent_user_id`, which is thereafter the only thing that lets that
        committee touch this petition."

        PRD §2.11: "Every required input field present and non-null; every enum
        value within its declared set; every integer within its declared range;
        every array within its declared cardinality and free of duplicate
        entries; every datetime a valid ISO 8601 UTC instant; `effective_to`
        strictly after `effective_from`; `limit` between 1 and 100 and `offset`
        not negative. Any failure is `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/petition_create_client_supplied_system_fields_input_ignored
        """
        set_clock(CLOCK_EPOCH)
        standard = register_standard(jurisdiction_code="SOS-SPF")

        payload = create_petition_payload(
            standard["id"],
            proponent_name="Spoof Committee",
            submitted_title="Spoof Measure",
            measure_subject_codes=["HEALTH"],
        )
        payload.update(
            {
                "id": "pet-forced",
                "created_at": "1999-01-01T00:00:00Z",
                "version": 9,
                "status": "CERTIFIED",
                "proponent_user_id": "prop-9",
                "required_valid_signatures": 999,
            }
        )

        petition = validate_success(
            api_client.create_petition(payload, make_proponent_headers("prop-1")), 201
        )

        assert petition["id"] != "pet-forced", "the server mints its own identifier"
        assert is_valid_uuid(petition["id"])
        assert_instants_equal(petition["created_at"], EPOCH_STAMP)
        assert petition["status"] == "DRAFT", "the body's CERTIFIED was ignored"
        assert petition["required_valid_signatures"] == 0, (
            "the threshold stays 0 until clearance freezes the formula"
        )
        assert petition["proponent_user_id"] == "prop-1", (
            "the acting X-User-ID wins over the body's prop-9"
        )
        assert petition["version"] != 9, "the body's version was ignored"

        assert read_petition(petition["id"], make_proponent_headers("prop-1")) == petition


class TestPetitionListingPaginatesAndFilters:
    """`GET /petitions` windows the collection with `limit`/`offset`, reports the
    filtered total, and narrows by `status`."""

    def test_two_pages_of_two_partition_three_petitions_with_a_constant_total(self):
        """`total_count` counts the filtered set rather than the page,
        `has_more` flips true then false, and no petition appears twice.

        PRD §2.3: "List responses populate four fields inside the `meta` object
        of the envelope: `limit`, `offset`, `total_count`, and `has_more`.
        Single-resource responses omit all four."

        Design: Corner/entities/petition_listing_paginates_and_filters_with_stable_order
        """
        set_clock(CLOCK_EPOCH)
        standard = register_standard(jurisdiction_code="SOS-LST")
        created = {
            file_petition(standard["id"], submitted_title=title)["id"]
            for title in ("Measure One", "Measure Two", "Measure Three")
        }
        assert len(created) == 3

        page1, meta1 = validate_paginated(
            api_client.list_petitions(
                make_sos_admin_headers(), params={"limit": 2, "offset": 0}
            )
        )
        assert len(page1) == 2
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api_client.list_petitions(
                make_sos_admin_headers(), params={"limit": 2, "offset": 2}
            )
        )
        assert len(page2) == 1
        assert meta2["limit"] == 2
        assert meta2["offset"] == 2
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        seen = [row["id"] for row in page1] + [row["id"] for row in page2]
        assert len(set(seen)) == 3, "the two pages must not repeat a row"
        assert set(seen) == created, "the two pages must partition the collection"

    def test_the_status_filter_narrows_the_collection_and_its_total(self):
        """Submitting one of the three petitions leaves exactly one
        `FORMAT_REVIEW` row, and the filtered `total_count` is 1, not 3.

        PRD §3.2: "Petitions are readable individually and as a list narrowable
        by `standard_id`, by `status`, or by `challenge_status`."

        Design: Corner/entities/petition_listing_paginates_and_filters_with_stable_order
        """
        set_clock(CLOCK_EPOCH)
        standard = register_standard(jurisdiction_code="SOS-LSF")
        file_petition(standard["id"], submitted_title="Measure One")
        file_petition(standard["id"], submitted_title="Measure Two")
        third = file_petition(standard["id"], submitted_title="Measure Three")
        submit_petition(third["id"])

        rows, meta = validate_paginated(
            api_client.list_petitions(
                make_sos_admin_headers(), params={"status": "FORMAT_REVIEW"}
            )
        )
        assert len(rows) == 1
        assert rows[0]["id"] == third["id"]
        assert rows[0]["status"] == "FORMAT_REVIEW"
        assert meta["total_count"] == 1, "total_count counts the filtered set"
        assert meta["has_more"] is False
        assert meta["limit"] == 10, "PRD §2.3: limit defaults to 10 when omitted"
        assert meta["offset"] == 0, "PRD §2.3: offset defaults to 0 when omitted"

        drafts, draft_meta = validate_paginated(
            api_client.list_petitions(make_sos_admin_headers(), params={"status": "DRAFT"})
        )
        assert len(drafts) == 2
        assert draft_meta["total_count"] == 2
        assert third["id"] not in {row["id"] for row in drafts}
