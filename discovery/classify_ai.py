
"""
Documentary Intelligence
Classificatore AI zero-shot sperimentale.

Legge i risultati del precedente test TMDB.
Non modifica documentaries.json.
Non sostituisce classify.py.

Dipendenze (da installare nel prossimo passaggio):
    torch
    transformers
    sentencepiece
    protobuf
"""

import json
import os
from collections import Counter
from datetime import datetime, timezone

from transformers import pipeline


# ============================================================
# CONFIGURAZIONE
# ============================================================

MODEL_NAME = (
    "MoritzLaurer/"
    "deberta-v3-base-zeroshot-v1.1-all-33"
)

INPUT_FILE = "discovery/tmdb_discovery_results.json"
OUTPUT_FILE = "discovery/ai_classification_results.json"

# Soglie sperimentali, non ancora calibrate.
INVESTIGATIVE_THRESHOLD = 0.70
GENRE_THRESHOLD = 0.50

# Nessuna esclusione automatica.
# Analizziamo tutti i documentari disponibili.
MAX_MOVIES = None


# ============================================================
# CLASSIFICAZIONE DEL METODO NARRATIVO
# ============================================================

APPROACH_LABELS = {
    "investigative": (
        "an investigative documentary that examines "
        "evidence, uncovers hidden facts, exposes wrongdoing "
        "or investigates an unresolved question"
    ),
    "historical": (
        "a historical documentary that explains past "
        "events without conducting a new investigation"
    ),
    "biographical": (
        "a biographical documentary portraying the life "
        "and achievements of a person"
    ),
    "observational": (
        "an observational documentary following people "
        "and their everyday experiences"
    ),
    "educational": (
        "an educational documentary explaining a subject "
        "without investigating wrongdoing or hidden facts"
    ),
    "performance": (
        "a documentary about an artistic performance, "
        "concert, cultural event or creative process"
    ),
}

APPROACH_DESCRIPTIONS = list(APPROACH_LABELS.values())

APPROACH_REVERSE = {
    value: key
    for key, value in APPROACH_LABELS.items()
}


# ============================================================
# GENERI TEMATICI
# ============================================================

GENRE_LABELS = {
    "politica_potere": (
        "political power, governments, elections, "
        "political corruption and abuse of authority"
    ),
    "intelligence_spionaggio": (
        "intelligence agencies, espionage, spies, "
        "covert operations and secret services"
    ),
    "criminalita_giustizia": (
        "criminal investigations, murders, organized crime, "
        "trials, justice and wrongful convictions"
    ),
    "economia_finanza": (
        "economics, banking, financial fraud, corporations, "
        "business scandals and economic inequality"
    ),
    "tecnologia_sorveglianza": (
        "technology, hacking, cybersecurity, digital "
        "surveillance, artificial intelligence and privacy"
    ),
    "guerre_geopolitica": (
        "wars, armed conflicts, military operations, "
        "international relations and geopolitics"
    ),
    "ambiente": (
        "environmental damage, pollution, climate change, "
        "natural resources and ecological controversies"
    ),
    "salute_scienza": (
        "medicine, public health, pharmaceuticals, "
        "scientific research and health controversies"
    ),
    "societa_diritti": (
        "human rights, civil liberties, discrimination, "
        "social injustice, labor rights and activism"
    ),
    "media_disinformazione": (
        "journalism, news media, propaganda, censorship, "
        "disinformation and media manipulation"
    ),
}

GENRE_DESCRIPTIONS = list(GENRE_LABELS.values())

GENRE_REVERSE = {
    value: key
    for key, value in GENRE_LABELS.items()
}


# ============================================================
# MODELLO
# ============================================================

def load_classifier():
    print(
        "Caricamento modello AI:",
        MODEL_NAME,
        flush=True,
    )

    classifier = pipeline(
        task="zero-shot-classification",
        model=MODEL_NAME,
        device=-1,
    )

    print("Modello caricato.", flush=True)
    return classifier


# ============================================================
# TESTO DA ANALIZZARE
# ============================================================

def build_text(movie):
    title = movie.get("title") or ""
    overview = movie.get("overview") or ""
    keywords = movie.get("keywords") or []

    if isinstance(keywords, list):
        keywords_text = ", ".join(
            str(keyword)
            for keyword in keywords
        )
    else:
        keywords_text = str(keywords)

    return (
        f"Documentary title: {title}\n"
        f"Synopsis: {overview}\n"
        f"Topics and keywords: {keywords_text}"
    )


