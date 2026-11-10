"""
The "Social Anxiety" algorithm.

Decides whether a bot should reply to a message. No Discord or Gemini code in
here, so it's easy to read, tweak and test.

    Layer 1  Direct reply   -> mentioned by name or @? Always reply.
    Layer 2  Trigger word   -> heard a word it cares about? Roll TRIGGER_CHANCE.
    Layer 3  Random chance  -> feeling chaotic? Roll RANDOM_CHANCE.

Plus the safety valves that stop the server from melting in 4 seconds:
    - a per-bot cooldown
    - a lower chance to reply to other bots (the "1% safety valve")
    - a chain breaker: after N bot-only messages in a row, everyone goes quiet
      until a human speaks again
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field


@dataclass
class Settings:
    cooldown_seconds: float = 8.0      # min gap between two replies from the same bot
    bot_reply_chance: float = 0.35     # Layer 2/3 rolls are multiplied by this when the author is a bot
    max_bot_chain: int = 25            # bot-only messages in a row before the server goes quiet
    chaos: float = 1.0                 # global multiplier on every roll (2.0 = twice as chaotic)
    always_answer_mentions: bool = True


@dataclass
class Decision:
    reply: bool
    reason: str


@dataclass
class Brain:
    name: str
    trigger_words: list[str]
    trigger_chance: float
    random_chance: float
    settings: Settings = field(default_factory=Settings)
    rng: random.Random = field(default_factory=random.Random)
    _last_reply_at: float = 0.0

    def _mentioned(self, text: str, mentioned_me: bool) -> bool:
        if mentioned_me:
            return True
        return re.search(rf"\b{re.escape(self.name.lower())}\b", text.lower()) is not None

    def _heard_trigger(self, text: str) -> str | None:
        lowered = text.lower()
        for word in self.trigger_words:
            if re.search(rf"\b{re.escape(word.lower())}\b", lowered):
                return word
        return None

    def decide(
        self,
        text: str,
        *,
        author_is_bot: bool,
        mentioned_me: bool = False,
        bot_chain_length: int = 0,
        now: float | None = None,
    ) -> Decision:
        now = time.monotonic() if now is None else now

        if author_is_bot and bot_chain_length >= self.settings.max_bot_chain:
            return Decision(False, "chain breaker: too many bot messages in a row, waiting for a human")

        if now - self._last_reply_at < self.settings.cooldown_seconds:
            return Decision(False, "cooldown")

        # Layer 1: direct reply
        if self.settings.always_answer_mentions and self._mentioned(text, mentioned_me):
            return Decision(True, "layer 1: mentioned")

        # The safety valve: other bots are less interesting than humans
        valve = self.settings.bot_reply_chance if author_is_bot else 1.0
        chaos = self.settings.chaos

        # Layer 2: trigger word
        word = self._heard_trigger(text)
        if word and self.rng.random() < min(1.0, self.trigger_chance * valve * chaos):
            return Decision(True, f"layer 2: heard '{word}'")

        # Layer 3: random chance
        if self.rng.random() < min(1.0, self.random_chance * valve * chaos):
            return Decision(True, "layer 3: random chaos")

        return Decision(False, "stayed quiet")

    def mark_replied(self, now: float | None = None) -> None:
        self._last_reply_at = time.monotonic() if now is None else now


# ---------------------------------------------------------------------------
# Post-credit scene helper: make any text look possessed.
# ---------------------------------------------------------------------------

_ZALGO_UP = [chr(c) for c in range(0x0300, 0x0315)] + [chr(c) for c in (0x033D, 0x033E, 0x033F, 0x0346, 0x034A, 0x034B, 0x034C)]
_ZALGO_DOWN = [chr(c) for c in range(0x0316, 0x0334)]


def zalgo(text: str, intensity: int = 6, rng: random.Random | None = None) -> str:
    rng = rng or random.Random()
    out = []
    for ch in text:
        out.append(ch)
        if ch.isspace():
            continue
        out.extend(rng.choice(_ZALGO_UP) for _ in range(rng.randint(1, intensity)))
        out.extend(rng.choice(_ZALGO_DOWN) for _ in range(rng.randint(1, intensity)))
    return "".join(out)
