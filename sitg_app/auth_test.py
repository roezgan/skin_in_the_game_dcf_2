import streamlit as st
from supabase import create_client

url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)

st.title("🔐 Login test")

email = st.text_input("Email")
password = st.text_input("Password", type="password")

if st.button("Sign up"):
    res = supabase.auth.sign_up({"email": email, "password": password})
    st.write(res)

if st.button("Sign in"):
    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
    st.write(res)

st.markdown(f"[Login met Google]({url}/auth/v1/authorize?provider=google)")
