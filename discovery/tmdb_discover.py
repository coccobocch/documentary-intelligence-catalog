
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone

from classify import classify_documentary


# ============================================================
# CONFIGURAZIONE
# ============================================================

TOKEN = os.environ.get("TMDB_READ_ACCESS_TOKEN")

REFERENCE_IDS = [
    72845,   # The Man Nobody Knew
    380808,  # Zero Days
]

DOCUMENTARY_GENRE_ID = 99

PAGES_PER_SEARCH = 15
MIN_RUNTIME = 70
MAX_RESULTS = 100
MAX_DETAILED_CHECKS = 150

OUTPUT_FILE = "discovery/tmdb_discovery_results.json"

# Questi temi servono ancora per il punteggio sperimentale
# del motore precedente.
#
# La nuova classificazione dei generi, invece, viene
# eseguita separatamente da classify.py.

TOPIC_GROUPS = {
    "intelligence": [
        "cia",
        "intelligence",
        "espionage",
        "spy",
        "spies",
        "secret service",
        "intelligence agency",
        "national security",
    ],
    "covert_operations": [
        "covert",
        "clandestine",
        "secret operation",
        "secret program",
        "black ops",
        "sabotage",
        "undercover",
    ],
    "government_secrecy": [
        "classified",
        "government cover-up",
        "government conspiracy",
        "state secrets",
        "government secrecy",
        "classified documents",
        "secret documents",
    ],
    "investigations": [
        "investigation",
        "investigative",
        "investigates",
        "exposes",
        "uncovers",
        "whistleblower",
        "leaked documents",
        "political scandal",
        "corruption",
    ],
    "cyberwarfare": [
        "cyberwarfare",
        "cyber warfare",
        "cyberattack",
        "cyber attack",
        "stuxnet",
        "malware",
        "hacking",
        "cybercrime",
        "surveillance",
    ],
    "geopolitics": [
        "cold war",
        "geopolitics",
        "nuclear program",
        "nuclear programme",
        "military intelligence",
        "iran",
        "israel",
        "national security",
    ],
}

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "on",
    "at", "to", "for", "with", "from", "by", "is",
    "are", "was", "were", "be", "been", "this",
    "that", "his", "her", "their", "its", "as",
    "who", "which", "into", "about", "after",
    "before", "through", "during", "over",
    "under", "he", "she", "they", "it", "but",
    "not", "has", "have", "had", "will", "can",
    "all", "one", "two", "new", "when", "where",
    "how", "what", "why", "more", "than", "also",
    "film", "documentary", "story", "tells",
    "explores", "follows", "life", "world",
}

if not TOKEN:
    raise SystemExit(
        "ERRORE: TMDB_READ_ACCESS_TOKEN non configurato."
    )


# ============================================================
# API TMDB
# ============================================================

def tmdb_get(endpoint, params=None):
    params = params or {}

    query = urllib.parse.urlencode(params)
    url = "https://api.themoviedb.org/3" + endpoint

    if query:
        url += "?" + query

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/json",
        },
    )

    for attempt in range(3):
        try:
            with urllib.request.urlopen(
                request,
                timeout=30,
            ) as response:
                return json.load(response)

        except urllib.error.HTTPError as error:
            if error.code in (429, 500, 502, 503, 504):
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))
                    continue

            raise

        except urllib.error.URLError:
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue

            raise

    raise RuntimeError("Richiesta TMDB non riuscita")


def get_movie(movie_id):
    return tmdb_get(
        f"/movie/{movie_id}",
        {"language": "en-US"},
    )


def get_keywords(movie_id):
    data = tmdb_get(f"/movie/{movie_id}/keywords")

    return [
        item["name"]
        for item in data.get("keywords", [])
        if item.get("name")
    ]


def poster_url(path):
    if not path:
        return None

    return "https://image.tmdb.org/t/p/w500" + path


# ============================================================
# TOKENIZZAZIONE E TF-IDF
# ============================================================

def tokenize(text):
    words = re.findall(
        r"[a-z]+",
        (text or "").lower(),
    )

    return [
        word
        for word in words
        if len(word) > 2 and word not in STOPWORDS
    ]


def tfidf_vectors(documents):
    tokenized = [
        tokenize(document)
        for document in documents
    ]

    count = len(tokenized)
    document_frequency = Counter()

    for tokens in tokenized:
        document_frequency.update(set(tokens))

    vectors = []

    for tokens in tokenized:
        frequencies = Counter(tokens)
        total = max(len(tokens), 1)

        vector = {}

        for word, frequency in frequencies.items():
            tf = frequency / total

            idf = math.log(
                (count + 1)
                / (document_frequency[word] + 1)
            ) + 1

            vector[word] = tf * idf

        vectors.append(vector)

    return vectors


