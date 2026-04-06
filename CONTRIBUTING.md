# Contributing to moltbloat

Thank you for your interest in improving moltbloat! This guide will help you contribute without adding bloat.

## Core Principle: Fight Bloat

Every addition has a cost. Before contributing, ask:

1. **Is this necessary?** Can users achieve the same result with existing tools?
2. **Can it be merged?** Instead of a new skill, can you extend an existing one?
3. **What's the context cost?** More skills = more tokens in the skill menu.

## Guidelines

### Adding Features

**✅ DO:**
- Extend existing skills with subcommands (e.g., `snapshot trends`)
- Add configuration options to `init-config.py` instead of new skills
- Write scripts that other skills can call (reusable components)
- Document the "why" in your PR description

**❌ DON'T:**
- Create single-purpose skills that could be flags on existing skills
- Duplicate functionality (check existing skills first)
- Add dependencies without strong justification
- Ignore the 12-skill soft limit

### Skill Structure

All skills must have:

```yaml
---
name: skill-name
description: Brief, clear description of what it does
level: 1-3 (1=simple, 2=moderate, 3=complex)
---

<Purpose>
What this skill does and why
</Purpose>

<Use_When>
- User says "keyword"
- User wants X
</Use_When>

<Do_Not_Use_When>
- User wants Y (use /other:skill instead)
</Do_Not_Use_When>

<Steps>
1. **Step one**
   Explanation and commands
2. **Step two**
   More details
</Steps>
```

### Testing

Before submitting a PR:

1. Run the validation script:
   ```bash
   bash scripts/validate.sh
   ```

2. Check your bloat footprint:
   ```bash
   # Count lines added
   git diff --stat
   
   # Check total skill count
   ls skills/*/SKILL.md | wc -l
   ```

3. Test any new scripts:
   ```bash
   bash -n scripts/your-script.sh      # Bash syntax
   python3 -m py_compile your-script.py # Python syntax
   ```

### The 12-Skill Rule

We aim to stay at or below 12 skills. If your PR would exceed this:

- **Option 1:** Merge with an existing skill
- **Option 2:** Replace a less-used skill
- **Option 3:** Make a strong case in your PR for why 13 is necessary

Current skills (as of v0.5.0):
1. `audit` — Full ecosystem scan + compatibility
2. `changelog` — Diff against baseline
3. `clean` — Interactive cleanup (with `--dry-run`)
4. `depends` — Dependency graph
5. `doctor` — Self-diagnostic
6. `help` — Command reference
7. `profile` — Profile management
8. `snapshot` — Baseline + trends
9. `team-report` — Team aggregation
10. `token-budget` — Cost analysis
11. `usage` — Usage tracking
12. `why` — Single plugin lookup

### Configuration Over Skills

If your feature needs user customization, add it to `scripts/init-config.py` instead of creating a new skill. Users can edit `~/.moltbloat/config.json` directly.

Example:
```python
# In init-config.py DEFAULT_CONFIG
"your_feature": {
    "enabled": True,
    "threshold": 100
}
```

Then read it in your skill:
```bash
value=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init-config.py" --get your_feature.threshold)
```

### Code Style

- **Bash scripts:** Use `shellcheck`-clean code, quote variables
- **Python:** Follow PEP 8, use type hints where helpful
- **YAML:** Valid frontmatter in all SKILL.md files
- **Documentation:** Clear, concise, actionable

### Pull Request Template

```markdown
## What does this change?
Brief description of the feature/fix.

## Bloat Impact Assessment
- [ ] No new skills added
- [ ] Existing skill extended (which: ___)
- [ ] New skill added (justification: ___)
- [ ] Lines of SKILL.md changed: ___

## Testing
- [ ] `scripts/validate.sh` passes
- [ ] Tested manually by running: ___

## Checklist
- [ ] Follows the 12-skill rule (or justifies exception)
- [ ] Documentation updated (CLAUDE.md, README.md if needed)
- [ ] CHANGELOG.md updated
```

## Questions?

Open an issue for discussion before major changes. We're happy to help you find the least-bloated way to add your feature!
