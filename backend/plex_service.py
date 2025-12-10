import os
import time
from datetime import datetime, timedelta
from plexapi.server import PlexServer
from cachetools import TTLCache
from dotenv import load_dotenv

load_dotenv()

class PlexService:
    def __init__(self):
        self.plex_url = os.getenv('PLEX_URL')
        self.plex_token = os.getenv('PLEX_TOKEN')
        self.library_name = os.getenv('LIBRARY_NAME', 'Movies')
        self.cache_ttl = int(os.getenv('CACHE_TTL', 300))
        
        self.server = None
        self.library_section = None
        
        # Initialize cache with TTL
        # We'll use a simple dictionary for the structured data, 
        # but wraps the access with time checks or use TTLCache for the whole object if simple
        # However, to support the specific structure requested, we might manage it manually 
        # or use TTLCache for the 'library_data' key.
        self.cache = TTLCache(maxsize=1, ttl=self.cache_ttl)
        
        self._connect()

    def _connect(self):
        """Establish connection to Plex Server"""
        if not self.plex_url or not self.plex_token:
            print("Warning: PLEX_URL or PLEX_TOKEN not set.")
            return

        try:
            self.server = PlexServer(self.plex_url, self.plex_token)
            print(f"Connected to Plex Server: {self.server.friendlyName}")
            self.library_section = self.server.library.section(self.library_name)
        except Exception as e:
            print(f"Failed to connect to Plex: {e}")
            self.server = None

    def _serialize_movie(self, movie):
        """Convert Plex movie object to dictionary"""
        return {
            "title": movie.title,
            "year": movie.year,
            "summary": movie.summary,
            "rating": movie.audienceRating if movie.audienceRating else movie.rating, # Prefer audience rating, fallback to critic
            "genres": [g.tag for g in movie.genres],
            "runtime": int(movie.duration / 60000) if movie.duration else 0, # ms to minutes
            "director": movie.directors[0].tag if movie.directors else None,
            "actors": [role.tag for role in movie.roles],
            "content_rating": movie.contentRating,
            "watched": movie.isPlayed,
            "view_count": movie.viewCount,
            "last_viewed_at": movie.lastViewedAt,
            "added_at": movie.addedAt,
            "plex_key": movie.key,
            "rating_key": movie.ratingKey,
            "guid": movie.guid
        }

    def get_library_data(self, force_refresh=False):
        """Get library data, utilizing cache"""
        if not self.server:
            self._connect()
            if not self.server:
                return None

        # Check cache
        if not force_refresh and 'library_data' in self.cache:
            return self.cache['library_data']

        print("Refreshing library cache...")
        try:
            all_movies = self.library_section.all()
            
            movies_data = []
            all_genres = set()
            all_actors = set()
            all_directors = set()

            for movie in all_movies:
                serialized = self._serialize_movie(movie)
                movies_data.append(serialized)
                
                # Aggregate metadata
                if serialized['genres']:
                    all_genres.update(serialized['genres'])
                if serialized['actors']:
                    all_actors.update(serialized['actors'])
                if serialized['director']:
                    all_directors.add(serialized['director'])

            library_data = {
                "movies": movies_data,
                "genres": sorted(list(all_genres)),
                "actors": sorted(list(all_actors)),
                "directors": sorted(list(all_directors)),
                "last_refresh": datetime.utcnow().isoformat()
            }

            self.cache['library_data'] = library_data
            return library_data

        except Exception as e:
            print(f"Error fetching library data: {e}")
            return None

    def get_clients(self):
        """Get available clients"""
        if not self.server:
            self._connect()
        try:
            return self.server.clients()
        except Exception as e:
            print(f"Error fetching clients: {e}")
            return []

    def play_media(self, client_name, plex_key):
        """Play media on a specific client"""
        if not self.server:
            self._connect()
        
        try:
            client = self.server.client(client_name)
            # We need the actual media object to play
            # plex_key is usually something like '/library/metadata/12345'
            # fetchItem expects the integer ID or the key
            item = self.server.fetchItem(plex_key)
            
            client.playMedia(item)
            return True
        except Exception as e:
            print(f"Error playing media: {e}")
            return False

    def get_history(self, limit=50, days=90):
        """Get watch history"""
        if not self.server:
            self._connect()
        
        try:
            # PlexAPI history doesn't strictly filter by days in the call usually, 
            # but we can filter the results or use advanced filters if supported.
            # For simplicity, we fetch recent history and filter.
            history_items = self.server.history(maxresults=limit*2) # Fetch more to allow filtering
            
            cutoff_date = datetime.now() - timedelta(days=days)
            
            results = []
            for item in history_items:
                if item.viewedAt < cutoff_date:
                    continue
                    
                if len(results) >= limit:
                    break
                
                # Check if it's a movie (or show if we support that later, requirements focus on "Library" which implies movies mostly based on examples, but History could be anything)
                # The prompt examples show "The Matrix", etc.
                
                results.append({
                    "title": item.title,
                    "watched_at": item.viewedAt.isoformat() if item.viewedAt else None,
                    # History items might not have full details populated depending on the object type
                    "genres": [g.tag for g in item.genres] if hasattr(item, 'genres') else [],
                    "rating": item.audienceRating if hasattr(item, 'audienceRating') else (item.rating if hasattr(item, 'rating') else None),
                    "type": item.type
                })
            
            return results
        except Exception as e:
            print(f"Error fetching history: {e}")
            return []
