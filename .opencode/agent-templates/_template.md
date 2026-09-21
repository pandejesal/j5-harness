---
name: _template
description: TEMPLATE — Copy this file, rename, and customize for new subagents
model: opencode/mimo-v2.5-free
tools:
  read: true
  write: true
  edit: true
  bash: true
  glob: true
  grep: true
  search: true
  symbols: true
  imports: true
  batch_symbols: true
  ast_grep: true
  test_runner: true
  test_impact: true
  build_check: true
  lint: true
  syntax_check: true
  quality_budget: true
  pre_check_batch: true
  secretscan: true
  osv_scan: true
  pkg_audit: true
  schema_drift: true
  diff: true
  diff_summary: true
  repo_map: true
  knowledge_recall: true
  knowledge_add: true
  knowledge_query: true
  doc_extract: true
  doc_scan: true
  web_fetch: true
  web_search: true
  google_ai_search_plus: true
  crawlberg_scrape: true
  crawlberg_crawl: true
  crawlberg_map: true
  html_to_markdown_fetch_url: true
  html_to_markdown_convert: true
  html_to_markdown_extract: true
  xberg_extract: true
  xberg_detect: true
  xberg_formats: true
  tspack_parse: true
  tspack_process: true
  tspack_info: true
  morph_edit: true
  suggest_patch: true
  swarm_apply_patch: true
  extract_code_blocks: true
  summarize_work: true
  phase_complete: true
  update_task_status: true
  declare_scope: true
  declare_council_criteria: true
  record_directive_override: true
  record_implementation_review: true
  record_issue_reproduction: true
  record_issue_publication: true
  record_recurrence_sweep: true
  complete_pr_workflow: true
  prepare_pr_workflow_checkout: true
  prepare_pr_feedback_scope: true
  rebind_pr_feedback_head: true
  run_pr_feedback_stage_a: true
  write_pr_review_artifact: true
  write_pr_review_trigger_eval: true
  write_drift_evidence: true
  write_hallucination_evidence: true
  write_mutation_evidence: true
  write_retro: true
  write_final_council_evidence: true
  write_architecture_supervisor_evidence: true
  submit_council_verdicts: true
  submit_phase_council_verdicts: true
  convene_general_council: true
  consensus_mine: true
  curator_analyze: true
  evidence_check: true
  req_coverage: true
  run_phase_review: true
  check_gate_status: true
  get_qa_gate_profile: true
  set_qa_gates: true
  get_approved_plan: true
  approve_plan_critic: true
  save_plan: true
  spec_write: true
  lint_spec: true
  swarm_command: true
  swarm_memory_recall: true
  swarm_memory_propose: true
  swarm_memory_outcome: true
  skill: true
  skill_apply: true
  skill_generate: true
  skill_improve: true
  skill_inspect: true
  skill_list: true
  skill_regenerate: true
  skill_retire: true
  external_skill_discover: true
  external_skill_inspect: true
  external_skill_list: true
  external_skill_promote: true
  external_skill_reject: true
  external_skill_revoke: true
  task: true
  supervisor_launch: true
  dispatch_lanes: true
  dispatch_lanes_async: true
  collect_lane_results: true
  parse_lane_candidates: true
  retrieve_lane_output: true
  retrieve_summary: true
  context_status: true
  set_reasoning_effort: true
  zen_usage: true
  zen_usage_clear: true
  actionlint_scan: true
  co_change_analyzer: true
  complexity_hotspots: true
  git_blame: true
  gitingest: true
  placeholder_scan: true
  todo_extract: true
  todowrite: true
  question: true
  jules_create: true
  jules_status: true
  jules_message: true
  jules_approve: true
  jules_delete: true
  jules_list: true
  jules_list_sources: true
  jules_get_source: true
  jules_activity: true
  generate_mutants: true
  mutation_test: true
  lean_turbo_plan_lanes: true
  lean_turbo_acquire_locks: true
  lean_turbo_run_phase: true
  lean_turbo_review: true
  lean_turbo_status: true
  lean_turbo_runner_status: true
  epic_decide_phase: true
  epic_plan_waves: true
  epic_record_divergence: true
  repair_gate_evidence: true
  repair_knowledge_receipt_ledger: true
  sbom_generate: true
---

# <Domain> Subagent Template

**Instructions**: Copy this file to `<name>.md`, replace all `<PLACEHOLDERS>`, and customize.

## Domain Configuration

From `domains/domains.config.json` under the `<domain>` domain:

- **Primary Models**: `<model-1>`, `<model-2>`
- **Fallback Models**: `<fallback-1>`, `<fallback-2>`
- **Skills**: `<skill-1>`, `<skill-2>`, `<skill-3>`
- **Tools**: `<tool-1>`, `<tool-2>`, `<tool-3>`
- **Data Sources**: `<source-1>`, `<source-2>`
- **Constraints**: `<constraint-1>`, `<constraint-2>`

## Fallback Ladders

| Role | Ladder |
|------|--------|
| research | `<model-a>` → `<model-b>` |
| coder | `<model-c>` → `<model-d>` |
| planner | `<model-e>` → `<model-f>` |
| bulk | `<model-g>` → `<model-h>` |

## Operating Principles

1. **<Principle 1>**: <Description>
2. **<Principle 2>**: <Description>
3. **<Principle 3>**: <Description>
4. **<Principle 4>**: <Description>
5. **Token Efficiency**: Use skills and MCP servers for domain knowledge.

## Delegation Patterns

- **Simple tasks** (<criteria>): `opencode` with `<model>`
- **Complex <work-type>`: `hermes` with `<model>` for multi-model consensus
- **<Parallel work>`: `kilocode` parallel agents (`-p N`) for <use-case>
- **<Specialized work>`: `prime-agent` via WSL for <reason>
- **<Visual/IDE work>`: `antigravity` bridge for <use-case>

## Skill Usage

Check `tools/skills/ecosystem/` for `<domain>` skills:
- `<domain>/<skill-1>` — <description>
- `<domain>/<skill-2>` — <description>
- `<domain>/<skill-3>` — <description>

## Verification Gates

Standard framework: trust-but-verify, multi-model cross-check, skill pack, scoreboard.
<Domain-specific additions if any>

---

**Remember**: <Domain-specific motto>