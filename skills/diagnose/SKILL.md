---
name: diagnose
description: Self-diagnostic for the moltbloat plugin — check moltbloat's installation health, dependencies, permissions, and data integrity. Not a general Claude Code diagnostic; for that, use Claude Code's built-in /doctor command.
level: 1
---

<Purpose>
Run a comprehensive self-diagnostic on the moltbloat installation and its environment. Checks for required dependencies, correct permissions, data file integrity, and common configuration issues. The first troubleshooting step when moltbloat isn't working as expected.
</Purpose>

<Use_When>
- User explicitly runs `/moltbloat:diagnose`
- User says "why isn't moltbloat working" or "check the moltbloat installation"
- A moltbloat command is failing or behaving unexpectedly
- After installing moltbloat for the first time to verify setup
- Before reporting a moltbloat bug — run this first
</Use_When>

<Do_Not_Use_When>
- User runs Claude Code's built-in `/doctor` or says a bare "doctor"/"diagnose" — that targets Claude Code itself, not moltbloat. Do not hijack it.
- User wants to audit their ecosystem — use `/moltbloat:audit`
- User wants general Claude Code troubleshooting — this is specifically for moltbloat
</Do_Not_Use_When>

**Paths:** `~/.claude` below means the active Claude config dir (`$CLAUDE_CONFIG_DIR` when set, else `~/.claude`); `~/.moltbloat` means moltbloat's data dir for that config (`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/paths.py" moltbloat-home`). Bash blocks already resolve both; name the actual directories in the report.

<Steps>

1. **Announce diagnostic**

   > Running moltbloat self-diagnostic... This checks installation health, dependencies, and data integrity.

2. **Check dependencies**

   Verify required tools are available:
   ```bash
   which python3
   python3 --version 2>/dev/null
   which bash
   bash --version 2>/dev/null | head -1
   which claude
   claude --version 2>/dev/null
   which jq 2>/dev/null && echo "jq: $(jq --version 2>/dev/null)" || echo "jq: not installed (optional)"
   ```

   Required:
   - `python3` (3.7+) — for snapshot age checking
   - `bash` — for usage tracking script
   - `claude` CLI — for plugin management

   Optional:
   - `jq` — for better JSON processing (graceful fallback without)

3. **Check moltbloat directory structure**

   ```bash
   # Check if data directory exists and is writable
   test -d "$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/paths.py" moltbloat-home)" && echo "Data directory: exists" || echo "Data directory: missing"
   test -w "$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/paths.py" moltbloat-home)" 2>/dev/null && echo "Data directory: writable" || echo "Data directory: NOT writable"

   # Check for expected files
   ls -la "$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/paths.py" moltbloat-home)/" 2>/dev/null || echo "No data files yet"
   ```

4. **Check data file integrity**

   ```bash
   # Check usage.jsonl validity (if exists)
   if [ -f "$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/paths.py" moltbloat-home)/usage.jsonl" ]; then
     total=$(wc -l < "$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/paths.py" moltbloat-home)/usage.jsonl")
     valid=$(grep -c '"type":"' "$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/paths.py" moltbloat-home)/usage.jsonl" 2>/dev/null || echo 0)
     echo "usage.jsonl: $total lines, ~$valid valid entries"
     
     # Check for JSON parse errors
     head -5 "$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/paths.py" moltbloat-home)/usage.jsonl" | while read line; do
       python3 -c "import json; json.loads('$line')" 2>/dev/null && echo "JSON valid" || echo "JSON INVALID"
     done
   else
     echo "usage.jsonl: not created yet (normal for new installs)"
   fi

   # Check baseline.json validity (if exists)
   if [ -f "$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/paths.py" moltbloat-home)/baseline.json" ]; then
     python3 -c "import json; json.load(open('$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/paths.py" moltbloat-home)/baseline.json'))" 2>/dev/null && echo "baseline.json: valid" || echo "baseline.json: CORRUPT"
   else
     echo "baseline.json: not created yet (normal)"
   fi

   # Check history.log (if exists)
   if [ -f "$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/paths.py" moltbloat-home)/history.log" ]; then
     entries=$(wc -l < "$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/paths.py" moltbloat-home)/history.log")
     echo "history.log: $entries entries"
   else
     echo "history.log: not created yet (normal)"
   fi
   ```

