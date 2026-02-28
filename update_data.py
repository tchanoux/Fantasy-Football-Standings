from yahoo_oauth import OAuth2

oauth = OAuth2(None, None, from_file="oauth2.json")

if not oauth.token_is_valid():
    oauth.refresh_access_token()


#------Pull in the league information-----

import xml.etree.ElementTree as ET
from collections import defaultdict

LEAGUE_KEY = "461.l.113410"  # replace with your league key
TOTAL_WEEKS = 17

# ---- Step 1: Get teams ----
teams = []
team_map = {}  # team_key -> team name
teams_url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{LEAGUE_KEY}/teams"
teams_xml = ET.fromstring(oauth.session.get(teams_url).text)

for team in teams_xml.findall(".//{http://fantasysports.yahooapis.com/fantasy/v2/base.rng}team"):
    t_key = team.find("{http://fantasysports.yahooapis.com/fantasy/v2/base.rng}team_key").text
    t_name = team.find("{http://fantasysports.yahooapis.com/fantasy/v2/base.rng}name").text
    teams.append(t_key)
    team_map[t_key] = t_name

# ---- Step 2: Pull weekly points ----
scores = defaultdict(dict)  # scores[week][team_key] = points
last_completed_week = 0

for week in range(1, TOTAL_WEEKS + 1):
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{LEAGUE_KEY}/scoreboard;week={week}"
    resp = oauth.session.get(url).text
    try:
        root = ET.fromstring(resp)
    except ET.ParseError:
        continue  # skip if week not available

    week_has_data = False
    for team in root.findall(".//{http://fantasysports.yahooapis.com/fantasy/v2/base.rng}team"):
        t_key = team.find("{http://fantasysports.yahooapis.com/fantasy/v2/base.rng}team_key").text
        points_node = team.find(".//{http://fantasysports.yahooapis.com/fantasy/v2/base.rng}team_points/{http://fantasysports.yahooapis.com/fantasy/v2/base.rng}total")
        if points_node is not None and points_node.text:
            scores[week][t_key] = float(points_node.text)
            week_has_data = True
    if week_has_data:
        last_completed_week = week

print(f"✅ Data available through Week {last_completed_week}")

# ---- Step 3: Compute regular season standings ----
wins = defaultdict(int)
losses = defaultdict(int)
points_for = defaultdict(float)

# Weeks 1-11: H2H
for week in range(1, min(12, last_completed_week + 1)):
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{LEAGUE_KEY}/scoreboard;week={week}"
    resp = oauth.session.get(url).text
    try:
        root = ET.fromstring(resp)
    except ET.ParseError:
        continue

    for matchup in root.findall(".//{http://fantasysports.yahooapis.com/fantasy/v2/base.rng}matchup"):
        teams_in_matchup = matchup.findall(".//{http://fantasysports.yahooapis.com/fantasy/v2/base.rng}team")
        if len(teams_in_matchup) != 2:
            continue
        t1 = teams_in_matchup[0].find("{http://fantasysports.yahooapis.com/fantasy/v2/base.rng}team_key").text
        t2 = teams_in_matchup[1].find("{http://fantasysports.yahooapis.com/fantasy/v2/base.rng}team_key").text
        s1 = scores[week].get(t1, 0)
        s2 = scores[week].get(t2, 0)
        points_for[t1] += s1
        points_for[t2] += s2
        if s1 > s2:
            wins[t1] += 1
            losses[t2] += 1
        elif s2 > s1:
            wins[t2] += 1
            losses[t1] += 1

# Weeks 12-14: points-based
for week in range(12, min(15, last_completed_week + 1)):
    ranked = sorted(scores[week].items(), key=lambda x: x[1], reverse=True)
    top6 = {t for t,_ in ranked[:6]}
    for t, pts in ranked:
        points_for[t] += pts
        if t in top6:
            wins[t] += 1
        else:
            losses[t] += 1

# ---- Step 4: Regular season standings ----
import pandas as pd

data = []

for t in teams:
    w = wins[t]
    l = losses[t]
    pf = points_for[t]

    games = w + l
    win_pct = round(w / games, 3) if games > 0 else 0

    data.append({
        "Team": team_map[t],
        "Wins": w,
        "Losses": l,
        "Win %": win_pct,
        "Points For": round(pf, 1),
    })

df = pd.DataFrame(data)

# -------------------------------------------------
# STEP 1: Sort by Wins, then Points For
# -------------------------------------------------
df = df.sort_values(
    by=["Wins", "Points For"],
    ascending=False
).reset_index(drop=True)

# Add Rank
df.insert(0, "Rank", range(1, len(df) + 1))

# -------------------------------------------------
# STEP 2: Identify Top 4 Automatic Qualifiers
# -------------------------------------------------
df["Playoff Status"] = ""

df.loc[df["Rank"] <= 4, "Playoff Status"] = "Clinched (Top 4)"

# -------------------------------------------------
# STEP 3: Identify Wild Cards
# -------------------------------------------------

# Get remaining teams (not top 4)
remaining = df[df["Rank"] > 4].copy()

# Sort remaining by Points For only
remaining = remaining.sort_values(
    by="Points For",
    ascending=False
)

# Take top 2
wildcards = remaining.head(2)["Team"].tolist()

df.loc[df["Team"].isin(wildcards), "Playoff Status"] = "Wild Card"

print(df)

df.to_json("data.json", orient="records", indent=2)
