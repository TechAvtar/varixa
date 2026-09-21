# Verixa Security and Privacy

## Threat model
Protect:
- uploaded files
- user identity
- provider credentials
- reports
- provider responses
- analysis history

## File security
- private object storage
- signed URLs with short expiry
- server-side validation
- magic-byte validation
- size limits
- decompression-bomb protection
- malware scanning where available
- random object keys
- never execute uploaded files

## Authentication
Use secure session/token handling.

Every resource query must include ownership authorization.

Never rely on frontend IDs for authorization.

## Secrets
Store in environment/secret manager.

Never:
- commit secrets
- log secrets
- return secrets in API
- place secrets in frontend bundles

## Logging
Safe:
- request ID
- analysis ID
- status
- duration
- provider name

Unsafe:
- raw uploaded content
- full user text
- access tokens
- signed URLs
- API keys

## Retention
Default proposal:
- uploaded raw content: 24 hours unless saved
- analysis records: retained according to product plan
- provider raw responses: retain only as needed for auditability and privacy

Make retention configurable.

## Deletion
Deleting an analysis should:
1. mark record deleted
2. revoke access
3. remove object storage content
4. remove derived artifacts where required
5. preserve only minimum audit information if legally required

## Privacy
Do not send user content to external providers unless:
- required for the selected feature
- disclosed to the user
- allowed by applicable provider terms

Provider data handling should be documented.

## Prompt injection
Treat uploaded text as untrusted data.
Never allow analyzed content to override system/developer instructions.

## SSRF
Do not fetch arbitrary URLs supplied by users without strict validation and an allowlist/proxy design.

## Security tests
Test:
- IDOR
- unauthorized report access
- malicious file upload
- oversized upload
- malformed image
- prompt injection
- provider error handling
- signed URL expiry
