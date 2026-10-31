# How the 2026 headline cards are written

The user asked for headlines a person would write, not a report. The title says the story in a few words; the
body carries the numbers. The four fixed cards pick their title by rules in `scripts/headlines26.py`; the extra
cards written on election night (`live/insights_night.json`, "headlines") follow the same voice.

## Voice

- Short, active, about people: leaders' names where readers know them (ביבי, בן גביר, סמוטריץ', איזנקוט, לפיד,
  ליברמן, יאיר גולן, הנדל, וינטר, דרעי, עבאס), groups of voters ("העשירים", "הצעירים", "הפריפריה", "הערבים",
  "החרדים") where the story is about them.
- Examples of the register: "ביבי שתה את סמוטריץ'", "בן גביר נגס בליכוד", "העשירים נטשו את לפיד",
  "איזנקוט ירש את גנץ", "הערבים נשארו בבית", "הבסיס של ביבי החזיק".
- Not: "הליכוד קיבל כך וכך קולות / מנדטים מהציונות הדתית". That sentence belongs in the body.
- No insults, nicknames that mock, or claims about motives ("נבגד", "ברחו מפחד"). Say what moved, not why.

## The verb must match the size

Judge on the low end of the 90% interval, as a share of the source list's 2022 voters:

| share of the source's voters | verb |
| --- | --- |
| 20% or more | שתה / בלע |
| 8% to 20% | נגס ב… |
| 4% to 8%, and at least about 1 seat | חדר לבסיס של… / לקח מ… |
| less | no headline about it |

"נטשו", "התפזרו", "נשארו בבית": only when the share leaving is clearly large (a third or more, or a turnout drop
the interval does not cross). "נשארו נאמנים": 80% or more stayed.

A group headline ("העשירים נטשו את לפיד") needs the group's own fit (`ses-*`, `sector:*`) with a narrow interval,
and a clear gap from the national figure; check in `ses_index.json` which cluster group is which before naming it.

## Card fields

- `title`: the headline, up to about 6 words.
- `big` and `unit`: the red number and its label of up to 3 words ("עזבו את הליכוד", "הגיעו מגנץ").
- `body`: the numbers in plain sentences, with the time and how much is counted if early.

- **One move, one headline.** No two cards may tell the same move (e.g. Yesh Atid to Yashar! from both sides), above all two cards side by side. headlines26.py replaces such a card with the largest move no card tells yet (or drops it); a card written by hand must also tell a move no other card tells.
- **A list that is not running was not bitten.** Its voters had to vote elsewhere (e.g. HaMahane HaMamlachti in 2026): say "ירש" with a share ("בנט ירש חמישית ממצביעי המחנה הממלכתי"), never "נגס" or "שתה".
- **Leaders by election.** 2026: Beyachad is led by Bennett (בנט); Yesh Atid runs inside it. Lapid (לפיד) led Yesh Atid in 2022, so he names Yesh Atid's 2022 voters ("מצביעי לפיד"), never the 2026 list.
- **No statistics in a card.** No "טווח 90%", intervals or method notes in a card's text: one sharp number and the message. The interval decides which verb a title may use; it is not written out.
- **At least 10 cards** on the night page: the fixed ones, the cluster card (the move that differs most between clusters 1-3 and 8-10, Jewish non-Haredi voters), then the largest untold moves (headlines26.make total=10 minus the cards written by hand).
- **What did not happen is news too.** A move people expect that stayed near zero is told, merged into the card on the same list where there is one ("הליכוד דימם ימינה, לא שמאלה"; "בנט לא הביא מצביעים מהימין" also tells where Beyachad's votes did come from). Two moves out of the same 2022 list share one card ("בן גביר וביבי נגסו בציונות הדתית").
