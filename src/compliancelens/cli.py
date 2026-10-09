import argparse

from pydantic import ValidationError

from compliancelens.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="compliancelens")
    parser.add_argument("command", choices=["config-check"])
    parser.parse_args()
    try:
        settings = Settings()
    except ValidationError as error:
        parser.exit(2, f"Invalid configuration: {error}\n")
    print(
        f"Scaffold configuration valid: chat={settings.llm_backend}, "
        f"embeddings={settings.embedding_backend}, dimension={settings.embedding_dimension}"
    )
    print("Provider credentials/connectivity, ingestion, and inference are not tested here.")
