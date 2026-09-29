"""Typed HTTP wrapper over the public access television studio API.

One method per row of the PRD's endpoint directory. Paths are rooted at the
service origin with no common prefix, so each method spells out its own path.
Every method returns the raw ``requests`` response so callers can assert on
both success envelopes and refusals.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import GenericApiClient


def _canonical_instant(value: Any) -> Any:
    """Normalise an ISO-8601 UTC instant so equality ignores fractional width.

    The PRD requires UTC instants ending in ``Z``; it does not require a fixed
    number of fractional digits on entity timestamps, so ``...T18:00:00.000Z``
    and ``...T18:00:00Z`` denote the same instant and must compare equal.
    """
    if not isinstance(value, str):
        return value
    if not value.endswith("Z"):
        return value
    body = value[:-1]
    if "." in body:
        whole, frac = body.split(".", 1)
        frac = frac.rstrip("0")
        if frac == "":
            return whole + "Z"
        return whole + "." + frac + "Z"
    return body + "Z"


class StudioApiClient(GenericApiClient):
    """Endpoint-specific client for the studio operations service."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, to_iso8601: str, headers: Optional[Dict[str, str]] = None):
        """Set the logical current UTC instant."""
        return self.post("/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers)

    # ------------------------------------------------------------ producers
    def create_producer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/producers", payload, headers=headers)

    def get_producer(self, producer_id: str, headers: Dict[str, str]):
        return self.get("/producers/{}".format(producer_id), headers=headers)

    def list_producers(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self.get("/producers", headers=headers, params=params)

    def verify_residency(self, producer_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            "/producers/{}/residency-verification".format(producer_id), payload, headers=headers
        )

    def reinstate_producer(
        self, producer_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self.post(
            "/producers/{}/reinstate".format(producer_id), payload or {}, headers=headers
        )

    def revoke_producer(
        self, producer_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self.post("/producers/{}/revoke".format(producer_id), payload or {}, headers=headers)

    # ----------------------------------------------------- training courses
    def create_training_course(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/training-courses", payload, headers=headers)

    def get_training_course(self, course_id: str, headers: Dict[str, str]):
        return self.get("/training-courses/{}".format(course_id), headers=headers)

    def list_training_courses(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get("/training-courses", headers=headers, params=params)

    # --------------------------------------------------- course enrollments
    def create_course_enrollment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/course-enrollments", payload, headers=headers)

    def get_course_enrollment(self, enrollment_id: str, headers: Dict[str, str]):
        return self.get("/course-enrollments/{}".format(enrollment_id), headers=headers)

    def list_course_enrollments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get("/course-enrollments", headers=headers, params=params)

    def record_attendance(
        self, enrollment_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self.post(
            "/course-enrollments/{}/attendance".format(enrollment_id),
            payload or {},
            headers=headers,
        )

    def grade_enrollment(
        self, enrollment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(
            "/course-enrollments/{}/grade".format(enrollment_id), payload, headers=headers
        )

    def withdraw_enrollment(
        self, enrollment_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self.post(
            "/course-enrollments/{}/withdraw".format(enrollment_id),
            payload or {},
            headers=headers,
        )

    # --------------------------------------------------------------- series
    def create_series(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/series", payload, headers=headers)

    def get_series(self, series_id: str, headers: Dict[str, str]):
        return self.get("/series/{}".format(series_id), headers=headers)

    def list_series(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self.get("/series", headers=headers, params=params)

    def activate_series(
        self, series_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self.post("/series/{}/activate".format(series_id), payload or {}, headers=headers)

    def replace_hold_plan(self, series_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/series/{}/hold-plans".format(series_id), payload, headers=headers)

    # ------------------------------------------------------------- programs
    def create_program(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/programs", payload, headers=headers)

    def get_program(self, program_id: str, headers: Dict[str, str]):
        return self.get("/programs/{}".format(program_id), headers=headers)

    def list_programs(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self.get("/programs", headers=headers, params=params)

    def append_attestation(self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            "/programs/{}/attestations".format(program_id), payload, headers=headers
        )

    def submit_program(
        self, program_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self.post("/programs/{}/submit".format(program_id), payload or {}, headers=headers)

    def claim_program_review(
        self, program_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self.post(
            "/programs/{}/review-claim".format(program_id), payload or {}, headers=headers
        )

    def decide_program_review(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(
            "/programs/{}/review-decision".format(program_id), payload, headers=headers
        )

    def withdraw_program(self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/programs/{}/withdraw".format(program_id), payload, headers=headers)

    # --------------------------------------------------------- attestations
    def get_attestation(self, attestation_id: str, headers: Dict[str, str]):
        return self.get("/attestations/{}".format(attestation_id), headers=headers)

    def list_attestations(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self.get("/attestations", headers=headers, params=params)

    # ------------------------------------------------------------- channels
    def create_channel(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/channels", payload, headers=headers)

    def get_channel(self, channel_id: str, headers: Dict[str, str]):
        return self.get("/channels/{}".format(channel_id), headers=headers)

    def list_channels(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self.get("/channels", headers=headers, params=params)

    # -------------------------------------------------------- playback slots
    def create_playback_slot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/playback-slots", payload, headers=headers)

    def get_playback_slot(self, slot_id: str, headers: Dict[str, str]):
        return self.get("/playback-slots/{}".format(slot_id), headers=headers)

    def list_playback_slots(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get("/playback-slots", headers=headers, params=params)

    def air_playback_slot(self, slot_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/playback-slots/{}/air".format(slot_id), payload, headers=headers)

    def cancel_playback_slot(
        self, slot_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self.post(
            "/playback-slots/{}/cancel".format(slot_id), payload or {}, headers=headers
        )

    # ------------------------------------------------------ crew assignments
    def create_crew_assignment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/crew-assignments", payload, headers=headers)

    def get_crew_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self.get("/crew-assignments/{}".format(assignment_id), headers=headers)

    def list_crew_assignments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get("/crew-assignments", headers=headers, params=params)

    def confirm_crew_assignment(
        self, assignment_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self.post(
            "/crew-assignments/{}/confirm".format(assignment_id), payload or {}, headers=headers
        )

    def release_crew_assignment(
        self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(
            "/crew-assignments/{}/release".format(assignment_id), payload, headers=headers
        )

    # ------------------------------------------------------ studio resources
    def create_studio_resource(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/studio-resources", payload, headers=headers)

    def get_studio_resource(self, resource_id: str, headers: Dict[str, str]):
        return self.get("/studio-resources/{}".format(resource_id), headers=headers)

    def list_studio_resources(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get("/studio-resources", headers=headers, params=params)

    def set_studio_resource_status(
        self, resource_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(
            "/studio-resources/{}/status".format(resource_id), payload, headers=headers
        )

    # --------------------------------------------------------- reservations
    def create_reservation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/reservations", payload, headers=headers)

    def get_reservation(self, reservation_id: str, headers: Dict[str, str]):
        return self.get("/reservations/{}".format(reservation_id), headers=headers)

    def list_reservations(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self.get("/reservations", headers=headers, params=params)

    def confirm_reservation(
        self, reservation_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self.post(
            "/reservations/{}/confirm".format(reservation_id), payload or {}, headers=headers
        )

    def cancel_reservation(
        self, reservation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(
            "/reservations/{}/cancel".format(reservation_id), payload, headers=headers
        )

    def checkout_reservation(
        self, reservation_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self.post(
            "/reservations/{}/checkout".format(reservation_id), payload or {}, headers=headers
        )

    def return_reservation(
        self, reservation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(
            "/reservations/{}/return".format(reservation_id), payload, headers=headers
        )

    # ----------------------------------------------------- damage assessments
    def get_damage_assessment(self, assessment_id: str, headers: Dict[str, str]):
        return self.get("/damage-assessments/{}".format(assessment_id), headers=headers)

    def list_damage_assessments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get("/damage-assessments", headers=headers, params=params)

    def finalize_damage_assessment(
        self, assessment_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self.post(
            "/damage-assessments/{}/finalize".format(assessment_id), payload or {}, headers=headers
        )

    def waive_damage_assessment(
        self, assessment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(
            "/damage-assessments/{}/waive".format(assessment_id), payload, headers=headers
        )

    # -------------------------------------------------------- funding periods
    def create_funding_period(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/funding-periods", payload, headers=headers)

    def get_funding_period(self, period_id: str, headers: Dict[str, str]):
        return self.get("/funding-periods/{}".format(period_id), headers=headers)

    def list_funding_periods(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get("/funding-periods", headers=headers, params=params)

    def revise_funding_period(
        self, period_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post("/funding-periods/{}/revise".format(period_id), payload, headers=headers)

    def submit_funding_report(
        self, period_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self.post(
            "/funding-periods/{}/report-submit".format(period_id), payload or {}, headers=headers
        )

    def decide_funding_report(
        self, period_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self.post(
            "/funding-periods/{}/report-decision".format(period_id), payload, headers=headers
        )

    # --------------------------------------------------------- archive assets
    def get_archive_asset(self, asset_id: str, headers: Dict[str, str]):
        return self.get("/archive-assets/{}".format(asset_id), headers=headers)

    def list_archive_assets(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self.get("/archive-assets", headers=headers, params=params)

    def publish_archive_asset(self, asset_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/archive-assets/{}/publish".format(asset_id), payload, headers=headers)

    def record_archive_views(self, asset_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post(
            "/archive-assets/{}/record-views".format(asset_id), payload, headers=headers
        )

    def purge_archive_asset(
        self, asset_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self.post("/archive-assets/{}/purge".format(asset_id), payload or {}, headers=headers)

    # --------------------------------------------------------- raw utilities
    def raw_get(self, path: str, headers: Optional[Dict[str, str]] = None,
                params: Optional[Dict[str, Any]] = None):
        """Escape hatch for asserting on paths that are not in the directory."""
        return self.get(path, headers=headers, params=params)

    def raw_post(self, path: str, payload: Optional[Dict[str, Any]] = None,
                 headers: Optional[Dict[str, str]] = None):
        return self.post(path, payload if payload is not None else {}, headers=headers)
