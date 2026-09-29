## Step 1: Create task directory — 2026-09-05T22:05:43.606309504Z

Created tasks/task_2958_technical_documentation_release_notes_publishing/ and its workspace/ subdirectory. Index 2958 was pre-assigned by the orchestrating invocation; no auto-allocation scan was performed (32 concurrent pipelines on this host).


## Step 2: Generate scaffold — 2026-09-05T23:42:53.086Z

Step 2 for task 2958 is complete. All three scaffold files exist and the lint is clean.

**Deliverables** (in `/home/ubuntu/github/CodingPRD/tasks/task_2958_technical_documentation_release_notes_publishing/`):

| file | lines | notes |
|---|---|---|
| `SCAFFOLD.yaml` | 3095 | §1.0–§1.7 only; contains neither `scaffold_difficulty_design` nor `scaffold_corner_design` (verified by grep = 0). 15 entities / 63 endpoints / 74 error codes / 12 calculations (3 dual-variant) / 11 state machines / 61 validations / 2 OCC rules. The `difficulty_level` comment was corrected this session — it previously understated the counts (57 endpoints / 47 errors / 11 calcs / 10 SMs). |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2076 | single top-level key `scaffold_difficulty_design`, 20 instances |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4153 | single top-level key `scaffold_corner_design`, 92 instances across all nine claim-extraction-guide sections |

**Corner-design breadth** (real recipe / `excluded_because` stub): entities 12/0, state_machines 10/7, calculations 7/8, validations 8/6, endpoints 4/1, errors 11/7, rbac 4/1, cross_cutting_complexity_layers 3/2, consistency_model 1/0 — 60 real recipes, 32 stubs.

**Lint verdict (verbatim):**
```
Coverage
  §1.5 endpoints declared:    63
  §1.1 entities declared:     15
  §1.8 instances scanned:     20
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  1116

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Key findings / audits done this session**
- **Error catalog is now fully triggerable.** I enumerated all 74 ids and cross-checked coverage programmatically; the two initially uncovered ones (`ERR_RELEASE_TRAIN_CLOSED_FOR_PLANNING`, `ERR_DUPLICATE_SIGNOFF_DISCIPLINE`) got a dedicated grouped instance that drives the train to GA (which itself requires a published doc set) and requests a second ENGINEERING sign-off from a *different* reviewer. The `errors` section opens with a YAML comment block mapping every id already triggered elsewhere in §1.9 to its owning section, so no id is silently assumed.
- **Fixed two mis-cited validation priorities** in stub `grounds`: `ERR_WRITER_WINDOW_OVERLAP` is priority 52 (not 46) and `ERR_LOCALE_PARALLEL_JOB_LIMIT_EXCEEDED` is 53 (not 52).
- **Normalized all 32 `excluded_because.difficulty_instance` citations to bare §1.8 instance names.** Earlier sections used a qualified `rule_id / name` form, which does not satisfy SKILL.md's "MUST exist by `name`" rule; all 32 now resolve exactly (19 of the 20 §1.8 instances are cited; only `writer_window_half_open_with_leading_handoff_buffer` is uncited, which is fine).
- Every append was chunked via `cat >> … << 'EOF'` and YAML-validated immediately; no chunk failed to parse.

**Flag for the orchestrator:** `SCAFFOLD.yaml`'s `scenario:` block still opens with the literal line `Generate task harder than expert level!` (line 8). That is the known difficulty-directive leak — it will otherwise reach PRD.md via Step 4, so strip that one line (and the following blank line) before Step 3.

Scratch cleanup: removed only `.scratch/step2`; the parent `.scratch/`, `worklog.md` and `workspace/` were left untouched.

**Orchestrator post-processing:** acted on the subagent's flag — stripped line 8 (`Generate task harder than expert level!`) and the following blank line from `SCAFFOLD.yaml`'s `scenario:` block. `grep -rn "harder than expert"` across the task dir now returns nothing, so the difficulty directive cannot reach PRD.md. All three YAMLs re-validated with `yaml.safe_load` after the edit (SCAFFOLD.yaml now 3093 lines).

## Step 3: Copy shared files — 2026-09-05T23:42:57.653Z

Copied ./INSTRUCTION.md to tasks/task_2958_technical_documentation_release_notes_publishing/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-05T23:56:40.520Z

PRD generation for task 2958 is complete and verified.

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_2958_technical_documentation_release_notes_publishing/workspace/PRD.md` — 450 lines, 98,135 bytes. Nothing else in the task dir was created, modified, or deleted; `.scratch/step4/` was removed and the parent `.scratch/` left intact.

Structure: §1 Introduction; §2 with ten domain-derived subsections (RBAC, verbatim response structure, pagination, identity/audit/logical clock, validation precedence, optimistic concurrency, precision & money, ledgers/conserved quantities/cascades, immutable snapshots vs live counters, date-window conventions); §3 with ten workflow subsections (release trains → writer roster → authoring/IA → terminology governance → accuracy review & sign-off → doc-set versions/archival/EOL → change records & release-note compilation → localization → deprecation timelines → reader signals & health); §4 endpoint table; §5 error catalogue.

## Truncation / coverage confirmation

The file ends at a real section boundary — the last row of the §5 table, `| \`ERR_WRITER_CAPACITY_EXCEEDED\` | 409 |`, not mid-sentence. All 63 §1.5 endpoints appear as rows in §4 (Method | Path | Description | Authorized Role(s)); all 74 §1.6 error codes appear in §5 with their HTTP statuses and each is also referenced in §2/§3 prose at its trigger point; all 61 §1.4 validation rules are expressed through §2.5's 17 precedence bands (including the five named intra-band orderings) plus the per-workflow narratives; all 12 calculations are stated as reconstructible formulas with their named constants, and all 11 state-machine dimensions (including Topic's parallel `review_state` × `publication_state`) have complete transition prose.

## Hard Contract reports

