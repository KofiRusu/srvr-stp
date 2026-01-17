#!/usr/bin/env python3
"""
ChatOS Data API - Streams live market data to remote clients (Mac).
Provides REST endpoints and WebSocket streaming from Redis pub/sub.
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('DataAPI')

try:
    import redis.asyncio as redis
    import asyncpg
except ImportError as e:
    logger.error(f"Missing dependency: {e}")

REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379')
POSTGRES_URL = os.environ.get('POSTGRES_URL', 'postgresql://chatos:chatos@localhost:5432/chatos_trading')
API_KEY = os.environ.get('API_KEY', 'chatos_api_key_change_me')

redis_client: Optional[redis.Redis] = None
pg_pool: Optional[asyncpg.Pool] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, pg_pool
    redis_client = redis.from_url(REDIS_URL)
    pg_pool = await asyncpg.create_pool(POSTGRES_URL, min_size=2, max_size=10)
    logger.info("Connected to Redis and PostgreSQL")
    yield
    if redis_client:
        await redis_client.close()
    if pg_pool:
        await pg_pool.close()


app = FastAPI(
    title="ChatOS Data API",
    description="Real-time market data streaming for ChatOS clients",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key


class LatestData(BaseModel):
    symbol: str
    data: dict
    timestamp: str


@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/latest/{data_type}/{symbol}", response_model=LatestData)
async def get_latest(data_type: str, symbol: str, api_key: str = Depends(verify_api_key)):
    """Get latest data for a symbol (trades, funding, oi, depth)"""
    key = f"latest:{data_type}:{symbol}"
    data = await redis_client.get(key)
    if not data:
        raise HTTPException(status_code=404, detail=f"No data for {data_type}:{symbol}")
    return LatestData(
        symbol=symbol,
        data=json.loads(data),
        timestamp=datetime.now(timezone.utc).isoformat()
    )


@app.get("/api/symbols")
async def get_symbols(api_key: str = Depends(verify_api_key)):
    """List all available symbols with data"""
    keys = await redis_client.keys("latest:*")
    symbols = set()
    for key in keys:
        parts = key.decode().split(':')
        if len(parts) >= 3:
            symbols.add(parts[2])
    return {"symbols": sorted(list(symbols))}


@app.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket):
    """WebSocket endpoint for real-time data streaming"""
    await websocket.accept()
    
    api_key = websocket.query_params.get('api_key', '')
    if api_key != API_KEY:
        await websocket.close(code=4001, reason="Invalid API key")
        return
    
    channels = websocket.query_params.get('channels', 'trades:BTCUSDT').split(',')
    
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(*channels)
    
    logger.info(f"Client subscribed to: {channels}")
    
    try:
        async def receive_messages():
            try:
                while True:
                    msg = await websocket.receive_text()
                    data = json.loads(msg)
                    if data.get('type') == 'subscribe':
                        new_channels = data.get('channels', [])
                        await pubsub.subscribe(*new_channels)
                        logger.info(f"Added subscriptions: {new_channels}")
                    elif data.get('type') == 'unsubscribe':
                        rm_channels = data.get('channels', [])
                        await pubsub.unsubscribe(*rm_channels)
            except WebSocketDisconnect:
                pass
        
        async def send_messages():
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    await websocket.send_text(json.dumps({
                        'channel': message['channel'].decode() if isinstance(message['channel'], bytes) else message['channel'],
                        'data': json.loads(message['data'])
                    }))
        
        await asyncio.gather(receive_messages(), send_messages())
        
    except WebSocketDisconnect:
        logger.info("Client disconnected")
    finally:
        await pubsub.close()


@app.get("/api/history/{data_type}/{symbol}")
async def get_history(
    data_type: str,
    symbol: str,
    limit: int = 100,
    api_key: str = Depends(verify_api_key)
):
    """Get historical data from PostgreSQL"""
    table_map = {
        'trades': 'trade_history',
        'funding': 'funding_rates',
        'oi': 'open_interest',
        'depth': 'orderbook_snapshots'
    }
    
    table = table_map.get(data_type)
    if not table:
        raise HTTPException(status_code=400, detail=f"Unknown data type: {data_type}")
    
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM {table} WHERE symbol = $1 ORDER BY timestamp DESC LIMIT $2",
            symbol, limit
        )
        return {"symbol": symbol, "data": [dict(r) for r in rows]}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8080)
