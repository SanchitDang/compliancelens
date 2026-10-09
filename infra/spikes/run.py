import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZipFile

import boto3
import psycopg
from botocore.config import Config
from botocore.exceptions import ClientError
from psycopg import sql

from compliancelens.config import Settings

TABLE = "compliancelens_spike_chunks"
INDEX = "compliancelens_spike_chunks_embedding_hnsw"
ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "data" / "spikes"


def client(service: str, settings: Settings) -> Any:
    return boto3.client(
        service,
        endpoint_url=settings.aws_endpoint_url,
        region_name=settings.aws_default_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key.get_secret_value(),
        config=Config(
            connect_timeout=5,
            read_timeout=180,
            retries={"max_attempts": 0},
            s3={"addressing_style": "path"},
        ),
    )


def is_missing(error: ClientError, code: str) -> bool:
    return error.response["Error"]["Code"] == code


def check_s3(settings: Settings, names: dict[str, str], verify: bool) -> dict[str, Any]:
    s3 = client("s3", settings)
    s3.head_bucket(Bucket=names["raw_bucket"])
    bucket = names["sdk_bucket"]
    if not verify:
        try:
            options = {}
            if settings.aws_default_region != "us-east-1":
                options["CreateBucketConfiguration"] = {
                    "LocationConstraint": settings.aws_default_region
                }
            s3.create_bucket(Bucket=bucket, **options)
        except ClientError as error:
            if not is_missing(error, "BucketAlreadyOwnedByYou"):
                raise
        s3.put_object(Bucket=bucket, Key="phase-0.txt", Body=b"ComplianceLens persistence probe")
    content = s3.get_object(Bucket=bucket, Key="phase-0.txt")["Body"].read()
    if content != b"ComplianceLens persistence probe":
        raise RuntimeError("S3 round trip did not preserve content")
    return {"terraform_bucket_verified": True, "sdk_bucket_roundtrip": True}


def database_endpoint(settings: Settings, identifier: str, verify: bool) -> dict[str, Any]:
    rds = client("rds", settings)
    try:
        rds.describe_db_instances(DBInstanceIdentifier=identifier)
    except ClientError as error:
        if verify or not is_missing(error, "DBInstanceNotFound"):
            raise
        rds.create_db_instance(
            DBInstanceIdentifier=identifier,
            DBInstanceClass="db.t3.micro",
            Engine="postgres",
            AllocatedStorage=5,
            DBName=settings.database_name,
            MasterUsername=settings.database_user,
            MasterUserPassword=settings.database_password.get_secret_value(),
        )
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        instance = rds.describe_db_instances(DBInstanceIdentifier=identifier)["DBInstances"][0]
        if instance["DBInstanceStatus"] == "available" and instance.get("Endpoint"):
            return instance["Endpoint"]
        time.sleep(1)
    raise TimeoutError("RDS did not become available within 180 seconds")


def connect_database(settings: Settings, endpoint: dict[str, Any]) -> psycopg.Connection:
    return psycopg.connect(
        host=urlsplit(settings.aws_endpoint_url).hostname,
        port=endpoint["Port"],
        dbname=settings.database_name,
        user=settings.database_user,
        password=settings.database_password.get_secret_value(),
        connect_timeout=10,
        sslmode="disable",
    )


def check_vectors(settings: Settings, endpoint: dict[str, Any], verify: bool) -> dict[str, Any]:
    dimension = settings.embedding_dimension
    vector = "[" + ",".join(["1"] + ["0"] * (dimension - 1)) + "]"
    opposite = "[" + ",".join(["-1"] + ["0"] * (dimension - 1)) + "]"
    with connect_database(settings, endpoint) as connection:
        with connection.cursor() as cursor:
            if not verify:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cursor.execute(
                    sql.SQL(
                        "CREATE TABLE IF NOT EXISTS {} ("
                        "id integer PRIMARY KEY, content_hash text NOT NULL, "
                        "embedding_backend text NOT NULL, embedding_model text NOT NULL, "
                        "embedding_dimension integer NOT NULL, embedding vector({}) NOT NULL)"
                    ).format(sql.Identifier(TABLE), sql.Literal(dimension))
                )
            cursor.execute(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = %s::regclass AND attname = 'embedding'",
                (TABLE,),
            )
            if cursor.fetchone()[0] != f"vector({dimension})":
                raise RuntimeError("Spike table dimension differs; use a fresh spike table")
            if not verify:
                for identifier, value in [(1, vector), (2, opposite)]:
                    cursor.execute(
                        sql.SQL(
                            "INSERT INTO {} VALUES (%s, %s, %s, %s, %s, %s::vector) "
                            "ON CONFLICT (id) DO NOTHING"
                        ).format(sql.Identifier(TABLE)),
                        (
                            identifier,
                            hashlib.sha256(value.encode()).hexdigest(),
                            "synthetic",
                            "synthetic-spike",
                            dimension,
                            value,
                        ),
                    )
                cursor.execute(
                    sql.SQL(
                        "CREATE INDEX IF NOT EXISTS {} ON {} USING hnsw "
                        "(embedding vector_cosine_ops)"
                    ).format(sql.Identifier(INDEX), sql.Identifier(TABLE))
                )
            cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            version = cursor.fetchone()[0]
            cursor.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(TABLE)))
            count = cursor.fetchone()[0]
            if count != 2:
                raise RuntimeError("Expected two persisted synthetic vector rows")
            cursor.execute("SET LOCAL enable_seqscan = off")
            query = sql.SQL("SELECT id FROM {} ORDER BY embedding <=> %s::vector LIMIT 1").format(
                sql.Identifier(TABLE)
            )
            cursor.execute(query, (vector,))
            if cursor.fetchone()[0] != 1:
                raise RuntimeError("Vector similarity query returned the wrong nearest row")
            cursor.execute(sql.SQL("EXPLAIN ") + query, (vector,))
            plan = "\n".join(row[0] for row in cursor.fetchall())
            if INDEX not in plan:
                raise RuntimeError("HNSW index was not used in the forced-index probe")
    return {
        "vector_version": version,
        "dimension": dimension,
        "synthetic_rows": count,
        "nearest_id": 1,
        "hnsw_plan": "\n".join(plan.splitlines()[:2]),
        "embeddings_generated": False,
    }


