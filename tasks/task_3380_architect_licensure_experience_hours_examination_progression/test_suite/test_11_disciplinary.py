"""Disciplinary reports: segregation of duties, terminal resolution, and the
depth-3 sanction cascade (PRD §2.6, §3.8)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, create_candidate, create_jurisdiction,
    file_disciplinary_report, make_candidate_headers,
    make_ncarb_admin_headers, setup_certificate_holder, validate_error,
    validate_paginated, validate_success,
)

J1 = "J1"
NCARB = TEST_USERS["ncarb_admin_headers"]
BOARD = TEST_USERS["board_admin_headers"]


def _candidate(api):
    create_jurisdiction(code=J1)
    return create_candidate(home_jurisdiction_code=J1)


def _transmittal(api, ctx, jurisdiction_code):
    return validate_success(api.create_transmittal(
        ctx["certificate"]["id"], {"jurisdiction_code": jurisdiction_code},
        make_candidate_headers(ctx["candidate"]["id"]),
    ), expected_status=201)


def _transmittal_by_id(api, ctx, transmittal_id):
    rows, _m = validate_paginated(
        api.list_transmittals(
            ctx["certificate"]["id"],
            make_candidate_headers(ctx["candidate"]["id"]),
        )
    )
    match = [t for t in rows if t["id"] == transmittal_id]
    assert len(match) == 1
    return match[0]


class TestSegregationOfDuties:
    def test_segregation_of_duties_resolver_is_filer(self, api):
        """PRD §3.8: "Resolution belongs to `NcarbAdministrator` staff under
        a segregation-of-duties rule: the resolver's `X-User-ID` must differ
        from the report's `filed_by_user_id`, and a violation is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §3.8: "the filer's `X-User-ID` is recorded as `filed_by_user_id`,
        and the report opens as `OPEN` with `resolution_notes` null."

        Design: Corner/validations/segregation_of_duties_resolver_is_filer
        """
        candidate = _candidate(api)
        report = file_disciplinary_report(
            candidate, J1, allegation="contract violation",
            filed_by="board-admin-1",
        )
        assert report["status"] == "OPEN"
        assert report["filed_by_user_id"] == "board-admin-1"
        assert report["resolution_notes"] is None
        # The filer's own operator id cannot resolve the report, even with
        # the resolver role.
        validate_error(
            api.resolve_disciplinary_report(
                report["id"], {"outcome": "CLEAR"},
                make_ncarb_admin_headers("board-admin-1"),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )
        resolved = validate_success(api.resolve_disciplinary_report(
            report["id"], {"outcome": "CLEAR"},
            make_ncarb_admin_headers("ncarb-9"),
        ))
        assert resolved["status"] == "RESOLVED_CLEAR"


class TestResolutionTerminal:
    def test_disciplinary_double_resolve_rejected(self, api):
        """PRD §2.6: "The target resource's current state must permit the
        attempted transition; any trigger attempted from a state that does not
        list it is rejected with the generic `ERR_INVALID_STATE` (HTTP 409)."
        PRD §3.8: "A `CLEAR` outcome moves the report to `RESOLVED_CLEAR` and
        changes nothing about standing or certificates."

        Design: Corner/state_machines/disciplinary_double_resolve_rejected
        """
        candidate = _candidate(api)
        report = file_disciplinary_report(
            candidate, J1, allegation="late renewal misstatement",
            filed_by="board-admin-1",
        )
        validate_success(api.resolve_disciplinary_report(
            report["id"],
            {"outcome": "CLEAR", "resolution_notes": "unfounded"},
            make_ncarb_admin_headers("ncarb-9"),
        ))
        validate_error(
            api.resolve_disciplinary_report(
                report["id"], {"outcome": "SANCTION"},
                make_ncarb_admin_headers("ncarb-9"),
            ),
            ApiErrorId.ERR_INVALID_STATE,
        )
        rows, _m = validate_paginated(
            api.list_disciplinary_reports(candidate["id"], NCARB)
        )
        assert len(rows) == 1 and rows[0]["status"] == "RESOLVED_CLEAR"
        refreshed = validate_success(api.get_candidate(candidate["id"], NCARB))
        assert refreshed["record_standing"] == "CLEAR", "no cascade fired"


class TestSanctionDepth3Cascade:
    def _setup_sanction_scenario(self, api):
        """ACTIVE certificate; transmittal T2 REQUESTED to J2; transmittal T3
        to J3 already LICENSE_GRANTED; report filed by board-admin-1."""
        ctx = setup_certificate_holder(jurisdiction_code=J1)
        create_jurisdiction(code="J2", name="Board Two")
        create_jurisdiction(code="J3", name="Board Three")
        t2 = _transmittal(api, ctx, "J2")
        t3 = _transmittal(api, ctx, "J3")
        granted = validate_success(api.decide_transmittal(
            t3["id"], {"outcome": "GRANT"}, BOARD,
        ))
        assert granted["status"] == "LICENSE_GRANTED"
        report = file_disciplinary_report(
            ctx["candidate"], "J2",
            allegation="stamping unsupervised work", filed_by="board-admin-1",
        )
        return ctx, report, t2, t3

    def test_sanction_flags_candidate_and_revokes_certificate(self, api):
        """PRD §3.8: "A `SANCTION` outcome moves the report to
        `RESOLVED_SANCTION` and fires a three-link cascade: link one sets the
        candidate's `record_standing` to `FLAGGED`, which is terminal; link
        two, caused by link one, moves the candidate's non-`REVOKED`
        certificate — if one exists, whether `ACTIVE` or `LAPSED` — to
        `REVOKED`; link three, caused by link two, moves every `REQUESTED`
        transmittal of that certificate to `CANCELLED`, leaving
        already-terminal `LICENSE_GRANTED` and `LICENSE_DENIED` transmittals
        untouched. The cascade finishes with a recompute of
        `certificate_eligible`, which the flag's `CLEAR`-standing conjunct
        forces to false."

        Design: Difficulty/transitive_cascade/disciplinary_sanction_depth3
        """
        ctx, report, _t2, _t3 = self._setup_sanction_scenario(api)
        resolved = validate_success(api.resolve_disciplinary_report(
            report["id"],
            {"outcome": "SANCTION", "resolution_notes": "certificate revoked"},
            make_ncarb_admin_headers("ncarb-9"),
        ))
        assert resolved["status"] == "RESOLVED_SANCTION"
        candidate = validate_success(api.get_candidate(
            ctx["candidate"]["id"], NCARB,
        ))
        assert candidate["record_standing"] == "FLAGGED", "cascade link 1"
        assert candidate["certificate_eligible"] is False, (
            "record_standing no longer CLEAR"
        )
        cert = validate_success(api.get_certificate(
            ctx["certificate"]["id"], NCARB,
        ))
        assert cert["status"] == "REVOKED", "cascade link 2"

    def test_sanction_cancels_requested_but_not_terminal_transmittals(self, api):
        """PRD §3.8: "link three, caused by link two, moves every `REQUESTED`
        transmittal of that certificate to `CANCELLED`, leaving
        already-terminal `LICENSE_GRANTED` and `LICENSE_DENIED` transmittals
        untouched."

        Design: Difficulty/transitive_cascade/disciplinary_sanction_depth3
        """
        ctx, report, t2, t3 = self._setup_sanction_scenario(api)
        validate_success(api.resolve_disciplinary_report(
            report["id"],
            {"outcome": "SANCTION", "resolution_notes": "certificate revoked"},
            make_ncarb_admin_headers("ncarb-9"),
        ))
        assert _transmittal_by_id(api, ctx, t2["id"])["status"] == "CANCELLED", (
            "cascade link 3 cancels the unanswered transmittal"
        )
        assert _transmittal_by_id(api, ctx, t3["id"])["status"] == "LICENSE_GRANTED", (
            "terminal transmittal untouched by the cascade"
        )
