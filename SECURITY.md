# Security Policy

## Supported versions

Etch is pre-1.0. Security fixes land on `main`; the supported version is the
latest commit on `main`.

| Version | Supported |
|---|---|
| latest on `main` | ✅ |
| anything older | ❌ (upgrade) |

## Reporting a vulnerability

**Do not open a public issue for a security vulnerability.**

Use GitHub's **private vulnerability reporting** on this repo
(Security tab → "Report a vulnerability"). Reports are triaged by the
maintainer; expect an acknowledgment within 7 days.

Please include:
- what the vulnerability is and where (file + line if you have it),
- steps to reproduce (a minimal scene graph or tool call is ideal),
- what you think the impact is (e.g. sandbox escape via SVG, auth bypass,
  dependency with a known CVE).

## Scope notes

- The render pipeline executes no untrusted code: scenes are data (JSON), and
  SVG output is generated, never parsed from untrusted input.
- `assets_upload` stores bytes and never executes them; still, don't feed it
  anything you wouldn't save to disk.
- Dependencies are pinned in `engine/requirements.txt`. If you spot a pinned
  dependency with a known CVE, that's in scope — report it.
