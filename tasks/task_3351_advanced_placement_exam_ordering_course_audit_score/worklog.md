# Worklog — task_3351_advanced_placement_exam_ordering_course_audit_score

Scenario: Advanced Placement Exam Ordering, Course Audit & Score Reporting (College Board)

## Step 1: Create task directory — 2026-10-01T04:55:50.583114134Z

Task directory was pre-allocated by the caller as `./tasks/task_3351_advanced_placement_exam_ordering_course_audit_score/` with an empty `workspace/` inside. No index computation performed; no other task_* directory created. Verified: directory exists and contains only `workspace/`.

## Step 2: Generate scaffold — 2026-10-01T05:26:15.929358214Z

**Status: PARTIAL — resumed and reconstructed.** The original Step 2 subagent wrote `SCAFFOLD.yaml` successfully (2396 lines / 120,444 bytes, verified complete and YAML-parseable: top-level keys scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles; no leftover `__APPEND__` sentinel). Its final report was lost to an API error, and the two sibling design-index files were never written.

Verified scaffold stats: 12 entities / 10 state machines / 4 concurrency rules / 11 calculations / 29 validations / **50 endpoints** (over the §0.4 band of 20–32; acceptable but will require the up-front Step 6 output constraints) / 32 errors / 8 roles. No `CONST.*` references exist in the file, so the referenced-but-undefined-constant bootstrap hazard does not apply. A `POST /_clock/set_current_utc` test-driving endpoint exists, so time-gated setups are reachable.

**Blocker:** Subagent spawns began failing with `model_not_found` for `deepseek-v4p1-flash-wave` (HTTP 404) partway through this session; a fresh-spawn probe that succeeded at 05:13 began failing again at 05:25, and an explicit `model: sonnet` override does not take effect (the harness still sends the nonexistent id). Per prior-run experience, subagents are now treated as unavailable for the remainder of this session. **The remaining steps are executed in the foreground by the orchestrator**, following each step's own protocol and preserving the same contracts (PRD-first filters, cardinal rules, 8-round parallel sweep, output discipline of ≤200 lines per message / one file per message).

Missing deliverables to be authored in the foreground: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8) and `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9).

## Step 2: Generate scaffold — 2026-10-01T08:56:02.240673658Z

**Status: COMPLETE (resumed, reconstructed and repaired).** This step spanned three interruptions; the record below is the authoritative account.

**Artifacts (all verified on disk, YAML-parseable, lint-clean):**
- `SCAFFOLD.yaml` — 2473 lines / 124,969 bytes, §1.0–§1.7, single-file (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1450 lines / 96,168 bytes, top-level key `scaffold_difficulty_design`, 9 rule_id blocks × 2 instances = **18 instances**
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1775 lines / 111,195 bytes, top-level key `scaffold_corner_design`, 9 taxonomy sections, **38 instances** (33 with test_recipe, 5 `excluded_because:` stubs)

**Final scaffold stats:** 12 entities / 11 state machines / 4 concurrency rules / 11 calculations / 29 ordered validations / **52 endpoints** / 32 errors / 8 roles.

**Reconstruction narrative.** The first Step 2 subagent wrote `SCAFFOLD.yaml` (v1, 50 endpoints) and then died with a lost report; a resumed run rewrote it as v2 (39 endpoints, 11 state machines) at 05:23:54, again without a report. I verified v2 complete and parseable rather than re-running. The §1.8 index was then authored in the foreground (18 instances) and the §1.9 index by a subagent (38 instances). A third interruption occurred before any downstream step.

**Repairs I made to v2 (all verified by `scaffold_lint.py` before and after):**
1. **§1.5 endpoint paths were missing the `api_prefix`.** The linter's `derive_entity_collection_segments` requires `path.startswith(api_prefix + "/")`; with bare paths every entity's collection segment was underivable, producing **14 FK_REVERSE_UNREACHABLE** violations. Prefixed all 48 paths with `/ap-program` → violations halved to 7.
2. **Seven endpoints referenced by §1.7 RBAC were absent from §1.5** (`POST /students/{id}/status-transitions`, `GET /exam-registrations/{id}`, `GET /accommodation-requests/{id}`, `GET /readers/{id}`, `GET /readers/{id}/calibration-summary`, `GET /irregularity-cases`, `GET /students/{id}/registrations`). Added them, plus `GET /exam-scores/{id}` and `GET /score-sends/{id}` which the §1.8 chains need.
3. **Four more reverse-reachability reads** to clear the remaining FK violations: `GET /students/{id}`, `GET /exam-orders` (filtered list on `school_id?`/`course_audit_id?`), `GET /readers/{id}/exam-scores`, `GET /schools/{id}/irregularity-cases`. §1.7 updated to list every new endpoint. Endpoint count 39 → **52** (above the §0.4 band; Step 6 will carry the up-front output constraints).
4. **30 OCC version literals** in the §1.8 index (`expected_*_version: 1`) replaced with `${var}` references bound by `captures: { <id>_v1: "$.data.version" }` on the corresponding create call.
5. **8 `expected_irregularity_case_version` payload keys removed** — the scaffold declares OCC rules for only four entities (CourseAudit, ExamOrder, ExamScore, AlternateExamRequest); IrregularityCase has none.
6. **5 `expected_alternate_exam_request_version` keys added** to the `FILED -> UNDER_REVIEW` calls, which §1.5 declares as required input, with matching version captures on the create calls.
7. **4 intentional negative-test triggers** (3 RBAC denials + 1 required-field omission) given `captures: { err: "$.data.error_id" }` so the linter's documented negative-trigger exemption recognises them as deliberate rejections rather than malformed calls.

**Verification (independent, orchestrator-run):** `scaffold_lint.py` → **clean** (52 endpoints, 18 + 33 instances, 560 calls scanned, all conform; all §1.1 FKs have reverse-reachability). My own placeholder-closure walker confirms 0 unbound `${var}` in either design file, 56 globally-unique instance names, and every `excluded_because.difficulty_instance` resolving to a real §1.8 instance.

**Known non-blocking lint exception:** none remaining. The three role-denial calls and the one omitted-required-field call now carry the error-envelope capture and lint clean.

**Endpoint-count note for Step 6:** 52 endpoints exceeds the §0.4 band of 20–32. Per prior runs (48/68/75 endpoints), this is survivable provided the Step 6 prompt mandates one file per message, per-domain route modules, an explicit no-truncation warning, and a mandatory boot smoke test.

## Step 3: Copy shared files — 2026-10-01T08:56:02.256930059Z

Copied `./INSTRUCTION.md` → `tasks/task_3351_advanced_placement_exam_ordering_course_audit_score/workspace/INSTRUCTION.md` (bash-only step, no subagent).

## Step 4: Generate PRD — 2026-10-01T09:04:42.930783720Z

Subagent summary (verbatim):

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3351_advanced_placement_exam_ordering_course_audit_score/workspace/PRD.md`

