# Evidence archives

The research ZIP retains every completed primary and HTTP episode, including the independent supplier SQLite databases, client database, event trace, visible history and scored outcome.

To keep the repository tree navigable, the thousands of per-episode files are stored as two compressed archives. From the study root, extract them before running the independent evidence audit:

```sh
tar -xzf results/eval-direct/episodes.tar.gz -C results/eval-direct
tar -xzf results/eval-http/episodes.tar.gz -C results/eval-http
python3 audit/verify_results.py
```

Both archives contain an `episodes/` directory. Existing scalar CSVs and manifests can be read without extraction. `results/paired-unknown-worlds/` retains the separate two-case diagnostic in expanded form.

`execution/interrupted-direct-run.tar.gz` preserves the excluded initial tool-interrupted attempt. Do not combine it with the scored 360-episode run. The HTTP manifest and retained execution logs document the interruption and continuation. Interrupted attempts are not extra independent observations.

`release.sha256` binds the files in this distribution. `protocol/frozen_manifest.json` separately records the pre-evaluation runtime/input freeze, not the later article or audits. Running the audit regenerates summary audit files from the archived evidence; it does not run a model or contact an external host.
