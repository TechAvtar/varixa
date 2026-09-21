# Verixa API Contract

Base path: `/api/v1`

## POST /analysis/image
Accept multipart upload.

Returns:
```json
{
  "id": "uuid",
  "status": "queued",
  "type": "image"
}
```

## POST /analysis/text
Request:
```json
{
  "text": "content to analyze",
  "title": "optional title"
}
```

## GET /analysis/{id}
Returns analysis status and summary.

## GET /analysis/{id}/metadata
Returns normalized metadata.

## GET /analysis/{id}/provenance
Returns C2PA/content credential findings.

## GET /analysis/{id}/ai
Returns AI detection results with provider/model/version and limitations.

## GET /analysis/{id}/forensics
Returns forensic findings and artifacts.

## GET /analysis/{id}/matches
Returns reverse/source matches.

## GET /analysis/{id}/timeline
Returns evidence-derived timeline.

## POST /analysis/{id}/report
Request:
```json
{
  "format": "pdf"
}
```

## GET /reports/{id}
Returns report metadata.

## GET /reports/{id}/pdf
Returns a short-lived signed URL or streamed PDF.

## DELETE /analysis/{id}
Soft-delete analysis and schedule physical content deletion according to retention policy.

## Error format

```json
{
  "error": {
    "code": "INVALID_FILE",
    "message": "The uploaded file is not supported.",
    "request_id": "uuid"
  }
}
```

Never return stack traces to clients.

## Status
- queued
- processing
- completed
- failed

## Evidence response

```json
{
  "category": "provenance",
  "level": "VERIFIED",
  "claim": "A valid C2PA credential was detected.",
  "source": "c2pa",
  "confidence": 1.0,
  "details": {}
}
```

## Authorization
Every analysis endpoint must verify that the authenticated user owns the analysis or has explicit access.

## API principles
- version endpoints
- validate request bodies
- paginate lists
- cap upload size
- use request IDs
- return stable error codes
- never expose object storage keys unnecessarily
