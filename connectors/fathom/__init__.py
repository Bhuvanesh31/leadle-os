"""Fathom ingestion (REST API; script).

Lands recording metadata first, then transcripts (chunked). Transcripts are
the heaviest payload by token volume in the system — a 1-hour call is
roughly 10K words. Chunking and embedding strategy is decided in P6 after
we observe actual transcript volume in docs/data-shape/fathom.md.

The Phantom Detector and Sales Insight Digest both depend on transcripts
being available — they're the foundation for transcript-mining agents.
"""
