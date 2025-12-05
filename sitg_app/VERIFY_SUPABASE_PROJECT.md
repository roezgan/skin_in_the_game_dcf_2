# Verify Your Supabase Project

The DNS lookup shows that even Google DNS cannot resolve your specific Supabase project domain. This suggests:

## Possible Issues:

1. **Project is paused** - Supabase free tier projects pause after inactivity
2. **Project was deleted** - The project might have been removed
3. **Incorrect project URL** - The URL in secrets.toml might be wrong

## How to Verify:

### Step 1: Check Supabase Dashboard

1. Go to https://supabase.com/dashboard
2. Log in to your account
3. Check if your project `zdztzngmbkmlnkesbtun` exists
4. Check if it's **paused** (you'll see a "Resume" button)
5. If paused, click **"Resume"** to reactivate it

### Step 2: Get Correct Project URL

1. In Supabase Dashboard, go to your project
2. Click **Settings** → **API**
3. Copy the **Project URL** (should be `https://[project-ref].supabase.co`)
4. Verify it matches what's in your `.streamlit/secrets.toml`

### Step 3: Verify Project is Active

- If the project shows as "Paused", you need to resume it
- Free tier projects pause after 1 week of inactivity
- Resuming takes a few minutes

### Step 4: Test After Resume

After resuming, test DNS again:
```powershell
nslookup zdztzngmbkmlnkesbtun.supabase.co 8.8.8.8
```

It should now resolve to an IP address.

## Alternative: Create New Project

If the project was deleted or you can't access it:

1. Create a new Supabase project at https://supabase.com/dashboard
2. Get the new Project URL and anon key
3. Update `.streamlit/secrets.toml` with the new credentials

