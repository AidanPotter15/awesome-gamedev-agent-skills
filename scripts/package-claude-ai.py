#!/usr/bin/env python3
"""Package the skills as ready-to-upload zips for Claude.ai (Customize -> Skills -> Upload).

Writes to dist/claude-ai/:

- gamedev.zip: one skill holding the router and every skill, so the whole catalog
  installs with a single upload. The router is its SKILL.md; each skill lives at
  skills/<category>/<name>/GUIDE.md (renamed so the zip has exactly one SKILL.md).
- individual/<name>.zip: one zip per skill, router included, for picking a subset.
- individual-skills.zip: every individual zip in one download.

Like validate-skills.py, this uses only the Python standard library.
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "dist" / "claude-ai"
BUNDLE_NAME = "gamedev"
GUIDE = "GUIDE.md"
VERSION_DOC = REPO_ROOT / "docs" / "VERSION-SUPPORT.md"
SKIP_NAMES = frozenset({"__pycache__", ".DS_Store", "Thumbs.db", "desktop.ini"})
# Fixed timestamp so rebuilding unchanged sources gives byte-identical zips.
ZIP_TIME = (1980, 1, 1, 0, 0, 0)

BUNDLE_NOTE = f"""
> **Bundled catalog.** This skill packages the router with every game-dev skill. Each skill
> lives at `skills/<category>/<name>/{GUIDE}` (with its own `references/`, `scripts/`,
> `assets/`), relative to this file. Wherever a skill is named in backticks, here or inside
> another guide, open that path; `references/skill-index.md` lists every skill with its
> description.
"""

Entry = tuple[str, bytes, int]


def replace_once(text: str, old: str, new: str, where: str) -> str:
    """Replace text the bundle depends on, failing loudly if the source changed."""
    if old not in text:
        sys.exit(f"package-claude-ai: expected text not found in {where}: {old!r}")
    return text.replace(old, new)


def frontmatter(text: str) -> dict[str, str]:
    """Parse the flat fields and folded scalars used by this repository."""
    lines = text.splitlines()
    end = lines.index("---", 1)
    fields: dict[str, str] = {}
    key = ""
    for line in lines[1:end]:
        if line[:1] in (" ", "\t"):
            fields[key] = f"{fields[key]} {line.strip()}".strip()
        elif line.strip():
            key, _, value = line.partition(":")
            value = value.strip()
            fields[key] = "" if value in {">", ">-", "|", "|-"} else value
    return fields


def skill_dirs() -> list[Path]:
    return sorted(p.parent for p in (REPO_ROOT / "skills").glob("*/*/SKILL.md"))


def files_under(root: Path) -> list[Path]:
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and not SKIP_NAMES.intersection(p.relative_to(root).parts)
    )


def rewrite_version_links(rel: Path, text: str) -> str:
    """Point the router's ../docs links at the copy shipped inside the zip."""
    if rel == Path("SKILL.md"):
        return replace_once(
            text, "`../docs/VERSION-SUPPORT.md`", "`docs/VERSION-SUPPORT.md`", "router/SKILL.md"
        )
    if rel == Path("references/engine-detection.md"):
        return replace_once(
            text,
            "`../../docs/VERSION-SUPPORT.md`",
            "`../docs/VERSION-SUPPORT.md`",
            "router/references/engine-detection.md",
        )
    return text


def router_entries(prefix: str, transform) -> list[Entry]:
    router = REPO_ROOT / "router"
    entries: list[Entry] = []
    for path in files_under(router):
        rel = path.relative_to(router)
        data = path.read_bytes()
        if path.suffix == ".md":
            text = rewrite_version_links(rel, data.decode("utf-8"))
            data = transform(rel, text).encode("utf-8")
        entries.append((f"{prefix}/{rel.as_posix()}", data, path.stat().st_mode))
    entries.append(
        (f"{prefix}/docs/VERSION-SUPPORT.md", VERSION_DOC.read_bytes(), VERSION_DOC.stat().st_mode)
    )
    return entries


