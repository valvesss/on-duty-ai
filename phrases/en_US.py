"""en-US pack. Item = a line (str) or a combo (list of lines spoken in sequence).
Placeholders: {time} = time on the phone, {n} = nag number, {name} = your name (lines with {name}
are only used when you set a name). Escalation: gentle → sarcastic → firm → drama → chaos."""

LEVELS = [
    # 1 — gentle
    [
        "Hey. Phone in hand? Back to the screen.",
        "Psst. That's not work.",
        "Quick reminder: the code won't write itself.",
        "Phone detected. Shall we go back?",
        "Remember what you were doing? Yeah. Go back to that.",
        ["Quick question.", "Is that more important than your work?"],
        "Scrolling the feed? Scroll back to your editor.",
        "That's {time} already. Put the phone down.",
        "Phone down, eyes up.",
        "Back in the game.",
        "{name}, phone in hand? Back to the screen.",
        "Hey {name}, your work misses you.",
        ["{name}.", "Just {name}.", "Come back."],
    ],
    # 2 — sarcastic
    [
        "Great video, huh? Shame it doesn't pay your bills.",
        "{time} on the phone. The algorithm thanks you for your service.",
        ["Breaking news.", "Nothing happened on the feed that you need to know.", "Go back."],
        "Congratulations, you're Instagram's employee of the month.",
        "Is that thumb training for a scrolling marathon?",
        "Your boss is watching. Kidding. But I am.",
        ["Let me guess.", "Just one more video, right?", "Classic."],
        "Every minute on that phone is one more bug in production.",
        "You're not resting. You're being farmed.",
        "Interesting. You're writing exactly zero lines of code right now.",
        "Nag number {n}. I've got all afternoon. Do you?",
        "{name}, you're the product right now, you know that?",
        ["Guess who's been scrolling for {time}?", "{name}. Yes, {name}."],
        "Lovely, {name}. Just lovely.",
    ],
    # 3 — firm
    [
        "{time} already. That's not a break anymore, that's an escape.",
        ["Put.", "The.", "Phone.", "Down."],
        "You'll look back and regret these {time}.",
        ["Here's the deal.", "Flip the phone face down.", "Now.", "I'll wait."],
        "Nobody on their deathbed says: I wish I'd watched more reels.",
        "Your tasks are piling up while you watch strangers dance.",
        "Seriously. Put the phone out of arm's reach. Now.",
        ["Deep breath.", "Let go of the phone.", "Hands on the keyboard.", "See? Easy."],
        "You asked me to bug you. So here it is: get back to work.",
        "The feed is infinite. Your day isn't.",
        "Nag {n}. I won't stop until you're back.",
        ["{name}.", "Look at me.", "Put that phone down."],
        "{name}, I'll keep saying your name until you come back. {name}. {name}.",
    ],
    # 4 — drama
    [
        ["Code red.", "Code red.", "Developer lost in the feed for {time}.", "Rescue team dispatched."],
        "I've seen careers end like this. It starts with just one more video.",
        ["Dear diary.", "Today it was {time} on the phone.", "Again.", "I'm so tired."],
        "Your future self is crying right now. Because of you.",
        ["Attention, attention.", "Subject is still on the phone.", "I repeat.", "Subject is still on the phone."],
        "Every time you scroll that feed, a commit dies alone.",
        "I'll keep talking. And talking. And talking. Until you come back.",
        ["Have you heard the legend of the one who just checked one notification?", "Never seen again."],
        "This is an intervention. Put the phone down.",
        ["Three.", "Two.", "One.", "Phone on the desk."],
        "{time}. You could have finished that task. Twice.",
        ["Attention, family of {name}.", "The feed has abducted {name}.", "Send help."],
        "{name}, your future self says: come back.",
    ],
    # 5 — chaos
    [
        ["I will not give up.", "I don't sleep.", "I don't blink.", "I am a webcam."],
        "Phone down, phone down, phone down, phone down.",
        ["Fine.", "Since you won't listen.", "I'll narrate your life.", "Still on the phone.", "Fascinating."],
        "Nag number {n}. This is a toxic relationship now. Between you and your phone.",
        ["If you go back to the keyboard now", "I promise I'll be quiet.", "Pinky promise."],
        "I'm losing my voice here. I've been talking to myself for {time}.",
        ["Breaking news.", "Local developer found scrolling for {time}.", "Witnesses say there was work to do."],
        ["Okay. Last try.", "Just kidding.", "I have infinite tries."],
        "Your phone's algorithm is good. But I'm more annoying.",
        ["Knock knock.", "Who's there?", "Your deadline.", "And it's winning."],
        "You're making me repeat myself. Put. That. Phone. Down.",
        ["{name}, {name}, {name}.", "I know you can hear me."],
        ["Final call for {name}.", "Now boarding at gate Work.", "This flight will not wait."],
    ],
]

# when you get back to the keyboard, by time spent on the phone
BACK = {
    "quick": ["Nice! That was quick.", "That's it. Focus.", "Good. Didn't even hurt.", "Way to go, {name}."],
    "medium": ["Finally. Let's go.", "Look who's back. Let's work.", "Phew. There we go.", "Right on time, {name}. Now stay."],
    "long": [
        "Finally! {time}. Let's not talk about it.",
        "{time} later, the legend returns. Let's make up for lost time.",
        "Back. I was about to call the fire department.",
        "{name} is back after {time}! Nobody say anything, just work.",
    ],
}
