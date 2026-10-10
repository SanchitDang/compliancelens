import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import boto3
import httpx
from botocore.config import Config
from botocore.exceptions import ClientError
from psycopg import sql
from settings import terraform_inputs

from compliancelens.config import Settings, require_local_endpoint
from compliancelens.documents import Chunk
from compliancelens.embeddings import Embedder, EmbeddingIdentity
from compliancelens.privacy import Redactor
from compliancelens.store import VectorStore, connect

ROOT = Path(__file__).resolve().parents[1]


def client(service: str, settings: Settings, credentials: dict[str, Any] | None = None) -> Any:
    require_local_endpoint(settings.aws_endpoint_url)
    credentials = credentials or {
        "AccessKeyId": "test",
        "SecretAccessKey": "test",  # pragma: allowlist secret - Floci dummy credential
    }
    return boto3.client(
        service,
        endpoint_url=settings.aws_endpoint_url,
        region_name=settings.aws_default_region,
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials.get("SessionToken"),
        config=Config(
            retries={"max_attempts": 0},
            connect_timeout=5,
            read_timeout=150,
            s3={"addressing_style": "path"},
        ),
    )


def outputs(environment: str) -> dict[str, Any]:
    if environment not in {"dev", "prod"}:
        raise ValueError("Unregistered environment")
    result = subprocess.run(
        ["terragrunt", "output", "-json"],
        cwd=ROOT / "infra" / "environments" / environment,
        capture_output=True,
        text=True,
        check=True,
    )
    return {key: value["value"] for key, value in json.loads(result.stdout).items()}


def verify_database(
    settings: Settings, values: dict[str, Any], dummy: dict[str, str]
) -> dict[str, Any]:
    database = values["database"]
    config = settings.model_copy(
        update={
            "database_host": urlsplit(settings.aws_endpoint_url).hostname,
            "database_port": database["port"],
            "database_name": database["name"],
            "database_user": database["user"],
        }
    )
    from pydantic import SecretStr

    config.database_password = SecretStr(dummy["database_password"])
    redactor = Redactor(settings.pii_spacy_model)
    with connect(config) as connection:
        app = VectorStore(connection, settings.vector_table, Embedder(settings, redactor).identity)
        app.initialize()
        app_rows = app.row_count()
        version = connection.execute(
            "SELECT extversion FROM pg_extension WHERE extname='vector'"
        ).fetchone()[0]
        schema = f"phase5_{uuid4().hex}"
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            connection.execute(
                sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema))
            )
            identity = EmbeddingIdentity(
                "synthetic",
                "phase5-synthetic",
                settings.embedding_dimension,
                hashlib.sha256(b"phase5-synthetic").hexdigest(),
            )
            store = VectorStore(connection, "phase5_vectors", identity)
            store.initialize()
            vector = [1.0] + [0.0] * (settings.embedding_dimension - 1)
            chunk = Chunk(
                "probe",
                "synthetic",
                "synthetic",
                "Synthetic vector probe",
                "synthetic",
                "Synthetic probe",
                "Probe",
                None,
                None,
                "https://example.invalid",
                datetime.now(UTC).isoformat(),
            )
            store.replace_document("synthetic", [chunk], {"synthetic": vector})
            found = store.search(vector, ["synthetic"], 1)
            if len(found) != 1 or found[0].metadata["chunk_id"] != "probe":
                raise RuntimeError("Synthetic nearest-neighbour probe failed")
            connection.execute("SET enable_seqscan=off")
            plan = connection.execute(
                sql.SQL(
                    "EXPLAIN SELECT id FROM {} ORDER BY embedding <=> %s::vector LIMIT 1"
                ).format(store.table),
                (json.dumps(vector),),
            ).fetchall()
            if not any("phase5_vectors_embedding_hnsw" in row[0] for row in plan):
                raise RuntimeError("HNSW probe did not use the index")
        finally:
            connection.execute("SET search_path TO public")
            connection.execute("RESET enable_seqscan")
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
    return {
        "port": database["port"],
        "vector_version": version,
        "dimension": settings.embedding_dimension,
        "application_rows": app_rows,
        "synthetic_nearest_and_hnsw": True,
    }