def lambda_package() -> bytes:
    dependencies = ARTIFACTS / "lambda"
    if not (dependencies / "pg8000").is_dir():
        raise RuntimeError("Install the registered pg8000 Lambda dependencies first")
    archive = ARTIFACTS / "lambda.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
        bundle.write(Path(__file__).with_name("lambda_handler.py"), "lambda_handler.py")
        for path in sorted(dependencies.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                bundle.write(path, path.relative_to(dependencies))
    return archive.read_bytes()


def check_lambda(
    settings: Settings, names: dict[str, str], endpoint: dict[str, Any], verify: bool
) -> dict[str, Any]:
    functions = client("lambda", settings)
    if not verify:
        iam = client("iam", settings)
        try:
            role = iam.get_role(RoleName=names["lambda_role"])["Role"]
        except ClientError as error:
            if not is_missing(error, "NoSuchEntity"):
                raise
            role = iam.create_role(
                RoleName=names["lambda_role"],
                AssumeRolePolicyDocument=json.dumps(
                    {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Principal": {"Service": "lambda.amazonaws.com"},
                                "Action": "sts:AssumeRole",
                            }
                        ],
                    }
                ),
            )["Role"]
        environment = {
            "Variables": {
                "DATABASE_HOST": endpoint["Address"],
                "DATABASE_PORT": str(endpoint["Port"]),
                "DATABASE_USER": settings.database_user,
                "DATABASE_PASSWORD": settings.database_password.get_secret_value(),
                "DATABASE_NAME": settings.database_name,
            }
        }
        package = lambda_package()
        try:
            functions.get_function(FunctionName=names["lambda_function"])
        except ClientError as error:
            if not is_missing(error, "ResourceNotFoundException"):
                raise
            functions.create_function(
                FunctionName=names["lambda_function"],
                Runtime="python3.12",
                Architectures=["arm64"],
                Role=role["Arn"],
                Handler="lambda_handler.handler",
                Code={"ZipFile": package},
                Environment=environment,
                Timeout=30,
                MemorySize=128,
            )
        else:
            functions.update_function_code(FunctionName=names["lambda_function"], ZipFile=package)
            functions.update_function_configuration(
                FunctionName=names["lambda_function"], Environment=environment
            )
        functions.get_waiter("function_active_v2").wait(
            FunctionName=names["lambda_function"], WaiterConfig={"Delay": 1, "MaxAttempts": 60}
        )
    response = functions.invoke(FunctionName=names["lambda_function"], Payload=b"{}")
    payload = json.loads(response["Payload"].read())
    if response.get("FunctionError") or payload.get("sql_result") != 1:
        raise RuntimeError("Lambda SQL connectivity probe failed; inspect local Floci logs")
    if not payload.get("vector_version"):
        raise RuntimeError("Lambda could not see the vector extension")
    return {"sql_result": payload["sql_result"], "vector_version": payload["vector_version"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-persistence", action="store_true")
    arguments = parser.parse_args()
    settings = Settings(_env_file=ROOT / ".env")
    names = json.loads((ARTIFACTS / "terraform-outputs.json").read_text())["names"]["value"]
    result = {
        "time_utc": datetime.now(UTC).isoformat(),
        "mode": "verify-persistence" if arguments.verify_persistence else "create-and-probe",
    }
    result["s3"] = check_s3(settings, names, arguments.verify_persistence)
    print("PASS: Terraform bucket verified and boto3 S3 object read succeeded", flush=True)
    endpoint = database_endpoint(settings, names["database"], arguments.verify_persistence)
    result["vectors"] = check_vectors(settings, endpoint, arguments.verify_persistence)
    print("PASS: RDS pgvector, synthetic similarity search, and HNSW index", flush=True)
    result["lambda"] = check_lambda(settings, names, endpoint, arguments.verify_persistence)
    print("PASS: Lambda executed SQL against RDS and found pgvector", flush=True)
    result["inference_requests"] = 0
    filename = "persistence-results.json" if arguments.verify_persistence else "results.json"
    (ARTIFACTS / filename).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
