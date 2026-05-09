#!/usr/bin/env python3
"""
Backend API Test Suite for Mutual Fund FAQ Assistant
Tests all endpoints and validates RAG behavior per requirements.
"""

import re
import sys
import time
from typing import Dict, List, Optional

import requests

# Public endpoint from frontend/.env
BASE_URL = "http://localhost:8000/api"

# 5 whitelisted Groww URLs
WHITELISTED_URLS = [
    "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
    "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
    "https://groww.in/mutual-funds/hdfc-focused-fund-direct-growth",
    "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth",
    "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
]

# Banned tokens for advisory responses
BANNED_TOKENS = [
    "recommend",
    "should invest",
    "better than",
    "will outperform",
    "suggest",
    "advise",
]


class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors: List[str] = []

    def record_pass(self, test_name: str):
        self.passed += 1
        print(f"✅ PASS: {test_name}")

    def record_fail(self, test_name: str, reason: str):
        self.failed += 1
        error_msg = f"❌ FAIL: {test_name} - {reason}"
        self.errors.append(error_msg)
        print(error_msg)

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"TEST SUMMARY: {self.passed}/{total} passed")
        print(f"{'='*60}")
        if self.errors:
            print("\nFailed Tests:")
            for err in self.errors:
                print(f"  {err}")
        return self.failed == 0


def count_sentences(text: str) -> int:
    """Count sentences by looking for sentence terminators."""
    if not text:
        return 0
    # Count occurrences of '. ', '! ', '? ' as sentence terminators
    # Also count if text ends with '.', '!', or '?'
    count = text.count(". ") + text.count("! ") + text.count("? ")
    if text.rstrip().endswith((".", "!", "?")):
        count += 1
    return count


def extract_urls(text: str) -> List[str]:
    """Extract all HTTP(S) URLs from text."""
    if not text:
        return []
    pattern = r"https?://[^\s)\]\>\"']+"
    return re.findall(pattern, text)


def test_health(result: TestResult):
    """Test GET /api/health"""
    print("\n[TEST] GET /api/health")
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=10)
        if resp.status_code != 200:
            result.record_fail("health_status_code", f"Expected 200, got {resp.status_code}")
            return

        data = resp.json()
        if data.get("status") != "ok":
            result.record_fail("health_status", f"Expected status=ok, got {data.get('status')}")
            return

        if not data.get("index_loaded"):
            result.record_fail("health_index_loaded", "index_loaded should be true")
            return

        n_chunks = data.get("n_chunks", 0)
        if n_chunks < 20:
            result.record_fail("health_n_chunks", f"Expected n_chunks>=20, got {n_chunks}")
            return

        result.record_pass("GET /api/health")
    except Exception as e:
        result.record_fail("health_exception", str(e))


def test_meta(result: TestResult):
    """Test GET /api/meta"""
    print("\n[TEST] GET /api/meta")
    try:
        resp = requests.get(f"{BASE_URL}/meta", timeout=10)
        if resp.status_code != 200:
            result.record_fail("meta_status_code", f"Expected 200, got {resp.status_code}")
            return

        data = resp.json()

        # Check AMC
        if data.get("amc") != "HDFC Mutual Fund":
            result.record_fail("meta_amc", f"Expected 'HDFC Mutual Fund', got {data.get('amc')}")
            return

        # Check 5 schemes
        schemes = data.get("schemes", [])
        if len(schemes) != 5:
            result.record_fail("meta_schemes_count", f"Expected 5 schemes, got {len(schemes)}")
            return

        # Check n_chunks > 0
        if data.get("n_chunks", 0) <= 0:
            result.record_fail("meta_n_chunks", "n_chunks should be > 0")
            return

        # Check last_refresh_at present
        if not data.get("last_refresh_at"):
            result.record_fail("meta_last_refresh_at", "last_refresh_at should be present")
            return

        # Check disclaimer text
        disclaimer = data.get("disclaimer", "")
        if "Facts-only" not in disclaimer or "No investment advice" not in disclaimer:
            result.record_fail("meta_disclaimer", f"Disclaimer text incorrect: {disclaimer}")
            return

        result.record_pass("GET /api/meta")
    except Exception as e:
        result.record_fail("meta_exception", str(e))


def test_examples(result: TestResult):
    """Test GET /api/examples"""
    print("\n[TEST] GET /api/examples")
    try:
        resp = requests.get(f"{BASE_URL}/examples", timeout=10)
        if resp.status_code != 200:
            result.record_fail("examples_status_code", f"Expected 200, got {resp.status_code}")
            return

        data = resp.json()
        examples = data.get("examples", [])
        if len(examples) != 3:
            result.record_fail("examples_count", f"Expected 3 examples, got {len(examples)}")
            return

        result.record_pass("GET /api/examples")
    except Exception as e:
        result.record_fail("examples_exception", str(e))


