# 🚀 Deployment Setup Guide

To enable the automatic restart of your Discord bot when you push code, you need to configure 3 secrets in your GitHub repository.

## 1. Get Your Credentials

### **PTERODACTYL_API_KEY**
1. Log in to your control panel (e.g., `https://panel.bot-hosting.net`).
2. Go to **Account Settings** (usually click your avatar > Account).
3. Click on the **API Credentials** tab.
4. Create a new API Key.
5. **Copy it immediately** - you won't see it again.

### **PTERODACTYL_SERVER_ID**
1. Go to your server's console page.
2. Look at the URL in your browser.
3. It will look like this: `https://panel.bot-hosting.net/server/a1b2c3d4`
4. The ID is the part after `/server/`. In this example: `a1b2c3d4`.

### **PTERODACTYL_HOST**
1. This is simply the base URL of your panel.
2. Example: `https://panel.bot-hosting.net`
3. **Important:** Do NOT include a trailing slash `/` at the end.

## 2. Add Secrets to GitHub

1. Go to your GitHub Repository.
2. Click **Settings** > **Secrets and variables** > **Actions**.
3. Click **New repository secret**.
4. Add the following 3 secrets matching the values you found above:

| Name | Example Value |
|------|---------------|
| `PTERODACTYL_API_KEY` | `ptlc_your_long_api_key_here` |
| `PTERODACTYL_SERVER_ID` | `a1b2c3d4` |
| `PTERODACTYL_HOST` | `https://panel.bot-hosting.net` |

## 3. Test It!

Once these are set, simply push a change to your repository:
```bash
git add .
git commit -m "Testing auto-deploy"
git push
```
Go to the **Actions** tab in GitHub to watch it run. If it turns green, your server just restarted! 🔄