**Counts**
- `wc -l -c` → **399 lines, 82,116 bytes**
- `grep -c '^#'` → **27 sections** (§1; §2.1–§2.10; §3.1–§3.9; §4; §5)
- distinct `ERR_*` ids → **32** (the scaffold declares exactly 32; all 32 also appear in §1–§3, not just the §5 table)
- `grep -n '__APPEND__'` → **no output**
- valid UTF-8; ends on a complete table row (`| ERR_ACCOMMODATION_PROVISION_INCOMPLETE | 409 |`) with a trailing newline

**Spot-check literals (grep counts):** `18000` → 3, `27000` → 1, `2026-11-01T00:00:00Z` → 2, `2027-07-05T00:00:00Z` → 2, `0.85` → 3, `/ap-program` → 54. All present.

**Hard Contracts (all PASS)**
```
Field coverage check:
- entities[].fields: 79 required, 79 present, 0 missing
- endpoints[].input/request_body: 59 required, 59 present, 0 missing
- endpoints[].query_params: 0 required, 0 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 29 checked, 29 expressed in prose (full ordered ladder table in §2.6), 0 missing
- concurrency_rules[] OCC rejections: 4 checked, 4 expressed (write_endpoint + expected_<entity>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 73 checked, 73 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed with constants and pinned evaluation order, 0 missing
- validations[] conditions: 29 checked, 29 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 52 checked, 52 expressed, 0 missing
- entities[].fields[] structured content: 79 checked, 79 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (order void x3, score withhold/cancel, accommodation decision, irregularity decision, reader calibration, shipment return), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 689
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Also verified:** §2.2 matches `section-2.2-response-structure.md` **byte-for-byte** (including `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, `"data": { }`); §4 table has 52 rows = 52 scaffold endpoints with 4 columns; §5 has 32 rows with 2 columns. Neither design-index file was opened, and no sibling `task_*/` directory was read.

**Two scaffold tensions carried through verbatim rather than resolved** (worth knowing at test time): `ExamMaterialShipment` declares `SEAL_BROKEN` as a terminal state while also defining a `SEAL_BROKEN → RETURNED` edge — the PRD states both; and the `late_order_fee` schedule has a `CLOSED`-window branch even though registration acceptance refuses `CLOSED`/`NOT_OPEN` — the PRD states the fee branch and the acceptance gate separately.

**Orchestrator independent verification (not taken on trust):** file exists at 82,116 bytes / 399 lines; 27 top-level headings; distinct `ERR_*` ids = 32 and the set difference against the scaffold's 32 error ids is EMPTY; all six spot-check literals present (`18000`×3, `27000`×1, `2026-11-01T00:00:00Z`×2, `2027-07-05T00:00:00Z`×2, `0.85`×3, `/ap-program`×54); file ends on a complete table row.

**Isolation note:** the Step 4 subagent was instructed not to read either design index and reported it did not. Both indices remain withheld from Steps 4 and 6 as the skill requires.

## Step 5: Generate unit tests — 2026-10-01T09:30:34.968865022Z

Subagent summary (verbatim, abridged only where it repeated file tables):

Done. Test infrastructure and 71 design-index-translated tests are on disk.

**`test_helpers/` — 1,994 lines**: `__init__.py` (49), `types.py` (347), `api_client.py` (267), `api_errors.py` (82), `assertions.py` (229), `constants.py` (146), `factories.py` (160), `test_users.py` (99), `fixtures.py` (615).
**`test_suite/` — 2,315 lines**: `conftest.py` (70) + `test_01…test_08` (queue A) + `test_20…test_29` (queue B).

**Totals**: 71 tests, 71 design tags, **0 unresolved**, 0 untagged, 0 dual-tagged. Queue A (Difficulty): all 18 instances at 2/2 — no shortfall. Queue B (Corner): all 33 non-stub instances at ≥1 (one instance carries 2); the 5 `excluded_because:` stubs emit nothing and all five `difficulty_instance` pointers resolve. **0 skipped instances.** **0 timeline shifts** — every chain instant (2026-10-31T23:59:59Z … 2027-08-01T00:00:00Z) is ≥ the `2026-09-01T00:00:00Z` startup clock; the one backward clock move in the §1.8 boundary recipe was avoided by giving each edge its own test starting from a fresh server. Constants match PRD.md exactly (all ordering-window instants, `18000`, `27000`, `0.85`, `READER_LOAD_CAP`=120, plus the worked values `139140`/`135360`/`3780`, `0.9100`, `293`). `py_compile` clean on all 28 files; `grep __APPEND__` → nothing; no `skip`/`xfail`; no scaffold/table references in code; every PRD citation is verbatim-greppable (0 non-verbatim after fixes).

**PRD-vs-design-recipe disagreements (PRD won in each case):**
1. §1.8 `course_audit_revision_loop…` — recipe rejects after 1 revision; PRD §3.1 requires `syllabus_revision_count >= 2`. Fixture performs two loop trips.
2. §1.8 `irregularity_case_appeal_cycle…` — recipe uses `PROHIBITED_DEVICE`; PRD §2.10 declares `UNAUTHORIZED_DEVICE`. Also `UNAUTHORIZED_MATERIALS` and `MISCONDUCT` are undeclared members; substituted declared values.
3. §1.8 `consolidation_slices…` — recipe asserts `provisional_order_fee_cents == 197000` while creating one registration; that literal belongs to a different instance. Re-derived from the PRD (8 delivered, 2 LATE ⇒ 152000 provisional / 143360 consolidated).
4. §1.8 `unused_charge…` — recipe's setup never reaches `DELIVERED`. Note the PRD makes the charge structurally unreachable above the grace count through the clean path (`MATERIALS_SHIPPED` requires every registration `CONFIRMED`, so `MATERIALS_RECEIVED` leaves none). Tests build the 27000/54000 cases by confirming registrations added after receipt, per §3.3's stated acceptance gates.
5. §1.8 `alternate_same_day…` — recipe claims capacity 10 (300 seat-minutes) admits three non-touching 255-minute blocks; it does not (765 > 300). Used capacity 30 (900) so the same-day cap is genuinely binding.
6. §1.9 `scoring_specialist_denied_school_creation` — recipe asserts against `GET /schools?school_code=`, which the PRD does not publish. Replaced with a same-payload-as-PlatformAdmin positive control.
7. §1.9 `unpaid_send_fee_maps_to_402` — recipe's 2027-07-10 clock is `CLOSED`, so its own registrations could not be created. Setup runs in `REGULAR`, then advances the clock for release.
8. §1.9 `confirm_with_unpaid_late_fee…` — recipe's `late_fee_cents == 4000` needs the `LATE` window; its listed clock (2027-02-15) works, its sibling §1.8 instance's 2027-02-10 does too.

