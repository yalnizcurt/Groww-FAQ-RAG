import requests
import json
import time

URL = "http://localhost:8000/api/ask"

QUERIES = [
    # Natural Language Factual
    "how risky is HDFC Mid Cap?",
    "what happens if I remove money early from HDFC Equity?",
    "how much do they charge yearly for HDFC Focused?",
    "is HDFC ELSS locked?",
    "what's the minimum amount I can start with in HDFC Large Cap?",
    "who is managing the HDFC Mid cap fund right now?",
    
    # Generic Factual
    "can I take money out anytime?",
    "how much does it cost?",
    "tell me the risk",
    
    # Performance (Should trigger refusal)
    "what are the returns for last 6 years if i would have invested 6000",
    "how has this done historically?",
    "what's the expected profit?",
    
    # Advisory (Should trigger refusal)
    "should I invest in this?",
    "is this a good fund to buy?",
    
    # Conversational / Greetings
    "hello",
    "thanks, got it",
    
    # Contextual
    # Handled by passing session_id
]

def run_tests():
    print("Running Semantic Tests...")
    for q in QUERIES:
        print(f"\n--- Query: {q} ---")
        try:
            resp = requests.post(URL, json={"query": q, "session_id": "test_sess_1"}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                print(f"Intent:     {data.get('intent')}")
                print(f"Answer:     {data.get('body')}")
                print(f"Scheme ID:  {data.get('scheme_id')}")
            else:
                print(f"Failed with status: {resp.status_code}")
        except Exception as e:
            print(f"Error: {e}")
            
if __name__ == "__main__":
    run_tests()
