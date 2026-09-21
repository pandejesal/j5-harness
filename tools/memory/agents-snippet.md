## Memory Layer (Source of Truth)

**Truth**: Mnemosyne SQLite (`%MNEMOSYNE_DATA%/memory.db`) = single source of truth
**Cache**: `06-Mnemosyne/MEMORY-MIRROR.md` = read-only snapshot (auto-refreshed daily 06:00)
**Bus**: `04-Prompt-Queues/Ecosystem/InterHarness/` = async handoff (carries `mnemosyne_id` refs)

### Recall Path
- **OpenCode**: `auto-recall` plugin injects first-message memory; explicit `mnemosyne recall` via CLI
- **Hermes**: `hermes_memory_provider` → `prefetch_all` + `on_delegation` + `on_pre_compress` (auto)
- **Kilo**: Reads `MEMORY-MIRROR.md` + `03-Decisions/<project>*.md` + InterHarness mail
- **Prime/Jules/Antigravity**: Vault reads + InterHarness writes (no direct Mnemosyne)

### Write Path
```bash
# Preferred: mnemosyne CLI (project-scoped)
mnemosyne store --project <slug> "concise fact" --kind lesson|convention|decision

# Fallback (degraded mode, LLM unavailable): append to session log
# → 05-Session-Logs/<project>-<date>.md (tagged needs-consolidation:true)
# Next LLM run auto-imports via mnemosyne import --from-session-log
```

### Scoping
- `--project wsb-alpha|burgonomics|safe-sponsor-ai|resonance` (required for writes)
- Global scope = `--global` (cross-project conventions, tool choices)
- Default recall = current project + global; sibling projects require explicit `--cross_project`

### Degraded Mode
When LLM-backed consolidation fails (766× `context_compressor` errors):
1. File-first: append to session log + `03-Decisions/<project>-inbox.md` (status: unconsolidated)
2. Tag `needs-consolidation:true`
3. Next successful LLM run drains queue via `mnemosyne import --from-session-log`