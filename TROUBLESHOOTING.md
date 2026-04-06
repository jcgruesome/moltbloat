# Troubleshooting moltbloat

Common issues and how to fix them.

## Installation Issues

### "claude plugin install moltbloat" fails

**Check:**
```bash
# Verify Claude Code CLI is installed
which claude
claude --version

# Check if marketplace is accessible
claude plugin marketplace list
```

**Fix:**
- Ensure Claude Code is updated: `claude update`
- Try installing from local path:
  ```bash
  git clone https://github.com/jcgruesome/moltbloat.git
  cd moltbloat
  claude plugin marketplace add ./
  claude plugin install moltbloat
  ```

## Runtime Issues

### Commands do nothing / no output

**Check dependencies:**
```bash
bash scripts/check-deps.sh
```

**Expected output:**
```
# Silent success (exit code 0)
```

**If missing dependencies:**
```bash
# macOS
brew install python3 bash

# Ubuntu/Debian
sudo apt-get install python3 bash

# Optional but recommended
brew install jq  # macOS
sudo apt-get install jq  # Ubuntu/Debian
```

### "Permission denied" errors

**Fix:**
```bash
# Ensure ~/.moltbloat is writable
mkdir -p ~/.moltbloat
chmod 755 ~/.moltbloat

# Fix script permissions
chmod +x ~/.claude/plugins/cache/*/moltbloat/*/scripts/*.sh
```

### Usage tracking not working

**Check if hook is firing:**
```bash
# Look for recent entries
ls -la ~/.moltbloat/usage.jsonl
tail ~/.moltbloat/usage.jsonl
```

**Check for errors:**
```bash
cat ~/.moltbloat/errors.log
```

**Common causes:**
1. **Lock file stuck**: 
   ```bash
   rm -f ~/.moltbloat/usage.lock
   ```

2. **Corrupted usage file**:
   ```bash
   # Backup and reset
   mv ~/.moltbloat/usage.jsonl ~/.moltbloat/usage.jsonl.bak
   touch ~/.moltbloat/usage.jsonl
   ```

3. **Hook timeout**: Usage tracking has a 2s timeout. If it fails silently, it won't block your work.

### Audit returns empty or errors

**Check Claude Code installation:**
```bash
ls ~/.claude/plugins/installed_plugins.json
```

**If file doesn't exist:**
```bash
# Claude Code may not be initialized
claude --version  # Ensure it runs
```

**Check plugin cache:**
```bash
ls ~/.claude/plugins/cache/
```

**If empty:**
- No plugins installed (expected for new installs)
- Audit will show "No plugins found"

### "jq: command not found" warnings

This is **optional**. The plugin works without jq, but JSON parsing may be less reliable.

**Install jq:**
```bash
# macOS
brew install jq

# Ubuntu/Debian  
sudo apt-get install jq

# Or use the fallback methods (slightly slower but functional)
```

## Configuration Issues

### Config file corrupted

**Reset to defaults:**
```bash
mv ~/.moltbloat/config.json ~/.moltbloat/config.json.bak
python3 ~/.claude/plugins/cache/*/moltbloat/*/scripts/init-config.py --init
```

### Config migration failed (v0.5.0 → v0.6.0)

**Manual fix:**
```bash
# Backup
mv ~/.moltbloat/config.json ~/.moltbloat/config.json.old

# Regenerate with defaults
python3 ~/.claude/plugins/cache/*/moltbloat/*/scripts/init-config.py --init

# Manually copy your custom values from .old to the new file
```

## Performance Issues

### Audit is slow on large ecosystems

**Expected behavior:**
- < 10 plugins: ~1-2 seconds
- 10-30 plugins: ~3-5 seconds  
- 30+ plugins: ~5-10 seconds

**If much slower:**
```bash
# Check for network-mounted home directory
mount | grep "$HOME"

# Check disk usage
du -sh ~/.claude/plugins/cache/*/*/
```

**Fix:**
- Clean stale cache: `/moltbloat:clean`
- Or manually: `find ~/.claude/plugins/cache -type d -name "*.old" -exec rm -rf {} +`

### Usage file very large

**Check size:**
```bash
ls -lh ~/.moltbloat/usage.jsonl
wc -l ~/.moltbloat/usage.jsonl
```

**Auto-compact:**
```bash
# Config should auto-compact at 5000 lines
# Check setting:
python3 scripts/init-config.py --get thresholds.usage_compact_lines

# Or manually run compact via:
/moltbloat:usage
# Then select compact when prompted
```

## Edge Cases

### Unicode/plugin names with special characters

Some plugins with non-ASCII characters in names may not be detected correctly. This is a known limitation.

**Workaround:**
Check plugins manually:
```bash
ls ~/.claude/plugins/cache/
```

### Windows/WSL

Not officially tested on Windows. May work in WSL with bash.

**If using native Windows:**
- Install Git Bash or WSL
- Or use the Windows Subsystem for Linux

### Multiple Claude Code installations

If you have both stable and preview versions:
```bash
# Check which one moltbloat is using
echo $HOME/.claude

# Ensure consistency between installs
```

## Getting Help

If none of these fix your issue:

1. **Run diagnostics:**
   ```
   /moltbloat:doctor
   ```

2. **Check validation:**
   ```bash
   cd ~/.claude/plugins/cache/*/moltbloat/*/
   bash scripts/validate.sh
   ```

3. **Open an issue** on GitHub with:
   - Output of `/moltbloat:doctor`
   - Claude Code version: `claude --version`
   - OS version
   - Steps to reproduce

## Debug Mode

Enable verbose logging:

```bash
# Add to your shell profile
export MOLTBLOAT_DEBUG=1
```

Then run commands and check:
```bash
cat ~/.moltbloat/errors.log
```
