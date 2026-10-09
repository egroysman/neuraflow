import os

# Most tests assert on the sample as it was cut (newest invoice 2026-04-09), so they run
# without the roll-forward. tests/test_sample_rebase.py turns it on explicitly.
os.environ.setdefault("SAMPLE_REBASE", "off")
