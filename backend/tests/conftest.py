"""Shared pytest setup.

Point the API's default database at a temporary file so importing api.main
during tests never writes to backend/data/mandateiq.db, and pin the provider
to mock so the LLM_PROVIDER in a developer's .env (which api.main loads, without
overriding variables already set) never sends tests to a real model.
"""
import os
import tempfile

os.environ.setdefault("MANDATEIQ_DB", os.path.join(tempfile.mkdtemp(prefix="mandateiq-test-"), "test.db"))
os.environ["LLM_PROVIDER"] = "mock"
