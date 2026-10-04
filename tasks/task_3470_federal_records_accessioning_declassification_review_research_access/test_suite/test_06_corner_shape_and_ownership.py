"""Corner coverage: transfer method/metadata compatibility, entity-backed
ownership, schedule shape gates, and description completeness."""

import test_helpers as th

E = th.ApiErrorId


def test_metadata_standard_mismatch_at_create(api):
    """PRD §3.2: "The `transfer_method` is `PHYSICAL` or `ELECTRONIC`; the
    `metadata_standard` is one of `EAD_2002`, `MODS_3_7`, or `PREMIS_3_0`. An
    `ELECTRONIC` transfer requires the `PREMIS_3_0` standard, while a
    `PHYSICAL` transfer requires `EAD_2002` or `MODS_3_7`; an incompatible
    pairing is rejected with `ERR_METADATA_STANDARD_MISMATCH` (422)."

    Design: Corner/validations/metadata_standard_mismatch_at_create
    """
    th.set_clock()
    agency = th.create_agency()
    schedule = th.create_approved_schedule(agency, schedule_number="SCH-DOJ-002")
    officer = th.make_records_officer_headers(agency["id"])

    electronic_wrong = th.transfer_payload(
        schedule["id"], agency["id"],
        transfer_method="ELECTRONIC", metadata_standard="EAD_2002",
        unit_count=10,
    )
    th.validate_error(api.create_transfer(electronic_wrong, headers=officer),
                      E.ERR_METADATA_STANDARD_MISMATCH)

    physical_wrong = th.transfer_payload(
        schedule["id"], agency["id"],
        transfer_method="PHYSICAL", metadata_standard="PREMIS_3_0",
        unit_count=10, linear_feet=2.0,
    )
    th.validate_error(api.create_transfer(physical_wrong, headers=officer),
                      E.ERR_METADATA_STANDARD_MISMATCH)

    data, meta = th.validate_paginated(
        api.list_transfers(
            headers=th.TEST_USERS["processing_archivist_headers"],
            params={"schedule_id": schedule["id"]},
        )
    )
    assert data == []
    assert meta["total_count"] == 0


def test_method_requirement_missing_at_create(api):
    """PRD §3.2: "Each method also has a required payload: a `PHYSICAL`
    transfer must supply `linear_feet` greater than zero, and an `ELECTRONIC`
    transfer must supply a non-empty `checksum_manifest` reference; a missing
    or empty requirement is rejected with `ERR_METHOD_REQUIREMENT_MISSING`
    (422)."

    Design: Corner/validations/method_requirement_missing_at_create
    """
    th.set_clock()
    agency = th.create_agency()
    schedule = th.create_approved_schedule(agency, schedule_number="SCH-DOJ-002")
    officer = th.make_records_officer_headers(agency["id"])

    electronic_no_manifest = th.transfer_payload(
        schedule["id"], agency["id"],
        transfer_method="ELECTRONIC", metadata_standard="PREMIS_3_0",
        unit_count=10, checksum_manifest=None,
    )
    th.validate_error(api.create_transfer(electronic_no_manifest, headers=officer),
                      E.ERR_METHOD_REQUIREMENT_MISSING)

    physical_no_feet = th.transfer_payload(
        schedule["id"], agency["id"],
        transfer_method="PHYSICAL", metadata_standard="EAD_2002",
        unit_count=10, linear_feet=None,
    )
    th.validate_error(api.create_transfer(physical_no_feet, headers=officer),
                      E.ERR_METHOD_REQUIREMENT_MISSING)


