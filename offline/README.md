# TWC Workbench Offline Installation

This folder deliberately has two operator scripts.

## 1. Offline-Prep.ps1

Run this on a connected Windows machine that matches the offline host's CPU
architecture and Python major/minor version. It:

- runs the backend tests unless `-SkipTests` is supplied;
- installs the locked frontend dependencies and builds `frontend/dist`;
- downloads/builds every required Python wheel;
- verifies the wheelhouse using `pip --no-index` in a clean virtual environment;
- copies the runtime application without secrets or database contents;
- records SHA-256 for every bundled file; and
- produces an extracted bundle, a ZIP, and a ZIP checksum under
  `offline/artifacts` by default.

```powershell
powershell -ExecutionPolicy Bypass -File .\offline\Offline-Prep.ps1
```

Use `-SkipFrontendInstall` only when `frontend/node_modules` already matches the
checked-in lockfile. The production frontend is always rebuilt.

For an enterprise package mirror, pass `-PipIndexUrl`. For TLS inspection or a
private CA, pass its PEM bundle through `-PackageCaFile`; the same file is used
for pip and npm. `-AllowUntrustedPackageHosts` is an explicit last-resort option
for the public PyPI hosts and npm install, and prints a warning when used.

## 2. Offline-Installer.ps1

Transfer the generated ZIP and `.sha256` file into the offline environment,
verify the outer checksum using the enclave's approved process, extract the
entire ZIP, and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\Offline-Installer.ps1
```

The installer:

- verifies every file against `offline-manifest.json` before changing the host;
- requires the same Python major/minor version and architecture used by Prep;
- installs Python packages only from the bundled wheelhouse with `--no-index`;
- deploys the prebuilt frontend, so Node.js is not needed offline;
- preserves an existing `backend/.env` and `backend/data` during upgrades;
- generates a cryptographically random `SESSION_SECRET` on first install; and
- creates `Start-Workbench.ps1` in the installation folder.

The default installation is `%LOCALAPPDATA%\TWCWorkbench`. Override it with
`-InstallPath`. Use `-StartAfterInstall` to launch immediately.

Before production use, edit `backend/.env` in the installed folder and configure
the approved TWC server, AuthServer callback, TLS, public origin, and other
environment-specific values.
