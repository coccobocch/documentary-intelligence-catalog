"""Documentary Intelligence: test AI v3 su 20 documentari fissi.
Non modifica il catalogo pubblicato o classify.py.
Dipendenze: torch, transformers, sentencepiece, protobuf.
"""
import json
import os
from collections import Counter
from datetime import datetime, timezone
from transformers import pipeline

MODEL_NAME = 'MoritzLaurer/deberta-v3-base-zeroshot-v1.1-all-33'
INPUT_FILE = 'discovery/tmdb_discovery_results.json'
OUTPUT_FILE = 'discovery/ai_classification_results.json'
INVESTIGATIVE_THRESHOLD = 0.70
GENRE_THRESHOLD = 0.50
RULE_GENRE_THRESHOLD = 5.0

TEST_GROUPS = {
    'investigative_examples': [
        'Citizenfour', 'The Thin Blue Line', 'Inside Job', 'Collective',
        'Black Box Diaries', 'The Invisible War', 'Dirty Wars',
        'The Inventor: Out for Blood in Silicon Valley',
        'Going Clear: Scientology and the Prison of Belief', 'The Dissident',
    ],
    'borderline_examples': [
        'Super Size Me', 'Bowling for Columbine', 'The Social Dilemma',
        'No Other Land', 'Paris Is Burning',
    ],
    'non_investigative_examples': [
        'Jackass 3D', 'Stop Making Sense', 'Baraka', 'Free Solo',
        'Harry Potter 20th Anniversary: Return to Hogwarts',
    ],
}

# Confronto binario diretto: la seconda etichetta non implica
# che il soggetto del film sia privo di controversie.
APPROACH_LABELS = {
    'investigative': (
        'a documentary that investigates a specific question using evidence, '
        'testimony or original reporting to uncover facts or challenge an official account'
    ),
    'non_investigative': (
        'a documentary that primarily observes, portrays, celebrates or explains '
        'people, events or subjects without conducting an evidence-based inquiry'
    ),
}

GENRE_LABELS = {
    'politica_potere': 'government, politics and abuse of political power',
    'intelligence_spionaggio': 'intelligence agencies, espionage and secret operations',
    'criminalita_giustizia': 'crime, criminal justice and legal investigations',
    'economia_finanza': 'business, corporations, banking and financial wrongdoing',
    'tecnologia_sorveglianza': 'technology, cybersecurity, digital surveillance and privacy',
    'guerre_geopolitica': 'war, military conflict and international geopolitics',
    'ambiente': 'environmental damage, climate change and pollution',
    'salute_scienza': 'medicine, public health and scientific research',
    'societa_diritti': 'human rights, discrimination and social injustice',
    'media_disinformazione': 'journalism, propaganda, disinformation and news media',
}


def select_test_movies(movies):
    by_title = {str(m.get('title', '')).casefold(): m for m in movies}
    chosen, missing = [], []
    for group, titles in TEST_GROUPS.items():
        for title in titles:
            movie = by_title.get(title.casefold())
            if movie is None:
                missing.append(title)
            else:
                item = dict(movie)
                item['test_group'] = group
                chosen.append(item)
    if missing:
        raise ValueError('Titoli assenti nel JSON TMDB v3.1: ' + ', '.join(missing))
    if len(chosen) != 20 or len({m['tmdb_id'] for m in chosen}) != 20:
        raise ValueError('Campione non valido: servono 20 film distinti')
    return chosen


def build_text(movie):
    keywords = movie.get('keywords') or []
    if not isinstance(keywords, list):
        keywords = [str(keywords)]
    return (
        f"Title: {movie.get('title') or ''}\n"
        f"Synopsis: {movie.get('overview') or ''}\n"
        f"Keywords: {', '.join(map(str, keywords))}"
    )


def score_labels(classifier, text, labels, template, multi_label):
    descriptions = list(labels.values())
    reverse = {description: key for key, description in labels.items()}
    result = classifier(
        text, candidate_labels=descriptions,
        hypothesis_template=template, multi_label=multi_label,
        truncation=True,
    )
    return {
        reverse[label]: round(float(score), 4)
        for label, score in zip(result['labels'], result['scores'])
    }


