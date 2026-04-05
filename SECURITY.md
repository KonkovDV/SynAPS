# Security Policy

## Scope

SynAPS is an active public research and engineering repository.

The repository should be treated as pre-production software and documentation, not as a validated industrial deployment artifact.

## Supported Versions

| Surface | Status | Notes |
| --- | --- | --- |
| current default branch (`master`) / active `0.1.x` line | best-effort security fixes | active development line |
| historical snapshots, unpublished experiments, generated artifacts | unsupported | no security-fix commitment |

## Reporting A Vulnerability

Do **not** disclose exploitable details in a public issue, pull request, benchmark artifact, or discussion thread.

Preferred reporting route:

1. use GitHub Private Vulnerability Reporting for the target public repository: `https://github.com/KonkovDV/SynAPS/security/advisories/new`;
2. if that route is not yet enabled during a publication rehearsal, pause public disclosure until the repository security settings are finished.

## Expected Response Windows

1. acknowledgement within 5 business days;
2. follow-up status update within 14 calendar days;
3. coordinated disclosure after a fix or mitigation path exists.

## Safe Disclosure Expectations

1. include affected file paths or surfaces when possible;
2. provide a minimal safe reproduction if one exists;
3. avoid posting secrets, private datasets, regulated data, or exploit payloads in public channels;
4. state whether the issue affects the current implementation, release packaging, or public technical claims.

## Repository Settings Counterpart

The publication baseline for this repository assumes:

1. GitHub Private Vulnerability Reporting is enabled;
2. maintainers watch `Security alerts` notifications;
3. secret scanning and push protection are enabled for the public repository.