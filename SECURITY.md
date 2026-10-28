# Security Notes

This project is open source. Open source code can be forked and modified by anyone, so you cannot fully prevent modified builds.

## What is protected in this codebase

- Sound file names are sanitized before use.
- Only approved audio extensions are accepted (`.wav`, `.mp3`, `.ogg`).
- Path traversal and absolute-path playback are blocked in runtime sound loading.
- Sound path resolution is constrained to the app sound folders.
- Single-instance lock prevents concurrent process conflicts.
- Donation address integrity is checked at startup.

## Secure release checklist

1. Pin all dependencies in `requirements.txt` (no unpinned packages).
2. Build from a clean, trusted machine.
3. Use signed git tags and signed release artifacts.
4. Publish SHA-256 checksums for release files.
5. Keep VirusTotal link/checksum in release notes.
6. Never distribute binaries from forks or unknown mirrors.

## Operational recommendations

- Accept pull requests only after code review.
- Require branch protection for `main`.
- Require CI checks before merge.
- Rotate API keys/secrets immediately if leaked.

## Report a vulnerability

Open a private security report or contact the maintainer directly.
Do not publish exploit details before a fix is available.