def verify_environment(
    settings: Settings,
    environment: str,
    values: dict[str, Any],
    other: dict[str, Any],
    result: dict[str, Any],
) -> None:
    names = values["names"]
    s3 = client("s3", settings)
    versions = {}
    for label, bucket in values["buckets"].items():
        if s3.get_bucket_versioning(Bucket=bucket).get("Status") != "Enabled":
            raise RuntimeError("Bucket versioning differs from configuration")
        key = f"phase5/{uuid4().hex}.txt"
        first = s3.put_object(Bucket=bucket, Key=key, Body=b"first")
        second = s3.put_object(Bucket=bucket, Key=key, Body=b"second")
        if first.get("VersionId") == second.get("VersionId") or not first.get("VersionId"):
            raise RuntimeError("S3 versions were not distinct")
        if (
            s3.get_object(Bucket=bucket, Key=key, VersionId=first["VersionId"])["Body"].read()
            != b"first"
        ):
            raise RuntimeError("S3 previous version was not preserved")
        for response in (first, second):
            s3.delete_object(Bucket=bucket, Key=key, VersionId=response["VersionId"])
        versions[label] = True
    result["s3_version_roundtrips"] = versions
    result["database"] = verify_database(settings, values, terraform_inputs(ROOT))
    iam, lambdas, logs = (client(service, settings) for service in ("iam", "lambda", "logs"))
    roles = {}
    for stage, name in names["functions"].items():
        config = lambdas.get_function_configuration(FunctionName=name)
        if config["Runtime"] != "python3.12" or config.get("Environment", {}).get("Variables"):
            raise RuntimeError("Unexpected runtime or provisioned environment secrets")
        policy = iam.get_role_policy(
            RoleName=names["roles"][stage], PolicyName=names["policies"][stage]
        )["PolicyDocument"]
        if isinstance(policy, str):
            policy = json.loads(policy)
        if any(statement["Resource"] == "*" for statement in policy["Statement"]):
            raise RuntimeError("Unscoped IAM resource")
        group = logs.describe_log_groups(logGroupNamePrefix=f"/aws/lambda/{name}")["logGroups"][0]
        if group["retentionInDays"] != (7 if environment == "dev" else 30):
            raise RuntimeError("Log retention differs from environment")
        roles[stage] = config["Role"]
    result["lambda_roles_and_retention"] = True
    response = lambdas.invoke(
        FunctionName=names["functions"]["query"], Payload=b'{"httpMethod":"POST"}'
    )
    if json.loads(response["Payload"].read()).get("statusCode") != 501 or response.get(
        "FunctionError"
    ):
        raise RuntimeError("Query scaffold did not return explicit 501")
    require_local_endpoint(settings.aws_endpoint_url)
    parsed = urlsplit(values["api_url"])
    if f"{parsed.scheme}://{parsed.netloc}" != settings.aws_endpoint_url.rstrip("/"):
        raise ValueError("API output is not on the configured local endpoint")
    http = httpx.post(values["api_url"], json={"question": "Phase 5 scaffold probe"}, timeout=150)
    if http.status_code != 501 or http.json().get("status") != "not_implemented":
        raise RuntimeError("API did not invoke the query scaffold")
    result["query_lambda_status"] = 501
    result["api_status"] = http.status_code
    functions = client("stepfunctions", settings)
    definition = json.loads(
        functions.describe_state_machine(stateMachineArn=values["workflow_arn"])["definition"]
    )
    if definition["StartAt"] != "Parse" or {
        state["Resource"] for state in definition["States"].values()
    } != {values["functions"][stage] for stage in ("parse", "chunk", "embed")}:
        raise RuntimeError("Workflow references differ from deployed functions")
    execution = functions.start_execution(
        stateMachineArn=values["workflow_arn"],
        name=f"phase5-{uuid4().hex}",
        input=json.dumps({"bucket": values["buckets"]["raw"], "key": "public-document.html"}),
    )["executionArn"]
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        state = functions.describe_execution(executionArn=execution)
        if state["status"] != "RUNNING":
            break
        time.sleep(1)
    else:
        raise TimeoutError("Scaffold workflow did not terminate")
    if state["status"] != "FAILED":
        raise RuntimeError("Unimplemented ingestion should fail explicitly")
    result["scaffold_workflow_status"] = state["status"]
    resources = [
        f"arn:aws:s3:::{values['buckets']['raw']}/probe",
        f"arn:aws:s3:::{other['buckets']['raw']}/probe",
    ]
    simulation = iam.simulate_principal_policy(
        PolicySourceArn=roles["parse"], ActionNames=["s3:GetObject"], ResourceArns=resources
    )["EvaluationResults"]
    decisions = {item["EvalResourceName"]: item["EvalDecision"] for item in simulation}
    if decisions.get(resources[0]) != "allowed" or decisions.get(resources[1]) != "implicitDeny":
        raise RuntimeError("IAM simulation did not isolate environment buckets")
    result["iam_simulation"] = {
        "own_raw": decisions[resources[0]],
        "other_raw": decisions[resources[1]],
    }
    sts = client("sts", settings)
    try:
        sts.assume_role(RoleArn=roles["parse"], RoleSessionName="phase5-trust-probe")
    except ClientError as error:
        if error.response["Error"]["Code"] != "AccessDenied":
            raise
        result["lambda_role_human_assume"] = "AccessDenied"
    else:
        raise RuntimeError("Lambda service role unexpectedly trusted the admin caller")
    credentials = sts.assume_role(
        RoleArn=values["authorization_role_arn"], RoleSessionName="phase5-probe"
    )["Credentials"]
    assumed_s3 = client("s3", settings, credentials)
    key = f"phase5/{uuid4().hex}.txt"
    created = []
    try:
        for target in (values, other):
            bucket = target["buckets"]["raw"]
            response = s3.put_object(Bucket=bucket, Key=key, Body=b"authorization probe")
            created.append((bucket, response["VersionId"]))
        own = assumed_s3.get_object(Bucket=values["buckets"]["raw"], Key=key)["Body"].read()
        if own != b"authorization probe":
            raise RuntimeError("Allowed own-bucket read failed")
        result["own_environment_read"] = "allowed"
        try:
            assumed_s3.get_object(Bucket=other["buckets"]["raw"], Key=key)["Body"].close()
        except ClientError as error:
            if error.response["Error"]["Code"] != "AccessDenied":
                raise
            result["cross_environment_read"] = "AccessDenied"
        else:
            raise RuntimeError("IAM enforcement did not deny a cross-environment read")
    finally:
        for bucket, version in created:
            s3.delete_object(Bucket=bucket, Key=key, VersionId=version)


def main() -> None:
    settings = Settings()
    report: dict[str, Any] = {
        "run_id": uuid4().hex,
        "kind": "infrastructure",
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "environments": {},
        "embedding_requests": 0,
        "chat_requests": 0,
    }
    path = ROOT / "data" / "runs" / f"{report['run_id']}.json"
    try:
        configurations = {name: outputs(name) for name in ("dev", "prod")}
        for environment, values in configurations.items():
            result: dict[str, Any] = {}
            report["environments"][environment] = result
            verify_environment(
                settings,
                environment,
                values,
                configurations["prod" if environment == "dev" else "dev"],
                result,
            )
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
