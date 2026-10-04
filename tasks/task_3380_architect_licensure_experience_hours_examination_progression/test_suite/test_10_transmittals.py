"""Transmittal lifecycle: certificate-state gate, duplicates, denial,
disciplinary block and release (PRD §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, create_jurisdiction,
    file_disciplinary_report, make_candidate_headers,
    make_ncarb_admin_headers, run_expiry_sweep, set_clock,
    setup_certificate_holder, validate_error, validate_success,
)

J1 = "J1"
NCARB = TEST_USERS["ncarb_admin_headers"]
BOARD = TEST_USERS["board_admin_headers"]


def _request_transmittal(api, ctx, jurisdiction_code):
    return api.create_transmittal(
        ctx["certificate"]["id"], {"jurisdiction_code": jurisdiction_code},
        make_candidate_headers(ctx["candidate"]["id"]),
    )


class TestTransmittalRequiresCertificateActive:
    def test_transmittal_succeeds_while_certificate_active(self, api):
        """PRD §3.8: "The request names a `jurisdiction_code` that must
        resolve to an existing jurisdiction, requires the certificate to be
        `ACTIVE` at request time (otherwise `ERR_CERTIFICATE_NOT_ACTIVE`)".
        PRD §3.8: "A new transmittal is `REQUESTED` with `denial_reason`
        null."

        Design: Difficulty/cross_entity_state_dependency/transmittal_requires_certificate_active
        """
        ctx = setup_certificate_holder(jurisdiction_code=J1)
        create_jurisdiction(code="J2", name="Board Two")
        data = validate_success(
            _request_transmittal(api, ctx, "J2"), expected_status=201,
        )
        assert data["status"] == "REQUESTED"
        assert data["denial_reason"] is None
        assert data["certificate_id"] == ctx["certificate"]["id"]

    def test_transmittal_rejected_after_certificate_lapses(self, api):
        """PRD §3.8: "The request names a `jurisdiction_code` that must
        resolve to an existing jurisdiction, requires the certificate to be
        `ACTIVE` at request time (otherwise `ERR_CERTIFICATE_NOT_ACTIVE`)".
        PRD §3.7: "When the expiry sweep finds an `ACTIVE` certificate whose
        `period_end` has been reached — the current date on or after
        `period_end` — the certificate becomes `LAPSED` regardless of how many
        continuing-education hours it holds; CE sufficiency only matters at
        renewal time."

        Design: Difficulty/cross_entity_state_dependency/transmittal_requires_certificate_active
        """
        ctx = setup_certificate_holder(jurisdiction_code=J1)
        create_jurisdiction(code="J2", name="Board Two")
        create_jurisdiction(code="J3", name="Board Three")
        # While ACTIVE the first transmittal succeeds.
        first = validate_success(
            _request_transmittal(api, ctx, "J2"), expected_status=201,
        )
        assert first["status"] == "REQUESTED"
        # Period end 2028-10-06 reached: the sweep lapses the certificate.
        set_clock("2028-10-06T00:00:00Z")
        sweep = run_expiry_sweep()
        assert sweep["lapsed_certificates"] == 1
        cert = validate_success(api.get_certificate(
            ctx["certificate"]["id"], NCARB,
        ))
        assert cert["status"] == "LAPSED"
        validate_error(
            _request_transmittal(api, ctx, "J3"),
            ApiErrorId.ERR_CERTIFICATE_NOT_ACTIVE,
        )


class TestTransmittalLifecycleAndDisciplinaryBlock:
    def test_transmittal_lifecycle_and_disciplinary_block(self, api):
        """PRD §3.8: "Only one unanswered transmittal per destination may
        exist: a second request to the same jurisdiction while one is still
        `REQUESTED` is rejected with `ERR_TRANSMITTAL_DUPLICATE`."
        PRD §3.8: "A `DENY` requires a non-empty `denial_reason` (its absence
        is an `ERR_INVALID_REQUEST`), moves the transmittal to
        `LICENSE_DENIED` with the reason recorded, and leaves the candidate
        free to request a fresh transmittal to the same jurisdiction
        afterwards."
        PRD §3.8: "is refused while any `OPEN` disciplinary report stands
        against the candidate with `ERR_OPEN_DISCIPLINARY_BLOCK`."
        PRD §3.8: "A `CLEAR` outcome moves the report to `RESOLVED_CLEAR` and
        changes nothing about standing or certificates."

        Design: Corner/validations/transmittal_lifecycle_and_disciplinary_block
        """
        ctx = setup_certificate_holder(jurisdiction_code=J1)
        create_jurisdiction(code="J2", name="Board Two")
        create_jurisdiction(code="J3", name="Board Three")
        candidate = ctx["candidate"]

        # Duplicate REQUESTED to the same board is rejected.
        t_a = validate_success(
            _request_transmittal(api, ctx, "J2"), expected_status=201,
        )
        validate_error(
            _request_transmittal(api, ctx, "J2"),
            ApiErrorId.ERR_TRANSMITTAL_DUPLICATE,
        )
        # DENY without a reason is a request-shape error; the transmittal
        # survives it and can then be properly denied.
        validate_error(
            api.decide_transmittal(t_a["id"], {"outcome": "DENY"}, BOARD),
            ApiErrorId.ERR_INVALID_REQUEST,
        )
        denied = validate_success(api.decide_transmittal(
            t_a["id"],
            {"outcome": "DENY", "denial_reason": "incomplete file"},
            BOARD,
        ))
        assert denied["status"] == "LICENSE_DENIED"
        assert denied["denial_reason"] == "incomplete file"
        # A denied board accepts a fresh request.
        t_b = validate_success(
            _request_transmittal(api, ctx, "J2"), expected_status=201,
        )
        assert t_b["status"] == "REQUESTED"
        # An OPEN disciplinary report blocks new transmittals.
        report = file_disciplinary_report(
            candidate, "J3", allegation="ethics complaint",
            filed_by="board-admin-3",
        )
        assert report["status"] == "OPEN"
        validate_error(
            _request_transmittal(api, ctx, "J3"),
            ApiErrorId.ERR_OPEN_DISCIPLINARY_BLOCK,
        )
        # Resolving CLEAR lifts the block.
        resolved = validate_success(api.resolve_disciplinary_report(
            report["id"],
            {"outcome": "CLEAR", "resolution_notes": "unfounded"},
            make_ncarb_admin_headers("ncarb-9"),
        ))
        assert resolved["status"] == "RESOLVED_CLEAR"
        t_c = validate_success(
            _request_transmittal(api, ctx, "J3"), expected_status=201,
        )
        assert t_c["status"] == "REQUESTED"
