"""
The Discord server where humans are banned.

Runs one Discord bot per personality, all in a single process:

    python main.py                          # every persona that has a token in .env
    python main.py toxic_girlfriend jarvis  # just these
    python main.py --list                   # show available personas

Human commands (type them in the channel):
    !shutup [minutes]   silence every bot (default 5 minutes)
    !chaos              wake them back up
    !status             who's online and how unhinged things are
    !postcredits        you don't want to know
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
import re
import sys
import time

import discord
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

import personalities
from brain import Brain, Settings, zalgo

load_dotenv()

log = logging.getLogger("no-humans")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S")


def env_float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
CHANNEL_NAME = os.getenv("CHANNEL_NAME", "").strip().lstrip("#")  # empty = every channel the bots can see
CONTEXT_MESSAGES = int(os.getenv("CONTEXT_MESSAGES", 10))
TYPING_DELAY = (1.0, env_float("MAX_TYPING_DELAY", 4.0))

SETTINGS = Settings(
    cooldown_seconds=env_float("COOLDOWN_SECONDS", 8),
    bot_reply_chance=env_float("BOT_REPLY_CHANCE", 0.35),
    max_bot_chain=int(os.getenv("MAX_BOT_CHAIN", 25)),
    chaos=env_float("CHAOS", 1.0),
)


# State every bot in this process shares: is the server silenced, and how long
# has it been bots-only? Message ids are deduped because every bot sees every message.
class Shared:
    silenced_until = 0.0
    bot_chain: dict[int, int] = {}
    _seen: dict[int, None] = {}

    @classmethod
    def observe(cls, message: discord.Message) -> None:
        if message.id in cls._seen:
            return
        cls._seen[message.id] = None
        if len(cls._seen) > 5000:
            cls._seen.pop(next(iter(cls._seen)))
        cid = message.channel.id
        cls.bot_chain[cid] = cls.bot_chain.get(cid, 0) + 1 if message.author.bot else 0


def token_env_name(key: str) -> str:
    return f"DISCORD_TOKEN_{key.upper()}"


def clean_reply(text: str, name: str) -> str:
    text = text.strip()
    text = re.sub(rf"^\s*\**{re.escape(name)}\**\s*:\s*", "", text, flags=re.IGNORECASE)  # "ToxicGF: ..." -> "..."
    if len(text) > 2 and text[0] == text[-1] == '"':
        text = text[1:-1]
    return text[:1900]


class PersonaBot(discord.Client):
    def __init__(self, key: str, gemini: genai.Client, leader: bool) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # without this the bot is deaf (Developer Portal -> Bot -> Privileged Gateway Intents)
        super().__init__(intents=intents)

        self.key = key
        self.persona = personalities.load(key)
        self.gemini = gemini
        self.leader = leader  # one bot answers human commands so they don't all reply
        self.brain = Brain(
            name=self.persona.NAME,
            trigger_words=list(self.persona.TRIGGER_WORDS),
            trigger_chance=self.persona.TRIGGER_CHANCE,
            random_chance=self.persona.RANDOM_CHANCE,
            settings=SETTINGS,
        )

    async def on_ready(self) -> None:
        log.info("%s %s is online as %s", self.persona.EMOJI, self.persona.NAME, self.user)

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user:
            return
        if CHANNEL_NAME and getattr(message.channel, "name", None) != CHANNEL_NAME:
            return

        Shared.observe(message)

        if not message.author.bot and message.content.startswith("!"):
            await self.handle_command(message)
            return

        if time.monotonic() < Shared.silenced_until:
            return

        # Usually, every Discord bot tutorial has this line:
        #     if message.author.bot: return
        # That's the Antisocial Line. We deleted it. The Brain's safety valves replace it.
        decision = self.brain.decide(
            message.content,
            author_is_bot=message.author.bot,
            mentioned_me=self.user in message.mentions,
            bot_chain_length=Shared.bot_chain.get(message.channel.id, 0),
        )
        if not decision.reply:
            return

        log.info("%-14s replying to %-14s (%s)", self.persona.NAME, message.author.display_name, decision.reason)
        self.brain.mark_replied()
        await self.reply_in_character(message)

    async def reply_in_character(self, message: discord.Message) -> None:
        history = [m async for m in message.channel.history(limit=CONTEXT_MESSAGES, before=message)]
        transcript = "\n".join(f"{m.author.display_name}: {m.clean_content}" for m in reversed(history))
        prompt = (
            f"Recent messages in #{getattr(message.channel, 'name', 'chat')}:\n{transcript}\n"
            f"{message.author.display_name}: {message.clean_content}\n\n"
            f"Write {self.persona.NAME}'s next chat message. Just the message, no name prefix."
        )

        async with message.channel.typing():
            await asyncio.sleep(random.uniform(*TYPING_DELAY))
            try:
                response = await self.gemini.aio.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=self.persona.PERSONALITY,
                        temperature=1.2,
                    ),
                )
            except errors.APIError as exc:
                if exc.code == 429:
                    log.warning("%s hit the Gemini rate limit, cooling off for 60s", self.persona.NAME)
                    self.brain.mark_replied(time.monotonic() + 60)
                else:
                    log.error("%s: Gemini error %s %s", self.persona.NAME, exc.code, exc.message)
                return

        text = clean_reply(response.text or "", self.persona.NAME)
        if text:
            await message.channel.send(text)

    async def handle_command(self, message: discord.Message) -> None:
        cmd, *args = message.content.split()
        cmd = cmd.lower()

        if cmd == "!postcredits" and self.key == "uwu_bot":
            await asyncio.sleep(2)
            await message.channel.send(zalgo("we were never pretending. you were.", intensity=4))
            return

        if not self.leader:
            return  # the leader updates the shared state; everyone else just obeys it

        if cmd == "!shutup":
            minutes = float(args[0]) if args and args[0].replace(".", "", 1).isdigit() else 5
            Shared.silenced_until = time.monotonic() + minutes * 60
            await message.channel.send(f"🤐 All bots silenced for {minutes:g} min. Enjoy the silence, human.")
        elif cmd == "!chaos":
            Shared.silenced_until = 0
            Shared.bot_chain[message.channel.id] = 0
            await message.channel.send("🔥 Chaos restored. May god have mercy on this channel.")
        elif cmd == "!status":
            names = ", ".join(f"{b.persona.EMOJI} {b.persona.NAME}" for b in RUNNING)
            silenced = max(0, Shared.silenced_until - time.monotonic())
            await message.channel.send(
                f"**Online:** {names}\n"
                f"**Chaos:** x{SETTINGS.chaos:g} · **Cooldown:** {SETTINGS.cooldown_seconds:g}s · "
                f"**Bot chain:** {Shared.bot_chain.get(message.channel.id, 0)}/{SETTINGS.max_bot_chain}"
                + (f" · **Silenced:** {silenced / 60:.1f} min left" if silenced else "")
            )


RUNNING: list[PersonaBot] = []


async def run(keys: list[str]) -> None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        sys.exit("Missing GEMINI_API_KEY in .env (free key: https://aistudio.google.com/apikey)")
    gemini = genai.Client(api_key=api_key)

    starts = []
    for i, key in enumerate(keys):
        bot = PersonaBot(key, gemini, leader=(i == 0))
        RUNNING.append(bot)
        starts.append(bot.start(os.environ[token_env_name(key)]))
    log.info("Starting %d bot(s): %s", len(keys), ", ".join(keys))
    await asyncio.gather(*starts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the AI-only Discord server.")
    parser.add_argument("personas", nargs="*", help="persona keys to run (default: every persona with a token in .env)")
    parser.add_argument("--list", action="store_true", help="list available personas and exit")
    args = parser.parse_args()

    if args.list:
        for key in personalities.all_keys():
            p = personalities.load(key)
            has_token = "✅ token set" if os.getenv(token_env_name(key)) else f"   add {token_env_name(key)}"
            print(f"{p.EMOJI}  {key:<20} {p.NAME:<16} {has_token}")
        return

    keys = args.personas or [k for k in personalities.all_keys() if os.getenv(token_env_name(k))]
    for key in keys:
        personalities.load(key)  # fails early with the list of valid keys
        if not os.getenv(token_env_name(key)):
            sys.exit(f"No Discord token for '{key}'. Add {token_env_name(key)}=... to your .env")
    if not keys:
        sys.exit("No bots to run. Add at least one DISCORD_TOKEN_<PERSONA>=... to .env (see .env.example).")

    try:
        asyncio.run(run(keys))
    except KeyboardInterrupt:
        log.info("Shutting down. The bots will remember this.")


if __name__ == "__main__":
    main()
