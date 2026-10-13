"""Documentary Intelligence — TMDB discovery v3.1.

Scoperta storica senza vincoli tematici, selezione investigativa + esplorativa.
Non modifica il catalogo Android e non esegue modelli AI.
"""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timezone

from classify import classify_documentary

TOKEN = os.environ.get("TMDB_READ_ACCESS_TOKEN", "").strip()
API_BASE = "https://api.themoviedb.org/3"
OUTPUT_FILE = "discovery/tmdb_discovery_results.json"
MIN_RUNTIME = 70
MAX_DETAILS = 500
MAX_RESULTS = 150
EXPLORATION_QUOTA = 38
PAGES_PER_SORT = 8
REQUEST_DELAY = 0.08

SORT_MODES = ("popularity.desc", "vote_count.desc")
YEAR_RANGES = (
    (1970, 1989), (1990, 1999), (2000, 2009),
    (2010, 2014), (2015, 2019), (2020, 2023), (2024, None),
)

INVESTIGATIVE_SIGNALS = {
    "investigative": 6, "investigation": 6, "investigates": 6,
    "investigating": 6, "uncovers": 5, "uncovering": 5,
    "exposes": 5, "exposing": 5, "exposé": 5,
    "whistleblower": 5, "whistleblowers": 5,
    "cover-up": 5, "cover up": 5, "hidden truth": 5,
    "hidden history": 3, "corruption": 4, "scandal": 4,
    "fraud": 4, "conspiracy": 3, "accountability": 4,
    "evidence": 4, "classified documents": 5,
    "secret documents": 5, "leaked documents": 5,
    "leaked": 3, "revelations": 4, "reveals": 3,
    "revealing": 3, "inquiry": 4, "journalist": 3,
    "journalism": 3, "undercover": 5, "unsolved": 3,
    "wrongful conviction": 5, "misconduct": 4,
    "abuse of power": 5, "systemic failure": 4,
    "deception": 3, "secrecy": 3,
    "traces the origins": 2, "behind the scandal": 4,
}
NEGATIVE_SIGNALS = {
    "concert film": 12, "live concert": 12,
    "concert performance": 10, "stand-up comedy": 12,
    "stand up comedy": 12, "comedy special": 12,
    "behind the scenes": 5, "making-of": 6,
    "making of the movie": 7, "cast reunion": 8,
    "reunion special": 8, "music video": 6,
    "tour documentary": 5, "sports highlights": 6,
    "pranks": 8, "stunts": 8, "reality show": 8,
    "visual poem": 5, "tone poem": 5,
}
GENRE_PENALTIES = {"Music": 4, "Comedy": 3}


def tmdb_get(endpoint, params=None):
    if not TOKEN:
        raise RuntimeError("Secret TMDB_READ_ACCESS_TOKEN mancante")
    query = urllib.parse.urlencode(params or {})
    url = API_BASE + endpoint + ("?" + query if query else "")
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/json",
        "User-Agent": "DocumentaryIntelligence/3.1",
    })
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                data = json.load(response)
            time.sleep(REQUEST_DELAY)
            return data
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 3:
                raise
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError("Richiesta TMDB non riuscita")


def has_phrase(text, phrase):
    return bool(re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text, re.I))


def score_text(title, overview, keywords=(), genres=()):
    text = ". ".join((title or "", overview or "", " ".join(keywords)))
    positive = [term for term in INVESTIGATIVE_SIGNALS if has_phrase(text, term)]
    negative = [term for term in NEGATIVE_SIGNALS if has_phrase(text, term)]
    genre_penalty = sum(GENRE_PENALTIES.get(g, 0) for g in genres)
    score = (sum(INVESTIGATIVE_SIGNALS[t] for t in positive)
             - sum(NEGATIVE_SIGNALS[t] for t in negative)
             - genre_penalty)
    return {"score": score, "positive": positive,
            "negative": negative, "genre_penalty": genre_penalty}


