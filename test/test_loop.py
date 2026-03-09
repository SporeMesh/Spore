"""Tests for experiment loop metadata extraction."""

from spore.loop import _extract_metadata


class TestExtractMetadata:
    def test_extract_structured_metadata(self):
        response = """
Description: Increase the embedding LR from 0.6 to 0.8.
Hypothesis: A slightly faster embedding update should improve adaptation inside the time budget.

```python
print("hello")
```
"""
        description, hypothesis = _extract_metadata(response)
        assert description == "Increase the embedding LR from 0.6 to 0.8."
        assert hypothesis == (
            "A slightly faster embedding update should improve adaptation inside the time budget."
        )

    def test_extract_legacy_single_line_metadata(self):
        response = """
I increased the embedding LR from 0.6 to 0.8 because faster token adaptation should lower val_bpb.

```python
print("hello")
```
"""
        description, hypothesis = _extract_metadata(response)
        assert description == "I increased the embedding LR from 0.6 to 0.8"
        assert hypothesis == "faster token adaptation should lower val_bpb"
