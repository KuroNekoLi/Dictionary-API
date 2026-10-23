# Dictionary API VPS deployment
GitHub Actions builds and deploys this API to the VPS when code is pushed to `main`. The container is replaced with the new image; dictionary data stays on the VPS persistent volume.
