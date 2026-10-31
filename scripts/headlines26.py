"""The four fixed election-night headlines, recomputed from the 2022-2026 pair on every update.

1. Likud 2022 voters: how many left, and to where.
2. Yashar! (Eisenkot): where its votes came from.
3. Yesh Atid 2022 voters: where they went (Yesh Atid runs inside Beyachad in 2026).
4. HaTzibur HaHaredi: how much of its vote came from Haredi ballot boxes and how much from others, read
   directly from the 2026 results (no model), plus, inside Haredi boxes, which 2022 lists it drew from.
5. Shas to UTJ inside Haredi boxes: a card only while the model and the raw box shares agree on the move.

make(site, k26) returns the cards; with k26=None (before results) every card is a placeholder.
build_site_live.py puts them first on the night page.

Titles: before results each card asks its question; with numbers the title becomes a headline a person would write
("בן גביר נגס בליכוד", "איזנקוט ירש את גנץ"), picked by rules on the size of the flow, so a strong verb only appears
when the move is large (judged on the low end of its 90% interval). The body keeps the exact numbers. Style guide for
the cards written by hand on the night: live/HEADLINES_STYLE.md.
"""
import json
import os

import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
PAIR = '25-26'
WAIT = 'המספר יופיע כאן כשתוצאות הקלפיות יהיו זמינות, ויתעדכן לאורך הספירה.'
DNV = 'לא הצביעו'


# the night cards, most interesting first (the big picture, then the surprises, then the details); any card not
# listed keeps its place after these
ORDER = ['blocs-2026', 'yashar-2026', 'likud-2026', 'beyachad-right-not-2026', 'far_right-otzma-2026', 'joint-dnv-2026',
         'winter-2026', 'shas-otzma-2026', 'ses-2026', 'shas-utj-2026', 'haredi-2026', 'arab-camps-2026', 'likud-left-not-2026']


def order(cards):
    """The cards in ORDER, the rest after them in their own order."""
    rank = {k: i for i, k in enumerate(ORDER)}
    return sorted(cards, key=lambda c: rank.get(c.get('id'), len(ORDER)))


def thousands(n):
    return f'{round(n / 1000):,}'


def dest(name):
    return {DNV: 'לא הצביעו', 'אחרים': 'רשימות קטנות'}.get(name, name)


def source(name):
    return {DNV: 'מי שלא הצביעו', 'אחרים': 'מצביעי רשימות קטנות'}.get(name, 'מצביעי ' + name)


def card(id_, title, big='—', unit='', body=WAIT, area='national', area_name='כל הארץ', links=None, pair=PAIR, src=None):
    # a card with numbers opens its pair in the chart; a placeholder has no pair; `src` (a fresh card's 2022 list)
    # lets a second move from the same list join it
    c = dict(id=id_, title=title, big=big, unit=unit, body=body, area=area, pair=None if body == WAIT else pair,
             area_name=area_name, links=links or [], check=None, view='last', group='ליל הבחירות 2026')
    if src:
        c['src'] = src
    return c


def flows(d, pair=PAIR):
    """(from name, from key, to name, to key, votes, pct of from, low end of its interval) for every link, or []."""
    p = (d or {}).get('pairs', {}).get(pair)
    if not p:
        return []
    return [(p['from'][l[0]][0], p['from'][l[0]][1], p['to'][l[1]][0], p['to'][l[1]][1], l[2], l[3],
             l[4] if len(l) > 4 and l[4] is not None else l[3]) for l in p['links']]


# who a list is in a headline: its leader where readers know one, else the list's own name
WHO = {'הליכוד': 'ביבי', 'עוצמה יהודית': 'בן גביר', 'הציונות הדתית': "סמוטריץ'", 'ישר!': 'איזנקוט', 'ביחד': 'בנט',
       'ישראל ביתנו': 'ליברמן', 'הדמוקרטים': 'יאיר גולן', 'המילואימניקים': 'הנדל', 'עמך ישראל': 'וינטר',
       'ש"ס': 'דרעי', 'רע"מ': 'עבאס'}
WHO22 = {'יש עתיד': 'לפיד', 'המחנה הממלכתי': 'גנץ', 'ישראל ביתנו': 'ליברמן', 'ש"ס': 'דרעי'}


def who(name):
    """(how a headline names a 2026 list, whether its verb is feminine): a leader is "he", a list's name "she"."""
    return (WHO[name], False) if name in WHO else (name, True)


# share of the source list's voters (low end of the interval) for each verb: שתה, נגס, חדר / לקח
SWALLOW, BITE, ENTER = 20, 8, 4


def took(name, victim, pct):
    """A headline for "list `name` won pct% of victim's voters": the verb grows with the share (low end of the interval)."""
    taker, fem = who(name)
    if pct >= SWALLOW:
        return f'{taker} {"שתתה" if fem else "שתה"} את {victim}'
    if pct >= BITE:
        return f'{taker} {"נגסה" if fem else "נגס"} {with_b(victim)}'
    return None


def with_b(name):
    """ב before a name: a list's name drops its ה (בליכוד), a person's name keeps it (בהנדל)."""
    people = set(WHO.values()) | set(WHO22.values())
    return 'ב' + (name[1:] if name.startswith('ה') and name not in people else name)


