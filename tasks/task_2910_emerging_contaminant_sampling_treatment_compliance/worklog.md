## Step 1: Create task directory — 2026-09-05T15:22:08.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2910_emerging_contaminant_sampling_treatment_compliance and its workspace/ subdirectory. Index 2910 was pre-assigned by the orchestrator invocation; no scan of ./tasks/ was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-05T17:19:56.000Z

All three scaffold artifacts for task 2910 are complete and lint-clean.

## Files produced

| File | Lines | Top-level key |
|---|---|---|
| `SCAFFOLD.yaml` | 3841 | §1.0–§1.7 only (`scaffold_difficulty_design` / `scaffold_corner_design` verified absent) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1807 | `scaffold_difficulty_design` (19 instances, 9 rule_ids × ≥2) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4632 | `scaffold_corner_design` (90 instances / 70 recipes + 20 stubs) |

## Lint verdict (verbatim, final run)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    61
  §1.1 entities declared:     13
  §1.8 instances scanned:     19
  §1.9 instances scanned:     70
  Calls scanned (§1.8+§1.9):  924

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Domain surface

13 entities (Contaminant, Laboratory, EntryPoint, Sample, LabResult, ComplianceDetermination, PublicNotification, TreatmentEvaluation, PilotTest, ResidualsManifest, CapitalProject, FundingApplication, CostRecoveryClaim), 61 endpoints, 79 error codes, 7 roles, 2 OCC rules, 1 segregation-of-duties rule.

## §1.9 breadth walk

All nine guide sections present: `entities` (11), `state_machines` (16), `calculations` (12), `validations` (23), `endpoints` (5), `errors` (12), `rbac` (3), `complexity_layers` (7), `consistency` (1). Deliberately skipped guide rows (no bulk endpoint, no soft-delete/idempotency/multi-tenancy layers, no eventual/saga consistency, immutability rows subsumed by `common_fields`) are documented in the file's header comment rather than silently omitted.

## Verified invariants beyond the linter

- **All 79 error ids are triggered** somewhere across §1.8 ∪ §1.9 — checked programmatically; the last six (`ERR_SEGREGATION_OF_DUTIES`, both stale-version codes, and the three monitoring-reduction codes) land in the rbac, complexity-layers and errors sections respectively.
- Instance names unique across the union of both design files; every `excluded_because.difficulty_instance` resolves to a real §1.8 `name`.
- Stub schema is `name` + `claim_type` + `grounds` + `excluded_because` with no `test_recipe`, per SKILL.md §1.9.
- No forbidden concurrency vocabulary; every formula-derived assert is a pre-computed literal.

## Notable computed ladders pinned as literals

- GAC pilot: removal 96.30, technology_score **80.14** (round-each-term, explicitly asserted *not* 80.13).
- Base GAC project (capital 680,000,000): debt 41,586,568 → base 72,586,568 → provisional 7.07 → 150 bp → final 73,675,367 → rate_impact **7.18**; uniform 341 / volumetric 340.
- RO-winning branch built specifically to reach `ERR_CONCENTRATE_PERMIT_REQUIRED`: RO score 73.15 vs GAC 54.75, both above the 90.00 removal floor; unfunded ladder 9.90, then EC_GRANT full forgiveness collapses it to **4.39** with a 208-cent uniform increase.
- Posture boundary: 2.00/4.00 = 0.5000 → TRIGGERED (inclusive) with `consecutive_qualifying_quarters` 0, versus 1.99 → 0.4975 → COMPLIANT with streak 1 — the same two numbers straddling one inclusive and one exclusive bound.

## Ordering traps that required construction work

- `ERR_OPEN_VIOLATION_BLOCKS_REDUCTION` is only reachable by issuing an MCL violation and then invalidating the ANALYZED sample: the accepted result becomes SUPERSEDED so posture falls back to COMPLIANT (priority 90 passes) while `open_violation_count` stays 1, since only a rescission decrements it. Rescinding then advances the identical request to the priority-92 history gate, which proves rows 90/91/92 are ordered rather than merged.
- `ERR_LABORATORY_NOT_OWNED` (priority 4) vs `ERR_LABORATORY_ASSIGNMENT_MISMATCH` (priority 9) separated on the same receive call; `ERR_FORBIDDEN_ROLE` (3) shown to beat both the 404 family (5) and the ownership gate (4).
- A SCREENING evaluation with zero pilots must answer `ERR_EVALUATION_STATE_INVALID`, not `ERR_INSUFFICIENT_PILOT_EVIDENCE`, even though the evidence count is also zero.
- The revision bound `revision_count <= 3` is probed at the fourth submission (accepted) and the fifth (refused), so both off-by-one directions fail.

Orchestrator verification: all three files present; `grep -rn "harder than expert"` over the task dir returns nothing, so the difficulty directive did not leak into any scaffold artifact. workspace/ confirmed intact after the subagent.

## Step 3: Copy shared files — 2026-09-05T17:19:56.000Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-05T17:37:00.000Z

PRD generation for task 2910 is complete.

**Output:** `workspace/PRD.md`

- **457 lines**, 26 Markdown headings, last section heading `## 5. Error Code Catalogue`, and the document ends at a real boundary — the final row of the completed 79-row error table (`| ERR_RECOVERY_EXCEEDS_CLAIM | 422 |`). No audit footer in the file.
- Built incrementally (initial `Write` plus seven `cat >> … <<'PRDEOF'` heredoc appends, plus two mechanically generated tables); no single-call truncation.
- Scratch dir was task-scoped: `/tmp/task_2910_prd/`.
- The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

