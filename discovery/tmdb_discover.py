
"""
Documentary Intelligence
TMDB Discovery v2 - ricerca storica e tematicamente neutrale.

Obiettivi:
- Cercare documentari cinematografici su tutti gli argomenti.
- Esplorare periodi storici differenti.
- Escludere film non ancora usciti.
- Richiedere almeno 70 minuti di durata.
- Conservare la classificazione a regole come confronto.
- Non modificare documentaries.json.
- Non utilizzare i due film di riferimento per ordinare i risultati.

Utilizza esclusivamente la libreria standard Python.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from collections import Counter
from datetime import date, datetime, timezone

from classify import classify_documentary


# ============================================================
# CONFIGURAZIONE
# ============================================================

TOKEN = os.environ.get(
    "TMDB_READ_ACCESS_TOKEN", ""
).strip()

API_BASE = "https://api.themoviedb.org/3"

OUTPUT_FILE = "discovery/tmdb_discovery_results.json"

MIN_RUNTIME = 70

# Numero massimo di candidati per cui recuperare
# dettagli completi e parole chiave.
MAX_DETAILS = 240

# Numero massimo di risultati salvati.
MAX_RESULTS = 150

# Per ogni periodo esaminiamo piu' ordinamenti.
# Questo riduce la dipendenza dalla sola popolarita'.
SORT_MODES = [
    "popularity.desc",
    "vote_count.desc",
]

PAGES_PER_SORT = 3

# Periodi non sovrapposti. L'ultimo termina oggi.
YEAR_RANGES = [
    (1970, 1989),
    (1990, 1999),
    (2000, 2009),
    (2010, 2014),
    (2015, 2019),
    (2020, 2023),
    (2024, None),
]

REQUEST_DELAY = 0.10


# ============================================================
# TMDB API
# ============================================================

def tmdb_get(endpoint, params=None):
    if not TOKEN:
        raise RuntimeError(
            "Secret TMDB_READ_ACCESS_TOKEN mancante."
        )

    params = params or {}

    query = urllib.parse.urlencode(params)

    url = API_BASE + endpoint

    if query:
        url += "?" + query

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/json",
            "User-Agent": "DocumentaryIntelligence/2.0",
        },
    )

    for attempt in range(4):
        try:
            with urllib.request.urlopen(
                request,
                timeout=35,
            ) as response:
                data = json.load(response)

            time.sleep(REQUEST_DELAY)
            return data

        except urllib.error.HTTPError as error:
            if (
                error.code in (429, 500, 502, 503, 504)
                and attempt < 3
            ):
                time.sleep(2 ** (attempt + 1))
                continue

            raise

        except (
            urllib.error.URLError,
            TimeoutError,
        ):
            if attempt < 3:
                time.sleep(2 ** (attempt + 1))
                continue

            raise

    raise RuntimeError(
        f"Impossibile recuperare {endpoint}"
    )


# ============================================================
# SCOPERTA PER PERIODO
# ============================================================

def discover_period(start_year, end_year, today):
    start_date = f"{start_year}-01-01"

    if end_year is None:
        end_date = today.isoformat()
    else:
        end_date = min(
            date(end_year, 12, 31),
            today,
        ).isoformat()

    candidates = {}

    for sort_mode in SORT_MODES:
        for page in range(
            1,
            PAGES_PER_SORT + 1,
        ):
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

            for movie in data.get(
                "results", []
            ):
                movie_id = movie.get("id")

                if movie_id:
                    candidates[movie_id] = movie

            if page >= data.get(
                "total_pages", 0
            ):
                break

    return list(candidates.values())


# ============================================================
# DISTRIBUZIONE EQUILIBRATA
# ============================================================

def allocate_candidates(groups, limit):
    """
    Selezione round-robin tra periodi storici.

    Non usa la somiglianza con i documentari
    di riferimento e non privilegia un tema.
    """

    ordered = []

    group_lists = [
        list(group)
        for group in groups
    ]

    index = 0

    while len(ordered) < limit:
        added = False

        for group in group_lists:
            if index < len(group):
                ordered.append(group[index])
                added = True

                if len(ordered) >= limit:
                    break

        if not added:
            break

        index += 1

    return ordered


# ============================================================
# DETTAGLI E PAROLE CHIAVE
# ============================================================

def fetch_documentary(movie_id, today):
    details = tmdb_get(
        f"/movie/{movie_id}",
        {
            "language": "en-US",
        },
    )

    genres = [
        item.get("name", "")
        for item in details.get(
            "genres", []
        )
    ]

    genre_ids = [
        item.get("id")
        for item in details.get(
            "genres", []
        )
    ]

    if 99 not in genre_ids:
        return None

    runtime = details.get("runtime")

    if (
        not isinstance(runtime, int)
        or runtime < MIN_RUNTIME
    ):
        return None

    release_date = (
        details.get("release_date")
        or ""
    )

    if not release_date:
        return None

    try:
        release = date.fromisoformat(
            release_date
        )
    except ValueError:
        return None

    if release > today:
        return None

    overview = (
        details.get("overview")
        or ""
    ).strip()

    if not overview:
        return None

    keywords_data = tmdb_get(
        f"/movie/{movie_id}/keywords"
    )

    keywords = [
        item.get("name", "")
        for item in keywords_data.get(
            "keywords", []
        )
        if item.get("name")
    ]

    poster_path = details.get(
        "poster_path"
    )

    poster_url = (
        "https://image.tmdb.org/t/p/w500"
        + poster_path
        if poster_path
        else None
    )

    result = {
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
        "popularity": details.get(
            "popularity", 0
        ),
        "vote_average": details.get(
            "vote_average", 0
        ),
        "vote_count": details.get(
            "vote_count", 0
        ),
        "tmdb_url": (
            "https://www.themoviedb.org/movie/"
            + str(movie_id)
        ),
    }

    result["classification"] = (
        classify_documentary(result)
    )

    return result


# ============================================================
# ESECUZIONE
# ============================================================

def main():
    today = datetime.now(
        timezone.utc
    ).date()

    print(
        "TMDB Discovery v2",
        flush=True,
    )

    print(
        "Data limite:",
        today.isoformat(),
        flush=True,
    )

    groups = []
    discovered_ids = set()

    errors = []

    for start_year, end_year in YEAR_RANGES:
        label = (
            f"{start_year}-{end_year}"
            if end_year is not None
            else f"{start_year}-oggi"
        )

        print(
            f"\nRicerca periodo {label}",
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

            print(
                "Errore:",
                error,
                flush=True,
            )

            groups.append([])
            continue

        unique = []

        for movie in candidates:
            movie_id = movie.get("id")

            if movie_id in discovered_ids:
                continue

            discovered_ids.add(movie_id)
            unique.append(movie)

        print(
            "Candidati:",
            len(unique),
            flush=True,
        )

        groups.append(unique)

    candidates = allocate_candidates(
        groups,
        MAX_DETAILS,
    )

    print(
        "\nCandidati da verificare:",
        len(candidates),
        flush=True,
    )

    results = []

    for index, candidate in enumerate(
        candidates,
        start=1,
    ):
        movie_id = candidate["id"]

        print(
            f"[{index}/{len(candidates)}] "
            f"{candidate.get('title', movie_id)}",
            flush=True,
        )

        try:
            documentary = fetch_documentary(
                movie_id,
                today,
            )

        except Exception as error:
            errors.append({
                "stage": "details",
                "tmdb_id": movie_id,
                "error": str(error),
            })

            print(
                "Errore:",
                error,
                flush=True,
            )

            continue

        if documentary is None:
            continue

        results.append(documentary)

    # Non usiamo il punteggio investigativo
    # per decidere quali film conservare.
    # Il file serve anche per valutare il
    # comportamento dei classificatori.

    results = results[:MAX_RESULTS]

    status_counts = Counter()
    genre_counts = Counter()

    for movie in results:
        classification = movie[
            "classification"
        ]

        status_counts.update([
            classification.get(
                "classification_status",
                "unknown",
            )
        ])

        genre_counts.update(
            classification.get(
                "genres", []
            )
        )

    output = {
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "method": (
            "TMDB historical multi-period discovery v2"
        ),
        "min_runtime": MIN_RUNTIME,
        "release_date_cutoff": today.isoformat(),
        "candidates_collected": len(
            discovered_ids
        ),
        "candidates_checked": len(
            candidates
        ),
        "results_count": len(results),
        "classification_summary": {
            "status_counts": dict(
                status_counts
            ),
            "genre_counts": dict(
                genre_counts
            ),
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
        "Documentari validi:",
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

    print(
        "File:",
        OUTPUT_FILE,
        flush=True,
    )


if __name__ == "__main__":
    main()