def kept(leader, pct):
    """"ביחד שמרה על שליש ממצביעי יש עתיד": the share of a 2022 list's voters that stayed with it (Yesh Atid runs
    inside Beyachad, led by Bennett), as a fraction a person would say."""
    part = next(w for lim, w in ((60, 'רוב'), (42, 'כחצי'), (29, 'שליש'), (21, 'רבע'), (0, 'מעט')) if pct >= lim)
    return f'{leader} שמרה על {part} {"מ" if part != "רוב" else ""}מצביעי יש עתיד'


RUNNING = set()  # keys of the 2026 lists, set by make() from the national fit


def runs(F, key):
    """Whether a 2022 list runs again in 2026 (Yesh Atid inside Beyachad): voters of a list that does not run had to
    vote elsewhere, so a move from it is an inheritance, never "biting" into it. Read from the national lists, as a
    small area may have no flow to a list that does run."""
    return key in RUNNING or (key == 'yeshatid' and 'beyachad' in RUNNING) or key in ('dnv', 'other')


def inherited(name, source22, pct):
    """"בנט ירש חמישית ממצביעי המחנה הממלכתי": the share of a list's 2022 voters, a list that is not running now."""
    part = next(w for lim, w in ((60, 'את רוב '), (42, 'כחצי מ'), (29, 'שליש מ'), (23, 'רבע מ'), (17, 'חמישית מ'),
                                 (0, 'חלק מ')) if pct >= lim)
    taker, fem = who(name)
    return f'{taker} {"ירשה" if fem else "ירש"} {part}{source(source22)}'


def with_l(name):
    """ל before a list's name, which drops its ה (לליכוד)."""
    return 'ל' + (name[1:] if name.startswith('ה') else name)


def entered(name, victim):
    taker, fem = who(name)
    return f'{taker} {"חדרה" if fem else "חדר"} לבסיס של {victim}'


def haredi_share(k26):
    """Share of זך votes cast in Haredi boxes: boxes where Shas, UTJ and HaTzibur HaHaredi together took at least 60% of valid votes."""
    cfg = json.load(open(os.path.join(ROOT, 'config/parties.json')))
    codes = cfg['sector_parties']['haredi']['26']
    df = pd.read_csv(k26, encoding='utf-8-sig', dtype=str)
    df.columns = [c.strip() for c in df.columns]
    if 'זך' not in df.columns:
        return None
    num = lambda c: pd.to_numeric(df[c], errors='coerce').fillna(0) if c in df.columns else 0
    valid, z = num('כשרים'), num('זך')
    har = sum(num(c) for c in codes)
    box = (valid > 0) & (har >= 0.6 * valid)
    total = z[valid > 0].sum()
    if total < 1000:
        return None
    out = dict(total=total, inside=z[box].sum() / total * 100,
               # its share of all valid votes in Haredi boxes: how much of the Haredi vote it took
               of_haredi=z[box].sum() / valid[box].sum() * 100)
    # abstention in the counted Haredi boxes, and in the same boxes (locality + ballot number) in 2022
    bzb, voters = num('בזב'), num('מצביעים')
    out['abstain'] = (1 - voters[box].sum() / bzb[box].sum()) * 100
    k25 = pd.read_csv(os.path.join(ROOT, 'data/raw/k25.csv'), encoding='utf-8-sig')
    key = lambda f: f['סמל ישוב'].astype(str).str.strip() + '|' + pd.to_numeric(f['קלפי'], errors='coerce').round(1).astype(str)
    old = k25[key(k25).isin(set(key(df[box])))]
    if len(old) >= 20:
        out['abstain22'] = (1 - old['מצביעים'].sum() / old['בזב'].sum()) * 100
    return out


