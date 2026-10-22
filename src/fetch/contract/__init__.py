"""One delivery contract for every team.

Envelope shape matches what inresearch `fetchspec-receive` already checks
(manifest + SHA256SUMS + files/). Structured candidates ride as optional
observations.jsonl. Provides offline package validation; provides no
reception, adoption, or target-status write.
"""
from fetch.contract.envelope import validate

__all__ = ["validate"]
