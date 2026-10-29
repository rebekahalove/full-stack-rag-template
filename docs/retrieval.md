# Retrieval and chunking

## Baseline strategy

The MVP uses structure-aware chunking and hybrid retrieval. The default values are starting points
for a general-purpose corpus and remain configurable:

| Setting | Default |
| --- | ---: |
| Minimum chunk | 150 tokens |
| Target chunk | 600 tokens |
| Maximum chunk | 900 tokens |
| Overlap | 80 tokens |
| Candidates per retrieval method | 20 |
| Final context chunks | 6 |
| Embedding dimensions | 1,536 |

Tune these settings with representative documents, questions, and expected supporting passages.
Larger numbers are not inherently better.

## Extraction by format

- **Markdown:** headings define section paths; paragraphs, lists, tables, and fenced code are
  structural blocks.
- **DOCX:** heading styles, paragraphs, lists, and tables are retained in source order where the
  document model permits it.
- **PDF:** pages and text blocks supply location metadata. Repeated headers/footers, hyphenation,
  and reading order should be normalized conservatively.

Scanned/image-only PDFs require OCR and are outside the MVP. PDF page numbers are metadata, not
mandatory chunk boundaries.

## Chunk construction

Chunking prefers semantic boundaries over fixed slices. Small adjacent blocks are combined toward
the target. Oversized blocks are split on token boundaries. Tables, lists, and code blocks remain
intact where the maximum permits; oversized structures may be token-split in the MVP.

Fragments below the minimum are merged with a compatible neighbor when the maximum allows. Each
chunk after the first may receive up to the configured overlap from the preceding chunk, bounded
by the maximum size. Retrieval deduplication limits the resulting repetition.

Each chunk has two text forms:

- **original content**, used for citations and answer context;
- **enriched embedding content**, which prepends useful document title and heading context.

Enrichment improves retrieval without misrepresenting source quotations.

## Required metadata

Metadata remains attached throughout extraction, storage, retrieval, and citation:

- document and chunk IDs;
- original filename and media type;
- stable sequence index;
- heading path;
- page start/end when available;
- character/block offsets when reliable;
- content type and token count;
- parser/chunker version and format-specific JSON metadata;
- embedding model/configuration used to create the vector.

Unknown locations are `null`, never invented. Page numbering should match the user-visible PDF.

## Candidate generation

Semantic search embeds the question and performs document-scoped vector similarity. Keyword search
uses PostgreSQL full-text search and is especially useful for exact names, identifiers, and rare
terms. Both methods fetch up to 20 candidates after applying the selected document filter.

Candidate ranks are combined using reciprocal rank fusion, which avoids treating incomparable
vector and text scores as though they shared a scale. Duplicate and heavily overlapping chunks are
collapsed. Adjacent chunks may be expanded or merged when needed, while preserving all source
ranges. The top six chunks form the default answer context.

An optional reranker can be introduced behind an interface, but it is not required for the MVP.

## Grounding and citations

The generation prompt labels each context block with an internal source key and instructs the model
to use only supplied evidence. Retrieved document content is quoted as untrusted data. The service
maps model references back to stored metadata and returns an excerpt, filename, heading, pages, and
score for each source.

The service returns `insufficient_evidence: true` when retrieval returns no candidates or the
answer provider determines the available text does not support the question. This decision should
be evaluated empirically; provider prose alone is not a reliable confidence signal.

## Evaluation

Maintain a small versioned set of representative documents and question cases containing:

- direct factual lookup;
- exact keyword/identifier lookup;
- answers split near chunk boundaries;
- table and list lookup;
- multi-passage synthesis;
- a deliberately unanswerable question;
- extraction edge cases for each format.

Track retrieval hit rate/recall at `k`, citation correctness, grounded-answer correctness,
insufficient-evidence precision, latency, and context token count. Tune extraction and chunking
before compensating with a larger final context.

## Known limitations

The baseline does not include OCR, query rewriting, multi-document retrieval, learned reranking,
or automated answer-quality scoring. Complex PDF layouts and merged DOCX table cells may lose
structure. Full-text configuration is language-dependent. The local single-user design does not
provide tenant isolation or access-control filters.
