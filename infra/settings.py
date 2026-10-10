import json
from pathlib import Path

from dotenv import dotenv_values

from compliancelens.config import Settings


def terraform_inputs(root: Path) -> dict[str, str]:
    current = Settings(_env_file=root / ".env")
    example = Settings(
        _env_file=None, **{k.lower(): v for k, v in dotenv_values(root / ".env.example").items()}
    )
    return {
        "endpoint": current.aws_endpoint_url,
        "region": current.aws_default_region,
        "database_user": example.database_user,
        "database_name": example.database_name,
        "database_password": example.database_password.get_secret_value(),
    }


if __name__ == "__main__":
    print(json.dumps(terraform_inputs(Path(__file__).resolve().parents[1])))
