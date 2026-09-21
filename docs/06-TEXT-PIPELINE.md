# Verixa Text Analysis Pipeline

## Pipeline

```text
Input
→ Normalize
→ Fingerprint
→ Language detection
→ Statistics
→ Structural analysis
→ AI detector
→ Source/phrase matching
→ Similarity
→ Evidence normalization
→ Timeline
→ LLM explanation
→ Report
```

## Input
MVP:
- pasted text
- TXT
- simple document extraction where reliable

Reject oversized inputs.

## Normalization
Keep both:
- original text
- normalized text

Normalization may include:
- Unicode normalization
- whitespace normalization
- line-ending normalization

Never destroy the original.

## Statistics
Calculate:
- characters
- words
- sentences
- paragraphs
- average sentence length
- vocabulary measures
- punctuation distribution
- repetition
- headings/structure where applicable

## AI detection
Provider adapter returns:
- score
- label
- model
- version
- raw response

Treat as probabilistic.

## Source matching
Search distinctive phrases through a configurable provider.

Record:
- phrase
- source
- URL
- similarity/relevance
- discovery time

Do not claim plagiarism from a single phrase match.

## Similarity
Generate normalized fingerprint and optional embeddings.

Support:
- exact normalized match
- near-duplicate match
- semantic similarity

## Text comparison
Later enhancement:
- compare two texts
- show additions/deletions
- identify semantic changes
- identify structural changes

Do not include full document comparison in MVP unless needed for the core report.

## LLM synthesis
The model receives structured statistics and evidence.
It must:
- explain signals
- distinguish detection from proof
- mention missing evidence
- avoid authorship claims
- avoid legal conclusions