def make(site, k26=None, area='national', area_name='כל הארץ', taken=(), total=0):
    """The 2026 cards; for another area (a city, a sector) only the three flow cards, from that area's own fit.
    `taken`: [from, to] moves that other cards on the page (the ones written on the night) already tell; `total`: the
    number of national cards to reach with further moves (the night's own cards not counted)."""
    load = lambda a: json.load(open(os.path.join(site, 'data', a.replace(':', '-') + '.json'))) if os.path.exists(os.path.join(site, 'data', a.replace(':', '-') + '.json')) else None
    nat = load(area) if k26 else None
    mk = lambda *x, **kw: card(*x, area=area, area_name=area_name, **kw)
    F = flows(nat)
    RUNNING.clear()
    RUNNING.update(f[3] for f in flows(load('national') if k26 else None))
    cards = []

    # 1. Likud
    t = 'כמה מצביעי ליכוד עזבו, ולאן?'
    out = sorted([f for f in F if f[1] == 'likud' and f[3] != 'likud'], key=lambda f: -f[4])
    stay = next((f for f in F if f[1] == 'likud' and f[3] == 'likud'), None)
    if stay and out:
        top = out[:3]
        f = next((x for x in out if x[3] != 'other'), out[0])
        if f[3] == 'dnv' and f[6] >= 10:
            t = 'מצביעי ליכוד נשארו בבית'
        elif f[3] not in ('dnv', 'other') and took(f[2], 'הליכוד', f[6]):
            t = took(f[2], 'הליכוד', f[6])
        elif f[3] not in ('dnv', 'other') and f[6] >= ENTER:
            t = entered(f[2], 'ביבי')
        elif stay[5] >= 85:
            t = 'הבסיס של ביבי החזיק'
        cards.append(mk('likud-2026', t, f'{100 - stay[5]:.0f}%', 'עזבו את הליכוד', (
            f'כ-{stay[5]:.0f}% ממצביעי הליכוד ב-2022 הצביעו שוב לליכוד. לאן הלכו מי שעזבו: ' +
            ', '.join(f'{dest(f[2])} (כ-{thousands(f[4])} אלף)' for f in top) + '.'),
            links=[[f[0], f[2]] for f in top]))
    else:
        cards.append(mk('likud-2026', t))

    # 2. Yashar! (Eisenkot)
    t = 'מאיפה הגיעו המצביעים של איזנקוט?'
    inn = sorted([f for f in F if f[3] == 'yashar'], key=lambda f: -f[4])
    tot = sum(f[4] for f in inn)
    if inn and tot > 0:
        top = inn[:3]
        sh = [f[4] / tot * 100 for f in top]
        f = top[0]
        if f[1] == 'yeshatid' and sh[0] >= 40:
            t = 'איזנקוט בנה את עצמו על מצביעי לפיד'
        elif f[0] == 'המחנה הממלכתי' and sh[0] >= 40:
            t = 'איזנקוט ירש את גנץ'
        elif f[1] == 'dnv' and sh[0] >= 25:
            t = 'איזנקוט הוציא אנשים מהבית'
        elif f[1] == 'likud' and sh[0] >= 20:
            t = entered('ישר!', 'ביבי')
        elif f[1] not in ('dnv', 'other') and not runs(F, f[1]) and sh[0] >= 20:
            t = inherited('ישר!', f[0], f[5])
        elif f[1] not in ('dnv', 'other') and runs(F, f[1]) and took('ישר!', WHO22.get(f[0], f[0]), f[6]):
            t = took('ישר!', WHO22.get(f[0], f[0]), f[6])
        cards.append(mk('yashar-2026', t, f'{sh[0]:.0f}%', 'מ' + source(top[0][0]), (
            f'כ-{sh[0]:.0f}% מקולות ישר! הגיעו מ{source(top[0][0])} ב-2022' +
            ''.join(f', כ-{s:.0f}% מ{source(f[0])}' for f, s in zip(top[1:], sh[1:])) +
            f'. בסך הכול כ-{thousands(tot)} אלף קולות.'), links=[[f[0], f[2]] for f in top]))
    else:
        cards.append(mk('yashar-2026', t))

    # 2b. Amcha Israel (Winter): where its votes came from, a new list
    c = sources_card(F, 'winter', 'winter-2026', mk)
    if c:
        cards.append(c)

    # 3. Yesh Atid
    t = 'לאן הלכו המצביעים של לפיד?'
    ya = sorted([f for f in F if f[1] == 'yeshatid'], key=lambda f: -f[4])
    if ya:
        main = next((f for f in ya if f[3] == 'beyachad'), ya[0])
        rest = [f for f in ya if f is not main][:2]
        rival = next((f for f in rest if f[3] not in ('dnv', 'other')), None)
        if main[3] == 'beyachad' and main[6] >= 80:
            t = 'מצביעי לפיד נשארו נאמנים'
        elif rival and rival[3] == 'yashar' and 'לפיד' in cards[-1]['title']:
            # the Yashar card already tells this move from Eisenkot's side: tell what Lapid kept instead
            t = kept('ביחד', main[5]) if main[3] == 'beyachad' else 'מצביעי לפיד עזבו אותו'
        elif rival and took(rival[2], 'לפיד', rival[6]):
            t = took(rival[2], 'לפיד', rival[6])
        elif main[3] == 'beyachad' and main[5] < 50:
            t = 'מצביעי לפיד התפזרו'
        elif rival and rival[6] >= ENTER:
            t = f'{who(rival[2])[0]} {"לקחה" if who(rival[2])[1] else "לקח"} מלפיד'
        cards.append(mk('lapid-2026', t, f'{main[5]:.0f}%', 'נשארו עם ביחד' if main[3] == 'beyachad' else 'ל' + dest(main[2]), (
            f'כ-{main[5]:.0f}% ממצביעי יש עתיד ב-2022 הצביעו ל{main[2]}' + (' (יש עתיד רצה בתוכה, בראשות בנט)' if main[3] == 'beyachad' else '') +
            '. האחרים: ' + ', '.join(f'{dest(f[2])} כ-{f[5]:.0f}%' for f in rest) + '.'),
            links=[[f[0], f[2]] for f in [main] + rest]))
    else:
        cards.append(mk('lapid-2026', t))

    if area != 'national':
        return dedupe(cards, F, mk, taken)

    # 4. HaTzibur HaHaredi
    t = 'הציבור החרדי: מחאה מבפנים או השפעה מבחוץ?'
    hs = haredi_share(k26) if k26 else None
    if hs:
        body = (f'כ-{hs["inside"]:.0f}% מקולות הציבור החרדי הגיעו מקלפיות חרדיות, '
                f'וכ-{100 - hs["inside"]:.0f}% מקלפיות אחרות. נספרו כ-{thousands(hs["total"])} אלף קולות לרשימה.')
        hf = sorted([f for f in flows(load('sector-haredi')) if f[2] == 'הציבור החרדי'], key=lambda f: -f[4])
        links, area, area_name = [], 'national', 'כל הארץ'
        # the breakdown is a model fit on the list's votes in Haredi boxes; below 10,000 of them it is noise
        if hf and sum(f[4] for f in hf) >= 10000:
            # where its votes in Haredi boxes came from, as shares of those votes
            tot = sum(f[4] for f in hf)
            top = [f for f in hf[:3] if f[4] / tot >= 0.01]
            parts = [f'כ-{f[4] / tot * 100:.0f}% מ{source(f[0])}' for f in top]
            rest = 100 - sum(round(f[4] / tot * 100) for f in top)
            if rest >= 2:
                parts.append(f'כ-{rest}% ממקורות אחרים')
            body += ' מקולותיה בקלפיות החרדיות: ' + ', '.join(parts) + ' (לפי ההצבעה ב-2022).'
            links, area, area_name = [[f[0], f[2]] for f in hf[:2]], 'sector:haredi', 'חרדים'
        if hs['inside'] >= 75:
            t = 'הציבור החרדי: מרד מבפנים'
        elif hs['inside'] <= 35:
            t = 'הציבור החרדי: הקולות באו מבחוץ'
        else:
            t = 'הציבור החרדי: גם מבפנים, גם מבחוץ'
        c = card('haredi-2026', t, f'{hs["inside"]:.0f}%', 'הגיעו מקלפיות חרדיות', body, area, area_name, links)
        c['stats'] = [f'כ-{hs["of_haredi"]:.1f}% מהקולות בקלפיות החרדיות הלכו לציבור החרדי.',
                      f'כ-{hs["abstain"]:.0f}% מבעלי זכות הבחירה בקלפיות החרדיות לא הצביעו' +
                      (f' (ב-2022, באותן קלפיות: כ-{hs["abstain22"]:.0f}%).' if 'abstain22' in hs else '.')]
        cards.append(c)
    else:
        cards.append(card('haredi-2026', t))

    # 5. Shas -> UTJ inside the Haredi boxes: shown only once both the model and the raw boxes agree on the move
    sh = shas_utj(k26) if k26 else None
    f = next((x for x in flows(load('sector-haredi')) if x[1] == 'shas' and x[3] == 'utj'), None)
    if sh and f and f[6] >= ENTER and sh['shas'][1] < sh['shas'][0] and sh['utj'][1] > sh['utj'][0]:
        t = took('יהדות התורה', 'דרעי', f[6]) or 'יהדות התורה לקחה מדרעי'
        c = card('shas-utj-2026', 'בקלפיות החרדיות, ' + t, f'{f[5]:.0f}%', 'ממצביעי ש"ס עברו ליהדות התורה', (
            f'בקלפיות החרדיות, כ-{f[5]:.0f}% ממצביעי ש"ס ב-2022 עברו ליהדות התורה. '
            f'ש"ס ירדה שם מ-{sh["shas"][0]:.0f}% ל-{sh["shas"][1]:.0f}%, ויהדות התורה עלתה מ-{sh["utj"][0]:.0f}% ל-{sh["utj"][1]:.0f}%.'),
            'sector:haredi', 'חרדים', [['ש"ס', 'יהדות התורה']])
        cards.append(c)

    # 6. the Joint List and Ra'am: whether voters crossed between the two Arab camps
    c = arab_camps(F, mk)
    if c:
        cards.append(c)

    # 6a. between the blocs (no Arab lists): who crossed, and who brought more voters from home
    c = bloc_card(F, mk)
    if c:
        cards.append(c)

    # 6b. what did not happen: an expected move that stayed close to nothing
    non_events(F, mk, cards)

    # 7. the economic clusters: the move whose size differs most between the poorest and the richest clusters
    c = ses_card(load, mk)
    if c:
        cards.append(c)
    cards = dedupe(cards, F, mk, taken)
    # 8. more moves, largest first, until the page has `total` cards with the ones written on the night
    while len(cards) < total:
        c = fresh_card(F, {tuple(l) for l in taken} | {tuple(l) for x in cards for l in x['links']}, mk)
        if not c:
            break
        # a move from the same 2022 list as a card already shown joins that card rather than standing beside it
        twin = next((x for x in cards if x.get('src') and x['src'] == c['src']), None)
        if twin:
            merge_fresh(twin, c, F)
        else:
            cards.append(c)
    return cards