def discover_period(start_year, end_year, today):
    start = f"{start_year}-01-01"
    end = min(date(end_year, 12, 31), today).isoformat() if end_year else today.isoformat()
    found = {}
    for sort_mode in SORT_MODES:
        for page in range(1, PAGES_PER_SORT + 1):
            data = tmdb_get("/discover/movie", {
                "with_genres": "99",
                "primary_release_date.gte": start,
                "primary_release_date.lte": end,
                "sort_by": sort_mode,
                "page": page,
                "include_adult": "false",
                "include_video": "false",
                "language": "en-US",
            })
            for movie in data.get("results", []):
                if movie.get("id"):
                    found[movie["id"]] = movie
            if page >= data.get("total_pages", 0):
                break
    return list(found.values())


def round_robin(groups):
    """Alterna periodi storici, senza duplicare gli ID."""
    result, seen = [], set()
    index = 0
    while True:
        added = False
        for group in groups:
            if index < len(group):
                added = True
                movie = group[index]
                if movie["id"] not in seen:
                    result.append(movie)
                    seen.add(movie["id"])
        if not added:
            break
        index += 1
    return result


def candidate_streams(period_groups):
    scored, exploratory = [], []
    for group in period_groups:
        enriched = []
        for movie in group:
            item = dict(movie)
            item["_preliminary"] = score_text(item.get("title"), item.get("overview"))
            enriched.append(item)
        scored.append(sorted(enriched, key=lambda m: (
            m["_preliminary"]["score"], m.get("vote_count", 0)), reverse=True))
        exploratory.append(sorted(enriched, key=lambda m: (
            m.get("vote_count", 0), m.get("popularity", 0)), reverse=True))
    return round_robin(scored), round_robin(exploratory)


def fetch_documentary(movie_id, today):
    details = tmdb_get(f"/movie/{movie_id}", {"language": "en-US"})
    genres = [g.get("name", "") for g in details.get("genres", [])]
    if 99 not in [g.get("id") for g in details.get("genres", [])]:
        return None
    runtime = details.get("runtime")
    if not isinstance(runtime, int) or runtime < MIN_RUNTIME:
        return None
    try:
        release = date.fromisoformat(details.get("release_date") or "")
    except ValueError:
        return None
    if release > today:
        return None
    overview = (details.get("overview") or "").strip()
    if not overview:
        return None
    keyword_data = tmdb_get(f"/movie/{movie_id}/keywords")
    keywords = [k["name"] for k in keyword_data.get("keywords", []) if k.get("name")]
    poster_path = details.get("poster_path")
    movie = {
        "tmdb_id": movie_id,
        "title": details.get("title") or details.get("original_title") or "",
        "release_date": release.isoformat(),
        "runtime": runtime,
        "overview": overview,
        "genres": genres,
        "keywords": keywords,
        "posterUrl": "https://image.tmdb.org/t/p/w500" + poster_path if poster_path else None,
        "popularity": details.get("popularity", 0),
        "vote_average": details.get("vote_average", 0),
        "vote_count": details.get("vote_count", 0),
        "tmdb_url": f"https://www.themoviedb.org/movie/{movie_id}",
    }
    movie["preliminary"] = score_text(movie["title"], overview, keywords, genres)
    movie["classification"] = classify_documentary(movie)
    return movie


def quality_key(movie):
    return (movie["preliminary"]["score"],
            movie["classification"].get("investigative_score", 0),
            movie.get("vote_count", 0))


def select_final(valid, investigative_order, exploration_order):
    """Quote effettive sul risultato finale, non solo sui candidati iniziali."""
    by_id = {m["tmdb_id"]: m for m in valid}
    chosen, chosen_ids = [], set()
    group_counts = Counter()

    def take(stream, limit, group):
        for item in stream:
            if group_counts[group] >= limit:
                break
            movie_id = item["id"]
            if movie_id in by_id and movie_id not in chosen_ids:
                chosen.append(by_id[movie_id])
                chosen_ids.add(movie_id)
                group_counts[group] += 1

    # Riserviamo prima la quota esplorativa, cosi' i candidati
    # investigativi non possono assorbirla.
    take(exploration_order, EXPLORATION_QUOTA, "exploratory")
    take(investigative_order, MAX_RESULTS - EXPLORATION_QUOTA, "investigative")

    # Eventuali posti vuoti vengono riempiti con gli altri validi.
    if len(chosen) < MAX_RESULTS:
        for movie in sorted(valid, key=quality_key, reverse=True):
            if len(chosen) >= MAX_RESULTS:
                break
            if movie["tmdb_id"] not in chosen_ids:
                chosen.append(movie)
                chosen_ids.add(movie["tmdb_id"])
                group_counts["fallback"] += 1

    return chosen, dict(group_counts)


