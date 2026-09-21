# Shelve / Resume Runbook (Mnemosyne)

## Shelve a Dormant Project
Run when a project goes dormant (e.g., Safe Sponsor AI, Resonance).

```powershell
# 1. Export project memories
mnemosyne export --project <slug> --output "C:\Users\DELL\Documents\Obsidian Vault\99-Meta\shelved\<slug>-$(Get-Date -Format yyyy-MM-dd).json"

# 2. Verify export
mnemosyne stats --project <slug>

# 3. Tag as shelved in project registry (if using one)
#    or simply note in vault: 99-Meta/shelved/<slug>-<date>.md
```

## Resume a Shelved Project
Run when restarting work on a shelved project.

```powershell
# 1. Import shelved memories
mnemosyne import --project <slug> --input "C:\Users\DELL\Documents\Obsidian Vault\99-Meta\shelved\<slug>-<date>.json"

# 2. Verify import
mnemosyne stats --project <slug>

# 3. Spot-check: recall 5 known facts
mnemosyne recall "known failure signature" --project <slug> --limit 5

# 4. Resume normal operation (prefetch will hydrate on next session)
```

## Project Slugs
| Project | Slug | Notes |
|---------|------|-------|
| WSB Alpha System | `wsb-alpha` | Active |
| Burgonomics | `burgonomics` | Active |
| Safe Sponsor AI | `safe-sponsor-ai` | Dormant |
| Resonance | `resonance` | Dormant |

## Automation
- Shelve: manual decision, run before archiving project
- Resume: manual decision, run when restarting project
- Auto-shelve: not implemented (would need activity monitoring)
- Mirror cron (06:00 daily) handles global backup regardless of project status