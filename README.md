# Pipeline ETL Serverless — AWS Lambda, S3, IAM

---

## Présentation du Projet

Ce projet met en place un **pipeline ETL automatisé** (Extract, Transform, Load) en utilisant les services AWS simulés localement via **LocalStack**. Quand un fichier CSV est déposé dans un bucket S3, une fonction Lambda Python se déclenche automatiquement, traite les données, et écrit les résultats dans des zones distinctes du bucket.

---

## Architecture

```
transactions.csv
      |
      v
  S3 : raw/                   ← dépôt du fichier source
      |
      | (événement ObjectCreated)
      v
  AWS Lambda                  ← traitement ETL Python
      |
      |── processed/year=YYYY/month=MM/day=DD/  ← données nettoyées (.csv.gz)
      |── analytics/audit/                       ← journal JSON du traitement
      └── error/                                 ← erreurs de schéma
      
  IAM Role: lambda-role       ← contrôle des permissions
```

---

## Structure du Projet

```
aws/
├── process_dataset.py        ← code principal de la Lambda
├── function/                 ← dépendances Python (pandas, boto3)
├── function.zip              ← archive déployée sur Lambda
├── trust-policy.json         ← politique de confiance IAM
├── s3-policy.json            ← permissions S3 pour la Lambda
├── s3-notification.json      ← configuration du trigger S3
├── test-event.json           ← événement de test manuel
├── transactions.csv          ← fichier de données de test
└── docker-compose.yml        ← configuration LocalStack
```

---

## Prérequis

| Outil | Version | Usage |
|-------|---------|-------|
| Docker Desktop | >= 4.x | Exécuter LocalStack |
| Python | >= 3.10 | Développer la Lambda |
| AWS CLI | >= 2.x | Interagir avec LocalStack |
| Node.js | >= 16.x | Optionnel (pptxgenjs) |

---

## Installation et Démarrage

### 1. Lancer LocalStack

Fichier `docker-compose.yml` :

```yaml
services:
  localstack:
    image: localstack/localstack
    ports:
      - "4566:4566"
    environment:
      - SERVICES=s3,lambda,iam
      - DEBUG=1
      - LAMBDA_RUNTIME_ENVIRONMENT_TIMEOUT=120
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - localstack-data:/var/lib/localstack

volumes:
  localstack-data:
```

```powershell
docker compose up -d
```

> **Important sur Windows** : Ne pas ajouter `LAMBDA_DOCKER_NETWORK=host` — incompatible avec Docker Desktop Windows.

### 2. Créer le Bucket S3

```powershell
aws --endpoint-url=http://localhost:4566 s3 mb s3://tp-ing4-ds-s3

aws --endpoint-url=http://localhost:4566 s3api put-object --bucket tp-ing4-ds-s3 --key raw/
aws --endpoint-url=http://localhost:4566 s3api put-object --bucket tp-ing4-ds-s3 --key processed/
aws --endpoint-url=http://localhost:4566 s3api put-object --bucket tp-ing4-ds-s3 --key analytics/audit/
aws --endpoint-url=http://localhost:4566 s3api put-object --bucket tp-ing4-ds-s3 --key error/
```

### 3. Configurer IAM

#### trust-policy.json
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "lambda.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}
```

#### s3-policy.json
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
    "Resource": [
      "arn:aws:s3:::tp-ing4-ds-s3",
      "arn:aws:s3:::tp-ing4-ds-s3/*"
    ]
  }]
}
```

```powershell
aws --endpoint-url=http://localhost:4566 iam create-role `
  --role-name lambda-role `
  --assume-role-policy-document file://trust-policy.json

aws --endpoint-url=http://localhost:4566 iam put-role-policy `
  --role-name lambda-role `
  --policy-name lambda-s3-policy `
  --policy-document file://s3-policy.json
```

### 4. Préparer et Déployer la Lambda

#### Installer les dépendances (version Linux — obligatoire sur Windows)

```powershell
pip install pandas boto3 -t function\ `
  --platform manylinux2014_x86_64 `
  --implementation cp `
  --python-version 3.10 `
  --only-binary=:all: `
  --no-compile
```

> **Pourquoi `--platform manylinux2014_x86_64` ?**
> La Lambda s'exécute dans un conteneur Linux. Sur Windows, `pip install` installe par défaut des binaires Windows qui ne fonctionnent pas dans Lambda. Cette option force l'installation de la version Linux.

#### Réduire la taille du ZIP

```powershell
Remove-Item -Recurse -Force function\*.dist-info
Get-ChildItem -Path function -Recurse -Filter "__pycache__" | Remove-Item -Recurse -Force
Remove-Item -Recurse -Force function\botocore\data\ec2
```

#### Créer le ZIP

