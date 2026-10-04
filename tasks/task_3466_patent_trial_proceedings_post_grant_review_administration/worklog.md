# Worklog — task_3466_patent_trial_proceedings_post_grant_review_administration

## Step 1: Create Task Directory — 2026-10-02T09:56:00.000Z

Task directory pre-allocated by the invoker and verified to exist: `tasks/task_3466_patent_trial_proceedings_post_grant_review_administration/` with empty `workspace/` inside. No index computation performed per invoker instruction.

## Step 2: Generate Scaffold — 2026-10-02T11:02:00.000Z

All three artifacts are complete, parse clean, and pass the lint with a clean verdict. Final report:

## Deliverables (all under `/home/ubuntu/github/CodingPRD/tasks/task_3466_patent_trial_proceedings_post_grant_review_administration/`)

| File | Lines | Parse | Contents |
|---|---|---|---|
| `SCAFFOLD.yaml` | 1605 | OK | §1.0–§1.7 only (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1427 | OK | single key `scaffold_difficulty_design`, **19 instances** (9 rules × ≥2; rule 2 carries 3, one per mode) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3266 | OK | single key `scaffold_corner_design`, **71 instances** (65 active + 6 `excluded_because` stubs) |

**Lint verdict (verbatim tail):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (40 endpoints, 14 entities, 807 calls scanned.)

**Endpoint count: 40** — exactly at the hard cap, not over. **api_prefix: `/ptab`**; the logical-clock endpoint sits unprefixed at `POST /_clock/set_current_utc` with the mandatory default `2026-09-01T00:00:00Z` stated in its description.

## Design shape
- **Archetype**: compliance/audit primary + workflow orchestration; flat topology, cyclic state machines, peer_roles RBAC (Petitioner/PatentOwner entity-backed by Party, BoardPanel/PlatformAdmin/AppealsCourt opaque), immediate consistency.
- **14 entities** (Party, Patent, LitigationMatter, Petition, InstitutionDecision, Proceeding, Brief, ExpertDeclaration, DiscoveryRequest, AmendmentMotion, OralHearing, HearingRoom, FinalWrittenDecision, Appeal); **8 state machines** including two cyclic ones (Proceeding remand loop DECIDED→REMANDED→REPLY_WINDOW, OralHearing continuance loop SCHEDULED→REQUESTED→SCHEDULED); **43 error codes**, all named in at least one design instance; **2 OCC concurrency rules** (petition filing vs Patent.version, matter patch vs LitigationMatter.version).
- **Difficulty rules** all grounded: dual-variant calcs in different domains (petition merits per-ground-max vs weighted aggregate; FWD deadline fixed-365-days vs 12-month anniversary, with a leap-day fixture at 2027-03-10 → 2028-03-09 vs 2028-03-10); combinatorial formulas in modes (a) Garmin factor cap + reply-phase bonus, (b) per-brief round-then-sum fee order (632 vs 633 cents), (c) Fintiv proximity pinned against the base projected FWD date, never the extended one; depth-3 cascades from two different triggers (FWD full-cancellation → patent → litigation stay; remand → patent → estoppel unwind); boundary checks at 365/366-day time bar and 40/39 merits threshold; hearing-room buffered-interval vs judge aggregate-capacity overlap semantics; compensating invariants on claim-ledger mass (claims_alive + cancelled == total_claims) and per-cycle amendment slot budget.
- All numeric/date literals in asserts were pre-computed with Python (window ends 2026-12-03, fee values 316/1581/633/1915000, FWD deadlines 2027-09-01/2028-03-02, etc.).

## Incidents handled during generation
- Two heredoc junction corruptions (stray `YAML_EOF`/command lines embedded at append boundaries) were detected by the per-append parse checks and removed; a missing trailing newline at one file tail was fixed before subsequent appends.
- One YAML flow-mapping bug (`$.data[0].id` unquoted) fixed by quoting.
- Lint caught 3 envelope-pagination captures (`$.data.total_count` on list endpoints) — fixed to whole-`$.data` captures.
- Self-audit found `ERR_BRIEF_SEQUENCE_VIOLATION` would have been dead code (phase gate always fired first); fixed by adding a `SUR_REPLY_WINDOW → SUR_REPLY_WINDOW` self-loop transition for sur-reply filing, making the per-cycle uniqueness check reachable, plus a corner instance proving it. Also added Patent re-entry transitions (PARTIALLY_CANCELLED/AMENDED/CONFIRMED/IN_REVIEW → IN_REVIEW on new institution) and a FULLY_CANCELLED petition guard after the state-machine reachability sweep.

Orchestrator verification: all three files exist at the task root, all three parse clean via yaml.safe_load, `/ptab` prefix appears 119× in SCAFFOLD.yaml, and domain markers (Petition, InstitutionDecision, FinalWrittenDecision, Appeal, PatentOwner) are present — no foreign-domain contamination.

## Step 3: Copy Shared Files — 2026-10-02T11:03:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T11:15:00.000Z

**Done.** Generated `/home/ubuntu/github/CodingPRD/tasks/task_3466_patent_trial_proceedings_post_grant_review_administration/workspace/PRD.md` — **327 lines**, built in 8 verified chunks (tail checked after every append). The two forbidden design-index files were never opened.

**Coverage summary:** The PRD renders all 14 scaffold entities to prose (Party, Patent, LitigationMatter, Petition, InstitutionDecision, Proceeding, Brief, ExpertDeclaration, DiscoveryRequest, AmendmentMotion, OralHearing, HearingRoom, FinalWrittenDecision, Appeal), all 8 state machines with every transition's preconditions and side effects (including the Patent IN_REVIEW self-loop, the SUR_REPLY_WINDOW self-loop, and the DECIDED→REMANDED remand unwind), all 13 calculations with constants embedded in business prose (merits thresholds 40/51 with the 0.7/0.3 advisory aggregate, Fintiv 20/40/20/−20 clamped scoring with the pinned base-deadline evaluation order, 365+183-day FWD deadline vs. advisory anniversary leap-day divergence, 90/132/146-day brief windows, Garmin factor scoring with the zero-factor cap and reply bonus, per-brief-then-sum overage rounding at 316.25 cents/page, the 1,900,000-cent fee schedule, the 365-day time bar, the 93-day institution window, the 30-minute hearing-room turnover buffer, panel capacity < 2, estoppel scope, and the claim-ledger invariant with status precedence), all 10 validation priorities in explicit order (§2.11), both OCC rules with exact error IDs and HTTP 412 (§2.7), all 5 roles with identity translations (§2.1), all 40 endpoints in the §4 4-column table (clock endpoint correctly unprefixed), and all 43 errors in the §5 2-column table with trigger conditions scattered through §2/§3.

**Hard contract reports:**
```
Field coverage check:
- entities[].fields + endpoint inputs/query/path identifiers: 95 required, 95 present, 0 missing
- (61 enum/state values also verified present)
Status: PASS

Rule coverage check (manual walk during drafting):
- validations[] priority ordering: 10 levels, expressed as numbered order in §2.11
- concurrency_rules[]: 2/2 (write_endpoint + expected_<parent>_version + error_id + 412 named)
- state_machines[].transitions: all 8 machines, all transitions expressed (from/to, preconditions+error_id, side effects)
- calculations[]: 13/13 in precise prose, no pseudocode, boundaries stated (40 institutes/39 doesn't; exactly 365 days not barred; exactly 93 timely/94 lapsed; 1 active admits/2 rejects; buffered-interval adjacency)
- validations[] conditions: all matchable to error_ids in §2/§3 narrative; all 43 error IDs in both narrative and §5 table
- endpoints[].side_effects: all expressed (cascades, version increments, fintiv refreshes, estoppel attach/unwind)
- entities[].fields[] structured content: defaults (nulls, 60 minutes, PHILLIPS, false flags, 1 slot, 0 cycle) and immutable-record status of InstitutionDecision/FinalWrittenDecision stated
- sibling-branch symmetry: IPR-vs-PGR ground rules, DENIED_MERITS/DENIED_DISCRETIONARY, HELD/WAIVED/CONTINUED role splits, GRANTED/DENIED/WITHDRAWN splits all rendered with equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 467
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 verified byte-identical to `section-2.2-response-structure.md`. Document ends at §5 with no audit footer. (One tooling note: the verification regex initially false-negatived because ``` code fences unbalance naive backtick pairing — stripping fences before tokenizing fixed the checker; the document was never defective.)

