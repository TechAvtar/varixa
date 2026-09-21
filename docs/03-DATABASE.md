# Verixa Database Specification

Use PostgreSQL. UUID primary keys. UTC timestamps.

## users
- id UUID PK
- email VARCHAR UNIQUE NOT NULL
- name VARCHAR
- password_hash VARCHAR NULL
- role VARCHAR NOT NULL DEFAULT 'user'
- created_at TIMESTAMPTZ
- updated_at TIMESTAMPTZ

## analyses
- id UUID PK
- user_id UUID FK users.id
- type VARCHAR NOT NULL
- status VARCHAR NOT NULL
- title VARCHAR
- error_code VARCHAR
- error_message TEXT
- retention_at TIMESTAMPTZ
- created_at TIMESTAMPTZ
- completed_at TIMESTAMPTZ

Indexes:
- user_id
- status
- created_at
- (user_id, created_at)

## analysis_files
- id UUID PK
- analysis_id UUID FK
- object_key VARCHAR NOT NULL
- original_filename VARCHAR
- mime_type VARCHAR
- size_bytes BIGINT
- sha256 VARCHAR NOT NULL
- width INTEGER NULL
- height INTEGER NULL
- created_at TIMESTAMPTZ

## image_metadata
- id UUID PK
- analysis_id UUID UNIQUE FK
- exif_json JSONB
- xmp_json JSONB
- iptc_json JSONB
- icc_json JSONB
- software VARCHAR
- camera_make VARCHAR
- camera_model VARCHAR
- captured_at TIMESTAMPTZ NULL
- modified_at TIMESTAMPTZ NULL
- created_at TIMESTAMPTZ

## image_provenance
- id UUID PK
- analysis_id UUID UNIQUE FK
- has_c2pa BOOLEAN
- valid_signature BOOLEAN
- manifests_json JSONB
- claims_json JSONB
- signer VARCHAR
- raw_json JSONB
- created_at TIMESTAMPTZ

## image_ai_detection
- id UUID PK
- analysis_id UUID UNIQUE FK
- provider VARCHAR
- model VARCHAR
- score NUMERIC
- label VARCHAR
- raw_json JSONB
- provider_version VARCHAR
- created_at TIMESTAMPTZ

## image_forensics
- id UUID PK
- analysis_id UUID UNIQUE FK
- ela_json JSONB
- noise_json JSONB
- compression_json JSONB
- resampling_json JSONB
- copy_move_json JSONB
- statistics_json JSONB
- created_at TIMESTAMPTZ

## image_fingerprints
- id UUID PK
- analysis_id UUID UNIQUE FK
- sha256 VARCHAR
- md5 VARCHAR
- phash VARCHAR
- dhash VARCHAR
- ahash VARCHAR
- embedding_id VARCHAR NULL
- created_at TIMESTAMPTZ

## reverse_matches
- id UUID PK
- analysis_id UUID FK
- provider VARCHAR
- url TEXT
- title TEXT
- similarity NUMERIC NULL
- discovered_at TIMESTAMPTZ
- raw_json JSONB

## text_analysis
- id UUID PK
- analysis_id UUID UNIQUE FK
- language VARCHAR
- word_count INTEGER
- character_count INTEGER
- sentence_count INTEGER
- paragraph_count INTEGER
- structure_json JSONB
- ai_detection_json JSONB
- source_matches_json JSONB
- embedding_ref VARCHAR NULL
- created_at TIMESTAMPTZ

## text_fingerprints
- id UUID PK
- analysis_id UUID UNIQUE FK
- sha256 VARCHAR
- normalized_sha256 VARCHAR
- created_at TIMESTAMPTZ

## evidence
- id UUID PK
- analysis_id UUID FK
- category VARCHAR NOT NULL
- level VARCHAR NOT NULL
- claim TEXT NOT NULL
- source VARCHAR NOT NULL
- confidence NUMERIC NULL
- details JSONB
- created_at TIMESTAMPTZ

## timeline_events
- id UUID PK
- analysis_id UUID FK
- event_type VARCHAR
- event_time TIMESTAMPTZ NULL
- certainty VARCHAR
- description TEXT
- source_evidence_ids JSONB
- created_at TIMESTAMPTZ

## reports
- id UUID PK
- analysis_id UUID FK
- format VARCHAR
- object_key VARCHAR NULL
- summary_json JSONB
- created_at TIMESTAMPTZ

## provider_calls
- id UUID PK
- analysis_id UUID FK
- provider VARCHAR
- operation VARCHAR
- request_id VARCHAR NULL
- status VARCHAR
- latency_ms INTEGER NULL
- estimated_cost NUMERIC NULL
- request_hash VARCHAR NULL
- response_json JSONB NULL
- error_json JSONB NULL
- created_at TIMESTAMPTZ

## usage
- id UUID PK
- user_id UUID FK
- period_start DATE
- analyses_count INTEGER DEFAULT 0
- provider_cost NUMERIC DEFAULT 0
- storage_bytes BIGINT DEFAULT 0
- UNIQUE(user_id, period_start)

## Data rules
- Never store secrets in JSONB.
- Keep raw provider output for auditability, subject to privacy/retention rules.
- Do not overwrite original evidence during reprocessing.
- Use new provider/model versions for new results.
