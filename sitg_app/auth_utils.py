import streamlit as st
from supabase import create_client
import os
import socket
import requests

# =====================================================
# CONNECTIVITY TEST
# =====================================================
def test_supabase_connectivity(url: str):
    """Test if we can resolve and connect to Supabase URL."""
    try:
        # Extract hostname from URL
        from urllib.parse import urlparse
        parsed = urlparse(url)
        hostname = parsed.hostname
        
        if not hostname:
            return False, "Invalid URL format"
        
        # Try DNS resolution
        try:
            socket.gethostbyname(hostname)
            return True, "Connection OK"
        except socket.gaierror as e:
            return False, f"DNS resolution failed: {e}"
    except Exception as e:
        return False, f"Connectivity test failed: {e}"


# =====================================================
# SUPABASE INITIALIZATION
# =====================================================
@st.cache_resource
def init_supabase():
    """Initialize Supabase client using secrets.toml."""
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["anon_key"]
        
        # Validate URL format
        if not url.startswith("https://"):
            raise ValueError("Supabase URL must start with https://")
        
        # Simple client creation - options can cause issues with some network configs
        client = create_client(url, key)
        
        # If we have a stored access token from OAuth, set it
        if hasattr(st, 'session_state') and st.session_state.get("supabase_access_token"):
            # Note: Supabase Python client doesn't have a direct way to set session
            # The token is stored in session_state and we'll use it for API calls
            pass
        
        return client
    except KeyError as e:
        raise ValueError(f"Supabase credentials not found in secrets: {e}")
    except Exception as e:
        raise ValueError(f"Failed to initialize Supabase client: {e}")


def check_connectivity_and_show_warning():
    """Check connectivity and show warning if needed (outside cached function).
    Only shows warning if user is trying to authenticate."""
    # Only check connectivity if user is actively trying to log in
    if not st.session_state.get("show_login", False) and not st.session_state.get("user"):
        return True  # Skip check if not trying to authenticate
    
    try:
        url = st.secrets["supabase"]["url"]
        can_connect, msg = test_supabase_connectivity(url)
        if not can_connect and st.session_state.get("show_connectivity_warning", True):
            st.error(f"⚠️ Cannot resolve Supabase domain: {msg}")
            st.warning("""
            **This could mean:**
            1. **Project is paused** - Free tier projects pause after inactivity. Check your Supabase dashboard.
            2. **Project was deleted** - Verify the project exists in your Supabase dashboard.
            3. **DNS/Network issue** - Your network cannot resolve the domain.
            """)
            st.info("💡 **Quick fixes:**")
            st.markdown("""
            1. **Check Supabase Dashboard**: Go to https://supabase.com/dashboard and verify your project is active
            2. **Resume project** if it's paused (free tier pauses after 1 week of inactivity)
            3. **Change DNS**: Use Google DNS (8.8.8.8) or Cloudflare (1.1.1.1) - see `FIX_DNS_WINDOWS.md`
            4. **Verify URL**: Make sure the URL in `secrets.toml` matches your project URL from Supabase dashboard
            """)
            st.markdown("📖 See `VERIFY_SUPABASE_PROJECT.md` and `FIX_DNS_WINDOWS.md` for detailed steps")
            if st.button("Dismiss warning", key="dismiss_conn_warning"):
                st.session_state.show_connectivity_warning = False
                st.rerun()
            return False
        return True
    except Exception:
        # If we can't check connectivity, just continue
        return True