**Structure:** §1 Introduction (3 paragraphs) · §2 with nine subsections (2.1 RBAC, 2.2 verbatim envelope, 2.3 Pagination, 2.4 Identity/Timestamps/Logical Clock, 2.5 Precision & Rounding, 2.6 OCC, 2.7 The Validation Ladder, 2.8 Flat Collections, 2.9 Derived-Field Reconciliation) · §3 with nine domain-derived subsections (regulated universe → field collection/custody → analytical reporting → review/LRAA/posture → determinations/notification → frequency reduction & suspension → treatment evaluation/pilots/selection → residuals manifests/classification/disposal → capital funding/rate impact/cost recovery) · §4 four-column table of all 61 endpoints · §5 two-column table of all 79 errors.

**Hard Contract reports**

```
Contract 1 — Field coverage check (2 passes, strict standalone-backtick match):
- entities[].fields: 160 required, 160 present, 0 missing
- endpoints[].input: 107 required, 107 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
- endpoints[].query_params: 0 required, 0 present, 0 missing
Status: PASS
```

```
Contract 2 — Rule coverage:
- errors[]: 79/79 referenced in §2/§3 narrative (not only in the §5 table); 0 invented ids
- validations[]: all 60 expressed with explicit priority ordering in §2.7 (17 named bands,
  scaffold priority numbers stated, plus the three "reads backwards" precedence notes)
- state_machines[]: 13 machines, 46 distinct state strings, all present as exact UPPERCASE
  tokens or transition pairs; 98/98 enum values present
- calculations[]: 13/13 covered including all 4 variants (compliance/planning LRAA,
  uniform/volumetric bill impact); the two opposed accumulation modes stated explicitly
  (hazard index accumulates unrounded and rounds once; technology score rounds each of five
  weighted terms then sums), and the pinned 7-step rate ladder stated as non-iterative
- concurrency_rules[]: 2/2 with write endpoint, occ_field, mismatch rejection, exact
  error_id and HTTP 412, framed purely in stale-version terms
Status: PASS
```

```
Contract 3 — §3 path purity:
- §3 spans 59,389 characters across nine subsections
- 0 backticked tokens containing a URL path or an HTTP method; 0 plain-text path/method mentions
- HTTP contract confined to §2.6 (OCC write endpoints), §4 and §5
Status: PASS
```

Additional checks: §2.2 verified byte-identical to `section-2.2-response-structure.md`; no pseudocode operators (`>=`, `==`, `+=`, `min()`, `round()`, `AND`/`OR`, etc.) survive outside the fenced JSON; no fuzzy quantifiers (the four hits for "about" are the English preposition, not approximation); all seven role names appear verbatim.

**Two defects found and fixed during verification:** the narrative had invented `ERR_FUNDING_STATE_INVALID` and `ERR_SELF_CERTIFICATION_FORBIDDEN`, which do not exist in the scaffold; both were corrected to the scaffold's real ids (`ERR_APPLICATION_STATE_INVALID`, priority 29, and `ERR_SEGREGATION_OF_DUTIES`, priority 64/HTTP 403).

**One scaffold/spec conflict resolved:** `SCAFFOLD.yaml` writes the role header as `X-Role` in its validation conditions, but `SKILL.md` mandates the exact names `X-User-ID` and `X-User-Role`. The PRD uses `X-User-Role`.

Orchestrator truncation guard (per the known doc-generator failure mode): independently verified PRD.md is 457 lines, that `## 5. Error Code Catalogue` is the last top-level section, and that the tail is a complete `| ERR_RECOVERY_EXCEEDS_CLAIM | 422 |` table row — a real section boundary, not a mid-sentence cut. No regeneration needed. Also grepped PRD.md for "harder than expert" and "scaffold": no hits, so the difficulty directive did not leak into the contract.

## Step 5: Generate unit tests — 2026-09-05T18:53:54.000Z

All 18 test modules import cleanly under `PYTHONPATH=<task root>` (rc=0, `imported 18`), which closes the last verification gap — pyflakes cannot catch a `from test_helpers.api_errors import ERR_X` naming a constant that does not exist, and a direct import of every module proves every symbol resolves.

## Step 5 complete — test infrastructure and test suite generated

Both directories are at the task root: `test_helpers/` and `test_suite/`. Nothing was written under `workspace/` (`ls workspace/` shows only `INSTRUCTION.md`, `PRD.md`, `implementation`), and `workspace/implementation/` was never read or written.

### Per-file line counts (28 files, 9216 lines)

test_helpers: `__init__.py` 16, `api_client.py` 279, `api_errors.py` 192, `assertions.py` 257, `constants.py` 219, `factories.py` 509, `fixtures.py` 571, `test_users.py` 105, `types.py` 241.

test_suite: `conftest.py` 9, `test_01` 214, `test_02` 335, `test_03` 252, `test_04` 250, `test_05` 232, `test_06` 199, `test_07` 220, `test_08` 304, `test_09` 237, `test_10` 439, `test_11` 614, `test_12` 396, `test_13` 919, `test_14` 371, `test_15` 1149, `test_16` 265, `test_17` 326, `test_18` 96.

### Coverage

107 tests over 88 distinct design instances: queue A = all 19 depth instances at 2 tests each (38), queue B = 69 of the 70 live corner instances (entities 11, state_machines 12, calculations 6, validations 17, endpoints 4, errors 12, rbac 3, complexity_layers 4, consistency 1). The 20 stub instances (no `distinguishing_aspect`/`test_recipe`) correctly have no tests. Every test carries exactly one trailing `Design:` tag resolving to a real instance name, and exactly one whitespace-normalizable verbatim `PRD:` citation.

### Verification

- `pyflakes test_suite/ test_helpers/` → rc=0
- `ast.parse` over both globs → `parsed 28 files`
- Live import of all 18 test modules → rc=0
- Design/PRD checker (`/tmp/task_2910_tests/check.py`) → `tests=107 distinct_instances=88`, zero PROBLEM lines
- Coverage diff against both YAMLs → 1 MISSING (the deliberate skip), 20 STUB untested

