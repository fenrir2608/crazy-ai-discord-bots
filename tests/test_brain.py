import random

from brain import Brain, Settings, zalgo


def make(seed=0, **settings):
    return Brain(
        name="ToxicGF",
        trigger_words=["busy", "who is she"],
        trigger_chance=0.5,
        random_chance=0.0,
        settings=Settings(cooldown_seconds=10, **settings),
        rng=random.Random(seed),
    )


def test_layer1_mention_always_replies():
    b = make()
    assert b.decide("hey toxicgf you there?", author_is_bot=True, now=100).reply
    assert b.decide("anything", author_is_bot=False, mentioned_me=True, now=100).reply


def test_layer2_trigger_word_rolls_dice():
    b = make(bot_reply_chance=1.0)
    hits = sum(make(seed=s, bot_reply_chance=1.0).decide("sorry I was busy", author_is_bot=False, now=100).reply for s in range(400))
    assert 150 < hits < 250  # ~50%
    assert not b.decide("nothing interesting here", author_is_bot=False, now=100).reply


def test_bots_are_less_interesting_than_humans():
    human = sum(make(seed=s, bot_reply_chance=0.1).decide("busy", author_is_bot=False, now=100).reply for s in range(400))
    bot = sum(make(seed=s, bot_reply_chance=0.1).decide("busy", author_is_bot=True, now=100).reply for s in range(400))
    assert bot < human / 3


def test_cooldown_blocks_even_mentions():
    b = make()
    b.mark_replied(now=100)
    assert b.decide("toxicgf!!", author_is_bot=False, now=105).reason == "cooldown"
    assert b.decide("toxicgf!!", author_is_bot=False, now=111).reply


def test_chain_breaker_waits_for_a_human():
    b = make(max_bot_chain=5)
    assert not b.decide("toxicgf", author_is_bot=True, bot_chain_length=5, now=100).reply
    assert b.decide("toxicgf", author_is_bot=False, bot_chain_length=5, now=100).reply


def test_zalgo_keeps_the_letters():
    out = zalgo("hello there", rng=random.Random(1))
    assert "".join(c for c in out if ord(c) < 0x300) == "hello there"
