# Legal AI dataset starter pack

Dataset processing runs on GitHub-hosted Actions runners. Nothing is downloaded to your laptop by this workflow.

## What is included

`manifest.json` lists 10 dataset entries/configurations for prototyping:
- LexGLUE: SCOTUS, CaseHOLD, LEDGAR, EURLEX, Unfair ToS, ECtHR Article Classification A, ECtHR Article Classification B
- CUAD
- LegalBench-RAG
- BillSum

The script requests up to 10 rows per entry by default and truncates long string fields to keep samples manageable. It writes one JSONL file per successful dataset and a `download_report.json` provenance/failure report.

## Run it in GitHub

1. Open the repository's **Actions** tab.
2. Choose **Prepare legal AI dataset samples**.
3. Select **Run workflow** and choose 5, 10, or 25 rows per dataset.
4. When the workflow finishes, check the run status and the report.

The workflow now attempts to commit generated samples and `download_report.json` into `datasets/generated/` on the branch that triggered the run. The files remain in Git history and are available from the repository. It also uploads an artifact retained for 14 days as a backup. If repository branch protection or permissions block the push, the commit step will fail and the workflow log will explain why.

## Important license and data cautions

- This is a small sample pack, not a mirror of the full datasets.
- A workflow run can complete with a failed status if an individual source cannot be fetched. Check `download_report.json` for exact status, row counts, and errors.
- Read each current dataset card and original-source terms before using, redistributing, or training on samples. A dataset collection can contain source material under different licenses; do not infer a blanket license from a repository name.
- Treat LegalBench-RAG samples as evaluation-only until the terms of their underlying sources have been verified.
- This workflow is intended for public benchmark data only. Never add confidential case files, client data, credentials, or API keys.
- Dataset examples are research/evaluation material, not legal advice.

## Files

- `manifest.json`: dataset IDs, configurations, source URLs, and license-review notes.
- `generated/`: committed sample JSONL files and `download_report.json` after a successful push.
- `../scripts/download_legal_datasets.py`: bounded streaming sample downloader.
- `../.github/workflows/legal-datasets.yml`: cloud workflow and automatic sample commit.