5. **Check hook functionality**

   ```bash
   # Check if hook script exists and is executable
   if [ -f "${CLAUDE_PLUGIN_ROOT}/scripts/track-usage.sh" ]; then
     test -x "${CLAUDE_PLUGIN_ROOT}/scripts/track-usage.sh" && echo "track-usage.sh: executable" || echo "track-usage.sh: not executable"
     bash -n "${CLAUDE_PLUGIN_ROOT}/scripts/track-usage.sh" 2>/dev/null && echo "track-usage.sh: syntax valid" || echo "track-usage.sh: SYNTAX ERRORS"
   else
     echo "track-usage.sh: NOT FOUND"
   fi

   # Check snapshot age script
   if [ -f "${CLAUDE_PLUGIN_ROOT}/scripts/check-snapshot-age.py" ]; then
     python3 -m py_compile "${CLAUDE_PLUGIN_ROOT}/scripts/check-snapshot-age.py" 2>/dev/null && echo "check-snapshot-age.py: syntax valid" || echo "check-snapshot-age.py: SYNTAX ERRORS"
   else
     echo "check-snapshot-age.py: NOT FOUND"
   fi
   ```

6. **Check Claude Code environment**

   ```bash
   # Check if we can read the plugin registry
   if [ -f "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/installed_plugins.json" ]; then
     echo "Plugin registry: readable"
     plugin_count=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/count-installed-plugins.py" 2>/dev/null || echo 0)
     echo "Installed plugins: $plugin_count"
   else
     echo "Plugin registry: NOT FOUND — Claude Code may not be initialized"
   fi

   # Check plugin cache access
   if [ -d "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/cache" ]; then
     cache_size=$(du -sm "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/cache" 2>/dev/null | cut -f1)
     echo "Plugin cache: ${cache_size}MB"
   else
     echo "Plugin cache: not found"
   fi
   ```

7. **Test write operations**

   ```bash
   # Test writing to moltbloat directory
   testfile="$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/paths.py" moltbloat-home)/.diagnose_test_$$"
   if echo "test" > "$testfile" 2>/dev/null; then
     rm "$testfile"
     echo "Write test: PASSED"
   else
     echo "Write test: FAILED: check permissions on "$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/paths.py" moltbloat-home)"/"
   fi
   ```

8. **Check for common issues**

   Scan for known problems:
   - Usage file > 10MB (should be compacted)
   - Baseline older than 90 days
   - Multiple moltbloat installations
   - Permission issues on scripts

   ```bash
   # Check usage file size
   if [ -f "$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/paths.py" moltbloat-home)/usage.jsonl" ]; then
     size=$(stat -f%z "$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/paths.py" moltbloat-home)/usage.jsonl" 2>/dev/null || stat -c%s "$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/paths.py" moltbloat-home)/usage.jsonl" 2>/dev/null || echo 0)
     if [ "$size" -gt 10485760 ]; then
       echo "WARNING: usage.jsonl is >10MB — run '/moltbloat:usage' to compact"
     fi
   fi

   # Check for very old baseline
   if [ -f "$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/paths.py" moltbloat-home)/baseline.json" ]; then
     age_days=$(python3 -c "
import json, datetime, os
try:
    with open('$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/paths.py" moltbloat-home)/baseline.json') as f:
        data = json.load(f)
    ts = data.get('timestamp', '2000-01-01')[:10]
    days = (datetime.date.today() - datetime.date.fromisoformat(ts)).days
    print(days)
except:
    print(0)
" 2>/dev/null)
     if [ "$age_days" -gt 90 ]; then
       echo "WARNING: baseline is ${age_days} days old — run '/moltbloat:snapshot' to update"
     fi
   fi
   ```

9. **Generate diagnostic report**

   ```
   # Moltbloat Diagnostic Report

   ## System Environment
   - Python: <version> <✅/❌>
   - Bash: <version> <✅/❌>
   - Claude CLI: <version> <✅/❌>
   - jq: <version> <✅/optional>

   ## Installation Health
   - Data directory (~/.moltbloat): <✅/❌>
   - Write permissions: <✅/❌>
   - Hook scripts: <✅/❌>
   - Syntax validation: <✅/❌>

   ## Data Files
   - usage.jsonl: <status> (<entries> entries)
   - baseline.json: <status>
   - history.log: <status> (<entries> entries)

   ## Claude Code Integration
   - Plugin registry: <✅/❌>
   - Plugin cache: <accessible/inaccessible>
   - Detected plugins: <count>

   ## Issues Found
   <list any warnings or errors from checks above, or "None — moltbloat appears healthy">

   ## Recommendations
   <specific fixes for any issues found>

   ## Still Having Problems?
   If issues persist after fixing the above:
   1. Check the moltbloat plugin is enabled: `claude plugin list`
   2. Try reinstalling: `claude plugin remove moltbloat && claude plugin install moltbloat`
   3. Check Claude Code logs for hook errors
   ```

10. **Done**

    If issues were found, suggest fixes. If everything passes, reassure the user that moltbloat is properly installed and ready to use.

</Steps>
