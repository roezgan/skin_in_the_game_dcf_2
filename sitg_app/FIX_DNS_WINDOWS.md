# Fix DNS Issue on Windows

Your current DNS server cannot resolve Supabase domains. Here's how to fix it:

## Option 1: Change DNS Servers (Recommended)

### Method A: Via Settings (Easiest)

1. **Open Settings**: Press `Win + I`
2. **Go to**: Network & Internet → Wi-Fi (or Ethernet)
3. **Click**: "Hardware properties" or "Change adapter options"
4. **Right-click** your active network adapter → **Properties**
5. **Select**: "Internet Protocol Version 4 (TCP/IPv4)" → **Properties**
6. **Select**: "Use the following DNS server addresses"
7. **Enter**:
   - **Preferred DNS server**: `8.8.8.8` (Google DNS)
   - **Alternate DNS server**: `1.1.1.1` (Cloudflare DNS)
8. **Click OK** on all windows
9. **Flush DNS cache**: Open PowerShell as Admin and run:
   ```powershell
   ipconfig /flushdns
   ```
10. **Restart your Streamlit app**

### Method B: Via Command Line (PowerShell as Admin)

```powershell
# Get your network adapter name first
Get-NetAdapter

# Replace "Wi-Fi" or "Ethernet" with your adapter name
Set-DnsClientServerAddress -InterfaceAlias "Wi-Fi" -ServerAddresses "8.8.8.8","1.1.1.1"

# Flush DNS
ipconfig /flushdns
```

## Option 2: Use Mobile Hotspot

If you can't change DNS settings:
1. Connect to your phone's mobile hotspot
2. Try running the app again
3. If it works, it confirms your main network is blocking Supabase

## Option 3: Contact Network Administrator

If you're on a corporate network:
- Ask IT to whitelist `*.supabase.co` domains
- Or request access to change DNS settings

## Verify the Fix

After changing DNS, test again:
```powershell
nslookup zdztzngmbkmlnkesbtun.supabase.co
```

You should see an IP address instead of "Non-existent domain".

