import os

# Most tests assert on the sample as it was cut (newest invoice 2026-04-09), so they run
# without the roll-forward. tests/test_sample_rebase.py turns it on explicitly.
os.environ.setdefault("SAMPLE_REBASE", "off")
# The data-loading scheduler never runs in tests; tests call the service directly.
os.environ.setdefault("INGEST_SCHEDULER", "off")
import tempfile

# Never read or write the real data store from tests.
os.environ["INGEST_DIR"] = tempfile.mkdtemp(prefix="nf-ingest-")
os.environ["WORKSPACES_DIR"] = tempfile.mkdtemp(prefix="nf-ws-")
os.environ.setdefault("OPENAI_API_KEY", "dummy")
