import streamlit as st

# =====================================================
# PAGE CONFIG  (moet als eerste Streamlit-call)
# =====================================================
st.set_page_config(
    page_title="Skin in the Game",
    layout="wide",
    initial_sidebar_state="collapsed",  # show hamburger menu instead of open sidebar
)

# =====================================================
# IMPORTS
# =====================================================
from dcf.ui_sections import render_dcf_section
from auth_utils import check_auth, login_icon

# =====================================================
# AUTHENTICATION (OPTIONAL)
# =====================================================
# Check auth but don't require it - users can use the app without logging in
check_auth()
login_icon()

# =====================================================
# MAIN PAGE CONTENT
# =====================================================
st.title("💼 Skin in the Game — DCF Dashboard")


# =====================================================
# ROUTER / MAIN CONTENT
# =====================================================
render_dcf_section()


# =====================================================
# FOOTER (optioneel)
# =====================================================
st.markdown(
    """
    <div style="text-align:center;margin-top:40px;font-size:12px;color:#888;">
        Built with ❤️ using Streamlit & Supabase · Skin in the Game © 2025
    </div>
    """,
    unsafe_allow_html=True,
)