def merge_fresh(a, b, F):
    """One card for two moves out of the same 2022 list: "בן גביר וביבי נגסו בציונות הדתית"."""
    fa, fb = (next(f for f in F if (f[0], f[2]) == tuple(c['links'][0])) for c in (a, b))
    victim = WHO22.get(fa[0], fa[0])
    big = min(fa[6], fb[6]) >= BITE
    a['title'] = f'{who(fa[2])[0]} ו{who(fb[2])[0]} ' + (f'נגסו {with_b(victim)}' if big else f'לקחו מ{victim}')
    stay = next((f for f in F if f[1] == fa[1] and loyal(f)), None)
    a['body'] = (f'כ-{fa[5]:.0f}% מ{source(fa[0])} ב-2022 הצביעו הפעם {with_l(fa[2])}, וכ-{fb[5]:.0f}% {with_l(fb[2])}.' +
                 (f' נשארו עם {fa[0]} כ-{stay[5]:.0f}%.' if stay else ''))
    a['big'], a['unit'] = f'{fa[5] + fb[5]:.0f}%', f'מ{source(fa[0])} עברו {with_l(fa[2])} {with_l(fb[2])[0] == "ל" and "ו" or ""}{with_l(fb[2])}'
    a['links'] = a['links'] + b['links']