```powershell
cd function
Compress-Archive -Path * -DestinationPath ..\function.zip -Force
cd ..
```

> Le ZIP doit faire **moins de 52 MB** (limite de LocalStack).

#### Déployer

```powershell
aws --endpoint-url=http://localhost:4566 lambda create-function `
  --function-name process-dataset `
  --runtime python3.10 `
  --handler process_dataset.lambda_handler `
  --zip-file fileb://function.zip `
  --role arn:aws:iam::000000000000:role/lambda-role `
  --timeout 60
```

### 5. Configurer le Trigger S3

#### s3-notification.json
```json
{
  "LambdaFunctionConfigurations": [{
    "Id": "trigger-process-dataset",
    "LambdaFunctionArn": "arn:aws:lambda:us-east-1:000000000000:function:process-dataset",
    "Events": ["s3:ObjectCreated:*"],
    "Filter": {
      "Key": {
        "FilterRules": [
          { "Name": "prefix", "Value": "raw/" },
          { "Name": "suffix", "Value": ".csv" }
        ]
      }
    }
  }]
}
```

```powershell
# Ajouter la permission à S3 d'invoquer la Lambda
aws --endpoint-url=http://localhost:4566 lambda add-permission `
  --function-name process-dataset `
  --statement-id s3-trigger `
  --action lambda:InvokeFunction `
  --principal s3.amazonaws.com `
  --source-arn arn:aws:s3:::tp-ing4-ds-s3 `
  --region us-east-1

# Appliquer la notification
aws --endpoint-url=http://localhost:4566 s3api put-bucket-notification-configuration `
  --bucket tp-ing4-ds-s3 `
  --notification-configuration file://s3-notification.json
```

---

## Explication Détaillée du Code Lambda

### Point d'entrée

```python
def lambda_handler(event, context):
```

- `event` : contient les informations de l'événement S3 (nom du bucket, clé du fichier)
- `context` : métadonnées d'exécution (temps restant, identifiant de requête)

### Connexion à S3

```python
s3 = boto3.client(
    "s3",
    endpoint_url=os.environ.get("AWS_ENDPOINT_URL", "http://172.22.0.2:4566"),
    ...
)
```

> **Pourquoi `AWS_ENDPOINT_URL` ?**
> Depuis l'intérieur du conteneur Lambda, `localhost` ne pointe pas vers LocalStack. LocalStack injecte automatiquement la variable `AWS_ENDPOINT_URL` avec la bonne adresse IP du réseau Docker. On utilise `os.environ.get()` pour la lire dynamiquement.

### Étape 1 — Lecture de l'événement

```python
record = event["Records"][0]
bucket = record["s3"]["bucket"]["name"]   # "tp-ing4-ds-s3"
key = record["s3"]["object"]["key"]       # "raw/transactions.csv"
```

S3 envoie un objet JSON avec la liste des fichiers créés. On extrait le premier enregistrement pour obtenir le nom du bucket et la clé (chemin) du fichier.

### Étape 2 — Filtrage

```python
if not key.startswith("raw/") or not key.endswith(".csv"):
    return {"statusCode": 400, "body": "Fichier ignoré"}
```

On ignore les fichiers qui ne sont pas dans `raw/` ou qui ne sont pas au format `.csv`. Cela évite de traiter les fichiers écrits par la Lambda elle-même dans `processed/`.

### Étape 3 — Validation du schéma

```python
REQUIRED_COLUMNS = ["InvoiceNo", "StockCode", "Description", "Quantity",
                    "InvoiceDate", "UnitPrice", "CustomerID", "Country"]

missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
if missing:
    s3.put_object(Bucket=bucket, Key="error/schema_error.json", Body=error_body)
    return {"statusCode": 400, "body": "Schéma invalide"}
```

On vérifie que toutes les colonnes attendues sont présentes. Si une colonne manque, on écrit un fichier d'erreur dans `error/` avec la liste des colonnes manquantes.

### Étape 4 — Nettoyage des données

```python
df = df.dropna(subset=["InvoiceNo", "StockCode", "Quantity", "UnitPrice"])
df = df[df["Quantity"] > 0]
df = df[df["UnitPrice"] >= 0]
df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"], errors="coerce")
df = df.dropna(subset=["InvoiceDate"])
```

- `dropna()` supprime les lignes avec des valeurs manquantes dans les colonnes critiques
- `Quantity > 0` élimine les retours de marchandises (quantités négatives)
- `UnitPrice >= 0` élimine les prix aberrants
- `pd.to_datetime()` convertit les dates en type datetime, puis `dropna()` élimine les dates non parsables

### Étape 5 — Compression et Partitionnement

