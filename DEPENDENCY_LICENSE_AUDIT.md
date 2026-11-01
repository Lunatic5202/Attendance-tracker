# Dependency license metadata audit

**Snapshot reviewed:** `frontend/package-lock.json`  
**Scope:** npm package metadata recorded in the committed lockfile; this is not a legal opinion or a complete asset-rights review.

## Inventory

The lockfile contains 115 package entries under `packages`. Every entry has a declared license field in the inspected snapshot.

| Declared license metadata | Package entries |
|---|---:|
| MIT | 107 |
| ISC | 5 |
| Apache-2.0 | 1 |
| CC-BY-4.0 | 1 |
| BSD-3-Clause | 1 |

## Python dependencies

The root `requirements.txt` is not represented by a resolved Python lockfile in this audit. The transitive dependency versions and license metadata remain unverified.

## Follow-up

1. Generate a reproducible Python dependency lock and license inventory.
2. Review face-recognition models, model weights, datasets, and camera-related assets separately.
3. Ensure no employee records, biometric templates, or private data are included in generated audit artifacts.
4. Regenerate this report whenever the npm lockfile changes.

**Limitations:** declared package metadata is not a substitute for actual license texts or notices. This report does not grant rights to employee or biometric data.