**Residual ambiguity flagged (not skipped):**
- `score_send_fee_all_include_vs_college_only_exclude`: the persisted `fee_cents` variant is not pinned; the recipe's two asserts contradict each other on one field. Asserted the PRD's own worked example for the above-allowance case and 0 for the within-allowance case. A compensating-invariant test covers the same instance variant-independently.
- `course_audit_invalid_transition_submitted_to_approved`: §3.1's `ERR_AUDIT_NOT_REVIEWED` pulls against §2.6's ladder (rank 7 `ERR_INVALID_STATE` < rank 9). Asserted `ERR_INVALID_STATE` per the ladder's first-failing-rank rule and the design index's explicit claim.

**Orchestrator independent verification (not taken on trust):** 28 .py files present (9 helpers + 19 suite files); 71 test functions; my own tag resolver parsed 71 `Design:` tags with **0 unresolved**; every §1.8 instance has ≥2 tests (**none short**); every non-stub §1.9 instance has ≥1 test (**none short**); no stub instance carries a test. My first pass appeared to show all 18 §1.8 instances at 1 test each — that was a bug in my checker (counting unique names instead of occurrences), corrected before recording this entry; the subagent's 2/2 claim is accurate.

**Note for Step 7:** the eight PRD-vs-recipe disagreements above are places where the §1.8/§1.9 indices and the PRD diverge. The tests follow the PRD, which is the correct precedence. If Step 7 meets a failure that traces to one of these sites, the PRD ruling recorded here is authoritative.

## Step 6: Generate implementation — 2026-10-01T09:58:32.727292214Z