def loyal(f):
    # voters who stayed with their list (Yesh Atid runs inside Beyachad in 2026)
    return f[1] == f[3] or (f[1], f[3]) == ('yeshatid', 'beyachad')


def dedupe(cards, F, mk, taken=()):
    """One move, one card: a card whose main move (its largest link that is not voters staying put) is already
    told by an earlier card, or by a card written on the night, gives way to the largest move no card tells yet, or
    is dropped when there is none."""
    told = {tuple(l) for l in taken}
    by = {(f[0], f[2]): f for f in F}
    out = []
    for c in cards:
        moves = [tuple(l) for l in c['links'] if tuple(l) in by and not loyal(by[tuple(l)])]
        # the cluster card and the "did not happen" cards tell a known move from another side, so they never give way
        if moves and moves[0] in told and c['id'] not in ('ses-2026', 'blocs-2026') and not c['id'].endswith('-not-2026'):
            # with no other move to tell (a small area), the card is dropped rather than told twice
            c = fresh_card(F, told | {tuple(l) for x in cards for l in x['links']}, mk)
            if not c:
                continue
        told |= {tuple(l) for l in c['links']}
        out.append(c)
    return out


def fresh_card(F, told, mk):
    """A card for the largest move between two lists that no card tells: not voters staying put, not small lists, and
    not a list running inside another (a move of 80% or more, like Hadash into the Joint List)."""
    for f in sorted(F, key=lambda f: -f[4]):
        # moves from or to non-voters are left out: as a share of all non-voters they read as tiny
        if (f[0], f[2]) in told or loyal(f) or {'other', 'dnv'} & {f[1], f[3]} or f[6] >= 80 or f[6] < ENTER:
            continue
        victim = WHO22.get(f[0], f[0])
        if runs(F, f[1]):
            t = took(f[2], victim, f[6]) or f'{who(f[2])[0]} {"לקחה" if who(f[2])[1] else "לקח"} {"מ" + victim}'
        else:
            t = inherited(f[2], f[0], f[5])
        to = with_l(f[2])
        rest = sorted([x for x in F if x[1] == f[1] and x[3] != f[3]], key=lambda x: -x[4])[:2]
        return mk(f'{f[1]}-{f[3]}-2026', t, f'{f[5]:.0f}%', 'מ' + source(f[0]) + ' עברו ' + to, (
            f'כ-{f[5]:.0f}% מ{source(f[0])} ב-2022 הצביעו הפעם {to}, כ-{thousands(f[4])} אלף קולות.' +
            ('' if runs(F, f[1]) else f' {f[0]} לא רצה הפעם.') +
            (' האחרים: ' + ', '.join(f'{dest(x[2])} כ-{x[5]:.0f}%' for x in rest) + '.' if rest else '')),
            links=[[f[0], f[2]]], src=f[1])
    return None


def sources_card(F, key, id_, mk, min_votes=20000):
    """Where a new 2026 list's votes came from: a headline on its main source when that source gave 40% or more (a
    list's 2022 voters, or people who did not vote), else on the spread; None for a list with few votes yet."""
    inn = sorted([f for f in F if f[3] == key], key=lambda f: -f[4])
    tot = sum(f[4] for f in inn)
    if not inn or tot < min_votes:
        return None
    name = inn[0][2]
    taker, fem = who(name)
    sh = [(f, f[4] / tot * 100) for f in inn[:4]]
    top, s0 = sh[0]
    dnv = next((x for f, x in sh if f[1] == 'dnv'), 0)
    if top[1] == 'dnv' and s0 >= 40:
        t = f'{taker} {"הוציאה" if fem else "הוציא"} אנשים מהבית'
    elif top[1] not in ('dnv', 'other') and s0 >= 40:
        t = f'{taker} {"בנתה" if fem else "בנה"} את עצמ{"ה" if fem else "ו"} על מצביעי {WHO22.get(top[0], WHO.get(top[0], top[0]))}'
        if dnv >= 20:
            t += ' ועל מי שישבו בבית'
    else:
        # no single main source: name the two largest, as a share a person would say
        def part(f, x):
            share = next(w for lim, w in ((60, 'רוב הקולות'), (45, 'כחצי'), (36, f'כ-{round(x / 5) * 5}%'), (30, 'שליש'),
                                          (23, 'רבע'), (17, 'חמישית'), (0, f'כ-{x:.0f}%')) if x >= lim)
            frm = 'ממי שישבו בבית' if f[1] == 'dnv' else 'מרשימות קטנות' if f[1] == 'other' else \
                f'ממצביעי {WHO22.get(f[0], WHO.get(f[0], f[0]))}'
            return f'{share} {frm}'
        t = f'{taker}: ' + ', '.join(part(f, x) for f, x in sh[:2])
    body = (f'כ-{s0:.0f}% מקולות {name} הגיעו מ{source(top[0])} ב-2022' +
            ''.join(f', כ-{x:.0f}% מ{source(f[0])}' for f, x in sh[1:]) + f'. בסך הכול כ-{thousands(tot)} אלף קולות.')
    return mk(id_, t, f'{s0:.0f}%', 'מ' + source(top[0]), body, links=[[f[0], f[2]] for f, _ in sh[:3]])


