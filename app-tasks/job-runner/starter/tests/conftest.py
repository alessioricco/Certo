import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobs import Runner  # noqa: E402

# How long a job in these tests works: like a real job, it takes a moment.
WORK_SECONDS = 2.0


def work(value, seconds=WORK_SECONDS):
    time.sleep(seconds)
    return value


def boom(message, seconds=WORK_SECONDS):
    time.sleep(seconds)
    raise RuntimeError(message)


@pytest.fixture
def runner():
    r = Runner()
    yield r
    r.stop()
