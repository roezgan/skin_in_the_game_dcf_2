# Network Connectivity Troubleshooting

If you're getting `[Errno 11001] getaddrinfo failed` when trying to sign up or login, this is a DNS resolution issue. Here are steps to fix it:

## Quick Fixes

### 1. Flush DNS Cache (Windows)
Open PowerShell or Command Prompt as Administrator and run:
```bash
ipconfig /flushdns
```

### 2. Check Internet Connection
Make sure you have an active internet connection and can access other websites.

### 3. Try Different DNS Server
If you're on a corporate network, the DNS server might be blocking Supabase. Try using a public DNS:

**Windows:**
1. Open Network Settings
2. Change adapter options
3. Right-click your network adapter → Properties
4. Select "Internet Protocol Version 4 (TCP/IPv4)" → Properties
5. Use these DNS servers:
   - Preferred: `8.8.8.8` (Google DNS)
   - Alternate: `1.1.1.1` (Cloudflare DNS)

### 4. Check Firewall/Proxy
If you're behind a corporate firewall or proxy:
- Contact your IT department to whitelist `*.supabase.co`
- Or configure proxy settings if required

### 5. Test DNS Resolution
Open Command Prompt and run:
```bash
nslookup zdztzngmbkmlnkesbtun.supabase.co
```

If this fails, it confirms a DNS issue.

### 6. Try from Different Network
Test if the issue persists on a different network (e.g., mobile hotspot) to determine if it's network-specific.

## Alternative: Use Supabase from Different Location
If you're in a restricted network environment, you might need to:
- Use a VPN
- Work from a different network
- Contact your network administrator

## Verify Supabase Project is Active
1. Go to https://supabase.com/dashboard
2. Check if your project is active and running
3. Verify the project URL matches what's in your `secrets.toml`