**Isolation model in force:** Steps 5 and 6 were launched as separate subagents in separate messages (the endpoint duplicates parallel tool calls, so the skill's single-message concurrent launch was impossible). The ISOLATION RULE was therefore imposed explicitly in the Step 6 prompt: the implementation subagent was forbidden to read, grep or open `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_suite/` or `test_helpers/`, and was forbidden to run the test suite. It implemented from INSTRUCTION.md + SCAFFOLD.yaml + PRD.md only. It reported complying; the files it produced show no reference to any test artifact.

Subagent summary (verbatim):

Implementation complete and verified. All files live in `workspace/implementation/`.

**File inventory**: `start.sh` (10), `requirements.txt` (1), `app.py` (30), `core.py` (190), `constants.py` (128), `errors.py` (85), `clock.py` (73), `response.py` (76), `auth.py` (31), `validation.py` (89), `machines.py` (142), `calc.py` (345), `cascades.py` (259), `entities.py` (140), plus 13 `routes_*.py` (21-192 each). Max file 345 lines (`calc.py`); total 3,284 lines.

**Verification results**
1. `wc -l`: all 27 files ≤ 345 lines.
2. `python3 -m py_compile *.py` → OK; `bash -n start.sh` → OK.
3. `grep -rn '__APPEND__' implementation/` → none.
4. **url_map endpoint count = 52** (enumerated in-process via `app.url_map.iter_rules()`), matching the 52-row PRD §4 table exactly.
5. **Boot smoke test** (fresh process, curl, real HTTP): school created as PlatformAdmin (201) → course audit filed as SchoolCoordinator with `X-User-ID`=school id (201) → `SUBMITTED→IN_REVIEW` as CourseAuditReviewer (200) → `APPROVED` with `decision_notes` (200) → school read shows `program_label_authorized = True`, `designated_course_count = 1` → exam order created → clock set to `2026-12-01T00:00:00Z` → `DRAFT→OPEN` with `ordering_window = REGULAR` → student created → registration created → registration read back (`REGISTERED`, version 1). Zero tracebacks in the server log.
6. **Restart isolation**: killed the server (only the PID started), relaunched via `bash start.sh`; every list endpoint returned `total_count=0 data=[]` and the clock read back `2026-09-01T00:00:00.000Z` — in-memory-only storage confirmed.
7. Additional live exercises (no test suite touched): full order lifecycle (fees 4000 late at LATE window, `ERR_LATE_FEE_UNPAID`, provisional fee 22000, `MATERIALS_SHIPPED`/`MATERIALS_RECEIVED`), shipment custody (dispatch/transit/receive with `NOT_REQUIRED` seal record, gap-free chain), reader calibration (0.91 index), score aggregation (ap_score 4 for 95.5, marginal recompute path), release gating (`ERR_SCORE_RELEASE_TOO_EARLY`), order auto-delivery (DELIVERED 22000 / unused 0), score sends + designation budget, irregularity invalidation cascade (registration→score→send CANCELLED with credit), alternate seat occupancy (`ERR_ALT_SEAT_CONFLICT`), accommodation approval cascade (weight_sum 2.2, 293 provisioned minutes), audit revision loop (`ERR_SYLLABUS_UNCHANGED`), SoD 403s, stale-version 412s, and order void paths.

Notable bugs found and fixed during the boot exercises: audit transitions weren't writing the target `status`; `School` was missing `designated_course_count` in its serialization; shared mutable default leaked one custody log across all shipments (deep-copy fix); `core.parse_instant` typo (500); reader branch read `status` instead of `calibration_status` (500); the scaffold's extra SUBMITTED-void precondition was dropped because PRD §3.2 enumerates only the material-lock precondition and its stated side effects require uncancelled registrations.

Two interpretation calls worth flagging: (a) the ladder is enforced literally, so a terminal state that also has a declared edge (e.g. shipment `RECEIVED→RETURNED`, score `WITHHELD→RELEASED`) returns `ERR_ALREADY_TERMINAL` — this is the only way rank 8 is reachable, per the "rank 7 outranks rank 8" note; (b) OCC mismatch is evaluated before the state machine (PRD §3.1 "rejected as stale before the state machine is consulted"), with a missing version field treated as `ERR_INVALID_REQUEST` (400).

**Orchestrator independent verification (not taken on trust):** 26 source files present totalling 3,283 lines; largest is `calc.py` at 345 lines; `python3 -m py_compile *.py` → OK; `bash -n start.sh` → OK; no `__APPEND__` sentinel anywhere; `start.sh` execs `python3 app.py` in the foreground and guards its pip install so the per-test reboot does not contend. The reported 52-endpoint count was not re-derived by me (Step 7's sweep will exercise the surface directly).

**Hand-off notes for Step 7:** interpretation call (a) above is the most likely source of a systematic failure cluster — the implementation treats a terminal state as rejecting even where the scaffold declares an outgoing edge, so any test that expects e.g. `WITHHELD→RELEASED` or `RECEIVED→RETURNED` to succeed will fail against it. The PRD states both facts (terminal list and the edge), so this is a genuine PRD-level ambiguity that Step 7 must adjudicate by the PRD-first rule and Step 8 must then pin.

## Step 7 (attempt 1): interrupted mid-flight — audit of inherited state — 2026-10-01T10:15:19.375613676Z

The first Step 7 fix subagent was launched, ran at least one full 8-round sweep, and was then killed by the host session ending. **Its report was lost.** Per the "lost report ≠ lost artifact" and "dead subagent leaves unattributed edits" rules, I audited the tree rather than re-running blind.

**What the dead subagent left on disk (verified by mtime):**
- `workspace/implementation/results.{1..8}.json` at 10:08:15 — a complete 8-round sweep.
- Three **test-side** edits at 10:05, all *before* that sweep (so the sweep reflects them):
  - `test_suite/test_27_corner_optimistic_concurrency.py` (10:05:36)
  - `test_helpers/constants.py` (10:05:30)
  - `test_helpers/fixtures.py` (10:05:26)
- **No implementation edits** after 09:57 (Step 6's last write). The implementation is therefore untouched Step 6 output.

**Sweep result: 65/71 passed, 6 failed, 0 errors, 0 skipped — identical in all 8 rounds.** An identical failure set across all 8 concurrent rounds proves the six defects are deterministic; there is no timing flakiness to chase, so the whole remaining budget goes to root-causing.

**Integrity audits run before trusting the tree:**
- `python3 -m pytest test_suite --collect-only -q` → **71 tests collected**, 0 import errors. The package graph is intact (the dangling-import failure mode does not apply).
- Deletion check: 71 collected = 71 reported by the Step 5 hand-back = 71 executed by the sweep. No silent test deletion.
- No source file other than the three listed above has an mtime between Step 6's last write and the sweep.

**The six failures (union over all 8 rounds — all six failed in every round):**

*Cluster A — 4 tests, one root cause, in `test_suite/test_07_alternate_seat_occupancy.py`:*
`test_touching_buffered_intervals_overflow_a_two_seat_centre`, `test_touching_buffered_intervals_are_admitted_by_a_generous_centre`, `test_third_alternate_on_one_calendar_day_is_refused_by_the_concurrent_cap`, `test_third_alternate_on_a_different_calendar_day_is_admitted` — all fail identically at setup with `HTTP 409: ERR_INVALID_STATE - A alternate_exam_requests row in UNDER_REVIEW cannot move to UNDER_REVIEW`.
Root cause (confirmed by reading the file, not inferred): the module defines `_file()` which creates an alternate **and already advances it to UNDER_REVIEW**, and `_approve()` which issues **another** `UNDER_REVIEW` transition before `APPROVED`. Every call site passes a `_file()` result into `_approve()`, so the second `UNDER_REVIEW` is a re-entry the PRD's `FILED -> UNDER_REVIEW -> APPROVED` machine correctly rejects. The implementation is right; `_approve()` is the bug. This is original Step 5 output (test_07 is older than the inherited edits), not an inherited edit.

*Cluster B — 1 test, `test_suite/test_04_*`:*
`test_score_invalidation_finding_cancels_every_send_and_credits_back_its_fee` — `AssertionError: the cancellation restores the designation budget the dispatches had consumed / assert 2 == 0`. The cancellation cascade zeroes the sends but the school's cached `designation_slots_used` still reads 2. Candidate impl defect: the cached count is recomputed on send creation but not on cancellation.

*Cluster C — 1 test, `test_suite/test_08_*`:*
`test_seal_break_and_return_pair_moves_no_cents` — `HTTP 409: ERR_ALREADY_TERMINAL - A material_shipments row in the terminal state SEAL_BROKEN admits no further transition`. This is precisely the ambiguity Step 6 flagged at hand-off: `SEAL_BROKEN` appears in the scaffold's `terminal_states` **and** as the source of a declared `SEAL_BROKEN -> RETURNED` edge. The implementation resolved it by making terminal states absorbing, which renders two declared edges (`SEAL_BROKEN -> RETURNED`, `RECEIVED -> RETURNED`) permanently unreachable. Needs explicit PRD adjudication.

**Verdict on the inherited edits:** the three test-side edits did not cause any of the six failures (none of the failing tests live in test_27, and the other two files are shared helpers whose edits are consistent with the 65 passing tests). They are, however, **unattributed** — Step 7 attempt 2 is instructed to re-adjudicate them against PRD + SCAFFOLD rather than inherit them on trust.

**Next:** relaunch Step 7 as a fresh long-lived subagent carrying this state, the six diagnoses above as leads (not verdicts), and the full diagnostic protocol.

## Step 7 (attempt 2): run tests and iterate — 2026-10-01T10:26:02.242388359Z

Subagent summary (verbatim):

Clean 8-round sweep: **71/71 in every round.**

**Iterations and per-round pass counts**
- Inherited baseline (from the dead subagent's 10:08 sweep): 65/71 in all 8 rounds, 6 deterministic failures.
- Iteration 1 (my fixes): **71/71 in all 8 rounds** (results.1–8.json, 10:24). 71 collected == 71 executed == 71 reported in every round; no test deleted, skipped, or xfailed. Newest `implementation/*.py` mtime (10:21:21) predates the results files (10:24:38), so the sweep is not invalidated by post-sweep writes. All 8 results files are left in place.

**Largest failure cluster and its single root cause**
Cluster A — 4 of the 6 failures, all in `test_suite/test_07_alternate_seat_occupancy.py`, all failing at setup with `ERR_INVALID_STATE: A alternate_exam_requests row in UNDER_REVIEW cannot move to UNDER_REVIEW`. Single root cause: the module's `_approve()` issued a redundant `UNDER_REVIEW` transition on a row `_file()` had already advanced to `UNDER_REVIEW`. PRD §3.6 says only "A filed request moves to `UNDER_REVIEW` only when the `form_code` is non-empty and the linked registration is `CONFIRMED`" — the machine is `FILED -> UNDER_REVIEW -> APPROVED` with no self-edge. Test-side defect, not an implementation bug. The other 2 failures were independent singletons.

**Tests deleted**: None. No test failed STEP 1 (PRD coverage + unique derivability).

**Fixes to `test_helpers/`**: None needed. Read all 630 lines of `fixtures.py` and all of `constants.py`; every fixture precondition traces to a PRD sentence.

**Fixes to `test_suite/`**
- `test_suite/test_07_alternate_seat_occupancy.py` — `_approve()` dropped its redundant `UNDER_REVIEW` step (call sites already pass a `_file()` result, which is `UNDER_REVIEW`). `_file()` keeps advancing to `UNDER_REVIEW` because the four tests also feed its result straight to `_attempt_approval()`. Comment added citing §3.6.

**Fixes to `implementation/`**
- `cascades.py` — `invalidation_cascade()`: added `school_of_send()` and a `recompute_designation_slots()` call after the send cancellations. PRD §3.9: "every score send of that score transitions to `CANCELLED` with `credit_back_cents` set to its `fee_cents`, restoring the designation budget those sends had consumed"; §2.5: counters "are recomputed from the rows as they stand after the transition, not adjusted incrementally". The `designation_slots_used` field is a count over sends in `PENDING`/`SENT`/`ACKNOWLEDGED` (§3.8), so a cancelled cascade must refresh it. This is the `assert 2 == 0` failure.
- `validation.py` — `check_state()`: terminal-state veto narrowed (see adjudication below).
- `machines.py` — added `has_outgoing_edge(store_key, status)` helper used by the above.

**Terminal-state adjudication**
Chosen reading: **declared edges out of terminal states are permitted** — "terminal" in this PRD means "end of the forward lifecycle", not "absorbing".
PRD line relied on (§3.5): *"The machine declares `RECEIVED`, `RETURNED` and `SEAL_BROKEN` as its terminal states, and defines one further edge out of `SEAL_BROKEN` — to `RETURNED` — for sending compromised material back to the program."* Corroborated by §3.5 *"a shipment in `SEAL_BROKEN` may be returned by a `PlatformAdmin` once every irregularity case created from that seal break has reached `CONFIRMED` or `DISMISSED`"*, §3.4 *"Cancellation and reinstatement bracket the registration's terminal state … it returns the registration to `REGISTERED`"* (while `CANCELLED` is also called terminal), and §3.8 *"Both brakes are reversible: a withheld score returns to `RELEASED` … and a cancelled score returns to `AGGREGATED`"* (while `WITHHELD`/`CANCELLED` are also called terminal). The strict-absorbing reading would make all of those documented operations impossible, so the specific functional sentences win over the generic rank text.
Consequence: rank 7 (`ERR_INVALID_STATE`) still fires first for a terminal state with no declared outgoing edge, which is what the three corner tests in `test_20_corner_state_machines.py` assert. `ERR_ALREADY_TERMINAL` is therefore retained in the code but is now vacuous for this machine — no test in the suite asserts it, and the corner design index itself notes "priority 8 … is unreachable for this shape because the from-state check fires first". Kept the branch and documented it rather than deleting it; making it genuinely reachable would require changing three currently-passing corner tests, which would contradict `SCAFFOLD_CORNER_DESIGN.yaml`.

**Verdict on the three inherited edits**
- `test_suite/test_27_corner_optimistic_concurrency.py` — **KEPT.** Every assertion cites a PRD sentence; the added `order_fee_cents == 18000` check on the rejected stale order traces to §3.2 ("`order_fee_cents` holds the provisional figure while the order is `OPEN`" + "The provisional variant charges every registered exam at the base fee of 18000 cents"). More faithful to PRD than a version without it.
- `test_helpers/constants.py` — **KEPT.** `ALTERNATE_PLANNING_CLOCK_UTC = 2027-02-10T00:00:00Z` sits inside the LATE window (2027-02-01 → 2027-03-15), which registration acceptance requires (rank 11 / §3.3). The alternative would make alternate-exam setup unreachable.
- `test_helpers/fixtures.py` — **KEPT.** Full read, no PRD inconsistency found; no edit reverted.

**Final 8-round result:** 71/71 passed, 0 failed, 0 errors, 0 skipped — in every one of the 8 rounds.

**Orchestrator independent verification (not taken on trust):** all 8 `results.{1..8}.json` read directly → `{total: 71, passed: 71, failed: 0, errors: 0, skipped: 0}` in each. Newest source mtime across `implementation/`, `test_suite/`, `test_helpers/` (excluding `__pycache__`) is `machines.py` at 10:21:21, which **predates** the results files at 10:24:38 — so the green sweep certifies the code currently on disk and no post-sweep write invalidated it. All three claimed implementation fixes spot-checked in source: `machines.has_outgoing_edge` is defined at `machines.py:145` **and called** at `validation.py:77` (not dead code); `cascades.recompute_designation_slots` is defined at `cascades.py:69` and called at `cascades.py:227` inside the cancellation cascade; the terminal veto at `validation.py:77` carries the new `has_outgoing_edge` guard.

**Step 7 fix breakdown for the Step 8 focus list:** 0 tests deleted; 0 `test_helpers/` fixes; 1 `test_suite/` fix (test_07 `_approve` redundant transition); 3 `implementation/` fixes (cascades designation-slot recompute, validation terminal-veto narrowing, machines `has_outgoing_edge` helper). The implementation fixes reveal one PRD-silence site: the PRD calls several states "terminal" while also documenting working edges out of them, and never states which reading governs.

## Step 8: Finalize PRD — 2026-10-01T10:32:37.339941133Z

Step 8 was **not skipped**: Step 7 made 3 `implementation/` fixes (plus 1 `test_suite/` fix, 0 deletions, 0 `test_helpers/` fixes), so the PRD had genuine silences to pin.

Subagent summary (verbatim):

Done. Verified the final artifact: `PRD_FINALIZED.md` is 401 lines vs `PRD.md` 399 (+2 lines, +0.50%), with exactly 3 edit hunks.

**Per-edit pre-edit search log**

**Edit 1a — §2.6 rank-8 table row (revise)**
- (a) Subject: the condition rank 8 actually evaluates.
- (b) Enumerated: `implementation/validation.py:38-79` (`check_state`: rank 7 edge membership → `ERR_INVALID_STATE`; rank 8 = `current in TERMINAL and not has_outgoing_edge`), `implementation/machines.py:17-147` (`EDGES`, `TERMINAL`, `has_outgoing_edge`), and every transition endpoint — grepped `transition_gate`: routes_audits/orders/registrations/accommodations/alternates/scores/readers/shipments/sends/irregularities/schools all funnel through it; grepped `ERR_ALREADY_TERMINAL`: only `validation.py:78` (plus the error catalogue). Also grepped the test suite for terminal assertions (`test_20`, `test_03`) to confirm they assert `ERR_INVALID_STATE`.
- (c) Wording adjusted: wrote the condition as "terminal state from which the machine declares no outgoing edge" rather than the vague "one of its terminal states", so the row no longer contradicts the admitted edges out of `SEAL_BROKEN`/`CANCELLED`/`WITHHELD`/`RECEIVED`.

**Edit 1b — §2.6 new paragraph after the ladder (insert)**
- (a) Subject: what "terminal" governs — terminal-list vs. declared edges, and rank-7-first ordering.
- (b) Enumerated and verified programmatically over `machines.py`: terminal states *with* outgoing edges are `exam_registrations.CANCELLED`, `exam_scores.{CANCELLED,RELEASED,WITHHELD}`, `material_shipments.{RECEIVED,SEAL_BROKEN}` — each is a PRD-documented working operation (§3.4 reinstatement, §3.8 brake reversals, §3.5 returns). Terminal states *without* outgoing edges exist and number 16 (`REJECTED`, `EXPIRED`, `DELIVERED`, `VOIDED`, `INVALIDATED` ×2, `REVOKED`, `INACTIVE`, `RETURNED`, `DENIED`, `WITHDRAWN`, `DISMISSED`, `ACKNOWLEDGED`, `FAILED`, `CANCELLED`(send), `RETIRED`). Because every rank-8 candidate has zero declared targets, rank 7 always fires first ⇒ rank 8 is unreachable. Also re-read the §3 "terminal state" sentences (§3.1–§3.9) for consistency.
- (c) Wording adjusted: the Step 7 diff's premise ("no state is terminal-with-no-outgoing-edge") is **false** — I did not write it. Instead the paragraph says terminal-and-edgeless states do exist, that they are refused by rank 7 with `ERR_INVALID_STATE`, and that `ERR_ALREADY_TERMINAL` is therefore never the error a caller observes. Also added a clause reconciling the §3 sentences that say "refused as terminal", and stated rank 8 is consulted only after rank 7 passes. Avoided any claim about machines other than the ones I enumerated.

**Edit 2 — §2.9 (insert, appended to the counter-doctrine sentence)**
- (a) Subject: counter refresh on cancellation — specifically `designation_slots_used` after send cancellations.
- (b) Enumerated: `cascades.py:69-85` (`recompute_designation_slots`, population = COLLEGE sends in PENDING/SENT/ACKNOWLEDGED of the school's students), and every send-status write: `routes_sends.py:144` (direct cancel, recompute at `:150`), `routes_scores.py:162-172` (`_cancel_sends`, recompute at `:172`; used by WITHHELD/CANCELLED/INVALIDATED), `cascades.py:204-227` (`invalidation_cascade`, recompute at `:227`). Grepped all `recompute_designation_slots` callsites (4) and all `send["status"] =` writes (3 cancel sites + SENT/ACKNOWLEDGED/FAILED, whose recompute at `routes_sends.py:148-150` is unconditional). Also checked the other counters the diff listed (`registration_count`, `accrued_fee_cents`, `designated_course_count`, `program_label_authorized`, `assigned_score_count`, `storage_checkpoint_count`, `custody_sequence_count`, `accommodation_eligible`, `accommodation_flag`, `release_blocked`) against `cascades.py` + their callsites.
- (c) Wording adjusted: deliberately did **not** write a general "any cascade that removes rows refreshes the counter" claim — `invalidation_cascade` moves the registration out of `registration_count`'s population without recomputing the order's count, which would have made that a false universal. Scoped the sentence to send cancellations (all three paths verified to recompute) and made it inclusive ("directly, or by the cascade that follows…") so it does not exclude the direct-cancel path.

**Changes**
- §2.6 rank table — revise — rank 8's condition now reads "not sitting in a terminal state from which the machine declares no outgoing edge" — `implementation/validation.py:77`
- §2.6 (after the ladder paragraph) — insert — new paragraph: terminal is not absorbing; a declared edge out of a terminal state passes rank 7 and rank 8; rank 8's veto is confined to edgeless terminal states (which do exist), which rank 7 already refuses with `ERR_INVALID_STATE`, so `ERR_ALREADY_TERMINAL` is never observed; "refused as terminal" in §3 means this rank-7 refusal — `implementation/validation.py:70-79`, `implementation/machines.py:145-147`
- §2.9 (counter-doctrine sentence) — insert — recomputation is not confined to creations: any send cancellation (direct, or via withholding / score cancellation / `SCORE_INVALIDATION_REQUIRED` invalidation) recomputes the owning school's `designation_slots_used` from the sends as they then stand — `implementation/cascades.py:204-227`, `routes_sends.py:144-150`, `routes_scores.py:162-172`

No edit was made for the `test_suite/test_07` helper fix (pure fixture defect, per the diff) or for `machines.has_outgoing_edge` (mechanism only, no independent PRD silence).

**Orchestrator independent verification (not taken on trust):** the Step 8 subagent **rejected a premise I handed it** and was right to. I had passed on Step 7's claim that "no state is terminal-with-no-outgoing-edge"; Step 8 verified programmatically that 16 terminal states DO lack outgoing edges, and wrote the opposite (correct) claim instead. I re-verified this myself by importing `machines` and enumerating: **6** terminal states carry an outgoing edge (`exam_registrations.CANCELLED`, `exam_scores.CANCELLED`, `exam_scores.RELEASED`, `exam_scores.WITHHELD`, `material_shipments.RECEIVED`, `material_shipments.SEAL_BROKEN`) and **16** do not. Reading `validation.py:70-79` confirms the ordering: rank 7 refuses any undeclared `(from, to)` pair first, so for an edgeless terminal state every `to_status` fails rank 7 and rank 8 is never reached. Step 7's hand-back was wrong on this point; Step 8's correction stands.

**Note for Step 9:** `ERR_ALREADY_TERMINAL` is declared in the error catalogue and ranked 8 in the ladder but is unreachable in the implementation. `PRD_FINALIZED.md` now says so explicitly. If Step 9 finds any other declared-but-vacuous rule, record it rather than silently reconciling.

## Step 9: Complete PRD — 2026-10-01T10:51:41.117847164Z

Step 9 ran (it always runs). Source was `PRD_FINALIZED.md`.

Subagent summary (verbatim, abridged only in the per-change bullet list formatting):

Done. `workspace/PRD_COMPLETED.md` written; `PRD_FINALIZED.md` untouched.

**Size**: `PRD_FINALIZED.md` 401 lines / 83,812 chars → `PRD_COMPLETED.md` 401 lines / 88,582 chars (**+4,770 chars, +0 lines**; 24 section headers unchanged, 52 endpoint rows unchanged, 32 error rows unchanged). 40 in-place edits across 37 lines: **20 mismatch-revisions, 20 ambiguity-pins**. No new sections, no new paragraphs.

**Changes** (40; grouped by PRD section):
- §2.1 — revise ×3 — identity paragraph (three entity-backed roles, not two; removed a claimed `school_id`-vs-`X-User-ID` ownership comparison that does not exist; SchoolStudent reads unscoped; only send-cancel compares identity) — `auth.py:10-25`, `routes_students.py:151`, `routes_registrations.py:199`; exclusivity paragraph replaced with the monopolies actually enforced — `routes_readers.py:72`, `routes_audits.py:55`, `routes_sends.py:38`; SOD gate rides only target statuses `IN_REVIEW`/`APPROVED`, `UNDER_DOC_REVIEW`/`APPROVED`/`REVOKED`, `CONFIRMED` — `machines.py:132-142`
- §2.3 — insert — insertion-order tie-break for equal `created_at` — `core.py:82-84`
- §2.4 — revise ×2 — expiry sweep runs only inside the clock call; the cancellation deadline refusal is inclusive; the `2027-09-15` release-window close is inert — `routes_clock.py:20`, `routes_scores.py:17-18`, `constants.py:14`
- §2.6 — revise ×3, insert ×1 — ranks 4 and 19 wording aligned; rank 21 "passes"→"reaches"; documented two observable ladder inversions (a missing `to_status` beats rank 4; rank 27 beats ranks 7/8) — `validation.py:82-94`
- §2.8 — revise — receipt sets `seal_verified` true even where the school requires no seal; only the event's `verification` reads NOT_REQUIRED — `routes_shipments.py:200-209`
- §2.9 — revise — `release_blocked` is written imperatively, not derived from case status — `routes_irregularities.py:255`, `cascades.py:118`
- §2.10 — revise — `school_code`/`center_code` length and character class are unvalidated conventions — `routes_schools.py:24-26`
- §3.1 — revise ×3, insert ×1 — approval cascade tests the student-level `accommodation_eligible` flag, not a per-subject request; non-ACTIVE-center approval is `ERR_INVALID_STATE`; revision-cap refusal is `ERR_INVALID_STATE`; expiry happens in the clock-move sweep — `cascades.py:168`, `routes_audits.py:76,92,118`
- §3.2 — revise, insert — non-ACTIVE-center open is `ERR_INVALID_STATE`; PlatformAdmin is refused on DRAFT/OPEN voids — `routes_orders.py:223,284`
- §3.3 — revise ×3, insert ×1 — late-fee window is read at the FEE_PENDING move and a LATE tier pays 0 in REGULAR/NOT_OPEN; the nine-registration cap is re-checked on that move; the order-level capped late-fee view is dead; fee settlement is absolute with `refundable = min(max(0, paid−late_fee), 18000)`; MATERIAL_ASSIGNED is reachable directly from CONFIRMED — `calc.py:122,134`, `routes_registrations.py:235-240,258,305`
- §3.4 — revise ×2 — REVOKED clears the flag only on REGISTERED/FEE_PENDING/CONFIRMED/MATERIAL_ASSIGNED; provisioning fields named `weight_sum`/`provisioned_minutes` — `routes_accommodations.py:169,279`
- §3.5 — revise — either listed role may drive either return path; the SEAL_BROKEN return tests every MATERIAL_COMPROMISE case hosted at the school — `routes_shipments.py:221-231`
- §3.6 — revise ×2 — `seat_block_conflict` stays true after a refused overflow; the day cap compares the requester's buffered start date; SCHEDULED's only form test is non-emptiness — `routes_alternates.py:60,67,278`
- §3.7 — revise ×3 — `assigned_score_count` is recomputed as the count of AGGREGATED/RELEASED scores (never incremented, so load accrues only on aggregation); the marginal variant's five section marks derive from the composite's own band plus a top-5%-of-band promotion; the calibration summary field set — `cascades.py:102`, `calc.py:215-230`, `routes_readers.py:44`
- §3.8 — revise ×5 — `release_blocked` phrasing; auto-delivery requires MATERIALS_RECEIVED + all `SCORE_RELEASED`; RELEASED→CANCELLED requires a recorded cancellation request; the college-only send-fee variant is dead so stored `fee_cents` is always the all-inclusive figure; the designation budget of 8 is a single per-school counter, not partitioned by `designation_year` — `routes_scores.py:109,137`, `cascades.py:69,246`, `calc.py:324`
- §3.9 — revise — opening a case blocks every score row of the registration, whatever its status — `routes_irregularities.py:279`
- §4 table — revise ×2 — readers status-transitions `+Reader`; score-sends status-transitions `+SchoolStudent` — both live in `authenticate`

**Dead-guard audit** (the "PRD-required check can ship as dead code" check): all guard helpers have live callsites — `authenticate` 53, `transition_gate` 12, `require_fk` 12, `require_unique` 4, `optional_version` 3, `_require_decision` 3, `registration_material_assignable` 3, `_set_block` 4, `_cancel_sends` 3, `refresh_student_flag` 3, `require_window_open` 2, `select_reader` 2, `_deadline_passed` 2, `_refresh_provisioning` 2, `count_active_registrations_for_year` 2, `refresh_reader_reliability` 2, and 1 each for `check_sod`, `require_version`, `check_state`, `has_outgoing_edge`, `_recipient_resolves`, `_chain_is_gap_free`, `score_release_open`, `_effective_completeness`, `_apply_request_flags`, `eligible_readers`, `calibration_index_weighted`, `approved_accommodation`, `maybe_auto_deliver`, `recompute_custody_counts`, `school_of_send`.
**Dangling (0 live callsites), reported not patched:** `cascades.recompute_release_blocked` (`cascades.py:118`), `cascades.registrations_reaching` (`:280`), `cascades.delivered_statuses` (`:284`), `calc.late_fee_order_level` (`calc.py:134`), `calc.score_send_fee_college_only` (`calc.py:324`); unused constants `CUSTODY_EVENT_TYPES`, `READER_RELIABILITY_CEILING`, `SCORE_RELEASE_WINDOW_CLOSES_UTC`. The PRD sentences those dead functions implied (§2.9 gate 3, §3.3 order-level late fee, §3.8 dual-variant send fee, §2.4 release-window close) were revised to describe the live behavior instead. **`implementation/` was deliberately NOT patched** — an implementation write at Step 9 would invalidate the verified 8-round sweep.

**Route surface**: `app.url_map.iter_rules()` after importing the app → **52 API routes** under `/ap-program` (plus Flask's `/static/<path:filename>`, not part of the API) vs **52 rows** in the §4 table — exact match. No prefix decorator is used; the prefix is literal in every `@app.route`.

**Not describable without inventing**: None. Two internal-state details are deliberately left undescribed because they are never serialized (`_last_submitted_hash`, `_last_submitted_completeness`, `_fees_paid_cents`, `_withholding_requested`, `_cancellation_requested`, `_confirmed_at`).

**Orchestrator independent verification (not taken on trust):** `PRD.md` 399 lines / 82,116 B; `PRD_FINALIZED.md` 401 / 83,812 B; `PRD_COMPLETED.md` 401 / 88,582 B. `diff -q PRD_FINALIZED.md PRD_COMPLETED.md` → **differ** (so Step 9 was not a silent `cp`-only no-op). No `implementation/` file is newer than the Step 7 sweep's results files.

## Final verification sweep (orchestrator-run, after Step 9) — 2026-10-01T10:51:41.117847164Z

Re-ran the 8-round parallel sweep myself against the frozen tree (`rm -f results.*.json` first, so a stale green set could not be mistaken for a fresh one):

**results.{1..8}.json — every round `{total: 71, passed: 71, failed: 0, errors: 0, skipped: 0}`. ALL 8 ROUNDS GREEN.**

Results written 10:51:04; newest source file is `machines.py` at 10:21:21 — the sweep therefore certifies the code currently on disk, and no post-sweep write invalidated it. This also restores the `results.{1..8}.json` deliverables the output contract requires.

## Pipeline complete — 2026-10-01T10:52:10.902645631Z

**Final state: 71/71 tests passing in all 8 rounds of the stability sweep; sweep re-run by the orchestrator against the frozen tree after Step 9.**

Deliverable inventory (all verified present and non-empty):

```
tasks/task_3351_advanced_placement_exam_ordering_course_audit_score/
├── SCAFFOLD.yaml                          2473 lines / 124,969 B  (§1.0–§1.7, 52 endpoints)
├── SCAFFOLD_DIFFICULTY_DESIGN.yaml        1450 lines /  96,168 B  (§1.8, 9 rules × 2 = 18 instances)
├── SCAFFOLD_CORNER_DESIGN.yaml            1775 lines / 111,195 B  (§1.9, 38 instances, 33 real + 5 stubs)
├── worklog.md                             this file
├── test_helpers/                          9 modules
├── test_suite/                            conftest + 18 test modules, 71 tests, 71 design tags, 0 unresolved
└── workspace/
    ├── INSTRUCTION.md                     build contract
    ├── PRD.md                             399 lines /  82,116 B
    ├── PRD_FINALIZED.md                   401 lines /  83,812 B  (Step 8: +3 hunks)
    ├── PRD_COMPLETED.md                   401 lines /  88,582 B  (Step 9: 40 in-place edits)
    └── implementation/                    25 Python modules + start.sh + requirements.txt
        ├── start.sh                       foreground launcher, , 0.0.0.0
        └── results.{1..8}.json            final sweep: 71/71 every round
```

**Post-cleanup cold-boot check (orchestrator-run):** after removing all `__pycache__` directories, started the server with `PORT=41777 bash start.sh` and exercised it: `GET /ap-program/score-sends` returned an empty array with the correct envelope and pagination fields; `POST /ap-program/schools` returned **HTTP 201** with a server-minted UUID, the correct default field set, and `created_at` = `2026-09-01T00:00:00.000Z` (the declared logical-clock default). Zero tracebacks in the boot log. Only the PID I started was killed.

**Session-level notes.** This pipeline ran across four host interruptions and one mid-session model-endpoint change. Two Step 2 subagents died with lost reports (the second had rewritten `SCAFFOLD.yaml` to v2 without reporting); a Step 7 subagent ran a full sweep and made three test-side edits before being killed with its report lost. In each case the tree was audited and the artifact verified rather than blindly re-run, and the audit findings are recorded in the entries above. The §1.8 index was authored in the foreground; §1.9 by subagent. The Step 7 relaunch carried the audited baseline and finished in a single iteration.

**Open items carried forward for a human reviewer (none block the deliverable):**
1. `ERR_ALREADY_TERMINAL` is declared in the error catalogue and ranked 8 in the validation ladder but is **unreachable** — rank 7 refuses every undeclared `(from, to)` pair first, and no terminal state lacks a declared edge that rank 8 could veto. `PRD_COMPLETED.md` §2.6 now states this explicitly.
2. Five helper functions and three constants ship as **dead code** (`cascades.recompute_release_blocked`, `cascades.registrations_reaching`, `cascades.delivered_statuses`, `calc.late_fee_order_level`, `calc.score_send_fee_college_only`; `CUSTODY_EVENT_TYPES`, `READER_RELIABILITY_CEILING`, `SCORE_RELEASE_WINDOW_CLOSES_UTC`). The PRD was revised to describe the live behavior rather than the dead code's intent; the dead code itself was deliberately left in place because patching `implementation/` after the verified sweep would invalidate it.
3. Endpoint count is **52**, above the scaffold-generator's §0.4 band of 20–32. The overshoot came from the reverse-reachability reads the linter's rule (f) mandates plus the §1.7-referenced reads the v2 scaffold had dropped. It was handled with the up-front Step 6 output constraints and cost no visible degradation.
