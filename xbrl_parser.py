#!/usr/bin/env python3
"""
xbrl_parser.py — Extract order/contract value from NSE XBRL filings.

Hard timeout: 5 seconds. Fails gracefully (returns "Not Available").
Tags searched (case-insensitive): OrderValue, ContractValue,
WorkOrderValue, OrderAmount, ContractAmount, ProjectValue.
"""

import re
import logging
import requests
from lxml import etree

logger = logging.getLogger("NSEAlert.XBRL")

# Tags to search for (lowercase for case-insensitive match)
VALUE_TAGS = [
    "ordervalue",
    "contractvalue",
    "workordervalue",
    "orderamount",
    "contractamount",
    "projectvalue",
    "letterofintentvalue",
    "loivalue",
    "purchaseordervalue",
]

TIMEOUT_SECS = 5
BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "accept": "application/xml,text/xml,*/*",
    "accept-language": "en-US,en;q=0.9",
    "referer": "https://www.nseindia.com/",
}


def _to_crores(raw_value: str) -> str:
    """Convert a numeric string (assumed rupees) to ₹X.XX Crores format."""
    try:
        val = float(re.sub(r"[^\d.\-]", "", raw_value))
        crores = val / 1e7  # 1 Crore = 10,000,000
        if crores >= 1:
            return f"₹{crores:,.2f} Crores"
        lacs = val / 1e5
        if lacs >= 1:
            return f"₹{lacs:,.2f} Lacs"
        return f"₹{val:,.2f}"
    except (ValueError, TypeError):
        return raw_value


def extract_order_value(attachment_url: str,
                        session: requests.Session = None) -> str:
    """
    Fetch an XBRL file from attachment_url and extract order value.

    Returns:
        Formatted string like "₹45.50 Crores"
        or "Not Available" on any failure.
    """
    if not attachment_url:
        return "Not Available"

    # Build full URL if relative path given
    if attachment_url.startswith("/"):
        attachment_url = "https://www.nseindia.com" + attachment_url

    try:
        requester = session or requests
        resp = requester.get(
            attachment_url,
            headers=BASE_HEADERS,
            timeout=TIMEOUT_SECS,
        )
        if resp.status_code != 200:
            logger.debug(f"XBRL fetch non-200: {resp.status_code} for {attachment_url}")
            return "Not Available"

        content = resp.content
        if not content:
            return "Not Available"

        return _parse_xbrl_bytes(content)

    except requests.exceptions.Timeout:
        logger.debug(f"XBRL fetch timed out: {attachment_url}")
        return "Not Available"
    except requests.exceptions.RequestException as e:
        logger.debug(f"XBRL fetch error: {e}")
        return "Not Available"
    except Exception as e:
        logger.debug(f"XBRL unexpected error: {e}")
        return "Not Available"


def _parse_xbrl_bytes(content: bytes) -> str:
    """Parse XML/XBRL bytes and search for value tags."""
    try:
        root = etree.fromstring(content)
    except etree.XMLSyntaxError:
        # Try HTML parser as fallback for malformed XML
        try:
            from lxml import html as lhtml
            root = lhtml.fromstring(content)
        except Exception:
            return "Not Available"

    # Walk all elements
    for element in root.iter():
        local = etree.QName(element.tag).localname.lower() if "{" in element.tag else element.tag.lower()
        if any(tag in local for tag in VALUE_TAGS):
            raw = (element.text or "").strip()
            if raw and re.search(r"\d", raw):
                formatted = _to_crores(raw)
                logger.debug(f"XBRL found tag={element.tag} value={raw} -> {formatted}")
                return formatted

    # Fallback: regex scan raw bytes for numeric values near keywords
    text = content.decode("utf-8", errors="ignore")
    pattern = re.compile(
        r"(?:order|contract|workorder|loi|purchase)\s*value[^>]*?>\s*([\d,\.]+)",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if match:
        return _to_crores(match.group(1))

    return "Not Available"


if __name__ == "__main__":
    # Quick smoke test — replace with a real NSE XBRL URL to verify
    import sys
    test_url = sys.argv[1] if len(sys.argv) > 1 else ""
    if test_url:
        print(f"Testing XBRL parser on: {test_url}")
        result = extract_order_value(test_url)
        print(f"Result: {result}")
    else:
        print("Usage: python3 xbrl_parser.py <XBRL_URL>")