def test_ownership_mismatch_three_ways(api):
    """PRD §2.1: "When `X-User-Role` is `RecordsOfficer`, `X-User-ID` is the
    `id` of the acting `Agency`, and ownership checks on any resource that
    references an agency compare that resource's `agency_id` field to
    `X-User-ID`. The same rule applies when `X-User-Role` is `AgencyLiaison`:
    `X-User-ID` is the `id` of the acting `Agency`, and an `AgencyLiaison`
    responds only for referrals addressed to that agency. A mismatch on any
    ownership-gated operation is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP
    403)."
    PRD §2.1: "When `X-User-Role` is `Researcher`, `X-User-ID` is the `id` of
    the acting `ResearcherRegistration`; ownership checks on a pull,
    reproduction, FOIA, or mandatory-review request compare the resource's
    `researcher_id` (or `requester_researcher_id`) field to `X-User-ID`."

    Design: Corner/validations/ownership_mismatch_three_ways
    """
    th.set_clock()
    ctx = th.setup_in_progress_mdr_with_referral()
    agency = ctx["agency"]               # the reviewing collection's agency
    referral_agency = ctx["referral_agency"]
    referral = ctx["referral"]
    ada = ctx["researcher"]
    bob = th.create_active_researcher(
        "Bob Press", "bob@example.org", "JOURNALIST", "PP-2002"
    )
    public_bundle = th.setup_public_described_collection(
        agency=agency, schedule_kwargs={"schedule_number": "SCH-DOJ-200"}
    )

    # RecordsOfficer of one agency cannot create a schedule for another.
    th.validate_error(
        api.create_schedule(
            th.schedule_payload(referral_agency["id"], schedule_number="SCH-CIA-900",
                                title="Not my agency"),
            headers=th.make_records_officer_headers(agency["id"]),
        ),
        E.ERR_OWNERSHIP_MISMATCH,
    )

    # A researcher cannot file a pull under another researcher's id.
    th.validate_error(
        api.create_pull_request(
            th.pull_request_payload(ada["id"], public_bundle["collection"]["id"],
                                    1, 5, "2026-09-10T00:00:00Z"),
            headers=th.make_researcher_headers(bob["id"]),
        ),
        E.ERR_OWNERSHIP_MISMATCH,
    )

    # An AgencyLiaison cannot answer another agency's referral.
    th.validate_error(
        api.respond_to_referral(
            referral["id"], th.respond_referral_payload("DECLASSIFY"),
            headers=th.make_agency_liaison_headers(agency["id"]),
        ),
        E.ERR_OWNERSHIP_MISMATCH,
    )


def test_schedule_not_approved_and_not_permanent(api):
    """PRD §3.2: "Two business-shape rules attach to the schedule at this
    point: it must be `APPROVED` (`ERR_SCHEDULE_NOT_APPROVED`, 409) and its
    disposition must be `PERMANENT` (`ERR_NOT_PERMANENT_DISPOSITION`, 409) — a
    temporary schedule can never underlie a transfer."

    Design: Corner/validations/schedule_not_approved_and_not_permanent
    """
    th.set_clock()
    agency = th.create_agency()
    officer = th.make_records_officer_headers(agency["id"])

    pending = th.create_draft_schedule(
        agency, schedule_number="SCH-DOJ-040", title="Pending one"
    )
    pending = th.submit_schedule(pending)

    temporary = th.create_approved_schedule(
        agency, schedule_number="SCH-DOJ-041", title="Disposable one",
        disposition="TEMPORARY", transfer_lag_years=None,
    )

    th.validate_error(
        api.create_transfer(
            th.transfer_payload(pending["id"], agency["id"], unit_count=5,
                                linear_feet=1.0),
            headers=officer,
        ),
        E.ERR_SCHEDULE_NOT_APPROVED,
    )
    th.validate_error(
        api.create_transfer(
            th.transfer_payload(temporary["id"], agency["id"], unit_count=5,
                                linear_feet=1.0),
            headers=officer,
        ),
        E.ERR_NOT_PERMANENT_DISPOSITION,
    )

    data, meta = th.validate_paginated(
        api.list_transfers(
            headers=th.TEST_USERS["processing_archivist_headers"],
            params={"agency_id": agency["id"]},
        )
    )
    assert data == []
    assert meta["total_count"] == 0


def test_description_incomplete_rejected(api):
    """PRD §3.4: "While `PROCESSING`, the archivist completes the description
    by supplying the three description elements — `scope_note`,
    `arrangement_note`, and `container_list_summary` — all of which must be
    non-empty; if any is missing or empty, the call is rejected with
    `ERR_DESCRIPTION_INCOMPLETE` (422)."

    Design: Corner/validations/description_incomplete_rejected
    """
    th.set_clock()
    bundle = th.create_collection_bundle()
    collection = th.begin_processing(bundle["collection"])
    archivist = th.TEST_USERS["processing_archivist_headers"]

    th.validate_error(
        api.complete_description(
            collection["id"], th.description_payload(scope_note=""),
            headers=archivist,
        ),
        E.ERR_DESCRIPTION_INCOMPLETE,
    )

    after = th.read_collection(collection["id"])
    assert after["processing_status"] == "PROCESSING"
