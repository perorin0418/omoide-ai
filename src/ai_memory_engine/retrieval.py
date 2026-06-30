from __future__ import annotations

from .analytics import DuckDBAnalyticsStore
from .context_builder import ContextBuilder
from .embeddings import HashingEmbeddingProvider
from .entity_extraction import GraphHit, InMemoryGraphStore, LadybugGraphStore, SimpleEntityExtractor
from .markdown_store import MarkdownMemoryStore
from .models import SearchResult
from .utils import tokenize
from .vector_store import InMemoryVectorStore, LanceDBVectorStore


class HybridRetriever:
    def __init__(
        self,
        *,
        store: MarkdownMemoryStore,
        embedder: HashingEmbeddingProvider,
        vector_store: InMemoryVectorStore | LanceDBVectorStore,
        graph_store: InMemoryGraphStore | LadybugGraphStore,
        entity_extractor: SimpleEntityExtractor,
        analytics: DuckDBAnalyticsStore,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.vector_store = vector_store
        self.graph_store = graph_store
        self.entity_extractor = entity_extractor
        self.analytics = analytics
        self.context_builder = ContextBuilder()

    def semantic_search(self, query: str, top_k: int, session_id: str = "") -> list[SearchResult]:
        results = self._semantic_results(query, top_k)
        self.analytics.log_search(session_id, query, len(results), {"mode": "semantic"})
        self._record_usage(results, session_id, query)
        return results

    def graph_search(self, query: str, top_k: int, session_id: str = "") -> list[SearchResult]:
        results = self._graph_results(query, top_k)
        entities = self.entity_extractor.extract(query)
        self.analytics.log_search(session_id, query, len(results), {"mode": "graph", "entities": entities})
        self._record_usage(results, session_id, query)
        return results

    def hybrid_search(self, query: str, top_k: int, session_id: str = "") -> list[SearchResult]:
        semantic = self._semantic_results(query, top_k)
        graph = self._graph_results(query, top_k)
        keyword = self._keyword_results(query, top_k)
        merged: dict[str, SearchResult] = {}
        for result in semantic:
            merged[result.memory.memory_id] = SearchResult(result.memory, result.score, "semantic")
        for result in graph:
            if result.memory.memory_id in merged:
                existing = merged[result.memory.memory_id]
                existing.score += result.score
                existing.reason = "hybrid"
            else:
                merged[result.memory.memory_id] = SearchResult(result.memory, result.score, "graph")
        for result in keyword:
            if result.memory.memory_id in merged:
                existing = merged[result.memory.memory_id]
                existing.score += result.score
                existing.reason = "hybrid"
            else:
                merged[result.memory.memory_id] = SearchResult(result.memory, result.score, "keyword")
        results = sorted(merged.values(), key=lambda item: item.score, reverse=True)[:top_k]
        self.analytics.log_search(session_id, query, len(results), {"mode": "hybrid"})
        self._record_usage(results, session_id, query)
        return results

    def build_context_block(
        self,
        results: list[SearchResult],
        open_questions: list[str],
        memory_mode: str = "dynamic",
    ) -> str:
        return self.context_builder.build(results, open_questions, memory_mode=memory_mode)

    def _semantic_results(self, query: str, top_k: int) -> list[SearchResult]:
        embedding = self.embedder.embed(query)
        hits = self.vector_store.search(embedding, top_k)
        return self._hydrate_vector_hits(hits)

    def _graph_results(self, query: str, top_k: int) -> list[SearchResult]:
        entities = self.entity_extractor.extract(query)
        hits = self.graph_store.search(entities, top_k)
        return self._hydrate_graph_hits(hits)

    def _keyword_results(self, query: str, top_k: int) -> list[SearchResult]:
        expanded = set(tokenize(query))
        if "言語" in query:
            expanded.update({"runtime", "implementation_runtime"})
        if "正本" in query or "真実源" in query:
            expanded.update({"source", "truth", "source_of_truth", "markdown"})
        if "クラウド" in query:
            expanded.update({"cloud", "offline"})
        results: list[SearchResult] = []
        for record in self.store.list_records():
            corpus = " ".join(
                [
                    record.title.lower(),
                    record.summary.lower(),
                    record.subject.lower(),
                    record.value.lower(),
                    " ".join(record.tags).lower(),
                ]
            )
            corpus_tokens = set(tokenize(corpus))
            overlap = len(expanded.intersection(corpus_tokens))
            if overlap:
                results.append(SearchResult(record, float(overlap), "keyword"))
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]

    def _hydrate_vector_hits(self, hits: list) -> list[SearchResult]:
        results: list[SearchResult] = []
        for hit in hits:
            record = self.store.get_record(hit.memory_id)
            if record:
                results.append(SearchResult(record, hit.score, "semantic"))
        return results

    def _hydrate_graph_hits(self, hits: list[GraphHit]) -> list[SearchResult]:
        results: list[SearchResult] = []
        for hit in hits:
            record = self.store.get_record(hit.memory_id)
            if record:
                results.append(SearchResult(record, hit.score, "graph"))
        return results

    def _record_usage(self, results: list[SearchResult], session_id: str, query: str) -> None:
        for result in results:
            self.analytics.record_memory_usage(result.memory.memory_id, session_id, query, result.score)
