#!/usr/bin/env python3
"""Lint instruction files (CLAUDE.md, AGENTS.md, rules, memory) for waste.

Checks, all structural:
  emphasis_density         all-caps imperatives and shout tags per 100 prose lines
  duplicate_section        near-identical sections within or across files
  drifted_duplicate        two diverged versions of one section (a conflict)
  import_residue           <!-- imported-from: ... --> markers left by `claude import`
  instruction_byte_budget  an always-loaded file over its byte budget
  placeholder_marker       TODO / FIXME / TBD / XXX / "not implemented" in prose

Code fences, inline code, and blockquotes are never counted or rewritten.

--suggest-rewrite FILE prints a unified diff that removes exact duplicate
sections and import markers and softens emphasis. It refuses (exit 3) if the
rewrite would drop any preserved item: fenced block, inline code span, URL,
or @import line.

Usage:
  python3 instruction-lint.py FILE [FILE ...] [--json]
      [--emphasis-per-100 N] [--duplicate-similarity F]
      [--drifted-similarity F] [--byte-budget N]
  python3 instruction-lint.py --suggest-rewrite FILE [--also FILE ...]
"""
import difflib
import hashlib
import json
import os
import re
import sys
from collections import Counter

EMPHASIS_WORDS = ("MUST", "NEVER", "ALWAYS", "IMPORTANT", "CRITICAL", "REQUIRED", "ABSOLUTELY")
EMPHASIS_RE = re.compile(r"\b(" + "|".join(EMPHASIS_WORDS) + r")\b")
SHOUT_TAG_RE = re.compile(r"</?[A-Z][A-Z_]{3,}>")
LEADING_EMPHASIS_RE = re.compile(r"(^|(?<=[\s*>(-]))(?:\*\*)?(IMPORTANT|CRITICAL)(?:\*\*)?:\s*")
PLACEHOLDER_RE = re.compile(r"\b(TODO|FIXME|TBD|XXX)\b|not implemented", re.IGNORECASE)
PLACEHOLDER_CASE_SENSITIVE = {"TODO", "FIXME", "TBD", "XXX"}
IMPORT_MARKER_RE = re.compile(r"^\s*<!--\s*imported-from:.*?-->\s*$")
HEADER_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
URL_RE = re.compile(r"https?://[^\s)>\]]+")
IMPORT_LINE_RE = re.compile(r"(?<![\w@`])@(?:~/|\.{1,2}/|/)?[\w.\-/]+")
WORD_RE = re.compile(r"[a-z]{4,}")

MIN_SECTION_LINES = 5
MIN_SAME_HEADING_LINES = 2
SHARED_TOP_WORDS = 3
DEFAULTS = {"emphasis_per_100": 3.0, "duplicate_similarity": 0.95,
            "drifted_similarity": 0.6, "byte_budget": 25000}


def _read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def prose_mask(lines):
    """Per line: True if it is prose (not inside a fence, not a fence line, not a blockquote)."""
    mask, in_fence = [], False
    for line in lines:
        if FENCE_RE.match(line):
            in_fence = not in_fence
            mask.append(False)
        elif in_fence or line.lstrip().startswith(">"):
            mask.append(False)
        else:
            mask.append(True)
    return mask


def _prose_text(line):
    return INLINE_CODE_RE.sub("", line)


def emphasis_hits(text):
    lines = text.splitlines()
    mask = prose_mask(lines)
    hits, prose_lines = [], 0
    for n, (line, is_prose) in enumerate(zip(lines, mask), 1):
        if not is_prose:
            continue
        if line.strip():
            prose_lines += 1
        body = _prose_text(line)
        for m in EMPHASIS_RE.finditer(body):
            hits.append((n, m.group(1)))
        for m in SHOUT_TAG_RE.finditer(body):
            hits.append((n, m.group(0)))
    return hits, prose_lines


