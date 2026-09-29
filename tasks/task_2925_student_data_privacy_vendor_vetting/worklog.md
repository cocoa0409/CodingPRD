# Worklog — task_2925_student_data_privacy_vendor_vetting

## Step 1: Create task directory — 2026-09-05T17:23:02.68484790Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2925_student_data_privacy_vendor_vetting and its workspace/ subdirectory. Index 2925 pre-assigned by the orchestrating command; no index scan performed.


## Step 2: Generate scaffold — 2026-09-05T18:59:35.305236151Z

All three scaffold artifacts are complete and the linter is clean.

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2925_student_data_privacy_vendor_vetting/`)

| file | lines |
|---|---|
| `SCAFFOLD.yaml` | 3000 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1750 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4334 |

`SCAFFOLD.yaml` top-level keys are exactly `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither design key is present; each design file has its single required top-level key.

Final lint (absolute paths, `scaffold_lint.py`):
```
  §1.5 endpoints declared:    50
  §1.1 entities declared:     11
  §1.8 instances scanned:     18
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  938

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## §1.0–§1.7 shape
11 entities (Vendor, Subprocessor, Application, Teacher, PrivacyAnalyst, ApplicationRequest, DataPracticeReview, DataElementCommitment, CatalogEntry, TelemetryDetection, VendorIncident), 50 declared endpoints plus the `POST /_clock/set_current_utc` test hook, 53 errors, 5 roles (Teacher, PrivacyAnalyst, VendorLiaison, PrivacyOfficeAdmin, TelemetryAgent), 8 state machines, 2 concurrency rules, flat topology, `immediate` consistency, complexity layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`.

## §1.8 — 9 rules x 2 instances = 18
`dual_variant_calc` 2, `combinatorial_formula` 2, `non_linear_state_machine` 2, `transitive_cascade` 2, `priority_pair_validation_conflict` 2, `boundary_precision_check` 2, `cross_entity_state_dependency` 2, `resource_temporal_overlap` 2, `compensating_invariant` 2.

## §1.9 — all 9 guide sections, 77 instances (62 with recipes, 15 `excluded_because` stubs)
entities 11+0, state_machines 14+3, calculations 6+6, validations 11+2, endpoints 6+1, errors 3+1, rbac 7+0, cross_cutting_complexity_layers 3+2, consistency_model 1+0. Every stub cites a real §1.8 instance by name and carries no `test_recipe`; all 95 instance names are globally unique across both design files.

## Design adjudications
- **Attest-after-approval deadlock**: priority-20 was widened so only `BLOCKED` applications cannot re-attest — accessibility/SSO are gated at publication time, i.e. after the review is decided, so an approved application must still be able to attest. `ERR_APPLICATION_STATE_INVALID` was rewritten to match.
- **Reassign from-state**: §1.4 priority 11 narrowed to `SCREENING` only for reassign (matching §1.2), while commitment attachment stays legal in SCREENING / FINDINGS_ISSUED / REMEDIATION_SUBMITTED.
- **Compliance-score ceiling**: with an empty ACCEPTED commitment set the score caps at 60.00 (minimization and retention both contribute 0), so three literals that asserted 100.00 were corrected to 60.00 / 60.00 / 55.00 with term-by-term derivations, and one instance gained the missing `attest-integration` call so its 100.00 legitimately stands.
- **Segregation of duties given three limbs**: the review is assigned to a LEAD and a second LEAD was added, so "decide needs LEAD" and "decider != assignee" are independently falsifiable without a reassign; the successful publisher is the assignee (a non-decider), proving the publication limb is decider-scoped rather than review-scoped.
- **OCC tokens are always re-read**: every `expected_*_version` is a captured `${var}`; the 404-beats-412 probe sends a real version with a bogus FK, and a post-sweep re-read replaces any token a sweep could have invalidated.
- **Rate threshold hit exactly**: 4 non-US subprocessors (40) + accepted GEOLOCATION 7.50 + STUDENT_ID 2.50 give load 5.00 for risk exactly 45.00 -> WATCH (the `>= 45` boundary), and rejecting the STUDENT_ID row drops it to 43.75 -> CLEAR, which also exercises the ACCEPTED -> REJECTED compensation.
- Eleven 404 probes were batched into one errors instance against `00000000-0000-4000-8000-000000000000`; the 401 test uses empty-string identity headers (never whitespace); a second vendor supplies the liaison-ownership breach; a 400-minute analyst makes the aggregate-capacity limit land exactly.
- **Difficulty-directive leak stripped**: the "Generate task harder than expert level!" line was removed from `scenario:` so it cannot reach the generated PRD; the scenario text itself is otherwise verbatim.
- Every numeric `assert:` is a literal computed against the declared formulas (spot-verified this pass: element_points 1.00/1.44/2.50/7.50, exposed 10.00 -> 7.50, risk 45.00/43.75/0.72, `reauthorization_due_at` 2028-07-02 from the 30-day lead, successor `effective_from` = predecessor `expires_at`).

Orchestrator verification: all three files present; `grep -i "harder than expert|expert level" SCAFFOLD.yaml` returns nothing, so the difficulty directive did not leak. workspace/ intact.

## Step 3: Copy shared files — 2026-09-05T18:59:40.369331183Z

Copied ./INSTRUCTION.md to tasks/task_2925_student_data_privacy_vendor_vetting/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-05T19:17:01.72237212Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — **487 lines**, 102,788 bytes. Last heading: `## 5. Error Code Catalogue`; the file ends on the final complete table row `| ERR_ANALYST_CAPACITY_EXCEEDED | 409 |`. No truncation, no mid-sentence tail, no contract-report text leaked into the document.