### PRD-first deviations

One instance skipped outright: `Corner/entities/lab_result_client_supplied_system_values_are_ignored_input` — the design expects 201 with client-supplied derived values silently ignored, but PRD §2.9 makes a body that sets derived values a shape failure. Contradiction, so the gap stays a gap.

Single dropped assertions (test kept, one unsupported claim removed): the nonexistent `GET /contaminants` and `GET /laboratories` list counts (errors §3, rbac §1 — no such endpoints in the PRD or api_client; substituted `list_entry_points`/`list_samples`/`list_treatment_evaluations` counts and GET-by-id re-reads); `EntryPoint.compliance_lraa_ng_per_l` (errors §12, complexity_layers §4 — the string appears zero times in PRD.md; kept the equivalent `max_compliance_ratio` assertions and substituted PRD-derived `compliance_value_ng_per_l` checks); the "ABANDON returns 200 with REJECTED_ALL" step in errors §8 (PRD line 254: the two-completed-pilot floor "applies to both actions, so an evaluation cannot even be abandoned until two pilots have run" — asserted the evaluation is still PILOTING instead); `violation_severity` renamed to the PRD's `violation_type`; and the invalidate-then-201 step in `Corner/validations/resampling_a_target_that_was_never_invalidated_is_rejected`, which contradicts PRD §3.4.

Orchestrator verification: `test_helpers/` and `test_suite/` confirmed present at the task root, and a `find` over the task dir shows no stray copies under `workspace/`.

## Step 6: Generate implementation — 2026-09-05T18:53:54.000Z

Implementation complete.

## What was built

`workspace/implementation/` — Python + Flask, in-memory dicts only, zero seeding at boot, all **61 PRD endpoints** (verified: 61 `@bp.route` decorators vs 61 `- method:` entries in SCAFFOLD.yaml).

| file | lines | file | lines |
|---|---|---|---|
| `app.py` | 61 | `routes/common.py` | 81 |
| `constants.py` | 158 | `routes/registry.py` | 261 |
| `db.py` | 78 | `routes/sampling.py` | 401 |
| `errors.py` | 116 | `routes/determinations.py` | 293 |
| `middleware.py` | 34 | `routes/treatment.py` | 395 |
| `numeric.py` | 54 | `routes/finance.py` | 378 |
| `response.py` | 135 | `services/compliance.py` | 251 |
| `shape.py` | 272 | `services/finance.py` | 134 |
| `start.sh` | 10 | `services/treatment.py` | 144 |
| `requirements.txt` | 1 | `routes/__init__.py`, `services/__init__.py` | 0 |

Total 3257 lines. Every module passes `python3 -m py_compile`.

## Verification

Booted via `start.sh` on port **41879** (killed only by that port / recorded PID — no broad `pkill`), scratch under `/tmp/task_2910_impl/`. Two end-to-end smoke suites, ~110 assertions, all PASS on a fresh boot:

- **Rate ladder matches the scaffold worked example exactly**: debt 41,586,568 → base 72,586,568 → provisional 7.07 → 150 bp → final 73,675,367 → rate 7.18; uniform 341, volumetric rate 68 → volumetric monthly 340. The mode-(c) discriminator (PATCH to 1,993,000,000) reproduces provisional 14.90 / **150 bp** / rate 15.12, confirming the pinned non-looping order.
- **Funding examples**: EC_GRANT 400,000,000 → borrowed 280,000,000, debt 17,123,881, rate 4.69.
- **Recovery waterfall**: buckets 20,000,000 / 280,000,000 / 7,750,000 / 442,250,000 summing exactly to `recovered_cents`.
- **Two accumulation modes both confirmed**: `technology_score` 82.50 (round-each-term-then-sum) and `hazard_index` 0.60 (accumulate-then-round-once).
- Precision emitted at declared width in the raw body (`1.5000`, `0.60`, `0.00`).
- Ladder orderings that invert the naive reading: suspension beats kit defect, prohibited disposal route beats budget overrun, holding time beats lab capacity, RO permit beats funding at BIDDING.
- Cascades and their exact inverses: accept → EP counters → `VIOLATION_PENDING` → mandated evaluation auto-created; invalidate → posture back to COMPLIANT, streak +1; reinstate → posture restored, streak back to 0.
- OCC 412 on both guarded writes; `expected_capital_project_version` supplied to `PATCH /capital-projects/{id}` correctly rejected as `ERR_INVALID_REQUEST`.

## Two spec conflicts resolved

1. **`PATCH /capital-projects/{id}` does not accept `expected_capital_project_version`.** §3.9 prose says it is "required", but §2.6 states the two version fields "appear on exactly the two writes named above and nowhere else, and supplying either of them to any other endpoint is a request-shape failure" — and the scaffold's PATCH `input:` list plus validation priority 11's `applies_to` agree with §2.6. The specific, twice-stated rule wins.
2. **`TRIGGERED → VIOLATION_PENDING` carries only the mandated-evaluation side effect** (no frequency revocation, no auto-deny), per the scaffold state-machine table and §3.4's per-transition paragraphs.

Also chosen deliberately: `settled_at` stays null on claim DISMISS (PRD assigns it only for settlement); `certification_expires_on` accepts date-only or a full instant; `concentrate_permit_ref` is accepted but not persisted (not a CapitalProject field).

Note: Steps 5 and 6 were launched concurrently in a single orchestrator message, so the implementation generator started before `test_suite/` existed and was physically unable to read it.

## Step 7: Run tests and iterate — 2026-09-05T19:23:22.000Z

All 8 rounds pass 107/107. Exiting.

## Summary

**Iterations run:** 3 sweeps (8 rounds each). Round 1: 97/107 with a fully deterministic 10-test failure set (same 10 in all 8 rounds — no load-induced flakiness anywhere in the run).