def cosine_similarity(a, b):
    dot = sum(
        value * b.get(word, 0)
        for word, value in a.items()
    )

    norm_a = math.sqrt(
        sum(value * value for value in a.values())
    )

    norm_b = math.sqrt(
        sum(value * value for value in b.values())
    )

    if not norm_a or not norm_b:
        return 0.0

    return dot / (norm_a * norm_b)


# ============================================================
# PUNTEGGIO TEMATICO PRECEDENTE
# ============================================================

def find_topics(text):
    text = (text or "").lower()
    found = []

    for group, expressions in TOPIC_GROUPS.items():
        for expression in expressions:
            pattern = (
                r"(?<!\w)"
                + re.escape(expression)
                + r"(?!\w)"
            )

            if re.search(pattern, text):
                found.append(group)
                break

    return found


def calculate_topic_score(topics):
    return min(len(topics) * 20, 100)


# ============================================================
# FILM DI RIFERIMENTO
# ============================================================

print(
    "Recupero i documentari di riferimento...",
    flush=True,
)

reference_movies = []

for movie_id in REFERENCE_IDS:
    movie = get_movie(movie_id)
    reference_movies.append(movie)

    print(
        "Riferimento:",
        movie.get("title"),
        flush=True,
    )


# ============================================================
# SCOPERTA DEI DOCUMENTARI
# ============================================================

print("\nCerco documentari...", flush=True)

candidates = {}

# Ricerca per data di uscita.
# Questa strategia e' ancora provvisoria:
# successivamente introdurremo una scoperta
# piu' ampia e indipendente dai film di riferimento.

for page in range(1, PAGES_PER_SEARCH + 1):
    data = tmdb_get(
        "/discover/movie",
        {
            "with_genres": DOCUMENTARY_GENRE_ID,
            "sort_by": "primary_release_date.desc",
            "language": "en-US",
            "include_adult": "false",
            "page": page,
        },
    )

    for movie in data.get("results", []):
        movie_id = movie.get("id")

        if (
            movie_id
            and movie.get("overview")
            and DOCUMENTARY_GENRE_ID
            in movie.get("genre_ids", [])
        ):
            candidates[movie_id] = movie


# Suggerimenti TMDB relativi ai riferimenti.

for movie_id in REFERENCE_IDS:
    print(
        f"Cerco documentari simili a {movie_id}...",
        flush=True,
    )

    data = tmdb_get(
        f"/movie/{movie_id}/similar",
        {
            "language": "en-US",
            "page": 1,
        },
    )

    for movie in data.get("results", []):
        candidate_id = movie.get("id")

        if (
            candidate_id
            and movie.get("overview")
            and DOCUMENTARY_GENRE_ID
            in movie.get("genre_ids", [])
        ):
            candidates[candidate_id] = movie


# Rimuoviamo i film di riferimento.

for movie_id in REFERENCE_IDS:
    candidates.pop(movie_id, None)

candidate_list = list(candidates.values())

print(
    "Candidati raccolti:",
    len(candidate_list),
    flush=True,
)


# ============================================================
# CLASSIFICA PRELIMINARE
# ============================================================

reference_texts = [
    movie.get("overview", "")
    for movie in reference_movies
]

candidate_texts = [
    movie.get("overview", "")
    for movie in candidate_list
]

vectors = tfidf_vectors(
    reference_texts + candidate_texts
)

reference_vectors = vectors[:len(reference_movies)]
candidate_vectors = vectors[len(reference_movies):]

preliminary_results = []

for movie, vector in zip(
    candidate_list,
    candidate_vectors,
):
    similarities = [
        cosine_similarity(vector, reference)
        for reference in reference_vectors
    ]

    text_score = max(similarities) * 100

    topics = find_topics(
        movie.get("overview", "")
    )

    topic_score = calculate_topic_score(topics)

    preliminary_score = (
        text_score * 0.65
        + topic_score * 0.35
    )

    preliminary_results.append({
        "movie": movie,
        "text_score": text_score,
        "preliminary_score": preliminary_score,
        "topics": topics,
        "similarities": similarities,
    })

preliminary_results.sort(
    key=lambda item: item["preliminary_score"],
    reverse=True,
)


# ============================================================
# VERIFICA E CLASSIFICAZIONE
# ============================================================

print(
    "\nVerifico e classifico i documentari...",
    flush=True,
)

results = []
errors = []
checked_count = 0

