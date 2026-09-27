#!/usr/bin/env python3
"""Apply one reviewed change to an instruction file or agent definition.

Used by /moltbloat:clean, one confirmed change at a time. Three actions:

  rewrite FILE                  apply instruction-lint's structural rewrite
                                (import markers, exact duplicate sections)
  drop-section FILE --line N --heading TEXT
                                remove the section starting at line N (with
                                its subsections), e.g. one side of a drifted
                                duplicate the user chose to drop
  pin-model FILE --model M      set `model:` in an agent's frontmatter

Every action:
  --dry-run            print the unified diff and the file's sha256; write nothing
  --expect-sha256 H    refuse (exit 3) if the file changed since it was reviewed
  --backup-root DIR    backup location (default ~/.moltbloat/backups/<UTC time>/)

Before writing it copies the file into the backup root (mirroring its
absolute path) and then replaces the file atomically. It refuses files under
~/.claude/plugins (plugin-owned: changes would be lost on update and belong
upstream) and non-Markdown files.

Exit codes: 0 applied (or dry run), 1 missing file, 2 bad arguments,
3 refused (changed since review, heading mismatch, unsafe rewrite, plugin file).
"""
import difflib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
PIN_MODELS = ("haiku", "sonnet", "opus", "fable", "inherit")


class Refused(Exception):
    pass


def _lint():
    spec = importlib.util.spec_from_file_location("instruction_lint", os.path.join(HERE, "instruction-lint.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_target(path, home):
    if not path.endswith(".md"):
        raise Refused(f"{path} is not a Markdown file")
    plugins = os.path.realpath(os.path.join(home, ".claude", "plugins"))
    real = os.path.realpath(path)
    if real == plugins or real.startswith(plugins + os.sep):
        raise Refused(f"{path} belongs to an installed plugin; change it upstream instead")


def new_rewrite(text, path):
    lint = _lint()
    if "\r" in text:
        raise Refused(f"{path} uses CRLF line endings")
    new = lint.rewrite(text)
    lost = lint.preserved_items(text) - lint.preserved_items(new)
    if lost:
        raise Refused(f"rewrite would drop preserved content ({', '.join(sorted(lost)[:3])})")
    return new


def new_drop_section(text, line, heading):
    lint = _lint()
    lines = text.splitlines()
    mask = lint.prose_mask(lines)
    for start, end, _path in lint._subtrees(lines, mask):
        if start + 1 != line:
            continue
        m = lint.HEADER_RE.match(lines[start])
        if not m or m.group(2).strip() != heading.strip():
            raise Refused(f"line {line} is '{lines[start].strip()}', not heading '{heading}'; file changed since review")
        drop = set(range(start, end))
        if start > 0 and not lines[start - 1].strip() and (end >= len(lines) or not lines[end].strip()):
            drop.add(start - 1)
        kept = [l for n, l in enumerate(lines) if n not in drop]
        return "\n".join(kept) + ("\n" if text.endswith("\n") else "")
    raise Refused(f"no section heading at line {line}; file changed since review")


def new_pin_model(text, model):
    if model not in PIN_MODELS:
        raise ValueError(f"--model must be one of {', '.join(PIN_MODELS)}")
    if not text.startswith("---\n"):
        raise Refused("agent file has no YAML frontmatter")
    end = text.find("\n---", 3)
    if end == -1:
        raise Refused("agent file frontmatter is not closed")
    fm_lines = text[4:end].split("\n")
    rest = text[end:]
    out, done = [], False
    for l in fm_lines:
        if re.match(r"^model\s*:", l):
            out.append(f"model: {model}")
            done = True
        else:
            out.append(l)
    if not done:
        idx = next((k + 1 for k, l in enumerate(out) if re.match(r"^name\s*:", l)), len(out))
        out.insert(idx, f"model: {model}")
    return "---\n" + "\n".join(out) + rest


def backup_and_write(path, new_text, backup_root):
    real = os.path.realpath(path)
    dest = os.path.join(backup_root, real.lstrip(os.sep))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(real, dest)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(real), prefix=".moltbloat-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(new_text)
        shutil.copymode(real, tmp)
        os.replace(tmp, real)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return dest


def run(action, path, opts, home):
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    check_target(path, home)
    text = _read(path)
    digest = sha256(text)
    if opts.get("expect_sha256") and opts["expect_sha256"] != digest:
        raise Refused(f"{path} changed since it was reviewed (sha256 {digest[:12]})")
    if action == "rewrite":
        new = new_rewrite(text, path)
    elif action == "drop-section":
        new = new_drop_section(text, opts["line"], opts["heading"])
    else:
        new = new_pin_model(text, opts["model"])
    diff = "".join(difflib.unified_diff(text.splitlines(True), new.splitlines(True),
                                        fromfile=path, tofile=path + " (after)"))
    result = {"action": action, "file": path, "sha256": digest, "changed": new != text, "diff": diff}
    if opts.get("dry_run") or new == text:
        return result
    root = opts.get("backup_root") or os.path.join(
        home, ".moltbloat", "backups", datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    result["backup"] = backup_and_write(path, new, root)
    result["applied"] = True
    return result


def main(argv, home=None):
    home = home or os.path.expanduser("~")
    args = argv[1:]
    if len(args) < 2 or args[0] not in ("rewrite", "drop-section", "pin-model"):
        sys.stderr.write("usage: apply-instruction-change.py {rewrite|drop-section|pin-model} FILE [options]\n")
        return 2
    action, path, rest = args[0], args[1], args[2:]
    opts, i = {"dry_run": False}, 0
    valued = {"--line": "line", "--heading": "heading", "--model": "model",
              "--expect-sha256": "expect_sha256", "--backup-root": "backup_root"}
    while i < len(rest):
        a = rest[i]
        if a == "--dry-run":
            opts["dry_run"] = True
        elif a in valued:
            i += 1
            if i >= len(rest):
                sys.stderr.write(f"error: {a} requires a value\n")
                return 2
            opts[valued[a]] = rest[i]
        else:
            sys.stderr.write(f"error: unknown argument {a}\n")
            return 2
        i += 1
    if action == "drop-section":
        if "line" not in opts or "heading" not in opts:
            sys.stderr.write("error: drop-section needs --line and --heading\n")
            return 2
        try:
            opts["line"] = int(opts["line"])
        except ValueError:
            sys.stderr.write("error: --line must be an integer\n")
            return 2
    if action == "pin-model" and "model" not in opts:
        sys.stderr.write("error: pin-model needs --model\n")
        return 2
    try:
        result = run(action, path, opts, home)
    except FileNotFoundError as e:
        sys.stderr.write(f"error: file not found: {e}\n")
        return 1
    except ValueError as e:
        sys.stderr.write(f"error: {e}\n")
        return 2
    except Refused as e:
        sys.stderr.write(f"refused: {e}\n")
        return 3
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