- **Field-Name Coverage — PASS.** `entities[].fields` 126/126, request-body inputs 66/66, query-param/output names 33/33, path params 1/1. Also 0 missing across role names, all state-machine state literals, and every `one of {...}` enum value.
- **Rule Coverage — PASS.** Every state transition, validation, calculation, cascade hop, conserved-ledger invariant, and both OCC rules are derivable from prose alone; no pseudocode, and a fuzzy-word grep (`approximately|roughly|conservatively|around N|…`) returned zero hits.
- **§3 Path Purity — PASS.** 966 backtick tokens scanned inside §3: 0 tokens beginning with `/`, 0 method+path combinations. Three bare `PATCH` tokens are the `ChangeRecord.severity` enum value (in the severity enumeration and the `SEV_WEIGHT` list), never an endpoint identifier.

## One discrepancy worth escalating

**Pagination default 10 vs 20.** `response_envelope.pagination_defaults` specifies `limit: 10`, but a comment in the §1.5 endpoints header says "default 20". I followed the skill's directive to derive pagination from `pagination_defaults`, reinforced by the verbatim §2.2 envelope showing `"limit": 10`, so the PRD states **default 10, min 1, max 100**. If the hidden tests were seeded from the header comment instead, this is the single field that would diverge.

Four other internal scaffold conflicts I resolved (all in favour of the more specific/authoritative source):

1. `load_points` — entity constraint says 1 decimal place, but `calculations.writer_capacity_load_points` says 2 dp round-half-up with worked values 8.44 / 40.80 → PRD says two decimal places.
2. `projected_localization_budget_cents` at draft creation — endpoint side-effect says `null`, entity field says `default: 0` → PRD says 0.
3. `support_end_date` — validation priority 45 implies `>=` against `ga_date`, entity constraint says `>` → PRD requires strictly later.
4. submit-review check order — the Topic state machine lists terminology-blocker before posture, but the priority table has posture=25 and blocker=28; since §1.4 is declared priority-ordered with lowest number winning, the PRD checks posture first.

**Orchestrator verification (truncation guard):** independently re-checked the tail. PRD.md ends at the final row of the §5 error table — a real section boundary, not mid-sentence. Programmatic cross-checks: all 63 §1.5 endpoints present in §4 with exact method+path match (0 missing, 0 extra); all 74 distinct `ERR_*` ids from SCAFFOLD.yaml present in PRD.md (the only two scaffold "errors" absent are the placeholder literals `ERR_` and `ERR_XXX` from comment text). `api_prefix: "/"` matches the PRD's "All paths are mounted at the service root." Leak grep for `scaffold|expert level|test_recipe|benchmark` → 0 hits. No regeneration needed.

## Step 6: Generate implementation — 2026-09-06T00:37:06.343Z

(Recorded on completion. Step 5 was launched concurrently in the same assistant message and is still running at the time of this entry; its summary is appended below as its own Step 5 heading.)

Implementation complete and verified.

## Files (all in `/home/ubuntu/github/CodingPRD/tasks/task_2958_technical_documentation_release_notes_publishing/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `app.py` | 57 | Blueprint registration, ApiError/HTTPException/Exception handlers, `app.run(host="0.0.0.0", port=$PORT or 10000, use_reloader=False)` |
| `core.py` | 383 | 74-entry `ERROR_STATUS` map, `ApiError`, Decimal helpers (ROUND_HALF_UP), logical-clock helpers, in-memory `Store` (15 dicts + clock + `_seq`), envelope builders, pagination |
| `validate.py` | 227 | Auth bands 1–3 (`X-User-ID`/`X-User-Role`, 6 roles, entity-backed Writer/Reviewer identity), body/field validators, pagination + filter parsing |
| `calc.py` | 488 | All 12 calculations plus the 3 conserved-quantity full recomputes |
| `flows.py` | 146 | Shared cascades (sign-off supersession, job cancellation, doc-set archive, EOL cascade, review invalidation) |
| `routes_core.py` | 264 | clock, release trains, writers, reviewers |
| `routes_plan.py` | 219 | plan items (create/get/list/assign/cancel) |
| `routes_topic.py` | 275 | topics, revisions, submit-review, feedback, deflection summary |
| `routes_signoff.py` | 194 | sign-off request/list/get/decide (both branches) |
| `routes_docset.py` | 222 | doc-set versions + auto-created translation jobs on publish |
| `routes_change.py` | 253 | change records + release notes |
| `routes_loc.py` | 320 | locale profiles + localization jobs (deliver/rework/publish/cancel) |
| `routes_term.py` | 202 | terminology terms + deprecation notices |
| `start.sh` | 8 | executable; guarded `pip install`, `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.2` |

Total 3,259 lines. In-memory dicts only — no SQLite, no disk/`/tmp` persistence (grep for `sqlite|open(|json.dump|pickle|/tmp` returns nothing), and no entity seeding at boot (every `db.<collection>[...] =` write lives inside a POST handler).

## Endpoint coverage: 63 / 63

Programmatic set-diff of `app.url_map` against `SCAFFOLD.yaml`'s `endpoints` (paths normalised) came back with **zero missing and zero extra**. No gaps.

## Verification performed