for item in preliminary_results[:MAX_DETAILED_CHECKS]:
    movie = item["movie"]
    movie_id = movie["id"]
    checked_count += 1

    try:
        details = get_movie(movie_id)

        runtime = details.get("runtime")

        if not runtime or runtime < MIN_RUNTIME:
            continue

        genre_ids = [
            genre["id"]
            for genre in details.get("genres", [])
        ]

        if DOCUMENTARY_GENRE_ID not in genre_ids:
            continue

        keywords = get_keywords(movie_id)

        # ----------------------------------------------------
        # NUOVO CLASSIFICATORE
        # ----------------------------------------------------

        classification = classify_documentary({
            "tmdb_id": movie_id,
            "title": details.get("title"),
            "overview": details.get("overview"),
            "keywords": keywords,
            "genres": details.get("genres", []),
            "runtime": runtime,
        })

        # Non escludiamo i needs_review.
        # Vogliamo poter valutare i falsi positivi
        # e i falsi negativi del classificatore.

        # ----------------------------------------------------
        # PUNTEGGIO PRECEDENTE, MANTENUTO PER CONFRONTO
        # ----------------------------------------------------

        combined_text = (
            details.get("overview", "")
            + " "
            + " ".join(keywords)
        )

        topics = find_topics(combined_text)
        topic_score = calculate_topic_score(topics)

        final_score = (
            item["text_score"] * 0.65
            + topic_score * 0.35
        )

        results.append({
            "tmdb_id": movie_id,
            "title": details.get("title"),
            "release_date": details.get("release_date"),
            "runtime": runtime,
            "overview": details.get("overview"),
            "genres": [
                genre["name"]
                for genre in details.get("genres", [])
            ],
            "keywords": keywords,
            "matched_topics": topics,
            "posterUrl": poster_url(
                details.get("poster_path")
            ),
            "similarity_score": round(
                item["text_score"], 2
            ),
            "topic_score": round(
                topic_score, 2
            ),
            "final_score": round(
                final_score, 2
            ),
            "reference_similarities": {
                reference_movies[i]["title"]: round(
                    value * 100, 2
                )
                for i, value in enumerate(
                    item["similarities"]
                )
            },
            "classification": classification,
            "tmdb_url": (
                "https://www.themoviedb.org/movie/"
                + str(movie_id)
            ),
        })

    except (
        urllib.error.URLError,
        ValueError,
        KeyError,
    ) as error:
        errors.append({
            "tmdb_id": movie_id,
            "error": str(error),
        })

        print(
            f"Errore su {movie_id}: {error}",
            flush=True,
        )


# ============================================================
# ORDINAMENTO E SALVATAGGIO
# ============================================================

results.sort(
    key=lambda item: item["final_score"],
    reverse=True,
)

status_counts = Counter(
    item["classification"]["classification_status"]
    for item in results
)

genre_counts = Counter()

for item in results:
    genre_counts.update(
        item["classification"]["genres"]
    )

output = {
    "generated_at": datetime.now(
        timezone.utc
    ).isoformat(),
    "method": (
        "TF-IDF + thematic scoring + "
        "weighted investigative classification"
    ),
    "reference_movies": [
        {
            "tmdb_id": movie["id"],
            "title": movie.get("title"),
        }
        for movie in reference_movies
    ],
    "candidates_collected": len(candidate_list),
    "candidates_checked": checked_count,
    "results_count": len(results[:MAX_RESULTS]),
    "classification_summary": {
        "status_counts": dict(status_counts),
        "genre_counts": dict(genre_counts),
    },
    "errors": errors,
    "results": results[:MAX_RESULTS],
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


# ============================================================
# RIEPILOGO NEL LOG DI GITHUB ACTIONS
# ============================================================

print("\nTOP 20 DOCUMENTARI", flush=True)

for result in results[:20]:
    classification = result["classification"]

    print(
        f"{result['final_score']:6.2f} | "
        f"{result['title']} | "
        f"{classification['classification_status']} | "
        f"{', '.join(classification['genres']) or 'nessun genere'}",
        flush=True,
    )

print("\nRIEPILOGO CLASSIFICAZIONE", flush=True)

for status, count in status_counts.most_common():
    print(
        f"{status}: {count}",
        flush=True,
    )

print("\nGENERI ASSEGNATI", flush=True)

for genre, count in genre_counts.most_common():
    print(
        f"{genre}: {count}",
        flush=True,
    )

print(
    f"\nDocumentari trovati: {len(results)}",
    flush=True,
)

print(
    f"Risultati salvati in: {OUTPUT_FILE}",
    flush=True,
)