LEFT26 = ('yashar', 'beyachad', 'labor')            # the centre-left lists of 2026
RIGHT22 = ('likud', 'far_right', 'shas', 'utj', 'religious_right')  # the right-wing and Haredi lists of 2022


def non_events(F, mk, cards):
    """What did not happen, merged into the card on the same list where there is one: Likud voters barely moved to
    the centre-left (into the Likud card), and Bennett's Beyachad drew barely any right-wing voters (one card that
    also tells what Beyachad did draw, so no second card on Beyachad's sources). Only while the move is small."""
    lik = [f for f in F if f[1] == 'likud']
    base = sum(f[4] for f in lik)
    left = sorted([f for f in lik if f[3] in LEFT26], key=lambda f: -f[4])
    if base and left:
        pct = sum(f[4] for f in left) / base * 100
        if pct < 3:
            gone = sorted([f for f in lik if f[3] not in ('likud',) + LEFT26], key=lambda f: -f[4])[:2]
            line = f'שמאלה, לישר!, לביחד ולדמוקרטים, עברו יחד רק כ-{pct:.0f}%.'
            lc = next((c for c in cards if c['id'] == 'likud-2026' and c['pair']), None)
            if lc:
                if gone and gone[0][3] in ('otzma', 'far_right'):
                    lc['title'] = 'הליכוד דימם ימינה, לא שמאלה'
                lc['body'] += ' ' + line
                lc['links'] += [[f[0], f[2]] for f in left[:1]]
            else:
                cards.append(mk('likud-left-not-2026', 'הליכוד לא זלג שמאלה', f'{pct:.0f}%', 'ממצביעי הליכוד עברו למרכז-שמאל', (
                    f'רק כ-{pct:.0f}% ממצביעי הליכוד ב-2022 עברו לישר!, לביחד ולדמוקרטים יחד. '
                    f'מי שעזבו את הליכוד הלכו בעיקר ל{" ול".join(dest(f[2]) for f in gone)}.'),
                    links=[[f[0], f[2]] for f in left]))
    def from_right(key):
        inn = [f for f in F if f[3] == key]
        tot = sum(f[4] for f in inn)
        r = sorted([f for f in inn if f[1] in RIGHT22], key=lambda f: -f[4])
        return (sum(f[4] for f in r) / tot * 100, r, inn, tot) if tot else (None, [], [], 0)
    b, r, inn, tot = from_right('beyachad')
    if b is not None and b < 5:
        top = sorted([f for f in inn if f[1] not in ('dnv', 'other')], key=lambda f: -f[4])[:2]
        y = from_right('yashar')[0]
        # the title names the inheritance too when HaMahane HaMamlachti (not running) is among the main sources
        t = 'בנט ירש מגנץ, לא מהימין' if any(f[1] == 'bluewhite' for f in top) else 'בנט לא הביא מצביעים מהימין'
        cards.append(mk('beyachad-right-not-2026', t, f'{b:.0f}%', 'מקולות ביחד הגיעו מהימין', (
            f'רק כ-{b:.0f}% מקולות ביחד הגיעו ממצביעי הליכוד, הציונות הדתית, ש"ס ויהדות התורה ב-2022. '
            f'רוב הקולות הגיעו מ' + ' ומ'.join(f'{source(f[0])} (כ-{f[4] / tot * 100:.0f}%)' for f in top) + '.' +
            (f' גם לישר! הגיעו מהימין רק כ-{y:.0f}%.' if y is not None and y < 5 else '')),
            # the sources are part of this card, so no other card retells them
            links=[[f[0], f[2]] for f in top] + [[f[0], f[2]] for f in r[:2]]))


# the 2022 blocs: the coalition formed after the vote and the opposition, without the Arab lists
RIGHT22_BLOC = ('likud', 'far_right', 'shas', 'utj', 'religious_right')
ANTI22_BLOC = ('yeshatid', 'bluewhite', 'yb', 'labor', 'meretz')


SPLIT26 = ('reservists',)  # lists between the blocs (Hendel's Reservists): split by where their 2022 voters came from


