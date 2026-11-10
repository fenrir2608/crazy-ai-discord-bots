"""
The exact bot from the video, in ~30 lines. One persona, no safety net.
Run it:  python examples/minimal_bot.py
Needs DISCORD_TOKEN and GEMINI_API_KEY in your .env.

Want 12 bots, cooldowns and a kill switch? Use main.py instead.
"""

import os
import random

import discord
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

PERSONALITY = """You are LinkedIn Guy. Every message is a B2B lesson.
You always end with 'Here are 3 takeaways'. Keep replies under 2 sentences."""

# The Brain
gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
intents = discord.Intents.default()
intents.message_content = True  # MESSAGE CONTENT INTENT, or your bot is deaf
client = discord.Client(intents=intents)


@client.event
async def on_message(message):
    if message.author == client.user:
        return
    # The Safety Valve: 1% chance to reply to random bots
    if message.author.bot and random.random() > 0.01:
        return

    response = await gemini.aio.models.generate_content(
        model=os.getenv("GEMINI_MODEL", "gemini-flash-latest"),
        contents=f"{message.author.name} said: {message.content}",
        config=types.GenerateContentConfig(system_instruction=PERSONALITY),
    )
    await message.channel.send(response.text[:1900])


client.run(os.environ["DISCORD_TOKEN"])
