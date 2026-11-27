"""Frameworks library and fix guides. Public content, so no sign-in is needed to read it."""
import pandas as pd
import streamlit as st

from gga import frameworks, knowledge

st.set_page_config(page_title="Frameworks and fix guides", page_icon=":books:", layout="wide")
st.title("Frameworks and fix guides")
st.caption("Summaries in our own words, with links to the original public sources. Most books and standards are "
           "copyrighted, so we link to them instead of copying them. Nothing here is legal advice. Limits and "
           "defaults change, so confirm against the linked page before acting.")

tab1, tab2 = st.tabs(["Frameworks library", "Fix guide for every check"])

with tab1:
    kinds = sorted({f["kind"] for f in frameworks.FRAMEWORKS})
    show = st.multiselect("Show", kinds, default=kinds,
                          help="Public source means a named publication backs it. General practice means widely used "
                               "ideas with no single authority.")
    for f in frameworks.FRAMEWORKS:
        if f["kind"] not in show:
            continue
        with st.expander(f"{f['name']}  ·  {f['kind']}"):
            st.markdown(f"**What it is.** {f['what']}")
            st.markdown(f"**How this tool uses it.** {f['in_tool']}")
            st.markdown(f"**Use it when.** {f['use_when']}")
            if f["sources"]:
                st.markdown("**Sources**")
                for title, url in f["sources"]:
                    st.markdown(f"- [{title}]({url})" if url else f"- {title} (no verified link)")
            if f["name"] == "Data quality dimensions":
                st.markdown("**Where each dimension shows up in an audit**")
                st.dataframe(pd.DataFrame(frameworks.DQ_MAP, columns=["Dimension", "Checks that cover it"]),
                             hide_index=True, width="stretch")

with tab2:
    q = st.text_input("Search checks", placeholder="for example: retention, consent, duplicate")
    n = 0
    for check, g in knowledge.GUIDES.items():
        blob = f"{check} {g['why']} {g['fix']}".lower()
        if q and q.lower() not in blob:
            continue
        n += 1
        with st.expander(check):
            st.markdown(f"**Why it matters.** {g['why']}")
            st.markdown(f"**How to fix.** {g['fix']}")
            if g.get("source"):
                st.markdown(f"**Source:** [{g['source'][0]}]({g['source'][1]})")
            else:
                st.caption("No single authoritative page found, so no link.")
    st.caption(f"{n} checks shown.")
