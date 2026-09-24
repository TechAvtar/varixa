# Verixa Evidence Engine

## Purpose
Convert heterogeneous technical observations into a consistent evidence model.

## Evidence object

```json
{
  "category": "metadata",
  "level": "STRONG",
  "claim": "The file contains an editing software tag.",
  "source": "exiftool",
  "confidence": 0.92,
  "details": {
    "software": "Example Editor"
  }
}
```

## Evidence levels

### VERIFIED
Directly established by cryptographic or deterministic evidence.

Examples:
- SHA-256 exact identity
- valid cryptographic provenance signature

### STRONG
Strong technical observation with meaningful evidentiary value.

Examples:
- explicit editing software metadata
- multiple independent forensic anomalies

### PROBABLE
Evidence supports an interpretation but uncertainty remains.

### POSSIBLE
A signal worth considering but insufficient alone.

### UNKNOWN
The system cannot establish the fact.

## Initial rules

| Observation | Level |
|---|---|
| Valid C2PA signature | VERIFIED |
| C2PA signing certificate chains to an anchor on the configured trust list (separate record from validity) | VERIFIED |
| C2PA signing certificate not on the trust list | UNKNOWN (never a manipulation signal) |
| Signed C2PA declaration (digital source type, training/mining permission, creator identity) with a valid signature | STRONG (POSSIBLE when the signature does not validate; a declaration is verified as stated, not as true) |
| C2PA ingredient with recorded validation failures | POSSIBLE |
| Signed source type disagrees with metadata source type; manifest signed before its ingredient | conflict record (UNKNOWN), both sides retained |
| Exact SHA-256 match | VERIFIED |
| EXIF software tag | STRONG |
| Multiple independent forensic anomalies | STRONG |
| High calibrated AI detector signal | PROBABLE |
| Medium AI detector signal | POSSIBLE |
| Single ELA anomaly | POSSIBLE |
| Reverse search match | POSSIBLE |
| High pHash similarity | POSSIBLE |
| Missing metadata | UNKNOWN |

Thresholds must be configurable, not hardcoded throughout the application.

## Independence
Do not double-count highly correlated signals.

Example:
- ELA
- JPEG block anomaly
- compression artifact

may be related and should not automatically become three independent strong indicators.

## Evidence conflicts
If evidence conflicts:
- retain both
- show conflict
- lower synthesis confidence
- never silently discard contradictory evidence

## Evidence provenance
Every evidence record should point to:
- source subsystem
- raw observation ID or provider call
- timestamp
- provider/model version where relevant

## LLM rules
The LLM is a synthesis layer only.

It cannot:
- create evidence
- change evidence levels
- invent timestamps
- invent previous versions
- infer hidden metadata
- declare certainty unsupported by the evidence

## Summary template
The report should answer:
1. What is directly verified?
2. What technical signals were found?
3. What signals are probabilistic?
4. What evidence conflicts?
5. What remains unknown?
6. What additional evidence would improve confidence?
