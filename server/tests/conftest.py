from __future__ import annotations

import os


# Unit tests must stay deterministic even when a local ignored .env contains
# real provider keys for simulator demos.
os.environ["ARK_API_KEY"] = ""
os.environ["TEXT_EMBEDDING_API_KEY"] = ""
os.environ["VISION_UNDERSTANDING_API_KEY"] = ""
