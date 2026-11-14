"""LOK — LOOK FOR IT.

AI Correction & Context Integrity Benchmark.

LOK is a local evaluation platform. It does not generate answers and does not
use an AI model. Users paste AI assistant responses; LOK checks them against
scenario-defined, deterministic assertions and optional human review.
"""

__all__ = ["APP_NAME", "PRODUCT_DESCRIPTION", "TAGLINE", "__version__"]

APP_NAME = "LOK"
TAGLINE = "LOOK FOR IT"
PRODUCT_DESCRIPTION = "AI Correction & Context Integrity Benchmark"
__version__ = "1.0.0"
