"""API client: one method per endpoint defined in the PRD."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/stroke-network"


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant so two spellings of the same moment compare equal.

    The PRD requires three fractional digits on server-assigned instants, but a
    caller-supplied instant may legitimately be echoed with or without them.
    Comparisons in tests go through this function so that
    '2026-09-01T08:00:00Z' and '2026-09-01T08:00:00.000Z' are treated as one
    instant rather than as two unequal strings.
    """
    if value is None:
        return None
    assert isinstance(value, str), f"instant must be a string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
        if frac == "000":
            return head + "Z"
        return f"{head}.{frac}Z"
    return text + "Z"


def instants_equal(left: Optional[str], right: Optional[str]) -> bool:
    """True when two ISO 8601 UTC instants denote the same moment."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """One method per endpoint of the Stroke Center Certification & Telestroke Network API."""

    # ----- Logical clock (PRD 2.4) -----------------------------------------
    def set_clock(self, current_utc: str, headers: Optional[Dict] = None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ----- Stroke centers --------------------------------------------------
    def register_stroke_center(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"{PREFIX}/stroke-centers", payload, headers)

    def get_stroke_center(self, center_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/stroke-centers/{center_id}", headers=headers
        )

    def list_stroke_centers(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/stroke-centers", headers=headers, params=params)

    def update_stroke_center(self, center_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "PATCH", f"{PREFIX}/stroke-centers/{center_id}", payload, headers
        )

    def record_readiness_attestation(
        self, center_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/stroke-centers/{center_id}/readiness-attestations",
            payload,
            headers,
        )

    def suspend_stroke_center(self, center_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/stroke-centers/{center_id}/suspend", payload, headers
        )

    # ----- Spoke agreements ------------------------------------------------
    def create_spoke_agreement(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"{PREFIX}/spoke-agreements", payload, headers)

    def get_spoke_agreement(self, agreement_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/spoke-agreements/{agreement_id}", headers=headers
        )

    def list_spoke_agreements(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/spoke-agreements", headers=headers, params=params)

    def activate_spoke_agreement(
        self, agreement_id: str, headers: Optional[Dict] = None, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/spoke-agreements/{agreement_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def suspend_spoke_agreement(
        self, agreement_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/spoke-agreements/{agreement_id}/suspend", payload, headers
        )

    def grant_proxy_credential(
        self, agreement_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/spoke-agreements/{agreement_id}/proxy-credentials",
            payload,
            headers,
        )

    # ----- Neurologists ----------------------------------------------------
    def register_neurologist(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"{PREFIX}/neurologists", payload, headers)

    def get_neurologist(self, neurologist_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/neurologists/{neurologist_id}", headers=headers)

    def list_neurologists(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/neurologists", headers=headers, params=params)

    def set_on_call_state(
        self, neurologist_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/neurologists/{neurologist_id}/on-call-state", payload, headers
        )

    # ----- Code stroke cases ----------------------------------------------
    def activate_code_stroke(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"{PREFIX}/code-strokes", payload, headers)

    def get_code_stroke(self, case_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/code-strokes/{case_id}", headers=headers)

    def list_code_strokes(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/code-strokes", headers=headers, params=params)

    def complete_imaging(self, case_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/code-strokes/{case_id}/imaging-complete", payload, headers
        )

    def administer_thrombolytic(self, case_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/code-strokes/{case_id}/administer-thrombolytic", payload, headers
        )

    def close_code_stroke(
        self, case_id: str, headers: Optional[Dict] = None, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/code-strokes/{case_id}/close",
            payload if payload is not None else {},
            headers,
        )

    def abort_code_stroke(self, case_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/code-strokes/{case_id}/abort", payload, headers
        )

    # ----- Telestroke consults --------------------------------------------
    def request_consult(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"{PREFIX}/consults", payload, headers)

    def get_consult(self, consult_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/consults/{consult_id}", headers=headers)

    def list_consults(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/consults", headers=headers, params=params)

    def accept_consult(
        self, consult_id: str, headers: Optional[Dict] = None, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/consults/{consult_id}/accept",
            payload if payload is not None else {},
            headers,
        )

    def decline_consult(self, consult_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/consults/{consult_id}/decline", payload, headers
        )

    def append_video_session(self, consult_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/consults/{consult_id}/video-sessions", payload, headers
        )

    def complete_consult(self, consult_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/consults/{consult_id}/complete", payload, headers
        )

    # ----- Thrombolytic checklists ----------------------------------------
    def create_checklist(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"{PREFIX}/checklists", payload, headers)

    def get_checklist(self, checklist_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/checklists/{checklist_id}", headers=headers)

    def list_checklists(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/checklists", headers=headers, params=params)

    def confirm_inclusion_item(self, checklist_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/checklists/{checklist_id}/inclusion-items", payload, headers
        )

    def document_contraindication(
        self, checklist_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/checklists/{checklist_id}/contraindications", payload, headers
        )

    def determine_checklist(
        self, checklist_id: str, headers: Optional[Dict] = None, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/checklists/{checklist_id}/determine",
            payload if payload is not None else {},
            headers,
        )

    def amend_checklist(self, checklist_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/checklists/{checklist_id}/amend", payload, headers
        )

    # ----- Transfer decisions ---------------------------------------------
    def propose_transfer(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"{PREFIX}/transfer-decisions", payload, headers)

    def get_transfer(self, transfer_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/transfer-decisions/{transfer_id}", headers=headers
        )

    def list_transfers(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/transfer-decisions", headers=headers, params=params
        )

    def accept_transfer(
        self, transfer_id: str, headers: Optional[Dict] = None, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/transfer-decisions/{transfer_id}/accept",
            payload if payload is not None else {},
            headers,
        )

    def decline_transfer(self, transfer_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/transfer-decisions/{transfer_id}/decline", payload, headers
        )

    def complete_handoff(self, transfer_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST",
            f"{PREFIX}/transfer-decisions/{transfer_id}/complete-handoff",
            payload,
            headers,
        )

    # ----- Protocol deviations --------------------------------------------
    def create_deviation(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"{PREFIX}/deviations", payload, headers)

    def get_deviation(self, deviation_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/deviations/{deviation_id}", headers=headers)

    def list_deviations(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/deviations", headers=headers, params=params)

    def start_deviation_review(
        self, deviation_id: str, headers: Optional[Dict] = None, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/deviations/{deviation_id}/start-review",
            payload if payload is not None else {},
            headers,
        )

    def return_deviation_for_info(
        self, deviation_id: str, payload: Dict, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/deviations/{deviation_id}/return-for-info", payload, headers
        )

    def resubmit_deviation(self, deviation_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/deviations/{deviation_id}/resubmit", payload, headers
        )

    def debrief_deviation(self, deviation_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/deviations/{deviation_id}/debrief", payload, headers
        )

    def decide_deviation(self, deviation_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/deviations/{deviation_id}/decide", payload, headers
        )

    # ----- Quality measure abstractions -----------------------------------
    def create_abstraction(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"{PREFIX}/abstractions", payload, headers)

    def get_abstraction(self, abstraction_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/abstractions/{abstraction_id}", headers=headers)

    def list_abstractions(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/abstractions", headers=headers, params=params)

    def finalize_abstraction(self, abstraction_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/abstractions/{abstraction_id}/finalize", payload, headers
        )

    def retract_abstraction(self, abstraction_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{PREFIX}/abstractions/{abstraction_id}/retract", payload, headers
        )

    # ----- Certification reports ------------------------------------------
    def create_certification_report(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"{PREFIX}/certification-reports", payload, headers)

    def get_certification_report(self, report_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/certification-reports/{report_id}", headers=headers
        )

    def list_certification_reports(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/certification-reports", headers=headers, params=params
        )

    def submit_certification_report(
        self, report_id: str, headers: Optional[Dict] = None, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/certification-reports/{report_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def decide_certification_report(
        self, report_id: str, headers: Optional[Dict] = None, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/certification-reports/{report_id}/decide",
            payload if payload is not None else {},
            headers,
        )

    def publish_certification_report(
        self, report_id: str, headers: Optional[Dict] = None, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/certification-reports/{report_id}/publish",
            payload if payload is not None else {},
            headers,
        )


api_client = ApiClient()