def bloc_card(F, mk):
    """Moves between the blocs, without the Arab lists: Netanyahu's bloc and the anti-Netanyahu bloc of 2026 (by the
    lists' declared alignment, config/blocs26.json) against the 2022 coalition and opposition (Shaked's Jewish Home
    counted with the coalition); and the turnout game, each bloc's voters brought from home against those it lost to it.
    A list between the blocs (SPLIT26) counts in each bloc by the share of its 2022 bloc voters that came from it."""
    cfg = json.load(open(os.path.join(ROOT, 'config/parties.json')))['elections']['26']['parties']
    bl = json.load(open(os.path.join(ROOT, 'config/blocs26.json')))
    R26 = {cfg[x][1] for x in bl['bibi'] if x in cfg} - set(SPLIT26)
    A26 = {cfg[x][1] for x in bl['anti'] if x in cfg} - set(SPLIT26)  # the Reservists sit in bl['mid']
    split = {}
    for key in SPLIT26:
        r = sum(f[4] for f in F if f[3] == key and f[1] in RIGHT22_BLOC)
        a = sum(f[4] for f in F if f[3] == key and f[1] in ANTI22_BLOC)
        if r + a:
            split[key] = r / (r + a)
    rw = lambda f: 1.0 if f[3] in R26 else split.get(f[3], 0.0)       # share of a 2026 list counted with Netanyahu
    aw = lambda f: 1.0 if f[3] in A26 else 1 - split[f[3]] if f[3] in split else 0.0
    r22, a22 = (lambda f: f[1] in RIGHT22_BLOC), (lambda f: f[1] in ANTI22_BLOC)
    dnv22, dnv26 = (lambda f: f[1] == 'dnv'), (lambda f: f[3] == 'dnv')
    ra = [(f, f[4] * aw(f)) for f in F if r22(f) and aw(f)]
    ar = [(f, f[4] * rw(f)) for f in F if a22(f) and rw(f)]
    if not ra and not ar:
        return None
    tot = lambda fs: sum(v for _, v in fs)
    r_in = sum(f[4] * rw(f) for f in F if dnv22(f))
    a_in = sum(f[4] * aw(f) for f in F if dnv22(f))
    r_out = sum(f[4] for f in F if r22(f) and dnv26(f))
    a_out = sum(f[4] for f in F if a22(f) and dnv26(f))
    gap = (a_in - a_out) - (r_in - r_out)
    cross = tot(ra) - tot(ar)
    k = lambda n: f'{thousands(n)} אלף'
    base = min(sum(f[4] for f in F if r22(f)), sum(f[4] for f in F if a22(f))) or 1
    who_won = 'אנטי-ביבי' if gap > 0 else 'גוש נתניהו'
    if abs(gap) >= abs(cross):
        # the net move between the blocs as a share of the smaller bloc: under 3% reads as "hardly any"
        t = (f'בין הגושים כמעט לא עברו קולות. {who_won} פשוט הביא יותר אנשים לקלפי' if abs(cross) / base < 0.03
             else f'{who_won} ניצח גם בהבאת מצביעים מהבית, גם במעברים')
        big, unit = f'{thousands(abs(gap))}', 'אלף קולות יתרון ' + ('לאנטי-ביבי' if gap > 0 else 'לגוש נתניהו') + ' מהבית'
    else:
        t = ('מצביעי ימין עברו לגוש אנטי-ביבי' if cross > 0 else 'מצביעי מרכז-שמאל עברו לגוש נתניהו')
        big, unit = f'{thousands(abs(cross))}', 'אלף קולות נטו בין הגושים'
    net_a, net_r = a_in - a_out, r_in - r_out
    body = (f'בין הגושים (בלי הרשימות הערביות) עברו נטו כ-{k(abs(cross))} מצביעים ' +
            ('מגוש נתניהו לגוש אנטי-ביבי. ' if cross > 0 else 'מגוש אנטי-ביבי לגוש נתניהו. ') +
            f'ממי שלא הצביעו ב-2022 גוש אנטי-ביבי הרוויח נטו כ-{k(net_a)} מצביעים, וגוש נתניהו כ-{k(net_r)}.' +
            (f' המילואימניקים נספרו בשני הגושים לפי מקור מצביעיהם: כ-{split["reservists"] * 100:.0f}% בגוש נתניהו.'
             if 'reservists' in split else ''))
    links = [[f[0], f[2]] for f, _ in sorted(ra, key=lambda x: -x[1])[:2] + sorted(ar, key=lambda x: -x[1])[:1]]
    return mk('blocs-2026', t, big, unit, body, links=links)


def arab_camps(F, mk):
    """Moves between the Joint List camp (Hadash-Ta'al and Balad in 2022) and Ra'am, both ways: a headline on the
    larger one when it is real, else that the camps held (itself a finding: the growth came from elsewhere)."""
    joint22 = [f for f in F if f[1] in ('hadash', 'balad')]
    raam22 = [f for f in F if f[1] == 'raam']
    if not joint22 or not raam22:
        return None
    base = lambda fs: sum(f[4] for f in fs)
    to_raam = [f for f in joint22 if f[3] == 'raam']
    to_joint = [f for f in raam22 if f[3] == 'joint']
    a = sum(f[4] for f in to_raam) / base(joint22) * 100
    b = sum(f[4] for f in to_joint) / base(raam22) * 100
    links = [[f[0], f[2]] for f in to_raam + to_joint]
    stay_j = sum(f[4] for f in joint22 if f[3] == 'joint') / base(joint22) * 100
    stay_r = sum(f[4] for f in raam22 if f[3] == 'raam') / base(raam22) * 100
    low = max([f[6] for f in to_raam + to_joint] or [0])
    if low >= ENTER:
        t = 'עבאס נגס במשותפת' if a >= b else 'המשותפת נגסה בעבאס'
        big = max(a, b)
        unit = 'ממצביעי חד"ש ובל"ד עברו לרע"מ' if a >= b else 'ממצביעי רע"מ עברו למשותפת'
    else:
        t = 'המשותפת ורע"מ: כל אחת שמרה על שלה'
        big, unit = min(stay_j, stay_r), 'נשארו במחנה שלהם'
        links = links or [[f[0], f[2]] for f in raam22 if f[3] == 'raam'][:1]
    body = (f'כ-{stay_j:.0f}% ממצביעי חד"ש-תע"ל ובל"ד ב-2022 הצביעו למשותפת, וכ-{stay_r:.0f}% ממצביעי רע"מ חזרו לרע"מ. '
            f'בין שני המחנות עברו {"כ-" + f"{a:.0f}" + "% לרע״מ וכ-" + f"{b:.0f}" + "% למשותפת" if low >= ENTER else "מעט מאוד קולות"}.')
    return mk('arab-camps-2026', t, f'{big:.0f}%', unit, body, links=links)


