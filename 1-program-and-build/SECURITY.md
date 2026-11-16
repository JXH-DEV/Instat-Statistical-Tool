# Security policy

INSTAT Explorer runs on the user's own computer, listens on `127.0.0.1` only, and asks for an access token on every request. What it sends
over the network, how it treats hostile files and what remains are described in [docs/SECURITY_AND_PRIVACY.md](docs/SECURITY_AND_PRIVACY.md).

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private vulnerability reporting (Security tab of the repository, "Report a
vulnerability"), or write to the repository owner. Include the version (`instat --version`), what you did and what happened.

Only the latest release is supported.