**Tests deleted:** none outright. Two individual assertions were removed under PRD-silence (STEP 1c partial coverage — the surrounding tests remain):
- `test_18_corner_consistency.py::test_the_selection_response_already_carries_everything_it_created` — dropped `decided["selected_at"]`. COMPUTED-FIELD SILENCE: the token `selected_at` appears nowhere in PRD.md; §3.7 says only that the winner's `selected` becomes true, the evaluation's `selected_technology` becomes the winner's technology and the evaluation moves `PILOTING → SELECTED`. Drove from design instance Corner/consistency/the_selection_response_already_carries_everything_it_created.
- `test_14_corner_endpoints.py::test_a_membrane_project_reaches_bidding_only_once_its_permit_is_named` — dropped `assert_equals(bidding, "concentrate_permit_ref", ...)`. PERSISTENCE SILENCE: PRD names `concentrate_permit_ref` only as an optional *request* field and as the BIDDING precondition; unlike the shipping paragraph ("the route, `carrier_ref` and cost are stored") it never says the reference is stored or echoed on the project.

**Fixes applied to `test_helpers/`:**
- `factories.py::project_patch_payload` — stopped sending `expected_capital_project_version` on `PATCH /capital-projects/{id}` (5 call sites in test_01/02/14/16 updated). This was the single upstream fixture bug behind 4 of the 10 failures (all `ERR_INVALID_REQUEST: unrecognised field expected_capital_project_version`).

**Fixes applied to `test_suite/`:**
- `test_02_combinatorial_formulas.py::_three_member_mixture` / `test_a_member_without_an_accepted_result_contributes_no_term` — rebuilt the scenario. The old one accepted 2 of a 3-compound panel, which leaves the sample in `RECEIVED`, and PRD §3.4 excludes *all* results of a non-`ANALYZED` sample from the average input set, so the PRD-faithful answer was `max_compliance_ratio` 0.0 / `hazard_index` 0.0, not 0.1675 / 0.67. The panel is now the two measured members (sample reaches `ANALYZED`) with the third hazard member registered but never sampled, which is exactly the PRD sentence the test cites ("a member contaminant with no accepted result is absent from the sum entirely").
- `test_02` `test_the_top_surcharge_tier_...` — `provisional_rate_impact_pct` 16.14 → 16.13. 165544780×100/1026000000 = 16.13497, which rounds half-up to 16.13; the tier assertion (400 bp) and every other ladder figure were already correct.
- `test_09_compensating_invariants.py` — leachate assertion `places=1` → default `places=2`. The test itself supplies 49.99, and PRD §2.4 carries ng/L concentrations to two decimals; `places=1` made the helper reject its own input.
- `test_15_corner_errors.py` — removed `health_advisory_ng_per_l=8.00` from the duplicate-code payload. That field exists nowhere in PRD.md and at no other call site, so shape-band rejection correctly pre-empted `ERR_DUPLICATE_CONTAMINANT_CODE`.
- `test_17_corner_complexity_layers.py` — expected verdict `NO_VIOLATION` → `MONITORING_VIOLATION` (docstring updated too). PRD §3.5 walks monitoring violation *first*: `quarters_used` 1 < 4, `monitoring_status` `QUARTERLY`, no individual or mixture exceedance at 3.00 against a 4.00 MCL. The implementation was right.

**Fixes applied to `implementation/`:** none. No implementation defect was found; all 10 failures were test-artifact bugs.

**Final round-by-round:** 107/107 in every one of rounds 1-8 (0 failed, 0 errors, 0 skipped).

**One PRD issue worth flagging to the orchestrator (I did not edit PRD.md):** §3.9 line 276 says a project cost adjustment has "`expected_capital_project_version` required for concurrency control", but §2.6 line 104 says "No other endpoint in this system accepts a version field… supplying either of them to any other endpoint is a request-shape failure", and the validation ladder (line 122) scopes `ERR_STALE_CAPITAL_PROJECT_VERSION` to "funding-application creation" only. I resolved in favour of the two-vote majority reading (§2.6 + ladder), which is what the implementation does, but line 276's clause should probably be struck so candidates can't be split by it.

Orchestrator verification (per the known "clean sweep with no artifacts" failure mode): independently re-read all eight `workspace/implementation/results.{1..8}.json` — every file present, all timestamped 19:18, each reporting passed=107 total=107 failed=0 errors=0. The clean sweep is real.

Orchestrator note on Step 8 scope: Step 7 applied 0 implementation fixes, so the Step 8 skip condition is *nearly* met — but it is not met, because Step 7 did make test_suite/ fixes, test_helpers/ fixes and two assertion removals. The skip condition requires all four counts to be zero. Step 8 therefore runs, with the caveat that a byte-identical PRD_FINALIZED.md is a legitimate outcome here: with no implementation fix, several diff items are pure fixture bugs that reveal no PRD silence. The one item that plainly does reveal a real PRD defect is the §3.9-vs-§2.6 `expected_capital_project_version` contradiction above.

## Step 8: Finalize PRD — 2026-09-05T19:28:38.000Z

Done. `PRD_FINALIZED.md` written with three targeted edits, all traceable to `<step_7_diff>` items.

## Size
- `PRD.md` 457 lines / 97,522 bytes → `PRD_FINALIZED.md` 457 lines / 98,442 bytes.
- Line-count delta 0.0% (the file is one paragraph per line); byte delta +920 (+0.94%). 3 of 457 lines changed.

