import os
import random
import yaml
import json
from flask import Flask, request, jsonify, abort, Response
from plex_service import PlexService
from dotenv import load_dotenv
from functools import wraps

load_dotenv()

def load_config():
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
        with open(config_path, 'r') as file:
            return yaml.safe_load(file)
    except Exception as e:
        print(f"Error loading config.yaml: {e}")
        return {}

CONFIG = load_config()
MOOD_MAPPINGS = CONFIG.get('mood_mappings', {})

app = Flask(__name__)
plex_service = PlexService()

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = os.getenv('API_KEY')
        if not api_key:
            return f(*args, **kwargs)
            
        # Check header or query arg
        request_key = request.headers.get('X-API-KEY') or request.args.get('api_key')
        
        # Also check Authorization: Bearer <token>
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            request_key = auth_header.split(' ')[1]

        if request_key and request_key == api_key:
            return f(*args, **kwargs)
        else:
            print(f"Auth Failed! Expected: '{api_key}', Received: '{request_key}'")
            print(f"Headers: {request.headers}")
            return jsonify({"error": "Unauthorized: Invalid or missing API Key"}), 401
    return decorated_function

# Mood Mappings are now loaded from config.yaml

@app.route('/search', methods=['GET'])
@require_api_key
def search():
    """
    Search the Plex library based on filters
    """
    # Get parameters
    genre = request.args.get('genre')
    mood = request.args.get('mood')
    year_start = request.args.get('year_start', type=int)
    year_end = request.args.get('year_end', type=int)
    decade = request.args.get('decade')
    runtime_max = request.args.get('runtime_max', type=int)
    runtime_min = request.args.get('runtime_min', type=int)
    rating_min = request.args.get('rating_min', type=float)
    actor = request.args.get('actor')
    director = request.args.get('director')
    limit = request.args.get('limit', default=5, type=int)
    unwatched_only = request.args.get('unwatched_only', default='true').lower() == 'true'
    sort_order = request.args.get('sort', default='random')

    # Get library data
    data = plex_service.get_library_data()
    if not data:
        return jsonify({"error": "Failed to retrieve library data"}), 500

    movies = data['movies']
    filtered_movies = []

    # Mood preprocessing
    mood_config = MOOD_MAPPINGS.get(mood) if mood else None
    
    # Filter Logic
    for movie in movies:
        # 1. Unwatched filter
        if unwatched_only and movie['watched']:
            continue

        # 2. Genre filter (Direct or Mood-based)
        movie_genres = set(movie.get('genres', []))
        
        if genre:
            if genre not in movie_genres:
                continue
        
        if mood_config:
            # Check mood genres (must match at least one)
            if 'genres' in mood_config:
                if not any(g in movie_genres for g in mood_config['genres']):
                    continue
            
            # Check mood exclusions
            if 'exclude_genres' in mood_config:
                if any(g in movie_genres for g in mood_config['exclude_genres']):
                    continue
            
            # Check mood rating
            if 'rating_min' in mood_config:
                movie_rating = movie.get('rating') or 0
                if movie_rating < mood_config['rating_min']:
                    continue
            
            # Check mood runtime
            if 'runtime_max' in mood_config:
                movie_runtime = movie.get('runtime') or 0
                if movie_runtime > mood_config['runtime_max']:
                    continue

        # 3. Year/Decade filter
        if year_start and movie['year'] < year_start:
            continue
        if year_end and movie['year'] > year_end:
            continue
        if decade:
            try:
                decade_start = int(decade.strip("s"))
                if not (decade_start <= movie['year'] < decade_start + 10):
                    continue
            except ValueError:
                pass # Ignore invalid decade format

        # 4. Runtime filter (Explicit)
        if runtime_min and movie['runtime'] < runtime_min:
            continue
        if runtime_max and movie['runtime'] > runtime_max:
            continue

        # 5. Rating filter (Explicit)
        if rating_min:
            movie_rating = movie.get('rating') or 0
            if movie_rating < rating_min:
                continue

        # 6. People filter
        if actor:
            if not any(actor.lower() in a.lower() for a in movie.get('actors', [])):
                continue
        
        if director:
            if director.lower() not in (movie.get('director') or '').lower():
                continue

        filtered_movies.append(movie)

    # Sorting
    if sort_order == 'rating':
        filtered_movies.sort(key=lambda x: x.get('rating') or 0, reverse=True)
    elif sort_order == 'recent':
        filtered_movies.sort(key=lambda x: x.get('added_at') or 0, reverse=True) # Using added_at for recent
    elif sort_order == 'oldest':
        filtered_movies.sort(key=lambda x: x.get('year') or 0)
    elif sort_order == 'random':
        # Weighted random based on rating? Instructions say:
        # "Randomization with weights - Use rating as weight for random selection"
        # We'll simple shuffle for now, or implement weighted selection if list is long
        pass 

    # Apply Limits
    # For weighted random, we pick 'limit' items based on weights
    if sort_order == 'random' and filtered_movies:
        # Filter out movies with no rating for weighting purposes (or give them a default small weight)
        weighted_pool = [(m, (m.get('rating') or 5.0)) for m in filtered_movies]
        total_weight = sum(w for m, w in weighted_pool)
        
        selected = []
        if total_weight > 0:
            # Simple weighted selection without replacement
            temp_pool = list(weighted_pool)
            for _ in range(min(limit, len(temp_pool))):
                pick_val = random.uniform(0, sum(w for m, w in temp_pool))
                current = 0
                for i, (m, w) in enumerate(temp_pool):
                    current += w
                    if current >= pick_val:
                        selected.append(m)
                        temp_pool.pop(i)
                        break
            filtered_movies = selected
        else:
            random.shuffle(filtered_movies)
            filtered_movies = filtered_movies[:limit]
    else:
        filtered_movies = filtered_movies[:limit]

    return jsonify(filtered_movies)

