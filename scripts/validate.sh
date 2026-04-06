#!/bin/bash
# Validate moltbloat plugin structure and skill files
# Exit codes: 0 = valid, 1 = errors found

set -e

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ERRORS=0

echo "=== Moltbloat Validation ==="
echo ""

# Check required files exist
echo "Checking required files..."
required_files=(
  "package.json"
  ".claude-plugin/plugin.json"
  ".claude-plugin/marketplace.json"
  "README.md"
  "CLAUDE.md"
  "hooks/hooks.json"
  "scripts/track-usage.sh"
  "scripts/check-snapshot-age.py"
)

for file in "${required_files[@]}"; do
  if [[ -f "$PLUGIN_ROOT/$file" ]]; then
    echo "  ✓ $file"
  else
    echo "  ✗ $file MISSING"
    ((ERRORS++))
  fi
done

echo ""
echo "Checking skills..."

# Check each SKILL.md
for skill_file in "$PLUGIN_ROOT"/skills/*/SKILL.md; do
  if [[ ! -f "$skill_file" ]]; then
    continue
  fi
  
  skill_dir=$(basename "$(dirname "$skill_file")")
  
  # Check YAML frontmatter
  if head -5 "$skill_file" | grep -q "^---$"; then
    echo "  ✓ $skill_dir: YAML frontmatter present"
    
    # Check required fields
    if grep -q "^name:" "$skill_file"; then
      echo "    ✓ has 'name'"
    else
      echo "    ✗ missing 'name'"
      ((ERRORS++))
    fi
    
    if grep -q "^description:" "$skill_file"; then
      echo "    ✓ has 'description'"
    else
      echo "    ✗ missing 'description'"
      ((ERRORS++))
    fi
    
    if grep -q "^level:" "$skill_file"; then
      echo "    ✓ has 'level'"
    else
      echo "    ✗ missing 'level'"
      ((ERRORS++))
    fi
  else
    echo "  ✗ $skill_dir: Missing YAML frontmatter"
    ((ERRORS++))
  fi
  
  # Check for required sections
  if grep -q "<Purpose>" "$skill_file"; then
    echo "    ✓ has <Purpose>"
  else
    echo "    ✗ missing <Purpose>"
    ((ERRORS++))
  fi
  
  if grep -q "<Use_When>" "$skill_file"; then
    echo "    ✓ has <Use_When>"
  else
    echo "    ✗ missing <Use_When>"
    ((ERRORS++))
  fi
  
  if grep -q "<Steps>" "$skill_file"; then
    echo "    ✓ has <Steps>"
  else
    echo "    ✗ missing <Steps>"
    ((ERRORS++))
  fi
done

echo ""
echo "Checking scripts..."

# Check bash script syntax
if bash -n "$PLUGIN_ROOT/scripts/track-usage.sh" 2>/dev/null; then
  echo "  ✓ track-usage.sh: syntax valid"
else
  echo "  ✗ track-usage.sh: syntax errors"
  ((ERRORS++))
fi

# Check python script syntax
if python3 -m py_compile "$PLUGIN_ROOT/scripts/check-snapshot-age.py" 2>/dev/null; then
  echo "  ✓ check-snapshot-age.py: syntax valid"
else
  echo "  ✗ check-snapshot-age.py: syntax errors"
  ((ERRORS++))
fi

if python3 -m py_compile "$PLUGIN_ROOT/scripts/init-config.py" 2>/dev/null; then
  echo "  ✓ init-config.py: syntax valid"
else
  echo "  ✗ init-config.py: syntax errors"
  ((ERRORS++))
fi

echo ""
echo "Checking for duplicates..."

# Check for duplicate skill names
skill_names=$(grep -r "^name:" "$PLUGIN_ROOT/skills/*/SKILL.md" 2>/dev/null | sed 's/.*: //')
duplicates=$(echo "$skill_names" | sort | uniq -d)
if [[ -z "$duplicates" ]]; then
  echo "  ✓ No duplicate skill names"
else
  echo "  ✗ Duplicate skill names found:"
  echo "$duplicates" | sed 's/^/    /'
  ((ERRORS++))
fi

echo ""
echo "=== Summary ==="
if [[ $ERRORS -eq 0 ]]; then
  echo "✓ All checks passed"
  exit 0
else
  echo "✗ $ERRORS error(s) found"
  exit 1
fi