## Changes
- **§2.7 ladder, band 6 (Request shape)** — *revise* — added "a body field the endpoint does not declare" to the shape-failure list, plus one sentence pinning that every write reads its body against a closed set of declared field names (exactly the fields the PRD introduces for that endpoint) and that this closed-set check sits in the shape band, pre-empting business checks — `implementation/shape.py:80-92` (`Body.__init__` strict allow-list), ordering witnessed at `routes/registry.py:44-73` (allow-list rejection precedes `ERR_DUPLICATE_CONTAMINANT_CODE`).
- **§3.9 cost adjustment (was line 276)** — *revise* — struck "`expected_capital_project_version` required for concurrency control"; the three cost fields are now stated as the only fields the write accepts, with the version token explicitly a shape failure per §2.6 — `implementation/routes/finance.py:52`.
- **§3.9 construction progression (was line 290)** — *insert* — one clause stating that `concentrate_permit_ref` is read only to satisfy the BIDDING precondition and is neither stored nor echoed on the project, contrasted with §3.8's manifest shipment which does store its route and `carrier_ref` — `implementation/routes/finance.py:75-104` and `services/treatment.py:99-136` (project field set has no such key).

## Per-edit pre-edit search log

**Edit 1 — closed body field set**
(a) Subject: rejection of body field names an endpoint does not declare, and its ladder position.
(b) Paths enumerated: `shape.py:80-92` (`Body`), then every `Body(` construction site — `routes/registry.py:34,44,99,142,200,222,248`; `routes/sampling.py:36,131,149,183,216,250,351`; `routes/treatment.py:37,82,129,224,238,277,331,347,382`; `routes/finance.py:52,75,111,169,217,241,316,331`; `routes/determinations.py:63,122,171,216,245,270`. Counted 37 sites against the 37 write endpoints in §4's table — every write, including `POST /_clock/set_current_utc` (`Body(["current_utc"])`) and the three no-body writes (`issue`, `start`, `reinstate`, all `Body([])`), uses an allow-list. Verified each allow-list equals the PRD-introduced field set for that endpoint (spot-read sample creation, lab-result creation, notification submit/review/certify, pilot create/complete, manifest create/classify/ship/void, claim create/file/resolve, contaminant/lab/entry-point registration). Also read `routes/common.py`/`shape.py:256-272` to confirm **list** endpoints only read named query params and silently ignore unknown ones.
(c) Adjustment: scoped the new sentence to *body* fields and to *write* endpoints only, so it makes no claim about unknown query parameters on GET/list endpoints (impl ignores those). Kept "the fields this document introduces for that endpoint" rather than enumerating, and said the check "pre-empts every business check below it" rather than fixing an order *within* the shape band (impl scans unknown keys before per-field reads, but both yield the same `error_id` and status, so pinning it would over-determine).

**Edit 2 — PATCH concurrency token**
(a) Subject: `expected_capital_project_version` and which writes take a version field.
(b) Paths enumerated: `routes/finance.py:48-68` (PATCH — three-field allow-list, no version read, no 412 path), `routes/finance.py:107-125` (funding-application creation — version required, `ERR_STALE_CAPITAL_PROJECT_VERSION`), `routes/determinations.py:63-73` (the parallel `expected_entry_point_version` guard), plus a whole-tree grep for both token names (only those three sites). Cross-checked the two other PRD statements on the subject: §2.6 line 104 and ladder item 11.
(b/c) Adjustment: worded as "this write accepts no concurrency token" and pointed at §2.6 instead of restating the ladder, so §2.6 line 104 and ladder item 11 remain the single source of truth and the determination-side guard (`expected_entry_point_version`, still required) is untouched.

**Edit 3 — `concentrate_permit_ref` non-persistence**
(a) Subject: persistence/echo of `concentrate_permit_ref`.
(b) Paths enumerated: whole-tree grep for `concentrate_permit_ref` → only `routes/finance.py:75` (allow-list) and `:77` (read), used solely in the `ERR_CONCENTRATE_PERMIT_REQUIRED` gate at `:89-93`; `services/treatment.py:99-136` (`create_capital_project` — full project field list, no permit-ref key); `db.py:71-72` (`public()` passes through every non-underscore key, so absence of the field is genuine, not a projection filter); `routes/finance.py:52` (PATCH cannot introduce it either). Also confirmed `concentrate_permit_required` (the boolean the gate reads) *is* seeded and stored — the edit must not blur the two.
(c) Adjustment: named only the *reference* as unstored and left `concentrate_permit_required` untouched; did not extend the clause to the impl's blank/whitespace-ref handling (`permit_ref.strip() == ""` treated as absent), since no Step 7 item exercised it and pinning it would go beyond the diff.

## Items that correctly produced no edit
- `selected_at` (test_18) — the token exists nowhere in `implementation/`; §3.7's selection sentence already enumerates exactly what changes (`selected`, `selected_technology`, `PILOTING → SELECTED`), so PRD silence already yields the impl's behavior.
- `_three_member_mixture` / non-`ANALYZED` exclusion (test_02) — `services/compliance.py:32-46,60-67` matches §3.4 verbatim; pure test-scenario bug.
- Surcharge tier 16.13 (test_02) — `services/finance.py:76-79` + `numeric.py:19-23` (ROUND_HALF_UP) match §3.9 steps 4-5; test arithmetic error.
- Leachate `places=2` (test_09) — `routes/treatment.py:331-332` quantizes to two places, already fixed by §2.5; test-helper bug.
- `MONITORING_VIOLATION` verdict (test_17) — `routes/determinations.py:29-43` walks the four branches in §3.5's stated order; test expectation was wrong.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` reports exactly 3 changed lines (6 diff lines), 97,522 → 98,442 bytes. Not byte-identical, and the §3.9/§2.6 `expected_capital_project_version` contradiction Step 7 flagged is among the three resolved sites.

## Step 9: Complete PRD — 2026-09-05T19:54:58.000Z

