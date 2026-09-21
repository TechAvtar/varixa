# Verixa UI/UX Specification

## Design direction
Modern investigative SaaS:
- clean
- technical
- trustworthy
- restrained
- evidence-first
- high information density without visual clutter

Avoid "AI magic" aesthetics that imply certainty.

## Main screens

### 1. Landing page
- product statement
- upload CTA
- supported modalities
- evidence methodology
- privacy statement
- limitations

### 2. Dashboard
Cards:
- total analyses
- image analyses
- text analyses
- recent analyses
- usage

### 3. New Analysis
Two primary modes:
- Analyze Image
- Analyze Text

Image:
- drag/drop
- preview
- file details
- start analysis

Text:
- paste area
- upload option
- character count
- start analysis

### 4. Processing
Show stages:
- validating
- extracting metadata
- checking provenance
- running forensics
- checking AI signals
- searching sources
- building evidence
- generating report

Do not fake progress percentages. Use real stage status.

### 5. Report
Header:
- content type
- analysis ID
- created time
- overall evidence summary

Tabs:
- Overview
- Metadata
- Provenance
- AI Analysis
- Forensics
- Matches
- Timeline

### Evidence card
Show:
- level
- claim
- source
- confidence
- timestamp
- technical details
- limitation

### 6. Timeline
Vertical timeline with:
- event
- date/time
- evidence level
- source

### 7. Export
- PDF
- printable report
- JSON later

## Colors
Use a restrained neutral palette. Evidence levels may use semantic color, but never use color alone.

## Accessibility
- keyboard navigation
- visible focus
- adequate contrast
- labels for controls
- screen-reader-friendly status
- no color-only meaning

## Empty states
Explain what is unavailable and why.

Example:
"No embedded provenance credentials were found. This does not establish whether the file was edited."

## Error states
Use actionable messages:
- invalid file
- unsupported format
- provider unavailable
- analysis failed
- report generation failed

## Responsive
Desktop-first but usable on tablet/mobile browser.

## UX rule
The interface should always separate:
**Fact → Signal → Interpretation → Unknown**
