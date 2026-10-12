import os
import sys

# Tests import the exporter modules the same way production does:
# flat (``from scraper import ...``), matching the Dockerfile layout
# which copies exporter/*.py into /app.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "exporter"))