Step 9 was deliberately run as **three sequential, module-partitioned passes over one shared `PRD_COMPLETED.md`** rather than a single scan, because a single-pass Step 9 on a document this size tends to no-op (producing a byte-identical file). Pass 1 performed the `cp`; passes 2 and 3 were explicitly forbidden from re-copying so earlier edits survived. Slices were disjoint: pass 1 = core infra (`app/middleware/shape/response/errors/numeric/db/constants/routes/common`) + `routes/registry.py`; pass 2 = `routes/sampling.py`, `routes/determinations.py`, `services/compliance.py`; pass 3 = `routes/treatment.py`, `routes/finance.py`, `services/treatment.py`, `services/finance.py`.

**Cumulative result: `PRD_FINALIZED.md` 98,442 bytes → `PRD_COMPLETED.md` 112,962 bytes (+14,520 bytes, +14.7%), 457 lines throughout (every edit is an in-paragraph insert or revision; no new sections, no new paragraphs). 57 of 457 lines changed. Totals across the three passes: 51 ambiguity-pins, 15 mismatch-revisions.**

### Pass 1 — core infrastructure + registry (12 ambiguity-pins, 2 mismatch-revisions)

Performed the `cp` of `PRD_FINALIZED.md` → `PRD_COMPLETED.md`. 98,442 → 102,318 bytes.

- §2.2 (`api_request_id`) — insert — ambiguity — id is `req_` plus exactly twenty characters from uppercase letters and digits — `response.py:17,20`
- §2.2 (`api_request_timestamp`) — insert — ambiguity — this one instant comes from the real wall clock, not the logical clock — `response.py:98`
- §2.3 ¶1 — insert — ambiguity — non-integer/non-numeric `limit`/`offset` yield `ERR_PAGINATION_OUT_OF_RANGE` (not a shape failure); empty-string params take defaults; undeclared query params ignored — `shape.py:239-252`
- §2.3 ¶2 — insert — ambiguity — rows sharing a `created_at` (common under the logical clock) order by internal creation sequence, which appears in no response field — `db.py:77,72`
- §2.4 ¶1 — insert — ambiguity — `created_at`/`updated_at` read the logical clock, never the wall clock — `db.py:56-58,45-47`
- §2.4 ¶2 — insert — ambiguity — the clock echo's `data` carries only `current_utc` (no `id`/`created_at`/`version`), normalised to UTC and three fractional digits — `routes/registry.py:32-37`
- §2.4 ¶3 — revise — mismatch — PRD claimed accepted datetimes are "exactly three fractional digits"; impl accepts 0–6 fractional digits, lower-case `t`/`z` and `±HH:MM` offsets normalised to UTC, while output is always three digits — `shape.py:14-42`, `response.py:24-37`
- §2.5 ¶1 — insert — ambiguity — a JSON number with a zero fractional part satisfies an integer field; any non-zero fraction is a shape failure — `shape.py:152-157`
- §2.7 item 6 — insert — ambiguity — absent/empty body reads as `{}`; malformed JSON or a non-object body is a shape failure; a present `null` is a shape failure and never falls back to a default, with contaminant `hbwc_ng_per_l` the sole exception — `shape.py:67-92,101-106`, `routes/registry.py:68`
- §2.8 ¶1 — insert — ambiguity — unrouted path → `ERR_NOT_FOUND` 404, undeclared method → `ERR_METHOD_NOT_ALLOWED` 405 (both outside the §5 catalogue), trailing slash insignificant — `app.py:22,37-42`, `errors.py:84-85`
- §2.8 ¶3 — insert — ambiguity — FK list filters resolve in the order §2.8 lists them before equality filters; empty-string filters narrow nothing; boolean filters accept case-insensitive `true`/`false` and ignore anything else — `routes/common.py:42-68`, `shape.py:256-272`
- §3.1 ¶1 — insert — ambiguity — the three uniqueness constraints compare exact, case-sensitive strings — `routes/registry.py:71-73,115-117,146-148`
- §3.1 (laboratory) — insert — ambiguity — `certification_expires_on` accepts a bare `YYYY-MM-DD` (read as midnight UTC) as well as a full instant, and is always echoed as an instant; verified this is the only date-accepting field in the implementation — `routes/registry.py:113`, `shape.py:45-56`
- §3.1 (entry point) — revise — mismatch — initial `max_compliance_ratio` is `0.0000` and `hazard_index` is `0.00` (PRD said `0.0` for both), each at its declared §2.5 precision — `routes/registry.py:27-28,165-166`, `services/compliance.py:79,108`
- §3.6 ¶3 — insert — ambiguity — the reduction `justification`, the decision `decision_note` and the suspend/resume `reason` are validated then discarded; the entry point has no field for them — `routes/registry.py:202,224,250`

Verified-no-change highlights: auth ladder order and the four laboratory-identity endpoints; full `ERR_*` → HTTP status table matches §5 one-for-one; rate-base arithmetic (ceil population/2.5, ×60, ×950); §3.6 reduction/suspension state checks and their fixed order; entry-point list filter set and `pagination()`-before-filters ordering; `total_count` post-filter and `has_more` as `offset + len(page) < total_count`; default clock `2026-08-01T00:00:00.000Z`; `version` starting at 1 and incrementing per mutation.

### Pass 2 — sampling, determinations, compliance (14 ambiguity-pins, 5 mismatch-revisions)

Did not re-copy; edited in place. 102,318 → 107,381 bytes. Pass 1's 14 edits verified intact.

