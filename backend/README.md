# Plex Concierge Backend

This is the backend service for the Plex Concierge application. It provides a RESTful API to interact with a Plex Media Server, allowing for advanced searching, recommendations based on mood and history, and playback control.

## Features

- **Advanced Search**: Filter movies by genre, mood, actor, director, year/decade, runtime, and rating.
- **Mood-Based Recommendations**: curated movie suggestions based on emotional tone (defined in `config.yaml`).
- **AI-Enhanced Recommendations**: Suggestions based on watch history and user preferences.
- **Playback Control**: Initiate playback on specific Plex clients.
- **Library Statistics**: View insights into your movie library.

## Prerequisites

- Python 3.9+
- A running Plex Media Server
- Plex Token (X-Plex-Token)

## Installation

1.  **Navigate to the backend directory:**
    ```bash
    cd backend
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Environment Setup:**
    Copy the template environment file and fill in your details:
    ```bash
    cp .env.template .env
    ```
    
    Edit `.env` with your configuration:
    - `PLEX_URL`: The URL of your Plex server (e.g., `http://192.168.1.100:32400`)
    - `PLEX_TOKEN`: Your Plex authentication token
    - `API_KEY`: A secure key for this API (clients must provide this)
    - `LIBRARY_NAME`: The name of your movie library (default: "Movies")
    - `CACHE_TTL`: Cache duration in seconds (default: 300)

4.  **Configuration:**
    The `config.yaml` file contains mood mappings. You can customize which genres and constraints correspond to specific moods (e.g., "uplifting", "dark", "cozy").

## Running the Service

### Local Development
```bash
python app.py
```
The server will start on `http://0.0.0.0:5000` (or the PORT defined in .env).

### Docker
```bash
docker-compose up --build
```

## API Documentation

All endpoints require authentication via the `X-API-KEY` header or `api_key` query parameter.

### 1. Search Library
**GET** `/search`

Search and filter movies.

**Parameters:**
- `genre` (string): Filter by genre (e.g., "Action").
- `mood` (string): Filter by mood defined in `config.yaml` (e.g., "uplifting").
- `actor` (string): Filter by actor name (partial match supported).
- `director` (string): Filter by director name.
- `year_start` (int): Minimum release year.
- `year_end` (int): Maximum release year.
- `decade` (string): Decade shortcut (e.g., "1990s").
- `runtime_max` (int): Maximum runtime in minutes.
- `runtime_min` (int): Minimum runtime in minutes.
- `rating_min` (float): Minimum audience rating (0-10).
- `unwatched_only` (bool): If true, only return unwatched movies (default: true).
- `limit` (int): Max results to return (default: 5).
- `sort` (string): Sort order (`random`, `rating`, `recent`, `oldest`).

**Example:**
```
GET /search?genre=Comedy&actor=Keanu&decade=2000s&limit=3
```

### 2. Get Recommendations
**GET** `/recommend`

Get personalized recommendations based on watch history and optional mood.

**Parameters:**
- `mood` (string): Optional mood filter.
- `count` (int): Number of recommendations (default: 5).

### 3. Start Playback
**POST** `/play`

Initiate playback on a device.

**Body (JSON):**
```json
{
  "title": "Movie Title",
  "client": "Living Room TV",
  "plex_key": "/library/metadata/12345"
}
```

### 4. List Clients
**GET** `/clients`

Returns a list of available Plex players/clients.

### 5. Watch History
**GET** `/history`

Get recent watch history.

**Parameters:**
- `limit` (int): Number of items (default: 50).
- `days` (int): Lookback period in days (default: 90).

### 6. Library Stats
**GET** `/library-stats`

Returns general statistics about the library (total movies, unwatched count, available genres, etc.).