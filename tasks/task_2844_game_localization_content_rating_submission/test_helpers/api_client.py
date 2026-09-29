"""One method per endpoint of the Game Localization & Rating Submission API (§4).

Every path is mounted at the root; related records are joined by foreign-key
fields carried in request bodies and by query filters on the list endpoints.
Each method returns the raw response so tests can assert on status codes.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """HTTP surface of the API under test."""

    # ─── Titles ────────────────────────────────────────────────────────

    def create_title(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/titles", payload, headers)

    def get_title(self, title_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/titles/{title_id}", None, headers)

    def list_titles(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/titles", params, headers)

    def lock_strings(self, title_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/titles/{title_id}/lock-strings", payload or {}, headers
        )

    # ─── Market plans ──────────────────────────────────────────────────

    def create_market_plan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/market-plans", payload, headers)

    def get_market_plan(self, market_plan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/market-plans/{market_plan_id}", None, headers)

    def list_market_plans(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/market-plans", params, headers)

    def scope_market_plan(self, market_plan_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/market-plans/{market_plan_id}/scope", payload or {}, headers
        )

    def start_localization(self, market_plan_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/market-plans/{market_plan_id}/start-localization",
            payload or {}, headers,
        )

    def enter_lqa(self, market_plan_id: str, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/market-plans/{market_plan_id}/enter-lqa", payload or {}, headers
        )

    def mark_release_ready(self, market_plan_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/market-plans/{market_plan_id}/mark-release-ready",
            payload or {}, headers,
        )

    def block_market_plan(self, market_plan_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/market-plans/{market_plan_id}/block", payload, headers
        )

    # ─── String keys ───────────────────────────────────────────────────

    def create_string_key(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/string-keys", payload, headers)

    def get_string_key(self, string_key_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/string-keys/{string_key_id}", None, headers)

    def list_string_keys(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/string-keys", params, headers)

    def patch_string_key(self, string_key_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/string-keys/{string_key_id}", payload, headers
        )

    # ─── Translation units ─────────────────────────────────────────────

    def get_translation_unit(self, translation_unit_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/translation-units/{translation_unit_id}", None, headers
        )

    def list_translation_units(self, headers: Dict[str, str],
                               params: Optional[Dict] = None):
        return self._request("GET", "/translation-units", params, headers)

    def write_translation_unit(self, translation_unit_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "PUT", f"/translation-units/{translation_unit_id}", payload, headers
        )

    def deliver_translation_unit(self, translation_unit_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/translation-units/{translation_unit_id}/deliver",
            payload or {}, headers,
        )

    def qa_mark_translation_unit(self, translation_unit_id: str,
                                 payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/translation-units/{translation_unit_id}/qa-mark",
            payload, headers,
        )

    # ─── Recording booths ──────────────────────────────────────────────

    def create_booth(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/booths", payload, headers)

    def get_booth(self, recording_booth_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/booths/{recording_booth_id}", None, headers)

    def list_booths(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/booths", params, headers)

    # ─── Voice talents ─────────────────────────────────────────────────

    def create_voice_talent(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/voice-talents", payload, headers)

    def get_voice_talent(self, voice_talent_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/voice-talents/{voice_talent_id}", None, headers)

    def list_voice_talents(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/voice-talents", params, headers)

    # ─── Talent contracts ──────────────────────────────────────────────

    def create_talent_contract(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/talent-contracts", payload, headers)

    def get_talent_contract(self, talent_contract_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/talent-contracts/{talent_contract_id}", None, headers
        )

    def list_talent_contracts(self, headers: Dict[str, str],
                              params: Optional[Dict] = None):
        return self._request("GET", "/talent-contracts", params, headers)

    def sign_talent_contract(self, talent_contract_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/talent-contracts/{talent_contract_id}/sign",
            payload or {}, headers,
        )

    def terminate_talent_contract(self, talent_contract_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/talent-contracts/{talent_contract_id}/terminate",
            payload or {}, headers,
        )

    # ─── Voice sessions ────────────────────────────────────────────────

    def create_voice_session(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/voice-sessions", payload, headers)

    def get_voice_session(self, voice_session_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/voice-sessions/{voice_session_id}", None, headers
        )

    def list_voice_sessions(self, headers: Dict[str, str],
                            params: Optional[Dict] = None):
        return self._request("GET", "/voice-sessions", params, headers)

    def start_voice_session(self, voice_session_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/voice-sessions/{voice_session_id}/start", payload or {}, headers
        )

    def complete_voice_session(self, voice_session_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/voice-sessions/{voice_session_id}/complete", payload, headers
        )

    def cancel_voice_session(self, voice_session_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/voice-sessions/{voice_session_id}/cancel", payload or {}, headers
        )

    # ─── QA passes ─────────────────────────────────────────────────────

    def create_qa_pass(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/qa-passes", payload, headers)

    def get_qa_pass(self, qa_pass_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/qa-passes/{qa_pass_id}", None, headers)

    def list_qa_passes(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/qa-passes", params, headers)

    def close_qa_pass(self, qa_pass_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/qa-passes/{qa_pass_id}/close", payload or {}, headers
        )

    def reopen_qa_pass(self, qa_pass_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/qa-passes/{qa_pass_id}/reopen", payload or {}, headers
        )

    # ─── Defects ───────────────────────────────────────────────────────

    def create_lqa_bug(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/lqa-bugs", payload, headers)

    def get_lqa_bug(self, lqa_bug_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/lqa-bugs/{lqa_bug_id}", None, headers)

    def list_lqa_bugs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/lqa-bugs", params, headers)

    def triage_lqa_bug(self, lqa_bug_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/lqa-bugs/{lqa_bug_id}/triage", payload, headers
        )

    def submit_fix_lqa_bug(self, lqa_bug_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/lqa-bugs/{lqa_bug_id}/submit-fix", payload or {}, headers
        )

    def verify_lqa_bug(self, lqa_bug_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/lqa-bugs/{lqa_bug_id}/verify", payload or {}, headers
        )

    # ─── Rating submissions ────────────────────────────────────────────

    def create_rating_submission(self, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request("POST", "/rating-submissions", payload, headers)

    def get_rating_submission(self, rating_submission_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "GET", f"/rating-submissions/{rating_submission_id}", None, headers
        )

    def list_rating_submissions(self, headers: Dict[str, str],
                                params: Optional[Dict] = None):
        return self._request("GET", "/rating-submissions", params, headers)

    def submit_rating_submission(self, rating_submission_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/rating-submissions/{rating_submission_id}/submit",
            payload or {}, headers,
        )

    def begin_review(self, rating_submission_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/rating-submissions/{rating_submission_id}/begin-review",
            payload or {}, headers,
        )

    def record_outcome(self, rating_submission_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/rating-submissions/{rating_submission_id}/record-outcome",
            payload, headers,
        )

    def appeal_rating_submission(self, rating_submission_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/rating-submissions/{rating_submission_id}/appeal",
            payload or {}, headers,
        )

    def withdraw_rating_submission(self, rating_submission_id: str,
                                   headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/rating-submissions/{rating_submission_id}/withdraw",
            payload or {}, headers,
        )

    # ─── Content edits ─────────────────────────────────────────────────

    def create_content_edit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/content-edits", payload, headers)

    def get_content_edit(self, content_edit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/content-edits/{content_edit_id}", None, headers)

    def list_content_edits(self, headers: Dict[str, str],
                           params: Optional[Dict] = None):
        return self._request("GET", "/content-edits", params, headers)

    def apply_content_edit(self, content_edit_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/content-edits/{content_edit_id}/apply", payload or {}, headers
        )

    def withdraw_content_edit(self, content_edit_id: str, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/content-edits/{content_edit_id}/withdraw", payload or {}, headers
        )

    # ─── Logical clock ─────────────────────────────────────────────────

    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)
