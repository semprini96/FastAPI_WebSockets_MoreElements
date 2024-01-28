from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import asyncio
import uvicorn
import random
import json
import os
from json import JSONEncoder
import datetime
from datetime import timezone
from pydantic import BaseModel
import httpx


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    async def broadcast(self, message):
        for connection in self.active_connections:
            await connection.send_json(message)
    
    def remove(self, websocket: WebSocket):
        self.active_connections.remove(websocket)


class TestTableEntry:
    def __init__(self, bench_id, test_id, start_date, resets, sw_version, actions):
        self.bench_id = bench_id
        self.test_id = test_id
        self.start_date = start_date
        self.resets = resets
        self.sw_version = sw_version
        self.actions = actions


class TestTableEntryEncoder(JSONEncoder):
    def default(self, o):
        return o.__dict__


class APIData(BaseModel):
    fact: str = 'No fact yet'
    status: str = 'in_progress'


app = FastAPI()
templates = Jinja2Templates(directory='templates')
app.mount('/static', StaticFiles(directory='static'), name='static')
api_url = 'https://catfact.ninja/fact'
api_data = APIData()

control_manager = ConnectionManager()
data_manager = ConnectionManager()

test_list = []
test_list.append(TestTableEntry('test1', 1000, '2024-01-01 08:00:00', 0, 4200, 1000))
test_list.append(TestTableEntry('test2', 2000, '2024-01-02 08:00:00', 0, 4202, 930))
test_list.append(TestTableEntry('test3', 3000, '2024-01-02 10:30:00', 50, 4140, 775))
test_list.append(TestTableEntry('OtherDevice', 4000, '2024-01-02 20:00:00', 125, 1234, 16777216))

test_list_json = []

state_timestamp = datetime.datetime.now(timezone.utc).timestamp()
server_status = {'server_status': 'SERVER_OK', 'last_update': state_timestamp, 'fact': api_data.fact}

async def data_update():
    global test_list_json
    while True:
        tmp_json_list = []
        for test_entry in test_list:
            test_entry.actions += random.randint(1, 5)
            jsoned_test = json.dumps(test_entry, indent=4, cls=TestTableEntryEncoder)
            tmp_json_list.append(jsoned_test)
        test_list_json = tmp_json_list
        tmp_json_list = []
        await asyncio.sleep(15)


async def status_update():
    global server_status
    while True:
        state_timestamp = datetime.datetime.now(timezone.utc).timestamp()
        server_status['last_update'] = state_timestamp
        server_status['fact'] = api_data.fact
        await asyncio.sleep(10)


async def api_data_update():
    while True:
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(api_url)
                resp.raise_for_status()
                t_data = resp.text
                t_data = json.loads(t_data)['fact']
                api_data.fact = t_data
                api_data.status = 'completed'
            except httpx.HTTPError as exc:
                api_data.status = 'error'
        await asyncio.sleep(30)


@app.on_event('startup')
async def schedule_periodic():
    loop = asyncio.get_event_loop()
    loop.create_task(api_data_update())
    loop.create_task(status_update())
    loop.create_task(data_update())


@app.get('/')
def main(request: Request):
    return templates.TemplateResponse('index.html', {'request': request, 'data': test_list})


@app.get('/favicon.ico')
async def get_favicon():
    file_name = 'icons8-robot-96.ico'
    file_path = os.path.join(app.root_path, 'static', file_name)
    return FileResponse(path=file_path, headers={"Content-Disposition": "attachment; filename=" + file_name})


@app.websocket('/WSControl/{client_id}')
async def control_websocket_endpoint(websocket: WebSocket, client_id: str):
    print(f'Accepted CONTROL connection from client with ID={client_id}')
    await control_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
            await control_manager.broadcast(server_status)
    except (WebSocketDisconnect, ConnectionClosed):
        print(f'Disconnecting CONTROL client with ID={client_id}')
        control_manager.remove(websocket)


@app.websocket('/WSData/{client_id}')
async def data_websocket_endpoint(websocket: WebSocket, client_id: str):
    print(f'Accepted DATA connection from client with ID={client_id}')
    await data_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
            await data_manager.broadcast(test_list_json)
    except (WebSocketDisconnect, ConnectionClosed):
        print(f'Disconnecting DATA client with ID={client_id}')
        data_manager.remove(websocket)


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000)
