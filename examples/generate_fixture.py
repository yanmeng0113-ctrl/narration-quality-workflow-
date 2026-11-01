"""Generate a synthetic local test tone; never overwrites an existing file."""
import argparse, math, struct, wave
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--output', default='workdir/fixture.wav')
args = parser.parse_args()
out = Path(args.output).resolve()
out.parent.mkdir(parents=True, exist_ok=True)
if out.exists():
    raise SystemExit('fixture.wav exists; refusing overwrite')
with wave.open(str(out), 'wb') as wav:
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(16000)
    wav.writeframes(b''.join(struct.pack('<h', int(10000 * math.sin(2 * math.pi * 440 * i / 16000))) for i in range(16000)))
print(out)

