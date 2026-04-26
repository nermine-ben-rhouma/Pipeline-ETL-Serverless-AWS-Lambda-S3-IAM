import json
import io
import gzip
from datetime import datetime
import boto3
import pandas as pd
import os

s3 = boto3.client(
    "s3",
    endpoint_url=os.environ.get("AWS_ENDPOINT_URL", "http://172.22.0.2:4566"),
    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
    region_name="us-east-1"
)

REQUIRED_COLUMNS = [
    "InvoiceNo", "StockCode", "Description", "Quantity",
    "InvoiceDate", "UnitPrice", "CustomerID", "Country"
]

def lambda_handler(event, context):
    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    key = record["s3"]["object"]["key"]

    if not key.startswith("raw/") or not key.endswith(".csv"):
        return {"statusCode": 400, "body": "Fichier ignoré"}

    response = s3.get_object(Bucket=bucket, Key=key)
    df = pd.read_csv(response["Body"])

    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        error_body = json.dumps({
            "file": key,
            "error": "Colonnes manquantes",
            "missing_columns": missing
        }).encode("utf-8")
        s3.put_object(Bucket=bucket, Key="error/schema_error.json", Body=error_body)
        return {"statusCode": 400, "body": "Schéma invalide"}

    df = df.dropna(subset=["InvoiceNo", "StockCode", "Quantity", "UnitPrice"])
    df = df[df["Quantity"] > 0]
    df = df[df["UnitPrice"] >= 0]
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"], errors="coerce")
    df = df.dropna(subset=["InvoiceDate"])

    run_date = datetime.utcnow()
    out_key = (
        f"processed/year={run_date:%Y}/month={run_date:%m}/"
        f"day={run_date:%d}/transactions_clean.csv.gz"
    )

    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    gz_buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=gz_buffer, mode="wb") as gz_file:
        gz_file.write(csv_buffer.getvalue().encode("utf-8"))
    s3.put_object(Bucket=bucket, Key=out_key, Body=gz_buffer.getvalue())

    audit = {
        "input_file": key,
        "output_file": out_key,
        "rows_after_cleaning": int(len(df)),
        "processed_at": run_date.isoformat() + "Z"
    }
    s3.put_object(
        Bucket=bucket,
        Key=f"analytics/audit/audit_{run_date:%Y%m%d_%H%M%S}.json",
        Body=json.dumps(audit, indent=2).encode("utf-8")
    )

    return {"statusCode": 200, "body": json.dumps(audit)}