def classify_movie(classifier, movie):
    text = build_text(movie)
    approach_scores = score_labels(
        classifier, text, APPROACH_LABELS, 'This film is {}.', False
    )
    investigative_score = approach_scores['investigative']
    genre_scores = score_labels(
        classifier, text, GENRE_LABELS, 'The main subject of this film is {}.', True
    )
    previous = movie.get('classification') or {}
    rule_genre_scores = previous.get('genre_scores') or {}
    ai_genres = {g for g, score in genre_scores.items() if score >= GENRE_THRESHOLD}
    rule_genres = {
        g for g, score in rule_genre_scores.items()
        if g in GENRE_LABELS and isinstance(score, (int, float))
        and score >= RULE_GENRE_THRESHOLD
    }
    # Le due fonti rimangono distinte per valutare eventuali conflitti.
    combined_genres = sorted(ai_genres | rule_genres)
    status = (
        'investigative_candidate' if investigative_score >= INVESTIGATIVE_THRESHOLD
        else 'needs_review'
    )
    return {
        'tmdb_id': movie.get('tmdb_id'),
        'title': movie.get('title'),
        'test_group': movie['test_group'],
        'best_approach': max(approach_scores, key=approach_scores.get),
        'investigative_score': investigative_score,
        'approach_scores': approach_scores,
        'genres': combined_genres,
        'ai_genres': sorted(ai_genres),
        'rule_genres': sorted(rule_genres),
        'genre_scores': genre_scores,
        'classification_status': status,
        'classification_method': 'binary_approach_plus_independent_genres_v3',
        'model': MODEL_NAME,
        'previous_classification': previous,
    }


def main():
    if not os.path.isfile(INPUT_FILE):
        raise SystemExit('File mancante: ' + INPUT_FILE)
    with open(INPUT_FILE, encoding='utf-8') as handle:
        data = json.load(handle)
    movies = select_test_movies(data.get('results', []))
    print('Caricamento modello:', MODEL_NAME, flush=True)
    classifier = pipeline('zero-shot-classification', model=MODEL_NAME, device=-1)
    results, errors = [], []
    for index, movie in enumerate(movies, 1):
        print(f"[{index}/20] {movie['title']}", flush=True)
        try:
            result = classify_movie(classifier, movie)
            results.append(result)
            print('  Approccio:', result['best_approach'],
                  '| investigativo:', result['investigative_score'], flush=True)
            print('  Generi:', ', '.join(result['genres']) or 'nessuno', flush=True)
        except Exception as exc:
            errors.append({'tmdb_id': movie.get('tmdb_id'),
                           'title': movie.get('title'), 'error': str(exc)})
            print('  ERRORE:', str(exc), flush=True)

    statuses = Counter(r['classification_status'] for r in results)
    genres = Counter(g for r in results for g in r['genres'])
    group_metrics = {}
    for group in TEST_GROUPS:
        group_results = [r for r in results if r['test_group'] == group]
        group_metrics[group] = {
            'analyzed': len(group_results),
            'investigative_candidates': sum(
                r['classification_status'] == 'investigative_candidate'
                for r in group_results
            ),
            'without_genres': sum(not r['genres'] for r in group_results),
        }
    output = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'model': MODEL_NAME,
        'experiment': 'curated_20_binary_approach_v3',
        'sample_groups': {g: len(t) for g, t in TEST_GROUPS.items()},
        'score_note': 'Zero-shot scores are not calibrated probabilities.',
        'input_file': INPUT_FILE,
        'movies_analyzed': len(results),
        'investigative_threshold': INVESTIGATIVE_THRESHOLD,
        'genre_threshold': GENRE_THRESHOLD,
        'rule_genre_threshold': RULE_GENRE_THRESHOLD,
        'status_counts': dict(statuses),
        'genre_counts': dict(genres),
        'group_metrics': group_metrics,
        'errors': errors,
        'results': results,
    }
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as handle:
        json.dump(output, handle, ensure_ascii=False, indent=2)
    print('\nRISULTATI FINALI:', json.dumps(group_metrics, ensure_ascii=False), flush=True)
    print('Errori:', len(errors), '| File:', OUTPUT_FILE, flush=True)
    if errors:
        raise SystemExit('Classificazione incompleta: consultare il JSON degli errori')


if __name__ == '__main__':
    main()
