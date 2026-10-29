"""Build, gate and regression-test the marketplace zip for gpt-image-generator.

Pipeline:
  1. validate SKILL.md frontmatter against the platform field table
  2. stage the shipping subset (root SKILL.md + references/ scripts/ templates/)
  3. run the STAGED copy's own selfcheck, in a clean config dir
  4. zip with a fixed mtime so the artefact is byte reproducible
  5. unpack the zip into a throwaway HOME and re-run the command battery
  6. size + depth + credential-leak gates

Any failed gate aborts the build; a bad package never reaches the platform.

Usage:
    python tools/pack_skill.py                 # build into dist/ next to the repo
    python tools/pack_skill.py -o out/x.zip    # explicit output path

The script is deliberately free of machine-specific paths so that anyone who
clones the repository can reproduce the exact same artefact.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT
DEFAULT_OUT = REPO_ROOT / "dist" / "gpt-image-generator.zip"

SHIP_DIRS = {"references", "scripts", "templates"}
SHIP_ROOT_FILES = {"SKILL.md"}
REQUIRED = ["name", "display_name", "display_name_en", "description",
            "description_zh", "description_en", "version", "author"]
# The platform's field table. Anything outside it is treated as noise.
# examples_zh / examples_en are not in the written field table, but the
# platform does parse them into the "试试这样问我" (usageExamples) block on
# the listing, so they belong here.
ALLOWED_FIELDS = {"name", "display_name", "display_name_en", "description",
                  "description_zh", "description_en", "examples_zh", "examples_en",
                  "allowed-tools", "version", "disable-model-invocation",
                  "user-invocable", "author", "category"}
MAX_ZIP_BYTES = 3 * 1024 * 1024
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def resolve_python() -> Path:
    """Prefer an interpreter that can import tkinter, so the selfcheck is honest."""
    candidates = [Path(sys.executable)]
    if os.name == "nt":
        for base in (Path(sys.prefix).parent, Path("C:/Program Files"),
                     Path("C:/Program Files (x86)")):
            if not base.is_dir():
                continue
            for folder in sorted(base.glob("Python3*")):
                candidate = folder / "python.exe"
                if candidate.is_file():
                    candidates.append(candidate)
    for candidate in candidates:
        if not candidate.is_file():
            continue
        probe = subprocess.run([str(candidate), "-c", "import tkinter"],
                               capture_output=True, text=True)
        if probe.returncode == 0:
            return candidate
    return Path(sys.executable)


PYTHON = resolve_python()


def fail(message: str) -> None:
    raise SystemExit(f"BUILD FAILED: {message}")


def run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None,
        timeout: int = 180) -> subprocess.CompletedProcess:
    merged = dict(os.environ)
    merged.setdefault("PYTHONIOENCODING", "utf-8")
    if env:
        merged.update(env)
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=merged,
                          capture_output=True, text=True, timeout=timeout, encoding="utf-8",
                          errors="replace")


def load_frontmatter(text: str) -> dict:
    """Parse the YAML frontmatter without hard-depending on PyYAML."""
    try:
        import yaml
    except ImportError:
        yaml = None
    if yaml is not None:
        return yaml.safe_load(text.split("---", 2)[1]) or {}
    data: dict = {}
    key = None
    for line in text.split("---", 2)[1].splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line.startswith(("  - ", "- ")):
            value = line.split("-", 1)[1].strip().strip('"').strip("'")
            if key:
                data.setdefault(key, [])
                if isinstance(data[key], list):
                    data[key].append(value)
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            data[key] = value if value else []
    return data


def check_frontmatter(text: str) -> dict:
    data = load_frontmatter(text)
    missing = [k for k in REQUIRED if not str(data.get(k, "")).strip()]
    if missing:
        fail(f"missing required fields: {missing}")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", str(data["name"])):
        fail(f"name is not kebab-case: {data['name']}")
    if "<" in str(data["description"]) or ">" in str(data["description"]):
        fail("description must not contain angle brackets")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(data["version"])):
        fail(f"version is not semver: {data['version']}")
    extra = sorted(set(data) - ALLOWED_FIELDS)
    if extra:
        fail(f"frontmatter carries fields outside the platform table: {extra}")
    if SKILL_DIR.name != data["name"]:
        fail(f"directory name {SKILL_DIR.name} does not match name {data['name']}")
    return data


def collect_files() -> list[tuple[Path, Path]]:
    files: list[tuple[Path, Path]] = []
    for path in sorted(SKILL_DIR.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(SKILL_DIR)
        if any(part in ("__pycache__", ".git", "dist", "tools") for part in rel.parts):
            continue
        if path.name.endswith((".pyc", ".pyo", ".bak", ".orig", ".swp", ".tmp")):
            continue
        if ".bak" in path.name or path.name.startswith("."):
            continue
        if len(rel.parts) == 1:
            if rel.name not in SHIP_ROOT_FILES:
                continue
        elif rel.parts[0] not in SHIP_DIRS:
            continue
        if len(rel.parts) > 2:
            fail(f"depth > 2: {rel}")
        files.append((path, rel))
    return files


def stage_files(files: list[tuple[Path, Path]], stage: Path) -> Path:
    if stage.exists():
        shutil.rmtree(stage)
    root = stage / SKILL_DIR.name
    root.mkdir(parents=True)
    for path, rel in files:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    return root


def gate_selfcheck(staged_root: Path) -> None:
    """The staged copy must pass its own offline self test."""
    script = staged_root / "scripts" / "aiimagesee_image.py"
    if not script.is_file():
        fail("scripts/aiimagesee_image.py missing from the staged package")
    with tempfile.TemporaryDirectory() as tmp:
        env = {"GPT_IMAGE_GENERATOR_CONFIG_DIR": str(Path(tmp) / "cfg")}
        result = run([str(PYTHON), str(script), "selfcheck", "--json"], env=env)
    if result.returncode != 0:
        fail(f"staged selfcheck exited {result.returncode}\n{result.stdout}\n{result.stderr}")
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        fail(f"staged selfcheck did not print JSON: {error}")
    if report.get("failed"):
        fail(f"staged selfcheck reported failures: {report}")
    print(f"  selfcheck: {report.get('passed')} passed, {report.get('warnings')} warnings")


def build_zip(staged_root: Path, stage: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(staged_root.rglob("*")):
            if not path.is_file():
                continue
            info = zipfile.ZipInfo(path.relative_to(stage).as_posix(), date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())


def gate_zip(out: Path) -> list[str]:
    size = out.stat().st_size
    if size > MAX_ZIP_BYTES:
        fail(f"zip is {size} bytes, over the 3MB limit")
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        for name in names:
            parts = name.split("/")
            if len(parts) > 3:
                fail(f"entry deeper than two levels: {name}")
            if not parts[0].startswith("gpt-image-generator"):
                fail(f"unexpected zip root: {parts[0]}")
            if len(parts) == 3 and parts[1] not in SHIP_DIRS:
                fail(f"entry in a directory outside the whitelist: {name}")
            if any(part in ("__pycache__", ".git") for part in parts):
                fail(f"build residue in the package: {name}")
            if name.endswith((".pyc", ".bak")):
                fail(f"backup residue in the package: {name}")
        payload = b"".join(zf.read(name) for name in names if not name.endswith(".png")
                           and not name.endswith(".jpg"))
        # Look for credential-shaped material, not the literal "sk-" prefix that
        # the setup guide legitimately mentions when it tells users to mask keys.
        secret_patterns = [
            rb"sk-[A-Za-z0-9_\-]{16,}",
            rb"Bearer\s+[A-Za-z0-9_\-]{16,}",
            rb"(?i)api[_-]?key\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{16,}",
            rb"(?i)(secret|password|token)\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{16,}",
        ]
        for pattern in secret_patterns:
            hit = re.search(pattern, payload)
            if hit:
                fail(f"possible credential material found in the package: {hit.group(0)[:40]!r}")
    return names


def gate_clean_room(out: Path) -> None:
    """Unpack the zip into a throwaway HOME and re-run the command battery."""
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        unpacked = Path(tmp) / "pkg"
        with zipfile.ZipFile(out) as zf:
            zf.extractall(unpacked)
        root = unpacked / "gpt-image-generator"
        script = root / "scripts" / "aiimagesee_image.py"
        env = {
            "GPT_IMAGE_GENERATOR_CONFIG_DIR": str(home / "cfg"),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "GPT_IMAGE_GENERATOR_HEADLESS": "1",
        }
        battery = [
            ["--help"], ["-h"], [], ["help"], ["help", "generate"],
            ["version"], ["--version"], ["config"], ["selfcheck"],
            ["selfcheck", "--json"], ["models"], ["model", "show"],
            ["generate", "--offline", "--prompt", "clean room", "--out", str(home / "a.png")],
            ["edit", "--offline", "--prompt", "clean room", "--image", str(home / "a.png"),
             "--out", str(home / "b.png")],
        ]
        for arguments in battery:
            result = run([str(PYTHON), str(script), *arguments], cwd=root, env=env)
            label = " ".join(arguments) or "(no arguments)"
            if result.returncode != 0:
                fail(f"clean room command failed: {label} -> exit {result.returncode}\n"
                     f"{result.stdout}\n{result.stderr}")
        # The two commands that must fail, and only those.
        for arguments in (["bogus-command"], ["generate", "--prompt", "x", "--out", str(home / "c.png")]):
            result = run([str(PYTHON), str(script), *arguments], cwd=root, env=env)
            label = " ".join(arguments)
            if result.returncode == 0:
                fail(f"clean room command should have failed: {label}")
            print(f"  expected failure ok: {label} -> exit {result.returncode}")
        produced = home / "a.png"
        if not produced.is_file() or produced.stat().st_size < 1024:
            fail("the offline preview did not produce a usable PNG")
        print(f"  clean room: {len(battery)} commands ok, offline preview {produced.stat().st_size} bytes")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and gate the marketplace zip.")
    parser.add_argument("-o", "--out", default=str(DEFAULT_OUT), help="output zip path")
    args = parser.parse_args()

    out = Path(args.out).expanduser().resolve()
    print(f"source : {SKILL_DIR}")
    print(f"python : {PYTHON}")
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    data = check_frontmatter(text)
    for ref in re.findall(r"@(references/[\w./-]+)", text):
        if not (SKILL_DIR / ref).exists():
            fail(f"broken @reference: {ref}")
    files = collect_files()
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "stage"
        staged_root = stage_files(files, stage)
        print(f"staged : {len(files)} files")
        gate_selfcheck(staged_root)
        build_zip(staged_root, stage, out)
        names = gate_zip(out)
        gate_clean_room(out)
    size = out.stat().st_size
    print(f"zip    : {out.name}  {size / 1024:.0f} KB  {len(names)} entries")
    for name in names:
        print("   ", name)
    print(f"version: {data['version']}   author: {data['author']}   category: {data['category']}")
    print("BUILD OK")


if __name__ == "__main__":
    main()
