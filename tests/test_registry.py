from federalgraph.sources.registry import SourceRegistry


class ExampleExtractor:
    name = "example"

    def extract(self):
        return []


def test_registry_registers_and_returns_source() -> None:
    registry = SourceRegistry()
    extractor = ExampleExtractor()
    registry.register(extractor)

    assert list(registry.names()) == ["example"]
    assert registry.get("example") is extractor