```python
run_date = datetime.utcnow()
out_key = f"processed/year={run_date:%Y}/month={run_date:%m}/day={run_date:%d}/transactions_clean.csv.gz"

csv_buffer = io.StringIO()
df.to_csv(csv_buffer, index=False)

gz_buffer = io.BytesIO()
with gzip.GzipFile(fileobj=gz_buffer, mode="wb") as gz_file:
    gz_file.write(csv_buffer.getvalue().encode("utf-8"))

s3.put_object(Bucket=bucket, Key=out_key, Body=gz_buffer.getvalue())
```

- Le DataFrame est d'abord écrit en CSV dans un buffer mémoire (`StringIO`)
- Puis compressé en `.gz` dans un buffer binaire (`BytesIO`)
- Le chemin de sortie est partitionné par date pour faciliter les analyses futures

### Étape 6 — Journalisation (Audit)

```python
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
```

Un fichier JSON est créé dans `analytics/audit/` avec toutes les informations du traitement : fichier d'entrée, fichier de sortie, nombre de lignes conservées, et horodatage.

---

## Test du Pipeline

### Test automatique (via trigger S3)

```powershell
aws --endpoint-url=http://localhost:4566 s3 cp transactions.csv s3://tp-ing4-ds-s3/raw/transactions.csv
```

### Test manuel (invocation directe)

#### test-event.json
```json
{
  "Records": [{
    "s3": {
      "bucket": { "name": "tp-ing4-ds-s3" },
      "object": { "key": "raw/transactions.csv" }
    }
  }]
}
```

```powershell
aws --endpoint-url=http://localhost:4566 lambda invoke `
  --function-name process-dataset `
  --cli-binary-format raw-in-base64-out `
  --payload file://test-event.json response.json

type response.json
```

### Vérification des résultats

```powershell
aws --endpoint-url=http://localhost:4566 s3 ls s3://tp-ing4-ds-s3/ --recursive
```

Résultat attendu :
```
raw/transactions.csv                                         ← fichier source
processed/year=2026/month=04/day=25/transactions_clean.csv.gz  ← données traitées
analytics/audit/audit_20260425_HHMMSS.json                  ← journal
```

---

## Résultats Obtenus

| Métrique | Valeur |
|----------|--------|
| Lignes dans le fichier source | 20 |
| Lignes après nettoyage | 19 |
| Taille du fichier compressé | 542 octets |
| StatusCode retourné | 200 |
| Fichiers créés dans S3 | 3 |

Réponse JSON de la Lambda :
```json
{
  "statusCode": 200,
  "body": {
    "input_file": "raw/transactions.csv",
    "output_file": "processed/year=2026/month=04/day=25/transactions_clean.csv.gz",
    "rows_after_cleaning": 19,
    "processed_at": "2026-04-25T14:03:39.407671Z"
  }
}
```

---

## Problèmes Rencontrés et Solutions

| Problème | Cause | Solution |
|----------|-------|----------|
| `State: Failed` sur Lambda | Docker socket non monté | Ajouter volume `/var/run/docker.sock` |
| Timeout au démarrage | `LAMBDA_DOCKER_NETWORK=host` incompatible Windows | Supprimer cette variable |
| ZIP > 52MB | Trop de fichiers inclus | Supprimer `.dist-info`, `__pycache__`, `botocore/data/ec2` |
| `os.add_dll_directory` error | pandas Windows dans conteneur Linux | `--platform manylinux2014_x86_64` |
| `EndpointConnectionError` | `localhost` ≠ LocalStack depuis le conteneur | Utiliser `AWS_ENDPOINT_URL` de l'environnement |
| Port 4566 déjà utilisé | Ancien conteneur encore actif | `docker stop` + `docker rm` du conteneur |

---

## Bonnes Pratiques Appliquées

- **Principe du moindre privilège** : IAM accorde uniquement les permissions nécessaires (`GetObject`, `PutObject`, `ListBucket`) sur ce bucket précis
- **Séparation des zones** : `raw/`, `processed/`, `analytics/audit/` et `error/` sont clairement distincts
- **Journalisation** : chaque traitement est tracé dans un fichier audit JSON
- **Filtrage des événements** : le trigger S3 est limité au préfixe `raw/` et au suffixe `.csv`
- **Partitionnement** : les données sont organisées par `year/month/day` pour faciliter les analyses futures
- **Gestion des erreurs** : les fichiers invalides sont redirigés vers `error/` avec un message descriptif

---

## Commandes Utiles

```powershell
# Voir les logs LocalStack
docker logs aws-localstack-1 --tail 100

# Lister tous les fichiers du bucket
aws --endpoint-url=http://localhost:4566 s3 ls s3://tp-ing4-ds-s3/ --recursive

# Vérifier l'état de la Lambda
aws --endpoint-url=http://localhost:4566 lambda get-function --function-name process-dataset

# Redémarrer LocalStack
docker compose down && docker compose up -d
```

---

