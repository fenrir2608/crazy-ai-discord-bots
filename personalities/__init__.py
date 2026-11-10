"""Persona registry: auto-discovers every persona module in this folder.

Drop a new ``something.py`` in here (copy ``_TEMPLATE.py``) and it is picked
up automatically. Files whose names start with an underscore are skipped.

    import personalities
    personalities.all_keys()            # ['crypto_bro', 'dramatic_narrator', ...]
    bot = personalities.load("jarvis")
    bot.NAME, bot.PERSONALITY
"""

import difflib
import importlib
import pkgutil

REQUIRED_FIELDS = (
    "NAME",
    "EMOJI",
    "TRIGGER_WORDS",
    "TRIGGER_CHANCE",
    "RANDOM_CHANCE",
    "PERSONALITY",
)


def all_keys():
    """Return a sorted list of every persona key (module name) in this folder."""
    return sorted(
        info.name
        for info in pkgutil.iter_modules(__path__)
        if not info.ispkg and not info.name.startswith("_")
    )


def load(key):
    """Import and return the persona module for ``key`` (e.g. ``"crypto_bro"``).

    Raises ValueError listing the available keys if ``key`` doesn't exist,
    and AttributeError if the persona file is missing a required field.
    """
    normalized = str(key).strip().lower().replace("-", "_")
    if normalized.endswith(".py"):
        normalized = normalized[:-3]

    keys = all_keys()
    if normalized not in keys:
        hint = difflib.get_close_matches(normalized, keys, n=1)
        did_you_mean = f" Did you mean '{hint[0]}'?" if hint else ""
        raise ValueError(
            f"No persona named '{key}'.{did_you_mean} "
            f"Available personas: {', '.join(keys) or '(none found)'}"
        )

    module = importlib.import_module(f"{__name__}.{normalized}")

    missing = [field for field in REQUIRED_FIELDS if not hasattr(module, field)]
    if missing:
        raise AttributeError(
            f"Persona '{normalized}' is missing required field(s): {', '.join(missing)}. "
            f"See personalities/_TEMPLATE.py for the expected shape."
        )
    return module
