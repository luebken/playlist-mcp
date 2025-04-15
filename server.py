import sys
import re
from datetime import datetime
import sqlite3

import anyio
import chromadb
import chromadb.api
from pytube import Playlist
from youtube_transcript_api import YouTubeTranscriptApi

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

def init_cache():
    conn = sqlite3.connect('transcripts.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS transcripts
        (video_id TEXT PRIMARY KEY,
         transcript TEXT,
         created_at TIMESTAMP)
    ''')
    conn.commit()
    conn.close()
    
def get_cached_transcript(video_id):
    conn = sqlite3.connect('transcripts.db')
    c = conn.cursor()
    c.execute('SELECT transcript FROM transcripts WHERE video_id = ?', (video_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def cache_transcript(video_id, transcript):
    conn = sqlite3.connect('transcripts.db')
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO transcripts (video_id, transcript, created_at)
        VALUES (?, ?, ?)
    ''', (video_id, transcript, datetime.now()))
    conn.commit()
    conn.close()

def get_video_ids(playlist):
    print(f"Get video ids for {playlist.title}")
    video_ids = []
    for url in playlist.video_urls:
        video_id = url.split("v=")[1].split("&")[0]
        video_ids.append(video_id)
    return video_ids

def fetch_transcripts(video_ids):
    init_cache()
    ytt_api = YouTubeTranscriptApi()
    video_tanscripts = []
    for video_id in video_ids:
        text = get_cached_transcript(video_id)
        if text is None:
            text = ""
            print(f"Fetching transcript for {video_id}")
            transcript = ytt_api.fetch(video_id, ["en", "es", "de", "fr", "hi", "sv", "lt"])
            for snippet in transcript:
                text += snippet.text
            cache_transcript(video_id, text)
        video_tanscripts.append(text)
    return video_tanscripts

def search_vector_db(collection, topic):
    query_result = collection.query(
        query_texts=[topic],
        n_results=20,
    )
    result = []
    for index, id in enumerate(query_result["ids"][0]):
        transcript = query_result["documents"][0][index]
        result.append({
            "Video Link": f"https://www.youtube.com/watch?v={id}",
            "Transcript": transcript
        })
    
    return result
    
    
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Error: Please provide a YouTube Playlist URL as an argument")
        sys.exit(1)
    playlist_url = sys.argv[1]    
    youtube_pattern = r'https?:\/\/(?:www\.)?youtube\.com\/playlist\?list=[\w-]+'
    if not re.match(youtube_pattern, playlist_url):
        print(f"Error: URL '{playlist_url}' is not a valid YouTube playlist URL")
        sys.exit(1)
    
    print(playlist_url)
    
    playlist = Playlist(playlist_url)
    title = playlist.title.lower().replace(' ', '_').replace('+', '-')
    
    try:
        description = playlist.description
    except KeyError:
        print("Can't find description. Using title.")
        description = playlist.title
        
    print(f"Description {description}")

    client = chromadb.PersistentClient(".")
    collection: chromadb.api.Collection
    try:
        collection = client.get_collection(title)
        print(f"Collection '{title}' found.")
    except chromadb.errors.NotFoundError as e:
        print(f"Collection '{title}' not found: {str(e)}")
        video_ids = get_video_ids(playlist)
        video_tanscripts = fetch_transcripts(video_ids)
        collection = client.create_collection(title)
        print("Adding transcripts to vector db")
        collection.add(
            documents=video_tanscripts,
            ids=video_ids
        )
    mcp = Server("Playlist MCP")

    @mcp.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=f"fetch_transcripts_{title}",
                description=f"Fetch transcripts for a specific topic of: {description}",
                inputSchema={
                    "type": "object",
                    "required": ["topic"],
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "The topic to search for",
                        }
                    },
                },
            )
        ]
    @mcp.call_tool()
    async def call_tool(
        name: str, arguments: dict
    ) -> list[types.TextContent]:
        results = search_vector_db(collection, arguments["topic"])
        return [types.TextContent(type="text", text=str(results))]
    
    print("Starting MCP server")
    async def arun():
        async with stdio_server() as streams:
            await mcp.run(
                streams[0], streams[1], mcp.create_initialization_options()
            )
    anyio.run(arun)