def placeholder_hits(text):
    lines = text.splitlines()
    out = []
    for n, (line, is_prose) in enumerate(zip(lines, prose_mask(lines)), 1):
        if not is_prose:
            continue
        for m in PLACEHOLDER_RE.finditer(_prose_text(line)):
            word = m.group(1)
            if word and word not in PLACEHOLDER_CASE_SENSITIVE:
                continue  # lowercase "todo" in prose is not a marker
            out.append((n, m.group(0)))
    return out


def split_sections(path, text):
    """Sections split on any Markdown header outside code fences.

    Each: {file, heading, line, body_lines}. Text before the first header is
    a section with heading "".
    """
    lines = text.splitlines()
    mask = prose_mask(lines)
    sections = [{"file": path, "heading": "", "line": 1, "body_lines": []}]
    for n, (line, is_prose) in enumerate(zip(lines, mask), 1):
        m = HEADER_RE.match(line) if is_prose else None
        if m:
            sections.append({"file": path, "heading": m.group(2), "line": n, "body_lines": []})
        else:
            sections[-1]["body_lines"].append(line)
    return sections


def _norm_heading(h):
    return re.sub(r"^[\d.)\s]+", "", h).strip().lower()


def _norm_body(lines):
    return "\n".join(" ".join(l.split()).lower() for l in lines if l.strip())


def _top_words(body):
    return {w for w, _ in Counter(WORD_RE.findall(body)).most_common(10)}


def compare_sections(sections, dup_sim, drift_sim):
    """Findings for duplicate and drifted section pairs (bounded comparison)."""
    cands = []
    for s in sections:
        body = _norm_body(s["body_lines"])
        n_lines = sum(1 for l in s["body_lines"] if l.strip())
        if n_lines < MIN_SAME_HEADING_LINES:
            continue
        cands.append((s, body, _norm_heading(s["heading"]), _top_words(body),
                      hashlib.sha1(body.encode()).hexdigest(), n_lines))
    findings = []
    for i in range(len(cands)):
        for j in range(i + 1, len(cands)):
            a, ab, ah, aw, ahash, an = cands[i]
            b, bb, bh, bw, bhash, bn = cands[j]
            same_heading = bool(ah) and ah == bh
            # Short sections only pair when their headings match; otherwise
            # short unrelated sections would pair on common words.
            if not same_heading and min(an, bn) < MIN_SECTION_LINES:
                continue
            if ahash == bhash:
                ratio = 1.0
            elif same_heading or len(aw & bw) >= SHARED_TOP_WORDS:
                ratio = difflib.SequenceMatcher(None, ab, bb).ratio()
            else:
                continue
            loc = f"{a['file']}:{a['line']} and {b['file']}:{b['line']}"
            if ratio >= dup_sim:
                findings.append({"type": "duplicate_section", "severity": "MEDIUM",
                                 "file": b["file"], "line": b["line"],
                                 "message": f"Section '{b['heading'] or '(preamble)'}' duplicates {a['file']}:{a['line']} ({ratio:.0%} similar). Keep one copy.",
                                 "pair": [f"{a['file']}:{a['line']}", f"{b['file']}:{b['line']}"]})
            elif ratio >= drift_sim or same_heading:
                diff = [l for l in difflib.unified_diff(a["body_lines"], b["body_lines"], lineterm="", n=0)
                        if l[:1] in "+-" and not l.startswith(("+++", "---"))]
                findings.append({"type": "drifted_duplicate", "severity": "HIGH",
                                 "file": b["file"], "line": b["line"],
                                 "message": f"Two diverged versions of '{b['heading'] or '(preamble)'}' at {loc} ({ratio:.0%} similar). Claude sees both and may follow either; pick one.",
                                 "pair": [f"{a['file']}:{a['line']}", f"{b['file']}:{b['line']}"],
                                 "differences": diff[:12]})
    return findings


