#!/usr/bin/env python3
"""Apply one reviewed change to an instruction file or agent definition.

Used by /moltbloat:clean, one confirmed change at a time. Three actions:

  rewrite FILE                  apply instruction-lint's structural rewrite
                                (import markers, exact duplicate sections)
  drop-section FILE --line N --heading TEXT
                                remove the section whose heading is at line N,
                                e.g. one side of a drifted duplicate the user
                                chose to drop; refused if it has subsections
  pin-model FILE --model M      set `model:` in an agent's frontmatter
                                (haiku, sonnet, opus, fable)

Every action:
  --dry-run            print the unified diff and the file's sha256; write nothing
  --expect-sha256 H    required to write: the sha256 from the reviewed dry run.
                       Refused (exit 3) if the file changed since.
  --backup-root DIR    backup location (default: a new directory under
                       <moltbloat data dir>/backups/, see paths.py). An existing backup is never
                       overwritten.

Refused (exit 3): files owned by an installed plugin (under the plugins dir
or any plugin installPath), non-Markdown, CRLF or BOM files, read-only or
hard-linked files, stale line or heading, unsafe rewrite.
Other exits: 0 applied or dry run, 1 missing file, 2 bad arguments.
"""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402  (active Claude config dir and per-config moltbloat data dir)

HERE = os.path.dirname(os.path.abspath(__file__))
PIN_MODELS = ("haiku", "sonnet", "opus", "fable")


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


def _fold(path):
    # APFS and HFS+ are case-insensitive by default.
    return path.lower() if sys.platform == "darwin" else path


def _under(path, root):
    path, root = _fold(os.path.realpath(path)), _fold(os.path.realpath(root))
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def config_dir(home):
    return paths.config_dir(home)


def plugin_roots(home):
    cfg = config_dir(home)
    roots = [os.path.join(cfg, "plugins")]
    manifest = os.path.join(cfg, "plugins", "installed_plugins.json")
    if os.path.isfile(manifest):
        with open(manifest, encoding="utf-8") as f:
            for entries in (json.load(f).get("plugins") or {}).values():
                roots += [e["installPath"] for e in entries or [] if (e or {}).get("installPath")]
    return roots


def check_target(path, home):
    real = os.path.realpath(path)
    if not real.endswith(".md"):
        raise Refused(f"{path} is not a Markdown file")
    for root in plugin_roots(home):
        if _under(real, root):
            raise Refused(f"{path} belongs to an installed plugin; change it upstream instead")
    if not os.access(real, os.W_OK):
        raise Refused(f"{path} is read-only")
    if os.stat(real).st_nlink > 1:
        raise Refused(f"{path} has other hard links; writing would split them")


def check_text(text, path):
    if text.startswith("﻿"):
        raise Refused(f"{path} starts with a byte-order mark")
    if "\r" in text:
        raise Refused(f"{path} uses CRLF line endings")


def new_rewrite(text, path):
    lint = _lint()
    new = lint.rewrite(text)
    lost = lint.preserved_items(text) - lint.preserved_items(new)
    if lost:
        raise Refused(f"rewrite would drop preserved content ({', '.join(sorted(lost)[:3])})")
    return new


def new_drop_section(text, line, heading):
    lint = _lint()
    lines = lint.split_lines(text)
    mask = lint.prose_mask(lines)
    for start, end, _path in lint._subtrees(lines, mask):
        if start + 1 != line:
            continue
        m = lint.HEADER_RE.match(lines[start])
        if not m or m.group(2).strip() != heading.strip():
            raise Refused(f"line {line} is '{lines[start].strip()}', not heading '{heading}'; file changed since review")
        for k in range(start + 1, end):
            if mask[k] and lint.HEADER_RE.match(lines[k]):
                raise Refused(f"section '{heading}' has subsections (line {k + 1}); the drift check compared only "
                              "its own body, so edit it by hand")
        drop = set(range(start, end))
        if start > 0 and not lines[start - 1].strip() and (end >= len(lines) or not lines[end].strip()):
            drop.add(start - 1)
        kept = [l for n, l in enumerate(lines) if n not in drop]
        return "\n".join(kept) + ("\n" if text.endswith("\n") else "")
    raise Refused(f"no section heading at line {line}; file changed since review")


FM_CLOSE_RE = re.compile(r"^---[ \t]*$", re.MULTILINE)


def new_pin_model(text, model):
    if model not in PIN_MODELS:
        raise ValueError(f"--model must be one of {', '.join(PIN_MODELS)}")
    if not text.startswith("---\n"):
        raise Refused("agent file has no YAML frontmatter")
    close = FM_CLOSE_RE.search(text, 4)
    if not close:
        raise Refused("agent file frontmatter is not closed")
    fm = text[4:close.start()]
    lines = fm.split("\n")[:-1] if fm.endswith("\n") else ([fm] if fm else [])
    if any(re.match(r"^model\s*:", l) for l in lines):
        lines = [f"model: {model}" if re.match(r"^model\s*:", l) else l for l in lines]
    else:
        lines = [f"model: {model}"] + lines  # first line: never inside a multi-line value
    return "---\n" + "".join(l + "\n" for l in lines) + text[close.start():]


def _backup_root(home):
    base = os.path.join(paths.moltbloat_home(home), "backups")
    os.makedirs(base, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return tempfile.mkdtemp(prefix=stamp + "-", dir=base)


def backup_and_write(path, expected_digest, new_text, backup_root):
    real = os.path.realpath(path)
    dest = os.path.join(backup_root, real.lstrip(os.sep))
    if os.path.exists(dest):
        raise Refused(f"backup {dest} already exists; not overwriting it")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(real, dest)
    if sha256(_read(real)) != expected_digest:
        raise Refused(f"{path} changed while applying; nothing written (backup kept at {dest})")
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(real), prefix=".moltbloat-")
    except OSError as e:
        raise Refused(f"cannot write next to {path}: {e}")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(new_text)
            f.flush()
            os.fsync(f.fileno())
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
    check_text(text, path)
    digest = sha256(text)
    if not opts.get("dry_run"):
        if not opts.get("expect_sha256"):
            raise ValueError("--expect-sha256 is required to write; take it from the reviewed --dry-run")
        if opts["expect_sha256"] != digest:
            raise Refused(f"{path} changed since it was reviewed (sha256 {digest[:12]})")
    if action == "rewrite":
        new = new_rewrite(text, path)
    elif action == "drop-section":
        new = new_drop_section(text, opts["line"], opts["heading"])
    else:
        new = new_pin_model(text, opts["model"])
    result = {"action": action, "file": path, "sha256": digest, "changed": new != text,
              "diff": _lint()._unified_diff(path, text, new) if new != text else ""}
    if opts.get("dry_run") or new == text:
        return result
    root = opts.get("backup_root") or _backup_root(home)
    result["backup"] = backup_and_write(path, digest, new, root)
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