- `ast.parse` clean on every module; `import app` clean; 63 registered rules.
- Fixed the outstanding `deflection_metrics` defect: window comparison is now instant-based per the scaffold's "BOTH ends inclusive" formula, with `timedelta`/`parse_instant` imported and the reported bounds derived from the new instant variables.
- Hand-checked calculations against the formulas: load points 36.00 / 43.20 / 3.75 / 3.75+1 rework = 4.75; quote 1500w tm=525 → leverage 35.00, base 13596, rush 0; same in a 5-day window → rush 2039, subtotal 15635; 30000w → 6% tier discount 21600 → 338400; MAJOR notice boundary 90 days → compliant, earliest_removal 2026-10-30.
- **Smoke test on `PORT=51958`** (server killed by captured PID each time; no `pkill`): full happy path train → writer → plan item → assign (load_points 36.00, writer ledger 36.00/1) → topic → revision → submit-review → two discipline sign-offs → FULLY_APPROVED (`signoff_latency_days` 5, `health_score` 96.00 / PRE_PUBLICATION) → locale profile → doc-set publish (`projected_localization_budget_cents` 13596, topic PUBLISHED, health re-derived to POST_PUBLICATION) → auto-created localization job → change record → editorial pass → release note compile (headline MAJOR, coverage 1.00, impact 12.00) → publish → page feedback → deflection summary (100.00 %) → POST_PUBLICATION health 92.00 → train advance to GA → localization job deliver (FINAL 12960, train ledger switches 13596 → 12960) → publish (`PUBLISHED_LOCALIZED`, locale reservation and train commitment both return to 0).
- Error paths confirmed with exact envelope shape: `ERR_UNAUTHENTICATED` 401, `ERR_UNAUTHORIZED` 403, `ERR_ROLE_IDENTITY_MISMATCH` 403, `ERR_INVALID_PAGINATION` 400, `ERR_RELEASE_TRAIN_NOT_FOUND` 404, `ERR_CLOCK_BACKWARD` 409, `ERR_STALE_RELEASE_TRAIN_VERSION` 412, `ERR_DUPLICATE_TERM` 409, `ERR_RELEASE_TRAIN_INVALID_ADVANCE` 409, `ERR_TRAIN_NOT_GA` 409, `ERR_LOCALIZATION_JOB_NOT_TRANSLATED` 409, plus shape-level `ERR_INVALID_REQUEST` for `tm_matched_word_count > translated_word_count`.
- Final cold boot on `PORT=51959` from a wiped `__pycache__`: ready in under 4 s, empty-list envelope correct, killed by PID, port free.

Two apparent discrepancies I chased turned out to be PRD-correct behaviour, not bugs: `expected_release_train_version` is OCC-checked **only** on doc-set-version create (PRD §2.6/§3.6), so plan-item create ignores it; and a single ENGINEERING approval leaves the topic at `PENDING_SIGNOFF` because FULLY_APPROVED needs one ENGINEERING *and* one PRODUCT approval pinned to the current revision (PRD §3.5). Also confirmed `included_change_record_ids` follows the PRD's severity-rank-then-created_at ordering rather than the scaffold's looser "created_at ASC" phrasing, per the PRD-wins rule.

Scratch was confined to `.scratch/step6/` and removed at the end; the sibling `.scratch/step5/` is untouched. I did not read `test_helpers/`, `test_suite/`, or any sibling task directory, and did not modify `worklog.md`, `SCAFFOLD*.yaml`, `PRD.md`, or `INSTRUCTION.md`.

## Step 5: Generate unit tests — 2026-09-06T01:02:38.212Z

(Recorded on completion. Launched concurrently with Step 6 in a single assistant message; Step 6 finished first so its entry appears above this one.)

Step 5 is complete. Both output directories are at the task root; nothing was written under `workspace/`.

## Deliverables

**`test_helpers/` — 9 files, 3,809 lines** (unchanged from Stage 1): `__init__.py` 36, `api_client.py` 363, `api_errors.py` 194, `assertions.py` 727, `constants.py` 259, `factories.py` 416, `fixtures.py` 1129, `test_users.py` 121, `types.py` 564. Package imports cleanly.

**`test_suite/` — `conftest.py` (70) + 16 test files, 9,202 lines, 171 tests:**

| File | Lines | Tests |
|---|---|---|
| test_01_release_train_registration_and_lifecycle | 463 | 13 |
| test_02_writer_roster_and_plan_item_registry | 455 | 8 |
| test_03_assignment_economics_and_writer_capacity | 1131 | 16 |
| test_04_topics_and_information_architecture | 695 | 11 |
| test_05_terminology_governance_and_submission_gates | 550 | 13 |
| test_06_review_requests_and_signoff_decisions | 540 | 12 |
| test_07_approval_invalidation_and_readiness_gating | 527 | 9 |
| test_08_documentation_set_publication_and_budget | 494 | 9 |
| test_09_archive_and_end_of_life_cascades | 416 | 6 |
| test_10_change_records_and_editorial_passes | 409 | 7 |
| test_11_release_note_compilation | 502 | 8 |
| test_12_localization_quotes_and_job_pipeline | 630 | 10 |
| test_13_localization_gates_windows_and_delivery | 833 | 14 |
| test_14_deprecation_notices_and_removal_timelines | 341 | 7 |
| test_15_reader_signals_and_topic_health | 426 | 7 |
| test_16_access_control_and_request_validation | 790 | 21 |

## Design-index coverage

- **Queue A (§1.8 difficulty): 20 / 20 translated, 0 skipped.** Every instance carries ≥2 tests.
- **Queue B (§1.9 corner): 60 / 60 non-stub translated, 0 skipped.** The 32 stub instances produced zero tests (verified: no `Design:` tag resolves to a stub).

No instance failed the PRD-first two-condition filter, so there are no skips to report.

## Verification (all clean)

An independent verifier at `.scratch/step5/verify_suite.py` re-checked every file: 171 tests, exactly one `Design:` line per test and always last, every tag resolving to a real non-stub instance; every `PRD §x.y: "…"` quote matched whitespace-normalised against `workspace/PRD.md` with zero non-verbatim and zero elided citations; no unused imports; every imported name present in the barrel; no `skip`/`skipif`/`xfail`/`TODO`. All 16 modules import cleanly, every file has ≥6 tests, and the suite was byte-stable over a 150 s re-check.

## Two real bugs found and fixed in my own exemplar

1. **`ApiErrorId.ERR_*` did not exist.** The enum's *members* are un-prefixed (`ApiErrorId.WRITER_ON_LEAVE`); only the values carry `ERR_`. Eight references in `test_01` would have raised `AttributeError` at collection. Fixed by a mechanical `ApiErrorId.ERR_` → `ApiErrorId.` edit; a repo-wide grep confirms no other file was affected.
2. **A version-bump assertion contradicted the PRD.** `test_01` asserted the train's `version` stays at 2 after a plan-item create (copying the corner instance's claim that "the plan-item create does not bump the train's version"). PRD §2.4 is explicit that `version` "increases by exactly 1 on every mutation the server applies to that resource — including mutations that arrive as the side effect of an operation on a different resource", and §3.2 says the create increments `plan_item_count` and recomputes readiness. Corrected to `version == 3` with the §2.4 citation added.