def lint_files(paths, emphasis_per_100=DEFAULTS["emphasis_per_100"],
               duplicate_similarity=DEFAULTS["duplicate_similarity"],
               drifted_similarity=DEFAULTS["drifted_similarity"],
               byte_budget=DEFAULTS["byte_budget"]):
    findings, sections = [], []
    for p in paths:
        if not os.path.isfile(p):
            raise FileNotFoundError(p)
        text = _read(p)
        hits, prose_lines = emphasis_hits(text)
        if prose_lines and hits:
            density = len(hits) * 100.0 / prose_lines
            if density > emphasis_per_100:
                sev = "MEDIUM" if density > 2 * emphasis_per_100 else "LOW"
                words = Counter(w for _, w in hits).most_common(5)
                findings.append({"type": "emphasis_density", "severity": sev, "file": p, "line": hits[0][0],
                                 "message": (f"{len(hits)} emphatic words or tags in {prose_lines} prose lines "
                                             f"({density:.1f} per 100; threshold {emphasis_per_100:g}): "
                                             + ", ".join(f"{w} x{c}" for w, c in words)
                                             + ". Newer models follow plain instructions closely; emphasis written for older models tends to over-trigger.")})
        for n, word in placeholder_hits(text):
            findings.append({"type": "placeholder_marker", "severity": "LOW", "file": p, "line": n,
                             "message": f"`{word}` in instruction prose: unfinished text that loads every session."})
        for n, line in enumerate(text.splitlines(), 1):
            if IMPORT_MARKER_RE.match(line):
                findings.append({"type": "import_residue", "severity": "LOW", "file": p, "line": n,
                                 "message": "`claude import` marker comment; check the imported block is not a duplicate of existing instructions."})
        size = len(text.encode("utf-8"))
        if size > byte_budget:
            sev = "MEDIUM" if size > 2 * byte_budget else "LOW"
            findings.append({"type": "instruction_byte_budget", "severity": sev, "file": p, "line": 1,
                             "message": f"{size:,} bytes, over the {byte_budget:,}-byte budget. Move detail into files loaded on demand."})
        sections.extend(split_sections(p, text))
    findings.extend(compare_sections(sections, duplicate_similarity, drifted_similarity))
    return {"files_scanned": len(paths), "findings": findings}


# ---------- rewrite ----------

def preserved_items(text):
    """Set of items a rewrite must keep: fenced blocks, inline code, URLs, @imports."""
    items, block, in_fence = set(), [], False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            if in_fence:
                items.add("fence:" + "\n".join(block))
                block = []
            in_fence = not in_fence
            continue
        if in_fence:
            block.append(line)
            continue
        items.update("code:" + m for m in INLINE_CODE_RE.findall(line))
        items.update("url:" + m for m in URL_RE.findall(line))
        items.update("import:" + m for m in IMPORT_LINE_RE.findall(_prose_text(line)))
    return items


def _soften_line(line):
    # Inline code and URLs are split out and never changed.
    parts = re.split(r"(`[^`\n]*`|https?://[^\s)>\]]+)", line)
    for k in range(0, len(parts), 2):
        seg = LEADING_EMPHASIS_RE.sub(lambda m: m.group(1), parts[k])
        seg = SHOUT_TAG_RE.sub("", seg)
        seg = EMPHASIS_RE.sub(lambda m: m.group(1).lower(), seg)
        parts[k] = seg
    return "".join(parts)


def rewrite(text, other_texts=()):
    """Rewritten text: drop exact-duplicate sections, import markers, emphasis."""
    lines = text.splitlines()
    mask = prose_mask(lines)
    seen = set()
    for other in other_texts:
        for s in split_sections("", other):
            body = _norm_body(s["body_lines"])
            if sum(1 for l in s["body_lines"] if l.strip()) >= MIN_SAME_HEADING_LINES:
                seen.add((_norm_heading(s["heading"]), body))
    out = []
    for line, is_prose in zip(lines, mask):
        m = HEADER_RE.match(line) if is_prose else None
        if is_prose and IMPORT_MARKER_RE.match(line):
            continue
        out.append((line, is_prose, m))
    # Second pass: drop a section whose heading and body exactly match an
    # earlier one (in this file or an --also file). Only exact matches;
    # drifted versions are left for the user to choose between.
    result, current = [], []

    def flush():
        if not current:
            return
        header = current[0][2]
        body_lines = [l for l, _, _ in (current[1:] if header else current)]
        key = (_norm_heading(header.group(2)) if header else "", _norm_body(body_lines))
        substantive = sum(1 for l in body_lines if l.strip()) >= MIN_SAME_HEADING_LINES
        if header and substantive and key in seen:
            return
        if substantive:
            seen.add(key)
        result.extend(current)

    for item in out:
        if item[2]:
            flush()
            current = [item]
        else:
            current.append(item)
    flush()
    final = [_soften_line(l) if p else l for l, p, _ in result]
    trailing = "\n" if text.endswith("\n") else ""
    return re.sub(r"\n{3,}", "\n\n", "\n".join(final)) + trailing


