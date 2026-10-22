"""fetch: one repository for five inresearch collection teams.

Provides inresearch with immutable, SHA-identified originals and structured
candidates in one delivery envelope. Provides no facts, no adoption, no target
status: those belong to inresearch.
"""
from pathlib import Path

TEAMS = ("fetchspec", "fetchstat", "fetchfilings", "fetchreports", "fetchquotes")
ROOT = Path(__file__).resolve().parents[2]
USER_AGENT = "inresearch-fetch/1 (+https://inresearch.ai)"
