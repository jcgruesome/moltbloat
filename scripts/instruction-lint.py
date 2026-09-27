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

--suggest-rewrite FILE prints a unified diff that removes `claude import`
markers and sections that exactly repeat an earlier section of the same file
(same heading path, identical subtree). Emphasis and cross-file duplicates
are reported, never rewritten. It refuses (exit 3) for non-Markdown or CRLF
files, or if the rewrite would lose every copy of a fenced block, inline
code span, URL, @import, or file path. Setext (underlined) headings are not
treated as section breaks.

Usage:
  python3 instruction-lint.py FILE [FILE ...] [--json]
      [--emphasis-per-100 N] [--duplicate-similarity F]
      [--drifted-similarity F] [--byte-budget N]
  python3 instruction-lint.py --suggest-rewrite FILE
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
# Above this many candidate sections, fuzzy comparison runs only on pairs
# with the same heading, keeping huge files from pairwise blowup.
FUZZY_PAIR_CAP = 300
STOPWORDS = {"this", "that", "with", "from", "have", "your", "when", "then", "they", "them",
             "will", "each", "into", "only", "also", "than", "what", "which", "there", "their",
             "should", "would", "could", "about", "before", "after", "using", "must", "never"}
SHARED_TOP_WORDS = 3
DEFAULTS = {"emphasis_per_100": 3.0, "duplicate_similarity": 0.95,
            "drifted_similarity": 0.6, "byte_budget": 25000}


def _read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def split_lines(text):
    """Lines split on "\n" only, without the empty tail after a final newline.

    str.splitlines() also splits on form feed, U+2028 and friends, which
    would renumber lines against editors and let a rewrite turn those
    characters into real newlines.
    """
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()
    return lines


def _keepends(text):
    return re.findall(r"[^\n]*\n|[^\n]+$", text)


def prose_mask(lines):
    """Per line: True if it is prose (not inside a fence, not a fence line, not a blockquote)."""
    mask, fence = [], None
    for line in lines:
        m = FENCE_RE.match(line)
        if m and (fence is None or m.group(1) == fence):
            fence = None if fence else m.group(1)
            mask.append(False)
        elif fence or line.lstrip().startswith(">"):
            mask.append(False)
        else:
            mask.append(True)
    return mask


def _prose_text(line):
    return INLINE_CODE_RE.sub("", line)


def emphasis_hits(text):
    lines = split_lines(text)
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
    lines = split_lines(text)
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
    lines = split_lines(text)
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
    words = [w for w in WORD_RE.findall(body) if w not in STOPWORDS]
    return {w for w, _ in Counter(words).most_common(10)}


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
    fuzzy_by_words = len(cands) <= FUZZY_PAIR_CAP
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
            elif same_heading or (fuzzy_by_words and len(aw & bw) >= SHARED_TOP_WORDS):
                ratio = difflib.SequenceMatcher(None, ab, bb).ratio()
            else:
                continue
            loc = f"{a['file']}:{a['line']} and {b['file']}:{b['line']}"
            if ratio >= dup_sim:
                findings.append({"type": "duplicate_section", "severity": "MEDIUM",
                                 "file": b["file"], "line": b["line"],
                                 "message": f"Section '{b['heading'] or '(preamble)'}' duplicates {a['file']}:{a['line']} ({ratio:.0%} similar). Keep one copy.",
                                 "pair": [f"{a['file']}:{a['line']}", f"{b['file']}:{b['line']}"],
                                 "headings": [a["heading"], b["heading"]]})
            elif ratio >= drift_sim or same_heading:
                diff = [l for l in difflib.unified_diff(a["body_lines"], b["body_lines"], lineterm="", n=0)
                        if l[:1] in "+-" and not l.startswith(("+++", "---"))]
                findings.append({"type": "drifted_duplicate", "severity": "HIGH",
                                 "file": b["file"], "line": b["line"],
                                 "message": f"Two diverged versions of '{b['heading'] or '(preamble)'}' at {loc} ({ratio:.0%} similar). Claude sees both and may follow either; pick one.",
                                 "pair": [f"{a['file']}:{a['line']}", f"{b['file']}:{b['line']}"],
                                 "headings": [a["heading"], b["heading"]],
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
        for n, line in enumerate(split_lines(text), 1):
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
#
# The rewrite is deliberately structural only: it removes `claude import`
# marker lines and exact duplicate sections within one file. Emphasis and
# cross-file duplicates are reported, never rewritten: softening wording and
# choosing which file keeps a shared section both need a human.

PATH_RE = re.compile(r"(?<![\w@/])(?:~/|\.{1,2}/|/)?(?:[\w.\-]+/)+[\w.\-]+|(?<![\w@/])[\w\-]+\.(?:md|json|ya?ml|toml|py|js|ts|sh)\b")


def preserved_items(text):
    """Items a rewrite must keep at least one copy of: fenced blocks, inline
    code, URLs, @imports, and file paths."""
    items, block, fence = set(), [], None
    for line in split_lines(text):
        m = FENCE_RE.match(line)
        if m and (fence is None or m.group(1) == fence):
            if fence is not None:
                items.add("fence:" + "\n".join(block))
                block = []
                fence = None
            else:
                fence = m.group(1)
            continue
        if fence is not None:
            block.append(line)
            continue
        items.update("code:" + c for c in INLINE_CODE_RE.findall(line))
        items.update("url:" + u for u in URL_RE.findall(line))
        prose = URL_RE.sub("", _prose_text(line))
        items.update("import:" + i for i in IMPORT_LINE_RE.findall(prose))
        items.update("path:" + q for q in PATH_RE.findall(prose))
    return items


def _subtrees(lines, mask):
    """(start, end, path) per header; a subtree runs to the next header of the
    same or higher level. `path` is the normalized headings from the root."""
    heads = []
    for n, (line, is_prose) in enumerate(zip(lines, mask)):
        m = HEADER_RE.match(line) if is_prose else None
        if m:
            heads.append((n, len(m.group(1)), _norm_heading(m.group(2))))
    out, stack = [], []
    for k, (n, level, heading) in enumerate(heads):
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, heading))
        end = len(lines)
        for n2, level2, _ in heads[k + 1:]:
            if level2 <= level:
                end = n2
                break
        out.append((n, end, tuple(h for _, h in stack)))
    return out