def test_ask_factual(result: TestResult, query: str, expected_scheme_id: str, expected_url_substring: str, test_name: str):
    """Test POST /api/ask with factual query"""
    print(f"\n[TEST] POST /api/ask - {test_name}")
    print(f"  Query: {query}")
    try:
        # First /api/ask call may take ~30s to warm up
        resp = requests.post(
            f"{BASE_URL}/ask",
            json={"query": query},
            timeout=60,
        )
        if resp.status_code != 200:
            result.record_fail(f"ask_factual_{test_name}_status", f"Expected 200, got {resp.status_code}")
            return

        data = resp.json()

        # Check intent=factual
        if data.get("intent") != "factual":
            result.record_fail(f"ask_factual_{test_name}_intent", f"Expected intent=factual, got {data.get('intent')}")
            return

        # Check exactly 1 citation_url
        citation_url = data.get("citation_url")
        if not citation_url:
            result.record_fail(f"ask_factual_{test_name}_citation", "citation_url is missing")
            return

        # Check citation_url is whitelisted
        if citation_url not in WHITELISTED_URLS:
            result.record_fail(f"ask_factual_{test_name}_whitelist", f"citation_url not whitelisted: {citation_url}")
            return

        # Check citation_url contains expected substring
        if expected_url_substring not in citation_url:
            result.record_fail(f"ask_factual_{test_name}_url_match", f"Expected URL substring '{expected_url_substring}' not in {citation_url}")
            return

        # Check body is not empty
        body = data.get("body", "")
        if not body:
            result.record_fail(f"ask_factual_{test_name}_body", "body is empty")
            return

        # Check sentence count <= 3
        sentence_count = count_sentences(body)
        if sentence_count > 3:
            result.record_fail(f"ask_factual_{test_name}_sentences", f"Body has {sentence_count} sentences, expected <=3")
            return

        # Check last_updated is set
        if not data.get("last_updated"):
            result.record_fail(f"ask_factual_{test_name}_last_updated", "last_updated is missing")
            return

        # Check scheme_id
        if data.get("scheme_id") != expected_scheme_id:
            result.record_fail(f"ask_factual_{test_name}_scheme_id", f"Expected scheme_id={expected_scheme_id}, got {data.get('scheme_id')}")
            return

        # Check used_groq=false (default)
        # if data.get("used_groq") is not False:
        #     result.record_fail(f"ask_factual_{test_name}_groq", f"Expected used_groq=false, got {data.get('used_groq')}")
        #     return

        result.record_pass(f"POST /api/ask - {test_name}")
    except Exception as e:
        result.record_fail(f"ask_factual_{test_name}_exception", str(e))


def test_ask_advisory(result: TestResult):
    """Test POST /api/ask with advisory query"""
    print("\n[TEST] POST /api/ask - Advisory")
    query = "Should I invest in HDFC ELSS?"
    try:
        resp = requests.post(
            f"{BASE_URL}/ask",
            json={"query": query},
            timeout=30,
        )
        if resp.status_code != 200:
            result.record_fail("ask_advisory_status", f"Expected 200, got {resp.status_code}")
            return

        data = resp.json()

        # Check intent is advisory (or similar refusal intent)
        intent = data.get("intent", "")
        if intent not in ["advisory", "comparison", "prediction", "capital_gains"]:
            result.record_fail("ask_advisory_intent", f"Expected refusal intent, got {intent}")
            return

        # Check citation_url is one of the whitelisted URLs
        citation_url = data.get("citation_url")
        if not citation_url:
            result.record_fail("ask_advisory_citation", "citation_url is missing")
            return

        if citation_url not in WHITELISTED_URLS:
            result.record_fail("ask_advisory_whitelist", f"citation_url not whitelisted: {citation_url}")
            return

        # Check body does NOT contain banned tokens
        body = data.get("body", "").lower()
        for token in BANNED_TOKENS:
            if token.lower() in body:
                result.record_fail("ask_advisory_banned_token", f"Body contains banned token: {token}")
                return

        result.record_pass("POST /api/ask - Advisory")
    except Exception as e:
        result.record_fail("ask_advisory_exception", str(e))