- §3.5 ¶1 — revise — mismatch — `period_end` is a `YYYYQn` monitoring-period label, not an ISO instant, and it does not bound the averaging window — `routes/determinations.py:66`, `services/compliance.py:32-46`
- §3.4 (max_compliance_ratio) — revise — mismatch — empty-window value is `0.0000`, not `0.0` — `services/compliance.py:15,83`
- §3.4 (posture transitions) — revise — mismatch — de-escalation resets to `0.0000`/`0.00` at each field's own precision, and `VIOLATION_PENDING → COMPLIANT` is also reachable with results still accepted (ratio < 0.5, hazard ≤ 1.00) — `services/compliance.py:83,107,147-154`
- §3.4 (uniqueness) — revise — mismatch — softened the "needs no tie-break inside a period" claim, which reinstatement falsifies — `services/compliance.py:42-43`
- §3.4 (LRAA window) — insert — ambiguity — per-period tie-break: when reinstatement leaves two accepted results in one period, the earliest-created wins — `services/compliance.py:42-43`
- §3.5 (notification submit) — insert — ambiguity — `delivery_methods` is a closed five-value enum (unrecognised channel = shape failure, not insufficiency) while `content_elements` accepts any string; duplicates in either array are a shape failure; empty arrays pass shape and fail the content/delivery gate; `drafted_by_user_id` is overwritten on resubmission, moving the segregation-of-duties bar — `routes/determinations.py:216-236`
- §3.2 ¶1 — insert — ambiguity — the seven custody/receipt fields a new sample begins null on — `routes/sampling.py:92-99`
- §3.2 (receipt) — insert — ambiguity — `field_blank_result_ng_per_l` must be at least zero — `routes/sampling.py:151`
- §3.2 (receipt) — insert — ambiguity — either receipt branch advances the entry point's `updated_at`/`version`, including a no-op reset of an already-zero streak — `routes/sampling.py:163-174`
- §3.2 (streak) — insert — ambiguity — the invalidation counter is neither capped at 3 nor cleared by the suspension it caused — `services/compliance.py:229-235`
- §3.4 ¶1 (review) — insert — ambiguity — `review_note` is stored on acceptance too; a `reject_reason_code` sent with `ACCEPT` passes shape and is discarded; rejection does not advance the entry point's `version` — `routes/sampling.py:356,367,390`
- §3.4 (reinstatement) — insert — ambiguity — results the invalidation drove `SUBMITTED → REJECTED` are **not** restored; only `SUPERSEDED` ones return — `routes/sampling.py:230-235`
- §3.5 (issue) — insert — ambiguity — a non-`MCL_VIOLATION` issuance leaves the entry point wholly untouched, so its `version` does not advance — `routes/determinations.py:133-135`
- §3.5 (issue) — insert — ambiguity — the six notification fields that begin null, and that the response body is the determination, not the notification — `routes/determinations.py:154-164`
- §3.5 (rescind) — insert — ambiguity — `rescind_reason` may not be empty or whitespace-only — `routes/determinations.py:172`
- §3.5 (rescind) — insert — ambiguity — `open_violation_count` is recomputed from `ISSUED` + `MCL_VIOLATION` evidence, and only that case touches the entry point — `routes/determinations.py:181-184`, `services/compliance.py:136-143`
- §3.5 (verdict) — insert — ambiguity — the monitoring-violation branch reads the literal `QUARTERLY` status, so `INITIAL`/`REDUCTION_PENDING`/`SUSPENDED` also produce none — `routes/determinations.py:33-34`
- §3.5 (notification review) — insert — ambiguity — a whitespace-only `review_note` counts as missing, and the shape failure pre-empts the `SUBMITTED` state check — `routes/determinations.py:248-252`
- §3.6 ¶1 — insert — ambiguity — the qualifying-quarter walk, unlike §3.4's window, does not require the parent sample to have reached `ANALYZED` — `services/compliance.py:111-114`
- §2.8 (filter list) — insert — ambiguity — the sample list's `panel_contaminant_ids` filter takes one contaminant id, resolves as an FK (`ERR_CONTAMINANT_NOT_FOUND`), and matches panel membership — `routes/sampling.py:113-116`
- §2.7 item 4 — insert — ambiguity — the laboratory-identity check is a gate only; neither lab-scoped list narrows rows to the caller's own laboratory — `routes/sampling.py:107,331`

