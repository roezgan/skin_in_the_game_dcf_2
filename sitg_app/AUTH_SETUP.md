# Authentication Setup Guide

This app uses Supabase for authentication. Follow these steps to set up authentication:

## 1. Create a Supabase Project

1. Go to [supabase.com](https://supabase.com) and create a new project
2. Note your project URL and anon key from the project settings

## 2. Configure Streamlit Secrets

Create a `.streamlit/secrets.toml` file in your project root with the following structure:

```toml
[supabase]
url = "https://your-project-id.supabase.co"
anon_key = "your-anon-key-here"
```

## 3. Configure OAuth (Optional - for Google Login)

If you want to enable Google OAuth login:

1. Go to your Supabase project dashboard
2. Navigate to Authentication > Providers
3. Enable Google provider and configure it with your Google OAuth credentials
4. Add redirect URLs:
   - For local development: `http://localhost:8501`
   - For Streamlit Cloud: `https://your-app-name.streamlit.app`

## 4. Email Authentication

Email/password authentication works out of the box. Users can sign up and will receive a verification email.

## 5. Testing

1. Run your Streamlit app: `streamlit run app.py`
2. You should see a login prompt
3. Click "Login / Sign Up" to create an account or sign in
4. After authentication, you'll have access to all pages

## Notes

- All pages require authentication
- Session persists across page navigations
- Users can logout via the sidebar (hamburger menu)
- OAuth redirect URLs must match exactly what's configured in Supabase

