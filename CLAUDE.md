# Project notes for Claude

- Commit and push as the repository owner: author `maracman
  <82516491+maracman@users.noreply.github.com>`. Use the noreply address,
  never the personal gmail, in anything public. Never add Co-Authored-By
  trailers to commits.
- This project has been in development since 2023 (Llama-2-era notebook);
  this repository only dates from March 2025. Do not treat the initial
  commit date as the project's age.
- The app runs under waitress and does not reload: restart it after source
  changes, and verify against the running server before spending on runs.
- Studies read `GOALGRAPH_BASE`; run a second app instance on another port
  rather than sharing :5000.