@app.route('/play', methods=['POST'])
@require_api_key
def play():
    """
    Initiate playback of a specific title on a Plex client
    """
    data = request.json
    if not data:
        return jsonify({"error": "No JSON body provided"}), 400

    title = data.get('title')
    client_name = data.get('client')
    plex_key = data.get('plex_key')

    if not client_name or not plex_key:
        return jsonify({"error": "Missing client or plex_key"}), 400

    success = plex_service.play_media(client_name, plex_key)
    
    if success:
        return jsonify({
            "status": "playing",
            "title": title,
            "client": client_name
        })
    else:
        return jsonify({"error": "Failed to start playback"}), 500

@app.route('/clients', methods=['GET'])
@require_api_key
def clients():
    """
    List all available Plex clients
    """
    clients = plex_service.get_clients()
    response_list = []
    for client in clients:
        # Handle both PlexClient (GDM/Sessions) and MyPlexResource (Cloud) objects
        name = getattr(client, 'title', None) or getattr(client, 'name', 'Unknown')
        
        response_list.append({
            "name": name,
            "product": client.product,
            "device": client.device
        })
    
    # Use json.dumps to ensure strict JSON formatting
    return Response(json.dumps(response_list), mimetype='application/json')

@app.route('/history', methods=['GET'])
@require_api_key
def history():
    """
    Get user's watch history
    """
    limit = request.args.get('limit', default=50, type=int)
    days = request.args.get('days', default=90, type=int)

    history_data = plex_service.get_history(limit=limit, days=days)
    return jsonify(history_data)

@app.route('/recommend', methods=['GET'])
@require_api_key
def recommend():
    """
    AI-enhanced recommendations based on watch history and patterns
    """
    mood = request.args.get('mood')
    count = request.args.get('count', default=5, type=int)

    # Get history to analyze patterns
    history_items = plex_service.get_history(limit=50, days=90)
    
    # Analyze preferences
    genre_counts = {}
    director_counts = {}
    
    for item in history_items:
        for g in item.get('genres', []):
            genre_counts[g] = genre_counts.get(g, 0) + 1
        
        # Note: History items from plexapi might be different objects than library items,
        # so we rely on what get_history returns.
        # Currently get_history returns a dict.
        pass # We'd need more data in history for actors/directors usually, but let's use what we have

    # Determine top genres
    top_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)
    favorite_genres = [g[0] for g in top_genres[:3]]

    # Get Library
    data = plex_service.get_library_data()
    if not data:
        return jsonify({"error": "Failed to retrieve library data"}), 500
    
    movies = data['movies']
    candidates = []
    
    mood_config = MOOD_MAPPINGS.get(mood) if mood else None

    for movie in movies:
        # Exclude watched (or maybe recently watched? Instructions: "Exclude recently watched content")
        # For simplicity, let's exclude all watched for recommendations unless strictly asked otherwise,
        # but the prompt says "Exclude recently watched". 
        # Using the library's 'watched' status is safest for "unwatched recommendations".
        if movie['watched']:
            continue
            
        score = 0
        movie_genres = set(movie.get('genres', []))

        # Mood scoring
        if mood_config:
            # Filter first (Hard constraints for mood)
             if 'genres' in mood_config:
                if not any(g in movie_genres for g in mood_config['genres']):
                    continue
             if 'exclude_genres' in mood_config:
                if any(g in movie_genres for g in mood_config['exclude_genres']):
                    continue
             if 'rating_min' in mood_config:
                 if (movie.get('rating') or 0) < mood_config['rating_min']:
                     continue
             if 'runtime_max' in mood_config:
                 if (movie.get('runtime') or 0) > mood_config['runtime_max']:
                     continue
             
             score += 10 # Base score for matching mood

        # History Preference scoring
        matching_genres = [g for g in movie_genres if g in favorite_genres]
        score += len(matching_genres) * 2
        
        # Rating weight
        score += (movie.get('rating') or 0)
        
        candidates.append((movie, score))

    # Sort by score
    candidates.sort(key=lambda x: x[1], reverse=True)
    
    recommendations = [c[0] for c in candidates[:count]]
    return jsonify(recommendations)

@app.route('/library-stats', methods=['GET'])
@require_api_key
def library_stats():
    """
    Get library statistics
    """
    data = plex_service.get_library_data()
    if not data:
        return jsonify({"error": "Failed to retrieve library data"}), 500

    movies = data['movies']
    
    total_movies = len(movies)
    unwatched_movies = sum(1 for m in movies if not m['watched'])
    
    genres = set()
    decades = set()
    
    for m in movies:
        if m.get('genres'):
            genres.update(m['genres'])
        if m.get('year'):
            decade = (m['year'] // 10) * 10
            decades.add(f"{decade}s")

    return jsonify({
        "total_movies": total_movies,
        # "total_shows": 0, # Only doing movies for now based on 'Movies' library assumption
        "unwatched_movies": unwatched_movies,
        "genres": sorted(list(genres)),
        "decades_available": sorted(list(decades)),
        "last_updated": data.get('last_refresh')
    })

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)