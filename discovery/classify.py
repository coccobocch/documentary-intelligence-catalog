
import re


# ============================================================
# CLASSIFICAZIONE DEI DOCUMENTARI DI INCHIESTA
# ============================================================

GENRES = {
    "politica_potere": {
        "political corruption": 5,
        "government corruption": 5,
        "political scandal": 5,
        "abuse of power": 5,
        "government": 1,
        "politics": 1,
        "election fraud": 5,
        "dictatorship": 2,
        "political repression": 3,
    },
    "intelligence_spionaggio": {
        "cia": 5,
        "intelligence agency": 5,
        "secret service": 5,
        "espionage": 5,
        "spy": 3,
        "spies": 3,
        "covert operation": 5,
        "clandestine operation": 5,
        "intelligence operation": 5,
        "classified intelligence": 5,
    },
    "criminalita_giustizia": {
        "murder investigation": 5,
        "wrongful conviction": 5,
        "miscarriage of justice": 5,
        "organized crime": 5,
        "criminal investigation": 5,
        "corruption": 2,
        "crime": 1,
        "trial": 1,
        "police misconduct": 5,
        "unsolved murder": 4,
    },
    "economia_finanza": {
        "financial fraud": 5,
        "financial crisis": 3,
        "corporate scandal": 5,
        "money laundering": 5,
        "banking scandal": 5,
        "wall street": 3,
        "corporate corruption": 5,
        "fraud": 2,
        "financial": 1,
        "bank": 1,
    },
    "tecnologia_sorveglianza": {
        "cyberwarfare": 5,
        "cyber warfare": 5,
        "cyberattack": 5,
        "cyber attack": 5,
        "stuxnet": 5,
        "malware": 4,
        "mass surveillance": 5,
        "government surveillance": 5,
        "spyware": 5,
        "data privacy": 3,
        "hacking": 2,
        "hacker": 1,
        "cybercrime": 4,
        "digital surveillance": 5,
    },
    "guerre_geopolitica": {
        "war crimes": 5,
        "military operation": 4,
        "geopolitics": 4,
        "international conflict": 4,
        "nuclear weapons": 3,
        "nuclear program": 4,
        "cold war": 3,
        "foreign policy": 3,
        "military intelligence": 5,
        "war": 1,
        "conflict": 1,
    },
    "ambiente": {
        "environmental disaster": 5,
        "environmental pollution": 5,
        "toxic waste": 5,
        "oil spill": 5,
        "climate change": 3,
        "environmental justice": 5,
        "industrial pollution": 5,
        "deforestation": 3,
        "pollution": 3,
        "environment": 1,
    },
    "salute_scienza": {
        "pharmaceutical industry": 5,
        "medical malpractice": 5,
        "health scandal": 5,
        "medical fraud": 5,
        "public health": 3,
        "clinical trial": 4,
        "drug company": 4,
        "medical research": 2,
        "healthcare": 2,
        "scientific misconduct": 5,
    },
    "societa_diritti": {
        "human rights abuse": 5,
        "human rights violation": 5,
        "civil rights": 4,
        "discrimination": 3,
        "institutional abuse": 5,
        "sexual abuse": 4,
        "social injustice": 4,
        "forced labor": 5,
        "human trafficking": 5,
        "racism": 2,
    },
    "media_disinformazione": {
        "propaganda": 5,
        "disinformation": 5,
        "misinformation": 4,
        "media manipulation": 5,
        "investigative journalism": 5,
        "press freedom": 4,
        "media censorship": 5,
        "fake news": 4,
        "journalism": 2,
        "whistleblower": 4,
    },
}


# Indizi che un'opera utilizzi un approccio investigativo.
# Questi termini non dimostrano da soli che sia un'inchiesta.

INVESTIGATIVE_TERMS = {
    "investigation": 4,
    "investigative": 4,
    "investigates": 4,
    "investigating": 4,
    "uncovers": 3,
    "exposes": 3,
    "reveals": 1,
    "whistleblower": 4,
    "cover-up": 4,
    "cover up": 3,
    "hidden documents": 4,
    "classified documents": 4,
    "leaked documents": 4,
    "secret documents": 3,
    "corruption": 2,
    "fraud": 2,
    "scandal": 2,
    "accountability": 3,
    "evidence": 2,
    "testimonies": 2,
    "undercover": 4,
    "wrongdoing": 3,
    "abuse of power": 4,
    "misconduct": 3,
}

# Espressioni deboli che possono indicare un film
# descrittivo o celebrativo anziche' un'inchiesta.

