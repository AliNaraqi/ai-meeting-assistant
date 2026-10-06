# Security Policy

## Supported versions

This project is under active portfolio development. Security fixes are applied to the latest `main` branch only.

## Reporting a vulnerability

Please report security issues privately.

1. Prefer emailing the repository maintainer (see the GitHub profile or repository security advisories once enabled).
2. If GitHub private vulnerability reporting is enabled for this repo, use **Security → Advisories → Report a vulnerability**.
3. Include steps to reproduce, impact, and whether audio/transcript data could be exposed.

Do **not** open a public issue for:

- Authentication or authorization bypasses
- Storage or signed-URL leaks
- Prompt-injection paths that cause unsafe actions
- Secret exposure in logs, CI, or client bundles

You should receive an acknowledgment within a few days when contact channels are monitored. Please give a reasonable window for a fix before public disclosure.

## Safe handling expectations

- Never commit `.env` files, API keys, JWTs, or service-role credentials.
- Never commit real meeting recordings or personally identifiable transcripts.
- Use synthetic fixtures under `evals/` for demos and tests.
- Log IDs and metrics only — not transcript text, participant emails, or storage URLs.
- Assume all uploaded media and transcript content is sensitive.

## Known product boundaries

- Browser recording captures local microphone audio unless the user separately provides a file.
- The app is not a legal, medical, or compliance-grade records system.
- Users must obtain informed consent before recording other people.

## Dependency and supply-chain checks

Pull requests run lint and tests in GitHub Actions. Dependabot is configured for Python, npm, GitHub Actions, and Docker base images. Please keep dependency bumps focused and review changelogs for security-related releases.