## Design-literal corrections applied (instances kept, per the PRD-wins rule)

`category` `CHANGED`/`FIXED` → `FIX`; `open_signoff_count` read from Reviewer not Topic; pagination sent as query params not a body; framework `NON_EXISTENT_UUID` instead of the yaml literal; new plan item's `load_points` `0.00` not null; fresh draft's `projected_localization_budget_cents` `0` not null; `person_key` uniqueness scoped per roster (§3.2 calls it "deliberately shared vocabulary", so a reviewer may reuse a writer's key); dropped assertions on a non-existent `LocalizationJob.delivered_at`.

## Two figures deliberately left unasserted (PRD does not uniquely derive them)

A topic's `health_score` immediately after a term retirement (the pre-retirement value on a never-approved topic is null), and `approved_plan_item_count` after a revision lands on an already-published page (§3.3's "drops by 1" conflicts with §3.1's derivation from plan-item statuses, since the item stays `PUBLISHED`). These are worth a look in Step 8/9 as candidate PRD ambiguities.

Scratch was confined to `.scratch/step5/`; the parent `.scratch/` was not touched. I did not read or write anything under `workspace/implementation/`, and did not modify `worklog.md`, `SCAFFOLD*.yaml`, `PRD.md`, or `INSTRUCTION.md`.

## Step 7: Run tests and iterate — 2026-09-06T01:29:24.239Z

Clean 8-round sweep achieved.

## Iterations run
2 (initial diagnostic sweep + one verification sweep after the fix).

## Final sweep — per-round results
All 8 rounds: **191 / 191 passed**, 0 failed, 0 errors, 0 skipped.

Results files:
- `/home/ubuntu/github/CodingPRD/tasks/task_2958_technical_documentation_release_notes_publishing/workspace/implementation/results.1.json`
- `.../results.2.json`
- `.../results.3.json`
- `.../results.4.json`
- `.../results.5.json`
- `.../results.6.json`
- `.../results.7.json`
- `.../results.8.json`

(Note: the suite is 191 collected tests, not 171 — parametrized cases expand.)

## Tests deleted
None. No test failed the STEP 1 coverage or unique-derivability checks.

## Fixes applied to `test_suite/`
- `/home/ubuntu/github/CodingPRD/tasks/task_2958_technical_documentation_release_notes_publishing/test_suite/test_16_access_control_and_request_validation.py`, `TestUniquenessKeysHonourTheirScope::test_a_page_slug_is_unique_across_the_whole_train_not_merely_its_deliverable` — the second plan item's authoring window was `2026-08-11` → `2026-08-17` (was `2026-08-10`), because the first assignment occupies `2026-08-02` → `2026-08-09` and PRD §3.2 states the leading-edge two-day handoff buffer makes "a one-day gap" collide while "a gap of exactly two days is accepted", so the original window legitimately tripped `ERR_WRITER_WINDOW_OVERLAP` before the test ever reached its slug-uniqueness assertion.

## Fixes applied to `test_helpers/`
None.

## Fixes applied to `implementation/`
None. The single failure was a test-setup precondition violation (STEP 2), not an implementation defect — `calc.windows_collide` implements §3.2's buffered half-open rule verbatim (`req_start < ex_end + 2 days and req_end > ex_start`), and the sibling test `test_a_gap_of_exactly_two_days_is_admitted` already confirmed the boundary was handled correctly.

## Key findings for the orchestrator
- Exactly **one** fix was made, and it was in `test_suite/`. The implementation was untouched, so **Step 8 has no implementation changes to fold into PRD_FINALIZED.md** — a byte-identical PRD_FINALIZED.md would be the legitimate outcome here.
- The failure was fully deterministic (identical in all 8 rounds of sweep 1); no flakiness, timeouts, or connection-reset symptoms appeared in either sweep, so no load-induced noise needed adjudication.

**Orchestrator verification:** independently re-read all 8 `results.$i.json` from the final sweep (mtime 01:19Z, after the fix). Every round reports 191/191 passed, 0 failed, 0 errors, 0 skipped — the clean sweep is real and the artifacts are on disk, not merely claimed.

**Step 8 decision:** NOT skipped. The skill's skip condition requires zero iterations beyond the baseline (0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes); this run had 2 iterations and 1 `test_suite/` fix, so Step 8 runs with that fix as its `<step_7_diff>`. Because there were no `implementation/` fixes, a byte-identical `PRD_FINALIZED.md` is a legitimate Step 8 outcome and will not be treated as a generator failure.

## Step 8: Finalize PRD — 2026-09-06T01:37:23.265Z

**Result: zero edits. `/home/ubuntu/github/CodingPRD/tasks/task_2958_technical_documentation_release_notes_publishing/workspace/PRD_FINALIZED.md` is byte-identical to `PRD.md`** (both 450 lines, 98135 bytes, md5 `eec9cff7ad23152f54880d791e7e6120`, `cmp` clean). Line-count delta: 0 lines, 0.0%.

### Why that is the correct outcome

`<step_7_diff>` contains exactly one item: a fixture-date change inside `test_suite/test_16_access_control_and_request_validation.py::TestUniquenessKeysHonourTheirScope::test_a_page_slug_is_unique_across_the_whole_train_not_merely_its_deliverable`. No test deletions, no `test_helpers/` fixes, no `implementation/` fixes. I independently verified the item is a pure test-precondition bug against a rule PRD.md already determines uniquely.

Arithmetic check (all values read directly, not taken on faith from Step 7):
- `test_helpers/constants.py:198-199` — the shared default window is `2026-08-02` → `2026-08-09`, and `topic_context` → `assigned_plan_item_context` → `assign_plan_item_payload` (`test_helpers/factories.py:103-110`) makes the first assignment occupy it.
- `implementation/calc.py:185-187`: `windows_collide` returns `req_start < add_days(ex_end, HANDOFF_BUFFER_DAYS) and req_end > ex_start`, with `HANDOFF_BUFFER_DAYS = 2` (`calc.py:31`) and `add_days` plain calendar addition (`core.py:198`).
- Old fixture start `2026-08-10`: `08-10 < 08-09 + 2d = 08-11` → True, and `08-16 > 08-02` → True ⇒ collides. That is the *one-day gap* case, which PRD.md line 177 explicitly says collides. The test tripped `ERR_WRITER_WINDOW_OVERLAP` before reaching its slug assertion — the fixture was wrong, the implementation was right.
- New fixture start `2026-08-11`: `08-11 < 08-11` → False ⇒ accepted. That is the *exactly two days* case, which PRD.md line 177 explicitly says is accepted.

PRD.md §3.2 line 177 states the rule in the same shape the code implements it, including the leading-edge-only buffer, the half-open interval, the touching/one-day-gap collisions, the two-day-gap acceptance, and the self-exclusion on reassignment. There is no silence and no mismatch to pin, so any edit here would have been manufactured.

### Pre-edit search log (run despite the zero-edit outcome)

- **(a) Subject:** the writer authoring-window collision rule for plan-item assignment — `ERR_WRITER_WINDOW_OVERLAP`, the two-day handoff buffer, and the set of windows compared against.
- **(b) Impl paths enumerated (grepped/read, not just the Step 7 site):**
  - `implementation/calc.py:185-187` — sole definition of `windows_collide`.
  - `implementation/routes_plan.py:120-132` — the sole callsite (`POST /plan-items/<id>/assign`); a repo-wide grep for `windows_collide` returns no other caller, so there is no second endpoint or cascade re-running the check with different semantics.
  - `implementation/calc.py:31` and `:39` — `HANDOFF_BUFFER_DAYS = 2` (used only at `calc.py:187`) and `COUNTED_ITEM_STATES = (ASSIGNED, IN_AUTHORING, IN_REVIEW, IN_REVISION, APPROVED_CONTENT)`, which matches PRD.md line 183's counted set verbatim.
  - `implementation/calc.py:193-196` — `writer_counted_items`, the comparison population; combined with the `other["id"] == item["id"]` skip at `routes_plan.py:124-125`, this is exactly PRD's "other counted plan items only / never collides with the window it currently occupies itself."
  - `implementation/routes_plan.py:126-127` — the null-window guard. Defensively skips items with no window, but no item can be in a counted state without having passed `assign` (which always writes both dates at `:146-147`), so this branch is unreachable and creates no PRD silence.
  - `implementation/routes_plan.py:119` (`ERR_INVALID_DATE_WINDOW`) and `:135-141` (capacity check ordered after the collision check) — confirmed consistent with PRD.md lines 175, 183, and the band-ordering sentence at line 113.
  - **Deliberately checked and excluded:** `implementation/routes_loc.py:135-151` implements a *different*, inclusive-both-edges, no-buffer overlap rule for localization vendor windows against `parallel_job_limit`. This is why I would not have widened any §3.2 wording into a universal claim about "windows" — a global-perspective edit there would have created a fresh mismatch with the localization path. No edit was made, so nothing risks it.
- **(c) Wording adjustment:** none — no sentence was changed.

**Orchestrator verification:** `cmp PRD.md PRD_FINALIZED.md` is clean. This is the legitimate Step 8 outcome per the skill: Step 7 applied zero `implementation/` fixes, so there is no impl-chosen behavior for Step 8 to fold back into the PRD. Step 9 (which always runs and must NOT be identical to its source) now performs the full PRD-vs-implementation scan.

## Step 9: Complete PRD — 2026-09-06T02:06:37.880Z

**Orchestrator decision — why Step 9 ran as three sequential passes.** A single subagent scanning a 450-line / 98 KB PRD against a 3,260-line implementation (13 modules, 63 endpoints, 74 error ids, 12 calculations, 11 state machines, 61 validations) reliably under-scans and can return a near-identical PRD_COMPLETED.md. Step 9 was therefore partitioned by implementation module into three **sequential** passes over one shared `workspace/PRD_COMPLETED.md`: pass 1 performed the `cp` from PRD_FINALIZED.md and later passes were explicitly forbidden from copying (a second `cp` would destroy the earlier passes' edits). Each pass's cross-module findings were forwarded verbatim to the next pass as a hand-off list.

- Pass 1 slice: `app.py`, `core.py`, `validate.py`, `calc.py`, `flows.py` (envelope, pagination, auth bands, logical clock, precision, the 12 calculations, shared cascades).
- Pass 2 slice: `routes_core.py`, `routes_plan.py`, `routes_topic.py`, `routes_signoff.py`.
- Pass 3 slice: `routes_docset.py`, `routes_change.py`, `routes_loc.py`, `routes_term.py`.

Aggregate: **PRD_FINALIZED.md 450 lines / 98,135 chars → PRD_COMPLETED.md 459 lines / 120,651 chars (+9 lines, +22,516 chars, +23.0%), 47 changed diff blocks, 53 edits total (37 ambiguity-pins, 16 mismatch-revisions).** The char delta far exceeds the line delta because this PRD stores one paragraph per physical line and the passes were instructed to prefer in-paragraph inserts over new paragraphs; passes 2 and 3 added no lines at all.

---

### Pass 1 of 3 — cross-cutting / computational core

- **Source** `workspace/PRD_FINALIZED.md`: 450 lines / 98,135 chars → **`workspace/PRD_COMPLETED.md`**: 459 lines / 108,925 chars (**+9 lines, +10,790 chars**). `cmp` confirms they are **not** identical (first divergence line 15). Document still ends at the last row of the §5 error table; heading count (25) and table-row count (141) are unchanged — no sections or table rows added.
- **Counts: 15 ambiguity-pins, 3 mismatch-revisions** (18 edits).

Changes:
- **§2.1** — insert — ambiguity — whitespace-only headers: only the exact empty string is absence, headers are never trimmed, and a whitespace `X-User-ID` is simply recorded as the opaque identifier for the four opaque roles (PRD said it "will fail later checks", which is false for `DocsLead`) — `validate.py:40-48`
- **§2.2** — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `[A-Z0-9]`, minted for error responses too — `core.py:255-257`
- **§2.2** — insert — **mismatch** — `api_request_timestamp` is read from the host's *real* clock, not the logical clock that §2.4 declares mandatory everywhere — `core.py:260-261, 304-305`
- **§2.2** — insert — ambiguity — pagination `meta` keys omitted on object/error responses; JSON object keys emitted in assembly order, not sorted — `core.py:308-328`, `app.py:23-26`
- **§2.3** — insert — ambiguity — integer parsing for `limit`/`offset` (whitespace tolerated, `+`/`-` sign allowed, empty/`5.0`/word rejected); offset past the end is 200 with an empty page — `validate.py:203-223`
- **§2.3** — insert — ambiguity — `has_more` defined as offset + returned count < `total_count` — `core.py:318`
- **§2.3** — insert — ambiguity — **`created_at` ties are broken by server creation sequence** (reversed for the newest-first train list); value-keyed orderings fall back to creation order — `core.py:273, 297-298`, `routes_core.py:114`
- **§2.3** — insert — ambiguity — filters are exact string equality, repeated params take the first value, unknown params ignored, and an out-of-enumeration filter value yields an empty page rather than a 400 — `validate.py:226-227`
- **§2.4** — insert — **mismatch** — a `version` bump requires an actual observable change: re-derivation to an identical value leaves `version`/`updated_at` alone (PRD claimed every side-effect visit increments) — `core.py:283-294`
- **§2.4** — insert — ambiguity — instant/date parsing: 0–6 fractional digits, `Z` mandatory (`+00:00` rejected), rendering truncates to 3 digits while full precision governs comparisons; dates exactly 10 zero-padded chars — `core.py:150-181`
- **§2.5 band 3** — revise — **mismatch** — identity resolution keys off the *caller's declared role*, not the endpoint's authorized list — `validate.py:49-58`
- **§2.5 band 4** — insert — ambiguity — absent/empty/`null` body reads as `{}`; non-object or malformed JSON is `ERR_INVALID_REQUEST`; explicit `null` == omitted; unknown fields ignored; booleans rejected where a number is required — `validate.py:69-96, 121-148`
- **§2.7** — insert — ambiguity — client-supplied decimal scale ("carried to one/two places") is **not validated**: extra places are stored and used unrounded; all numerics ship as JSON numbers so `1.00` appears as `1.0` — `validate.py:134-148`, `core.py:135-141`
- **§2.8** — insert — ambiguity — every other derived counter (assignment_count, open_signoff_count, open_job_count, train counts/ratio/posture) is also full-recomputed, not incremented — `calc.py:199-275`
- **§2.8** — revise — **mismatch** — cascade touch is conditional on real change; parent ledgers are settled once each, after the sibling sweep, in first-encounter order — `flows.py:32-38, 53-59`, `core.py:289-294`
- **§3.1** — insert — ambiguity — EOL: notice retirement runs after the five hops in `created_at` order; the closing recompute refreshes counts and ratio as well as the commitment; plan items are not zeroed — `flows.py:87-121`
- **§3.3** — insert — ambiguity — review invalidation leaves `health_score`/`health_score_variant` untouched (a stale `PRE_PUBLICATION` score can outlive its approval) — `flows.py:124-142`, confirmed against `routes_topic.py:160-165`
- **§3.4** — insert — ambiguity — scan lowercases both sides so mixed-case tokens are accepted; duplicate tokens are set-reduced; `preferred_form` is never matched — `calc.py:128-144`
- **§3.10** — insert — ambiguity — the deflection window is compared as **instants** while reporting calendar dates, so the two disagree at the edge when the clock carries a time of day — `calc.py:352-383`
- **§5 intro** — insert — ambiguity — undefined path → `ERR_INVALID_REQUEST` **404**, bad method → `ERR_INVALID_REQUEST` **405**, unexpected fault → `ERR_INTERNAL` 500; trailing slashes tolerated; `message` text is not contractual — `app.py:38-52, 22`

Handoff to later passes (routes_*.py — noticed, not edited): (1) `routes_plan.py:136-141` capacity check excludes the item's own current load; (2) `routes_plan.py:140` capacity total is `r2`-rounded before comparison; (3) `routes_plan.py:126-127` counted items with a null authoring window are skipped by the collision sweep; (4) `routes_term.py:103-107` term retirement recomputes `health_score` only when already non-null, with a variant-selection rule PRD never names; (5) `routes_topic.py:109-113` single-topic read recomputes health only when `PUBLISHED` and mutates without bumping `version`; (6) `routes_core.py:48-50` clock endpoint returns `data: {}` and echoes no clock value.

---

### Pass 2 of 3 — routes_core / routes_plan / routes_topic / routes_signoff

Pass 2 complete. All of pass 1's edit blocks are verifiably intact (verified by diff against `PRD_FINALIZED.md`: 32 changed blocks = pass 1's 17 + pass 2's 15).

| | before | after |
|---|---|---|
| lines | 459 | **459** |
| chars | 108,925 | **115,540** (+6,615) |

Line count did **not** grow: this PRD stores one paragraph per physical line, and the rules mandated in-paragraph inserts/revisions over new paragraphs. Every edit landed inside an existing paragraph, so growth shows up as +6,615 chars rather than new lines. Padding the doc with new lines just to satisfy the line-count check would have violated the minimal-patch rule.

Structure verified: 63 endpoint rows in §4, 74 error rows in §5, 28 headings, file still ends on `| ERR_WRITER_CAPACITY_EXCEEDED | 409 |`.

**Counts: ambiguity-pins 12, mismatch-revisions 5.**

Changes:
- §2.1 — revise — mismatch — "leave one page rating per reading session" → "leave page ratings on a live one"; the per-session cap does not exist — `routes_topic.py:223`
- §2.4 — revise — ambiguity — clock endpoint returns HTTP 200 with an empty `data` object, echoes no clock value, mutates no record — `routes_core.py:48-51`
- §2.10 — revise — mismatch — end-of-support date must be *strictly* later than GA (equal is refused); GA equal to freeze is accepted — `routes_core.py:72`
- §3.1 — revise — ambiguity — a `target_status` outside the five spine values is `ERR_INVALID_REQUEST`, not `ERR_RELEASE_TRAIN_INVALID_ADVANCE`; hop preconditions run only after the successor test — `routes_core.py:127,133`
- §3.1 — revise — mismatch — the GA gate tests *current* `PUBLISHED` status, not history: a published-then-archived doc set does not satisfy it — `routes_core.py:138-142`
- §3.2 — revise — mismatch — `feature_key` uniqueness within a train is a convention, not enforced; no error code exists — `routes_plan.py:45`
- §3.2 — revise — ambiguity — plan-item creation defaults `assigned_writer_id`, both window dates and `cancel_reason` to present-and-null — `routes_plan.py:62-68`
- §3.2 — revise — ambiguity — reassigning an `ASSIGNED`/`IN_AUTHORING` item keeps its status; every accepted assignment still bumps `version` — `routes_plan.py:150-152`
- §3.2 — revise — ambiguity — the collision sweep skips counted items with a null window (defensive; unreachable on defined transitions) — `routes_plan.py:126-127`
- §3.2 — revise — mismatch — capacity compares against the sum over the writer's **other** counted items, not the stored `committed_load_points`; total is rounded before the `>` test — `routes_plan.py:136-140`
- §3.2 — revise — mismatch — cancellation returns to `NOT_SUBMITTED` only topics where a sign-off was actually superseded; also pins what it never touches — `routes_plan.py:205-208`
- §3.3 — revise — ambiguity — topic creation opens five more fields as present-and-null; `health_score_variant` is null, not absent — `routes_topic.py:91-97`
- §3.3 — revise — ambiguity — single-topic read refreshes health only when `publication_state` is exactly `PUBLISHED`, persists it, and bumps neither `version` nor `updated_at`; `ARCHIVED`/`UNPUBLISHED` are never refreshed — `routes_topic.py:109-114`
- §3.3 — revise — ambiguity — `used_terms` is a mandatory field that may be an empty array — `routes_topic.py:137`
- §3.5 — revise — ambiguity — a fresh sign-off carries `decided_at` and `comment` as present nulls — `routes_signoff.py:58-61`
- §3.5 — revise — ambiguity — `comment` is written on both decide branches, null when omitted, empty string legitimate — `routes_signoff.py:118,135`
- §3.10 — revise — ambiguity — locale lookup ignores the profile's `status`, raises `ERR_LOCALE_PROFILE_NOT_FOUND` (404), and runs *before* the publication-state check; feedback bumps the topic's `version` only if health moved — `routes_topic.py:227-231,244-246`
- §3.10 — revise — mismatch — `PRE_PUBLICATION` is selected by reaching `FULLY_APPROVED`, not by `publication_state`: an already-live page that is revised and re-approved reverts to a `PRE_PUBLICATION` variant — `routes_signoff.py:157`

Verdict on the 5 handed-off findings: (1) capacity excludes the item's own load — **CONFIRMED and pinned**, materially different on same-writer reassignment; (2) total is `r2`-rounded before comparison — **CONFIRMED and pinned**, pinned as a formality since every addend is already 2dp so the rounding never changes the outcome; (3) window-less counted items skipped — **CONFIRMED and pinned**, with the caveat that it is unreachable (`assigned_writer_id` is only ever set by `assign`, which always writes both dates; `cancel` clears the writer rather than the dates), so it is pinned as an explicitly defensive rule; (4) read-that-writes, `PUBLISHED`-only — **CONFIRMED and pinned**, both the `ARCHIVED` gap versus §3.10's variant assignment and the mutation-without-audit-bump; it is the only read in the system that changes future reads without touching audit fields; (5) clock returns `data: {}` — **CONFIRMED and pinned**, weakly implied already by §2.2's "2xx with no data", now explicit in §2.4.

Handoff to pass 3: `routes_docset.py:~101` archive route gates only on the doc set being `PUBLISHED` with no release-train status gate (this is what makes the §3.1 GA-gate finding reachable); `routes_docset.py:~54,70-71` publish flips plan items `APPROVED_CONTENT → PUBLISHED`, silently lowering the writer's `committed_load_points` as a side effect of a doc-set operation; `routes_term.py:120,146` deprecation notices carry their own `feature_key` matched against `change_records.affected_component` in `routes_change.py:232`, and since plan-item `feature_key` is non-unique, §3.7/§3.9 should be checked for a uniqueness assumption.

---

### Pass 3 of 3 — routes_docset / routes_change / routes_loc / routes_term

**Size:** 459 lines / 115,540 chars → **459 lines / 120,651 chars** (+5,111 chars, no line added — one paragraph per line preserved).
**Counts:** 10 ambiguity-pins, 8 mismatch-revisions (18 edits landing in 15 diff blocks; 3 blocks carry two edits each).

Changes:
- §3.4 (`routes_term.py:43`, `calc.py:137`) — revise — mismatch — `forbidden_forms` no longer claims "none may equal the `preferred_form` of any other active term" (no such check exists, and no error code for it); lowercase is not enforced on entries.
- §3.4 (`routes_term.py:103-107`) — revise — mismatch — retirement recomputes `health_score` **only when the topic already carries one**, reusing that topic's existing `health_score_variant`; null-score topics keep null score/variant while counters still move.
- §3.6 (`routes_docset.py:44-48,62-64`) — insert — ambiguity — duplicate `version_label` names `ERR_DUPLICATE_VERSION_LABEL`, uniqueness spans sets of any status; `eol_notice_text`/`published_at`/`archived_at` present and null at create.
- §3.6 (`routes_docset.py:158-165`) — revise — mismatch — projection is **not** stored when the cap check fails; a refused publish leaves `projected_localization_budget_cents` at 0 (the old text said "computed, stored, and compared", contradicting the same paragraph's "before any state is mutated").
- §3.6 (`routes_docset.py:170-171`) — insert — ambiguity — a `FULLY_APPROVED` topic already `PUBLISHED`/`ARCHIVED` is passed over: keeps `published_at`/`published_in_doc_set_version_id`, no health recompute, plan item untouched even at `APPROVED_CONTENT`, excluded from `published_topic_count`.
- §3.6 (`routes_docset.py:114`) — insert — ambiguity — auto-created job pins `source_revision_number` from the topic's `current_revision_number`.
- §3.6 (`routes_docset.py:194-199`) — insert — ambiguity — the train's `localization_committed_cents` recomputation runs *after* job seeding, so it counts the auto-created jobs' provisional quotes.
- §3.6 (`routes_docset.py:210-212`) — insert — ambiguity — archive's **only** precondition is `status == PUBLISHED`; the train's lifecycle status is not consulted, which is how a train reaches the `DOC_FREEZE → GA` gate of §3.1 with nothing `PUBLISHED` left.
- §3.7 (`routes_change.py:62`) — insert — ambiguity — `editorial_by_user_id` opens null.
- §3.7 (`routes_change.py:99-104`) — revise — mismatch — the **state** test precedes the segregation-of-duties test (PRD listed SoD first); a submitter editing their own approved record gets `ERR_CHANGE_RECORD_NOT_EDITABLE`.
- §3.7 (`routes_change.py:96`) — insert — ambiguity — editorial-pass `used_terms` is mandatory, 0–200 entries of 1–60 chars.
- §3.7 (`routes_change.py:220-224`) — revise — mismatch — the included set is fixed once at compilation.
- §3.7 (`routes_change.py:220-252`) — insert — mismatch — publication reads the stored `included_change_record_ids`, never re-runs the query: a later-approved record is neither scored nor published; a record an earlier note already published still faces the breaking-change gate and still contributes its weight, with its `state` untouched.
- §3.8 (`routes_loc.py:128-129`) — insert — ambiguity — job-create resolves `topic_id` before `locale_profile_id` (both unknown → `ERR_TOPIC_NOT_FOUND`).
- §3.8 (`routes_loc.py:147-148`) — insert — ambiguity — auto-created jobs neither undergo the parallelism test nor occupy a slot in it.
- §3.8 (`routes_loc.py:278-303`) — insert — ambiguity — delayed branch when the lag has already elapsed publishes in one step with `publication_mode_applied` `DELAYED` and a **non-null** `scheduled_publish_date`; a parked job keeps that date when it publishes; a too-early attempt writes nothing (no `version`/`updated_at` move).
- §3.9 (`routes_term.py:120`) — revise — mismatch — deprecation `feature_key` is **not** unique within the train (no check, no error code); the §3.7 gate is satisfied by any matching published notice.
- §3.9 (`routes_term.py:191-197`) — revise — mismatch — publish order is status → guide live → announce date (PRD had announce before guide), matching §2.5 bands 12 before 15.

Verdict on the 4 handed-off findings: (1) term-retirement health/variant — **confirmed and pinned** (§3.4); (2) archive has no train-status gate — **confirmed and pinned** (§3.6), cross-referenced to pass 2's §3.1 "at the moment of the advance" GA-gate wording; (3) writer-ledger side effect of doc-set publish — **confirmed, already pinned** by §3.6 ("the published item leaves the counted set… `committed_load_points` decreases… `assignment_count` decreases by 1"), no edit needed, but the adjacent skip rule for already-live topics was pinned; (4) `feature_key` uniqueness — **confirmed, with the defect on the other side**: both matching sites (`calc.py:466` coverage, `routes_change.py:230` breaking-change gate) are existential any-match tests, so plan-item non-uniqueness is harmless and §3.7 needed no change — the real mismatch was §3.9 asserting deprecation-notice `feature_key` is "unique within that train" when impl enforces nothing, now revised.

Pass 3 integrity checks: ends at a real boundary (`| ERR_WRITER_CAPACITY_EXCEEDED | 409 |`); §4 has 63 endpoint rows; §5 has 74 `ERR_*` rows (matches `core.ERROR_STATUS` exactly, `ERR_INTERNAL` remains prose-only); `diff PRD_FINALIZED.md PRD_COMPLETED.md` shows 47 changed blocks = 17 + 15 + 15, all earlier blocks intact; `grep -ic "scaffold|expert level|test_recipe|benchmark|SCAFFOLD"` → 0 (a broader grep hits the word "difficulty" once at §3.2 describing `complexity_points` as "the estimator's judgement of difficulty" — ordinary domain prose, not a difficulty-level leak).

---

### Orchestrator final verification

- `wc`: PRD.md 450/98,135 · PRD_FINALIZED.md 450/98,135 · PRD_COMPLETED.md 459/120,651.
- `cmp PRD.md PRD_FINALIZED.md` clean (legitimate — Step 7 applied zero implementation fixes). `cmp PRD_FINALIZED.md PRD_COMPLETED.md` differs, 47 changed diff blocks — Step 9 demonstrably scanned rather than no-op'ing.
- PRD_COMPLETED.md ends at a real section boundary (final `ERR_WRITER_CAPACITY_EXCEEDED | 409` row), 63 endpoint rows in §4, 74 `ERR_*` rows in §5, 26 headings, leak grep 0.
- `implementation/*.py` mtimes are all ≤ 00:19Z — before both Step 7 sweeps (01:09Z and 01:19Z) — independently confirming Step 7 made zero implementation edits and that Step 9 modified nothing but `PRD_COMPLETED.md`. The last test-file write is 01:13Z (Step 7's single `test_suite/` fixture fix), which the clean 01:19Z sweep postdates, so the recorded 8×191/191 green sweep is the state of the artifacts as they stand now.
- One `worklog.md` only, at the task root; no strays under `workspace/`. Scratch tree `.scratch/` removed.

**Pipeline complete.** `workspace/PRD_COMPLETED.md` is written; all nine steps finished.