SES_LOW, SES_HIGH = 'g1', 'g4'  # clusters 1-3 and 8-10 (ses_index.json)


def ses_card(load, mk, flt='general', min_votes=3000):
    """The move whose share differs most between the poorest clusters (1-3) and the richest (8-10), among Jewish
    non-Haredi voters (so that the Arab and Haredi towns, all in the low clusters, do not make the difference). Only a
    move whose two intervals are clearly apart, and that is not small where it is larger; None otherwise."""
    def links(g):
        d = load(f'ses-{flt}-{g}')
        p = (d or {}).get('pairs', {}).get(PAIR)
        if not p:
            return {}
        return {(p['from'][l[0]][0], p['from'][l[0]][1], p['to'][l[1]][0], p['to'][l[1]][1]): l[2:6] for l in p['links']
                if len(l) >= 6 and l[4] is not None and l[5] is not None}
    lo, hi = links(SES_LOW), links(SES_HIGH)
    best = None
    for k in set(lo) | set(hi):
        if k[1] == k[3] or {'other', 'dnv'} & {k[1], k[3]} or (k[1], k[3]) == ('yeshatid', 'beyachad'):
            continue
        a, b = lo.get(k, [0, 0, 0, 0]), hi.get(k, [0, 0, 0, 0])
        if max(a[0], b[0]) < min_votes:
            continue
        gap = max(a[2] - b[3], b[2] - a[3])  # the space between the two intervals; above 0 means they do not overlap
        ratio = max(a[1], b[1]) / max(min(a[1], b[1]), 1)
        if gap > 0.5 and max(a[2], b[2]) >= ENTER and ratio >= 2 and (not best or ratio > best[0]):
            best = (ratio, k, a, b)
    if not best:
        return None
    _, (fn, fk, tn, tk), a, b = best
    taker, fem = who(tn)
    where = 'באשכולות החלשים' if a[1] > b[1] else 'באשכולות החזקים'
    victim = WHO22.get(fn, fn)
    verb = ("חדרה" if fem else "חדר") + ' ל' + (fn[1:] if fn.startswith('ה') else fn) if fk == 'likud' else ("לקחה" if fem else "לקח") + ' מ' + victim
    t = f'{taker} {verb} {where}'
    body = (f'בקרב יהודים לא-חרדים: באשכולות 1 עד 3 כ-{a[1]:.0f}% מ{source(fn)} ב-2022 הצביעו הפעם {with_l(tn)}, '
            f'ובאשכולות 8 עד 10 {"רק " if a[1] > b[1] else ""}כ-{b[1]:.0f}%.')
    unit = f'מ{source(fn)} באשכולות ' + ('1 עד 3' if a[1] > b[1] else '8 עד 10')
    # the card opens the national chart on this move: the area menu has no cluster groups
    return mk('ses-2026', t, f'{max(a[1], b[1]):.0f}%', unit, body, links=[[fn, tn]])


def shas_utj(k26, cut=0.6, min_boxes=50):
    """Shas and UTJ shares of the valid vote in 2022 and 2026, in the counted boxes that were Haredi in 2022 (Shas
    plus UTJ at least 60%) and can be matched by locality and ballot number; None with too few such boxes."""
    k26 = pd.read_csv(k26, encoding='utf-8-sig')
    k25 = pd.read_csv(os.path.join(ROOT, 'data/raw/k25.csv'), encoding='utf-8-sig')
    key = lambda f: f['סמל ישוב'].astype(str).str.strip() + '|' + pd.to_numeric(f['קלפי'], errors='coerce').round(1).astype(str)
    k26.index, k25.index = key(k26), key(k25)
    k26 = k26[pd.to_numeric(k26['כשרים'], errors='coerce') > 0]
    m = k25.index.intersection(k26.index)
    a, b = k25.loc[m], k26.loc[m]
    box = (a['שס'] + a['ג']) / a['כשרים'] >= cut
    if box.sum() < min_boxes:
        return None
    a, b = a[box], b[box]
    pct = lambda f, c: f[c].sum() / f['כשרים'].sum() * 100
    return dict(n=int(box.sum()), shas=(pct(a, 'שס'), pct(b, 'שס')), utj=(pct(a, 'ג'), pct(b, 'ג')))


if __name__ == '__main__':
    import sys
    for c in make(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None):
        print(f"{c['big']:>5} {c['title']}\n      {c['body']}")
