from app.core import config
from app.services import embeddings


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_nemotron_embedding_sends_passage_input_type(monkeypatch):
    monkeypatch.setattr(config.settings, "embedding_api_key", "test-key")
    monkeypatch.setattr(config.settings, "embedding_api_base_url", "https://integrate.api.nvidia.com/v1")
    monkeypatch.setattr(config.settings, "embedding_model", "nvidia/nemotron-3-embed-1b")
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["payload"] = json
        return FakeResponse({"data": [{"index": 0, "embedding": [0.1, 0.2]}]})

    monkeypatch.setattr(embeddings.httpx, "post", fake_post)
    vectors = embeddings.embed_texts(["contract passage"])

    assert captured["url"] == "https://integrate.api.nvidia.com/v1/embeddings"
    assert captured["payload"]["input_type"] == "passage"
    assert vectors == [[0.1, 0.2]]


def test_nemotron_embedding_sends_query_input_type(monkeypatch):
    monkeypatch.setattr(config.settings, "embedding_api_key", "test-key")
    monkeypatch.setattr(config.settings, "embedding_api_base_url", "https://integrate.api.nvidia.com/v1")
    monkeypatch.setattr(config.settings, "embedding_model", "nvidia/nemotron-3-embed-1b")
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["payload"] = json
        return FakeResponse({"data": [{"index": 0, "embedding": [0.3, 0.4]}]})

    monkeypatch.setattr(embeddings.httpx, "post", fake_post)
    vectors = embeddings.embed_texts(["query"], input_type="query")

    assert captured["payload"]["input_type"] == "query"
    assert vectors == [[0.3, 0.4]]


def test_embedding_batches_large_documents_and_preserves_order(monkeypatch):
    monkeypatch.setattr(config.settings, "embedding_api_key", "test-key")
    monkeypatch.setattr(config.settings, "embedding_api_base_url", "https://example.test/v1")
    monkeypatch.setattr(config.settings, "embedding_model", "test-model")
    batch_sizes = []

    def fake_post(url, headers, json, timeout):
        batch_sizes.append(len(json["input"]))
        return FakeResponse({
            "data": [
                {"index": index, "embedding": [float(text.split("-")[1]), 1.0]}
                for index, text in enumerate(json["input"])
            ]
        })

    monkeypatch.setattr(embeddings.httpx, "post", fake_post)
    texts = [f"chunk-{index}" for index in range(70)]
    vectors = embeddings.embed_texts(texts)

    assert batch_sizes == [32, 32, 6]
    assert len(vectors) == len(texts)
    assert [vector[0] for vector in vectors] == [float(index) for index in range(70)]

[executed on device: NIDHIN (47c41d4b-ef60-4c09-8668-4cc72e1eff30)]