import os
import tempfile

import pytest

# Route all runtime data (uploads, sqlite history, rules.json) to a temp dir
# BEFORE any app module imports app.config, so tests never touch the repo.
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="mbtest-data-"))


@pytest.fixture
def anyio_backend():
    # Run @pytest.mark.anyio tests on asyncio only (no trio dependency).
    return "asyncio"
