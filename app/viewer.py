"""Minimal Streamlit viewer for output/submission.json. Run with: streamlit run app/viewer.py"""
import json
from pathlib import Path

import streamlit as st

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "output" / "submission.json"

st.title("Shipping Doc Checker - Results")

if not OUTPUT_PATH.exists():
    st.warning(f"No output found at {OUTPUT_PATH}. Run main.py first.")
else:
    data = json.loads(OUTPUT_PATH.read_text())

    for email_id, entry in data.items():
        with st.container(border=True):
            st.subheader(email_id)
            st.write(f"**Category:** {entry.get('category')}")
            st.write(f"**Mismatch found:** {entry.get('mismatch_found')}")
            st.write(f"**Mismatches:** {entry.get('mismatches')}")
            escalation = entry.get("escalation", {})
            st.write(f"**Escalation flagged:** {escalation.get('flagged')}")
            st.write(f"**Escalation reason:** {escalation.get('reason')}")