# =====================================================
# LOGIN POPUP (MODAL)
# =====================================================
@st.dialog("🔐 Login or Sign Up", width="small")
def show_login_modal():
    """Toont login popup met email/password + Google login."""
    sb = init_supabase()

    # -----------------------------------------------
    # E-mail + wachtwoord login
    # -----------------------------------------------
    email = st.text_input("Email", key="login_email")
    password = st.text_input("Password", type="password", key="login_password")

    col1, col2 = st.columns(2)
    if col1.button("Login", key="login_btn"):
        try:
            if not email or not password:
                st.error("Please enter both email and password")
            else:
                res = sb.auth.sign_in_with_password({"email": email, "password": password})
                if res.user:
                    st.session_state.user = {"id": res.user.id, "email": res.user.email}
                    st.session_state.show_login = False
                    st.rerun()
                else:
                    st.error("Invalid credentials")
        except Exception as e:
            error_msg = str(e)
            if "getaddrinfo failed" in error_msg or "11001" in error_msg:
                st.error("🌐 Network/DNS Error: Cannot resolve Supabase domain")
                st.markdown("""
                **This is a DNS resolution issue. Try these steps:**
                1. **Flush DNS cache**: Open PowerShell as Admin and run `ipconfig /flushdns`
                2. **Check internet connection**: Make sure you can access other websites
                3. **Corporate network?**: Your firewall might be blocking Supabase. Try:
                   - Using a different network (mobile hotspot)
                   - Contacting IT to whitelist `*.supabase.co`
                4. **Change DNS**: Try using Google DNS (8.8.8.8) or Cloudflare (1.1.1.1)
                
                See `TROUBLESHOOTING_NETWORK.md` for detailed steps.
                """)
            elif "Invalid login credentials" in error_msg or "invalid" in error_msg.lower():
                st.error("Invalid email or password")
            else:
                st.error(f"Login failed: {error_msg}")

    if col2.button("Sign up", key="signup_btn"):
        try:
            if not email or not password:
                st.error("Please enter both email and password")
            elif len(password) < 6:
                st.error("Password must be at least 6 characters")
            else:
                res = sb.auth.sign_up({"email": email, "password": password})
                if res and res.user:
                    st.success("Account created! Please check your email for verification.")
                    st.session_state.user = {"id": res.user.id, "email": res.user.email}
                    st.session_state.show_login = False
                    st.rerun()
                else:
                    st.info("Check your email for verification link")
        except Exception as e:
            error_msg = str(e)
            if "getaddrinfo failed" in error_msg or "11001" in error_msg:
                st.error("🌐 Network/DNS Error: Cannot resolve Supabase domain")
                st.markdown("""
                **This is a DNS resolution issue. Try these steps:**
                1. **Flush DNS cache**: Open PowerShell as Admin and run `ipconfig /flushdns`
                2. **Check internet connection**: Make sure you can access other websites
                3. **Corporate network?**: Your firewall might be blocking Supabase. Try:
                   - Using a different network (mobile hotspot)
                   - Contacting IT to whitelist `*.supabase.co`
                4. **Change DNS**: Try using Google DNS (8.8.8.8) or Cloudflare (1.1.1.1)
                
                See `TROUBLESHOOTING_NETWORK.md` for detailed steps.
                """)
            elif "already registered" in error_msg.lower() or "user already exists" in error_msg.lower():
                st.warning("This email is already registered. Try logging in instead.")
            else:
                st.error(f"Signup failed: {error_msg}")

    st.markdown("---")

    # -----------------------------------------------
    # Dynamische redirect-URL (werkt lokaal én op Streamlit Cloud)
    # -----------------------------------------------
    # Get redirect URL - should be configured in Supabase dashboard
    # For local: http://localhost:8501
    # For Streamlit Cloud: https://your-app-name.streamlit.app
    try:
        # Check if we're on Streamlit Cloud
        server_url = os.getenv("STREAMLIT_SERVER_URL", "")
        if server_url and "streamlit.app" in server_url:
            redirect_url = server_url.rstrip('/')
        else:
            # Local development - try to detect port
            try:
                port = (
                    st.runtime.exists()
                    and st.runtime.get_instance()._runtime._server.server_port
                    or 8501
                )
                redirect_url = f"http://localhost:{port}"
            except Exception:
                redirect_url = "http://localhost:8501"
    except Exception:
        redirect_url = "http://localhost:8501"

    # -----------------------------------------------
    # Google-login knop
    # -----------------------------------------------
    if st.button("🔗 Sign in with Google", use_container_width=True):
        try:
            res = sb.auth.sign_in_with_oauth(
                {"provider": "google", "options": {"redirect_to": redirect_url}}
            )

            # ✅ Compatibel met alle supabase-py versies
            auth_url = None
            if isinstance(res, dict):
                auth_url = res.get("url")
            elif hasattr(res, "url"):
                auth_url = res.url

            if auth_url:
                st.markdown(
                    f"[👉 Continue with Google Login]({auth_url})",
                    unsafe_allow_html=True,
                )
            else:
                st.warning("Could not retrieve Google login URL.")
        except Exception as e:
            st.error(f"Google login failed: {e}")

    # -----------------------------------------------
    # Cancel-knop
    # -----------------------------------------------
    st.button(
        "Cancel",
        key="cancel_btn",
        on_click=lambda: st.session_state.update(show_login=False),
    )