Pass 2 deliberately deferred two things: the document-wide "exactly two decimal places" phrasing (handed to pass 3, since a slice-local edit would have left the document internally inconsistent), and `accepted_result_count` counting accepted results whose sample has not reached `ANALYZED` (§3.4's "rises by one" already pins it).

### Pass 3 — treatment, finance, plus the cross-slice decimal-width fix (25 ambiguity-pins, 8 mismatch-revisions)

Did not re-copy; edited in place with 24 in-paragraph Edits. 107,381 → 112,962 bytes. Both prior passes verified intact.

**Cross-slice resolution of "exactly two decimal places":** verified against `shape.py:166-190` (`Body.decimal` rejects only `decimal_places(number) > places`, accepts a bare `int` or a shorter fraction, then quantizes to the declared width) and `response.py:40-45` (Decimals emitted at stored scale) — impl accepts **at most** the declared width and always emits exactly it. Resolved document-wide by (a) extending the §2.5 sentence that already said "more than two is refused" with the affirmative half (fewer places, or a whole number with no decimal point, is accepted and stored/emitted at full declared width: `12` → `12.00`), plus one closing sentence making every §3 width an input ceiling and an exact output width; and (b) replacing `exactly two decimal places` → `at most two decimal places` at all six remaining sites (§3.1 contaminant concentrations, §3.3 `reported_ng_per_l`/`detection_limit_ng_per_l`, §3.7 `ebct_min` + the three burden scores, §3.7 `spent_media_kg`, §3.8 `mass_kg`, §3.9 `allocation_pct`). `grep -c "exactly two decimal places"` is now 0.

- §2.5 — insert — ambiguity — fewer-than-declared / integer decimals accepted, emitted at full width; §3 widths are input ceilings — `shape.py:182`, `response.py:40`
- §2.5/§3.1/§3.3/§3.7/§3.8/§3.9 — revise — mismatch — the 6 "exactly two decimal places" phrasings → "at most" (cross-slice assignment above) — `shape.py:182`
- §2.6 — revise — mismatch — "requested amount is sized against the project's remaining local share" was a constraint impl never applies; now says only the later award is capped against the cost basis — `routes/finance.py:120`
- §3.7 — insert — ambiguity — evaluation created with `decision_note` null; cascade-created mandated evaluation takes identical defaults (SCREENING, budget 250000, spent 0, nulls) — `services/compliance.py:166`, `routes/treatment.py:46`
- §3.7 — insert — ambiguity — an entry point may carry any number of evaluations, at any monitoring status or posture — `routes/treatment.py:35`
- §3.7 — insert — ambiguity — pilot registration requires the evaluation in `SCREENING`/`PILOTING`, else `ERR_EVALUATION_STATE_INVALID` (PRD was wholly silent) — `routes/treatment.py:159`
- §3.7 — insert — ambiguity — two pilots of the same technology permitted under one evaluation — `routes/treatment.py:145`
- §3.7 — insert — ambiguity — pilot created with `influent_ng_per_l`, `effluent_ng_per_l`, `bed_volumes_treated`, `spent_media_kg`, `removal_pct`, `lifecycle_cost_score`, `technology_score` null — `routes/treatment.py:181`
- §3.7 — insert — ambiguity — no upper time bound on start (a pilot past `window_end_at` may still start); start accepts no body fields — `routes/treatment.py:224`
- §3.7 — insert — ambiguity — completion bounds: influent/effluent at least zero with ≤2 places, `bed_volumes_treated` an integer ≥ 0 — `routes/treatment.py:241`
- §3.7 — insert — ambiguity — influent of 0.00 is never divided by; `removal_pct` is 0.00 (below the selection floor) — `services/treatment.py:26`
- §3.7 — insert — ambiguity — `ABANDON` note must be non-blank and, being a shape failure, is reported ahead of the state/evidence checks; note persisted under both actions, null on an omitting `SELECT` — `routes/treatment.py:85`
- §3.7 — insert — ambiguity — final ranking tie-break is the internal creation sequence of §2.3 — `services/treatment.py:88`
- §3.7 — insert — ambiguity — losing pilots untouched; `treatment_status` stays `PILOT` on `SELECT` — `routes/treatment.py:114`
- §3.7 — insert — ambiguity — project carries its own `selected_technology` and starts with `recovered_cents` zero — `services/treatment.py:106`
- §3.8 — insert — ambiguity — manifest also created with `carrier_ref`, `classified_by_user_id`, `void_reason_code` null — `routes/treatment.py:300`
- §3.8 — insert — ambiguity — `carrier_ref` mandatory, neither empty nor whitespace-only — `routes/treatment.py:349`
- §3.8 — insert — ambiguity — `void_reason_code` persisted on the voided manifest — `routes/treatment.py:386`
- §3.9 — insert — ambiguity — `capital_cost_cents`/`annual_om_cost_cents` integers ≥ 0; an all-omitted PATCH is a no-op that still recomputes and bumps `version` — `routes/finance.py:53`
- §3.9 — insert — ambiguity — `local_share_cents` never floored at zero; a reduced cost basis carries a negative share through the ladder — `services/finance.py:59`
- §3.9 — insert — ambiguity — blank/whitespace `concentrate_permit_ref` counts as not supplied — `routes/finance.py:90`
- §3.9 — revise — mismatch — "Creating the application changes `funding_status` to `APPLIED`" was a false universal; it re-derives, staying `AWARDED` when another application already is — `services/finance.py:23`
- §3.9 — insert — ambiguity — an application may be lodged at any construction stage, including `IN_SERVICE`; only withdrawal is stage-restricted — `routes/finance.py:107`
- §3.9 — insert — ambiguity — `awarded_cents` ≥ 0, and a zero award still reaches `AWARDED`, satisfying `ERR_FUNDING_NOT_SECURED` — `routes/finance.py:171`
- §3.9 — insert — ambiguity — denial note non-blank, `decided_by_user_id` recorded on denial; an award's note is optional and stored null — `routes/finance.py:175`
- §3.9 — insert — ambiguity — `withdraw_reason` non-blank and persisted; only `awarded_cents`/`forgiven_cents` are cleared, `forgiveness_pct`/`decided_by_user_id`/`decision_note` survive — `routes/finance.py:218`
- §3.9 — insert — ambiguity — claim created with `claimed_cents`, `recovered_cents`, four buckets, `filed_at`, `settled_at`, `resolution_note` null — `routes/finance.py:280`
- §3.9 — insert — ambiguity — `recovered_cents` ≥ 0; settle stores the optional note; capital-bucket ceiling read as zero when `local_share_cents` is negative — `services/finance.py:124`
- §3.9 — insert — ambiguity — dismissal leaves `settled_at` null, and from `INVESTIGATING` also `claimed_cents`/`filed_at` null — `routes/finance.py:340`

Pass 3 deliberately did not pin ladder division-by-zero: it is unreachable because `population_served ≥ 1` forces `served_account_count ≥ 1`, `annual_billed_kgal ≥ 60` and `baseline_annual_revenue_cents ≥ 57000` (`routes/registry.py:146-154`).

### Orchestrator verification

`cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (the tell that a Step 9 scan silently no-opped): 112,962 vs 98,442 bytes, 57 changed lines / 114 diff lines. The file ends at a real boundary — the final `| ERR_RECOVERY_EXCEEDS_CLAIM | 422 |` row of the §5 catalogue. Only `./worklog.md` exists in the task tree; no stray copies drifted into `workspace/`.

No re-sweep was run after Steps 8 and 9 because neither step touches `test_suite/`, `test_helpers/` or `implementation/` — both edit PRD documents only. The passing artifact of record remains the Step 7 sweep: `workspace/implementation/results.{1..8}.json`, all eight at 107/107.

**Pipeline complete.**

