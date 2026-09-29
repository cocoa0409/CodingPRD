"""Who may act, whose badge is honoured, which version they must hold, and when a cascade becomes visible."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors, factories
from test_helpers.api_client import same_instant
from test_helpers.assertions import assert_number_equals
from test_helpers.constants import (
    CALC_STATUS_APPROVED,
    CALC_STATUS_DRAFT,
    CALC_STATUS_SUBMITTED,
    CERT_STATUS_ACTIVE,
    COMPONENT_HEAD,
    COMPONENT_SHELL,
    DEFAULT_CLOCK_UTC,
    FORM_TYPE_U1,
    JOB_STATUS_DESIGN_REVIEW,
    JOB_STATUS_DRAFT,
    JOB_STATUS_FAB_PLANNING,
    REQUIRED_COMPONENTS_HEAT_EXCHANGER,
    REQUIRED_TEST_SIDES_HEAT_EXCHANGER,
    ROLE_CODE_AUTHORIZED_INSPECTOR,
    ROLE_CODE_QC_INSPECTOR,
    ROLE_CODE_WELDING_ENGINEER,
    ROLE_DESIGN_ENGINEER,
    ROLE_QC_INSPECTOR,
    ROLE_SHOP_ADMIN,
    ROLE_WELDING_ENGINEER,
    RT_EXTENT_FULL,
    RT_EXTENT_SPOT,
    VESSEL_TYPE_HEAT_EXCHANGER,
)
from test_helpers.test_users import (
    headers_blank_user_id,
    headers_missing_user_id,
    headers_no_authentication,
    headers_undeclared_role,
    make_authorized_inspector_headers,
    make_design_engineer_headers,
    make_headers,
    make_qc_inspector_headers,
    make_welding_engineer_headers,
)


def test_each_role_is_locked_out_of_the_operations_another_role_owns(client, shop, admin_headers):
    """Five capacities are each pointed at another capacity's exclusive operation, and the role gate answers before the body is even inspected.

    PRD §2.1: "A request whose declared role is well formed but does not appear in the permitted-role list for the endpoint it targets is rejected with `ERR_ROLE_NOT_PERMITTED` (403); §4 lists those permissions endpoint by endpoint."

    PRD §2.8: "**Role permission.** The declared role appears in the endpoint's permitted-role list — otherwise `ERR_ROLE_NOT_PERMITTED` (403)."

    PRD §2.8: "**Request shape.** The body parses as JSON, every required field is present and non-null, every field carries its declared type, enum fields carry a declared value, decimal fields respect their declared scale, instant fields are ISO 8601 UTC instants and date fields are ISO 8601 calendar dates, quantities declared strictly positive are strictly positive, `limit` sits in the range 1 to 100 and `offset` is zero or greater, and `weld_ids` is an array whose entries are distinct."

    PRD §2.8: "**Body-reference existence.** Every identifier carried in the request body resolves to a live row, validated in the field order the endpoint declares — `certificate_id`, then `heat_id`, then `wps_id`, then `welder_qualification_id`, then `part_a_id`, then `part_b_id`, then `repair_of_weld_id`, then the entries of `weld_ids` — otherwise `ERR_CERTIFICATE_NOT_FOUND`, `ERR_HEAT_NOT_FOUND`, `ERR_WPS_NOT_FOUND`, `ERR_QUALIFICATION_NOT_FOUND`, `ERR_PART_NOT_FOUND` or `ERR_WELD_NOT_FOUND` (404)."

    PRD §4: "| POST | `/personnel` | Register a shop person and the single functional role they may act as. The returned id is the value callers put in `X-User-ID`. | `ShopAdmin` |"

    PRD §4: "| POST | `/vessel-jobs` | Open a vessel or heat-exchanger job under a certificate. | `ShopAdmin` |"

    PRD §4: "| POST | `/certificates` | Record a Certificate of Authorization and the code stamp scopes it confers. | `ShopAdmin` |"

    PRD §4: "| POST | `/vessel-jobs/{job_id}/design-calculations` | Prepare a code calculation sheet for one pressure component. A sheet for a component that already has one supersedes it and returns the job to `DRAFT`, which is why the call is version-guarded on the job. | `DesignEngineer` |"

    PRD §4: "| POST | `/material-heats` | Receive a heat of material with its mill test report values. | `QCInspector` |"

    PRD §4: "| POST | `/vessel-jobs/{job_id}/parts` | Issue a piece of material from an accepted heat to a job, drawing down the heat's mass ledger. | `WeldingEngineer` |"

    PRD §4: "| POST | `/wps` | Draft a welding procedure specification. | `WeldingEngineer` |"

    Design: Corner/rbac/rbac_exclusive_operations_are_forbidden_to_every_other_role
    """
    design_engineer = shop.design_engineer()
    welding_engineer = shop.welding_engineer()
    qc_inspector = shop.qc_inspector()
    authorized_inspector = shop.authorized_inspector()
    certificate = shop.certificate(cert_number="CA-U-8935")
    job = shop.job(certificate, job_number="J-2885-C53", mawp_psi=350)
    guarded_version = shop.job_version(job["id"])

    # Registering people belongs to the quality manager alone.
    validate_error(
        client.register_person(
            factories.personnel_payload(
                ROLE_CODE_QC_INSPECTOR, full_name="Intruder One", stamp_initials="XZ"
            ),
            shop.acting_as(design_engineer),
        ),
        api_errors.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    # Opening a job and issuing a certificate likewise.
    validate_error(
        client.create_job(
            factories.vessel_job_payload(certificate["id"], job_number="J-2885-C54", mawp_psi=350),
            shop.acting_as(authorized_inspector),
        ),
        api_errors.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    # Preparing a sheet is the design engineer's, and owning the parent job confers nothing.
    validate_error(
        client.create_calculation(
            job["id"],
            factories.design_calculation_payload(
                guarded_version,
                component=COMPONENT_SHELL,
                allowable_stress_psi=20000,
                corrosion_allowance_in=0.0625,
                thickness_nominal_in=0.8750,
            ),
            admin_headers,
        ),
        api_errors.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    # Receiving material is the inspector's.
    validate_error(
        client.create_heat(
            factories.material_heat_payload(heat_number="H-7200"),
            shop.acting_as(welding_engineer),
        ),
        api_errors.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    # Issuing material is the welding engineer's, and the refusal precedes the
    # body-reference check that the deliberately wrong heat identifier would trip.
    validate_error(
        client.issue_part(
            job["id"],
            factories.part_payload(
                certificate["id"], part_mark="SH-X1", issued_quantity_lb=100.00
            ),
            shop.acting_as(design_engineer),
        ),
        api_errors.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    # Drafting a procedure is the welding engineer's, and the role gate answers
    # before the shape gate even though the body is empty.
    validate_error(
        client.create_wps({}, shop.acting_as(qc_inspector)),
        api_errors.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    # A body that both duplicates a certificate number and omits required fields
    # still reports the role, not the duplicate and not the shape.
    validate_error(
        client.create_certificate(
            {"cert_number": "CA-U-8935", "scope_codes": []}, shop.acting_as(qc_inspector)
        ),
        api_errors.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    _, people_meta = validate_paginated(client.list_people(admin_headers, params={"limit": 20}))
    assert people_meta["total_count"] == 4

    _, heat_meta = validate_paginated(client.list_heats(admin_headers))
    assert heat_meta["total_count"] == 0

    _, wps_meta = validate_paginated(client.list_wps(admin_headers))
    assert wps_meta["total_count"] == 0

    _, certificate_meta = validate_paginated(client.list_certificates(admin_headers))
    assert certificate_meta["total_count"] == 1

    _, job_meta = validate_paginated(client.list_jobs(admin_headers))
    assert job_meta["total_count"] == 1

    _, part_meta = validate_paginated(client.list_parts(admin_headers, params={"job_id": job["id"]}))
    assert part_meta["total_count"] == 0

    _, sheet_meta = validate_paginated(
        client.list_calculations(admin_headers, params={"job_id": job["id"]})
    )
    assert sheet_meta["total_count"] == 0

    untouched = shop.read_job(job["id"])
    assert untouched["version"] == guarded_version
    assert untouched["status"] == JOB_STATUS_DRAFT


def test_every_capacity_reads_the_same_job_and_the_reads_change_nothing(client, shop, admin_headers):
    """One read is issued under all five capacities — including the opaque one, which carries no identity at all — and every answer is the same record.

    PRD §2.1: "Every `GET` endpoint in the system is readable by all five roles."

    PRD §4: "Endpoints whose authorized roles read *All roles* are open to all five of `ShopAdmin`, `DesignEngineer`, `WeldingEngineer`, `QCInspector` and `AuthorizedInspector`."

    PRD §2.1: "When `X-User-Role` is `ShopAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity."

    PRD §2.1: "The server may accept and log it, but it never resolves it against a `Personnel` row and never compares it to any entity's `id`."

    PRD §3.2: "`required_components` — the design components that must each carry an approved calculation sheet before fabrication can be released — is `SHELL` and `HEAD` for a `PRESSURE_VESSEL`, and `SHELL`, `HEAD` and `TUBESHEET` for a `HEAT_EXCHANGER`."

    PRD §3.2: "`required_test_sides` — the pressure boundaries that must each reach a passing test — is `SHELL_SIDE` alone for a `PRESSURE_VESSEL`, and `SHELL_SIDE` together with `TUBE_SIDE` for a `HEAT_EXCHANGER`."

    PRD §3.2: "The job opens at `status` `DRAFT` with `governing_joint_efficiency` null, `nonconformance_open_count` at 0, `weld_completion_pct` at 0.00 and `design_release_at` null."

    PRD §3.1: "A fresh certificate opens at `status` `ACTIVE` with `open_major_findings_count` and `open_minor_findings_count` at 0, `renewal_count` at 0, `last_audit_closed_on` null and `stamping_authorized` true."

    PRD §3.2: "The `id` the registry returns is exactly the value that person will put in `X-User-ID`, and people can be listed with an optional `role_code` filter."

    PRD §2.4: "`version` is an integer that starts at 1 when the record is created and increments by exactly 1 on every mutation of that record, whether the mutation was requested directly by a client or applied by the server as a cascade from somewhere else."

    Design: Corner/rbac/rbac_shared_read_surface_is_open_to_all_five_declared_roles
    """
    design_engineer = shop.design_engineer()
    welding_engineer = shop.welding_engineer()
    qc_inspector = shop.qc_inspector()
    authorized_inspector = shop.authorized_inspector()
    certificate = shop.certificate(cert_number="CA-U-8936")
    opened = shop.job(
        certificate,
        job_number="J-2885-C55",
        vessel_type=VESSEL_TYPE_HEAT_EXCHANGER,
        mawp_psi=350,
    )

    read_by_admin = validate_success(client.get_job(opened["id"], admin_headers), 200)
    read_by_design = validate_success(
        client.get_job(opened["id"], shop.acting_as(design_engineer)), 200
    )
    read_by_welding = validate_success(
        client.get_job(opened["id"], shop.acting_as(welding_engineer)), 200
    )
    read_by_qc = validate_success(client.get_job(opened["id"], shop.acting_as(qc_inspector)), 200)
    read_by_ai = validate_success(
        client.get_job(opened["id"], shop.acting_as(authorized_inspector)), 200
    )

    assert read_by_admin["status"] == JOB_STATUS_DRAFT
    assert read_by_admin["required_components"] == REQUIRED_COMPONENTS_HEAT_EXCHANGER
    assert read_by_admin["required_test_sides"] == REQUIRED_TEST_SIDES_HEAT_EXCHANGER
    assert read_by_admin["version"] == 1
    assert read_by_design == read_by_admin
    assert read_by_welding == read_by_admin
    assert read_by_qc == read_by_admin
    assert read_by_ai == read_by_admin

    # The opaque capacity is not backed by a person, so it needs no identity header.
    read_without_identity = validate_success(
        client.get_job(opened["id"], headers_missing_user_id(ROLE_SHOP_ADMIN)), 200
    )
    assert read_without_identity == read_by_admin

    # List reads are shared too, and are not scoped to the capacity that wrote the row.
    active_certificates, certificate_meta = validate_paginated(
        client.list_certificates(
            shop.acting_as(welding_engineer),
            params={"status": CERT_STATUS_ACTIVE, "limit": 10, "offset": 0},
        )
    )
    assert certificate_meta["total_count"] == 1
    assert [row["id"] for row in active_certificates] == [certificate["id"]]

    inspectors, personnel_meta = validate_paginated(
        client.list_people(
            shop.acting_as(design_engineer),
            params={"role_code": ROLE_CODE_AUTHORIZED_INSPECTOR, "limit": 10, "offset": 0},
        )
    )
    assert personnel_meta["total_count"] == 1
    assert inspectors[0]["id"] == authorized_inspector["id"]
    assert inspectors[0]["ai_agency"] == "Hartford Steam Boiler"

    after_all_reads = validate_success(client.get_job(opened["id"], admin_headers), 200)
    assert after_all_reads["version"] == 1
    assert after_all_reads == read_by_admin


def test_a_request_with_no_usable_credentials_is_turned_away_before_anything_else(
    client, shop, admin_headers
):
    """A missing role header, an invented role name and a person-backed role with no identity are all refused at the door, even when the same request is defective further in.

    PRD §2.1: "A request whose `X-User-Role` is absent or is not one of those five strings, or whose `X-User-ID` is absent or blank where the role is backed by a person record, is rejected with `ERR_UNAUTHENTICATED` (401)."

    PRD §2.1: "Five roles exist and their spelling is exact: `ShopAdmin`, `DesignEngineer`, `WeldingEngineer`, `QCInspector` and `AuthorizedInspector`."

    PRD §2.8: "**Authentication.** Headers present and well formed — otherwise `ERR_UNAUTHENTICATED` (401)."

    PRD §2.8: "**Role permission.** The declared role appears in the endpoint's permitted-role list — otherwise `ERR_ROLE_NOT_PERMITTED` (403)."

    PRD §2.8: "Otherwise `ERR_INVALID_REQUEST` (400)."

    PRD §2.1: "When `X-User-Role` is `ShopAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity."

    Design: Corner/rbac/rbac_unauthenticated_requests_are_refused_before_every_other_gate
    """
    shop.design_engineer()
    certificate = shop.certificate(cert_number="CA-U-8937")
    job = shop.job(certificate, job_number="J-2885-C56", mawp_psi=350)
    guarded_version = shop.job_version(job["id"])

    # A pure read of an existing row still needs a declared capacity.
    validate_error(
        client.get_job(job["id"], headers_no_authentication()),
        api_errors.ERR_UNAUTHENTICATED,
        401,
    )

    # A role name outside the five declared strings never reaches the permitted-role list.
    validate_error(
        client.get_job(job["id"], headers_undeclared_role()),
        api_errors.ERR_UNAUTHENTICATED,
        401,
    )

    # A person-backed role is not an identity on its own.
    validate_error(
        client.create_calculation(
            job["id"],
            factories.design_calculation_payload(
                guarded_version,
                component=COMPONENT_SHELL,
                allowable_stress_psi=20000,
                corrosion_allowance_in=0.0625,
                thickness_nominal_in=0.8750,
            ),
            headers_missing_user_id(ROLE_DESIGN_ENGINEER),
        ),
        api_errors.ERR_UNAUTHENTICATED,
        401,
    )

    # A blank identity is treated exactly as an absent one.
    validate_error(
        client.get_job(job["id"], headers_blank_user_id(ROLE_WELDING_ENGINEER)),
        api_errors.ERR_UNAUTHENTICATED,
        401,
    )

    # Defective in two ways at once: the outermost gate is the one that answers.
    validate_error(
        client.create_heat({}, headers_missing_user_id(ROLE_QC_INSPECTOR)),
        api_errors.ERR_UNAUTHENTICATED,
        401,
    )

    # The opaque capacity is exempt from the identity requirement.
    validate_success(
        client.get_certificate(certificate["id"], headers_missing_user_id(ROLE_SHOP_ADMIN)), 200
    )

    _, sheet_meta = validate_paginated(
        client.list_calculations(admin_headers, params={"job_id": job["id"]})
    )
    assert sheet_meta["total_count"] == 0

    _, heat_meta = validate_paginated(client.list_heats(admin_headers))
    assert heat_meta["total_count"] == 0

    untouched = shop.read_job(job["id"])
    assert untouched["version"] == guarded_version
    assert untouched["status"] == JOB_STATUS_DRAFT


def test_a_badge_that_does_not_match_its_holder_is_refused_ahead_of_the_role_list(
    client, shop, admin_headers
):
    """A well-formed header pair whose two halves disagree is refused on both writes and reads, and the two registry carve-outs still go through.

    PRD §2.1: "For those four person-backed roles the `X-User-ID` must resolve to an existing `Personnel` row whose `role_code` matches the declared `X-User-Role` — `DESIGN_ENGINEER` for `DesignEngineer`, `WELDING_ENGINEER` for `WeldingEngineer`, `QC_INSPECTOR` for `QCInspector` and `AUTHORIZED_INSPECTOR` for `AuthorizedInspector`."

    PRD §2.1: "A mismatch, or an `X-User-ID` that names no person at all, is rejected with `ERR_IDENTITY_ROLE_MISMATCH` (403)."

    PRD §2.1: "This identity resolution is applied on every endpoint except the two that necessarily precede or stand outside the person registry: registering a person at `POST /personnel` and moving the clock at `POST /_clock/set_current_utc`, both of which are `ShopAdmin`-only anyway."

    PRD §2.8: "**Identity resolution.** `X-User-ID` resolves to a `Personnel` row whose `role_code` matches the declared role, on every endpoint except `POST /personnel` and `POST /_clock/set_current_utc` — otherwise `ERR_IDENTITY_ROLE_MISMATCH` (403)."

    PRD §2.8: "**Role permission.** The declared role appears in the endpoint's permitted-role list — otherwise `ERR_ROLE_NOT_PERMITTED` (403)."

    PRD §4: "| POST | `/vessel-jobs` | Open a vessel or heat-exchanger job under a certificate. | `ShopAdmin` |"

    PRD §4: "| POST | `/personnel` | Register a shop person and the single functional role they may act as. The returned id is the value callers put in `X-User-ID`. | `ShopAdmin` |"

    PRD §2.5: "Before any client moves it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time."

    Design: Corner/rbac/rbac_identity_role_mismatch_is_rejected_and_outranks_the_role_gate
    """
    design_engineer = shop.design_engineer()
    welding_engineer = shop.welding_engineer()
    qc_inspector = shop.qc_inspector()
    shop.authorized_inspector()
    certificate = shop.certificate(cert_number="CA-U-8938")
    job = shop.job(certificate, job_number="J-2885-C57", mawp_psi=350)
    guarded_version = shop.job_version(job["id"])

    # The identity resolves to an inspector while the header claims an engineer.
    validate_error(
        client.create_calculation(
            job["id"],
            factories.design_calculation_payload(
                guarded_version,
                component=COMPONENT_SHELL,
                allowable_stress_psi=20000,
                corrosion_allowance_in=0.0625,
                thickness_nominal_in=0.8750,
            ),
            make_design_engineer_headers(qc_inspector["id"]),
        ),
        api_errors.ERR_IDENTITY_ROLE_MISMATCH,
        403,
    )

    # A faultless body does not rescue a mismatched pair.
    validate_error(
        client.create_heat(
            factories.material_heat_payload(heat_number="H-7300"),
            make_qc_inspector_headers(welding_engineer["id"]),
        ),
        api_errors.ERR_IDENTITY_ROLE_MISMATCH,
        403,
    )

    # The shared read surface is gated on identity as well.
    validate_error(
        client.get_job(job["id"], make_authorized_inspector_headers(design_engineer["id"])),
        api_errors.ERR_IDENTITY_ROLE_MISMATCH,
        403,
    )

    # An identity that names no person at all is a mismatch, not a missing record.
    validate_error(
        client.create_wps(
            factories.wps_payload(wps_number="WPS-200"),
            make_welding_engineer_headers(certificate["id"]),
        ),
        api_errors.ERR_IDENTITY_ROLE_MISMATCH,
        403,
    )

    # Identity resolution precedes the permitted-role list, so the mismatch is
    # reported even though this capacity may never open a job.
    validate_error(
        client.create_job(
            factories.vessel_job_payload(
                certificate["id"], job_number="J-2885-C58", mawp_psi=350
            ),
            make_design_engineer_headers(welding_engineer["id"]),
        ),
        api_errors.ERR_IDENTITY_ROLE_MISMATCH,
        403,
    )

    # Carve-out one: the person registry is exempt from identity resolution, so a
    # mismatched pair there is answered by the role gate instead.
    validate_error(
        client.register_person(
            factories.personnel_payload(
                ROLE_CODE_WELDING_ENGINEER, full_name="Ola Beck", stamp_initials="OB"
            ),
            make_design_engineer_headers(qc_inspector["id"]),
        ),
        api_errors.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    # ... and the same registration goes through under the opaque capacity even
    # though its identifier names a registered inspector.
    registered = validate_success(
        client.register_person(
            factories.personnel_payload(
                ROLE_CODE_WELDING_ENGINEER, full_name="Ola Beck", stamp_initials="OB"
            ),
            make_headers(ROLE_SHOP_ADMIN, qc_inspector["id"]),
        ),
        201,
    )
    assert registered["role_code"] == ROLE_CODE_WELDING_ENGINEER

    # Carve-out two: the clock stands outside the registry as well.
    moved = validate_success(
        client.set_clock(DEFAULT_CLOCK_UTC, make_headers(ROLE_SHOP_ADMIN, qc_inspector["id"])), 200
    )
    assert same_instant(moved["current_utc"], DEFAULT_CLOCK_UTC)

    _, personnel_meta = validate_paginated(client.list_people(admin_headers, params={"limit": 20}))
    assert personnel_meta["total_count"] == 5

    _, wps_meta = validate_paginated(client.list_wps(admin_headers))
    assert wps_meta["total_count"] == 0

    _, heat_meta = validate_paginated(client.list_heats(admin_headers))
    assert heat_meta["total_count"] == 0

    _, job_meta = validate_paginated(client.list_jobs(admin_headers))
    assert job_meta["total_count"] == 1

    _, sheet_meta = validate_paginated(
        client.list_calculations(admin_headers, params={"job_id": job["id"]})
    )
    assert sheet_meta["total_count"] == 0

    untouched = shop.read_job(job["id"])
    assert untouched["version"] == guarded_version
    assert untouched["status"] == JOB_STATUS_DRAFT


def test_the_engineer_who_prepared_a_sheet_cannot_review_it_in_either_direction(client, shop):
    """Holding the reviewing capacity is necessary but not sufficient: the preparer is barred from both terminal reviews, and a colleague in the very same capacity clears the sheet at once.

    PRD §2.1: "Four operations require the acting person to differ from the person who performed the paired earlier step: approving a calculation sheet, rejecting a calculation sheet, completing a furnace charge against its chart, and signing a manufacturer's data report."

    PRD §2.1: "In all four, an attempt by the same person is refused with `ERR_SEGREGATION_OF_DUTIES` (409)."

    PRD §2.8: "**Segregation of duties.** `ERR_SEGREGATION_OF_DUTIES` (409) on calculation approve, calculation reject, furnace-charge complete and data-report signature."

    PRD §2.8: "**Role permission.** The declared role appears in the endpoint's permitted-role list — otherwise `ERR_ROLE_NOT_PERMITTED` (403)."

    PRD §3.3: "Creation answers 201 with the sheet at `status` `DRAFT`, `prepared_by_personnel_id` set to the acting `X-User-ID`, `reviewed_by_personnel_id` null and `reject_reason` null."

    PRD §3.3: "Approval moves the sheet `SUBMITTED → APPROVED` and requires that the acting `X-User-ID` differ from the sheet's `prepared_by_personnel_id`; the same engineer approving their own arithmetic is refused with `ERR_SEGREGATION_OF_DUTIES`."

    PRD §3.3: "It moves the sheet `SUBMITTED → REJECTED`, requires that the acting `X-User-ID` differ from `prepared_by_personnel_id` under the same `ERR_SEGREGATION_OF_DUTIES`, and additionally requires a non-blank `reject_reason` in the request."

    PRD §4: "| POST | `/design-calculations/{calculation_id}/approve` | Approve a submitted sheet. The reviewer must be a different `DesignEngineer` from the preparer. | `DesignEngineer` |"

    PRD §4: "| POST | `/design-calculations/{calculation_id}/reject` | Reject a submitted sheet with a reason. The reviewer must be a different `DesignEngineer` from the preparer. | `DesignEngineer` |"

    Design: Corner/rbac/rbac_segregation_of_duties_bars_a_preparer_from_reviewing_their_own_sheet
    """
    preparer = shop.design_engineer()
    reviewer = shop.reviewing_design_engineer()
    inspector = shop.qc_inspector()
    certificate = shop.certificate(cert_number="CA-U-8939")
    job = shop.job(certificate, job_number="J-2885-C59", mawp_psi=350)

    sheet = shop.prepare_sheet(
        job["id"],
        COMPONENT_SHELL,
        preparer=preparer,
        rt_extent_declared=RT_EXTENT_FULL,
        allowable_stress_psi=20000,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=0.8750,
    )
    assert sheet["prepared_by_personnel_id"] == preparer["id"]
    assert sheet["status"] == CALC_STATUS_DRAFT
    submitted = shop.submit_sheet(sheet["id"], preparer=preparer)
    assert submitted["status"] == CALC_STATUS_SUBMITTED

    # The preparer cannot approve their own arithmetic.
    validate_error(
        client.approve_calculation(sheet["id"], shop.acting_as(preparer)),
        api_errors.ERR_SEGREGATION_OF_DUTIES,
        409,
    )

    # Nor force the sheet out of review the other way.
    validate_error(
        client.reject_calculation(
            sheet["id"],
            factories.reject_payload(reject_reason="Second thoughts about the corrosion allowance"),
            shop.acting_as(preparer),
        ),
        api_errors.ERR_SEGREGATION_OF_DUTIES,
        409,
    )

    # A capacity outside the reviewing one never reaches the duties check.
    validate_error(
        client.approve_calculation(sheet["id"], shop.acting_as(inspector)),
        api_errors.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    inert = validate_success(client.get_calculation(sheet["id"], shop.admin), 200)
    assert inert["status"] == CALC_STATUS_SUBMITTED
    assert inert["reviewed_by_personnel_id"] is None
    assert inert["reject_reason"] is None

    # The independent review succeeds for a colleague holding exactly the same capacity.
    approved = validate_success(
        client.approve_calculation(sheet["id"], shop.acting_as(reviewer)), 200
    )
    assert approved["status"] == CALC_STATUS_APPROVED
    assert approved["reviewed_by_personnel_id"] == reviewer["id"]
    assert approved["prepared_by_personnel_id"] == preparer["id"]
    assert reviewer["role_code"] == preparer["role_code"]
    assert reviewer["id"] != preparer["id"]


def test_a_job_scoped_write_holding_a_superseded_job_version_is_refused_and_writes_nothing(
    client, shop, admin_headers
):
    """Sending the sheet to review moves the guard the client is holding, so the next job-scoped write is refused on both version-guarded endpoints — and the refusals cost nothing, so the retry on the fresh guard goes through.

    PRD §2.7: "Preparing a design calculation sheet — `POST /vessel-jobs/{job_id}/design-calculations` — must carry `expected_job_version` matching the current `version` of the `VesselJob` named in the path."

    PRD §2.7: "When `expected_job_version` differs from the job's current `version`, the request is rejected with `ERR_STALE_JOB_VERSION` (412) and nothing is written."

    PRD §2.7: "Assembling a manufacturer's data report — `POST /vessel-jobs/{job_id}/data-report` — must likewise carry `expected_job_version` matching the job's current `version`, because a second assembly voids the first."

    PRD §2.7: "A mismatch is rejected with `ERR_STALE_JOB_VERSION` (412)."

    PRD §2.8: "**Stale version.** The optimistic-concurrency field matches the parent's current `version` on the three endpoints of §2.7 — otherwise `ERR_STALE_JOB_VERSION` or `ERR_STALE_CERTIFICATE_VERSION` (412)."

    PRD §3.3: "A successful submit carries the job `DRAFT → DESIGN_REVIEW` and increments both records' versions."

    PRD §3.3: "`revision` is a system-maintained index scoped to the pairing of job and `component`: the first sheet for a component is revision 1, and each superseding sheet starts at one more than the revision of the sheet it supersedes."

    PRD §3.3: "Creation answers 201 with the sheet at `status` `DRAFT`, `prepared_by_personnel_id` set to the acting `X-User-ID`, `reviewed_by_personnel_id` null and `reject_reason` null."

    PRD §2.10: "Callers holding a job `version` for optimistic-concurrency purposes must expect it to advance whenever any of the job's roll-ups move."

    Design: Corner/cross_cutting_complexity_layers/layer_optimistic_concurrency_guards_every_job_scoped_write
    """
    engineer = shop.design_engineer()
    inspector = shop.qc_inspector()
    certificate = shop.certificate(cert_number="CA-U-8940")
    job = shop.job(certificate, job_number="J-2885-C60", mawp_psi=350)

    shell = shop.prepare_sheet(
        job["id"],
        COMPONENT_SHELL,
        preparer=engineer,
        rt_extent_declared=RT_EXTENT_FULL,
        allowable_stress_psi=20000,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=0.8750,
    )
    # The guard the client last observed, before the sheet went to review.
    observed_version = shop.job_version(job["id"])

    shop.submit_sheet(shell["id"], preparer=engineer)
    advanced = shop.read_job(job["id"])
    assert advanced["status"] == JOB_STATUS_DESIGN_REVIEW
    assert advanced["version"] == observed_version + 1

    head_body = factories.design_calculation_payload(
        observed_version,
        component=COMPONENT_HEAD,
        rt_extent_declared=RT_EXTENT_FULL,
        allowable_stress_psi=20000,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=0.8750,
    )
    validate_error(
        client.create_calculation(job["id"], head_body, shop.acting_as(engineer)),
        api_errors.ERR_STALE_JOB_VERSION,
        412,
    )

    # The other endpoint carrying the same field answers with the same error id.
    validate_error(
        client.assemble_data_report(
            job["id"],
            factories.data_report_payload(observed_version, form_type=FORM_TYPE_U1),
            shop.acting_as(inspector),
        ),
        api_errors.ERR_STALE_JOB_VERSION,
        412,
    )

    unconsumed = shop.read_job(job["id"])
    assert unconsumed["version"] == advanced["version"]
    assert unconsumed["status"] == JOB_STATUS_DESIGN_REVIEW

    _, sheet_meta = validate_paginated(
        client.list_calculations(admin_headers, params={"job_id": job["id"]})
    )
    assert sheet_meta["total_count"] == 1

    _, report_meta = validate_paginated(
        client.list_data_reports(admin_headers, params={"job_id": job["id"]})
    )
    assert report_meta["total_count"] == 0

    fresh_body = factories.design_calculation_payload(
        shop.job_version(job["id"]),
        component=COMPONENT_HEAD,
        rt_extent_declared=RT_EXTENT_FULL,
        allowable_stress_psi=20000,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=0.8750,
    )
    head = validate_success(
        client.create_calculation(job["id"], fresh_body, shop.acting_as(engineer)), 201
    )
    assert head["component"] == COMPONENT_HEAD
    assert head["revision"] == 1
    assert head["status"] == CALC_STATUS_DRAFT
    assert head["prepared_by_personnel_id"] == engineer["id"]
    assert head["reviewed_by_personnel_id"] is None

    sheets, after_meta = validate_paginated(
        client.list_calculations(admin_headers, params={"job_id": job["id"], "limit": 10})
    )
    assert after_meta["total_count"] == 2
    assert sorted(row["component"] for row in sheets) == [COMPONENT_HEAD, COMPONENT_SHELL]

    _, still_no_reports = validate_paginated(
        client.list_data_reports(admin_headers, params={"job_id": job["id"]})
    )
    assert still_no_reports["total_count"] == 0


def test_the_last_approval_publishes_the_whole_release_cascade_before_it_answers(
    client, shop, admin_headers
):
    """The approve that completes the required set carries the job into planning inside its own request: the very next read, with no wait and no second write, already shows the release instant and the re-derived efficiency.

    PRD §2.10: "Every computed field is recomputed inside the request that changes any of its inputs, and re-evaluated whenever a read returns the record that owns it."

    PRD §2.10: "Cascades run in the same request as the operation that triggers them, and each record a cascade touches is itself mutated: its `updated_at` is refreshed and its `version` increments by 1."

    PRD §3.3: "On approval the reviewer's identity is written to `reviewed_by_personnel_id`, the job's `governing_joint_efficiency` is recomputed as the smallest `joint_efficiency` across the job's approved sheets, and — once **every** component listed in the job's `required_components` carries exactly one `APPROVED` sheet — the job moves `DESIGN_REVIEW → FAB_PLANNING` with `design_release_at` stamped to the current logical UTC instant."

    PRD §3.3: "Approval moves the sheet `SUBMITTED → APPROVED` and requires that the acting `X-User-ID` differ from the sheet's `prepared_by_personnel_id`; the same engineer approving their own arithmetic is refused with `ERR_SEGREGATION_OF_DUTIES`."

    PRD §3.3: "`joint_efficiency` is resolved directly from `rt_extent_declared`: a `FULL` declaration yields 1.00, a `SPOT` declaration yields 0.85 and a `NONE` declaration yields 0.70, carried at two decimal places."

    PRD §3.2: "`governing_joint_efficiency` is the smallest `joint_efficiency` among the job's approved calculation sheets, and null while no sheet is approved."

    PRD §3.2: "`design_release_at` records the logical UTC instant the job entered `FAB_PLANNING` and is null before that ever happens."

    PRD §3.2: "`nonconformance_open_count` counts the job's nonconformance reports whose `disposition` is `OPEN`, `REPAIR` or `USE_AS_IS`; reaching 0 is what releases an examination hold."

    PRD §3.6: "The value is 0.00 when the denominator is 0, and otherwise 100 multiplied by the numerator divided by the denominator, rounded half up to two decimal places."

    PRD §2.5: "Before any client moves it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time."

    Design: Corner/consistency_model/consistency_immediate_cascade_is_visible_in_the_same_request_cycle
    """
    preparer = shop.design_engineer()
    reviewer = shop.reviewing_design_engineer()
    certificate = shop.certificate(cert_number="CA-U-8941")
    job = shop.job(certificate, job_number="J-2885-C61", mawp_psi=350)

    shell = shop.prepare_sheet(
        job["id"],
        COMPONENT_SHELL,
        preparer=preparer,
        rt_extent_declared=RT_EXTENT_FULL,
        allowable_stress_psi=20000,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=0.8750,
    )
    head = shop.prepare_sheet(
        job["id"],
        COMPONENT_HEAD,
        preparer=preparer,
        rt_extent_declared=RT_EXTENT_SPOT,
        allowable_stress_psi=20000,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=0.8750,
    )
    assert_number_equals(shell["joint_efficiency"], 1.00, 2, "joint_efficiency")
    assert_number_equals(head["joint_efficiency"], 0.85, 2, "joint_efficiency")

    shop.submit_sheet(shell["id"], preparer=preparer)
    shop.approve_sheet(shell["id"], reviewer=reviewer)
    shop.submit_sheet(head["id"], preparer=preparer)

    before = shop.read_job(job["id"])
    assert before["status"] == JOB_STATUS_DESIGN_REVIEW
    assert_number_equals(before["governing_joint_efficiency"], 1.00, 2, "governing_joint_efficiency")
    assert before["design_release_at"] is None

    # The trigger: the response body is itself already final.
    approved = validate_success(
        client.approve_calculation(head["id"], shop.acting_as(reviewer)), 200
    )
    assert approved["status"] == CALC_STATUS_APPROVED
    assert approved["reviewed_by_personnel_id"] == reviewer["id"]

    # The first read after the write, with nothing in between.
    after = validate_success(client.get_job(job["id"], shop.acting_as(preparer)), 200)
    assert after["status"] == JOB_STATUS_FAB_PLANNING
    assert after["design_release_at"] is not None
    assert same_instant(after["design_release_at"], DEFAULT_CLOCK_UTC)
    assert_number_equals(after["governing_joint_efficiency"], 0.85, 2, "governing_joint_efficiency")
    assert_number_equals(after["weld_completion_pct"], 0.00, 2, "weld_completion_pct")
    assert after["nonconformance_open_count"] == 0

    approved_sheets, approved_meta = validate_paginated(
        client.list_calculations(
            admin_headers,
            params={
                "job_id": job["id"],
                "status": CALC_STATUS_APPROVED,
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert approved_meta["total_count"] == 2
    assert sorted(row["component"] for row in approved_sheets) == [COMPONENT_HEAD, COMPONENT_SHELL]

    # Nothing settles between two identical reads.
    repeated = validate_success(client.get_job(job["id"], shop.acting_as(preparer)), 200)
    assert repeated == after
