# test_wake.py
import numpy as np
import sounddevice as sd
from openwakeword.model import Model

RATE = 16000
CHUNK = 1280  # 80 ms

model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")

print(sd.query_devices())
print("Default input device:", sd.default.device)

def callback(indata, frames, time, status):
    if status:
        print(status)
    audio = indata[:, 0]
    vol = int(np.abs(audio).mean())
    for name, score in model.predict(audio).items():
        print(f"vol={vol:5d}  {name}: {score:.3f} {'#' * int(score * 40)}")

# অন্য মাইক বেছে নিতে চাইলে InputStream-এ device=<index> যোগ করো
with sd.InputStream(samplerate=RATE, channels=1, dtype="int16",
                    blocksize=CHUNK, callback=callback):
    input("'Hey Jarvis' বলো। থামাতে Enter চাপো.\n")
