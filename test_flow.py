"""End-to-end flow test with mock data and a mocked Claude client.

Tests everything EXCEPT the real Claude API and convert_data.py:
  - pipeline.run() orchestration
  - extract() response parsing (incl. markdown-fenced JSON)
  - retrieve() filtering: city keying, active-only, type match, fallback,
    newest-first sort, cap of 12
  - rank_and_reply() payload construction (trims, compact JSON)
  - out-of-scope city handling

Run: python test_flow.py   (no API key needed)
"""
import json
import sys
import types

# ---------------------------------------------------------------- mock claude
call_log = []

EXTRACT_RESPONSES = {
    # keyed by a substring of the user message
    "इंदौर": '{"city":"indore","city_mentioned":"इंदौर","language":"hi","resource_type":"cylinder","location_detail":null,"urgency":"high","delivery_preference":null,"notes":"User needs cylinder urgently"}',
    "Andheri": '```json\n{"city":"mumbai","city_mentioned":"Mumbai","language":"mr","resource_type":"concentrator","location_detail":"Andheri","urgency":"normal","delivery_preference":"home_delivery","notes":null}\n```',
    "Delhi": '{"city":"delhi","city_mentioned":"Delhi","language":"en","resource_type":"refill","location_detail":null,"urgency":"normal","delivery_preference":"pickup","notes":null}',
    "Kanpur": '{"city":"other","city_mentioned":"Kanpur","language":"hi","resource_type":"cylinder","location_detail":null,"urgency":"normal","delivery_preference":null,"notes":null}',
}

RANK_RESPONSE = '{"top_listing_ids":%s,"reason":"Most recently verified and matches preference","reply":"MOCK REPLY (data verified 2021; nonprofit only connects, does not sell)"}'


class FakeMessages:
    @staticmethod
    def create(**kw):
        call_log.append(kw)
        system = kw.get("system", "")
        content = kw["messages"][0]["content"]
        if "intake classifier" in system:  # extract call
            for key, resp in EXTRACT_RESPONSES.items():
                if key in content:
                    return types.SimpleNamespace(content=[types.SimpleNamespace(text=resp)])
            raise AssertionError(f"no mock extract response for: {content!r}")
        # rank call: return the first 3 candidate ids plus one bogus id, so we
        # also exercise the hallucinated-id filtering in rank_and_reply()
        payload = json.loads(content)
        ids = [c["id"] for c in payload["candidates"][:3]] + ["FAKE-999"]
        text = RANK_RESPONSE % json.dumps(ids if payload["candidates"] else [])
        return types.SimpleNamespace(content=[types.SimpleNamespace(text=text)])


class FakeClient:
    messages = FakeMessages


sys.modules["anthropic"] = types.SimpleNamespace(Anthropic=lambda *a, **k: FakeClient())
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda *a, **k: False))

import pipeline  # noqa: E402  (import after mocks)

pipeline._client = FakeClient()

# ---------------------------------------------------------------- mock data
pipeline._listings = {
    "indore": [
        {"id": "IND-001", "city": "indore", "resource_types": ["cylinder"], "raw_object": "Oxygen Cylinder",
         "location": "Vijay Nagar", "price": "Rs.500", "is_free": False, "delivery": "pickup",
         "phone": "9111111111", "verified_date": "2021-05-10", "documents": "none",
         "active": True, "inactive_reason": None},
        {"id": "IND-002", "city": "indore", "resource_types": ["cylinder", "refill"], "raw_object": "Oxygen Cylinder and Refill",
         "location": "Palasia", "price": None, "is_free": False, "delivery": "home_delivery",
         "phone": "9222222222", "verified_date": "2021-06-01", "documents": "Aadhar card",
         "active": True, "inactive_reason": None},
        {"id": "IND-003", "city": "indore", "resource_types": ["cylinder"], "raw_object": "Oxygen Cylinder",
         "location": "Rau", "price": "free", "is_free": True, "delivery": "unknown",
         "phone": None, "verified_date": "2021-06-20", "documents": "none",
         "active": False, "inactive_reason": "missing phone number"},
    ],
    "mumbai": [
        {"id": "MUM-001", "city": "mumbai", "resource_types": ["concentrator"], "raw_object": "Oxygen Concentrator",
         "location": "Andheri West", "price": "Rs.40000", "is_free": False, "delivery": "home_delivery",
         "phone": "9333333333", "verified_date": "2021-06-15", "documents": "id proof",
         "active": True, "inactive_reason": None},
        {"id": "MUM-002", "city": "mumbai", "resource_types": ["concentrator"], "raw_object": "Oxygen Concentrator 5L",
         "location": "Dadar", "price": "Rs.35000", "is_free": False, "delivery": "pickup",
         "phone": "9444444444", "verified_date": "2021-06-25", "documents": "none",
         "active": True, "inactive_reason": None},
        {"id": "MUM-003", "city": "mumbai", "resource_types": ["cylinder"], "raw_object": "Oxygen Cylinder",
         "location": "Thane", "price": None, "is_free": False, "delivery": "both",
         "phone": "9555555555", "verified_date": "2021-06-10", "documents": "none",
         "active": True, "inactive_reason": None},
    ],
    "delhi": [
        # 14 refill rows to prove the 12-cap; DEL-014 newest, DEL-001 oldest
        *[{"id": f"DEL-{i:03d}", "city": "delhi", "resource_types": ["refill"], "raw_object": "Oxygen Refill",
           "location": f"Area {i}", "price": f"Rs.{100 + i}", "is_free": False, "delivery": "pickup",
           "phone": f"98000000{i:02d}", "verified_date": f"2021-06-{i:02d}", "documents": "none",
           "active": True, "inactive_reason": None} for i in range(1, 15)],
        {"id": "DEL-015", "city": "delhi", "resource_types": ["refill"], "raw_object": "Oxygen Refill",
         "location": "Karol Bagh", "price": None, "is_free": False, "delivery": "pickup",
         "phone": None, "verified_date": "2021-06-30", "documents": None,
         "active": False, "inactive_reason": "dead or unreachable phone number"},
    ],
}

