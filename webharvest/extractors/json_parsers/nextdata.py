"""NextJS __NEXT_DATA__ Parser.

Extracts page props and state from Next.js server-side rendered tags.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional
from bs4 import BeautifulSoup

logger = logging.getLogger("webharvest.extractors.nextdata")


class NextDataParser:
    """Parses __NEXT_DATA__ script tags in Next.js page DOM."""

    @staticmethod
    def extract(html: str) -> Optional[dict[str, Any]]:
        """Extracts the JSON from __NEXT_DATA__ tag in HTML."""
        try:
            soup = BeautifulSoup(html, "lxml")
            script = soup.find("script", id="__NEXT_DATA__")
            if not script or not script.string:
                return None
            return json.loads(script.string)
        except Exception as e:
            logger.warning("Failed to extract __NEXT_DATA__ script: %s", e)
            return None

    @staticmethod
    def find_key_recursive(data: Any, target_key: str) -> list[Any]:
        """Finds all values associated with a specific key in nested JSON dicts/lists."""
        results = []
        if isinstance(data, dict):
            for k, v in data.items():
                if k == target_key:
                    results.append(v)
                else:
                    results.extend(NextDataParser.find_key_recursive(v, target_key))
        elif isinstance(data, list):
            for item in data:
                results.extend(NextDataParser.find_key_recursive(item, target_key))
        return results