def main():
    today = datetime.now(timezone.utc).date()
    groups, unique_ids, errors = [], set(), []
    print("Documentary Intelligence - Discovery v3.1", flush=True)

    for start_year, end_year in YEAR_RANGES:
        label = f"{start_year}-{end_year or 'oggi'}"
        try:
            candidates = discover_period(start_year, end_year, today)
        except Exception as error:
            errors.append({"stage": "discovery", "period": label, "error": str(error)})
            groups.append([])
            print(f"Errore periodo {label}: {error}", flush=True)
            continue
        group = []
        for movie in candidates:
            if movie["id"] not in unique_ids:
                unique_ids.add(movie["id"])
                group.append(movie)
        groups.append(group)
        print(f"Periodo {label}: {len(group)} candidati", flush=True)

    investigative_order, exploration_order = candidate_streams(groups)
    # Due quote distinte anche nella fase di recupero dettagli.
    # L'esplorazione usa un ordinamento indipendente dai segnali.
    exploration_budget = MAX_DETAILS // 4
    investigation_budget = MAX_DETAILS - exploration_budget
    selected, selected_ids = [], set()
    selection_counts = Counter()

    for label, stream, budget in (
        ("exploratory", exploration_order, exploration_budget),
        ("investigative", investigative_order, investigation_budget),
    ):
        for item in stream:
            if selection_counts[label] >= budget:
                break
            if item["id"] not in selected_ids:
                selected.append(item)
                selected_ids.add(item["id"])
                selection_counts[label] += 1

    # Riempie il budget se le due liste hanno sovrapposizioni.
    for item in investigative_order:
        if len(selected) >= MAX_DETAILS:
            break
        if item["id"] not in selected_ids:
            selected.append(item)
            selected_ids.add(item["id"])
            selection_counts["fallback"] += 1

    valid = []
    for index, candidate in enumerate(selected, 1):
        movie_id = candidate["id"]
        print(f"[{index}/{len(selected)}] {candidate.get('title', movie_id)}", flush=True)
        try:
            movie = fetch_documentary(movie_id, today)
            if movie:
                valid.append(movie)
        except Exception as error:
            errors.append({"stage": "details", "tmdb_id": movie_id, "error": str(error)})
            print(f"Errore {movie_id}: {error}", flush=True)

    results, final_groups = select_final(valid, investigative_order, exploration_order)
    statuses, genres, decades = Counter(), Counter(), Counter()
    for movie in results:
        classification = movie["classification"]
        statuses[classification.get("classification_status", "unknown")] += 1
        genres.update(classification.get("genres", []))
        year = int(movie["release_date"][:4])
        decades[f"{year // 10 * 10}s"] += 1

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "TMDB historical investigative discovery v3.1",
        "min_runtime": MIN_RUNTIME,
        "release_date_cutoff": today.isoformat(),
        "candidates_collected": len(unique_ids),
        "candidates_checked": len(selected),
        "valid_documentaries": len(valid),
        "results_count": len(results),
        "selection_counts": dict(selection_counts),
        "final_selection_counts": final_groups,
        "classification_summary": {
            "status_counts": dict(statuses),
            "genre_counts": dict(genres),
            "decade_counts": dict(decades),
        },
        "errors": errors,
        "results": results,
    }
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)
    print(f"Salvati {len(results)} documentari; errori: {len(errors)}", flush=True)
    print(f"Quote finali: {final_groups}", flush=True)


if __name__ == "__main__":
    main()