**Section list**
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 RBAC · 2.2 API Response Structure (verbatim, incl. the two JSON fences) · 2.3 Pagination/Sorting/Filters · 2.4 Identity, Versioning, Logical Clock · 2.5 Request Admission · 2.6 Rejection Ladder (rungs 1–42 + the out-of-ladder uniqueness rule) · 2.7 Optimistic Concurrency · 2.8 Precision & Rounding · 2.9 Privacy Posture · 2.10 Cascade Discipline · 2.11 Two Interval Conventions
- `## 3. Business Logic & Workflows` — 3.1 Registry/vendors/applications/subprocessors · 3.2 Teacher intake & triage · 3.3 Review opening & analyst workload · 3.4 Data-element commitments · 3.5 Findings & negotiation · 3.6 Terminal decision + four-hop cascade · 3.7 Catalog publication, sweep, reauthorization, revocation · 3.8 Telemetry detection & triage · 3.9 Incident response + suspend/reinstate
- `## 4. API Endpoint Specifications` — 4-column table, 50 rows
- `## 5. Error Code Catalogue` — 52 rows

**Coverage audit (machine-checked against SCAFFOLD.yaml)**
- Contract 1 (field-name coverage): 123/123 required names — 102 entity fields, 68 body fields, 26 query params, 11 path params — present as exact backtick tokens. Zero missing on the strict pass.
- Contract 2 (rule coverage): 52/52 error ids appear in §2–§3 prose (not only in the §5 table); all state-machine states across the 8 machines / 50 transitions appear in prose; every `one of …` enum value across all 11 entities appears in prose; every numeric constant from all 15 calculations appears in prose (retention caps, tier weights, decay, 30-day lead, 72h buffer, 24/48/72/168 statutory hours, 0.4/0.05 weights, class bases 0/25/45/30, thresholds 1000/100/10, etc.). All 42 validations rendered as the ordered ladder; both concurrency rules in §2.7.
- Contract 3 (§3 path purity): 282 distinct backtick tokens in §3, 0 violations.

**Adjudications carried through §3.6–§3.9** (scaffold self-conflicts resolved consistently with earlier sections): send-notification is `PrivacyOfficeAdmin`-only; `contained_at` defaults to the clock when omitted; reinstate returns to `APPROVED` or to `CONDITIONAL` if the vendor was `CONDITIONAL` pre-suspension; the reinstate restore branch reads the clock, never `hold_restored_from`; CLEAR additionally requires `subprocessor_disclosure_complete`; ESCALATE-minted incidents default `max_data_tier` to 3 and bypass the incident-window buffer rung; BLOCK/WHITELIST/ESCALATE classification preconditions are reported as `ERR_DISPOSITION_NOT_APPLICABLE`.

Orchestrator verification: `tail -25 PRD.md` ends at a complete table row of §5 (a real section boundary) — not truncated. Grep for "expert level"/"harder than expert"/"scaffold" in PRD.md returns nothing.

## Step 6: Generate implementation — 2026-09-05T19:47:17.416065738Z

(Subagent self-labelled its summary "Step 5"; it is the Step 6 implementation generator. Summary verbatim below.)

Step 5 is complete. The implementation is finished, smoke-tested, and the smoke server has been killed by its own PID (port 39251 free, nothing left running).

## Location
`/home/ubuntu/github/CodingPRD/tasks/task_2925_student_data_privacy_vendor_vetting/workspace/implementation/`

## Modules (2741 lines total)

| File | Lines |
|---|---|
| `app.py` | 65 |
| `start.sh` | 10 |
| `requirements.txt` | 1 (`Flask==3.0.3`) |
| `core/errors.py` | 73 |
| `core/store.py` | 107 |
| `core/envelope.py` | 93 |
| `core/validate.py` | 160 |
| `core/auth.py` | 69 |
| `core/logic.py` | 559 |
| `core/serialize.py` | 100 |
| `routes/vendors.py` | 135 |
| `routes/subprocessors.py` | 102 |
| `routes/applications.py` | 92 |
| `routes/people.py` | 65 |
| `routes/requests.py` | 152 |
| `routes/reviews.py` | 287 |
| `routes/commitments.py` | 121 |
| `routes/catalog.py` | 232 |
| `routes/telemetry.py` | 156 |
| `routes/incidents.py` | 144 |
| `routes/clock.py` | 16 |
| `core/__init__.py`, `routes/__init__.py` | 1 each |

**Endpoints: 50**, exactly matching the PRD §4 table (no extras — an early `GET /_health` was removed). All 52 error ids and their HTTP statuses match PRD §5.

## Boot behaviour (per-test-server safe)
`start.sh` reads `$PORT` (default 10000), binds 0.0.0.0, guards the pip install, and `exec`s the server in the foreground, so the launcher PID *is* the listening PID and one `kill` reaps it cleanly. Three consecutive cold boots each became ready in ~800 ms with completely empty state (in-memory dicts only, zero seeded entities, no disk artifacts).

## Verification
Two scratch harnesses were run against a fresh server: a 44-assertion rejection-ladder probe (44 ok / 0 fail) and an end-to-end domain walk (0 mismatches, 0 tracebacks). Hand-checked numerics all matched the PRD: element points 3.13 and 11.04, exposure 3.13, live risk 31.57 vs reauthorization risk 1.57, provisional 51.5 / final 87.5 compliance, priority raw 140 -> HIGH -> 168.00, incident CRITICAL with a 24 h deadline (min of 48 h contractual and 24 h statutory), sweep counters `{2,1,0,0,1}` then all-zero on an idempotent second run, and the closed doubly-buffered incident window rejecting a touching endpoint at exactly +72 h while accepting +9 days. Scratch dir removed.