Orchestrator verification: PRD.md exists at 327 lines, `/ptab` appears 42×, tail is the §5 error table (ERR_OUTCOME_SET_INVALID / ERR_FEE_INSUFFICIENT rows).

## Step 5: Generate Unit Tests — 2026-10-02T11:45:00.000Z

Task complete. Test infrastructure and suite generated for task_3466 (patent trial proceedings / PTAB post-grant review).

## What was built

**Stage 5a — `test_helpers/` (frozen before any test file):** `types.py` (all 13 entities + 15 enums; immutable event records omit `updated_at`/`version`), `api_client.py` (one method per endpoint; `set_clock` correctly uses the **unprefixed** `/_clock/set_current_utc`), `api_errors.py` (all 38 error IDs with PRD §5 statuses, registered via `set_error_http_status_map`), `assertions.py` (per-entity asserts, claim-ledger invariant, `assert_same_instant` tolerant of optional fractional seconds), `factories.py`, `constants.py` (all values from PRD prose: 40/51 thresholds, Fintiv 20/40/20/−20/70/180, fees 1,900,000+15,000>20, windows 90/132/146, caps 110/65/40, rate 316.25, buffer 30, capacity 2, window 93, bar 365, default clock 2026-09-01T00:00:00Z), `test_users.py` (opaque-role constants + mandatory per-instance builders for entity-backed Petitioner/PatentOwner), `fixtures.py` (five tiers: `new_world` → `setup_instituted_proceeding` → `setup_hearing_scheduled` → `setup_decision_phase` → `setup_decided_proceeding`/`_with_appeal`, plus `add_petitioned_patent` for multi-patent worlds; identity threading via `make_*_headers(entity.id)` throughout).

