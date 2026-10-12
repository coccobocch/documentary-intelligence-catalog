
import json
import math
import os
import re
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone

# ============================================================
# CONFIGURAZIONE
# ============================================================

TOKEN = os.environ.get("TMDB_READ_ACCESS_TOKEN")

REFERENCE_IDS = [
    72845,   # The Man Nobody Knew
    380808,  # Zero Days
    245916,  # Kill the Messenger
]

GENRE_IDS = [
    99,     # Documentary
    36,     # History
    53,     # Thriller
    18,     # Drama
    80,     # Crime
]

PAGES_PER_GENRE = 5
MIN_RUNTIME = 70
MAX_RESULTS = 100

OUTPUT_FILE = "discovery/tmdb_discovery_results.json"

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

    with urllib.request.urlopen(
        request,
        timeout=30,
    ) as response:
        return json.load(response)


# ============================================================
# ANALISI TESTUALE
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

    document_count = len(tokenized)

    document_frequency = Counter()

    for tokens in tokenized:
        document_frequency.update(set(tokens))

    vectors = []

    for tokens in tokenized:
        counts = Counter(tokens)
        total = max(len(tokens), 1)

        vector = {}

        for word, count in counts.items():
            tf = count / total

            idf = math.log(
                (document_count + 1)
                / (document_frequency[word] + 1)
            ) + 1

            vector[word] = tf * idf

        vectors.append(vector)

    return vectors


def cosine_similarity(a, b):
    dot_product = sum(
        value * b.get(word, 0)
        for word, value in a.items()
    )

    norm_a = math.sqrt(
        sum(value * value for value in a.values())
    )

    norm_b = math.sqrt(
        sum(value * value for value in b.values())
    )

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


def poster_url(poster_path):
    if not poster_path:
        return None

    return (
        "https://image.tmdb.org/t/p/w500"
        + poster_path
    )


# ============================================================
# FILM DI RIFERIMENTO
# ============================================================

print("Recupero i film di riferimento...", flush=True)

reference_movies = []

for movie_id in REFERENCE_IDS:
    movie = tmdb_get(
        f"/movie/{movie_id}",
        {"language": "en-US"},
    )

    reference_movies.append(movie)

    print(
        "Riferimento:",
        movie.get("title"),
        flush=True,
    )


# ============================================================
# SCOPERTA DEI CANDIDATI
# ============================================================

print("\nCerco film candidati...", flush=True)

candidates = {}

for genre_id in GENRE_IDS:
    print(
        f"Analizzo genere TMDB {genre_id}...",
        flush=True,
    )

    for page in range(1, PAGES_PER_GENRE + 1):
        data = tmdb_get(
            "/discover/movie",
            {
                "with_genres": genre_id,
                "with_runtime.gte": MIN_RUNTIME,
                "sort_by": "primary_release_date.desc",
                "language": "en-US",
                "page": page,
                "include_adult": "false",
            },
        )

        for movie in data.get("results", []):
            movie_id = movie.get("id")

            if movie_id and movie.get("overview"):
                candidates[movie_id] = movie


# Aggiungiamo i film suggeriti da TMDB
# come simili ai nostri tre riferimenti.

for movie_id in REFERENCE_IDS:
    print(
        f"Cerco film simili a {movie_id}...",
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

        if candidate_id and movie.get("overview"):
            candidates[candidate_id] = movie


# Escludiamo i tre film di riferimento.

for movie_id in REFERENCE_IDS:
    candidates.pop(movie_id, None)

candidate_list = list(candidates.values())

print(
    "Candidati raccolti:",
    len(candidate_list),
    flush=True,
)


# ============================================================
# CALCOLO DELLA SIMILARITÀ
# ============================================================

reference_texts = [
    movie.get("overview", "")
    for movie in reference_movies
]

candidate_texts = [
    movie.get("overview", "")
    for movie in candidate_list
]

all_texts = reference_texts + candidate_texts

vectors = tfidf_vectors(all_texts)

reference_vectors = vectors[:len(reference_movies)]

candidate_vectors = vectors[len(reference_movies):]

results = []

for movie, vector in zip(
    candidate_list,
    candidate_vectors,
):
    similarities = [
        cosine_similarity(vector, reference)
        for reference in reference_vectors
    ]

    score = max(similarities) * 100

    results.append({
        "tmdb_id": movie["id"],
        "title": movie.get("title"),
        "release_date": movie.get("release_date"),
        "overview": movie.get("overview"),
        "genre_ids": movie.get("genre_ids", []),
        "posterUrl": poster_url(
            movie.get("poster_path")
        ),
        "similarity_score": round(score, 2),
        "reference_similarities": {
            reference_movies[i]["title"]: round(
                value * 100,
                2,
            )
            for i, value in enumerate(similarities)
        },
        "tmdb_url": (
            "https://www.themoviedb.org/movie/"
            + str(movie["id"])
        ),
    })


# ============================================================
# ORDINAMENTO E SALVATAGGIO
# ============================================================

results.sort(
    key=lambda item: item["similarity_score"],
    reverse=True,
)

output = {
    "generated_at": datetime.now(
        timezone.utc
    ).isoformat(),
    "method": "TF-IDF cosine similarity",
    "reference_movies": [
        {
            "tmdb_id": movie["id"],
            "title": movie.get("title"),
        }
        for movie in reference_movies
    ],
    "candidates_analyzed": len(candidate_list),
    "results": results[:MAX_RESULTS],
}

os.makedirs("discovery", exist_ok=True)

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

print("\nTOP 20 RISULTATI", flush=True)

for item in results[:20]:
    print(
        f"{item['similarity_score']:6.2f} | "
        f"{item['title']} "
        f"({item['release_date']})",
        flush=True,
    )

print(
    f"\nFilm analizzati: {len(candidate_list)}",
    flush=True,
)

print(
    f"Risultati salvati in: {OUTPUT_FILE}",
    flush=True,
)
