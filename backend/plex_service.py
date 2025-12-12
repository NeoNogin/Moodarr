import os
import time
from datetime import datetime, timedelta
from plexapi.server import PlexServer
from plexapi.client import PlexClient
from plexapi.myplex import MyPlexAccount
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
        self.account = None
        self.library_section = None
        
        # Initialize cache with TTL
        self.cache = TTLCache(maxsize=1, ttl=self.cache_ttl)
        
        self._connect()

    def _connect(self):
        """Establish connection to Plex Server and MyPlex"""
        if not self.plex_url or not self.plex_token:
            print("Warning: PLEX_URL or PLEX_TOKEN not set.")
            return

        try:
            # 1. Connect to Direct Server
            self.server = PlexServer(self.plex_url, self.plex_token)
            print(f"Connected to Plex Server: {self.server.friendlyName}")
            self.library_section = self.server.library.section(self.library_name)
            
            # 2. Connect to MyPlex (Critical for Docker client discovery)
            self.account = MyPlexAccount(token=self.plex_token)
            print(f"Connected to MyPlex Account: {self.account.username}")
            
        except Exception as e:
            print(f"Failed to connect to Plex: {e}")
            # Don't set server to None immediately if just one fails, but usually both share creds
            if not self.server:
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
        """Get available clients using Resources API (Cloud) + Local Discovery"""
        if not self.server:
            self._connect()
        
        combined_clients = {} # Use dict to dedup by machineIdentifier

        try:
            print("Fetching clients...")
            
            # 1. Resources API (Cloud/Remote/Docker-friendly)
            # This is the most reliable way to find 'online' clients
            if self.account:
                try:
                    resources = self.account.resources()
                    for r in resources:
                        if 'player' in r.provides:
                            # We don't connect yet, just list them. Connection is expensive.
                            # We map Resource object to a simple dict structure or keep it wrapped
                            print(f"Found Resource: {r.name} ({r.product}) - Presence: {r.presence}")
                            combined_clients[r.clientIdentifier] = r
                except Exception as e:
                    print(f"Error fetching resources: {e}")

            # 2. Standard Local Discovery (GDM)
            # Good if on Host Networking
            try:
                clients = self.server.clients()
                print(f"Standard clients found: {len(clients)}")
                for c in clients:
                    combined_clients[c.machineIdentifier] = c
            except Exception as e:
                print(f"Error with standard discovery: {e}")
            
            # 3. Active Sessions
            # Good for currently playing devices
            try:
                sessions = self.server.sessions()
                print(f"Active sessions found: {len(sessions)}")
                for session in sessions:
                    players = []
                    if hasattr(session, 'players'):
                        players = session.players
                    elif hasattr(session, 'player'):
                        players = [session.player]
                    
                    for p in players:
                        print(f"Found Session Player: {p.title}")
                        # Session players might not have machineIdentifier easily accessible or matching resource
                        # We use it if we haven't found a better resource yet
                        if p.machineIdentifier not in combined_clients:
                            combined_clients[p.machineIdentifier] = p
            except Exception as e:
                print(f"Error with sessions: {e}")

            # Convert to list
            return list(combined_clients.values())

        except Exception as e:
            print(f"Error fetching clients: {e}")
            return []

    def play_media(self, client_name, plex_key):
        """Play media on a specific client with robust discovery"""
        if not self.server:
            self._connect()
        
        try:
            target_client = None
            
            # Strategy 1: Check Resources (Best for Docker/Remote)
            if self.account:
                print(f"Searching Resources for '{client_name}'...")
                resources = self.account.resources()
                for r in resources:
                    if 'player' in r.provides:
                        # Match by Name, Product, or Device (Safely handle None)
                        r_name = r.name.lower() if r.name else ''
                        r_product = r.product.lower() if r.product else ''
                        r_device = r.device.lower() if r.device else ''
                        
                        if client_name.lower() in [r_name, r_product, r_device]:
                            print(f"Found Resource match: {r.name}. Attempting connection...")
                            try:
                                # connect() tries local, remote, and relay connections automatically
                                target_client = r.connect(timeout=3)
                                if target_client:
                                    print(f"Connected to client via Resource: {target_client.url}")
                                    break
                            except Exception as e:
                                print(f"Failed to connect to resource {r.name}: {e}")
            
            # Strategy 2: Check Standard Clients (GDM)
            if not target_client:
                try:
                    target_client = self.server.client(client_name)
                    print(f"Found Client via GDM: {target_client.title}")
                except:
                    pass

            # Strategy 3: Check Active Sessions
            if not target_client:
                print(f"Checking sessions for '{client_name}'...")
                for session in self.server.sessions():
                    players = []
                    if hasattr(session, 'players'):
                        players = session.players
                    elif hasattr(session, 'player'):
                        players = [session.player]
                        
                    for p in players:
                        p_title = p.title.lower() if p.title else ''
                        p_product = p.product.lower() if p.product else ''
                        p_device = p.device.lower() if p.device else ''

                        if client_name.lower() in [p_title, p_product, p_device]:
                            target_client = p
                            print(f"Found Client via Session: {p.title}")
                            
                            # Session clients often lack baseurl.
                            # 1. Try manual direct connection (Android default port 32500)
                            if not getattr(target_client, 'baseurl', None) and target_client.address:
                                print(f"Client has IP {target_client.address} but no BaseURL. Trying direct connection on port 32500...")
                                # Manually patch the existing object to avoid re-instantiation crash
                                base_url = f"http://{target_client.address}:32500"
                                target_client.baseurl = base_url
                                target_client._baseurl = base_url # Some versions use this
                                target_client.proxyThroughServer(False) # Disable proxy to force direct
                                target_client.token = self.plex_token # Ensure token is set
                                print(f"Manually patched client baseurl to {base_url}")

                            # 2. Fallback to Proxy if still no baseurl
                            # For now, let's trust the manual set. If it fails, playMedia might throw.
                            
                            if not getattr(target_client, 'baseurl', None):
                                print("Session client still missing baseurl, attempting to proxy...")
                                target_client.proxyThroughServer()
                            break
                    if target_client: break

            if not target_client:
                print(f"Error: Client '{client_name}' could not be found or connected.")
                return False

            # Play Command
            print(f"Sending play command to {target_client.title}...")
            item = self.server.fetchItem(plex_key)
            try:
                target_client.playMedia(item)
                return True
            except Exception as e:
                print(f"Error executing playMedia: {e}")
                if "404" in str(e):
                    print("NOTE: 404 Error suggests the client is refusing control.")
                    print("ACTION REQUIRED: Ensure 'Advertise as player' is ENABLED in the Plex App settings on the device.")
                return False

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