def bundle_router(rel: Path, text: str) -> str:
    if rel == Path("SKILL.md"):
        where = "router/SKILL.md"
        text = replace_once(text, "\nname: router\n", f"\nname: {BUNDLE_NAME}\n", where)
        heading = "# Master Router — Game-Development Skill Dispatcher\n"
        text = replace_once(text, heading, heading + BUNDLE_NOTE, where)
        text = replace_once(
            text,
            "open only the chosen `SKILL.md` bodies",
            f"open only the chosen `{GUIDE}` bodies",
            where,
        )
        text = replace_once(
            text,
            "1. **Preloaded:** only each skill's `name` + `description` are in context. "
            "Decide from those plus\n   the fingerprint — do **not** pre-read bodies.",
            "1. **Pick from the index:** choose from the routing table above (every skill's "
            "description is in\n   `references/skill-index.md`) plus the fingerprint — do "
            "**not** pre-read guide bodies.",
            where,
        )
    if rel in (Path("SKILL.md"), Path("references/routing-table.md")):
        text = replace_once(
            text,
            "`skills/<category>/<name>/SKILL.md`",
            f"`skills/<category>/<name>/{GUIDE}`",
            f"router/{rel.as_posix()}",
        )
    return text


def skill_index(dirs: list[Path]) -> bytes:
    rows = [
        "# Skill index",
        "",
        f"Every skill in this bundle. Open `skills/<category>/<name>/{GUIDE}` for the one you pick.",
        "",
        "| Skill | Category | Description |",
        "|-------|----------|-------------|",
    ]
    for skill in dirs:
        fields = frontmatter((skill / "SKILL.md").read_text(encoding="utf-8"))
        description = fields["description"].replace("|", "\\|")
        rows.append(f"| `{skill.name}` | `{skill.parent.name}` | {description} |")
    return ("\n".join(rows) + "\n").encode("utf-8")


def bundle_entries(dirs: list[Path]) -> list[Entry]:
    entries = router_entries(BUNDLE_NAME, bundle_router)
    entries = [e for e in entries if not e[0].startswith(f"{BUNDLE_NAME}/agents/")]
    entries.append((f"{BUNDLE_NAME}/references/skill-index.md", skill_index(dirs), 0o100644))
    for skill in dirs:
        prefix = f"{BUNDLE_NAME}/skills/{skill.parent.name}/{skill.name}"
        for path in files_under(skill):
            rel = path.relative_to(skill)
            if rel.parts[0] == "agents":
                continue
            data = path.read_bytes()
            if path.suffix == ".md":
                data = data.decode("utf-8").replace("`SKILL.md`", f"`{GUIDE}`").encode("utf-8")
            name = GUIDE if rel == Path("SKILL.md") else rel.as_posix()
            entries.append((f"{prefix}/{name}", data, path.stat().st_mode))
    skill_mds = [arc for arc, _, _ in entries if arc.endswith("/SKILL.md")]
    if skill_mds != [f"{BUNDLE_NAME}/SKILL.md"]:
        sys.exit(f"package-claude-ai: bundle must hold exactly one SKILL.md, found {skill_mds}")
    return entries


def individual_entries(skill: Path) -> list[Entry]:
    return [
        (f"{skill.name}/{p.relative_to(skill).as_posix()}", p.read_bytes(), p.stat().st_mode)
        for p in files_under(skill)
    ]


def write_zip(path: Path, entries: list[Entry]) -> None:
    dirs = {
        f"{'/'.join(arc.split('/')[:i])}/"
        for arc, _, _ in entries
        for i in range(1, arc.count("/") + 1)
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(dirs):
            info = zipfile.ZipInfo(name, date_time=ZIP_TIME)
            info.external_attr = (0o40755 << 16) | 0x10
            zf.writestr(info, b"")
        for arc, data, mode in sorted(entries):
            info = zipfile.ZipInfo(arc, date_time=ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (mode & 0xFFFF) << 16
            zf.writestr(info, data)


def main() -> int:
    dirs = skill_dirs()
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)

    write_zip(OUT_DIR / f"{BUNDLE_NAME}.zip", bundle_entries(dirs))

    individual = OUT_DIR / "individual"
    write_zip(individual / "router.zip", router_entries("router", lambda rel, text: text))
    for skill in dirs:
        write_zip(individual / f"{skill.name}.zip", individual_entries(skill))

    zips = sorted(individual.glob("*.zip"))
    write_zip(
        OUT_DIR / "individual-skills.zip",
        [(f"individual/{z.name}", z.read_bytes(), 0o100644) for z in zips],
    )

    print(f"{BUNDLE_NAME}.zip: router + {len(dirs)} skills in one upload")
    print(f"individual/: {len(zips)} zips (router + {len(dirs)} skills)")
    print(f"output: {OUT_DIR.relative_to(REPO_ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
