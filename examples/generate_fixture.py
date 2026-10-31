"""Generate a synthetic local test tone; never overwrites an existing file."""
import math, struct, wave
from pathlib import Path

out = Path(__file__).resolve().parent / 'fixture.wav'
if out.exists():
    raise SystemExit('fixture.wav exists; refusing overwrite')
with wave.open(str(out), 'wb') as wav:
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(16000)
    wav.writeframes(b''.join(struct.pack('<h', int(10000 * math.sin(2 * math.pi * 440 * i / 16000))) for i in range(16000)))
print(out)