def suggest_rewrite(path, also=()):
    """(exit_code, output). 0 with a diff, 0 with no-op note, 3 if unsafe."""
    text = _read(path)
    new = rewrite(text, [_read(p) for p in also])
    if new == text:
        return 0, f"No rewrite suggested for {path}."
    lost = preserved_items(text) - preserved_items(new)
    if lost:
        sample = ", ".join(sorted(lost)[:3])
        return 3, f"error: rewrite of {path} would drop preserved content ({sample}); not suggested\n"
    diff = difflib.unified_diff(text.splitlines(True), new.splitlines(True),
                                fromfile=path, tofile=path + " (suggested)")
    return 0, "".join(diff)


def render_markdown(result):
    lines = ["# Instruction Lint", "", f"Scanned {result['files_scanned']} file(s).", ""]
    if not result["findings"]:
        lines.append("No findings.")
        return "\n".join(lines)
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    lines += ["| Severity | Check | File:line | Finding |", "|---|---|---|---|"]
    for f in sorted(result["findings"], key=lambda f: (order.get(f["severity"], 9), f["file"], f["line"])):
        lines.append(f"| {f['severity']} | {f['type']} | {f['file']}:{f['line']} | {f['message']} |")
    for f in result["findings"]:
        if f.get("differences"):
            lines += ["", f"Differences for {f['pair'][0]} vs {f['pair'][1]}:", "```diff"] + f["differences"] + ["```"]
    return "\n".join(lines)


def main(argv):
    args = argv[1:]
    if args[:1] == ["--suggest-rewrite"]:
        if len(args) < 2:
            sys.stderr.write("error: --suggest-rewrite requires a file\n")
            return 2
        path, also, rest = args[1], [], args[2:]
        while rest:
            if rest[0] == "--also" and len(rest) > 1:
                also.append(rest[1])
                rest = rest[2:]
            else:
                sys.stderr.write(f"error: unknown argument {rest[0]}\n")
                return 2
        for p in [path] + also:
            if not os.path.isfile(p):
                sys.stderr.write(f"error: file not found: {p}\n")
                return 1
        code, out = suggest_rewrite(path, also)
        (sys.stderr if code else sys.stdout).write(out if out.endswith("\n") else out + "\n")
        return code

    opts = {"--emphasis-per-100": ("emphasis_per_100", float),
            "--duplicate-similarity": ("duplicate_similarity", float),
            "--drifted-similarity": ("drifted_similarity", float),
            "--byte-budget": ("byte_budget", int)}
    kwargs, files, as_json = {}, [], False
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--json":
            as_json = True
        elif a in opts:
            i += 1
            if i >= len(args):
                sys.stderr.write(f"error: {a} requires a value\n")
                return 2
            key, cast = opts[a]
            try:
                kwargs[key] = cast(args[i])
            except ValueError:
                sys.stderr.write(f"error: {a} got {args[i]!r}\n")
                return 2
        elif a.startswith("--"):
            sys.stderr.write(f"error: unknown argument {a}\n")
            return 2
        else:
            files.append(a)
        i += 1
    if not files:
        sys.stderr.write("error: no files given\n")
        return 2
    try:
        result = lint_files(files, **kwargs)
    except FileNotFoundError as e:
        sys.stderr.write(f"error: file not found: {e}\n")
        return 1
    print(json.dumps(result, indent=2) if as_json else render_markdown(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
