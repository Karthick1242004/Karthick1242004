#!/usr/bin/env python3
"""Write data/profile.json: the contribution calendar, profile counts and public repos.

    GITHUB_TOKEN=... python scripts/fetch_profile_data.py

Locally, GITHUB_TOKEN="$(gh auth token)" works. The calendar is the same one the
profile page shows: the last year, with private contributions included only as
counts and only if "Include private contributions" is on in the profile settings.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "profile.json"
LOGIN = os.environ.get("PROFILE_LOGIN") or os.environ.get("GITHUB_REPOSITORY_OWNER") or "Karthick1242004"

QUERY = """
query($login: String!) {
  user(login: $login) {
    login name bio
    followers { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, privacy: PUBLIC,
                 orderBy: {field: PUSHED_AT, direction: DESC}) {
      totalCount
      nodes {
        name description url homepageUrl stargazerCount forkCount pushedAt isFork
        primaryLanguage { name color }
      }
    }
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def main():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("fetch_profile_data: set GITHUB_TOKEN (in Actions) or GH_TOKEN=$(gh auth token) locally")

    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": LOGIN}}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "profile-readme-cards"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            payload = json.load(res)
    except urllib.error.HTTPError as err:
        sys.exit(f"fetch_profile_data: GitHub answered HTTP {err.code}: {err.read()[:300]!r}")
    if payload.get("errors") or not (payload.get("data") or {}).get("user"):
        sys.exit(f"fetch_profile_data: GraphQL error: {json.dumps(payload.get('errors'))[:500]}")

    user = payload["data"]["user"]
    cal = user["contributionsCollection"]["contributionCalendar"]
    days = [{"date": d["date"], "count": d["contributionCount"]}
            for w in cal["weeks"] for d in w["contributionDays"]]
    repos = {
        r["name"]: {
            "description": r["description"],
            "url": r["url"],
            "homepage": r["homepageUrl"] or None,
            "stars": r["stargazerCount"],
            "forks": r["forkCount"],
            "pushed_at": r["pushedAt"],
            "fork": r["isFork"],
            "language": (r["primaryLanguage"] or {}).get("name"),
            "language_color": (r["primaryLanguage"] or {}).get("color"),
        }
        for r in user["repositories"]["nodes"]
    }
    data = {
        "login": user["login"],
        "name": user["name"],
        "bio": user["bio"],
        "followers": user["followers"]["totalCount"],
        "public_repos": user["repositories"]["totalCount"],
        "total_contributions": cal["totalContributions"],
        "days": days,
        "repos": repos,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    print(f"fetch_profile_data: {len(days)} days ({cal['totalContributions']} contributions), "
          f"{len(repos)} repos -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
