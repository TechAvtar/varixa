# Verixa MVP Product Scope

## Vision
Verixa provides evidence-based analysis of digital content so a user can understand what can be established about an image or text, what signals suggest, and what remains unknown.

## Target users
- journalists and researchers
- legal/compliance teams
- investigators
- content moderation teams
- cybersecurity/trust teams
- businesses verifying submitted media
- advanced consumers

## MVP user journey

### Image
Upload image → create analysis → process evidence → view report → inspect metadata/provenance/AI/forensics/matches/timeline → export report.

### Text
Paste or upload text → create analysis → process evidence → view report → inspect AI-generation signals/source similarity/text statistics/timeline → export report.

## MVP image capabilities
- secure upload
- file validation
- SHA-256
- file type and dimensions
- EXIF/XMP/IPTC/ICC extraction
- software/creation/editing tags
- C2PA/content credentials inspection
- pHash/dHash/aHash
- image statistics
- ELA
- compression/resampling indicators
- noise consistency indicators
- basic copy-move/tamper heuristics
- AI detector through provider adapter
- source/reverse-search provider adapter
- evidence normalization
- confidence/evidence levels
- timeline reconstruction from available evidence
- AI-generated explanation
- report/PDF

## MVP text capabilities
- paste text
- upload supported text/document formats where practical
- encoding normalization
- language detection
- character/word/sentence statistics
- structural/style statistics
- AI-generation detector through provider adapter
- phrase/source matching provider adapter
- text fingerprint
- embeddings/similarity
- evidence normalization
- AI explanation
- report/PDF

## Evidence levels
- VERIFIED
- STRONG
- PROBABLE
- POSSIBLE
- UNKNOWN

These are evidence classifications, not claims of authorship or factual truth.

## Explicit limitations
- An AI detector cannot prove authorship.
- Absence of C2PA does not prove manipulation or AI generation.
- EXIF software tags indicate recorded metadata, not necessarily complete edit history.
- A reverse-search result is evidence of similarity/source discovery, not automatically proof of origin.
- A final image normally cannot reveal a previous version unless historical evidence is available.
- Forensic heuristics can produce false positives.
- Provider outputs may change over time and must be versioned.

## Non-goals
- owning a web-scale reverse image index
- training a proprietary foundation model
- automatic legal conclusions
- guaranteed AI authorship detection
- recovering deleted image history
- decrypting protected content
- bypassing access controls
- video/audio analysis
- social-media scraping at scale