def rewrite(text):
    """Text with import markers and exact duplicate sections removed.

    A section is removed only when an earlier section has the same heading
    path (parent headings included, levels ignored) and an identical subtree
    (its body plus every child section), with at least MIN_SAME_HEADING_LINES
    non-blank body lines. Everything else is left byte-for-byte.
    """
    lines = split_lines(text)
    mask = prose_mask(lines)
    drop = set(n for n, (line, p) in enumerate(zip(lines, mask)) if p and IMPORT_MARKER_RE.match(line))
    seen = set()
    for start, end, path in _subtrees(lines, mask):
        if start in drop:
            continue  # inside a subtree already removed
        body = [l for k, l in enumerate(lines[start + 1:end], start + 1) if k not in drop]
        key = (path, _norm_body(body))
        if sum(1 for l in body if l.strip()) < MIN_SAME_HEADING_LINES:
            continue
        if key in seen:
            drop.update(range(start, end))
            # also drop the blank line that separated it, so no gap doubles
            if start > 0 and not lines[start - 1].strip() and (end >= len(lines) or not lines[end].strip()):
                drop.add(start - 1)
        else:
            seen.add(key)
    kept = [l for n, l in enumerate(lines) if n not in drop]
    trailing = "\n" if text.endswith("\n") else ""
    return "\n".join(kept) + trailing


def _unified_diff(path, old, new):
    """Unified diff that `patch` accepts, including files without a final newline."""
    out = []
    for line in difflib.unified_diff(_keepends(old), _keepends(new),
                                     fromfile=path, tofile=path + " (suggested)"):
        if line.endswith("\n"):
            out.append(line)
        else:
            out.append(line + "\n\\ No newline at end of file\n")
    return "".join(out)


def suggest_rewrite(path):
    """(exit_code, output). 0 with a diff or a no-op note, 3 if refused."""
    if not path.endswith(".md"):
        return 3, f"error: {path} is not a Markdown file; only prose instruction files are rewritten\n"
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        text = f.read()  # newline="" keeps \r\n visible
    if "\r" in text:
        return 3, f"error: {path} uses CRLF line endings; no rewrite suggested\n"
    new = rewrite(text)
    if new == text:
        return 0, f"No rewrite suggested for {path}."
    lost = preserved_items(text) - preserved_items(new)
    if lost:
        sample = ", ".join(sorted(lost)[:3])
        return 3, f"error: rewrite of {path} would drop preserved content ({sample}); not suggested\n"
    return 0, _unified_diff(path, text, new)


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
        if len(args) > 2:
            sys.stderr.write(f"error: unknown argument {args[2]}\n")
            return 2
        path = args[1]
        if not os.path.isfile(path):
            sys.stderr.write(f"error: file not found: {path}\n")
            return 1
        code, out = suggest_rewrite(path)
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
