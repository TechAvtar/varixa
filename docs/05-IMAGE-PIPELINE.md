# Verixa Image Analysis Pipeline

## Pipeline

```text
Upload
→ Validate
→ SHA-256
→ Store original
→ Metadata
→ C2PA
→ Fingerprints
→ Image statistics
→ Forensics
→ AI detector
→ Source/reverse search
→ Normalize evidence
→ Timeline
→ LLM explanation
→ Report
```

## 1. Validation
Accept common image types:
- JPEG
- PNG
- WebP
- TIFF where practical

Validate:
- MIME type
- magic bytes
- maximum file size
- decompression dimensions
- malformed files

Do not trust the filename or client-provided MIME type.

## 2. Hashing
Calculate SHA-256 immediately.
Use it as the primary content identity.

Also calculate:
- MD5 for compatibility only
- pHash
- dHash
- aHash

## 3. Metadata
Use ExifTool as the preferred extraction engine.

Normalize:
- camera
- lens
- capture time
- software
- modify time
- GPS presence
- XMP
- IPTC
- ICC
- orientation

Preserve raw output separately from normalized fields.

## 4. C2PA
Inspect manifests and credentials.

Record:
- presence
- signature validity
- signer
- claims
- actions
- timestamps
- source manifest data

A missing credential is UNKNOWN, not evidence of fraud.

## 5. Forensics
Implement MVP heuristics:
- ELA
- JPEG quantization/compression indicators
- noise consistency
- resampling/interpolation
- basic copy-move/tamper indicators
- image statistics

Each result must include:
- method
- observation
- confidence
- limitations

Avoid language such as "this proves manipulation."

## 6. AI detection
Call a configurable provider adapter.

Persist:
- provider
- model
- version
- score
- label
- timestamp
- raw response

Do not convert a detector score directly into a factual statement of authorship.

## 7. Reverse/source search
Use an external provider adapter.

Normalize:
- URL
- title
- similarity
- provider
- discovery time

A match should become POSSIBLE unless corroborated by stronger evidence.

## 8. Timeline
Construct timeline events from:
- C2PA timestamps
- capture timestamps
- metadata modification timestamps
- source discovery timestamps

Label each event:
- VERIFIED
- STRONG
- PROBABLE
- POSSIBLE
- UNKNOWN

## 9. AI explanation
The LLM receives structured evidence, not arbitrary hidden application state.

Prompt it to:
- summarize facts
- explain uncertainty
- identify conflicts
- avoid unsupported conclusions
- cite evidence IDs internally

The LLM must never invent metadata or provider results.
