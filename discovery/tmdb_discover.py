
"""
Documentary Intelligence - TMDB Discovery v3

Ricerca documentari cinematografici investigativi
di qualsiasi argomento e periodo storico.

Fasi:
1. Raccolta ampia da TMDB
2. Preselezione basata sul metodo investigativo
3. Recupero dei dettagli e delle keywords
4. Classificazione con le regole esistenti
5. Salvataggio di candidati e risultati diagnostici

Non modifica documentaries.json.
Non esegue modelli AI.
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


TOKEN = os.environ.get(
    "TMDB_READ_ACCESS_TOKEN", ""
).strip()

API_BASE = "https://api.themoviedb.org/3"
OUTPUT_FILE = "discovery/tmdb_discovery_results.json"

MIN_RUNTIME = 70
MAX_DETAILS = 500
MAX_RESULTS = 150
PAGES_PER_SORT = 8
REQUEST_DELAY = 0.08

# La quota esplorativa permette di conservare
# documentari che non contengono parole investigative.
EXPLORATION_FRACTION = 0.25

SORT_MODES = [
    "popularity.desc",
    "vote_count.desc",
]

YEAR_RANGES = [
    (1970, 1989),
    (1990, 1999),
    (2000, 2009),
    (2010, 2014),
    (2015, 2019),
    (2020, 2023),
    (2024, None),
]

# Segnali del metodo investigativo.
# Non sono argomenti: riguardano il modo
# in cui il documentario affronta la storia.
INVESTIGATIVE_SIGNALS = {
    "investigative": 6,
    "investigation": 6,
    "investigates": 6,
    "investigating": 6,
    "uncovers": 5,
    "uncovering": 5,
    "exposes": 5,
    "exposing": 5,
    "exposé": 5,
    "whistleblower": 5,
    "whistleblowers": 5,
    "cover-up": 5,
    "cover up": 5,
    "hidden truth": 5,
    "hidden history": 3,
    "corruption": 4,
    "scandal": 4,
    "fraud": 4,
    "conspiracy": 3,
    "accountability": 4,
    "evidence": 4,
    "classified documents": 5,
    "secret documents": 5,
    "leaked documents": 5,
    "leaked": 3,
    "revelations": 4,
    "reveals": 3,
    "revealing": 3,
    "inquiry": 4,
    "journalist": 3,
    "journalism": 3,
    "undercover": 5,
    "unsolved": 3,
    "wrongful conviction": 5,
    "misconduct": 4,
    "abuse of power": 5,
    "systemic failure": 4,
    "deception": 3,
    "secrecy": 3,
    "traces the origins": 2,
    "behind the scandal": 4,
}

# Penalizzazioni per formati spesso estranei
# all'obiettivo del catalogo.
NEGATIVE_SIGNALS = {
    "concert film": 12,
    "live concert": 12,
    "concert performance": 10,
    "stand-up comedy": 12,
    "stand up comedy": 12,
    "comedy special": 12,
    "behind the scenes": 5,
    "making-of": 6,
    "making of the movie": 7,
    "cast reunion": 8,
    "reunion special": 8,
    "music video": 6,
    "tour documentary": 5,
    "sports highlights": 6,
    "pranks": 8,
    "stunts": 8,
    "reality show": 8,
    "visual poem": 5,
    "tone poem": 5,
}

# Generi TMDB che costituiscono indizi di
# formato non investigativo, non esclusioni.
GENRE_PENALTIES = {
    "Music": 4,
    "Comedy": 3,
}


def tmdb_get(endpoint, params=None):
    if not TOKEN:
        raise RuntimeError(
            "Secret TMDB_READ_ACCESS_TOKEN mancante."
        )

    query = urllib.parse.urlencode(params or {})
    url = API_BASE + endpoint

    if query:
        url += "?" + query

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/json",
            "User-Agent": "DocumentaryIntelligence/3.0",
        },
    )

    for attempt in range(4):
        try:
            with urllib.request.urlopen(
                request,
                timeout=35,
            ) as response:
                result = json.load(response)

            time.sleep(REQUEST_DELAY)
            return result

        except urllib.error.HTTPError as error:
            if (
                error.code in (429, 500, 502, 503, 504)
                and attempt < 3
            ):
                time.sleep(2 ** (attempt + 1))
                continue
            raise

        except (urllib.error.URLError, TimeoutError):
            if attempt < 3:
                time.sleep(2 ** (attempt + 1))
                continue
            raise


def phrase_present(text, phrase):
    """
    Ricerca con confini di parola per evitare
    corrispondenze all'interno di altre parole.
    """
    pattern = (
        r"(?<!\w)"
        + re.escape(phrase.lower())
        + r"(?!\w)"
    )

    return bool(re.search(pattern, text.lower()))


def preliminary_score(movie):
    title = movie.get("title") or ""
    overview = movie.get("overview") or ""

    text = title + ". " + overview

    positive = []
    negative = []

    score = 0

    for phrase, weight in INVESTIGATIVE_SIGNALS.items():
        if phrase_present(text, phrase):
            score += weight
            positive.append(phrase)

    for phrase, weight in NEGATIVE_SIGNALS.items():
        if phrase_present(text, phrase):
            score -= weight
            negative.append(phrase)

    return {
        "score": score,
        "positive": positive,
        "negative": negative,
    }


def discover_period(start_year, end_year, today):
    start_date = f"{start_year}-01-01"

    end_date = (
        today.isoformat()
        if end_year is None
        else min(
            date(end_year, 12, 31),
            today,
        ).isoformat()
    )

    found = {}

    for sort_mode in SORT_MODES:
        for page in range(1, PAGES_PER_SORT + 1):
            params = {
                "with_genres": "99",
                "primary_release_date.gte": start_date,
                "primary_release_date.lte": end_date,
                "sort_by": sort_mode,
                "page": page,
                "include_adult": "false",
                "include_video": "false",
                "language": "en-US",
            }

            data = tmdb_get(
                "/discover/movie",
                params,
            )

            for movie in data.get("results", []):
                movie_id = movie.get("id")

                if movie_id:
                    found[movie_id] = movie

            if page >= data.get("total_pages", 0):
                break

    return list(found.values())


def round_robin(groups, limit):
    result = []
    index = 0

    while len(result) < limit:
        added = False

        for group in groups:
            if index < len(group):
                result.append(group[index])
                added = True

                if len(result) >= limit:
                    break

        if not added:
            break

        index += 1

    return result


def select_candidates(period_groups):
    """
    Due percorsi indipendenti:
    - 75% candidati con segnali investigativi
    - 25% esplorazione senza dipendere dai segnali

    Entrambi distribuiti tra i periodi storici.
    """

    scored_groups = []
    exploration_groups = []

    for group in period_groups:
        enriched = []

        for movie in group:
            item = dict(movie)
            item["_preliminary"] = preliminary_score(movie)
            enriched.append(item)

        ranked = sorted(
            enriched,
            key=lambda item: (
                item["_preliminary"]["score"],
                item.get("vote_count", 0),
            ),
            reverse=True,
        )

        scored_groups.append(ranked)

        # I candidati esplorativi sono ordinati
        # per voto/popolarita', senza richiedere
        # parole investigative.
        exploratory = sorted(
            enriched,
            key=lambda item: (
                item.get("vote_count", 0),
                item.get("popularity", 0),
            ),
            reverse=True,
        )

        exploration_groups.append(exploratory)

    exploration_limit = int(
        MAX_DETAILS * EXPLORATION_FRACTION
    )

    investigative_limit = (
        MAX_DETAILS - exploration_limit
    )

    selected = []
    selected_ids = set()

    def add_unique(items):
        for item in items:
            movie_id = item.get("id")

            if movie_id not in selected_ids:
                selected.append(item)
                selected_ids.add(movie_id)

    # Sovracampioniamo per compensare
    # i duplicati tra le due selezioni.
    add_unique(
        round_robin(
            scored_groups,
            investigative_limit,
        )
    )

    add_unique(
        round_robin(
            exploration_groups,
            MAX_DETAILS,
        )
    )

    # Riempimento eventuale, senza duplicati.
    if len(selected) < MAX_DETAILS:
        add_unique(
            round_robin(
                scored_groups,
                MAX_DETAILS,
            )
        )

    return selected[:MAX_DETAILS]


def fetch_documentary(movie_id, today):
    details = tmdb_get(
        f"/movie/{movie_id}",
        {"language": "en-US"},
    )

    genres = [
        item.get("name", "")
        for item in details.get("genres", [])
    ]

    genre_ids = [
        item.get("id")
        for item in details.get("genres", [])
    ]

    if 99 not in genre_ids:
        return None

    runtime = details.get("runtime")

    if (
        not isinstance(runtime, int)
        or runtime < MIN_RUNTIME
    ):
        return None

    release_date = details.get("release_date") or ""

    try:
        released = date.fromisoformat(release_date)
    except ValueError:
        return None

    if released > today:
        return None

    overview = (details.get("overview") or "").strip()

    if not overview:
        return None

    keyword_data = tmdb_get(
        f"/movie/{movie_id}/keywords"
    )

    keywords = [
        item["name"]
        for item in keyword_data.get("keywords", [])
        if item.get("name")
    ]

    poster_path = details.get("poster_path")

    poster_url = (
        "https://image.tmdb.org/t/p/w500"
        + poster_path
        if poster_path
        else None
    )

    movie = {
        "tmdb_id": movie_id,
        "title": (
            details.get("title")
            or details.get("original_title")
            or ""
        ),
        "release_date": release_date,
        "runtime": runtime,
        "overview": overview,
        "genres": genres,
        "keywords": keywords,
        "posterUrl": poster_url,
        "popularity": details.get("popularity", 0),
        "vote_average": details.get("vote_average", 0),
        "vote_count": details.get("vote_count", 0),
        "tmdb_url": (
            "https://www.themoviedb.org/movie/"
            + str(movie_id)
        ),
    }

    # Valutiamo anche le keywords e i generi
    # disponibili solo nella scheda completa.
    text_movie = {
        "title": movie["title"],
        "overview": (
            movie["overview"]
            + ". "
            + ". ".join(keywords)
        ),
    }

    preliminary = preliminary_score(text_movie)

    genre_penalty = sum(
        GENRE_PENALTIES.get(genre, 0)
        for genre in genres
    )

    preliminary["score"] -= genre_penalty
    preliminary["genre_penalty"] = genre_penalty

    movie["preliminary"] = preliminary

    movie["classification"] = (
        classify_documentary(movie)
    )

    return movie


def quality_key(movie):
    """
    Ordinamento per rilevanza investigativa.

    Il voto TMDB viene usato soltanto come
    criterio secondario.
    """
    return (
        movie["preliminary"]["score"],
        movie["classification"].get(
            "investigative_score", 0
        ),
        movie.get("vote_count", 0),
    )


def main():
    today = datetime.now(timezone.utc).date()

    print(
        "Documentary Intelligence - Discovery v3",
        flush=True,
    )

    groups = []
    unique_ids = set()
    errors = []

    for start_year, end_year in YEAR_RANGES:
        label = (
            f"{start_year}-{end_year}"
            if end_year is not None
            else f"{start_year}-oggi"
        )

        print(
            f"\nRicerca {label}",
            flush=True,
        )

        try:
            candidates = discover_period(
                start_year,
                end_year,
                today,
            )
        except Exception as error:
            errors.append({
                "stage": "discovery",
                "period": label,
                "error": str(error),
            })
            groups.append([])
            continue

        group = []

        for movie in candidates:
            movie_id = movie.get("id")

            if movie_id in unique_ids:
                continue

            unique_ids.add(movie_id)
            group.append(movie)

        groups.append(group)

        print(
            f"Candidati unici: {len(group)}",
            flush=True,
        )

    selected = select_candidates(groups)

    print(
        f"\nSchede da verificare: {len(selected)}",
        flush=True,
    )

    valid = []

    for index, candidate in enumerate(
        selected, 1
    ):
        movie_id = candidate["id"]

        print(
            f"[{index}/{len(selected)}] "
            f"{candidate.get('title', movie_id)}",
            flush=True,
        )

        try:
            movie = fetch_documentary(
                movie_id,
                today,
            )

            if movie is not None:
                valid.append(movie)

        except Exception as error:
            errors.append({
                "stage": "details",
                "tmdb_id": movie_id,
                "error": str(error),
            })

    # Prima ordiniamo tutti i documentari
    # validi e poi conserviamo i migliori.
    valid.sort(
        key=quality_key,
        reverse=True,
    )

    results = valid[:MAX_RESULTS]

    status_counts = Counter()
    genre_counts = Counter()
    decade_counts = Counter()

    for movie in results:
        classification = movie["classification"]

        status_counts[
            classification.get(
                "classification_status",
                "unknown",
            )
        ] += 1

        genre_counts.update(
            classification.get("genres", [])
        )

        year = int(movie["release_date"][:4])
        decade = f"{(year // 10) * 10}s"
        decade_counts[decade] += 1

    output = {
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "method": (
            "TMDB historical investigative discovery v3"
        ),
        "min_runtime": MIN_RUNTIME,
        "release_date_cutoff": today.isoformat(),
        "candidates_collected": len(unique_ids),
        "candidates_checked": len(selected),
        "valid_documentaries": len(valid),
        "results_count": len(results),
        "preliminary_method": (
            "investigative signals + "
            "format penalties + exploration"
        ),
        "classification_summary": {
            "status_counts": dict(status_counts),
            "genre_counts": dict(genre_counts),
            "decade_counts": dict(decade_counts),
        },
        "errors": errors,
        "results": results,
    }

    os.makedirs(
        os.path.dirname(OUTPUT_FILE),
        exist_ok=True,
    )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(
        "\nRISULTATI FINALI",
        flush=True,
    )

    print(
        "Candidati raccolti:",
        len(unique_ids),
        flush=True,
    )

    print(
        "Schede esaminate:",
        len(selected),
        flush=True,
    )

    print(
        "Documentari validi:",
        len(valid),
        flush=True,
    )

    print(
        "Risultati salvati:",
        len(results),
        flush=True,
    )

    print(
        "Candidati investigativi:",
        status_counts.get(
            "investigative_candidate", 0
        ),
        flush=True,
    )

    print(
        "Errori:",
        len(errors),
        flush=True,
    )


if __name__ == "__main__":
    main()
