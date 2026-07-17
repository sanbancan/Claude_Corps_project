import logging
import streamlit as st

import pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("covio2.app")


def render_top_listings(top_listings):
    if not top_listings:
        return
    st.table([
        {
            "Rank": i + 1,
            "Supplier ID": l["id"],
            "Resource": ", ".join(l["resource_types"]),
            "Location": l["location"] or "—",
            "Phone": l["phone"] or "—",
            "Price": ("Free" if l["is_free"] else l["price"]) or "confirm on call",
            "Delivery": l["delivery"].replace("_", " "),
            "Documents": l["documents"] or "confirm on call",
            "Verified": l["verified_date"] or "—",
        }
        for i, l in enumerate(top_listings)
    ])

st.set_page_config(page_title="CoviO2", page_icon="🫁")
st.title("🫁 CoviO2 — Oxygen Resource Navigator")
st.caption("Covering Indore · Mumbai · Delhi | Data verified 2021 — demo project")

SAMPLES = [
    "इंदौर में ऑक्सीजन सिलेंडर चाहिए, बहुत urgent है",
    "Mumbai madhe Andheri javal oxygen concentrator pahije, home delivery hawi",
    "Need an oxygen refill in Delhi, can pick up myself",
    "Kanpur me oxygen cylinder chahiye",
]

if "history" not in st.session_state:
    st.session_state.history = []

try:
    listings = pipeline.load_listings()
    log.info("app ready — listings loaded")
except FileNotFoundError:
    log.error("data/listings.json not found — run convert_data.py first")
    st.error("data/listings.json not found. Run `python convert_data.py` first.")
    st.stop()

with st.sidebar:
    st.subheader("Listings")
    for city in ("indore", "mumbai", "delhi"):
        count = sum(1 for l in listings.get(city, []) if l["active"])
        st.write(f"**{city.title()}**: {count} active")
    st.subheader("Try a sample")
    for sample in SAMPLES:
        if st.button(sample, key=sample):
            st.session_state.pending = sample

for turn in st.session_state.history:
    with st.chat_message(turn["role"]):
        st.write(turn["text"])
        if turn["role"] == "assistant" and turn.get("debug"):
            debug = turn["debug"]
            render_top_listings(debug.get("top_listings", []))
            with st.expander("🔍 Behind the scenes"):
                st.markdown("**Step 1 — extracted**")
                st.json(debug["extracted"])
                st.markdown(f"**Step 2 — {len(debug['candidates'])} candidates**")
                if debug["candidates"]:
                    st.dataframe([
                        {
                            "id": c["id"],
                            "types": ", ".join(c["resource_types"]),
                            "location": c["location"],
                            "verified_date": c["verified_date"],
                            "delivery": c["delivery"],
                            "free?": c["is_free"],
                        }
                        for c in debug["candidates"]
                    ])
                st.markdown(f"**Step 3 — top listings:** `{debug['top_listing_ids']}`")
                st.markdown(f"*{debug['reason']}*")

message = st.chat_input("Describe what you need, in any language…")
if not message and "pending" in st.session_state:
    message = st.session_state.pop("pending")

if message:
    st.session_state.history.append({"role": "user", "text": message})
    with st.chat_message("user"):
        st.write(message)
    with st.chat_message("assistant"):
        try:
            log.info("user message received: %r", message)
            with st.spinner("Finding the best supplier…"):
                extracted, candidates, result = pipeline.run(message)
            st.write(result["reply"])
            render_top_listings(result.get("top_listings", []))
            debug = {
                "extracted": extracted,
                "candidates": candidates,
                "top_listings": result.get("top_listings", []),
                "top_listing_ids": [l["id"] for l in result.get("top_listings", [])],
                "reason": result.get("reason"),
            }
            with st.expander("🔍 Behind the scenes"):
                st.markdown("**Step 1 — extracted**")
                st.json(extracted)
                st.markdown(f"**Step 2 — {len(candidates)} candidates**")
                if candidates:
                    st.dataframe([
                        {
                            "id": c["id"],
                            "types": ", ".join(c["resource_types"]),
                            "location": c["location"],
                            "verified_date": c["verified_date"],
                            "delivery": c["delivery"],
                            "free?": c["is_free"],
                        }
                        for c in candidates
                    ])
                st.markdown(f"**Step 3 — top listings:** `{debug['top_listing_ids']}`")
                st.markdown(f"*{debug['reason']}*")
            st.session_state.history.append(
                {"role": "assistant", "text": result["reply"], "debug": debug}
            )
        except Exception as e:
            log.exception("pipeline error for message: %r", message)
            st.error(f"Something went wrong: {e}")