## PRD ambiguities resolved (interpretation chosen)
- **Rung 6 scope**: guards eight operations per PRD §2.6, including `issue-findings` and `contain`, which SCAFFOLD omitted. PRD wins on every PRD/SCAFFOLD conflict.
- **Undeclared bounds**: `review_capacity_minutes` 15–12000, `data_deletion_days` 1–3650 (both from §2.3's range list); `reason`/`note` free text left unbounded because the PRD declares no length for them.
- **Initial derived values**: new Vendor `reauthorization_risk_score = 0.00`; new draft request `priority_score = 0.00`, `priority_band = LOW`.
- **Priority band**: derived from the *raw* pre-multiplier score and never re-derived from the multiplied result.
- **submit-remediation over-claiming**: `unresolved = max(0, open - resolved)` then `open = unresolved`; no error for claiming more than exist.
- **send-notification**: PrivacyOfficeAdmin only, no ownership check; `SENT` vs `SENT_LATE` chosen purely from the logical clock.
- **contain**: `contained_at` optional, defaulting to the clock.
- **ESCALATE-minted incident**: `max_data_tier` from payload else 3, `affected_student_count` from payload else `distinct_user_count`; bypasses the buffer check (PRD §3.8's explicit exemption); the triage returns 200.
- **reauthorize**: takes no `review_id` — it reuses the predecessor's review, carries over `published_review_score`, sets `effective_from = predecessor.expires_at`, requires posture in {CLEAR, WATCH}, and returns **200** (a transition, not a creation, under §4's taxonomy).
- **Clock-bound violations** on `detected_at`/`observed_at`/`contained_at` -> `ERR_INVALID_REQUEST`, evaluated as early as the data allows.
- **issue-findings** ">=1 PROPOSED/ACCEPTED commitment" -> `ERR_REVIEW_STATE_INVALID`, immediately after the status check.
- **reassign**: all three refusal conditions (same assignee, target not ACTIVE, target over capacity) -> `ERR_ANALYST_CAPACITY_EXCEEDED`.
- **Subprocessor FLAG** from a non-DISCLOSED state -> `ERR_DISPOSITION_NOT_APPLICABLE`.
- **Timestamps**: `created_at`/`updated_at` use the wall clock (3 fractional digits); all domain instants use the logical clock, which never falls back to wall time. List ordering is `(created_at, _seq)`.
- **List endpoints**: unknown query params and invalid enum filter values both -> 400.
- **Sweep counters**: `evaluated_entry_count` = entries PUBLISHED/EXPIRING_SOON at sweep start; the three movement counters count rows actually moved; `recomputed_vendor_count` = distinct vendors touched.
- **Versioning**: bump on any persisted change, plus forced bumps where the PRD is explicit (e.g. every integration attestation). Private state (`_pre_suspension_status`, notes, `_seq`) is `_`-prefixed and filtered out of serialization.

## Step 5: Generate unit tests — 2026-09-05T20:47:02.692308202Z

Step 5 test generation is complete.

## Files written

**`test_helpers/`** (2,562 lines)

| file | lines |
|---|---|
| `__init__.py` | 79 |
| `api_client.py` | 423 |
| `api_errors.py` | 154 |
| `assertions.py` | 189 |
| `constants.py` | 470 |
| `factories.py` | 379 |
| `fixtures.py` | 697 |
| `test_users.py` | 89 |
| `types.py` | 82 |

**`test_suite/`** (7,646 lines, 98 tests)

| file | lines | tests |
|---|---|---|
| `conftest.py` | 41 | — |
| `test_01_dual_variant_and_combinatorial_scoring.py` | 683 | 8 |
| `test_02_state_machines_and_cascades.py` | 571 | 8 |
| `test_03_ladder_order_and_boundaries.py` | 694 | 8 |
| `test_04_cross_entity_gates_and_windows.py` | 582 | 8 |
| `test_05_compensating_invariants.py` | 318 | 4 |
| `test_06_registry_entities.py` | 560 | 11 |
| `test_07_lifecycle_transitions.py` | 857 | 14 |
| `test_08_computed_values.py` | 444 | 6 |
| `test_09_business_rule_gates.py` | 963 | 11 |
| `test_10_endpoint_operations.py` | 557 | 6 |
| `test_11_error_catalogue.py` | 296 | 3 |
| `test_12_access_control.py` | 587 | 7 |
| `test_13_concurrency_and_thresholds.py` | 493 | 4 |

## Tests per source queue

- **Queue A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`) — 36 tests** over all 18 non-stub instances, exactly 2 each (files 01–05).
- **Queue B (`SCAFFOLD_CORNER_DESIGN.yaml`) — 62 tests** over all 62 non-stub instances, 1 each (files 06–13): entities 11, state_machines 14, calculations 6, validations 11, endpoints 6, errors 3, rbac 7, cross_cutting_complexity_layers 3, consistency_model 1.
- **Total 98.**

## Verification passes

- `pytest --collect-only` -> **98 tests collected**, no import or collection errors.
- `pyflakes test_suite/*.py` -> **clean** (only the expected unused re-exports in `test_helpers/__init__.py`).
- Citation checker (whitespace-normalized substring match against `workspace/PRD.md`) -> `checked=98 bad=0`; every test carries a verbatim, full-sentence, rule-bearing PRD quote.
- Design-tag checker -> `tests=98 bad=0`; exactly one `Design:` line per test and it is the docstring's last line, every tag resolves to a real yaml instance, **no `excluded_because:` stub was translated**, and **zero non-stub instances left uncovered in either queue**.
- No occurrence of the word "scaffold" anywhere in `test_suite/` or `test_helpers/`; the only `§` references are inside verbatim PRD quotations.
- Nothing written under `workspace/`; scratch scripts confined to `.scratch/`; `worklog.md` untouched.

## Instances skipped

**None.** All 62 non-stub corner instances and all 18 non-stub difficulty instances passed the PRD-first two-condition filter. The 15 `excluded_because:` stubs were deliberately not translated (design lines 1424, 1433, 1443, 1842, 1850, 1858, 1866, 1875, 1883, 2700, 2709, 3138, 3381, 4232, 4240).

## Design defects corrected (asserted outcome re-derived from the PRD)

1. **Invalid `data_categories` enum literals** at design lines 3357, 3592 and 4136–4151 (`["HOSTING"]`, `["ANALYTICS"]`, `["SUPPORT"]`, `["COMMUNICATION"]`). PRD line 219 states `data_categories` is "drawn from the same element codes the commitments use", so these were replaced with real element codes. The substitution is inert for the pinned arithmetic (the foreign-subprocessor penalty is 10 per non-`US` `country_code` regardless of categories).
2. **`rbac/exclusive_operations_are_refused_to_every_other_role`** asserted `Vendor.status == REGISTERED` after a setup that opens a review; PRD line 247 uniquely derives `UNDER_REVIEW`, so the assertion was corrected.
3. **rbac instances 5 and 7** omitted the mandatory commitment before issuing findings (PRD line 279 requires >=1 `PROPOSED`-or-`ACCEPTED` commitment). One commitment is now proposed and left `PROPOSED`, which preserves the pinned `final_compliance_score` (55.00 / 60.00) because PRD line 306 makes the final variant's input set `ACCEPTED`-only.
4. Six citations in the queue-A files were abbreviated sentences (a C3 violation) and 24 more differed only in em-dash rendering; both classes were repaired programmatically with verify-before-write, ending at `bad=0`.

Orchestrator verification: test_helpers/ and test_suite/ are both at the task root; nothing test-related was written under workspace/.

## Step 7: Run tests and iterate — 2026-09-05T21:08:46.275936587Z

All 8 rounds green. Task complete.

## Summary

**Iterations run: 2** (one diagnostic sweep + fixes, one confirmation sweep).

**Final sweep — per-round numbers quoted from `workspace/implementation/results.$i.json`:**

| file | passed / total | failed | errors | skipped |
|---|---|---|---|---|
| results.1.json | 98 / 98 | 0 | 0 | 0 |
| results.2.json | 98 / 98 | 0 | 0 | 0 |
| results.3.json | 98 / 98 | 0 | 0 | 0 |
| results.4.json | 98 / 98 | 0 | 0 | 0 |
| results.5.json | 98 / 98 | 0 | 0 | 0 |
| results.6.json | 98 / 98 | 0 | 0 | 0 |
| results.7.json | 98 / 98 | 0 | 0 | 0 |
| results.8.json | 98 / 98 | 0 | 0 | 0 |

Union of failures across all 8 rounds: **0**. Iteration 1 was deterministic 76/98 in every round (zero cross-round variance), so none of the 22 failures were load or timing artifacts.

**Tests deleted: none.** Three individual assertions were removed under STEP 1 (PRD silence / non-unique derivability); in each case the test's verbatim-covered rule and all other assertions were retained:
- `test_suite/test_06_registry_entities.py::test_registering_a_vendor_returns_the_full_computed_envelope` — dropped `created_at == 2026-08-01T00:00:00.000Z`. PRD §2.4 scopes the logical clock to "Deadlines, expiries, incident decay, authorization windows and sweep eligibility" and names the clock explicitly where it wants it (`submitted_at`, `reported_at`), never for `created_at`; §2.3's stable created_at ordering argues for wall clock. **PRD silent.**
- `test_suite/test_07_lifecycle_transitions.py::test_deciding_a_screening_review_is_refused_before_any_findings_round` — dropped `review["decided_at"] is None`. The token `decided_at` does not exist anywhere in PRD.md; §3.3 gives reviews only `decided_by_analyst_id` and `decision_note`. **PRD silent** (the assertion raised `KeyError`).
- `test_suite/test_08_computed_values.py::test_an_incident_weighs_half_once_it_is_older_than_ninety_days` — dropped `recomputed_vendor_count == 1`. §3.7 scopes sweep recomputation to "every **touched** vendor" (nothing moved in this scenario => 0) while §3.1 states the trigger scope-free => two faithful readings, **outcome not uniquely determined.** The 90-day half-weight rule itself is verbatim covered, so it was preserved by re-triggering recomputation through containment — a trigger §3.1 names explicitly ("an incident is reported, contained, notified or resolved") — and keeping `risk_score == 9.00`.

**Fixes to `test_helpers/`** (1):
- `fixtures.py::reauthorize_entry` expected HTTP 201 -> **200**. PRD §4's 50-endpoint accounting (11 collection-POST creations + 20 GETs + 17 `/{id}/action` transitions + sweep + clock) places `POST /catalog-entries/{entryId}/reauthorize` in the transition bucket, and §4 says "every read, list, transition and sweep endpoint answers HTTP 200".

**Fixes to `test_suite/`** (the two real defect clusters, both test-artifact wiring bugs):
- **19 call sites missing identity headers** (11 tests failing 401 `ERR_UNAUTHENTICATED`): `api.*` calls passing `headers=None` or omitting the argument entirely (e.g. `api.list_reviews(None, source_request_id=…)`, `api.create_catalog_entry(ctx["overlapping_body"], None)`, `api.get_subprocessor(subprocessor["id"])`). PRD §2.1 requires both headers on every request and every affected operation is `PrivacyOfficeAdmin`-authorized => replaced with `ADMIN_HEADERS` in test_02/03/04/07/09.
- **3 fixture sites sending `contained_at` in the future** (5 tests failing 400 on a setup step): PRD §3.9 requires `contained_at` "at or before the current logical clock". Fixed by advancing the logical clock to the containment instant, *not* by changing `contained_at` — `test_02` asserts `contained_at == "2026-08-01T12:00:00.000Z"` verbatim. The PRD-required implementation bound was left in place.
- 1 double-projection bug: `assert_covers_exactly([ids_of(a), ids_of(b)], …)` -> `[a, b]` (the helper applies `ids_of` internally).

**Fixes to `implementation/`: none.** No implementation defect was found; `workspace/implementation/` was never modified. `pyflakes test_suite/*.py` is clean and a full AST audit of `api.*`/`client.*` call sites against the `ApiClient` signatures now reports 0 missing-header sites. `worklog.md` untouched; `.scratch_fix/` removed.

Orchestrator verification: re-read all 8 `workspace/implementation/results.$i.json` files independently — every round reports `98 / 98 failed=0 errors=0 skipped=0`. The sweep artifacts are present on disk (timestamped 21:01), so the clean sweep really happened.

## Step 8: Finalize PRD — 2026-09-05T21:19:24.80063572Z

Done. `PRD_FINALIZED.md` exists at `workspace/PRD_FINALIZED.md`.

## Line counts
- PRD.md: 487 lines / 102,788 bytes
- PRD_FINALIZED.md: 487 lines / 104,440 bytes -> **0.0% line delta** (all 5 edits are inline within existing paragraphs), +1.6% bytes.
- File ends at a real boundary: the last row of the §5 Error Code Catalogue table (`| ERR_ANALYST_CAPACITY_EXCEEDED | 409 |`), unchanged from PRD.md.

## Changes (one bullet each)
- **§2.4 — revise** — `created_at`/`updated_at` are pinned as the one pair of stored instants stamped from server wall-clock time, not the logical clock; notes that driving the clock never changes `created_at`, which is what keeps §2.3 ordering stable — `core/store.py:45-48,60-66,74-78`.
- **§2.5 — insert** — the clock-relative instant bounds stated in §3 (`observed_at`/`detected_at`/`contained_at` after the clock, `contained_at` before `detected_at`) are shape failures reported as `ERR_INVALID_REQUEST`, not state/business failures — `routes/incidents.py:22-23,90-93`, `routes/telemetry.py:23-24`, `core/errors.py:16`.
- **§3.7 (sweep) — insert** — defines *touched*: an application is touched when one of its own entries changed status in that run; a vendor when it owns a touched application or an incident moved to `OVERDUE`; untouched vendors keep score, posture and `version`; `recomputed_vendor_count` is the count of distinct touched vendors and is zero when nothing moved — `routes/catalog.py:186-232`.
- **§3.1 — revise** — the `risk_score` recomputation trigger "the nightly sweep runs" is scoped to the vendors that run touches, per §3.7 — `routes/catalog.py:218-224`.
- **§4 preamble — revise** — 201 is scoped to the eleven collection `POST`s; every transition answers 200 even when it mints a row, naming `reauthorize` (returns the successor entry) and `telemetry-detections/{id}/triage` on `ESCALATE` (returns the detection) — `routes/catalog.py:176-177`, `routes/telemetry.py:153`, `core/envelope.py:20-26`.

## Per-edit pre-edit search log
1. **§2.4 created_at** — (a) subject: which clock stamps timestamps. (b) grepped every `wall_now`/`clock()` callsite: `store.new_row`/`store.bump` (all entities, wall clock), `envelope._meta` `api_request_timestamp` (wall clock, not a stored field), and every logical-clock consumer — `requests.py:111 submitted_at`, `incidents.py:21,88,118`, `telemetry.py:23,135`, `vendors.py:75,117 suspended_at`, `reviews.py:124,149 remediation_due_at`, `catalog.py:184 sweep`, `logic.py:253 decay`, `clock.py:16`; also `store.ordered` (`created_at`,`_seq`). (c) said "the one pair of **stored** instants" so the claim excludes `api_request_timestamp` (impl also wall-clock, but §2.2 leaves it unstated and I did not widen the claim there).
2. **§2.5 clock bounds** — (a) subject: error class for cross-field/clock instant bounds. (b) enumerated all `validate.bad` sites: `catalog.py:24,128,133` (already PRD-covered shape rules), `incidents.py:23,91,93`, `telemetry.py:24`; confirmed `ERR_INVALID_REQUEST -> 400` in `core/errors.py`. (c) dropped an initially planned claim that these bounds precede path/FK resolution — `contain` resolves the incident before comparing `contained_at` to `detected_at`, so I stated only the error code and made no ordering claim.
3. **§3.7 touched/`recomputed_vendor_count`** — (a) subject: sweep recomputation scope and counters. (b) read `routes/catalog.py:180-232` (both entry passes, incident pass, `touched_apps`/`touched_vendors` construction, counter assembly) and `core/logic.py:526-548` (`recompute_application_visibility`, `recompute_vendor`, which bumps `version` unconditionally); grepped every `recompute_vendor` callsite to confirm the sweep is the only multi-vendor loop. (c) added "score, posture and `version` alike" and the idempotence note to stay consistent with `recompute_vendor`'s unconditional `store.bump`; left `evaluated_entry_count` wording untouched (out of Step 7 scope).
4. **§3.1 sweep trigger** — (a) subject: the scope-free "the nightly sweep runs" trigger in the `risk_score` recomputation list. (b) re-checked all other triggers in that sentence against their callsites (`subprocessors.py:41,101`, `commitments.py:120`, `incidents.py:54,106,124,143`, `reviews.py:257`, `catalog.py:175`) — each is single-vendor, so the parenthetical touches nothing else. (c) kept the insertion to a delimited aside referring to §3.7 rather than restating the rule.
5. **§4 status codes** — (a) subject: which endpoints answer 201 vs 200. (b) grepped every `envelope.created`/`envelope.ok`/`envelope.paged` return: exactly 11 `created` sites (vendors, subprocessors, applications, teachers, privacy-analysts, application-requests, data-practice-reviews, data-element-commitments, catalog-entries, telemetry-detections, vendor-incidents); all `/{id}/action` transitions, the sweep and the clock return `ok`. (c) widened the sentence from naming only `reauthorize` to also naming the `ESCALATE` triage branch, so "a transition that mints a row still answers 200" is not falsely exclusive to one endpoint.

**Considered, no edit:** `decided_at` (impl's review serializer has no such field and PRD never names one, so PRD silence already yields the impl's behavior); the 19 missing-header call sites and the `assert_covers_exactly` double projection (pure test-artifact bugs — §2.1 already requires both headers on every request); the `contained_at` bound itself (already pinned verbatim in §3.9, only its error class was silent).

Orchestrator verification: `cmp` reports PRD_FINALIZED.md DIFFERS from PRD.md (5 inline edits, same line count), and the file still ends at the final §5 table row.

## Step 9: Complete PRD — 2026-09-05T21:43:54.768259967Z

Orchestrator note: Step 9 was run as THREE SEQUENTIAL file-partitioned passes over one shared `PRD_COMPLETED.md` (a single-shot whole-impl scan has historically no-op'd and left the file byte-identical to its source). Pass 1 owned the `cp`; passes 2 and 3 were forbidden from copying. Partition: pass 1 = `app.py`/`start.sh`/all of `core/`; pass 2 = `routes/{vendors,subprocessors,applications,people,requests,reviews}.py`; pass 3 = `routes/{commitments,catalog,telemetry,incidents,clock}.py`.

### Pass 1 of 3 — core layers (14 changes: 13 ambiguity-pins, 1 mismatch-revision)

`cp workspace/PRD_FINALIZED.md -> workspace/PRD_COMPLETED.md` ran; only `PRD_COMPLETED.md` was edited. PRD_FINALIZED.md 487 lines / 104,440 chars -> PRD_COMPLETED.md 487 lines / 108,877 chars (+4,437 chars; 14 lines revised in place, no new sections). Ends at the last §5 table row.

- `§2.2` — revise — ambiguity — `api_request_id` pinned to `req_` + exactly 20 upper-case-alphanumeric chars; `api_request_timestamp` pinned to real wall-clock, never the logical clock — `core/envelope.py:15-17`
- `§2.2` — insert — ambiguity — `message` is advisory; a rejection with no bespoke sentence repeats its own `error_id` there — `core/errors.py:9`
- `§2.3` — revise — ambiguity — non-integer `limit`/`offset` is malformed, empty-string value falls back to the default; `created_at` ties (ms-truncated wall clock) broken by server creation order, which is what makes the ordering total — `core/envelope.py:59-71`, `core/store.py:97-99`
- `§2.3` — insert — ambiguity — filters match by exact string equality; any query parameter other than `limit`/`offset`/declared filters is an unknown field -> `ERR_INVALID_REQUEST`, as is an out-of-enumeration filter value — `core/envelope.py:74-93`
- `§2.5` — insert — ambiguity — explicit `null` in any declared field (optional included) is a shape failure; a boolean is not an integer; absent/whitespace-only body reads as `{}`; non-object JSON body is a shape failure; instant syntax admits `T`/`t`/space, 0–9 fractional digits and `±HH:MM` offsets normalised to UTC, echoed as `Z` with 3 digits — `core/validate.py:9-31,53-59,122-151`
- `§2.5` — insert — ambiguity — arrays stored/echoed in supplied order with duplicates preserved everywhere except `framework_set` — `core/validate.py:95-118`, `core/serialize.py:22`
- `§2.8` — insert — ambiguity — decimals leave as JSON numbers in shortest round-trip form (63.80 -> `63.8`, 0.00 -> `0.0`) — `core/serialize.py:21`
- `§2.8` — insert — ambiguity — `priority_score`, `element_points` and `exposed_sensitivity_points` are unclamped and may exceed 100.00 — `core/logic.py:193-196,206-212,218-237`
- `§2.10` — **revise — mismatch** — PRD claimed *every* cascade-touched row is re-stamped; impl stamps only when the value actually moved. Revised to: no-op recomputations leave `updated_at`/`version` alone (teacher `open_request_count` on `RETURN`/resubmit-from-`RETURNED`, application `catalog_visibility` on a revoke that leaves another visible entry), with two unconditional exceptions — vendor recompute always bumps, and the application always bumps on a commitment disposition and on a reauthorization — `core/store.py:81-94`, `core/logic.py:532-548`, `routes/commitments.py:119`, `routes/catalog.py:174`
- `§3.1` — insert — ambiguity — incident age is a floor of complete 24-hour periods, so a `detected_at` left ahead of the clock (clock driven backwards) yields a non-positive age and full weight — `core/logic.py:251-259`
- `§3.9` — insert — ambiguity — suspension `reason` retained internally, not a field of the vendor payload — `core/serialize.py:35-40`, `routes/vendors.py:77`
- `§3.9` — insert — ambiguity — reinstatement `note` likewise retained but not surfaced — `core/serialize.py:35-40`, `routes/vendors.py:107`
- `§4` — insert — ambiguity — a trailing slash resolves to the same endpoint — `app.py:27`
- `§5` — insert — ambiguity — unknown route -> `ERR_INVALID_REQUEST` @404, undeclared method -> `ERR_INVALID_REQUEST` @405, escaped internal failure -> `ERR_INVALID_REQUEST` @400; service never answers 5xx — `app.py:39-56`

Cross-checks that found no gap: §5 catalogue vs `core/errors.py` (all 52 codes, statuses and table order identical); every field name in `core/serialize.py` already named in PRD; every enum member / element code / status literal in `core/logic.py` already named; all numeric constants in `core/logic.py` already uniquely pinned; `validate.grade_band`'s `low_current`/`high_current` are dead in routes (reauthorize re-implements the pair check inline at `routes/catalog.py:122-126`), so §2.5's pair rule was deliberately left un-narrowed.

### Pass 2 of 3 — registry/intake/review routes (17 changes: 14 ambiguity-pins, 3 mismatch-revisions)

No `cp` was run; 17 surgical `Edit` calls, no `Write`. Pass 1's edits verified intact (spot-checked §2.10's cascade re-stamping revision plus a full diff against PRD_FINALIZED.md). 487 lines unchanged; 111,988 chars, up from 108,877 (+3,111). Ends at the last §5 table row.

- §2.5 — revise — mismatch — non-blank set corrected: `legal_name`, `name`, `full_name`, `employee_number`, `school_code`, `observed_domain` are non-blank; `purpose`/`justified_purpose`/`instructional_justification` are length-bounded only; note/reason fields carry no bound at all — `routes/people.py:15-17`
- §3.1 — insert — ambiguity — registration computes score+posture as part of row creation, so a fresh vendor still reads `version` 1 (guards pass 1's universal "vendor always bumps" claim) — `routes/vendors.py:41-42`
- §3.1 — revise — mismatch — application registration carries **no** ownership rung; a liaison may name a `vendor_id` other than its own — `routes/applications.py:15-27`
- §3.1 — insert — ambiguity — `processor_vendor_id` may name the disclosing vendor itself — `routes/subprocessors.py:24-25`
- §3.1 — insert — ambiguity — an omitted `reviewed_note` leaves the stored note unchanged — `routes/subprocessors.py:97-98`
- §3.1 — revise — ambiguity — `FLAG` also requires `DISCLOSED` (PRD enumerated only VERIFY/REMOVE) — `routes/subprocessors.py:91-92`
- §3.9 — insert — ambiguity — the suspension `reason` is mandatory — `routes/vendors.py:70`
- §3.2 — insert — ambiguity — submit's effective values feed every check but persist only on success; a refused submission leaves the draft untouched — `routes/requests.py:95-109`
- §3.2 — insert — ambiguity — an omitted `triage_note` leaves the stored note unchanged — `routes/requests.py:142-143`
- §3.3 — insert — ambiguity — the assignee's staffing `status` is not checked when a review is opened (only reassignment requires `ACTIVE`) — `routes/reviews.py:24-33`
- §3.3 — revise — ambiguity — all three reassignment conditions (same assignee, `INACTIVE`, no room) report `ERR_ANALYST_CAPACITY_EXCEEDED` — `routes/reviews.py:272-278`
- §3.5 — insert — ambiguity — `findings_count` is an integer >= 0 with no upper bound; zero is admissible and leaves the review immediately clearable — `routes/reviews.py:95`
- §3.5 — insert — ambiguity — issue-findings' `decision_note` is written to the review's own `decision_note` field; omission leaves it unchanged — `routes/reviews.py:96,125-126`
- §3.5 — insert — ambiguity — a review with no `PROPOSED`/`ACCEPTED` commitment is refused with `ERR_REVIEW_STATE_INVALID`, on the status-gate rung and thus ahead of the posture check — `routes/reviews.py:104-108`
- §3.5 — insert/revise — ambiguity + mismatch — `resolved_findings_count` is an integer >= 0 with no cap, and the review `remediation_note` is retained internally and never surfaced — `routes/reviews.py:139,158-159`
- §3.5 — insert — ambiguity — the provisional penalty reads `open_findings_count` **after** this round rewrote it to `findings_count` — `routes/reviews.py:122-130`
- §3.6 — insert — ambiguity — an `X-User-ID` matching no stored analyst row is also refused with `ERR_SEGREGATION_OF_DUTIES` on decide — `routes/reviews.py:174-177`
- §3.6 — insert — ambiguity — the BLOCK-branch revocation leaves `hold_restored_from` as it stands (an explicit revocation clears it) — `routes/reviews.py:242-245`
- §3.6 — revise — ambiguity — `decision_note` is recorded only when the decide payload supplies one, otherwise the last findings round's note survives — `routes/reviews.py:201-202`

Cross-checks so wording does not falsely universalize into other passes' modules: `recompute_vendor` call sites (only registration recomputes score+posture without a bump), `sod_or_403` call sites (`commitments.py:94`, `catalog.py:32` impose no LEAD/existence requirement, so the stored-row clause is scoped to decide), and every `nonblank=True`/note-field `F(...)` spec across all route modules.

### Pass 3 of 3 — commitment/catalog/telemetry/incident/clock routes (14 changes in 13 Edits: 11 ambiguity-pins, 3 mismatch-revisions)

No `cp`, no `Write`. Passes 1 and 2 intact and spot-checked: §2.10's pass-1 cascade re-stamping revision is present and **verified correct** against pass 3's modules (`catalog.py:174` uses `force=True` on reauthorize while `catalog.py:70` publish and `:108` revoke do not; `commitments.py:119` forces on disposition); §3.3's pass-2 reassignment revision is present. Pass 2's §3.1 risk-score trigger list is consistent with `incidents.py`/`telemetry.py`/`catalog.py`, so send-notification recomputation was not re-pinned (line 211 already covers it). 487 lines; 116,489 chars, up from 111,988 (+4,501). Ends at the last §5 row. NOT byte-identical to PRD_FINALIZED.md — 39 of 487 lines differ (29 from passes 1–2, 10 from pass 3).

- §2.4 — insert — ambiguity — clock echo is the single member `current_utc` of the `data` object, normalised to `Z`/3 digits — `routes/clock.py:16`
- §2.7 — revise — **mismatch** — "rejects a mismatch before any business rule" contradicted impl: the row's own state gate (rungs 11/15) is evaluated *above* the concurrency rungs, so a stale token on a decided review gives `ERR_REVIEW_STATE_INVALID` and on a fresh `PUBLISHED` entry gives `ERR_CATALOG_ENTRY_NOT_RENEWABLE` — `routes/commitments.py:24-28`, `routes/catalog.py:135-138`
- §3.4 — insert — ambiguity — supersede-on-re-author touches only earlier `PROPOSED` rows; an already-`ACCEPTED`/`REJECTED`/`SUPERSEDED` row for the same element survives, and two `ACCEPTED` rows for one element both count toward exposure — `routes/commitments.py:51-55`
- §3.4 — insert — ambiguity — a commitment create moves nothing but the review and the superseded row; no application/vendor recompute, so `expected_application_version` survives it — `routes/commitments.py:57-59`
- §3.7 — insert — ambiguity — defined `evaluated_entry_count` (opening-snapshot count of `PUBLISHED`/`EXPIRING_SOON` entries, excludes `EXPIRED`/`SUSPENDED_HOLD`/`REVOKED`/`SUPERSEDED` and all incidents) and pinned the other three as transition counts — `routes/catalog.py:186-232`
- §3.7 — insert — ambiguity — reauthorize's grade-band low/high check runs against the *effective* (partly inherited) pair and therefore after `entryId` resolves, so an unknown `entryId` with inverted bounds yields 404 not 400 — `routes/catalog.py:121-133`
- §3.7 — insert — ambiguity — reauthorize's gate list is exhaustive: it never re-runs publication's subprocessor-disclosure, accessibility or SSO gates — `routes/catalog.py:135-153`
- §3.8 — insert — ambiguity — triage `note` is retained internally and never surfaced on the detection payload — `routes/telemetry.py:123` + `core/serialize.py:89-93`
- §3.8 — insert — ambiguity — `affected_student_count`/`max_data_tier` are declared for every disposition (admitted then ignored outside `ESCALATE`), not unknown fields — `routes/telemetry.py:83-84`
- §3.8 — insert — ambiguity — escalation-minted incident's `reported_at` = logical clock, with the same `PENDING`/zero/null notification defaults as a self-report — `routes/telemetry.py:135-147`
- §3.8 — revise — **mismatch** — "that rung guards only vendor self-reports" -> guards every incident filed through `POST /vendor-incidents` whichever role files it — `routes/telemetry.py:148` vs `routes/incidents.py:32`
- §3.9 — revise — **mismatch** — "Self-reports — and only self-reports — are subject to the … buffered window collision" was wrong: impl runs the buffer check role-independently, including for a `PrivacyOfficeAdmin` filing on the vendor's behalf; only the telemetry-escalation incident is exempt — `routes/incidents.py:29-33`
- §3.9 — insert — ambiguity — a successful report recounts `open_incident_count`, recomputes `risk_score` (live) and re-evaluates `privacy_posture` in that order, so a `CRITICAL` self-report freezes the vendor at filing time — `routes/incidents.py:54`
- §3.9 — insert — ambiguity — containment's optional `remediation_note` is written to the incident's surfaced field; omission leaves the stored value unchanged — `routes/incidents.py:102-103`
- §3.9 — insert — ambiguity — `notified_party_count` is an integer >= 0 with no upper bound (absent from §2.5's range list) — `routes/incidents.py:113`

Behaviors checked and left alone (PRD already pinned uniquely): full publication gate order and ladder alignment; sweep three-pass ordering, touched-set scoping and idempotency; revoke clearing `hold_restored_from`; detection classification ladder incl. `_widest` tie-break and `REVOKED`/`SUSPENDED_HOLD` exclusion; exposure/severity/`notification_due_at` formulas; all five list-filter sets; every RBAC row against §4; all HTTP 200/201 choices against §4's pass-2 preamble; clock-relative 400s ordering ahead of body-FK 404s.

### Step 9 totals and orchestrator verification

45 changes across the three passes (38 ambiguity-pins, 7 mismatch-revisions). `PRD_COMPLETED.md` = 487 lines / 116,489 chars vs `PRD_FINALIZED.md` 487 lines / 104,440 chars (+12,049 chars; 39 lines differ). `cmp` confirms the two files are NOT byte-identical, so the scan genuinely ran. The file ends at the final §5 error-catalogue row — a real section boundary, not a truncation.

`workspace/implementation/` was not modified by Steps 8 or 9 (newest source mtime is still 19:35, from Step 6), so the Step 7 clean sweep remains valid and all eight `results.$i.json` (98/98 each) are on disk. Scratch directories removed. Pipeline complete.