# =====================================================
# AUTHENTICATION CHECK & SESSION MANAGEMENT
# =====================================================
def check_auth():
    """Check if user is authenticated. Returns True if authenticated, False otherwise.
    Does not block the app if authentication fails - authentication is optional."""
    try:
        sb = init_supabase()
    except ValueError as e:
        # Configuration error - silently fail (auth is optional)
        return False
    except Exception as e:
        # Other errors - silently fail (auth is optional)
        return False
    
    # Check for OAuth callback in URL first (before checking session)
    query_params = st.query_params
    if "code" in query_params or "access_token" in query_params or "error" in query_params:
        try:
            # Handle OAuth callback
            if "error" in query_params:
                error = query_params.get("error", "Unknown error")
                st.error(f"Authentication failed: {error}")
                st.query_params.clear()
                return False
            
            # Prevent infinite loop - track retry count
            oauth_retry_key = "oauth_retry_count"
            retry_count = st.session_state.get(oauth_retry_key, 0)
            
            if retry_count > 3:
                # Too many retries - clear and show error
                st.error("❌ OAuth authentication failed after multiple attempts.")
                st.info("Please try logging in again. If the problem persists, check your Supabase OAuth configuration.")
                st.query_params.clear()
                st.session_state[oauth_retry_key] = 0
                return False
            
            # For OAuth, we need to exchange the code for a session
            # Check if we have a code in the URL
            if "code" in query_params:
                code = query_params["code"]
                try:
                    # Get the redirect URL that was used
                    try:
                        server_url = os.getenv("STREAMLIT_SERVER_URL", "")
                        if server_url and "streamlit.app" in server_url:
                            redirect_url = server_url.rstrip('/')
                        else:
                            port = (
                                st.runtime.exists()
                                and st.runtime.get_instance()._runtime._server.server_port
                                or 8501
                            )
                            redirect_url = f"http://localhost:{port}"
                    except:
                        redirect_url = "http://localhost:8501"
                    
                    # Try using Supabase client's session_from_url method if available
                    # Otherwise, manually exchange the code
                    url = st.secrets["supabase"]["url"]
                    anon_key = st.secrets["supabase"]["anon_key"]
                    
                    # Supabase OAuth callback sets session via cookies in browser
                    # But in Streamlit server-side, we need to manually exchange the code
                    # Try to get session - Supabase might have set it via the redirect
                    try:
                        user_response = sb.auth.get_user()
                        if user_response and user_response.user:
                            # Session was set successfully
                            email = user_response.user.email
                            if not email and user_response.user.user_metadata:
                                email = user_response.user.user_metadata.get("email") or user_response.user.user_metadata.get("preferred_username", "Unknown")
                            
                            st.session_state.user = {
                                "id": user_response.user.id,
                                "email": email or "Unknown"
                            }
                            st.query_params.clear()
                            st.session_state[oauth_retry_key] = 0
                            st.rerun()
                            return True
                    except:
                        pass
                    
                    # If session not set, try manual exchange
                    # Note: Supabase OAuth uses PKCE which requires code_verifier
                    # Without it, we can't exchange the code server-side
                    # The best solution is to use a client-side redirect page
                    st.error("❌ OAuth session not available")
                    st.markdown("""
                    **OAuth in Streamlit requires special handling:**
                    
                    Supabase OAuth uses browser cookies for session management, which doesn't work 
                    directly in Streamlit's server-side environment.
                    
                    **Solution:** Use email/password authentication instead, or implement a 
                    client-side OAuth callback handler.
                    
                    For now, please use the email/password login option.
                    """)
                    
                    st.query_params.clear()
                    st.session_state[oauth_retry_key] = 0
                    return False
                except Exception as e:
                    st.error(f"❌ OAuth error: {e}")
                    st.query_params.clear()
                    st.session_state[oauth_retry_key] = 0
                    return False
            elif "access_token" in query_params:
                # Direct access token (less common)
                # Supabase should handle this automatically
                user_response = sb.auth.get_user()
                if user_response and user_response.user:
                    email = user_response.user.email
                    if not email and user_response.user.user_metadata:
                        email = user_response.user.user_metadata.get("email") or user_response.user.user_metadata.get("preferred_username", "Unknown")
                    st.session_state.user = {
                        "id": user_response.user.id,
                        "email": email or "Unknown"
                    }
                    st.query_params.clear()
                    st.session_state[oauth_retry_key] = 0
                    st.rerun()
                    return True
                else:
                    st.error("❌ OAuth token received but session not created.")
                    st.query_params.clear()
                    st.session_state[oauth_retry_key] = 0
                    return False
                
        except Exception as e:
            error_msg = str(e)
            # If we can't get user, the callback might have failed
            if "error" not in query_params:
                # Clear retry count and show error
                st.session_state["oauth_retry_count"] = 0
                st.error(f"❌ Authentication error: {error_msg}")
                st.info("Please try logging in again. If the problem persists, check your Supabase OAuth redirect URL configuration.")
                st.query_params.clear()
            else:
                st.query_params.clear()
            return False
    
    # Check if we have a user in session state
    if st.session_state.get("user"):
        # If we have an OAuth token stored, verify it's still valid
        if st.session_state.get("supabase_access_token"):
            try:
                # Verify token by making API call
                url = st.secrets["supabase"]["url"]
                anon_key = st.secrets["supabase"]["anon_key"]
                user_url = f"{url}/auth/v1/user"
                user_headers = {
                    "apikey": anon_key,
                    "Authorization": f"Bearer {st.session_state.supabase_access_token}"
                }
                user_response = requests.get(user_url, headers=user_headers)
                
                if user_response.status_code == 200:
                    user_data = user_response.json()
                    email = user_data.get("email")
                    if not email and user_data.get("user_metadata"):
                        email = user_data["user_metadata"].get("email") or user_data["user_metadata"].get("preferred_username", "Unknown")
                    
                    st.session_state.user = {
                        "id": user_data.get("id"),
                        "email": email or st.session_state.user.get("email", "Unknown")
                    }
                    return True
                else:
                    # Token expired - try to refresh
                    if st.session_state.get("supabase_refresh_token"):
                        try:
                            refresh_url = f"{url}/auth/v1/token?grant_type=refresh_token"
                            refresh_data = {"refresh_token": st.session_state.supabase_refresh_token}
                            refresh_headers = {"apikey": anon_key, "Content-Type": "application/json"}
                            refresh_response = requests.post(refresh_url, json=refresh_data, headers=refresh_headers)
                            
                            if refresh_response.status_code == 200:
                                token_data = refresh_response.json()
                                st.session_state.supabase_access_token = token_data.get("access_token")
                                st.session_state.supabase_refresh_token = token_data.get("refresh_token")
                                # Retry getting user
                                user_response = requests.get(user_url, headers={
                                    "apikey": anon_key,
                                    "Authorization": f"Bearer {st.session_state.supabase_access_token}"
                                })
                                if user_response.status_code == 200:
                                    user_data = user_response.json()
                                    email = user_data.get("email")
                                    if not email and user_data.get("user_metadata"):
                                        email = user_data["user_metadata"].get("email") or user_data["user_metadata"].get("preferred_username", "Unknown")
                                    st.session_state.user = {
                                        "id": user_data.get("id"),
                                        "email": email or "Unknown"
                                    }
                                    return True
                        except:
                            pass
                    
                    # Token invalid and couldn't refresh
                    st.session_state.user = None
                    st.session_state.supabase_access_token = None
                    st.session_state.supabase_refresh_token = None
                    return False
            except Exception:
                # Error verifying token
                st.session_state.user = None
                return False
        else:
            # Regular session (email/password) - verify with Supabase client
            try:
                user_response = sb.auth.get_user()
                if user_response and user_response.user:
                    # Update session state with current user info
                    st.session_state.user = {
                        "id": user_response.user.id,
                        "email": user_response.user.email or user_response.user.user_metadata.get("email", st.session_state.user.get("email", "Unknown"))
                    }
                    return True
                else:
                    # Session expired or invalid
                    st.session_state.user = None
                    return False
            except Exception:
                # Session expired or invalid
                st.session_state.user = None
                return False
    
    # No user in session state - try to get from Supabase session (might be from email/password login)
    try:
        user_response = sb.auth.get_user()
        if user_response and user_response.user:
            # Found a valid session
            st.session_state.user = {
                "id": user_response.user.id,
                "email": user_response.user.email or user_response.user.user_metadata.get("email", "Unknown")
            }
            return True
    except Exception:
        # No valid session
        pass
    
    return False


