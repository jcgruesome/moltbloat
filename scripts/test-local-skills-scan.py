#!/usr/bin/env python3
"""Tests for local-skills-scan.py: `.claude/skills/` inventory and collisions.

Run: python3 scripts/test-local-skills-scan.py
"""
import importlib.util
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("local_skills_scan", os.path.join(HERE, "local-skills-scan.py"))
lss = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lss)


def _assert(cond, msg):
    if not cond:
        print(f"  x {msg}")
        raise SystemExit(1)
    print(f"  ok {msg}")


def make_skill(root, name):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "SKILL.md"), "w") as f:
        f.write(f"---\nname: {name}\n---\n")


def run():
    with tempfile.TemporaryDirectory() as d:
        skills_dir = os.path.join(d, "skills")
        make_skill(skills_dir, "deploy")
        make_skill(skills_dir, "lint")

        result = lss.scan([skills_dir])
        _assert("deploy" in result["local_skills"] and "lint" in result["local_skills"], "nested skills found")
        _assert(result["collisions"] == [], "no collisions when nothing else claims these names")

        solo_dir = os.path.join(d, "solo-skill")
        os.makedirs(solo_dir, exist_ok=True)
        with open(os.path.join(solo_dir, "SKILL.md"), "w") as f:
            f.write("---\nname: solo-skill\n---\n")
        _assert("solo-skill" in lss.scan([solo_dir])["local_skills"], "root-level SKILL.md counted as one skill")

        other_skills_dir = os.path.join(d, "other-skills")
        make_skill(other_skills_dir, "deploy")
        result_dup = lss.scan([skills_dir, other_skills_dir])
        dup = next(c for c in result_dup["collisions"] if c["name"] == "deploy")
        _assert(len(dup["paths"]) == 2, "same-named skill from two local dirs flagged, both paths recorded")

        result_plugin = lss.scan([skills_dir], plugin_skill_names={"lint": "some-linter-plugin"})
        hit = next(c for c in result_plugin["collisions"] if c["name"] == "lint")
        _assert(hit["plugin_source"] == "some-linter-plugin", "plugin collision names the owning plugin")
        _assert(not any(c["name"] == "deploy" for c in result_plugin["collisions"]), "unrelated local skill not flagged")

        missing = lss.scan([os.path.join(d, "does-not-exist")])
        _assert(missing == {"local_skills": {}, "collisions": []}, "nonexistent directory yields nothing, no error")

    print("\nAll local-skills-scan tests passed")


if __name__ == "__main__":
    run()
