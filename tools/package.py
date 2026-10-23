"""Create a source submission archive, excluding credentials and learner data."""
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {"data", "dist", ".git", "__pycache__", "node_modules", ".pytest_cache"}


def main():
    output = ROOT / "dist" / "zhidian-v0.5-source.zip"
    output.parent.mkdir(exist_ok=True)
    count = 0
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(ROOT.rglob("*")):
            relative = file.relative_to(ROOT)
            if not file.is_file() or any(part in EXCLUDED for part in relative.parts) or (file.name.startswith(".env") and file.name != ".env.example") or file.suffix == ".pyc":
                continue
            archive.write(file, Path("zhidian") / relative)
            count += 1
    print(f"Packaged {count} files: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