def require_auth():
    """Require authentication. Shows login modal if not authenticated.
    Note: This function is kept for backward compatibility but is no longer used
    since authentication is now optional."""
    # Check connectivity first (outside cached function to avoid widget warnings)
    check_connectivity_and_show_warning()
    
    if not check_auth():
        # Show login modal if requested
        if st.session_state.get("show_login", False):
            show_login_modal()
        else:
            # Show login prompt
            st.warning("🔐 Please log in to access this application.")
            if st.button("👤 Login / Sign Up", key="require_login_btn"):
                st.session_state.show_login = True
                st.rerun()
            st.stop()


# =====================================================
# LOGIN ICON (TOP RIGHT)
# =====================================================
def login_icon():
    """Login / profile control in the sidebar (opened via Streamlit hamburger)."""

    # Place login/profile control in the sidebar (opened via the default hamburger)
    with st.sidebar:
        # Check if user is logged in (check both session state and Supabase session)
        user_logged_in = False
        user_email = None
        
        if st.session_state.get("user"):
            user_logged_in = True
            user_email = st.session_state.user.get("email", "Unknown")
        else:
            # Try to get user from Supabase session (might be from OAuth)
            try:
                sb = init_supabase()
                user_response = sb.auth.get_user()
                if user_response and user_response.user:
                    user_logged_in = True
                    email = user_response.user.email
                    if not email and user_response.user.user_metadata:
                        email = user_response.user.user_metadata.get("email") or user_response.user.user_metadata.get("preferred_username", "Unknown")
                    user_email = email or "Unknown"
                    # Update session state
                    st.session_state.user = {
                        "id": user_response.user.id,
                        "email": user_email
                    }
            except Exception:
                pass
        
        if user_logged_in and user_email:
            # Extract username from email
            username = user_email.split('@')[0] if '@' in user_email else user_email
            label = f"👤 {username}"
            if st.button(label, key="logout_btn", use_container_width=True):
                # Clear OAuth tokens if present
                if st.session_state.get("supabase_access_token"):
                    # Revoke token via Supabase API
                    try:
                        url = st.secrets["supabase"]["url"]
                        anon_key = st.secrets["supabase"]["anon_key"]
                        logout_url = f"{url}/auth/v1/logout"
                        logout_headers = {
                            "apikey": anon_key,
                            "Authorization": f"Bearer {st.session_state.supabase_access_token}"
                        }
                        requests.post(logout_url, headers=logout_headers)
                    except:
                        pass
                    st.session_state.supabase_access_token = None
                    st.session_state.supabase_refresh_token = None
                
                # Clear regular session
                sb = init_supabase()
                try:
                    sb.auth.sign_out()
                except Exception:
                    pass
                
                st.session_state.user = None
                st.rerun()
        else:
            if st.button("👤 Login", key="loginbtn", help="Login / Profile", use_container_width=True):
                st.session_state.show_login = True
                st.rerun()
    
    # Show login modal if requested
    if st.session_state.get("show_login", False):
        show_login_modal()