passed = 0


def check(name, cond, detail=""):
    global passed
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        sys.exit(f"\nTEST FAILED: {name} {detail}")
    passed += 1


# ---------------------------------------------------------------- scenario 1
print("\n=== Scenario 1: Hindi, urgent cylinder in Indore ===")
extracted, candidates, result = pipeline.run("इंदौर में ऑक्सीजन सिलेंडर चाहिए, बहुत urgent है")
check("city extracted as indore", extracted["city"] == "indore")
check("language is hi", extracted["language"] == "hi")
check("urgency is high", extracted["urgency"] == "high")
ids = [c["id"] for c in candidates]
check("both active cylinder listings retrieved", set(ids) == {"IND-001", "IND-002"}, str(ids))
check("inactive IND-003 excluded", "IND-003" not in ids)
check("sorted newest first", ids[0] == "IND-002", str(ids))
top_ids = [l["id"] for l in result["top_listings"]]
check("top listings chosen, best first", top_ids[0] == "IND-002", str(top_ids))
check("hallucinated FAKE-999 id filtered out", "FAKE-999" not in top_ids)
check("full listing objects resolved (phone present)", all(l.get("phone") for l in result["top_listings"]))

# ---------------------------------------------------------------- scenario 2
print("\n=== Scenario 2: Marathi, concentrator near Andheri, home delivery ===")
extracted, candidates, result = pipeline.run("Mumbai madhe Andheri javal oxygen concentrator pahije, home delivery hawi")
check("markdown-fenced JSON parsed", extracted["city"] == "mumbai")
check("location_detail captured", extracted["location_detail"] == "Andheri")
ids = [c["id"] for c in candidates]
check("only concentrators retrieved", set(ids) == {"MUM-001", "MUM-002"}, str(ids))
check("cylinder row MUM-003 excluded by type filter", "MUM-003" not in ids)
check("location NOT filtered in retrieve (both areas present)", "MUM-002" in ids and "MUM-001" in ids)

# ---------------------------------------------------------------- scenario 3
print("\n=== Scenario 3: English, Delhi refill, cap of 12 ===")
extracted, candidates, result = pipeline.run("Need an oxygen refill in Delhi, can pick up myself")
ids = [c["id"] for c in candidates]
check("capped at 12 candidates", len(candidates) == 12, str(len(candidates)))
check("newest first (DEL-014 top)", ids[0] == "DEL-014", str(ids[:3]))
check("oldest two (DEL-001, DEL-002) dropped by cap", "DEL-001" not in ids and "DEL-002" not in ids)
check("inactive DEL-015 excluded despite newest date", "DEL-015" not in ids)
top_ids = [l["id"] for l in result["top_listings"]]
check("exactly 3 top listings returned", len(top_ids) == 3, str(top_ids))
check("top listing is newest", top_ids[0] == "DEL-014", str(top_ids))

# ---------------------------------------------------------------- scenario 4
print("\n=== Scenario 4: Kanpur — out of scope ===")
extracted, candidates, result = pipeline.run("Kanpur me oxygen cylinder chahiye")
check("city extracted as other", extracted["city"] == "other")
check("no candidates", candidates == [])
check("rank call still made (reply in user language)", result["reply"].startswith("MOCK REPLY"))
check("no listings for out-of-scope", result["top_listings"] == [])

# ---------------------------------------------------------------- scenario 5
print("\n=== Scenario 5: type fallback (no 'can' in indore -> all active) ===")
candidates = pipeline.retrieve({"city": "indore", "resource_type": "can"})
ids = [c["id"] for c in candidates]
check("falls back to all active listings", set(ids) == {"IND-001", "IND-002"}, str(ids))

# ---------------------------------------------------------------- payload audit
print("\n=== Payload audit: what was actually sent to (mock) Claude ===")
rank_calls = [c for c in call_log if "helpline assistant" in c.get("system", "")]
extract_calls = [c for c in call_log if "intake classifier" in c.get("system", "")]
check("exactly 4 extract + 4 rank calls (2 per message)", len(extract_calls) == 4 and len(rank_calls) == 4,
      f"extract={len(extract_calls)} rank={len(rank_calls)}")

for rc in rank_calls:
    payload = json.loads(rc["messages"][0]["content"])
    for c in payload["candidates"]:
        assert "city" not in c and "active" not in c and "raw_object" not in c and "inactive_reason" not in c
    assert "city_mentioned" not in payload["extracted"]
check("every rank payload trimmed (no city/active/raw_object/inactive_reason/city_mentioned)", True)

delhi_call = json.loads(rank_calls[2]["messages"][0]["content"])
check("delhi rank payload has exactly 12 candidates (never the full 15)", len(delhi_call["candidates"]) == 12)
check("compact JSON separators used", '", "' not in rank_calls[2]["messages"][0]["content"])
check("all calls used claude-haiku-4-5", all(c["model"] == "claude-haiku-4-5" for c in call_log))
check("max_tokens caps respected (512 extract / 1024 rank)",
      all(c["max_tokens"] == 512 for c in extract_calls) and all(c["max_tokens"] == 1024 for c in rank_calls))

print(f"\n=== ALL {passed} CHECKS PASSED ===")
