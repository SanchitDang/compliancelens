import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from compliancelens.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="compliancelens")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("config-check")
    ingestion = commands.add_parser("ingest")
    mode = ingestion.add_mutually_exclusive_group()
    mode.add_argument("--download-only", action="store_true")
    mode.add_argument("--prepare-only", action="store_true")
    ingestion.add_argument("--refresh", action="store_true")
    arguments = parser.parse_args()
    try:
        settings = Settings()
    except ValidationError as error:
        parser.exit(2, f"Invalid configuration: {error}\n")
    if arguments.command == "ingest":
        from compliancelens.ingestion import ingest
        from compliancelens.store import IdentityMismatch

        try:
            report = ingest(
                settings,
                Path.cwd(),
                arguments.download_only,
                arguments.prepare_only,
                arguments.refresh,
            )
        except Exception as error:
            detail = str(error) if isinstance(error, IdentityMismatch) else type(error).__name__
            parser.exit(1, f"Ingestion failed: {detail}. See data/runs for safe usage records.\n")
        print(json.dumps(report, indent=2))
        return
    print(
        f"Scaffold configuration valid: chat={settings.llm_backend}, "
        f"embeddings={settings.embedding_backend}, dimension={settings.embedding_dimension}"
    )
    print("Provider credentials/connectivity, ingestion, and inference are not tested here.")
