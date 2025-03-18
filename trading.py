import os
import re
import discord
from discord.ext import commands, tasks
from tradingview_ta import TA_Handler, Interval
import logging
from keep_alive import keep_alive
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
CHECK_INTERVAL = 29  # Check every 29 seconds

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('discord')

# Enable necessary intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

# Create the bot with command prefix "/"
bot = commands.Bot(command_prefix="/", intents=intents)

# Stored alerts: {guild_id: {symbol: {"target_price": price, "channel_id": channel_id}}}
alerts = {}

@bot.command()
async def alert(ctx, symbol: str, target_price: float):
    """
    Command usage:
    /alert GBPUSD 1.2999
    Stores an alert with the channel ID where the command was issued.
    """
    guild_id = ctx.guild.id
    channel_id = ctx.channel.id
    if guild_id not in alerts:
        alerts[guild_id] = {}
    alerts[guild_id][symbol.upper()] = {"target_price": target_price, "channel_id": channel_id}
    await ctx.send(f"✅ تم ضبط تنبيه لـ **{symbol.upper()}** عند السعر **{target_price}** في هذه القناة.")
    logger.debug(f"New alert added: {symbol.upper()} at {target_price} in guild {guild_id}")

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_prices():
    logger.debug("🔎 Checking prices...")
    # Iterate through alerts for each guild
    for guild_id, guild_alerts in list(alerts.items()):
        for symbol, alert_data in list(guild_alerts.items()):
            target_price = alert_data["target_price"]
            channel_id = alert_data["channel_id"]
            try:
                handler = TA_Handler(
                    symbol=symbol,
                    screener="forex",
                    exchange="OANDA",
                    interval=Interval.INTERVAL_5_MINUTES  # Using 5-minute candlesticks
                )
                analysis = handler.get_analysis()
                indicators = analysis.indicators
                high_price = float(indicators.get('high', 0))
                low_price = float(indicators.get('low', 0))
                logger.debug(f"{symbol}: High={high_price}, Low={low_price}, Target={target_price}")
                
                channel = bot.get_channel(channel_id)
                if channel:
                    if low_price <= target_price <= high_price:
                        await channel.send(
                            f"🚨 **تنبيه:** {symbol} وصل إلى السعر المطلوب **{target_price}** خلال آخر 5 دقائق!"
                        )
                        logger.info(f"Alert triggered for {symbol} at {target_price} in channel {channel_id}")
                        del alerts[guild_id][symbol]  # Remove alert to prevent duplicates
                    else:
                        # Send a confirmation message that the bot has read the data and target not reached
                        await channel.send(f"🔄 **{symbol}**: لم يصل إلى **{target_price}** بعد.")
            except Exception as e:
                logger.error(f"Error fetching data for {symbol}: {e}")

@bot.event
async def on_ready():
    logger.info(f"✅ Logged in as {bot.user}")
    
    # On startup, scan each text channel in every guild to restore untriggered alerts
    for guild in bot.guilds:
        for channel in guild.text_channels:
            try:
                # Get the last 50 messages from the channel
                messages = [msg async for msg in channel.history(limit=50)]
                for msg in messages:
                    # Only consider messages sent by the bot (Trading Alert)
                    if msg.author.id == bot.user.id:
                        content = msg.content
                        # Check for "alert set" messages (not the triggered alert message)
                        if "تم ضبط تنبيه" in content and "تنبيه:" not in content:
                            pattern = r"تم ضبط تنبيه لـ \*\*(.+?)\*\* عند السعر \*\*(.+?)\*\* في هذه القناة\."
                            match = re.search(pattern, content)
                            if match:
                                symbol_found = match.group(1).upper()
                                try:
                                    target_price_found = float(match.group(2))
                                except ValueError:
                                    continue
                                # Ensure there is no triggered alert message for the same symbol/price
                                alert_already_sent = False
                                for m in messages:
                                    if m.author.id == bot.user.id and "تنبيه:" in m.content:
                                        if symbol_found in m.content and str(target_price_found) in m.content:
                                            alert_already_sent = True
                                            break
                                if not alert_already_sent:
                                    if guild.id not in alerts:
                                        alerts[guild.id] = {}
                                    if symbol_found not in alerts[guild.id]:
                                        alerts[guild.id][symbol_found] = {
                                            "target_price": target_price_found,
                                            "channel_id": channel.id
                                        }
                                        logger.debug(f"Restored alert: {symbol_found} at {target_price_found} in channel {channel.id}")
            except Exception as e:
                logger.error(f"Error reading channel {channel.name}: {e}")
    
    check_prices.start()

# Start keep_alive server and run the bot
keep_alive()
bot.run(TOKEN)
