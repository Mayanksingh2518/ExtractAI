"""Stage 13: the harder realistic FAKE documents, classified and extracted with the real model.

The cases live in scripts/evaluate_realistic.py, which also prints a field-by-field report
and can compare DPI and max_pages settings.
"""

import pytest

from app.pipelines.registry import PipelineRegistry
from app.services.classifier import DocumentClassifier
from app.utils.pdf import to_page_images
from scripts.evaluate_realistic import CASES, _matches, _same_person

pytestmark = [pytest.mark.anyio, pytest.mark.model]


@pytest.mark.parametrize("name, doc_type, owner, expected", CASES, ids=[c[0] for c in CASES])
async def test_realistic_document(name, doc_type, owner, expected, ollama, samples, settings, tmp_path):
    pages = await to_page_images(samples / name, tmp_path, settings.pdf_render_dpi, settings.max_pdf_pages)
    result = await DocumentClassifier(ollama).classify(pages)
    assert result.documentType is doc_type, result.documentName
    assert _same_person(result.ownerName, owner)
    data = (await PipelineRegistry.build(ollama).extract(doc_type, pages)).model_dump()
    assert data.keys() == expected.keys()
    assert [k for k, v in expected.items() if not _matches(data[k], v)] == []
