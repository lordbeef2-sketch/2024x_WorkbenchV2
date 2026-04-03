# TWC Swagger Diff Package

This package is for building a **true-source** Teamwork Cloud API dataset for:
- 2022x R2
- 2024x R3

It is designed for default installs where the main environment-specific difference is the server hostname.

## What this package does

1. Pulls Swagger/OpenAPI from live TWC servers.
2. Saves raw specs separately for 2022xR2 and 2024xR3.
3. Normalizes each spec into a contract-friendly summary.
4. Diffs the two versions.
5. Produces JSON and Markdown reports you can hand to GPT-5.4 XHigh.

## Recommended workflow

### Option A: pull directly from your live servers

Python:

```powershell
python scripts/build_twc_dataset.py \
  --v2022-url https://YOUR-2022-SERVER:8111/osmc/swagger \
  --v2024-url https://YOUR-2024-SERVER:8111/osmc/swagger \
  --outdir output \
  --insecure
```

PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/fetch_twc_swagger.ps1 \
  -V2022Url "https://YOUR-2022-SERVER:8111/osmc/swagger" \
  -V2024Url "https://YOUR-2024-SERVER:8111/osmc/swagger" \
  -OutDir "output/swagger/raw"
```

Then normalize + diff:

```powershell
python scripts/normalize_openapi.py output/swagger/raw/twc_2022xR2.json output/swagger/normalized/twc_2022xR2_normalized.json --label 2022xR2
python scripts/normalize_openapi.py output/swagger/raw/twc_2024xR3.json output/swagger/normalized/twc_2024xR3_normalized.json --label 2024xR3
python scripts/diff_openapi_versions.py \
  output/swagger/normalized/twc_2022xR2_normalized.json \
  output/swagger/normalized/twc_2024xR3_normalized.json \
  --out-json output/diffs/twc_diff.json \
  --out-md output/reports/twc_diff_report.md
```

### Option B: use the one-shot builder

```powershell
python scripts/build_twc_dataset.py \
  --v2022-url https://YOUR-2022-SERVER:8111/osmc/swagger \
  --v2024-url https://YOUR-2024-SERVER:8111/osmc/swagger \
  --outdir output \
  --insecure
```

## Files you will get

- `output/swagger/raw/twc_2022xR2.json`
- `output/swagger/raw/twc_2024xR3.json`
- `output/swagger/normalized/twc_2022xR2_normalized.json`
- `output/swagger/normalized/twc_2024xR3_normalized.json`
- `output/diffs/twc_diff.json`
- `output/reports/twc_diff_report.md`

## Notes

- `--insecure` disables SSL verification. Use it if your environment does not use a trusted certificate.
- The scripts support either JSON Swagger/OpenAPI responses or HTML pages that contain a link to the JSON spec.
- These tools do not invent endpoints. They only process what the source spec contains.
