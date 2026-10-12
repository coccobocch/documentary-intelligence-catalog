
import json
import os
import urllib.error
import urllib.request

TOKEN = os.environ.get("TMDB_READ_ACCESS_TOKEN")

MOVIES = {
    72845: "The Man Nobody Knew",
    380808: "Zero Days",
    245916: "Kill the Messenger",
}

if not TOKEN:
    raise SystemExit("ERRORE: token TMDB non configurato.")


def tmdb_get(path):
    url = f"https://api.themoviedb.org/3{path}"

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


results = []

for movie_id, expected_title in MOVIES.items():
    print(f"\nAnalisi: {expected_title} ({movie_id})")

    try:
        movie = tmdb_get(f"/movie/{movie_id}?language=en-US")
        keywords_data = tmdb_get(f"/movie/{movie_id}/keywords")

        result = {
            "tmdb_id": movie_id,
            "title": movie.get("title"),
            "release_date": movie.get("release_date"),
            "runtime": movie.get("runtime"),
            "genres": [
                genre["name"]
                for genre in movie.get("genres", [])
            ],
            "overview": movie.get("overview"),
            "keywords": [
                keyword["name"]
                for keyword in keywords_data.get("keywords", [])
            ],
        }

        results.append(result)

        print("Titolo:", result["title"])
        print("Generi:", ", ".join(result["genres"]))
        print("Keyword:", ", ".join(result["keywords"]))

    except (urllib.error.URLError, ValueError) as error:
        print("ERRORE:", error)

os.makedirs("discovery", exist_ok=True)

with open(
    "discovery/tmdb_test_results.json",
    "w",
    encoding="utf-8",
) as file:
    json.dump(
        results,
        file,
        ensure_ascii=False,
        indent=2,
    )

print("\nTest completato.")
print("Risultati: discovery/tmdb_test_results.json")
