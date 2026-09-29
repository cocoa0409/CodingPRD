"""Endpoint-surface behaviour: clock stamping, list filters, version echoes.

Three concerns meet here. Every system-assigned instant comes from the logical
clock of §2.4 at millisecond precision, and a mutating action refreshes
`updated_at`/`version` on a managed resource while leaving a configuration
resource's `created_at` alone. Every list endpoint narrows by each reference
§3 declares for it, returning an empty page rather than a 404 when nothing
matches. And the two writes of §2.9 refuse a replayed version echo with 412
without touching the resource.

Adjudication recorded rather than weakened silently: PRD §2.3 pins the default
list order to "creation timestamp in ascending order", but the §2.4 clock never
advances on its own, so resources created inside one test share an identical
`created_at` and the PRD does not break that tie. Every list assertion below is
therefore a count/membership assertion, never a positional one.
"""
from test_helpers import (
    api_client,
    assert_instants_equal,
    assert_millisecond_instant,
    make_circulator_agent_headers,
    make_county_clerk_headers,
    make_sos_admin_headers,
    make_title_examiner_headers,
    paid_disclosure_payload,
    read_circulator,
    read_petition,
    registration_status_payload,
    title_summary_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.fixtures import (
    add_line,
    add_voter,
    create_assignment,
    create_cleared_petition,
    create_registered_circulator,
    decide_format,
    file_batch,
    file_petition,
    register_circulator,
    register_county,
    register_standard,
    set_clock,
    submit_petition,
    verify_batch_affidavit,
)
from test_helpers.factories import create_assignment_payload

CREATE_CLOCK = "2026-05-01T12:34:56.789Z"
MUTATE_CLOCK = "2026-05-02T03:04:05.006Z"
BATCH_TWO_CLOCK = "2026-09-12T00:00:00Z"


def _ids(rows):
    return {row["id"] for row in rows}


class TestLogicalClockStampsCreatesAndMutatingActions:
    """Creates take their instants from the clock in force; a later clock move
    never rewrites them, and only managed resources gain `updated_at`."""

    def test_every_create_stamps_the_clock_to_the_millisecond_and_never_moves_after(self):
        """A county, a voter record and a paid circulator all stamp
        `2026-05-01T12:34:56.789Z`, keep it after the clock advances, and only
        the circulator carries the two managed fields.

        PRD §2.4: "Every system-assigned instant in the data model is stamped
        from this clock: a petition's `cleared_at`, a batch's `filed_at`, a
        circulator's `training_completed_at` and `affidavit_filed_at`, a cure
        period's `opened_at`, and a challenge's `filed_at`. Moving the clock
        re-evaluates every subsequent window comparison, so a test can walk a
        petition past its circulation deadline simply by advancing the clock.
        Instants already stamped on stored resources are never rewritten when
        the clock moves."

        PRD §2.7: "`created_at` (string): an ISO 8601 UTC timestamp with three
        fractional digits, for example `2025-05-24T10:30:00.123Z`, recording
        when the resource was first created."

        Design: Corner/endpoints/logical_clock_stamps_creates_and_mutating_action_endpoints
        """
        set_clock(CREATE_CLOCK)

        county = register_county("ALPHA", 20)
        voter = add_voter(county["id"], "VA1", registration_status="ACTIVE")
        circulator = register_circulator(
            full_name="Cora Carter", is_paid=True, employer_name="Signature Co"
        )

        for label, resource in (
            ("county", county),
            ("voter_record", voter),
            ("circulator", circulator),
        ):
            assert_millisecond_instant(resource["created_at"], f"{label}.created_at")
            assert_instants_equal(resource["created_at"], CREATE_CLOCK, f"{label}.created_at")

        for label, resource in (("county", county), ("voter_record", voter)):
            assert "updated_at" not in resource, f"{label} must not carry updated_at"
            assert "version" not in resource, f"{label} must not carry version"

        assert_millisecond_instant(circulator["updated_at"], "circulator.updated_at")
        assert_instants_equal(circulator["updated_at"], circulator["created_at"])
        assert isinstance(circulator["version"], int)
        assert circulator["paid_disclosure_on_file"] is False, (
            "PRD §3.3: a paid circulator with no filed document is not covered yet"
        )

        set_clock(MUTATE_CLOCK)

        assert_instants_equal(
            validate_success(api_client.get_county(county["id"], make_sos_admin_headers()))[
                "created_at"
            ],
            CREATE_CLOCK,
            "county.created_at after the clock moved",
        )
        assert_instants_equal(
            validate_success(
                api_client.get_voter_record(voter["id"], make_sos_admin_headers())
            )["created_at"],
            CREATE_CLOCK,
            "voter_record.created_at after the clock moved",
        )
        reread_circulator = read_circulator(circulator["id"])
        assert_instants_equal(reread_circulator["created_at"], CREATE_CLOCK)
        assert_instants_equal(
            reread_circulator["updated_at"],
            CREATE_CLOCK,
            "circulator.updated_at — a clock move is not a mutation",
        )
        assert reread_circulator["version"] == circulator["version"]

    def test_the_two_put_actions_restamp_only_the_managed_resource(self):
        """Moving a voter between registration states neither stamps
        `updated_at` nor bumps `version`; filing a paid disclosure does both.

        PRD §3.1: "Because `VoterRecord` is a configuration resource, this write
        neither stamps an `updated_at` nor bumps a `version` — see §2.7."

        PRD §2.7: "`version` (integer): a server-managed counter that increments
        by one on every mutation of the resource, derived-counter mutations
        included."

        Design: Corner/endpoints/logical_clock_stamps_creates_and_mutating_action_endpoints
        """
        set_clock(CREATE_CLOCK)
        county = register_county("ALPHA", 20)
        voter = add_voter(county["id"], "VA1", registration_status="ACTIVE")
        circulator = register_circulator(
            full_name="Cora Carter", is_paid=True, employer_name="Signature Co"
        )
        version_before = circulator["version"]

        set_clock(MUTATE_CLOCK)

        moved = validate_success(
            api_client.set_voter_registration_status(
                voter["id"],
                registration_status_payload("INACTIVE"),
                make_county_clerk_headers(county["id"]),
            )
        )
        assert moved["registration_status"] == "INACTIVE"
        assert moved["id"] == voter["id"]
        assert_instants_equal(moved["created_at"], CREATE_CLOCK, "voter_record.created_at")
        assert "updated_at" not in moved, "PRD §3.1: this write stamps no updated_at"
        assert "version" not in moved, "PRD §3.1: this write bumps no version"
        assert (
            validate_success(api_client.get_voter_record(voter["id"], make_sos_admin_headers()))
            == moved
        ), "the read-back must agree with the write's own response"

        disclosed = validate_success(
            api_client.file_paid_disclosure(
                circulator["id"],
                paid_disclosure_payload("DISC-1", employer_name="Signature Co LLC"),
                make_circulator_agent_headers(circulator["id"]),
            )
        )
        assert disclosed["disclosure_document_id"] == "DISC-1"
        assert disclosed["employer_name"] == "Signature Co LLC"
        assert disclosed["paid_disclosure_on_file"] is True
        assert disclosed["registration_status"] == "PENDING_TRAINING", (
            "filing the disclosure is not a registration transition"
        )
        assert_instants_equal(disclosed["created_at"], CREATE_CLOCK, "circulator.created_at")
        assert_millisecond_instant(disclosed["updated_at"], "circulator.updated_at")
        assert_instants_equal(disclosed["updated_at"], MUTATE_CLOCK, "circulator.updated_at")
        assert disclosed["version"] == version_before + 1
        assert read_circulator(circulator["id"]) == disclosed


def _listing_world():
    """Two cleared petitions of one standard, one circulator holding an
    assignment on each, and one batch per petition — the first affidavit-verified
    with two lines, the second left `RECEIVED` with one line."""
    set_clock(CLOCK_EPOCH)
    standard = register_standard(jurisdiction_code="SOS-L")
    alpha = register_county("ALPHA", 20)
    add_voter(alpha["id"], "VA1", registration_status="ACTIVE")
    add_voter(alpha["id"], "VB2", registration_status="ACTIVE")

    petition_one = create_cleared_petition(
        standard["id"],
        proponent_user_id="prop-1",
        measure_subject_codes=("TAX",),
        submitted_title="Measure One",
    )
    petition_two = create_cleared_petition(
        standard["id"],
        proponent_user_id="prop-2",
        measure_subject_codes=("ENVIRONMENT",),
        submitted_title="Measure Two",
    )
    assert petition_one["status"] == "CLEARED"
    assert petition_two["status"] == "CLEARED"

    circulator = create_registered_circulator(full_name="Cora Carter")
    assignment_one = create_assignment(
        petition_one["id"],
        circulator["id"],
        assigned_county_codes=("ALPHA",),
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-08-31T00:00:00Z",
    )
    assignment_two = create_assignment(
        petition_two["id"],
        circulator["id"],
        assigned_county_codes=("ALPHA",),
        effective_from="2026-09-10T00:00:00Z",
        effective_to="2026-09-30T00:00:00Z",
    )
    assert assignment_one["status"] == "ACTIVE"
    assert assignment_two["status"] == "ACTIVE"

    batch_one = file_batch(
        petition_one["id"], circulator["id"], alpha["id"], proponent_user_id="prop-1"
    )
    line_one = add_line(
        batch_one["id"],
        line_number=1,
        claimed_voter_id_number="VA1",
        signed_on="2026-08-05T00:00:00Z",
        proponent_user_id="prop-1",
    )
    line_two = add_line(
        batch_one["id"],
        line_number=2,
        claimed_voter_id_number="VB2",
        signed_on="2026-08-06T00:00:00Z",
        proponent_user_id="prop-1",
    )
    batch_one = verify_batch_affidavit(batch_one["id"], alpha["id"])
    assert batch_one["status"] == "AFFIDAVIT_VERIFIED"

    set_clock(BATCH_TWO_CLOCK)
    batch_two = file_batch(
        petition_two["id"], circulator["id"], alpha["id"], proponent_user_id="prop-2"
    )
    line_three = add_line(
        batch_two["id"],
        line_number=1,
        claimed_voter_id_number="VA1",
        signed_on="2026-09-11T00:00:00Z",
        proponent_user_id="prop-2",
    )
    assert batch_two["status"] == "RECEIVED"

    return {
        "standard": standard,
        "county": alpha,
        "petition_one": petition_one,
        "petition_two": petition_two,
        "circulator": circulator,
        "assignment_one": assignment_one,
        "assignment_two": assignment_two,
        "batch_one": batch_one,
        "batch_two": batch_two,
        "lines_one": [line_one, line_two],
        "line_three": line_three,
    }


class TestListEndpointsFilterByEveryDeclaredReference:
    """Each list endpoint narrows by every reference §3 declares for it, reports
    the filtered `total_count`, and answers an unmatched filter with an empty
    page rather than a 404."""

    def test_batch_and_line_lists_narrow_by_each_declared_filter(self):
        """`/signature-batches` narrows by `petition_id`, `circulator_id`,
        `county_id`, `status` and `is_supplemental`; `/signature-records` by
        `batch_id`, `validation_status` and `in_sample`.

        PRD §3.5: "Batches are readable individually and as a list narrowable by
        `petition_id`, `circulator_id`, `county_id`, `cure_period_id`, `status`
        or `is_supplemental`."

        PRD §3.5: "Lines are readable individually and as a list narrowable by
        `batch_id`, `matched_voter_record_id`, `duplicate_of_signature_id`,
        `validated_in_round_id`, `validation_status` or `in_sample`."

        PRD §2.3: "A filter narrows the result set to rows whose corresponding
        field equals the supplied value; supplying several filters narrows on all
        of them together."

        Design: Corner/endpoints/list_endpoints_filter_by_every_declared_reference
        """
        world = _listing_world()
        admin = make_sos_admin_headers()
        one = world["batch_one"]["id"]
        two = world["batch_two"]["id"]

        rows, meta = validate_paginated(
            api_client.list_signature_batches(
                admin, params={"petition_id": world["petition_one"]["id"]}
            )
        )
        assert _ids(rows) == {one}
        assert meta["total_count"] == 1

        rows, meta = validate_paginated(
            api_client.list_signature_batches(
                admin,
                params={"petition_id": world["petition_two"]["id"], "status": "RECEIVED"},
            )
        )
        assert _ids(rows) == {two}
        assert meta["total_count"] == 1

        rows, meta = validate_paginated(
            api_client.list_signature_batches(
                admin,
                params={"petition_id": world["petition_one"]["id"], "status": "RECEIVED"},
            )
        )
        assert rows == [], "the verified batch is no longer RECEIVED"
        assert meta["total_count"] == 0

        rows, _ = validate_paginated(
            api_client.list_signature_batches(admin, params={"county_id": world["county"]["id"]})
        )
        assert _ids(rows) == {one, two}, "both batches were filed with ALPHA"

        rows, _ = validate_paginated(
            api_client.list_signature_batches(
                admin, params={"circulator_id": world["circulator"]["id"]}
            )
        )
        assert _ids(rows) == {one, two}, "one circulator swore both batches"

        rows, meta = validate_paginated(
            api_client.list_signature_batches(admin, params={"is_supplemental": "true"})
        )
        assert rows == [], "no supplemental batch exists in this world"
        assert meta["total_count"] == 0

        rows, _ = validate_paginated(
            api_client.list_signature_batches(admin, params={"is_supplemental": "false"})
        )
        assert _ids(rows) == {one, two}

        rows, meta = validate_paginated(
            api_client.list_signature_records(admin, params={"batch_id": one})
        )
        assert _ids(rows) == {line["id"] for line in world["lines_one"]}
        assert {row["line_number"] for row in rows} == {1, 2}
        assert world["line_three"]["id"] not in _ids(rows), (
            "the other batch's line 1 must not leak through the batch filter"
        )
        assert meta["total_count"] == 2

        rows, meta = validate_paginated(
            api_client.list_signature_records(
                admin, params={"batch_id": one, "in_sample": "true"}
            )
        )
        assert rows == [], "no round has drawn a sample yet"
        assert meta["total_count"] == 0

        rows, meta = validate_paginated(
            api_client.list_signature_records(
                admin, params={"batch_id": two, "validation_status": "PENDING"}
            )
        )
        assert _ids(rows) == {world["line_three"]["id"]}
        assert meta["total_count"] == 1

        rows, meta = validate_paginated(
            api_client.list_signature_records(
                admin, params={"batch_id": two, "validation_status": "VALID"}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_assignment_round_petition_and_circulator_lists_narrow_the_same_way(self):
        """`/circulation-assignments` narrows by `petition_id`, `circulator_id`
        and `status`; `/verification-rounds` returns an empty page for a petition
        with no round; `/petitions` narrows by `standard_id` and `status`; and
        `/circulators` by `registration_status` and `is_paid`.

        PRD §3.3: "An assignment begins at `ACTIVE`; assignments are readable
        individually and as a list narrowable by `petition_id`, `circulator_id`
        or `status`."

        PRD §3.5: "Rounds are assigned a 1-based `round_index` in creation order
        within their petition, begin at `OPEN`, and are readable individually and
        as a list narrowable by `petition_id`, `cure_period_id`, `round_type`,
        `status` or `determination`."

        PRD §3.3: "Circulators are readable individually and as a list narrowable
        by `registration_status` or by `is_paid`."

        Design: Corner/endpoints/list_endpoints_filter_by_every_declared_reference
        """
        world = _listing_world()
        admin = make_sos_admin_headers()
        first = world["assignment_one"]["id"]
        second = world["assignment_two"]["id"]

        rows, meta = validate_paginated(
            api_client.list_circulation_assignments(
                admin, params={"circulator_id": world["circulator"]["id"]}
            )
        )
        assert _ids(rows) == {first, second}
        assert meta["total_count"] == 2

        rows, meta = validate_paginated(
            api_client.list_circulation_assignments(
                admin,
                params={"petition_id": world["petition_two"]["id"], "status": "ACTIVE"},
            )
        )
        assert _ids(rows) == {second}
        assert meta["total_count"] == 1

        rows, meta = validate_paginated(
            api_client.list_circulation_assignments(admin, params={"status": "TERMINATED"})
        )
        assert rows == [], "nothing has been terminated"
        assert meta["total_count"] == 0

        rows, meta = validate_paginated(
            api_client.list_verification_rounds(
                admin, params={"petition_id": world["petition_one"]["id"]}
            )
        )
        assert rows == [], "a petition with no round yields an empty page, not a 404"
        assert meta["total_count"] == 0
        assert meta["has_more"] is False

        rows, meta = validate_paginated(
            api_client.list_petitions(
                admin, params={"standard_id": world["standard"]["id"], "status": "CLEARED"}
            )
        )
        assert _ids(rows) == {world["petition_one"]["id"], world["petition_two"]["id"]}
        assert meta["total_count"] == 2

        rows, meta = validate_paginated(
            api_client.list_petitions(admin, params={"status": "DRAFT"})
        )
        assert rows == [], "both petitions were walked out of DRAFT"
        assert meta["total_count"] == 0

        rows, meta = validate_paginated(
            api_client.list_circulators(admin, params={"registration_status": "REGISTERED"})
        )
        assert _ids(rows) == {world["circulator"]["id"]}
        assert meta["total_count"] == 1

        rows, _ = validate_paginated(
            api_client.list_circulators(admin, params={"is_paid": "false"})
        )
        assert _ids(rows) == {world["circulator"]["id"]}

        rows, meta = validate_paginated(
            api_client.list_circulators(admin, params={"is_paid": "true"})
        )
        assert rows == [], "the only circulator is unpaid"
        assert meta["total_count"] == 0


class TestStaleVersionsRejectedOnBothConcurrencyRules:
    """The only two version-echoing writes in the system refuse a replayed echo
    with 412, change nothing, and accept the same write once the client re-reads."""

    def test_the_title_summary_write_refuses_a_replayed_petition_version(self):
        """A second preparation from the pre-bump view is refused with
        `ERR_STALE_PETITION_VERSION` and 412, leaves title and summary as the
        first write left them, and succeeds on the refreshed version.

        PRD §2.9: "`PUT /petitions/{petition_id}/title-summary` requires
        `expected_petition_version` in its request body. The field is not
        optional — omitting it is a request-shape violation. Its value must equal
        the target petition's current `version`. If another writer has advanced
        the petition's `version` since the client last read it, the write is
        refused with `ERR_STALE_PETITION_VERSION` and HTTP 412, and neither
        `official_title` nor `official_summary` is touched. On success the
        petition's `version` increments by one, so a client that intends to
        revise the title twice must re-read the petition between the two writes."

        Design: Corner/complexity_layers/stale_versions_rejected_on_both_concurrency_rules
        """
        set_clock(CLOCK_EPOCH)
        standard = register_standard(jurisdiction_code="SOS-V")
        petition = file_petition(standard["id"], measure_subject_codes=("TAX",))
        submit_petition(petition["id"])
        petition = decide_format(petition["id"], "APPROVE")
        assert petition["status"] == "TITLE_PENDING"
        assert petition["official_title"] is None
        stale_version = petition["version"]

        first = validate_success(
            api_client.put_title_summary(
                petition["id"],
                title_summary_payload(
                    stale_version,
                    official_title="First Revision",
                    official_summary="The first official summary.",
                ),
                make_title_examiner_headers(),
            )
        )
        assert first["official_title"] == "First Revision"
        assert first["official_summary"] == "The first official summary."
        assert first["status"] == "TITLE_PENDING", (
            "PRD §3.2: title preparation is a self-transition"
        )
        assert first["version"] == stale_version + 1

        validate_error(
            api_client.put_title_summary(
                petition["id"],
                title_summary_payload(
                    stale_version,
                    official_title="Replayed Revision",
                    official_summary="A summary written from a stale view.",
                ),
                make_title_examiner_headers(),
            ),
            "ERR_STALE_PETITION_VERSION",
            412,
        )

        untouched = read_petition(petition["id"])
        assert untouched["official_title"] == "First Revision"
        assert untouched["official_summary"] == "The first official summary."
        assert untouched["version"] == stale_version + 1, (
            "a refused write is not a mutation"
        )

        second = validate_success(
            api_client.put_title_summary(
                petition["id"],
                title_summary_payload(
                    untouched["version"],
                    official_title="Second Revision",
                    official_summary="The second official summary.",
                ),
                make_title_examiner_headers(),
            )
        )
        assert second["official_title"] == "Second Revision"
        assert second["official_summary"] == "The second official summary."
        assert second["version"] == stale_version + 2
        assert second["status"] == "TITLE_PENDING"

    def test_the_assignment_create_refuses_a_replayed_circulator_version(self):
        """A second assignment attempted from the pre-bump circulator view is
        refused with `ERR_STALE_CIRCULATOR_VERSION` and 412 even though its
        window clears the buffer on both sides, and succeeds after a re-read.

        PRD §2.9: "`POST /circulation-assignments` requires
        `expected_circulator_version` in its request body, likewise
        non-optional, carrying the client's last observed `version` of the
        `Circulator` named by `circulator_id`. A mismatch with that circulator's
        current `version` refuses the create with
        `ERR_STALE_CIRCULATOR_VERSION` and HTTP 412. A successful create
        increments the circulator's `version` by one, which is precisely why a
        client scripting several assignments for one circulator must re-read the
        circulator between them."

        Design: Corner/complexity_layers/stale_versions_rejected_on_both_concurrency_rules
        """
        set_clock(CLOCK_EPOCH)
        standard = register_standard(jurisdiction_code="SOS-V2")
        register_county("ALPHA", 20)
        petition_one = create_cleared_petition(
            standard["id"], measure_subject_codes=("TAX",), submitted_title="Measure One"
        )
        petition_two = create_cleared_petition(
            standard["id"],
            measure_subject_codes=("ENVIRONMENT",),
            submitted_title="Measure Two",
        )
        circulator = create_registered_circulator(full_name="Cora Carter")
        stale_version = circulator["version"]

        first = validate_success(
            api_client.create_circulation_assignment(
                create_assignment_payload(
                    petition_one["id"],
                    circulator["id"],
                    stale_version,
                    assigned_county_codes=["ALPHA"],
                    effective_from="2026-08-01T00:00:00Z",
                    effective_to="2026-08-10T00:00:00Z",
                ),
                make_sos_admin_headers(),
            ),
            201,
        )
        assert first["status"] == "ACTIVE"
        assert first["petition_id"] == petition_one["id"]
        bumped = read_circulator(circulator["id"])
        assert bumped["version"] == stale_version + 1

        # 2026-08-20 is seven days clear of 2026-08-10, so the three-day buffer
        # of §3.3 cannot be what refuses this create.
        validate_error(
            api_client.create_circulation_assignment(
                create_assignment_payload(
                    petition_two["id"],
                    circulator["id"],
                    stale_version,
                    assigned_county_codes=["ALPHA"],
                    effective_from="2026-08-20T00:00:00Z",
                    effective_to="2026-08-31T00:00:00Z",
                ),
                make_sos_admin_headers(),
            ),
            "ERR_STALE_CIRCULATOR_VERSION",
            412,
        )

        rows, meta = validate_paginated(
            api_client.list_circulation_assignments(
                make_sos_admin_headers(), params={"circulator_id": circulator["id"]}
            )
        )
        assert _ids(rows) == {first["id"]}, "the refused create stored nothing"
        assert meta["total_count"] == 1
        assert read_circulator(circulator["id"])["version"] == stale_version + 1

        retried = validate_success(
            api_client.create_circulation_assignment(
                create_assignment_payload(
                    petition_two["id"],
                    circulator["id"],
                    bumped["version"],
                    assigned_county_codes=["ALPHA"],
                    effective_from="2026-08-20T00:00:00Z",
                    effective_to="2026-08-31T00:00:00Z",
                ),
                make_sos_admin_headers(),
            ),
            201,
        )
        assert retried["status"] == "ACTIVE"
        assert retried["petition_id"] == petition_two["id"]
        assert read_circulator(circulator["id"])["version"] == stale_version + 2

        rows, meta = validate_paginated(
            api_client.list_circulation_assignments(
                make_sos_admin_headers(), params={"circulator_id": circulator["id"]}
            )
        )
        assert _ids(rows) == {first["id"], retried["id"]}
        assert meta["total_count"] == 2