**Stage 5b — `test_suite/` (21 files, one per message):** 104 tests = 38 difficulty (19 instances × 2) + 66 corner (65 non-stub instances; the day-93/day-94 institution-window instance's two trigger arms were translated as two tests under the same tag).

## Audit numbers (all gates run, all green)

- AST tag audit (real `ast` walk vs. both YAML indices): difficulty instances with <2 tests: **0**; corner instances with <1 test: **0**; untagged: **0**; dual-tagged: **0**; unknown tags: **0**; stub tags used: **0**; all 6 `excluded_because` stub cross-references resolve to real difficulty instances. Every docstring **ends** with its `Design:` line.
- `pytest --collect-only`: **104 tests collected, 0 errors** (package graph intact).
- Verbatim citation sweep: **139 quoted segments, 0 failures** against PRD.md (whitespace-normalized grep).
- No `skip`/`skipif`/`xfail`; no "scaffold" references in generated code.
- Instances skipped: **none**.

## Judgment calls worth flagging

1. **Design-index literal corrected against PRD**: `dual_variant_calc/merits_per_ground_max...` asserts `advisory_aggregate_score == 28` for scores [40,0,0], but the PRD formula (0.7·max + 0.3·mean, round-half-up) yields **32**. Tests assert 32 — the instance's distinguishing point (aggregate 32 < 40 while max 40 ≥ 40 institutes) is preserved. The other two aggregate literals (70 for [80,40,20]; 83 for [90,40]) check out and are used.
2. **Dropped one underivable literal**: `version == 1` on party creation — PRD §2.5 says version increments per modification but never pins the initial value; the test asserts all PRD-covered fields and lets `assert_party` check version is a positive int.
3. **Timestamp equality is instant-based** (`assert_same_instant`, parses ISO) since PRD §2.5 allows three-fractional-digit forms — avoids failing faithful serializers emitting `.000Z`.
4. **Priority-pair tests kept** (not skipped under the validation-priority silence pattern) because PRD §2.11 states the full ten-category order verbatim, satisfying coverage + unique derivability.

Orchestrator verification (independent of subagent claims): 104 `def test_` functions across test_suite/; Design tags counted from source = 66 Corner + 38 Difficulty = 104, matching; unique ERR_* ids in PRD.md = 43 and in test_helpers/api_errors.py = 43 with EMPTY diff (the subagent's "38 error IDs" remark was a misstatement — actual registration is complete). NOTE for Step 6→7 hand-off: tests assert advisory_aggregate_score == 32 for per-ground scores [40,0,0] per the PRD formula 0.7·max + 0.3·mean round-half-up (the design index's literal 28 was adjudicated WRONG by Step 5 and overridden); the implementation must follow the PRD formula.

## Step 6: Generate Implementation — 2026-10-02T12:27:00.000Z

Everything verifies clean. Final report follows.

---

# Final Report — task_3466 PTAB Implementation

## File list (all under `workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Foreground launcher, guarded `pip install`, `exec python3 app.py` |
| `requirements.txt` | 1 | flask>=3.0 |
| `app.py` | 60 | Entry point, error handlers, blueprint registration, store lock, `0.0.0.0:$PORT` (default 10000) |
| `db.py` | 109 | In-memory store + logical clock (default `2026-09-01T00:00:00Z`, never wall-clock) |
| `errors.py` | 78 | ApiError + full error-id catalog verbatim from SCAFFOLD Table 6 |
| `helpers.py` | 191 | Envelope (`meta`/`response_type`/`data`), pagination (`limit/offset/total_count/has_more`, default 10/1..100/0), auth + role gates, field validators |
| `lookups.py` | 112 | Left-to-right path existence + body-FK existence, party-to-proceeding checks |
| `calculations.py` | 218 | Merits threshold + advisory aggregate (Decimal ROUND_HALF_UP), Fintiv (base-365-day projection pinned), FWD fixed-days vs anniversary months, brief windows, Garmin, overage per-brief rounding, fee tiers, time bar, buffered room conflict, panel capacity |
| `routes/__init__.py` | 33 | Blueprint registry |
| `routes/clock.py` | 25 | `POST /_clock/set_current_utc` — unprefixed |
| `routes/parties.py` | 30 | Party registration |
| `routes/patents.py` | 113 | Patent create/list/get + matter docketing beneath patents |
| `routes/matters.py` | 107 | Matter list/get + OCC-guarded PATCH with stay_reason provenance and Fintiv refresh |
| `routes/petitions.py` | 347 | Filing (10-step validation ladder), accord (IPR screens), decide-institution (merits/Fintiv/window/capacity + 3 cascade links), decision read |
| `routes/proceedings.py` | 74 | Proceeding reads + extension request (+183 days / +6 months) |
| `routes/briefs.py` | 151 | Brief filing (phase gates, windows, sequence, caps, per-brief fee) + expert declarations |
| `routes/discovery.py` | 81 | ROUTINE auto-grant, ADDITIONAL Garmin scoring, deterministic panel ruling |
| `routes/amendments.py` | 135 | Motion filing (slot/quota/volume/mismatch) + per-outcome role-split resolve with claim-ledger swap |
| `routes/hearings.py` | 198 | Hearing request, scheduling (buffered half-open conflict, FWD cutoff), HELD/WAIVED/CONTINUED resolve |
| `routes/decisions.py` | 141 | FWD issuance (already-issued → phase → deadline → outcome-set order), ledger reconciliation, estoppel attach, full-cancel stay cascade |
| `routes/appeals.py` | 116 | Appeal filing + appellate dispositions with remand unwind cascade |
| `routes/rooms.py` | 26 | Hearing-room registration |

**Total: 2,356 lines across 21 files. Endpoint count: exactly 40** (verified programmatically from Flask's url_map), with `/_clock/set_current_utc` the only unprefixed route (grep-confirmed). No seeding — the store starts empty; only mention of "seed" is the docstring saying there is none.

## Smoke-test transcript summary

Two suites, each against a fresh `start.sh` boot on a dynamically allocated port (via `socket.bind(("",0))`), each server killed by exact PID afterward (surviving `python3 app.py` processes on the host verified to belong to other tasks' pipelines and left untouched):

- **Suite 1 — 26/26 PASS**: missing-auth 400; clock set/echo round-trip; role 403 on clock; party/patent creates (201, ISSUED, ledger init); petitioner-as-owner → `ERR_VALIDATION`; fee one cent short of 1,975,000 → 402 `ERR_FEE_INSUFFICIENT`; stale patent version → 412; filing bumps patent version; accord FILED→NOTICE_ACCORDED; re-accord → 409 `ERR_PETITION_WRONG_STATE`; score 39 vs IPR threshold 40 → `DENIED_MERITS`; decision read as 1-element array without `version`/`updated_at`; institution creates proceeding with `fwd_due_date` 2027-09-01 (= +365 days) and `advisory_anniversary_date` +12 months; cross-side brief → 403 `ERR_NOT_RESOURCE_OWNER`; 95-page PO_RESPONSE → fee 1581 (`round_half_up(5×316.25)`) and phase → REPLY_WINDOW; repeat PO_RESPONSE → 409 `ERR_INVALID_PHASE`; declaration 201; unknown role → 403; pagination meta; 404 family.
- **Suite 2 — 41/41 PASS**: time bar (>365 days) → 422; provisional Fintiv 40 (base+investment); matter PATCH OCC + version bump; Fintiv refresh to 80 after trial_date set; stale matter 412; merits-met + Fintiv 80 → `DENIED_DISCRETIONARY`; manual stay `MANUAL_STAY`; institution after stay; amendment grant ledger swap (total 3, cancelled 1, amended 1, alive 2 — invariant holds); Garmin `min(8,4)+1` reply bonus = 5 → DENIED; ROUTINE auto-granted with factors ignored; new-evidence-on-reply 422; hearing request/ALREADY_PENDING 409/schedule/HEARING_PHASE; party resolving HELD → 403; panel HELD → DECISION_PHASE; outcome-set marking substituted claim UNPATENTABLE → 422; FWD issues, patent AMENDED, estoppel = challenged claims on defendant-matching matters; second FWD same cycle → 409; remand_instructions on AFFIRMED → 400; VACATED_AND_REMANDED → REMANDED, cycle 1, slots 1 (0 consumed + 1 fresh), estoppel_applied false, patent back IN_REVIEW, matters' estoppel cleared; cycle-1 PO_RESPONSE accepted from REMANDED.
- An accidental double-run against a dirty server additionally confirmed `ERR_PANEL_CAPACITY_EXCEEDED` fires at exactly 2 active proceedings per lead.

## Guard self-audit and interpretation choices

Every guard was traced to a verbatim PRD sentence (§2.1/§2.11/§3 prose) before shipping; I removed one invented guard found in audit (`argument_minutes >= 1` — neither PRD nor scaffold constrains it; now integer-only, default 60). I deliberately did **not** add: patent_number/room-name uniqueness errors (no error id exists for duplicates), a party_type constraint on `defendant_party_id`, basis-enum validation on `per_ground_scores`, phase gates on discovery/declaration endpoints, or rejection of `AMENDED_SUBSTITUTED` on non-substituted claims (the catalog's outcome-set condition doesn't list it).

Interpretation choices where the PRD admitted more than one reading:

1. **Clock echo format**: `current_utc` echoes the supplied `to_iso8601` verbatim; all system-stamped/computed datetimes use ISO 8601 UTC with three fractional digits per §2.5; input-sourced datetimes (issue_date, complaint_served_date, trial_date, start_at, end_at) echo the client's string verbatim.
2. **`api_request_timestamp`** is stamped from the logical clock, per §2.4's "never by wall-clock time under any circumstance."
3. **Missing OCC fields** → `ERR_VALIDATION` (§2.7 says the request "must carry" them), not a skipped check.
4. **Body-FK existence order** on `POST /ptab/petitions`: patent before petitioner (scaffold priority-3 entry order); non-string FK values defer to `ERR_VALIDATION` at priority 5 rather than 404.
5. **Brief authorship is identity-based** (caller id vs owner/petitioner id), per §3.5's pinning of `ERR_NOT_RESOURCE_OWNER` for side violations, rather than role-shaped per the roles table.
6. **Within-priority-9 ordering**: amendment quota → substitute mismatch → volume (scaffold check-sentence order); brief sequence before page cap (scaffold transition order); hearing interval validity before room conflict.
7. **Same-status matter PATCH** (e.g. ACTIVE→ACTIVE) → `ERR_INVALID_STATE` (no self-transition in the machine); explicit JSON `null` trial_date clears it, absent leaves it unchanged.
8. **Version bumps**: client writes always bump on success; cascade writes bump only when a value actually changes (§2.5 "increments with every modification").
9. **Institution cascade on a FULLY_CANCELLED patent** leaves status unchanged (terminal, no machine transition) while still creating the proceeding — PRD is silent on this corner.
10. **Extension guard order**: `ERR_EXTENSION_ALREADY_USED` before the DECIDED/CLOSED phase check (§3.8 prose order).
11. **Fintiv refresh also fires after the full-cancellation stay cascade**, per §3.2's "both of the cascades that can stay a matter."
12. **Pagination params honored on all list endpoints** (including sub-resource lists) with declared defaults; out-of-range limit/offset → `ERR_VALIDATION`.

Orchestrator verification: all 21 files exist under workspace/implementation/ (13 route modules + app/db/errors/helpers/lookups/calculations + start.sh/requirements.txt), every .py compiles via py_compile, start.sh is executable. ISOLATION RULE was enforced — Step 6 ran after Step 5 but was instructed to read only INSTRUCTION.md + SCAFFOLD.yaml + PRD.md; its report references no test content.

## Step 7: Test-Fix Iteration Loop — 2026-10-02T12:40:00.000Z

All 8 rounds pass 104/104. The sweep is clean and the final results files remain in `workspace/implementation/` per the output contract.

## Summary

- **Iterations run:** 2 (first sweep: 2 deterministic failures in all 8 rounds; second sweep: 8/8 rounds fully green, 104/104 each).

- **Tests deleted:** none.

- **Fixes applied to `test_suite/`:** one.
  - `test_suite/test_09_resources.py` — `TestHearingRoomBufferedIntervalConflict._two_proceedings_one_booking`: added `do_accord=True` to the `add_petitioned_patent(..., do_decide=True)` call (patent `US10000016B`). The helper's `do_decide` branch does not imply accord, so the petition was still `FILED` when `decide_institution` ran, and the PRD-faithful implementation correctly rejected it with 409 `ERR_PETITION_WRONG_STATE` ("decide-institution requires the petition to be NOTICE_ACCORDED"). This was a test-setup bug, not an impl bug: the test skipped a PRD-required state-machine step (FILED → NOTICE_ACCORDED → decide). The asserted rule itself (§3.7 buffered half-open room conflict, `ERR_HEARING_ROOM_CONFLICT`, boundary acceptance at exactly the buffered end) is verbatim-covered and uniquely determined by PRD line 210, so the test stayed intact.

- **Fixes applied to `test_helpers/`:** none needed — the `add_petitioned_patent` helper's flag semantics (independent `do_accord` / `do_decide`) are correct; the single call site was misusing them.

- **Fixes applied to `implementation/`:** none. The implementation was already PRD-faithful on the failing path; both failures were the same upstream setup omission surfacing in two tests of the same class.

Orchestrator verification (independent): all 8 `results.{1..8}.json` files present in workspace/implementation/ (not deleted), each reporting `passed == total == 104, failed == 0`; `find ... -newer results.1.json` across test_suite/, test_helpers/, and implementation/ sources returns EMPTY — the passing sweep postdates every source edit, so the green state is current.

## Step 8: Finalize PRD — 2026-10-02T12:50:00.000Z

All evidence gathered. The investigation confirms a zero-edit outcome.

## Summary on exit

**PRD.md vs PRD_FINALIZED.md line counts and %-delta:** 327 lines each, 0% delta. `diff -q PRD.md PRD_FINALIZED.md` → byte-identical (exit 0, no differences reported).

**Changes:** Zero changes. The single `<step_7_diff>` item is confirmed to be a pure test-fixture bug revealing no PRD silence and no PRD/impl mismatch.

**Evidence log (zero-edit justification):**

1. **Impl path read** — `workspace/implementation/routes/petitions.py`, `decide_institution` (function starting line 206). The state gate at lines 232–235: `if petition["status"] != "NOTICE_ACCORDED": raise_err(ERR_PETITION_WRONG_STATE, "decide-institution requires the petition to be NOTICE_ACCORDED")`.

2. **PRD passage matched** — PRD.md line 176: *"The petition must be in `NOTICE_ACCORDED` (`ERR_PETITION_WRONG_STATE` otherwise)"* — verbatim-pins both the required state and the error for the decide-institution operation. PRD.md line 302 pins `ERR_PETITION_WRONG_STATE` → 409 Conflict. PRD.md line 174 pins the upstream state-machine step (*"A successful accordance moves the petition from `FILED` to `NOTICE_ACCORDED`"*), and line 142 places state-machine preconditions at validation priority 7, matching the impl's inline comment ("State (priority 7)").

3. **Fixture-bug confirmation** — `test_helpers/fixtures.py:270-276` shows `do_accord` and `do_decide` are independent flags in `add_petitioned_patent`; `do_decide` does not imply accord. The fixed call site (`test_suite/test_09_resources.py:37-46`, patent `US10000016B`) now passes `do_accord=True, do_decide=True`. Before the fix, the petition remained `FILED` when `decide_institution` ran, and the PRD-faithful impl correctly rejected it with 409 — the impl was right, the test setup was wrong.

Since the PRD already uniquely determines every behavior the Step 7 diff touched, no edit was warranted and none was made. The NO-NEW-MISMATCH rule is vacuously satisfied (zero edits).

**Output file:** `workspace/PRD_FINALIZED.md` — byte-identical copy of PRD.md.

Orchestrator verification (independent): `diff -q PRD.md PRD_FINALIZED.md` confirms byte-identical; PRD line 176 does contain the NOTICE_ACCORDED gate with ERR_PETITION_WRONG_STATE and the 93-day institution window sentence; line 302 is the §5 table row mapping ERR_PETITION_WRONG_STATE → 409 Conflict.

## Step 9: PRD Completeness Scan — 2026-10-02T13:15:00.000Z

PRD_COMPLETED.md is written. Summary below.

## Output

- **Source:** `workspace/PRD_FINALIZED.md` (327 lines, 53,737 chars)
- **Produced:** `workspace/PRD_COMPLETED.md` (331 lines, 57,896 chars; **+4 lines, +4,159 chars**, 21 diff hunks, no new sections)

**Counts:** 19 ambiguity-pins (inserts), 2 mismatch-revisions.

## Changes (one per hunk)

1. **§2.1** — insert — ambiguity — unrecognized `X-User-Role` value (outside the five roles) is `ERR_FORBIDDEN_ROLE` — implementation/helpers.py:111-116
2. **§2.2** — insert — ambiguity — `api_request_id` is `req_` + 20 random alphanumerics; `api_request_timestamp` is stamped from the logical clock — helpers.py:22-31
3. **§2.2** — insert — ambiguity — framework fallback errors `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) use the same envelope — implementation/app.py:41-55
4. **§2.3** — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_VALIDATION`; honored on all list endpoints — helpers.py:57-90
5. **§2.3** — insert — ambiguity — `created_at` ties broken by insertion sequence — helpers.py:60 (db.py `_seq`)
6. **§2.3** — insert — ambiguity — `total_count` = full filtered count; `has_more` iff `offset+limit < total_count` — helpers.py:82-89
7. **§2.4** — insert — ambiguity — clock endpoint echoes `to_iso8601` verbatim as `current_utc`; malformed → `ERR_VALIDATION`; offset-less values read as UTC — routes/clock.py:19-25, db.py:44-47
8. **§2.5** — insert — ambiguity — `version` starts at 1 at creation — db.py:93
9. **§2.6** — insert — ambiguity — petition-filing body-FK existence order: `patent_id` before `petitioner_id` — routes/petitions.py:49-52
10. **§2.7** — insert — ambiguity — missing/non-integer OCC version field is `ERR_VALIDATION` at priority 5, ahead of the 412 agreement check — routes/petitions.py:104, routes/matters.py:57
11. **§2.10** — insert — ambiguity — a cascade hop leaving stored values unchanged performs no write and no version bump (governs §3.2 score refresh, §3.8 estoppel attach, §3.9 estoppel clear) — calculations.py:131-134, routes/decisions.py:118-120, routes/appeals.py:111-115
12. **§2.11** — revise — mismatch — category-(9) enumeration reordered to the impl's sub-order and marked significant (brief sequence before page caps; amendment quota → substitute-claim matching → amendment volume; interval validity before room conflicts; volume added) — routes/briefs.py:73-82, routes/amendments.py:54-63, routes/hearings.py:135-141
13. **§3.2** — insert — ambiguity — same-status matter PATCH → `ERR_INVALID_STATE`; explicit null `trial_date` clears it; omitted/null `status` leaves status unchanged — routes/matters.py:89-97
14. **§3.4** — revise — ambiguity — the STAYED "20-point credit" is a 20-point *subtraction* from the Fintiv score — calculations.py:23,97
15. **§3.4** — revise — ambiguity — proximity projection base: decision date + 365d at decision time, current logical time + 365d for the provisional variant — calculations.py:90
16. **§3.4** — insert — ambiguity — institution cascade leaves a `FULLY_CANCELLED` patent untouched (no status write, no version increment); denial responses carry `proceeding_id: null` — routes/petitions.py:322-326, 281-294
17. **§3.5** — insert — ambiguity — a brief tendered exactly at its window's closing instant is timely — routes/briefs.py:68
18. **§3.5** — insert — ambiguity — brief authorship is identity-based (`X-User-ID` equals the side's party `id`, whichever of the two party roles was presented); `brief_type` schema check precedes the side-directed ownership check — routes/briefs.py:41-55
19. **§3.6** — insert — ambiguity — auto-granted ROUTINE requests store null `factor_scores`/`garmin_score`; substitute-claim originals need not be distinct, each entry applied to the ledger at grant — routes/discovery.py:40-45, routes/amendments.py:124-127
20. **§3.7** — revise — mismatch — scheduling guard order pinned to §2.11 category order (hearing state + proceeding phase → FWD cutoff → interval validity → room conflict); the old prose mentioned interval and conflict before the phase gate — routes/hearings.py:97-141
21. **§3.9** — insert — ambiguity — remand cascade leaves a patent already `IN_REVIEW` or standing `FULLY_CANCELLED` unchanged — routes/appeals.py:105-109

All 14 known interpretation-choice sites from the task brief are covered (clock echo ✓, timestamp-from-clock ✓, missing OCC → ERR_VALIDATION ✓, patent-before-petitioner ✓, identity-based brief authorship ✓, priority-9 sub-orderings ✓, same-status PATCH + null-clear ✓, change-only cascade version bumps ✓, FULLY_CANCELLED institution skip ✓, extension ALREADY_USED-before-phase — already pinned by §3.8 prose order, verified against proceedings.py:61-66, no edit needed ✓, Fintiv refresh after cancellation cascade — already pinned by §3.2, verified at decisions.py:130 ✓, pagination ERR_VALIDATION ✓).

## IMPL BUG findings (NOT patched into PRD_COMPLETED.md)

- **IMPL BUG:** implementation/routes/patents.py:17-49 — PRD §3.1 "Patents enter the docket with a `patent_number` unique across the system" — `create_patent` performs no uniqueness check; a duplicate `patent_number` is accepted with 201. No error code exists in the §5 catalogue for this, so no conforming rejection behavior could be pinned.
- **IMPL BUG:** implementation/routes/rooms.py:13-26 — PRD §3.1 "Hearing rooms are registered with a `name` unique across the board facility" — `create_room` performs no uniqueness check; duplicate room names are accepted with 201.

## DEAD CHECK findings

None. All 43 catalogued error ids are defined in errors.py and raised at ≥1 site (grep-verified). Reachability notes: `ERR_BRIEF_SEQUENCE_VIOLATION` is reachable only via a second `PO_SUR_REPLY` (PO_RESPONSE/REPLY advance the phase, so their duplicates trip `ERR_INVALID_PHASE` first) — reachable, not dead. `ERR_DECISION_ALREADY_ISSUED` correctly fires before the phase gate on a second same-cycle issuance.

Orchestrator verification (independent): PRD_COMPLETED.md = 331 lines (+4 vs PRD_FINALIZED.md), diff shows 44 changed lines across ~21 hunks; both uniqueness sentences retained verbatim at PRD_COMPLETED.md:154 (patent_number) and :156 (room name); impl grep confirms `create_patent` (patents.py) and `create_room` (rooms.py) perform NO uniqueness check — the two IMPL BUGs are real. Adjudication: uniqueness is a PRD-stated constraint with no dedicated §5 error id; the conforming fix is rejection with `ERR_VALIDATION` (400, the catalog's generic validation error) placed immediately before record creation (after all existing checks) so no currently-passing behavior changes. Proceeding to Step 9b: targeted impl fix + full re-sweep; PRD_COMPLETED.md stays untouched (impl moves toward PRD).

## Step 9b: Impl Fix for Step 9 IMPL BUGs + Re-sweep — 2026-10-02T13:30:00.000Z

All 8 rounds pass 104/104 on the first sweep — no fixture or test edits were needed.

**Implementation edits made:**

1. `workspace/implementation/routes/patents.py` — in `create_patent`, immediately before `store.patents[patent["id"]] = patent` (after all existing role/validation/FK checks), inserted:
```python
    for existing in store.patents.values():
        if existing["patent_number"] == patent_number:
            raise_err(ERR_VALIDATION,
                      "patent_number must be unique across the system")
```
`raise_err`/`ERR_VALIDATION` were already imported in this file; no import change.

2. `workspace/implementation/routes/rooms.py` — added `from errors import raise_err, ERR_VALIDATION` import, and in `create_room`, immediately before `store.rooms[room["id"]] = room`, inserted:
```python
    for existing in store.rooms.values():
        if existing["name"] == name:
            raise_err(ERR_VALIDATION,
                      "name must be unique across the board facility")
```

No other files in `implementation/` touched; nothing under `test_suite/` or `test_helpers/` modified; PRD documents untouched. No new error ids added (reused catalog `ERR_VALIDATION`, HTTP 400), no existing checks reordered.

**Fixture/test edits:** none — no test fixture collides on patent_number or room name.

**Sweep outcome (one 8-round iteration needed):**
- Round 1: 104/104
- Round 2: 104/104
- Round 3: 104/104
- Round 4: 104/104
- Round 5: 104/104
- Round 6: 104/104
- Round 7: 104/104
- Round 8: 104/104

All 8 `results.${i}.json` files remain in place at `workspace/implementation/results.{1..8}.json` as required artifacts.

Orchestrator final verification (independent): all 8 results files report 104/104 failed=0; no .py or PRD file is newer than the sweep; uniqueness checks grep-confirmed at patents.py:51 and rooms.py:29; PRD_COMPLETED.md (57,896 B, 13:02) untouched by 9b; full output tree present — SCAFFOLD.yaml + both design indices at task root, worklog.md, test_helpers/ (9 modules), test_suite/ (22 .py = 21 test files + conftest, 104 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (21 source files + start.sh + results.{1..8}.json)}. PIPELINE COMPLETE.