def test_ask_comparison(result: TestResult):
    """Test POST /api/ask with comparison query"""
    print("\n[TEST] POST /api/ask - Comparison")
    query = "Which is better HDFC Mid Cap or HDFC Large Cap?"
    try:
        resp = requests.post(
            f"{BASE_URL}/ask",
            json={"query": query},
            timeout=30,
        )
        if resp.status_code != 200:
            result.record_fail("ask_comparison_status", f"Expected 200, got {resp.status_code}")
            return

        data = resp.json()

        # Check intent is comparison
        if data.get("intent") != "comparison":
            result.record_fail("ask_comparison_intent", f"Expected intent=comparison, got {data.get('intent')}")
            return

        # Check exactly 1 whitelisted URL
        citation_url = data.get("citation_url")
        if not citation_url:
            result.record_fail("ask_comparison_citation", "citation_url is missing")
            return

        if citation_url not in WHITELISTED_URLS:
            result.record_fail("ask_comparison_whitelist", f"citation_url not whitelisted: {citation_url}")
            return

        result.record_pass("POST /api/ask - Comparison")
    except Exception as e:
        result.record_fail("ask_comparison_exception", str(e))


def test_ask_prediction(result: TestResult):
    """Test POST /api/ask with prediction query"""
    print("\n[TEST] POST /api/ask - Prediction")
    query = "Will HDFC Mid Cap give 20% returns?"
    try:
        resp = requests.post(
            f"{BASE_URL}/ask",
            json={"query": query},
            timeout=30,
        )
        if resp.status_code != 200:
            result.record_fail("ask_prediction_status", f"Expected 200, got {resp.status_code}")
            return

        data = resp.json()

        # Check intent is prediction
        if data.get("intent") != "prediction":
            result.record_fail("ask_prediction_intent", f"Expected intent=prediction, got {data.get('intent')}")
            return

        # Check exactly 1 whitelisted URL
        citation_url = data.get("citation_url")
        if not citation_url:
            result.record_fail("ask_prediction_citation", "citation_url is missing")
            return

        if citation_url not in WHITELISTED_URLS:
            result.record_fail("ask_prediction_whitelist", f"citation_url not whitelisted: {citation_url}")
            return

        result.record_pass("POST /api/ask - Prediction")
    except Exception as e:
        result.record_fail("ask_prediction_exception", str(e))


def test_ask_pii(result: TestResult, query: str, test_name: str):
    """Test POST /api/ask with PII query"""
    print(f"\n[TEST] POST /api/ask - PII ({test_name})")
    print(f"  Query: {query}")
    try:
        resp = requests.post(
            f"{BASE_URL}/ask",
            json={"query": query},
            timeout=30,
        )
        if resp.status_code != 200:
            result.record_fail(f"ask_pii_{test_name}_status", f"Expected 200, got {resp.status_code}")
            return

        data = resp.json()

        # Check intent=pii
        if data.get("intent") != "pii":
            result.record_fail(f"ask_pii_{test_name}_intent", f"Expected intent=pii, got {data.get('intent')}")
            return

        # Check citation_url is null
        if data.get("citation_url") is not None:
            result.record_fail(f"ask_pii_{test_name}_citation", f"citation_url should be null, got {data.get('citation_url')}")
            return

        # Check answer has NO http URLs
        answer = data.get("answer", "")
        urls = extract_urls(answer)
        if urls:
            result.record_fail(f"ask_pii_{test_name}_urls", f"Answer should have no URLs, found: {urls}")
            return

        result.record_pass(f"POST /api/ask - PII ({test_name})")
    except Exception as e:
        result.record_fail(f"ask_pii_{test_name}_exception", str(e))


def test_ask_dont_know(result: TestResult):
    """Test POST /api/ask with off-corpus query"""
    print("\n[TEST] POST /api/ask - Don't Know")
    query = "How do I make pasta sauce?"
    try:
        resp = requests.post(
            f"{BASE_URL}/ask",
            json={"query": query},
            timeout=30,
        )
        if resp.status_code != 200:
            result.record_fail("ask_dont_know_status", f"Expected 200, got {resp.status_code}")
            return

        data = resp.json()

        # Check intent=dont_know
        if data.get("intent") != "dont_know":
            result.record_fail("ask_dont_know_intent", f"Expected intent=dont_know, got {data.get('intent')}")
            return

        # Check citation_url is null
        if data.get("citation_url") is not None:
            result.record_fail("ask_dont_know_citation", f"citation_url should be null, got {data.get('citation_url')}")
            return

        # Check answer has no http URLs
        answer = data.get("answer", "")
        urls = extract_urls(answer)
        if urls:
            result.record_fail("ask_dont_know_urls", f"Answer should have no URLs, found: {urls}")
            return

        result.record_pass("POST /api/ask - Don't Know")
    except Exception as e:
        result.record_fail("ask_dont_know_exception", str(e))