# ============================================================
# CLASSIFICAZIONE DEL DOCUMENTARIO
# ============================================================

def classify_movie(classifier, movie):
    text = build_text(movie)

    # Prima valutiamo il tipo di documentario.
    # Le categorie sono alternative: multi_label=False.

    approach_output = classifier(
        text,
        candidate_labels=APPROACH_DESCRIPTIONS,
        hypothesis_template=(
            "This film is {}."
        ),
        multi_label=False,
        truncation=True,
    )

    approach_scores = {
        APPROACH_REVERSE[label]: round(
            float(score), 4
        )
        for label, score in zip(
            approach_output["labels"],
            approach_output["scores"],
        )
    }

    investigative_score = approach_scores.get(
        "investigative", 0.0
    )

    best_approach = APPROACH_REVERSE[
        approach_output["labels"][0]
    ]

    # I generi non sono alternativi.
    # Un film puo' appartenere a piu' categorie.

    genre_output = classifier(
        text,
        candidate_labels=GENRE_DESCRIPTIONS,
        hypothesis_template=(
            "This documentary is about {}."
        ),
        multi_label=True,
        truncation=True,
    )

    genre_scores = {
        GENRE_REVERSE[label]: round(
            float(score), 4
        )
        for label, score in zip(
            genre_output["labels"],
            genre_output["scores"],
        )
    }

    selected_genres = [
        genre
        for genre, score in sorted(
            genre_scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        if score >= GENRE_THRESHOLD
    ]

    if investigative_score >= INVESTIGATIVE_THRESHOLD:
        status = "investigative_candidate"
    else:
        status = "needs_review"

    return {
        "tmdb_id": movie.get("tmdb_id"),
        "title": movie.get("title"),
        "best_approach": best_approach,
        "investigative_score": round(
            investigative_score, 4
        ),
        "approach_scores": approach_scores,
        "genres": selected_genres,
        "genre_scores": genre_scores,
        "classification_status": status,
        "classification_method": "deberta_zero_shot_v1",
        "model": MODEL_NAME,
        "previous_classification": movie.get(
            "classification"
        ),
    }


# ============================================================
# ESECUZIONE
# ============================================================

def main():
    if not os.path.isfile(INPUT_FILE):
        raise SystemExit(
            f"File non trovato: {INPUT_FILE}\n"
            "Eseguire prima tmdb_discover.py."
        )

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(file)

    movies = data.get("results", [])

    if MAX_MOVIES is not None:
        movies = movies[:MAX_MOVIES]

    print(
        f"Documentari da analizzare: {len(movies)}",
        flush=True,
    )

    classifier = load_classifier()

    results = []
    errors = []

    for index, movie in enumerate(movies, start=1):
        title = movie.get("title", "Senza titolo")

        print(
            f"[{index}/{len(movies)}] {title}",
            flush=True,
        )

        try:
            result = classify_movie(
                classifier,
                movie,
            )

            results.append(result)

            print(
                "  Approccio:",
                result["best_approach"],
                flush=True,
            )

            print(
                "  Investigativo:",
                result["investigative_score"],
                flush=True,
            )

            print(
                "  Generi:",
                ", ".join(result["genres"])
                or "nessuno",
                flush=True,
            )

        except Exception as error:
            errors.append({
                "tmdb_id": movie.get("tmdb_id"),
                "title": title,
                "error": str(error),
            })

            print(
                "  ERRORE:",
                str(error),
                flush=True,
            )

    status_counts = Counter(
        item["classification_status"]
        for item in results
    )

    genre_counts = Counter()

    for item in results:
        genre_counts.update(item["genres"])

    output = {
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "model": MODEL_NAME,
        "input_file": INPUT_FILE,
        "movies_analyzed": len(results),
        "investigative_threshold": INVESTIGATIVE_THRESHOLD,
        "genre_threshold": GENRE_THRESHOLD,
        "status_counts": dict(status_counts),
        "genre_counts": dict(genre_counts),
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

    print("\nRISULTATI FINALI", flush=True)

    print(
        "Documentari analizzati:",
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
        "Da verificare:",
        status_counts.get(
            "needs_review", 0
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
