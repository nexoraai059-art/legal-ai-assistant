# Legal AI dataset starter pack

All dataset processing runs on GitHub-hosted Actions runners. Nothing is downloaded to your laptop by this workflow.

## What is included

`manifest.json` lists 10 legal datasets / dataset configurations for prototyping:
- LexGLUE: SCOTUS, CaseHOLD, LEDGAR, EURLEX, Unfair ToS
- CUAD
- ContractNLI
- LegalBench-RAG
- BillSum
- Multi-LexSum

The script requests up to 10 rows per entry by default and truncates long string fields to keep the sample artifact manageable. It writes one JSONL file per dataset and a `download_report.json` provenance/failure report.

## Run it in GitHub

1. Open the repository's **Actions** tab.
2. Choose **Prepare legal AI dataset samples**.
3. Select **Run workflow** and choose 5, 10, or 25 rows per dataset.
4. Open the resulting workflow run and download the `legal-ai-dataset-samples` artifact.

The workflow also runs after relevant dataset-manifest/script changes. Artifacts are retained for 14 days. This keeps dataset files out of Git history and avoids bloating the source repository.

## Important license and data cautions

- This is a small sample pack, not a mirror of all full datasets.
- The workflow can fail for an individual source because dataset IDs, access requirements, schemas, or upstream hosting can change. Check `download_report.json` in the artifact for exact status and errors.
- Read the current dataset card and original-source terms before using, redistributing, or training on any dataset. A dataset collection can contain source material under different licenses; do not infer a blanket license from a repository name.
- LegalBench-RAG and Multi-LexSum may include source materials with additional restrictions. Treat the samples as evaluation-only until each source's rights are confirmed.
- Do not upload confidential case files, client data, credentials, or API keys into this public-data workflow.
- Dataset examples are research/evaluation material, not legal advice.

## Files

- `manifest.json`: dataset IDs, configurations, source URLs, and license-review notes.
- `../scripts/download_legal_datasets.py`: bounded streaming sample downloader.
- `../.github/workflows/legal-datasets.yml`: cloud workflow and artifact upload.
