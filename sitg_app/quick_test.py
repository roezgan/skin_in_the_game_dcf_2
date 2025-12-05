import streamlit as st
from supabase import create_client

url = st.secrets["supabase"]["url"]
key = st.secrets["supabase"]["anon_key"]
sb = create_client(url, key)

if st.button("Test Google OAuth"):
    res = sb.auth.sign_in_with_oauth({
        "provider": "google",
        "options": {"redirect_to": "http://localhost:8501/"}
    })
    st.write(res)
