import cv2
import google.generativeai as genai

import typing_extensions as typing
import base64
import json
import time
import requests
import signal
import sys
from dataclasses import dataclass

@dataclass
class ScoreboardReading:
    home_score: int
    home_foul: int
    away_score: int
    away_foul: int
    period: int
    minutes: int
    seconds: int

model = genai.GenerativeModel(
    "gemini-1.5-flash",
    system_instruction='''You are reading image of a scoreboard for a basketball game to extract data from it, including:
    home team score
    home team number of fouls
    away team score
    away team number of fouls
    game period,
    minutes and seconds on the game clock,
    be careful, the game clock has two parts, the minute and second, time will be counting down,
    but during the last minute of the game, the minute part will become the second, while the second part becomes tenth of second,
    Set field to zero value if you can't recognize any.'''
)
config = genai.GenerationConfig(response_mime_type="application/json", response_schema=ScoreboardReading, temperature=0)

cap = cv2.VideoCapture(0)
print(f"frame width {cap.get(cv2.CAP_PROP_FRAME_WIDTH)} height {cap.get(cv2.CAP_PROP_FRAME_HEIGHT)} fps {cap.get(cv2.CAP_PROP_FPS)}")

def signal_handler(sig, frame):
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

def run_vision(frame):

    # scale down to 786 pixel in height as it's expected by Gemini
    height, width, _ = frame.shape
    aspect_ratio = width / float(height)
    new_width = int(786 * aspect_ratio)
    frame = cv2.resize(frame, (new_width, 786))

    # convert from BGR to RGB
    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    _, jpg = cv2.imencode(".jpg", frame)
    response = model.generate_content([
        {'mime_type': 'image/jpeg', 'data': base64.b64encode(jpg.tobytes()).decode('utf-8')},
        "extract data from this image"
    ], generation_config=config)
    print(f"model response: {response.text}")

    data_dict = json.loads(response.text)
    return ScoreboardReading(**data_dict)

def cleanup(new: ScoreboardReading, old: ScoreboardReading):
        if abs(new.away_score - old.away_score) > 3:
            new.away_score = old.away_score
        if abs(new.home_score - old.home_score) > 3:
            new.home_score = old.home_score
        if abs(new.home_foul - old.home_foul) > 1:
            new.home_foul = old.home_foul
        if abs(new.away_foul - old.away_foul) > 1:
            new.away_foul = old.away_foul
        if abs(new.period - old.period) > 1:
            new.period = old.period

        if is_last_minute:
            new.seconds = new.minutes
            new.minutes = 0
            return new.minutes == 0 and new.seconds == 0
        else:
            return old.minutes == 1 and new.minutes > 8

last_reading = ScoreboardReading(home_foul=0, home_score=0, away_foul=0, away_score=0, period=0, minutes=0, seconds=0)
is_clock_running = False
is_last_minute = False
uno_control_url = 'https://app.overlays.uno/apiv2/controlapps/6XfLW0GSrlU20FtxwyIL0h/api'
headers = {'Content-Type': 'application/json'}
while True:
    start = time.time()
    result, frame = cap.read()
    if not result:
        break

    current_reading = run_vision(frame)
    is_last_minute = cleanup(current_reading, last_reading)

    if current_reading.minutes == last_reading.minutes and current_reading.seconds == last_reading.seconds:
        if is_clock_running == True:
            #update the clock value and reset
            uno_content={}
            uno_content["Game Clock Minutes"]=current_reading.minutes
            uno_content["Game Clock Seconds"]=current_reading.seconds
            data = {
                "command": "SetOverlayContent",
                "id": "e30a3d91-6ab2-47a5-aa38-500ef2c5fbfc",
                "content": uno_content
            }
            print(f"update clock to {current_reading.minutes}:{current_reading.seconds}")
            resp = requests.put(uno_control_url, headers=headers, json=data)
            print(resp.status_code)
            data = {
                "command": "ExecuteOverlayContentField",
                "id": "e30a3d91-6ab2-47a5-aa38-500ef2c5fbfc",
                "fieldId":"Game Clock",
                "value":"reset"
            }
            print(f"reset clock")
            resp = requests.put(uno_control_url, headers=headers, json=data)
            print(resp.status_code)
            is_clock_running = False
    elif is_clock_running == False:
        #update the clock, reset and play it
        uno_content={}
        uno_content["Game Clock Minutes"]=current_reading.minutes
        uno_content["Game Clock Seconds"]=current_reading.seconds
        data = {
            "command": "SetOverlayContent",
            "id": "e30a3d91-6ab2-47a5-aa38-500ef2c5fbfc",
            "content": uno_content
        }
        print(f"update clock to {current_reading.minutes}:{current_reading.seconds}")
        resp = requests.put(uno_control_url, headers=headers, json=data)
        print(resp.status_code)
        data = {
            "command": "ExecuteOverlayContentField",
            "id": "e30a3d91-6ab2-47a5-aa38-500ef2c5fbfc",
            "fieldId":"Game Clock",
            "value":"reset"
        }
        print(f"reset clock")
        resp = requests.put(uno_control_url, headers=headers, json=data)
        print(resp.status_code)
        data = {
            "command": "ExecuteOverlayContentField",
            "id": "e30a3d91-6ab2-47a5-aa38-500ef2c5fbfc",
            "fieldId":"Game Clock",
            "value":"play"
        }
        print(f"play clock")
        resp = requests.put(uno_control_url, headers=headers, json=data)
        print(resp.status_code)
        is_clock_running = True
    
    last_reading.minutes = current_reading.minutes
    last_reading.seconds = current_reading.seconds

    if current_reading == last_reading:
        print("no need to update scoreboard overlay")
        continue

    uno_content = {}
    uno_content["t1Score"]=current_reading.away_score
    uno_content["t2Score"]=current_reading.home_score
    uno_content["t1Fouls"]=f"{current_reading.away_foul}" if current_reading.away_foul < 5 else f"Bonus, {current_reading.away_foul}"
    uno_content["t2Fouls"]=f"{current_reading.home_foul}" if current_reading.home_foul < 5 else f"Bonus, {current_reading.home_foul}"
    uno_content["gameState"]=current_reading.period
    print(uno_content)
    data = {
        "command": "SetOverlayContent",
        "id": "e30a3d91-6ab2-47a5-aa38-500ef2c5fbfc",
        "content": uno_content
    }
    print("update non-clock values")
    resp = requests.put(uno_control_url, headers=headers, json=data)
    print(resp.status_code)

    last_reading = current_reading
    time_to_sleep = 1 - (time.time() - start)
    if time_to_sleep > 0:
        time.sleep(time_to_sleep)