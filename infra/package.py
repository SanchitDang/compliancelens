import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def archive(source: Path, destination: Path, prefix: str = "") -> None:
    with ZipFile(destination, "w", ZIP_DEFLATED) as bundle:
        for path in sorted(source.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                info = ZipInfo(prefix + str(path.relative_to(source)))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                bundle.writestr(info, path.read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--application-only", action="store_true")
    args = parser.parse_args()
    DIST.mkdir(exist_ok=True)
    subprocess.run(
        [
            "uv",
            "export",
            "--no-dev",
            "--no-editable",
            "--no-hashes",
            "--no-emit-project",
            "--output-file",
            str(DIST / "requirements.txt"),
        ],
        cwd=ROOT,
        check=True,
    )
    requirements_hash = hashlib.sha256((DIST / "requirements.txt").read_bytes()).hexdigest()
    stamp = DIST / "dependencies.sha256"
    runtime_image = (ROOT / "infra" / "Dockerfile").read_text().splitlines()[0].split()[1]
    if args.application_only and (
        not stamp.exists() or stamp.read_text().strip() != requirements_hash
    ):
        raise RuntimeError("Requirements changed; run the full package command")
    if not args.application_only:
        if (DIST / "python").exists():
            shutil.rmtree(DIST / "python")
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--platform",
                "linux/arm64",
                "--entrypoint",
                "bash",
                "-v",
                f"{DIST}:/build",
                runtime_image,
                "-c",
                "pip install --disable-pip-version-check -r /build/requirements.txt "
                "--target /build/python --upgrade && python -c "
                "\"import sys; sys.path.insert(0, '/build/python'); "
                "import spacy, psycopg, presidio_analyzer, en_core_web_sm; "
                "en_core_web_sm.load(); print('Linux ARM64 imports and model passed')\"",
            ],
            check=True,
        )
        stamp.write_text(requirements_hash + "\n")
    application = DIST / "application"
    if application.exists():
        shutil.rmtree(application)
    shutil.copytree(
        ROOT / "src" / "compliancelens",
        application / "compliancelens",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (application / "data").mkdir()
    shutil.copyfile(ROOT / "data" / "manifest.json", application / "data" / "manifest.json")
    archive(application, DIST / "lambda.zip")
    digest = hashlib.sha256(
        (DIST / "lambda.zip").read_bytes()
        + (DIST / "requirements.txt").read_bytes()
        + (ROOT / "infra" / "Dockerfile").read_bytes()
    ).hexdigest()
    registry = (ROOT / "infra" / "modules" / "platform" / "main.tf").read_text()
    repository = re.search(r'image_repository\s*=\s*"([^"$]+)"', registry).group(1)
    image_uri = f"{repository}:{digest}"
    subprocess.run(
        [
            "docker",
            "build",
            "--platform",
            "linux/arm64",
            "-f",
            str(ROOT / "infra" / "Dockerfile"),
            "-t",
            image_uri,
            str(DIST),
        ],
        check=True,
    )
    image_id = subprocess.run(
        ["docker", "image", "inspect", image_uri, "--format", "{{.Id}}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    (DIST / "image.json").write_text(
        json.dumps({"image_uri": image_uri, "sha256": digest, "image_id": image_id}) + "\n"
    )
    print("Built credential-free Linux ARM64 application image")


if __name__ == "__main__":
    main()
