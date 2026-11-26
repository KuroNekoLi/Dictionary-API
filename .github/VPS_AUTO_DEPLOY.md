# Dictionary API VPS deployment
GitHub Actions builds and deploys this API to the VPS when code is pushed to `main`. The container is replaced with the new image; dictionary data stays on the VPS persistent volume.

The Actions SSH key is intentionally restricted to `/usr/local/sbin/ci-deploy-wrapper dictionary-api`; do not pass an SSH remote command. The VPS `migration-load-image` dispatcher handles the image load, checks available disk space, backs up `wordnet.db`, merges ECDICT, Word Atlas, Complete_Dictionary, and cached records into that file, checks SQLite integrity and source row counts, then recreates only the Dictionary API service and performs a local lookup smoke check. If disk space or verification fails, the existing service is not restarted.
