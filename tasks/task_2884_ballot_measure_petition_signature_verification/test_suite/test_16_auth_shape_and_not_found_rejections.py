"""The first six rungs of the §2.11 ladder: headers, role, shape, existence.

Priorities 1 through 3 are probed on requests that are also wrong in later ways
— an unresolvable path identifier, a negative integer, a missing required field
— so an implementation that inspects the body or touches the store before
reading the headers is caught. Priority 4 is then probed once per clause of the
shape rule, and priorities 5 and 6 are probed across all twelve not-found codes,
including the declared resolution order for body foreign keys.

A blank header is sent as the empty string rather than omitted, because absent
and present-but-empty are the same violation at priority 1 and only the
empty-string form catches a truthiness bug.
"""
from test_helpers import (
    api_client,
    create_petition_payload,
    create_voter_record_payload,
    make_challenger_headers,
    make_county_clerk_headers,
    make_examiner_headers,
    make_headers,
    make_proponent_headers,
    make_sos_admin_headers,
    validate_error,
    validate_paginated,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.factories import create_assignment_payload
from test_helpers.fixtures import (
    file_petition,
    register_circulator,
    register_county,
    register_standard,
    set_clock,
)

# An identifier the API never issues.
MISSING = "00000000-0000-0000-0000-000000009999"


def _probe_world():
    """One standard, one county, one circulator and one DRAFT petition, so every
    probe below can hold exactly one defect while everything else resolves."""
    set_clock(CLOCK_EPOCH)
    standard = register_standard(jurisdiction_code="SOS-E")
    county = register_county("ALPHA", 20)
    circulator = register_circulator(full_name="Cora Carter")
    petition = file_petition(
        standard["id"],
        measure_subject_codes=("TAX",),
        proponent_name="Shape Committee",
        submitted_title="Shape Measure",
    )
    assert petition["status"] == "DRAFT"
    return {
        "standard": standard,
        "county": county,
        "circulator": circulator,
        "petition": petition,
    }


class TestAuthHeaderFailuresPrecedeEverythingElse:
    """Priorities 1 to 3 run before the body is inspected and before any
    identifier is resolved."""

    def test_blank_and_unrecognised_role_headers_are_refused_before_any_lookup(self):
        """An empty `X-User-Role`, an empty `X-User-ID`, an unknown role and a
        lowercase misspelling are all 401s on a path naming a petition that does
        not exist.

        PRD §2.11: "1. **Headers present.** Both `X-User-ID` and `X-User-Role`
        present and neither an empty string, else `ERR_MISSING_AUTH_HEADERS`
        (401). Applies to every endpoint."

        PRD §2.11: "2. **Role recognised.** `X-User-Role` is one of `SosAdmin`,
        `ElectionsExaminer`, `TitleExaminer`, `Proponent`, `CountyClerk`,
        `CirculatorAgent`, `Challenger`, else `ERR_INVALID_ROLE` (401). Applies
        to every endpoint."

        Design: Corner/errors/auth_header_failures_rejected_before_anything_else
        """
        set_clock(CLOCK_EPOCH)

        validate_error(
            api_client.get_petition(MISSING, make_headers("admin-1", "")),
            "ERR_MISSING_AUTH_HEADERS",
            401,
        )
        validate_error(
            api_client.get_petition(MISSING, make_headers("", "SosAdmin")),
            "ERR_MISSING_AUTH_HEADERS",
            401,
        )
        validate_error(
            api_client.get_petition(MISSING, make_headers("", "")),
            "ERR_MISSING_AUTH_HEADERS",
            401,
        )
        validate_error(
            api_client.get_petition(MISSING, make_headers("notary-1", "Notary")),
            "ERR_INVALID_ROLE",
            401,
        )
        validate_error(
            api_client.create_county(
                {"county_code": "ALPHA", "registered_voter_count": -5},
                make_headers("notary-1", "notary"),
            ),
            "ERR_INVALID_ROLE",
            401,
        )
        validate_error(
            api_client.create_county(
                {"county_code": "ALPHA", "registered_voter_count": -5},
                make_headers("admin-1", "sosadmin"),
            ),
            "ERR_INVALID_ROLE",
            401,
        )  # role matching is case-sensitive

        rows, meta = validate_paginated(api_client.list_counties(make_sos_admin_headers()))
        assert rows == [], "no probe reached the store"
        assert meta["total_count"] == 0

    def test_the_role_check_outranks_both_the_shape_check_and_existence(self):
        """A `Challenger` posting a malformed county body gets 403 rather than
        400, and a `Proponent` clearing a petition that does not exist gets 403
        rather than 404.

        PRD §2.11: "3. **Role authorised.** The acting role appears in the
        endpoint's authorised-role list, else `ERR_UNAUTHORIZED` (403). Applies
        to every endpoint."

        PRD §2.11: "The practical consequence worth internalising is that
        authorisation always precedes shape, shape always precedes existence,
        existence always precedes ownership, ownership precedes concurrency,
        concurrency precedes state, and state precedes every business rule."

        Design: Corner/errors/auth_header_failures_rejected_before_anything_else
        """
        set_clock(CLOCK_EPOCH)

        validate_error(
            api_client.create_county(
                {"county_code": "ALPHA", "registered_voter_count": -5},
                make_challenger_headers("chal-1"),
            ),
            "ERR_UNAUTHORIZED",
            403,
        )  # priority 3 runs before the shape check at priority 4

        validate_error(
            api_client.clear_for_circulation(MISSING, make_proponent_headers("prop-1")),
            "ERR_UNAUTHORIZED",
            403,
        )  # clearance is SosAdmin-only, and the role check precedes existence

        rows, meta = validate_paginated(api_client.list_counties(make_sos_admin_headers()))
        assert rows == []
        assert meta["total_count"] == 0


class TestMalformedRequestShapesReturnInvalidRequest:
    """One code covers every clause of the priority-4 rule, and it outranks the
    state gates and the temporal rules that the same requests also break."""

    def test_seven_body_shape_violations_all_answer_with_invalid_request(self):
        """A missing required field, an out-of-range integer, an empty array, a
        duplicated array entry, an unknown enum member, an unparseable instant
        and `effective_to` equal to `effective_from` are all 400s, and none of
        them stores anything.

        PRD §2.11: "4. **Request shape.** Every required input field present and
        non-null; every enum value within its declared set; every integer within
        its declared range; every array within its declared cardinality and free
        of duplicate entries; every datetime a valid ISO 8601 UTC instant;
        `effective_to` strictly after `effective_from`; `limit` between 1 and 100
        and `offset` not negative. Any failure is `ERR_INVALID_REQUEST` (400).
        Applies to every endpoint."

        Design: Corner/errors/malformed_request_shapes_return_invalid_request
        """
        world = _probe_world()
        admin = make_sos_admin_headers()
        proponent = make_proponent_headers("prop-1")

        validate_error(
            api_client.create_county(
                {"county_code": "BETA", "registered_voter_count": 10}, admin
            ),
            "ERR_INVALID_REQUEST",
            400,
        )  # name is required and absent

        validate_error(
            api_client.create_county(
                {"county_code": "GAMMA", "name": "Gamma County", "registered_voter_count": -5},
                admin,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )  # registered_voter_count is at least 1

        validate_error(
            api_client.create_petition(
                create_petition_payload(
                    world["standard"]["id"],
                    proponent_name="Empty Subjects",
                    submitted_title="No Subjects",
                    measure_subject_codes=[],
                ),
                proponent,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )  # measure_subject_codes holds between 1 and 5 entries

        validate_error(
            api_client.create_petition(
                create_petition_payload(
                    world["standard"]["id"],
                    proponent_name="Dup Subjects",
                    submitted_title="Dup Subjects",
                    measure_subject_codes=["TAX", "TAX"],
                ),
                proponent,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )  # a duplicate entry is a shape violation, not ERR_SINGLE_SUBJECT_VIOLATION

        validate_error(
            api_client.format_decision(
                world["petition"]["id"], {"decision": "MAYBE"}, make_examiner_headers()
            ),
            "ERR_INVALID_REQUEST",
            400,
        )  # decision admits only APPROVE and REJECT; the DRAFT state is never consulted

        validate_error(
            api_client.create_voter_record(
                create_voter_record_payload(
                    world["county"]["id"],
                    voter_id_number="VBAD",
                    full_name="Bad Date",
                    signature_on_file_hash="H-VBAD",
                    registration_date="2020-13-45T99:99:99Z",
                ),
                admin,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )  # registration_date is not a valid ISO 8601 UTC instant

        validate_error(
            api_client.create_circulation_assignment(
                create_assignment_payload(
                    world["petition"]["id"],
                    world["circulator"]["id"],
                    world["circulator"]["version"],
                    assigned_county_codes=["ALPHA"],
                    effective_from="2026-08-10T00:00:00Z",
                    effective_to="2026-08-10T00:00:00Z",
                ),
                admin,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )  # equal instants fail at priority 4, not at the interval rules of priority 14

        counties, county_meta = validate_paginated(api_client.list_counties(admin))
        assert {row["county_code"] for row in counties} == {"ALPHA"}
        assert county_meta["total_count"] == 1
        petitions, petition_meta = validate_paginated(api_client.list_petitions(admin))
        assert {row["id"] for row in petitions} == {world["petition"]["id"]}
        assert petition_meta["total_count"] == 1
        _, voter_meta = validate_paginated(api_client.list_voter_records(admin))
        assert voter_meta["total_count"] == 0
        _, assignment_meta = validate_paginated(
            api_client.list_circulation_assignments(admin)
        )
        assert assignment_meta["total_count"] == 0

    def test_pagination_arguments_outside_their_declared_range_are_shape_violations(self):
        """`limit` 0, `limit` 101 and `offset` -1 are 400s while `limit` 100 is
        accepted, so the upper bound is inclusive.

        PRD §2.3: "`limit` sets the maximum number of items in the page; it
        defaults to 10 when omitted, with a minimum of 1 and a maximum of 100.
        `offset` sets the number of items to skip before the window starts; it
        defaults to 0 and may not be negative. A `limit` outside the range 1
        through 100, or a negative `offset`, is a request-shape violation and is
        refused with `ERR_INVALID_REQUEST` and HTTP 400."

        Design: Corner/errors/malformed_request_shapes_return_invalid_request
        """
        world = _probe_world()
        admin = make_sos_admin_headers()

        validate_error(
            api_client.list_petitions(admin, params={"limit": 0}),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            api_client.list_petitions(admin, params={"limit": 101}),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            api_client.list_signature_batches(admin, params={"offset": -1}),
            "ERR_INVALID_REQUEST",
            400,
        )

        rows, meta = validate_paginated(api_client.list_petitions(admin, params={"limit": 100}))
        assert {row["id"] for row in rows} == {world["petition"]["id"]}
        assert meta["limit"] == 100, "the upper bound is inclusive"
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False


class TestUnresolvableIdsReturnTheEntitySpecificNotFoundCode:
    """Each of the twelve types has its own 404 code, on reads and on writes
    alike, and body foreign keys resolve in the order §2.8 declares."""

    def test_the_twelve_read_paths_each_answer_with_their_own_not_found_code(self):
        """Twelve `GET`s by an unissued identifier produce twelve distinct 404
        codes, each with an authorised role so priority 3 cannot mask priority 5.

        PRD §2.8: "The twelve not-found signals are `ERR_PETITION_NOT_FOUND`,
        `ERR_CIRCULATOR_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
        `ERR_BATCH_NOT_FOUND`, `ERR_SIGNATURE_RECORD_NOT_FOUND`,
        `ERR_ROUND_NOT_FOUND`, `ERR_CURE_PERIOD_NOT_FOUND`,
        `ERR_CHALLENGE_NOT_FOUND`, `ERR_FRAUD_REFERRAL_NOT_FOUND`,
        `ERR_VERIFICATION_STANDARD_NOT_FOUND`, `ERR_COUNTY_NOT_FOUND` and
        `ERR_VOTER_RECORD_NOT_FOUND`, and they carry the same meaning whether the
        failing identifier came from the path or from the body."

        Design: Corner/errors/unresolvable_ids_return_the_entity_specific_not_found_code
        """
        set_clock(CLOCK_EPOCH)
        admin = make_sos_admin_headers()

        probes = [
            (api_client.get_verification_standard, "ERR_VERIFICATION_STANDARD_NOT_FOUND"),
            (api_client.get_county, "ERR_COUNTY_NOT_FOUND"),
            (api_client.get_voter_record, "ERR_VOTER_RECORD_NOT_FOUND"),
            (api_client.get_petition, "ERR_PETITION_NOT_FOUND"),
            (api_client.get_circulator, "ERR_CIRCULATOR_NOT_FOUND"),
            (api_client.get_circulation_assignment, "ERR_ASSIGNMENT_NOT_FOUND"),
            (api_client.get_signature_batch, "ERR_BATCH_NOT_FOUND"),
            (api_client.get_signature_record, "ERR_SIGNATURE_RECORD_NOT_FOUND"),
            (api_client.get_verification_round, "ERR_ROUND_NOT_FOUND"),
            (api_client.get_cure_period, "ERR_CURE_PERIOD_NOT_FOUND"),
            (api_client.get_challenge, "ERR_CHALLENGE_NOT_FOUND"),
            (api_client.get_fraud_referral, "ERR_FRAUD_REFERRAL_NOT_FOUND"),
        ]
        seen = set()
        for reader, expected in probes:
            validate_error(reader(MISSING, admin), expected, 404)
            seen.add(expected)
        assert len(seen) == 12, "the twelve codes must be distinct"

    def test_the_mutating_paths_report_the_same_codes_as_the_reads(self):
        """A tally, an expiry, a dismissal, an AG referral, a termination and a
        line validation against an unissued identifier all answer with that
        type's 404 rather than a state, ownership or linkage error.

        PRD §2.11: "5. **Path identifiers resolve.** Left to right, as described
        in §2.8, each failure yielding that type's not-found code (404). Applies
        to every endpoint carrying a path parameter."

        Design: Corner/errors/unresolvable_ids_return_the_entity_specific_not_found_code
        """
        world = _probe_world()
        admin = make_sos_admin_headers()

        validate_error(
            api_client.tally_round(MISSING, make_examiner_headers()), "ERR_ROUND_NOT_FOUND", 404
        )
        validate_error(
            api_client.expire_cure_period(MISSING, admin), "ERR_CURE_PERIOD_NOT_FOUND", 404
        )
        validate_error(
            api_client.dismiss_challenge(MISSING, admin, {"reason": "no such challenge"}),
            "ERR_CHALLENGE_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.refer_to_ag(MISSING, make_examiner_headers()),
            "ERR_FRAUD_REFERRAL_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.terminate_assignment(MISSING, admin, {"reason": "no such assignment"}),
            "ERR_ASSIGNMENT_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.validate_signature_record(
                MISSING, make_county_clerk_headers(world["county"]["id"])
            ),
            "ERR_SIGNATURE_RECORD_NOT_FOUND",
            404,
        )

    def test_body_foreign_keys_resolve_in_the_declared_order(self):
        """With `petition_id`, `circulator_id` and `county_id` all unresolvable
        the first declared key wins, and resolving them one at a time walks down
        the order; an unresolvable `cure_period_id` and an unknown
        `assigned_county_codes` entry are existence failures too.

        PRD §2.8: "Body foreign keys are resolved in a fixed order too — the
        order in which the fields are introduced across the data model:
        `standard_id`, then `petition_id`, then `circulator_id`, then
        `county_id`, then `batch_id`, then `cure_period_id`, and finally each
        entry of `assigned_county_codes` against a registered county code. That
        ordering governs which 404 surfaces when a single request names two
        nonexistent parents."

        PRD §2.8: "a `county_code` entry in `assigned_county_codes` that matches
        no registered county is reported as `ERR_COUNTY_NOT_FOUND`."

        Design: Corner/errors/unresolvable_ids_return_the_entity_specific_not_found_code
        """
        world = _probe_world()
        petition_id = world["petition"]["id"]
        circulator_id = world["circulator"]["id"]
        county_id = world["county"]["id"]
        proponent = make_proponent_headers("prop-1")

        validate_error(
            api_client.create_petition(
                create_petition_payload(
                    MISSING,
                    proponent_name="Bad Standard",
                    submitted_title="Bad Standard",
                    measure_subject_codes=["TAX"],
                ),
                proponent,
            ),
            "ERR_VERIFICATION_STANDARD_NOT_FOUND",
            404,
        )

        validate_error(
            api_client.create_signature_batch(
                {
                    "petition_id": MISSING,
                    "circulator_id": MISSING,
                    "county_id": MISSING,
                    "affidavit_signed": True,
                },
                proponent,
            ),
            "ERR_PETITION_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.create_signature_batch(
                {
                    "petition_id": petition_id,
                    "circulator_id": MISSING,
                    "county_id": MISSING,
                    "affidavit_signed": True,
                },
                proponent,
            ),
            "ERR_CIRCULATOR_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.create_signature_batch(
                {
                    "petition_id": petition_id,
                    "circulator_id": circulator_id,
                    "county_id": MISSING,
                    "affidavit_signed": True,
                },
                proponent,
            ),
            "ERR_COUNTY_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.create_signature_batch(
                {
                    "petition_id": petition_id,
                    "circulator_id": circulator_id,
                    "county_id": county_id,
                    "affidavit_signed": True,
                    "is_supplemental": True,
                    "cure_period_id": MISSING,
                },
                proponent,
            ),
            "ERR_CURE_PERIOD_NOT_FOUND",
            404,
        )  # existence at priority 6 precedes linkage at priority 13

        validate_error(
            api_client.create_fraud_referral(
                {
                    "petition_id": petition_id,
                    "circulator_id": circulator_id,
                    "referral_type": "FORGED_SIGNATURES",
                    "narrative": "Batch does not exist.",
                    "batch_id": MISSING,
                },
                make_examiner_headers(),
            ),
            "ERR_BATCH_NOT_FOUND",
            404,
        )

        validate_error(
            api_client.create_circulation_assignment(
                create_assignment_payload(
                    petition_id,
                    circulator_id,
                    world["circulator"]["version"],
                    assigned_county_codes=["ZULU"],
                    effective_from="2026-08-10T00:00:00Z",
                    effective_to="2026-08-20T00:00:00Z",
                ),
                make_sos_admin_headers(),
            ),
            "ERR_COUNTY_NOT_FOUND",
            404,
        )

        batches, batch_meta = validate_paginated(
            api_client.list_signature_batches(make_sos_admin_headers())
        )
        assert batches == [], "no refused filing stored a batch"
        assert batch_meta["total_count"] == 0
        _, referral_meta = validate_paginated(
            api_client.list_fraud_referrals(make_sos_admin_headers())
        )
        assert referral_meta["total_count"] == 0