NON_INVESTIGATIVE_TERMS = {
    "concert film": 4,
    "live concert": 4,
    "concert tour": 3,
    "behind the scenes": 2,
    "career retrospective": 3,
    "portrait of an artist": 3,
    "wildlife photography": 3,
    "nature documentary": 3,
    "travelogue": 3,
}


def normalize(text):
    text = (text or "").lower()
    text = text.replace("’", "'")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def contains_term(text, term):
    pattern = (
        r"(?<!\w)"
        + re.escape(normalize(term))
        + r"(?!\w)"
    )
    return re.search(pattern, text) is not None


def weighted_matches(text, terms):
    matches = []
    total = 0

    for term, weight in terms.items():
        if contains_term(text, term):
            total += weight
            matches.append({
                "term": term,
                "weight": weight,
            })

    return total, matches


def classify_documentary(movie):
    """
    Accetta un dizionario con:
      title
      overview
      keywords
      genres
      runtime

    Restituisce una classificazione preliminare.
    """

    overview = normalize(movie.get("overview"))
    title = normalize(movie.get("title"))

    keywords = movie.get("keywords") or []
    tmdb_genres = movie.get("genres") or []

    keyword_text = normalize(" ".join(keywords))
    combined_text = " ".join([
        title,
        overview,
        keyword_text,
    ])

    # --------------------------------------------------------
    # Verifica dei requisiti cinematografici
    # --------------------------------------------------------

    genre_names = [
        normalize(
            genre.get("name", "")
            if isinstance(genre, dict)
            else str(genre)
        )
        for genre in tmdb_genres
    ]

    is_documentary = "documentary" in genre_names

    runtime = movie.get("runtime")
    feature_length = (
        isinstance(runtime, (int, float))
        and not isinstance(runtime, bool)
        and runtime >= 70
    )

    # --------------------------------------------------------
    # Valutazione dell'approccio investigativo
    # --------------------------------------------------------

    overview_score, overview_evidence = weighted_matches(
        overview,
        INVESTIGATIVE_TERMS,
    )

    keyword_score, keyword_evidence = weighted_matches(
        keyword_text,
        INVESTIGATIVE_TERMS,
    )

    negative_score, negative_evidence = weighted_matches(
        combined_text,
        NON_INVESTIGATIVE_TERMS,
    )

    investigative_score = max(
        0,
        overview_score
        + keyword_score
        - negative_score,
    )

    # --------------------------------------------------------
    # Classificazione multilabel dei generi
    # --------------------------------------------------------

    genre_scores = {}
    genre_evidence = {}

    for genre_id, terms in GENRES.items():
        overview_points, overview_matches = weighted_matches(
            overview,
            terms,
        )

        keyword_points, keyword_matches = weighted_matches(
            keyword_text,
            terms,
        )

        title_points, title_matches = weighted_matches(
            title,
            terms,
        )

        # Le keyword esplicite ricevono un peso maggiore.
        score = (
            overview_points
            + keyword_points * 1.5
            + title_points * 0.5
        )

        genre_scores[genre_id] = round(score, 2)

        genre_evidence[genre_id] = {
            "overview": overview_matches,
            "keywords": keyword_matches,
            "title": title_matches,
        }

    # Una soglia iniziale conservativa.
    # La calibreremo su film verificati manualmente.

    assigned_genres = [
        genre_id
        for genre_id, score in genre_scores.items()
        if score >= 4
    ]

    assigned_genres.sort(
        key=lambda genre_id: genre_scores[genre_id],
        reverse=True,
    )

    # Non usiamo "verified" qui:
    # la classificazione e' soltanto automatica.

    if not is_documentary or not feature_length:
        status = "excluded_format"

    elif investigative_score >= 5:
        status = "investigative_candidate"

    else:
        status = "needs_review"

    return {
        "title": movie.get("title"),
        "tmdb_id": movie.get("tmdb_id"),
        "is_documentary": is_documentary,
        "feature_length": feature_length,
        "investigative_score": investigative_score,
        "investigative_evidence": {
            "overview": overview_evidence,
            "keywords": keyword_evidence,
            "negative": negative_evidence,
        },
        "genres": assigned_genres,
        "genre_scores": genre_scores,
        "genre_evidence": genre_evidence,
        "classification_status": status,
        "classification_method": "weighted_rules_v1",
    }


# ============================================================
# TEST LOCALE
# ============================================================

if __name__ == "__main__":
    example = {
        "tmdb_id": 380808,
        "title": "Zero Days",
        "runtime": 116,
        "genres": ["Documentary"],
        "overview": (
            "An investigation into Stuxnet, a malware program "
            "used in a covert operation against Iran's "
            "nuclear program."
        ),
        "keywords": [
            "hacking",
            "cybercrime",
        ],
    }

    import json

    result = classify_documentary(example)

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )
