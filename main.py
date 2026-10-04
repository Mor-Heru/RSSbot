import discord
from discord.ext import commands
from discord.ext import tasks
from dotenv import load_dotenv
import os
import feedparser
import csv
from datetime import datetime
import pytz

# Load the bot token from the project's environment file.
load_dotenv("discord.env")
token = os.getenv("DISCORD_TOKEN")
if token is None:
    raise ValueError("DISCORD_TOKEN is not set in discord.env")

intents=discord.Intents.default()
intents.message_content=True
bot=commands.Bot(command_prefix='!',intents=intents, help_command=None)
warsaw = pytz.timezone("Europe/Warsaw")
daily_update_enabled = True
daily_update_hour = 21
daily_update_minute = 14
last_daily_date = None

def checkIsExist(link):
    with open('rss_log.csv', 'r', encoding='utf-8') as file:
        reader = csv.reader(file)
        for row in reader:
            if len(row) > 1 and link == row[1]:
                return False
    return True 

def checkList(rss_url):
    with open('rss_list.csv', 'r', encoding='utf-8') as file:
        reader = csv.reader(file)
        for row in reader:
            if rss_url == row[0]:
                return True
    return False

async def get_rss_channel(channel_id: int):
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.NotFound:
            return None
    return channel

# Read each feed's destination channel ID from rss_list.csv and send new entries there.
async def update_rss():
    any_new = False
    destination_channels = {}
    with open('rss_list.csv', 'r', encoding='utf-8') as file:
        reader = csv.reader(file)
        for row in reader:
            if len(row) < 2:
                print(f"Skipping RSS row without a channel ID: {row}")
                continue

            try:
                channel_id = int(row[1])
            except ValueError:
                print(f"Skipping RSS row with an invalid channel ID: {row}")
                continue

            channel = destination_channels.get(channel_id)
            if channel is None:
                channel = await get_rss_channel(channel_id)
                if channel is None:
                    print(f"Channel {channel_id} not found")
                    continue
                destination_channels[channel_id] = channel

            feed = feedparser.parse(row[0])
            for entry in feed.entries:
                if "/shorts/" in entry.link:
                    continue
                if checkIsExist(entry.link):
                    any_new = True
                    parsed_date = datetime.fromisoformat(entry.published.replace('Z', '+00:00'))
                    formatted_date = parsed_date.strftime("%H:%M %d-%m-%Y")

                    message = f"{entry.title}\n{entry.link}\n{entry.author}\n{formatted_date}"
                    await channel.send(message)

                    with open('rss_log.csv', 'a', newline='', encoding='utf-8') as file:
                        writer = csv.writer(file)
                        writer.writerow([entry.title, entry.link, entry.author, formatted_date])

    if not any_new:
        for channel in destination_channels.values():
            await channel.send("Nothing new has been released!")
    return any_new

@tasks.loop(minutes=1)
async def daily_update():
    global last_daily_date
    if not daily_update_enabled:
        return

    now = datetime.now(warsaw)
    print(f"daily_update tick: {now.strftime('%Y-%m-%d %H:%M')} Warsaw")

    if now.hour != daily_update_hour or now.minute != daily_update_minute:
        return
    if last_daily_date == now.date():
        return

    last_daily_date = now.date()
    # The RSS CSV rows determine which channels receive their updates.
    await update_rss()

@daily_update.before_loop
async def before_daily_update():
    await bot.wait_until_ready()
    print("daily_update: bot ready, starting schedule")

@bot.event
async def on_ready():
    print(f"Ready to go, {bot.user.name}")
    if not daily_update.is_running():
        daily_update.start()
        print("Started daily_update loop")

@bot.command()
async def update(ctx):
    await update_rss()

@bot.command()
async def update_settings(ctx):
    if daily_update_enabled:
        await ctx.send(f"Daily update is enabled for {daily_update_hour:02d}:{daily_update_minute:02d} Warsaw.")
    else:
        await ctx.send("Daily update is currently disabled.")

@bot.command()
async def set_update(ctx, h: int = None, m: int = None):
    global daily_update_enabled, daily_update_hour, daily_update_minute, last_daily_date
    if h is None and m is None:
        daily_update_enabled = False
        last_daily_date = None
        await ctx.send("Daily updates disabled.")
        return
    if h is None or m is None:
        await ctx.send("Use: !set_update <hour> <minute> or !set_update to disable daily updates.")
        return
    if not (0 <= h < 24 and 0 <= m < 60):
        await ctx.send("Invalid time. Hour must be 0-23 and minute must be 0-59.")
        return

    daily_update_hour = h
    daily_update_minute = m
    daily_update_enabled = True
    last_daily_date = None
    await ctx.send(f"Daily update schedule set to {h:02d}:{m:02d} Warsaw.")

@bot.command()
async def add_rss(ctx,*, rss_url):
    if checkList(rss_url):
        await ctx.send("RSS already in list!")
    else:
        with open('rss_list.csv', 'a+', newline='', encoding='utf-8') as file:
            # Separate the new row if an older malformed file has no final newline.
            file.seek(0, os.SEEK_END)
            if file.tell() > 0:
                file.seek(file.tell() - 1)
                if file.read(1) not in ('\n', '\r'):
                    file.write('\n')
            writer = csv.writer(file)
            writer.writerow([rss_url, ctx.channel.id])
        await ctx.send("New RSS added!")

@bot.command()
async def show_log(ctx):
    with open('rss_log.csv', 'r', encoding='utf-8') as file:
        reader = csv.reader(file)
        for row in reader:
            await ctx.send(row)

@bot.command()
async def show_rss(ctx):
    with open('rss_list.csv', 'r', encoding='utf-8') as file:
        reader = csv.reader(file)
        for row in reader:
            if len(row) < 2:
                await ctx.send(f"{row[0]} — channel ID missing")
                continue
            channel = await bot.fetch_channel(int(row[1]))
            await ctx.send(f"{row[0]} — {channel.name}")

@bot.command()
async def del_rss(ctx,*, rss_url):
    rss_rows = []
    removed = False
    with open('rss_list.csv', 'r', encoding='utf-8') as file:
        reader = csv.reader(file)
        for row in reader:
            if row and row[0] == rss_url:
                removed = True
                continue
            rss_rows.append(row)

    if removed:
        with open('rss_list.csv', 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerows(rss_rows)
        await ctx.send("RSS deleted!")
    else:
        await ctx.send("RSS is not exist!")

@bot.command()
async def help(ctx):
    await ctx.send(
        "!update - Checks all RSS feeds and sends new entries\n"
        "!add_rss <url> - Adds a new RSS feed to the list. Example: !add_rss https://example.com/rss\n"
        "!show_rss - Lists all saved RSS feeds\n"
        "!show_log - Shows saved RSS entries from the log\n"
        "!del_rss <url> - Removes a RSS feed from the list. Example: !del_rss https://example.com/rss\n"
        "!update_settings - Shows whether daily update is enabled and the scheduled time\n"
        "!set_update <hour> <minute> - Sets the daily update time in Warsaw time\n"
        "!set_update - Disables daily updates\n"
        "!help - Displays this list of commands"
    )

bot.run(token)