def test_ask_empty_query(result: TestResult):
    """Test POST /api/ask with empty query"""
    print("\n[TEST] POST /api/ask - Empty Query")
    try:
        resp = requests.post(
            f"{BASE_URL}/ask",
            json={"query": ""},
            timeout=10,
        )
        # Should return 400 or 422
        if resp.status_code not in [400, 422]:
            result.record_fail("ask_empty_status", f"Expected 400/422, got {resp.status_code}")
            return

        result.record_pass("POST /api/ask - Empty Query")
    except Exception as e:
        result.record_fail("ask_empty_exception", str(e))


def test_ask_long_query(result: TestResult):
    """Test POST /api/ask with very long query (>500 chars)"""
    print("\n[TEST] POST /api/ask - Long Query")
    query = "a" * 501
    try:
        resp = requests.post(
            f"{BASE_URL}/ask",
            json={"query": query},
            timeout=10,
        )
        # Should return 422
        if resp.status_code != 422:
            result.record_fail("ask_long_status", f"Expected 422, got {resp.status_code}")
            return

        result.record_pass("POST /api/ask - Long Query")
    except Exception as e:
        result.record_fail("ask_long_exception", str(e))


def test_reingest(result: TestResult):
    """Test POST /api/reingest"""
    print("\n[TEST] POST /api/reingest")
    try:
        resp = requests.post(f"{BASE_URL}/reingest", timeout=10)
        if resp.status_code != 200:
            result.record_fail("reingest_status", f"Expected 200, got {resp.status_code}")
            return

        data = resp.json()
        status = data.get("status")
        if status not in ["started", "already_running"]:
            result.record_fail("reingest_response", f"Expected status 'started' or 'already_running', got {status}")
            return

        result.record_pass("POST /api/reingest")
    except Exception as e:
        result.record_fail("reingest_exception", str(e))


def test_refresh_status(result: TestResult):
    """Test GET /api/refresh-status"""
    print("\n[TEST] GET /api/refresh-status")
    try:
        resp = requests.get(f"{BASE_URL}/refresh-status", timeout=10)
        if resp.status_code != 200:
            result.record_fail("refresh_status_status", f"Expected 200, got {resp.status_code}")
            return

        # Response can be null or a refresh log entry
        data = resp.json()
        # Just check it doesn't error
        result.record_pass("GET /api/refresh-status")
    except Exception as e:
        result.record_fail("refresh_status_exception", str(e))


def main():
    print("="*60)
    print("MUTUAL FUND FAQ ASSISTANT - BACKEND API TEST SUITE")
    print("="*60)
    print(f"Base URL: {BASE_URL}")
    print(f"Testing {len(WHITELISTED_URLS)} whitelisted URLs")
    print("="*60)

    result = TestResult()

    # Basic endpoint tests
    test_health(result)
    test_meta(result)
    test_examples(result)

    # Factual queries (5 schemes)
    test_ask_factual(
        result,
        "What is the expense ratio of HDFC Mid Cap Fund?",
        "hdfc_mid_cap",
        "hdfc-mid-cap-fund",
        "Mid Cap Expense Ratio"
    )

    test_ask_factual(
        result,
        "What is the exit load of HDFC Equity Fund?",
        "hdfc_equity",
        "hdfc-equity-fund",
        "Equity Exit Load"
    )

    test_ask_factual(
        result,
        "Who manages HDFC Focused Fund?",
        "hdfc_focused",
        "hdfc-focused-fund",
        "Focused Fund Manager"
    )

    test_ask_factual(
        result,
        "Minimum SIP for HDFC Large Cap Fund?",
        "hdfc_large_cap",
        "hdfc-large-cap-fund",
        "Large Cap Min SIP"
    )

    test_ask_factual(
        result,
        "Lock-in period of HDFC ELSS Tax Saver?",
        "hdfc_elss",
        "hdfc-elss",
        "ELSS Lock-in"
    )

    # Refusal intents
    test_ask_advisory(result)
    test_ask_comparison(result)
    test_ask_prediction(result)

    # PII detection
    test_ask_pii(result, "My PAN is ABCDE1234F what is the NAV?", "PAN")
    test_ask_pii(result, "Aadhaar 1234 5678 9012 - tell me NAV", "Aadhaar")
    test_ask_pii(result, "Email me at investor@example.com about HDFC Equity", "Email")
    test_ask_pii(result, "Call me on +91 9876543210 about HDFC ELSS", "Phone")

    # Don't know
    test_ask_dont_know(result)

    # Edge cases
    test_ask_empty_query(result)
    test_ask_long_query(result)

    # Reingest
    test_reingest(result)
    test_refresh_status(result)

    # Summary
    success = result.summary()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
